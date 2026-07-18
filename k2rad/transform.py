"""
k2rad.transform  –  pure affine-transform math for LS-DYNA assembly keywords.

Implements the geometry of *DEFINE_TRANSFORMATION rows exactly as the
OpenRadioss starter applies the /TRANSFORM cards dyna2rad emits 1:1 from those
rows (lectrans.F / lectranssub.F / euler_mrot.F+euler_vrot.F /
3points_to_frame.F): every row is an affine map  x' = M·x + t  and rows
compose SEQUENTIALLY in card order — row 1 is applied first, row n acts on the
result of row n-1.  Angles are degrees, rotation is counter-clockwise about
the axis direction (right-hand rule, standard Rodrigues matrix).

Node-referenced rows (TRANSL2ND / ROTATE3NA / POS6N) resolve node coordinates
the way the starter does: parse-time (original) coordinates, except that a
referenced node which is itself moved by this transform (same include /
same node set) is first pushed through the rows composed so far — the intent
of the starter's RTRANSPOS pre-transform, implemented here without its
documented TRA/SYM/SCA defects (which collapse points; see lectranssub.F).

This module is pure geometry: stdlib only, no imports from the rest of k2rad,
so the parser layer can use it without touching handlers/state/writer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

Vec3 = Tuple[float, float, float]
Mat3 = Tuple[float, float, float, float, float, float, float, float, float]
# Affine map x' = M·x + t, M row-major.
Affine = Tuple[Mat3, Vec3]

_I3: Mat3 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
IDENTITY: Affine = (_I3, (0.0, 0.0, 0.0))


def mat_apply(m: Mat3, v: Vec3) -> Vec3:
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
            m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
            m[6] * v[0] + m[7] * v[1] + m[8] * v[2])


def affine_apply(a: Affine, p: Vec3) -> Vec3:
    m, t = a
    q = mat_apply(m, p)
    return (q[0] + t[0], q[1] + t[1], q[2] + t[2])


def affine_compose(second: Affine, first: Affine) -> Affine:
    """Return the affine equal to applying *first*, then *second*."""
    m2, t2 = second
    m1, t1 = first
    m = (m2[0] * m1[0] + m2[1] * m1[3] + m2[2] * m1[6],
         m2[0] * m1[1] + m2[1] * m1[4] + m2[2] * m1[7],
         m2[0] * m1[2] + m2[1] * m1[5] + m2[2] * m1[8],
         m2[3] * m1[0] + m2[4] * m1[3] + m2[5] * m1[6],
         m2[3] * m1[1] + m2[4] * m1[4] + m2[5] * m1[7],
         m2[3] * m1[2] + m2[4] * m1[5] + m2[5] * m1[8],
         m2[6] * m1[0] + m2[7] * m1[3] + m2[8] * m1[6],
         m2[6] * m1[1] + m2[7] * m1[4] + m2[8] * m1[7],
         m2[6] * m1[2] + m2[7] * m1[5] + m2[8] * m1[8])
    q = mat_apply(m2, t1)
    return (m, (q[0] + t2[0], q[1] + t2[1], q[2] + t2[2]))


def is_identity(a: Affine) -> bool:
    return a == IDENTITY


def linear_is_identity(a: Affine) -> bool:
    """True when the map is a pure translation (directions/tensors unchanged)."""
    return a[0] == _I3


# ─────────────────────────────────────────────────────────────────────────────
# Elementary transforms (the /TRANSFORM starter formulas)
# ─────────────────────────────────────────────────────────────────────────────

def translation(tx: float, ty: float, tz: float) -> Affine:
    return (_I3, (tx, ty, tz))


def rotation_deg(center: Vec3, axis: Vec3, angle_deg: float) -> Optional[Affine]:
    """Rodrigues rotation by *angle_deg* about the line through *center* with
    direction *axis* (right-hand rule) — EULER_MROT/EULER_VROT applied as
    x' = X0 + R·(x−X0). Returns None for a zero-length axis."""
    ax, ay, az = axis
    ln = math.sqrt(ax * ax + ay * ay + az * az)
    if ln <= 0.0:
        return None
    nx, ny, nz = ax / ln, ay / ln, az / ln
    th = math.radians(angle_deg)
    c, s = math.cos(th), math.sin(th)
    cm = 1.0 - c
    m: Mat3 = (c + nx * nx * cm,      nx * ny * cm - s * nz, nx * nz * cm + s * ny,
               nx * ny * cm + s * nz, c + ny * ny * cm,      ny * nz * cm - s * nx,
               nx * nz * cm - s * ny, ny * nz * cm + s * nx, c + nz * nz * cm)
    q = mat_apply(m, center)
    t = (center[0] - q[0], center[1] - q[1], center[2] - q[2])
    return (m, t)


