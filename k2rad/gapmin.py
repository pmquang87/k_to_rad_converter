"""
k2rad.gapmin  –  suggest a per-interface /INTER/TYPE7 Gapmin from the *actual
node-to-segment clearance* the contact engine sees.

Why
---
For a solid /SURF/PART/EXT contact the writer emits Igap=0 (constant gap) with
Fscalegap=0 / GAP_MAX=0, so the engagement gap is simply **Gapmin**.  Gapmin
must therefore sit just *below* the real clearance between the two contacting
parts:

  * Gapmin > clearance  → the secondary nodes start already inside the gap
    (OpenRadioss starter ``WARNING 343 INITIAL PENETRATIONS``).  Under a pull the
    releasing-side nodes then flip-flop in and out of the penalty gap and the
    force residual sticks — the implicit solve never converges (the elevator
    TET10 contact limit cycle: |du|/|u| oscillates, |r|/|r0| pinned at the
    tolerance, the contact active set churns, MAX_ITER → timestep cut → repeat).
  * Gapmin ≪ clearance  → contact never engages under load → no load path → a
    rigid-body mode → divergence.

What clearance?
---------------
OpenRadioss /INTER/TYPE7 engages a secondary **NODE** against a main **SEGMENT**
(a surface facet).  The clearance the engine actually sees is therefore the
**node-to-segment** distance: the minimum, over the secondary side's nodes, of
the distance from that node to the nearest point of any main-side surface facet.

An earlier version measured node-to-**node** distance (closest approach between
the two parts' nodes).  That *over-estimates* the real clearance — the nearest
point of a facet usually lies on its interior, closer than any of its vertices —
so a Gapmin derived from it still leaves initial penetrations even at a small
factor.  Node-to-node has been removed; only the node-to-segment measure remains.

    Gapmin = factor × (min node-to-segment distance),  factor < 1

factor < 1 is a safety margin that keeps the gap strictly below the measured
clearance (0 initial penetration) while still engaging promptly under load.

Dependencies
------------
The node-to-segment search is a point-to-mesh query accelerated by a spatial
tree, so it needs **numpy + scipy** (``scipy.spatial.cKDTree``).  These are an
*optional* dependency: importing :mod:`k2rad` and running a default conversion
never touch this module, so they work with the standard library alone.  Only the
``--auto-gapmin`` / ``--suggest-gapmin`` features need numpy+scipy; when the
packages are absent those features report that clearly and apply no Gapmin
(there is no node-to-node fallback — it was found to leave penetrations even at
factor 0.1).  See ``docs/DEPENDENCIES.md``.

Algorithm
---------
The MAIN side's external surface is extracted as linear triangles (solids:
boundary faces shared by exactly one element — TET4 → 4 tris, hex/brick → 6
quads → 12 tris, TET10 → each boundary face subdivided into the 4 linear
sub-triangles through its mid-edge nodes, matching what OpenRadioss builds for a
/TETRA10 contact surface; shells: the element is the facet).  The exact
point-to-triangle distance (Ericson, *Real-Time Collision Detection*) is then
evaluated, but only on a small candidate set: a cKDTree gives a global
upper-bound on the closest approach, which prunes the secondary nodes to those
near the surface and, per node, the facets near it.  This keeps the query in the
seconds range on a large (~100 MB) mesh.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .state import ConversionState
# The validated TET10 mid-edge map (mid_local_index, cornerA_local, cornerB_local)
# lives in the neutral topology module; reuse it so the contact-facet subdivision
# here always matches the surface the writer/engine builds — without importing the
# whole writer just for this constant.
from .topology import TET10_MIDEDGE as _TET10_MIDEDGE

# ── Optional fast-proximity backend (numpy + scipy) ──────────────────────────
# Kept optional so `import k2rad` and a default conversion need no third party.
try:                                                # pragma: no cover - env dependent
    import numpy as _np
    from scipy.spatial import cKDTree as _cKDTree
    _HAVE_FAST_PROXIMITY = True
except Exception:                                   # pragma: no cover - env dependent
    _np = None
    _cKDTree = None
    _HAVE_FAST_PROXIMITY = False


# Default safety factor: Gapmin = DEFAULT_GAPMIN_FACTOR × (min node-to-segment
# clearance).  <1 so the gap stays below the clearance (0 initial penetration);
# close enough to 1 that the contact still engages promptly under load.  Lower it
# (e.g. 0.5) if an interface still reports initial penetration on a coarse main
# mesh; raise it toward 1.0 if a contact fails to engage.
DEFAULT_GAPMIN_FACTOR = 0.8

Coord = Tuple[float, float, float]


def fast_proximity_available() -> bool:
    """True when numpy + scipy are importable, i.e. node-to-segment clearance can
    be measured.  ``--auto-gapmin`` / ``--suggest-gapmin`` require this; without
    it they apply no Gapmin (there is no node-to-node fallback)."""
    return _HAVE_FAST_PROXIMITY


def _round_sig(x: float, sig: int = 4) -> float:
    """Round *x* to *sig* significant figures for a tidy, reproducible Gapmin."""
    if x == 0.0:
        return 0.0
    from math import floor as _floor, log10
    digits = sig - 1 - _floor(log10(abs(x)))
    return round(x, digits)


# ─────────────────────────────────────────────────────────────────────────────
# Exact point-to-triangle distance (the contact node-to-segment kernel)
# ─────────────────────────────────────────────────────────────────────────────

def point_triangle_distance(p: Coord, a: Coord, b: Coord, c: Coord) -> float:
    """Exact Euclidean distance from point *p* to triangle (*a*, *b*, *c*).

    Pure standard library (no numpy) so it is always available and directly
    testable.  Implements Ericson's *ClosestPtPointTriangle* (Real-Time Collision
    Detection §5.1.5): the closest point lies in one of 7 Voronoi regions — the
    three vertices, the three edges, or the face interior — and this returns the
    distance to whichever applies.  Degenerate (zero-area) triangles collapse to
    the relevant edge/vertex and are handled without dividing by zero.
    """
    ax, ay, az = a
    bx, by, bz = b
    cx, cy, cz = c
    px, py, pz = p

    abx, aby, abz = bx - ax, by - ay, bz - az
    acx, acy, acz = cx - ax, cy - ay, cz - az
    apx, apy, apz = px - ax, py - ay, pz - az

    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    if d1 <= 0.0 and d2 <= 0.0:                       # region: vertex A
        return sqrt(apx * apx + apy * apy + apz * apz)

    bpx, bpy, bpz = px - bx, py - by, pz - bz
    d3 = abx * bpx + aby * bpy + abz * bpz
    d4 = acx * bpx + acy * bpy + acz * bpz
    if d3 >= 0.0 and d4 <= d3:                         # region: vertex B
        return sqrt(bpx * bpx + bpy * bpy + bpz * bpz)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:          # region: edge AB
        den = d1 - d3
        v = d1 / den if den != 0.0 else 0.0
        qx, qy, qz = ax + v * abx, ay + v * aby, az + v * abz
        dx, dy, dz = px - qx, py - qy, pz - qz
        return sqrt(dx * dx + dy * dy + dz * dz)

    cpx, cpy, cpz = px - cx, py - cy, pz - cz
    d5 = abx * cpx + aby * cpy + abz * cpz
    d6 = acx * cpx + acy * cpy + acz * cpz
    if d6 >= 0.0 and d5 <= d6:                         # region: vertex C
        return sqrt(cpx * cpx + cpy * cpy + cpz * cpz)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:          # region: edge AC
        den = d2 - d6
        w = d2 / den if den != 0.0 else 0.0
        qx, qy, qz = ax + w * acx, ay + w * acy, az + w * acz
        dx, dy, dz = px - qx, py - qy, pz - qz
        return sqrt(dx * dx + dy * dy + dz * dz)

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:   # region: edge BC
        den = (d4 - d3) + (d5 - d6)
        w = (d4 - d3) / den if den != 0.0 else 0.0
        qx, qy, qz = bx + w * (cx - bx), by + w * (cy - by), bz + w * (cz - bz)
        dx, dy, dz = px - qx, py - qy, pz - qz
        return sqrt(dx * dx + dy * dy + dz * dz)

    den = va + vb + vc                                 # region: face interior
    if den == 0.0:
        return sqrt(apx * apx + apy * apy + apz * apz)
    v = vb / den
    w = vc / den
    qx = ax + abx * v + acx * w
    qy = ay + aby * v + acy * w
    qz = az + abz * v + acz * w
    dx, dy, dz = px - qx, py - qy, pz - qz
    return sqrt(dx * dx + dy * dy + dz * dz)


def min_point_to_triangles(points: Sequence[Coord], verts: Sequence[Coord],
                           faces: Sequence[Tuple[int, int, int]]) -> Optional[float]:
    """Brute-force minimum distance from any point in *points* to the triangle
    set (*verts* indexed by *faces*).  Pure standard library, O(P·F) — intended
    for small inputs and as the correctness reference for the fast path; the
    production query uses the cKDTree-pruned :func:`_min_point_to_triangles_fast`.
    Returns ``None`` when either set is empty."""
    if not points or not faces:
        return None
    best = float("inf")
    for p in points:
        for i, j, k in faces:
            d = point_triangle_distance(p, verts[i], verts[j], verts[k])
            if d < best:
                best = d
                if best == 0.0:
                    return 0.0
    return None if best == float("inf") else best


def max_node_to_triangles(points: Sequence[Coord], verts: Sequence[Coord],
                          faces: Sequence[Tuple[int, int, int]]) -> Optional[float]:
    """Maximum over *points* of the minimum distance to the triangle set — the
    worst node-to-surface gap a tied interface's search distance must cover
    (every /INTER/TYPE2 secondary node needs a main segment within dsearch).

    Pure standard library so it is always available (a tied weld line is small
    next to a whole-model contact surface). Per point, an exact distance to the
    nearest-centroid triangle bounds the search; triangles whose centroid
    sphere (centroid + max centroid-to-vertex radius) cannot beat that bound
    are skipped. Returns ``None`` when either set is empty."""
    if not points or not faces:
        return None
    cents: List[Coord] = []
    rads: List[float] = []
    for i, j, k in faces:
        a, b, c = verts[i], verts[j], verts[k]
        cx = (a[0] + b[0] + c[0]) / 3.0
        cy = (a[1] + b[1] + c[1]) / 3.0
        cz = (a[2] + b[2] + c[2]) / 3.0
        cents.append((cx, cy, cz))
        rads.append(max(sqrt((v[0] - cx) ** 2 + (v[1] - cy) ** 2 + (v[2] - cz) ** 2)
                        for v in (a, b, c)))
    worst = 0.0
    for p in points:
        px, py, pz = p
        cdists = [sqrt((cx - px) ** 2 + (cy - py) ** 2 + (cz - pz) ** 2)
                  for cx, cy, cz in cents]
        near = min(range(len(faces)), key=cdists.__getitem__)
        f = faces[near]
        best = point_triangle_distance(p, verts[f[0]], verts[f[1]], verts[f[2]])
        for idx, (i, j, k) in enumerate(faces):
            if idx == near or cdists[idx] - rads[idx] >= best:
                continue
            d = point_triangle_distance(p, verts[i], verts[j], verts[k])
            if d < best:
                best = d
                if best == 0.0:
                    break
        if best > worst:
            worst = best
    return worst


# ── Vectorised kernel (numpy) — one point against many triangles ─────────────

def _closest_tri_dist2(P, tris):
    """Squared distance from each point *P[i]* (shape (M, 3)) to its paired
    triangle *tris[i]* (shape (M, 3, 3)); returns an (M,) array.  numpy port of
    :func:`point_triangle_distance` — the closest point per triangle is built
    region-wise and selected with :func:`numpy.select`.  Edge parameters are
    clamped to [0, 1] so degenerate triangles never divide by zero.  Fully paired
    so the whole node-vs-candidate-facet set is evaluated in one vectorised call."""
    np = _np
    A = tris[:, 0, :]
    B = tris[:, 1, :]
    C = tris[:, 2, :]
    AB = B - A
    AC = C - A
    AP = P - A
    d1 = (AB * AP).sum(1)
    d2 = (AC * AP).sum(1)
    BP = P - B
    d3 = (AB * BP).sum(1)
    d4 = (AC * BP).sum(1)
    CP = P - C
    d5 = (AB * CP).sum(1)
    d6 = (AC * CP).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    def _safe_div(num, den):
        out = np.zeros_like(num)
        np.divide(num, den, out=out, where=(den != 0.0))
        return out

    v_ab = np.clip(_safe_div(d1, d1 - d3), 0.0, 1.0)
    w_ac = np.clip(_safe_div(d2, d2 - d6), 0.0, 1.0)
    w_bc = np.clip(_safe_div(d4 - d3, (d4 - d3) + (d5 - d6)), 0.0, 1.0)
    denom = va + vb + vc
    v_in = _safe_div(vb, denom)
    w_in = _safe_div(vc, denom)

    QA = A
    QB = B
    QC = C
    Qab = A + v_ab[:, None] * AB
    Qac = A + w_ac[:, None] * AC
    Qbc = B + w_bc[:, None] * (C - B)
    Qin = A + v_in[:, None] * AB + w_in[:, None] * AC

    r1 = (d1 <= 0.0) & (d2 <= 0.0)
    r2 = (d3 >= 0.0) & (d4 <= d3)
    r3 = (vc <= 0.0) & (d1 >= 0.0) & (d3 <= 0.0)
    r4 = (d6 >= 0.0) & (d5 <= d6)
    r5 = (vb <= 0.0) & (d2 >= 0.0) & (d6 <= 0.0)
    r6 = (va <= 0.0) & ((d4 - d3) >= 0.0) & ((d5 - d6) >= 0.0)
    region = np.select([r1, r2, r3, r4, r5, r6], [0, 1, 2, 3, 4, 5], default=6)

    Qs = np.stack([QA, QB, Qab, QC, Qac, Qbc, Qin], axis=0)   # (7, M, 3)
    Q = Qs[region, np.arange(tris.shape[0])]                  # (M, 3)
    diff = P - Q
    return (diff * diff).sum(1)


def _min_point_to_triangles_fast(P, V, F) -> float:
    """Minimum distance from any point in *P* (np, 3) to the mesh (*V* verts,
    *F* tri indices), using a cKDTree to prune candidates so the exact kernel runs
    only on a handful of node/facet pairs.

    Correctness of the pruning (we want only the global minimum *D*):
      * A facet vertex lies on the surface, so each point's nearest-vertex
        distance ``dv`` is an upper bound on its true surface distance, and
        ``UB = min(dv)`` ≥ *D*.
      * For any point, the closest surface point sits within one triangle whose
        farthest vertex is ≤ ``Lmax`` (longest edge) away, so true ≥ dv − Lmax.
        Hence only points with ``dv ≤ UB + Lmax`` can achieve ≤ *D* — the rest
        are dropped.
      * For a kept point, the closest triangle's centroid is within ``dv + Rc``
        (Rc = max vertex-to-centroid distance), so a centroid ball of that radius
        contains it.
    ``best`` starts at ``UB`` (a real surface distance) so the result is valid
    even if every ball were empty.
    """
    np = _np
    cKDTree = _cKDTree
    tris = V[F]                                       # (nf, 3, 3)
    A = tris[:, 0, :]
    B = tris[:, 1, :]
    C = tris[:, 2, :]
    e0 = np.sqrt(((B - A) ** 2).sum(1))
    e1 = np.sqrt(((C - B) ** 2).sum(1))
    e2 = np.sqrt(((A - C) ** 2).sum(1))
    Lmax = float(np.maximum(np.maximum(e0, e1), e2).max())
    cen = (A + B + C) / 3.0
    rc = np.sqrt(np.maximum(np.maximum(((A - cen) ** 2).sum(1),
                                       ((B - cen) ** 2).sum(1)),
                            ((C - cen) ** 2).sum(1)))
    Rc = float(rc.max())

    Tv = cKDTree(V)
    dv, _ = Tv.query(P, k=1, workers=-1)               # nearest main vertex / point
    UB = float(dv.min())
    if UB <= 0.0:
        return 0.0

    keep = dv <= (UB + Lmax)                            # only points near the surface
    Pc = P[keep]
    dvc = dv[keep]
    Tc = cKDTree(cen)
    cand = Tc.query_ball_point(Pc, dvc + Rc, workers=-1)   # candidate facets per point

    # Flatten the ragged candidate lists into (node, facet) pairs and evaluate the
    # exact distance for all pairs in one vectorised pass; the global minimum is
    # simply the smallest pair distance (no per-node reduction needed). Chunked to
    # bound peak memory on a very large candidate set.
    counts = _np.fromiter((len(c) for c in cand), dtype=_np.intp, count=len(cand))
    total = int(counts.sum())
    best2 = UB * UB
    if total:
        tri_idx = _np.concatenate([_np.asarray(c, dtype=_np.intp) for c in cand])
        pt_idx = _np.repeat(_np.arange(Pc.shape[0], dtype=_np.intp), counts)
        chunk = 1_000_000
        for s in range(0, total, chunk):
            sl = slice(s, min(s + chunk, total))
            d2 = _closest_tri_dist2(Pc[pt_idx[sl]], tris[tri_idx[sl]])
            m = float(d2.min())
            if m < best2:
                best2 = m
    return sqrt(best2)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN-side surface facet extraction (pure standard library)
# ─────────────────────────────────────────────────────────────────────────────

# Solid element faces as local-corner-index tuples.
_TET4_FACES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
_HEX_FACES = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
              (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
# Local edge {cornerA, cornerB} → local mid-edge node index, from the writer's
# validated TET10 map, so a TET10 boundary face can be split into 4 sub-triangles
# through its mid-edge nodes exactly as the engine builds the contact surface.
_TET10_EDGEMID = {frozenset((a, b)): m for (m, a, b) in _TET10_MIDEDGE}


def _surface_triangles(state: ConversionState, pids: Iterable[int]
                       ) -> Tuple[List[Coord], List[Tuple[int, int, int]]]:
    """Extract the external surface of the given parts as linear triangles.

    Returns ``(verts, faces)`` where *verts* is a list of (x, y, z) and *faces* a
    list of (i, j, k) indices into *verts*.  Solids contribute boundary faces
    (those used by exactly one element; interior faces appear twice and are
    dropped): TET4 → its 4 triangular faces; hex/brick → 6 quad faces, each split
    into 2 triangles; TET10 → each boundary face subdivided into the 4 linear
    sub-triangles through its mid-edge nodes (matching the engine's /TETRA10
    contact faceting).  Shell elements *are* facets (tri as-is; quad → 2 tris).
    Empty when the parts have no surface (e.g. a node-set side)."""
    pidset = set(pids)

    # Solid boundary faces: keep a representative element+face for each face key
    # the first time it is seen, mark it None when seen again (interior/shared).
    seen: Dict[Tuple[int, ...], Optional[Tuple[List[int], Tuple[int, ...]]]] = {}
    for e in state.solid_elems:
        if e.pid not in pidset:
            continue
        nds = e.nodes
        n = len(nds)
        if n == 4 or n == 10:
            faces = _TET4_FACES                       # by 4 corner nodes
        elif n == 8:
            faces = _HEX_FACES
        else:
            continue
        for f in faces:
            key = tuple(sorted(nds[i] for i in f))
            if key in seen:
                seen[key] = None
            else:
                seen[key] = (nds, f)

    tris: List[Tuple[int, int, int]] = []             # triangles by ORIGINAL node id

    def _emit_tet10_face(nds: List[int], f: Tuple[int, ...]) -> None:
        """4-way subdivision of a TET10 boundary face (local corner indices *f*)
        through its mid-edge nodes; falls back to the corner triangle if a
        mid-edge node is missing."""
        i, j, k = f
        a, b, c = nds[i], nds[j], nds[k]
        try:
            mij = nds[_TET10_EDGEMID[frozenset((i, j))]]
            mjk = nds[_TET10_EDGEMID[frozenset((j, k))]]
            mik = nds[_TET10_EDGEMID[frozenset((i, k))]]
        except (KeyError, IndexError):
            mij = mjk = mik = 0
        if mij > 0 and mjk > 0 and mik > 0:
            tris.append((a, mij, mik))
            tris.append((mij, b, mjk))
            tris.append((mik, mjk, c))
            tris.append((mij, mjk, mik))
        else:
            tris.append((a, b, c))

    for repr_face in seen.values():
        if repr_face is None:
            continue
        nds, f = repr_face
        if len(f) == 3:
            if len(nds) == 10:
                _emit_tet10_face(nds, f)
            else:
                tris.append((nds[f[0]], nds[f[1]], nds[f[2]]))
        else:                                          # quad face → 2 triangles
            q0, q1, q2, q3 = (nds[f[0]], nds[f[1]], nds[f[2]], nds[f[3]])
            tris.append((q0, q1, q2))
            tris.append((q0, q2, q3))

    # Shell elements are themselves contact facets.
    for e in state.shell_elems:
        if e.pid not in pidset:
            continue
        nn = [n for n in e.nodes if n > 0]
        if len(nn) >= 3:
            tris.append((nn[0], nn[1], nn[2]))
            if len(nn) == 4:
                tris.append((nn[0], nn[2], nn[3]))

    if not tris:
        return [], []

    # Compact to a vertex list + index faces, dropping degenerate/unknown tris.
    nodes = state.nodes
    idmap: Dict[int, int] = {}
    verts: List[Coord] = []
    faces_out: List[Tuple[int, int, int]] = []
    for a, b, c in tris:
        if a == b or b == c or a == c:
            continue
        try:
            ia = idmap[a]
        except KeyError:
            nd = nodes.get(a)
            if nd is None:
                continue
            ia = idmap[a] = len(verts)
            verts.append((nd.x, nd.y, nd.z))
        try:
            ib = idmap[b]
        except KeyError:
            nd = nodes.get(b)
            if nd is None:
                continue
            ib = idmap[b] = len(verts)
            verts.append((nd.x, nd.y, nd.z))
        try:
            ic = idmap[c]
        except KeyError:
            nd = nodes.get(c)
            if nd is None:
                continue
            ic = idmap[c] = len(verts)
            verts.append((nd.x, nd.y, nd.z))
        faces_out.append((ia, ib, ic))
    return verts, faces_out


def _segment_triangles(state: ConversionState, segments: Iterable[List[int]]
                       ) -> Tuple[List[Coord], List[Tuple[int, int, int]]]:
    """A *SET_SEGMENT's 3/4-node segments as linear triangles (quads split in
    two), in the same ``(verts, faces)`` form as :func:`_surface_triangles`.
    Segments with unknown node ids are dropped."""
    nodes = state.nodes
    idmap: Dict[int, int] = {}
    verts: List[Coord] = []
    faces: List[Tuple[int, int, int]] = []

    def _vidx(nid: int) -> Optional[int]:
        try:
            return idmap[nid]
        except KeyError:
            nd = nodes.get(nid)
            if nd is None:
                return None
            idx = idmap[nid] = len(verts)
            verts.append((nd.x, nd.y, nd.z))
            return idx

    for seg in segments:
        nn = [n for n in seg if n > 0]
        if len(nn) < 3:
            continue
        idx = [_vidx(n) for n in nn[:4]]
        if any(i is None for i in idx):
            continue
        faces.append((idx[0], idx[1], idx[2]))
        if len(idx) == 4:
            faces.append((idx[0], idx[2], idx[3]))
    return verts, faces


def _min_node_to_segment(state: ConversionState, secondary_node_ids: Iterable[int],
                         main_pids: Iterable[int]) -> Optional[float]:
    """Minimum distance from the secondary side's nodes to the MAIN side's surface
    facets (the node-to-segment clearance /INTER/TYPE7 engages on).  Returns
    ``None`` when the fast backend is unavailable or the main side has no facets
    (e.g. it is a node set) — the caller then skips the interface."""
    if not _HAVE_FAST_PROXIMITY:
        return None
    verts, faces = _surface_triangles(state, main_pids)
    if not faces:
        return None
    pts = _coords_for(state, secondary_node_ids)
    if not pts:
        return None
    np = _np
    P = np.asarray(pts, dtype=float)
    V = np.asarray(verts, dtype=float)
    F = np.asarray(faces, dtype=np.intp)
    return _min_point_to_triangles_fast(P, V, F)


# ─────────────────────────────────────────────────────────────────────────────
# Resolving a *CONTACT side to its mesh nodes / parts
# ─────────────────────────────────────────────────────────────────────────────

def _part_nodes_map(state: ConversionState) -> Dict[int, Set[int]]:
    """pid → set of node ids used by that part's shell + solid elements.

    Built once and shared across all contacts (avoids re-scanning the element
    lists per side — important on a large TET10 mesh)."""
    m: Dict[int, Set[int]] = {}
    for e in state.shell_elems:
        m.setdefault(e.pid, set()).update(n for n in e.nodes if n > 0)
    for e in state.solid_elems:
        m.setdefault(e.pid, set()).update(n for n in e.nodes if n > 0)
    return m


def _side_pids(state: ConversionState, sid: int, styp: int) -> Optional[Set[int]]:
    """Part ids a *CONTACT side (sid/styp) resolves to, or ``None`` for a node
    set (not part-resolvable).  Mirrors the writer's contact-side rules."""
    if styp == 4:
        return None
    if styp == 3:
        return {sid} if sid in state.parts else set()
    if styp == 2:
        ps = state.part_sets.get(sid)
        return set(ps[1]) if ps else set()
    if styp in (0, 1):
        if sid in state.parts:
            return {sid}
        if sid in state.part_sets:
            return set(state.part_sets[sid][1])
        if sid in state.node_sets:
            return None
    return set()


