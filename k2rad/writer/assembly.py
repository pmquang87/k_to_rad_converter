"""Top-level assemblers: build_starter / build_engine and the engine-card emitters."""

from __future__ import annotations

from typing import List
from ..state import ConversionState
from .common import HDR, _f, _i
from .materials import (
    _make_functions,
    _make_materials,
    _resolve_define_tables,
    _resolve_mat_plas_tab,
    _resolve_mat_power_law,
)
from .mesh import (
    _assign_ortho_props,
    _assign_hourglass_props,
    _downgrade_tet10_to_tet4,
    _make_extra_groups,
    _make_nodes,
    _make_parts_and_elements,
    _make_properties,
    _make_skews,
    _normalize_tet10_ordering,
    _screen_sliver_tets,
    _snap_tet10_midsides,
    _synthesize_vector_skews,
)
from .contacts import (
    _make_force_transducers,
    _make_interfaces,
    _make_tied_interfaces,
    _recipe_active,
)
from .rbody import _make_cnrb_rbodies, _make_probe_rbody, _make_rbodies
from .loads import (
    _make_added_masses,
    _make_bcs,
    _make_body_loads,
    _make_constrained_spotweld_springs,
    _make_damping,
    _make_discrete_springs,
    _make_free_node_constraints,
    _make_gravity_loads,
    _make_grounding_springs,
    _make_imposed_motions,
    _make_imposed_motions_set,
    _make_inivel,
    _make_initial_velocity,
    _make_initial_velocity_generation,
    _make_modal_dummy_cload,
    _make_node_cloads,
    _make_pressure_loads,
    _make_rigid_walls,
    _make_rlinks,
    _make_spotweld_beam_connectors,
    _make_starter_cloads,
    _synthesize_rwall_moving_nodes,
)
from .blast_ale import (
    _make_blast_loads,
    _make_control_ale_notes,
    _make_detonations,
    _make_ebcs,
    _make_fsi_coupling,
    _make_inivol_notes,
)
from .inistate import _make_cross_sections, _make_initial_stresses, _make_starter_th_sectio
from .output import (
    _make_ams,
    _make_analysis_defaults,
    _make_eig,
    _make_freq_domain_notes,
    _make_header,
    _make_skipped_comment,
    _make_starter_th,
    _make_starter_th_inter,
    _make_starter_th_node_reac,
    _make_starter_th_node_spc,
    _make_starter_th_surf,
    _make_title,
    _spc_constrains_rotations,
)

__all__ = [
    "_make_engine_modal",
    "_make_engine_header",
    "_make_engine_output",
    "_make_engine_implicit",
    "_make_engine_cpu",
    "build_starter",
    "_StarterContext",
    "_progress_marker",
    "_starter_section_registry",
    "_make_engine_restart",
    "_make_engine_timestep",
    "build_engine",
]


def _make_engine_modal(state: ConversionState) -> List[str]:
    """Engine cards for a normal-modes run.

    Default (validated stiffness-export recipe): the open-source OpenRadioss
    engine ships the /EIG eigensolver only as a no-op stub (the kernel is gated
    behind an undefined DNC build macro and the real com/eig/*.F source is not
    released), so the engine cannot compute modes itself. Instead the deck runs
    ONE linear implicit step (/IMPL/LINEAR, /IMPL/DTINI = the run end) and the
    undocumented /IMPL/PRINT/STIF keyword (engine freimpl.F; data line
    ``PRSTIFMAT_TOL PRSTIFMAT_NC PRSTIFMAT_IT`` = ``0 1 0``) makes MUMPS write
    the EXACT assembled stiffness matrix it factorizes to
    ``local_stiffness_matrix_domain0`` (run np=1). The eigenproblem is then
    solved offline with scipy — see tools/modal_solve.py. Validated on the W14
    bogie: a static solve from the exported K matches the engine to 0.000%, and
    the eigenfrequencies match an explicit impulse ring-down FFT.

    With ``--eig`` (options.emit_eig): the classic one-shot /EIG eigensolve
    engine for commercial Altair Radioss (which has the real /EIG kernel).
    """
    if state.options.emit_eig:
        return [
            "#-  MODAL (normal-modes) ENGINE",
            "#   /EIG (starter) requests the eigenmodes; /IMPL/LINEAR does the single",
            "#   linear factorization the shift-invert eigensolve needs. No time march.",
            "#   NOTE: only commercial Altair Radioss can solve /EIG — the open-source",
            "#   engine segfaults at init (eigensolver kernel not in the source release).",
            "/IMPL/LINEAR",
            "/IMPL/PRINT/NONL/-1",
            "/IMPL/SOLVER/2",
            "  0 0 0 0",
            "/IMPL/MUMPS/AUTOCORE",
            "#",
        ]
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    return [
        "#-  MODAL (normal-modes) ENGINE - stiffness-matrix export recipe",
        "#   The open-source OpenRadioss engine cannot solve /EIG, so this deck runs",
        "#   ONE linear implicit step and /IMPL/PRINT/STIF makes MUMPS print the",
        "#   assembled stiffness matrix to 'local_stiffness_matrix_domain0'.",
        "#   Run np=1, then solve the eigenproblem offline (needs numpy+scipy):",
        "#       python tools/modal_solve.py <run_dir>/local_stiffness_matrix_domain0 <model.k>",
        "#   Stock-engine caveats (both fixed by 1-line patches, see k2rad README):",
        "#     * the matrix is printed with FORMAT E10.2 (2 significant digits) ->",
        "#       ~1% stiffness rounding, ~0.5% eigenfrequency error;",
        "#     * after '--STIFFNESS MATRIX IS PRINTED--' the np=1 run can hang in an",
        "#       O(NZ^2) domain-merge scan - kill it; the per-domain file is complete.",
        "/IMPL/LINEAR",
        "/IMPL/PRINT/NONL/-1",
        "/IMPL/PRINT/STIF",
        "0 1 0",
        "/IMPL/SOLVER/2",
        "  0 0 0 0",
        "/IMPL/MUMPS/AUTOCORE",
        "/IMPL/DTINI",
        f"{endtim:.6G}",
        "#",
    ]


