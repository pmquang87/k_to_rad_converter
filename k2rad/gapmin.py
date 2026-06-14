"""
k2rad.gapmin  –  suggest a per-interface /INTER/TYPE7 Gapmin from the *actual
mesh clearance* between the two contacting parts.

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

The closest approach between the two parts' nodes is a direct, mesh-specific
proxy for that clearance.  Hand-tuning *CONTACT Card-3 SST/SBST per mesh (what
made the TET4 deck converge while the re-used uniform value stalled the finer
TET10 deck) is exactly what this module automates:

    Gapmin = factor × (min node-to-node distance between the two parts),  factor<1

Node-to-node distance is an *upper bound* on the true node-to-segment clearance
(the nearest point of a segment can lie on its interior, closer than any of its
nodes), so factor<1 also absorbs that overestimate and keeps the gap below the
clearance.

This module is pure standard-library (the converter has a zero third-party
dependency policy), so the minimum distance is found with an adaptive uniform
spatial grid rather than a KD-tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isinf, sqrt
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .state import ConversionState

# Default safety factor: Gapmin = DEFAULT_GAPMIN_FACTOR × (min nodal clearance).
# <1 so the gap stays below the clearance (0 initial penetration); close enough
# to 1 that the contact still engages promptly under load.  Lower it (e.g. 0.5)
# if an interface still reports initial penetration on a coarse main mesh; raise
# it toward 1.0 if a contact fails to engage.
DEFAULT_GAPMIN_FACTOR = 0.8

Coord = Tuple[float, float, float]


# ─────────────────────────────────────────────────────────────────────────────
# Minimum distance between two point clouds (pure-Python adaptive spatial grid)
# ─────────────────────────────────────────────────────────────────────────────

def min_distance_between_coords(a: List[Coord], b: List[Coord]) -> Optional[float]:
    """Smallest Euclidean distance between any point of *a* and any point of *b*.

    Returns ``None`` when either cloud is empty.  Pure standard library: a
    uniform grid (cell size *h*) is built over the smaller cloud and the larger
    cloud is queried against the 27 surrounding cells.

    Correctness: if two points are ≤ *h* apart their grid cells differ by at most
    1 on each axis, so the 27-cell scan finds *every* pair closer than *h*.
    Hence a result ``best ≤ h`` is exact.  If ``best > h`` (or nothing is found)
    the cell is grown and the pass repeats; this converges in a couple of passes.
    """
    if not a or not b:
        return None
    grid_pts, query_pts = (a, b) if len(a) <= len(b) else (b, a)

    # Initial cell size ≈ characteristic node spacing of the grid cloud.
    xs = [p[0] for p in grid_pts]
    ys = [p[1] for p in grid_pts]
    zs = [p[2] for p in grid_pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    if span <= 0.0:
        span = 1.0
    h = span / max(1.0, round(len(grid_pts) ** (1.0 / 3.0)))
    if h <= 0.0:
        h = span

    best = float("inf")
    for _ in range(64):                         # bounded adaptive refinement
        inv = 1.0 / h
        cells: Dict[Tuple[int, int, int], List[Coord]] = {}
        for p in grid_pts:
            key = (floor(p[0] * inv), floor(p[1] * inv), floor(p[2] * inv))
            cells.setdefault(key, []).append(p)

        best2 = float("inf")
        for q in query_pts:
            ci = floor(q[0] * inv)
            cj = floor(q[1] * inv)
            ck = floor(q[2] * inv)
            qx, qy, qz = q
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for dk in (-1, 0, 1):
                        bucket = cells.get((ci + di, cj + dj, ck + dk))
                        if not bucket:
                            continue
                        for rx, ry, rz in bucket:
                            dx = qx - rx
                            dy = qy - ry
                            dz = qz - rz
                            d2 = dx * dx + dy * dy + dz * dz
                            if d2 < best2:
                                best2 = d2
            if best2 == 0.0:
                return 0.0

        if isinf(best2):
            h *= 2.0                             # cell too small — nothing nearby
            continue
        best = sqrt(best2)
        if best <= h:                            # validated exact (see docstring)
            return best
        h = best                                 # grow so the next pass validates
    return None if isinf(best) else best


def _round_sig(x: float, sig: int = 4) -> float:
    """Round *x* to *sig* significant figures for a tidy, reproducible Gapmin."""
    if x == 0.0:
        return 0.0
    from math import floor as _floor, log10
    digits = sig - 1 - _floor(log10(abs(x)))
    return round(x, digits)


# ─────────────────────────────────────────────────────────────────────────────
# Resolving a *CONTACT side to its mesh nodes
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


def min_node_distance(state: ConversionState, pids_a: Iterable[int],
                      pids_b: Iterable[int]) -> Optional[float]:
    """Minimum node-to-node distance between two groups of parts.

    A general-purpose helper: gather every node of *pids_a* and of *pids_b*
    (dropping any node shared by both), then return their closest approach, or
    ``None`` if either group has no nodes of its own."""
    part_nodes = _part_nodes_map(state)
    a: Set[int] = set()
    for p in pids_a:
        a.update(part_nodes.get(p, ()))
    b: Set[int] = set()
    for p in pids_b:
        b.update(part_nodes.get(p, ()))
    shared = a & b
    a -= shared
    b -= shared
    return min_distance_between_coords(_coords_for(state, a), _coords_for(state, b))


# ─────────────────────────────────────────────────────────────────────────────
# Per-interface Gapmin suggestion
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GapminSuggestion:
    inter_id: int
    title: str
    side_a: str               # human description of the secondary side
    side_b: str               # human description of the main side
    min_distance: float       # closest node-to-node approach between the parts
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
    *distinct* parts, from the closest node-to-node approach between them.

    Returns ``(suggestions, skipped)`` where *suggestions* maps inter_id →
    :class:`GapminSuggestion` and *skipped* maps inter_id → a reason string
    (self-contacts, single-surface contacts and unresolvable sides — none of
    which have a meaningful "clearance between two parts").
    """
    part_nodes = _part_nodes_map(state)
    suggestions: Dict[int, GapminSuggestion] = {}
    skipped: Dict[int, str] = {}

    # Single-surface (self / all-parts) contacts have no two-part clearance.
    for c in state.contacts_single:
        skipped[c.inter_id] = "single-surface self-contact (no two-part clearance)"

    for c in state.contacts_surf2surf:
        a_pids = _side_pids(state, c.ssid, c.sstyp)
        b_pids = _side_pids(state, c.msid, c.mstyp)
        if a_pids is not None and b_pids is not None and a_pids and a_pids == b_pids:
            skipped[c.inter_id] = "self-contact (same part on both sides)"
            continue

        a_nodes = _side_node_ids(state, c.ssid, c.sstyp, part_nodes)
        b_nodes = _side_node_ids(state, c.msid, c.mstyp, part_nodes)
        shared = a_nodes & b_nodes
        a_nodes -= shared
        b_nodes -= shared
        if not a_nodes or not b_nodes:
            skipped[c.inter_id] = "a side has no nodes of its own (empty or fully shared)"
            continue

        d = min_distance_between_coords(_coords_for(state, a_nodes),
                                        _coords_for(state, b_nodes))
        if d is None or d <= 0.0:
            skipped[c.inter_id] = "degenerate clearance (coincident nodes)"
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


