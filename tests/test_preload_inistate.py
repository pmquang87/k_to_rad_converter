"""Tests for the PRELOAD / INITIAL-STATE batch:

  *INITIAL_STRAIN_SHELL[_SET]  → /INISHE/STRA_F/GLOB + /INISH3/STRA_F/GLOB
  *INITIAL_STRESS_SECTION      → /PRELOAD (+ a dedicated /SECT + /GRBRIC)
  *INITIAL_AXIAL_FORCE_BEAM    → /PRELOAD/AXIAL (+ /GRBEAM, /GRSPRI, /FUNCT)

Kept in its own module (like tests/test_inistate_sect.py) so the additions do
not collide with other in-flight work on the big test files.
"""

import math
import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import HANDLERS, INITIAL_STATE_PRELOAD_KEYWORDS, dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState
from k2rad.writer.preload import (_preload_curve_window,
                                  _preload_truncated_points)
from k2rad.writer import _f, _i


# ── Harness ──────────────────────────────────────────────────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _row16(*vals) -> str:
    """LARGE-format (16-char) card row."""
    return "".join(f"{v:>16}" for v in vals)


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
        if ln == header:
            out = []
            for data in lines[i + 1:]:
                if data.startswith("/"):
                    break
                out.append(data)
            return out
    return None


