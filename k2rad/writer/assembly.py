"""Top-level assemblers: build_starter / build_engine and the engine-card emitters."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple
from ..state import ConversionState
from .beams import _resolve_integration_beams
from .common import HDR, _ams_is_emitted, _f, _i
from .materials import (
    _make_functions,
    _make_materials,
    _resolve_define_tables,
    _resolve_define_tables_3d,
    _resolve_mat_gurson,
    _resolve_mat_hyper_rubber,
    _resolve_mat_iso_elas_plas,
    _resolve_mat_johnson_cook,
    _resolve_mat_plas_comp_tens,
    _resolve_mat_tabulated_jc,
    _resolve_mat_impact,
    _resolve_mat_viscoelastic,
    _resolve_mat_adhesives,
    _resolve_mat_foams,
    _resolve_mat_plas_tab,
    _resolve_mat_power_law,
    _resolve_mat_shape_memory,
    _resolve_mat_law106,
    _resolve_mat_law3,
    _warn_refused_materials,
)
from .muscle import _make_muscle_springs
from .thermal import (_make_thermal, _resolve_thermal,
                      _thermal_solve_active)
from .mesh import (
    _assign_ortho_props,
    _assign_hourglass_props,
    _downgrade_tet10_to_tet4,
    _flatten_set_adds,
    _resolve_contact_interior,
    _make_extra_groups,
    _make_nodes,
    _make_parts_and_elements,
    _make_properties,
    _make_skews,
    _normalize_tet10_ordering,
    _screen_provisional_elements,
    _screen_sliver_tets,
    _snap_tet10_midsides,
    _synthesize_beam_orientation_nodes,
    _synthesize_vector_skews,
)
from .composites import (
    _assign_composite_props,
    _emit_composite_props,
    _fold_element_beta,
    _make_composite_materials,
    _resolve_composites,
    _resolve_icomp_sections,
    _resolve_integration_shells,
)
from .seatbelts import (
    _assign_seatbelt_props,
    _emit_seatbelt_2d_props,
    _make_seatbelt_2d_materials,
    _make_seatbelts,
)
from .fabric import (
    _assign_fabric_props,
    _emit_fabric_props,
    _make_fabric_materials,
    _resolve_mat_fabric,
)
from .monvol import _make_monvols, _resolve_airbags
from .sph import _make_sphglo, _resolve_sph
from .tshell import _resolve_tshells
from .contacts import (
    _make_force_transducers,
    _make_general_interfaces,
    _make_interfaces,
    _make_tied_interfaces,
    _make_tiebreak_interfaces,
    _make_spotweld_interfaces,
    _make_type25_interfaces,
    _recipe_active,
)
from .frictions import _make_frictions
from .rbody import _make_cnrb_rbodies, _make_probe_rbody, _make_rbodies
from .rbe3 import _make_rbe3
from .joints import _make_joints, _resolve_joints
from .dbeam import _make_discrete_beam_connectors
from .loads import (
    _make_added_masses,
    _make_bcs,
    _make_body_loads,
    _make_constrained_spotweld_springs,
    _make_hex_spotweld_clusters,
    _make_damping,
    _make_damping_part_mass,
    _make_damping_frequency_range,
    _resolve_damping_relative,
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
    _make_plotel_elements,
    _make_pressure_loads,
    _make_rigid_walls,
    _make_rlinks,
    _make_spotweld_beam_connectors,
    _make_starter_cloads,
    _synthesize_local_motion_frames,
    _synthesize_rwall_moving_nodes,
    _resolve_geometric_rigid_walls,
    _warn_spring_eid_collisions,
)
from .blast_ale import (
    _make_blast_loads,
    _make_control_ale_notes,
    _make_detonations,
    _make_ebcs,
    _make_fsi_coupling,
    _make_inivol_notes,
)
from .inistate import (_make_cross_sections, _make_eref,
                       _make_initial_stresses,
                       _make_starter_th_sectio, _make_xref,
                       _resolve_xref_parts)
from .preload import _make_preload
from .rarecards import (_make_element_death, _make_engine_dynain,
                        _make_impdisp_fgeo, _make_random)
from .output import (
    _make_ams,
    _make_analysis_defaults,
    _make_eig,
    _make_engine_parith,
    _make_freq_domain_notes,
    _make_header,
    _make_skipped_comment,
    _make_starter_th,
    _make_starter_th_bndout,
    _make_starter_th_accel,
    _make_starter_th_monv,
    _make_starter_th_seatbelt,
    _make_starter_th_inter,
    _make_starter_th_nodal_force_group,
    _make_starter_th_node_reac,
    _make_starter_th_node_spc,
    _make_starter_th_rbody,
    _make_starter_th_swforc,
    _make_starter_th_discrete_connectors,
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
    "_make_engine_dt_deletion",
    "_make_engine_timestep_scale",
    "_make_engine_thermal",
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


#: *CONTROL_TERMINATION ENDTIM at or above this is treated as a SENTINEL ("run
#: until something else stops it") rather than a run length, and no output
#: frequency is derived from it. LS-DYNA decks that terminate on ENDCYC/ENDENG
#: conventionally write 1e10 or 1e20 here. Every deck in the 201-deck
#: regression corpus states an ENDTIM between 8.5e-5 and 30, so this sits four
#: orders of magnitude above any real run length in any unit system used there.
_ENDTIM_SENTINEL = 1e6


def _make_engine_output(state: ConversionState) -> List[str]:
    lines: List[str] = []
    # Radioss has ONE time-history frequency for the whole T01, so the whole
    # *DATABASE_* family has to collapse to a single /TFILE. Take the MINIMUM
    # of everything the deck asked for, never the first one that happens to be
    # set: an `or`-chain hands the frequency to whichever card sits earliest in
    # the chain, so a deck with *DATABASE_NODOUT DT=0.01 and *DATABASE_SWFORC
    # DT=1e-5 would sample every weld channel 1000x coarser than requested. The
    # minimum is the only rule that honours every channel; it can only ever
    # write MORE data than asked for, never less.
    # db_deforc_dt / db_disbout_dt / db_jntforc_dt belong in the chain for the
    # same reason as the rest: all three now drive a real /TH/SPRING (DEFORC
    # over the *ELEMENT_DISCRETE springs, DISBOUT over the ELFORM=6 discrete
    # beams, JNTFORC over the joint springs), so leaving them out sampled a
    # group the deck DID ask for at whatever coarser frequency the other cards
    # happened to set. The remaining *DATABASE_ dts k2rad parses
    # (BINARY_D3THDT, BINARY_INTFOR, SLEOUT) stay out: they have no /TH
    # consumer at all, so honouring them would only thicken the T01 for
    # channels that are not in it.
    #
    # *DATABASE_ABSTAT used to be on that out-list for exactly that reason and
    # is now IN, on the same "does this card pace a channel that is in the T01"
    # membership test — because the airbag batch gave it a consumer:
    # writer/output.py::_make_starter_th_monv builds a /TH/MONV over every
    # converted /MONVOL. It is gated on state.monvol_ids for the #122 reason
    # the three output-parity cards are gated on theirs: the test is not "is
    # the card in the deck". An ABSTAT on a deck whose only *AIRBAG_* was
    # dropped (or that has none at all) emits no group, and counting its dt
    # would thicken the T01 for channels that are not in it.
    _db_dts = (state.db_nodout_dt, state.db_elout_dt,
               state.db_glstat_dt, state.db_matsum_dt,
               state.db_spcforc_dt, state.db_ncforc_dt,
               state.db_rcforc_dt, state.db_blstfor_dt,
               state.db_rwforc_dt, state.db_secforc_dt,
               state.db_swforc_dt, state.db_deforc_dt,
               state.db_disbout_dt,
               # *DATABASE_SPHOUT joins for the same reason: the SPH particle
               # channels it asks for DO reach the T01, through the /TH/SPHCEL
               # groups *DATABASE_HISTORY_SPH builds.
               state.db_sphout_dt,
               state.db_jntforc_dt,
               # The output-parity batch, on the same membership test — but
               # each gated on its OWN consumer, because the test is "does this
               # card pace a channel that is IN the T01", not "is this card in
               # the deck". A *DATABASE_BNDOUT on a deck that prescribes no
               # motion emits no group, so counting its dt would only thicken
               # the T01 for channels that are not in it — which is the exact
               # argument that keeps *DATABASE_TPRINT out (see
               # handlers.handle_database_tprint), and it has to apply to these
               # three as well or the rule is not a rule. It bites: 52 of the
               # 118 *DATABASE_BNDOUT decks in the corpus carry no
               # *BOUNDARY_PRESCRIBED_MOTION at all.
               #
               # build_starter runs before build_engine (k2rad/__init__.py:486),
               # so all three registries are filled by the time this is read.
               #   BNDOUT  -> /TH/NODE 'TH_NODE_BNDOUT' on the driven nodes
               #   RBDOUT  -> /TH/RBODY over every converted rigid body
               #   NODFOR  -> the interval of the *DATABASE_NODAL_FORCE_GROUP
               #              /TH/NODE groups (that card has no DT of its own)
               # *DATABASE_HISTORY_* has no DT field at all, in any spelling.
               state.db_bndout_dt if state.imp_motion_nodes else 0.0,
               state.db_rbdout_dt if state.rbody_ids else 0.0,
               state.db_nodfor_dt if state.db_nodal_force_groups else 0.0,
               #   ABSTAT  -> /TH/MONV over every converted monitored volume
               state.db_abstat_dt if state.monvol_ids else 0.0,
               #   SBTOUT  -> /TH/SLIPRING + /TH/RETRACTOR over the emitted
               #              seatbelt devices, gated on its OWN consumers for
               #              the #122 reason: an *DATABASE_SBTOUT on a deck
               #              whose sliprings and retractors were all dropped
               #              (or that has none) emits no group at all, so
               #              counting its dt would only thicken the T01 for
               #              channels that are not in it.
               state.db_sbtout_dt
               if (state.slipring_ids or state.retractor_ids) else 0.0)
    requested = [v for v in _db_dts if v > 0.0]
    # "If DT < 0.0, the result will be output every -DT time steps" (Manual
    # p. 16-7) — a CYCLE-based request, which is a real request even though
    # Radioss's /TFILE is a time interval only and cannot express it. Counted
    # here so the derived-frequency warning below does not claim the deck said
    # nothing when it did.
    cycle_based = [v for v in _db_dts if v < 0.0]
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 0.0
    derived_from_endtim = not requested and 0.0 < endtim < _ENDTIM_SENTINEL
    if requested:
        dt_th = min(requested)
    elif derived_from_endtim:
        # No *DATABASE_ card states a dt, so the frequency has to be invented.
        # A hard-coded 1e-3 was the old answer and it is wrong at both ends of
        # the scale: on a 0.01 s impact it writes TEN T01 records for the whole
        # event, on a 100 s quasi-static run it writes a hundred thousand. Tie
        # it to the run length instead — 1000 points over the termination time,
        # the same shape as the /ANIM/DT default just below (endtim/40 = 40
        # frames), so the T01 resolves the run rather than the number 0.001.
        dt_th = endtim / 1000.0
    else:
        # Either no *CONTROL_TERMINATION at all (an include-only fragment), or
        # an ENDTIM that is not a run length: <= 0, or the sentinel a deck
        # carries when it really terminates on ENDCYC / ENDENG. Nothing states a
        # usable time scale, so fall back to the historical constant.
        #
        # The sentinel case is why this is a WINDOW and not just `endtim > 0`:
        # `*CONTROL_TERMINATION ENDTIM = 1e20` would otherwise derive /TFILE
        # 1E+17, a T01 that never fires at all — a silent total loss of
        # time-history output, strictly worse than the old constant. /TFILE must
        # also be strictly positive or lectur.F:335 (`IF(DTH /= ZERO)
        # OUTPUT%TH%DTHIS=DTH`) silently ignores the card and the T01 is written
        # at a frequency the deck never asked for, with no diagnostic at all.
        dt_th = 1e-3
    if not requested and state.th_groups_emitted:
        # Warned only when a /TH group was actually written (build_starter runs
        # first and records what it emitted): on a deck with no time-history
        # block the invented frequency governs nothing anyone reads.
        if derived_from_endtim:
            why = (f" (*CONTROL_TERMINATION ENDTIM {endtim:g} / 1000 = 1000 "
                   "samples over the run)")
        elif endtim >= _ENDTIM_SENTINEL:
            why = (f" (the fallback constant — *CONTROL_TERMINATION ENDTIM "
                   f"{endtim:g} is a SENTINEL, not a run length: a deck that "
                   "big really terminates on ENDCYC/ENDENG, which k2rad does "
                   "not convert, so scaling from it would have written a T01 "
                   "that never fires)")
        else:
            why = (" (the fallback constant — the deck states no usable ENDTIM "
                   "to scale it from)")
        state.warn(
            f"TIME HISTORY: this deck writes {state.th_groups_emitted} /TH "
            "group(s) but no *DATABASE_ card states a positive output "
            f"interval, so the T01 frequency was DERIVED as /TFILE {dt_th:.6G}"
            + why
            + ". Radioss has ONE time-history frequency for the whole T01, and "
            "nothing in the deck picks it. Add a *DATABASE_ card (e.g. "
            "*DATABASE_NODOUT) with the dt you actually want if this "
            "resolution is wrong."
            + (f" NOTE: {len(cycle_based)} *DATABASE_ card(s) DO state an "
               "interval, but as a negative DT — 'output every -DT time steps' "
               "(Manual p. 16-7). Radioss's /TFILE is a TIME interval and has "
               "no cycle-based form, so those requests cannot be honoured and "
               "took no part in the derivation above." if cycle_based else ""))
    lines += ["/TFILE", f"{dt_th:.6G}", "#", "/PRINT/-1", "#"]

    dt_anim = 0.0
    if state.db_d3plot:
        dt_anim = state.db_d3plot.dt
        if dt_anim == 0.0 and state.db_d3plot.npltc > 0:
            # A deck with no *CONTROL_TERMINATION at all keeps the historical
            # 1.0 s stand-in (the same one /RUN is written with); a deck that
            # states ENDTIM 0 keeps ITS zero and falls through to the omit
            # branch below, rather than having a run length invented for it.
            dt_anim = ((endtim if state.ctrl_termination else 1.0)
                       / state.db_d3plot.npltc)
    if dt_anim == 0.0:
        # No *CONTROL_TERMINATION → the literal 0.01, not 1.0/40: that is the
        # historical value and every deck in the corpus without a termination
        # card rides it. (It is inconsistent with the 1.0 s /RUN stand-in used
        # one line up — noted, deliberately not changed here, because moving it
        # would rewrite the engine file of every include-only fragment.)
        dt_anim = endtim / 40.0 if state.ctrl_termination else 0.01
    if dt_anim > 0.0:
        lines += ["/ANIM/DT", f"0. {dt_anim:.6G}"]
    else:
        # ENDTIM <= 0 (a cycle-terminated deck, or a deck that simply states 0)
        # drove dt_anim to 0.0, and `/ANIM/DT  0. 0` is not a harmless no-op:
        # freanim.F:131-134 raises MESSAGE 293 ("TIME FREQUENCY ... MUST BE
        # GREATER THAN ZERO") and calls ARRET(0), so the engine stops before
        # cycle 1. Omitting the card entirely is the safe branch — DTANIM0
        # stays 0 from anim_set2zero_struct.F, lectur.F:2648-2651 pushes TANIM
        # to 1e30, and no A-file and no error are produced.
        npltc = state.db_d3plot.npltc if state.db_d3plot else 0
        state.warn(
            "*CONTROL_TERMINATION ENDTIM is "
            f"{endtim:g} and "
            + (f"*DATABASE_BINARY_D3PLOT states no positive DT — its NPLTC "
               f"{npltc} would give ENDTIM/NPLTC, but there is no positive "
               "ENDTIM to divide" if npltc > 0 else
               "no *DATABASE_BINARY_D3PLOT states a positive DT or NPLTC")
            + ", so there is no time to derive an animation frequency "
            "from. The /ANIM/DT card was OMITTED and NO ANIMATION (A-files) "
            "will be written. It is left out on purpose: `/ANIM/DT 0. 0` is "
            "engine MESSAGE 293 followed by ARRET(0) (freanim.F:131-134), "
            "which stops the run before the first cycle. Give the deck a "
            "positive ENDTIM, or a *DATABASE_BINARY_D3PLOT DT, to get "
            "animation output.")

    ext = state.db_extent_binary

    # ── Vector outputs ────────────────────────────────────────────
    lines.append("/ANIM/VECT/DISP")
    lines.append("/ANIM/VECT/VEL")
    lines.append("/ANIM/VECT/ACC")
    lines.append("/ANIM/VECT/CONT")
    lines.append("/ANIM/VECT/CONT2")
    lines.append("/ANIM/VECT/PCONT")
    if state.db_spcforc_dt and (state.bcs_spcs or state.cnrb_spc_bcs):
        # *DATABASE_SPCFORC: constraint-reaction nodal vectors. This is the
        # instantaneous reaction FORCE (reactions.F:328 finalizes
        # FREAC = MS*A - FREAC each cycle, no dt factor); the /TH/NODE REAC*
        # channels carry the per-node time history but as an accumulated
        # IMPULSE (see writer/output.py:_make_starter_th_node_spc).
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
                                for m in state.mat_plas_tab.values()) \
            or any(m.d1 or m.d2 or m.d3 or m.d4 or m.d5
                   or (m.ortho and m.psfail > 0.0)
                   for m in state.mat_johnson_cook.values()):
        lines.append("/ANIM/ELEM/DAMG")

    # ── Nodal scalar outputs ──────────────────────────────────────
    lines.append("/ANIM/NODA/DT")
    lines.append("/ANIM/NODA/DMAS")
    # Nodal temperature, ONLY when the deck really runs a thermal solve (a
    # /HEAT/MAT AND an emitted temperature-moving card — an /IMPTEMP, or one of
    # the heat sources /CONVEC, /RADIATION, /IMPFLUX). The #122 rule: /ANIM and
    # /TH temperature channels on a deck with no thermal solve are accepted,
    # run clean and write state after state of exactly 0.0.
    if _thermal_solve_active(state):
        lines.append("/ANIM/NODA/TEMP")
    if state.db_blstfor_dt and state.blast_segment_loads:
        # *DATABASE_BINARY_BLSTFOR: nodal blast-pressure fringe (element
        # /LOAD/PBLAST pressures averaged onto the loaded-surface nodes).
        lines.append("/ANIM/NODA/PEXT")
    if state.tiebreak_rupture_inter_ids:
        # Per-node tiebreak DAMAGE, the only observable of a /INTER/TYPE2
        # rupture besides the .out START/TOTAL RUPTURE lines. The card is what
        # ARMS it: ruptint2.F:143/155/169 fill PDAMA2 only under
        # `ANIM_N(15)==1 .OR. H3D_DATA%N_SCAL_DAMA2 == 1`, and
        # anim_dcod_key_0.F:2997-2999 is where DAMA2 sets both ANIM_N(15) and
        # ANIM_N(16) (normal and tangential, genani.F:1914-1915). Gated on a
        # rupturing tie existing, per the #122 rule: with no Rupt=2 interface
        # in the deck the channel is legal, accepted, and exactly 0.0 forever.
        lines.append("/ANIM/NODA/DAMA2")

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
    if dyn is not None and dyn.imass > 0:
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


# Orphan-element guard
#
# Every structural element is emitted from INSIDE the
# ``for pid, part in sorted(state.parts.items())`` loop of
# ``writer/mesh.py::_make_parts_and_elements`` (and, for the spring/damper
# connectors, from the per-part loops in ``writer/loads.py``). An element whose
# PID has no ``PartData`` is therefore never REACHED: it is not skipped with a
# message, not counted as unsupported — the loop simply never visits that id and
# the element does not appear in the .rad at all. Nothing downstream notices
# either, because the starter only ever sees the elements that were written.
#
# That is the exact failure mode `*PART_COMPOSITE` had before it got a handler:
# an entire part's mesh disappeared and the converted deck ran happily without
# it, just lighter and softer than the model the user drew. The same silence
# covers every other way a PID can go missing — a `*PART` block inside an
# `*INCLUDE` that did not resolve, an id typo, a deck assembled from a subset of
# its parts, a `*PART` variant k2rad does not parse yet.
#
# So: one loud, aggregated warning naming the missing PIDs and how many elements
# of each type were lost with them. `*ELEMENT_DISCRETE` is scanned as well even
# though `_make_discrete_springs` warns per part on its own — this stays the one
# place that answers "did the conversion drop any of my mesh?", and it keeps
# answering it if that emitter is ever short-circuited or reordered.
_ORPHAN_ELEM_KINDS = ("shell", "solid", "tshell", "sph", "beam", "discrete",
                      "seatbelt")

# Cap on the PIDs spelled out in the message: a deck missing a whole *INCLUDE
# can orphan hundreds of parts, and one unreadable 10-kB warning line helps
# nobody. The total count is always exact.
_ORPHAN_PIDS_SHOWN = 12


def _warn_orphan_elements(state: ConversionState) -> None:
    """Warn about parsed elements whose PID has no ``*PART`` (see above)."""
    orphans: Dict[int, Dict[str, int]] = {}
    for kind, elems in (("shell", state.shell_elems),
                        ("solid", state.solid_elems),
                        ("tshell", state.tshell_elems),
                        # SPH particles are emitted per /PART exactly as every
                        # other family is, so an orphaned one is lost mass with
                        # nothing else to say so — this census is the only
                        # place that answers "did the conversion drop any of my
                        # mesh?" and it has to see the SPH cloud too.
                        ("sph", state.sph_elems),
                        ("beam", state.beam_elems),
                        ("discrete", state.discrete_elems),
                        # A belt element whose PID has no *PART is lost the
                        # same way any other element is - and losing it loses
                        # a RESTRAINT, on a run that terminates normally.
                        ("seatbelt", state.seatbelt_elems)):
        for e in elems:
            if e.pid in state.parts:
                continue
            per_kind = orphans.setdefault(e.pid, {})
            per_kind[kind] = per_kind.get(kind, 0) + 1
    if not orphans:
        return

    n_elems = sum(sum(per_kind.values()) for per_kind in orphans.values())
    shown = sorted(orphans)[:_ORPHAN_PIDS_SHOWN]
    detail = "; ".join(
        "PID {} ({})".format(
            pid,
            ", ".join(f"{orphans[pid][k]} {k}"
                      for k in _ORPHAN_ELEM_KINDS if k in orphans[pid]))
        for pid in shown)
    if len(orphans) > len(shown):
        detail += f"; and {len(orphans) - len(shown)} more part id(s)"

    state.warn(
        f"MESH LOSS: {n_elems} element(s) reference {len(orphans)} part id(s) "
        f"that no *PART card defines, and are NOT in the converted deck — "
        f"{detail}. k2rad emits elements per /PART, so an element whose PID has "
        "no *PART has nowhere to go and is dropped silently: the .rad runs, but "
        "that mesh is missing from it (less stiffness, less mass, no contact "
        "surface). Check for an *INCLUDE that did not resolve or a *PART id "
        "typo, add the missing *PART (with its *SECTION_* and *MAT_*), or "
        "delete the elements.")


def build_starter(state: ConversionState, progress=None) -> str:
    # Snapshot the deck's OWN node ids first, before any prepass synthesizes one
    # (/RBODY CoG masters, /SKEW/MOV third nodes, the _LOCAL triads, rigid-wall
    # carriers, beam-orientation nodes). Everything resolving a *DEFINE_BOX by
    # scanning state.nodes has to intersect with this, or a box drawn round the
    # user's model also catches k2rad's own artefacts — measured: a box-only
    # *BOUNDARY_PRESCRIBED_MOTION_SET_BOX drove a rigid body's synthesized master
    # node, a kinematic condition the source deck never states.
    #
    # Only taken when the deck HAS a *DEFINE_BOX, which is the precondition for
    # _box_node_ids being reachable at all: a set of ints per node is a real cost
    # on the 100-200 MB mesh decks in the corpora and nothing would read it.
    if state.boxes:
        state.source_node_ids = set(state.nodes)
    # *SET_<FAMILY>_ADD → plain sets of that family (recursively), BEFORE
    # anything reads state.part_sets / node_sets / the element and segment set
    # containers (contact sides, *CONTACT_INTERIOR, gravity/ALE scopes, /BCS,
    # /RBODY, /RWALL scopes, /SECT groups, /TH channels, /PLOAD surfaces) and
    # before the tet10->tet4 node-set prune, which mutates state.node_sets.
    # Idempotent — convert() already ran it so --auto-gapmin sees the
    # flattened sets; this covers direct build_starter callers.
    _flatten_set_adds(state)
    _resolve_define_tables(state)
    _resolve_mat_plas_tab(state)
    _resolve_mat_power_law(state)
    # Johnson-Cook LAW2/LAW4 routing (needs the *PART EOSID bindings) + the
    # DTF → /FAIL/GENE1 dtmin injection — before _make_materials emits.
    _resolve_mat_johnson_cook(state)
    # Hyperelastic rubber routing (MAT_027 LAW42-vs-LAW69 needs the parsed
    # *DEFINE_CURVEs; the MAT_077 LAW69 paths synthesize rescaled duplicate
    # curves; the MAT_027 LAW42 branch synthesizes its 500-point funIDbulk
    # curve) + the
    # dropped-field and REF-coverage warnings — before _make_materials emits
    # and before _resolve_xref_parts (which needs the LAW42/LAW69 routing).
    _resolve_mat_hyper_rubber(state)
    # Metal plasticity batch 2. MAT_012's E/nu come from G/BULK; MAT_120's
    # hardening input may synthesize a /FUNCT (so before _make_functions) and
    # registers table ids; MAT_124 only reports dropped fields. All three run
    # before _make_materials and before _resolve_xref_parts, which reads
    # _target_mat_law and therefore needs the containers already routed.
    _resolve_mat_iso_elas_plas(state)
    _resolve_mat_gurson(state)
    _resolve_mat_plas_comp_tens(state)
    # Viscoelastic batch. MAT_006's temperature curves and MAT_181/183's
    # loading/unloading families both need the parsed *DEFINE_CURVEs (and
    # MAT_181's LC/TBID may be a *DEFINE_TABLE, so after _resolve_define_tables
    # above); the LAW88 specimen normalization synthesizes rescaled duplicate
    # curves, so before _make_functions. Also before _resolve_xref_parts: LAW42
    # (MAT_076, MAT_091/092) and LAW88 (MAT_181/183) are BOTH on the starter's
    # solid-/XREF law whitelist, so these containers decide which parts get a
    # /XREF and pick up Ismstr=10.
    _resolve_mat_viscoelastic(state)
    # Adhesives / cohesive batch. Needs the parsed *DEFINE_CURVE/_TABLEs (so
    # after _resolve_define_tables above) because /MAT/LAW120's Table_Id and
    # /FAIL/INIEVO's TAB_ID/TAB_EL are TABLE slots: a *DEFINE_CURVE referenced
    # there is re-routed to a 1-D /TABLE/1 via state.table_1d_ids, which
    # _make_functions reads — so before _make_functions. Nothing here touches
    # _resolve_xref_parts' inputs: none of LAW116/117/120/169 is on the
    # solid-/XREF law whitelist (the _target_mat_law entries alone make the
    # gate warn-skip those parts correctly instead of claiming "no /MAT").
    _resolve_mat_adhesives(state)

    # An *ELEMENT_SHELL/_BEAM block with an option k2rad does not model keeps
    # its connectivity by CONTENT, which cannot distinguish an all-integer
    # option card from a real element. Screen those candidates against the node
    # table FIRST, before any pass reads the element lists, so a phantom never
    # reaches a contact group, a /PART or the free-node guard.
    _screen_provisional_elements(state)

    # Report elements orphaned by a missing *PART. AFTER the provisional screen
    # (a screened-out phantom is an option card, not lost mesh — counting it
    # here would be a false alarm) but before the tet10 downgrade and the
    # sliver screening rewrite solid_elems (those announce their own drops), so
    # the counts describe the real elements the .k file contained.
    _warn_orphan_elements(state)

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

    # Foam batch. MAT_005's P(mu) transform and MAT_126's V/V0-recomputed
    # yield curves synthesize /FUNCTs (so after _resolve_define_tables, and
    # before _make_functions which emits them); the MAT_126 slot wiring and
    # LCSR sampling need the parsed *DEFINE_CURVEs. Runs AFTER
    # _screen_provisional_elements / the tet passes so its shell-vs-solid
    # part classification (the ERROR-3046 warnings, MAT_154's Isolid gate)
    # reads the FINAL element lists — a phantom shell recovered from an
    # unmodelled *ELEMENT_SHELL_* option would otherwise draw a false
    # shell-part warning. And before _resolve_xref_parts below: LAW90
    # (MAT_073) is on the starter's solid-/XREF law whitelist, so that
    # container decides which parts get a /XREF; the other four
    # (LAW21/50/62/115) are off-whitelist and their _target_mat_law entries
    # make the gate warn-skip naming the law instead of claiming "no /MAT".
    # (Nothing between the adhesives pass and here allocates curve ids, so
    # the synthesized /FUNCT numbering is unchanged by this placement.)
    _resolve_mat_foams(state)

    # Tabulated Johnson-Cook batch. *DEFINE_TABLE_3D validation + its flat
    # Ndim=3 /TABLE/1 first (needs the resolved 2-D tables from
    # _resolve_define_tables above), then the MAT_224 wiring, which slices
    # the same nesting for LCK1, synthesizes flipped/exp-unwrapped curves and
    # AutoTables (so before _make_functions) and re-routes table-slot curves
    # via state.table_1d_ids. NUMINT's solid/shell split reads the FINAL
    # element lists (after _screen_provisional_elements, like the foams).
    # Before _resolve_xref_parts below: LAW109 is NOT on the starter's
    # solid-/XREF law whitelist, so the _target_mat_law entry alone makes
    # that gate warn-skip MAT_224 parts naming the law.
    _resolve_define_tables_3d(state)
    _resolve_mat_tabulated_jc(state)

    # Impact / blast batch (MAT_110 -> LAW79, MAT_111 -> LAW126,
    # *MAT_ELASTIC_FLUID -> LAW6 + /EOS/POLYNOMIAL). Synthesizes no curve and
    # no id, so its placement is free of the /FUNCT numbering; what it DOES
    # need is the final element lists, because all three laws are solid-only
    # (no SHELL_* class on any of them) and the ERROR-3046 warnings classify
    # parts as shell-vs-solid — hence after _screen_provisional_elements and
    # the tet passes, exactly like the foam and MAT_224 passes above. Before
    # _resolve_xref_parts below: NONE of LAW79 / LAW126 / LAW6 is on the
    # starter's solid-/XREF law whitelist, so their _target_mat_law entries
    # are what make that gate warn-skip such parts NAMING the law instead of
    # claiming they have no /MAT at all.
    _resolve_mat_impact(state)

    # Rare materials batch (*MAT_030 -> /MAT/LAW71). Synthesizes no curve and
    # no id, so its placement does not move the /FUNCT numbering; it only
    # reports the three hard starter guards (ERROR 1122/1123/1124) and the
    # E_mart sanity check. Before _resolve_xref_parts below: LAW71 is NOT on
    # the starter's solid-/XREF law whitelist, so its _target_mat_law entry is
    # what makes that gate warn-skip such parts NAMING the law instead of
    # claiming they have no /MAT at all.
    _resolve_mat_shape_memory(state)

    # R14 triage batch: *MAT_004 / *MAT_270 -> /MAT/LAW106. It SYNTHESIZES the
    # E(T), nu(T) and alpha(T) /FUNCTs and fills state.therm_stress_cards, so
    # it must precede _make_functions (which emits the curves) and
    # _resolve_thermal (whose _resolve_heat_materials reads therm_stress_cards
    # to decide which materials get the mandatory /HEAT/MAT — a
    # /THERM_STRESS/MAT without one is ERROR 1129). It must also precede
    # _resolve_thermal's SOLN=1 stand-in pass, whose screen is the EMITTED
    # /MAT registry: thermal-stress.k's *PART MID names a
    # *MAT_ELASTIC_PLASTIC_THERMAL that only converts because of this pass,
    # and screening before it would shadow the real material (#130).
    _resolve_mat_law106(state)

    # R14 triage batch: *MAT_010 -> /MAT/LAW3 + its same-id /EOS. Synthesizes
    # no curve and no id, so its placement does not move the /FUNCT numbering;
    # what it needs is state.eos_cards (filled at parse time) and the FINAL
    # element lists, because LAW3 declares SOLID_ISOTROPIC and SPH only
    # (hm_read_mat03.F:224-225) and the compatibility reports classify parts.
    # Before _resolve_xref_parts below: LAW3 is NOT on the starter's
    # solid-/XREF law whitelist, so its _target_mat_law entry is what makes
    # that gate warn-skip such a part NAMING the law instead of claiming it
    # has no /MAT at all.
    _resolve_mat_law3(state)

    # Materials REFUSED BY NAME (*MAT_102, *MAT_090, *MAT_031, *MAT_VACUUM,
    # *MAT_GAS_MIXTURE). The handler could only record the law and the reason
    # — it runs while the deck is still being parsed — so this pass, with the
    # mesh complete, adds the /PART ids and the element counts the refusal
    # costs. Emits nothing, so its placement is free.
    _warn_refused_materials(state)

    # Thermal expansion + the temperature drivers. MUST run BEFORE
    # _make_functions (it registers the synthesized coefficient and driver
    # curves in state.curves) and before _make_materials (it can SPLIT a
    # material that is shared by a part the *MAT_ADD_THERMAL_EXPANSION card
    # does not name, which changes what that writer emits and what
    # _target_mat_law answers). It allocates /FUNCT ids, so it is placed after
    # every other curve-synthesizing pass to keep their numbering unchanged.
    _resolve_thermal(state)

    # Airbag fabric (*MAT_FABRIC → /MAT/LAW19 + /PROP/TYPE9, or /MAT/LAW58 +
    # /PROP/TYPE16). Routes the law from FORM + the card-7 curves, fills the
    # derived moduli and names every dropped field. Synthesizes no curve and no
    # id, so its placement does not move the /FUNCT numbering; what it needs is
    # the FINAL element lists (the shell-only warnings classify parts) — hence
    # after _screen_provisional_elements and the tet passes, like the foam,
    # MAT_224 and impact passes above. It MUST precede _assign_fabric_props
    # (which reads use_law58 to choose the property type) and
    # _resolve_xref_parts below, which reads _target_mat_law: neither LAW19 nor
    # LAW58 is on the solid-/XREF whitelist, but a fabric part is a SHELL part
    # and the shell arm has no law gate, so the entry changes no /XREF decision
    # — it only stops that gate claiming "no /MAT at all".
    _resolve_mat_fabric(state)

    # *AIRBAG_* → /MONVOL. Resolves each bag's external surface to SHELL
    # ELEMENTS (a /SURF/SEG external surface is starter ERROR 18 and aborts the
    # run), measures the surface's closed-ness and signed volume, allocates the
    # /MONVOL, /SURF, /MAT/GAS and /PROP/INJECT1 ids, and synthesizes the
    # /FUNCTs the PRES / injector / LFLUID-Pmax slots need. Needs the FINAL
    # element lists (after _screen_provisional_elements and the tet passes) and
    # the flattened part sets (_flatten_part_set_adds, at the top); must run
    # before _make_functions, which emits the synthesized curves.
    _resolve_airbags(state)

    # Decide which parts get a /XREF (reference-geometry) block. AFTER the
    # tet10 passes (the 8/4-node-solid gate must see the final connectivity)
    # and BEFORE properties (their sections switch to Ismstr=10). Needs the
    # rubber routing from _resolve_mat_hyper_rubber above (LAW42-vs-LAW69
    # decides the starter's solid-/XREF law whitelist).
    _resolve_xref_parts(state)

    # *CONTACT_INTERIOR → Icontrol: resolution + warnings only (the input
    # column is radioss2025-only, measured — see _resolve_contact_interior).
    # AFTER _screen_provisional_elements so the solid-part classification
    # reads the final element lists; emits nothing, so order past that is
    # free.
    _resolve_contact_interior(state)

    # Composites: allocate the *MAT_032 glass companion ids and the MAT_037
    # hardening curves, then give every composite / orthotropic part its own
    # /PROP id. Both run BEFORE _assign_ortho_props (which skips the parts
    # claimed here), before parts (repoint) and properties (emit) — and
    # _resolve_composites also before _make_functions, which emits the curves.
    # Thick shells: fold the *ELEMENT_TSHELL_BETA angles into the properties
    # that have an angle slot, resolve the per-part layups
    # (*PART_COMPOSITE_TSHELL, a uniform *ELEMENT_TSHELL_COMPOSITE stack) and
    # claim a /PROP id for each. BEFORE _assign_composite_props, which skips
    # every thick-shell part: a *PART_COMPOSITE_TSHELL must reach /PROP/TYPE22
    # and not the thin-shell /PROP/TYPE51 sandwich (which the starter refuses
    # on bricks, ERROR 60 + 226 — dyna2rad's own defect). AFTER
    # _screen_provisional_elements, so the fold sees the final element list.
    _resolve_tshells(state)
    # SPH particles: screen the cells against the node table (a /SPHCEL id with
    # no /NODE is starter ERROR 78, a repeated one ERROR 79), auto-create a
    # placeholder *SECTION_SPH where a part names none, split a SECID shared
    # with another element family, and decide PER SECTION whether each
    # particle's mass rides on its own /SPHCEL row or on the property's Mp —
    # the choice that also decides whether the deck's smoothing length survives.
    # AFTER _screen_provisional_elements (state.sph_elems must be final) and
    # before the parts (repoint + /SPHCEL emission) and properties are built.
    _resolve_sph(state)
    _resolve_composites(state)
    # Fabric: one synthesized /PROP per *MAT_FABRIC part. FIRST among the shell
    # property-assignment prepasses — _assign_composite_props,
    # _assign_ortho_props and _assign_hourglass_props all skip a part already
    # in state.fabric_prop_ids, because /MAT/LAW19 and /MAT/LAW58 each accept
    # exactly ONE property class (starter ERROR 3047) and any overlay would
    # replace it. Before _make_parts_and_elements (repoint) and
    # _make_properties (suppress the section's now-unused /PROP/SHELL).
    # Seatbelts: fold the 2D (shell) belt elements into state.shell_elems and
    # claim a /PROP/TYPE9 for each 2D belt part. BEFORE _assign_fabric_props
    # and the three shell property passes it precedes, for the same reason
    # fabric goes first: /MAT/LAW119 accepts exactly ONE property class
    # (starter ERROR 3047) and any later overlay would replace it. Before
    # _make_parts_and_elements (which repoints the /PART and emits the folded
    # shells) and before _make_properties (which suppresses the section's
    # now-unused /PROP/SHELL). A no-op, drawing no id, on any deck without a
    # *MAT_SEATBELT.
    _assign_seatbelt_props(state)
    _assign_fabric_props(state)
    _assign_composite_props(state)
    # Bind every *SECTION_SHELL QR/IRID reference to its *INTEGRATION_SHELL
    # rule, let the rule's NIP win over the section's, and claim a /PROP for the
    # parts that pass did not (an ordinary isotropic material with a rule).
    # AFTER _resolve_composites (a rule on a *MAT_032 part needs the synthesized
    # glass id) and AFTER _assign_composite_props (it only ADDS claims); before
    # _resolve_icomp_sections, whose "angles are DROPPED" ladder must not fire
    # for a part the rule now routes to a layered /PROP/TYPE11.
    _resolve_integration_shells(state)
    # Then report every *SECTION_SHELL ICOMP=1 layup whose angles cannot reach a
    # Radioss property — needs the composite_prop_ids the line above allocated.
    _resolve_icomp_sections(state)

    # Bind every *SECTION_BEAM QR/IRID reference to its *INTEGRATION_BEAM rule
    # and decide, per section, between the integrated /PROP/TYPE18 and the
    # resultant /PROP/BEAM. AFTER _screen_provisional_elements (state.beam_elems
    # must be final: a phantom element would otherwise claim a section) and
    # AFTER _resolve_mat_johnson_cook (its LAW2-vs-LAW4 routing decides the
    # TYPE18 material gate); before the parts and the properties are emitted.
    _resolve_integration_beams(state)

    # Assign a synthesized orthotropic /PROP id to each LAW128 (MAT_103) part
    # (LAW128 is orthotropic-only). Must run before parts (which repoint the
    # /PART at it) and properties (which emit it) are built.
    _assign_ortho_props(state)

    # *ELEMENT_SHELL_BETA: the starter reads the per-element /SHELL Phi column
    # only for IGTYP 17/51/52, so a uniform angle on an IGTYP 9/10/11/16 part
    # has to be folded into that part's property instead. AFTER both /PROP
    # assignment prepasses (it needs to know which class each part lands on) and
    # before the elements and the properties are emitted.
    _fold_element_beta(state)

    # Per-part hourglass control (*HOURGLASS + *PART HGID / *CONTROL_HOURGLASS):
    # allocate a dedicated /PROP id for each part whose effective hourglass
    # differs from its section base. Runs AFTER ortho (it skips ortho parts) and
    # before parts (repoint) and properties (emit).
    _assign_hourglass_props(state)

    # *ELEMENT_BEAM_ORIENTATION: turn each VX/VY/VZ into a real third node at
    # N1 + V. Before the /NODE section (so the nodes are emitted) and before the
    # other node-synthesizing prepasses, which allocate off max(state.nodes)+1
    # and therefore have to see these ids already registered.
    _synthesize_beam_orientation_nodes(state)

    # Moving rigid walls need their carrier node in the deck BEFORE the /NODE
    # section is built (the /RWALL cards themselves are emitted later).
    _synthesize_rwall_moving_nodes(state)

    # *RIGIDWALL_GEOMETRIC_*: resolve each wall's geometry to the concrete
    # /RWALL wall(s) — a prism becomes six /RWALL/PARAL faces — and synthesize
    # the _MOTION carrier nodes. Same constraint as above (nodes before /NODE),
    # and it has to follow the planar prepass so both allocate off a
    # max(state.nodes)+1 that already includes the earlier synthesis.
    _resolve_geometric_rigid_walls(state)

    # Assign a /SKEW id to every *DEFINE_VECTOR[_NODES] / *DEFINE_SD_ORIENTATION
    # and synthesize the third node each moving /SKEW/MOV needs — before the
    # /NODE section (so the nodes are emitted) and before /FRAME allocation (so
    # the ids are reserved in the shared /SKEW+/FRAME namespace).
    _synthesize_vector_skews(state)

    # *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL: build each body's co-rotating
    # /SKEW/MOV triad out of three synthesized element-free nodes. Same two
    # constraints as the vector skews (nodes before /NODE, ids before /FRAME),
    # plus a third: it must precede the /RBODY sections below, which fold
    # state.local_frame_nodes into the bodies' secondary groups.
    _synthesize_local_motion_frames(state)

    # Reserve a /SKEW id for each *CONSTRAINED_JOINT frame and register the
    # joint /SPRING nodes. After the vector skews (which prefer their own VID
    # and should get first pick of the low ids) and before /FRAME allocation,
    # which shares the /SKEW id namespace. Registering the spring nodes here
    # rather than in _make_joints keeps the implicit free-node guard correct
    # regardless of section order.
    _resolve_joints(state)

    # *ELEMENT_DISCRETE, MAT_100 spotweld beams and *ELEMENT_PLOTEL all become
    # /SPRING under their SOURCE-deck ids, which LS-DYNA keeps in three separate
    # namespaces and Radioss in one. Report the overlap here rather than letting
    # the starter be the first to mention it (ERROR 79, no restart file).
    _warn_spring_eid_collisions(state)

    rbody_lines, rigid_nodes, rbody_info = _make_rbodies(state)
    # *CONSTRAINED_NODAL_RIGID_BODY produces additional /RBODY entries that must
    # be visible to every rigid-body-keyed section below, so merge their info,
    # rigid-node set, and rad lines with the *MAT_RIGID ones.
    cnrb_lines, cnrb_rigid_nodes, cnrb_info = _make_cnrb_rbodies(state)
    rigid_nodes = rigid_nodes | cnrb_rigid_nodes
    # The two dicts are keyed by DIFFERENT id namespaces — *MAT_RIGID records by
    # PART id, CNRB records by the CNRB's own PID — so a CNRB whose PID happens
    # to equal a rigid part's id silently replaces that part's record here, and
    # every rbody_info consumer below (gravity groups, /BCS, /INIVEL, /TH) then
    # addresses the wrong main node. LS-DYNA requires a CNRB's PID to be a new,
    # unused part id, so this is invalid input — but it must not be silent.
    for _dup in sorted(set(rbody_info) & set(cnrb_info)):
        state.warn(
            f"*CONSTRAINED_NODAL_RIGID_BODY PID {_dup} collides with the id of "
            "a *MAT_RIGID part that k2rad also turned into an /RBODY. The CNRB "
            "record wins, so cards keyed on that part id (gravity groups, "
            "/BCS, /INIVEL, /TH) address the CNRB's main node and the rigid "
            "PART's own main node is not reached - give the CNRB an unused "
            "part id.")
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
    _pad_surfaces_for_spmd_th_surf(state, lines)
    _warn_duplicate_th_group_ids(state, lines)
    _warn_duplicate_prop_ids(state, lines)
    _warn_duplicate_mat_ids(state, lines)
    _warn_duplicate_eos_ids(state, lines)
    _warn_duplicate_group_ids(state, lines)
    _warn_node_tc_rc(state, lines)
    _warn_duplicate_thermal_ids(state, lines)
    _warn_duplicate_thermal_bc_ids(state, lines)
    _warn_duplicate_preload_ids(state, lines)
    _warn_duplicate_sect_ids(state, lines)
    _warn_duplicate_function_ids(state, lines)
    _warn_duplicate_impdisp_ids(state, lines)
    _warn_duplicate_inter_ids(state, lines)
    _warn_dangling_part_materials(state, lines)
    _rep(1.0, "Starter deck ready")
    return "\n".join(lines) + "\n"


# Every /SURF option of any type counts toward the engine's surface table, in
# deck order (verified against a real run, see _pad_surfaces_for_spmd_th_surf).
_SURF_CARD_RE = re.compile(r"^/SURF/(?:[A-Z0-9_]+/)+(\d+)\s*$")
_TH_SURF_HEAD_RE = re.compile(r"^/TH/SURF/\d+\s*$")


def _th_surf_listed_ids(lines: List[str]) -> List[int]:
    """Surface ids listed inside every emitted /TH/SURF block (the block's id
    lines are right-aligned integers; the title, the comments and the VAR line
    are skipped; the block ends at the next '/' card)."""
    ids: List[int] = []
    i = 0
    while i < len(lines):
        if _TH_SURF_HEAD_RE.match(lines[i]):
            j = i + 2                       # skip the head and the title line
            while j < len(lines) and not lines[j].startswith("/"):
                ln = lines[j]
                if not ln.startswith("#"):
                    toks = ln.split()
                    if toks and all(t.isdigit() for t in toks):
                        ids.extend(int(t) for t in toks)
                j += 1
            i = j
        else:
            i += 1
    return ids


def _pad_surfaces_for_spmd_th_surf(state: ConversionState,
                                   lines: List[str]) -> None:
    """Append inert /SURF/SEG padding cards so every /TH/SURF surface survives
    the engine's SPMD reduction — the fix for "the second blast surface's P/A
    channels are exactly 0.0 for the whole run".

    **OpenRadioss engine bug** (present at least through the 20260520 tree):
    the /TH/SURF channel array FSAVSURF is (TH_SURF_NUM_CHANNEL=6, NSURF)
    (common_source/modules/interfaces/th_surf_mod.F:96-100, allocated with the
    GLOBAL surface count in engine/source/engine/resol_alloc.F90:336), but the
    MPI reduction only covers the first 5*NSURF of its 6*NSURF elements:

        engine/source/output/th/hist2.F:679
        IF(NSPMD > 1)CALL SPMD_GLOB_DSUM9(FSAVSURF,5*NSURF)

    a stale length from before the 6th channel (cumulated mass) was added.
    Fortran is column-major, so surface I's channel c sits at flat position
    6*(I-1)+c and is reduced across MPI domains only while 6*(I-1)+c <= 5*NSURF.
    Any surface with internal index I > ~(5/6)*NSURF loses the tail channels —
    including ch4 (pressure accumulator) and ch5 (loaded area) that /LOAD/PBLAST
    fills (engine pblast_1.F:418-419). Domain 0 then writes its LOCAL-only
    values: exactly 0.0 whenever domain 0 owns none of the loaded segments, and
    hist2.F:687-691 zeroes P outright when the unreduced ch5 stays 0. The
    internal index is the surface's position among ALL /SURF options in deck
    order (planes included), NOT its position inside the /TH/SURF block —
    multiple ids per /TH/SURF block are fully legal (starter
    hm_read_thgrsurf.F:147-175 flags each id; thsurf.F:71-80 writes one
    var-set per listed surface).

    Field evidence (OpenRadioss 2026, two independent SPMD runs):
      * E:/w13/stack4 (12 domains, 13 surfaces): witness surface 90031 is the
        10th surface -> positions 58/59 <= 65 -> correct (peak 222.7 MPa);
        surface 90034 is the 12th -> positions 70/71 > 65 -> all-zero T01.
      * E:/w13/neuberger (6 domains, 2 surfaces): 90001 is 1st -> correct;
        90003 is 2nd -> its ch4 (position 10) IS reduced but ch5 (position 11)
        is not, so the divide guard zeroes P as well -> all-zero T01.
      * Cross-check: were /SURF/PLANE not counted, 90031 would have been the
        10th of 11 (position 59 > 55) and failed too — it did not.

    The deck-side fix: raise NSURF without moving the /TH/SURF surfaces, by
    appending K inert /SURF/SEG cards AFTER every real surface, so that
    6*(I_max-1)+5 <= 5*(NSURF+K) holds for the highest-indexed /TH/SURF
    surface (K = ceil((6*I_max - 1 - 5*NSURF)/5), usually 1-2 cards). The
    criterion covers channels 1..5 — everything through ch5 (loaded area),
    which the emitted VAR line (P, A -> ch4, ch5) needs; ch6 is the
    monvol/EBCS cumulated mass, which /LOAD/PBLAST never fills and k2rad
    never requests. Each padding card duplicates one existing blast segment
    (valid nodes, zero physics) and is referenced by nothing. Splitting the
    /TH/SURF block per surface would change NOTHING — the failure depends
    only on the global surface index. Harmless on SMP runs and after the
    upstream one-word fix (5*NSURF -> TH_SURF_NUM_CHANNEL*NSURF)."""
    th_ids = set(_th_surf_listed_ids(lines))
    if not th_ids:
        return
    surf_ids = [int(m.group(1)) for ln in lines
                if (m := _SURF_CARD_RE.match(ln))]
    positions = [pos for pos, sid in enumerate(surf_ids, start=1)
                 if sid in th_ids]
    if not positions:
        return
    n_surf = len(surf_ids)
    i_max = max(positions)
    deficit = 6 * (i_max - 1) + 5 - 5 * n_surf
    if deficit <= 0:
        return
    k_pad = -(-deficit // 5)        # ceil(deficit / 5)

    # Donor segment for the inert cards: the first data line of the first
    # /SURF/SEG among the /TH/SURF surfaces (k2rad emits blast surfaces as
    # /SURF/SEG, so one always exists when th_ids is non-empty).
    donor_nodes: List[int] = []
    for sid in surf_ids:
        if sid not in th_ids:
            continue
        try:
            head = lines.index(f"/SURF/SEG/{sid}")
        except ValueError:
            continue
        for ln in lines[head + 2:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#"):
                continue
            toks = ln.split()
            if len(toks) >= 4 and all(t.isdigit() for t in toks):
                donor_nodes = [int(t) for t in toks[1:5]]
                break
        if donor_nodes:
            break
    if not donor_nodes:
        state.warn(
            "/TH/SURF SPMD padding: no /SURF/SEG donor segment found for the "
            "/TH/SURF surfaces — padding NOT emitted. On an MPI run the "
            "highest-indexed /TH/SURF surfaces will record 0.0 (engine "
            "hist2.F:679 reduces only 5*NSURF of the 6*NSURF /TH/SURF "
            "channels). This is a k2rad bug — please report the deck.")
        return

    pad_ids = [state.next_id() for _ in range(k_pad)]
    pad_lines: List[str] = [
        "#-  /TH/SURF SPMD padding surfaces (inert, referenced by nothing):",
        HDR,
    ]
    for k, pid in enumerate(pad_ids, start=1):
        pad_lines += [
            f"/SURF/SEG/{pid}",
            f"TH_surf_spmd_pad_{k} (inert; extends the surface table for the "
            f"SPMD /TH/SURF reduction)"[:100],
            "#   seg_ID        n1        n2        n3        n4",
            _i(1) + "".join(_i(n) for n in donor_nodes),
            HDR,
        ]
    # Insert before the trailing /END so the padding surfaces are the LAST
    # /SURF options in the deck (highest internal indices, ids from next_id()
    # so they also sort last by id — the /TH/SURF surfaces keep their index).
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == "/END":
            lines[i:i] = pad_lines
            break
    else:
        lines.extend(pad_lines)
    state.warn(
        "/TH/SURF + MPI: the OpenRadioss engine reduces only 5*NSURF of the "
        "6*NSURF-element /TH/SURF channel array across SPMD domains "
        "(hist2.F:679 SPMD_GLOB_DSUM9(FSAVSURF,5*NSURF) vs "
        "TH_SURF_NUM_CHANNEL=6, th_surf_mod.F:100), so a surface whose "
        "internal index I violates 6*(I-1)+5 <= 5*NSURF records exactly 0.0 "
        "for P and A on a multi-domain run (its channels never leave the domains "
        f"that loaded them). Emitted {k_pad} inert padding /SURF/SEG card(s) "
        f"(id(s) {', '.join(str(p) for p in pad_ids)}) after the last real "
        f"surface so all {len(positions)} /TH/SURF surface(s) satisfy the "
        "inequality (surface table "
        f"{n_surf} -> {n_surf + k_pad}, highest /TH/SURF index {i_max}). The "
        "padding has no physics and is harmless on SMP runs; it can be "
        "dropped once the engine is fixed upstream "
        "(5*NSURF -> TH_SURF_NUM_CHANNEL*NSURF).")


# /TH group ids are unique across the WHOLE time-history namespace, not per
# /TH type. Six independent builders emit /TH blocks (five in writer/output.py,
# plus inistate /TH/SECTIO and loads /TH/RWALL) and they do not share one
# allocator: _make_starter_th numbers its blocks 1..N off a local counter while
# the rest draw from state.next_id(). Nothing tied the two together, so
# /TH/INTER's hard-coded id 1 collided with the first _make_starter_th block
# and the starter refused the deck outright:
#
#   ERROR ID : 79 / ** ERROR: DUPLICATE ID
#   IN TH GROUP DEFINITION / ID=1 is DUPLICATED
#   .. ERROR ==> NO RESTART FILE
#
# The id is now allocated, but the shape of the bug is the interesting part: a
# builder can be added without knowing about the others. This scans what was
# actually emitted, so the next collision is a converter warning naming the
# blocks rather than an unexplained starter error with no restart file.
_TH_GROUP_RE = re.compile(r"^/TH/([A-Z0-9_]+)/(\d+)\s*$")


def _warn_duplicate_th_group_ids(state: ConversionState,
                                 lines: List[str]) -> None:
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _TH_GROUP_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(m.group(1))
    # Same scan, second consumer: build_engine's /TFILE fallback needs to know
    # whether ANY /TH group reached the deck, and this is the one place that
    # counts what was actually emitted rather than what each builder intended.
    # build_starter runs before build_engine (k2rad/__init__.py:470-473), so
    # the count is set by the time _make_engine_output reads it.
    state.th_groups_emitted = sum(len(t) for t in seen.values())
    for tid, types in sorted(seen.items()):
        if len(types) > 1:
            state.warn(
                f"TIME HISTORY: group id {tid} is emitted by more than one "
                f"/TH block (" + ", ".join(f"/TH/{t}/{tid}" for t in types)
                + "). The /TH id namespace is global across types, so the "
                "OpenRadioss starter will reject this deck with ERROR 79 "
                "(DUPLICATE ID, IN TH GROUP DEFINITION) and write no restart "
                "file. This is a k2rad bug — please report the deck.")


#: Every property card header, whatever its type: ``/PROP/SHELL/12``,
#: ``/PROP/TYPE20/12``, ``/PROP/SPH/12``, ``/PROP/SOLID/12``.
_PROP_CARD_ID_RE = re.compile(r"^/PROP/(?:[A-Z0-9_]+/)*([A-Z0-9_]+)/(\d+)\s*$")


def _warn_duplicate_prop_ids(state: ConversionState,
                             lines: List[str]) -> None:
    """The /PROP id namespace is GLOBAL across property types — two cards on
    one id is starter ``ERROR ID : 79 DUPLICATE ID / IN PID DEFINITION`` and the
    whole deck is refused.

    Every family that turns a ``*SECTION_*`` into a property keys it on the
    SECID, and LS-DYNA's section-id namespaces are PER FAMILY: a
    ``*SECTION_SHELL 2`` and a ``*SECTION_SPH 2`` are different cards in a legal
    deck. Each family's writer guards the collisions it can see from where it
    stands (``writer/sph.py`` and ``writer/tshell.py`` both split a shared
    SECID and both refuse a section of the wrong family), but no single writer
    sees the FINISHED deck — measured, a ``*SECTION_SOLID 2`` beside an
    unreferenced ``*SECTION_SHELL 2`` emits both properties with no diagnostic
    on any branch of the converter.

    This is the scan that does see it: one pass over the assembled starter,
    modelled on :func:`_warn_duplicate_th_group_ids`. It changes no output —
    it only makes a refusal that was silent into one the log names, with the
    ids and card types that collided.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _PROP_CARD_ID_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(m.group(1))
    for pid, types in sorted(seen.items()):
        if len(types) > 1:
            state.warn(
                f"PROPERTY ID {pid} is emitted by more than one /PROP card ("
                + ", ".join(f"/PROP/{t}/{pid}" for t in types)
                + "). The /PROP id namespace is global across property TYPES, "
                "while LS-DYNA's *SECTION_* id namespaces are per family, so "
                "two sections of different families sharing an id land on one "
                "Radioss property id. The starter refuses the whole deck with "
                "ERROR 79 (DUPLICATE ID, IN PID DEFINITION). Renumber one of "
                "the *SECTION_* cards.")


