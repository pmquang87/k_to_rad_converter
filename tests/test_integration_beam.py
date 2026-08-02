"""Tests for *INTEGRATION_BEAM user cross-section integration rules, and for
the multi card-set walks of the three remaining *SECTION_* keywords:

  *SECTION_BEAM card-1 field 4 (QR/IRID) < 0  -> the rule reference
  *INTEGRATION_BEAM ICST=0 (S/T/WF/PID)       -> /PROP/TYPE18 Isect=0 + points
  *INTEGRATION_BEAM ICST>0 (D1..D6)           -> /PROP/TYPE18 Isect=ICST+9
  a rule on a TYPE18-hostile material         -> /PROP/BEAM with the section
                                                 constants DERIVED from it
  *SECTION_SOLID / _BEAM / _DISCRETE multi set -> every section, not just #1

Kept in a separate module from tests/test_converter.py and
tests/test_composites.py so it does not collide with other in-flight work on
those files (same policy as tests/test_integration_shell.py).

Assertions are COLUMN-EXACT against the emitted cards, and every integration
point's position and area is recomputed by hand from the deck's S/T/WF and the
section's TS1/TT1 in the test rather than copied from the implementation. Where
the conversion turns on what an LS-DYNA field MEANS rather than on arithmetic -
S and T are NORMALIZED quadrature coordinates and not lengths, WF is an AREA
fraction, RA is the relative area of the bounding box, the two card blocks of
the rule are ADDITIVE and not exclusive - the assertion pins the value the
manual's definition implies, with the citation in the test docstring.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402


# ── Harness (same shape as tests/test_integration_shell.py) ──────────────────

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


def _row(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def _blocks(starter: str, header: str):
    out, cur = [], None
    for ln in starter.splitlines():
        if ln.startswith(header):
            cur = [ln]
            out.append(cur)
        elif cur is not None:
            if ln.startswith("#---1----"):
                cur = None
            else:
                cur.append(ln)
    return out


def _block(starter: str, header: str):
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _cards(block):
    """The data cards of a /PROP block: everything after the header + title,
    comments removed. A genuinely BLANK card is kept - /PROP/TYPE18's
    predefined-section branch ends with a mandatory blank line."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warned(result, *needles):
    return any(all(n in w for n in needles) for w in result.warnings)


def _p18(starter: str):
    """The single /PROP/TYPE18 as a dict of its named fields plus the
    (Yi, Zi, AREA) point list, all read by COLUMN.

    Layout, prop_p18_int_beam.cfg FORMAT(radioss120):199-235 --
      card 1  Isect(1-10)   Ismstr(11-20)
      card 2  Dm(1-20)      Df(21-40)
      card 3  NIP(1-10)     Iref(11-20)  Y0(21-40)  Z0(41-60)
      card 4  Yi(1-20)      Zi(21-40)    AREA(41-60)   x NIP, only if NIP>0
      card 5  NITRS(1-10)   <blank>      L1(21-40)  L2(41-60), only if Isect!=0
      card 6  BLANK, only if Isect != 0
      card 7  W_DOF
    """
    c = _cards(_block(starter, "/PROP/TYPE18/"))
    out = {
        "isect": _col_i(c[0], 1, 10),
        "ismstr": _col_i(c[0], 11, 20),
        "dm": _col_f(c[1], 1, 20),
        "df": _col_f(c[1], 21, 40),
        "nip": _col_i(c[2], 1, 10),
        "iref": _col_i(c[2], 11, 20),
        "y0": _col_f(c[2], 21, 40),
        "z0": _col_f(c[2], 41, 60),
        "points": [],
        "nitrs": None, "l1": None, "l2": None,
        "wdof": c[-1],
    }
    if out["isect"] == 0:
        out["points"] = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40),
                          _col_f(ln, 41, 60)) for ln in c[3:3 + out["nip"]]]
    else:
        out["nitrs"] = _col_i(c[3], 1, 10)
        out["l1"] = _col_f(c[3], 21, 40)
        out["l2"] = _col_f(c[3], 41, 60)
        out["blank"] = c[4]
    return out


def _p3(starter: str):
    """(Area, Iyy, Izz, Ixx) of the single /PROP/BEAM, by column
    (prop_p3_beam.cfg FORMAT(radioss51): four F20 fields on card 3)."""
    c = _cards(_block(starter, "/PROP/BEAM/"))
    return tuple(_col_f(c[2], 20 * k + 1, 20 * (k + 1)) for k in range(4))


# ── Decks ────────────────────────────────────────────────────────────────────

NODES = "\n".join([
    "*NODE",
    f"{1:>8}{0.0:>16}{0.0:>16}{0.0:>16}",
    f"{2:>8}{10.0:>16}{0.0:>16}{0.0:>16}",
    f"{3:>8}{0.0:>16}{1.0:>16}{0.0:>16}",
])

BEAM = "\n".join([
    "*ELEMENT_BEAM",
    "".join(f"{v:>8}" for v in (1, 7, 1, 2, 3)),
    "*PART", "beam part", _row(7, 5, 9),
])

# LAW36 (PLAS_TAB) is BEAM_INTEGRATED, i.e. it accepts /PROP/TYPE18 and NOT
# /PROP/BEAM (init_mat_keyword: hm_read_mat36.F:360).
MAT_PLAS = "\n".join([
    "*MAT_PIECEWISE_LINEAR_PLASTICITY",
    _row(9, "7.85E-9", 210000.0, 0.3, 300.0),
])

# LAW1 (/MAT/ELAST) is BEAM_CLASSIC: TYPE3 only (hm_read_mat01.F:148).
MAT_ELAST = "\n".join(["*MAT_ELASTIC", _row(9, "7.85E-9", 210000.0, 0.3)])

# TS1 = 4 (s-direction thickness at node 1), TT1 = 6 (t-direction).
CARD2_4x6 = _row(4.0, 4.0, 6.0, 6.0)

