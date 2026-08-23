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


def _fields(row: str, w: int = 20):
    """Slice a fixed-width Radioss card row into stripped w-char cells."""
    return [row[i:i + w].strip() for i in range(0, len(row.rstrip()), w)]


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
