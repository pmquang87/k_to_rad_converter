"""Tests for *MAT_ANISOTROPIC_VISCOPLASTIC (MAT_103) → /MAT/LAW128
(HILL_VISC_PLAST) plus the companion orthotropic property.

LAW128 is the near 1:1 OpenRadioss counterpart of MAT_103: same Voce (QR/CR) +
kinematic (QX/CX) hardening, a Cowper-Symonds rate term (into which VK/VM are
approximated) and the Hill surface from shell Lankford R00/R45/R90 or brick
F/G/H/L/M/N. Because every Radioss Hill law is orthotropic-only, a converted
part is repointed at a synthesized /PROP/TYPE9 (shell) or /PROP/TYPE6 (solid).

Helpers modeled on tests/test_tables_rates.py.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState


def _convert(deck: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _dispatch(deck: str) -> ConversionState:
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _block_lines(starter: str, header_prefix: str):
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(header_prefix))
    out = [lines[i + 1]]                          # title line
    for ln in lines[i + 2:]:
        if ln.startswith("/"):
            break
        if ln.startswith("#") or not ln.strip():
            continue
        out.append(ln)
    return out


# Single-brick solid deck; {MAT} substituted per test.
SOLID_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             0.0             0.0             1.0\n"
    "       6             1.0             0.0             1.0\n"
    "       7             1.0             1.0             1.0\n"
    "       8             0.0             1.0             1.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "*PART\n"
    "solid\n"
    "         1         1         1\n"
    "*SECTION_SOLID\n"
    "         1         1\n"
    "{MAT}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

# Single-quad shell deck.
SHELL_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "*PART\n"
    "shell\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2         0         3\n"
    "       0.5       0.5       0.5       0.5\n"
    "{MAT}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

# Shell-Lankford, no kinematic, no viscosity, mild anisotropy (Iglidur-like).
MAT_LANKFORD = (
    "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
    "         1   1.05E-9    1800.0       0.4      35.0       0.0       0.0       1.0\n"
    "      10.0      50.0       5.0     300.0       0.0       0.0       0.0       0.0\n"
    "       0.0       0.0      1.35       1.0      0.75       0.0       0.0       0.0\n"
    "       0.0       0.1\n"
)


# /MAT/LAW128 block line indices (index 0 is the title line):
_RHO, _EC, _TAB, _QR, _QX, _EPSP, _R, _FGH, _LMN = 1, 2, 3, 4, 5, 6, 7, 8, 9


def _law128(starter):
    """All lines of the /MAT/LAW128 block: [title, rho, E-card, tab-card, QR, QX,
    EPSP0/CP, R00, F/G/H, L/M/N]."""
    return _block_lines(starter, "/MAT/LAW128/1")


class Law128BasicTests(unittest.TestCase):
    def setUp(self):
        self.state = _dispatch(SOLID_DECK.format(MAT=MAT_LANKFORD))
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=MAT_LANKFORD))

    def test_handler_stores_aniso_visco(self):
        m = self.state.mat_aniso_visco[1]
        self.assertAlmostEqual(m.E, 1800.0)
        self.assertAlmostEqual(m.nu, 0.4)
        self.assertAlmostEqual(m.sigy, 35.0)
        self.assertAlmostEqual(m.qr1, 10.0)
        self.assertAlmostEqual(m.cr1, 50.0)
        self.assertAlmostEqual(m.qr2, 5.0)
        self.assertAlmostEqual(m.cr2, 300.0)
        self.assertAlmostEqual(m.r00, 1.35)
        self.assertAlmostEqual(m.r90, 0.75)
        self.assertAlmostEqual(m.fail, 0.1)

    def test_emits_law128_not_law36(self):
        self.assertIn("/MAT/LAW128/1", self.starter)
        self.assertNotIn("/MAT/LAW36/1", self.starter)

    def test_law128_card_values(self):
        d = _law128(self.starter)
        e_card = [float(d[_EC][i:i + 20]) for i in range(0, 80, 20)]
        self.assertEqual(e_card, [1800.0, 0.4, 35.0, 0.0])   # CHARD=0 (no kin)
        qr = [float(d[_QR][i:i + 20]) for i in range(0, 80, 20)]
        self.assertEqual(qr, [10.0, 50.0, 5.0, 300.0])

    def test_lankford_mode_sets_r_values_and_unit_lmn(self):
        d = _law128(self.starter)
        r = [float(d[_R][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(r, [1.35, 1.0, 0.75])
        fgh = [float(d[_FGH][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(fgh, [0.0, 0.0, 0.0])               # computed from Lankford
        lmn = [float(d[_LMN][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(lmn, [1.5, 1.5, 1.5])               # von Mises shear defaults

    def test_failure_emits_fail_johnson(self):
        self.assertIn("/FAIL/JOHNSON/1", self.starter)
        d = _block_lines(self.starter, "/FAIL/JOHNSON/1")
        self.assertAlmostEqual(float(d[1][0:20]), 0.1)       # D1 = FAIL

    def test_solid_part_repointed_at_ortho_prop(self):
        # /PART references the synthesized orthotropic prop id, not section 1.
        self.assertIn(1, self.state.parts)
        d = _block_lines(self.starter, "/PART/1")
        prop_ref = int(d[1][0:10])
        self.assertNotEqual(prop_ref, 1)
        self.assertIn(f"/PROP/TYPE6/{prop_ref}", self.starter)

    def test_isotropic_solid_prop_suppressed(self):
        # Section 1 is used only by the LAW128 part → no /PROP/SOLID/1.
        self.assertNotIn("/PROP/SOLID/1\n", self.starter)
        self.assertNotIn("/PROP/SOLID/1", self.starter)

    def test_ortho_prop_warning(self):
        self.assertTrue(any("orthotropic property" in w and "TYPE9" in w
                            for w in self.result.warnings))


class Law128ShellTests(unittest.TestCase):
    def test_shell_gets_type9(self):
        result, starter = _convert(SHELL_DECK.format(MAT=MAT_LANKFORD))
        d = _block_lines(starter, "/PART/1")
        prop_ref = int(d[1][0:10])
        self.assertIn(f"/PROP/TYPE9/{prop_ref}", starter)
        # thickness carried from *SECTION_SHELL (0.5)
        p = _block_lines(starter, f"/PROP/TYPE9/{prop_ref}")
        # p: [title, Ishell-card, Hm-card, N/ISTRAIN/Thick-card, Vx-card]
        thick_card = p[3]
        self.assertAlmostEqual(float(thick_card[20:40]), 0.5)


class Law128BrickHillTests(unittest.TestCase):
    """L/M/N given → brick Hill mode: F/G/H taken from the R00/R45/R90 slots and
    R00=R45=R90 zeroed so LAW128 uses the coefficients directly."""

    MAT_BRICK = (
        "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
        "         1   1.05E-9    1800.0       0.4      35.0       0.0       0.0       1.0\n"
        "      10.0      50.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
        "       0.0       0.0       0.6       0.4       0.5       1.4       1.6       1.7\n"
        "       0.0       0.0\n"
    )

    def test_brick_mode_uses_fgh_lmn(self):
        _, starter = _convert(SOLID_DECK.format(MAT=self.MAT_BRICK))
        d = _law128(starter)
        r = [float(d[_R][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(r, [0.0, 0.0, 0.0])                 # Lankford disabled
        fgh = [float(d[_FGH][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(fgh, [0.6, 0.4, 0.5])               # F/G/H from slots 3-5
        lmn = [float(d[_LMN][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(lmn, [1.4, 1.6, 1.7])               # L/M/N from slots 6-8


class Law128KinematicTests(unittest.TestCase):
    MAT_KIN = (
        "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
        "         1   1.05E-9    1800.0       0.4      35.0       0.0       0.0       1.0\n"
        "      30.0      50.0       0.0       0.0      10.0      40.0       0.0       0.0\n"
        "       0.0       0.0       1.0       1.0       1.0       0.0       0.0       0.0\n"
        "       0.0       0.0\n"
    )

    def test_chard_is_kinematic_fraction(self):
        result, starter = _convert(SOLID_DECK.format(MAT=self.MAT_KIN))
        d = _law128(starter)
        chard = float(d[_EC][60:80])
        # kinematic fraction = QX/(QR+QX) = 10 / (30+10) = 0.25
        self.assertAlmostEqual(chard, 0.25, places=6)
        # QX terms carried through verbatim
        qx = [float(d[_QX][i:i + 20]) for i in range(0, 80, 20)]
        self.assertEqual(qx, [10.0, 40.0, 0.0, 0.0])
        self.assertTrue(any("kinematic" in w.lower() and "CHARD" in w
                            for w in result.warnings))


class Law128FlagAlphaTests(unittest.TestCase):
    """FLAG=1 with a load curve → CHARD = 1 - ALPHA and tab_ID = LCSS."""

    MAT_FLAG1 = (
        "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
        "         1   1.05E-9    1800.0       0.4      35.0       1.0       500       0.7\n"
        "       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
        "       0.0       0.0       1.2       1.0       0.9       0.0       0.0       0.0\n"
        "       0.0       0.0\n"
        "*DEFINE_CURVE\n"
        "       500\n"
        "0.0,35.0\n"
        "1.0,60.0\n"
    )

    def test_chard_from_alpha_and_tab_id(self):
        _, starter = _convert(SOLID_DECK.format(MAT=self.MAT_FLAG1))
        d = _law128(starter)
        chard = float(d[_EC][60:80])
        self.assertAlmostEqual(chard, 1.0 - 0.7, places=6)   # 1 - ALPHA
        tab_id = int(d[_TAB][0:10])
        self.assertEqual(tab_id, 500)
        self.assertIn("/FUNCT/500", starter)


def _c(*vals):
    """Format LS-DYNA fixed 10-column fields (blank = '')."""
    return "".join(f"{v:>10}" for v in vals)


class Law128AxisMappingTests(unittest.TestCase):
    """MAT_103 AOPT axis definition → /PROP orthotropy reference direction."""

    HEAD = (
        "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
        + _c(1, "1.05E-9", 1800.0, 0.4, 35.0, 0.0, 0.0, 1.0) + "\n"
        + _c(10.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
        + _c(0.0, 0.0, 1.35, 1.0, 0.75, 0.0, 0.0, 0.0) + "\n"
    )

    def _type6_vx_card(self, starter):
        d = _block_lines(starter, "/PART/1")
        prop_ref = int(d[1][0:10])
        p = _block_lines(starter, f"/PROP/TYPE6/{prop_ref}")
        # p: [title, Isolid, qa/qb/h, Vx/Vy/Vz/skew/Ip/Iorth, Phi/Px/Py/Pz, card5]
        return p[3], p[4]

    def test_aopt2_global_vector_maps_to_vxyz(self):
        mat = (self.HEAD
               + _c(2.0, 0.0, 0.0, 0.0) + "\n"                 # card4: AOPT=2
               + _c("", "", "", 0.0, 0.0, 1.0) + "\n"          # card5: a = (0,0,1)
               + _c("", "", "", 1.0, 0.0, 0.0) + "\n")         # card6: d
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        vx_card, _ = self._type6_vx_card(starter)
        vxyz = [float(vx_card[i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(vxyz, [0.0, 0.0, 1.0])                # build direction z
        self.assertTrue(any("auto-mapped" in w and "AOPT=2" in w
                            for w in result.warnings))

    def test_aopt3_vector_and_beta(self):
        mat = (self.HEAD
               + _c(3.0, 0.0, 0.0, 0.0) + "\n"                 # card4: AOPT=3
               + _c("", "", "", 0.0, 0.0, 0.0) + "\n"          # card5 (unused)
               + _c(0.0, 1.0, 0.0, "", "", "", 30.0) + "\n")   # card6: v=(0,1,0) BETA=30
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        vx_card, phi_card = self._type6_vx_card(starter)
        vxyz = [float(vx_card[i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(vxyz, [0.0, 1.0, 0.0])
        self.assertAlmostEqual(float(phi_card[0:20]), 30.0)    # Phi = BETA
        self.assertTrue(any("AOPT=3" in w and "auto-mapped" in w
                            for w in result.warnings))

    def test_aopt0_falls_back_to_global_x(self):
        mat = (self.HEAD
               + _c(0.0, 0.0, 0.0, 0.0) + "\n")                # card4: AOPT=0 (nodes)
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        vx_card, _ = self._type6_vx_card(starter)
        vxyz = [float(vx_card[i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(vxyz, [1.0, 0.0, 0.0])                # default
        self.assertTrue(any("defaulted to GLOBAL X" in w for w in result.warnings))


class Law128ViscosityTests(unittest.TestCase):
    """VK/VM additive overstress → Cowper-Symonds EPSP0/CP matched at yield."""

    MAT_VISC = (
        "*MAT_ANISOTROPIC_VISCOPLASTIC\n"
        "         1   1.05E-9    1800.0       0.4      40.0       0.0       0.0       1.0\n"
        "      10.0      50.0       0.0       0.0       0.0       0.0       0.0       0.0\n"
        "       5.0       0.2       1.0       1.0       1.0       0.0       0.0       0.0\n"
        "       0.0       0.0\n"
    )

    def test_cowper_symonds_from_vk_vm(self):
        result, starter = _convert(SOLID_DECK.format(MAT=self.MAT_VISC))
        d = _law128(starter)
        epsp0, cp = float(d[_EPSP][0:20]), float(d[_EPSP][20:40])
        # CP = 1/VM = 5; EPSP0 = (SIGY/VK)^(1/VM) = (40/5)^5 = 32768
        self.assertAlmostEqual(cp, 5.0, places=6)
        self.assertAlmostEqual(epsp0, (40.0 / 5.0) ** 5.0, places=2)
        self.assertTrue(any("Cowper-Symonds" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
