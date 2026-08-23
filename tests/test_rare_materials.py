"""Tests for the RARE MATERIALS batch:

  *MAT_SHAPE_MEMORY / *MAT_030      → /MAT/LAW71
  *MAT_MUSCLE / *MAT_156            → /PROP/TYPE46 (SPR_MUSCLE) + /SPRING
  *MAT_SPRING_MUSCLE / *MAT_S15     → /PROP/TYPE46 (SPR_MUSCLE) + /SPRING
  *MAT_ADD_THERMAL_EXPANSION        → /THERM_STRESS/MAT + /HEAT/MAT
  *MAT_THERMAL_ISOTROPIC (*PART TMID) → the /HEAT/MAT values
  *INITIAL_TEMPERATURE[_SET|_NODE]  → /INITEMP
  *LOAD_THERMAL_* / *BOUNDARY_TEMPERATURE[_SET|_NODE] → /IMPTEMP

Kept in its own module, the repo's one-module-per-batch convention.
"""

import math
import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import HANDLERS, RARE_MATERIAL_KEYWORDS, dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness ──────────────────────────────────────────────────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
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


def _block(starter: str, header: str):
    """The lines of the first starter block whose header line equals *header*,
    up to the next '/' line."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            out = []
            for data in lines[i + 1:]:
                if data.startswith("/"):
                    break
                out.append(data)
            return out
    return None


def _data_rows(starter: str, header: str):
    """The non-comment, non-ruler data rows of a starter block."""
    body = _block(starter, header)
    if body is None:
        return None
    return [ln for ln in body if not ln.startswith("#")]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _row16(*vals) -> str:
    """LS-DYNA *DEFINE_CURVE point row (2 x 16-char fields)."""
    return "".join(f"{v:>16}" for v in vals)


def _fields(row: str, w: int = 20):
    """Slice a fixed-width Radioss card row into stripped w-char cells."""
    return [row[i:i + w].strip() for i in range(0, len(row.rstrip()), w)]


def _prop_id(starter: str) -> int:
    """The id of the (single) /PROP/TYPE46 in a starter deck."""
    for ln in starter.splitlines():
        if ln.startswith("/PROP/TYPE46/"):
            return int(ln.rsplit("/", 1)[1])
    raise AssertionError("no /PROP/TYPE46 in the deck")


def _funct_named(starter: str, title: str) -> int:
    """The id of the /FUNCT whose title line is exactly *title*."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/FUNCT/") and i + 1 < len(lines) \
                and lines[i + 1].strip() == title:
            return int(ln.rsplit("/", 1)[1])
    raise AssertionError(f"no /FUNCT titled {title!r}")


def _funct_points(starter: str, fid: int):
    """The (x, y) pairs of /FUNCT/<fid>."""
    body = _block(starter, f"/FUNCT/{fid}")
    pts = []
    for ln in body[1:]:
        if ln.startswith("#"):
            continue
        pts.append((float(ln[0:20]), float(ln[20:40])))
    return pts


# ── Shared deck fragments ────────────────────────────────────────────────────

#: One hex on part 1. `{MAT}` is substituted with the material under test, and
#: `{EXTRA}` with anything else the case needs.
HEX = (
    "*KEYWORD\n"
    "*NODE\n"
    "         1             0.0             0.0             0.0\n"
    "         2            10.0             0.0             0.0\n"
    "         3            10.0            10.0             0.0\n"
    "         4             0.0            10.0             0.0\n"
    "         5             0.0             0.0            10.0\n"
    "         6            10.0             0.0            10.0\n"
    "         7            10.0            10.0            10.0\n"
    "         8             0.0            10.0            10.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "*PART\n"
    "block\n"
    + _row(1, 1, 30) + "\n"
    "*SECTION_SOLID\n"
    + _row(1, 1) + "\n"
    "{MAT}"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.001\n"
    "*END\n"
)

#: Every slot a DIFFERENT number, so a column swap is detectable:
#: RO 6.45e-9, E 50000, PR 0.33, SIG_ASS 400, SIG_ASF 450, SIG_SAS 300,
#: SIG_SAF 200, EPSL 0.05, ALPHA 0.12, YMRT 25000.
SMA = (
    "*MAT_SHAPE_MEMORY_TITLE\n"
    "NiTi superelastic\n"
    + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
    + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12, 25000.0) + "\n"
)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_SHAPE_MEMORY / *MAT_030 → /MAT/LAW71
# ═════════════════════════════════════════════════════════════════════════════

#: sqrt(2/3)·ALPHA, hand-computed: 0.8164965809277260 × 0.12 = 0.09797958971132712
#: → the card's %.10G field is "0.09797958971", and the starter echoes
#: 9.7979589710000E-02 (measured on the probe deck).
ALPHA_ON_CARD = "0.09797958971"


