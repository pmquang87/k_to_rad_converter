"""Unit tests for the Tier-4 offline analysis extensions that ride the modal
K-export chain::

    python -m unittest tests.test_modal_analysis -v

Covers the two new tools under ``tools/``:

* ``modal_frf.py``      – harmonic / frequency-response output; validated against
  the closed-form single-DOF FRF (dynamic-amplification peak = 1/(2ζ) and
  half-power bandwidth Δf = 2ζ·f_n) and against the reused
  ``modal_random_response.frf_matrix`` kernel;
* ``modal_buckling.py`` – linear (eigenvalue) buckling; validated against the
  analytic Euler pin-pinned column  P_cr = π²·E·I/L²  (beam K_g) and the
  analytic simply supported square plate under uniaxial compression
  σ_cr = 4·π²·E/(12(1−ν²))·(t/b)²  (shell consistent-membrane K_g).

Both tools are gated on numpy / scipy exactly like the existing modal tools, so
these tests self-skip when those libraries are unavailable.
"""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# The package and the offline tools live outside tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from k2rad.parser import parse_k_file          # noqa: E402
from k2rad.handlers import dispatch            # noqa: E402
from k2rad.state import ConversionState        # noqa: E402

import modal_common                            # noqa: E402
import modal_solve                             # noqa: E402
import modal_random_response                   # noqa: E402
import modal_frf                               # noqa: E402
import modal_buckling                          # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Shared beam-column model (a pin-pinned Euler column discretised into N beams)
# ─────────────────────────────────────────────────────────────────────────────

def _beam_column_deck(n_el, L, A, I, E, orient=100000):
    """A straight *ELEMENT_BEAM column along +X with an elastic *SECTION_BEAM."""
    le = L / n_el
    out = ["*KEYWORD", "*TITLE", "beam column", "*NODE"]
    for i in range(n_el + 1):
        out.append(f"{i + 1:8d}{i * le:16.6f}{0.0:16.6f}{0.0:16.6f}")
    out.append(f"{orient:8d}{0.0:16.6f}{1.0:16.6f}{0.0:16.6f}")   # orientation
    out.append("*ELEMENT_BEAM")
    for e in range(n_el):
        out.append(f"{e + 1:8d}{1:8d}{e + 1:8d}{e + 2:8d}{orient:8d}")
    out += ["*PART", "beam part", f"{1:10d}{1:10d}{1:10d}",
            "*SECTION_BEAM", f"{1:10d}{2:10d}",
            f"{A:10.1f}{I:10.1f}{I:10.1f}{I:10.1f}",
            "*MAT_ELASTIC", f"{1:10d}{7.8e-9:10.3e}{E:10.1f}{0.3:10.2f}",
            "*END"]
    return "\n".join(out) + "\n"