# The four corner cells of the 4 x 6 rectangle, each a quarter of the area.
RULE_4CELL = "\n".join([
    "*INTEGRATION_BEAM",
    _row(77, 4, 1.0, 0, 0),
    _row(-1.0, -1.0, 0.25, 0),
    _row(1.0, -1.0, 0.25, 0),
    _row(1.0, 1.0, 0.25, 0),
    _row(-1.0, 1.0, 0.25, 0),
])


def _deck(section, rule, mat=MAT_PLAS, extra=""):
    return "\n".join(["*KEYWORD", NODES, BEAM, mat, section, rule, extra,
                      "*END", ""])


SEC_RULE = "\n".join(["*SECTION_BEAM", _row(5, 1, 1.0, -77, 2), CARD2_4x6])


# ── Parsing ──────────────────────────────────────────────────────────────────

class IntegrationBeamParseTests(unittest.TestCase):
    def test_card_one_fields_land_in_their_own_columns(self):
        """Card 1 is IRID NIP RA ICST K (Vol I R17 p.29-2): RA is a FLOAT in
        cols 21-30 sitting between two integers, so a reader that took it as
        an int would silently truncate the relative area to 0."""
        st = _dispatch("*KEYWORD\n*INTEGRATION_BEAM\n"
                       + _row(77, 3, 0.85, 0, 2) + "\n"
                       + _row(-0.5, 0.0, 0.5, 0) + "\n"
                       + _row(0.0, 0.0, 0.25, 0) + "\n"
                       + _row(0.5, 0.0, 0.25, 0) + "\n*END\n")
        r = st.integration_beams[77]
        self.assertEqual((r.nip, r.icst, r.k), (3, 0, 2))
        self.assertEqual(r.ra, 0.85)
        self.assertEqual([(p.s, p.t, p.wf, p.pid) for p in r.points],
                         [(-0.5, 0.0, 0.5, 0), (0.0, 0.0, 0.25, 0),
                          (0.5, 0.0, 0.25, 0)])

    def test_d5_and_d6_are_fields_seven_and_eight_not_five_and_six(self):
        """The ICST>0 card reads D1 D2 D3 D4 SREF TREF D5 D6 - SREF/TREF sit
        BETWEEN D4 and D5 (integration_beam.cfg:156-157), so reading D5/D6 off
        fields 5/6 would pick up the two reference-axis offsets instead."""
        st = _dispatch("*KEYWORD\n*INTEGRATION_BEAM\n"
                       + _row(3, 0, 0.0, 10, 0) + "\n"
                       + _row(1.0, 2.0, 3.0, 4.0, 0.25, -0.25, 5.0, 6.0)
                       + "\n*END\n")
        r = st.integration_beams[3]
        self.assertEqual(r.dims, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        self.assertEqual((r.sref, r.tref), (0.25, -0.25))

    def test_the_two_card_blocks_are_additive_not_exclusive(self):
        """The manual prints the dimension card and the quadrature cards under
        two INDEPENDENT headings, and the real reader consumes both: a rule
        with ICST>0 AND NIP>0 spans 1 + 1 + NIP lines. The HyperMesh CFG gates
        the point list on `ICST == 0 && NIP > 0` and is wrong - a converter
        that believed it would read the next rule's card 1 as a point card and
        lose that rule entirely."""
        st = _dispatch("*KEYWORD\n*INTEGRATION_BEAM\n"
                       + _row(11, 2, 0.0, 5, 0) + "\n"
                       + _row(10.0, 20.0, 30.0, 40.0) + "\n"
                       + _row(-1.0, -1.0, 0.5, 0) + "\n"
                       + _row(1.0, 1.0, 0.5, 0) + "\n"
                       + _row(12, 0, 0.0, 8, 1) + "\n"
                       + _row(2.5) + "\n*END\n")
        self.assertEqual(sorted(st.integration_beams), [11, 12])
        self.assertEqual(st.integration_beams[12].icst, 8)
        self.assertEqual(st.integration_beams[12].dims[0], 2.5)
        self.assertEqual(st.integration_beams[12].k, 1)

    def test_several_rules_stack_under_one_header(self):
        st = _dispatch("*KEYWORD\n*INTEGRATION_BEAM\n"
                       + _row(1, 1, 1.0, 0, 0) + "\n"
                       + _row(0.0, 0.0, 1.0, 0) + "\n"
                       + _row(2, 1, 1.0, 0, 0) + "\n"
                       + _row(0.5, 0.5, 1.0, 4) + "\n*END\n")
        self.assertEqual(sorted(st.integration_beams), [1, 2])
        self.assertEqual(st.integration_beams[2].points[0].pid, 4)

    def test_a_short_point_block_is_reported_and_the_rest_used(self):
        deck = _deck(SEC_RULE, "\n".join([
            "*INTEGRATION_BEAM", _row(77, 3, 1.0, 0, 0),
            _row(-1.0, 0.0, 0.5, 0), _row(1.0, 0.0, 0.5, 0)]))
        result, starter = _convert(deck)
        self.assertTrue(_warned(result, "*INTEGRATION_BEAM 77",
                                "NIP=3 needs 3 S/T/WF/PID card(s) but only 2"))
        self.assertEqual(_p18(starter)["nip"], 2)

    def test_a_duplicate_rule_id_is_reported(self):
        st = _dispatch("*KEYWORD\n*INTEGRATION_BEAM\n"
                       + _row(77, 1, 1.0, 0, 0) + "\n"
                       + _row(0.0, 0.0, 1.0, 0) + "\n"
                       + _row(77, 1, 1.0, 0, 0) + "\n"
                       + _row(0.5, 0.5, 1.0, 0) + "\n*END\n")
        self.assertTrue(any("defined more than once" in w
                            and "*INTEGRATION_BEAM 77" in w
                            for w in st.warnings), st.warnings)
        self.assertEqual(st.integration_beams[77].points[0].s, 0.5)

    def test_a_non_positive_irid_stops_the_block(self):
        st = _dispatch("*KEYWORD\n*INTEGRATION_BEAM\n"
                       + _row(0, 1, 1.0, 0, 0) + "\n"
                       + _row(0.0, 0.0, 1.0, 0) + "\n*END\n")
        self.assertEqual(st.integration_beams, {})
        self.assertTrue(any("no positive IRID" in w for w in st.warnings))


class SectionBeamLinkageTests(unittest.TestCase):
    def test_the_link_is_card_one_field_four_and_it_is_a_float(self):
        """"EQ.-n: |n| is the number of the user defined rule" on the QR/IRID
        cell, *SECTION_BEAM card 1 cols 31-40 (Vol I R17 p.41-4). Both "-77"
        and "-77.0" occur in real decks, so the cell is read as a FLOAT and
        only its sign selects the rule branch."""
        for cell in (-77, -77.0, "-7.700E+01"):
            with self.subTest(cell=cell):
                st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                               + _row(5, 1, 1.0, cell, 2) + "\n"
                               + CARD2_4x6 + "\n*END\n")
                self.assertEqual(st.sec_beams[5].irid, 77)

    def test_a_positive_qr_carries_no_rule_reference(self):
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(5, 1, 1.0, 2.0, 0) + "\n"
                       + CARD2_4x6 + "\n*END\n")
        self.assertEqual(st.sec_beams[5].irid, 0)
        self.assertEqual(st.sec_beams[5].qr, 2.0)

    def test_a_referenced_rule_kills_the_sections_own_quadrature_field(self):
        """On the object branch the quadrature scalar is DEAD: dyna2rad's own
        SCALAR_OR_OBJECT cell force-zeroes it (meci_data_reader.cpp:7003), so a
        reader that kept the negative value - or read the cell as a plain
        number - would see QR=0 and pick the 2-point rectangular rule on top of
        the user rule it was already given."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(5, 1, 1.0, -77, 2) + "\n"
                       + CARD2_4x6 + "\n*END\n")
        self.assertEqual((st.sec_beams[5].irid, st.sec_beams[5].qr), (77, 0.0))

    def test_ts_and_tt_are_the_two_DIRECTIONS_not_the_two_NODES(self):
        """Card 2a is TS1 TS2 TT1 TT2 = s-thickness at node 1 / node 2, then
        t-thickness at node 1 / node 2 (p.41-11). dyna2rad maps L1<-TS1 and
        L2<-TS2 (convertprops.cxx:1274-1275), i.e. two s-direction values, so a
        tapered beam has its taper read as its depth."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(5, 1, 1.0, 2.0, 0) + "\n"
                       + _row(4.0, 4.5, 6.0, 6.5) + "\n*END\n")
        sec = st.sec_beams[5]
        self.assertEqual((sec.ts1, sec.ts2, sec.tt1, sec.tt2),
                         (4.0, 4.5, 6.0, 6.5))

    def test_a_dangling_rule_reference_is_reported(self):
        result, starter = _convert(_deck(SEC_RULE, ""))
        self.assertTrue(_warned(result, "*SECTION_BEAM 5",
                                "rule 77 that the deck does NOT define"))
        self.assertNotIn("/PROP/TYPE18/", starter)

    def test_a_rule_nobody_references_is_recognized_not_emitted(self):
        deck = _deck("\n".join(["*SECTION_BEAM", _row(5, 2, 1.0, 2.0, 0),
                                _row(24.0, 108.0, 228.0, 336.0)]),
                     RULE_4CELL)
        result, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE18/", starter)
        self.assertTrue(any("*INTEGRATION_BEAM" in k
                            and "no *SECTION_BEAM references them" in v
                            for k, v in result.recognized_not_emitted))


