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


def _ids_of_group(starter: str, header: str):
    """The integer ids listed in a /GRNOD-style block (title line skipped)."""
    body = _block(starter, header)
    ids = []
    for ln in body[1:]:
        if ln.startswith("#"):
            continue
        ids.extend(int(t) for t in ln.split() if t.lstrip("-").isdigit())
    return ids


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

#: ALPHA is copied 1:1 — LS-DYNA's ALPHA and Radioss's ``alpha`` are the SAME
#: quantity in the SAME normalisation (Vol II R17 p.2-307 Remark 1 vs
#: sigeps71.F:171/245/277), so the card's %.10G field is just "0.12".
ALPHA_ON_CARD = "0.12"


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

    def test_alpha_is_copied_one_to_one(self):
        # LS-DYNA Vol II R17 p.2-307 Remark 1 states
        #     alpha = sqrt(2/3)*(-sig_AS- - sig_AS+)/(-sig_AS- + sig_AS+),
        #     -sqrt(2/3) < alpha < sqrt(2/3)
        # and p.2-309 Remark 2 the criterion F = ||t|| + 3*alpha*p >=
        # (alpha + sqrt(2/3))*sig_tr — term for term sigeps71.F:245/277
        # (RSAS = YLD_ASS*(SQDT+ALPHA), FS = SV + THREE*ALPHA*P). Same
        # normalisation on both sides, so no factor may be applied.
        _r, starter = _convert(HEX.replace("{MAT}", SMA).replace("{EXTRA}", ""))
        row = _block(starter, "/MAT/LAW71/30")[6]
        alpha = float(_fields(row)[4])
        self.assertAlmostEqual(alpha, 0.12, places=12)
        # ...and NOT dyna2rad's sqrt(2/3)*ALPHA (convertmats.cxx:1931), which
        # is 0.8164965809277260 * 0.12 = 0.09797958971132712.
        self.assertNotAlmostEqual(alpha, 0.09797958971132712, places=6)

    def test_emitted_alpha_reproduces_the_manual_compression_onset(self):
        # Hand-computed from the two closed forms, which must agree:
        #   LS-DYNA  |sig_AS-| = (ALPHA + sqrt(2/3))/(sqrt(2/3) - ALPHA)*sig_AS+
        #   Radioss   onset    = sig_sas*(sqrt(2/3) + alpha)/(sqrt(2/3) - alpha)
        # With sig_ASS = 400 and ALPHA = 0.1: 400*0.9164965809277260 /
        # 0.7164965809277260 = 511.6545... MPa (solver-measured 513.50, +0.36 %;
        # the sqrt(2/3)-shrunk card measured 490.52, -4.1 %).
        mat = ("*MAT_SHAPE_MEMORY\n"
               + _row(30, "6.4500E-9", 50000.0, 0.33) + "\n"
               + _row(400.0, 450.0, 300.0, 200.0, 0.05, 0.1, 25000.0) + "\n")
        _r, starter = _convert(HEX.replace("{MAT}", mat).replace("{EXTRA}", ""))
        fields = _fields(_block(starter, "/MAT/LAW71/30")[6])
        sig_sas, alpha = float(fields[0]), float(fields[4])
        sqdt = math.sqrt(2.0 / 3.0)
        self.assertAlmostEqual(sig_sas * (sqdt + alpha) / (sqdt - alpha),
                               511.6544057983016, places=8)

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

    def test_alpha_between_sqrt_two_thirds_and_one_is_flagged(self):
        # ALPHA = 0.9 is illegal in LS-DYNA (|alpha| < sqrt(2/3) = 0.8164966,
        # Vol II R17 p.2-307 Remark 1) AND is refused by the starter, because
        # the value is copied 1:1. A |ALPHA| > 1 guard would have missed it.
        w = self._warns(400.0, 450.0, 300.0, 200.0, alpha=0.9)
        self.assertIn("ERROR 1124", w)
        self.assertIn("0.8164966", w)

    def test_negative_alpha_below_the_bound_is_flagged_without_a_starter_guard(
            self):
        # hm_read_mat71.F:154-160 tests ALPHA > SQRT(TWO/THREE) only, so a
        # negative out-of-range value runs silently — the converter must say so.
        w = self._warns(400.0, 450.0, 300.0, 200.0, alpha=-0.9)
        self.assertIn("NEGATIVE ALPHA has no guard at all", w)

    def test_alpha_just_inside_the_bound_raises_nothing(self):
        w = self._warns(400.0, 450.0, 300.0, 200.0, alpha=0.81)
        self.assertNotIn("ERROR 1124", w)

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


def _muscle_s15(tl=1.0, tv=1.0, fpe=1.0, l0=10.0, sv=1.0, extra=""):
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
        r = _dispatch(_muscle156(card2=_row(0.5, 7.0, 8.0, 9.0, 0.0) + "\n"))
        m = r.mat_muscle[1]
        self.assertAlmostEqual(m.sfr, 1.0)
        self.assertAlmostEqual(m.svs, 1.0)
        self.assertAlmostEqual(m.svr, 1.0)
        self.assertEqual((m.svs_lcid, m.svr_lcid), (0, 0))
        # ALM on the same card is the CONTRAST — "GE.0.0: Constant value of
        # ALM is used" — so its 0.5 does survive.
        self.assertAlmostEqual(m.alm, 0.5)
        w = " ".join(r.warnings)
        self.assertIn("SFR=7", w)
        self.assertIn("Constant value of 1.0 is used", w)

    def test_scale_cell_of_exactly_one_or_zero_is_not_warned(self):
        r = _dispatch(_muscle156(card2=_row(0.5, 1.0, 0.0, 1.0, 0.0) + "\n"))
        self.assertNotIn("Constant value of 1.0 is used",
                         " ".join(r.warnings))

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
        self.assertAlmostEqual(m.sv, 1.0)
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
        # VMAX * SV = 100 * 1.0 = 100. SV is not a coefficient the deck can
        # choose: "SV ... GE.0.0: Constant value of 1.0 is used" (p.2-2096).
        self.assertEqual([round(x, 10) for x, _y in pts], [-100.0, 0.0, 100.0])

    def test_positive_sv_is_discarded_not_used_as_a_factor(self):
        extra = ("*DEFINE_CURVE\n" + _row(6) + "\n"
                 + _row16(-1.0, 1.8) + "\n" + _row16(0.0, 1.0) + "\n"
                 + _row16(1.0, 0.5) + "\n")
        r, starter = _convert(_muscle_s15(tv=-6, fpe=1.0, sv=0.8, extra=extra))
        pts = _funct_points(starter, _funct_named(starter, "MatS15_TV_5"))
        # 100*0.8 = 80 is the naive reading; LS-DYNA uses SV = 1.
        self.assertEqual([round(x, 10) for x, _y in pts], [-100.0, 0.0, 100.0])
        self.assertIn("SV=0.8", " ".join(r.warnings))

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

    def test_length_abscissa_uses_l0_and_the_mesh_length_separately(self):
        # The one place the transform beats dyna2rad's (L-1)*L0: with
        # L0 = 7 and a 10-long element, X = L*L0 - l_init, so
        # L = 0.5/1.0/1.5 -> -6.5 / -3.0 / +0.5. dyna2rad's (L-1)*L0 would
        # give -3.5 / 0 / +3.5 — the two coincide only at L0 == l_init, which
        # is why every other case here is blind to the difference.
        extra = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + _row16(0.5, 0.0) + "\n" + _row16(1.0, 1.0) + "\n"
                 + _row16(1.5, 0.3) + "\n")
        _r, starter = _convert(
            _muscle_s15(tl=-5, fpe=1.0, l0=7.0, extra=extra))
        pts = _funct_points(starter, _funct_named(starter, "MatS15_TL_5"))
        self.assertEqual([round(x, 10) for x, _y in pts], [-6.5, -3.0, 0.5])

    def test_zero_fmax_writes_a_zero_passive_function_not_a_unit_scale(self):
        # hm_read_prop46.F:179 turns Scale_F = 0 into ONE FORCE UNIT, and
        # ruser46.F:203 multiplies fct_id4 by it — a zero-strength muscle
        # would develop a fabricated passive force.
        deck = (MUSCLE_S15
                .replace("{CARD1}",
                         _row(5, 10.0, 100.0, 1.0, 0.5, 0.0, 1.0, 1.0) + "\n")
                .replace("{CARD2}", _row(0.0, 1.5, 3.0) + "\n")
                .replace("{EXTRA}", ""))
        r, starter = _convert(deck)
        prop = _block(starter, f"/PROP/TYPE46/{_prop_id(starter)}")
        self.assertIsNotNone(prop, starter)
        fct4 = int(_fields(prop[4], 10)[3])
        self.assertEqual({y for _x, y in _funct_points(starter, fct4)}, {0.0})
        self.assertIn("FMAX = 0", " ".join(r.warnings))


class MuscleTimeHistoryTests(unittest.TestCase):
    def test_set_beam_history_of_a_muscle_beam_is_dropped_not_zero_filled(self):
        # The muscle beam is a /SPRING in the emitted deck, so it must not go
        # to /TH/BEAM — but /TH/SPRING on a TYPE46 writes 15 channels of exact
        # zero (measured), so it must not go there either. The same rule
        # *DATABASE_DEFORC already applies, through the other door (#122).
        extra = ("*SET_BEAM_LIST\n" + _row(77) + "\n" + _row(7) + "\n"
                 "*DATABASE_HISTORY_BEAM_SET\n" + _row(77) + "\n"
                 "*DATABASE_BINARY_D3PLOT\n" + _row(1.0e-4) + "\n")
        r, starter = _convert(_muscle156(extra=extra))
        self.assertNotIn("/TH/SPRING", starter)
        self.assertNotIn("/TH/BEAM", starter)
        self.assertIn("15 channels of EXACT ZERO", " ".join(r.warnings))

    def test_a_non_muscle_beam_in_the_same_card_still_gets_its_group(self):
        # Only the TYPE46 ids are dropped; an ordinary beam in the same
        # *SET_BEAM keeps its /TH/BEAM group.
        extra = ("*PART\nrod\n" + _row(9, 9, 9) + "\n"
                 "*SECTION_BEAM\n" + _row(9, 1) + "\n"
                 + _row(4.0, 1.0, 1.0, 1.0) + "\n"
                 "*MAT_ELASTIC\n" + _row(9, "7.8500E-9", 210000.0, 0.3) + "\n"
                 "*ELEMENT_BEAM\n" + _row(31, 9, 1, 2, 3) + "\n"
                 "*SET_BEAM_LIST\n" + _row(77) + "\n" + _row(7, 31) + "\n"
                 "*DATABASE_HISTORY_BEAM_SET\n" + _row(77) + "\n"
                 "*DATABASE_BINARY_D3PLOT\n" + _row(1.0e-4) + "\n")
        _r, starter = _convert(_muscle156(extra=extra))
        self.assertIn("/TH/BEAM", starter)
        self.assertNotIn("/TH/SPRING", starter)

    def test_cross_section_plane_leaves_the_rerouted_beam_out(self):
        # The muscle beam runs 0 -> 50 along x and is a /SPRING in the emitted
        # deck, so its eid in a /GRBEAM/BEAM group matches nothing: starter
        # WARNING 534 "BEAM GROUP ... GROUP IS EMPTY", and the section loses
        # it either way. It is left out and the loss is named.
        extra = ("*DATABASE_CROSS_SECTION_PLANE\n"
                 + _row(0, 25.0, 0.0, 0.0, 26.0, 0.0, 0.0) + "\n"
                 "*DATABASE_SECFORC\n" + _row(1.0e-5) + "\n")
        r, starter = _convert(_muscle156(extra=extra))
        self.assertNotIn("/GRBEAM/BEAM", starter)
        self.assertIn("re-routes them to a SPRING connector",
                      " ".join(r.warnings))

    def test_deforc_leaves_the_all_zero_muscle_channel_out(self):
        extra = "*DATABASE_DEFORC\n" + _row(1.0e-5) + "\n"
        r, starter = _convert(_muscle_s15(fpe=0.0, extra=extra))
        self.assertNotIn("/TH/SPRING", starter)
        self.assertIn("no converted *ELEMENT_DISCRETE connector",
                      " ".join(r.warnings))


