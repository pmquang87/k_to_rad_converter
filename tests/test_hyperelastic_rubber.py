"""Tests for the hyperelastic rubber batch:

  * *MAT_BLATZ-KO_RUBBER (MAT_007) → /MAT/LAW42 fixed form (Mu_1 = G,
    alpha_1 = 2, Nu = 0.463), hyphen/underscore/numeric aliases.
  * *MAT_MOONEY-RIVLIN_RUBBER (MAT_027) → /MAT/LAW42 with the exact dyna2rad
    Ogden equivalences Mu_1 = 2A / Mu_2 = -2B / alpha = ±2, Nu = PR VERBATIM,
    and the 500-point funIDbulk curve (as-built dyna2rad formula, integer-
    division j^0 terms included) at the correct card columns (funIDbulk at
    51-60, phantom Jstrain 41-50 blank); LCID present → /MAT/LAW69 LAW_ID=2
    with the curve unscaled (SGL/SW/ST warned); missing curve → LAW42
    fallback; degenerate PR=0.5 / A=B=0 skip the curve with warnings.
  * *MAT_OGDEN_RUBBER (MAT_077_O): N=0 → LAW42 pairs 1:1 (Nu=|PR| + Mullins
    warning, I_form=2, BETAI>0 Prony embedded as Gamma=GI / Tau=1/BETAI,
    pairs 6-8 and BETAI<=0 terms warned), the two mandatory blank cards;
    N>0 → LAW69 (LAW_ID=int(DATA), N_PAIR=N, the 1/SGL / 1/(SW*ST) duplicate
    curve) with GI/BETAI and G/SIGF (/VISC/PLAS unreadable at /BEGIN 2022)
    warn-dropped.
  * *MAT_HYPERELASTIC_RUBBER (MAT_077_H): N=0 → LAW95 (Radioss column order
    C10 C01 C20 C11 C02, D1 = |2/K| from PR, zero Bergstrom-Boyce terms),
    PR<0 → D1=0 + Mullins warning, PR=0 → K=2G/3 warning; N>0 → LAW69; both
    branches emit /VISC/PRONY (no title line, Beta_i NOT inverted, 4-field
    rows); Gj/SIGFj and header G/SIGF warned.
  * *INITIAL_FOAM_REFERENCE_GEOMETRY[_RAMP] → /XREF per intersecting part
    (part-id header, ascending node rows at I10+3xF20, Nitrs from NDTRRG),
    REF=1 coverage warnings, REF flags never gating the /XREF emission.
  * *INCLUDE_TRANSFORM id offsets: MAT_077_O N>0 LCID1 offset, N=0 MU
    constants untouched, foam-reference node ids offset.
  * Alias + _TITLE dispatch and no-regression (existing materials unchanged,
    no stray /XREF//VISC blocks).

Helpers modeled on tests/test_johnson_cook.py.
"""

import math
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