class ShapeMemoryParseTests(unittest.TestCase):
    def test_card_fields_land_in_their_own_slots(self):
        state = _dispatch("*KEYWORD\n" + SMA + "*END\n")
        m = state.mat_shape_memory[30]
        self.assertEqual(m.title, "NiTi superelastic")
        self.assertAlmostEqual(m.rho, 6.45e-9)
        self.assertAlmostEqual(m.e, 50000.0)
        self.assertAlmostEqual(m.nu, 0.33)
        self.assertAlmostEqual(m.sig_ass, 400.0)
        self.assertAlmostEqual(m.sig_asf, 450.0)
        self.assertAlmostEqual(m.sig_sas, 300.0)
        self.assertAlmostEqual(m.sig_saf, 200.0)
        self.assertAlmostEqual(m.epsl, 0.05)
        self.assertAlmostEqual(m.alpha, 0.12)
        self.assertAlmostEqual(m.ymrt, 25000.0)

    def test_numeric_spellings_reach_the_same_handler(self):
        for kw in ("MAT_030", "MAT_30"):
            state = _dispatch(
                "*KEYWORD\n*" + kw + "\n"
                + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
                + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12, 25000.0) + "\n"
                "*END\n")
            self.assertIn(30, state.mat_shape_memory, kw)
            self.assertEqual(state.skipped_keywords, [], kw)

    def test_fused_mid_and_density_are_sliced_fixed_width(self):
        # "        306.4500E-9" — RO fills its whole 10-char field and glues to
        # MID; a free split would shift every value (the *MAT_187 trap).
        state = _dispatch("*KEYWORD\n*MAT_SHAPE_MEMORY\n"
                          "        306.4500E-9   50000.0      0.33\n"
                          + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12,
                                 25000.0) + "\n*END\n")
        m = state.mat_shape_memory[30]
        self.assertAlmostEqual(m.rho, 6.45e-9)
        self.assertAlmostEqual(m.e, 50000.0)

    def test_optional_card_3_is_claimed_by_row_index(self):
        state = _dispatch("*KEYWORD\n*MAT_SHAPE_MEMORY\n"
                          + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
                          + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12,
                                 25000.0) + "\n"
                          + _row(77, 88) + "\n*END\n")
        m = state.mat_shape_memory[30]
        self.assertEqual((m.lcid_as, m.lcid_sa), (77, 88))

    def test_absent_card_3_does_not_swallow_the_next_keyword(self):
        state = _dispatch("*KEYWORD\n" + SMA
                          + "*MAT_ELASTIC\n" + _row(9, 7.8e-9, 210000.0, 0.3)
                          + "\n*END\n")
        self.assertIn(30, state.mat_shape_memory)
        self.assertEqual(state.mat_shape_memory[30].lcid_as, 0)
        self.assertIn(9, state.mat_elastic)
        self.assertAlmostEqual(state.mat_elastic[9].E, 210000.0)

    def test_lcss_lcssc_idpp_are_warn_dropped_by_name(self):
        state = _dispatch("*KEYWORD\n*MAT_SHAPE_MEMORY\n"
                          + _row(30, "6.4500E-9", 50000.0, 0.33, 31, 32, 1)
                          + "\n"
                          + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12,
                                 25000.0) + "\n*END\n")
        m = state.mat_shape_memory[30]
        self.assertEqual((m.lcss, m.lcssc, m.idpp), (31, 32, 1))
        w = " ".join(state.warnings)
        self.assertIn("LCSS=31", w)
        self.assertIn("LCSSC=32", w)
        self.assertIn("IDPP=1", w)

    def test_negative_transformation_stress_is_a_curve_id_and_warn_skips(self):
        state = _dispatch("*KEYWORD\n*MAT_SHAPE_MEMORY\n"
                          + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
                          + _row(-11.0, -12.0, 300.0, 200.0, 0.05, 0.12,
                                 25000.0) + "\n*END\n")
        self.assertNotIn(30, state.mat_shape_memory)
        w = " ".join(state.warnings)
        self.assertIn("SIG_ASS", w)
        self.assertIn("curve 11", w)
        self.assertIn("SIG_ASF", w)
        self.assertIn("curve 12", w)