class _Column:
    """Assembled elastic beam-column ready for the buckling / FRF tools.

    The elastic K is built here with the SAME consistent Euler–Bernoulli beam
    element that a fine OpenRadioss beam mesh converges to, so the tool's
    geometric-stiffness assembly can be validated against the analytic Euler
    load without needing a live engine export.  DOFs kept per node: TX(1),
    TY(2), RZ(6); pin-pinned BCs remove node-1 TX/TY and the tip TY.
    """

    def __init__(self, n_el=10, L=1000.0, A=100.0, I=800.0, E=210000.0):
        import numpy as np
        import scipy.sparse as sp
        self.n_el, self.L, self.A, self.I, self.E = n_el, L, A, I, E
        self.le = le = L / n_el
        self.EI = E * I

        # mkdtemp (not TemporaryDirectory) so the helper carries no finalizer
        # that would emit a ResourceWarning during test teardown.
        self.dir = tempfile.mkdtemp()
        self.kpath = os.path.join(self.dir, "col.k")
        with open(self.kpath, "w") as fh:
            fh.write(_beam_column_deck(n_el, L, A, I, E))
        self.state = ConversionState()
        for block in parse_k_file(self.kpath):
            dispatch(block, self.state)
        self.mesh = modal_common.build_mesh(self.state)

        dofs = [(i, d) for i in range(1, n_el + 2) for d in (1, 2, 6)]
        idx = {dd: k for k, dd in enumerate(dofs)}
        n = len(dofs)
        K = np.zeros((n, n))
        for e in range(n_el):
            n1, n2 = e + 1, e + 2
            axial = (E * A / le) * np.array([[1.0, -1.0], [-1.0, 1.0]])
            a = [idx[(n1, 1)], idx[(n2, 1)]]
            for p in range(2):
                for q in range(2):
                    K[a[p], a[q]] += axial[p, q]
            kb = (self.EI / le ** 3) * np.array([
                [12.0, 6 * le, -12.0, 6 * le],
                [6 * le, 4 * le ** 2, -6 * le, 2 * le ** 2],
                [-12.0, -6 * le, 12.0, -6 * le],
                [6 * le, 2 * le ** 2, -6 * le, 4 * le ** 2]])
            b = [idx[(n1, 2)], idx[(n1, 6)], idx[(n2, 2)], idx[(n2, 6)]]
            for p in range(4):
                for q in range(4):
                    K[b[p], b[q]] += kb[p, q]

        constrained = {(1, 1), (1, 2), (n_el + 1, 2)}     # pin-pinned column
        keep = [k for k, dd in enumerate(dofs) if dd not in constrained]
        K = K[np.ix_(keep, keep)]
        kept = [dofs[k] for k in keep]
        gids = np.array([6 * (nn - 1) + dd for nn, dd in kept])
        order = np.argsort(gids)
        gids = gids[order]
        K = K[np.ix_(order, order)]
        kept = [kept[i] for i in order]
        self.kept = kept
        self.gids = gids
        self.K = K
        self.user_node = np.array([nn for nn, dd in kept], dtype=np.int64)
        self.dof = np.array([dd for nn, dd in kept], dtype=np.int64)
        self.stiff = modal_solve.StiffnessMatrix(
            n_declared=len(gids), gids=gids, K=sp.csc_matrix(K),
            user_node=self.user_node, dof=self.dof, low_precision=False)

    def euler_pcr(self):
        return math.pi ** 2 * self.EI / self.L ** 2

    def write_matrix_file(self, path):
        """Emit the elastic K in the read_stiffness "N N NZ / II JJ V" format
        (one lower triangle in gid space, II >= JJ)."""
        n = len(self.gids)
        entries = []
        for i in range(n):
            for j in range(i + 1):
                v = self.K[i, j]
                if v != 0.0:
                    gi, gj = int(self.gids[i]), int(self.gids[j])
                    ii, jj = (gi, gj) if gi >= gj else (gj, gi)
                    entries.append((ii, jj, v))
        with open(path, "w") as fh:
            fh.write(f"{n} {n} {len(entries)}\n")
            for ii, jj, v in entries:
                fh.write(f"{ii:10d}{jj:10d}  {v:.16E}\n")

    def synth_modes_npz(self, path, n_modes=4):
        """A realistic modes.npz for the column via a dense generalized eig
        (lumped translational mass, rotational/axial DOFs regularised)."""
        import numpy as np
        import scipy.linalg as sla
        node_mass, _ = modal_solve.nodal_masses_from_state(self.state)
        md = np.array([node_mass.get(int(nn), 0.0) if dd <= 3 else 0.0
                       for nn, dd in self.kept])
        md = md + md[md > 0].min() * 1e-6
        lam, vec = sla.eigh(self.K, np.diag(md))
        freq = np.sqrt(np.maximum(lam, 0.0)) / (2.0 * math.pi)
        np.savez(path, freq=freq[:n_modes], phi=vec[:, :n_modes],
                 user_node=self.user_node, dof=self.dof, gids=self.gids)
        return freq[:n_modes]


# ─────────────────────────────────────────────────────────────────────────────
# Shared plate model (a simply supported square plate meshed with N×N quads)
# ─────────────────────────────────────────────────────────────────────────────

def _plate_deck(nx, ny, a, b, t, E, nu, rho=7.8e-9):
    """A flat *ELEMENT_SHELL plate in the x-y plane with *SECTION_SHELL t."""
    dx, dy = a / nx, b / ny

    def nid(i, j):
        return j * (nx + 1) + i + 1

    out = ["*KEYWORD", "*TITLE", "square plate", "*NODE"]
    for j in range(ny + 1):
        for i in range(nx + 1):
            out.append(f"{nid(i, j):8d}{i * dx:16.6f}{j * dy:16.6f}{0.0:16.6f}")
    out.append("*ELEMENT_SHELL")
    eid = 1
    for j in range(ny):
        for i in range(nx):
            out.append(f"{eid:8d}{1:8d}{nid(i, j):8d}{nid(i + 1, j):8d}"
                       f"{nid(i + 1, j + 1):8d}{nid(i, j + 1):8d}")
            eid += 1
    out += ["*PART", "plate part", f"{1:10d}{1:10d}{1:10d}",
            "*SECTION_SHELL", f"{1:10d}{2:10d}", f"{t:10.4f}",
            "*MAT_ELASTIC", f"{1:10d}{rho:10.3e}{E:10.1f}{nu:10.2f}",
            "*END"]
    return "\n".join(out) + "\n"


