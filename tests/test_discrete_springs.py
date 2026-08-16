"""Tests for the DISCRETE-SPRING batch:

  *MAT_SPRING_ELASTOPLASTIC (S03) / _GENERAL_NONLINEAR (S06) / _INELASTIC (S08)
  *MAT_DAMPER_NONLINEAR_VISCOUS (S05)      -> /PROP/TYPE4 function slots
  *SECTION_DISCRETE DRO=1 (torsional)      -> /PROP/TYPE13 or /PROP/TYPE8 DOF 4
  *SECTION_BEAM ELFORM=6 discrete beams    -> /PROP/TYPE8 (skew oriented) or
      /PROP/TYPE13 (node oriented) + /SPRING, for *MAT_066/067/068/071/074/
      119/121/196; *MAT_069/070/093/094/095/097/146 warn-drop to an inert
      connector.

Kept in its own module (same policy as tests/test_connectors.py, which covers
the S01/S04/D01 + MAT_100 paths this batch extends).
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState
from k2rad.writer import loads as wloads
from k2rad.writer import dbeam as wdbeam
from k2rad.writer.mesh import _target_mat_law


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
    for i, ln in enumerate(lines):
        if ln.startswith(header_prefix):
            return lines[i:]
    raise AssertionError(f"{header_prefix!r} not found in starter")


def _funct_points(starter: str, fid: int):
    """The (X, Y) pairs of /FUNCT/<fid>, read from the 20-wide columns."""
    blk = _block_lines(starter, f"/FUNCT/{fid}\n".rstrip())
    pts = []
    for ln in blk[3:]:
        if ln.startswith("#") or ln.startswith("/"):
            break
        pts.append((float(ln[0:20]), float(ln[20:40])))
    return pts


# ── *ELEMENT_DISCRETE + *SECTION_DISCRETE decks ──────────────────────────────

def _spring_deck(mat: str, section: str = "         1         0\n",
                 extra: str = "") -> str:
    return (
        "*KEYWORD\n"
        "*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2             1.0             0.0             0.0\n"
        "*PART\n"
        "spring part\n"
        "         1         1         1\n"
        "*SECTION_DISCRETE\n" + section
        + mat + extra
        + "*ELEMENT_DISCRETE\n"
        "       1       1       1       2\n"
        "*CONTROL_TERMINATION\n"
        "       1.0\n"
        "*END\n"
    )


CURVE_50 = ("*DEFINE_CURVE\n"
            "        50\n"
            "             0.0             0.0\n"
            "             1.0           100.0\n"
            "             2.0           150.0\n")
CURVE_51 = ("*DEFINE_CURVE\n"
            "        51\n"
            "            -1.0          -400.0\n"
            "             0.0             0.0\n"
            "             1.0           400.0\n")


class MatS03Tests(unittest.TestCase):
    """*MAT_SPRING_ELASTOPLASTIC: K=1000, KT=200, FY=50 ->
    yield displacement FY/K = 0.05, so the 5 points are
      (-1.05, -250) (-0.05, -50) (0, 0) (0.05, 50) (1.05, 250)
    with K1 = K = 1000 and H1 = 1 (isotropic hardening)."""

    DECK = _spring_deck("*MAT_SPRING_ELASTOPLASTIC\n"
                        "         1    1000.0     200.0      50.0\n")

    def test_handler_parses_card(self):
        st = _dispatch(self.DECK)
        m = st.mat_spring_elastoplastic[1]
        self.assertEqual((m.k, m.kt, m.fy), (1000.0, 200.0, 50.0))

    def test_title_variant_dispatches(self):
        deck = self.DECK.replace(
            "*MAT_SPRING_ELASTOPLASTIC\n",
            "*MAT_SPRING_ELASTOPLASTIC_TITLE\nelastoplastic spring\n")
        st = _dispatch(deck)
        self.assertIn(1, st.mat_spring_elastoplastic)

    def test_numeric_alias_dispatches(self):
        deck = self.DECK.replace("*MAT_SPRING_ELASTOPLASTIC\n", "*MAT_S03\n")
        st = _dispatch(deck)
        self.assertIn(1, st.mat_spring_elastoplastic)

    def test_curve_points_and_type4_columns(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        self.assertEqual(blk[5][0:20].strip(), "1000")   # K1 = K
        fcard = blk[7]
        fid = int(fcard[0:10])
        self.assertEqual(fcard[10:20].strip(), "1")      # H1 = 1
        self.assertEqual(
            _funct_points(starter, fid),
            [(-1.05, -250.0), (-0.05, -50.0), (0.0, 0.0),
             (0.05, 50.0), (1.05, 250.0)])

    def test_zero_stiffness_is_warn_skipped(self):
        deck = _spring_deck("*MAT_SPRING_ELASTOPLASTIC\n"
                            "         1       0.0     200.0      50.0\n")
        result, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE4/", starter)
        self.assertTrue(any("MAT_SPRING_ELASTOPLASTIC" in w
                            and "NOT converted" in w for w in result.warnings))


class MatS05Tests(unittest.TestCase):
    """*MAT_DAMPER_NONLINEAR_VISCOUS: LCDR is the force-vs-rate function, which
    is the fct_ID41 (h(rate)) slot — NOT the fct_ID11 displacement slot."""

    DECK = _spring_deck("*MAT_DAMPER_NONLINEAR_VISCOUS\n"
                        "         1        50\n", extra=CURVE_50)

    def test_lcdr_lands_on_fct_id41(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        fcard = blk[7]
        self.assertEqual(fcard[0:10].strip(), "0")     # fct_ID11 (no f(d))
        self.assertEqual(fcard[20:30].strip(), "0")    # fct_ID21
        self.assertEqual(fcard[30:40].strip(), "0")    # fct_ID31
        self.assertEqual(fcard[40:50].strip(), "50")   # fct_ID41 = LCDR
        # K and C stay 0: the whole force comes from h(rate).
        self.assertEqual(blk[5][0:20].strip(), "0")
        self.assertEqual(blk[5][20:40].strip(), "0")

    def test_missing_curve_warn_skips(self):
        deck = _spring_deck("*MAT_DAMPER_NONLINEAR_VISCOUS\n"
                            "         1        99\n", extra=CURVE_50)
        result, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE4/", starter)
        self.assertTrue(any("LCDR=99" in w for w in result.warnings))


class MatS06Tests(unittest.TestCase):
    """*MAT_SPRING_GENERAL_NONLINEAR: LCDL -> fct_ID11, LCDU -> fct_ID31,
    H1 = 6 (isotropic hardening with nonlinear unloading)."""

    DECK = _spring_deck("*MAT_SPRING_GENERAL_NONLINEAR\n"
                        "         1        50        51       1.0      10.0"
                        "     -10.0\n", extra=CURVE_50 + CURVE_51)

    def test_handler_parses_all_six_fields(self):
        st = _dispatch(self.DECK)
        m = st.mat_spring_general_nl[1]
        self.assertEqual((m.lcdl, m.lcdu, m.beta, m.tyi, m.cyi),
                         (50, 51, 1.0, 10.0, -10.0))

    def test_loading_unloading_slots_and_hflag(self):
        _, starter = _convert(self.DECK)
        fcard = _block_lines(starter, "/PROP/TYPE4/")[7]
        self.assertEqual(fcard[0:10].strip(), "50")    # fct_ID11 = LCDL
        self.assertEqual(fcard[10:20].strip(), "6")    # H1 = 6
        self.assertEqual(fcard[30:40].strip(), "51")   # fct_ID31 = LCDU

    def test_beta_tyi_cyi_are_named_in_the_warning(self):
        result, _ = _convert(self.DECK)
        self.assertTrue(any("BETA, TYI, CYI" in w for w in result.warnings))

    def test_missing_unloading_curve_demotes_h_to_zero(self):
        """H=6 with fct_ID31 = 0 is starter ERROR 1057 — the deck would not
        start, so the flag must be demoted, not written."""
        deck = _spring_deck("*MAT_SPRING_GENERAL_NONLINEAR\n"
                            "         1        50\n", extra=CURVE_50)
        result, starter = _convert(deck)
        fcard = _block_lines(starter, "/PROP/TYPE4/")[7]
        self.assertEqual(fcard[10:20].strip(), "0")
        self.assertTrue(any("1057" in w for w in result.warnings))


class MatS08Tests(unittest.TestCase):
    """*MAT_SPRING_INELASTIC: LCFD is positive-quadrant only and CTF picks the
    active side; the curve must be mirrored or Radioss invents force on the
    inactive side by extrapolating the end segment."""

    def _deck(self, ctf: str) -> str:
        return _spring_deck(
            "*MAT_SPRING_INELASTIC\n"
            f"         1        50     800.0{ctf}\n", extra=CURVE_50)

    def test_compression_only_default_mirrors_into_third_quadrant(self):
        # CTF blank -> +1.0 = compression only: reflect through the origin and
        # close off with a flat zero-force point one unit into tension.
        _, starter = self._convert_and_return("")
        fcard = _block_lines(starter, "/PROP/TYPE4/")[7]
        fid = int(fcard[0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-2.0, -150.0), (-1.0, -100.0), (0.0, 0.0),
                          (1.0, 0.0)])

    def test_tension_only_keeps_branch_and_zeroes_compression(self):
        _, starter = self._convert_and_return("      -1.0")
        fcard = _block_lines(starter, "/PROP/TYPE4/")[7]
        fid = int(fcard[0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-1.0, 0.0), (0.0, 0.0), (1.0, 100.0), (2.0, 150.0)])

    def test_ku_becomes_k1_with_hflag_one(self):
        """LS-DYNA unloads along max(KU, max loading slope) — Radioss H=1
        unloads along K1, so KU belongs there AND the flag must be set.
        dyna2rad leaves H at 0, which makes the spring elastic."""
        _, starter = self._convert_and_return("")
        blk = _block_lines(starter, "/PROP/TYPE4/")
        self.assertEqual(blk[5][0:20].strip(), "800")   # K1 = KU
        self.assertEqual(blk[7][10:20].strip(), "1")    # H1 = 1

    def test_blank_ku_demotes_to_elastic_and_warns(self):
        deck = _spring_deck("*MAT_SPRING_INELASTIC\n"
                            "         1        50\n", extra=CURVE_50)
        result, starter = _convert(deck)
        self.assertEqual(_block_lines(starter, "/PROP/TYPE4/")[7][10:20].strip(),
                         "0")
        self.assertTrue(any("dissipates NO" in w for w in result.warnings))

    def _convert_and_return(self, ctf: str):
        return _convert(self._deck(ctf))


class SectionDiscreteFieldTests(unittest.TestCase):
    def test_kd_v0_and_cl_warn_separately_and_name_the_loss(self):
        deck = _spring_deck(
            "*MAT_SPRING_ELASTIC\n         1     250.0\n",
            section="         1         0       2.5       1.0       0.7\n")
        result, _ = _convert(deck)
        self.assertTrue(any("KD=2.5" in w and "V0=1" in w
                            for w in result.warnings))
        self.assertTrue(any("CL=0.7" in w and "COMPRESSION-ONLY" in w
                            for w in result.warnings))


class TorsionalDro1Tests(unittest.TestCase):
    """DRO=1 is a MOMENT-per-radian spring. /PROP/TYPE4 is purely
    translational, so the payload goes to slot 4 (Rx) of a 6-DOF property —
    /PROP/TYPE13, whose local X is node1->node2 (r4buf3.F:145), so the torsion
    acts about the element's own axis."""

    DECK = _spring_deck("*MAT_SPRING_ELASTIC\n         1     250.0\n",
                        section="         1         1\n")

    def test_stiffness_is_on_rotational_slot_four(self):
        _, starter = _convert(self.DECK)
        self.assertNotIn("/PROP/TYPE4/", starter)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        for slot, expected in ((1, "0"), (2, "0"), (3, "0"),
                               (4, "250"), (5, "0"), (6, "0")):
            k_card = blk[4 + 6 * (slot - 1) + 1]
            self.assertEqual(k_card[0:20].strip(), expected,
                             f"K{slot}")

    def test_zero_length_torsional_element_is_not_converted(self):
        """With node1 == node2 there is no axis to twist about (r4buf3.F
        answers WARNING 325)."""
        deck = self.DECK.replace(
            "       2             1.0             0.0             0.0\n",
            "       2             0.0             0.0             0.0\n")
        result, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE13/", starter)
        self.assertTrue(any("ZERO-LENGTH" in w for w in result.warnings))

    def test_oriented_torsional_uses_type8_slot_four(self):
        deck = _spring_deck(
            "*MAT_SPRING_ELASTIC\n         1     250.0\n",
            section="         1         1\n",
            extra="*DEFINE_SD_ORIENTATION\n"
                  "         4         0       0.0       0.0       1.0\n",
        ).replace("       1       1       1       2\n",
                  "       1       1       1       2       4\n")
        _, starter = _convert(deck)
        blk = _block_lines(starter, "/PROP/TYPE8/")
        # blk[0] header, [1] title, [2] card-1 comment, [3] card 1, then six
        # 6-line DOF blocks (un-indexed comments on TYPE8).
        self.assertEqual(blk[5][0:20].strip(), "0")      # K1
        self.assertEqual(blk[23][0:20].strip(), "250")   # K4