# ── ICST = 0: the arbitrary point cloud ──────────────────────────────────────

class ArbitraryRuleTests(unittest.TestCase):
    """S and T are NORMALIZED quadrature coordinates in [-1, 1] and WF is the
    area FRACTION A_i/A, while Radioss wants absolute local coordinates and an
    absolute area (prop_p18_int_beam.cfg:29-31). The denormalization is
    Y = S*TS1/2, Z = T*TT1/2, A_i = WF_i/sum(WF) * RA*TS1*TT1."""

    def test_the_four_corner_cells_land_on_the_rectangle_corners(self):
        result, starter = _convert(_deck(SEC_RULE, RULE_4CELL))
        p = _p18(starter)
        # TS1 = 4 -> Y = +/-2; TT1 = 6 -> Z = +/-3; A = 1.0*4*6 = 24, quartered
        self.assertEqual(p["points"], [(-2.0, -3.0, 6.0), (2.0, -3.0, 6.0),
                                       (2.0, 3.0, 6.0), (-2.0, 3.0, 6.0)])
        self.assertEqual(p["isect"], 0)
        self.assertEqual(p["nip"], 4)
        self.assertEqual(sum(a for _, _, a in p["points"]), 24.0)
        self.assertEqual(result.warnings, [])

    def test_the_reference_axis_stays_on_the_node_line(self):
        """Iref=1 with Y0=Z0=0, NOT Iref=0. The rule's S/T are measured from
        the beam's node line, and Iref=0 makes the starter recompute the centre
        as the area-weighted barycentre of the cells and shift every point by
        it (hm_read_prop18.F:267-279) - which silently relocates the neutral
        axis of a deliberately eccentric section."""
        result, starter = _convert(_deck(SEC_RULE, "\n".join([
            "*INTEGRATION_BEAM", _row(77, 2, 1.0, 0, 0),
            _row(0.5, 0.0, 0.5, 0), _row(1.0, 0.0, 0.5, 0)])))
        p = _p18(starter)
        self.assertEqual((p["iref"], p["y0"], p["z0"]), (1, 0.0, 0.0))
        # Both cells are on the +s side; nothing recentres them.
        self.assertEqual([y for y, _, _ in p["points"]], [1.0, 2.0])

    def test_ra_scales_the_gross_area_of_every_cell(self):
        """RA is the RELATIVE area A/(TS1*TT1) (p.29-2), so a section that
        fills 60% of its bounding box carries 0.6*4*6 = 14.4 in total."""
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 2, 0.6, 0, 0),
                          _row(-1.0, 0.0, 0.5, 0), _row(1.0, 0.0, 0.5, 0)])
        result, starter = _convert(_deck(SEC_RULE, rule))
        areas = [a for _, _, a in _p18(starter)["points"]]
        self.assertEqual(areas, [7.2, 7.2])
        self.assertAlmostEqual(sum(areas), 0.6 * 4.0 * 6.0, places=10)

    def test_a_zero_ra_is_reported_and_treated_as_the_full_box(self):
        """RA's card default is 0.0, which would make every cell zero-area -
        starter ERROR 314 'AREA OF THE SUBSECTION MUST BE POSITIVE'
        (hm_read_prop18.F:169). k2rad substitutes 1.0 and says so."""
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 1, 0.0, 0, 0),
                          _row(0.0, 0.0, 1.0, 0)])
        result, starter = _convert(_deck(SEC_RULE, rule))
        self.assertTrue(_warned(result, "RA=0 is not positive", "ERROR 314"))
        self.assertEqual(_p18(starter)["points"], [(0.0, 0.0, 24.0)])

    def test_unnormalized_weights_are_divided_by_their_sum(self):
        """"WF is a fraction and the WFs are meant to sum to 1, but nothing
        enforces it - dyna2rad's shell rule normalizes by sum(WF)
        (convertprops.cxx:1991-1996) and this does the same, so the total area
        stays RA*TS1*TT1 whatever the deck wrote."""
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 2, 1.0, 0, 0),
                          _row(-1.0, 0.0, 3.0, 0), _row(1.0, 0.0, 1.0, 0)])
        result, starter = _convert(_deck(SEC_RULE, rule))
        areas = [a for _, _, a in _p18(starter)["points"]]
        self.assertEqual(areas, [18.0, 6.0])        # 3/4 and 1/4 of 24
        self.assertEqual(sum(areas), 24.0)

    def test_zero_weights_are_dropped_with_the_starter_error_named(self):
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 2, 1.0, 0, 0),
                          _row(-1.0, 0.0, 1.0, 0), _row(1.0, 0.0, 0.0, 0)])
        result, starter = _convert(_deck(SEC_RULE, rule))
        self.assertTrue(_warned(result, "non-positive area", "ERROR 314"))
        self.assertNotIn("/PROP/TYPE18/", starter)

    def test_a_section_without_thicknesses_cannot_denormalize_the_rule(self):
        sec = "\n".join(["*SECTION_BEAM", _row(5, 1, 1.0, -77, 2), _row(4.0)])
        result, starter = _convert(_deck(sec, RULE_4CELL))
        self.assertTrue(_warned(result, "TS1=4 and TT1=0"))
        self.assertNotIn("/PROP/TYPE18/", starter)

    def test_a_per_cell_pid_is_reported_as_dropped(self):
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 2, 1.0, 0, 0),
                          _row(-1.0, 0.0, 0.5, 0), _row(1.0, 0.0, 0.5, 8)])
        result, _ = _convert(_deck(SEC_RULE, rule))
        self.assertTrue(_warned(result, "per-cell PID of 1 integration point",
                                "one material for the whole cross-section"))

    def test_more_than_one_hundred_cells_are_clamped(self):
        n = 130
        cards = [_row(77, n, 1.0, 0, 0)]
        cards += [_row(round(-1.0 + 2.0 * k / (n - 1), 6), 0.0,
                       round(1.0 / n, 8), 0) for k in range(n)]
        result, starter = _convert(
            _deck(SEC_RULE, "\n".join(["*INTEGRATION_BEAM"] + cards)))
        self.assertTrue(_warned(result, "at most 100", "ERROR 977"))
        self.assertEqual(_p18(starter)["nip"], 100)