def _membrane_quad_k(dx, dy, E, nu, t):
    """Bilinear plane-stress rectangle (2×2 Gauss), DOFs [u1,v1,...,u4,v4]."""
    import numpy as np
    D = (E * t / (1.0 - nu * nu)) * np.array(
        [[1.0, nu, 0.0], [nu, 1.0, 0.0], [0.0, 0.0, (1.0 - nu) / 2.0]])
    xy = np.array([[0.0, 0.0], [dx, 0.0], [dx, dy], [0.0, dy]])
    g = 1.0 / math.sqrt(3.0)
    K = np.zeros((8, 8))
    for xi in (-g, g):
        for eta in (-g, g):
            dN = 0.25 * np.array([[-(1 - eta), -(1 - xi)],
                                  [(1 - eta), -(1 + xi)],
                                  [(1 + eta), (1 + xi)],
                                  [-(1 + eta), (1 - xi)]])
            J = dN.T @ xy
            detJ = np.linalg.det(J)
            G = np.linalg.solve(J, dN.T)                # rows: d/dx, d/dy
            B = np.zeros((3, 8))
            for k in range(4):
                B[0, 2 * k] = G[0, k]
                B[1, 2 * k + 1] = G[1, k]
                B[2, 2 * k] = G[1, k]
                B[2, 2 * k + 1] = G[0, k]
            K += (B.T @ D @ B) * detJ
    return K


def _acm_bending_k(dx, dy, E, nu, t):
    """12-DOF non-conforming ACM/MZC rectangular plate-bending element.

    DOFs per node: (w, θx=∂w/∂y, θy=−∂w/∂x) — the exported-K RX/RY sign
    convention.  Built numerically from the 12-term polynomial basis
    (1, x, y, x², xy, y², x³, x²y, xy², y³, x³y, xy³) with 4×4 Gauss (exact
    for these polynomial orders).  Valid for RECTANGULAR elements only, which
    is all the regular fixture mesh contains.
    """
    import numpy as np
    D = (E * t ** 3 / (12.0 * (1.0 - nu * nu))) * np.array(
        [[1.0, nu, 0.0], [nu, 1.0, 0.0], [0.0, 0.0, (1.0 - nu) / 2.0]])
    ax, by = dx / 2.0, dy / 2.0
    corners = [(-ax, -by), (ax, -by), (ax, by), (-ax, by)]

    def p(x, y):
        return np.array([1, x, y, x * x, x * y, y * y, x ** 3, x * x * y,
                         x * y * y, y ** 3, x ** 3 * y, x * y ** 3])

    def px(x, y):
        return np.array([0, 1, 0, 2 * x, y, 0, 3 * x * x, 2 * x * y, y * y, 0,
                         3 * x * x * y, y ** 3])

    def py(x, y):
        return np.array([0, 0, 1, 0, x, 2 * y, 0, x * x, 2 * x * y,
                         3 * y * y, x ** 3, 3 * x * y * y])

    def pxx(x, y):
        return np.array([0, 0, 0, 2, 0, 0, 6 * x, 2 * y, 0, 0, 6 * x * y, 0])

    def pyy(x, y):
        return np.array([0, 0, 0, 0, 0, 2, 0, 0, 2 * x, 6 * y, 0, 6 * x * y])

    def pxy(x, y):
        return np.array([0, 0, 0, 0, 1, 0, 0, 2 * x, 2 * y, 0,
                         3 * x * x, 3 * y * y])

    C = np.zeros((12, 12))
    for k, (x, y) in enumerate(corners):
        C[3 * k] = p(x, y)
        C[3 * k + 1] = py(x, y)                          # θx =  ∂w/∂y
        C[3 * k + 2] = -px(x, y)                         # θy = −∂w/∂x
    Ci = np.linalg.inv(C)
    gp, gw = np.polynomial.legendre.leggauss(4)
    Kc = np.zeros((12, 12))
    for xi, wx in zip(gp, gw):
        for eta, wy in zip(gp, gw):
            x, y = ax * xi, by * eta
            B = np.vstack([pxx(x, y), pyy(x, y), 2.0 * pxy(x, y)])
            Kc += (B.T @ D @ B) * (wx * wy * ax * by)
    return Ci.T @ Kc @ Ci