class NonlinearScaleTests(unittest.TestCase):
    """The per-element force scale S on a NONLINEAR spring rides on A, and the
    property readers store the stiffness as K/A (hm_read_prop04.F:249) — so K
    has to be pre-multiplied by S^2 for the stored K/A to be the true scaled
    tangent S*K."""

    def test_scaled_nonlinear_spring_stores_s_squared_k(self):
        deck = _spring_deck(
            "*MAT_SPRING_NONLINEAR_ELASTIC\n         1        51\n",
            extra=CURVE_51).replace(
            "       1       1       1       2\n",
            "       1       1       1       2       0             3.0\n")
        _, starter = _convert(deck)
        blk = _block_lines(starter, "/PROP/TYPE4/")
        # slope at origin = 400; S = 3 -> A = 3, K = 400*9 = 3600, so the
        # stored K/A = 1200 = 3*400.
        self.assertEqual(blk[5][0:20].strip(), "3600")
        self.assertEqual(blk[5][40:60].strip(), "3")


# ── *SECTION_BEAM ELFORM=6 discrete beams ────────────────────────────────────

DBEAM_HEAD = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             0.0             0.0            10.0\n"
    "       3             1.0             0.0             0.0\n"
)
DBEAM_TAIL = (
    "*ELEMENT_BEAM\n"
    "       1       7       1       2       3\n"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)