# ═════════════════════════════════════════════════════════════════════════════
# Thermal expansion + the temperature-driver foothold
# ═════════════════════════════════════════════════════════════════════════════

#: Two hexes on TWO parts (1 and 2) that SHARE material 1 — the corpus
#: carrier's shape, and what forces the material split.
THERMAL_MESH = (
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
    "         9            20.0             0.0             0.0\n"
    "        10            20.0            10.0             0.0\n"
    "        11            20.0             0.0            10.0\n"
    "        12            20.0            10.0            10.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "       2       2       2       9      10       3       6      11      12       7\n"
    "*PART\n"
    "blockA\n" + _row(1, 1, 1, 0, 0, 0, 0, "{TMID1}") + "\n"
    "*PART\n"
    "blockB\n" + _row(2, 1, 1, 0, 0, 0, 0, "{TMID2}") + "\n"
    "*SECTION_SOLID\n" + _row(1, 1) + "\n"
    "*MAT_ELASTIC\n" + _row(1, "7.8500E-9", 210000.0, 0.3) + "\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.001\n"
    "*END\n"
)

#: The corpus carrier's own card, verbatim: 8 fields with TREF, LCID 0, the
#: coefficient in MULT, and the MULTY/MULTZ = 1.0 cells that are IGNORED on an
#: isotropic material.
CARRIER_EXPANSION = ("*MAT_ADD_THERMAL_EXPANSION\n"
                     + _row(1, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0) + "\n")

#: The minimal driver that makes any of it do something.
DRIVER = ("*LOAD_THERMAL_LOAD_CURVE\n" + _row(7, 0) + "\n"
          "*DEFINE_CURVE\n" + _row(7) + "\n"
          + _row16(0.0, 20.0) + "\n" + _row16(1.0, 120.0) + "\n")


def _thermal(extra="", tmid1=0, tmid2=0):
    return (THERMAL_MESH.replace("{EXTRA}", extra)
            .replace("{TMID1}", str(tmid1)).replace("{TMID2}", str(tmid2)))


class ThermalParseTests(unittest.TestCase):
    def test_eight_field_layout_carries_tref(self):
        state = _dispatch("*KEYWORD\n" + CARRIER_EXPANSION + "*END\n")
        c = state.mat_add_thermal_expansion[0]
        self.assertEqual((c.pid, c.lcid), (1, 0))
        self.assertAlmostEqual(c.mult, 1.2e-5)
        self.assertEqual((c.lcidy, c.lcidz), (0, 0))
        self.assertAlmostEqual(c.multy, 1.0)
        self.assertAlmostEqual(c.multz, 1.0)
        self.assertTrue(c.has_tref)

    def test_seven_field_layout_has_no_tref_cell(self):
        # The nvh carrier's shape: LCID = 1, MULT = 0, no 8th cell at all.
        state = _dispatch("*KEYWORD\n*MAT_ADD_THERMAL_EXPANSION\n"
                          + _row(1, 1, 0.0, 0, 0.0, 0, 0.0) + "\n*END\n")
        c = state.mat_add_thermal_expansion[0]
        self.assertEqual((c.pid, c.lcid), (1, 1))
        self.assertFalse(c.has_tref)

    def test_negative_id_is_a_material_reference(self):
        state = _dispatch("*KEYWORD\n*MAT_ADD_THERMAL_EXPANSION\n"
                          + _row(-4, 0, 1.0e-5) + "\n*END\n")
        self.assertEqual(state.mat_add_thermal_expansion[0].pid, -4)

    def test_part_tmid_is_read(self):
        state = _dispatch(_thermal(tmid1=3, tmid2=0))
        self.assertEqual(state.parts[1].tmid, 3)
        self.assertEqual(state.parts[2].tmid, 0)

    def test_mat_thermal_isotropic_fields(self):
        state = _dispatch("*KEYWORD\n*MAT_THERMAL_ISOTROPIC\n"
                          + _row(3, "7.8500E-9", 0, 0.0, 0.0, 0.0) + "\n"
                          + _row("4.6000E+8", 40.0) + "\n*END\n")
        m = state.mat_thermal_isotropic[3]
        self.assertAlmostEqual(m.tro, 7.85e-9)
        self.assertAlmostEqual(m.hc, 4.6e8)
        self.assertAlmostEqual(m.tc, 40.0)


