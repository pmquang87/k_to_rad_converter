#!/usr/bin/env python3
"""
modal_common.py – shared helpers for the offline modal post-processing tools.

Used by tools/modal_shapes_export.py (mode-shape d3plot/VTK export) and
tools/modal_random_response.py (PSD / RMS / Dirlik-fatigue post-processing).
Everything here works on the two artifacts a k2rad modal run produces:

* ``<jobname>_modes.npz`` written by tools/modal_solve.py with keys
  ``freq``      – natural frequencies in cycles per deck TIME unit
                  (kg-mm-ms deck → kHz),
  ``phi``       – (n_free_dofs × n_modes) mass-normalized mode shapes,
  ``user_node`` – user node id per phi row,
  ``dof``       – 1..6 = TX,TY,TZ,RX,RY,RZ per phi row,
  ``gids``      – original stiffness-matrix indices (6·(node-1)+dof);
* the source LS-DYNA ``.k`` file, parsed with the k2rad package.

Deck-unit heuristic
-------------------
The npz frequencies are in cycles per deck time-unit, but nothing in the file
records what that unit is.  :func:`detect_freq_scale` guesses the ``freq → Hz``
factor from the deck itself (gravity magnitude, then material wave speed +
model size) so a kg-mm-ms deck is labelled 44.5 Hz instead of 0.0445.  The
guess is printed and can always be overridden with ``--time-unit``.

Dependencies: numpy (same optional stack as tools/modal_solve.py).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# k2rad lives one directory up from tools/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402

try:                                             # pragma: no cover - env dependent
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:                              # pragma: no cover - env dependent
    np = None
    _HAVE_NUMPY = False


def parse_deck(k_path: str) -> ConversionState:
    state = ConversionState()
    for block in parse_k_file(k_path):
        dispatch(block, state)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Mode set (the modal_solve.py npz)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModeSet:
    """Contents of a tools/modal_solve.py ``*_modes.npz``."""
    freq: "np.ndarray"       # (n_modes,) cycles per deck time-unit
    phi: "np.ndarray"        # (n_free_dofs, n_modes) mass-normalized
    user_node: "np.ndarray"  # (n_free_dofs,) user node id per row
    dof: "np.ndarray"        # (n_free_dofs,) 1..6 = TX,TY,TZ,RX,RY,RZ

    @property
    def n_modes(self) -> int:
        return len(self.freq)


def load_modes(npz_path: str) -> ModeSet:
    """Read a modal_solve.py output npz into a :class:`ModeSet`."""
    if not _HAVE_NUMPY:
        raise RuntimeError("numpy is required to read the modes .npz "
                           "(pip install numpy - see docs/DEPENDENCIES.md)")
    d = np.load(npz_path)
    for key in ("freq", "phi", "user_node", "dof"):
        if key not in d.files:
            raise ValueError(f"{npz_path}: missing key {key!r} - not a "
                             "tools/modal_solve.py output file")
    return ModeSet(freq=d["freq"], phi=d["phi"],
                   user_node=d["user_node"].astype(np.int64),
                   dof=d["dof"].astype(np.int64))


# ─────────────────────────────────────────────────────────────────────────────
# Mesh arrays from the parsed deck
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Mesh:
    """Node/element arrays (0-based indexed) built from a parsed .k deck.

    Elements keep the deck's user ids and are sorted by id within each family.
    ``*_conn`` holds 0-based indices into ``node_ids``/``coords``.  The overall
    cell order for VTK cell data is shells, then solids, then beams.
    """
    node_ids: "np.ndarray"           # (n_nodes,) sorted user node ids
    coords: "np.ndarray"             # (n_nodes, 3)
    nid_to_idx: Dict[int, int]
    shell_ids: "np.ndarray"          # (n_shells,)
    shell_conn: List[List[int]]      # 3 or 4 node indices each
    shell_part: "np.ndarray"         # (n_shells,) 0-based part index
    solid_ids: "np.ndarray"
    solid_conn: List[List[int]]      # 4, 8 or 10 node indices each
    solid_part: "np.ndarray"
    beam_ids: "np.ndarray"
    beam_conn: List[List[int]]       # 2 node indices each
    beam_part: "np.ndarray"
    part_ids: "np.ndarray"           # (n_parts,) sorted user part ids
    part_titles: List[str]
    warnings: List[str] = field(default_factory=list)

    @property
    def n_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def n_cells(self) -> int:
        return len(self.shell_conn) + len(self.solid_conn) + len(self.beam_conn)

    def bbox_diagonal(self) -> float:
        if not len(self.coords):
            return 1.0
        span = self.coords.max(axis=0) - self.coords.min(axis=0)
        return float(np.linalg.norm(span)) or 1.0


def build_mesh(state: ConversionState) -> Mesh:
    """Assemble sorted node/element/part arrays from a parsed deck."""
    if not _HAVE_NUMPY:
        raise RuntimeError("numpy is required (pip install numpy)")
    node_ids = np.array(sorted(state.nodes), dtype=np.int64)
    nid_to_idx = {int(n): i for i, n in enumerate(node_ids)}
    coords = np.array([[state.nodes[int(n)].x,
                        state.nodes[int(n)].y,
                        state.nodes[int(n)].z] for n in node_ids],
                      dtype=np.float64).reshape(len(node_ids), 3)

    part_ids = np.array(sorted(state.parts), dtype=np.int64)
    pid_to_idx = {int(p): i for i, p in enumerate(part_ids)}
    part_titles = [state.parts[int(p)].title or f"part_{int(p)}"
                   for p in part_ids]
    warnings: List[str] = []

    def collect(elems, get_nodes, family: str):
        ids, conns, parts, dropped = [], [], [], 0
        for e in elems:
            try:
                conn = [nid_to_idx[n] for n in get_nodes(e)]
            except KeyError:
                dropped += 1
                continue
            ids.append(e.eid)
            conns.append(conn)
            parts.append(pid_to_idx.get(e.pid, 0))
        if dropped:
            warnings.append(f"{dropped} {family} element(s) referenced missing "
                            "nodes and were dropped from the export")
        order = np.argsort(np.asarray(ids, dtype=np.int64), kind="stable")
        return (np.asarray(ids, dtype=np.int64)[order],
                [conns[i] for i in order],
                np.asarray(parts, dtype=np.int64)[order]
                if len(parts) else np.zeros(0, dtype=np.int64))

    shell_ids, shell_conn, shell_part = collect(
        state.shell_elems, lambda e: e.nodes, "shell")
    solid_ids, solid_conn, solid_part = collect(
        state.solid_elems, lambda e: e.nodes, "solid")
    beam_ids, beam_conn, beam_part = collect(
        state.beam_elems, lambda e: (e.n1, e.n2), "beam")

    return Mesh(node_ids=node_ids, coords=coords, nid_to_idx=nid_to_idx,
                shell_ids=shell_ids, shell_conn=shell_conn, shell_part=shell_part,
                solid_ids=solid_ids, solid_conn=solid_conn, solid_part=solid_part,
                beam_ids=beam_ids, beam_conn=beam_conn, beam_part=beam_part,
                part_ids=part_ids, part_titles=part_titles, warnings=warnings)


def shapes_on_mesh(mesh: Mesh, modes: ModeSet,
                   rotations: bool = False) -> "np.ndarray":
    """Scatter the phi rows onto mesh nodes.

    Returns (n_modes, n_nodes, 3) translational shapes — or (n_modes, n_nodes, 6)
    with the rotational rows too when ``rotations`` is True.  Nodes absent from
    phi (constrained / rigid-slaved) stay zero, exactly like a d3eigv shape.
    """
    ncomp = 6 if rotations else 3
    out = np.zeros((modes.n_modes, mesh.n_nodes, ncomp))
    sel = modes.dof <= ncomp
    known = np.array([mesh.nid_to_idx.get(int(n), -1)
                      for n in modes.user_node[sel]], dtype=np.int64)
    ok = known >= 0
    n_missing = int((~ok).sum())
    if n_missing:
        miss = np.unique(modes.user_node[sel][~ok])
        raise ValueError(
            f"{n_missing} mode-shape rows reference nodes not in the .k mesh "
            f"(e.g. {', '.join(map(str, miss[:5]))}) - the .k file does not "
            "match the modes .npz")
    rows = known[ok]
    cols = (modes.dof[sel][ok] - 1)
    out[:, rows, cols] = modes.phi[sel][ok].T
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Deck frequency-unit heuristic
# ─────────────────────────────────────────────────────────────────────────────

def _stiffest_wave_speed(state: ConversionState) -> Optional[float]:
    """sqrt(E/rho) of the stiffest deck material, in deck units."""
    best = None
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_null, state.mat_power_law):
        for m in mats.values():
            if m.rho > 0.0 and m.E > 0.0:
                c = math.sqrt(m.E / m.rho)
                best = c if best is None else max(best, c)
    return best


def detect_freq_scale(state: ConversionState, mesh: Mesh) -> Tuple[float, str]:
    """Guess the multiplier turning npz frequencies into Hz.

    Returns (scale, reason).  scale is 1000.0 for a millisecond deck (npz
    frequencies are kHz), 1.0 for a second deck (already Hz).  Heuristics, in
    order of trust:

    1. gravity magnitude from *LOAD_GRAVITY_PART: g ≈ 0.0098 ⇒ mm/ms²
       (millisecond deck); g ≈ 9.81 ⇒ m/s²; g ≈ 9810 ⇒ mm/s²;
    2. material wave speed sqrt(E/rho): ≈ 5·10³ for steel in both mm-ms and
       m-s (numerically identical), ≈ 5·10⁶ in mm-s (ton-mm-s) — a mm-scale
       model (bounding box ≫ 100) with c ≈ 10³..10⁴ must be mm-ms;
    3. fall back to seconds (scale 1) with a warning.
    """
    for g in state.gravity_loads:
        a = abs(g.accel)
        if 0.002 <= a <= 0.05:
            return 1000.0, (f"*LOAD_GRAVITY_PART accel {g.accel:g} ~ g in "
                            "mm/ms^2 -> millisecond deck (npz frequencies are kHz)")
        if 2.0 <= a <= 50.0 or 2000.0 <= a <= 50000.0:
            return 1.0, (f"*LOAD_GRAVITY_PART accel {g.accel:g} ~ g with time "
                         "in seconds (npz frequencies are already Hz)")
    c = _stiffest_wave_speed(state)
    if c is not None:
        diag = mesh.bbox_diagonal()
        if 1.0e3 <= c <= 3.0e4:
            if diag > 100.0:
                return 1000.0, (f"material wave speed {c:.3G} + model size "
                                f"{diag:.3G} -> mm-ms deck (npz frequencies are kHz)")
            return 1.0, (f"material wave speed {c:.3G} + model size {diag:.3G} "
                         "-> m-s deck (npz frequencies are already Hz)")
        if 3.0e5 <= c <= 3.0e7:
            return 1.0, (f"material wave speed {c:.3G} -> mm-s (ton-mm-s) deck "
                         "(npz frequencies are already Hz)")
    return 1.0, ("could not identify the deck time unit - assuming seconds "
                 "(frequencies already Hz); override with --time-unit")


def freq_scale_from_args(time_unit: str, state: ConversionState,
                         mesh: Mesh) -> Tuple[float, str]:
    """Map a --time-unit CLI value (auto|s|ms) to the freq→Hz multiplier."""
    if time_unit == "s":
        return 1.0, "deck time unit forced to seconds (--time-unit s)"
    if time_unit == "ms":
        return 1000.0, "deck time unit forced to milliseconds (--time-unit ms)"
    return detect_freq_scale(state, mesh)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy-VTK writer (ParaView)
# ─────────────────────────────────────────────────────────────────────────────

# VTK cell type ids
_VTK_LINE, _VTK_TRI, _VTK_QUAD = 3, 5, 9
_VTK_TETRA, _VTK_HEXA, _VTK_QUAD_TETRA = 10, 12, 24


def _vtk_cells(mesh: Mesh) -> Tuple[List[List[int]], List[int]]:
    """Cells in the canonical order (shells, solids, beams) + VTK type ids.

    LS-DYNA and VTK use the same 10-node tet ordering (corners then mid-edge
    nodes), so a TETRA10 maps 1:1 to VTK_QUADRATIC_TETRA.
    """
    cells: List[List[int]] = []
    types: List[int] = []
    for conn in mesh.shell_conn:
        if len(conn) == 4 and len(set(conn)) == 3:      # collapsed quad = tri
            conn = list(dict.fromkeys(conn))
        cells.append(conn)
        types.append(_VTK_QUAD if len(conn) == 4 else _VTK_TRI)
    for conn in mesh.solid_conn:
        if len(conn) == 10:
            cells.append(conn); types.append(_VTK_QUAD_TETRA)
        elif len(conn) == 8:
            cells.append(conn); types.append(_VTK_HEXA)
        else:
            cells.append(conn[:4]); types.append(_VTK_TETRA)
    for conn in mesh.beam_conn:
        cells.append(conn); types.append(_VTK_LINE)
    return cells, types


def write_vtk(path: str, mesh: Mesh, comment: str = "k2rad modal export",
              point_vectors: Optional[Dict[str, "np.ndarray"]] = None,
              point_scalars: Optional[Dict[str, "np.ndarray"]] = None,
              cell_scalars: Optional[Dict[str, "np.ndarray"]] = None,
              points: Optional["np.ndarray"] = None) -> None:
    """Write a legacy ASCII VTK unstructured grid.

    ``point_vectors`` become VECTORS arrays (ready for ParaView's
    Warp By Vector), ``point_scalars``/``cell_scalars`` become SCALARS.
    ``cell_scalars`` arrays follow the mesh cell order (shells, solids, beams).
    """
    cells, types = _vtk_cells(mesh)
    pts = mesh.coords if points is None else points
    lines: List[str] = [
        "# vtk DataFile Version 3.0",
        comment[:255],
        "ASCII",
        "DATASET UNSTRUCTURED_GRID",
        f"POINTS {len(pts)} double",
    ]
    lines.extend(f"{p[0]:.9G} {p[1]:.9G} {p[2]:.9G}" for p in pts)
    total = sum(len(c) + 1 for c in cells)
    lines.append(f"CELLS {len(cells)} {total}")
    lines.extend(str(len(c)) + " " + " ".join(map(str, c)) for c in cells)
    lines.append(f"CELL_TYPES {len(cells)}")
    lines.extend(str(t) for t in types)

    if point_vectors or point_scalars:
        lines.append(f"POINT_DATA {len(pts)}")
        for name, arr in (point_vectors or {}).items():
            lines.append(f"VECTORS {name} double")
            lines.extend(f"{v[0]:.9G} {v[1]:.9G} {v[2]:.9G}" for v in arr)
        for name, arr in (point_scalars or {}).items():
            lines.append(f"SCALARS {name} double 1")
            lines.append("LOOKUP_TABLE default")
            lines.extend(f"{v:.9G}" for v in arr)
    if cell_scalars:
        lines.append(f"CELL_DATA {len(cells)}")
        for name, arr in cell_scalars.items():
            if len(arr) != len(cells):
                raise ValueError(f"cell scalar {name!r}: {len(arr)} values for "
                                 f"{len(cells)} cells")
            lines.append(f"SCALARS {name} double 1")
            lines.append("LOOKUP_TABLE default")
            lines.extend(f"{v:.9G}" for v in arr)
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Small CLI helpers
# ─────────────────────────────────────────────────────────────────────────────

def parse_mode_list(spec: Optional[str], n_modes: int) -> List[int]:
    """'1,3-5' → [1, 3, 4, 5]; None → all modes 1..n_modes (1-based)."""
    if not spec:
        return list(range(1, n_modes + 1))
    out: List[int] = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, b = tok.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(tok))
    picked = sorted(set(out))
    bad = [m for m in picked if m < 1 or m > n_modes]
    if bad:
        raise ValueError(f"mode(s) {bad} out of range 1..{n_modes}")
    return picked


def default_output_stem(npz_path: str) -> str:
    """<dir>/<jobname> from '<dir>/<jobname>_modes.npz' (or any .npz name)."""
    p = Path(npz_path)
    stem = p.name[:-len(".npz")] if p.name.endswith(".npz") else p.name
    if stem.endswith("_modes"):
        stem = stem[:-len("_modes")]
    return str(p.parent / stem)