def _make_engine_header(state: ConversionState) -> List[str]:
    import re as _re
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    safe_title = _re.sub(r"[^A-Za-z0-9_-]", "_", state.model_title)[:40]
    return [f"/RUN/{safe_title}/1", f"{endtim:.6G}", "#"]


def _make_engine_output(state: ConversionState) -> List[str]:
    lines: List[str] = []
    dt_th = (state.db_nodout_dt or state.db_elout_dt or state.db_glstat_dt
             or state.db_matsum_dt or state.db_spcforc_dt
             or state.db_ncforc_dt or state.db_blstfor_dt
             or state.db_rwforc_dt or state.db_secforc_dt or 1e-3)
    lines += ["/TFILE", f"{dt_th:.6G}", "#", "/PRINT/-1", "#"]

    dt_anim = 0.0
    if state.db_d3plot:
        dt_anim = state.db_d3plot.dt
        if dt_anim == 0.0 and state.db_d3plot.npltc > 0:
            endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
            dt_anim = endtim / state.db_d3plot.npltc
    if dt_anim == 0.0:
        dt_anim = (state.ctrl_termination.endtim / 40.0
                   if state.ctrl_termination else 0.01)
    lines += ["/ANIM/DT", f"0. {dt_anim:.6G}"]

    ext = state.db_extent_binary

    # ── Vector outputs ────────────────────────────────────────────
    lines.append("/ANIM/VECT/DISP")
    lines.append("/ANIM/VECT/VEL")
    lines.append("/ANIM/VECT/ACC")
    lines.append("/ANIM/VECT/CONT")
    lines.append("/ANIM/VECT/CONT2")
    lines.append("/ANIM/VECT/PCONT")
    if state.db_spcforc_dt and state.bcs_spcs:
        # *DATABASE_SPCFORC: constraint-reaction nodal vectors (the /TH/NODE
        # REAC* channels carry the per-node time history; see writer starter).
        lines.append("/ANIM/VECT/FREAC")
        if _spc_constrains_rotations(state):
            lines.append("/ANIM/VECT/MREAC")
    if state.db_blstfor_dt and state.blast_segment_loads:
        # *DATABASE_BINARY_BLSTFOR: the blast loading as external nodal force
        # vectors (/LOAD/PBLAST accumulates into FEXT — engine pblast_1.F).
        lines.append("/ANIM/VECT/FEXT")

    # ── Shell tensor outputs (membrane / upper / lower) ───────────
    lines.append("/ANIM/SHELL/TENS/STRESS/MEMB")
    lines.append("/ANIM/SHELL/TENS/STRESS/UPPER")
    lines.append("/ANIM/SHELL/TENS/STRESS/LOWER")
    lines.append("/ANIM/SHELL/TENS/STRAIN/MEMB")
    lines.append("/ANIM/SHELL/TENS/STRAIN/UPPER")
    lines.append("/ANIM/SHELL/TENS/STRAIN/LOWER")
    lines.append("/ANIM/SHELL/EPSP/UPPER")
    lines.append("/ANIM/SHELL/EPSP/LOWER")

    # ── Solid (brick) tensor outputs ──────────────────────────────
    lines.append("/ANIM/BRICK/TENS/STRESS")
    lines.append("/ANIM/BRICK/TENS/STRAIN")

    # ── Element scalar outputs ────────────────────────────────────
    lines.append("/ANIM/ELEM/EPSP")
    lines.append("/ANIM/ELEM/VONM")
    lines.append("/ANIM/ELEM/ENER")
    lines.append("/ANIM/ELEM/THICK")
    if ext and ext.shge:
        lines.append("/ANIM/ELEM/HOUR")
    # Tabulated damage models (/FAIL/TAB2 GISSMO, /FAIL/TAB1 + /FAIL/FLD from
    # *MAT_123 EPSTHIN/EPSMAJ) write the damage parameter D to the anim (and
    # hence d3plot) only when this channel is requested. This is the OpenRadioss
    # counterpart of raising NEIPH for GISSMO in LS-DYNA — NEIPH itself has no
    # effect on the OpenRadioss output path.
    if state.fail_gissmo or any(m.epsthin > 0.0 or m.epsmaj != 0.0
                                for m in state.mat_plas_tab.values()):
        lines.append("/ANIM/ELEM/DAMG")

    # ── Nodal scalar outputs ──────────────────────────────────────
    lines.append("/ANIM/NODA/DT")
    lines.append("/ANIM/NODA/DMAS")
    if state.db_blstfor_dt and state.blast_segment_loads:
        # *DATABASE_BINARY_BLSTFOR: nodal blast-pressure fringe (element
        # /LOAD/PBLAST pressures averaged onto the loaded-surface nodes).
        lines.append("/ANIM/NODA/PEXT")

    # ── Spring force output ───────────────────────────────────────
    lines.append("/ANIM/SPRING/FORC")

    lines.append("#")
    return lines