class ThermalEmitTests(unittest.TestCase):
    def test_constant_coefficient_becomes_a_synthesized_function(self):
        # Fct_ID_T = 0 + Fscale_y = alpha produces NO expansion at all
        # (alpha = FINTER(0,T)*Fscale = 0, measured on two code paths), which is
        # exactly the card dyna2rad writes.
        _r, starter = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/THERM_STRESS/MAT/")]
        self.assertEqual(len(header), 1, starter)
        body = _block(starter, header[0])
        self.assertEqual(body[0], "# Fct_ID_T            Fscale_y")
        fid = int(body[1][0:10])
        self.assertNotEqual(fid, 0)
        # Fscale_y is written as an explicit 1.0: MULT is already IN the
        # synthesized ordinate, so the cell must SAY "no further scaling"
        # rather than lean on hm_read_therm_stress.F90:135's 0 -> 1.0.
        self.assertEqual(float(body[1][10:30]), 1.0)
        pts = _funct_points(starter, fid)
        self.assertEqual([y for _x, y in pts], [1.2e-5, 1.2e-5])

    def test_curve_coefficient_keeps_the_curve_and_carries_mult(self):
        extra = ("*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 9, 2.5) + "\n"
                 "*DEFINE_CURVE\n" + _row(9) + "\n"
                 + _row16(0.0, 1.0e-5) + "\n" + _row16(1000.0, 1.0e-5) + "\n"
                 + DRIVER)
        _r, starter = _convert(_thermal(extra))
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/THERM_STRESS/MAT/")][0]
        body = _block(starter, header)
        self.assertEqual(int(body[1][0:10]), 9)
        self.assertAlmostEqual(float(body[1][10:30]), 2.5)

    def test_heat_mat_is_mandatory_and_column_exact(self):
        _r, starter = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/HEAT/MAT/")]
        self.assertEqual(len(header), 1)
        mid = int(header[0].rsplit("/", 1)[1])
        ts = [ln for ln in starter.splitlines()
              if ln.startswith("/THERM_STRESS/MAT/")][0]
        # The pair is mandatory: /THERM_STRESS without /HEAT/MAT is ERROR 1129.
        self.assertEqual(int(ts.rsplit("/", 1)[1]), mid)
        body = _block(starter, header[0])
        self.assertEqual(
            body[0],
            "#                 T0             RHO0_CP                  AS"
            "                  BS")
        self.assertEqual(
            body[2],
            "#                 T1                  AL                  BL"
            "               EFRAC")
        self.assertEqual(_fields(body[3])[3], "1.000000E-20")   # EFRAC off
        self.assertEqual(len(_fields(body[1])), 4)              # no Iform cell

    def test_shared_material_is_split_so_the_unnamed_part_never_expands(self):
        _r, starter = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        p1 = int(_data_rows(starter, "/PART/1")[1][10:20])
        p2 = int(_data_rows(starter, "/PART/2")[1][10:20])
        self.assertNotEqual(p1, p2)
        self.assertEqual(p2, 1)                     # the original mid
        ts = [int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
              if ln.startswith("/THERM_STRESS/MAT/")]
        self.assertEqual(ts, [p1])
        self.assertIn("/MAT/ELAST/1", starter)
        self.assertIn(f"/MAT/ELAST/{p1}", starter)
        self.assertIn("was SPLIT", " ".join(_r.warnings))

    def test_both_parts_named_needs_no_split(self):
        extra = (CARRIER_EXPANSION
                 + "*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(2, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0) + "\n"
                 + DRIVER)
        r, starter = _convert(_thermal(extra))
        self.assertEqual(int(_data_rows(starter, "/PART/1")[1][10:20]), 1)
        self.assertEqual(int(_data_rows(starter, "/PART/2")[1][10:20]), 1)
        self.assertEqual(len([ln for ln in starter.splitlines()
                              if ln.startswith("/THERM_STRESS/MAT/")]), 1)
        self.assertNotIn("was SPLIT", " ".join(r.warnings))

    def test_two_different_cards_on_one_mid_leave_no_orphan_material(self):
        # Both parts are named, with DIFFERENT coefficients, so the mid needs
        # two /THERM_STRESS/MATs — but cloning for BOTH would leave
        # /MAT/ELAST/1 referenced by no part at all.
        extra = (CARRIER_EXPANSION
                 + "*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(2, 0, "2.40000E-5", 0, 1.0, 0, 1.0, 0.0) + "\n"
                 + DRIVER)
        r, starter = _convert(_thermal(extra))
        p1 = int(_data_rows(starter, "/PART/1")[1][10:20])
        p2 = int(_data_rows(starter, "/PART/2")[1][10:20])
        self.assertNotEqual(p1, p2)
        used = {p1, p2}
        mats = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                if ln.startswith("/MAT/ELAST/")}
        self.assertEqual(mats, used)            # no orphan /MAT left behind
        ts = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
              if ln.startswith("/THERM_STRESS/MAT/")}
        self.assertEqual(ts, used)
        # ...and the warning names the parts that stayed, not a stale list.
        self.assertIn("keeps part(s) [2]", " ".join(r.warnings))

    def test_an_unresolvable_lcid_leaves_no_duplicate_material(self):
        extra = ("*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(1, 404, 1.0, 0, 1.0, 0, 1.0, 0.0) + "\n" + DRIVER)
        r, starter = _convert(_thermal(extra))
        self.assertEqual(
            [ln for ln in starter.splitlines()
             if ln.startswith("/MAT/ELAST/")], ["/MAT/ELAST/1"])
        self.assertEqual(int(_data_rows(starter, "/PART/1")[1][10:20]), 1)
        self.assertNotIn("/THERM_STRESS/MAT/", starter)
        self.assertIn("NOT split off for it either", " ".join(r.warnings))

    def test_two_tmids_on_one_material_are_named_not_silently_merged(self):
        extra = ("*MAT_THERMAL_ISOTROPIC\n" + _row(3, "7.8500E-9") + "\n"
                 + _row("4.6000E+8", 40.0) + "\n"
                 "*MAT_THERMAL_ISOTROPIC\n" + _row(4, "7.8500E-9") + "\n"
                 + _row("1.0000E+8", 5.0) + "\n" + DRIVER)
        # No expansion card: the pure-TMID path is what collects both parts,
        # and it has no card of its own to split the material on.
        r, starter = _convert(_thermal(extra, tmid1=3, tmid2=4))
        self.assertIn("DIFFERENT *MAT_THERMAL_* materials",
                      " ".join(r.warnings))
        heat = _block(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(heat[1][40:60]), 40.0)   # AS from TMID 3

    def test_isotropic_multy_one_form_is_not_warned_about(self):
        # The carrier's MULTY = MULTZ = 1.0 with LCIDY = LCIDZ = 0 on an
        # ISOTROPIC material: LS-DYNA ignores those cells itself, so a warning
        # would fire on every correct deck.
        r, _s = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        self.assertNotIn("MULTY", " ".join(r.warnings))

    def test_tref_is_warn_dropped_by_name(self):
        extra = ("*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(1, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 293.0) + "\n"
                 + DRIVER)
        r, _s = _convert(_thermal(extra))
        self.assertIn("TREF=293", " ".join(r.warnings))
        self.assertIn("SECANT", " ".join(r.warnings))

    def test_undefined_coefficient_curve_emits_nothing(self):
        extra = ("*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 999, 1.0) + "\n"
                 + DRIVER)
        r, starter = _convert(_thermal(extra))
        self.assertNotIn("/THERM_STRESS/MAT", starter)
        self.assertIn("LCID=999", " ".join(r.warnings))

    def test_tmid_join_supplies_the_real_heat_mat_values(self):
        extra = ("*MAT_THERMAL_ISOTROPIC\n"
                 + _row(3, "7.8500E-9", 0, 0.0, 0.0, 0.0) + "\n"
                 + _row("4.6000E+8", 40.0) + "\n"
                 + CARRIER_EXPANSION + DRIVER)
        _r, starter = _convert(_thermal(extra, tmid1=3, tmid2=3))
        for header in [ln for ln in starter.splitlines()
                       if ln.startswith("/HEAT/MAT/")]:
            f = _fields(_block(starter, header)[1])
            # RHO0_CP = TRO * HC = 7.85e-9 * 4.6e8 = 3.611 (units pass through)
            self.assertAlmostEqual(float(f[1]), 3.611, places=6)
            self.assertAlmostEqual(float(f[2]), 40.0)     # AS = TC

    def test_no_thermal_material_gives_the_no_op_form_and_says_so(self):
        r, starter = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/HEAT/MAT/")][0]
        f = _fields(_block(starter, header)[1])
        self.assertEqual(f[2], "0")                     # AS: no conduction
        self.assertNotEqual(float(f[1]), 0.0)           # positive capacity
        self.assertIn("no *MAT_THERMAL_* is bound", " ".join(r.warnings))

    #: One quad on *MAT_ELASTIC, plus whatever {EXTRA} adds.
    SHELL = (
        "*KEYWORD\n"
        "*NODE\n"
        "         1             0.0             0.0             0.0\n"
        "         2            10.0             0.0             0.0\n"
        "         3            10.0            10.0             0.0\n"
        "         4             0.0            10.0             0.0\n"
        "         5            10.0            20.0             0.0\n"
        "         6             0.0            20.0             0.0\n"
        "*ELEMENT_SHELL\n"
        + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)) + "\n"
        "*PART\nplate\n" + _row(1, 1, 1) + "\n"
        "*SECTION_SHELL\n" + _row(1, 2, 0.833, 5) + "\n" + _row(3.0) + "\n"
        "*MAT_ELASTIC\n" + _row(1, "7.8500E-9", 210000.0, 0.3) + "\n"
        "{EXTRA}"
        "*CONTROL_TERMINATION\n     0.001\n*END\n")

    def test_law1_shell_is_restated_as_law36_so_it_can_expand(self):
        # LAW1 runs GLOBAL integration (WARNING 1084) and thermexpc.F only
        # reaches the per-integration-point stresses, so a LAW1 shell expands
        # by nothing: measured 2.66e-07 mm against a closed-form 0.012 mm, at
        # NIP 1 and NIP 5 alike. The restatement is elastically neutral
        # (+0.012 % membrane stress at the same elongation).
        r, starter = _convert(
            self.SHELL.replace("{EXTRA}", CARRIER_EXPANSION + DRIVER))
        self.assertIn("/THERM_STRESS/MAT/1", starter)
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertNotIn("/MAT/ELAST/1", starter)
        self.assertIn("is RESTATED as /MAT/LAW36", " ".join(r.warnings))
        # The far-yield curve is flat at 1000 x E and is a real /FUNCT.
        law36 = _block(starter, "/MAT/LAW36/1")
        fid = int(law36[law36.index("# fct_ID1") + 1])
        pts = _funct_points(starter, fid)
        self.assertEqual([y for _x, y in pts], [2.1e8, 2.1e8])

    def test_a_solid_part_on_the_material_blocks_the_restatement(self):
        # mmain.F90:757 applies the expansion before the law dispatch, so a
        # LAW1 SOLID expands correctly — restating would change its law for
        # nothing. The mixed case keeps LAW1 and is named instead.
        r, starter = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        self.assertIn("/MAT/ELAST/", starter)
        self.assertNotIn("/MAT/LAW36/", starter)
        self.assertNotIn("is RESTATED as /MAT/LAW36", " ".join(r.warnings))

    def test_an_initial_stress_record_blocks_the_restatement(self):
        # The #127 mixed-deck rule: /INISHE carries one station per
        # THROUGH-THICKNESS integration point and the count is cross-checked
        # against /PROP/SHELL N, which the restatement would move from 0
        # (global integration) to N.
        ini = ("*INITIAL_STRESS_SHELL\n" + _row(1, 1, 2, 0, 0, 0) + "\n"
               + _row16(-0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row16(0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        r, starter = _convert(self.SHELL.replace(
            "{EXTRA}", CARRIER_EXPANSION + DRIVER + ini))
        self.assertIn("/MAT/ELAST/1", starter)
        self.assertNotIn("/MAT/LAW36/", starter)
        w = " ".join(r.warnings)
        self.assertIn("*INITIAL_STRESS_SHELL / *INITIAL_STRAIN_SHELL", w)
        self.assertIn("The law is left as LAW1", w)

    def test_a_shell_without_the_expansion_card_keeps_law1(self):
        r, starter = _convert(self.SHELL.replace("{EXTRA}", ""))
        self.assertIn("/MAT/ELAST/1", starter)
        self.assertNotIn("/MAT/LAW36/", starter)
        self.assertNotIn("RESTATED", " ".join(r.warnings))

    def test_a_mixed_shell_and_solid_material_names_the_inert_shell(self):
        # The material carries both a shell part and a solid part, so it
        # cannot be restated; the shell half is reported as inert.
        deck = (_thermal(CARRIER_EXPANSION + DRIVER
                         + "*PART\nplate\n" + _row(3, 3, 1) + "\n"
                         "*SECTION_SHELL\n" + _row(3, 2, 0.833, 5) + "\n"
                         + _row(3.0) + "\n"
                         "*ELEMENT_SHELL\n"
                         + "".join(f"{v:>8}" for v in (9, 3, 1, 2, 3, 4))
                         + "\n")
                .replace("*MAT_ADD_THERMAL_EXPANSION\n"
                         + _row(1, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0),
                         "*MAT_ADD_THERMAL_EXPANSION\n"
                         + _row(3, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0)))
        r, starter = _convert(deck)
        self.assertIn("/THERM_STRESS/MAT", starter)
        w = " ".join(r.warnings)
        self.assertTrue("is RESTATED as /MAT/LAW36" in w
                        or "could NOT be restated" in w, w)

    def test_tabulated_johnson_cook_is_refused_by_name(self):
        # /HEAT/MAT would kill LAW109's own self-heating and /THERM_STRESS
        # without one is ERROR 1129 — the pair cannot be had on that law.
        jc = _thermal(
            "*MAT_TABULATED_JOHNSON_COOK\n"
            + _row(1, "7.8500E-9", 210000.0, 0.3, 4.6e8, 293.0, 0.9, 1) + "\n"
            + _row(0, 0, 0, 0, 0, 0, 0) + "\n"
            + CARRIER_EXPANSION + DRIVER)
        jc = jc.replace("*MAT_ELASTIC\n"
                        + _row(1, "7.8500E-9", 210000.0, 0.3) + "\n", "")
        r, starter = _convert(jc)
        self.assertNotIn("/THERM_STRESS/MAT", starter)
        self.assertNotIn("/HEAT/MAT", starter)
        self.assertIn("kills that self-heating", " ".join(r.warnings))


class TemperatureDriverTests(unittest.TestCase):
    def _imptemp(self, starter):
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/IMPTEMP/")]
        self.assertTrue(header, starter)
        return _block(starter, header[0])

    def test_load_thermal_load_curve_uses_the_deck_curve(self):
        _r, starter = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        body = self._imptemp(starter)
        self.assertEqual(body[1], "# func_IDT sensor_ID  grnod_ID")
        self.assertEqual(int(body[2][0:10]), 7)
        self.assertEqual(
            body[3],
            "#           Ascale_x            Fscale_y             T_start"
            "              T_stop")
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)

    def _imptemps(self, starter):
        return [_block(starter, ln) for ln in starter.splitlines()
                if ln.startswith("/IMPTEMP/")]

    def test_load_thermal_load_curve_reads_every_card(self):
        # "Thermal Load Curve Cards. Include as many cards in this format as
        # desired" (Vol I R17 p.33-171).
        extra = ("*LOAD_THERMAL_LOAD_CURVE\n" + _row(7, 0) + "\n"
                 + _row(8, 0) + "\n" + CARRIER_EXPANSION
                 + "*DEFINE_CURVE\n" + _row(7) + "\n"
                 + _row16(0.0, 20.0) + "\n" + _row16(1.0, 120.0) + "\n"
                 + "*DEFINE_CURVE\n" + _row(8) + "\n"
                 + _row16(0.0, 30.0) + "\n" + _row16(1.0, 130.0) + "\n")
        _r, starter = _convert(_thermal(extra))
        self.assertEqual([int(b[2][0:10]) for b in self._imptemps(starter)],
                         [7, 8])

    def test_load_thermal_constant_node_reads_every_node_card(self):
        # "Node Cards. Include as many cards in this format as desired"
        # (p.33-169). One /IMPTEMP per row, each at its own temperature.
        extra = ("*LOAD_THERMAL_CONSTANT_NODE\n"
                 + _row(1, 100.0) + "\n" + _row(2, 200.0) + "\n"
                 + _row(3, 300.0) + "\n" + CARRIER_EXPANSION)
        _r, starter = _convert(_thermal(extra))
        got = []
        for b in self._imptemps(starter):
            pts = _funct_points(starter, int(b[2][0:10]))
            got.append(pts[0][1])
        self.assertEqual(got, [100.0, 200.0, 300.0])

    def test_load_thermal_variable_node_reads_every_node_card(self):
        extra = ("*LOAD_THERMAL_VARIABLE_NODE\n"
                 + _row(1, 1.0, 0.0, 7) + "\n"
                 + _row(2, 2.0, 0.0, 7) + "\n" + CARRIER_EXPANSION
                 + "*DEFINE_CURVE\n" + _row(7) + "\n"
                 + _row16(0.0, 10.0) + "\n" + _row16(1.0, 110.0) + "\n")
        _r, starter = _convert(_thermal(extra))
        self.assertEqual(len(self._imptemps(starter)), 2)

    def test_load_thermal_constant_reads_every_card_set(self):
        # "Card Sets. Include as many sets consisting of the following two
        # cards as desired" (p.33-166). Card 1 of the SECOND set is entirely
        # blank (NSID defaults to all nodes) — a "next non-blank row" walk
        # would eat it and mis-read the whole block.
        extra = ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2) + "\n"
                 "*LOAD_THERMAL_CONSTANT\n"
                 + _row(5, 0, 0) + "\n" + _row(150.0, 0.0) + "\n"
                 + "\n" + _row(60.0, 0.0) + "\n" + CARRIER_EXPANSION)
        _r, starter = _convert(_thermal(extra))
        blocks = self._imptemps(starter)
        self.assertEqual(len(blocks), 2)
        temps = [_funct_points(starter, int(b[2][0:10]))[0][1]
                 for b in blocks]
        self.assertEqual(temps, [150.0, 60.0])
        # ...and the blank card 1 really did mean "all nodes".
        gids = [int(b[2][20:30]) for b in blocks]
        self.assertEqual(len(_ids_of_group(starter,
                                           f"/GRNOD/NODE/{gids[1]}")), 12)

    def test_load_thermal_constant_trailing_blank_makes_no_phantom_driver(self):
        extra = ("*LOAD_THERMAL_CONSTANT\n"
                 + _row(0, 0, 0) + "\n" + _row(150.0, 0.0) + "\n"
                 + "\n" + "\n" + CARRIER_EXPANSION)
        _r, starter = _convert(_thermal(extra))
        self.assertEqual(len(self._imptemps(starter)), 1)

    def test_nsidex_nodes_are_left_out_of_the_imptemp_group(self):
        # "NSIDEX - Nodal set ID containing nodes that are exempted from the
        # imposed temperature" (p.33-166). /IMPTEMP is a hard Dirichlet reset
        # every cycle, so an exempted node must not be in its /GRNOD.
        extra = ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2, 3, 4) + "\n"
                 "*SET_NODE_LIST\n" + _row(6) + "\n" + _row(2) + "\n"
                 "*LOAD_THERMAL_CONSTANT\n"
                 + _row(5, 6, 0) + "\n" + _row(150.0, 0.0) + "\n"
                 + CARRIER_EXPANSION)
        r, starter = _convert(_thermal(extra))
        gid = int(self._imptemp(starter)[2][20:30])
        self.assertEqual(_ids_of_group(starter, f"/GRNOD/NODE/{gid}"),
                         [1, 3, 4])
        self.assertIn("NSIDEX=6", " ".join(r.warnings))

    def test_boxid_is_named_rather_than_silently_ignored(self):
        extra = ("*LOAD_THERMAL_CONSTANT\n"
                 + _row(0, 0, 66) + "\n" + _row(150.0, 0.0) + "\n"
                 + CARRIER_EXPANSION)
        r, _s = _convert(_thermal(extra))
        self.assertIn("BOXID=66", " ".join(r.warnings))

    def test_load_thermal_variable_initial_temp_uses_ts_times_f_zero(self):
        # "T0 = TB + TS x f(0)" (Vol I R17 p.33-180 Remark 1). The curve
        # deliberately starts at a NON-ZERO ordinate: with f(0) = 0 the
        # TB + 1.0*f(0) bug and the correct TB + TS*f(0) agree.
        extra = ("*LOAD_THERMAL_VARIABLE\n" + _row(0, 0, 0) + "\n"
                 + _row(2.0, 20.0, 9) + "\n" + CARRIER_EXPANSION
                 + "*DEFINE_CURVE\n" + _row(9) + "\n"
                 + _row16(0.0, 10.0) + "\n" + _row16(1.0, 110.0) + "\n")
        _r, starter = _convert(_thermal(extra))
        fid = int(self._imptemp(starter)[2][0:10])
        self.assertEqual([y for _x, y in _funct_points(starter, fid)],
                         [40.0, 240.0])            # TB + TS*f
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/INITEMP/")][0]
        self.assertAlmostEqual(float(_block(starter, header)[2][0:20]), 40.0)

    def test_load_thermal_constant_synthesizes_a_two_point_function(self):
        # func_IDT = 0 is ERROR 120 once PER NODE, so a constant temperature
        # can never be paired with a zero id.
        extra = ("*LOAD_THERMAL_CONSTANT\n" + _row(0, 0, 0) + "\n"
                 + _row(150.0, 0.0) + "\n" + CARRIER_EXPANSION)
        _r, starter = _convert(_thermal(extra))
        body = self._imptemp(starter)
        fid = int(body[2][0:10])
        self.assertNotEqual(fid, 0)
        self.assertEqual([y for _x, y in _funct_points(starter, fid)],
                         [150.0, 150.0])
        # ...and a companion /INITEMP carries the t=0 value.
        init = [ln for ln in starter.splitlines() if ln.startswith("/INITEMP/")]
        self.assertTrue(init)
        self.assertAlmostEqual(float(_block(starter, init[0])[2][0:20]), 150.0)

    def test_load_thermal_variable_bakes_the_tb_offset_into_the_curve(self):
        # T = TB + TS*f(t); /IMPTEMP has only Fscale_y*f(x), no additive slot.
        extra = ("*LOAD_THERMAL_VARIABLE\n" + _row(0, 0, 0) + "\n"
                 + _row(2.0, 20.0, 7) + "\n" + CARRIER_EXPANSION
                 + "*DEFINE_CURVE\n" + _row(7) + "\n"
                 + _row16(0.0, 0.0) + "\n" + _row16(1.0, 50.0) + "\n")
        _r, starter = _convert(_thermal(extra))
        body = self._imptemp(starter)
        fid = int(body[2][0:10])
        self.assertNotEqual(fid, 7)
        self.assertEqual([y for _x, y in _funct_points(starter, fid)],
                         [20.0, 120.0])              # TB + TS*f
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)

    def test_boundary_temperature_constant_form_is_the_value_not_a_scale(self):
        # TLCID = 0 -> T is the constant TMULT (an OVERRIDE on the LS-DYNA
        # side), never a scale on a zero function.
        extra = ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2, 3, 4) + "\n"
                 "*BOUNDARY_TEMPERATURE_SET\n"
                 + _row(5, 0, 250.0, 0, 1.0e20, 0.0) + "\n"
                 + CARRIER_EXPANSION)
        _r, starter = _convert(_thermal(extra))
        body = self._imptemp(starter)
        fid = int(body[2][0:10])
        self.assertEqual([y for _x, y in _funct_points(starter, fid)],
                         [250.0, 250.0])
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)

    def _bt(self, tmult=3.0, tbirth=0.0, tdeath=0.5):
        extra = ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2, 3, 4) + "\n"
                 "*BOUNDARY_TEMPERATURE_SET\n"
                 + _row(5, 7, tmult, 0, tdeath, tbirth) + "\n"
                 + CARRIER_EXPANSION
                 + "*DEFINE_CURVE\n" + _row(7) + "\n"
                 + _row16(0.0, 20.0) + "\n" + _row16(1.0, 120.0) + "\n")
        return _convert(_thermal(extra))

    def test_boundary_temperature_curve_form_carries_tmult_as_fscale(self):
        _r, starter = self._bt()
        body = self._imptemp(starter)
        self.assertEqual(int(body[2][0:10]), 7)                # the deck curve
        self.assertAlmostEqual(float(body[4][20:40]), 3.0)     # TMULT
        self.assertAlmostEqual(float(body[4][40:60]), 0.0)     # TBIRTH
        self.assertAlmostEqual(float(body[4][60:80]), 0.5)     # TDEATH

    def test_tbirth_shifts_the_curve_because_t_start_is_its_time_origin(self):
        # fixtemp.F:118-129 evaluates the function at TT - STARTT, so T_start
        # is BOTH the activation gate and the curve's time origin; LS-DYNA
        # reads its (t, T) pairs at absolute time. The emitted function must
        # therefore be the deck curve shifted by -TBIRTH.
        _r, starter = self._bt(tmult=1.0, tbirth=0.1)
        body = self._imptemp(starter)
        fid = int(body[2][0:10])
        self.assertNotEqual(fid, 7)
        self.assertEqual([(round(x, 10), y)
                          for x, y in _funct_points(starter, fid)],
                         [(-0.1, 20.0), (0.9, 120.0)])
        self.assertAlmostEqual(float(body[4][40:60]), 0.1)     # T_start kept

    def test_tbirth_zero_keeps_the_deck_curve_unshifted(self):
        _r, starter = self._bt(tmult=1.0, tbirth=0.0)
        self.assertEqual(int(self._imptemp(starter)[2][0:10]), 7)

    def test_blank_tmult_beside_a_curve_is_resolved_to_one_not_zero(self):
        # hm_read_imptemp.F:139 turns Fscale_y = 0 into 1.0, so writing the
        # literal 0 would mean the opposite of what it does — and the
        # companion /INITEMP would then be 0*f(0) = 0 instead of 20.
        r, starter = self._bt(tmult=0.0)
        self.assertAlmostEqual(float(self._imptemp(starter)[4][20:40]), 1.0)
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/INITEMP/")][0]
        self.assertAlmostEqual(float(_block(starter, header)[2][0:20]), 20.0)
        self.assertIn("leaves TMULT blank/zero", " ".join(r.warnings))

    def test_initial_temperature_set_zero_covers_every_node(self):
        extra = ("*INITIAL_TEMPERATURE_SET\n" + _row(0, 20.0, 0) + "\n"
                 + CARRIER_EXPANSION + DRIVER)
        _r, starter = _convert(_thermal(extra))
        header = [ln for ln in starter.splitlines()
                  if ln.startswith("/INITEMP/")][0]
        body = _block(starter, header)
        self.assertEqual(body[1], "#                 T0   grnd_ID  fld_type")
        self.assertAlmostEqual(float(body[2][0:20]), 20.0)
        # fld_type 0 (the GROUP form): the per-node form loses its values.
        self.assertEqual(int(body[2][30:40]), 0)
        gid = int(body[2][20:30])
        self.assertEqual(len(_ids_of_group(starter, f"/GRNOD/NODE/{gid}")), 12)

    def test_drivers_are_dropped_when_no_material_is_thermal(self):
        extra = ("*INITIAL_TEMPERATURE_SET\n" + _row(0, 20.0, 0) + "\n"
                 + DRIVER)
        r, starter = _convert(_thermal(extra))
        self.assertNotIn("/INITEMP", starter)
        self.assertNotIn("/IMPTEMP", starter)
        self.assertIn("no thermal solve is armed", " ".join(r.warnings))