#: A ``/PART/<pid>`` header, and any ``/MAT/<...>/<mid>`` header whatever the
#: law spelling (``/MAT/ELAST/1``, ``/MAT/LAW19/3``, ``/MAT/GAS/CSTA/90002``).
_PART_CARD_ID_RE = re.compile(r"^/PART/(\d+)\s*$")
_MAT_CARD_ID_RE = re.compile(r"^/MAT/(?:[A-Z0-9_]+/)*(\d+)\s*$")


#: ``/MAT/<law spelling>/<mid>``, capturing the law spelling AND the id, so a
#: duplicate can be reported as "which two cards".
_MAT_CARD_LAW_ID_RE = re.compile(r"^/MAT/((?:[A-Z0-9_]+/)*[A-Z0-9_]+)/(\d+)\s*$")


def _warn_duplicate_mat_ids(state: ConversionState,
                            lines: List[str]) -> None:
    """The /MAT id namespace is GLOBAL across material laws — two cards on one
    id is starter ``ERROR ID : 79 DUPLICATE ID / IN MATERIAL DEFINITION`` and
    the deck is refused, usually with a second error on whichever /PART
    resolved to the wrong one of the pair.

    The twin of :func:`_warn_duplicate_prop_ids`, and it exists for the same
    reason: k2rad emits every /MAT under the LS-DYNA MID verbatim (there is no
    material-duplication remap as in dyna2rad), each family guards only the
    collisions it can see from where it stands, and no single writer sees the
    FINISHED deck. MEASURED before this scan existed — a *PART on a
    *SECTION_SEATBELT whose MID was an ordinary *MAT_ELASTIC emitted both
    ``/MAT/ELAST/<mid>`` and ``/MAT/LAW114/<mid>`` with no diagnostic on any
    branch, and two belt parts sharing one *MAT_SEATBELT emitted its
    ``/MAT/LAW114`` twice. Both CAUSES are fixed in writer/seatbelts.py; this
    removes the CLASS, so the next family cannot make the failure silent again.

    Changes no output.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _MAT_CARD_LAW_ID_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(m.group(1))
    for mid, laws in sorted(seen.items()):
        if len(laws) > 1:
            state.warn(
                f"MATERIAL ID {mid} is emitted by more than one /MAT card ("
                + ", ".join(f"/MAT/{law}/{mid}" for law in laws)
                + "). The /MAT id namespace is global across material LAWS, so "
                "the starter refuses the whole deck with ERROR 79 (DUPLICATE "
                "ID, IN MATERIAL DEFINITION) and every /PART naming that id "
                "resolves to whichever card came first. Renumber one of the "
                "*MAT_* cards.")


#: ``/<FAMILY>/<sub-keyword...>/<id>`` for every GROUP namespace, capturing the
#: FAMILY (the first path segment) and the id. The sub-keyword is deliberately
#: NOT part of the key — MEASURED, ``/GRBRIC/BRIC/5000`` beside
#: ``/GRBRIC/PART/5000`` is ``ERROR 79 ... IN BRIC ELEMENT GROUP``, so they are
#: one namespace.
_GROUP_CARD_ID_RE = re.compile(
    r"^/(GRBRIC|GRQUAD|GRSHEL|GRSH3N|GRTRIA|GRTRUS|GRBEAM|GRSPRI|GRNOD"
    r"|GRPART|SURF|LINE|SUBSET)/(?:[A-Z0-9_]+/)*(\d+)\s*$")

#: The starter's own ``MESS`` string per family, so the warning quotes the text
#: the user will actually see. ``hm_lecgre.F:150-152`` builds the element-group
#: ones as ``MES(01:04)=ELKEY; MES(05:18)=' ELEMENT GROUP'``; the others come
#: from their own readers (``hm_lecgrn.F:142``, ``hm_read_grpart.F:85``,
#: ``hm_read_surf.F:187``, ``hm_read_lines.F:163``, ``hm_read_subset.F:103``).
_GROUP_FAMILY_MESS = {
    "GRBRIC": "BRIC ELEMENT GROUP",
    "GRQUAD": "QUAD ELEMENT GROUP",
    "GRSHEL": "SHEL ELEMENT GROUP",
    "GRSH3N": "SH3N ELEMENT GROUP",
    "GRTRIA": "TRIA ELEMENT GROUP",
    "GRTRUS": "TRUS ELEMENT GROUP",
    "GRBEAM": "BEAM ELEMENT GROUP",
    "GRSPRI": "SPRI ELEMENT GROUP",
    "GRNOD":  "NODE GROUP DEFINITION",
    "GRPART": "PART GROUP",
    "SURF":   "SURFACE DEFINITION",
    "LINE":   "LINE DEFINITION",
    "SUBSET": "SUBSET DEFINITION",
}


def _warn_node_tc_rc(state: ConversionState, lines: List[str]) -> None:
    """``*NODE``'s TC/RC constraint cells are read and DROPPED — say so.

    Vol I R17's ``*NODE`` Card 1 is ``NID X Y Z TC RC``: TC and RC are
    constraint codes (0 none, 1 x, 2 y, 3 z, 4 xy, 5 yz, 6 zx, 7 xyz) in the
    global system, exactly the triples ``*BOUNDARY_SPC_NODE`` states one flag
    at a time. ``handle_node`` reads only NID/X/Y/Z, so a deck that states its
    constraints there converts into a model with those DOFs FREE.

    This is the silent half that makes it worth a message: measured on a
    spring-mass coupon whose anchor carried ``tc=7 rc=7``, no ``/BCS`` was
    emitted, the anchor was free, the whole oscillator drifted at the
    centre-of-mass velocity (node-2 DX reached 6.68 mm against an intended
    0.317 mm amplitude) — and the run still reported NORMAL TERMINATION. The
    #122 class: legal, accepted, and wrong.

    **Not converted here, and the reason is the SCREENING, not the direction
    of the error.** An earlier draft argued that an extra constraint is the
    harder failure to notice than a missing one; that does not justify
    shipping a missing one. What does justify deferral is that a correct /BCS
    pass has to screen two things this round cannot validate:

      * p.35-3 Remark 1, verbatim: *"No attempt should be made to apply
        boundary conditions to nodes belonging to rigid bodies (see
        \\*MAT_RIGID for application of rigid body constraints)."* So every
        rigid-body secondary node has to come out of the set, and k2rad's
        rigid nodes are assembled across ``*MAT_RIGID`` parts,
        ``*CONSTRAINED_NODAL_RIGID_BODY`` and the synthesized element-free
        masters.
      * A DOF already driven by ``/IMPVEL`` or ``/IMPDISP`` must not also be
        pinned — the two cards fight over the same slot.

    Both need their own twin campaign against LS-DYNA, and the need is
    MEASURED rather than asserted: of the 721 carrying decks in the two corpus
    roots, **278 (39 %) also carry a rigid body or a prescribed motion** —
    139 a ``*MAT_RIGID`` / ``*CONSTRAINED_NODAL_RIGID_BODY`` /
    ``*CONSTRAINED_EXTRA_NODES``, 211 a ``*BOUNDARY_PRESCRIBED_MOTION_*`` — so
    a naive pass would be wrong on two decks in five. The other 443 (61 %)
    would be safe, which is exactly why the conversion is worth building.

    The interim is the loud per-deck note below, and the conversion is a
    ROADMAP item behind an opt-in flag (``--node-tc-rc-to-bcs``) so the
    carrying decks can be fixed without changing the default for everyone.

    The detector itself is independently checked: a scanner that does not use
    k2rad found a non-zero TC/RC in exactly the decks this note fires on, with
    no false positives and no misses.
    """
    if not state.node_tc_rc_count:
        return
    shown = ", ".join(str(n) for n in state.node_tc_rc[:5])
    more = ("" if state.node_tc_rc_count <= 5
            else f" and {state.node_tc_rc_count - 5} more")
    state.warn(
        f"*NODE: {state.node_tc_rc_count} node(s) state a constraint in the "
        f"card's own TC/RC cells (node {shown}{more}) — Vol I R17 makes *NODE "
        "Card 1 'NID X Y Z TC RC', where TC and RC are constraint codes (0 "
        "none, 1 x, 2 y, 3 z, 4 xy, 5 yz, 6 zx, 7 xyz) in the GLOBAL system. "
        "k2rad reads only NID/X/Y/Z, so those degrees of freedom are FREE in "
        "the converted model and no /BCS is emitted for them. Nothing in the "
        "run reports it: measured on a spring-mass coupon whose anchor carried "
        "tc=7/rc=7, the anchor was free and the whole oscillator drifted at "
        "the centre-of-mass velocity while the engine printed NORMAL "
        "TERMINATION. Restate the constrained nodes as *BOUNDARY_SPC_NODE (or "
        "*BOUNDARY_SPC_SET), which this converter does emit as /BCS.")


def _warn_duplicate_group_ids(state: ConversionState,
                              lines: List[str]) -> None:
    """One id per GROUP FAMILY — and the families are INDEPENDENT.

    ``lecgroup.F:124-224`` calls ``HM_LECGRE`` once per element family, each
    with its own array, and ``hm_lecgre.F:262-267`` runs ``UDOUBLE_IGR`` over
    that family's list only; ``/GRNOD``, ``/GRPART``, ``/SURF``, ``/LINE`` and
    ``/SUBSET`` each have their own reader and their own ``UDOUBLE``. So a
    duplicate is ``ERROR 79`` only within one family.

    MEASURED, twelve probe decks on one 6-family mesh, all at id 5000:

      * ``/GRBRIC/BRIC`` + ``/GRSHEL/SHEL``        -> ACCEPTED, 0 ERROR
      * ``/GRSHEL/SHEL`` + ``/GRSH3N/SH3N``        -> ACCEPTED
      * ``/GRSPRI`` + ``/GRBEAM``, ``/GRSPRI`` + ``/GRTRUS``  -> ACCEPTED
      * ``/GRNOD`` + ``/GRBRIC``, ``/GRPART`` + ``/GRSHEL``,
        ``/SURF`` + ``/GRSHEL``, ``/SUBSET`` + ``/GRBRIC``    -> ACCEPTED
      * NINE groups on one id across nine families -> ACCEPTED, 0 ERROR
      * ``/GRBRIC/BRIC`` twice -> ``ERROR ID : 79 ** ERROR: DUPLICATE ID /
        IN BRIC ELEMENT GROUP / ID=5000 is DUPLICATED``
      * ``/GRBRIC/BRIC`` + ``/GRBRIC/PART`` -> the SAME ERROR 79, so the
        sub-keyword is not part of the key
      * ``/GRPART/PART`` twice -> ``ERROR 79 ... IN PART GROUP``

    **A single scan over "any /GR* id" would therefore be WRONG** and would
    fire on five of those decks. This is the missing member of the family of
    deck-wide scans at :func:`build_starter`'s finish pass, which had nine
    (TH-group, PROP, MAT, thermal, preload, SECT, FUNCTION, IMPDISP, INTER) and
    now has eleven with ``/EOS``. Changes no output.

    A collision is not reachable today — the synthesized ids come from
    monotonic allocators and nothing re-emits a user element set under its own
    SID — which is exactly why this exists: it removes the CLASS, so the next
    writer that decides to pass a deck-stated id through cannot make the
    failure silent again.
    """
    seen: Dict[Tuple[str, int], List[str]] = {}
    for ln in lines:
        m = _GROUP_CARD_ID_RE.match(ln)
        if m:
            seen.setdefault((m.group(1), int(m.group(2))), []).append(
                ln.strip())
    for (fam, gid), cards in sorted(seen.items()):
        if len(cards) > 1:
            mess = _GROUP_FAMILY_MESS.get(fam, f"{fam} GROUP")
            state.warn(
                f"GROUP ID {gid} is emitted by more than one /{fam} card ("
                + ", ".join(cards)
                + f"). The starter keeps ONE table per family and checks it "
                f"with UDOUBLE_IGR, so this is ERROR 79 (DUPLICATE ID, IN "
                f"{mess}) and the whole deck is refused. Note the families are "
                "INDEPENDENT — a /GRBRIC and a /GRSHEL may legally share a "
                "number, and this scan is keyed per family for that reason — "
                "but the sub-keyword is NOT part of the key: /"
                f"{fam}/<one sub-keyword> and /{fam}/<another> collide.")


#: ``/EOS/<kind>/<mid>``, capturing the kind AND the id. ``-`` is in the class
#: because ``/EOS/IDEAL-GAS`` is a real spelling.
_EOS_CARD_KIND_ID_RE = re.compile(r"^/EOS/([A-Z0-9_-]+)/(\d+)\s*$")


def _warn_duplicate_eos_ids(state: ConversionState,
                            lines: List[str]) -> None:
    """One ``/EOS`` per /MAT id — and the starter will NOT tell you otherwise.

    An ``/EOS``'s id is not an id of its own: it is a POINTER into the /MAT
    table. ``hm_read_eos.F:165-177`` scans ``IPM(1,IMAT)`` for a material of
    the same number and raises ERROR 1663 (UNKNOWN REFERENCE TO MATERIAL MODEL)
    when there is none, then ``:301-304`` writes ``IPM(4,IMAT) = IEOS``. There
    is **no** ``UDOUBLE``/``VDOUBLE`` call anywhere in that routine, so unlike
    every other namespace this one has no duplicate check: two ``/EOS`` blocks
    on one id are accepted at 0 ERROR / 0 WARNING and the LAST one silently
    replaces the material's equation of state. MEASURED (probe ``a_dupeos``,
    a /MAT/HYD_VISC carrying two /EOS): NORMAL TERMINATION, both echoed, last
    ``IEOS`` wins — strictly worse than the ERROR 79 the /MAT twin gets,
    because nothing at any layer says a pressure law was replaced.

    The missing member of the family at :func:`build_starter`'s finish pass
    (nine scans existed, none for /EOS), added with the *EOS_* carrier fix:
    ``2Dlag.k`` emitted ``/EOS/GRUNEISEN/3`` and ``/EOS/POLYNOMIAL/3`` and only
    the ``/MAT`` half of that double collision was diagnosed. Changes no
    output.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _EOS_CARD_KIND_ID_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(m.group(1))
    for mid, kinds in sorted(seen.items()):
        if len(kinds) > 1:
            state.warn(
                f"MATERIAL ID {mid} carries more than one /EOS card ("
                + ", ".join(f"/EOS/{k}/{mid}" for k in kinds)
                + "). A Radioss /EOS binds to the /MAT of the SAME id "
                "(hm_read_eos.F:165-177), one per material, and the starter "
                "does NOT diagnose a duplicate — it accepts both blocks and "
                f"the LAST one wins, so material {mid} silently runs with "
                f"/EOS/{kinds[-1]}/{mid} and the others are dead input. "
                "Renumber or remove the *EOS_* cards that were not meant for "
                "this material (in LS-DYNA an *EOS_* binds only through the "
                "*PART EOSID field).")


