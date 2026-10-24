"""Starter loads and constraints: BCS, cloads, pressure, gravity, imposed motions, inivel, rigid walls, springs/connectors, added masses, damping."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Set, Tuple
from ..state import (
    ConversionState, NodeData, BeamElem, SectionDiscrete, Curve,
    DampingFrequencyRange, PM_VAD_KEYWORD, PrescribedMotionSet, RigidInertia,
    RigidWallGeomFace,
)
from .common import (
    HDR, _discrete_beam_pids, _dof_string, _emit_grnod_grnod, _emit_grnod_node,
    _emit_grpart_part, _emit_id_group, _f, _fmt_eid_list, _i,
    _muscle_beam_pids, _muscle_discrete_pids, _part_node_sets,
    _part_scoped_segment_set,
    _spotweld_beam_pids, _truss_pids, _vcross, _vnorm, _vsub, rigid_part_ids,
)
from .mesh import (_emit_skew_fix, _emit_skew_mov, _ortho_skew_axes,
                   _target_mat_law)
from ..lumping import element_mass_by_node, rigid_body_momentum_velocity
# ONE skip predicate for the default J = -SUM(IN) (round 7, A2) and this
# module's --mass-weighted-inivel pass (round 6, A7); it moved to rbody.py
from .rbody import _rbody_in_skip_reason
from .sph import _mat_density

__all__ = [
    "_make_rlinks",
    "_make_bcs",
    "_make_node_tc_rc_bcs",
    "_global_spc_dofs",
    "_mesh_has_rotational_dof",
    "_FORCE_DOF_AXIS",
    "_emit_spr_gene_dof",
    "_emit_spr_gene_dof_kc",
    "_make_grounding_springs",
    "SpringDof",
    "_as_spring_dof",
    "_emit_spring_dof",
    "_emit_prop_type4",
    "_emit_prop_type8",
    "_emit_prop_type13",
    "_pts_slope_at_origin",
    "_curve_slope_at_origin",
    "_mirror_one_sided_curve",
    "_plastic_to_total_disp",
    "_card_value",
    "_monotonic_abscissae",
    "_emit_funct",
    "_s03_curve_points",
    "_curve_max_slope",
    "_finite_length",
    "_element_length",
    "_new_ground_node",
    "_emit_spring_part",
    "_register_spring_token_mass",
    "_SPRING_TOKEN_MASS",
    "_SPRING_TOKEN_INERTIA",
    "_make_discrete_springs",
    "PLOTEL_ID",
    "PLOTEL_MASS",
    "_spring_eid_families",
    "_warn_spring_eid_collisions",
    "_make_plotel_elements",
    "_box_basis",
    "_box_global_corners",
    "_box_contains",
    "_box_node_ids",
    "_resolve_box_nodes",
    "_make_spotweld_beam_connectors",
    "_make_constrained_spotweld_springs",
    "_CLUSTER_IFAIL",
    "_CLUSTER_A",
    "_CLUSTER_B",
    "_cluster_brick_eids",
    "_cluster_failure_limits",
    "_emit_cluster_brick",
    "_emit_th_cluster",
    "_make_hex_spotweld_clusters",
    "_DOF_DIR",
    "_emit_imp_card",
    "_pm_skew_for",
    "_pm_lock_cards",
    "_make_imposed_motions",
    "_synthesize_local_motion_frames",
    "_PM_DOF_TO_BCS",
    "_or_dof_codes",
    "_pm_set_nodes",
    "_make_imposed_motions_set",
    "_emit_grnod_part",
    "_emit_grav_card",
    "_rbody_mains_in_scope",
    "_grav_groups",
    "_make_gravity_loads",
    "_make_body_loads",
    "_emit_centri_card",
    "_centri_frame",
    "_emit_inivel",
    "_make_inivel",
    "_emit_frame_fix",
    "_emit_inivel_axis",
    "_make_initial_velocity",
    "_make_initial_velocity_generation",
    "_emit_pload_card",
    "_emit_sensor_time",
    "_shell_load_segments",
    "_make_pressure_loads",
    "_make_added_masses",
    "_make_tied_nodes_failure_notes",
    "_make_constrained_linear_mpcs",
    "_apply_mass_weighted_rbody_inertia",
    "_merge_mass_weighted_pairs",
    "_make_starter_cloads",
    "_make_node_cloads",
    "_synthesize_rwall_moving_nodes",
    "_rwall_finite_corners",
    "_rwall_geom_triad",
    "_rwall_geom_faces",
    "_resolve_geometric_rigid_walls",
    "_make_geometric_rwall_motion",
    "_emit_rwall_geom_face",
    "_rwall_node_groups",
    "_rwall_slide",
    "_make_rigid_walls",
    "_make_modal_dummy_cload",
    "_make_damping",
    "_make_damping_part_mass",
    "_make_damping_frequency_range",
    "_resolve_damping_relative",
    "_make_free_node_constraints",
]


def _make_rlinks(state: ConversionState) -> List[str]:
    """*CONSTRAINED_NODE_SET → /RLINK: every node in the set keeps the same
    velocity along the constrained direction(s). The set is emitted as a /GRNOD
    by _make_extra_groups, which /RLINK references by the same id."""
    if not state.constrained_node_sets:
        return []
    # The Trarot code field is the same "   TTT RRR" layout /BCS uses: a 3-digit
    # translation code (Tx Ty Tz) then a 3-digit rotation code (Rx Ry Rz) within
    # one 10-char field (a packed 6-digit code is mis-decoded by the reader).
    dof_code = {1: ("100", "000"), 2: ("010", "000"), 3: ("001", "000"),
                4: ("111", "000"), 5: ("000", "100"), 6: ("000", "010"),
                7: ("000", "001")}
    lines = ["#-  RIGID LINKS (*CONSTRAINED_NODE_SET):", HDR]
    for cns in state.constrained_node_sets:
        code = dof_code.get(cns.dof)
        if code is None:
            code = ("111", "000")
            state.warn(f"*CONSTRAINED_NODE_SET nsid={cns.nsid}: DOF={cns.dof} "
                       "unrecognized — defaulted to all three translations.")
        tra, rot = code
        if cns.tf < 1e19:
            state.warn(f"*CONSTRAINED_NODE_SET nsid={cns.nsid}: failure time "
                       f"TF={cns.tf:g} dropped (/RLINK has no failure time).")
        title = (state.node_sets.get(cns.nsid, ("", []))[0]
                 or f"CONSTRAINED_NODE_SET_{cns.nsid}")
        lines += [
            f"/RLINK/{cns.nsid}",
            title,
            "#   Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}{_i(0)}{_i(cns.nsid)}",
            HDR,
        ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: boundary conditions
# ─────────────────────────────────────────────────────────────────────────────

def _curve_identically_zero(state: ConversionState, lcid: int) -> bool:
    """True when *lcid* is a converted *DEFINE_CURVE whose every ordinate is
    0.0 (the stored points already carry SFO / OFFO). A function, a table or a
    missing id is NOT zero (round 9, A8)."""
    c = state.curves.get(lcid)
    return bool(c is not None and c.pts and all(o == 0.0 for _a, o in c.pts))


def _pm_sf(state: ConversionState, pm) -> float:
    """The scale factor LS-DYNA applies to a *BOUNDARY_PRESCRIBED_MOTION row
    (round 9, A8; ``--prescribed-motion-sf-default``, default ON).

    Vol I R17 p.759: "SF  Load curve scale factor. The default is 1.0." - with
    no EQ.0 clause - and the general rule of Appendix V p.73-9: the keyword
    reader fills a blank field with 0 and LS-DYNA then replaces the value 0 by
    the default. So a STATED 0.0 is 1.0 (the Yaris roof crush press, SF 0.0,
    does 5.4039E+05 of work in its bndout). The OpenRadioss starter reads a
    zero Fscale as 1.0 too (read_impdisp.F:239, read_impvel.F:248,
    hm_read_impacc.F:194), so on a RIGID row only the bytes change.
    ``--no-prescribed-motion-sf-default`` keeps the stated 0."""
    if pm.sf == 0.0 and state.options.prescribed_motion_sf_default:
        return 1.0
    return pm.sf


def _pm_zero_hold(state: ConversionState, pm) -> bool:
    """A *BOUNDARY_PRESCRIBED_MOTION_NODE / _SET row written as a /BCS hold
    instead of an /IMP* card: before round 9 every SF = 0.0 row; with
    ``prescribed_motion_sf_default`` only a stated SF 0.0 whose motion really
    is zero - VAD 0 or 2 on an identically zero curve, or no motion
    definition at all (LCID 0, or an id no curve / table registry holds) -
    because SF 0 is LS-DYNA's 1.0 and a non-zero curve then MOVES the nodes;
    VAD 1 on a zero curve is imposed (a zero acceleration keeps the initial
    velocity, decision D11)."""
    if pm.sf != 0.0:
        return False
    if not state.options.prescribed_motion_sf_default:
        return True
    if pm.vad not in (0, 2):
        return False
    if (pm.lcid == 0 or (pm.lcid not in state.curves
                         and pm.lcid not in state.define_tables
                         and pm.lcid not in state.define_tables_3d)):
        return True
    return _curve_identically_zero(state, pm.lcid)


def spc_cid_skew(state: ConversionState, cid: int) -> int:
    """The /SKEW id a ``*BOUNDARY_SPC`` (or ``*LOAD_NODE``) CID resolves to, 0
    when it resolves to none (round 9, A6).

    ``_make_skews`` writes every ``*DEFINE_COORDINATE_SYSTEM`` / ``_NODES`` /
    ``_VECTOR`` under its own CID (a VECTOR frame as ``/SKEW/FIX/<cid>``,
    ``writer/mesh._emit_coord_vector_skew``), and LS-DYNA applies the SPC in
    any of the three (control_adaptive.cylinder.d3hsp:1170-1172 'number of
    spc nodes ... 48', 'number of spc coordinates ... 9'). Before round 9
    the five consumers accepted only SYSTEM / NODES frames and wrote a
    VECTOR-CID constraint in the GLOBAL system behind a false 'not found'.
    ``--no-spc-vector-frames`` keeps a VECTOR CID out (the 386444e bytes).
    Every consumer reads this one test - ``_make_bcs``, ``_global_spc_dofs``,
    the ``*CONSTRAINED_LINEAR`` screen, the free-node guard / ERROR 148
    refusal and the screw ``BodyCondition`` - so they cannot disagree; the
    ``*LOAD_NODE`` CID sibling takes it too (decision D9, reach 0).
    """
    if not cid:
        return 0
    if cid in state.coord_sys or cid in state.coord_nodes:
        return cid
    if cid in state.coord_vectors and state.options.spc_vector_frames:
        return cid
    return 0


def _make_bcs(state: ConversionState, rbody_info: Dict) -> List[str]:
    """``*BOUNDARY_SPC_NODE`` / ``_SET`` -> one ``/BCS`` ``BC_<id>`` per card,
    on the card's own node set (``/GRNOD/NODE/<nsid>``, shared by every card
    on that set and written once).

    In this order, per card:

      1. a rigid-body member is RE-POINTED onto its ``/RBODY`` main node
         (``node_to_ind``; a ``/BCS`` on a secondary is inert,
         ``rgbodv.F:150-155``);
      2. a resolvable CID (``*DEFINE_COORDINATE_SYSTEM`` / ``_NODES``) becomes
         the card's skew; anything else is written in the GLOBAL system, named;
      3. (round 8, A1) a main node that carries its body's own SKEWED card
         (``*MAT_RIGID`` CMO -1, a skewed CNRB ``_SPC`` card) leaves a card in
         ANOTHER skew - the starter accepts one skew per node
         (``hm_read_bcs.F:199-205``, ERROR 148) - and is named;
      4. (round 8, A3 P1; ``--bcs-union``, default ON) the UNION per
         ``(node, skew)``: a DOF an EARLIER card already states on that node
         in that skew is not restated. LS-DYNA keeps ONE constraint per node
         (sphere1.d3hsp prints 120 SPC nodes for its 124 deck rows) and the
         starter ORs two ``/BCS`` into the same union (``hm_read_bcs.F:198``
         ``MY_OR``), so a second card on a common DOF only fed starter
         WARNING 312 - which counts the DOFs both cards fix
         (``kinchk.F:945-947``), not nodes. A node whose card adds new DOFs
         keeps them in a ``BC_<id>_<Tra>_<Rot>`` remainder card and group;
         the card's other nodes go to a ``BC_<id>_not_restated`` group; a
         card left with no node writes no ``/BCS`` at all (its set's
         ``/GRNOD`` is still written). Two skews never merge (a digit is an
         axis of its own skew) and a node in two skews is named. When no node
         is shared the cards are byte-identical to 4f5b6e8.
    """
    if not state.bcs_spcs:
        return []
    lines = ["#-  BOUNDARY CONDITIONS:", HDR]

    node_to_ind = {}
    for pid, info in rbody_info.items():
        ind_node = info["ind_node"]
        for node in info["nodes"]:
            node_to_ind[node] = ind_node
    # round 8, B8 (q-ii): a member of a converted screw body is HELD by the
    # joint in every DOF the card states (any other code refused the joint):
    # the code is written nowhere - the joint section names it
    from .joint_screw import screw_merged_members
    screw_members = screw_merged_members(state)

    # round 8, A1: the rigid-body main nodes that carry a SKEWED /BCS of their
    # own body (empty under --no-rigid-local-constraints)
    skewed_cards = _rigid_skewed_cards(state)
    skew_drops: Dict[int, Tuple[str, str, int]] = {}
    # round 8, A3 P1: (node, skew) -> the six digits an EARLIER card states
    union = state.options.bcs_union
    stated: Dict[Tuple[int, int], str] = {}
    skews_of: Dict[int, Set[int]] = defaultdict(set)
    merged_dofs: Dict[int, int] = defaultdict(int)
    cards_gone: List[int] = []
    rest_nodes: Set[int] = set()
    emitted_grnods: Set[int] = set()
    # round 9, A6: (card id, CID) of every card written in a VECTOR frame
    vector_cards: List[Tuple[int, int]] = []
    for bc in state.bcs_spcs:
        nsid = bc.nsid
        raw_nids = state.node_sets.get(nsid, ("", []))[1]
        if screw_members:
            kept_raw = [n for n in raw_nids if n not in screw_members]
            if raw_nids and not kept_raw:
                continue          # merged into a screw joint (its sentence)
            raw_nids = kept_raw

        mapped_nids = set()
        for n in raw_nids:
            if n in node_to_ind:
                mapped_nids.add(node_to_ind[n])
            else:
                mapped_nids.add(n)

        if not mapped_nids:
            state.warn(f"BCS {bc.bc_id} (nsid={nsid}): all nodes mapped to empty set – skipped")
            continue

        # *BOUNDARY_SPC CID: constraint acts in that local system → /BCS skew.
        # Only reference it when a matching /SKEW is actually emitted
        # (_make_skews writes /SKEW/<cid> for every *DEFINE_COORDINATE_*).
        # round 9, A6: ONE helper for every *BOUNDARY_SPC consumer
        skew_id = spc_cid_skew(state, bc.cid)
        if bc.cid and skew_id and bc.cid in state.coord_vectors:
            vector_cards.append((bc.bc_id, bc.cid))
        elif bc.cid and not skew_id:
            if bc.cid in state.coord_vectors:
                state.warn(
                    f"BCS {bc.bc_id} (nsid={nsid}): CID {bc.cid} is a "
                    "*DEFINE_COORDINATE_VECTOR frame (written as "
                    f"/SKEW/FIX/{bc.cid}); --no-spc-vector-frames writes the "
                    "constraint in the GLOBAL system instead, where LS-DYNA "
                    "applies it in that local frame.")
            else:
                state.warn(
                    f"BCS {bc.bc_id} (nsid={nsid}): local system cid={bc.cid} "
                    "not found — constraint applied in the GLOBAL system.")

        tra = _dof_string(bc.dofx, bc.dofy, bc.dofz)
        rot = _dof_string(bc.dofrx, bc.dofry, bc.dofrz)
        # round 8, A1 consumer (b): a member re-pointed onto a main node that
        # carries its body's SKEWED /BCS leaves this card when the card is in
        # another skew (ONE skew per node, ERROR 148); the same skew stays
        card_nids = mapped_nids
        if skewed_cards:
            gone = {m for m in mapped_nids if m in skewed_cards
                    and any(s != skew_id for s, _t, _a, _b in skewed_cards[m])}
            for m in gone:
                skew_drops[m] = (tra, rot, skew_id)
            card_nids = mapped_nids - gone
        # round 8, A3 P1: the union per (node, skew), in deck order
        code = tra + rot
        keep: List[int] = []
        rest: Dict[str, List[int]] = defaultdict(list)
        for n in sorted(card_nids):
            skews_of[n].add(skew_id)
            if not union:
                keep.append(n)
                continue
            prev = stated.get((n, skew_id), "000000")
            hit = sum(1 for c, p in zip(code, prev) if c == "1" and p == "1")
            stated[(n, skew_id)] = "".join(
                "1" if "1" in (c, p) else "0" for c, p in zip(code, prev))
            if not hit:
                keep.append(n)
                continue
            merged_dofs[n] += hit
            new = "".join("1" if (c == "1" and p == "0") else "0"
                          for c, p in zip(code, prev))
            if "1" in new:
                rest[new].append(n)
                rest_nodes.add(n)
        if keep:
            if len(keep) == len(mapped_nids):
                grnod = nsid               # nothing shared: the 4f5b6e8 card
            else:
                grnod = state.next_grnod_id()
            lines += [
                f"/BCS/{bc.bc_id}",
                f"BC_{bc.bc_id}",
                "#  Tra rot   skew_ID  grnod_ID",
                f"   {tra} {rot}{_i(skew_id)}{_i(grnod)}",
                HDR,
            ]
            if grnod != nsid:
                restated = len(keep) < len(card_nids)
                set_title = state.node_sets.get(nsid, ("", []))[0]
                lines += _emit_grnod_node(
                    grnod, (f"BC_{bc.bc_id}_not_restated" if restated else
                            f"{set_title or f'SET_{nsid}'}_one_skew"), keep)
        elif card_nids:
            cards_gone.append(bc.bc_id)
        for new in sorted(rest):
            rid = state.next_id()
            gid = state.next_grnod_id()
            rtitle = f"BC_{bc.bc_id}_{new[:3]}_{new[3:]}"
            lines += [
                f"/BCS/{rid}",
                rtitle,
                "#  Tra rot   skew_ID  grnod_ID",
                f"   {new[:3]} {new[3:]}{_i(skew_id)}{_i(gid)}",
                HDR,
            ]
            lines += _emit_grnod_node(gid, rtitle, rest[new])
        if nsid in emitted_grnods:
            continue          # several SPC cards on one set share the /GRNOD
        emitted_grnods.add(nsid)
        set_title = state.node_sets.get(nsid, ("", []))[0]
        lines += _emit_grnod_node(nsid, set_title or f"SET_{nsid}", sorted(mapped_nids))
    if skew_drops:
        state.warn("*BOUNDARY_SPC:" + _skew_drop_sentence(
            skew_drops, skewed_cards, "*BOUNDARY_SPC"))
    if merged_dofs:
        nn = sorted(merged_dofs)
        state.warn(
            f"*BOUNDARY_SPC: {sum(merged_dofs.values())} DOF(s) on {len(nn)} "
            f"node(s) (node {_named(nn)}) are stated by two or more "
            "*BOUNDARY_SPC cards in one system; LS-DYNA keeps ONE constraint "
            "per node, the union of the DOFs, and the starter ORs two /BCS the "
            "same way (hm_read_bcs.F:198 MY_OR), so a later card no longer "
            "restates a DOF an earlier card fixes (the second /BCS only fed "
            "starter WARNING 312, one condition per DOF both cards fix). "
            f"{len(cards_gone)} card(s) write no /BCS"
            + (" (" + ", ".join(f"BC_{c}" for c in cards_gone[:8])
               + (" ..." if len(cards_gone) > 8 else "") + ")"
               if cards_gone else "")
            + f"; {len(rest_nodes)} node(s) keep the remaining DOFs in a "
            "BC_<id>_<Tra>_<Rot> group. MEASURED on intro-by-j.-day sphere1 "
            "(nt 4 and nt 2): 1592 = 1592 cycles, every printed row "
            "identical, WARNING 312 24 -> none. --no-bcs-union writes every "
            "card as before (round 8).")
    cross = sorted(n for n, s in skews_of.items() if len(s) > 1)
    if union and cross:
        sk = sorted({s for n in cross for s in skews_of[n]})
        state.warn(
            f"*BOUNDARY_SPC: node(s) {_named(cross)} are constrained in two "
            f"different systems (skews {', '.join(str(s) for s in sk)}); not "
            "merged (a digit is an axis of its own skew), and the starter "
            "accepts ONE skew per node: ERROR 148 (hm_read_bcs.F:199-205) will "
            "stop it - state both in one system.")
    if vector_cards:
        cids = sorted({c for _b, c in vector_cards})
        state.warn(
            f"*BOUNDARY_SPC: {len(vector_cards)} card(s) name a "
            "*DEFINE_COORDINATE_VECTOR CID ("
            + ", ".join(str(c) for c in cids)
            + "); each constraint is written in that frame's /SKEW/FIX/<cid> "
            "(LS-DYNA applies the DOFs in the local system). Before round 9 "
            "they went to the GLOBAL system with a false 'not found': on "
            "control_adaptive.cylinder the constrained radial displacement "
            "reached 0.3352 mm (now 1.8e-8 mm on every state) and a free "
            "tangential DOF carried up to 4611 N (now 0.024 N; LS-DYNA 0). "
            "--no-spc-vector-frames restores the global writing.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: *NODE's own TC/RC constraint cells → /GRNOD/NODE + /BCS
# ─────────────────────────────────────────────────────────────────────────────

#: LS-DYNA ``*NODE`` TC / RC code → the three ``/BCS`` digits. Vol I R17
#: p.35-2/35-3, verbatim: "EQ.0 no constraints, EQ.1 constrained x
#: displacement, EQ.2 y, EQ.3 z, EQ.4 x and y, EQ.5 y and z, EQ.6 z and x,
#: EQ.7 x, y, and z" (RC the same seven on rotations). NOT assumed: the table
#: reproduces LS-DYNA's OWN ``nodal spc summary on *NODE cards`` d3hsp echo
#: (printed by 155 of the R14 reference runs) on all 162 139 constrained *NODE
#: ROWS of the 137 carrier decks (267 641 non-zero TC/RC cells, counting TC and
#: RC separately — the echo prints one row per node), with zero
#: translation-code disagreements.
_TC_RC_DIGITS = {0: "000", 1: "100", 2: "010", 3: "001",
                 4: "110", 5: "011", 6: "101", 7: "111"}

#: The inverse of :data:`_TC_RC_DIGITS`: three ``/BCS`` digits -> the
#: ``*NODE`` TC/RC code. All eight digit patterns have a code (``000`` -> 0 ...
#: ``101`` -> 6, ``111`` -> 7), so any OR of two codes is a code.
_TC_RC_CODE = {v: k for k, v in _TC_RC_DIGITS.items()}


def _or_code(a: int, b: int) -> int:
    """The ``*NODE`` TC/RC code whose digits are the OR of codes *a* and *b*
    (``_or_code(3, 1)`` = 6: z OR x = "z and x")."""
    return _TC_RC_CODE[_or_dof_codes([_TC_RC_DIGITS[a], _TC_RC_DIGITS[b]])]


def _element_node_ids(state: ConversionState) -> Set[int]:
    """The defined nodes the deck's ELEMENTS reference: shells (2-D belts
    included), solids, thick shells, SPH particles, and the two end nodes of
    beams, discretes and 1-D belts (never a beam's orientation node n3) - the
    mesh whose size ``*CONSTRAINED_GLOBAL``'s default tolerance scales with."""
    ids: Set[int] = set()
    for elems in (state.shell_elems, state.solid_elems, state.tshell_elems,
                  state.sph_elems):
        for e in elems:
            ids.update(e.nodes)
    for pairs in (state.beam_elems, state.discrete_elems,
                  state.seatbelt_elems):
        for b in pairs:
            ids.update((b.n1, b.n2))
    return {n for n in ids if n in state.nodes}


def _bounding_box(pts) -> List[Tuple[float, float]]:
    """``[(xmin, xmax), (ymin, ymax), (zmin, zmax)]`` of a non-empty list of
    nodes."""
    return [(min(v), max(v)) for v in ([p.x for p in pts], [p.y for p in pts],
                                       [p.z for p in pts])]


def _resolve_constrained_globals(state: ConversionState) -> None:
    """``*CONSTRAINED_GLOBAL`` -> the per-node TC/RC union (R14 triage round 6,
    B5). Called in ``build_starter`` BEFORE any prepass synthesizes a node, so
    both the model extent and the candidates are the deck's OWN nodes.

    Per row: every node whose coordinate along the plane normal (DIR 1/2/3 =
    global x/y/z) is within the row's TOL of the plane point - or, when TOL
    is 0, within ``1e-6 x`` the model extent (the largest side of the bounding
    box of the nodes the deck's ELEMENTS reference, :func:`_element_node_ids`;
    every defined node stays a CANDIDATE). LS-DYNA's own rule is "the
    internal mesh-size dependent tolerance" (Vol I R17 p.10-39), which the
    card does not state, so the default is k2rad's own; it reproduces
    LS-DYNA's own d3hsp 'nodal spc summary' NODE FOR NODE, id set and codes,
    on all three R14 carriers (ex_27 constrained twin 305 of 11285 nodes,
    extent 32.4; efg/metal-cutting 54 = 36 x 001/111 + 18 x 111/111 of 4197,
    extent 24; ale_wavehitcol 24737 in 7 codes of 352232, extent 487.68 -
    the same extents over the element nodes as over all nodes). Until the
    post-review round of #140 the box was that of ALL nodes, so one
    element-free node far away (an orientation or reference node) inflated
    the tolerance: measured on the pre-fix code, a 2 x 2 x 1 hex grid with one
    such node at x = 1e6 got a tolerance of 1.0, and a plane at z = 0.5
    through the middle of its elements selected all 18 grid nodes and the
    stray one. A node on
    several planes gets the OR of their codes (``_or_code``); the union with
    the ``*NODE`` cells and the four screens happen in
    :func:`_make_node_tc_rc_bcs`.

    Every plane selecting 0 nodes leaves nothing to emit: the keyword goes
    back into ``skipped_keywords`` (reach 0), the same bookkeeping as a
    refused card.
    """
    if not state.constrained_globals:
        return
    extent = 0.0
    if state.nodes:
        mesh = _element_node_ids(state)
        pts = [state.nodes[n] for n in sorted(mesh)] or list(
            state.nodes.values())
        box = _bounding_box(pts)
        extent = max(hi - lo for lo, hi in box)
        if mesh:
            free_out = [
                n for nid, n in state.nodes.items() if nid not in mesh
                and any(not lo <= c <= hi
                        for c, (lo, hi) in zip((n.x, n.y, n.z), box))]
            if free_out:
                all_box = _bounding_box(list(state.nodes.values()))
                state.constrained_global_extent_outliers = (
                    len(free_out), max(hi - lo for lo, hi in all_box))
    state.constrained_global_extent = extent
    for g in state.constrained_globals:
        tol = g.tol if g.tol > 0.0 else 1e-6 * extent
        k = g.dir - 1
        c = (g.x, g.y, g.z)[k]
        sel = [nid for nid, n in state.nodes.items()
               if abs((n.x, n.y, n.z)[k] - c) <= tol]
        state.constrained_global_rows.append((g, tol, len(sel)))
        for nid in sel:
            t0, r0 = state.constrained_global_tc_rc.get(nid, (0, 0))
            state.constrained_global_tc_rc[nid] = (_or_code(t0, g.tc),
                                                   _or_code(r0, g.rc))
    # a row with TC = RC = 0 selects nodes and constrains nothing
    state.constrained_global_tc_rc = {
        n: c for n, c in state.constrained_global_tc_rc.items() if c != (0, 0)}
    if not state.constrained_global_tc_rc:
        state.skipped_keywords.append("CONSTRAINED_GLOBAL")
        state.warn(
            f"*CONSTRAINED_GLOBAL: none of its {len(state.constrained_globals)}"
            " plane(s) passes within its tolerance of any node (or every row "
            "states TC = RC = 0), so NOTHING is converted (the keyword stays in "
            "the SKIPPED list): "
            + "; ".join(f"{'xyz'[g.dir - 1]} = {(g.x, g.y, g.z)[g.dir - 1]:g} "
                        f"within {tol:g}"
                        for g, tol, _n in state.constrained_global_rows) + ".")


#: ``/IMPVEL|/IMPDISP|/IMPACC`` ``Dir`` letter → (0 = translation code /
#: 1 = rotation code, digit index). The letters are the ones ``_DOF_DIR``
#: produces, so this cannot drift from what the motion cards actually say.
_IMP_DIR_BIT = {"X": (0, 0), "Y": (0, 1), "Z": (0, 2),
                "XX": (1, 0), "YY": (1, 1), "ZZ": (1, 2)}


def _global_spc_dofs(state: ConversionState) -> Dict[int, Tuple[str, str]]:
    """``node id -> (Tra, Rot)`` already pinned by a GLOBAL-system ``/BCS``
    that another pass writes from the deck's own cards.

    Two sources, and they are the only two a ``*NODE`` TC/RC node can collide
    with:

      * ``*BOUNDARY_SPC_{NODE,SET}`` (``state.bcs_spcs`` → :func:`_make_bcs`);
      * a ``*BOUNDARY_PRESCRIBED_MOTION_{NODE,SET}`` row with ``SF = 0``, which
        :func:`_make_imposed_motions_set` writes as a ``/BCS`` rather than an
        ``/IMP*`` ("zero x any curve = 0 displacement = fixed").

    Every OTHER ``/BCS`` k2rad emits — the spring/discrete ground anchors, the
    inert probe rigid body, the ``*MAT_RIGID`` auto-constraint and the CNRB
    ``_SPC`` card — sits on a node no ``*NODE`` row can name: the first three
    are ids k2rad MINTS, and the last two act on an ``/RBODY`` independent
    node. That node is NOT outside the TC/RC pass, though: rule (a) RE-POINTS
    the members' cells onto it. The last two are therefore merged too, but
    from their OWN source, :func:`_rigid_auto_spc_dofs` (``state.rigid_auto_bcs``
    and the skew-0 ``state.cnrb_spc_bcs``), in screen (c') of
    :func:`_make_node_tc_rc_bcs` (round 7, A1) — with their own counter and
    their own sentence, because the digits are the rigid body's and not a
    ``*BOUNDARY_SPC``'s. They are deliberately NOT in this map: its two other
    consumers would gain nothing (the ``*CONSTRAINED_LINEAR`` screen already
    refuses every rigid-body node and labels its hits as a ``*BOUNDARY_SPC``;
    the modal dummy-load screen never sees a rigid node). Before round 7 the
    main node landed in TWO ``/BCS`` groups (``BC_rigid_PID`` and a TC/RC or
    ``*CONSTRAINED_GLOBAL`` group) on 6 roster keys / 6 models (bend,
    275key2, ex_16_thin_shell_elform_13, forging_A, forging_B,
    ale_wavehitcol), inert by ``MY_OR`` (``hm_read_bcs.F:198`` unions the
    codes) and reported as starter WARNING 312, one condition per DOF both
    cards fix: MEASURED 275key2 20 -> none, ex_16 5 -> none, bend 33 -> 30
    (its other 30 are boundary condition + rigid wall). ``*CONSTRAINED_GLOBAL``
    itself is not in this map: its cells are UNIONED with the ``*NODE`` cells
    inside :func:`_make_node_tc_rc_bcs`, so they meet every screen there.

    A ``*BOUNDARY_SPC`` with a resolvable ``CID`` is deliberately NOT here: its
    ``/BCS`` carries a skew, so its digits are axes of that skew and no global
    TC/RC bit can be cancelled against them. The test mirrors ``_make_bcs``
    exactly (an unresolvable CID falls back to the global system there, so it
    counts here).

    The ``_BOX`` rows of a prescribed motion are skipped: resolving a
    ``*DEFINE_BOX`` costs the box resolver's own diagnostics, and running it a
    second time here would print them twice. The consequence is bounded and
    named in the report — at worst one extra ``/BCS`` on a node that already
    has one, which ``hm_read_bcs.F:198`` unions (``MY_OR``) into the identical
    constraint and only reports as starter WARNING 312.
    """
    out: Dict[int, Tuple[str, str]] = {}

    def _add(nid: int, tra: str, rot: str) -> None:
        old = out.get(nid, ("000", "000"))
        out[nid] = (_or_dof_codes([old[0], tra]), _or_dof_codes([old[1], rot]))

    for bc in state.bcs_spcs:
        if spc_cid_skew(state, bc.cid):
            continue                      # a skewed /BCS: not a global bit
        tra = _dof_string(bc.dofx, bc.dofy, bc.dofz)
        rot = _dof_string(bc.dofrx, bc.dofry, bc.dofrz)
        for nid in state.node_sets.get(bc.nsid, ("", []))[1]:
            _add(nid, tra, rot)
    for pm in state.prescribed_motion_sets:
        # round 9, A8: only the rows still written as a /BCS hold count
        if not _pm_zero_hold(state, pm) or pm.boxid:
            continue
        mapped = _PM_DOF_TO_BCS.get(pm.dof)
        if mapped is None:
            continue
        for nid in state.node_sets.get(pm.nsid, ("", []))[1]:
            _add(nid, mapped[0], mapped[1])
    return out


def _rigid_auto_spc_dofs(state: ConversionState
                         ) -> Dict[int, Tuple[str, str, List[str]]]:
    """``/RBODY main node -> (Tra, Rot, [card titles])`` of the ``/BCS`` the
    rigid-body producers themselves write there (round 7, A1).

    Two sources, unioned (OR) per node:

      * ``state.rigid_auto_bcs`` — ``BC_rigid_<pid>``, the ``*MAT_RIGID``
        CMO 1 CON1/CON2 code plus the implicit stabilisation of an unloaded
        free translation, exactly the digits ``_make_rbodies`` emitted;
      * ``state.cnrb_spc_bcs`` with ``skew == 0`` — ``BC_cnrb_<pid>``, the
        ``*CONSTRAINED_NODAL_RIGID_BODY_SPC`` code. A skewed card's digits are
        axes of that skew, so no global TC/RC bit can be cancelled against
        them (the rule :func:`_global_spc_dofs` applies to a ``*BOUNDARY_SPC``
        with a CID).

    Kept apart from :func:`_global_spc_dofs` on purpose: screen (c') gives
    these hits their own counter and sentence (the code is the rigid body's,
    not a ``*BOUNDARY_SPC``'s), and that map's other two consumers would only
    gain a false label.
    """
    out: Dict[int, Tuple[str, str, List[str]]] = {}

    def _add(nid: int, tra: str, rot: str, title: str) -> None:
        old = out.get(nid, ("000", "000", []))
        out[nid] = (_or_dof_codes([old[0], tra]), _or_dof_codes([old[1], rot]),
                    old[2] + [title])

    for nid, (tra, rot, title) in sorted(state.rigid_auto_bcs.items()):
        _add(nid, tra, rot, title)
    for cbc in state.cnrb_spc_bcs:
        if cbc.skew:
            continue                      # a skewed /BCS: not a global bit
        _add(cbc.ind_node, cbc.tra, cbc.rot,
             cbc.title or f"/BCS/{cbc.bc_id}")
    return out


def _rigid_skewed_cards(state: ConversionState
                        ) -> Dict[int, List[Tuple[int, str, str, str]]]:
    """``/RBODY main node -> [(skew_ID, title, Tra, Rot)]`` of the SKEWED
    ``/BCS`` the rigid-body producers write there (round 8, A1): the
    ``*MAT_RIGID`` CMO -1 cards (``state.rigid_skewed_bcs``) and the
    ``*CONSTRAINED_NODAL_RIGID_BODY_SPC`` cards with a skew
    (``state.cnrb_spc_bcs``).

    The ONE predicate of the one-skew-per-node rule: the starter accepts ONE
    skew per node across every /BCS (``hm_read_bcs.F:199-205``, ERROR 148 'A
    SKEW IS ALREADY DEFINED WITH THE NODE'; the same skew twice is fine and
    skew 0 counts), so a code on such a node in ANOTHER skew - a re-pointed
    member *NODE TC/RC or *CONSTRAINED_GLOBAL code, or a *BOUNDARY_SPC - is
    dropped and named (:func:`_skew_drop_sentence`) instead of making the
    starter stop. Empty under ``--no-rigid-local-constraints``, which keeps
    round 7's behaviour (the clash is named, not resolved).
    """
    out: Dict[int, List[Tuple[int, str, str, str]]] = {}
    if not state.options.rigid_local_constraints:
        return out
    for nid, cards in sorted(state.rigid_skewed_bcs.items()):
        for tra, rot, skew, title in cards:
            out.setdefault(nid, []).append((skew, title, tra, rot))
    for cbc in state.cnrb_spc_bcs:
        if cbc.skew:
            out.setdefault(cbc.ind_node, []).append(
                (cbc.skew, cbc.title or f"/BCS/{cbc.bc_id}", cbc.tra,
                 cbc.rot))
    return out


def _skew_drop_sentence(drops: Dict[int, Tuple[str, str, int]],
                        cards: Dict[int, List[Tuple[int, str, str, str]]],
                        source: str) -> str:
    """W7 of round 8 A1: the codes the one-skew-per-node rule DROPPED.

    *drops* maps a main node to the dropped code ``(Tra, Rot, skew)``;
    *cards* is :func:`_rigid_skewed_cards`. The drop is EXACT where every
    dropped digit is still held by the kept card: a global digit is held by a
    skewed card only when that card fixes all three of its kind (``111``), so
    exact iff (no dropped translation or kept Tra 111) and (no dropped rotation
    or kept Rot 111)."""
    if not drops:
        return ""
    nodes = sorted(drops)
    kept_desc = sorted({f"{t} at skew {s}" for n in nodes
                        for s, t, _a, _b in cards.get(n, [])})
    codes = sorted({f"'{d[0]} {d[1]}' (skew {d[2]})" for d in drops.values()})
    lost: List[str] = []
    for n in nodes:
        tra, rot, _s = drops[n]
        k_tra = _or_dof_codes([c[2] for c in cards.get(n, [])] or ["000"])
        k_rot = _or_dof_codes([c[3] for c in cards.get(n, [])] or ["000"])
        miss = []
        if "1" in tra and k_tra != "111":
            miss += [ax for ax, d in zip(("x", "y", "z"), tra) if d == "1"]
        if "1" in rot and k_rot != "111":
            miss += [ax for ax, d in zip(("rx", "ry", "rz"), rot) if d == "1"]
        if miss:
            lost.append(f"node {n} no longer holds global {'/'.join(miss)}")
    if lost:
        tail = ("not exact: " + "; ".join(lost[:5])
                + (f" and {len(lost) - 5} more" if len(lost) > 5 else "")
                + " - state them in the body's own CON2 (its local system)")
    else:
        tail = ("exact: the kept card's Tra / Rot is 111, so every dropped "
                "digit is still held")
    # The opt-out clause is keyed on the PRODUCER of the kept card (the
    # round-8 post-review verification): the *MAT_RIGID producer titles its
    # skewed card BC_rigid_<pid>; every other one is a skewed
    # *CONSTRAINED_NODAL_RIGID_BODY_SPC card. Measured on starter probes:
    # the opt-out of a *MAT_RIGID CMO -1 body is the 4f5b6e8 deck, 0 errors;
    # that of a skewed CNRB _SPC card stops on ERROR 148.
    titles = {t for n in nodes for _s, t, _a, _b in cards.get(n, [])}
    opt_out = []
    if any(t.startswith("BC_rigid_") for t in titles):
        opt_out.append("writes no CMO -1 card for a *MAT_RIGID CMO -1 body, "
                       "so the other code stays and nothing clashes")
    if any(not t.startswith("BC_rigid_") for t in titles):
        opt_out.append("keeps a skewed *CONSTRAINED_NODAL_RIGID_BODY_SPC "
                       "card's old pair and its ERROR 148")
    return (
        f" {len(nodes)} /RBODY main node(s) (node {_named(nodes)}) carry the "
        "SKEWED /BCS of their rigid body ("
        + ", ".join(kept_desc[:5]) + (" ..." if len(kept_desc) > 5 else "")
        + f"); the {source} code(s) " + ", ".join(codes[:5])
        + (" ..." if len(codes) > 5 else "")
        + " on the same node were DROPPED: the starter accepts ONE skew per "
        "node (ERROR 148 'A SKEW IS ALREADY DEFINED WITH THE NODE', "
        "hm_read_bcs.F:199-205; measured on a starter probe). LS-DYNA applies "
        f"both; {tail} (round 8; --no-rigid-local-constraints "
        + ", and ".join(opt_out) + ").")


def _mesh_has_rotational_dof(state: ConversionState,
                             rbody_info: Dict) -> bool:
    """True unless this deck's mesh provably carries no rotational DOF.

    ``bcs10.F:66`` applies the ROTATIONAL half of every ``/BCS`` only inside
    ``IF(IRODDL/=0)``, so on a solid-only model the Rot digits are inert — and
    LS-DYNA agrees, dropping them from its own ``nodal spc summary`` echo
    (measured: 71 885 ``*NODE`` rotational codes across 22 solid/ALE R14 decks
    are stated in the deck and absent from the echo; ``control_energy.bar-impact``
    with its 864 ``TC 0 / RC 7`` nodes produces no echo row at all).

    The predicate is deliberately one-sided: it only says NO when the deck has
    none of the entities that bring rotational DOF with them. Anything else —
    a rigid body included — answers yes, so the report can never claim a code
    is inert on a model where it is not.
    """
    return bool(state.shell_elems or state.beam_elems or state.discrete_elems
                or state.seatbelt_elems or state.constrained_spotwelds
                or rbody_info)


def _make_node_tc_rc_bcs(state: ConversionState, rbody_info: Dict,
                         rigid_nodes: Set[int]) -> List[str]:
    """``*NODE`` card 1's own TC/RC cells → one ``/GRNOD/NODE`` + ``/BCS`` per
    distinct ``(TC, RC)`` pair. **On by default**; ``--no-node-tc-rc-bcs``
    (``convert(node_tc_rc_bcs=False)``) restores the old drop.

    Vol I R17 p.35-2/35-3 makes card 1 ``NID X Y Z TC RC`` with TC/RC the
    ``*BOUNDARY_SPC`` triples in the GLOBAL system, and unlike ``*BOUNDARY_SPC``
    they carry no CID, no id and no birth/death — they are unconditionally
    active for the whole run. So ``skew_ID`` is always 0 here.

    That bounds, but does not eliminate, the reader's ``ERROR 148`` ("A SKEW IS
    ALREADY DEFINED WITH THE NODE"). ``hm_read_bcs.F:107-109`` seeds
    ``ISKEW(I) = -1`` for every node and ``:198-204`` then raises 148 per NODE
    whenever the node's stored skew is neither -1 nor THIS card's — so the pair
    that can trip it is a node carrying both a ``*BOUNDARY_SPC`` with a
    resolvable CID (which ``_make_bcs`` writes as ``/BCS ... skew_ID = cid``)
    and a ``*NODE`` TC/RC cell, which this pass always writes at skew 0.
    :func:`_global_spc_dofs` deliberately skips skewed SPCs, so nothing screens
    that node out. MEASURED: 0 of the 893 decks in the three corpus roots carry
    a non-zero ``*NODE`` TC/RC beside a ``*BOUNDARY_SPC`` with a non-zero CID,
    so the pair is unrealised rather than impossible.

    **Why it is ON.** ROADMAP.md prescribed shipping this behind an opt-in and
    said "then run the campaign and consider flipping it". The campaign has
    run: on the 356-deck dynaexamples R14 roster **137 decks carry a non-zero
    TC/RC cell and 119 of them have no ``*BOUNDARY_SPC`` at all** — the card's
    own cells are their only support — and those decks sit under **44 of the
    69 IE-collapse decks and 27 of the 42 implicit-ERROR decks**. Two of them,
    patched by hand and run against their own LS-DYNA ``glstat``:
    ``component1`` went from IE −99.92 % / KE +772630 % to **IE +1.5 % /
    KE +1.0 %**, and ``ex_03_solid_elform_1_4x6x4_mesh`` from a TIMESTEP-LIMIT
    death at t = 0.22 to **NORMAL TERMINATION at t = 1.0**.

    **The four screens, each measured.**

      a. *A rigid-body member's cell is RE-POINTED onto the body's /RBODY main
         node, unioned per body.* Two independent measurements pick this over
         the two alternatives (emit it on the member; drop it).

         *OpenRadioss: the card on the member is inert.* ``resol.F:7073`` runs
         ``BCS10``, ``resol.F:7572`` then runs ``RBYVIT`` →
         ``rgbodv.F:150-155``, which rebuilds every secondary node's
         acceleration from the body's field, with no third ``BCS10`` after it.
         MEASURED on a three-arm rigid twin (``*MAT_RIGID`` block under
         ``*LOAD_BODY_Z``): ``/BCS`` on the member nodes gives K-ENERGY
         0.3720E-03, identical to the no-``/BCS`` control and to the analytic
         ½mv²; the SAME ``/BCS`` on the body's MAIN node gives 0.000, i.e. the
         body is held. So the main node is the only place the cell can act.

         *LS-DYNA: it applies the cell to the BODY.* This was shipped as "not
         decidable on this corpus" and the corpus decides it — in the same deck
         the old sentence used. ``control_contact.hemi-draw`` has four parts,
         three of them on one ``*MAT_RIGID`` (mid 2, ``CMO`` 0.0, ``CON1`` /
         ``CON2`` 0), no ``*BOUNDARY_SPC`` and no ``*CONSTRAINED`` anywhere,
         one ``*BOUNDARY_PRESCRIBED_MOTION_RIGID`` (part 2, dof 2) and one
         ``*RIGIDWALL_PLANAR`` whose node set holds 175 of part 3's nodes and
         none of part 4's:

           ============ ========================= ===================== ==================================
           part          TC cells (all its nodes)  union of translations  ``matsum`` max abs rbv over 121 steps
           ============ ========================= ===================== ==================================
           2 Punch       TC 3/1/6 on 41 of 331     x, z                   x 0.0, **y 1.885e4**, z 0.0
           3 Holder      TC 3/1 on 14 of 175       x, z                   x 0.0, **y 1.534e4**, z 0.0
           4 Die         **TC 7 / RC 7 on all 525**  x, y, z              **x 0.0, y 0.0, z 0.0**
           ============ ========================= ===================== ==================================

         The Die is not driven, not on the rigidwall, has no other constraint
         of any kind, and carries up to 1.8e4 of interface-3 contact force
         (``rcforc``) — and LS-DYNA holds it at exactly zero rigid-body
         velocity in all three components at every output time, while the two
         bodies whose cells leave y free move in y. That is the union rule and
         the control in one deck. ``control_adaptive.cup-draw`` says the same
         in its ``rbdout`` (body 4, TC 7, CMO 0, contact-loaded: acceleration
         exactly 0 in all six components at all 141 steps).

         Vol I R17 p.35-3 Remark 1 — "No attempt should be made to apply
         boundary conditions to nodes belonging to rigid bodies" — is advice to
         the deck author, not a statement that the solver ignores them; only
         the IMPLICIT path says otherwise out loud.
         ``ex_16_thin_shell_elform_13`` prints ``*** Warning 60257 (IMP+257)
         skipping spc on rigid body node 1003 / tcode = 6 rcode = 7`` (in its
         ``.d3hsp``, its ``.messag`` and its ``.console.log``) — but for 2 of
         that deck's 3 rigid TC/RC nodes (1003 and 1004, not 1001), and on 1 of
         the 16 rule-(a) carriers in the R14 tree. On the explicit carriers the
         cells are listed as stated in the ``nodal spc summary on *NODE cards``
         echo.

         The re-point is what ``_make_bcs`` has always done for a
         ``*BOUNDARY_SPC`` on a rigid member (``node_to_ind``), so the two
         paths now agree; the shared member→main map is ``_rbody_main_of``.
         Rules (b), (c) and (d) are applied AT THE MAIN NODE (one ``_screen``
         helper for both passes), which is the node
         ``*BOUNDARY_PRESCRIBED_MOTION_RIGID`` registers its ``/IMPVEL``
         against — so a driven rigid body keeps its driven DOF. A member whose
         body has no main node in ``rbody_info`` is still dropped, and named.
      b. *A DOF an imposed motion already drives is left to it.* MEASURED on a
         one-brick twin: ``/BCS`` and ``/IMPVEL`` on the same node and DOF give
         starter WARNING 312 and EXT-WORK 13.66 against an I-ENERGY of 1688 —
         a 99.9 % energy error on every cycle, which is the implicit
         residual-never-converges signature and, on an explicit deck, poisons
         exactly the channel the campaign grades by. The complementary split
         (pin the DOFs the motion does not drive) measures 0.0 % with no
         warning.

         The screen is UNCONDITIONAL in time, and the card it defers to may not
         be: ``_register_imp_motion_nodes`` records the ``Dir`` letter only, so
         a ``*BOUNDARY_PRESCRIBED_MOTION`` with a BIRTH or a finite DEATH
         clears the DOF for the whole run while its ``/IMPVEL`` drives only
         inside its window — and a ``*NODE`` TC/RC cell has no window at all.
         MEASURED reach on the 356-deck R14 roster: 30 TC/RC carriers also
         carry a prescribed motion, 9 of the 10 whose DEATH looks finite state
         ``DEATH = 0.0``, which Vol I R17 p.35 makes the 1e28 default, and the
         one genuinely finite carrier (``275key2.k``, dof 3, death 5e-4) is a
         ``*_RIGID`` motion, which drives k2rad's own ``/RBODY`` main node and
         so meets no ``*NODE`` row. 0 decks affected today.
      c. *A DOF a ``*BOUNDARY_SPC`` already states is merged, not restated.*
         ``hm_read_bcs.F:198`` unions the codes (``ICODE = MY_OR(IC, ICODE)``),
         so a second ``/BCS`` changes no physics — but ``kinset``/``kinchk``
         still count it, and a two-``/BCS`` coupon measures 1 × WARNING 312 /
         8 incompatible conditions. MEASURED on the R14 roster at this head —
         AFTER the set spellings of this same batch made two more
         ``*BOUNDARY_SPC_SET`` cards resolve, which is why the figure moved:
         **570 DOFs on 570 nodes in 18 decks**, of which 16 (512 nodes, the
         ``ex_12`` / ``ex_13`` / ``ex_14`` / ``ex_15`` family — 32 nodes
         ``TC 3`` beside a ``*BOUNDARY_SPC_SET`` ``dofz = 1`` on the same 32)
         are exact duplication and lose the node entirely, while ``ex_09``
         (26 DOFs) and ``ex_10`` (32) are PARTIAL and keep a ``/BCS`` for the
         DOFs their SPC does not state.
      c'. *A DOF the rigid body's OWN /BCS fixes is merged into it* (round 7,
         A1): ``BC_rigid_<pid>`` (``*MAT_RIGID`` CMO 1 CON1/CON2) and
         ``BC_cnrb_<pid>`` (the CNRB ``_SPC`` option, skew 0 only) sit on the
         very main node rule (a) re-points the members' cells onto — see
         :func:`_rigid_auto_spc_dofs`. Applied after (c), with its own counter
         and sentence; a partial overlap keeps the REMAINDER in its own group
         (disjoint codes raise no WARNING 312). 0 physics by ``MY_OR``.
      d. *Rotational codes on a mesh with no rotational DOF are EMITTED and
         named.* See :func:`_mesh_has_rotational_dof`.

    The implicit free-node guard is the fifth interaction, and it is resolved
    from the OTHER side: :func:`_make_free_node_constraints` runs later, drops
    any node this pass has already pinned in all six DOFs, and (round 8, A3
    P3; ``--bcs-union``) writes on a partially pinned free node only the DOFs
    this pass leaves free, in a ``fix_free_reference_nodes_<Tra>_<Rot>`` group
    - the node is still fixed in all six (``MY_OR``) and no DOF twice.

    **Rule (b)'s reach is bounded by what registers itself.**
    ``state.imp_motion_dirs`` is filled by ``_register_imp_motion_nodes``,
    which the two ``_emit_imp_card`` sites call — i.e. every ``/IMPVEL``,
    ``/IMPDISP`` and ``/IMPACC`` built from a ``*BOUNDARY_PRESCRIBED_MOTION_*``
    card. Two other ``/IMP*`` sites exist and neither can matter here: the
    geometric rigid wall's drives k2rad's OWN synthesized carrier nodes, which
    no ``*NODE`` row can name; ``/IMPDISP/FGEO``
    (``*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY``, writer/rarecards.py) does not
    register and would therefore not be screened — measured reach **0 decks on
    the 356-deck R14 roster**, so it is NAMED here rather than given an arm.

    **What is NOT proved**, and the report says so: LS-DYNA's precedence for
    TC/RC vs a prescribed motion on the same node AND DOF. The one R14 carrier
    (``channel_A/B/C``) states ``TC 7`` beside a motion whose ``sf = 1e-8``, so
    its zero reaction work is explained by the scale factor and not by which
    card wins. Rule (b) is chosen on the Radioss measurement above.

    **``*CONSTRAINED_GLOBAL`` (round 6, B5) is a second producer of the same
    cells.** Its planes' codes (``state.constrained_global_tc_rc``, filled by
    :func:`_resolve_constrained_globals`) are UNIONED here, per node, with the
    ``*NODE`` cells, and the union goes through the SAME screens and out as
    ONE ``/BCS`` per union code - one ``/BCS`` per plane gives starter WARNING
    312 for every DOF two planes BOTH constrain on a shared node (MEASURED:
    efg/metal-cutting 12 conditions = 3 shared nodes x 4 common DOFs; a grid
    probe 3 = 3 x 1, and none when the two planes' DOFs are disjoint, where
    the node in two /BCS is harmless). The two sources keep their own
    provenance: ``--no-node-tc-rc-bcs`` drops only the ``*NODE`` cells (the
    planes still convert; ``--no-constrained-global`` is theirs); a group
    holding at least one ``*NODE``-cell node keeps the ``node_tc_rc_TRA_ROT``
    title (every pre-round-6 deck is byte-identical) and a GLOBAL-only group
    is titled ``constrained_global_TRA_ROT``; each source gets its own
    announcement, counting only its own nodes and screens.
    """
    node_cells: Dict[int, Tuple[int, int]] = (
        state.node_tc_rc if state.options.node_tc_rc_bcs else {})
    glob_cells = state.constrained_global_tc_rc
    if state.node_tc_rc and not state.options.node_tc_rc_bcs:
        _warn_node_tc_rc_dropped(state)
    if not node_cells and not glob_cells:
        return []
    cells: Dict[int, Tuple[int, int]] = dict(node_cells)
    for nid, (tc_g, rc_g) in glob_cells.items():
        t0, r0 = cells.get(nid, (0, 0))
        cells[nid] = (_or_code(t0, tc_g), _or_code(r0, rc_g))

    spc_dofs = _global_spc_dofs(state)
    # the /BCS the rigid-body producers write on their own main nodes (round 7,
    # A1): a SEPARATE source with its own counter, see _rigid_auto_spc_dofs
    auto_dofs = _rigid_auto_spc_dofs(state)
    rot_capable = _mesh_has_rotational_dof(state, rbody_info)

    groups: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    stated: Dict[Tuple[int, int], int] = defaultdict(int)
    rigid_dropped: List[int] = []
    # (node, DOFs cleared) per screen call, in call order - split by source
    # after the passes
    motion_hits: List[Tuple[int, int]] = []
    spc_hits: List[Tuple[int, int]] = []
    # screen (c'): (node, DOFs merged, the rigid body's own card titles)
    auto_hits: List[Tuple[int, int, List[str]]] = []
    # ... and the nodes where a merged digit is k2rad's implicit
    # stabilisation (state.rigid_auto_stab), so the sentence names it there
    auto_stab_hits: Set[int] = set()
    # ... and the nodes whose rigid-body card is that stabilisation ALONE (a
    # CMO 0 body, or CON1 / CON2 0): the sentence must not name a *MAT_RIGID
    # CON1/CON2 code the deck does not state there (the post-review round)
    auto_stab_only: Set[int] = set()
    rot_inert: List[int] = []
    skewed_motion: List[int] = []
    emptied: List[int] = []

    def _screen(nid: int, tra: List[str], rot: List[str]) -> Tuple[str, str]:
        """Rules (b), (c) and (d) on one node's digits.

        ONE implementation for both passes — the ordinary nodes and the
        re-pointed rigid-body main nodes — so a screen cannot be applied to one
        and forgotten on the other (the #120 "audit every registry walk" class,
        here with only two walks). Every screen keys on ``nid``, which is why
        the rigid pass must pass the MAIN node: that is the node
        ``*BOUNDARY_PRESCRIBED_MOTION_RIGID`` registers its /IMPVEL against.
        """
        cleared_here = 0
        for letter in sorted(state.imp_motion_dirs.get(nid, ())):
            which, idx = _IMP_DIR_BIT[letter]
            target = tra if which == 0 else rot
            if target[idx] == "1":
                target[idx] = "0"
                cleared_here += 1
        if cleared_here:
            motion_hits.append((nid, cleared_here))
        if nid in state.imp_motion_skew_nodes:
            skewed_motion.append(nid)
        spc_tra, spc_rot = spc_dofs.get(nid, ("000", "000"))
        merged_here = 0
        for i in range(3):
            if spc_tra[i] == "1" and tra[i] == "1":
                tra[i] = "0"
                merged_here += 1
            if spc_rot[i] == "1" and rot[i] == "1":
                rot[i] = "0"
                merged_here += 1
        if merged_here:
            spc_hits.append((nid, merged_here))
        # (c') the /BCS the rigid body itself writes on its main node
        # (BC_rigid_<pid> from *MAT_RIGID CMO 1 CON1/CON2, BC_cnrb_<pid> from
        # the CNRB _SPC option at skew 0): merged rather than written a second
        # time. AFTER rule (c), so a digit a *BOUNDARY_SPC states keeps that
        # attribution. Only a main node can hit: the map holds main nodes.
        a_tra, a_rot, a_titles = auto_dofs.get(nid, ("000", "000", []))
        a_stab = state.rigid_auto_stab.get(nid, "000")
        merged_auto = 0
        for i in range(3):
            if a_tra[i] == "1" and tra[i] == "1":
                tra[i] = "0"
                merged_auto += 1
                if a_stab[i] == "1":
                    auto_stab_hits.add(nid)
            if a_rot[i] == "1" and rot[i] == "1":
                rot[i] = "0"
                merged_auto += 1
        if merged_auto:
            auto_hits.append((nid, merged_auto, a_titles))
            if a_rot == "000" and a_tra == a_stab:
                auto_stab_only.add(nid)
        if "1" in rot and not rot_capable:
            rot_inert.append(nid)
        return "".join(tra), "".join(rot)

    # A rigid-body member's cell is re-pointed onto the body's MAIN node and
    # UNIONED with every other member's, because that is what LS-DYNA does with
    # it (see the rule (a) docstring) and because a /BCS on the secondary is
    # inert (rgbodv.F:150-155). The union is collected first and screened after
    # the member loop, at the MAIN node — the node an imposed motion on a rigid
    # part is registered against (_register_imp_motion_nodes is called with
    # info["ind_node"] for *BOUNDARY_PRESCRIBED_MOTION_RIGID), so rule (b) sees
    # the conflict it exists for.
    main_of = _rbody_main_of(rbody_info)
    rigid_union: Dict[int, Tuple[List[str], List[str]]] = {}
    rigid_members: Dict[int, List[int]] = defaultdict(list)
    rigid_orphans: List[int] = []
    rigid_repointed: Dict[int, Tuple[str, str]] = {}
    # round 8, B8 (q-ii): a code on a converted screw body's member is HELD
    # by the joint (any other code refused it) - written nowhere, named by
    # the joint section
    from .joint_screw import screw_merged_members
    screw_members = screw_merged_members(state)

    for nid in sorted(cells):
        tc, rc = cells[nid]
        if nid in node_cells:
            stated[node_cells[nid]] += 1       # the *NODE card's OWN code
        if nid in screw_members:
            continue
        if nid in rigid_nodes:
            main = main_of.get(nid)
            if main is None:
                rigid_orphans.append(nid)
                continue
            acc = rigid_union.setdefault(main, (list("000"), list("000")))
            for i in range(3):
                if _TC_RC_DIGITS[tc][i] == "1":
                    acc[0][i] = "1"
                if _TC_RC_DIGITS[rc][i] == "1":
                    acc[1][i] = "1"
            rigid_members[main].append(nid)
            rigid_dropped.append(nid)
            continue
        tra_s, rot_s = _screen(nid, list(_TC_RC_DIGITS[tc]),
                               list(_TC_RC_DIGITS[rc]))
        if tra_s == "000" and rot_s == "000":
            emptied.append(nid)
            continue
        groups[(tra_s, rot_s)].append(nid)
        state.node_tc_rc_emitted[nid] = (tra_s, rot_s)

    # ── the re-pointed rigid-body constraints, screened AT THE MAIN NODE ──
    for main in sorted(rigid_union):
        tra_s, rot_s = _screen(main, *rigid_union[main])
        if tra_s == "000" and rot_s == "000":
            emptied.append(main)
            continue
        groups[(tra_s, rot_s)].append(main)
        state.node_tc_rc_emitted[main] = (tra_s, rot_s)
        rigid_repointed[main] = (tra_s, rot_s)

    # ── round 8, A1: ONE skew per node. A main node that carries a SKEWED
    # /BCS of its own rigid body (a *MAT_RIGID CMO -1 card or a skewed CNRB
    # _SPC card) LEAVES its skew-0 TC/RC group: the pair is starter ERROR 148
    # (hm_read_bcs.F:199-205), so the rigid body's card is kept and this code
    # dropped and named (_skew_drop_sentence). Empty without
    # --rigid-local-constraints, where the clash is only named (below).
    skewed_cards = _rigid_skewed_cards(state)
    skew_drops: Dict[int, Tuple[str, str, int]] = {}
    if skewed_cards:
        for key in sorted(groups):
            hit = [n for n in groups[key] if n in skewed_cards]
            if not hit:
                continue
            for n in hit:
                skew_drops[n] = (key[0], key[1], 0)
                state.node_tc_rc_emitted.pop(n, None)
            keep = [n for n in groups[key] if n not in skewed_cards]
            if keep:
                groups[key] = keep
            else:
                del groups[key]

    # ── ERROR 148 (the post-review round; reach 0, pre-existing): a skewed
    # CNRB _SPC code is never merged (its digits are axes of its skew), and a
    # skew-0 group written on the SAME main node makes the starter stop -
    # hm_read_bcs.F:199-205 accepts one skew per node across /BCS cards.
    # Named, not refused: which of the two conditions should win is the
    # deck author's call.
    skewed_cnrb: Dict[int, List[str]] = defaultdict(list)
    for cbc in state.cnrb_spc_bcs:
        if cbc.skew:
            skewed_cnrb[cbc.ind_node].append(
                f"{cbc.title or f'/BCS/{cbc.bc_id}'} at skew {cbc.skew}")
    skew148: List[int] = sorted({n for nids in groups.values() for n in nids
                                 if n in skewed_cnrb})

    # ── provenance: which source(s) each screened node came from ──
    node_prov: Set[int] = {n for n in cells if n in node_cells}
    glob_prov: Set[int] = {n for n in cells if n in glob_cells}
    for main, members in rigid_members.items():
        if any(m in node_cells for m in members):
            node_prov.add(main)
        if any(m in glob_cells for m in members):
            glob_prov.add(main)

    lines: List[str] = []
    if groups:
        head = ("*NODE TC/RC cells" if not glob_cells else
                "*CONSTRAINED_GLOBAL planes" if not node_cells else
                "*NODE TC/RC cells + *CONSTRAINED_GLOBAL planes")
        lines = [f"#-  BOUNDARY CONDITIONS ({head}):", HDR]
    for tra_s, rot_s in sorted(groups):
        nids = groups[(tra_s, rot_s)]
        # next_grnod_id, never a bare next_id: a user *SET_NODE at or above the
        # 90001 auto base is re-emitted verbatim as /GRNOD/NODE/<sid>, and a
        # collision is starter ERROR 79 IN NODE GROUP DEFINITION with no
        # restart file (the #131 rule — every synthesized /GRNOD goes through
        # the guarded counter).
        grnod_id = state.next_grnod_id()
        bc_id = state.next_id()
        title = (f"node_tc_rc_{tra_s}_{rot_s}"
                 if any(n in node_prov for n in nids) else
                 f"constrained_global_{tra_s}_{rot_s}")
        lines += [
            f"/BCS/{bc_id}",
            title,
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {tra_s} {rot_s}         0{_i(grnod_id)}",
            HDR,
        ]
        lines += _emit_grnod_node(grnod_id, title, nids)

    def _of(prov: Set[int], raw_cells: Dict[int, Tuple[int, int]]):
        """Every screen list restricted to one source (a node with both
        sources counts in both announcements)."""
        return dict(
            groups={k: [n for n in v if n in prov] for k, v in groups.items()
                    if any(n in prov for n in v)},
            rigid_dropped=[n for n in rigid_dropped if n in raw_cells],
            rigid_repointed={m: c for m, c in rigid_repointed.items()
                             if m in prov},
            rigid_members={m: [n for n in v if n in raw_cells]
                           for m, v in rigid_members.items() if m in prov},
            rigid_orphans=[n for n in rigid_orphans if n in raw_cells],
            motion_nodes=[n for n, _k in motion_hits if n in prov],
            motion_dofs=sum(k for n, k in motion_hits if n in prov),
            spc_nodes=[n for n, _k in spc_hits if n in prov],
            spc_dof_count=sum(k for n, k in spc_hits if n in prov),
            auto_nodes=[n for n, _k, _t in auto_hits if n in prov],
            auto_dof_count=sum(k for n, k, _t in auto_hits if n in prov),
            auto_titles=sorted({t for n, _k, ts in auto_hits if n in prov
                                for t in ts}),
            auto_stab=any(n in auto_stab_hits
                          for n, _k, _t in auto_hits if n in prov),
            auto_cmo_neg=any(n in state.rigid_auto_cmo_neg
                             for n, _k, _t in auto_hits if n in prov),
            auto_stab_only=bool([n for n, _k, _t in auto_hits if n in prov])
            and all(n in auto_stab_only
                    for n, _k, _t in auto_hits if n in prov),
            skew148=[n for n in skew148 if n in prov],
            skew148_cards=sorted({c for n in skew148 if n in prov
                                  for c in skewed_cnrb[n]}),
            skew_drop={n: c for n, c in skew_drops.items() if n in prov},
            skew_cards=skewed_cards,
            rot_inert=[n for n in rot_inert if n in prov],
            skewed_motion=[n for n in skewed_motion if n in prov],
            emptied=[n for n in emptied if n in prov])

    if node_cells:
        mine = _of(node_prov, node_cells)
        _warn_node_tc_rc_converted(state, stated=stated, **mine)
        _warn_node_tc_rc_on_null_material(state, mine["groups"])
    if glob_cells:
        _warn_constrained_global_converted(state, **_of(glob_prov,
                                                        glob_cells))
    return lines


def _warn_constrained_global_converted(
        state: ConversionState, *,
        groups: Dict[Tuple[str, str], List[int]],
        rigid_dropped: List[int],
        rigid_repointed: Dict[int, Tuple[str, str]],
        rigid_members: Dict[int, List[int]],
        rigid_orphans: List[int],
        motion_nodes: List[int], motion_dofs: int,
        spc_nodes: List[int], spc_dof_count: int,
        auto_nodes: List[int], auto_dof_count: int, auto_titles: List[str],
        auto_stab: bool, auto_stab_only: bool,
        auto_cmo_neg: bool,
        skew148: List[int], skew148_cards: List[str],
        rot_inert: List[int], skewed_motion: List[int],
        emptied: List[int],
        skew_drop: Optional[Dict[int, Tuple[str, str, int]]] = None,
        skew_cards: Optional[Dict[int, List[Tuple[int, str, str, str]]]] = None
        ) -> None:
    """Announce the ``*CONSTRAINED_GLOBAL`` conversion once per deck, AFTER
    every screen (the #133 ordering rule), with this source's own counts."""
    rows = state.constrained_global_rows
    planes = "; ".join(
        f"TC {g.tc} RC {g.rc} on {'xyz'[g.dir - 1]} = "
        f"{(g.x, g.y, g.z)[g.dir - 1]:g} ({n} node(s) within {tol:g})"
        for g, tol, n in rows)
    emitted = sum(len(v) for v in groups.values())
    codes = ("; ".join(f"Tra {t} Rot {r}: {len(groups[(t, r)])}"
                       for t, r in sorted(groups)) if groups else "none")
    msg = [
        f"*CONSTRAINED_GLOBAL: {len(rows)} constraint plane(s) -> /BCS through "
        "the *NODE TC/RC pass, the constrained DOFs 'held fixed in time' (Vol "
        f"I R17 p.10-38): {planes}. A node on more than one plane gets ONE "
        "/BCS carrying the UNION of the planes' codes - "
        f"{emitted} node(s) in {len(groups)} union code(s): {codes} - "
        "because one /BCS per plane gives starter WARNING 312 for every DOF "
        "two planes both constrain on a shared node (measured: 12 conditions "
        "= 3 shared nodes x 4 common DOFs on efg/metal-cutting/main.k)."]
    if any(g.tol == 0.0 for g, _t, _n in rows):
        extent = state.constrained_global_extent
        msg.append(
            " The node tolerance is k2rad's OWN where a row states TOL = 0: "
            "LS-DYNA uses 'the internal mesh-size dependent tolerance' "
            f"(p.10-39), k2rad uses 1e-6 x the model extent ({extent:g}, the "
            "largest side of the bounding box of the nodes the deck's "
            f"elements reference) = {1e-6 * extent:g}; it selects exactly the "
            "nodes LS-DYNA's own "
            "d3hsp 'nodal spc summary' lists on all three R14 carriers "
            "(ex_27_solid_elform_2_rigidwall_constrained_nodes_implicit "
            "305 = 305; efg/metal-cutting/main.k 54 = 36 x 001/111 + 18 x "
            "111/111; ale_wavehitcol 24737 in the same 7 codes).")
        n_out, all_side = state.constrained_global_extent_outliers
        if n_out:
            msg.append(
                f" {n_out} element-free node(s) lie outside that box and do "
                "NOT set the tolerance: the box of every *NODE row has side "
                f"{all_side:g}, which would make it {1e-6 * all_side:g} and "
                "let a plane sweep nodes far from it.")
    if rigid_dropped:
        msg.append(
            f" {len(rigid_dropped)} node(s) (node {_named(rigid_dropped)}) "
            "belong to a rigid body and were RE-POINTED onto its /RBODY main "
            f"node, unioned per body ({len(rigid_repointed)} main node(s)): a "
            "/BCS on a /RBODY secondary is inert (rgbodv.F:150-155), exactly "
            "the *NODE TC/RC rule (a).")
    if rigid_orphans:
        msg.append(
            f" {len(rigid_orphans)} node(s) (node {_named(rigid_orphans)}) are "
            "rigid-body members whose body has no main node, so their codes "
            "are DROPPED.")
    if motion_nodes:
        msg.append(
            f" {motion_dofs} DOF(s) on {len(motion_nodes)} node(s) (node "
            f"{_named(motion_nodes)}) already driven by an imposed motion were "
            "left to it (a /BCS and an /IMPVEL on one DOF give starter WARNING "
            "312).")
    if skewed_motion:
        msg.append(
            f" {len(skewed_motion)} node(s) (node {_named(skewed_motion)}) also "
            "carry an imposed motion in a LOCAL system; nothing was cleared for "
            "them.")
    if spc_nodes:
        msg.append(
            f" {spc_dof_count} DOF(s) on {len(spc_nodes)} node(s) (node "
            f"{_named(spc_nodes)}) already stated by a *BOUNDARY_SPC were "
            "merged (hm_read_bcs.F:198 unions the codes).")
    if auto_nodes:
        msg.append(_rigid_auto_merge_sentence(auto_nodes, auto_dof_count,
                                              auto_titles,
                                              stab=auto_stab,
                                              stab_only=auto_stab_only,
                                              cmo_neg=auto_cmo_neg))
    if skew148:
        msg.append(_skew148_sentence(skew148, skew148_cards,
                                     "--no-constrained-global"))
    if skew_drop:
        msg.append(_skew_drop_sentence(skew_drop, skew_cards or {},
                                       "*CONSTRAINED_GLOBAL"))
    if rot_inert:
        msg.append(
            f" {len(rot_inert)} node(s) (node {_named(rot_inert)}) got a "
            "rotational code on a mesh with no rotational DOF: emitted and "
            "inert (bcs10.F:66 applies the Rot digits only inside "
            "IF(IRODDL/=0); LS-DYNA drops them from its echo too).")
    if emptied:
        msg.append(
            f" {len(emptied)} node(s) (node {_named(emptied)}) had every DOF "
            "screened away, so no /BCS was written for them.")
    if groups and state.mat_null:
        part_nodes = _part_node_sets(state)
        null_nodes: Set[int] = set()
        for p in state.parts.values():
            if p.mid in state.mat_null:
                null_nodes |= part_nodes.get(p.pid, set())
        n_null = len({n for v in groups.values() for n in v} & null_nodes)
        if n_null:
            msg.append(
                f" {n_null} of these nodes belong to a *MAT_NULL part: the "
                "/BCS is a wall of that fluid domain, as LS-DYNA applies it.")
    msg.append(" Pass --no-constrained-global to drop the card (these DOFs "
               "are then FREE).")
    state.warn("".join(msg))


def _warn_node_tc_rc_on_null_material(
        state: ConversionState,
        groups: Dict[Tuple[str, str], List[int]]) -> None:
    """Name the TC/RC pins that land on a ``*MAT_NULL`` mesh.

    MEASURED on the R14 campaign re-run of this batch: of the 137 carriers,
    THREE ``*MAT_NULL`` decks LOST a NORMAL termination they had when the cells
    were dropped — ``ale/sloshing/sloshing-a`` (33 813 cycles at min dt 5.9e-05
    to t = 2.0, against 697 421 cycles at min dt 2.3e-16 reaching t = 0.18),
    ``sloshing-c`` and ``sloshing-d``. On all three ``--no-node-tc-rc-bcs`` is
    byte-identical to a true master conversion. The decode is faithful: 242 of
    242 ``sloshing_A`` nodes agree with LS-DYNA's own ``nodal spc summary on
    *NODE cards`` echo (180 as ``0 0 1``, 40 as ``1 0 1``, 22 as ``1 1 1``,
    and 0 in every rotational column), and LS-DYNA runs the constrained model
    to t = 2.0.

    Two things this warning used to say, both corrected by measurement:

      * ``ale/bird/bird-b`` was listed as a fourth carrier. It is not one:
        with the opt-out its ``.rad`` still differs from a true master
        conversion by 337 added / 6 removed lines (item B gave the bird an
        ``/INIVEL`` master had dropped) and the opt-out arm collapses exactly
        like the full branch.
      * the class was named "``*MAT_NULL`` / ALE". Only ``bird_B`` of the four
        emits an ALE property at all: ``sloshing_A``/``_B`` carry no ALE
        keyword, and ``sloshing_C``/``_D`` state ELFORM 5 (1-point ALE) +
        ``*CONTROL_ALE`` yet convert to ``Iale = 0``, i.e. a Lagrangian solid.
        That silent ELFORM 5/6/7 downgrade is its own ROADMAP gap.

    And the CAUSE is not the pin. Same shipped ``.rad`` with only the
    ``/PROP/SOLID`` Isolid cell changed: Isolid 17 (what ELFORM 1 maps to)
    collapses at t = 0.18, Isolid 1 with h = 0.1 runs to NORMAL at t = 2.0 with
    IE −0.25 % against sloshing_A's own reference. The corpus even holds the
    controlled experiment — ``sloshing_B.k`` is ``sloshing_A.k`` plus three
    lines of ``*CONTROL_HOURGLASS``, which is what makes ``_ihq_to_isolid``
    remap 17 → 1, and it does not regress. The discriminator this warning gives
    the reader is therefore the deck's own ``*CONTROL_HOURGLASS`` card; the
    class is in ROADMAP as the ELFORM → Isolid item.
    """
    if not groups or not state.mat_null:
        return
    part_nodes = _part_node_sets(state)
    null_pids = {p.pid for p in state.parts.values()
                 if p.mid in state.mat_null}
    if not null_pids:
        return
    null_nodes: Set[int] = set()
    for pid in null_pids:
        null_nodes |= part_nodes.get(pid, set())
    hit = sorted({n for ids in groups.values() for n in ids} & null_nodes)
    if not hit:
        return
    state.warn(
        f"*NODE TC/RC: {len(hit)} of the converted node(s) (node "
        f"{_named(hit)}) belong to a *MAT_NULL part ("
        f"{', '.join(str(p) for p in sorted(null_pids))}), which carries no "
        "deviatoric stiffness. The /BCS is faithful — LS-DYNA applies these "
        "cells, its own d3hsp echoes all of them and it runs the constrained "
        "model to termination — but MEASURED on the R14 campaign three "
        "*MAT_NULL decks (ale/sloshing-a/-c/-d) lost a NORMAL termination to a "
        "time-step collapse once their tank walls were pinned. The cause is "
        "NOT the pin: the same .rad with /PROP/SOLID Isolid 1 instead of 17 "
        "runs sloshing_A to t = 2.0 at IE -0.25 % against its own LS-DYNA "
        "reference. *SECTION_SOLID ELFORM 1 is 1-point integration and k2rad "
        "maps it to the 8-point Isolid 17, and it re-maps to Isolid 1 ONLY "
        "when the deck carries a *CONTROL_HOURGLASS / *HOURGLASS card - so a "
        "deck relying on LS-DYNA's own default (IHQ 2 / QH 0.1, Vol I R17 "
        "p.12-271 Remark 1) gets no hourglass control at all. THE "
        "DISCRIMINATOR: this deck "
        + ("HAS" if (state.ctrl_hourglass or state.hourglass_defs)
           else "does NOT have")
        + " a *CONTROL_HOURGLASS/*HOURGLASS card"
        + ("." if (state.ctrl_hourglass or state.hourglass_defs) else
           " - sloshing_B, which is sloshing_A plus exactly that card, does "
           "not regress.")
        + " If this deck's dt collapses, --no-node-tc-rc-bcs "
        "(convert(node_tc_rc_bcs=False)) reproduces the previous behaviour "
        "byte for byte.")


def _named(nids: List[int], cap: int = 5) -> str:
    """``"1, 4, 7 and 12 more"`` — the first *cap* ids of a screened set."""
    shown = ", ".join(str(n) for n in nids[:cap])
    rest = len(nids) - cap
    return shown + (f" and {rest} more" if rest > 0 else "")


def _rigid_auto_merge_sentence(auto_nodes: List[int], auto_dof_count: int,
                               auto_titles: List[str],
                               stab: bool = False,
                               stab_only: bool = False,
                               cmo_neg: bool = False) -> str:
    """Screen (c')'s sentence (round 7, A1), shared by the ``*NODE`` and the
    ``*CONSTRAINED_GLOBAL`` announcements so the two cannot drift.

    Facts only: the merged code is the RIGID BODY's own /BCS. Attributing it to
    a ``*BOUNDARY_SPC`` would be false - on bend.k node 125's code is the
    ``*MAT_RIGID`` CON1/CON2 of body 2 and the deck states no SPC at all. On
    an *implicit* deck the ``BC_rigid`` card can also carry k2rad's own
    stabilisation of an unloaded free translation (``rbody._make_rbodies``),
    and *stab* names it where a merged DOF IS one of those digits
    (``state.rigid_auto_stab``; the validation round). The roster's one
    implicit A1 mover, ex_16_thin_shell_elform_13, merges CON1 6 / CON2 7
    digits only, so its sentence does not name it. *stab_only* (the
    post-review round): every merged node's card is that stabilisation
    ALONE (``state.rigid_auto_stab`` equals the card's digits - a CMO 0 body,
    or CON1 / CON2 0), so the sentence names no *MAT_RIGID CON1/CON2 code.
    """
    shown = ", ".join(auto_titles[:5]) + (
        f" and {len(auto_titles) - 5} more" if len(auto_titles) > 5 else "")
    named = (" - and the stabilisation k2rad adds on this implicit deck to "
             "an unloaded free translation of a loaded body -" if stab else "")
    what = ("the stabilisation k2rad adds on this implicit deck to an "
            "unloaded free translation of a loaded body - the body states no "
            "*MAT_RIGID CON1/CON2 digit there" if stab_only else
            f"*MAT_RIGID CMO 1 CON1/CON2{named}, or the "
            "*CONSTRAINED_NODAL_RIGID_BODY _SPC option"
            + (", or *MAT_RIGID CMO -1 CON2 in the global frame (CON1 0)"
               if cmo_neg else ""))
    return (
        f" {auto_dof_count} DOF(s) on {len(auto_nodes)} rigid-body main "
        f"node(s) (node {_named(auto_nodes)}) are already fixed by the /BCS "
        f"the rigid body itself writes there ({shown}: {what}) "
        "and were "
        "merged into it rather than written a second time: hm_read_bcs.F:198 "
        "unions the codes (MY_OR), so the second /BCS changed no physics and "
        "only added starter WARNING 312, one condition per DOF both cards fix.")


def _skew148_sentence(nodes: List[int], cards: List[str],
                      opt_out: str) -> str:
    """The ERROR-148 clause of the TC/RC announcements (the post-review
    round, A1's skew rule; reach 0 on every corpus, the same bytes as
    65ff389): a skewed *CONSTRAINED_NODAL_RIGID_BODY_SPC code is never merged,
    so a re-pointed member code keeps its own skew-0 /BCS on the same main
    node - which the starter refuses. Measured on a starter probe (the
    skewed-CNRB test deck): ERROR 148 + WARNING 312 at 65ff389 and at the
    round-7 head; without the member code, 0 errors."""
    return (
        f" {len(nodes)} /RBODY main node(s) (node {_named(nodes)}) carry "
        "this skew-0 /BCS AND the SKEWED /BCS a "
        "*CONSTRAINED_NODAL_RIGID_BODY_SPC writes there ("
        + ", ".join(cards[:5]) + (" ..." if len(cards) > 5 else "")
        + "), whose digits are axes of that skew and so were not merged: the "
        "starter accepts ONE skew per node across /BCS cards and STOPS with "
        "ERROR 148 'A SKEW IS ALREADY DEFINED WITH THE NODE' "
        "(hm_read_bcs.F:199-205). REMEDY: state the code in that CNRB's own "
        f"CON2 (its local system) instead, or drop the cells ({opt_out} drops "
        "them here).")


def _warn_node_tc_rc_converted(state: ConversionState, *,
                               stated: Dict[Tuple[int, int], int],
                               groups: Dict[Tuple[str, str], List[int]],
                               rigid_dropped: List[int],
                               rigid_repointed: Dict[int, Tuple[str, str]],
                               rigid_members: Dict[int, List[int]],
                               rigid_orphans: List[int],
                               motion_nodes: List[int], motion_dofs: int,
                               spc_nodes: List[int], spc_dof_count: int,
                               auto_nodes: List[int], auto_dof_count: int,
                               auto_titles: List[str],
                               auto_stab: bool, auto_stab_only: bool,
                               auto_cmo_neg: bool,
                               skew148: List[int], skew148_cards: List[str],
                               rot_inert: List[int],
                               skewed_motion: List[int],
                               emptied: List[int],
                               skew_drop: Optional[
                                   Dict[int, Tuple[str, str, int]]] = None,
                               skew_cards: Optional[Dict[
                                   int, List[Tuple[int, str, str, str]]]]
                               = None) -> None:
    """Announce the ``*NODE`` TC/RC conversion once per deck, AFTER every
    screen has run and with each screen's own count.

    The ordering is the #133 rule, not a preference: a message that ANNOUNCES a
    conversion has to run after every screen that can drop the record, or the
    log states a conversion the deck never gets. Every screen below therefore
    reports what it actually removed, from the same pass that removed it.
    """
    total = sum(stated.values())
    emitted = sum(len(v) for v in groups.values())
    codes = ", ".join(
        f"TC={tc} RC={rc}: {n} node(s)" for (tc, rc), n in sorted(stated.items()))
    msg = [
        f"*NODE: {total} node(s) state a constraint in the card's own TC/RC "
        f"cells ({codes}) — Vol I R17 p.35-2 makes card 1 'NID X Y Z TC RC', "
        "where TC and RC are constraint codes (0 none, 1 x, 2 y, 3 z, 4 xy, "
        "5 yz, 6 zx, 7 xyz) in the GLOBAL system, always active. "
        f"{emitted} node(s) were converted to {len(groups)} /GRNOD/NODE + "
        "/BCS group(s): "
        + ("; ".join(f"Tra {t} Rot {r}: {len(groups[(t, r)])} node(s)"
                     for t, r in sorted(groups)) if groups else "none")
        + "."]
    if rigid_dropped:
        msg.append(
            f" {len(rigid_dropped)} node(s) (node {_named(rigid_dropped)}) "
            "belong to a rigid body. A /BCS written on them would be INERT: "
            "rgbodv.F:150-155 rebuilds a /RBODY secondary's acceleration from "
            "the body after BCS10 has run (resol.F:7073 vs :7572) — measured "
            "identical to a free-fall control. LS-DYNA, however, DOES apply "
            "them, measured rather than assumed: on "
            "control_contact.hemi-draw part 4 (the Die: 525 nodes all at "
            "TC 7 / RC 7, *MAT_RIGID CMO 0, no *BOUNDARY_SPC and no "
            "*CONSTRAINED anywhere in the deck, not in the *RIGIDWALL node "
            "set, not the *BOUNDARY_PRESCRIBED_MOTION_RIGID target, and "
            "carrying up to 1.8e4 of interface-3 contact force) its own matsum "
            "holds the body at x-rbv = y-rbv = z-rbv = 0.0 at all 121 output "
            "times, while parts 2 and 3 — same *MAT_RIGID, TC codes unioning "
            "to x and z only — are held in x and z and move freely in y. "
            "Vol I R17 p.35-3 Remark 1 ('No attempt should be made to apply "
            "boundary conditions to nodes belonging to rigid bodies') is "
            "advice to the deck author, not a statement that the solver "
            "ignores them; only the IMPLICIT path prints Warning 60257 "
            "('skipping spc on rigid body node <n> tcode=<tc> rcode=<rc>', "
            "IMP+257 — 1 of the 16 R14 rule-(a) carriers, and there 2 of that "
            "deck's 3 rigid TC/RC nodes). So the cells are RE-POINTED onto the "
            "/RBODY main node, unioned per body, exactly as _make_bcs already "
            "does for a *BOUNDARY_SPC on a rigid member." + (
                " " + f"{len(rigid_repointed)} main node(s): "
                + ", ".join(
                    f"{m} -> {rigid_repointed[m][0]} {rigid_repointed[m][1]}"
                    f" (from {len(rigid_members.get(m, []))} member cell(s))"
                    for m in sorted(rigid_repointed)[:5])
                + (" ..." if len(rigid_repointed) > 5 else "") + "."
                if rigid_repointed else
                " Every one of them screened away to 000 000."))
    if rigid_orphans:
        msg.append(
            f" {len(rigid_orphans)} node(s) (node {_named(rigid_orphans)}) are "
            "rigid-body members whose body has no main node in rbody_info "
            "(a *CONSTRAINED_RIGID_BODIES merge whose master was itself "
            "dropped, say), so their cells are DROPPED rather than re-pointed "
            "— a /BCS on the secondary would be inert (rgbodv.F:150-155).")
    if motion_nodes:
        msg.append(
            f" {motion_dofs} DOF(s) on {len(motion_nodes)} node(s) (node "
            f"{_named(motion_nodes)}) are already driven by a "
            "*BOUNDARY_PRESCRIBED_MOTION and were left to it: a /BCS and an "
            "/IMPVEL on one DOF give starter WARNING 312 and a 99.9 percent "
            "engine energy error (measured on a one-brick twin: EXT-WORK 13.66 "
            "against an I-ENERGY of 1688). The node's remaining DOFs are still "
            "pinned.")
    if skewed_motion:
        msg.append(
            f" {len(skewed_motion)} node(s) (node {_named(skewed_motion)}) also "
            "carry an imposed motion written in a LOCAL system (/IMP* skew_ID "
            "!= 0). Its Dir letter is a skew axis, so no global TC/RC bit can "
            "be matched against it and NOTHING was cleared for those nodes — "
            "check whether the skew axis and the pinned global axis overlap.")
    if spc_nodes:
        msg.append(
            f" {spc_dof_count} DOF(s) on {len(spc_nodes)} node(s) (node "
            f"{_named(spc_nodes)}) are already stated by a *BOUNDARY_SPC (or a "
            "zero-scale *BOUNDARY_PRESCRIBED_MOTION) on the same node and were "
            "merged rather than restated: hm_read_bcs.F:198 unions the codes, "
            "so a second /BCS only adds starter WARNING 312.")
    if auto_nodes:
        msg.append(_rigid_auto_merge_sentence(auto_nodes, auto_dof_count,
                                              auto_titles,
                                              stab=auto_stab,
                                              stab_only=auto_stab_only,
                                              cmo_neg=auto_cmo_neg))
    if skew148:
        msg.append(_skew148_sentence(skew148, skew148_cards,
                                     "--no-node-tc-rc-bcs"))
    if skew_drop:
        msg.append(_skew_drop_sentence(skew_drop, skew_cards or {},
                                       "*NODE TC/RC"))
    if rot_inert:
        msg.append(
            f" {len(rot_inert)} node(s) (node {_named(rot_inert)}) got a "
            "rotational code on a mesh with no shell, beam, spring or rigid "
            "body — i.e. no rotational DOF at all. They are emitted, and they "
            "are inert on both sides: bcs10.F:66 applies the Rot digits only "
            "inside IF(IRODDL/=0), and LS-DYNA drops them too (they do not "
            "appear in its 'nodal spc summary on *NODE cards' d3hsp echo).")
    if emptied:
        msg.append(
            f" {len(emptied)} node(s) (node {_named(emptied)}) had every stated "
            "DOF removed by the screens above, so no /BCS was written for them.")
    msg.append(
        " Pass --no-node-tc-rc-bcs (convert(node_tc_rc_bcs=False)) to keep the "
        "pre-2026-09 behaviour, in which these DOFs are FREE.")
    state.warn("".join(msg))


def _warn_node_tc_rc_dropped(state: ConversionState) -> None:
    """The ``--no-node-tc-rc-bcs`` path: say what the deck loses.

    MEASURED on a spring-mass coupon whose anchor carried ``tc=7 rc=7``: no
    ``/BCS`` was emitted, the anchor was free, the whole oscillator drifted at
    the centre-of-mass velocity (node-2 DX reached 6.68 mm against an intended
    0.317 mm amplitude) — and the engine still printed NORMAL TERMINATION. The
    #122 class: legal, accepted, and wrong.
    """
    total = len(state.node_tc_rc)
    shown = _named(sorted(state.node_tc_rc))
    state.warn(
        f"*NODE: {total} node(s) state a constraint in the card's own TC/RC "
        f"cells (node {shown}), and --no-node-tc-rc-bcs "
        "(convert(node_tc_rc_bcs=False)) was passed — so those degrees of "
        "freedom are FREE in the converted model and no /BCS is emitted for "
        "them. Nothing in the run reports it: measured on a spring-mass coupon "
        "whose anchor carried tc=7/rc=7, the anchor was free and the whole "
        "oscillator drifted at the centre-of-mass velocity while the engine "
        "printed NORMAL TERMINATION. Drop the flag to convert them, or restate "
        "the constrained nodes as *BOUNDARY_SPC_NODE / *BOUNDARY_SPC_SET.")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: grounding springs  (force-control bootstrap stabilization)
# ─────────────────────────────────────────────────────────────────────────────

# *LOAD_RIGID_BODY translational DOF (1=Fx,2=Fy,3=Fz) → global axis index.
_FORCE_DOF_AXIS = {1: 0, 2: 1, 3: 2}


def _emit_spr_gene_dof_kc(k: float, c: float = 0.0, a: float = 0.0,
                          fct: int = 0, h: int = 0,
                          dmin: float = 0.0, dmax: float = 0.0,
                          fct2: int = 0, fct3: int = 0, fct4: int = 0,
                          b: float = 0.0, d: float = 0.0, e: float = 0.0,
                          hscale: float = 0.0) -> List[str]:
    """The 3 data lines of one /PROP/TYPE8 (SPR_GENE) DOF, with stiffness K,
    viscous C, scale A, an optional force function fct (+ hardening flag H) and
    the rupture displacements DeltaMin/DeltaMax. Zero-valued A/B/D and rupture
    fields take the reader defaults (A=1, B=0, ±1e30) — the same convention the
    validated grounding-spring emitter relies on.

    The un-indexed comment header is kept (rather than the DOF-numbered one
    /PROP/TYPE13 uses) so the grounding-spring and oriented-discrete-spring
    output stays byte-identical; new 6-DOF emitters use _emit_spring_dof."""
    return [
        "#                 K                   C                   A                   B                   D",
        f"{_f(k)}{_f(c)}{_f(a)}{_f(b)}{_f(d)}",
        "#  fct_ID1         H   fct_ID2   fct_ID3   fct_ID4                      DeltaMin            DeltaMax",
        f"{_i(fct)}{_i(h)}{_i(fct2)}{_i(fct3)}{_i(fct4)}          {_f(dmin)}{_f(dmax)}",
        "#                 F                   E              Ascale              Hscale",
        f"{_f(0.0)}{_f(e)}{_f(0.0)}{_f(hscale)}",
    ]


def _emit_spr_gene_dof(k: float) -> List[str]:
    """The 3 data lines of one /PROP/TYPE8 (SPR_GENE) DOF: a linear spring with
    only the stiffness K set (C=A=B=D=0, no function, no failure).

    Layout verified against the OpenRadioss source + hm_cfg and a validated run
    (add_grounding_springs.py): the reader forces A=1,B=0 and ±1e30 failure
    displacements when no function is given, so only K matters here.
    """
    return _emit_spr_gene_dof_kc(k)


def _make_grounding_springs(state: ConversionState, rbody_info: Dict) -> List[str]:
    """Inject soft /PROP/TYPE8 grounding springs on force-loaded rigid bodies
    (opt-in: --ground-springs). Returns [] when off → byte-identical output.

    A *LOAD_RIGID_BODY that pulls a rigid body held to ground only by
    clearance-fit penalty contact has a singular tangent in the loaded DOFs at
    t=0 (a rigid-body mode → MUMPS zero pivot / frozen residual; force control
    cannot bootstrap because load≈0 → the gap never closes → no stiffness). The
    Altair-documented fix (User Guide p.483) is a weak artificial spring on the
    free loaded DOFs: it removes the singular mode yet stays soft enough that
    contact carries the load once engaged (spring reaction ≈ k·u — a few % of
    the applied force at k=100 N/mm). Displacement control sidesteps this by
    imposing the motion; force control does not. See durable lesson #3.

    One zero-length SPR_GENE spring per loaded rigid body, from its /RBODY
    master node to a new fully-fixed ground node at the same location, with K on
    each loaded translational axis. A soft K on a DOF that is otherwise /BCS-
    constrained is inert, so spring-on-loaded-axes is safe and reproduces the
    validated RB_pull result (free Y+Z carry the pull; X stays fixed).
    """
    if not state.options.ground_springs or not state.load_rigid_bodies:
        return []

    # Union the loaded translational axes per rigid-body part (a |F| load, dof
    # 4, grounds all three; moments dof 5/6/7 are not sprung).
    axes_by_pid: Dict[int, Set[int]] = defaultdict(set)
    for lb in state.load_rigid_bodies:
        if lb.dof == 4:
            axes_by_pid[lb.pid] |= {0, 1, 2}
        elif lb.dof in _FORCE_DOF_AXIS:
            axes_by_pid[lb.pid].add(_FORCE_DOF_AXIS[lb.dof])

    if not axes_by_pid:
        return []

    k = state.options.ground_spring_k
    lines: List[str] = [
        "#-  GROUNDING SPRINGS (force-control bootstrap stabilization):", HDR]
    emitted = False

    for pid, axes in sorted(axes_by_pid.items()):
        info = rbody_info.get(pid)
        if info is None:
            state.warn(
                f"--ground-springs: *LOAD_RIGID_BODY pid={pid} has no rigid body "
                "(no /RBODY master node) — grounding spring skipped."
            )
            continue
        master = info["ind_node"]
        nd = state.nodes.get(master)
        if nd is None:
            state.warn(
                f"--ground-springs: rigid body pid={pid} master node {master} has "
                "no coordinates — grounding spring skipped."
            )
            continue

        # state.next_node_id(), not an open-coded max(state.nodes)+1 counter:
        # these ground nodes are deliberately NOT registered in state.nodes
        # (the /BCS beside them already fixes them), so a later synthesis site
        # taking max(state.nodes)+1 would reuse the same ids.
        ground_node = state.next_node_id()
        grnod_id = state.next_id()
        bcs_id = state.next_id()
        prop_id = state.next_prop_id()
        part_id = state.next_id()
        elem_id = state.next_id()
        kx = k if 0 in axes else 0.0
        ky = k if 1 in axes else 0.0
        kz = k if 2 in axes else 0.0
        axis_names = ",".join(
            n for n, on in zip("XYZ", (0 in axes, 1 in axes, 2 in axes)) if on)

        lines += [
            f"#-- master node {master}, axes {axis_names}, K={k:g} N/mm per loaded axis",
            "/NODE",
            f"{_i(ground_node)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}",
            f"/GRNOD/NODE/{grnod_id}",
            f"spring_ground_pid{pid}",
            f"{_i(ground_node)}",
            f"/BCS/{bcs_id}",
            f"fix_spring_ground_pid{pid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   111 111         0{_i(grnod_id)}",
            f"/PROP/TYPE8/{prop_id}",
            f"soft_ground_spring_pid{pid}",
            "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
            f"{_f(1.0e-4)}{_f(1.0e-6)}{_i(0) * 6}",
        ]
        # 6 DOF blocks: X Y Z RX RY RZ — K only on the loaded translational axes.
        lines += (_emit_spr_gene_dof(kx) + _emit_spr_gene_dof(ky) + _emit_spr_gene_dof(kz)
                  + _emit_spr_gene_dof(0.0) + _emit_spr_gene_dof(0.0) + _emit_spr_gene_dof(0.0))
        # Trailing strain-rate card (Fsmooth/Fcut). FORMAT(radioss2018) — the newest
        # SPR_GENE reader cfg ≤ /BEGIN-2022 — closes the /PROP/TYPE8 block with one
        # more "%10d%20lg" card (ISRATE, Asrate). Omitting it makes the reader run
        # past the property into the following /PART and raise WARNING 100217
        # ("card is missing"). Strain-rate smoothing off (ISRATE=0) → Asrate inert.
        lines += [
            "#  Fsmooth                Fcut",
            f"{_i(0)}{_f(0.0)}",
        ]
        lines += [
            f"/PART/{part_id}",
            f"soft_ground_spring_part_pid{pid}",
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{part_id}",
            "# sprg_ID  node_ID1  node_ID2",
            f"{_i(elem_id)}{_i(master)}{_i(ground_node)}",
            HDR,
        ]
        # /SPRING producer 5 of 9: the --ground-springs stabilizer. Its id is
        # minted by next_id() and matches no LS-DYNA element, so it stays out
        # of the three per-database sets — but it IS a /SPRING, so a
        # *DATABASE_HISTORY_BEAM/_DISCRETE id collision has to be able to see
        # it (state.spring_elem_ids answers "does a /SPRING with this id
        # exist?", nothing more).
        state.spring_elem_ids.add(elem_id)
        emitted = True
        state.warn(
            f"--ground-springs: injected a /PROP/TYPE8 grounding spring (K={k:g} "
            f"N/mm on axis/axes {axis_names}) from rigid-body pid={pid} master "
            f"node {master} to new fixed ground node {ground_node}. Removes the "
            "t=0 rigid-body singularity in the loaded DOFs; carries negligible "
            "load once contact engages. Remove if this is not force control "
            "through a clearance-fit contact."
        )

    return lines if emitted else []


class SpringDof:
    """One local DOF of a Radioss spring property (/PROP/TYPE4 slot 1, or one
    of the six blocks of /PROP/TYPE8 and /PROP/TYPE13).

    The three cards are byte-identical across all three properties (and across
    /MAT/LAW108 and /MAT/LAW113, whose bodies are the same blocks with RHO in
    place of Mass), so ONE payload object drives every spring emitter:

        K  C  A  B  D
        fct_ID1  H  fct_ID2  fct_ID3  fct_ID4  <10 blanks>  DeltaMin  DeltaMax
        F  E  Ascale  Hscale

    Force law (redef3.F90:1140-1148):
        F = f(δ)·[A + B·ln(max(1,|δ̇/D|)) + E·g(δ̇)] + C·δ̇ + Hscale·h(δ̇)
    with f = fct_ID1 (loading), g = fct_ID2 (rate scale), fct_ID3 the unloading
    curve used by H = 4/5/6/7/9, and h = fct_ID4 (extra damping force).

    ⚠ ``A`` is NOT a free scale factor on a PROPERTY-driven spring: the readers
    store the stiffness as ``K / A`` (hm_read_prop04.F:249, hm_read_prop08.F:282
    and hm_read_prop13.F:295, once per DOF), which exactly cancels the ``·A`` the
    engine applies in the no-function branch. /MAT/LAW108 and /MAT/LAW113 store
    XK raw (hm_read_mat108.F:271) and do NOT cancel. So dyna2rad's
    ``A1 = 1e-20`` trick for *MAT_S04's LCR (convertprops.cxx:974) is a LAW108-
    only device — writing it on a TYPE4/8/13 would multiply the time-step
    stiffness by 1e20 and collapse dt at cycle 0. Leave A at 0 (→ reader default
    1.0) unless the force really is scaled, and then pre-multiply K by A so the
    stored K/A is the true tangent.
    """

    __slots__ = ("k", "c", "a", "b", "d", "fct1", "h", "fct2", "fct3", "fct4",
                 "dmin", "dmax", "f", "e", "ascale", "hscale")

    def __init__(self, k: float = 0.0, c: float = 0.0, a: float = 0.0,
                 b: float = 0.0, d: float = 0.0, fct1: int = 0, h: int = 0,
                 fct2: int = 0, fct3: int = 0, fct4: int = 0,
                 dmin: float = 0.0, dmax: float = 0.0, f: float = 0.0,
                 e: float = 0.0, ascale: float = 0.0, hscale: float = 0.0):
        self.k, self.c, self.a, self.b, self.d = k, c, a, b, d
        self.fct1, self.h, self.fct2, self.fct3, self.fct4 = \
            fct1, h, fct2, fct3, fct4
        self.dmin, self.dmax = dmin, dmax
        self.f, self.e, self.ascale, self.hscale = f, e, ascale, hscale


def _as_spring_dof(dof) -> SpringDof:
    """Accept a SpringDof or the legacy ``(k, fct, h, dmin, dmax)`` 5-tuple the
    spotweld connectors pass — the tuple form maps onto a SpringDof whose other
    fields are all 0, i.e. byte-identical output."""
    if isinstance(dof, SpringDof):
        return dof
    k, fct, h, dmin, dmax = dof
    return SpringDof(k=k, fct1=fct, h=h, dmin=dmin, dmax=dmax)


def _emit_spring_dof(i: int, dof) -> List[str]:
    """The 6 lines (3 comments + 3 data cards) of spring DOF block *i* (1..6).

    Column layout is identical for /PROP/TYPE8, /PROP/TYPE13, /MAT/LAW108 and
    /MAT/LAW113: %20lg x5, then %10d x5 + 10 blanks + %20lg x2, then %20lg x4.
    Cols 51-60 of the middle card MUST stay blank at /BEGIN 2022 — they only
    become ``fct_ID5i`` at radioss2023."""
    d = _as_spring_dof(dof)
    return [
        f"#                 K{i}                  C{i}                  A{i}                  B{i}                  D{i}",
        f"{_f(d.k)}{_f(d.c)}{_f(d.a)}{_f(d.b)}{_f(d.d)}",
        f"# fct_ID1{i}        H{i}  fct_ID2{i}  fct_ID3{i}  fct_ID4{i}                     DeltaMin{i}           DeltaMax{i}",
        f"{_i(d.fct1)}{_i(d.h)}{_i(d.fct2)}{_i(d.fct3)}{_i(d.fct4)}          {_f(d.dmin)}{_f(d.dmax)}",
        f"#                 F{i}                  E{i}             Ascale{i}             Hscale{i}",
        f"{_f(d.f)}{_f(d.e)}{_f(d.ascale)}{_f(d.hscale)}",
    ]


def _emit_prop_type4(prop_id: int, title: str, mass: float, k: float, c: float,
                     a: float, fct1: int, hflag: int,
                     dmin: float, dmax: float, fct2: int = 0, fct3: int = 0,
                     fct4: int = 0, b: float = 0.0, d: float = 0.0,
                     e: float = 0.0, hscale: float = 0.0) -> List[str]:
    """/PROP/TYPE4 (SPRING). Layout: prop_p4_spring.cfg FORMAT(radioss140), the
    newest TYPE4 reader format ≤ /BEGIN-2022. Zero-valued A/B/D and rupture
    displacements take the reader defaults (A=1, B=0, D=1, ±1e30) — same
    convention the validated TYPE8 grounding-spring emitter relies on.

    The optional fct_ID21/31/41 + B/D/E/Hscale arguments carry the rate,
    unloading and damping-function slots the S03/S05/S06/S08 spring materials
    need; leaving them at their defaults reproduces the original card exactly.
    """
    return [
        f"/PROP/TYPE4/{prop_id}",
        title,
        "#               MASS                                 sens_ID    Isflag     Ileng",
        f"{_f(mass)}{' ' * 30}{_i(0)}{_i(0)}{_i(0)}",
        "#                  K                   C                   A                   B                   D",
        f"{_f(k)}{_f(c)}{_f(a)}{_f(b)}{_f(d)}",
        "# fct_ID11        H1  fct_ID21  fct_ID31  fct_ID41                      DeltaMin            DeltaMax",
        f"{_i(fct1)}{_i(hflag)}{_i(fct2)}{_i(fct3)}{_i(fct4)}          {_f(dmin)}{_f(dmax)}",
        "#                 F1                  E1             AScale1             HScale1",
        f"{_f(0.0)}{_f(e)}{_f(0.0)}{_f(hscale)}",
        HDR,
    ]


def _emit_prop_type8(prop_id: int, title: str, mass: float, inertia: float,
                     skew_id: int, dofs, ifail: int = 0, ifail2: int = 0,
                     iequil: int = 0) -> List[str]:
    """/PROP/TYPE8 (SPR_GENE). Layout: prop_p8_spr_gene.cfg FORMAT(radioss2018).

    Card 1 is ``Mass I skew_ID sens_ID Isflag Ifail Ifail2 Iequil`` — note the
    order differs from /PROP/TYPE13's ``… Ifail Ileng Ifail2``, and that TYPE8
    accepts Ifail2 ∈ {1,2} only (hm_read_prop08.F:150 forces anything else to 0;
    there is no energy criterion here).

    This is the SKEW-oriented 6-DOF spring: r2buf3.F builds the local triad
    entirely from the skew (per-element /SPRING Skew_ID first, else the property
    skew_ID, else global). It is the property-driven twin of /PROP/TYPE23 +
    /MAT/LAW108, with an absolute Mass in place of RHO×Volume.
    """
    lines = [
        f"/PROP/TYPE8/{prop_id}",
        title,
        "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
        f"{_f(mass)}{_f(inertia)}{_i(skew_id)}{_i(0)}{_i(0)}{_i(ifail)}{_i(ifail2)}{_i(iequil)}",
    ]
    for i, dof in enumerate(dofs, start=1):
        lines += _emit_spring_dof(i, dof)
    lines += [
        "#  Fsmooth                Fcut",
        f"{_i(0)}{_f(0.0)}",
        HDR,
    ]
    return lines


def _emit_prop_type13(prop_id: int, title: str, mass: float, inertia: float,
                      ifail: int, ifail2: int, dofs, ileng: int = 0,
                      skew_id: int = 0,
                      alpha_beta: Optional[List[Tuple[float, float]]] = None
                      ) -> List[str]:
    """/PROP/TYPE13 (SPR_BEAM). Layout: prop_p13_spr_beam.cfg
    FORMAT(radioss2018), the newest TYPE13 reader format ≤ /BEGIN-2022.
    ``dofs`` is 6 SpringDof (or legacy ``(k, fct_id, hflag, dmin, dmax)``
    tuples) for Tx Ty Tz Rx Ry Rz.
    With Ifail2=2 the DeltaMin/DeltaMax fields are failure FORCES (moments on
    the rotational DOFs); zero-valued fields take the ±1e30 'no failure'
    reader defaults.

    This is the NODE-oriented 6-DOF spring: r4buf3.F sets local X along
    node_ID1→node_ID2 and takes the XY plane from node_ID3 (falling back to the
    property skew's Y′). It is the property-driven twin of /PROP/TYPE23 +
    /MAT/LAW113. ``Ileng=1`` makes K, the input curves and the failure limits
    per unit length (strain based) — what *MAT_CABLE_DISCRETE_BEAM needs.

    ``alpha_beta`` fills the ``alpha_i`` / ``beta_i`` cells of the six
    trailing ``c n alpha beta`` lines (columns 41-60 / 61-80,
    ``%20lg%20lg%20lg%20lg``), DOF by DOF; the lines it does not reach stay
    0. With ``Ifail = 1`` the reader turns a zero ``alpha`` into 1 and a zero
    ``beta`` into 2 (``hm_read_prop13.F:1169-1170``), so a blank card is a
    QUADRATIC multi-directional criterion. Only the
    *CONSTRAINED_SPOTWELD / _GENERALIZED_WELD_SPOT weld tie passes a value
    (its deck N / M, round 6 A2); every other caller writes zeros, which is
    byte-identical to before."""
    lines = [
        f"/PROP/TYPE13/{prop_id}",
        title,
        "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail     Ileng    Ifail2",
        f"{_f(mass)}{_f(inertia)}{_i(skew_id)}{_i(0)}{_i(0)}{_i(ifail)}{_i(ileng)}{_i(ifail2)}",
    ]
    for i, dof in enumerate(dofs, start=1):
        lines += _emit_spring_dof(i, dof)
    lines += [
        "#                 Vo                  Wo                Fcut   Fsmooth",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_i(0)}",
    ]
    for i in range(1, 7):
        a, b = ((alpha_beta[i - 1] if alpha_beta is not None
                 and i <= len(alpha_beta) else (0.0, 0.0)))
        lines += [
            f"#                 c{i}                  n{i}              alpha{i}               beta{i}",
            f"{_f(0.0)}{_f(0.0)}{_f(a)}{_f(b)}",
        ]
    lines.append(HDR)
    return lines


def _pts_slope_at_origin(pts) -> float:
    """Slope of the segment spanning (or nearest to) the origin of a raw point
    list — the stiffness a nonlinear spring's force function implies there."""
    pts = sorted((float(a), float(o)) for a, o in pts)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x2 > x1 and x1 <= 0.0 <= x2:
            return (y2 - y1) / (x2 - x1)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x2 > x1:
            return (y2 - y1) / (x2 - x1)
    return 0.0


def _curve_slope_at_origin(curve: Curve) -> float:
    """Slope of the curve segment spanning (or nearest to) the origin — used as
    the /PROP/TYPE4 K (unloading / time-step stiffness) for a nonlinear
    spring's force-displacement function."""
    return _pts_slope_at_origin(curve.pts)


def _mirror_one_sided_curve(pts, tension_only: bool):
    """Mirror a ONE-SIDED force-displacement curve into the opposite quadrant.

    ``*MAT_SPRING_INELASTIC`` (S08) defines LCFD in the POSITIVE quadrant only
    whatever the tension/compression sense; CTF picks the sense. Radioss reads a
    spring function over the full displacement range and extrapolates the end
    segments, so a positive-only curve on a compression-only spring would invent
    a tensile force. dyna2rad's ``HandleCurveLCFD`` (convertprops.cxx:1066-1128)
    is reproduced here: an already two-quadrant curve is left alone, otherwise

      * ``CTF = -1`` (tension only)  → prepend ``(-1, 0)``: zero force in
        compression, the given branch in tension;
      * ``CTF = +1`` (compression only, the LS-DYNA default) → reflect the
        branch through the origin (x,y → -x,-y, order reversed) and close it off
        with ``(+1, 0)``.

    Returns the new point list; ``[]`` when the input cannot be used.
    """
    pts = sorted((float(a), float(o)) for a, o in pts)
    if len(pts) < 2:
        return []
    if pts[0][0] < 0.0:
        return pts                      # already spans both quadrants
    if tension_only:
        # Keep the positive branch; a flat zero-force point one unit into
        # compression makes the extrapolated compressive force zero.
        head = [(-1.0, 0.0)]
        if pts[0][0] > 0.0:
            head.append((0.0, 0.0))
        return head + pts
    # Compression only: reflect the branch through the origin, then close it
    # off with a flat zero-force point one unit into tension.
    out = [(-a, -o) for a, o in reversed(pts)]
    if out[-1][0] < 0.0:
        out.append((0.0, 0.0))
    return out + [(1.0, 0.0)]


def _plastic_to_total_disp(pts, stiff: float):
    """LS-DYNA PLASTIC-displacement abscissa → Radioss TOTAL displacement.

    ``*MAT_068``'s LCPD*/LCPM* curves and ``*MAT_196``'s TYPE≠0 FLCID give the
    yield force against the PLASTIC deformation; a Radioss spring function is
    read against the TOTAL deformation, so every abscissa gains the elastic part
    ``F/K`` (dyna2rad ``ConvertPlasticDispPointsTotalDisp``,
    convertmats.cxx:8862-8921). The curve is then mirrored through the origin so
    the spring yields symmetrically in compression, which is what LS-DYNA does
    for a one-sided plastic curve.

    Returns ``[]`` when *stiff* is zero (no elastic branch to add) or the curve
    is unusable, so the caller can warn instead of emitting nonsense.
    """
    pts = [(float(a), float(o)) for a, o in pts]
    if len(pts) < 2 or stiff == 0.0:
        return []
    pts.sort()
    if any(a < 0.0 for a, _ in pts):
        # Already a two-quadrant curve: keep the positive half only, so the
        # mirroring below stays symmetric (dyna2rad:8866-8883 does the same).
        pts = [p for p in pts if p[0] >= 0.0]
        if len(pts) < 2:
            return []
    total: List[Tuple[float, float]] = []
    for a, o in pts:
        x = a + o / stiff
        if total and x <= total[-1][0]:
            # Non-monotonic after the elastic shift: a Radioss function must
            # have strictly increasing abscissae, so nudge past the previous
            # point.
            prev = total[-1][0]
            x = prev + max(_PLASTIC_CURVE_EPS, abs(prev) * _PLASTIC_CURVE_REL)
        total.append((x, o))
    if total[0][0] > 0.0:
        total.insert(0, (0.0, 0.0))
    return [(-a, -o) for a, o in reversed(total) if a != 0.0] + total


#: Abscissa nudge that keeps a plastic→total curve strictly increasing
#: (dyna2rad hard-codes 0.01 at convertmats.cxx:8892, a unit-dependent magic
#: number). The step has to survive ``_f``'s %.10G card field, so it is RELATIVE
#: to the running abscissa with an absolute floor: 1e-9 alone vanishes at
#: |x| >= 10 (``_f(20.0)`` and ``_f(20.0 + 1e-9)`` are both "20"), which would
#: put a DUPLICATE abscissa on the card and earn starter ERROR 156. 1e-7
#: relative is two decades above the ten-significant-digit resolution and still
#: far below any meaningful deformation.
_PLASTIC_CURVE_EPS = 1.0e-9
_PLASTIC_CURVE_REL = 1.0e-7


def _curve_max_slope(curve: Curve) -> float:
    """The largest |secant slope| of a force-displacement function.

    ``hm_read_prop04.F``'s companion check (starter WARNING 506, "STIFFNESS
    VALUE IS NOT CONSISTENT WITH THE MAXIMUM SLOPE OF THE YIELD FUNCTION - THE
    STIFFNESS VALUE IS CHANGED") compares the spring's K against exactly this
    number and RAISES K itself when it is smaller. On an elastic-plastic spring
    (H != 0) K is the unloading stiffness, so letting the starter pick it means
    shipping a card whose physics is decided downstream — better to state it."""
    pts = sorted(curve.pts)
    best = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x2 > x1:
            best = max(best, abs((y2 - y1) / (x2 - x1)))
    return best


def _finite_length(state: ConversionState, e) -> bool:
    """True when a 2-node connector element has two REAL, distinct nodes — the
    precondition for any node-oriented frame (r4buf3.F builds local X from
    node1→node2 and answers WARNING 325 when it cannot). A grounded element
    (N2=0) fails it: its synthesized ground node sits on top of N1."""
    return _element_length(state, e) > 1e-12


def _element_length(state: ConversionState, e) -> float:
    """Distance between a 2-node connector element's nodes; 0 when either end
    is missing or the element is grounded (N2=0)."""
    if e.n1 <= 0 or e.n2 <= 0:
        return 0.0
    a, b = state.nodes.get(e.n1), state.nodes.get(e.n2)
    if a is None or b is None:
        return 0.0
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2
            + (a.z - b.z) ** 2) ** 0.5


#: Artificial mass every discrete-spring connector property carries. LS-DYNA's
#: discrete elements are massless (nodal mass comes from *ELEMENT_MASS) but
#: hm_read_prop04.F:136 rejects MASS <= 1e-15 outright (ERROR 229), and the
#: explicit time step needs a finite one.
_SPRING_TOKEN_MASS = 1.0e-4

#: The companion token INERTIA. /PROP/TYPE8 and /PROP/TYPE13 have no ERROR-229
#: floor (hm_read_prop08.F / hm_read_prop13.F check only the inertia, WARNING
#: 445), but a zero rotary inertia on a 6-DOF spring leaves r2len3.F's
#: rotational branch with no time step of its own. NOT compensated: the /ADMAS
#: card carries a MASS only (hm_read_admas.F), rotary inertia reaches a node
#: through /ADMAS/... type 4-6 or a rigid body's J cells, and no consumer of
#: this writer needs it. Named here so the value is not a bare literal at four
#: emission sites.
_SPRING_TOKEN_INERTIA = 1.0e-6

def _spring_kc(dofs, l13: float = 0.0
               ) -> Tuple[float, float, float, float]:
    """``(K_t, K_r, C_t, C_r)`` of a six-DOF spring property, as the ENGINE
    builds them for the element's own time step (SpringDof objects or the
    legacy 5-tuples).

    ``K_t`` / ``C_t``: the largest translational stiffness / damping
    (``r4def3.F:165-171``, ``r2def3.F:157-163``: ``XKM = MAX(XKA, YKA,
    ZKA)``). ``K_r`` / ``C_r``: the largest rotational ones, PLUS, on a
    ``/PROP/TYPE13`` (*l13* = the element length, 0 for any other type),
    the larger shear stiffness / damping times the length squared
    (``r4def3.F:173-174``, added at ``:545-548``: ``XKR = MAX(K4..K6) +
    MAX(K2, K3) * ALDP**2``) - the bending stiffness the two shear springs
    give the element. ``r2len3.F:221-247`` then takes
    ``min(M / (sqrt(C_t^2 + M K_t) + C_t), I / (sqrt(C_r^2 + I K_r) +
    C_r))``. An Ileng 1 property divides all four by the length afterwards
    (``r4def3.F:870-875``); the caller does that. The PRINTED K is used:
    where a force curve is steeper the starter raises K to its slope
    (``rkini3.F:73-80``, ``XK = MAX(XK, LSCALE*(B2-B1)/(A2-A1))`` at
    ``:79``) and the true step is shorter."""
    ds = [_as_spring_dof(d) for d in dofs]
    k_s = max([d.k for d in ds[1:3]] + [0.0])
    c_s = max([d.c for d in ds[1:3]] + [0.0])
    return (max([d.k for d in ds[:3]] + [0.0]),
            max([d.k for d in ds[3:6]] + [0.0]) + k_s * l13 * l13,
            max([d.c for d in ds[:3]] + [0.0]),
            max([d.c for d in ds[3:6]] + [0.0]) + c_s * l13 * l13)


def _register_spring_token_mass(state: ConversionState, n1: int, n2: int,
                                prop_mass: float = _SPRING_TOKEN_MASS,
                                spring: Optional[Tuple[int, float, float,
                                                       float, float,
                                                       float]] = None,
                                prop: Optional[Tuple[int, str, int,
                                                     float]] = None
                                ) -> None:
    """Record the invented property mass one emitted /SPRING row puts on its
    end nodes, for the /ADMAS compensation in :func:`_make_added_masses`.

    *spring* = ``(eid, I, K_t, K_r, C_t, C_r)`` of the row's property, the
    step quantities :func:`_spring_kc` builds (round 7, A5
    (iv)): recorded in ``state.spring_token_springs`` so the LIGHT clause of
    :func:`_warn_spring_token_mass` can state each light node's two-mass
    critical step against the spring's own step. Every registration site
    passes it; ``None`` records nothing (no clause numbers for that row).

    *prop* = ``(/PROP id, "TYPE4" | "TYPE8" | "TYPE13", Ileng, element
    length)`` of the row's token property (round 8, A5): recorded with the
    spring in ``state.spring_token_props``, so the adaptive-token pass
    (:func:`_adaptive_spring_token`) knows which emitted MASS cell carries
    this spring's token. The four token producers pass it.

    ``rinit3.F:1926`` is ``EMS(I) = HALF*UMASS(I)`` and ``:1937-1939`` writes
    ``MSR(1..3,I)`` onto ``IXR(2,I)`` and ``IXR(3,I)`` only — HALF the property
    mass on EACH end node, per element, and NOTHING on a TYPE13's third
    (orientation) node. On an ``Ileng=1`` property ``UMASS = mass x L_element``,
    so the caller passes the already-scaled value.

    ALWAYS call this at the line that WRITES the /SPRING row, never from the
    parsed element list: every producer has `continue`s above it that drop
    elements which never reach the deck, and a compensation for a spring that
    does not exist would remove real mass.

    Two masses are deliberately NOT registered through here:

    * ``PLOTEL_MASS`` (1.1e-15) — *ELEMENT_PLOTEL is a display-only element and
      that is the smallest value clearing the ERROR-229 floor at all, i.e. it
      is already the "no mass" answer rather than an invented one.
    * ``--ground-springs`` (:func:`_make_grounding_springs`) — an opt-in
      stabiliser the LS-DYNA deck does not state at all, so "compensating" it
      would take away mass the USER asked for.
    """
    share = 0.5 * prop_mass
    if share <= 0.0:
        return
    for _n in (n1, n2):
        if _n > 0:
            state.spring_token_mass_by_node[_n] = (
                state.spring_token_mass_by_node.get(_n, 0.0) + share)
    if spring is not None:
        eid, inertia, k_t, k_r, c_t, c_r = spring
        state.spring_token_springs.append(
            (eid, n1, n2, prop_mass, inertia, k_t, k_r, c_t, c_r))
        if prop is not None:
            state.spring_token_props[len(state.spring_token_springs) - 1] = prop


def _spring_token_mass_sentence(state: ConversionState, g_elems) -> str:
    """The sentence every discrete-spring warning ends with.

    It used to read *"The spring carries a small artificial mass (1e-4) for the
    explicit time step — add \\*ELEMENT_MASS-equivalent mass if dynamics of the
    spring ends matter."* — advice to ADD mass, when the defect is that k2rad
    had ADDED mass the LS-DYNA card does not carry. The measured consequence is
    a frequency error, so that is what it states now.
    """
    ends = sorted({n for e in g_elems for n in (e.n1, e.n2) if n > 0})
    head = (f"LS-DYNA discrete elements are MASSLESS (nodal mass comes from "
            f"*ELEMENT_MASS), but hm_read_prop04.F:136-142 refuses a property "
            f"MASS <= 1e-15 (ERROR 229), so k2rad writes a token "
            f"{_SPRING_TOKEN_MASS:g} and rinit3.F:1926/1937-1939 puts HALF of "
            f"it on EACH end node, per element.")
    if state.options.spring_token_mass_compensation:
        return (head + " That token is REMOVED again from those nodes - "
                "subtracted from an /ADMAS the deck already states, else taken "
                "off with a NEGATIVE /ADMAS of its own (hm_read_admas.F:"
                "164-170 accepts one, WARNING ID 476). The deck-level "
                "token-mass line below names every node and every class, "
                "including the ones no compensation can reach. "
                "Uncompensated the token shifts omega by "
                "sqrt(1 + m_token/(2*m_node)) - MEASURED on "
                "ex_17_spring_elform_0: 41.715 rad/s against LS-DYNA's 43.954, "
                "a 5.4 % frequency error that reads as IE +10.20 % / KE "
                "-99.27 % at t = 0.15 once the OFFSET pre-load is honoured.")
    return (head + " --no-spring-token-mass-compensation was passed, so it is "
            f"LEFT on node(s) {ends[:20]}"
            + (f" and {len(ends) - 20} more" if len(ends) > 20 else "")
            + ": the model's total mass is HIGH by "
              f"{_SPRING_TOKEN_MASS * len(g_elems):g} and every local "
              "frequency is LOW by sqrt(1 + m_token/(2*m_node)) - MEASURED on "
              "ex_17_spring_elform_0, 41.715 rad/s against LS-DYNA's 43.954, a "
              "5.4 % error.")


def _connector_inertia(state: ConversionState, elems) -> float:
    """The rotational inertia written on a synthesized 6-DOF spring property.

    ``rinit3.F:427-437`` measures every /PROP/TYPE8, /TYPE13 and /TYPE25 spring
    against ``RATIO = Mass·L²`` and answers WARNING 432 outside a factor of
    1000 either way, so an inertia k2rad invents should BE that reference
    rather than a fixed token: with the 1e-4 spring mass, a flat 1e-6 already
    trips the check at any element longer than ~3.2 length units. TYPE8 skips
    the check for zero-length elements only (``.NOT.((IGTYP == 8).AND.
    (LENGTH < EM15))``), which is exactly the grounded-spring case the 1e-20
    floor covers."""
    lens = [x for x in (_element_length(state, e) for e in elems) if x > 0.0]
    l_mean = (sum(lens) / len(lens)) if lens else 1.0
    return max(_SPRING_TOKEN_MASS * l_mean * l_mean, 1.0e-20)


def _emit_inert_spring_part(state: ConversionState, pid: int, title: str,
                            reason: str) -> List[str]:
    """An inert /PROP/TYPE4 + /PART for a discrete-spring part whose elements
    could not be converted.

    ``_discrete_part_ids`` claims the part unconditionally, so the ordinary
    /PART emitter skips it — dropping it here would delete the /PART id along
    with every *SET_PART member, /GRNOD/PART scope, contact and /TH channel
    that names it. The sibling discrete-BEAM writer guards the same hazard the
    same way (dbeam.py's ``wrong_section`` branch)."""
    state.warn(
        f"*ELEMENT_DISCRETE part {pid}: {reason} An INERT /PROP/TYPE4 + "
        f"/PART/{pid} (zero stiffness, token mass, no /SPRING) was written in "
        "its place so the part id stays addressable — a *SET_PART member, a "
        "/GRNOD/PART scope or a contact that names it would otherwise dangle.")
    prop_id = state.next_prop_id()
    return _emit_prop_type4(
        prop_id, f"{title} (inert - not converted)", _SPRING_TOKEN_MASS,
        0.0, 0.0, 0.0, 0, 0, 0.0, 0.0) + [
        f"/PART/{pid}",
        title,
        f"{_i(prop_id)}{_i(0)}{_i(0)}",
        HDR,
    ]


def _new_ground_node(state: ConversionState, at: NodeData) -> int:
    """Synthesize a fully-fixed ground node at *at*'s coordinates. Registered in
    state.nodes so later id allocations (e.g. --ground-springs) cannot collide,
    and in state.connector_ground_nodes so the implicit free-node guard skips
    it (it is already /BCS-fixed by the caller)."""
    nid = (max(state.nodes) + 1) if state.nodes else 90000001
    state.nodes[nid] = NodeData(at.x, at.y, at.z)
    state.connector_ground_nodes.add(nid)
    return nid


def _emit_spring_part(state: ConversionState, part_id: int, prop_id: int,
                      title: str, g_elems, pid: int,
                      spring_kind_label: str = "TYPE4",
                      spring_kc: Optional[Tuple[float, float, float,
                                                float, float]] = None
                      ) -> List[str]:
    """Emit /PART + /SPRING for a group of discrete elements on *prop_id*,
    synthesizing a fixed ground node (+ /BCS 111 111) for each grounded element
    (N2=0). Shared by the axial /PROP/TYPE4 and the oriented /PROP/TYPE8 paths.
    *spring_kc* = ``(I, K_t, K_r, C_t, C_r)`` of *prop_id*, recorded per row
    for the LIGHT clause of the token warning (round 7, A5 (iv))."""
    lines = [
        f"/PART/{part_id}",
        title,
        f"{_i(prop_id)}{_i(0)}{_i(0)}",
        f"/SPRING/{part_id}",
        "# sprg_ID  node_ID1  node_ID2",
    ]
    ground_nodes: List[int] = []
    for e in g_elems:
        n1, n2 = e.n1, e.n2
        if n1 <= 0 or n2 <= 0:
            anchor = n1 if n1 > 0 else n2
            nd = state.nodes.get(anchor)
            if nd is None:
                state.warn(f"*ELEMENT_DISCRETE {e.eid}: grounded "
                           f"element's node {anchor} has no "
                           "coordinates — element skipped.")
                continue
            gnid = _new_ground_node(state, nd)
            ground_nodes.append(gnid)
            n1, n2 = anchor, gnid
        lines.append(f"{_i(e.eid)}{_i(n1)}{_i(n2)}")
        # Recorded at the line that writes it, not from g_elems: the `continue`
        # just above drops a grounded element whose anchor node has no
        # coordinates, and *DATABASE_DEFORC must list only ids that reached the
        # deck (a /TH/SPRING on a missing element is starter ERROR 69).
        state.discrete_spring_eids.add(e.eid)
        state.spring_elem_ids.add(e.eid)      # producer 1 of 9
        # ... and the artificial mass this row puts on its two nodes, for the
        # /ADMAS compensation (rinit3.F:1926/1937-1939 — HALF the property mass
        # on EACH end node, per element). Recorded for BOTH nodes including a
        # synthesized ground node, so the tally is the deck's truth; the ground
        # node is /BCS-fixed and carries no /ADMAS, so nothing is subtracted
        # there and nothing is warned about it (see _spring_token_warn_nodes).
        _register_spring_token_mass(
            state, n1, n2,
            spring=((e.eid,) + spring_kc) if spring_kc is not None else None,
            prop=(prop_id, spring_kind_label, 0, 1.0))
    lines.append(HDR)
    if ground_nodes:
        grnod_id = state.next_grnod_id()
        bcs_id = state.next_id()
        lines.append("/NODE")
        for gnid in ground_nodes:
            nd = state.nodes[gnid]
            lines.append(f"{_i(gnid)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}")
        lines += _emit_grnod_node(grnod_id,
                                  f"discrete_ground_pid{pid}",
                                  ground_nodes)
        lines += [
            f"/BCS/{bcs_id}",
            f"fix_discrete_ground_pid{pid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   111 111         0{_i(grnod_id)}",
            HDR,
        ]
        state.warn(f"*ELEMENT_DISCRETE part {pid}: {len(ground_nodes)} "
                   "grounded element(s) (N2=0) tied to new fully-fixed "
                   "ground node(s) at the attached node's coordinates "
                   f"(zero-length {spring_kind_label} spring = central "
                   "restoring force toward the anchor point).")
    return lines


def _card_value(v: float) -> float:
    """The number the starter reads back from a ``_f`` field.

    ``_f`` prints %.10G (or %.6E outside 1e-4 .. 1e15), so the card carries ten
    significant digits — anything finer than that is invented precision that
    only exists in the converter."""
    return float(_f(v))


def _monotonic_abscissae(pts, state=None, label: str = ""):
    """Force a /FUNCT point list to be strictly increasing AS PRINTED.

    ``hm_read_funct.F:143`` refuses a function whose abscissa does not grow —
    ``IF (PLD(NPC(L+1)) <= PLD(NPC(L+1)-2)) ... MSGID = 156`` (MSGERROR), i.e.
    the deck is rejected, not degraded. The comparison the starter makes is on
    the CARD value, so the invariant has to be checked on ``_f``'s output and
    not on the float: a tie-break below the ten-digit field resolution survives
    in memory and disappears on the card (#113).

    TWO different defects reach this, and they get different repairs.

    **A TIE** (``_card_value(x) == prev``) is the original case: a builder that
    emits two points at one abscissa (the plastic->total mapping, the cable's
    zero-crossing insertion) or a nudge that the ten-digit field ate. The
    abscissa is stepped forward until the CARD value grows and the ordinate is
    kept — the curve was never ambiguous about its value there. A caller that
    passes a ``state`` and a ``label`` — today only the ``*DEFINE_CURVE``
    emitter, i.e. curves the DECK typed — also gets a warning for it, because
    on a user curve a duplicate abscissa is a STATEMENT: the common stepped
    shape ``(0,0),(1,0),(1,100),(2,100)`` means "jump at x = 1" and the repair
    turns it into a ramp across the nudge. The synthesized builders pass
    neither and stay silent, where the tie is their own rounding.

    **A REVERSAL** (``_card_value(x) < prev``) is a deck defect, and copying the
    ordinate would be wrong. LS-DYNA does not reorder such a curve either: it
    warns (``*** Warning 20446 ... load curve N x-axis reverses direction at
    point, K``) and then evaluates it with a forward-walking segment search that
    can simply never select the reversed interval, so the value JUMPS at the
    reversal and continues on the segment that starts at the out-of-order point.
    MEASURED on ``mat_spring.belted-dummy`` (curve 50, point 26 at x = 0.1125
    after 0.1195, driving a ``*BOUNDARY_PRESCRIBED_MOTION`` acceleration): node
    1763's x-acceleration is 5.15057E+03 at t = 0.119275 and jumps to
    6.85894E+03 at t = 0.119512, whose back-extrapolated slope -419917 per unit
    t hits -9810 at t = 0.1124843 and -2450 at t = 0.130012 — i.e. exactly the
    segment (0.1125, -9810) -> (0.13, -2450), the pair AS WRITTEN.

    So the reversed point is replaced by ``(prev + eps, f(prev))`` where ``f``
    is the segment from it to the NEXT point — the value LS-DYNA jumps TO. On
    that curve f(0.1195) = -6866.0 — exactly what this rule writes,
    -9810 + 0.4*7360 — and the three candidates differ by far more
    than round-off: a plain nudge (keep the ordinate) evaluates 9801.6 at
    t = 0.119512 (+43 % against LS-DYNA's 6858.94), re-SORTING by abscissa gives
    4907 (-28 %), this rule gives 6860.96 (+0.03 %) — the emitted curve read
    at the nodout SAMPLE time 0.119512, not at the re-anchored abscissa
    itself. When there is no next point
    to anchor to — the reversal is the LAST point — it is DROPPED, because
    LS-DYNA can never evaluate past ``prev`` there either.

    Points already strictly increasing are returned unchanged, so the emitted
    card is byte-identical for every well-formed curve. *state* and *label* are
    optional so the connector-inline callers keep working; when they are given,
    every repair is named.
    """
    out: List[Tuple[float, float]] = []
    pts = list(pts)
    for k, (a, o) in enumerate(pts):
        x, y = float(a), float(o)
        if out:
            prev = _card_value(out[-1][0])
            if _card_value(x) < prev:
                # REVERSAL. Re-anchor onto the segment that leaves this point.
                nxt = next(((float(p[0]), float(p[1])) for p in pts[k + 1:]
                            if _card_value(float(p[0])) > prev), None)
                if nxt is None:
                    if state is not None:
                        state.warn(
                            f"{label}: the abscissa reverses direction at "
                            f"point {k + 1} (x = {x:g} after {prev:g}) and no "
                            "later point lies beyond it, so the point is "
                            "DROPPED. LS-DYNA warns (Warning 20446 'x-axis "
                            "reverses direction at point') and then never "
                            "evaluates it either — its forward-walking segment "
                            "search cannot enter a backwards interval — while "
                            "Radioss REFUSES a non-increasing abscissa "
                            "outright (hm_read_funct.F:143, ERROR 156). Check "
                            "the curve: a genuinely non-monotone (x, y) data "
                            "set must state DATTYP = 1 (Vol I R17 p.17-106).")
                    continue
                x2, y2 = nxt
                y = y + (y2 - y) * (prev - x) / (x2 - x) if x2 != x else y2
                if state is not None:
                    state.warn(
                        f"{label}: the abscissa reverses direction at point "
                        f"{k + 1} (x = {x:g} after {prev:g}) — LS-DYNA itself "
                        "flags this (Warning 20446, 'load curve N x-axis "
                        "reverses direction at point, K') and then evaluates "
                        "the curve by SKIPPING the reversed interval, so its "
                        f"value jumps from {float(o):g} to {y:.6g} at "
                        f"x = {prev:g} and follows the segment ({x:g}, "
                        f"{float(o):g}) -> ({x2:g}, {y2:g}). Radioss REFUSES a "
                        "non-increasing abscissa outright "
                        "(hm_read_funct.F:143, ERROR 156), so k2rad emits the "
                        "curve LS-DYNA ACTUALLY EVALUATES: this point becomes "
                        f"(~{prev:g}, {y:.6g}). Keeping the stated ordinate "
                        "instead would be a 43 % error on the corpus carrier, "
                        "and re-sorting by abscissa a -28 % one. The source "
                        "deck's DATTYP = 0 declares a MONOTONE curve (Vol I "
                        "R17 p.17-106; DATTYP = 1 is the escape for "
                        "non-monotone data), so this pair is a deck defect — "
                        "check it.")
            tied = _card_value(x) == prev
            step = max(abs(prev), 1.0) * 1.0e-8
            for _ in range(64):
                if _card_value(x) > prev:
                    break
                x = prev + step
                step *= 2.0
            if tied and state is not None:
                # A tie on a SYNTHESIZED curve is the builder's own rounding
                # and says nothing to the reader; a tie on a curve the DECK
                # typed is a statement — the common stepped shape
                # (0,0),(1,0),(1,100),(2,100) means "jump at x = 1", and the
                # repair silently turns it into a steep ramp. Master emitted
                # the duplicate and let the starter refuse it with ERROR 156,
                # which at least said something, so the repair must not be the
                # quieter of the two. Only the callers that pass a `label`
                # (today: the *DEFINE_CURVE emitter) reach this.
                state.warn(
                    f"{label}: two points share the abscissa x = {prev:g} "
                    f"(point {k + 1}), which Radioss refuses outright "
                    "(hm_read_funct.F:143, ERROR 156 — it compares the CARD "
                    "value, so the duplicate has to be broken on the printed "
                    f"number). k2rad nudges the second to {x:.10g} and KEEPS "
                    f"its ordinate {y:g}. If this pair was meant as a STEP — "
                    "the (0,0),(1,0),(1,100),(2,100) shape LS-DYNA evaluates "
                    "as a jump — it is now a ramp across that nudge, which is "
                    "a different function at exactly one point. State the two "
                    "abscissae a real distance apart if the width matters.")
        out.append((x, y))
    return out


def _emit_funct(fid: int, title: str, pts, smooth: bool = False) -> List[str]:
    """A /FUNCT written INLINE in a connector section.

    The single /FUNCT emitter (materials.py::_make_functions) runs at the
    "functions" step, which is BEFORE every connector step in the writer
    dispatch, so a curve registered in state.curves from here would never reach
    the deck. Connector-synthesized functions are therefore written where they
    are built — the same thing the spotweld bilinear-axial function does.

    ``smooth=True`` writes /FUNCT_SMOOTH instead, with the neutral
    Ascalex/Fscaley/Ashiftx/Fshifty card materials._make_functions writes. That
    is NOT cosmetic: the ISMOOTH flag it sets makes the /IMP* consumers blend
    with the quintic smoothstep instead of interpolating linearly, which is a
    different motion for the same points (MEASURED on the /IMPDISP/FGEO path:
    f = 0.1035673 against the plain twin's 0.2503 at u = 0.25). A caller that
    copies or shifts a *DEFINE_CURVE_SMOOTH must keep the flag.

    The two consumers dispatch through DIFFERENT routines, and only one of them
    clamps — do not state the clamp as a property of the flag:

    * /IMPDISP/FGEO — fixfingeo.F:194-199 picks FINTER2 or FINTER2_SMOOTH.
      FINTER2_SMOOTH (finter_smooth.F:116-152) has NO clamp: it walks IPOS to
      the last segment and evaluates the quintic with u > 1, so past the last
      point the smooth curve extrapolates FASTER than the plain one (measured
      f = -7.62 vs -1.50 at the same instant).
    * /IMPVEL — fixvel.F:314/316 calls VINTER_SMOOTH, which DOES clamp per
      segment (vinter_smooth.F:68-71 returns the segment end ordinate outside
      [X_FIRST, X_LAST]).

    FINTER_SMOOTH (finter_smooth.F:71/74), the third routine and the other one
    that clamps, is called by gravit.F/forcefingeo.F and by neither of these."""
    if smooth:
        lines = [f"/FUNCT_SMOOTH/{fid}", title[:100],
                 "#            Ascalex             Fscaley             "
                 "Ashiftx             Fshifty",
                 f"{_f(1.0)}{_f(1.0)}{_f(0.0)}{_f(0.0)}",
                 "#                  X                   Y"]
    else:
        lines = [f"/FUNCT/{fid}", title[:100],
                 "#                  X                   Y"]
    for a, o in _monotonic_abscissae(pts):
        lines.append(f"{_f(a)}{_f(o)}")
    lines.append(HDR)
    return lines


def _shift_curve_abscissae(pts, offset: float):
    """*pts* with every abscissa reduced by *offset*, ordinates untouched.

    Radioss's spring deflection is purely geometric — ``r1def3.F:206``
    ``DL(I) = ALDP(I) - AL0DP(I)`` — so an ``*ELEMENT_DISCRETE`` ``OFFSET``,
    which LS-DYNA defines as "a displacement or rotation at time zero"
    (Vol I R17 p.19-33), makes ``delta_LS = delta_RAD + OFFSET``. The exact
    restatement of ``F = f_LS(delta_LS)`` in the Radioss variable is therefore
    ``f_RAD(d) = f_LS(d + OFFSET)``: a pure SHIFT of the abscissae by
    ``-OFFSET``, with the ordinates unchanged. Nothing else in the law moves.
    """
    return [(a - offset, o) for a, o in pts]


def _curve_value_at(pts, x: float) -> float:
    """Linear interpolation of *pts* at *x*, extrapolating the end segments.

    That is what the engine does with a spring function (``redef3.F90`` reads
    it through the ordinary FINTER path, which walks to the bracketing segment
    and evaluates it), so the pre-stretch force this returns is the one the
    run would develop.
    """
    if not pts:
        return 0.0
    if len(pts) == 1:
        return pts[0][1]
    if x <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    elif x >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
    else:
        i = 0
        while i + 2 < len(pts) and pts[i + 1][0] < x:
            i += 1
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _emit_inispri_full_type4(records) -> List[str]:
    """``/INISPRI/FULL`` for ``prop_type`` 4 springs: ``[(spring_id, EI), …]``.

    Layout from ``hm_cfg_files/.../TABLE/inispri_full_subobject_type_4_12.cfg``
    ``FORMAT(radioss2018)`` — one record per spring, three cards:

        ``# springID prop_type     nvars``      ``%10d%10d%10d``
        ``#  F_X  D_X  FEP_X  DPL_X+  DPL_X-``  ``%20lg`` x5
        ``#  L_X  EI``                          ``%20lg%20lg``

    The header itself carries NO title line: ``inispri.cfg``'s
    ``CARD_PREREAD("%10s%10d",_BLANK_,prop_type)`` reads ``prop_type`` out of
    the FIRST record's own card, so the records follow the keyword directly and
    every record in one block must share a ``prop_type``.

    Only ``EI`` is written. ``hm_read_inistate_d00.F:4598-4606`` maps the cells
    to ``SIGRS(2..8)`` and ``rinit3.F:2024-2036`` (``R4INI``) unpacks them into
    ``F0 / DL0 / FEP / DPL / DPL2 / XL0 / EINT`` — so a non-zero ``F_X`` or
    ``D_X`` would state a force and an elongation the geometry does not have,
    and ``L_X`` must stay 0 because ``rinit3.F:2022`` initialises ``XL0`` to
    zero for exactly the "not concerned by INISPRI" case that
    ``r1def3.F:150-151`` then treats as "length not initialised". The energy is
    the only datum an OFFSET really carries: LS-DYNA's own ``ex_17`` ``glstat``
    reads ``internal energy 2.82451E+02`` at ``t = 0`` against a ``deforc``
    ``y-force 2.22402E+01`` at ``change in length 2.54000E+01``, i.e. exactly
    ``1/2 * f(OFFSET) * OFFSET``.
    """
    if not records:
        return []
    lines: List[str] = ["/INISPRI/FULL"]
    for spring_id, ei in records:
        lines += [
            "# springID prop_type     nvars",
            f"{_i(spring_id)}{_i(4)}{_i(0)}",
            "#                F_X                 D_X               FEP_X"
            "              DPL_X+              DPL_X-",
            f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
            "#                L_X                  EI",
            f"{_f(0.0)}{_f(ei)}",
        ]
    lines.append(HDR)
    return lines


def _s03_curve_points(k: float, kt: float, fy: float):
    """The 5-point symmetric elastic-plastic force function of *MAT_S03.

    dyna2rad (convertprops.cxx:923) synthesizes

        (-(FY/K + 1), -(FY + KT))  (-FY/K, -FY)  (0,0)  (FY/K, FY)
        (FY/K + 1, FY + KT)

    i.e. an elastic branch of slope K up to the yield force FY, then a plastic
    branch of slope KT carried ONE displacement unit past yield (Radioss
    extrapolates the last segment, so the branch continues at slope KT beyond
    it). Returns [] when the card cannot produce a usable curve."""
    if k <= 0.0 or fy <= 0.0:
        return []
    dy = fy / k
    return [(-(dy + 1.0), -(fy + kt)), (-dy, -fy), (0.0, 0.0),
            (dy, fy), (dy + 1.0, fy + kt)]


def _make_discrete_springs(state: ConversionState) -> List[str]:
    """*ELEMENT_DISCRETE + *SECTION_DISCRETE + a discrete spring/damper material
    → /PROP/TYPE4 (SPRING) + /PART + /SPRING.

    Materials: ``*MAT_SPRING_ELASTIC`` (S01), ``*MAT_SPRING_ELASTOPLASTIC``
    (S03), ``*MAT_SPRING_NONLINEAR_ELASTIC`` (S04),
    ``*MAT_DAMPER_NONLINEAR_VISCOUS`` (S05),
    ``*MAT_SPRING_GENERAL_NONLINEAR`` (S06), ``*MAT_SPRING_INELASTIC`` (S08) and
    ``*MAT_DAMPER_VISCOUS`` (S02). Every one of them is a 1-DOF connector and
    lands in the single DOF block of a /PROP/TYPE4, which carries the full
    Radioss spring law — loading function, hardening flag, rate function,
    unloading function, damping function and the rupture displacements — so no
    /MAT is written and the /PART keeps mat_id 0.

    dyna2rad instead pairs an (initially empty) /MAT/LAW108 with a /PROP/TYPE23
    and fills the stiffness in from the property pass; the card BODY is the same
    six DOF blocks either way, and the property-driven route avoids TYPE23's
    "a /PART on it must carry a MID whose law is 108/113/114/135" rule
    (hm_read_part.F, ERROR 179 / ERROR 1715).

    A grounded element (N2=0) gets a fixed ground node at N1's coordinates +
    /BCS 111 111 (the _make_grounding_springs pattern); the zero-length TYPE4
    spring then acts as a central restoring force F=K·|d| toward the anchor —
    TYPE4 explicitly allows zero-length springs.

    A DRO=1 (torsional) section puts the same payload on the ROTATIONAL DOF of a
    6-DOF property instead: /PROP/TYPE13 slot 4 (Rx = torsion about the element's
    own n1→n2 axis) for an unoriented spring, /PROP/TYPE8 slot 4 for one carrying
    a *DEFINE_SD_ORIENTATION. LS-DYNA already states a DRO=1 spring in
    moment-per-radian, which is exactly what the Radioss rotational slot wants,
    so no unit conversion applies — only the DOF changes.

    A part whose material, curve or elements cannot be converted still gets an
    INERT /PROP/TYPE4 + /PART (``_emit_inert_spring_part``): the pid is claimed
    by ``_discrete_part_ids`` either way, so dropping it would delete the /PART
    id from under every *SET_PART member, /GRNOD/PART scope, contact and /TH
    channel that names it."""
    if not state.discrete_elems:
        return []
    lines: List[str] = [
        "#-  DISCRETE SPRING/DAMPER CONNECTORS (*ELEMENT_DISCRETE -> /PROP/TYPE4 + /SPRING):",
        HDR]
    emitted = False

    by_pid: Dict[int, List] = defaultdict(list)
    for e in state.discrete_elems:
        by_pid[e.pid].append(e)

    # *MAT_SPRING_MUSCLE (S15) parts belong to _make_muscle_springs, which
    # writes their /PART + /PROP/TYPE46 + /SPRING. BOTH writers would emit
    # /PART/<pid> under the source pid, so a part claimed by both is ERROR 79.
    muscle_pids = _muscle_discrete_pids(state)

    inispri_records: List[Tuple[int, float]] = []
    for pid in sorted(by_pid):
        if pid in muscle_pids:
            continue
        elems = by_pid[pid]
        part = state.parts.get(pid)
        if part is None:
            state.warn(f"*ELEMENT_DISCRETE: part {pid} is not defined — "
                       f"{len(elems)} discrete element(s) skipped.")
            continue
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_discrete.get(secid)
        if sec is None:
            state.warn(f"*ELEMENT_DISCRETE part {pid}: no *SECTION_DISCRETE "
                       f"{secid} found — a default translational section is "
                       "assumed (no failure deflection).")
            sec = SectionDiscrete(secid, "")
        torsional = sec.dro == 1
        title = part.title or f"DISCRETE_{pid}"

        # Material → the single spring DOF (K / C / A / B / D, fct_ID1..4, H).
        k = c = 0.0
        b_coef = d_coef = e_coef = hscale = 0.0
        fct1 = fct2 = fct3 = fct4 = 0
        hflag = 0
        kind = None
        funct_lines: List[str] = []
        # The POINTS behind fct_ID11, whatever built it — a deck *DEFINE_CURVE
        # (state.curves) or one this writer synthesized here (whose id is a
        # next_curve_id() and is therefore NOT in state.curves). The OFFSET
        # abscissa shift needs them, and a shift that silently found nothing
        # would ship an unshifted law.
        fct1_pts: Optional[List[Tuple[float, float]]] = None
        mat_lin = state.mat_spring_elastic.get(part.mid)
        mat_nl = state.mat_spring_nonlinear.get(part.mid)
        mat_dmp = state.mat_damper_viscous.get(part.mid)
        mat_ep = state.mat_spring_elastoplastic.get(part.mid)
        mat_nlv = state.mat_damper_nl_viscous.get(part.mid)
        mat_gnl = state.mat_spring_general_nl.get(part.mid)
        mat_inel = state.mat_spring_inelastic.get(part.mid)
        if mat_lin is not None:
            k = mat_lin.k
            kind = "linear spring"
        elif mat_nl is not None:
            curve = state.curves.get(mat_nl.lcd)
            if curve is None or len(curve.pts) < 2:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_NONLINEAR_ELASTIC {part.mid}'s load curve "
                    f"LCD={mat_nl.lcd} is not defined, so its {len(elems)} "
                    "element(s) carry no force at all.")
                emitted = True
                continue
            fct1 = mat_nl.lcd            # curve is already emitted as /FUNCT
            fct1_pts = list(curve.pts)
            hflag = 0                    # H=0: nonlinear ELASTIC (S04 semantics)
            k = _curve_slope_at_origin(curve)
            if k <= 0.0:
                state.warn(f"*MAT_SPRING_NONLINEAR_ELASTIC {part.mid}: LCD "
                           f"{mat_nl.lcd} has a non-positive slope at the "
                           "origin — TYPE4 K left 0 (engine time-step/unloading "
                           "stiffness); verify the curve.")
                k = 0.0
            if mat_nl.lcr:
                # LS-DYNA S04 is F = LCD(δ)·LCR(δ̇). The Radioss spring law is
                # F = f(δ)·[A + B·ln(…) + E·g(δ̇)] + …, so an exact match needs
                # A = 0 and E = 1 — and A = 0 is re-defaulted to 1 by the
                # reader, giving f·(1 + g). dyna2rad dodges that with A = 1e-20
                # (convertprops.cxx:974), which is only legal on /MAT/LAW108:
                # the PROPERTY readers store the stiffness as K/A
                # (hm_read_prop04.F:249), so A = 1e-20 would multiply the
                # time-step stiffness by 1e20 and collapse dt at cycle 0.
                state.warn(f"*MAT_SPRING_NONLINEAR_ELASTIC {part.mid}: rate "
                           f"scale curve LCR={mat_nl.lcr} has no /PROP/TYPE4 "
                           "slot that reproduces F=LCD(d)*LCR(d/dt) — the "
                           "spring is converted RATE-INDEPENDENT (F=LCD(d)). "
                           "The A=1e-20 trick dyna2rad uses is a /MAT/LAW108 "
                           "device: a property-driven spring stores K/A, so it "
                           "would blow up the time step. Fold the rate scale "
                           "into LCD if it matters.")
            kind = "nonlinear elastic spring"
        elif mat_ep is not None:
            pts = _s03_curve_points(mat_ep.k, mat_ep.kt, mat_ep.fy)
            if not pts:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_ELASTOPLASTIC {part.mid} states K="
                    f"{mat_ep.k:g}/FY={mat_ep.fy:g}, and both must be positive "
                    "to place the yield point (the elastic branch is FY/K "
                    f"wide), so its {len(elems)} element(s) carry no force.")
                emitted = True
                continue
            fct1 = state.next_curve_id()
            fct1_pts = list(pts)
            funct_lines = _emit_funct(
                fct1, f"MATS03_elastoplastic_mid{part.mid}", pts)
            k = mat_ep.k
            hflag = 1                    # isotropic hardening, unloads along K
            kind = "elastoplastic spring"
        elif mat_nlv is not None:
            if not mat_nlv.lcdr or mat_nlv.lcdr not in state.curves:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_DAMPER_NONLINEAR_VISCOUS {part.mid}'s force-vs-rate "
                    f"curve LCDR={mat_nlv.lcdr} is not defined, so its "
                    f"{len(elems)} element(s) carry no damping force.")
                emitted = True
                continue
            # fct_ID41 is h(δ̇), added to the force as Hscale·h(δ̇) — exactly
            # LS-DYNA's F = LCDR(δ̇). Hscale = 0 takes the reader default 1.0.
            fct4 = mat_nlv.lcdr
            kind = "nonlinear viscous damper"
        elif mat_gnl is not None:
            if not mat_gnl.lcdl or mat_gnl.lcdl not in state.curves:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_GENERAL_NONLINEAR {part.mid}'s loading curve "
                    f"LCDL={mat_gnl.lcdl} is not defined, so its {len(elems)} "
                    "element(s) carry no force.")
                emitted = True
                continue
            fct1 = mat_gnl.lcdl
            fct1_pts = list(state.curves[mat_gnl.lcdl].pts)
            # H=6 makes K1 the UNLOADING stiffness, and the starter refuses to
            # let it be smaller than the loading curve's steepest segment: it
            # raises it silently under WARNING 506. State it instead, so the
            # hysteresis loop the deck runs is the one the card says.
            k = _curve_max_slope(state.curves[mat_gnl.lcdl])
            if mat_gnl.lcdu and mat_gnl.lcdu in state.curves:
                fct3 = mat_gnl.lcdu
                hflag = 6                # iso. hardening + nonlinear unloading
            else:
                # H=6 with fct_ID31 = 0 is a hard starter ERROR 1057
                # (hm_read_prop04.F:171). Demote rather than emit a deck that
                # cannot start.
                hflag = 0
                state.warn(f"*MAT_SPRING_GENERAL_NONLINEAR {part.mid}: "
                           f"LCDU={mat_gnl.lcdu} (the unloading curve) is "
                           "missing, and H=6 without fct_ID31 is starter ERROR "
                           "1057 — the spring was DEMOTED to H=0 (nonlinear "
                           "ELASTIC: it unloads along the loading curve and "
                           "dissipates nothing). Supply LCDU to keep the "
                           "hysteresis.")
            # BETA is tested against 1.0, NOT against 0: LS-DYNA's BLANK
            # default BETA=0.0 selects "tensile and compressive yield with
            # strain SOFTENING" and any other non-unit value selects KINEMATIC
            # hardening (Manual Vol II R17 p.2-2087) — both differ from the
            # isotropic H=6 that is emitted. BETA=1.0 is the one value that
            # matches it exactly, so it is the one value that must stay silent.
            dropped = [n for n, v in (("TYI", mat_gnl.tyi),
                                      ("CYI", mat_gnl.cyi)) if v]
            if mat_gnl.beta != 1.0:
                dropped.insert(0, f"BETA={mat_gnl.beta:g}")
            if dropped:
                state.warn(f"*MAT_SPRING_GENERAL_NONLINEAR {part.mid}: "
                           f"{', '.join(dropped)} have no Radioss spring slot "
                           "— dropped. BETA selects LS-DYNA's hardening "
                           "flavour (0.0, the BLANK DEFAULT = tensile and "
                           "compressive yield with strain softening; 1.0 = "
                           "isotropic; anything else = kinematic) and TYI/CYI "
                           "the initial tensile/compressive yield; the "
                           "converted spring always uses the ISOTROPIC rule "
                           "H=6 with the yield taken from the loading curve. "
                           "Radioss's kinematic flag H=4 is not an option — "
                           "hm_read_prop04.F:157 rejects it outright when K=0 "
                           "and LAW108 rejects it unconditionally (ERROR 230).")
            kind = "general nonlinear spring"
        elif mat_inel is not None:
            curve = state.curves.get(mat_inel.lcfd)
            if curve is None or len(curve.pts) < 2:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_INELASTIC {part.mid}'s force-vs-displacement "
                    f"curve LCFD={mat_inel.lcfd} is not defined, so its "
                    f"{len(elems)} element(s) carry no force.")
                emitted = True
                continue
            pts = _mirror_one_sided_curve(curve.pts, mat_inel.ctf < 0.0)
            if not pts:
                lines += _emit_inert_spring_part(
                    state, pid, title,
                    f"*MAT_SPRING_INELASTIC {part.mid}'s LCFD "
                    f"{mat_inel.lcfd} could not be mirrored into the opposite "
                    f"quadrant, so its {len(elems)} element(s) carry no force.")
                emitted = True
                continue
            fct1 = state.next_curve_id()
            fct1_pts = list(pts)
            side = "tension" if mat_inel.ctf < 0.0 else "compression"
            funct_lines = _emit_funct(
                fct1, f"MATS08_{side}_only_mid{part.mid}", pts)
            k = mat_inel.ku
            if k > 0.0:
                # LS-DYNA S08 unloads along max(KU, max loading slope) — that
                # is precisely Radioss H=1 (elastic-plastic, unloading with K).
                # dyna2rad leaves H at 0 here (convertprops.cxx:1000-1028),
                # which silently turns the INELASTIC spring into a nonlinear
                # ELASTIC one that dissipates nothing; k2rad sets the flag.
                hflag = 1
            else:
                state.warn(f"*MAT_SPRING_INELASTIC {part.mid}: KU (the "
                           "unloading stiffness) is blank, so there is no "
                           "slope to unload along — the spring is converted "
                           "as nonlinear ELASTIC (H=0) and dissipates NO "
                           "energy. Give KU to keep the inelastic loop.")
            state.warn(f"*MAT_SPRING_INELASTIC {part.mid}: LCFD "
                       f"{mat_inel.lcfd} is one-sided (CTF={mat_inel.ctf:g} = "
                       f"{side} only), so it was mirrored into the opposite "
                       f"quadrant and closed off with a flat zero-force point "
                       f"-> /FUNCT/{fct1} ({len(pts)} points). Radioss reads a "
                       "spring function over the whole displacement range and "
                       "extrapolates its end segments, so an unmirrored curve "
                       "would invent force on the inactive side.")
            kind = "inelastic spring"
        elif mat_dmp is not None:
            c = mat_dmp.dc
            kind = "viscous damper"
        else:
            lines += _emit_inert_spring_part(
                state, pid, title,
                f"material {part.mid} is not a discrete spring/damper material "
                "k2rad converts (S01/S02/S03/S04/S05/S06/S08), so its "
                f"{len(elems)} element(s) carry no force.")
            emitted = True
            continue

        if sec.kd or sec.v0:
            state.warn(f"*SECTION_DISCRETE {secid}: KD={sec.kd:g}/V0={sec.v0:g} "
                       "(the dynamic magnification F=(1+KD·V/V0)·F_static) has "
                       "no Radioss spring slot that reproduces it — DROPPED, "
                       "the spring is converted rate-independent. The nearest "
                       "equivalent is a B/D log-rate pair or an fct_ID21 rate "
                       "curve on the property; state it there if the "
                       "magnification carries load.")
        if sec.cl:
            state.warn(f"*SECTION_DISCRETE {secid}: CL={sec.cl:g} (clearance — "
                       "a non-zero value makes the LS-DYNA spring "
                       "COMPRESSION-ONLY with CL of free travel first) has no "
                       "Radioss spring field and is DROPPED: the converted "
                       "spring carries load in both directions from zero "
                       "displacement. Restate it as a shifted, one-sided "
                       "force-displacement function if it matters.")
        # Failure deflections: TDL/CDL deflection limits and the FD failure
        # deflection map to the TYPE4 rupture displacements (element deletion
        # in both codes). 0 = no limit (reader default ±1e30).
        dmax = sec.tdl if 0.0 < sec.tdl < 1e19 else 0.0
        dmin = -sec.cdl if 0.0 < sec.cdl < 1e19 else 0.0
        if sec.fd > 0.0:
            dmax = min(dmax, sec.fd) if dmax else sec.fd
        elif sec.fd < 0.0:
            dmin = max(dmin, sec.fd) if dmin else sec.fd

        # Per-element force scale S becomes a cloned property per distinct S:
        # linear K/C scale directly; a nonlinear function is scaled through the
        # A coefficient (F = f(δ)·A when B=0). Elements oriented by a
        # *DEFINE_SD_ORIENTATION (VID) that resolved to a /SKEW are grouped by
        # (vid, S) onto an oriented /PROP/TYPE8; everything else is axial
        # /PROP/TYPE4.
        # Keyed on (S, OFFSET), not on S alone: a non-zero OFFSET is honoured
        # by SHIFTING the force function's abscissae by -OFFSET, which is a
        # different /FUNCT and therefore a different /PROP — exactly as a
        # different force scale already was. With every element at OFFSET 0
        # (every deck on this corpus but ex_17 and ex_18) the grouping, the
        # property ids and the emitted bytes are unchanged.
        groups: Dict[Tuple[float, float], List] = defaultdict(list)
        ori_groups: Dict[Tuple[int, float, float], List] = defaultdict(list)
        n_vid = 0
        n_bad = 0
        for e in elems:
            if e.n1 <= 0 and e.n2 <= 0:
                n_bad += 1
                continue
            if e.vid:
                if state.sdorient_skew_ids.get(e.vid) is None:
                    n_vid += 1
                    continue
                if e.offset:
                    # REFUSED BY NAME rather than emitted: an oriented section
                    # puts the payload on slot 1 (or 4) of a /PROP/TYPE8, whose
                    # /INISPRI/FULL record is the SIX-DOF subobject
                    # (inispri_full_subobject_type_8_13_25.cfg, prop_type 8),
                    # a card shape nothing on any roster exercises. Reach 0 on
                    # 885 decks — an unmeasured card is not shipped.
                    state.warn(
                        f"*ELEMENT_DISCRETE {e.eid}: OFFSET={e.offset:g} (Vol I "
                        "R17 p.19-33, 'a displacement or rotation at time zero') "
                        "is DROPPED on this element, so it starts at zero force "
                        "instead of the pre-stretched state the card names. The "
                        "abscissa-shift + /INISPRI/FULL restatement k2rad "
                        "applies to an axial spring is NOT applied here: this "
                        "element is oriented by *DEFINE_SD_ORIENTATION "
                        f"VID={e.vid}, so it becomes a 6-DOF /PROP/TYPE8 whose "
                        "/INISPRI/FULL record is the type-8/13/25 subobject - a "
                        "card shape with no carrier on any corpus here and "
                        "therefore unmeasured. Restate the offset as a shifted, "
                        "one-sided force-displacement function if it carries "
                        "load.")
                ori_groups[(e.vid, e.s if e.s else 1.0, e.offset)].append(e)
                continue
            groups[(e.s if e.s else 1.0, e.offset)].append(e)
        if n_vid:
            state.warn(f"*ELEMENT_DISCRETE part {pid}: {n_vid} element(s) "
                       "reference a *DEFINE_SD_ORIENTATION VID that is undefined "
                       "or uses IOP=1/3 (an unsupported spring-axis projection) "
                       "— those elements were NOT converted.")
        if n_bad:
            state.warn(f"*ELEMENT_DISCRETE part {pid}: {n_bad} element(s) have "
                       "no valid nodes — skipped.")

        # MASS: LS-DYNA discrete elements are massless (nodal mass comes from
        # *ELEMENT_MASS); OpenRadioss wants a spring mass > 0 for the explicit
        # time step. _SPRING_TOKEN_MASS is the same inert token mass the
        # validated grounding-spring emitter uses.
        part_id_used = [False]

        def _alloc_part_id():
            if not part_id_used[0]:
                part_id_used[0] = True
                return pid          # keep the DYNA part id for traceability
            return state.next_id()

        def _scaled(s, fct=None):
            """(K, C, A, Hscale) for a per-element force scale S.

            *fct* overrides the part's own ``fct_ID11`` — the OFFSET path
            hands in the abscissa-SHIFTED clone, and a linear spring that had
            no function at all acquires one there, which moves the scale from
            K/C onto the A coefficient exactly as a deck-supplied curve would.

            With no function the force is K·δ and A cancels out entirely (the
            reader stores K/A, the engine multiplies by A again), so K and C
            are scaled directly. With a loading function the force is f(δ)·A,
            so A carries the scale — but then the STORED stiffness is K/A, and
            the true scaled tangent is S·K, so K must be pre-multiplied by S²
            for K/A to come out right. Leaving that out understates the
            time-step stiffness by S² on a scaled nonlinear spring.

            ``A`` does NOT reach the fct_ID4 damping force: the engine adds it
            as a separate ``Hscale·h(δ̇)`` term (redef3.F90:1143), so a
            curve-driven damper (*MAT_S05, whose whole payload sits on
            fct_ID41 with K = C = 0) needs the scale on Hscale or S is lost
            without a trace."""
            fct_eff = fct1 if fct is None else fct
            a_coef = 0.0            # 0 → reader default 1.0
            k_s, c_s, h_s = k, c, hscale
            if s != 1.0:
                if fct_eff:
                    a_coef = s      # scales f(δ) (A coefficient, B=0)
                    k_s, c_s = k * s * s, c * s
                else:
                    k_s, c_s = k * s, c * s
                if fct4:
                    # 0 → reader default 1.0, so the unscaled base is 1.
                    h_s = (hscale or 1.0) * s
            return k_s, c_s, a_coef, h_s

        def _dof(s, fct=None):
            """The loaded SpringDof for per-element force scale *s*."""
            fct_eff = fct1 if fct is None else fct
            k_s, c_s, a_coef, h_s = _scaled(s, fct_eff)
            return SpringDof(k=k_s, c=c_s, a=a_coef, b=b_coef, d=d_coef,
                             fct1=fct_eff, h=hflag, fct2=fct2, fct3=fct3,
                             fct4=fct4, dmin=dmin, dmax=dmax, e=e_coef,
                             hscale=h_s)

        def _offset_law(offset: float, s: float, g_elems):
            """(fct_ID11, extra /FUNCT lines, [(spring_id, EI), …]) for a
            group whose elements carry ``OFFSET``.

            Returns ``(fct1, [], [])`` unchanged when there is no offset to
            honour (or ``--no-discrete-offset`` was passed), so the OFFSET-free
            path below is byte-identical to the pre-round-4 writer.
            """
            if not offset:
                return fct1, [], []
            if not state.options.discrete_offset:
                state.warn(
                    f"*ELEMENT_DISCRETE part {pid}: OFFSET={offset:g} on "
                    f"{len(g_elems)} element(s) is DROPPED "
                    "(--no-discrete-offset). LS-DYNA develops a force at "
                    "t = 0 from it (Vol I R17 p.19-33); the converted spring "
                    "starts unstressed.")
                return fct1, [], []
            if torsional:
                # Same refusal as the oriented branch, for the same reason: a
                # DRO=1 section is a /PROP/TYPE13, whose /INISPRI/FULL record
                # is the type-8/13/25 six-DOF subobject. Reach 0 on 885 decks.
                state.warn(
                    f"*ELEMENT_DISCRETE part {pid}: OFFSET={offset:g} on "
                    f"{len(g_elems)} element(s) is DROPPED. *SECTION_DISCRETE "
                    f"{secid} is TORSIONAL (DRO=1), so the spring becomes a "
                    "6-DOF /PROP/TYPE13 whose /INISPRI/FULL record is the "
                    "type-8/13/25 subobject - a card shape with no carrier on "
                    "any corpus here and therefore unmeasured. The axial "
                    "abscissa-shift restatement is not applied; the converted "
                    "spring starts at zero moment.")
                return fct1, [], []
            if fct1:
                if not fct1_pts:
                    state.warn(
                        f"*ELEMENT_DISCRETE part {pid}: OFFSET={offset:g} is "
                        f"DROPPED - fct_ID11={fct1}'s points could not be "
                        "resolved, so there is nothing to shift. The converted "
                        "spring starts unstressed.")
                    return fct1, [], []
                base_pts = fct1_pts
                shifted = _shift_curve_abscissae(base_pts, offset)
                new_fct = state.next_curve_id()
                extra = _emit_funct(
                    new_fct,
                    f"discrete_offset_{offset:g}_from_fct{fct1}_pid{pid}",
                    shifted)
                f_at = _curve_value_at(base_pts, offset)
            else:
                # No loading function: *MAT_SPRING_ELASTIC's K is the whole
                # law, so synthesize the two points of f(d) = K*(d + OFFSET).
                # Two points are exact for a linear law (Radioss extrapolates
                # a spring function's end segments), and K STAYS on the card -
                # r1len3.F reads it for the element time step and for
                # MAX_SLOPE, and hm_read_prop04.F:249 stores it as K/A.
                if k <= 0.0:
                    state.warn(
                        f"*ELEMENT_DISCRETE part {pid}: OFFSET={offset:g} is "
                        f"DROPPED - material {part.mid} states no positive "
                        "stiffness and no loading function, so there is no "
                        "law to shift. The converted spring starts unstressed.")
                    return fct1, [], []
                lo, hi = sorted((-2.0 * offset, offset))
                pts2 = [(lo, k * (lo + offset)), (hi, k * (hi + offset))]
                new_fct = state.next_curve_id()
                extra = _emit_funct(
                    new_fct, f"discrete_offset_{offset:g}_K_pid{pid}", pts2)
                f_at = k * offset
            # LS-DYNA's own datum: the energy already stored in the spring at
            # t = 0. ex_17's glstat reads internal energy 2.82451E+02 against a
            # deforc y-force 2.22402E+01 at a change in length 2.54000E+01,
            # i.e. exactly 1/2 * f(OFFSET) * OFFSET. The per-element force
            # scale S multiplies the force, so it multiplies the energy too.
            ei = 0.5 * s * f_at * offset
            recs = [(e.eid, ei) for e in g_elems]
            if dmin or dmax:
                state.warn(
                    f"*SECTION_DISCRETE {secid}: TDL/CDL/FD deflection limits "
                    f"({dmin:g} .. {dmax:g}) are written to the /PROP/TYPE4 "
                    "rupture cells UNSHIFTED while OFFSET="
                    f"{offset:g} shifts the deflection datum by that much - "
                    "LS-DYNA measures its deflection limits on the OFFSET "
                    "side of the datum and Radioss on the geometric side, and "
                    "no deck on any corpus here states both, so which one the "
                    "limits belong to is UNMEASURED. Check the rupture "
                    "displacements if they carry load.")
            return new_fct, extra, recs

        # ── translational (axial) springs → /PROP/TYPE4 ────────────────────
        # A DRO=1 torsional section cannot use TYPE4 (a purely translational
        # 1-DOF property): the payload moves to slot 4 (Rx) of a /PROP/TYPE13,
        # whose local X is node1→node2 by construction (r4buf3.F:145), so the
        # torsion acts about the element's own axis exactly as in LS-DYNA.
        pid_emitted = False
        for (s, offset) in sorted(groups):
            g_elems = groups[(s, offset)]
            if torsional:
                usable = [e for e in g_elems if _finite_length(state, e)]
                if len(usable) < len(g_elems):
                    state.warn(
                        f"*SECTION_DISCRETE {secid}: {len(g_elems) - len(usable)}"
                        f" of part {pid}'s DRO=1 (torsional) element(s) are "
                        "ZERO-LENGTH or grounded (N2=0), so there is no "
                        "node1->node2 axis to twist about — those elements were "
                        "NOT converted. Give the torsional spring a second "
                        "node, or orient it with a *DEFINE_SD_ORIENTATION "
                        "(VID), which k2rad puts on a skew-oriented "
                        "/PROP/TYPE8 instead.")
                    g_elems = usable
                if not g_elems:
                    continue
            prop_id = state.next_prop_id()
            part_id = _alloc_part_id()
            if part_id != pid:
                state.warn(f"*ELEMENT_DISCRETE part {pid}: elements with force "
                           f"scale S={s:g}"
                           + (f" / OFFSET={offset:g}" if offset else "")
                           + f" were split onto auto part {part_id} "
                           "(the per-element scale has no /SPRING field).")
            eff_fct, off_funct, off_recs = _offset_law(offset, s, g_elems)
            inispri_records += off_recs
            lines += funct_lines
            funct_lines = []       # one /FUNCT, shared by every scaled clone
            lines += off_funct     # the OFFSET clone is per (S, OFFSET) group
            if torsional:
                dofs = [SpringDof(), SpringDof(), SpringDof(),
                        _dof(s, eff_fct), SpringDof(), SpringDof()]
                tors_i = _connector_inertia(state, g_elems)
                lines += _emit_prop_type13(
                    prop_id, f"{title} ({kind}, torsional DRO=1)",
                    _SPRING_TOKEN_MASS, tors_i,
                    0, 0, dofs)
                kc = (tors_i,) + _spring_kc(dofs)
            else:
                k_s, c_s, a_coef, h_s = _scaled(s, eff_fct)
                lines += _emit_prop_type4(
                    prop_id, f"{title} ({kind})", _SPRING_TOKEN_MASS, k_s, c_s,
                    a_coef, eff_fct, hflag, dmin, dmax, fct2=fct2, fct3=fct3,
                    fct4=fct4, b=b_coef, d=d_coef, e=e_coef, hscale=h_s)
                kc = (0.0, k_s, 0.0, c_s, 0.0)
            lines += _emit_spring_part(
                state, part_id, prop_id, title, g_elems, pid,
                spring_kind_label="TYPE13" if torsional else "TYPE4",
                spring_kc=kc)
            emitted = pid_emitted = True
            state.warn(f"*ELEMENT_DISCRETE part {pid} ({kind}, "
                       f"{len(g_elems)} element(s)) -> "
                       + (f"/PROP/TYPE13/{prop_id} (SPR_BEAM): the section is "
                          "torsional (DRO=1), so the payload sits on local DOF "
                          "4 (Rx = rotation about the node1->node2 axis) and "
                          "K/C are read as MOMENT per radian and per rad/s — "
                          "the units LS-DYNA already states them in, so "
                          "nothing is rescaled"
                          if torsional else f"/PROP/TYPE4/{prop_id}")
                       + f" + /SPRING on /PART/{part_id}."
                       + (f" OFFSET={offset:g} is honoured by SHIFTING the "
                          f"force law's abscissae by {-offset:g} onto "
                          f"/FUNCT/{eff_fct} (Vol I R17 p.19-33: OFFSET is 'a "
                          "displacement or rotation at time zero ... a "
                          "positive offset on a translational spring will lead "
                          "to a tensile force being developed at time zero', "
                          "and Radioss spring deflection is purely geometric - "
                          "r1def3.F:206 DL = ALDP - AL0DP - so delta_LS = "
                          "delta_RAD + OFFSET and f_RAD(d) = f_LS(d + OFFSET)), "
                          "plus an /INISPRI/FULL carrying the pre-stretch "
                          f"energy EI = 1/2*f(OFFSET)*OFFSET = "
                          f"{(off_recs[0][1] if off_recs else 0.0):g}."
                          if off_recs else "")
                       + " " + _spring_token_mass_sentence(state, g_elems))

        # ── oriented springs → /PROP/TYPE8 (SPR_GENE) on the VID's /SKEW ────
        # Only TYPE8 carries a skew_ID, so an oriented discrete element becomes a
        # SPR_GENE whose local DOF 1 (Tx) acts along the skew's local X (= the
        # *DEFINE_SD_ORIENTATION axis); DOFs 2-6 stay inert.
        # A DRO=1 section puts the payload on slot 4 instead: the skew's local X
        # IS the *DEFINE_SD_ORIENTATION axis, so Rx is rotation about it.
        slot = 4 if torsional else 1
        for (vid, s, offset) in sorted(ori_groups):
            g_elems = ori_groups[(vid, s, offset)]
            skew_id = state.sdorient_skew_ids[vid]
            prop_id = state.next_prop_id()
            part_id = _alloc_part_id()
            k_s, c_s, a_coef, h_s = _scaled(s)
            lines += funct_lines
            funct_lines = []
            lines += [
                f"/PROP/TYPE8/{prop_id}",
                f"{title} ({kind}, oriented VID {vid})",
                "#               Mass             Inertia   skew_ID   sens_ID    Isflag     Ifail   Ifail2     Iequil",
                f"{_f(_SPRING_TOKEN_MASS)}{_f(_connector_inertia(state, g_elems))}"
                f"{_i(skew_id)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}{_i(0)}",
            ]
            for j in range(1, 7):
                if j == slot:
                    lines += _emit_spr_gene_dof_kc(
                        k_s, c_s, a_coef, fct1, hflag, dmin, dmax,
                        fct2=fct2, fct3=fct3, fct4=fct4, b=b_coef, d=d_coef,
                        e=e_coef, hscale=h_s)
                else:
                    lines += _emit_spr_gene_dof_kc(0.0)
            lines += [
                "#  Fsmooth                Fcut",
                f"{_i(0)}{_f(0.0)}",
            ]
            ori_i = _connector_inertia(state, g_elems)
            lines += _emit_spring_part(
                state, part_id, prop_id, title, g_elems, pid,
                spring_kind_label="TYPE8",
                spring_kc=((ori_i, 0.0, k_s, 0.0, c_s) if slot == 4 else
                           (ori_i, k_s, 0.0, c_s, 0.0)))
            emitted = pid_emitted = True
            state.warn(
                f"*ELEMENT_DISCRETE part {pid} ({kind}, {len(g_elems)} "
                f"element(s)) oriented by *DEFINE_SD_ORIENTATION VID={vid} -> "
                f"/PROP/TYPE8/{prop_id} (SPR_GENE) + /SPRING on /PART/{part_id} "
                f"with skew_ID={skew_id}; stiffness on local DOF {slot} ("
                + ("rotation about" if torsional else "translation along")
                + " the orientation axis). "
                + _spring_token_mass_sentence(state, g_elems))

        if not pid_emitted:
            # Every element was filtered out (grounded/zero-length under DRO=1,
            # node-less, or bound to an unresolved *DEFINE_SD_ORIENTATION), so
            # no /PART was written above — but the pid is still claimed by
            # _discrete_part_ids and would vanish from the deck entirely.
            lines += _emit_inert_spring_part(
                state, pid, title,
                f"none of its {len(elems)} element(s) could be converted.")
            emitted = True

    # ONE /INISPRI/FULL block for the whole deck: inispri.cfg's
    # CARD_PREREAD("%10s%10d", _BLANK_, prop_type) reads prop_type out of the
    # FIRST record, so every record in a block must share it. Only prop_type 4
    # (axial /PROP/TYPE4) is written — the 6-DOF subobject of TYPE8/TYPE13 is
    # refused by name where the OFFSET is read.
    if inispri_records:
        lines += _emit_inispri_full_type4(inispri_records)

    return lines if emitted else []


# *ELEMENT_PLOTEL part / property id. LS-DYNA Vol I R17, *ELEMENT_PLOTEL
# Remark 1: "Part ID, 10000000, is assigned to PLOTEL elements." The card has no
# PID column at all, so the converter has to fabricate the part; dyna2rad picks
# the same id (convertelements.cxx:242-262).
PLOTEL_ID = 10000000
# /PROP/TYPE4 MASS. hm_read_prop04.F:136-142 rejects MASS <= 1e-15 outright:
#   IF(GEO(1)<=EM15) ... ANCMSG(MSGID=229) -> "** ERROR IN SPRING PROPERTY (MASS)"
# so this is the smallest legal value with a margin, and it is exactly what
# dyna2rad writes (1.1*pow(10.0,-15)). k2rad's /BEGIN gives the input and work
# unit systems the same values, so the comparison is against the same number the
# card carries.
PLOTEL_MASS = 1.1e-15


def _spring_eid_families(state: ConversionState) -> List[Tuple[str, Set[int]]]:
    """Every /SPRING element id k2rad takes VERBATIM from the source deck.

    Radioss has ONE /SPRING element-id namespace, but LS-DYNA hands these
    families three separate ones, so ids that are legal input collide after
    conversion (starter ERROR 79, DUPLICATE ID, IN SPRING ELEMENT DEFINITION,
    and no restart file):

      * ``*ELEMENT_DISCRETE``  → ``_make_discrete_springs`` / the grounding
        springs, keyed on the discrete EID;
      * ``*ELEMENT_BEAM`` on a *MAT_SPOTWELD (MAT_100) part →
        ``_make_spotweld_beam_connectors``, keyed on the BEAM EID;
      * ``*ELEMENT_BEAM`` on a *SECTION_BEAM ELFORM=6 discrete-beam part →
        ``_make_discrete_beam_connectors``, also keyed on the BEAM EID (so the
        two beam families cannot clash with each other — their part sets are
        disjoint — but both can clash with the discrete and PLOTEL springs);
      * ``*ELEMENT_PLOTEL`` → ``_make_plotel_elements``, keyed on the PLOTEL EID;
      * ``*ELEMENT_SEATBELT`` (1D) → ``_make_seatbelts``, keyed on the BELT
        EID — a FIFTH LS-DYNA namespace, so a belt element and a discrete
        spring may legally share an id in the source deck and both become
        ``/SPRING`` in the same one.

    The joint (/PROP/TYPE45) and *CONSTRAINED_SPOTWELD springs are not listed:
    their ids come from ``next_id()`` during section emission, so they are
    unique by construction and not yet allocated when this runs.
    """
    weld_pids = _spotweld_beam_pids(state)
    dbeam_pids = _discrete_beam_pids(state)
    muscle_pids = _muscle_beam_pids(state)
    return [
        ("*ELEMENT_DISCRETE", {d.eid for d in state.discrete_elems}),
        ("*ELEMENT_BEAM on a *MAT_MUSCLE truss part",
         {b.eid for b in state.beam_elems if b.pid in muscle_pids}),
        ("*ELEMENT_BEAM on a *MAT_SPOTWELD part",
         {b.eid for b in state.beam_elems if b.pid in weld_pids}),
        ("*ELEMENT_BEAM on a *SECTION_BEAM ELFORM=6 discrete-beam part",
         {b.eid for b in state.beam_elems if b.pid in dbeam_pids}),
        ("*ELEMENT_PLOTEL", {p.eid for p in state.plotel_elems}),
        ("*ELEMENT_SEATBELT (1D belt)",
         {e.eid for e in state.seatbelt_elems if not e.is_2d}),
    ]


def _warn_spring_eid_collisions(state: ConversionState) -> None:
    """Report every source-deck id two /SPRING families would both claim."""
    fams = [(name, eids) for name, eids in _spring_eid_families(state) if eids]
    for i, (name_a, eids_a) in enumerate(fams):
        for name_b, eids_b in fams[i + 1:]:
            clash = eids_a & eids_b
            if not clash:
                continue
            state.warn(
                f"{len(clash)} element id(s) are used by BOTH {name_a} and "
                f"{name_b} (first: {sorted(clash)[0]}). LS-DYNA keeps those in "
                "separate id namespaces, but both convert to /SPRING, which is "
                "ONE namespace in the starter — the deck will be rejected with "
                "ERROR 79 (DUPLICATE ID, IN SPRING ELEMENT DEFINITION). "
                "Renumber one of the two families in the .k file.")


def _make_plotel_elements(state: ConversionState) -> List[str]:
    """*ELEMENT_PLOTEL → inert /SPRING + one /PART + one /PROP/TYPE4.

    PLOTEL is a pure visualization line: it must add NO stiffness, NO mass and
    must not govern the time step. /PROP/TYPE4 with K=0, C=0 does all three:

      * NODAL stiffness — r1len3.F:81-105 initialises STI(1,I)=STI(2,I)=ZERO and
        only overwrites them when XK/=0 or XC/=0, so a K=C=0 spring contributes
        exactly zero to the nodal time step of the parts it is drawn on.
      * ELEMENT time step — r1len3.F:139, DT = XM/MAX(EM15, SQRT(XC²+XM·XK)+XC).
        With K=C=0 the denominator floors at the EM15 clamp instead of going to
        zero, giving DT = M/1e-15 ~ 1.1 s raw; the starter's damping-limit term
        (rinit3.F, DTC = HALF*XM/MAX(EM15,XCM)) halves it, and the element table
        prints 0.55 s — MEASURED, against 1.67e-6 s for the shells of the same
        deck, so it never governs. (The MASS>1e-15 hard error is what keeps M
        out of the DT=0 branch at r1len3.F:143.)
      * Mass — 1.1e-15 per element, split over its two nodes. It DOES show up in
        the starter's TOTAL MASS echo (1.2560000000000E-05 -> 1.2560000003300E-05
        Mg for three PLOTELs, a 2.6e-10 relative change); every structural part
        mass, the time step and the result history are bit-identical.

    Everything else stays at the /PROP/TYPE4 reader defaults (no functions, no
    rupture limits), matching dyna2rad, which sets MASS and nothing else.
    """
    if not state.plotel_elems:
        return []

    # Prefer the LS-DYNA id, but never collide: /PART and /PROP ids are checked
    # against what the deck already occupies (k2rad emits /PROP/SHELL|SOLID|BEAM
    # under the SECID verbatim), because a duplicate is starter ERROR 79.
    part_id = (PLOTEL_ID if PLOTEL_ID not in state.parts
               else state.next_part_id())
    prop_id = PLOTEL_ID
    if (PLOTEL_ID in state.sec_shells or PLOTEL_ID in state.sec_solids
            or PLOTEL_ID in state.sec_beams):
        prop_id = state.next_prop_id()

    lines: List[str] = [
        "#-  PLOTEL VISUALIZATION ELEMENTS (*ELEMENT_PLOTEL -> inert /SPRING):",
        HDR,
    ]
    lines += _emit_prop_type4(prop_id, "PLOTEL", PLOTEL_MASS, 0.0, 0.0, 0.0,
                              0, 0, 0.0, 0.0)
    lines += [
        f"/PART/{part_id}",
        "PLOTEL",
        # mat_ID is left 0: /PROP/TYPE4 needs no material, and dyna2rad never
        # sets one on the PLOTEL part either.
        f"{_i(prop_id)}{_i(0)}{_i(0)}",
        f"/SPRING/{part_id}",
        "# sprg_ID  node_ID1  node_ID2",
    ]
    missing: List[int] = []
    kept = 0
    for e in state.plotel_elems:
        if e.n1 not in state.nodes or e.n2 not in state.nodes:
            missing.append(e.eid)
            continue
        lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}")
        # /SPRING producer 4 of 9. A PLOTEL keeps its SOURCE eid, so it shares
        # the /SPRING id namespace with the real connectors — and the
        # `continue` above drops elements whose nodes are missing, so this is
        # recorded at the write line like every other producer.
        state.spring_elem_ids.add(e.eid)
        kept += 1
    lines.append(HDR)

    if missing:
        state.warn(
            f"*ELEMENT_PLOTEL: {len(missing)} element(s) reference a node with "
            f"no *NODE record (first: EID {missing[0]}) — dropped, because a "
            "/SPRING on an undefined node is starter ERROR 78 (USR2SYS). Only "
            "the visualization line is lost.")
    state.warn(
        f"*ELEMENT_PLOTEL: {kept} visualization element(s) converted to inert "
        f"/SPRING on the synthesized /PART/{part_id} + /PROP/TYPE4/{prop_id} "
        f"(K=0, C=0, MASS={PLOTEL_MASS:g} per element). They add no stiffness "
        "and do not govern the time step, but they DO appear in the animation "
        "and in the part list — delete the *ELEMENT_PLOTEL cards if you want "
        "them out of the model entirely.")

    # (The /SPRING id-namespace collision check covering this family lives in
    # _warn_spring_eid_collisions, a build_starter prepass — the clash is not
    # PLOTEL-specific and must be reported even on a deck with no PLOTELs.)
    return lines


def _mean_diameter(d1: float, d2: float) -> float:
    """Mean of a spot weld nugget's node-1 / node-2 diameters (card 2i).

    A tapered weld is reduced to one prismatic spring at the mean diameter,
    matching dyna2rad's ``meanTS = (TS1+TS2)/2``. A blank/zero column on one
    end is an omission rather than a nugget that tapers to a point, so the
    populated value is used for both ends — averaging the blank in would
    silently quarter the weld area.
    """
    if d1 > 0.0 and d2 > 0.0:
        return (d1 + d2) / 2.0
    return max(d1, d2, 0.0)


Vec3 = Tuple[float, float, float]


def _closest_on_triangle(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    """The point of triangle *abc* nearest to *p* (the Voronoi-region walk of
    Ericson, "Real-Time Collision Detection" 5.1.5): a vertex, an edge point
    or the interior projection, never outside the triangle."""
    def sub(u: Vec3, v: Vec3) -> Vec3:
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    def dot(u: Vec3, v: Vec3) -> float:
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def at(o: Vec3, d: Vec3, t: float) -> Vec3:
        return (o[0] + t * d[0], o[1] + t * d[1], o[2] + t * d[2])

    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return a
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return at(a, ab, d1 / (d1 - d3))
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return at(a, ac, d2 / (d2 - d6))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        return at(b, sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)))
    den = va + vb + vc
    v, w = vb / den, vc / den
    return (a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w,
            a[2] + ab[2] * v + ac[2] * w)


def _spotweld_reference_faces(state: ConversionState, c
                              ) -> List[Tuple[Tuple[int, int], str, int,
                                              List[int]]]:
    """The reference segments of a weld tie: the faces of its MAIN side, as
    ``(sort key, label, part id or 0, node ids)``. MSTYP 3 a part, 2 a part
    set, 1 a ``*SET_SHELL`` (shells), 0 a ``*SET_SEGMENT`` (its segments)."""
    out: List[Tuple[Tuple[int, int], str, int, List[int]]] = []
    if c.mstyp in (2, 3):
        pids = ({c.msid} if c.mstyp == 3 else
                set(state.part_sets.get(c.msid, ("", []))[1]))
        for e in state.shell_elems:
            if e.pid in pids:
                out.append(((0, e.eid), f"shell {e.eid}", e.pid,
                            list(e.nodes)))
    elif c.mstyp == 1:
        wanted = set(state.shell_sets.get(c.msid, ("", []))[1])
        for e in state.shell_elems:
            if e.eid in wanted:
                out.append(((0, e.eid), f"shell {e.eid}", e.pid,
                            list(e.nodes)))
    elif c.mstyp == 0:
        ss = state.segment_sets.get(c.msid)
        if ss is not None:
            for k, seg in enumerate(ss.segments, start=1):
                out.append(((1, k), f"segment {k} of *SET_SEGMENT {c.msid}", 0,
                            [n for n in seg if n > 0]))
    return out


def _synthesize_spotweld_second_nodes(state: ConversionState) -> None:
    """``--spotweld-node-synthesis`` (round 6, B6 rule 1; default OFF): an
    ELFORM-9 ``*MAT_SPOTWELD`` beam that states ONE node gets its second one
    where Vol I R17 p.19-3 puts it - *"If the PID option is inactive for the
    type 9 element, the nodal points of the spot weld are located to the two
    nearest reference surface segments"*.

    The reference surface is the MAIN side of the first ``*CONTACT_TIED_*`` /
    ``*CONTACT_SPOTWELD`` whose SURFA names the weld part. The given node N1
    moves to its nearest point q1 on those segments (segment S1; ties -> the
    lowest id), and a NEW element-free node is created at the nearest point
    q2 on a segment strictly on the OTHER side of N1 ((q2 - P).(q1 - P) < 0).
    So the weld length is the distance between the two sheets, whatever the
    sheet thickness or TS1 - on the only R14 carrier, spotweld.k, the three
    coincide at 2.0 and cannot tell the rules apart; LS-DYNA's own d3plot
    there moved node 1213 from z 1.0 to z 0.0 and created node 1214 at z 2.0,
    and its swforc prints length 2.0. (The deck's commented-out beam card
    names nodes 213 / 123 at z 1.5 / 0.5: those are ORPHANS, in *NODE and in no
    element; the sheets are at z 0 and 2.)

    A PREPASS, before the ``/NODE`` section and before the tied / spotweld
    sections that must name the node; the id comes from ``next_node_id`` (so
    under the flag the ``/SECT`` frame nodes allocated later move up by one).
    Refused by name, the weld then kept exactly as before (the connector
    writer's part-level refusal of a node-less beam): N1 shared with any other
    element, no tie naming the part, no reference segment, N1 ON a reference
    sheet (the side of the second sheet is not guessed), no segment on the
    other side, or coinciding points.
    """
    if not state.options.spotweld_node_synthesis:
        return
    weld_pids = _spotweld_beam_pids(state)
    if not weld_pids:
        return
    candidates = [e for e in state.beam_elems
                  if e.pid in weld_pids and e.n2 == 0 and e.n1 > 0]
    if not candidates:
        return
    extent = 0.0
    if state.nodes:
        xs = [n.x for n in state.nodes.values()]
        ys = [n.y for n in state.nodes.values()]
        zs = [n.z for n in state.nodes.values()]
        extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    ties = list(state.contacts_tied) + list(state.contacts_spotweld)
    for e in candidates:
        part = state.parts.get(e.pid)
        sec = state.sec_beams.get(part.secid if part and part.secid > 0
                                  else e.pid)
        if sec is None or sec.elform != 9:
            continue
        head = (f"--spotweld-node-synthesis: *ELEMENT_BEAM {e.eid} (part "
                f"{e.pid}) names ONE node ({e.n1}) and was NOT given a second "
                "one: ")
        tail = (". It stays as before: a node-less spotweld beam is not "
                "converted.")
        used = any(e.n1 in s.nodes for s in state.shell_elems) or any(
            e.n1 in s.nodes for s in state.solid_elems) or any(
            e.n1 in s.nodes for s in state.tshell_elems) or any(
            e.n1 == c.nid for c in state.sph_elems) or any(
            e.n1 in (s.n1, s.n2) for s in state.seatbelt_elems) or any(
            e.n1 in (d.n1, d.n2) for d in state.discrete_elems) or any(
            b is not e and e.n1 in (b.n1, b.n2) for b in state.beam_elems)
        if used:
            state.warn(head + f"node {e.n1} also belongs to another element; "
                       "moving it would distort that element" + tail)
            continue
        if e.n1 not in state.nodes:
            state.warn(head + f"node {e.n1} is not defined" + tail)
            continue
        tie = next((c for c in ties
                    if (c.sstyp == 3 and c.ssid == e.pid)
                    or (c.sstyp == 2 and e.pid in
                        state.part_sets.get(c.ssid, ("", []))[1])), None)
        if tie is None:
            state.warn(head + "no *CONTACT_TIED_*/_SPOTWELD names part "
                       f"{e.pid} as its tracked (SURFA) side, so there is no "
                       "reference surface to place the second node on" + tail)
            continue
        faces = [f for f in _spotweld_reference_faces(state, tie)
                 if len(f[3]) >= 3 and all(n in state.nodes for n in f[3])]
        if not faces:
            state.warn(head + "no shell reference segment on the MAIN side of "
                       f"that tie ({tie.inter_id})" + tail)
            continue
        pn = state.nodes[e.n1]
        p = (pn.x, pn.y, pn.z)
        near = []
        for key, label, fpid, nodes in faces:
            pts = [(state.nodes[n].x, state.nodes[n].y, state.nodes[n].z)
                   for n in nodes]
            uniq = list(dict.fromkeys(pts))
            tris = ([(uniq[0], uniq[1], uniq[2])] if len(uniq) == 3 else
                    [(pts[0], pts[1], pts[2]), (pts[0], pts[2], pts[3])]
                    if len(uniq) >= 4 else [])
            best = None
            for a, b, c3 in tris:
                q = _closest_on_triangle(p, a, b, c3)
                d = sum((q[i] - p[i]) ** 2 for i in range(3)) ** 0.5
                if best is None or d < best[0]:
                    best = (d, q)
            if best is not None:
                near.append((best[0], key, label, fpid, best[1]))
        if not near:
            state.warn(head + "no shell reference segment on the MAIN side of "
                       f"that tie ({tie.inter_id})" + tail)
            continue
        near.sort(key=lambda t: (t[0], t[1]))
        d1, _k1, lab1, pid1, q1 = near[0]
        if d1 <= 1e-9 * extent:
            state.warn(head + f"node {e.n1} lies ON a reference sheet ({lab1}), "
                       "and k2rad does not guess the side of the second sheet"
                       + tail)
            continue
        v1 = tuple(q1[i] - p[i] for i in range(3))
        other = [t for t in near
                 if sum((t[4][i] - p[i]) * v1[i] for i in range(3)) < 0.0]
        if not other:
            state.warn(head + "no reference segment lies on the other side of "
                       f"node {e.n1}" + tail)
            continue
        _d2, _k2, lab2, pid2, q2 = other[0]
        length = sum((q2[i] - q1[i]) ** 2 for i in range(3)) ** 0.5
        if length <= 1e-12:
            state.warn(head + "the two reference points coincide" + tail)
            continue
        n2 = state.next_node_id()
        state.nodes[e.n1] = NodeData(*q1)
        state.nodes[n2] = NodeData(*q2)
        e.n2 = n2
        kw = getattr(tie, "keyword", "") or (
            f"CONTACT_TIED_{tie.variant}" if tie in state.contacts_tied
            else "CONTACT_SPOTWELD")

        def xyz(v) -> str:
            return f"({v[0]:g}, {v[1]:g}, {v[2]:g})"
        if state.options.beam_contact_secondary:
            # round 9, B9: today's defaults (the EFAIL displacement criterion
            # of round 7, the DT scaling of round 8) on the two opt-in rules
            # - cG3's swA6 arm; round 6's combined-arm figures are history
            # (CHANGELOG round 6)
            clause = (
                " MEASURED with both flags on spotweld.k (nt 4, today's "
                "defaults incl. the EFAIL displacement criterion and the DT "
                "scaling): the last cycle 1332 = LS-DYNA's 1332; IE END "
                "-31.18 %, KE END +30.76 %, RMS IE / KE 6.82 / 23.66 % of the "
                "LS peak over the 1331 LS times to t 0.00119792; the weld "
                "ruptures at 1.12229e-3 s, 65.3 us before LS-DYNA's swforc "
                "failure time 1.1876e-3 s.")
        else:
            clause = (
                " WITHOUT --beam-contact-secondary the tie's secondary side "
                "still resolves to no node, so the weld connects nothing: "
                "MEASURED on spotweld.k (nt 4), this flag alone costs 2.09x "
                "the cycles (639 -> 1334) at IE END -99.88 % with today's DT "
                "scaling - 7.64x (4884) under --no-spotweld-dt-mass-scaling.")
        state.warn(
            f"*ELEMENT_BEAM {e.eid} (part {e.pid}: *SECTION_BEAM ELFORM 9, "
            f"*MAT_SPOTWELD) names ONE node ({e.n1}; n2 = 0). "
            "--spotweld-node-synthesis places the weld the way Vol I R17 "
            "p.19-3 describes - 'the nodal points of the spot weld are "
            "located to the two nearest reference surface segments': node "
            f"{e.n1} moved from {xyz(p)} to {xyz(q1)} on {lab1}"
            + (f" (part {pid1})" if pid1 else "")
            + f" and a new element-free node {n2} created at {xyz(q2)} on "
            f"{lab2}" + (f" (part {pid2})" if pid2 else "")
            + f", the reference surface being the MAIN side of *{kw} "
            f"{tie.inter_id}; weld length {length:g}. LS-DYNA's own d3plot of "
            "the only R14 carrier (spotweld.k) shows exactly this placement "
            "(node 1213 at (60, 20, 0), new node 1214 at (60, 20, 2)) and its "
            "swforc prints length 2.0." + clause)


#: LS-DYNA's "never" idiom on a *MAT_SPOTWELD cell: a value at or above this
#: is "not stated" - both for the dropped-field clause and for the EFAIL ->
#: displacement-failure rule (round 7, A3), ONE threshold. The Yaris door sag
#: states EFAIL 2e20 and converts to no failure (0 bytes).
_SPOTWELD_NEVER = 1.0e19

#: The measured evidence the A3 warnings quote, ONE copy each (part-A spec
#: A3.4; plates.mat100 re-measured on the implementation, nt 4, base-paired
#: in one window; history RMS in % of the LS peak, the LS glstat blocks up to
#: the last printed OpenRadioss cycle).
_SPOTWELD_SHEAR_EVIDENCE = (
    "MEASURED on intro-by-k.-weimar/spotweld/spotweld-i/plates.mat100.k "
    "(nt 4): LS-DYNA's weld shear force plateaus at 20374..20408 between "
    "1.9e-4 and 2.9e-4 s = (SIGY/sqrt3)·A = 20405 to 0.1 %; with the curve "
    "the converted weld reads 20450 / 20597 at 1.6e-4 / 2.4e-4 s (LS 17872 / "
    "20389; elastic shear 23958 / 34213), and the IE / KE history RMS goes "
    "23.53 / 62.56 -> 8.58 / 26.74 % of the LS peak at 1.107x the cycles.")
_SPOTWELD_EFAIL_EVIDENCE = (
    "MEASURED on intro-by-a.-tabiei/contact/contact-spotweld/spotweld.k with "
    "--spotweld-node-synthesis --beam-contact-secondary (nt 4): the weld "
    "fails at 1.12229e-3 s, 65.3 us before LS-DYNA's swforc failure time "
    "1.1876e-3 s; IE -31.18 % / KE +30.76 % at the end, RMS 6.82 / 23.66 % "
    "of the LS peak (1331 LS times).")


def _make_spotweld_beam_connectors(state: ConversionState) -> List[str]:
    """*MAT_SPOTWELD (MAT_100) beam parts → /PROP/TYPE13 (SPR_BEAM) /SPRING
    connectors.

    Route note: /MAT/LAW59 (CONNECT) was evaluated and rejected — its cfg
    (matl59_CONNECT.cfg) binds it to /PROP/TYPE43 8-node connection SOLIDS,
    not to 2-node spring elements, so a LAW59 card here could not be attached
    to the converted beams. The complete spotweld behaviour therefore lives in
    the TYPE13 property: local Tx is the beam axis (Radioss and LS-DYNA share
    that convention for a 2-node spring/beam), per-DOF elastic stiffness comes
    from E, G=E/2(1+ν) and the *SECTION_BEAM resultants, and MAT_100 card 2
    (NRR NRS NRT MRR MSS MTT) becomes the Ifail=1/Ifail2=2 multi-directional
    FORCE failure surface — the same quadratic resultant criterion LS-DYNA
    applies. SIGY/EH give a bilinear axial force function (H=1 elastic-plastic)
    when SIGY > 0, and (round 7, A3, default ON) a bilinear SHEAR function on
    Ty / Tz at the von Mises shear yield (SIGY/sqrt3)·A with the hardening
    G·EH/(3G+EH)·A/L (``--no-spotweld-shear-yield`` keeps the shear elastic).
    A card that states EFAIL (below the 1e19 'never' idiom) and NO resultant
    cell gets the Ifail 1 / Ifail2 0 DISPLACEMENT criterion DeltaMax1 =
    delta_y + EFAIL·L, DeltaMax2,3 = delta_y,s + sqrt3·EFAIL·L
    (``--no-spotweld-efail-displacement`` keeps EFAIL dropped); beside
    resultant cells EFAIL is named, not converted (one criterion type per
    TYPE13).
    """
    pids = sorted(_spotweld_beam_pids(state))
    if not pids:
        return []
    lines: List[str] = [
        "#-  SPOTWELD CONNECTORS (*MAT_SPOTWELD beam parts -> /PROP/TYPE13 + /SPRING):",
        HDR]
    emitted = False

    beams_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    for e in state.beam_elems:
        beams_by_pid[e.pid].append(e)

    for pid in pids:
        part = state.parts[pid]
        mat = state.mat_spotweld[part.mid]
        beams = beams_by_pid.get(pid, [])
        secid = part.secid if part.secid > 0 else pid
        sec = state.sec_beams.get(secid)

        # Mean weld length from the node coordinates.
        lens = []
        for e in beams:
            a, b = state.nodes.get(e.n1), state.nodes.get(e.n2)
            if a is not None and b is not None:
                lens.append(((a.x - b.x) ** 2 + (a.y - b.y) ** 2
                             + (a.z - b.z) ** 2) ** 0.5)
        L = (sum(lens) / len(lens)) if lens else 0.0
        if L <= 1e-12:
            state.warn(f"*MAT_SPOTWELD part {pid}: zero-length (or node-less) "
                       "spotweld beams — /PROP/TYPE13 needs a finite length; "
                       f"{len(beams)} weld(s) NOT converted. Tie the sheets "
                       "with *CONSTRAINED_SPOTWELD instead.")
            continue

        # Cross-section area + inertias from the *SECTION_BEAM.
        area = iyy = izz = ixx = 0.0
        if sec is None:
            state.warn(f"*MAT_SPOTWELD part {pid}: no *SECTION_BEAM {secid} — "
                       "cannot size the weld stiffness; welds NOT converted.")
            continue
        if sec.elform == 1:
            # Integrated beam: TS1 is the (outer) section dimension; assume a
            # solid circular spotweld nugget of diameter TS1.
            d = sec.ts1
            area = math.pi * d * d / 4.0
            iyy = izz = math.pi * d ** 4 / 64.0
            ixx = 2.0 * iyy
            if d > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=1) on spotweld part "
                           f"{pid}: assumed a solid circular nugget of diameter "
                           f"TS1={d:g} (card 2a's TS2/TT1/TT2 and CST are not "
                           "read on this path).")
        elif sec.elform == 9:
            # Spot weld beam, *SECTION_BEAM card 2i: TS1/TS2 are the nugget
            # OUTER diameter at node 1/2 and TT1/TT2 the INNER diameter — the
            # card carries diameters, never a volume or an area. A tapered
            # weld (TS1 != TS2) collapses to ONE prismatic /PROP/TYPE13 spring,
            # so the section is taken at the MEAN diameter; that is also what
            # dyna2rad does (convertprops.cxx ConvertToPropType13:
            #   meanTS = (TS1+TS2)/2, meanTT = (TT1+TT2)/2,
            #   area   = pi*(meanTS^2 - meanTT^2)/4).
            # With TT = 0 this is the solid circle pi*d^2/4 of the ELFORM=1
            # branch above, so both spot weld formulations agree.
            do = _mean_diameter(sec.ts1, sec.ts2)
            di = _mean_diameter(sec.tt1, sec.tt2)
            if di >= do > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: inner diameter TT ({di:g}) is not smaller "
                           f"than the outer diameter TS ({do:g}) — the nugget "
                           "was sized as SOLID (TT ignored).")
                di = 0.0
            area = math.pi * (do * do - di * di) / 4.0
            # Solid/annular circular nugget: I = pi(do^4-di^4)/64 about either
            # bending axis, polar J = 2I = pi(do^4-di^4)/32.
            iyy = izz = math.pi * (do ** 4 - di ** 4) / 64.0
            ixx = 2.0 * iyy
            if do > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: nugget sized from card 2i as a circular "
                           f"section, outer d={do:g}"
                           + (f", inner d={di:g}" if di > 0.0 else "")
                           + f" -> A={area:g} (mean of TS1={sec.ts1:g}/"
                           f"TS2={sec.ts2:g}); bending/torsion inertia follow "
                           "from the same section.")
            if (sec.ts1 > 0.0) != (sec.ts2 > 0.0):
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: only one of TS1/TS2 is populated "
                           f"(TS1={sec.ts1:g}, TS2={sec.ts2:g}) — the weld was "
                           f"sized prismatic at d={do:g} instead of tapering "
                           "to a point. Fill in both columns if the nugget "
                           "really is conical.")
            if sec.cst != 1 and do > 0.0:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: CST={sec.cst} (not tubular) — TS/TT are "
                           "then RECTANGULAR thicknesses, but the weld was "
                           "still sized as a circular nugget of diameter "
                           f"{do:g} (same assumption dyna2rad makes). Check "
                           "the weld stiffness if the nugget is not round.")
            if sec.itoff == 1:
                state.warn(f"*SECTION_BEAM {secid} (ELFORM=9 spotweld) on part "
                           f"{pid}: ITOFF=1 (torsion free) is NOT applied — "
                           "the /PROP/TYPE13 keeps its elastic Rx stiffness.")
        else:
            area, iyy, izz, ixx = sec.area, sec.iyy, sec.izz, sec.ixx
        if area <= 0.0:
            state.warn(f"*MAT_SPOTWELD part {pid}: *SECTION_BEAM {secid} gives "
                       "no cross-section area — welds NOT converted.")
            continue
        if iyy <= 0.0 or izz <= 0.0:
            est = area * area / (4.0 * math.pi)
            iyy = iyy if iyy > 0.0 else est
            izz = izz if izz > 0.0 else est
            state.warn(f"*MAT_SPOTWELD part {pid}: missing bending inertia in "
                       f"*SECTION_BEAM {secid} — estimated as a solid circular "
                       "section from the area.")
        if ixx <= 0.0:
            ixx = iyy + izz

        E = mat.E
        G = E / (2.0 * (1.0 + mat.nu)) if mat.nu > -1.0 else E / 2.0
        k1 = E * area / L            # axial Tx
        k23 = G * area / L           # shear Ty/Tz
        k4 = G * ixx / L             # torsion Rx
        k5 = E * iyy / L             # bending Ry
        k6 = E * izz / L             # bending Rz

        mass = mat.rho * area * L
        # RO*A*L is LS-DYNA's OWN beam mass — it is never compensated. Only the
        # fallback below invents one, so the flag travels with the branch.
        token_mass = mass <= 0.0
        if token_mass:
            mass = _SPRING_TOKEN_MASS
            state.warn(f"*MAT_SPOTWELD part {pid}: non-positive weld mass "
                       f"(RO or section) — token mass {_SPRING_TOKEN_MASS:g} "
                       "used, and removed again from the end nodes with a "
                       "negative /ADMAS (see the *ELEMENT_DISCRETE token-mass "
                       "warning; --no-spring-token-mass-compensation keeps "
                       "it).")
        inertia = max(mass * L * L / 12.0, 1e-20)

        # Failure surface (Ifail=1 multi-directional + Ifail2=2 force criteria:
        # the combined quadratic force/moment resultant criterion, matching
        # MAT_100's (N/NRR)²+(Ns/NRS)²+(Nt/NRT)²+(M/M..)² ≥ 1). Zero fields
        # default to ±1e30 = that component never fails, like a blank in DYNA.
        has_fail = any(v > 0.0 for v in (mat.nrr, mat.nrs, mat.nrt,
                                         mat.mrr, mat.mss, mat.mtt))
        ifail, ifail2 = (1, 2) if has_fail else (0, 0)
        # EFAIL (round 7, A3 piece (ii)): a stated value below LS-DYNA's 1e19
        # 'never' idiom (the dropped-field filter's own threshold - ONE
        # number), converted ONLY where the card states no resultant cell at
        # all; beside resultants it is named (TYPE13 carries ONE criterion
        # type per property).
        efail_given = 0.0 < mat.efail < _SPOTWELD_NEVER
        efail_on = state.options.spotweld_efail_displacement and efail_given
        efail_disp = efail_on and all(
            v == 0.0 for v in (mat.nrr, mat.nrs, mat.nrt,
                               mat.mrr, mat.mss, mat.mtt))
        efail_mixed = efail_on and has_fail

        # Axial elastic-plastic bilinear force function from SIGY/EH.
        fct1 = 0
        h1 = 0
        funct_lines: List[str] = []
        # The yielding SHEAR (round 7, A3 piece (i)): the shear curve's id
        # and H, and its yield displacement (also the base of piece (ii)'s
        # shear cells, so it is computed even with the curve switched off).
        fs = 0
        hs = 0
        dy_s = 0.0
        if mat.sigy > 0.0:
            fy = mat.sigy * area
            dy = fy / k1
            if mat.et > 0.0 and mat.et < E:
                # EH is the plastic hardening modulus: tangent = E·EH/(E+EH).
                kt = (E * mat.et / (E + mat.et)) * area / L
            else:
                kt = k1 * 1e-4       # near-perfectly-plastic fallback
            dend = dy * 101.0        # 100·δy of plastic range; Radioss
            fend = fy + kt * (dend - dy)   # extrapolates the last segment
            # a /FUNCT AND /TABLE free id (the post-review round): the raw
            # counter collided with a user curve id in the auto range (starter
            # ERROR 79 at 65ff389 and round 7 alike); next_curve_id is the
            # same id on every deck without such a collision
            fct1 = state.next_curve_id()
            h1 = 1                   # elastic-plastic, unloading with K1
            funct_lines = [
                f"/FUNCT/{fct1}",
                f"spotweld_axial_bilinear_pid{pid}",
                "#                  X                   Y",
                f"{_f(-dend)}{_f(-fend)}",
                f"{_f(-dy)}{_f(-fy)}",
                f"{_f(0.0)}{_f(0.0)}",
                f"{_f(dy)}{_f(fy)}",
                f"{_f(dend)}{_f(fend)}",
                HDR,
            ]
            # MAT_100 is von Mises plasticity in axial AND shear (Vol II R17
            # p.2-697, Remark 1 p.2-708): the shear yield force is
            # (SIGY/sqrt3)·A, and LS-DYNA's own swforc shows it - plates.
            # mat100's weld shear plateaus at 20374..20408 = 20405. The
            # 1e-8 nudge keeps the PRINTED slope below the PRINTED K2: at
            # dy_s = fy_s / k23 the 10-digit print made it exceed K2 by
            # 1.77e-11 and the starter warned WARNING 506 (rkini3.F:70-99).
            fy_s = mat.sigy / math.sqrt(3.0) * area
            dy_s = fy_s / k23 * (1.0 + 1.0e-8)
            if state.options.spotweld_shear_yield:
                # the shear tangent of a von Mises material with plastic
                # modulus EH (d tau / d gamma_p = EH / 3); EH <= 0 falls back
                # like the axial curve
                kt_s = ((G * mat.et / (3.0 * G + mat.et)) * area / L
                        if mat.et > 0.0 else k23 * 1e-4)
                dend_s = 101.0 * dy_s      # the axial curve's end-point rule
                fend_s = fy_s + kt_s * (dend_s - dy_s)
                # a /FUNCT AND /TABLE free id (hm_read_table.F:88 checks both
                # in one scan), like the axial curve above
                fs = state.next_curve_id()
                hs = 1
                funct_lines += [
                    f"/FUNCT/{fs}",
                    f"spotweld_shear_bilinear_pid{pid}",
                    "#                  X                   Y",
                    f"{_f(-dend_s)}{_f(-fend_s)}",
                    f"{_f(-dy_s)}{_f(-fy_s)}",
                    f"{_f(0.0)}{_f(0.0)}",
                    f"{_f(dy_s)}{_f(fy_s)}",
                    f"{_f(dend_s)}{_f(fend_s)}",
                    HDR,
                ]
                state.warn(
                    f"*MAT_SPOTWELD part {pid}: SIGY={mat.sigy:g}/EH="
                    f"{mat.et:g} sampled into a bilinear AXIAL /FUNCT/{fct1} "
                    f"(yield SIGY·A = {fy:.6G}) and a bilinear SHEAR "
                    f"/FUNCT/{fs} on Ty/Tz (yield (SIGY/sqrt3)·A = "
                    f"{fy_s:.6G}, the von Mises shear yield; hardening "
                    f"G·EH/(3G+EH)·A/L = {kt_s:.6G} per unit displacement), "
                    "H = 1 elastic-plastic; bending and torsion stay elastic "
                    "up to the failure surface. " + _SPOTWELD_SHEAR_EVIDENCE
                    + " --no-spotweld-shear-yield keeps the shear elastic.")
            else:
                state.warn(f"*MAT_SPOTWELD part {pid}: SIGY={mat.sigy:g}/EH="
                           f"{mat.et:g} sampled into a bilinear axial "
                           f"force-displacement /FUNCT/{fct1} (yield force "
                           f"SIGY·A={fy:.6G}, H=1 elastic-plastic). "
                           "Shear/bending DOFs stay elastic up to the failure "
                           "surface.")
        elif (mat.sigy if mat.sigy_stated is None
              else mat.sigy_stated) == 0.0:
            # A field the deck leaves at 0 still has a solver default (the
            # validation round): Vol II R17 p.2-697 defines SIGY 'EQ.0:
            # Default to 1% of E'. It is not converted - named, 0 bytes
            # (reach 0 on the R14 roster: every *MAT_SPOTWELD there states
            # SIGY > 0). A NEGATIVE SIGY (a yield curve / table) is named by
            # the handler, which zeroes it - hence the stated value here.
            state.warn(
                f"*MAT_SPOTWELD part {pid}: SIGY=0 - LS-DYNA's default "
                f"yield stress 1 % of E = {0.01 * abs(E):.6G} (Vol II R17 "
                "p.2-697, 'EQ.0: Default to 1% of E') is NOT converted: "
                "the weld is written ELASTIC in axial and shear (no "
                "bilinear /FUNCT)"
                + (" and the EFAIL displacement criterion gets no yield "
                   "displacement" if efail_disp else "")
                + ".")

        dofs = [
            (k1, fct1, h1, 0.0, mat.nrr),          # Tx: tension-only failure
            (k23, fs, hs, -mat.nrs, mat.nrs),      # Ty
            (k23, fs, hs, -mat.nrt, mat.nrt),      # Tz
            (k4, 0, 0, -mat.mrr, mat.mrr),         # Rx torsion
            (k5, 0, 0, -mat.mss, mat.mss),         # Ry bending
            (k6, 0, 0, -mat.mtt, mat.mtt),         # Rz bending
        ]
        if efail_disp:
            # EFAIL -> a DISPLACEMENT criterion (Ifail 1 / Ifail2 0: XA 1,
            # XB 2, r4def3.F:342-375; CRIT >= 1 deletes, :819-820). For a
            # proportional path with plastic >> elastic strain the effective
            # plastic strain sqrt(eps^2 + gamma^2/3), eps = d_a/L,
            # gamma = d_s/L, reaches EFAIL exactly on (d1/D1)^2 + (d2/D2)^2 +
            # (d3/D3)^2 = 1 with D1 = EFAIL·L and D2,3 = sqrt3·EFAIL·L; the
            # yield displacements are added. Tension only on Tx (DeltaMin 0 =
            # the reader's -1e30), rotations never fail. dyna2rad's strain
            # form (Ileng 1, +-EFAIL on all six DOFs) is NOT used: measured
            # 45 % early on spotweld.k.
            dy_a = (mat.sigy * area) / k1 if mat.sigy > 0.0 else 0.0
            d1 = dy_a + mat.efail * L
            d2 = dy_s + math.sqrt(3.0) * mat.efail * L
            ifail, ifail2 = 1, 0
            dofs[0] = (k1, fct1, h1, 0.0, d1)
            dofs[1] = (k23, fs, hs, -d2, d2)
            dofs[2] = (k23, fs, hs, -d2, d2)
            state.warn(
                f"*MAT_SPOTWELD part {pid}: EFAIL={mat.efail:g} (no resultant "
                "failure cells) -> /PROP/TYPE13 Ifail 1 / Ifail2 0 displacement "
                f"failure: DeltaMax1 = delta_y + EFAIL·L = {d1:.6G}, "
                f"DeltaMax2,3 = +-(delta_y,s + sqrt3·EFAIL·L) = {d2:.6G} "
                f"(L = {L:g}, the mean weld length): for a proportional path "
                "the effective plastic strain sqrt(eps^2 + gamma^2/3) reaches "
                "EFAIL exactly on the quadratic surface (d1/D1)^2 + (d2/D2)^2 "
                "+ (d3/D3)^2 = 1 that Ifail 1 / Ifail2 0 applies (r4def3.F). "
                "NOT carried: the path history (LS integrates the plastic "
                "strain), the elastic share of the displacement, the plastic "
                "strain from bending and torsion (TYPE13's rotations stay "
                "elastic), and LS's per-integration-point deletion. "
                + _SPOTWELD_EFAIL_EVIDENCE
                + (" With --no-spotweld-shear-yield the shear stays ELASTIC "
                   "and these shear cells are measured never to be reached "
                   "on spotweld.k (the weld does not fail)."
                   if mat.sigy > 0.0 and not state.options.spotweld_shear_yield
                   else "")
                + " --no-spotweld-efail-displacement keeps EFAIL dropped.")
        # round 8, A6 (default ON, --no-spotweld-dt-mass-scaling): *MAT_100
        # DT -> the TYPE13 Mass / Inertia closed form. Vol II R17
        # *MAT_SPOTWELD Remark 4 scales the weld inertias in the first step so
        # that their stable step is DT - UP only. The TYPE13 step is
        # DTFAC1(6) min(XM / (sqrt(XCM^2 + XM XKM) + XCM), the rotational one)
        # (r2len3.F:221-247; STI = XM/DT^2 at :233) with XKM = max(K1..K3)
        # (r4def3.F:165) and XKR = max(K2, K3) ALDP^2 + max(K4..K6) (:173,
        # :545-547): undamped, dt = 0.9 min(sqrt(M / max K1..3),
        # sqrt(I / (max K4..6 + max K2,3 L^2))). L_max = the LONGEST weld of
        # the property (the smallest rotational step).
        dt_scaled = False
        dt_inert = False
        f_m = f_i = 1.0
        if (state.options.spotweld_dt_mass_scaling
                and 0.0 < mat.dt < _SPOTWELD_NEVER):
            l_max = max(lens) if lens else L
            m_dt = max(k1, k23) * mat.dt ** 2
            i_dt = (max(k4, k5, k6) + k23 * l_max ** 2) * mat.dt ** 2
            new_mass, new_inertia = max(mass, m_dt), max(inertia, i_dt)
            if new_mass > mass or new_inertia > inertia:
                f_m, f_i = new_mass / mass, new_inertia / inertia
                dt_added = (new_mass - mass) * len(beams)
                mass, inertia = new_mass, new_inertia
                dt_scaled = True
            else:
                dt_inert = True
        prop_id = state.next_prop_id()
        lines += funct_lines
        lines += _emit_prop_type13(
            prop_id, (part.title or f"SPOTWELD_{pid}") + " (MAT_100 spotweld)",
            mass, inertia, ifail, ifail2, dofs)
        if dt_scaled:
            state.warn(
                f"*MAT_SPOTWELD part {pid}: DT={mat.dt:g} -> "
                f"/PROP/TYPE13/{prop_id} Mass x {f_m:.4g}, Inertia x "
                f"{f_i:.4g} (Vol II R17 *MAT_SPOTWELD Remark 4: the weld "
                "inertias are scaled so that their stable step is DT), added "
                f"mass {dt_added:.6G} on {len(beams)} weld(s): the TYPE13 "
                "step is 0.9 min(sqrt(Mass / max K1..3), sqrt(Inertia / (max "
                "K4..6 + max K2,3 L^2))) (r2len3.F:221-247, STI = XM/DT^2 at "
                ":233), so it starts at 0.9 DT; a lengthening weld pulls it "
                "below. MEASURED on spotweld.k under the opt-in rules 1 + 2 "
                "(nt 4): last cycle 1332 = LS-DYNA's 1332 (4791 unscaled), cycle-0 "
                "step 9.000e-7, "
                "model mass +7.0 %, IE END -31.18 % (unscaled -33.00 %) - "
                "MIXED: the histories are WORSE, RMS IE 6.65 -> 6.82 % and "
                "RMS KE 23.09 -> 23.66 % of the LS peak over the 1331 LS "
                "times to t 0.00119792. KE END +30.76 % (unscaled +38.90 %); "
                "the weld ruptures at 1.12229e-3 s, 65.3 us before LS-DYNA's "
                "swforc failure time 1.1876e-3 s (4.2 us earlier than without "
                "the scaling); the energy error stays within -0.3 .. +0.2 %. "
                "--no-spotweld-dt-mass-scaling drops DT as before (round 8).")
        elif dt_inert:
            state.warn(
                f"*MAT_SPOTWELD part {pid}: DT={mat.dt:g} is inert: the "
                "weld's own TYPE13 step already exceeds it (Remark 4 scales a "
                "weld UP to DT, never down - LS-DYNA runs plates.mat100 at its "
                "beam step 2.99951e-7 s with DT 1e-9). "
                "--no-spotweld-dt-mass-scaling names DT as dropped (round 8).")
        lines += [
            f"/PART/{pid}",
            part.title or f"SPOTWELD_{pid}",
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{pid}",
            "# sprg_ID  node_ID1  node_ID2  node_ID3",
        ]
        for e in beams:
            lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}{_i(e.n3)}")
            # Record what was ACTUALLY written: *DATABASE_SWFORC lists these
            # sprg_IDs, and every `continue` above skips a whole part without
            # emitting a /SPRING. A /TH/SPRING naming a skipped id is starter
            # ERROR 69 and the deck is refused outright.
            state.spotweld_spring_eids.add(e.eid)
            state.spring_elem_ids.add(e.eid)  # producer 2 of 9
            # Only the token branch: with RO*A*L > 0 the property mass is
            # LS-DYNA's own and compensating it would be a NEW defect. n3 is
            # the orientation node and gets nothing (rinit3.F:1937-1939 writes
            # IXR(2,I)/IXR(3,I) only). Ileng is 0 on this property.
            if token_mass:
                _register_spring_token_mass(
                    state, e.n1, e.n2,
                    spring=(e.eid, inertia) + _spring_kc(
                        dofs, l13=_element_length(state, e)),
                    prop=(prop_id, "TYPE13", 0, 1.0))
            # /PRELOAD/AXIAL property gate, recorded at the write line: this
            # /PROP/TYPE13's axial DOF carries fct_ID1=fct1 and H=h1, and
            # rinit3.F:1627-1690 accepts CASE(4,13) only with a non-zero
            # function AND H in 1..7 (ERROR 3057 otherwise). A *MAT_SPOTWELD
            # with SIGY<=0 leaves both at 0, so the test is on the values, not
            # on the property type.
            if fct1 and 1 <= h1 <= 7:
                state.spring_axial_preloadable.add(e.eid)
        lines.append(HDR)
        emitted = True

        cells = [("DT", mat.dt), ("TFAIL", mat.tfail), ("EFAIL", mat.efail),
                 ("NF", mat.nf)]
        if dt_scaled or dt_inert:
            # A6 (round 8): DT is converted (or named inert) above
            cells = [c for c in cells if c[0] != "DT"]
        if efail_disp or efail_mixed:
            # EFAIL is converted (piece ii) or named by its own sentence below
            # (the mixed card): the dropped clause leaves it out
            cells = [c for c in cells if c[0] != "EFAIL"]
        dropped = [name for name, v in cells
                   if v and 0.0 < v < _SPOTWELD_NEVER]
        if dropped and (efail_disp or efail_mixed):
            meaning = {"DT": "weld time-step mass scaling",
                       "TFAIL": "timed failure", "NF": "force filtering"}
            state.warn(f"*MAT_SPOTWELD part {pid}: {', '.join(dropped)} have no "
                       "/PROP/TYPE13 slot — dropped (no "
                       + " / ".join(meaning[n] for n in dropped) + ").")
        elif dropped:
            state.warn(f"*MAT_SPOTWELD part {pid}: {', '.join(dropped)} have no "
                       "/PROP/TYPE13 slot — dropped (no weld time-step mass "
                       "scaling / timed failure / plastic-strain failure / "
                       "force filtering).")
        if efail_mixed:
            state.warn(
                f"*MAT_SPOTWELD part {pid}: EFAIL={mat.efail:g} is NOT "
                "converted: the card also states resultant failure cells "
                "(NRR..MTT), which are written as the Ifail2 = 2 force "
                "criteria, and /PROP/TYPE13 carries ONE criterion type per "
                "property; LS-DYNA applies both.")
        if has_fail and abs(mat.nf) > 0.0:
            pass  # NF already reported above
        state.warn(
            f"*MAT_SPOTWELD part {pid} ({len(beams)} weld beam(s)) -> "
            f"/PROP/TYPE13/{prop_id} SPR_BEAM /SPRING connectors "
            f"(K_axial=E·A/L={k1:.6G}, K_shear=G·A/L={k23:.6G}, "
            + ("failure displacements from EFAIL via Ifail2=0"
               if efail_disp else
               "failure forces/moments from MAT_100 card 2 via Ifail2=2")
            + "). APPROXIMATE "
            "mapping: validate against LS-DYNA on a single-weld pull and "
            "lap-shear coupon before trusting a full-vehicle result.")

    return lines if emitted else []


#: The welds' exponent records for the per-deck warning: ``(class, N, M) ->
#: (index in state.warnings of the group's FIRST weld, [(keyword, label,
#: /PROP/TYPE13 id), ...])``, class "applied" / "optout" / "nonpos"
#: (post-review round of #140: the measured paragraph was warned once PER
#: WELD - ~1.6 KB each, thousands of times on a vehicle deck).
_WeldExpNotes = Dict[Tuple[str, float, float],
                     Tuple[int, List[Tuple[str, str, int]]]]


def _weld_failure_exponents(state: ConversionState, w, label: str,
                            prop_id: int, notes: _WeldExpNotes
                            ) -> Optional[List[Tuple[float, float]]]:
    """The weld tie's failure exponents N / M -> the TYPE13 ``alpha``/``beta``
    cells (R14 triage round 6, A2); ``None`` = leave every cell blank.

    LS-DYNA fails the weld when ``(fn/SN)^N + (fs/SS)^M >= 1`` (Vol I R17
    p.10-212/213, Remark 2; ``fn`` tensile only, ``fs`` the shear resultant).
    With ``Ifail = 1`` / ``Ifail2 = 2`` the engine sums ``XA*DLIM**XB`` over
    the DOFs (``r4def3.F:374`` for DOF 1, ``:449`` for DOF 2, ...; ``DLIM`` =
    force / failure force, ``:361``) and deletes the spring at ``CRIT >= 1``
    (``:819``), but the reader turns a zero ``alpha`` into 1 and a zero
    ``beta`` into 2 (``hm_read_prop13.F:1169-1170``): blank cells are always
    exponent 2. So when N or M differs from 2: ``alpha1-3 = 1``,
    ``beta1 = N``, ``beta2 = beta3 = M``; rows 4-6 stay blank (the moment
    DOFs carry the no-failure defaults). ``N = M = 2`` (blank or stated)
    writes nothing and is byte-identical — the reader's own default IS 2. A
    stated exponent ``<= 0`` is not written (named). dyna2rad writes
    ``beta1 = N`` / ``beta2 = M`` with ``Ifail 1`` / ``Ifail2 2`` on its
    ``/PROP/TYPE25`` route (``convertconstrainedspotwelds.cxx:103-124``).

    Called AFTER every ``continue`` screen of the weld loop and after the
    property id is drawn. The message is NOT warned here: the weld is
    recorded in *notes* and :func:`_warn_weld_exponents` writes ONE warning
    per (class, N, M) after the loop - the measured paragraph once, every
    weld of the group named with its property id (post-review round of #140;
    a deck with one weld per group reads exactly the one-weld text)."""
    n, m = w.n, w.m
    if abs(n - 2.0) <= 1e-9 and abs(m - 2.0) <= 1e-9:
        return None
    kw = ("*CONSTRAINED_GENERALIZED_WELD_SPOT" if w.nsid > 0
          else "*CONSTRAINED_SPOTWELD")
    cls = ("optout" if not state.options.weld_exponents
           else "nonpos" if n <= 0.0 or m <= 0.0 else "applied")
    # the group's warning is inserted where its FIRST weld used to warn
    notes.setdefault((cls, n, m), (len(state.warnings), []))[1].append(
        (kw, label, prop_id))
    if cls != "applied":
        return None
    return [(1.0, n), (1.0, m), (1.0, m)]


def _warn_weld_exponents(state: ConversionState, notes: _WeldExpNotes) -> None:
    """One warning per (class, N, M) group of *notes*, inserted into
    ``state.warnings`` where the group's FIRST weld used to warn - so a deck
    with one weld per group keeps its warning record byte for byte, order
    included. A group of ONE weld names it as ``<keyword> <label>`` and its
    ``/PROP/TYPE13/<id>`` - the text the round shipped per weld; a larger
    group names every weld with its property id in one list and states the
    criterion, the caveat and the measurement once."""
    out: List[Tuple[int, str]] = []
    for (cls, n, m), (first, welds) in notes.items():
        one = len(welds) == 1
        if one:
            kw, label, pid = welds[0]
            who = f"{kw} {label}"
            prop = f"/PROP/TYPE13/{pid}"
        else:
            who = (f"{len(welds)} welds ("
                   + "; ".join(f"{kw} {label} -> /PROP/TYPE13/{pid}"
                               for kw, label, pid in welds) + ")")
            prop = "their /PROP/TYPE13"
        if cls == "optout":
            out.append((first,
                f"--no-weld-exponents: {who} "
                f"{'states' if one else 'state'} N={n:g} / M={m:g}; "
                f"the alpha/beta cells of {prop} are left blank "
                "and the starter reads them as alpha 1 / beta 2 "
                "(hm_read_prop13.F:1169-1170), so "
                f"{'this weld fails' if one else 'these welds fail'} on "
                "exponent 2 in every term, not on the deck's N/M."))
            continue
        if cls == "nonpos":
            out.append((first,
                f"{who}: N={n:g} / M={m:g} - a failure exponent <= 0 is "
                f"not written into {prop}; the starter reads a "
                "blank beta cell as 2 (hm_read_prop13.F:1170), so "
                f"{'this weld fails' if one else 'these welds fail'} on "
                "exponent 2 in every term."))
            continue
        caveat = ""
        if abs(m - 2.0) > 1e-9:
            # The Radioss/LS ratio of the shear term with two EQUAL components
            # f: 2 (f/SS)^M against (sqrt(2) f/SS)^M, i.e. 2^(1 - M/2). Above 1
            # for M < 2 (Radioss reaches 1 first), below 1 for M > 2 (LS-DYNA
            # does).
            ratio = 2.0 ** (1.0 - m / 2.0)
            caveat = (
                " LS-DYNA scores the shear RESULTANT (Vol I R17 p.10-213 "
                "Remark 2); Radioss scores the two shear DIRECTIONS "
                "separately. The two agree when the shear stays on one local "
                "axis, and for any direction at M = 2. With both components "
                "present the direction of the difference follows M: ")
            if m < 2.0:
                caveat += (
                    f"at M = {m:g} and equal components the Radioss sum is "
                    f"{ratio:.3f}x the resultant term, so Radioss reaches 1 "
                    "first - the converted weld fails EARLIER than LS-DYNA "
                    "(conservative for M < 2).")
            else:
                caveat += (
                    f"at M = {m:g} and equal components the Radioss sum is "
                    f"only {ratio:.3f}x the resultant term, so LS-DYNA "
                    "reaches 1 first - the converted weld fails LATER than "
                    "LS-DYNA (NON-conservative for M > 2).")
        out.append((first,
            f"{who}: failure exponents N={n:g} / M={m:g} written into "
            f"{prop} as alpha1-3 = 1, beta1 = {n:g}, "
            f"beta2 = beta3 = {m:g}, so the Ifail = 1 criterion is "
            "(fn/SN)^N + (|fy|/SS)^M + (|fz|/SS)^M >= 1, fn tensile only "
            "(r4def3.F:361, :374 and its per-DOF siblings, deletion at :819). "
            "A blank alpha/beta cell is read as 1 / 2 "
            "(hm_read_prop13.F:1169-1170), so without these cells the deck's "
            "exponents would be replaced by 2."
            + caveat +
            " MEASURED at nt 4 on spotweld-ii/plates.nrbc and "
            "spotweld-iii/plates.spot (N = M = 1, the only two carriers): the "
            "weld deletes at t 2.460e-4 against LS-DYNA's 2.4193e-4 (+1.7 %; "
            "it was 3.130e-4, +29.4 %), in 2407 cycles against 2678 (0.899x); "
            "plates.nrbc IE +23.64 -> -18.99 %, KE +61.93 -> +12.75 %, "
            "external work +60.66 -> +7.83 %; plates.spot IE +34.23 -> "
            "-12.05 %, KE +45.57 -> +1.36 %, external work +59.99 -> +7.38 %; "
            "both rows stay deviation (IE and the -6.9 % energy error). Pass "
            "--no-weld-exponents to leave the cells blank."))
    for shift, (idx, msg) in enumerate(sorted(out, key=lambda x: x[0])):
        state.warnings.insert(idx + shift, msg)


def _make_constrained_spotweld_springs(state: ConversionState) -> List[str]:
    """*CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT with failure
    forces → one stiff /PROP/TYPE13 /SPRING per weld (Ifail=1/Ifail2=2:
    DeltaMax1=SN axial tension, ±SS on the shear DOFs). The no-failure flavour
    was already turned into a 2-node CNRB at parse time."""
    welds = state.constrained_spotwelds
    if not welds:
        return []
    lines: List[str] = [
        "#-  CONSTRAINED SPOTWELDS WITH FAILURE (-> stiff /PROP/TYPE13 + /SPRING):",
        HDR]
    emitted = False

    # Stiffness rationale: the weld must be rigid relative to the joined
    # sheets. A sheet loads the weld through a patch of membrane stiffness
    # ~E·t; with t of the order of the weld gap L, K = 10·E_ref·L is ~10x
    # stiffer than the surroundings (a firm tie that does not wreck the
    # explicit time step the way a huge penalty K would). E_ref is the
    # stiffest converted structural material.
    e_candidates = ([m.E for m in state.mat_elastic.values()]
                    + [m.E for m in state.mat_plas_tab.values()]
                    + [m.E for m in state.mat_plas_kin.values()]
                    + [m.E for m in state.mat_power_law.values()])
    e_ref = max([e for e in e_candidates if e > 0.0], default=0.0)
    if e_ref <= 0.0:
        e_ref = 210000.0
        state.warn("*CONSTRAINED_SPOTWELD: no structural material found to "
                   "scale the tie stiffness — defaulted E_ref=210000 (steel, "
                   "N/mm² assumed); check the unit system.")

    exp_notes: _WeldExpNotes = {}
    for w in welds:
        label = w.title or (f"spotweld_{w.n1}_{w.n2}" if w.nsid == 0
                            else f"gen_weld_spot_{w.nsid}")
        n1, n2 = w.n1, w.n2
        if w.nsid > 0:
            nids = sorted({n for n in state.node_sets.get(w.nsid, ("", []))[1]
                           if n > 0})
            if len(nids) != 2:
                state.warn(f"*CONSTRAINED_GENERALIZED_WELD_SPOT nsid={w.nsid}: "
                           f"node set has {len(nids)} node(s) (need exactly 2) "
                           "— weld NOT converted.")
                continue
            n1, n2 = nids
        a, b = state.nodes.get(n1), state.nodes.get(n2)
        if a is None or b is None:
            state.warn(f"*CONSTRAINED_SPOTWELD {label}: node {n1 if a is None else n2} "
                       "has no coordinates — weld NOT converted.")
            continue
        L = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
        if L <= 1e-12:
            state.warn(f"*CONSTRAINED_SPOTWELD {label}: nodes {n1}/{n2} are "
                       "coincident — /PROP/TYPE13 needs a finite length; weld "
                       "NOT converted (merge the nodes or use a tied contact).")
            continue
        k = 10.0 * e_ref * L
        krot = k * L * L / 12.0
        dofs = [
            (k, 0, 0, 0.0, w.sn),        # Tx: tension failure force SN
            (k, 0, 0, -w.ss, w.ss),      # Ty: shear failure force SS
            (k, 0, 0, -w.ss, w.ss),      # Tz
            (krot, 0, 0, 0.0, 0.0),      # Rx/Ry/Rz: no moment failure in the
            (krot, 0, 0, 0.0, 0.0),      #   DYNA criterion (defaults ±1e30)
            (krot, 0, 0, 0.0, 0.0),
        ]
        prop_id = state.next_prop_id()
        part_id = state.next_id()
        elem_id = state.next_id()
        exps = _weld_failure_exponents(state, w, label, prop_id, exp_notes)
        # Token mass/inertia: the tie itself is massless in LS-DYNA
        # (*CONSTRAINED_SPOTWELD has no mass cell at all — it is a CONSTRAINT),
        # so both cells are k2rad's own invention and the mass half is
        # registered below for the /ADMAS compensation.
        lines += _emit_prop_type13(prop_id, f"{label} (stiff weld tie)",
                                   _SPRING_TOKEN_MASS, _SPRING_TOKEN_INERTIA,
                                   1, 2, dofs, alpha_beta=exps)
        lines += [
            f"/PART/{part_id}",
            label,
            f"{_i(prop_id)}{_i(0)}{_i(0)}",
            f"/SPRING/{part_id}",
            "# sprg_ID  node_ID1  node_ID2",
            f"{_i(elem_id)}{_i(n1)}{_i(n2)}",
            HDR,
        ]
        state.spring_elem_ids.add(elem_id)    # producer 6 of 9
        # Recorded AT the write line, never from `welds`: the four `continue`s
        # above drop a weld whose node set is not a pair, whose nodes have no
        # coordinates, or which is coincident — none of those reached the deck.
        # Ileng is 0 on this property, so UMASS is the property mass itself.
        _register_spring_token_mass(
            state, n1, n2,
            spring=(elem_id, _SPRING_TOKEN_INERTIA) + _spring_kc(dofs,
                                                                 l13=L),
            prop=(prop_id, "TYPE13", 0, 1.0))
        emitted = True
        state.warn(
            f"*CONSTRAINED_SPOTWELD {label}: converted to a stiff "
            f"/PROP/TYPE13/{prop_id} spring (K=10·E_ref·L={k:.6G} per "
            f"translational DOF; failure SN={w.sn:g} axial / SS={w.ss:g} "
            "shear via Ifail2=2 force criteria). APPROXIMATE: the pre-failure "
            "tie is penalty-stiff, not rigid — validate the failure load on a "
            "single-weld case.")

    _warn_weld_exponents(state, exp_notes)
    return lines if emitted else []


# ─────────────────────────────────────────────────────────────────────────────
# Starter: hex spot welds  (*DEFINE_HEX_SPOTWELD_ASSEMBLY → /CLUSTER/BRICK)
# ─────────────────────────────────────────────────────────────────────────────

# /CLUSTER Ifail: 3 = multi-directional (the general power-law interaction).
# dyna2rad hardcodes the same value (convertdefinehexspotweldassembly.cxx:70).
_CLUSTER_IFAIL = 3

# /CLUSTER failure-surface coefficients a1..a4 and exponents b1..b4. The engine
# forms (clusterf.F:386-390, the IFAIL==3 branch)
#
#   DMG = a1*(FN/Fn_fail1)^b1 + a2*(FT/Fs_fail)^b2
#       + a3*(MR/Mt_fail)^b3  + a4*(MB/Mb_fail)^b4      -> fails at DMG > 1
#
# and *MAT_SPOTWELD's own criterion (LS-DYNA Vol I R16, MAT_100) is
#
#   (Nrr/NRR)^2 + (Nrs/NRS)^2 + (Nrt/NRT)^2
# + (Mrr/MRR)^2 + (Mss/MSS)^2 + (Mtt/MTT)^2  >= 1
#
# i.e. QUADRATIC in every term, so b = 2 is the right exponent and dyna2rad's
# b1..b4 = 1.0 (convertdefinehexspotweldassembly.cxx:76-79) is not: its LINEAR
# interaction fails a weld held at 40% of both its tension and its shear limit
# at DMG = 0.4 + 0.4 = 0.8, where LS-DYNA gets 0.4^2 + 0.4^2 = 0.32.
#
# But the EXPONENT is only half the mapping. Radioss compares one SHEAR
# RESULTANT FT = sqrt(Fx^2+Fy^2) against ONE limit Fs_fail (clusterf.F:365-366),
# where MAT_100 scores its two shear directions separately against NRS and NRT.
# The exponent and the resultant reduction have to agree, and the obvious
# reduction does NOT agree with b = 2: with Fs_fail = sqrt(NRS^2+NRT^2) the
# shear term becomes (Fx^2+Fy^2)/(NRS^2+NRT^2), which for NRS = NRT = S is
# (Fx^2+Fy^2)/(2S^2) — exactly HALF of MAT_100's (Fx^2+Fy^2)/S^2. Measured on
# NRS=5000/NRT=4000: the weld then survives to 6403 N in pure s-shear where
# LS-DYNA breaks at 5000 (+28%), and to 6403 N in pure t-shear where LS-DYNA
# breaks at 4000 (+60%). Un-conservative in every load state involving shear.
# (dyna2rad pairs that same sqrt with b = 1, whose over-strength happens to
# cancel the other way; neither half is right on its own.)
#
# The reduction that agrees with b = 2 is the MINIMUM of the pair — see
# _resultant_limit. It is EXACT whenever NRS == NRT (a round nugget: the normal
# case, and the only one a single Radioss limit can carry) and conservative
# otherwise, which is the safe direction for a failure criterion.
_CLUSTER_A = 1.0
_CLUSTER_B = 2.0


def _resultant_limit(a: float, b: float) -> float:
    """One Radioss resultant limit for a MAT_100 direction PAIR (NRS,NRT) /
    (MSS,MTT).

    /CLUSTER scores the shear RESULTANT FT = sqrt(Fx^2+Fy^2) against a single
    Fs_fail (clusterf.F:365), so the two LS-DYNA per-direction limits have to
    collapse to one number. With the quadratic exponent b = 2 the term is
    (Fx^2+Fy^2)/Fs_fail^2, and MAT_100's is Fx^2/NRS^2 + Fy^2/NRT^2. Taking
    ``Fs_fail = min(NRS, NRT)`` makes the two IDENTICAL when NRS == NRT, and
    otherwise gives 1/min^2 >= 1/NRS^2 and >= 1/NRT^2, i.e. damage at or above
    LS-DYNA's — the weld fails no later than it would in LS-DYNA.

    A zero field is LS-DYNA's "this component never fails", so it is skipped
    rather than taken as the minimum: min(5000, 0) = 0 would be promoted to
    INFINITY by the starter (hm_read_cluster.F:293-296) and disable the shear
    term entirely. With one of the pair blank the surviving limit is used, which
    over-counts the blank direction's force into FT — unavoidable, because
    Radioss cannot ignore one shear direction of a single resultant. Both blank
    returns 0.0 and the starter's INFINITY promotion is then correct.
    """
    live = [v for v in (a, b) if v > 0.0]
    return min(live) if live else 0.0


def _pair_is_directional(a: float, b: float) -> bool:
    """True when a MAT_100 limit pair carries direction dependence a single
    Radioss resultant limit cannot reproduce — the two are live but unequal, or
    exactly one of them is blank. Both equal (the round-nugget norm) or both
    blank map exactly; anything else only maps conservatively."""
    if a > 0.0 and b > 0.0:
        return a != b
    return (a > 0.0) != (b > 0.0)


def _cluster_brick_eids(state: ConversionState, eids: List[int]):
    """Split an assembly's element ids into (bricks, tets, unknown).

    Applies the identical distinct-node test _make_parts_and_elements uses to
    route a solid to /TETRA4 (4 distinct corners) or /TETRA10 (10 nodes) rather
    than /BRICK, so the two cannot drift apart.

    A tetrahedron is NOT rejected by the starter here — measured: a /GRBRIC/BRIC
    listing a TET4 id resolves, and the cluster reports it in its element count
    with 0 ERROR(S). It is screened out because the result is silently wrong.
    hm_read_cluster.F:201-205 takes the weld's two joined faces from IXS(2:5)
    and IXS(6:9) — the hex's bottom and top faces — and on a collapsed tet
    (n1 n2 n3 n4 n4 n4 n4 n4) the "top face" is one repeated node, so the local
    frame the starter builds from the two face centroids, and with it the
    FN/FT/MR/MB split the whole failure surface is evaluated on, is meaningless.
    The Radioss Reference Guide says the same in prose (/CLUSTER comment 2:
    8-node hexa only) and notes it is not code-enforced.
    """
    by_eid = {e.eid: e for e in state.solid_elems}
    bricks: List[int] = []
    tets: List[int] = []
    unknown: List[int] = []
    for eid in eids:
        e = by_eid.get(eid)
        if e is None:
            unknown.append(eid)
        elif len(e.nodes) == 10 or len(set(n for n in e.nodes if n > 0)) == 4:
            tets.append(eid)
        else:
            bricks.append(eid)
    return bricks, tets, unknown


def _cluster_failure_limits(state: ConversionState, eids: List[int]):
    """(Fn_fail1, Fs_fail, Mt_fail, Mb_fail, mat_id) for one weld assembly.

    The limits come from the *MAT_SPOTWELD of the PART the assembly's FIRST
    element belongs to — dyna2rad does the same walk (element -> PID -> MID,
    convertdefinehexspotweldassembly.cxx:98-113). LS-DYNA forbids an assembly
    element from sharing a MID with anything outside an assembly
    (Vol I R16 p.17-301), so one lookup describes the whole nugget.

    The engine scores ONE shear resultant FT = sqrt(Fx^2+Fy^2) against ONE
    Fs_fail and one bending resultant MB against one Mb_fail (clusterf.F:365,
    367), so each MAT_100 direction PAIR collapses to a single limit via
    _resultant_limit — the minimum of the live pair, which is what agrees with
    the quadratic exponent b=2 (see the _CLUSTER_B comment for the arithmetic).
    Returns mat_id 0 when no MAT_100 is reachable.
    """
    by_eid = {e.eid: e for e in state.solid_elems}
    for eid in eids:
        e = by_eid.get(eid)
        if e is None:
            continue
        part = state.parts.get(e.pid)
        if part is None:
            continue
        m = state.mat_spotweld.get(part.mid)
        if m is None:
            continue
        return (m.nrr,
                _resultant_limit(m.nrs, m.nrt),
                m.mrr,
                _resultant_limit(m.mss, m.mtt),
                part.mid,
                _pair_is_directional(m.nrs, m.nrt)
                or _pair_is_directional(m.mss, m.mtt))
    return 0.0, 0.0, 0.0, 0.0, 0, False


def _emit_cluster_brick(cluster_id: int, title: str, group_id: int,
                        fn_fail: float, fs_fail: float,
                        mt_fail: float, mb_fail: float) -> List[str]:
    """/CLUSTER/BRICK card (FORMAT radioss140 — the only one that exists).

      C1  group_ID(1-10) skew_ID(11-20) Ifail(21-30)
      C2  Fn_fail1(1-20)  a1(21-40)  b1(41-60)
      C3  Fs_fail(1-20)   a2(21-40)  b2(41-60)
      C4  Mt_fail(1-20)   a3(21-40)  b3(41-60)
      C5  Mb_fail(1-20)   a4(21-40)  b4(41-60)

    All five data cards are UNCONDITIONAL — the CFG puts no `if` around cards
    2-5, so they must be written even for Ifail=0 or the starter reads the next
    keyword's line as a failure limit.

    skew_ID=0 lets the starter build the weld's local frame from the cluster's
    own bottom-face -> top-face normal (hm_read_cluster.F:104 `IF (IFAIL > 0
    .and. ISKN == 0)`), which is the correct frame for a through-thickness weld
    and is what dyna2rad emits. A zero limit auto-promotes to INFINITY when
    Ifail > 0 (:293-296), so an unknown resultant disables that term rather
    than failing the weld instantly.

    There is deliberately no Kn/Kt on this card: a /CLUSTER adds no stiffness
    of its own — it is a force/moment monitor around real brick elements, and
    the weld stiffness comes from their own material.
    """
    return [
        f"/CLUSTER/BRICK/{cluster_id}",
        (title or f"HEX_SPOTWELD_{cluster_id}")[:100],
        "# group_ID   skew_ID     Ifail",
        f"{_i(group_id)}{_i(0)}{_i(_CLUSTER_IFAIL)}",
        "#           Fn_fail1                  a1                  b1",
        f"{_f(fn_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        "#            Fs_fail                  a2                  b2",
        f"{_f(fs_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        "#            Mt_fail                  a3                  b3",
        f"{_f(mt_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        "#            Mb_fail                  a4                  b4",
        f"{_f(mb_fail)}{_f(_CLUSTER_A)}{_f(_CLUSTER_B)}",
        HDR,
    ]


def _emit_th_cluster(th_id: int, cluster_ids: List[int]) -> List[str]:
    """/TH/CLUSTER over every emitted weld cluster.

    Variable names are read from the STARTER's table, not the CFG's GUI list:
    hm_read_thgrou.F:1249-1252 `DATA VARCLUS` is FX FY FZ MX MY MZ FS FN MS MN
    FAIL, and the two group names (:1763-1766) expand to

      DEF  -> FX FY FZ MX MY MZ FAIL   (global frame + damage)
      FLOC -> FS FN MS MN              (LOCAL shear/normal force, bending/torsion)

    dyna2rad asks for DEF alone (convertdefinehexspotweldassembly.cxx:321), so
    the local weld resultants — the quantities a weld report is actually about,
    and the ones swforc prints in LS-DYNA — never reach the T01. Both groups
    are requested here. (The CFG's dropdown offers FT/MB/MT; the starter does
    not know those names and answers ERROR 260.)

    Object ids are cluster ids, TEN PER LINE — /TH/CLUSTER goes through
    hm_read_thgrki.F, not the one-id-per-line hm_read_thgrne.F that /TH/SPRING
    and /TH/BRIC use. A leading 0 in that list would mean "all clusters"
    (WARNING 3083), so the rows are never padded.
    """
    lines = [
        f"/TH/CLUSTER/{th_id}",
        f"TH_CLUSTERS_{th_id}",
        "#     var1      var2",
        "DEF       FLOC      ",
    ]
    row: List[str] = []
    for cid in cluster_ids:
        row.append(_i(cid))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _make_hex_spotweld_clusters(state: ConversionState) -> List[str]:
    """*DEFINE_HEX_SPOTWELD_ASSEMBLY[_N] → /GRBRIC/BRIC + /CLUSTER/BRICK
    (+ one /TH/CLUSTER when *DATABASE_SWFORC asks for weld forces).

    One assembly becomes one cluster: LS-DYNA caps an assembly at 16 hexes and
    /CLUSTER caps a group at 500 (hm_read_cluster.F:86, ERROR 1055), so the 1:1
    map is always inside both limits.

    The cluster is a monitor, not a joint — the hexes keep whatever material
    the deck gave them, and the cluster deletes all of them at once when its
    failure surface is reached. dyna2rad emits the element group as a
    /SET/GENERAL with a SOLID clause; k2rad emits the classic /GRBRIC/BRIC,
    which the starter fills with the same GRTYPE=1 that hm_read_cluster.F:180
    demands.
    """
    if not state.hex_spotweld_assemblies:
        return []
    lines: List[str] = []
    cluster_ids: List[int] = []
    seen_ids: Set[int] = set()
    for a in state.hex_spotweld_assemblies:
        # ID_SW is a user id and goes straight through, like every other
        # passthrough in the writer — but only when it is USABLE. A blank or
        # zero ID_SW would emit /CLUSTER/BRICK/0, and a 0 in the /TH/CLUSTER
        # object list is read as "every cluster" (WARNING 3083,
        # hm_read_thgrki.F:123-137), silently widening the group. A repeated
        # ID_SW is a duplicate-id starter rejection. LS-DYNA requires ID_SW to
        # be unique (Vol I R16 p.17-300), so both cases are malformed decks;
        # repair them the way handle_contact_spotweld repairs a bad interface
        # id rather than passing the fault on to the starter.
        cluster_id = a.sw_id
        if cluster_id <= 0 or cluster_id in seen_ids:
            cluster_id = state.next_id()
            state.warn(
                "*DEFINE_HEX_SPOTWELD_ASSEMBLY: ID_SW "
                + (f"{a.sw_id} is used by more than one assembly"
                   if a.sw_id > 0 else "is blank or zero")
                + f" — the /CLUSTER/BRICK was given generated id {cluster_id} "
                "instead. LS-DYNA requires ID_SW to be unique and non-zero "
                "(Vol I R16 p.17-300); a zero would additionally make the "
                "/TH/CLUSTER request read as ALL clusters (WARNING 3083). The "
                "weld itself is unaffected — only the id it reports under.")
        seen_ids.add(cluster_id)
        bricks, tets, unknown = _cluster_brick_eids(state, a.eids)
        if unknown:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: element id(s) "
                f"{_fmt_eid_list(unknown)} name no *ELEMENT_SOLID in this deck "
                "and were left out of the /CLUSTER/BRICK group.")
        if tets:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: element id(s) "
                f"{_fmt_eid_list(tets)} are tetrahedra and were left OUT of the "
                "/CLUSTER/BRICK group. The starter would accept them without "
                "complaint, which is the problem: a cluster takes the weld's "
                "two joined faces from the hex node ordering "
                "(hm_read_cluster.F:201-205), so a tet contributes a degenerate "
                "top face and corrupts the local frame — and with it the "
                "normal/shear/torsion/bending split the whole failure surface "
                "is evaluated on — for the ENTIRE weld. A hex spot weld must be "
                "meshed with 8-node hexahedra (Radioss Reference Guide, "
                "/CLUSTER comment 2). The remaining bricks are still clustered; "
                "the tets stay in the model as ordinary solids.")
        if not bricks:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: none of its "
                f"{len(a.eids)} element id(s) resolved to an 8-node /BRICK, so "
                "NO /CLUSTER/BRICK was emitted. PHYSICAL CONSEQUENCE: this "
                "weld has no failure criterion in the converted model — its "
                "elements behave as ordinary solids and never delete, so the "
                "joint holds for the whole run. REMEDY: check the element ids "
                "on the card and that the nugget is hex-meshed.")
            continue
        if len(bricks) > 500:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id}: {len(bricks)} "
                "elements exceed the starter's 500-per-cluster limit "
                "(hm_read_cluster.F:86, ERROR 1055) — the deck will be "
                "rejected. Split the assembly.")
        grbric_id = state.next_elem_group_id()
        lines += _emit_id_group("GRBRIC/BRIC", grbric_id,
                                f"hex_spotweld_{cluster_id}_bricks", bricks)
        fn, fs, mt, mb, mid, aniso = _cluster_failure_limits(state, bricks)
        lines += _emit_cluster_brick(cluster_id,
                                     a.title or f"HEX_SPOTWELD_{cluster_id}",
                                     grbric_id, fn, fs, mt, mb)
        cluster_ids.append(cluster_id)
        state.cluster_ids.append((cluster_id, a.title))
        if mid:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id} -> "
                f"/CLUSTER/BRICK/{cluster_id} over {len(bricks)} brick(s), "
                f"failure limits from *MAT_SPOTWELD {mid}: Fn_fail1=NRR="
                f"{fn:g}, Fs_fail=min(NRS,NRT)={fs:g}, Mt_fail=MRR="
                f"{mt:g}, Mb_fail=min(MSS,MTT)={mb:g}, with a1..a4=1 and "
                f"b1..b4={_CLUSTER_B:g}. /CLUSTER scores ONE shear resultant "
                "against ONE limit where MAT_100 scores NRS and NRT "
                "separately, so the pair is collapsed to its minimum: that "
                "REPRODUCES MAT_100 exactly when NRS==NRT and MSS==MTT, and is "
                "otherwise conservative (the weld fails no later than in "
                "LS-DYNA). dyna2rad writes b=1 there, which fails a "
                "combined-load weld early. A zero limit is promoted to "
                "INFINITY by the starter (that term is then inactive)."
                + (" NOTE: this weld's transverse limits are NOT equal, so the "
                   "single Radioss resultant cannot carry the direction "
                   "dependence — the converted weld is STRONGER-direction "
                   "conservative, breaking earlier than LS-DYNA when the load "
                   "leans towards the larger limit." if aniso else ""))
        else:
            state.warn(
                f"*DEFINE_HEX_SPOTWELD_ASSEMBLY {a.sw_id} -> "
                f"/CLUSTER/BRICK/{cluster_id} over {len(bricks)} brick(s) with NO "
                "failure limits: no *MAT_SPOTWELD (MAT_100) is reachable from "
                "the parts of its elements. Every limit is 0, which the "
                "starter promotes to INFINITY — the weld monitors force and "
                "moment but NEVER fails. Give the nugget part a *MAT_SPOTWELD "
                "if the joint is meant to break.")
    if not lines:
        return []
    head = ["#-  HEX SPOT WELDS (*DEFINE_HEX_SPOTWELD_ASSEMBLY -> /CLUSTER/BRICK):",
            HDR]
    if cluster_ids and state.db_swforc_dt:
        lines += [
            f"#-- *DATABASE_SWFORC -> hex weld cluster forces (dt={state.db_swforc_dt:g})"
        ]
        lines += _emit_th_cluster(state.next_id(), cluster_ids)
    return head + lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: imposed motions
# ─────────────────────────────────────────────────────────────────────────────

#: *BOUNDARY_PRESCRIBED_MOTION DOF -> the /IMPVEL|/IMPACC|/IMPDISP ``Dir``
#: field. 1/2/3 = translation along x/y/z, 5/6/7 = rotation about x/y/z, and
#: +-4 / +-8 = translation along / rotation about the *DEFINE_VECTOR VID, which
#: reach the same X / XX spelling but only make sense together with a
#: ``skew_ID`` whose local X' is that vector — see _pm_skew_for.
_DOF_DIR = {1: "X", 2: "Y", 3: "Z", 4: "X", 5: "XX", 6: "YY", 7: "ZZ", 8: "XX"}

#: /IMPVEL|/IMPACC|/IMPDISP card 1 header. All three share the column grid to
#: col 50; ``frame_ID``/``Icoor`` (51-70) exist only on /IMPVEL and /IMPDISP
#: (FORMAT radioss120) and are written as zeros on /IMPACC too, which the
#: reader ignores (measured: no WARNING 100214).
_IMP_COMMENT = ("#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID"
                "  frame_ID     Icoor")
_IMP_COMMENT2 = ("#           Ascale_x            Fscale_Y"
                 "              Tstart               Tstop")


def _register_imp_motion_nodes(state: ConversionState, nids, dir_str: str,
                               skew_id: int = 0, tstart: float = 0.0,
                               tstop: float = 0.0, sensor_id: int = 0) -> None:
    """Record the nodes an /IMPDISP | /IMPVEL | /IMPACC was just written for.

    This is the *DATABASE_BNDOUT scope. dyna2rad builds it by re-walking the
    converted /IMPDISP, /IMPVEL and /IMPACC cards and reading their node groups
    back out (dyna2rad.cxx:456-479); recording it here instead means a row that
    was warned about and dropped — an unsupported DOF, a pid with no /RBODY, a
    box that no set node lies inside — contributes nothing, so the /TH/NODE can
    never name an undefined node (starter ERROR 78).

    ``dir_str`` is the emitted ``Dir`` letter pair. ``XX``/``YY``/``ZZ`` are the
    ROTATIONAL directions (_DOF_DIR maps LS-DYNA dof 5/6/7 and |8| onto them),
    and their presence is what gates the REACXX/YY/ZZ channels — the same
    discipline ``_spc_constrains_rotations`` applies to the SPC block.

    ``skew_id`` splits the per-node record in two. A motion written in the
    GLOBAL system (skew_ID 0) is recorded per DIRECTION in
    ``state.imp_motion_dirs``, because that is the only form a global ``*NODE``
    TC/RC bit can be compared against; a motion written in a LOCAL system
    lands in ``state.imp_motion_skew_nodes`` instead, where the TC/RC pass
    NAMES it rather than guessing which global bits the skew axis touches.

    ``tstart`` / ``tstop`` / ``sensor_id`` are the card's own window (round 8,
    A5): a GLOBAL motion is also recorded with it in
    ``state.imp_motion_windows``, because the adaptive spring token counts an
    end DRIVEN only when a motion holds it for the WHOLE run.
    """
    real = [n for n in nids if n in state.nodes]
    state.imp_motion_nodes.update(real)
    if len(dir_str) > 1:
        state.imp_motion_rot = True
    if skew_id:
        state.imp_motion_skew_nodes.update(real)
        return
    for n in real:
        state.imp_motion_dirs.setdefault(n, set()).add(dir_str)
        state.imp_motion_windows.setdefault(n, []).append(
            (dir_str, tstart, tstop, sensor_id))


def _emit_imp_card(keyword: str, motion_id: int, title: str, lcid: int,
                   dir_str: str, grnod_id: int, fscale: float,
                   tstart: float, tstop: float,
                   skew_id: int = 0,
                   state: Optional[ConversionState] = None) -> List[str]:
    """One /IMPVEL | /IMPACC | /IMPDISP block.

    Pass *state* to record ``motion_id`` in ``state.imp_card_ids[keyword]`` —
    the registry ``/IMPDISP/FGEO`` screens its ``BPFGID`` against, because
    ``hm_read_impvel.F:96-129`` counts ``/IMPDISP`` and ``/IMPDISP/FGEO``
    together and runs ONE ``UDOUBLE`` duplicate scan over the merged
    ``NOM_OPT`` slice. (``/IMPVEL`` and ``/IMPACC`` get their own scans, so
    they are recorded but never conflict with FGEO.)

    ``skew_id`` goes in cols 21-30 and is the ONLY system column that is safe on
    all three keywords. ``frame_ID`` (cols 51-60) is deliberately left at 0 even
    where a moving system is wanted: measured under ``/BEGIN 2022`` an /IMPDISP
    with ``frame_ID=300`` echoes ``FRAME 0`` and falls back to the global axis
    with NO error and NO warning, because ``radioss120/LOADS/impdisp.cfg``
    never populates the attribute ``read_impdisp.F:140-142`` reads (the
    ``CARD_PREREAD`` that fixes it was added in FORMAT radioss2025, which a 2022
    deck cannot reach). /IMPVEL has that CARD_PREREAD already in radioss120 and
    its frame_ID does work — but ``read_impvel.F:322-325`` then makes it
    ERROR 3091 if a driven node is one of the frame's own N1/N2/N3, a constraint
    /SKEW/MOV does not impose. So: skews, never frames.
    """
    if state is not None:
        state.imp_card_ids.setdefault(keyword, set()).add(motion_id)
        # round 9, B5: a curve OpenRadioss would extrapolate nonzero inside
        # [Tstart, Tstop] is read through its zero-off-scale copy
        from .loadcurves import load_funct_id
        lcid = load_funct_id(state, lcid, keyword, tstart, tstop)
    return [
        f"/{keyword}/{motion_id}",
        title,
        _IMP_COMMENT,
        f"{_i(lcid)}{dir_str.rjust(10)}{_i(skew_id)}{_i(0)}{_i(grnod_id)}"
        f"{_i(0)}{_i(0)}",
        _IMP_COMMENT2,
        f"{_f(1.0)}{_f(fscale)}{_f(tstart)}{_f(tstop)}",
        HDR,
    ]


def _pm_skew_for(state: ConversionState, pm, keyword: str, ref: str) -> int:
    """The ``skew_ID`` a prescribed motion needs, or 0 for the global system.

    Two independent sources. ``|DOF| in (4, 8)`` WINS over the _LOCAL option,
    because a VID direction is explicitly NOT body-attached — LS-DYNA: "the
    direction is not updated with time" (Manual Vol I R16 p.751):

    1. ``|DOF| in (4, 8)`` — the DOF is expressed along / about the
       *DEFINE_VECTOR ``VID``, not a global axis. The vector's own /SKEW (local
       X' = tail->head = +V, ``_emit_define_vector_skew``) carries it, so
       ``Dir = "X"`` / ``"XX"`` then means "along V" / "about V" exactly as
       LS-DYNA does. This is what dyna2rad does too (``convertbcs.cxx:339``:
       ``inputsystem = GetRadiossSkewIdFromLsdVID(VID)``). k2rad <= PR #116
       wrote ``skew_ID = 0`` here, so DOF 4 became global X and DOF 8 global XX
       with NO warning — a silently wrong direction.
    2. the _LOCAL option's co-rotating /SKEW/MOV (rigid form only), assigned by
       ``_synthesize_local_motion_frames``.

    A negative DOF (-4 / -8) additionally forbids motion in the two transverse
    directions; that lock is emitted separately (see ``_pm_lock_cards``).
    """
    local_skew = getattr(pm, "skew_id", 0)
    if abs(pm.dof) not in (4, 8):
        if pm.vid:
            state.warn(
                f"*{keyword} {ref}: VID={pm.vid} is only used by |DOF| 4 or 8 "
                f"(translation along / rotation about the vector); DOF={pm.dof} "
                "names a global axis, so the vector is ignored — which is what "
                "LS-DYNA does as well.")
        return local_skew
    if not pm.vid:
        state.warn(
            f"*{keyword} {ref}: DOF={pm.dof} means "
            + ("translation along" if abs(pm.dof) == 4 else "rotation about")
            + " the *DEFINE_VECTOR VID, but VID is 0 — the motion is applied "
            "along the GLOBAL "
            + ("X axis" if abs(pm.dof) == 4 else "X axis (XX)")
            + " instead. Give the card a VID.")
        return local_skew
    if local_skew:
        state.warn(
            f"*{keyword} {ref}: DOF={pm.dof} names the *DEFINE_VECTOR VID, and "
            "an explicit vector direction is NOT body-attached (Manual Vol I "
            "R16 p.751: \"the direction is not updated with time\"), so the "
            f"fixed VID skew is used and the co-rotating /SKEW/MOV/{local_skew} "
            "the _LOCAL option built is left unused for this card.")
    # *DEFINE_VECTOR[_NODES] keeps its VID as the /SKEW id when that is free and
    # falls back to a reserved auto id (state.vector_skew_ids records which).
    # A VID naming a *DEFINE_COORDINATE_* system is accepted too, because
    # _make_skews emits all three flavours under their own cid (_SYSTEM and
    # _VECTOR via _emit_skew_fix / _emit_coord_vector_skew, _NODES via
    # _emit_skew_from_nodes) — so a skew with that id really is in the deck and
    # the card resolves. All three registries are tested, the same set
    # _make_body_loads accepts for its CID; leaving coord_nodes out sent a card
    # whose VID named a *DEFINE_COORDINATE_NODES system down the "no /SKEW exists
    # — THE DIRECTION IS WRONG" exit while the skew sat in the same .rad.
    skew_id = state.vector_skew_ids.get(pm.vid)
    if skew_id:
        return skew_id
    if (pm.vid in state.coord_vectors or pm.vid in state.coord_sys
            or pm.vid in state.coord_nodes):
        return pm.vid
    state.warn(
        f"*{keyword} {ref}: DOF={pm.dof} references *DEFINE_VECTOR {pm.vid}, "
        "which is not in the deck (or is degenerate) — no /SKEW exists for it, "
        "so the motion is applied along the GLOBAL "
        + ("X" if abs(pm.dof) == 4 else "XX")
        + " axis instead. THE DIRECTION IS WRONG unless that vector happens to "
        "be the global axis.")
    return local_skew


def _pm_lock_cards(state: ConversionState, pm, keyword: str,
                   ref: str) -> Tuple[List[str], int, List[str]]:
    """The ``Dir`` letters a NEGATIVE DOF (-4 / -8) must additionally hold at
    zero, as ``(dirs, zero_funct_id, funct_lines)``.

    LS-DYNA's -4 / -8 mean "motion along/about VID, and motion in the normal
    directions is NOT permitted" (Manual Vol I R16 p.750). The lock needs a
    synthesized FLAT-ZERO /FUNCT and ``Fscale_Y = 1``, not the real curve with
    ``Fscale_Y = 0``: a zero ordinate scale is SILENTLY replaced by the
    unit-system factor — ``read_impvel.F:248`` ``IF (YSCALE == ZERO) YSCALE =
    ONE * FSCAL_V``. Measured on a live starter run, the lock cards written with
    ``Fscale_Y = 0`` echoed ``FSCALE 1.0`` and would have driven the two
    transverse axes at FULL scale on the real curve — the exact opposite of
    locking them. dyna2rad uses a synthetic 2-point ``(0,0),(1,0)`` function for
    the same reason (``convertbcs.cxx:644,663``).
    """
    if pm.dof not in (-4, -8):
        return [], 0, []
    locked = (["Y", "Z"] if pm.dof == -4 else ["YY", "ZZ"])
    fct = state.next_curve_id()
    lines = _emit_funct(fct, f"ZERO_FUNCT_LOCK_{fct}", [(0.0, 0.0), (1.0, 0.0)])
    state.warn(
        f"*{keyword} {ref}: DOF={pm.dof} also FORBIDS motion in the two "
        f"directions normal to the vector, so {'/'.join(locked)} of the same "
        f"skew are additionally driven to zero — two extra /IMP* cards on a "
        f"synthesized flat-zero /FUNCT/{fct}. It cannot be the real curve with "
        "Fscale_Y = 0: read_impvel.F:248 replaces a zero ordinate scale with "
        "the unit-system factor, so those cards would drive the transverse "
        "axes at FULL scale (measured on a live starter run). dyna2rad uses the "
        "same synthetic 2-point function (convertbcs.cxx:644,663). NOTE the "
        "precondition k2rad does NOT test: LS-DYNA applies the negative forms "
        "\"to rigid bodies [only] if |CMO| = 2 on *MAT_RIGID or "
        "*CONSTRAINED_NODAL_RIGID_BODY\" (p.750). The manual does not document "
        "what it does instead when |CMO| != 2, so k2rad emits the lock either "
        "way rather than guessing the constraint away — on a rigid body with "
        "|CMO| != 2 these two cards may therefore be an OVER-CONSTRAINT LS-DYNA "
        "would have ignored. Check card 2 of the body's *MAT_RIGID / "
        "*CONSTRAINED_NODAL_RIGID_BODY_SPC.")
    return locked, fct, lines


def _body_con1(state: ConversionState, pid: int) -> int:
    """The CMO -1 CON1 (the local system of the body's own constraint card)
    of the rigid body a motion on *pid* drives: the rigid PART's *MAT_RIGID
    (round 9 A1: a clashing CNRB gives way to the part), else a
    *CONSTRAINED_NODAL_RIGID_BODY_SPC of that PID; 0 when none."""
    part = state.parts.get(pid)
    mat = state.mat_rigid.get(part.mid) if part is not None else None
    if mat is not None and mat.cmo < 0:
        return int(mat.con1)
    for c in state.cnrbs:
        if c.pid == pid and getattr(c, "has_spc", False) and c.cmo < 0:
            return int(c.con1)
    return 0


#: (axis index into Tra + Rot) of each /IMP* Dir letter
_DIR_DIGIT = {"X": 0, "Y": 1, "Z": 2, "XX": 3, "YY": 4, "ZZ": 5}


def _shared_local_skew(state: ConversionState, pm, main: int, base_dir: str,
                       mov_skew: int) -> int:
    """round 9, A9 (``--rigid-local-shared-skew``, default ON): the skew a
    ``*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL`` drive is written in.

    The drive's co-rotating ``/SKEW/MOV`` and the body's own CMO -1 ``/BCS``
    (round 8, A1) put TWO skew ids on one main node: the implicit solver then
    condenses the /BCS skew (``bc_imp0.F:159-337``) and the skewed drive
    (``fv_imp0.F:1182-1205``) separately and imposes a frame-dependent wrong
    displacement behind an ERROR 0.0 % (g2g's two-card coupon: x0.750 /
    x-0.5625 of the prescribed value in two oblique frames, x1.000 with one
    skew; nt 2 = nt 4), and the starter prints WARNING 312 (kinset.F:103-105).
    When the main node carries exactly ONE skewed card of its own body
    (decision D12) and (a) that card holds every rotation (Rot 111), (b) the
    drive's frame at t 0 is the card's (LCO == CON1, or every axis pair
    e_i . e_i' >= 1 - 1e-9 - SIGNED: a frame turned 180 degrees about one
    axis has two anti-parallel pairs and would impose the drive backwards in
    the card's skew, measured -0.0100 mm for a prescribed +0.01 mm on the
    W1i coupon, implicit, nt 4), (c) the drive's DOF is not one the card
    holds, the drive is written in the CARD's skew - equal at t 0 and both
    rotate with the body as long as no rotation is free. Otherwise both
    skews stay and the failed condition is named. The /SKEW/MOV and its
    three nodes stay (inert). IMPLICIT decks only (the caller's gate,
    decision A9 'explicit unchanged'): an explicit deck keeps the 386444e
    bytes, where the two skews impose the motion exactly (an explicit
    two-card coupon with a step-setting shell: u . x' = the ramp value,
    x1.0000, with two skews and with one, 665 cycles each, nt 4)."""
    cards = _rigid_skewed_cards(state).get(main, [])
    if len(cards) != 1:
        return mov_skew
    bskew, btitle, btra, brot = cards[0]
    label = f"*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL pid={pm.pid}"
    why = ""
    if brot != "111":
        why = (f"(a) the /BCS {btitle} leaves a rotation free (Rot {brot}), so "
               "the co-rotating frame and the card's fixed one part company")
    else:
        drive_basis = _local_body_basis(state, pm.pid)[0] or (
            (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        con1 = _body_con1(state, pm.pid)
        part = state.parts.get(pm.pid)
        mat = state.mat_rigid.get(part.mid) if part is not None else None
        same_cid = bool(mat is not None and mat.lco and mat.lco == con1)
        coord = (set(state.coord_sys) | set(state.coord_vectors)
                 | set(state.coord_nodes))
        bcs_cid = bskew if bskew in coord else con1
        bcs_basis = (_icid_basis(state, bcs_cid) if bcs_cid else
                     ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
        if not same_cid and (bcs_basis is None or any(
                _vdot(a, b) < 1.0 - 1e-9
                for a, b in zip(drive_basis, bcs_basis))):
            why = (f"(b) the drive's frame at t 0 is not the /BCS {btitle}'s "
                   f"(/SKEW {bskew})")
        elif (btra + brot)[_DIR_DIGIT[base_dir]] == "1":
            why = (f"(c) the /BCS {btitle} also HOLDS the driven DOF "
                   f"{base_dir}: the solver paths disagree on which wins "
                   "(implicit in the moving skew: the /BCS; in one skew and "
                   "explicit: the drive)")
    if why:
        state.warn(
            f"{label}: the drive keeps its co-rotating /SKEW/MOV/{mov_skew} "
            f"beside the body's own CMO -1 /BCS in /SKEW {bskew} - two skew "
            f"ids on one node - because {why}. Two skews on one node make the "
            "IMPLICIT solver impose a frame-dependent wrong displacement with "
            "a 0.0 % energy error and the starter print WARNING 312; check "
            "the motion.")
        return mov_skew
    state.warn(
        f"{label}: the drive is written in /SKEW/{bskew}, the skew of the "
        f"body's own CMO -1 /BCS {btitle}, instead of the co-rotating "
        f"/SKEW/MOV/{mov_skew}: the frames are equal at t 0 and the /BCS holds "
        "every rotation, so they stay equal. Two skew ids on one node make "
        "the IMPLICIT solver impose a frame-dependent wrong displacement with "
        "a 0.0 % energy error (a two-block coupon: x0.750 / x-0.5625 of the "
        "prescribed value in two oblique frames, x1.000 in one skew; nt 2 = "
        "nt 4) and the starter print WARNING 312. "
        "--no-rigid-local-shared-skew keeps the two skews.")
    return bskew


def _make_imposed_motions(state: ConversionState, rbody_info: Dict) -> List[str]:
    """*BOUNDARY_PRESCRIBED_MOTION_RIGID[_LOCAL] -> /IMPVEL | /IMPACC | /IMPDISP
    on the rigid body's /RBODY main node."""
    lines: List[str] = []
    # A converted *CONSTRAINED_JOINT_SCREW's drive is re-written as
    # /IMPVEL/LAGMUL by the joint section (round 7, B2): skip it here,
    # matched by identity, without drawing a counter value.
    from .joint_screw import screw_drives
    lagmul_drives = {id(pm) for pm in screw_drives(state)}
    if not [pm for pm in state.prescribed_motions
            if id(pm) not in lagmul_drives]:
        return lines
    lines.append("#-  IMPOSED MOTIONS:")

    # /IMPVEL, /IMPACC and /IMPDISP ids come from a local counter, not
    # state.next_id(). _make_imposed_motions_set writes the same three keywords,
    # but from next_id(), whose _auto_id base is 90001 — far above anything this
    # counter reaches — so the two cannot collide, and no user id can either (the
    # starter's UDOUBLE scan runs separately per option,
    # hm_read_impvel.F:129/169). Keeping the counter means a deck with no _LOCAL /
    # no VID motion converts byte-identically to PR #116.
    motion_counter = 1
    # Several cards may drive the same body on different DOFs, and the _LOCAL
    # prepass gives them ONE shared /SKEW/MOV — emitting the card per motion
    # would write that id twice (starter ERROR 79 DUPLICATE ID over the merged
    # /SKEW+/FRAME table, no restart file).
    skews_written: Set[int] = set()
    for pm in state.prescribed_motions:
        if id(pm) in lagmul_drives:
            continue
        keyword = ("BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL" if pm.local
                   else "BOUNDARY_PRESCRIBED_MOTION_RIGID")
        info = rbody_info.get(pm.pid)
        if not info:
            state.warn(f"BOUNDARY_PRESCRIBED_MOTION_RIGID pid={pm.pid}: no RBODY found; motion skipped")
            continue

        # Impose the motion on the rigid body's PRIMARY (master) node only, NOT on
        # every node of the rigid part. The secondary nodes are slaved by /RBODY;
        # adding /IMPDISP on them creates "incompatible kinematic conditions"
        # (Starter WARNING ID 312) which OpenRadioss resolves in favour of the
        # rigid body — silently dropping the imposed motion so the part never moves
        # (zero reaction → zero strain energy → zero stress). Driving the master
        # node (the same node the rigid-body /BCS constrains) translates the whole
        # body correctly.
        grnod_id = info["ind_grnod_id"]
        base_dir = _DOF_DIR.get(abs(pm.dof))
        if base_dir is None:
            state.warn(
                f"*{keyword} pid={pm.pid}: DOF={pm.dof} has no /IMP* Dir "
                "equivalent — nothing emitted. |DOF| 9/10/11 rotate about an "
                "axis parallel to x/y/z through (OFFSET1, OFFSET2), which "
                "LS-DYNA itself does not allow on a rigid body, and DOF=12 "
                "(translation along segment normals) is *_SET_SEGMENT only. "
                "dyna2rad emits an EMPTY /IMPVEL for these instead "
                "(convertbcs.cxx:634-675).")
            continue
        ref = f"pid={pm.pid}"
        skew_id = _pm_skew_for(state, pm, keyword, ref)
        # round 9, A9: a _LOCAL drive shares the skew of its body's own CMO -1
        # /BCS when the two frames are one (no second skew id on the node) -
        # on an IMPLICIT deck only (decision A9: explicit unchanged)
        if (pm.local and skew_id and skew_id == getattr(pm, "skew_id", 0)
                and state.is_implicit
                and state.options.rigid_local_shared_skew):
            skew_id = _shared_local_skew(state, pm, info["ind_node"],
                                         base_dir, skew_id)
        tstart = pm.birth if pm.birth < 1e27 else 0.0
        tstop = pm.death if pm.death < 1e27 else 0.0
        # PM_VAD_KEYWORD is the SAME dict handlers._pm_vad_supported gates on,
        # so this index can never miss (a VAD outside it never reaches here).
        kw = PM_VAD_KEYWORD[pm.vad]
        if pm.local and pm.skew_id and pm.skew_id not in skews_written:
            skews_written.add(pm.skew_id)
            lines += _emit_skew_mov(
                pm.skew_id, f"SKEW_MOV_LOCAL_PID{pm.pid}", *pm.mov_nodes, "X")
        if pm.sf == 0.0 and state.options.prescribed_motion_sf_default:
            # round 9, A8: bytes only - the starter already reads 0 as 1.0
            state.warn(
                f"*{keyword} pid={pm.pid} dof={pm.dof}: SF = 0.0 written as "
                "the default Fscale 1.0; the OpenRadioss starter reads 0 as "
                "1.0 too (read_impdisp.F:239), so the motion is unchanged - "
                "only the card now says what runs (LS-DYNA: SF 'The default "
                "is 1.0', Vol I R17 p.759). --no-prescribed-motion-sf-default "
                "writes the stated 0.")
        lines += _emit_imp_card(kw, motion_counter, f"Motion_{motion_counter}",
                                pm.lcid, base_dir, grnod_id, _pm_sf(state, pm),
                                tstart, tstop, skew_id, state=state)
        motion_counter += 1
        _register_imp_motion_nodes(state, [info["ind_node"]], base_dir, skew_id,
                                   tstart, tstop)
        locked, zero_fct, fct_lines = _pm_lock_cards(state, pm, keyword, ref)
        lines += fct_lines
        for lock_dir in locked:
            lines += _emit_imp_card(kw, motion_counter,
                                    f"Motion_{motion_counter}_lock",
                                    zero_fct, lock_dir, grnod_id, 1.0,
                                    tstart, tstop, skew_id, state=state)
            motion_counter += 1
            _register_imp_motion_nodes(state, [info["ind_node"]], lock_dir,
                                       skew_id, tstart, tstop)
    # A triad the prepass built for a card the loop then dropped (no /RBODY for
    # the pid — an element-free rigid part, or a *CONSTRAINED_RIGID_BODIES slave
    # whose nodes were merged into its master) still has its three nodes in /NODE
    # and in the body's /RBODY secondary group. Write the /SKEW/MOV that explains
    # them rather than leaving three unaccounted-for element-free nodes behind
    # and a prepass warning describing a skew the deck does not contain. An
    # unreferenced /SKEW is inert.
    for pm in state.prescribed_motions:
        if pm.local and pm.skew_id and pm.skew_id not in skews_written:
            skews_written.add(pm.skew_id)
            lines += _emit_skew_mov(
                pm.skew_id, f"SKEW_MOV_LOCAL_PID{pm.pid}", *pm.mov_nodes, "X")
    return lines


def _cnrb_gives_way(state: ConversionState, pid: int) -> bool:
    """round 9, A1 (``--rigid-part-pid-precedence``, default ON): True when a
    *CONSTRAINED_NODAL_RIGID_BODY with this PID gives way to the rigid PART of
    the same id - a *MAT_RIGID / *DEFORMABLE_TO_RIGID part that owns nodes and
    so becomes an /RBODY of its own (LS-DYNA's Warning 10177 drives the
    part). Read from the deck, not from ``state.cnrb_record_key``: the
    _LOCAL frame reservation runs BEFORE the /RBODY builders set that."""
    if not state.options.rigid_part_pid_precedence:
        return False
    if pid not in state.parts or pid not in rigid_part_ids(state):
        return False
    if not any(c.pid == pid for c in state.cnrbs):
        return False
    return (bool(_part_node_sets(state).get(pid))
            or bool(state.extra_rigid_nodes.get(pid))
            or any(c.pid == pid for c in state.sph_elems))


def _local_body_basis(state: ConversionState, pid: int):
    """The rigid body's OWN local system, as ``(basis, source)`` where *basis* is
    the global-frame orthonormal triad ``(ex, ey, ez)``, or ``(None, reason)``.

    LS-DYNA takes the *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL system from
    "LCO and CID in *MAT_RIGID and *CONSTRAINED_NODAL_RIGID_BODY, respectively.
    If LCO/CID is 0, the local coordinate system defaults to the principal
    inertia directions of the rigid body" (Manual Vol I R16 p.756-757 Remark 7;
    *MAT_RIGID's own card 3 repeats it, Vol II R16 p.2-233). k2rad parses both,
    so both are honoured EXACTLY:

      * ``CID`` on *CONSTRAINED_NODAL_RIGID_BODY, and ``LCO`` on *MAT_RIGID card
        3, are *DEFINE_COORDINATE_* ids — the /SKEW k2rad already emits for them,
        read back through ``_icid_basis``;
      * *MAT_RIGID card 3's alternative ``A1-V3`` pair gives the triad directly:
        "the output parameters are in the directions a, b, and c where the latter
        are given by the cross products c = a x v and b = c x a".

    Only the LCO/CID = 0 default is unrecoverable, because it needs the body's
    inertia tensor and k2rad computes none. A CNRB whose PID collides with a
    rigid part's id resolves to the PART under --rigid-part-pid-precedence
    (the default, round 9 A1: LS Warning 10177 drives the part), to the CNRB
    without it.
    """
    yields = _cnrb_gives_way(state, pid)
    for c in state.cnrbs:
        if c.pid != pid or yields:
            continue
        if not c.cid:
            return None, ("*CONSTRAINED_NODAL_RIGID_BODY CID is 0, so LS-DYNA "
                          "uses the body's PRINCIPAL INERTIA directions")
        basis = _icid_basis(state, c.cid)
        if basis is None:
            return None, (f"*CONSTRAINED_NODAL_RIGID_BODY CID={c.cid} is not a "
                          "*DEFINE_COORDINATE_* system in the deck (or is "
                          "degenerate)")
        return basis, f"CID={c.cid} on *CONSTRAINED_NODAL_RIGID_BODY {pid}"
    part = state.parts.get(pid)
    mat = state.mat_rigid.get(part.mid) if part is not None else None
    if mat is None:
        return None, "the part has no *MAT_RIGID card to read a local system from"
    if mat.a_vec is not None and mat.v_vec is not None:
        ex = _vnorm(mat.a_vec)
        ez = _vnorm(_vcross(mat.a_vec, mat.v_vec)) if ex is not None else None
        if ex is None or ez is None:
            return None, (f"*MAT_RIGID {mat.mid} card 3 gives A1-V3, but a and v "
                          "are zero or parallel so c = a x v is degenerate")
        return (ex, _vcross(ez, ex), ez), \
            f"the A1-V3 vector pair on *MAT_RIGID {mat.mid} card 3"
    if not mat.lco:
        return None, (f"LCO on *MAT_RIGID {mat.mid} card 3 is 0 (or blank), so "
                      "LS-DYNA uses the body's PRINCIPAL INERTIA directions")
    basis = _icid_basis(state, mat.lco)
    if basis is None:
        return None, (f"LCO={mat.lco} on *MAT_RIGID {mat.mid} card 3 is not a "
                      "*DEFINE_COORDINATE_* system in the deck (or is degenerate)")
    return basis, f"LCO={mat.lco} on *MAT_RIGID {mat.mid} card 3"


def _synthesize_local_motion_frames(state: ConversionState) -> None:
    """build_starter prepass: give every *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL
    a co-rotating /SKEW/MOV, by synthesizing three nodes that ride the body.

    **Why a moving SKEW.** With the _LOCAL option LS-DYNA expresses DOF in the
    rigid body's own system, whose "orientation rotates with time in accordance
    with the rotation of the rigid body" (Manual Vol I R16 p.756-757 Remark 7).
    A /SKEW/MOV is rebuilt from its three nodes' CURRENT coordinates every cycle
    (``newskw.F``, "SKEW MOBILE", called from ``resol``) and ``fixvel.F:390-417``
    projects the imposed component onto that freshly-updated row — so three nodes
    that move rigidly with the body give exactly the co-rotating triad, and no
    fictitious forces (a moving SKEW carries no omega, unlike a moving FRAME, so
    no entrainment or Coriolis term is ever added — which is what is wanted).
    The skew goes in the ``skew_ID`` column, the only system column that works on
    all three of /IMPVEL, /IMPACC and /IMPDISP (see _emit_imp_card).

    **Why synthesized nodes and not three mesh nodes.** The /SKEW/MOV triad is
    fully determined by its N1/N2/N3, so three arbitrary mesh nodes would give
    some mesh direction, not the body's local axes — a silent redefinition of
    what DOF means. Three purpose-built nodes place the triad exactly. They are
    element-free, so they add no mass and no inertia (the same trick
    ``--rigid-cog-master`` already uses for the /RBODY main), and they are folded
    into the body's /RBODY secondary group via ``state.local_frame_nodes`` so
    they co-rotate with it.

    **The triad's ORIENTATION.** ``_local_body_basis`` reads the body's own local
    system from LCO on *MAT_RIGID card 3 or CID on *CONSTRAINED_NODAL_RIGID_BODY
    — the two fields LS-DYNA itself names (Manual Vol I R16 p.756-757 Remark 7)
    — and places N2/N3 along that ex/ey, so a deck that states its local system
    converts EXACTLY. Only the LCO/CID = 0 default is out of reach: it is the
    body's PRINCIPAL INERTIA directions and k2rad computes no inertia tensor. The
    triad then falls back to the GLOBAL axes and the residual is the CONSTANT
    rotation R0 between them and the true principal system — exact when the body
    happens to be principal-aligned, a fixed misalignment otherwise. Even that is
    strictly better than the Radioss dyna-reader, which never reads
    ``localOption`` at all (``convertbcs.cxx`` has no match for LOCAL) and so
    freezes the axes at t=0 — an error that GROWS as cos(theta(t)) and becomes
    meaningless once the body has turned ~90 degrees.

    Must run BEFORE the /NODE section (the helper nodes have to be emitted),
    before the /RBODY sections (which read ``local_frame_nodes``) and before
    /FRAME allocation (which shares the /SKEW id namespace).
    """
    # A motion on a part that is neither *MAT_RIGID nor a *CONSTRAINED_NODAL_
    # RIGID_BODY has no /RBODY to drive at all: the writer drops it with its own
    # "no RBODY found" warning, and building a triad for it would leave three
    # free nodes attached to nothing. Same reason for the _DOF_DIR test: a DOF
    # with no /IMP* Dir letter (9/10/11/12) is refused by the writer, so a triad
    # for it would be three unexplained nodes plus a warning promising a
    # co-rotating skew that the .rad never contains.
    rigid_pids = set(rigid_part_ids(state))      # *MAT_RIGID + *DEFORMABLE_TO_RIGID
    rigid_pids |= {c.pid for c in state.cnrbs}
    locals_ = [pm for pm in state.prescribed_motions
               if pm.local and pm.pid in rigid_pids
               and _DOF_DIR.get(abs(pm.dof)) is not None]
    if not locals_:
        return
    # Node coordinates of each candidate body, to scale the helper offsets: a
    # unit offset on a micrometre-scale model would sit at the rounding limit of
    # the F20 coordinate fields. newskw.F normalises the triad, so only the
    # conditioning matters.
    pnodes = _part_node_sets(state)
    next_node = (max(state.nodes) + 1) if state.nodes else 90000001
    done: Dict[int, Tuple[int, Tuple[int, int, int]]] = {}
    for pm in locals_:
        if pm.pid in done:
            pm.skew_id, pm.mov_nodes = done[pm.pid]
            continue
        pts = [state.nodes[n] for n in pnodes.get(pm.pid, ()) if n in state.nodes]
        if not pts:
            # A CNRB target (its nodes belong to deformable parts) or an
            # element-free part: fall back to the model bbox for the scale and
            # the global origin for the reference point. Both are only used for
            # conditioning — the triad's DIRECTIONS are what carry the physics.
            pts = list(state.nodes.values())
        if not pts:
            state.warn(
                f"*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL pid={pm.pid}: the deck "
                "has no nodes, so no co-rotating /SKEW/MOV could be built — the "
                "motion is applied in the GLOBAL system (which is what the "
                "Radioss dyna-reader always does).")
            continue
        k = len(pts)
        cx = sum(p.x for p in pts) / k
        cy = sum(p.y for p in pts) / k
        cz = sum(p.z for p in pts) / k
        span = max(max(p.x for p in pts) - min(p.x for p in pts),
                   max(p.y for p in pts) - min(p.y for p in pts),
                   max(p.z for p in pts) - min(p.z for p in pts))
        s = span * 0.1 if span > 0.0 else 1.0
        basis, why = _local_body_basis(state, pm.pid)
        ex, ey = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) if basis is None \
            else (basis[0], basis[1])
        n1, n2, n3 = next_node, next_node + 1, next_node + 2
        next_node += 3
        state.nodes[n1] = NodeData(cx, cy, cz)
        # N1->N2 = the body's local X'; N3 fixes the X'Y' plane.
        state.nodes[n2] = NodeData(cx + s * ex[0], cy + s * ex[1], cz + s * ex[2])
        state.nodes[n3] = NodeData(cx + s * ey[0], cy + s * ey[1], cz + s * ey[2])
        pm.skew_id = state.reserve_skew_id(state.next_id())
        pm.mov_nodes = (n1, n2, n3)
        state.local_frame_nodes.setdefault(pm.pid, []).extend([n1, n2, n3])
        done[pm.pid] = (pm.skew_id, pm.mov_nodes)
        common = (
            f"*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL pid={pm.pid}: the DOF is "
            f"driven in a CO-ROTATING /SKEW/MOV/{pm.skew_id}, built on three "
            f"synthesized element-free nodes ({n1}, {n2}, {n3}) that join the "
            "body's /RBODY secondary group so the triad turns with it "
            "(newskw.F rebuilds it every cycle; fixvel.F:390-417 projects the "
            "imposed component onto the updated row). ")
        if basis is not None:
            state.warn(
                common
                + f"Its axes are taken from {why}, which is the field LS-DYNA "
                "itself reads for this option (Manual Vol I R16 p.756-757 "
                "Remark 7), so the local system is reproduced EXACTLY. (The "
                "Radioss dyna-reader ignores the _LOCAL flag entirely, which "
                "freezes the axes at t=0 instead: an error that grows with the "
                "body's rotation.)")
        else:
            state.warn(
                common
                + f"Its axes are INITIALISED TO THE GLOBAL AXES because {why}, "
                "and k2rad computes no inertia tensor, so the true orientation "
                "cannot be recovered. The conversion is therefore EXACT only if "
                "the body's local system is global-aligned at t=0 and off by "
                "that CONSTANT rotation otherwise — check the \"principal "
                "directions\" block of the LS-DYNA d3hsp mass summary, and name "
                "the system explicitly (LCO on *MAT_RIGID card 3, or CID on "
                "*CONSTRAINED_NODAL_RIGID_BODY) to make it exact. (The Radioss "
                "dyna-reader ignores the _LOCAL flag entirely, which freezes the "
                "axes at t=0 instead: an error that grows with the body's "
                "rotation.)")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: imposed motions for node sets
# ─────────────────────────────────────────────────────────────────────────────

# LS-DYNA *BOUNDARY_PRESCRIBED_MOTION DOF → (translation, rotation) /BCS codes.
# 1/2/3 = Tx/Ty/Tz, 5/6/7 = Rx/Ry/Rz. DOF 4 (translation along vector VID) and
# 8 (rotation about VID) have no global X/Y/Z /BCS code and are not mapped here.
_PM_DOF_TO_BCS = {
    1: ("100", "000"), 2: ("010", "000"), 3: ("001", "000"),
    5: ("000", "100"), 6: ("000", "010"), 7: ("000", "001"),
}


def _or_dof_codes(codes: List[str]) -> str:
    """OR a list of 3-char DOF codes, e.g. ['100','001'] → '101'."""
    out = ["0", "0", "0"]
    for c in codes:
        for i in range(3):
            if c[i] == "1":
                out[i] = "1"
    return "".join(out)


def _pm_set_nodes(state: ConversionState, pm,
                  box_cache: Optional[Dict[int, Optional[Set[int]]]] = None
                  ) -> Optional[List[int]]:
    """The node ids one *BOUNDARY_PRESCRIBED_MOTION_SET[_BOX] row drives, or
    None (already warned) when the row cannot be resolved.

    Three shapes, exactly the ones ``convertbcs.cxx:465-540`` distinguishes:

      * NSID, no BOXID   -> the node set verbatim;
      * NSID and BOXID   -> the INTERSECTION with the box's contained nodes
        (dyna2rad builds a /SET/GENERAL with a ``SET`` clause plus a ``SET_I``
        clause, ``:493-520``; k2rad resolves the same membership numerically,
        like every other *DEFINE_BOX consumer);
      * BOXID, no NSID   -> every node inside the box (``:522-535``).

    **Caveat, warned:** LS-DYNA re-evaluates box membership as nodes move in and
    out of the box every timestep; both the numeric resolution here and the
    dyna2rad /SET/GENERAL are a t = 0 SNAPSHOT.

    ``box_cache`` memoizes the per-box resolution across the rows of one deck, so
    N rows naming one missing box report it once instead of N times.
    """
    if pm.boxid:
        label = f"*BOUNDARY_PRESCRIBED_MOTION_SET_BOX nsid={pm.nsid}"
        if box_cache is not None and pm.boxid in box_cache:
            box_nodes = box_cache[pm.boxid]
        else:
            box_nodes = _resolve_box_nodes(state, pm.boxid, label)
            if box_cache is not None:
                box_cache[pm.boxid] = box_nodes
        if pm.nsid:
            if pm.nsid not in state.node_sets:
                state.warn(f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: node set not found – skipped")
                return None
            nids = state.node_sets[pm.nsid][1]
            if box_nodes is None:               # undefined/degenerate box
                return list(nids)
            kept = [n for n in nids if n in box_nodes]
            if not kept:
                state.warn(
                    f"{label}: no node of set {pm.nsid} lies inside "
                    f"*DEFINE_BOX {pm.boxid} (of {len(nids)} in the set) — the "
                    "motion is dropped. LS-DYNA would still pick nodes up as "
                    "they ENTER the box during the run; a Radioss node group is "
                    "resolved once, on the t=0 geometry.")
                return None
            if len(kept) < len(nids):
                state.warn(
                    f"{label}: {len(kept)} of {len(nids)} set nodes lie inside "
                    f"*DEFINE_BOX {pm.boxid} and are driven. The membership is a "
                    "t=0 SNAPSHOT — LS-DYNA re-tests the box every timestep, so "
                    "nodes that move into it later are NOT picked up (and nodes "
                    "that leave keep being driven).")
            return kept
        if box_nodes is None:
            return None
        if not box_nodes:
            state.warn(f"{label}: *DEFINE_BOX {pm.boxid} contains no node — the "
                       "motion is dropped.")
            return None
        state.warn(
            f"*BOUNDARY_PRESCRIBED_MOTION_SET_BOX: NSID is 0, so the box alone "
            f"is the group — all {len(box_nodes)} node(s) inside *DEFINE_BOX "
            f"{pm.boxid} are driven (t=0 snapshot; see above).")
        return sorted(box_nodes)
    # No box: the plain _SET / _NODE path, byte- and message-identical to what
    # k2rad has always emitted. A card that names neither a set nor a box lands
    # here with nsid = 0, which is not a node set either, so it takes the same
    # "node set not found" exit. (The Radioss dyna-reader leaves its set id
    # uninitialised in that case, behind an empty "// warning / error" comment,
    # convertbcs.cxx:536-539.)
    if pm.nsid not in state.node_sets:
        state.warn(f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: node set not found – skipped")
        return None
    return list(state.node_sets[pm.nsid][1])


def _make_imposed_motions_set(state: ConversionState) -> List[str]:
    lines: List[str] = []
    if not state.prescribed_motion_sets:
        return lines

    # _BOX card 2 fields with no OpenRadioss target. Reported once per deck.
    if any(pm.toffset for pm in state.prescribed_motion_sets):
        state.warn(
            "*BOUNDARY_PRESCRIBED_MOTION_SET_BOX: TOFFSET=1 (\"the time value "
            "of the load curve, LCID, will be offset by the time when the node "
            "enters the box\") has no OpenRadioss equivalent — DROPPED. The "
            "curve is evaluated against absolute time for every driven node, so "
            "nodes LS-DYNA would start later start at t=0 here. dyna2rad drops "
            "it silently.")
    if any(pm.lcbchk for pm in state.prescribed_motion_sets):
        state.warn(
            "*BOUNDARY_PRESCRIBED_MOTION_SET_BOX: LCBCHK (curve giving the "
            "discrete box-check times) has no OpenRadioss equivalent — DROPPED. "
            "Radioss resolves the box once, on the t=0 geometry, so there is "
            "nothing to schedule re-checks for. dyna2rad drops it silently.")

    # LS-DYNA convention: *BOUNDARY_PRESCRIBED_MOTION_SET with sf=0 means "fix this
    # DOF" (zero x any_curve = 0 displacement = fixed). Emit a /BCS (constraint)
    # instead of an /IMPDISP with a bogus unit scale — critical for symmetry BCs
    # (treated as IMPDISP with sf=1 the plane nodes would get spurious motion and
    # the stiffness matrix would go singular). All fixed DOFs of one node set are
    # combined into ONE /BCS (OpenRadioss applies the union) rather than one card
    # per DOF — fewer cards and no dependence on whether multiple /BCS stack.
    # Keyed by (nsid, boxid): two rows on the same NSID but different boxes drive
    # different node lists and must not share one /BCS.
    fix_tra: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    fix_rot: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    fix_nodes: Dict[Tuple[int, int], List[int]] = {}
    fix_order: List[Tuple[int, int]] = []
    # (row, its resolved node ids) — carried together rather than looked up by
    # id(pm) later, which only stays unique while the objects are alive.
    motions: List[Tuple[PrescribedMotionSet, List[int]]] = []
    box_cache: Dict[int, Optional[Set[int]]] = {}
    for pm in state.prescribed_motion_sets:
        nids = _pm_set_nodes(state, pm, box_cache)
        if nids is None:
            continue
        hold = _pm_zero_hold(state, pm)
        if pm.sf == 0.0 and not hold:
            # round 9, A8: a stated SF 0.0 is LS-DYNA's 1.0
            state.warn(
                "*BOUNDARY_PRESCRIBED_MOTION_NODE / _SET "
                f"nsid={pm.nsid} dof={pm.dof}: SF = 0.0 is read as the card's "
                "default 1.0 (Vol I R17 p.759; Appendix V p.73-9) and curve "
                f"{pm.lcid} (VAD {pm.vad}) is not a zero motion, so the motion "
                f"is IMPOSED (/{PM_VAD_KEYWORD[pm.vad]} Fscale 1); before round "
                "9 k2rad held the DOF with a /BCS. A zero motion (VAD 0 / 2 on a "
                "zero curve, or no curve) stays a /BCS hold; VAD 1 on a zero "
                "curve is imposed (the node keeps its initial velocity). "
                "--no-prescribed-motion-sf-default restores the hold.")
        if hold:
            mapped = _PM_DOF_TO_BCS.get(pm.dof)
            if mapped is None:
                state.warn(
                    f"BOUNDARY_PRESCRIBED_MOTION_SET nsid={pm.nsid}: dof={pm.dof} is "
                    "not a global X/Y/Z translation (1-3) or rotation (5-7) — e.g. "
                    "4/8 act along a vector — so no zero-motion /BCS was emitted."
                )
                continue
            key = (pm.nsid, pm.boxid)
            if key not in fix_tra:
                fix_order.append(key)
                fix_nodes[key] = nids
            fix_tra[key].append(mapped[0])
            fix_rot[key].append(mapped[1])
        else:
            motions.append((pm, nids))

    for key in fix_order:
        nsid, boxid = key
        set_title = state.node_sets.get(nsid, ("", []))[0]
        nids = fix_nodes[key]
        tra = _or_dof_codes(fix_tra[key])
        rot = _or_dof_codes(fix_rot[key])
        bc_id = state.next_id()
        # next_grnod_id, not next_id: a user *SET_NODE whose SID sits at or above
        # the auto-id base is re-emitted verbatim as /GRNOD/NODE/<sid>, and a
        # collision is starter ERROR 79 DUPLICATE ID / IN NODE GROUP DEFINITION
        # with no restart file. The motion path below already drew from it; this
        # branch, four lines away, still used the unguarded counter.
        grnod_id = state.next_grnod_id()
        lines += [
            f"/BCS/{bc_id}",
            set_title or f"BC_set_{nsid}",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {tra} {rot}         0{_i(grnod_id)}",
            HDR,
        ]
        lines += _emit_grnod_node(grnod_id, set_title or f"SET_{nsid}", nids)

    # Non-zero scale: real prescribed motion → /IMPDISP, /IMPVEL, /IMPACC
    for pm, nids in motions:
        keyword = ("BOUNDARY_PRESCRIBED_MOTION_SET_BOX" if pm.boxid
                   else "BOUNDARY_PRESCRIBED_MOTION_SET")
        set_title = state.node_sets.get(pm.nsid, ("", []))[0]
        base_dir = _DOF_DIR.get(abs(pm.dof))
        if base_dir is None:
            state.warn(
                f"*{keyword} nsid={pm.nsid}: DOF={pm.dof} has no /IMP* Dir "
                "equivalent — nothing emitted. |DOF| 9/10/11 rotate about an "
                "axis parallel to x/y/z through the (OFFSET1, OFFSET2) point of "
                "the continuation card, and DOF=12 (translation along the "
                "segment normals) belongs to *_SET_SEGMENT — neither is a "
                "single skew axis, so no Dir letter can carry it. dyna2rad "
                "emits an EMPTY /IMPVEL for these (convertbcs.cxx:634-675).")
            continue
        ref = f"nsid={pm.nsid}"
        skew_id = _pm_skew_for(state, pm, keyword, ref)
        grnod_id = state.next_grnod_id()
        motion_id = state.next_id()
        tstart = pm.birth if pm.birth < 1e27 else 0.0
        tstop  = pm.death if pm.death < 1e27 else 0.0
        # PM_VAD_KEYWORD is the SAME dict handlers._pm_vad_supported gates on,
        # so this index can never miss (a VAD outside it never reaches here).
        kw = PM_VAD_KEYWORD[pm.vad]
        lines += _emit_imp_card(kw, motion_id, f"Motion_{motion_id}", pm.lcid,
                                base_dir, grnod_id, _pm_sf(state, pm), tstart,
                                tstop, skew_id, state=state)
        lines += _emit_grnod_node(grnod_id, set_title or f"SET_{pm.nsid}", nids)
        _register_imp_motion_nodes(state, nids, base_dir, skew_id, tstart,
                                   tstop)
        locked, zero_fct, fct_lines = _pm_lock_cards(state, pm, keyword, ref)
        lines += fct_lines
        for lock_dir in locked:
            lock_id = state.next_id()
            lines += _emit_imp_card(kw, lock_id, f"Motion_{lock_id}_lock",
                                    zero_fct, lock_dir, grnod_id, 1.0,
                                    tstart, tstop, skew_id, state=state)
            _register_imp_motion_nodes(state, nids, lock_dir, skew_id, tstart,
                                       tstop)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: gravity loads
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grnod_part(grnod_id: int, title: str, pids: List[int]) -> List[str]:
    """/GRNOD/PART — a node group holding all nodes of the listed parts."""
    lines = [f"/GRNOD/PART/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for p in pids:
        row.append(str(p).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


# ── /GRAV card layout ────────────────────────────────────────────────────────
# grav.cfg (radioss51 FORMAT, LOADS/grav.cfg:110-114) is
#   CARD("%10d%10s%10d%10d%10d          %20lg%20lg", curveid, rad_dir,
#        inputsystem, rad_sensor_id, entityid, xscale, magnitude);
# — note the TEN literal blank columns (51-60) between grnod_ID and Ascale_x.
# The data line is 100 characters wide: Ascale_x right-aligned at column 80,
# Fscale_Y at column 100 (cross-checked against Altair's own reference deck
# demos_example/.../RD-E-1602_Implicit/.../SEAT_0000.rad:10907-10910).
#
# k2rad used to pack the fields with no gap, putting Ascale_x at 51-70 and
# Fscale_Y at 71-90. That happened to READ correctly only while both rendered
# numbers were <= 10 characters, because _f right-aligns in width 20. The
# moment Fscale_Y is longer the field boundary cuts through it and the starter
# silently takes the wrong number — measured with starter_win64.exe:
#
#   Fscale_Y written    starter echo SCALE_Y      verdict
#   -9810               -9810.000000000           ok (5 chars)
#   -0.00980665          9.8066500000000E-03      SIGN LOST -> gravity up
#   -9.810000E-06        0.8100000000000          sign lost + 8e4x magnitude
#
# i.e. every mm/ms (0.00980665) or %.6E deck. Signed Fscale_Y is now the norm
# on both gravity paths, so the gap is not cosmetic.
_GRAV_GAP = " " * 10
_GRAV_COMMENT = ("#funct_IDT       DIR   skew_ID sensor_ID  grnod_ID"
                 "                      Ascale_x            Fscale_Y")


def _emit_grav_card(grav_id: int, title: str, fct: int, direction: str,
                    grnod_id: int, fscale: float,
                    skew_id: int = 0,
                    state: Optional[ConversionState] = None) -> List[str]:
    """One /GRAV card in the column layout grav.cfg specifies (see above).

    ``Ascale_x`` is always 1.0: the starter stores ``GRAV(2,K) = ONE/FCX``
    (hm_read_grav.F:236) and the engine evaluates the curve at ``t * FCX``, so
    it is a divisor on the time abscissa, not an ordinate scale.

    ``skew_id`` names the local system the DIR axis is taken in: the starter
    resolves it to an internal index (hm_read_grav.F:177-186 — a MISSING skew
    id is MSGID=137, a starter ERROR, so only ever pass an id that is really
    emitted) and the engine then adds the acceleration along that skew's row
    for DIR instead of the global axis (gravit.F:150-162,
    ``A(1..3,N) += SKEW(3*N2-2..3*N2, ISK) * AA``). 0 = global.

    Pass *state* to read a curve OpenRadioss would extrapolate nonzero
    through its zero-off-scale copy (round 9, B5, writer/loadcurves.py).
    """
    if state is not None:
        from .loadcurves import load_funct_id
        fct = load_funct_id(state, fct, "GRAV")
    return [
        f"/GRAV/{grav_id}",
        title,
        _GRAV_COMMENT,
        f"{_i(fct)}{direction.rjust(10)}{_i(skew_id)}{_i(0)}{_i(grnod_id)}"
        f"{_GRAV_GAP}{_f(1.0)}{_f(fscale)}",
        HDR,
    ]


def _rbody_mains_in_scope(state: ConversionState, rbody_info: Dict,
                          pids: List[int], whole_model: bool,
                          pnodes: Optional[Dict] = None,
                          keyword: str = "") -> Tuple[Set[int], List[int]]:
    """Which parts of a /GRAV scope are rigid, and which /RBODY main nodes the
    /GRAV must therefore load.  Returns ``(rigid_part_pids, main_node_ids)``.

    **Why this exists.** /GRAV adds an ACCELERATION to every node of its group
    (``gravit.F:147``: ``A(N2,N1) = A(N2,N1) + AA``, no mass factor — the mass
    only appears in the external-work term). In ``resol.F`` that happens at
    line 6884, i.e. 1382 lines AFTER ``RBYFOR`` (5502) has already summed the
    secondary-node forces into the rigid-body main node, and before ``RBYVIT``
    (7572) → ``rgbodv.F:109-155`` **overwrites** ``A(1..3,N)`` of every
    secondary from the main (``=``, not ``+=``). Gravity deposited on a rigid
    secondary node is therefore never transmitted and then discarded: net
    effect on motion exactly zero.

    With ``--rigid-cog-master`` (the default since PR #54) the main node is a
    synthesized element-free node at the part centroid, so it is in no element
    and can never appear in a ``/GRNOD/PART``. Measured on a free rigid block
    with ``*LOAD_BODY_Y``: as converted the block never moved (526 cycles, all
    displacements 0, KE = 0); with the main node in the group it free-falls
    exactly (DY 4.727803E-01 vs the analytic 4.727802E-01 mm).

    **The mapping.** For a part that k2rad turned into an /RBODY the part is
    swapped OUT of the /GRNOD/PART and its main node put in instead — what
    dyna2rad does for ``*LOAD_GRAVITY_PART`` (``convertloads.cxx:887-902``,
    ``storeRbodyPIDVsMasterNode``). The main carries the summed mass of the
    whole body (``inirby.F:187-243, 837``), so one main node at ``g`` is the
    exact load, and dropping the secondaries keeps ``WFEXT`` exact too — the
    starter does NOT zero secondary masses, so leaving them in the group would
    accumulate a spurious ``Σ m_secondary·g·v·dt`` in the energy balance
    (``gravit.F:148``) without changing a single displacement.

    A *CONSTRAINED_NODAL_RIGID_BODY is different: its secondaries are ordinary
    nodes of DEFORMABLE parts, so the part cannot be swapped out. Its main is
    added on top (the union the starter itself performs for rigid-material
    parts in ``rbody_part_modif.F90``/``rpart_grav_check`` — which never fires
    on a k2rad deck, because that check is gated on ``npby(21,·) /= 0``, true
    only for rigid bodies auto-generated from a /PART, and k2rad emits explicit
    /RBODY cards). The body accelerates correctly and exactly once: the CNRB
    main carries the summed mass of the secondaries whose own contribution is
    discarded. **Energy bookkeeping is the one thing this costs.** The
    secondaries stay in the /GRNOD/PART (they belong to deformable parts that
    must keep their own gravity), so ``gravit.F:148`` accumulates
    ``Σ m_secondary·g·v·dt`` for them *and* the same mass again through the
    main — a CNRB in scope inflates the reported EXT WORK by its own mass
    contribution without moving a single node differently. That is exactly the
    term swapping rigid PARTS out avoids, and it cannot be avoided here.

    **A deliberate asymmetry, in scoped loads.** A rigid part OUTSIDE the scope
    is NOT pulled in even when it shares nodes with a scoped deformable part:
    its main would then take the whole body's mass at ``g`` where LS-DYNA loads
    only the shared fraction. A rigid CLUSTER that straddles the scope is the
    opposite — a CNRB whose secondaries reach outside, or a
    *CONSTRAINED_RIGID_BODIES merge whose partner part is unscoped — because
    there is no way to load *part* of one rigid body: the cluster has a single
    main node and a single mass. Those get the main anyway (case (b) is also
    what the starter's own ``rpart_grav_check`` does), so the whole cluster
    accelerates at ``g`` where LS-DYNA would give ``g·m_scoped/m_cluster``. The
    load is then an upper bound and the caller warns about it.
    """
    if not rbody_info:
        return set(), []
    # Records are tagged by their builder: "part" = a whole *MAT_RIGID PART
    # (the only kind that may be swapped out of a /GRNOD/PART), "cnrb" = a
    # *CONSTRAINED_NODAL_RIGID_BODY over nodes of deformable parts. Reading the
    # tag rather than re-deriving it from state.parts[p].mid also survives the
    # rbody_info/cnrb_info merge in assembly.py, which is keyed by two id
    # namespaces at once.
    part_keyed = {p for p, info in rbody_info.items()
                  if info.get("kind", "part") == "part"}
    rigid_part_pids = {p for p in pids if p in part_keyed}
    # *CONSTRAINED_RIGID_BODIES slaves are aliased onto their master's record,
    # so several pids can share one ind_node — dedupe on the node, not the pid.
    mains: Set[int] = {rbody_info[p]["ind_node"] for p in rigid_part_pids}
    others = [info for k, info in rbody_info.items() if k not in part_keyed]
    if whole_model:
        mains.update(info["ind_node"] for info in others)
        return rigid_part_pids, sorted(mains)
    # Scoped load: report every rigid cluster the scope only partly covers, so
    # the user knows those bodies get g on their FULL mass (see the docstring).
    partial: Set[int] = set()
    cluster: Dict[int, Set[int]] = defaultdict(set)
    for p in part_keyed:
        cluster[rbody_info[p]["ind_node"]].add(p)
    for main in mains:
        if not cluster[main] <= rigid_part_pids:
            partial.add(main)
    if others:
        if pnodes is None:
            pnodes = _part_node_sets(state)
        scope_nodes: Set[int] = set()
        for p in pids:
            if p not in rigid_part_pids:
                scope_nodes |= pnodes.get(p, set())
        if scope_nodes:
            for info in others:
                if scope_nodes.intersection(info["nodes"]):
                    mains.add(info["ind_node"])
                    if not set(info["nodes"]) <= scope_nodes:
                        partial.add(info["ind_node"])
    if partial:
        shown = ", ".join(str(n) for n in sorted(partial)[:8])
        if len(partial) > 8:
            shown += ", ..."
        state.warn(
            f"{keyword or '*LOAD_*'} -> /GRAV on part(s) {sorted(pids)}: the "
            f"scope covers only PART of the rigid body/bodies whose main "
            f"node(s) are {shown} (a *CONSTRAINED_NODAL_RIGID_BODY reaching "
            "outside the scope, or a *CONSTRAINED_RIGID_BODIES merge with an "
            "unscoped partner). A rigid body has one main node and one mass, "
            "so it cannot be loaded fractionally: the WHOLE cluster is "
            "accelerated at g, where LS-DYNA applies g*m_scoped/m_cluster. The "
            "converted load is an UPPER BOUND on those bodies - scope the load "
            "to the whole cluster if that is not what you want.")
    return rigid_part_pids, sorted(mains)


def _grav_groups(state: ConversionState, part_pids: List[int],
                 main_nodes: List[int], stem: str,
                 part_kind: str = "parts") -> Tuple[List[str], int, int]:
    """Build the /GRNOD cards one /GRAV needs. Returns ``(lines, grnod_id,
    grav_id)``, where ``grnod_id`` is what the /GRAV must reference.

    Three shapes, so the common case stays exactly what it always was:

    * parts only  → one ``/GRNOD/PART`` (unchanged);
    * mains only  → one ``/GRNOD/NODE`` (every loaded part is rigid);
    * both        → ``/GRNOD/PART`` + ``/GRNOD/NODE`` + a ``/GRNOD/GRNOD``
      union, which the starter resolves by group id and de-duplicates
      (``hm_grogronod.F:179-219``).

    Id allocation order is deliberate: the part group and the /GRAV itself keep
    the ids they have always drawn, and the two extra groups are allocated
    afterwards and only when they exist. A load whose scope holds no rigid body
    therefore emits the same /GRNOD cards, with the same ids, as the pre-fix
    converter (the /GRAV card itself changes — see _emit_grav_card).

    The group ids come from ``next_grnod_id()``, not ``next_id()``: k2rad
    re-emits user *SET_NODE groups under their own SID, so a deck with a
    *SET_NODE id at or above the auto-id base would otherwise hand the starter
    two /GRNOD cards with the same id (ERROR 79, no restart file).
    """
    grnod_id = state.next_grnod_id() if part_pids else 0
    grav_id = state.next_id()
    lines: List[str] = []
    if part_pids:
        lines += _emit_grnod_part(grnod_id, f"{stem}_{part_kind}_{grav_id}",
                                  part_pids)
    if main_nodes:
        mains_id = state.next_grnod_id()
        lines += _emit_grnod_node(mains_id, f"{stem}_rbody_mains_{grav_id}",
                                  main_nodes)
        if part_pids:
            union_id = state.next_grnod_id()
            lines += _emit_grnod_grnod(union_id, f"{stem}_group_{grav_id}",
                                       [grnod_id, mains_id])
            grnod_id = union_id
        else:
            grnod_id = mains_id
    return lines, grnod_id, grav_id


def _implicit_rigid_gravity_keep(state: ConversionState) -> bool:
    """round 9, A4 (``--implicit-rigid-gravity-nodes``, default ON): on an
    IMPLICIT deck the rigid parts in a /GRAV scope STAY in its /GRNOD/PART
    beside their /RBODY main node (the main's gravity alone leaves the body
    frozen in an implicit run - measured on ex_16); explicit decks keep the
    386444e swap (rgbodv.F discards a secondary node's gravity there)."""
    return state.is_implicit and state.options.implicit_rigid_gravity_nodes


def _warn_rbody_mains_added(state: ConversionState, keyword: str,
                            mains: Set[int],
                            kept_rigid: Optional[Set[int]] = None) -> None:
    if not mains:
        return
    shown = ", ".join(str(n) for n in sorted(mains)[:8])
    if len(mains) > 8:
        shown += ", ..."
    if kept_rigid:
        kept = ", ".join(str(p) for p in sorted(kept_rigid)[:8])
        if len(kept_rigid) > 8:
            kept += ", ..."
        state.warn(
            f"{keyword} -> /GRAV on an IMPLICIT deck: the rigid part(s) "
            f"{kept} stay in the /GRNOD/PART beside their /RBODY main "
            f"node(s) ({shown}). In an implicit run the main node's gravity "
            "alone does not move the body: gravit_imp.F:84-91 weighs an "
            "active rigid body's main node with RBY(15), the main's OWN mass "
            "before the body was formed (inirby.F:836-837) - 0 on k2rad's "
            "element-free main - while the members' gravity is summed into "
            "the body. Measured on "
            "introduction/Introduction/example-16/ex_16_thin_shell_elform_13.k, "
            "the main-only group leaves the rigid disk frozen (kinetic energy "
            "-100.00 % against LS-DYNA at every fifth of t_end), this group "
            "lets it fall with LS-DYNA (KE +0.42 / +0.20 / +0.14 % at the "
            "first three fifths, nt 4 = nt 2; the 4th / 5th are the disk "
            "passing the wall: *CONTACT_2D is not converted). The implicit "
            "fall depends on the step: a free rigid disk follows -g t^2 / 2 "
            "within 0.7 % at ex_16's dtmax 1e-4 s (its velocity lags g t by "
            "one step) and falls 13-14 % short at the fifths with large "
            "automatic steps (25 cycles). Explicit decks keep the main-node "
            "group. --no-implicit-rigid-gravity-nodes restores it.")
        return
    state.warn(
        f"{keyword} -> /GRAV: the load's scope contains rigid bodies, so the "
        f"/GRNOD also lists their /RBODY main node(s) ({shown}) and rigid "
        "PARTS are represented by their main node instead of their mesh nodes. "
        "Gravity landing on a rigid secondary node is discarded by the engine "
        "(rgbodv.F overwrites A(1:3,N) from the main after GRAVIT has run), so "
        "without this the rigid body does not move at all. k2rad <= PR #88 did "
        "not do this: every gravity deck with a rigid body converts "
        "differently now.")


def _make_gravity_loads(state: ConversionState,
                        rbody_info: Optional[Dict] = None) -> List[str]:
    """*LOAD_GRAVITY_PART → /GRAV (non-modal decks).

    Magnitude: the load is ACCEL × factor(t), NOT one or the other. Manual Vol
    I R16 p.33-57 defines LC as the "Load curve defining factor as a function
    of time" and ACCEL as the "Acceleration (will be multiplied by factor from
    curve)", and Remark 1a adds "A constant factor of 1.0 is assumed if LC is
    not specified". So Fscale_Y = ACCEL in BOTH forms, and fct_IDT = LC only
    picks up the factor curve. (k2rad <= PR #88 wrote Fscale_Y = -1 whenever
    LC > 0, dropping ACCEL entirely — a factor-|ACCEL| under-load on exactly
    the ramped staged-construction decks this keyword exists for.) ACCEL is
    itself optional (its default is 0); a blank ACCEL with a curve means the
    curve carries the whole acceleration, so a factor of 1.0 is substituted
    and the substitution warned about.

    Sign: the R16/R17 manual states NO sign for ACCEL — p.33-57 defines it
    only as an acceleration, and no remark in that keyword's section fixes a
    direction — so the convention is taken from the only authority that does
    fix one, Radioss' own dyna-reader (``convertloads.cxx:859``:
    ``Fscale_Y = -lsdACCEL``). That source file is not part of this repo, but
    the behaviour is reproducible here: feeding the same ``.k`` straight to
    ``starter_win64.exe`` (which reads LS-DYNA through dyna2rad) prints

        SKEW  DIRECTION  LOAD CURVE  SENSOR    SCALE_X        SCALE_Y
           0     Y            1        0    1.000000000  -9810.000000000
        213

    for ``*LOAD_GRAVITY_PART 1 2 1 9810`` on a *MAT_RIGID part — the same
    ``Fscale_Y = -ACCEL``, the same curve, and the same main-node-only group
    this function emits.

    Parts sharing (dof, lc, accel) are grouped into one /GRAV; rigid parts in
    that group are replaced by their /RBODY main node (see
    _rbody_mains_in_scope).

    Modal decks emit NO /GRAV: gravity does not change a non-prestressed
    eigenproblem, and the stiffness-export run must stay load-consistent with
    the eigensolve.  A NOTE (not a bare "skipped") records that.
    """
    if not state.gravity_loads:
        return []
    if state.is_modal:
        state.warn(
            "NOTE: *LOAD_GRAVITY_PART is not emitted for a modal deck - "
            "gravity does not affect a non-prestressed eigenproblem, so the "
            "stiffness-export/eigen run omits /GRAV. (A non-modal conversion "
            "maps it to /GRAV.)")
        return [
            "#-  *LOAD_GRAVITY_PART: intentionally NOT converted for the modal",
            "#-  (eigenvalue) run - gravity is irrelevant to a non-prestressed",
            "#-  eigenproblem. A non-modal conversion emits /GRAV instead.",
            HDR,
        ]
    rbody_info = rbody_info or {}
    _DIR = {1: "X", 2: "Y", 3: "Z"}
    groups: Dict[Tuple[int, int, float], List[int]] = {}
    for g in state.gravity_loads:
        groups.setdefault((g.dof, g.lc, g.accel), []).append(g.pid)
        if g.lcdr:
            state.warn(f"LOAD_GRAVITY_PART pid={g.pid}: dynamic-relaxation "
                       f"curve LCDR={g.lcdr} has no OpenRadioss mapping - "
                       "ignored (only the transient gravity is converted).")
        if g.stga or g.stgr:
            state.warn(f"LOAD_GRAVITY_PART pid={g.pid}: staged-construction "
                       f"stages STGA/STGR={g.stga}/{g.stgr} are not supported "
                       "- gravity is applied for the whole run.")
    lines: List[str] = ["#-  GRAVITY LOADS (*LOAD_GRAVITY_PART):", HDR]
    added_mains: Set[int] = set()
    # round 9, A4: implicit decks keep the rigid parts in the part group
    keep = _implicit_rigid_gravity_keep(state)
    kept_rigid: Set[int] = set()
    # Built once: _rbody_mains_in_scope needs the {pid: nodes} inventory for
    # every scoped group, and rebuilding it walks every solid/shell/beam.
    pnodes = _part_node_sets(state) if rbody_info else {}
    for (dof, lc, accel), pids in sorted(groups.items()):
        if lc > 0 and lc not in state.curves:
            state.warn(f"LOAD_GRAVITY_PART: load curve {lc} not found - "
                       f"gravity on part(s) {pids} skipped.")
            continue
        pids = sorted(set(pids))
        if accel == 0.0 and lc == 0:
            # Fscale_Y = 0 does NOT mean "no gravity": hm_read_grav.F:190 does
            # IF (FCY == ZERO) FCY = FAC_FCY, silently turning it into the unit
            # -system dimension factor (1.0 in a consistent system). A zero
            # ACCEL with no curve is zero gravity, so emit nothing at all.
            state.warn(f"LOAD_GRAVITY_PART part(s) {pids}: ACCEL = 0 with no "
                       "load curve is zero gravity - no /GRAV emitted (a /GRAV "
                       "with Fscale_Y = 0 would be read back as 1.0 by the "
                       "starter, hm_read_grav.F:190).")
            continue
        rigid_pids, mains = _rbody_mains_in_scope(
            state, rbody_info, pids, whole_model=False, pnodes=pnodes,
            keyword="*LOAD_GRAVITY_PART")
        added_mains.update(mains)
        if keep:
            part_pids = list(pids)
            kept_rigid |= set(rigid_pids)
        else:
            part_pids = [p for p in pids if p not in rigid_pids]
        if not part_pids and not mains:
            continue
        glines, grnod_id, grav_id = _grav_groups(state, part_pids, mains,
                                                 "gravity")
        lines += glines
        # The load is ACCEL x factor(t) (manual p.33-57), so Fscale_Y = -ACCEL
        # in both forms and fct_IDT only selects the factor curve. ACCEL's own
        # default is 0, so a blank ACCEL alongside a curve means the curve is
        # the acceleration: substitute the factor 1.0 rather than emit a load
        # of literally zero.
        fct = lc if lc > 0 else 0
        if accel == 0.0:
            state.warn(f"LOAD_GRAVITY_PART part(s) {pids}: ACCEL is 0/blank "
                       f"with load curve {lc} - taken as ACCEL = 1.0, i.e. "
                       "curve LC carries the whole acceleration (the literal "
                       "reading, ACCEL x factor, would be zero load).")
            accel = 1.0
        lines += _emit_grav_card(
            grav_id,
            f"Gravity_{_DIR[dof]}_parts_" + "_".join(str(p) for p in pids),
            fct, _DIR[dof], grnod_id, -accel, state=state)
    _warn_rbody_mains_added(state, "*LOAD_GRAVITY_PART", added_mains,
                            kept_rigid)
    return lines if len(lines) > 2 else []


def _make_body_loads(state: ConversionState,
                     rbody_info: Optional[Dict] = None) -> List[str]:
    """*LOAD_BODY_{X,Y,Z} (+ *LOAD_BODY_PARTS scoping) → /GRAV.

    The load is a base acceleration along the named axis, and a POSITIVE card
    acts along the NEGATIVE axis. Manual Vol I R16 p.33-27/33-28: "base
    acceleration may be thought of as accelerating the coordinate system in the
    direction specified, and, thus, the inertial loads acting on the model are
    of opposite sign", and the manual's own *LOAD_BODY_Z example — SF = 0.00981
    on a constant +1.0 curve, commented "Add gravity such that it acts in the
    negative Z-direction" — is annotated "Note: Positive body load acts in the
    negative direction." So Fscale_Y = -SF, which is also what the Radioss
    dyna-reader emits (``convertloads.cxx:247``: ``Fscale_Y = -lsdSF``). That
    source file is not part of this repo, but the behaviour is reproducible
    here: read the same ``.k`` straight into ``starter_win64.exe`` and its
    GRAVITY LOADS echo gives ``SCALE_Y = -9810`` for ``SF = +9810`` and
    ``SCALE_Y = +9810`` for ``SF = -9810`` — an unconditional negation. The
    manual's *LOAD_BODY_VECTOR example is a third, independent confirmation:
    it specifies ``-1.0, -1.0, -1.0`` to obtain a body force in the POSITIVE
    (1,1,1) direction (p.33-29).

    Scope is the whole model unless a *LOAD_BODY_PARTS card names a part set
    (manual p.33-25; only one such card is permitted per deck, so the last one
    wins). Every *LOAD_BODY_* card in the deck shares that one scope, so the
    /GRNOD group is built once and all the /GRAV cards reference it.

    CID names a local system the acceleration is given in ("The accelerations
    (LCID) are with respect to CID", p.33-27) and becomes the /GRAV skew_ID.
    Rigid parts in scope are represented by their /RBODY main node; see
    _rbody_mains_in_scope.

    Modal decks emit nothing (a body load is a static preload, irrelevant to a
    non-prestressed eigenproblem).
    """
    any_body = bool(state.body_loads or state.body_load_vectors
                    or state.body_load_rots)
    if not any_body or state.is_modal:
        if state.body_load_psid and not state.is_modal:
            # Parsed, stored, and then nothing consumed it: without this the
            # conversion log says nothing at all about the card (it has a
            # handler, so it never reaches skipped_keywords either).
            state.note_recognized_not_emitted(
                "LOAD_BODY_PARTS",
                f"part set {state.body_load_psid} scopes the *LOAD_BODY_* "
                "cards, but the deck has no *LOAD_BODY_{X,Y,Z} card for it to "
                "scope - nothing emitted.")
        return []
    rbody_info = rbody_info or {}
    whole_model = True
    part_kind = "allparts"
    all_pids = sorted(state.parts)
    psid = state.body_load_psid
    if psid:
        pset = state.part_sets.get(psid)
        scoped = sorted({p for p in pset[1] if p in state.parts}) if pset else []
        if not scoped:
            state.warn(
                f"*LOAD_BODY_PARTS: part set {psid} "
                + ("is empty or names no known part"
                   if pset else "not found")
                + " - the body load is applied to the whole model instead.")
        else:
            all_pids = scoped
            whole_model = False
            part_kind = f"pset{psid}"
    if not all_pids:
        return []
    rigid_pids, mains = _rbody_mains_in_scope(state, rbody_info, all_pids,
                                              whole_model=whole_model,
                                              keyword="*LOAD_BODY_*")
    # round 9, A4: an implicit deck keeps the rigid parts in the part group
    kept_rigid: Set[int] = set()
    if _implicit_rigid_gravity_keep(state):
        part_pids = list(all_pids)
        kept_rigid = set(rigid_pids)
    else:
        part_pids = [p for p in all_pids if p not in rigid_pids]
    if not part_pids and not mains:
        return []
    lines: List[str] = ["#-  BODY LOADS (*LOAD_BODY_* -> /GRAV):", HDR]
    emitted = False
    grnod_id: Optional[int] = None
    # The scope is deck-global, so ONE group serves every *LOAD_BODY_* card of
    # every flavour. It is built on the first card that survives its checks
    # rather than before the loop, which keeps the first card's ids exactly where
    # they have always been (byte-identity for _X/_Y/_Z-only decks).
    def _first_group() -> Tuple[int, int]:
        """Build the shared /GRNOD scope; return ``(card id, grnod id)``.

        The grnod id is RETURNED as well as stored in the enclosing
        ``grnod_id``: a ``nonlocal`` write from a closure is invisible to a
        type checker, so the three call sites take the value from here."""
        nonlocal grnod_id, lines
        glines, grnod_id, load_id = _grav_groups(state, part_pids, mains,
                                                 "body_load", part_kind)
        lines += glines
        return load_id, grnod_id

    for bl in state.body_loads:
        if bl.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_{bl.dir}: load curve {bl.lcid} not found "
                       "— skipped.")
            continue
        emitted = True
        if grnod_id is None:
            grav_id, gnid = _first_group()
        else:
            grav_id, gnid = state.next_id(), grnod_id
        skew_id = 0
        if bl.cid:
            if (bl.cid in state.coord_sys or bl.cid in state.coord_nodes
                    or bl.cid in state.coord_vectors):
                skew_id = bl.cid
            else:
                state.warn(
                    f"*LOAD_BODY_{bl.dir}: local system CID={bl.cid} not found "
                    "— the base acceleration is applied along the GLOBAL "
                    f"{bl.dir} axis.")
        lines += _emit_grav_card(grav_id, f"Body_accel_{bl.dir}", bl.lcid,
                                 bl.dir, gnid, -bl.sf, skew_id, state=state)
    if emitted:
        state.warn(
            "*LOAD_BODY_{X,Y,Z} -> /GRAV with Fscale_Y = -SF: a POSITIVE LS-DYNA "
            "body load acts along the NEGATIVE axis (Manual Vol I R16 p.33-28, "
            "\"Positive body load acts in the negative direction\"), matching the "
            "Radioss dyna-reader (convertloads.cxx:247) and this converter's own "
            "*LOAD_GRAVITY_PART path. k2rad <= PR #88 wrote Fscale_Y = +SF, so a "
            "deck converted with an older version has the body-load direction "
            "REVERSED.")

    # ── *LOAD_BODY_VECTOR → /GRAV along a synthesized skew's local X' ─────────
    # The two summary warnings below are gated on EMISSION, not on the presence
    # of a parsed card: a *LOAD_BODY_VECTOR whose LCID is missing warns "load
    # curve N not found — skipped" and must not then be followed by a paragraph
    # describing the /GRAV + /SKEW/FIX pair it did not produce.
    vec_emitted = False
    for bv in state.body_load_vectors:
        if bv.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_VECTOR: load curve {bv.lcid} not found "
                       "— skipped.")
            continue
        v = bv.v
        if bv.cid:
            basis = _icid_basis(state, bv.cid)
            if basis is None:
                state.warn(
                    f"*LOAD_BODY_VECTOR: local system CID={bv.cid} not found — "
                    "V1/V2/V3 are taken as GLOBAL components. THE LOAD "
                    "DIRECTION IS WRONG unless that system is global-aligned. "
                    "(The Radioss dyna-reader is worse here: a failed lookup "
                    "leaves it building a /SKEW/FIX from two null vectors, "
                    "convertloads.cxx:607-652.)")
            else:
                # V1..V3 are components IN the CID basis: V_global = X'*V1 +
                # Y'*V2 + Z'*V3 (the same mapping convertloads.cxx:620-624 does).
                v = _local_to_global(basis, bv.v)
        axes = _ortho_skew_axes(v)
        if axes is None:                    # guarded in the handler; belt-and-braces
            state.warn("*LOAD_BODY_VECTOR: the direction vector is degenerate "
                       "after mapping through CID — skipped.")
            continue
        emitted = True
        vec_emitted = True
        if grnod_id is None:
            grav_id, gnid = _first_group()
        else:
            grav_id, gnid = state.next_id(), grnod_id
        skew_id = state.reserve_skew_id(state.next_id())
        # /SKEW/FIX's two vector cards are the local Y' and Z'; the starter
        # rebuilds X' = Y' x Z' (hm_read_skw.F:448-459), and _ortho_skew_axes
        # returns the pair for which that is exactly +V. Origin = (XC,YC,ZC),
        # which is inert for a uniform acceleration field but is where dyna2rad
        # puts it too (convertloads.cxx:668).
        lines += _emit_skew_fix(skew_id, f"SKEW_FIX_GRAV_{grav_id}",
                                (bv.xc, bv.yc, bv.zc), axes[0], axes[1])
        lines += _emit_grav_card(grav_id, "Body_accel_VECTOR", bv.lcid,
                                 "X", gnid, -bv.sf, skew_id, state=state)
    if vec_emitted:
        state.warn(
            "*LOAD_BODY_VECTOR -> ONE /GRAV with DIR=X in a companion /SKEW/FIX "
            "whose local X' is +V, and Fscale_Y = -SF. The two halves belong "
            "together: /GRAV adds +Fscale_Y*f(t) along DIR (gravit.F:147), so "
            "the applied acceleration is -SF*f(t)*V_hat, i.e. along -V — which "
            "is what LS-DYNA prescribes (Manual Vol I R16 p.33-29: the manual's "
            "own validation example writes V = (-1,-1,-1) to obtain gravity "
            "along +(1,1,1)). Reproducing only one half flips the load. |V| is "
            "irrelevant: the starter normalises the skew, and LS-DYNA uses V as "
            "a direction only.")

    # ── *LOAD_BODY_RX/_RY/_RZ → /LOAD/CENTRI (+ /FRAME/FIX for the axis) ──────
    # The section HEADER is INSERTED at the position it would have been appended
    # at, and only if a card was actually written: a deck whose R* curves are all
    # missing used to get a dangling header plus two paragraphs describing
    # /LOAD/CENTRI cards the .rad does not contain. Inserting (rather than
    # buffering the cards) keeps the header ahead of the shared /GRNOD that
    # _first_group() emits inside the loop, so a deck that DOES emit converts
    # byte-identically.
    rot_header_at = len(lines)
    rot_emitted = False
    for br in state.body_load_rots:
        if br.lcid not in state.curves:
            state.warn(f"*LOAD_BODY_R{br.dir}: angular-velocity curve "
                       f"{br.lcid} not found — skipped (fct_IDT is mandatory on "
                       "/LOAD/CENTRI: a missing function is starter ERROR 883).")
            continue
        emitted = True
        rot_emitted = True
        if grnod_id is None:
            centri_id, gnid = _first_group()
        else:
            centri_id, gnid = state.next_id(), grnod_id
        frame_id, flines = _centri_frame(state, br)
        lines += flines
        lines += _emit_centri_card(centri_id, f"Body_omega_{br.dir}", br.lcid,
                                   br.dir * 2, frame_id, gnid, br.sf)
    if rot_emitted:
        lines[rot_header_at:rot_header_at] = [
            "#-  ROTATIONAL BODY LOADS (*LOAD_BODY_R* -> /LOAD/CENTRI):", HDR]
        state.warn(
            "*LOAD_BODY_R{X,Y,Z} -> /LOAD/CENTRI with fct_IDT = LCID and "
            "Fscaley = +SF. The curve carries the ANGULAR VELOCITY omega(t), "
            "LINEARLY: LS-DYNA forms b = rho*[omega x (omega x r)] internally "
            "(Manual Vol I R16 p.33-20 Remark 3) and the OpenRadioss engine "
            "squares the curve for itself (cfield.F: VROT = Fscaley*f(t), then "
            "VROT2 = VROT*VROT, AREL = r_perp*VROT2). Do NOT pre-square or "
            "square-root it. There is NO sign flip either — unlike the "
            "translational forms, both codes apply the acceleration radially "
            "OUTWARD. Ivar = 1, so the dOmega/dt Euler term is omitted, which "
            "is what LS-DYNA does too (Remark 2: \"torsional effects due to "
            "changes in angular velocity are neglected\").")
        state.warn(
            "*LOAD_BODY_R{X,Y,Z} -> /LOAD/CENTRI Dir is written as XX/YY/ZZ, "
            "not X/Y/Z. The starter accepts both (hm_read_load_centri.F:206-211 "
            "maps X/Y/Z to IDIR 1/2/3 and XX/YY/ZZ to 4/5/6) but the engine's "
            "cfield.F:132-144 only branches on 4 and 5, so IDIR 1/2/3 all fall "
            "into the ELSE and rotate about the FRAME'S Z AXIS - silently, with "
            "no error and no warning (measured). The Radioss dyna-reader writes "
            "X/Y/Z (convertloads.cxx:271-288) and is therefore wrong for RX and "
            "RY, and right for RZ only by accident.")
    if not emitted:
        return []
    _warn_rbody_mains_added(state, "*LOAD_BODY_*", set(mains), kept_rigid)
    return lines


# ── /LOAD/CENTRI card layout ─────────────────────────────────────────────────
# centri.cfg (radioss120 FORMAT, LOADS/centri.cfg:79) is
#   CARD("%10d%10s%10d%10d%10d%10d%20lg%20lg", curveid, rad_dir, inputsystem,
#        rad_sensor_id, entityid, rad_ivar_flag, xscale, magnitude);
# — note cols 51-60 hold Ivar and are NOT blank. /GRAV's grid looks the same up
# to col 50 but has ten LITERAL blanks there (see _GRAV_GAP), so the two cards
# must NOT share a formatter: writing /GRAV's blank gap here would leave Ivar
# unset (harmless, defaults to 1) while writing Ivar into a /GRAV would be read
# as nothing at all in a field the reader skips.
_CENTRI_COMMENT = ("#funct_IDT       Dir  frame_ID sensor_ID  grnod_ID"
                   "      Ivar             Ascalex             Fscaley")


def _emit_centri_card(load_id: int, title: str, fct: int, direction: str,
                      frame_id: int, grnod_id: int, fscale: float,
                      ivar: int = 1) -> List[str]:
    """One /LOAD/CENTRI card.

    ``direction`` must be ``"XX"``, ``"YY"`` or ``"ZZ"`` (right-justified) — see
    the Dir warning in _make_body_loads. ``Ascalex`` is always 1.0: like /GRAV's
    it is an abscissa DIVISOR (``CFIELD(2,K) = ONE/FCX``), and with ``Ivar = 2``
    the engine's Euler term would additionally be off by that factor because
    ``DWDT = FAC(1,NL)*DYDX`` omits the chain-rule ``1/Ascalex``.
    """
    return [
        f"/LOAD/CENTRI/{load_id}",
        title,
        _CENTRI_COMMENT,
        f"{_i(fct)}{direction.rjust(10)}{_i(frame_id)}{_i(0)}{_i(grnod_id)}"
        f"{_i(ivar)}{_f(1.0)}{_f(fscale)}",
        HDR,
    ]


def _centri_frame(state: ConversionState, br) -> Tuple[int, List[str]]:
    """The /FRAME/FIX a *LOAD_BODY_R* rotation axis needs, as
    ``(frame_id, lines)``. ``frame_id = 0`` (global axes through the global
    origin) when the card names neither a centre nor a CID — ``XFRAME(:,1)`` is
    initialised to the identity with origin (0,0,0),
    ``hm_read_frm.F:133-135``, so no card is needed at all.

    A CID SUPERSEDES XC/YC/ZC: the frame is then the CID's own origin and axes.
    That is a CHOICE, not a documented rule — *LOAD_BODY's card says only
    "Coordinate system ID to define acceleration in local coordinate system. The
    accelerations (LCID) are with respect to CID" (Manual Vol I R16 p.33-27) and
    is SILENT on how CID interacts with the centre of rotation. It follows
    dyna2rad, whose ``_SYSTEM`` branch copies the CID skew's origin verbatim and
    ignores XC/YC/ZC (``convertloads.cxx:325-385``), and it is warned loudly
    whenever a deck supplies both. Note the sibling *LOAD_BODY_GENERALIZED
    documents the OPPOSITE for its own card — "the coordinate (XC, YC, ZC) is
    defined with respect to the local coordinate system if CID is nonzero"
    (p.33-32) — so if that reading is the intended one for *LOAD_BODY too, the
    frame origin should be ``CID_origin + R*(XC,YC,ZC)`` instead.

    Frame ids are drawn one per card from ``reserve_skew_id``: /FRAME and /SKEW
    share ONE starter table, so a collision is ERROR 79. (dyna2rad calls
    ``GetDynaMaxEntityID`` inside the loop, which returns the SAME id every time
    and gives a deck with two *LOAD_BODY_R* cards two /FRAMEs with one id.)
    """
    origin = (br.xc, br.yc, br.zc)
    yax, zax = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    if br.cid:
        basis = _icid_basis(state, br.cid)
        if basis is None:
            state.warn(
                f"*LOAD_BODY_R{br.dir}: local system CID={br.cid} not found — "
                "the rotation axis uses the GLOBAL axes"
                + (f" through ({br.xc:g}, {br.yc:g}, {br.zc:g})" if any(origin)
                   else " through the global origin")
                + ". THE AXIS IS WRONG unless that system is global-aligned. "
                "(dyna2rad silently attaches no frame at all on this path, "
                "convertloads.cxx:342, which additionally loses XC/YC/ZC.)")
        else:
            ex, ey, ez = basis
            yax, zax = ey, ez
            cs = state.coord_sys.get(br.cid)
            cid_origin = (cs.xo, cs.yo, cs.zo) if cs is not None else None
            if cid_origin is None:
                cn = state.coord_nodes.get(br.cid)
                if cn is not None:
                    from .mesh import _skew_axes_from_nodes
                    axes = _skew_axes_from_nodes(state, cn)
                    cid_origin = axes[0] if axes else None
            if cid_origin is None:
                # *DEFINE_COORDINATE_VECTOR has axes but no origin point.
                cid_origin = (0.0, 0.0, 0.0)
            if any(origin) and cid_origin != origin:
                state.warn(
                    f"*LOAD_BODY_R{br.dir}: both CID={br.cid} and a centre of "
                    f"rotation ({br.xc:g}, {br.yc:g}, {br.zc:g}) are given. "
                    f"k2rad lets CID win: the axis passes through the CID origin "
                    f"{cid_origin} and XC/YC/ZC are IGNORED, which is what "
                    "dyna2rad does (convertloads.cxx:325-385). The *LOAD_BODY "
                    "card does NOT document how the two interact (p.33-27 covers "
                    "only the acceleration direction), and the sibling "
                    "*LOAD_BODY_GENERALIZED documents the opposite for its own "
                    "card — \"the coordinate (XC, YC, ZC) is defined with respect "
                    "to the local coordinate system if CID is nonzero\" (p.33-32) "
                    "— which would put the axis through CID_origin + R*(XC,YC,ZC). "
                    "Give only one of the two if the axis position matters.")
            origin = cid_origin
    if not br.cid and not any(origin):
        return 0, []                        # frame 0 = global axes at (0,0,0)
    frame_id = state.reserve_skew_id(state.next_id())
    return frame_id, _emit_frame_fix(
        frame_id, f"FRAME_FIX_LOAD_CENTRI_{frame_id}", origin, yax, zax)


# ─────────────────────────────────────────────────────────────────────────────
# Starter: initial conditions
# ─────────────────────────────────────────────────────────────────────────────

def _emit_inivel(kind: str, inivel_id: int, title: str, grnod_id: int,
                 v: Tuple[float, float, float], skew_id: int = 0) -> List[str]:
    """One /INIVEL/TRA|ROT block — a single data card after the title:
    Vx(20) Vy(20) Vz(20) Gnod_id(10) Skew_id(10)."""
    return [
        f"/INIVEL/{kind}/{inivel_id}",
        title,
        "#                 Vx                  Vy                  Vz   Gnod_id   Skew_id",
        f"{_f(v[0])}{_f(v[1])}{_f(v[2])}{_i(grnod_id)}{_i(skew_id)}",
        HDR,
    ]


def _constant_velocity_of(v: Tuple[float, float, float]
                          ) -> Callable[[int], Tuple[float, float, float]]:
    """The per-node velocity field of a card that states ONE velocity.

    A named function rather than a lambda at each call site: the two TRA
    cards and the `_GENERATION` field all hand
    ``_warn_inivel_on_rigid_members`` the same shape, and this is the one that
    says so in the type.
    """
    def _of(_nid: int) -> Tuple[float, float, float]:
        return v
    return _of


def _emit_mass_weighted_bodies(state: ConversionState,
                               bodies: List[_MassWeightedBody],
                               tag: str) -> List[str]:
    """One ``/INIVEL/TRA`` (+ ``/INIVEL/ROT``) pair per momentum-averaged body.

    Each pair is written on a one-node ``/GRNOD`` over the body's ``/RBODY``
    MAIN node — ``hm_read_inivel.F:535-541`` writes the three components
    straight into that node's ``V``/``VR``, and ``inirby.F:1032-1048`` rebuilds
    every secondary from it as ``v_N = v_M + omega x (x_N - x_M)``.
    ``/INIVEL/ROT`` rather than ``/INIVEL/AXIS`` because ``omega`` is an
    arbitrary 3-vector here, while ``/INIVEL/AXIS`` carries one magnitude about
    a frame axis — and the manual forbids combining it with TRA/ROT on the same
    node anyway.

    The ROT block is written even when ``omega`` is all zeros: it is the cell
    that says the body has no spin, and emitting it on one body and not on
    another would make the deck depend on round-off.

    ONE pair per main node (the round-8 post-review verification). A body
    partly covered by SEVERAL velocity groups (an ``*INITIAL_VELOCITY_NODE``
    whose rows carry different velocities: ``_make_inivel`` groups them by
    value) or by several cards reaches here once per group, each time with
    that group's momentum share over the WHOLE body mass. The starter
    OVERWRITES a node's velocity card by card (``hm_read_inivel.F:524-526``
    ``V = V1..V3`` for ``/INIVEL/TRA``, ``:538-540`` ``VR`` for ``/ROT``), so
    a pair per group kept only the LAST share - the shares are linear in
    the nodal velocities, and Vol I R17 p.28-129 Remark 3 forms the body's
    momentum from ALL of them. A later share is therefore recorded in
    ``state.mass_weighted_pairs`` and written nowhere; the post-registry
    pass :func:`_merge_mass_weighted_pairs` rewrites the FIRST pair's two
    rows with the sums. A body with one share keeps its bytes.
    """
    lines: List[str] = []
    for main, v_cm, omega in bodies:
        rec = state.mass_weighted_pairs.get(main)
        if rec is not None:
            # a later share: summed into the first pair by the post-registry
            # pass, written nowhere here (no id is drawn)
            rec[3].append(v_cm)
            rec[4].append(omega)
            continue
        # the ONE record of "this body got an /INIVEL/ROT": the post-registry
        # rotary-inertia pass (_apply_mass_weighted_rbody_inertia) reads it
        state.mass_weighted_rot_mains[main] = omega
        grnod_id = state.next_grnod_id()
        lines += _emit_grnod_node(grnod_id, f"{tag}_rb_main_{main}", [main])
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVelMW_{inivel_id}",
                              grnod_id, v_cm)
        rot_id = state.next_id()
        lines += _emit_inivel("ROT", rot_id, f"InitVelMWRot_{rot_id}",
                              grnod_id, omega)
        state.mass_weighted_pairs[main] = (inivel_id, rot_id, grnod_id,
                                           [v_cm], [omega])
    return lines


#: the measured coupon of _merge_mass_weighted_pairs' sentence (the round-8
#: post-review verification's two-group cube, starter + engine at nt 4 on
#: both arms; the closed form: M 1.57e-5, L = (0, 5.8875e-3, -1.9625e-3)
#: about the CoG (7.5, 7.5, 7.5), the starter's NEW INERTIA tensor)
_MW_MERGE_MEASURED = (
    "MEASURED on a two-group coupon (a 10 mm *MAT_RIGID cube, its z = 0 "
    "nodes at vx 100 and its z = 10 nodes at vx 300, an *ELEMENT_MASS "
    "7.85e-6 on corner node 7; nt 4): cycle-0 K-ENERGY T 0.4906 = 0.5 M "
    "250^2 and K-ENERGY R 0.03084 = 0.5 omega.I.omega of the summed shares "
    "(the closed form), where one pair per group gave 0.3974 (v 225, the "
    "last group's share) and 0.06939.")


def _merge_mass_weighted_pairs(state: ConversionState,
                               lines: List[str]) -> None:
    """``--mass-weighted-inivel``: write the SUM of every momentum share of
    a body into the ONE ``/INIVEL/TRA`` + ``/INIVEL/ROT`` pair on its main
    node (the round-8 post-review verification; see
    :func:`_emit_mass_weighted_bodies` for why a pair per group was wrong).

    A POST-REGISTRY pass: the shares of one body can come from different
    writer sections (``*INITIAL_VELOCITY_NODE`` groups, ``*INITIAL_VELOCITY``
    cards, ``*INITIAL_VELOCITY_GENERATION`` cards), and the first pair is
    already in the assembled starter when a later one arrives. The two data
    rows are located by EXACT line equality on the header, the title and the
    first share's row the emitter wrote (asserted; a mismatch raises - a
    k2rad bug, never a silent skip), and only those two rows are replaced.
    Draws no id; a no-op without the flag or without a multi-share body."""
    merged = {m: r for m, r in state.mass_weighted_pairs.items()
              if len(r[3]) > 1}
    for main in sorted(merged):
        tra_id, rot_id, grnod_id, v_shares, w_shares = merged[main]
        v_sum = (math.fsum(v[0] for v in v_shares),
                 math.fsum(v[1] for v in v_shares),
                 math.fsum(v[2] for v in v_shares))
        w_sum = (math.fsum(w[0] for w in w_shares),
                 math.fsum(w[1] for w in w_shares),
                 math.fsum(w[2] for w in w_shares))
        for kind, card_id, title, first, total in (
                ("TRA", tra_id, f"InitVelMW_{tra_id}", v_shares[0], v_sum),
                ("ROT", rot_id, f"InitVelMWRot_{rot_id}", w_shares[0],
                 w_sum)):
            old = _emit_inivel(kind, card_id, title, grnod_id, first)
            new = _emit_inivel(kind, card_id, title, grnod_id, total)
            hits = [i for i, ln in enumerate(lines) if ln == old[0]]
            if len(hits) != 1 or lines[hits[0]:hits[0] + 4] != old[:4]:
                raise RuntimeError(
                    f"--mass-weighted-inivel: /INIVEL/{kind}/{card_id} is "
                    "not the block its emitter recorded (found "
                    f"{len(hits)} header line(s)); refusing to rewrite a "
                    "velocity row blind. This is a k2rad bug.")
            lines[hits[0] + 3] = new[3]
        state.mass_weighted_rot_mains[main] = w_sum
        state.warn(
            f"--mass-weighted-inivel: the rigid body on main node {main} is "
            f"partly covered by {len(v_shares)} velocity groups / cards; "
            "their momentum shares (each over the whole body mass) are "
            f"SUMMED into ONE pair, /INIVEL/TRA/{tra_id} v_cm = ("
            + ", ".join(f"{c:.6g}" for c in v_sum)
            + f") and /INIVEL/ROT/{rot_id} omega = ("
            + ", ".join(f"{c:.6g}" for c in w_sum)
            + ") - the starter OVERWRITES a node's velocity card by card "
            "(hm_read_inivel.F:524-526 / :538-540), so the pair per group "
            "written before kept only the LAST group's share, where Vol I "
            "R17 p.28-129 Remark 3 forms the body's momentum from ALL its "
            "nodal velocities. " + _MW_MERGE_MEASURED)


def _apply_mass_weighted_rbody_inertia(state: ConversionState,
                                       lines: List[str],
                                       rbody_info: Dict) -> None:
    """``--mass-weighted-inivel``: ``J = J_old - SUM(IN)`` on every ``/RBODY``
    the re-point wrote an ``/INIVEL/ROT`` on (round 6, A7).

    WHY. The starter assembles a body's inertia tensor in ``inirby.F``: for
    ICoG 1/2/3 (``:322``) it adds every secondary's ``m r^2`` AND its nodal
    rotary inertia ``IN`` (``:355``), plus the main node's ``IN``
    (``:166-168``), plus the ``/RBODY`` ``J`` cells, which are ADDITIVE
    (``:154-160``); the tensor is printed as ``NEW INERTIA`` (``:708/:712``).
    LS-DYNA's rigid-body inertia is the point-mass sum - MEASURED: the
    reference d3hsp tensor equals it (revo-stiff 0.1977E-02, the point-mass
    value, where Theory R16 eq. 29.23's density integral J_rho gives 6.66e-4)
    - so the lumped shell ``IN`` is a residual the momentum
    average hands straight to the spin. ``J = -SUM(IN)`` over the SAME nodes
    ``inirby.F`` adds ``IN`` for (the body's secondaries and its main node;
    ``k2rad.lumping.nodal_masses_from_state``'s ``IN``, shells only) takes it
    back out. On translat the starter then prints ``NEW INERTIA
    0.1977227E-02 / 0.3954455E-02`` = LS-DYNA's 0.1977E-02 / 0.3954E-02.

    WHICH BODIES. Exactly the ones ``_emit_mass_weighted_bodies`` recorded in
    ``state.mass_weighted_rot_mains`` — the one decision site; a body the
    card fully covers gets no ``/INIVEL/ROT`` and keeps its J. SINCE ROUND 7
    the ``*MAT_RIGID`` producer writes ``J = -SUM(IN)`` on every part body BY
    DEFAULT (A2, ``rbody._rigid_shell_in_correction``), so this pass adds it
    only where the producer did not: guard (2) skips a body whose record says
    ``j_in`` "applied" or "refused" (never subtract twice), and guard (1)
    never writes J on a ``*CONSTRAINED_NODAL_RIGID_BODY``. With
    ``--no-rigid-shell-rotary-inertia`` it behaves exactly as in round 6.

    SKIPPED by name: ICoG 4 (``inirby.F:322`` adds no nodal ``IN``; the J is
    the deck's ``*PART_INERTIA`` tensor) and any body whose shells the lumper
    does not reproduce (``_rbody_in_skip_reason``). REFUSED by name: the
    corrected tensor's smallest principal value not above
    ``rbody.RIGID_IN_MARGIN`` (1e-3) x its largest - the A2 producer's
    margin, the starter's own default-path threshold (WARNING 275 raises
    such a value by 0.1 x the largest, ``inirby.F:753-758``; ERROR 274 is
    ``<= 0``, ``inirby.F:823``; this pass refused at ``<= 0`` until the
    round-7 validation round).

    HOW. A POST-REGISTRY pass: every ``/RBODY`` block is built before the
    inivel sections decide the re-point, and the decision needs
    ``rbody_info``, so no pre-pass could make it without a second copy of the
    inivel card-group resolution. The block is located by EXACT line
    equality on ``/RBODY/<main>`` (the ``/RBODY`` id IS its main node, unique
    in ``state.rbody_ids``), the ``Jxx Jyy Jzz`` header and row the producer
    wrote are ASSERTED against ``rbody_info[..]["j"]``, and only that one row
    is replaced. A failed assertion raises: a k2rad bug, never a silent skip.
    """
    mains = state.mass_weighted_rot_mains
    if not mains or not state.options.mass_weighted_inivel:
        return
    from ..lumping import _sym3_eigen, nodal_masses_from_state
    from .rbody import RIGID_IN_MARGIN, _inertia_lines
    mass_by_node, in_by_node = nodal_masses_from_state(state)
    for main in sorted(mains):
        rec = next((info for info in rbody_info.values()
                    if info.get("ind_node") == main), None)
        if rec is None or "j" not in rec:
            continue
        # guard (1), round 7: never on a *CONSTRAINED_NODAL_RIGID_BODY. LS-DYNA
        # KEEPS the nodal rotary inertia in a nodal rigid body - MEASURED on
        # implicit/basic-examples/basics-iii/rigid_tip.k CNRB 99: LS reads
        # point mass + 1.373e-4 on every axis, and the subtraction would take
        # it from -7.36 % to -25.08 %.
        if rec.get("kind") == "cnrb":
            state.warn(
                f"--mass-weighted-inivel: /RBODY/{main} keeps its J - it is a "
                "*CONSTRAINED_NODAL_RIGID_BODY: LS-DYNA keeps the nodal rotary "
                "inertia in a nodal rigid body (rigid_tip CNRB 99: LS = point "
                "mass + 1.373e-4 on every axis); J = -SUM(IN) would take it "
                "from -7.36 % to -25.08 %.")
            continue
        # guard (2), round 7: the *MAT_RIGID producer already wrote J =
        # -SUM(IN) on this body by default (A2), or refused it on the same
        # relative margin - subtracting here again would write -2 SUM(IN). A
        # body the producer SKIPPED reaches the skip check below (the same
        # function) and is named there again; with
        # --no-rigid-shell-rotary-inertia every record carries j_in "" and
        # this pass behaves exactly as in round 6.
        if rec.get("j_in") in ("applied", "refused"):
            continue
        nodes = set(rec["nodes"]) | {main}
        icog = int(rec.get("icog", 0) or 0)
        if icog == 4:
            state.warn(
                f"--mass-weighted-inivel: /RBODY/{main} keeps its J - ICoG 4: "
                "its J is the deck's *PART_INERTIA tensor and inirby.F:322 "
                "adds no nodal IN to it.")
            continue
        why = _rbody_in_skip_reason(state, nodes)
        if why:
            state.warn(
                f"--mass-weighted-inivel: /RBODY/{main} keeps its J - {why}, "
                "so -SUM(IN) would take out the wrong amount. Its spin carries "
                "the lumped rotary-inertia residual.")
            continue
        shell_nodes = sorted(n for n in nodes if in_by_node.get(n, 0.0) > 0.0)
        sum_in = math.fsum(in_by_node.get(n, 0.0) for n in shell_nodes)
        if sum_in <= 0.0:
            continue                      # no shell IN on this body at all
        j_old = tuple(rec["j"])
        j_new = (j_old[0] - sum_in, j_old[1] - sum_in, j_old[2] - sum_in,
                 j_old[3], j_old[4], j_old[5])
        # what inirby.F assembles, about the lumped centre of mass
        pts = [(state.nodes[n].x, state.nodes[n].y, state.nodes[n].z,
                mass_by_node.get(n, 0.0)) for n in sorted(nodes)
               if n in state.nodes]
        m_tot = math.fsum(p[3] for p in pts)
        if m_tot > 0.0:
            cx = math.fsum(p[0] * p[3] for p in pts) / m_tot
            cy = math.fsum(p[1] * p[3] for p in pts) / m_tot
            cz = math.fsum(p[2] * p[3] for p in pts) / m_tot
        else:
            cx = cy = cz = 0.0
        t = [[0.0] * 3 for _ in range(3)]
        for x, y, z, m in pts:
            d = (x - cx, y - cy, z - cz)
            r2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
            for a in range(3):
                for b in range(3):
                    t[a][b] += m * ((r2 if a == b else 0.0) - d[a] * d[b])
        for a in range(3):
            t[a][a] += sum_in + j_new[a]
        t[0][1] += j_new[3]
        t[1][0] += j_new[3]
        t[1][2] += j_new[4]
        t[2][1] += j_new[4]
        t[0][2] += j_new[5]
        t[2][0] += j_new[5]
        evs = _sym3_eigen(t)[0]
        low, high = min(evs), max(evs)
        # the A2 producer's margin, the starter's own default-path threshold
        # (round-7 validation round: WARNING 275 raises a principal value at
        # or below 1e-3 x the largest long before ERROR 274's <= 0)
        if not (high > 0.0 and low > RIGID_IN_MARGIN * high):
            state.warn(
                f"--mass-weighted-inivel: /RBODY/{main} keeps its J - with "
                f"J = {j_new[0]:g} the body tensor's smallest principal value "
                f"{low:g} would not exceed {RIGID_IN_MARGIN:g} x the largest "
                f"{high:g} (starter WARNING 275 raises it by 0.1 x the "
                "largest, inirby.F:753-758; ERROR 274 at <= 0, "
                "inirby.F:823).")
            continue
        hits = [i for i, ln in enumerate(lines) if ln == f"/RBODY/{main}"]
        old = _inertia_lines(j_old)
        if (len(hits) != 1 or len(lines) <= hits[0] + 5
                or lines[hits[0] + 4] != old[0]
                or lines[hits[0] + 5] != old[1]):
            raise RuntimeError(
                f"--mass-weighted-inivel: the /RBODY/{main} block is not the "
                "shape its producer recorded (found "
                f"{len(hits)} header line(s)); refusing to rewrite a J row "
                "blind. This is a k2rad bug.")
        lines[hits[0] + 5] = _inertia_lines(j_new)[1]
        state.warn(
            f"--mass-weighted-inivel also wrote J = {j_new[0]:g} (= -SUM of "
            f"the nodal rotary inertia IN of the body's {len(shell_nodes)} "
            f"shell node(s)) into /RBODY/{main}: the starter ADDS every "
            "member's IN to the body tensor for ICoG 1/2/3 (inirby.F:166-168, "
            ":322, :355), while LS-DYNA's rigid-body inertia is the "
            "point-mass sum (measured on the reference d3hsp tensors), so the J cells "
            "take the difference back out. MEASURED on "
            "intro-by-j.-day/joint/joint-ii/translat.k (nt 4): NEW INERTIA "
            "0.2642894E-02 -> 0.1977227E-02 = LS-DYNA's 0.1977E-02; cycle-0 "
            "KE 220.58 -> 189.96 (LS 189.962); final KE 139.89 -> 92.77 (LS "
            "94.6381, -1.97 % - an END value: the KE history at the fifths of "
            "the run reads -7.1 / -5.3 / +2.8 / +26.3 / -2.0 % against "
            "-13.9 / +22.6 / +2.8 / +39.2 / +47.8 % without the J cells, "
            "RMS 17.5 -> 11.6 % of the LS peak); 1.156x the cycles (the "
            "body's main node owns "
            "the step and its rotational step shrinks with J). The IE is NOT "
            "fixed by it (1159 -> 1436 against LS-DYNA's 0.1026; the engine "
            "energy error is 99.9 % from cycle 1 on every arm - the joint "
            "path).")


def _make_inivel(state: ConversionState, rbody_info: Dict,
                 rigid_nodes: Optional[Set[int]] = None) -> List[str]:
    """Initial velocities → /INIVEL/TRA (+ /INIVEL/ROT for rotational DOFs).

    The only valid /INIVEL subtypes are TRA/ROT (cfg inivel.cfg); rotational
    components need their own /INIVEL/ROT block. For rigid bodies the velocity
    goes on the MASTER node only — its 6 DOFs drive the body, and secondary-
    node values are overridden by /RBODY kinematics anyway.
    """
    lines: List[str] = []

    vel_groups: Dict[Tuple, List[int]] = defaultdict(list)
    for iv in state.inivel_nodes:
        vel_groups[(iv.vx, iv.vy, iv.vz, iv.vxr, iv.vyr, iv.vzr)].append(iv.nid)

    for vel_key, nids in vel_groups.items():
        vx, vy, vz, vxr, vyr, vzr = vel_key
        nids, mw_bodies = _warn_inivel_on_rigid_members(
            state, 0, sorted(nids), rigid_nodes,
            keyword="*INITIAL_VELOCITY_NODE",
            rbody_info=rbody_info, repoint=True,
            velocity_of=_constant_velocity_of((vx, vy, vz)),
            mass_weighted_block=("the card also states NODAL ROTATIONAL velocities "
                     "(VXR/VYR/VZR), and this rule forms the body's angular "
                     "momentum from the TRANSLATIONAL velocities alone - "
                     "folding a prescribed nodal spin into it needs each "
                     "node's own rotary inertia, which the momentum average "
                     "does not use"
                                 if (vxr or vyr or vzr) else ""))
        lines += _emit_mass_weighted_bodies(state, mw_bodies, "inivel_nodes")
        if not nids:
            continue
        grnod_id = state.next_grnod_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_nodes_{grnod_id}", sorted(nids))
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVel_{inivel_id}",
                              grnod_id, (vx, vy, vz))
        if vxr or vyr or vzr:
            rot_id = state.next_id()
            lines += _emit_inivel("ROT", rot_id, f"InitVelRot_{rot_id}",
                                  grnod_id, (vxr, vyr, vzr))

    for iv in state.inivel_rbodies:
        info = rbody_info.get(iv.pid)
        if not info:
            state.warn(f"INITIAL_VELOCITY_RIGID_BODY pid={iv.pid}: no RBODY found – skipped")
            continue
        grnod_id = info["ind_grnod_id"]
        inivel_id = state.next_id()
        lines += _emit_inivel("TRA", inivel_id, f"InitVelRB_{inivel_id}",
                              grnod_id, (iv.vx, iv.vy, iv.vz))
        if iv.vxr or iv.vyr or iv.vzr:
            rot_id = state.next_id()
            lines += _emit_inivel("ROT", rot_id, f"InitVelRBRot_{rot_id}",
                                  grnod_id, (iv.vxr, iv.vyr, iv.vzr))

    lines += _make_inertia_inivel(state, rbody_info)

    if lines:
        lines = ["#-  INITIAL CONDITIONS:", HDR] + lines
    return lines


def _make_inertia_inivel(state: ConversionState, rbody_info: Dict) -> List[str]:
    """`_INERTIA` card 5 ``VTX..VRZ`` → /INIVEL/TRA + /INIVEL/ROT on the main node.

    **Why the main node alone is exact.** /INIVEL/ROT has no axis and no origin: it
    writes its three components straight into the nodal rotational-velocity vector
    (``hm_read_inivel.F:535-541``: ``VR(1,NOSYS)=V1`` ... for every node of the
    group), and ``inirby.F`` then propagates the main node's ``V``/``VR`` to the
    secondaries as a rigid field about the main node's position,
    ``V(:,N) = V(:,M) + omega x (X_N - X_M)``. With ICoG=4 that position IS the
    centre of mass the card states, so putting ``VTX..VTZ`` and ``VRX..VRZ`` on a
    group containing only the main node reproduces "translational/rotational
    velocity about the centre of mass" with no correction term — a pure
    translation and a pure omega are both position-independent, which is why
    /INIVEL/AXIS (the only variant that carries an origin, via a /FRAME) is not
    needed and must not be used ("This option cannot be used when /INIVEL/TRA or
    /INIVEL/ROT is applied on the same node").

    ``IRODDL > 0`` is required for the ``VR`` write to happen at all, and
    ``contrl.F:1053`` includes ``NRBODY`` in that MIN(), so any /RBODY in the deck
    guarantees it — always true here.

    **Double-application guard.** *PART Remark 5: "The *INITIAL_VELOCITY card may
    overwrite the initial velocity of the rigid body." Radioss /INIVEL ASSIGNS
    (``V(1,NOSYS) = V1``) rather than accumulating, so two cards on the same node
    are not additive — the LAST one read wins. An
    `*INITIAL_VELOCITY_RIGID_BODY` on the same body therefore makes the card-5
    values dead weight, and they are dropped here with a warning instead of being
    written to be silently overwritten. The whole-model and generated forms are
    warned but kept: they are emitted by LATER sections
    (``_make_initial_velocity`` / ``_make_initial_velocity_generation``), so
    Radioss reads them after these cards and LS-DYNA's precedence falls out of the
    section order by itself.
    """
    if not state.part_inertias and not any(c.inertia for c in state.cnrbs):
        return []
    # Bodies an *INITIAL_VELOCITY_RIGID_BODY already drives, by part id.
    iv_rb_pids = {iv.pid for iv in state.inivel_rbodies}
    # A whole-model *INITIAL_VELOCITY (NSID blank/0 → "whole model", which by then
    # includes the synthesized main node) or an *INITIAL_VELOCITY_GENERATION with
    # STYP=0 covers every node, main nodes included.
    global_iv = ([f"*INITIAL_VELOCITY with NSID={iv.nsid or 0}"
                  for iv in state.inivel_general
                  if not iv.nsid and (iv.vx or iv.vy or iv.vz
                                      or iv.vxr or iv.vyr or iv.vzr)]
                 + [f"*INITIAL_VELOCITY_GENERATION with STYP={g.styp}"
                    for g in state.inivel_generations if not g.styp])

    todo: List[Tuple[int, str, RigidInertia, int]] = [
        (pid, f"*PART_INERTIA {pid}", inr, pid)
        for pid, inr in sorted(state.part_inertias.items())]
    # round 9, A1: a CNRB that gave way to the rigid part of its PID is filed
    # under its shadow key - its own card-5 velocity stays on the CNRB main
    todo += [(c.pid, f"*CONSTRAINED_NODAL_RIGID_BODY_INERTIA pid={c.pid}",
              c.inertia, state.cnrb_record_key.get(c.pid, c.pid))
             for c in state.cnrbs if c.inertia is not None]

    lines: List[str] = []
    for pid, label, inr, key in todo:
        if not inr.has_velocity():
            continue
        info = rbody_info.get(key)
        if not info:
            state.warn(
                f"{label}: the card-5 initial velocity "
                f"(VT={inr.vtx:g},{inr.vty:g},{inr.vtz:g} "
                f"VR={inr.vrx:g},{inr.vry:g},{inr.vrz:g}) is DROPPED — no /RBODY "
                "was emitted for that id, so there is no main node to put it on.")
            continue
        if pid in iv_rb_pids and key == pid:
            state.warn(
                f"{label}: the card-5 initial velocity is DROPPED because "
                f"*INITIAL_VELOCITY_RIGID_BODY also drives part {pid}. *PART "
                "Remark 5 gives *INITIAL_VELOCITY precedence ('may overwrite the "
                "initial velocity of the rigid body'), and Radioss /INIVEL "
                "ASSIGNS rather than accumulates, so emitting both would leave "
                "the result decided by card order. Remove one of the two cards.")
            continue
        if global_iv:
            state.warn(
                f"{label}: the card-5 initial velocity is applied to /RBODY main "
                f"node {info['ind_node']}, but {global_iv[0]} covers every node "
                "in the model including that one. Radioss /INIVEL assigns rather "
                "than accumulates and the whole-model card is written LATER in "
                "the deck, so it WINS — which is LS-DYNA's own precedence (*PART "
                "Remark 5), but scope the whole-model card if that is not what "
                "was meant.")
        grnod_id = info["ind_grnod_id"]
        if inr.vtx or inr.vty or inr.vtz:
            tid = state.next_id()
            lines += _emit_inivel("TRA", tid, f"InitVelInertia_{tid}", grnod_id,
                                  (inr.vtx, inr.vty, inr.vtz))
        if inr.vrx or inr.vry or inr.vrz:
            rid = state.next_id()
            lines += _emit_inivel("ROT", rid, f"InitVelInertiaRot_{rid}", grnod_id,
                                  (inr.vrx, inr.vry, inr.vrz))
    return lines


def _vdot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _icid_basis(state: ConversionState, cid: int):
    """Global-frame orthonormal basis (ex, ey, ez) of the converted /SKEW whose id
    is *cid* — the local axes of the *DEFINE_COORDINATE_* system, built exactly as
    _make_skews emits them. Returns None when cid has no converted skew (the
    velocity/axis then stay global). Pre-rotating with this basis reproduces what
    Radioss would do if the components carried a Skew_id (as the plain
    *INITIAL_VELOCITY path does)."""
    cs = state.coord_sys.get(cid)
    if cs is not None:
        origin = (cs.xo, cs.yo, cs.zo)
        ex = _vnorm(_vsub((cs.xl, cs.yl, cs.zl), origin))
        if ex is None:
            return None
        ez = _vnorm(_vcross(ex, _vsub((cs.xp, cs.yp, cs.zp), origin)))
        if ez is None:
            return None
        return ex, _vcross(ez, ex), ez
    cn = state.coord_nodes.get(cid)
    if cn is not None:
        from .mesh import _skew_axes_from_nodes
        axes = _skew_axes_from_nodes(state, cn)
        if axes is None:
            return None
        _origin, xax, yax = axes
        return xax, yax, _vcross(xax, yax)
    cv = state.coord_vectors.get(cid)
    if cv is not None:
        # Same basis _emit_coord_vector_skew builds: ex = X̂, ez = X × V, ey = ez × ex.
        ex = _vnorm((cv.xx, cv.yx, cv.zx))
        if ex is None:
            return None
        ez = _vnorm(_vcross((cv.xx, cv.yx, cv.zx), (cv.xv, cv.yv, cv.zv)))
        if ez is None:
            return None
        return ex, _vcross(ez, ex), ez
    return None


def _local_to_global(basis, v):
    """Express a vector whose components *v* are given in the local *basis*
    (columns ex, ey, ez, in global coords) back in global coords:
    g = v0·ex + v1·ey + v2·ez."""
    ex, ey, ez = basis
    return (v[0] * ex[0] + v[1] * ey[0] + v[2] * ez[0],
            v[0] * ex[1] + v[1] * ey[1] + v[2] * ez[1],
            v[0] * ex[2] + v[1] * ey[2] + v[2] * ez[2])


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_BOX membership (numeric node scoping — no /BOX entity emitted)
# ─────────────────────────────────────────────────────────────────────────────

def _box_basis(box):
    """Orthonormal (origin, ex, ey, ez) of a _LOCAL box's frame, built exactly
    as dyna2rad does (convertboxes.cxx): ex = X̂, ez = normalize(X × V), ey =
    ez × ex. Returns None when the X vector is zero or X∥V (a degenerate frame
    with no interior)."""
    ex = _vnorm((box.xx, box.yx, box.zx))
    if ex is None:
        return None
    ez = _vnorm(_vcross((box.xx, box.yx, box.zx), (box.xv, box.yv, box.zv)))
    if ez is None:
        return None
    ey = _vcross(ez, ex)                          # unit (ez ⟂ ex, both unit)
    return (box.cx, box.cy, box.cz), ex, ey, ez


def _box_global_corners(box):
    """Global diagonal corner points (P1, P2) of a box. Plain: the global
    min/max corners. _LOCAL: the local min/max extents baked through the box
    frame (P1 = origin + xmn·ex + ymn·ey + zmn·ez), matching dyna2rad's
    rotateVector corner bake. Returns None for a degenerate _LOCAL frame."""
    lo = (min(box.xmn, box.xmx), min(box.ymn, box.ymx), min(box.zmn, box.zmx))
    hi = (max(box.xmn, box.xmx), max(box.ymn, box.ymx), max(box.zmn, box.zmx))
    if not box.local:
        return lo, hi
    basis = _box_basis(box)
    if basis is None:
        return None
    origin, ex, ey, ez = basis
    p1 = _local_to_global((ex, ey, ez), lo)
    p2 = _local_to_global((ex, ey, ez), hi)
    p1 = (p1[0] + origin[0], p1[1] + origin[1], p1[2] + origin[2])
    p2 = (p2[0] + origin[0], p2[1] + origin[1], p2[2] + origin[2])
    return p1, p2


def _box_contains(box, x: float, y: float, z: float) -> bool:
    """True if the global point (x,y,z) lies in the box. A _LOCAL box tests the
    point's coordinates in the box frame; a plain box tests global coordinates
    against its axis-aligned extents (min/max taken per axis, so P1/P2 may be
    given in either diagonal order)."""
    lox, hix = min(box.xmn, box.xmx), max(box.xmn, box.xmx)
    loy, hiy = min(box.ymn, box.ymx), max(box.ymn, box.ymx)
    loz, hiz = min(box.zmn, box.zmx), max(box.zmn, box.zmx)
    if box.local:
        basis = _box_basis(box)
        if basis is None:
            return False
        origin, ex, ey, ez = basis
        d = (x - origin[0], y - origin[1], z - origin[2])
        u, v, w = _vdot(d, ex), _vdot(d, ey), _vdot(d, ez)
    else:
        u, v, w = x, y, z
    return lox <= u <= hix and loy <= v <= hiy and loz <= w <= hiz


def _box_node_ids(state: ConversionState, box) -> Set[int]:
    """Set of node ids whose coordinates fall inside *box* (O(nodes) scan — the
    same cost class as the existing NSIDEX set-difference; there is no spatial
    index in the codebase). The _LOCAL frame is computed once.

    Only the SOURCE deck's nodes are candidates. By write time ``state.nodes``
    also holds everything the writer synthesized — /RBODY CoG masters, /SKEW/MOV
    third nodes, the *BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL triads, rigid-wall
    carriers, *ELEMENT_BEAM_ORIENTATION third nodes — and a *DEFINE_BOX names a
    region of the USER's model, so those artefacts must not be picked up.
    Measured: a box-only ``*BOUNDARY_PRESCRIBED_MOTION_SET_BOX`` round a rigid
    brick emitted an /IMPVEL on the brick's synthesized /RBODY MASTER node, i.e.
    drove the whole body (starter WARNING 312, 0 errors, restart written — the
    wrong model runs), and the ``if not box_nodes`` guard cannot see it because
    the box does contain nodes, just the wrong ones. ``source_node_ids`` is empty
    only when build_starter has not run (direct unit-test calls), in which case
    every node is a candidate as before.
    """
    lox, hix = min(box.xmn, box.xmx), max(box.xmn, box.xmx)
    loy, hiy = min(box.ymn, box.ymx), max(box.ymn, box.ymx)
    loz, hiz = min(box.zmn, box.zmx), max(box.zmn, box.zmx)
    src = state.source_node_ids
    cands = ((nid, nd) for nid, nd in state.nodes.items()
             if not src or nid in src)
    if box.local:
        basis = _box_basis(box)
        if basis is None:
            return set()
        origin, ex, ey, ez = basis
        out: Set[int] = set()
        for nid, nd in cands:
            d = (nd.x - origin[0], nd.y - origin[1], nd.z - origin[2])
            u, v, w = _vdot(d, ex), _vdot(d, ey), _vdot(d, ez)
            if lox <= u <= hix and loy <= v <= hiy and loz <= w <= hiz:
                out.add(nid)
        return out
    return {nid for nid, nd in cands
            if lox <= nd.x <= hix and loy <= nd.y <= hiy and loz <= nd.z <= hiz}


def _resolve_box_nodes(state: ConversionState, box_id: int, label: str):
    """Node ids inside *DEFINE_BOX ``box_id`` (a set), or None (with a warning)
    when the box is undefined or has a degenerate local frame — the caller then
    applies the load/wall to the full node group instead."""
    box = state.boxes.get(box_id)
    if box is None:
        state.warn(f"{label}: no *DEFINE_BOX {box_id} in the deck — box scoping "
                   "ignored (applied to the full node group).")
        return None
    if box.local and _box_basis(box) is None:
        state.warn(f"{label}: *DEFINE_BOX_LOCAL {box_id} has a degenerate local "
                   "frame (zero or parallel defining vectors) — box scoping "
                   "ignored.")
        return None
    return _box_node_ids(state, box)


def _emit_frame_fix(frame_id: int, title: str, origin, yaxis, zaxis) -> List[str]:
    """Emit /FRAME/FIX — same card layout and Y'/Z' rule as /SKEW/FIX: the two
    vector cards are the LOCAL Y' and Z' axes (globalyaxis / globalzaxis). The
    starter rebuilds X' = Y' x Z' then re-orthogonalises Y'' = Z' x X', so the
    Z' card (card 3) is the exactly-preserved local Z; the Y' card only needs to
    be non-parallel to Z'."""
    return [
        f"/FRAME/FIX/{frame_id}",
        title,
        "#                 Ox                  Oy                  Oz",
        f"{_f(origin[0])}{_f(origin[1])}{_f(origin[2])}",
        "#                 X1                  Y1                  Z1   (local Y axis)",
        f"{_f(yaxis[0])}{_f(yaxis[1])}{_f(yaxis[2])}",
        "#                 X2                  Y2                  Z2   (local Z axis)",
        f"{_f(zaxis[0])}{_f(zaxis[1])}{_f(zaxis[2])}",
        HDR,
    ]


def _emit_inivel_axis(inivel_id: int, title: str, frame_id: int, grnod_id: int,
                      v: Tuple[float, float, float], vr: float,
                      dir_axis: str = "Z") -> List[str]:
    """One /INIVEL/AXIS block: card A = DIR(10s) FRAME_id(10) GRNOD_id(10);
    card B = Vxt(20) Vyt(20) Vzt(20) VR(20). Vxt/Vyt/Vzt are the translational
    velocity expressed in the FRAME's local axes; VR is the angular velocity
    about the DIR axis (here the frame's local Z)."""
    return [
        f"/INIVEL/AXIS/{inivel_id}",
        title,
        "#      DIR  FRAME_id  GRNOD_id",
        f"{dir_axis.rjust(10)}{_i(frame_id)}{_i(grnod_id)}",
        "#                Vxt                 Vyt                 Vzt                  VR",
        f"{_f(v[0])}{_f(v[1])}{_f(v[2])}{_f(vr)}",
        HDR,
    ]


def _rbody_main_of(rbody_info: Optional[Dict]) -> Dict[int, int]:
    """member node -> its /RBODY main node, the map ``_make_bcs`` builds inline.

    One helper so the ``*BOUNDARY_SPC`` re-point (``_make_bcs``), the
    ``*NODE`` TC/RC re-point and the ``/INIVEL`` re-point cannot drift apart:
    all three answer the same question — *which node carries this body's six
    degrees of freedom?*
    """
    out: Dict[int, int] = {}
    for info in (rbody_info or {}).values():
        ind = info["ind_node"]
        for node in info["nodes"]:
            out[node] = ind
    return out


def _rbody_coverage_exempt(state: ConversionState) -> Set[int]:
    """Nodes that must not count against a rigid body's /INIVEL COVERAGE.

    A body is "fully covered" by an initial-velocity card when the card names
    every node of it that LS-DYNA would have initialised. Two kinds of member
    node are in k2rad's ``rbody_info[...]["nodes"]`` and in NO LS-DYNA node
    group:

    * ``*CONSTRAINED_EXTRA_NODES_NODE/_SET`` nodes. Vol I R17 p.28-127, the
      ``ID`` field of ``*INITIAL_VELOCITY_GENERATION``: *"WARNING for if
      IVATN = 0: If a part ID of a rigid body is specified, only the nodes
      that belong to elements of the rigid body are initialized. Nodes added
      with \\*CONSTRAINED_EXTRA_NODES are not initialized."* So LS-DYNA does
      not count them either.
    * the helper nodes ``_synthesize_local_motion_frames`` invents to carry a
      ``*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL`` triad — k2rad's own, absent
      from the source deck.

    (The synthesized element-free CoG master is already outside ``["nodes"]``:
    ``writer/rbody`` keeps it in ``ind_node`` only.) Without this exemption
    ``brake.k`` — whose IVG names the part's 144 element nodes while its
    /RBODY carries 146 — reads as PARTLY covered and keeps a card that moves
    nothing.
    """
    exempt: Set[int] = set()
    for extra in state.extra_rigid_nodes.values():
        exempt.update(extra)
    for helpers in state.local_frame_nodes.values():
        exempt.update(helpers)
    return exempt


#: One partly-covered rigid body the momentum average was formed for:
#: ``(main node, v_cm, omega)``. ``_make_inivel`` and its two siblings write
#: one /INIVEL/TRA + /INIVEL/ROT pair per entry on that main node.
_MassWeightedBody = Tuple[int, Tuple[float, float, float],
                          Tuple[float, float, float]]


def _lumped_nodal_masses(state: ConversionState) -> Tuple[Dict[int, float],
                                                          float]:
    """``(mass by node, the model's total lumped mass)``, computed once.

    The rule is ``k2rad.lumping.nodal_masses_from_state`` — the same one
    ``tools/modal_solve`` pairs with the engine's exported stiffness matrix,
    which reproduces the starter's own MS array. Imported INSIDE the function:
    ``k2rad.lumping`` imports ``writer.beams`` and ``writer.materials``, and a
    module-level import here would put the writer package in a cycle with
    itself.

    The lumper walks every element, so the result is memoised ON the state
    (``state.lumped_nodal_masses_memo``): one pass per conversion, since
    nothing between the /INIVEL writers changes the mesh. It used to live
    in a module dict keyed by ``id(state)`` that was never cleared - CPython
    reuses the id of a freed state, so a later conversion in the same
    process (the GUI, the test suite, a script calling ``convert()`` in a
    loop) could read an EARLIER model's masses: measured, 53 of 150
    alternating conversions of two element-mass variants wrote the other
    deck's /INIVEL/TRA.
    """
    got = state.lumped_nodal_masses_memo
    if got is None:
        from ..lumping import nodal_masses_from_state
        mass, _inertia = nodal_masses_from_state(state)
        got = (mass, math.fsum(mass.values()))
        state.lumped_nodal_masses_memo = got
    return got


def _momentum_average_body(state: ConversionState, info: Optional[Dict],
                           main: int, group: Set[int],
                           velocity_of: Callable[
                               [int], Optional[Tuple[float, float, float]]],
                           keyword: str, where: str
                           ) -> Optional[_MassWeightedBody]:
    """The momentum average for ONE partly-covered rigid body, or ``None``.

    ``None`` means "leave this body to the caller's existing behaviour", and
    every route to it warns with the reason — a guard that refuses in silence
    is a guard that cannot be audited.

    The arithmetic is :func:`k2rad.lumping.rigid_body_momentum_velocity`;
    everything here is the bookkeeping around it: which nodes the card
    prescribes (``group``), what velocity each of them carries
    (``velocity_of``, a constant for a ``*INITIAL_VELOCITY[_NODE]`` and the
    ``v + omega x r`` field for an ``_GENERATION``), and whether the body's
    /RBODY puts its main node where ``v_cm`` acts.

    **Where the velocity is written.** ``/INIVEL/TRA`` + ``/INIVEL/ROT`` on the
    MAIN node, from which ``inirby.F:1032-1048`` rebuilds every secondary as
    ``v_N = v_M + omega x (x_N - x_M)``. That is exact when the main node sits
    at the centre of mass, which is what ``ICoG`` 0/1 does (the starter MOVES
    it there, ``inirby.F:186-211``; measured on ``translat`` as
    ``NEW X/Y/Z 12.7 / 12.7 / 4e-15`` against LS-DYNA's 12.7 / 12.7 / 0). A
    body whose ``ICoG`` KEEPS the main node where it is (3, or 4 on an
    ``_INERTIA`` body) gets the transport term ``omega x (x_main - x_cm)``
    added to ``v_cm`` instead, so the rigid field is the same one either way.
    Any other ``ICoG`` is refused by name rather than guessed at — k2rad emits
    only 0, 3 and 4 today.
    """
    if info is None:
        return None
    nodes = sorted(set(info["nodes"]) | {main})
    mass_by_node, model_mass = _lumped_nodal_masses(state)
    coords: List[Tuple[float, float, float]] = []
    masses: List[float] = []
    vels: List[Optional[Tuple[float, float, float]]] = []
    for nid in nodes:
        nd = state.nodes.get(nid)
        if nd is None:
            state.warn(
                f"{keyword} {where}: --mass-weighted-inivel could not form the "
                f"momentum average for the rigid body on main node {main} - "
                f"its member node {nid} has no coordinates. The body keeps the "
                "behaviour it had without the flag.")
            return None
        coords.append((nd.x, nd.y, nd.z))
        masses.append(mass_by_node.get(nid, 0.0))
        vels.append(velocity_of(nid) if nid in group else None)
    icog = int(info.get("icog", 0) or 0)
    if icog not in (0, 1, 3, 4):
        state.warn(
            f"{keyword} {where}: --mass-weighted-inivel did not touch the "
            f"rigid body on main node {main} - its /RBODY carries ICoG "
            f"{icog}, and where that leaves the main node decides whether "
            "v_cm may be written there unchanged. k2rad emits only 0, 3 and 4, "
            "so this is a card no path of this writer produces. The body keeps "
            "the behaviour it had without the flag.")
        return None
    v_cm, omega, cog, refusal = rigid_body_momentum_velocity(
        coords, masses, vels, model_mass)
    if v_cm is None or omega is None or cog is None:
        state.warn(
            f"{keyword} {where}: --mass-weighted-inivel REFUSED the rigid body "
            f"on main node {main} - {refusal}. The body keeps the behaviour it "
            "had without the flag (the card's full velocity when every node of "
            "the card is a rigid member, nothing otherwise).")
        return None
    if icog in (3, 4):
        # The main node is NOT moved to the centre of mass, so the velocity
        # written on it is the rigid field's value AT the main node.
        nd = state.nodes[main]
        dx, dy, dz = nd.x - cog[0], nd.y - cog[1], nd.z - cog[2]
        v_cm = (v_cm[0] + omega[1] * dz - omega[2] * dy,
                v_cm[1] + omega[2] * dx - omega[0] * dz,
                v_cm[2] + omega[0] * dy - omega[1] * dx)
    covered = sum(1 for v in vels if v)
    state.warn(
        f"{keyword} {where}: --mass-weighted-inivel gave the rigid body on "
        f"main node {main} the MOMENTUM AVERAGE of the {covered} of its "
        f"{len(nodes)} /RBODY member node(s) (its secondary group plus "
        f"the main node) the card names - v_cm = ({v_cm[0]:.6g}, "
        f"{v_cm[1]:.6g}, {v_cm[2]:.6g}) and omega = ({omega[0]:.6g}, "
        f"{omega[1]:.6g}, {omega[2]:.6g}) on /INIVEL/TRA + /INIVEL/ROT, from "
        "which inirby.F:1032-1048 rebuilds every secondary. Vol I R17 "
        "p.28-129 Remark 3: 'the translational and rotational rigid body "
        "momentums are computed based on the prescribed nodal velocities. From "
        "this rigid body motion, the velocities of the nodal points are "
        "computed and reset to the new values.' Without the flag this body "
        "gets the card's FULL velocity (when every node of the card is a rigid "
        "member) or NOTHING at all (a mixed card). MEASURED on "
        "intro-by-j.-day/joint/joint-ii/translat.k at nt 4, where 2 of rigid "
        "part 1's 4 element nodes carry v = (2286, 0, 7620) against an LS-DYNA "
        "glstat cycle-0 K-ENERGY of 189.962: the full-velocity re-point reads "
        "387.9 (+104.20 %), this rule reads 220.58 (+16.12 %), and the final "
        "ke_dev goes +194.03 % -> +47.82 %. That residual is NOT the velocity "
        "- it is the /RBODY's own lumped rotary inertia (starter NEW INERTIA "
        "0.2642894E-02 against LS-DYNA's 0.1977E-02, the difference being "
        "exactly 4 x (m/4)(A + t^2)/12 = 6.65667e-4 per diagonal), and the "
        "/RBODY J cells are ADDITIVE (inirby.F:154-168), "
        + _mass_weighted_j_clause(info))
    return main, v_cm, omega


def _mass_weighted_j_clause(info: Dict) -> str:
    """The momentum-average warning's last clause: WHO takes the lumped IN
    back out of this body (round 7, A2). Since round 7 the ``*MAT_RIGID``
    producer writes ``J = -SUM(IN)`` by default and records it in
    ``info["j_in"]``; the flag's own J pass then leaves the body alone, so
    the round-6 wording ("the flag also writes ...") would be false on the
    default arm."""
    status = info.get("j_in", "")
    if status == "applied":
        return ("and k2rad already wrote J = -SUM(IN) into this body's /RBODY "
                "by default (round 7; --no-rigid-shell-rotary-inertia leaves "
                "it to this flag) to take it back out.")
    if status == "refused":
        return ("and the J = -SUM(IN) that would take it back out was REFUSED "
                "for this body (see its refusal line): its spin carries the "
                "lumped residual.")
    return ("so the flag also writes J = -SUM(IN) into this body's /RBODY to "
            "take it back out - see the J sentence for this body.")


def _warn_inivel_on_rigid_members(state: ConversionState, nsid: int,
                                  nids: List[int],
                                  rigid_nodes: Optional[Set[int]],
                                  keyword: str = "*INITIAL_VELOCITY",
                                  sid_label: str = "NSID",
                                  rbody_info: Optional[Dict] = None,
                                  repoint: bool = False,
                                  velocity_of: Optional[Callable[
                                      [int], Optional[Tuple[
                                          float, float, float]]]] = None,
                                  mass_weighted_block: str = ""
                                  ) -> Tuple[List[int],
                                             List[_MassWeightedBody]]:
    """Re-point (or name) the /INIVEL that lands on RIGID-BODY member nodes.

    ``inirby.F`` rebuilds every secondary node's velocity from its /RBODY main
    node as a rigid field, so an /INIVEL written on the secondaries is
    overwritten before the first cycle — the group is emitted, the starter
    accepts it at 0 ERROR / 0 WARNING, and the body does not move. LS-DYNA has
    no such rule: *INITIAL_VELOCITY on a rigid part's nodes sets the PART's
    velocity (that is what the IRIGID cell exists to override).

    MEASURED on ``intro-by-a.-tabiei/contact/contact-foam/matfoamsoil.k`` after
    the R14 round-2 set batch made its ``*SET_NODE_LIST_GENERATE 99`` resolve:
    the /INIVEL/TRA vx = 25000 lands on nodes 1000..1124, every one of them a
    member of ``*MAT_RIGID`` part 10 (/RBODY/1125), and the engine reaches
    NORMAL TERMINATION at 242 cycles with I-ENERGY = K-ENERGY = 0.000 against
    an LS-DYNA glstat of IE 8573.23 / KE 19834.5. Before the batch the set did
    not exist and no /INIVEL was written at all, so the deck was a zero model
    for a DIFFERENT reason — clearing the first one promoted the second into
    view, which is why it is named here rather than left silent.

    Re-pointing the group onto the /RBODY main node IS the fix, and with
    ``repoint=True`` this function performs it: when EVERY node of the card
    belongs to a rigid body, the group is replaced by that body's main node
    (or, for a card spanning several bodies, by one main node each). MEASURED
    on ``matfoamsoil`` — nothing changed but this group's member list — cycle-0
    K-ENERGY 3.547E+04 against the LS-DYNA glstat's own initial total energy
    3.54775E+04 (-0.008 %), where the un-re-pointed card gives 0.000; 1320
    cycles with both channels evolving against 242 flat at zero; starter
    0 ERRORS / 0 WARNINGS and NORMAL TERMINATION on both arms. Reproducing
    LS-DYNA's initial kinetic energy to four significant figures is direct
    evidence that LS-DYNA gives the rigid PART the velocity, and ``_make_bcs``
    already performs the same re-point for a ``*BOUNDARY_SPC`` on a rigid
    member (loads.py, ``node_to_ind``).

    ``*INITIAL_VELOCITY_GENERATION`` is re-pointed too, and needs NO arithmetic
    to keep its spin. The 2026-09 round-2 docstring claimed the opposite —
    "collapsing the group to the main node would give that one node its own
    omega x r and the body NO spin at all" — and it was never solver-measured.
    ``hm_read_inivel.F:580-617``, the ``ITYPE == 4`` (``/INIVEL/AXIS``) branch,
    writes BOTH halves per node::

        IF (IRODDL>0) THEN
           VR(1,NOSYS)= VRA*XFRAME(K1,IFM)      ! the ANGULAR velocity
           ...
        V(1,NOSYS)= V1+VRA*(NIXJ(3)-NIXJ(4))    ! V + omega x (x - O)

    and ``contrl.F:1053`` puts ``NRBODY`` in the ``IRODDL`` minimum, so any
    deck with an /RBODY has ``IRODDL = 1`` and the ``VR`` write always happens.
    ``inirby.F:1032-1048`` then rebuilds every secondary from the main node's
    six DOFs (``v_N = v_M + omega_M x (x_N - x_M)``, ``VR(:,N) = VR(:,M)``), so
    the body spins. MEASURED on a hand-built coupon (one 10 mm *MAT_RIGID cube,
    ``*INITIAL_VELOCITY_GENERATION`` STYP 2, OMEGA 100 about global Z through
    (50,0,0)): hand values ``1/2 m v_c^2 = 98.125`` and ``1/2 I omega^2 =
    1.9625`` from the starter's own echoed lumped inertia; the control reads
    KE-T 0.000 / KE-R 0.000 and the re-pointed arm 98.13 (+0.005 %) / 1.963
    (+0.026 %). And on the corpus's own controlled pair: ``brake.k`` and
    ``brake_debug.k`` differ by ONE emitted line (their ``*MAT_RIGID`` CON2
    cells, 6 vs 5, give ``/BCS/90005`` "111 101" vs "111 011"), the spin axis
    is global Y, and LS-DYNA's own initial KE is 1.33808e7 for brake and
    exactly 0.0 for brake_debug — the re-point moves the one whose axis is
    free, to +0.517 %, and leaves the other inert.

    A MIXED card is SPLIT rather than left whole: every deformable node stays,
    and each rigid body the card FULLY covers is replaced by its main node.
    Coverage is measured over the body's element nodes only
    (``_rbody_coverage_exempt``). A body a MIXED card only PARTLY covers keeps
    its nodes and is named: Vol I
    R17 p.28-129 Remark 3 says LS-DYNA computes the body's translational and
    rotational MOMENTUM from the prescribed nodal velocities and resets every
    node from that rigid motion. **``--mass-weighted-inivel`` forms exactly
    that average** (``_momentum_average_body`` →
    ``k2rad.lumping.rigid_body_momentum_velocity``, on the same lumped nodal
    masses ``tools/modal_solve`` pairs with the engine's own stiffness export)
    and writes it as ``/INIVEL/TRA`` + ``/INIVEL/ROT`` on the body's main node.
    It is OFF by default for an evidence reason, not a physics one: exactly ONE
    carrier with an LS-DYNA reference exists on this machine, and there is no
    LS-DYNA solver here to make a second — see
    ``ConvertOptions.mass_weighted_inivel``.

    **But a card that names ONLY rigid nodes re-points its partly-covered
    bodies too.** Refusing there does not fall back on the deformable half —
    there is none — it makes the whole card inert, and the round-3
    verification round measured exactly that regression on
    ``intro-by-j.-day/joint/joint-ii/translat.k``: its
    ``*INITIAL_VELOCITY_NODE`` names nodes 3 and 4 of rigid part 1, whose one
    shell element carries nodes 1-4, so the coverage test refused and the deck
    became a NORMAL-terminating model with I-ENERGY = K-ENERGY = 0.000 on all
    13980 cycles — the very zero model round 2 had cleared. The three arms,
    against the deck's own LS-DYNA glstat:

    ==========================  ==================  ==========
    arm                         cycle-0 K-ENERGY    vs LS
    ==========================  ==================  ==========
    LS-DYNA (glstat)            189.962             --
    re-pointed (shipped)        387.9               +104 %
    left on the secondaries     0.000               -100 %
    ==========================  ==================  ==========

    LS-DYNA's 189.962 is reproduced by hand from the deck's own geometry with
    equal corner masses: the momentum average gives the body ``v/2``, i.e.
    ``1/2 M (v/2)^2 = 97.0``, and the two loaded nodes sit on one edge so the
    body also SPINS — ``L = (M/4)(r3 + r4) x v`` over the lumped corner
    inertia gives ``omega = (300, 0, -45)`` and ``1/2 omega.I.omega = 93.0``;
    97.0 + 93.0 = 190.0 against the glstat's 189.962. By DEFAULT the writer
    forms neither half — it gives the main node the card's FULL velocity and
    NAMES the over-estimate. Between a model that is 2x too fast and one that
    does not move at all, the over-estimate is the one whose channels evolve;
    it is what round 2 shipped and what the campaign recorded as a cleared zero
    model. ``--mass-weighted-inivel`` forms BOTH halves and writes them on the
    main node: on this very deck it emits ``v_cm = (1143, 0, 3810)`` — half the
    card's ``(2286, 0, 7620)`` — and ``omega = (300, 0, -45)``, the hand values
    above to every digit, for a cycle-0 K-ENERGY of **220.58** (+16.12 %).
    MEASURED on the two corpus carriers: ``pipe.k`` (IVG over 2 parts of which
    1 is rigid, omega -82) goes from a cycle-0 KE of 8.69749e7 to 8.70569e7
    against the LS-DYNA glstat's 8.70616e7, i.e. -0.100 % to -0.005 %; and
    ``mat_spring.belted-dummy`` (whole-model ``*INITIAL_VELOCITY``, 1640 of
    1931 nodes rigid) is byte-identical either way at -0.006 %.

    **All three emission sites call this** — ``_make_inivel``
    (``*INITIAL_VELOCITY_NODE``), ``_make_initial_velocity`` (the NSID set
    form) and ``_make_initial_velocity_generation``
    (``*INITIAL_VELOCITY_GENERATION``) — because the same keyword family lands
    in three different writer functions and a probe on one leaves the other two
    silent (the #132 rule). The second carrier the widening found is
    ``intro-by-j.-day/contact/force-transducer/transducer.k``: all six
    ``*INITIAL_VELOCITY_NODE`` nodes (1-6, vy = 10160) are the member set of
    ``/RBODY/23``, the engine reports K-ENERGY 0.000 at cycle 0 and at every
    one of its 969 cycles against an LS-DYNA glstat of IE 161.523 /
    KE 1092.45 — and before this the deck said nothing at all.
    """
    if not rigid_nodes:
        return list(nids), []
    on_rigid = [n for n in nids if n in rigid_nodes]
    if not on_rigid:
        return list(nids), []
    where = f"{sid_label}={nsid}" if nsid else "over the whole model"
    named = ", ".join(str(n) for n in on_rigid[:5])
    all_rigid = len(on_rigid) == len(nids)
    axis_note = (
        " The card becomes an /INIVEL/AXIS, which writes BOTH halves on every "
        "node of its group when IRODDL > 0 (hm_read_inivel.F:580-617: "
        "VR = omega*n and V = V + omega x (x - O)), and any deck with an "
        "/RBODY has IRODDL = 1 (contrl.F:1053) — so the main node carries the "
        "body's spin as well as its translation, and inirby.F:1032-1048 "
        "rebuilds the secondaries from it."
        if keyword.endswith("_GENERATION") else "")

    if repoint:
        group = set(nids)
        main_of = _rbody_main_of(rbody_info)
        exempt = _rbody_coverage_exempt(state)
        covered_mains: List[int] = []
        partial_mains: List[int] = []
        partial_nodes: Set[int] = set()
        seen_mains: Set[int] = set()
        for info in (rbody_info or {}).values():
            body = set(info["nodes"])
            hit = body & group
            if not hit:
                continue
            main = info["ind_node"]
            if main in seen_mains:
                continue
            seen_mains.add(main)
            if (body - exempt) <= group:
                covered_mains.append(main)
            else:
                partial_mains.append(main)
                partial_nodes |= hit
        # --mass-weighted-inivel: a body the card covers only PARTLY gets the
        # momentum average of Vol I R17 p.28-129 Remark 3 on its main node,
        # instead of the card's FULL velocity (an all-rigid card, below) or
        # nothing at all (a mixed card, where it is refused). A body the card
        # FULLY covers is deliberately NOT routed through here: its momentum
        # average IS the card's velocity with omega 0, so the existing
        # re-point already writes the same physics and no deck of that class
        # changes a byte.
        mw_bodies: List[_MassWeightedBody] = []
        mw_dropped: Set[int] = set()
        if (state.options.mass_weighted_inivel and partial_mains
                and mass_weighted_block):
            # The flag is ON and this card HAS the class it targets, but
            # something about the card puts it out of the rule's scope. Said
            # out loud: a lever that silently does nothing on the one deck it
            # was passed for is worse than no lever.
            state.warn(
                f"{keyword} {where}: --mass-weighted-inivel did NOT touch the "
                f"{len(partial_mains)} partly covered rigid body/bodies here - "
                + mass_weighted_block + ". They keep the behaviour they have "
                "without the flag.")
        elif (state.options.mass_weighted_inivel and partial_mains
                and velocity_of is not None):
            info_by_main = {i["ind_node"]: i
                            for i in (rbody_info or {}).values()}
            still_partial: List[int] = []
            for main in sorted(partial_mains):
                got = _momentum_average_body(
                    state, info_by_main.get(main), main, group, velocity_of,
                    keyword, where)
                if got is None:
                    still_partial.append(main)
                    continue
                mw_bodies.append(got)
                mw_dropped |= set(info_by_main[main]["nodes"]) | {main}
            partial_mains = still_partial
            partial_nodes = {n for n in partial_nodes if n not in mw_dropped}
        over_mains: List[int] = []
        if all_rigid and partial_mains:
            # EVERY node the card names is a rigid-body member, so leaving a
            # partly-covered body's nodes where they are makes the card move
            # NOTHING at all (inirby.F:1032-1048 rebuilds every one of them
            # from the main node). The choice here is not between a faithful
            # arm and an over-estimate - it is between an over-estimate and an
            # inert model, and round 2 shipped the over-estimate. The
            # docstring carries the three measured arms on translat.k.
            over_mains = sorted(partial_mains)
            covered_mains = sorted(set(covered_mains) | set(partial_mains))
            partial_mains = []
            partial_nodes = set()
        if covered_mains:
            # Every node of a fully-covered body leaves the group; the body's
            # main node takes its place. Deformable nodes, and the nodes of a
            # body only partly covered by a MIXED card, stay where they were.
            kept = [n for n in nids
                    if (n not in main_of or main_of[n] in partial_mains)
                    and n not in mw_dropped]
            out = sorted(set(kept) | set(covered_mains))
            if out != sorted(nids):
                shown = ", ".join(str(m) for m in sorted(covered_mains)[:5])
                state.warn(
                    f"{keyword} {where}: {len(on_rigid)} of its {len(nids)} "
                    f"node(s) (e.g. {named}) belong to a rigid body, so the "
                    f"{len(covered_mains)} body/bodies the card "
                    + ("touches" if over_mains else "FULLY covers")
                    + f" are RE-POINTED onto their /RBODY main node(s) {shown}"
                    + (" ..." if len(covered_mains) > 5 else "")
                    + f" — the group goes from {len(nids)} to {len(out)} "
                    "node(s)"
                    + ("" if all_rigid else
                       ", the deformable nodes unchanged")
                    + ". OpenRadioss rebuilds a /RBODY secondary node's "
                    "velocity from the body's main node every cycle "
                    "(inirby.F:1032-1048), so the same card written on the "
                    "secondaries is OVERWRITTEN before cycle 1 and the body "
                    "starts at rest at 0 starter diagnostics; LS-DYNA gives "
                    "the rigid PART that velocity (Vol I R17 p.28-129 Remark "
                    "3). Measured cycle-0 K-ENERGY against each deck's own "
                    "LS-DYNA glstat: matfoamsoil 3.547E+04 vs 3.54775E+04 "
                    "(-0.008 %), sphere1 6.993E+06 vs 6.99320E+06 "
                    "(-0.003 %), wood-post 5.409E+07 vs 5.40914E+07 "
                    "(-0.003 %), brake's rotational 1.345E+07 vs 1.33808E+07 "
                    "(+0.517 %) — all 0.000 without the re-point. Pass "
                    "*INITIAL_VELOCITY_RIGID_BODY to state it explicitly."
                    + (
                        f" {len(over_mains)} of these bodies (main node(s) "
                        + ", ".join(str(m) for m in over_mains[:5])
                        + (" ..." if len(over_mains) > 5 else "")
                        + ") are only PARTLY covered by the card and are "
                        "re-pointed anyway, which OVER-STATES their velocity: "
                        "Vol I R17 p.28-129 Remark 3 gives such a body the "
                        "MASS-WEIGHTED momentum average of the prescribed "
                        "nodal velocities, which is smaller. Every node this "
                        "card names is a rigid member, so the alternative is "
                        "not a smaller velocity but NONE - MEASURED on "
                        "translat.k (2 of rigid part 1's 4 element nodes, "
                        "v = (2286, 0, 7620)): cycle-0 K-ENERGY 387.9 "
                        "re-pointed against the LS-DYNA glstat's 189.962, and "
                        "0.000 with every channel flat for all 13980 cycles "
                        "when the card is left on the secondaries. LS-DYNA's "
                        "190.0 is 97.0 translational + 93.0 rotational (hand "
                        "arithmetic on the deck's own geometry at equal "
                        "corner masses), i.e. the body also SPINS. PASS "
                        "--mass-weighted-inivel to write both halves instead "
                        "of the card's full velocity: on that deck it emits "
                        "v_cm = (1143, 0, 3810) and omega = (300, 0, -45) on "
                        "the main node for a cycle-0 K-ENERGY of 220.58 "
                        "(+16.12 % against 189.962, where this arm reads "
                        "+104.20 %). It is opt-in because exactly one carrier "
                        "with an LS-DYNA reference exists. Or state "
                        "*INITIAL_VELOCITY_RIGID_BODY on the part to control "
                        "it exactly."
                        if over_mains else "")
                    + axis_note)
            if partial_mains:
                _warn_inivel_partial_rigid_body(
                    state, keyword, where, partial_mains, partial_nodes)
            return out, mw_bodies
        if partial_mains:
            _warn_inivel_partial_rigid_body(
                state, keyword, where, partial_mains, partial_nodes)
        if mw_bodies:
            # No body was FULLY covered, but at least one partly-covered body
            # took the momentum average: its nodes leave the group (the
            # /INIVEL on them would be overwritten from the main node anyway)
            # and the deformable half of a mixed card stays exactly as it was.
            return ([n for n in nids if n not in mw_dropped], mw_bodies)
        if partial_mains:
            return list(nids), []

    state.warn(
        f"{keyword} {where}: {len(on_rigid)} of its {len(nids)} "
        f"node(s) (e.g. {named}) belong to a rigid body. OpenRadioss rebuilds "
        "a /RBODY secondary node's velocity from the body's main node every "
        "cycle (inirby.F), so the /INIVEL on them is OVERWRITTEN before cycle "
        "1 and the body starts at rest — at 0 starter diagnostics."
        + (" EVERY node of this card is a rigid-body member, so the card moves "
           "NOTHING." if all_rigid else "")
        + " LS-DYNA instead gives the rigid PART that velocity. State it as "
          "*INITIAL_VELOCITY_RIGID_BODY on the part (k2rad puts that on the "
          "/RBODY main node), or as *PART_INERTIA card 5, to move the body."
        + ("" if all_rigid else
           " The card is left over its stated nodes: re-pointing only the "
           "rigid half would change which nodes it names."))
    return list(nids), []


def _warn_inivel_partial_rigid_body(state: ConversionState, keyword: str,
                                    where: str, mains: List[int],
                                    hit: Set[int]) -> None:
    """Name a rigid body a MIXED initial-velocity card covers only PARTLY.

    Refused rather than modelled — and only on a card that also names
    DEFORMABLE nodes, which keep working. When EVERY node of the card is a
    rigid member the caller re-points these bodies instead and names the
    over-estimate, because refusing there leaves the card moving nothing at
    all (see ``_warn_inivel_on_rigid_members``, translat.k). Vol I R17 p.28-129 ``*INITIAL_VELOCITY_
    GENERATION`` Remark 3 (``*INITIAL_VELOCITY`` Remark 4, p.28-125, is the
    same sentence): *"Nodes that belong to rigid bodies must have motion
    consistent with the translational and rotational velocity of the rigid
    body. During initialization, the translational and rotational rigid body
    momentums are computed based on the prescribed nodal velocities. From this
    rigid body motion, the velocities of the nodal points are computed and
    reset to the new values. These new values may or may not be the same as the
    values prescribed for the node."* That is a MASS-weighted average over the
    whole body, so the body's velocity is smaller than the card's.
    ``--mass-weighted-inivel`` forms it and writes it on the body's main node;
    this refusal is what happens with the flag OFF, which is the default (one
    carrier with a reference — see ``ConvertOptions.mass_weighted_inivel``).
    """
    shown = ", ".join(str(m) for m in sorted(mains)[:5])
    state.warn(
        f"{keyword} {where}: it names {len(hit)} node(s) of rigid body/bodies "
        f"whose main node(s) are {shown}"
        + (" ..." if len(mains) > 5 else "")
        + " but NOT every element node of them, so those bodies are left "
        "un-re-pointed and their part of the card moves nothing "
        "(inirby.F:1032-1048 rebuilds a secondary's velocity from the main "
        "node). LS-DYNA does not give the body the card's velocity either: "
        "Vol I R17 p.28-129 Remark 3 says it computes the body's "
        "translational and rotational MOMENTUM from the prescribed nodal "
        "velocities and resets every node from that rigid motion, i.e. a "
        "MASS-weighted average that is smaller than the stated velocity. "
        "PASS --mass-weighted-inivel and k2rad forms exactly that average "
        "from the body's own lumped nodal masses and writes it as "
        "/INIVEL/TRA + /INIVEL/ROT on the /RBODY main node (MEASURED on "
        "intro-by-j.-day/joint/joint-ii/translat.k at nt 4: cycle-0 K-ENERGY "
        "220.58 against the LS-DYNA glstat's 189.962, +16.12 %, where the "
        "full-velocity arm reads 387.9 / +104.20 %); it is OFF by default "
        "because exactly one carrier with an LS-DYNA reference exists on this "
        "machine. Or give the body its own *INITIAL_VELOCITY_RIGID_BODY (or "
        "*PART_INERTIA card 5) with the velocity you want, or extend the "
        "card's set to the whole body.")


def _make_initial_velocity(state: ConversionState,
                           rigid_nodes: Optional[Set[int]] = None,
                           rbody_info: Optional[Dict] = None) -> List[str]:
    """*INITIAL_VELOCITY (base set form) → /INIVEL/TRA (+ /INIVEL/ROT).

    NSID scopes the node group (blank/0 = whole model); NSIDEX is subtracted by
    set difference (writer phase = every *SET_NODE is resolvable). BOXID and a
    rigid-overwrite IRIGID are warned + dropped; ICID maps to the matching
    /SKEW when *DEFINE_COORDINATE_* produced one, else falls back to global.
    """
    if not state.inivel_general:
        return []
    lines: List[str] = []
    for iv in state.inivel_general:
        has_tra = bool(iv.vx or iv.vy or iv.vz)
        has_rot = bool(iv.vxr or iv.vyr or iv.vzr)
        if not has_tra and not has_rot:
            continue   # zero velocity → no-op card

        # ── resolve the node group ──────────────────────────────────────────
        if iv.nsid:
            ns = state.node_sets.get(iv.nsid)
            if ns is None:
                state.warn(
                    f"*INITIAL_VELOCITY NSID={iv.nsid}: this deck defines no "
                    "*SET_NODE with that id - skipped. (The parenthetical this "
                    "message used to carry, \"unsupported *SET_NODE "
                    "variant?\", named the R14 round-2 defect: "
                    "*SET_NODE_LIST_GENERATE, _GENERAL and _COLUMN went "
                    "unread, so taylor1/taylor2/matfoamsoil ran with no "
                    "/INIVEL at all. All three spellings are read now. The "
                    "spellings still NOT read are *SET_NODE_LIST_SMOOTH and "
                    "the *SET_NODE_GENERAL clauses k2rad refuses by name "
                    "(BRANCH, VOL, SALE*), each of which warns for itself.)")
                continue
            base = set(ns[1])
        else:
            base = set(state.nodes.keys())         # whole model
        if iv.nsidex:
            ex = state.node_sets.get(iv.nsidex)
            if ex is None:
                state.warn(
                    f"*INITIAL_VELOCITY NSIDEX={iv.nsidex}: exclusion set not "
                    "resolvable - applied WITHOUT exclusion")
            else:
                base -= set(ex[1])
        # ── BOXID: intersect the group with the *DEFINE_BOX contained nodes ──
        if iv.boxid:
            box_nids = _resolve_box_nodes(
                state, iv.boxid, f"*INITIAL_VELOCITY BOXID={iv.boxid}")
            if box_nids is not None:
                before = len([n for n in base if n > 0])
                base &= box_nids
                state.warn(
                    f"*INITIAL_VELOCITY BOXID={iv.boxid}: velocity scoped to the "
                    f"{len([n for n in base if n > 0])} node(s) inside "
                    f"*DEFINE_BOX {iv.boxid} (of {before} in the base group).")
        nids = sorted(n for n in base if n > 0)
        if not nids:
            state.warn("*INITIAL_VELOCITY: resolved node group is empty - skipped")
            continue
        nids, mw_bodies = _warn_inivel_on_rigid_members(
            state, iv.nsid, nids, rigid_nodes,
            rbody_info=rbody_info, repoint=True,
            velocity_of=_constant_velocity_of((iv.vx, iv.vy, iv.vz)),
            mass_weighted_block=("the card also states NODAL ROTATIONAL velocities "
                     "(VXR/VYR/VZR), and this rule forms the body's angular "
                     "momentum from the TRANSLATIONAL velocities alone - "
                     "folding a prescribed nodal spin into it needs each "
                     "node's own rotary inertia, which the momentum average "
                     "does not use"
                                 if (iv.vxr or iv.vyr or iv.vzr) else ""))
        lines += _emit_mass_weighted_bodies(state, mw_bodies, "inivel_set")

        # ── lossy fields (warn + continue) ──────────────────────────────────
        if iv.irigid:
            state.warn(
                f"*INITIAL_VELOCITY IRIGID={iv.irigid}: rigid-body velocity "
                "overwrite bookkeeping not modelled - velocity applied to the "
                "node group as-is")
        skew_id = 0
        if iv.icid:
            if (iv.icid in state.coord_sys or iv.icid in state.coord_nodes
                    or iv.icid in state.coord_vectors):
                skew_id = iv.icid
                state.warn(
                    f"*INITIAL_VELOCITY ICID={iv.icid}: velocity components read "
                    f"in /SKEW/{iv.icid} (components not rotated to global, "
                    "matching LS-DYNA)")
            else:
                state.warn(
                    f"*INITIAL_VELOCITY ICID={iv.icid}: no converted /SKEW with "
                    "that id - velocity applied in the GLOBAL frame")

        # ── emit ────────────────────────────────────────────────────────────
        if not nids:
            # Every node this card named went to a momentum-averaged
            # rigid body above (--mass-weighted-inivel); there is no
            # group left to write. The lossy-field warnings above still
            # ran, because what the card STATED is still worth saying.
            continue
        grnod_id = state.next_grnod_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_grp_{grnod_id}", nids)
        if has_tra:
            tid = state.next_id()
            lines += _emit_inivel("TRA", tid, f"InitVel_{tid}", grnod_id,
                                  (iv.vx, iv.vy, iv.vz), skew_id)
        if has_rot:
            rid = state.next_id()
            lines += _emit_inivel("ROT", rid, f"InitVelRot_{rid}", grnod_id,
                                  (iv.vxr, iv.vyr, iv.vzr), skew_id)

    if lines:
        lines = ["#-  INITIAL VELOCITY (set form):", HDR] + lines
    return lines


def _inivel_gen_group_nodes(state: ConversionState, g):
    """Resolve the *INITIAL_VELOCITY_GENERATION STYP scope to sorted node ids.
    Returns None when the STYP target id cannot be resolved (caller falls back
    to the whole model with a warning)."""
    nids: Set[int] = set()

    def add_part_nodes(pid: int):
        for e in state.shell_elems:
            if e.pid == pid:
                nids.update(e.nodes)
        for e in state.solid_elems:
            if e.pid == pid:
                nids.update(e.nodes)
        for e in state.tshell_elems:        # /BRICK — same as an ordinary hex
            if e.pid == pid:
                nids.update(e.nodes)
        # SPH particles: their nodes ARE the mesh of the part, and driving an
        # SPH body by *INITIAL_VELOCITY_GENERATION with STYP=2/3 (a part or a
        # part set) is the idiomatic way to launch a bird / a jet. Without this
        # arm the group comes out EMPTY and the projectile does not move — the
        # #120 thick-shell failure again, and the highest-value SPH row in that
        # audit because the W11 bird strike is exactly this shape.
        for c in state.sph_elems:
            if c.pid == pid:
                nids.update(c.nodes)
        for e in state.beam_elems:
            if e.pid == pid:
                nids.update((e.n1, e.n2))
        for e in state.discrete_elems:      # *ELEMENT_DISCRETE (springs); n2=0=ground
            if e.pid == pid:
                nids.update((e.n1, e.n2))
        # Belt elements: a 1D belt part's nodes ARE its mesh, and a sled test
        # launched with *INITIAL_VELOCITY_GENERATION over the whole vehicle
        # scopes by part set. Leaving the belt out gives it zero initial
        # velocity while the dummy it restrains has the sled's - the belt would
        # be yanked taut at t=0. (2D belt elements are in state.shell_elems by
        # then, so the shell arm above already covers them.)
        for e in state.seatbelt_elems:
            if e.pid == pid:
                nids.update((e.n1, e.n2, e.n3, e.n4))

    if g.styp == 0 or g.sid == 0:
        return sorted(state.nodes.keys())            # whole model
    if g.styp == 1:                                  # part set
        ps = state.part_sets.get(g.sid)
        if ps is None:
            return None
        for pid in ps[1]:
            add_part_nodes(pid)
    elif g.styp == 2:                                # single part
        if g.sid not in state.parts:
            return None
        add_part_nodes(g.sid)
    elif g.styp == 3:                                # node set
        ns = state.node_sets.get(g.sid)
        if ns is None:
            return None
        nids.update(ns[1])
    else:
        return None
    return sorted(n for n in nids if n > 0)


def _make_initial_velocity_generation(
        state: ConversionState,
        rigid_nodes: Optional[Set[int]] = None,
        rbody_info: Optional[Dict] = None) -> List[str]:
    """*INITIAL_VELOCITY_GENERATION → /INIVEL/AXIS + a companion /FRAME/FIX.

    The rotation axis (through (XC,YC,ZC) along (NX,NY,NZ), or node-defined when
    NX=-999) becomes the frame's local Z; OMEGA → VR about it; the translational
    (VX,VY,VZ) is projected onto the frame's local axes so Radioss re-expands it
    to the correct global velocity. A nonzero ICID rotates VX/VY/VZ and the
    vector axis from that local system to global (there is no Skew_id field on
    /INIVEL/AXIS, so it is baked in here). STYP selects the node group. PHASE,
    IVATN and IRIGID are lossy and warned.
    """
    if not state.inivel_generations:
        return []
    refX, refY, refZ = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    # /FRAME and /SKEW share ONE id namespace in the starter (UDOUBLE over the
    # combined table), and converted /SKEW ids preserve the LS-DYNA coord cid
    # verbatim — so a synthesized frame id must never land on one, or the starter
    # aborts with ERROR 79 DUPLICATE ID. all_skew_ids() covers every converted
    # skew: coordinate systems/nodes/vectors and the *DEFINE_VECTOR /
    # *DEFINE_SD_ORIENTATION skews the prepass assigned.
    reserved_skew = state.all_skew_ids()
    lines: List[str] = []
    for g in state.inivel_generations:
        if g.phase:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION PHASE={g.phase}: dynamic-relaxation "
                "phase flag not modelled - velocity applied at t=0")
        if g.ivatn:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION IVATN={g.ivatn}: attached "
                "secondary-node scoping dropped")
        if g.irigid:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION IRIGID={g.irigid}: rigid-body "
                "overwrite flag not modelled")
        # ICID: VX/VY/VZ and the (vector) rotation axis are given in this local
        # system. Resolve its global basis and pre-rotate them, mirroring the
        # plain *INITIAL_VELOCITY path (which attaches a Skew_id and lets Radioss
        # rotate) — /INIVEL/AXIS has no skew field, so the rotation is baked here.
        icid_basis = None
        if g.icid:
            icid_basis = _icid_basis(state, g.icid)
            if icid_basis is None:
                state.warn(
                    f"*INITIAL_VELOCITY_GENERATION ICID={g.icid}: no converted "
                    "/SKEW with that id - VX/VY/VZ and the rotation axis applied "
                    "in the GLOBAL frame")
            else:
                state.warn(
                    f"*INITIAL_VELOCITY_GENERATION ICID={g.icid}: VX/VY/VZ and the "
                    f"vector rotation axis rotated from /SKEW/{g.icid} to global")

        # ── origin + raw rotation axis vector ───────────────────────────────
        if -999.5 < g.nx < -998.5:                     # NX=-999 → node-defined axis
            n1 = state.nodes.get(g.node1)
            n2 = state.nodes.get(g.node2)
            if n1 is None or n2 is None:
                state.warn(
                    f"*INITIAL_VELOCITY_GENERATION: axis node {g.node1}/{g.node2} "
                    "missing - rotation axis undefined, OMEGA dropped")
                origin, N = (g.xc, g.yc, g.zc), (0.0, 0.0, 0.0)
            else:
                origin = (n1.x, n1.y, n1.z)      # nodes are global; ICID N/A here
                N = _vsub((n2.x, n2.y, n2.z), origin)
        else:
            origin, N = (g.xc, g.yc, g.zc), (g.nx, g.ny, g.nz)
            if icid_basis is not None:
                N = _local_to_global(icid_basis, N)

        # ── build the local frame triad (local Z = rotation axis) ───────────
        nhat = _vnorm(N)
        vr = g.omega
        if nhat is None:
            if g.omega:
                state.warn(
                    "*INITIAL_VELOCITY_GENERATION: no rotation axis "
                    "(NX=NY=NZ=0 or degenerate nodes) - OMEGA dropped, "
                    "translation only")
            vr = 0.0
            fz = refZ
            fy = _vnorm(_vcross(refZ, refX)) or refY
            fx = _vnorm(_vcross(fy, fz)) or refX
        else:
            fz = nhat
            fy = _vnorm(_vcross(nhat, refX)) or _vnorm(_vcross(nhat, refZ)) or refY
            fx = _vnorm(_vcross(fy, fz)) or refX

        # ── translational velocity, expressed in the frame's local axes ─────
        gV = (g.vx, g.vy, g.vz)
        if icid_basis is not None:       # rotate ICID-local components to global
            gV = _local_to_global(icid_basis, gV)
        vxt = _vdot(fx, gV)              # local X = FrameVect3
        vyt = _vdot(fy, gV)              # local Y = FrameVect1
        vzt = _vdot(fz, gV)             # local Z = FrameVect2

        # ── node group (STYP) ──────────────────────────────────────────────
        nids = _inivel_gen_group_nodes(state, g)
        if nids is None:
            state.warn(
                f"*INITIAL_VELOCITY_GENERATION STYP={g.styp} id={g.sid}: scope "
                "target not found - applied to the whole model")
            nids = sorted(state.nodes.keys())
        if not nids:
            state.warn("*INITIAL_VELOCITY_GENERATION: node group empty - skipped")
            continue

        # ── emit /FRAME/FIX then /INIVEL/AXIS ───────────────────────────────
        frame_id = state.next_id()
        while frame_id in reserved_skew:   # never collide with a converted /SKEW
            frame_id = state.next_id()
        lines += _emit_frame_fix(frame_id, f"FRAME_INIVEL_GEN_{frame_id}",
                                 origin, fy, fz)
        # The RETURN VALUE is the group: the round-2 site called this helper
        # and threw it away, so flipping repoint would have changed nothing.
        # The card's velocity FIELD, per node: the rigid motion
        # v + omega x (x - O) that hm_read_inivel.F:580-617 writes itself. The
        # momentum average needs the prescribed velocity of each node, and on
        # this card that is not one constant.
        def _gen_velocity_of(nid: int, _o=origin, _n=nhat, _w=vr,
                             _v=(g.vx, g.vy, g.vz)
                             ) -> Optional[Tuple[float, float, float]]:
            nd = state.nodes.get(nid)
            if nd is None:
                return None
            if not _w or _n is None:
                return _v
            rx, ry, rz = nd.x - _o[0], nd.y - _o[1], nd.z - _o[2]
            wx, wy, wz = _w * _n[0], _w * _n[1], _w * _n[2]
            return (_v[0] + wy * rz - wz * ry,
                    _v[1] + wz * rx - wx * rz,
                    _v[2] + wx * ry - wy * rx)

        nids, mw_bodies = _warn_inivel_on_rigid_members(
            state, g.sid, list(nids), rigid_nodes,
            keyword="*INITIAL_VELOCITY_GENERATION", sid_label="SID",
            rbody_info=rbody_info, repoint=True,
            velocity_of=_gen_velocity_of)
        lines += _emit_mass_weighted_bodies(state, mw_bodies, "inivel_gen")
        if not nids:
            # Every node of the card went to a momentum-averaged body
            # (--mass-weighted-inivel), so there is no group left for the
            # /INIVEL/AXIS. The /FRAME/FIX above stays behind, unused: a
            # frame is a standalone card (nothing requires it to be
            # referenced) and it costs one id, which is cheaper than
            # moving the frame emission below a decision that depends on
            # the group this very call returns.
            continue
        grnod_id = state.next_grnod_id()
        lines += _emit_grnod_node(grnod_id, f"inivel_gen_grp_{grnod_id}", nids)
        inivel_id = state.next_id()
        lines += _emit_inivel_axis(inivel_id, f"InitVelGen_{inivel_id}",
                                   frame_id, grnod_id, (vxt, vyt, vzt), vr)

    if lines:
        lines = ["#-  INITIAL VELOCITY GENERATION:", HDR] + lines
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: pressure loads
# ─────────────────────────────────────────────────────────────────────────────

_PLOAD_COMMENT = ("#  surf_ID  functIDT sensor_ID                             "
                  "             Ascale_x            Fscale_y")


def _emit_pload_card(pload_id: int, title: str, surf_id: int, lcid: int,
                     fscale: float, sensor_id: int = 0,
                     state: Optional[ConversionState] = None) -> List[str]:
    """One /PLOAD block.

    Card grid (``radioss2021/LOADS/pload.cfg``, the newest FORMAT block a
    ``/BEGIN 2022`` deck resolves):
      ``surf_ID(10) fct_IDT(10) sens_ID(10) Ipinch(10) Idel(10) <blank 51-60>
        Ascale_x(20) Fscale_y(20)``
    Cols 31-60 are left blank, which the reader takes as ``Ipinch=0`` and
    ``Idel=0 -> 1`` (cancel the pressure once every element of a segment is
    deleted). Cols 51-60 must STAY blank: that is where the 2023-only
    ``Itypfun`` column lives, and writing it into a 2022 deck raises
    ``WARNING ID 100214`` "unsupported field exists" (measured).

    ``Ascale_x`` is always 1.0 — it is an abscissa DIVISOR (the starter stores
    ``PRES(2,K) = ONE/FCX``, ``hm_read_pload.F:166``), and no LS-DYNA pressure
    keyword scales the time axis.

    Pass *state* to read a curve OpenRadioss would extrapolate nonzero
    through its zero-off-scale copy (round 9, B5; a sensor-gated card is
    excluded: its argument is shifted by the sensor's start).
    """
    if state is not None:
        from .loadcurves import load_funct_id
        lcid = load_funct_id(state, lcid, "PLOAD", sensor_id=sensor_id)
    return [
        f"/PLOAD/{pload_id}",
        title,
        _PLOAD_COMMENT,
        f"{_i(surf_id)}{_i(lcid)}{_i(sensor_id)}" + " " * 30
        + f"{_f(1.0)}{_f(fscale)}",
        HDR,
    ]


def _emit_sensor_time(sensor_id: int, title: str, tdelay: float) -> List[str]:
    """One /SENSOR/TIME block — the only time gate a /PLOAD has.

    Card: ``Tdelay(20) Tstop(20)`` (``radioss2022/SENSOR/sensor.cfg:219-222``
    selects the header ``/SENSOR/TIME/<id>``; ``read_sensor_time.F:69-71`` reads
    the two floats and turns ``Tstop = 0`` into INFINITY, so leaving it 0 means
    "never deactivate").

    What the consumer then does with it, and why it is a SHIFT and not a gate:
    ``sensor_time.F:66-68`` sets ``SENSOR%TSTART = TDELAY`` once the sensor
    fires, and the load evaluation subtracts it — ``force.F90:216-218``:
    ``ts = tt - sensor_tab(isens)%tstart``, with ``IF (ts < ZERO) CYCLE``. So the
    load is zero for ``t < Tdelay`` and the pressure curve is evaluated at
    ``t - Tdelay`` afterwards. That is exactly how LS-DYNA's arrival time AT
    reads, and it is what dyna2rad emits (``convertloads.cxx:803-812``).
    """
    return [
        f"/SENSOR/TIME/{sensor_id}",
        title,
        "#             Tdelay               Tstop",
        f"{_f(tdelay)}{_f(0.0)}",
        HDR,
    ]


def _shell_load_segments(state: ConversionState, eids: List[int],
                         label: str, shells: Optional[Dict] = None
                         ) -> List[List[int]]:
    """The /SURF/SEG rows for a list of shell element ids.

    The connectivity is pasted through UNREVERSED: ``/SHELL`` /``/SH3N``
    ``elem_ID n1 n2 n3 n4`` maps column-for-column onto ``/SURF/SEG``
    ``seg_ID n1 n2 n3 n4`` (Reference Guide 2022 p.2499 Comment 3 says segments
    may be produced by cut-and-paste of shell element input), so the segment
    normal IS the shell normal and the single sign flip lives in Fscale_y.

    Pass *shells* (``{eid: ShellElem}``) when calling this in a loop — building
    it per row is O(elements x rows).
    """
    if shells is None:
        shells = {e.eid: e for e in state.shell_elems}
    segs: List[List[int]] = []
    missing: List[int] = []
    for eid in eids:
        e = shells.get(eid)
        if e is None:
            missing.append(eid)
            continue
        nodes = [n for n in e.nodes if n > 0]
        # A degenerate quad (n4 == n3) is a triangle: /SURF/SEG wants n4 = 0 so
        # hm_read_pload.F:196-200 flags a true tria and force.F90 uses the 1/6
        # per-node factor instead of 1/8.
        if len(nodes) >= 4 and nodes[3] == nodes[2]:
            nodes = nodes[:3]
        if len(nodes) >= 3:
            segs.append(nodes[:4])
    if missing:
        state.warn(
            f"{label}: shell element(s) {_fmt_eid_list(sorted(missing))} are not "
            "in the deck (or are not shells) — those faces carry no /PLOAD. "
            "*LOAD_SHELL only loads shells; a solid face needs *LOAD_SEGMENT.")
    return segs


def _make_pressure_loads(state: ConversionState) -> List[str]:
    """*LOAD_SEGMENT[_SET] and *LOAD_SHELL_ELEMENT/_SET → /SURF/SEG + /PLOAD.

    /PLOAD has ONE data card referencing a surface; see _emit_pload_card for the
    column grid. The segments themselves are a /SURF/SEG entity (seg_ID n1 n2 n3
    n4, five 10-char fields per line; n4=0 → triangle).

    **Sign.** Positive ``Fscale_y`` pushes the surface along its POSITIVE
    segment normal ``n = N1N3 x N2N4`` (Altair help, /PLOAD Comment 1; engine
    ``force.F90:451-465`` sums ``+P*A*n_hat`` over the segment's nodes). The two
    sources differ:

    * *LOAD_SEGMENT / _SET gives the pressure on an explicitly ORIENTED
      segment — and the orientation does NOT carry the direction, because
      LS-DYNA's own sign rule is stated against it: Vol I R17 p.33-107,
      Figure 33-12's caption, *"Positive pressure acts in the negative
      t-direction"*, with ``t`` the right-hand normal of the N1..N4 order.
      k2rad pastes that node order into the ``/SURF/SEG`` verbatim, so
      ``n_hat = t_hat`` and exactly ONE flip is needed: ``Fscale_y = -SF``.
    * *LOAD_SHELL gives a pressure on a SHELL, positive "in the negative
      t-direction" (Manual Vol I R16 p.3421), i.e. INTO the top face. Pasting
      the shell connectivity makes ``n_hat = t_hat``, so exactly ONE flip is
      needed and it is applied as ``Fscale_y = -SF``. Reversing the node order
      as well would cancel it back out.

    The two rules are therefore the SAME rule, and until this round only the
    shell half applied it. MEASURED on ``3.1_Elastic_Beams_etc`` against its
    own LS-DYNA ``nodout`` (last displacement block, t = 1.0), one converted
    deck run twice with only the ``Fscale_y`` sign patched between the runs:

      =========================  ================  ================  ==========
      node                       WITHOUT the flip  WITH the flip     LS-DYNA
      =========================  ================  ================  ==========
      1 root, DX                 -8.258400E-03     8.405220E-03      8.430160E-03
                                 (**-197.96 %**)   (-0.30 %)
      21 hex tip, DZ             +1.066000E-01     -1.066000E-01     -1.062870E-01
                                 (**-200.29 %**)   (+0.29 %)
      64 tet tip, DZ             +1.065740E-01     -1.066400E-01     -1.062850E-01
                                 (**-200.27 %**)   (+0.33 %)
      1247 mid-span, DZ          +7.595400E-02     -7.600600E-02     -7.598150E-02
                                 (**-199.96 %**)   (+0.03 %)
      1320 shell tip, DZ         -1.064400E-01     -1.064400E-01     -1.057880E-01
                                 (+0.62 %)         (+0.62 %)
      =========================  ================  ================  ==========

    Node 1320 is loaded by ``*LOAD_NODE_POINT``, not by a pressure, and is
    IDENTICAL in both runs — which is what isolates the pressure path rather
    than blaming the whole model.
    """
    if not (state.pressure_loads or state.segment_set_pressure_loads
            or state.shell_pressure_loads):
        return []
    # Grouped by (lcid, fscale, at): one /SURF/SEG + one /PLOAD per distinct
    # load. `at` joins the key because it becomes a per-load /SENSOR/TIME.
    groups: Dict[Tuple, List[List[int]]] = defaultdict(list)
    seg_flipped = False
    for pl in state.pressure_loads:
        groups[(pl.lcid, -pl.sf, pl.at)].append(pl.nodes)
        seg_flipped = True
    # *LOAD_SEGMENT_SET: expand each referenced *SET_SEGMENT into per-segment
    # cards, grouped alongside *LOAD_SEGMENT by (lcid, sf).
    for ssl in state.segment_set_pressure_loads:
        segset = state.segment_sets.get(ssl.ssid)
        if segset is None:
            state.warn(f"*LOAD_SEGMENT_SET references *SET_SEGMENT {ssl.ssid}, "
                       "which is not defined — pressure load dropped.")
            continue
        if _part_scoped_segment_set(state, ssl.ssid, "*LOAD_SEGMENT_SET",
                                    "The pressure load is DROPPED."):
            continue
        for nodes in segset.segments:
            groups[(ssl.lcid, -ssl.sf, ssl.at)].append(list(nodes))
            seg_flipped = True
    # *LOAD_SHELL_ELEMENT / _SET: the sign flip is applied HERE, so the group key
    # already holds the emitted Fscale_y.
    flipped = False
    shells = ({e.eid: e for e in state.shell_elems}
              if state.shell_pressure_loads else {})
    for spl in state.shell_pressure_loads:
        eids = spl.eids
        if spl.ssid:
            sset = state.shell_sets.get(spl.ssid)
            if sset is None:
                state.warn(
                    f"{spl.source} references *SET_SHELL {spl.ssid}, which is "
                    "not defined — pressure load dropped.")
                continue
            eids = list(sset[1])
            if not eids:
                state.warn(f"{spl.source}: *SET_SHELL {spl.ssid} is empty — "
                           "pressure load dropped.")
                continue
        segs = _shell_load_segments(state, eids,
                                    f"{spl.source} lcid={spl.lcid}", shells)
        if not segs:
            continue
        flipped = True
        groups[(spl.lcid, -spl.sf, spl.at)].extend(segs)

    lines: List[str] = ["#-  PRESSURE LOADS:", HDR]
    pload_id = 1
    sensors_emitted = False
    for (lcid, sf, at), segs in groups.items():
        if sf == 0.0:
            # Unreachable from the handlers, which default SF = 0 to 1.0 — kept
            # because a /PLOAD carrying a zero ordinate scale is not a zero load
            # but a FULL-amplitude one: hm_read_pload.F:167 is
            # `IF (FCY == ZERO) FCY = FAC_FCY`, so the starter substitutes the
            # unit-system factor. Never let a literal 0 reach the card.
            state.warn(
                f"Pressure load on curve {lcid} resolved to Fscale_y = 0, which "
                "/PLOAD cannot express: hm_read_pload.F:167 replaces a zero "
                "ordinate scale with the unit-system factor, so the load would "
                "run at FULL amplitude. The load is DROPPED instead.")
            continue
        surf_id = state.next_id()
        lines += [
            f"/SURF/SEG/{surf_id}",
            f"PLOAD_{pload_id}_segments",
            "#   seg_ID        n1        n2        n3        n4",
        ]
        for seg_no, nodes in enumerate(segs, start=1):
            quad = (list(nodes) + [0, 0, 0, 0])[:4]
            lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
        sensor_id = 0
        if at > 0.0:
            # next_sensor_id, not next_id: *ELEMENT_SEATBELT_SENSOR puts USER
            # ids into the /SENSOR namespace, so a deck with an SBSID at or
            # above the auto-id base (90001) would otherwise collide here
            # (starter ERROR 79 over the /SENSOR table). A no-op vs next_id()
            # on any deck without one, so it shifts no existing id.
            sensor_id = state.next_sensor_id()
            sensors_emitted = True
            lines += _emit_sensor_time(sensor_id, f"PLOAD_{pload_id}_arrival", at)
        lines += _emit_pload_card(pload_id, f"PLOAD_{pload_id}", surf_id, lcid,
                                  sf, sensor_id, state=state)
        pload_id += 1
    if seg_flipped:
        state.warn(
            "*LOAD_SEGMENT[_SET] -> /PLOAD with Fscale_y = -SF. LS-DYNA's "
            "positive segment pressure acts along the NEGATIVE segment normal "
            "-- Vol I R17 p.33-107, Figure 33-12's caption is 'Positive "
            "pressure acts in the negative t-direction', with t the right-hand "
            "normal of the N1..N4 order -- while a /PLOAD with positive "
            "Fscale_y pushes the surface along its POSITIVE segment normal "
            "(force.F90:451-465 sums +P*A*n_hat). k2rad pastes the deck's node "
            "order into the /SURF/SEG verbatim, so n_hat = t_hat and exactly "
            "ONE flip is correct -- the same flip *LOAD_SHELL_* has always "
            "had. MEASURED on implicit/Salzburg_2017 3.1_Elastic_Beams_etc "
            "against its own LS-DYNA nodout, one converted deck run twice "
            "with only this cell's sign patched between the runs: WITHOUT the "
            "flip the hex cantilever tip (node 21) reads +1.066000E-01 "
            "against a reference -1.062870E-01, i.e. -200.29 % -- the right "
            "magnitude the wrong way -- and the tet tip, the mid-span node "
            "and the root DX are -200.27 %, -199.96 % and -197.96 %; WITH it "
            "they are +0.29 %, +0.33 %, +0.03 % and -0.30 %. The same deck's "
            "*LOAD_NODE_POINT-loaded shell tip (node 1320) is IDENTICAL in "
            "both runs at +0.62 %, which is what isolates the pressure path. "
            "If your deck was built against k2rad's previous behaviour, drop "
            "the minus sign from SF.")
    if flipped:
        state.warn(
            "*LOAD_SHELL_{ELEMENT,SET} -> /PLOAD with Fscale_y = -SF. LS-DYNA's "
            "positive pressure acts along the shell's NEGATIVE normal (Manual "
            "Vol I R16 p.3421: the connectivity follows the right-hand rule and "
            "\"positive pressure acts in the negative t-direction\"), while a "
            "/PLOAD with positive Fscale_y pushes the surface along its POSITIVE "
            "segment normal (force.F90:451-465 sums +P*A*n_hat). The /SURF/SEG "
            "is built by pasting the shell connectivity, so n_hat = t_hat and "
            "ONE flip is correct. Note the Radioss dyna-reader gets this wrong: "
            "ConvertLoadShell writes the value under the name 'Fscale_Y' while "
            "/PLOAD's attribute is 'Fscale_y', the solver-name map is "
            "case-sensitive (mv_descriptor.cpp:93), and the write is silently "
            "discarded — a dyna2rad-converted *LOAD_SHELL runs at Fscale_y = "
            "+1.0, losing SF and inverting the sign.")
    if sensors_emitted:
        state.warn(
            "Pressure-load arrival time AT > 0 -> /SENSOR/TIME with Tdelay = AT "
            "in the /PLOAD sens_ID column: the load is zero for t < AT and the "
            "curve is then evaluated at t - AT, i.e. the abscissa is SHIFTED, "
            "not merely gated (sensor_time.F:66-68 sets TSTART = TDELAY; "
            "force.F90:216-218 evaluates at ts = tt - TSTART). That matches the "
            "usual reading of LS-DYNA's arrival time and is what dyna2rad emits "
            "(convertloads.cxx:803-812) — but if your curve's abscissa is "
            "already absolute time, pre-shift it instead. k2rad <= PR #116 "
            "dropped AT on *LOAD_SEGMENT_SET entirely.")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Engine file sections
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_node_list(nids, cap: int = 20) -> str:
    """``[1, 2, 3]`` for a short list, ``[1, 2, …] and N more`` for a long one.

    ``mat_spring.belted-dummy.k`` has 122 springs; a warning that prints every
    node it touches is a warning nobody reads."""
    nids = sorted(nids)
    if len(nids) <= cap:
        return str(nids)
    return f"{nids[:cap]} and {len(nids) - cap} more"


def _spring_token_negative_admas(
        state: ConversionState, rigid_nodes: Set[int], compensated,
        degenerate) -> Tuple[Dict[float, List[int]], List[Tuple[int, float]],
                             List[Tuple[int, float, float]]]:
    """The nodes whose token share needs a NEGATIVE ``/ADMAS`` to come off.

    The shipped rule only ever SUBTRACTED from an ``/ADMAS`` the deck already
    states, so the classes that carry none got nothing — which on
    ``spotweld-ii/plates.nrbc.k`` is the whole defect: one token of 1e-4 against
    an LS-DYNA model mass of 1.0048e-4, i.e. the starter's ``TOTAL MASS`` read
    **2.0048E-04, +99.52 %**.

    ``hm_read_admas.F:161-171`` accepts a negative added mass — it raises only
    ``ANCMSG(MSGID=476, MSGTYPE=MSGWARNING)`` ``NEGATIVE ADDED MASS``, ONCE per
    card per read of the deck (the check at ``:164-165`` sits inside the
    ``IF (FLAG == 0)`` block opened at ``:160``, and ``lectur.F:7967-7979``
    calls ``HM_READ_ADMAS`` with ``FLAGG = 0`` and then ``FLAGG = 1``, so the
    second pass never reaches it; it is the file's only ``MSGID=476``) — and
    applies it algebraically at ``:247-248``
    (``MS(NOSYS) = MS(NOSYS) + AMAS``). There is
    no sign check and no floor, and ``/ADMAS`` is read at ``lectur.F:7969``,
    before the rigid bodies and before ``INITIA``, so the model total
    (``initia.F:2250``) is exactly LS-DYNA's again.

    THE SCREEN (round 6, A3 — the "S2" screen). A node is compensated iff it
    keeps mass of its OWN once the token is off: ``m_own + m_admas > 0``,
    where ``m_own`` is the ELEMENT mass the engine will hold there
    (``lumping.element_mass_by_node``: every emitted shell / solid / thick
    shell / beam, at the emitted thickness and at the density
    ``sph._mat_density`` reads from EVERY material container — 0.0 for a
    zero-density-floored material) and ``m_admas`` is the deck's own
    ``*ELEMENT_MASS`` on the node. The round-5 screen was an element-INCIDENCE
    test, which refused a node carrying only an ``*ELEMENT_MASS``
    (gnonspring.k: TOTAL MASS 1.02e-4 against LS-DYNA's 2.0e-6).

    WHY A NODE MUST NOT BE LEFT AT EXACTLY ZERO. Nothing catches it:
    ``chkmsin.F:53`` tests ``MS(N) < ZERO`` strictly (``resol.F:5460`` aborts
    only on that), and ``accele.F:67-80`` then writes ``A = 0`` for
    ``MS = 0`` — no NaN, the node silently keeps its velocity (a fixed point
    if it starts at rest). The starter's ERROR 1870 is not it either:
    ``rcheckmass.F:112``/``:123`` gate that branch on ``IGTYP==23`` with
    ``MTN==108``. ``m_own = m_admas = 0`` is therefore REFUSED (the token
    stays and the GUARDED sentence names the node).

    WHAT THE SCREEN CANNOT SEE: whether a node that keeps LESS mass than its
    share is still STABLE. The spring's own step uses the PROPERTY mass
    (``r1def3.F:113``, ``r1len3.F:175``), not the node's, so a compensated
    node on a near-massless shell can go unstable with no element step to
    stop it (the LIGHT clause names every such node; ROADMAP).

    Returns ``({share: [nid, ...]}, [(nid, share), ...],
    [(nid, m_own + m_admas, share), ...])`` — the groups to emit, the nodes
    the screen REFUSED, and the compensated nodes that keep less than their
    share. ONE mass computation, handed to the warning, never recomputed.
    """
    if not state.spring_token_mass_by_node:
        return {}, [], []
    if not state.options.spring_token_mass_compensation:
        return {}, [], []
    done = {nid for nid, _b, _s in compensated}
    want: Dict[int, float] = {}
    for nid, share in state.spring_token_mass_by_node.items():
        # `nid in done` = the share is already off the deck's own /ADMAS.
        # `nid not in state.nodes` is DEFENSIVE and no deck reaches it: every
        # registered node was written into a /SPRING row, and the synthesized
        # ground node is registered in state.nodes by _new_ground_node. It
        # stays because a /GRNOD naming a node the deck does not define is a
        # starter error, and a mutation of it is therefore a no-op rather than
        # an uncaught branch — probed with a *MAT_SPOTWELD beam on a missing
        # node, which the zero-length screen drops one level up.
        if share <= 0.0 or nid in done or nid not in state.nodes:
            continue
        if nid in state.connector_ground_nodes:
            continue                     # /BCS 111 111 — mass cannot act
        if nid in rigid_nodes:
            continue                     # measured inert; see the warning
        want[nid] = share
    # NOTE on the DEGENERATE class (a deck /ADMAS at or below the token share):
    # it needs NO pass of its own. Such a node is not in `done` — nothing was
    # subtracted from it — so the loop above already selected it, and the
    # deck's own /ADMAS value is kept by _make_added_masses while the FULL
    # share comes off here: m_own + m_admas + token - token. A second loop over
    # `degenerate` was written here and then removed as dead code; the
    # parameter is kept because _warn_spring_token_mass needs the list to
    # choose its wording.
    del degenerate
    if not want:
        return {}, [], []
    m_own = element_mass_by_node(state, set(want),
                                 lambda mid: _mat_density(state, mid))
    groups: Dict[float, List[int]] = {}
    guarded: List[Tuple[int, float]] = []
    light: List[Tuple[int, float, float]] = []
    for nid, share in sorted(want.items()):
        own = m_own.get(nid, 0.0) + state.added_node_masses.get(nid, 0.0)
        if own > 0.0:
            groups.setdefault(share, []).append(nid)
            if own < share:
                light.append((nid, own, share))
        else:
            guarded.append((nid, share))
    return groups, guarded, light


def _light_pair_clause(state: ConversionState,
                       light: List[Tuple[int, float, float]],
                       rigid_nodes: Set[int],
                       guarded: List[Tuple[int, float]]) -> str:
    """The LIGHT clause's per-pair numbers (round 7, A5 (iv); text only).

    For a light node n on a recorded spring s whose far end is f: the
    two-mass critical step ``2 sqrt(mu / K_t)`` with ``mu = m_n m_f /
    (m_n + m_f)`` (LS-DYNA Theory R16 eq. 26.25 / 26.27, the real nodal
    masses), against ``Tsca x`` the spring's OWN step ``dt_s = min(M /
    (sqrt(C_t^2 + M K_t) + C_t), I / (sqrt(C_r^2 + I K_r) + C_r))``
    (r1len3.F:175 for a TYPE4, r2len3.F:221-247 for a TYPE8 / TYPE13; both
    read the PROPERTY mass and inertia, never the node's), with K / C as
    :func:`_spring_kc` builds them - on a TYPE13 the rotational K includes
    the shear springs' K x L^2 (r4def3.F:173), which on the R14 spotweld
    plates makes the rotation the governing step. PROTECTED iff ``crit >=
    Tsca x dt_s``. ``m_n`` is the light node's own mass; ``m_f`` the far
    end's engine mass after compensation - its element mass plus its
    *ELEMENT_MASS (the compensation restores exactly that), or that plus
    the token share left on a GUARDED node, and infinite for a connector
    ground node, a rigid-body node or a node whose GLOBAL ``/BCS`` from the
    deck's own cards (:func:`_global_spc_dofs`: ``*BOUNDARY_SPC`` and the
    ``SF = 0`` prescribed motions) fixes all three translations. ``Tsca``
    is the deck's TSSFAC (0.9 when it states
    none). The two-mass form decided 8 of 8 cases of a boundary sweep right
    (the engine's limit between 2.05e-5 and 2.08e-5 against the closed form
    2.0668e-5). A spring with no translational stiffness is skipped (its
    pair has no translational critical step)."""
    if not light or not state.spring_token_springs:
        return ""
    ts = state.ctrl_timestep
    tsca = ts.tssfac if (ts and ts.tssfac and ts.tssfac > 0.0) else 0.9
    ends = {n for rec in state.spring_token_springs for n in rec[1:3]}
    m_el = element_mass_by_node(state, ends,
                                lambda mid: _mat_density(state, mid))
    fixed = {n for n, (tra, _rot) in _global_spc_dofs(state).items()
             if tra == "111"}
    guarded_share = dict(guarded)
    own_of = {n: own for n, own, _sh in light}
    inf = float("inf")

    def _far_mass(n: int) -> float:
        if (n in state.connector_ground_nodes or n in rigid_nodes
                or n in fixed):
            return inf
        if n in own_of:
            return own_of[n]
        m = m_el.get(n, 0.0) + state.added_node_masses.get(n, 0.0)
        return m + guarded_share.get(n, 0.0)

    pairs: List[Tuple[float, int, int, float, float, float]] = []
    # a light node whose own three translations are fixed cannot move, so it
    # has no critical step to compare (the post-review round: gnonspring's
    # node 1, *BOUNDARY_SPC_NODE 111111, printed UNPROTECTED); named HELD
    held: List[Tuple[int, int]] = []
    # round 8, A5: a spring whose two ends are both held or driven along it
    # for the whole run kept the token (the adaptive-token pass recorded it);
    # its light end is labelled DRIVEN, not compared (gnonspring's node 2)
    driven: List[Tuple[int, int]] = []
    for n, m_n, _sh in light:
        for eid, n1, n2, mass, inertia, k_t, k_r, c_t, c_r in \
                state.spring_token_springs:
            if n not in (n1, n2) or k_t <= 0.0:
                continue
            if n in fixed:
                held.append((n, eid))
                continue
            if eid in state.spring_token_both_driven:
                driven.append((n, eid))
                continue
            m_f = _far_mass(n2 if n == n1 else n1)
            mu = m_n if m_f == inf else m_n * m_f / (m_n + m_f)
            crit = 2.0 * math.sqrt(mu / k_t)
            dt_t = mass / (math.sqrt(c_t * c_t + mass * k_t) + c_t)
            dt_r = (inertia / (math.sqrt(c_r * c_r + inertia * k_r) + c_r)
                    if inertia > 0.0 and (k_r > 0.0 or c_r > 0.0) else inf)
            dt_s = min(dt_t, dt_r)
            pairs.append((crit / (tsca * dt_s), n, eid, crit, dt_s, mass))
    held_txt = "; ".join(
        f"node {n} on spring {eid}: HELD (its three translations are fixed "
        "by the deck's own *BOUNDARY_SPC or zero-scale prescribed motion, so "
        "it has no critical step to compare)" for n, eid in held[:5]) + (
        " ..." if len(held) > 5 else "")
    driven_txt = "; ".join(
        f"node {n} on spring {eid}: DRIVEN (both ends of spring {eid} are "
        "held along its axis for the whole run: bcs1.F:56-89 / "
        "fixvel.F:370-372 overwrite the acceleration there, so no "
        "instability can grow along it; the token is kept)"
        for n, eid in driven[:5]) + (" ..." if len(driven) > 5 else "")
    if held and driven:
        held_txt = held_txt + "; " + driven_txt
    elif driven:
        held_txt = driven_txt
    if not pairs:
        return " Per pair: " + held_txt + "." if held_txt else ""
    pairs.sort()

    def _prescribed(n: int) -> str:
        """A translation an imposed motion drives (gnonspring's node 2 is
        driven along its spring's axis): named beside the label."""
        dirs = sorted(d for d in state.imp_motion_dirs.get(n, ())
                      if d in ("X", "Y", "Z"))
        return (f" (its {'/'.join(dirs)} "
                f"{'is' if len(dirs) == 1 else 'are'} prescribed by an "
                "imposed motion)" if dirs else "")

    shown = "; ".join(
        f"node {n} on spring {eid}: {crit:.3g} s vs {tsca:g} x {dt_s:.3g} s"
        f" -> {'PROTECTED' if ratio >= 1.0 else 'UNPROTECTED'}"
        + _prescribed(n)
        for ratio, n, eid, crit, dt_s, _m in pairs[:5])
    if len(pairs) > 5:
        shown += " ..."
    if held_txt:
        shown += "; " + held_txt
    token = pairs[0][5]
    text = (
        " Per pair, the two-mass critical step 2 sqrt(mu / K) against Tsca x "
        "the spring's own step (r1len3.F:175 / r2len3.F:221-247, which read "
        "the PROPERTY mass and inertia; a TYPE13's rotational K includes its "
        "shear K x L^2, r4def3.F:173): " + shown + ". An UNPROTECTED node "
        "is stable only while the model's governing element step stays below "
        "its critical step; nothing else catches it: the run ends NORMAL "
        "TERMINATION with the energy ERROR column at 99.9 % (MEASURED on a "
        "four-spring coupon: node 20, own mass 1.96e-13, diverged in 6 cycles "
        "at nt 4 and 2; a two-mass sweep put the engine's limit between "
        "2.05e-5 and 2.08e-5 against the closed form 2.0668e-5). Remedies: an "
        "*ELEMENT_MASS that lifts mu above (Tsca^2 / 4) x M (M = the spring's "
        f"token mass {token:g}), /DT/NODA on the engine deck (the step then "
        "comes from the real nodal masses), or "
        "--no-spring-token-mass-compensation (keeps the token on the node).")
    if state.is_implicit:
        text += (" This deck runs implicit: no explicit element step applies, "
                 "the comparison is stated for an explicit run only.")
    return text


def _warn_spring_token_mass(state: ConversionState, rigid_nodes: Set[int],
                            compensated, degenerate, neg_groups=None,
                            guarded=None, light=None) -> None:
    """What happened to k2rad's own artificial spring mass, node by class.

    Four classes, and every one of them is named because the mass is INVENTED —
    LS-DYNA's discrete elements carry none (``*ELEMENT_DISCRETE`` has no mass
    cell at all; nodal mass comes from ``*ELEMENT_MASS``):

    * SUBTRACTED — the node has an ``/ADMAS`` big enough to take the token off.
    * DEGENERATE — it has one, but at or below the token share, so subtracting
      would write a non-positive ``/ADMAS``. The deck's own value is kept AND
      the full share comes off with a negative card (round 5). Under the
      round-6 own-mass screen that negative card is ALWAYS written: the
      deck's own ``*ELEMENT_MASS`` is mass of the node's own.
    * NO ``/ADMAS`` — nothing to subtract from. Since round 5 the token is
      REMOVED from these nodes with a negative ``/ADMAS`` instead
      (``hm_read_admas.F:164-170`` accepts one, WARNING ID 476), unless the
      own-mass screen refuses the node (``m_own + m_admas = 0``, see
      ``_spring_token_negative_admas``), which the GUARDED sentence names; a
      compensated node that keeps LESS than its share is named by the LIGHT
      clause. A fifth list, ``orphan``, catches a registered node that is not
      in ``state.nodes``: a deck FRAGMENT whose *NODE cards live in another
      file (two *INCLUDE fragments of C:/openradioss_run converted on their
      own reach it).
    * RIGID — the node is a SECONDARY node of a rigid body. Whether the token
      reaches that body at all depends on its ICoG; on the roster's only
      carrier it is measurably INERT (see below).

    Synthesized ground nodes are excluded: ``_emit_spring_part`` mints them
    fully ``/BCS``-fixed, so a mass on one cannot move anything.
    """
    if not state.spring_token_mass_by_node:
        return
    if not state.options.spring_token_mass_compensation:
        # The per-part warnings already said the token was left in place and
        # what it costs; one deck-level line would only repeat them.
        return
    neg_groups = neg_groups or {}
    guarded = guarded or []
    light = light or []
    # round 8, A5: where the adaptive token rewrote a /PROP the share a node
    # carries is no longer the fixed token's half, so the sentences below
    # name the share itself (and keep their fixed-token wording otherwise)
    adapted = bool(state.adaptive_token_changed)
    per_prop = (f"{_SPRING_TOKEN_MASS:g} per /PROP"
                + (", or the smaller MASS the adaptive token wrote on "
                   f"{len(state.adaptive_token_changed)} /PROP(s)"
                   if adapted else ""))

    def _left(nodes: List[int]) -> str:
        shown = ", ".join(
            f"node {n}: {state.spring_token_mass_by_node.get(n, 0.0):g}"
            for n in nodes[:5]) + (" ..." if len(nodes) > 5 else "")
        return f"the token share left on them ({shown})"

    done = {nid for nid, _b, _s in compensated}
    removed = {nid for nids in neg_groups.values() for nid in nids}
    bad = {nid for nid, _m, _s in degenerate}
    rigid: List[int] = []
    orphan: List[int] = []
    for nid in state.spring_token_mass_by_node:
        if nid in done or nid in bad or nid in removed:
            continue
        if nid in state.connector_ground_nodes:
            continue                     # /BCS 111 111 — mass cannot act
        if nid in {n for n, _s in guarded}:
            continue                     # named by its own sentence below
        (rigid if nid in rigid_nodes else orphan).append(nid)
    if compensated:
        total = sum(sh for _n, _b, sh in compensated)
        state.warn(
            f"*ELEMENT_DISCRETE: k2rad's token spring mass "
            f"({per_prop}, half on each end node per "
            f"element - rinit3.F:1926/1937-1939) was SUBTRACTED from the "
            f"/ADMAS of {len(compensated)} node(s) {_fmt_node_list(done)}, "
            f"{total:g} in total, so the model's mass and its natural "
            "frequencies are LS-DYNA's. (LS-DYNA discrete elements are "
            "massless; hm_read_prop04.F:136-142 refuses a property MASS "
            "<= 1e-15 with ERROR 229, which is why the token exists at all.) "
            "Pass --no-spring-token-mass-compensation to keep the "
            "pre-round-4 output.")
    if degenerate:
        detail = ", ".join(f"node {n}: /ADMAS {m:g} vs token share {sh:g}"
                           for n, m, sh in sorted(degenerate)[:5])
        deg_removed = sorted(n for n, _m, _s in degenerate if n in removed)
        # Under the round-6 own-mass screen a degenerate node always carries
        # m_admas > 0 (its own *ELEMENT_MASS), so it is always compensated and
        # this is the only arm left.
        tail = (
            f" The full share was taken off {len(deg_removed)} of them "
            f"{_fmt_node_list(deg_removed)} with a separate NEGATIVE /ADMAS "
            "instead, so their sum is exact (m_own + m_admas + token - token).")
        state.warn(
            f"*ELEMENT_DISCRETE: {len(degenerate)} node(s) carry LESS /ADMAS "
            "than k2rad's own token spring mass, so the deck's own /ADMAS "
            "value was KEPT (k2rad never writes a non-positive /ADMAS on "
            "the deck's own card - that is a k2rad policy, not a solver "
            "rule: hm_read_admas.F has no sign check at all): "
            f"{detail}"
            + (" ..." if len(degenerate) > 5 else "")
            + "." + tail
            + " MEASURED on the carrier of this shape, gnonspring.k "
              "(*ELEMENT_MASS 1e-6 on each end node against a token half of "
              "5e-5, 50x): TOTAL MASS 1.02e-4 -> 2.0e-6, which is LS-DYNA's "
              "(the two *ELEMENT_MASS), 786 cycles on both arms, IE 431.3 on "
              "both.")
    if neg_groups:
        nodes = sorted(n for nids in neg_groups.values() for n in nids)
        total = sum(sh * len(nids) for sh, nids in neg_groups.items())
        light_clause = ""
        if light:
            shown = ", ".join(f"node {n}: own {own:g} vs share {sh:g}"
                              for n, own, sh in sorted(light)[:5])
            light_clause = (
                f" {len(light)} of these node(s) keep LESS mass than the token "
                f"share they lost ({shown}"
                + (" ..." if len(light) > 5 else "")
                + "): the screen reads only whether a node has mass, not the "
                "spring's stiffness, so it cannot tell a stable light node "
                "from an unstable one. The spring's own step uses the "
                "PROPERTY mass (r1def3.F:113, r1len3.F:175), not the node's. "
                "MEASURED: stable on spotweld-ii/plates.nrbc (own 1.57e-6 "
                "against the share 5e-5; the /PROP/TYPE13 rotational step "
                "governs, dt 2.110e-7) and on a coupon node with own mass "
                "1.96e-7; UNSTABLE on the same coupon's node on a T 1e-6 "
                "shell (own mass 1.96e-13): IE 1.58e22 at cycle 7, a USER "
                "BREAK - and the engine still printed NORMAL TERMINATION. See "
                "ROADMAP (the per-spring stability rule)."
                + _light_pair_clause(state, light, rigid_nodes, guarded))
        state.warn(
            "*ELEMENT_DISCRETE/*CONSTRAINED_SPOTWELD: k2rad's own token "
            f"spring mass ({per_prop}, half on each end "
            "node per element - rinit3.F:1926/1937-1939) was REMOVED again "
            f"from {len(nodes)} node(s) {_fmt_node_list(nodes)} with a "
            f"NEGATIVE /ADMAS/0 of "
            + ", ".join(f"{-sh:g} x {len(nids)}"
                        for sh, nids in sorted(neg_groups.items()))
            + f", total {-total:g}, so the model's mass is LS-DYNA's. "
              "hm_read_admas.F:164-170 accepts a negative added mass (WARNING "
              "ID 476 NEGATIVE ADDED MASS, once per card per read of the deck "
              "- the check is inside the IF (FLAG == 0) block at :160, so the "
              "FLAGG=1 pass of lectur.F:7967-7979 never reaches it) and adds "
              "it algebraically at :247. A starter that runs a SECOND domain "
              "decomposition reads the deck again - lectur.F:9047-9048 sets "
              "IDDLEVEL = 1 and the GOTO 100 at :9094 jumps back to label "
              "100 at :5691 - and so reprints every warning raised inside "
              "that span, this one included. (A warning raised OUTSIDE the "
              "span still prints once: KINCHK is called at lectur.F:10568, "
              "so WARNING 312 does not double.) On plates.nrbc the deck's own "
              "pre-existing WARNING ID 1084 already appears twice on the arm "
              "that has no negative /ADMAS at all, and the dome deck, which "
              "runs no second decomposition, prints all nine of its warnings "
              "once. MEASURED on spotweld-ii/plates.nrbc (nt 4): the starter's "
              "TOTAL MASS goes 2.0048E-04 -> 1.0048E-04, which is LS-DYNA's "
              "own total mass to every printed digit (+99.52 % -> 0.00 %), at "
              "+1.21 % cycles (2646 -> 2678) and NORMAL TERMINATION."
            + light_clause
            + " Pass --no-spring-token-mass-compensation to keep the "
              "pre-round-5 output.")
    if guarded:
        state.warn(
            f"*ELEMENT_DISCRETE: {len(guarded)} spring node(s) "
            f"{_fmt_node_list(n for n, _s in guarded)} carry NO element mass "
            "of their own and no *ELEMENT_MASS, so k2rad's token was LEFT in "
            "place: subtracting it would leave them at EXACTLY zero mass, "
            "which nothing catches - chkmsin.F:52-59 prints NEGATIVE MASS ON "
            "NODE ID= only for MS < 0 (chkmsin.F:53; resol.F:5460 aborts on "
            "that), and accele.F:67-80 then writes A = 0 for MS = 0, so the "
            "node silently keeps its velocity (a fixed point if it starts at "
            "rest; MEASURED on a spring coupon: the unscreened node read "
            "DX = VX = AX = 0 for the whole run under NORMAL TERMINATION). The "
            "starter's ERROR 1870 is NOT it - rcheckmass.F:112/:123 gate that "
            "branch on IGTYP==23 with MTN==108, i.e. a /PROP/TYPE23 SPR_MAT "
            "spring on /MAT/LAW108, which k2rad never emits here. Their mass "
            "is HIGH by "
            + (_left(sorted(n for n, _s in guarded)) if adapted else
               f"{_SPRING_TOKEN_MASS / 2:g} per attached spring element")
            + "; give "
            "them an *ELEMENT_MASS if their dynamics matter - any positive "
            "*ELEMENT_MASS makes the node eligible, and the token then comes "
            "off. The screen is the node's OWN mass (its element mass at the "
            "emitted thickness and density, plus *ELEMENT_MASS), and a "
            "zero-density part counts as massless.")
    if orphan:
        # Since round 5 a spring node with no /ADMAS gets a NEGATIVE one, so
        # "no /ADMAS to subtract from" is no longer a terminal class. The
        # ONLY way into this list left is a registered node that is not in
        # state.nodes: _register_spring_token_mass refuses a share <= 0, and
        # done / bad / removed / connector_ground / guarded / rigid cover
        # every other node _spring_token_negative_admas selects. MEASURED
        # reach: the two *INCLUDE fragments set-yaris-detailed-v2j.key (16
        # nodes) and set-camry-detailed-v5a.key (10 nodes) of
        # C:/openradioss_run, converted on their own.
        state.warn(
            f"*ELEMENT_DISCRETE: {len(orphan)} spring node(s) "
            f"{_fmt_node_list(orphan)} were registered for k2rad's token "
            "spring mass but are NOT in the converted model's node set, so "
            "no /ADMAS - positive or negative - could be written for them "
            "and their mass is HIGH by "
            + (_left(sorted(orphan)) if adapted else
               f"{_SPRING_TOKEN_MASS / 2:g} per attached spring element")
            + ". The "
            "deck names these nodes but does not define them: it is a "
            "fragment whose *NODE cards live in another file - MEASURED: the "
            "*INCLUDE fragments set-yaris-detailed-v2j.key (16 nodes) and "
            "set-camry-detailed-v5a.key (10 nodes) of C:/openradioss_run, "
            "converted on their own, land here, and the /SPRING rows that "
            "name the nodes fail in the starter anyway. Convert the deck that "
            "includes the fragment.")
    if rigid:
        state.warn(
            f"*ELEMENT_DISCRETE: {len(rigid)} spring node(s) "
            f"{_fmt_node_list(rigid)} are SECONDARY nodes of a rigid body. "
            "Whether k2rad's token spring mass ("
            + (_left(sorted(rigid)) if adapted else
               f"{_SPRING_TOKEN_MASS / 2:g} per attached element")
            + ") reaches that "
            "body depends on its ICoG: with ICoG=4 inirby.F:265-266 (\"CG OF "
            "THE MAIN NODE (MASS OF SECONDS IGNORED)\", MASRB = MS(M)) the "
            "secondary nodes' mass is discarded, so the token - and any "
            "/ADMAS compensation of it - is INERT. MEASURED on "
            "mat_spring.belted-dummy (15 registered token nodes, 0.0108 in "
            "total, all on ICoG=4 bodies): the starter's TOTAL MASS is "
            "0.3356681850251 with the token, with the token at 1e-12, with a "
            "-0.0108 /ADMAS and with a +0.0108 /ADMAS, and the full engine run "
            "is 110032 cycles with bit-identical energies in every arm. On an "
            "ICoG 1/2/3 body the members' masses ARE summed "
            "(inirby.F:186-258) and the token would reach it - UNMEASURED, no "
            "roster carrier.")


#: The smallest MASS the adaptive token writes: hm_read_prop04.F:136-142
#: refuses a /PROP/TYPE4 MASS <= 1e-15 (ERROR 229), the floor the PLOTEL
#: mass already uses.
_ADAPTIVE_TOKEN_FLOOR = 1.1e-15


def _adaptive_spring_token(state: ConversionState, rigid_nodes: Set[int],
                           acc_lines: Optional[List[str]]) -> None:
    """The ADAPTIVE spring token MASS (R14 triage round 8, A5;
    ``--adaptive-spring-token``, default ON).

    WHY. A token ``/PROP`` (k2rad's 1e-4 on a massless LS-DYNA discrete
    element) steps on its PROPERTY mass: ``r1len3.F:175`` ``sqrt(M / K)`` for
    a TYPE4, ``r2len3.F:221-247`` for a TYPE8 / TYPE13 - never on the nodes'.
    The S2 screen then takes the token back off the end nodes, so a light
    compensated end can sit far below what that step assumes, and nothing
    stops it: no nodal step without ``/DT/NODA``, AMS or an emitted
    ``/INTER/TYPE2`` with Spotflag 25-28 (``intti1.F:258`` sets I7KGLO,
    which turns on ``dtnoda.F:661``'s nodal step), and the run diverges
    behind a NORMAL TERMINATION banner (measured on three coupons: the
    energy-error limit, MESSAGE 205, killed them within 3-6 cycles).
    LS-DYNA steps a discrete element on the REAL nodal masses (Theory R16
    eq. 26.27, the two-mass ``2 sqrt(mu / K)``).

    THE RULE. Per token ``/PROP`` (TYPE4 / TYPE8 / TYPE13, recorded by its
    producer in ``state.spring_token_props``; never a property whose mass is
    LS-DYNA's own ``RO A L``)::

        MASS := max(1.1e-15, min(current, min over its springs s of cap_s))
        cap_s = 2 mu_s min(1, 2 / n_s) / (L_s if Ileng 1 else 1)
        mu_s  = m_a m_b / (m_a + m_b)   (one end infinite -> the other end)
        n_s   = the larger token-spring count of its two end nodes

    ``m_e`` = the end's own mass as the S2 screen counts it (element mass +
    ``*ELEMENT_MASS``), or INFINITE for a rigid-body node, a connector ground
    node, or an end DRIVEN along the spring for the WHOLE run: its GLOBAL
    fixed or imposed translations (``_global_spc_dofs`` = the deck's
    ``*BOUNDARY_SPC`` + the ``SF = 0`` motions, the emitted ``*NODE`` TC /
    ``*CONSTRAINED_GLOBAL`` codes, and every skew-0 ``/IMP*`` direction whose
    window is the whole run - ``state.imp_motion_windows``: sensor 0,
    ``tstart <= 0``, ``tstop`` 0 or at / after ENDTIM) cover the spring's stiff
    directions - on a TYPE4 every axis component on a FREE direction is at
    most 1e-6 (a zero-length spring: all three), on a TYPE8 / TYPE13 all
    three. NOT driven: a skewed SPC, a local-system motion, a windowed or
    sensor-gated motion, a tied secondary node. A spring with both ends
    infinite sets no cap (the token is kept; with a driven end it is
    recorded in ``state.spring_token_both_driven`` for the LIGHT clause's
    DRIVEN label); a GUARDED end (own mass 0, not driven) sets no cap
    either - the S2 screen leaves its token in place. ONE MASS per ``/PROP``
    (decision D7): a guarded spring sharing a rewritten ``/PROP`` carries
    its smaller MASS, and W-A5 says so.

    A ``/PROP`` whose printed MASS is not the token its springs registered -
    a token weld whose ``*MAT_SPOTWELD`` DT raised it (A6, decision D11) - is
    left alone: its step is already 0.9 DT, and the raised part stays on its
    end nodes as LS-DYNA's own added mass.

    HOW. The MASS cell of each moving ``/PROP`` is rewritten in the already
    emitted lines (located by its exact ``/PROP/TYPEn/<id>`` header, the
    comment row and the old value ASSERTED - a k2rad bug raises, never a
    silent skip), printed with ``_f``; the shares in
    ``state.spring_token_mass_by_node`` and the spring records are then
    moved by the PRINTED value, so the S2 compensation that runs next
    removes exactly what ``rinit3.F:1926/1937-1939`` adds. Inert under
    ``--no-spring-token-mass-compensation``; ``--no-adaptive-spring-token``
    keeps the fixed token (4f5b6e8 bytes).
    """
    state.spring_token_both_driven = set()
    state.adaptive_token_changed = {}
    if not (state.options.adaptive_spring_token
            and state.options.spring_token_mass_compensation):
        return
    if not state.spring_token_springs or not state.spring_token_props:
        return
    if acc_lines is None:
        return
    inf = float("inf")
    recs = state.spring_token_springs
    props = state.spring_token_props
    ends = {n for rec in recs for n in rec[1:3] if n > 0}
    m_el = element_mass_by_node(state, ends,
                                lambda mid: _mat_density(state, mid))
    count: Dict[int, int] = {}
    for rec in recs:
        for n in rec[1:3]:
            if n > 0:
                count[n] = count.get(n, 0) + 1
    held: Dict[int, Set[int]] = {}

    def _hold(nid: int, tra: str) -> None:
        got = held.setdefault(nid, set())
        for k, ch in enumerate(tra[:3]):
            if ch == "1":
                got.add(k)

    for nid, (tra, _rot) in _global_spc_dofs(state).items():
        _hold(nid, tra)
    for nid, (tra, _rot) in state.node_tc_rc_emitted.items():
        _hold(nid, tra)
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 0.0
    for nid, wins in state.imp_motion_windows.items():
        for d, t0, t1, sensor in wins:
            if d not in ("X", "Y", "Z") or sensor or t0 > 0.0:
                continue
            if t1 != 0.0 and not (endtim > 0.0 and t1 >= endtim):
                continue
            held.setdefault(nid, set()).add("XYZ".index(d))

    def _axis(a: int, b: int) -> Optional[Tuple[float, float, float]]:
        na, nb = state.nodes.get(a), state.nodes.get(b)
        if na is None or nb is None:
            return None
        d = (nb.x - na.x, nb.y - na.y, nb.z - na.z)
        ln = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        if ln <= 0.0:
            return None
        return (d[0] / ln, d[1] / ln, d[2] / ln)

    def _end(n: int, ptype: str,
             axis: Optional[Tuple[float, float, float]]) -> Tuple[float, str]:
        """``(mass counted, why)``: why is '', 'ground', 'rigid', 'driven'
        or 'guarded'."""
        if n <= 0 or n in state.connector_ground_nodes:
            return inf, "ground"
        if n in rigid_nodes:
            return inf, "rigid"
        c = held.get(n)
        if c:
            if ptype == "TYPE4" and axis is not None:
                if all(abs(axis[k]) <= 1.0e-6 for k in range(3)
                       if k not in c):
                    return inf, "driven"
            elif c >= {0, 1, 2}:
                return inf, "driven"
        own = m_el.get(n, 0.0) + state.added_node_masses.get(n, 0.0)
        if own <= 0.0:
            return 0.0, "guarded"
        return own, ""

    cap_of: Dict[int, float] = {}
    springs_of: Dict[int, List[int]] = {}
    guarded_idx: Set[int] = set()
    for idx, rec in enumerate(recs):
        prop = props.get(idx)
        if prop is None:
            continue
        pid, ptype, ileng, length = prop
        springs_of.setdefault(pid, []).append(idx)
        n1, n2 = rec[1], rec[2]
        axis = _axis(n1, n2)
        m1, why1 = _end(n1, ptype, axis)
        m2, why2 = _end(n2, ptype, axis)
        if "guarded" in (why1, why2):
            guarded_idx.add(idx)
            continue
        if m1 == inf and m2 == inf:
            if "driven" in (why1, why2):
                state.spring_token_both_driven.add(rec[0])
            continue
        mu = m2 if m1 == inf else (m1 if m2 == inf else m1 * m2 / (m1 + m2))
        cap = 2.0 * mu * min(1.0, 2.0 / max(count.get(n1, 1),
                                            count.get(n2, 1)))
        if ileng == 1 and length > 0.0:
            cap /= length
        cap_of[pid] = min(cap_of.get(pid, inf), cap)
    if not cap_of:
        return
    # the emitted /PROP blocks: header, title, comment, the MASS row
    where: Dict[int, int] = {}
    want = {f"/PROP/{props[springs_of[pid][0]][1]}/{pid}": pid for pid in cap_of}
    for i, ln in enumerate(acc_lines):
        pid_hit = want.get(ln)
        if pid_hit is not None:
            assert pid_hit not in where, f"two {ln} blocks"
            where[pid_hit] = i + 3
    changed: Dict[int, Tuple[float, float]] = {}
    for pid in sorted(cap_of):
        j = where.get(pid)
        assert j is not None and j < len(acc_lines), (
            f"adaptive token: /PROP {pid} was registered but not emitted")
        assert acc_lines[j - 1].startswith("#"), acc_lines[j - 1]
        old = float(acc_lines[j][:20])
        # the printed cell must BE the token its springs registered (x L on
        # Ileng 1): a DT-raised token weld (A6) is left alone
        if any(abs(old * (props[k][3] if props[k][2] == 1 else 1.0)
                   - recs[k][3]) > 1.0e-9 * recs[k][3]
               for k in springs_of[pid]):
            continue
        new = max(min(old, cap_of[pid]), _ADAPTIVE_TOKEN_FLOOR)
        if not new < old * (1.0 - 1.0e-9):
            continue
        txt = _f(new)
        acc_lines[j] = txt + acc_lines[j][20:]
        changed[pid] = (old, float(txt))
    if not changed:
        return
    state.adaptive_token_changed = dict(changed)
    n_guarded = 0
    for pid, (_old, newp) in changed.items():
        for k in springs_of[pid]:
            rec = recs[k]
            _p, _t, ileng, length = props[k]
            new_pm = newp * (length if ileng == 1 else 1.0)
            dsh = 0.5 * (new_pm - rec[3])
            for n in rec[1:3]:
                if n > 0:
                    state.spring_token_mass_by_node[n] = (
                        state.spring_token_mass_by_node.get(n, 0.0) + dsh)
            recs[k] = (rec[0], rec[1], rec[2], new_pm, rec[4], rec[5], rec[6],
                       rec[7], rec[8])
            if k in guarded_idx:
                n_guarded += 1
    _warn_adaptive_spring_token(state, changed, springs_of, n_guarded)


def _warn_adaptive_spring_token(state: ConversionState,
                                changed: Dict[int, Tuple[float, float]],
                                springs_of: Dict[int, List[int]],
                                n_guarded: int) -> None:
    """W-A5: one sentence per deck where a token MASS cell moved."""
    inf = float("inf")
    low_pid = min(changed, key=lambda p: (changed[p][1], p))
    low_dt = inf
    for k in springs_of[low_pid]:
        _e, _a, _b, mass, inertia, k_t, k_r, c_t, c_r = \
            state.spring_token_springs[k]
        dt_t = (mass / (math.sqrt(c_t * c_t + mass * k_t) + c_t)
                if k_t > 0.0 or c_t > 0.0 else inf)
        dt_r = (inertia / (math.sqrt(c_r * c_r + inertia * k_r) + c_r)
                if inertia > 0.0 and (k_r > 0.0 or c_r > 0.0) else inf)
        low_dt = min(low_dt, dt_t, dt_r)
    shown = ", ".join(f"{p}: {o:g} -> {n:.7g}"
                      for p, (o, n) in sorted(changed.items())[:8])
    if len(changed) > 8:
        shown += ", ..."
    n_both = len(state.spring_token_both_driven)
    state.warn(
        "*ELEMENT_DISCRETE / *CONSTRAINED_SPOTWELD spring token: MASS set from "
        f"the end-node masses on {len(changed)} /PROP(s) ({shown}): min(1e-4, "
        "2 m_a m_b / (m_a + m_b) x min(1, 2/n)), n the busier end's "
        "token-spring count, per unit length on an Ileng 1 property, floor "
        "1.1e-15; a rigid, ground or DRIVEN end (held or imposed along the "
        "spring for the whole run) counts infinitely heavy, so the spring's "
        "own step sqrt(M/K) (r1len3.F:175; r2len3.F:221-247 on a TYPE8 / "
        "TYPE13, both on the PROPERTY mass) stays inside LS-DYNA's two-mass "
        "step on the real nodal masses (Theory R16 eq. 26.27). "
        f"{n_both} spring(s) with both ends driven kept the token. A skewed "
        "SPC, a local, windowed or sensor-gated motion and a tied end are NOT "
        f"driven. {n_guarded} guarded spring(s) (an end with no own mass) "
        "share a rewritten /PROP and carry its smaller MASS. The token still "
        "comes off both ends exactly (the shares follow the PRINTED value). "
        f"Smallest MASS {changed[low_pid][1]:.7g} on /PROP {low_pid} -> spring "
        f"step {low_dt:.3g} s. MEASURED (nt 4): the fixed token was killed "
        "by the engine's energy-error limit (MESSAGE 205) within 3-6 cycles "
        "on three coupons, each behind a NORMAL TERMINATION banner (D4 at "
        "cycle 3, D2 at 5, i14 at 6 with IE 1.578e22); the rule runs D2 / "
        "D4 4970 cycles and i14 50163 cycles, IE + KE 499.96 of the "
        "launched 500. "
        "--no-adaptive-spring-token keeps the fixed token (round 8).")


def _make_added_masses(state: ConversionState, rigid_nodes: Set[int],
                       acc_lines: Optional[List[str]] = None) -> List[str]:
    """*ELEMENT_MASS lumped masses on ORDINARY nodes → /ADMAS/0.

    *acc_lines* = the starter lines emitted so far (round 8, A5): the
    adaptive spring token (:func:`_adaptive_spring_token`) runs FIRST and
    rewrites the token /PROP MASS cells there, before the S2 compensation
    below reads the shares.

    state.added_node_masses holds every *ELEMENT_MASS nodal mass. A mass on an
    /RBODY MAIN node (or on any member of an ICoG-4 body) is accounted for in
    the /RBODY Mass field (_make_rbodies / _make_cnrb_rbodies), so /ADMAS is
    not emitted there. Since round 8 (A8, --rigid-element-mass-admas) a mass
    on a rigid SECONDARY node IS emitted here, on its node: the starter counts
    it at its position (centre of mass and inertia), where the fold put it at
    the body's main node and a CNRB secondary's mass was dropped; the opt-out
    restores the old rule (every rigid node skipped). /ADMAS/0 adds its Mass value to
    EACH node of the referenced /GRNOD, so nodes are grouped by identical mass
    value (one /GRNOD + /ADMAS/0 per distinct value). Before this, ordinary-node
    *ELEMENT_MASS was silently dropped (writer consumed added_node_masses only
    for rigid masters) — a real mass/dynamics error on any deck with point masses.
    """
    _adaptive_spring_token(state, rigid_nodes, acc_lines)
    compensated: List[Tuple[int, float, float]] = []     # (nid, before, share)
    degenerate: List[Tuple[int, float, float]] = []      # (nid, m_node, share)
    masses_by_value: Dict[float, List[int]] = {}
    skipped_rigid = 0
    # round 8, A8 (--rigid-element-mass-admas): only the masses an /RBODY
    # Mass field keeps (main nodes, ICoG-4 members) are skipped; a mass on a
    # rigid SECONDARY node is written here, on its node
    a8 = state.options.rigid_element_mass_admas
    skip = state.rbody_folded_mass_nodes if a8 else rigid_nodes
    moved: Dict[int, Tuple[int, str]] = {}
    for nid, mass in state.added_node_masses.items():
        if mass <= 0 or nid not in state.nodes:
            continue
        if nid in skip:
            skipped_rigid += 1          # folded into its /RBODY already
            continue
        if a8 and nid in rigid_nodes:
            moved[nid] = state.rbody_secondary_masses.get(nid, (0, "dropped"))
            masses_by_value.setdefault(mass, []).append(nid)
            continue                    # a rigid end is never compensated (S2)
        share = state.spring_token_mass_by_node.get(nid, 0.0)
        if share > 0.0 and state.options.spring_token_mass_compensation:
            if mass - share > 0.0:
                compensated.append((nid, mass, share))
                mass = mass - share
            else:
                # NEVER a non-positive /ADMAS. gnonspring.k is the carrier:
                # 1e-6 of stated nodal mass against a token half of 5e-5, 50x.
                # The deck's own number is kept here and the FULL share comes
                # off below on a negative card of its own, so the sum is exact.
                degenerate.append((nid, mass, share))
        masses_by_value.setdefault(mass, []).append(nid)
    # The classes the SUBTRACTION above cannot reach — a node with no
    # *ELEMENT_MASS has no /ADMAS to take the token off, and the loop above
    # never even visits it (it iterates state.added_node_masses).
    neg_groups, guarded, light = _spring_token_negative_admas(
        state, rigid_nodes, compensated, degenerate)
    _warn_spring_token_mass(state, rigid_nodes, compensated, degenerate,
                            neg_groups, guarded, light)
    if not masses_by_value and not neg_groups:
        return []
    lines: List[str] = []
    n_nodes = 0
    total = 0.0
    if masses_by_value:
        lines += [HDR,
                  "#-  ADDED MASSES (*ELEMENT_MASS on ordinary nodes"
                  + (" and rigid-body secondary nodes" if moved else "")
                  + "):"]
        for mass, nids in sorted(masses_by_value.items()):
            nids = sorted(nids)
            n_nodes += len(nids)
            total += mass * len(nids)
            grnod_id = state.next_grnod_id()
            lines += _emit_grnod_node(grnod_id, f"added_mass_{mass:g}_nodes",
                                      nids)
            admas_id = state.next_id()
            lines += [
                f"/ADMAS/0/{admas_id}",
                f"added_mass_{mass:g}",
                "#               MASS   grnd_ID",
                f"{_f(mass)}{_i(grnod_id)}",
                HDR,
            ]
    # ... then the negative cards, AFTER the positive block so a deck with no
    # token to compensate keeps its id stream byte-identical.
    if neg_groups:
        lines += [
            HDR,
            "#-  SPRING TOKEN MASS COMPENSATION (negative /ADMAS - "
            "hm_read_admas.F:164-170/:247):",
        ]
        for share, nids in sorted(neg_groups.items()):
            nids = sorted(nids)
            grnod_id = state.next_grnod_id()
            lines += _emit_grnod_node(
                grnod_id, f"spring_token_compensation_{share:g}", nids)
            admas_id = state.next_id()
            lines += [
                f"/ADMAS/0/{admas_id}",
                f"spring_token_compensation_{-share:g}",
                "#               MASS   grnd_ID",
                f"{_f(-share)}{_i(grnod_id)}",
                HDR,
            ]
    if n_nodes:
        n_ord = n_nodes - len(moved)
        note = (f"*ELEMENT_MASS: emitted /ADMAS/0 for {n_ord} ordinary "
                f"node(s)" + (f" and {len(moved)} rigid-body SECONDARY "
                              "node(s)" if moved else "")
                + f" (total added mass {total:g}).")
        if skipped_rigid:
            note += (f" {skipped_rigid} mass(es) on rigid-body nodes were left "
                     "to the /RBODY (" + ("main-node mass folded into its Mass "
                                          "field" if a8 else
                                          "master-node mass is folded into its "
                                          "Mass field") + ").")
        state.warn(note)
    if moved:
        _warn_rigid_secondary_element_mass(state, moved)
    return lines


def _warn_rigid_secondary_element_mass(state: ConversionState,
                                       moved: Dict[int, Tuple[int, str]]
                                       ) -> None:
    """W-A8 (round 8): the *ELEMENT_MASS on rigid SECONDARY nodes that is
    now /ADMAS on its node - named with what the previous converter did."""
    nodes = sorted(moved)
    bodies = sorted({b for b, _h in moved.values()})
    folded = [n for n in nodes if moved[n][1] == "folded"]
    dropped = [n for n in nodes if moved[n][1] != "folded"]
    was = []
    if folded:
        was.append(f"folded into the /RBODY Mass field at the centre of mass "
                   f"({len(folded)}, *MAT_RIGID part bodies)")
    if dropped:
        was.append(f"being DROPPED ({len(dropped)}: *CONSTRAINED_NODAL_RIGID_"
                   "BODY secondaries, or part bodies under "
                   "--no-rigid-cog-master)")
    state.warn(
        f"*ELEMENT_MASS: {len(nodes)} nodal mass(es) on {len(bodies)} rigid "
        f"body/bodies sit on SECONDARY nodes (node {_named(nodes)}); they are "
        "written as /ADMAS on their nodes, where the starter counts them at "
        "their position, instead of " + " or ".join(was) + " as before round "
        "8. LS-DYNA keeps a discrete mass at its node: on sph/foam/foam.k the "
        "body's CoG moves z 121.4891 -> 150.9633 and xx / yy 1.922978 -> "
        "2.238421 (LS-DYNA 150.96326 / 2.238), mass unchanged; a mass on a "
        "*CONSTRAINED_NODAL_RIGID_BODY secondary was LOST before (Yaris roof "
        "crush CNRB 2300387: LS-DYNA 2.3367e-4 vs 3.3799e-5). "
        "--no-rigid-element-mass-admas restores the previous fold (and drop).")


def _make_tied_nodes_failure_notes(state: ConversionState) -> List[str]:
    """ONE warning per deck for every ``*CONSTRAINED_TIED_NODES_FAILURE``
    card (R14 triage round 6, A4) — a note-only section: it returns ``[]``
    and draws no id.

    The card is refused BY NAME (``handlers.handle_constrained_tied_nodes_
    failure``): LS-DYNA releases each coincident group on the volume-weighted
    plastic strain of the surrounding elements, and no OpenRadioss tie reads
    an element's strain. Run as a writer section rather than in the handler
    because the message needs every card's count and every node set, known
    only after dispatch. The four arms measured on ``contact.n2s-sphere`` are
    quoted so the reader can see why none of them is written.
    """
    cards = state.tied_nodes_failures
    if not cards:
        return []
    hist: Dict[float, int] = {}
    etypes: Set[int] = set()
    nodes: Set[int] = set()
    undefined = 0
    pid_form: List[int] = []
    for nsid, eppf, etype, pid in cards:
        hist[eppf] = hist.get(eppf, 0) + 1
        etypes.add(etype)
        if pid > 0:
            pid_form.append(pid)
        ns = state.node_sets.get(nsid) if nsid > 0 else None
        if ns is None:
            if nsid > 0 or pid <= 0:
                undefined += 1
            continue
        nodes.update(n for n in ns[1] if n > 0)
    n = len(cards)
    eppf_txt = ", ".join(f"{e:g} x{k}" for e, k in sorted(hist.items()))
    tail = ""
    if undefined:
        tail += (f" ({undefined} card(s) name a node set the deck does not "
                 "define.)")
    if pid_form:
        tail += (f" {len(pid_form)} card(s) use the PID form, which asks "
                 f"LS-DYNA to split part(s) {sorted(set(pid_form))} into free "
                 "elements first - k2rad converts that part as ONE connected "
                 "mesh, i.e. never separated.")
    state.warn(
        f"*CONSTRAINED_TIED_NODES_FAILURE: {n} card(s) tying {len(nodes)} "
        f"nodes in {n} coincident group(s) (EPPF {eppf_txt}; ETYPE "
        f"{', '.join(str(e) for e in sorted(etypes))}) are NOT converted, so "
        "the elements they join are NOT connected at those nodes. LS-DYNA "
        "keeps each group tied until the volume-weighted plastic strain (or "
        "volume strain / damage, by material) of the surrounding elements "
        "exceeds EPPF and then releases the nodes of the elements that "
        "exceed it (Vol I R17 p.10-226/227, Remark 1). No OpenRadioss tie "
        "reads an element's strain: /RBODY Ifail 1 fails on a force "
        "(rgbodv.F:248-267, rbyonf.F:490-498), /INTER/TYPE2 Spotflag 20-22 "
        "on its own separation (ruptint2.F:138-151), and /SENSOR has no "
        "element-strain type (hm_read_sensors.F:175-250). MEASURED on "
        "contact.n2s-sphere (nt 4, against LS-DYNA, which released 78 of the "
        "841 ties - 5/65/8/0 by EPPF 0.0212/0.085/0.125/0.5 - and eroded "
        "nothing): left untied, as here, IE -71.8 % / KE +10.6 %; merged "
        "permanently, IE +333 %; tied by /RBODY with a force failure, IE "
        "-57 % to +117 % depending on the chosen force scale (diverged at "
        "4x), with bulk-class releases LS-DYNA never makes; an erosion "
        "emulation (a /FAIL per EPPF class) IE -16.9 % but 92 of 900 "
        "elements deleted that LS-DYNA keeps. None of these is the LS-DYNA "
        "rule, so none is written." + tail)
    return []


#: The /MPC data-row comment (radioss110/RBODY/mpc.cfg, FORMAT(radioss90)).
_MPC_ROW_HDR = "#  node_ID      Idof   skew_ID               alpha"


#: The explanation of each /MPC refusal reason, printed ONCE per card after
#: the per-term clauses that name the nodes.
_MPC_REFUSAL_NOTES = {
    "dof": "DOF 7 is the piezoelectric voltage (Vol I R17 p.10-136) and has "
           "no /MPC DOF; an /MPC row takes DOF 1-6 only",
    "coef": "the manual requires a non-zero COEF, and hm_read_mpc.F:124 "
            "would read 0 as 1",
    "cid": "no /SKEW of that id is written (starter ERROR 137)",
    "rigid": "the manual forbids rigid bodies in a constraint equation on the "
             "explicit solver, and the /RBODY would overwrite the node's "
             "motion",
    "mass": "lag_mpc.F divides by the nodal mass",
    "inertia": "lag_mpc.F divides by the nodal rotary inertia IN, which only a "
               "shell or a beam carries",
    "kin": "two kinematic conditions on one DOF are starter WARNING 312 "
           "(round 5's joint-screw arm measured an energy error of -30.8 % "
           "with one)",
    "twice": "the same node AND DOF may not carry two constraint equations "
             "(the WARNING box of Vol I R17 p.10-135 / p.10-139 forbids an "
             "explicit-solver node in two equations at all and allows the "
             "implicit solver to put equations on different DOFs of one "
             "node; the /MPC rows are solved by Lagrange multipliers, "
             "resol.F:7880 -> lag_mult.F, so this screen refuses only the "
             "repeated node-DOF pair and writes a node that two cards "
             "constrain on DIFFERENT DOFs)",
    "tied": "a tied-interface secondary node may not carry a constraint "
            "equation - Vol I R17 p.10-135 / p.10-139 (the explicit-solver "
            "WARNING box names tied interfaces); MEASURED on two hand-built "
            "two-plate probes at nt 4: a kinematic tie (Spotflag 0, 1 or "
            "k2rad's rupture 21) gives starter WARNING 312 and NaN from "
            "cycle 0 under NORMAL TERMINATION, and Spotflag 28 - which the "
            "starter switches to a penalty tie for that node (WARNING 1179, "
            "itagsl2.F:92 / :99-104) - still ends NORMAL with a 99.9 % "
            "energy error, with a CONFLICTING /MPC (IE 6237 against external "
            "work 44.35) and with a REDUNDANT one (0.1 % at cycle 1000, "
            "19.6 % at 3000): the redundant term is not redundant on "
            "Spotflag 28, because the tie point follows its main facet's "
            "rigid fit (i2vit3.F:386-389), so the term reaches the main "
            "nodes - and a plain /INTER/TYPE2 is outside the Lagrange "
            "system (lag_ntag.F:131): INTTI2 overwrites the secondaries "
            "(resol.F:7675) before LAG_MULT corrects the main nodes "
            "(:7901); no Spotflag is exempt",
    "tied_main": "a node of a tied interface's MAIN side may not carry one "
                 "either - the same WARNING box names tied-interface "
                 "MEMBERS, not one side; MEASURED (nt 4 = nt 2) on the same "
                 "two-plate probe: an /MPC between two main-plate nodes ends "
                 "NORMAL at a 99.9 % energy error from cycle 1000 on the "
                 "Spotflag-28 tie (IE 1.25e6 against external work -3.9) and "
                 "on the Spotflag-27 tie (IE 3.83e4 against 48.2), and "
                 "between two main-plate nodes at x 5, outside the tied "
                 "strip x 10..20, at 99.9 % from cycle 3000 (IE 1.80e6 "
                 "against 196), while the tie without the /MPC (IE 20.27 "
                 "against 20.28) and the /MPC on two plate-B nodes outside "
                 "the tie (20.35 against 20.36) balance; the main side is "
                 "the MSID side's nodes, which for a part side includes a "
                 "solid's interior nodes (an over-approximation that can only "
                 "refuse more); the mechanism, READ from the code order (not "
                 "instrumented): a plain /INTER/TYPE2 is outside the Lagrange "
                 "system (lag_ntag.F:131 admits a TYPE2 only when IPARI(33) "
                 "= 1, which only /INTER/LAGMUL/TYPE2 sets), and every cycle "
                 "INTTI2 (resol.F:7675) overwrites each kinematic secondary's "
                 "velocity and acceleration with its main facet's motion "
                 "(i2vit3.F:504-509 / :810-815) before LAG_MULT (resol.F:7901) "
                 "corrects the main node - a non-zero multiplier on a main "
                 "node never reaches the secondaries on its facets, and the "
                 "next reset creates energy. MEASURED on second geometries "
                 "(nt 4 = nt 2, window 0..3 ms): two solid blocks, an /MPC on "
                 "two main nodes, IE 4.005e4 against external work 306.1 "
                 "(x130.9) on Spotflag 28 and 1.899e4 against 375.7 (x50.54) "
                 "on Spotflag 27; a shell edge tied to a solid face x1983 on "
                 "Spotflag 27; a term between a secondary and nodes outside "
                 "every tie balances (-0.01 % with the tie's contact energy "
                 "counted)",
}


def _constrained_linear_refusals(
        state: ConversionState, lin,
        gspc: Dict[int, Tuple[str, str]], tcrc: Dict[int, Tuple[str, str]],
        skew_spc: Dict[int, Tuple[str, str]], rigid: Set[int],
        trans_nodes: Set[int], rot_nodes: Set[int], skews: Set[int],
        used: Set[Tuple[int, int]],
        tied: Optional[Dict[int, Tuple[int, int]]] = None,
        tied_main: Optional[Dict[int, Tuple[int, int]]] = None) -> List[str]:
    """Every reason one ``*CONSTRAINED_LINEAR_*`` card cannot be written as
    an ``/MPC`` — empty when it can. One clause per term that fails, then the
    explanation of each reason ONCE. PURE: no id is drawn, nothing is
    written, so a refused card leaves the deck byte-identical to the
    ``--no-constrained-linear`` arm.

    *tied* maps every SECONDARY node of an emitted ``/INTER/TYPE2`` to
    ``(inter_id, Spotflag)`` (round 7, B4; built from
    ``state.type2_secondary``) and *tied_main* every node of its MAIN side
    (the post-review round; built from ``state.type2_main_side``): a term on
    either is refused whatever the Spotflag. Round 7 first screened the
    secondary side only, reasoning from the starter's tag loop
    (``itagsl2.F:95-96``), which decides the penalty switch and is no
    stability argument; the main-side probe then measured the same 99.9 %
    energy error (``_MPC_REFUSAL_NOTES["tied_main"]``)."""
    tied = tied or {}
    tied_main = tied_main or {}
    why: List[str] = []
    notes: List[str] = []

    def add(clause: str, note: str) -> None:
        why.append(clause)
        if note not in notes:
            notes.append(note)

    if not lin.terms:
        why.append("the card states no term")
    seen: Set[Tuple[int, int]] = set()
    for nid, dof, cid, coef in lin.terms:
        if dof < 1 or dof > 6:
            add(f"node {nid}: " + ("DOF 7 (the piezoelectric voltage)"
                                   if dof == 7 else
                                   "no DOF stated" if dof == 0 else
                                   f"DOF {dof}"), "dof")
            continue
        if coef == 0.0:
            add(f"node {nid} DOF {dof}: COEF 0", "coef")
        if nid not in state.nodes:
            why.append(f"node {nid} is not defined")
            continue
        if cid > 0 and cid not in skews:
            add(f"node {nid}: CID {cid} is not a *DEFINE_COORDINATE_* of this "
                "deck", "cid")
        if nid in tied:
            iid, sp = tied[nid]
            add(f"node {nid} is a secondary node of /INTER/TYPE2/{iid} "
                f"(Spotflag {sp})", "tied")
        if nid in tied_main:
            iid, sp = tied_main[nid]
            add(f"node {nid} is a MAIN-side node of /INTER/TYPE2/{iid} "
                f"(Spotflag {sp})", "tied_main")
        if nid in rigid:
            add(f"node {nid} is a rigid-body node", "rigid")
        rot = dof >= 4
        if rot and nid not in rot_nodes:
            add(f"node {nid} DOF {dof} has no rotary inertia", "inertia")
        elif not rot and nid not in trans_nodes:
            add(f"node {nid} carries no element and no *ELEMENT_MASS", "mass")
        k = dof - 4 if rot else dof - 1
        kind = 1 if rot else 0
        hits: List[str] = []
        # the TC/RC /BCS map holds both of its producers (round 6, B5)
        tcrc_label = (
            "*NODE TC/RC" if nid not in state.constrained_global_tc_rc else
            "*CONSTRAINED_GLOBAL" if nid not in state.node_tc_rc else
            "*NODE TC/RC and *CONSTRAINED_GLOBAL")
        for label, table in (("*BOUNDARY_SPC", gspc), (tcrc_label, tcrc)):
            code = table.get(nid)
            if code is None:
                continue
            digits = code[kind]
            if (cid == 0 and digits[k] == "1") or (cid > 0 and "1" in digits):
                hits.append(label + " /BCS")
        if skew_spc.get(nid, ("000", "000"))[kind] != "000":
            hits.append("a skewed *BOUNDARY_SPC /BCS")
        dirs = state.imp_motion_dirs.get(nid, set())
        mine = (("XX", "YY", "ZZ") if rot else ("X", "Y", "Z"))
        if (cid == 0 and mine[k] in dirs) or (cid > 0 and set(mine) & dirs):
            hits.append("an imposed motion")
        if nid in state.imp_motion_skew_nodes:
            hits.append("an imposed motion in a local system")
        if hits:
            add(f"node {nid} DOF {dof} already carries " + " and ".join(hits),
                "kin")
        if (nid, dof) in used:
            add(f"node {nid} DOF {dof} is already in an earlier /MPC", "twice")
        elif (nid, dof) in seen:
            add(f"node {nid} DOF {dof} is named twice on the card", "twice")
        seen.add((nid, dof))
    if notes:
        why.append("(" + "; ".join(_MPC_REFUSAL_NOTES[n] for n in notes)
                   + ")")
    return why


def _make_constrained_linear_mpcs(state: ConversionState, rbody_info: Dict,
                                  rigid_nodes: Set[int]) -> List[str]:
    """``*CONSTRAINED_LINEAR_LOCAL`` / ``_GLOBAL`` → one ``/MPC`` per card
    (R14 triage round 6, A5; default ON, ``--no-constrained-linear``).

    ``/MPC`` (``radioss110/RBODY/mpc.cfg`` FORMAT(radioss90): a title card,
    then a free list of ``%10d%10d%10d%20lg`` rows ``node_ID Idof skew_ID
    alpha``; ``hm_read_mpc.F:119-122``). Each term is one row: ``node = NID``,
    ``Idof = DOF``, ``skew = CID`` (every ``*DEFINE_COORDINATE_*`` is written
    as the ``/SKEW`` of the same id, ``writer/mesh._make_skews``), ``alpha =
    COEF``. The engine enforces it by a Lagrange multiplier as the VELOCITY
    equation ``sum alpha_k v_k = 0`` (``lag_mpc.F``, reached from
    ``resol.F`` through ``lag_mult.F``) — LS-DYNA's ``sum C_k u_k = C0`` with
    ``C0 = 0`` from ``t = 0``, which is the only C0 LS-DYNA has (*"LS-DYNA
    assumes the constant C0 is zero"*, Vol I R17 p.10-136 / p.10-139).

    PLACED immediately before the frequency-domain notes: every section that
    can write a ``/BCS``, an imposed motion, a rigid body, a free-node pin or
    an ``/INTER/TYPE2`` has run, so the screens read complete registries
    (``state.type2_secondary`` and ``state.type2_main_side`` included: a term
    on a node of either side of a tied interface is refused whatever the
    Spotflag - round 7 B4, the main side since the post-review round), and no
    section after
    it draws an id, so an emitted ``/MPC`` renumbers nothing. The id is drawn
    only after the last screen, and the keyword leaves ``skipped_keywords``
    only when its card is emitted: a refused card keeps its ``#-- SKIPPED:``
    line.
    """
    cards = state.constrained_linears
    if not cards:
        return []
    if not state.options.constrained_linear:
        state.warn(
            f"--no-constrained-linear: {len(cards)} *CONSTRAINED_LINEAR_* "
            f"card(s) (LCID {[c.lcid for c in cards]}) left unconverted and "
            "listed as skipped: the linear constraint between their nodes is "
            "lost.")
        return []
    skew_spc: Dict[int, Tuple[str, str]] = {}
    for bc in state.bcs_spcs:
        if not spc_cid_skew(state, bc.cid):
            continue
        tra = _dof_string(bc.dofx, bc.dofy, bc.dofz)
        rot = _dof_string(bc.dofrx, bc.dofry, bc.dofrz)
        for nid in state.node_sets.get(bc.nsid, ("", []))[1]:
            old = skew_spc.get(nid, ("000", "000"))
            skew_spc[nid] = (_or_dof_codes([old[0], tra]),
                             _or_dof_codes([old[1], rot]))
    rigid: Set[int] = set(rigid_nodes) | set(state.rbody_ids)
    rigid |= {info["ind_node"] for info in rbody_info.values()}
    trans_nodes: Set[int] = {n for n, m in state.added_node_masses.items()
                             if m > 0.0}
    rot_nodes: Set[int] = set()
    for e in state.shell_elems:
        trans_nodes.update(e.nodes)
        rot_nodes.update(e.nodes)
    for elems in (state.solid_elems, state.tshell_elems):
        for s in elems:
            trans_nodes.update(s.nodes)
    for b in state.beam_elems:
        trans_nodes.update((b.n1, b.n2))
        rot_nodes.update((b.n1, b.n2))
    for d in state.discrete_elems:
        trans_nodes.update((d.n1, d.n2))
    gspc = _global_spc_dofs(state)
    skews: Set[int] = (set(state.coord_sys) | set(state.coord_nodes)
                       | set(state.coord_vectors))
    # every emitted /INTER/TYPE2 secondary node -> (inter_id, Spotflag); the
    # lowest interface id names a node two ties share
    tied: Dict[int, Tuple[int, int]] = {}
    for iid, (sp, tnodes) in sorted(state.type2_secondary.items()):
        for n in tnodes:
            tied.setdefault(n, (iid, sp))
    # ... and every node of each one's MAIN side -> (inter_id, Spotflag),
    # resolved here (only a deck with *CONSTRAINED_LINEAR_* cards gets this
    # far) with the resolution the deck-wide ERROR-556 pass uses
    # (contacts._emitted_type2_mains): exact for a *SET_SEGMENT / *SET_SHELL
    # side, every node of the parts for a part side (a solid's interior nodes
    # included - an over-approximation that can only refuse more)
    from .contacts import _tied_slave_nids
    tied_main: Dict[int, Tuple[int, int]] = {}
    side_nodes: Dict[Tuple[int, int], List[int]] = {}
    for iid, side in sorted(state.type2_main_side.items()):
        sp = state.type2_secondary[iid][0]
        if side not in side_nodes:
            side_nodes[side] = _tied_slave_nids(state, *side)
        for n in side_nodes[side]:
            tied_main.setdefault(n, (iid, sp))
    used: Set[Tuple[int, int]] = set()
    lines: List[str] = []
    emitted: List[Tuple[int, int]] = []
    for lin in cards:
        why = _constrained_linear_refusals(
            state, lin, gspc, state.node_tc_rc_emitted, skew_spc, rigid,
            trans_nodes, rot_nodes, skews, used, tied, tied_main)
        if why:
            state.warn(
                f"*{lin.keyword} {lin.lcid}: NOT converted to /MPC - "
                + "; ".join(dict.fromkeys(why[:-1] if why[-1].startswith("(")
                                          else why))
                + (" " + why[-1] if why[-1].startswith("(") else "")
                + ". The card is listed as skipped and its linear "
                "constraint is lost.")
            continue
        mpc_id = state.next_id()      # AFTER the last screen that can refuse
        lines += [f"/MPC/{mpc_id}", f"{lin.keyword}_{lin.lcid}", _MPC_ROW_HDR]
        for nid, dof, cid, coef in lin.terms:
            lines.append(f"{_i(nid)}{_i(dof)}{_i(cid)}{_f(coef)}")
            used.add((nid, dof))
        lines.append(HDR)
        state.skipped_keywords.remove(lin.keyword)
        emitted.append((lin.lcid, mpc_id))
    if emitted:
        state.warn(
            f"*CONSTRAINED_LINEAR_LOCAL/_GLOBAL: {len(emitted)} card(s) -> "
            f"/MPC {[m for _l, m in emitted]} (LCID "
            f"{[lcid for lcid, _m in emitted]}; a Lagrange multiplier, "
            "lag_mpc.F; the velocity form sum alpha_k v_k = 0 enforces "
            "LS-DYNA's sum C_k u_k = C0 with C0 = 0 from t = 0 - Vol I R17 "
            "p.10-136/139: 'LS-DYNA assumes the constant C0 is zero'). A term "
            "in a local system is written with skew_ID = its CID (the /SKEW "
            "of that id). The /MPC makes the engine solve a Lagrange system "
            "every cycle (resol.F -> lag_mult.F -> lag_mpc.F). Pass "
            "--no-constrained-linear to leave the card unconverted.")
    return lines


def _make_starter_cloads(state: ConversionState) -> List[str]:
    """/CLOAD is a Starter keyword – concentrated loads on node groups.

    Card layout (one 100-col data card after the title — same columns from
    radioss51 through 2026; cfg radioss2023+ reads cols 51-60 as Itypfun,
    older input versions blank-skip them):
      fct_IDT(10) Dir(10) skew_ID(10) sens_ID(10) grnd_ID(10) Itypfun(10)
      Ascalex(20) Fscaley(20)
    Itypfun stays BLANK (= default 1, abscissa is time, matching
    *LOAD_RIGID_BODY LCID semantics): /BEGIN-2022 readers flag any non-blank
    text in skipped columns with WARNING 100214 "unsupported field exists",
    while 2023+ readers take blank as 1 — blank is warning-free either way.
    """
    if not state.load_rigid_bodies:
        return []

    _DOF_DIR_FORCE = {1: "X", 2: "Y", 3: "Z", 5: "XX", 6: "YY", 7: "ZZ"}
    lines: List[str] = ["#-  CONCENTRATED LOADS (RIGID BODY):"]
    load_id = 1
    emitted = False
    for lb in state.load_rigid_bodies:
        ind_grnod_id = state.rbody_ind_grnods.get(lb.pid)
        if ind_grnod_id is None:
            state.warn(f"LOAD_RIGID_BODY pid={lb.pid}: rigid body not found – skipped")
            continue

        if lb.dof == 4:
            dirs_to_emit = [("X", lb.sf), ("Y", lb.sf), ("Z", lb.sf)]
        else:
            d = _DOF_DIR_FORCE.get(lb.dof)
            if d is None:
                state.warn(f"LOAD_RIGID_BODY pid={lb.pid} DOF={lb.dof}: unknown DOF – skipped")
                continue
            dirs_to_emit = [(d, lb.sf)]

        from .loadcurves import load_funct_id
        for dir_str, sf in dirs_to_emit:
            fct = load_funct_id(state, lb.lcid, "CLOAD")   # round 9, B5
            lines += [
                f"/CLOAD/{load_id}",
                f"LoadRB_{load_id}",
                "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
                f"{_i(fct)}{dir_str.rjust(10)}{_i(lb.cid)}         0{_i(ind_grnod_id)}"
                f"          {_f(1.0)}{_f(sf)}",
                HDR,
            ]
            load_id += 1
            emitted = True

    return lines if emitted else []


def _make_node_cloads(state: ConversionState) -> List[str]:
    """*LOAD_NODE_POINT / *LOAD_NODE_SET → /CLOAD on the node (set)'s /GRNOD.

    Same card layout as the rigid-body /CLOAD above; the CID local system maps
    to the /CLOAD skew (the /SKEW of the same id is emitted by _make_skews),
    falling back to global with a warning when no such system exists.
    """
    if not state.load_nodes:
        return []

    _DOF_DIR_FORCE = {1: "X", 2: "Y", 3: "Z", 5: "XX", 6: "YY", 7: "ZZ"}
    lines: List[str] = ["#-  CONCENTRATED LOADS (NODES):"]
    grnod_by_nsid: Dict[int, int] = {}
    for ln in state.load_nodes:
        set_title, nids = state.node_sets.get(ln.nsid, ("", []))
        if not nids:
            state.warn(f"LOAD_NODE nsid={ln.nsid}: node set not found – skipped")
            continue
        skew_id = 0
        if ln.cid:
            # round 9, A6 (D9): the same three-kind test as *BOUNDARY_SPC
            if spc_cid_skew(state, ln.cid):
                skew_id = ln.cid
            elif ln.cid in state.coord_vectors:
                # the post-review round: under --no-spc-vector-frames the
                # VECTOR frame exists and is kept out (the 386444e bytes) -
                # a true sentence instead of 'not found'
                state.warn(
                    f"LOAD_NODE nsid={ln.nsid}: local system cid={ln.cid} is a "
                    "*DEFINE_COORDINATE_VECTOR, which --no-spc-vector-frames "
                    "keeps out — load applied in the GLOBAL system.")
            else:
                state.warn(
                    f"LOAD_NODE nsid={ln.nsid}: local system cid={ln.cid} not "
                    "found — load applied in the GLOBAL system.")
        grnod_id = grnod_by_nsid.get(ln.nsid)
        emit_grnod = grnod_id is None   # read further down; the narrowing
        if grnod_id is None:            # needs the `is None` test itself
            grnod_id = state.next_grnod_id()
            grnod_by_nsid[ln.nsid] = grnod_id
        load_id = state.next_id()
        from .loadcurves import load_funct_id
        fct = load_funct_id(state, ln.lcid, "CLOAD")       # round 9, B5
        lines += [
            f"/CLOAD/{load_id}",
            set_title or f"LoadNode_{load_id}",
            "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
            f"{_i(fct)}{_DOF_DIR_FORCE[ln.dof].rjust(10)}{_i(skew_id)}         0{_i(grnod_id)}"
            f"          {_f(1.0)}{_f(ln.sf)}",
            HDR,
        ]
        if emit_grnod:
            lines += _emit_grnod_node(grnod_id, set_title or f"SET_{ln.nsid}", nids)
    return lines if len(lines) > 1 else []


def _synthesize_rwall_moving_nodes(state: ConversionState) -> None:
    """Give each *RIGIDWALL_PLANAR_MOVING wall its /RWALL carrier node.

    The OpenRadioss moving /RWALL form (cfg RWALL/plane.cfg + paral.cfg,
    FORMAT radioss51; starter hm_read_rwall_plane.F) takes node_ID > 0: the
    node's coordinates become the wall base point M, and the wall card's own
    "Mass VX0 VY0 VZ0" line adds the wall mass to that node and sets its
    initial velocity (MS(MSR) += Mass; V(:,MSR) = VX0..) — so no /ADMAS or
    /INIVEL is needed. Synthesize a free node at the LS-DYNA tail point
    (XT,YT,ZT), like the rigid-cog master synthesis in _make_rbodies (new ids
    above the current maximum). Must run before the /NODE section is built.
    """
    movers = [rw for rw in state.rigid_walls if rw.moving and rw.node_id == 0]
    if not movers:
        return
    next_free = (max(state.nodes) + 1) if state.nodes else 90000001
    for rw in movers:
        rw.node_id = next_free
        next_free += 1
        state.nodes[rw.node_id] = NodeData(rw.xt, rw.yt, rw.zt)
        state.warn(
            f"*RIGIDWALL_PLANAR_MOVING id={rw.rwid}: wall carried by "
            f"synthesized free node {rw.node_id} at the wall tail point; the "
            "/RWALL card's Mass/V0 fields give that node the wall mass and "
            "the initial velocity V0 along the wall normal.")


def _rwall_finite_corners(rw, state: ConversionState):
    """Corner points M1/M2 of the /RWALL/PARAL form for a _FINITE wall.

    LS-DYNA: the l-edge direction is the in-plane projection of
    (HEV − tail); the m-edge is m = n × l; the wall spans lenl and lenm from
    the tail corner. /RWALL/PARAL takes the two opposite in-plane corner
    POINTS M1 = M + lenl·l̂ and M2 = M + lenm·m̂ (cfg RWALL/paral.cfg); the
    starter derives the outward normal as (M1−M)×(M2−M) =
    lenl·lenm·(l̂×m̂) = lenl·lenm·n̂ (hm_read_rwall_paral.F), so the normal
    orientation is preserved. Returns (M1, M2) or None when the wall cannot
    be expressed as a finite parallelogram (→ infinite-plane fallback, with
    a warning naming the reason).
    """
    label = f"*RIGIDWALL_PLANAR_FINITE id={rw.rwid}"
    n = _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt))
    if n is None:
        state.warn(f"{label}: degenerate wall normal (head == tail) — "
                   "emitted as an infinite plane.")
        return None
    if rw.lenl <= 0.0 or rw.lenm <= 0.0:
        # DYNA convention: a zero LENL/LENM means infinite extent in that
        # direction. /RWALL/PARAL is strictly finite (no semi-infinite
        # form), so fall back to the infinite plane.
        state.warn(
            f"{label}: LENL/LENM = 0 means an infinite extent in that "
            "direction in LS-DYNA; /RWALL/PARAL cannot express a "
            "semi-infinite wall — emitted as an infinite plane.")
        return None
    triad = _rwall_geom_triad(rw, n)
    if triad is None:
        state.warn(
            f"{label}: the edge-vector head (XHEV,YHEV,ZHEV) coincides with "
            "the wall tail or projects onto the wall normal (no in-plane l "
            "direction) — emitted as an infinite plane.")
        return None
    _n, lu, mu = triad
    m1 = (rw.xt + rw.lenl * lu[0], rw.yt + rw.lenl * lu[1],
          rw.zt + rw.lenl * lu[2])
    m2 = (rw.xt + rw.lenm * mu[0], rw.yt + rw.lenm * mu[1],
          rw.zt + rw.lenm * mu[2])
    return m1, m2


def _rwall_geom_triad(rw, n):
    """The (n̂, l̂, m̂) orthonormal triad of a FLAT/PRISM/_FINITE rigid wall.

    ``n`` is the already-validated unit wall normal (LS-DYNA's
    normalize(head − tail)). The l-edge direction comes from
    (XHEV,YHEV,ZHEV) − tail and m = n × l (Manual p. 40-9); the HEV vector is
    projected into the wall plane first, because a raw normalize(HEV − T) —
    what dyna2rad uses, convertrwalls.cxx:255-259 — leaves m̂ = n̂ × l̂ short by
    sin(theta) whenever HEV is not exactly perpendicular to the normal, so
    every m-edge length comes out wrong by that factor.

    Returns None when (HEV − tail) has no in-plane component, i.e. when the
    l direction does not exist. The test is deliberately TAIL-RELATIVE, not
    "is XHEV/YHEV/ZHEV the global origin": HEV is a POINT, so an
    *INCLUDE_TRANSFORM translation moves it, and an absolute test would
    classify the same physical wall differently depending on how the deck is
    assembled. Shared by the *RIGIDWALL_PLANAR _FINITE path and the
    *RIGIDWALL_GEOMETRIC FLAT/PRISM path so the two cannot drift.
    """
    v = (rw.xhev - rw.xt, rw.yhev - rw.yt, rw.zhev - rw.zt)
    dot = v[0] * n[0] + v[1] * n[1] + v[2] * n[2]
    proj = (v[0] - dot * n[0], v[1] - dot * n[1], v[2] - dot * n[2])
    vmag = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
    pmag = (proj[0] ** 2 + proj[1] ** 2 + proj[2] ** 2) ** 0.5
    if pmag <= 1e-10 * max(1.0, vmag):
        return None
    lu = (proj[0] / pmag, proj[1] / pmag, proj[2] / pmag)
    return n, lu, _vcross(n, lu)        # n ⊥ l and both unit ⇒ |n × l| = 1


def _rwall_geom_faces(rw, state: ConversionState, label: str, title: str,
                      alloc_rwid) -> List[RigidWallGeomFace]:
    """Resolve one *RIGIDWALL_GEOMETRIC card to its Radioss /RWALL wall(s).

    CYLINDER → one /RWALL/CYL, SPHERE → one /RWALL/SPHER, FLAT → one
    /RWALL/PLANE (infinite) or /RWALL/PARAL (finite), PRISM → six /RWALL/PARAL
    faces with outward normals, because Radioss has no box rigid wall (the only
    /RWALL readers are hm_read_rwall_{plane,paral,cyl,spher,lagmul,therm}.F).
    Returns [] when nothing can be emitted; every loss is warned.
    """
    if rw.shape == "CYLINDER":
        # /RWALL/CYL: M and M1 are two absolute points, the axis is
        # normalize(M1 − M) and only the DIRECTION survives (the length is
        # divided out, hm_read_rwall_cyl.F:240-254) — so the LS-DYNA head
        # point is carried over verbatim, exactly as dyna2rad does.
        if _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt)) is None:
            state.warn(f"{label}: the cylinder axis is degenerate (head == "
                       "tail) — the starter would abort with ERROR 167, so "
                       "the wall was skipped.")
            return []
        if rw.radcyl <= 0.0:
            state.warn(f"{label}: RADCYL = {rw.radcyl:g} — a zero-radius "
                       "cylinder never contacts anything, so the wall was "
                       "skipped.")
            return []
        if rw.lencyl > 0.0:
            state.warn(
                f"{label}: LENCYL = {rw.lencyl:g} makes the LS-DYNA cylinder "
                "FINITE (length running from the tail plane along -n), but "
                "/RWALL/CYL stores only a base point, an axis direction and a "
                "diameter and is AXIALLY INFINITE (there is no length field; "
                "the engine's only contact test is the perpendicular distance "
                "to the axis line, rgwalc.F:129-133) — the converted wall also "
                "blocks nodes beyond both ends of the LS-DYNA cylinder.")
        return [RigidWallGeomFace(
            rwid=rw.rwid, title=title, form="CYL",
            m=(rw.xt, rw.yt, rw.zt), m1=(rw.xh, rw.yh, rw.zh),
            diameter=2.0 * rw.radcyl)]

    if rw.shape == "SPHERE":
        if rw.radsph <= 0.0:
            state.warn(f"{label}: RADSPH = {rw.radsph:g} — a zero-radius "
                       "sphere never contacts anything, so the wall was "
                       "skipped.")
            return []
        # /RWALL/SPHER has no card 4: M is the centre and Diameter the size
        # (hm_read_rwall_spher.F:204-206, 230).
        return [RigidWallGeomFace(
            rwid=rw.rwid, title=title, form="SPHER",
            m=(rw.xt, rw.yt, rw.zt), diameter=2.0 * rw.radsph)]

    # ── FLAT / PRISM ────────────────────────────────────────────────────────
    tail = (rw.xt, rw.yt, rw.zt)
    head = (rw.xh, rw.yh, rw.zh)
    plane_face = RigidWallGeomFace(rwid=rw.rwid, title=title, form="PLANE",
                                   m=tail, m1=head)
    n = _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt))
    if n is None:
        state.warn(f"{label}: degenerate wall normal (head == tail) — the "
                   "wall orientation is undefined, so it was skipped.")
        return []
    if rw.lenl <= 0.0 or rw.lenm <= 0.0:
        # "LENL/LENM: Length of the l/m edge. A ZERO VALUE DEFINES AN INFINITE
        # SIZE PLANE" (Manual p. 40-9, and the same wording for the prism on
        # p. 40-10) — so for a FLAT wall /RWALL/PLANE through the tail with
        # M1 = head is the EXACT conversion, not an approximation, and no
        # warning is due. dyna2rad instead builds a 1e20 x 1e20 PARAL quadrant
        # anchored at the tail, which misses every node on its -l/-m side.
        if rw.shape == "FLAT":
            return [plane_face]
        state.warn(
            f"{label}: LENL/LENM = 0 defines an INFINITE plane (Manual "
            "p. 40-10), so the prism has no finite top face to extrude — "
            "emitted as an INFINITE /RWALL/PLANE through the tail point (the "
            "prism's four side faces and its bottom face are lost).")
        return [plane_face]

    # The wall IS finite, so it needs the in-plane l direction. The test is
    # tail-relative — HEV is a POINT (Manual p. 40-9, "coordinate of head of
    # edge vector l"), so l = HEV - tail; a blank card means l = -tail, not
    # "infinite plane". Classifying on the ABSOLUTE HEV instead (what
    # rigidwall_geometric.cfg:416 does for its HyperMesh geometrytype radio)
    # is not *INCLUDE_TRANSFORM-invariant: a translation moves HEV off the
    # global origin and the same physical wall would convert differently
    # depending on how the deck is assembled.
    triad = _rwall_geom_triad(rw, n)
    if triad is None:
        state.warn(
            f"{label}: the edge-vector head (XHEV,YHEV,ZHEV) coincides with "
            "the wall tail or projects onto the wall normal, so the l edge "
            "direction is undefined — emitted as an INFINITE /RWALL/PLANE "
            "through the tail point, which blocks more than the finite "
            "LS-DYNA wall does"
            + (" (the prism's four side faces and its bottom face are lost)."
               if rw.shape == "PRISM" else "."))
        return [plane_face]

    nu, lu, mu = triad
    lvec = (rw.lenl * lu[0], rw.lenl * lu[1], rw.lenl * lu[2])
    mvec = (rw.lenm * mu[0], rw.lenm * mu[1], rw.lenm * mu[2])
    add = lambda *vs: tuple(sum(v[i] for v in vs) for i in range(3))
    # /RWALL/PARAL takes the two opposite corner POINTS; the starter forms the
    # normal as (M1-M) x (M2-M) = LENL*LENM*(l x m) = +n̂ and keeps the
    # UN-normalized edge vectors as the patch extents (hm_read_rwall_paral.F:
    # 245-267), so the LS-DYNA outward normal is preserved exactly.
    top = RigidWallGeomFace(rwid=rw.rwid, title=title, form="PARAL",
                            m=tail, m1=add(tail, lvec), m2=add(tail, mvec))
    if rw.shape == "FLAT":
        return [top]

    if rw.lenp <= 0.0:
        state.warn(
            f"{label}: LENP = 0 makes the prism infinitely deep along -n; the "
            "four side faces and the bottom face would each need a "
            "semi-infinite /RWALL/PARAL, which does not exist — only the top "
            "face was emitted (dyna2rad emits four walls with a zero edge "
            "vector here, which the starter rejects with ERROR 168).")
        return [top]

    pvec = (-rw.lenp * nu[0], -rw.lenp * nu[1], -rw.lenp * nu[2])
    neg = lambda v: (-v[0], -v[1], -v[2])
    # Box corner T with edges +l (LENL), +m (LENM) and -n (LENP). Each face is
    # (M, M1, M2) with (M1-M) x (M2-M) pointing OUT of the box, so the six
    # walls together keep nodes outside the prism — the same decomposition
    # dyna2rad uses (convertrwalls.cxx:299-374), verified face by face.
    faces = [top]
    for suffix, m0, e1, e2 in (
            ("2", tail,                      pvec,      lvec),   # m = 0
            ("3", tail,                      mvec,      pvec),   # l = 0
            ("4", add(tail, mvec),           lvec,      pvec),   # m = LENM
            ("5", add(tail, mvec, lvec),     neg(mvec), pvec),   # l = LENL
            ("6", add(tail, pvec),           mvec,      lvec)):  # p = LENP
        faces.append(RigidWallGeomFace(
            rwid=alloc_rwid(), title=f"{title}_FACE{suffix}", form="PARAL",
            m=m0, m1=add(m0, e1), m2=add(m0, e2)))
    return faces


def _resolve_geometric_rigid_walls(state: ConversionState) -> None:
    """build_starter prepass for *RIGIDWALL_GEOMETRIC_*.

    Resolves every geometric wall to its concrete Radioss wall(s) (so the
    geometry warnings are raised exactly once), allocates the extra /RWALL ids
    a PRISM's five additional faces need, and synthesizes the _MOTION carrier
    nodes. Must run before the /NODE section is built and alongside the other
    node-synthesizing prepasses, which all allocate off max(state.nodes)+1.
    """
    if not state.rigid_walls_geometric:
        return
    used_rwids = ({rw.rwid for rw in state.rigid_walls}
                  | {g.rwid for g in state.rigid_walls_geometric})
    next_node = (max(state.nodes) + 1) if state.nodes else 90000001

    def alloc_rwid() -> int:
        # /RWALL ids are checked by ONE starter UDOUBLE pass across PLANE, CYL,
        # SPHER and PARAL (read_rwall.F), so a synthesized face id must dodge
        # every wall in the deck, not just the geometric ones.
        rid = state.next_id()
        while rid in used_rwids:
            rid = state.next_id()
        used_rwids.add(rid)
        return rid

    for rw in state.rigid_walls_geometric:
        label = f"*RIGIDWALL_GEOMETRIC_{rw.shape} id={rw.rwid}"
        title = rw.title or f"RWALL_{rw.rwid}"
        rw.faces = _rwall_geom_faces(rw, state, label, title, alloc_rwid)
        if not rw.faces:
            rw.motion = False
            continue
        if len(rw.faces) > 1:
            # Every box EDGE is covered by two of the six faces and every
            # CORNER by three, so the tracked nodes carry overlapping rigid-wall
            # constraints by construction. The starter reports that as
            # WARNING 312 with roughly 5 x (tracked nodes) conditions; it is
            # expected, not a deck error — the engine resolves each wall in
            # turn (rgwal0.F loops over NRWALL) and a convex-edge hit splits
            # the impulse between the two adjoining faces.
            msg = (f"{label}: Radioss has no box rigid wall, so the prism "
                   f"became {len(rw.faces)} separate /RWALL/PARAL faces (ids "
                   + ", ".join(str(f.rwid) for f in rw.faces)
                   + "). They share the tracked node group and overlap along "
                   "the box edges, so the starter raises WARNING ID 312 "
                   "(INCOMPATIBLE KINEMATIC CONDITIONS ... BETWEEN SEVERAL "
                   "RIGID WALLS) — expected for this decomposition.")
            if state.db_rwforc_dt > 0.0:
                msg += (" The /TH/RWALL reaction is likewise split across "
                        f"{len(rw.faces)} entries — sum them to compare "
                        "against one LS-DYNA rwforc record.")
            state.warn(msg)
        if not rw.motion:
            continue
        # ── _MOTION validity ────────────────────────────────────────────────
        if rw.lcid <= 0:
            state.warn(
                f"{label}: the MOTION card has no load curve (LCID = 0), so "
                "there is nothing to prescribe — the wall is emitted as a "
                "FIXED wall rather than as a free, unconstrained one "
                "(dyna2rad emits the massless free wall).")
            rw.motion = False
            continue
        if rw.lcid not in state.curves:
            state.warn(
                f"{label}: MOTION curve LCID={rw.lcid} is not in the deck — "
                "the wall is emitted as a FIXED wall.")
            rw.motion = False
            continue
        if _vnorm((rw.vx, rw.vy, rw.vz)) is None:
            state.warn(
                f"{label}: the MOTION direction cosines VX/VY/VZ are all zero, "
                "so the motion direction is undefined — the wall is emitted as "
                "a FIXED wall (dyna2rad silently moves it along global +X).")
            rw.motion = False
            continue
        # A moving /RWALL takes its base point M from the carrier node's
        # coordinates and replaces the XM/YM/ZM card with "Mass VX0 VY0 VZ0"
        # (hm_read_rwall_cyl.F:199-230) — so every DISTINCT face base point
        # needs a node there, and one prescribed-motion card drives them all.
        # Faces that share a base point (a prism's top and its two faces
        # through the tail corner) share one node: several /RWALLs may name
        # the same MSR, and fewer carrier nodes means fewer of them landing in
        # a neighbouring face's secondary-node search.
        by_point: Dict[Tuple[float, float, float], int] = {}
        for face in rw.faces:
            nid = by_point.get(face.m)
            if nid is None:
                nid = by_point[face.m] = next_node
                next_node += 1
                state.nodes[nid] = NodeData(*face.m)
            face.node_id = nid
        state.warn(
            f"{label}: MOTION → the wall is carried by synthesized free "
            f"node(s) {', '.join(str(n) for n in sorted(by_point.values()))} "
            f"driven by /{'IMPVEL' if rw.opt == 0 else 'IMPDISP'} on curve "
            f"{rw.lcid}; /RWALL itself has no motion-curve field, and the "
            "imposed motion wins over the wall reaction (resol.F calls FIXVEL "
            "after RGWALF). The wall's own Mass field stays 0, matching the "
            "LS-DYNA card, which specifies no wall mass — and a zero-mass "
            "carrier node makes the motion PURELY kinematic: rgwal0.F:417-423 "
            "scales the wall reaction by MS(MSR)/(MS(MSR)+Sum(m_secondary)), "
            "which is 0 here, so contact can never accelerate or laterally "
            "drift the wall (unlike a *RIGIDWALL_PLANAR_MOVING wall, which "
            "carries a real mass).")


def _make_geometric_rwall_motion(rw, state: ConversionState,
                                 grnod_id: int) -> List[str]:
    """The /SKEW/FIX + /GRNOD + /IMPVEL|/IMPDISP driving a _MOTION wall.

    LS-DYNA gives a motion DIRECTION (VX,VY,VZ direction cosines) plus a curve
    that carries the amplitude; /IMPVEL and /IMPDISP prescribe along one axis
    of a skew, so the direction becomes a /SKEW/FIX whose local X' is the
    motion vector and the card asks for Dir = "X". /SKEW/FIX's two vector
    cards are the local Y' and Z' (NOT X and Y), and the starter rebuilds
    X' = Y' x Z' (hm_read_skw.F:448-459): with Y' = ê x V and Z' = V x Y',
    X' = Y' x Z' = V |Y'|^2, i.e. exactly +V.

    This is the THIRD /IMP* emission site in the writer, and the only one that
    does NOT call ``_register_imp_motion_nodes``. Deliberate, not an omission:
    that registry is the *DATABASE_BNDOUT scope, and LS-DYNA reports a rigid
    wall's reaction in ``rwforc`` (-> *DATABASE_RWFORC -> /TH/RWALL), never in
    ``bndout``. The carrier nodes are synthesized by k2rad as well — massless
    free nodes that appear in no LS-DYNA deck and whose REAC* is identically
    zero — so listing them would name ids the deck author never wrote and fill
    the channel with zeros. dyna2rad does sweep them in, but only because it
    rebuilds the scope by re-walking the OUTPUT model's /IMPVEL cards
    (dyna2rad.cxx:456-479) and cannot tell the two sources apart. See
    ``writer/output.py::_make_starter_th_bndout``.
    """
    v = _vnorm((rw.vx, rw.vy, rw.vz))
    # ê = global Z, or global X when V is parallel to Z (a zero cross product).
    yax = _vnorm(_vcross((0.0, 0.0, 1.0), v))
    if yax is None:
        yax = _vnorm(_vcross((1.0, 0.0, 0.0), v))
    zax = _vnorm(_vcross(v, yax))
    skew_id = state.reserve_skew_id(state.next_id())
    keyword = "IMPVEL" if rw.opt == 0 else "IMPDISP"
    # /IMPDISP shares ONE starter id table with /IMPDISP/FGEO, whose ids come
    # from the deck (BPFGID) — hence the guarded allocator here and the
    # recording below. This is the third /IMP* emission site and the only one
    # that does not go through _emit_imp_card, which is where the other two
    # record themselves.
    motion_id = (state.next_impdisp_id() if keyword == "IMPDISP"
                 else state.next_id())
    state.imp_card_ids.setdefault(keyword, set()).add(motion_id)
    lines = _emit_skew_fix(skew_id, f"RWALL_{rw.rwid}_MOTION_DIR",
                           (0.0, 0.0, 0.0), yax, zax)
    from .loadcurves import load_funct_id
    fct = load_funct_id(state, rw.lcid, keyword)       # round 9, B5
    lines += [
        f"/{keyword}/{motion_id}",
        f"RWALL_{rw.rwid}_MOTION",
        "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID  frame_ID     Icoor",
        f"{_i(fct)}{'X'.rjust(10)}{_i(skew_id)}         0{_i(grnod_id)}"
        "         0         0",
        "#           Ascale_x            Fscale_Y              Tstart               Tstop",
        f"                   1{_f(1.0)}{_f(0.0)}{_f(0.0)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, f"RWALL_{rw.rwid}_MOTION_NODES",
                              sorted({f.node_id for f in rw.faces}))
    return lines


def _emit_rwall_geom_face(face: RigidWallGeomFace, slide: int, fric: float,
                          grnd1: int, grnd2: int, d: float) -> List[str]:
    """One /RWALL block in the exact cfg FORMAT(radioss51) layout.

    Card 1 is exactly 40 columns (cols 41-50 are the 2026-only Iform, silently
    dropped at /BEGIN 2022); card 2 is the full 90-column
    "d fric Diameter ffac ifq" (20/20/20/20/10). Diameter is meaningful for CYL
    and SPHER only and is read-but-unused for PLANE/PARAL. The title line is
    MANDATORY: omitting it shifts every following card by one and the starter
    accepts the result with 0 ERRORS.
    """
    lines = [
        f"/RWALL/{face.form}/{face.rwid}",
        face.title,
        "#  node_ID     Slide  grnd_ID1  grnd_ID2",
        f"{_i(face.node_id)}{_i(slide)}{_i(grnd1)}{_i(grnd2)}",
        "#           D_search                fric            Diameter"
        "                ffac       ifq",
        f"{_f(d)}{_f(fric if slide == 2 else 0.0)}{_f(face.diameter)}"
        f"{_f(0.0)}{_i(0)}",
    ]
    if face.node_id:
        # Moving form: M comes from the node, and the card carries the wall
        # mass + initial velocity instead. A *RIGIDWALL_PLANAR_MOVING wall
        # puts its LS-DYNA mass and V0 here; a geometric _MOTION wall leaves
        # both at 0 — that card specifies no mass, and the prescribed motion
        # (applied by FIXVEL, after RGWALF) sets the velocity every cycle.
        lines += [
            "#               Mass                VX_0             "
            "   VY_0                VZ_0",
            f"{_f(face.mass)}{_f(face.v0[0])}{_f(face.v0[1])}{_f(face.v0[2])}",
        ]
    else:
        lines += [
            "#                 XM                  YM                  ZM",
            f"{_f(face.m[0])}{_f(face.m[1])}{_f(face.m[2])}",
        ]
    if face.m1 is not None:                      # PLANE, CYL, PARAL
        lines += [
            "#                XM1                 YM1                 ZM1",
            f"{_f(face.m1[0])}{_f(face.m1[1])}{_f(face.m1[2])}",
        ]
    if face.m2 is not None:                      # PARAL only
        lines += [
            "#                XM2                 YM2                 ZM2",
            f"{_f(face.m2[0])}{_f(face.m2[1])}{_f(face.m2[2])}",
        ]
    lines.append(HDR)
    return lines


def _rwall_bbox_corners(state: ConversionState):
    """The 8 corners of the mesh bounding box, or [] for an empty mesh."""
    if not state.nodes:
        return []
    xs = [n.x for n in state.nodes.values()]
    ys = [n.y for n in state.nodes.values()]
    zs = [n.z for n in state.nodes.values()]
    return [(x, y, z) for x in (min(xs), max(xs))
            for y in (min(ys), max(ys)) for z in (min(zs), max(zs))]


def _rwall_search_distance(face: RigidWallGeomFace, corners,
                           state: ConversionState, label: str) -> float:
    """The ``d`` that makes the /RWALL distance search cover the whole mesh.

    LS-DYNA's NSID = 0 means "All nodes are tracked with respect to the rigid
    wall" (Manual p. 40-7). The 2022 /RWALL format has no "all nodes" group
    id, so the tracked set has to come from the search distance — and the
    starter measures that distance from the wall SURFACE, keeping only
    ``DISN >= 0 .AND. DISN <= DIST`` (hm_read_rwall_{plane,paral,cyl,spher}.F):

        PLANE / PARAL   DISN = (X - M) . n̂
        CYL             DISN = |(X - M) - ((X - M).â)â| - Phi/2
        SPHER           DISN = |X - M| - Phi/2

    The model's bounding-box DIAGONAL is NOT an upper bound for any of those
    — an impactor cylinder or sphere parked outside the structure (the normal
    geometry for the geometric family) is further from the mesh than the mesh
    is wide, and the wall then tracks NOTHING, is emitted completely inert,
    and neither the converter nor the starter says a word.

    Each DISN above is a convex function of X, so its maximum over the mesh is
    attained at a bounding-box CORNER: eight evaluations give a tight,
    guaranteed-sufficient d (with a 0.1% margin for the 10-significant-digit
    card field). Returns 0.0 when no corner is in front of the wall, after
    warning — no search distance can help there.
    """
    if not corners:
        return 1e10                     # no mesh: keep the wall harmless
    m = face.m
    rel = [(c[0] - m[0], c[1] - m[1], c[2] - m[2]) for c in corners]
    if face.form == "SPHER":
        vals = [math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
                - 0.5 * face.diameter for v in rel]
    elif face.form == "CYL":
        # `m1` is None for SPHER only (RigidWallGeomFace's docstring: "``m1``
        # None for SPHER"), and that form is handled by the first arm of this
        # if/elif chain, so it never reaches here — but say so with the file's
        # own idiom for "cannot compute, keep the wall harmless" rather than
        # letting an unreachable TypeError stand in for it.
        if face.m1 is None:
            return 1e10
        ax = _vnorm((face.m1[0] - m[0], face.m1[1] - m[1], face.m1[2] - m[2]))
        if ax is None:                  # already refused upstream (ERROR 167)
            return 1e10
        vals = []
        for v in rel:
            d1 = v[0] * ax[0] + v[1] * ax[1] + v[2] * ax[2]
            d2 = v[0] ** 2 + v[1] ** 2 + v[2] ** 2
            vals.append(math.sqrt(max(d2 - d1 * d1, 0.0)) - 0.5 * face.diameter)
    else:                               # PLANE / PARAL
        if face.m1 is None:             # SPHER only — see the CYL arm above
            return 1e10
        if face.m2 is None:             # PLANE: n̂ = normalize(M1 - M)
            nrm = _vnorm((face.m1[0] - m[0], face.m1[1] - m[1],
                          face.m1[2] - m[2]))
        else:                           # PARAL: n̂ = normalize((M1-M) x (M2-M))
            nrm = _vnorm(_vcross(
                (face.m1[0] - m[0], face.m1[1] - m[1], face.m1[2] - m[2]),
                (face.m2[0] - m[0], face.m2[1] - m[1], face.m2[2] - m[2])))
        if nrm is None:                 # already refused upstream
            return 1e10
        vals = [v[0] * nrm[0] + v[1] * nrm[1] + v[2] * nrm[2] for v in rel]
    top = max(vals)
    if top > 0.0:
        return top * 1.001
    if top < 0.0:
        state.warn(
            f"{label}: the wall tracks ALL nodes (NSID = 0), but every node "
            "in the model lies BEHIND its outward normal — the starter's "
            "search keeps only DISN >= 0, so the wall gets no secondary nodes "
            "and is inert. Check the tail/head order on Card 2: the normal "
            "points FROM (XT,YT,ZT) TO (XH,YH,ZH).")
    # top == 0 means every node sits exactly on the wall surface; any d > 0
    # takes them all, and d = 0 would switch the search off entirely
    # (``IF (DIST /= ZERO)``), so never return zero here.
    return 1e10


def _rwall_node_groups(state: ConversionState, label: str, rwid: int,
                       nsid: int, nsidex: int, boxid: int,
                       carrier_nodes=(), carrier_grnod=None):
    """A rigid wall's tracked (grnd_ID1) and excluded (grnd_ID2) node groups.

    Returns (grnd_ID1, grnd_ID2, /GRNOD blocks), or None when the wall must be
    dropped entirely. NSID wins over BOXID (matching dyna2rad); a box-only wall
    becomes a /GRNOD of the in-box nodes; neither means "track ALL nodes",
    which the caller expresses with a search distance d because the 2022
    /RWALL format has no "all nodes" group id.

    ``carrier_nodes`` are the synthesized moving-wall carrier nodes in the
    deck. They are real /NODE entries, so a "track ALL nodes" distance search
    picks them up as SECONDARY nodes of a neighbouring wall — the starter
    excludes only the wall's own main node (``I /= MSR``,
    hm_read_rwall_paral.F:281) — and the rigid-wall constraint then fights the
    /IMPVEL|/IMPDISP that is supposed to drive them (starter WARNING 312, and
    the prescribed motion is no longer trustworthy). A prism's six faces sit on
    each other's box corners, so they hit this at DISN = 0 exactly. Putting
    them in grnd_ID2 clears it: the "Node group -" pass runs AFTER the distance
    search and simply zeroes LPRW (hm_read_rwall_spher.F:266-274). Feeding a
    face its OWN carrier node there is harmless, so all walls share one group
    — ``carrier_grnod`` is a one-element cache the caller uses to emit it once.
    """
    grnd1 = grnd2 = 0
    grnod_blocks: List[str] = []
    if nsid > 0:
        set_title, nids = state.node_sets.get(nsid, ("", []))
        if nids:
            grnd1 = state.next_grnod_id()
            grnod_blocks += _emit_grnod_node(
                grnd1, set_title or f"rwall_{rwid}_nodes", nids)
        else:
            state.warn(
                f"{label}: node set {nsid} not "
                "found — the wall tracks ALL nodes instead.")
    # BOXID scopes the tracked node group. dyna2rad drops the box when NSID
    # is also given (NSID wins); a box-only wall becomes a /GRNOD of the
    # in-box nodes (the same role the NSID set plays above).
    if boxid:
        if grnd1:
            state.warn(
                f"{label}: both NSID and BOXID given "
                "— BOXID dropped, the NSID node set scopes the wall "
                "(matching dyna2rad).")
        else:
            box_nids = _resolve_box_nodes(
                state, boxid, f"{label} BOXID={boxid}")
            if box_nids:
                box_nids = sorted(box_nids)
                grnd1 = state.next_grnod_id()
                grnod_blocks += _emit_grnod_node(
                    grnd1, f"rwall_{rwid}_box{boxid}", box_nids)
                state.warn(
                    f"{label}: tracked nodes scoped "
                    f"to the {len(box_nids)} node(s) inside *DEFINE_BOX "
                    f"{boxid}.")
            elif box_nids is not None:          # resolved but empty
                state.warn(
                    f"{label}: *DEFINE_BOX {boxid} "
                    "encloses no mesh node — no slave nodes, so the wall is "
                    "inactive (LS-DYNA tracks nothing); the wall was skipped "
                    "rather than falling back to tracking ALL nodes.")
                return None
    # Only a distance search (grnd_ID1 = 0) can sweep in a foreign carrier
    # node; an explicit tracked group never contains one, and d is 0 there.
    extra = sorted(carrier_nodes) if not grnd1 else []
    if nsidex > 0:
        set_title, nids = state.node_sets.get(nsidex, ("", []))
        if nids or extra:
            grnd2 = state.next_grnod_id()
            grnod_blocks += _emit_grnod_node(
                grnd2, set_title or f"rwall_{rwid}_excluded",
                sorted(set(nids) | set(extra)))
        if not nids:
            state.warn(
                f"{label}: excluded node set "
                f"{nsidex} not found — no nodes excluded.")
    elif extra:
        if carrier_grnod:                       # already emitted for a sibling
            grnd2 = carrier_grnod[0]
        else:
            grnd2 = state.next_grnod_id()
            grnod_blocks += _emit_grnod_node(
                grnd2, "rwall_moving_carrier_nodes", extra)
            if carrier_grnod is not None:
                carrier_grnod.append(grnd2)
    return grnd1, grnd2, grnod_blocks


def _rwall_slide(fric: float, state: ConversionState, label: str,
                 planar: bool) -> int:
    """LS-DYNA FRIC → the /RWALL ``Slide`` flag.

    0 = frictionless sliding, 1 = tied, 2 = Coulomb friction with the
    coefficient on card 2. "FRIC could be any positive value. Three special
    values of FRIC trigger special treatments" (Manual p. 40-20) — so the
    table is a set of EXACT matches, not a threshold, and it differs by
    family:

    *RIGIDWALL_PLANAR (Manual p. 40-20)   *RIGIDWALL_GEOMETRIC (p. 40-8)
      0.0  frictionless sliding             0.0  frictionless sliding
      1.0  no sliding                       1.0  no sliding
      2.0  weld above WVEL, sliding ok      -    (no weld values)
      3.0  weld above WVEL, no sliding      -
      else Coulomb mu = FRIC                else Coulomb mu = FRIC

    The geometric card documents only 0.0 and 1.0, so FRIC = 2.0 there is a
    plain Coulomb coefficient of 2.0 and must NOT be read as a weld. A
    ``FRIC >= 1.0 → tied`` threshold silently turns every high-friction wall
    into a no-slip one and throws the coefficient away; dyna2rad's geometric
    path has the opposite defect (``FRIC > 0 → Slide 2``, which turns the
    tied FRIC = 1.0 into mu = 1.0, convertrwalls.cxx:234-238).
    """
    if fric == 0.0:
        return 0
    if fric == 1.0:
        return 1
    if fric < 0.0:
        state.warn(f"{label}: FRIC = {fric:g} is negative; LS-DYNA's FRIC is "
                   '"any positive value" (Manual p. 40-20) — treated as a '
                   "frictionless wall (Slide 0).")
        return 0
    if planar and fric in (2.0, 3.0):
        # WVEL-gated welding: the node sticks to the wall once its normal
        # impact velocity exceeds WVEL. /RWALL has no velocity-gated mode, so
        # take the closest unconditional one and say so.
        tied = fric == 3.0
        state.warn(
            f"{label}: FRIC = {fric:g} welds a node to the wall once its "
            "normal impact velocity exceeds WVEL (Manual p. 40-20"
            + ("; no sliding after welding)" if tied else
               "; frictionless sliding after welding)")
            + ". /RWALL has no velocity-gated weld, so the wall is emitted "
            + ("tied (Slide 1) UNCONDITIONALLY — nodes below WVEL are tied "
               "too, and they would rebound in LS-DYNA."
               if tied else
               "frictionless (Slide 0) — nodes above WVEL are NOT held "
               "against the wall and will rebound, which LS-DYNA prevents."))
        return 1 if tied else 0
    return 2


def _rwall_planar_face(rw, state: ConversionState) -> RigidWallGeomFace:
    """The one Radioss wall a *RIGIDWALL_PLANAR resolves to.

    M = LS-DYNA tail (XT,YT,ZT), M1 = head (XH,YH,ZH): both codes point the
    outward normal from the first point to the second. _FINITE becomes
    /RWALL/PARAL with the two opposite corner points (falling back to the
    infinite /RWALL/PLANE, with a warning, when the extents are unusable), and
    _MOVING becomes the moving form: node_ID = the synthesized carrier node,
    with the wall mass and V0 (along the outward unit normal) on its card.
    """
    title = rw.title or f"RWALL_{rw.rwid}"
    paral = _rwall_finite_corners(rw, state) if rw.finite else None
    face = RigidWallGeomFace(
        rwid=rw.rwid, title=title,
        form="PARAL" if paral is not None else "PLANE",
        m=(rw.xt, rw.yt, rw.zt),
        m1=paral[0] if paral is not None else (rw.xh, rw.yh, rw.zh),
        m2=paral[1] if paral is not None else None)
    if not rw.moving:
        return face
    face.node_id = rw.node_id
    face.mass = rw.mass
    nrm = _vnorm((rw.xh - rw.xt, rw.yh - rw.yt, rw.zh - rw.zt))
    if nrm is None:
        state.warn(
            f"*RIGIDWALL_PLANAR_MOVING id={rw.rwid}: degenerate wall normal "
            "(head == tail) — initial velocity V0 dropped (wall starts at "
            "rest).")
    else:
        face.v0 = (rw.v0 * nrm[0], rw.v0 * nrm[1], rw.v0 * nrm[2])
    return face


def _make_rigid_walls(state: ConversionState) -> List[str]:
    """*RIGIDWALL_PLANAR and *RIGIDWALL_GEOMETRIC_* → /RWALL/*.

    Every wall of both families goes through ONE card writer
    (``_emit_rwall_geom_face``) in the exact cfg FORMAT(radioss51) layout
    (hm_cfg_files RWALL/{plane,paral,cyl,sphere}.cfg): the mandatory title
    line, card 1 "node_ID Slide grnd_ID1 grnd_ID2" (4 x I10, exactly 40
    columns), card 2 "D_search fric Diameter ffac ifq" (20/20/20/20/10), then
    "Mass VX0 VY0 VZ0" (moving, node_ID > 0) or "XM YM ZM" (fixed), then
    "XM1 YM1 ZM1" (PLANE/CYL/PARAL) and "XM2 YM2 ZM2" (PARAL).

    A wall with NSID = 0 tracks ALL nodes; /RWALL has no "all" group id, so
    grnd_ID1 stays 0 and the tracked set comes from the search distance d —
    see ``_rwall_search_distance`` for how far that has to reach.
    """
    if not (state.rigid_walls or state.rigid_walls_geometric):
        return []
    lines: List[str] = []

    corners = _rwall_bbox_corners(state)
    # Every synthesized moving-wall carrier node in the deck: excluded from
    # any OTHER wall's "track all nodes" distance search (see the
    # _rwall_node_groups docstring). carrier_grnod caches the shared /GRNOD id.
    carriers = {rw.node_id for rw in state.rigid_walls if rw.node_id > 0}
    carriers |= {f.node_id for rw in state.rigid_walls_geometric
                 for f in rw.faces if f.node_id > 0}
    carrier_grnod: List[int] = []

    th_wall_ids: List[Tuple[int, str]] = []

    def emit(label: str, rwid: int, nsid: int, nsidex: int, boxid: int,
             fric: float, faces: List[RigidWallGeomFace], planar: bool,
             motion=None) -> None:
        # A face's OWN carrier node is already excluded by the starter's
        # `I /= MSR`, so the exclusion group is only worth emitting when some
        # face would otherwise sweep in a FOREIGN one.
        foreign = carriers if any(carriers - {f.node_id} for f in faces) else ()
        groups = _rwall_node_groups(state, label, rwid, nsid, nsidex, boxid,
                                    foreign, carrier_grnod)
        if groups is None:
            return
        grnd1, grnd2, grnod_blocks = groups
        slide = _rwall_slide(fric, state, label, planar)
        # All faces of a prism share one tracked group, one friction setting
        # and (for _MOTION) one prescribed-motion card.
        for face in faces:
            d = 0.0 if grnd1 else _rwall_search_distance(
                face, corners, state, label)
            lines.extend(_emit_rwall_geom_face(face, slide, fric,
                                               grnd1, grnd2, d))
            th_wall_ids.append((face.rwid, face.title))
        if motion is not None:
            lines.extend(motion())
        lines.extend(grnod_blocks)

    for rw in state.rigid_walls:
        emit(f"*RIGIDWALL_PLANAR id={rw.rwid}", rw.rwid, rw.nsid, rw.nsidex,
             rw.boxid, rw.fric, [_rwall_planar_face(rw, state)], planar=True)

    # *RIGIDWALL_GEOMETRIC_* — geometry already resolved to concrete Radioss
    # walls by the _resolve_geometric_rigid_walls prepass (which also created
    # the _MOTION carrier nodes, since those must exist before /NODE).
    for rw in state.rigid_walls_geometric:
        if not rw.faces:
            continue
        emit(f"*RIGIDWALL_GEOMETRIC_{rw.shape} id={rw.rwid}", rw.rwid,
             rw.nsid, rw.nsidex, rw.boxid, rw.fric, rw.faces, planar=False,
             motion=(lambda rw=rw: _make_geometric_rwall_motion(
                 rw, state, state.next_grnod_id())) if rw.motion else None)

    # *DATABASE_RWFORC → /TH/RWALL (wall resultant IMPULSE time history).
    #
    # DEF expands to FNX/Y/Z + FTX/Y/Z (starter hm_read_thgrou.F IVARRWG), and
    # those are a time-ACCUMULATED impulse, not the instantaneous wall force
    # LS-DYNA's rwforc reports. engine/source/constraints/general/rwall/
    # rgwal0.F:504-509 does FSAV(1..6) = FSAV(1..6) + FXN..FZT, where FXN..FZT
    # are the summed nodal IMPULSES for the cycle — the engine divides them by
    # DT12 one line earlier to get the true force (:496-500, DIVDT12 = 1/DT12)
    # but routes that only to FOPT (/ANIM) and the sensor buffer FBSAV6
    # (:485-493), never to /TH. thkin.F:56 then copies FSAV out undivided, and
    # nothing resets it on the writing rank (hist2.F:616-622 zeroes FSAV only
    # for ISPMD/=0). Exactly the FTHREAC-vs-FREAC split of the /TH/NODE REAC*
    # channels, one array further along the same FSAV block.
    if state.db_rwforc_dt > 0.0 and th_wall_ids:
        state.warn(
            "*DATABASE_RWFORC -> /TH/RWALL FNX/Y/Z + FTX/Y/Z: these channels "
            "are a time-ACCUMULATED impulse (force x time), not the "
            "instantaneous wall force rwforc reports — the engine accumulates "
            "the per-cycle nodal impulse sums (rgwal0.F:504-509) and sends the "
            "divided-by-dt force only to /ANIM and the sensors "
            "(rgwal0.F:496-500). Differentiate with respect to time "
            "(F = d(FNX)/dt, e.g. numpy.gradient, or tools/th_to_csv.py which "
            "writes the differentiated column) before comparing against an "
            "LS-DYNA rwforc file.")
        th_id = state.next_id()
        lines += [f"/TH/RWALL/{th_id}", "rwall_forces",
                  "#  DEF = FNX/Y/Z + FTX/Y/Z: IMPULSE (force x time), not force",
                  "#  FSAV accumulates F*dt every cycle: wall force = d(FNX)/dt",
                  "#     var1", "DEF       "]
        for rwid, _tit in th_wall_ids:
            lines.append(_i(rwid))
        lines.append(HDR)
    # Every wall may have been dropped by the geometry checks (a degenerate
    # cylinder axis, an empty *DEFINE_BOX); do not leave an empty section.
    return ["#-  RIGID WALLS:", HDR] + lines if lines else []


def _make_modal_dummy_cload(state: ConversionState,
                            rigid_nodes: Set[int]) -> List[str]:
    """Dummy unit load for the modal stiffness-export run.

    The implicit engine refuses to start a solve with no loading data at all
    (MESSAGE ID 79 ``SOLVER IMPLICIT STOPPED DUE TO LOADING DATA``) — and a
    modal deck usually has none, because its LS-DYNA loads (e.g. gravity) are
    irrelevant to the eigenproblem and are skipped by the conversion. So give
    the one /IMPL/LINEAR step a unit /CLOAD on a free structural node: the
    exported stiffness matrix is load-independent, and the resulting static
    solution doubles as the validation reference — the same load solved
    offline (``tools/modal_solve.py --static <node> Z 1``) must reproduce the
    engine displacements to ~0% (exact-K check; W14 bogie: 0.000%).
    """
    if not state.is_modal or state.options.emit_eig:
        return []
    if (state.load_rigid_bodies or state.pressure_loads
            or state.segment_set_pressure_loads
            or state.prescribed_motions or state.prescribed_motion_sets):
        return []                       # the deck already loads something
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    for e in state.tshell_elems:        # /BRICK — a real structural node
        elem_nodes.update(e.nodes)
    # An SPH particle node carries mass and kernel stiffness, so it is a
    # legitimate place to hang the dummy unit load. The candidate set is
    # otherwise empty on a deck whose only OTHER mesh is rigid, and an empty
    # set is engine MESSAGE ID 79 (SOLVER IMPLICIT STOPPED DUE TO LOADING DATA).
    for c in state.sph_elems:
        elem_nodes.update(c.nodes)
    for e in state.beam_elems:
        elem_nodes.update((e.n1, e.n2))
    # The screen is per-DOF, not per-node. It used to drop every node named by
    # any *BOUNDARY_SPC whatever that SPC pins, which was harmless while few
    # node sets resolved — and stopped being harmless the moment the R14
    # round-2 batch taught the converter to read *SET_NODE_LIST_GENERATE.
    # MEASURED on introduction/Introduction/example-08/ex_08_beam_elform_1.k
    # (a *CONTROL_IMPLICIT_EIGENVALUE deck): its two *BOUNDARY_SPC_SET cards
    # sit on _GENERATE sets and used to resolve to NOTHING, so every node was
    # a candidate; with them read, one set is `Tra 111` and the other
    # `Tra 001 Rot 110`, i.e. every node is named — and the whole-node screen
    # emptied the candidate list and turned a deck that reached 2 cycles into
    # a MESSAGE ID 79 stop. X and Y are free on 66 of its 74 nodes, and a unit
    # /CLOAD along a FREE direction is perfectly good loading data.
    #
    # The screen also has to see the *NODE TC/RC pins this batch introduced.
    # `_global_spc_dofs` covers *BOUNDARY_SPC and zero-scale
    # *BOUNDARY_PRESCRIBED_MOTION only; `state.node_tc_rc_emitted` is filled by
    # _make_node_tc_rc_bcs, which writer/assembly runs BEFORE this section, so
    # unioning it here is both possible and necessary — without it the message
    # below would call a pinned node "still free" and the --static cross-check
    # it prints would compare a zero displacement against a zero displacement,
    # i.e. a check that cannot fail.
    spc = _global_spc_dofs(state)
    for nid, (tra, rot) in state.node_tc_rc_emitted.items():
        have_t, have_r = spc.get(nid, ("000", "000"))
        spc[nid] = ("".join("1" if a == "1" or b == "1" else "0"
                            for a, b in zip(have_t, tra)),
                    "".join("1" if a == "1" or b == "1" else "0"
                            for a, b in zip(have_r, rot)))
    dof_free = {"X": 0, "Y": 1, "Z": 2}
    candidates = elem_nodes - rigid_nodes
    node = 0
    direction = "Z"
    for d in ("Z", "X", "Y"):           # Z first: the historical choice
        free = [n for n in sorted(candidates)
                if spc.get(n, ("000", "000"))[0][dof_free[d]] == "0"]
        if free:
            node, direction = max(free), d
            break
    pinned_fallback = False
    if not node and candidates:
        # No free translational DOF anywhere. Emitting NOTHING is worse than
        # emitting a load the constraints hold: the engine stops with MESSAGE
        # ID 79 without loading data, and the exported stiffness matrix — the
        # only thing this run exists for — is load-INDEPENDENT, so a /CLOAD on
        # a pinned node still lets the export happen. What is lost is the
        # static cross-check, and the message says so instead of pretending
        # the node is free (a check that cannot fail is worse than no check).
        node, direction, pinned_fallback = max(candidates), "Z", True
    if not node:
        state.warn(
            "Modal stiffness-export run has no load and no structural node to "
            "put a dummy /CLOAD on at all — the engine will stop with MESSAGE "
            "ID 79. Add any load to the deck manually.")
        return []
    endtim = state.ctrl_termination.endtim if state.ctrl_termination else 1.0
    funct_id = state.next_id()
    grnod_id = state.next_grnod_id()
    cload_id = state.next_id()
    state.warn(
        "Modal stiffness-export run: the deck has no load, but the implicit "
        "engine refuses to start without loading data (MESSAGE ID 79). Added "
        f"a dummy unit /CLOAD (node {node}, dir {direction} — the highest-"
        "numbered structural node with that translation still free, screened "
        "against *BOUNDARY_SPC, *NODE TC/RC and zero-scale prescribed "
        "motions). The "
        "exported stiffness matrix is load-independent; the static solution "
        "can be cross-checked with: tools/modal_solve.py <matrix> --static "
        f"{node} {direction} 1"
        if not pinned_fallback else
        "Modal stiffness-export run: the deck has no load, but the implicit "
        "engine refuses to start without loading data (MESSAGE ID 79), and "
        "EVERY structural node is pinned in X, Y and Z by a *BOUNDARY_SPC, a "
        "*NODE TC/RC cell or a zero-scale *BOUNDARY_PRESCRIBED_MOTION. Added "
        f"the dummy unit /CLOAD on node {node} (dir {direction}) anyway, "
        "because the stiffness matrix this run exports is load-independent "
        "and no load at all is MESSAGE ID 79. The static cross-check "
        "(tools/modal_solve.py --static) is NOT available on this deck: the "
        "loaded DOF is constrained, so both sides of it are zero."
    )
    lines = [
        "#-  DUMMY STATIC LOAD (modal stiffness-export run needs loading data):",
        HDR,
        f"/FUNCT/{funct_id}",
        "const_unit_load",
        "#                  X                   Y",
        f"{_f(0.0)}{_f(1.0)}",
        f"{_f(max(2.0 * endtim, 1.0))}{_f(1.0)}",
        HDR,
    ]
    lines += _emit_grnod_node(grnod_id, "modal_dummy_load_node", [node])
    lines += [
        f"/CLOAD/{cload_id}",
        "modal_dummy_static_load",
        "#funct_IDT       Dir   skew_ID sensor_ID  grnod_ID   Itypfun             Ascalex             Fscaley",
        f"{_i(funct_id)}{direction.rjust(10)}{_i(0)}         0{_i(grnod_id)}"
        f"          {_f(1.0)}{_f(1.0)}",
        HDR,
    ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Top-level assemblers
# ─────────────────────────────────────────────────────────────────────────────

#: /DAMP card 1 column header, naming the FORMAT(radioss110) fields of
#: ``radioss110/DAMP/Damp.cfg`` — Alpha(20) Beta(20) grnod_ID(10) skew_ID(10)
#: Tstart(20) Tstop(20). k2rad's own wording, NOT that cfg's COMMENT string:
#: the cfg's is 100 chars with every label right-aligned on its field's last
#: column, this one is 102 and sits two columns to the right of the values it
#: labels. Inherited verbatim from the pre-existing inline literal and kept
#: byte-for-byte, because it is a ``#`` comment the starter never reads and
#: re-aligning it would move the hash of every /DAMP-bearing deck in the
#: corpus for a purely cosmetic gain.
_DAMP_CARD1_HDR = ("#               alpha                beta   grnod_ID"
                   "   skew_ID              Tstart               Tstop")


def _damping_elem_nodes(state: ConversionState,
                        keep_pid) -> Set[int]:
    """Every node carried by an element whose part passes *keep_pid*.

    EVERY element family that has nodes is walked, because ``/DAMP`` has NO
    element-type restriction anywhere on its path — reader, group builder or
    engine kernel:

      * ``hm_read_damp.F:415-429`` is the entire group validation: it resolves
        the group id and stores the index. No member walk, no
        element-attachment test.
      * ``hm_lecgrn.F:538-550`` builds a ``/GRNOD/PART`` over a spring, beam or
        truss part with ``TAGNOD(IXT,...)`` / ``TAGNOD(IXP,...)`` /
        ``TAGNODR(IXR,...)``, so those nodes are ordinary group members.
      * ``engine/source/assembly/damping.F:148-150`` is
        ``DO N=1,IGRNOD(IGR)%NENTITY ; I=IGRNOD(IGR)%ENTITY(N) ;
        IF(TAGSLV_RBY(I)==0)`` — the loop index is a NODE, nothing reads IXR,
        IXP, IXT, IXC or IXS, and the only exclusion is rigid SECONDARY nodes.
        ``:175`` opens a second loop for the ROTATIONAL DOFs under ``IRODDL``,
        which is the half that matters MOST to beams and springs.

    MEASURED on a spring-only model (one ``/SPRING``, ``m = 1e-6 Mg``,
    ``k = 100 N/mm``, ``alpha = 600``): the damped envelope gives a log
    decrement of 0.18857418 against the hand-computed 0.18858044, i.e. alpha
    recovered as 600.000132 from an input of 600 — 2e-5 % error. The alpha-0
    twin and a twin whose group holds only the FIXED node both reproduce the
    undamped envelope exactly (delta = -0.00000000), so that is the control
    proving the damping came from the group membership. A beam-only twin
    recovers 44025.98 from 44028 (-0.005 %).

    So the four-family scope this used to have (shells, solids, thick shells,
    SPH) was not a property of ``/DAMP``; it was an omission, and it left a
    beam+spring model completely undamped.

    ``*ELEMENT_PLOTEL`` is the one family deliberately left out: Vol I R17
    calls it a visualization element that "has no effect on the analysis", and
    k2rad emits it as an inert ``/SPRING`` with K = C = 0. Letting a plot
    element introduce damping would be an effect on the analysis. Its nodes
    are damped anyway whenever a real element also holds them, which is the
    normal case — a PLOTEL is drawn between nodes the mesh already has.

    **Vol I R17 p.15-9 Remark 3 is NOT implemented, and the reason is only
    PARTLY sound.** The remark is *"Mass damping will not be applied to
    deformable nodes with prescribed motion or to nodes tied with
    CONSTRAINED_NODE_SET."* Only the rigid-SECONDARY exclusion above is
    applied here. What the engine source does support:
    ``resol.F:7216/7219`` calls ``DAMPING`` and ``resol.F:7345`` calls
    ``FIXVEL`` in that order within one cycle, and ``fixvel.F:370-372``
    (``AOLD = A(J,I) ; A(J,I) = YC(II)``) OVERWRITES the prescribed DOF's
    acceleration outright — so whatever ``damping.F`` put there is discarded
    and the prescribed DOF's MOTION is unaffected.

    Two things that argument does NOT cover, so do not read it as "no
    deviation":

      * The overwrite is per **DOF**; LS-DYNA's exemption is per **NODE**. A
        node whose x is prescribed still has its y, z and rotational DOFs
        damped here and left undamped by LS-DYNA.
      * ``damping.F:167-170`` accumulates ``DW`` (the system damping energy)
        for the node BEFORE ``FIXVEL`` runs, so the reported damping energy
        includes work on a DOF whose motion never changed.

    The CONSTRAINED_NODE_SET half is not analysed at all. Implementing the
    exemption needs its own screening pass and a twin campaign, so it is a
    ROADMAP item, not a claim of parity.
    """
    out: Set[int] = set()

    def take(nodes, pid) -> None:
        if keep_pid(pid):
            out.update(n for n in nodes if n > 0)

    for e in state.shell_elems:
        take(e.nodes, e.pid)
    for e in state.solid_elems:
        take(e.nodes, e.pid)
    for e in state.tshell_elems:
        take(e.nodes, e.pid)
    for c in state.sph_elems:
        take(c.nodes, c.pid)
    for e in state.beam_elems:
        take((e.n1, e.n2), e.pid)          # n3 is an ORIENTATION node
    for e in state.discrete_elems:
        take((e.n1, e.n2), e.pid)          # n2 == 0 means grounded
    for e in state.seatbelt_elems:
        take((e.n1, e.n2, e.n3, e.n4), e.pid)
    return out


def _damping_part_nodes(state: ConversionState, pids: Set[int],
                        rigid_nodes: Set[int]) -> List[int]:
    """Deformable nodes carried by *pids*, rigid-body nodes excluded.

    Every node-carrying element family is scanned — see
    :func:`_damping_elem_nodes` for the source and the measurement. A deck
    whose damped part is built only from beams or springs used to get an empty
    group and a warning instead of a card.
    """
    return sorted(_damping_elem_nodes(state, lambda p: p in pids)
                  - rigid_nodes)


def _damping_resolve_pids(state: ConversionState, pid: int, is_set: bool,
                          what: str) -> Optional[List[int]]:
    """PID or *SET_PART PSID → a list of part ids, or None when unresolvable.

    *SET_PART_ADD sets arrive pre-expanded by ``_flatten_set_adds``
    (recursively), so a single ``state.part_sets`` lookup covers both variants
    — which is also why the resolution has to happen HERE, in the writer, and
    not in the handler.
    """
    if is_set:
        entry = state.part_sets.get(pid)
        if entry is None:
            state.warn(
                f"{what}: *SET_PART {pid} is not defined in this deck (or uses "
                "an unsupported variant such as _COLUMN/_GENERATE) — the "
                "damping scope cannot be resolved, so the card is DROPPED and "
                "those parts run UNDAMPED.")
            return None
        pids = [p for p in entry[1] if p in state.parts]
        missing = sorted(set(entry[1]) - set(pids))
        if missing:
            state.warn(f"{what}: *SET_PART {pid} lists part id(s) {missing} "
                       "with no *PART card — ignored.")
        return pids
    if pid not in state.parts:
        state.warn(f"{what}: part {pid} has no *PART card — the card is "
                   "DROPPED.")
        return None
    return [pid]


def _make_damping(state: ConversionState, rigid_nodes: Set[int],
                  rbody_info: Optional[Dict] = None) -> List[str]:
    """Emit /DAMP from *DAMPING_GLOBAL and *DAMPING_PART_STIFFNESS.

    Rayleigh damping: C = α·M + β·K.
    - α from *DAMPING_GLOBAL valdmp (mass-proportional, damps low-freq modes)
    - β from *DAMPING_PART_STIFFNESS coef (stiffness-prop, damps high-freq waves)

    OpenRadioss /DAMP (Reference Guide p.130):
    - Format 1: single α, all DOFs
    - Format 2: per-DOF α and β, 6 lines

    Target nodes:
    - If *DAMPING_PART_STIFFNESS specifies parts, damp those parts' nodes only
    - Otherwise damp exactly what Vol I R17 p.15-8 says *DAMPING_GLOBAL damps:
      "the nodes of deformable bodies and ... the mass center of the rigid
      bodies" — every node-carrying element family, the *ELEMENT_MASS nodes,
      and each /RBODY's main node. ``rbody_info`` supplies the last of those;
      when it is omitted (a direct call in a test) the rigid mass centres are
      simply absent from the group.
    OpenRadioss /DAMP does NOT accept grnod_ID=0 as "all nodes" — it is starter
    ERROR 171 (RAYLEIGH DAMPING NONEXISTENT / NODE GROUP ID=0 DOES NOT EXIST),
    so an explicit /GRNOD/NODE block is always emitted.

    Note: LS-DYNA's per-part β semantics (β_part = 2·coef/ω_max) cannot be
    exactly preserved without ω_max — we pass the largest coef as-is and warn
    if multiple parts have different values.
    """
    if state.damping_global is None and not state.damping_part_stiffness:
        return []

    alpha = state.damping_global.valdmp if state.damping_global else 0.0
    # Aggregate β from *DAMPING_PART_STIFFNESS — use max coef across all parts
    beta = max((d.coef for d in state.damping_part_stiffness), default=0.0)
    if alpha == 0.0 and beta == 0.0:
        # Two ways in, and the message has to name the one that applies:
        #   - *DAMPING_PART_STIFFNESS with every COEF = 0.0 — documented
        #     "Inactive" (Manual Vol I R16 p.15-12). With no *DAMPING_GLOBAL
        #     alongside it, this is also the deck that used to CRASH the whole
        #     conversion on `d.stx` further down.
        #   - *DAMPING_GLOBAL with VALDMP = 0.0, which on the corpus is usually
        #     a card whose damping really lives on its LCID curve — a field
        #     handle_damping_global already warns it does not read.
        # Either way there is nothing to apply, and emitting the card anyway
        # costs a /GRNOD over every deformable node in the model plus a /DAMP
        # that damps exactly zero. Same rule _make_damping_part_mass applies to
        # SF x curve == 0.
        why = []
        if state.damping_global is not None:
            g = state.damping_global
            why.append("*DAMPING_GLOBAL VALDMP=0" + (
                f" (its damping constant lives on LCID={g.lcid}, a curve this "
                "card does not read — reported separately above)"
                if g.lcid > 0 else ""))
        if state.damping_part_stiffness:
            why.append("*DAMPING_PART_STIFFNESS with every COEF=0.0, which "
                       "LS-DYNA documents as 'Inactive'")
        state.warn(
            "*DAMPING_*: the deck's damping resolves to alpha=0 AND beta=0 ("
            + "; ".join(why) + "), so there is nothing to apply — /DAMP is NOT "
            "emitted. The model runs UNDAMPED either way; what is dropped is an "
            "inert card plus a /GRNOD listing every deformable node.")
        return []
    target_pids: Set[int] = set()
    if state.damping_part_stiffness:
        coefs = [d.coef for d in state.damping_part_stiffness]
        target_pids = {d.pid for d in state.damping_part_stiffness}
        unique_pids = sorted(target_pids)
        if len(set(coefs)) > 1:
            state.warn(
                f"*DAMPING_PART_STIFFNESS: multiple different coefs across parts "
                f"{unique_pids} - using max={beta:.6G} as global beta (per-part "
                f"damping not directly mappable to /DAMP)."
            )
        state.warn(
            f"*DAMPING_PART_STIFFNESS pid(s) {unique_pids}: coef={beta:.6G} "
            f"used as /DAMP beta directly. LS-DYNA scales by 2/omega_max"
            f" - if waves aren't damped enough, try beta ~ 1e-7 to 1e-6."
        )

    # Resolve target node set.
    #
    # EVERY node-carrying element family counts — /DAMP is NODE-based Rayleigh
    # damping with no element-type restriction on any layer of its path. See
    # _damping_elem_nodes for the reader/group/engine source and for the
    # spring-only and beam-only measurements that recover alpha to 2e-5 %.
    # (Contrast /DAMP/FREQUENCY_RANGE, which enters as a Maxwell/Prony viscous
    # stress INSIDE the material law and really does reach only shells and
    # solids; that path's own warning stays right.)
    if target_pids:
        target_nodes = sorted(
            _damping_elem_nodes(state, lambda p: p in target_pids)
            - rigid_nodes)
        grnod_title = f"damping_target_pids_{'_'.join(str(p) for p in sorted(target_pids))}"
    else:
        # No specific parts → every node of every DEFORMABLE part, plus the
        # lumped masses, plus each rigid body's mass centre. That is the scope
        # LS-DYNA states verbatim, Vol I R17 p.15-8: "*DAMPING_GLOBAL ... Define
        # mass weighted nodal damping that applies globally to THE NODES OF
        # DEFORMABLE BODIES and to the MASS CENTER OF THE RIGID BODIES."
        #
        # Rigid SECONDARY nodes stay out and cost nothing either way: the
        # engine drops them itself at damping.F:150 (IF(TAGSLV_RBY(I)==0)), and
        # rbyonf.F:181-192 fills TAGSLV_RBY from LPBY — the SECONDARY list only
        # — so a /RBODY MAIN node is NOT tagged and IS damped. Putting the main
        # node in the group is therefore exactly LS-DYNA's "mass center of the
        # rigid bodies", not an approximation of it.
        # "Deformable" through the ONE predicate: a *DEFORMABLE_TO_RIGID part
        # is rigid from t = 0 and belongs on the mass-centre half of LS-DYNA's
        # own sentence, not on the nodal half. Equivalent on every shipping
        # deck (its nodes are in `rigid_nodes` and would be subtracted anyway)
        # and the degenerate arm is EMPTY by construction: a rigid part with no
        # elements contributes no node to _damping_elem_nodes either.
        rigid_parts = rigid_part_ids(state)

        def _deformable(pid: int) -> bool:
            return pid not in rigid_parts

        target_nodes_set = _damping_elem_nodes(state, _deformable) - rigid_nodes
        # *ELEMENT_MASS on an ordinary node: k2rad gives it an /ADMAS, so it
        # carries mass and LS-DYNA damps it. A dummy or a mechanism can be
        # built almost entirely out of these.
        target_nodes_set |= {n for n in state.added_node_masses
                             if n > 0 and n not in rigid_nodes}
        main_nodes = sorted({info["ind_node"]
                             for info in (rbody_info or {}).values()
                             if info.get("ind_node")})
        target_nodes_set |= set(main_nodes)
        target_nodes = sorted(target_nodes_set)
        grnod_title = "damping_target_all_deformable"

    if not target_nodes:
        state.warn(
            "*DAMPING_*: the deck carries no node that this card can damp — "
            "no /DAMP was emitted, so the model runs COMPLETELY UNDAMPED. "
            "/DAMP needs a /GRNOD (grnod_ID = 0 is starter ERROR 171, not "
            "'all nodes'), and the group is built from the nodes of every "
            "element family, the *ELEMENT_MASS nodes and the rigid bodies' "
            "main nodes; a deck with none of those has no mesh to damp.")
        return []

    # next_grnod_id, not next_id: k2rad re-emits every user *SET_NODE under its
    # own SID, so a set numbered at or above the auto-id base collides with this
    # synthesized group and the starter aborts the whole deck with ERROR 79
    # DUPLICATE ID / IN NODE GROUP DEFINITION. A no-op on any deck without such
    # a set, so no ordinary deck's ids shift.
    grnod_id = state.next_grnod_id()
    damp_id = state.next_id()
    lines = _emit_grnod_node(grnod_id, grnod_title, target_nodes)

    # *DAMPING_GLOBAL's STX..SRZ (Vol I R17 p.15-8, card 1 fields 3-8) are
    # "Scale factor on global x/y/z translational damping FORCES" and the three
    # rotational moments, and Remark 2 is exact about the default: "If STX =
    # STY = STZ = SRX = SRY = SRZ = 0.0 in the input above, all six values are
    # defaulted to unity." So all-six-zero means UNIFORM, and anything else
    # means LS-DYNA damps the stated DOFs and leaves the rest alone.
    #
    # Both branches below used to write the same uniform alpha on all six DOFs
    # — the Format-1 one with a warning, the Format-2 one in total silence — so
    # STX=1 with the other five zero removed energy from five DOFs the source
    # deck leaves undamped (#122 class). The map is the one the
    # *DAMPING_PART_MASS FLAG=1 emitter below already uses and that
    # hm_read_damp.F:104-115 reads as DAMPR(3/5/7/9/11/13):
    # alpha_i = alpha * ST_i in the order x, y, z, xx, yy, zz. Beta is NOT
    # scaled: it comes from *DAMPING_PART_STIFFNESS, a different card with no
    # per-DOF cells of its own.
    #
    # The guard on `d` is belt-and-braces: alpha comes ONLY from
    # *DAMPING_GLOBAL, so `d is None` implies alpha == 0, which the early
    # return above already took. Before that return existed, a
    # *DAMPING_PART_STIFFNESS whose every COEF was 0.0 reached here with d None
    # and reading d.stx aborted the WHOLE conversion with an AttributeError.
    d = state.damping_global
    scales = ((d.stx, d.sty, d.stz, d.srx, d.sry, d.srz) if d else (0.0,) * 6)
    per_dof = any(s != 0.0 for s in scales)
    if not per_dof:
        scales = (1.0,) * 6

    # If only α, no β and no per-DOF factors, use Format 1 (smaller deck).
    if beta == 0.0 and not per_dof:
        # The /DAMP card always reads Beta from cols 21-40 — there is no
        # "alpha-only" card layout. Beta must be written explicitly as 0,
        # otherwise the grnod_ID digits land in the Beta field and are parsed
        # as a (huge) stiffness-damping coefficient.
        lines += [
            f"/DAMP/{damp_id}",
            f"Rayleigh mass damping (alpha={alpha:.6G})",
            _DAMP_CARD1_HDR,
            f"{_f(alpha)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
            HDR,
        ]
        return lines

    # Format 2: per-DOF α + β. The PRESENCE of the five extra cards is what
    # selects the per-DOF reading — there is no explicit switch column.
    ax, ay, az, axx, ayy, azz = (alpha * s for s in scales)
    if per_dof:
        title = (f"Rayleigh damping (alpha={alpha:.6G} x STX..SRZ"
                 + (f", beta={beta:.6G}" if beta else "") + ")")
        zeroed = [n for n, s in zip(("STX", "STY", "STZ", "SRX", "SRY", "SRZ"),
                                    scales) if s == 0.0]
        if zeroed:
            # The cell names carry the DOF: ST* is a translation, SR* a
            # rotation. Deriving a bare axis letter from the last character
            # ("z" for both STZ and SRZ) would make the two indistinguishable,
            # so the cells are named and nothing is derived from them.
            state.warn(
                f"*DAMPING_GLOBAL: {', '.join(zeroed)} = 0.0 while the others "
                "are not, so Vol I R17 p.15-9 Remark 2's all-six-zero unity "
                "default does NOT apply — LS-DYNA leaves the degrees of "
                "freedom those cells name undamped, and so does the emitted "
                "/DAMP (Format 2, alpha_i = VALDMP x ST_i in the order x, y, "
                "z, xx, yy, zz). Check this is intended: mass damping on a "
                "subset of the DOFs is unusual outside a 2-D or planar "
                "idealisation.")
    else:
        title = f"Rayleigh damping (alpha={alpha:.6G}, beta={beta:.6G})"
    lines += [
        f"/DAMP/{damp_id}",
        title,
        _DAMP_CARD1_HDR,
        f"{_f(ax)}{_f(beta)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
        f"{_f(ay)}{_f(beta)}",
        f"{_f(az)}{_f(beta)}",
        f"{_f(axx)}{_f(beta)}",
        f"{_f(ayy)}{_f(beta)}",
        f"{_f(azz)}{_f(beta)}",
        HDR,
    ]
    return lines


def _damping_curve_constant(state: ConversionState, lcid: int,
                            what: str) -> Optional[float]:
    """The single ordinate a /BEGIN 2022 /DAMP can carry for curve *lcid*.

    LS-DYNA's *DAMPING_PART_MASS states its damping constant as ``D_s(t) =
    SF * f_LCID(t)``; plain /DAMP has only a scalar ``Alpha``, and the Radioss
    card that DOES take a function — /DAMP/FUNCT, whose engine kernel computes
    ``alpha = f(t)*Alpha*Alpha_dir`` (``damping_funct_ini.F90:80-99``) — first
    exists in ``radioss2026/DAMP/Damp_funct.cfg``, far above the /BEGIN 2022
    this converter writes.

    So the curve is reduced to its ordinate at the first abscissa. That is
    EXACT for the flat curves these decks almost always use (the corpus case
    ``11.3.sqt_iga_s.k`` is ``(0, 200) (0.01, 200)``), and is warned about
    otherwise. Returns None when the curve cannot be used at all.
    """
    curve = state.curves.get(lcid)
    if curve is None or not curve.pts:
        state.warn(
            f"{what}: load curve {lcid} is not defined in this deck (or has no "
            "points) — the damping constant comes ENTIRELY from that curve, so "
            "the card is DROPPED and those parts run UNDAMPED.")
        return None
    ordinates = [o for _, o in curve.pts]
    value = ordinates[0]
    if any(o != value for o in ordinates):
        state.warn(
            f"{what}: load curve {lcid} is time-VARYING "
            f"(ordinates {min(ordinates):.6G}..{max(ordinates):.6G}); a "
            f"/BEGIN 2022 /DAMP carries a constant Alpha only, so the value at "
            f"the first point ({value:.6G}) is used for the whole run and the "
            "time variation is LOST. The Radioss card that takes a function, "
            "/DAMP/FUNCT, is a radioss2026 keyword.")
    return value


def _make_damping_part_mass(state: ConversionState,
                            rigid_nodes: Set[int]) -> List[str]:
    """*DAMPING_PART_MASS / _SET -> one part-scoped /DAMP per card.

    Both sides apply the SAME force. LS-DYNA (Manual Vol I R16 p.15-8):
    ``F_damp = D_s*m*v``. Radioss ``DAMPING51`` (``engine/source/assembly/
    damping.F:127-170``) subtracts ``DAMP_A*V`` from the nodal acceleration,
    i.e. ``F = -Alpha*m*v``. So ``Alpha = D_s = SF * curve``, with no unit
    conversion and no frequency term — this is the one damping keyword of the
    batch that needs no version bump at all, because plain /DAMP has been
    readable since radioss42.

    dyna2rad does NOT convert this keyword: ``convertdampings.cxx`` runs exactly
    four converters (:38-44) and its only ``SelectionRead`` calls are at lines
    51/167/247/321 — GLOBAL, PART_STIFFNESS, RELATIVE, FREQUENCY_RANGE. The card
    parses cleanly into its model (registered in every profile's
    ``data_hierarchy.cfg`` as ``DAMPING/DampMass.cfg``) and is then silently
    dropped. k2rad converting it is a deliberate super-set, not a parity item.

    Scoping: LS-DYNA damps the PART's nodes; Radioss /DAMP takes a grnod, so one
    /GRNOD/NODE is emitted per card (``grnod_ID = 0`` is NOT "all nodes" on this
    card — see _make_damping).
    """
    if not state.damping_part_mass:
        return []
    lines: List[str] = []
    # LS-DYNA Manual Vol I R16 p.15-9: "cannot be combined with
    # *DAMPING_GLOBAL". Radioss would happily apply both (hm_read_damp.F:146
    # loops over every /DAMP card and damping.F:101 sums their contributions),
    # so the deck would come out MORE damped than LS-DYNA would have run it.
    if state.damping_global is not None:
        state.warn(
            "*DAMPING_PART_MASS: the deck also carries *DAMPING_GLOBAL, which "
            "LS-DYNA forbids combining with it. Radioss applies every /DAMP "
            "card additively, so the converted model is damped by the SUM of "
            "the two — remove one of them.")
    # The /DAMP that _make_damping builds from *DAMPING_PART_STIFFNESS carries a
    # non-zero Beta, and Beta is the term that a shared history buffer corrupts.
    # The clash is on NODES, not on part ids: two conformally meshed parts share
    # the nodes along their common edge, so a part-id intersection would miss
    # exactly the case that bites. And the pid set has to be the one
    # _make_damping actually puts in that /GRNOD — ALL *DAMPING_PART_STIFFNESS
    # pids, unfiltered — not just the ones whose own COEF is non-zero: the
    # single card carries beta = max(coefs), so a part written with COEF 0.0
    # still rides inside the beta-bearing group and its nodes still collide.
    # What decides whether there is a clash at all is whether that MAXIMUM is
    # non-zero.
    stiff_nodes: Set[int] = set()
    stiff_pids = {d.pid for d in state.damping_part_stiffness}
    if stiff_pids and max(d.coef for d in state.damping_part_stiffness) != 0.0:
        stiff_nodes = set(_damping_part_nodes(state, stiff_pids, rigid_nodes))
    for dm in state.damping_part_mass:
        kw = "*DAMPING_PART_MASS_SET" if dm.is_set else "*DAMPING_PART_MASS"
        what = f"{kw} ({'PSID' if dm.is_set else 'PID'}={dm.pid})"
        if dm.lcid == 0:
            state.warn(
                f"{what}: LCID=0. Unlike *DAMPING_GLOBAL this card has NO "
                "constant-value column — the damping constant is read entirely "
                "off the curve — so there is nothing to apply; card DROPPED.")
            continue
        value = _damping_curve_constant(state, dm.lcid, what)
        if value is None:
            continue
        alpha = dm.sf * value
        if alpha == 0.0:
            state.warn(
                f"{what}: SF={dm.sf:.6G} x curve {dm.lcid} = 0, so the card "
                "damps nothing — /DAMP not emitted for it. (If the curve is "
                "flat at zero it really does ask for no damping; if it only "
                "STARTS at zero and ramps up, the time variation that is being "
                "lost has been reported separately — a /BEGIN 2022 /DAMP "
                "carries a constant Alpha and cannot ramp.)")
            continue
        pids = _damping_resolve_pids(state, dm.pid, dm.is_set, what)
        if pids is None:
            continue
        if not pids:
            # An empty (or fully unresolvable) *SET_PART. Distinguished from the
            # "no deformable mesh" case below, which would otherwise report
            # "part(s) [] carry no ... nodes" and name the wrong cause — the
            # same branch _make_damping_frequency_range already has.
            state.warn(f"{what}: *SET_PART {dm.pid} resolved to no existing "
                       "part — /DAMP not emitted for this card.")
            continue
        nodes = _damping_part_nodes(state, set(pids), rigid_nodes)
        if not nodes:
            state.warn(
                f"{what}: part(s) {sorted(pids)} carry no deformable node at "
                "all — every element on them belongs to a rigid body, or they "
                "have no mesh — so /DAMP was not emitted for this card. "
                "(Beams, springs, belts, thick shells and SPH particles DO "
                "count towards this group; they were excluded until the "
                "SIDE-DEFECT batch, which is why this message used to fire on "
                "a perfectly damped beam part.)")
            continue
        # Per-DOF scale factors. LS-DYNA FLAG=1 means "the global components of
        # the damping forces require separate scale factors"; Radioss holds them
        # in the /DAMP Format-2 per-DOF rows, so alpha_i = SF*curve*ST_i.
        scales = (dm.stx, dm.sty, dm.stz, dm.srx, dm.sry, dm.srz)
        per_dof = dm.flag == 1
        if per_dof and not any(s != 0.0 for s in scales):
            state.warn(
                f"{what}: FLAG=1 requests per-DOF damping scale factors but "
                "STX..SRZ are all 0.0, which would scale the damping to zero "
                "on every DOF. Read as 'uniform' (the all-six-zero convention "
                f"dyna2rad applies on /DAMP/FUNCT) and alpha={alpha:.6G} is "
                "used on all six DOFs.")
            per_dof = False
        if shared := sorted(stiff_nodes.intersection(nodes)):
            # Two /DAMP cards sharing a node share the single per-node history
            # buffer DAMP(1:6,I): damping.F:145 stores A() into it and the next
            # card overwrites, so the FIRST card's Beta term reads a foreign
            # acceleration from the following cycle on. Alpha-only overlap is
            # harmless, which is why only the Beta-bearing case is reported.
            state.warn(
                f"{what}: {len(shared)} node(s) of part(s) {sorted(pids)} "
                f"(e.g. {shared[:5]}) are ALSO in the stiffness-damping /DAMP "
                "built from *DAMPING_PART_STIFFNESS on part(s) "
                f"{sorted(stiff_pids)} — conformally meshed parts share the "
                "nodes along their common edge even when the part lists are "
                "disjoint. Radioss keeps ONE per-node damping history buffer, "
                "so two /DAMP cards sharing a node corrupt the Beta "
                "(stiffness) term of whichever is read first (2022 Reference "
                "Guide p.130 comment 4). Merge them or scope them apart.")
        grnod_id = state.next_grnod_id()
        damp_id = state.next_id()
        lines += _emit_grnod_node(
            grnod_id, f"damping_part_mass_{'pset' if dm.is_set else 'pid'}"
                      f"_{dm.pid}", nodes)
        if not per_dof:
            lines += [
                f"/DAMP/{damp_id}",
                f"Mass damping *DAMPING_PART_MASS lcid={dm.lcid} "
                f"(alpha={alpha:.6G})",
                _DAMP_CARD1_HDR,
                f"{_f(alpha)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
                HDR,
            ]
        else:
            ax, ay, az, axx, ayy, azz = (alpha * s for s in scales)
            # Format 2: the PRESENCE of the five extra cards is what sets
            # Mass_Damp_Factor_Option — there is no explicit switch column.
            lines += [
                f"/DAMP/{damp_id}",
                f"Mass damping *DAMPING_PART_MASS lcid={dm.lcid} per-DOF "
                f"(alpha={alpha:.6G} x STX..SRZ)",
                _DAMP_CARD1_HDR,
                f"{_f(ax)}{_f(0.0)}{_i(grnod_id)}{_i(0)}{_f(0.0)}{_f(1.0E30)}",
                f"{_f(ay)}{_f(0.0)}",
                f"{_f(az)}{_f(0.0)}",
                f"{_f(axx)}{_f(0.0)}",
                f"{_f(ayy)}{_f(0.0)}",
                f"{_f(azz)}{_f(0.0)}",
                HDR,
            ]
    if not lines:
        return []
    return ["#-  PART MASS DAMPING (*DAMPING_PART_MASS -> /DAMP):", HDR] + lines


def _dfr_what(dfr: DampingFrequencyRange) -> str:
    """The keyword spelling + card values that every warning below leads with.

    Built in one place so the two passes of _make_damping_frequency_range
    cannot drift apart in how they name the same card.
    """
    kw = ("*DAMPING_FREQUENCY_RANGE_DEFORM_DMIG" if dfr.dmig else
          "*DAMPING_FREQUENCY_RANGE_DEFORM" if dfr.deform else
          "*DAMPING_FREQUENCY_RANGE")
    return (f"{kw} (CDAMP={dfr.cdamp:.6G}, FLOW={dfr.flow:.6G}, "
            f"FHIGH={dfr.fhigh:.6G})")


def _make_damping_frequency_range(state: ConversionState) -> List[str]:
    """*DAMPING_FREQUENCY_RANGE[_DEFORM] -> /DAMP/FREQUENCY_RANGE.

    Card layout, ``radioss2025/DAMP/Damp_freq_range.cfg``::

        /DAMP/FREQUENCY_RANGE/damp_ID
        title
        #              Cdamp                     grpart_ID          Tstart      Tstop
                %20lg   (20 dead cols)      %10d   (10 dead cols)    %20lg      %20lg
        #           Freq_low           Freq_high
                %20lg               %20lg

    The two dead 10-column slots on card 1 are real: the card was laid out to
    keep ``grpart_ID`` in the same column block as the sibling cards' ``grnod_id``
    / ``skew_id``. They must be spaces.

    VERSION GATE — measured, not assumed. ``radioss2022/data_hierarchy.cfg``
    registers only ``DAMP`` and ``DAMP_INTER`` under ``DAMPING``, so a /BEGIN
    2022 deck names a keyword its registry does not carry. Measured on
    starter_win64 (2026-05-20) with twin decks differing only in /BEGIN: at 2022
    the starter draws ``WARNING ID : 100211  Unsupported option
    /DAMP/FREQUENCY_RANGE in format < 2025`` and then reads the card ANYWAY,
    with every field correct — echo ``PART GROUP ID 91004 / DAMPING RATIO
    2.0E-02 / LOWEST FREQUENCY 10.0 / HIGHEST FREQUENCY 200.0``, identical to
    the /BEGIN 2025 run. (The cfg has exactly one FORMAT block, radioss2025, so
    there is no older layout for the reader to fall back to.) The card is
    therefore emitted, with the warning restated for the user — the opposite
    call from ``*DAMPING_RELATIVE``, whose twin measurement came out MISREAD.

    Fidelity: the single Radioss card IS LS-DYNA's ``_DEFORM`` behaviour.
    Damping is applied as a Maxwell/Prony viscous stress inside the material law
    (``damping_range_{shell,shell_mom,solid}.F90``, reached through
    ``mulawc.F90:1974`` / ``viscmain.F``), gated by the static per-element-group
    flag ``IPARG(93)`` — never as a nodal force, so rigid-body motion is not
    damped and natural frequencies shift UP. Radioss has no nodal variant, so
    the blank (non-DEFORM) LS-DYNA option is an approximation and says so.
    """
    if not state.damping_frequency_range:
        return []
    parts_all = sorted(state.parts)
    # Parts Radioss can actually reach with frequency-range damping — see the
    # element-scope warning below. THICK SHELLS were deliberately left out with
    # the #120 batch and SPH PARTICLES are left out here for the same reason:
    # unlike /DAMP, this damping is a Maxwell/Prony viscous stress INSIDE the
    # material law, reached only through the IPARG(93)-gated shell and solid
    # paths (damping_range_{shell,shell_mom,solid}.F90) — there is no SPH
    # element loop that reads that flag at all, so listing a particle part here
    # would claim a scope the engine never visits.
    meshed_pids = ({e.pid for e in state.shell_elems}
                   | {e.pid for e in state.solid_elems})

    # Pass 1: validate, then resolve each surviving card's part scope, so the
    # PSID=0 complement and the overlap check both see the whole picture
    # (dyna2rad builds the same union at convertdampings.cxx:323-334). The
    # validation has to happen HERE and not in pass 2: `claimed` is what a
    # PSID=0 card subtracts, and subtracting the parts of a card that is about
    # to be dropped would shrink the complement for no reason. Resolving a DMIG
    # card's PSID would likewise be wrong — there it is a SUPERELEMENT id, not
    # a *SET_PART id, and would draw a misleading "set is not defined" warning.
    resolved: List[Tuple[DampingFrequencyRange, Optional[List[int]]]] = []
    claimed: Set[int] = set()
    for dfr in state.damping_frequency_range:
        what = _dfr_what(dfr)
        if dfr.dmig:
            state.warn(
                f"{what}: the _DMIG option damps a SUPERELEMENT (PSID is a "
                "superelement id, not a part set). k2rad converts no "
                "superelement keywords and Radioss has no equivalent — card "
                "DROPPED.")
            continue
        # The starter's KEY(1:4)=='FREQ' branch validates NEITHER bound. With
        # Freq_low = 0 the starter's f_mid = sqrt(f_low*f_high) is 0, the 3x3
        # collocation matrix of damping_range_compute_param.F90 fills with 0/0
        # and NaN alpha/tau propagate into every element of the group.
        if dfr.flow <= 0.0 or dfr.fhigh <= dfr.flow:
            state.warn(
                f"{what}: needs 0 < FLOW < FHIGH. The Radioss starter fits "
                "three Maxwell branches at [FLOW, sqrt(FLOW*FHIGH), FHIGH] and "
                "validates neither bound, so this card would make that 3x3 "
                "system singular and push NaN damping parameters into every "
                "element of the group — card DROPPED.")
            continue
        if dfr.cdamp <= 0.0:
            state.warn(f"{what}: CDAMP <= 0 damps nothing — card DROPPED.")
            continue
        if dfr.psid == 0:
            resolved.append((dfr, None))
            continue
        pids = _damping_resolve_pids(state, dfr.psid, True, f"{what} PSID")
        if pids is None:
            continue                     # unresolvable PSID, already warned
        if not pids:
            state.warn(f"{what}: *SET_PART {dfr.psid} resolved to no existing "
                       "part — card DROPPED.")
            continue
        resolved.append((dfr, pids))
        claimed |= set(pids)

    lines: List[str] = []
    tagged: Dict[int, str] = {}          # part id -> the card that claimed it
    n_all_parts = 0
    gate_warned = False
    for dfr, pids in resolved:
        # Pass 2 never sees a DMIG card — pass 1 drops those — so _dfr_what's
        # third spelling cannot appear here.
        what = _dfr_what(dfr)

        # ── scope ────────────────────────────────────────────────────────────
        pre: List[str] = []
        if dfr.psid != 0:
            scope = sorted(set(pids or []))
            grpart_id = state.next_id()
            pre = _emit_grpart_part(
                grpart_id, f"damping_freq_range_pset_{dfr.psid}", scope)
        else:
            # LS-DYNA: "If PSID = 0, the damping is applied to all parts EXCEPT
            # those referred to by other *DAMPING_FREQUENCY_RANGE cards."
            # Radioss grpart_ID=0 means all parts with no exclusion AND, worse,
            # re-tags every part (hm_read_damp.F:305-307 DAMP_RANGE_PART(J)=I),
            # silently overriding every earlier card. So the complement is made
            # explicit whenever anything else claimed parts.
            n_all_parts += 1
            scope = [p for p in parts_all if p not in claimed]
            if not claimed:
                grpart_id = 0
                pre = []
            elif not scope:
                state.warn(
                    f"{what}: PSID=0 means 'all parts except those claimed by "
                    "other *DAMPING_FREQUENCY_RANGE cards', and the other "
                    "cards already claim every part in the deck — nothing "
                    "left to damp, card DROPPED.")
                continue
            else:
                grpart_id = state.next_id()
                pre = _emit_grpart_part(
                    grpart_id, "damping_freq_range_all_other_parts", scope)
        if n_all_parts == 2:
            state.warn(
                f"{what}: a SECOND *DAMPING_FREQUENCY_RANGE card also has "
                "PSID=0. Both then cover the same complement set, and Radioss "
                "resolves overlaps by plain overwrite (hm_read_damp.F:299-307) "
                "— the LAST card silently wins on every shared part.")
        if overlap := sorted(p for p in scope if p in tagged):
            state.warn(
                f"{what}: part(s) {overlap} are already damped by "
                f"{tagged[overlap[0]]}. Radioss allows only ONE "
                "/DAMP/FREQUENCY_RANGE per part and resolves the clash by "
                "overwrite, so the LAST card silently wins on them.")
        for p in scope:
            tagged[p] = what

        # ── fidelity warnings ────────────────────────────────────────────────
        if not gate_warned:
            gate_warned = True
            state.warn(
                "*DAMPING_FREQUENCY_RANGE -> /DAMP/FREQUENCY_RANGE is a "
                "radioss2025 keyword and k2rad writes /BEGIN 2022, so the "
                "starter draws 'WARNING ID : 100211 Unsupported option "
                "/DAMP/FREQUENCY_RANGE in format < 2025'. Measured on "
                "starter_win64: the warning is advisory — the card is read "
                "with every field correct (Cdamp/grpart_ID/Freq_low/Freq_high "
                "echo identically under /BEGIN 2022 and 2025), so it is "
                "emitted rather than dropped. Bumping /BEGIN to 2025 by hand "
                "silences it, but note that a 2025 read then raises "
                "'WARNING ID : 100217 card is missing' on the OTHER cards "
                "k2rad writes in the 2022 layout (several gained a trailing "
                "card by 2025 — measured, about a dozen on a small deck, with "
                "0 ERRORS and every field still read back identically).")
        if not dfr.deform:
            state.warn(
                f"{what}: this is the BLANK option, which damps global NODE "
                "motion. Radioss has only the element-level form — damping "
                "enters as a Maxwell/Prony viscous stress inside the material "
                "law (damping_range_shell/solid.F90, gated by IPARG(93)), "
                "which is LS-DYNA's _DEFORM behaviour. Two consequences on "
                "this deck: rigid-body motion is NOT damped, and natural "
                "frequencies shift UP instead of down (Manual Vol I R16 "
                "Remark 3).")
        # Element scope — applies to BOTH options, so it lives outside the
        # blank-option branch. LS-DYNA damps solids, beams, shells, thick
        # shells and discrete elements (Manual Vol I R16 Remark 4); Radioss
        # reaches only shells and solids (damping_range_shell / _shell_mom /
        # _solid.F90), and LAW25 shells are excluded outright
        # (mulawc.F90:1972). Under _DEFORM — advertised as the clean 1:1 —
        # a beam-only or tshell-only part would otherwise lose ALL its damping
        # without a word.
        if unmeshed := sorted(p for p in scope if p not in meshed_pids):
            shown = (f"{unmeshed[:10]} (+{len(unmeshed) - 10} more)"
                     if len(unmeshed) > 10 else str(unmeshed))
            state.warn(
                f"{what}: {len(unmeshed)} part(s) {shown} in the damped scope "
                "carry no shell or solid element. Radioss applies "
                "frequency-range damping inside the shell and solid material "
                "laws only (damping_range_shell/_shell_mom/_solid.F90, and "
                "LAW25 shells are excluded outright, mulawc.F90:1972), while "
                "LS-DYNA damps solids, beams, shells, thick shells and "
                "discrete elements (Manual Vol I R16 Remark 4) — those part(s) "
                "come out COMPLETELY UNDAMPED.")
        # LAW25 is the sibling case of the same warning: mulawc.F90:1963/1972
        # skip prony_modelc AND damping_range_shell whenever `ilaw == 25`, so a
        # *MAT_COMPOSITE_DAMAGE shell part (the only LAW25 producer k2rad has)
        # is meshed, is inside the damped scope, and still gets nothing.
        # Gating only on "carries no shell or solid element" would let it
        # through in silence — the #124 "a guard gated on one condition goes
        # dead on its sibling" class, on a warning whose own text already names
        # the exclusion.
        #
        # Through _part_mat_mids, not state.parts[p].mid: a *PART_COMPOSITE's
        # fallback PartData carries only the FIRST real ply's MID, so a MAT_022
        # sitting in layer 2..n of a layup is meshed, is inside the damped
        # scope, runs on LAW25 and would still be reported as damped.
        from .composites import _part_mat_mids
        if law25 := sorted(p for p in scope
                           if p in meshed_pids
                           and any(_target_mat_law(state, m) == 25
                                   for m in _part_mat_mids(state, p))):
            shown = (f"{law25[:10]} (+{len(law25) - 10} more)"
                     if len(law25) > 10 else str(law25))
            state.warn(
                f"{what}: {len(law25)} part(s) {shown} in the damped scope "
                "run on /MAT/LAW25 (COMPSH), which mulawc.F90:1972 excludes "
                "from damping_range_shell outright (and :1963 from the Prony "
                "branch) — those part(s) come out COMPLETELY UNDAMPED even "
                "though they are meshed with shells. LS-DYNA applies "
                "*DAMPING_FREQUENCY_RANGE to them like any other material. "
                "Move the part to a damped law, or add the damping as a "
                "global /DAMP, if it matters.")
        if dfr.pidrel:
            state.warn(
                f"{what}: PIDREL={dfr.pidrel} asks for damping of the motion "
                "RELATIVE to that rigid body. /DAMP/FREQUENCY_RANGE has no "
                "such field at any format version (the relative-velocity "
                "reference lives on /DAMP/VREL, a different card) — DROPPED, "
                "so the rigid body's own motion is damped along with "
                "everything else.")
        if dfr.iflg == 0:
            state.warn(
                f"{what}: IFLG=0 selects LS-DYNA's ITERATIVE fit (errors ~1% "
                "of the target CDAMP). Radioss implements a one-shot 3-point "
                "collocation instead (damping_range_compute_param.F90 has no "
                "refinement loop), i.e. the analogue of IFLG=1. Expect the "
                "achieved damping to sit BELOW target across the band — about "
                "-8%..0% at CDAMP=0.01, about -26%..-4% at CDAMP=0.05.")
        if dfr.icard2 == 1:
            state.warn(
                f"{what}: ICARD2=1 supplies CDAMPV={dfr.cdampv:.6G} "
                f"(volumetric/pressure damping for solids) and IPWP={dfr.ipwp} "
                "(pore pressure). Radioss applies one damping ratio to both "
                "the deviatoric and the volumetric branch (damping_range_"
                "solid.F90 scales gv from the shear modulus and kv from Young "
                "with the SAME alpha) and has no pore-pressure switch — both "
                "fields are DROPPED and CDAMP alone is used.")

        # ── the card ─────────────────────────────────────────────────────────
        damp_id = state.next_id()
        scope_txt = "all other parts" if dfr.psid == 0 and grpart_id else \
                    "all parts" if dfr.psid == 0 else f"pset {dfr.psid}"
        lines += pre
        lines += [
            f"/DAMP/FREQUENCY_RANGE/{damp_id}",
            f"Frequency-range damping {dfr.cdamp:.6G} over "
            f"{dfr.flow:.6G}-{dfr.fhigh:.6G} Hz ({scope_txt})",
            "#              Cdamp                     grpart_ID"
            "                        Tstart               Tstop",
            # Tstart/Tstop are read and echoed but INERT for this type: both
            # nodal kernels skip it (damping.F:120-127 guards on
            # FL_FREQ_RANGE==0, DAMPING44 likewise) and the material-law path
            # has no time argument at all. Written as the neutral 0 / 1e30.
            f"{_f(dfr.cdamp)}{' ' * 20}{_i(grpart_id)}{' ' * 10}"
            f"{_f(0.0)}{_f(1.0E30)}",
            "#           Freq_low           Freq_high",
            f"{_f(dfr.flow)}{_f(dfr.fhigh)}",
            HDR,
        ]
    if not lines:
        return []
    return ["#-  FREQUENCY-RANGE DAMPING "
            "(*DAMPING_FREQUENCY_RANGE -> /DAMP/FREQUENCY_RANGE):", HDR] + lines


def _resolve_damping_relative(state: ConversionState,
                              rbody_info: Dict[int, dict]) -> List[str]:
    """*DAMPING_RELATIVE -> /DAMP/VREL: resolved, reported, NOT emitted.

    The mapping itself is exact. LS-DYNA Remark 3 gives ``F = -(D*m*v) -
    (DV2*m*v^2)`` with ``D = 4*pi*CDAMP*FREQ`` and ``v`` relative to the rigid
    body ``PIDRB``; the Radioss engine computes ``damp_a = fact*Alpha_x*4*pi*
    freq`` (``damping_vref_compute_dampa.F90``) and applies ``F = -alpha*m*
    (v - v_ref)`` (``damping.F:231-266``). Field for field:
    ``CDAMP->Alpha_x``, ``FREQ->Freq``, ``PIDRB->RbodyID``, ``DV2->Alpha2_x``,
    ``LCID->FuncID``, ``PSID->grnod_id``.

    VERSION GATE — measured, and it fails. /DAMP/VREL first appears in
    ``radioss2023/DAMP/Damp_Vrel.cfg``; the 2023 block is REDUCED (``Alpha_x
    <blank> grnod_id skew_id Tstart Tstop`` / ``Alpha_y`` / ``Alpha_z``) and
    only radioss2024 adds the ``Freq RbodyID FuncID Xscale`` card and the
    quadratic columns. Measured on starter_win64 (2026-05-20), /BEGIN 2022 vs
    2025 twins carrying the identical 6-line 2024-format card:

      2025  DAMPING FUNCTION ID 91002 / X 3.0E-02 / Y 3.0E-02 / Z 3.0E-02
            DAMPING FREQUENCY 12.5                                    (correct)
      2022  WARNING 100211 "Unsupported option /DAMP/VREL in format < 2023"
            WARNING 100213 "unsupported field exists at the end of line"
            DAMPING FUNCTION ID 0 / X 3.0E-02 / Y 12.5 / Z 3.0E-02
            DAMPING FREQUENCY 0.0

    i.e. at 2022 the reader falls back to the reduced 2023 layout, swallows the
    ``Freq RbodyID FuncID Xscale`` card as if it were the ``Alpha_y`` row, and
    leaves ``Freq`` at 0. That is not a degraded card, it is a wrong one twice
    over: ``Alpha_y`` becomes 12.5 instead of 0.03, and with ``Freq == 0`` the
    engine takes the other branch of ``damping_vref_compute_dampa.F90``,
    ``damp_a = Alpha_x/dt_initial`` — for a dt around 1e-6 that is roughly
    twelve orders of magnitude away from the intended ``4*pi*CDAMP*FREQ``.

    Emitting a card that reads as something else is exactly what
    ``_resolve_contact_interior`` refused to do, so this follows that
    precedent: resolve everything, name every resolved id in the warning so the
    user can paste the correct card into a /BEGIN 2024 deck by hand, and emit
    nothing. Returns [] always; the return type keeps it registry-shaped.
    """
    if not state.damping_relative:
        return []
    state.note_recognized_not_emitted(
        "*DAMPING_RELATIVE",
        "its Radioss counterpart /DAMP/VREL needs the radioss2024 card format; "
        "under the /BEGIN 2022 this converter writes, the starter falls back "
        "to the reduced radioss2023 layout and MISREADS it (measured: Freq "
        "lost to 0, which switches the engine to the alpha=Cdamp/dt_initial "
        "branch, and the Freq value lands in Alpha_y) — the resolved card is "
        "reported in a warning instead")
    for dr in state.damping_relative:
        what = f"*DAMPING_RELATIVE (CDAMP={dr.cdamp:.6G}, FREQ={dr.freq:.6G})"

        if dr.freq <= 0.0:
            # Altair's online card documents the Freq=0 branch as
            # "alpha = CDAMP * dt * Func(t)"; the shipped engine DIVIDES by the
            # initial timestep instead (damping_vref_compute_dampa.F90:
            # `damp_a(1) = fact*dampr(3,id)*(one/dtini)`), latched on first
            # activation. At dt ~ 1e-6 the two readings are ~1e12 apart, so the
            # card is unusable at Freq=0 whichever /BEGIN it lands in.
            state.warn(
                f"{what}: FREQ is 0, and LS-DYNA reads CDAMP as the fraction of "
                "critical damping AT that frequency (D = 4*pi*CDAMP*FREQ), so "
                "the card asks for zero damping. Radioss does something else "
                "entirely on Freq=0 — the engine divides by the INITIAL "
                "timestep (alpha = Alpha_x/dt_initial), which its own "
                "documentation describes as a multiplication; the two readings "
                "are about 1e12 apart at a dt of 1e-6. Set a real FREQ (the "
                "lowest mode of interest) before using the resolved card below.")

        # RbodyID: PIDRB's OWN part, not "any /RBODY built from that part's
        # material" — dyna2rad walks PIDRB -> MID -> conversion log
        # (convertdampings.cxx:274-293) and, when several parts share one
        # *MAT_RIGID, its loop lets the LAST /RBODY win, which is generally not
        # PIDRB's. k2rad keys rbody_info by part id, so the lookup is direct.
        # The emitted /RBODY id is the main node id (writer/rbody.py
        # _make_rbodies writes f"/RBODY/{ind_node}"; a line number here went
        # stale with every edit above it, so the function is named instead).
        rbody_id = 0
        if dr.pidrb <= 0:
            state.warn(
                f"{what}: PIDRB is 0, so there is no rigid body to measure "
                "velocity against — the card would degrade to ordinary "
                "absolute damping, which is not what *DAMPING_RELATIVE means.")
        else:
            info = rbody_info.get(dr.pidrb)
            if info is None:
                state.warn(
                    f"{what}: PIDRB={dr.pidrb} is not a rigid body in the "
                    "converted deck (no *MAT_RIGID part and no "
                    "*CONSTRAINED_NODAL_RIGID_BODY of that id), so there is no "
                    "/RBODY for the relative-velocity reference to point at.")
            else:
                rbody_id = info["ind_node"]

        pids = _damping_resolve_pids(state, dr.psid, True, f"{what} PSID") \
            if dr.psid else None
        scope_txt = (f"*SET_PART {dr.psid} -> parts {sorted(pids)}"
                     if pids else
                     f"*SET_PART {dr.psid} (unresolved)" if dr.psid else
                     "PSID=0 (no part scope given)")

        # FuncID — THE deliberate deviation from dyna2rad. convertdampings.cxx:
        # 305 routes the CURVE id through GetRadiossSetIdFromLsdSet(lcid,
        # "*SET_PART") with the SET entity type, a copy-paste of the PSID line
        # above it. When that id also numbers two or more *SET_* families the
        # part-set branch fires and a part-set id is written into a /FUNCT slot
        # — either pointing at the wrong curve (silent) or at no curve at all
        # (starter ERROR 3049). k2rad resolves LCID against state.curves, the
        # *DEFINE_CURVE -> /FUNCT table, and never against part_sets.
        func_id = 0
        alpha_x = dr.cdamp
        if dr.lcid:
            if dr.lcid in state.table_1d_ids:
                state.warn(
                    f"{what}: LCID={dr.lcid} is consumed by a material through "
                    "a TABLE slot, so k2rad emits it as /TABLE/1/"
                    f"{dr.lcid} rather than /FUNCT/{dr.lcid} — a /DAMP/VREL "
                    "FuncID pointing at it would dangle (starter ERROR 3049). "
                    "The time-varying damping reference is DROPPED.")
            elif dr.lcid not in state.curves:
                state.warn(
                    f"{what}: LCID={dr.lcid} has no *DEFINE_CURVE in this deck "
                    "— a dangling FuncID is starter ERROR 3049, so the "
                    "time-varying damping reference is DROPPED.")
            else:
                func_id = dr.lcid
                # LS-DYNA: "CDAMP will be ignored if LCID is non-zero" — the
                # curve REPLACES the constant. Radioss MULTIPLIES: damp_a =
                # fact*Alpha_x*4*pi*freq. Copying CDAMP into Alpha_x alongside
                # a FuncID would therefore double-count, so Alpha_* becomes 1.0.
                alpha_x = 1.0

        alpha2 = dr.dv2
        if dr.dv2 != 0.0 and rbody_id == 0:
            # DAMPR(22:24) is referenced in exactly one engine file,
            # damping_vref_rby.F90:141-143, inside `if (id_rby > 0)`. The
            # grnod path of damping.F:231 never touches it.
            state.warn(
                f"{what}: DV2={dr.dv2:.6G} (quadratic velocity term) is only "
                "applied by Radioss on the rigid-body path — with no usable "
                "RbodyID the Alpha2_* columns are read and then ignored.")
            alpha2 = 0.0

        state.warn(
            f"{what}: NOT EMITTED. The Radioss equivalent /DAMP/VREL is a "
            "radioss2024 card and k2rad writes /BEGIN 2022, where the starter "
            "falls back to the reduced radioss2023 layout and MISREADS it "
            "(measured on starter_win64: WARNING 100211 + 100213, Freq lost to "
            "0 so the engine switches to the alpha=Cdamp/dt_initial branch — "
            "about 1e12 off for a dt of 1e-6 — and the Freq value lands in "
            "Alpha_y). Emitting a card that reads as something else would be "
            "silently wrong, so the run is left UNDAMPED for this card. "
            "Resolved mapping, ready to paste into a deck whose /BEGIN says "
            f"2024 or later: Alpha_x=Alpha_y=Alpha_z={alpha_x:.6G}, "
            f"Alpha2_x={alpha2:.6G}, Freq={dr.freq:.6G}, RbodyID={rbody_id} "
            f"(from PIDRB={dr.pidrb}), FuncID={func_id} (from LCID={dr.lcid}, "
            f"resolved through the *DEFINE_CURVE -> /FUNCT table), grnod_id = a "
            f"node group covering {scope_txt}. Note Xscale must stay 1.0: the "
            "starter reads it into DAMPR(27) and no engine file ever reads "
            "that slot back, so abscissa scaling has to be baked into the "
            "curve's own X values.")
    return []


def _make_free_node_constraints(state: ConversionState, rigid_nodes: Set[int]) -> List[str]:
    """Implicit guard: fix nodes attached to no element and no rigid body.

    A free node carries no stiffness, so its DOFs are zero rows in the implicit
    tangent → a singular matrix → the MUMPS factorization fails (or floods the
    solver with null pivots). LS-DYNA tolerates such reference nodes — e.g.
    *DEFINE_COORDINATE_NODES nodes (we bake those into /SKEW/FIX coordinates so
    they end up unreferenced) and lone origin markers — but OpenRadioss implicit
    does not. Constrain them: they carry no mass and no load, so pinning them
    changes nothing that moves.

    "They drive nothing" was the older wording and is no longer strictly true:
    the element-free nodes k2rad synthesizes for a /SECT reporting frame land
    in this set too, and those DO drive something — the frame the section
    reports in. The CONCLUSION survives (they are massless and forceless, so
    the constraint holds them exactly where the cross-section card placed
    them, which is what a fixed reporting frame is for), but a true conclusion
    resting on a false premise still misinforms, so the premise is stated as
    the one that actually holds.

    Nodes of a MOVING skew (/SKEW/MOV, *DEFINE_COORDINATE_NODES flag=1) are left
    free so the frame can co-rotate. Explicit runs skip this entirely.
    """
    if not state.is_implicit or not state.nodes:
        return []
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(e.nodes)
    for e in state.solid_elems:
        elem_nodes.update(e.nodes)
    # THICK SHELLS carry stiffness like any other /BRICK, so their nodes are
    # NOT free reference nodes. Leaving them out put a /BCS 111 111 on every
    # node of the mesh — the starter accepts that (a /BCS on real nodes is
    # legal, 0 ERRORS) and the model then simply cannot move. Every r14
    # *ELEMENT_TSHELL deck is implicit, so this guard sees them all.
    for e in state.tshell_elems:
        elem_nodes.update(e.nodes)
    # SPH PARTICLES are NOT free reference nodes. A particle carries mass and,
    # through its kernel, stiffness against every neighbour inside 2h — the
    # node's rows in the tangent are anything but zero. Leaving them out would
    # put a /BCS 111 111 on EVERY particle of the cloud, which the starter
    # accepts without a single error (a /BCS on real nodes is legal) and which
    # then freezes the whole SPH body in place. That is the #120 thick-shell
    # failure exactly: 0 starter errors, a model that cannot move. Every SPH
    # deck in the corpus is EXPLICIT and returns at the guard above, so no
    # corpus run exercises this — which is precisely why it is closed here on
    # principle and tested synthetically.
    for c in state.sph_elems:
        elem_nodes.update(c.nodes)
    # A TRUSS contributes ONLY (n1, n2). /TRUSS has no third-node column, so a
    # deck-stated N3 on an ELFORM=3 *ELEMENT_BEAM (two corpus decks do state a
    # real one, node 45012) is a node the truss does not stiffen — counting it
    # as "attached" would switch the implicit singularity guard OFF for it and
    # leave six zero rows in the tangent. That is the #120 failure mode with
    # the sign reversed: a genuinely free node left free, rather than a stiff
    # node clamped. Both carrier decks are explicit, so no corpus run reaches
    # this branch — closed on principle and tested synthetically, exactly as
    # the SPH arm above was.
    truss_pids = _truss_pids(state)
    for e in state.beam_elems:
        if e.pid in truss_pids:
            elem_nodes.update((e.n1, e.n2))
        else:
            elem_nodes.update((e.n1, e.n2, e.n3))
    # /SPRING connector nodes carry spring stiffness; the synthesized ground
    # nodes are already fully /BCS-fixed by the connector section.
    #
    # *ELEMENT_PLOTEL is deliberately NOT in this list: its /PROP/TYPE4 is
    # K=0/C=0 by construction, and r1len3.F:81-105 leaves STI at zero unless XK
    # or XC is non-zero, so a node whose only attachment is a PLOTEL has exactly
    # the same (zero) stiffness as a genuinely free node. Counting the drawing
    # line as an attachment would switch the singularity guard off for that
    # node — the same reasoning that makes a synthesized beam-orientation node
    # subtractable a few lines below.
    for d in state.discrete_elems:
        elem_nodes.update((d.n1, d.n2))
    # A 1D BELT is a /SPRING with a real force-strain curve on it, so its nodes
    # carry stiffness exactly as a discrete spring's do - a /BCS 111 111 there
    # would weld the belt to ground and the occupant would never move. (2D belt
    # elements are folded into state.shell_elems by _assign_seatbelt_props and
    # are already covered above.)
    #
    for e in state.seatbelt_elems:
        elem_nodes.update((e.n1, e.n2))
    # A slipring / retractor ANCHORAGE node is not a zero row either, and that
    # is the whole point of the device-anchor split: the split takes the
    # anchorage OFF the belt, so it would otherwise arrive here as a "free"
    # node - and then kine_seatbelt_force.F:91,117 adds the mouth node's whole
    # force AND STIFFNESS onto it every cycle
    # (STIFN(ANCHOR_NODE) = STIFN(ANCHOR_NODE) + STIFN(NODE2)). A /BCS 111 111
    # there would weld the belt end to ground.
    for s in state.seatbelt_sliprings:
        if s.sbrnid > 0:
            elem_nodes.add(s.sbrnid)
    for r in state.seatbelt_retractors:
        if r.sbrnid > 0:
            elem_nodes.add(r.sbrnid)
    for w in state.constrained_spotwelds:
        elem_nodes.update((w.n1, w.n2))
    # A beam's THIRD node is a geometric reference only — the starter tags it
    # CHECK_USED, not CHECK_BEAM (hm_read_beam.F:179-181), and the engine takes
    # the local frame from the stored co-rotational triad, not from that node's
    # current position (pevec3.F reads E2 from RLOC). So a SYNTHESIZED
    # orientation node, which by construction no other element touches, carries
    # no stiffness at all: leaving it out of the constraint set would put six
    # zero rows per node into the implicit tangent. Fixing it is inert.
    elem_nodes -= state.beam_orient_nodes
    # *CONSTRAINED_JOINT nodes carry the /PROP/TYPE45 joint spring; fixing them
    # here would weld the joint solid. Registered by the _resolve_joints prepass
    # so this does not depend on the joint section having run yet.
    elem_nodes.update(state.joint_spring_nodes)
    elem_nodes.update(state.connector_ground_nodes)
    # /RBE3 nodes are kinematically coupled, so they are not zero rows — and a
    # /BCS 111 111 on an /RBE3 DEPENDENT node fights the constraint outright
    # (starter WARNING 3115: a dependent node that also has boundary conditions
    # silently switches the whole element to the penalty formulation). Filled by
    # _make_rbe3, which the section registry runs before this guard.
    elem_nodes.update(state.rbe3_nodes)
    keep_free: Set[int] = set()
    for cn in state.coord_nodes.values():
        if cn.flag == 1:
            keep_free.update((cn.n1, cn.n2, cn.n3))
    # An *ELEMENT_SEATBELT_ACCELEROMETER triad is a MOVING SKEW - k2rad writes
    # /SKEW/MOV(N1,N2,N3) and puts the /ACCEL on N1 with that Iskew - so it is
    # the coord_nodes flag=1 case above, spelled with a different keyword.
    # Pinning N2/N3 freezes the frame the /ACCEL projects onto, and pinning N1
    # makes the channel read zero: the constraint is anything but inert.
    for a in state.seatbelt_accels:
        keep_free.update(n for n in (a.nid1, a.nid2, a.nid3) if n > 0)
    # A slipring ORIENTATION node is a live geometric reference: the engine
    # rebuilds the ring's frame from its CURRENT position every cycle
    # (kine_seatbelt_vel.F:91-108 reads X(:,NODE3) and stores ACOS(SCAL) into
    # ORIENTATION_ANGLE, which material_flow.F:203 folds into the friction).
    # NOT the beam-third-node case below, where the frame is baked at the
    # starter and the node can be pinned without effect.
    for s in state.seatbelt_sliprings:
        if s.onid > 0:
            keep_free.add(s.onid)
    # A sensor watches a node's POSITION (/SENSOR/DIST) or its ACCELERATION
    # (/SENSOR/ACCE). Pinning either freezes the quantity the sensor tests, so
    # the retractor never locks and the pretensioner never fires - a silent
    # loss of the whole restraint trigger, not an inert constraint.
    for sen in state.seatbelt_sensors.values():
        keep_free.update(n for n in (sen.nid, sen.nid1, sen.nid2) if n > 0)
    # Moving rigid-wall carrier nodes must stay free to translate the wall —
    # both the *RIGIDWALL_PLANAR_MOVING node (free-flying under contact) and
    # the *RIGIDWALL_GEOMETRIC_*_MOTION carrier nodes, which /IMPVEL|/IMPDISP
    # drives: a /BCS 111 111 on the same node would fight the imposed motion.
    keep_free.update(rw.node_id for rw in state.rigid_walls if rw.node_id > 0)
    keep_free.update(f.node_id for rw in state.rigid_walls_geometric
                     for f in rw.faces if f.node_id > 0)
    # *AIRBAG_* deliberately adds NOTHING here, batch 2 included. A monitored
    # volume owns no node: its surface, its vent surfaces, its internal
    # surface and its inflator-nozzle surface are all built from shells the
    # mesh already had, and the finite-volume mesh of a /MONVOL/FVMBAG2 is
    # generated inside the STARTER (init_monvol.F appends its extra vertices
    # to ITAB itself), so no FV node exists in the deck to be found free.
    #
    # The one case that reaches this guard is an *AIRBAG_HYBRID_JETTING whose
    # node_ID1/2/3 are orphan geometry markers rather than mesh nodes. Those
    # stay IN the constraint set on purpose: a node attached to no element and
    # no rigid body is moved by nothing, so pinning it changes no trajectory —
    # it only removes six zero rows from the implicit tangent, which is the
    # whole point of the guard. A jet node that IS on the inflator housing is
    # in elem_nodes already and never gets here.
    # A node the *NODE TC/RC pass has ALREADY pinned in all six DOFs needs
    # nothing from this guard, and a second /BCS on it is starter WARNING 312
    # (INCOMPATIBLE KINEMATIC CONDITIONS — measured, 1 warning / 8 conditions
    # on a two-/BCS coupon). That exact `111 111` case leaves the free set
    # here. A node pinned only PARTIALLY - by its TC/RC (or *CONSTRAINED_GLOBAL)
    # /BCS or by a global *BOUNDARY_SPC / zero-scale prescribed motion - still
    # arrives, and since round 8 (A3 P2 / P3, --bcs-union) the guard writes
    # only the DOFs those cards leave free, so no DOF is fixed twice and every
    # free node is still fixed in all six (MY_OR). The subtraction is done
    # HERE rather than in the TC/RC pass because only this side knows the
    # finished free set — the element walk above depends on registries
    # (state.rbe3_nodes, state.connector_ground_nodes) that later sections
    # fill.
    fully_pinned = {n for n, (tra, rot) in state.node_tc_rc_emitted.items()
                    if tra == "111" and rot == "111"}
    free = sorted(n for n in state.nodes
                  if n > 0 and n not in elem_nodes and n not in rigid_nodes
                  and n not in keep_free and n not in fully_pinned)
    if not free:
        return []
    state.warn(
        f"{len(free)} free node(s) attached to no element or rigid body were "
        "constrained with /BCS to keep the implicit tangent non-singular (e.g. "
        "*DEFINE_COORDINATE_NODES reference nodes baked into /SKEW/FIX, or origin "
        "markers, or the element-free nodes k2rad synthesizes to carry a "
        "/SECT reporting frame). They carry no mass and no load, so the "
        "constraint holds them where they were placed and changes nothing "
        "that moves."
    )
    if not state.options.bcs_union:
        bc_id = state.next_id()
        grnod_id = state.next_grnod_id()
        lines = [
            "#-  FREE-NODE CONSTRAINTS (implicit singularity guard):", HDR,
            f"/BCS/{bc_id}",
            "fix_free_reference_nodes",
            "#  Tra rot   skew_ID  grnod_ID",
            f"   111 111         0{_i(grnod_id)}",
            HDR,
        ]
        lines += _emit_grnod_node(grnod_id, "free_reference_nodes", free)
        return lines
    # round 8, A3 P2 / P3: per free node the guard writes NOT(global SPC OR
    # TC/RC) - the two sources are disjoint by screen (c) of the TC/RC pass.
    # A *BOUNDARY_SPC with a CID is NOT subtracted (its digits are axes of its
    # skew): the guard keeps 111 111 at skew 0 there, which the starter stops
    # with ERROR 148 - named below (reach 0).
    spc6 = {n: t + r for n, (t, r) in _global_spc_dofs(state).items()}
    tcrc6 = {n: t + r for n, (t, r) in state.node_tc_rc_emitted.items()}
    skewed_spc: Dict[int, int] = {}
    for bc in state.bcs_spcs:
        if spc_cid_skew(state, bc.cid):
            for n in state.node_sets.get(bc.nsid, ("", []))[1]:
                skewed_spc[n] = bc.cid
    rem_groups: Dict[str, List[int]] = defaultdict(list)
    spc_hit: Dict[int, int] = {}
    tcrc_hit: Dict[int, int] = {}
    spc_gone: List[int] = []
    tcrc_gone: List[int] = []
    for n in free:
        s = spc6.get(n, "000000")
        t = tcrc6.get(n, "000000")
        both = "".join("1" if "1" in (a, b) else "0" for a, b in zip(s, t))
        if "1" in s:
            spc_hit[n] = sum(1 for a in s if a == "1")
        if "1" in t:
            tcrc_hit[n] = sum(1 for a, b in zip(t, s) if a == "1" and b == "0")
        rem = "".join("0" if c == "1" else "1" for c in both)
        if rem == "000000":
            (spc_gone if "1" in s else tcrc_gone).append(n)
            continue
        rem_groups[rem].append(n)
    lines = ["#-  FREE-NODE CONSTRAINTS (implicit singularity guard):", HDR]
    # the 111 111 group FIRST and under today's titles (byte identity without a
    # hit), then each remainder code; ids drawn only for a written card
    for rem in sorted(rem_groups, key=lambda c: (c != "111111", c)):
        bc_id = state.next_id()
        grnod_id = state.next_grnod_id()
        title = ("fix_free_reference_nodes" if rem == "111111" else
                 f"fix_free_reference_nodes_{rem[:3]}_{rem[3:]}")
        lines += [
            f"/BCS/{bc_id}",
            title,
            "#  Tra rot   skew_ID  grnod_ID",
            f"   {rem[:3]} {rem[3:]}         0{_i(grnod_id)}",
            HDR,
        ]
        lines += _emit_grnod_node(
            grnod_id, "free_reference_nodes" if rem == "111111" else title,
            rem_groups[rem])
    if spc_hit:
        nn = sorted(spc_hit)
        state.warn(
            f"Free-node guard x *BOUNDARY_SPC: {sum(spc_hit.values())} DOF(s) "
            f"on {len(nn)} free node(s) (node {_named(nn)}) are already fixed "
            "by the deck's global *BOUNDARY_SPC (or a zero-scale prescribed "
            f"motion); the guard does not fix them again: {len(spc_gone)} "
            "node(s) need no guard /BCS, the rest keep the remaining DOFs in a "
            "fix_free_reference_nodes_<Tra>_<Rot> group. Every free node stays "
            "fixed in all six DOFs (hm_read_bcs.F:198 MY_OR); MEASURED on "
            "ex_08_beam_elform_1 (nt 4): 2 = 2 cycles, identical rows, MUMPS "
            "83 / 315 on both, WARNING 312 30 -> none. --no-bcs-union writes "
            "the guard's 111 111 card as before (round 8).")
    if tcrc_hit:
        nn = sorted(tcrc_hit)
        state.warn(
            f"Free-node guard x *NODE TC/RC: {sum(tcrc_hit.values())} DOF(s) "
            f"on {len(nn)} free node(s) (node {_named(nn)}) are already fixed "
            "by their TC/RC (or *CONSTRAINED_GLOBAL) /BCS; the guard writes "
            "only the DOFs left free, in a fix_free_reference_nodes_<Tra>_<Rot> "
            f"group ({len(tcrc_gone)} need none). Every free node stays fixed "
            "in all six DOFs (hm_read_bcs.F:198 MY_OR); on 11.2.sqt_iga starter "
            "WARNING 312 goes 449 -> none. --no-bcs-union writes the guard's "
            "111 111 card as before (round 8).")
    skw = sorted(n for n in free if n in skewed_spc)
    if skw:
        state.warn(
            f"Free-node guard: free node(s) {_named(skw)} carry a *BOUNDARY_SPC "
            f"in /SKEW {', '.join(str(s) for s in sorted({skewed_spc[n] for n in skw}))}; "
            "the guard's global card on them makes the starter stop with ERROR "
            "148 (one skew per node, hm_read_bcs.F:199-205) - give the node an "
            "element or state its SPC globally.")
    if len(lines) == 2:
        return []
    return lines