# ── ICST > 0: the standard sections ──────────────────────────────────────────

class StandardSectionTests(unittest.TestCase):
    """ICST 1..22 line up 1:1 with Radioss Isect 10..31, offset by exactly 9
    (starter defbeam_sect_new.F90). Only shapes needing at most two dimensions
    can be written at /BEGIN 2022, whose TYPE18 card layout declares L1 and L2
    and nothing else (radioss120/PROP/prop_p18_int_beam.cfg:33-34)."""

    def _run(self, icst, dims, k=0, mat=MAT_PLAS):
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 0, 0.0, icst, k),
                          _row(*dims)])
        return _convert(_deck(SEC_RULE, rule, mat=mat))

    def test_a_solid_circle_becomes_isect_seventeen_with_l1_as_the_radius(self):
        """ICST 8 (Circular, 1 dimension) -> Isect 17, whose own area formula
        is `area = pi*l(1)**2` (defbeam_sect_new.F90:355) - so L1 is the
        RADIUS, matching dyna2rad's SECTION_08 `A = pi*D1**2`
        (convertprops.cxx:1372)."""
        result, starter = self._run(8, (3.0,))
        p = _p18(starter)
        self.assertEqual((p["isect"], p["l1"], p["l2"]), (17, 3.0, 0.0))
        self.assertEqual((p["nip"], p["iref"], p["y0"], p["z0"]), (0, 0, 0, 0))
        self.assertEqual(p["points"], [])
        self.assertEqual(p["blank"].strip(), "")
        self.assertEqual(result.warnings, [])

    def test_a_tube_carries_both_radii(self):
        """ICST 9 (Tubular, 2 dims) -> Isect 18, `area = pi*(l(1)**2-l(2)**2)`
        (defbeam_sect_new.F90:380): L1 outer radius, L2 inner."""
        _, starter = self._run(9, (5.0, 4.0))
        p = _p18(starter)
        self.assertEqual((p["isect"], p["l1"], p["l2"]), (18, 5.0, 4.0))

    def test_a_solid_box_becomes_isect_twenty(self):
        """ICST 11 (Solid Box, 2 dims) -> Isect 20, `area = l(1)*l(2)`."""
        _, starter = self._run(11, (8.0, 12.0))
        p = _p18(starter)
        self.assertEqual((p["isect"], p["l1"], p["l2"]), (20, 8.0, 12.0))

    def test_k_becomes_nitrs_and_is_clamped_to_the_shapes_own_ceiling(self):
        """Isect 17's intr_max is 2 (defbeam_sect_new.F90:353); NITRS above it
        is starter ERROR 3060 (hm_read_prop18.F:212)."""
        _, starter = self._run(8, (3.0,), k=1)
        self.assertEqual(_p18(starter)["nitrs"], 1)
        result, starter = self._run(8, (3.0,), k=9)
        self.assertEqual(_p18(starter)["nitrs"], 2)
        self.assertTrue(_warned(result, "K=9", "CLAMPED to 2", "ERROR 3060"))

    def test_a_shape_needing_more_than_two_dimensions_is_reported(self):
        """ICST 1 (I-shape) needs L1..L4. Verified against the real starter:
        the same deck at /BEGIN 2022 earns WARNING 100213 + ERROR 3059 and at
        /BEGIN 2026 reads L3/L4 and builds the section."""
        result, starter = self._run(1, (50.0, 5.0, 100.0, 5.0))
        self.assertTrue(_warned(result, "ICST=1 maps to Radioss Isect=10",
                                "needs 4 dimensions", "ERROR 3059"))
        self.assertNotIn("/PROP/TYPE18/", starter)
        self.assertIn("/PROP/BEAM/5", starter)

    def test_an_unsupported_icst_is_reported(self):
        result, starter = self._run(23, (1.0, 2.0))
        self.assertTrue(_warned(result, "ICST=23 is not one of the 22 standard"))
        self.assertNotIn("/PROP/TYPE18/", starter)

    def test_a_missing_dimension_is_reported_with_the_starter_error(self):
        result, starter = self._run(9, (5.0, 0.0))
        self.assertTrue(_warned(result, "needs 2 positive dimension(s)",
                                "D2 is zero", "ERROR 3059"))
        self.assertNotIn("/PROP/TYPE18/", starter)

    def test_sref_and_tref_are_reported_as_dropped(self):
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 0, 0.0, 8, 0),
                          _row(3.0, 0.0, 0.0, 0.0, 0.5, -0.25)])
        result, starter = _convert(_deck(SEC_RULE, rule))
        self.assertTrue(_warned(result, "SREF=0.5", "TREF=-0.25",
                                "are DROPPED"))
        self.assertEqual(_p18(starter)["isect"], 17)

    def test_point_cards_under_a_standard_section_are_consumed_and_ignored(self):
        """The blocks are additive: the reader eats NIP point cards even when
        ICST>0, and LS-DYNA discards their data. Skipping the lines instead
        would de-sync the whole block."""
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 2, 0.0, 11, 0),
                          _row(8.0, 12.0), _row(-1.0, -1.0, 0.5, 0),
                          _row(1.0, 1.0, 0.5, 0)])
        result, starter = _convert(_deck(SEC_RULE, rule))
        p = _p18(starter)
        self.assertEqual((p["isect"], p["l1"], p["l2"]), (20, 8.0, 12.0))
        self.assertEqual(p["points"], [])
        self.assertTrue(_warned(result, "their data is IGNORED"))


