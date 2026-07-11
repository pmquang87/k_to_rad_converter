"""Tests for the CONNECTOR conversions:

  *ELEMENT_DISCRETE + *SECTION_DISCRETE + *MAT_SPRING_ELASTIC /
  *MAT_SPRING_NONLINEAR_ELASTIC / *MAT_DAMPER_VISCOUS  → /PROP/TYPE4 + /SPRING
  *MAT_SPOTWELD (MAT_100) beam parts                   → /PROP/TYPE13 + /SPRING
  *CONSTRAINED_SPOTWELD / *CONSTRAINED_GENERALIZED_WELD_SPOT
      without failure → 2-node nodal rigid body (/RBODY)
      with failure    → stiff /PROP/TYPE13 + /SPRING (Ifail2=2 force criteria)

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_roadmap_keywords.py).
"""

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
    """Return the starter lines from the first line starting with
    *header_prefix* to the end of the file (caller indexes into it)."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(header_prefix):
            return lines[i:]
    raise AssertionError(f"{header_prefix!r} not found in starter")


# ── Discrete spring/damper decks ─────────────────────────────────────────────

SPRING_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "*PART\n"
    "spring part\n"
    "         1         1         1\n"
    "*SECTION_DISCRETE\n"
    "         1         0\n"
    "*MAT_SPRING_ELASTIC\n"
    "         1     250.0\n"
    "*ELEMENT_DISCRETE\n"
    "       1       1       1       2\n"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


class LinearSpringTests(unittest.TestCase):
    def test_handler_parses_element_section_material(self):
        state = _dispatch(SPRING_DECK)
        self.assertEqual(len(state.discrete_elems), 1)
        e = state.discrete_elems[0]
        self.assertEqual((e.eid, e.pid, e.n1, e.n2, e.vid), (1, 1, 1, 2, 0))
        self.assertEqual(e.s, 1.0)
        self.assertIn(1, state.sec_discrete)
        self.assertEqual(state.mat_spring_elastic[1].k, 250.0)

    def test_emits_prop_type4_part_and_spring(self):
        _, starter = _convert(SPRING_DECK)
        self.assertIn("/PROP/TYPE4/", starter)
        self.assertIn("/SPRING/1", starter)
        # The original DYNA section/material must NOT leak into the output as
        # a dangling /PROP or /MAT reference.
        self.assertNotIn("/PROP/SHELL/1\n", starter)
        # /SPRING element row: sprg_ID node_ID1 node_ID2 in 10-wide columns.
        self.assertIn("\n         1         1         2\n", starter)

    def test_type4_column_positions(self):
        _, starter = _convert(SPRING_DECK)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        # blk[0] header, [1] title, [2] MASS comment, [3] MASS card,
        # [4] K comment, [5] K/C/A/B/D card, [6] fct comment, [7] fct card.
        kcard = blk[5]
        self.assertEqual(kcard[0:20].strip(), "250")     # K
        self.assertEqual(kcard[20:40].strip(), "0")      # C
        fcard = blk[7]
        self.assertEqual(fcard[0:10].strip(), "0")       # fct_ID11 (linear)
        self.assertEqual(fcard[10:20].strip(), "0")      # H1
        # MASS card: sens_ID/Isflag/Ileng live in cols 51-80 (30-col gap).
        mcard = blk[3]
        self.assertEqual(mcard[20:50], " " * 30)


class GroundedSpringTests(unittest.TestCase):
    DECK = SPRING_DECK.replace(
        "       1       1       1       2\n",
        "       1       1       1       0\n")

    def test_ground_node_and_bcs(self):
        result, starter = _convert(self.DECK)
        # New ground node id = max node id + 1 = 3, at N1's coordinates.
        self.assertIn("\n         1         1         3\n", starter)
        self.assertIn("fix_discrete_ground_pid1", starter)
        self.assertIn("   111 111         0", starter)
        self.assertTrue(any("grounded" in w for w in result.warnings))

    def test_ground_node_coordinates_match_anchor(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        node_lines = [blk[i + 1] for i, ln in enumerate(blk) if ln == "/NODE"]
        self.assertEqual(len(node_lines), 1)
        self.assertEqual(node_lines[0][:10].strip(), "3")
        self.assertEqual(node_lines[0][10:30].strip(), "0")   # x of node 1
        self.assertEqual(node_lines[0][30:50].strip(), "0")   # y
        self.assertEqual(node_lines[0][50:70].strip(), "0")   # z


NONLIN_DECK = SPRING_DECK.replace(
    "*MAT_SPRING_ELASTIC\n         1     250.0\n",
    "*MAT_SPRING_NONLINEAR_ELASTIC\n         1         7\n"
    "*DEFINE_CURVE\n"
    "         7\n"
    "            -1.0          -500.0\n"
    "             0.0             0.0\n"
    "             1.0           500.0\n")


class NonlinearSpringTests(unittest.TestCase):
    def test_references_curve_and_initial_slope(self):
        _, starter = _convert(NONLIN_DECK)
        self.assertIn("/FUNCT/7", starter)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        kcard = blk[5]
        self.assertEqual(kcard[0:20].strip(), "500")     # K = initial slope
        fcard = blk[7]
        self.assertEqual(fcard[0:10].strip(), "7")       # fct_ID11 = LCD
        self.assertEqual(fcard[10:20].strip(), "0")      # H=0 nonlinear elastic

    def test_rate_curve_lcr_warns(self):
        deck = NONLIN_DECK.replace("         1         7\n",
                                   "         1         7         9\n")
        result, _ = _convert(deck)
        self.assertTrue(any("LCR" in w for w in result.warnings))


class DamperTests(unittest.TestCase):
    DECK = SPRING_DECK.replace(
        "*MAT_SPRING_ELASTIC\n         1     250.0\n",
        "*MAT_DAMPER_VISCOUS\n         1       1.5\n")

    def test_damping_c_field(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        kcard = blk[5]
        self.assertEqual(kcard[0:20].strip(), "0")       # K
        self.assertEqual(kcard[20:40].strip(), "1.5")    # C = DC


class OrientationAndTorsionalWarnTests(unittest.TestCase):
    def test_vid_element_warns_and_is_skipped(self):
        deck = SPRING_DECK.replace(
            "       1       1       1       2\n",
            "       1       1       1       2       4\n")
        result, starter = _convert(deck)
        self.assertTrue(any("DEFINE_SD_ORIENTATION" in w
                            for w in result.warnings))
        self.assertNotIn("\n         1         1         2\n", starter)
        self.assertNotIn("/SPRING/", starter)

    def test_torsional_dro1_warns_and_is_skipped(self):
        deck = SPRING_DECK.replace(
            "*SECTION_DISCRETE\n         1         0\n",
            "*SECTION_DISCRETE\n         1         1\n")
        result, starter = _convert(deck)
        self.assertTrue(any("torsional" in w for w in result.warnings))
        self.assertNotIn("/PROP/TYPE4/", starter)

    def test_failure_deflection_maps_to_deltamax(self):
        deck = SPRING_DECK.replace(
            "*SECTION_DISCRETE\n         1         0\n",
            "*SECTION_DISCRETE\n"
            "         1         0       0.0       0.0       0.0      0.02\n")
        _, starter = _convert(deck)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        fcard = blk[7]
        self.assertEqual(fcard[80:100].strip(), "0.02")  # DeltaMax = FD


# ── MAT_100 spotweld beam parts ──────────────────────────────────────────────

SPOTWELD_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             0.0             0.0             2.0\n"
    "*PART\n"
    "weld\n"
    "         5         3         9\n"
    "*SECTION_BEAM\n"
    "         3         2\n"
    "       4.0       1.2       1.2       2.4\n"
    "*MAT_SPOTWELD\n"
    "         9    7.8E-9  210000.0       0.3     300.0    1000.0\n"
    "       0.0    5000.0    3000.0    3000.0   40000.0   20000.0   20000.0\n"
    "*ELEMENT_BEAM\n"
    "       1       5       1       2\n"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


class SpotweldBeamTests(unittest.TestCase):
    def test_handler_parses_mat100(self):
        state = _dispatch(SPOTWELD_DECK)
        m = state.mat_spotweld[9]
        self.assertEqual(m.E, 210000.0)
        self.assertEqual(m.sigy, 300.0)
        self.assertEqual(m.nrr, 5000.0)
        self.assertEqual(m.mtt, 20000.0)

    def test_beam_part_becomes_type13_spring_connector(self):
        result, starter = _convert(SPOTWELD_DECK)
        self.assertIn("/PROP/TYPE13/", starter)
        self.assertIn("/SPRING/5", starter)
        self.assertNotIn("/BEAM/5", starter)
        # The spotweld-only *SECTION_BEAM must not leak as a /PROP/BEAM.
        self.assertNotIn("/PROP/BEAM/3", starter)
        # /SPRING row keeps eid/n1/n2 (+ n3 orientation column).
        self.assertIn("\n         1         1         2         0\n", starter)
        self.assertTrue(any("single-weld pull" in w for w in result.warnings))

    def test_type13_stiffness_and_failure_columns(self):
        _, starter = _convert(SPOTWELD_DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        # blk[0] header, [1] title, [2] card1 comment, [3] card1,
        # then per-DOF blocks of 6 lines starting at [4].
        card1 = blk[3]
        self.assertEqual(card1[70:80].strip(), "1")      # Ifail = 1 (multi-dir)
        self.assertEqual(card1[90:100].strip(), "2")     # Ifail2 = 2 (force)
        # Mass = rho*A*L = 7.8e-9 * 4 * 2
        self.assertAlmostEqual(float(card1[0:20]), 6.24e-8, places=12)
        # DOF1 (Tx): K card at [5], delta card at [7].
        k1card = blk[5]
        self.assertEqual(k1card[0:20].strip(), "420000")  # E*A/L = 210000*4/2
        d1card = blk[7]
        self.assertEqual(d1card[10:20].strip(), "1")      # H=1 elastic-plastic
        self.assertNotEqual(d1card[0:10].strip(), "0")    # bilinear fct_ID11
        self.assertEqual(d1card[60:80].strip(), "0")      # DeltaMin1 (default)
        self.assertEqual(d1card[80:100].strip(), "5000")  # DeltaMax1 = NRR
        # DOF2 (Ty shear): K = G*A/L = 80769.23*4/2, deltas = ±NRS.
        k2card = blk[11]
        self.assertAlmostEqual(float(k2card[0:20]), 161538.4615, places=3)
        d2card = blk[13]
        self.assertEqual(d2card[60:80].strip(), "-3000")
        self.assertEqual(d2card[80:100].strip(), "3000")
        # DOF4 (Rx torsion): deltas = ±MRR.
        d4card = blk[25]
        self.assertEqual(d4card[80:100].strip(), "40000")

    def test_bilinear_yield_function_emitted(self):
        result, starter = _convert(SPOTWELD_DECK)
        self.assertIn("spotweld_axial_bilinear_pid5", starter)
        self.assertTrue(any("SIGY" in w and "bilinear" in w
                            for w in result.warnings))

    def test_dropped_fields_warn(self):
        deck = SPOTWELD_DECK.replace(
            "         9    7.8E-9  210000.0       0.3     300.0    1000.0\n",
            "         9    7.8E-9  210000.0       0.3     300.0    1000.0"
            "   1.0E-06      0.01\n")
        result, _ = _convert(deck)
        self.assertTrue(any("DT" in w and "TFAIL" in w for w in result.warnings))

    def test_mat100_on_shell_part_falls_back_to_elast(self):
        deck = (
            "*KEYWORD\n"
            "*NODE\n"
            "       1             0.0             0.0             0.0\n"
            "       2             1.0             0.0             0.0\n"
            "       3             1.0             1.0             0.0\n"
            "       4             0.0             1.0             0.0\n"
            "*PART\n"
            "solidweld\n"
            "         1         1         9\n"
            "*SECTION_SHELL\n"
            "         1         2\n"
            "       1.0\n"
            "*MAT_SPOTWELD\n"
            "         9    7.8E-9  210000.0       0.3     300.0\n"
            "       0.0    5000.0\n"
            "*ELEMENT_SHELL\n"
            "       1       1       1       2       3       4\n"
            "*CONTROL_TERMINATION\n"
            "       1.0\n"
            "*END\n"
        )
        result, starter = _convert(deck)
        self.assertIn("/MAT/ELAST/9", starter)
        self.assertIn("(MAT_100 fallback)", starter)
        self.assertNotIn("/PROP/TYPE13/", starter)
        self.assertTrue(any("DROPPED" in w for w in result.warnings))


# ── CONSTRAINED_SPOTWELD ─────────────────────────────────────────────────────

TWO_SHEET_BASE = (
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
    "*PART\n"
    "sheetA\n"
    "         1         1         1\n"
    "*PART\n"
    "sheetB\n"
    "         2         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2\n"
    "       1.0\n"
    "*MAT_ELASTIC\n"
    "         1    7.8E-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       2       5       6       7       8\n"
    "{WELD}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


class ConstrainedSpotweldTests(unittest.TestCase):
    def test_no_failure_becomes_cnrb_tie(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}", "*CONSTRAINED_SPOTWELD\n         1         5\n")
        state = _dispatch(deck)
        self.assertEqual(len(state.cnrbs), 1)
        self.assertEqual(len(state.constrained_spotwelds), 0)
        result, starter = _convert(deck)
        self.assertEqual(starter.count("/RBODY/"), 1)
        self.assertTrue(any("nodal rigid body" in w for w in result.warnings))

    def test_failure_becomes_stiff_type13(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}",
            "*CONSTRAINED_SPOTWELD\n"
            "         1         5    4000.0    2500.0\n")
        state = _dispatch(deck)
        self.assertEqual(len(state.constrained_spotwelds), 1)
        self.assertEqual(state.constrained_spotwelds[0].sn, 4000.0)
        result, starter = _convert(deck)
        self.assertIn("/PROP/TYPE13/", starter)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        card1 = blk[3]
        self.assertEqual(card1[70:80].strip(), "1")       # Ifail
        self.assertEqual(card1[90:100].strip(), "2")      # Ifail2 force crit.
        d1card = blk[7]
        self.assertEqual(d1card[80:100].strip(), "4000")  # SN
        d2card = blk[13]
        self.assertEqual(d2card[60:80].strip(), "-2500")  # -SS
        self.assertEqual(d2card[80:100].strip(), "2500")  # SS
        self.assertTrue(any("APPROXIMATE" in w for w in result.warnings))

    def test_failure_time_and_ep_warn(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}",
            "*CONSTRAINED_SPOTWELD\n"
            "         1         5    4000.0    2500.0       2.0       2.0"
            "      0.05      0.10\n")
        result, _ = _convert(deck)
        self.assertTrue(any("TF=" in w for w in result.warnings))
        self.assertTrue(any("EP=" in w for w in result.warnings))

    def test_nonquadratic_exponents_warn(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}",
            "*CONSTRAINED_SPOTWELD\n"
            "         1         5    4000.0    2500.0       3.0       4.0\n")
        result, _ = _convert(deck)
        self.assertTrue(any("N=3" in w and "quadratic" in w
                            for w in result.warnings))

    def test_coincident_nodes_warn_and_skip(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}",
            "*CONSTRAINED_SPOTWELD\n"
            "         1         1    4000.0    2500.0\n")
        result, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE13/", starter)
        self.assertTrue(any("coincident" in w for w in result.warnings))


class GeneralizedWeldSpotTests(unittest.TestCase):
    def test_no_failure_ties_node_set_as_cnrb(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}",
            "*SET_NODE_LIST\n"
            "        10\n"
            "         1         5\n"
            "*CONSTRAINED_GENERALIZED_WELD_SPOT\n"
            "        10\n"
            "\n")
        state = _dispatch(deck)
        self.assertEqual(len(state.cnrbs), 1)
        self.assertEqual(state.cnrbs[0].nsid, 10)
        _, starter = _convert(deck)
        self.assertEqual(starter.count("/RBODY/"), 1)

    def test_failure_resolves_node_pair_to_type13(self):
        deck = TWO_SHEET_BASE.replace(
            "{WELD}",
            "*SET_NODE_LIST\n"
            "        10\n"
            "         1         5\n"
            "*CONSTRAINED_GENERALIZED_WELD_SPOT\n"
            "        10\n"
            "       0.0       0.0    4000.0    2500.0\n")
        result, starter = _convert(deck)
        self.assertIn("/PROP/TYPE13/", starter)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[7][80:100].strip(), "4000")


if __name__ == "__main__":
    unittest.main()
