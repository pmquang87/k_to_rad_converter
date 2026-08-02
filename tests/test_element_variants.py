"""Tests for the *ELEMENT_ VARIANT conversions:

  *ELEMENT_SHELL_THICKNESS / _BETA / _MCID / _OFFSET / _DOF (+ combinations)
        -> /SHELL // SH3N with the per-element Phi (deg) and Thick columns
  *ELEMENT_SHELL_<anything else>  -> the MESH is still kept, loudly warned
  *ELEMENT_BEAM_ORIENTATION       -> a synthesized /NODE at pos(N1) + (VX,VY,VZ)
  *ELEMENT_PLOTEL                 -> an inert /SPRING on a PLOTEL /PART +
                                     /PROP/TYPE4 (K=0, C=0, MASS=1.1e-15)

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_composites.py, tests/test_joints.py and tests/test_connectors.py).

Assertions are COLUMN-EXACT against the emitted cards — the whole point of the
batch is which absolute columns the optional fields occupy, and a substring
check would pass on a card the starter reads as a thickness of 15.03. Every
number (the thickness means, the third-node coordinates) is recomputed by hand
in the test rather than taken from the implementation.

The column layout the assertions pin was verified against the OpenRadioss
starter, not only against the shipped CFG: ``radioss41/ELEM/shell3n.cfg`` writes
the /SH3N blank gap as ``%30s`` (Phi at 71-90, Thick at 91-110) while its own
COMMENT line says 61-80 / 81-100 — and the starter follows the COMMENT. Running
this module's own deck through starter_win64 read element 1 back as
ANGLE=0.5235987755983 rad (=30 deg) / THICKNESS=2.5 and the /SH3N element as
ANGLE=0.2617993877991 rad (=15 deg) / THICKNESS=1.0, and the model's total mass
matched the hand calculation exactly.
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
from k2rad.writer.loads import PLOTEL_ID, PLOTEL_MASS   # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

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


def _blocks(starter: str, header: str):
    """Every block whose first line starts with *header*, as a list of its lines
    (header line included, the trailing HDR ruler excluded)."""
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
    """The single block starting with *header* (fails the test if not unique)."""
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _elem_rows(starter: str, header: str):
    """The element data rows of an element block (comments excluded)."""
    return [ln for ln in _block(starter, header)[1:] if not ln.startswith("#")]


def _col(line: str, a: int, b: int) -> str:
    """Raw 1-based inclusive column slice [a, b] (unstripped)."""
    return line[a - 1:b]


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _col_f(line: str, a: int, b: int) -> float:
    return float(line[a - 1:b] or 0)


# ── Deck pieces ──────────────────────────────────────────────────────────────

def _i8(*v):
    return "".join(f"{x:>8}" for x in v)


def _f16(*v):
    return "".join(f"{x:>16}" for x in v)


def _f10(*v):
    return "".join(f"{x:>10}" for x in v)


def _row10(*v):
    return "".join(f"{x:>10}" for x in v)


# 6 nodes: a 10x10 quad (1-2-3-4) plus a second one (2-5-6-3), all in z=0.
NODES = "*NODE\n" + "\n".join(
    f"{n:>8}{x:>16}{y:>16}{z:>16}" for n, x, y, z in [
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
        (4, 0.0, 10.0, 0.0), (5, 20.0, 0.0, 0.0), (6, 20.0, 10.0, 0.0),
        (7, 0.0, 0.0, 50.0), (8, 0.0, 0.0, 60.0),
    ]) + "\n"

SHELL_PART = ("*PART\nplate\n" + _row10(1, 1, 1) + "\n"
              "*SECTION_SHELL\n" + _row10(1, 2) + "\n"
              + _row10(1.0, 1.0, 1.0, 1.0) + "\n"
              "*MAT_ELASTIC\n" + _row10(1, 7.85e-9, 210000.0, 0.3) + "\n")

BEAM_PART = ("*PART\nbar\n" + _row10(2, 2, 1) + "\n"
             "*SECTION_BEAM\n" + _row10(2, 2) + "\n"
             + _row10(100.0, 833.0, 833.0, 1400.0) + "\n")

END = "*CONTROL_TERMINATION\n" + _row10(0.01) + "\n*END\n"


def _shell_deck(keyword: str, cards) -> str:
    """A minimal one-part shell deck carrying *cards* under *keyword*."""
    return ("*KEYWORD\n" + NODES + SHELL_PART
            + keyword + "\n" + "\n".join(cards) + "\n" + END)


# ─────────────────────────────────────────────────────────────────────────────
# A. *ELEMENT_SHELL_THICKNESS / _BETA — the element Phi / Thick columns
# ─────────────────────────────────────────────────────────────────────────────

class ShellThicknessBetaTests(unittest.TestCase):
    """THIC1..THIC4 -> the element's own Thick field (mean), BETA -> Phi.

    Neither is a property and neither is a skew: shell4n.cfg's CARD is
    ``%10d%10d%10d%10d%10d%10s%20lg%20lg`` — id, n1..n4, a BLANK 10-char field,
    then PHI_Z and Thick. dyna2rad puts the same two values on the same two
    element-card fields (convertelements.cxx:284-314).
    """

    def test_quad_thickness_is_the_mean_and_lands_in_columns_81_100(self):
        """THIC1..4 = 2,2,3,3 -> Thick = (2+2+3+3)/4 = 2.5, right-justified in
        the 81-100 field. Radioss uses it INSTEAD of the /PROP thickness
        (cinmas.F:324-329, THKE/=0 branch)."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 2.0, 3.0, 3.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_i(row, 1, 10), 1)
        self.assertEqual([_col_i(row, a, a + 9) for a in (11, 21, 31, 41)],
                         [1, 2, 3, 4])
        self.assertEqual(_col(row, 51, 60).strip(), "0")   # blank field
        self.assertEqual(_col_f(row, 61, 80), 0.0)         # Phi, no BETA given
        self.assertEqual(_col_f(row, 81, 100), 2.5)
        self.assertEqual(len(row), 100)

    def test_beta_lands_in_columns_61_80_in_degrees(self):
        """hm_read_shell.F:170 does ANGLE(I) = HM_ANGLE(I)*PI/180, so the card
        field is DEGREES and BETA is copied across 1:1 — no conversion."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_BETA",
            [_i8(1, 1, 1, 2, 3, 4), _f16("", "", "", "", 30.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 61, 80), 30.0)
        self.assertEqual(_col_f(row, 81, 100), 0.0)

    def test_thickness_and_beta_share_one_optional_card(self):
        """*ELEMENT_SHELL_THICKNESS and _BETA read the IDENTICAL card — 5 x F16
        THIC1..THIC4 + BETA (Vol I R17; shell.cfg:193). The suffix names which
        datum is meant, not which columns exist."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS_BETA",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 2.0, 3.0, 3.0, 30.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 61, 80), 30.0)
        self.assertEqual(_col_f(row, 81, 100), 2.5)

    def test_beta_only_deck_still_keeps_the_thicknesses(self):
        """DELIBERATE DIVERGENCE from dyna2rad: under *_BETA it tests
        elemKeyWord.find("THICK"), which fails, and forces Thick=0 — throwing
        away thicknesses its own reader just parsed off the shared card."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_BETA",
            [_i8(1, 1, 1, 2, 3, 4), _f16(1.5, 1.5, 1.5, 1.5, 30.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 81, 100), 1.5)

    def test_tri_thickness_averages_three_cells_and_uses_shell_columns(self):
        """A collapsed quad (n1 n2 n3 n3) is routed to /SH3N, and its thickness
        mean is over THIC1..THIC3 — THIC4 duplicates THIC3 under LS-DYNA's
        convention, so including it would be double counting. The /SH3N Phi and
        Thick fields sit at the SAME absolute columns as /SHELL's."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS_BETA",
            [_i8(1, 1, 2, 5, 6, 6), _f16(1.0, 2.0, 3.0, 3.0, 15.0)]))
        row = _elem_rows(starter, "/SH3N/1")[0]
        self.assertEqual([_col_i(row, a, a + 9) for a in (1, 11, 21, 31)],
                         [1, 2, 5, 6])
        self.assertEqual(_col(row, 41, 60).strip(), "0")   # blank field
        self.assertEqual(_col_f(row, 61, 80), 15.0)
        self.assertAlmostEqual(_col_f(row, 81, 100), (1.0 + 2.0 + 3.0) / 3.0)
        self.assertEqual(len(row), 100)

    def test_three_id_triangle_averages_three_cells(self):
        """A triangle written as 3 ids with a blank N4 column: only THIC1..3
        exist, so the mean is over them."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 2, 5, 6), _f16(1.0, 2.0, 6.0)]))
        row = _elem_rows(starter, "/SH3N/1")[0]
        self.assertEqual(_col_f(row, 81, 100), 3.0)

    def test_blank_cells_are_excluded_from_the_mean(self):
        """DELIBERATE DIVERGENCE from dyna2rad, whose divisor is always the node
        count (convertelements.cxx:290-301) because its reader cannot tell a
        blank cell from 0.0: THIC1=2.0 with three blanks converts to 0.5 there —
        a quarter of the thickness, hence a quarter of the mass. Here the mean
        is over the POPULATED cells, so it stays 2.0, and the loss of
        information is warned about instead of applied."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 81, 100), 2.0)
        self.assertTrue(any("only SOME of the THIC1..THIC4 cells" in w
                            for w in result.warnings), result.warnings)

    def test_explicit_zero_counts_as_populated(self):
        """An explicit 0.0 is the user saying zero, unlike a blank cell — so it
        enters the mean: (2+0+2+0)/4 = 1.0."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 0.0, 2.0, 0.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 81, 100), 1.0)

    def test_all_zero_thickness_falls_back_to_the_property(self):
        """Thick = 0 on the card is the documented 'use the /PROP thickness'
        value (cinmas.F:324-329), so no field is emitted at all and the row
        stays the 60-char shape a plain *ELEMENT_SHELL produces."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4), _f16(0.0, 0.0, 0.0, 0.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(len(row), 60)
        self.assertEqual(row, _row10(1, 1, 2, 3, 4, 0))

    def test_free_format_optional_card_is_read(self):
        """A comma-separated optional card is legal LS-DYNA and must not be
        sliced at 16 columns."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS_BETA",
            [_i8(1, 1, 1, 2, 3, 4), "2.0,2.0,3.0,3.0,45.0"]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 61, 80), 45.0)
        self.assertEqual(_col_f(row, 81, 100), 2.5)

    def test_two_elements_do_not_desync(self):
        """The optional card is consumed POSITIONALLY, one per element — the
        second element must not read the first one's thickness card."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 2.0, 2.0, 2.0),
             _i8(2, 1, 2, 5, 6, 3), _f16(5.0, 5.0, 5.0, 5.0)]))
        rows = _elem_rows(starter, "/SHELL/1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(_col_f(rows[0], 81, 100), 2.0)
        self.assertEqual(_col_f(rows[1], 81, 100), 5.0)


# ─────────────────────────────────────────────────────────────────────────────
# B. The variants whose data has no Radioss home
# ─────────────────────────────────────────────────────────────────────────────

class ShellInexpressibleDataTests(unittest.TestCase):
    """_MCID / _OFFSET / _DOF: the ELEMENTS survive, the datum is warned about."""

    def test_mcid_is_not_written_into_the_angle_column(self):
        """MCID and BETA occupy the SAME columns 65-80 of the optional card and
        mean different things: MCID is a *DEFINE_COORDINATE_SYSTEM id, BETA is
        an angle in degrees. Writing MCID=7 into Phi would rotate the material
        axes by 7 degrees on every element of the block."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_MCID",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 2.0, 2.0, 2.0, 7)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 61, 80), 0.0)      # NOT 7
        self.assertEqual(_col_f(row, 81, 100), 2.0)     # thickness still kept
        hit = [w for w in result.warnings if "coordinate-system id MCID" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("DROPPED", hit[0])

    def test_mcid_zero_is_not_warned_about(self):
        """MCID=0 means 'no system' — nothing was lost, so no warning."""
        result, _ = _convert(_shell_deck(
            "*ELEMENT_SHELL_MCID",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 2.0, 2.0, 2.0, 0)]))
        self.assertFalse(any("MCID" in w for w in result.warnings))

    def test_offset_card_is_consumed_and_counted(self):
        """The _OFFSET card is an EXTRA F16 card per element. Consuming it is
        what keeps the next element's base card from being read as thicknesses;
        the value itself has no /SHELL field."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS_OFFSET",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0, 2.0, 2.0, 2.0), _f16(0.5),
             _i8(2, 1, 2, 5, 6, 3), _f16(4.0, 4.0, 4.0, 4.0), _f16(0.5)]))
        rows = _elem_rows(starter, "/SHELL/1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(_col_f(rows[0], 81, 100), 2.0)
        self.assertEqual(_col_f(rows[1], 81, 100), 4.0)
        hit = [w for w in result.warnings if "mid-surface offset" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("2 element(s)", hit[0])

    def test_dof_card_is_consumed_and_counted(self):
        """The _DOF card is blank(16) + NS1..NS4 as I8, so the scalar node ids
        start at column 17."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_DOF",
            [_i8(1, 1, 1, 2, 3, 4), " " * 16 + _i8(11, 12, 13, 14),
             _i8(2, 1, 2, 5, 6, 3), " " * 16 + _i8(21, 22, 23, 24)]))
        self.assertEqual(len(_elem_rows(starter, "/SHELL/1")), 2)
        hit = [w for w in result.warnings if "scalar-node references" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("2 element(s)", hit[0])

    def test_all_options_combined_still_converts_every_element(self):
        """*ELEMENT_SHELL_THICKNESS_MCID_OFFSET_DOF is 4 cards per element and
        is one of the spellings dyna2rad's exact-match keyword table rejects
        outright."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS_MCID_OFFSET_DOF",
            [_i8(1, 1, 1, 2, 3, 4), _f16(3.0, 3.0, 3.0, 3.0, 9), _f16(0.25),
             " " * 16 + _i8(11, 12, 13, 14),
             _i8(2, 1, 2, 5, 6, 3), _f16(6.0, 6.0, 6.0, 6.0, 9), _f16(0.25),
             " " * 16 + _i8(21, 22, 23, 24)]))
        rows = _elem_rows(starter, "/SHELL/1")
        self.assertEqual(len(rows), 2)
        self.assertEqual([_col_i(r, 1, 10) for r in rows], [1, 2])
        self.assertEqual(_col_f(rows[0], 81, 100), 3.0)
        self.assertEqual(_col_f(rows[1], 81, 100), 6.0)
        self.assertEqual(result.skipped_keywords, [])

    def test_eight_node_shell_consumes_the_second_thickness_card(self):
        """Vol I R17: THIC5..THIC8 is 'only required if mid-side nodes are
        defined'. Missing that card would desync the whole block."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4, 11, 12, 13, 14),
             _f16(2.0, 2.0, 2.0, 2.0), _f16(1.0, 1.0, 1.0, 1.0),
             _i8(2, 1, 2, 5, 6, 3)]))
        rows = _elem_rows(starter, "/SHELL/1")
        self.assertEqual([_col_i(r, 1, 10) for r in rows], [1, 2])
        self.assertEqual(_col_f(rows[0], 81, 100), 2.0)
        self.assertTrue(any("mid-side nodes" in w for w in result.warnings),
                        result.warnings)


# ─────────────────────────────────────────────────────────────────────────────
# C. Mesh preservation — the headline of the batch
# ─────────────────────────────────────────────────────────────────────────────

class ShellMeshPreservationTests(unittest.TestCase):
    """No *ELEMENT_SHELL_<suffix> may take its elements with it.

    dispatch() is an exact dict lookup, and _make_parts_and_elements emits
    elements INSIDE the state.parts loop — so a shell keyword that misses the
    table leaves the /PART in the deck with no element block under it. Nothing
    warns, and the conversion log says "skipped: 1 unsupported keyword", which
    reads like a lost card rather than a lost mesh.
    """

    #: Every suffix worth naming. The last four are the ones dyna2rad's CFG
    #: table rejects with an ERROR and skips wholesale, plus a spelling that
    #: exists in no manual at all.
    SUFFIXES = [
        "", "_THICKNESS", "_BETA", "_MCID", "_OFFSET", "_DOF",
        "_THICKNESS_BETA", "_THICKNESS_MCID", "_BETA_OFFSET",
        "_THICKNESS_BETA_OFFSET", "_MCID_OFFSET",
        "_THICKNESS_BETA_OFFSET_DOF",
        "_COMPOSITE", "_COMPOSITE_LONG", "_SHL4_TO_SHL8", "_SOURCE_SINK",
        "_TOTALLY_MADE_UP",
    ]

    def test_every_suffix_keeps_its_elements(self):
        for suffix in self.SUFFIXES:
            with self.subTest(suffix=suffix):
                # One base card, then a card of each optional shape. A handler
                # that mis-counts either loses the element or invents one.
                cards = [_i8(1, 1, 1, 2, 3, 4)]
                if suffix and suffix != "_TOTALLY_MADE_UP":
                    cards.append(_f16(2.0, 2.0, 2.0, 2.0, 1.0))
                result, starter = _convert(
                    _shell_deck(f"*ELEMENT_SHELL{suffix}", cards))
                rows = _elem_rows(starter, "/SHELL/1")
                self.assertEqual(len(rows), 1, f"{suffix}: {rows}")
                self.assertEqual([_col_i(rows[0], a, a + 9)
                                  for a in (1, 11, 21, 31, 41)],
                                 [1, 1, 2, 3, 4])
                self.assertEqual(result.skipped_keywords, [])

    def test_unknown_suffix_warns_loudly_and_names_the_option(self):
        result, _ = _convert(_shell_deck(
            "*ELEMENT_SHELL_SHL4_TO_SHL8", [_i8(1, 1, 1, 2, 3, 4)]))
        hit = [w for w in result.warnings if "SHL4_TO_SHL8" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("not implemented", hit[0])
        self.assertIn("MESH is preserved", hit[0])

    def test_unknown_suffix_does_not_invent_elements_from_data_cards(self):
        """The *ELEMENT_SHELL_COMPOSITE ply card (MID THICK B TMID pairs) is not
        connectivity. Taking every line of an unrecognized block at face value
        would turn each ply card into a bogus element with node ids read out of
        thicknesses and angles."""
        state = _dispatch(
            "*KEYWORD\n"
            "*ELEMENT_SHELL_COMPOSITE\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + _row10(1, 0.125, 0.0, 0, 2, 0.125, 90.0, 0) + "\n"
            + _row10(3, 0.125, 45.0, 0) + "\n"
            + _i8(2, 1, 2, 5, 6, 3) + "\n"
            + _row10(1, 0.125, 0.0, 0, 2, 0.125, 90.0, 0) + "\n"
            "*END\n")
        self.assertEqual([e.eid for e in state.shell_elems], [1, 2])
        self.assertEqual(state.shell_elems[0].nodes, [1, 2, 3, 4])
        self.assertEqual(state.shell_elems[1].nodes, [2, 5, 6, 3])
        self.assertEqual(state.skipped_keywords, [])

    def test_unknown_suffix_drops_a_repeated_element_id(self):
        """An all-integer data card can imitate connectivity. Inside one block
        element ids are unique, so a repeat is data, not a second element."""
        state = _dispatch(
            "*KEYWORD\n"
            "*ELEMENT_SHELL_MADE_UP\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + _i8(1, 1, 1, 1, 2, 1) + "\n"          # imitates a base card
            "*END\n")
        self.assertEqual([e.eid for e in state.shell_elems], [1])

    def test_isogeometric_patch_is_skipped_not_turned_into_elements(self):
        """*ELEMENT_SHELL_NURBS_PATCH card 1 is NPEID PID NPR PR NPS PS: six
        positive integers that pass every connectivity test while meaning
        polynomial orders and control-point counts. Keeping the block "as mesh"
        would invent elements on node ids that do not exist — turning a keyword
        k2rad merely skipped into starter ERROR 78."""
        result, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + "*ELEMENT_SHELL_NURBS_PATCH\n"
            + _i8(9, 1, 3, 5, 3, 5, 0, 0, 2) + "\n" + END)
        self.assertEqual(len(_elem_rows(starter, "/SHELL/1")), 1)
        self.assertIn("ELEMENT_SHELL_NURBS_PATCH", result.skipped_keywords)
        self.assertTrue(any("ISOGEOMETRIC" in w for w in result.warnings),
                        result.warnings)

    def test_beam_suffixes_keep_their_elements(self):
        for suffix in ("", "_ORIENTATION", "_OFFSET", "_OFFSET_ORIENTATION",
                       "_THICKNESS", "_SECTION", "_SCALAR", "_PID",
                       "_WARPAGE", "_MADE_UP"):
            with self.subTest(suffix=suffix):
                cards = [_i8(11, 2, 7, 8)]
                if "ORIENTATION" in suffix or "OFFSET" in suffix:
                    if "OFFSET" in suffix:
                        cards.append(_f10(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
                    if "ORIENTATION" in suffix:
                        cards.append(_f10(0.0, 1.0, 0.0))
                deck = ("*KEYWORD\n" + NODES + SHELL_PART + BEAM_PART
                        + f"*ELEMENT_BEAM{suffix}\n" + "\n".join(cards) + "\n"
                        + END)
                result, starter = _convert(deck)
                rows = _elem_rows(starter, "/BEAM/2")
                self.assertEqual(len(rows), 1, f"{suffix}: {rows}")
                self.assertEqual([_col_i(rows[0], a, a + 9) for a in (1, 11, 21)],
                                 [11, 7, 8])
                self.assertEqual(result.skipped_keywords, [])

    def test_plotel_is_not_skipped(self):
        result, _ = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + "*ELEMENT_PLOTEL\n" + _i8(500, 1, 3) + "\n" + END)
        self.assertEqual(result.skipped_keywords, [])


# ─────────────────────────────────────────────────────────────────────────────
# D. *ELEMENT_BEAM_ORIENTATION -> synthesized third node
# ─────────────────────────────────────────────────────────────────────────────

def _beam_deck(keyword: str, cards, extra_nodes: str = "") -> str:
    return ("*KEYWORD\n" + NODES + extra_nodes + SHELL_PART + BEAM_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + keyword + "\n" + "\n".join(cards) + "\n" + END)


class BeamOrientationTests(unittest.TestCase):
    """VX/VY/VZ is relative to N1 and "points to a virtual third node"
    (Vol I R17), so the node goes at pos(N1) + V — RAW, unnormalized, exactly
    what dyna2rad computes (convertelements.cxx:220-232)."""

    def _n3_and_pos(self, vx, vy, vz, n1=7, n2=8):
        result, starter = _convert(_beam_deck(
            "*ELEMENT_BEAM_ORIENTATION",
            [_i8(11, 2, n1, n2), _f10(vx, vy, vz)]))
        row = _elem_rows(starter, "/BEAM/2")[0]
        n3 = _col_i(row, 31, 40)
        node_rows = [ln for ln in _block(starter, "/NODE")[1:]
                     if not ln.startswith("#")]
        pos = None
        for ln in node_rows:
            if _col_i(ln, 1, 10) == n3:
                pos = (_col_f(ln, 11, 30), _col_f(ln, 31, 50),
                       _col_f(ln, 51, 70))
        return result, starter, n3, pos

    def test_third_node_position_is_n1_plus_the_raw_vector(self):
        """Node 7 is at (0, 0, 50) and V = (0, 3, 4): the synthesized node must
        be at (0, 3, 54), NOT at the normalized (0, 0.6, 50.8). |V| is
        irrelevant — Radioss stores V/|V| itself (hm_read_beam.F:158-161)."""
        _, _, n3, pos = self._n3_and_pos(0.0, 3.0, 4.0)
        self.assertEqual(pos, (0.0, 3.0, 54.0))
        self.assertGreater(n3, 8)          # above every user node id

    def test_third_node_is_actually_wired_into_the_beam_card(self):
        """dyna2rad writes elemNodes[2] BEFORE resize(3), and a beam whose N3
        column is blank arrives with 2 nodes — so the resize zeroes the slot
        again and node_ID3 is emitted as 0 for exactly the elements
        _ORIENTATION exists for. The node is created and then orphaned."""
        _, starter, n3, pos = self._n3_and_pos(0.0, 1.0, 0.0)
        self.assertNotEqual(n3, 0)
        self.assertIsNotNone(pos, "the third node must be in the /NODE block")
        row = _elem_rows(starter, "/BEAM/2")[0]
        self.assertEqual([_col_i(row, a, a + 9) for a in (1, 11, 21, 31)],
                         [11, 7, 8, n3])

    def test_zero_vector_creates_no_node_and_keeps_the_card_n3(self):
        """dyna2rad's rule: |V| == 0 -> no node, no fallback direction. The beam
        keeps whatever N3 the base card carried; a blank one leaves the starter
        to apply INFO 2093 (N3 := N2)."""
        result, starter = _convert(_beam_deck(
            "*ELEMENT_BEAM_ORIENTATION",
            [_i8(11, 2, 7, 8), _f10(0.0, 0.0, 0.0)]))
        row = _elem_rows(starter, "/BEAM/2")[0]
        self.assertEqual(_col_i(row, 31, 40), 0)
        node_ids = [_col_i(ln, 1, 10) for ln in _block(starter, "/NODE")[1:]
                    if not ln.startswith("#")]
        self.assertEqual(node_ids, list(range(1, 9)))
        self.assertTrue(any("ZERO orientation vector" in w
                            for w in result.warnings), result.warnings)

    def test_explicit_card_n3_is_overridden_by_the_vector(self):
        """When both are given LS-DYNA says N3 "should be left undefined", and
        the vector is the newer, more specific statement — it wins."""
        result, starter = _convert(_beam_deck(
            "*ELEMENT_BEAM_ORIENTATION",
            [_i8(11, 2, 7, 8, 3), _f10(0.0, 1.0, 0.0)]))
        row = _elem_rows(starter, "/BEAM/2")[0]
        self.assertGreater(_col_i(row, 31, 40), 8)
        self.assertTrue(any("third node(s) synthesized" in w
                            for w in result.warnings), result.warnings)

    def test_identical_n1_and_vector_share_one_node(self):
        """dyna2rad creates a brand-new node per element even when many beams
        carry the same N1 and vector. Sharing is the same geometry with fewer
        orphan nodes."""
        deck = ("*KEYWORD\n" + NODES + SHELL_PART + BEAM_PART
                + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
                + "*ELEMENT_BEAM_ORIENTATION\n"
                + _i8(11, 2, 7, 8) + "\n" + _f10(0.0, 1.0, 0.0) + "\n"
                + _i8(12, 2, 7, 8) + "\n" + _f10(0.0, 1.0, 0.0) + "\n"
                + _i8(13, 2, 7, 8) + "\n" + _f10(0.0, 2.0, 0.0) + "\n"
                + END)
        _, starter = _convert(deck)
        n3s = [_col_i(r, 31, 40) for r in _elem_rows(starter, "/BEAM/2")]
        self.assertEqual(n3s[0], n3s[1])
        self.assertNotEqual(n3s[0], n3s[2])

    def test_collinear_vector_is_warned_about(self):
        """V parallel to the N1-N2 axis gives a third node ON the beam line: no
        local Y-Z frame can be built from it and Iyy/Izz land on arbitrary axes.
        dyna2rad does not test for this at all."""
        # Nodes 7 -> 8 run along +z; so does V.
        result, _ = _convert(_beam_deck(
            "*ELEMENT_BEAM_ORIENTATION",
            [_i8(11, 2, 7, 8), _f10(0.0, 0.0, 5.0)]))
        self.assertTrue(any("PARALLEL to their own N1-N2 axis" in w
                            for w in result.warnings), result.warnings)

    def test_missing_n1_node_is_warned_not_crashed(self):
        state = _dispatch(
            "*KEYWORD\n*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 999, 998) + "\n" + _f10(0.0, 1.0, 0.0) + "\n*END\n")
        self.assertEqual(len(state.beam_elems), 1)
        self.assertEqual(state.beam_elems[0].vy, 1.0)

    def test_orientation_card_is_ten_wide_not_sixteen(self):
        """beam.cfg reads the orientation card as %10lg%10lg%10lg while the
        shell's optional card is %16lg — the two families do NOT share a width,
        and slicing this one at 16 would read VX as 'VX and half of VY'."""
        state = _dispatch(
            "*KEYWORD\n*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 7, 8) + "\n"
            + f"{1.0:>10}{2.0:>10}{3.0:>10}" + "\n*END\n")
        e = state.beam_elems[0]
        self.assertEqual((e.vx, e.vy, e.vz), (1.0, 2.0, 3.0))


class NodeIdAllocatorTests(unittest.TestCase):
    """state.next_node_id(): the guarded allocator the synthesis draws from."""

    def test_ids_are_above_every_existing_node(self):
        st = ConversionState()
        from k2rad.state import NodeData
        st.nodes[1] = NodeData(0.0, 0.0, 0.0)
        st.nodes[9_000_042] = NodeData(0.0, 0.0, 0.0)
        self.assertEqual(st.next_node_id(), 9_000_043)

    def test_ids_are_unique_without_registering_them_first(self):
        """The open-coded ``max(state.nodes)+1`` sites are only safe because each
        registers before the next one runs. A caller that allocates a batch and
        registers later would get the SAME id twice, and state.nodes is a dict:
        the second write replaces the first node instead of erroring."""
        st = ConversionState()
        from k2rad.state import NodeData
        st.nodes[5] = NodeData(0.0, 0.0, 0.0)
        ids = [st.next_node_id() for _ in range(4)]
        self.assertEqual(ids, [6, 7, 8, 9])
        self.assertEqual(len(set(ids)), 4)

    def test_empty_model_uses_the_house_base(self):
        self.assertEqual(ConversionState().next_node_id(), 90_000_001)

    def test_allocator_skips_a_user_node_that_appears_later(self):
        st = ConversionState()
        from k2rad.state import NodeData
        st.nodes[1] = NodeData(0.0, 0.0, 0.0)
        first = st.next_node_id()             # 2, not yet registered
        st.nodes[2] = NodeData(1.0, 1.0, 1.0)  # a *NODE parsed afterwards
        self.assertNotEqual(st.next_node_id(), first)

    def test_synthesized_node_does_not_collide_with_a_high_user_id(self):
        """A deck whose node ids already sit above the auto-id base must not see
        one of its nodes teleported to the orientation point."""
        high = "*NODE\n" + f"{90000001:>8}{1.0:>16}{2.0:>16}{3.0:>16}\n"
        _, starter = _convert(_beam_deck(
            "*ELEMENT_BEAM_ORIENTATION",
            [_i8(11, 2, 7, 8), _f10(0.0, 1.0, 0.0)], extra_nodes=high))
        rows = [ln for ln in _block(starter, "/NODE")[1:]
                if not ln.startswith("#")]
        ids = [_col_i(ln, 1, 10) for ln in rows]
        self.assertEqual(len(ids), len(set(ids)))
        kept = [ln for ln in rows if _col_i(ln, 1, 10) == 90000001][0]
        self.assertEqual((_col_f(kept, 11, 30), _col_f(kept, 31, 50),
                          _col_f(kept, 51, 70)), (1.0, 2.0, 3.0))
        n3 = _col_i(_elem_rows(starter, "/BEAM/2")[0], 31, 40)
        self.assertEqual(n3, 90000002)


# ─────────────────────────────────────────────────────────────────────────────
# E. *ELEMENT_PLOTEL -> inert /SPRING
# ─────────────────────────────────────────────────────────────────────────────

def _plotel_deck(cards, extra: str = "") -> str:
    return ("*KEYWORD\n" + NODES + SHELL_PART + extra
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + "*ELEMENT_PLOTEL\n" + "\n".join(cards) + "\n" + END)


class PlotelTests(unittest.TestCase):
    """A visualization line must add no stiffness, no meaningful mass, and must
    not govern the time step."""

    def _prop_cards(self, starter):
        blk = _block(starter, f"/PROP/TYPE4/{PLOTEL_ID}")
        return [ln for ln in blk[2:] if not ln.startswith("#")]

    def test_part_and_property_use_the_lsdyna_id(self):
        """Vol I R17 Remark 1: "Part ID, 10000000, is assigned to PLOTEL
        elements." The card has no PID column, so the converter fabricates the
        part; dyna2rad picks the same id."""
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)]))
        self.assertEqual(PLOTEL_ID, 10000000)
        part = _block(starter, f"/PART/{PLOTEL_ID}")
        self.assertEqual(part[1], "PLOTEL")
        self.assertEqual(_col_i(part[2], 1, 10), PLOTEL_ID)   # prop_ID
        self.assertEqual(_col_i(part[2], 11, 20), 0)          # mat_ID: none
        self.assertEqual(_block(starter, f"/PROP/TYPE4/{PLOTEL_ID}")[1],
                         "PLOTEL")

    def test_elements_are_two_node_springs(self):
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3), _i8(501, 2, 4)]))
        rows = _elem_rows(starter, f"/SPRING/{PLOTEL_ID}")
        self.assertEqual([(_col_i(r, 1, 10), _col_i(r, 11, 20),
                           _col_i(r, 21, 30)) for r in rows],
                         [(500, 1, 3), (501, 2, 4)])
        for r in rows:                        # no skew, no extra nodes
            self.assertEqual(len(r), 30)

    def test_property_has_zero_stiffness_and_zero_damping(self):
        """/PROP/TYPE4 card 3 is K C A B D. K=0 keeps the nodal stiffness at
        zero (r1len3.F:81-105 only overwrites STI when XK/=0 or XC/=0), so the
        spring cannot change the time step of the parts it is drawn on."""
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)]))
        k_card = self._prop_cards(starter)[1]
        self.assertEqual([_col_f(k_card, a, a + 19)
                          for a in (1, 21, 41, 61, 81)],
                         [0.0, 0.0, 0.0, 0.0, 0.0])

    def test_property_mass_is_the_smallest_legal_value(self):
        """hm_read_prop04.F:136-142 rejects MASS <= 1e-15 with ERROR 229
        (** ERROR IN SPRING PROPERTY (MASS)), and r1len3.F:143 turns MASS = 0
        into a DT=0 element. 1.1e-15 is the value dyna2rad writes."""
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)]))
        mass_card = self._prop_cards(starter)[0]
        self.assertEqual(PLOTEL_MASS, 1.1e-15)
        self.assertGreater(_col_f(mass_card, 1, 20), 1e-15)
        self.assertEqual(_col_f(mass_card, 1, 20), PLOTEL_MASS)
        self.assertEqual(_col_i(mass_card, 51, 60), 0)   # sens_ID
        self.assertEqual(_col_i(mass_card, 61, 70), 0)   # Isflag
        self.assertEqual(_col_i(mass_card, 71, 80), 0)   # Ileng

    def test_property_has_no_functions_and_no_rupture_limits(self):
        """Everything except MASS stays at the reader defaults, matching
        dyna2rad, which sets MASS and nothing else."""
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)]))
        cards = self._prop_cards(starter)
        fct_card = cards[2]
        self.assertEqual([_col_i(fct_card, a, a + 9)
                          for a in (1, 11, 21, 31, 41)], [0, 0, 0, 0, 0])
        self.assertEqual(_col_f(fct_card, 61, 80), 0.0)   # DeltaMin
        self.assertEqual(_col_f(fct_card, 81, 100), 0.0)  # DeltaMax
        self.assertEqual([_col_f(cards[3], a, a + 19)
                          for a in (1, 21, 41, 61)], [0.0, 0.0, 0.0, 0.0])

    def test_time_step_formula_is_non_governing(self):
        """r1len3.F:139: DT = XM / MAX(EM15, SQRT(XC^2 + XM*XK) + XC). With
        K = C = 0 the denominator FLOORS at the 1e-15 clamp instead of going to
        zero, so dt = 1.1e-15/1e-15 = 1.1 s — some six orders of magnitude above
        a structural shell step. (Measured 0.55 s in a real starter run of this
        module's deck, against 1.67e-6 s for its shells.)"""
        dt = PLOTEL_MASS / max(1e-15, (0.0 ** 2 + PLOTEL_MASS * 0.0) ** 0.5)
        self.assertGreater(dt, 1.0)

    def test_id_collides_with_a_user_part(self):
        """A deck that already defines *PART 10000000 (the LS-DYNA convention
        for PLOTELs) must not get two /PART/10000000 — that is starter
        ERROR 79."""
        extra = ("*PART\nmine\n" + _row10(PLOTEL_ID, 1, 1) + "\n")
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)], extra=extra))
        headers = [b[0] for b in _blocks(starter, "/PART/")]
        self.assertEqual(len(headers), len(set(headers)), headers)
        # The user's part keeps the id; the PLOTEL part is pushed elsewhere.
        self.assertEqual(_block(starter, f"/PART/{PLOTEL_ID}")[1], "mine")
        plotel = [b for b in _blocks(starter, "/PART/") if b[1] == "PLOTEL"]
        self.assertEqual(len(plotel), 1, headers)
        plotel_id = int(plotel[0][0].rsplit("/", 1)[1])
        self.assertNotEqual(plotel_id, PLOTEL_ID)
        self.assertEqual(len(_elem_rows(starter, f"/SPRING/{plotel_id}")), 1)

    def test_id_collides_with_a_user_section(self):
        """k2rad emits /PROP/SHELL|SOLID|BEAM under the SECID verbatim, so a
        *SECTION_SHELL 10000000 owns that /PROP id."""
        extra = ("*SECTION_SHELL\n" + _row10(PLOTEL_ID, 2) + "\n"
                 + _row10(1.0, 1.0, 1.0, 1.0) + "\n")
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)], extra=extra))
        plotel_part = _block(starter, f"/PART/{PLOTEL_ID}")
        prop_ref = _col_i(plotel_part[2], 1, 10)
        self.assertNotEqual(prop_ref, PLOTEL_ID)
        self.assertEqual(len(_blocks(starter, f"/PROP/TYPE4/{prop_ref}")), 1)

    def test_element_referencing_an_undefined_node_is_dropped(self):
        result, starter = _convert(_plotel_deck([_i8(500, 1, 3),
                                                 _i8(501, 1, 999)]))
        rows = _elem_rows(starter, f"/SPRING/{PLOTEL_ID}")
        self.assertEqual([_col_i(r, 1, 10) for r in rows], [500])
        self.assertTrue(any("no *NODE record" in w for w in result.warnings),
                        result.warnings)

    def test_spring_id_clash_with_a_discrete_element_is_warned(self):
        """/SPRING is ONE starter id namespace across every spring emitter, and
        LS-DYNA does not force a PLOTEL EID to differ from a discrete one."""
        extra = ("*PART\nspr\n" + _row10(3, 3, 3) + "\n"
                 "*SECTION_DISCRETE\n" + _row10(3) + "\n" + _row10(0.0, 0.0) + "\n"
                 "*MAT_SPRING_ELASTIC\n" + _row10(3, 100.0) + "\n"
                 "*ELEMENT_DISCRETE\n" + _i8(500, 3, 1, 2) + "\n")
        result, _ = _convert(_plotel_deck([_i8(500, 1, 3)], extra=extra))
        hit = [w for w in result.warnings if "ERROR 79" in w and "PLOTEL" in w]
        self.assertEqual(len(hit), 1, result.warnings)

    def test_no_plotel_no_cards(self):
        _, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n" + END)
        self.assertNotIn("PLOTEL", starter)