def _side_node_ids(state: ConversionState, sid: int, styp: int,
                   part_nodes: Dict[int, Set[int]]) -> Set[int]:
    """Node ids forming a *CONTACT side (handles part / part-set / node-set)."""
    out: Set[int] = set()
    if styp == 4:
        ns = state.node_sets.get(sid)
        if ns:
            out.update(n for n in ns[1] if n > 0)
    elif styp == 3:
        out.update(part_nodes.get(sid, ()))
    elif styp == 2:
        ps = state.part_sets.get(sid)
        if ps:
            for pid in ps[1]:
                out.update(part_nodes.get(pid, ()))
    elif styp in (0, 1):
        if sid in state.parts:
            out.update(part_nodes.get(sid, ()))
        elif sid in state.part_sets:
            for pid in state.part_sets[sid][1]:
                out.update(part_nodes.get(pid, ()))
        elif sid in state.node_sets:
            out.update(n for n in state.node_sets[sid][1] if n > 0)
    return out


def _coords_for(state: ConversionState, nids: Iterable[int]) -> List[Coord]:
    nodes = state.nodes
    out: List[Coord] = []
    for n in nids:
        nd = nodes.get(n)
        if nd is not None:
            out.append((nd.x, nd.y, nd.z))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Per-interface Gapmin suggestion
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GapminSuggestion:
    inter_id: int
    title: str
    side_a: str               # human description of the secondary side
    side_b: str               # human description of the main side
    min_distance: float       # min node-to-segment clearance (secondary node → main facet)
    suggested_gapmin: float   # = factor × min_distance (rounded)