def _ids_in(starter: str, header_prefix: str):
    """Integer ids listed in the first block whose header starts with
    *header_prefix* (title line skipped)."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(header_prefix):
            ids = []
            for data in lines[i + 2:]:
                if data.startswith("/"):
                    break
                if data.startswith("#"):
                    continue
                ids.extend(int(t) for t in data.split() if t.lstrip("-").isdigit())
            return ids
    return None


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


# ── Shared deck fragments ────────────────────────────────────────────────────

#: Two 4-node shells (eids 1, 2) plus a collapsed triangle (eid 3 → /SH3N),
#: *SECTION_SHELL NIP = 5 so nb_integr=2 is provably NOT the property N.
SHELLS = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             2.0             0.0             0.0\n"
    "       6             2.0             1.0             0.0\n"
    "       7             3.0             0.5             0.0\n"
    "*PART\n"
    "strip\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2                   5\n"
    "       1.0\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       1       2       5       6       3\n"
    "       3       1       5       7       6       6\n"
    "*SET_SHELL_LIST\n"
    "        77\n"
    "         1         3\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

#: Distinct value per slot so a swapped column is detectable, and
#: eps_XY != eps_YZ != eps_ZX so a shear permutation is too.
STRAIN_SMALL = (
    "*INITIAL_STRAIN_SHELL\n"
    + _row(1, 1, 2) + "\n"
    + _row(0.011, 0.022, 0.033, 0.044, 0.055, 0.066, -1.0) + "\n"
    + _row(0.111, 0.122, 0.133, 0.144, 0.155, 0.166, 1.0) + "\n"
)


# ═════════════════════════════════════════════════════════════════════════════
# *INITIAL_STRAIN_SHELL → /INISHE/STRA_F/GLOB
# ═════════════════════════════════════════════════════════════════════════════

class InitialStrainShellTests(unittest.TestCase):
    def test_card_lines_are_column_exact(self):
        _r, starter = _convert(SHELLS.replace("{EXTRA}", STRAIN_SMALL))
        body = _block(starter, "/INISHE/STRA_F/GLOB")
        self.assertIsNotNone(body, "no /INISHE/STRA_F/GLOB block emitted")
        data = [ln for ln in body if not ln.startswith("#")]
        # Card 1: shell_ID nb_integr npg Thick — nb_integr is 2 (the two
        # extreme stations), npg is 1 unconditionally, Thick 0 keeps the
        # property thickness. *SECTION_SHELL NIP is 5, proving nb_integr is
        # NOT the property N here (the STRS_F cross-check does not apply).
        self.assertEqual(data[0], f"{_i(1)}{_i(2)}{_i(1)}{_f(0.0)}")
        self.assertEqual(data[1], f"{_f(0.011)}{_f(0.022)}{_f(0.033)}")
        self.assertEqual(data[2], f"{_f(0.044)}{_f(0.055)}{_f(0.066)}{_f(-1.0)}")
        self.assertEqual(data[3], f"{_f(0.111)}{_f(0.122)}{_f(0.133)}")
        self.assertEqual(data[4], f"{_f(0.144)}{_f(0.155)}{_f(0.166)}{_f(1.0)}")
        self.assertEqual(len(data), 5)

    def test_shear_is_copied_one_to_one_and_the_convention_is_stated(self):
        r, starter = _convert(SHELLS.replace("{EXTRA}", STRAIN_SMALL))
        body = _block(starter, "/INISHE/STRA_F/GLOB")
        shear = [ln for ln in body if not ln.startswith("#")][2]
        # 0.044 on the card, NOT 0.022: the starter's CG2LEPS doubles it into
        # the engineering shear held in GBUF%STRA, so eps_XY must be the
        # TENSOR component and LS-DYNA's EPSxy is copied unscaled.
        self.assertTrue(shear.startswith(_f(0.044)))
        self.assertTrue(any("TENSOR shear" in w for w in r.warnings))

    def test_large_format_reads_five_plus_two_sixteen_wide_fields(self):
        extra = ("*INITIAL_STRAIN_SHELL\n"
                 + _row(1, 1, 2, 1) + "\n"
                 + _row16(0.011, 0.022, 0.033, 0.044, 0.055) + "\n"
                 + _row16(0.066, -1.0) + "\n"
                 + _row16(0.111, 0.122, 0.133, 0.144, 0.155) + "\n"
                 + _row16(0.166, 1.0) + "\n")
        _r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(data[1], f"{_f(0.011)}{_f(0.022)}{_f(0.033)}")
        self.assertEqual(data[2], f"{_f(0.044)}{_f(0.055)}{_f(0.066)}{_f(-1.0)}")
        self.assertEqual(data[4], f"{_f(0.144)}{_f(0.155)}{_f(0.166)}{_f(1.0)}")

    def test_large_flag_is_field_3_not_field_5(self):
        # *INITIAL_STRESS_SHELL puts LARGE in cell 6; *INITIAL_STRAIN_SHELL
        # puts it in cell 4 (cfg :110). Reading the stress position would take
        # LARGE=0 here and slice the 16-wide cards at width 10.
        extra = ("*INITIAL_STRAIN_SHELL\n"
                 + _row(1, 1, 2, 0, 1, 1, 1) + "\n"    # cells 5..7 non-zero
                 + _row(0.011, 0.022, 0.033, 0.044, 0.055, 0.066, -1.0) + "\n"
                 + _row(0.111, 0.122, 0.133, 0.144, 0.155, 0.166, 1.0) + "\n")
        _r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(data[1], f"{_f(0.011)}{_f(0.022)}{_f(0.033)}")

    def test_ilocal_is_read_from_cols_71_80_and_warn_dropped(self):
        # cell 8 of "%10d%10d%10d%10d%10s%10s%10s%10d" — three blanks after
        # LARGE (Vol I R17 p.28-67). This is the ONLY initial-state keyword with
        # an ILOCAL field; *INITIAL_STRESS_SHELL's card 1 ends at field 8 with
        # NTHHSV, so a cell-9 read there would be reading nothing LS-DYNA writes.
        card = _row(1, 1, 2) + " " * 49 + "1"
        extra = ("*INITIAL_STRAIN_SHELL\n" + card + "\n"
                 + _row(0.011, 0.022, 0.033, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.111, 0.122, 0.133, 0.0, 0.0, 0.0, 1.0) + "\n")
        self.assertEqual(len(card), 80)
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        self.assertNotIn("/INISHE/STRA_F", starter)
        self.assertNotIn("/INISH3/STRA_F", starter)
        self.assertTrue(any("ILOCAL=1" in w and "DROPPED" in w
                            for w in r.warnings))

    def test_sh3n_goes_to_inish3_and_quads_to_inishe(self):
        extra = ("*INITIAL_STRAIN_SHELL\n"
                 + _row(1, 1, 2) + "\n"
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n"
                 + _row(3, 1, 2) + "\n"
                 + _row(0.03, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.04, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        _r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        quad = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        tri = [ln for ln in _block(starter, "/INISH3/STRA_F/GLOB")
               if not ln.startswith("#")]
        self.assertEqual(int(quad[0][:10]), 1)
        self.assertEqual(int(tri[0][:10]), 3)
        self.assertEqual(tri[1], f"{_f(0.03)}{_f(0.0)}{_f(0.0)}")

    def test_set_spelling_expands_and_ignores_nplane_nthick(self):
        extra = ("*INITIAL_STRAIN_SHELL_SET\n"
                 + _row(77, 4, 5) + "\n"      # NPLANE/NTHICK must be IGNORED
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        quad = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        tri = [ln for ln in _block(starter, "/INISH3/STRA_F/GLOB")
               if not ln.startswith("#")]
        self.assertEqual(int(quad[0][:10]), 1)     # set 77 = shells 1 and 3
        self.assertEqual(int(tri[0][:10]), 3)
        self.assertTrue(any("NPLANE/NTHICK are IGNORED" in w
                            for w in r.warnings))

    def test_nplane_gt_1_is_averaged_per_station(self):
        rows = []
        for v in (0.01, 0.03, 0.05, 0.07):          # bottom station, mean 0.04
            rows.append(_row(v, 0.02, 0.0, 0.0, 0.0, 0.0, -1.0))
        for v in (0.11, 0.13, 0.15, 0.17):          # top station,    mean 0.14
            rows.append(_row(v, 0.02, 0.0, 0.0, 0.0, 0.0, 1.0))
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 4, 2) + "\n"
                 + "\n".join(rows) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(data[1], f"{_f(0.04)}{_f(0.02)}{_f(0.0)}")
        self.assertEqual(data[3], f"{_f(0.14)}{_f(0.02)}{_f(0.0)}")
        self.assertTrue(any("AVERAGED per through-" in w for w in r.warnings))

    def test_the_nplane_report_does_not_state_the_cards_npg(self):
        # The handler cannot know the writer's npg: it is 4 on Ishell 12 once
        # the deck also carries an initial-STRESS block. Asserting npg=1 there
        # contradicted the emitted card (measured: "1 5 4 0").
        rows = ([_row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0)] * 4
                + [_row(0.03, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)] * 4)
        extra = STRESS_5 + ("*INITIAL_STRAIN_SHELL\n" + _row(1, 4, 2) + "\n"
                            + "\n".join(rows) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        card = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")][0]
        self.assertEqual(int(card[20:30]), 4)          # the card says npg = 4
        w = [x for x in r.warnings if "AVERAGED per through-" in x]
        self.assertTrue(w)
        self.assertNotIn("npg=1", w[0])

    def test_more_than_two_stations_keeps_the_extremes_and_warns(self):
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 3) + "\n"
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                 + _row(0.03, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(data[0], f"{_i(1)}{_i(2)}{_i(1)}{_f(0.0)}")
        self.assertEqual(data[1], f"{_f(0.01)}{_f(0.0)}{_f(0.0)}")
        self.assertEqual(data[3], f"{_f(0.03)}{_f(0.0)}{_f(0.0)}")
        self.assertTrue(any("MIN(2,NPP)" in w for w in r.warnings))

    def test_single_station_is_written_at_minus_one_and_plus_one(self):
        # Two records at the SAME parametric position is starter ERROR 1904.
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 1) + "\n"
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(data[2][-20:], _f(-1.0))
        self.assertEqual(data[4][-20:], _f(1.0))
        self.assertEqual(data[1], data[3])          # pure membrane
        self.assertTrue(any("ERROR 1904" in w for w in r.warnings))

    def test_unknown_element_is_warned_never_silently_dropped(self):
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(999, 1, 2) + "\n"
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        self.assertNotIn("/INISHE/STRA_F", starter)
        self.assertTrue(any("999" in w and "not 4-node /SHELL or /SH3N" in w
                            for w in r.warnings))

    def test_blank_strain_card_does_not_swallow_the_next_record(self):
        # An all-blank strain card is legal LS-DYNA (every component defaults
        # to 0.0). A "next non-blank row" walk would read element 3's card 1
        # as element 1's second station and lose element 3 entirely (#119).
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 2) + "\n"
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + "\n"                                    # blank top station
                 + _row(3, 1, 2) + "\n"
                 + _row(0.03, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.04, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        _r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        quad = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        tri = [ln for ln in _block(starter, "/INISH3/STRA_F/GLOB")
               if not ln.startswith("#")]
        self.assertEqual(int(quad[0][:10]), 1)
        self.assertIsNotNone(tri, "element 3 was swallowed by the blank card")
        self.assertEqual(int(tri[0][:10]), 3)
        self.assertEqual(tri[1], f"{_f(0.03)}{_f(0.0)}{_f(0.0)}")

    def test_an_element_named_twice_is_warned(self):
        # The starter keeps one slot per element and the last record read
        # wins, silently (hm_read_inistate_d00.F:2486-2492).
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 2) + "\n"
                 + _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n"
                 + "*INITIAL_STRAIN_SHELL_SET\n" + _row(77) + "\n"
                 + _row(0.05, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0) + "\n"
                 + _row(0.06, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        r, _starter = _convert(SHELLS.replace("{EXTRA}", extra))
        self.assertTrue(any("named by more than one record" in w
                            for w in r.warnings))

    def test_istrain_is_forced_on_or_the_block_is_inert(self):
        # csigini.F:165 gates the whole ingest on
        # IF (ISTRAIN /= 0 .AND. ITHKSHEL == 2) — with Istrain=0 the /INISHE
        # block is accepted, echoed and does nothing at all.
        _r, base = _convert(SHELLS.replace("{EXTRA}", ""))
        _r2, with_strain = _convert(SHELLS.replace("{EXTRA}", STRAIN_SMALL))
        def _nip_istrain(starter):
            body = _block(starter, "/PROP/SHELL/1")
            data = [ln for ln in body if not ln.startswith("#")]
            return data[-1][:20]                # card 3: N then Istrain
        self.assertEqual(_nip_istrain(base), f"{_i(5)}{_i(0)}")
        self.assertEqual(_nip_istrain(with_strain), f"{_i(5)}{_i(1)}")

    def test_npg_is_one_even_on_a_batoz_or_qeph_property(self):
        # npg=4 on Ishell=24 (QEPH) is a measured SILENT no-op and npg=4 on
        # Ishell=1..4 is starter ERROR 1904, so npg is 1 for every
        # formulation. ELFORM 2 → Ishell 12 (BATOZ) in this deck.
        _r, starter = _convert(SHELLS.replace("{EXTRA}", STRAIN_SMALL))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(int(data[0][20:30]), 1)

    def test_mesh_survives_and_the_keyword_leaves_skipped(self):
        r, starter = _convert(SHELLS.replace("{EXTRA}", STRAIN_SMALL))
        self.assertNotIn("INITIAL_STRAIN_SHELL", r.skipped_keywords)
        self.assertIn("/SHELL/1", starter)
        self.assertIn("/SH3N/1", starter)

    def test_decks_without_the_keyword_are_byte_identical_to_master(self):
        # The strain emitter draws NO id at all, so a deck without the keyword
        # cannot shift the id stream (#119 fixture rule).
        _r, a = _convert(SHELLS.replace("{EXTRA}", ""))
        _r2, b = _convert(SHELLS.replace("{EXTRA}", ""))
        self.assertEqual(a, b)
        self.assertNotIn("STRA_F", a)


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / *INCLUDE_TRANSFORM coverage
# ═════════════════════════════════════════════════════════════════════════════

class DispatchAndOffsetCoverageTests(unittest.TestCase):
    def test_parser_and_offset_tables_cover_the_same_spellings(self):
        # ONE source (#116): every spelling the handler reads must also be
        # offsettable, or an *INCLUDE_TRANSFORM keeps its original
        # CSID/LCID/PSID/BSID/EID while the rest of the include moves.
        self.assertTrue(INITIAL_STATE_PRELOAD_KEYWORDS)
        for kw in INITIAL_STATE_PRELOAD_KEYWORDS:
            self.assertIn(kw, HANDLERS, f"{kw} has no handler")
            self.assertIn(kw, _OFFSET_SPECS, f"{kw} has no offset spec")

    def test_title_option_is_stripped_by_the_parser(self):
        state = _dispatch("*KEYWORD\n*INITIAL_STRESS_SECTION_TITLE\n"
                          "bolt preload\n" + _row(5, 6, 7, 8, 0, 0, 0) + "\n"
                          "*END\n")
        self.assertEqual(len(state.ini_stress_sections), 1)
        iss = state.ini_stress_sections[0]
        self.assertEqual((iss.issid, iss.csid, iss.lcid, iss.psid),
                         (5, 6, 7, 8))
        self.assertEqual(iss.title, "bolt preload")

    def test_axial_force_beam_has_no_title_or_id_option(self):
        # Both HEADER lines in Keyword971_R9.3/LOADCOL/
        # initial_axial_force_beam.cfg are the bare keyword.
        state = _dispatch("*KEYWORD\n*INITIAL_AXIAL_FORCE_BEAM\n"
                          + _row(100, 200, 2.5, 1) + "\n*END\n")
        b = state.ini_axial_force_beams[0]
        self.assertEqual((b.bsid, b.lcid, b.kbend), (100, 200, 1))
        self.assertAlmostEqual(b.scale, 2.5)

    def test_blank_scale_defaults_to_one_never_zero(self):
        state = _dispatch("*KEYWORD\n*INITIAL_AXIAL_FORCE_BEAM\n"
                          + _row(100, 200) + "\n*END\n")
        self.assertAlmostEqual(state.ini_axial_force_beams[0].scale, 1.0)
        state = _dispatch("*KEYWORD\n*INITIAL_AXIAL_FORCE_BEAM\n"
                          + _row(100, 200, 0.0) + "\n*END\n")
        self.assertAlmostEqual(state.ini_axial_force_beams[0].scale, 1.0)


class IncludeTransformOffsetTests(unittest.TestCase):
    def _dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def _write(self, d, name, text):
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def _state_and_blocks(self, main_path):
        state = ConversionState()
        blocks = list(parse_k_file(main_path))
        for block in blocks:
            dispatch(block, state)
        return state, blocks

    #: IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF IDDOFF
    OFFSETS = _row(0, 400, 1000, 0, 200, 3000, 40)

    def _main(self, d, child_text):
        self._write(d, "child.k", child_text)
        return self._write(d, "main.k", "\n".join([
            "*KEYWORD", "*INCLUDE_TRANSFORM", "child.k",
            self.OFFSETS, "", "", "", "*END"]) + "\n")

    def test_strain_shell_eid_takes_ideoff_and_values_are_untouched(self):
        d = self._dir()
        main = self._main(d, "\n".join([
            "*KEYWORD", "*INITIAL_STRAIN_SHELL",
            _row(7, 1, 2),
            _row(1.5, 0.022, 0.033, 0.044, 0.055, 0.066, -1.0),
            _row(0.111, 0.122, 0.133, 0.144, 0.155, 0.166, 1.0),
            _row(9, 1, 2),
            _row(0.2, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0),
            _row(0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            "*END"]) + "\n")
        state, _blocks = self._state_and_blocks(main)
        self.assertEqual([r.eid for r in state.ini_strain_shells], [407, 409])
        # A strain of 1.5 must NOT be read as the id 1 and rewritten to 401.
        self.assertAlmostEqual(state.ini_strain_shells[0].layers[0][1], 1.5)
        self.assertAlmostEqual(state.ini_strain_shells[0].layers[1][1], 0.111)

    def test_strain_shell_set_id_takes_idsoff(self):
        d = self._dir()
        main = self._main(d, "\n".join([
            "*KEYWORD", "*INITIAL_STRAIN_SHELL_SET",
            _row(7),
            _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0),
            _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            "*END"]) + "\n")
        state, _blocks = self._state_and_blocks(main)
        self.assertEqual(state.ini_strain_shells[0].eid, 207)
        self.assertTrue(state.ini_strain_shells[0].is_set)

    def test_strain_offset_walk_survives_a_blank_strain_card(self):
        # The offsetter shares handlers.initial_strain_shell_records, so its
        # notion of "a card 1" cannot drift from the handler's.
        d = self._dir()
        main = self._main(d, "\n".join([
            "*KEYWORD", "*INITIAL_STRAIN_SHELL",
            _row(7, 1, 2),
            _row(0.01, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0),
            "",
            _row(9, 1, 2),
            _row(0.02, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0),
            _row(0.03, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            "*END"]) + "\n")
        state, _blocks = self._state_and_blocks(main)
        self.assertEqual([r.eid for r in state.ini_strain_shells], [407, 409])

    def test_stress_section_buckets(self):
        d = self._dir()
        main = self._main(d, "\n".join([
            "*KEYWORD", "*INITIAL_STRESS_SECTION_TITLE",
            "preload",
            #     ISSID CSID LCID PSID  VID IZSHEAR ISTIFF
            _row(1, 2, 3, 4, 5, 1, 6),
            "*END"]) + "\n")
        state, _blocks = self._state_and_blocks(main)
        iss = state.ini_stress_sections[0]
        self.assertEqual(iss.issid, 1)          # IDROFF (0 here) — unchanged
        self.assertEqual(iss.csid, 1002)        # IDPOFF
        self.assertEqual(iss.lcid, 3003)        # IDFOFF
        self.assertEqual(iss.psid, 204)         # IDSOFF
        self.assertEqual(iss.vid, 45)           # IDDOFF
        self.assertEqual(iss.izshear, 1)        # not an id
        self.assertEqual(iss.istiff, 3006)      # IDFOFF (a curve id)

    def test_axial_force_beam_buckets_on_every_repeated_card(self):
        d = self._dir()
        main = self._main(d, "\n".join([
            "*KEYWORD", "*INITIAL_AXIAL_FORCE_BEAM",
            _row(11, 21, 1.5, 0),
            _row(12, 22, 2.5, 2),
            "*END"]) + "\n")
        state, _blocks = self._state_and_blocks(main)
        got = [(b.bsid, b.lcid, b.scale, b.kbend)
               for b in state.ini_axial_force_beams]
        self.assertEqual(got, [(211, 3021, 1.5, 0), (212, 3022, 2.5, 2)])



# ═════════════════════════════════════════════════════════════════════════════
# *INITIAL_STRESS_SECTION → /PRELOAD
# ═════════════════════════════════════════════════════════════════════════════

def _unit(v):
    m = math.sqrt(sum(c * c for c in v))
    return tuple(c / m for c in v)


def _perp_pair(n):
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = sum(a[k] * n[k] for k in range(3))
    e1 = _unit(tuple(a[k] - d * n[k] for k in range(3)))
    e2 = (n[1] * e1[2] - n[2] * e1[1], n[2] * e1[0] - n[0] * e1[2],
          n[0] * e1[1] - n[1] * e1[0])
    return e1, e2


ISS_CARD = _row(7, 1, 1, 0, 0, 0, 0)


def _bar_deck(normal=(0.0, 0.0, 1.0), curve_pts=((0.0, 0.0), (2.0e-4, 1.0)),
              sfo=200.0, offa=0.0, pids=(1, 1, 1, 1), psid_card=0,
              extra="", iss_card=None, bars=1, psid_parts=()):
    """*bars* parallel 1x1x4 bars of four hexas along *normal*, each cut
    through its second brick by one plane.

    The bars are BUILT along the requested normal, so a rotated plane
    exercises the frame construction rather than an axis-aligned special case.
    A second bar (offset 3 units along e1) gives the cut two bricks on two
    parts, which is what makes a PSID restriction observable.
    """
    n = _unit(normal)
    e1, e2 = _perp_pair(n)
    lines = ["*KEYWORD", "*NODE"]
    nid = 1
    bar_layers = []
    for b in range(bars):
        layers = []
        for k in range(5):
            row = []
            for (u, v) in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
                uu = u + 3.0 * b
                p = tuple(k * n[j] + uu * e1[j] + v * e2[j] for j in range(3))
                lines.append(f"{nid:>8}{p[0]:16.8E}{p[1]:16.8E}{p[2]:16.8E}")
                row.append(nid)
                nid += 1
            layers.append(row)
        bar_layers.append(layers)
    all_pids = sorted({p for b in range(bars) for p in
                       (pids if b == 0 else tuple(q + 10 * b for q in pids))})
    for pid in all_pids:
        lines += ["*PART", f"bar{pid}", _row(pid, pid, 1),
                  "*SECTION_SOLID", _row(pid, 1)]
    lines += ["*MAT_ELASTIC", "         1  7.85E-09  210000.0       0.3",
              "*ELEMENT_SOLID"]
    eid = 1
    for b, layers in enumerate(bar_layers):
        bp = pids if b == 0 else tuple(q + 10 * b for q in pids)
        for e in range(4):
            lines.append("".join(f"{v:>8}" for v in
                                 [eid, bp[e]] + layers[e] + layers[e + 1]))
            eid += 1
    lines += ["*SET_PART_LIST", _row(5), _row(*all_pids)]
    if psid_card:
        lines += ["*SET_PART_LIST", _row(psid_card),
                  _row(*(psid_parts or (pids[1],)))]
    mid = tuple(1.5 * n[j] + 0.5 * e1[j] + 0.5 * e2[j] for j in range(3))
    head = tuple(mid[j] + n[j] for j in range(3))
    lines += ["*DATABASE_CROSS_SECTION_PLANE_ID", f"{1:>10}bolt cut",
              _row(5, f"{mid[0]:.8G}", f"{mid[1]:.8G}", f"{mid[2]:.8G}",
                   f"{head[0]:.8G}", f"{head[1]:.8G}", f"{head[2]:.8G}", 3.0),
              "*DEFINE_CURVE", _row(1, 0, 1.0, sfo, offa)]
    for x, y in curve_pts:
        lines.append(f"{x:>20.10G}{y:>20.10G}")
    lines += ["*INITIAL_STRESS_SECTION_TITLE", "bolt one",
              iss_card if iss_card is not None else ISS_CARD]
    if extra:
        lines.append(extra.rstrip("\n"))
    lines += ["*CONTROL_TERMINATION", "    4.0E-4", "*END"]
    return "\n".join(lines) + "\n"


def _nodes_of(starter):
    """{nid: (x, y, z)} over every /NODE block of the starter."""
    out, inblk = {}, False
    for ln in starter.splitlines():
        if ln.startswith("/NODE"):
            inblk = True
            continue
        if not inblk:
            continue
        if ln.startswith("/"):
            inblk = False
            continue
        if ln.startswith("#") or not ln.strip():
            continue
        tok = ln[:10].strip()
        if not tok.lstrip("-").isdigit():
            continue
        out[int(tok)] = (float(ln[10:30]), float(ln[30:50]), float(ln[50:70]))
    return out


def _sect_frame(starter, sect_id):
    card = [ln for ln in _block(starter, f"/SECT/{sect_id}")[1:]
            if not ln.startswith("#")][0]
    return int(card[0:10]), int(card[10:20]), int(card[20:30])


def _frame_normal(starter, sect_id):
    n1, n2, n3 = _sect_frame(starter, sect_id)
    nodes = _nodes_of(starter)
    p1, p2, p3 = nodes[n1], nodes[n2], nodes[n3]
    u = tuple(p2[k] - p1[k] for k in range(3))
    v = tuple(p3[k] - p1[k] for k in range(3))
    return _unit((u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                  u[0] * v[1] - u[1] * v[0]))


class InitialStressSectionTests(unittest.TestCase):
    def test_preload_card_is_column_exact(self):
        _r, starter = _convert(_bar_deck())
        self.assertEqual(_headers(starter, "/PRELOAD/"), ["/PRELOAD/7"])
        body = _block(starter, "/PRELOAD/7")
        self.assertEqual(body[0], "bolt one")
        data = [ln for ln in body[1:] if not ln.startswith("#")][0]
        sect = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        # sect_ID | sens_ID 0 | Itype 2 (stress) | Fct_ID column BLANK |
        # Preload = the curve plateau | Tstart | Tstop
        self.assertEqual(
            data,
            f"{_i(sect)}{_i(0)}{_i(2)}{' ' * 10}"
            f"{_f(200.0)}{_f(0.0)}{_f(2.0e-4)}")
        # Cols 31-40 must stay blank: the Fct_ID cell exists only in
        # FORMAT(radioss2026) and is dropped to IFUNC=0 at /BEGIN 2022, so a
        # function id there would be Preload=plateau + a silently lost ramp.
        self.assertEqual(data[30:40], " " * 10)

    def test_frame_nodes_realize_a_rotated_plane_normal(self):
        nrm = _unit((1.0, 2.0, -3.0))
        _r, starter = _convert(_bar_deck(normal=nrm))
        sect_id = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        got = _frame_normal(starter, sect_id)
        for k in range(3):
            self.assertAlmostEqual(got[k], nrm[k], places=6)

    def test_the_reporting_section_now_realizes_the_plane_normal_too(self):
        """The REVERSE of what this pinned before the SIDE-DEFECT batch.

        The reporting /SECT used to take three best-CONDITIONED MESH nodes,
        which has nothing to do with the cut — measured 26.57 degrees off on a
        +X plane, with the frame origin not even on the plane — and this test
        asserted the mismatch, noting "if this ever starts matching, the
        dedicated section could go". It matches now: item (E) gives the
        reporting section the same synthesized-node construction #127 built
        for the preload one.

        The dedicated preload /SECT is still emitted separately, because the
        two carry different element groups (the preload one is bricks-only,
        intersected with *INITIAL_STRESS_SECTION's own PSID) and different
        node scopes. Merging them is a separate change."""
        nrm = _unit((1.0, 2.0, -3.0))
        _r, starter = _convert(_bar_deck(normal=nrm))
        got = _frame_normal(starter, 1)
        for k in range(3):
            self.assertAlmostEqual(got[k], nrm[k], places=6)

    def test_reporting_section_and_th_sectio_are_untouched(self):
        _r, starter = _convert(_bar_deck())
        sect_hdrs = _headers(starter, "/SECT/")
        self.assertEqual(len(sect_hdrs), 2)         # reporting + dedicated
        self.assertEqual(sect_hdrs[0], "/SECT/1")   # CSID kept for reporting
        # /TH/SECTIO must list the REPORTING section only — a second channel
        # for the same physical cut would double-count it.
        th = _block(starter, _headers(starter, "/TH/SECTIO/")[0])
        ids = [int(ln) for ln in th if ln.strip().isdigit()]
        self.assertEqual(ids, [1])

    def test_psid_restricts_the_preload_bricks_only(self):
        # Two parallel bars: the plane cuts brick 2 (part 2) and brick 6
        # (part 12). PSID 6 names part 12 only, so the PRELOAD group holds
        # brick 6 while the reporting /SECT keeps both — Vol I R17 p.3144,
        # "included in both PSID from this card and the PSID field from the
        # associated *DATABASE_CROSS_SECTION card".
        _r, starter = _convert(_bar_deck(pids=(1, 2, 3, 4), bars=2,
                                         psid_card=6, psid_parts=(12,),
                                         iss_card=_row(7, 1, 1, 6, 0, 0, 0)))
        grp = _headers(starter, "/GRBRIC/BRIC/")
        self.assertEqual(len(grp), 2)
        self.assertEqual(_ids_in(starter, grp[0]), [2, 6])
        self.assertEqual(_ids_in(starter, grp[1]), [6])

    def test_without_psid_every_cut_brick_is_preloaded(self):
        _r, starter = _convert(_bar_deck(pids=(1, 2, 3, 4), bars=2))
        grp = _headers(starter, "/GRBRIC/BRIC/")
        self.assertEqual(_ids_in(starter, grp[0]), [2, 6])
        self.assertEqual(_ids_in(starter, grp[1]), [2, 6])

    def test_vid_overrides_the_plane_normal(self):
        extra = "*DEFINE_VECTOR\n" + _row(4, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        _r, starter = _convert(_bar_deck(extra=extra,
                                         iss_card=_row(7, 1, 1, 0, 4, 0, 0)))
        sect_id = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        got = _frame_normal(starter, sect_id)
        self.assertAlmostEqual(got[0], 1.0, places=6)   # the VID x-axis
        self.assertAlmostEqual(got[2], 0.0, places=6)   # not the bar's +z

    def test_izshear_and_istiff_are_dropped_by_name(self):
        _r2, _s2 = _convert(_bar_deck(iss_card=_row(7, 1, 1, 0, 0, 2, 9)))
        r = _r2
        w = [x for x in r.warnings if "IZSHEAR=2" in x]
        self.assertTrue(w)
        self.assertIn("ISTIFF=9", w[0])
        self.assertIn("no /PRELOAD slot", w[0])

    def test_both_istiff_spellings_are_named_as_curve_ids(self):
        # Vol I R17 p.3144 gives BOTH signs as curve ids — "GT.0: Load curve ID
        # defining stiffness fraction as a function of time" and "LT.0:
        # |ISTIFF| is the load curve ID for the stiffness fraction as a
        # function of time"; the sign only selects whether the preload stress is
        # auto-adjusted +/-10%. The positive spelling used to be reported as a
        # bare "artificial stiffness" flag, so the reader was never told a
        # *DEFINE_CURVE reference had been dropped.
        for istiff, cid in ((9, "9"), (-9, "9")):
            with self.subTest(istiff=istiff):
                r, _s = _convert(_bar_deck(
                    iss_card=_row(7, 1, 1, 0, 0, 0, istiff)))
                w = [x for x in r.warnings if f"ISTIFF={istiff}" in x]
                self.assertTrue(w, list(r.warnings)[:4])
                self.assertIn("*DEFINE_CURVE id in BOTH spellings", w[0])
                self.assertIn(f"curve {cid} is the fraction", w[0])
        # Only the negative spelling claims the id is quoted un-offset.
        rp, _sp = _convert(_bar_deck(iss_card=_row(7, 1, 1, 0, 0, 0, 9)))
        rn, _sn = _convert(_bar_deck(iss_card=_row(7, 1, 1, 0, 0, 0, -9)))
        self.assertFalse(any("un-offset" in x for x in rp.warnings))
        self.assertTrue(any("un-offset" in x for x in rn.warnings))

    def test_missing_curve_emits_nothing(self):
        r, starter = _convert(_bar_deck(iss_card=_row(7, 1, 99, 0, 0, 0, 0)))
        self.assertEqual(_headers(starter, "/PRELOAD/"), [])
        self.assertTrue(any("LCID 99 resolves to no converted" in x
                            for x in r.warnings))

    def test_missing_cross_section_emits_nothing(self):
        r, starter = _convert(_bar_deck(iss_card=_row(7, 88, 1, 0, 0, 0, 0)))
        self.assertEqual(_headers(starter, "/PRELOAD/"), [])
        self.assertTrue(any("ERROR 1243" in x for x in r.warnings))

    def test_curve_scaling_and_offset_reach_the_preload_value(self):
        # SFO=250, OFFA=1e-4: handle_define_curve applies both at parse time,
        # so the window is [1e-4, 3e-4] and the plateau 250.
        _r, starter = _convert(_bar_deck(sfo=250.0, offa=1.0e-4))
        data = [ln for ln in _block(starter, "/PRELOAD/7")[1:]
                if not ln.startswith("#")][0]
        self.assertEqual(data[40:], f"{_f(250.0)}{_f(1.0e-4)}{_f(3.0e-4)}")

    def test_section_without_solids_is_refused(self):
        # A shell-only model: hm_read_preload.F:233-237 answers ERROR 1251.
        deck = SHELLS.replace("{EXTRA}", (
            "*DATABASE_CROSS_SECTION_PLANE_ID\n"
            + f"{1:>10}cut\n"
            + _row(0, 1.5, 0.5, 0.0, 2.5, 0.5, 0.0) + "\n"
            + "*DEFINE_CURVE\n" + _row(1, 0, 1.0, 100.0) + "\n"
            + f"{0.0:>20.10G}{0.0:>20.10G}\n"
            + f"{0.1:>20.10G}{1.0:>20.10G}\n"
            + "*INITIAL_STRESS_SECTION\n" + _row(7, 1, 1, 0, 0, 0, 0) + "\n"))
        r, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/PRELOAD/"), [])
        self.assertTrue(any("ERROR 1251" in x for x in r.warnings))

    def test_frame_nodes_are_fresh_ids_registered_in_the_node_table(self):
        _r, starter = _convert(_bar_deck())
        nodes = _nodes_of(starter)
        # 20 mesh nodes + 3 for the preload /SECT frame + 3 for the REPORTING
        # /SECT frame, which got the same synthesized construction in the
        # SIDE-DEFECT batch (item E).
        self.assertEqual(len(nodes), 20 + 3 + 3)
        sect_id = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        for nid in _sect_frame(starter, sect_id):
            self.assertGreater(nid, 20)

    def test_ismstr10_part_loses_its_total_strain_formulation(self):
        # *MAT_073 (LAW90) parts get /PROP/SOLID Ismstr=10 because that law
        # needs it; sgrtails.F:1387-1412 then shifts a PRELOADED group 10 -> 4
        # with WARNING 1775, taking it away again.
        deck = _bar_deck(pids=(1, 2, 3, 4)).replace(
            "*MAT_ELASTIC\n         1  7.85E-09  210000.0       0.3\n",
            "*MAT_ELASTIC\n         1  7.85E-09  210000.0       0.3\n"
            "*MAT_LOW_DENSITY_VISCOUS_FOAM\n"
            + _row(2, 7.85e-9, 210000.0, 9) + "\n"
            + _row(1.0, 0.0, 0, 0.0, 0) + "\n"
            + "*DEFINE_CURVE\n" + _row(9, 0, 1.0, 1.0) + "\n"
            + f"{0.0:>20.10G}{0.0:>20.10G}\n"
            + f"{1.0:>20.10G}{1.0:>20.10G}\n")
        # part 2 (the cut brick) now takes mid 2 = the LAW90 foam
        deck = deck.replace(_row(2, 2, 1), _row(2, 2, 2))
        r, starter = _convert(deck)
        prop2 = [ln for ln in _block(starter, "/PROP/SOLID/2")
                 if not ln.startswith("#")]
        self.assertEqual(int(prop2[1][10:20]), 10)      # Ismstr=10 emitted
        w = [x for x in r.warnings if "Ismstr=10 (total strain)" in x]
        self.assertTrue(w, "no /PRELOAD Ismstr warning")
        self.assertIn("WARNING 1775", w[0])
        self.assertIn("[2]", w[0])

    def test_no_preload_keyword_draws_no_id(self):
        base = _bar_deck().replace(
            "*INITIAL_STRESS_SECTION_TITLE\nbolt one\n" + ISS_CARD + "\n", "")
        self.assertNotIn("INITIAL_STRESS_SECTION", base)
        _r, a = _convert(base)
        self.assertNotIn("/PRELOAD", a)
        self.assertNotIn("BOLT PRE-TENSION", a)
        _r2, b = _convert(base)
        self.assertEqual(a, b)


class PreloadCurveWindowTests(unittest.TestCase):
    """LS-DYNA Remark 2 at the three curve shapes."""

    def test_ramp_then_flat_ends_at_the_curve_end(self):
        self.assertEqual(
            _preload_curve_window([(0.0, 0.0), (0.1, 5.0), (1.0, 5.0)]),
            (0.0, 1.0, 5.0))

    def test_ramp_then_descend_ends_at_the_maximum(self):
        self.assertEqual(
            _preload_curve_window([(0.0, 0.0), (0.1, 5.0), (0.2, 3.0),
                                   (1.0, 9.0)]),
            (0.0, 0.1, 5.0))

    def test_flat_from_zero_keeps_the_whole_plateau(self):
        self.assertEqual(
            _preload_curve_window([(0.0, 7.0), (0.5, 7.0), (1.0, 7.0)]),
            (0.0, 1.0, 7.0))

    def test_degenerate_windows_are_refused(self):
        self.assertIsNone(_preload_curve_window([(0.3, 5.0)]))
        self.assertIsNone(_preload_curve_window([(0.0, 5.0), (0.1, 1.0)]))
        self.assertIsNone(_preload_curve_window([]))

    def test_truncation_keeps_equal_ordinates(self):
        pts = [(0.0, 0.0), (1.0, 2.0), (2.0, 2.0), (3.0, 1.0), (4.0, 9.0)]
        self.assertEqual(_preload_truncated_points(pts),
                         [(0.0, 0.0), (1.0, 2.0), (2.0, 2.0)])



CROSS_SET_BAR = (
    "*KEYWORD\n*NODE\n"
    + "".join(f"{i:>8}{x:16.8E}{y:16.8E}{z:16.8E}\n"
              for i, (x, y, z) in enumerate(
                  [(a, b, float(k)) for k in range(3)
                   for (a, b) in ((0., 0.), (1., 0.), (1., 1.), (0., 1.))], 1))
    + "*PART\nbar\n" + _row(1, 1, 1) + "\n"
    + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
    + "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
    + "*ELEMENT_SOLID\n"
    + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4, 5, 6, 7, 8)) + "\n"
    + "".join(f"{v:>8}" for v in (2, 1, 5, 6, 7, 8, 9, 10, 11, 12)) + "\n"
    + "*SET_NODE_LIST\n" + _row(11) + "\n" + _row(5, 6, 7, 8) + "\n"
    + "*SET_SOLID\n" + _row(12) + "\n" + _row(2) + "\n"
    #                                NSID HSID BSID SSID TSID DSID
    + "*DATABASE_CROSS_SECTION_SET_ID\n" + f"{1:>10}set cut" + "\n"
    + _row(11, 12, 0, 0, 0, 0) + "\n"
    + "*DEFINE_CURVE\n" + _row(1, 0, 1.0, 150.0) + "\n"
    + f"{0.0:>20.10G}{0.0:>20.10G}\n" + f"{2.0e-4:>20.10G}{1.0:>20.10G}\n"
    + "{EXTRA}"
    + "*CONTROL_TERMINATION\n    4.0E-4\n*END\n"
)


class CrossSectionSetPreloadTests(unittest.TestCase):
    """The _SET cross-section variant, where LS-DYNA REQUIRES a VID."""

    def _run(self, with_vid):
        extra = ""
        if with_vid:
            extra += ("*DEFINE_VECTOR\n"
                      + _row(4, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n")
        extra += ("*INITIAL_STRESS_SECTION\n"
                  + _row(7, 1, 1, 0, 4 if with_vid else 0, 0, 0) + "\n")
        return _convert(CROSS_SET_BAR.replace("{EXTRA}", extra))

    def test_vid_gives_the_exact_axis(self):
        r, starter = self._run(True)
        sect_id = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        got = _frame_normal(starter, sect_id)
        self.assertAlmostEqual(got[0], 0.0, places=9)
        self.assertAlmostEqual(got[1], 0.0, places=9)
        self.assertAlmostEqual(got[2], 1.0, places=9)
        self.assertTrue(any("*DEFINE_VECTOR 4 = (0, 0, 1)" in w
                            for w in r.warnings))
        self.assertFalse(any("no VID" in w for w in r.warnings))
        # HSID gives the brick group; the node set gives the frame origin.
        self.assertEqual(_ids_in(starter, "/GRBRIC/BRIC/"), [2])
        n1 = _sect_frame(starter, sect_id)[0]
        self.assertEqual(_nodes_of(starter)[n1], (0.5, 0.5, 1.0))

    def test_without_vid_the_plane_is_fitted_and_said_out_loud(self):
        r, starter = self._run(False)
        sect_id = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        got = _frame_normal(starter, sect_id)
        self.assertAlmostEqual(abs(got[2]), 1.0, places=9)
        w = [x for x in r.warnings if "no VID" in x]
        self.assertTrue(w)
        self.assertIn("FITTED to the plane the section nodes lie in", w[0])
        self.assertIn("dyna2rad never reads VID", w[0])

# ═════════════════════════════════════════════════════════════════════════════
# *INITIAL_AXIAL_FORCE_BEAM → /PRELOAD/AXIAL
# ═════════════════════════════════════════════════════════════════════════════

#: Part 10 = an ELFORM-1 *SECTION_BEAM on *MAT_ELASTIC -> /BEAM.
#: Part 20 = an ELFORM-9 *SECTION_BEAM on *MAT_SPOTWELD -> /PROP/TYPE13
#:           /SPRING whose axial DOF gets a bilinear fct_ID1 with H=1, so it
#:           PASSES the /PRELOAD/AXIAL property gate.
#: One *SET_BEAM holds both, so the emitted-family split is exercised.
SPOTWELD_MAT = _row(20, 7.85e-9, 210000.0, 0.3, 640.0, 9500.0)

BEAMS = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2            10.0             0.0             0.0\n"
    "       3             0.0            10.0             0.0\n"
    "       4             0.0             0.0            20.0\n"
    "       5            10.0             0.0            20.0\n"
    "*PART\nshank\n" + _row(10, 10, 10) + "\n"
    "*SECTION_BEAM\n" + _row(10, 1) + "\n" + _row(1.0, 1.0, 1.0, 1.0) + "\n"
    "*MAT_ELASTIC\n" + _row(10, 7.85e-9, 210000.0, 0.3) + "\n"
    "*PART\nweld\n" + _row(20, 20, 20) + "\n"
    "*SECTION_BEAM\n" + _row(20, 9) + "\n" + _row(10.0, 10.0, 0.0, 0.0) + "\n"
    "*MAT_SPOTWELD\n" + SPOTWELD_MAT + "\n"
    "*ELEMENT_BEAM\n"
    + "".join(f"{v:>8}" for v in (1001, 10, 1, 2, 3)) + "\n"
    + "".join(f"{v:>8}" for v in (1002, 20, 4, 5, 3)) + "\n"
    "*SET_BEAM\n" + _row(100) + "\n" + _row(1001, 1002) + "\n"
    "*DEFINE_CURVE\n" + _row(9, 0, 1.0, 28.8) + "\n"
    "{CURVE}"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n       1.0\n*END\n"
).replace("{CURVE}", f"{0.0:>20.10G}{0.0:>20.10G}\n"
                     f"{0.001:>20.10G}{1000.0:>20.10G}\n")

AXIAL = "*INITIAL_AXIAL_FORCE_BEAM\n" + _row(100, 9, 2.5, 0) + "\n"


class InitialAxialForceBeamTests(unittest.TestCase):
    def test_set_beam_is_split_by_what_was_actually_emitted(self):
        r, starter = _convert(BEAMS.replace("{EXTRA}", AXIAL))
        # hm_read_preload_axial.F90:262-292 resolves one set_id to exactly ONE
        # family (SPRING before BEAM before TRUSS), so a mixed *SET_BEAM needs
        # two cards on two groups.
        self.assertEqual(len(_headers(starter, "/PRELOAD/AXIAL/")), 2)
        self.assertEqual(_ids_in(starter, "/GRSPRI/SPRI/"), [1002])
        self.assertEqual(_ids_in(starter, "/GRBEAM/BEAM/"), [1001])
        self.assertTrue(any("straddles two Radioss element families" in w
                            for w in r.warnings))

    def test_axial_card_is_column_exact(self):
        _r, starter = _convert(BEAMS.replace("{EXTRA}", AXIAL))
        hdr = _headers(starter, "/PRELOAD/AXIAL/")[0]
        data = [ln for ln in _block(starter, hdr)[1:]
                if not ln.startswith("#")][0]
        grp = int(_headers(starter, "/GRSPRI/SPRI/")[0].split("/")[-1])
        fid = int(_headers(starter, "/FUNCT/")[-1].split("/")[-1])
        # set_id | sens_id 0 | 10 BLANK | curveid | Preload = SCALE | Damp 0
        self.assertEqual(
            data, f"{_i(grp)}{_i(0)}{' ' * 10}{_i(fid)}{_f(2.5)}{_f(0.0)}")
        self.assertEqual(data[20:30], " " * 10)

    def test_scale_reaches_preload_and_the_curve_keeps_its_sfo(self):
        _r, starter = _convert(BEAMS.replace("{EXTRA}", AXIAL))
        fid = _headers(starter, "/FUNCT/")[-1]
        pts = [ln for ln in _block(starter, fid)[1:] if not ln.startswith("#")]
        # SFO=28.8 was applied at parse time: 1000 -> 28800.
        self.assertEqual(pts[-1], f"{_f(0.001)}{_f(28800.0)}")

    def test_curve_is_truncated_at_the_first_descent(self):
        deck = BEAMS.replace(
            f"{0.001:>20.10G}{1000.0:>20.10G}\n",
            f"{0.001:>20.10G}{1000.0:>20.10G}\n"
            f"{0.002:>20.10G}{500.0:>20.10G}\n"
            f"{0.003:>20.10G}{2000.0:>20.10G}\n").replace("{EXTRA}", AXIAL)
        r, starter = _convert(deck)
        fid = _headers(starter, "/FUNCT/")[-1]
        pts = [ln for ln in _block(starter, fid)[1:] if not ln.startswith("#")]
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[-1], f"{_f(0.001)}{_f(28800.0)}")
        self.assertTrue(any("truncated to its leading non-decreasing run" in w
                            for w in r.warnings))

    def test_missing_curve_emits_nothing(self):
        deck = BEAMS.replace("{EXTRA}", "*INITIAL_AXIAL_FORCE_BEAM\n"
                             + _row(100, 77, 1.0, 0) + "\n")
        r, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/PRELOAD/AXIAL/"), [])
        self.assertTrue(any("LCID 77 resolves to no converted" in w
                            for w in r.warnings))

    def test_missing_beam_set_emits_nothing(self):
        deck = BEAMS.replace("{EXTRA}", "*INITIAL_AXIAL_FORCE_BEAM\n"
                             + _row(555, 9, 1.0, 0) + "\n")
        r, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/PRELOAD/AXIAL/"), [])
        self.assertTrue(any("*SET_BEAM 555 not found" in w for w in r.warnings))

    def test_version_gate_is_restated_not_hidden(self):
        r, _starter = _convert(BEAMS.replace("{EXTRA}", AXIAL))
        self.assertTrue(any("100211" in w and "format < 2024" in w
                            for w in r.warnings))

    def test_kbend_is_dropped_by_name(self):
        deck = BEAMS.replace("{EXTRA}", "*INITIAL_AXIAL_FORCE_BEAM\n"
                             + _row(100, 9, 1.0, 2) + "\n")
        r, _starter = _convert(deck)
        w = [x for x in r.warnings if "KBEND=2" in x]
        self.assertTrue(w)
        self.assertIn("no /PRELOAD/AXIAL slot", w[0])

    def test_a_spring_failing_the_property_gate_is_dropped_by_name(self):
        # *MAT_SPOTWELD with SIGY=0 leaves fct_ID1=0 and H=0 on the axial DOF,
        # which is starter ERROR 3057 if the group is named. Drop and say so.
        deck = BEAMS.replace(
            SPOTWELD_MAT,
            _row(20, 7.85e-9, 210000.0, 0.3, 0.0, 0.0)).replace("{EXTRA}",
                                                                AXIAL)
        r, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/GRSPRI/SPRI/"), [])
        self.assertEqual(_ids_in(starter, "/GRBEAM/BEAM/"), [1001])
        self.assertTrue(any("ERROR 3057" in w for w in r.warnings))

    def test_preload_and_preload_axial_never_share_an_id(self):
        _r, starter = _convert(BEAMS.replace("{EXTRA}", AXIAL))
        ids = [h.split("/")[-1] for h in _headers(starter, "/PRELOAD/")]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(ids), len(set(ids)))

    def test_duplicate_preload_and_sect_ids_are_scanned_deck_wide(self):
        from k2rad.writer.assembly import (_warn_duplicate_preload_ids,
                                           _warn_duplicate_sect_ids)
        st = ConversionState()
        _warn_duplicate_preload_ids(st, ["/PRELOAD/7", "/PRELOAD/AXIAL/7"])
        _warn_duplicate_sect_ids(st, ["/SECT/3", "/SECT/3"])
        self.assertTrue(any("BOLT PRELOAD ID 7" in w for w in st.warnings))
        self.assertTrue(any("SECTION ID 3" in w for w in st.warnings))
        st2 = ConversionState()
        _warn_duplicate_preload_ids(st2, ["/PRELOAD/7", "/PRELOAD/AXIAL/8"])
        _warn_duplicate_sect_ids(st2, ["/SECT/3", "/SECT/4"])
        self.assertEqual(st2.warnings, [])

    def test_no_axial_keyword_draws_no_id(self):
        _r, a = _convert(BEAMS.replace("{EXTRA}", ""))
        _r2, b = _convert(BEAMS.replace("{EXTRA}", ""))
        self.assertEqual(a, b)
        self.assertNotIn("/PRELOAD", a)


# ═════════════════════════════════════════════════════════════════════════════
# Corpus carriers
# ═════════════════════════════════════════════════════════════════════════════

_GENNL = ("C:/Users/pmqua/PycharmProjects/k_to_rad_converter/ls-dyna_example/"
          "implicit_general-nonlinearity/4.3_General_Nonlinearity.key")
_BOLTA = ("C:/Users/pmqua/PycharmProjects/FEM_solver/verification/"
          "dynaexamples_r14_ton-mm-s/show-cases/bolts/typea/explicit/"
          "mainboltaexpl.k")


def _convert_file(path):
    tmp = tempfile.TemporaryDirectory()
    dst = os.path.join(tmp.name, os.path.basename(path))
    with open(path, "rb") as src, open(dst, "wb") as out:
        out.write(src.read())
    result = convert(dst, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


class CorpusCarrierTests(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(_GENNL), "corpus deck not available")
    def test_general_nonlinearity_emits_one_preload(self):
        r, starter = _convert_file(_GENNL)
        self.assertNotIn("INITIAL_STRESS_SECTION", r.skipped_keywords)
        hdrs = _headers(starter, "/PRELOAD/")
        self.assertEqual(len(hdrs), 1)
        sect = int(_headers(starter, "/SECT/")[-1].split("/")[-1])
        data = [ln for ln in _block(starter, hdrs[0])[1:]
                if not ln.startswith("#")][0]
        # LCID 1 "Bolt Preload Ramp It Up!": SFO=100, (0,0) -> (0.25,1)
        # => Itype 2, Preload 100 MPa over [0, 0.25], Fct_ID column blank.
        self.assertEqual(
            data,
            f"{_i(sect)}{_i(0)}{_i(2)}{' ' * 10}"
            f"{_f(100.0)}{_f(0.0)}{_f(0.25)}")
        # The real deck carries wedges in the preloaded part, but LS-DYNA
        # spells them by repeating a node, so k2rad emits a DEGENERATE HEX8
        # (cells 7-8 filled) which the starter reads as ISOLNOD=8 and DOES
        # pre-tension — measured: AREA echoes 1.000E+00 and /TH/BRIC SZ reads
        # 200.00 MPa at t=0 on a wedge bolt bar, same as its hex twin. The
        # penta warning must NOT fire here; see the synthetic test below for
        # the blank-cell spelling that does lose the preload.
        self.assertFalse(any("PENTA solids" in w for w in r.warnings))
        # The implicit probe rigid body allocates three nodes too: no /NODE id
        # may appear twice (measured collision before both sites were moved
        # onto state.next_node_id()).
        nodes = [ln[:10].strip() for ln in starter.splitlines()]
        seen, dup = set(), []
        inblk = False
        for ln in starter.splitlines():
            if ln.startswith("/NODE"):
                inblk = True
                continue
            if not inblk:
                continue
            if ln.startswith("/"):
                inblk = False
                continue
            tok = ln[:10].strip()
            if not tok.lstrip("-").isdigit():
                continue
            if tok in seen:
                dup.append(tok)
            seen.add(tok)
        self.assertEqual(dup, [])
        self.assertTrue(nodes)

    @unittest.skipUnless(os.path.exists(_BOLTA), "corpus deck not available")
    def test_mainboltaexpl_emits_one_axial_preload_on_a_spring(self):
        r, starter = _convert_file(_BOLTA)
        self.assertNotIn("INITIAL_AXIAL_FORCE_BEAM", r.skipped_keywords)
        hdrs = _headers(starter, "/PRELOAD/AXIAL/")
        self.assertEqual(len(hdrs), 1)
        # The one beam sits on a *MAT_SPOTWELD part, so it became a /SPRING.
        self.assertEqual(_ids_in(starter, "/GRSPRI/SPRI/"), [1000000])
        self.assertEqual(_headers(starter, "/GRBEAM/BEAM/"), [])
        grp = int(_headers(starter, "/GRSPRI/SPRI/")[0].split("/")[-1])
        data = [ln for ln in _block(starter, hdrs[0])[1:]
                if not ln.startswith("#")][0]
        self.assertEqual(int(data[0:10]), grp)
        self.assertEqual(data[40:60], _f(1.0))       # Preload = SCALE = 1.0
        self.assertEqual(data[60:80], _f(0.0))       # Damp = 0


#: *INITIAL_STRESS_SHELL on element 2 with NTHICK = 5, matching SHELLS' NIP.
#: Card 1 is EID/SID NPLANE NTHICK NHISV NTENSR LARGE NTHINT NTHHSV — eight
#: fields, Vol I R17 p.28-95; then T sig_xx sig_yy sig_zz sig_xy sig_yz sig_zx
#: eps_p per station.
STRESS_5 = ("*INITIAL_STRESS_SHELL\n" + _row(2, 1, 5) + "\n"
            + "".join(_row(round(-1.0 + 0.5 * k, 4), 100.0 + 2.5 * k,
                           0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                      for k in range(5)))

#: The same record moved onto element 3 — SHELLS' collapsed triangle, which
#: this converter emits as a /SH3N.
STRESS_5_ON_THE_TRI = STRESS_5.replace(_row(2, 1, 5), _row(3, 1, 5), 1)


class MixedStressAndStrainTests(unittest.TestCase):
    """A deck that carries BOTH initial-state keywords — LS-DYNA's own dynain
    shape. Reading a /STRA_F block sets the starter's ITHKSHEL=2 globally and a
    /STRS_F block sets ISIGSH, and the two together switch on cross-checks the
    plain strain card cannot satisfy: measured 4x ERROR 26 + 4x ERROR 1904 and
    ERROR TERMINATION before this was handled."""

    def _mixed(self, strain_eid=1, **kw):
        extra = STRESS_5 + ("*INITIAL_STRAIN_SHELL\n"
                            + _row(strain_eid, 1, 2) + "\n"
                            + _row(0.0, 0, 0, 0, 0, 0, -1.0) + "\n"
                            + _row(0.02, 0, 0, 0, 0, 0, 1.0) + "\n")
        return _convert(SHELLS.replace("{EXTRA}", extra), **kw)

    def test_npg_is_four_on_batoz_and_nb_integr_is_the_property_n(self):
        _r, starter = self._mixed()
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        # nb_integr = 5 (the /PROP/SHELL N, which the MSGID-26 layer check
        # demands once ISIGSH is on) and npg = 4 (Ishell 12): npg=1 would leave
        # NPGI=0 against csigini4's NPG=4 and error the element out.
        self.assertEqual(data[0], f"{_i(1)}{_i(5)}{_i(4)}{_f(0.0)}")
        # 5 stations x 4 in-plane copies x 2 data lines, for each of the two
        # records (element 1's own strain + element 2's companion).
        self.assertEqual(len(data), 2 + 2 * (5 * 4 * 2))

    def test_the_stress_element_gets_an_all_zero_companion_record(self):
        r, starter = self._mixed()
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        card1 = [ln for ln in data if ln.endswith(f"{_i(4)}{_f(0.0)}")]
        self.assertEqual(card1, [f"{_i(1)}{_i(5)}{_i(4)}{_f(0.0)}",
                                 f"{_i(2)}{_i(5)}{_i(4)}{_f(0.0)}"])
        # Element 2's block: every strain component zero, T spanning -1..+1 so
        # the two stations the starter keeps are not at the same position
        # (identical T is ERROR 1904).
        start = data.index(f"{_i(2)}{_i(5)}{_i(4)}{_f(0.0)}")
        payload = data[start + 1:start + 1 + 5 * 4 * 2]
        self.assertEqual({ln.strip() for ln in payload[0::2]},
                         {f"{_f(0.0)}{_f(0.0)}{_f(0.0)}".strip()})
        self.assertEqual({ln[:60].strip() for ln in payload[1::2]},
                         {f"{_f(0.0)}{_f(0.0)}{_f(0.0)}".strip()})
        ts = [float(ln[60:80]) for ln in payload[1::2]]
        self.assertEqual(ts[0], -1.0)
        self.assertEqual(ts[-1], 1.0)
        # The message names the card each companion actually went into — a
        # 3-node shell's goes to /INISH3/STRA_F/GLOB (#131).
        w = next(x for x in r.warnings if "an all-zero record was added" in x)
        placed = w.split("was added for each of them, in ")[1].split(".")[0]
        self.assertEqual(placed, "/INISHE/STRA_F/GLOB (element(s) 2)")

    def test_re_sampled_stations_span_minus_one_to_plus_one(self):
        _r, starter = self._mixed()
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        payload = data[1:1 + 5 * 4 * 2]
        ts = [float(ln[60:80]) for ln in payload[1::2]]
        self.assertEqual(sorted(set(ts)), [-1.0, -0.5, 0.0, 0.5, 1.0])
        # eps_XX runs 0 -> 0.02 linearly with T, so the first two stations the
        # starter keeps rebuild the same membrane+curvature as the 2-station
        # form. Measured: /TH/SHEL E1 = 0.01, K1 = 0.02 either way.
        exx = [float(ln[0:20]) for ln in payload[0::2]]
        self.assertAlmostEqual(exx[0], 0.0)
        self.assertAlmostEqual(exx[4], 0.005)
        self.assertAlmostEqual(exx[-1], 0.02)

    def test_a_strain_only_deck_keeps_the_plain_two_station_form(self):
        _r, starter = _convert(SHELLS.replace("{EXTRA}", STRAIN_SMALL))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        # No stress block => ISIGSH stays 0 => none of the cross-checks fire
        # and the compact nb_integr=2 / npg=1 card is kept unchanged.
        self.assertEqual(data[0], f"{_i(1)}{_i(2)}{_i(1)}{_f(0.0)}")

    def test_qeph_takes_npg_one_because_the_reader_fills_npgi_itself(self):
        _r, starter = self._mixed(shell_formulation="qeph")
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        # IHBE==24 makes the reader write SIGSH(NVSHELL)=4 AND the INISHVAR1
        # marker plus the PT+1 shift cstraini4 reads back; npg=4 skips both and
        # is a measured silent no-op.
        self.assertEqual(data[0], f"{_i(1)}{_i(5)}{_i(1)}{_f(0.0)}")

    def test_mixed_formulations_refuse_the_strain_block(self):
        # ELFORM 20 is always QEPH, ELFORM 2 follows the default (QBAT), so the
        # two initial-state elements land on different Ishell values.
        deck = SHELLS.replace(
            "*SECTION_SHELL\n         1         2                   5\n",
            "*SECTION_SHELL\n         1         2                   5\n"
            "       1.0\n"
            "*PART\nstrip2\n         2         2         1\n"
            "*SECTION_SHELL\n         2        20                   5\n")
        deck = deck.replace("       2       1       2       5       6       3",
                            "       2       2       2       5       6       3")
        extra = STRESS_5 + ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 2) + "\n"
                            + _row(0.0, 0, 0, 0, 0, 0, -1.0) + "\n"
                            + _row(0.02, 0, 0, 0, 0, 0, 1.0) + "\n")
        r, starter = _convert(deck.replace("{EXTRA}", extra))
        self.assertIsNone(_block(starter, "/INISHE/STRA_F/GLOB"))
        self.assertTrue(any("do not all share one formulation" in w
                            for w in r.warnings))
        # The initial STRESS is untouched by the refusal.
        self.assertIsNotNone(_block(starter, "/INISHE/STRS_F/GLOB"))


class TriangleStressRecordTests(unittest.TestCase):
    """An *INITIAL_STRESS_SHELL record on a 3-node shell.

    The element leaves this converter as a /SH3N, and until the SIDE-DEFECT
    batch its stress was DROPPED because no ``/INISH3/STRS_F`` was written.
    That card turned out to be the SAME layout as the ``/INISHE`` one already
    emitted: ``diff`` of the extracted ``FORMAT(radioss2021)`` blocks of
    ``inish3_strs_f_glob_sub.cfg`` and ``inishe_strs_f_glob_sub.cfg`` is EMPTY,
    the only difference being the HyperMesh-only ``SUBTYPES`` line. The
    converter's own comment and its user-facing warning both said "the card
    layout differs"; both were false (the #131 "check a warning's CITED FACT"
    class).

    The one difference is ``npg``: the /SH3N reader has no npg cross-check of
    its own, and k2rad always writes ``Ish3n = 0``, so the element is
    initialised through ``c3init3 -> CSIGINI``, whose check is
    ``NPGI > 1`` (csigini.F:143) — the OPPOSITE of the quad path's
    ``NPG /= NPGI`` at scigini4.F:160. Measured: npg 3 and 4 give ERROR 26 per
    element and ERROR TERMINATION; npg 0 and 1 are clean and the stress is
    consumed.

    A record whose id is in NEITHER element table is still dropped, and for the
    original reason: hm_read_inistate_d00.F:2105 (:3266 on the /INISH3 side)
    arms the global ``ISIGSH`` before the id is looked up, and scigini4.F:285-287
    then runs the GLOBAL stress reconstruction for every element whose
    ``SIGSH(17)`` the /STRA_F reader set to ONE — over slots that hold no
    stress. Measured on the real starter/engine: a strain-only quad beside such
    a record reads a constant F1 = -0.249, F2 = -0.248, M1 = 1.503 for all 163
    states on a deck that states no stress at all, at 0 starter ERRORS and
    NORMAL TERMINATION; deleting the one unresolvable record gives exactly 0.0
    on every channel with the strain unchanged.
    """

    def test_a_tri_stress_record_goes_to_the_INISH3_block(self):
        r, starter = _convert(SHELLS.replace("{EXTRA}", STRESS_5_ON_THE_TRI))
        self.assertEqual(_headers(starter, "/INISHE/STRS_F"), [])
        self.assertEqual(_headers(starter, "/INISH3/STRS_F"),
                         ["/INISH3/STRS_F/GLOB"])
        cards = [ln for ln in _block(starter, "/INISH3/STRS_F/GLOB")
                 if not ln.startswith("#")]
        # Card 1: shell_ID 3, nb_integr = the /PROP/SHELL N = 5, npg = 1,
        # Thick = 0. npg 4 would be ERROR 26 on this path.
        self.assertEqual([int(cards[0][0:10]), int(cards[0][10:20]),
                          int(cards[0][20:30])], [3, 5, 1])
        self.assertEqual(float(cards[0][30:50]), 0.0)
        self.assertEqual(float(cards[1][0:20]), 0.0)          # Em
        # 1 card-1 + 1 Em/Eb row + 5 layers x 2 rows x npg 1.
        self.assertEqual(len(cards), 12, cards)
        self.assertFalse([w for w in r.warnings
                          if "*INITIAL_STRESS_SHELL" in w and "DROPPED" in w])

    def test_the_tri_stress_values_land_in_the_right_columns(self):
        """STRESS_5_ON_THE_TRI's layer k carries T = -1 + 0.5k and
        SIGXX = 100 + 2.5k, everything else 0 — so the first layer is
        (T -1.0, sigma_X 100.0) and the last (T 1.0, sigma_X 110.0), bottom
        first. Card rows are consumed in card order and row 1 is the LOWER
        surface (measured against the ANIM: a -100/0/+100 record reads back
        lower/membrane/upper)."""
        _r, starter = _convert(SHELLS.replace("{EXTRA}",
                                              STRESS_5_ON_THE_TRI))
        cards = [ln for ln in _block(starter, "/INISH3/STRS_F/GLOB")
                 if not ln.startswith("#")]
        pts = cards[2:]
        self.assertEqual(float(pts[0][0:20]), 100.0)      # sigma_X, layer 1
        self.assertEqual(float(pts[0][20:40]), 0.0)       # sigma_Y
        self.assertEqual(float(pts[1][80:100]), -1.0)     # pos_nip, layer 1
        self.assertEqual(float(pts[8][0:20]), 110.0)      # sigma_X, layer 5
        self.assertEqual(float(pts[9][80:100]), 1.0)      # pos_nip, layer 5

    def test_a_degenerate_shell_stress_record_is_dropped(self):
        # A shell with fewer than 3 distinct corners has zero area and
        # _make_parts writes NO element for it, so its id is in NEITHER
        # element table and the record must still be left out — the ISIGSH
        # arming hazard is unchanged for it. Gating on "is it a tri" instead
        # of "is it in an emitted table" would leave this one armed (`#120`).
        deck = SHELLS.replace(
            "       3       1       5       7       6       6\n",
            "       3       1       5       5       6       6\n")
        r, starter = _convert(deck.replace("{EXTRA}", STRESS_5_ON_THE_TRI))
        # element 3 is written nowhere: not as /SHELL, not as /SH3N.
        emitted = [int(ln[:10]) for hdr in ("/SHELL/1", "/SH3N/1")
                   for ln in (_block(starter, hdr) or [])
                   if not ln.startswith("#")]
        self.assertEqual(sorted(emitted), [1, 2])
        self.assertEqual(_headers(starter, "/INISHE/STRS_F"), [])
        self.assertEqual(_headers(starter, "/INISH3/STRS_F"), [])
        self.assertTrue(any("fewer than 3 distinct corner nodes" in w
                            and "DROPPED" in w and "ISIGSH" in w
                            for w in r.warnings), list(r.warnings)[:4])

    def test_a_tri_stress_record_DOES_make_a_strain_deck_mixed(self):
        """The reverse of what this pinned before the batch. A tri stress
        record is now a real initial-STRESS block, so ISIGSH IS armed and the
        strain card must take the mixed form — nb_integr = the property N,
        npg per formulation — and the tri must get an all-zero STRAIN
        companion or csigini.F:190 reads Z1 == Z2 == 0 and raises ERROR 1904
        ("IN /INISHE/STRA_F/GLOB OR /INISH3/STRA_F/GLOB", the message names
        both families itself). ITHKSHEL = 2 is global AND cross-family:
        measured, a QUAD's strain block breaks a TRI's stress record."""
        extra = STRESS_5_ON_THE_TRI + ("*INITIAL_STRAIN_SHELL\n"
                                       + _row(1, 1, 2) + "\n"
                                       + _row(0.0, 0, 0, 0, 0, 0, -1.0) + "\n"
                                       + _row(0.02, 0, 0, 0, 0, 0, 1.0) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        self.assertEqual(_headers(starter, "/INISH3/STRS_F"),
                         ["/INISH3/STRS_F/GLOB"])
        # The named element (quad 1) takes the mixed form: nb_integr 5, npg 4.
        quad = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual([int(quad[0][10:20]), int(quad[0][20:30])], [5, 4])
        # ... and the stress-carrying TRI gets its own all-zero companion,
        # nb_integr 5 / npg 1, in the /INISH3 strain block.
        tri = [ln for ln in _block(starter, "/INISH3/STRA_F/GLOB")
               if not ln.startswith("#")]
        self.assertEqual([int(tri[0][0:10]), int(tri[0][10:20]),
                          int(tri[0][20:30])], [3, 5, 1])
        self.assertTrue(all(float(ln[0:20]) == 0.0 for ln in tri[1:]))
        self.assertTrue(any("all-zero" in w for w in r.warnings))

    def test_a_quad_stress_record_beside_a_tri_one_still_arms_the_mixed_form(self):
        # The drop is scoped to the unresolvable id: a resolvable quad record in
        # the same block keeps the deck mixed, so the strain card must still
        # carry npg=4 / nb_integr=N. Otherwise this fix would silently undo the
        # ERROR 26 / ERROR 1904 repair.
        extra = STRESS_5 + STRESS_5_ON_THE_TRI + (
            "*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 2) + "\n"
            + _row(0.0, 0, 0, 0, 0, 0, -1.0) + "\n"
            + _row(0.02, 0, 0, 0, 0, 0, 1.0) + "\n")
        _r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        stress = [ln for ln in _block(starter, "/INISHE/STRS_F/GLOB")
                  if not ln.startswith("#")]
        self.assertEqual(int(stress[0][0:10]), 2)          # only the quad
        strain = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                  if not ln.startswith("#")]
        self.assertEqual([int(strain[0][10:20]), int(strain[0][20:30])], [5, 4])
        # ... and the companion goes to quad 2, never to the dropped tri.
        # A card-1 row is 3 ids + Thick = 10+10+10+20 chars; a payload row is
        # 60 or 80.
        heads = [int(ln[0:10]) for ln in strain if len(ln) == 50]
        self.assertEqual(sorted(heads), [1, 2])


class BlankThicknessColumnTests(unittest.TestCase):
    def test_two_stations_with_a_blank_t_column_report_the_inference(self):
        # Both rows leave T blank, but their values DIFFER — so a real
        # curvature is reconstructed from positions the converter inferred.
        # The single-station message ("pure membrane, zero curvature") would be
        # false on both counts here.
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 2) + "\n"
                 + _row(0.01, 0, 0, 0, 0, 0) + "\n"
                 + _row(0.03, 0, 0, 0, 0, 0) + "\n")
        r, starter = _convert(SHELLS.replace("{EXTRA}", extra))
        data = [ln for ln in _block(starter, "/INISHE/STRA_F/GLOB")
                if not ln.startswith("#")]
        self.assertEqual(float(data[2][60:80]), -1.0)
        self.assertEqual(float(data[4][60:80]), 1.0)
        self.assertTrue(data[1].startswith(_f(0.01)))
        self.assertTrue(data[3].startswith(_f(0.03)))
        self.assertTrue(any("PLACED at T=-1 and T=+1" in w
                            for w in r.warnings))
        self.assertFalse(any("pure membrane state, zero curvature" in w
                             for w in r.warnings))

    def test_one_station_still_reports_a_pure_membrane_state(self):
        extra = ("*INITIAL_STRAIN_SHELL\n" + _row(1, 1, 1) + "\n"
                 + _row(0.01, 0, 0, 0, 0, 0, 0.0) + "\n")
        r, _starter = _convert(SHELLS.replace("{EXTRA}", extra))
        self.assertTrue(any("pure membrane state, zero curvature" in w
                            for w in r.warnings))
        self.assertFalse(any("PLACED at T=-1 and T=+1" in w
                             for w in r.warnings))


class PreloadWarningGateTests(unittest.TestCase):
    """The three /PRELOAD guards that name a part, each on a synthetic deck —
    the corpus carriers are @skipUnless and cover none of them portably."""

    def test_penta_warning_needs_the_blank_cell_spelling(self):
        # A wedge written LS-DYNA's usual way (last node repeated into cells
        # 7-8) leaves k2rad as a degenerate HEX8: hm_read_solid.F:167 wants
        # cells 7 AND 8 blank for ISOLNOD=6, so this one IS pre-tensioned.
        # Measured: AREA 1.000E+00 and /TH/BRIC SZ = 200.00 MPa at t=0.
        deck = _bar_deck()
        out = []
        for ln in deck.splitlines():
            # Collapse the cut brick into a wedge the LS-DYNA way: repeat the
            # 3rd/7th node into cells 4 and 8. Six unique nodes, no blank cell.
            if ln.startswith(f"{2:>8}{1:>8}") and len(ln) == 80:
                out.append(ln[:40] + ln[32:40] + ln[48:72] + ln[64:72])
            else:
                out.append(ln)
        r, _s = _convert("\n".join(out) + "\n")
        self.assertFalse(any("PENTA solids" in w for w in r.warnings))

    def test_penta_warning_fires_on_blank_cells_seven_and_eight(self):
        deck = _bar_deck()
        out = []
        for ln in deck.splitlines():
            # The bar's second brick is the cut one; blank its last two cells
            # so the starter classifies it ISOLNOD=6.
            if ln.startswith(f"{2:>8}{1:>8}") and len(ln) >= 80:
                ln = ln[:64] + f"{0:>8}{0:>8}"
            out.append(ln)
        r, _s = _convert("\n".join(out) + "\n")
        self.assertTrue(any("PENTA solids" in w for w in r.warnings),
                        [w for w in r.warnings][:3])

    def test_a_tet_spelled_with_trailing_zeros_is_not_a_penta(self):
        # mesh.py routes any solid with 4 DISTINCT nodes to /TETRA4, a card
        # that has no cells 7-8 at all — but `n1 n2 n3 n4 0 0 0 0` still has
        # zeros in the raw LS-DYNA row, so classifying on the connectivity
        # instead of on the emitted family called it a PENTA. Measured: such a
        # deck emits /TETRA4 rows and the starter echoes AREA 1.000E+00,
        # exactly like the `n1 n2 n3 n4 n4 n4 n4 n4` spelling and the all-hex
        # twin — so the warning prescribed a remesh on a bolt that
        # pre-tensions correctly (SBOLTINI IS reached from s4init3).
        deck = _bar_deck()
        out = []
        for ln in deck.splitlines():
            # The bar's second brick is the cut one. Keep 3 nodes of its lower
            # face plus 1 of its upper face (a real tet straddling the cut
            # plane) and BLANK cells 5-8.
            if ln.startswith(f"{2:>8}{1:>8}") and len(ln) >= 80:
                ln = ln[:40] + ln[48:56] + f"{0:>8}" * 4
            out.append(ln)
        r, starter = _convert("\n".join(out) + "\n")
        self.assertIn("/TETRA4/1", starter)
        self.assertFalse(any("PENTA solids" in w for w in r.warnings),
                         [w for w in r.warnings if "PENTA" in w])
        self.assertNotEqual(_headers(starter, "/PRELOAD/"), [])

    def test_the_penta_message_names_both_failure_modes(self):
        # ISOLNOD=6 under a solid property is ERROR 3107 at every Isolid but
        # 24 (initia.F:1081-1094), and a silent zero-preload at 24 — the
        # message used to claim the silent case unconditionally, while this
        # converter emits Isolid 17 for *SECTION_SOLID ELFORM 1.
        deck = _bar_deck()
        out = []
        for ln in deck.splitlines():
            if ln.startswith(f"{2:>8}{1:>8}") and len(ln) >= 80:
                ln = ln[:64] + f"{0:>8}{0:>8}"
            out.append(ln)
        r, _s = _convert("\n".join(out) + "\n")
        msg = [w for w in r.warnings if "PENTA solids" in w]
        self.assertEqual(len(msg), 1, list(r.warnings)[:4])
        self.assertIn("ERROR ID 3107", msg[0])
        self.assertIn("ISOLID = 24", msg[0])

    def test_isolid_warning_fires_on_an_unsupported_hourglass_choice(self):
        # *CONTROL_HOURGLASS IHQ=6 -> Isolid 24, measured to DIVERGE after
        # 0.7*(Tstop-Tstart) (1266 -> 1370 MPa against a 200 MPa target).
        r, _s = _convert(_bar_deck(extra="*CONTROL_HOURGLASS\n" + _row(6)))
        self.assertTrue(any("emit /PROP/SOLID Isolid=24" in w
                            for w in r.warnings))

    def test_isolid_five_is_supported_and_does_not_warn(self):
        # IHQ 4/5 -> Isolid 5, re-measured: 200.0 MPa at t=0, 199.1 after
        # Tstop, NORMAL TERMINATION. Warning it would be a false positive.
        r, _s = _convert(_bar_deck(extra="*CONTROL_HOURGLASS\n" + _row(4)))
        self.assertFalse(any("emit /PROP/SOLID Isolid" in w
                             for w in r.warnings))

    def test_the_section_node_group_dodges_a_user_set_node_id(self):
        # _make_extra_groups re-emits *SET_NODE 90004 verbatim as
        # /GRNOD/NODE/90004; next_id() would hand the preload's section-node
        # group the same number -> starter ERROR 79, a refused deck.
        r, starter = _convert(_bar_deck(
            extra="*SET_NODE_LIST\n" + _row(90004) + "\n" + _row(1, 2)))
        ids = [int(h.split("/")[-1]) for h in _headers(starter, "/GRNOD/NODE/")]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertIn(90004, ids)
        self.assertNotIn("INITIAL_STRESS_SECTION", r.skipped_keywords)

    def test_a_preload_window_past_endtim_is_named(self):
        # sboltlaw.F holds the bolted parts at 1e-4 of E until 0.4*dT and
        # restores them only at 0.7*dT; a run that ends first never gets its
        # stiffness back, silently.
        r, _s = _convert(_bar_deck(curve_pts=((0.0, 0.0), (1.0, 1.0))))
        self.assertTrue(any("AFTER the run ends" in w for w in r.warnings))
        # ENDTIM 4e-4 is far below Tstart+0.4*dT = 0.4, so the run really does
        # end inside the HOLD phase: 1e-4 of E throughout.
        w = [x for x in r.warnings if "AFTER the run ends" in x][0]
        self.assertIn("still in its HOLD phase", w)
        self.assertIn("~10000x", w)

    def test_a_run_ending_on_the_stiffness_ramp_quotes_the_fraction(self):
        # sboltlaw.F:120-127 REDUC = 1e-4*(1-w) + w for T1 < TT < T2, so a run
        # that ends between 0.4*dT and 0.7*dT is soft by far LESS than 1e4.
        # ENDTIM = 4e-4 with Tstop = 8e-4 puts it at w = (4-3.2)/(5.6-3.2) =
        # 1/3, i.e. REDUC = 1e-4*2/3 + 1/3 = 0.3334 — measured 0.328 on the
        # real engine with a fully prescribed hexa.
        r, _s = _convert(_bar_deck(curve_pts=((0.0, 0.0), (8.0e-4, 1.0))))
        w = [x for x in r.warnings if "AFTER the run ends" in x]
        self.assertTrue(w, list(r.warnings)[:4])
        self.assertIn("part-way UP the stiffness ramp", w[0])
        self.assertNotIn("~10000x", w[0])
        self.assertIn("0.3334", w[0])

    def test_a_window_inside_the_run_is_not_flagged(self):
        r, _s = _convert(_bar_deck())
        self.assertFalse(any("AFTER the run ends" in w for w in r.warnings))


def _tshell_bar_deck() -> str:
    """A 1x1x4 bar of four *ELEMENT_TSHELL, cut through the second one."""
    lines = ["*KEYWORD", "*NODE"]
    nid = 1
    layers = []
    for k in range(5):
        row = []
        for (u, v) in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
            lines.append(f"{nid:>8}{u:16.8E}{v:16.8E}{float(k):16.8E}")
            row.append(nid)
            nid += 1
        layers.append(row)
    lines += ["*PART", "tsbar", _row(1, 1, 1),
              "*SECTION_TSHELL", _row(1, 2),
              "*MAT_ELASTIC", "         1  7.85E-09  210000.0       0.3",
              "*ELEMENT_TSHELL"]
    for e in range(4):
        lines.append("".join(f"{v:>8}" for v in
                             [e + 1, 1] + layers[e] + layers[e + 1]))
    lines += ["*SET_PART_LIST", _row(5), _row(1),
              "*DATABASE_CROSS_SECTION_PLANE_ID", f"{1:>10}bolt cut",
              _row(5, 0.5, 0.5, 1.5, 0.5, 0.5, 2.5, 3.0),
              "*DEFINE_CURVE", _row(1, 0, 1.0, 200.0, 0.0),
              f"{0.0:>20.10G}{0.0:>20.10G}", f"{2.0e-4:>20.10G}{1.0:>20.10G}",
              "*INITIAL_STRESS_SECTION_TITLE", "bolt one", ISS_CARD,
              "*CONTROL_TERMINATION", "    4.0E-4", "*END"]
    return "\n".join(lines) + "\n"


class PreloadThickShellTests(unittest.TestCase):
    def test_thick_shells_are_kept_out_of_the_preload_group(self):
        # _plane_cut deliberately puts thick shells in solid_eids so a section
        # through them still records force, but SBOLTINI is reached only from
        # sinit3 / s4init3 / s8zinit3 / s10init3 — never the thick-shell
        # initialisers — so a preloaded thick shell would carry no BPRELD at
        # all. LS-DYNA does not support it either (Vol I R17 p.3145 Remark 4).
        r, starter = _convert(_tshell_bar_deck())
        self.assertTrue(any("thick-shell element(s)" in w
                            and "left OUT of the /PRELOAD element group" in w
                            for w in r.warnings), list(r.warnings)[:4])
        # Every element is a thick shell, so nothing is left to pre-tension.
        self.assertEqual(_headers(starter, "/PRELOAD/"), [])
        self.assertTrue(any("cuts no SOLID element" in w for w in r.warnings))


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