class ThermalDuplicateScanTests(unittest.TestCase):
    def test_each_thermal_card_is_emitted_once_per_material_id(self):
        # Both cards are MATERIAL-keyed while *MAT_ADD_THERMAL_EXPANSION is
        # PART-keyed, so two cards on two parts sharing one MID is the natural
        # way to emit a duplicate (the #125 /PROP/TYPE23 failure one namespace
        # over). The starter does not refuse it — it reads the first block and
        # drops the rest silently.
        extra = (CARRIER_EXPANSION
                 + "*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(2, 0, "1.20000E-5", 0, 1.0, 0, 1.0, 0.0) + "\n"
                 + DRIVER)
        r, starter = _convert(_thermal(extra))
        for kind in ("/HEAT/MAT/", "/THERM_STRESS/MAT/"):
            heads = [ln for ln in starter.splitlines() if ln.startswith(kind)]
            self.assertEqual(len(heads), len(set(heads)), heads)
        self.assertNotIn("is emitted 2 times", " ".join(r.warnings))

    def test_the_deck_wide_scan_would_catch_a_duplicate(self):
        from k2rad.writer.assembly import _warn_duplicate_thermal_ids
        st = ConversionState()
        _warn_duplicate_thermal_ids(
            st, ["/HEAT/MAT/7", "/HEAT/MAT/7", "/THERM_STRESS/MAT/7"])
        self.assertIn("/HEAT/MAT/7 is emitted 2 times", " ".join(st.warnings))
        self.assertNotIn("/THERM_STRESS/MAT/7 is emitted",
                         " ".join(st.warnings))