def _describe_side(state: ConversionState, sid: int, styp: int) -> str:
    """A short 'part 60000000 (title)' / 'part set 7' label for a contact side."""
    if styp == 4 or (styp in (0, 1) and sid in state.node_sets):
        return f"node set {sid}"
    if styp == 2 or (styp in (0, 1) and sid in state.part_sets):
        return f"part set {sid}"
    p = state.parts.get(sid)
    if p is not None:
        return f"part {sid} ({p.title.strip()})" if p.title.strip() else f"part {sid}"
    return f"id {sid}"


def suggest_gapmins(state: ConversionState, factor: float = DEFAULT_GAPMIN_FACTOR
                    ) -> Tuple[Dict[int, GapminSuggestion], Dict[int, str]]:
    """Suggest a Gapmin for every surface-to-surface contact between two
    *distinct* parts, from the **node-to-segment** clearance the engine sees: the
    closest approach from the secondary side's nodes to the main side's surface
    facets.

    Returns ``(suggestions, skipped)`` where *suggestions* maps inter_id →
    :class:`GapminSuggestion` and *skipped* maps inter_id → a reason string
    (self-contacts, single-surface contacts, node-set / facet-less main sides,
    and — when numpy+scipy are absent — every interface, since there is no
    node-to-node fallback).
    """
    part_nodes = _part_nodes_map(state)
    suggestions: Dict[int, GapminSuggestion] = {}
    skipped: Dict[int, str] = {}

    # Single-surface (self / all-parts) contacts have no two-part clearance.
    for c in state.contacts_single:
        skipped[c.inter_id] = "single-surface self-contact (no two-part clearance)"

    have_backend = _HAVE_FAST_PROXIMITY

    for c in state.contacts_surf2surf:
        a_pids = _side_pids(state, c.ssid, c.sstyp)        # secondary
        b_pids = _side_pids(state, c.msid, c.mstyp)        # main
        if a_pids is not None and b_pids is not None and a_pids and a_pids == b_pids:
            skipped[c.inter_id] = "self-contact (same part on both sides)"
            continue

        a_nodes = _side_node_ids(state, c.ssid, c.sstyp, part_nodes)   # secondary
        b_nodes = _side_node_ids(state, c.msid, c.mstyp, part_nodes)   # main
        shared = a_nodes & b_nodes
        a_nodes -= shared
        if not a_nodes or not b_nodes:
            skipped[c.inter_id] = "a side has no nodes of its own (empty or fully shared)"
            continue

        if not have_backend:
            skipped[c.inter_id] = (
                "node-to-segment clearance needs numpy+scipy (not installed) — "
                "no node-to-node fallback")
            continue

        if b_pids is None or not b_pids:
            skipped[c.inter_id] = (
                "main side is a node set (no surface facets to measure against)")
            continue

        d = _min_node_to_segment(state, a_nodes, b_pids)
        if d is None:
            skipped[c.inter_id] = "main side has no surface facets (no solid/shell elements)"
            continue
        if d <= 0.0:
            skipped[c.inter_id] = "degenerate clearance (secondary node lies on the main surface)"
            continue

        suggestions[c.inter_id] = GapminSuggestion(
            inter_id=c.inter_id,
            title=c.title.strip() or f"CONTACT_{c.inter_id}",
            side_a=_describe_side(state, c.ssid, c.sstyp),
            side_b=_describe_side(state, c.msid, c.mstyp),
            min_distance=d,
            suggested_gapmin=_round_sig(factor * d),
        )

    return suggestions, skipped


