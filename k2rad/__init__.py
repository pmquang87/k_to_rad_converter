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
from typing import Callable, Dict, List, Optional, Tuple

from .parser import parse_k_file, PARSER_WARNINGS
from .handlers import dispatch
from .state import ConversionState, ContactAutoSingle, ConvertOptions
from .writer.common import SHELL_FORMULATIONS
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
            title="auto_implicit_stabilization_self_contact",
            ssid=0, sstyp=0, fs=0.0, fd=0.0, bt=0.0, dt=1.0e28,
        )
    )
    state.warn(
        "Implicit model has no contact interface — the OpenRadioss engine "
        "segfaults in implicit setup without one. Injected an inert all-parts "
        f"self-contact (/INTER/TYPE7 id {inter_id}); it carries no load unless "
        "parts actually touch. Remove it if you define real contact."
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
    tet10_to_tet4: bool = False,
    auto_gapmin: bool = False,
    gapmin_factor: float = 0.8,
    fixpoint_count: int = 100,
    deformable_contact_recipe: bool = False,
    emit_eig: bool = False,
    blast_ground: str = "auto",
    rigid_cog_master: bool = True,
    zero_density_floor: bool = True,
    law106_shell_restate: bool = True,
    zero_t0_sentinel: bool = True,
    write_restart: bool = False,
    ams: bool = False,
    shell_formulation: str = "qbat",
    dt_del: Optional[float] = None,
    he_bunreacted: Optional[float] = None,
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
    fixpoint_count : int
        Number of evenly spaced /IMPL/DT/FIXPOINT milestones the implicit
        time-step controller is forced to land on (k/N × the run end, for
        k = 1 … N), so an animation / time-history state is produced at each
        instead of wherever the variable step falls. The OpenRadioss engine caps
        the list at 100, so this is clamped to 1…100; 0 disables the card.
        Default 100 (a point every 1% of the run). Implicit decks only.
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
        law just produced (``thermexpc.F:283-300``), while
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
        its value and its consequence (the unburnt cells then carry
        ``P = K·mu``, ``jwl51.F:197``, where an LS-DYNA ``BETA = 0`` card
        carried nothing at all).
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
        tet10_to_tet4=tet10_to_tet4,
        auto_gapmin=auto_gapmin,
        gapmin_factor=gapmin_factor,
        fixpoint_count=fixpoint_count,
        deformable_contact_recipe=deformable_contact_recipe,
        emit_eig=emit_eig,
        blast_ground=str(blast_ground).strip() or "auto",
        rigid_cog_master=rigid_cog_master,
        zero_density_floor=zero_density_floor,
        law106_shell_restate=law106_shell_restate,
        zero_t0_sentinel=zero_t0_sentinel,
        write_restart=write_restart,
        ams=ams,
        shell_formulation=shell_formulation,
        dt_del=dt_del,
        he_bunreacted=he_bunreacted,
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
    from .writer import _flatten_set_adds, _screen_provisional_elements
    _screen_provisional_elements(state)

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
