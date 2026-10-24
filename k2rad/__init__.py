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
from .state import ConversionState, ConvertOptions
from .writer.common import SHELL_FORMULATIONS
from .writer import (build_starter, build_engines, _warn_implicit_solid_contact_np1,
                     _warn_deformable_deformable_contact,
                     deformable_deformable_inter_ids, _recipe_active,
                     add_implicit_contact_stub, _STUB_TYPE25_KEPT_SENTENCE,
                     n2s_routed)


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
    # R14 triage round 9, A2 (--implicit-n2s-type7): an implicit
    # *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE is written as a one-way
    # /INTER/TYPE7 ("routed"); only the rest of the TYPE25-route records are
    # written as /INTER/TYPE25 ("t25") - the B6 opt-in and its sentence key
    # on those alone.
    routed = [c for c in state.contacts_type25 if n2s_routed(state, c)]
    t25 = [c for c in state.contacts_type25 if not n2s_routed(state, c)]
    if t25 and state.options.skip_implicit_stub_with_type25:
        # R14 triage round 8, B6 (inverted by the round's validation): under
        # the opt-in the stub is left out only where a TYPE25-route contact
        # is actually WRITTEN, which the writer knows and this pass does not
        # - so the decision is deferred to
        # writer/contacts._make_deferred_implicit_stub (right after the
        # TYPE25 section), before any id is drawn here. Placed after every
        # other early return, so it fires exactly where a stub WOULD have
        # been injected.
        state.implicit_stub_deferred_for = sorted(c.inter_id for c in t25)
        return
    # round 9, A2 (coordinator decision: friction-faithful): beside a routed
    # contact the stub duplicates its pairs, so it carries the routed FS x
    # FSF when every routed record states the same scalar value
    stub_fs = 0.0
    scalars = [c.fs * c.fsf if c.fs >= 0.0 and c.fs != 2.0 else None
               for c in routed]
    if routed and len(set(scalars)) == 1 and scalars[0] is not None:
        stub_fs = scalars[0]
    inter_id = add_implicit_contact_stub(state, fs=stub_fs)
    if t25:
        # The default since the round-8 validation round: the stub STAYS
        # beside a TYPE25-route contact (the 4f5b6e8 deck byte for byte);
        # the sentence names both measured arms and the opt-in.
        state.warn(_STUB_TYPE25_KEPT_SENTENCE.format(
            ids=sorted(c.inter_id for c in t25), stub=inter_id))
    if routed and (len(set(scalars)) > 1 or scalars[0] is None):
        shown = ", ".join("a table / sentinel" if v is None else f"{v:g}"
                          for v in scalars)
        state.warn(
            "Implicit deck: the routed node-to-surface contacts "
            f"{sorted(c.inter_id for c in routed)} state different (or no "
            f"scalar) friction coefficients ({shown}); the all-parts implicit "
            f"stub (/INTER/TYPE7 {inter_id}) beside them stays frictionless, "
            "so on the pairs it duplicates it carries none of their friction.")
    elif routed:
        state.warn(
            "Implicit deck: the all-parts implicit stub (/INTER/TYPE7 "
            f"{inter_id}) is KEPT beside the routed contact(s) "
            f"{sorted(c.inter_id for c in routed)} and carries their friction "
            f"FS {stub_fs:g}: it duplicates their pairs (doorbeam: the same "
            "normal impulse on both, within 0.15 %, while the punch loads, "
            "through t 9.35e-4 s; they part over the last 0.17 ms, the stub "
            "at 0.89-0.90 x the routed contact's at t_end on the main branch "
            "and 1.29-1.33 x on the -16 % one), so a frictionless stub would "
            "halve the friction there; the same friction also acts on the "
            "stub's other pairs. Without the stub the one-way route loses the load "
            "silently on few-node contacts (4-node coupon: the block passes "
            "through behind a NORMAL TERMINATION).")


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
    # Every engine file in RUN ORDER (round 8, B3 h.2): [engine_path] for
    # every deck but an IMFLAG < 0 one under --imflag-curve-restart, which
    # gets <stem>_0001.rad, <stem>_0002.rad, ... (run them in order from one
    # directory). Never empty.
    engine_paths: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.engine_paths:
            self.engine_paths = [self.engine_path]


def _stale_engine_files(output_stem: str, n_engine: int) -> List[str]:
    """The ``<stem>_k.rad`` files (k a 4-digit number > *n_engine*) already
    beside the output - engine files an earlier, longer
    ``--imflag-curve-restart`` chain wrote, which this conversion does not
    overwrite. ``_0000.rad`` is the starter and ``_0001`` .. ``_000N`` are
    this conversion's own, so only k > N is stale. Sorted by k; names only."""
    stem = Path(output_stem)
    folder = stem.parent if str(stem.parent) else Path(".")
    if not folder.is_dir():
        return []
    prefix = stem.name + "_"
    out = []
    for p in folder.iterdir():
        name = p.name
        if (name.startswith(prefix) and name.endswith(".rad")
                and len(name) == len(prefix) + 8
                and name[len(prefix):len(prefix) + 4].isdigit()
                and int(name[len(prefix):len(prefix) + 4]) > n_engine
                and p.is_file()):
            out.append((int(name[len(prefix):len(prefix) + 4]), name))
    return [name for _k, name in sorted(out)]