#: ``/HEAT/MAT/<mid>`` and ``/THERM_STRESS/MAT/<mid>`` — a THIRD id namespace,
#: and one ``_MAT_CARD_LAW_ID_RE`` deliberately does not see (three path
#: segments, and the middle one is not a law spelling).
_THERMAL_MAT_CARD_ID_RE = re.compile(
    r"^/(HEAT|THERM_STRESS)/MAT/(\d+)\s*$")


def _warn_duplicate_thermal_ids(state: ConversionState,
                                lines: List[str]) -> None:
    """One ``/HEAT/MAT`` and one ``/THERM_STRESS/MAT`` per MATERIAL id.

    The sibling of :func:`_warn_duplicate_mat_ids` for the thermal subobject
    namespaces, added with the thermal-expansion batch for exactly the reason
    that one exists: ``*MAT_ADD_THERMAL_EXPANSION`` is keyed on a PART while
    both Radioss cards are keyed on a MATERIAL, so two cards naming two parts
    that share one MID are the natural way to emit either card twice — which is
    the #125 ``/PROP/TYPE23`` failure, one namespace over. dyna2rad does
    exactly that and the starter does NOT refuse it: measured, two
    ``*MAT_ADD_THERMAL_EXPANSION`` cards on one MID give ONE echoed block
    carrying the FIRST card's values and no duplicate-id error at all, so the
    second card is silently lost.

    writer/thermal.py keys both on a per-mid dict, so a duplicate cannot arise
    from there; this removes the CLASS, so a later writer cannot make the loss
    silent again. Changes no output.
    """
    seen: Dict[Tuple[str, int], int] = {}
    for ln in lines:
        m = _THERMAL_MAT_CARD_ID_RE.match(ln)
        if m:
            key = (m.group(1), int(m.group(2)))
            seen[key] = seen.get(key, 0) + 1
    for (kind, mid), n in sorted(seen.items()):
        if n > 1:
            state.warn(
                f"/{kind}/MAT/{mid} is emitted {n} times. Both cards are keyed "
                "on a MATERIAL id while *MAT_ADD_THERMAL_EXPANSION is keyed on "
                "a PART, so two cards naming parts that share one MID produce "
                "the duplicate. The starter does not refuse it - it reads the "
                "FIRST block and silently drops the rest - so the second card's "
                "coefficient or thermal properties are lost without a "
                "diagnostic of any kind.")


