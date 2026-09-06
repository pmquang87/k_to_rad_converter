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
import datetime
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
# The two derivations this module must NOT re-implement: the writer's
# thickness-to-section-constants rule (the /PROP/BEAM the engine's stiffness
# matrix came from used it) and the converter's own RO <= 0 floor (the .rad it
# came from carries it). See _beam_section_area and _material_rho.
from k2rad.writer.beams import _constants_from_thicknesses   # noqa: E402
from k2rad.writer.materials import _ZERO_DENSITY_FLOOR       # noqa: E402

#: *SECTION_BEAM ELFORMs whose card 2 states THICKNESSES instead of section
#: constants (Vol I R17 p.41-11: cards 2a and 2e) — the ones
#: ``_constants_from_thicknesses`` is written for.
_THICKNESS_BEAM_ELFORMS = frozenset({0, 1, 4, 5, 11})

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


# Hexa8 split into 6 tets fanned around the 0-6 body diagonal (exact for any
# hexa whose faces are planar, standard approximation otherwise). NOTE: an
# earlier corner-based table ended with tet (5,4,6,7) — the four TOP-FACE
# corners, which are coplanar (zero volume) — so every hexa's volume/mass came
# out 5/6 of the true value (+9.5% bias on hexa-model eigenfrequencies).
_HEXA_TETS = ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6),
              (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6))


def _material_rho(state: ConversionState,
                  zero_density_floor: bool = True) -> Dict[int, float]:
    """``mid -> rho`` for every law this module can weigh.

    ``zero_density_floor`` mirrors the CONVERTER's own ``RO <= 0`` floor
    (``writer/materials._ZERO_DENSITY_FLOOR``). This is not a fabrication and
    not a modelling choice: the stiffness matrix this module pairs the mass
    with was exported by the engine from the CONVERTED ``.rad``, in which
    k2rad has already written ``rho = 1e-24`` for exactly these materials.
    Building M at ``rho = 0`` while K comes from a model at ``rho = 1e-24``
    pairs a mass matrix with a stiffness matrix from a DIFFERENT model — and
    the zero rows are what makes the eigensolve fail (see ``solve_modes``).
    The substitution is printed the way the converter prints it, and
    ``--no-zero-density-floor`` turns it off.

    ``nvh/example-06-02/6.2.PSD_Beam_Example_LSTC.k`` is the measured carrier:
    its ``*MAT_ELASTIC`` card 1 parses as ``mid 1 | RO 0.0 | E 68947.5729 |
    PR 0.33``, so the density really is zero in the source.
    """
    rho: Dict[int, float] = {}
    floored: List[int] = []
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_rigid, state.mat_null, state.mat_power_law):
        for mid, m in mats.items():
            r = m.rho
            if r <= 0.0 and zero_density_floor:
                r = _ZERO_DENSITY_FLOOR
                floored.append(mid)
            rho[mid] = r
    if floored:
        print(f"  NOTE: material(s) {sorted(floored)} state RO <= 0; the mass "
              f"matrix uses rho = {_ZERO_DENSITY_FLOOR:g}, the same floor "
              "k2rad wrote into the .rad the stiffness matrix was exported "
              "from (writer/materials._ZERO_DENSITY_FLOOR). "
              "--no-zero-density-floor keeps the stated zero.")
    return rho


def _beam_section_area(sec) -> float:
    """Cross-section AREA of a *SECTION_BEAM that states only thicknesses.

    ELFORM 0/1/4/5/11 carry no A/Iyy/Izz/Ixx at all — their card 2 is
    ``TS1 TS2 TT1 TT2 ...`` — so ``sec.area`` is 0 and this module weighed the
    beam at zero. The WRITER already derives the constants for exactly these
    formulations (``k2rad.writer.beams._constants_from_thicknesses``, CST 0/2
    rectangular TS1 x TT1, CST 1 tubular with TS1 the OUTER and TT1 the INNER
    diameter), so the derivation is IMPORTED rather than repeated here: the
    /PROP/BEAM the engine built its stiffness matrix from used those very
    numbers, and a second copy of the rule is how the two drift apart.

    MEASURED on ``nvh/example-06-02/6.2.PSD_Beam_Example_LSTC.k``: elform 1,
    area 0.0, ts1 6.35, tt1 50.8, cst 0 ->
    ``_constants_from_thicknesses(0, 6.35, 50.8) = (322.58, 69371.904,
    1083.936, 70455.840)``, and I = 50.8*6.35**3/12 = 1083.936 gives
    k = 3EI/L**3 = 109.4543 and f = 110.5541 Hz against the deck's own
    ``.eigout`` f1 = 110.4521 Hz (-0.09 %).
    """
    if getattr(sec, "elform", -1) not in _THICKNESS_BEAM_ELFORMS:
        return 0.0
    got = _constants_from_thicknesses(sec.cst, sec.ts1, sec.tt1)
    return float(got[0]) if got else 0.0


