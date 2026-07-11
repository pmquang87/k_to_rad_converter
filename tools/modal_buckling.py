#!/usr/bin/env python3
"""
modal_buckling.py – linear (eigenvalue) buckling on top of the modal K export.

LS-DYNA's *CONTROL_IMPLICIT_BUCKLE has no OpenRadioss equivalent (the engine
cannot solve the eigenproblem), so k2rad finishes it OFFLINE, reusing the same
/IMPL/PRINT/STIF stiffness export and static-solve chain that tools/modal_solve.py
already validates.

Theory
------
Linear buckling seeks the load factor λ at which the tangent stiffness of a
pre-loaded structure becomes singular::

    (K + λ·K_g) φ = 0        ⟺        K φ = λ·(−K_g) φ

where K is the elastic stiffness (the exported matrix) and K_g is the geometric
(stress) stiffness produced by a REFERENCE load case.  λ is the multiplier on
the reference load at which buckling occurs; the critical load is
P_cr = λ·P_ref and φ is the buckling mode shape.

Because K_g depends on the element internal forces — which the exported global K
does not carry — the geometric stiffness is assembled from the mesh plus a
static pre-solve:

  1. apply the reference load and solve  K·u = F  (via modal_solve.solve_static);
  2. recover each element's internal forces (beam axial force  N = (E·A/L)·
     (u₂−u₁)·ê; shell membrane stress resultants {Nx, Ny, Nxy} = t·σ from the
     in-plane strains, plane stress);
  3. assemble K_g element-by-element (see scope below);
  4. solve the generalized eigenproblem  K φ = λ·(−K_g) φ  for the lowest λ
     (scipy eigsh with K — symmetric positive-definite — as the metric).

Supported vs. warned scope  (READ THIS)
---------------------------------------
* **BEAM elements** (*ELEMENT_BEAM with *SECTION_BEAM area + second moments and
  an elastic material): FULLY SUPPORTED.  The consistent Euler–Bernoulli
  geometric stiffness (Przemieniecki / Cook) is assembled in both local bending
  planes.  This is validated in tests/test_modal_analysis.py against the
  analytic Euler pin-pinned column  P_cr = π²·E·I/L²  (agreement < 1 %).  Rods
  and truss/bar members that carry only axial force are a degenerate case of the
  same block (the transverse "string" terms) and are covered when modelled as
  beams.

* **SHELL elements** (*ELEMENT_SHELL with *SECTION_SHELL thickness and an
  elastic material): SUPPORTED at the classical "consistent membrane" level —
  the flat-facet membrane geometric stiffness (see
  :func:`assemble_geometric_stiffness`).  Membrane stress resultants
  {Nx, Ny, Nxy} are recovered from the pre-solve (CST strains for triangles,
  bilinear quadrilateral evaluated at the centroid for quads; plane stress),
  and the textbook plate-buckling geometric stiffness
  K_g = ∫ (∇N_w)ᵀ [Nx Nxy; Nxy Ny] (∇N_w) dA is integrated over the
  OUT-OF-PLANE (w = element normal) DOFs.  Rotational-DOF contributions are
  neglected, which is the standard level of approximation of this classical
  formulation.  Validated in tests/test_modal_analysis.py against the analytic
  simply supported square plate under uniaxial compression,
  σ_cr = 4·π²·E/(12(1−ν²))·(t/b)²: measured +2.2 % on an 8×8 mesh (asserted
  < 3 %), converging quadratically (+1.0 % at 12×12, +0.5 % at 16×16).

* **SOLID elements: NOT SUPPORTED — WARNED, NOT WRONG.**  A correct continuum
  geometric stiffness needs the full 3-D element stress tensor recovered from
  the pre-solve and the corresponding K_g integrals; a naive version emits
  *wrong* buckling factors, which is worse than none.  Solid elements are
  skipped and a prominent warning is printed; if the model is solid dominated
  the tool refuses to report a buckling factor.

Usage
-----
    python tools/modal_buckling.py <local_stiffness_matrix_domain0> <model.k> \\
           --load NODE DIR FORCE  [-n N_MODES] [-o buckling.npz]

``--load`` is the reference load (e.g. a unit axial compression); the reported
λ multiplies exactly that load.  DIR is X|Y|Z|XX|YY|ZZ.

Dependencies: numpy + scipy (same optional stack as modal_solve.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from k2rad.state import ConversionState                     # noqa: E402
from modal_common import Mesh, build_mesh, parse_deck        # noqa: E402
import modal_solve                                          # noqa: E402
from modal_solve import StiffnessMatrix, _DIR_TO_DOF, DOF_NAMES  # noqa: E402

try:                                             # pragma: no cover - env dependent
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    _HAVE_SCIPY = True
except ImportError:                              # pragma: no cover - env dependent
    np = None
    _HAVE_SCIPY = False


# ─────────────────────────────────────────────────────────────────────────────
# Beam section / material properties
# ─────────────────────────────────────────────────────────────────────────────

def _material_E(state: ConversionState) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for mats in (state.mat_elastic, state.mat_plas_tab, state.mat_plas_kin,
                 state.mat_rigid, state.mat_null, state.mat_power_law):
        for mid, m in mats.items():
            out[mid] = m.E
    return out


def beam_properties(state: ConversionState) -> Dict[int, Tuple[float, float, float, float]]:
    """part id → (E, A, Iyy, Izz) for beam parts with an elastic material.

    Missing second moments fall back to ixx or 0 (a rod: no bending stiffness).
    """
    E_by_mid = _material_E(state)
    props: Dict[int, Tuple[float, float, float, float]] = {}
    for pid, part in state.parts.items():
        sec = state.sec_beams.get(part.secid)
        E = E_by_mid.get(part.mid, 0.0)
        if sec is None or E <= 0.0 or sec.area <= 0.0:
            continue
        props[int(pid)] = (E, sec.area, sec.iyy, sec.izz)
    return props


# ─────────────────────────────────────────────────────────────────────────────
# Beam geometry + consistent geometric stiffness
# ─────────────────────────────────────────────────────────────────────────────

def _beam_frame(p1, p2, p3) -> Optional[Tuple["np.ndarray", float]]:
    """Local frame R (rows = ex,ey,ez in global) and length L for a beam.

    ``ex`` runs n1→n2; ``ey`` lies in the plane of the orientation point p3
    (falls back to an arbitrary perpendicular when p3 is unusable).
    """
    ex = np.asarray(p2, float) - np.asarray(p1, float)
    L = float(np.linalg.norm(ex))
    if L < 1e-30:
        return None
    ex = ex / L
    ref = None
    if p3 is not None:
        v = np.asarray(p3, float) - np.asarray(p1, float)
        v = v - np.dot(v, ex) * ex
        if np.linalg.norm(v) > 1e-12:
            ref = v
    if ref is None:                                   # arbitrary perpendicular
        trial = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(trial, ex)) > 0.9:
            trial = np.array([0.0, 1.0, 0.0])
        ref = trial - np.dot(trial, ex) * ex
    ey = ref / np.linalg.norm(ref)
    ez = np.cross(ex, ey)
    return np.stack([ex, ey, ez], axis=0), L


# base consistent geometric-stiffness block (times N) for local DOFs
# [transverse, rotation, transverse, rotation] with slope = +rotation.
def _kg_block(N: float, L: float) -> "np.ndarray":
    return (N / (30.0 * L)) * np.array([
        [36.0, 3.0 * L, -36.0, 3.0 * L],
        [3.0 * L, 4.0 * L * L, -3.0 * L, -L * L],
        [-36.0, -3.0 * L, 36.0, -3.0 * L],
        [3.0 * L, -L * L, -3.0 * L, 4.0 * L * L]])


def beam_geometric_stiffness_local(N: float, L: float) -> "np.ndarray":
    """12×12 local consistent geometric stiffness for axial force N (tension +).

    Local DOF order [u1,v1,w1,θx1,θy1,θz1, u2,v2,w2,θx2,θy2,θz2].  The x-y
    bending plane (v,θz) uses the base block; the x-z plane (w,θy) uses it with
    the θy = −w' sign convention (S·B·S, S = diag(1,−1,1,−1)).
    """
    kg = np.zeros((12, 12))
    B = _kg_block(N, L)
    xy = [1, 5, 7, 11]                                 # v1,θz1,v2,θz2
    for a in range(4):
        for b in range(4):
            kg[xy[a], xy[b]] += B[a, b]
    S = np.diag([1.0, -1.0, 1.0, -1.0])
    Bxz = S @ B @ S
    xz = [2, 4, 8, 10]                                 # w1,θy1,w2,θy2
    for a in range(4):
        for b in range(4):
            kg[xz[a], xz[b]] += Bxz[a, b]
    return kg


# ─────────────────────────────────────────────────────────────────────────────
# Shell membrane geometric stiffness (flat facet, consistent membrane level)
# ─────────────────────────────────────────────────────────────────────────────

def shell_properties(state: ConversionState) -> Dict[int, Tuple[float, float, float]]:
    """part id → (E, ν, t) for shell parts with an elastic material + thickness.

    Same part/material lookup as modal_solve's mass rebuild: thickness t from
    the part's *SECTION_SHELL, plane-stress elastic constants from the part's
    material.
    """
    em = modal_solve._material_E_nu(state)
    props: Dict[int, Tuple[float, float, float]] = {}
    for pid, part in state.parts.items():
        sec = state.sec_shells.get(part.secid)
        E, nu = em.get(part.mid, (0.0, 0.0))
        if sec is None or E <= 0.0 or sec.t1 <= 0.0:
            continue
        props[int(pid)] = (E, nu, sec.t1)
    return props


def _plane_stress_D(E: float, nu: float) -> "np.ndarray":
    """Plane-stress constitutive matrix (σ = D·[εx, εy, γxy])."""
    c = E / (1.0 - nu * nu)
    return np.array([[c, c * nu, 0.0],
                     [c * nu, c, 0.0],
                     [0.0, 0.0, 0.5 * E / (1.0 + nu)]])


def _shell_frame(pts: "np.ndarray"):
    """Flat-facet local frame for a 3/4-node shell.

    Returns (n̂, ê1, ê2, xy): the unit normal (from the diagonal cross product
    for quads, the edge cross product for tris), two in-plane axes, and the
    (n_nodes, 2) local in-plane coordinates of the nodes projected onto the
    facet plane through the centroid.  None for a degenerate element.
    """
    if len(pts) == 4:
        v1, v2 = pts[2] - pts[0], pts[3] - pts[1]
    else:
        v1, v2 = pts[1] - pts[0], pts[2] - pts[0]
    nvec = np.cross(v1, v2)
    nrm = float(np.linalg.norm(nvec))
    if nrm < 1e-30:
        return None
    n_hat = nvec / nrm
    t1 = pts[1] - pts[0]
    t1 = t1 - np.dot(t1, n_hat) * n_hat
    tl = float(np.linalg.norm(t1))
    if tl < 1e-30:
        return None
    e1 = t1 / tl
    e2 = np.cross(n_hat, e1)
    rel = pts - pts.mean(axis=0)
    xy = np.stack([rel @ e1, rel @ e2], axis=1)
    return n_hat, e1, e2, xy


def _tri_grads(xy: "np.ndarray"):
    """CST shape-function gradients.  Returns (G, area): G[0]=∂N/∂x, G[1]=∂N/∂y."""
    (x1, y1), (x2, y2), (x3, y3) = xy
    two_a = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    if abs(two_a) < 1e-30:
        return None, 0.0
    G = np.array([[y2 - y3, y3 - y1, y1 - y2],
                  [x3 - x2, x1 - x3, x2 - x1]]) / two_a
    return G, 0.5 * two_a


def _quad_grads(xy: "np.ndarray", xi: float, eta: float):
    """Bilinear-quad shape-function gradients at (ξ, η).  Returns (G, det J)."""
    dN = 0.25 * np.array([[-(1.0 - eta), -(1.0 - xi)],
                          [(1.0 - eta), -(1.0 + xi)],
                          [(1.0 + eta), (1.0 + xi)],
                          [-(1.0 + eta), (1.0 - xi)]])
    J = dN.T @ xy
    det = J[0, 0] * J[1, 1] - J[0, 1] * J[1, 0]
    if det <= 1e-30:
        return None, 0.0
    return np.linalg.solve(J, dN.T), det


_GAUSS_1D = (-1.0 / 3.0 ** 0.5, 1.0 / 3.0 ** 0.5)     # 2-point rule, weights 1


def shell_membrane_kg_w(xy: "np.ndarray", uv: "np.ndarray", E: float,
                        nu: float, t: float):
    """(kg_w, N) for one flat shell facet in its local frame.

    ``xy`` are the local in-plane node coordinates, ``uv`` the local in-plane
    nodal displacements from the static pre-solve.  The membrane stress
    resultants N = {Nx, Ny, Nxy} = t·σ (plane stress) are recovered from CST
    strains for triangles and from the bilinear quadrilateral evaluated at the
    CENTROID for quads (one constant N field per element — consistent with the
    flat-facet, constant-resultant formulation used here).

    kg_w is the consistent geometric stiffness of the facet under that
    membrane force field over the OUT-OF-PLANE (w) nodal DOFs::

        kg_w = ∫ (∇N_w)ᵀ [Nx Nxy; Nxy Ny] (∇N_w) dA

    with the same CST/bilinear shape-function gradients (triangles: closed
    form; quads: 2×2 Gauss).  Only the transverse-displacement DOFs receive
    geometric stiffness — rotational-DOF contributions are neglected, the
    standard "consistent membrane" level of approximation of the classical
    plate-buckling formulation.  Returns (None, None) for a degenerate facet.
    """
    nn = len(xy)
    if nn == 3:
        G, area = _tri_grads(xy)
        if G is None:
            return None, None
        strain = np.array([G[0] @ uv[:, 0], G[1] @ uv[:, 1],
                           G[1] @ uv[:, 0] + G[0] @ uv[:, 1]])
        Nf = t * (_plane_stress_D(E, nu) @ strain)
        Nmat = np.array([[Nf[0], Nf[2]], [Nf[2], Nf[1]]])
        return area * (G.T @ Nmat @ G), Nf
    G0, det0 = _quad_grads(xy, 0.0, 0.0)
    if G0 is None:
        return None, None
    strain = np.array([G0[0] @ uv[:, 0], G0[1] @ uv[:, 1],
                       G0[1] @ uv[:, 0] + G0[0] @ uv[:, 1]])
    Nf = t * (_plane_stress_D(E, nu) @ strain)
    Nmat = np.array([[Nf[0], Nf[2]], [Nf[2], Nf[1]]])
    kg = np.zeros((4, 4))
    for xi in _GAUSS_1D:
        for eta in _GAUSS_1D:
            G, det = _quad_grads(xy, xi, eta)
            if G is None:
                return None, None
            kg += det * (G.T @ Nmat @ G)
    return kg, Nf


def _row_lookup(stiff: StiffnessMatrix) -> Dict[Tuple[int, int], int]:
    return {(int(n), int(d)): k
            for k, (n, d) in enumerate(zip(stiff.user_node, stiff.dof))}


def _node_translation(u: "np.ndarray", pos: Dict[Tuple[int, int], int],
                      node: int) -> "np.ndarray":
    return np.array([u[pos[(node, d)]] if (node, d) in pos else 0.0
                     for d in (1, 2, 3)])


def assemble_geometric_stiffness(
        state: ConversionState, mesh: Mesh, stiff: StiffnessMatrix,
        u: "np.ndarray") -> Tuple["sp.csc_matrix", Dict[str, int], List[float]]:
    """Assemble K_g (in the exported DOF space) from the beam + shell elements.

    Beams get the consistent Euler–Bernoulli geometric stiffness; shells get
    the flat-facet consistent-membrane geometric stiffness over the
    out-of-plane DOFs (see :func:`shell_membrane_kg_w`); solids are skipped
    (unsupported — a wrong K_g is worse than a warning).

    Returns (K_g, counts, axial_forces).  ``counts`` keys: ``beam`` = beams
    that contributed, ``shell`` = shell elements present, ``shell_kg`` = shells
    that contributed, ``shell_skipped`` = shells without usable
    section/material/geometry, ``solid`` = solids present (all skipped).
    ``axial_forces`` are the recovered per-beam N (tension +).
    """
    props = beam_properties(state)
    pos = _row_lookup(stiff)
    nodes = state.nodes
    n = len(stiff.gids)
    rows: List[int] = []
    cols: List[int] = []
    vals: List[float] = []
    axial: List[float] = []
    n_beams = 0

    # local DOF k -> (node_id, nodal dof 1..6)
    for e in state.beam_elems:
        part = state.parts.get(e.pid)
        if part is None or int(e.pid) not in props:
            continue
        E, A, iyy, izz = props[int(e.pid)]
        try:
            p1 = (nodes[e.n1].x, nodes[e.n1].y, nodes[e.n1].z)
            p2 = (nodes[e.n2].x, nodes[e.n2].y, nodes[e.n2].z)
        except KeyError:
            continue
        p3 = None
        if getattr(e, "n3", 0) and e.n3 in nodes:
            p3 = (nodes[e.n3].x, nodes[e.n3].y, nodes[e.n3].z)
        frame = _beam_frame(p1, p2, p3)
        if frame is None:
            continue
        R, L = frame
        ex = R[0]
        # axial force from the pre-solve displacements
        du = _node_translation(u, pos, int(e.n2)) - _node_translation(
            u, pos, int(e.n1))
        N = (E * A / L) * float(np.dot(du, ex))
        axial.append(N)
        n_beams += 1
        if abs(N) < 1e-300:
            continue
        kg_local = beam_geometric_stiffness_local(N, L)
        # 12x12 transform T = blkdiag(R,R,R,R): u_local = T u_global
        T = np.zeros((12, 12))
        for blk in range(4):
            T[3 * blk:3 * blk + 3, 3 * blk:3 * blk + 3] = R
        kg_glob = T.T @ kg_local @ T
        dofmap = [(int(e.n1), 1), (int(e.n1), 2), (int(e.n1), 3),
                  (int(e.n1), 4), (int(e.n1), 5), (int(e.n1), 6),
                  (int(e.n2), 1), (int(e.n2), 2), (int(e.n2), 3),
                  (int(e.n2), 4), (int(e.n2), 5), (int(e.n2), 6)]
        rowk = [pos.get(key) for key in dofmap]
        for a in range(12):
            ra = rowk[a]
            if ra is None:
                continue
            for b in range(12):
                rb = rowk[b]
                if rb is None:
                    continue
                v = kg_glob[a, b]
                if v != 0.0:
                    rows.append(ra)
                    cols.append(rb)
                    vals.append(v)
    # ── shells: flat-facet consistent-membrane geometric stiffness ─────────
    sprops = shell_properties(state)
    n_shell_kg = 0
    n_shell_skip = 0
    for e in state.shell_elems:
        prop = sprops.get(int(e.pid))
        nids = list(dict.fromkeys(int(nn) for nn in e.nodes))  # collapse dupes
        if prop is None or len(nids) < 3:
            n_shell_skip += 1
            continue
        E, nu, t = prop
        try:
            pts = np.array([[nodes[nn].x, nodes[nn].y, nodes[nn].z]
                            for nn in nids])
        except KeyError:
            n_shell_skip += 1
            continue
        frame = _shell_frame(pts)
        if frame is None:
            n_shell_skip += 1
            continue
        n_hat, e1, e2, xy = frame
        ue = np.array([_node_translation(u, pos, nn) for nn in nids])
        uv = np.stack([ue @ e1, ue @ e2], axis=1)
        kg_w, Nf = shell_membrane_kg_w(xy, uv, E, nu, t)
        if kg_w is None:
            n_shell_skip += 1
            continue
        n_shell_kg += 1
        if float(np.abs(Nf).max()) < 1e-300:
            continue
        # w = n̂·u at each node: scatter kg_w[a,b]·(n̂ n̂ᵀ) into the global
        # translational 3×3 blocks (rotational DOFs receive nothing — see
        # shell_membrane_kg_w).
        for a, na in enumerate(nids):
            ra3 = [pos.get((na, d)) for d in (1, 2, 3)]
            for b, nb in enumerate(nids):
                coef = kg_w[a, b]
                if coef == 0.0:
                    continue
                rb3 = [pos.get((nb, d)) for d in (1, 2, 3)]
                for i in range(3):
                    if ra3[i] is None:
                        continue
                    for j in range(3):
                        if rb3[j] is None:
                            continue
                        v = coef * n_hat[i] * n_hat[j]
                        if v != 0.0:
                            rows.append(ra3[i])
                            cols.append(rb3[j])
                            vals.append(v)

    Kg = sp.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsc()
    counts = {"beam": n_beams,
              "shell": len(mesh.shell_conn),
              "shell_kg": n_shell_kg,
              "shell_skipped": n_shell_skip,
              "solid": len(mesh.solid_conn)}
    return Kg, counts, axial


# ─────────────────────────────────────────────────────────────────────────────
# Buckling eigenproblem
# ─────────────────────────────────────────────────────────────────────────────

def solve_buckling(K: "sp.csc_matrix", Kg: "sp.csc_matrix",
                   n_modes: int) -> Tuple["np.ndarray", "np.ndarray"]:
    """Lowest positive buckling factors λ of  K φ = λ·(−K_g) φ.

    K (elastic) is symmetric positive-definite, so it is used as the metric:
    with B = −K_g the pencil B φ = β·K φ is solved for the largest algebraic
    β = 1/λ (eigsh which='LA'), giving the smallest positive λ.  Modes with no
    geometric stiffness (β ≈ 0, e.g. purely axial DOFs) map to λ → ∞ and are
    dropped.
    """
    B = (-Kg).tocsc()
    n = K.shape[0]
    k = min(n_modes, n - 2)
    if k < 1:
        k = 1
    # eigsh needs k < n; for tiny systems fall back to a dense generalized solve.
    import scipy.linalg as sla
    if n <= max(2 * k + 2, 20):
        beta, vecs = sla.eigh(B.toarray(), K.toarray())
    else:
        try:
            beta, vecs = spla.eigsh(B, k=k, M=K, which="LA")
        except (spla.ArpackError, spla.ArpackNoConvergence):
            # ARPACK cannot build an Arnoldi factorization when there is no
            # positive buckling mode in the requested set — e.g. a tensile
            # reference load, where B = -K_g has no large positive algebraic
            # eigenvalue relative to K. The dense symmetric generalized
            # eigensolve always resolves it (these buckling systems are small),
            # and the good-mode filter below then correctly yields no positive λ.
            beta, vecs = sla.eigh(B.toarray(), K.toarray())
    order = np.argsort(beta)[::-1]                     # largest β first
    beta, vecs = beta[order], vecs[:, order]
    good = beta > 1e-9 * max(abs(beta).max(), 1e-30)
    beta, vecs = beta[good], vecs[:, good]
    lam = 1.0 / beta
    order = np.argsort(lam)
    lam, vecs = lam[order], vecs[:, order]
    return lam[:n_modes], vecs[:, :n_modes]


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="modal_buckling",
        description="Offline linear (eigenvalue) buckling from an OpenRadioss "
                    "/IMPL/PRINT/STIF stiffness export + a reference load. "
                    "Beam elements are validated (Euler column); shells carry "
                    "the consistent membrane K_g (validated vs the SSSS "
                    "plate); solids are warned as unsupported.")
    ap.add_argument("matrix", help="path to local_stiffness_matrix_domain0")
    ap.add_argument("k_file", help="source LS-DYNA .k file (mesh + sections)")
    ap.add_argument("--load", nargs=3, required=True,
                    metavar=("NODE", "DIR", "FORCE"),
                    help="reference load: FORCE on user NODE along DIR "
                         "(X|Y|Z|XX|YY|ZZ). Buckling factor lambda multiplies "
                         "THIS load, so P_cr = lambda*FORCE.")
    ap.add_argument("-n", "--n-modes", type=int, default=5, metavar="N",
                    help="number of buckling modes to report (default 5)")
    ap.add_argument("-o", "--output", default=None, metavar="NPZ",
                    help="save buckling factors + mode shapes (default: "
                         "buckling.npz next to the matrix file)")
    args = ap.parse_args(argv)

    if not _HAVE_SCIPY:
        print("ERROR: numpy + scipy are required (pip install scipy - see "
              "docs/DEPENDENCIES.md)", file=sys.stderr)
        return 1

    print(f"Reading stiffness matrix: {args.matrix}")
    stiff = modal_solve.read_stiffness(args.matrix)
    print(f"  K: {len(stiff.gids)} free DOFs, {stiff.K.nnz} nonzeros")
    if stiff.low_precision:
        print("  WARNING: matrix printed by a STOCK engine (E10.2) - buckling "
              "factors carry the same ~1% stiffness rounding.")

    node = int(args.load[0])
    try:
        dof = _DIR_TO_DOF[args.load[1].upper()]
    except KeyError:
        print(f"ERROR: unknown direction {args.load[1]!r} (use X|Y|Z|XX|YY|ZZ)",
              file=sys.stderr)
        return 1
    force = float(args.load[2])

    print(f"Parsing deck: {args.k_file}")
    state = parse_deck(args.k_file)
    mesh = build_mesh(state)

    print(f"  reference static solve: F={force:g} on node {node} "
          f"{DOF_NAMES[dof - 1]}")
    u = modal_solve.solve_static(stiff, node, dof, force)

    print("Assembling geometric stiffness from beam + shell elements ...")
    Kg, counts, axial = assemble_geometric_stiffness(state, mesh, stiff, u)
    print(f"  {counts['beam']} beam element(s) contributed K_g")
    print(f"  {counts['shell_kg']} shell element(s) contributed the consistent "
          "membrane K_g")
    if counts["shell_skipped"]:
        print(f"  WARNING: {counts['shell_skipped']} shell element(s) had no "
              "usable *SECTION_SHELL thickness / elastic material / geometry "
              "and were SKIPPED from the geometric stiffness.")
    if counts["solid"]:
        print(f"  WARNING: {counts['solid']} solid element(s) are UNSUPPORTED "
              "for geometric stiffness and were SKIPPED (beams and shells are "
              "supported). Buckling factors reflect the beam/shell "
              "sub-structure only; for solid-dominated models they are NOT "
              "valid.")
    if (counts["beam"] + counts["shell_kg"]) == 0 or Kg.nnz == 0:
        print("ERROR: no geometric stiffness assembled (no supported beam/"
              "shell elements carried internal force under the reference "
              "load). Refusing to report a buckling factor.", file=sys.stderr)
        return 1
    if axial:
        amin, amax = min(axial), max(axial)
        print(f"  recovered beam axial forces: {amin:.4G} .. {amax:.4G} "
              "(tension +, compression -)")

    print(f"Solving for {args.n_modes} buckling mode(s) ...")
    lam, phi = solve_buckling(stiff.K, Kg, args.n_modes)
    if len(lam) == 0:
        print("ERROR: no positive buckling factor found - the reference load "
              "may be tensile (stabilizing) in the buckling-prone members.",
              file=sys.stderr)
        return 1

    print("\n  mode | buckling factor lambda |  P_cr = lambda*FORCE")
    for i, l in enumerate(lam, 1):
        print(f"  {i:4d} | {l:21.6G} | {l * force:.6G}")
    print("\n  (lambda multiplies the reference load; the lowest positive "
          "lambda is the critical buckling factor.)")

    out = args.output or str(Path(args.matrix).parent / "buckling.npz")
    np.savez(out, buckling_factors=lam, phi=phi,
             user_node=stiff.user_node, dof=stiff.dof, gids=stiff.gids,
             axial_forces=np.array(axial))
    print(f"  buckling modes saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