class ShapeMemoryEmitTests(unittest.TestCase):
    def test_law71_card_is_column_exact(self):
        _r, starter = _convert(HEX.replace("{MAT}", SMA).replace("{EXTRA}", ""))
        body = _block(starter, "/MAT/LAW71/30")
        self.assertIsNotNone(body, starter)
        self.assertEqual(body[0], "NiTi superelastic")
        self.assertEqual(body[1], "#              RHO_I")
        self.assertEqual(body[2], "        6.450000E-09")
        self.assertEqual(
            body[3],
            "#                  E                  Nu              E_mart")
        self.assertEqual(body[4],
                         "               50000                0.33"
                         "               25000")
        self.assertEqual(
            body[5],
            "#            sig_sas             sig_fas             sig_ssa"
            "             sig_fsa               alpha")
        self.assertEqual(body[6],
                         "                 400                 450"
                         "                 300                 200"
                         f"{ALPHA_ON_CARD:>20}")
        self.assertEqual(
            body[7],
            "#               EpsL                 CAS                 CSA"
            "                TSAS                TFAS")
        self.assertEqual(body[8],
                         "                0.05                   0"
                         "                   0                   0"
                         "                   0")
        self.assertEqual(
            body[9],
            "#               TSSA                TFSA                  CP"
            "                TINI")
        self.assertEqual(body[10],
                         "                   0                   0"
                         "                   0                   0")

    def test_alpha_carries_the_sqrt_two_thirds_factor(self):
        _r, starter = _convert(HEX.replace("{MAT}", SMA).replace("{EXTRA}", ""))
        row = _block(starter, "/MAT/LAW71/30")[6]
        alpha = float(_fields(row)[4])
        self.assertAlmostEqual(alpha, math.sqrt(2.0 / 3.0) * 0.12, places=10)
        # ...and it is NOT the raw LS-DYNA value.
        self.assertNotAlmostEqual(alpha, 0.12, places=4)

    def test_blank_ymrt_emits_a_zero_e_mart_not_a_fabricated_modulus(self):
        # E_mart = 0 is the reader's "single-modulus" option
        # (hm_read_mat71.F:176 IF (EMART /= ZERO) EFLAG = 1), which is exactly
        # LS-DYNA's "YMRT defaults to the austenite modulus".
        sma0 = ("*MAT_SHAPE_MEMORY\n"
                + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
                + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12) + "\n")
        _r, starter = _convert(HEX.replace("{MAT}", sma0).replace("{EXTRA}", ""))
        self.assertEqual(_block(starter, "/MAT/LAW71/30")[4],
                         "               50000                0.33"
                         "                   0")

    def test_temperature_terms_are_left_blank(self):
        _r, starter = _convert(HEX.replace("{MAT}", SMA).replace("{EXTRA}", ""))
        body = _block(starter, "/MAT/LAW71/30")
        self.assertEqual([f for f in _fields(body[8])[1:]], ["0"] * 4)
        self.assertEqual([f for f in _fields(body[10])], ["0"] * 4)

    def test_untitled_material_gets_the_default_title(self):
        sma = ("*MAT_030\n" + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
               + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12, 25000.0) + "\n")
        _r, starter = _convert(HEX.replace("{MAT}", sma).replace("{EXTRA}", ""))
        self.assertEqual(_block(starter, "/MAT/LAW71/30")[0], "MAT_30")

    def test_mesh_survives_and_the_part_keeps_its_material(self):
        _r, starter = _convert(HEX.replace("{MAT}", SMA).replace("{EXTRA}", ""))
        self.assertIn("/BRICK/1", starter)
        self.assertIn("/PART/1", starter)
        part = _data_rows(starter, "/PART/1")
        # /PART is "title" then "prop_ID mat_ID subset_ID" in I10 columns.
        self.assertEqual(int(part[1][10:20]), 30)
        self.assertNotIn("*MAT_SHAPE_MEMORY", " ".join(_r.skipped_keywords))


class ShapeMemoryGuardTests(unittest.TestCase):
    def _warns(self, sig_ass, sig_asf, sig_sas, sig_saf, alpha=0.12,
               e=50000.0, ymrt=25000.0):
        mat = ("*MAT_SHAPE_MEMORY\n"
               + _row(30, "6.4500E-9", e, 0.33) + "\n"
               + _row(sig_ass, sig_asf, sig_sas, sig_saf, 0.05, alpha, ymrt)
               + "\n")
        r, _s = _convert(HEX.replace("{MAT}", mat).replace("{EXTRA}", ""))
        return " ".join(r.warnings)

    def test_forward_ordering_violation_names_error_1122(self):
        w = self._warns(450.0, 400.0, 300.0, 200.0)
        self.assertIn("ERROR 1122", w)

    def test_reverse_ordering_violation_names_error_1123(self):
        w = self._warns(400.0, 450.0, 200.0, 300.0)
        self.assertIn("ERROR 1123", w)

    def test_alpha_out_of_range_names_error_1124(self):
        w = self._warns(400.0, 450.0, 300.0, 200.0, alpha=1.5)
        self.assertIn("ERROR 1124", w)

    def test_valid_card_raises_none_of_the_three(self):
        w = self._warns(400.0, 450.0, 300.0, 200.0)
        for eid in ("ERROR 1122", "ERROR 1123", "ERROR 1124"):
            self.assertNotIn(eid, w)

    def test_martensite_stiffer_than_austenite_is_flagged(self):
        w = self._warns(400.0, 450.0, 300.0, 200.0, e=25000.0, ymrt=50000.0)
        self.assertIn("martensite modulus", w)

    def test_beam_part_draws_the_type18_only_warning(self):
        # LAW71 declares BEAM_INTEGRATED only (hm_read_mat71.F:247-251), so a
        # /PROP/BEAM (TYPE3) part on it is starter ERROR 3047 + 745.
        deck = (
            "*KEYWORD\n"
            "*NODE\n"
            "         1             0.0             0.0             0.0\n"
            "         2            10.0             0.0             0.0\n"
            "         3             0.0            10.0             0.0\n"
            "*ELEMENT_BEAM\n"
            + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3)) + "\n"
            "*PART\n"
            "bar\n" + _row(1, 1, 30) + "\n"
            "*SECTION_BEAM\n"
            + _row(1, 1) + "\n"
            + _row(4.0, 4.0, 4.0, 4.0) + "\n"
            + SMA
            + "*CONTROL_TERMINATION\n     0.001\n*END\n")
        r, _s = _convert(deck)
        w = " ".join(r.warnings)
        self.assertIn("LAW71", w)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_MUSCLE (156) and *MAT_SPRING_MUSCLE (S15) → /PROP/TYPE46