def apply_auto_gapmin(state: ConversionState, protect_inter_ids=()) -> None:
    """Compute suggested Gapmins and merge them into ``state.options.inter_gapmin``
    (so the existing writer Gapmin path emits them), warning per interface.

    Precedence (highest first): an explicit ``--inter-gapmin`` for an interface
    always wins; then interfaces in *protect_inter_ids* are left untouched so
    they keep their mesh-scale Card-3 SST/MST Gapmin; otherwise the auto
    suggestion is applied.  *protect_inter_ids* carries the deformable-contact
    recipe's deformable-deformable interfaces — their sub-mesh-scale auto value
    would re-trigger the active-set chatter the recipe specifically fixes, so
    auto-gapmin must not shrink them.  Called by :func:`k2rad.convert` when
    ``auto_gapmin`` is on.
    """
    protect = set(protect_inter_ids)
    if not _HAVE_FAST_PROXIMITY:
        state.warn(
            "--auto-gapmin: node-to-segment clearance needs numpy+scipy, which are "
            "not installed — no Gapmin was applied (the node-to-node fallback was "
            "removed because it left initial penetrations even at factor 0.1). "
            "Install them (pip install scipy) or set Gapmin manually via "
            "--inter-gapmin. See docs/DEPENDENCIES.md.")
        return

    factor = state.options.gapmin_factor
    suggestions, skipped = suggest_gapmins(state, factor)

    for iid, s in sorted(suggestions.items()):
        if iid in state.options.inter_gapmin:
            state.warn(
                f"--auto-gapmin INTER {iid} ({s.title}): kept explicit --inter-gapmin "
                f"{state.options.inter_gapmin[iid]:g} (node-to-segment clearance "
                f"{s.side_a} → {s.side_b} = {s.min_distance:g}, suggestion was "
                f"{s.suggested_gapmin:g})."
            )
            continue
        if iid in protect:
            state.warn(
                f"--auto-gapmin INTER {iid} ({s.title}): kept the mesh-scale Card-3 "
                f"SST/MST Gapmin (auto-gapmin skipped here) because the deformable-"
                f"contact recipe is on — the auto value {s.suggested_gapmin:g} is "
                f"below mesh scale and would re-trigger the active-set chatter the "
                f"recipe fixes. Pin it with --inter-gapmin {iid}=VAL to override."
            )
            continue
        state.options.inter_gapmin[iid] = s.suggested_gapmin
        state.warn(
            f"--auto-gapmin INTER {iid} ({s.title}): min node-to-segment clearance "
            f"{s.side_a} → {s.side_b} = {s.min_distance:g} → Gapmin="
            f"{s.suggested_gapmin:g} (= {factor:g}×clearance) for 0 initial "
            "penetrations and clean engagement under load."
        )

    for iid, reason in sorted(skipped.items()):
        state.warn(
            f"--auto-gapmin INTER {iid}: no clearance suggestion — {reason}. "
            "Set Gapmin manually via --inter-gapmin if it pre-penetrates or fails to engage."
        )

    if not suggestions and not skipped:
        state.warn("--auto-gapmin: no contact interfaces found to analyze.")


def analyze_file(input_path: str, factor: float = DEFAULT_GAPMIN_FACTOR
                 ) -> Tuple[Dict[int, GapminSuggestion], Dict[int, str]]:
    """Parse *input_path*, then return :func:`suggest_gapmins` for it — the
    read-only "what Gapmins would you suggest?" path (CLI ``--suggest-gapmin``).
    Does not build or write any .rad output."""
    from .parser import parse_k_file
    from .handlers import dispatch

    blocks = parse_k_file(input_path)
    state = ConversionState()
    for block in blocks:
        dispatch(block, state)
    return suggest_gapmins(state, factor)


__all__ = [
    "DEFAULT_GAPMIN_FACTOR",
    "GapminSuggestion",
    "point_triangle_distance",
    "min_point_to_triangles",
    "fast_proximity_available",
    "suggest_gapmins",
    "apply_auto_gapmin",
    "analyze_file",
]