def scale_about_origin(sx: float, sy: float, sz: float) -> Affine:
    """Componentwise scale about the global origin; zero factors default to 1
    (LS-DYNA and starter lectrans.F convention)."""
    sx = sx if sx != 0.0 else 1.0
    sy = sy if sy != 0.0 else 1.0
    sz = sz if sz != 0.0 else 1.0
    return ((sx, 0.0, 0.0, 0.0, sy, 0.0, 0.0, 0.0, sz), (0.0, 0.0, 0.0))


def mirror(p0: Vec3, p1: Vec3) -> Optional[Affine]:
    """Reflection about the plane through *p0* with normal toward *p1*:
    x' = x − 2·n·((x−p0)·n). Returns None when p1 == p0."""
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    ln = math.sqrt(dx * dx + dy * dy + dz * dz)
    if ln <= 0.0:
        return None
    nx, ny, nz = dx / ln, dy / ln, dz / ln
    m: Mat3 = (1.0 - 2.0 * nx * nx, -2.0 * nx * ny,      -2.0 * nx * nz,
               -2.0 * nx * ny,      1.0 - 2.0 * ny * ny, -2.0 * ny * nz,
               -2.0 * nx * nz,      -2.0 * ny * nz,      1.0 - 2.0 * nz * nz)
    d = 2.0 * (nx * p0[0] + ny * p0[1] + nz * p0[2])
    return (m, (d * nx, d * ny, d * nz))


def _points_to_frame(p1: Vec3, p2: Vec3, p3: Vec3) -> Optional[Mat3]:
    """3points_to_frame.F: u = P2−P1, w = u×(P3−P1), v = w×u, all normalized;
    returns the frame as COLUMNS [u v w] (row-major Mat3), or None when
    degenerate (P1==P2 or collinear points)."""
    u = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
    r = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
    w = (u[1] * r[2] - u[2] * r[1],
         u[2] * r[0] - u[0] * r[2],
         u[0] * r[1] - u[1] * r[0])
    v = (w[1] * u[2] - w[2] * u[1],
         w[2] * u[0] - w[0] * u[2],
         w[0] * u[1] - w[1] * u[0])
    lu = math.sqrt(sum(x * x for x in u))
    lw = math.sqrt(sum(x * x for x in w))
    lv = math.sqrt(sum(x * x for x in v))
    if lu <= 0.0 or lw <= 0.0 or lv <= 0.0:
        return None
    u = (u[0] / lu, u[1] / lu, u[2] / lu)
    v = (v[0] / lv, v[1] / lv, v[2] / lv)
    w = (w[0] / lw, w[1] / lw, w[2] / lw)
    # columns [u v w] in a row-major 3×3
    return (u[0], v[0], w[0],
            u[1], v[1], w[1],
            u[2], v[2], w[2])


def position_map(pts: List[Vec3]) -> Optional[Affine]:
    """POS6P/POS6N: the rigid map taking start frame (P1,P2,P3) onto target
    frame (P4,P5,P6): ROT = QQ·PPᵀ, x' = P4 + ROT·(x − P1) (lectrans.F:807).
    Returns None on a degenerate frame."""
    pp = _points_to_frame(pts[0], pts[1], pts[2])
    qq = _points_to_frame(pts[3], pts[4], pts[5])
    if pp is None or qq is None:
        return None
    # ROT = QQ · PPᵀ   (both row-major)
    ppt: Mat3 = (pp[0], pp[3], pp[6], pp[1], pp[4], pp[7], pp[2], pp[5], pp[8])
    rot = (qq[0] * ppt[0] + qq[1] * ppt[3] + qq[2] * ppt[6],
           qq[0] * ppt[1] + qq[1] * ppt[4] + qq[2] * ppt[7],
           qq[0] * ppt[2] + qq[1] * ppt[5] + qq[2] * ppt[8],
           qq[3] * ppt[0] + qq[4] * ppt[3] + qq[5] * ppt[6],
           qq[3] * ppt[1] + qq[4] * ppt[4] + qq[5] * ppt[7],
           qq[3] * ppt[2] + qq[4] * ppt[5] + qq[5] * ppt[8],
           qq[6] * ppt[0] + qq[7] * ppt[3] + qq[8] * ppt[6],
           qq[6] * ppt[1] + qq[7] * ppt[4] + qq[8] * ppt[7],
           qq[6] * ppt[2] + qq[7] * ppt[5] + qq[8] * ppt[8])
    q = mat_apply(rot, pts[0])
    t = (pts[3][0] - q[0], pts[3][1] - q[1], pts[3][2] - q[2])
    return (rot, t)


