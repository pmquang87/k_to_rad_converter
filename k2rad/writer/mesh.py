"""Starter mesh: nodes, skews, parts+elements, TET10 handling, properties, extra groups."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from ..state import (
    ConversionState,
    SET_ADD_ADVANCED_TYPES,
    SET_ADD_FAMILIES,
    NodeData,
    SegmentSet,
    ShellElem,
    SolidElem,
    BeamElem,
    SectionShell,
    SectionSolid,
    SectionBeam,
    SectionTshell,
)
from ..topology import (
    TET10_MIDEDGE as _TET10_MIDEDGE,
    TET10_DYNA_TO_RADIOSS as _TET10_DYNA_TO_RADIOSS,
    classify_tet10_apex_order as _classify_tet10_apex_order,
)
from .beams import _constants_from_thicknesses, _emit_prop_int_beam
from .common import (
    HDR,
    _discrete_beam_mids,
    _discrete_beam_pids,
    _discrete_part_ids,
    _elform_to_ishell,
    _ELFORM_ALWAYS_QEPH,
    ISHELL_QEPH,
    _elform_to_isolid,
    _emit_grnod_node,
    _muscle_beam_pids,
    _muscle_part_ids,
    _f,
    _fmt_eid_list,
    _i,
    _ordered_unique_nodes,
    _seatbelt_mat_law,
    _seatbelt_part_ids,
    _spotweld_beam_pids,
    _truss_pids,
    _vcross,
    _vnorm,
    _vsub,
)
# One-way: materials imports .common and .blast_ale only, never .mesh.
from .materials import _null_part_eos_bindings
# One-way: truss imports .common and ..state only; its ONE reference back into
# this module (_target_mat_law, for the /TRUSS material gate) is a local import
# inside the function, the same shape as _plas_kin_law2_eligible's.
from .truss import (
    _emit_prop_truss,
    _emit_truss_block,
    _truss_section_is_emittable,
    _warn_truss_material,
    _warn_truss_releases,
    _warn_truss_section_cells,
)

__all__ = [
    "_make_nodes",
    "_emit_skew_fix",
    "_emit_skew_mov",
    "_ortho_skew_axes",
    "_make_skews",
    "_skew_axes_from_nodes",
    "_emit_skew_from_nodes",
    "_mov_third_pos",
    "_synthesize_vector_skews",
    "_emit_coord_vector_skew",
    "_emit_define_vector_skew",
    "_emit_sd_orientation_skew",
    "_normalize_tet10_ordering",
    "_snap_tet10_midsides",
    "_tet_corner_metrics",
    "_tet10_badly_shaped",
    "_TET4_WARN_AR",
    "_TET4_WARN_NVOL",
    "_TET4_DROP_AR",
    "_TET4_DROP_NVOL",
    "_TET4_DROP_LMIN_FRAC",
    "_tet4_sliver_class",
    "_screen_sliver_tets",
    "_referenced_node_ids",
    "_downgrade_tet10_to_tet4",
    "_screen_provisional_elements",
    "_synthesize_beam_orientation_nodes",
    "_unique_node_slots",
    "_shell_element_thickness",
    "_shell_optional_fields",
    "_make_parts_and_elements",
    "_make_properties",
    "_emit_prop_beam",
    "_TYPE3_BEAM_LAWS",
    "_TYPE18_ONLY_BEAM_LAWS",
    "_target_mat_law",
    "_warn_beam_type3_material",
    "_resolve_contact_interior",
    "_assign_ortho_props",
    "_law128_ref_axis",
    "_emit_prop_type9",
    "_emit_prop_type6",
    "_emit_ortho_props",
    "_make_extra_groups",
    "_TET10_MIDEDGE",
]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: nodes
# ─────────────────────────────────────────────────────────────────────────────

def _make_nodes(state: ConversionState, progress=None) -> List[str]:
    if not state.nodes:
        return []
    lines = ["#-  NODES:", HDR, "/NODE",
             "#  Node ID               X               Y               Z"]
    items = sorted(state.nodes.items())
    total = len(items)
    step = max(1, total // 20)
    for idx, (nid, nd) in enumerate(items):
        lines.append(f"{_i(nid)}{_f(nd.x)}{_f(nd.y)}{_f(nd.z)}")
        if progress is not None and idx % step == 0:
            progress(idx / total)
    lines.append(HDR)
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Starter: skews
# ─────────────────────────────────────────────────────────────────────────────

def _emit_skew_fix(skew_id: int, title: str, origin, yaxis, zaxis) -> List[str]:
    """Emit /SKEW/FIX. The two vector cards are the LOCAL Y and Z axes — NOT X
    and Y: per the Reference Guide (and cfg attrs globalyaxis/globalzaxis),
    X1Y1Z1 = Y', X2Y2Z2 = Z', and the starter builds X' = Y' × Z' then
    re-orthogonalizes Y'' = Z' × X'. Passing X/Y here would yield a cyclically
    permuted frame (Radioss-X = intended Z) and rotate every skewed BCS/CLOAD.
    """
    return [
        f"/SKEW/FIX/{skew_id}",
        title,
        "#                 Ox                  Oy                  Oz",
        f"{_f(origin[0])}{_f(origin[1])}{_f(origin[2])}",
        "#                 X1                  Y1                  Z1   (local Y axis)",
        f"{_f(yaxis[0])}{_f(yaxis[1])}{_f(yaxis[2])}",
        "#                 X2                  Y2                  Z2   (local Z axis)",
        f"{_f(zaxis[0])}{_f(zaxis[1])}{_f(zaxis[2])}",
        HDR,
    ]


def _emit_skew_mov(skew_id: int, title: str, n1: int, n2: int, n3: int,
                   dir_: str = "X") -> List[str]:
    """Emit /SKEW/MOV (cfg radioss2019): N1=origin, N1→N2 = the Dir axis, N3
    fixes the plane. The frame is recomputed by the starter every step."""
    return [
        f"/SKEW/MOV/{skew_id}",
        title,
        "#  node_ID1  node_ID2  node_ID3       Dir",
        f"{_i(n1)}{_i(n2)}{_i(n3)}{dir_.rjust(10)}",
        HDR,
    ]


def _make_skews(state: ConversionState) -> List[str]:
    if not (state.coord_sys or state.coord_nodes or state.coord_vectors
            or state.define_vectors or state.sd_orientations):
        return []
    lines = ["#-  SKEWS / COORDINATE SYSTEMS:", HDR]
    for cid, cs in sorted(state.coord_sys.items()):
        # *DEFINE_COORDINATE_SYSTEM gives POINTS: origin O, a point L on the
        # local x-axis and a point P in the local x-y plane — convert to axis
        # vectors before emitting (raw point coordinates are only valid vectors
        # when the origin happens to be (0,0,0)).
        origin = (cs.xo, cs.yo, cs.zo)
        xv = _vnorm(_vsub((cs.xl, cs.yl, cs.zl), origin))
        zv = None
        if xv is not None:
            zv = _vnorm(_vcross(xv, _vsub((cs.xp, cs.yp, cs.zp), origin)))
        if zv is None:
            state.warn(
                f"*DEFINE_COORDINATE_SYSTEM cid={cid}: degenerate axis points - "
                "global axes used for /SKEW/FIX."
            )
            yv, zv = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        else:
            yv = _vcross(zv, xv)
        lines += _emit_skew_fix(cid, f"SKEW_{cid}", origin, yv, zv)
    for cid, cn in sorted(state.coord_nodes.items()):
        lines += _emit_skew_from_nodes(state, cn)
    for cid, cv in sorted(state.coord_vectors.items()):
        lines += _emit_coord_vector_skew(state, cv)
    for vid, dv in sorted(state.define_vectors.items()):
        if dv.skew_id:
            lines += _emit_define_vector_skew(state, dv)
    for vid, so in sorted(state.sd_orientations.items()):
        if so.skew_id:
            lines += _emit_sd_orientation_skew(state, so)
    return lines


def _skew_axes_from_nodes(state: ConversionState, cn):
    """Compute the local (X, Y, Z) orthonormal axes of a *DEFINE_COORDINATE_NODES
    system at t=0 from node coordinates, honouring LS-DYNA's `dir` convention.

    n1->n2 is the `dir` axis; n3 (with n1) fixes the next cyclic axis (toward n3).
    Returns ((Ox,Oy,Oz), Xaxis, Yaxis) or None if a node/geometry is degenerate.
    """
    n1 = state.nodes.get(cn.n1)
    n2 = state.nodes.get(cn.n2)
    n3 = state.nodes.get(cn.n3)
    if not (n1 and n2 and n3):
        return None
    origin = (n1.x, n1.y, n1.z)
    a = _vsub((n2.x, n2.y, n2.z), origin)       # n1->n2 = the `dir` axis
    b = _vsub((n3.x, n3.y, n3.z), origin)       # n1->n3 lies in the dir/next plane
    e_dir = _vnorm(a)
    nrm = _vnorm(_vcross(a, b))                  # plane normal (a x b)
    if e_dir is None or nrm is None:
        return None
    inplane = _vnorm(_vcross(nrm, e_dir))        # perp to dir, in plane, toward n3
    if inplane is None:
        return None
    # Cyclic assignment X->Y->Z->X: dir axis = e_dir, next (in-plane) = inplane,
    # the one after = nrm. This reproduces /SKEW/MOV's documented axes exactly.
    if cn.dir == "Y":
        X, Y, _Z = nrm, e_dir, inplane
    elif cn.dir == "Z":
        X, Y, _Z = inplane, nrm, e_dir
    else:  # "X" (default)
        X, Y, _Z = e_dir, inplane, nrm
    return origin, X, Y


def _emit_skew_from_nodes(state: ConversionState, cn) -> List[str]:
    """Emit a /SKEW for a *DEFINE_COORDINATE_NODES system.

    flag=1 (co-rotating) -> /SKEW/MOV with the SAME (N1, N2, N3, Dir) card, which
    OpenRadioss recomputes every step. flag=0 (fixed) -> /SKEW/FIX with the axes
    evaluated once from the t=0 node coordinates. If the nodes are missing/
    degenerate, fall back to /SKEW/MOV so the skew_ID still resolves.
    """
    axes = _skew_axes_from_nodes(state, cn)
    if cn.flag == 1 or axes is None:
        if cn.flag != 1 and axes is None:
            state.warn(
                f"*DEFINE_COORDINATE_NODES cid={cn.cid}: nodes "
                f"{cn.n1}/{cn.n2}/{cn.n3} missing or collinear at t=0 — emitted a "
                "moving /SKEW/MOV instead of a fixed /SKEW/FIX."
            )
        else:
            state.warn(
                f"*DEFINE_COORDINATE_NODES cid={cn.cid}: flag=1 -> co-rotating "
                f"/SKEW/MOV (N1={cn.n1}, N2={cn.n2}, N3={cn.n3}, Dir={cn.dir})."
            )
        return [
            f"/SKEW/MOV/{cn.cid}",
            f"SKEW_NODES_{cn.cid}",
            "#  node_ID1  node_ID2  node_ID3       Dir",
            f"{_i(cn.n1)}{_i(cn.n2)}{_i(cn.n3)}{cn.dir.rjust(10)}",
            HDR,
        ]
    origin, X, Y = axes
    state.warn(
        f"*DEFINE_COORDINATE_NODES cid={cn.cid}: flag={cn.flag} -> fixed "
        f"/SKEW/FIX with axes computed at t=0 (Dir={cn.dir}); set flag=1 in the "
        ".k file for a co-rotating /SKEW/MOV."
    )
    return _emit_skew_fix(cn.cid, f"SKEW_NODES_{cn.cid}", origin, Y, _vcross(X, Y))


def _mov_third_pos(p1, axis):
    """A point offset from *p1* by a unit global axis NOT parallel to *axis* —
    the synthesized third node that fixes a moving skew's plane (its exact
    transverse orientation is irrelevant for a 1-D vector/orientation frame; all
    that matters is that it is not collinear with N1→N2)."""
    helpers = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    e = min(helpers, key=lambda h: abs(h[0] * axis[0] + h[1] * axis[1]
                                       + h[2] * axis[2]))
    return (p1[0] + e[0], p1[1] + e[1], p1[2] + e[2])


def _synthesize_vector_skews(state: ConversionState) -> None:
    """build_starter prepass: assign a /SKEW id to every *DEFINE_VECTOR[_NODES]
    and *DEFINE_SD_ORIENTATION, and synthesize the third node each moving
    /SKEW/MOV needs. Runs before the /NODE section so synthesized nodes are
    emitted, and before /FRAME allocation so the ids are reserved.

    *DEFINE_COORDINATE_VECTOR keeps its CID as the /SKEW id (coordinate-system id
    space, already unique among *DEFINE_COORDINATE_*). *DEFINE_VECTOR /
    *DEFINE_SD_ORIENTATION VIDs live in a separate LS-DYNA id space that can
    collide with a CID, so each prefers its own VID but falls back to a fresh
    reserved id (state.next_id) on a collision — all recorded in
    state.vector_skew_ids / state.sdorient_skew_ids so a consumer (and the /FRAME
    id guard) can find them.
    """
    if not (state.define_vectors or state.sd_orientations):
        return
    reserved = state.all_skew_ids()          # coord_sys/_nodes/_vectors ids
    next_node = (max(state.nodes) + 1) if state.nodes else 90000001

    def alloc_skew(pref: int) -> int:
        if 0 < pref <= 90000 and pref not in reserved:
            sid = pref
        else:
            sid = state.next_id()
            while sid in reserved:
                sid = state.next_id()
        reserved.add(sid)
        return sid

    for vid in sorted(state.define_vectors):
        dv = state.define_vectors[vid]
        if dv.is_nodes:
            n1 = state.nodes.get(dv.nodet)
            n2 = state.nodes.get(dv.nodeh)
            if n1 is None or n2 is None:
                state.warn(
                    f"*DEFINE_VECTOR_NODES vid={vid}: tail/head node "
                    f"{dv.nodet}/{dv.nodeh} missing — no /SKEW emitted.")
                continue
            axis = _vnorm(_vsub((n2.x, n2.y, n2.z), (n1.x, n1.y, n1.z)))
            if axis is None:
                state.warn(
                    f"*DEFINE_VECTOR_NODES vid={vid}: tail and head node "
                    "coincide — no /SKEW emitted.")
                continue
            dv.skew_id = alloc_skew(vid)
            pos3 = _mov_third_pos((n1.x, n1.y, n1.z), axis)
            dv.n3 = next_node
            next_node += 1
            state.nodes[dv.n3] = NodeData(*pos3)
            state.vector_skew_ids[vid] = dv.skew_id
        else:
            if _vnorm(_vsub((dv.xh, dv.yh, dv.zh),
                            (dv.xt, dv.yt, dv.zt))) is None:
                state.warn(
                    f"*DEFINE_VECTOR vid={vid}: tail and head coincide — no "
                    "/SKEW emitted.")
                continue
            dv.skew_id = alloc_skew(vid)
            state.vector_skew_ids[vid] = dv.skew_id

    for vid in sorted(state.sd_orientations):
        so = state.sd_orientations[vid]
        if so.iop == 0:
            if _vnorm((so.xt, so.yt, so.zt)) is None:
                state.warn(
                    f"*DEFINE_SD_ORIENTATION vid={vid}: IOP=0 orientation vector "
                    "is zero — no /SKEW emitted.")
                continue
            so.skew_id = alloc_skew(vid)
            state.sdorient_skew_ids[vid] = so.skew_id
        elif so.iop == 2:
            n1 = state.nodes.get(so.nid1)
            n2 = state.nodes.get(so.nid2)
            if n1 is None or n2 is None:
                state.warn(
                    f"*DEFINE_SD_ORIENTATION vid={vid}: IOP=2 node "
                    f"{so.nid1}/{so.nid2} missing — no /SKEW; oriented springs "
                    "on this VID stay unconverted.")
                continue
            axis = _vnorm(_vsub((n2.x, n2.y, n2.z), (n1.x, n1.y, n1.z)))
            if axis is None:
                state.warn(
                    f"*DEFINE_SD_ORIENTATION vid={vid}: IOP=2 nodes coincide — "
                    "no /SKEW emitted.")
                continue
            so.skew_id = alloc_skew(vid)
            pos3 = _mov_third_pos((n1.x, n1.y, n1.z), axis)
            so.n3 = next_node
            next_node += 1
            state.nodes[so.n3] = NodeData(*pos3)
            state.sdorient_skew_ids[vid] = so.skew_id
        else:                                   # IOP = 1 or 3 (or unset)
            state.warn(
                f"*DEFINE_SD_ORIENTATION vid={vid}: IOP={so.iop} (spring-node "
                "axis projected perpendicular to a vector / node pair) has no "
                "OpenRadioss skew equivalent — unhandled by dyna2rad too, so an "
                "*ELEMENT_DISCRETE referencing this VID is NOT converted.")

    # Surface dead output: a *DEFINE_VECTOR nothing consumes, and a
    # *DEFINE_SD_ORIENTATION that no *ELEMENT_DISCRETE references. An unused
    # /SKEW is harmless, but the moving (_NODES / IOP=2) forms also injected a
    # free helper node above — flag both so that extra node is not a silent
    # surprise (it would otherwise appear unexplained in the free-node /BCS
    # guard for implicit decks).
    #
    # *BOUNDARY_PRESCRIBED_MOTION with |DOF| 4 or 8 IS a consumer: the VID skew
    # becomes the motion's skew_ID (writer/loads.py _pm_skew_for). Before that
    # was wired the vector skew was always dead output, which is why this used to
    # read "no k2rad consumer exists".
    referenced_sd = {e.vid for e in state.discrete_elems if e.vid}
    referenced_vec = {pm.vid
                      for pm in (list(state.prescribed_motions)
                                 + list(state.prescribed_motion_sets))
                      if pm.vid and abs(pm.dof) in (4, 8)}
    unref_vec = sorted(v for v in state.vector_skew_ids
                       if v not in referenced_vec)
    unref_sd = sorted(v for v in state.sdorient_skew_ids
                      if v not in referenced_sd)
    if unref_vec or unref_sd:
        injected = ([v for v in unref_vec if state.define_vectors[v].is_nodes]
                    + [v for v in unref_sd if state.sd_orientations[v].iop == 2])
        msg = (f"Unreferenced /SKEW output — *DEFINE_VECTOR {unref_vec or '[]'} "
               f"and *DEFINE_SD_ORIENTATION {unref_sd or '[]'} each emit a /SKEW "
               "no converted keyword uses")
        if injected:
            msg += (f"; the moving forms {injected} also injected a free helper "
                    "node each (needed by /SKEW/MOV — harmless but unused)")
        state.warn(msg + ".")


def _emit_coord_vector_skew(state: ConversionState, cv) -> List[str]:
    """*DEFINE_COORDINATE_VECTOR → /SKEW/FIX at the origin. local X' = (XX,YX,ZX);
    local Z' = X × V; local Y' = Z × X. The card carries Y'/Z' (X' is rebuilt by
    the starter). The vectors are normalized here (k2rad's skew convention;
    Radioss re-orthonormalizes internally either way)."""
    ex = _vnorm((cv.xx, cv.yx, cv.zx))
    if ex is None:
        state.warn(f"*DEFINE_COORDINATE_VECTOR cid={cv.cid}: local-X vector is "
                   "zero — /SKEW/FIX defaults to the global axes.")
        return _emit_skew_fix(cv.cid, cv.title or f"SKEW_VEC_{cv.cid}",
                              (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    ez = _vnorm(_vcross((cv.xx, cv.yx, cv.zx), (cv.xv, cv.yv, cv.zv)))
    if ez is None:
        state.warn(f"*DEFINE_COORDINATE_VECTOR cid={cv.cid}: the in-plane vector "
                   "V is parallel to X (or zero) — a transverse axis was chosen "
                   "arbitrarily; the local X axis is preserved.")
        axes = _ortho_skew_axes((cv.xx, cv.yx, cv.zx))
        return _emit_skew_fix(cv.cid, cv.title or f"SKEW_VEC_{cv.cid}",
                              (0.0, 0.0, 0.0), axes[0], axes[1])
    if cv.nid:
        state.warn(f"*DEFINE_COORDINATE_VECTOR cid={cv.cid}: co-rotation node "
                   f"NID={cv.nid} dropped — emitted a fixed /SKEW/FIX (dyna2rad "
                   "also treats this card as fixed).")
    ey = _vcross(ez, ex)
    return _emit_skew_fix(cv.cid, cv.title or f"SKEW_VEC_{cv.cid}",
                          (0.0, 0.0, 0.0), ey, ez)


def _emit_define_vector_skew(state: ConversionState, dv) -> List[str]:
    """*DEFINE_VECTOR → /SKEW/FIX, *DEFINE_VECTOR_NODES → /SKEW/MOV. Local X'
    follows the tail→head direction (the correct LS-DYNA convention, and the same
    sense both the _NODES and value forms use here — dyna2rad's value form builds
    tail−head, the reverse, which is a documented dyna2rad quirk we deliberately
    do not reproduce)."""
    title = dv.title or f"SKEW_VEC_{dv.vid}"
    if dv.is_nodes:
        return _emit_skew_mov(dv.skew_id, title, dv.nodet, dv.nodeh, dv.n3, "X")
    origin = (dv.xt, dv.yt, dv.zt)
    if dv.cid:
        state.warn(
            f"*DEFINE_VECTOR vid={dv.vid}: CID={dv.cid} (components expressed in "
            "a local system) is treated as global — the tail/head are used "
            "verbatim; re-express them in the global frame if that is wrong.")
    axes = _ortho_skew_axes(_vsub((dv.xh, dv.yh, dv.zh), origin))
    if axes is None:                            # guarded in the prepass, belt-and-braces
        return _emit_skew_fix(dv.skew_id, title, origin, (0.0, 1.0, 0.0),
                              (0.0, 0.0, 1.0))
    return _emit_skew_fix(dv.skew_id, title, origin, axes[0], axes[1])


def _emit_sd_orientation_skew(state: ConversionState, so) -> List[str]:
    """*DEFINE_SD_ORIENTATION → /SKEW/FIX (IOP=0) or /SKEW/MOV (IOP=2). For
    IOP=0 the skew's local X' is aligned with the orientation vector (XT,YT,ZT) —
    an improvement on dyna2rad, whose fixed helper axis tilts X' by the
    orientation's component along global X. For IOP=2 the local X' follows
    node1→node2 (correct LS-DYNA sense)."""
    title = so.title or f"SKEW_SD_{so.vid}"
    if so.iop == 2:
        return _emit_skew_mov(so.skew_id, title, so.nid1, so.nid2, so.n3, "X")
    axes = _ortho_skew_axes((so.xt, so.yt, so.zt))
    if axes is None:                            # guarded in the prepass
        return _emit_skew_fix(so.skew_id, title, (0.0, 0.0, 0.0),
                              (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return _emit_skew_fix(so.skew_id, title, (0.0, 0.0, 0.0), axes[0], axes[1])


def _snap_tet10_midsides(state: ConversionState) -> int:
    """Move every 10-node tet's mid-edge nodes onto the exact midpoints of their
    corner edges (straight-edged "sub-parametric" /TETRA10).

    A mid-edge node displaced from the midpoint can fold the quadratic Jacobian
    (det J changes sign inside the element) → OpenRadioss ERROR 489 "BADLY SHAPED
    10-NODE TETRA". Crucially this is NOT predicted by mid-edge deviation or corner
    aspect ratio alone — it's the corner+midside interaction — so the only robust,
    deterministic cure is to straighten the edges: a straight-edged tetra has a
    constant-sign Jacobian for any non-degenerate corner tet, so it cannot fold.
    Shared mid-edge nodes map to the same midpoint, so the pass is consistent;
    curved boundary elements are flattened slightly (still quadratic interior).
    Returns the number of distinct mid-edge nodes actually moved.
    """
    moved: Set[int] = set()
    for e in state.solid_elems:
        if len(e.nodes) != 10:
            continue
        raw_cs = [state.nodes.get(e.nodes[k]) for k in range(4)]
        if any(c is None for c in raw_cs):
            continue
        cs = [c for c in raw_cs if c is not None]
        for mi, a, b in _TET10_MIDEDGE:
            mnid = e.nodes[mi]
            m = state.nodes.get(mnid)
            if m is None:
                continue
            mx = 0.5 * (cs[a].x + cs[b].x)
            my = 0.5 * (cs[a].y + cs[b].y)
            mz = 0.5 * (cs[a].z + cs[b].z)
            if abs(m.x - mx) > 1e-9 or abs(m.y - my) > 1e-9 or abs(m.z - mz) > 1e-9:
                m.x, m.y, m.z = mx, my, mz
                moved.add(mnid)
    return len(moved)


def _tet10_coord(state: ConversionState, nid: int) -> Optional[Tuple[float, float, float]]:
    nd = state.nodes.get(nid)
    if nd is None:
        return None
    return (nd.x, nd.y, nd.z)


def _warn_tet10_order_inconsistent(state: ConversionState, tet10s) -> int:
    """Cross-element consistency check (reuses the snap_consistency.py logic):
    under the Radioss mid-edge map every element sharing a midside node must imply
    the SAME edge midpoint. After normalization a residual disagreement means the
    mesh is genuinely non-uniform (mixed LS-DYNA/Radioss connectivity) — the single
    apex permutation cannot fix that, and the straight-edge snap would collapse the
    shared node (ERROR 558). Warn loudly. Scale-invariant: the spread is compared
    to the element's largest corner-edge length. Returns the disagreement count.
    """
    import math
    targets: Dict[int, List[Tuple[Tuple[float, float, float], float]]] = defaultdict(list)
    for e in tet10s:
        raw_cs = [_tet10_coord(state, e.nodes[k]) for k in range(4)]
        if any(c is None for c in raw_cs):
            continue
        cs = [c for c in raw_cs if c is not None]
        scale = max(
            math.sqrt((cs[a][0] - cs[b][0]) ** 2 + (cs[a][1] - cs[b][1]) ** 2
                      + (cs[a][2] - cs[b][2]) ** 2)
            for a in range(4) for b in range(a + 1, 4)
        ) or 1.0
        for mi, a, b in _TET10_MIDEDGE:
            m = _tet10_coord(state, e.nodes[mi])
            if m is None:
                continue
            mid = ((cs[a][0] + cs[b][0]) / 2.0, (cs[a][1] + cs[b][1]) / 2.0,
                   (cs[a][2] + cs[b][2]) / 2.0)
            targets[e.nodes[mi]].append((mid, scale))
    disagree = 0
    for _nid, items in targets.items():
        if len(items) < 2:
            continue
        pts = [p for p, _ in items]
        scale = min(s for _, s in items) or 1.0
        spread = max(
            max(abs(p[k] - q[k]) for k in range(3)) for p in pts for q in pts)
        if spread > 1e-3 * scale:
            disagree += 1
    if disagree:
        state.warn(
            f"/TETRA10 midside-order verifier: {disagree} shared midside node(s) "
            "still get conflicting edge-midpoint targets under the Radioss map "
            "after normalization — the mesh is not uniformly ordered (mixed "
            "LS-DYNA/Radioss connectivity). The straight-edge snap will collapse "
            "these onto one point (risk of ERROR 558 MAIN SEGMENT CROSSED / NULL "
            "AREA); re-mesh or supply a single consistent element ordering."
        )
    return disagree


def _normalize_tet10_ordering(state: ConversionState) -> int:
    """Normalize every 10-node tet's connectivity to the **Radioss /TETRA10**
    midside convention (apex nodes 8/9/10 = mid(1,4)/mid(2,4)/mid(3,4)) BEFORE any
    writer pass reads the midside slots.

    LS-DYNA ``*ELEMENT_SOLID`` and Radioss ``/TETRA10`` agree on corners 1-4 and
    the base midsides 5/6/7 but disagree on the three apex midsides: LS-DYNA orders
    them mid(2,4)/mid(3,4)/mid(1,4), Radioss mid(1,4)/mid(2,4)/mid(3,4). Feeding a
    LS-DYNA deck's connectivity verbatim into ``/TETRA10`` — or through the Radioss
    mid-edge map in the snap / gapmin passes — puts the wrong node in each apex
    slot, which (1) collapses shared midside nodes in the snap pass onto one point
    → null-area contact segments (ERROR 558), and (2) gives every ``/TETRA10`` a
    ~−30% element volume/mass. Both die once the connectivity is Radioss-ordered.

    Detection is geometric and per element (nearest apex-edge midpoint, from the
    tet10_order_sweep.py diagnosis). The whole mesh is then normalized to one
    convention chosen by **majority** of the classified elements:

    * majority Radioss/Abaqus order → no-op (a native C3D10 deck stays untouched,
      even if a stray sliver/degenerate element fails to classify);
    * otherwise → permute every element's apex slots via ``TET10_DYNA_TO_RADIOSS``
      (LS-DYNA→Radioss). Mixed / ambiguous / coordinate-less meshes take the
      LS-DYNA default **with a loud warning** — every real ``*ELEMENT_SOLID`` deck
      is LS-DYNA-ordered and Altair's hm_reader permutes on import the same way.
      A majority-vote (not all-or-nothing) means a few unclassifiable elements
      cannot flip a clearly-ordered mesh into a wrongful permutation.

    Idempotent via ``state.tet10_normalized`` (the permutation is a 3-cycle, so a
    blind re-run would corrupt the connectivity). Returns the number of
    ``/TETRA10`` elements permuted.
    """
    if state.tet10_normalized:
        return 0
    state.tet10_normalized = True

    tet10s = [e for e in state.solid_elems if len(e.nodes) == 10]
    if not tet10s:
        return 0

    n_dyna = n_radioss = n_ambiguous = 0
    for e in tet10s:
        corners = [_tet10_coord(state, e.nodes[k]) for k in range(4)]
        apex = [_tet10_coord(state, e.nodes[k]) for k in (7, 8, 9)]
        cls = _classify_tet10_apex_order(corners, apex)
        if cls == "dyna":
            n_dyna += 1
        elif cls == "radioss":
            n_radioss += 1
        else:
            n_ambiguous += 1

    # On a --tet10-to-tet4 run the midsides are about to be discarded and only the
    # order-invariant corners survive, so the apex permutation is a geometric no-op
    # for the emitted deck — suppress the (otherwise misleading) /TETRA10-repair
    # warnings. The pass itself still runs so the upstream --auto-gapmin faceting
    # sees Radioss order.
    quiet = state.options.tet10_to_tet4

    # Decide ONE convention for the whole mesh by MAJORITY of the classified
    # (non-ambiguous) elements. A single uniform ordering is mandatory: the snap
    # pass mutates SHARED midside nodes in place, so mixing per-element orderings on
    # a shared node would itself collapse it. Majority (not all-or-nothing) means a
    # handful of sliver/ambiguous/stray-ordered elements cannot flip a clearly-
    # Radioss mesh into a wrongful permutation (or vice-versa) — a single degenerate
    # tet on an Abaqus-exported deck no longer corrupts every correct element. Ties
    # and the all-ambiguous / coordinate-less case default to the LS-DYNA permutation
    # (every real *ELEMENT_SOLID deck is LS-DYNA-ordered and Altair's hm_reader
    # permutes unconditionally on import).
    if n_radioss > n_dyna:
        # Majority Radioss/Abaqus (C3D10) order → already correct, do not permute.
        if not quiet:
            if n_dyna or n_ambiguous:
                state.warn(
                    f"/TETRA10 apex midside order: {n_radioss} element(s) read as "
                    f"Radioss/Abaqus (C3D10) order (majority), {n_dyna} as LS-DYNA, "
                    f"{n_ambiguous} ambiguous/coordinate-less. Treating the mesh as "
                    "Radioss-ordered and applying NO permutation. If some elements "
                    "are genuinely LS-DYNA-ordered, verify their /TETRA10 volume."
                )
            else:
                state.warn(
                    f"{n_radioss} /TETRA10 element(s): detected Radioss/Abaqus "
                    "(C3D10) apex midside order already; no permutation applied."
                )
        return 0

    for e in tet10s:
        e.nodes = [e.nodes[p] for p in _TET10_DYNA_TO_RADIOSS] + list(e.nodes[10:])
    n = len(tet10s)

    if not quiet:
        if n_ambiguous or n_radioss:
            state.warn(
                f"/TETRA10 apex midside order is not uniform: {n_dyna} element(s) "
                f"read as LS-DYNA order, {n_radioss} as Radioss, {n_ambiguous} "
                "ambiguous/coordinate-less. Defaulting ALL to the LS-DYNA→Radioss "
                "apex permutation (mid(2,4)/mid(3,4)/mid(1,4) → mid(1,4)/mid(2,4)/"
                "mid(3,4)) — this matches every real *ELEMENT_SOLID deck and Altair "
                "hm_reader. If this deck is genuinely Abaqus/Radioss-ordered, apex "
                "nodes 8/9/10 are now wrong; verify the /TETRA10 volume."
            )
        else:
            state.warn(
                f"{n} /TETRA10 element(s): detected LS-DYNA *ELEMENT_SOLID apex "
                "midside order; permuted apex nodes 8/9/10 to Radioss /TETRA10 "
                "order (mid(1,4)/mid(2,4)/mid(3,4)) so the snap/gapmin/emit passes "
                "and the engine agree (fixes ERROR 558 storm + silent ~−30% "
                "/TETRA10 volume)."
            )
        _warn_tet10_order_inconsistent(state, tet10s)
    return n


def _tet_corner_metrics(
    state: ConversionState, nodes: List[int]
) -> Optional[Tuple[float, float, float, float]]:
    """Shape metrics of the tetrahedron spanned by the first 4 node IDs:
    (lmin, lmax, lmean, vol) with vol = |signed volume| and lmin/lmax/lmean over
    the 6 corner edges. Returns None if any corner node is missing.
    """
    import math
    pts = []
    for n in nodes[:4]:
        nd = state.nodes.get(n)
        if nd is None:
            return None
        pts.append((nd.x, nd.y, nd.z))
    if len(pts) < 4:
        return None
    c0, c1, c2, c3 = pts

    def dist(a, b):
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)

    L = [dist(pts[a], pts[b]) for a in range(4) for b in range(a + 1, 4)]
    a = (c1[0] - c0[0], c1[1] - c0[1], c1[2] - c0[2])
    b = (c2[0] - c0[0], c2[1] - c0[1], c2[2] - c0[2])
    d = (c3[0] - c0[0], c3[1] - c0[1], c3[2] - c0[2])
    cx = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    vol = abs(cx[0] * d[0] + cx[1] * d[1] + cx[2] * d[2]) / 6.0
    return min(L), max(L), sum(L) / 6.0, vol


def _tet10_badly_shaped(state: ConversionState, nodes: List[int]) -> bool:
    """True if a 10-node tet's 4-corner shape is a sliver/degenerate tetra that
    OpenRadioss rejects as /TETRA10 (ERROR 489: BADLY SHAPED 10-NODE TETRA).

    Quadratic tets fail the Jacobian check when the underlying tetra is nearly
    flat. Criterion (on the 4 corners, independent of mid-edge ordering): shortest
    edge < 1/8 of the longest (aspect ratio > 8), OR normalized volume
    V / mean_edge^3 < 0.02, OR non-positive volume. These sliver elements have
    ~zero volume (negligible stiffness), so the writer drops them rather than keep
    a deck OpenRadioss won't read.
    """
    m = _tet_corner_metrics(state, nodes)
    if m is None:
        return False
    lmin, lmax, lmean, vol = m
    if lmin <= 0.0:
        return True
    if lmax / lmin > 8.0:
        return True
    return lmean > 0.0 and vol / (lmean ** 3) < 0.02


# 4-node tet sliver thresholds. Warn at the same shape limits that already
# condemn a /TETRA10 (aspect ratio > 8 or V/Lmean^3 < 0.02); drop only extreme
# cases — OpenRadioss *reads* sliver /TETRA4 fine, so dropping is justified only
# where the element is so degenerate that implicit contact crushes it to zero
# volume (stiffness vanishes -> AUTOSPC dimension-flip dt-cut loops, or element
# inversion polluting the energy balance).
_TET4_WARN_AR = 8.0
_TET4_WARN_NVOL = 0.02
_TET4_DROP_AR = 40.0
_TET4_DROP_NVOL = 0.001
_TET4_DROP_LMIN_FRAC = 0.05


def _tet4_sliver_class(state: ConversionState, nodes: List[int]) -> Optional[str]:
    """Classify a 4-node tet's corner shape for implicit runs.

    Returns "drop" for extreme slivers (aspect ratio > 40, V/Lmean^3 < 0.001,
    shortest edge < 5% of the mean edge, or degenerate/zero volume), "warn" for
    moderate slivers (the /TETRA10 limits: aspect ratio > 8 or V/Lmean^3 < 0.02),
    and None for sound elements or missing nodes.
    """
    m = _tet_corner_metrics(state, nodes)
    if m is None:
        return None
    lmin, lmax, lmean, vol = m
    if lmin <= 0.0 or lmean <= 0.0 or vol <= 0.0:
        return "drop"
    nvol = vol / (lmean ** 3)
    if (lmax / lmin > _TET4_DROP_AR or nvol < _TET4_DROP_NVOL
            or lmin < _TET4_DROP_LMIN_FRAC * lmean):
        return "drop"
    if lmax / lmin > _TET4_WARN_AR or nvol < _TET4_WARN_NVOL:
        return "warn"
    return None


def _screen_sliver_tets(state: ConversionState) -> None:
    """Remove sliver tets from state.solid_elems before any section is built.

    Screening must mutate the element list (not just skip at write time): the
    free-node guard (_make_free_node_constraints) decides "attached to an
    element" from state.solid_elems, so a node referenced only by a dropped
    sliver must look free there to get its /BCS — otherwise it carries zero
    stiffness rows into the implicit tangent (singular matrix).

    Three screens run here:
      * Solids with fewer than 4 distinct nodes (collapsed to a point, edge,
        or triangle) are dropped unconditionally — they have exactly zero
        volume, and written as /BRICK the starter rejects the whole deck
        (ERROR 245: ZERO OR NEGATIVE 3D SOLID VOLUME).
      * 10-node tets failing _tet10_badly_shaped are dropped unconditionally —
        OpenRadioss refuses to read them as /TETRA10 (ERROR 489).
      * 4-node tets are screened for implicit decks only (explicit reads and
        runs slivers, merely slowly): extreme slivers are dropped, moderate
        ones kept but warned with their element list, since under contact
        pressure they crush flat — stiffness vanishes and the run stalls in
        AUTOSPC dimension-flip dt cuts or inverts and pollutes the energy.
    """
    bad_t10: Dict[int, int] = defaultdict(int)            # pid -> count
    null_solid: Dict[int, List[int]] = defaultdict(list)  # pid -> eids
    drop_t4: Dict[int, List[int]] = defaultdict(list)     # pid -> eids
    warn_t4: Dict[int, List[int]] = defaultdict(list)     # pid -> eids
    kept: List[SolidElem] = []
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            if _tet10_badly_shaped(state, e.nodes):
                bad_t10[e.pid] += 1
                continue
        else:
            uniq = _ordered_unique_nodes(e.nodes)
            if len(uniq) < 4:
                null_solid[e.pid].append(e.eid)
                continue
            if state.is_implicit and len(uniq) == 4:
                shape = _tet4_sliver_class(state, uniq)
                if shape == "drop":
                    drop_t4[e.pid].append(e.eid)
                    continue
                if shape == "warn":
                    warn_t4[e.pid].append(e.eid)
        kept.append(e)
    state.solid_elems = kept

    for pid, eids in sorted(null_solid.items()):
        state.warn(
            f"PART {pid}: dropped {len(eids)} degenerate solid(s) with fewer "
            "than 4 distinct nodes (collapsed to a point, edge, or triangle — "
            "exactly zero volume). Emitted as /BRICK the OpenRadioss starter "
            "rejects the whole deck (ERROR 245: zero or negative 3D solid "
            "volume). They carry no volume, mass, or stiffness, so dropping "
            "them is physically negligible; on implicit decks any node left "
            "unattached is constrained by the free-node guard. "
            f"Dropped element(s): {_fmt_eid_list(eids)}"
        )
    for pid, n in sorted(bad_t10.items()):
        state.warn(
            f"PART {pid}: dropped {n} near-degenerate (sliver) 10-node "
            "tet(s) that OpenRadioss rejects as /TETRA10 (ERROR 489: badly "
            "shaped). Their volume is ~0 so the physical effect is negligible; "
            "clean/remesh them to retain the full element count."
        )
    for pid, eids in sorted(drop_t4.items()):
        state.warn(
            f"PART {pid}: dropped {len(eids)} extreme-sliver 4-node tet(s) "
            f"(aspect ratio > {_TET4_DROP_AR:g}, V/Lmean^3 < {_TET4_DROP_NVOL:g}, "
            f"or shortest edge < {_TET4_DROP_LMIN_FRAC:.0%} of the mean edge). "
            "Under implicit contact load such slivers crush to zero volume — "
            "their stiffness vanishes and the run stalls in AUTOSPC "
            "dimension-flip dt cuts or inverts and pollutes the energy balance. "
            "Their volume is ~0 so dropping them is physically negligible; any "
            "node left unattached is constrained by the free-node guard. "
            f"Dropped element(s): {_fmt_eid_list(eids)}"
        )
    for pid, eids in sorted(warn_t4.items()):
        state.warn(
            f"PART {pid}: {len(eids)} sliver 4-node tet(s) kept (aspect ratio "
            f"> {_TET4_WARN_AR:g} or V/Lmean^3 < {_TET4_WARN_NVOL:g}). They may "
            "hinder implicit convergence under load; consider remeshing. "
            f"Element(s): {_fmt_eid_list(eids)}"
        )


def _referenced_node_ids(state: ConversionState) -> Set[int]:
    """Every node id still referenced by a retained entity — elements, node sets,
    beams, initial velocities, added masses, coordinate-node systems, pressure
    loads, and NODE time-histories. Used to find nodes orphaned by a mesh
    transform so they can be dropped without breaking any reference."""
    ref: Set[int] = set()
    for e in state.shell_elems:
        ref.update(n for n in e.nodes if n > 0)
    for e in state.solid_elems:
        ref.update(n for n in e.nodes if n > 0)
    for e in state.tshell_elems:            # /BRICK — a real reference
        ref.update(n for n in e.nodes if n > 0)
    # An SPH particle IS its node: dropping that node as "unreferenced" would
    # delete the particle with it (starter ERROR 78 on the /SPHCEL id).
    for c in state.sph_elems:
        ref.update(n for n in c.nodes if n > 0)
    for e in state.beam_elems:
        ref.update(n for n in (e.n1, e.n2, e.n3) if n > 0)
    # A belt element's nodes are a real reference on BOTH routes: a 1D belt is
    # a /SPRING on (n1,n2), a 2D belt a /SHELL on all four. Dropping one as
    # "unreferenced" during --tet10-to-tet4 pruning is starter ERROR 78.
    for e in state.seatbelt_elems:
        ref.update(n for n in (e.n1, e.n2, e.n3, e.n4) if n > 0)
    # The restraint DEVICES reference nodes without owning an element: the
    # slipring's anchorage and orientation nodes, the retractor's anchorage
    # node, the SBSTYP=1 sensor's watched node, the SBSTYP=4 sensor's two
    # distance nodes and the accelerometer's whole triad. Every one is named on
    # an emitted card, so pruning it dangles the card. What each of them does
    # at RUNTIME differs — an anchorage receives the belt's force and stiffness
    # (kine_seatbelt_force.F:91,117), an orientation node and an accelerometer
    # triad are live frames read every cycle, a sensor node is watched — and
    # loads.py::_make_free_node_constraints keeps them all off the implicit
    # /BCS for those reasons.
    for s in state.seatbelt_sliprings:
        ref.update(n for n in (s.sbrnid, s.onid) if n > 0)
    for r in state.seatbelt_retractors:
        if r.sbrnid > 0:
            ref.add(r.sbrnid)
    for sens in state.seatbelt_sensors.values():
        ref.update(n for n in (sens.nid, sens.nid1, sens.nid2) if n > 0)
    for a in state.seatbelt_accels:
        ref.update(n for n in (a.nid1, a.nid2, a.nid3) if n > 0)
    for _title, nids in state.node_sets.values():
        ref.update(n for n in nids if n > 0)
    for iv in state.inivel_nodes:
        if iv.nid > 0:
            ref.add(iv.nid)
    ref.update(n for n in state.added_node_masses if n > 0)
    for cn in state.coord_nodes.values():
        ref.update(n for n in (cn.n1, cn.n2, cn.n3) if n > 0)
    for dv in state.define_vectors.values():
        if dv.is_nodes:
            ref.update(n for n in (dv.nodet, dv.nodeh) if n > 0)
    for so in state.sd_orientations.values():
        ref.update(n for n in (so.nid1, so.nid2) if n > 0)
    for pl in state.pressure_loads:
        ref.update(n for n in pl.nodes if n > 0)
    for ssl in state.segment_set_pressure_loads:
        segset = state.segment_sets.get(ssl.ssid)
        if segset is not None:
            for nodes in segset.segments:
                ref.update(n for n in nodes if n > 0)
    for h in state.db_histories:
        if h.db_type == "NODE":
            ref.update(n for n in h.ids if n > 0)
    return ref


def _downgrade_tet10_to_tet4(state: ConversionState) -> None:
    """Convert every 10-node quadratic tet to a 4-node linear tet (opt-in:
    --tet10-to-tet4). Keeps the 4 corner nodes (the writer then emits /TETRA4),
    drops the 6 mid-edge nodes, and removes those mid-edge nodes from /NODE when
    nothing else references them.

    A no-op when the option is off → byte-identical output. Linear tets are
    markedly stiffer and less accurate than quadratic ones (bending / near-
    incompressible locking), so this trades stress fidelity for a smaller, faster
    model — handy when only a TET10 source .k is available but a TET4 run is
    wanted. Contact surfaces (/SURF/PART/EXT) and the grounding-spring / Gapmin /
    Stfac stabilization are unaffected. Runs before _snap_tet10_midsides and
    _screen_sliver_tets so those prepasses operate on the linear mesh; Itetra10
    then turns off automatically (no 10-node solids remain).
    """
    if not state.options.tet10_to_tet4:
        return
    midedge: Set[int] = set()
    affected_pids: Set[int] = set()
    n_down = 0
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            midedge.update(n for n in e.nodes[4:10] if n > 0)
            e.nodes = e.nodes[:4]               # keep the 4 corners → /TETRA4
            affected_pids.add(e.pid)
            n_down += 1
    if n_down == 0:
        state.warn("--tet10-to-tet4: no 10-node tetrahedra found; mesh unchanged.")
        return

    # Mid-edge nodes are now in no element. Any that a NODE SET still references
    # must be pruned from that set, not kept: otherwise the node survives only to
    # carry the set's condition (e.g. a symmetry SPC from *BOUNDARY_PRESCRIBED_
    # MOTION_SET) AND, being element-less, the implicit free-node guard's /BCS —
    # two boundary conditions on one node, which OpenRadioss rejects as WARNING
    # 312 INCOMPATIBLE KINEMATIC CONDITIONS (seen as 6152 orphaned symmetry-plane
    # mid-edge nodes x 3 DOFs = 18456 on the elevator TET4 downgrade). The
    # surviving corner nodes on the same plane still carry the condition, so the
    # SPC is unchanged for the linear mesh. Genuinely-needed references (coord-node
    # systems, inivel, pressure, added mass, beams, node TH) keep the node — those
    # carry no second BCS, so the free-node guard constrains them harmlessly.
    elem_nodes: Set[int] = set()
    for e in state.shell_elems:
        elem_nodes.update(n for n in e.nodes if n > 0)
    for e in state.solid_elems:
        elem_nodes.update(n for n in e.nodes if n > 0)
    for e in state.beam_elems:
        elem_nodes.update(n for n in (e.n1, e.n2, e.n3) if n > 0)
    gone = {n for n in midedge if n not in elem_nodes}     # removed from the mesh

    n_pruned = 0
    n_sets_pruned = 0
    for nsid, (title, nids) in list(state.node_sets.items()):
        kept = [n for n in nids if n not in gone]
        if len(kept) != len(nids):
            n_pruned += len(nids) - len(kept)
            n_sets_pruned += 1
            state.node_sets[nsid] = (title, kept)

    referenced = _referenced_node_ids(state)
    dropped = [nid for nid in gone if nid not in referenced and nid in state.nodes]
    for nid in dropped:
        del state.nodes[nid]
    state.warn(
        f"--tet10-to-tet4: downgraded {n_down} /TETRA10 to /TETRA4 (kept the 4 "
        f"corner nodes, dropped {len(dropped)} now-unreferenced mid-edge node(s)) "
        f"on part(s) {sorted(affected_pids)}. Linear tets are stiffer and less "
        "accurate than quadratic tets (bending / near-incompressible locking) — "
        "expect coarser stress; remesh for production accuracy."
    )
    if n_pruned:
        state.warn(
            f"--tet10-to-tet4: removed {n_pruned} dropped mid-edge node(s) from "
            f"{n_sets_pruned} node set(s) so their SPC/BC now applies to the "
            "surviving corner nodes only (prevents orphan nodes carrying both a "
            "node-set BC and the implicit free-node /BCS — OpenRadioss WARNING 312)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Unmodelled *ELEMENT_ option suffixes: validate what the content test kept
# ─────────────────────────────────────────────────────────────────────────────

def _screen_provisional_elements(state: ConversionState) -> None:
    """Drop the phantom "elements" an unmodelled *ELEMENT_ option card produced.

    An *ELEMENT_SHELL/_BEAM block whose suffix k2rad does not model has, by
    definition, an unknown card layout, so the handler cannot step over the
    extra cards by POSITION — it keeps every line that could be connectivity
    (all fields plain positive integers, no repeated EID in the block) and marks
    the result provisional. That content test cannot be made exact:

      * ``*ELEMENT_BEAM_THICKNESS`` on a 10x10 square section writes
        ``10 10 10 10`` — four positive integers, indistinguishable from
        ``eid pid n1 n2``;
      * an ``*ELEMENT_SHELL_COMPOSITE`` ply card ``mid thick beta tmid …`` does
        the same whenever its thicknesses/angles are written as whole numbers
        and its leading MID is not an EID already seen in the block.

    Inventing an element from such a card is strictly worse than the old silent
    skip: the starter rejects the deck outright with ERROR 78 (UNDEFINED NODE
    NUMBER) and ERROR 222 (BEAM ID … IS INCONSISTENT: N1=N2), so the converter
    would be reporting a preserved element while producing a deck that will not
    start. This pass is the sufficiency half of the test — it runs after ALL
    parsing (so *NODE may follow *ELEMENT, and *INCLUDEs are merged) and keeps a
    provisional element only when the node table actually backs it:

      * every node id it names exists in ``state.nodes``;
      * a /BEAM has N1 != N2 (the ERROR 222 case), and a third node, if given,
        exists too — a bogus N3 is zeroed rather than costing the element,
        because the starter's INFO 2093 fallback (N3 := N2) is recoverable;
      * a /SHELL has at least 3 DISTINCT corners (fewer is zero area).

    The per-block warning is emitted here, not in the handler, so the "kept"
    count the user is told to reconcile against the source deck is the count
    that actually reaches the deck.
    """
    if not state.provisional_elem_blocks:
        return
    nodes = state.nodes
    # Keyed by (FAMILY, id), never by id alone. LS-DYNA's element-id namespaces
    # are per family and an SPH particle is keyed by its NODE id on top of
    # that, so one flat set makes an id that two families both use into a drop
    # in BOTH — measured, a provisional *ELEMENT_SPH block on nodes 1..8 beside
    # a provisional *ELEMENT_SHELL block with EIDs 1,2,3 lost particles 1, 2
    # and 3 (37.5 % of the cloud's mass) for no reason, and the per-block report
    # then blamed the SPH block's own node screen, which had passed.
    dropped: Set[Tuple[str, int]] = set()
    shells = {e.eid: e for e in state.shell_elems if e.provisional}
    beams = {e.eid: e for e in state.beam_elems if e.provisional}
    tshells = {e.eid: e for e in state.tshell_elems if e.provisional}
    sph = {c.nid: c for c in state.sph_elems if c.provisional}
    for eid, e in shells.items():
        if not all(n in nodes for n in e.nodes) \
                or len(_ordered_unique_nodes(e.nodes)) < 3:
            dropped.add(("shell", eid))
    for eid, e in beams.items():
        if e.n1 not in nodes or e.n2 not in nodes or e.n1 == e.n2:
            dropped.add(("beam", eid))
        elif e.n3 and e.n3 not in nodes:
            e.n3 = 0
    for eid, e in tshells.items():
        # A thick shell needs both faces real: fewer than 6 distinct corners is
        # below even the degenerate pentahedron (ERROR 245 zero volume), and an
        # undefined node id is ERROR 78. A card 2b ply line is exactly what this
        # catches when a deck's ply MIDs happen to look like node ids.
        if not all(n in nodes for n in e.nodes) \
                or len(_ordered_unique_nodes(e.nodes)) < 6:
            dropped.add(("tshell", eid))
    for nid, c in sph.items():
        # A particle IS its node, so the whole test is "does that node exist".
        # An option card whose first two cells happen to be positive integers
        # is exactly what this catches: an invented particle sits on an id the
        # deck never defines, which is starter ERROR 78.
        if nid not in nodes:
            dropped.add(("sph", nid))
    if dropped:
        state.shell_elems = [e for e in state.shell_elems
                             if not (e.provisional
                                     and ("shell", e.eid) in dropped)]
        state.beam_elems = [e for e in state.beam_elems
                            if not (e.provisional
                                    and ("beam", e.eid) in dropped)]
        state.tshell_elems = [e for e in state.tshell_elems
                              if not (e.provisional
                                      and ("tshell", e.eid) in dropped)]
        state.sph_elems = [c for c in state.sph_elems
                           if not (c.provisional and ("sph", c.nid) in dropped)]
    for rec in state.provisional_elem_blocks:
        n_dropped = sum(1 for eid in rec.eids if (rec.kind, eid) in dropped)
        n_kept = len(rec.eids) - n_dropped
        family = {"shell": "/SHELL // SH3N",
                  "tshell": "/BRICK (thick shell)",
                  "sph": "/SPHCEL (SPH particle)"}.get(rec.kind, "/BEAM")
        state.warn(
            f"*{rec.keyword}: option '{rec.option}' is not implemented — "
            f"{n_kept} element(s) were kept as plain {family} connectivity and "
            f"{rec.n_unparsed + n_dropped} card(s) in the block were NOT "
            "interpreted (their data is dropped)"
            + (f", of which {n_dropped} looked like connectivity but named "
               "node ids the deck does not define, so they were option data "
               "rather than elements" if n_dropped else "")
            + ". The MESH is preserved; check the element count against the "
            "source deck, and supply the option's data another way if the "
            "model depends on it. (dyna2rad drops this whole block, elements "
            "included.)")
    state.provisional_elem_blocks = []


# ─────────────────────────────────────────────────────────────────────────────
# *ELEMENT_BEAM_ORIENTATION → synthesized third node
# ─────────────────────────────────────────────────────────────────────────────

def _synthesize_beam_orientation_nodes(state: ConversionState) -> None:
    """VX/VY/VZ → a real /NODE at ``pos(N1) + V``, wired into the beam's N3.

    The LS-DYNA manual defines the orientation vector as relative to N1 and says
    it "points to a virtual third node", so the node is placed at N1 + V with the
    vector taken RAW — unnormalized, exactly as dyna2rad does
    (convertelements.cxx:220-232). Normalizing would move the node and is not
    what either code means; the direction is all Radioss keeps
    (hm_read_beam.F:158-161 stores V/|V|).

    Two things dyna2rad gets wrong and this does not:
      * it writes ``elemNodes[2] = <new id>`` BEFORE ``elemNodes.resize(3)``, and
        since a beam whose N3 column is blank arrives with only 2 nodes, the
        resize value-initializes slot 2 back to 0 — so the node is created but
        ``node_ID3`` is emitted as 0 for exactly the elements _ORIENTATION is
        meant for. Here the id is simply assigned to the element.
      * it creates one brand-new node per element even when many beams share an
        N1 and a vector. Here identical (N1, V) pairs share one node — same
        geometry, fewer orphan nodes.

    Runs as a build_starter prepass so the new nodes exist before the /NODE
    section is emitted.

    TRUSS parts are SKIPPED. ``/TRUSS`` has three cells and no orientation
    column (``truss.cfg``; ``hm_read_truss.F`` takes material and property from
    the ``/PART``), so a node minted here would be referenced by nothing — and
    it would enter ``state.beam_orient_nodes``, which the implicit free-node
    sweeper SUBTRACTS, leaving a genuinely unattached node unconstrained.
    """
    if not any(e.vx or e.vy or e.vz for e in state.beam_elems):
        return
    truss_pids = _truss_pids(state)
    cache: Dict[Tuple[int, float, float, float], int] = {}
    n_missing = 0
    n_collinear = 0
    n_truss = 0
    for e in state.beam_elems:
        if e.vx == 0.0 and e.vy == 0.0 and e.vz == 0.0:
            continue
        if e.pid in truss_pids:
            n_truss += 1
            continue
        base = state.nodes.get(e.n1)
        if base is None:
            n_missing += 1
            continue
        key = (e.n1, e.vx, e.vy, e.vz)
        nid = cache.get(key)
        if nid is None:
            nid = state.next_node_id()
            state.nodes[nid] = NodeData(base.x + e.vx, base.y + e.vy,
                                        base.z + e.vz)
            state.beam_orient_nodes.add(nid)
            cache[key] = nid
        e.n3 = nid
        other = state.nodes.get(e.n2)
        if other is not None:
            axis = (other.x - base.x, other.y - base.y, other.z - base.z)
            vec = (e.vx, e.vy, e.vz)
            cr = _vcross(axis, vec)
            la = (axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2) ** 0.5
            lv = (vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2) ** 0.5
            lc = (cr[0] ** 2 + cr[1] ** 2 + cr[2] ** 2) ** 0.5
            if la > 0.0 and lv > 0.0 and lc <= 1e-6 * la * lv:
                n_collinear += 1
    if n_truss:
        state.warn(
            f"*ELEMENT_BEAM_ORIENTATION: {n_truss} element(s) on a "
            "*SECTION_BEAM ELFORM=3 (TRUSS) part state an orientation vector "
            "— IGNORED, and no third node is synthesized for them. A /TRUSS "
            "row is three cells (id, node_ID1, node_ID2) and the element has "
            "no cross-section frame to orient, so the vector has no meaning "
            "and a node placed for it would be referenced by nothing. LS-DYNA "
            "says the same on its side: N3 is 'optional for beam types 3, 6, 7 "
            "and 8' (Vol I R17 p.19-5), and dyna2rad guards its whole "
            "orientation block with `if (destElem != \"/TRUSS\")` "
            "(convertelements.cxx:203). Nothing is lost.")
    if cache:
        state.warn(
            f"*ELEMENT_BEAM_ORIENTATION: {len(cache)} third node(s) synthesized "
            f"at N1 + (VX,VY,VZ) for {sum(1 for e in state.beam_elems if e.vx or e.vy or e.vz)} "
            "beam(s), and written into the /BEAM node_ID3 column. They are pure "
            "geometric reference nodes (the starter tags them CHECK_USED, not "
            "CHECK_BEAM): no mass, no stiffness, no effect on the time step. "
            "Node ids come from the guarded allocator, above every id in the "
            "deck.")
    if n_missing:
        state.warn(
            f"*ELEMENT_BEAM_ORIENTATION: {n_missing} element(s) reference an N1 "
            "with no *NODE record, so no third node could be placed. Those "
            "beams keep the N3 from their base card (normally 0 → starter INFO "
            "2093, N3:=N2, a degenerate local frame).")
    if n_collinear:
        state.warn(
            f"*ELEMENT_BEAM_ORIENTATION: {n_collinear} element(s) give an "
            "orientation vector PARALLEL to their own N1-N2 axis. The "
            "synthesized third node is then collinear with the beam and cannot "
            "define a local Y-Z frame — the section's Iyy/Izz (or the "
            "/PROP/TYPE18 integration points) end up on arbitrary axes. Check "
            "these vectors; dyna2rad does not test for this at all.")


def _unique_node_slots(nodes: List[int]) -> List[int]:
    """SLOT index of each first-seen distinct positive node id.

    ``_ordered_unique_nodes`` returns the surviving ids; this returns where they
    sat on the *ELEMENT_SHELL card, which is what the per-node THIC1..THIC4
    cells are keyed on. The two are only the same list of positions for a
    TRAILING collapse (n1 n2 n3 n3): ``_ordered_unique_nodes`` accepts a repeat
    in ANY slot, so ``n1 n1 n2 n3`` survives with slots 0, 2, 3 and averaging
    THIC1..THIC3 would read a thickness cell belonging to a corner that is not
    in the element.
    """
    seen: Set[int] = set()
    out: List[int] = []
    for i, n in enumerate(nodes):
        if n > 0 and n not in seen:
            seen.add(n)
            out.append(i)
    return out


def _shell_element_thickness(e: ShellElem, slots: List[int],
                            sec_t: float) -> float:
    """Element thickness from the *ELEMENT_SHELL_THICKNESS nodal values.

    Arithmetic mean of THIC over the element's surviving corners (*slots* are
    their positions on the card — see ``_unique_node_slots``), with the
    *SECTION_SHELL thickness substituted for every cell that is zero.

    That substitution is LS-DYNA's own rule, and it is per VALUE, not per
    element: Vol I R17 *ELEMENT_SHELL Card 2 defaults THIC1..THIC4 to ``0.``
    (so a blank cell and an explicit ``0.0`` are the same input), and Remark 1
    reads "Default values in place of zero shell thicknesses are taken from the
    cross-section property definition of the PID". A quad with THIC1=4.0 and
    three empty cells on a T=1.5 section is therefore (4.0+1.5+1.5+1.5)/4 =
    2.125 mm, not 4.0 and not 1.0.

    Both other readings are wrong in a way that scales mass linearly and bending
    stiffness cubically: dyna2rad divides the written values by the node count
    (``convertelements.cxx:290-301``) and gets 1.0; averaging only the non-empty
    cells gets 4.0 and additionally makes the blank and the explicit-zero
    spellings of one LS-DYNA element differ by 4x.

    Every cell zero → 0.0, which is the card's own "use the /PROP thickness"
    value (``cinmas.F:324-329``; ERROR 495 if the property is zero too), so the
    element field is left off entirely. *sec_t* <= 0 means the part has no
    usable *SECTION_SHELL thickness to substitute (k2rad's auto-section is
    0.0) — the non-zero cells are then averaged on their own, which is the best
    available answer and matches what the /PROP would have supplied anyway.
    """
    if not e.thick_nodes:
        return 0.0
    vals = [e.thick_nodes[s] if s < len(e.thick_nodes) else 0.0 for s in slots]
    if not any(vals):
        return 0.0
    if sec_t > 0.0:
        vals = [v if v else sec_t for v in vals]
    else:
        vals = [v for v in vals if v]
    return sum(vals) / len(vals) if vals else 0.0


def _shell_optional_fields(e: ShellElem, slots: List[int], sec_t: float) -> str:
    """The trailing ``Phi`` + ``Thick`` columns of a /SHELL or /SH3N card.

    Both cards carry them at the SAME absolute columns — Phi 61-80, Thick
    81-100 — and both default to 0 when absent, so the fields are emitted only
    when there is something to say. That keeps a deck without the _THICKNESS /
    _BETA variants byte-identical to what k2rad produced before.

    (The shipped ``radioss41/ELEM/shell3n.cfg`` CARD string writes the blank gap
    as ``%30s``, which would put Phi at 71-90 and Thick at 91-110. It disagrees
    with the COMMENT line in the same file, and the STARTER follows the comment:
    a probe deck with /IOFLAG IPRI=5 read a value ending in column 90 back as
    THICKNESS, not as the angle, and discarded everything past column 100. So
    the cfg CARD string is wrong and /SH3N uses the /SHELL columns.)

    Phi is in DEGREES on the card — hm_read_shell.F:170 multiplies by PI/180.
    Note that the starter only READS it for IGTYP 17/51/52; on the orthotropic
    single-property classes the angle has to reach the /PROP instead, which is
    what ``writer/composites.py::_fold_element_beta`` arranges (it zeroes
    ``e.beta`` once it has, so the deck never states the angle twice).
    """
    phi = e.beta
    thick = _shell_element_thickness(e, slots, sec_t)
    if phi == 0.0 and thick == 0.0:
        return ""
    return _f(phi) + _f(thick)


def _warn_part_contact_fields(state: ConversionState) -> None:
    """Report the `*PART_CONTACT` card-8 fields that have no `/PART` destination.

    ``OPTT`` becomes the `/PART` ``Thick`` column (see _make_parts_and_elements).
    The other seven are dropped, and dyna2rad drops them without a word:
    ``convertparts.cxx:133-138`` reads ``OPTT`` and nothing else, and a grep over
    its whole source finds zero references to ``SCFC``/``DCFC``/``EDC``/``VCFC``/
    ``SFT``/``SSF``/``CPARM8``. Two of them change results by a lot, so they are
    named per part with their values.

    ``SFT`` in particular is deliberately NOT multiplied into ``Thick``: LS-DYNA's
    ``SFT`` scales the TRUE (element) thickness, while ``Thick`` REPLACES it, so
    folding one into the other would apply the factor to a quantity it was never
    meant for.

    ``OPTT`` itself gets three warnings of its own, all of them about the value
    reaching ``Thick`` and then not being read: it BEATS the element thickness
    rather than losing to it, it is dead on a solid-only part, and it is dead on
    any interface written with ``Igap = 0``. See the comments at each.
    """
    if not state.part_contacts:
        return
    fric_parts, sft_parts, ssf_parts, cparm_parts = [], [], [], []
    for pid in sorted(state.part_contacts):
        pc = state.part_contacts[pid]
        if pc.fs or pc.fd or pc.dc or pc.vc:
            fric_parts.append(
                f"{pid} (FS={pc.fs:g} FD={pc.fd:g} DC={pc.dc:g} VC={pc.vc:g})")
        if pc.sft:
            sft_parts.append(f"{pid} (SFT={pc.sft:g})")
        if pc.ssf:
            ssf_parts.append(f"{pid} (SSF={pc.ssf:g})")
        if pc.cparm8:
            cparm_parts.append(f"{pid} (CPARM8={pc.cparm8:g})")
    if fric_parts:
        state.warn(
            "*PART_CONTACT: the per-part friction coefficients on part(s) "
            f"{', '.join(fric_parts)} are DROPPED. Radioss expresses friction per "
            "INTERFACE (/INTER Fric, or a /FRICTION table bound through fric_ID), "
            "never per part, and these values only take effect in LS-DYNA when a "
            "*CONTACT card sets FS=-1 anyway. Put the real FS/FD on *CONTACT "
            "Card 2, or collect the per-part pairs into a *DEFINE_FRICTION table "
            "and reference it with FS=-2 (which k2rad does convert).")
    if sft_parts:
        state.warn(
            f"*PART_CONTACT: the thickness SCALE factor on part(s) "
            f"{', '.join(sft_parts)} is DROPPED — it is NOT folded into the /PART "
            "Thick column, because LS-DYNA's SFT scales the element's true "
            "thickness while Thick REPLACES it. Give the scaled value directly as "
            "OPTT if that is what was meant.")
    if ssf_parts:
        state.warn(
            "*PART_CONTACT: the penalty-stiffness scale on part(s) "
            f"{', '.join(ssf_parts)} is DROPPED. Radioss has no per-part stiffness "
            "scale at /BEGIN 2022 — /INTER Stfac is per interface, and the per-side "
            "Igap=5 + THICK_S/THICK_M route is radioss2026-only.")
    if cparm_parts:
        state.warn(
            f"*PART_CONTACT: CPARM8 on part(s) {', '.join(cparm_parts)} is DROPPED "
            "(it exists only from FORMAT(Keyword971_R8.0) and has no Radioss "
            "counterpart).")
    # The CONTACT-gap cascade is THK_PART first, element THK second, property
    # GEO(1,MG) third — i7sti3.F:230-238 tests `IF (THK_PART(IP) /= ZERO .AND.
    # IINTTHICK == 0)` and only falls through to `THK(I)` when the part value is
    # zero (same three-level cascade at :248, :264, :275, :285, :494, :580, :750,
    # :833, and in i11sti3/i20sti3/i24sti3). So a part carrying both loses the
    # ELEMENT thickness from its contact gap, not the OPTT. Measured: an
    # /INTER/TYPE7 at Igap=1 over *ELEMENT_SHELL_THICKNESS 2.0 read GAP MIN =
    # 1.0 without OPTT and 7.0E-3 with OPTT=0.007 — a factor of ~143 the other way
    # from what this warning used to claim. (The Reference Guide's /PART Comment 3
    # is about the shell PROPERTY thickness, level 3, not the element card.)
    thick_elem_pids = {e.pid for e in state.shell_elems
                       if any(t > 0.0 for t in e.thick_nodes)}
    clash = sorted(pid for pid, pc in state.part_contacts.items()
                   if pc.optt and pid in thick_elem_pids)
    if clash:
        named = ", ".join(str(p) for p in clash[:10])
        if len(clash) > 10:
            named += f", ... ({len(clash)} parts)"
        state.warn(
            f"*PART_CONTACT: part(s) {named} carry BOTH "
            "an OPTT contact thickness and per-element *ELEMENT_SHELL_THICKNESS "
            "values. For the CONTACT GAP the part-level OPTT SUPERSEDES the "
            "element thickness (i7sti3.F:230 tests THK_PART first and only falls "
            "through to THK(I) when it is zero) — the element value still governs "
            "the STRUCTURAL thickness. LS-DYNA's OPTT is likewise contact-only, so "
            "this matches; check the two are meant to differ.")
    # OPTT on a part with no shell/tria/1D element is written and then never read:
    # the starter applies THK_PART only in loops over NUMELC, NUMELTG, NUMELT,
    # NUMELP and NUMELR (i7sti3.F:226/244/261/272/283, and the same shape in
    # i11sti3/i20sti3/i24sti3) — there is no NUMELS loop. LS-DYNA differs ("OPTT —
    # Optional contact thickness.  For SOFT = 2, it applies to solids, shells, and
    # beams", Vol I R17 p.37-11), so this is a real silent loss on a solid part.
    # THICK SHELLS count as solids here: they are /BRICK, and the missing
    # NUMELS loop is exactly what leaves their OPTT unread too. SPH PARTICLES
    # join the same bucket for the same reason — there is no NUMSPH loop in
    # i7sti3.F either — and they must NOT join non_solid_pids, or a
    # particles-only part would look like it had a thickness the starter reads.
    non_solid_pids = ({e.pid for e in state.shell_elems}
                      | {e.pid for e in state.beam_elems}
                      | {e.pid for e in state.discrete_elems}
                      # A belt part is a /SPRING or /SHELL part, never a solid,
                      # and i7sti3.F reads OPTT on NUMELC/NUMELP/NUMELR - the
                      # /SPRING loop included - so its OPTT is not lost.
                      | {e.pid for e in state.seatbelt_elems})
    solid_pids = ({e.pid for e in state.solid_elems}
                  | {e.pid for e in state.tshell_elems}
                  | {c.pid for c in state.sph_elems})
    solid_only = sorted(f"{pid} (OPTT={pc.optt:g})"
                        for pid, pc in state.part_contacts.items()
                        if pc.optt and pid in solid_pids
                        and pid not in non_solid_pids)
    if solid_only:
        listed = ", ".join(solid_only[:10])
        if len(solid_only) > 10:
            listed += f", ... ({len(solid_only)} parts)"
        state.warn(
            f"*PART_CONTACT: part(s) {listed} hold SOLID or SPH elements "
            "only, so the OPTT written into their /PART Thick column has NO "
            "EFFECT. The starter reads THK_PART in its shell/tria/truss/beam/"
            "spring loops only (i7sti3.F:226-293) — there is no solid loop — while "
            "LS-DYNA does apply OPTT to solids under SOFT=2. Set the gap on the "
            "interface instead (/INTER Gapmin, or Igap=2 to take it from the "
            "element size).")
    # And the /PART Thick column is only consulted at all by an interface with
    # Igap >= 1: on /INTER/TYPE7 the whole secondary-node gap block that reads
    # THK_PART sits inside `IF(IGAP >= 1)` (i7sti3.F:222), and at Igap=0 the
    # interface uses ONE constant gap (Gapmin, or the main surface's own average
    # when Gapmin is 0 — the secondary side's thickness never enters). k2rad's
    # default TYPE7 is Igap=0. Measured: identical decks with and without OPTT=5.0
    # on the 1.0 mm moving plate gave the SAME contact onset 0.0090042418 s;
    # patching only the Igap column of that same deck to 1 moved it to
    # 0.0070024668 s, the hand-computed 0.002000 s earlier (+0.089 %). The TYPE25
    # route k2rad emits from *CONTACT_AUTOMATIC_NODES_TO_SURFACE (Igap=2) is live
    # as shipped: 0.0090043144 -> 0.0070017553 s (+0.128 %).
    optt_pids = sorted(pid for pid, pc in state.part_contacts.items() if pc.optt)
    if optt_pids:
        # A crash deck can carry hundreds of *PART_CONTACT cards (512 on the Yaris
        # model), so the list is capped the way the /RBE3 reporters cap theirs.
        shown = ", ".join(str(p) for p in optt_pids[:10])
        if len(optt_pids) > 10:
            shown += f", ... ({len(optt_pids)} parts)"
        state.warn(
            f"*PART_CONTACT: OPTT on part(s) {shown} reaches the /PART Thick "
            "column, but Radioss only consults it for interfaces with Igap >= 1 — "
            "on /INTER/TYPE7 the whole THK_PART block is inside `IF(IGAP >= 1)` "
            "(i7sti3.F:222), and at Igap=0 the gap is the single constant Gapmin. "
            "k2rad's plain TYPE7 (from *CONTACT_SURFACE_TO_SURFACE and friends) "
            "carries Igap=0, so OPTT is INERT there; the TYPE25 route and the "
            "SOFT=-7 TYPE7 both use Igap=2 and do honour it. Check the Igap column "
            "of the interfaces that scope these parts, and set /INTER Gapmin "
            "directly (or *CONTACT Card 3 SST/MST) if the gap has to change.")


def _make_parts_and_elements(state: ConversionState, progress=None) -> List[str]:
    if not state.parts:
        return []
    _warn_part_contact_fields(state)
    lines = ["#-  PARTS AND ELEMENTS:", HDR]

    # Progress is driven off the solid elements (the dominant count); a single
    # part can hold every tet, so the counter ticks inside the emission loops.
    _emitted = 0
    _total = max(1, len(state.solid_elems))
    _step = max(1, _total // 30)

    def _tick():
        nonlocal _emitted
        _emitted += 1
        if progress is not None and _emitted % _step == 0:
            progress(_emitted / _total)

    shells_by_pid: Dict[int, List[ShellElem]] = defaultdict(list)
    for e in state.shell_elems:
        shells_by_pid[e.pid].append(e)

    solids_by_pid: Dict[int, List[SolidElem]] = defaultdict(list)
    for e in state.solid_elems:
        solids_by_pid[e.pid].append(e)

    # Thick shells are /BRICK too, but they get their OWN bucket: the solid
    # bucket is split by distinct-node count into /TETRA4 // /TETRA10 //
    # /BRICK, and a degenerate 6-node thick shell (written n1 n2 n3 n3 n5 n6 n7
    # n7) must stay the collapsed 8-node form — ERROR 639 refuses the 6-node
    # penta on a thick-shell property unless Isolid=15.
    tshells_by_pid: Dict[int, List] = defaultdict(list)
    for e in state.tshell_elems:
        tshells_by_pid[e.pid].append(e)

    # SPH particles get their own bucket for the strongest reason in this
    # function: they have NO connectivity at all (one node, a mass) and a
    # /SPHCEL is not an element card in the /SHELL // /BRICK sense.
    sph_by_pid: Dict[int, List] = defaultdict(list)
    for c in state.sph_elems:
        sph_by_pid[c.pid].append(c)

    # *SECTION_BEAM ELFORM=3 parts: their *ELEMENT_BEAM rows are /TRUSS, not
    # /BEAM. Split HERE, on the write side, so the elements stay in
    # state.beam_elems for every LS-DYNA-side lookup (*SET_BEAM,
    # *DATABASE_HISTORY_BEAM, the *INCLUDE_TRANSFORM offset walk) — see
    # common._truss_secids for the data-model verdict.
    truss_pids = _truss_pids(state)
    beams_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    truss_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    for e in state.beam_elems:
        (truss_by_pid if e.pid in truss_pids else beams_by_pid)[e.pid].append(e)
    if truss_by_pid:
        _warn_truss_releases(
            state, [e for es in truss_by_pid.values() for e in es])

    # Connector parts (discrete springs/dampers, MAT_100 spotweld beam parts,
    # *SECTION_BEAM ELFORM=6 discrete beams, 1D SEATBELTS) are emitted by the
    # connector sections with their own /PROP/TYPE4-13/23 and /SPRING elements —
    # emitting them here would reference a DYNA section / material id that has
    # no /PROP or /MAT counterpart, and would write the /PART twice (ERROR 79).
    connector_pids = (_discrete_part_ids(state) | _spotweld_beam_pids(state)
                      | _discrete_beam_pids(state)
                      | _seatbelt_part_ids(state)
                      # *MAT_MUSCLE truss parts: /PART + /PROP/TYPE46 + /SPRING
                      # from _make_muscle_springs. (Its *MAT_SPRING_MUSCLE half
                      # is already inside _discrete_part_ids.)
                      | _muscle_part_ids(state))

    for pid, part in sorted(state.parts.items()):
        if pid in connector_pids:
            continue
        secid = part.secid if part.secid > 0 else pid
        # A composite / orthotropic part is repointed at its synthesized
        # property, because every one of those laws is orthotropic-class and the
        # isotropic section /PROP is rejected by the starter (ERROR 3047):
        #   tshell     – a per-part thick-shell layup (*PART_COMPOSITE_TSHELL,
        #                or a uniform *ELEMENT_TSHELL_COMPOSITE stack)
        #                → /PROP/TYPE22. Claimed FIRST: the thick-shell prepass
        #                runs before the composite one, which then skips the
        #                part, so the two can never both fire.
        #   composite  – *PART_COMPOSITE layup, MAT_002/037/054/055/032
        #                (/PROP/TYPE51+TYPE19, TYPE11, TYPE9 or TYPE6)
        #   ortho      – *MAT_ANISOTROPIC_VISCOPLASTIC → LAW128 (TYPE9/TYPE6)
        #   hourglass  – per-part hourglass differing from the section base
        # The three are mutually exclusive by construction (each prepass skips
        # the parts the earlier ones claimed); the order here just makes the
        # precedence explicit.
        #   sph        – an SPH part whose *SECTION_SPH SECID is also claimed
        #                by another element family; the /PROP/SPH moved to a
        #                synthesized id (writer/sph.py _split_mixed_family_
        #                sections) and the /PART follows it.
        #   fabric     – *MAT_FABRIC → /PROP/TYPE9 (LAW19) or /PROP/TYPE16
        #                (LAW58); the starter REFUSES either law on the
        #                isotropic /PROP/SHELL a *SECTION_SHELL would give it
        #                (ERROR 3047), so the part must follow the synthesized
        #                property. Claimed first among the shell families.
        #   seatbelt2d - a 2D (shell) *ELEMENT_SEATBELT part on
        #                /MAT/LAW119, which declares SHELL_ORTHOTROPIC
        #                (hm_read_mat119.F:218) and is refused on the
        #                isotropic /PROP/SHELL for the same ERROR 3047.
        prop_ref = (state.tshell_prop_ids.get(pid)
                    or state.sph_prop_ids.get(pid)
                    or state.fabric_prop_ids.get(pid)
                    or state.seatbelt_prop_ids.get(pid)
                    or state.composite_prop_ids.get(pid)
                    or state.ortho_prop_ids.get(pid)
                    or state.hourglass_prop_ids.get(pid, secid))

        # *PART_CONTACT OPTT → the /PART card's 4th field, Thick (cols 31-50,
        # F20): "(Optional) Virtual thickness for shells.  Define a thickness for
        # shells, only used to calculate gap in interfaces" (Reference Guide 2022
        # p.194-195). Starter side, hm_read_part.F:193-198 stores it raw as
        # THK_PART(I), and i7sti3.F:226-238 picks it as the FIRST of three levels:
        # `IF (THK_PART(IP) /= ZERO ...)`, then the element thickness, then the
        # property's.
        #
        # Which interfaces actually read it is narrower than the Reference Guide's
        # sentence suggests, and _warn_part_contact_fields says so per deck. The
        # secondary-gap block is gated by `IF(IGAP >= 1)` on TYPE7 (i7sti3.F:222)
        # and TYPE20 (i20sti3.F:149), and k2rad's plain TYPE7 is Igap=0. TYPE11
        # and TYPE24 read it UNgated (i11sti3.F:212, i24sti3.F:182), and the
        # TYPE25 k2rad emits carries Igap=2 — measured live, OPTT=5.0 moved that
        # interface's contact onset by 0.0020025591 s against 0.002000 s
        # predicted (+0.128 %).
        #
        # The field is only written when non-zero. That test is not cosmetic: the
        # starter's own gate is `/= ZERO`, so a written 0.0 is INDISTINGUISHABLE
        # from blank — a literal zero contact thickness is not expressible through
        # /PART at all — and suppressing it keeps the 3-field line every deck
        # without the option has always produced, byte for byte.
        part_thick = 0.0
        pc = state.part_contacts.get(pid)
        if pc is not None and pc.optt:
            part_thick = pc.optt
        # An SPH part whose *MAT_PLASTIC_KINEMATIC is shared with a shell or
        # solid part points at the /MAT/LAW2 CLONE instead: LAW44 is not
        # SPH-declared and one /MAT id cannot be two laws (writer/sph.py
        # ::_resolve_sph_materials). Empty on every other deck.
        mat_ref = state.sph_mat_ids.get(pid, part.mid)
        lines += [
            f"/PART/{pid}",
            part.title or f"PART_{pid}",
            (f"{_i(prop_ref)}{_i(mat_ref)}         0{_f(part_thick)}"
             if part_thick else f"{_i(prop_ref)}{_i(mat_ref)}         0"),
            HDR,
        ]
        if pid in shells_by_pid:
            # Split quads from triangles. LS-DYNA writes a triangular shell either
            # as 3 IDs (blank N4) or as a 4-slot quad with the last corner repeated
            # (n1 n2 n3 n3) — a "collapsed quad". Both must become /SH3N, not a
            # 4-node /SHELL, because Radioss sizes the two element types with
            # DIFFERENT critical-time-step rules: /SH3N uses the triangle form
            # (L = 2A/L_max, matching LS-DYNA's beta=1 rule) while /SHELL uses the
            # quad length. Passing a collapsed quad through as /SHELL therefore
            # halves dt for the whole model off a single degenerate element — on
            # the W13 blast deck 370 collapsed quads (of 38,218) held dt at
            # 8.361e-7 s where the triangle rule gives 1.6919e-6 s, doubling
            # runtime. A collapsed 4-node shell is also not numerically identical
            # to a C0 triangle, so this is a fidelity fix as well as a cost one.
            # The *ELEMENT_SHELL_THICKNESS cells are keyed on the CARD SLOT, so
            # a collapsed quad carries its surviving corners' slot indices to
            # the thickness mean, not the first three cells.
            sec_t = state.sec_shells[secid].t1 if secid in state.sec_shells \
                else 0.0
            quads = []
            tris = []                 # (ShellElem, [n1, n2, n3], [slot, ...])
            n_bowtie = 0
            for e in shells_by_pid[pid]:
                slots = _unique_node_slots(e.nodes)
                uniq = [e.nodes[s] for s in slots]
                if len(uniq) >= 4:
                    quads.append(e)
                elif len(uniq) == 3:
                    if len(e.nodes) == 4 and not any(
                            e.nodes[i] == e.nodes[(i + 1) % 4] for i in range(4)):
                        # Repeated corner is NOT adjacent (e.g. n1 n2 n1 n3): a
                        # zero-area "bowtie", not an ordinary collapse. Emitting
                        # the 3 distinct corners invents area the original element
                        # did not have, so say so rather than fix it silently.
                        n_bowtie += 1
                    tris.append((e, uniq, slots))
                else:
                    # < 3 distinct corners: zero area, no valid element (Radioss
                    # would reject it). Mirrors the degenerate-solid screening.
                    state.warn(
                        f"PART {pid}: shell {e.eid} has only {len(uniq)} distinct "
                        f"node(s) {uniq} — zero area, dropped (it cannot be a "
                        "/SHELL or a /SH3N).")
            if n_bowtie:
                state.warn(
                    f"PART {pid}: {n_bowtie} shell(s) repeat a corner in "
                    "NON-adjacent slots (n1 n2 n1 n3) — a zero-area bowtie rather "
                    "than a normal triangle collapse. Emitted as /SH3N on the 3 "
                    "distinct corners, which gives them real area; check these "
                    "elements in the source mesh.")
            if quads:
                lines.append(f"/SHELL/{pid}")
                for e in quads:
                    row = _i(e.eid)
                    for n in e.nodes:
                        row += _i(n)
                    pad = 4 - len(e.nodes)
                    if pad > 0:
                        row += "         0" * pad
                    row += "         0"          # blank field, cols 51-60
                    row += _shell_optional_fields(e, [0, 1, 2, 3], sec_t)
                    lines.append(row)
                    # The #106 register, the /SHELL half. See the note on the
                    # /BEAM one below: recorded at the line that writes the row
                    # so a part with no *PART record — never visited by this
                    # loop — cannot reach a /TH/SHEL group.
                    state.shell_elem_ids.add(e.eid)
                # The PART-scoped half of the same register: /DYNAIN/DT selects
                # by part and writes shells only, so a part list has to be
                # screened on "owns a shell", not on "is a part".
                state.shell_part_ids.add(pid)
                lines.append(HDR)
            if tris:
                # /SH3N shares the part's /PROP/SHELL (its Ish3n field selects the
                # triangle formulation), so quads and triangles coexist under one
                # /PART — unlike /TETRA10, which needs a part of its own.
                lines.append(f"/SH3N/{pid}")
                for e, nd, slots in tris:
                    row = (_i(e.eid) + _i(nd[0]) + _i(nd[1]) + _i(nd[2])
                           + "         0")
                    tail = _shell_optional_fields(e, slots, sec_t)
                    if tail:
                        # The 0 above sits in the 41-60 blank field; pad it out
                        # to column 60 so Phi/Thick land at 61-80 / 81-100.
                        row += " " * 10 + tail
                    lines.append(row)
                    # The #106 register, the /SH3N half — the split /TH/SHEL vs
                    # /TH/SH3N reads back, so it can never re-decide the
                    # topology differently from this loop.
                    state.sh3n_elem_ids.add(e.eid)
                state.shell_part_ids.add(pid)
                lines.append(HDR)
        if pid in solids_by_pid:
            # Emit 4-node tetrahedra as proper /TETRA4. Writing a tet as an
            # 8-node /BRICK with collapsed nodes reintroduces spurious
            # hourglass modes (a real tet has none) -> the load energy goes
            # into zero-stress hourglassing and the stress is garbage on
            # tet-meshed parts (observed on implicit_hr-anlenkung: I-ENERGY
            # ~0.8 J vs EXT-WORK ~690 J, -99.9% energy error). 5-8 unique
            # nodes stay /BRICK (a wedge/pyramid as a degenerate hex is ok).
            # 10-node solids are quadratic tets -> /TETRA10 (all 10 nodes kept).
            # Degenerate (<4 distinct nodes, ERROR 245) and sliver screening
            # (tet10 always, tet4 for implicit) already ran in
            # _screen_sliver_tets, so every element here is emitted.
            tets = []     # (eid, [n1, n2, n3, n4])
            tets10 = []   # SolidElem with 10 nodes (quadratic tet)
            bricks = []   # SolidElem with >4 distinct nodes
            for e in solids_by_pid[pid]:
                if len(e.nodes) == 10:
                    tets10.append(e)
                    continue
                uniq = _ordered_unique_nodes(e.nodes)
                if len(uniq) == 4:
                    tets.append((e.eid, uniq))
                else:
                    bricks.append(e)
            if tets10 and (tets or bricks):
                state.warn(
                    f"PART {pid}: mixes 10-node tets with 4-node/brick solids. "
                    "OpenRadioss requires /TETRA10 to use a part_ID distinct from "
                    "/TETRA4 and /BRICK; emitted together under one /PART, which the "
                    "starter may reject — split the part by element type if so."
                )
            if tets:
                lines.append(f"/TETRA4/{pid}")
                for eid, nd in tets:
                    row = _i(eid)
                    for n in nd:
                        row += _i(n)
                    lines.append(row)
                    # The #106 register. /TETRA4, /TETRA10 and /BRICK share one
                    # Radioss solid id pool (all three land in IXS), so
                    # /TH/BRIC resolves any of them and all three register into
                    # the same set.
                    state.solid_elem_ids.add(eid)
                    _tick()
                lines.append(HDR)
            if tets10:
                # /TETRA10: 2 lines per element — tetra_ID, then the 10 node IDs
                # (10 fixed-width fields). Connectivity is in Radioss /TETRA10 order
                # here: any LS-DYNA *ELEMENT_SOLID input was permuted to it by
                # _normalize_tet10_ordering (apex nodes 8/9/10 → mid(1,4)/mid(2,4)/
                # mid(3,4)), so emit verbatim. Emitting LS-DYNA order 1:1 was the
                # silent −30%-volume bug (LS-DYNA and Abaqus do NOT share this map).
                lines.append(f"/TETRA10/{pid}")
                for e in tets10:
                    lines.append(_i(e.eid))
                    lines.append("".join(_i(n) for n in e.nodes[:10]))
                    state.solid_elem_ids.add(e.eid)          # #106 register
                    _tick()
                lines.append(HDR)
            if bricks:
                lines.append(f"/BRICK/{pid}")
                for e in bricks:
                    nodes = list(e.nodes)
                    if len(nodes) < 8:
                        nodes += [nodes[-1]] * (8 - len(nodes))
                    row = _i(e.eid)
                    for n in nodes[:8]:
                        row += _i(n)
                    lines.append(row)
                    state.solid_elem_ids.add(e.eid)          # #106 register
                    _tick()
                lines.append(HDR)
        if pid in tshells_by_pid:
            # *ELEMENT_TSHELL → /BRICK with the LS-DYNA n1..n8 order VERBATIM.
            # LS-DYNA's n1-n4 = lower face / n5-n8 = upper face is exactly the
            # pairing Radioss reads with Icstr=010 — scdtchk3.F takes the
            # through-thickness edges as (1-5) (2-6) (3-7) (4-8) there, and
            # scortho3.F builds the same S axis out of the connectivity — so
            # the thickness direction survives with NO permutation. (Contrast
            # /TETRA10, where a verbatim copy was the -30%-volume bug.)
            #
            # A degenerate 6-node thick shell arrives as the collapsed
            # n1 n2 n3 n3 n5 n6 n7 n7 pattern and stays that way: written with
            # trailing ZEROS instead it would be classified ISOLNOD=6 and then
            # refused on any thick-shell property with Isolid != 15 —
            # ERROR 639, whose own text names "n1 n2 n3 n4 n5 n6 n6 n5" as the
            # alternative. The collapsed form is legal for both formulations.
            if pid in solids_by_pid:
                state.warn(
                    f"PART {pid} holds BOTH *ELEMENT_SOLID and *ELEMENT_TSHELL "
                    "elements. They share the /BRICK card but need different "
                    "properties — a solid wants /PROP/SOLID, a thick shell "
                    "/PROP/TYPE20|21|22 — and a /PART carries exactly one, so "
                    "the thick shells run on the property the section route "
                    "chose and one of the two groups is wrong. Split them into "
                    "separate *PARTs.")
            lines.append(f"/BRICK/{pid}")
            for e in tshells_by_pid[pid]:
                row = _i(e.eid)
                for n in e.nodes[:8]:
                    row += _i(n)
                lines.append(row)
                # #106 register. A thick shell IS a /BRICK here, so
                # *DATABASE_HISTORY_TSHELL screens against the same set.
                state.solid_elem_ids.add(e.eid)
            lines.append(HDR)
        if pid in sph_by_pid:
            # *ELEMENT_SPH → /SPHCEL/<part_ID>, one row per particle. The cell
            # id IS the node id (hm_read_sphcel.F:243-250), so there is nothing
            # to renumber and nothing to permute; what the block does carry is
            # the MASS, and whether it is written per row at all was decided
            # once, per section, by writer/sph.py::_resolve_sph.
            from .sph import _emit_sphcel_block
            lines += _emit_sphcel_block(state, pid, sph_by_pid[pid])
        if pid in beams_by_pid:
            lines.append(f"/BEAM/{pid}")
            for e in beams_by_pid[pid]:
                lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}{_i(e.n3)}")
                # The #106 register. *DATABASE_HISTORY_BEAM has to know which
                # of its ids became a /BEAM and which became a /SPRING (a
                # *MAT_SPOTWELD or ELFORM=6 part), and which became NEITHER
                # because the pid has no *PART record and this loop never
                # visited it. Recorded at the line that writes the row, never
                # derived from state.beam_elems, for exactly that reason.
                state.beam_elem_ids.add(e.eid)
            lines.append(HDR)
        if pid in truss_by_pid:
            # /TRUSS/<pid> — three cells, and its own #106 register
            # (state.truss_elem_ids), filled at the write line inside
            # _emit_truss_block for the same reason the /BEAM half states.
            lines += _emit_truss_block(state, pid, truss_by_pid[pid])

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Per-part hourglass control (*HOURGLASS + *PART HGID → per-part /PROP)
# ─────────────────────────────────────────────────────────────────────────────
#
# Semantics follow dyna2rad ConvertProp::ConvertEntities (solids only there):
#   h ← QM (or the global *CONTROL_HOURGLASS QH); Isolid ← f(IHQ) with
#   IHQ 1/2/3 → 1, 4/5 → 5, 6/7 → 24; 0/8/9/10 unmapped (section Isolid kept).
#   The map is gated to /PROP/SOLID with ELFORM ∉ {2,13} (2 = fully-integrated
#   S/R hex — no hourglass modes; 13 = tetra) and a section Isolid ∉ {14,17,18}
#   (not ALE/cohesive). A *HOURGLASS on a *PART overrides the global card;
#   HGID=0 (or a dangling id) falls back to it.
#
# k2rad props are per-SECTION, so — unlike dyna2rad, which mutates the shared
# /PROP in place and lets the last part win — a per-part hourglass difference
# forces a dedicated /PROP split (the same mechanism as the LAW128 ortho props),
# keeping every part's setting. Shells carry the coefficient into Hm/Hf/Hr
# (clamped to the Radioss shell max 0.05); k2rad selects Ishell from ELFORM
# (12/24), for which Hm/Hf/Hr are physically inert (warned once), so no
# IHQ→Ishell map is invented (dyna2rad maps no shell formulation either).

_SHELL_HG_MAX = 0.05   # Radioss /PROP/SHELL Hm/Hf/Hr upper bound (cfg CHECK)


def _auto_section_solid(secid: int) -> SectionSolid:
    """The default *SECTION_SOLID k2rad synthesizes when a *PART's SECID has no
    *SECTION_SOLID card. Kept in sync with the auto-create in _make_properties so
    the hourglass prepass (which runs BEFORE that auto-create) resolves a part on
    an undefined section to the SAME formulation the property emit will use —
    ELFORM 1, the under-integrated structural hex."""
    return SectionSolid(secid, f"AutoPropSolid_{secid}", 1)


def _auto_section_tshell(secid: int) -> SectionTshell:
    """The placeholder *SECTION_TSHELL for a thick-shell *PART whose SECID has
    no card. Re-exported from writer/tshell.py so the two cannot drift."""
    from .tshell import auto_section_tshell
    return auto_section_tshell(secid)


def _auto_section_shell(secid: int) -> SectionShell:
    """The default *SECTION_SHELL k2rad synthesizes for a sectionless shell
    *PART (in sync with _make_properties): ELFORM 2, NIP 3, zero thickness."""
    return SectionShell(secid, f"AutoPropShell_{secid}", 2, 3, 0.0)


def _element_free_part_ids(state: ConversionState,
                           part_secids: Dict[int, int]) -> Set[int]:
    """*PART ids that own no elements AND whose property id nothing emits.

    ``_make_properties`` derives its missing-section set from the ELEMENTS that
    name a secid, so an element-free *PART is never reached: nothing creates a
    section for it, nothing emits a /PROP — yet ``_make_parts_and_elements``
    still writes its /PART card pointing at that id. The starter rejects the
    result outright, ERROR 178 "PROPERTY ID=<x> DOES NOT EXIST", and the whole
    conversion is dead on a part that carries no mesh.

    The part is NOT simply dropped instead, for two reasons:

    * A part id is addressable independently of its mesh. ``*SET_PART`` members
      reach the deck as ``/GRNOD/PART`` (gravity), ``/SURF/PART``, ``/GRBRIC/
      PART`` and subset ids, and none of those are filtered against the parts
      that were actually emitted — dropping the /PART downgrades ERROR 178 to
      starter WARNING 194, "REFERENCE TO NONEXISTENT PART ID=<x>" (measured on
      a *LOAD_BODY_PARTS deck), which is quieter but still a broken deck.
    * An element-free part is idiomatic, not a mistake: ``*INTEGRATION_SHELL``'s
      PID_i "may reference a part with no elements" (Vol I R17 p.29-17) purely
      to carry a layer MATERIAL. Deleting it would delete the material binding
      the user wrote the part for.

    dyna2rad is deliberately NOT followed here: it emits the /PART with
    ``prop_ID = 0`` (convertprops.cxx:110-150 — SECID 0 leaves ``radPropEdit``
    invalid and the else-branch writes entity id 0), which its own starter then
    rejects with the SAME ERROR 178, just reporting "PROPERTY ID=0"
    (hm_read_part.F:203-210 — note MID 0 gets a fictitious-material fallback a
    few lines down, PID 0 gets none). The native reader is broken on this deck,
    so there is nothing to match.

    So the part keeps its id, its title, its material and its subset, and gets
    the same placeholder property a sectionless MESHED shell part already gets.
    A property with no elements on it costs nothing: the starter's ELEM/PROP/MAT
    compatibility checks run per element group, and this one has none.
    """
    meshed = ({e.pid for e in state.shell_elems}
              | {e.pid for e in state.solid_elems}
              | {e.pid for e in state.tshell_elems}
              # SPH particles ARE a mesh. Leaving them out gave a particle part
              # the placeholder /PROP/SHELL — measured on master, exactly the
              # bare "/PART on a placeholder shell property and nothing else"
              # shape the thick-shell batch found, and a /SPHCEL cannot run on
              # a shell property at all.
              | {c.pid for c in state.sph_elems}
              | {e.pid for e in state.beam_elems}
              | {e.pid for e in state.discrete_elems}
              # 1D belt SPRINGS are a mesh too. A belt part left out here would
              # get the placeholder /PROP/SHELL *and* a duplicate /PART from
              # the seatbelt section (ERROR 79). 2D belt elements are folded
              # into state.shell_elems by _assign_seatbelt_props, so they are
              # already covered by the first term.
              | {e.pid for e in state.seatbelt_elems if not e.is_2d})
    # Parts the normal /PART emission skips: their /PART *and* /PROP come from
    # the connector writers, so they never carry a section-derived prop_ref.
    # (_discrete_part_ids already claims an element-free part whose SECID is a
    # *SECTION_DISCRETE or whose MID is a spring/damper material, and
    # _discrete_beam_pids one whose SECID is an ELFORM=6 *SECTION_BEAM.)
    connectors = (_discrete_part_ids(state) | _spotweld_beam_pids(state)
                  | _discrete_beam_pids(state) | _seatbelt_part_ids(state)
                  | _muscle_part_ids(state))
    # A part repointed at a synthesized composite / orthotropic / per-part
    # hourglass property does not reference its section id at all.
    split = (set(state.composite_prop_ids) | set(state.ortho_prop_ids)
             | set(state.hourglass_prop_ids) | set(state.tshell_prop_ids)
             | set(state.sph_prop_ids) | set(state.fabric_prop_ids)
             | set(state.seatbelt_prop_ids))
    # Any section id already defined resolves on its own — including one shared
    # with a meshed sibling part, and including the auto-created sections the
    # caller has just filled in.
    defined = (set(state.sec_shells) | set(state.sec_solids)
               | set(state.sec_beams) | set(state.sec_discrete)
               | set(state.sec_tshells) | set(state.sec_sph)
               | set(state.sec_seatbelts))
    return {pid for pid in state.parts
            if pid not in meshed and pid not in connectors and pid not in split
            and pid in part_secids and part_secids[pid] not in defined}


def _ihq_to_isolid(ihq: int) -> Optional[int]:
    """LS-DYNA solid IHQ → Radioss Isolid (dyna2rad table). None = unmapped
    (IHQ 0/8/9/10): the section's ELFORM-derived Isolid is kept."""
    if ihq in (1, 2, 3):
        return 1
    if ihq in (4, 5):
        return 5
    if ihq in (6, 7):
        return 24
    return None


