"""Starter mesh: nodes, skews, parts+elements, TET10 handling, properties, extra groups."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from ..state import (
    ConversionState,
    NodeData,
    ShellElem,
    SolidElem,
    BeamElem,
    SectionShell,
    SectionSolid,
    SectionBeam,
)
from ..topology import TET10_MIDEDGE as _TET10_MIDEDGE
from .common import (
    HDR,
    _discrete_part_ids,
    _elform_to_ishell,
    _elform_to_isolid,
    _emit_grnod_node,
    _f,
    _fmt_eid_list,
    _i,
    _ordered_unique_nodes,
    _spotweld_beam_pids,
    _vcross,
    _vnorm,
    _vsub,
)

__all__ = [
    "_make_nodes",
    "_emit_skew_fix",
    "_emit_skew_mov",
    "_make_skews",
    "_skew_axes_from_nodes",
    "_emit_skew_from_nodes",
    "_mov_third_pos",
    "_synthesize_vector_skews",
    "_emit_coord_vector_skew",
    "_emit_define_vector_skew",
    "_emit_sd_orientation_skew",
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
    "_make_parts_and_elements",
    "_make_properties",
    "_emit_prop_beam",
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

    # Surface dead output: *DEFINE_VECTOR has no k2rad consumer yet, and a
    # *DEFINE_SD_ORIENTATION that no *ELEMENT_DISCRETE references is unused too.
    # An unused /SKEW is harmless, but the moving (_NODES / IOP=2) forms also
    # injected a free helper node above — flag both so that extra node is not a
    # silent surprise (it would otherwise appear unexplained in the free-node
    # /BCS guard for implicit decks).
    referenced_sd = {e.vid for e in state.discrete_elems if e.vid}
    unref_vec = sorted(state.vector_skew_ids)             # no consumer exists
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
        cs = [state.nodes.get(e.nodes[k]) for k in range(4)]
        if any(c is None for c in cs):
            continue
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
    for e in state.beam_elems:
        ref.update(n for n in (e.n1, e.n2, e.n3) if n > 0)
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


def _make_parts_and_elements(state: ConversionState, progress=None) -> List[str]:
    if not state.parts:
        return []
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

    beams_by_pid: Dict[int, List[BeamElem]] = defaultdict(list)
    for e in state.beam_elems:
        beams_by_pid[e.pid].append(e)

    # Connector parts (discrete springs/dampers, MAT_100 spotweld beam parts)
    # are emitted by the connector sections with their own /PROP/TYPE4-13 and
    # /SPRING elements — emitting them here would reference a DYNA section /
    # material id that has no /PROP or /MAT counterpart.
    connector_pids = _discrete_part_ids(state) | _spotweld_beam_pids(state)

    for pid, part in sorted(state.parts.items()):
        if pid in connector_pids:
            continue
        secid = part.secid if part.secid > 0 else pid
        # A *MAT_ANISOTROPIC_VISCOPLASTIC (LAW128) part is repointed at its
        # synthesized orthotropic /PROP/TYPE9|TYPE6 (LAW128 is orthotropic-only);
        # a part whose per-part hourglass differs from its section is repointed
        # at its dedicated hourglass /PROP. The two are mutually exclusive (the
        # hourglass prepass skips ortho parts), so ortho wins where both exist.
        prop_ref = (state.ortho_prop_ids.get(pid)
                    or state.hourglass_prop_ids.get(pid, secid))

        lines += [
            f"/PART/{pid}",
            part.title or f"PART_{pid}",
            f"{_i(prop_ref)}{_i(part.mid)}         0",
            HDR,
        ]
        if pid in shells_by_pid:
            lines.append(f"/SHELL/{pid}")
            for e in shells_by_pid[pid]:
                row = _i(e.eid)
                for n in e.nodes:
                    row += _i(n)
                pad = 4 - len(e.nodes)
                if pad > 0:
                    row += "         0" * pad
                row += "         0"
                lines.append(row)
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
                    _tick()
                lines.append(HDR)
            if tets10:
                # /TETRA10: 2 lines per element — tetra_ID, then the 10 node IDs
                # (10 fixed-width fields). Node order matches LS-DYNA/Abaqus tet10.
                lines.append(f"/TETRA10/{pid}")
                for e in tets10:
                    lines.append(_i(e.eid))
                    lines.append("".join(_i(n) for n in e.nodes[:10]))
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
                    _tick()
                lines.append(HDR)
        if pid in beams_by_pid:
            lines.append(f"/BEAM/{pid}")
            for e in beams_by_pid[pid]:
                lines.append(f"{_i(e.eid)}{_i(e.n1)}{_i(e.n2)}{_i(e.n3)}")
            lines.append(HDR)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Per-part hourglass control (*HOURGLASS + *PART HGID → per-part /PROP)
# ─────────────────────────────────────────────────────────────────────────────
#
# Semantics follow dyna2rad ConvertProp::ConvertEntities (solids only there):
#   h ← QM (or the global *CONTROL_HOURGLASS QH); Isolid ← f(IHQ) with
#   IHQ 1/2/3 → 1, 4/5 → 5, 6/7 → 24; 0/8/9/10 unmapped (section Isolid kept).
#   The map is gated to /PROP/SOLID with ELFORM ∉ {2,13} (not tetra) and a
#   section Isolid ∉ {14,17,18} (not ALE/cohesive). A *HOURGLASS on a *PART
#   overrides the global card; HGID=0 (or a dangling id) falls back to it.
#
# k2rad props are per-SECTION, so — unlike dyna2rad, which mutates the shared
# /PROP in place and lets the last part win — a per-part hourglass difference
# forces a dedicated /PROP split (the same mechanism as the LAW128 ortho props),
# keeping every part's setting. Shells carry the coefficient into Hm/Hf/Hr
# (clamped to the Radioss shell max 0.05); k2rad selects Ishell from ELFORM
# (12/24), for which Hm/Hf/Hr are physically inert (warned once), so no
# IHQ→Ishell map is invented (dyna2rad maps no shell formulation either).

_SHELL_HG_MAX = 0.05   # Radioss /PROP/SHELL Hm/Hf/Hr upper bound (cfg CHECK)


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
    tetra (ELFORM 2/13), or a tet4/cohesive Isolid (14/18) — or no hourglass
    source applies. h is the coefficient verbatim (no IHQ dependence);
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
    # only Isolids are 17/14/2) and make the whole feature a no-op. So the gate
    # is adapted to the same *intent* — skip ALE, tetra, and cohesive, where
    # hourglass control is meaningless — while allowing the structural hex (17)
    # to be remapped to the under-integrated 1/5/24 the IHQ dictates (necessary
    # anyway: Isolid 17 is full-integration and ignores the h coefficient).
    if sec.iale or sec.elform in (2, 13):
        return (None, None)
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


def _emit_prop_solid(prop_id: int, title: str, isolid: int, iale: int,
                     itetra10: int, istrain: int,
                     hcoef: Optional[float] = None) -> List[str]:
    """/PROP/SOLID (TYPE14), byte-identical to the historical inline block.
    *hcoef* None → card-2 field 3 (h) stays 0 (Radioss default 1.1/0.05/0.10
    for qa/qb/h); otherwise the hourglass coefficient. Shared by the
    per-section and per-part paths so the 100-column layout cannot drift."""
    h_field = _f(hcoef if hcoef is not None else 0.0)
    return [
        f"/PROP/SOLID/{prop_id}",
        title,
        "#   Isolid    Ismstr      Iale     Icpre  Itetra10     Inpts   Itetra4    Iframe                  Dn",
        f"{_i(isolid)}         0{_i(iale)}         0{_i(itetra10)}         0         0         0",
        "#                q_a                 q_b                   h            LAMBDA_V                MU_V",
        f"{_f(0.0)}{_f(0.0)}{h_field}{_f(0.0)}{_f(0.0)}",
        "#             dt_min   istrain      IHKT",
        f"                   0{_i(istrain)}         0",
        HDR,
    ]


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
    ext = state.db_extent_binary
    istrain = 1 if (ext and ext.strflg > 0) else 0

    missing_shells = set()
    missing_solids = set()
    missing_beams = set()

    part_secids = {p.pid: p.secid if p.secid > 0 else p.pid for p in state.parts.values()}

    # Sections whose EVERY part is served by a dedicated per-part /PROP — a
    # LAW128 (MAT_103) orthotropic prop or a per-part hourglass prop — reference
    # that instead, so the shared isotropic section prop would be emitted unused.
    # Skip it in that case (a section with even one plain part keeps it, and the
    # split parts additionally get their own props). Mirrors the ortho split.
    split_pids = set(state.ortho_prop_ids) | set(state.hourglass_prop_ids)
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

    # Spotweld beam parts become /SPRING connectors (their /PROP/TYPE13 is
    # emitted by _make_spotweld_beam_connectors); their beams must not force an
    # auto /PROP/BEAM, and a *SECTION_BEAM used ONLY by spotweld parts is not
    # emitted (its ELFORM-9 card has no /PROP/BEAM meaning).
    spotweld_pids = _spotweld_beam_pids(state)
    spotweld_only_secids: Set[int] = set()
    if spotweld_pids:
        other_beam_secids = {part_secids.get(e.pid) for e in state.beam_elems
                             if e.pid not in spotweld_pids}
        spotweld_only_secids = {part_secids[pid] for pid in spotweld_pids
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
        if e.pid in spotweld_pids:
            continue
        secid = part_secids.get(e.pid)
        if secid and secid not in state.sec_beams:
            missing_beams.add(secid)

    for ms in missing_shells:
        state.sec_shells[ms] = SectionShell(ms, f"AutoPropShell_{ms}", 2, 3, 0.0)
    for ms in missing_solids:
        state.sec_solids[ms] = SectionSolid(ms, f"AutoPropSolid_{ms}", 1)
    for ms in missing_beams:
        state.sec_beams[ms] = SectionBeam(ms, f"AutoPropBeam_{ms}", 2)

    for sec in sorted(state.sec_shells.values(), key=lambda s: s.secid):
        if sec.secid in ortho_only_secids:
            continue
        ishell = _elform_to_ishell(sec.elform, state.is_implicit)
        nip = max(2, sec.nip)
        # Shared section prop carries the global *CONTROL_HOURGLASS coefficient
        # (its base); parts with a different *HOURGLASS are split out below.
        hm, _ = _shell_hg_values(state, sec, None)
        lines += _emit_prop_shell(sec.secid, sec.title or f"PROP_{sec.secid}",
                                  ishell, nip, istrain, sec.t1, hcoef=hm)
    for sec in sorted(state.sec_solids.values(), key=lambda s: s.secid):
        if sec.secid in ortho_only_secids:
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
        lines += _emit_prop_solid(sec.secid, sec.title or f"PROP_{sec.secid}",
                                  isolid, sec.iale, itetra10, istrain, hcoef=h)
    for sec in sorted(state.sec_beams.values(), key=lambda s: s.secid):
        if sec.secid in spotweld_only_secids:
            continue
        lines += _emit_prop_beam(sec)
    # Orthotropic properties for LAW128 (MAT_103) parts (the section auto-create
    # above has already populated any missing section this reads).
    lines += _emit_ortho_props(state, istrain)
    # Per-part hourglass properties (*HOURGLASS / per-part *CONTROL_HOURGLASS
    # override), each a copy of its section prop with part-specific h/Isolid.
    lines += _emit_hourglass_props(state, istrain)
    return lines


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
    for pid, part in sorted(state.parts.items()):
        if part.mid not in mat_mids or pid in state.ortho_prop_ids:
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
    for pid, part in sorted(state.parts.items()):
        # A LAW128 part already owns a dedicated ortho /PROP; the hourglass
        # overlay does not also split it (its TYPE6/TYPE9 keeps its defaults).
        if pid in state.ortho_prop_ids:
            continue
        is_solid = pid in solid_pids
        is_shell = pid in shell_pids and not is_solid
        if not (is_solid or is_shell):
            continue    # beams / discrete / tshell — dyna2rad maps none
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
            sec = state.sec_solids.get(secid)
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
            sec = state.sec_shells.get(secid)
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
            state.hourglass_prop_ids[pid] = state.next_id()
            state.hourglass_prop_vals[pid] = eff
    if state.hourglass_prop_ids:
        state.warn(
            "Per-part hourglass control split the shared section /PROP for "
            f"part(s) {sorted(state.hourglass_prop_ids)} into dedicated /PROP "
            "copies (their *HOURGLASS/HGID resolves differently from the "
            "section's global *CONTROL_HOURGLASS base) — h/Isolid follow the "
            "*HOURGLASS card.")


def _emit_prop_type9(prop_id: int, title: str, sec: SectionShell,
                     is_implicit: bool, istrain: int, state: ConversionState,
                     refvec=(1.0, 0.0, 0.0), phi: float = 0.0) -> List[str]:
    """Orthotropic shell property /PROP/TYPE9 (SH_ORTH) — the isotropic
    /PROP/SHELL fields plus a material reference direction (Vx/Vy/Vz + Phi).
    Column layout from PROP/prop_p9_sh_orth.cfg FORMAT(radioss2022)."""
    ishell = _elform_to_ishell(sec.elform, is_implicit)
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
                     phi: float = 0.0, skew_id: int = 0) -> List[str]:
    """Orthotropic solid property /PROP/TYPE6 (SOL_ORTH). With skew_id the
    orthotropy axes are taken DIRECTLY from the /SKEW (starter maps Ip=0 +
    skew_ID to the internal Ip<0 skew branch: material dir 1 = skew X' for
    EVERY element, exactly). Without a skew, Ip=11 projects the reference
    vector onto each element's local r-s plane — element-topology-dependent on
    free tet meshes, so only used as a fallback. Column layout from
    PROP/prop_p6_sol_orth.cfg FORMAT(radioss2022)."""
    isolid = _elform_to_isolid(sec.elform) if sec else 0
    vx, vy, vz = (0.0, 0.0, 0.0) if skew_id else refvec
    if skew_id:
        ip, phi = 0, 0.0
    b10 = " " * 10
    lines = [
        f"/PROP/TYPE6/{prop_id}",
        title,
        "#   Isolid    Ismstr               Icpre  Itetra10     Inpts   Itetra4    Iframe                  Dn",
        f"{_i(isolid)}{_i(0)}{b10}{_i(0)}{_i(itetra10)}{_i(0)}{_i(0)}{_i(0)}{_f(0.0)}",
        "#                 qa                  qb                   h",
        f"{_f(0.0)}{_f(0.0)}{_f(0.0)}",
        "#                 Vx                  Vy                  Vz   skew_ID        Ip     Iorth",
        f"{_f(vx)}{_f(vy)}{_f(vz)}{_i(skew_id)}{_i(ip)}{_i(0)}",
        "#                Phi                 Px                  Py                  Pz",
        f"{_f(phi)}{_f(0.0)}{_f(0.0)}{_f(0.0)}",
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
    skew_ids_used = state.all_skew_ids()
    for pid, prop_id in sorted(state.ortho_prop_ids.items()):
        secid = part_secids.get(pid, pid)
        title = f"LAW128_ORTHO_PROP_{prop_id} (part {pid})"
        part = state.parts.get(pid)
        mat = state.mat_aniso_visco.get(part.mid) if part else None
        vec, phi, note = _law128_ref_axis(mat) if mat else (None, 0.0, None)
        mapped = vec is not None
        if not mapped:
            vec, phi = (1.0, 0.0, 0.0), 0.0
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
            skew_id = prop_id
            while skew_id in skew_ids_used:
                skew_id += 1
            skew_ids_used.add(skew_id)
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
    lines: List[str] = []
    for pid, prop_id in sorted(state.hourglass_prop_ids.items()):
        secid = part_secids.get(pid, pid)
        coeff, iso_over = state.hourglass_prop_vals.get(pid, (None, None))
        title = f"HG_PROP_{prop_id} (part {pid})"
        # solid-first, matching _assign_hourglass_props' family selection.
        if pid in solid_pids:
            sec = state.sec_solids.get(secid)
            isolid = (0 if (sec and sec.iale)
                      else (_elform_to_isolid(sec.elform) if sec else 17))
            if iso_over is not None:
                isolid = iso_over
            iale = sec.iale if sec else 0
            itetra10 = 1000 if tet10_by_pid.get(pid) else 0
            lines += _emit_prop_solid(prop_id, title, isolid, iale, itetra10,
                                      istrain, hcoef=coeff)
        elif pid in shell_pids:
            sec = state.sec_shells.get(secid)
            ishell = (_elform_to_ishell(sec.elform, state.is_implicit) if sec
                      else _elform_to_ishell(2, state.is_implicit))
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
# Starter: extra groups (node sets not already emitted)
# ─────────────────────────────────────────────────────────────────────────────

def _make_extra_groups(state: ConversionState) -> List[str]:
    emitted: Set[int] = {bc.nsid for bc in state.bcs_spcs}
    lines: List[str] = []
    for nsid, (title, nids) in sorted(state.node_sets.items()):
        if nsid not in emitted:
            lines += _emit_grnod_node(nsid, title, nids)
    return lines