def _raw_block(starter: str, header_prefix: str):
    """ALL lines of a block (comments and blank cards included) up to the
    next '/' header — for asserting the physical card layout."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(header_prefix))
    out = [lines[i]]
    for ln in lines[i + 1:]:
        if ln.startswith("/"):
            break
        out.append(ln)
    return out


def _floats(line: str, n: int):
    """The first n 20-wide float fields of a card line."""
    return [float(line[i:i + 20]) for i in range(0, 20 * n, 20)]


def _funct_points(starter: str, fid: int):
    return [tuple(_floats(ln, 2)) for ln in _block_lines(starter, f"/FUNCT/{fid}")[1:]]


def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


# Single-hex solid deck; {MAT} substituted per test (materials + curves +
# reference geometry all ride this slot).
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
    "rubber\n"
    "         1         1         1\n"
    "*SECTION_SOLID\n"
    "         1         1\n"
    "{MAT}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

BLATZ_KO = (
    "*MAT_BLATZ-KO_RUBBER\n"
    + _row(1, "1.1E-9", 104.0) + "\n"
)

# A=0.7 (C10), B=0.3 (C01), PR=0.495 — the constants branch.
MOONEY_CONST = (
    "*MAT_MOONEY-RIVLIN_RUBBER\n"
    + _row(1, "1.1E-9", 0.495, 0.7, 0.3) + "\n"
)

# Curve branch: A=B blank, LCID=88 with a parsed *DEFINE_CURVE.
MOONEY_CURVE = (
    "*MAT_MOONEY-RIVLIN_RUBBER\n"
    + _row(1, "1.1E-9", 0.49) + "\n"
    + _row("", "", "", 88) + "\n"
    "*DEFINE_CURVE\n"
    + _row(88) + "\n"
    "                 0.0                 0.0\n"
    "                 0.5                12.0\n"
)

# N=0 direct pairs + two Prony cards (the second has BETAI=0 → dropped).
OGDEN_DIRECT = (
    "*MAT_OGDEN_RUBBER\n"
    + _row(1, "1.1E-9", -0.495, 0, 2) + "\n"
    + _row(1.6, -0.4) + "\n"
    + _row(2.5, -2.5) + "\n"
    + _row(0.05, 10.0) + "\n"
    + _row(0.03, 0.0) + "\n"
)

# N=3 fit path: SGL=10 SW=5 ST=2, LCID1=77 (curve carries its own SFA/OFFA),
# DATA=1 (Ogden fit), plus a GI/BETAI card that must be warn-dropped.
OGDEN_FIT = (
    "*MAT_OGDEN_RUBBER\n"
    + _row(1, "1.1E-9", 0.495, 3, 0, 0.0, 0.0) + "\n"
    + _row(10.0, 5.0, 2.0, 77, 1.0) + "\n"
    + _row(0.05, 10.0) + "\n"
    "*DEFINE_CURVE\n"
    + _row(77, "", 2.0, 3.0) + "\n"
    "                 0.0                 0.0\n"
    "                 1.0               100.0\n"
)

# N=0 polynomial + one 4-column viscoelastic card (Gi BETAi Gj SIGFj).
HYPER_DIRECT = (
    "*MAT_HYPERELASTIC_RUBBER\n"
    + _row(1, "1.1E-9", 0.499, 0, 1) + "\n"
    + _row(0.7, 0.3, 0.01, 0.02, 0.03, 0.04) + "\n"
    + _row(0.05, 5.0) + "\n"
)

REF_GEOM = (
    "*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.1             0.0             0.0\n"
    "       3             1.1             1.1             0.0\n"
    "       4             0.0             1.1             0.0\n"
    "       9           400.0             0.0             0.0\n"
)


class Mat007BlatzKoTests(unittest.TestCase):
    def setUp(self):
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=BLATZ_KO))

    def test_law42_fixed_form(self):
        d = _block_lines(self.starter, "/MAT/LAW42/1")
        self.assertAlmostEqual(_floats(d[1], 1)[0], 1.1e-9)          # RHO_I
        nu_card = d[2]
        self.assertEqual(_floats(nu_card, 2), [0.463, 0.0])          # Nu, sigma_cut
        self.assertEqual(nu_card[40:50], " " * 10)                   # phantom Jstrain
        self.assertEqual(int(nu_card[50:60]), 0)                     # no funIDbulk
        self.assertEqual(int(nu_card[80:90]), 0)                     # M = 0
        self.assertEqual(int(nu_card[90:100]), 0)                    # I_form → starter 1
        self.assertEqual(_floats(d[3], 5), [104.0, 0.0, 0.0, 0.0, 0.0])   # Mu_1 = G
        self.assertEqual(_floats(d[4], 5), [2.0, 0.0, 0.0, 0.0, 0.0])     # alpha_1 = 2
        self.assertNotIn("/VISC/PRONY/1", self.starter)

    def test_mandatory_blank_cards_present(self):
        raw = _raw_block(self.starter, "/MAT/LAW42/1")
        # header title #RHO rho #Nu nu #Mu mu #blank BLANK #alpha alpha #blank BLANK
        self.assertEqual(raw[9], "")
        self.assertTrue(raw[8].startswith("#"))
        self.assertEqual(raw[13], "")
        self.assertTrue(raw[12].startswith("#"))

    def test_no_warnings_for_plain_card(self):
        self.assertFalse([w for w in self.result.warnings if "BLATZ" in w])


class Mat027ConstantsTests(unittest.TestCase):
    A, B, PR = 0.7, 0.3, 0.495

    def setUp(self):
        self.state = _dispatch(SOLID_DECK.format(MAT=MOONEY_CONST))
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=MOONEY_CONST))

    def test_handler_stores_fields(self):
        m = self.state.mat_mooney_rivlin[1]
        self.assertAlmostEqual(m.rho, 1.1e-9)
        self.assertAlmostEqual(m.pr, 0.495)
        self.assertAlmostEqual(m.a, 0.7)
        self.assertAlmostEqual(m.b, 0.3)
        self.assertEqual(m.lcid, 0)

    def test_law42_ogden_equivalents(self):
        d = _block_lines(self.starter, "/MAT/LAW42/1")
        self.assertEqual(_floats(d[2], 1), [0.495])                  # Nu = PR verbatim
        self.assertEqual(_floats(d[3], 5), [1.4, -0.6, 0.0, 0.0, 0.0])   # 2A, -2B
        self.assertEqual(_floats(d[4], 5), [2.0, -2.0, 0.0, 0.0, 0.0])
        self.assertNotIn("/MAT/LAW69/1", self.starter)

    def test_funidbulk_at_columns_51_60(self):
        nu_card = _block_lines(self.starter, "/MAT/LAW42/1")[2]
        self.assertEqual(nu_card[40:50], " " * 10)                   # phantom slot
        fid = int(nu_card[50:60])
        self.assertGreater(fid, 0)
        self.assertIn(f"/FUNCT/{fid}", self.starter)

    def test_bulk_curve_reproduces_dyna2rad_formula(self):
        fid = int(_block_lines(self.starter, "/MAT/LAW42/1")[2][50:60])
        pts = _funct_points(self.starter, fid)
        self.assertEqual(len(pts), 500)
        self.assertAlmostEqual(pts[0][0], 0.01)
        self.assertAlmostEqual(pts[-1][0], 5.0, places=6)
        # Independent recomputation of the as-built dyna2rad value at j=0.01:
        # the pow(j,(-1/3)) / pow(j,(1/3)) terms are C++ INTEGER divisions
        # (exponent 0 → 1.0), so fbulk = (2A(1-j^-5)+4B(1-j^-5)+4Dj(j²-1))/(K(j-1)).
        a, b, pr = self.A, self.B, self.PR
        k = 2.0 * (2.0 * (a + b)) * (1.0 + pr) / (3.0 * (1.0 - 2.0 * pr))
        dcst = (a * (5.0 * pr - 2.0) + b * (11.0 * pr - 5.0)) / (2.0 * (1.0 - 2.0 * pr))
        j = 0.01
        expect = (2.0 * a * (1.0 - j ** -5) + 4.0 * b * (1.0 - j ** -5)
                  + 4.0 * dcst * j * (j * j - 1.0)) / (k * (j - 1.0))
        self.assertAlmostEqual(pts[0][1], expect, delta=abs(expect) * 1e-6)
        # the j≈1 point survives via float round-off — every value finite
        self.assertTrue(all(math.isfinite(y) for _, y in pts))

    def test_negative_pr_written_verbatim_no_mullins_warning(self):
        # dyna2rad MAT_027 copies PR with no abs() and no warning 28.
        mat = MOONEY_CONST.replace("     0.495", "    -0.495")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        d = _block_lines(starter, "/MAT/LAW42/1")
        self.assertEqual(_floats(d[2], 1), [-0.495])
        self.assertFalse([w for w in result.warnings if "Mullins" in w])

    def test_pr_half_skips_curve_with_warning(self):
        mat = MOONEY_CONST.replace("     0.495", "       0.5")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        nu_card = _block_lines(starter, "/MAT/LAW42/1")[2]
        self.assertEqual(int(nu_card[50:60]), 0)
        self.assertTrue(any("PR=0.5" in w for w in result.warnings))

    def test_zero_a_b_skips_curve_with_error_828_warning(self):
        mat = ("*MAT_MOONEY-RIVLIN_RUBBER\n"
               + _row(1, "1.1E-9", 0.495) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertEqual(int(_block_lines(starter, "/MAT/LAW42/1")[2][50:60]), 0)
        self.assertTrue(any("828" in w for w in result.warnings))


class Mat027CurveTests(unittest.TestCase):
    def setUp(self):
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=MOONEY_CURVE))

    def test_law69_mooney_fit(self):
        d = _block_lines(self.starter, "/MAT/LAW69/1")
        self.assertAlmostEqual(_floats(d[1], 1)[0], 1.1e-9)          # RHO_I
        card = d[2]
        self.assertEqual(int(card[0:10]), 2)                         # LAW_ID = 2
        self.assertEqual(int(card[10:20]), 0)                        # bulk FCT_ID
        self.assertEqual(float(card[20:40]), 0.49)                   # NU verbatim
        self.assertEqual(float(card[40:60]), 0.0)                    # FSCALE → 1.0
        self.assertEqual(int(card[60:70]), 0)                        # N_PAIR → 2
        self.assertEqual(int(card[70:80]), 0)                        # ICHECK → -3
        self.assertEqual(int(d[3][0:10]), 88)                        # FCT_ID1 = LCID
        self.assertNotIn("/MAT/LAW42/1", self.starter)

    def test_curve_not_duplicated_or_scaled(self):
        # dyna2rad applies NO SGL/SW/ST normalization on the MAT_027 path.
        self.assertNotIn("_Duplicate", self.starter)
        pts = _funct_points(self.starter, 88)
        self.assertEqual(pts, [(0.0, 0.0), (0.5, 12.0)])

    def test_nontrivial_sgl_sw_st_warned(self):
        mat = MOONEY_CURVE.replace(
            _row("", "", "", 88), _row(10.0, 5.0, 2.0, 88))
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertEqual(int(_block_lines(starter, "/MAT/LAW69/1")[3][0:10]), 88)
        self.assertNotIn("_Duplicate", starter)
        self.assertTrue(any("SGL=10" in w and "unscaled" in w
                            for w in result.warnings))

    def test_missing_curve_falls_back_to_law42(self):
        mat = ("*MAT_MOONEY-RIVLIN_RUBBER\n"
               + _row(1, "1.1E-9", 0.49, 0.7, 0.3) + "\n"
               + _row("", "", "", 99) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertIn("/MAT/LAW42/1", starter)
        self.assertNotIn("/MAT/LAW69/1", starter)
        self.assertTrue(any("LCID=99" in w for w in result.warnings))


class Mat077OgdenDirectTests(unittest.TestCase):
    def setUp(self):
        self.state = _dispatch(SOLID_DECK.format(MAT=OGDEN_DIRECT))
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=OGDEN_DIRECT))

    def test_handler_stores_pairs_and_prony(self):
        m = self.state.mat_ogden[1]
        self.assertEqual(m.n, 0)
        self.assertEqual(m.mu[:2], [1.6, -0.4])
        self.assertEqual(m.alpha[:2], [2.5, -2.5])
        self.assertEqual(m.gi, [0.05, 0.03])
        self.assertEqual(m.betai, [10.0, 0.0])

    def test_law42_pairs_abs_pr_iform2(self):
        d = _block_lines(self.starter, "/MAT/LAW42/1")
        nu_card = d[2]
        self.assertEqual(_floats(nu_card, 2), [0.495, 0.0])          # Nu = |PR|
        self.assertEqual(int(nu_card[80:90]), 1)                     # M (BETAI>0 only)
        self.assertEqual(int(nu_card[90:100]), 2)                    # I_form = 2
        self.assertEqual(_floats(d[3], 5), [1.6, -0.4, 0.0, 0.0, 0.0])
        self.assertEqual(_floats(d[4], 5), [2.5, -2.5, 0.0, 0.0, 0.0])

    def test_embedded_prony_gamma_and_inverted_tau(self):
        d = _block_lines(self.starter, "/MAT/LAW42/1")
        self.assertEqual(_floats(d[5], 1), [0.05])                   # Gamma_1 = GI
        self.assertEqual(_floats(d[6], 1), [0.1])                    # Tau_1 = 1/BETAI
        self.assertNotIn("/VISC/PRONY/1", self.starter)              # embedded, not aux

    def test_mullins_and_dropped_beta_warned(self):
        self.assertTrue(any("Mullins" in w for w in self.result.warnings))
        self.assertTrue(any("BETAI <= 0" in w for w in self.result.warnings))

    def test_pairs_6_to_8_dropped_with_warning(self):
        mat = ("*MAT_OGDEN_RUBBER\n"
               + _row(1, "1.1E-9", 0.495, 0) + "\n"
               + _row(*[f"{0.1 * i:.1f}" for i in range(1, 9)]) + "\n"
               + _row(*[f"{float(i)}" for i in range(1, 9)]) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        d = _block_lines(starter, "/MAT/LAW42/1")
        self.assertEqual(_floats(d[3], 5), [0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertEqual(_floats(d[4], 5), [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertTrue(any("pairs 6-8" in w and "5 mu/alpha slots" in w
                            for w in result.warnings))


class Mat077OgdenFitTests(unittest.TestCase):
    def setUp(self):
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=OGDEN_FIT))

    def test_law69_data_npair(self):
        d = _block_lines(self.starter, "/MAT/LAW69/1")
        card = d[2]
        self.assertEqual(int(card[0:10]), 1)                         # LAW_ID = DATA
        self.assertEqual(float(card[20:40]), 0.495)                  # NU = |PR|
        self.assertEqual(int(card[60:70]), 3)                        # N_PAIR = N

    def test_duplicate_curve_specimen_normalization(self):
        # curve 77 parse-applies SFA=2/SFO=3 → (0,0),(2,300); the duplicate
        # multiplies by SFA=1/SGL=0.1 and SFO=1/(SW*ST)=0.1 → (0.2, 30).
        fid = int(_block_lines(self.starter, "/MAT/LAW69/1")[3][0:10])
        self.assertNotEqual(fid, 77)
        self.assertEqual(_funct_points(self.starter, fid),
                         [(0.0, 0.0), (0.2, 30.0)])
        self.assertEqual(_funct_points(self.starter, 77),
                         [(0.0, 0.0), (2.0, 300.0)])                 # original kept
        self.assertTrue(any("_Duplicate" in ln for ln in
                            self.starter.splitlines()))

    def test_gi_betai_dropped_on_fit_path(self):
        self.assertTrue(any("GI/BETAI" in w and "LAW69" in w
                            for w in self.result.warnings))
        self.assertNotIn("/VISC/PRONY/1", self.starter)

    def test_unit_scales_reuse_original_curve(self):
        mat = OGDEN_FIT.replace(_row(10.0, 5.0, 2.0, 77, 1.0),
                                _row(1.0, 1.0, 1.0, 77, 2.0))
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        d = _block_lines(starter, "/MAT/LAW69/1")
        self.assertEqual(int(d[2][0:10]), 2)                         # LAW_ID = 2
        self.assertEqual(int(d[3][0:10]), 77)                        # no duplicate
        self.assertNotIn("_Duplicate", starter)

    def test_blank_st_guard_warned(self):
        mat = OGDEN_FIT.replace(_row(10.0, 5.0, 2.0, 77, 1.0),
                                _row(10.0, 5.0, "", 77, 1.0))
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        # ST treated as 1.0: SFO = 1/(5*1) = 0.2 (dyna2rad would emit inf)
        fid = int(_block_lines(starter, "/MAT/LAW69/1")[3][0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 0.0), (0.2, 60.0)])
        self.assertTrue(any("ST is blank" in w for w in result.warnings))

    def test_g_sigf_damping_dropped_with_warning(self):
        mat = OGDEN_FIT.replace(_row(1, "1.1E-9", 0.495, 3, 0, 0.0, 0.0),
                                _row(1, "1.1E-9", 0.495, 3, 0, 0.5, 2.0))
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertNotIn("/VISC/PLAS", starter)
        self.assertTrue(any("G=0.5" in w and "SIGF=2" in w
                            for w in result.warnings))

    def test_invalid_data_warns_error_882(self):
        # dyna2rad writes LAW_ID = int(DATA) blindly; the starter accepts only
        # -1/1/2 (0 → -1 automatic). DATA=3 must be flagged as ERROR 882.
        mat = OGDEN_FIT.replace(_row(10.0, 5.0, 2.0, 77, 1.0),
                                _row(10.0, 5.0, 2.0, 77, 3.0))
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertEqual(int(_block_lines(starter, "/MAT/LAW69/1")[2][0:10]), 3)
        self.assertTrue(any("882" in w for w in result.warnings))

    def test_lcid2_relaxation_fit_warned(self):
        mat = OGDEN_FIT.replace(_row(10.0, 5.0, 2.0, 77, 1.0),
                                _row(10.0, 5.0, 2.0, 77, 1.0, 42))
        result, _ = _convert(SOLID_DECK.format(MAT=mat))
        self.assertTrue(any("LCID2=42" in w for w in result.warnings))

    def test_missing_lcid1_warns_error_894(self):
        mat = ("*MAT_OGDEN_RUBBER\n"
               + _row(1, "1.1E-9", 0.495, 2) + "\n"
               + _row(1.0, 1.0, 1.0) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertEqual(int(_block_lines(starter, "/MAT/LAW69/1")[3][0:10]), 0)
        self.assertTrue(any("894" in w for w in result.warnings))


class Mat077HyperelasticTests(unittest.TestCase):
    def setUp(self):
        self.state = _dispatch(SOLID_DECK.format(MAT=HYPER_DIRECT))
        self.result, self.starter = _convert(SOLID_DECK.format(MAT=HYPER_DIRECT))

    def test_handler_stores_polynomial_and_prony(self):
        m = self.state.mat_hyper_rubber[1]
        self.assertEqual((m.c10, m.c01, m.c11, m.c20, m.c02, m.c30),
                         (0.7, 0.3, 0.01, 0.02, 0.03, 0.04))
        self.assertEqual(m.gi, [0.05])
        self.assertEqual(m.betai, [5.0])

    def test_law95_field_map_radioss_column_order(self):
        d = _block_lines(self.starter, "/MAT/LAW95/1")
        self.assertAlmostEqual(_floats(d[1], 1)[0], 1.1e-9)
        # Radioss order C10 C01 C20 C11 C02 (C20/C11 swapped vs the LS-DYNA card)
        self.assertEqual(_floats(d[2], 5), [0.7, 0.3, 0.02, 0.01, 0.03])
        self.assertEqual(_floats(d[3], 5), [0.04, 0.0, 0.0, 0.0, 0.0])   # C30..Sb
        # D1 = |2/K|, K = 2G(1+PR)/3/(1-2PR), G = 2(C10+C01)
        g2 = 2.0 * (0.7 + 0.3)
        k = 2.0 * g2 * (1.0 + 0.499) / 3.0 / (1.0 - 2.0 * 0.499)
        self.assertAlmostEqual(_floats(d[4], 3)[0], abs(2.0 / k), places=12)
        self.assertEqual(_floats(d[4], 3)[1:], [0.0, 0.0])               # D2 D3
        self.assertEqual(_floats(d[5], 5), [0.0] * 5)                    # A C M KSI TAU
        self.assertNotIn("/MAT/LAW69/1", self.starter)

    def test_visc_prony_block(self):
        raw = _raw_block(self.starter, "/VISC/PRONY/1")
        # No title line: the M-card comment follows the header directly.
        self.assertTrue(raw[1].startswith("#"))
        m_card = raw[2]
        self.assertEqual(int(m_card[0:10]), 1)                       # M
        self.assertEqual(m_card[10:20], " " * 10)                    # literal gap
        self.assertEqual(float(m_card[20:40]), 0.0)                  # K_v
        self.assertEqual(int(m_card[40:50]), 0)                      # Itab
        self.assertEqual(int(m_card[50:60]), 0)                      # Ishape
        row = raw[4]
        # Beta_i is the LS-DYNA decay constant DIRECTLY (no 1/BETA inversion)
        self.assertEqual(_floats(row, 4), [0.05, 5.0, 0.0, 0.0])
        self.assertEqual(self.starter.count("/VISC/PRONY/1"), 1)

    def test_pr_negative_mullins_d1_zero(self):
        mat = HYPER_DIRECT.replace("     0.499", "    -0.499")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        d = _block_lines(starter, "/MAT/LAW95/1")
        self.assertEqual(_floats(d[4], 3), [0.0, 0.0, 0.0])          # D1 stays 0
        self.assertTrue(any("Mullins" in w for w in result.warnings))

    def test_pr_blank_warns_zero_poisson(self):
        mat = HYPER_DIRECT.replace("     0.499", "          ")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        d = _block_lines(starter, "/MAT/LAW95/1")
        # dyna2rad exact behavior: K = 2G/3 = 4/3 → D1 = 1.5
        self.assertAlmostEqual(_floats(d[4], 3)[0], 1.5, places=12)
        self.assertTrue(any("PR is blank/0" in w for w in result.warnings))

    def test_n_positive_law69_with_prony(self):
        mat = ("*MAT_HYPERELASTIC_RUBBER\n"
               + _row(1, "1.1E-9", 0.495, 2, 1) + "\n"
               + _row(1.0, 1.0, 1.0, 77, 2.0) + "\n"
               + _row(0.05, 5.0) + "\n"
               "*DEFINE_CURVE\n"
               + _row(77) + "\n"
               "                 0.0                 0.0\n"
               "                 1.0               100.0\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        d = _block_lines(starter, "/MAT/LAW69/1")
        self.assertEqual(int(d[2][0:10]), 2)                         # LAW_ID = DATA
        self.assertEqual(int(d[2][60:70]), 2)                        # N_PAIR = N
        self.assertEqual(int(d[3][0:10]), 77)
        self.assertIn("/VISC/PRONY/1", starter)                      # both branches
        self.assertNotIn("/MAT/LAW95/1", starter)

    def test_header_g_sigf_and_gj_sigfj_warned(self):
        mat = ("*MAT_HYPERELASTIC_RUBBER\n"
               + _row(1, "1.1E-9", 0.499, 0, 1, 0.5, 2.0) + "\n"
               + _row(0.7, 0.3) + "\n"
               + _row(0.05, 5.0, 0.01, 3.0) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertNotIn("/VISC/PLAS", starter)
        self.assertTrue(any("header G=0.5" in w for w in result.warnings))
        self.assertTrue(any("Gj/SIGFj" in w for w in result.warnings))
        # Gi/BETAi still convert
        raw = _raw_block(starter, "/VISC/PRONY/1")
        self.assertEqual(_floats(raw[4], 4), [0.05, 5.0, 0.0, 0.0])


class XrefTests(unittest.TestCase):
    def test_xref_block_from_reference_geometry(self):
        _, starter = _convert(SOLID_DECK.format(MAT=BLATZ_KO + REF_GEOM))
        raw = _raw_block(starter, "/XREF/1")
        self.assertEqual(raw[0], "/XREF/1")
        self.assertEqual(raw[1], "XREF_PART_1")
        self.assertEqual(int(raw[3][0:10]), 0)                       # Nitrs
        rows = [ln for ln in raw[4:] if ln.strip() and not ln.startswith("#")]
        self.assertEqual(len(rows), 4)                               # node 9 excluded
        self.assertEqual(int(rows[0][0:10]), 1)
        self.assertEqual(int(rows[3][0:10]), 4)                      # ascending ids
        self.assertEqual(_floats(rows[1][10:], 3), [1.1, 0.0, 0.0])  # I10 + 3xF20

    def test_ramp_variant_sets_nitrs(self):
        ramp = REF_GEOM.replace(
            "*INITIAL_FOAM_REFERENCE_GEOMETRY\n",
            "*INITIAL_FOAM_REFERENCE_GEOMETRY_RAMP\n" + _row(25) + "\n")
        _, starter = _convert(SOLID_DECK.format(MAT=BLATZ_KO + ramp))
        raw = _raw_block(starter, "/XREF/1")
        self.assertEqual(int(raw[3][0:10]), 25)

    def test_xref_emitted_regardless_of_ref_flag(self):
        # dyna2rad converts the keyword unconditionally — REF=0 still gets /XREF.
        _, starter = _convert(SOLID_DECK.format(MAT=MOONEY_CONST + REF_GEOM))
        self.assertIn("/XREF/1", starter)

    def test_ref_flag_without_keyword_warns(self):
        mat = ("*MAT_BLATZ-KO_RUBBER\n"
               + _row(1, "1.1E-9", 104.0, 1.0) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertNotIn("/XREF/", starter)
        self.assertTrue(any("REF=1" in w and "INITIAL_FOAM_REFERENCE_GEOMETRY" in w
                            for w in result.warnings))

    def test_ref_flag_with_coverage_no_warning(self):
        mat = ("*MAT_BLATZ-KO_RUBBER\n"
               + _row(1, "1.1E-9", 104.0, 1.0) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat + REF_GEOM))
        self.assertIn("/XREF/1", starter)
        self.assertFalse([w for w in result.warnings if "REF=1" in w])

    def test_uncovered_ref_material_warns(self):
        # Reference geometry exists but touches none of the material's nodes.
        geom = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
                "      77           400.0             0.0             0.0\n")
        mat = ("*MAT_BLATZ-KO_RUBBER\n"
               + _row(1, "1.1E-9", 104.0, 1.0) + "\n")
        result, starter = _convert(SOLID_DECK.format(MAT=mat + geom))
        self.assertNotIn("/XREF/", starter)
        self.assertTrue(any("covers no node" in w for w in result.warnings))

    def test_xref_solid_section_switches_to_ismstr_10(self):
        # Starter ERROR 2013: /XREF on an 8-point solid needs Ismstr>=10.
        _, starter = _convert(SOLID_DECK.format(MAT=BLATZ_KO + REF_GEOM))
        prop = _block_lines(starter, "/PROP/SOLID/1")
        self.assertEqual(int(prop[1][10:20]), 10)                    # Ismstr
        self.assertEqual(int(prop[1][0:10]), 17)                     # Isolid kept
        # ... and without reference geometry the property is untouched.
        _, starter2 = _convert(SOLID_DECK.format(MAT=BLATZ_KO))
        self.assertEqual(int(_block_lines(starter2, "/PROP/SOLID/1")[1][10:20]), 0)

    def test_law95_solid_part_xref_skipped_error_2014_guard(self):
        # The starter's solid-/XREF law whitelist is 1/35/38/42/70/88/90 —
        # LAW95 (and LAW69) parts must not get a /XREF (ERROR 2014). The
        # section still gets Ismstr=10, but through the LAW95 rule (below),
        # not through /XREF.
        result, starter = _convert(SOLID_DECK.format(MAT=HYPER_DIRECT + REF_GEOM))
        self.assertNotIn("/XREF/", starter)
        self.assertTrue(any("whitelist" in w and "2014" in w
                            for w in result.warnings))

    def test_law95_solid_section_ismstr_10_without_xref(self):
        # The starter force-promotes LAW95 properties ("ISMSTR IS CHANGED TO
        # 10 SINCE LAW 95 IS ONLY COMPATIBLE WITH ISMSTR=10", WARNING 1200) —
        # k2rad pre-sets it for a warning-clean deck with the identical
        # formulation.
        _, starter = _convert(SOLID_DECK.format(MAT=HYPER_DIRECT))
        prop = _block_lines(starter, "/PROP/SOLID/1")
        self.assertEqual(int(prop[1][10:20]), 10)                    # Ismstr
        self.assertEqual(int(prop[1][0:10]), 17)                     # Isolid kept
        # ... but the N>0 (LAW69) routing keeps the default formulation.
        law69 = ("*MAT_HYPERELASTIC_RUBBER\n"
                 + _row(1, "1.1E-9", 0.495, 2, 0) + "\n"
                 + _row(1.0, 1.0, 1.0, 77, 2.0) + "\n"
                 "*DEFINE_CURVE\n"
                 + _row(77) + "\n"
                 "                 0.0                 0.0\n"
                 "                 1.0               100.0\n")
        _, starter2 = _convert(SOLID_DECK.format(MAT=law69))
        self.assertEqual(int(_block_lines(starter2, "/PROP/SOLID/1")[1][10:20]), 0)

    def test_mooney_curve_branch_xref_skipped(self):
        # MAT_027 with LCID routes to LAW69 → its part loses the /XREF too.
        result, starter = _convert(SOLID_DECK.format(MAT=MOONEY_CURVE + REF_GEOM))
        self.assertIn("/MAT/LAW69/1", starter)
        self.assertNotIn("/XREF/", starter)
        self.assertTrue(any("LAW69" in w and "2014" in w
                            for w in result.warnings))


class IncludeOffsetTests(unittest.TestCase):
    def _assembled(self, child: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write(child)
        main = os.path.join(tmp.name, "main.k")
        with open(main, "w") as fh:
            fh.write("\n".join([
                "*KEYWORD",
                "*INCLUDE_TRANSFORM",
                "child.k",
                # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF
                _row(100, 0, 0, 20, 0, 50),
                "", "", "",
                "*END",
            ]) + "\n")
        state = ConversionState()
        for block in parse_k_file(main):
            dispatch(block, state)
        return state

    def test_ogden_fit_lcid1_offset(self):
        child = ("*KEYWORD\n" + OGDEN_FIT + "*END\n")
        st = self._assembled(child)
        m = st.mat_ogden[21]                                         # mid + IDMOFF
        self.assertEqual(m.lcid1, 127)                               # 77 + IDFOFF
        self.assertIn(127, st.curves)

    def test_ogden_direct_constants_not_corrupted(self):
        child = ("*KEYWORD\n" + OGDEN_DIRECT + "*END\n")
        st = self._assembled(child)
        m = st.mat_ogden[21]
        self.assertEqual(m.mu[:2], [1.6, -0.4])                      # MU4/MU6 safe
        self.assertEqual(m.alpha[:2], [2.5, -2.5])
        self.assertEqual(m.gi, [0.05, 0.03])

    def test_mooney_lcid_offset(self):
        child = ("*KEYWORD\n" + MOONEY_CURVE + "*END\n")
        st = self._assembled(child)
        self.assertEqual(st.mat_mooney_rivlin[21].lcid, 138)         # 88 + IDFOFF
        self.assertIn(138, st.curves)

    def test_foam_ref_geometry_node_ids_offset(self):
        child = ("*KEYWORD\n" + REF_GEOM + "*END\n")
        st = self._assembled(child)
        self.assertEqual(sorted(st.foam_ref_geoms[0].nodes),
                         [101, 102, 103, 104, 109])
        self.assertEqual(st.foam_ref_geoms[0].nodes[102], (1.1, 0.0, 0.0))


class AliasDispatchTests(unittest.TestCase):
    def _mat_reaches(self, deck_mat: str, container: str):
        state = _dispatch(SOLID_DECK.format(MAT=deck_mat))
        self.assertIn(1, getattr(state, container))
        self.assertFalse(state.skipped_keywords)

    def test_blatz_ko_aliases(self):
        for kw in ("MAT_BLATZ-KO_RUBBER", "MAT_BLATZ_KO_RUBBER",
                   "MAT_007", "MAT_7"):
            self._mat_reaches(BLATZ_KO.replace("MAT_BLATZ-KO_RUBBER", kw),
                              "mat_blatz_ko")

    def test_mooney_aliases(self):
        for kw in ("MAT_MOONEY-RIVLIN_RUBBER", "MAT_MOONEY_RIVLIN_RUBBER",
                   "MAT_027", "MAT_27"):
            self._mat_reaches(MOONEY_CONST.replace("MAT_MOONEY-RIVLIN_RUBBER", kw),
                              "mat_mooney_rivlin")

    def test_ogden_aliases(self):
        for kw in ("MAT_OGDEN_RUBBER", "MAT_077_O", "MAT_77_O"):
            self._mat_reaches(OGDEN_DIRECT.replace("MAT_OGDEN_RUBBER", kw),
                              "mat_ogden")

    def test_hyperelastic_aliases(self):
        for kw in ("MAT_HYPERELASTIC_RUBBER", "MAT_077_H", "MAT_77_H"):
            self._mat_reaches(HYPER_DIRECT.replace("MAT_HYPERELASTIC_RUBBER", kw),
                              "mat_hyper_rubber")

    def test_title_option_dispatch(self):
        mat = MOONEY_CONST.replace("*MAT_MOONEY-RIVLIN_RUBBER\n",
                                   "*MAT_MOONEY-RIVLIN_RUBBER_TITLE\nsoft seal\n")
        state = _dispatch(SOLID_DECK.format(MAT=mat))
        self.assertEqual(state.mat_mooney_rivlin[1].title, "soft seal")
        _, starter = _convert(SOLID_DECK.format(MAT=mat))
        self.assertIn("soft seal", starter)


class NoRegressionTests(unittest.TestCase):
    ELASTIC = ("*MAT_ELASTIC\n"
               + _row(1, "7.85E-9", 210000.0, 0.3) + "\n")

    def test_elastic_block_byte_identical(self):
        _, starter = _convert(SOLID_DECK.format(MAT=self.ELASTIC))
        i = starter.find("/MAT/ELAST/1")
        block = "\n".join(starter[i:].splitlines()[:7])
        self.assertEqual(block, "\n".join([
            "/MAT/ELAST/1",
            "MAT_1",
            "#              RHO_I",
            "        7.850000E-09",
            "#                  E                  nu",
            "              210000                 0.3",
            "#---1----|----2----|----3----|----4----|----5----|----6----|"
            "----7----|----8----|----9----|---10----|",
        ]))

    def test_non_rubber_deck_has_no_rubber_blocks(self):
        result, starter = _convert(SOLID_DECK.format(MAT=self.ELASTIC))
        for token in ("/XREF/", "/VISC/PRONY", "/MAT/LAW42", "/MAT/LAW69",
                      "/MAT/LAW95"):
            self.assertNotIn(token, starter)
        self.assertFalse([w for w in result.warnings if "RUBBER" in w])

    def test_rubber_deck_emits_no_fail_or_eos(self):
        _, starter = _convert(SOLID_DECK.format(MAT=OGDEN_DIRECT))
        self.assertNotIn("/FAIL/", starter)
        self.assertNotIn("/EOS/", starter)


if __name__ == "__main__":
    unittest.main()