def _solid_hg_values(state: ConversionState, sec: Optional[SectionSolid],
                     hg) -> Tuple[Optional[float], Optional[int]]:
    """Effective (h, isolid_override) for a solid section, combining the global
    *CONTROL_HOURGLASS base with an optional *HOURGLASS override *hg*. Returns
    (None, None) when the (k2rad-adapted) solid gate excludes the section — ALE,
    a fully-integrated S/R hex (ELFORM 2) or tetra (ELFORM 13), or a tet4/
    cohesive Isolid (14/18) — or no hourglass source applies. h is the
    coefficient verbatim (no IHQ dependence);
    isolid_override None keeps the ELFORM Isolid — the 'mixed result' when the
    IHQ is unmapped but the base card mapped one. See the gate note below for
    why k2rad's structural-hex Isolid 17 is (unlike dyna2rad) NOT excluded."""
    if sec is None:
        return (None, None)
    # dyna2rad gates the solid map to /PROP/TYPE14 with elform ∉ {2,13} and
    # Radioss Isolid ∉ {14,17,18}. That Isolid set is dyna2rad's fluid/ALE/
    # cohesive formulations; k2rad, however, numbers its *default structural
    # hex* Isolid 17 (full integration, chosen for implicit accuracy). Porting
    # the literal {14,17,18} exclusion would gate out every k2rad solid (its
    # only ELFORM-derived Isolids are 17 and 14) and make the whole feature a
    # no-op. So the gate
    # is adapted to the same *intent* — skip ALE, full-integration, tetra, and
    # cohesive, where hourglass control is meaningless — while allowing the
    # structural hex (17) to be remapped to the under-integrated 1/5/24 the IHQ
    # dictates (necessary anyway: Isolid 17 is full-integration and ignores h).
    # ELFORM 2 = fully-integrated S/R hex (no hourglass modes); 13 = tetra
    # (LS-DYNA tets are ELFORM 10/13, not 2 — 2 is a hex).
    if sec.iale or sec.elform in (2, 13):
        return (None, None)
    if sec.elform in _COHESIVE_ELFORMS:
        return (None, None)     # /PROP/TYPE43: 4 mid-plane points, no HG modes
    if _elform_to_isolid(sec.elform) in (14, 18):
        return (None, None)     # tet4 (Kessler=14) / cohesive (18): no HG modes
    h: Optional[float] = None
    iso: Optional[int] = None
    if state.ctrl_hourglass is not None:
        h = state.ctrl_hourglass.qh
        m = _ihq_to_isolid(state.ctrl_hourglass.ihq)
        if m is not None:
            iso = m
    if hg is not None:
        h = hg.qm
        m = _ihq_to_isolid(hg.ihq)
        if m is not None:
            iso = m
    return (h, iso)