# ── The material gate and the derived-constant fallback ──────────────────────

class MaterialGateTests(unittest.TestCase):
    def test_a_law1_beam_keeps_type3_with_constants_derived_from_the_rule(self):
        """/MAT/ELAST is BEAM_CLASSIC, which check_mat_elem_prop_compatibility.F
        :239-241 rejects on /PROP/TYPE18 (ERROR 3047 + ERROR 745). The section
        stays on /PROP/BEAM and the rule is condensed into the four constants
        with the starter's OWN summary formula (hm_read_prop18.F:289-301):
        Iyy = sum(A_i^2/12 + A_i*y_i^2), Izz likewise in z, Ixx = Iyy + Izz."""
        result, starter = _convert(_deck(SEC_RULE, RULE_4CELL, mat=MAT_ELAST))
        self.assertNotIn("/PROP/TYPE18/", starter)
        # four cells of area 6 at (+/-2, +/-3):
        #   A   = 4*6                                   = 24
        #   Iyy = 4*(6^2/12 + 6*2^2) = 4*(3 + 24)       = 108
        #   Izz = 4*(6^2/12 + 6*3^2) = 4*(3 + 54)       = 228
        #   Ixx = 108 + 228                             = 336
        self.assertEqual(_p3(starter), (24.0, 108.0, 228.0, 336.0))
        self.assertTrue(_warned(result, "ERROR 3047",
                                "stays on /PROP/BEAM (TYPE3) with the "
                                "Area/Iyy/Izz/Ixx DERIVED"))

    def test_a_law1_beam_on_a_standard_section_derives_the_circle(self):
        """dyna2rad's own SECTION_08 closed form (convertprops.cxx:1372-1375):
        A = pi*r^2, I = pi*r^4/4, Ixx = pi*r^4/2."""
        import math
        rule = "\n".join(["*INTEGRATION_BEAM", _row(77, 0, 0.0, 8, 0),
                          _row(3.0)])
        _, starter = _convert(_deck(SEC_RULE, rule, mat=MAT_ELAST))
        a, iyy, izz, ixx = _p3(starter)
        self.assertAlmostEqual(a, math.pi * 9.0, places=6)
        self.assertAlmostEqual(iyy, math.pi * 81.0 / 4.0, places=6)
        self.assertAlmostEqual(izz, iyy, places=10)
        self.assertAlmostEqual(ixx, 2.0 * iyy, places=6)

    def test_a_law36_beam_gets_the_integrated_property(self):
        _, starter = _convert(_deck(SEC_RULE, RULE_4CELL, mat=MAT_PLAS))
        self.assertIn("/PROP/TYPE18/5", starter)
        self.assertNotIn("/PROP/BEAM/5", starter)

    def test_a_law44_beam_gets_the_integrated_property(self):
        """*MAT_PLASTIC_KINEMATIC -> /MAT/LAW44, which is BEAM_ALL
        (hm_read_mat44.F:319) and so takes either beam property."""
        mat = "\n".join(["*MAT_PLASTIC_KINEMATIC",
                         _row(9, "7.85E-9", 210000.0, 0.3, 300.0, 1000.0)])
        _, starter = _convert(_deck(SEC_RULE, RULE_4CELL, mat=mat))
        self.assertIn("/PROP/TYPE18/5", starter)