def _make_engine_implicit(state: ConversionState) -> List[str]:
    if state.is_modal:
        # Normal-modes (/EIG) → one-shot linear eigensolve, not the QSTAT/NONLIN
        # time-marching engine below.
        return _make_engine_modal(state)
    if not state.is_implicit:
        return []
    gen  = state.ctrl_implicit_gen
    dyn  = state.ctrl_implicit_dyn
    auto = state.ctrl_implicit_auto

    dt0_in = gen.dt0    if gen  and gen.dt0    > 0 else 0.01
    dtmax  = auto.dtmax if auto and auto.dtmax > 0 else 0.0
    iteopt = auto.iteopt if auto else 0

    # For dynamic implicit with rigid bodies that have free DOFs (only contact-
    # constrained), the K_eff = K + M/(β·Δt²) needs a small Δt for the mass
    # contribution to stabilize the matrix. LS-DYNA's DT0=0.05 is too large
    # for OpenRadioss's MUMPS direct solver on this large model (568k DOFs)
    # with tiny rigid-body masses (~0.27 g). Use a much smaller initial step
    # so M/(β·Δt²) provides ~2500× more stabilization. The auto time-step
    # control (/IMPL/DT/2) will grow Δt back up as iterations converge.
    is_dynamic_pre = dyn and dyn.imass > 0
    dt0 = min(dt0_in, 1e-3) if is_dynamic_pre else dt0_in
    dtmin  = auto.dtmin if auto and auto.dtmin > 0 else max(dt0 * 1e-4, 1e-10)

    # /IMPL/NONLIN/N data line (Reference Guide p.2969-2970): L_A  Itol  Toli
    #   L_A  = max iterations between stiffness-matrix reforms (0 -> 6 for the
    #          direct/MUMPS solver; smaller = fresher tangent). Default 2 here for
    #          robust convergence on rigid-body-contact models (the default 6 left
    #          the tangent too stale: |r|/|r0| plateaued ~7e-3 and never dropped).
    #   Itol = termination criterion (1=energy, 2=force, 3=displacement).
    #   Toli = tolerance. The force default is 5e-3; we use 1e-2 (Altair's own
    #          combined-criteria force default), which clears the ~7e-3 residual
    #          plateau seen when a free rigid body engages contact.
    # Overridable from LS-DYNA *CONTROL_IMPLICIT_SOLUTION: ilimit -> L_A, and
    # rctol/ectol/dctol -> Itol(2/1/3) + Toli (whichever tolerance the user set).
    sol = state.ctrl_implicit_sol
    l_a, itol, toli = 2, 2, 0.01
    if sol:
        if sol.ilimit and sol.ilimit > 0:
            l_a = sol.ilimit
        # OpenRadioss Toli is a RELATIVE convergence tolerance, so a sane value is
        # 0 < Toli < 1. Accept the tightest LS-DYNA tolerance the user actually set
        # but ignore implausible values (>= 1.0): those do not come from a real
        # "100%+ tolerance" but from a mis-aligned fixed-format card — e.g. an
        # all-blank leading card in *CONTROL_IMPLICIT_SOLUTION collapses (blank
        # lines are dropped during parsing), shifting the next card's columns so a
        # stray value lands in the dctol slot. Falling back to the robust default
        # avoids silently emitting a useless tolerance (Toli=2.0 => the solver
        # "converges" at iteration 1 and the reaction force is meaningless).
        if sol.rctol and 0.0 < sol.rctol < 1.0:      # force (LS-DYNA rctol)
            itol, toli = 2, sol.rctol
        elif sol.ectol and 0.0 < sol.ectol < 1.0:    # energy (LS-DYNA ectol)
            itol, toli = 1, sol.ectol
        elif sol.dctol and 0.0 < sol.dctol < 1.0:    # displacement (LS-DYNA dctol)
            itol, toli = 3, sol.dctol
        for name, val in (("rctol", sol.rctol), ("ectol", sol.ectol), ("dctol", sol.dctol)):
            if val and val >= 1.0:
                state.warn(
                    f"*CONTROL_IMPLICIT_SOLUTION {name}={val:g} is >= 1.0 (not a valid "
                    "relative tolerance); ignored. This usually means an all-blank "
                    "leading card shifted the fixed-format columns — check the card. "
                    f"Using robust /IMPL/NONLIN default Toli={toli:g}.")
    lines: List[str] = ["/IMPL/NONLIN/1", "# L_A Itol Toli",
                        f"  {l_a} {itol} {toli:g}"]

    # Per OpenRadioss 2022 Reference Guide (pages 2942-2943):
    #   /IMPL/DYNA/1 = HHT method, ONE parameter α (-1/3 < α < 0)
    #   /IMPL/DYNA/2 = Newmark method, TWO parameters (γ, β)
    # LS-DYNA's *CONTROL_IMPLICIT_DYNAMICS provides γ and β (Newmark), so
    # we MUST use /IMPL/DYNA/2 — using /IMPL/DYNA/1 with two values is wrong
    # and the matrix factorization then fails.
    is_dynamic = dyn and dyn.imass > 0
    if is_dynamic:
        gamma = dyn.gamma if dyn.gamma > 0 else 0.5
        beta  = dyn.beta  if dyn.beta  > 0 else 0.25
        lines += ["/IMPL/DYNA/2", f" {gamma:.6G}  {beta:.6G}"]
    else:
        # /IMPL/QSTAT/DTSCAL: inertia-stabilization scale; stabilization grows as
        # 1/DTSCAL^2 (Reference Guide p.2973). 0.1 (=> x100 stiffness) anchors free
        # rigid bodies connected only by contact. For nonlinear analysis it only
        # affects convergence speed, not the result, so a strong (small) value is
        # safe. (The SEAT example's 1000 is too weak for free-body-via-contact:
        # the body sloshed in its rigid mode and the solve never converged.)
        #
        # The deformable-deformable contact recipe tightens this to 0.05 (=> x400):
        # a compliant contact under force control adds a soft mode that 0.1 leaves
        # a step-overshoot 2-cycle on, while 0.01 over-damps and freezes the solve;
        # 0.05 anchors it without over-stiffening the tangent. Physics-neutral for
        # nonlinear analysis (the stabilization vanishes at equilibrium). See
        # _warn_deformable_deformable_contact.
        dtscal = "0.05" if _recipe_active(state) else "0.1"
        lines += ["/IMPL/QSTAT/DTSCAL", f" {dtscal}"]

    # /IMPL/SOLVER format (Reference Guide p.2976-2978):
    #   /IMPL/SOLVER/N  with data card: Iprec  It_max  Itol  Tol
    # N=2 is MUMPS direct solver. (N=7 Auto solver is NO LONGER SUPPORTED
    # in OpenRadioss 2024+ per MESSAGE ID 296 — it now falls back to MUMPS.)
    #
    # MUMPS memory mode: /IMPL/MUMPS/AUTOCORE. MUMPS starts in-core (fast, no
    # disk I/O) and automatically switches to out-of-core ONLY if the factors do
    # not fit in available memory (Altair Radioss 2026 /IMPL/MUMPS/AUTOCORE).
    # This supersedes the two older modes we used to choose between by mesh size:
    #   - /IMPL/MUMPS/AUTOC is OBSOLETE (and in this build never reliably spilled
    #     to disk, so it crashed silently when the factors overflowed RAM);
    #   - /IMPL/MUMPS/OUTCORE forces always-on-disk streaming -- safe but slow.
    # AUTOCORE gives in-core speed with an automatic disk fallback, so one mode
    # covers both the ~190k-node hr-anlenkung and the ~834k-node / 2.4M-DOF
    # elevator-linkage. Validated on the elevator (np=1 -nt 12): runs in-core and
    # writes results, far faster than OUTCORE. Hand-edit this to
    # /IMPL/MUMPS/OUTCORE only to force disk streaming on a RAM-starved machine.
    lines += ["/IMPL/PRINT/NONL/-1",
              "/IMPL/SOLVER/2", "  0 0 0 0",
              "/IMPL/MUMPS/AUTOCORE",
              "/IMPL/DTINI", _f(dt0)]
    lines += ["/IMPL/DT/STOP", f"{_f(dtmin)}{_f(dtmax)}"]
    # /IMPL/DT/2 data: It_w  L_arc  L_dtn  Tsca_dn  Tsca_up
    # (Reference Guide p.2981)
    #   It_w   = converge-iter threshold for time-step increase (default 6).
    #            LS-DYNA *CONTROL_IMPLICIT_AUTO ITEOPT maps here when given.
    #   L_arc  = arc length (0 = auto)
    #   L_dtn  = MAX iterations before a timestep cut. 0 => engine default (20).
    #            We do NOT force a non-default value by default: a higher cap is
    #            only needed for the slow LINEAR force-residual convergence of a
    #            deformable-deformable penalty contact (~30 iters/step), so it
    #            ships behind the opt-in deformable-contact recipe (L_dtn=50),
    #            announced by _warn_deformable_deformable_contact. (LS-DYNA KFAIL
    #            is "failed steps before abort", NOT this per-step cap, so it is
    #            never written into this slot.)
    #   Tsca_dn = scale for decreasing (0 = 0.67)
    #   Tsca_up = scale for increasing (0 = 1.1)
    it_w = iteopt if iteopt > 0 else 8
    l_dtn = 50 if _recipe_active(state) else 0
    lines += ["/IMPL/DT/2", f"{_i(it_w)}{_i(0)}{_i(l_dtn)}{_i(0)}{_i(0)}"]

    # /IMPL/DT/FIXPOINT — force the implicit time-step controller to land EXACTLY
    # on evenly spaced times (k/N × the run end, for k = 1 … N) so a clean
    # animation / time-history state is produced at each milestone instead of
    # wherever the variable implicit step happens to fall. Without it the auto
    # time step (/IMPL/DT/2) can stride past a requested output time, and that
    # interval's animation is then written late, at the overshooting time. The
    # engine reads the points free-format over as many lines as supplied, sorts
    # them ascending and caps the list at 100 (OpenRadioss
    # engine/source/input/freimpl.F). It is honoured by /IMPL/DT/1 and /IMPL/DT/2
    # (our default); only /IMPL/DT/3 (RIKS) ignores it. N is
    # options.fixpoint_count (default 100 → a point every 1% of the run); we
    # clamp it to the engine's 1…100 range here, and 0 disables the card.
    n_fix = min(max(int(state.options.fixpoint_count), 0), 100)
    if n_fix > 0 and state.ctrl_termination and state.ctrl_termination.endtim > 0:
        endtim = state.ctrl_termination.endtim
        fixpts = [endtim * k / n_fix for k in range(1, n_fix + 1)]  # 1/N … N/N
        lines.append("/IMPL/DT/FIXPOINT")
        for i in range(0, len(fixpts), 5):                   # ≤5 fields → ≤100 cols
            lines.append("".join(_f(t) for t in fixpts[i:i + 5]))

    lines.append("#")
    return lines