def _shell_hg_values(state: ConversionState, sec: Optional[SectionShell],
                     hg) -> Tuple[Optional[float], Optional[int]]:
    """Effective (hm, ishell_override) for a shell section. The LS-DYNA
    hourglass coefficient (QM, or the global QH) goes into Hm/Hf/Hr clamped to
    _SHELL_HG_MAX; Ishell stays ELFORM-derived (ishell_override always None —
    dyna2rad maps no shell formulation and the ELFORM selection must not
    regress). Returns (None, None) when no hourglass source applies."""
    if sec is None:
        return (None, None)
    coeff: Optional[float] = None
    if state.ctrl_hourglass is not None:
        coeff = state.ctrl_hourglass.qh
    if hg is not None:
        coeff = hg.qm
    if coeff is None:
        return (None, None)
    return (min(max(coeff, 0.0), _SHELL_HG_MAX), None)


def _effective_solid_isolid(state: ConversionState, pid: int,
                            sec: Optional[SectionSolid]) -> int:
    """The Isolid the /PROP/SOLID that *part pid* references actually emits, once
    per-part hourglass control has had its say: the per-part split's Isolid, else
    the global *CONTROL_HOURGLASS remap on the shared prop, else (no hourglass)
    the section's ELFORM Isolid. The /INIBRI writer needs this — not the raw
    ELFORM Isolid — so its Nb_integr matches the property's integration order
    once IHQ remaps a full-integration hex to an under-integrated 1/5/24 (a
    stale Nb_integr is rejected by the starter, MSGID 695)."""
    base = 0 if (sec and sec.iale) else \
        (_elform_to_isolid(sec.elform) if sec else 17)
    if pid in state.hourglass_prop_ids:
        iso_over = state.hourglass_prop_vals.get(pid, (None, None))[1]
        return iso_over if iso_over is not None else base
    _, iso = _solid_hg_values(state, sec, None)
    return iso if iso is not None else base


