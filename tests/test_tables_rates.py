"""Tests for *DEFINE_TABLE[_2D] → /TABLE/1 (Ndim=2) and the strain-rate
conversions built on it:

  * *DEFINE_TABLE_2D → a 2-D /TABLE/1 (dimension card = 2, rows sorted
    ascending by the 2nd-dimension abscissa A, SFA/OFFA applied).
  * Legacy *DEFINE_TABLE (bare VALUE rows) resolved positionally against the
    *DEFINE_CURVE blocks that follow it, or warned + skipped when impossible.
  * MAT_024 with LCSS pointing at a table → /MAT/LAW36 rate-function family.
  * *MAT_SIMPLIFIED_JOHNSON_COOK C != 0 → sampled rate-curve family with the
    (1 + C·ln(rate/EPSO)) scaling; C = 0 stays the single static curve.

Kept separate from tests/test_converter.py (helpers modeled on
tests/test_roadmap_keywords.py).
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
    """convert() a deck string; return (result, starter_text)."""
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
    """Parse + dispatch a deck string into a fresh ConversionState."""
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
    """Return the data lines (comments stripped) of the starter block whose
    first line starts with *header_prefix* — [title, data, data, ...]."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(header_prefix))
    out = [lines[i + 1]]                      # title line
    for ln in lines[i + 2:]:
        if ln.startswith("/"):
            break
        if ln.startswith("#") or not ln.strip():
            continue
        out.append(ln)
    return out


# A minimal solid deck; {MAT} and {EXTRA} are substituted per test.
BASE_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             0.0             1.0             0.0\n"
    "       4             0.0             0.0             1.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       4       4       4       4\n"
    "*PART\n"
    "solid\n"
    "         1         1         1\n"
    "*SECTION_SOLID\n"
    "         1        10\n"
    "{MAT}"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

MAT24_LCSS_TABLE = (
    "*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
    "         1   2.7e-9   72000.0       0.3     200.0\n"
    "       0.0       0.0       100\n"
)

# Three hardening curves at strain rates 0 / 1 / 10 (rows deliberately out of
# order to exercise the ascending-A sort).
TABLE_2D_AND_CURVES = (
    "*DEFINE_TABLE_2D\n"
    "       100       1.0\n"
    "                10.0                 203\n"
    "                 0.0                 201\n"
    "                 1.0                 202\n"
    "*DEFINE_CURVE\n"
    "       201\n"
    "0.0,200.0\n"
    "1.0,300.0\n"
    "*DEFINE_CURVE\n"
    "       202\n"
    "0.0,240.0\n"
    "1.0,360.0\n"
    "*DEFINE_CURVE\n"
    "       203\n"
    "0.0,280.0\n"
    "1.0,420.0\n"
)