# ── ELFORM gating and other skip paths ───────────────────────────────────────

class RuleSkipPathTests(unittest.TestCase):
    def test_only_the_integrated_elforms_take_a_rule(self):
        """A cross-section rule only means something to a formulation that
        integrates one. dyna2rad reaches a rule-aware path for ELFORM 1 and 4
        only and drops 5 and 11 with no message at all (they have no switch
        case and there is no `default:`, convertprops.cxx:1248-1516)."""
        for elform in (0, 1, 4, 5, 11):
            with self.subTest(elform=elform):
                sec = "\n".join(["*SECTION_BEAM",
                                 _row(5, elform, 1.0, -77, 2), CARD2_4x6])
                _, starter = _convert(_deck(sec, RULE_4CELL))
                self.assertIn("/PROP/TYPE18/5", starter)
        for elform in (2, 3, 9):
            with self.subTest(elform=elform):
                sec = "\n".join(["*SECTION_BEAM",
                                 _row(5, elform, 1.0, -77, 2), CARD2_4x6])
                result, starter = _convert(_deck(sec, RULE_4CELL))
                self.assertNotIn("/PROP/TYPE18/", starter)
                self.assertTrue(_warned(result, "is not an integrated beam"))

    def test_a_rule_on_a_section_no_beam_uses_is_reported(self):
        deck = "\n".join(["*KEYWORD", NODES, MAT_PLAS, SEC_RULE, RULE_4CELL,
                          "*END", ""])
        result, starter = _convert(deck)
        self.assertTrue(_warned(result, "no *ELEMENT_BEAM uses this section"))
        self.assertNotIn("/PROP/TYPE18/", starter)

    def test_a_spotweld_only_section_is_reported(self):
        mat = "\n".join(["*MAT_SPOTWELD", _row(9, "7.85E-9", 210000.0, 0.3,
                                               300.0)])
        result, starter = _convert(_deck(SEC_RULE, RULE_4CELL, mat=mat))
        self.assertTrue(_warned(result, "*MAT_SPOTWELD beam"))
        self.assertNotIn("/PROP/TYPE18/", starter)


# ── Multi card-set walks ─────────────────────────────────────────────────────