def _make_engine_cpu(state: ConversionState) -> List[str]:
    if not state.ctrl_cpu:
        return []
    return ["/CPU", f"{_f(state.ctrl_cpu.cputim)}         2", "#"]


def build_starter(state: ConversionState, progress=None) -> str:
    _resolve_define_tables(state)
    _resolve_mat_plas_tab(state)
    _resolve_mat_power_law(state)

    # Normalize 10-node tet connectivity to Radioss /TETRA10 midside order (the
    # LS-DYNA *ELEMENT_SOLID apex nodes 8/9/10 differ). MUST run before every other
    # tet10 pass (downgrade/snap/emit) and before the gapmin faceting, all of which
    # read the midside slots through the Radioss map. Idempotent: if --auto-gapmin
    # already ran it in convert(), this is a guarded no-op. Fixes the ERROR 558 snap
    # collapse and the silent ~-30% /TETRA10 volume.
    _normalize_tet10_ordering(state)

    # Optional TET10 -> TET4 linear downgrade (opt-in). Runs first so the tet10
    # snap and sliver prepasses below operate on the resulting linear mesh.
    _downgrade_tet10_to_tet4(state)

    # Straighten 10-node tet edges (mid-edge nodes -> edge midpoints) so no
    # quadratic Jacobian folds (OpenRadioss ERROR 489). Must run before nodes are
    # emitted and before CNRB centroids are computed from node coordinates.
    n_snapped = _snap_tet10_midsides(state)
    if n_snapped:
        state.warn(
            f"{n_snapped} /TETRA10 mid-edge node(s) snapped onto their edge "
            "midpoints (straight-edged sub-parametric tets) to avoid folded "
            "quadratic Jacobians (OpenRadioss ERROR 489: badly shaped 10-node "
            "tetra). Curved boundary elements are flattened slightly; remesh with "
            "better element quality to retain exact curved edges."
        )

    # Drop sliver tets (tet10 always — ERROR 489; extreme tet4 for implicit)
    # BEFORE any section is built, so the free-node guard sees the post-drop
    # connectivity and constrains any node the drops left unattached.
    _screen_sliver_tets(state)

    # Assign a synthesized orthotropic /PROP id to each LAW128 (MAT_103) part
    # (LAW128 is orthotropic-only). Must run before parts (which repoint the
    # /PART at it) and properties (which emit it) are built.
    _assign_ortho_props(state)

    # Per-part hourglass control (*HOURGLASS + *PART HGID / *CONTROL_HOURGLASS):
    # allocate a dedicated /PROP id for each part whose effective hourglass
    # differs from its section base. Runs AFTER ortho (it skips ortho parts) and
    # before parts (repoint) and properties (emit).
    _assign_hourglass_props(state)

    # Moving rigid walls need their carrier node in the deck BEFORE the /NODE
    # section is built (the /RWALL cards themselves are emitted later).
    _synthesize_rwall_moving_nodes(state)

    # Assign a /SKEW id to every *DEFINE_VECTOR[_NODES] / *DEFINE_SD_ORIENTATION
    # and synthesize the third node each moving /SKEW/MOV needs — before the
    # /NODE section (so the nodes are emitted) and before /FRAME allocation (so
    # the ids are reserved in the shared /SKEW+/FRAME namespace).
    _synthesize_vector_skews(state)

    rbody_lines, rigid_nodes, rbody_info = _make_rbodies(state)
    # *CONSTRAINED_NODAL_RIGID_BODY produces additional /RBODY entries that must
    # be visible to every rigid-body-keyed section below, so merge their info,
    # rigid-node set, and rad lines with the *MAT_RIGID ones.
    cnrb_lines, cnrb_rigid_nodes, cnrb_info = _make_cnrb_rbodies(state)
    rigid_nodes = rigid_nodes | cnrb_rigid_nodes
    rbody_info = {**rbody_info, **cnrb_info}
    rbody_lines = rbody_lines + cnrb_lines
    # Implicit deck without any rigid body: the engine segfaults at solver init
    # (MESSAGE ID 44) — give it an inert fully-fixed probe rigid body.
    rbody_lines = rbody_lines + _make_probe_rbody(state, rbody_info)
    state.rbody_grnods = {pid: info["grnod_id"] for pid, info in rbody_info.items()}
    state.rbody_ind_grnods = {pid: info["ind_grnod_id"] for pid, info in rbody_info.items()}

    def _rep(frac: float, label: str) -> None:
        if progress is not None:
            progress(frac, label)

    # The starter is assembled from an ordered registry of (name, builder)
    # entries — see _starter_section_registry(). Iterating a data-driven list
    # (rather than a hand-maintained sequence of sections.append(...) calls)
    # makes the section order explicit and lets a new section be inserted by
    # adding one tuple, without editing the middle of this function. The context
    # carries the state plus the three values threaded across sections
    # (rbody_info, rigid_nodes, the pre-built rbody_lines) and the progress
    # reporter. Output is byte-identical to the previous fixed sequence.
    ctx = _StarterContext(state, rbody_info, rigid_nodes, rbody_lines, _rep)
    lines: List[str] = []
    for _name, builder in _starter_section_registry():
        lines.extend(builder(ctx))
    _rep(1.0, "Starter deck ready")
    return "\n".join(lines) + "\n"