def matrix44(m16: Tuple[float, ...]) -> Affine:
    """*DEFINE_TRANSFORMATION MATRIX (R16): node (x,y,z,1)·M — row-vector
    convention, so the linear part is the transpose of the upper-left 3×3 and
    the translation is row 4 (M41 M42 M43)."""
    m: Mat3 = (m16[0], m16[4], m16[8],
               m16[1], m16[5], m16[9],
               m16[2], m16[6], m16[10])
    return (m, (m16[12], m16[13], m16[14]))


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_TRANSFORMATION row composition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransformRow:
    """One OPTION card of a *DEFINE_TRANSFORMATION (A1..A7 as floats; MATRIX
    additionally carries its 16 values from cards 3-4)."""
    verb: str
    a: Tuple[float, ...]                      # always length 7
    matrix: Optional[Tuple[float, ...]] = None


#: Verbs this module composes numerically. Anything else is warned + skipped.
SUPPORTED_VERBS = frozenset({
    "TRANSL", "TRANSL2ND", "ROTATE", "ROTATE3NA", "SCALE", "MIRROR",
    "POINT", "POS6P", "POS6N", "MATRIX",
})


def compose_rows(rows: List[TransformRow],
                 node_coord: Callable[[int], Optional[Vec3]],
                 node_in_scope: Callable[[int], bool],
                 warn: Callable[[str], None],
                 label: str) -> Affine:
    """Compose the rows of one *DEFINE_TRANSFORMATION into a single affine.

    *node_coord* returns the parse-time (pre-transform) coordinates of a node
    id, or None when unknown; *node_in_scope* is True for nodes that are moved
    by this very transform (their reference coordinates are pushed through the
    rows composed so far, the starter's RTRANSPOS intent). Rows that cannot be
    resolved (unknown verb, missing node/POINT, degenerate geometry) are
    SKIPPED with a loud warning — the caller decides what to do with the
    (then incomplete) result.
    """
    acc = IDENTITY
    points: Dict[int, Vec3] = {}

    def _node(fid: float, what: str, verb: str) -> Optional[Vec3]:
        nid = int(fid)
        p = node_coord(nid) if nid > 0 else None
        if p is None:
            warn(f"{label}: {verb} references {what} node {nid} which is not "
                 "defined in the deck — this row is SKIPPED, the composed "
                 "transform is INCOMPLETE; verify the geometry.")
            return None
        return affine_apply(acc, p) if node_in_scope(nid) else p

    for row in rows:
        verb, a = row.verb, row.a
        step: Optional[Affine] = None

        if verb == "POINT":
            # Local point table (no geometric effect). dyna2rad stores the raw
            # card coordinates (convertdefinetransform.cxx fills mapPointIdx in
            # the same top-to-bottom sweep) — the R16 manual's "points are
            # transformed by transforms preceding their reference" is NOT what
            # dyna2rad/OpenRadioss do, and we match dyna2rad.
            points[int(a[0])] = (a[1], a[2], a[3])
            continue

        if verb == "TRANSL":
            step = translation(a[0], a[1], a[2])

        elif verb == "TRANSL2ND":
            p1 = _node(a[0], "first", verb)
            p2 = _node(a[1], "second", verb)
            if p1 is None or p2 is None:
                continue
            d = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
            ln = math.sqrt(sum(x * x for x in d))
            if ln <= 0.0:
                warn(f"{label}: TRANSL2ND nodes {int(a[0])}/{int(a[1])} are "
                     "coincident — no direction, row SKIPPED.")
                continue
            mag = a[2]
            # A3 = 0 → translate by the full node1→node2 vector (R16 manual;
            # dyna2rad would build a zero translation here — a known defect).
            f = 1.0 if mag == 0.0 else mag / ln
            step = translation(d[0] * f, d[1] * f, d[2] * f)

        elif verb == "ROTATE":
            if a[3] == 0.0 and a[4] == 0.0 and a[5] == 0.0 and a[6] == 0.0:
                # Two-POINT form (cfg preread heuristic: A4-A7 all zero/blank):
                # A1/A2 = POINT ids, A3 = angle; axis POINT1 → POINT2.
                pid1, pid2 = int(a[0]), int(a[1])
                p1, p2 = points.get(pid1), points.get(pid2)
                if p1 is None or p2 is None:
                    missing = pid1 if p1 is None else pid2
                    warn(f"{label}: ROTATE (two-point form) references POINT "
                         f"{missing} with no preceding POINT row — row SKIPPED, "
                         "the transform is INCOMPLETE.")
                    continue
                center = p1
                axis = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
                ang = a[2]
            else:
                # Direction form: axis (A1,A2,A3) through point (A4,A5,A6),
                # angle A7 degrees.
                center = (a[3], a[4], a[5])
                axis = (a[0], a[1], a[2])
                ang = a[6]
            if ang == 0.0:
                continue                       # starter no-op (lectrans.F:334)
            step = rotation_deg(center, axis, ang)
            if step is None:
                warn(f"{label}: ROTATE has a zero-length axis — row SKIPPED.")
                continue

        elif verb == "ROTATE3NA":
            p1 = _node(a[0], "first", verb)
            p2 = _node(a[1], "second", verb)
            if p1 is None or p2 is None:
                continue
            # Axis direction node1→node2 through node3 (R16 manual; the
            # OpenRadioss starter ignores node3 and pivots at node1 — we keep
            # the LS-DYNA meaning since node3 is what the deck author wrote).
            center = p1
            if int(a[2]) > 0:
                p3 = _node(a[2], "pivot", verb)
                if p3 is None:
                    continue
                center = p3
            if a[3] == 0.0:
                continue
            step = rotation_deg(center, (p2[0] - p1[0], p2[1] - p1[1],
                                         p2[2] - p1[2]), a[3])
            if step is None:
                warn(f"{label}: ROTATE3NA nodes {int(a[0])}/{int(a[1])} are "
                     "coincident — no axis, row SKIPPED.")
                continue

        elif verb == "SCALE":
            step = scale_about_origin(a[0], a[1], a[2])

        elif verb == "MIRROR":
            if a[6] != 0.0:
                warn(f"{label}: MIRROR A7={a[6]:g} (also mirror coordinate "
                     "systems) is NOT applied — only node coordinates are "
                     "reflected; local systems in the include keep their "
                     "right-handed orientation.")
            step = mirror((a[0], a[1], a[2]), (a[3], a[4], a[5]))
            if step is None:
                warn(f"{label}: MIRROR plane point and normal point coincide — "
                     "row SKIPPED.")
                continue

        elif verb in ("POS6P", "POS6N"):
            pts: List[Vec3] = []
            ok = True
            for k in range(6):
                if verb == "POS6P":
                    p = points.get(int(a[k]))
                    if p is None:
                        warn(f"{label}: POS6P references POINT {int(a[k])} with "
                             "no preceding POINT row — row SKIPPED, the "
                             "transform is INCOMPLETE.")
                        ok = False
                        break
                else:
                    p = _node(a[k], f"position{k + 1}", verb)
                    if p is None:
                        ok = False
                        break
                pts.append(p)
            if not ok:
                continue
            step = position_map(pts)
            if step is None:
                warn(f"{label}: {verb} start/target points are degenerate "
                     "(coincident or collinear) — row SKIPPED.")
                continue

        elif verb == "MATRIX":
            if row.matrix is None or len(row.matrix) < 16:
                warn(f"{label}: MATRIX option without its two Mij cards — row "
                     "SKIPPED.")
                continue
            step = matrix44(row.matrix)

        else:
            warn(f"{label}: unsupported *DEFINE_TRANSFORMATION option "
                 f"'{verb}' — this row is SKIPPED and the composed transform "
                 "is INCOMPLETE; the resulting geometry is wrong if the row "
                 "is load-bearing.")
            continue

        acc = affine_compose(step, acc)

    return acc
