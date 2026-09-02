"""
k2rad.topology  –  neutral element-connectivity facts shared across the package.

These are pure mesh-topology constants/helpers with no dependency on the writer
or the parser, so both the writer and the optional ``gapmin`` proximity path can
import them without dragging in the whole output stage. (Previously
``gapmin.py`` reached into ``writer._TET10_MIDEDGE`` directly.)
"""

from math import sqrt
from typing import List, Optional, Sequence, Tuple

# Mid-edge node -> (corner A, corner B) of its edge in the **Radioss /TETRA10**
# convention (identical to Abaqus C3D10). Indices are 0-based positions into the
# 10-node connectivity list:
#   node5=mid(1,2), node6=mid(2,3), node7=mid(1,3),
#   node8=mid(1,4), node9=mid(2,4), node10=mid(3,4).
# This is the ONE convention every downstream consumer (the snap pass, the gapmin
# contact faceting, and the /TETRA10 emit) reads through, and it is what the
# engine's own s10mass3.F / dim_s10edg.F integration tables expect.
#
# LS-DYNA *ELEMENT_SOLID differs on the three APEX midsides only:
#   LS-DYNA node8=mid(2,4), node9=mid(3,4), node10=mid(1,4).
# A LS-DYNA deck's connectivity is permuted to this Radioss order by
# writer.mesh._normalize_tet10_ordering (via TET10_DYNA_TO_RADIOSS) BEFORE any of
# those consumers run, so they only ever see Radioss-ordered midsides.
# (An earlier revision mislabeled this map as the "LS-DYNA/Abaqus/Nastran"
# convention and called the LS-DYNA map a "cyclic rotation"; that conflation was
# the root cause of the ERROR 558 snap-collapse regression — the two orderings
# are genuinely different, not a relabeling.)
TET10_MIDEDGE = [(4, 0, 1), (5, 1, 2), (6, 0, 2), (7, 0, 3), (8, 1, 3), (9, 2, 3)]

# Convenience: {frozenset(cornerA, cornerB): mid-node index} for edge lookups.
TET10_EDGEMID = {frozenset((a, b)): m for (m, a, b) in TET10_MIDEDGE}

# (The LS-DYNA apex order — node8=mid(2,4), node9=mid(3,4), node10=mid(1,4) — is
# documented above; it is never materialized as a map because detection is purely
# geometric via classify_tet10_apex_order and the permutation below is the only
# action ever applied.)
#
# Permutation that maps an LS-DYNA-ordered 10-node connectivity to Radioss order,
# as new = [nodes[p] for p in TET10_DYNA_TO_RADIOSS]. Corners 1-4 and base
# midsides 5/6/7 are identity; the three apex slots cycle:
#   radioss[7] = dyna[9] (mid(1,4)),
#   radioss[8] = dyna[7] (mid(2,4)),
#   radioss[9] = dyna[8] (mid(3,4)).
# This is a 3-cycle on slots {7,8,9} (period 3, NOT self-inverse), so applying it
# twice corrupts the connectivity — callers must guard against a double apply.
TET10_DYNA_TO_RADIOSS = (0, 1, 2, 3, 4, 5, 6, 9, 7, 8)

Coord = Tuple[float, float, float]


def _dist(p: Coord, q: Coord) -> float:
    return sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)


def classify_tet10_apex_order(
    corners: Optional[Sequence[Optional[Coord]]],
    apex_mids: Optional[Sequence[Optional[Coord]]],
    off_edge_frac: float = 0.25,
) -> str:
    """Classify one 10-node tet's *apex* midside ordering purely from geometry.

    *corners* is the 4 corner coordinates (each ``(x, y, z)`` or ``None``);
    *apex_mids* is the 3 apex midside coordinates for connectivity slots 8/9/10
    (0-based 7/8/9), each ``(x, y, z)`` or ``None``. Returns ``"dyna"``,
    ``"radioss"``, or ``"ambiguous"``.

    The three apex edges all meet corner 4 — edges (1,4), (2,4), (3,4), i.e.
    0-based (0,3), (1,3), (2,3) — so each apex midside node must sit on one of
    those three edge midpoints. The two conventions assign them to different
    slots::

                slot8 (idx7)  slot9 (idx8)  slot10 (idx9)
        DYNA:     mid(2,4)      mid(3,4)      mid(1,4)
        Radioss:  mid(1,4)      mid(2,4)      mid(3,4)

    Classification is nearest-edge-midpoint (as in the tet10_order_sweep.py
    diagnosis) with an off-edge guard: if any apex node is farther than
    ``off_edge_frac`` of its matched edge length from every apex-edge midpoint,
    or the resulting slot->edge assignment is not one of the two clean patterns,
    the element is ``"ambiguous"``. Missing coordinates → ``"ambiguous"``.
    """
    # Split from two compound guards so the None exclusion is visible to a
    # reader and to a type checker; every arm returns the same "ambiguous".
    if corners is None or len(corners) < 4:
        return "ambiguous"
    c0, c1, c2, c3 = corners[0], corners[1], corners[2], corners[3]
    if c0 is None or c1 is None or c2 is None or c3 is None:
        return "ambiguous"
    if apex_mids is None or len(apex_mids) < 3:
        return "ambiguous"
    apex: List[Coord] = []
    for m in apex_mids[:3]:
        if m is None:
            return "ambiguous"
        apex.append(m)
    # apex-edge midpoints, indexed 0->(0,3), 1->(1,3), 2->(2,3)
    mids: List[Coord] = [
        ((c0[0] + c3[0]) / 2.0, (c0[1] + c3[1]) / 2.0, (c0[2] + c3[2]) / 2.0),
        ((c1[0] + c3[0]) / 2.0, (c1[1] + c3[1]) / 2.0, (c1[2] + c3[2]) / 2.0),
        ((c2[0] + c3[0]) / 2.0, (c2[1] + c3[1]) / 2.0, (c2[2] + c3[2]) / 2.0),
    ]
    elens = [_dist(c0, c3), _dist(c1, c3), _dist(c2, c3)]
    assign: List[int] = []
    for p in apex:
        d = [_dist(p, mids[e]) for e in range(3)]
        best = min(range(3), key=lambda e: d[e])
        if elens[best] <= 0.0 or d[best] > off_edge_frac * elens[best]:
            return "ambiguous"
        assign.append(best)
    t = tuple(assign)
    if t == (1, 2, 0):
        return "dyna"
    if t == (0, 1, 2):
        return "radioss"
    return "ambiguous"
