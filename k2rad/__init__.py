"""
k2rad  –  LS-DYNA .k → OpenRadioss .rad converter.

Usage::

    from k2rad import convert
    result = convert("model.k")
    print(result.starter_path, result.engine_path)
    for w in result.warnings:
        print("WARNING:", w)
"""

from __future__ import annotations

__version__ = "0.1.0"

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from .parser import parse_k_file, PARSER_WARNINGS
from .handlers import dispatch
from .state import ConversionState, ContactAutoSingle, ConvertOptions
from .writer.common import AUTO_IMPLICIT_STUB_TITLE, SHELL_FORMULATIONS
from .writer import (build_starter, build_engine, _warn_implicit_solid_contact_np1,
                     _warn_deformable_deformable_contact,
                     deformable_deformable_inter_ids, _recipe_active)


def _inject_implicit_contact_stub(state: ConversionState) -> None:
    """Work around an OpenRadioss engine crash.

    The OpenRadioss implicit solver segfaults during setup (before
    ``IMPLICIT OPTION USED`` is even printed) when the model defines **no**
    contact interface — even though a part loaded only by boundary conditions
    or forces is a perfectly valid implicit problem.  A model *with* at least
    one ``/INTER`` runs fine.

    So when converting an implicit model that has no contact, inject one inert
    all-parts self-contact (``/INTER/TYPE7``).  On a model whose parts never
    touch it transmits no load, so results are unchanged — it merely gives the
    engine the interface its implicit setup requires.

    NOTE (W14 bogie root-cause refinement): the real trigger of the no-contact
    segfault appears to be the absence of a *rigid body*, not of contact — a
    contact-free implicit deck runs fine once it has one /RBODY (see
    writer._make_probe_rbody, which now injects an inert probe rigid body for
    any implicit deck without one). The decks that established this stub all
    had rigid bodies, so the stub is kept for non-modal decks as
    belt-and-braces until the rbody-only fix is validated on the QSTAT/NONLIN
    model class too.
    """
    if not state.is_implicit:
        return
    if state.is_modal:
        # Modal decks must NOT get the stub. It is not needed (the injected
        # probe rigid body alone fixes the implicit-init segfault) and it
        # actively pollutes the exported stiffness matrix: the interface's
        # initial-penetration corrections add "SUPPLEMENTARY CONTACT STIFFNESS"
        # terms that shifted the W14 bogie static response ~2x and its first
        # eigenfrequency 44.5 -> 24.7 Hz.
        return
    if state.contacts_single or state.contacts_surf2surf or state.contacts_general:
        return
    if state.contacts_tied or state.contacts_spotweld or state.contacts_tiebreak:
        # A tied, spot-welded or TIEBREAK deck already gets an /INTER (TYPE2).
        # contacts_tiebreak belongs in this guard, not the one above it: a
        # tiebreak's pre-failure state IS a tie, so the tied reasoning applies
        # to it verbatim. (Before #131 a tiebreak lived in contacts_surf2surf
        # and blocked the stub from the previous line; moving it to its own
        # container without this would have let an implicit tiebreak-only deck
        # collect the stub, with the parasitic stiffness the comment below
        # describes.) More
        # importantly, the all-parts TYPE7 self-contact stub would ENGAGE across
        # the tied gaps: tied nodes sit within half a shell thickness of their
        # main surface — inside the TYPE7 thickness-derived gap — so the "inert"
        # stub would add parasitic contact stiffness at every weld.
        return
    if not (state.solid_elems or state.shell_elems or state.tshell_elems):
        # No deformable surface to build the interface from. THICK SHELLS count:
        # they are /BRICK in the emitted deck and _make_master_surface gives
        # their part the same /SURF/PART/EXT a brick part gets, so an implicit
        # thick-shell deck — which every one of the r14 *ELEMENT_TSHELL decks
        # is — can and should have the stub. (Empty on any deck without
        # *ELEMENT_TSHELL, so no other conversion moves.)
        #
        # SPH particles do NOT count, and that is a verdict rather than an
        # omission: this stub is an all-parts /INTER/TYPE7 whose surface comes
        # from _make_master_surface, and a particle has no face to put in one.
        # Adding `or state.sph_elems` would inject an interface that
        # _make_master_surface then refuses to build and _drop_interface
        # immediately discards — noise, not a stabilization. A particles-only
        # implicit deck is outside what this stub can help with; it is also
        # outside what OpenRadioss SPH supports, and every SPH deck in the
        # corpus is explicit.
        return
    inter_id = state.next_id()
    state.contacts_single.append(
        ContactAutoSingle(
            inter_id=inter_id,
            title=AUTO_IMPLICIT_STUB_TITLE,
            ssid=0, sstyp=0, fs=0.0, fd=0.0, bt=0.0, dt=1.0e28,
            # The stub takes the ORDINARY ignore -> Inacti mapping, i.e.
            # Inacti = 5 (variable gap, no t = 0 pre-load). A previous round
            # stated Inacti = 1 here to dodge starter ERROR 611 on
            # 05_1_welding_solid's conformal weld mesh; that was MEASURED to be
            # the wrong lever, because Inacti = 1 zeroes the stiffness of EVERY
            # initially penetrating secondary node for the whole run, not just
            # the ones that cannot be depenetrated. On
            # `efg/metal-cutting/main.k` — an implicit deck whose only contact
            # is this stub — Inacti = 1 turned a NORMAL TERMINATION (218 cycles,
            # t = 0.03 of 0.03) into a TIMESTEP-LIMIT death at t = 0.0084, and
            # putting Inacti back to 5 restored the 218-cycle run exactly.
            # ERROR 611 is cleared by the Fpenmax cell that
            # writer/contacts._emit_inter_type7 derives from Inacti (measured on
            # 05_1_welding_solid: stub Inacti = 5 + Fpenmax = 0.999999 gives
            # 0 ERRORS / 1 WARNING and deactivates 355 nodes against its 310
            # zero-normal ones).
        )
    )
    state.warn(
        "Implicit model has no contact interface — the OpenRadioss engine "
        "segfaults in implicit setup without one. Injected an inert all-parts "
        f"self-contact (/INTER/TYPE7 id {inter_id}) with the ordinary Inacti=5 "
        "(variable gap: an initially touching node gets a gap reduced to its "
        "own penetration, so the stub carries no load at t=0) plus "
        "Fpenmax=0.999999, which "
        "deactivates only a node lying EXACTLY on a main segment — i7pwr3.F:118 "
        "refuses such a node with ERROR 611 for every Inacti except 1 and 2 "
        "unless Fpenmax is set (measured, 310 of them on 05_1_welding_solid's "
        "conformal weld mesh). Inacti=1 was tried and rejected: it zeroes every "
        "penetrating node's stiffness and cost efg/metal-cutting its NORMAL "
        "TERMINATION. What the stub does AFTER t=0 depends on the mesh, "
        "measured on a two-block implicit coupon: with a 0.5 mm physical gap "
        "(0 nodes deactivated) it resists further interpenetration (I-ENERGY "
        "1.636E+05 with the block, 4.469 without); on COINCIDENT non-merged "
        "faces (24 nodes deactivated by Fpenmax) it is fully inert — the run "
        "is identical to one with the whole /INTER/TYPE7 block deleted, "
        "I-ENERGY = EXT-WORK matching at every cycle. Fpenmax buys the "
        "refusal-free start by removing the resistance on exactly the meshes "
        "that need Fpenmax. Remove the interface if you define real contact."
    )


@dataclass
class ConversionResult:
    starter_path: str
    engine_path: str
    warnings: List[str]
    skipped_keywords: List[str]
    log_path: Optional[str] = None   # path of the auto-saved warning log (if any)
    # (keyword, reason) for keywords that were recognized — they have a handler,
    # so they are NOT in skipped_keywords — but produced no card in either deck.
    recognized_not_emitted: List[Tuple[str, str]] = field(default_factory=list)