COORD_77 = ("*DEFINE_COORDINATE_SYSTEM\n"
            "        77       0.0       0.0       0.0       1.0       0.0"
            "       0.0\n"
            "       0.0       1.0       0.0\n")


def _dbeam_deck(mat: str, card1_tail: str = "", card2: str = None,
                extra: str = "") -> str:
    """A one-element discrete-beam deck. ``card1_tail`` fills *SECTION_BEAM
    card 1 from SHRF on (SHRF QR CST SCOOR); ``card2`` is card 2f."""
    if card2 is None:
        card2 = "     100.0       5.0         0\n"
    return (DBEAM_HEAD + extra
            + "*PART\ndiscrete beam\n         7         3         9\n"
            + "*SECTION_BEAM\n"
            + "         3         6" + card1_tail + "\n" + card2
            + mat + DBEAM_TAIL)


SCOOR2 = "       0.0       0.0       0.0       2.0"

MAT066 = ("*MAT_LINEAR_ELASTIC_DISCRETE_BEAM\n"
          "         9    7.8E-9    1000.0    2000.0    3000.0    4000.0"
          "    5000.0    6000.0\n"
          "      10.0      20.0      30.0      40.0      50.0      60.0\n"
          "     500.0       0.0       0.0       0.0       0.0       0.0\n")


class SectionBeamElform6ParseTests(unittest.TestCase):
    def test_card_2f_fields_land_in_named_slots(self):
        st = _dispatch(_dbeam_deck(
            MAT066, card1_tail=SCOOR2,
            card2="     100.0       5.0        77      12.0       1.5"
                  "       1.0       0.0       1.0\n"))
        sec = st.sec_beams[3]
        self.assertEqual(sec.elform, 6)
        self.assertEqual(sec.scoor, 2.0)
        self.assertEqual(sec.vol, 100.0)
        self.assertEqual(sec.iner, 5.0)
        self.assertEqual(sec.cid, 77)
        self.assertEqual(sec.ca, 12.0)          # NOT DOFN1 (cfg comment bug)
        self.assertEqual(sec.cable_offset, 1.5)  # NOT DOFN2
        self.assertEqual((sec.rrcon, sec.srcon, sec.trcon), (1.0, 0.0, 1.0))
        # Card 2f states NO cross-section at all.
        self.assertEqual((sec.area, sec.iyy, sec.izz, sec.ixx),
                         (0.0, 0.0, 0.0, 0.0))

    def test_no_prop_beam_is_emitted_for_the_elform6_section(self):
        _, starter = _convert(_dbeam_deck(MAT066, card1_tail=SCOOR2))
        self.assertNotIn("/PROP/BEAM/3", starter)
        self.assertNotIn("/BEAM/7", starter)