class ThermalOutputTests(unittest.TestCase):
    def test_temperature_channels_only_with_a_real_thermal_solve(self):
        _r, with_solve = _convert(_thermal(CARRIER_EXPANSION + DRIVER))
        self.assertIn("/TH/NODE", with_solve)
        self.assertIn("      TEMP", with_solve)
        # ...and never without one (#122: an all-zero channel reads as data).
        _r2, plain = _convert(_thermal(""))
        self.assertNotIn("TEMP", plain)

    #: A /HEAT/MAT and a stated driver whose *SET_NODE the converter cannot
    #: resolve — here a plain undefined id 404. The driver is dropped at
    #: EMISSION, so nothing ever changes the temperature and the channels must
    #: stay out.
    #:
    #: The two corpus examples this comment used to name,
    #: thermal/metal-forming/metal-forming.k (*SET_NODE_LIST_GENERATE) and the
    #: mat-add carrier (*SET_NODE_GENERAL), stopped being examples of the shape
    #: in R14 triage round 2, which registered both spellings; the ones that
    #: still leave this hole are *SET_NODE_LIST_SMOOTH and a *SET_NODE_GENERAL
    #: clause k2rad refuses by name. The probe itself never depended on them —
    #: id 404 exists nowhere in it — so only the sentence changed.
    UNRESOLVABLE_DRIVER = ("*BOUNDARY_TEMPERATURE_SET\n"
                           + _row(404, 0, 250.0, 0, 1.0e20, 0.0) + "\n")

    def test_a_driver_whose_node_set_is_missing_arms_nothing(self):
        r, starter = _convert(
            _thermal(CARRIER_EXPANSION + self.UNRESOLVABLE_DRIVER))
        self.assertIn("/HEAT/MAT/", starter)
        self.assertIn("/THERM_STRESS/MAT/", starter)
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertNotIn("TEMP", starter.split("/THERM_STRESS")[0])
        self.assertNotIn("/TH/NODE", starter)
        w = " ".join(r.warnings)
        self.assertIn("is INERT on this deck", w)
        self.assertIn("*SET_NODE 404 is not defined", w)

    def test_an_initemp_alone_is_a_state_not_a_driver(self):
        # A uniform *INITIAL_TEMPERATURE with nothing to change it leaves
        # DTEMP identically 0 on every cycle (#122).
        extra = ("*INITIAL_TEMPERATURE_SET\n" + _row(0, 20.0, 0) + "\n"
                 + CARRIER_EXPANSION)
        r, starter = _convert(_thermal(extra))
        self.assertIn("/INITEMP/", starter)
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertNotIn("/TH/NODE", starter)
        self.assertIn("is INERT on this deck", " ".join(r.warnings))

    def test_anim_noda_temp_is_off_when_the_driver_was_dropped(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(_thermal(CARRIER_EXPANSION + self.UNRESOLVABLE_DRIVER))
        res = convert(path, write_log=False)
        with open(res.engine_path) as fh:
            self.assertNotIn("/ANIM/NODA/TEMP", fh.read())
        tmp.cleanup()

    def test_anim_noda_temp_follows_the_same_gate(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(_thermal(CARRIER_EXPANSION + DRIVER))
        res = convert(path, write_log=False)
        with open(res.engine_path) as fh:
            engine = fh.read()
        self.assertIn("/ANIM/NODA/TEMP", engine)
        with open(path, "w") as fh:
            fh.write(_thermal(""))
        res = convert(path, write_log=False)
        with open(res.engine_path) as fh:
            engine = fh.read()
        self.assertNotIn("/ANIM/NODA/TEMP", engine)
        tmp.cleanup()


class ThermalDeferredTests(unittest.TestCase):
    def test_control_and_boundary_thermal_cards_are_named_not_skipped(self):
        # What is left here after the THERMAL SOLVER batch: the spellings with
        # NO Radioss counterpart at all. *CONTROL_THERMAL_SOLVER,
        # *BOUNDARY_{FLUX,CONVECTION,RADIATION}_*, *MAT_THERMAL_{ORTHOTROPIC,
        # ISOTROPIC_TD,ISOTROPIC_TD_LC} and the eight
        # *LOAD_THERMAL_*_ELEMENT_<F> spellings now CONVERT and are covered by
        # tests/test_thermal_solver.py; *CONTROL_THERMAL_{TIMESTEP,NONLINEAR}
        # are still named drops but through their own parsing handlers, and
        # keep their row here.
        for kw, card in (
                ("CONTROL_THERMAL_TIMESTEP", _row(1, 1.0)),
                ("CONTROL_THERMAL_NONLINEAR", _row(1, 0.001)),
                ("CONTROL_THERMAL_FORMING", _row(1.0e-5, 1, 10.0)),
                ("CONTROL_THERMAL_EIGENVALUE", _row(1)),
                ("MAT_THERMAL_CWM", _row(9)),
                ("LOAD_THERMAL_BINOUT", _row(1)),
                ("LOAD_THERMAL_D3PLOT", _row(1)),
                # The REAL R17 spellings — there is no *LOAD_THERMAL_DYNAIN.
                ("LOAD_THERMAL_TOPAZ", _row(1)),
                ("LOAD_THERMAL_RSW", _row(1)),
                ("LOAD_THERMAL_VARIABLE_BEAM", _row(1, 1.0, 0.0, 100)),
                ("LOAD_THERMAL_VARIABLE_BEAM_SET", _row(1, 1.0, 0.0, 100)),
                ("LOAD_THERMAL_VARIABLE_SHELL", _row(1, 1.0, 0.0, 100)),
                ("LOAD_THERMAL_VARIABLE_SHELL_SET", _row(1, 1.0, 0.0, 100)),
                ("BOUNDARY_FLUX_TRAJECTORY", _row(1, 0)),
                ("BOUNDARY_RADIATION_ENCLOSURE", _row(1, 2)),
                ("BOUNDARY_RADIATION_SET_VF_READ", _row(1, 2)),
                ("BOUNDARY_RADIATION_SET_VF_CALCULATE", _row(1, 2)),
                ("BOUNDARY_RADIATION_SET_VF_READ_RESTART", _row(1, 2)),
                ("BOUNDARY_RADIATION_SET_VF_CALCULATE_RESTART", _row(1, 2)),
                ("BOUNDARY_RADIATION_SEGMENT_VF_READ", _row(1, 2, 3, 4)),
                ("BOUNDARY_RADIATION_SEGMENT_VF_CALCULATE", _row(1, 2, 3, 4)),
                ("BOUNDARY_RADIATION_SEGMENT_VF_READ_RESTART",
                 _row(1, 2, 3, 4)),
                ("BOUNDARY_RADIATION_SEGMENT_VF_CALCULATE_RESTART",
                 _row(1, 2, 3, 4))):
            state = _dispatch(f"*KEYWORD\n*{kw}\n{card}\n*END\n")
            self.assertEqual(state.skipped_keywords, [], kw)
            self.assertIn(kw, dict(state.recognized_not_emitted), kw)

    def test_load_thermal_dynain_is_not_invented(self):
        # *LOAD_THERMAL_DYNAIN appears in no LS-DYNA manual (Vol I R16/R17,
        # Vol III R17) and in no shipped hm_cfg_files keyword tree. A
        # fabricated row in a user-facing catalogue is worse than an honest
        # "unsupported": it claims an authority that does not exist.
        from k2rad.handlers import HANDLERS, RARE_MATERIAL_KEYWORDS
        self.assertNotIn("LOAD_THERMAL_DYNAIN", RARE_MATERIAL_KEYWORDS)
        self.assertNotIn("LOAD_THERMAL_DYNAIN", HANDLERS)

    def test_mat_thermal_cwm_title_reaches_the_same_handler(self):
        state = _dispatch("*KEYWORD\n*MAT_THERMAL_CWM_TITLE\nweld\n"
                          + _row(9) + "\n*END\n")
        self.assertEqual(state.skipped_keywords, [])
        self.assertIn("MAT_THERMAL_CWM", dict(state.recognized_not_emitted))

    def test_control_solution_soln_is_reported(self):
        state = _dispatch("*KEYWORD\n*CONTROL_SOLUTION\n" + _row(2) + "\n*END\n")
        self.assertIn("SOLN=2",
                      dict(state.recognized_not_emitted)["CONTROL_SOLUTION"])
        # SOLN = 1 is now DECIDED IN THE WRITER, because whether a /DT/THERM is
        # honest depends on the emitted deck (a thermal-only run mode that
        # integrates nothing freezes the whole model for no reason). The
        # handler only records the value; tests/test_thermal_solver.py pins
        # both arms end to end.
        state = _dispatch("*KEYWORD\n*CONTROL_SOLUTION\n" + _row(1) + "\n*END\n")
        self.assertEqual(state.ctrl_solution_soln, 1)
        self.assertEqual(state.warnings, [])

    def test_section_shell_thermal_is_parsed_not_skipped(self):
        # Registering the spelling is what turns 40 x ERROR 495 ("SHELL HAS A
        # NULL THICKNESS") into a startable deck: the option adds one card the
        # card-set walk already strides.
        state = _dispatch("*KEYWORD\n*SECTION_SHELL_THERMAL\n"
                          + _row(1, 16, 0.0, 2) + "\n" + _row(3.0) + "\n"
                          + _row(1) + "\n*END\n")
        self.assertEqual(state.skipped_keywords, [])
        self.assertIn(1, state.sec_shells)
        self.assertAlmostEqual(state.sec_shells[1].t1, 3.0)


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / *INCLUDE_TRANSFORM coverage
# ═════════════════════════════════════════════════════════════════════════════

class DispatchAndOffsetCoverageTests(unittest.TestCase):
    def test_parser_and_offset_tables_cover_the_same_spellings(self):
        # ONE source (#116): every spelling the handler reads must also carry an
        # explicit VERDICT in the offset table, or an *INCLUDE_TRANSFORM keeps
        # its original MID/LCID while the rest of the include moves. A `None`
        # verdict is the deliberate "recognized but warn-dropped, so its cells
        # must NOT be rewritten by position" answer (the *AIRBAG warn-drop
        # rule) — what must never happen is a spelling with no verdict at all,
        # which the KeyError in assembly.py turns into an ImportError.
        from k2rad.assembly import _RARE_MATERIAL_OFFSETS
        self.assertTrue(RARE_MATERIAL_KEYWORDS)
        self.assertEqual(set(RARE_MATERIAL_KEYWORDS),
                         set(_RARE_MATERIAL_OFFSETS))
        for kw, spec in _RARE_MATERIAL_OFFSETS.items():
            self.assertIn(kw, HANDLERS, f"{kw} has no handler")
            if spec is None:
                self.assertNotIn(kw, _OFFSET_SPECS,
                                 f"{kw} is warn-dropped but offset anyway")
            else:
                self.assertIn(kw, _OFFSET_SPECS, f"{kw} has no offset spec")

    def test_every_batch_keyword_is_read_not_skipped(self):
        # A warn-dropped keyword must reach note_recognized_not_emitted (or a
        # real conversion), never skipped_keywords: the two channels are
        # deliberately distinct, and "skipped" reads as "k2rad has never heard
        # of this card".
        for kw in RARE_MATERIAL_KEYWORDS:
            state = _dispatch(f"*KEYWORD\n*{kw}\n" + _row(1) + "\n"
                              + _row(1) + "\n*END\n")
            self.assertEqual(state.skipped_keywords, [], kw)

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
        # Card 2 is IDNOFF..IDDOFF; IDROFF lives on CARD 3 (Vol I R17
        # *INCLUDE_TRANSFORM), so it cannot ride along as an eighth cell.
        cells = [offs.get(k, 0) for k in
                 ("idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff",
                  "iddoff")]
        with open(os.path.join(d, "main.k"), "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\ninc.k\n"
                     + _row(*cells) + "\n"
                     + _row(offs.get("idroff", 0)) + "\n*END\n")
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

    def test_muscle_curve_cells_move_only_when_negative(self):
        inner = ("*MAT_MUSCLE\n"
                 + _row(1, "1.0000E-9", 1.25, 10.0, 0.3, 0.15, 5.0, 2.0) + "\n"
                 + _row(0.5, 1.0, -3, -4, 0.0) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1001)
        self.assertEqual(int(float(out[1][20:30])), -503)     # SVS curve
        self.assertEqual(int(float(out[1][30:40])), -504)     # SVR curve
        self.assertAlmostEqual(float(out[1][0:10]), 0.5)      # ALM: physics
        self.assertAlmostEqual(float(out[1][10:20]), 1.0)     # SFR: physics

    def test_spring_muscle_curve_cells_move_only_when_negative(self):
        inner = ("*MAT_SPRING_MUSCLE\n"
                 + _row(5, 10.0, 100.0, -7, 0.5, 1000.0, -5, -6) + "\n"
                 + _row(-8, 1.5, 3.0) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1005)
        self.assertEqual(int(float(out[0][30:40])), -507)     # SV
        self.assertEqual(int(float(out[0][60:70])), -505)     # TL
        self.assertEqual(int(float(out[0][70:80])), -506)     # TV
        self.assertEqual(int(float(out[1][0:10])), -508)      # FPE
        self.assertAlmostEqual(float(out[0][40:50]), 0.5)     # A: physics

    def test_thermal_expansion_pid_and_curves_move(self):
        inner = ("*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(1, 9, 1.0e-5, 11, 2.0, 12, 3.0, 0.0) + "\n"
                 + _row(2, 9, 1.0e-5, 0, 1.0, 0, 1.0, 0.0) + "\n")
        out = self._offset(inner, idpoff=300, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 301)      # PID
        self.assertEqual(int(out[0][10:20]), 509)     # LCID
        self.assertEqual(int(out[0][30:40]), 511)     # LCIDY
        self.assertEqual(int(out[0][50:60]), 512)     # LCIDZ
        # ...on EVERY repeated card, not just the first.
        self.assertEqual(int(out[1][0:10]), 302)
        self.assertEqual(int(out[1][10:20]), 509)

    def test_thermal_driver_set_and_curve_ids_move(self):
        for kw, cells, offs, want in (
                ("INITIAL_TEMPERATURE_SET", (5, 20.0, 0),
                 {"idsoff": 400}, {0: 405}),
                ("INITIAL_TEMPERATURE_NODE", (7, 20.0, 0),
                 {"idnoff": 200}, {0: 207}),
                ("BOUNDARY_TEMPERATURE_SET", (5, 9, 1.0),
                 {"idsoff": 400, "idfoff": 500}, {0: 405, 1: 509}),
                ("BOUNDARY_TEMPERATURE_NODE", (7, 9, 1.0),
                 {"idnoff": 200, "idfoff": 500}, {0: 207, 1: 509}),
                ("LOAD_THERMAL_LOAD_CURVE", (9, 0),
                 {"idfoff": 500}, {0: 509}),
                ("MAT_THERMAL_ISOTROPIC", (3, 7.85e-9, 9),
                 {"idmoff": 1000, "idfoff": 500}, {0: 1003, 2: 509})):
            inner = f"*{kw}\n" + _row(*cells) + "\n"
            out = self._offset(inner, **offs).splitlines()
            for cell, value in want.items():
                self.assertEqual(int(out[0][cell * 10:(cell + 1) * 10]),
                                 value, f"{kw} cell {cell}")

    def test_thermal_expansion_negative_pid_takes_idmoff_sign_preserved(self):
        # Field 0 lives in TWO id namespaces by SIGN (Vol II R17 p.2-146):
        # GT.0 is a PART id -> IDPOFF, LT.0 makes |PID| a MATERIAL id ->
        # IDMOFF. Both forms may appear under one keyword, so the block needs
        # BOTH rewrites over the SAME row set — the #125 "one cell, two id
        # namespaces" class.
        inner = ("*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(-5, 0, 1.0e-5) + "\n"
                 + _row(7, 0, 2.0e-5) + "\n")
        out = self._offset(inner, idpoff=300, idmoff=1000).splitlines()
        self.assertEqual(int(float(out[0][0:10])), -1005)   # |PID| = material
        self.assertEqual(int(out[1][0:10]), 307)            # PID = part

    def test_load_thermal_offsets_reach_every_card_set(self):
        # "Card Sets. Include as many sets consisting of the following two
        # cards as desired" (Vol I R17 pp.33-166/33-179). A first-card-only
        # walk leaves every later NSID / NSIDEX / BOXID / LCID pointing at the
        # parent deck's numbering — the silent-wrong-id class of #116/#119/#125.
        inner = ("*LOAD_THERMAL_CONSTANT\n"
                 + _row(5, 6, 8) + "\n" + _row(100.0, 20.0) + "\n"
                 + _row(11, 12, 13) + "\n" + _row(200.0, 30.0) + "\n")
        out = self._offset(inner, idsoff=400, iddoff=700).splitlines()
        self.assertEqual([int(out[0][k * 10:(k + 1) * 10]) for k in range(3)],
                         [405, 406, 708])
        self.assertEqual([int(out[2][k * 10:(k + 1) * 10]) for k in range(3)],
                         [411, 412, 713])

    def test_load_thermal_variable_curve_cells_move_on_every_set(self):
        inner = ("*LOAD_THERMAL_VARIABLE\n"
                 + _row(5, 6, 8) + "\n"
                 + _row(1.0, 0.0, 9, 1.0, 0.0, 10) + "\n"
                 + _row(11, 12, 13) + "\n"
                 + _row(1.0, 0.0, 21, 1.0, 0.0, 22) + "\n")
        out = self._offset(inner, idsoff=400, iddoff=700,
                           idfoff=500).splitlines()
        self.assertEqual([int(out[0][k * 10:(k + 1) * 10]) for k in range(3)],
                         [405, 406, 708])
        self.assertEqual(int(out[1][20:30]), 509)      # LCID, set 1
        self.assertEqual(int(out[1][50:60]), 510)      # LCIDE, set 1
        self.assertEqual([int(out[2][k * 10:(k + 1) * 10]) for k in range(3)],
                         [411, 412, 713])
        self.assertEqual(int(out[3][20:30]), 521)      # LCID, set 2
        self.assertEqual(int(out[3][50:60]), 522)      # LCIDE, set 2

    def test_load_thermal_row_spellings_offset_every_row(self):
        for kw, rows, offs, want in (
                ("LOAD_THERMAL_CONSTANT_NODE",
                 [(1, 100.0), (2, 200.0), (3, 300.0)],
                 {"idnoff": 200}, [201, 202, 203]),
                ("LOAD_THERMAL_VARIABLE_NODE",
                 [(1, 1.0, 0.0, 9), (2, 1.0, 0.0, 9), (3, 1.0, 0.0, 9)],
                 {"idnoff": 200}, [201, 202, 203]),
                ("LOAD_THERMAL_LOAD_CURVE",
                 [(9, 0), (10, 0), (11, 0)],
                 {"idfoff": 500}, [509, 510, 511])):
            inner = f"*{kw}\n" + "".join(_row(*r) + "\n" for r in rows)
            out = self._offset(inner, **offs).splitlines()
            self.assertEqual([int(ln[0:10]) for ln in out], want, kw)

    def test_section_shell_thermal_option_cell_is_not_an_id(self):
        # *SECTION_SHELL_THERMAL's option card carries ITHELFM ("Thermal shell
        # formulation", Keyword971_R10.1/PROPERTY/SectShll.cfg:53), a
        # formulation FLAG — NOT the *MAT_THERMAL_* id *PART's TMID names. The
        # corpus carrier 07_metalstrip.k writes 1 and 2 there while both its
        # parts state TMID 1, so rewriting it under IDMOFF would corrupt the
        # element formulation of every included shell part.
        inner = ("*SECTION_SHELL_THERMAL\n"
                 + _row(4, 2, 1.0, 5, 1.0, 0, 0, 0) + "\n"
                 + _row(1.0, 1.0, 1.0, 1.0) + "\n"
                 + _row(2) + "\n")
        out = self._offset(inner, idmoff=1000, idroff=600).splitlines()
        self.assertEqual(int(out[0][0:10]), 604)        # SECID -> IDROFF
        self.assertEqual(int(out[2][0:10]), 2)          # ITHELFM untouched

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


#: The five ``*MAT_ADD_THERMAL_EXPANSION`` carriers in the r14 verification
#: corpus. Outside the repository, so the case skips when the tree is absent —
#: but when it IS there this is the only test that runs the batch against decks
#: nobody wrote for it.
_R14 = ("C:/Users/pmqua/PycharmProjects/FEM_solver/verification/"
        "dynaexamples_r14_ton-mm-s")
CARRIERS = [
    _R14 + "/thermal/thermal-expansion/thermal-load/main_steel_frame.k",
    _R14 + "/thermal/thermal-expansion/mat-add/main_steel_frame.k",
    _R14 + "/thermal/thick-thin-shells/07_metalstrip.k",
    _R14 + "/nvh/example-06-04/6.4.tbl.psd.intermittent.k",
    _R14 + "/nvh/example-06-04/6.4.tbl.psd.thermal-1.k",
]


class CorpusCarrierTests(unittest.TestCase):
    def test_every_carrier_converts_and_emits_the_expansion_pair(self):
        for path in CARRIERS:
            if not os.path.exists(path):
                self.skipTest(f"corpus tree absent: {path}")
            with self.subTest(deck=os.path.basename(os.path.dirname(path))):
                tmp = tempfile.TemporaryDirectory()
                res = convert(path, os.path.join(tmp.name, "d"),
                              write_log=False)
                with open(res.starter_path) as fh:
                    starter = fh.read()
                # The pair is mandatory: a /THERM_STRESS without a /HEAT/MAT is
                # ERROR 1129 and the deck does not start.
                ts = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                      if ln.startswith("/THERM_STRESS/MAT/")}
                heat = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                        if ln.startswith("/HEAT/MAT/")}
                self.assertTrue(ts, "no /THERM_STRESS/MAT emitted")
                self.assertTrue(ts <= heat,
                                f"/THERM_STRESS on {ts - heat} with no "
                                "/HEAT/MAT — starter ERROR 1129")
                # Every Fct_ID_T must resolve: an unknown one is accepted at 0
                # errors and reinterpreted as an internal index.
                functs = {int(ln.rsplit("/", 1)[1])
                          for ln in starter.splitlines()
                          if ln.startswith("/FUNCT/")}
                for mid in sorted(ts):
                    body = _block(starter, f"/THERM_STRESS/MAT/{mid}")
                    fid = int(body[1][0:10])
                    self.assertIn(fid, functs,
                                  f"Fct_ID_T {fid} is not a /FUNCT in the deck")
                self.assertNotIn("*MAT_ADD_THERMAL_EXPANSION",
                                 " ".join(res.skipped_keywords))
                tmp.cleanup()

    def test_metalstrip_section_shell_thermal_keeps_its_thickness(self):
        path = CARRIERS[2]
        if not os.path.exists(path):
            self.skipTest("corpus tree absent")
        tmp = tempfile.TemporaryDirectory()
        res = convert(path, os.path.join(tmp.name, "d"), write_log=False)
        with open(res.starter_path) as fh:
            starter = fh.read()
        # Before the *SECTION_SHELL_THERMAL registration the section was lost
        # whole and the starter answered 40 x ERROR 495 "NULL THICKNESS".
        self.assertNotIn("SECTION_SHELL_THERMAL",
                         " ".join(res.skipped_keywords))
        self.assertIn("/PROP/SHELL/1", starter)
        thick = [ln for ln in _block(starter, "/PROP/SHELL/1")
                 if not ln.startswith("#")]
        self.assertTrue(any("3" in ln for ln in thick), thick)
        tmp.cleanup()


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