# ═════════════════════════════════════════════════════════════════════════════

#: One 50-long truss on part 1, plus an orientation node the truss does not use.
#: Every muscle constant a DIFFERENT number so a slot swap is detectable:
#: RO 1e-9, SNO 1.25, SRM 10, PIS 0.3, SSM 0.15, CER 5, DMP 2, A 25.
#:   Mass    = RO*A/SNO        = 1e-9*25/1.25   = 2e-8
#:   Vel_max = SRM*L0/SNO      = 10*50/1.25     = 400
#:   Force   = PIS*A           = 0.3*25         = 7.5
#:   Damp    = DMP*A*SNO^2/L0  = 2*25*1.5625/50 = 1.5625
#:   Scale_v = SFR/SNO         = 1/1.25         = 0.8
MUSCLE156 = (
    "*KEYWORD\n"
    "*NODE\n"
    "         1             0.0             0.0             0.0\n"
    "         2            50.0             0.0             0.0\n"
    "         3             0.0            10.0             0.0\n"
    "*ELEMENT_BEAM\n"
    + "".join(f"{v:>8}" for v in (7, 1, 1, 2, 3)) + "\n"
    "*PART\n"
    "musclebeam\n"
    + _row(1, 1, 1) + "\n"
    "*SECTION_BEAM\n"
    + _row(1, 3) + "\n"
    + _row(25.0) + "\n"
    "*MAT_MUSCLE\n"
    + _row(1, "1.0000E-9", 1.25, 10.0, 0.3, 0.15, 5.0, 2.0) + "\n"
    "{CARD2}"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.001\n"
    "*END\n"
)

#: One 10-long discrete spring on part 2. L0 10 = the element length, VMAX 100,
#: SV 0.8, A 0.5, FMAX 1000, LMAX 1.5, KSH 3.
MUSCLE_S15 = (
    "*KEYWORD\n"
    "*NODE\n"
    "         1             0.0             0.0             0.0\n"
    "         2            10.0             0.0             0.0\n"
    "*ELEMENT_DISCRETE\n"
    + "".join(f"{v:>8}" for v in (11, 2, 1, 2, 0)) + f"{0.0:>16}" + "\n"
    "*PART\n"
    "musclespring\n"
    + _row(2, 2, 5) + "\n"
    "*SECTION_DISCRETE\n"
    + _row(2) + "\n"
    "*MAT_SPRING_MUSCLE\n"
    "{CARD1}"
    "{CARD2}"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.001\n"
    "*END\n"
)


def _muscle156(card2="       1.0       1.0       1.0       1.0       1.0\n",
               extra=""):
    return MUSCLE156.replace("{CARD2}", card2).replace("{EXTRA}", extra)


def _muscle_s15(tl=1.0, tv=1.0, fpe=1.0, l0=10.0, sv=0.8, extra=""):
    return (MUSCLE_S15
            .replace("{CARD1}",
                     _row(5, l0, 100.0, sv, 0.5, 1000.0, tl, tv) + "\n")
            .replace("{CARD2}", _row(fpe, 1.5, 3.0) + "\n")
            .replace("{EXTRA}", extra))