def _write_conversion_log(output_stem: str, input_path: str,
                          state: ConversionState) -> Optional[str]:
    """Save the conversion's warnings + skipped keywords to ``<stem>_conversion.log``
    so they survive for later investigation (the console scrolls them away on a
    large deck).  Written only when there is something to record; returns the log
    path, or ``None`` if there were no warnings/skips."""
    if not (state.warnings or state.skipped_keywords
            or state.recognized_not_emitted):
        return None
    from datetime import datetime
    log_path = output_stem + "_conversion.log"
    skipped = sorted(set(state.skipped_keywords))
    not_emitted = sorted(state.recognized_not_emitted)
    lines = [
        "k2rad conversion log",
        f"  generated : {datetime.now().isoformat(timespec='seconds')}",
        f"  input     : {input_path}",
        f"  output    : {output_stem}_0000.rad / _0001.rad",
        f"  warnings  : {len(state.warnings)}",
        f"  skipped   : {len(skipped)} unsupported keyword(s)",
        f"  not emitted: {len(not_emitted)} recognized keyword(s) that "
        "produced no card",
        "",
    ]
    if skipped:
        lines.append(f"Skipped (unsupported) keywords ({len(skipped)}):")
        lines.extend(f"  *{kw}" for kw in skipped)
        lines.append("")
    if not_emitted:
        # These have a handler, so they never reach skipped_keywords — without
        # this section "skipped: 0" would read as "everything was converted".
        lines.append(
            f"Recognized but not emitted ({len(not_emitted)}) — the keyword was "
            "parsed and did NOT count as skipped, but no card was written for "
            "it:")
        for kw, reason in not_emitted:
            lines.append(f"  *{kw}: {reason}")
        lines.append("")
    if state.warnings:
        lines.append(f"Warnings ({len(state.warnings)}):")
        lines.extend(f"  {w}" for w in state.warnings)
        lines.append("")
    try:
        with open(log_path, "w", newline="\n", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    except OSError:
        return None
    return log_path


def convert(
    input_path: str,
    output_stem: Optional[str] = None,
    units: tuple = ("Mg", "mm", "s"),
    *,
    ground_springs: bool = False,
    ground_spring_k: float = 100.0,
    inter_gapmin: Optional[Dict[int, float]] = None,
    soften_stfac: Optional[float] = None,
    tie_stfac: Optional[Union[str, float]] = None,
    tet10_to_tet4: bool = False,
    auto_gapmin: bool = False,
    gapmin_factor: float = 0.8,
    derived_gapmin: bool = False,
    derived_gapmin_factor: float = 0.005,
    rigid_secondary_swap: bool = True,
    deformable_to_rigid: bool = True,
    fixpoint_count: int = 0,
    qstat_dtscal: Union[str, float] = 10.0,
    arclength_riks: bool = False,
    discrete_offset: bool = True,
    spring_token_mass_compensation: bool = True,
    shell_to_solid_rbody: bool = True,
    generalized_weld_butt: bool = True,
    tgmult_imptemp: bool = True,
    deformable_contact_recipe: bool = False,
    emit_eig: bool = False,
    blast_ground: str = "auto",
    rigid_cog_master: bool = True,
    zero_density_floor: bool = True,
    law106_shell_restate: bool = True,
    zero_t0_sentinel: bool = True,
    node_tc_rc_bcs: bool = True,
    default_hourglass: bool = True,
    assumed_strain_isolid: str = "none",
    implicit_rigid_secondary_swap: bool = False,
    mass_weighted_inivel: bool = False,
    write_restart: bool = False,
    ams: bool = False,
    shell_formulation: str = "qbat",
    dt_del: Optional[float] = None,
    he_bunreacted: Optional[float] = None,
    ale_multimat_law51: bool = False,
    eroding_surf_ext: bool = False,
    airbag_particle_uniform: bool = False,
    progress: Optional[Callable[[float, str], None]] = None,
    write_log: bool = True,
) -> ConversionResult:
    """Convert a LS-DYNA .k file to OpenRadioss Starter + Engine .rad files.

    Parameters
    ----------
    input_path : str
        Path to the LS-DYNA keyword file (.k).
    output_stem : str, optional
        Base path for output files (without ``_0000.rad`` / ``_0001.rad``).
        Defaults to *input_path* with the extension removed.
    units : tuple of (mass, length, time)
        Unit strings written to the /BEGIN header.  Defaults to the LS-DYNA
        ton-mm-s system ("Mg", "mm", "s").  This only labels the header — the
        converter never rescales numeric values, so the labels should match
        the units already used in the .k file.

    Other Parameters
    ----------------
    ground_springs : bool
        Inject soft /PROP/TYPE8 grounding springs on every force-loaded rigid
        body to bootstrap the singular t=0 tangent of force control through a
        clearance-fit contact. Off by default.
    ground_spring_k : float
        Grounding-spring stiffness (N/mm) per loaded axis. Default 100.
    inter_gapmin : dict[int, float], optional
        Per-interface Gapmin overrides ``{inter_id: gapmin}`` applied to the
        emitted /INTER/TYPE7 (drops a pulled interface's pre-penetration).
    soften_stfac : float, optional
        Stfac (penalty stiffness scale) set on ALL /INTER/TYPE7 interfaces
        (e.g. 0.3). None leaves the engine default (0).
    tie_stfac : float or ``"auto"``, optional
        STFAC (penalty-tie stiffness scale) on every ``/INTER/TYPE10``
        tie. ``"auto"`` asks for 100x the local element stiffness, i.e.
        ``100*3(1-2nu)`` read from the tie's own main side (120 at
        nu = 0.3). None (the default) leaves STFAC 0, which the starter
        turns into Radioss's own 0.2 — MEASURED on a determinate two-hex
        coupon that is a -67.6 % tie, because ``i7sti3.F:444`` makes the
        tie spring ``STFAC/(3(1-2nu))`` times the stiffness of the element
        it welds (0.167x at the default). STFAC 30 reaches -0.76 % and 120
        reaches +0.05 %, at dt x 0.115 and dt x 0.058 (dt scales as
        ``1/sqrt(STFAC)``). Only IMPLICIT ties and ties whose secondary
        side is entirely rigid use ``/INTER/TYPE10``; an explicit tie gets
        ``/INTER/TYPE2``, which reproduces the same coupon exactly at no
        time-step cost.
    tet10_to_tet4 : bool
        Downgrade every 10-node quadratic tet to a 4-node linear tet (keep the
        4 corners, drop the mid-edge nodes). Off by default.
    auto_gapmin : bool
        Derive each surface-to-surface interface's /INTER/TYPE7 Gapmin from the
        minimum node-to-node clearance between its two parts (Gapmin =
        ``gapmin_factor`` × clearance) instead of hand-tuning *CONTACT Card-3
        SST/SBST per mesh. Any explicit ``inter_gapmin`` entry still wins. Off
        by default. See :mod:`k2rad.gapmin`.
    gapmin_factor : float
        Fraction of the measured clearance used as the suggested Gapmin (default
        0.8). <1 keeps the gap below the clearance (0 initial penetration);
        near 1 still engages promptly.
    derived_gapmin : bool
        Write an explicit Gapmin on every ``/INTER/TYPE7`` whose MAIN surface is
        SOLID segments only and whose Gapmin would otherwise be 0 — the
        population where the starter derives ``0.1 ×`` the smallest main-surface
        segment side itself (``i7sti3.F:1055-1063``) while LS-DYNA's own offset
        on a solid segment is ZERO unless ``SLDTHK > 0`` is stated (Vol I R17
        p.11-101/103). **Off by default**, with a default-ON warning naming the
        derived value on every carrier. MEASURED on ``twobar`` (10 mm bars,
        derived ``GAP MIN`` 1.0): the starter's gap costs +1151 % internal
        energy against the LS-DYNA reference 3036.17 where this rule writes
        ``0.005 × 10 = 0.05`` and reads −5.60 %; but the same factor degrades
        other carriers (``sphere1``, where it writes 0.02921 and internal
        energy goes −1.66 % → −7.77 % at 4.1× the cycles; ``bend``,
        −2.0038 % → −2.8418 % at 4.69×). Of the class's 15 interfaces on the
        356-key R14 roster **7 now have a measured arm and 8 are still
        unjudgeable**, and the 7 disagree: 1 better, 3 worse, 2 byte-inert
        (``pend.imp``, ``06_heating_plate``) and 1 mixed
        (``4.3_General_Nonlinearity``, whose energy error improves −99.9 % →
        −55.2 % while its internal energy gets worse −98.87 % → −99.92 %) —
        which is why it is opt-in. A press-fit
        ``*CONTACT_*_INTERFERENCE`` and k2rad's own injected implicit
        stabilization stub are excluded.
    derived_gapmin_factor : float
        Fraction of the smallest main-surface segment side used by
        ``derived_gapmin`` (default 0.005 — measured; 0.01 reads +14.45 % on
        ``twobar`` and must not be used).
    rigid_secondary_swap : bool
        On an EXPLICIT deck, rescue a ``*CONTACT`` whose SECONDARY (SSID) side
        is WHOLLY RIGID instead of losing the whole interface: the roles are
        swapped when the MSID side carries deformable nodes, and the rigid
        secondary group is kept when BOTH sides are wholly rigid. **On by
        default.** ``/INTER/TYPE7`` is an asymmetric node-to-segment contact, so
        the deformable side must supply the tracked nodes. MEASURED:
        ``sphere1`` internal energy 0 (−100 %) → 77 830 (−1.66 %) against the
        LS-DYNA reference 79 147.3; ``EXP_SC_CONTACT_INTERFERENCE`` −100 % →
        −42.8 %; ``boundary_prescribed_motion.blow-mold`` from a diverging
        241 934-cycle run at t = 0.0061 of 0.015 to NORMAL TERMINATION at
        t = 0.015 in 25 675 cycles. IMPLICIT decks keep the drop either way.
    deformable_to_rigid : bool
        Honour ``*DEFORMABLE_TO_RIGID`` (the plain spelling): the named part is
        rigid FROM ``t = 0`` and is emitted as an ``/RBODY`` through the same
        path a ``*MAT_RIGID`` part takes, keeping its own material (Vol I R17
        p.18-1). **On by default.** MEASURED on ``pend.imp``: the deck's energy
        error goes 99.9 % → −0.0 % (internal energy 5.162e5 → 5.901e-06 against
        the LS-DYNA reference 5.03545e-06) in 9 480 cycles where LS-DYNA takes
        9 479.
    fixpoint_count : int
        Number of evenly spaced /IMPL/DT/FIXPOINT milestones the implicit
        time-step controller is forced to land on (k/N × the run end, for
        k = 1 … N), so an animation / time-history state is produced at each
        instead of wherever the variable step falls. The OpenRadioss engine caps
        the list at 100, so this is clamped to 1…100; 0 disables the card.
        **Default 0** — changed from 100 on 2026-09, because the grid makes
        the adaptive step oscillate against ``/IMPL/DT/2`` and trapezoidal
        Newmark is unconditionally stable at a CONSTANT step, not at one that
        alternates 2 : 1 every cycle. MEASURED on the dynaexamples R14 roster:
        ten decks that died ``** ERROR: SOLVER IMPLICIT STOPPED DUE TO
        TIMESTEP LIMIT **`` reach NORMAL TERMINATION without the card
        (``ex_01`` x3 at cycle 20, ``ex_14`` x4 at cycle 33, ``ex_15`` x3 at
        cycle 38); ``ex_01_thin_shell_elform_2`` goes from ERROR at
        ``t = 0.105`` to ``t = 1.000`` at IE −14.12 % against its LS-DYNA
        reference (the COMBINED arm — the −13.7 % this entry used to quote was
        measured before ``--qstat-dtscal 10`` reached the same deck), and
        ``ex_14_solid_elform_1`` from ERROR TERMINATION to
        NORMAL at cycle 33, engine energy error −0.7 % (the −3.1 % this entry
        used to quote is the ``--no-default-hourglass`` arm of the same deck,
        measured before the hourglass default reached it). Three
        currently-NORMAL implicit controls do not regress and
        two improve. A coarser grid is NOT the fix: at 10 points ``ex_14`` and
        ``ex_15`` terminate at a 99.9 % energy error. The cost of 0 is fewer
        output states (15 cycles become 8 on the controls) — set a count to
        get the milestones back. Implicit decks only.
    qstat_dtscal : str or float
        The ``/IMPL/QSTAT/DTSCAL`` inertia-stabilization scale written on a
        QUASI-STATIC implicit deck (one with no
        ``*CONTROL_IMPLICIT_DYNAMICS``); ``"none"`` emits no ``/IMPL/QSTAT``
        card at all. **Default 10** — changed from 0.1 on 2026-09. The
        stabilization added to the stiffness diagonal is
        ``M/((1+alpha)*beta*(DTSCAL*dt)^2)`` (``imp_dyna.F:351-355``), so it
        grows as ``1/DTSCAL^2`` AND as ``1/dt^2``: at 0.1 it was 100x the
        Radioss default (``SCAL_DTQ = 1``, ``freimpl.F:135``) and every
        auto-step cut stiffened the tangent further. LS-DYNA's standard static
        implicit adds none at all. MEASURED at nt 3 AND nt 4 against each
        deck's own LS-DYNA ``glstat``: ``4.2.frf.cant-1`` goes from 4 cycles
        (its pre-round CAMPAIGN ROW — a quiet-machine master repeat never
        leaves cycle 0; either way the arm advances nothing)
        and an ERROR to 104 cycles, ``t = 1.000``, IE 7922 against the
        reference 7946.31 (−0.31 %); ``tensile2`` +7.36 %;
        ``6.5.tbl.psd.prepressure-1`` +0.03 %; ``doorbeam`` NORMAL (its
        +380 % is a separate, named ``/INTER/TYPE25``-under-implicit drop, not
        a match). The cost is ``ex_02_thick_shell_elform_{2,3,5}`` — 3 deck
        keys on ONE emitted file, all three ``not_comparable`` BOTH WAYS —
        going ``normal`` → ``timeout``; ``--qstat-dtscal 0.1`` reproduces the
        pre-round-4 file byte for byte on that family. ``"none"``
        is measured WORSE than either (``ex_02`` dies at cycle 0, ``tensile2``
        at ``t = 0.746``). ``deformable_contact_recipe`` keeps its separately
        validated 0.05 and ignores this.
    arclength_riks : bool
        Emit ``/IMPL/DT/3`` (RIKS arc-length continuation) in place of
        ``/IMPL/DT/2`` when ``*CONTROL_IMPLICIT_SOLUTION`` asks for LS-DYNA's
        arc-length method — the manual's own rule (Vol I R17 p.12-354 and
        p.12-358): ``6 <= NSOLVR <= 9``, or ``NSOLVR = 12`` with card-3
        ``ARCMTH = 3``. ``ARCCTL`` is NOT part of the predicate — p.12-358
        defines it as the arc-length CONTROLLING NODE ID whose 0 means
        *"Generalized arc length method"*, and card 3 is ignored outright
        unless the method is already active. (An ``ARCCTL != 0`` clause
        shipped first and is retracted: it made ``ex_06_beam_elform_1`` a
        carrier, and that deck's own LS-DYNA ``d3hsp`` shows plain BFGS.)
        Roster reach: **2 keys**. **Off by default**; the request is warned
        about either way. It buys the load path, not the answer: measured at
        nt 3 AND nt 4 on both carriers (``error_engine`` either way) against
        this branch's own flag-off baseline, ``ex_07_beam_elform_1`` walks
        from ``t = 0.3004`` to ``t = 1.000`` at −1.72 % of its reference but
        still exits ERROR on the last increment, and
        ``ex_05_beam_elform_3_&_6`` fails in ~2 s without the flag and with
        it runs tens of thousands of cycles to ``t ~ 1e-7`` and times out.
        ``/IMPL/DT/FIXPOINT`` is deactivated by the engine under RIKS
        (``lectur.F:3523-3532``).
    discrete_offset : bool
        Honour ``*ELEMENT_DISCRETE``'s ``OFFSET`` cell (Vol I R17 p.19-33:
        *"a displacement or rotation at time zero … a positive offset on a
        translational spring will lead to a tensile force being developed at
        time zero"*). **On by default.** Radioss spring deflection is purely
        geometric (``r1def3.F:206``) and ``/PROP/TYPE4`` has no offset cell,
        so the exact restatement is ``f_RAD(d) = f_LS(d + OFFSET)``: the force
        function's ABSCISSAE are shifted by ``−OFFSET`` (ordinates untouched)
        and an ``/INISPRI/FULL`` carries the pre-stretch energy
        ``EI = ½·f_LS(OFFSET)·OFFSET``. MEASURED, together with
        ``spring_token_mass_compensation``, on the only two carriers of 885
        roster decks: ``ex_17_spring_elform_0`` IE +0.0074 % / KE +0.039 % and
        ``ex_18_spring_elform_0`` +0.0064 % / −0.015 %, where the shipped arm
        was a strict ZERO model on both.
    spring_token_mass_compensation : bool
        Subtract k2rad's own artificial spring mass from the ``/ADMAS`` of the
        nodes it lands on. **On by default.** LS-DYNA discrete elements are
        massless, but ``hm_read_prop04.F:136-142`` refuses a ``/PROP/TYPE4``
        ``MASS <= 1e-15`` (ERROR 229), so k2rad writes a token ``1e-4`` and
        ``rinit3.F:1926``/``:1937-1939`` puts HALF of it on EACH end node, per
        element. Measured ALONE it is inert on every deck where it can be
        measured; it is load-bearing inside the ``discrete_offset`` bundle,
        where it turns ``ex_17``'s +10.20 % / −99.27 % into +0.0074 % /
        +0.039 %. **Round 5** extended it to the three producers that invent a
        token and never registered one (the ``*CONSTRAINED_SPOTWELD`` /
        ``*CONSTRAINED_GENERALIZED_WELD_SPOT`` ``(stiff weld tie)``, and the
        ``mass <= 0`` fallbacks of the ``*MAT_SPOTWELD`` beam connector and the
        discrete-beam writer — LS-DYNA's own ``RO·A·L`` / ``RO·VOL`` is never
        compensated), and gave the class with NO ``/ADMAS`` to subtract from a
        NEGATIVE ``/ADMAS`` of its own (``hm_read_admas.F:161-171`` accepts one
        — WARNING ID 476, no sign check, no floor — and adds it algebraically
        at ``:247-248``). MEASURED on ``plates.nrbc`` at nt 4: the starter's
        ``TOTAL MASS`` goes 2.0048E-04 → 1.0048E-04, LS-DYNA's own to every
        figures, at +1.21 % cycles (2646 → 2678), both arms NORMAL. It never
        writes a non-positive value on the deck's OWN ``/ADMAS``, and it
        refuses a spring node carrying no element mass of its own (subtracting
        there leaves ``MS <= 0``, which the engine aborts on —
        ``chkmsin.F:52-59`` + ``resol.F:5460``) and a secondary node of an
        ICoG = 4 rigid body (``inirby.F:265-266`` discards that mass anyway —
        measured inert on ``mat_spring.belted-dummy``).
    shell_to_solid_rbody : bool
        Convert ``*CONSTRAINED_SHELL_TO_SOLID`` to one ``/RBODY`` per card —
        the shell node ``NID`` as the main node, the ``NSID`` set as the
        secondary group, ``Mass`` 0, ``ICoG`` 3, ``Ifail`` 0. **On by
        default.** LS-DYNA names the substitute in the card's own Purpose
        sentence (Vol I R17 p.10-182): *"Nodal rigid bodies can perform the
        same function and may also be used."* THE COST: LS-DYNA lets the brick
        nodes *"move relative to each other in the fiber direction"*
        (p.10-183) and an ``/RBODY`` cannot. MEASURED on
        ``constrained.shell_solid.dome`` (7 cards, 5 nodes each, nt 4): NORMAL
        48190 cycles (+0.27 % over the drop arm's 48060), external work 1689
        against LS-DYNA's 1692.55 (−0.21 %), IE 0.6693 → 873.9
        (−99.90 % → +36.08 %), KE 1.290e5 → 806.4 (+12299.9 % → −22.49 %).
        The campaign row stays ``deviation``.
    generalized_weld_butt : bool
        Convert ``*CONSTRAINED_GENERALIZED_WELD_BUTT`` to one ``/RBODY`` per
        card with ``Ifail = 1``, ``FN = FT = SIGY·L·D/BETA`` and
        ``expN = expT = 2``. **On by default**, COINCIDENT node pairs only.
        LS-DYNA's own model of this weld IS a nodal rigid body (*"When the
        failure time, tf, is reached the nodal rigid body becomes inactive"*,
        Vol I R17 p.10-32). On a coincident pair Radioss's normal is a zero
        vector (``rgbodv.F:249-256``), so ``FN`` is identically 0 and ``FT``
        carries the whole reaction — hence ``FT = FNmax`` and not
        ``FNmax/√3``, at the price of the normal/shear distinction. MEASURED
        on ``constrained.butt-weld`` (nt 4): NORMAL 2082 cycles (+0.63 %),
        IE −100.00 % → +4.70 %, KE −30.79 % → −26.85 %; the SAME two
        welds LS-DYNA's own ``.messag`` records trip the criterion at
        t 1.269e-3 against its own 1.26914e-3 and are set off at 1.272e-3.
    tgmult_imptemp : bool
        Turn a ``*MAT_THERMAL_*`` ``TGMULT`` (volumetric heat generation) into
        an ``/IMPTEMP`` holding the closed-form adiabatic solution
        ``T(t) = T0 + (TGMULT/(ρ·Cp))·∫f dt`` over the parts' own nodes. **On by
        default**, and gated hard: it fires only when the deck states no OTHER
        temperature driver, because ``/IMPTEMP`` is a hard Dirichlet reset
        applied every cycle (``fixtemp.F:180-199``) and would overwrite a
        conduction solution rather than add to it. MEASURED on
        ``thermal/thermal-stress``: the free-expansion displacement of node 2
        goes from exactly 0.0 to 1.49531e-04 mm at ``t = 2.994002`` -
        +0.21 % against the LS-DYNA ``nodout``'s NEAREST SAMPLE
        (1.49216e-04 at ``t = 2.99``) and +0.007 % against the closed form at
        the same time - at 406 580 cycles and 0 ERROR / 0 WARNING. Quote the DISPLACEMENT — that deck's LS
        reference energies are structural zeros.
    deformable_contact_recipe : bool
        Apply the validated stabilization recipe for an implicit deck with
        deformable-vs-deformable contact (e.g. force control through a
        clearance-fit deformable pin): Inacti=5 on each deformable-deformable
        /INTER/TYPE7, plus /IMPL/DT/2 L_dtn=50 and /IMPL/QSTAT/DTSCAL=0.05. Off
        by default — without it the converter only WARNS that such contact was
        detected and that this recipe exists. Implicit decks only.
    emit_eig : bool
        For a modal deck (*CONTROL_IMPLICIT_EIGENVALUE): emit the classic /EIG
        request + one-shot eigensolve engine, which only COMMERCIAL Altair
        Radioss can run (the open-source engine lacks the eigensolver kernel
        and segfaults). Off by default: the modal deck is instead converted to
        the validated stiffness-export recipe (/IMPL/PRINT/STIF writes the
        assembled K; tools/modal_solve.py solves the modes offline with scipy),
        which runs on the open-source engine.
    blast_ground : str
        Ground plane for a surface-burst /LOAD/PBLAST (Exp_data=2), which needs a
        reflecting ground or OpenRadioss assumes it ⊥Z through the detonation
        point and drops target segments on the far side. ``"auto"`` (default)
        infers the vertical axis from geometry and synthesizes a flat ground
        plane through the charge whose normal faces the target; ``"none"`` emits
        no Ground_ID (OpenRadioss's ⊥Z default) and only warns; ``"X"``/``"Y"``/
        ``"Z"``/``"-X"``/``"-Y"``/``"-Z"`` force the ground-normal (up) axis.
    rigid_cog_master : bool
        Synthesize an element-free /RBODY master node at each *MAT_RIGID part's
        nodal centroid (the treatment CNRBs always get) instead of reusing the
        part's lowest-id mesh node. **On by default**: it clears starter WARNINGs
        448/1624 (master connected to an element / removed from the secondary
        set), keeps all mesh nodes at their source coordinates (otherwise
        OpenRadioss relocates the mesh-node master to the centre of mass at
        runtime, so that node appears to move in post-processing), and makes the
        deck AMS-compatible (a mesh-node master trips AMS ERROR 1066). Set False
        (CLI ``--no-rigid-cog-master``) to reuse the mesh node as the master,
        which keeps the master-node id stable for scripts that address
        loads/readouts by it, at the cost of those warnings and the runtime move.
    zero_density_floor : bool
        Substitute ``rho = 1e-24`` (in the deck's own unit system) for a
        material that states ``RO <= 0``. **On by default**: the OpenRadioss
        starter refuses a non-positive density outright
        (``hm_read_mat.F90:1575-1583``, ``ERROR 683``, exempting only laws
        0/20/51/108/151/999), while LS-DYNA accepts the card and makes the SAME
        substitution silently — its own ``.d3hsp`` reports a part mass of
        exactly ``1.000e-24 x volume``, measured to seven figures on five R14
        reference decks and four element families. A STATIC or EIGENVALUE
        answer is unaffected (``/IMPL/QSTAT``'s stabilization is ``~ M/dt^2``
        and vanishes with the mass; a modal shift is bounded by
        ``df/f ~ -0.5 rho V / M_eff``, 2.1e-17 on the corpus carrier); an
        EXPLICIT deck gets a second, harder warning, because at that density
        ``c = sqrt(E/rho)`` collapses the element time step to ~1e-14 s.
        A material converting to an exempt law — ``*MAT_VACUUM`` -> ``/MAT/VOID``
        above all, where ``RO = 0`` is the card's own meaning — is left alone.
        Set False (CLI ``--no-zero-density-floor``) to copy the deck's own RO
        through and let the starter refuse it.
    law106_shell_restate : bool
        Restate a ``*MAT_ELASTIC_PLASTIC_THERMAL`` / ``*MAT_CWM`` from
        ``/MAT/LAW106`` to ``/MAT/LAW36`` when every part on it is a SHELL and
        it carries a thermal expansion coefficient. **On by default**, because a
        ``/MAT/LAW106`` SHELL DOES NOT THERMALLY EXPAND AT ALL: ``cmain3.F:348``
        runs ``THERMEXPC`` AFTER ``MULAWC`` at ``:320`` and all THERMEXPC does
        on a ``/PROP/SHELL`` is SUBTRACT the thermal stress from the stress the
        law just produced (``thermexpc.F:269-293``), while
        ``sigeps106c.F90:297-298`` rebuilds ``signxx``/``signyy`` from the TOTAL
        strain and never reads ``sigoxx`` — so the subtraction is discarded on
        the next cycle. ``/MAT/LAW36`` is incremental (``sigeps36c.F:276``) and
        reads it back. MEASURED on three controlled coupons (alpha 1.2e-5,
        dT 100 K, L 10 mm, NIP 3, closed form 1.2e-2 mm): LAW106 shell
        0.0000000e+00 (**-100 %**), the LAW36 restatement 1.2000000e-02
        (+0.000 %, and identical to a ``*MAT_024`` + expansion control run at
        every printed T01 digit), the LAW106 SOLID 1.2000000e-02 (+0.000 %).
        SOLIDS are never
        restated — ``mmain.F90`` applies the expansion to the strain increment
        before the law dispatch — and neither is a material shared between shell
        and non-shell parts (it is warned by name instead). The cost is named per
        card: ``/MAT/LAW36`` carries no temperature dependence, so E, nu and the
        yield are frozen at the reference temperature and the warning prints each
        table's own measured spread. Set False (CLI
        ``--no-law106-shell-restate``) to keep ``/MAT/LAW106`` and its E(T) at
        the price of zero thermal expansion on those parts.
    zero_t0_sentinel : bool
        Write ``/HEAT/MAT`` ``T0`` as ``1e-10`` in the deck's own temperature
        unit when the deck STATES an initial temperature of exactly ``0.0``.
        **On by default.** Radioss cannot tell a stated 0 from "not stated":
        ``hm_read_therm.F:236-237`` turns a zero ``T0`` into 300 K, and
        ``scoor3.F:328-338`` (solids), ``cinmas.F:900-905`` /
        ``c3inmas.F:1516`` (shells) and ``pmass.F:233`` then overwrite every
        node still at exactly ``0.0`` with it - so the run starts 300 K away
        from where the deck says it starts. Both are EXACT zero tests, so the
        substituted value is a sentinel dodge and not physics; a tenth of a
        nanokelvin is below every channel's print precision. MEASURED on
        ``ex_22_solid_elform_2``, whose ``*INITIAL_TEMPERATURE_SET`` states
        ``0.0`` over all 54 nodes: node 5 at ``t = 31.60 s`` reads
        ``198.21400`` against the LS-DYNA reference's ``34.83880`` (+468.9 %)
        with ``T0 = 0``, and ``35.15680`` (+0.91 %) with the sentinel, while
        the driven node 6 is ``61.32760`` either way. A deck that states NO
        initial temperature keeps ``0.0`` - there the 300 K default is
        Radioss's own documented behaviour and contradicts nothing. Set False
        (CLI ``--no-zero-t0-sentinel``) to write the deck's own ``0.0``.
    node_tc_rc_bcs : bool
        Convert ``*NODE`` card 1's own ``TC``/``RC`` constraint cells into
        ``/GRNOD/NODE`` + ``/BCS`` — one pair per distinct ``(TC, RC)`` code.
        **On by default.** Vol I R17 p.35-2/35-3 makes card 1
        ``NID X Y Z TC RC`` with the codes ``0`` none, ``1`` x, ``2`` y,
        ``3`` z, ``4`` xy, ``5`` yz, ``6`` zx, ``7`` xyz in the GLOBAL system,
        carrying no CID, no id and no birth/death — they are unconditionally
        active for the whole run. LS-DYNA applies them, measured rather than
        assumed: this decode reproduces its own ``nodal spc summary on *NODE
        cards`` d3hsp echo — printed by 155 of the R14 reference runs — on all
        162 139 TC/RC cells of the 137 carrier decks, with zero
        translation-code disagreements. Dropping them leaves those
        degrees of freedom FREE at 0 conversion warnings and 0 starter errors;
        on the 356-deck dynaexamples R14 campaign **137 decks carry a non-zero
        cell and 119 of them have no ``*BOUNDARY_SPC`` at all**, and those
        decks sit under 44 of the 69 IE-collapse and 27 of the 42
        implicit-ERROR rows. Two measured against their own LS-DYNA
        ``glstat``: ``component1`` moves from IE −99.92 % / KE +772630 % to
        IE +1.5 % / KE +1.0 %, and ``ex_03_solid_elform_1_4x6x4_mesh`` from a
        TIMESTEP-LIMIT death at ``t = 0.22`` to NORMAL TERMINATION at
        ``t = 1.0``. Screened rule by rule, each screen counted in the log:
        rigid-body member nodes are DROPPED (Vol I p.35-3 Remark 1; LS-DYNA's
        own ``Warning 60257 skipping spc on rigid body node``; inert in
        OpenRadioss anyway per ``rgbodv.F:150-155``), a DOF a
        ``*BOUNDARY_PRESCRIBED_MOTION`` already drives is left to it (a
        ``/BCS`` on the same DOF measures starter WARNING 312 and a 99.9 %
        engine energy error), and a DOF a ``*BOUNDARY_SPC`` already states is
        merged rather than restated. Set False (CLI ``--no-node-tc-rc-bcs``)
        to keep the pre-2026-09 behaviour, in which those DOFs are free.
    default_hourglass : bool
        Give a 1-point ``*SECTION_SOLID`` that the deck leaves DEFAULTED
        LS-DYNA's own default hourglass control, and feed it through the
        existing IHQ → Isolid remap. **On by default.** Vol I R17 p.12-271
        ``*CONTROL_HOURGLASS`` Remark 1: *"If omitted or if IHQ = 0, the
        default hourglass control types are as follows: … b) For solids: type
        2 for explicit; type 6 for implicit"*, with ``QH`` 0.1 from the card's
        own Default row — and a STATED ``QH``/``QM`` of 0.0 is that same
        default (``birdball.k`` states IHQ 2 / QH 0.0 and its d3hsp echoes
        ``hourglass coefficient = 1.00000E-01``; ``275key2.k`` the same at
        IHQ 4). So an explicit deck gets ``Isolid`` 1 (viscous
        Belytschko-orthogonalised) with ``h`` 0.1 and an implicit one
        ``Isolid`` 24 (HEPH), instead of the full-integration ``Isolid`` 17 —
        which ``prop_p14_solid.cfg`` itself calls *"2*2*2 Integration Points,
        No Hourglass"* and for which ``hm_read_prop14.F:369-372`` forces
        ``GEO(13) = ZERO``, i.e. no hourglass control at all. The deck's own
        d3hsp states which default it used: ``sloshing_A`` carries no
        ``*CONTROL_HOURGLASS`` and prints ``hourglass model = 2`` /
        ``hourglass coefficient = 1.00000E-01``; the implicit
        ``ex_03_solid_elform_1_4x6x4_mesh`` prints ``hourglass
        model.(bricks) = 6``. MEASURED against each deck's own LS-DYNA
        ``glstat``: ``sloshing_A`` goes from a TIMESTEP-LIMIT death at
        ``t = 0.18`` to NORMAL TERMINATION at ``t = 2.0`` with IE −0.25 %,
        ``sloshing_C`` from a timeout to NORMAL at +2.82 %, ``taylor_A`` from
        IE +2.56 % / KE +1.48 % to +0.00 % / −0.03 %, ``rodsol`` from
        +2.88 % / +4.04 % to −1.72 % / +1.41 %, ``tension1`` from +0.10 % to
        −0.01 %, and the implicit ``ex_03_solid_elform_1`` from −20.38 % to
        −4.14 % (its ``_elform_2`` sibling, gated out, moves only through
        item F, −0.10 % → −0.03 %).
        Screened out, each for its own measured or quoted reason: ELFORM
        −1/−2 (p.41-104 Remark 13 — *"there is no hourglass energy, and the
        behavior is not affected by hourglass parameters"*), ELFORM 2/3/16 and
        the tetrahedra (no hourglass modes), ALE sections, ``/MAT/LAW115``
        sections (their own measured 17 → 24) and any deck carrying an
        ``*INITIAL_STRESS_SECTION`` (``Isolid`` 1 and 2 hit ZERO OR NEGATIVE
        VOLUME at cycle 0 under ``/PRELOAD`` ``Itype=2``). A ``*MAT_NULL`` /
        ``*MAT_ELASTIC_FLUID`` section keeps the VISCOUS ``Isolid`` 1 even on
        an implicit deck (p.25-3 ``*HOURGLASS`` Remark 4: *"For fluids modeled
        with null material, type 6 hourglass control is viscous"*; the
        stiffness-form ``Isolid`` 24 makes ``sloshing_A`` "terminate normally"
        at a 99.9 % energy error). On an implicit deck a STATED IHQ 1-5 also
        becomes type 6, which is what LS-DYNA does itself (p.12-272). Set
        False (CLI ``--no-default-hourglass``) to keep the pre-2026-09 output,
        in which a defaulted deck gets full integration and no hourglass
        control.
    assumed_strain_isolid : str
        What ``*SECTION_SOLID`` ELFORM **-1 and -2** — LS-DYNA's
        ASSUMED-STRAIN 8-point hexes — land on: ``"24"`` or ``"none"``
        (default). ``"none"`` keeps the shipped ``/PROP/SOLID`` ``Isolid`` 17,
        which IS the locking ELFORM-2 element those two formulations exist to
        replace (Vol I R17 p.41-104 Remark 13: *"Solid formulations -1 and -2
        employ an assumed strain approach to avoid the shear locking behavior
        seen in formulation 2 elements with poor aspect ratios"*). ``"24"``
        writes HEPH — one Gauss point with physical stabilisation — and
        supplies LS-DYNA's own default ``QH`` 0.1 in the ``h`` cell when the
        deck states no hourglass card of its own (the cell is inert: an
        ``Isolid`` 24 reads its coefficient from ``Dn``, which k2rad leaves
        blank, so ``hm_read_prop14.F:358-361`` takes the same 0.1 from the
        ``CVIS`` default). ELFORM 2 and 3 are deliberately NOT touched: 2 is
        the fully-integrated element ``Isolid`` 17 reproduces exactly, and 3
        is the quadratic hex, for which no Radioss ``Isolid`` exists.
        Reach: **22 deck keys on 18 emitted models** state ELFORM -1/-2 on the
        356-key R14 roster (two independently written scanners, one of them
        ``*SECTION_SOLID_TITLE``-aware); the flag MOVES **19 keys on 16
        models** — re-measured by converting all 22 carriers with the flag ON
        and OFF on the same tree. THREE do not move, all three already on
        ``Isolid`` 24: the ``ex_12_solid_elform_{-1,-2}`` pair through its
        own ``*HOURGLASS`` IHQ 6 overlay, and ``main_fsi.k`` through
        ``*CONTROL_HOURGLASS`` IHQ 6 / QH 0.1. **Opt-in because the
        arms disagree**, each measured against its own LS-DYNA reference at
        nt 4 (``Isolid`` 17 → 24): ``ex_03_solid_elform_-1_4x6x4_mesh``
        −21.72 % → −5.87 % and ``ex_04_solid_elform_-1`` −5.84 % → −2.83 %
        get better, while ``ex_14_solid_elform_-1/-2`` go +313.9/+494.0 % →
        +1373/+2014 %, ``mainboltaexpl`` −72.72 % → −81.40 % at 5× the wall
        time, and ``ex_27_solid_elform_-2_rigidwall`` LOSES the class's only
        ``match`` (ke +9.75 % → +15.43 %). Two better, four worse. A
        self-built bending coupon says why anyone would want it: ``Isolid`` 17
        reads 0.24820 / 0.15760 / 0.14942 / 0.14758 at 1/2/4/8 elements
        through the depth — the error GROWS with refinement, to −28.8 % of the
        converged 3-D 0.2072–0.2074 — while 24 reads 0.20540 / 0.20180 /
        0.20140 / 0.20140 (−2.9 %). dyna2rad maps -1 → 24 and 2/3 → 18
        (``convertprops.cxx:398-402``).
        Second effect, named because it is not obvious: with the flag ON an
        ELFORM -1/-2 part no longer satisfies ``writer/materials``'s
        ``_exact_all_ip``, which gates a ``/FAIL/TAB1`` ``Ifail_so = 2``
        (delete when ALL integration points fail) on the element really having
        8 of them — so such a deck erodes on the FIRST failed point instead,
        and says so in its own warning.
    implicit_rigid_secondary_swap : bool
        On an IMPLICIT deck, SWAP the two sides of a ``*CONTACT`` whose
        SECONDARY (SSID) side is wholly rigid instead of DROPPING the whole
        interface. **Off by default.** The flag reaches exactly the branch the
        explicit path already swaps — a rigid SSID against a deformable MSID —
        and it IMPLIES the derived ``Gapmin`` on the interface it creates,
        refusing to swap where none can be derived (a main surface that is not
        solid segments only), because the bare swap ERRORs. MEASURED on
        ``implicit/basic-examples/contact-i/bumper.k`` at nt 2 AND nt 4,
        against the LS-DYNA reference IE 1.23131e7: the shipped drop reaches
        NORMAL TERMINATION as a ZERO MODEL (IE 0, −100 %); the bare swap
        ERRORs at ``t = 3.0e-4`` (ISTOP −2, MESSAGE ID 79); the swap with the
        derived ``Gapmin`` 0.1499 and ``Inacti`` 0 reaches NORMAL TERMINATION
        in **131 cycles** at t = 0.05 with IE **6.934e5** (−94.4 %), and
        1.473e6 (−88.0 %) with ``/IMPL/QSTAT/DTSCAL`` 1. It buys a load path
        that is still 94 % short of the reference, and the campaign VERDICT
        cannot move either way — that deck's LS-DYNA KE is exactly 0, a
        structural zero the benchmark short-circuits on. The
        deformable-contact recipe is deliberately NOT widened to reach it: its
        ``DTSCAL`` 0.05, hand-set on the same converted deck, drives its
        internal energy to −7.418e5 at the same 131 cycles — NEGATIVE.
    mass_weighted_inivel : bool
        Give a rigid body that an ``*INITIAL_VELOCITY`` / ``_NODE`` /
        ``_GENERATION`` card covers only PARTLY the momentum average Vol I R17
        p.28-129 Remark 3 describes — *"the translational and rotational rigid
        body momentums are computed based on the prescribed nodal velocities.
        From this rigid body motion, the velocities of the nodal points are
        computed and reset to the new values"* — instead of the card's full
        velocity (an all-rigid card) or nothing at all (a mixed card, where
        such a body is refused today). **Off by default.** ``v_cm`` and
        ``omega`` come from the body's own lumped nodal masses
        (``k2rad.lumping.nodal_masses_from_state``) and are written as
        ``/INIVEL/TRA`` + ``/INIVEL/ROT`` on the ``/RBODY`` main node;
        ``inirby.F:1032-1048`` rebuilds every secondary from it. MEASURED on
        ``intro-by-j.-day/joint/joint-ii/translat.k`` at nt 4, where 2 of
        rigid part 1's 4 element nodes carry ``v = (2286, 0, 7620)`` and
        LS-DYNA's own cycle-0 K-ENERGY is 189.962: the shipped full-velocity
        re-point reads 387.9 (+104.20 %), this rule reads **220.58**
        (+16.12 %), and the final ``ke_dev`` goes +194.03 % → **+47.82 %**.
        The residual is not the velocity — it is the ``/RBODY``'s own lumped
        rotary inertia (starter ``NEW INERTIA`` 0.2642894E-02 against
        LS-DYNA's 0.1977E-02, the difference being exactly
        ``4 × (m/4)(A + t²)/12 = 6.65667e-4`` per diagonal), which the
        ``/RBODY`` ``J`` cells would ADD rather than replace
        (``inirby.F:166-168`` and ``:331-339`` ADD them;
        ``hm_read_rbody.F:276-279`` is only where the cells are read): a
        named follow-up, not compensated
        here. **Opt-in** because exactly one carrier with an LS-DYNA reference
        exists on this machine. A body the card FULLY covers is untouched by
        construction: its momentum average IS the card's velocity with
        ``omega`` 0, so no deck of that class changes a byte.
    write_restart : bool
        Keep OpenRadioss's engine restart (.rst) files. Off by default, which
        emits ``/RFILE/OFF`` in the engine deck — the engine restart files are
        only needed for ``/RERUN``/crash recovery and are large on a big model.
        The starter's ``<stem>_0000_*.rst`` model-handoff file is always written
        and is not affected by this flag.
    ams : bool
        Advanced Mass Scaling. For a mass-scaled explicit deck (*CONTROL_TIMESTEP
        DT2MS<0), emit ``/DT/AMS`` (engine) + ``/AMS`` (starter) instead of
        ``/DT/NODA/CST``. AMS holds the target time step with a coupled mass
        matrix that preserves the low-frequency response, rather than adding real
        nodal mass (whose inertia can dominate a fine mesh). It solves a
        preconditioned conjugate gradient each cycle and can diverge ("AMS IS
        LIKELY DIVERGING") on stiff / high-stiffness-contrast / contact-heavy
        models or at a large Tmin/element-dt ratio — if it does, drop this flag
        (back to /DT/NODA/CST) or lower ``|DT2MS|``. Implies ``rigid_cog_master``
        (a whole-part rigid body's master must be element-free or AMS errors with
        ERROR 1066). Off by default.
    eroding_surf_ext : bool
        Build the SOLID side of an ``*CONTACT_ERODING_*`` from
        ``/SURF/PART/EXT`` (external skin only) instead of the default
        ``/SURF/PART/ALL``. Off by default, because /ALL is what makes eroding
        contact work: the starter marks each interior (two-solid) face dormant
        with a negative stiffness and the engine wakes it the moment one of its
        solids dies, which is LS-DYNA's IADJ=1 / EROSOP=1 behaviour. With /EXT
        the newly exposed crater face has no contact segment at all, and the
        solver says nothing about it. Turn this on only to reproduce LS-DYNA
        SMP's literal IADJ=0, or if the extra interior segments make the
        contact sort too expensive.
    airbag_particle_uniform : bool
        Convert ``*AIRBAG_PARTICLE`` to a uniform-pressure ``/MONVOL/AIRBAG1``
        instead of the finite-volume ``/MONVOL/FVMBAG2`` it maps to. Off by
        default — FVMBAG2 is the faithful target — but that target cannot run
        on an open-source OpenRadioss build, whose ``HYPERMESH_TETRA`` is a
        stub that prints ``FVMBAGS require a mesher`` and stops. The gas
        species, injector, vents and porous surfaces are identical either way;
        only the pressure field differs.
    he_bunreacted : float, optional
        Override the ``/MAT/LAW5`` ``Bunreacted`` cell — the UNREACTED
        explosive's bulk modulus — in the deck's own pressure unit. Without it
        the card's own ``K`` is written when it states one, and otherwise the
        value is DERIVED, but only for a material an
        ``*ALE_MULTI-MATERIAL_GROUP`` names: ``fill_buffer_51.F:496`` refuses a
        LAW51 phase whose ``Bunreacted`` is ``<= 0`` with ``ERROR 99``, while a
        stand-alone ``/MAT/LAW5`` is perfectly startable with 0 there. The
        derivation is the JWL isentrope's bulk modulus at the unreacted
        density, ``A·R1·e^{-R1} + B·R2·e^{-R2} + omega·E0``, every term from a
        cell the ``*EOS_JWL`` states; it is named in the log with its formula,
        its value and its consequence: ``mjwl.F:166`` adds ``(1 - F)·K·mu`` to
        the applied pressure at every burn fraction, where an LS-DYNA
        ``BETA = 0`` card carries nothing at all. Since the derivation exists
        only to answer a check on the orphan ``/MAT/LAW51``, which is no longer
        emitted by default, it now fires only under ``ale_multimat_law51``.
    ale_multimat_law51 : bool
        Emit the synthesized ``/MAT/LAW51`` for an ``*ALE_MULTI-MATERIAL_GROUP``
        (default False). k2rad writes the LS-DYNA per-fluid ALE layout, so no
        ``/PART`` it emits ever references that card — it is an orphan by
        construction, and MEASURED inert (deleting it left all 164
        ``underwater_C`` T01 channels identical at all 172 samples). Turning it
        on also re-arms the ``Bunreacted`` derivation, because
        ``fill_buffer_51.F:496`` then applies again.
    progress : callable(fraction, label), optional
        Called with an estimated completion fraction (0.0–1.0) and a short stage
        label as the conversion proceeds, for a progress display. The CLI prints a
        percentage; the GUI drives a progress bar.
    write_log : bool
        Save the conversion's warnings + skipped keywords to ``<stem>_conversion.log``
        for later investigation (default True). The .rad files are unaffected.

    All conversion switches are opt-in: with their defaults the .rad output is
    byte-identical to a plain conversion (see :class:`~k2rad.state.ConvertOptions`).

    Returns
    -------
    ConversionResult
        Paths of the two generated files plus any warnings.
    """
    input_path = str(input_path)
    if output_stem is None:
        stem = Path(input_path).with_suffix("")
        output_stem = str(stem)

    starter_path = output_stem + "_0000.rad"
    engine_path  = output_stem + "_0001.rad"

    def _report(frac: float, label: str) -> None:
        if progress is not None:
            progress(max(0.0, min(1.0, frac)), label)

    # 1. Parse
    _report(0.0, "Parsing input file")
    blocks = parse_k_file(input_path)
    _report(0.05, f"Parsed {len(blocks)} keyword block(s)")

    # AMS needs element-free /RBODY masters: a whole-part *MAT_RIGID body whose
    # master is a mesh/element node makes the AMS starter fail with ERROR 1066.
    # Element-free masters are on by default, so this only bites when the user
    # explicitly opted out (--no-rigid-cog-master) while asking for --ams.
    ams_forced_cog = bool(ams and not rigid_cog_master)
    if ams_forced_cog:
        rigid_cog_master = True

    # 2. Dispatch each block to fill state
    state = ConversionState()
    state.units = tuple(units)
    state.options = ConvertOptions(
        ground_springs=ground_springs,
        ground_spring_k=ground_spring_k,
        inter_gapmin=dict(inter_gapmin or {}),
        soften_stfac=soften_stfac,
        tie_stfac=tie_stfac,
        tet10_to_tet4=tet10_to_tet4,
        auto_gapmin=auto_gapmin,
        gapmin_factor=gapmin_factor,
        derived_gapmin=derived_gapmin,
        derived_gapmin_factor=derived_gapmin_factor,
        rigid_secondary_swap=rigid_secondary_swap,
        deformable_to_rigid=deformable_to_rigid,
        fixpoint_count=fixpoint_count,
        qstat_dtscal=qstat_dtscal,
        arclength_riks=arclength_riks,
        discrete_offset=discrete_offset,
        spring_token_mass_compensation=spring_token_mass_compensation,
        shell_to_solid_rbody=shell_to_solid_rbody,
        generalized_weld_butt=generalized_weld_butt,
        tgmult_imptemp=tgmult_imptemp,
        deformable_contact_recipe=deformable_contact_recipe,
        emit_eig=emit_eig,
        blast_ground=str(blast_ground).strip() or "auto",
        rigid_cog_master=rigid_cog_master,
        zero_density_floor=zero_density_floor,
        law106_shell_restate=law106_shell_restate,
        zero_t0_sentinel=zero_t0_sentinel,
        node_tc_rc_bcs=node_tc_rc_bcs,
        default_hourglass=default_hourglass,
        assumed_strain_isolid=assumed_strain_isolid,
        implicit_rigid_secondary_swap=implicit_rigid_secondary_swap,
        mass_weighted_inivel=mass_weighted_inivel,
        write_restart=write_restart,
        ams=ams,
        shell_formulation=shell_formulation,
        dt_del=dt_del,
        he_bunreacted=he_bunreacted,
        ale_multimat_law51=ale_multimat_law51,
        eroding_surf_ext=eroding_surf_ext,
        airbag_particle_uniform=airbag_particle_uniform,
    )
    if shell_formulation not in SHELL_FORMULATIONS:
        raise ValueError(
            f"shell_formulation must be one of "
            f"{sorted(SHELL_FORMULATIONS)}, not {shell_formulation!r}. "
            "'qbat' -> /PROP/SHELL Ishell=12 (fully integrated, the default "
            "and what every previous conversion produced); 'qeph' -> Ishell=24 "
            "(reduced integration, physically stabilised, closer to LS-DYNA "
            "ELFORM=2 Belytschko-Tsay). Choosing 'qeph' CHANGES RESULTS on "
            "every shell deck.")
    if ams_forced_cog:
        state.warn(
            "--ams requires element-free /RBODY masters, overriding "
            "--no-rigid-cog-master: rigid masters are synthesized element-free "
            "so no whole-part rigid body's master is an element node (AMS ERROR "
            "1066).")
    nblocks = max(1, len(blocks))
    bstep = max(1, nblocks // 25)
    for i, block in enumerate(blocks):
        dispatch(block, state)
        if i % bstep == 0:
            _report(0.05 + 0.28 * (i / nblocks), "Building model")
    _report(0.33, "Building model")

    # Parser-level warnings (missing *INCLUDE files, unapplied *INCLUDE_TRANSFORM
    # offsets, unresolved &parameters). Collected after dispatch: handlers resolve
    # "&name" fields lazily via to_float, which appends to this list.
    state.warnings.extend(PARSER_WARNINGS)

    # Elements recovered from an *ELEMENT_ option k2rad does not model were
    # identified by CONTENT (an all-integer option card imitates connectivity
    # exactly), so validate them against the node table now that every *NODE
    # and every *INCLUDE has been read — BEFORE --auto-gapmin analyses the mesh
    # and before build_starter emits it. Idempotent: build_starter calls it too
    # for the direct-writer callers, and the second call is a no-op.
    from .writer import (_expand_set_ranges_and_generals, _flatten_set_adds,
                         _screen_provisional_elements)
    _screen_provisional_elements(state)

    # *SET_<F>_GENERATE / _GENERAL → plain sets of that family, BEFORE the
    # _ADD unions are flattened (an _ADD member may be a _GENERATE sid) and
    # before anything allocates a /GRNOD or element-group id. Vol I R17
    # p.43-40: "these sets are generated after all input is read", which is
    # exactly this slot. Idempotent; build_starter calls it too.
    _expand_set_ranges_and_generals(state)

    # *SET_<FAMILY>_ADD → plain sets of that family now that every member
    # block has been read (a parse-time expansion could miss a child defined
    # later in the deck), so --auto-gapmin's contact-side resolution below and
    # every build_starter consumer see the combined sets. Idempotent:
    # build_starter calls it too for direct callers.
    _flatten_set_adds(state)

    # 2a. Blast decks: /LOAD/PBLAST reads the /BEGIN unit labels to convert its
    #     internal {cm,g,µs} TM5-1300 data to model units, so those labels MUST
    #     match the deck's real units. A *LOAD_BLAST_ENHANCED UNIT flag pins the
    #     system down (handlers._blast_unit_system); adopt it when the caller
    #     left units at the default so the pressures come out right.
    if state.blast_unit_system:
        # Already a Tuple[str, str, str] — the tuple() call was a copy of one.
        blast_units = state.blast_unit_system
        if tuple(units) == ("Mg", "mm", "s"):
            state.units = blast_units
            m, l, t = state.units
            state.warn(
                f"/BEGIN units set to {m}/{l}/{t} from the *LOAD_BLAST_ENHANCED UNIT "
                "flag (the TM5-1300 blast formula is unit-dependent). Pass an explicit "
                "convert(units=...) to override.")
        elif (tuple(str(u).strip().lower() for u in units)
              != tuple(u.lower() for u in blast_units)):
            # Explicit units win (deliberate), but a mismatch against the deck's
            # own UNIT flag is almost always a mistake: /LOAD/PBLAST rescales its
            # internal {cm,g,µs} data by the /BEGIN labels, so e.g. labelling an
            # SI-metre deck "mm" makes every distance read 1000x too small — the
            # starter then flags EVERY loaded segment "Rg/W**(1/3) < 0.5 :
            # Horizontal Distance on Ground (Rg) is too close to the charge" and
            # the blast pressures are wrong by unit factors.
            eu = "/".join(str(u).strip() for u in units)
            bu = "/".join(blast_units)
            state.warn(
                f"UNIT MISMATCH for the blast load: explicit units {eu} were "
                f"passed, but the deck's *LOAD_BLAST_ENHANCED UNIT flag says the "
                f"model is in {bu}. /LOAD/PBLAST converts its empirical TM5-1300 "
                f"data via the /BEGIN labels, so mislabelled units make the blast "
                f"pressures wrong by unit factors (typical symptom: the starter "
                f"warns 'Rg too close to the charge' on every loaded segment). "
                f"Unless the deck really is in {eu}, reconvert with units={bu} "
                f"(or leave units at the default to adopt the UNIT flag).")

    # 2b. Implicit safety net: a contact-free implicit model segfaults the
    #     OpenRadioss engine during setup, so give it one inert self-contact.
    _inject_implicit_contact_stub(state)

    # 2d. Auto-Gapmin: derive each surface-to-surface interface's Gapmin from
    #     the measured node-to-segment clearance between its two parts (opt-in).
    #     Runs after the stub so a real-contact model is analyzed; merges into
    #     inter_gapmin (explicit overrides win) so the writer's Gapmin path emits it.
    if state.options.auto_gapmin:
        _report(0.34, "Analyzing contact clearances")
        from .gapmin import apply_auto_gapmin
        # --auto-gapmin measures clearance off the TET10 contact facets, which are
        # built through the Radioss mid-edge map. Normalize the /TETRA10 apex
        # midside ordering (LS-DYNA→Radioss) first so the analyzed surface matches
        # what the engine builds; build_starter's own normalize pass is then a
        # guarded no-op (state.tet10_normalized).
        from .writer import _normalize_tet10_ordering
        _normalize_tet10_ordering(state)
        # When the deformable-contact recipe is active, protect its deformable-
        # deformable interfaces from auto-gapmin: they must keep their mesh-scale
        # Card-3 SST/MST Gapmin (the sub-mesh-scale auto value re-triggers the
        # chatter the recipe fixes). Explicit --inter-gapmin still wins over both.
        protect = (set(deformable_deformable_inter_ids(state))
                   if _recipe_active(state) else set())
        apply_auto_gapmin(state, protect_inter_ids=protect)

    # 2c. Implicit np>1 limitation: a solid-part contact surface makes the
    #     OpenRadioss SPMD engine segfault at the first implicit solve. The
    #     converter cannot rewrite the deck around it (it is not a surface bug),
    #     so warn the user to run np=1.
    _warn_implicit_solid_contact_np1(state)

    # 2e. Deformable-vs-deformable contact: warn it is chatter/overshoot-prone in
    #     implicit, and point to (or confirm) the opt-in stabilization recipe.
    _warn_deformable_deformable_contact(state)

    # 3. Generate output text (build_starter dominates wall time on a large mesh,
    #    so it drives most of the progress bar).
    _report(0.36, "Writing starter deck")
    starter_text = build_starter(
        state, progress=lambda fr, label: _report(0.36 + 0.61 * fr, label))
    _report(0.97, "Writing engine deck")
    engine_text  = build_engine(state)

    # 4. Write files. utf-8 regardless of locale (an ASCII/C locale would
    # UnicodeEncodeError on a non-ASCII part title); create the output
    # directory when the stem points into one that does not exist yet.
    _report(0.98, "Saving files")
    out_dir = Path(starter_path).parent
    if out_dir and not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
    with open(starter_path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write(starter_text)
    with open(engine_path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write(engine_text)

    # 5. Auto-save warnings/skips for later investigation (large decks scroll the
    #    console). Written next to the output as <stem>_conversion.log.
    log_path = _write_conversion_log(output_stem, input_path, state) if write_log else None

    _report(1.0, "Done")
    return ConversionResult(
        starter_path=starter_path,
        engine_path=engine_path,
        warnings=list(state.warnings),
        skipped_keywords=sorted(set(state.skipped_keywords)),
        recognized_not_emitted=sorted(state.recognized_not_emitted),
        log_path=log_path,
    )


__all__ = ["convert", "ConversionResult", "__version__"]