def nodal_masses_from_state(
        state: ConversionState, zero_density_floor: bool = True
) -> Tuple[Dict[int, float], Dict[int, float]]:
    """Lumped nodal masses and rotary inertias [deck units] from the parsed deck.

    Returns ``(mass, inertia)``: translational mass and rotational inertia per
    node.  Element mass is split evenly over the element's nodes (row-sum
    lumping for the linear elements used here); shell nodes also receive the
    Radioss rotary-inertia lumping IN = (m_elem/n_nodes)·(A_elem + t²)/12.
    Both reproduce the OpenRadioss starter's MS/IN nodal arrays to machine
    precision (verified on the W14 bogie). *ELEMENT_MASS /
    *ELEMENT_MASS_PART additions are then applied to the masses.
    """
    rho_by_mid = _material_rho(state, zero_density_floor)
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
        if sec is None or rho == 0.0:
            continue
        area = sec.area or _beam_section_area(sec)
        if area <= 0.0:
            continue
        try:
            p1 = nodes[e.n1]; p2 = nodes[e.n2]
        except KeyError:
            continue
        length = math.dist((p1.x, p1.y, p1.z), (p2.x, p2.y, p2.z))
        m_elem = length * area * rho
        add((e.n1, e.n2), m_elem)   # rho*A*L/2 per end node
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


# ─────────────────────────────────────────────────────────────────────────────
# Drilling-rotation stiffness (LS-DYNA implicit parity)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DRILL_FACTOR = 1.0e-3


def _material_E_nu(state: ConversionState) -> Dict[int, Tuple[float, float]]:
    out: Dict[int, Tuple[float, float]] = {}
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_rigid, state.mat_null, state.mat_power_law):
        for mid, m in mats.items():
            out[mid] = (m.E, m.nu)
    return out