class MuscleParseTests(unittest.TestCase):
    def test_mat_156_card_fields_land_in_their_own_slots(self):
        state = _dispatch(_muscle156(
            card2=_row(0.5, 1.0, -3, -4, 0.0) + "\n"))
        m = state.mat_muscle[1]
        self.assertAlmostEqual(m.rho, 1.0e-9)
        self.assertAlmostEqual(m.sno, 1.25)
        self.assertAlmostEqual(m.srm, 10.0)
        self.assertAlmostEqual(m.pis, 0.3)
        self.assertAlmostEqual(m.ssm, 0.15)
        self.assertAlmostEqual(m.cer, 5.0)
        self.assertAlmostEqual(m.dmp, 2.0)
        self.assertAlmostEqual(m.alm, 0.5)
        self.assertEqual(m.alm_lcid, 0)
        # SVS/SVR negative = curve id; the scalar stays at the manual's 1.0.
        self.assertEqual((m.svs_lcid, m.svr_lcid), (3, 4))
        self.assertAlmostEqual(m.svs, 1.0)
        self.assertAlmostEqual(m.svr, 1.0)

    def test_mat_156_positive_scale_cells_are_the_constant_one(self):
        # "GE.0.0: Constant value of 1.0 is used" — the number itself is
        # DISCARDED (mat_156.cfg:45/49/53).
        state = _dispatch(_muscle156(card2=_row(0.5, 7.0, 8.0, 9.0, 0.0) + "\n"))
        m = state.mat_muscle[1]
        self.assertAlmostEqual(m.sfr, 7.0)   # kept raw; the writer reads 1.0
        self.assertEqual((m.svs_lcid, m.svr_lcid), (0, 0))

    def test_mat_s15_blank_defaults_are_not_zero(self):
        deck = ("*KEYWORD\n*MAT_SPRING_MUSCLE\n" + _row(5) + "\n"
                + _row() + "\n*END\n")
        m = _dispatch(deck).mat_spring_muscle[5]
        self.assertAlmostEqual(m.l0, 1.0)
        self.assertAlmostEqual(m.sv, 1.0)
        self.assertAlmostEqual(m.tl, 1.0)
        self.assertAlmostEqual(m.tv, 1.0)
        self.assertAlmostEqual(m.fpe, 0.0)

    def test_mat_s15_card_fields_land_in_their_own_slots(self):
        state = _dispatch(_muscle_s15(tl=-5, tv=-6, fpe=0.0))
        m = state.mat_spring_muscle[5]
        self.assertAlmostEqual(m.l0, 10.0)
        self.assertAlmostEqual(m.vmax, 100.0)
        self.assertAlmostEqual(m.sv, 0.8)
        self.assertAlmostEqual(m.a, 0.5)
        self.assertAlmostEqual(m.fmax, 1000.0)
        self.assertEqual((m.tl_lcid, m.tv_lcid), (5, 6))
        self.assertAlmostEqual(m.lmax, 1.5)
        self.assertAlmostEqual(m.ksh, 3.0)

    def test_numeric_spellings_reach_the_same_handlers(self):
        for kw, reg in (("MAT_156", "mat_muscle"),
                        ("MAT_S15", "mat_spring_muscle")):
            state = _dispatch("*KEYWORD\n*" + kw + "\n" + _row(9) + "\n"
                              + _row() + "\n*END\n")
            self.assertIn(9, getattr(state, reg), kw)
            self.assertEqual(state.skipped_keywords, [], kw)


