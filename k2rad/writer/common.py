"""Shared low-level helpers: field formatting, group/surface emitters, small vector math."""

from __future__ import annotations

from typing import List, Set
from ..state import ConversionState

__all__ = [
    "HDR",
    "_f",
    "_i",
    "_dof_string",
    "_vsub",
    "_vcross",
    "_vnorm",
    "_elform_to_ishell",
    "_elform_to_isolid",
    "_emit_grnod_node",
    "_emit_grshel",
    "_emit_id_group",
    "_emit_surf_part",
    "_emit_surf_grshel",
    "_emit_surf_surf",
    "_make_master_surface",
    "_ordered_unique_nodes",
    "_fmt_eid_list",
    "_discrete_part_ids",
    "_spotweld_beam_pids",
    "_emit_surf_seg",
]


HDR = "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|"


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v: float, w: int = 20) -> str:
    """Right-aligned float field of width *w*."""
    if v == 0.0:
        s = "0"
    elif abs(v) >= 1e15 or (0.0 < abs(v) < 1e-4):
        s = f"{v:.6E}"
    else:
        s = f"{v:.10G}"
    return s.rjust(w)


def _i(v: int, w: int = 10) -> str:
    return str(v).rjust(w)


def _dof_string(dx: int, dy: int, dz: int) -> str:
    return f"{dx}{dy}{dz}"


# ── Small 3-vector helpers (for /SKEW/FIX axis construction) ──────────────────

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vnorm(a):
    import math
    m = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if m == 0.0:
        return None
    return (a[0] / m, a[1] / m, a[2] / m)


def _elform_to_ishell(elform: int, is_implicit: bool) -> int:
    if is_implicit:
        return 24   # QBAT – recommended for implicit
    return 24 if elform in {-16, 9, 20, 21, 26} else 12


def _elform_to_isolid(elform: int) -> int:
    # 17 = 8-node full integration (iso-parametric) — correct for structural solids in implicit.
    # 14 = tet4 (Kessler).  2 = HEPH.
    return {0: 17, 1: 17, 2: 2, 10: 14, 13: 14, 16: 17, -1: 17}.get(elform, 17)


# ─────────────────────────────────────────────────────────────────────────────
# Group emitters (shared by Starter sections)
# ─────────────────────────────────────────────────────────────────────────────