def drilling_stiffness(state: ConversionState, stiff: StiffnessMatrix,
                       factor: float) -> "sp.csc_matrix":
    """Element-level drilling-rotation stiffness, added to K for the EIGENSOLVE.

    The rotation of a shell node about the element normal (the "drilling"
    DOF) has (near-)zero physical stiffness in the exported OpenRadioss K, but
    the lumped rotary inertia IN is finite — so the raw eigenproblem grows
    spurious low-frequency rotation-dominated modes (W14 bogie: 9 junk modes
    at 63–81 Hz hiding the real 129–290 Hz structure).  LS-DYNA implicit
    suppresses exactly this with its "Drilling Rotation Constraint Parameter"
    (d3hsp, default 1.0, plus AUTOSPC); this is the same cure on our side::

        K_drill = Σ_shells Σ_nodes  factor · G·t·A/n_nodes · (n̂ n̂ᵀ)

    added to each shell node's rotational 3×3 block (n̂ = element normal,
    G = E/2(1+ν), A = element area, t = shell thickness).  Validated on the
    W14 bogie against LS-DYNA R14 eigout/d3eigv: with factor 1e-3 modes 1–8
    match to ≤0.5 % with MAC = 1.000 (and LS-DYNA's mode 9 appears at our
    mode 11 with 0.003 % / MAC 0.997); the retained modes are insensitive to
    the factor over 1e-4…3e-3, so the default needs no tuning.  ``factor=0``
    disables the augmentation (the pre-parity behaviour).
    """
    if factor <= 0.0 or not state.shell_elems:
        n = len(stiff.gids)
        return sp.csc_matrix((n, n))
    nodes = state.nodes
    em = _material_E_nu(state)
    pos = {(int(n), int(d)): k
           for k, (n, d) in enumerate(zip(stiff.user_node, stiff.dof))}
    rows: List[int] = []
    cols: List[int] = []
    vals: List[float] = []
    for e in state.shell_elems:
        part = state.parts.get(e.pid)
        sec = state.sec_shells.get(part.secid) if part else None
        E, nu = em.get(part.mid, (0.0, 0.0)) if part else (0.0, 0.0)
        if sec is None or E <= 0.0 or sec.t1 <= 0.0:
            continue
        try:
            p = [(nodes[n].x, nodes[n].y, nodes[n].z) for n in e.nodes]
        except KeyError:
            continue
        if len(p) == 4:                       # quad: diagonal cross product
            u = _vsub(p[2], p[0])
            v = _vsub(p[3], p[1])
        else:                                 # tri
            u = _vsub(p[1], p[0])
            v = _vsub(p[2], p[0])
        nx, ny, nz = (u[1] * v[2] - u[2] * v[1],
                      u[2] * v[0] - u[0] * v[2],
                      u[0] * v[1] - u[1] * v[0])
        nrm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nrm < 1e-30:
            continue
        area = 0.5 * nrm
        n_hat = (nx / nrm, ny / nrm, nz / nrm)
        G = 0.5 * E / (1.0 + nu)
        kd = factor * G * sec.t1 * area / len(e.nodes)
        for n in e.nodes:
            rr = [pos.get((n, d)) for d in (4, 5, 6)]
            for i in range(3):
                if rr[i] is None:
                    continue
                for j in range(3):
                    if rr[j] is None:
                        continue
                    v = kd * n_hat[i] * n_hat[j]
                    if v != 0.0:
                        rows.append(rr[i])
                        cols.append(rr[j])
                        vals.append(v)
    n = len(stiff.gids)
    return sp.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsc()


def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


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
    # ARPACK's shift-invert operator here is OP = K^-1 M, whose RANK is the
    # number of non-zero mass DOFs. Asking for more modes than that (scipy's
    # default ncv is ~min(n, max(2k+1, 20))) makes the Arnoldi factorization
    # break down after a few steps and eigsh returns -9999 — a FAILURE that
    # reads like a singular stiffness matrix and is not one. MEASURED on
    # nvh/example-06-02/6.2.PSD_Beam_Example_LSTC.k, whose M had exactly THREE
    # non-zero diagonal entries (node 2's translations) before the beam mass
    # arm was fixed: rank 3 against ncv 20.
    rank = int((md > 0.0).sum())
    if rank and n_modes >= rank:
        print(f"  NOTE: only {rank} DOF(s) of the mass matrix are non-zero, so "
              f"at most {rank - 1} mode(s) can be extracted by shift-invert "
              f"(OP = K^-1 M has rank {rank}); asking for {n_modes} makes "
              "ARPACK break down and return -9999. Solving for "
              f"{max(1, rank - 1)}.")
        n_modes = max(1, rank - 1)
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
              "significant digits). On a compact model that is ~1% stiffness "
              "rounding and ~0.5-1% frequency error, but the error is NOT "
              "bounded at 1%: a soft global mode of a slender structure is a "
              "near-cancellation of much larger local terms, and 2 digits "
              "destroy it. MEASURED on the 50-element cantilever of "
              "nvh/example-06-02 (6.2.PSD_Beam_Example_LSTC.k, LS-DYNA eigout "
              "f1 = 110.4521 Hz): the exact matrix gives 110.5541 Hz and a "
              "tip stiffness of 109.454 = 3EI/L^3 to six figures, while the "
              "SAME matrix rounded to E10.2 gives a NEGATIVE tip stiffness "
              "(-2.6e5) and f1 = 0.0000 Hz. Treat any frequency from a "
              "low-precision matrix as unvalidated until a patched engine "
              "(imp_mumps.F FORMAT 1003 E10.2 -> E24.16, which the k2rad "
              "Docker image ships) reproduces it; see the k2rad README.")