class Muscle156EmitTests(unittest.TestCase):
    def setUp(self):
        self._r, self.starter = _convert(_muscle156())

    def test_prop_type46_card_is_column_exact(self):
        header = [ln for ln in self.starter.splitlines()
                  if ln.startswith("/PROP/TYPE46/")]
        self.assertEqual(len(header), 1, self.starter)
        body = _block(self.starter, header[0])
        self.assertEqual(body[0], "musclebeam")
        self.assertEqual(
            body[1],
            "#               Mass           Stiffness             Vel_max"
            "               Force                  Xk")
        self.assertEqual(body[2],
                         "        2.000000E-08                   0"
                         "                 400                 7.5"
                         "                   0")
        self.assertEqual(
            body[3],
            "#  fct_id1   fct_id2   fct_id3   fct_id4               Idens")
        # Idens sits in columns 51-60, NOT 41-50: ten blank columns first.
        self.assertEqual(body[4][40:50], " " * 10)
        self.assertEqual(int(body[4][50:60]), 0)
        self.assertEqual(body[5], "#               Damp      Epsi")
        self.assertEqual(body[6], "              1.5625         0")
        self.assertEqual(
            body[7],
            "#            Scale_t             Scale_x             Scale_v"
            "             Scale_F")
        self.assertEqual(body[8],
                         "                   0                   0"
                         "                 0.8                 7.5")

    def test_every_function_slot_is_non_zero(self):
        # GET_U_FUNC(0) returns 0 and the whole active product collapses to
        # zero at 0 starter errors (ruser46.F:207, measured on four decks).
        body = _block(self.starter, "/PROP/TYPE46/"
                      + str(_prop_id(self.starter)))
        row = body[4]
        for k in range(4):
            self.assertNotEqual(int(row[k * 10:(k + 1) * 10]), 0,
                                f"fct_id{k + 1} is 0")

    def test_beam_becomes_a_spring_and_no_beam_or_prop_beam_is_written(self):
        self.assertIn("/SPRING/1", self.starter)
        self.assertNotIn("/BEAM/1", self.starter)
        self.assertNotIn("/PROP/BEAM/1", self.starter)
        rows = _data_rows(self.starter, "/SPRING/1")
        self.assertEqual(rows, ["         7         1         2"])

    def test_exactly_one_part_card(self):
        self.assertEqual(_headers(self.starter, "/PART/1"), ["/PART/1"])

    def test_element_registries_record_a_spring_never_a_beam(self):
        # #122: state.beam_elem_ids / spring_elem_ids answer "which kind of
        # element does the EMITTED deck hold?" — a *SET_BEAM naming a muscle
        # element must reach /TH/SPRING, and a /TH/BEAM on it is ERROR 69.
        from k2rad.writer import build_starter
        state = _dispatch(_muscle156())
        build_starter(state)
        self.assertIn(7, state.spring_elem_ids)
        self.assertNotIn(7, state.beam_elem_ids)
        self.assertIn(7, state.muscle_spring_eids)

    def test_no_mat_card_is_written_for_the_muscle_material(self):
        self.assertNotIn("/MAT/LAW", self.starter)
        part = _data_rows(self.starter, "/PART/1")
        self.assertEqual(int(part[1][10:20]), 0)     # mat_ID 0

    def test_svs_curve_abscissa_is_lambda_over_sno_minus_one(self):
        extra = ("*DEFINE_CURVE\n" + _row(3) + "\n"
                 + _row16(1.0, 0.0) + "\n" + _row16(1.25, 0.8) + "\n"
                 + _row16(1.5, 0.0) + "\n")
        _r, starter = _convert(_muscle156(
            card2=_row(1.0, 1.0, -3, 1.0, 1.0) + "\n", extra=extra))
        fid = _funct_named(starter, "MatL156_SVS_1")
        pts = _funct_points(starter, fid)
        self.assertEqual([round(x, 10) for x, _y in pts], [-0.2, 0.0, 0.2])
        self.assertEqual([y for _x, y in pts], [0.0, 0.8, 0.0])

    def test_svr_curve_is_used_verbatim(self):
        # Vel_max*Scale_v is built so the Radioss abscissa IS eps_bar_dot.
        extra = ("*DEFINE_CURVE\n" + _row(4) + "\n"
                 + _row16(-1.0, 1.6) + "\n" + _row16(1.0, 0.4) + "\n")
        _r, starter = _convert(_muscle156(
            card2=_row(1.0, 1.0, 1.0, -4, 1.0) + "\n", extra=extra))
        body = _block(starter, "/PROP/TYPE46/"
                      + str(_prop_id(starter)))
        self.assertEqual(int(body[4][20:30]), 4)

    def test_ssp_exponential_matches_the_manual(self):
        _r, starter = _convert(_muscle156(
            card2=_row(1.0, 1.0, 1.0, 1.0, 0.0) + "\n"))
        fid = _funct_named(starter, "MatL156_SSP_1")
        pts = _funct_points(starter, fid)
        self.assertEqual(len(pts), 102)
        # eps = -1 and eps = 0 both give h = 0; the abscissa is
        # (1+eps)/SNO - 1, so -1 -> -1 and 0 -> 1/1.25 - 1 = -0.2.
        self.assertAlmostEqual(pts[0][0], -1.0)
        self.assertAlmostEqual(pts[0][1], 0.0)
        self.assertAlmostEqual(pts[1][0], -0.2)
        self.assertAlmostEqual(pts[1][1], 0.0)
        # eps = 1 -> h = (exp(CER/SSM) - 1)/(exp(CER) - 1), CER 5, SSM 0.15
        want = (math.exp(5.0 / 0.15) - 1.0) / (math.exp(5.0) - 1.0)
        self.assertAlmostEqual(pts[-1][0], 2.0 / 1.25 - 1.0)
        self.assertAlmostEqual(pts[-1][1] / want, 1.0, places=8)

    def test_ssp_positive_gives_a_constant_zero_passive_function(self):
        _r, starter = _convert(_muscle156(
            card2=_row(1.0, 1.0, 1.0, 1.0, 3.0) + "\n"))
        fid = _funct_named(starter, "MatL156_SSP_1_zero")
        self.assertEqual([y for _x, y in _funct_points(starter, fid)], [0.0, 0.0])

    def test_ssp_table_is_warn_dropped_by_name(self):
        extra = ("*DEFINE_TABLE\n" + _row(9) + "\n" + _row16(0.0) + _row(3)
                 + "\n*DEFINE_CURVE\n" + _row(3) + "\n"
                 + _row16(1.0, 0.0) + "\n" + _row16(1.5, 1.0) + "\n")
        r, _s = _convert(_muscle156(
            card2=_row(1.0, 1.0, 1.0, 1.0, -9) + "\n", extra=extra))
        w = " ".join(r.warnings)
        self.assertIn("SSP names TABLE 9", w)

    def test_sfr_curve_is_warn_dropped_by_name(self):
        extra = ("*DEFINE_CURVE\n" + _row(8) + "\n"
                 + _row16(0.0, 1.0) + "\n" + _row16(1.0, 1.0) + "\n")
        r, starter = _convert(_muscle156(
            card2=_row(1.0, -8, 1.0, 1.0, 1.0) + "\n", extra=extra))
        self.assertIn("SFR is stated as curve 8", " ".join(r.warnings))
        # Scale_v falls back to 1/SNO.
        body = _block(starter, "/PROP/TYPE46/" + str(_prop_id(starter)))
        self.assertAlmostEqual(float(_fields(body[8])[2]), 0.8)

    def test_missing_area_skips_the_part_and_says_why(self):
        deck = _muscle156().replace(_row(25.0) + "\n", _row(0.0) + "\n")
        r, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE46", starter)
        self.assertIn("states no cross-section AREA", " ".join(r.warnings))