class Mat066Tests(unittest.TestCase):
    DECK = _dbeam_deck(MAT066, card1_tail=SCOOR2)

    def test_handler_parses_three_cards(self):
        st = _dispatch(self.DECK)
        m = st.mat_dbeam_linear[9]
        self.assertEqual(m.rho, 7.8e-9)
        self.assertEqual(m.k, [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0])
        self.assertEqual(m.c, [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        self.assertEqual(m.preload, [500.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_r_s_t_map_straight_onto_dof_1_to_6(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        for slot, k, c in ((1, "1000", "10"), (2, "2000", "20"),
                           (3, "3000", "30"), (4, "4000", "40"),
                           (5, "5000", "50"), (6, "6000", "60")):
            card = blk[4 + 6 * (slot - 1) + 1]
            self.assertEqual(card[0:20].strip(), k, f"K{slot}")
            self.assertEqual(card[20:40].strip(), c, f"C{slot}")

    def test_mass_is_rho_times_vol_and_inertia_is_iner(self):
        _, starter = _convert(self.DECK)
        card1 = _block_lines(starter, "/PROP/TYPE13/")[3]
        self.assertAlmostEqual(float(card1[0:20]), 7.8e-9 * 100.0)
        self.assertEqual(float(card1[20:40]), 5.0)

    def test_preload_becomes_a_two_point_stiffness_function(self):
        _, starter = _convert(self.DECK)
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        fid = int(fcard[0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 500.0), (1.0, 1500.0)])

    def test_scoor_two_selects_the_node_oriented_property(self):
        _, starter = _convert(self.DECK)
        self.assertIn("/PROP/TYPE13/", starter)
        self.assertNotIn("/PROP/TYPE8/", starter)

    def test_cid_without_scoor_two_selects_the_skew_oriented_property(self):
        _, starter = _convert(_dbeam_deck(
            MAT066, card2="     100.0       5.0        77\n", extra=COORD_77))
        blk = _block_lines(starter, "/PROP/TYPE8/")
        self.assertEqual(blk[3][40:50].strip(), "77")     # skew_ID = CID
        self.assertNotIn("/PROP/TYPE13/", starter)

    def test_unresolvable_cid_falls_back_to_node_orientation(self):
        result, starter = _convert(_dbeam_deck(
            MAT066, card2="     100.0       5.0        99\n"))
        self.assertIn("/PROP/TYPE13/", starter)
        self.assertTrue(any("CID=99" in w and "ERROR 137" in w
                            for w in result.warnings))

    def test_spring_row_keeps_the_beam_id_and_third_node(self):
        _, starter = _convert(self.DECK)
        self.assertIn("\n/SPRING/7\n", starter)
        self.assertIn("\n         1         1         2         3\n", starter)


class Mat067Tests(unittest.TestCase):
    MAT = ("*MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM\n"
           "         9    7.8E-9        51         0         0         0"
           "         0         0\n"
           "        50         0         0         0         0         0\n"
           "       0.0       0.0       0.0       0.0       0.0       0.0\n"
           "       0.0       0.0       0.0       0.0       0.0       0.0\n"
           "       2.5       0.0       0.0       0.0       0.0       0.0\n")
    DECK = _dbeam_deck(MAT, card1_tail=SCOOR2, extra=CURVE_50 + CURVE_51)

    def test_loading_and_damping_curve_slots(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        fcard = blk[7]
        # LCIDTR=51 already spans both quadrants and carries no preload, so it
        # is referenced verbatim (a /DEFINE_CURVE id IS the /FUNCT id).
        self.assertEqual(fcard[0:10].strip(), "51")     # fct_ID11
        self.assertEqual(fcard[40:50].strip(), "50")    # fct_ID41 = LCIDTDR
        self.assertEqual(blk[9][60:80].strip(), "1")    # Hscale1 = 1

    def test_stiffness_comes_from_the_curve_slope_at_the_origin(self):
        """MAT_067 states no stiffness, and a K=0 spring contributes nothing to
        the explicit time step (r1len3.F:81-105)."""
        result, starter = _convert(self.DECK)
        self.assertEqual(
            _block_lines(starter, "/PROP/TYPE13/")[5][0:20].strip(), "400")
        self.assertTrue(any("SLOPE OF THE LOADING CURVE" in w
                            for w in result.warnings))

    def test_displacement_limits_win_over_force_limits(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[3][70:80].strip(), "1")     # Ifail = 1
        self.assertEqual(blk[3][90:100].strip(), "1")    # Ifail2 = 1 (displ.)
        self.assertEqual(blk[7][60:80].strip(), "-2.5")  # DeltaMin1
        self.assertEqual(blk[7][80:100].strip(), "2.5")  # DeltaMax1

    def test_force_limits_are_used_when_no_displacement_limit_is_given(self):
        mat = self.MAT.replace(
            "       0.0       0.0       0.0       0.0       0.0       0.0\n"
            "       0.0       0.0       0.0       0.0       0.0       0.0\n"
            "       2.5       0.0       0.0       0.0       0.0       0.0\n",
            "       0.0       0.0       0.0       0.0       0.0       0.0\n"
            "    9000.0       0.0       0.0       0.0       0.0       0.0\n"
            "       0.0       0.0       0.0       0.0       0.0       0.0\n")
        _, starter = _convert(_dbeam_deck(mat, card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[3][90:100].strip(), "2")    # Ifail2 = 2 (force)
        self.assertEqual(blk[7][80:100].strip(), "9000")

    def test_one_sided_curve_is_mirrored_and_preloaded(self):
        mat = self.MAT.replace(
            "         9    7.8E-9        51         0",
            "         9    7.8E-9        50         0").replace(
            "       0.0       0.0       0.0       0.0       0.0       0.0\n"
            "       0.0       0.0       0.0       0.0       0.0       0.0\n"
            "       2.5",
            "     500.0       0.0       0.0       0.0       0.0       0.0\n"
            "       0.0       0.0       0.0       0.0       0.0       0.0\n"
            "       2.5")
        _, starter = _convert(_dbeam_deck(mat, card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        fid = int(fcard[0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-2.0, 350.0), (-1.0, 400.0), (0.0, 500.0),
                          (1.0, 600.0), (2.0, 650.0)])


class Mat068Tests(unittest.TestCase):
    """LCPD* abscissae are PLASTIC displacement; Radioss reads TOTAL, so each
    abscissa gains F/K. With K1 = 1000 the curve (0,0) (1,100) (2,150) becomes
    (0,0) (1.1,100) (2.15,150), mirrored through the origin, H=1."""

    MAT = ("*MAT_NONLINEAR_PLASTIC_DISCRETE_BEAM\n"
           "         9    7.8E-9    1000.0       0.0       0.0       0.0"
           "       0.0       0.0\n"
           "      10.0       0.0       0.0       0.0       0.0       0.0"
           "       1.4\n"
           "        50         0         0         0         0         0\n"
           "    7000.0       0.0       0.0       0.0       0.0       0.0\n"
           "       3.0       0.0       0.0       0.0       0.0       0.0\n"
           "       0.0       0.0       0.0       0.0       0.0       0.0\n")
    DECK = _dbeam_deck(MAT, card1_tail=SCOOR2, extra=CURVE_50)

    def test_handler_reads_ryld_from_the_r12_column(self):
        st = _dispatch(self.DECK)
        self.assertEqual(st.mat_dbeam_nl_plastic[9].ryld, 1.4)

    def test_plastic_to_total_displacement_conversion(self):
        _, starter = _convert(self.DECK)
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        self.assertEqual(fcard[10:20].strip(), "1")     # H1 = 1
        fid = int(fcard[0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-2.15, -150.0), (-1.1, -100.0), (0.0, 0.0),
                          (1.1, 100.0), (2.15, 150.0)])

    def test_force_limits_win_over_displacement_limits(self):
        """MAT_068 reverses MAT_067's priority (dyna2rad convertmats.cxx:3848
        vs :3680) — both pairs are populated here, so the order is visible."""
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[3][90:100].strip(), "2")     # Ifail2 = 2 (force)
        self.assertEqual(blk[7][80:100].strip(), "7000")  # FFAILR, not UFAILR

    def test_ryld_is_named_in_a_warning(self):
        result, _ = _convert(self.DECK)
        self.assertTrue(any("RYLD=1.4" in w for w in result.warnings))


class Mat071CableTests(unittest.TestCase):
    def _deck(self, mat_card: str, ca: str = "      12.0"):
        return _dbeam_deck(
            mat_card, card2="     100.0       5.0         0" + ca + "\n")

    def test_positive_e_gives_k_equal_e_times_ca_and_ileng_one(self):
        _, starter = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9  210000.0\n"))
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[3][70:80].strip(), "0")      # Ifail
        self.assertEqual(blk[3][80:90].strip(), "1")      # Ileng = 1
        self.assertEqual(blk[5][0:20].strip(), "2520000")  # K1 = E*CA
        # Ileng=1 makes Mass a mass PER UNIT LENGTH (rinit3.F:408-412), so it
        # is RO*CA, not RO*CA*L.
        self.assertAlmostEqual(float(blk[3][0:20]), 7.8e-9 * 12.0)

    def test_negative_e_is_used_as_the_stiffness_directly(self):
        _, starter = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9   -5000.0\n"))
        self.assertEqual(
            _block_lines(starter, "/PROP/TYPE13/")[5][0:20].strip(), "5000")

    def test_tension_only_curve_with_no_pretension(self):
        _, starter = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9   -5000.0\n"))
        fid = int(_block_lines(starter, "/PROP/TYPE13/")[7][0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-1.0, 0.0), (0.0, 0.0), (1.0, 5000.0)])

    def test_pretension_shifts_the_slack_point_not_the_zero_branch(self):
        """F = max(F0 + K*strain, 0): the cable is already stretched by F0/K,
        so the flat branch must end there. A plain ordinate shift (what
        dyna2rad writes) leaves the cable PUSHING with F0 in compression."""
        _, starter = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9   -5000.0         0     250.0\n"))
        fid = int(_block_lines(starter, "/PROP/TYPE13/")[7][0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-1.05, 0.0), (-0.05, 0.0), (0.95, 5000.0)])

    def test_time_limited_pretension_is_dropped_with_a_warning(self):
        result, starter = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9   -5000.0         0     250.0      0.01\n"))
        fid = int(_block_lines(starter, "/PROP/TYPE13/")[7][0:10])
        self.assertEqual(_funct_points(starter, fid),
                         [(-1.0, 0.0), (0.0, 0.0), (1.0, 5000.0)])
        self.assertTrue(any("TMAXF0" in w for w in result.warnings))

    def test_missing_ca_with_positive_e_warns(self):
        result, _ = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9  210000.0\n", ca=""))
        self.assertTrue(any("ZERO stiffness" in w for w in result.warnings))

    def test_iread_card2_is_warn_dropped(self):
        result, _ = _convert(self._deck(
            "*MAT_CABLE_DISCRETE_BEAM\n"
            "         9    7.8E-9   -5000.0         0       0.0       0.0"
            "       0.0         1\n"
            "         1       0.0\n"))
        self.assertTrue(any("IREAD=1" in w for w in result.warnings))


class Mat074Tests(unittest.TestCase):
    MAT = ("*MAT_ELASTIC_SPRING_DISCRETE_BEAM\n"
           "         9    7.8E-9    1500.0       0.0       2.5       4.0"
           "       6.0\n"
           "         0        50       1.1       2.2       3.3        51\n")
    DECK = _dbeam_deck(MAT, extra=CURVE_50 + CURVE_51)

    def test_scalar_slots(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        kcard = blk[5]
        self.assertEqual(kcard[0:20].strip(), "1500")   # K1 = K
        self.assertEqual(kcard[20:40].strip(), "2.5")   # C1 = D (the DAMPING
        #                                                 column, not the c1
        #                                                 relative-velocity
        #                                                 coefficient)
        self.assertEqual(kcard[60:80].strip(), "2.2")   # B1 = C2
        self.assertEqual(kcard[80:100].strip(), "3.3")  # D1 = DLE
        self.assertEqual(blk[9][20:40].strip(), "1.1")  # E1 = C1

    def test_failure_displacements_are_signed(self):
        """CDF is input POSITIVE in LS-DYNA but DeltaMin must be <= 0."""
        _, starter = _convert(self.DECK)
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        self.assertEqual(fcard[60:80].strip(), "-4")    # -CDF
        self.assertEqual(fcard[80:100].strip(), "6")    # TDF
        self.assertEqual(fcard[20:30].strip(), "50")    # fct_ID21 = HLCID

    def test_glcid_is_warn_dropped(self):
        result, _ = _convert(self.DECK)
        self.assertTrue(any("GLCID=51" in w for w in result.warnings))

    def test_rate_terms_apply_even_without_flcid(self):
        """dyna2rad puts the whole DLE/C1/C2/GLCID block inside
        `if (FLCID valid)`, so a blank FLCID silently loses the rate law."""
        _, starter = _convert(self.DECK)
        self.assertEqual(_block_lines(starter, "/PROP/TYPE13/")[5][60:80].strip(),
                         "2.2")


class Mat119Tests(unittest.TestCase):
    def _mat(self, iunld: str = "         1", unld: str = "        51"):
        return ("*MAT_GENERAL_NONLINEAR_6DOF_DISCRETE_BEAM\n"
                "         9    7.8E-9    1000.0    2000.0" + iunld
                + "       0.0       0.0         0\n"
                "        50         0         0         0         0         0\n"
                + unld + "         0         0         0         0         0\n"
                "         0         0         0         0         0         0\n"
                "         0         0         0         0         0         0\n"
                "       3.0       0.0       0.0       0.0       0.0       0.0\n"
                "       1.5       0.0       0.0       0.0       0.0       0.0\n"
                "         0         0         0         0         0         0\n")

    def test_kt_and_kr_fill_the_translational_and_rotational_slots(self):
        _, starter = _convert(_dbeam_deck(self._mat(), card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        blk = _block_lines(starter, "/PROP/TYPE13/")
        for slot in (1, 2, 3):
            self.assertEqual(blk[4 + 6 * (slot - 1) + 1][0:20].strip(), "1000")
        for slot in (4, 5, 6):
            self.assertEqual(blk[4 + 6 * (slot - 1) + 1][0:20].strip(), "2000")

    def test_unldopt_one_gives_hflag_six_with_the_unloading_curve(self):
        _, starter = _convert(_dbeam_deck(self._mat(), card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        self.assertEqual(fcard[0:10].strip(), "50")     # fct_ID11 loading
        self.assertEqual(fcard[10:20].strip(), "6")     # H1 = 6
        self.assertEqual(fcard[30:40].strip(), "51")    # fct_ID31 unloading

    def test_same_curve_on_both_slots_means_elastic(self):
        _, starter = _convert(_dbeam_deck(self._mat(unld="        50"),
                                          card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        self.assertEqual(fcard[10:20].strip(), "0")     # H1 demoted
        self.assertEqual(fcard[30:40].strip(), "0")     # fct_ID31 cleared

    def test_unldopt_three_is_mapped_to_hflag_five(self):
        """dyna2rad maps UNLDOPT=3 for MAT_121 only, leaving MAT_119's springs
        purely elastic."""
        _, starter = _convert(_dbeam_deck(self._mat(iunld="         3"),
                                          card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        self.assertEqual(
            _block_lines(starter, "/PROP/TYPE13/")[7][10:20].strip(), "5")

    def test_tension_and_compression_limits_are_signed(self):
        _, starter = _convert(_dbeam_deck(self._mat(), card1_tail=SCOOR2,
                                          extra=CURVE_50 + CURVE_51))
        fcard = _block_lines(starter, "/PROP/TYPE13/")[7]
        self.assertEqual(fcard[60:80].strip(), "-1.5")  # -UCFAILR
        self.assertEqual(fcard[80:100].strip(), "3")    # UTFAILR

    def test_iflag_two_warns_about_the_lost_buckling_tables(self):
        mat = self._mat().replace("       0.0       0.0         0\n",
                                  "       0.0       0.0         2\n", 1)
        result, _ = _convert(_dbeam_deck(mat, card1_tail=SCOOR2,
                                         extra=CURVE_50 + CURVE_51))
        self.assertTrue(any("IFLAG=2" in w for w in result.warnings))


class Mat121Tests(unittest.TestCase):
    MAT = ("*MAT_GENERAL_NONLINEAR_1DOF_DISCRETE_BEAM\n"
           "         9    7.8E-9    1200.0         2       0.0       0.0\n"
           "        50        51         0         0\n"
           "       4.0       2.0         0\n")
    DECK = _dbeam_deck(MAT, card1_tail=SCOOR2, extra=CURVE_50 + CURVE_51)

    def test_single_dof_payload(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[5][0:20].strip(), "1200")   # K1
        fcard = blk[7]
        self.assertEqual(fcard[0:10].strip(), "50")      # LCIDT
        self.assertEqual(fcard[10:20].strip(), "7")      # UNLDOPT 2 -> H=7
        self.assertEqual(fcard[30:40].strip(), "51")     # LCIDTU
        self.assertEqual(fcard[60:80].strip(), "-2")     # -UCFAIL
        self.assertEqual(fcard[80:100].strip(), "4")     # UTFAIL
        # DOFs 2..6 stay inert.
        self.assertEqual(blk[11][0:20].strip(), "0")


class Mat196Tests(unittest.TestCase):
    MAT = ("*MAT_GENERAL_SPRING_DISCRETE_BEAM\n"
           # MID RO then 40 blank columns; MDFAIL is cols 61-70 and DOSPOT
           # 71-80 (the shipped Keyword971 cfg stops after RO).
           "         9    7.8E-9" + " " * 40 + "         1         0\n"
           "         1         0    1000.0      12.0       3.0       4.0\n"
           "        50         0       0.5       0.6       0.7         0\n"
           "         4         1    2000.0       0.0       1.0       2.0\n"
           "        51         0       0.0       0.0       0.0         0\n")
    DECK = _dbeam_deck(MAT, card1_tail=SCOOR2, extra=CURVE_50 + CURVE_51)

    def test_handler_reads_the_dof_card_pairs(self):
        st = _dispatch(self.DECK)
        m = st.mat_general_spring_dbeam[9]
        self.assertEqual(m.mdfail, 1)
        self.assertEqual(len(m.dofs), 2)
        self.assertEqual(m.dofs[0][:6], (1, 0, 1000.0, 12.0, 3.0, 4.0))
        self.assertEqual(m.dofs[1][:2], (4, 1))

    def test_each_pair_fills_the_slot_it_names(self):
        _, starter = _convert(self.DECK)
        blk = _block_lines(starter, "/PROP/TYPE13/")
        k1 = blk[5]
        self.assertEqual(k1[0:20].strip(), "1000")     # K1
        self.assertEqual(k1[20:40].strip(), "12")      # C1 = D
        self.assertEqual(k1[60:80].strip(), "0.6")     # B1 = C2
        self.assertEqual(k1[80:100].strip(), "0.7")    # D1 = DLE
        self.assertEqual(blk[9][20:40].strip(), "0.5")  # E1 = C1
        self.assertEqual(blk[7][60:80].strip(), "-3")   # -|CDF|
        self.assertEqual(blk[7][80:100].strip(), "4")   # +|TDF|
        # DOF 2 was never given a pair.
        self.assertEqual(blk[11][0:20].strip(), "0")
        # DOF 4 comes from the second pair.
        self.assertEqual(blk[23][0:20].strip(), "2000")

    def test_type_one_dof_gets_the_plastic_conversion_and_hflag_one(self):
        _, starter = _convert(self.DECK)
        fcard = _block_lines(starter, "/PROP/TYPE13/")[25]
        self.assertEqual(fcard[10:20].strip(), "1")     # H4 = 1
        fid = int(fcard[0:10])
        # curve 51 is (-1,-400) (0,0) (1,400); the positive half with K=2000
        # gives x = 1 + 400/2000 = 1.2, then mirrored.
        self.assertEqual(_funct_points(starter, fid),
                         [(-1.2, -400.0), (0.0, 0.0), (1.2, 400.0)])

    def test_type_zero_dof_references_the_curve_verbatim(self):
        _, starter = _convert(self.DECK)
        self.assertEqual(
            _block_lines(starter, "/PROP/TYPE13/")[7][0:10].strip(), "50")

    def test_mdfail_is_named_in_a_warning(self):
        result, _ = _convert(self.DECK)
        self.assertTrue(any("MDFAIL=1" in w for w in result.warnings))

    def test_duplicate_dof_warns(self):
        mat = self.MAT.replace(
            "         4         1    2000.0", "         1         1    2000.0")
        result, _ = _convert(_dbeam_deck(mat, card1_tail=SCOOR2,
                                         extra=CURVE_50 + CURVE_51))
        self.assertTrue(any("defined more than" in w for w in result.warnings))


class UnmappedDiscreteBeamTests(unittest.TestCase):
    def test_each_unmapped_family_names_what_is_lost(self):
        cases = [
            ("*MAT_SID_DAMPER_DISCRETE_BEAM", "orifice"),
            ("*MAT_HYDRAULIC_GAS_DAMPER_DISCRETE_BEAM", "polytropic"),
            ("*MAT_ELASTIC_6DOF_SPRING_DISCRETE_BEAM", "co-rotational"),
            ("*MAT_INELASTIC_SPRING_DISCRETE_BEAM", "yield offsets"),
            ("*MAT_INELASTIC_6DOF_SPRING_DISCRETE_BEAM", "per-DOF yield"),
            ("*MAT_GENERAL_JOINT_DISCRETE_BEAM", "TYPE45"),
            ("*MAT_1DOF_GENERALIZED_SPRING", "DOFN1/DOFN2"),
        ]
        for kw, needle in cases:
            with self.subTest(kw=kw):
                result, starter = _convert(_dbeam_deck(
                    kw + "\n         9    7.8E-9\n", card1_tail=SCOOR2))
                self.assertTrue(any(needle in w for w in result.warnings),
                                f"{kw}: no warning naming {needle!r}")
                # The connector is still written, inert, so the deck starts.
                blk = _block_lines(starter, "/PROP/TYPE13/")
                self.assertEqual(blk[5][0:20].strip(), "0")
                self.assertIn("\n/SPRING/7\n", starter)

    def test_rho_is_still_used_for_the_connector_mass(self):
        _, starter = _convert(_dbeam_deck(
            "*MAT_SID_DAMPER_DISCRETE_BEAM\n         9    7.8E-9\n",
            card1_tail=SCOOR2))
        self.assertAlmostEqual(
            float(_block_lines(starter, "/PROP/TYPE13/")[3][0:20]),
            7.8e-9 * 100.0)

    def test_discrete_beam_material_on_a_non_elform6_section(self):
        """The part is CLAIMED by the connector path (its material is a
        6-DOF spring material), so skipping it would delete the /PART along
        with every *SET_PART member that names it. An inert connector keeps
        the deck startable and the ids addressable."""
        deck = _dbeam_deck(MAT066, card1_tail="").replace(
            "         3         6\n     100.0       5.0         0\n",
            "         3         2\n       4.0       1.2       1.2       2.4\n")
        result, starter = _convert(deck)
        self.assertTrue(any("ELFORM=2, not 6" in w for w in result.warnings))
        self.assertTrue(any("INERT /SPRING" in w for w in result.warnings))
        blk = _block_lines(starter, "/PROP/TYPE13/")
        self.assertEqual(blk[5][0:20].strip(), "0")     # no stiffness
        self.assertIn("\n/PART/7\n", starter)
        self.assertIn("\n/SPRING/7\n", starter)

    def test_unknown_material_on_an_elform6_section_still_warns(self):
        result, starter = _convert(_dbeam_deck(
            "*MAT_ELASTIC\n         9    7.8E-9  210000.0       0.3\n",
            card1_tail=SCOOR2))
        self.assertTrue(any("not a discrete-beam material" in w
                            for w in result.warnings))
        self.assertIn("/PROP/TYPE13/", starter)


class TargetMatLawTests(unittest.TestCase):
    """Every spring/discrete-beam material emits NO /MAT: the whole material
    lives in the connector property and the /PART carries mat_id 0."""

    CASES = [
        ("*MAT_SPRING_ELASTIC\n         9     250.0\n", None),
        ("*MAT_SPRING_ELASTOPLASTIC\n         9    1000.0     200.0"
         "      50.0\n", None),
        ("*MAT_DAMPER_NONLINEAR_VISCOUS\n         9        50\n", None),
        ("*MAT_SPRING_GENERAL_NONLINEAR\n         9        50        51\n",
         None),
        ("*MAT_SPRING_INELASTIC\n         9        50     800.0\n", None),
        (MAT066, None),
        ("*MAT_CABLE_DISCRETE_BEAM\n         9    7.8E-9   -5000.0\n", None),
        ("*MAT_SID_DAMPER_DISCRETE_BEAM\n         9    7.8E-9\n", None),
    ]

    def test_no_mat_is_emitted_for_any_spring_family(self):
        for mat, expected in self.CASES:
            with self.subTest(mat=mat.splitlines()[0]):
                st = _dispatch(_dbeam_deck(mat, card1_tail=SCOOR2,
                                           extra=CURVE_50 + CURVE_51))
                self.assertEqual(_target_mat_law(st, 9), expected)

    def test_element_free_spring_part_is_claimed_by_the_connector_path(self):
        """A *PART on a spring material with no elements must NOT reach the
        ordinary /PART emission — it would reference a MID that emits no /MAT
        (starter ERROR 3046) and a *SECTION_DISCRETE that emits no /PROP."""
        from k2rad.writer.common import _discrete_part_ids
        for mat, kw in (
                ("*MAT_SPRING_ELASTOPLASTIC\n"
                 "         9    1000.0     200.0      50.0\n", "S03"),
                ("*MAT_DAMPER_NONLINEAR_VISCOUS\n         9        50\n", "S05"),
                ("*MAT_SPRING_GENERAL_NONLINEAR\n"
                 "         9        50        51\n", "S06"),
                ("*MAT_SPRING_INELASTIC\n"
                 "         9        50     800.0\n", "S08")):
            with self.subTest(kw=kw):
                deck = ("*KEYWORD\n*PART\nempty spring\n"
                        "         7         3         9\n"
                        "*SECTION_DISCRETE\n         3         0\n"
                        + mat + CURVE_50 + CURVE_51
                        + "*CONTROL_TERMINATION\n       1.0\n*END\n")
                st = _dispatch(deck)
                self.assertIn(7, _discrete_part_ids(st))

    def test_spring_parts_do_not_reach_the_beam_type3_check(self):
        """A discrete-beam part HAS *ELEMENT_BEAMs, so it would otherwise be
        reported as 'no /MAT at all' by _warn_beam_type3_material."""
        result, _ = _convert(_dbeam_deck(MAT066, card1_tail=SCOOR2))
        self.assertFalse(any("/PROP/BEAM" in w and "TYPE3" in w
                             for w in result.warnings))


class CurveHelperTests(unittest.TestCase):
    def test_mirror_one_sided_curve(self):
        pts = [(0.0, 0.0), (1.0, 100.0), (2.0, 150.0)]
        self.assertEqual(wloads._mirror_one_sided_curve(pts, True),
                         [(-1.0, 0.0), (0.0, 0.0), (1.0, 100.0), (2.0, 150.0)])
        self.assertEqual(wloads._mirror_one_sided_curve(pts, False),
                         [(-2.0, -150.0), (-1.0, -100.0), (0.0, 0.0),
                          (1.0, 0.0)])
        # A two-quadrant curve is left alone.
        two = [(-1.0, -100.0), (0.0, 0.0), (1.0, 100.0)]
        self.assertEqual(wloads._mirror_one_sided_curve(two, False), two)

    def test_plastic_to_total_disp_is_monotonic(self):
        out = wloads._plastic_to_total_disp(
            [(0.0, 0.0), (0.0, 50.0), (1.0, 100.0)], 1000.0)
        xs = [a for a, _ in out]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), len(xs))

    def test_plastic_to_total_disp_needs_a_stiffness(self):
        self.assertEqual(
            wloads._plastic_to_total_disp([(0.0, 0.0), (1.0, 100.0)], 0.0), [])

    def test_odd_extend_curve(self):
        self.assertEqual(
            wdbeam._odd_extend_curve([(0.0, 0.0), (1.0, 100.0)]),
            [(-1.0, -100.0), (0.0, 0.0), (1.0, 100.0)])

    def test_clamp_tension_only_inserts_the_zero_crossing(self):
        out = wdbeam._clamp_tension_only([(-1.0, -100.0), (1.0, 100.0)])
        self.assertEqual(out, [(-1.0, 0.0), (0.0, 0.0), (1.0, 100.0)])

    def test_unload_hflag_table(self):
        self.assertEqual([wdbeam._dbeam_unload_hflag(i) for i in range(4)],
                         [0, 6, 7, 5])

    def test_dbeam_failure_priority_and_signs(self):
        ifail2, limits = wdbeam._dbeam_failure(
            [2.0, 0, 0, 0, 0, 0], [9.0, 0, 0, 0, 0, 0], disp_first=True)
        self.assertEqual((ifail2, limits[0]), (1, (-2.0, 2.0)))
        ifail2, limits = wdbeam._dbeam_failure(
            [2.0, 0, 0, 0, 0, 0], [9.0, 0, 0, 0, 0, 0], disp_first=False)
        self.assertEqual((ifail2, limits[0]), (2, (-9.0, 9.0)))
        # A negative input still yields a NEGATIVE DeltaMin (the CFG's
        # MIN_RUP <= 0 constraint); dyna2rad writes (-v, +v) and inverts it.
        _, limits = wdbeam._dbeam_failure(
            [-2.0, 0, 0, 0, 0, 0], [0] * 6, disp_first=True)
        self.assertEqual(limits[0], (-2.0, 2.0))


class SpringEidCollisionTests(unittest.TestCase):
    def test_discrete_beam_and_plotel_ids_collide_loudly(self):
        deck = _dbeam_deck(MAT066, card1_tail=SCOOR2) \
            .replace("*CONTROL_TERMINATION\n",
                     "*ELEMENT_PLOTEL\n       1       1       2\n"
                     "*CONTROL_TERMINATION\n")
        result, _ = _convert(deck)
        self.assertTrue(any("ERROR 79" in w and "discrete-beam" in w
                            for w in result.warnings))


class IncludeTransformOffsetTests(unittest.TestCase):
    """*INCLUDE_TRANSFORM must move the MID (IDMOFF) and every curve reference
    (IDFOFF) of the new materials, and the *SECTION_BEAM card-2f CID (IDDOFF).
    A keyword with no offset spec keeps its ids and is only warned about."""

    def _state(self, child: str, offsets: str) -> ConversionState:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write("*KEYWORD\n" + child + "*END\n")
        main = os.path.join(tmp.name, "main.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n" + offsets
                     + "\n*END\n")
        state = ConversionState()
        for block in parse_k_file(main):
            dispatch(block, state)
        return state

    # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF IDDOFF ; then IDROFF
    OFFS = ("      1000      2000      3000      4000      5000      6000"
            "      7000\n      8000\n")

    def test_material_ids_and_curve_ids_move(self):
        st = self._state(
            "*MAT_SPRING_GENERAL_NONLINEAR\n"
            "         9        50        51\n"
            "*MAT_SPRING_INELASTIC\n"
            "         8        50     800.0\n"
            "*MAT_DAMPER_NONLINEAR_VISCOUS\n"
            "         7        50\n", self.OFFS)
        self.assertIn(4009, st.mat_spring_general_nl)
        self.assertEqual((st.mat_spring_general_nl[4009].lcdl,
                          st.mat_spring_general_nl[4009].lcdu), (6050, 6051))
        self.assertEqual(st.mat_spring_inelastic[4008].lcfd, 6050)
        self.assertEqual(st.mat_damper_nl_viscous[4007].lcdr, 6050)

    def test_discrete_beam_curve_runs_move(self):
        st = self._state(
            "*MAT_NONLINEAR_ELASTIC_DISCRETE_BEAM\n"
            "         9    7.8E-9        51        52         0         0"
            "         0         0\n"
            "        50         0         0         0         0         0\n",
            self.OFFS)
        m = st.mat_dbeam_nl_elastic[4009]
        self.assertEqual(m.lcid[:2], [6051, 6052])
        self.assertEqual(m.lcid_damp[0], 6050)

    def test_mat196_pair_walker_moves_only_the_curve_card(self):
        st = self._state(
            "*MAT_GENERAL_SPRING_DISCRETE_BEAM\n"
            "         9    7.8E-9\n"
            "         1         0    1000.0      12.0       3.0       4.0\n"
            "        50         0       0.5       0.6       0.7        51\n",
            self.OFFS)
        m = st.mat_general_spring_dbeam[4009]
        # DOF number and TYPE are NOT ids and must stay put.
        self.assertEqual(m.dofs[0][0], 1)
        self.assertEqual(m.dofs[0][1], 0)
        self.assertEqual(m.dofs[0][6], 6050)     # FLCID
        self.assertEqual(m.dofs[0][11], 6051)    # GLCID

    def test_section_beam_card2f_cid_moves(self):
        st = self._state(
            "*SECTION_BEAM\n"
            "         3         6       0.0       0.0       0.0       2.0\n"
            "     100.0       5.0        77      12.0\n", self.OFFS)
        sec = st.sec_beams[8003]                 # SECID under IDROFF
        self.assertEqual(sec.cid, 7077)          # CID under IDDOFF
        self.assertEqual(sec.vol, 100.0)         # geometry untouched
        self.assertEqual(sec.ca, 12.0)


class ByteIdentityTests(unittest.TestCase):
    """A deck with none of the batch's keywords must convert exactly as before
    — the whole corpus sweep rests on that."""

    PLAIN = (
        "*KEYWORD\n"
        "*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2             1.0             0.0             0.0\n"
        "       3             1.0             1.0             0.0\n"
        "       4             0.0             1.0             0.0\n"
        "*PART\nshell part\n         1         1         1\n"
        "*SECTION_SHELL\n         1         2\n       1.0\n"
        "*MAT_ELASTIC\n         1    7.8E-9  210000.0       0.3\n"
        "*ELEMENT_SHELL\n"
        "       1       1       1       2       3       4\n"
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )

    def test_plain_shell_deck_has_no_spring_output_and_no_new_warnings(self):
        result, starter = _convert(self.PLAIN)
        self.assertNotIn("/PROP/TYPE4/", starter)
        self.assertNotIn("/PROP/TYPE8/", starter)
        self.assertNotIn("/PROP/TYPE13/", starter)
        self.assertNotIn("DISCRETE BEAM CONNECTORS", starter)
        for needle in ("discrete-beam", "DRO=1", "ELFORM=6"):
            self.assertFalse(any(needle in w for w in result.warnings),
                             f"unexpected {needle!r} warning on a plain deck")

    def test_s01_spring_deck_output_is_unchanged_by_the_batch(self):
        """The Yaris/Camry suspension springs are S01/S04/D01 — the corpus
        byte-identity canary. Their /PROP/TYPE4 must be exactly the four
        pre-existing cards, with every new column at its reader default."""
        _, starter = _convert(_spring_deck(
            "*MAT_SPRING_ELASTIC\n         1     250.0\n"))
        blk = _block_lines(starter, "/PROP/TYPE4/")
        self.assertEqual(blk[5], f"{250.0:>20g}" + f"{0.0:>20g}" * 4)
        self.assertEqual(blk[7], f"{0:>10d}" * 5 + " " * 10
                         + f"{0.0:>20g}" * 2)
        self.assertEqual(blk[9], f"{0.0:>20g}" * 4)


if __name__ == "__main__":
    unittest.main()