class SectionBeamMultiSetTests(unittest.TestCase):
    """"Card Sets.  For each BEAM section in the model, add one set of Cards 1
    and 2 ... This input ends at the next keyword ("*") card." (p.41-3)."""

    def test_every_card_set_is_read_not_only_the_first(self):
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(1, 2, 1.0, 2.0, 0) + "\n" + _row(11.0, 12.0,
                                                               13.0, 14.0)
                       + "\n" + _row(2, 2, 1.0, 2.0, 0) + "\n"
                       + _row(21.0, 22.0, 23.0, 24.0) + "\n"
                       + _row(3, 1, 1.0, -8, 0) + "\n"
                       + _row(4.0, 4.0, 6.0, 6.0) + "\n*END\n")
        self.assertEqual(sorted(st.sec_beams), [1, 2, 3])
        self.assertEqual(st.sec_beams[2].area, 21.0)
        self.assertEqual(st.sec_beams[3].irid, 8)

    def test_a_second_set_really_reaches_the_part_that_references_it(self):
        deck = "\n".join([
            "*KEYWORD", NODES,
            "*ELEMENT_BEAM",
            "".join(f"{v:>8}" for v in (1, 7, 1, 2, 3)),
            "*PART", "beam part", _row(7, 6, 9),
            MAT_PLAS,
            "*SECTION_BEAM",
            _row(5, 2, 1.0, 2.0, 0), _row(1.0, 2.0, 3.0, 4.0),
            _row(6, 2, 1.0, 2.0, 0), _row(24.0, 108.0, 228.0, 336.0),
            "*END", ""])
        result, starter = _convert(deck)
        self.assertIn("/PROP/BEAM/6", starter)
        self.assertEqual(_col_f(_cards(_block(starter, "/PROP/BEAM/6"))[2],
                                1, 20), 24.0)

    def test_the_title_card_repeats_per_set(self):
        """"an addition line is read for each section in 80a format"
        (p.41-1). Eating it only once shifts every later set up by one line."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM_TITLE\nfirst beam\n"
                       + _row(1, 2, 1.0, 2.0, 0) + "\n"
                       + _row(11.0, 0.0, 0.0, 0.0) + "\n"
                       + "second beam\n"
                       + _row(2, 2, 1.0, 2.0, 0) + "\n"
                       + _row(22.0, 0.0, 0.0, 0.0) + "\n*END\n")
        self.assertEqual(sorted(st.sec_beams), [1, 2])
        self.assertEqual(st.sec_beams[1].title, "first beam")
        self.assertEqual(st.sec_beams[2].title, "second beam")
        self.assertEqual(st.sec_beams[2].area, 22.0)

    def test_elform_twelve_takes_card_2c1_only_after_the_numeric_card_2(self):
        """"Include this card if ELFORM equals 12 and the preceding card is
        Card 2c" is exact: an ELFORM 12 set whose card 2 is a NAMED
        SECTION_nn takes NO card 2c.1. Verified against LS-PrePost, which
        round-trips a 7-set block containing both spellings."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(1, 12, 1.0, 2.0, 0) + "\n"
                       + _row(1.0, 2.0, 3.0, 4.0, 5.0, 6.0) + "\n"
                       + _row(7.0, 8.0, 9.0) + "\n"           # card 2c.1
                       + _row(2, 12, 1.0, 2.0, 0) + "\n"
                       + f"{'SECTION_09':<10}" + _row(30.0, 25.0) + "\n"
                       + _row(3, 2, 1.0, 2.0, 0) + "\n"
                       + _row(99.0, 0.0, 0.0, 0.0) + "\n*END\n")
        self.assertEqual(sorted(st.sec_beams), [1, 2, 3])
        self.assertEqual(st.sec_beams[1].area, 1.0)
        self.assertEqual(st.sec_beams[3].area, 99.0)

    def test_elform_two_takes_the_optcard_only_when_one_is_there(self):
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(1, 2, 1.0, 2.0, 0) + "\n"
                       + f"{'SECTION_01':<10}" + _row(1.0, 2.0, 3.0, 4.0)
                       + "\n" + f"{'OPTCARD':<10}" + _row(0.5) + "\n"
                       + _row(2, 2, 1.0, 2.0, 0) + "\n"
                       + f"{'SECTION_01':<10}" + _row(1.0, 2.0, 3.0, 4.0)
                       + "\n"
                       + _row(3, 2, 1.0, 2.0, 0) + "\n"
                       + _row(77.0, 0.0, 0.0, 0.0) + "\n*END\n")
        self.assertEqual(sorted(st.sec_beams), [1, 2, 3])
        self.assertEqual(st.sec_beams[3].area, 77.0)

    def test_a_duplicate_secid_is_reported(self):
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(5, 2, 1.0, 2.0, 0) + "\n" + _row(1.0) + "\n"
                       + _row(5, 2, 1.0, 2.0, 0) + "\n" + _row(2.0) + "\n"
                       + "*END\n")
        self.assertTrue(any("*SECTION_BEAM 5 is defined more than once" in w
                            for w in st.warnings), st.warnings)
        self.assertEqual(st.sec_beams[5].area, 2.0)

    def test_an_undefined_elform_stops_the_walk_loudly(self):
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(1, 10, 1.0, 2.0, 0) + "\n" + _row(1.0) + "\n"
                       + _row(2, 2, 1.0, 2.0, 0) + "\n" + _row(2.0) + "\n"
                       + "*END\n")
        self.assertEqual(sorted(st.sec_beams), [1])
        self.assertTrue(any("ELFORM=10 is not a defined beam formulation" in w
                            for w in st.warnings), st.warnings)

    def test_the_named_standard_section_is_reported_instead_of_mis_read(self):
        """Card 2b's field 1 is the A10 string SECTION_nn; the old catch-all
        resultant branch read it as an AREA (0.0) and D1/D2/D3 as Iyy/Izz/Ixx."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(1, 2, 1.0, 2.0, 0) + "\n"
                       + f"{'SECTION_01':<10}" + _row(1.0, 2.0, 3.0, 4.0)
                       + "\n*END\n")
        sec = st.sec_beams[1]
        self.assertEqual((sec.area, sec.iyy, sec.izz, sec.ixx), (0, 0, 0, 0))
        self.assertTrue(any("NAMED standard section 'SECTION_01'" in w
                            for w in st.warnings), st.warnings)

    def test_the_truss_card_gives_only_an_area(self):
        """ELFORM 3's card 2d is A RAMPT STRESS: fields 2/3 are a ramp TIME and
        an initial STRESS, not two bending inertias."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(1, 3, 1.0, 2.0, 0) + "\n"
                       + _row(12.5, 0.002, 250.0) + "\n*END\n")
        sec = st.sec_beams[1]
        self.assertEqual((sec.area, sec.iyy, sec.izz, sec.ixx),
                         (12.5, 0, 0, 0))
        self.assertTrue(any("ELFORM=3 is a TRUSS" in w for w in st.warnings))

    def test_the_spotweld_card_mapping_is_untouched(self):
        """ELFORM 9 keeps the exact fields k2rad's /PROP/TYPE13 connector path
        already read, so this card-dialect rewrite cannot move a nugget."""
        st = _dispatch("*KEYWORD\n*SECTION_BEAM\n"
                       + _row(2, 9, 1.0, 2.0, 1) + "\n"
                       + _row(0.003, 0.003, 0.0, 0.0, 0.0) + "\n*END\n")
        sec = st.sec_beams[2]
        self.assertEqual((sec.vol, sec.ca, sec.area), (0.003, 0.0, 0.0))
        self.assertEqual((sec.ts1, sec.ts2), (0.003, 0.003))


