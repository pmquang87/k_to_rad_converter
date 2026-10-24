"""Top-level assemblers: build_starter / build_engine and the engine-card emitters."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from ..state import ConversionState, EngineSegment
from .beams import _resolve_integration_beams
from .common import HDR, _SOLVINFO_HINT, _ams_is_emitted, _f, _i
from .materials import (
    _apply_zero_density_floor,
    _make_functions,
    _make_materials,
    _resolve_define_tables,
    _resolve_define_tables_3d,
    _resolve_mat_gurson,
    _resolve_mat_hyper_rubber,
    _resolve_mat_iso_elas_plas,
    _resolve_eos_gruneisen_a,
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
    _resolve_he_bunreacted,
    _resolve_ale_submaterials,
    _warn_refused_materials,
    _resolve_modal_acoustic_void,
)
from .muscle import _make_muscle_springs
from .axisym2d import (resolve_axisym_plan, transform_engine_lines,
                       transform_starter_lines)
from .loadcurves import make_offscale_functs
from .thermal import (_make_thermal, _resolve_thermal,
                      _resolve_weld_trajectories, _thermal_solve_active,
                      _weld_anim_dt)
from .mesh import (
    _assign_ortho_props,
    _assign_hourglass_props,
    _downgrade_tet10_to_tet4,
    _expand_set_ranges_and_generals,
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
    _bolt_end_rigid_members,
    _make_force_transducers,
    _make_refused_contact_notes,
    _make_general_interfaces,
    _make_interfaces,
    _make_tied_interfaces,
    _make_tiebreak_interfaces,
    _make_spotweld_interfaces,
    _make_type25_interfaces,
    _make_deferred_implicit_stub,
    _recipe_active,
    _warn_beam_contact_secondary_unused,
)
from .frictions import _make_frictions
from .rbody import (_make_cnrb_rbodies, _make_generalized_weld_butt_rbodies,
                    _make_probe_rbody, _make_rbodies,
                    _make_screw_carriage_rbodies,
                    _make_shell_to_solid_rbodies)
from .rbe3 import _make_rbe3
from .joints import _make_joints, _resolve_joints
from .joint_screw import _make_joint_screws, _resolve_joint_screws
from .dbeam import _make_discrete_beam_connectors
from .loads import (
    _make_added_masses,
    _make_bcs,
    _make_node_tc_rc_bcs,
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
    _make_tied_nodes_failure_notes,
    _make_constrained_linear_mpcs,
    _resolve_constrained_globals,
    _synthesize_spotweld_second_nodes,
    _apply_mass_weighted_rbody_inertia,
    _merge_mass_weighted_pairs,
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
    _make_shell_in_solid_coupling,
    _make_shell_in_solid_notes,
    _resolve_shell_in_solid,
    _make_ale_reference_notes,
    finalize_shell_in_solid,
    sis_dt_inter_guard,
    sis_dt_inter_lines,
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
    # round 8, B3 (h.2): one engine file per IMFLAG segment - its own run
    # number (the FILE number, get_file_name_info.F:63) and its own end
    seg = state.engine_segment
    run = seg.run if seg is not None else 1
    stop = seg.t_stop if seg is not None else endtim
    return [f"/RUN/{safe_title}/{run}", f"{stop:.6G}", "#"]


def _engine_implicit(state: ConversionState) -> bool:
    """The method of the engine file BEING BUILT (round 8, B3 h.2): the
    segment's under ``--imflag-curve-restart``, else the deck's. Every
    ENGINE-side read of ``state.is_implicit`` goes through it; the starter
    keeps ``state.is_implicit`` (the starter is the implicit one
    throughout)."""
    seg = state.engine_segment
    return seg.implicit if seg is not None else state.is_implicit


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
               # convert() (k2rad/__init__.py, step 3) calls build_starter before
               # build_engines, so all three registries are filled by the time
               # this is read.
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
    # Round 9, B1 (S2): a SOLN-1 deck with an accepted weld trajectory that
    # requests > 1000 frames gets max(d3plot dt, ENDTIM / 100); every other
    # deck keeps dt_anim (writer/thermal._weld_anim_dt).
    dt_anim = _weld_anim_dt(state, dt_anim, endtim)
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


#: The LS-DYNA *CONTROL_IMPLICIT_SOLUTION card-1 NSOLVR values that select the
#: arc-length (Riks) continuation on their own. The ONE other route is
#: NSOLVR 12 with card-3 ARCMTH = 3 — see `_arclength_requested`.
_ARCLENGTH_NSOLVR = frozenset({6, 7, 8, 9})

#: The card-3 ARCMTH value that activates the method under NSOLVR 12.
_ARCLENGTH_ARCMTH = 3


def _arclength_requested(state: ConversionState) -> bool:
    """Does this deck ask LS-DYNA for arc-length (Riks) continuation?

    THE MANUAL'S OWN RULE, quoted verbatim from Vol I R17 p.12-354 and again
    on the card-3 definition page p.12-358 (and identically in Vol I R16, so
    it is not an R17 novelty): *"The contents of this card are ignored unless
    an arc-length method is activated (6 <= NSOLVR <= 9, or NSOLVR = 12 and
    ARCMTH = 3)"*.

    ``ARCCTL`` is NOT part of the predicate and must not be: p.12-358 defines
    it as *"Arc length controlling node ID (see Remark 7). EQ.0: Generalized
    arc length method"* — a node id whose 0 selects the generalized variant of
    a method that is already on, not a switch that turns one on.

    An ``arcctl != 0`` predicate used to ship here, and it was wrong on a
    corpus deck we could measure: ``ex_06_beam_elform_1`` states NSOLVR 12 /
    ARCMTH 1 / ARCCTL 6, and its LS-DYNA reference run's own ``d3hsp`` shows
    plain BFGS — ``solution method ... 12``, the legend
    *"eq.12: nonlinear, (experimental), BFGS updates with optional arclength"*,
    and card 6 echoing *"arc length formulation 1 = Crisfield (generalized arc
    length only)"* beside *"eq.3: Modified Crisfield (used with nonlinear
    solution method 12 only)"*. So the deck LS-DYNA ran WITHOUT arc length was
    getting a default-ON warning saying it asked for one, and under
    ``--arclength-riks`` would have been converted to a solver LS-DYNA did not
    use. Carriers on the 356-key R14 roster under the manual's rule: TWO
    (``ex_05_beam_elform_3_&_6`` and ``ex_07_beam_elform_1``, both NSOLVR 6);
    under the retracted rule, three. The canonical NSOLVR 12 + ARCMTH 3 deck
    has 0 carriers here, so that arm is a rule and not a measured save.
    """
    sol = state.ctrl_implicit_sol
    if sol is None:
        return False
    if sol.nsolvr in _ARCLENGTH_NSOLVR:
        return True
    return sol.nsolvr == 12 and sol.arcmth == _ARCLENGTH_ARCMTH


#: The *CONTROL_IMPLICIT_SOLUTION NSOLVR values --implicit-bfgs reaches: 12
#: (LS-DYNA's nonlinear solver with BFGS updates) and 0 = a blank cell.
_BFGS_NSOLVR = frozenset({0, 12})


def _bfgs_requested(state: ConversionState) -> bool:
    """R14 triage round 9, A12: does ``--implicit-bfgs`` apply to this deck?

    An implicit, non-modal deck whose ``*CONTROL_IMPLICIT_SOLUTION`` NSOLVR
    is 12 or blank (or that states no such card) - the one family the
    option was measured on (ex_06_beam_elform_1, NSOLVR 12). Any other
    NSOLVR keeps ``/IMPL/NONLIN/1`` and is named by
    :func:`_warn_implicit_bfgs`.
    """
    if not (state.options.implicit_bfgs and state.is_implicit
            and not state.is_modal):
        return False
    sol = state.ctrl_implicit_sol
    return sol is None or sol.nsolvr in _BFGS_NSOLVR


def _warn_implicit_bfgs(state: ConversionState) -> None:
    """The ``--implicit-bfgs`` sentence: what it writes, the one carrier it
    was measured on, and the silent failure it can give (round 9, A12)."""
    if not (state.options.implicit_bfgs and state.is_implicit
            and not state.is_modal):
        return
    sol = state.ctrl_implicit_sol
    n = sol.nsolvr if sol is not None else 0
    if not _bfgs_requested(state):
        state.warn(
            f"--implicit-bfgs: *CONTROL_IMPLICIT_SOLUTION NSOLVR {n} is not "
            "the family the option was measured on (NSOLVR 12 or blank: "
            "ex_06_beam_elform_1), so /IMPL/NONLIN/1 and the /IMPL/QSTAT "
            "choice stay as without the flag.")
        return
    qstat = ("the /IMPL/QSTAT card --qstat-dtscal asked for is kept"
             if state.options.qstat_dtscal_stated else
             "no /IMPL/QSTAT card")
    state.warn(
        f"--implicit-bfgs: /IMPL/NONLIN/2 (Quasi-Newton BFGS) in place of "
        f"/IMPL/NONLIN/1 for NSOLVR {n or 'blank'}, with {qstat}. "
        + _BFGS_MEASURED)


#: The measured record of --implicit-bfgs (round 9, A12, on the branch
#: bytes). ONE constant so the warning and the docs cannot drift. doorbeam
#: (the A1 + A2 bytes, engine file sha256 a31d565457c5): 96 runs of
#: identical bytes - the round-9 record's 14 (implement A's two, the
#: solver-physics validator's six, the fix round's six) and the post-review
#: round's 82 (its fix agent's 50, its verifiers' 32); a NORMAL banner in
#: every run, nonsense internal energy in 4 of 51 at nt 4 (none in the fix
#: agent's 30 there, four in the verifiers' 14) and 9 of 45 at nt 2 - which
#: run fails is run to run, not an nt property (the round-9 text tied it to
#: nt 2). The TYPE25 route: 14 runs (the round-9 two, the post-review 12),
#: 13 NORMAL, every one with nonsense energy - a band, not a figure.
_BFGS_MEASURED = (
    "Measured on ONE carrier: ex_06_beam_elform_1 NORMAL in 277 cycles, "
    "internal energy END -0.09 %, RMS 0.09 % of the LS peak over 121 LS "
    "times in (0.01, 1.0], nt 4 = nt 2, where the default stops at t "
    "0.1601 (IE -59.58 %). The failure can be SILENT, on the default bytes "
    "too, at nt 4 AND nt 2: doorbeam (A1 + A2 bytes) ends a NORMAL banner in "
    "all 96 runs of identical bytes, and 13 of them carry NONSENSE internal "
    "energy (4 of 51 at nt 4, 9 of 45 at nt 2; END -19769.57 .. +1082.01 %) "
    "- run to run, not an nt property - while the other 83 end -11.85 .. "
    "+29.51 %; the TYPE25 route (--no-implicit-n2s-type7) carries nonsense "
    "energy behind the banner too (13 of 14 runs NORMAL, every one "
    "nonsense); tensile2's IE RMS goes 2.48 -> 5.61 % (END -0.54 -> +26.88 "
    "%, nt 4 = nt 2). Check the energies before using a run.")


def _qstat_dtscal_cell(state: ConversionState) -> Optional[str]:
    """The ``/IMPL/QSTAT/DTSCAL`` data cell, or None to emit no card.

    ``options.qstat_dtscal`` is a positive number or the literal ``"none"``
    (``--qstat-dtscal none``). Numbers are printed with ``%g`` so the default
    10.0 writes ``10`` and 0.1 writes ``0.1`` — the same text the pre-round-4
    constant produced, so ``--qstat-dtscal 0.1`` restores the old line byte for
    byte.

    Anything else RAISES. ``cli._qstat_dtscal_arg`` and the GUI already refuse
    ``<= 0`` and a non-number, but ``convert(qstat_dtscal=...)`` is a public
    entry point of its own and used to format whatever it was handed: MEASURED
    through the API, ``-3.0`` wrote the cell ``-3`` and ``0.0`` wrote ``0``,
    which divides by zero in ``M/((1+alpha)*beta*(DTSCAL*dt)^2)``
    (``imp_dyna.F:351-356``), and an unparsable string silently became the
    default ``10`` instead of telling the caller their value never arrived.
    """
    v = state.options.qstat_dtscal
    if isinstance(v, str):
        if v.strip().lower() == "none":
            return None
        try:
            v = float(v)
        except ValueError:
            raise ValueError(
                f"qstat_dtscal must be a number or 'none', not {v!r}")
    fv = float(v)
    if fv <= 0.0:
        raise ValueError(
            f"qstat_dtscal must be > 0 (got {fv:g}); pass 'none' to emit no "
            "/IMPL/QSTAT card. The engine divides by (DTSCAL*dt)^2 "
            "(imp_dyna.F:351-356), so 0 is a division by zero and a negative "
            "value has no meaning.")
    return f"{fv:g}"


def _warn_arclength(state: ConversionState, modal: bool = False) -> None:
    """Name LS-DYNA's arc-length request, and what ``--arclength-riks`` buys.

    Fires on EVERY carrier, flag or no flag: the deck asked for a continuation
    method k2rad does not write by default, and silence is what used to leave
    ``ControlImplicitSolution.nsolvr`` "PARSED AND UNUSED" with nothing in the
    log. What the flag emits is named, and so is the measurement that keeps it
    opt-in.

    *modal* is True on a ``/EIG`` deck, where the request is dropped no matter
    what the flag says — the modal engine writes no ``/IMPL/DT`` card at all,
    so there is nothing for ``/IMPL/DT/3`` to replace. Reach of that arm on the
    R14 roster: 0 decks (all three arc-length carriers are non-modal), so it is
    stated rather than measured.
    """
    sol = state.ctrl_implicit_sol
    if sol is None:
        return
    asks = []
    if sol.nsolvr in _ARCLENGTH_NSOLVR:
        asks.append(f"card-1 NSOLVR={sol.nsolvr}")
    else:
        asks.append(f"card-1 NSOLVR={sol.nsolvr} with card-3 "
                    f"ARCMTH={sol.arcmth}")
    if sol.arcctl != 0:
        asks.append(f"controlling node card-3 ARCCTL={sol.arcctl}")
    head = (f"*CONTROL_IMPLICIT_SOLUTION {' and '.join(asks)} requests "
            "LS-DYNA's ARC-LENGTH (Riks) continuation. Its Radioss counterpart "
            "is /IMPL/DT/3 (freimpl.F:384-387 reads SEVEN fields "
            "NL_DTP/ALEN0/NL_DTN/Tsca_dn/Tsca_up/IAL_M/SCAL_RIKS; the zero "
            "cells take lectur.F:3518-3522's defaults NL_DTP 12 / NL_DTN 25 / "
            "Tsca_dn 2-3 / Tsca_up 1.2 / IAL_M 2). ")
    measured = (
        "It BUYS THE LOAD PATH, NOT THE ANSWER: on ex_07_beam_elform_1 the "
        "path loops through negative load factors LS-DYNA never visits (the "
        "converged load factor goes down to -0.4412 and turns back and forth "
        "many times in every round-9 run; LS-DYNA's path rises to 0.3745, "
        "unloads to exactly 0 and reloads to 1.185, and never goes below 0) "
        "and the run ends NORMAL in 9 of 10 "
        "runs of identical bytes (1192 .. 1219 cycles: five at nt 4, four "
        "at nt 2) and ERROR once at nt 4 (MESSAGE 79 at cycle 1421, the load "
        "factor back at 0); ex_05_beam_elform_3_&_6 still stops (MESSAGE 79 "
        "at load factor 0.84 .. 0.87 in four runs at nt 4 and nt 2). The LS "
        "reference of both is UNMATCHED "
        "(its time axis runs backwards), so no run is evidence of the "
        "answer - which is why the flag ships OFF. /IMPL/DT/FIXPOINT is "
        "DEACTIVATED by the engine under RIKS (lectur.F:3523-3532), so "
        "--fixpoint-count is silently disarmed with it.")
    if modal:
        state.warn(head + "This deck is a NORMAL-MODES (/EIG) analysis, whose "
                          "engine is /IMPL/LINEAR plus the stiffness export "
                          "and writes no /IMPL/DT card at all, so the "
                          "arc-length request is DROPPED whatever "
                          "--arclength-riks says - there is no step controller "
                          "for /IMPL/DT/3 to replace. " + measured)
    elif state.options.arclength_riks:
        qstat = ("the /IMPL/QSTAT card --qstat-dtscal asked for is kept"
                 if state.options.qstat_dtscal_stated else
                 "NO /IMPL/QSTAT card is written (the quasi-static term would "
                 "stiffen the arc-length tangent, imp_dyna.F:351-355; pass "
                 "--qstat-dtscal to keep one - through the API, "
                 "qstat_dtscal=<value> WITH qstat_dtscal_stated=True)")
        state.warn(head + "--arclength-riks was passed: /IMPL/DT/3 replaces "
                          f"/IMPL/DT/2 and {qstat}. " + measured)
    else:
        state.warn(head + "It is NOT emitted: k2rad writes /IMPL/DT/2 and the "
                          "arc-length request is DROPPED. Pass "
                          "--arclength-riks to emit it. " + measured)


def _written_step_card(state: ConversionState, modal: bool) -> str:
    """The step card k2rad writes, in words, for the constant-step and
    ``*CONTROL_IMPLICIT_AUTO`` sentences."""
    if modal:
        return ("no /IMPL/DT card at all - a modal deck's engine is "
                "/IMPL/LINEAR plus the stiffness export")
    if _arclength_requested(state) and state.options.arclength_riks:
        return "/IMPL/DT/3 (the arc-length control --arclength-riks asked for)"
    return ("/IMPL/DT/2 (AUTOMATIC step control) with It_w taken from "
            "ITEOPT alone")


def _constant_step_body(state: ConversionState) -> str:
    """What LS-DYNA does with IAUTO 0 on THIS deck, and what k2rad writes
    instead (non-modal implicit decks; R14 triage round 6, B2).

    Keyed on DT0 against ENDTIM - the ``/RUN`` value, read after
    ``*PARAMETER`` substitution - because LS-DYNA's constant step means four
    different things: DT0 steps to ENDTIM (0 < DT0 < ENDTIM; 24 + 10 roster
    keys), ONE step of ENDTIM (DT0 = 0: 6 keys, ``ex_01`` / ``ex_02``; DT0 >=
    ENDTIM: 9 + 1 keys - the dynamic 1e-3 DTINI sub-arm has reach 0, a
    fixture pins it) and ``|DT0|`` with the geometric-stiffness option (DT0 <
    0, Vol I R17 p.12-321; reach 0 of the 136 roster keys that state the
    card). The numbers are :func:`_implicit_step_cells`' - the ones the
    ``/IMPL/DTINI`` and ``/IMPL/DT/STOP`` cards carry. ``--implicit-constant-
    step`` is named only where :func:`_constant_step_scope` says it WOULD act.
    """
    gen = state.ctrl_implicit_gen
    auto = state.ctrl_implicit_auto
    dt0 = gen.dt0 if gen else 0.0
    end = _run_end(state)
    dtini, _dtmin, dtmax = _implicit_step_cells(state)
    written = _written_step_card(state, False)
    it_w = auto.iteopt if auto and auto.iteopt > 0 else 8
    if dt0 < 0.0:
        return (f"DT0 = {dt0:g} is NEGATIVE: Vol I R17 p.12-321 reads it as an "
                f"initial step of |DT0| = {abs(dt0):g} with negative principal "
                "stresses eliminated from the geometric stiffness. k2rad "
                f"writes /IMPL/DTINI {dtini:g} (it takes 0.01 for any DT0 <= "
                f"0) and {written}; the geometric-stiffness option has no "
                "/IMPL counterpart and is DROPPED.")
    if dt0 == 0.0:
        return ("DT0 of *CONTROL_IMPLICIT_GENERAL is 0, so LS-DYNA solves the "
                f"whole run as ONE implicit step of ENDTIM = {end:g} (the R14 "
                "references of this shape echo 'initial time step for "
                "implicit solution 0.0000E+00' and print one glstat step of "
                f"ENDTIM). k2rad writes /IMPL/DTINI {dtini:g} and {written}, "
                "so the converted deck marches in adaptive steps from "
                f"{dtini:g} instead. --implicit-constant-step does not act on "
                "DT0 = 0.")
    if dt0 >= end:
        head = (f"DT0 = {dt0:g} is not smaller than ENDTIM = {end:g}, so "
                "LS-DYNA solves the run in ONE implicit step. k2rad writes "
                f"/IMPL/DTINI {dtini:g} and {written}; ")
        if dtini >= end:
            return head + ("the first Radioss step is the whole run too "
                           "(imp_init.F:95 takes the remaining time once DTINI "
                           "reaches it), but a step that does not converge is "
                           "CUT and retried (imp_dt.F:107-119) where LS-DYNA "
                           "would stop in error (p.12-362 Remark 4).")
        return head + ("the 1e-3 cap k2rad puts on a dynamic deck's DTINI "
                       "makes it march in adaptive steps instead.")
    lead = (f"LS-DYNA holds every implicit step at DT0 = {dt0:g} of "
            f"*CONTROL_IMPLICIT_GENERAL ({round(end / dt0)} steps to ENDTIM = "
            f"{end:g}; p.12-323 Remark 2: the step changes only when "
            "automatic control is active - every R14 reference d3hsp of this "
            "class echoes 'time step control method 0'). k2rad writes "
            f"/IMPL/DTINI {dtini:g} and {written}")
    tail = (f"SHRINKS it after an increment that needed more than It_w = "
            f"{it_w} iterations and CUTS it on a non-converged one "
            "(imp_dt.F:107-174), where LS-DYNA keeps DT0 and ends in error "
            "(p.12-362 Remark 4).")
    if _constant_step_scope(state)[0]:
        return (lead + "; its DT_MAX is DT0 (--implicit-constant-step, see "
                "its own warning), so the converted deck can no longer GROW "
                "the step above DT0, but it still " + tail)
    if 0.0 < dtmax <= dt0:
        return (lead + f", and the deck's own DTMAX = {dtmax:g} keeps the step "
                "at or below DT0, but the converted deck still " + tail)
    flag = ""
    if _constant_step_scope(state, assume_flag=True)[0]:
        flag = (" --implicit-constant-step caps the Radioss step at DT0 "
                "(/IMPL/DT/STOP DT_MAX := DT0; the cut-back stays); it is OFF "
                "by default - see its --help for the measured cost.")
    return (lead + ", so the converted deck GROWS the step above DT0 on easy "
            "increments, " + tail + flag)


def _warn_implicit_auto_drops(state: ConversionState,
                              modal: bool = False) -> None:
    """``*CONTROL_IMPLICIT_AUTO``: the cells that reach no ``/IMPL`` card.

    ``handle_control_implicit_auto`` parses IAUTO, ITEOPT, ITEWIN, DTMIN,
    DTMAX and KFAIL; the writer reads ITEOPT (into ``/IMPL/DT/2`` It_w) and
    DTMIN/DTMAX (into ``/IMPL/DT/STOP``) and NOTHING else. Three of the six are
    therefore parsed-and-unused, and a NEGATIVE DTMAX — LS-DYNA's "this is a
    load-curve id, not a value" idiom — is dropped outright, leaving the
    implicit step unbounded (``lectur.F:3546`` turns a zero DT_MAX into EP10).

    **``IAUTO = 0`` is named too**, and it is the cell where the substitution
    is largest. A truthiness filter used to skip it; but Vol I R17 p.12-277
    defines ``IAUTO EQ.0: Constant time step size``, that is the card's own
    DEFAULT, and k2rad writes ``/IMPL/DT/2`` — automatic step control — on
    every implicit deck regardless. MISTAKES #136: a value a deck leaves blank
    still has a solver default and the default can be load-bearing. Censused
    over the 356-key R14 roster: 11 decks state or blank ``IAUTO = 0``,
    ``tensile2`` (one of round 4's four ``--qstat-dtscal`` movers) and the
    whole ``ex_14_solid_elform_*`` family among them, against 22 with
    ``IAUTO > 0``. ``IAUTO < 0`` gets the load-curve gloss p.12-277 gives it,
    the same one ``DTMAX < 0`` already had.

    One warning per deck (the card is a singleton). *modal* is True on a
    ``/EIG`` deck, where the drop is the same but the card that would have read
    the cells is not ``/IMPL/DT/2`` — the modal recipe writes no ``/IMPL/DT``
    card at all — so the sentence says that instead of naming a card the deck
    does not carry.

    **The ABSENT card is IAUTO 0 too** (R14 triage round 6, B2). The early
    return this function used to take when no ``*CONTROL_IMPLICIT_AUTO`` is
    stated told the 39 deck keys on 28 emitted models of that shape nothing,
    although the card's default is the same "Constant time step size" and
    k2rad writes the same ``/IMPL/DT/2``. Both shapes now get ONE sentence
    builder, :func:`_constant_step_body`, keyed on DT0 against ENDTIM (a
    constant step, one step of ENDTIM when DT0 = 0 or DT0 >= ENDTIM, and the
    ``|DT0|`` reading of a negative DT0) and on the card k2rad writes. The
    shipped "grows and cuts the implicit step where LS-DYNA holds it at DT0"
    was false for a one-step deck (``tensile1``: DT0 = ENDTIM) and for a
    modal deck (no ``/IMPL/DT`` card; reach 0 - no modal roster deck states
    IAUTO 0). Non-modal implicit decks only for the absent card; a modal deck
    with no card gets nothing. Warning only: no ``.rad`` byte moves.
    """
    auto = state.ctrl_implicit_auto
    if auto is None:
        if not modal and state.is_implicit:
            state.warn("*CONTROL_IMPLICIT_AUTO is ABSENT, so IAUTO takes its "
                       "default 0, which Vol I R17 p.12-277 defines as "
                       "'Constant time step size'. "
                       + _constant_step_body(state))
        return
    gloss = {"ITEWIN": "the iteration window",
             "KFAIL": "the number of failed steps before an abort"}
    unused = [(n, v) for n, v in (("ITEWIN", auto.itewin),
                                  ("KFAIL", auto.kfail)) if v]
    neg_dtmax = auto.dtmax < 0.0
    written = _written_step_card(state, modal)
    msg = "*CONTROL_IMPLICIT_AUTO: "
    if auto.iauto == 0:
        if modal:
            msg += ("IAUTO=0 - LS-DYNA's own default, 'Constant time step "
                    "size' (Vol I R17 p.12-277). This deck is a NORMAL-MODES "
                    "analysis whose engine is ONE /IMPL/LINEAR step with no "
                    "/IMPL/DT card, so no step control applies either way. ")
        else:
            msg += ("IAUTO=0 - LS-DYNA's own default, and Vol I R17 p.12-277 "
                    "defines it as 'Constant time step size'. "
                    + _constant_step_body(state) + " ")
    elif auto.iauto < 0:
        msg += (f"IAUTO={auto.iauto} is NEGATIVE, i.e. Vol I R17 p.12-277's "
                "'IAUTO LT.0: Curve ID = (-IAUTO) gives time step size as a "
                f"function of time'. The curve is DROPPED: k2rad writes "
                f"{written}. ")
    else:
        msg += (f"IAUTO={auto.iauto} (the auto-step on/off switch) is parsed "
                f"and NOT used - k2rad writes {written} whatever it says. ")
    if unused:
        msg += (", ".join(f"{n}={v} ({gloss[n]})" for n, v in unused) + " "
                + ("is" if len(unused) == 1 else "are")
                + " parsed and NOT used either. ")
    if neg_dtmax:
        msg += (f"DTMAX={auto.dtmax:g} is NEGATIVE, i.e. LS-DYNA's idiom for "
                "'-DTMAX is a LOAD CURVE id giving the maximum step as a "
                "function of time' (Vol I R17 *CONTROL_IMPLICIT_AUTO). "
                "/IMPL/DT/STOP takes a CONSTANT maximum, so the curve is "
                "DROPPED and the step is left UNBOUNDED: lectur.F:3546 turns "
                "a zero DT_MAX into EP10. LS-DYNA's own default for DTMAX = 0 "
                "is 'max. allowed step size is 10*initial step size', which "
                "k2rad does not write either. MEASURED on "
                "ex_27_solid_elform_2_rigidwall_penalty_implicit: setting "
                "DT_MAX to that deck's own DT0 changed nothing.")
    state.warn(msg.rstrip())


def _run_end(state: ConversionState) -> float:
    """EXACTLY the ``/RUN`` value: :func:`_make_engine_header`'s own
    expression. ENDTIM is read AFTER ``*PARAMETER`` substitution
    (``handle_control_termination``), so a deck that states ``&t_ends`` arrives
    here as its number."""
    return state.ctrl_termination.endtim if state.ctrl_termination else 1.0


def _implicit_dtini_dtmin(state: ConversionState) -> Tuple[float, float]:
    """``/IMPL/DTINI`` and the ``/IMPL/DT/STOP`` DT_MIN exactly as
    :func:`_make_engine_implicit` writes them: DT0 (0.01 when DT0 <= 0), capped
    at 1e-3 on a dynamic deck (the ``K + M/(beta dt^2)`` stabilization comment
    there), and DT_MIN = the stated ``*CONTROL_IMPLICIT_AUTO`` DTMIN or
    ``max(1e-4 x DTINI, 1e-10)``. ONE computation, shared by the emitter, the
    constant-step sentence and the ``--implicit-constant-step`` scope, so a
    warning and the card it describes cannot read two different numbers."""
    gen = state.ctrl_implicit_gen
    dyn = state.ctrl_implicit_dyn
    auto = state.ctrl_implicit_auto
    dt0_in = gen.dt0 if gen and gen.dt0 > 0 else 0.01
    is_dynamic_pre = bool(dyn and dyn.imass > 0)
    dtini = min(dt0_in, 1e-3) if is_dynamic_pre else dt0_in
    dtmin = auto.dtmin if auto and auto.dtmin > 0 else max(dtini * 1e-4, 1e-10)
    return dtini, dtmin


def _constant_step_scope(state: ConversionState,
                         assume_flag: bool = False) -> Tuple[bool, str]:
    """Does ``--implicit-constant-step`` write DT_MAX := DT0 on this deck?

    ``(True, "")`` or ``(False, <why not>)``. ``assume_flag=True`` answers
    "WOULD it act?", which the absent-card constant-step sentence asks before
    naming the flag, so a user is never pointed at a lever that does nothing
    on the deck. The scope is LS-DYNA's constant-step class that the cap can
    express: an implicit time-marching deck (not modal, not the
    ``--arclength-riks`` ``/IMPL/DT/3`` arm) whose ``*CONTROL_IMPLICIT_AUTO``
    is absent or states IAUTO 0 (Vol I R17 p.12-277 "EQ.0: Constant time step
    size"), with ``0 < DT0 < ENDTIM`` (DT0 = 0 and DT0 >= ENDTIM are ONE
    LS-DYNA step; DT0 < 0 is p.12-321's ``|DT0|`` with the geometric-stiffness
    option - reach 0 of the 136 roster keys that state the card), no stated
    DTMAX in (0, DT0] (that already caps the step: ex_14_solid_elform_3 is
    byte-identical) and a DT_MIN below DT0 (a pinned step was measured NO-GO).
    """
    if not (assume_flag or state.options.implicit_constant_step):
        return False, "the flag is not set"
    if state.is_modal or not state.is_implicit:
        return False, ("the deck is not an implicit time-marching analysis (a "
                       "modal deck writes no /IMPL/DT card)")
    if _arclength_requested(state) and state.options.arclength_riks:
        return False, ("--arclength-riks writes /IMPL/DT/3, whose arc-length "
                       "step this flag does not touch")
    auto, gen = state.ctrl_implicit_auto, state.ctrl_implicit_gen
    if auto is not None and auto.iauto != 0:
        return False, (f"*CONTROL_IMPLICIT_AUTO IAUTO={auto.iauto} asks for "
                       "automatic (or curve-driven) step control")
    dt0 = gen.dt0 if gen else 0.0
    end = _run_end(state)
    if dt0 < 0.0:
        return False, (f"DT0 = {dt0:g} < 0 is not converted as a step (see the "
                       "*CONTROL_IMPLICIT_AUTO sentence)")
    if dt0 == 0.0:
        return False, "DT0 = 0: LS-DYNA takes ONE step of ENDTIM"
    if dt0 >= end:
        return False, (f"DT0 = {dt0:g} >= ENDTIM = {end:g}: LS-DYNA takes ONE "
                       "step")
    if auto is not None and 0.0 < auto.dtmax <= dt0:
        return False, (f"the deck's own DTMAX = {auto.dtmax:g} <= DT0 already "
                       "caps the step")
    _dtini, dtmin = _implicit_dtini_dtmin(state)
    if dtmin >= dt0:
        return False, (f"the deck's DTMIN = {dtmin:g} is not below DT0 - a "
                       "pinned step, measured NO-GO")
    return True, ""


def _implicit_step_cells(state: ConversionState) -> Tuple[float, float, float]:
    """``(DTINI, DT_MIN, DT_MAX)`` exactly as ``/IMPL/DTINI`` +
    ``/IMPL/DT/STOP`` write them. DT_MAX is the stated
    ``*CONTROL_IMPLICIT_AUTO`` DTMAX > 0, else 0 (``lectur.F:3546`` reads 0 as
    1e10, i.e. unbounded) - and, under ``--implicit-constant-step`` inside
    :func:`_constant_step_scope`, the deck's own DT0 (NOT the dynamic-capped
    DTINI)."""
    auto = state.ctrl_implicit_auto
    dtini, dtmin = _implicit_dtini_dtmin(state)
    dtmax = auto.dtmax if auto and auto.dtmax > 0 else 0.0
    applies, _why = _constant_step_scope(state)
    if applies and state.ctrl_implicit_gen is not None:
        dtmax = state.ctrl_implicit_gen.dt0
    return dtini, dtmin, dtmax


def _warn_implicit_constant_step(state: ConversionState) -> None:
    """``--implicit-constant-step``: say what it wrote, or why it wrote nothing
    (R14 triage round 6, B3). Silent without the flag and on an explicit deck;
    one warning per implicit or modal deck with it."""
    if not state.options.implicit_constant_step:
        return
    if not (state.is_implicit or state.is_modal):
        return
    applies, why = _constant_step_scope(state)
    if not applies:
        state.warn("--implicit-constant-step was passed but wrote nothing on "
                   f"this deck: {why}.")
        return
    gen, auto = state.ctrl_implicit_gen, state.ctrl_implicit_auto
    dt0 = gen.dt0 if gen else 0.0
    it_w = auto.iteopt if auto and auto.iteopt > 0 else 8
    iauto = ("0 (stated)" if auto is not None else
             "0 by default (no *CONTROL_IMPLICIT_AUTO)")
    replaced = (f"; the deck's own DTMAX = {auto.dtmax:g} is replaced by DT0"
                if auto is not None and auto.dtmax > dt0 else "")
    state.warn(
        f"--implicit-constant-step: /IMPL/DT/STOP DT_MAX := DT0 = {dt0:g}, the "
        "deck's own *CONTROL_IMPLICIT_GENERAL DT0 - LS-DYNA holds every step "
        f"there because IAUTO is {iauto} (Vol I R17 p.12-277). /IMPL/DT/2 can "
        "no longer GROW the step above DT0 (imp_dt.F:129 / :167); it still "
        "CUTS a non-converged increment (imp_dt.F:107-119) where LS-DYNA would "
        "end in error (p.12-362 Remark 4), and it still SHRINKS the step after "
        f"an increment that needed more than It_w = {it_w} iterations "
        f"(imp_dt.F:141-150){replaced}; a pinned step (DT_MIN = DT0) was "
        "measured to end 3 of 3 NORMAL quasi-static R14 decks at their first "
        "non-converged increment and is not offered. MEASURED on the R14 "
        "roster (nt 4 and nt 2 identical in cycles and steps): the dynamic "
        "carriers take 2.9x to 5.9x the cycles (ex_11 35 -> 100, ex_15 53 -> "
        "202, ex_14 34 -> 201) and follow their references closer in time - "
        "ex_15_thick_shell_elform_2 energy error +74.1 % -> -0.9 %, ex_11 "
        "kinetic-energy history error (RMS) 16.07 % -> 1.16 %, "
        "ex_14_solid_elform_2 internal-energy history error 10.56 % -> "
        "2.93 % - but WORSE against the references of a DIFFERENT LS-DYNA "
        "element than the one k2rad emits (ex_14_solid_elform_-1/-2/1, ex_15 "
        "_3/_5). Those history errors are an RMS in % of the reference's "
        "peak; the END state at matched time reads differently - on "
        "ex_15_thick_shell_elform_2 the cap trades internal energy +36.2 % -> "
        "-54.8 % for kinetic energy +132.0 % -> +0.5 %. (The ex_15 figures "
        "are the /PROP/TYPE20 card's, which k2rad wrote before round 7; the "
        "default --implicit-tshell-solid route closes its energy balance by "
        "itself, -0.7 %, and on that routed card the cap takes ex_15 from 34 "
        "to 202 cycles (5.94x), energy error -0.7 % -> -1.8 %, END internal "
        "energy +72.81 % -> -55.94 % and kinetic energy +27.37 % -> +0.12 %, "
        "history RMS IE 8.06 -> 3.19 / KE 9.52 -> 7.45 % of the reference's "
        "peak, nt 4 = nt 2.) On the quasi-static "
        "decks, whose all-zero tolerances now get "
        "LS-DYNA's ECTOL (--zero-tolerance-ectol, default), it costs cycles: "
        "tensile2 75 -> 168 (2.24x), its END internal energy -0.54 % -> "
        "-4.36 % against its reference but its HISTORY the closest of the "
        "four measured arms (RMS 2.48 -> 1.66 % of the reference's peak; the "
        "force criterion alone 2.00, the cap alone 1.83; at t 0.76 / 0.80 "
        "+13 % / +14 % where --zero-tolerance-ectol alone reads -64 % / "
        "+53 %); 4.2.frf.cant-1 70 -> 134 (-0.60 % both), "
        "6.5.tbl.psd.prepressure-1 10 -> 11 (-0.50 % -> -0.62 %), ie_shell "
        "92 -> 124 (-99.87 % -> -99.95 %). The campaign's one constant-step "
        "deck that was a match, ex_11_beam_elform_1, is a deviation at "
        "matched time either way - the shipped run's KE reads +1343 % there "
        "(its match compared t 0.0922 with LS-DYNA's t 0.1: the engine never "
        "prints its last converged increment), the flag's run +17.9 % at t "
        "0.099 (-15.87 % under the retired end-of-run scorer) - while its KE "
        "history error falls 14x. " + _SOLVINFO_HINT)


#: The four initial-velocity registries and the keyword each one is filled
#: from (handlers.py HANDLERS). A spelling that is not one of these four lands
#: in a drop bucket, emits no /INIVEL and needs no engine-defect warning.
_INIVEL_REGISTRIES = (
    ("inivel_nodes", "*INITIAL_VELOCITY_NODE"),
    ("inivel_rbodies", "*INITIAL_VELOCITY_RIGID_BODY"),
    ("inivel_general", "*INITIAL_VELOCITY"),
    ("inivel_generations", "*INITIAL_VELOCITY_GENERATION"),
)


def _warn_implicit_dynamic_initial_velocity(state: ConversionState, imass: int,
                                            gamma: float, beta: float) -> None:
    """An implicit-DYNAMIC deck with an initial velocity: the ENGINE defect,
    measured (R14 triage round 6, B4). Default ON, warning only, 0 bytes.

    Called from the emitter's own branch - where ``/IMPL/DYNA/2`` is written -
    so it fires exactly when the card it describes is in the deck: non-modal,
    implicit, ``*CONTROL_IMPLICIT_DYNAMICS`` IMASS > 0, and one of the four
    registered initial-velocity records. IMASS != 0 holds on 23 R14 keys / 18
    models, two of them MODAL (``tire.k``, ``11.1.sbrake.k``), where the modal
    recipe writes no ``/IMPL/DYNA/2`` and no Newmark step exists to warn about;
    IMASS < 0 (a switching curve) is on 0 keys. Reach: 2 keys / 2 models, the
    ``ex_27_solid_elform_2_rigidwall_*_implicit`` twins, of the 21 keys / 16
    models that emit ``/IMPL/DYNA/2``.

    The warning DESCRIBES THE MEASUREMENT and cites no source line as the
    cause: the faulty line is not isolated. What is known is negative: the
    Newmark cells are not swapped (``lectur.F:3432-3434`` reads NEWM_A >= 1/2
    as gamma and NEWM_B as beta), and the engine special-cases exactly this
    path (``imp_dyna.F`` DYNA_INA's ``IF (NINVEL>0)`` block, INTE_DYNA, and
    ``imp_solv.F:797-807``). A small-DTINI "fix" is deliberately NOT shipped:
    it completes the run with the wrong velocity.
    """
    kws = [kw for attr, kw in _INIVEL_REGISTRIES if getattr(state, attr)]
    if not kws:
        return
    state.warn(
        f"*CONTROL_IMPLICIT_DYNAMICS IMASS={imass} with an initial velocity "
        f"({', '.join(kws)}): this deck runs OpenRadioss's IMPLICIT Newmark "
        f"path (/IMPL/DYNA/2 {gamma:g} {beta:g}) from a non-zero initial "
        "velocity, and that combination was MEASURED to be wrong in the "
        "ENGINE, whatever the converter writes: on the R14 Taylor-bar pair "
        "(ex_27_solid_elform_2_rigidwall_*_implicit), with a first step small "
        "enough to converge (/IMPL/DTINI 1e-8), the bar's momentum at the "
        "first converged increment is exactly -3.0000000 times the initial "
        "one (Z-momentum -2.099317 -> +6.297951, kinetic energy x 9.00000) "
        "and the run ends NORMAL TERMINATION with the bar flying AWAY from "
        "the wall - with the contact deleted, with no wall at all, and with "
        "/INIVEL/AXIS or /INIVEL/TRA alike. That is the free bar: the penalty "
        "twin, and the constrained twin WITHOUT its *CONSTRAINED_GLOBAL plane "
        "(--no-constrained-global); with the plane converted the constrained "
        "twin reads -2.94x (KE x 8.81) at the first time-history sample (t "
        "1.69e-7) and ends with its base held by the plane (Z-momentum "
        "8.8e-4 at t 7.59e-5; nt 4 and nt 2 identical, 72 cycles). With the "
        "deck's own first step the "
        "first increment does not converge, every cut-back restarts from the "
        "corrupted state and the run stops at TIMESTEP LIMIT (on the pair at "
        "nt 4 and nt 2: cycle 3 on the penalty twin, cycle 0 on the "
        "constrained twin with its *CONSTRAINED_GLOBAL plane converted). A "
        "smaller /IMPL/DTINI is therefore NOT a fix: it "
        "trades the error termination for a completed run with the wrong "
        "velocity. Run this model EXPLICIT until the engine is fixed "
        "upstream. " + _SOLVINFO_HINT)


#: LS-DYNA's own *CONTROL_IMPLICIT_SOLUTION card-1 defaults (Vol I R17
#: p.12-354): DCTOL 0.001, ECTOL 0.01, RCTOL 1e10 ("effectively disabled",
#: p.12-362 Remark 5). ECTOL is the one B1 writes; the other two are named.
_LS_DEFAULT_DCTOL = 0.001
_LS_DEFAULT_ECTOL = 0.01


def _warn_zero_tolerance_ectol(state: ConversionState, sol) -> None:
    """One warning per deck: the stated-zero ``*CONTROL_IMPLICIT_SOLUTION``
    got LS-DYNA's own ECTOL default (R14 triage round 6, B1).

    Facts only, and every figure here is a measurement on the R14 roster at
    nt 4 AND nt 2 (identical final state and cycle count on every pair).
    The rule rests on the reference d3hsp echo, NOT on a measured
    improvement: post-review round of #140, the internal-energy HISTORY of the
    11 carriers (RMS over the reference's glstat times, in % of its peak) is
    closer to LS-DYNA on 3 by at most 0.03 points, unchanged on 3, farther on
    4 (ie_shell a status change) - tensile2's -0.54 % END value is a
    coincidence of a
    history that reads -64 % at t 0.76 and +53 % at t 0.80. A cell stated
    >= 1 beside the zeros is LS-DYNA's own value, not its default, and is
    named: only a stated ECTOL changes what LS-DYNA would run against the
    Toli written here (a DCTOL is not carried anyway, and RCTOL >= 1 is
    LS-DYNA's own "criterion disabled", p.12-362 Remark 5).
    """
    stated = ""
    if sol.ectol >= 1.0:
        stated = (
            f" This card STATES ECTOL={sol.ectol:g}: that is LS-DYNA's own "
            "value, not its default, and a relative tolerance >= 1 is not "
            "carried (the warning above), so the Toli 0.01 written here is "
            f"NOT the energy tolerance LS-DYNA runs on this card "
            f"({sol.ectol:g}).")
    state.warn(
        "*CONTROL_IMPLICIT_SOLUTION states no usable convergence tolerance "
        f"(DCTOL={sol.dctol:g}, ECTOL={sol.ectol:g}, RCTOL={sol.rctol:g}: "
        "none lies in (0, 1)). LS-DYNA runs a 0.0 or blank cell of this card "
        "on its OWN default - every one of the 11 R14 reference d3hsp files "
        "of this shape (all three cells 0.0 or blank) echoes 'displacement "
        "convergence tolerance 0.1000E-02', 'energy convergence tolerance "
        "0.1000E-01' and 'residual convergence tolerance 0.9990E+11' (Vol I "
        "R17 p.12-354: DCTOL 0.001, ECTOL 0.01, RCTOL 1e10), although the "
        "keyword's header (p.12-353) says a stated 0 means zero. k2rad "
        "therefore writes LS-DYNA's ENERGY criterion, /IMPL/NONLIN/1 Itol 1, "
        "Toli 0.01, instead of its own force default (Itol 2, Toli 0.01) - "
        "because it is the criterion LS-DYNA runs, NOT because it was "
        "measured closer." + stated + " DCTOL is NOT carried: LS-DYNA "
        "measures it against the TOTAL displacement (DNORM 2) and no "
        "/IMPL/NONLIN Itol offers that norm (nl_solv.F:410-421 is per step); "
        "the combined Itol 13 was measured to end 3 of 3 NORMAL quasi-static "
        "R14 decks in ERROR. MEASURED on the 11 R14 decks of this shape at "
        "nt 4 and nt 2 (identical): NORMAL kept on all 10 that were NORMAL; "
        "the internal-energy HISTORY (RMS over the reference's output times, "
        "in % of its peak) is closer to the reference on 3 of the 11 by at "
        "most 0.03 points (rigid_tip 0.78 -> 0.75; aellipse and ellipse by "
        "less than 0.01), unchanged on 3 (tensile1, bumper, "
        "6.4.tbl.psd.thermal-1) and farther on 4 - tensile2 2.00 -> 2.48, "
        "doorbeam 189 -> 393, 4.2.frf.cant-1 0.30 -> 0.59, "
        "6.5.tbl.psd.prepressure-1 0.03 -> 0.39 - and ie_shell's is a status "
        "change (below). tensile2's "
        "END value reads +7.36 % -> -0.54 % at 0.11x the cycles, a "
        "coincidence of its history: at t 0.76 / 0.80 the run reads -64 % / "
        "+53 % where the force criterion reads +18 % / +14 %. doorbeam reads "
        "+380.25 % -> +582.00 % at the end and +668 / +1086 / +973 / +842 % "
        "at the four earlier fifths of the run where the force criterion "
        "reads +476 / +353 / +361 / +349 % (a springback deck already ~5x "
        "off its reference - a named regression, larger mid-run); ie_shell "
        "ERROR (TIMESTEP LIMIT at cycle 4) -> NORMAL in 92 cycles, but at IE "
        "-99.87 % and KE 0 against the reference's 149.9 - a STATUS change "
        "only, measured on the ONE implicit engine file that "
        "--no-imflag-curve-restart still writes; by default (round 8, h.3) "
        "its IMFLAG -9 implicit/explicit switching curve converts as a "
        "two-engine-file chain (18 implicit + 11 127 explicit cycles, END IE "
        "-4.54 %, RMS IE 12.07 % of the LS peak over 320 LS times). "
        "--no-zero-tolerance-ectol restores the force default.")


def _make_engine_implicit(state: ConversionState) -> List[str]:
    # The two "what this deck asked for and did not get" warnings run for BOTH
    # implicit shapes. They used to sit below the modal early return, so a
    # /EIG deck was told nothing: MEASURED, ex_08_beam_elform_{1,2,13} state
    # *CONTROL_IMPLICIT_AUTO IAUTO 1 / ITEWIN 15 beside
    # *CONTROL_IMPLICIT_EIGENVALUE and got no drop warning at all, though the
    # modal recipe ignores those cells exactly as /IMPL/DT/2 does. Each warning
    # is told which shape it is on, so neither names a card the deck will not
    # carry.
    # round 8, B3 (h.2): under --imflag-curve-restart the warnings run on the
    # FIRST implicit segment only (once per deck), and an explicit segment
    # gets no /IMPL block
    seg = state.engine_segment
    if (state.is_modal or state.is_implicit) and (
            seg is None or seg.first_implicit):
        if _arclength_requested(state):
            _warn_arclength(state, modal=state.is_modal)
        _warn_implicit_bfgs(state)
        _warn_implicit_auto_drops(state, modal=state.is_modal)
        _warn_implicit_constant_step(state)
    if state.is_modal:
        # Normal-modes (/EIG) → one-shot linear eigensolve, not the QSTAT/NONLIN
        # time-marching engine below.
        return _make_engine_modal(state)
    if not _engine_implicit(state):
        return []
    dyn  = state.ctrl_implicit_dyn
    auto = state.ctrl_implicit_auto
    iteopt = auto.iteopt if auto else 0

    # For dynamic implicit with rigid bodies that have free DOFs (only contact-
    # constrained), the K_eff = K + M/(β·Δt²) needs a small Δt for the mass
    # contribution to stabilize the matrix. LS-DYNA's DT0=0.05 is too large
    # for OpenRadioss's MUMPS direct solver on this large model (568k DOFs)
    # with tiny rigid-body masses (~0.27 g). Use a much smaller initial step
    # so M/(β·Δt²) provides ~2500× more stabilization. The auto time-step
    # control (/IMPL/DT/2) will grow Δt back up as iterations converge.
    # (The computation is _implicit_dtini_dtmin: one place, shared with the
    # constant-step sentence and the --implicit-constant-step scope, which
    # replaces DT_MAX by the deck's own DT0 inside its scope - round 6, B3.)
    dt0, dtmin, dtmax = _implicit_step_cells(state)

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
    #
    # A card whose three tolerances are ALL 0.0 / blank (or >= 1) gets
    # LS-DYNA's own ECTOL default, Itol 1 / Toli 0.01 (round 6, B1; default
    # ON, --no-zero-tolerance-ectol): every R14 reference d3hsp of that shape
    # echoes DCTOL 0.001 / ECTOL 0.01 / RCTOL 0.999e11 - LS-DYNA applies its
    # defaults to the stated zeros. L_A is NOT touched: the rule is scoped to
    # the tolerance cell and the documented rigid-contact 2 above stays.
    # L_A 11 (LS-DYNA's ILIMIT default) was measured beside it at nt 4 and 2
    # and is MIXED, not better or worse: closer to LS-DYNA on 4 of the 11
    # carriers (tensile2, 6.5.tbl.psd, doorbeam, rigid_tip), farther on 4
    # (4.2.frf, ellipse, aellipse, ie_shell), identical on 3, at up to 1.8x
    # the cycles. A NEGATIVE cell is a tolerance CURVE id (Vol I R17 p.12-355
    # "LT.0: -XCTOL references a curve"), not a stated zero: it keeps the
    # force default and is named as dropped (reach 0 of the 112 parsed
    # roster cards). A deck with NO card keeps "2 2 0.01" - its one roster
    # carrier, nvh/example-11-02/11.3.sqt_iga_s.k, is a refused conversion
    # with no elements.
    sol = state.ctrl_implicit_sol
    l_a, itol, toli = 2, 2, 0.01
    zero_tol_ectol = False
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
        elif (state.options.zero_tolerance_ectol
              and min(sol.rctol, sol.ectol, sol.dctol) >= 0.0):
            # B1: no usable tolerance, and none of the three is a curve id
            itol, toli = 1, _LS_DEFAULT_ECTOL
            zero_tol_ectol = True
        for name, val in (("rctol", sol.rctol), ("ectol", sol.ectol), ("dctol", sol.dctol)):
            if val and val >= 1.0:
                state.warn(
                    f"*CONTROL_IMPLICIT_SOLUTION {name}={val:g} is >= 1.0 (not a valid "
                    "relative tolerance); ignored. rctol=1e10 is LS-DYNA's own "
                    "'criterion disabled' idiom (Vol I R17 p.12-362 Remark 5: "
                    "'By default, residual norm ratio (RCTOL) criterion is "
                    "effectively disabled (RCTOL = 10^10)') and is the usual "
                    "reason on this corpus - 15 of the 34 implicit R14 decks; "
                    "an all-blank leading card shifting the fixed-format "
                    "columns is the other reading, worth a look if the value "
                    "is not 1e10. "
                    + ("Using LS-DYNA's own ECTOL default instead (Itol 1, "
                       "Toli 0.01; see the warning below)."
                       if zero_tol_ectol else
                       f"Using robust /IMPL/NONLIN default Toli={toli:g}."))
        for name, val in (("rctol", sol.rctol), ("ectol", sol.ectol), ("dctol", sol.dctol)):
            if val < 0.0:
                # reach 0 of the 112 parsed roster cards; a probe pins it
                state.warn(
                    f"*CONTROL_IMPLICIT_SOLUTION {name.upper()}={val:g} is "
                    "NEGATIVE, i.e. Vol I R17 p.12-355's 'LT.0: "
                    f"-{name.upper()} references a curve that defines "
                    "tolerance as a function of time'. The curve is DROPPED: "
                    "/IMPL/NONLIN takes one constant tolerance, here "
                    f"Itol {itol}, Toli {toli:g}.")
        if zero_tol_ectol:
            _warn_zero_tolerance_ectol(state, sol)
    # round 9, A12 (opt-in): /IMPL/NONLIN/2 = Quasi-Newton BFGS
    nonlin = 2 if _bfgs_requested(state) else 1
    lines: List[str] = [f"/IMPL/NONLIN/{nonlin}", "# L_A Itol Toli",
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
        # The engine defect on this path with an initial velocity (round 6,
        # B4) - warned here, in the branch that writes the card it is about.
        _warn_implicit_dynamic_initial_velocity(state, dyn.imass, gamma, beta)
    else:
        # /IMPL/QSTAT/DTSCAL: the inertia-stabilization scale. imp_dyna.F:351
        # builds S = (1+D_AL)*DY_B*DT2*DT2, :353 multiplies it by SCAL_DTQ^2
        # and :355 takes BDT = 1/S, so the stabilization added to the stiffness
        # diagonal is M/((1+alpha)*beta*(DTSCAL*dt)^2) — it grows as 1/DTSCAL^2
        # AND as 1/dt^2. Radioss's own default is SCAL_DTQ = 1
        # (freimpl.F:135), and imp_dyna.F:1148 returns immediately at that
        # value; k2rad shipped 0.1 (= 100x the default) until 2026-09, which
        # made every auto-step cut stiffen the tangent further and shrink the
        # next Newton correction instead of letting the step recover.
        #
        # The value now comes from options.qstat_dtscal (default 10, CLI
        # --qstat-dtscal), and "none" emits no /IMPL/QSTAT card at all. See
        # state.ConvertOptions.qstat_dtscal for the measured arms: 4.2.frf,
        # tensile2, 6.5.tbl.psd and doorbeam move error_engine -> normal, at
        # the cost of the ex_02_thick_shell_elform_{2,3,5} family (3 keys on
        # one emitted file, all three not_comparable both ways) going
        # normal -> timeout on the /PROP/TYPE20 card k2rad wrote before round
        # 7 (round 7's default /PROP/SOLID route, writer/tshell.py, ends the
        # family NORMAL in 28 cycles at this default, and at 0.1 too - the
        # value is inert on the routed card); --qstat-dtscal 0.1 with
        # --no-implicit-tshell-solid reproduces the pre-round-4 file byte for
        # byte on that family (0.1 alone does not since round 7).
        #
        # The deformable-deformable contact recipe keeps 0.05 (=> x400) and
        # IGNORES the option: a compliant contact under force control adds a
        # soft mode that 0.1 leaves a step-overshoot 2-cycle on, while 0.01
        # over-damps and freezes the solve; 0.05 anchors it without
        # over-stiffening the tangent. Separately validated, opt-in, and it is
        # evaluated FIRST so --qstat-dtscal cannot override it. See
        # _warn_deformable_deformable_contact.
        if _recipe_active(state):
            lines += ["/IMPL/QSTAT/DTSCAL", " 0.05"]
        elif (((state.options.arclength_riks
                and _arclength_requested(state))
               or _bfgs_requested(state))
              and not state.options.qstat_dtscal_stated):
            # R14 triage round 9, A11: --arclength-riks writes NO quasi-
            # static term unless --qstat-dtscal was GIVEN - it adds
            # M/((1+alpha)*beta*(DTSCAL*dt)^2) to the diagonal
            # (imp_dyna.F:351-355), i.e. stiffens the arc-length tangent,
            # and the engine has no QSTAT-versus-RIKS guard
            # (lectur.F:3517-3532 disarms only FIXPOINT). The recipe above
            # is evaluated first and keeps its 0.05. Round 9, A12: the
            # --implicit-bfgs pair is measured WITHOUT the term too.
            pass
        else:
            dtscal = _qstat_dtscal_cell(state)
            if dtscal is not None:
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
    if _arclength_requested(state) and state.options.arclength_riks:
        # /IMPL/DT/3 — RIKS arc-length continuation, LS-DYNA's NSOLVR 6-9 /
        # ARCCTL. freimpl.F:377 stores IDTC = IM and :384-387 READs SEVEN
        # list-directed fields from ONE record:
        #     NL_DTP ALEN0 NL_DTN SCAL_DTN SCAL_DTP IAL_M SCAL_RIKS
        # /IMPL/DT/2's data line is only FIVE, so a five-field line would run
        # the READ off the end of the record. The four zeros and the two extra
        # cells take lectur.F:3518-3522's own defaults (NL_DTP 12, NL_DTN 25,
        # SCAL_DTN 2/3, SCAL_DTP 1.2, IAL_M 2) — which is exactly what the
        # measurement used. It_w (from *CONTROL_IMPLICIT_AUTO ITEOPT) and the
        # recipe's L_dtn keep their slots.
        lines += ["/IMPL/DT/3",
                  f"{_i(it_w)}{_i(0)}{_i(l_dtn)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}"]
    else:
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
    # options.fixpoint_count; we clamp it to the engine's 1…100 range here, and
    # 0 disables the card.
    #
    # OFF BY DEFAULT since 2026-09 (options.fixpoint_count 100 → 0). This is a
    # k2rad convenience LS-DYNA never asks for, and the milestone grid is not
    # free: it makes the adaptive step oscillate against /IMPL/DT/2, and
    # trapezoidal Newmark (/IMPL/DYNA/2, γ = 0.5, β = 0.25) is unconditionally
    # stable at a CONSTANT step, not at one that alternates 2 : 1 every cycle.
    # MEASURED on the dynaexamples R14 roster, ten implicit decks that died
    # "** ERROR: SOLVER IMPLICIT STOPPED DUE TO TIMESTEP LIMIT **"
    # (imp_solv.F:2031, ISTOP = -2) reach NORMAL TERMINATION once the card is
    # gone — ex_01 x3 at cycle 20, ex_14 x4 at cycle 33, ex_15 x3 at cycle 38,
    # each family dying at an identical cycle, i.e. one mechanism per family.
    # See state.ConvertOptions.fixpoint_count for the numbers and for the eight
    # other arms that do NOT fix ex_14.
    n_fix = min(max(int(state.options.fixpoint_count), 0), 100)
    if n_fix > 0 and _arclength_requested(state) and state.options.arclength_riks:
        # Not a k2rad choice: lectur.F:3523-3532 prints "** WARNING :RIKS
        # METHOD IS NOT COMPATIBLE WITH FIXED TIME POINT" and sets NDTFIX = 0
        # itself, so the card would be read and then thrown away. Dropping it
        # here says so in the log instead of leaving the reader to find the
        # engine's own line.
        n_fix = 0
        state.warn(
            "--fixpoint-count is DISARMED on this deck: --arclength-riks "
            "emitted /IMPL/DT/3, and lectur.F:3523-3532 deactivates "
            "/IMPL/DT/FIXPOINT under RIKS (it prints '** WARNING :RIKS METHOD "
            "IS NOT COMPATIBLE WITH FIXED TIME POINT' and sets NDTFIX = 0). No "
            "/IMPL/DT/FIXPOINT is written.")
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


def _sample_implicit_smooth_curves(state: ConversionState) -> None:
    """R14 triage round 8, B2: on an IMPLICIT, non-modal deck every
    well-formed ``*DEFINE_CURVE_SMOOTH`` (``state.smooth_curve_params``) is
    re-sampled as a sine ramp (``handlers.sampled_smooth_points``) and loses
    its ``/FUNCT_SMOOTH`` flag, so every emitter (``_make_functions``,
    ``_emit_funct``, the FGEO BIRTH copy) writes a plain ``/FUNCT`` under the
    same id: the implicit imposed-motion path reads a curve's points
    piecewise-linearly whatever the flag (``fv_imp0.F:209`` -> ``:333``
    DINTERI). Explicit and modal decks, a degenerate shape and
    ``--no-implicit-smooth-curve-sampling`` keep today's /FUNCT_SMOOTH.
    Idempotent (``state.smooth_curves_sampled``)."""
    if state.smooth_curves_sampled:
        return
    state.smooth_curves_sampled = True
    if (not state.options.implicit_smooth_curve_sampling
            or not state.is_implicit or state.is_modal):
        return
    from ..handlers import sampled_smooth_points, smooth_sampling_sentence
    term = state.ctrl_termination
    endtim = term.endtim if term is not None else None
    for lcid in sorted(state.funct_smooth_ids):     # sorted() = a copy
        params = state.smooth_curve_params.get(lcid)
        curve = state.curves.get(lcid)
        if params is None or curve is None:
            continue
        tstart, trise, tend, vmax = params
        curve.pts = sampled_smooth_points(tstart, trise, tend, vmax, endtim)
        state.funct_smooth_ids.discard(lcid)
        state.warn(smooth_sampling_sentence(
            lcid, len(curve.pts), vmax * (tend - tstart - trise)))


def _merge_cnrb_records(state: ConversionState, rbody_info: Dict,
                        cnrb_info: Dict) -> Dict:
    """Merge the *CONSTRAINED_NODAL_RIGID_BODY records into ``rbody_info``.

    The two dicts are keyed by DIFFERENT id namespaces - *MAT_RIGID records by
    PART id, CNRB records by the CNRB's own PID - so a CNRB whose PID equals a
    rigid part's id collides with that part's record. LS-DYNA accepts the
    shared id with ``*** Warning 10177 (KEY+177)`` ('nodal rigid body and part
    share the same ID', doorbeam.d3hsp:1040-1041) and drives the PART;
    dyna2rad does the same by write order (``ConvertEntities`` calls
    ``ConvertConstrainedNodalRbodies`` before ``ConvertMatsRigid``,
    convertrigids.cxx:37-50, and the part overwrites the CNRB's entry of
    ``storeRbodyPIDVsMasterNode``, :145 / :238).

    round 9, A1 (``--rigid-part-pid-precedence``, default ON): on a clash the
    part record keeps its key and position, so every part-keyed consumer
    (prescribed motion and its /TH rows, *LOAD_RIGID_BODY, the rigid-body
    initial velocities, gravity, /BCS, /TH) addresses the PART's /RBODY; the
    CNRB record is filed under the SHADOW key ``-pid`` (its ``kind`` stays
    "cnrb"), so the value-iterating consumers (the node -> main maps of /BCS
    and /TH, gravity's CNRB scope, the bolt-end screen) keep BOTH bodies and
    the CNRB's own _INERTIA velocity still finds it through
    ``state.cnrb_record_key``. No clash: ``{**rbody_info, **cnrb_info}``, the
    386444e merge exactly. ``--no-rigid-part-pid-precedence`` keeps the
    386444e merge (the CNRB record replaces the part's) and its sentence.
    """
    clash = sorted(set(rbody_info) & set(cnrb_info))
    if not clash or not state.options.rigid_part_pid_precedence:
        state.cnrb_record_key = {}
        for _dup in clash:
            state.warn(
                f"*CONSTRAINED_NODAL_RIGID_BODY PID {_dup} collides with the "
                "id of a *MAT_RIGID part that k2rad also turned into an "
                "/RBODY. The CNRB record wins, so cards keyed on that part id "
                "(gravity groups, /BCS, /INIVEL, /TH) address the CNRB's main "
                "node and the rigid PART's own main node is not reached - give "
                "the CNRB an unused part id.")
        return {**rbody_info, **cnrb_info}
    state.cnrb_record_key = {pid: -pid for pid in clash}
    merged = dict(rbody_info)
    for pid, info in cnrb_info.items():
        merged[-pid if pid in rbody_info else pid] = info
    for pid in clash:
        state.warn(
            f"*CONSTRAINED_NODAL_RIGID_BODY PID {pid} collides with the id of "
            "a *MAT_RIGID part that k2rad also turned into an /RBODY. LS-DYNA "
            "accepts the shared id with Warning 10177 ('nodal rigid body and "
            "part share the same ID') and drives the PART; dyna2rad does the "
            "same by write order (convertrigids.cxx:37-50, :145, :238). So "
            "the part-keyed cards (*BOUNDARY_PRESCRIBED_MOTION_RIGID[_LOCAL] "
            "and its /TH reaction rows, *LOAD_RIGID_BODY, "
            "*INITIAL_VELOCITY_RIGID_BODY / _GENERATION, gravity, /BCS, /TH) "
            f"address the PART's /RBODY main node {rbody_info[pid]['ind_node']}; "
            f"the CNRB keeps its own /RBODY {cnrb_info[pid]['ind_node']} (its "
            "_INERTIA velocity and _SPC stay on it). Before round 9 the CNRB "
            "record replaced the part's: on "
            "implicit/basic-examples/springback-i/doorbeam.k the driven punch "
            "never moved (DY 0 at every fifth of t_end against LS-DYNA's 135 "
            "mm) and internal energy ended +582.00 % against LS-DYNA (RMS "
            "393.31 % of the LS peak over the 25 LS times in (1e-5, 1.1e-3]); "
            "the part drive alone brings it to +53.91 % (RMS 81.05 %, nt 4 = "
            "nt 2) and the shipped default - with the implicit "
            "node-to-surface route of --implicit-n2s-type7 - to -0.78 .. "
            "-28.12 % (RMS 7.21 .. 15.26 %, 125 runs at nt 4 and nt 2, run to "
            "run on three branches), the punch then following LS-DYNA's "
            "nodout at every fifth. "
            "--no-rigid-part-pid-precedence restores the CNRB precedence.")
    return merged


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
    # *CONSTRAINED_GLOBAL -> the per-node TC/RC union (round 6, B5): here, on
    # the deck's OWN nodes, before any prepass synthesizes one (the model
    # extent that sets the default tolerance and the candidate nodes must not
    # include k2rad's artefacts).
    _resolve_constrained_globals(state)
    # *SET_<FAMILY>_ADD → plain sets of that family (recursively), BEFORE
    # anything reads state.part_sets / node_sets / the element and segment set
    # containers (contact sides, *CONTACT_INTERIOR, gravity/ALE scopes, /BCS,
    # /RBODY, /RWALL scopes, /SECT groups, /TH channels, /PLOAD surfaces) and
    # before the tet10->tet4 node-set prune, which mutates state.node_sets.
    # Idempotent — convert() already ran it so --auto-gapmin sees the
    # flattened sets; this covers direct build_starter callers.
    #
    # The *SET_<F>_GENERATE / _GENERAL ranges and OPTION clauses expand FIRST,
    # in the same slot and for the same four reasons: an _ADD member may be a
    # _GENERATE sid, the id allocators below dodge whatever is in the set
    # containers, and the tet10->tet4 prune (further down) mutates node_sets.
    _expand_set_ranges_and_generals(state)
    _flatten_set_adds(state)
    # Round 9, B2: the axisymmetric 2-D route decision, BEFORE any writer -
    # the rigid-body writer skips its J = -SUM(IN) correction on a routed
    # deck and the section sentences read it. Reads the parsed deck only,
    # draws no id; a deck with no ELFORM 14 / 15 section (or the opt-out)
    # gets an empty plan and nothing below changes.
    resolve_axisym_plan(state)
    # R14 triage round 8, B2: an implicit deck's *DEFINE_CURVE_SMOOTH -> a
    # sampled sine /FUNCT, before any emitter reads funct_smooth_ids.
    _sample_implicit_smooth_curves(state)
    _resolve_define_tables(state)
    # R14 triage round 9, A7: on a MODAL deck a *PART on a refused
    # *MAT_ACOUSTIC gets /MAT/VOID with the acoustic density. FIRST of the
    # material passes, because it moves the mid out of refused_materials and
    # into what _target_mat_law answers (law 0) — every later reader of
    # either must see the resolved state. Emits nothing and draws no id.
    _resolve_modal_acoustic_void(state)
    _resolve_mat_plas_tab(state)
    _resolve_mat_power_law(state)
    # Johnson-Cook LAW2/LAW4 routing (needs the *PART EOSID bindings) + the
    # DTF → /FAIL/GENE1 dtmin injection — before _make_materials emits.
    _resolve_mat_johnson_cook(state)
    # *EOS_GRUNEISEN A = 0 -> a tiny positive a, BEFORE any of the six
    # _emit_eos call sites (three of which copy the params dict onto a new
    # EosCard) can read the cell. Idempotent: the guard is `a == 0`.
    _resolve_eos_gruneisen_a(state)
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

    # R14 triage batch: the /MAT/LAW5 Bunreacted cell. Needs the flattened
    # part sets (for the *ALE_MULTI-MATERIAL_GROUP membership test) and must
    # precede _make_materials, whose _emit_mat_law5 writes the cell. Emits
    # nothing and draws no id.
    _resolve_he_bunreacted(state)

    # R14 triage batch: the /MAT/LAW51 phase list. It reads the EMITTED law of
    # every member (_target_mat_law) and whether that material carries an
    # /EOS, so it must run after every _resolve_mat_* pass above and before
    # _make_materials, whose _make_ale_multimaterial writes the list this
    # decides. It synthesizes no card and draws no id.
    _resolve_ale_submaterials(state)

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
    #
    # Round 9, B1: the *BOUNDARY_THERMAL_WELD_TRAJECTORY screen + deposit
    # plan runs FIRST - an accepted card's *MAT_THERMAL_CWM becomes a TD_LC
    # record that _resolve_thermal's stand-in and /HEAT/MAT passes read, and
    # its one shared unit /FUNCT must exist before _make_functions. It draws
    # that /FUNCT's id only when a card is ACCEPTED (the /GRBRIC + /IMPFLUX
    # ids come at emission), so a refused deck keeps the opt-out's bytes; it
    # does nothing on a deck without a trajectory or under the opt-out.
    _resolve_weld_trajectories(state)
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

    # RO <= 0 -> rho = 1e-24 (starter ERROR 683). LAST of the material passes,
    # deliberately: it screens on mesh._target_mat_law, so every routing
    # decision above (LAW2-vs-LAW4, LAW19-vs-LAW58, the LAW51 phase list, the
    # /MAT/VOID exemption) must already be final, and _resolve_thermal above
    # can CLONE a material — a clone made before this pass inherits the zero
    # and is floored with its original, one made after would not be. It
    # mutates the RECORD rather than the emitted cell, which is the faithful
    # model of what LS-DYNA does: its own d3hsp reports the substituted
    # density in the part MASS, so the element time step, /HEAT/MAT's RHO0_CP
    # and the modal chain's lumped masses all see the same number. Allocates
    # no id, so it cannot shift an existing deck's id stream.
    _apply_zero_density_floor(state)

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

    # --spotweld-node-synthesis (round 6, B6 rule 1): the second node of a
    # one-node ELFORM-9 *MAT_SPOTWELD beam, before the /NODE section and before
    # the tied / spotweld sections that name it. A no-op without the flag.
    _synthesize_spotweld_second_nodes(state)

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

    # *CONSTRAINED_JOINT_SCREW -> /GJOINT/RACK (round 7, B2): the ONE decision
    # over every screw, BEFORE the /RBODY producers (which skip the bodies'
    # CMO /BCS and build the carriage from it) and before the contact section
    # (which splits the pair out of an all-parts self-contact). Draws no id.
    _resolve_joint_screws(state)

    # *CONSTRAINED_SHELL_IN_SOLID -> /INTER/TYPE18 under
    # --shell-in-solid-coupling (round 8, B10): the ONE decision, BEFORE the
    # materials (the void density cells) and the parts (a copy MID). Draws
    # no id unless a void host shares its *MAT_NULL; empty by default.
    _resolve_shell_in_solid(state)

    # *ELEMENT_DISCRETE, MAT_100 spotweld beams and *ELEMENT_PLOTEL all become
    # /SPRING under their SOURCE-deck ids, which LS-DYNA keeps in three separate
    # namespaces and Radioss in one. Report the overlap here rather than letting
    # the starter be the first to mention it (ERROR 79, no restart file).
    _warn_spring_eid_collisions(state)

    rbody_lines, rigid_nodes, rbody_info = _make_rbodies(state)
    # round 9, A1 (--rigid-part-pid-precedence): the CNRB pids that collide
    # with a rigid PART record, known BEFORE _make_cnrb_rbodies runs - it
    # leaves such a part's _LOCAL triad nodes and *ELEMENT_MASS_PART to the
    # part (rbody.py), and the merge below files the CNRB record under the
    # shadow key -pid. Always empty under --no-rigid-part-pid-precedence.
    state.cnrb_record_key = {}
    if state.options.rigid_part_pid_precedence:
        state.cnrb_record_key = {
            c.pid: -c.pid for c in state.cnrbs if c.pid in rbody_info}
    # *CONSTRAINED_NODAL_RIGID_BODY produces additional /RBODY entries that must
    # be visible to every rigid-body-keyed section below, so merge their info,
    # rigid-node set, and rad lines with the *MAT_RIGID ones.
    cnrb_lines, cnrb_rigid_nodes, cnrb_info = _make_cnrb_rbodies(state)
    rigid_nodes = rigid_nodes | cnrb_rigid_nodes
    rbody_info = _merge_cnrb_records(state, rbody_info, cnrb_info)
    rbody_lines = rbody_lines + cnrb_lines
    # *CONSTRAINED_SHELL_TO_SOLID and *CONSTRAINED_GENERALIZED_WELD_BUTT:
    # /RBODY producers 4 and 5, appended before the probe body.
    #
    # They contribute NEITHER an rbody_info record NOR members to
    # `rigid_nodes`, and both halves are the same reason. rbody_info is keyed
    # by LS-DYNA PART id and consumed by *LOAD_RIGID_BODY /
    # *BOUNDARY_PRESCRIBED_MOTION_RIGID / *INITIAL_VELOCITY_RIGID_BODY; a tie
    # or a weld has no part id, so it cannot have a record — and every
    # `rigid_nodes` consumer that matters here (the *NODE TC/RC re-point
    # first) resolves a member through rbody_info and DROPS it when the lookup
    # fails. MEASURED on constrained.shell_solid.dome: registering the tied
    # nodes cost 12 of the deck's 132 stated TC/RC constraints, silently, so
    # they are left out. See _make_shell_to_solid_rbodies' docstring.
    rbody_lines = rbody_lines + _make_shell_to_solid_rbodies(state)
    rbody_lines = rbody_lines + _make_generalized_weld_butt_rbodies(state)
    # Implicit deck without any rigid body: the engine segfaults at solver init
    # (MESSAGE ID 44) — give it an inert fully-fixed probe rigid body.
    rbody_lines = rbody_lines + _make_probe_rbody(state, rbody_info)
    # /RBODY producer 6: the carriage of every converted *CONSTRAINED_JOINT_
    # SCREW (round 7, B2) - after the probe, its nodes registered in
    # state.nodes before the /NODE section is written. A no-op (no id
    # drawn) on any deck without a converted screw.
    rbody_lines = rbody_lines + _make_screw_carriage_rbodies(state, rbody_info)
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
    # round 8, A2 (l)-2 (--bolt-rigid-contact, default ON): the members of a
    # rigid body holding an end node of an *INITIAL_AXIAL_FORCE_BEAM bolt stay
    # on every PENALTY contact's secondary side - the three builders below
    # read ctx.contact_rigid_nodes; the TYPE2 family and the force
    # transducers keep the full rigid set (decision D5). Computed once, after
    # the rigid bodies are merged, before any interface is built.
    state.bolt_rigid_keep = {}
    state.bolt_kept_by_side = {}
    # --mass-weighted-inivel's one-pair-per-body record is a PER-BUILD
    # registry (the round-8 post-review verification): a second build of the
    # same state must emit its own first pair, not sum into the last build's
    state.mass_weighted_pairs = {}
    contact_rigid_nodes = rigid_nodes
    if state.options.bolt_rigid_contact:
        state.bolt_rigid_keep = _bolt_end_rigid_members(state, rbody_info)
        if state.bolt_rigid_keep:
            contact_rigid_nodes = rigid_nodes - set(state.bolt_rigid_keep)
    ctx = _StarterContext(state, rbody_info, rigid_nodes, rbody_lines, _rep,
                          contact_rigid_nodes)
    lines: List[str] = []
    ctx.lines = lines
    for _name, builder in _starter_section_registry():
        lines.extend(builder(ctx))
    # --mass-weighted-inivel: ONE /INIVEL/TRA + /ROT pair per /RBODY main
    # node - a body partly covered by several velocity groups / cards gets
    # the SUM of its momentum shares in the first pair written on it (the
    # starter overwrites a node's velocity card by card; round-8 post-review
    # verification). A post-pass because the shares can come from three
    # sections; content-asserted, it rewrites two rows per such body and
    # draws no id. A no-op without the flag.
    _merge_mass_weighted_pairs(state, lines)
    # --mass-weighted-inivel: J = -SUM(IN) on the /RBODY blocks the inivel
    # sections re-pointed (round 6, A7) - since round 7 only where the
    # *MAT_RIGID producer did not already write it by default (A2; the
    # pass skips a record whose j_in is "applied" or "refused", and never
    # touches a CNRB). A post-pass because those blocks are
    # built above, before the re-point is decided; id-keyed and
    # content-asserted, it rewrites one J row per body and draws no id. A
    # no-op without the flag.
    _apply_mass_weighted_rbody_inertia(state, lines, rbody_info)
    # --beam-contact-secondary with nothing gained: say so once (round 6, B6)
    _warn_beam_contact_secondary_unused(state)
    _pad_surfaces_for_spmd_th_surf(state, lines)
    _warn_duplicate_th_group_ids(state, lines)
    _warn_duplicate_prop_ids(state, lines)
    _warn_duplicate_mat_ids(state, lines)
    _warn_duplicate_eos_ids(state, lines)
    _warn_duplicate_group_ids(state, lines)
    _warn_duplicate_thermal_ids(state, lines)
    _warn_duplicate_thermal_bc_ids(state, lines)
    _warn_duplicate_preload_ids(state, lines)
    _warn_duplicate_sect_ids(state, lines)
    _warn_duplicate_function_ids(state, lines)
    _warn_duplicate_impdisp_ids(state, lines)
    _warn_duplicate_inter_ids(state, lines)
    _warn_dangling_part_materials(state, lines)
    # Round 9, B4 (--shell-in-solid-coupling): the re-tune is decided once
    # every interface is written - Gap 0.55 + /DT/INTER/CST only on a deck
    # that is the SIS problem alone, else the round-8 form; it rewrites the
    # Gap cell of its own TYPE18 rows and draws no id. A no-op without a
    # converted card.
    lines = finalize_shell_in_solid(state, lines)
    # Round 9, B2: the 2-D axisymmetric route is ONE post-pass on the emitted
    # lines (decision B2-a) - every 3-D writer above ran as before, so a deck
    # that is not routed (or the opt-out) is byte-identical by construction.
    lines = transform_starter_lines(state, lines)
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
    # convert() (k2rad/__init__.py, step 3) calls build_starter before
    # build_engines, so the count is set by the time _make_engine_output
    # reads it.
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
    __slots__ = ("state", "rbody_info", "rigid_nodes", "rbody_lines", "rep",
                 "contact_rigid_nodes", "lines")

    def __init__(self, state, rbody_info, rigid_nodes, rbody_lines, rep,
                 contact_rigid_nodes=None):
        self.state = state
        self.rbody_info = rbody_info
        self.rigid_nodes = rigid_nodes
        self.rbody_lines = rbody_lines
        self.rep = rep
        # round 8, A2 (l)-2: the rigid set the PENALTY contact builders filter
        # a secondary side by (rigid_nodes minus the bolt-end bodies' members)
        self.contact_rigid_nodes = (rigid_nodes if contact_rigid_nodes is None
                                    else contact_rigid_nodes)
        # round 8, A5: the starter lines accumulated so far (build_starter
        # binds its list here) - the adaptive spring token rewrites the
        # token /PROP MASS cells the connector sections emitted earlier
        self.lines = None


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
        ("interfaces",        lambda c: _make_interfaces(c.state,
                                                     c.contact_rigid_nodes)),
        ("general_interfaces", lambda c: _make_general_interfaces(
            c.state, c.contact_rigid_nodes)),
        ("type25_interfaces", lambda c: _make_type25_interfaces(
            c.state, c.contact_rigid_nodes)),
        # Round 8, B6: --skip-implicit-stub-with-type25 keyed on the WRITTEN
        # TYPE25 set - right after the TYPE25 writer, which records it. A
        # no-op that draws no id unless the flag deferred the stub.
        ("deferred_implicit_stub", lambda c: _make_deferred_implicit_stub(
            c.state, c.contact_rigid_nodes)),
        ("tied_interfaces",   lambda c: _make_tied_interfaces(c.state, c.rigid_nodes)),
        ("tiebreak_interfaces",
                              lambda c: _make_tiebreak_interfaces(c.state, c.rigid_nodes)),
        ("spotweld_interfaces",
                              lambda c: _make_spotweld_interfaces(c.state, c.rigid_nodes)),
        ("force_transducers", lambda c: _make_force_transducers(c.state, c.rigid_nodes)),
        # A note-only section (it returns []): it emits the by-name
        # refusal for every *CONTACT k2rad RECOGNIZES and deliberately
        # does not convert. Here rather than in the handler because one
        # refusal quotes a *DEFINE_CURVE that the corpus carrier defines
        # 150 lines AFTER the contact - see state.ContactRefused.
        ("refused_contacts", lambda c: _make_refused_contact_notes(c.state)),
        # A note-only section (it returns [] and draws no id): the ONE
        # warning per deck for the *CONSTRAINED_TIED_NODES_FAILURE cards
        # the handler refused by name (round 6, A4). A writer section rather
        # than the handler because it counts every card and every node set.
        ("tied_nodes_failure_notes",
                              lambda c: _make_tied_nodes_failure_notes(c.state)),
        ("rbodies",           lambda c: c.rbody_lines),
        # *CONSTRAINED_JOINT_SCREW -> /GJOINT/RACK (round 7, B2): right after
        # the /RBODY cards whose main nodes (and carriage) it ties; every id
        # it draws is drawn here. A no-op on any deck without a converted
        # screw.
        ("joint_screws",      lambda c: _make_joint_screws(c.state,
                                                           c.rbody_info)),
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
        # *NODE card 1's own TC/RC cells -> /GRNOD/NODE + /BCS. Deliberately
        # HERE and not beside the *BOUNDARY_SPC "bcs" section: its screening
        # rules read registries that only exist once earlier sections have
        # run -- rule (a) needs rigid_nodes (available), and rule (b) needs
        # state.imp_motion_dirs, which the three imposed-motion sections
        # directly above fill as they emit. Announcing a conversion before
        # the screens that can drop it is the #133 defect; the placement is
        # what makes the announcement true.
        ("node_tc_rc_bcs",    lambda c: _make_node_tc_rc_bcs(
            c.state, c.rbody_info, c.rigid_nodes)),
        ("inivel",            lambda c: _make_inivel(c.state, c.rbody_info,
                                                       c.rigid_nodes)),
        ("initial_velocity",  lambda c: _make_initial_velocity(
            c.state, c.rigid_nodes, c.rbody_info)),
        ("initial_velocity_generation",
                              lambda c: _make_initial_velocity_generation(
                                  c.state, c.rigid_nodes, c.rbody_info)),
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
        # --shell-in-solid-coupling (round 8, B10): the converted cards'
        # /INTER/TYPE18; empty (no id drawn) by default
        ("shell_in_solid_coupling",
                              lambda c: _make_shell_in_solid_coupling(c.state)),
        # *CONSTRAINED_SHELL_IN_SOLID: ONE named warning per deck (round 7,
        # B5); writes no card and draws no id - the keyword stays skipped.
        ("shell_in_solid_notes",
                              lambda c: _make_shell_in_solid_notes(c.state)),
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
        # *ALE_REFERENCE_SYSTEM_* (round 9, B8): the skip / refusal sentences;
        # no card, no id (the --ale-flow-tracking card itself is written by
        # _make_analysis_defaults, right after /DEF_SOLID)
        ("ale_reference_notes",
                              lambda c: _make_ale_reference_notes(c.state)),
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
        # round 8, A5: the adaptive spring token runs first inside it and
        # rewrites the token /PROP MASS cells already in c.lines
        ("added_masses",      lambda c: _make_added_masses(c.state, c.rigid_nodes,
                                                           c.lines)),
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
        # /BEAM, /SPRING and /TRUSS producer above, whose write lines fill
        # state.beam_elem_ids / spring_elem_ids / truss_elem_ids (the *SET_BEAM
        # of *INITIAL_AXIAL_FORCE_BEAM is split by what was ACTUALLY emitted —
        # a /GRTRUS group is a third family the reader scans).
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
        # beam_elem_ids / truss_elem_ids and the three BEAM->/SPRING re-route
        # registries at the
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
        #   * rbody reads state.rbody_ids, which the six /RBODY producers
        #     fill in build_starter BEFORE the registry is walked at all
        #     (round 5's shell-to-solid and butt-weld bodies and round 7's
        #     screw carriage included);
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
        # *CONSTRAINED_LINEAR_LOCAL/_GLOBAL -> /MPC (round 6, A5). HERE, last
        # of the id-drawing sections: its screens read every /BCS, imposed
        # motion, rigid body, free-node pin and /INTER/TYPE2 secondary group
        # (all written above; the tied-node refusal is round 7, B4), and no
        # section below draws an id, so an emitted /MPC renumbers nothing.
        # A no-op, drawing no id, on any deck without the keyword.
        ("constrained_linear_mpcs",
                              lambda c: _make_constrained_linear_mpcs(
                                  c.state, c.rbody_info, c.rigid_nodes)),
        # round 9, B5: the zero-off-scale copies of applied-load curves,
        # AFTER every consumer has drawn its copy id (writer/loadcurves.py)
        ("offscale_functs",   lambda c: make_offscale_functs(c.state)),
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
    if _engine_implicit(state) or state.is_modal:
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
    if ts is None or _engine_implicit(state) or state.is_modal:
        # round 9, B4: the --shell-in-solid-coupling re-tune's /DT/INTER/CST
        # stands alone on a deck without *CONTROL_TIMESTEP ([] otherwise)
        return (sis_dt_inter_lines(state)
                if ts is None and not _engine_implicit(state)
                and not state.is_modal else [])
    if ts.dt2ms >= 0.0:
        # round 9, B4: right after the /DT block ([] without the re-tune;
        # a DT2MS < 0 deck never gets it - the card is refused there)
        return (_make_engine_timestep_scale(state, ts)
                + sis_dt_inter_lines(state))
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


def _missing_thermal_halves(state: ConversionState) -> str:
    """Name the half of ``_thermal_solve_active`` that is actually missing.

    The sentence this feeds used to prescribe ``*MAT_THERMAL_* + *PART TMID and
    a driver`` unconditionally — on a deck that may STATE both and simply not
    get them emitted (``*MAT_THERMAL_CWM`` has no Radioss counterpart, and a
    driver whose ``*SET_NODE_*`` k2rad cannot read is dropped at emission). That
    is the #125 class: a true conclusion prescribing a fix on a correct deck.
    Both flags are read from what was WRITTEN, the same source
    :func:`~k2rad.writer.thermal._thermal_solve_active` reads.
    """
    heat = bool(state.heat_mat_cards)
    drive = bool(state.thermal_driver_emitted or state.thermal_source_emitted)
    if not heat and not drive:
        return ("NEITHER — no /HEAT/MAT and no temperature-moving card reached "
                "the output. If the deck states a *MAT_THERMAL_* and a driver, "
                "they were DROPPED at emission (a *MAT_THERMAL_CWM has no "
                "Radioss counterpart at all, and a driver whose *SET_NODE_* "
                "this converter cannot read is dropped with the set); the "
                "warnings above name each one")
    if not heat:
        return ("a temperature-moving card WAS written, but no /HEAT/MAT — no "
                "*PART reached the output naming a converted *MAT_THERMAL_* "
                "through TMID, so hm_read_therm.F:253 never arms ITHERM and "
                "every thermal call in resol.F stays gated off")
    return ("a /HEAT/MAT WAS written, but no temperature-moving card reached "
            "the output — an /INITEMP is a STATE, not a driver, so DTEMP stays "
            "identically zero on every cycle. Add an /IMPTEMP-producing "
            "*BOUNDARY_TEMPERATURE_* or a *BOUNDARY_CONVECTION / _RADIATION / "
            "_FLUX heat source (and check the warnings above for one that was "
            "dropped with its node set)")


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
                     and not _engine_implicit(state) and not state.is_modal)
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
               if _engine_implicit(state) or state.is_modal else
               "this deck arms no thermal solve: /DT/THERM without a "
               "/HEAT/MAT and a temperature-moving card would freeze the whole "
               "model and integrate nothing (GLOB_THERM%ITHERM_FE gates every "
               "thermal call in resol.F). WHICH HALF IS MISSING, from what was "
               "EMITTED rather than what was stated: "
               + _missing_thermal_halves(state)
               + (" (and --ams is in force, which would refuse /DT/THERM "
                  "anyway — freform.F:1327-1330 hard-stops the pair)"
                  if _ams_is_emitted(state) else ""))
            + ". The mechanical model is converted as usual and its degrees of "
            "freedom stay live."
            + (" AND THAT MATTERS FOR THE STAND-IN MATERIALS: "
               f"{len(state.thermal_standin_mats)} /PART(s) "
               f"{sorted(state.thermal_standin_mats)} were given a synthesized "
               "/MAT/ELAST whose E = 1 is justified ONLY by /DT/THERM freezing "
               "every DOF. Without /DT/THERM that E = 1 is the part's REAL "
               "structural stiffness, roughly five orders of magnitude below "
               "any metal, so the mechanical answer on those parts is "
               "meaningless. Give them a real structural *MAT_*, or state a "
               "*MAT_THERMAL_* + a temperature driver so the thermal-only run "
               "mode is written."
               if state.thermal_standin_mats else ""))
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
        if _thermal_solve_active(state) and not _engine_implicit(state) \
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
                   if _engine_implicit(state) or state.is_modal else
                   "this deck arms no thermal solve — no material gets a "
                   "/HEAT/MAT and/or no temperature-moving card is emitted, "
                   "so there is nothing for it to speed up")
                + ".")
    return lines


def imflag_segments(pts: List[Tuple[float, float]], endtim: float
                    ) -> List[Tuple[float, float, str]]:
    """The solution-method schedule of an IMFLAG < 0 curve (round 7, A5):
    ``[(t_start, t_end, "implicit" | "explicit"), ...]`` up to *endtim*.

    A point's method is implicit when its ordinate is >= 0.5 (the curve
    states 1 / 0), else explicit. The points are walked in abscissa order
    from the first point's method; a segment boundary is the abscissa of the
    FIRST point that carries the new method (LS-DYNA's ie_shell messag reads
    "formulation switch at time = 1.0000E-02" for the points (0.00999, 1)
    (0.01, 0)). A boundary at or before the current segment's start is
    absorbed (a vertical step at t 0 just sets the starting method); one at
    or beyond *endtim* ends the walk."""
    if not pts:
        return []
    ordered = sorted(pts, key=lambda p: p[0])      # stable: equal x kept

    def _meth(y: float) -> str:
        return "implicit" if y >= 0.5 else "explicit"

    start = 0.0
    method = _meth(ordered[0][1])
    segs: List[Tuple[float, float, str]] = []
    for x, y in ordered[1:]:
        m = _meth(y)
        if m == method:
            continue
        if x <= start:
            method = m
            continue
        if x >= endtim:
            break
        segs.append((start, x, method))
        start, method = x, m
    segs.append((start, endtim, method))
    return segs


#: IMFLAG values whose in-run behaviour OpenRadioss has no mode for (Vol I R17
#: p.12-321 / 12-322); converted implicit throughout, named.
_IMFLAG_TEXT_ONLY = {
    2: "explicit followed by one implicit step",
    4: "implicit that switches to explicit when the equilibrium iterations "
       "fail",
    5: "implicit that switches to explicit when the equilibrium iterations "
       "fail, with a mandatory implicit finish",
    6: "explicit with intermittent eigenvalue extraction",
}


def _warn_imflag(state: ConversionState,
                 restart: Optional[List[EngineSegment]] = None) -> None:
    """``*CONTROL_IMPLICIT_GENERAL`` IMFLAG < 0 (a method-switching curve) and
    the IMFLAG 2 / 4 / 5 / 6 forms, named (round 7, A5 (iii)). Called ONCE
    from :func:`build_engines` / :func:`build_engine` - not from
    ``_make_engine_implicit``, whose modal early return would hide it (a
    warning below an early return covers one branch). 0 bytes. Round 8 (B3
    h.2): *restart* = the engine files ``--imflag-curve-restart`` writes
    (None: computed here; ``[]`` from ``build_engine``, the single-file
    entry), and the sentence names them and their run order; without them
    the deck is emitted implicit throughout and the sentence names the
    opt-in.
    """
    g = state.ctrl_implicit_gen
    if g is None:
        return
    imflag = g.imflag
    switch = ("OpenRadioss fixes the solution method per ENGINE FILE (engine "
              "input/freimpl.F:82, :127-129: implicit iff the file holds an "
              "/IMPL card)")
    if imflag in _IMFLAG_TEXT_ONLY:
        state.warn(
            f"*CONTROL_IMPLICIT_GENERAL IMFLAG={imflag} "
            f"({_IMFLAG_TEXT_ONLY[imflag]}, Vol I R17 p.12-321 / 12-322): "
            "converted IMPLICIT THROUGHOUT - " + switch + ", so there is no "
            "such mode inside one engine run.")
        return
    if imflag >= 0:
        return
    lcid = -imflag
    curve = state.curves.get(lcid)
    if curve is None or not curve.pts:
        state.warn(
            f"*CONTROL_IMPLICIT_GENERAL IMFLAG={imflag}: curve {lcid} is not "
            "defined in the deck, so its implicit/explicit schedule cannot be "
            "read; the deck is emitted IMPLICIT THROUGHOUT (" + switch + ").")
        return
    term = state.ctrl_termination
    endtim = term.endtim if term is not None and term.endtim > 0.0 else \
        max(p[0] for p in curve.pts)
    segs = imflag_segments(curve.pts, endtim)
    if all(m == "explicit" for _a, _b, m in segs):
        state.warn(
            f"*CONTROL_IMPLICIT_GENERAL IMFLAG={imflag}: curve {lcid} selects "
            "EXPLICIT for the whole run, which LS-DYNA runs explicit; k2rad "
            "emits it IMPLICIT (any IMFLAG != 0 makes the deck implicit) - "
            "state IMFLAG 0 to convert it as the explicit run it is.")
        return
    if len(segs) < 2:
        return                     # implicit throughout: nothing is lost
    sched = ", ".join(f"{m} {a:g} -> {b:g}" for a, b, m in segs)
    if restart is None:
        restart = imflag_restart_segments(state)
    if restart:
        files = ", ".join(
            f"_{s.run:04d}.rad ({'implicit' if s.implicit else 'explicit'} "
            f"to {s.t_stop:g}{'' if s.last else ', restart written'})"
            for s in restart)
        state.warn(
            f"*CONTROL_IMPLICIT_GENERAL IMFLAG={imflag}: curve {lcid} "
            f"switches the solution method in time ({sched}); " + switch
            + f", so --imflag-curve-restart wrote {len(restart)} engine "
            f"files, one per segment: {files}. Run them IN ORDER from ONE "
            "directory - run k restarts from the <stem>_<k-1>_0001.rst that "
            "run k-1 wrote (radioss2.F:817-830; every file but the last omits "
            "/RFILE/OFF for that): run the starter, then <stem>_0001.rad, "
            "<stem>_0002.rad and so on, each under its own name; never run "
            "a renamed copy. The starter is the implicit one "
            "throughout. " + _IMFLAG_RESTART_MEASURED)
        return
    state.warn(
        f"*CONTROL_IMPLICIT_GENERAL IMFLAG={imflag}: curve {lcid} switches "
        f"the solution method in time ({sched}); LS-DYNA switches inside one "
        "run (Vol I R17 p.12-321 / p.12-323 Remark 1). " + switch + ", and "
        "this deck is emitted IMPLICIT THROUGHOUT. MEASURED on "
        "implicit/basic-examples/impl-expl-switch/ie_shell.k (nt 4 = nt 2): "
        "the released strip does not vibrate - internal energy -1.52 / -2.36 "
        "/ -99.48 / -98.77 / -99.87 % against LS-DYNA at the fifths of the "
        "run, kinetic energy 0 against 149.9 at the end - while the run ends "
        "NORMAL in 92 cycles (a status, not a result). "
        "--imflag-curve-restart writes one engine file per segment "
        "(MEASURED on this deck: END IE -4.54 %, RMS 12.07 / 12.04 % of the "
        "LS peak; run the files in order).")


#: the measured chain of --imflag-curve-restart (round 8, B3 h.2): ie_shell's
#: two files run in order, scored by the campaign rule (the LAST row of a
#: printed time)
_IMFLAG_RESTART_MEASURED = (
    "MEASURED on implicit/basic-examples/impl-expl-switch/ie_shell.k (nt 4 "
    "= nt 2): NORMAL in 18 + 11 127 cycles; against LS-DYNA at t 0.025 (its "
    "last block 0.0249996) internal energy -4.54 %, kinetic +248.43 % (LS's "
    "end KE is 1.9 % of its 8059.66 peak); internal energy at the fifths of "
    "t_end 0.025 -1.52 / +1.17 / -41.73 / +84.55 / -4.54 % (the last row of "
    "each printed time); RMS 12.07 / 12.04 % of the LS peak over the 320 LS "
    "times 0 < t <= 0.025, where the single implicit file reads 58.96 / "
    "58.79; energy after the release +0.09 % against LS; the free vibration "
    "leads LS-DYNA by 0.270 / 0.239 ms at the tip minima. NOT MEASURED on any "
    "deck: an implicit DYNAMIC segment after an explicit one (ZERO_V is not "
    "carried; an implicit dynamic restart that carries a velocity is the x "
    "-3 momentum class of round 6); an implicit STATIC segment after an "
    "explicit one drops the explicit kinetic energy and re-bases its "
    "external work (a coupon: KE 316.1 -> 0, EXT-WORK 7096 -> 6783), so the "
    "last file's energy error cannot see the switch; a chain of more than "
    "two engine files (every measured chain has two).")


def imflag_restart_segments(state: ConversionState) -> List[EngineSegment]:
    """The engine files of ``--imflag-curve-restart`` (round 8, B3 h.2), or
    ``[]`` when its rule does not fire: the flag on, an implicit non-modal
    deck, ``*CONTROL_IMPLICIT_GENERAL`` IMFLAG < 0 whose curve exists, and
    ``imflag_segments`` returning two or more segments that are not all
    explicit. The curve's points are already scaled (SFA / OFFA at parse
    time), so the boundaries are the scaled abscissae."""
    if (not state.options.imflag_curve_restart or state.is_modal
            or not state.is_implicit):
        return []
    g = state.ctrl_implicit_gen
    if g is None or g.imflag >= 0:
        return []
    curve = state.curves.get(-g.imflag)
    if curve is None or not curve.pts:
        return []
    term = state.ctrl_termination
    endtim = term.endtim if term is not None and term.endtim > 0.0 else \
        max(p[0] for p in curve.pts)
    segs = imflag_segments(curve.pts, endtim)
    if len(segs) < 2 or all(m == "explicit" for _a, _b, m in segs):
        return []
    first_impl = next(i for i, s in enumerate(segs) if s[2] == "implicit")
    return [EngineSegment(run=i + 1, t_stop=b, implicit=(m == "implicit"),
                          last=(i == len(segs) - 1),
                          first_implicit=(i == first_impl))
            for i, (_a, b, m) in enumerate(segs)]


def build_engines(state: ConversionState) -> List[str]:
    """One engine text per run (round 8, B3 h.2): ``[build_engine(state)]``
    for every deck but an IMFLAG < 0 one under ``--imflag-curve-restart``,
    which gets one file per method segment, in run order. A warning the
    per-file builders repeat is kept once."""
    _warn_imflag(state)
    segs = imflag_restart_segments(state)
    if not segs:
        return [_build_engine_text(state)]
    w0 = len(state.warnings)
    out: List[str] = []
    for seg in segs:
        state.engine_segment = seg
        try:
            out.append(_build_engine_text(state))
        finally:
            state.engine_segment = None
    seen = set(state.warnings[:w0])
    kept: List[str] = []
    for w in state.warnings[w0:]:
        if w not in seen:
            seen.add(w)
            kept.append(w)
    state.warnings[w0:] = kept
    return out


def build_engine(state: ConversionState) -> str:
    """The ONE engine file (today's entry for its direct callers): the
    IMFLAG warning and the engine text, whatever --imflag-curve-restart
    says (``build_engines`` is what ``convert`` uses)."""
    _warn_imflag(state, [])
    return _build_engine_text(state)


def _build_engine_text(state: ConversionState) -> str:
    """The engine text of the file being built (``state.engine_segment``
    names the IMFLAG segment under --imflag-curve-restart, else None)."""
    seg = state.engine_segment
    not_last = seg is not None and not seg.last
    sections = [
        _make_engine_header(state),
        # round 8, B3 (h.2): every file but the last keeps its restart file -
        # run k+1 restarts from the .rst run k writes (radioss2.F:817-830)
        [] if not_last else _make_engine_restart(state),
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
        # Round 8, B3 (h.2): a dynain belongs to the END state, the last file.
        [] if not_last else _make_engine_dynain(state),
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
    # Round 9, B2: a routed 2-D deck never carries /DT/NODA/CST or /DT/AMS
    # (resol.F:2711-2729 rebuilds the 2-D nodal masses every cycle).
    lines = transform_engine_lines(state, lines)
    # Round 9, B4: the re-tune's /DT/INTER/CST leaves if another /DT/INTER
    # card is already there (no k2rad writer emits one today)
    lines = sis_dt_inter_guard(state, lines)
    return "\n".join(lines) + "\n"