class _Tee:
    """Mirror every write to several streams (terminal + a log file).

    Used to save the console output of a modal solve, which the OpenRadioss
    engine's own ``*_0001.out`` never captures (the eigensolve runs offline in
    this separate Python process).
    """

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)
        return len(data)

    def flush(self):
        for s in self._streams:
            s.flush()


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
    ap.add_argument("--drill", type=float, default=DEFAULT_DRILL_FACTOR,
                    metavar="FACTOR",
                    help="drilling-rotation stiffness factor added to shell "
                         "nodes for the eigensolve (suppresses spurious "
                         "rotation-dominated modes, mirroring LS-DYNA "
                         "implicit's drilling constraint; validated default "
                         f"{DEFAULT_DRILL_FACTOR:g}, retained modes "
                         "insensitive over 1e-4..3e-3; 0 disables)")
    ap.add_argument("--static", nargs=3, metavar=("NODE", "DIR", "FORCE"),
                    default=None,
                    help="static validation instead of modes: apply FORCE on "
                         "user NODE along DIR (X|Y|Z|XX|YY|ZZ) and print the "
                         "displacements - compare against an engine /CLOAD "
                         "static run (exact-K check)")
    ap.add_argument("--sensors", nargs="+", type=int, default=None,
                    metavar="NODE", help="nodes to report in --static mode "
                                         "(default: the loaded node)")
    ap.add_argument("--log", default=None, metavar="PATH",
                    help="mirror everything printed to the console into this "
                         "log file as well (the engine *_0001.out does NOT "
                         "capture the offline modal output); default: "
                         "modal_solve.log next to the matrix file")
    ap.add_argument("--no-log", action="store_true",
                    help="do not write the console log file")
    ap.add_argument("--zero-density-floor",
                    action=argparse.BooleanOptionalAction, default=True,
                    help="build the mass matrix with k2rad's own RO <= 0 floor "
                         "(%(default)s) so M and the exported K describe the "
                         "SAME model - the .rad the engine exported from "
                         "already carries rho = 1e-24 on those materials. "
                         "--no-zero-density-floor keeps the stated zero, which "
                         "leaves those elements massless")
    args = ap.parse_args(argv)

    if not _HAVE_SCIPY:
        print("ERROR: numpy + scipy are required (pip install scipy - see "
              "docs/DEPENDENCIES.md)", file=sys.stderr)
        return 1

    # Mirror the whole console session to a log file (the engine *_0001.out
    # only holds the engine's own run, never this offline eigensolve).
    old_out, old_err = sys.stdout, sys.stderr
    log_fh = None
    log_path = None
    if not args.no_log:
        log_path = args.log or str(Path(args.matrix).parent / "modal_solve.log")
        try:
            log_fh = open(log_path, "w", encoding="utf-8", newline="")
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cmd_args = sys.argv[1:] if argv is None else argv
            log_fh.write(f"# modal_solve.py console log  {ts}\n"
                         f"# args: {' '.join(cmd_args)}\n\n")
        except OSError as exc:
            print(f"WARNING: cannot write log file {log_path!r}: {exc}",
                  file=sys.stderr)
            log_fh = None
        if log_fh is not None:
            sys.stdout = _Tee(old_out, log_fh)
            sys.stderr = _Tee(old_err, log_fh)

    try:
        return _run(args)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        if log_fh is not None:
            log_fh.close()
            print(f"[console log saved: {log_path}]", file=sys.stderr)


def _run(args) -> int:
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
    node_mass, node_inertia = nodal_masses_from_state(
        state, zero_density_floor=args.zero_density_floor)
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

    if args.drill > 0.0:
        kdrill = drilling_stiffness(state, stiff, args.drill)
        if kdrill.nnz:
            print(f"  drilling-rotation stiffness added for the eigensolve "
                  f"(factor {args.drill:g}, {kdrill.nnz} entries) - "
                  "suppresses spurious shell drilling modes (LS-DYNA "
                  "implicit parity; --drill 0 disables)")
            stiff = StiffnessMatrix(
                n_declared=stiff.n_declared, gids=stiff.gids,
                K=(stiff.K + kdrill).tocsc(), user_node=stiff.user_node,
                dof=stiff.dof, low_precision=stiff.low_precision)

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