def apply_auto_gapmin(state: ConversionState) -> None:
    """Compute suggested Gapmins and merge them into ``state.options.inter_gapmin``
    (so the existing writer Gapmin path emits them), warning per interface.

    An explicit ``--inter-gapmin`` for an interface always wins over the
    suggestion.  Called by :func:`k2rad.convert` when ``auto_gapmin`` is on.
    """
    factor = state.options.gapmin_factor
    suggestions, skipped = suggest_gapmins(state, factor)

    for iid, s in sorted(suggestions.items()):
        if iid in state.options.inter_gapmin:
            state.warn(
                f"--auto-gapmin INTER {iid} ({s.title}): kept explicit --inter-gapmin "
                f"{state.options.inter_gapmin[iid]:g} (mesh clearance "
                f"{s.side_a} ↔ {s.side_b} = {s.min_distance:g}, suggestion was "
                f"{s.suggested_gapmin:g})."
            )
            continue
        state.options.inter_gapmin[iid] = s.suggested_gapmin
        state.warn(
            f"--auto-gapmin INTER {iid} ({s.title}): min node clearance "
            f"{s.side_a} ↔ {s.side_b} = {s.min_distance:g} → Gapmin="
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
    "min_distance_between_coords",
    "min_node_distance",
    "suggest_gapmins",
    "apply_auto_gapmin",
    "analyze_file",
]
