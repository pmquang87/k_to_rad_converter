#!/usr/bin/env python3
"""
modal_solve.py – normal modes from an OpenRadioss /IMPL/PRINT/STIF export.

The open-source OpenRadioss engine cannot solve /EIG (the eigensolver kernel is
not in the source release), so k2rad converts a *CONTROL_IMPLICIT_EIGENVALUE
deck to a one-step /IMPL/LINEAR run whose /IMPL/PRINT/STIF card makes MUMPS
write the EXACT assembled stiffness matrix it factorizes to
``local_stiffness_matrix_domain0`` (run the engine np=1).  This script finishes
the job offline:

  1. parse the exported stiffness matrix K,
  2. rebuild the lumped diagonal mass matrix M from the source .k file
     (element mass lumping + *ELEMENT_MASS point masses),
  3. solve the generalized eigenproblem  K·φ = λ·M·φ  with shift-invert
     ``scipy.sparse.linalg.eigsh`` and print  f = sqrt(λ)/2π.

Usage
-----
    python tools/modal_solve.py <local_stiffness_matrix_domain0> <model.k> \\
           [-n N_MODES] [-o modes.npz]

    # static validation: apply a point load, print displacements to compare
    # against an engine /CLOAD run (they must match to ~0% — exact-K check):
    python tools/modal_solve.py <matrix> --static NODE DIR FORCE \\
           [--sensors N1 N2 ...]

Matrix file format (engine imp_mumps.F, MUMPS assembled/coordinate format)
--------------------------------------------------------------------------
    header line:  N  N  NZ
    data lines:   II  JJ  V        (NZ lines)

* ONE triangle only (the engine swaps each pair so II >= JJ); this script
  mirrors the off-diagonal entries to build the full symmetric K.
* Duplicate (II, JJ) entries must be SUMMED (MUMPS assembled convention).
* II = 6*(USER_node_id - 1) + dof  with dof 1..6 = TX,TY,TZ,RX,RY,RZ.
  Only free (unconstrained, non-rigid-slaved) DOFs appear, so the maximum
  index can exceed the header N — the index space is the full 6·n_nodes
  USER-id grid with gaps.  (Validated on the W14 bogie: a unit /CLOAD static
  solve from the parsed K reproduces the engine displacements to 0.000%;
  interpreting II with INTERNAL node ids instead scatters the couplings and
  gives wrong frequencies.)

Stock-engine caveats (see the k2rad README for the 1-line engine patches)
-------------------------------------------------------------------------
* The stock engine prints V with FORMAT(...,E10.2) — 2 significant digits,
  ~1% stiffness rounding, ~0.5-1% eigenfrequency error.  This script detects
  the low-precision format and warns.  A patched engine (E24.16) is exact.
* After ``--STIFFNESS MATRIX IS PRINTED--`` the stock np=1 engine can hang in
  an O(NZ²) domain-merge duplicate scan: kill it — the per-domain file is
  already complete.

Mass model
----------
Lumped (diagonal) M rebuilt from the .k mesh, matching the engine's own
lumping (verified against the engine's MS/IN nodal arrays on the W14 bogie —
identical to machine precision):

* translational DOFs: each element's mass (shell area×t×rho, solid
  volume×rho, beam length×A×rho) split evenly over its nodes, plus
  *ELEMENT_MASS / *ELEMENT_MASS_PART additions;
* rotational DOFs of shell nodes: the Radioss shell lumping
  IN = Σ_elems (m_elem/n_nodes)·(A_elem + t²)/12;
* rotational DOFs of solid/beam-only nodes: zero (solid nodes have no
  rotational stiffness so those DOFs never appear in K; beam rotary inertia
  is not modeled — shift-invert eigsh accepts the semi-definite M).

Units: frequencies come out in cycles per TIME-UNIT of the deck.  For a
kg-mm-ms deck (the LS-DYNA frequency-domain examples) that is kHz; the
printed table includes a ×1000 column for that common case.

Dependencies: numpy + scipy (same optional stack as k2rad's --auto-gapmin;
see docs/DEPENDENCIES.md).  The k2rad package itself is used to parse the .k.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# k2rad lives one directory up from tools/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402

try:                                             # pragma: no cover - env dependent
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    _HAVE_SCIPY = True
except ImportError:                              # pragma: no cover - env dependent
    np = None
    _HAVE_SCIPY = False

# DOF numbering inside a 6-DOF nodal block (matrix index = 6*(node-1)+dof).
DOF_NAMES = ("TX", "TY", "TZ", "RX", "RY", "RZ")
# Direction argument accepted by --static.
_DIR_TO_DOF = {"X": 1, "Y": 2, "Z": 3, "XX": 4, "YY": 5, "ZZ": 6,
               "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}

# The stock engine writes V as FORMAT(I10,I10,E10.2) -> mantissa "0.XX" (2
# significant digits). The patched engine writes E24.16.
_LOW_PRECISION_RE = re.compile(r"^-?0?\.\d{1,2}E[+-]\d+$", re.IGNORECASE)


@dataclass
class StiffnessMatrix:
    """Symmetric K from a /IMPL/PRINT/STIF export, compressed to its free DOFs.

    ``gids`` are the sorted original matrix indices (6*(user_node-1)+dof);
    row/column k of ``K`` corresponds to ``gids[k]`` = user node
    ``user_node[k]``, DOF ``dof[k]`` (1..6 = TX,TY,TZ,RX,RY,RZ).
    """
    n_declared: int          # header N (number of free DOFs, per the engine)
    gids: "np.ndarray"       # original sparse indices, sorted ascending
    K: "sp.csc_matrix"       # len(gids) x len(gids), symmetric
    user_node: "np.ndarray"  # user node id per row
    dof: "np.ndarray"        # 1..6 per row
    low_precision: bool      # True = stock E10.2 print (2 significant digits)


def read_stiffness(path: str) -> StiffnessMatrix:
    """Parse a ``local_stiffness_matrix_domain0`` file into a symmetric CSC K."""
    if not _HAVE_SCIPY:
        raise RuntimeError(
            "numpy + scipy are required to parse/solve the stiffness matrix "
            "(pip install scipy - see docs/DEPENDENCIES.md)")
    with open(path) as fh:
        header = fh.readline().split()
        if len(header) < 3:
            raise ValueError(
                f"{path}: expected header 'N N NZ', got {header!r}")
        n_declared, nz_declared = int(header[0]), int(header[2])
        # Low-precision (stock-engine E10.2) detection on the first data line.
        pos = fh.tell()
        first = fh.readline().split()
        low_precision = bool(first) and bool(_LOW_PRECISION_RE.match(first[-1]))
        fh.seek(pos)
        dat = np.loadtxt(fh, ndmin=2)
    if dat.shape[0] != nz_declared:
        print(f"  NOTE: header declares {nz_declared} entries, file has "
              f"{dat.shape[0]} - using the file contents.")
    ii = dat[:, 0].astype(np.int64)
    jj = dat[:, 1].astype(np.int64)
    v = dat[:, 2]
    # Compress the gappy 6*(user_node-1)+dof index space to 0..n-1.
    gids = np.unique(np.concatenate([ii, jj]))
    lut = {g: k for k, g in enumerate(gids)}
    r = np.fromiter((lut[g] for g in ii), np.int64, len(ii))
    c = np.fromiter((lut[g] for g in jj), np.int64, len(jj))
    # One triangle on file: mirror off-diagonal entries. coo->csc sums
    # duplicate (II,JJ) entries, per the MUMPS assembled-format convention.
    off = r != c
    n = len(gids)
    K = sp.coo_matrix(
        (np.concatenate([v, v[off]]),
         (np.concatenate([r, c[off]]), np.concatenate([c, r[off]]))),
        shape=(n, n)).tocsc()
    return StiffnessMatrix(
        n_declared=n_declared,
        gids=gids,
        K=K,
        user_node=((gids - 1) // 6 + 1).astype(np.int64),
        dof=((gids - 1) % 6 + 1).astype(np.int64),
        low_precision=low_precision,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Lumped nodal masses from the source .k
# ─────────────────────────────────────────────────────────────────────────────

def _tri_area(p1, p2, p3) -> float:
    ux, uy, uz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
    vx, vy, vz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def _tet_volume(p1, p2, p3, p4) -> float:
    a = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
    b = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
    c = (p4[0] - p1[0], p4[1] - p1[1], p4[2] - p1[2])
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return abs(det) / 6.0


# Hexa8 split into 6 tets (corner-based decomposition; exact for any hexa
# whose faces are planar, standard approximation otherwise).
_HEXA_TETS = ((0, 1, 3, 4), (1, 2, 3, 4), (2, 6, 3, 4),
              (1, 5, 2, 4), (5, 6, 2, 4), (5, 4, 6, 7))


def _material_rho(state: ConversionState) -> Dict[int, float]:
    rho: Dict[int, float] = {}
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_rigid, state.mat_null, state.mat_power_law):
        for mid, m in mats.items():
            rho[mid] = m.rho
    return rho


def nodal_masses_from_state(
        state: ConversionState) -> Tuple[Dict[int, float], Dict[int, float]]:
    """Lumped nodal masses and rotary inertias [deck units] from the parsed deck.

    Returns ``(mass, inertia)``: translational mass and rotational inertia per
    node.  Element mass is split evenly over the element's nodes (row-sum
    lumping for the linear elements used here); shell nodes also receive the
    Radioss rotary-inertia lumping IN = (m_elem/n_nodes)·(A_elem + t²)/12.
    Both reproduce the OpenRadioss starter's MS/IN nodal arrays to machine
    precision (verified on the W14 bogie). *ELEMENT_MASS /
    *ELEMENT_MASS_PART additions are then applied to the masses.
    """
    rho_by_mid = _material_rho(state)
    nodes = state.nodes
    mass: Dict[int, float] = {}
    inertia: Dict[int, float] = {}

    def add(nids: Sequence[int], m_elem: float) -> None:
        share = m_elem / len(nids)
        for n in nids:
            mass[n] = mass.get(n, 0.0) + share

    part_mass: Dict[int, float] = {}

    def add_part(pid: int, m_elem: float) -> None:
        part_mass[pid] = part_mass.get(pid, 0.0) + m_elem

    for e in state.shell_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        sec = state.sec_shells.get(part.secid)
        rho = rho_by_mid.get(part.mid, 0.0)
        if sec is None or rho == 0.0:
            continue
        try:
            p = [ (nodes[n].x, nodes[n].y, nodes[n].z) for n in e.nodes ]
        except KeyError:
            continue
        area = _tri_area(p[0], p[1], p[2])
        if len(p) == 4:
            area += _tri_area(p[0], p[2], p[3])
        m_elem = area * sec.t1 * rho
        add(e.nodes, m_elem)
        add_part(e.pid, m_elem)
        in_share = (m_elem / len(e.nodes)) * (area + sec.t1 ** 2) / 12.0
        for n in e.nodes:
            inertia[n] = inertia.get(n, 0.0) + in_share

    for e in state.solid_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        rho = rho_by_mid.get(part.mid, 0.0)
        if rho == 0.0:
            continue
        try:
            p = [ (nodes[n].x, nodes[n].y, nodes[n].z) for n in e.nodes ]
        except KeyError:
            continue
        if len(p) >= 8:                       # hexa8 (or degenerate penta/hexa)
            vol = sum(_tet_volume(p[a], p[b], p[c], p[d])
                      for a, b, c, d in _HEXA_TETS)
        else:                                 # tet4 / tet10 (corner volume)
            vol = _tet_volume(p[0], p[1], p[2], p[3])
        m_elem = vol * rho
        add(e.nodes, m_elem)
        add_part(e.pid, m_elem)

    for e in state.beam_elems:
        part = state.parts.get(e.pid)
        if part is None:
            continue
        sec = state.sec_beams.get(part.secid)
        rho = rho_by_mid.get(part.mid, 0.0)
        if sec is None or rho == 0.0 or sec.area == 0.0:
            continue
        try:
            p1 = nodes[e.n1]; p2 = nodes[e.n2]
        except KeyError:
            continue
        length = math.dist((p1.x, p1.y, p1.z), (p2.x, p2.y, p2.z))
        m_elem = length * sec.area * rho
        add((e.n1, e.n2), m_elem)
        add_part(e.pid, m_elem)

    # *ELEMENT_MASS point masses (per node).
    for nid, m in state.added_node_masses.items():
        mass[nid] = mass.get(nid, 0.0) + m

    # *ELEMENT_MASS_PART: ADDMASS spread evenly over the part's nodes;
    # FINMASS = target total -> spread (FINMASS - current part mass).
    if state.element_mass_parts:
        part_nodes: Dict[int, set] = {}
        for e in state.shell_elems:
            part_nodes.setdefault(e.pid, set()).update(e.nodes)
        for e in state.solid_elems:
            part_nodes.setdefault(e.pid, set()).update(e.nodes)
        for e in state.beam_elems:
            part_nodes.setdefault(e.pid, set()).update((e.n1, e.n2))
        for pid, (addmass, finmass) in state.element_mass_parts.items():
            nids = sorted(part_nodes.get(pid, ()))
            if not nids:
                continue
            extra = (finmass - part_mass.get(pid, 0.0)) if finmass > 0 else addmass
            if extra:
                share = extra / len(nids)
                for n in nids:
                    mass[n] = mass.get(n, 0.0) + share
    return mass, inertia


def parse_deck(k_path: str) -> ConversionState:
    state = ConversionState()
    for block in parse_k_file(k_path):
        dispatch(block, state)
    return state


def nodal_masses_from_k(k_path: str) -> Tuple[Dict[int, float], Dict[int, float]]:
    return nodal_masses_from_state(parse_deck(k_path))


def default_n_modes(state: ConversionState,
                    requested: Optional[int] = None) -> int:
    """Number of modes to extract: an explicit -n wins, then the deck's
    *CONTROL_IMPLICIT_EIGENVALUE neig, then 12."""
    if requested:
        return requested
    eig = state.ctrl_implicit_eig
    if eig is not None and eig.neig > 0:
        return eig.neig
    return 12


def build_mass_diagonal(stiff: StiffnessMatrix,
                        node_mass: Dict[int, float],
                        node_inertia: Dict[int, float]) -> "np.ndarray":
    """Diagonal of lumped M aligned with the K rows: translational DOFs carry
    the nodal mass, rotational DOFs the nodal rotary inertia (see module
    docstring)."""
    md = np.zeros(len(stiff.gids))
    tra = stiff.dof <= 3
    md[tra] = [node_mass.get(int(n), 0.0) for n in stiff.user_node[tra]]
    md[~tra] = [node_inertia.get(int(n), 0.0) for n in stiff.user_node[~tra]]
    return md


# ─────────────────────────────────────────────────────────────────────────────
# Solvers
# ─────────────────────────────────────────────────────────────────────────────

def solve_modes(stiff: StiffnessMatrix, md: "np.ndarray",
                n_modes: int) -> Tuple["np.ndarray", "np.ndarray"]:
    """Shift-invert eigsh: lowest n_modes of K·φ = λ·M·φ.

    Returns (freq, phi): natural frequencies in cycles per deck time-unit
    (columns of phi are M-mass-normalized eigenvectors, one per frequency).
    """
    M = sp.diags(md).tocsc()
    vals, vecs = spla.eigsh(stiff.K, k=n_modes, M=M, sigma=0, which="LM")
    order = np.argsort(vals)
    vals, vecs = vals[order], vecs[:, order]
    freq = np.sqrt(np.maximum(vals, 0.0)) / (2.0 * math.pi)
    return freq, vecs


def solve_static(stiff: StiffnessMatrix, load_node: int, load_dof: int,
                 force: float) -> "np.ndarray":
    """u = K⁻¹·f for a single point load — the exact-K validation solve.

    Run the same load as an engine /CLOAD static (/IMPL/LINEAR): the
    displacements must match the engine output to ~0% when the matrix comes
    from a patched (E24.16) engine, ~1% from a stock (E10.2) one.
    """
    sel = (stiff.user_node == load_node) & (stiff.dof == load_dof)
    if not sel.any():
        raise SystemExit(
            f"ERROR: node {load_node} DOF {DOF_NAMES[load_dof-1]} is not a free"
            " DOF of the exported matrix (constrained, rigid-slaved, or absent)")
    f = np.zeros(len(stiff.gids))
    f[sel] = force
    return spla.spsolve(stiff.K, f)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _print_matrix_info(stiff: StiffnessMatrix) -> None:
    print(f"  K: {len(stiff.gids)} free DOFs (header N={stiff.n_declared}), "
          f"{stiff.K.nnz} nonzeros, "
          f"{len(np.unique(stiff.user_node))} nodes")
    if stiff.low_precision:
        print("  WARNING: matrix printed by a STOCK engine (FORMAT E10.2, 2 "
              "significant digits) - expect ~1% stiffness rounding and "
              "~0.5-1% frequency error. A patched engine (imp_mumps.F FORMAT "
              "1003 E10.2 -> E24.16) is exact; see the k2rad README.")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="modal_solve",
        description="Solve normal modes (or a static validation load) from an "
                    "OpenRadioss /IMPL/PRINT/STIF stiffness export.")
    ap.add_argument("matrix", help="path to local_stiffness_matrix_domain0")
    ap.add_argument("k_file", nargs="?", default=None,
                    help="source LS-DYNA .k file (used to rebuild the lumped "
                         "mass matrix; required for the modal solve)")
    ap.add_argument("-n", "--n-modes", type=int, default=None, metavar="N",
                    help="number of modes to extract (default: the deck's "
                         "*CONTROL_IMPLICIT_EIGENVALUE neig, else 12)")
    ap.add_argument("-o", "--output", default=None, metavar="NPZ",
                    help="save frequencies + mode shapes to this .npz "
                         "(default: modes.npz next to the matrix file)")
    ap.add_argument("--static", nargs=3, metavar=("NODE", "DIR", "FORCE"),
                    default=None,
                    help="static validation instead of modes: apply FORCE on "
                         "user NODE along DIR (X|Y|Z|XX|YY|ZZ) and print the "
                         "displacements - compare against an engine /CLOAD "
                         "static run (exact-K check)")
    ap.add_argument("--sensors", nargs="+", type=int, default=None,
                    metavar="NODE", help="nodes to report in --static mode "
                                         "(default: the loaded node)")
    args = ap.parse_args(argv)

    if not _HAVE_SCIPY:
        print("ERROR: numpy + scipy are required (pip install scipy - see "
              "docs/DEPENDENCIES.md)", file=sys.stderr)
        return 1

    print(f"Reading stiffness matrix: {args.matrix}")
    stiff = read_stiffness(args.matrix)
    _print_matrix_info(stiff)

    # ── Static validation mode ────────────────────────────────────────────
    if args.static:
        node = int(args.static[0])
        try:
            dof = _DIR_TO_DOF[args.static[1].upper()]
        except KeyError:
            print(f"ERROR: unknown direction {args.static[1]!r} "
                  f"(use X|Y|Z|XX|YY|ZZ)", file=sys.stderr)
            return 1
        force = float(args.static[2])
        print(f"  static solve: F={force:g} on node {node} "
              f"{DOF_NAMES[dof-1]}")
        u = solve_static(stiff, node, dof, force)
        sensors = args.sensors or [node]
        print("  displacements (compare with the engine /CLOAD run):")
        print("      node          DX              DY              DZ")
        for nid in sensors:
            row = []
            for d in (1, 2, 3):
                s = (stiff.user_node == nid) & (stiff.dof == d)
                row.append(f"{u[s][0]: .8E}" if s.any() else "     (fixed)   ")
            print(f"  {nid:8d}  " + "  ".join(row))
        return 0

    # ── Modal solve ───────────────────────────────────────────────────────
    if not args.k_file:
        print("ERROR: the modal solve needs the source .k file for the mass "
              "matrix:  modal_solve.py <matrix> <model.k>", file=sys.stderr)
        return 1
    print(f"Building lumped mass matrix from: {args.k_file}")
    state = parse_deck(args.k_file)
    node_mass, node_inertia = nodal_masses_from_state(state)
    md = build_mass_diagonal(stiff, node_mass, node_inertia)
    n_modes = default_n_modes(state, args.n_modes)
    in_k = np.unique(stiff.user_node)
    total = sum(node_mass.values())
    print(f"  total deck mass {total:.6G} "
          f"(on the {len(in_k)} matrix nodes: {md[stiff.dof <= 3].sum() / 3.0:.6G} "
          "- constrained-node mass does not enter the eigenproblem)")
    massless = np.unique(stiff.user_node[(stiff.dof <= 3) & (md == 0.0)])
    if massless.size:
        print(f"  NOTE: {massless.size} node(s) in K carry zero mass "
              f"(e.g. {', '.join(map(str, massless[:5]))}) - check materials "
              "/ sections if unexpected.")

    print(f"Solving for {n_modes} modes (shift-invert eigsh) ...")
    freq, phi = solve_modes(stiff, md, n_modes)
    print("\n  mode |  f [1/time-unit]  |  f [Hz] if deck time is ms")
    for i, fq in enumerate(freq, 1):
        print(f"  {i:4d} | {fq:17.6f} | {1000.0 * fq:12.2f}")
    print("\n  (f is in cycles per deck TIME-UNIT: kg-mm-ms deck -> kHz, "
          "Mg-mm-s / kg-m-s deck -> Hz)")

    out = args.output or str(Path(args.matrix).parent / "modes.npz")
    np.savez(out, freq=freq, phi=phi,
             user_node=stiff.user_node, dof=stiff.dof, gids=stiff.gids)
    print(f"  mode shapes saved: {out}  (freq, phi[dof,mode], user_node, dof)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
