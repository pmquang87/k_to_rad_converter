"""Tests for the PRELOAD / INITIAL-STATE batch:

  *INITIAL_STRAIN_SHELL[_SET]  → /INISHE/STRA_F/GLOB + /INISH3/STRA_F/GLOB
  *INITIAL_STRESS_SECTION      → /PRELOAD (+ a dedicated /SECT + /GRBRIC)
  *INITIAL_AXIAL_FORCE_BEAM    → /PRELOAD/AXIAL (+ /GRBEAM, /GRSPRI, /FUNCT)

Kept in its own module (like tests/test_inistate_sect.py) so the additions do
not collide with other in-flight work on the big test files.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import HANDLERS, INITIAL_STATE_PRELOAD_KEYWORDS, dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState
from k2rad.writer import _f, _i


# ── Harness ──────────────────────────────────────────────────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _row16(*vals) -> str:
    """LARGE-format (16-char) card row."""
    return "".join(f"{v:>16}" for v in vals)


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
        # LARGE. Reading the stress keyword's ILOC cell (9) would miss it.
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


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