class _Plate:
    """Assembled elastic flat-shell K for a square plate, ready for the
    buckling tool (the plate analogue of :class:`_Column`).

    The tool needs the ELASTIC K too, so it is assembled here: bilinear
    plane-stress membrane + the 12-DOF non-conforming ACM rectangular
    plate-bending element (converges for the REGULAR RECTANGULAR mesh this
    fixture generates — the only mesh it supports).  DOFs kept per node:
    TX,TY (membrane) and TZ,RX,RY (bending); the drilling DOF RZ is absent,
    exactly like a real exported K with AUTOSPC.

    ``bc='ssss'`` applies hard simple supports (w=0 on all edges plus the
    tangential-derivative edge rotation) and membrane supports ux=0 on x=0,
    uy=0 on y=0 — compatible with an exact uniform uniaxial membrane field.
    ``bc='free'`` keeps every DOF (K is then singular; only used to feed
    rigid-body displacement fields to the K_g assembly).
    """

    def __init__(self, n=8, a=1000.0, t=10.0, E=210000.0, nu=0.3, bc="ssss"):
        import numpy as np
        import scipy.sparse as sp
        self.n, self.a, self.b, self.t, self.E, self.nu = n, a, a, t, E, nu
        dx = dy = a / n
        self.dir = tempfile.mkdtemp()
        self.kpath = os.path.join(self.dir, "plate.k")
        with open(self.kpath, "w") as fh:
            fh.write(_plate_deck(n, n, a, a, t, E, nu))
        self.state = ConversionState()
        for block in parse_k_file(self.kpath):
            dispatch(block, self.state)
        self.mesh = modal_common.build_mesh(self.state)

        def nid(i, j):
            return j * (n + 1) + i + 1

        self._nid = nid
        dofs = [(nid(i, j), d) for j in range(n + 1) for i in range(n + 1)
                for d in (1, 2, 3, 4, 5)]
        idx = {dd: k for k, dd in enumerate(dofs)}
        K = np.zeros((len(dofs), len(dofs)))
        km = _membrane_quad_k(dx, dy, E, nu, t)
        kb = _acm_bending_k(dx, dy, E, nu, t)
        for j in range(n):
            for i in range(n):
                nids = [nid(i, j), nid(i + 1, j), nid(i + 1, j + 1),
                        nid(i, j + 1)]
                m = [idx[(nn, d)] for nn in nids for d in (1, 2)]
                K[np.ix_(m, m)] += km
                bnd = [idx[(nn, d)] for nn in nids for d in (3, 4, 5)]
                K[np.ix_(bnd, bnd)] += kb

        constrained = set()
        if bc == "ssss":
            for j in range(n + 1):
                constrained.add((nid(0, j), 1))          # ux = 0 on x = 0
            for i in range(n + 1):
                constrained.add((nid(i, 0), 2))          # uy = 0 on y = 0
            for j in range(n + 1):
                for i in range(n + 1):
                    edge_x, edge_y = i in (0, n), j in (0, n)
                    if edge_x or edge_y:
                        constrained.add((nid(i, j), 3))  # w = 0 on all edges
                    if edge_x:
                        constrained.add((nid(i, j), 4))  # θx = ∂w/∂y = 0
                    if edge_y:
                        constrained.add((nid(i, j), 5))  # θy = −∂w/∂x = 0
        keep = [k for k, dd in enumerate(dofs) if dd not in constrained]
        K = K[np.ix_(keep, keep)]
        kept = [dofs[k] for k in keep]
        gids = np.array([6 * (nn - 1) + dd for nn, dd in kept])
        order = np.argsort(gids)
        gids = gids[order]
        K = K[np.ix_(order, order)]
        kept = [kept[i] for i in order]
        self.kept = kept
        self.gids = gids
        self.pos = {dd: k for k, dd in enumerate(kept)}
        self.user_node = np.array([nn for nn, dd in kept], dtype=np.int64)
        self.dof = np.array([dd for nn, dd in kept], dtype=np.int64)
        self.stiff = modal_solve.StiffnessMatrix(
            n_declared=len(gids), gids=gids, K=sp.csc_matrix(K),
            user_node=self.user_node, dof=self.dof, low_precision=False)

    def presolve_uniaxial(self, n0=10.0):
        """u for a uniform compressive edge load Nx = −n0 (force/length) on
        x = a: consistent nodal forces (half shares at the edge corners), so
        the discrete solution is the EXACT uniform field σx = −n0/t."""
        import numpy as np
        import scipy.sparse.linalg as spla
        n = self.n
        dy = self.a / n
        f = np.zeros(len(self.gids))
        for j in range(n + 1):
            share = dy if 0 < j < n else dy / 2.0
            f[self.pos[(self._nid(n, j), 1)]] -= n0 * share
        return spla.spsolve(self.stiff.K, f)

    def sigma_cr(self):
        """Analytic SSSS uniaxial plate buckling stress, k = 4 (square, m=1)."""
        return (4.0 * math.pi ** 2 * self.E
                / (12.0 * (1.0 - self.nu ** 2)) * (self.t / self.b) ** 2)


# ─────────────────────────────────────────────────────────────────────────────
# Harmonic / FRF tool
# ─────────────────────────────────────────────────────────────────────────────