class _StarterContext:
    """Values threaded across the starter section builders (see
    _starter_section_registry). ``rep(frac, label)`` forwards to the progress
    callback."""
    __slots__ = ("state", "rbody_info", "rigid_nodes", "rbody_lines", "rep")

    def __init__(self, state, rbody_info, rigid_nodes, rbody_lines, rep):
        self.state = state
        self.rbody_info = rbody_info
        self.rigid_nodes = rigid_nodes
        self.rbody_lines = rbody_lines
        self.rep = rep


def _progress_marker(ctx: "_StarterContext", frac: float, label: str) -> List[str]:
    """A registry entry that only reports progress (emits no starter lines), so
    the two heavy builders (nodes, elements) keep their coarse progress markers
    at the same points as the original fixed sequence."""
    ctx.rep(frac, label)
    return []


def _starter_section_registry():
    """Ordered (name, builder) registry the starter is assembled from. Each
    builder takes a _StarterContext and returns its list of .rad lines. Insert a
    new section by adding a tuple at the right position — no need to edit
    build_starter. Order and output match the historical fixed sequence."""
    return [
        ("header",            lambda c: _make_header(c.state)),
        ("title",             lambda c: _make_title(c.state)),
        ("analysis_defaults", lambda c: _make_analysis_defaults(c.state)),
        ("ams",               lambda c: _make_ams(c.state)),
        ("materials",         lambda c: _make_materials(c.state)),
        ("_progress_nodes",   lambda c: _progress_marker(c, 0.08, "Writing nodes")),
        ("nodes",             lambda c: _make_nodes(
            c.state, progress=lambda fr: c.rep(0.08 + 0.32 * fr, "Writing nodes"))),
        ("bcs",               lambda c: _make_bcs(c.state, c.rbody_info)),
        ("skews",             lambda c: _make_skews(c.state)),
        ("_progress_elems",   lambda c: _progress_marker(c, 0.40, "Writing elements")),
        ("parts_elements",    lambda c: _make_parts_and_elements(
            c.state, progress=lambda fr: c.rep(0.40 + 0.50 * fr, "Writing elements"))),
        ("_progress_final",   lambda c: _progress_marker(c, 0.90, "Finalizing starter deck")),
        ("properties",        lambda c: _make_properties(c.state)),
        ("functions",         lambda c: _make_functions(c.state)),
        ("extra_groups",      lambda c: _make_extra_groups(c.state)),
        ("rlinks",            lambda c: _make_rlinks(c.state)),
        ("interfaces",        lambda c: _make_interfaces(c.state, c.rigid_nodes)),
        ("tied_interfaces",   lambda c: _make_tied_interfaces(c.state, c.rigid_nodes)),
        ("force_transducers", lambda c: _make_force_transducers(c.state, c.rigid_nodes)),
        ("rbodies",           lambda c: c.rbody_lines),
        ("imposed_motions",   lambda c: _make_imposed_motions(c.state, c.rbody_info)),
        ("imposed_motions_set", lambda c: _make_imposed_motions_set(c.state)),
        ("inivel",            lambda c: _make_inivel(c.state, c.rbody_info)),
        ("initial_velocity",  lambda c: _make_initial_velocity(c.state)),
        ("initial_velocity_generation",
                              lambda c: _make_initial_velocity_generation(c.state)),
        ("pressure_loads",    lambda c: _make_pressure_loads(c.state)),
        ("gravity_loads",     lambda c: _make_gravity_loads(c.state)),
        ("body_loads",        lambda c: _make_body_loads(c.state)),
        ("blast_loads",       lambda c: _make_blast_loads(c.state)),
        ("detonations",       lambda c: _make_detonations(c.state)),
        ("fsi_coupling",      lambda c: _make_fsi_coupling(c.state)),
        ("ebcs",              lambda c: _make_ebcs(c.state)),
        ("inivol_notes",      lambda c: _make_inivol_notes(c.state)),
        ("control_ale_notes", lambda c: _make_control_ale_notes(c.state)),
        ("starter_cloads",    lambda c: _make_starter_cloads(c.state)),
        ("node_cloads",       lambda c: _make_node_cloads(c.state)),
        ("rigid_walls",       lambda c: _make_rigid_walls(c.state)),
        ("modal_dummy_cload", lambda c: _make_modal_dummy_cload(c.state, c.rigid_nodes)),
        ("discrete_springs",  lambda c: _make_discrete_springs(c.state)),
        ("spotweld_beams",    lambda c: _make_spotweld_beam_connectors(c.state)),
        ("spotweld_ties",     lambda c: _make_constrained_spotweld_springs(c.state)),
        ("grounding_springs", lambda c: _make_grounding_springs(c.state, c.rbody_info)),
        ("added_masses",      lambda c: _make_added_masses(c.state, c.rigid_nodes)),
        ("initial_stresses",  lambda c: _make_initial_stresses(c.state)),
        ("cross_sections",    lambda c: _make_cross_sections(c.state)),
        ("eig",               lambda c: _make_eig(c.state)),
        ("free_node_constraints", lambda c: _make_free_node_constraints(c.state, c.rigid_nodes)),
        ("damping",           lambda c: _make_damping(c.state, c.rigid_nodes)),
        ("starter_th",        lambda c: _make_starter_th(c.state)),
        ("starter_th_inter",  lambda c: _make_starter_th_inter(c.state)),
        ("starter_th_node_reac", lambda c: _make_starter_th_node_reac(c.state, c.rbody_info)),
        ("starter_th_node_spc",  lambda c: _make_starter_th_node_spc(c.state, c.rbody_info)),
        ("starter_th_surf",   lambda c: _make_starter_th_surf(c.state)),
        ("starter_th_sectio", lambda c: _make_starter_th_sectio(c.state)),
        ("freq_domain_notes", lambda c: _make_freq_domain_notes(c.state)),
        ("skipped_comment",   lambda c: _make_skipped_comment(c.state)),
        ("end",               lambda c: ["/END", HDR]),
    ]