#: The three heat-source boundary cards, each with its OWN starter id
#: namespace (measured: ``/CONVEC/7`` + ``/RADIATION/7`` + ``/IMPFLUX/7`` +
#: ``/IMPTEMP/7`` in one deck give 0 ERROR / 0 WARNING).
_THERMAL_BC_CARD_ID_RE = re.compile(
    r"^/(IMPFLUX|CONVEC|RADIATION|IMPTEMP|INITEMP)/(\d+)\s*$")


def _warn_duplicate_thermal_bc_ids(state: ConversionState,
                                   lines: List[str]) -> None:
    """One id per card WITHIN each thermal-boundary namespace.

    The starter does NOT check this. ``hm_read_impflux.F``,
    ``hm_read_convec.F``, ``hm_read_radiation.F`` and ``hm_read_imptemp.F``
    none of them call ``UDOUBLE`` or touch ``NOM_OPT``, and it was MEASURED:
    two ``/CONVEC`` cards on one id are BOTH read and BOTH applied, at 0 ERROR
    and 0 WARNING — so the deck silently gets twice the convection it asks for.
    (The four namespaces are independent of each other, which the same probe
    round measured, so this scan keys on the card spelling as well.)

    Every one of these ids comes from the monotonic ``state.next_id()``, so a
    duplicate cannot arise from the writer today; this removes the CLASS, in
    the shape :func:`_warn_duplicate_thermal_ids` already established for the
    material-keyed thermal cards. Changes no output.
    """
    seen: Dict[Tuple[str, int], int] = {}
    for ln in lines:
        m = _THERMAL_BC_CARD_ID_RE.match(ln)
        if m:
            key = (m.group(1), int(m.group(2)))
            seen[key] = seen.get(key, 0) + 1
    for (kind, cid), n in sorted(seen.items()):
        if n > 1:
            state.warn(
                f"/{kind}/{cid} is emitted {n} times. The starter does NOT "
                "refuse it — none of hm_read_impflux.F, hm_read_convec.F, "
                "hm_read_radiation.F or hm_read_imptemp.F calls UDOUBLE — so "
                "BOTH cards are read and BOTH are applied (measured), and the "
                "deck silently gets twice the thermal load it states.")