# LS-DYNA cohesive solid formulations (*SECTION_SOLID Vol I R16 p.41-88):
# ±19 = 8-node 4-point cohesive (+19 zero-thickness, -19 with plane offset),
# 20 = 19 with offsets for use WITH SHELLS (transmits moments), ±21/22 = the
# 6-node pentahedron counterparts (*ELEMENT_SOLID pattern N1 N2 N3 N3 N5 N6
# N7 N7 — a degenerate hex the /BRICK writer passes through verbatim, which
# is exactly what /PROP/TYPE43 wants: it is 8-node-hex-only, so the penta
# lives as the collapsed pattern on both sides).
_COHESIVE_ELFORMS = frozenset({19, -19, 20, 21, -21, 22})

# Radioss laws /PROP/TYPE43 accepts (check_mat_elem_prop_compatibility.F:
# 228-232: PROP_SOLID must be 4, 6 or 7, else ERROR 3047):
#   4 SOLID_COHESIVE  = LAW59, LAW83, LAW116, LAW117, LAW169 (the complete
#     INIT_MAT_KEYWORD("SOLID_COHESIVE") call-site list in the 2026-05-20
#     starter tree)
#   6 SOLID_ALL       = LAW13, LAW120 (+ user laws 29/31/99, never emitted)
#   7 SOLID_BRICK_ISOTROPIC = LAW77, LAW88
# The reverse also holds: a SOLID_COHESIVE law on a plain /PROP/SOLID
# (TYPE14 accepts classes 1/5/6/7) is the same ERROR 3047 — which is why the
# routing below follows the MATERIAL when the ELFORM alone says nothing
# (*MAT_ARUP_ADHESIVE runs on ordinary ELFORM 1/2/15 bricks in LS-DYNA).
_TYPE43_LAWS = frozenset({13, 59, 77, 83, 88, 116, 117, 120, 169})

# The three laws of this converter that are SOLID_COHESIVE-classed — a part
# on one of them can ONLY live on /PROP/TYPE43.
_SOLID_COHESIVE_LAWS = frozenset({116, 117, 169})


def _cohesive_solid_secids(state: ConversionState) -> Set[int]:
    """Solid SECIDs that must emit /PROP/TYPE43 instead of /PROP/SOLID.

    Two routes, mirroring dyna2rad's *SECTION_SOLID branch (convertprops.cxx:
    385-395, which routes on the part's MATERIAL keyword — MAT_138/169/240 →
    /PROP/CONNECT — and never looks at ELFORM) plus the ELFORM the task
    actually encodes:
      * ELFORM ±19/20/±21/22 — the section IS cohesive whatever material
        sits on it (a non-cohesive material there is warned as ERROR 3047
        by the pairing check).
      * any part on the section maps to a SOLID_COHESIVE law (116/117/169) —
        those laws are TYPE43-only, so an ordinary ELFORM 1 ARUP-adhesive
        brick section must still become TYPE43 (d2r parity).
    MAT_252 (LAW120) deliberately does NOT trigger the material route: d2r
    sends it to the plain solid property (LAW120 is SOLID_ALL and legal on
    both), so only an explicit cohesive ELFORM puts it on TYPE43.
    """
    out = {secid for secid, sec in state.sec_solids.items()
           if sec.elform in _COHESIVE_ELFORMS}
    cohesive_mids = (set(state.mat_cohesive_mixed_mode)
                     | set(state.mat_cohesive_mm_epr)
                     | set(state.mat_arup_adhesive))
    if cohesive_mids:
        solid_pids = {e.pid for e in state.solid_elems}
        for pid, part in state.parts.items():
            if part.mid in cohesive_mids and pid in solid_pids:
                out.add(part.secid if part.secid > 0 else pid)
    return out


def _emit_prop_type43(prop_id: int, title: str,
                      true_thickness: float) -> List[str]:
    """/PROP/TYPE43 (CONNECT), audited against hm_cfg_files
    radioss140/PROP/prop_p43_connect.cfg — the newest FORMAT block, i.e. what
    a /BEGIN 2022 deck reads with: title, then ONE data card
    ``Ismstr(10) blank(70) True_thickness(81-100)``.

    Ismstr is written 1 explicitly: the starter collapses every other value
    to 1 or 4 anyway (hm_read_prop43.F:121-124 — 0/2/3 → 1, 10 → 4, and a
    blank falls to /DEF_SOLID first), and 1 (small strain from t=0) is what
    dyna2rad sets for its MAT_138/MAT_240 CONNECT props; k2rad emits no
    /DEF_SOLID, so this pins the resolved value instead of leaving it to a
    default chain. True_thickness 0 = use the element's geometric height in
    the strain measure; a *SECTION_SOLID_MISC COHTHK lands here (the exact
    Radioss analogue of its supersede-*MAT_240-THICK rule). The property has
    no other input: 4 mid-plane Gauss points, local t-axis from face 1-2-3-4
    to face 5-6-7-8 (identical to the LS-DYNA cohesive convention, so
    *ELEMENT_SOLID connectivity passes through unpermuted), zero element
    height legal (the element computes no time step of its own — nodal
    time step governs).
    """
    return [
        f"/PROP/TYPE43/{prop_id}",
        title,
        "#   Ismstr                                                                        True_thickness",
        f"{_i(1)}{' ' * 70}{_f(true_thickness)}",
        HDR,
    ]


def _warn_type43_pairings(state: ConversionState, secid: int,
                          sec: SectionSolid) -> None:
    """Name every starter refusal a cohesive section conversion sets up.

    One warning per (section, defect class), naming all the offending part
    ids — a realistic adhesive model shares one cohesive section across many
    parts, and ``state.warn`` does not deduplicate, so per-part emission
    floods the log with near-identical lines (the aggregation rule the
    element-free-*PART path and _assign_ortho_props already follow)."""
    parts_here = [(pid, p) for pid, p in sorted(state.parts.items())
                  if (p.secid if p.secid > 0 else pid) == secid]
    offclass: Dict[int, List[int]] = {}
    offclass_mids: Dict[int, Set[int]] = {}
    arup_pids: List[int] = []
    law120_pids: List[int] = []
    for pid, part in parts_here:
        law = _target_mat_law(state, part.mid)
        if law is None:
            continue    # no /MAT at all — the dangling-material path warns
        if law not in _TYPE43_LAWS:
            offclass.setdefault(law, []).append(pid)
            offclass_mids.setdefault(law, set()).add(part.mid)
        if law == 169 and sec.elform in _COHESIVE_ELFORMS:
            arup_pids.append(pid)
        if law == 120:
            law120_pids.append(pid)
    for law, pids in sorted(offclass.items()):
        mids = sorted(offclass_mids[law])
        state.warn(
            f"*SECTION_SOLID {secid} converts to /PROP/TYPE43 (cohesive) "
            f"but part(s) {pids} pair it with /MAT/LAW{law} (mid(s) "
            f"{mids}), which is not in TYPE43's accepted classes "
            "(SOLID_COHESIVE LAW59/83/116/117/169, SOLID_ALL LAW13/120, "
            "SOLID_BRICK_ISOTROPIC LAW77/88) — the starter refuses the "
            "pair with ERROR 3047 + ERROR 658 "
            "(check_mat_elem_prop_compatibility.F:228-232). Put a cohesive "
            "material on the part(s) or move them off the cohesive section.")
    if arup_pids:
        state.warn(
            f"*SECTION_SOLID {secid} (part(s) {arup_pids}): /MAT/LAW169 "
            "always uses VOLUME density — it is missing from the sini43.F "
            "area-mass flag list (MLW 59/83/116/117 only) and has no "
            "Imass field — so a ZERO-HEIGHT cohesive element gets zero "
            "nodal mass from these parts. Model the ARUP adhesive with "
            "finite bondline height, or use MAT_138/MAT_240 (LAW117/116, "
            "which default to area mass) for zero-thickness meshes.")
    if law120_pids:
        state.warn(
            f"*SECTION_SOLID {secid} (part(s) {law120_pids}): /MAT/LAW120 "
            "on /PROP/TYPE43 is legal (SOLID_ALL), but LAW120's own Thick "
            "field is unset and defaults to 1.0 LENGTH UNIT in the "
            "cohesive strain measure (hm_read_mat120.F:170-176; LS-DYNA "
            "pairs MAT_252 with *MAT_ADD_COHESIVE for this, which k2rad "
            "does not convert). Verify the traction-separation scaling "
            "against a coupon before trusting the bondline response.")
    if sec.elform in (20, 22):
        state.warn(
            f"*SECTION_SOLID {secid}: ELFORM={sec.elform} is the cohesive "
            "form WITH SHELL OFFSETS — LS-DYNA generates moments on the "
            "connected shells from the offset between the cohesive mid-plane "
            "and the shell reference surfaces; /PROP/TYPE43 has no offset "
            "mechanism, so those moments are NOT reproduced (forces act at "
            "the nodes). Expect softer peel response on shell-bonded joints.")


def _emit_prop_solid(prop_id: int, title: str, isolid: int, iale: int,
                     itetra10: int, istrain: int,
                     hcoef: Optional[float] = None,
                     ismstr: int = 0) -> List[str]:
    """/PROP/SOLID (TYPE14), byte-identical to the historical inline block.
    *hcoef* None → card-2 field 3 (h) stays 0 (Radioss default 1.1/0.05/0.10
    for qa/qb/h); otherwise the hourglass coefficient. *ismstr* 0 (default,
    unchanged output) leaves the strain formulation to the starter; 10 =
    total-strain large deformation — required by /XREF reference-geometry
    parts (starter ERROR 2013 rejects /XREF on a fully-integrated solid at
    small strain). Shared by the per-section and per-part paths so the
    100-column layout cannot drift."""
    h_field = _f(hcoef if hcoef is not None else 0.0)
    return [
        f"/PROP/SOLID/{prop_id}",
        title,
        "#   Isolid    Ismstr      Iale     Icpre  Itetra10     Inpts   Itetra4    Iframe                  Dn",
        f"{_i(isolid)}{_i(ismstr)}{_i(iale)}         0{_i(itetra10)}         0         0         0",
        "#                q_a                 q_b                   h            LAMBDA_V                MU_V",
        f"{_f(0.0)}{_f(0.0)}{h_field}{_f(0.0)}{_f(0.0)}",
        "#             dt_min   istrain      IHKT",
        f"                   0{_i(istrain)}         0",
        HDR,
    ]


def _shell_istrain_flag(state: ConversionState) -> int:
    """The ``Istrain`` cell of /PROP/SHELL card 3 (cols 11-20, FORMAT
    radioss2020 — the block /BEGIN 2022 selects).

    Two independent reasons to switch it on:

    * ``*DATABASE_EXTENT_BINARY`` STRFLG>0 asks for strain-tensor output, and
      OpenRadioss only computes/stores element strains when Istrain/=0 — with
      Istrain=0 the /ANIM/.../TENS/STRAIN channels come out empty.
    * ``*INITIAL_STRAIN_SHELL`` wants a correctly SIZED strain buffer.
      ``elbuf_ini.F:1584`` allocates ``GBUF%G_STRA = 8`` only for
      ``ISTRA > 0 .OR. IFAIL > 0 .OR. ISMSTR == 11 .OR. ...``, and the
      /PROP/SHELL property tag leaves ``PTAG%G_STRA`` at 0 (only the truss prop
      sets it) — yet ``cbainit3.F:549`` calls the ingest whenever
      ``ITHKSHEL == 2 .AND. G_STRPG > G_STRA``, and ``cstraini4.F`` writes its
      membrane average into that buffer. LS-DYNA's own manual requires
      STRFLG=1 alongside *INITIAL_STRAIN_SHELL (Vol I R17 p.3119), so a
      well-formed source deck already sets it; this OR covers one that forgot.

      Honest scope of the claim: this is defence-in-depth, NOT a measured
      necessity. Twin decks on this build — the branch's own emitted starter
      with Istrain hand-set back to 0, Ishell 12 / 24 / 1, with and without a
      /FAIL — read the initial strain back IDENTICALLY (/TH/SHEL E1 = 0.01,
      K1 = 0.02 either way). The gate that DOES test ISTRAIN, csigini.F:165 /
      scigini4.F:168, is not the path these formulations take: cbainit3.F:549
      reaches cstraini4.F, which takes ISTRAIN as an argument and never looks
      at it. So the flag buys a properly sized buffer and the strain output
      such a user implicitly wants, not a working-versus-inert difference.

    Istrain=1 costs a per-element strain buffer and changes no physics on its
    own, so switching it on is inert for everything except the two consumers
    above.
    """
    ext = state.db_extent_binary
    if ext and ext.strflg > 0:
        return 1
    return 1 if state.ini_strain_shells else 0