class ModalFrfTests(unittest.TestCase):
    """tools/modal_frf.py — validated against the closed-form SDOF FRF and the
    reused modal_random_response.frf_matrix kernel (numpy required; self-skips)."""

    def setUp(self):
        if not modal_common._HAVE_NUMPY:
            self.skipTest("modal_frf needs numpy")

    def test_sdof_peak_amplification_and_bandwidth(self):
        import numpy as np
        fn, gamma, zeta = 10.0, np.array([1.3]), 0.02
        modes_hz = np.array([fn])
        grid = np.linspace(0.01, 25.0, 200001)
        q = modal_frf.base_modal_coeffs(modes_hz, grid, zeta, gamma)
        mag = np.abs(q[:, 0])
        static = abs(gamma[0]) / (2 * math.pi * fn) ** 2      # ω→0 limit
        peak = mag.max()
        # dynamic amplification factor at resonance = 1/(2ζ)
        self.assertAlmostEqual(peak / static, 1.0 / (2 * zeta), delta=0.01)
        # resonance sits at f_n
        self.assertAlmostEqual(grid[mag.argmax()], fn, delta=0.02)
        # half-power (−3 dB) bandwidth = 2ζ·f_n
        band = mag >= peak / math.sqrt(2.0)
        where = np.nonzero(band)[0]
        bw = grid[where[-1]] - grid[where[0]]
        self.assertAlmostEqual(bw, 2 * zeta * fn, delta=0.01 * (2 * zeta * fn))

    def test_base_coeffs_are_the_reused_frf_matrix(self):
        import numpy as np
        modes_hz = np.array([12.0, 30.0])
        grid = np.linspace(1.0, 50.0, 500)
        gamma = np.array([0.8, -0.5])
        q = modal_frf.base_modal_coeffs(modes_hz, grid, 0.03, gamma)
        H = modal_random_response.frf_matrix(modes_hz, grid, 0.03, gamma)
        # identical: FRF and random vibration share one validated kernel
        self.assertTrue(np.array_equal(q, H))

    def test_load_coeffs_match_closed_form(self):
        import numpy as np
        modes_hz = np.array([8.0, 21.0])
        grid = np.array([5.0, 8.0, 15.0])
        mf = np.array([0.7, -1.1])
        q = modal_frf.load_modal_coeffs(modes_hz, grid, 0.02, mf)
        w = 2 * math.pi * grid[:, None]
        wj = 2 * math.pi * modes_hz[None, :]
        ref = mf[None, :] / (wj ** 2 - w ** 2 + 2j * 0.02 * wj * w)
        np.testing.assert_allclose(q, ref)

    def test_assemble_response_is_modal_sum(self):
        import numpy as np
        coeffs = np.array([[1 + 1j, 2.0], [0.0, 1j]])         # (2 freq, 2 modes)
        shapes = np.array([[[1.0, 0.0, 0.0]], [[0.0, 2.0, 0.0]]])  # (2 modes,1,3)
        u = modal_frf.assemble_response(coeffs, shapes)
        np.testing.assert_allclose(u[0, 0], [1 + 1j, 4.0, 0.0])
        np.testing.assert_allclose(u[1, 0], [0.0, 2j, 0.0])

    def test_nodal_modal_force_missing_dof_errors(self):
        import numpy as np
        modes = modal_common.ModeSet(
            freq=np.array([1.0]), phi=np.array([[0.5]]),
            user_node=np.array([7]), dof=np.array([2]))
        self.assertAlmostEqual(
            float(modal_frf.nodal_modal_force(modes, 7, 2, 3.0)[0]), 1.5)
        with self.assertRaises(SystemExit):
            modal_frf.nodal_modal_force(modes, 7, 1, 1.0)   # DOF absent

    def test_frf_band_override(self):
        import numpy as np
        modes = np.array([10.0, 40.0])
        fmin, fmax, _ = modal_frf.frf_band(None, None, modes)
        self.assertAlmostEqual(fmin, 5.0)
        self.assertAlmostEqual(fmax, 60.0)
        fmin, fmax, _ = modal_frf.frf_band(2.0, 99.0, modes)
        self.assertEqual((fmin, fmax), (2.0, 99.0))

    def test_main_end_to_end_writes_csv_with_resonance(self):
        import csv
        import numpy as np
        col = _Column(n_el=10)
        with tempfile.TemporaryDirectory() as tmp:
            npz = os.path.join(tmp, "col_modes.npz")
            freqs = col.synth_modes_npz(npz, n_modes=4)
            stem = os.path.join(tmp, "frf")
            rc = modal_frf.main([npz, col.kpath, "--load", "6", "Y", "1.0",
                                 "--nf", "300", "-o", stem])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(stem + "_frf_peaks.csv"))
            node_csv = stem + "_frf_node_6.csv"
            self.assertTrue(os.path.exists(node_csv))
            with open(node_csv) as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0][0], "freq_hz")
            f = np.array([float(r[0]) for r in rows[1:]])
            mag = np.array([float(r[-1]) for r in rows[1:]])
            # the response near the first resonance is far above the low-f tail
            near = mag[np.abs(f - freqs[0]) < 1.0].max()
            base = mag[f < 0.6 * freqs[0]].max()
            self.assertGreater(near, 10.0 * base)