# ─────────────────────────────────────────────────────────────────────────────
# F. *INCLUDE_TRANSFORM id offsets
# ─────────────────────────────────────────────────────────────────────────────

class ElementVariantOffsetTests(unittest.TestCase):
    """The offset table has to know the new spellings too, or an included
    element block keeps its original node ids while the nodes are renumbered."""

    def _include(self, child_body: str, offsets):
        tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write("*KEYWORD\n" + NODES + child_body + "*END\n")
        main = os.path.join(tmp.name, "main.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     + _row10(*offsets) + "\n\n\n\n*END\n")
        state = ConversionState()
        for block in parse_k_file(main):
            dispatch(block, state)
        tmp.cleanup()
        return state

    #: *INCLUDE_TRANSFORM card 2 = IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF ...
    OFFSETS = (100, 200, 400, 0, 300)

    def test_shell_thickness_block_is_offset_without_touching_the_thicknesses(self):
        """The optional card holds no ids: offsetting it, or reslicing its F16
        floats at w=8, would corrupt the thicknesses."""
        state = self._include(
            "*ELEMENT_SHELL_THICKNESS_BETA\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16(2.0, 2.0, 2.0, 2.0, 30.0)
            + "\n", self.OFFSETS)
        e = state.shell_elems[0]
        self.assertEqual(e.eid, 201)             # IDEOFF
        self.assertEqual(e.pid, 401)             # IDPOFF
        self.assertEqual(e.nodes, [101, 102, 103, 104])   # IDNOFF
        self.assertEqual(e.beta, 30.0)
        self.assertEqual(e.thick_nodes[:4], [2.0, 2.0, 2.0, 2.0])

    def test_beam_orientation_block_is_offset_without_touching_the_vector(self):
        state = self._include(
            "*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 7, 8) + "\n" + _f10(0.0, 1.0, 0.0) + "\n",
            self.OFFSETS)
        e = state.beam_elems[0]
        self.assertEqual((e.eid, e.pid, e.n1, e.n2), (211, 402, 107, 108))
        self.assertEqual((e.vx, e.vy, e.vz), (0.0, 1.0, 0.0))

    def test_plotel_block_is_offset(self):
        state = self._include("*ELEMENT_PLOTEL\n" + _i8(500, 1, 3) + "\n",
                              self.OFFSETS)
        p = state.plotel_elems[0]
        self.assertEqual((p.eid, p.n1, p.n2), (700, 101, 103))

    def test_unknown_suffix_is_offset_rather_than_warned_about(self):
        """An unmapped keyword only warns; for elements that leaves dangling
        connectivity, which is worse than the warning."""
        state = self._include(
            "*ELEMENT_SHELL_SHL4_TO_SHL8\n" + _i8(1, 1, 1, 2, 3, 4) + "\n",
            self.OFFSETS)
        self.assertEqual(state.shell_elems[0].nodes, [101, 102, 103, 104])


# ─────────────────────────────────────────────────────────────────────────────
# G. Regression: no flag, no change on a deck without the new cards
# ─────────────────────────────────────────────────────────────────────────────

class ElementVariantRegressionTests(unittest.TestCase):

    def test_plain_shell_row_is_unchanged(self):
        """A plain *ELEMENT_SHELL carries no thickness and no angle, so the row
        keeps its historical 60-character shape: eid + 4 nodes + the blank
        field. dyna2rad writes an explicit Thick=0 and PHI_Z=0 on EVERY shell;
        emitting them would change every existing k2rad deck for no gain (0 is
        the reader default for both)."""
        _, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + _i8(2, 1, 2, 5, 6) + "\n" + END)
        quad = _elem_rows(starter, "/SHELL/1")[0]
        tri = _elem_rows(starter, "/SH3N/1")[0]
        self.assertEqual(quad, _row10(1, 1, 2, 3, 4, 0))
        self.assertEqual(tri, _row10(2, 2, 5, 6, 0))

    def test_plain_deck_emits_no_variant_cards(self):
        _, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n" + END)
        for token in ("PLOTEL", "/PROP/TYPE4", "/SPRING"):
            self.assertNotIn(token, starter, token)

    def test_goldens_are_unchanged(self):
        """No checked-in fixture uses an *ELEMENT_ variant, so all five golden
        decks must still match byte-for-byte (asserted again here, per repo
        policy for a no-flag feature)."""
        from tests import test_golden
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(test_golden)
        result = unittest.TextTestRunner(
            stream=open(os.devnull, "w"), verbosity=0).run(suite)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])


if __name__ == "__main__":
    unittest.main()