def _warn_duplicate_preload_ids(state: ConversionState,
                                lines: List[str]) -> None:
    """``/PRELOAD`` and ``/PRELOAD/AXIAL`` share ONE starter id namespace.

    Both flavours are read from the same option loop: ``hm_read_preload.F:110``
    walks every ``/PRELOAD`` block and skips the axial ones with
    ``IF (KEY(1:LEN_TRIM(KEY))=='AXIAL') CYCLE``; ``hm_read_preload_axial.F90``
    does the mirror image. The solid path keeps the LS-DYNA ISSID verbatim
    while the 1D path mints ids, so a deck whose ``*INITIAL_STRESS_SECTION``
    ISSID lands on a minted one would put two bolt preloads under one number.

    Changes no output — the #125 rule: a per-id memo in the writer (there is
    one, shared across both emitters) PLUS a deck-wide scan of the finished
    deck, because no single writer sees the whole thing.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        if not ln.startswith("/PRELOAD/"):
            continue
        parts = ln.split("/")
        kind = "/PRELOAD/AXIAL" if parts[2] == "AXIAL" else "/PRELOAD"
        tok = parts[3] if parts[2] == "AXIAL" else parts[2]
        if tok.isdigit():
            seen.setdefault(int(tok), []).append(kind)
    for pid, kinds in sorted(seen.items()):
        if len(kinds) > 1:
            state.warn(
                f"BOLT PRELOAD ID {pid} is emitted by more than one card ("
                + ", ".join(f"{k}/{pid}" for k in kinds)
                + "). /PRELOAD and /PRELOAD/AXIAL are one keyword to the "
                "starter's option loop (hm_read_preload.F:110), so the second "
                "card is at best ignored and at worst ERROR 79. Renumber the "
                "*INITIAL_STRESS_SECTION ISSID.")


def _warn_duplicate_sect_ids(state: ConversionState,
                             lines: List[str]) -> None:
    """Two ``/SECT`` cards on one id.

    ``*DATABASE_CROSS_SECTION_*`` keeps its CSID verbatim while the bolt
    preload mints a DEDICATED section beside it, so the two producers share a
    namespace no single writer sees whole. ``hm_read_sect.F`` resolves a
    section by id, and ``/PRELOAD``'s sect_ID (hm_read_preload.F:267) would
    silently pick up whichever card the starter read first.

    Changes no output.
    """
    seen: Dict[int, int] = {}
    for ln in lines:
        if ln.startswith("/SECT/"):
            tok = ln.split("/")[2]
            if tok.isdigit():
                seen[int(tok)] = seen.get(int(tok), 0) + 1
    for sid, n in sorted(seen.items()):
        if n > 1:
            state.warn(
                f"SECTION ID {sid} is emitted by {n} /SECT cards. The starter "
                "resolves a section by id, so /TH/SECTIO and any /PRELOAD "
                "naming it pick up whichever card was read first. Renumber the "
                "*DATABASE_CROSS_SECTION id.")


#: ``/FUNCT/<id>``, ``/FUNCT_SMOOTH/<id>`` and ``/TABLE/<order>/<id>`` — the
#: three card kinds that share ONE starter id table.
_FUNCT_CARD_ID_RE = re.compile(r"^(/FUNCT(?:_SMOOTH)?)/(\d+)\s*$")
_TABLE_CARD_ID_RE = re.compile(r"^(/TABLE)/\d+/(\d+)\s*$")


def _warn_duplicate_function_ids(state: ConversionState,
                                 lines: List[str]) -> None:
    """``/FUNCT``, ``/FUNCT_SMOOTH`` and ``/TABLE`` are ONE id namespace.

    ``hm_read_funct.F`` reads ``/FUNCT`` (``HM_OPTION_COUNT`` :103) and
    ``/FUNCT_SMOOTH`` (:104) into the same ``NPC/PLD/NOM_OPT`` arrays under one
    running index, differing only by ``NPC(2*NFUNCT+L+1) = ISMOOTH``, and
    ``hm_read_table.F:88`` counts "total number /TABLE + /FUNCT" before its
    UDOUBLE duplicate pass. A shared id is
    ``ERROR ID : 79 ** ERROR: DUPLICATE ID / IN FUNCTION & TABLE DEFINITION``
    and no restart file — MEASURED on all three pairings (/FUNCT + /FUNCT_SMOOTH
    on 8002; /FUNCT_SMOOTH + /TABLE on 301, which additionally raised
    ERROR 604).

    ``state.next_curve_id`` keeps SYNTHESIZED ids out of every one of those
    registries, but nothing stops a deck from stating a ``*DEFINE_CURVE``, a
    ``*DEFINE_CURVE_SMOOTH`` and a ``*DEFINE_TABLE`` on the same number —
    LS-DYNA's curve and table id namespaces are separate. This is the scan that
    sees it: one pass over the assembled starter, the sibling of
    :func:`_warn_duplicate_prop_ids`. It changes no output.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _FUNCT_CARD_ID_RE.match(ln) or _TABLE_CARD_ID_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(m.group(1))
    for fid, kinds in sorted(seen.items()):
        if len(kinds) > 1:
            state.warn(
                f"CURVE ID {fid} is emitted by more than one card ("
                + ", ".join(f"{k}/{fid}" for k in kinds)
                + "). /FUNCT, /FUNCT_SMOOTH and /TABLE share ONE starter id "
                "namespace (hm_read_funct.F reads /FUNCT and /FUNCT_SMOOTH "
                "into the same arrays; hm_read_table.F:88 merges /TABLE into "
                "the duplicate scan), while LS-DYNA's *DEFINE_CURVE, "
                "*DEFINE_CURVE_SMOOTH and *DEFINE_TABLE ids are independent. "
                "The starter refuses the whole deck with ERROR 79 (DUPLICATE "
                "ID, IN FUNCTION & TABLE DEFINITION). Renumber one of them.")


#: ``/IMPDISP/<id>`` and ``/IMPDISP/FGEO/<id>`` — two card kinds, ONE starter
#: id table.
_IMPDISP_CARD_ID_RE = re.compile(r"^/IMPDISP(/FGEO)?/(\d+)\s*$")