# ─────────────────────────────────────────────────────────────────────────────
# Linear buckling tool
# ─────────────────────────────────────────────────────────────────────────────

class ModalBucklingTests(unittest.TestCase):
    """tools/modal_buckling.py — validated against the analytic Euler column
    P_cr = π²EI/L² (numpy+scipy required; self-skips)."""

    def setUp(self):
        if not modal_buckling._HAVE_SCIPY:
            self.skipTest("modal_buckling needs numpy+scipy")

    def test_euler_pin_pinned_column(self):
        import numpy as np
        col = _Column(n_el=10)
        P = 1000.0
        u = modal_solve.solve_static(col.stiff, col.n_el + 1, 1, -P)
        Kg, counts, axial = modal_buckling.assemble_geometric_stiffness(
            col.state, col.mesh, col.stiff, u)
        self.assertEqual(counts["beam"], col.n_el)
        # uniform axial compression = -P recovered in every element
        np.testing.assert_allclose(axial, -P, rtol=1e-9)
        lam, phi = modal_buckling.solve_buckling(col.stiff.K, Kg, 3)
        p_cr = lam[0] * P
        self.assertAlmostEqual(p_cr / col.euler_pcr(), 1.0, delta=0.01)

    def test_higher_buckling_modes_follow_n_squared(self):
        col = _Column(n_el=16)
        P = 500.0
        u = modal_solve.solve_static(col.stiff, col.n_el + 1, 1, -P)
        Kg, _, _ = modal_buckling.assemble_geometric_stiffness(
            col.state, col.mesh, col.stiff, u)
        lam, _ = modal_buckling.solve_buckling(col.stiff.K, Kg, 3)
        # Euler modes scale as n^2: λ2/λ1 ≈ 4, λ3/λ1 ≈ 9
        self.assertAlmostEqual(lam[1] / lam[0], 4.0, delta=0.05)
        self.assertAlmostEqual(lam[2] / lam[0], 9.0, delta=0.25)

    def test_geometric_stiffness_is_symmetric(self):
        col = _Column(n_el=6)
        u = modal_solve.solve_static(col.stiff, col.n_el + 1, 1, -100.0)
        Kg, _, _ = modal_buckling.assemble_geometric_stiffness(
            col.state, col.mesh, col.stiff, u)
        d = (Kg - Kg.T)
        self.assertLess(abs(d).max() if d.nnz else 0.0, 1e-9)

    def test_tension_reference_gives_no_positive_buckling_factor(self):
        # A tensile reference load stiffens (K_g > 0), so there is no positive
        # buckling factor — the honest answer, not a bogus number.
        col = _Column(n_el=8)
        u = modal_solve.solve_static(col.stiff, col.n_el + 1, 1, +1000.0)
        Kg, _, axial = modal_buckling.assemble_geometric_stiffness(
            col.state, col.mesh, col.stiff, u)
        self.assertGreater(axial[0], 0.0)                 # tension
        lam, _ = modal_buckling.solve_buckling(col.stiff.K, Kg, 3)
        self.assertEqual(len(lam), 0)

    def test_shells_solids_reported_for_warning(self):
        # A shell/solid element in the deck must be counted (so main() can warn)
        # and skipped from the geometric stiffness, never silently mis-assembled.
        col = _Column(n_el=4)
        from k2rad.state import ShellElem
        col.state.shell_elems.append(ShellElem(999, 1, [1, 2, 3, 4]))
        mesh = modal_common.build_mesh(col.state)
        u = modal_solve.solve_static(col.stiff, col.n_el + 1, 1, -100.0)
        Kg, counts, _ = modal_buckling.assemble_geometric_stiffness(
            col.state, mesh, col.stiff, u)
        self.assertEqual(counts["shell"], 1)
        self.assertEqual(counts["beam"], col.n_el)        # beams still assembled

    def test_main_end_to_end_matches_euler(self):
        import numpy as np
        col = _Column(n_el=12)
        with tempfile.TemporaryDirectory() as tmp:
            mpath = os.path.join(tmp, "local_stiffness_matrix_domain0")
            col.write_matrix_file(mpath)
            out = os.path.join(tmp, "buck.npz")
            P = 1234.0
            rc = modal_buckling.main(
                [mpath, col.kpath, "--load", str(col.n_el + 1), "X", str(-P),
                 "-n", "3", "-o", out])
            self.assertEqual(rc, 0)
            # Close the NpzFile before the TemporaryDirectory is torn down —
            # on Windows an open file handle blocks the temp-dir cleanup.
            with np.load(out) as d:
                p_cr = d["buckling_factors"][0] * P
            self.assertAlmostEqual(p_cr / col.euler_pcr(), 1.0, delta=0.01)