def _write_conversion_log(output_stem: str, input_path: str,
                          state: ConversionState,
                          engine_paths: Optional[List[str]] = None
                          ) -> Optional[str]:
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
        (f"  output    : {output_stem}_0000.rad / _0001.rad"
         if not engine_paths or len(engine_paths) < 2 else
         f"  output    : {output_stem}_0000.rad / "
         + " / ".join(Path(p).name for p in engine_paths)),
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
    qstat_dtscal_stated: bool = False,
    arclength_riks: bool = False,
    zero_tolerance_ectol: bool = True,
    implicit_constant_step: bool = False,
    discrete_offset: bool = True,
    spring_token_mass_compensation: bool = True,
    shell_to_solid_rbody: bool = True,
    generalized_weld_butt: bool = True,
    initial_void_floor: bool = True,
    weld_exponents: bool = True,
    constrained_linear: bool = True,
    constrained_global: bool = True,
    spotweld_node_synthesis: bool = False,
    beam_contact_secondary: bool = False,
    shell_offset_gapmin: bool = True,
    rigid_shell_rotary_inertia: bool = True,
    spotweld_shear_yield: bool = True,
    spotweld_efail_displacement: bool = True,
    implicit_tshell_solid: bool = True,
    corotational_orthotropic: bool = True,
    mat_null_pc_mu: bool = True,
    joint_screw_gjoint: bool = True,
    rigid_local_constraints: bool = True,
    bcs_union: bool = True,
    bolt_rigid_contact: bool = True,
    fixed_curve_columns: bool = True,
    section_nodal_thickness_mean: bool = True,
    plane_strain_unit_thickness: bool = True,
    rigid_element_mass_admas: bool = True,
    spotweld_dt_mass_scaling: bool = True,
    adaptive_spring_token: bool = True,
    imflag0_eigen_explicit: bool = True,
    implicit_smooth_curve_sampling: bool = True,
    elastic_fluid_cp_cutoff: bool = True,
    skip_implicit_stub_with_type25: bool = False,
    shell_in_solid_coupling: bool = False,
    imflag_curve_restart: bool = True,
    rigid_part_pid_precedence: bool = True,
    implicit_n2s_type7: bool = True,
    implicit_rigid_gravity_nodes: bool = True,
    elform7_beam_thickness_section: bool = True,
    spc_vector_frames: bool = True,
    prescribed_motion_sf_default: bool = True,
    rigid_local_shared_skew: bool = True,
    modal_acoustic_void: bool = True,
    mixed_main_thickness_gap: bool = False,
    implicit_bfgs: bool = False,
    weld_trajectory_impflux: bool = True,
    weld_trajectory_window: float = 0.25,
    axisymmetric_2d: bool = True,
    positive_dt2ms_mass_scaling: bool = True,
    plane_stress_unit_thickness: bool = True,
    load_curve_offscale_zero: bool = True,
    ale_flow_tracking: bool = False,
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
        derived ``GAP MIN`` 1.0): the starter's gap ENDS at +1151 % internal
        energy against the LS-DYNA reference 3036.17 and this rule's
        ``0.005 × 10 = 0.05`` ends at −5.60 % — an END value: the first impact
        reads −91 % and the engine energy error stays −7.1 to −8.2 % at every
        gap. Two rounds of arms — round 6 alone ran 16 gap values on
        ``twobar``, ``hemi``, ``sphere1`` and ``bend`` — found ZERO campaign
        verdict promotions (``sphere1``, where it writes 0.02921, goes
        −1.66 % → −7.77 % at 4.1× the cycles; ``bend`` −2.0038 % → −2.8418 %
        at 4.69×). Of the class's 15 interfaces on the 356-key R14 roster
        (counted before round 6's shell-offset Gapmin took ``bend``'s) **7
        now have a measured arm and 8 are still unjudgeable**: twobar's end
        value moves while its history does not, ``sphere1`` and ``bend`` are
        worse, ``pend.imp`` and ``06_heating_plate`` byte-inert,
        ``4.3_General_Nonlinearity`` mixed (energy error −99.9 % → −55.2 %,
        internal energy −98.87 % → −99.92 %). And it costs: below a
        deck-specific knee the cycle count grows as ~1/Gapmin (twobar 2.17× at
        0.02 and 7.71× at 0.005; the contact step is ½(GAPV − PENE)/v,
        ``i7for3.F:762-770``) — which is why it is opt-in. A press-fit
        ``*CONTACT_*_INTERFERENCE`` and k2rad's own injected implicit
        stabilization stub are excluded.
    derived_gapmin_factor : float
        Fraction of the smallest main-surface segment side used by
        ``derived_gapmin`` (default 0.005; every twobar figure is an end
        state — its first impact reads −91 % at 0.005 — and cycles grow as
        ~1/factor below the knee).
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
        going ``normal`` → ``timeout`` on the ``/PROP/TYPE20`` card k2rad
        wrote before round 7 (round 7's default ``implicit_tshell_solid``
        route ends the family NORMAL in 28 cycles at this default, and at
        0.1 too: the value is inert on the routed card);
        ``--qstat-dtscal 0.1`` with ``--no-implicit-tshell-solid``
        reproduces the pre-round-4 file byte for byte on that family (0.1
        alone does not since round 7). ``"none"``
        is measured WORSE than either (``ex_02`` dies at cycle 0, ``tensile2``
        at ``t = 0.746``). ``deformable_contact_recipe`` keeps its separately
        validated 0.05 and ignores this.
    qstat_dtscal_stated : bool
        Whether ``qstat_dtscal`` was GIVEN rather than left at its default
        (R14 triage round 9, A11; the CLI sets it when ``--qstat-dtscal``
        appears, the GUI when its QSTAT box is filled). ``arclength_riks``
        writes no ``/IMPL/QSTAT`` card unless this is True. Default False.
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
        about either way. Since round 9 (A11) the flag also writes NO
        ``/IMPL/QSTAT`` card unless ``qstat_dtscal_stated`` (the quasi-static
        term stiffens the arc-length tangent). It buys a load path, NOT the
        answer: on ``ex_07_beam_elform_1`` the path loops through negative
        load factors LS-DYNA never visits and the run ends NORMAL in 9 of 10
        runs of identical bytes (nt 4 and nt 2), ERROR once;
        ``ex_05_beam_elform_3_&_6``
        still stops; the LS reference of both is UNMATCHED (its time axis
        runs backwards), so no run is evidence of the answer.
        ``/IMPL/DT/FIXPOINT`` is deactivated by the engine under RIKS
        (``lectur.F:3523-3532``).
    zero_tolerance_ectol : bool
        On a ``*CONTROL_IMPLICIT_SOLUTION`` whose DCTOL, ECTOL and RCTOL are
        ALL 0.0 / blank (or >= 1), write LS-DYNA's own ECTOL default -
        ``/IMPL/NONLIN/1`` Itol 1 (energy), Toli 0.01 - instead of k2rad's
        force default Itol 2. **On by default.** Every one of the 11 R14
        reference ``d3hsp`` files of that shape echoes DCTOL 0.001 / ECTOL
        0.01 / RCTOL 0.999e11 (Vol I R17 p.12-354), i.e. LS-DYNA applies its
        defaults to the stated zeros - the rule rests on that echo, not on a
        measured gain. L_A is unchanged; a NEGATIVE cell is a tolerance curve
        (p.12-355) and keeps Itol 2. MEASURED at nt 4 = nt 2: the IE history
        is closer on 3 of the 11 carriers by at most 0.03 points of the
        reference peak and farther on 4; ``tensile2`` ENDS at IE +7.36 % ->
        -0.54 % at 0.11x
        the cycles but reads +53 % at t 0.80 (+14 % before) - its history
        RMS 2.00 % -> 2.48 % of the reference peak; ``doorbeam`` +380.25 % ->
        +582.00 % (a named regression, larger mid-run), ``ie_shell`` ERROR ->
        NORMAL at IE -99.87 % (a status-only promotion).
    implicit_constant_step : bool
        Cap the implicit step at the deck's own DT0 (``/IMPL/DT/STOP``
        ``DT_MAX := DT0``) where LS-DYNA runs a CONSTANT step: an implicit
        deck stating IAUTO 0 or no ``*CONTROL_IMPLICIT_AUTO`` (Vol I R17
        p.12-277), with ``0 < DT0 < ENDTIM`` and no stated DTMAX <= DT0.
        **Off by default.** Radioss keeps cutting a non-converged increment
        (``imp_dt.F:107-119``) where LS-DYNA would stop; a pinned step ended
        3 of 3 NORMAL quasi-static R14 decks in ERROR and is not offered.
        MEASURED at nt 4 = nt 2: ``ex_15`` energy error +74.1 % -> -0.9 % at
        3.81x the cycles (its END state at matched time trades IE +36.2 % ->
        -54.8 % for KE +132.0 % -> +0.5 %; on the ``/PROP/TYPE20`` card k2rad
        wrote before round 7 - the default ``implicit_tshell_solid`` route
        closes ex_15's energy balance by itself, -0.7 %, and on that routed
        card the cap takes ex_15 from 34 to 202 cycles (5.94x), energy error
        -0.7 % -> -1.8 %, END IE +72.81 % -> -55.94 % and KE +27.37 % ->
        +0.12 %, history RMS IE 8.06 -> 3.19 / KE 9.52 -> 7.45 % of the
        reference peak); ``ex_11`` KE history error
        16.07 % -> 1.16 % at 2.86x (at matched time KE +17.9 % where the
        shipped run reads +1343 % - both deviations: the engine never prints
        its last increment); with the default ``zero_tolerance_ectol`` it
        costs cycles on the quasi-static decks - ``tensile2`` 75 -> 168
        cycles, IE -0.54 % -> -4.36 % at the END, but the closest IE history
        of the measured arms (RMS 2.48 % -> 1.66 % of the reference peak).
        Reach: 33 R14 deck keys on 22 emitted models.
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
        refuses a spring node that carries no mass of its own — no element
        mass and no ``*ELEMENT_MASS`` — because subtracting there would leave
        the node at EXACTLY ``MS = 0``, which nothing catches
        (``chkmsin.F:53`` aborts only on ``MS < 0``; ``accele.F:67-80`` then
        freezes the node's velocity); a node with only an ``*ELEMENT_MASS``
        (gnonspring: ``TOTAL MASS`` 1.02e-4 → 2.0e-6 = LS-DYNA's, round 6)
        IS compensated. It also leaves out a secondary node of an ICoG = 4
        rigid body (``inirby.F:265-266`` discards that mass anyway —
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
    initial_void_floor : bool
        On a deck that states ``*INITIAL_VOID_PART`` / ``_SET`` on an
        ELFORM-12 part whose material is a ``*MAT_NULL`` + ``*EOS_*`` carrier,
        write ``Pmin = -1e-20`` on the ``/MAT/HYD_VISC`` of that fluid — the
        void's own material and every LAW6 material of the deck's ELFORM-12
        fluid (Vol I R17 p.28-134: one fluid per single-material-and-void
        mesh). **On by default.** NOT 0: ``hm_read_mat06.F:154`` reads an
        exact ``Pmin`` 0 as -INFINITY, so the ``Pmin 0`` every
        ``*MAT_NULL`` + ``*EOS_*`` ``/MAT/HYD_VISC`` carried was an UNBOUNDED
        tension in the cells the fluid leaves. A stated PC is overridden and named; refused (nothing
        written) on a deck with ``*ALE_MULTI-MATERIAL_GROUP`` and for a void
        that is not ELFORM 12 or not a LAW6 carrier. The void's low density is
        NOT written. MEASURED at nt 4: quadrature_B timeout → NORMAL in 1095
        cycles (IE +394.0 %), bird_B timeout → NORMAL in 2936 (IE
        +1484.7 %), bird-el NORMAL either way (IE +454.1 → +1134.6 %) —
        NORMAL, not a match: the void is still full of fluid.
    weld_exponents : bool
        Write a failing ``*CONSTRAINED_SPOTWELD`` /
        ``*CONSTRAINED_GENERALIZED_WELD_SPOT`` weld's exponents N / M into its
        ``/PROP/TYPE13`` as ``alpha1-3 = 1``, ``beta1 = N``,
        ``beta2 = beta3 = M`` when either differs from 2. **On by default.**
        A blank cell is read as ``alpha 1`` / ``beta 2``
        (``hm_read_prop13.F:1169-1170``), so without them the criterion is
        always exponent 2; ``N = M = 2`` writes nothing (byte-identical).
        Radioss sums the two shear directions where LS-DYNA scores the
        RESULTANT: exact at ``M = 2`` and for shear on one local axis; with
        both components present an ``M < 2`` weld fails earlier than in
        LS-DYNA (conservative) and an ``M > 2`` weld fails later
        (non-conservative). MEASURED at nt 4 on ``plates.nrbc``
        / ``plates.spot`` (N = M = 1): rupture t 3.130e-4 (+29.4 %) →
        2.460e-4 (+1.7 % against LS-DYNA's 2.4193e-4), 0.899x the cycles.
    constrained_linear : bool
        Convert ``*CONSTRAINED_LINEAR_LOCAL`` / ``_GLOBAL`` (and the legacy
        ``*CONSTRAINED_LINEAR``) to one ``/MPC`` per card — node = ``NID``,
        ``Idof`` = ``DOF``, skew = the ``/SKEW`` of ``CID``, alpha = ``COEF``.
        **On by default.** The engine enforces it by a Lagrange multiplier as
        ``sum alpha_k v_k = 0`` (``lag_mpc.F``), LS-DYNA's ``C0 = 0``
        equation. Refused by name (the card stays skipped): a DOF that also
        carries a ``/BCS`` or an imposed motion (WARNING 312), a rigid-body
        node, an element-free node, a zero ``COEF`` (``hm_read_mpc.F:124``
        reads 0 as 1), DOF 7, an undefined ``CID``, a (node, DOF) pair used
        twice. MEASURED on ``plates.lce`` (the only carrier): starter
        ``NUMMPC 1``, 0 errors, engine identical to the base on all 683 rows
        (the constrained nodes are symmetric about the driven one).
    constrained_global : bool
        Convert ``*CONSTRAINED_GLOBAL`` (a global constraint plane, Vol I R17
        p.10-38) to ``/BCS``: the nodes within the row's TOL of the plane -
        or ``1e-6 x`` the model extent where TOL is 0 - get the row's TC/RC
        codes, UNIONED per node over all rows and with the deck's ``*NODE``
        TC/RC cells, one ``/BCS`` per union code through the ``*NODE`` TC/RC
        screens. **On by default.** The selection equals LS-DYNA's own d3hsp
        'nodal spc summary' node for node on all three R14 carriers (305, 54
        and 24737 nodes). A bad row (TC/RC outside 0-7, DIR not 1/2/3, TOL <
        0) and a card from a transformed ``*INCLUDE_TRANSFORM`` are refused by
        name; off, the keyword stays SKIPPED and its DOFs are free.
    spotweld_node_synthesis : bool
        Give an ELFORM-9 ``*MAT_SPOTWELD`` beam that states ONE node its
        second one where Vol I R17 p.19-3 puts it: the given node moved onto
        the nearest reference segment of the tie that names the weld part, a
        new node on the nearest segment on the other side (spotweld.k: 1213
        -> z 0, new node at z 2, length 2.0 = LS-DYNA's own d3plot and
        swforc). **Off by default**: alone it only costs cycles (2.09x on
        spotweld.k with today's DT scaling, 639 -> 1334, 7.64x without; IE
        END -99.88 %); with ``beam_contact_secondary`` (and
        today's EFAIL displacement criterion and DT scaling) the IE END
        reads -31.18 % at LS-DYNA's own cycle count 1332 and the weld
        ruptures 65.3 us before LS-DYNA's (1.12229e-3 vs 1.1876e-3 s).
    beam_contact_secondary : bool
        Put the nodes of ``*ELEMENT_BEAM`` elements (beams, trusses, spotweld
        and discrete beams) of a part named on a contact side into that
        side's node group. **Off by default**: it changes the secondary side
        of 4 R14 deck keys on 4 emitted models (spotweld.k,
        ``show-cases/contact-overview/main.k`` and the two Yaris giants) and
        of the two full-vehicle models in ``C:/openradioss_run``, none of
        which but spotweld.k has been run WITH it (the three R14 giants have
        campaign rows from runs without it).
    shell_offset_gapmin : bool
        On a ``/INTER/TYPE7`` whose main side is SOLID segments only and
        whose secondary is SHELLS that LS-DYNA offsets by half their
        thickness - the ``AUTOMATIC_*`` / ``SINGLE_SURFACE`` spellings always
        (Vol I R17 p.11-128/129 General Remark 12), the others under
        ``*CONTROL_CONTACT SHLTHK 2``, ``SHLTHK 1`` on deformable shells, or
        their own Card B ``THKOPT 1`` - with no stated gap: write
        ``Gapmin = t/2``, capped at ``0.5 x`` the smallest main-segment side,
        instead of the starter's derived ``0.1 x`` that side
        (``i7sti3.F:1055-1063``). **On by default.** Several thicknesses:
        written only when every ``t/2`` is above the cap. A shell main is
        never touched. MEASURED on ``bend`` (t 0.381 under SHLTHK 2, written
        the capped 0.127): IE -2.00 -> -1.42 %, KE -68.65 -> -45.60 % at
        matched time, 0.98x the cycles; the row stays deviation.
    rigid_shell_rotary_inertia : bool
        Write ``J = -SUM(IN)`` into the ``Jxx/Jyy/Jzz`` cells of every
        ``*MAT_RIGID`` / ``*DEFORMABLE_TO_RIGID`` part ``/RBODY`` (ICoG != 4)
        whose nodes carry lumped shell rotary inertia (round 7, A2). The
        starter ADDS every shell node's ``IN`` - ``(m/4)(A + t^2)/12`` per
        ``/SHELL`` corner (``cinmas.F:1379``, FAC 12), ``m(A/4.5 + t^2/12)``
        per ``/SH3N`` spread by the corner angles (``c3inmas.F:1111``) - to a
        rigid body's tensor
        (``inirby.F:166-168`` the main node, ``:355-363`` the secondaries),
        while LS-DYNA's rigid-part inertia is the point-mass sum (MEASURED:
        18 of 18 reference d3hsp tensors within 0.04 %; not Theory R16
        eq. 29.23's density integral).
        **On by default.** Written in the producer (a CNRB PID that shadows a
        part id no longer hides the body), skipped by name where the lumper
        is not the starter's, refused by name at or below a relative
        ``1e-3`` margin (the starter's WARNING 275 threshold,
        ``inirby.F:753-758``), never on CNRB / weld / tie / probe bodies.
        MEASURED (nt 4): a spun rigid plate's rotational KE +16.83 / +33.66 %
        -> 0.00 %; ``revo-stiff`` IE / KE history RMS
        4.96 / 2.94 -> 0.78 / 0.73 % of the LS peak at 1.156x the cycles
        (deviation -> match).
        Reach 56 deck keys on 53 emitted models (151 bodies written; 2 more
        refused by name at the margin, one each on forging_A / forging_B).
        ``--mass-weighted-inivel`` no longer subtracts on a body the
        producer already corrected.
    spotweld_shear_yield : bool
        Give every ``*MAT_SPOTWELD`` weld's ``/PROP/TYPE13`` a bilinear SHEAR
        curve on Ty/Tz (round 7, A3 piece (i)): yield ``(SIGY/sqrt3)·A`` (the
        von Mises shear yield - MAT_100 is axial-and-shear plasticity, Vol
        II R17 p.2-708), hardening ``G·EH/(3G+EH)·A/L``, ``H2 = H3 = 1``.
        **On by default.** MEASURED on plates.mat100 (nt 4): LS-DYNA's weld
        shear plateaus at 20374..20408 = (SIGY/sqrt3)·A = 20405; IE / KE
        history RMS 23.53 / 62.56 -> 8.58 / 26.74 % of the LS peak at 1.107x
        the cycles (deviation -> match). ``mainboltaexpl`` moves too, and
        not by the yield (its weld shear stays below it): the row was
        hypersensitive because its bolt collapsed - with
        ``bolt_rigid_contact`` and ``fixed_curve_columns`` (round 8) a
        K2 = K3 x (1 - 1e-8) cell moves only the 4th KE digit on 60 of 58550
        rows.
    spotweld_efail_displacement : bool
        A ``*MAT_SPOTWELD`` ``EFAIL`` below the 1e19 'never' idiom on a card
        with NO resultant failure cell -> ``Ifail 1`` / ``Ifail2 0``
        displacement failure, ``DeltaMax1 = delta_y + EFAIL·L``,
        ``DeltaMax2,3 = delta_y,s + sqrt3·EFAIL·L`` (round 7, A3 piece
        (ii)). **On by default**; beside resultant cells EFAIL is named.
        Measured on spotweld.k with the round-6 opt-in pair: rupture
        1.12229e-3 s, 65.3 us before LS-DYNA's swforc failure time 1.1876e-3
        s (the round-8 DT scaling makes it 4.2 us earlier). The measurable
        default effect is nil (its one default mover is a giant the
        campaign does not run).
    implicit_tshell_solid : bool
        On an IMPLICIT deck (the modal path included), write an isotropic
        ``*SECTION_TSHELL`` whose live parts are all ``*MAT_ELASTIC`` as
        ``/PROP/SOLID`` Isolid 14 (Inpts 222) on the same ``/BRICK`` rows
        instead of ``/PROP/TYPE20`` (round 7, A4): the implicit thick-shell
        tangent integrates the thickness with ONE mid-plane point
        (``s8cke3.F:354-364``) and 80 + 4 coupon runs stop at cycle 0.
        **On by default**; explicit decks keep TYPE20, other laws and
        TYPE21 / TYPE22 keep their card with a named warning. MEASURED:
        ``ex_02_thick_shell_elform_{2,3,5}`` timeout -> NORMAL in 28 cycles
        (nt 4 and 2); ``ex_15`` energy error 74.1 -> -0.7 % (named cost: END
        IE +0.03 -> +36.49 %).
    corotational_orthotropic : bool
        Write an element-frame orthotropic ``/PROP/TYPE6`` (Ip 20 / 21 / 23 /
        24, LS-DYNA AOPT 0 / 1 / 3 / 4) co-rotational (round 7, B3): the
        ``*MAT_MODIFIED_HONEYCOMB`` property keeps its pinned Isolid 1 /
        Ismstr 1 and gets ``Iframe 2`` on a /BRICK part, an Ip 21 / 24
        orthotropic brick on Isolid 17 takes the round-6 Isolid-14 route like
        Ip 20 / 23, and on Ip 21 ``/MAT/LAW93``'s 2 / 3 constants are
        exchanged (Radioss b = e_z x a, ``smorth3.F:326-328``). **On by
        default.** MEASURED on one-hex coupons at nt 4: MAT_126 crush 0 -> 12
        of 12 cases right (sigma(0.10) 6.0047 -> 1.5049 against 1.5), LAW93
        Ip 24 0 -> 6 of 6, Ip 21 2 -> 6 of 6; the plateau unchanged (RMS
        0.164 %). Element-frame tetrahedra are named, never changed. Reach 0
        on every corpus.
    mat_null_pc_mu : bool
        Write the ``*MAT_NULL`` PC and MU cells on the ``/MAT/HYD_VISC`` of
        every ``*MAT_NULL`` + ``*EOS_*`` carrier (round 7, B1): ``Pmin`` = PC
        (PC 0.0 or blank -> ``-1e-20``: LS-DYNA cuts at zero, while
        ``hm_read_mat06.F:154`` reads ``Pmin 0`` as -INFINITY; PC > 0 refused
        by name) and ``Nu = MU / RO`` (kinematic, ``m6law.F:98``) only where
        every part of the material is a ``*SECTION_SOLID`` ELFORM 6 on a deck
        without ``*INITIAL_VOID`` (the measured channel family; elsewhere MU
        is named and not carried). The ELFORM-12 void floor keeps
        precedence; with ``initial_void_floor=False`` alone a PC-0 void gets
        ``-1e-20`` from this rule. **On by default.** MEASURED at nt 4:
        sph/bird IE +69.44 -> +4.50 % (0.832x cycles), channel_B -98.89 ->
        -0.09 %, channel_A -98.88 -> -4.03 %; underwater_A/B stay within
        1 %. Byte reach: 20 deck keys, 17 emitted models. Since round 8 a
        ``/PROP/SOLID`` carrying a Nu > 0 brick with ``R = 10 Nu / (c0
        dmin) > 1`` gets ``h / R``; since round 9 (B7) a stated h is first
        capped: ``h' = min(h_eff, 0.14 / Tsca) / max(1, R)`` (0 corpus
        movers).
    joint_screw_gjoint : bool
        Convert ``*CONSTRAINED_JOINT_SCREW`` between two ``*MAT_RIGID``
        bodies on a global axis into ``/GJOINT/RACK`` (round 7, B2;
        Lagrange multipliers, ``FscaleV = -1/PARM`` because
        ``hm_read_gjoint.F:221`` inverts the cell) on a synthesized carriage
        ``/RBODY``, with the bodies' ``*MAT_RIGID`` constraints and drive
        re-written as ``/BCS/LAGMUL`` + ``/IMPVEL/LAGMUL`` (a VAD 2 curve
        differentiated) and the rigid pair split out of an all-parts
        self-contact. **On by default.** MEASURED on EXP_SC_JOINT_SCREW at
        nt 4: nut travel 0 -> 185.70 mm against LS-DYNA's 183.59 at the same
        instant (t 0.09995), IE -100 ->
        +42.76 % (the exact joint against LS-DYNA's yielding penalty joint),
        0.9998x cycles. SMP only (``-np > 1`` stops in its first cycle,
        ``lag_mult.F:667-671``). Anything
        outside the pattern keeps the skip with a named reason.
    rigid_local_constraints : bool
        Write a ``*MAT_RIGID`` CMO -1 card as a ``/BCS`` on the
        ``/RBODY`` main node in the ``/SKEW`` of CON1 (round 8, A1):
        CON2 is the six-digit local code, CON1 the local system, "fixed
        in time" (Vol II R17 *MAT_RIGID); LCO plays no part. CON1 0 =
        the global frame; a FLAG-1 ``*DEFINE_COORDINATE_NODES`` frame
        gets a ``/SKEW/FIX`` at its t = 0 axes; a code with a digit >=
        2 or more than six digits, an undefined CON1 or a degenerate
        node frame writes NO card and is named. The
        ``*CONSTRAINED_NODAL_RIGID_BODY_SPC`` CMO -1 card shares the
        helper (a VECTOR CON1 is a real /SKEW/FIX).
        ONE skew per node (``hm_read_bcs.F:199-205``, ERROR 148): a
        ``*NODE`` TC/RC, ``*CONSTRAINED_GLOBAL`` or ``*BOUNDARY_SPC``
        code on such a main node in another skew is DROPPED and named,
        for the ``*MAT_RIGID`` and the skewed CNRB card alike. **On by
        default.** MEASURED at nt 4: mat_rigid.block-slide KE END
        +100.10 -> +0.05 % (RMS 44.81 -> 0.006 % of the LS peak over
        500 LS blocks 0 < t <= 0.01), control_timestep.billet-forge IE
        END -99.97 -> +0.13 % (RMS 41.95 -> 0.056 %, 150 LS blocks),
        both at 1.000x cycles; reach 3 deck keys on 3 emitted models
        (the Yaris roof crush giant convert-only). False restores the
        4f5b6e8 bytes and warnings.
    bcs_union : bool
        Write a node that two or more ``*BOUNDARY_SPC`` cards constrain
        as ONE union per ``(node, skew)`` (round 8, A3 P1): a later
        card no longer restates a DOF an earlier card fixes, a node
        whose card adds new DOFs keeps them in a
        ``BC_<id>_<Tra>_<Rot>`` card, a card left with no node writes
        no ``/BCS``; and (P2 / P3) the implicit free-node guard writes
        on a free node only the DOFs its global SPC / *NODE TC/RC
        ``/BCS`` leaves free
        (``fix_free_reference_nodes_<Tra>_<Rot>``). LS-DYNA keeps one
        constraint per node and the starter ORs two ``/BCS``
        (``hm_read_bcs.F:198`` ``MY_OR``), so the second card only fed
        starter WARNING 312 - 0 physics: sphere1 1592 = 1592 cycles,
        every printed row identical at nt 4 and nt 2; WARNING 312 24 /
        339 / 4 / 30 / 449 / 486 -> none on sphere1 / ex_20 /
        6.1.test13r / ex_08 / 11.2-11.3 / 11.5. Two skews never merge.
        **On by default.** Reach 9 deck keys on 9 emitted models. False
        writes every card as before (the 4f5b6e8 bytes).
    bolt_rigid_contact : bool
        Keep the members of a rigid body holding an END node of an
        ``*INITIAL_AXIAL_FORCE_BEAM`` bolt on every PENALTY contact's
        secondary side (round 8, A2 (l)-2; the TYPE7 / general / TYPE25
        builders, never the TYPE2 family or the force transducers).
        LS-DYNA keeps every rigid member in a contact (mainboltaexpl's
        d3hsp counts 1601 nodes for interface 1, including the 68 CNRB
        110 / 120 members k2rad removed), and these carry the bolt's
        clamp. **On by default.** MEASURED on mainboltaexpl with
        ``fixed_curve_columns`` (nt 4): IE END -81.87 -> -8.49 %,
        history RMS IE / KE 31.32 / 28.24 -> 9.19 / 10.22 % of the LS
        peak (1000 LS blocks, t <= 5e-3), plates IE RMS 36.39 -> 0.65
        %, bolt force RMS 29.11 -> 0.91 %, 1.131x the cycles; each rule
        alone is worse. Reach 1 deck key on 1 emitted model.
    fixed_curve_columns : bool
        Read a comma-free ``*DEFINE_CURVE`` point line that a
        whitespace split cannot read as two numbers in LS-DYNA's fixed
        2E20.0 columns, blank = 0.0 (round 8, A2 (l)-3) - only where
        the split FAILS (decision D4), so a two-token line keeps the
        free read. mainboltaexpl's fused ``0.0055.0`` / ``0.005055.0``
        lines were dropped: its /FUNCT/11 kept 2 of 4 points and the
        bolt never pulled. ``*DEFINE_CURVE_SMOOTH`` and
        ``*DEFINE_FUNCTION`` are not touched. **On by default.**
        Shipped with ``bolt_rigid_contact``: alone it creates energy on
        mainboltaexpl (IE END +19.20 %). Reach 1 deck key on 1 emitted
        model (+ camry-detailed-v5a, 12 lines).
    section_nodal_thickness_mean : bool
        Write a ``*SECTION_SHELL`` whose Card 2 states T1..T4 with one
        written, nonzero and different from T1 with the MEAN of the
        four (blank / 0.0 = T1; round 8, A4). LS-DYNA integrates the
        thickness at the nodes and its d3hsp reproduces mean(T1..T4) on
        every element: mat_transversely_anisotropic.cup-draw's rigid
        tools weigh 0.0888 / 0.0655 / 0.0555 with T1 and 0.0223 /
        0.0164 / 0.0139 with the mean = LS-DYNA. The one cell feeds
        every consumer (mass, the J row, the lumper, offsets). The 2-D
        ELFORMs are A7's. **On by default.** MEASURED on cup-draw (nt
        4, 150 LS blocks 0 < t <= 0.015): IE / KE history RMS 7.54 /
        65.93 -> 2.89 / 29.15 % of the LS peak, IE END +11.90 -> +6.09 %,
        1.0007x the cycles - the NAMED COST: OpenRadioss's energy error
        grows, mean -4.39 -> -17.88 % (named cost: OpenRadioss's energy
        error counts no interface energy and no TYPE7 VisS damping work -
        ecrit.F:500-511, i7for3.F:1077-1120; with VisS 1e-6 the mean is
        -5.04 %). Reach 2 deck keys on 2 emitted models.
    plane_strain_unit_thickness : bool
        Write a plane-strain ``*SECTION_SHELL`` (ELFORM 13 / 43 / 52 /
        55) with thickness 1.0 (round 8, A7): LS-DYNA ignores Card 2's
        thickness on those formulations and integrates a unit depth
        (Vol I R17 *SECTION_SHELL Remark 6); every consumer of the cell
        follows. **On by default.** MEASURED (starter, nt 4):
        ex_16_thin_shell_elform_13's rigid disk 0.08756308 ->
        0.003447366 = LS-DYNA's 0.34473655E-02, its inertia 0.02225525
        x2 / 0.04451050 = LS-DYNA; the element stays a 3-D plane-stress
        shell (named). Axisymmetric ELFORM 14 / 15 take the 2-D route
        (axisymmetric_2d, round 9); ELFORM 44 is named (LS-DYNA's
        per-radian mass, 2Dlag x157.5). Reach 1 deck key on 1 emitted
        model (bytes) + 4 / 4 by text.
    rigid_element_mass_admas : bool
        Write an ``*ELEMENT_MASS`` on a rigid body's SECONDARY node as
        ``/ADMAS/0`` on that node (round 8, A8): the starter counts it
        at its position, so the body's centre of mass and inertia
        include it. Before, a ``*MAT_RIGID`` body folded every member's
        mass into the ``/RBODY`` Mass field at its main node, which the
        starter moves to the CoG of the secondaries WITHOUT it
        (sph/foam: CoG z 121.4891 vs LS-DYNA's 150.96326, xx / yy
        1.922978 vs 2.238), and a ``*CONSTRAINED_NODAL_RIGID_BODY``
        secondary's mass was dropped altogether. The main node's own
        mass stays in the Mass field; ICoG-4 bodies (TM supersedes) are
        unchanged. **On by default.** MEASURED (starter, nt 4): foam
        CoG z 150.9633, xx / yy 2.238421 = LS-DYNA, mass unchanged,
        engine 12030 = 12030 cycles (inert there); the Yaris roof
        crush's 12 CNRB bodies -38..-86 % -> within 0.54 % of LS-DYNA's
        d3hsp. Reach 5 deck keys on 5 emitted models (foam + 4 Yaris
        giants).
    spotweld_dt_mass_scaling : bool
        Convert ``*MAT_SPOTWELD`` ``DT`` (round 8, A6): Vol II R17
        *MAT_SPOTWELD Remark 4 scales the weld inertias in the first
        step so that their stable step is DT (up only). The TYPE13 step
        is 0.9 min(sqrt(Mass / max K1..3), sqrt(Inertia / (max K4..6 +
        max K2,3 L^2))) (``r2len3.F:221-247``, STI = XM/DT^2 at
        ``:233``), so Mass' = max(Mass, max K1..3 DT^2) and Inertia' =
        max(Inertia, (max K4..6 + max K2,3 L_max^2) DT^2) start the
        weld at 0.9 DT. **On by default.** MEASURED on spotweld.k under
        the opt-in rules 1 + 2 (nt 4): Mass x2.5 (LS-DYNA's own
        factor), Inertia x13.41, last cycle 1332 = LS-DYNA's 1332,
        cycle-0 step 9.000e-7, IE END -33.00 -> -31.18 % - MIXED: RMS
        IE 6.65 -> 6.82 % and RMS KE 23.09 -> 23.66 % of the LS peak
        (1331 LS times to t 0.00119792) are worse; KE END +38.90 ->
        +30.76 %, the weld ruptures at 1.12229e-3 s, 65.3 us before
        LS-DYNA's swforc failure time 1.1876e-3 s (4.2 us earlier than
        without the scaling), the energy error within -0.3 .. +0.2 %.
        Default byte movers 0
        (plates.mat100's DT is inert: its warning says so).
    adaptive_spring_token : bool
        Set each spring token ``/PROP`` MASS (TYPE4 / TYPE8 / TYPE13,
        k2rad's fixed 1e-4) to ``max(1.1e-15, min(1e-4, 2 mu min(1,
        2/n)))`` (round 8, A5), ``mu = m_a m_b / (m_a + m_b)`` the end
        nodes' own masses (the S2 screen's: element mass +
        ``*ELEMENT_MASS``), ``n`` the busier end's token-spring count,
        per unit length on an Ileng 1 property; a rigid,
        connector-ground or DRIVEN end (its GLOBAL fixed / imposed
        translations cover the spring's stiff directions for the WHOLE
        run) counts infinitely heavy, a spring with both ends infinite
        keeps the token, a GUARDED end (no own mass) sets no cap. The
        spring's own step sqrt(M/K) (``r1len3.F:175``) reads the
        PROPERTY mass, so a light compensated end could outrun it
        silently: the fixed token was killed by the energy-error limit
        within 3-6 cycles on three coupons, each behind a NORMAL
        TERMINATION banner. **On by default.** Reach 6
        deck keys on 6 emitted models, one cell each (the Yaris static
        suspension ``/PROP/TYPE4/107020`` 1e-4 -> 5.483321e-7); the 4
        runnable movers' printed rows identical at 1.000x the cycles;
        ex_17 / ex_18 (match) byte-identical. Inert under
        ``--no-spring-token-mass-compensation``.
    imflag0_eigen_explicit : bool
        Convert a deck whose *CONTROL_IMPLICIT_GENERAL states IMFLAG 0
        and whose *CONTROL_IMPLICIT_EIGENVALUE states NEIG 0 on the
        EXPLICIT route (round 8, B1): LS-DYNA runs it explicit
        (tire.d3hsp:1056-1057 'eq.0: explicit analysis', :1316 NEIG 0).
        The route is decided in handlers._resolve_eigen_route, called
        by both handlers, so the cards' order does not matter. **On by
        default.** MEASURED on
        implicit/basic-examples/eigenvalue/tire.k (nt 4): the modal
        recipe stopped at cycle 0 (LOADING DATA); the explicit route
        ends NORMAL in 24329 cycles, END IE +3.93 % / KE -18.30 %, RMS
        2.06 / 2.23 % of the LS peak over the 500 LS times to t 0.1.
        Reach 1 deck key on 1 emitted model. False keeps the modal
        K-export route of 4f5b6e8.
    implicit_smooth_curve_sampling : bool
        On an implicit, non-modal deck write every well-formed
        *DEFINE_CURVE_SMOOTH as a /FUNCT (same id) sampling a sine ramp
        (41 points per ramp, area = DIST) (round 8, B2): the implicit
        imposed-motion path integrates a curve's points
        piecewise-linearly whatever the smoothing flag (fv_imp0.F:209
        FV_IMP -> :333 DINTERI), so /FUNCT_SMOOTH acts as a straight
        ramp there. **On by default.** MEASURED on
        efg/metal-cutting/main.k (nt 4 and 2): ERROR TERMINATION at
        cycle 26 on 13 of 13 straight-ramp runs -> NORMAL in 202 cycles
        on 7 of 7 sine runs - a status, not a score. Reach 1 deck key
        on 1 emitted model. False keeps /FUNCT_SMOOTH.
    elastic_fluid_cp_cutoff : bool
        Write a *MAT_ELASTIC_FLUID stated CP 0.0 as /MAT/HYD_VISC Pmin
        -1e-20, a cut-off at zero (round 8, B5): LS-DYNA keeps the
        stated 0 as its cavitation pressure
        (9.1.acoustic.compartment.hex.d3hsp:3471 'cavitation pressure =
        0.00000E+00') while hm_read_mat06.F:154 reads a Pmin of exactly
        0 as -INFINITY; *MAT_NULL PC 0 gets the same cell (round 7).
        **On by default.** Decided on consistency - the four carriers
        (nvh 8.7 / 9.1 / 9.2 / 9.4) are frequency-domain acoustic
        decks; on 9.4 (nt 4) both cells give the same 18 rows with zero
        energy. Reach 4 deck keys on 4 emitted models. False keeps Pmin
        0 (= -INFINITY), the 4f5b6e8 cell.
    skip_implicit_stub_with_type25 : bool
        Leave out the inert all-parts implicit contact stub on an
        implicit deck whose only contacts take the TYPE25 route, wherever
        a TYPE25 contact is actually WRITTEN (round 8, B6; opt-in since
        the round's validation inverted the default). By default the
        stub stays there, the 4f5b6e8 deck: OpenRadioss builds no
        implicit contact stiffness for a TYPE25 (imp_int_k.F:111-200 has
        no TYPE25 branch; ind_glob_k.F:4601-4605 prints MESSAGE 232; its
        force still enters the residual, intfop2.F:595), so beside a
        TYPE25 the stub is the deck's only implicit contact stiffness and
        without it the run can stop early OR end NORMAL with the load
        path lost. MEASURED (nt 4 = nt 2): on a two-block coupon whose
        TYPE25 contact must carry load the skip turns NORMAL in 11 cycles
        into ERROR TERMINATION at cycle 9 (23 ITERATION DIVERGE, then
        MESSAGE 79); on implicit/basic-examples/springback-i/doorbeam.k
        with its punch driven (round 9, A1) the run without the stub ends
        a NORMAL banner at t 5.434e-4 (24 cycles, 49.4 % of t_end): the
        run stops with the punch at 81.51 of 135 mm. Since round 9 an
        implicit
        *CONTACT_[AUTOMATIC_]NODES_TO_SURFACE is a routed /INTER/TYPE7
        (implicit_n2s_type7), so the flag reaches the ERODING spellings
        and an N2S spelling only under implicit_n2s_type7=False. When the
        writer drops every TYPE25 the stub is written after all. Default
        False.
    shell_in_solid_coupling : bool
        Write *CONSTRAINED_SHELL_IN_SOLID as an /INTER/TYPE18 penalty
        coupling (R14 triage round 8, B10): /SURF/PART/EXT over the
        embedded shell parts, /GRBRIC/PART over the ALE host, Stfval =
        0.1 x K_host x A_seg^2 / V_host (PSSF on the _PENALTY form),
        and - on an *INITIAL_VOID host of the card only - the void
        density (RHO_I = VFACT x RO, the EOS RHO_0 = RO). Round 9 (B4):
        on a deck whose only Lagrangian parts are the embedded shells and
        that emits no other interface, Gap = 0.55 x the mean host edge and
        the engine card /DT/INTER/CST Tsca Tmin (Tmin = 0.5 x Tsca x
        min(host edge / c_host, shortest shell edge / c_shell)); any
        other deck keeps the round-8 Gap 0.5 x without the card (the card
        is global - the round-9 gate measured it adding mass to a TYPE7
        pair's nodes beside the SIS); a DT2MS < 0 deck refuses the card.
        MEASURED on intro-by-j.-day/misc/bird-ale/bird-el.k (nt 4): the
        plate -100 -> -29.06 %, the deck IE +1134.62 -> +39.41 % / KE
        -92.06 -> -42.96 % at 1.140x the cycles (energy error -32.6 ->
        -35.0 %). Default False: the density half fails on both
        *CONSTRAINED_LAGRANGE_IN_SOLID void hosts.
    imflag_curve_restart : bool
        Write one engine file per method segment of an IMFLAG < 0 curve
        (R14 triage round 8, B3 h.2): <stem>_000k.rad carries
        /RUN/<title>/k to the segment's end, /IMPL only in implicit
        segments, /DT only in explicit ones, /RFILE/OFF only in the
        last file; run them in order from one directory (each restarts
        from the previous run's .rst). ConversionResult.engine_paths
        lists them. Default True since round 8 (kept after the campaign
        runner's chain passed gate (b) on ie_shell); False keeps one
        implicit engine file.
    rigid_part_pid_precedence : bool
        When a *CONSTRAINED_NODAL_RIGID_BODY PID equals a *MAT_RIGID part
        id, every part-keyed card (*BOUNDARY_PRESCRIBED_MOTION_RIGID[_LOCAL]
        and its /TH rows, *LOAD_RIGID_BODY, *INITIAL_VELOCITY_RIGID_BODY /
        _GENERATION, gravity, /BCS, /TH) addresses the PART's /RBODY (R14
        triage round 9, A1): LS-DYNA accepts the shared id with Warning
        10177 and drives the part, dyna2rad too (by write order). The CNRB
        keeps its own /RBODY, its _INERTIA velocity and its _SPC. MEASURED
        on implicit/basic-examples/springback-i/doorbeam.k: the punch never
        moved before (DY 0 at every fifth of t_end; 32.30 / 65.32 / 95.32 /
        132.8 / 135.0 mm with the part drive) and IE ended +582.00 %; with
        the part drive alone +53.91 % (RMS 393.31 -> 81.05 % of the LS peak,
        25 LS times in (1e-5, 1.1e-3], nt 4 = nt 2), with the shipped
        default (+ implicit_n2s_type7) -0.78 .. -28.12 %, RMS 7.21 ..
        15.26 % (125 runs at nt 4 and nt 2, run to run on three branches).
        Default True; False restores the 386444e bytes (the CNRB record
        wins).
    implicit_n2s_type7 : bool
        Write an implicit, non-modal *CONTACT_NODES_TO_SURFACE /
        *CONTACT_AUTOMATIC_NODES_TO_SURFACE (not the ERODING spellings) as a
        ONE-WAY /INTER/TYPE7 on the groups the TYPE25 route resolves (R14
        triage round 9, A2): OpenRadioss builds no implicit contact stiffness
        for a TYPE25 (imp_int_k.F:111-200; ind_glob_k.F:4601-4605 MESSAGE
        232). k2rad's TYPE7 cells (Istf 4, Igap 0 with the starter's default
        gap, Inacti from IGNORE, Fric = FS x FSF, Tstart / Tstop = BT / DT);
        where k2rad injects the all-parts implicit stub (an implicit deck
        with no contact of its own) it stays beside the route with the
        contact's friction - beside another contact there is no stub, and
        the warning says so. MEASURED on
        implicit/basic-examples/springback-i/doorbeam.k
        (with the A1 part drive): IE END -0.78 .. -28.12 %, RMS 7.21 ..
        15.26 % of the LS peak over the 25 LS times in (1e-5, 1.1e-3],
        125 runs of the same bytes at nt 4 and nt 2, run to run on three
        branches (102 at -27.76 .. -28.12 %, 21 at -15.85 .. -16.27 %, two
        single nt-4 runs at -8.36 / -0.78 %), where the TYPE25 ended
        +53.91 % / RMS 81.05 %.
        With four contact nodes on a coarse rigid base the outcome depends
        on the geometry: one coupon ends NORMAL with the block through where
        the TYPE25 stops with MESSAGE 79, another holds where the TYPE25
        lets the block through, and with the nodes over the base's corners
        both let it through. Default True; False keeps the TYPE25 (the
        386444e bytes).
    implicit_rigid_gravity_nodes : bool
        On an implicit deck keep *MAT_RIGID parts' own nodes in the /GRAV
        group beside their /RBODY main node (R14 triage round 9, A4): the
        main's gravity alone leaves the body frozen in an implicit run.
        MEASURED on introduction/Introduction/example-16/
        ex_16_thin_shell_elform_13.k with elform7_beam_thickness_section:
        NORMAL 1101 cycles, kinetic energy at the fifths of t_end +0.42 /
        +0.20 / +0.14 / +60.22 / +439.67 % against LS-DYNA (the last two =
        the unconverted *CONTACT_2D; 1100 LS times in (1e-4, 0.11], nt 4 = nt
        2), where the main-only group leaves the disk frozen (-100 % at
        every fifth). Explicit decks keep the main-node group. Default True.
    elform7_beam_thickness_section : bool
        Give a *SECTION_BEAM ELFORM 7 (2-D plane-strain beam) whose parts are
        all rigid the section Area = TS1 x 1, Iyy = Izz = TS1^3 / 12, Ixx =
        Iyy + Izz instead of the zero section the starter refuses (R14 triage
        round 9, A5) - NOT LS-DYNA's: ex_16's ELFORM 7 wall has the LS rigid
        mass 0.15414498E-10, 5.68x rho x TS1 x L. On an implicit deck only
        together with implicit_rigid_gravity_nodes (alone it runs with the
        rigid body frozen). A deformable ELFORM 7 member and ELFORM 8 keep
        the refusal. Default True.
    spc_vector_frames : bool
        Write a *BOUNDARY_SPC whose CID is a *DEFINE_COORDINATE_VECTOR in that
        frame's /SKEW/FIX (R14 triage round 9, A6): LS-DYNA applies the DOFs
        in the local system; before, the constraint went to the GLOBAL system
        behind a false 'not found'. One helper (writer/loads.spc_cid_skew) for
        all five consumers. MEASURED on control_adaptive.cylinder (explicit,
        nt 4, 271 = 271 cycles): the constrained radial displacement 0.3352 ->
        1.8e-8 mm, the free-DOF reaction 4611 -> 0.024 N (LS-DYNA 0).
        Default True.
    prescribed_motion_sf_default : bool
        Read a stated SF 0.0 on *BOUNDARY_PRESCRIBED_MOTION_* as LS-DYNA's
        default 1.0 (R14 triage round 9, A8; Vol I R17 p.759, Appendix V
        p.73-9): a NODE / SET row stays a /BCS hold only for a zero motion
        (VAD 0 / 2 on a zero curve, or no curve), else it is imposed with
        Fscale 1; a RIGID row writes Fscale 1 (bytes only: the OpenRadioss
        starter already reads 0 as 1.0, read_impdisp.F:239). Default True;
        False keeps the stated 0.
    rigid_local_shared_skew : bool
        On an implicit deck write a *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL
        drive in the skew of the body's own CMO -1 /BCS (R14 triage round 9,
        A9; explicit decks unchanged) when the frames coincide at t 0 (every
        axis pair aligned, signed), the /BCS holds every rotation and no DOF
        is held and driven: two skew ids on one node make the implicit
        solver impose a frame-dependent wrong displacement with a 0.0 %
        energy error (a
        two-card coupon: x0.750 / x-0.5625 of the motion in two oblique
        frames, x1.000 in one skew) and the starter print WARNING 312.
        Default True.
    modal_acoustic_void : bool
        On a modal (/IMPL/PRINT/STIF) deck write a part on a refused
        *MAT_ACOUSTIC as /MAT/VOID with RHO_I = RO, E 0, nu 0 (R14 triage round
        9, A7): the part resolves and the structure's stiffness is exported,
        where the refusal stopped the starter (ERROR 179). The void carries
        no pressure DOF, no fluid stiffness and no acoustic coupling (and,
        on an 8-point brick, no nodal mass), so the modes are the
        structure's alone. A time-domain deck keeps the refusal (a void
        there carries no wave and removes the fluid's radiation sink: on 8.3
        the structure's energy does not decay, IE RMS 168.69 %). Default
        True.
    mixed_main_thickness_gap : bool
        Opt-in (R14 triage round 9, A10): on an AUTOMATIC contact's
        /INTER/TYPE7 whose main mixes shells and solids and states no gap,
        write Igap 3 with Gapmin = half the thinnest main shell (capped at
        half the smallest main edge) - LS-DYNA offsets the shells by t/2 and
        the solids by nothing. Measured: mainboltaexpl's bolt 2.19560 ->
        1.99461 mm (LS 1.81686); COST: EXP_SC_PRELOAD's contact energy
        2916 -> 7557 at END (LS sliding 1758.5). Default False.
    implicit_bfgs : bool
        Opt-in (R14 triage round 9, A12): Quasi-Newton BFGS (/IMPL/NONLIN/2)
        with no /IMPL/QSTAT (unless qstat_dtscal_stated) on an implicit deck
        whose NSOLVR is 12 or blank. One carrier (ex_06_beam_elform_1); the
        failure can be SILENT at nt 4 and nt 2 (doorbeam's default A1 + A2
        bytes: a NORMAL banner in all 96 runs, nonsense internal energy in
        13 - 4 of 51 at nt 4, 9 of 45 at nt 2), so check the energies before
        using a run.
        Default False.
    weld_trajectory_impflux : bool
        Convert a *BOUNDARY_THERMAL_WELD_TRAJECTORY (R14 triage round 9, B1)
        whose screen accepts it - IFORM 2, ENFOR 0, Q > 0, SOLN 1, RELVEL 0,
        no NSID1 node on a driven / loaded part, NSID2 < 0 with every NSID1
        edge aimed, PTYP 1 / 2 naming all-solid parts, its *MAT_THERMAL_CWM
        born before t 0 - into windowed /IMPFLUX VOLUMIC cards: each seam
        brick gets its in-window mean of the IFORM-2 double ellipsoid (64
        sub-points, 10 mid-point instants), the source OFF past the end of
        NSID1; the CWM becomes the part's live /HEAT/MAT (TD_LC line), the
        engine /ANIM/DT is capped at max(d3plot dt, ENDTIM / 100) when more
        than 1000 frames are requested, and the TEMP /TH/NODE group is the
        NSID1 + *DATABASE_HISTORY_NODE nodes. A refused card keeps the
        386444e output with one named sentence; a CWM never converts alone.
        MEASURED on 05_5_1 (= 05_4_1, one LS model; nt 4): NORMAL in 66 323
        cycles, deposit -0.30 % of LS-DYNA's source energy, the path nodes
        END -11.81 / -13.46 / -12.22 % of their rise; 720-2075 s of engine
        time. Default True; False restores the 386444e output.
    weld_trajectory_window : float
        The /IMPFLUX window of the conversion above, in seconds (default
        0.25, the measured one); must be > 0 and finite (ValueError).
    axisymmetric_2d : bool
        Write an all-ELFORM-14 / 15 *SECTION_SHELL deck as an OpenRadioss 2-D
        AXISYMMETRIC deck (R14 triage round 9, B2): /ANALY N2D3D 1, every
        node (x, y, 0) written (0, x, y) (Radioss Y = the radius, Z = the
        axis), /SHELL -> /QUAD on /PROP/SOLID Isolid 2, the /BCS and the
        prescribed-motion directions permuted, /RBODY J = 0, /TH/QUAD. Refused
        by name (the deck stays 3-D) for another element family, a 3-node
        shell, any *CONTACT_*, a node off the xy-plane or at x < 0, ELFORM 14
        and 15 together, ELFORM 44 or an unmapped card. MEASURED on
        metal-forming: starter TOTAL MASS 5.7080700E-06 = LS-DYNA per radian
        (the 3-D route -77.78 %). Default True.
    positive_dt2ms_mass_scaling : bool
        On a ROUTED 2-D deck, a positive *CONTROL_TIMESTEP DT2MS multiplies
        each deformable material's density by max(1, (DT2MS / dt0)^2), dt0 =
        OpenRadioss's own cycle-0 2-D step of its quads in closed form, so
        the run starts at DT2MS (round 9, B2); /DT/NODA/CST is never written
        on a 2-D deck. MEASURED on metal-forming (nt 4): a timeout -> NORMAL
        in 24 807 cycles, IE END -0.45 %, RMS 0.24 % of the LS peak (the KE
        is the scaled-mass KE). Default True.
    plane_stress_unit_thickness : bool
        Write a 2-D plane-stress *SECTION_SHELL (ELFORM 12) whose Card 2
        states no thickness (T1..T4 all 0 / blank) with thickness 1.0 (R14
        triage round 9, B3): LS-DYNA integrates a unit thickness there
        (main_fsi's d3hsp: rigid mass 0.23410459 = rho 1.2 x area 0.19508716
        x 1.0000008), although Remark 6 does not list ELFORM 12; a stated T1
        > 0 is kept. MEASURED on main_fsi: starter 117 ERROR(S) -> 0, TOTAL
        MASS 0.2341045880 = LS-DYNA (a status move: the body is fixed under a
        skipped ICFD fluid). Default True.
    load_curve_offscale_zero : bool
        Point a MECHANICAL applied-load consumer (/IMPVEL, /IMPDISP, /IMPACC,
        /CLOAD, /PLOAD, /GRAV) at a copy of its /FUNCT that is zero past its
        last abscissa and - for a DATTYP-0 curve with OFFA > 0 and SFA 0 / 1 -
        before OFFA, where OpenRadioss would extrapolate it nonzero inside
        the consumer's window (a curve that starts after t 0 without OFFA
        keeps its head) (R14 triage round 9, B5): LS-DYNA
        *DEFINE_CURVE Remark 4a adds (0, 0) and (0.999 OFFA, 0) for DATTYP 0
        with OFFA > 0, Remark 5 sets load curves to zero off scale, while
        OpenRadioss extends the first / last segment (finter.F:235-273). The
        deck's own curves are never changed (material, preload and thermal
        consumers keep them). MEASURED: the aniso cup-draw's punch no longer
        starts backward but the deck IE is WORSE (END +6.09 -> +13.10 %, RMS
        2.89 -> 5.57 %; KE END -40.31 -> -42.14 %);
        thick.k's punch stops at -10 mm as LS-DYNA's, KE END +91.96 ->
        +23.42 %. Default True.
    ale_flow_tracking : bool
        OPT-IN (R14 triage round 9, B8): write ``*ALE_REFERENCE_SYSTEM_GROUP``
        PRTYPE 4 (the ALE grid moving with the material's mass-weighted mean
        velocity about its centre of mass) as ``/ALE/GRID/FLOW-TRACKING`` in
        ``_0000.rad`` after ``/DEF_SOLID`` (I_def -1 for BCEXP 7, I_rot +1 /
        -1 for BCROT 0 / 7; ``alew7.F:186-227``); one GROUP card naming every
        ALE part, PRID 0, ICR 0, and BCTRAN already held by the ALE nodes'
        own /BCS - anything else is refused by name and stays skipped.
        ``/BEGIN`` stays 2022 (WARNING 100211, the card read). MEASURED on
        bird_B (nt 4): END IE +1484.66 -> +17.00 %, IE RMS 1189.95 ->
        27.74 %, but the deck KE RMS 253.09 -> 749.89 % (the void is
        converted at full density) - a MIXED row, hence opt-in. Default
        False.
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
        That residual is not the velocity — it is the ``/RBODY``'s own lumped
        rotary inertia (starter ``NEW INERTIA`` 0.2642894E-02 against
        LS-DYNA's 0.1977E-02, the difference being exactly
        ``4 × (m/4)(A + t²)/12 = 6.65667e-4`` per diagonal). The ``/RBODY``
        ``J`` cells are ADDITIVE (``inirby.F:154-168``), so ``J = −ΣIN`` (the
        body's shell nodes' lumped rotary inertia) is written BY DEFAULT
        since round 7 (``rigid_shell_rotary_inertia``); the flag's own pass
        writes it only where the default did not (with
        ``rigid_shell_rotary_inertia=False``, on every body it re-points, as
        in round 6): ``NEW INERTIA``
        0.1977227E-02 = LS-DYNA's, cycle-0 KE **189.96** (LS 189.962), final
        KE −1.97 % (an END value: the KE history RMS goes 17.5 % → 11.6 % of
        the LS peak), 1.156x the cycles; the IE is not fixed (the joint path's
        99.9 % energy error). **Opt-in** because exactly one carrier with an LS-DYNA reference
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
        qstat_dtscal_stated=qstat_dtscal_stated,
        arclength_riks=arclength_riks,
        zero_tolerance_ectol=zero_tolerance_ectol,
        implicit_constant_step=implicit_constant_step,
        discrete_offset=discrete_offset,
        spring_token_mass_compensation=spring_token_mass_compensation,
        shell_to_solid_rbody=shell_to_solid_rbody,
        generalized_weld_butt=generalized_weld_butt,
        initial_void_floor=initial_void_floor,
        weld_exponents=weld_exponents,
        constrained_linear=constrained_linear,
        constrained_global=constrained_global,
        spotweld_node_synthesis=spotweld_node_synthesis,
        beam_contact_secondary=beam_contact_secondary,
        shell_offset_gapmin=shell_offset_gapmin,
        rigid_shell_rotary_inertia=rigid_shell_rotary_inertia,
        spotweld_shear_yield=spotweld_shear_yield,
        spotweld_efail_displacement=spotweld_efail_displacement,
        implicit_tshell_solid=implicit_tshell_solid,
        corotational_orthotropic=corotational_orthotropic,
        mat_null_pc_mu=mat_null_pc_mu,
        joint_screw_gjoint=joint_screw_gjoint,
        rigid_local_constraints=rigid_local_constraints,
        bcs_union=bcs_union,
        bolt_rigid_contact=bolt_rigid_contact,
        fixed_curve_columns=fixed_curve_columns,
        section_nodal_thickness_mean=section_nodal_thickness_mean,
        plane_strain_unit_thickness=plane_strain_unit_thickness,
        rigid_element_mass_admas=rigid_element_mass_admas,
        spotweld_dt_mass_scaling=spotweld_dt_mass_scaling,
        adaptive_spring_token=adaptive_spring_token,
        imflag0_eigen_explicit=imflag0_eigen_explicit,
        implicit_smooth_curve_sampling=implicit_smooth_curve_sampling,
        elastic_fluid_cp_cutoff=elastic_fluid_cp_cutoff,
        skip_implicit_stub_with_type25=skip_implicit_stub_with_type25,
        shell_in_solid_coupling=shell_in_solid_coupling,
        imflag_curve_restart=imflag_curve_restart,
        rigid_part_pid_precedence=rigid_part_pid_precedence,
        implicit_n2s_type7=implicit_n2s_type7,
        implicit_rigid_gravity_nodes=implicit_rigid_gravity_nodes,
        elform7_beam_thickness_section=elform7_beam_thickness_section,
        spc_vector_frames=spc_vector_frames,
        prescribed_motion_sf_default=prescribed_motion_sf_default,
        rigid_local_shared_skew=rigid_local_shared_skew,
        modal_acoustic_void=modal_acoustic_void,
        mixed_main_thickness_gap=mixed_main_thickness_gap,
        implicit_bfgs=implicit_bfgs,
        weld_trajectory_impflux=weld_trajectory_impflux,
        weld_trajectory_window=weld_trajectory_window,
        axisymmetric_2d=axisymmetric_2d,
        positive_dt2ms_mass_scaling=positive_dt2ms_mass_scaling,
        plane_stress_unit_thickness=plane_stress_unit_thickness,
        load_curve_offscale_zero=load_curve_offscale_zero,
        ale_flow_tracking=ale_flow_tracking,
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
    # round 8, B3 (h.2): one engine text per run - several only for an
    # IMFLAG < 0 deck under --imflag-curve-restart
    engine_texts = build_engines(state)
    engine_paths = [engine_path] + [f"{output_stem}_{k:04d}.rad"
                                    for k in range(2, len(engine_texts) + 1)]
    stale = _stale_engine_files(output_stem, len(engine_texts))
    if stale:
        # Named, never deleted (B3-b). Every <stem>_k.rad with k past this
        # conversion's last engine file, not only _0002 (the fix round,
        # code-sweep F9): an earlier, LONGER chain leaves _0003 and up, and
        # a loop over every engine file present would run them.
        state.warn(
            f"Stale engine file(s) {', '.join(stale)} from an earlier "
            "--imflag-curve-restart conversion sit beside this "
            f"{len(engine_texts)}-engine-file output; delete them before "
            "running the engine files by hand.")

    # 4. Write files. utf-8 regardless of locale (an ASCII/C locale would
    # UnicodeEncodeError on a non-ASCII part title); create the output
    # directory when the stem points into one that does not exist yet.
    _report(0.98, "Saving files")
    out_dir = Path(starter_path).parent
    if out_dir and not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
    with open(starter_path, "w", newline="\n", encoding="utf-8") as fh:
        fh.write(starter_text)
    for path, text in zip(engine_paths, engine_texts):
        with open(path, "w", newline="\n", encoding="utf-8") as fh:
            fh.write(text)

    # 5. Auto-save warnings/skips for later investigation (large decks scroll the
    #    console). Written next to the output as <stem>_conversion.log.
    log_path = (_write_conversion_log(output_stem, input_path, state,
                                      engine_paths)
                if write_log else None)

    _report(1.0, "Done")
    return ConversionResult(
        starter_path=starter_path,
        engine_path=engine_path,
        warnings=list(state.warnings),
        skipped_keywords=sorted(set(state.skipped_keywords)),
        recognized_not_emitted=sorted(state.recognized_not_emitted),
        log_path=log_path,
        engine_paths=engine_paths,
    )


__all__ = ["convert", "ConversionResult", "__version__"]