class MuscleS15EmitTests(unittest.TestCase):
    def setUp(self):
        self._r, self.starter = _convert(_muscle_s15(fpe=0.0))

    def test_prop_type46_card_is_column_exact(self):
        body = _block(self.starter,
                      "/PROP/TYPE46/" + str(_prop_id(self.starter)))
        self.assertEqual(body[0], "musclespring")
        self.assertEqual(body[2],
                         "                   0                   0"
                         "                 100                1000"
                         "                   0")
        self.assertEqual(body[6], "                   0         1")   # Damp, Epsi
        self.assertEqual(body[8],
                         "                   0                   0"
                         "                   0                1000")

    def test_no_mass_is_invented(self):
        body = _block(self.starter,
                      "/PROP/TYPE46/" + str(_prop_id(self.starter)))
        self.assertEqual(_fields(body[2])[0], "0")
        self.assertIn("carries NO MASS", " ".join(self._r.warnings))

    def test_tl_abscissa_is_length_ratio_times_l0_minus_the_element_length(self):
        extra = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + _row16(0.5, 0.0) + "\n" + _row16(1.0, 1.0) + "\n"
                 + _row16(1.5, 0.3) + "\n")
        _r, starter = _convert(_muscle_s15(tl=-5, fpe=1.0, extra=extra))
        pts = _funct_points(starter, _funct_named(starter, "MatS15_TL_5"))
        self.assertEqual([round(x, 10) for x, _y in pts], [-5.0, 0.0, 5.0])
        self.assertEqual([y for _x, y in pts], [0.0, 1.0, 0.3])

    def test_tv_abscissa_is_denormalised_by_vmax_times_sv(self):
        extra = ("*DEFINE_CURVE\n" + _row(6) + "\n"
                 + _row16(-1.0, 1.8) + "\n" + _row16(0.0, 1.0) + "\n"
                 + _row16(1.0, 0.5) + "\n")
        _r, starter = _convert(_muscle_s15(tv=-6, fpe=1.0, extra=extra))
        pts = _funct_points(starter, _funct_named(starter, "MatS15_TV_5"))
        # VMAX * SV = 100 * 0.8 = 80
        self.assertEqual([round(x, 10) for x, _y in pts], [-80.0, 0.0, 80.0])

    def test_sv_curve_is_warn_dropped_by_name(self):
        extra = ("*DEFINE_CURVE\n" + _row(7) + "\n"
                 + _row16(0.0, 1.0) + "\n" + _row16(1.0, 1.0) + "\n"
                 + "*DEFINE_CURVE\n" + _row(6) + "\n"
                 + _row16(-1.0, 1.8) + "\n" + _row16(1.0, 0.5) + "\n")
        r, starter = _convert(_muscle_s15(tv=-6, fpe=1.0, sv=-7,
                                          extra=extra))
        self.assertIn("SV is stated as curve 7", " ".join(r.warnings))
        pts = _funct_points(starter, _funct_named(starter, "MatS15_TV_5"))
        self.assertEqual([round(x, 10) for x, _y in pts], [-100.0, 100.0])

    def test_fpe_exponential_matches_the_manual(self):
        pts = _funct_points(self.starter,
                            _funct_named(self.starter, "MatS15_FPE_5"))
        self.assertEqual(len(pts), 102)
        # abscissa = (1+u)*L0 - l_init = u*10  (L0 = the element length = 10)
        self.assertAlmostEqual(pts[0][0], -10.0)
        self.assertAlmostEqual(pts[-1][0], 10.0)
        want = (math.exp(3.0 / 1.5) - 1.0) / (math.exp(3.0) - 1.0)
        self.assertAlmostEqual(pts[-1][1], want)
        self.assertEqual(pts[1][1], 0.0)          # u = 0 -> f_PE = 0

    def test_discrete_writer_does_not_also_claim_the_part(self):
        self.assertEqual(_headers(self.starter, "/PART/2"), ["/PART/2"])
        self.assertNotIn("/PROP/TYPE4/", self.starter)
        rows = _data_rows(self.starter, "/SPRING/2")
        self.assertEqual(rows, ["        11         1         2"])

    def test_l0_mismatch_is_warned_by_name(self):
        r, _s = _convert(_muscle_s15(fpe=0.0, l0=7.0))
        self.assertIn("states L0 = 7", " ".join(r.warnings))