class PlateBucklingTests(unittest.TestCase):
    """tools/modal_buckling.py shell membrane K_g — validated against the
    analytic SSSS square plate σ_cr = 4·π²·E/(12(1−ν²))·(t/b)² and against a
    closed-form single-CST check (numpy+scipy required; self-skips).

    The ELASTIC K comes from the _Plate fixture's own flat-shell assembly
    (bilinear plane-stress membrane + ACM rectangular bending, regular mesh
    only) written into the same StiffnessMatrix container a real
    /IMPL/PRINT/STIF export produces — the tool's stress recovery, K_g
    assembly, and eigensolve are exercised exactly as in the _Column tests.
    """

    def setUp(self):
        if not modal_buckling._HAVE_SCIPY:
            self.skipTest("modal_buckling needs numpy+scipy")

    def test_ssss_plate_buckling_matches_analytic_k4(self):
        plate = _Plate(n=8)
        n0 = 10.0                                       # reference Nx [F/L]
        u = plate.presolve_uniaxial(n0)
        Kg, counts, _ = modal_buckling.assemble_geometric_stiffness(
            plate.state, plate.mesh, plate.stiff, u)
        self.assertEqual(counts["shell_kg"], plate.n ** 2)
        self.assertEqual(counts["shell_skipped"], 0)
        lam, _ = modal_buckling.solve_buckling(plate.stiff.K, Kg, 3)
        n_cr = lam[0] * n0
        analytic = plate.sigma_cr() * plate.t           # N_cr = sigma_cr * t
        ratio = n_cr / analytic
        print(f"\n  SSSS 8x8 plate: N_cr = {n_cr:.4f} vs analytic k=4 "
              f"{analytic:.4f} -> measured ratio {ratio:.4f} "
              "(mesh convergence: 12x12 -> 1.010, 16x16 -> 1.005)")
        # measured +2.2% at 8x8 (ACM bending vs consistent membrane K_g),
        # quadratic convergence to the analytic value -> assert within 3%.
        self.assertAlmostEqual(ratio, 1.0, delta=0.03)

    def test_plate_kg_symmetry(self):
        plate = _Plate(n=4)
        u = plate.presolve_uniaxial(25.0)
        Kg, _, _ = modal_buckling.assemble_geometric_stiffness(
            plate.state, plate.mesh, plate.stiff, u)
        self.assertGreater(Kg.nnz, 0)
        d = Kg - Kg.T
        self.assertLess(abs(d).max() if d.nnz else 0.0, 1e-9)

    def test_rigid_inplane_translation_zero_kg_energy(self):
        import numpy as np
        plate = _Plate(n=4, bc="free")

        def field(fx, fy):
            out = np.zeros(len(plate.kept))
            for k, (nn, d) in enumerate(plate.kept):
                x, y = plate.state.nodes[nn].x, plate.state.nodes[nn].y
                if d == 1:
                    out[k] = fx(x, y)
                elif d == 2:
                    out[k] = fy(x, y)
            return out

        # reference: a genuinely strained pre-solve field -> nonzero K_g
        u_strain = field(lambda x, y: -1e-3 * x + 2e-4 * y,
                         lambda x, y: 1e-4 * x - 5e-4 * y)
        Kgs, _, _ = modal_buckling.assemble_geometric_stiffness(
            plate.state, plate.mesh, plate.stiff, u_strain)
        ref = abs(Kgs).max()
        self.assertGreater(ref, 0.0)

        # (a) a rigid in-plane translation as the pre-solve displacement
        #     recovers zero membrane force -> zero geometric stiffness
        u_rigid = field(lambda x, y: 0.7, lambda x, y: -1.3)
        Kg0, _, _ = modal_buckling.assemble_geometric_stiffness(
            plate.state, plate.mesh, plate.stiff, u_rigid)
        z = abs(Kg0).max() if Kg0.nnz else 0.0
        self.assertLess(z, 1e-12 * ref)

        # (b) under a real pre-stress, a rigid translation mode carries zero
        #     K_g energy (shape-function gradients annihilate constants)
        for t_vec in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            phi = np.array([t_vec[d - 1] if d <= 3 else 0.0
                            for nn, d in plate.kept])
            energy = float(phi @ (Kgs @ phi))
            self.assertLess(abs(energy), 1e-10 * ref * float(phi @ phi))

    def _cst_triangle(self, L=100.0, t=2.5, E=70000.0, nu=0.33):
        """One right CST in the x-y plane, its StiffnessMatrix stub and props."""
        import numpy as np
        import scipy.sparse as sp
        from k2rad.state import (NodeData, PartData, SectionShell, ShellElem,
                                 MatElastic)
        state = ConversionState()
        state.nodes[1] = NodeData(0.0, 0.0, 0.0)
        state.nodes[2] = NodeData(L, 0.0, 0.0)
        state.nodes[3] = NodeData(0.0, L, 0.0)
        state.parts[1] = PartData(1, "tri", 1, 1)
        state.sec_shells[1] = SectionShell(1, "", 2, 3, t)
        state.mat_elastic[1] = MatElastic(1, "", 7.8e-9, E, nu)
        state.shell_elems.append(ShellElem(1, 1, [1, 2, 3]))
        mesh = modal_common.build_mesh(state)
        dofs = [(nn, d) for nn in (1, 2, 3) for d in (1, 2, 3)]
        gids = np.array(sorted(6 * (nn - 1) + d for nn, d in dofs))
        stiff = modal_solve.StiffnessMatrix(
            n_declared=len(gids), gids=gids,
            K=sp.identity(len(gids), format="csc"),
            user_node=((gids - 1) // 6 + 1).astype(np.int64),
            dof=((gids - 1) % 6 + 1).astype(np.int64),
            low_precision=False)
        return state, mesh, stiff, (L, t, E, nu)

    def test_cst_triangle_kg_matches_closed_form(self):
        import numpy as np
        state, mesh, stiff, (L, t, E, nu) = self._cst_triangle()
        pos = {(int(n), int(d)): k
               for k, (n, d) in enumerate(zip(stiff.user_node, stiff.dof))}
        eps = 1e-3                                       # ux = eps*x
        u = np.zeros(len(stiff.gids))
        u[pos[(2, 1)]] = eps * L
        Kg, counts, _ = modal_buckling.assemble_geometric_stiffness(
            state, mesh, stiff, u)
        self.assertEqual(counts["shell_kg"], 1)
        # closed form: N = t*D*[eps,0,0], kg_w = A * G^T [N] G on the w DOFs
        c = E / (1.0 - nu * nu)
        nx, ny = t * c * eps, t * c * nu * eps           # Nxy = 0
        area = 0.5 * L * L
        G = np.array([[-1.0, 1.0, 0.0], [-1.0, 0.0, 1.0]]) / L
        kg_exp = area * (G.T @ np.array([[nx, 0.0], [0.0, ny]]) @ G)
        Kgd = Kg.toarray()
        wi = [pos[(nn, 3)] for nn in (1, 2, 3)]          # normal = +z -> TZ
        np.testing.assert_allclose(Kgd[np.ix_(wi, wi)], kg_exp, rtol=1e-12)
        Kgd[np.ix_(wi, wi)] = 0.0                        # nothing anywhere else
        self.assertEqual(np.abs(Kgd).max(), 0.0)

    def test_shell_kg_frame_invariance_under_rotation(self):
        # rotating the whole model (geometry + pre-solve displacements) must
        # leave the K_g energy of any (co-rotated) test vector unchanged.
        import numpy as np
        state, mesh, stiff, (L, t, E, nu) = self._cst_triangle()
        pos = {(int(n), int(d)): k
               for k, (n, d) in enumerate(zip(stiff.user_node, stiff.dof))}
        rng = np.random.default_rng(42)
        u = np.zeros(len(stiff.gids))
        for nn in (1, 2, 3):
            for d in (1, 2, 3):
                u[pos[(nn, d)]] = 1e-3 * rng.standard_normal()
        phi = rng.standard_normal(len(stiff.gids))
        Kg, _, _ = modal_buckling.assemble_geometric_stiffness(
            state, mesh, stiff, u)
        e_flat = float(phi @ (Kg @ phi))
        self.assertNotEqual(e_flat, 0.0)

        cx, sx = math.cos(0.5), math.sin(0.5)
        cy, sy = math.cos(0.4), math.sin(0.4)
        cz, sz = math.cos(0.3), math.sin(0.3)
        R = (np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
             @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
             @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]))
        state2, mesh2, stiff2, _ = self._cst_triangle()
        from k2rad.state import NodeData
        for nn in (1, 2, 3):
            p = state.nodes[nn]
            state2.nodes[nn] = NodeData(*(R @ np.array([p.x, p.y, p.z])))
        mesh2 = modal_common.build_mesh(state2)

        def rotate(vec):
            out = np.zeros_like(vec)
            for nn in (1, 2, 3):
                idx = [pos[(nn, d)] for d in (1, 2, 3)]
                out[idx] = R @ vec[idx]
            return out

        Kg2, _, _ = modal_buckling.assemble_geometric_stiffness(
            state2, mesh2, stiff2, rotate(u))
        phi2 = rotate(phi)
        e_rot = float(phi2 @ (Kg2 @ phi2))
        self.assertAlmostEqual(e_rot / e_flat, 1.0, delta=1e-9)


if __name__ == "__main__":
    unittest.main()