# ═════════════════════════════════════════════════════════════════════════════
# Post-review verification: id namespaces, the /SECT spring group, the
# exempted-node temperature and the refused-group split
# ═════════════════════════════════════════════════════════════════════════════

#: A solid block cut by a plane at z = 5, plus a 1D element from node 9 to
#: node 10 that crosses it. `{ONED}` and `{EXTRA}` are substituted per case.
SECT_MESH = (
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
    "         9            20.0             0.0             0.0\n"
    "        10            20.0             0.0            10.0\n"
    "        11            30.0             0.0             0.0\n"
    "        12            30.0             0.0            10.0\n"
    "        13             0.0             0.0             5.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "{ONED}"
    "*PART\n"
    "solid\n" + _row(1, 1, 1) + "\n"
    "*SECTION_SOLID\n" + _row(1, 1) + "\n"
    "*MAT_ELASTIC\n" + _row(1, "7.8500E-9", 210000.0, 0.3) + "\n"
    "{EXTRA}"
    "*DATABASE_CROSS_SECTION_PLANE\n"
    + _row(0, 0.0, 0.0, 5.0, 0.0, 0.0, 10.0, 0.0) + "\n"
    "*CONTROL_TERMINATION\n"
    "     0.001\n"
    "*END\n"
)

#: A plain elastic beam on part 2, element id 50, crossing the plane.
PLAIN_BEAM = (
    "*ELEMENT_BEAM\n" + _row(50, 2, 9, 10, 13) + "\n",
    "*PART\nplain beam\n" + _row(2, 2, 2) + "\n"
    "*SECTION_BEAM\n" + _row(2, 1, 1.0, 2.0, 2.0, 0) + "\n"
    + _row(10.0, 10.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0) + "\n"
    "*MAT_ELASTIC\n" + _row(2, "7.8500E-9", 210000.0, 0.3) + "\n",
)