def _emit_grnod_node(grnod_id: int, title: str, nids: List[int]) -> List[str]:
    lines = [f"/GRNOD/NODE/{grnod_id}", title or f"GRNOD_{grnod_id}"]
    row: List[str] = []
    for n in nids:
        row.append(str(n).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_grshel(grshel_id: int, title: str, eids: List[int]) -> List[str]:
    lines = [f"/GRSHEL/SHEL/{grshel_id}", title or f"GRSHEL_{grshel_id}"]
    row: List[str] = []
    for e in eids:
        row.append(str(e).rjust(10))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_id_group(keyword: str, group_id: int, title: str, ids: List[int]) -> List[str]:
    """Generic id-list group block (/GRBRIC/BRIC, /GRBEAM/BEAM, ...): header,
    title, then ids 10 per row."""
    lines = [f"/{keyword}/{group_id}", title or f"{keyword.split('/')[0]}_{group_id}"]
    row: List[str] = []
    for v in ids:
        row.append(_i(v))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_part(surf_id: int, title: str, pids: List[int]) -> List[str]:
    lines = [f"/SURF/PART/EXT/{surf_id}", title or f"SURF_PART_{surf_id}"]
    row: List[str] = []
    for p in pids:
        row.append(_i(p))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _emit_surf_grshel(surf_id: int, title: str, grshel_id: int) -> List[str]:
    return [
        f"/SURF/GRSHEL/{surf_id}",
        title or f"SURF_GRSHEL_{surf_id}",
        f"{_i(grshel_id)}",
        HDR,
    ]


def _emit_surf_surf(surf_id: int, title: str, sub_surf_ids: List[int]) -> List[str]:
    lines = [f"/SURF/SURF/{surf_id}", title or f"SURF_SURF_{surf_id}"]
    row: List[str] = []
    for s in sub_surf_ids:
        row.append(_i(s))
        if len(row) == 10:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    lines.append(HDR)
    return lines


def _make_master_surface(state: ConversionState, surf_id: int, title: str,
                         pids: List[int], out_lines: List[str]) -> bool:
    """Emit a master surface (for /INTER) from a list of PIDs."""
    shell_eids: List[int] = []
    solid_pids: List[int] = []
    for pid in sorted(pids):
        eids_in_pid = [e.eid for e in state.shell_elems if e.pid == pid]
        has_solids = any(e.pid == pid for e in state.solid_elems)
        if eids_in_pid:
            shell_eids.extend(eids_in_pid)
        elif has_solids:
            solid_pids.append(pid)

    shell_eids.sort()

    if shell_eids and not solid_pids:
        grshel_id = state.next_id()
        out_lines += _emit_grshel(grshel_id, f"{title}_grshel", shell_eids)
        out_lines += _emit_surf_grshel(surf_id, title, grshel_id)
        return True
    if solid_pids and not shell_eids:
        out_lines += _emit_surf_part(surf_id, title, solid_pids)
        return True
    if shell_eids and solid_pids:
        grshel_id = state.next_id()
        sub_shell = state.next_id()
        sub_solid = state.next_id()
        out_lines += _emit_grshel(grshel_id, f"{title}_grshel", shell_eids)
        out_lines += _emit_surf_grshel(sub_shell, f"{title}_shells", grshel_id)
        out_lines += _emit_surf_part(sub_solid, f"{title}_solids", solid_pids)
        out_lines += _emit_surf_surf(surf_id, title, [sub_shell, sub_solid])
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Starter: parts + elements
# ─────────────────────────────────────────────────────────────────────────────

def _ordered_unique_nodes(nodes: List[int]) -> List[int]:
    """Distinct positive node IDs, preserving first-seen order.

    LS-DYNA stores a 4-node tet either as 4 IDs or as an 8-slot hex with
    nodes 5-8 collapsed onto node 4 (e.g. n1 n2 n3 n4 n4 n4 n4 n4). Either
    way this returns the 4 distinct corners, so callers can detect tets.
    """
    seen: Set[int] = set()
    out: List[int] = []
    for n in nodes:
        if n > 0 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _fmt_eid_list(eids: List[int], limit: int = 25) -> str:
    """Comma-separated element IDs, truncated past *limit* with a count."""
    s = ", ".join(str(e) for e in eids[:limit])
    if len(eids) > limit:
        s += f", ... (+{len(eids) - limit} more)"
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Starter: connectors (*ELEMENT_DISCRETE springs/dampers, spotwelds)
# ─────────────────────────────────────────────────────────────────────────────

def _discrete_part_ids(state: ConversionState) -> Set[int]:
    """Part ids handled by the discrete-spring connector path: parts referenced
    by *ELEMENT_DISCRETE, or whose section is a *SECTION_DISCRETE, or whose
    material is a discrete spring/damper material. These are skipped by the
    normal /PART emission (their /PART + /PROP/TYPE4 come from
    _make_discrete_springs; the DYNA section/material ids have no /PROP or
    /MAT of their own)."""
    spring_mids = (set(state.mat_spring_elastic) | set(state.mat_spring_nonlinear)
                   | set(state.mat_damper_viscous))
    pids = {e.pid for e in state.discrete_elems}
    for pid, p in state.parts.items():
        secid = p.secid if p.secid > 0 else pid
        if secid in state.sec_discrete or p.mid in spring_mids:
            pids.add(pid)
    return pids


def _spotweld_beam_pids(state: ConversionState) -> Set[int]:
    """*MAT_SPOTWELD (MAT_100) parts whose elements are exclusively beams —
    these become /PROP/TYPE13 (SPR_BEAM) /SPRING connectors. MAT_100 on
    shell/solid (hexa) spotwelds is NOT converted (falls back to /MAT/ELAST)."""
    if not state.mat_spotweld:
        return set()
    shell_pids = {e.pid for e in state.shell_elems}
    solid_pids = {e.pid for e in state.solid_elems}
    beam_pids = {e.pid for e in state.beam_elems}
    return {pid for pid, p in state.parts.items()
            if p.mid in state.mat_spotweld and pid in beam_pids
            and pid not in shell_pids and pid not in solid_pids}


def _emit_surf_seg(surf_id: int, title: str, segments) -> List[str]:
    """A /SURF/SEG from a list of node lists (shared by blast/EBCS/FSI)."""
    lines = [f"/SURF/SEG/{surf_id}", (title or f"surf_seg_{surf_id}")[:100],
             "#   seg_ID        n1        n2        n3        n4"]
    for seg_no, nodes in enumerate(segments, start=1):
        quad = (list(nodes) + [0, 0, 0, 0])[:4]
        lines.append(_i(seg_no) + "".join(_i(n) for n in quad))
    lines.append(HDR)
    return lines