def _warn_duplicate_impdisp_ids(state: ConversionState,
                                lines: List[str]) -> None:
    """``/IMPDISP`` and ``/IMPDISP/FGEO`` share ONE id namespace.

    ``hm_read_impvel.F:96-129`` counts ``/IMPDISP`` with ``HM_OPTION_COUNT`` and
    ``/IMPDISP/FGEO`` separately only to size the two readers
    (``NFDISP = NIMPDISP - FGEOD``) — the duplicate scan that follows,
    ``UDOUBLE(OPTID,1,NIMPDISP,...)`` over ``NOM_OPT(1,1:NIMPDISP)``, covers
    BOTH. ``/IMPVEL`` and ``/IMPACC`` get their own scans over their own slices,
    so they are deliberately not in this one.

    ``_make_impdisp_fgeo`` already screens a user ``BPFGID`` against the ids
    ``state.imp_card_ids["IMPDISP"]`` holds — which is what all THREE producers
    record into: ``loads._emit_imp_card``, ``loads._emit_rwall_geom_motion``
    and ``_make_impdisp_fgeo`` itself. The rigid-wall one runs AFTER the FGEO
    section, so it dodges from its own side (``state.next_impdisp_id``) instead
    of being screened here. This is the deck-wide backstop for any future
    producer that forgets to do either — the ``#125`` "per-id memo PLUS a
    deck-wide scan for every namespace" rule. It changes no output.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _IMPDISP_CARD_ID_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(
                "/IMPDISP/FGEO" if m.group(1) else "/IMPDISP")
    for did, kinds in sorted(seen.items()):
        if len(kinds) > 1:
            state.warn(
                f"IMPOSED-DISPLACEMENT ID {did} is emitted by more than one "
                "card (" + ", ".join(f"{k}/{did}" for k in kinds)
                + "). /IMPDISP and /IMPDISP/FGEO are ONE starter id namespace "
                "(hm_read_impvel.F:129 runs a single UDOUBLE over the merged "
                "NOM_OPT slice), so the starter refuses the deck with ERROR 79. "
                "This is a k2rad bug — please report the deck.")


#: ``/INTER/TYPEnn/<id>`` — every interface TYPE shares ONE starter id table.
#: ``/INTER/SUB`` is deliberately NOT matched: ``hm_read_interfaces.F:154``
#: runs ``IF(KEY == 'SUB') CYCLE`` **before** ``NI = NI + 1`` at ``:156``, so a
#: sub-interface never enters ``IPARI`` and never reaches the duplicate loop at
#: ``:229-234`` (``/INTER/GUIDED_CABLE`` is excluded the same way at ``:155``).
#: Matching it would flag a legal TYPE-vs-SUB id pairing as a k2rad bug.
_INTER_CARD_ID_RE = re.compile(r"^/INTER/(TYPE\d+)/(\d+)\s*$")


def _warn_duplicate_inter_ids(state: ConversionState,
                              lines: List[str]) -> None:
    """Interface ids are ONE namespace across every ``/INTER/TYPEnn``.

    ``hm_read_interfaces.F`` reads every ``/INTER/TYPEnn`` into the same
    ``IPARI``/``NOM_OPT`` slice and then scans it deck-wide (``:229-234``,
    ``DO K=1,NI-1 / IF (NOINT == IPARI(15,K)) / ANCMSG(MSGID=117)``, under the
    ``IF (IPARI(71,NI) <= 0)`` guard that exempts only the sub-interfaces a
    ``/INTER/TYPE19`` generates for itself):
    a repeated id is ``ERROR ID : 117 ** INTERFACE ID USED TWICE OR MORE`` and
    no restart file. ``_parse_contact_header``'s docstring has named that error
    since the per-block-length id fallback was removed; this is the deck-wide
    backstop for it — the #125 "per-id memo PLUS a deck-wide scan for every
    namespace" rule, applied to the one namespace that still had no scan.

    It matters now because a contact can produce more than one interface for
    the first time: a rupturing ``*CONTACT_..._TIEBREAK`` emits its
    ``/INTER/TYPE2`` under the deck's own id and a companion ``/INTER/TYPE25``
    under an allocated one. It changes no output.
    """
    seen: Dict[int, List[str]] = {}
    for ln in lines:
        m = _INTER_CARD_ID_RE.match(ln)
        if m:
            seen.setdefault(int(m.group(2)), []).append(m.group(1))
    for iid, kinds in sorted(seen.items()):
        if len(kinds) > 1:
            state.warn(
                f"INTERFACE ID {iid} is emitted by more than one card ("
                + ", ".join(f"/INTER/{k}/{iid}" for k in kinds)
                + "). Every /INTER/TYPEnn shares ONE starter id namespace "
                "(hm_read_interfaces.F reads them into one IPARI slice and "
                "scans it at :229-234), so the starter refuses the deck with "
                "ERROR 117 (INTERFACE ID USED TWICE OR MORE) and writes no "
                "restart file. This is a k2rad bug — please report the deck.")


def _warn_dangling_part_materials(state: ConversionState,
                                  lines: List[str]) -> None:
    """Name every ``/PART`` that points at a ``/MAT`` id the deck never writes.

    A ``/PART`` card is ``prop_ID mat_ID subset_ID`` and the starter resolves
    the material by id: a mat_ID that matches no ``/MAT`` is refused outright.
    Until this scan existed the converter could produce exactly that and say
    NOTHING — measured on ``airbag.deploy.k`` before the fabric batch:
    ``/PART/3`` ("Airbag - Fabric") pointed at mid 3 while a grep of the whole
    ``_0000.rad`` returned only ``/MAT/ELAST/1`` and ``/MAT/ELAST/2``, with no
    warning on any branch. Implementing *MAT_FABRIC removed that CAUSE; this
    scan removes the CLASS, the same way ``_warn_duplicate_prop_ids`` turned a
    silent ERROR 79 into a named one.

    One pass over the ASSEMBLED starter, so it sees what was really written
    rather than what each builder intended — a material container that a
    prepass warn-skipped, a *PART whose MID is a typo, and a family added
    later that forgets its emitter are all caught by the same three lines.

    ``mat_ID = 0`` is NOT a dangling reference: it is the connector convention
    (a spring / damper / spotweld part whose whole material lives inside its
    /PROP/TYPE4|8|13, ``mesh._target_mat_law`` returns None for those by
    design), and the starter accepts it.
    """
    mats = {int(m.group(1)) for m in
            (_MAT_CARD_ID_RE.match(ln) for ln in lines) if m}
    dangling: List[Tuple[int, int]] = []
    for k, ln in enumerate(lines):
        m = _PART_CARD_ID_RE.match(ln)
        if not m or k + 2 >= len(lines):
            continue
        row = lines[k + 2]                 # header, title, then the data card
        if row.startswith("#") or row.startswith("/"):
            continue
        try:
            mid = int(row[10:20] or 0)
        except ValueError:
            continue
        if mid and mid not in mats:
            dangling.append((int(m.group(1)), mid))
    if not dangling:
        return
    shown = ", ".join(f"/PART/{p} -> mat {m}" for p, m in dangling[:10])
    if len(dangling) > 10:
        shown += f", ... ({len(dangling)} parts)"
    # Name the culprit where the deck makes it nameable. MEASURED on the
    # 827-deck corpus: 280 decks carry this defect, and in almost all of them
    # the cause is one unconverted *MAT_ keyword sitting in the skip list —
    # so quoting it turns a "look above" into an answer.
    # A REFUSED material is uncoverted too, and it is the one this scan can
    # name best — but it is deliberately NOT in skipped_keywords (it has a
    # handler). Reading only that list would answer "no *MAT_ keyword is in
    # the skipped list ... look above" on exactly the decks whose culprit is
    # already known by name (#130: the premise of a true conclusion still has
    # to be true).
    skipped_mats = sorted({k for k in state.skipped_keywords
                           if k.startswith("MAT_")}
                          | {kw for kw, _what, _why
                             in state.refused_materials.values()})
    culprit = (" The deck's UNCONVERTED material keyword(s): "
               + ", ".join("*" + k for k in skipped_mats[:6])
               + ("." if len(skipped_mats) <= 6 else
                  f", ... ({len(skipped_mats)} in all).")
               ) if skipped_mats else (
        " No *MAT_ keyword is in the skipped list, so the material was "
        "recognised and then dropped — look above for a warning naming its "
        "family, or check that the *PART's MID is not simply a typo.")
    state.warn(
        f"{len(dangling)} /PART card(s) reference a material id that NO /MAT "
        f"card in the emitted deck defines: {shown}. The starter resolves a "
        "part's material by id and refuses the deck when it cannot."
        + culprit)


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
        # /SPHGLO is a global analysis card like /AMS, and only the FIRST one
        # in the deck is read — so it sits with the other globals, above the
        # entity sections. No-op (and draws no id) on any deck without SPH.
        ("sphglo",            lambda c: _make_sphglo(c.state)),
        ("materials",         lambda c: _make_materials(c.state)),
        # Composite / orthotropic laws live in their own module (they carry a
        # per-part property split that the plain material path does not), so
        # they are their own section right after the materials block.
        ("composite_materials", lambda c: _make_composite_materials(c.state)),
        # Airbag fabric laws (/MAT/LAW19, /MAT/LAW58) — their own section for
        # the same reason the composite laws have one: the law and its property
        # are one decision (writer/fabric.py). A no-op on any deck without
        # *MAT_FABRIC, and it draws no id, so it cannot shift an existing
        # deck's id stream.
        ("fabric_materials",  lambda c: _make_fabric_materials(c.state)),
        # 2D (shell) seatbelt laws (/MAT/LAW119) - their own section for the
        # same reason the fabric laws have one: the law and its property are
        # one decision (writer/seatbelts.py). The 1D belt's /MAT/LAW114 is NOT
        # here: it is written beside its /PROP/TYPE23 and its /PART in the
        # seatbelts section far below, because a /PART on a TYPE23 must name a
        # material whose law is 108/113/114/135 (ERROR 179/1715) and the three
        # cards are one unit. A no-op, drawing no id, on any deck without a
        # *MAT_SEATBELT on a *SECTION_SHELL.
        ("seatbelt_2d_materials",
                              lambda c: _make_seatbelt_2d_materials(c.state)),
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
        ("composite_properties", lambda c: _emit_composite_props(c.state)),
        ("fabric_properties",    lambda c: _emit_fabric_props(c.state)),
        ("seatbelt_2d_properties",
                                 lambda c: _emit_seatbelt_2d_props(c.state)),
        ("functions",         lambda c: _make_functions(c.state)),
        ("extra_groups",      lambda c: _make_extra_groups(c.state)),
        ("rlinks",            lambda c: _make_rlinks(c.state)),
        # /FRICTION before the interfaces that reference it by fric_ID. The
        # starter resolves entities by id, not by order, so this is only for
        # readability — but it also keeps the friction tables' (preserved,
        # LS-DYNA-side) ids away from the state.next_id() stream the surfaces
        # below draw from.
        ("frictions",         lambda c: _make_frictions(c.state)),
        ("interfaces",        lambda c: _make_interfaces(c.state, c.rigid_nodes)),
        ("general_interfaces", lambda c: _make_general_interfaces(c.state, c.rigid_nodes)),
        ("type25_interfaces", lambda c: _make_type25_interfaces(c.state, c.rigid_nodes)),
        ("tied_interfaces",   lambda c: _make_tied_interfaces(c.state, c.rigid_nodes)),
        ("tiebreak_interfaces",
                              lambda c: _make_tiebreak_interfaces(c.state, c.rigid_nodes)),
        ("spotweld_interfaces",
                              lambda c: _make_spotweld_interfaces(c.state, c.rigid_nodes)),
        ("force_transducers", lambda c: _make_force_transducers(c.state, c.rigid_nodes)),
        ("rbodies",           lambda c: c.rbody_lines),
        # /RBE3 after the rigid bodies: its guards need the /RBODY main-node and
        # secondary-node sets to report the RBODY > RBE3 hierarchy conflicts
        # (starter ERROR 810 / WARNING 3104), and its dependent node has to be in
        # state.rbe3_nodes before the implicit free-node guard runs.
        ("rbe3",              lambda c: _make_rbe3(c.state, c.rbody_info,
                                                   c.rigid_nodes)),
        ("imposed_motions",   lambda c: _make_imposed_motions(c.state, c.rbody_info)),
        ("imposed_motions_set", lambda c: _make_imposed_motions_set(c.state)),
        # *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY -> /IMPDISP/FGEO, beside the two
        # sections it is a sibling of: read_impdisp_fgeo.F is reached from the
        # same hm_read_impvel.F option loop as the plain /IMPDISP, and the two
        # share the IBFVEL/FBFVEL arrays. A no-op — and it draws no id — on any
        # deck without the keyword, so it cannot shift an existing deck's id
        # stream (the #119 fixture rule).
        ("impdisp_fgeo",      lambda c: _make_impdisp_fgeo(c.state)),
        ("inivel",            lambda c: _make_inivel(c.state, c.rbody_info)),
        ("initial_velocity",  lambda c: _make_initial_velocity(c.state)),
        ("initial_velocity_generation",
                              lambda c: _make_initial_velocity_generation(c.state)),
        ("pressure_loads",    lambda c: _make_pressure_loads(c.state)),
        # Both gravity paths need rbody_info: a /GRAV whose group holds only
        # rigid secondary nodes moves nothing (the engine overwrites their
        # acceleration from the main node), so the /RBODY main nodes have to be
        # in the group. See _rbody_mains_in_scope.
        ("gravity_loads",     lambda c: _make_gravity_loads(c.state,
                                                            c.rbody_info)),
        ("body_loads",        lambda c: _make_body_loads(c.state,
                                                         c.rbody_info)),
        ("blast_loads",       lambda c: _make_blast_loads(c.state)),
        ("detonations",       lambda c: _make_detonations(c.state)),
        ("fsi_coupling",      lambda c: _make_fsi_coupling(c.state)),
        ("ebcs",              lambda c: _make_ebcs(c.state)),
        # Monitored volumes. AFTER parts_elements, whose write line fills
        # state.shell_elem_ids / sh3n_elem_ids — the /SURF is screened against
        # those so it can never name an element the deck does not define
        # (starter ERROR 70). BEFORE the /TH block far below, which lists
        # state.monvol_ids. A no-op (and draws no id) on any deck without an
        # *AIRBAG_*, so it cannot shift an existing deck's id stream.
        ("monvols",           lambda c: _make_monvols(c.state)),
        ("inivol_notes",      lambda c: _make_inivol_notes(c.state)),
        ("control_ale_notes", lambda c: _make_control_ale_notes(c.state)),
        ("starter_cloads",    lambda c: _make_starter_cloads(c.state)),
        ("node_cloads",       lambda c: _make_node_cloads(c.state)),
        ("rigid_walls",       lambda c: _make_rigid_walls(c.state)),
        ("modal_dummy_cload", lambda c: _make_modal_dummy_cload(c.state, c.rigid_nodes)),
        ("discrete_springs",  lambda c: _make_discrete_springs(c.state)),
        # *MAT_MUSCLE truss parts and *MAT_SPRING_MUSCLE discrete parts:
        # /PART + /PROP/TYPE46 (SPR_MUSCLE) + /SPRING, plus the synthesized
        # /FUNCTs the four function slots need (written INLINE here, because
        # the single /FUNCT emitter runs at the "functions" step far above).
        ("muscle_springs",    lambda c: _make_muscle_springs(c.state)),
        # /HEAT/MAT + /THERM_STRESS/MAT (both keyed on the MATERIAL id) and the
        # /INITEMP / /IMPTEMP drivers with their /GRNODs. After the materials
        # they attach to and after the connector sections, whose /GRNOD ids come
        # from the same auto-id stream.
        ("thermal",           lambda c: _make_thermal(c.state)),
        ("plotel_elements",   lambda c: _make_plotel_elements(c.state)),
        ("spotweld_beams",    lambda c: _make_spotweld_beam_connectors(c.state)),
        # ELFORM=6 discrete beams: their /PART + spring property come from here,
        # not from _make_properties (an ELFORM=6 *SECTION_BEAM states no
        # cross-section, so a /PROP/BEAM from it is starter ERROR 314-317).
        ("discrete_beams",    lambda c: _make_discrete_beam_connectors(c.state)),
        ("spotweld_ties",     lambda c: _make_constrained_spotweld_springs(c.state)),
        # Seatbelts: the 1D belt /PART + /PROP/TYPE23 + /MAT/LAW114 + /SPRING,
        # then the sensors, the accelerometers, the sliprings and the
        # retractors. AFTER parts_elements, whose write line fills
        # state.shell_elem_ids (the 2D-belt screen reads it) and BEFORE the /TH
        # block far below, which lists state.slipring_ids, state.retractor_ids
        # and state.th_accel_ids - all three filled AT the line that writes
        # each card, the same ordering constraint the /CLUSTER + swforc and
        # discrete-connector pairs rely on. It also fills spring_elem_ids
        # (producer 8), which starter_th screens *DATABASE_HISTORY_SEATBELT
        # against. A no-op, drawing no id, on any deck without a seatbelt.
        ("seatbelts",         lambda c: _make_seatbelts(c.state)),
        # The clusters must precede starter_th_swforc: the SWFORC block
        # reports "no weld to output" only when no cluster was emitted
        # either, and it reads state.cluster_ids to know.
        ("spotweld_clusters", lambda c: _make_hex_spotweld_clusters(c.state)),
        ("joints",            lambda c: _make_joints(c.state, c.rigid_nodes,
                                                     set(c.rbody_info))),
        ("grounding_springs", lambda c: _make_grounding_springs(c.state, c.rbody_info)),
        ("added_masses",      lambda c: _make_added_masses(c.state, c.rigid_nodes)),
        ("xref",              lambda c: _make_xref(c.state)),
        # /EREF is the per-ELEMENT twin of /XREF. AFTER it, because the
        # two are mutually exclusive per node (starter ERROR 1098) and
        # the /EREF resolver drops the rows of any part the /XREF
        # already covers. AFTER parts_elements too, which is why the
        # resolve runs inside the emitter rather than in the prepass
        # block: the element screen reads the write-line registries.
        ("eref",              lambda c: _make_eref(c.state)),
        ("initial_stresses",  lambda c: _make_initial_stresses(c.state)),
        ("cross_sections",    lambda c: _make_cross_sections(c.state)),
        # Bolt pre-tension. AFTER cross_sections, which fills state.sect_ids
        # (the dedicated preload /SECT must dodge those ids) and after every
        # /BEAM and /SPRING producer above, whose write lines fill
        # state.beam_elem_ids / spring_elem_ids (the *SET_BEAM of
        # *INITIAL_AXIAL_FORCE_BEAM is split by what was ACTUALLY emitted).
        # BEFORE free_node_constraints, so the three synthesized /SECT frame
        # nodes are in state.nodes when the implicit singularity guard runs —
        # they carry no element and no stiffness, so a /BCS 111 111 on them is
        # correct and inert (the starter reads the frame once, at
        # hm_read_preload.F:203-217, and never again). A no-op drawing no id on
        # any deck without the two keywords, so it cannot shift an existing
        # deck's id stream.
        ("preload",           lambda c: _make_preload(c.state)),
        # *DEFINE_ELEMENT_DEATH_* -> /ACTIV. AFTER parts_elements far above,
        # which fills state.shell_elem_ids / sh3n_elem_ids / solid_elem_ids /
        # beam_elem_ids and the three BEAM->/SPRING re-route registries at the
        # line that writes each element row — the same "registry filled at the
        # write line, consumed by a later section" ordering the /CLUSTER +
        # swforc pair relies on. A no-op drawing no id on any deck without the
        # keyword.
        ("element_death",     lambda c: _make_element_death(c.state)),
        # *PERTURBATION_NODE -> /RANDOM[/GRNOD]. AFTER extra_groups, which is
        # where a user *SET_NODE that no other card consumed is re-emitted as
        # /GRNOD/NODE/<nsid> — the group this card references by id. A no-op
        # drawing no id on any deck without the keyword.
        ("random_noise",      lambda c: _make_random(c.state)),
        ("eig",               lambda c: _make_eig(c.state)),
        ("free_node_constraints", lambda c: _make_free_node_constraints(c.state, c.rigid_nodes)),
        ("damping",           lambda c: _make_damping(c.state, c.rigid_nodes,
                                                      c.rbody_info)),
        # The damping family, continued. Each of these three is a no-op (and
        # draws no ids) on a deck without its keyword, so they cannot shift the
        # id stream of an existing deck. *DAMPING_RELATIVE resolves and warns
        # without emitting — see _resolve_damping_relative for the measured
        # version gate that makes that the honest answer.
        ("damping_part_mass", lambda c: _make_damping_part_mass(c.state,
                                                                c.rigid_nodes)),
        ("damping_freq_range", lambda c: _make_damping_frequency_range(c.state)),
        ("damping_relative",  lambda c: _resolve_damping_relative(c.state,
                                                                  c.rbody_info)),
        ("starter_th",        lambda c: _make_starter_th(c.state)),
        ("starter_th_inter",  lambda c: _make_starter_th_inter(c.state)),
        ("starter_th_node_reac", lambda c: _make_starter_th_node_reac(c.state, c.rbody_info)),
        ("starter_th_node_spc",  lambda c: _make_starter_th_node_spc(c.state, c.rbody_info)),
        ("starter_th_surf",   lambda c: _make_starter_th_surf(c.state)),
        ("starter_th_sectio", lambda c: _make_starter_th_sectio(c.state)),
        ("starter_th_swforc", lambda c: _make_starter_th_swforc(c.state)),
        # After discrete_springs and discrete_beams above: this block lists the
        # sprg_IDs those two writers ACTUALLY emitted (state.discrete_spring_-
        # eids / dbeam_spring_eids), so it must not run before they are filled
        # or the group would come out empty. Same ordering constraint the
        # /CLUSTER + swforc pair records.
        ("starter_th_discrete_connectors", lambda c: _make_starter_th_discrete_connectors(c.state)),
        # The output-parity batch. Each of the three is a no-op — and draws no
        # id — on a deck without its keyword, so none can shift the id stream
        # of an existing deck (the #119 fixture rule).
        #   * nodal_force_group expands *SET_NODE and needs nothing else;
        #   * rbody reads state.rbody_ids, which the three /RBODY producers
        #     fill in build_starter BEFORE the registry is walked at all;
        #   * bndout reads state.imp_motion_nodes, filled by the two
        #     imposed_motions sections far above — the same "registry filled at
        #     the write line, consumed by a later section" ordering the
        #     /CLUSTER + swforc and discrete-connector pairs rely on.
        ("starter_th_nodal_force_group",
                              lambda c: _make_starter_th_nodal_force_group(c.state)),
        ("starter_th_rbody",  lambda c: _make_starter_th_rbody(c.state)),
        ("starter_th_bndout", lambda c: _make_starter_th_bndout(c.state)),
        # *DATABASE_ABSTAT -> /TH/MONV. AFTER the monvols section far
        # above, which fills state.monvol_ids at the line that writes
        # each /MONVOL card — the same "registry filled at the write
        # line, consumed by a later section" ordering the /CLUSTER +
        # swforc and discrete-connector pairs rely on. A no-op, drawing
        # no id, on any deck without a converted monitored volume.
        ("starter_th_monv", lambda c: _make_starter_th_monv(c.state)),
        # *DATABASE_SBTOUT -> /TH/SLIPRING + /TH/RETRACTOR, and the
        # accelerometer group. AFTER the seatbelts section far above, which
        # fills state.slipring_ids / retractor_ids / th_accel_ids at the line
        # that writes each card — the same "registry filled at the write line,
        # consumed by a later section" ordering the /CLUSTER + swforc,
        # discrete-connector and /TH/MONV pairs rely on. Both are no-ops,
        # drawing no id, on any deck without a converted seatbelt device.
        ("starter_th_seatbelt",
                              lambda c: _make_starter_th_seatbelt(c.state)),
        ("starter_th_accel", lambda c: _make_starter_th_accel(c.state)),
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


def _make_engine_timestep_scale(state: ConversionState, ts) -> List[str]:
    """*CONTROL_TIMESTEP with DT2MS >= 0 (no mass scaling): TSSFAC is still a
    real instruction and must not be dropped.

    TSSFAC is LS-DYNA's scale factor on the computed critical time step
    (dt = TSSFAC * dt_critical). OpenRadioss spells exactly the same quantity
    Tsca on the plain /DT engine card, so the mapping is one-to-one:

        /DT
        Tsca  Tmin

    Tmin is emitted as 0.0 = no lower bound. Tmin on /DT is a run-STOP
    threshold, and LS-DYNA's equivalent (TSLIMT) is a different field that this
    handler does not parse; inventing one would stop runs the user never asked
    to stop. Tsca is the only thing being carried across.

    Only emitted when TSSFAC > 0. TSSFAC = 0 is LS-DYNA's "use my default"
    (0.9), which is also OpenRadioss's /DT default, so there is nothing to
    carry and the deck is left exactly as it converted before.
    """
    tsca = ts.tssfac
    if not tsca or tsca <= 0.0:
        return []
    state.warn(
        f"*CONTROL_TIMESTEP TSSFAC={tsca:g} (DT2MS={ts.dt2ms:g}, no mass "
        f"scaling) -> /DT Tsca={tsca:g}. The time-step safety factor is "
        "carried over; Tmin=0 (no lower bound) because LS-DYNA TSLIMT is not "
        "converted, so the engine will not stop or delete on a small step."
    )
    return [
        "/DT",
        f"{_f(tsca)}{_f(0.0)}",
        "#",
    ]


# /DT/<elem>/DEL blocks k2rad can emit, in the order they are written. SH_3N is
# a separate family from SHELL in Radioss, so a deck whose ESORT generates
# triangles needs both or the triangles have no floor at all.
_DT_DEL_KINDS = ("SHELL", "SH_3N", "BRICK")


def _make_engine_dt_deletion(state: ConversionState) -> List[str]:
    """``/DT/<elem>/DEL`` — delete an element whose time step reaches Tmin.

    **This card deletes elements, so k2rad never emits it uninvited.** Two
    routes in, both explicit:

    * the DECK asks: ``*CONTROL_TIMESTEP`` ``ERODE=1`` with ``TSLIMT>0``.
      ERODE is precisely LS-DYNA's "delete elements that fall below the floor",
      so carrying it across is faithful rather than inventive. Both fields used
      to be sliced off the card and dropped silently;
    * the USER asks: ``--dt-del <seconds>`` (``convert(dt_del=...)``) — the
      escape hatch for a long run where one degrading element drags the global
      step toward zero and the job never finishes. It has no LS-DYNA
      counterpart, so it is opt-in and never derived automatically.

    ORDERING AGAINST MASS SCALING, which issue #78 flagged as the crux and
    feared would leave one of the two cards as dead configuration. Verified in
    ``engine/source/elements/shell/coque/cdt3.F`` (OpenRadioss 2026-05-20):

    * the element step is ``DT = DTFAC1(3)*ALDT/SSP`` (``cdt3.F:111-115``) —
      characteristic length over sound speed, **no mass term** — so nodal mass
      scaling cannot lift an element back off the deletion threshold;
    * the ``IDTMIN(3)==2`` deletion block (``cdt3.F:146``) executes **before**
      the ``IF (NODADT/=0...) RETURN`` at ``cdt3.F:200``.

    So ``/DT/NODA/CST`` and ``/DT/<elem>/DEL`` do NOT fight, and the deletion
    floor stays reachable with nodal scaling active. They are still not fully
    independent, and this is the case the earlier analysis missed: under
    **AMS** (``IDTMINS==2``) the step comes from ``SQRT(MAS/STI)`` instead
    (``cdt3.F:105-109``), which IS mass-based, and ``cdt3.F:200`` also returns
    early for AMS. A deletion floor under ``--ams`` is therefore warned about
    rather than assumed to work.

    Tmin here is a DELETION threshold, not a mass-scaling target, and the two
    want very different values. A floor at ~0.9x the initial step deletes
    elements that have merely stretched ~10%, which shreds a crushable
    structure; deletion belongs at near-total collapse of an element's
    characteristic length (~0.4-0.5x the initial step). k2rad does not invent
    the value — it carries TSLIMT, or the number the user passed.
    """
    ts = state.ctrl_timestep
    if state.is_implicit or state.is_modal:
        return []
    explicit = state.options.dt_del
    tmin = None
    source = ""
    if explicit is not None and explicit > 0.0:
        tmin = float(explicit)
        source = f"--dt-del {tmin:g}"
    elif ts is not None and int(ts.erode) == 1 and ts.tslimt > 0.0:
        tmin = float(ts.tslimt)
        source = f"*CONTROL_TIMESTEP ERODE=1 TSLIMT={ts.tslimt:g}"

    if tmin is None:
        # Nothing to emit — but SAY so when the deck asked for something and
        # only half of it is usable, instead of dropping it on the floor.
        if ts is not None and (int(ts.erode) == 1 or ts.tslimt > 0.0):
            state.note_recognized_not_emitted(
                "CONTROL_TIMESTEP",
                f"ERODE={int(ts.erode)} / TSLIMT={ts.tslimt:g} asks for element "
                "deletion below a time-step floor, but a floor needs BOTH "
                "ERODE=1 and TSLIMT>0, so no /DT/<elem>/DEL was emitted. Set "
                "both, or pass --dt-del <seconds> to choose the floor "
                "explicitly.")
        return []

    tsca = ts.tssfac if (ts and ts.tssfac and ts.tssfac > 0.0) else 0.9
    warn = (f"{source} -> /DT/{{SHELL,SH_3N,BRICK}}/DEL (Tsca={tsca:g}, "
            f"Tmin={tmin:g}): OpenRadioss will DELETE any element whose time "
            "step reaches Tmin, and prints each deletion to the .out and "
            "stdout. This removes mass and stiffness the LS-DYNA original may "
            "have kept — check the deletion count before trusting the result.")
    if ts is not None and ts.dt2ms < 0.0:
        if state.options.ams:
            warn += (
                " NOTE --ams: under AMS the element step is computed from "
                "SQRT(mass/stiffness) (cdt3.F:105-109), not length/sound "
                "speed, and cdt3.F:200 returns early for AMS — so this floor "
                "may behave differently from the non-AMS case, or not fire at "
                "all. Verify against the deletion messages.")
        else:
            warn += (
                f" It coexists with /DT/NODA/CST (Tmin={abs(ts.dt2ms):g}): the "
                "deletion test runs on the element's own GEOMETRIC step "
                "(length/sound speed, no mass term) and executes BEFORE the "
                "NODADT early return (cdt3.F:146 vs :200), so nodal mass "
                "scaling does NOT make this floor unreachable.")
    state.warn(warn)

    out: List[str] = []
    for kind in _DT_DEL_KINDS:
        out += [f"/DT/{kind}/DEL", f"{_f(tsca)}{_f(tmin)}", "#"]
    return out


def _make_engine_timestep(state: ConversionState) -> List[str]:
    """*CONTROL_TIMESTEP DT2MS<0 → /DT/NODA/CST (nodal-mass scaling that holds
    the explicit time step at the target |DT2MS|). Without this OpenRadioss runs
    at the raw smallest-element step — on a fine/TET mesh that can be ~100x below
    the intended DT2MS, so the run is ~100x slower. Explicit runs only (implicit
    and modal have no CFL time step to scale).

    DT2MS >= 0 means no mass scaling, but TSSFAC still applies and is handled by
    _make_engine_timestep_scale below — it used to be dropped on the floor."""
    ts = state.ctrl_timestep
    if ts is None or state.is_implicit or state.is_modal:
        return []
    if ts.dt2ms >= 0.0:
        return _make_engine_timestep_scale(state, ts)
    tmin = abs(ts.dt2ms)
    if _ams_is_emitted(state):
        # Advanced Mass Scaling (opt-in). 0.67 is the OpenRadioss-recommended AMS
        # scale factor — the PCG needs more margin than /DT/NODA/CST's 0.9. The
        # paired starter /AMS card is emitted by _make_ams, and the /DT/THERM
        # refusal screens on the SAME predicate — see _ams_is_emitted.
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


def _warn_dt_therm_window(state: ConversionState) -> None:
    """Is ``*CONTROL_TERMINATION`` ENDTIM long enough for ONE thermal step?

    MEASURED on a converter-emitted coupon (a 1 mm brick, ``RHO0_CP = 3.611``,
    ``AS = 45``, six convecting faces, ENDTIM = 1e-3 s): the run printed
    ``FINITE ELEMENT THERMAL ANALYSIS`` / ``THERMAL ANALYSIS ONLY`` / ``THERMAL
    TIME STEP SCALE FACTOR 0.9``, wrote ONE cycle line — ``CYCLE 0, TIME 0.000,
    TIME-STEP 0.1000E-02`` — and stopped with ``HEAT STORED = 0.0000000`` at
    **0 ERROR, 0 WARNING, NORMAL TERMINATION**. The mechanism is
    ``resol.F:5870-5880``: under ``IDT_THERM`` the step is
    ``MIN(dt_therm, TSTOP - TT)``, so a run shorter than one thermal step is
    clamped to the whole remaining time, the cycle-0 line is printed with
    ``DT1 = 0`` (no heat is deposited on the first cycle), and ``resol.F:9120``
    stops the run at TSTOP.

    This is easy to hit precisely because the LS-DYNA deck's ENDTIM was written
    for a MECHANICAL time scale while ``/DT/THERM`` runs on the conduction one,
    which is many orders of magnitude larger.
    """
    from .thermal import _thermal_step_estimate
    ct = state.ctrl_termination
    endtim = ct.endtim if ct is not None else 0.0
    dt_th = _thermal_step_estimate(state)
    if dt_th is None:
        state.warn(
            "/DT/THERM paces the run by the conduction stability step, but no "
            "emitted /HEAT/MAT states a conductivity (every AS/BS is 0), so "
            "that step is unbounded: mqviscb.F:666 divides by max(k, 1e-20). "
            "The run will be paced by TSTOP alone. Give the parts a "
            "*MAT_THERMAL_* through *PART TMID.")
        return
    if endtim <= 0.0:
        state.warn(
            f"/DT/THERM: the estimated thermal time step is {dt_th:.6g} "
            "(0.9*0.5*Lc^2*RHO0_CP/k from the emitted /HEAT/MAT and the "
            "model's shortest node-pair distance), but the deck states no usable "
            "*CONTROL_TERMINATION ENDTIM. A thermal-only run whose TSTOP is "
            "not larger than one thermal step does exactly ONE cycle at "
            "DT1 = 0 and stores ZERO heat, under NORMAL TERMINATION "
            "(measured).")
        return
    if endtim <= dt_th:
        state.warn(
            f"/DT/THERM: *CONTROL_TERMINATION ENDTIM = {endtim:g} is NOT "
            f"larger than one thermal time step ({dt_th:.6g}, estimated as "
            "0.9*0.5*Lc^2*RHO0_CP/k from the emitted /HEAT/MAT and the model's "
            "shortest node-pair distance). MEASURED on exactly this shape: the run "
            "does ONE cycle at TIME 0.000 with the step clamped to the whole "
            "remaining time (resol.F:5870-5880 takes MIN(dt_therm, "
            "TSTOP - TT)), deposits NOTHING because DT1 is 0 on the first "
            "cycle, and reports HEAT STORED = 0.0000000 at 0 ERROR / "
            "0 WARNING / NORMAL TERMINATION. The LS-DYNA ENDTIM was written "
            "for the MECHANICAL time scale; a thermal-only Radioss run needs a "
            f"TSTOP on the CONDUCTION one — of order {dt_th:.6g} per step. "
            "Raise ENDTIM (or *CONTROL_TERMINATION) before running.")
        return
    state.warn(
        f"/DT/THERM: ENDTIM = {endtim:g} against an estimated thermal step of "
        f"{dt_th:.6g} is about {endtim / dt_th:.0f} thermal cycle(s) "
        "(0.9*0.5*Lc^2*RHO0_CP/k from the emitted /HEAT/MAT and the model's "
        "shortest node-pair distance — a conservative proxy for the engine's "
        "own DELTAX). Check the .out's '** THERMAL ANALYSIS **' block: a run "
        "shorter than one thermal step stores ZERO heat under NORMAL "
        "TERMINATION.")
    _warn_dt_therm_surface_rate(state, dt_th)


def _warn_dt_therm_surface_rate(state: ConversionState, dt_th: float) -> None:
    """Is the thermal step small enough for the deck's own SURFACE loads?

    ``/DT/THERM``'s step is a CONDUCTION stability limit and nothing else — no
    convective or radiative term appears in ``dttherm.F90`` or ``mqviscb.F``.
    So a deck whose surface exchange is faster than its conduction runs
    UNSTABLE at the engine's own chosen step.

    The screen compares ``dt_therm`` with ``tau_surf = RHO0_CP * Lc / h``, the
    time for the surface load to change a layer one element thick — the right
    physical scale, computed from quantities that are exact here (the
    ``/HEAT/MAT``'s ``RHO0_CP``, the emitted ``H``, and the model's shortest
    element edge). Radiation is linearised as ``h_rad = 4*E*sigma*T0^3``, its
    standard small-signal equivalent.

    ``tau_surf`` alone is the time constant of a node fed by ONE loaded face
    per element. A body only a few elements thick, loaded on several sides at
    once, runs faster than that by ``r = max(loaded segments per node /
    elements per node)`` — see ``_surface_load_concentration``, which counts
    both from the emitted deck. The trip point and the prescribed factor are
    both divided by ``r``, so an ordinary thick mesh (``r = 1``) keeps exactly
    the arithmetic this guard shipped with, and a one-element-thick body
    (``r = 3``) gets a step that actually approaches its environment
    monotonically instead of overshooting it.

    MEASURED, three runs of the six-face 1 mm coupon (RHO0_CP 3.611, AS 45,
    h = 100, T_inf = 1000, T0 = 300, ENDTIM 0.2, all NORMAL TERMINATION at
    0 ERROR / 0 WARNING), reading the ``/TH/NODE`` TEMP channel and not only
    the heat balance:

    ===============  =======  ===========================  ============
    /DT/THERM        cycles   nodal temperature            HEAT STORED
    ===============  =======  ===========================  ============
    default 0.9      6        diverges                     7 901 590.2
    0.225 (r=1)      23       300 -> **1350.0** -> 825 ...  2527.6994
    0.075 (r=3)      67       300 -> 650 -> 825 -> 912.5    2527.7000
    ===============  =======  ===========================  ============

    The middle row is the point: it is stable, it saturates at the right total
    heat to seven figures, and its first step is 350 K PAST the environment
    temperature. The predicted step change is ``2·r·dt/tau·(T_inf - T)`` —
    ``1.5 × 700 = 1050`` at 0.225 and ``0.5 × 700 = 350`` at 0.075 — and the
    engine reproduced both exactly.

    MEASURED on a converter-emitted coupon: a 1 mm brick, ``RHO0_CP = 3.611``,
    ``AS = 45``, ``h = 100`` on all six faces, ENDTIM = 0.2 s. The engine chose
    ``dt = 0.3611E-01`` (matching this module's estimate to four figures),
    ``tau_surf = 3.611*1/100 = 0.03611`` — equal, i.e. right at the screen —
    and the run DIVERGED to ``HEAT STORED = 7 901 590.2`` mJ where the physical
    saturation is 2527.7 mJ (a factor 3126, about 2.2e6 K), at **0 ERROR,
    0 WARNING, NORMAL TERMINATION** over 6 cycles.
    """
    from .thermal import (_min_element_edge, _sigma_deck,
                          _surface_load_concentration)
    if not state.thermal_boundaries:
        return
    lc = _min_element_edge(state)
    rho_cps = [c[1] for c in state.heat_mat_cards.values() if c[1] > 0.0]
    if lc <= 0.0 or not rho_cps:
        return
    t0 = max((c[0] for c in state.heat_mat_cards.values()), default=0.0) or 300.0
    sigma = _sigma_deck(state) or 0.0
    h_max = 0.0
    for bc in state.thermal_boundaries:
        if not bc.surf_id:
            continue
        if bc.kind == "CONVEC":
            h_max = max(h_max, abs(bc.coef))
        elif bc.kind == "RADIATION" and sigma:
            h_max = max(h_max, 4.0 * abs(bc.coef) * sigma * t0 ** 3)
    if h_max <= 0.0:
        return
    tau_surf = min(rho_cps) * lc / h_max
    conc = _surface_load_concentration(state)
    tau_node = tau_surf / conc
    if dt_th < 0.5 * tau_node:
        return
    factor = 0.9 * 0.25 * tau_node / dt_th
    state.warn(
        f"/DT/THERM is UNSAFE on this deck: the thermal step it will choose is "
        f"about {dt_th:.6g}, while the deck's own surface exchange acts on a "
        f"time scale of tau = RHO0_CP*Lc/h = {tau_surf:.6g} (h = {h_max:.6g}, "
        f"the largest emitted /CONVEC H or linearised 4*E*sigma*T0^3)"
        + ("" if conc <= 1.0 else
           f", and the most heavily loaded node carries {conc:g} loaded "
           f"face(s) per element that feeds it, so ITS time constant is "
           f"tau/{conc:g} = {tau_node:.6g}")
        + ". Radioss picks its thermal step from CONDUCTION ALONE — there is "
        "no convective or radiative term anywhere in dttherm.F90 or "
        "mqviscb.F:644-670 — so a surface load faster than the conduction "
        "limit is integrated UNSTABLY. MEASURED on exactly this shape (a 1 mm "
        "brick, RHO0_CP 3.611, AS 45, h 100 on six faces): the engine chose "
        "dt = 0.03611, tau = 0.03611, and the run diverged to HEAT STORED = "
        "7 901 590 mJ where the physical saturation is 2527.7 mJ — a factor "
        "3126, about 2.2e6 K — at 0 ERROR / 0 WARNING / NORMAL TERMINATION "
        "over 6 cycles. Write the scale factor explicitly on the /DT/THERM "
        f"line (a POSITIVE number; about {factor:.3g} puts the step at a "
        "quarter of that node's own time constant, which is a monotone "
        "approach to the environment temperature). Then check the "
        "TEMPERATURE HISTORY, not only the heat balance: a step that "
        "OSCILLATES about the environment temperature still saturates at the "
        "right total heat, so '** THERMAL ANALYSIS **' can read exactly "
        "correct while the transient overshot. MEASURED on the six-face "
        "coupon: at 0.225 (0.25*tau, ignoring the concentration) the FIRST "
        "step went 300 -> 1350.000 K against a 1000 K environment and rang "
        "down 825 / 1087.5 / 956.25 / 1021.9 ... , while HEAT STORED came out "
        "2527.6994 against an analytic 2527.7000; at 0.075 the same deck "
        "climbs 650 / 825 / 912.5 / 956.25 ... to exactly 1000.0000 and "
        "stores 2527.7000. No node should pass the environment temperature.")


def _make_engine_thermal(state: ConversionState) -> List[str]:
    """The two ENGINE thermal keywords: ``/DT/THERM`` and ``/THERM``.

    **There is no ``/DTTHERM``.** ``dttherm.F90`` is a SUBROUTINE; the engine's
    keyword table (``freform.F:213-232``) has exactly two thermal entries —
    ``'DT '`` slot 3 (whose ``KEY2 == 'THERM'`` arm is ``freform.F:950-960``)
    and ``'THERM'`` slot 82 (``frethermal.F:64-70``) — plus ``/DEL/THERM``,
    which only switches the thermal output off. The registry's old ``/DTTHERM``
    target named a card that does not exist.

    ``/DT/THERM [<factor>]``
        ``GLOB_THERM%IDT_THERM = 1``, ``DTFACTHERM = 0.9`` unless an optional
        free-format float follows. It is a MODE SWITCH, not a step control, and
        it is the Radioss expression of ``*CONTROL_SOLUTION`` SOLN = 1:
        ``resol.F:1738`` calls ``BCSDTTH_COPY(...,1)``, which sets
        ``ICODT(N) = 7`` AND ``ICODR(N) = 7`` on every node (restored at
        ``:9167``), and ``resol.F:5807-5809`` replaces the mechanical step with
        the conduction stability step. ``lectur.F:696-698`` prints
        ``THERMAL ANALYSIS ONLY``.

    ``/THERM <THEACCFACT>``
        one float, default 1.0, a stated 0 becomes 1.0 — the exact counterpart
        of ``*CONTROL_THERMAL_SOLVER`` ``TSF``, the Thermal Speedup Factor
        (Vol I R17 p.12-576: *"This factor multiplies all thermal parameters
        with units of time in the denominator"*). ``THEACCFACT`` multiplies the
        conductivity (``dttherm.F90:114``) and the time argument of every
        thermal source (``convec.F:102-115``, ``radiation.F:109``,
        ``fixflux.F:104-105``, ``fixtemp.F:100``).

    Three traps, all source-cited:

    * **Never write ``0.0`` on the ``/DT/THERM`` value line.**
      ``freform.F:958`` is ``IF (GLOB_THERM%DTFACTHERM == ZERO) DTFACA = ZEP9``
      — it assigns the WRONG variable, so a stated zero leaves
      ``DTFACTHERM = 0`` and the thermal step is identically 0. The card is
      written bare (default 0.9) instead.
    * **``/DT/THERM`` is incompatible with AMS.** ``freform.F:1327-1330``:
      ``IDT_THERM == 1 .AND. IDTMINS /= 0`` is ``ANCMSG(301)`` + ``ARRET(0)``.
      k2rad's ``--ams`` writes ``/DT/AMS``, so the two are refused together.
    * **The thermal step is a CONDUCTION-only stability limit.** Measured: a
      ``/DT/THERM`` deck at the default 0.9 whose convection time constant was
      6x smaller than the step DIVERGED to 318 490 mJ stored (an 88 200 K rise)
      under ``0 ERROR / 0 WARNING / NORMAL TERMINATION``; the same deck at
      factor 0.05 gave 2527.7000 mJ against an analytic 2527.7000. There is no
      convective or radiative limit anywhere in ``dttherm.F90`` /
      ``mqviscb.F``, so the warning says so.
    """
    from .thermal import _thermal_solve_active
    lines: List[str] = []
    ct = state.ctrl_thermal_solver
    tsf = ct.tsf if ct is not None else 0.0
    want_dt_therm = (state.ctrl_solution_soln == 1
                     and _thermal_solve_active(state)
                     and not state.is_implicit and not state.is_modal)
    if state.ctrl_solution_soln == 1 and not want_dt_therm:
        state.warn(
            "*CONTROL_SOLUTION SOLN=1 selects a THERMAL-ONLY analysis, and "
            "Radioss can express that — the engine card /DT/THERM freezes "
            "every nodal DOF (resol.F:1738 BCSDTTH_COPY(...,1) sets "
            "ICODT = ICODR = 7 on every node) and paces the run by the "
            "conduction stability step (resol.F:5807-5809). It is NOT written "
            "here, because "
            + ("this deck runs implicitly or as a modal analysis, where the "
               "engine does not integrate the temperature at all (MEASURED: "
               "the same converted bar carries its far end 300 -> 400 K "
               "explicitly and stays at exactly 300.000 K under "
               "/IMPL/*, with HEAT STORED = 0.0000000). The SOURCE routines "
               "still run there — resol.F:6547's 'GOTO 111' skips only the "
               "block holding the single CALL TEMPUR at :6736 — so the .out's "
               "'** THERMAL ANALYSIS **' block shows plausible imposed / "
               "convection / radiation heat beside a HEAT STORED of exactly "
               "zero, and only that last number tells the story"
               if state.is_implicit or state.is_modal else
               "this deck arms no thermal solve: /DT/THERM without a "
               "/HEAT/MAT and a temperature-moving card would freeze the whole "
               "model and integrate nothing (GLOB_THERM%ITHERM_FE gates every "
               "thermal call in resol.F). Add *MAT_THERMAL_* + *PART TMID and "
               "a driver or heat-source boundary")
            + ". The mechanical model is converted as usual and its degrees of "
            "freedom stay live.")
    elif want_dt_therm and _ams_is_emitted(state):
        want_dt_therm = False
        state.warn(
            "*CONTROL_SOLUTION SOLN=1 asks for a THERMAL-ONLY run (engine card "
            "/DT/THERM) but --ams asks for Advanced Mass Scaling (/DT/AMS), "
            "and the engine refuses the pair OUTRIGHT: freform.F:1327-1330 is "
            "'IF (GLOB_THERM%IDT_THERM == 1 .AND. IDTMINS /= 0)' -> "
            "ANCMSG(301) + ARRET(0), a hard stop before the first cycle. "
            "/DT/THERM is NOT written; /DT/AMS is kept because it was asked "
            "for explicitly. Drop --ams to get the thermal-only run mode. "
            "(The screen mirrors the /DT/AMS emitter's OWN conditions — "
            "*CONTROL_TIMESTEP present with DT2MS < 0, explicit — so a deck "
            "that asked for --ams but gets no /DT/AMS keeps its /DT/THERM.)")
    if want_dt_therm:
        lines += [
            "#-  THERMAL-ONLY RUN (*CONTROL_SOLUTION SOLN=1)",
            "#   /DT/THERM freezes every nodal DOF and paces the run by the",
            "#   conduction stability step. The value line is deliberately",
            "#   OMITTED: freform.F:958 turns a stated 0 into a write of the",
            "#   WRONG variable, leaving the thermal step at exactly 0.",
            "/DT/THERM",
            "#",
        ]
        state.warn(
            "*CONTROL_SOLUTION SOLN=1 -> the engine card /DT/THERM (thermal "
            "analysis only, scale factor left at its default 0.9). Three "
            "things it does that the LS-DYNA card does not say out loud: "
            "(1) resol.F:1738 calls BCSDTTH_COPY(...,1), which sets ICODT = "
            "ICODR = 7 on EVERY node — the whole mesh is fully constrained for "
            "the run and released at resol.F:9167; (2) resol.F:5807-5809 "
            "REPLACES the mechanical time step with the thermal one, so the "
            "run's cycle count and its /ANIM/TFILE cadence change completely; "
            "(3) the thermal step is a CONDUCTION stability limit only "
            "(DTFACTHERM*0.5*Lc^2*rhoCp/max(k,1e-20), dttherm.F90:116 / "
            "mqviscb.F:666) — there is no convective or radiative limit in it. "
            "MEASURED: a deck whose convection time constant was 6x SMALLER "
            "than that step diverged to an 88 200 K temperature rise while "
            "reporting 0 ERROR / 0 WARNING / NORMAL TERMINATION; the same deck "
            "with the factor lowered to 0.05 matched its closed form to 8 "
            "figures. If the run carries a stiff /CONVEC or /RADIATION, lower "
            "the factor by hand on the /DT/THERM line (a POSITIVE number — a "
            "stated 0 is the freform.F:958 trap) and check the .out's "
            "'** THERMAL ANALYSIS **' heat balance.")
        _warn_dt_therm_window(state)
    if tsf < 0.0:
        state.warn(
            f"*CONTROL_THERMAL_SOLVER: TSF={tsf:g} < 0 makes |TSF| a load "
            "curve id giving the thermal speedup factor as a function of time "
            "(Vol I R17 p.12-576). The Radioss counterpart /THERM carries ONE "
            "constant (frethermal.F:68 reads a single float into "
            "GLOB_THERM%THEACCFACT), so a time-varying speedup is "
            "inexpressible — the card is not written and the run goes at its "
            "real thermal rate.")
    elif tsf > 0.0 and tsf != 1.0:
        # Same implicit/modal exclusion as /DT/THERM. The MECHANISM, corrected:
        # an earlier draft of this comment said convec/radiation/fixflux/
        # fixtemp are "never called from imp_solv", and that is measurably
        # FALSE — resol.F:1802/2994/3006/3025 carry NO IMPL_S test (their
        # neighbours at :2869 NCONLD, :2898 NFXVEL, :2916 NLOADP_F and :2937
        # PBLAST all do), so they run on an implicit cycle and their
        # GLOB_THERM counters fill correctly. What is dead is the nodal
        # ACCUMULATION: resol.F:6547, inside 'IF (IMPL_S == 1)', does
        # 'GOTO 111' to the label at :7949 and so skips the
        # 'IF (ILAG + IALE + IEULER /= 0)' block opened at :6552, in which the
        # one and only CALL TEMPUR sits (:6736) — and tempur.F:51-58 is the
        # whole integrator (TEMP += FTHE/MCP) and the only writer of
        # HEAT_STORED. So THEACCFACT scales sources that never reach a node:
        # an emitted-and-inert card, the #122 case. (The #129 lesson: a true,
        # measured conclusion resting on a false premise still misinforms.)
        if _thermal_solve_active(state) and not state.is_implicit \
                and not state.is_modal:
            lines += [
                "#-  THERMAL SPEED-UP (*CONTROL_THERMAL_SOLVER TSF)",
                "/THERM",
                _f(tsf).strip(),
                "#",
            ]
            state.warn(
                f"*CONTROL_THERMAL_SOLVER TSF={tsf:g} -> the engine card "
                "/THERM (THEACCFACT). Both are the same artificial "
                "time-scaling knob: LS-DYNA's 'multiplies all thermal "
                "parameters with units of time in the denominator, e.g. "
                "thermal conductivity, convection heat transfer coefficients' "
                "(Vol I R17 p.12-576), and Radioss multiplies the conductivity "
                "(dttherm.F90:114) and the TIME ARGUMENT of every thermal "
                "source (convec.F:102-115, radiation.F:109, fixflux.F:104-105, "
                "fixtemp.F:100). The two are equivalent for the heat equation "
                "but NOT identical in form: Radioss stretches the clock the "
                "sources are read at, so a /FUNCT of time is sampled "
                f"{tsf:g}x faster as well. The starter echoes it as 'FACTOR TO "
                "SPEED-UP THERMAL ANALYSIS' (lectur.F:700-702) only when it is "
                "greater than 1.")
        else:
            state.warn(
                f"*CONTROL_THERMAL_SOLVER TSF={tsf:g} would map to the engine "
                "card /THERM (THEACCFACT), but it is not written because "
                + ("this deck runs implicitly or as a modal analysis, where "
                   "there is nothing to speed up: MEASURED, an implicit run "
                   "of a converted thermal bar leaves every undriven node at "
                   "exactly its initial temperature and reports HEAT STORED = "
                   "0.0000000, while its explicit twin conducts normally. "
                   "THEACCFACT would still be READ (frethermal.F:64-70) and "
                   "would still scale the sources, which do run — it is the "
                   "nodal accumulation that resol.F:6547's 'GOTO 111' skips, "
                   "by jumping over the block that holds the single CALL "
                   "TEMPUR at :6736 — so the card would be emitted-and-inert"
                   if state.is_implicit or state.is_modal else
                   "this deck arms no thermal solve — no material gets a "
                   "/HEAT/MAT and/or no temperature-moving card is emitted, "
                   "so there is nothing for it to speed up")
                + ".")
    return lines


def build_engine(state: ConversionState) -> str:
    sections = [
        _make_engine_header(state),
        _make_engine_restart(state),
        # /PARITH is a global run flag like /RFILE, and is emitted ONLY when
        # the deck carries a *CONTROL_PARALLEL — see _make_engine_parith for
        # why the unconditional /PARITH/OFF dyna2rad writes is not neutral.
        _make_engine_parith(state),
        _make_engine_output(state),
        # /DYNAIN is an ENGINE keyword, so it goes here rather than into the
        # starter. After _make_engine_output because the starter-side
        # registries it screens (state.shell_elem_ids, state.parts) are filled
        # by build_starter, which k2rad/__init__.py runs BEFORE build_engine,
        # and because check_dynain.F re-parses this file from inside the
        # STARTER — see _make_engine_dynain for the two measured traps.
        _make_engine_dynain(state),
        _make_engine_timestep(state),
        # /DT/THERM is a /DT sub-card, so it sits with its siblings — and it
        # must run AFTER _make_engine_timestep, which is what decides whether
        # /DT/AMS was written (freform.F:1327 refuses the pair outright).
        _make_engine_thermal(state),
        _make_engine_dt_deletion(state),
        _make_engine_implicit(state),
        _make_engine_cpu(state),
        ["/MON/ON", "#"],
    ]
    lines: List[str] = []
    for sec in sections:
        lines.extend(sec)
    return "\n".join(lines) + "\n"