def _emit_prop_shell(prop_id: int, title: str, ishell: int, nip: int,
                     istrain: int, thick: float,
                     hcoef: Optional[float] = None) -> List[str]:
    """/PROP/SHELL (TYPE1), byte-identical to the historical inline block.
    *hcoef* None → Hm/Hf/Hr stay 0 (Radioss default 0.01); otherwise the
    (clamped) hourglass coefficient is written into all three membrane/bending/
    rotation slots. Shared by the per-section and per-part paths."""
    if hcoef is not None:
        hg_card = f"{_f(hcoef)}{_f(hcoef)}{_f(hcoef)}{_f(0.0)}{_f(0.0)}"
    else:
        hg_card = f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}"
    return [
        f"/PROP/SHELL/{prop_id}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill",
        f"{_i(ishell)}         0         0         0",
        "#                 hm                  hf                  hr                  dm                  dn",
        hg_card,
        "#        N   Istrain               Thick              Ashear              Ithick     Iplas",
        f"{_i(nip)}{_i(istrain)}{_f(thick)}                   0                   0         0",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Starter: properties
# ─────────────────────────────────────────────────────────────────────────────

def _make_properties(state: ConversionState) -> List[str]:
    lines = ["#-  PROPERTIES:", HDR]

    # LS-DYNA *DATABASE_EXTENT_BINARY strflg>0 requests strain-tensor output (and
    # its tens digit selects the plastic-strain tensor — the user's strflg=11
    # means "strain + plastic strain"). OpenRadioss only computes/stores element
    # strains for post-processing when Istrain=1 in the property; with Istrain=0
    # the engine's /ANIM/.../TENS/STRAIN — and, for solids, /ANIM/ELEM/EPSP — come
    # out empty. So enable Istrain whenever the deck asks for strain output.
    # (The plastic-strain channels /ANIM/ELEM/EPSP + /ANIM/SHELL/EPSP are always
    # emitted in the engine, see _make_engine_output.)
    istrain = _shell_istrain_flag(state)

    missing_shells = set()
    missing_solids = set()
    missing_beams = set()

    part_secids = {p.pid: p.secid if p.secid > 0 else p.pid for p in state.parts.values()}

    # Sections whose EVERY part is served by a dedicated per-part /PROP — a
    # composite/orthotropic prop (MAT_002/032/037/054/055, *PART_COMPOSITE), a
    # LAW128 (MAT_103) orthotropic prop or a per-part hourglass prop — reference
    # that instead, so the shared isotropic section prop would be emitted unused.
    # Skip it in that case (a section with even one plain part keeps it, and the
    # split parts additionally get their own props). Mirrors the ortho split.
    split_pids = (set(state.composite_prop_ids) | set(state.ortho_prop_ids)
                  | set(state.hourglass_prop_ids) | set(state.fabric_prop_ids)
                  | set(state.seatbelt_prop_ids))
    ortho_only_secids: Set[int] = set()
    if split_pids:
        parts_by_secid: Dict[int, List[int]] = defaultdict(list)
        for pid, sid in part_secids.items():
            parts_by_secid[sid].append(pid)
        ortho_only_secids = {
            sid for sid, pids in parts_by_secid.items()
            if pids and all(p in split_pids for p in pids)}

    # Sections whose parts carry 10-node tets need the quadratic Itetra10 flag set
    # in /PROP/SOLID so /TETRA10 elements use the quadratic formulation.
    tet10_secids: Set[int] = set()
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            sid = part_secids.get(e.pid)
            if sid:
                tet10_secids.add(sid)

    # Solid sections serving a /XREF reference-geometry part are emitted with
    # Ismstr=10 (total strain): the starter rejects /XREF on a fully-integrated
    # solid at small strain (ERROR 2013 — it requires 1 integration point OR
    # Ismstr>=10, and k2rad's ELFORM-derived Isolid is the 8-point 17). Warn
    # when the section is shared with non-/XREF parts, whose formulation
    # changes along.
    solid_elem_pids = {e.pid for e in state.solid_elems}
    xref_solid_pids = {pid for pid in state.xref_part_ids
                       if pid in solid_elem_pids}
    xref_secids: Set[int] = {part_secids[pid] for pid in xref_solid_pids
                             if pid in part_secids}
    if xref_secids:
        dragged = sorted(pid for pid, sid in part_secids.items()
                         if sid in xref_secids and pid in solid_elem_pids
                         and pid not in xref_solid_pids)
        if dragged:
            state.warn(
                "/XREF reference geometry: solid part(s) "
                f"{dragged} share a *SECTION_SOLID with a /XREF part, so "
                "their shared /PROP/SOLID also switches to Ismstr=10 "
                "(total-strain formulation). Give the /XREF parts their own "
                "*SECTION_SOLID to keep the others at the default.")
    # ... and so are sections serving a /MAT/LAW95 (MAT_077_H N=0) part: the
    # starter force-promotes any LAW95 element group at another Ismstr anyway
    # ("ISMSTR IS CHANGED TO 10 SINCE LAW 95 IS ONLY COMPATIBLE WITH
    # ISMSTR=10", WARNING 1200, sgrtails.F). Pre-setting it on the property
    # emits the identical LAW95 formulation with a warning-clean deck — but
    # the native promotion is per ELEMENT GROUP, so a non-LAW95 sibling on a
    # shared section would natively keep its default while the pre-set prop
    # switches it to total strain too: warned, mirroring the /XREF drag.
    law95_pids = {pid for pid, part in state.parts.items()
                  if part.mid in state.mat_hyper_rubber
                  and state.mat_hyper_rubber[part.mid].n == 0}
    law95_secids: Set[int] = {
        part_secids[pid] for pid in law95_pids
        if pid in solid_elem_pids and pid in part_secids}
    if law95_secids:
        dragged95 = sorted(pid for pid, sid in part_secids.items()
                           if sid in law95_secids and pid in solid_elem_pids
                           and pid not in law95_pids
                           and pid not in xref_solid_pids)
        if dragged95:
            state.warn(
                "/MAT/LAW95 (*MAT_HYPERELASTIC_RUBBER N=0): solid part(s) "
                f"{dragged95} share a *SECTION_SOLID with a LAW95 part, so "
                "their shared /PROP/SOLID also switches to Ismstr=10 "
                "(total-strain formulation); the native starter promotes "
                "only the LAW95 element groups (WARNING 1200) and would "
                "leave these parts at the default. Give the LAW95 parts "
                "their own *SECTION_SOLID to keep the others unchanged.")
    # ... and sections serving a /MAT/LAW90 (*MAT_LOW_DENSITY_VISCOUS_FOAM)
    # part: dyna2rad pins Ismstr=10 on the generated /PROP/TYPE14 for every
    # MAT_073 *SECTION_SOLID unconditionally (convertprops.cxx CP:484-495 —
    # the same rule that moves DAMP onto the property), LAW90 being a
    # total-strain law whose deep-crush robustness needs it. Same drag
    # caveat as above for a shared section.
    law90_pids = {pid for pid, part in state.parts.items()
                  if part.mid in state.mat_low_density_viscous_foam}
    law90_secids: Set[int] = {
        part_secids[pid] for pid in law90_pids
        if pid in solid_elem_pids and pid in part_secids}
    if law90_secids:
        dragged90 = sorted(pid for pid, sid in part_secids.items()
                           if sid in law90_secids and pid in solid_elem_pids
                           and pid not in law90_pids
                           and pid not in xref_solid_pids
                           and pid not in law95_pids)
        if dragged90:
            state.warn(
                "/MAT/LAW90 (*MAT_LOW_DENSITY_VISCOUS_FOAM): solid part(s) "
                f"{dragged90} share a *SECTION_SOLID with a LAW90 foam "
                "part, so their shared /PROP/SOLID also switches to "
                "Ismstr=10 (total-strain formulation — dyna2rad pins it "
                "for every MAT_073 section, CP:484-495). Give the foam "
                "parts their own *SECTION_SOLID to keep the others at "
                "the default.")
    ismstr10_secids: Set[int] = xref_secids | law95_secids | law90_secids

    # Sections serving a /MAT/LAW115 (*MAT_DESHPANDE_FLECK_FOAM) part leave
    # the full-integration hex Isolid=17 for 24 (HEPH): LAW115 at Isolid 17
    # is engine-fatal — the solid time step collapses below DTMIN at cycle 0
    # and the run "completes" after 1 cycle with NORMAL TERMINATION
    # (measured; the starter only answers WARNING 1905). Isolid=24 is also
    # dyna2rad's default hex formulation, and the identical deck runs to
    # completion there with 0 warnings. Announced per material in
    # _resolve_mat_deshpande_fleck; only the measured-fatal 17 is remapped
    # (tet formulations keep their ELFORM-derived value, warned there).
    law115_pids = {pid for pid, part in state.parts.items()
                   if part.mid in state.mat_deshpande_fleck}
    law115_secids: Set[int] = {
        part_secids[pid] for pid in law115_pids
        if pid in solid_elem_pids and pid in part_secids}
    if law115_secids:
        dragged115 = sorted(pid for pid, sid in part_secids.items()
                            if sid in law115_secids
                            and pid in solid_elem_pids
                            and pid not in law115_pids)
        if dragged115:
            state.warn(
                "/MAT/LAW115 (*MAT_DESHPANDE_FLECK_FOAM): solid part(s) "
                f"{dragged115} share a *SECTION_SOLID with a LAW115 foam "
                "part, so their shared /PROP/SOLID also switches from "
                "Isolid=17 to Isolid=24 (HEPH — LAW115 on 17 collapses "
                "the engine time step at cycle 0). Give the foam parts "
                "their own *SECTION_SOLID to keep the others at the "
                "full-integration default.")

    # Spotweld beam parts become /SPRING connectors (their /PROP/TYPE13 is
    # emitted by _make_spotweld_beam_connectors); their beams must not force an
    # auto /PROP/BEAM, and a *SECTION_BEAM used ONLY by spotweld parts is not
    # emitted (its ELFORM-9 card has no /PROP/BEAM meaning).
    # Beam parts that become /SPRING connectors instead: the MAT_100 spotweld
    # beams (/PROP/TYPE13) and the *SECTION_BEAM ELFORM=6 discrete beams
    # (/PROP/TYPE8 or /PROP/TYPE13). Their beams must not force an auto
    # /PROP/BEAM, and a *SECTION_BEAM used ONLY by such parts is not emitted —
    # neither the ELFORM-9 spotweld card nor the ELFORM-6 discrete-beam card
    # states a cross-section, so a /PROP/BEAM from either is ERROR 314-317.
    spotweld_pids = _spotweld_beam_pids(state)
    # ... and the *MAT_MUSCLE truss parts, which become /PROP/TYPE46 springs:
    # their ELFORM-3 *SECTION_BEAM states only an AREA, which the muscle
    # property consumes itself, so no /PROP/BEAM may be auto-created for them.
    connector_beam_pids = (spotweld_pids | _discrete_beam_pids(state)
                           | _muscle_beam_pids(state))
    spotweld_only_secids: Set[int] = set()
    if connector_beam_pids:
        other_beam_secids = {part_secids.get(e.pid) for e in state.beam_elems
                             if e.pid not in connector_beam_pids}
        spotweld_only_secids = {part_secids[pid] for pid in connector_beam_pids
                                if pid in part_secids} - other_beam_secids

    for e in state.shell_elems:
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_shells:
            missing_shells.add(secid)
    for e in state.solid_elems:
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_solids:
            missing_solids.add(secid)
    for e in state.beam_elems:
        if e.pid in connector_beam_pids:
            continue
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_beams:
            missing_beams.add(secid)
    # A thick-shell *PART with no *SECTION_TSHELL still needs a property: its
    # /BRICK on a /PROP/SOLID would be starter ERROR 3047 the moment the
    # material is orthotropic, and would carry no through-thickness layers
    # either way. A part repointed at its own layup /PROP/TYPE22 does not.
    missing_tshells: Set[int] = set()
    for e in state.tshell_elems:
        if e.pid in state.tshell_prop_ids:
            continue
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_tshells:
            missing_tshells.add(secid)

    for ms in missing_shells:
        state.sec_shells[ms] = _auto_section_shell(ms)
    for ms in missing_solids:
        state.sec_solids[ms] = _auto_section_solid(ms)
    for ms in missing_beams:
        # ELFORM 2, never 3: a section the deck never DEFINES states no
        # formulation, so it cannot be known to be a truss — and because it is
        # absent from state.sec_beams, common._truss_secids does not hold it and
        # its parts are not in _truss_pids either, so their elements go to
        # /BEAM and this placeholder /PROP/BEAM is what the missing-section
        # warning below is written against. (The truss batch's audit listed
        # "skip this synthesis for a truss part" as an arm to grow; it is
        # vacuous by construction, and stated here rather than left unexplained.)
        state.sec_beams[ms] = SectionBeam(ms, f"AutoPropBeam_{ms}", 2)
    if missing_tshells:
        for ms in sorted(missing_tshells):
            state.sec_tshells[ms] = _auto_section_tshell(ms)
        state.warn(
            "*ELEMENT_TSHELL element(s) reference section id(s) "
            + ", ".join(str(s) for s in sorted(missing_tshells))
            + " that no *SECTION_TSHELL card defines, so a PLACEHOLDER "
            "thick-shell property was created for each (ELFORM 1 → Isolid=15, "
            "NIP 2 — LS-DYNA's own defaults). Without it the /PART would point "
            "at a property id nothing emits, which is starter ERROR 178 and "
            "kills the whole run. Add the *SECTION_TSHELL if the deck was "
            "meant to have one.")

    # A *PART with NO elements is invisible to every loop above (they all walk
    # the elements), but it still gets a /PART card — pointing at a property id
    # nothing emits. That is starter ERROR 178. Give it the same placeholder
    # shell property, and say so: an empty part is usually either an
    # *INTEGRATION_SHELL material carrier or a leftover the user meant to
    # delete, and both are worth naming. Runs AFTER the three loops above so a
    # section they just auto-created counts as defined.
    free_pids = sorted(_element_free_part_ids(state, part_secids))
    if free_pids:
        for pid in free_pids:
            secid = part_secids[pid]
            state.sec_shells[secid] = _auto_section_shell(secid)
        state.warn(
            "*PART record(s) " + ", ".join(str(p) for p in free_pids)
            + " hold no elements and reference no *SECTION. Each keeps its "
            "/PART (id, title, material and subset stay addressable — a "
            "*SET_PART member, a /GRNOD/PART gravity scope or an "
            "*INTEGRATION_SHELL PID_i material carrier all reference a part by "
            "id, with or without mesh) and is given a PLACEHOLDER "
            "/PROP/SHELL, because a /PART whose property does not exist is "
            "starter ERROR 178 and kills the whole run. The placeholder has no "
            "elements to act on, so it changes no physics. If the part was not "
            "meant to be empty, its elements are missing — check for an "
            "*INCLUDE that did not resolve or a PID typo.")

    _warn_shell_formulation_choice(state)
    for sec in sorted(state.sec_shells.values(), key=lambda s: s.secid):
        if sec.secid in ortho_only_secids:
            continue
        ishell = _elform_to_ishell(sec.elform, state.is_implicit,
                                  state.options.shell_default_ishell)
        nip = max(2, sec.nip)
        # Shared section prop carries the global *CONTROL_HOURGLASS coefficient
        # (its base); parts with a different *HOURGLASS are split out below.
        hm, _ = _shell_hg_values(state, sec, None)
        lines += _emit_prop_shell(sec.secid, sec.title or f"PROP_{sec.secid}",
                                  ishell, nip, istrain, sec.t1, hcoef=hm)
    cohesive_secids = _cohesive_solid_secids(state)
    for sec in sorted(state.sec_solids.values(), key=lambda s: s.secid):
        if sec.secid in ortho_only_secids:
            continue
        # Cohesive route (ELFORM ±19/20/±21/22, or any part pairing the
        # section with a SOLID_COHESIVE law): /PROP/TYPE43 under the SECID
        # verbatim, exactly where /PROP/SOLID would sit, so no /PART repoint.
        # MUST come before _elform_to_isolid — ELFORM 19/20 has no entry
        # there and would silently fall to the structural-hex default 17,
        # i.e. a zero-thickness cohesive on a full-integration brick prop
        # (ERROR 245 zero volume at best, garbage stiffness at worst).
        # /INIBRI note: _effective_solid_isolid still reports the ELFORM
        # default for these sections — an *INITIAL_STRESS_SOLID on a cohesive
        # part is not supported (TYPE43 has 4 mid-plane points, no Radioss
        # /INIBRI layout matches it).
        if sec.secid in cohesive_secids:
            if sec.elform not in _COHESIVE_ELFORMS:
                mids = sorted({p.mid for pid, p in state.parts.items()
                               if (p.secid if p.secid > 0 else pid)
                               == sec.secid
                               and _target_mat_law(state, p.mid)
                               in _SOLID_COHESIVE_LAWS})
                state.warn(
                    f"*SECTION_SOLID {sec.secid}: ELFORM={sec.elform} is not "
                    "a cohesive formulation, but the section is used by "
                    f"cohesive-law material(s) {mids} "
                    "(LAW116/117/169 are SOLID_COHESIVE — a plain "
                    "/PROP/SOLID pairing is starter ERROR 3047), so it is "
                    "routed to /PROP/TYPE43 like dyna2rad's material-based "
                    "*SECTION_SOLID → /PROP/CONNECT rule. *MAT_ARUP_ADHESIVE "
                    "on ELFORM 1/2/15 bricks is the standard LS-DYNA usage "
                    "this covers; verify any NON-cohesive part sharing the "
                    "section (warned separately if present).")
            _warn_type43_pairings(state, sec.secid, sec)
            lines += _emit_prop_type43(sec.secid,
                                       sec.title or f"PROP_{sec.secid}",
                                       sec.cohthk)
            continue
        # ALE/Euler elements need an ALE-compatible solid formulation; the
        # full-integration Lagrangian Isolid 17 is rejected (ERROR 131/608
        # "INCOMPATIBLE ELEMENT TYPE WITH ALE/EULER FRAMEWORK"). Isolid 0 =
        # the default, which resolves to the co-located ALE brick (the value
        # used by the reference Drop_Container FSI deck).
        isolid = 0 if sec.iale else _elform_to_isolid(sec.elform)
        # /PROP/SOLID card 1 (cfg radioss2022): Isolid Ismstr Iale Icpre Itetra10
        # Inpts Itetra4 Iframe Dn — note the Iale column at 21-30 (the 2022 PDF
        # p.1738 omits it; writing the PDF's 8-field layout shifts Itetra10 into
        # Icpre and silently drops it). Itetra10=1000 = quadratic /TETRA10 with
        # 4 integration points, for parts that have 10-node tets; 0 otherwise
        # (ignored by /TETRA4/brick). Do NOT use Itetra10=2 (same formulation
        # plus a /TETRA4-equivalent time step): its internal mid-side-node
        # treatment makes the starter reject any deck where kinematic
        # conditions (/RBODY, /BCS, CNRB...) touch tet10 nodes — ERROR 1216
        # "CONFLICT OF TETRA10&ITET=2 WITH KINEMATIC CONDITIONS" — and the
        # time-step benefit only matters for explicit runs anyway.
        itetra10 = 1000 if sec.secid in tet10_secids else 0
        # Shared section prop carries the global *CONTROL_HOURGLASS (its base):
        # h from QH and Isolid from IHQ (1/5/24). Parts with a *HOURGLASS that
        # resolves differently are split into their own /PROP below. The gate
        # (tetra / ALE / cohesive) returns (None, None) → prop unchanged.
        h, iso = _solid_hg_values(state, sec, None)
        if iso is not None:
            isolid = iso
        # LAW115 sections: remap the (engine-fatal) full-integration hex 17
        # to HEPH 24 — see the law115_secids comment above. Applied last so
        # a *HOURGLASS-resolved formulation is respected; only the measured
        # 17 is touched.
        if sec.secid in law115_secids and isolid == 17:
            isolid = 24
        if sec.secid in ismstr10_secids:
            # Recorded at the write line for the /PRELOAD writer: a preloaded
            # element group at Ismstr 10/11/12 is downgraded to 4/1/2 by
            # sgrtails.F:1387-1412 (WARNING 1775), i.e. the total-strain
            # formulation these parts were given is taken away again.
            state.ismstr10_solid_secids.add(sec.secid)
        lines += _emit_prop_solid(sec.secid, sec.title or f"PROP_{sec.secid}",
                                  isolid, sec.iale, itetra10, istrain, hcoef=h,
                                  ismstr=10 if sec.secid in ismstr10_secids
                                  else 0)
    # Collected, not re-derived: the check below must see exactly the sections
    # that really carry a /PROP/BEAM, so that a section routed to some other
    # beam property stays out of it without the check having to know about that
    # route (see _warn_beam_type3_material).
    type3_secids: Set[int] = set()
    # ... and the same bookkeeping for the sections that really wrote a
    # /PROP/TYPE2. A truss section refused by _truss_section_is_emittable never
    # enters it, so _warn_truss_material cannot warn about a property the deck
    # does not carry.
    truss_secids: Set[int] = set()
    truss_pids = _truss_pids(state)
    emitted_truss_secs: List[SectionBeam] = []
    for sec in sorted(state.sec_beams.values(), key=lambda s: s.secid):
        if sec.secid in spotweld_only_secids:
            continue
        if sec.elform == 3:
            # ELFORM=3 is a TRUSS: /PROP/TYPE2, which reads AREA and GAP and
            # nothing else. It never reaches _constants_from_thicknesses (an
            # ELFORM 3 card states no thicknesses) and never joins
            # type3_secids: a truss carries a DIFFERENT material gate
            # (PROP_TRUSS, six laws) from /PROP/BEAM's PROP_BEAM.
            # The test is `sec.elform`, NOT membership of _truss_secids(state):
            # that set is BUILT from this same elform over this same dict, so
            # the second half was a no-op, and the property has to be written
            # from the SECTION even when no *PART reaches it (an unreferenced
            # /PROP is legal; a /PART pointing at a missing one is ERROR 178).
            # A section whose every part is claimed by a connector path is
            # already gone via spotweld_only_secids above.
            if _truss_section_is_emittable(state, sec):
                truss_secids.add(sec.secid)
                emitted_truss_secs.append(sec)
                lines += _emit_prop_truss(sec)
            continue
        # A section that bound a usable *INTEGRATION_BEAM rule becomes the
        # INTEGRATED beam property instead of the resultant one; the rule hangs
        # off the SECTION in LS-DYNA, so every part on it switches together.
        # This `continue` sits ABOVE the type3_secids bookkeeping on purpose:
        # a section promoted to /PROP/TYPE18 must stay out of the TYPE3
        # material check, which is exactly the seam that check was built to
        # survive (it collects rather than re-derives, see
        # _warn_beam_type3_material).
        int_prop = state.int_beam_props.get(sec.secid)
        if int_prop is not None:
            lines += _emit_prop_int_beam(sec, int_prop)
            continue
        if not (sec.area or sec.iyy or sec.izz or sec.ixx):
            # ELFORM 0/1/4/5/11 state the section as card-2 THICKNESSES and
            # carry no resultants at all, so leaving the four constants at zero
            # is not a soft beam — it is a deck the starter refuses outright
            # (ERROR 314/315/316/317). The thicknesses fully determine a
            # prismatic section, so derive it and say so, rather than emitting
            # a property that cannot start.
            derived = _constants_from_thicknesses(sec.cst, sec.ts1, sec.tt1)
            if derived is not None:
                sec.area, sec.iyy, sec.izz, sec.ixx = derived
                state.warn(
                    f"*SECTION_BEAM {sec.secid}: ELFORM={sec.elform} states "
                    "the cross-section as card-2 THICKNESSES, which /PROP/BEAM "
                    "(TYPE3) has no column for, so k2rad DERIVES the four "
                    "resultants from them: "
                    + (f"CST=1 tubular, outer diameter TS1={sec.ts1:g} and "
                       f"inner TT1={sec.tt1:g}" if sec.cst == 1 else
                       f"a solid TS1 x TT1 = {sec.ts1:g} x {sec.tt1:g} "
                       "rectangle")
                    + f" gives Area={sec.area:g}, Iyy={sec.iyy:g}, "
                    f"Izz={sec.izz:g}, Ixx={sec.ixx:g} (Ixx is the POLAR "
                    "moment, equal to the torsion constant only for a round "
                    "section). Any node-2 taper is dropped and the beam is "
                    "elastic through the section. State it as an "
                    "*INTEGRATION_BEAM rule on a negative QR/IRID to keep "
                    "through-section plasticity, or numerically on an "
                    "ELFORM=2 section to control J.")
            elif sec.elform == 6:
                state.warn(
                    f"*SECTION_BEAM {sec.secid}: ELFORM=6 is a DISCRETE beam — "
                    "its card 2f states a lumped VOL/INER and a CID, never a "
                    "cross-section — but a *PART on it is NOT claimed by the "
                    "discrete-beam connector path (it carries shell or solid "
                    "elements, or shares the section with an ordinary beam "
                    "part). Its /PROP/BEAM is therefore written with "
                    "Area=Iyy=Izz=Ixx=0 and the starter REFUSES it (ERROR "
                    "314-317). Give the discrete beams their own "
                    "*SECTION_BEAM, and a discrete-beam material "
                    "(*MAT_066/067/068/071/074/119/121/196) so k2rad can turn "
                    "them into a 6-DOF /SPRING.")
            else:
                state.warn(
                    (f"*SECTION_BEAM {sec.secid} is referenced by a beam *PART "
                     "but the deck never defines it, so a PLACEHOLDER"
                     if sec.secid in missing_beams else
                     f"*SECTION_BEAM {sec.secid}: ELFORM={sec.elform} carries "
                     "no cross-section area or inertia that k2rad can read, so "
                     "its")
                    + " /PROP/BEAM is written with Area=Iyy=Izz=Ixx=0, which "
                    "the starter REFUSES: hm_read_prop03.F:151-182 raises "
                    "ERROR 314 (AREA), 315 (IYY), 316 (IZZ) and 317 (IXX) on "
                    "every non-positive value, so the deck will not start. "
                    "State the section numerically (ELFORM=2 with A/ISS/ITT/J) "
                    "or, for a geometrically integrated beam, add an "
                    "*INTEGRATION_BEAM rule and reference it from a negative "
                    "QR/IRID on card 1 field 4.")
        type3_secids.add(sec.secid)
        lines += _emit_prop_beam(sec)
    _warn_beam_type3_material(state, part_secids, connector_beam_pids,
                              type3_secids)
    _warn_truss_section_cells(state, emitted_truss_secs)
    _warn_truss_material(state, part_secids, truss_pids, truss_secids)
    # Thick shells: /PROP/TYPE20 (iso) / TYPE21 (ortho) / TYPE22 (composite),
    # under the SECID verbatim, plus one synthesized TYPE22 per per-part layup.
    # Local import: writer/tshell.py reuses the #90 AOPT machinery out of
    # writer/composites.py, which imports THIS module at load time, so a
    # top-level import here would close the cycle (same rule as
    # _emit_prop_type6, which composites.py imports locally for the same
    # reason, in the opposite direction).
    from .tshell import _make_tshell_properties
    lines += _make_tshell_properties(state, istrain)
    # SPH particles: /PROP/SPH (TYPE34), under the SECID verbatim unless the
    # SECID is shared with another element family. Its payload — the particle
    # mass Mp and the smoothing length h — was decided in the _resolve_sph
    # prepass, together with whether each /SPHCEL row states its own mass, so
    # the two emitters cannot disagree about where a particle's mass comes from.
    from .sph import _make_sph_properties
    lines += _make_sph_properties(state)
    # Orthotropic properties for LAW128 (MAT_103) parts (the section auto-create
    # above has already populated any missing section this reads).
    lines += _emit_ortho_props(state, istrain)
    # Per-part hourglass properties (*HOURGLASS / per-part *CONTROL_HOURGLASS
    # override), each a copy of its section prop with part-specific h/Isolid.
    lines += _emit_hourglass_props(state, istrain)
    return lines


#: How deep a chain of ``*SET_..._ADD`` unions is followed. LS-DYNA states NO
#: nesting rule at all — the ``*SET`` chapter is silent on whether a member of
#: an ``_ADD`` set may itself be an ``_ADD`` set, and gives no depth limit —
#: so any cap is a CONVERTER policy, not a manual rule, and is warned rather
#: than applied silently. dyna2rad's own set converter recurses without a limit
#: (``convertsets.cxx:1248-1277``, memoised through ``convertedGroups`` /
#: ``unconvertibleGroups``); 16 is far past any hand-authored deck and keeps a
#: pathological input from costing unbounded work.
_SET_ADD_MAX_DEPTH = 16


def _segment_key(nodes):
    """Canonical identity of one segment, for de-duplicating a segment union.

    Rotation-invariant, orientation-PRESERVING: the smallest of the corner
    list's cyclic rotations. Two rows that name the same corners in the same
    cyclic order ARE one segment (a quad ``1 2 3 4`` and ``2 3 4 1`` have the
    same normal and the same area), so the union must keep one; a REVERSED
    row is the opposite face normal and is deliberately a different key —
    dropping it would silently delete a load direction.

    This matters only for segments. ``/GRNOD``, ``/GRSHEL``, ``/GRBRIC``,
    ``/GRBEAM``, ``/GRSPRI`` and ``/GRPART`` all de-duplicate inside the
    starter (``sysfus.F:468-479`` for nodes, ``nintrr.F:814-828`` "WITH REMOVAL
    OF DUPLICATE NOS" for elements), but ``/SURF/SEG`` and ``/SURF/SURF`` do
    NOT: measured on a free-floating /PLOAD impulse, the same face on two seg
    rows applies exactly TWICE the load at 0 ERROR (one-row vs two-row twin,
    both NORMAL TERMINATION at 67 cycles: EXT-WORK 18.35 -> 73.39 and K-ENERGY
    17.68 -> 70.73, a factor of 4.0005 in energy = impulse x2.0001). Only
    ``/SURF/DSURF`` de-duplicates, and k2rad emits the flat ``/SURF/SEG``
    form — so the union has to do it here.

    The corner list arrives already canonical in LENGTH: ``handle_set_segment``
    collapses BOTH documented triangle spellings (``n1 n2 n3 0`` and the
    manual's ``n1 n2 n3 n3``, Vol I R17 p.43-63) to a 3-node list, so this
    function never has to compare a 3-tuple against a 4-tuple naming the same
    face.
    """
    n = len(nodes)
    return min(tuple(nodes[i:] + nodes[:i]) for i in range(n)) if n else ()


def _flatten_set_adds(state: ConversionState) -> None:
    """``*SET_<FAMILY>_ADD`` → a plain set of that family, resolved ONCE for
    every consumer — the shared resolver for all seven families.

    An ``_ADD`` set's data ids are SET ids of its own family, so the block
    cannot land in the family's ordinary container at parse time (a child set
    may not be read yet, and every consumer reads the members as entity ids).
    Expanding it here into a normal ``state.<family>_sets`` entry makes every
    consumer — contact sides, *CONTACT_INTERIOR, --auto-gapmin, /GRAV and ALE
    part scopes, /BCS, /RBODY, /IMPVEL, /RWALL node scopes, /SECT groups, the
    /TH channel expansion, /PLOAD and /LOAD/PBLAST surfaces — resolve the union
    without knowing the variant. Before this pass covered the family, a
    *BOUNDARY_SPC_SET on a *SET_NODE_ADD lost its constraint at ZERO starter
    diagnostics.

    ONE resolver rather than seven copies: the family table lives in
    ``state.SET_ADD_FAMILIES``, which also generates the parser keys and the
    ``*INCLUDE_TRANSFORM`` offset rows, so a guard added here cannot go dead on
    a sibling family.

    **Nesting is RECURSIVE**, with a cycle guard and a warned depth cap
    (``_SET_ADD_MAX_DEPTH``). The manual states no nesting rule either way; the
    reference implementation recurses without limit and breaks cycles with a
    memo (``convertsets.cxx:1248-1277``). k2rad <= PR #129 expanded exactly one
    level for *SET_PART_ADD and warn-dropped a nested child; that restriction
    is lifted here, so a chain of unions now resolves in full.

    **Members are de-duplicated.** For every family but SEGMENT this only
    matches what the starter does anyway (``sysfus.F:468-479``,
    ``nintrr.F:814-828``); for SEGMENT it is load-bearing — see
    ``_segment_key``.

    Runs post-parse (all member blocks are read by then) and is idempotent:
    convert() calls it right after dispatch so --auto-gapmin sees it, and
    build_starter calls it again for direct-writer callers. Parse-time
    consumers (*ELEMENT_MASS_PART_SET, *LOAD_BODY_PARTS,
    *CONSTRAINED_EXTRA_NODES_SET, *ELEMENT_MASS_NODE_SET) resolve during
    dispatch and still see only direct sets — a pre-existing deck-order
    limitation this pass cannot lift.
    """
    if state.set_adds_flattened:
        return
    state.set_adds_flattened = True
    # NODE last: *SET_NODE_ADD_ADVANCED unions across families and reads the
    # element/segment sets, which must be flattened first.
    rows = [r for r in SET_ADD_FAMILIES if r[0] != "NODE"]
    rows += [r for r in SET_ADD_FAMILIES if r[0] == "NODE"]
    for family, keyword, _ncells, adds_name, target_name in rows:
        _flatten_one_set_add_family(state, family, keyword,
                                    adds_name, target_name)


#: Kept as the historical name for the PART-only entry point (it is what
#: convert() and build_starter used before the resolver became generic). It
#: flattens every family — a caller that wanted only part sets would leave the
#: other six unions invisible to their consumers, which is the bug this batch
#: exists to fix.
_flatten_part_set_adds = _flatten_set_adds


def _set_add_members(state: ConversionState, family: str, target_name: str,
                     sid: int):
    """The MEMBER list of a resolved set of *family*, as a list of hashable
    keys plus the value each key stands for.

    Every family but SEGMENT stores ``sid -> (title, [ids])``; SEGMENT stores a
    ``SegmentSet`` whose ``segments`` are corner-node lists (unhashable), so
    the union keys them through ``_segment_key`` and keeps the ORIGINAL list as
    the value — the segment's node order fixes its outward normal and must
    survive verbatim.
    """
    container = getattr(state, target_name)
    entry = container.get(sid)
    if entry is None:
        return None
    if family == "SEGMENT":
        # A COPY of each corner list: the union's SegmentSet must not alias
        # the child's rows, or a later in-place edit would reach both.
        return [(_segment_key(seg), list(seg)) for seg in entry.segments]
    return [(v, v) for v in entry[1]]


def _flatten_one_set_add_family(state: ConversionState, family: str,
                                keyword: str, adds_name: str,
                                target_name: str) -> None:
    """One family's unions, expanded into its ordinary container.

    Every diagnostic is keyed on the union id its TEXT names, and the memo is
    keyed the same way, so a union that appears as a member of two others still
    reports its own unresolved members exactly once (the #129 round-2 rule:
    de-duplicate a diagnostic at the scope its text names). It is also keyed on
    the SPELLING that id was written with, so a ``*SET_NODE_ADD_ADVANCED``
    block is never reported under a keyword the deck does not contain.

    The traversal is an EXPLICIT stack, not Python recursion. The depth cap is
    an intrinsic-height cap (see ``expand``), which can only be evaluated
    bottom-up, so a chain has to be walked to its end before the cap can fire —
    with a recursive walk a deck of a few hundred nested unions raised
    ``RecursionError`` and aborted the conversion instead of hitting the cap.
    """
    adds = getattr(state, adds_name)
    advanced = state.node_set_add_advanced if family == "NODE" else {}
    if not adds and not advanced:
        return
    container = getattr(state, target_name)
    # Snapshot the DIRECT sets before anything is added, so an already-expanded
    # union is never mistaken for one (the id sets below decide what a child
    # id MEANS, and that must not depend on iteration order).
    direct_ids = set(container)
    union_ids = set(adds) | set(advanced)
    memo: Dict[int, Tuple[Any, Any, Any]] = {}   # sid -> (out, height, cyclic)
    # Every diagnostic below names ONE set id, so it is de-duplicated on that
    # id and not on the expansion memo — skipping the memo for a cycle-cut
    # subtree (see expand) would otherwise repeat a union's own "member set
    # id(s) ... name no parsed set" line once per path that reaches it, and a
    # cycle reachable through two members would warn about it twice. Everything
    # that reports goes through warn_once, INCLUDING _advanced_members.
    reported = set()

    def kw_of(sid: int) -> str:
        """The spelling THIS set id was written with. ``*SET_NODE_ADD`` and
        ``*SET_NODE_ADD_ADVANCED`` share one id namespace and one resolver, so
        the family keyword alone would report an ADVANCED block under a card
        that is not in the deck — a reader grepping for it finds nothing."""
        return ("SET_NODE_ADD_ADVANCED"
                if family == "NODE" and sid in advanced else keyword)

    def warn_once(kind, sid, msg):
        if (kind, sid) in reported:
            return
        reported.add((kind, sid))
        state.warn(msg)

    def members_of(sid: int, missing: List[int]):
        """The ``(child_id, pre_resolved_or_None)`` list of union *sid*."""
        if family == "NODE" and sid in advanced:
            return _advanced_members(state, sid, advanced[sid][1], missing,
                                     warn_once)
        return [(child, None)
                for child in _expanded_member_ids(family, keyword, sid,
                                                  adds[sid][1], direct_ids,
                                                  union_ids, warn_once)]

    def absorb(frame, child: int, got):
        """Merge one child's ``(members, height, cyclic)`` into *frame*."""
        members_of_child, h, child_cyclic = got
        frame["cyclic"] = frame["cyclic"] or child_cyclic
        if h + 1 > _SET_ADD_MAX_DEPTH:
            warn_once("depth", (frame["sid"], child),
                f"*{kw_of(frame['sid'])} {frame['sid']}: member set {child} "
                f"sits at the top of a chain of nested _ADD unions more than "
                f"{_SET_ADD_MAX_DEPTH} levels deep — that member is "
                "DROPPED. This depth cap is a k2rad policy, not a manual "
                "rule: the LS-DYNA *SET chapter states no nesting rule "
                "and no limit, so there is nothing to be faithful to. "
                "Flatten the deck's set hierarchy if the deeper members "
                "matter.")
            return
        frame["height"] = max(frame["height"], h + 1)
        seen, out = frame["seen"], frame["out"]
        for key, val in members_of_child:
            if key not in seen:
                seen.add(key)
                out.append((key, val))

    def new_frame(sid: int):
        missing: List[int] = []
        return {"sid": sid,
                "members": members_of(sid, missing), "i": 0,
                "out": [], "seen": set(), "missing": missing,
                "height": 0, "cyclic": False}

    def expand(root: int):
        """``([(key, value)], height, cyclic)`` for union *root*, by an
        EXPLICIT stack.

        ``height`` is the number of union levels BELOW a node inclusive — 0 for
        a direct set — and it is INTRINSIC to the subtree, never a function of
        which union happened to be expanded first. That is what makes the depth
        cap deterministic: memoising a traversal-order depth would let a deck's
        set ids decide whether the cap fires. It also means the cap can only be
        applied on the way back UP, so the walk must be able to descend an
        arbitrarily long chain — hence the explicit stack rather than Python
        frames.

        ``cyclic`` says the subtree was CUT by the cycle guard. Such a result
        depends on the path taken to reach it, so it must not be memoised —
        otherwise a diamond over a cycle (A -> {X, B}, B -> {Y, A}) would give
        a later top-level expansion of B the members it had *as A's child*.
        """
        if root in memo:
            return memo[root]
        # ONE path list and ONE membership set for the whole walk, pushed and
        # popped with the stack: copying either per frame would make a deep
        # chain cost O(depth^2) memory, which is the shape this rewrite exists
        # to survive.
        stack = [new_frame(root)]
        path = [root]
        on_path = {root}
        while True:
            frame = stack[-1]
            if frame["i"] < len(frame["members"]):
                child, pre = frame["members"][frame["i"]]
                frame["i"] += 1
                if pre is not None:
                    absorb(frame, child, (pre, 0, False))
                elif child in direct_ids:
                    absorb(frame, child,
                           (_set_add_members(state, family, target_name, child),
                            0, False))
                elif child not in union_ids:
                    frame["missing"].append(child)
                elif child in on_path:
                    warn_once("cycle", child,
                        f"*{kw_of(child)} {child}: this union is reached from "
                        f"itself ({' -> '.join(str(p) for p in path)}"
                        f" -> {child}) — a set cannot contain itself, so the "
                        "cycle is CUT there and the rest of the union is kept. "
                        "LS-DYNA states no nesting rule for _ADD sets at all, "
                        "so a cycle has no defined meaning on either side; fix "
                        "the deck.")
                    absorb(frame, child, ([], 0, True))
                elif child in memo:
                    absorb(frame, child, memo[child])
                else:
                    stack.append(new_frame(child))
                    path.append(child)
                    on_path.add(child)
                continue
            # This frame is finished.
            sid = frame["sid"]
            if frame["missing"]:
                warn_once("missing", sid,
                    f"*{kw_of(sid)} {sid}: member set id(s) "
                    f"{sorted(set(frame['missing']))} "
                    "name no parsed set of the family they claim (missing "
                    "block, or an unsupported variant such as _GENERAL/"
                    "_COLUMN/_GENERATE) — that slice of the union is "
                    "UNRESOLVED and dropped BY NAME. A dangling member is "
                    "never written into the group instead: the starter accepts "
                    "one as nothing worse than WARNING 174 (hm_grogronod.F), "
                    "so it would silently come up short.")
            got = (frame["out"], frame["height"], frame["cyclic"])
            if not frame["cyclic"]:
                memo[sid] = got
            stack.pop()
            path.pop()
            on_path.discard(sid)
            if not stack:
                return got
            absorb(stack[-1], sid, got)

    for sid in sorted(union_ids):
        title = (advanced[sid][0] if sid in advanced else adds[sid][0])
        if sid in direct_ids:
            state.warn(
                f"*{kw_of(sid)} {sid}: a direct set with the same id is also "
                "defined — LS-DYNA set ids are unique per set type "
                "(Vol I R17 p.43-1), so the direct set wins and the _ADD "
                "block is IGNORED. Check the two blocks.")
            continue
        if family == "NODE" and sid in advanced and sid in adds:
            state.warn(
                f"*SET_NODE_ADD_ADVANCED {sid}: a plain *SET_NODE_ADD with "
                "the same id is also defined. Set ids are unique per set type, "
                "so only one can be the deck's set — the ADVANCED block wins "
                "here and the plain one is IGNORED. Check the two blocks.")
        values = [v for _k, v in expand(sid)[0]]
        if not values:
            # Deliberately NOT registered as an empty set. The deck's union is
            # not empty — k2rad simply could not resolve any of its members
            # (the warning above names them) — so an empty set here would be a
            # FALSE statement about the model, and every consumer's "set not
            # found" message is the truthful one. It would also be a card the
            # deck did not ask for: MEASURED on starter_win64 (2026-05-20), an
            # empty /GRNOD/NODE draws "WARNING ID : 690 ** WARNING IN NODE
            # GROUP DEFINITION / THE NODE GROUP ID=... IS EMPTY" (0 ERRORS,
            # NORMAL TERMINATION) — a diagnostic pointing at the wrong thing.
            # A union that is a MEMBER of another union still resolves through
            # the memo above, so a chain is unaffected.
            state.warn(
                f"*{kw_of(sid)} {sid}: the union resolves to NO member at "
                "all, so no set of that id is created and every consumer will "
                "report it as undefined. That is deliberate — an empty set "
                "would claim the deck's union is empty when it is only "
                "unresolved here (and an empty /GRNOD draws starter WARNING "
                "690 naming the wrong culprit). Convert or restate the member "
                "sets named above.")
            continue
        if family == "SEGMENT":
            container[sid] = SegmentSet(sid, title, values)
        else:
            container[sid] = (title, values)


def _expanded_member_ids(family: str, keyword: str,
                         sid: int, raw_ids, direct_ids, union_ids,
                         warn_once) -> List[int]:
    """The member ids of one plain ``*SET_..._ADD``, with ``*SET_PART_ADD``'s
    negative RANGE form expanded.

    Vol I R17 p.43-57 gives ``PSID[N]`` two readings and only *SET_PART_ADD*
    has them (the NODE, SEGMENT, SHELL, SOLID, BEAM and DISCRETE ``_ADD`` pages
    carry no ``GT.0``/``LT.0`` block at all, checked against the R17 text):

        GT.0: PSID[N] is added to SID,
        LT.0: All part sets with ID between PSID[N-1] and -PSID[N], including
              PSID[N-1] and -PSID[N], will be added to SID.
        ... PSID[N-1] must be > 0 and must have a magnitude smaller or equal
        to -PSID[N] when PSID[N] < 0.

    So ``... 5, -9`` means part sets 5..9, not "5, then a stray flag". The
    parser keeps the negative cell (only exact zeros are padding) and the range
    is resolved HERE, where every child set of the family is known — at parse
    time the deck may not have read them yet, which is the whole reason the
    ``_ADD`` families are deferred.

    The pool is every part set the deck defines, direct or itself an ``_ADD``:
    a ``*SET_PART_ADD`` is a part set too, so one inside the range is picked up
    and then resolved by the ordinary recursion — EXCEPT the union's own id.
    ``*SET_PART_ADD 7`` with members ``5, -9`` spans 7, and the pool holds 7,
    so without that exclusion the union becomes a member of itself: the members
    still come out right (a union with itself is a no-op) but the resolver's
    cycle guard fires and tells the reader to "fix the deck" on a deck the very
    page above declares legal — and marks the frame ``cyclic``, which bars that
    union and every union above it from the memo. The manual's "all part sets
    with ID between" cannot mean the set being defined; ``k != lo`` already
    drops the range's start for the same no-op reason.
    """
    ids: List[int] = []
    prev = 0
    for v in raw_ids:
        if v > 0:
            ids.append(v)
            prev = v
            continue
        lo, hi = prev, -v
        # ``PSID[N-1]`` is the cell IMMEDIATELY before, so a range consumes its
        # start: ``5, -9, -12`` is not 5..12, it is a valid range followed by a
        # negative whose predecessor is negative — malformed, and reported.
        prev = 0
        if family != "PART":
            warn_once("negid", (sid, v),
                f"*{keyword} {sid}: member id {v} is NEGATIVE. Only "
                "*SET_PART_ADD gives a negative cell a meaning (the "
                "PSID[N-1]..-PSID[N] inclusive RANGE, Vol I R17 p.43-57); this "
                "keyword's page states none, so the cell is DROPPED. Restate "
                "the member as a positive set id.")
            continue
        if lo <= 0 or hi < lo:
            warn_once("negid", (sid, v),
                f"*{keyword} {sid}: member id {v} opens a range "
                f"PSID[N-1]..{hi}, but the manual requires the PRECEDING cell "
                f"to be positive and no larger than {hi} (Vol I R17 p.43-58); "
                f"here it is {lo}. The range is DROPPED — fix the pair.")
            continue
        ids.extend(k for k in sorted(set(direct_ids) | set(union_ids))
                   if lo <= k <= hi and k != lo and k != sid)
    return ids


def _advanced_members(state: ConversionState, nsid: int, pairs, missing,
                      warn_once):
    """``*SET_NODE_ADD_ADVANCED`` members: ``(child, pre-resolved)`` pairs.

    A ``TYPE = 1`` member is an ordinary node set and is handed back for the
    node family's own recursion (``pre = None``). Every other TYPE names a set
    of a DIFFERENT family, whose contribution is the NODES of the entities it
    lists — those families are already flattened when this runs (the NODE row
    is resolved last), so they are expanded here and returned ready-made.

    The drop diagnostics go through the caller's ``warn_once``, keyed on the
    ``nsid`` their text names: a union inside a cycle is deliberately NOT
    memoised, so this function can be reached twice for one set and a bare
    ``state.warn`` would print the same line twice (the #129 round-2 rule).
    """
    out: List[Tuple[int, Optional[List[Tuple[int, int]]]]] = []
    dropped: Dict[str, List[int]] = {}
    for child, typ in pairs:
        fam = SET_ADD_ADVANCED_TYPES.get(typ)
        if child < 0:
            # p.43-46 gives card 2b's SID[N] no GT.0/LT.0 reading, so dropping
            # is right — but by NAME, like every plain _ADD family since the
            # review round (_expanded_member_ids' non-PART arm).
            warn_once(("advneg", child), nsid,
                f"*SET_NODE_ADD_ADVANCED {nsid}: member set id {child} is "
                "NEGATIVE. Card 2b's SID[N] has no GT.0/LT.0 reading on its "
                "page (Vol I R17 p.43-46) — only *SET_PART_ADD's PSID gives a "
                "negative cell the RANGE meaning (p.43-57) — so the cell is "
                "DROPPED. Restate the member as a positive set id.")
            continue
        if typ in (0, 1):
            # TYPE 1 is "Node set". A blank/0 TYPE is not a documented value;
            # the only sane reading of a bare id on a NODE set's own card is a
            # node set, which is what the non-ADVANCED spelling means anyway.
            out.append((child, None))
            continue
        if fam is None:
            dropped.setdefault(f"a TYPE={typ} that the manual does not define "
                               "(Vol I R17 p.43-46 lists 1..7)",
                               []).append(child)
            continue
        name, attr = fam
        if not attr:
            dropped.setdefault(
                f"TYPE={typ}, a {name.lower()} set — k2rad does not convert "
                "*SET_TSHELL, so there is no member list to take nodes from",
                []).append(child)
            continue
        entry = getattr(state, attr).get(child)
        if entry is None:
            missing.append(child)
            continue
        out.append((child, [(n, n)
                            for n in _entity_set_nodes(state, name, entry)]))
    for reason, ids in sorted(dropped.items()):
        warn_once(("adv", reason), nsid,
            f"*SET_NODE_ADD_ADVANCED {nsid}: member set id(s) {sorted(ids)} "
            f"carry {reason} — that slice of the node union is DROPPED. "
            "(dyna2rad reads this card as a plain id list and never dispatches "
            "on TYPE at all, convertsets.cxx:103, so there the TYPE column "
            "itself is taken for another set id.)")
    return out


#: How each element family's node ids are read off its k2rad record. Shells and
#: solids keep a ``nodes`` list; beams and springs keep named end nodes.
#:
#: A BEAM contributes N1 and N2 only. Its third node is an ORIENTATION
#: reference, not a structural node of the beam — and on an
#: ``*ELEMENT_BEAM_ORIENTATION`` beam k2rad SYNTHESIZES it
#: (``_synthesize_beam_orientation_nodes``), so it need not exist in the source
#: deck at all; putting a converter artefact into a set the deck defined would
#: be wrong outright. A DISCRETE spring's N2 = 0 means "attached to ground"
#: (Vol I R17 *ELEMENT_DISCRETE) and is filtered by the ``n > 0`` test below.
_ADVANCED_NODE_READERS = {
    "SHELL": ("shell_elems", lambda e: e.nodes),
    "SOLID": ("solid_elems", lambda e: e.nodes),
    "BEAM": ("beam_elems", lambda e: (e.n1, e.n2)),
    "DISCRETE": ("discrete_elems", lambda e: (e.n1, e.n2)),
}


def _entity_set_nodes(state: ConversionState, family: str, entry) -> List[int]:
    """The node ids an ``*SET_NODE_ADD_ADVANCED`` member of *family*
    contributes, in first-seen order."""
    ids: List[int] = []
    seen: Set[int] = set()
    if family == "SEGMENT":
        rows = entry.segments
    else:
        table_name, reader = _ADVANCED_NODE_READERS[family]
        wanted = set(entry[1])
        rows = [reader(e) for e in getattr(state, table_name)
                if e.eid in wanted]
    for row in rows:
        for n in row or ():
            if n > 0 and n not in seen:
                seen.add(n)
                ids.append(n)
    return ids


def _resolve_contact_interior(state: ConversionState) -> None:
    """*CONTACT_INTERIOR → Icontrol=1 (solid distortion control) on the
    listed parts' /PROP — resolved, classified and WARNED, not emitted.

    dyna2rad's whole conversion is one property write (CC:751-759): look up
    each part of each PSID and `SetValue(prop, "Icontrol", 1)`. The catch is
    a version gate this converter measured rather than guessed: the Icontrol
    input column exists only in the radioss2025 property formats
    (prop_p14_solid.cfg / prop_p6_sol_orth.cfg FORMAT(radioss2025) last card
    "Ndir sphpartID Icontrol"; the radioss2022 blocks end at "Ndir
    sphpartID"), and k2rad emits /BEGIN 2022 decks. Measured on starter_win64
    (2026-05-20): appending the 3-field card under /BEGIN 2022 leaves the
    per-part echo at ICONTROL 0 and draws WARNING 100213 (unsupported field
    at end of line); the identical deck under /BEGIN 2025 echoes ICONTROL 1
    cleanly. Emitting a dead field that claims to be set would be silently
    wrong, so the conversion is a loud warning naming the affected parts
    (plus note_recognized_not_emitted), the PSID resolution following
    dyna2rad CC:671-767: each id is a *SET_PART (part ids); a *SET_PART_ADD
    arrives pre-expanded by _flatten_set_adds (recursively, and with its
    negative PSID range form resolved). The per-set attributes DA1..DA4
    (PSF/Fa/ED/TYPE — the manual defines them on the referenced set, not the
    contact card) have no Icontrol counterpart at any version and are warned
    when set; dyna2rad reads none of them.
    """
    if not state.contact_interior_psids:
        return
    state.note_recognized_not_emitted(
        "*CONTACT_INTERIOR",
        "its Radioss counterpart Icontrol=1 on the solid /PROP is a "
        "radioss2025-only input column; a /BEGIN 2022 deck cannot carry it "
        "(measured: ICONTROL echo stays 0 + starter WARNING 100213), so the "
        "affected parts are named in a warning instead")
    # Icontrol lives on the solid AND thick-shell property readers
    # (hm_read_prop06/14/20/21/22.F + /DEF_SOLID), so "has an Icontrol-bearing
    # property" is "holds solid OR thick-shell elements". SPH is deliberately
    # NOT in that set: /PROP/SPH has no Icontrol column at any version, and
    # *CONTACT_INTERIOR is a solid-element keyword (it damps the interior of a
    # crushing foam BRICK), so an SPH part named by one is not a lost mapping.
    # *SET_PART_ADD sets were already expanded into part_sets by
    # _flatten_set_adds (recursively; dyna2rad stops at one level,
    # CC:692-727), so a single lookup covers both variants.
    solid_pids = ({e.pid for e in state.solid_elems}
                  | {e.pid for e in state.tshell_elems})
    for psid in sorted(set(state.contact_interior_psids)):
        direct = state.part_sets.get(psid)
        if direct is None:
            state.warn(
                f"*CONTACT_INTERIOR: part set {psid} is not defined in the "
                "deck (or uses an unsupported *SET_PART variant such as "
                "_COLUMN/_GENERATE) — the interior-contact scope cannot be "
                "resolved for it.")
            continue
        title, pids = direct[0], list(direct[1])
        known = [p for p in pids if p in state.parts]
        unknown = sorted(set(pids) - set(known))
        if unknown:
            state.warn(
                f"*CONTACT_INTERIOR (set {psid}): part id(s) {unknown} have "
                "no *PART card — ignored.")
        with_icontrol = sorted(p for p in known if p in solid_pids)
        without = sorted(p for p in known if p not in solid_pids)
        setname = f" '{title}'" if title else ""
        if with_icontrol:
            state.warn(
                f"*CONTACT_INTERIOR (set {psid}{setname}): LS-DYNA arms "
                "interior contact inside the foam solids of part(s) "
                f"{with_icontrol}; the Radioss counterpart is Icontrol=1 "
                "(solid distortion control) on their /PROP — but that input "
                "column exists only in the radioss2025 property format, and "
                "k2rad emits /BEGIN 2022 decks, where the starter reads the "
                "trailing property card as 'Ndir sphpartID' only (measured "
                "on starter_win64: the appended field is ignored — per-part "
                "echo ICONTROL 0 — and draws WARNING 100213). NOT emitted: "
                "these parts run WITHOUT interior contact, so deep crush "
                "can invert elements (negative volume) that LS-DYNA would "
                "have caught. Mitigate with /DT/BRICK/CST (small-strain "
                "switching) in the engine file, or migrate the deck to the "
                "2025 format and set Icontrol=1 by hand.")
        if without:
            state.warn(
                f"*CONTACT_INTERIOR (set {psid}{setname}): part(s) "
                f"{without} carry no solid/thick-shell elements — their "
                "converted property type has NO Icontrol field at ANY "
                "format version (interior contact is a solid-element "
                "mechanism), so there is nothing to convert for them. "
                "(dyna2rad's blind SetValue silently no-ops there too.)")
        attrs = state.part_set_attrs.get(psid)
        if attrs:
            psf, fa, ed, ctype = attrs
            named = []
            if psf not in (0.0, 1.0):
                named.append(f"PSF={psf:g} (penalty scale factor)")
            if fa:
                named.append(f"Fa={fa:g} (activation factor: contact begins "
                             f"at {fa:g} x initial thickness; LS-DYNA "
                             "default 0.1)")
            if ed:
                named.append(f"ED={ed:g} (interior-contact stiffness "
                             "modulus)")
            if named:
                state.warn(
                    f"*CONTACT_INTERIOR (set {psid}{setname}): set "
                    f"attribute(s) {', '.join(named)} tune the LS-DYNA "
                    "interior-contact penalty — Icontrol is a plain on/off "
                    "flag with no equivalent knobs, and since it cannot be "
                    "emitted at /BEGIN 2022 anyway, they are dropped "
                    "(dyna2rad never reads DA1..DA4 either).")
            if ctype == 2.0:
                state.warn(
                    f"*CONTACT_INTERIOR (set {psid}{setname}): TYPE=2 "
                    "(DA4) selects the combined compression+shear "
                    "formulation for ELFORM 1/10 solids — the distinction "
                    "has no Radioss counterpart and is dropped (dyna2rad "
                    "never reads it; every listed part would get the same "
                    "Icontrol=1).")


def _assign_ortho_props(state: ConversionState) -> None:
    """*MAT_ANISOTROPIC_VISCOPLASTIC → /MAT/LAW128 is orthotropic-only, so a part
    using it cannot sit on the isotropic /PROP/SHELL|SOLID (starter ERROR 3047).
    Allocate a dedicated orthotropic property id per such part; the /PART is
    repointed at it in _make_parts_and_elements and the property is emitted by
    _emit_ortho_props. Runs as a build_starter prepass, before parts/properties.
    """
    if not state.mat_aniso_visco:
        return
    mat_mids = set(state.mat_aniso_visco)
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    tshell_pids = {e.pid for e in state.tshell_elems}
    sph_pids = {c.pid for c in state.sph_elems}
    for pid, part in sorted(state.parts.items()):
        if part.mid not in mat_mids or pid in state.ortho_prop_ids:
            continue
        # A composite part already owns a dedicated orthotropic /PROP.
        if pid in state.composite_prop_ids:
            continue
        # So does a THICK-SHELL part: /MAT/LAW128 is PROP_SOLID class 2, which
        # /PROP/TYPE21 and TYPE22 accept and /PROP/TYPE20 rejects, so the
        # thick-shell section route already picks the orthotropic property for
        # it. Skipped before the element-kind test below, which would otherwise
        # tell the user their thick shells are not a mesh.
        if pid in tshell_pids:
            continue
        # And so does an SPH part, differently: /MAT/LAW128 IS on the starter's
        # SPH whitelist (init_mat_keyword.F), so the pairing is legal — but the
        # only property an SPH part may carry is /PROP/SPH (IGTYP 34, else
        # ERROR 3047), and that property has an orthotropy slot of its own
        # (skew_ID). Synthesizing a /PROP/TYPE9 or TYPE6 here would replace the
        # particle property outright. Skipped before the element-kind test
        # below, which would otherwise tell the user their particles are not a
        # mesh.
        if pid in sph_pids:
            continue
        if pid not in shell_pids and pid not in solid_pids:
            state.warn(
                f"*MAT_ANISOTROPIC_VISCOPLASTIC on part {pid}: no shell or solid "
                "elements found — /MAT/LAW128 needs an orthotropic shell/solid "
                "property. The part keeps its default property, which the starter "
                "will reject as incompatible; check the mesh.")
            continue
        state.ortho_prop_ids[pid] = state.next_id()
    if state.ortho_prop_ids:
        state.warn(
            "*MAT_ANISOTROPIC_VISCOPLASTIC → /MAT/LAW128 requires an orthotropic "
            f"property: synthesized /PROP/TYPE9 (shell) or /PROP/TYPE6 (solid) for "
            f"part(s) {sorted(state.ortho_prop_ids)}. The orthotropy reference "
            "direction is auto-mapped from the material AOPT where it is a global "
            "vector (AOPT=2/3); other AOPT modes fall back to global X — see the "
            "per-part notes below.")


def _assign_hourglass_props(state: ConversionState) -> None:
    """Per-part hourglass overlay (*HOURGLASS via *PART HGID, or the global
    *CONTROL_HOURGLASS). k2rad /PROPs are per-SECTION, so a part whose effective
    hourglass differs from its section's base (the global card) needs its own
    /PROP — allocate an id here and record the resolved (h, Isolid) for
    _emit_hourglass_props; the /PART is repointed in _make_parts_and_elements.
    Runs as a build_starter prepass, before parts/properties, after ortho.
    Semantics follow dyna2rad — see the comment block above _make_properties.
    """
    if not state.hourglass_defs and state.ctrl_hourglass is None \
            and not any(p.hgid > 0 for p in state.parts.values()):
        # No *HOURGLASS, no *CONTROL_HOURGLASS, and no part references an HGID →
        # nothing to do, behaviour unchanged. (A part carrying an HGID with no
        # matching *HOURGLASS card still enters, to warn about the dangling id.)
        return
    part_secids = {pid: (p.secid if p.secid > 0 else pid)
                   for pid, p in state.parts.items()}
    solid_pids = {e.pid for e in state.solid_elems}
    shell_pids = {e.pid for e in state.shell_elems}
    warned_ihq: Set[int] = set()
    shell_inert_warned = False
    ctrl_isolid_warned = False
    # Sibling parts that share a SECID AND resolve to the same effective
    # hourglass get ONE shared split /PROP, not a byte-identical copy each:
    # (is_solid, secid, eff) → prop_id.
    prop_by_key: Dict[Tuple[bool, int, Tuple[Optional[float], Optional[int]]],
                      int] = {}
    cohesive_secids = _cohesive_solid_secids(state)
    for pid, part in sorted(state.parts.items()):
        # A LAW128, composite or FABRIC part already owns a dedicated
        # orthotropic/anisotropic /PROP; the hourglass overlay does not also
        # split it (its TYPE6/TYPE9/TYPE11/TYPE16/TYPE51 keeps its defaults —
        # and on fabric an overlay would emit a /PROP/SHELL the starter refuses
        # for LAW19/LAW58, ERROR 3047).
        if (pid in state.ortho_prop_ids or pid in state.composite_prop_ids
                or pid in state.fabric_prop_ids
                # A 2D belt part is on /PROP/TYPE9 for the same ERROR 3047
                # reason a fabric part is, and Ishell=12 (QEPH) has no
                # hourglass for an overlay to set.
                or pid in state.seatbelt_prop_ids):
            continue
        # A cohesive section emits /PROP/TYPE43, which has no hourglass (4
        # mid-plane Gauss points) — splitting the part onto a /PROP/SOLID
        # clone would both drop the cohesive formulation and hit the
        # SOLID_COHESIVE-law compatibility refusal (ERROR 3047). The
        # elform-cohesive case is already gated inside _solid_hg_values;
        # this skip also covers the MATERIAL-routed sections (ARUP adhesive
        # on ELFORM 1), which that sec-only gate cannot see.
        if part_secids.get(pid) in cohesive_secids:
            continue
        is_solid = pid in solid_pids
        is_shell = pid in shell_pids and not is_solid
        if not (is_solid or is_shell):
            # beams / discrete / tshell: no k2rad hourglass /PROP path.
            # SPH is skipped DELIBERATELY, not for want of a property path
            # (k2rad has had *SECTION_SPH → /PROP/SPH since the SPH batch):
            # a particle has no hourglass modes and /PROP/SPH has no hourglass
            # field at all, so a *HOURGLASS / HGID on a particle part is inert
            # in both codes. dyna2rad maps QM/QH onto the /PROP/SPH cell named
            # "h", which is a LENGTH — see writer/sph.py divergence 5, where
            # the measured damage is a smoothing length of 0.13 (and, for the
            # *CONTROL_HOURGLASS QH path, of zero).
            continue
        secid = part_secids[pid]
        # Resolve the part's *HOURGLASS (HGID). A dangling / undefined id is a
        # LOUD warn + fallback to the global card (dyna2rad is silent here; the
        # task requires the warning).
        hg = None
        if part.hgid > 0:
            hg = state.hourglass_defs.get(part.hgid)
            if hg is None:
                state.warn(
                    f"*PART {pid}: HGID={part.hgid} references a *HOURGLASS card "
                    "not defined in the deck — falling back to the global "
                    "*CONTROL_HOURGLASS (or the Radioss property defaults). "
                    "Check the *HOURGLASS id.")
        if is_solid:
            # A *PART on an undefined SECID gets an auto-created *SECTION_SOLID
            # in _make_properties (which runs AFTER this prepass). Resolve to the
            # SAME default here so the split decision reflects the formulation the
            # property will actually carry — otherwise a per-part *HOURGLASS on a
            # sectionless part would be silently dropped (sec=None → no remap).
            sec = state.sec_solids.get(secid) or _auto_section_solid(secid)
            eff = _solid_hg_values(state, sec, hg)
            base = _solid_hg_values(state, sec, None)
            # The global *CONTROL_HOURGLASS was previously inert; now honored, it
            # can remap the shared solid /PROP Isolid off its ELFORM default.
            # Note it once for the parts that inherit the global card (no HGID).
            if hg is None and state.ctrl_hourglass is not None \
                    and base[1] is not None and not ctrl_isolid_warned \
                    and sec is not None and base[1] != _elform_to_isolid(sec.elform):
                ctrl_isolid_warned = True
                state.warn(
                    f"*CONTROL_HOURGLASS IHQ={state.ctrl_hourglass.ihq} is now "
                    "honored (was previously dropped): the shared /PROP/SOLID "
                    f"Isolid is remapped {_elform_to_isolid(sec.elform)}→"
                    f"{base[1]} (h={base[0]:g}) for parts without a *PART HGID. "
                    "Set HGID or *HOURGLASS per part to override.")
            # Unsupported IHQ (0/8/9/10): h is applied but Isolid is unmapped —
            # warn once per distinct IHQ (dyna2rad silently keeps the Isolid).
            if eff[0] is not None:
                gov = (hg.ihq if hg is not None
                       else state.ctrl_hourglass.ihq
                       if state.ctrl_hourglass is not None else None)
                if gov is not None and _ihq_to_isolid(gov) is None \
                        and gov not in warned_ihq:
                    warned_ihq.add(gov)
                    src = (f"*HOURGLASS {hg.hgid}" if hg is not None
                           else "*CONTROL_HOURGLASS")
                    state.warn(
                        f"{src}: IHQ={gov} has no faithful Radioss solid Isolid "
                        "mapping (only IHQ 1-7 → Isolid 1/5/24). The section's "
                        "ELFORM-derived Isolid is kept; the hourglass coefficient "
                        f"h={eff[0]:g} is still applied. Verify the formulation.")
        else:
            sec = state.sec_shells.get(secid) or _auto_section_shell(secid)
            eff = _shell_hg_values(state, sec, hg)
            base = _shell_hg_values(state, sec, None)
            if eff[0] is not None and not shell_inert_warned:
                shell_inert_warned = True
                state.warn(
                    "Shell hourglass coefficient (*HOURGLASS/*CONTROL_HOURGLASS) "
                    "written to /PROP/SHELL Hm/Hf/Hr (clamped to "
                    f"{_SHELL_HG_MAX:g}), but k2rad selects Ishell 12 (QBAT) / 24 "
                    "(QEPH) from ELFORM, for which Hm/Hf/Hr are physically inert "
                    "(full integration / physical stabilization). The coefficient "
                    "is carried for fidelity; switch to an under-integrated "
                    "Ishell 1-4 to activate it.")
        if eff != base:
            key = (is_solid, secid, eff)
            prop_id = prop_by_key.get(key)
            if prop_id is None:
                prop_id = state.next_id()
                prop_by_key[key] = prop_id
            state.hourglass_prop_ids[pid] = prop_id
            state.hourglass_prop_vals[pid] = eff
    if state.hourglass_prop_ids:
        state.warn(
            "Per-part hourglass control split the shared section /PROP for "
            f"part(s) {sorted(state.hourglass_prop_ids)} into dedicated /PROP "
            "copies (their *HOURGLASS/HGID resolves differently from the "
            "section's global *CONTROL_HOURGLASS base) — h/Isolid follow the "
            "*HOURGLASS card.")


def _warn_shell_formulation_choice(state: ConversionState) -> None:
    """Say which Ishell the unmapped shell ELFORMs got, and that it is a choice.

    The original defect reported in issue #77 was not only that ELFORM=2 maps
    to a fully-integrated Ishell — it was that it did so with **no warning of
    any kind**, so a formulation-class change was invisible in the log. That
    stays true whichever way the option is set, so this fires either way. It
    is the difference between a default and a silent default.

    Implicit decks are exempt: they return Ishell=24 regardless of the option,
    which predates it and is not a choice the user is making here.
    """
    if state.is_implicit or not state.sec_shells:
        return
    unmapped = sorted({s.elform for s in state.sec_shells.values()
                       if s.elform not in _ELFORM_ALWAYS_QEPH})
    if not unmapped:
        return
    ishell = state.options.shell_default_ishell
    if ishell == ISHELL_QEPH:
        state.warn(
            f"*SECTION_SHELL ELFORM {unmapped} -> /PROP/SHELL Ishell=24 "
            "(QEPH, reduced integration with physical stabilisation), because "
            "shell_formulation='qeph' was requested. This is NOT the default: "
            "the default 'qbat' emits Ishell=12 and is what every earlier "
            "conversion of this deck produced, so results WILL differ from "
            "them. QEPH is the closer match to ELFORM=2 Belytschko-Tsay and "
            "erodes more faithfully under /FAIL/JOHNSON Ifail_sh=2 (2 failure "
            "events to delete an element, not 8).")
    else:
        state.warn(
            f"*SECTION_SHELL ELFORM {unmapped} -> /PROP/SHELL Ishell=12 "
            "(QBAT, FULLY integrated, 4 in-plane points) — the default. Note "
            "LS-DYNA ELFORM=2 (Belytschko-Tsay) is UNDER-integrated, so this "
            "changes the element's integration class: with /FAIL/JOHNSON "
            "Ifail_sh=2 it takes 4 Gauss x 2 through-thickness = 8 failure "
            "events to delete an element instead of 2, measured at up to "
            "~1.7x under-erosion. Pass shell_formulation='qeph' (CLI "
            "--shell-formulation qeph) for Ishell=24, which is the closer "
            "match — it changes results, which is why it is not the default.")


def _emit_prop_type9(prop_id: int, title: str, sec: SectionShell,
                     is_implicit: bool, istrain: int, state: ConversionState,
                     refvec=(1.0, 0.0, 0.0), phi: float = 0.0) -> List[str]:
    """Orthotropic shell property /PROP/TYPE9 (SH_ORTH) — the isotropic
    /PROP/SHELL fields plus a material reference direction (Vx/Vy/Vz + Phi).
    Column layout from PROP/prop_p9_sh_orth.cfg FORMAT(radioss2022)."""
    ishell = _elform_to_ishell(sec.elform, is_implicit,
                               state.options.shell_default_ishell)
    nip = max(2, sec.nip)
    if sec.t1 <= 0.0:
        state.warn(
            f"/PROP/TYPE9/{prop_id}: shell thickness is {sec.t1:g} (<=0), which "
            "the starter rejects (THICK must be > 0). Set the *SECTION_SHELL "
            "thickness for the LAW128 shell part.")
    vx, vy, vz = refvec
    b20 = " " * 20
    return [
        f"/PROP/TYPE9/{prop_id}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill                            P_Thick_Fail",
        f"{_i(ishell)}{_i(0)}{_i(0)}{_i(0)}{b20}{_f(0.0)}",
        "#                 Hm                  Hf                  Hr                  Dm                  Dn",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#        N   ISTRAIN               Thick              Ashear     Iskew    ITHICK     IPLAS",
        f"{_i(nip)}{_i(istrain)}{_f(sec.t1)}{_f(0.0)}{_i(0)}{_i(0)}{_i(0)}",
        "#                 Vx                  Vy                  Vz                 Phi                  Ip",
        f"{_f(vx)}{_f(vy)}{_f(vz)}{_f(phi)}{' ' * 10}{_i(0)}",
        HDR,
    ]


def _emit_prop_type6(prop_id: int, title: str, sec: Optional[SectionSolid],
                     itetra10: int, istrain: int,
                     refvec=(1.0, 0.0, 0.0), ip: int = 11,
                     phi: float = 0.0, skew_id: int = 0,
                     refpoint=(0.0, 0.0, 0.0),
                     isolid: Optional[int] = None,
                     ismstr: int = 0) -> List[str]:
    """Orthotropic solid property /PROP/TYPE6 (SOL_ORTH). With skew_id the
    orthotropy axes are taken DIRECTLY from the /SKEW (starter maps Ip=0 +
    skew_ID to the internal Ip<0 skew branch: material dir 1 = skew X' for
    EVERY element, exactly). Without a skew, Ip=11 projects the reference
    vector onto each element's local r-s plane — element-topology-dependent on
    free tet meshes, so only used as a fallback. Column layout from
    PROP/prop_p6_sol_orth.cfg FORMAT(radioss2022).

    *refpoint* is the card-4 Px/Py/Pz reference POINT, which is a different
    field from the Vx/Vy/Vz reference VECTOR and the only place the starter
    looks for the two point-based modes: ``hm_read_prop06.F`` reads
    ``'Px'/'Py'/'Pz'`` into ``GEO(33..35)`` and echoes them for ``Ip=21``
    (point alone, :496) and ``Ip=24`` (cylindrical, point AND vector, :500).
    Routing a point through *refvec* puts it in the wrong columns and the
    orthotropy is silently built about the global origin instead.

    *isolid* None (default) derives the formulation from the section ELFORM
    as everywhere else; an explicit value pins it (the MAT_126 honeycomb
    path passes 1 — with *ismstr* 1 — matching dyna2rad's fixed
    ISOLID=1/Ismstr=1 for the honeycomb-family TYPE6, CP:404-476)."""
    if isolid is None:
        isolid = _elform_to_isolid(sec.elform) if sec else 0
    vx, vy, vz = (0.0, 0.0, 0.0) if skew_id else refvec
    px, py, pz = (0.0, 0.0, 0.0) if skew_id else refpoint
    if skew_id:
        ip, phi = 0, 0.0
    b10 = " " * 10
    lines = [
        f"/PROP/TYPE6/{prop_id}",
        title,
        "#   Isolid    Ismstr               Icpre  Itetra10     Inpts   Itetra4    Iframe                  Dn",
        f"{_i(isolid)}{_i(ismstr)}{b10}{_i(0)}{_i(itetra10)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}",
        "#                 qa                  qb                   h",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#                 Vx                  Vy                  Vz   skew_ID        Ip     Iorth",
        f"{_f(vx)}{_f(vy)}{_f(vz)}{_i(skew_id)}{_i(ip)}{_i(0)}",
        "#                Phi                 Px                  Py                  Pz",
        f"{_f(phi)}{_f(px)}{_f(py)}{_f(pz)}",
    ]
    # Card 5 has Ihkt only for the physically-stabilized ISOLID 24 (and the
    # /DEF_SOLID-default 0); other formulations read just deltaT_min + Istrain.
    if isolid in (0, 24):
        lines += ["#         deltaT_min   Istrain      Ihkt",
                  f"{_f(0.0)}{_i(istrain)}{_i(0)}"]
    else:
        lines += ["#         deltaT_min   Istrain",
                  f"{_f(0.0)}{_i(istrain)}"]
    lines.append(HDR)
    return lines


def _ortho_skew_axes(vec, phi_deg: float = 0.0):
    """Build the /SKEW/FIX (Y', Z') vector cards for a skew whose X' is *vec*.

    The starter reconstructs X' = Y' x Z', so any orthonormal (Y', Z') pair
    perpendicular to vec works; phi_deg spins that transverse pair about X'
    (LS-DYNA AOPT=3 BETA — direction 1 itself is unchanged). Returns
    (yaxis, zaxis), or None for a null vector."""
    import math
    x = _vnorm(vec)
    if x is None:
        return None
    # helper axis least aligned with X' → a well-conditioned cross product
    helpers = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    e = min(helpers, key=lambda h: abs(h[0]*x[0] + h[1]*x[1] + h[2]*x[2]))
    y = _vnorm(_vcross(e, x))
    z = _vcross(x, y)                       # unit by construction
    if phi_deg:
        c, s = math.cos(math.radians(phi_deg)), math.sin(math.radians(phi_deg))
        y, z = (tuple(c*y[i] + s*z[i] for i in range(3)),
                tuple(c*z[i] - s*y[i] for i in range(3)))
    return y, z


def _law128_ref_axis(mat) -> Tuple[Optional[Tuple[float, float, float]],
                                   float, Optional[str]]:
    """Map a *MAT_ANISOTROPIC_VISCOPLASTIC AOPT axis definition to a Radioss
    orthotropy reference direction. Returns ``(vec, phi, note)`` where ``vec`` is
    the material-1 direction for the /PROP Vx/Vy/Vz (``None`` → fall back to the
    default axis), ``phi`` the extra in-plane rotation, and ``note`` a short
    description for the warning. Only the two AOPT modes that reduce to a single
    global vector are mapped: AOPT=2 (the global a-vector) and AOPT=3 (vector v
    rotated by BETA). AOPT=0 (element nodes), 1 (point/radial) and 4 (cylindrical)
    have no single global direction and return ``None``.
    """
    aopt = int(round(mat.aopt)) if abs(mat.aopt - round(mat.aopt)) < 1e-6 else -1
    if aopt == 2 and any((mat.a1, mat.a2, mat.a3)):
        return (mat.a1, mat.a2, mat.a3), 0.0, \
            f"AOPT=2 global a-vector ({mat.a1:g}, {mat.a2:g}, {mat.a3:g})"
    if aopt == 3 and any((mat.v1, mat.v2, mat.v3)):
        return (mat.v1, mat.v2, mat.v3), mat.beta, \
            (f"AOPT=3 vector v ({mat.v1:g}, {mat.v2:g}, {mat.v3:g})"
             + (f" rotated by BETA={mat.beta:g}deg" if mat.beta else ""))
    return None, 0.0, None


def _emit_ortho_props(state: ConversionState, istrain: int) -> List[str]:
    """Emit the /PROP/TYPE9 (shell) or /PROP/TYPE6 (solid) for each LAW128 part
    assigned an orthotropic property id by _assign_ortho_props, with the material
    reference direction auto-mapped from the MAT_103 AOPT axis where possible."""
    if not state.ortho_prop_ids:
        return []
    shell_pids = {e.pid for e in state.shell_elems}
    tet10_by_pid: Dict[int, bool] = defaultdict(bool)
    solid_pids: Set[int] = set()
    for e in state.solid_elems:
        solid_pids.add(e.pid)
        if len(e.nodes) == 10:
            tet10_by_pid[e.pid] = True
    part_secids = {pid: (p.secid if p.secid > 0 else pid)
                   for pid, p in state.parts.items()}
    lines: List[str] = []
    for pid, prop_id in sorted(state.ortho_prop_ids.items()):
        secid = part_secids.get(pid, pid)
        title = f"LAW128_ORTHO_PROP_{prop_id} (part {pid})"
        part = state.parts.get(pid)
        mat = state.mat_aniso_visco.get(part.mid) if part else None
        vec, phi, note = _law128_ref_axis(mat) if mat else (None, 0.0, None)
        mapped = vec is not None      # read further down; the narrowing needs
        if vec is None:               # the `is None` test itself
            vec, phi = (1.0, 0.0, 0.0), 0.0
        # A uniform *ELEMENT_SHELL_BETA folded here by _fold_element_beta: the
        # starter takes an IGTYP 9 layer angle from GEO(10,PID) alone and never
        # adds the element's own Phi column (corthini.F:202).
        phi += state.part_beta_fold.get(pid, 0.0)
        if pid in shell_pids:
            if mapped:
                state.warn(
                    f"/PROP for LAW128 part {pid}: orthotropy reference "
                    f"direction auto-mapped from the material {note} → "
                    f"Vx/Vy/Vz=({vec[0]:g}, {vec[1]:g}, {vec[2]:g})"
                    + (f", Phi={phi:g}" if phi else "") + ".")
            else:
                reason = (f"AOPT={mat.aopt:g}" if mat else "the material")
                state.warn(
                    f"/PROP for LAW128 part {pid}: {reason} axis definition "
                    "has no single global vector (element-node, point-radial "
                    "or cylindrical system) — reference direction defaulted "
                    "to GLOBAL X (Vx=1,0,0). Set Vx/Vy/Vz + Phi on the /PROP "
                    "to your orthotropy/build axis.")
            sec = state.sec_shells.get(secid) or SectionShell(secid, "", 2, 3, 0.0)
            lines += _emit_prop_type9(prop_id, title, sec, state.is_implicit,
                                      istrain, state, refvec=vec, phi=phi)
        elif pid in solid_pids:
            # Solids get the orthotropy frame from a dedicated /SKEW/FIX
            # (Ip=0 + skew_ID → starter's direct-skew branch): material dir 1
            # = skew X' for EVERY element. The vector-projection alternative
            # (Ip=11) tilts dir 1 into each element's local r-s plane — on a
            # free tet mesh that scatters the direction element-by-element
            # (and elements whose plane is exactly normal to the vector fall
            # back to a mesh edge: starter WARNING 811).
            axes = _ortho_skew_axes(vec, phi)
            # Reserved on the STATE, not a local set: writer/composites.py
            # mints its AOPT=2 skews the same way in the same pass, and an id
            # only one of them knows about is an ERROR 79 waiting to happen.
            skew_id = state.reserve_skew_id(prop_id)
            if mapped:
                state.warn(
                    f"/PROP for LAW128 part {pid}: orthotropy axes taken from "
                    f"the material {note} via /SKEW/FIX {skew_id} (X'="
                    f"({vec[0]:g}, {vec[1]:g}, {vec[2]:g}) exactly, for every "
                    "element" + (f"; BETA={phi:g}deg spins the transverse "
                                 "2/3 axes about X'" if phi else "") + ").")
            else:
                reason = (f"AOPT={mat.aopt:g}" if mat else "the material")
                state.warn(
                    f"/PROP for LAW128 part {pid}: {reason} axis definition "
                    "has no single global vector (element-node, point-radial "
                    "or cylindrical system) — orthotropy defaulted to GLOBAL "
                    f"X via /SKEW/FIX {skew_id}. Edit that skew's axes to set "
                    "your orthotropy/build direction.")
            lines += _emit_skew_fix(skew_id, f"LAW128_ORTHO_SKEW_{skew_id}",
                                    (0.0, 0.0, 0.0), axes[0], axes[1])
            sec = state.sec_solids.get(secid)
            itetra10 = 1000 if tet10_by_pid.get(pid) else 0
            lines += _emit_prop_type6(prop_id, title, sec, itetra10, istrain,
                                      skew_id=skew_id)
    return lines


def _emit_hourglass_props(state: ConversionState, istrain: int) -> List[str]:
    """Emit the dedicated per-part /PROP/SOLID or /PROP/SHELL for each part that
    _assign_hourglass_props split out — a copy of its section prop (same
    geometry fields: Iale/Itetra10/nip/thick) stamped with the resolved
    part-specific hourglass h/Isolid (solid) or Hm/Hf/Hr (shell). Isolid/Ishell
    otherwise stay ELFORM-derived, re-computed here from the part's section."""
    if not state.hourglass_prop_ids:
        return []
    part_secids = {pid: (p.secid if p.secid > 0 else pid)
                   for pid, p in state.parts.items()}
    solid_pids = {e.pid for e in state.solid_elems}
    shell_pids = {e.pid for e in state.shell_elems}
    tet10_by_pid: Dict[int, bool] = defaultdict(bool)
    for e in state.solid_elems:
        if len(e.nodes) == 10:
            tet10_by_pid[e.pid] = True
    # A split /PROP may be shared by several sibling parts (same SECID + same
    # effective hourglass); emit it ONCE, listing all its parts in the title.
    pids_by_prop: Dict[int, List[int]] = defaultdict(list)
    for pid, prop_id in state.hourglass_prop_ids.items():
        pids_by_prop[prop_id].append(pid)
    lines: List[str] = []
    emitted: Set[int] = set()
    for pid, prop_id in sorted(state.hourglass_prop_ids.items()):
        if prop_id in emitted:
            continue
        emitted.add(prop_id)
        secid = part_secids.get(pid, pid)
        coeff, iso_over = state.hourglass_prop_vals.get(pid, (None, None))
        siblings = sorted(pids_by_prop[prop_id])
        title = (f"HG_PROP_{prop_id} (part{'s' if len(siblings) > 1 else ''} "
                 f"{','.join(map(str, siblings))})")
        # solid-first, matching _assign_hourglass_props' family selection.
        if pid in solid_pids:
            sec = state.sec_solids.get(secid)
            isolid = (0 if (sec and sec.iale)
                      else (_elform_to_isolid(sec.elform) if sec else 17))
            if iso_over is not None:
                isolid = iso_over
            iale = sec.iale if sec else 0
            itetra10 = 1000 if tet10_by_pid.get(pid) else 0
            # A /XREF or /MAT/LAW95 part split out by the hourglass overlay
            # keeps the Ismstr=10 its formulation requires (starter ERROR 2013
            # for /XREF; the starter force-promotes LAW95 element groups with
            # WARNING 1200 anyway). The split prop may be shared by siblings —
            # any such sibling promotes it, and siblings that are neither
            # /XREF nor LAW95 are dragged along: warned, mirroring the
            # shared-section path (natively they would keep their default).
            promoters = [
                p for p in siblings
                if p in state.xref_part_ids
                or (state.parts.get(p) is not None
                    and state.parts[p].mid in state.mat_hyper_rubber
                    and state.mat_hyper_rubber[state.parts[p].mid].n == 0)]
            ismstr = 10 if promoters else 0
            dragged = sorted(p for p in siblings if p not in promoters)
            if promoters and dragged:
                state.warn(
                    f"hourglass-split /PROP/SOLID {prop_id}: part(s) {dragged} "
                    f"share it with /XREF or /MAT/LAW95 part(s) "
                    f"{sorted(promoters)}, so they also switch to Ismstr=10 "
                    "(total-strain formulation) — natively they would keep "
                    "the default. Give the /XREF or LAW95 parts their own "
                    "*SECTION_SOLID or *HOURGLASS to keep the others "
                    "unchanged.")
            if ismstr == 10:
                state.ismstr10_solid_pids.update(siblings)   # see above
            lines += _emit_prop_solid(prop_id, title, isolid, iale, itetra10,
                                      istrain, hcoef=coeff, ismstr=ismstr)
        elif pid in shell_pids:
            sec = state.sec_shells.get(secid)
            ishell = (_elform_to_ishell(sec.elform, state.is_implicit,
                                        state.options.shell_default_ishell) if sec
                      else _elform_to_ishell(2, state.is_implicit,
                                             state.options.shell_default_ishell))
            nip = max(2, sec.nip) if sec else 2
            thick = sec.t1 if sec else 0.0
            lines += _emit_prop_shell(prop_id, title, ishell, nip, istrain,
                                      thick, hcoef=coeff)
    return lines


def _emit_prop_beam(sec: SectionBeam) -> List[str]:
    return [
        f"/PROP/BEAM/{sec.secid}",
        sec.title or f"PROP_{sec.secid}",
        "#             Ismstr",
        "                   0",
        "#                 dm                  df",
        "                   0                   0",
        "#               Area                 Iyy                 Izz                 Ixx",
        f"{_f(sec.area)}{_f(sec.iyy)}{_f(sec.izz)}{_f(sec.ixx)}",
        "# OmegaDof    Ishear",
        "   000 000         0",
        HDR,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# /PROP/BEAM (IGTYP 3) material compatibility
# ─────────────────────────────────────────────────────────────────────────────

# The Radioss laws /PROP/BEAM accepts. The gate is on the MATERIAL, not the
# property: every law declares a PROP_BEAM class through INIT_MAT_KEYWORD —
# 1 BEAM_CLASSIC (TYPE3 only), 2 BEAM_INTEGRATED (TYPE18 only), 3 BEAM_ALL
# (init_mat_keyword.F:251-258) — and IGTYP 3 requires 1 or 3:
#
#     CASE (3)
#       IF (MAT_PARAM(IMAT)%PROP_BEAM /= 1 .AND.
#    .      MAT_PARAM(IMAT)%PROP_BEAM /= 3) COMPAT_PROP = .FALSE.
#         — check_mat_elem_prop_compatibility.F:379-381
#
# Grepping every INIT_MAT_KEYWORD call under starter/source/materials/ gives the
# COMPLETE list (10 call sites, all unconditional): BEAM_CLASSIC = LAW1
# (hm_read_mat01.F:148); BEAM_ALL = LAW0 (mat00:133), LAW2 in all three of its
# readers — _jc:381, _zerilli:342, _predef:392 — LAW13 (mat13:128) and LAW44
# (mat44:319); BEAM_INTEGRATED = LAW34 (mat34:162), LAW36 (mat36:360) and
# LAW71 (mat71:251). Every OTHER law leaves PROP_BEAM at its 0 default
# (ini_mat_elem.F:89) and so fails both beam properties.
_TYPE3_BEAM_LAWS = frozenset({0, 1, 2, 13, 44})

# ... and the three that are TYPE18-only, which fail TYPE3 one step LATER than
# a PROP_BEAM=0 law and therefore under a different error id (see the warning).
_TYPE18_ONLY_BEAM_LAWS = frozenset({34, 36, 71})

# Classification of the laws the metal-plasticity-2 batch adds, read from the
# same INIT_MAT_KEYWORD call sites in the 2026-05-20 starter tree. NONE of them
# is beam-capable, so neither set above changes and the existing
# "no beam keyword at all — starter ERROR 3046" message is already the right
# one for all four:
#   LAW52  hm_read_mat52.F:238-241   HOOK, SHELL_ISOTROPIC, SOLID_ISOTROPIC
#   LAW66  hm_read_mat66.F:326-329   ELASTO_PLASTIC, SHELL_ISOTROPIC,
#                                    SOLID_ISOTROPIC, SPH
#   LAW121 hm_read_mat121.F:277-285  ELASTO_PLASTIC, INCREMENTAL,
#                                    LARGE_STRAIN, HOOK, SOLID_ISOTROPIC,
#                                    SHELL_ISOTROPIC, SPH
#   LAW32  hm_read_mat32.F:247-252   ELASTO_PLASTIC, HILL, ORTHOTROPIC,
#                                    SHELL_ORTHOTROPIC  — no solid class
#                                    either, so *MAT_122 rides the same
#                                    /PROP/TYPE9 split and solid-part refusal
#                                    as LAW43 (writer/composites.py).
# LAW2 (*MAT_012's target) is BEAM_ALL in all three of its readers and is
# already in _TYPE3_BEAM_LAWS, so a *MAT_012 beam part converts and runs.
#
# Classification of the laws the VISCOELASTIC batch adds, read from the same
# INIT_MAT_KEYWORD call sites in the 2026-05-20 starter tree. Neither frozenset
# above changes: LAW34 is already listed as TYPE18-only, and none of the other
# three declares any beam class at all, so the existing "no beam keyword at all
# — starter ERROR 3046" message is already the right one for them:
#   LAW34  hm_read_mat34.F:155-162   HOOK, SHELL_ISOTROPIC, SOLID_ISOTROPIC,
#                                    SPH, TRUSS, BEAM_INTEGRATED  — the only
#                                    beam-capable law in this batch, and it is
#                                    already in _TYPE18_ONLY_BEAM_LAWS, so a
#                                    *MAT_006 beam part reaches the TYPE18
#                                    routing in writer/beams.py unchanged.
#   LAW40  hm_read_mat40.F:182-185   HOOK, SOLID_ISOTROPIC, SPH — no shell
#                                    class either, so a *MAT_061 on a SHELL
#                                    part is ERROR 3046 as well; warned by
#                                    _resolve_mat061, since neither the beam
#                                    gate here nor any property pass sees it.
#   LAW42  hm_read_mat42.F:265-271   INCOMPRESSIBLE, TOTAL, HOOK,
#                                    SHELL_ISOTROPIC, SOLID_ISOTROPIC, SPH
#   LAW88  hm_read_mat88.F90:669-679 COMPRESSIBLE/INCOMPRESSIBLE, TOTAL,
#                                    LARGE_STRAIN, HOOK,
#                                    SOLID_BRICK_ISOTROPIC, SHELL_ISOTROPIC
#
# Classification of the laws the ADHESIVES/COHESIVE batch adds, read from the
# same INIT_MAT_KEYWORD call sites in the 2026-05-20 starter tree. NONE of
# the four declares any BEAM_* keyword (or any SHELL_* class either — these
# are solid-only laws), so neither frozenset above changes and the existing
# "no beam keyword at all — starter ERROR 3046" message is already the right
# one for a beam part on any of them:
#   LAW116 hm_read_mat116.F:236,239    HOOK; SOLID_COHESIVE
#   LAW117 hm_read_mat117.F:208,211    HOOK; SOLID_COHESIVE
#   LAW120 hm_read_mat120.F:257-262    COMPRESSIBLE, INCREMENTAL,
#                                      LARGE_STRAIN, HOOK; SOLID_ALL
#   LAW169 hm_read_mat169.F90:191      SOLID_COHESIVE (no HOOK call)
# The SOLID-side compatibility these classes encode is enforced/warned by
# the /PROP/TYPE43 routing (_cohesive_solid_secids/_warn_type43_pairings
# above): SOLID_COHESIVE lives ONLY on TYPE43, and TYPE43 takes ONLY
# PROP_SOLID classes 4/6/7 (ERROR 3047 either way around).
#
# Classification of the laws the FOAM batch adds, read from the same
# INIT_MAT_KEYWORD call sites in the 2026-05-20 starter tree. NONE of the
# five declares any BEAM_* keyword, so neither frozenset above changes and
# the existing "no beam keyword at all — starter ERROR 3046" message is
# already the right one for a beam part on any of them:
#   LAW21  hm_read_mat21.F:213-224    ELASTO_PLASTIC, DRUCKER, EOS,
#                                     HYDRO_EOS; SOLID_ISOTROPIC, SPH — no
#                                     shell class either, so *MAT_005 on a
#                                     SHELL part is ERROR 3046 as well;
#                                     warned by _resolve_mat_soil_and_foam.
#   LAW50  hm_read_mat50.F90:430-435  HOOK, COMPRESSIBLE, SMALL_STRAIN,
#                                     ORTHOTROPIC; SOLID_ISOTROPIC — the
#                                     shell-part refusal for *MAT_126 lives
#                                     in _assign_composite_props (the part
#                                     never gets an orthotropic /PROP).
#   LAW62  hm_read_mat62.F:265-274    TOTAL, IN/COMPRESSIBLE, HOOK;
#                                     SHELL_ISOTROPIC + SOLID_ISOTROPIC —
#                                     the only shell-capable law of the
#                                     batch, so a *MAT_177 shell part
#                                     converts and runs.
#   LAW90  hm_read_mat90.F:225-233    TOTAL, IN/COMPRESSIBLE, HOOK;
#                                     SOLID_ISOTROPIC only; warned by
#                                     _resolve_mat_low_density_viscous_foam.
#   LAW115 hm_read_mat115.F:313-319   COMPRESSIBLE, INCREMENTAL,
#                                     LARGE_STRAIN, HOOK; SOLID_ISOTROPIC
#                                     only; warned by
#                                     _resolve_mat_deshpande_fleck.
#
# Classification of the TABULATED JOHNSON-COOK batch's law, read from the
# same INIT_MAT_KEYWORD call sites in the 2026-05-20 starter tree. No BEAM_*
# keyword, so neither frozenset above changes and the existing "no beam
# keyword at all — starter ERROR 3046" message is already the right one for
# a *MAT_224 beam part:
#   LAW109 hm_read_mat109.F:182-191   ELASTO_PLASTIC, INCREMENTAL,
#                                     LARGE_STRAIN, HOOK, EOS (conditional),
#                                     SHELL_ISOTROPIC, SOLID_ISOTROPIC, SPH
#                                     — shell- and solid-capable, beam-
#                                     incompatible with BOTH /PROP/TYPE3
#                                     and /PROP/TYPE18.
#
# Classification of the laws the IMPACT/BLAST batch adds, read from the same
# INIT_MAT_KEYWORD call sites in the 2026-05-20 starter tree. NONE of the
# three declares any BEAM_* keyword — nor any SHELL_* class, so all three are
# solid/SPH-only — so neither frozenset above changes and the existing "no
# beam keyword at all — starter ERROR 3046" message is already the right one
# for a beam part on any of them:
#   LAW79  hm_read_mat79.F:233-234    SOLID_ISOTROPIC, SPH — the shortest
#                                     class list in the tree; the shell-part
#                                     refusal for *MAT_110 is warned by
#                                     _resolve_mat110 (materials.py).
#   LAW126 hm_read_mat126.F90:247-255 SOLID_ISOTROPIC, SPH, COMPRESSIBLE,
#                                     INCREMENTAL, LARGE_STRAIN, HYDRO_EOS,
#                                     ISOTROPIC — HYDRO_EOS here is a
#                                     pressure-treatment capability tag, NOT
#                                     a requirement for a companion /EOS
#                                     block (LAW126 reads its own K1/K2/K3);
#                                     warned by _resolve_mat111.
#   LAW6   hm_read_mat06.F:185-194    EOS, HYDRO_EOS, INCOMPRESSIBLE,
#                                     SOLID_POROUS, SPH — note SOLID_POROUS,
#                                     not SOLID_ISOTROPIC: both map to
#                                     PROP_SOLID classes that include
#                                     /PROP/TYPE14 (init_mat_keyword.F:212-231
#                                     gives ISOTROPIC->1 = TYPE 6/14/20/21/22
#                                     and POROUS->5 = TYPE 14/15), so an
#                                     ordinary solid part is fine, but LAW6 is
#                                     NOT compatible with the orthotropic /
#                                     composite solid properties TYPE 6/20/21/
#                                     22 (ERROR 3047) the way LAW79/LAW126
#                                     are. Warned by _resolve_mat_elastic_fluid.
#                                     (hm_read_mat06_keps.F:217-226 is the k-eps
#                                     variant, same class set — not converted.)


def _target_mat_law(state: ConversionState, mid: int) -> Optional[int]:
    """The Radioss law number k2rad will actually EMIT for LS-DYNA material
    *mid* — ``None`` when no ``/MAT`` is written for it at all (a spring/damper
    material that lives entirely inside a ``/PROP/TYPE4``, a ``*MAT_SPOTWELD``
    fully absorbed by its ``/PROP/TYPE13`` connector, or an id the deck never
    defines).

    This follows the CONVERTER's routing, not the LS-DYNA material number, so
    it stays right where the two disagree — ``*MAT_024`` and
    ``*MAT_POWER_LAW_PLASTICITY`` are different keywords that land on the same
    ``/MAT/LAW36``, and one keyword can split: ``*MAT_JOHNSON_COOK`` is LAW2 or
    LAW4 depending on whether an ``*EOS_*`` is attached, ``*MAT_NULL`` is
    ``/MAT/VOID`` (LAW0) alone but the ``/MAT/LAW6`` hydro carrier with one, and
    each rubber keyword picks its law off a curve/order field. Order and
    conditions mirror ``_make_materials`` and ``_make_composite_materials``
    exactly.

    The ONE mid → law map in the codebase: ``inistate.py::_resolve_xref_parts``
    reads it for the starter's solid-/XREF law whitelist too. It used to keep a
    private 7-family copy that returned ``None`` for ``mat_rigid`` and the
    ``mat_spotweld`` fallback, both really LAW1 and really on that whitelist, so
    both lost their ``/XREF`` under a warning about a law violation that did not
    exist. Anything added here therefore reaches both callers — check the /XREF
    gate when adding a family that lands on LAW 1/35/38/42/70/88/90.

    Not mapped, because no ``*PART`` can name it: the ``/MAT/LAW6`` carrier a
    bare ``*EOS_*`` with no companion ``*MAT_NULL`` gets under the EOSID, and
    the ``/MAT/LAW51`` of an ALE multi-material group, whose id is synthesized
    by ``next_mat_id()`` and so is guaranteed not to be any deck MID.
    """
    if mid in state.mat_elastic:
        return 1                                   # /MAT/ELAST
    if mid in state.mat_plas_tab:
        return 36                                  # *MAT_024/123 → PLAS_TAB
    if mid in state.mat_plas_kin:
        # *MAT_003 → COWPER, EXCEPT on a material whose every part carries SPH
        # particles: LAW44 is not SPH-declared (starter ERROR 3046), so the
        # expressible cases are re-routed to LAW2. The ONE eligibility test
        # lives with the emitter — if these two disagreed, writer/sph.py's
        # compatibility report would warn about an error the emitted deck no
        # longer raises, or stay silent about one it does.
        from .materials import _plas_kin_law2_eligible
        if _plas_kin_law2_eligible(state, state.mat_plas_kin[mid]):
            return 2                               # /MAT/LAW2 (PLAS_JOHNS)
        return 44                                  # *MAT_003 → COWPER
    m = state.mat_johnson_cook.get(mid)
    if m is not None:
        # _resolve_mat_johnson_cook sets use_law4 when an *EOS_* binds to the
        # material (MAT_015 only); MAT_099 and the EOS-less MAT_015 stay LAW2.
        return 4 if m.use_law4 else 2
    if mid in state.mat_aniso_visco:
        return 128                                 # *MAT_103 → HILL_VISC_PLAST
    if mid in state.mat_rigid:
        return 1                                   # /MAT/ELAST for the /RBODY
    if mid in state.mat_null:
        # A bare *MAT_NULL is /MAT/VOID (LAW0); one that carries a supported
        # *EOS_* — by the shared-id pairing or a *PART EOSID binding — becomes
        # the /MAT/HYD_VISC (LAW6) carrier instead. Same tests as
        # _make_materials / _make_explosive_and_eos_materials, INCLUDING their
        # seam: an *EOS_JWL id suppresses the /MAT/VOID (it is in `eos_mids`)
        # but the LAW6 loop walks `eos_cards` only, so a *MAT_NULL carrying
        # nothing but a companion-less *EOS_JWL gets NO /MAT at all.
        if mid in state.mat_high_explosive:
            return 5
        if mid in state.eos_cards or mid in _null_part_eos_bindings(state):
            return 6
        if mid in state.eos_jwl:
            return None
        return 0
    if mid in state.mat_power_law:
        return 36                                  # *MAT_018 → PLAS_TAB fit
    if mid in state.mat_samp:
        return 76                                  # *MAT_187 → SAMP
    if mid in state.mat_crushable_foam:
        return 50                                  # *MAT_063
    if mid in state.mat_low_density_foam:
        return 38                                  # *MAT_057
    if mid in state.mat_fu_chang_foam:
        return 70                                  # *MAT_083
    if mid in state.mat_honeycomb:
        return 28                                  # *MAT_026
    # Foam batch. Only MAT_073's LAW90 is on the solid-/XREF whitelist this
    # function feeds — the entry alone makes *MAT_073 parts newly RECEIVE a
    # /XREF (and Ismstr=10) from *INITIAL_FOAM_REFERENCE_GEOMETRY; LAW21/50/
    # 62/115 are off-whitelist, so their parts warn-skip NAMING the law
    # (without these entries the gate would misreport "no /MAT at all").
    # A *MAT_177 with LCID>0 warn-skips at parse and never fills its dict,
    # so it correctly reads as "no /MAT" here — like the MAT_240 variants.
    if mid in state.mat_soil_and_foam:
        return 21                                  # *MAT_005
    if mid in state.mat_low_density_viscous_foam:
        return 90                                  # *MAT_073
    if mid in state.mat_modified_honeycomb:
        return 50                                  # *MAT_126
    if mid in state.mat_deshpande_fleck:
        return 115                                 # *MAT_154
    if mid in state.mat_hill_foam:
        return 62                                  # *MAT_177 (LCID=0 branch)
    if mid in state.mat_blatz_ko:
        return 42                                  # *MAT_007 → OGDEN form
    m = state.mat_mooney_rivlin.get(mid)
    if m is not None:
        return 69 if m.use_law69 else 42           # curve branch vs constants
    m = state.mat_ogden.get(mid)
    if m is not None:
        return 69 if m.n > 0 else 42               # *MAT_077_O
    m = state.mat_hyper_rubber.get(mid)
    if m is not None:
        return 69 if m.n > 0 else 95               # *MAT_077_H
    # Metal plasticity batch 2. Placed to mirror _make_materials, which emits
    # these four after the hyperelastic loop and before the /MAT/LAW5.
    if mid in state.mat_iso_elas_plas:
        return 2                                   # *MAT_012 → PLAS_JOHNS
    if mid in state.mat_strain_rate_plas:
        return 121                                 # *MAT_019 → PLAS_RATE
    if mid in state.mat_gurson:
        return 52                                  # *MAT_120 → GURSON
    if mid in state.mat_plas_comp_tens:
        return 66                                  # *MAT_124
    # Viscoelastic batch. None of these five splits — each keyword has exactly
    # one target law — but LAW42 and LAW88 are both on the solid-/XREF
    # whitelist inistate.py reads through this function, so an
    # *INITIAL_FOAM_REFERENCE_GEOMETRY deck newly reaches those parts.
    if mid in state.mat_viscoelastic:
        return 34                                  # *MAT_006 → BOLTZMAN
    if mid in state.mat_kelvin_maxwell:
        return 40                                  # *MAT_061 → KELVINMAX
    if mid in state.mat_general_visco:
        return 42                                  # *MAT_076 → OGDEN carrier
    if mid in state.mat_simplified_rubber:
        return 88                                  # *MAT_181/183
    if mid in state.mat_soft_tissue:
        return 42                                  # *MAT_091/092 → OGDEN
    # Adhesives / cohesive batch. None of the four splits (one law per
    # keyword; a MAT_240 option variant is warn-skipped at parse and never
    # fills its dict, so it correctly reads as "no /MAT" here). None of
    # 116/117/120/169 is on the solid-/XREF whitelist, so the gate in
    # inistate.py warn-skips such parts NAMING the law — without these
    # entries it would misreport them as having no /MAT at all.
    if mid in state.mat_cohesive_mixed_mode:
        return 117                                 # *MAT_138
    if mid in state.mat_arup_adhesive:
        return 169                                 # *MAT_169
    if mid in state.mat_cohesive_mm_epr:
        return 116                                 # *MAT_240 (option-free)
    if mid in state.mat_toughened_adhesive:
        return 120                                 # *MAT_252 → TAPO
    # Tabulated Johnson-Cook batch. LAW109 is NOT on the solid-/XREF
    # whitelist this function feeds, so a MAT_224 part hit by
    # *INITIAL_FOAM_REFERENCE_GEOMETRY warn-skips NAMING the law (without
    # the entry the gate would misreport "no /MAT at all"). The _GYS /
    # _ORTHO_PLASTICITY variants are warn-skipped at parse and never fill
    # the dict, so they correctly read as "no /MAT" here — the MAT_240
    # variant pattern.
    if mid in state.mat_tabulated_jc:
        return 109                                 # *MAT_224 → LAW109
    # Impact / blast batch. None of the three splits (one law per keyword) and
    # NONE of LAW79 / LAW126 / LAW6 is on the solid-/XREF whitelist, so the
    # gate in inistate.py warn-skips such parts NAMING the law — without these
    # entries it would misreport them as having no /MAT at all. The fluid is
    # deliberately its own container: a plain *MAT_ELASTIC stays on
    # `mat_elastic` above and keeps LAW1 (which IS whitelisted), so adding the
    # _FLUID variant cannot move any existing deck's /XREF decisions.
    if mid in state.mat_jh_ceramics:
        return 79                                  # *MAT_110 → JOHN_HOLM
    if mid in state.mat_jh_concrete:
        return 126                                 # *MAT_111 → LAW126
    if mid in state.mat_elastic_fluid:
        return 6                                   # *MAT_001_FLUID → HYD_VISC
    # Rare materials batch. LAW71 is NOT on the solid-/XREF whitelist, so this
    # entry makes that gate warn-skip a *MAT_030 solid part NAMING the law
    # instead of misreporting it as having no /MAT; it is also what routes the
    # part through _warn_beam_type3_material's TYPE18-only arm and through the
    # SPH ERROR-3046 report (LAW71 declares HOOK / SHELL_ISOTROPIC /
    # SOLID_ISOTROPIC / BEAM_INTEGRATED and nothing else — hm_read_mat71.F:
    # 247-251). *MAT_156 and *MAT_S15 deliberately have NO entry: both live
    # entirely inside a /PROP/TYPE46 and emit no /MAT, so `None` (= the
    # *MAT_Sxx spring answer) is the correct one for them.
    if mid in state.mat_shape_memory:
        return 71                                  # *MAT_030 → LAW71 (SMA)
    # R14 triage batch. *MAT_004 and *MAT_270 both land on /MAT/LAW106, and the
    # RESOLVED registry is the one to test: a source card the resolver refused
    # (fewer than two temperature points, RO <= 0, an unresolvable LCEM) emits
    # no /MAT at all, so `None` is the right answer for it. LAW106 is NOT on
    # the starter's solid-/XREF law whitelist, so this entry makes that gate
    # warn-skip such a part NAMING the law instead of misreporting it as
    # having no /MAT; it also routes the part through the /PROP/BEAM TYPE3
    # report, which is correct — hm_read_mat106.F90:293-295 declares
    # SOLID_ISOTROPIC, SHELL_ISOTROPIC and SPH and nothing else, so a LAW106
    # beam part IS starter ERROR 3046.
    if mid in state.mat_law106:
        return 106                                 # *MAT_004 / *MAT_270
    # *MAT_010 -> /MAT/LAW3 (HYDPLA). Declares ELASTO_PLASTIC, EOS, HYDRO_EOS,
    # SOLID_ISOTROPIC and SPH (hm_read_mat03.F:214-225) — no shell and no beam
    # class — and LAW3 is already in writer/sph.py's _SPH_COMPATIBLE_LAWS, so
    # this entry is what makes the SPH and /PROP/BEAM compatibility reports
    # (and the solid-/XREF gate, whose whitelist LAW3 is NOT on) name the law
    # instead of reporting "no /MAT at all".
    if mid in state.mat_law3:
        return 3                                   # *MAT_010 -> HYDPLA
    # *MAT_140 -> /MAT/VOID, the same law a bare *MAT_NULL takes. The entry
    # matters to _resolve_ale_submaterials, which drops law 0 from the
    # /MAT/LAW51 phase list (fill_buffer_51.F:210 does not accept it, and
    # Radioss's void is the undeclared balance of the volume fractions).
    if mid in state.mat_vacuum:
        return 0                                   # *MAT_140 -> /MAT/VOID
    if mid in state.mat_high_explosive:
        return 5                                   # +/EOS/JWL
    if mid in state.mat_orthotropic:
        return 93                                  # *MAT_002 → ORTH_HILL
    if mid in state.mat_enhanced_composite:
        return 127                                 # *MAT_054/055
    if mid in state.mat_composite_damage:
        # *MAT_022 splits by ELEMENT KIND — writer/composites._mat022_law is
        # the ONE router, shared with the material writer and the /PROP split,
        # so the law, the property class and every warning agree.
        from .composites import _mat022_law
        return _mat022_law(state, mid)             # 25 (+/FAIL/CHANG) or 127
    # Airbag fabric. *MAT_FABRIC splits on FORM + the card-7 curves
    # (writer/fabric.py::_fabric_law is the ONE predicate; the property branch
    # reads the same function, so law and property cannot disagree). NEITHER
    # LAW19 nor LAW58 is on the solid-/XREF whitelist — but a fabric part is a
    # SHELL part and inistate._resolve_xref_parts' shell arm keeps it with no
    # law check at all, so this entry never changes a /XREF decision; what it
    # does is stop that gate (and the /PROP/BEAM and SPH compatibility reports)
    # reporting "no /MAT at all" for a material the deck plainly defines.
    m = state.mat_fabric.get(mid)
    if m is not None:
        from .fabric import _fabric_law
        return _fabric_law(m)                      # *MAT_034 → LAW19 or LAW58
    # Seatbelts. Which law a *MAT_SEATBELT becomes is decided by the PROPERTY
    # its parts carry, not by the keyword (common._seatbelt_mat_law is the ONE
    # router, shared with the material writer and the property writer). Neither
    # LAW114 nor LAW119 is on the solid-/XREF whitelist and neither can be on a
    # solid part at all, so this entry never changes a /XREF decision; what it
    # does is stop that gate - and the /PROP/BEAM and SPH compatibility reports
    # - saying "no /MAT at all" about a material the deck plainly defines.
    law = _seatbelt_mat_law(state, mid)
    if law is not None:
        return law                                 # *MAT_SEATBELT / *MAT_B01
    if mid in state.mat_transverse_aniso:
        return 43                                  # *MAT_037 → HILL_TAB
    m = state.mat_hill_3r.get(mid)
    if m is not None:
        # *MAT_122: HR=2 (exponential hardening) takes the analytic /MAT/LAW32
        # instead of the tabular LAW43 — set by _resolve_hill_3r, which runs
        # inside _resolve_composites, i.e. AFTER _resolve_xref_parts. That
        # caller therefore always sees 43 here; harmless, because neither 32
        # nor 43 is in the solid-/XREF law whitelist, so the part is
        # warn-skipped either way.
        return 32 if m.use_law32 else 43
    if mid in state.mat_laminated_glass:
        return 27                                  # *MAT_032 → PLAS_BRIT pair
    if mid in state.mat_spotweld:
        # MAT_100 normally has NO /MAT at all — the material lives entirely in
        # the /PROP/TYPE13 connector and the /PART is written with mat_id 0.
        # _make_materials writes the /MAT/ELAST fallback only when some part on
        # the mid is not a pure-beam spotweld part, which is the same test.
        sw_pids = _spotweld_beam_pids(state)
        if any(p.mid == mid and pid not in sw_pids
               for pid, p in state.parts.items()):
            return 1
        return None
    # Discrete SPRING/DAMPER (S01/S03/S04/S05/S06/S08/D01) and DISCRETE-BEAM
    # (MAT_066/067/068/071/074/119/121/196, plus the seven with no Radioss
    # spring law) materials never get a /MAT of their own: the whole material
    # lives in the /PROP/TYPE4 / TYPE8 / TYPE13 connector and the /PART is
    # written with mat_id 0. Listed EXPLICITLY rather than left to fall through
    # to `return None` so that a future reader (and _resolve_xref_parts, which
    # shares this map) sees the routing stated, not inferred from an absence.
    if (mid in state.mat_spring_elastic or mid in state.mat_spring_nonlinear
            or mid in state.mat_damper_viscous
            or mid in state.mat_spring_elastoplastic
            or mid in state.mat_damper_nl_viscous
            or mid in state.mat_spring_general_nl
            or mid in state.mat_spring_inelastic
            # *MAT_MUSCLE (156) and *MAT_SPRING_MUSCLE (S15) join that list:
            # both live entirely in a /PROP/TYPE46 (SPR_MUSCLE) and their
            # /PART is written with mat_id 0 — verified on the starter, which
            # accepts mat_ID 0 on a TYPE46 spring part.
            or mid in state.mat_muscle
            or mid in state.mat_spring_muscle
            or mid in _discrete_beam_mids(state)):
        return None
    return None


def _warn_beam_type3_material(state: ConversionState,
                              part_secids: Dict[int, int],
                              connector_beam_pids: Set[int],
                              type3_secids: Set[int]) -> None:
    """Name every beam part whose material converts to a law ``/PROP/BEAM``
    rejects — the deck is unrunnable and k2rad said nothing about it.

    ``_make_properties`` writes a ``/PROP/BEAM`` (IGTYP 3) for every
    ``*SECTION_BEAM`` regardless of the material on the parts using it, and the
    starter accepts that only for ``PROP_BEAM`` 1 or 3, i.e. LAW0/1/2/13/44
    (``_TYPE3_BEAM_LAWS``). ``*MAT_PIECEWISE_LINEAR_PLASTICITY`` — by some
    distance the most common LS-DYNA beam material — routes to ``/MAT/LAW36``,
    which is BEAM_INTEGRATED, so the single most likely beam deck there is
    converted straight into an ERROR TERMINATION with no warning at all.

    Measured on ``starter_win64`` (nt=6), one ``*SECTION_BEAM`` ELFORM=2 and two
    ``*ELEMENT_BEAM`` per deck, everything else held constant:

    ===========================  =====  ========================================
    beam material                law    starter
    ===========================  =====  ========================================
    ``*MAT_ELASTIC``             1      NORMAL TERMINATION, 0 ERROR 0 WARNING
    ``*MAT_JOHNSON_COOK``        2      0 ERROR (warnings unrelated)
    ``*MAT_PLASTIC_KINEMATIC``   44     NORMAL TERMINATION, 0 ERROR 0 WARNING
    ``*MAT_PIECEWISE_LIN…``      36     3 ERRORS: 3047 + one 745 per element
    ``*MAT_BLATZ-KO_RUBBER``     42     1 ERROR: 3046
    ===========================  =====  ========================================

    The LAW36 run reads, verbatim::

        ERROR ID :   3047
        ** ERROR IN MATERIAL/PROPERTY COMPATIBILITY
           PROPERTY ID 2  OF TYPE 3  IS NOT COMPATIBLE WITH MATERIAL ID 1  OF TYPE 36
        ERROR ID :    745
        ** ERROR IN MATERIAL-PROPERTY COMPATIBILITY
           ON ELEMENT ID=11, PID TYPE 2 IS NOT COMPATIBLE WITH
           MATERIAL LAW 36

    and the LAW42 one::

        ERROR ID :   3046
        ** ERROR IN MATERIAL/ELEMENT COMPATIBILITY
           ELEMENTS OF TYPE BEAM ARE NOT COMPATIBLE WITH MATERIAL ID 1  OF TYPE 42

    **The two error ids are not interchangeable, and the split is structural.**
    A law that declares no beam keyword at all sits at ``PROP_BEAM == 0``, which
    fails the ELEMENT test (``IF (MAT_PARAM(IMAT)%PROP_BEAM == 0) COMPAT_ELEM =
    .FALSE.``, same file lines 153-155 / 342-343) and reports 3046 —
    material-vs-element, the property never enters it. Only a law that IS beam
    material but the WRONG class, i.e. the BEAM_INTEGRATED LAW34/36/71, passes
    the element test and fails the property one, and that is 3047; the legacy
    hard-coded pair check in ``initia.F:2806-2817`` fires ERROR 745 on the same
    combination one phase earlier, per element. So the warning names the id the
    user will actually read in their ``.out``.

    WARN-ONLY, deliberately — no auto-promotion to ``/PROP/TYPE18``:

    * A promotion is **not information-preserving**. ``*SECTION_BEAM`` ELFORM=2
      states four independent resultants (A, Iss, Itt, J) while ``/PROP/TYPE18``
      integrates a point cloud whose ``Ixx`` the starter *defines* as
      ``Iyy + Izz`` (``hm_read_prop18.F:289-301``) — the polar moment, which is
      the torsion constant only for a circular section. There is no point set
      that reproduces a general (A, Iss, Itt, J) quadruple, so promoting means
      inventing a cross-section and silently overwriting the deck's J.
    * It would rescue a **subset**. TYPE18 takes ``PROP_BEAM`` 2 or 3, so it
      covers LAW34/36/71 (and the LAW0/2/13/44 that already work) — but a beam
      on LAW38/42/50/70/76/95/127/128 declares no beam keyword at all and has
      no beam property in Radioss at either type. A warning that names the
      remedy covers every case; a promotion covers one third of them and leaves
      the rest failing exactly as before.
    * The ``/PROP/TYPE18`` machinery is being written on ``feat/integration-beam``
      right now (``writer/beams.py``, its own ``_type18_material`` gate for the
      opposite direction). Building a second copy here would collide head-on
      for no gain.

    The promotion is therefore named as a FOLLOW-UP: once that branch merges,
    a LAW34/36/71 beam part on a section whose ELFORM/CST implies a shape
    ``_constants_from_shape`` can integrate could be routed to TYPE18 by
    reusing that module — and this check is what tells us which parts qualify.

    Structured to survive that merge unchanged: it is driven by *type3_secids*,
    the sections that ACTUALLY emitted a ``/PROP/BEAM``, collected inside the
    emit loop. A section promoted to ``/PROP/TYPE18`` never enters the set, so
    it is never warned about — before the merge because nothing promotes, after
    it because the promoted ones ``continue`` past the collection point.
    """
    if not type3_secids:
        return
    # Parts with beam ELEMENTS only. Two reasons, both load-bearing: the
    # starter's compatibility loop runs per element GROUP, so an element-free
    # part contributes nothing to check (the lesson of the composite
    # element-free warning); and a *MAT_SPOTWELD beam part — or a
    # *SECTION_BEAM ELFORM=6 discrete-beam part — has already been turned into
    # /SPRING elements on a spring property by the time this runs.
    groups: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for pid in sorted({e.pid for e in state.beam_elems
                       if e.pid not in connector_beam_pids}):
        part = state.parts.get(pid)
        if part is None or part_secids.get(pid) not in type3_secids:
            continue
        law = _target_mat_law(state, part.mid)
        # None = k2rad emits no /MAT for this id, which is a different (and
        # already reported) problem; do not guess a law for it.
        if law is None or law in _TYPE3_BEAM_LAWS:
            continue
        groups[(part.mid, law)].append(pid)
    if not groups:
        return
    entries = []
    for (mid, law), pids in sorted(groups.items()):
        plural = "s" if len(pids) > 1 else ""
        entries.append(
            f"part{plural} " + ", ".join(str(p) for p in pids)
            + f" on mid {mid} (/MAT/LAW{law}, "
            + ("BEAM_INTEGRATED — starter ERROR 3047 plus one ERROR 745 per "
               "beam element" if law in _TYPE18_ONLY_BEAM_LAWS else
               "no beam keyword at all — starter ERROR 3046")
            + ")")
    state.warn(
        "/PROP/BEAM (TYPE3) material compatibility: " + "; ".join(entries)
        + ". The classic beam property accepts only PROP_BEAM 1 or 3 — "
        "/MAT/LAW0, LAW1, LAW2, LAW13 and LAW44 — and REJECTS everything "
        "else (check_mat_elem_prop_compatibility.F:379-381, the class set by "
        "INIT_MAT_KEYWORD in each law's reader). These beams do not degrade, "
        "they ERROR-TERMINATE the starter, so the converted deck will not run "
        "until the deck is changed: (a) state the section as an INTEGRATED "
        "beam — /PROP/TYPE18 takes PROP_BEAM 2, i.e. LAW34/36/71 — by adding "
        "an *INTEGRATION_BEAM rule and referencing it from *SECTION_BEAM card "
        "1 field 4 (QR/IRID, written as the NEGATIVE of the rule id); this "
        "warning is raised only for sections that really emit a /PROP/BEAM, "
        "so it disappears by itself once the rule converts, and if it still "
        "names the part afterwards then this k2rad did not convert the rule "
        "and only (b) is left. Or (b) move the part to a law the classic beam "
        "takes: *MAT_PLASTIC_KINEMATIC → /MAT/LAW44 is the closest "
        "elasto-plastic substitute for *MAT_PIECEWISE_LINEAR_PLASTICITY "
        "(bilinear hardening plus Cowper-Symonds rate), *MAT_ELASTIC → LAW1 "
        "and *MAT_JOHNSON_COOK → LAW2 for the rest. Note the law is k2rad's "
        "OWN routing, not the LS-DYNA material number: *MAT_024 and "
        "*MAT_POWER_LAW_PLASTICITY both land on LAW36.")


# ─────────────────────────────────────────────────────────────────────────────
# Starter: extra groups (node sets not already emitted)
# ─────────────────────────────────────────────────────────────────────────────

def _make_extra_groups(state: ConversionState) -> List[str]:
    emitted: Set[int] = {bc.nsid for bc in state.bcs_spcs}
    lines: List[str] = []
    for nsid, (title, nids) in sorted(state.node_sets.items()):
        if nsid not in emitted:
            lines += _emit_grnod_node(nsid, title, nids)
    return lines