def _make_engine_restart(state: ConversionState) -> List[str]:
    """/RFILE/OFF disables the engine restart (.rst) files, which are only
    needed for /RERUN or crash recovery and are large on a big model. Emitted
    by default (write_restart off); set write_restart to keep OpenRadioss's
    default restart writing. (The starter's <root>_0000_*.rst is the mandatory
    model handoff to the engine and cannot be suppressed here.)"""
    opts = getattr(state, "options", None)
    if opts is not None and getattr(opts, "write_restart", False):
        return []
    return ["/RFILE/OFF", "#"]


def _make_engine_timestep(state: ConversionState) -> List[str]:
    """*CONTROL_TIMESTEP DT2MS<0 → /DT/NODA/CST (nodal-mass scaling that holds
    the explicit time step at the target |DT2MS|). Without this OpenRadioss runs
    at the raw smallest-element step — on a fine/TET mesh that can be ~100x below
    the intended DT2MS, so the run is ~100x slower. Explicit runs only (implicit
    and modal have no CFL time step to scale)."""
    ts = state.ctrl_timestep
    if ts is None or ts.dt2ms >= 0.0 or state.is_implicit or state.is_modal:
        return []
    tmin = abs(ts.dt2ms)
    if state.options.ams:
        # Advanced Mass Scaling (opt-in). 0.67 is the OpenRadioss-recommended AMS
        # scale factor — the PCG needs more margin than /DT/NODA/CST's 0.9. The
        # paired starter /AMS card is emitted by _make_ams.
        tsca = 0.67
        state.warn(
            f"*CONTROL_TIMESTEP DT2MS={ts.dt2ms:g} → /DT/AMS (Advanced Mass "
            f"Scaling, Tmin={tmin:g}, Tsca={tsca:g}) [--ams]. AMS holds the time "
            "step with a coupled mass matrix that preserves low-frequency dynamics "
            "instead of adding real nodal mass. It solves a PCG each cycle and can "
            "DIVERGE ('AMS IS LIKELY DIVERGING') on stiff / high-stiffness-contrast "
            "/ contact-heavy models or at a large Tmin/element-dt ratio; if it "
            "does, drop --ams (default /DT/NODA/CST) or lower |DT2MS|."
        )
        return [
            "/DT/AMS",
            f"{_f(tsca)}{_f(tmin)}",
            "#",
        ]
    tsca = ts.tssfac if ts.tssfac and ts.tssfac > 0.0 else 0.9
    state.warn(
        f"*CONTROL_TIMESTEP DT2MS={ts.dt2ms:g} → /DT/NODA/CST/0 (nodal mass "
        f"scaling, Tmin={tmin:g}, Tsca={tsca:g}); OpenRadioss adds mass to hold "
        "the time step at Tmin. Check the starter ADDED MASS is acceptable."
    )
    return [
        "/DT/NODA/CST/0",
        f"{_f(tsca)}{_f(tmin)}",
        "#",
    ]


def build_engine(state: ConversionState) -> str:
    sections = [
        _make_engine_header(state),
        _make_engine_restart(state),
        _make_engine_output(state),
        _make_engine_timestep(state),
        _make_engine_implicit(state),
        _make_engine_cpu(state),
        ["/MON/ON", "#"],
    ]
    lines: List[str] = []
    for sec in sections:
        lines.extend(sec)
    return "\n".join(lines) + "\n"