class DefineTable2DTests(unittest.TestCase):
    def setUp(self):
        deck = BASE_DECK.format(MAT=MAT24_LCSS_TABLE, EXTRA=TABLE_2D_AND_CURVES)
        self.result, self.starter = _convert(deck)

    def test_handler_records_table(self):
        state = _dispatch(
            BASE_DECK.format(MAT=MAT24_LCSS_TABLE, EXTRA=TABLE_2D_AND_CURVES))
        self.assertIn(100, state.define_tables)
        tab = state.define_tables[100]
        self.assertTrue(tab.resolved)
        self.assertEqual(sorted(tab.rows), [(0.0, 201), (1.0, 202), (10.0, 203)])

    def test_table_emits_dimension_2(self):
        d = _block_lines(self.starter, "/TABLE/1/100")
        # d: title, dimension card, 3 rows
        self.assertEqual(d[1].strip(), "2")
        self.assertEqual(len(d), 5)

    def test_table_rows_sorted_with_cfg_columns(self):
        d = _block_lines(self.starter, "/TABLE/1/100")
        rows = d[2:]
        # cfg row: fct_ID(10) blank(10) A(20) blank(40) Scale_y(20)
        fcts = [int(r[0:10]) for r in rows]
        avals = [float(r[20:40]) for r in rows]
        scales = [float(r[80:100]) for r in rows]
        self.assertEqual(fcts, [201, 202, 203])
        self.assertEqual(avals, [0.0, 1.0, 10.0])
        self.assertEqual(scales, [1.0, 1.0, 1.0])
        # blank spacer columns really are blank
        for r in rows:
            self.assertEqual(r[10:20].strip(), "")
            self.assertEqual(r[40:80].strip(), "")

    def test_sfa_offa_scale_the_second_dimension(self):
        extra = TABLE_2D_AND_CURVES.replace(
            "       100       1.0\n",
            "       100       2.0       0.5\n")   # A = 2.0 * (VALUE + 0.5)
        _, starter = _convert(BASE_DECK.format(MAT=MAT24_LCSS_TABLE, EXTRA=extra))
        d = _block_lines(starter, "/TABLE/1/100")
        avals = [float(r[20:40]) for r in d[2:]]
        self.assertEqual(avals, [1.0, 3.0, 21.0])

    def test_referenced_curves_still_emit_as_funct(self):
        for lcid in (201, 202, 203):
            self.assertIn(f"/FUNCT/{lcid}", self.starter)

    def test_mat24_lcss_table_becomes_rate_family(self):
        d = _block_lines(self.starter, "/MAT/LAW36/1")
        # d: title, rho, E/nu/eps, Nfunct card, fctIDp card, funcIDs, Fscales,
        #    Eps_dots
        self.assertEqual(len(d), 8)
        self.assertEqual(d[3][0:10].strip(), "3")          # N_funct = 3
        self.assertEqual(
            [int(d[5][i:i + 10]) for i in range(0, 30, 10)], [201, 202, 203])
        eps_dots = [float(d[7][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(eps_dots, [0.0, 1.0, 10.0])
        fscales = [float(d[6][i:i + 20]) for i in range(0, 60, 20)]
        self.assertEqual(fscales, [1.0, 1.0, 1.0])
        self.assertTrue(any("rate-function family" in w
                            for w in self.result.warnings))

    def test_missing_curve_row_dropped_with_warning(self):
        extra = TABLE_2D_AND_CURVES.replace(
            "                 1.0                 202\n",
            "                 1.0                 999\n")
        result, starter = _convert(
            BASE_DECK.format(MAT=MAT24_LCSS_TABLE, EXTRA=extra))
        d = _block_lines(starter, "/TABLE/1/100")
        self.assertEqual(len(d), 4)                        # 2 surviving rows
        self.assertTrue(any("999" in w and "undefined" in w
                            for w in result.warnings))


class LegacyDefineTableTests(unittest.TestCase):
    LEGACY = (
        "*DEFINE_TABLE\n"
        "       300\n"
        "                 0.0\n"
        "                50.0\n"
        "*DEFINE_CURVE\n"
        "       301\n"
        "0.0,200.0\n"
        "1.0,300.0\n"
        "*DEFINE_CURVE\n"
        "       302\n"
        "0.0,260.0\n"
        "1.0,390.0\n"
    )
    MAT = MAT24_LCSS_TABLE.replace("       100", "       300")

    def test_positional_resolution_pairs_following_curves(self):
        result, starter = _convert(BASE_DECK.format(MAT=self.MAT,
                                                    EXTRA=self.LEGACY))
        d = _block_lines(starter, "/TABLE/1/300")
        self.assertEqual(d[1].strip(), "2")
        self.assertEqual([int(r[0:10]) for r in d[2:]], [301, 302])
        self.assertEqual([float(r[20:40]) for r in d[2:]], [0.0, 50.0])
        self.assertTrue(any("resolved" in w and "positionally" in w
                            for w in result.warnings))
        # And the material consumed it as a rate family.
        m = _block_lines(starter, "/MAT/LAW36/1")
        self.assertEqual(m[3][0:10].strip(), "2")          # N_funct = 2

    def test_unresolvable_legacy_table_warns_and_skips(self):
        # Two values but only ONE curve after the table → cannot pair.
        legacy = self.LEGACY.replace(
            "*DEFINE_CURVE\n       302\n0.0,260.0\n1.0,390.0\n", "")
        result, starter = _convert(BASE_DECK.format(MAT=self.MAT,
                                                    EXTRA=legacy))
        self.assertNotIn("/TABLE/1/300", starter)
        self.assertTrue(any("tbid=300" in w and "skipped" in w
                            for w in result.warnings))
        # The material fell back to bilinear hardening (single curve) and said so.
        self.assertTrue(any("could not be resolved" in w
                            for w in result.warnings))
        m = _block_lines(starter, "/MAT/LAW36/1")
        self.assertEqual(m[3][0:10].strip(), "1")          # N_funct = 1

    def test_curves_before_table_are_not_consumed(self):
        # The two curves precede the table → nothing follows it → skip.
        legacy = (
            "*DEFINE_CURVE\n       301\n0.0,200.0\n1.0,300.0\n"
            "*DEFINE_CURVE\n       302\n0.0,260.0\n1.0,390.0\n"
            "*DEFINE_TABLE\n"
            "       300\n"
            "                 0.0\n"
            "                50.0\n"
        )
        result, starter = _convert(BASE_DECK.format(MAT=self.MAT,
                                                    EXTRA=legacy))
        self.assertNotIn("/TABLE/1/300", starter)
        self.assertTrue(any("tbid=300" in w for w in result.warnings))


JC_RATE_MAT = (
    "*MAT_SIMPLIFIED_JOHNSON_COOK\n"
    "         1   7.8e-9  210000.0       0.3\n"
    "     350.0     275.0      0.36     0.022\n"
)

JC_STATIC_MAT = (
    "*MAT_SIMPLIFIED_JOHNSON_COOK\n"
    "         1   7.8e-9  210000.0       0.3\n"
    "     350.0     275.0      0.36\n"
)


class SimplifiedJohnsonCookRateTests(unittest.TestCase):
    def setUp(self):
        self.result, self.starter = _convert(
            BASE_DECK.format(MAT=JC_RATE_MAT, EXTRA=""))

    def test_rate_family_size_and_eps_dots(self):
        d = _block_lines(self.starter, "/MAT/LAW36/1")
        # d: title, rho, E-card, Nfunct card, fctIDp card, funcIDs, Fscales,
        #    Eps_dots (5 rates fit one CELL_LIST line each)
        self.assertEqual(d[3][0:10].strip(), "5")          # N_funct = 5
        eps_dots = [float(d[7][i:i + 20]) for i in range(0, 100, 20)]
        self.assertEqual(eps_dots, [1.0, 10.0, 100.0, 1000.0, 10000.0])
        fids = [int(d[5][i:i + 10]) for i in range(0, 50, 10)]
        self.assertEqual(len(set(fids)), 5)                # 5 distinct curves

    def test_ln_scaling_applied_to_sampled_curves(self):
        # At eps_p = 1.0 the quasi-static stress is A + B = 625.0; at rate 100
        # the curve must carry 625 * (1 + 0.022 * ln(100 / 1.0)).
        lines = self.starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip() == "Auto_JC_mid1_rate100")
        last = None
        for ln in lines[i + 1:]:
            if ln.startswith("/") or ln.startswith("#---1"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            last = ln
        self.assertIsNotNone(last)
        self.assertAlmostEqual(float(last[0:20]), 1.0)
        expected = 625.0 * (1.0 + 0.022 * math.log(100.0))
        self.assertAlmostEqual(float(last[20:40]), expected, places=6)

    def test_base_rate_curve_is_unscaled(self):
        lines = self.starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip() == "Auto_JC_mid1_rate1")
        last = None
        for ln in lines[i + 1:]:
            if ln.startswith("/") or ln.startswith("#---1"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            last = ln
        self.assertAlmostEqual(float(last[20:40]), 625.0, places=6)

    def test_informational_note_replaces_drop_warning(self):
        w = " ".join(self.result.warnings)
        self.assertIn("rate-function family", w)
        self.assertNotIn("dropped", w.lower())
        self.assertNotIn("rate-independent", w)

    def test_vp_flag_lands_in_law36_vp_column(self):
        mat = JC_RATE_MAT.replace(
            "   7.8e-9  210000.0       0.3\n",
            "   7.8e-9  210000.0       0.3         1\n")
        _, starter = _convert(BASE_DECK.format(MAT=mat, EXTRA=""))
        d = _block_lines(starter, "/MAT/LAW36/1")
        nf = d[3]
        self.assertEqual(nf[0:10].strip(), "5")
        self.assertEqual(len(nf), 100)
        self.assertEqual(nf[90:100].strip(), "1")          # VP at cols 91-100
        self.assertEqual(nf[20:90].strip(), "")            # C_hard/F_cut/Eps_f blank

    def test_c_zero_keeps_single_static_curve(self):
        result, starter = _convert(BASE_DECK.format(MAT=JC_STATIC_MAT, EXTRA=""))
        d = _block_lines(starter, "/MAT/LAW36/1")
        # Single-curve layout: title, rho, E-card, Nfunct/Fsmooth, fctIDp/Fscale,
        # fctID1, Fscale1, Epsdot1 — exactly 8 lines, N_funct=1, Eps_dot=0.
        self.assertEqual(len(d), 8)
        self.assertEqual(d[3].rstrip(), "         1         0")
        self.assertEqual(d[7].strip(), "0")                # Eps_dot_1 = static
        self.assertEqual(starter.count("Auto_JC_"), 0)
        self.assertFalse(any("rate-function family" in w for w in result.warnings))


class Epso_DefaultTests(unittest.TestCase):
    def test_explicit_epso_shifts_reference_rate(self):
        # EPSO = 10: rates 1 is skipped (≤ EPSO); family = 10, 100, 1000, 10000.
        mat = (
            "*MAT_SIMPLIFIED_JOHNSON_COOK\n"
            "         1   7.8e-9  210000.0       0.3\n"
            "     350.0     275.0      0.36     0.022       0.0       0.0       0.0      10.0\n"
        )
        _, starter = _convert(BASE_DECK.format(MAT=mat, EXTRA=""))
        d = _block_lines(starter, "/MAT/LAW36/1")
        self.assertEqual(d[3][0:10].strip(), "4")
        eps_dots = [float(d[7][i:i + 20]) for i in range(0, 80, 20)]
        self.assertEqual(eps_dots, [10.0, 100.0, 1000.0, 10000.0])


if __name__ == "__main__":
    unittest.main()