#: An *ELEMENT_DISCRETE that REUSES element id 50 — legal LS-DYNA, because
#: *ELEMENT_BEAM and *ELEMENT_DISCRETE are separate id namespaces.
DISCRETE_50 = (
    "*ELEMENT_DISCRETE\n" + _row(50, 3, 11, 12, 0, 0.0, 0, 0.0) + "\n"
    "*PART\ndiscrete\n" + _row(3, 3, 3) + "\n"
    "*SECTION_DISCRETE\n" + _row(3, 0, 0.0, 0, 0.0, 0.0) + "\n"
    "*MAT_SPRING_ELASTIC\n" + _row(3, 100.0) + "\n"
)

#: A *MAT_SPOTWELD beam on part 2, element id 50: the writer really does
#: re-route it to a /SPRING.
SPOTWELD_BEAM = (
    "*ELEMENT_BEAM\n" + _row(50, 2, 9, 10, 0) + "\n",
    "*PART\nspotweld\n" + _row(2, 2, 2) + "\n"
    "*SECTION_BEAM\n" + _row(2, 9, 1.0, 0.0, 0.0, 0) + "\n"
    + _row(2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
    "*MAT_SPOTWELD\n"
    + _row(2, "7.8500E-9", 210000.0, 0.3, 400.0, 0.0, 0.0, 0.0) + "\n",
)


def _sect(oned, extra=""):
    return SECT_MESH.replace("{ONED}", oned).replace("{EXTRA}", extra)


def _sect_tail(starter: str):
    """The /SECT tail card as a list of ints:
    grbric, grshel, grtrus, grbeam, grsprg, grtria, Niter, Iframe."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("#grbric_ID"):
            row = lines[i + 1]
            cols = [(0, 10), (20, 30), (30, 40), (40, 50), (50, 60),
                    (60, 70), (70, 80), (90, 100)]
            return [int(row[a:b] or 0) for a, b in cols]
    raise AssertionError("no /SECT tail card in the deck")


class CrossSectionIdNamespaceTests(unittest.TestCase):
    def test_a_plain_beam_sharing_an_eid_with_a_discrete_stays_in_the_section(self):
        # LS-DYNA element ids are PER-TYPE namespaces: *ELEMENT_BEAM 50 and
        # *ELEMENT_DISCRETE 50 are both legal in one deck (#125's "one cell,
        # two id namespaces" class). Testing a beam eid against the GLOBAL
        # /SPRING id set drops the real beam from the section's /GRBEAM group
        # under a warning blaming a re-route that never happened — measured
        # against master, which keeps it.
        rows, parts = PLAIN_BEAM
        _r, starter = _convert(_sect(rows, parts + DISCRETE_50))
        self.assertIn("/BEAM/2", starter)          # the beam IS emitted
        grbeam = _headers(starter, "/GRBEAM/BEAM/")
        self.assertEqual(len(grbeam), 1, starter)
        self.assertEqual(_ids_of_group(starter, grbeam[0]), [50])
        self.assertEqual(_sect_tail(starter)[3],
                         int(grbeam[0].rsplit("/", 1)[1]))
        self.assertNotIn("re-routes them to a SPRING", " ".join(_r.warnings))

    def test_a_rerouted_connector_gets_the_sect_grsprg_group(self):
        # A *MAT_SPOTWELD beam really is a /SPRING in the emitted deck, so its
        # eid belongs in the /SECT card's grsprg_ID column, not /GRBEAM.
        # sect.cfg:37 types grsprg_id as SUBTYPES = (/SETS/GRSPRI) and
        # hm_read_sect.F:301/548 resolves it with ELEGROR(...,'SPRI') —
        # starter-validated at 0 errors, and the engine reports a NON-ZERO
        # /TH/SECTIO channel with the group against exactly 0.0 without it.
        rows, parts = SPOTWELD_BEAM
        _r, starter = _convert(_sect(rows, parts))
        grsprg = _headers(starter, "/GRSPRI/SPRI/")
        self.assertEqual(len(grsprg), 1, starter)
        self.assertEqual(_ids_of_group(starter, grsprg[0]), [50])
        tail = _sect_tail(starter)
        self.assertEqual(tail[4], int(grsprg[0].rsplit("/", 1)[1]))
        self.assertEqual(tail[3], 0)               # NOT in the beam group
        self.assertEqual(_headers(starter, "/GRBEAM/BEAM/"), [])

    def test_history_beam_keeps_a_beam_whose_eid_matches_a_muscle_discrete(self):
        # The same namespace rule on the /TH door: *DATABASE_HISTORY_BEAM
        # names *ELEMENT_BEAM ids, so a *MAT_SPRING_MUSCLE DISCRETE with the
        # same eid must not take the beam out of the group.
        rows, parts = PLAIN_BEAM
        muscle = (
            "*ELEMENT_DISCRETE\n" + _row(50, 3, 11, 12, 0, 0.0, 0, 0.0) + "\n"
            "*PART\nmuscle\n" + _row(3, 3, 15) + "\n"
            "*SECTION_DISCRETE\n" + _row(3, 0, 0.0, 0, 0.0, 0.0) + "\n"
            "*MAT_SPRING_MUSCLE\n"
            + _row(15, 10.0, 100.0, 1.0, 0.5, 1000.0, 1.0, 1.0) + "\n"
            + _row(0.0, 1.5, 3.0) + "\n"
            "*DATABASE_HISTORY_BEAM\n" + _row(50) + "\n")
        _r, starter = _convert(_sect(rows, parts + muscle))
        beam_groups = [h for h in _headers(starter, "/TH/BEAM/")]
        self.assertEqual(len(beam_groups), 1, starter)
        self.assertIn(50, _ids_of_group(starter, beam_groups[0]))


class ExemptedNodeTemperatureTests(unittest.TestCase):
    #: NSID 0 (all nodes) minus NSIDEX 11 = {2, 3}, driven at 500; the two
    #: exempted nodes are held at TE = 20.
    DECK = ("*SET_NODE_LIST\n" + _row(11) + "\n" + _row(2, 3) + "\n"
            "*LOAD_THERMAL_CONSTANT\n" + _row(0, 11, 0) + "\n"
            + _row(500.0, 20.0) + "\n")

    def _run(self):
        return _convert(_thermal(CARRIER_EXPANSION + self.DECK))

    def test_te_is_the_exempted_nodes_own_temperature(self):
        # Vol I R17 p.33-167: "TE — Temperature of exempted nodes (optional)".
        # It is NOT a second field applied to the expansion term alone.
        _r, starter = self._run()
        imptemps = _headers(starter, "/IMPTEMP/")
        self.assertEqual(len(imptemps), 2, starter)
        groups = {}
        for h in imptemps:
            body = _block(starter, h)
            rows = [ln for ln in body if not ln.startswith("#")]
            gid = int(rows[1][20:30])
            fid = int(rows[1][0:10])
            groups[tuple(_ids_of_group(starter, f"/GRNOD/NODE/{gid}"))] = \
                _funct_points(starter, fid)[0][1]
        self.assertEqual(groups[(2, 3)], 20.0)
        self.assertEqual(groups[(1, 4, 5, 6, 7, 8, 9, 10, 11, 12)], 500.0)

    def test_the_companion_initemp_does_not_reach_the_exempted_nodes(self):
        # An /INITEMP over the WHOLE set beside an /IMPTEMP over
        # set-minus-NSIDEX would start the exempted nodes at the very
        # temperature the card exempts them from.
        _r, starter = self._run()
        got = {}
        for h in _headers(starter, "/INITEMP/"):
            rows = [ln for ln in _block(starter, h) if not ln.startswith("#")]
            gid = int(rows[1][20:30])
            got[tuple(_ids_of_group(starter, f"/GRNOD/NODE/{gid}"))] = \
                float(rows[1][0:20])
        self.assertEqual(got[(2, 3)], 20.0)
        self.assertEqual(got[(1, 4, 5, 6, 7, 8, 9, 10, 11, 12)], 500.0)

    def test_te_without_nsidex_is_named_and_dropped(self):
        deck = ("*LOAD_THERMAL_CONSTANT\n" + _row(0, 0, 0) + "\n"
                + _row(500.0, 20.0) + "\n")
        r, starter = _convert(_thermal(CARRIER_EXPANSION + deck))
        self.assertEqual(len(_headers(starter, "/IMPTEMP/")), 1)
        self.assertIn("exempts no node at all", " ".join(r.warnings))

    def test_unresolvable_lcide_is_named_not_guessed(self):
        deck = ("*SET_NODE_LIST\n" + _row(11) + "\n" + _row(2, 3) + "\n"
                "*LOAD_THERMAL_VARIABLE\n" + _row(0, 11, 0) + "\n"
                + _row(1.0, 0.0, 7, 1.0, 5.0, 404) + "\n"
                "*DEFINE_CURVE\n" + _row(7) + "\n"
                + _row16(0.0, 20.0) + "\n" + _row16(1.0, 120.0) + "\n")
        r, starter = _convert(_thermal(CARRIER_EXPANSION + deck))
        self.assertEqual(len(_headers(starter, "/IMPTEMP/")), 1)
        joined = " ".join(r.warnings)
        self.assertIn("LCIDE=404", joined)
        self.assertIn("exempted nodes", joined)

    def test_a_scaled_exempt_temperature_without_lcide_is_not_invented(self):
        deck = ("*SET_NODE_LIST\n" + _row(11) + "\n" + _row(2, 3) + "\n"
                "*LOAD_THERMAL_VARIABLE\n" + _row(0, 11, 0) + "\n"
                + _row(1.0, 0.0, 7, 2.5, 5.0, 0) + "\n"
                "*DEFINE_CURVE\n" + _row(7) + "\n"
                + _row16(0.0, 20.0) + "\n" + _row16(1.0, 120.0) + "\n")
        r, starter = _convert(_thermal(CARRIER_EXPANSION + deck))
        self.assertEqual(len(_headers(starter, "/IMPTEMP/")), 1)
        self.assertIn("Guessing one would fabricate", " ".join(r.warnings))


class RefusedExpansionGroupTests(unittest.TestCase):
    def test_a_refused_group_does_not_inherit_the_other_cards_expansion(self):
        # Two cards on two parts that SHARE one MID, the card on the LOWER pid
        # unresolvable. The surviving group must NOT keep the original
        # material id: the refused part still points at it, and would silently
        # expand at the OTHER card's coefficient while the warning says the
        # material was neither carded nor split.
        extra = ("*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 404, 0.0) + "\n"
                 "*MAT_ADD_THERMAL_EXPANSION\n" + _row(2, 0, "2.40000E-5")
                 + "\n" + DRIVER)
        r, starter = _convert(_thermal(extra))
        mids = {}
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/PART/"):
                mids[int(ln.rsplit("/", 1)[1])] = int(lines[i + 2][10:20])
        carded = {int(h.rsplit("/", 1)[1])
                  for h in _headers(starter, "/THERM_STRESS/MAT/")}
        self.assertIn(mids[2], carded)              # the resolvable card
        self.assertNotIn(mids[1], carded)           # the refused one
        self.assertNotEqual(mids[1], mids[2])
        self.assertIn("LCID=404", " ".join(r.warnings))

    def test_groups_that_together_name_every_part_still_keep_the_mid(self):
        # The review round's own case must not regress: with BOTH cards
        # resolvable the last group keeps the original id and no orphan /MAT
        # is left behind.
        extra = ("*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(1, 0, "1.20000E-5") + "\n"
                 "*MAT_ADD_THERMAL_EXPANSION\n"
                 + _row(2, 0, "2.40000E-5") + "\n" + DRIVER)
        _r, starter = _convert(_thermal(extra))
        self.assertEqual(len(_headers(starter, "/MAT/")), 2, starter)
        self.assertEqual(len(_headers(starter, "/THERM_STRESS/MAT/")), 2)


class InertRestatementTests(unittest.TestCase):
    def test_an_inert_card_says_the_law_was_restated(self):
        # A *MAT_ELASTIC whose every part is a shell is restated as
        # /MAT/LAW36 so the expansion can reach the through-thickness
        # stresses. That costs -4.6 % of the time step, so a deck that ends
        # up with NO driver must be told its law changed for a card that does
        # nothing.
        deck = (
            "*KEYWORD\n"
            "*NODE\n"
            "         1             0.0             0.0             0.0\n"
            "         2            10.0             0.0             0.0\n"
            "         3            10.0             1.0             0.0\n"
            "         4             0.0             1.0             0.0\n"
            "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
            "*PART\nstrip\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2, 1.0, 5) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            "*MAT_ELASTIC\n" + _row(1, "7.8500E-9", 210000.0, 0.3) + "\n"
            "*MAT_ADD_THERMAL_EXPANSION\n"
            + _row(1, 0, "1.20000E-5") + "\n"
            "*CONTROL_TERMINATION\n     0.001\n*END\n")
        r, starter = _convert(deck)
        self.assertIn("/MAT/LAW36/1", starter)
        joined = " ".join(r.warnings)
        self.assertIn("is INERT on this deck", joined)
        self.assertIn("RESTATED as /MAT/LAW36 for a thermal expansion that "
                      "turns out to be INERT", joined)


class MuscleWarningTextTests(unittest.TestCase):
    def test_the_manual_quote_does_not_carry_the_deck_prefix(self):
        # The quoted sentence is the MANUAL's, so it must name the bare cell,
        # not "*MAT_MUSCLE mid=1: SFR".
        state = _dispatch("*KEYWORD\n*MAT_MUSCLE\n"
                          + _row(1, "1.0000E-9", 1.25, 10.0, 0.3, 0.15, 5.0,
                                 2.0) + "\n"
                          + _row(0.5, 7.0, 1.0, 1.0, 0.0) + "\n*END\n")
        hit = [w for w in state.warnings if "DISCARDS it" in w]
        self.assertEqual(len(hit), 1, state.warnings)
        self.assertTrue(hit[0].startswith("*MAT_MUSCLE mid=1: SFR=7"), hit[0])
        self.assertIn("'SFR ... GE.0.0: Constant value of 1.0 is used'",
                      hit[0])
        self.assertNotIn("'*MAT_MUSCLE mid=1: SFR ...", hit[0])


class MuscleZeroPassiveTests(unittest.TestCase):
    def test_a_zero_force_muscle_mints_no_orphan_passive_curve(self):
        # _resolve_fpe EMITS its function as it mints it, so deciding the
        # zero-force case afterwards left a 100-row exponential /FUNCT in the
        # deck referenced by nothing.
        deck = (
            "*KEYWORD\n"
            "*NODE\n"
            "         1             0.0             0.0             0.0\n"
            "         2            10.0             0.0             0.0\n"
            "*ELEMENT_DISCRETE\n" + _row(1, 1, 1, 2, 0, 0.0, 0, 0.0) + "\n"
            "*PART\nmuscle\n" + _row(1, 1, 15) + "\n"
            "*SECTION_DISCRETE\n" + _row(1, 0, 0.0, 0, 0.0, 0.0) + "\n"
            "*MAT_SPRING_MUSCLE\n"
            + _row(15, 10.0, 100.0, 1.0, 0.5, 0.0, 1.0, 1.0) + "\n"
            + _row(0.0, 1.5, 3.0) + "\n"
            "*CONTROL_TERMINATION\n     0.001\n*END\n")
        _r, starter = _convert(deck)
        fpe = [h for h in _headers(starter, "/FUNCT/")
               if "FPE" in (_block(starter, h) or [""])[0]]
        self.assertEqual(len(fpe), 1, [_block(starter, h)[0] for h in fpe])
        pts = _funct_points(starter, int(fpe[0].rsplit("/", 1)[1]))
        self.assertEqual([y for _x, y in pts], [0.0, 0.0])
        self.assertEqual(len(pts), 2)

if __name__ == "__main__":
    unittest.main()