class SectionSolidMultiSetTests(unittest.TestCase):
    def test_every_card_set_is_read_not_only_the_first(self):
        st = _dispatch("*KEYWORD\n*SECTION_SOLID\n"
                       + _row(1, 1) + "\n" + _row(2, 16) + "\n"
                       + _row(3, 10) + "\n*END\n")
        self.assertEqual(sorted(st.sec_solids), [1, 2, 3])
        self.assertEqual(st.sec_solids[2].elform, 16)
        self.assertEqual(st.sec_solids[3].elform, 10)

    def test_the_user_solid_cards_are_strided_over(self):
        """ELFORM 101-105 add card 3 (NIP ... LMC ...), NIP integration-point
        cards and ceil(LMC/8) constant cards. Card 3 opens with a POSITIVE
        integer, so a walk that did not clear them would read the next set out
        of the middle of this one."""
        st = _dispatch("*KEYWORD\n*SECTION_SOLID\n"
                       + _row(1, 16) + "\n"
                       + _row(2, 101) + "\n"
                       + _row(2, 0, 0, 0, 3, 0, 0) + "\n"      # NIP=2, LMC=3
                       + _row(0.0, 0.0, 0.0, 1.0) + "\n"
                       + _row(0.5, 0.5, 0.5, 1.0) + "\n"
                       + _row(1.0, 2.0, 3.0) + "\n"
                       + _row(3, 10) + "\n*END\n")
        self.assertEqual(sorted(st.sec_solids), [1, 2, 3])
        self.assertEqual(st.sec_solids[3].elform, 10)

    def test_the_title_card_repeats_per_set(self):
        st = _dispatch("*KEYWORD\n*SECTION_SOLID_TITLE\nbrick\n"
                       + _row(1, 1) + "\nale\n" + _row(2, 11) + "\n*END\n")
        self.assertEqual(sorted(st.sec_solids), [1, 2])
        self.assertEqual(st.sec_solids[1].title, "brick")
        self.assertEqual(st.sec_solids[2].title, "ale")
        self.assertEqual(st.sec_solids[2].iale, 1)

    def test_a_duplicate_secid_is_reported(self):
        st = _dispatch("*KEYWORD\n*SECTION_SOLID\n"
                       + _row(1, 1) + "\n" + _row(1, 16) + "\n*END\n")
        self.assertTrue(any("*SECTION_SOLID 1 is defined more than once" in w
                            for w in st.warnings), st.warnings)
        self.assertEqual(st.sec_solids[1].elform, 16)

    def test_a_second_set_really_reaches_the_part_that_references_it(self):
        deck = "\n".join([
            "*KEYWORD",
            "*NODE"] + [f"{i:>8}{x:>16}{y:>16}{z:>16}" for i, x, y, z in [
                (1, 0.0, 0.0, 0.0), (2, 1.0, 0.0, 0.0), (3, 1.0, 1.0, 0.0),
                (4, 0.0, 1.0, 0.0), (5, 0.0, 0.0, 1.0), (6, 1.0, 0.0, 1.0),
                (7, 1.0, 1.0, 1.0), (8, 0.0, 1.0, 1.0)]] + [
            "*ELEMENT_SOLID",
            "".join(f"{v:>8}" for v in (1, 3)),
            "".join(f"{v:>8}" for v in (1, 2, 3, 4, 5, 6, 7, 8)),
            "*PART", "brick", _row(3, 12, 9),
            MAT_PLAS,
            "*SECTION_SOLID", _row(11, 1), _row(12, 1),
            "*END", ""])
        _, starter = _convert(deck)
        self.assertIn("/PROP/SOLID/12", starter)


class SectionDiscreteMultiSetTests(unittest.TestCase):
    """"Card Sets.  For each DISCRETE section include a pair of Cards 1 and 2."
    (p.41-32) - the pair is unconditional, so the stride is fixed."""

    def test_every_card_set_is_read_not_only_the_first(self):
        st = _dispatch("*KEYWORD\n*SECTION_DISCRETE\n"
                       + _row(1, 0, 0.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(0.0, 0.0) + "\n"
                       + _row(2, 0, 0.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(1.5, 2.5) + "\n*END\n")
        self.assertEqual(sorted(st.sec_discrete), [1, 2])
        self.assertEqual((st.sec_discrete[2].cdl, st.sec_discrete[2].tdl),
                         (1.5, 2.5))

    def test_a_blank_card_two_is_still_a_card(self):
        st = _dispatch("*KEYWORD\n*SECTION_DISCRETE\n"
                       + _row(1, 0, 0.0, 0.0, 0.0, 0.0) + "\n"
                       + "\n"
                       + _row(2, 1, 5.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(3.0, 4.0) + "\n*END\n")
        self.assertEqual(sorted(st.sec_discrete), [1, 2])
        self.assertEqual(st.sec_discrete[2].kd, 5.0)

    def test_the_title_card_repeats_per_set(self):
        st = _dispatch("*KEYWORD\n*SECTION_DISCRETE_TITLE\nspring a\n"
                       + _row(1, 0, 0.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(0.0, 0.0) + "\nspring b\n"
                       + _row(2, 0, 0.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(9.0, 8.0) + "\n*END\n")
        self.assertEqual(sorted(st.sec_discrete), [1, 2])
        self.assertEqual(st.sec_discrete[1].title, "spring a")
        self.assertEqual(st.sec_discrete[2].title, "spring b")
        self.assertEqual(st.sec_discrete[2].cdl, 9.0)

    def test_a_duplicate_secid_is_reported(self):
        st = _dispatch("*KEYWORD\n*SECTION_DISCRETE\n"
                       + _row(1, 0, 1.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(0.0, 0.0) + "\n"
                       + _row(1, 0, 2.0, 0.0, 0.0, 0.0) + "\n"
                       + _row(0.0, 0.0) + "\n*END\n")
        self.assertTrue(any("*SECTION_DISCRETE 1 is defined more than once" in w
                            for w in st.warnings), st.warnings)
        self.assertEqual(st.sec_discrete[1].kd, 2.0)

    def test_an_empty_block_still_reports_the_old_way(self):
        st = _dispatch("*KEYWORD\n*SECTION_DISCRETE\n" + _row(0) + "\n*END\n")
        self.assertEqual(st.sec_discrete, {})
        self.assertTrue(any("empty card" in w for w in st.warnings))


# ── Regression ───────────────────────────────────────────────────────────────

class IntegrationBeamRegressionTests(unittest.TestCase):
    def test_a_plain_beam_deck_emits_no_integrated_property(self):
        """A deck with no rule walks through this feature SILENTLY.

        The material is *MAT_ELASTIC on purpose: LAW1 is BEAM_CLASSIC, the one
        class /PROP/BEAM accepts, so the TYPE3 material gate is silent too and
        the assertion can stay at "no warning at all" rather than filtering.
        """
        deck = _deck("\n".join(["*SECTION_BEAM", _row(5, 2, 1.0, 2.0, 0),
                                _row(24.0, 108.0, 228.0, 336.0)]), "",
                     mat=MAT_ELAST)
        result, starter = _convert(deck)
        self.assertNotIn("/PROP/TYPE18/", starter)
        self.assertIn("/PROP/BEAM/5", starter)
        self.assertEqual(_p3(starter), (24.0, 108.0, 228.0, 336.0))
        self.assertEqual(result.warnings, [])

    def test_goldens_are_unchanged(self):
        from tests import test_golden
        suite = unittest.TestLoader().loadTestsFromModule(test_golden)
        res = unittest.TextTestRunner(verbosity=0,
                                      stream=open(os.devnull, "w")).run(suite)
        self.assertEqual((len(res.failures), len(res.errors)), (0, 0))


if __name__ == "__main__":
    unittest.main()