class MuscleTimeHistoryTests(unittest.TestCase):
    def test_set_beam_history_of_a_muscle_beam_routes_to_th_spring(self):
        extra = ("*SET_BEAM_LIST\n" + _row(77) + "\n" + _row(7) + "\n"
                 "*DATABASE_HISTORY_BEAM_SET\n" + _row(77) + "\n"
                 "*DATABASE_BINARY_D3PLOT\n" + _row(1.0e-4) + "\n")
        _r, starter = _convert(_muscle156(extra=extra))
        self.assertIn("/TH/SPRING", starter)
        self.assertNotIn("/TH/BEAM", starter)

    def test_deforc_leaves_the_all_zero_muscle_channel_out(self):
        extra = "*DATABASE_DEFORC\n" + _row(1.0e-5) + "\n"
        r, starter = _convert(_muscle_s15(fpe=0.0, extra=extra))
        self.assertNotIn("/TH/SPRING", starter)
        self.assertIn("no converted *ELEMENT_DISCRETE connector",
                      " ".join(r.warnings))


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / *INCLUDE_TRANSFORM coverage
# ═════════════════════════════════════════════════════════════════════════════

class DispatchAndOffsetCoverageTests(unittest.TestCase):
    def test_parser_and_offset_tables_cover_the_same_spellings(self):
        # ONE source (#116): every spelling the handler reads must also be
        # offsettable, or an *INCLUDE_TRANSFORM keeps its original MID/LCID
        # while the rest of the include moves.
        self.assertTrue(RARE_MATERIAL_KEYWORDS)
        for kw in RARE_MATERIAL_KEYWORDS:
            self.assertIn(kw, HANDLERS, f"{kw} has no handler")
            self.assertIn(kw, _OFFSET_SPECS, f"{kw} has no offset spec")

    def test_title_option_is_stripped_by_the_parser(self):
        state = _dispatch("*KEYWORD\n" + SMA + "*END\n")
        self.assertEqual(state.mat_shape_memory[30].title, "NiTi superelastic")
        self.assertEqual(state.skipped_keywords, [])


class IncludeTransformOffsetTests(unittest.TestCase):
    def _dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def _offset(self, inner: str, **offs) -> str:
        """Run *inner* through an *INCLUDE_TRANSFORM and return the offset
        text of the included file as the parser saw it."""
        d = self._dir()
        with open(os.path.join(d, "inc.k"), "w") as fh:
            fh.write("*KEYWORD\n" + inner + "*END\n")
        cells = [offs.get(k, 0) for k in
                 ("idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff",
                  "iddoff", "idroff")]
        with open(os.path.join(d, "main.k"), "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\ninc.k\n"
                     + _row(*cells) + "\n*END\n")
        blocks = parse_k_file(os.path.join(d, "main.k"))
        for b in blocks:
            if b.keyword in RARE_MATERIAL_KEYWORDS:
                return "\n".join(b.raw)
        return ""

    def test_mid_moves_with_idmoff_and_curves_with_idfoff(self):
        inner = ("*MAT_SHAPE_MEMORY\n"
                 + _row(30, "6.4500E-9", 50000.0, 0.33, 31, 32) + "\n"
                 + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12, 25000.0) + "\n"
                 + _row(77, 88) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1030)
        self.assertEqual(int(out[0][40:50]), 531)     # LCSS
        self.assertEqual(int(out[0][50:60]), 532)     # LCSSC
        self.assertEqual(int(out[2][0:10]), 577)      # LCID_AS
        self.assertEqual(int(out[2][10:20]), 588)     # LCID_SA
        # The four POSITIVE transformation stresses are physics, never ids.
        self.assertAlmostEqual(float(out[1][0:10]), 400.0)
        self.assertAlmostEqual(float(out[1][10:20]), 450.0)

    def test_negative_transformation_stress_moves_sign_preserved(self):
        inner = ("*MAT_SHAPE_MEMORY\n"
                 + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
                 + _row(-11.0, -12.0, 300.0, 200.0, 0.05, 0.12, 25000.0) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(float(out[1][0:10])), -511)
        self.assertEqual(int(float(out[1][10:20])), -512)
        self.assertAlmostEqual(float(out[1][20:30]), 300.0)

    def test_no_offsets_leaves_the_card_untouched(self):
        inner = ("*MAT_SHAPE_MEMORY\n"
                 + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
                 + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.12, 25000.0) + "\n")
        self.assertEqual(self._offset(inner), inner.split("\n", 1)[1].rstrip())


# ═════════════════════════════════════════════════════════════════════════════
# Byte-identity: a deck with none of these keywords must not move
# ═════════════════════════════════════════════════════════════════════════════

PLAIN = HEX.replace("{MAT}",
                    "*MAT_ELASTIC\n" + _row(30, 7.8e-9, 210000.0, 0.3) + "\n"
                    ).replace("{EXTRA}", "")


class ByteIdentityTests(unittest.TestCase):
    def test_deck_without_the_batch_keywords_is_unchanged(self):
        _r, a = _convert(PLAIN)
        _r2, b = _convert(PLAIN)
        self.assertEqual(a, b)
        self.assertNotIn("/MAT/LAW71", a)
        self.assertNotIn("/PROP/TYPE46", a)
        self.assertNotIn("/THERM_STRESS", a)
        self.assertNotIn("/HEAT/MAT", a)
        self.assertNotIn("/INITEMP", a)
        self.assertNotIn("/IMPTEMP", a)


if __name__ == "__main__":
    unittest.main()
