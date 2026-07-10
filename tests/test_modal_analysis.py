"""Unit tests for the Tier-4 offline analysis extensions that ride the modal
K-export chain::

    python -m unittest tests.test_modal_analysis -v

Covers the two new tools under ``tools/``:

* ``modal_frf.py``      – harmonic / frequency-response output; validated against
  the closed-form single-DOF FRF (dynamic-amplification peak = 1/(2ζ) and
  half-power bandwidth Δf = 2ζ·f_n) and against the reused
  ``modal_random_response.frf_matrix`` kernel;
* ``modal_buckling.py`` – linear (eigenvalue) buckling; validated against the
  analytic Euler pin-pinned column  P_cr = π²·E·I/L².

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
            d = np.load(out)
            p_cr = d["buckling_factors"][0] * P
            self.assertAlmostEqual(p_cr / col.euler_pcr(), 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
