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

    def test_zero_cells_take_the_section_thickness_per_value(self):
        """LS-DYNA's own rule, and it is per VALUE: Vol I R17 *ELEMENT_SHELL
        Card 2 defaults THIC1..THIC4 to ``0.``, and Remark 1 reads "Default
        values in place of zero shell thicknesses are taken from the
        cross-section property definition of the PID". With *SECTION_SHELL
        T=1.0, THIC1=2.0 and three empty cells is (2+1+1+1)/4 = 1.25.

        Both alternatives are wrong and wrong differently: dyna2rad divides the
        written values by the node count (convertelements.cxx:290-301) -> 0.5,
        and averaging only the non-empty cells -> 2.0."""
        _, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_THICKNESS",
            [_i8(1, 1, 1, 2, 3, 4), _f16(2.0)]))
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 81, 100), 1.25)

    def test_a_blank_cell_and_an_explicit_zero_are_the_same_input(self):
        """Card 2's Default row is ``0.`` for THIC1..THIC4, so LS-DYNA cannot
        and does not distinguish the two spellings — two elements written the
        two ways must convert to the SAME thickness. (They used to differ by 4x
        here: 4.0 for the blanks, 1.0 for the zeros.)"""
        _, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL_THICKNESS\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16(4.0) + "\n"
            + _i8(2, 1, 2, 5, 6, 3) + "\n" + _f16(4.0, 0.0, 0.0, 0.0) + "\n"
            + END)
        rows = _elem_rows(starter, "/SHELL/1")
        self.assertEqual(_col_f(rows[0], 81, 100), _col_f(rows[1], 81, 100))
        self.assertEqual(_col_f(rows[0], 81, 100), 1.75)   # (4+1+1+1)/4

    def test_a_sectionless_part_averages_the_written_cells(self):
        """With no *SECTION_SHELL there is no thickness to substitute (k2rad's
        auto-section is 0.0), so the non-zero cells are averaged on their own —
        the /PROP could not have supplied anything better."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART\nplate\n" + _row10(1, 1, 1) + "\n"
                + "*MAT_ELASTIC\n" + _row10(1, 7.85e-9, 210000.0, 0.3) + "\n"
                + "*ELEMENT_SHELL_THICKNESS\n"
                + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16(2.0, 4.0) + "\n" + END)
        _, starter = _convert(deck)
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 81, 100), 3.0)

    def test_collapsed_quad_uses_the_surviving_corners_thickness_cells(self):
        """The THIC cells are keyed on the CARD SLOT, and a collapse may sit in
        ANY slot: ``n1 n1 n2 n3`` survives with slots 0, 2, 3. Averaging the
        first three cells would read a thickness belonging to a corner that is
        not in the element — here (1+1+1)/3 = 1.0 instead of (1+1+10)/3 = 4.0, a
        4x under-thickness (4x under-mass, 64x under-bending-stiffness).

        Both spellings of the same triangle must give the same answer."""
        _, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART
            + "*ELEMENT_SHELL_THICKNESS\n"
            # trailing collapse: corners in slots 0, 1, 2
            + _i8(1, 1, 1, 2, 3, 3) + "\n" + _f16(1.0, 1.0, 10.0, 10.0) + "\n"
            # leading collapse: the SAME three thicknesses in slots 0, 2, 3
            + _i8(2, 1, 2, 2, 5, 6) + "\n" + _f16(1.0, 1.0, 1.0, 10.0) + "\n"
            + END)
        rows = _elem_rows(starter, "/SH3N/1")
        self.assertAlmostEqual(_col_f(rows[0], 81, 100), 4.0)
        self.assertAlmostEqual(_col_f(rows[1], 81, 100), 4.0)

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

    def test_a_free_format_dof_card_is_counted_too(self):
        """A comma-delimited card is legal LS-DYNA. Slicing it at column 16
        would drop the scalar nodes AND the warning that says they were
        dropped, so the user is never told."""
        result, starter = _convert(_shell_deck(
            "*ELEMENT_SHELL_DOF",
            [_i8(1, 1, 1, 2, 3, 4), ",,11,12,13,14"]))
        self.assertEqual(len(_elem_rows(starter, "/SHELL/1")), 1)
        self.assertTrue(any("scalar-node references" in w
                            for w in result.warnings), result.warnings)

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


class ProvisionalElementScreenTests(unittest.TestCase):
    """The content test that keeps an unmodelled option's mesh is NECESSARY but
    not SUFFICIENT — an all-integer option card imitates connectivity exactly.
    Emitting one is worse than the old silent skip: the starter rejects the
    whole deck with ERROR 78 (UNDEFINED NODE NUMBER) and ERROR 222 (N1=N2),
    while the converter reports the phantom as a preserved element.

    ``_screen_provisional_elements`` supplies the sufficiency half by checking
    the candidates against the node table after parsing.
    """

    def test_integer_beam_thickness_card_does_not_become_a_beam(self):
        """*ELEMENT_BEAM_THICKNESS with a 10x10 square section writes
        ``10 10 10 10`` — four positive integers. Read as connectivity that is
        beam 10 on nodes 10-10: a node that does not exist AND N1 == N2."""
        deck = ("*KEYWORD\n" + NODES + SHELL_PART + BEAM_PART
                + "*ELEMENT_BEAM_THICKNESS\n"
                + _i8(11, 2, 7, 8) + "\n" + _i8(10, 10, 10, 10) + "\n"
                + _i8(12, 2, 8, 7) + "\n" + _i8(10, 10, 10, 10) + "\n"
                + END)
        result, starter = _convert(deck)
        rows = _elem_rows(starter, "/BEAM/2")
        self.assertEqual([_col_i(r, 1, 10) for r in rows], [11, 12])
        hit = [w for w in result.warnings if "_THICKNESS" in w
               and "not implemented" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("2 element(s) were kept", hit[0])
        self.assertIn("node ids the deck does not define", hit[0])

    def test_integer_ply_card_does_not_become_a_shell(self):
        """An *ELEMENT_SHELL_COMPOSITE ply card whose leading MID is not an EID
        already seen in the block slips past the unique-EID rule; its "nodes"
        are a thickness, an angle and a ply id."""
        deck = ("*KEYWORD\n" + NODES + SHELL_PART
                + "*ELEMENT_SHELL_COMPOSITE\n"
                + _i8(1, 1, 1, 2, 3, 4) + "\n"
                + _i8(1001, 1, 45, 1, 1002, 1, 45, 1) + "\n"
                + END)
        result, starter = _convert(deck)
        rows = _elem_rows(starter, "/SHELL/1")
        self.assertEqual([_col_i(r, 1, 10) for r in rows], [1])
        self.assertTrue(any("1 element(s) were kept" in w
                            for w in result.warnings), result.warnings)

    def test_every_node_of_a_kept_element_exists(self):
        """The invariant the screen enforces, stated directly: no element that
        survives an unmodelled suffix may name a node the deck does not have."""
        deck = ("*KEYWORD\n" + NODES + SHELL_PART
                + "*ELEMENT_SHELL_MADE_UP\n"
                + _i8(1, 1, 1, 2, 3, 4) + "\n"
                + _i8(7, 7, 77, 78, 79, 80) + "\n"
                + END)
        _, starter = _convert(deck)
        nids = {_col_i(ln, 1, 10) for ln in _block(starter, "/NODE")[1:]
                if ln.strip() and not ln.startswith("#")}
        for row in _elem_rows(starter, "/SHELL/1"):
            for a in (11, 21, 31, 41):
                self.assertIn(_col_i(row, a, a + 9), nids)

    def test_a_real_element_on_defined_nodes_survives(self):
        """The screen must not be a blanket drop — the whole point of the
        fallback is that the MESH of an unmodelled option is preserved."""
        deck = ("*KEYWORD\n" + NODES + SHELL_PART
                + "*ELEMENT_SHELL_SHL4_TO_SHL8\n"
                + _i8(1, 1, 1, 2, 3, 4) + "\n"
                + _i8(2, 1, 2, 5, 6, 3) + "\n"
                + END)
        result, starter = _convert(deck)
        self.assertEqual(len(_elem_rows(starter, "/SHELL/1")), 2)
        self.assertTrue(any("2 element(s) were kept" in w
                            for w in result.warnings), result.warnings)
        self.assertNotIn("node ids the deck does not define",
                         " ".join(result.warnings))

    def test_screen_leaves_the_modelled_suffixes_alone(self):
        """Only the unknown-suffix path marks elements provisional; a
        *ELEMENT_SHELL_THICKNESS element on a missing node is NOT this pass's
        business (it is ordinary bad input, reported by the starter)."""
        state = _dispatch(
            "*KEYWORD\n*ELEMENT_SHELL_THICKNESS\n"
            + _i8(1, 1, 900, 901, 902, 903) + "\n" + _f16(1.0) + "\n*END\n")
        self.assertEqual(len(state.shell_elems), 1)
        self.assertFalse(state.shell_elems[0].provisional)
        self.assertEqual(state.provisional_elem_blocks, [])


# ─────────────────────────────────────────────────────────────────────────────
# C2. BETA on an orthotropic part — the solver reads it only off the /PROP
# ─────────────────────────────────────────────────────────────────────────────

#: *MAT_ORTHOTROPIC_ELASTIC with EA/EB = 100. AOPT=0 puts material axis 1 along
#: the element's N1->N2 edge, so a BETA of 90 deg must swap Q11 for Q22.
MAT002 = ("*MAT_ORTHOTROPIC_ELASTIC\n"
          + _row10(9, 1.55e-9, 100000.0, 1000.0, 1000.0, 0.02, 0.02, 0.4) + "\n"
          + _row10(5000.0, 3000.0, 4000.0, 0.0) + "\n"
          + _row10(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0) + "\n"
          + _row10(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")

ORTHO_PART = ("*PART\nply\n" + _row10(1, 1, 9) + "\n"
              "*SECTION_SHELL\n" + _row10(1, 2, "", "", "", "", 1) + "\n"
              + _row10(1.0, 1.0, 1.0, 1.0) + "\n" + MAT002)


class ShellBetaOnOrthotropicPartTests(unittest.TestCase):
    """`*ELEMENT_SHELL_BETA` reaches an IGTYP 9/10/11/16 part only via the /PROP.

    k2rad writes the angle into the /SHELL `Phi` column and the starter reads it
    back correctly (90 deg echoes as 1.570796326795 rad under /IOFLAG IPRI=5) —
    and then discards it. `starter/source/elements/shell/coque/corthini.F` builds
    the layer angle from the PROPERTY alone for IGTYP 1 (:110, an early RETURN),
    9 (:202), 10/11 (:206-217) and 16 (:429-435); only IGTYP 17/51/52 do
    `PHI1(J,I) = ANGLE(I) + ...`.

    Measured on this material pulled along global X: per-element BETA=90 on the
    /PROP/TYPE11 part gave 103094.25 MPa, byte-identical to its BETA=0 twin
    (ratio 1.000000) where Q22 = 25789.81 was required. The same 90 deg reaching
    the TYPE11 layer Phi column gives 25773.52 (dev -0.063%).
    """

    def _layer_phis(self, starter):
        """The Phi column of every layer row of the part's /PROP/TYPE11."""
        blk = _block(starter, "/PROP/TYPE11/")
        head = next(i for i, ln in enumerate(blk)
                    if ln.startswith("#") and "Phi" in ln and "Thick" in ln
                    and "F_weight" in ln)
        return [_col_f(ln, 1, 20) for ln in blk[head + 1:]
                if not ln.startswith("#")]

    def test_uniform_beta_is_folded_into_the_property_layers(self):
        _, starter = _convert(
            "*KEYWORD\n" + NODES + ORTHO_PART
            + "*ELEMENT_SHELL_BETA\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16("", "", "", "", 90.0) + "\n"
            + _i8(2, 1, 2, 5, 6, 3) + "\n" + _f16("", "", "", "", 90.0) + "\n"
            + END)
        self.assertEqual(self._layer_phis(starter), [90.0, 90.0])

    def test_the_element_column_is_cleared_once_it_is_folded(self):
        """The angle must be stated ONCE. Leaving it in the /SHELL column as
        well reads as a second rotation to anyone diffing the deck, and the
        solver ignores it there anyway."""
        _, starter = _convert(
            "*KEYWORD\n" + NODES + ORTHO_PART
            + "*ELEMENT_SHELL_BETA\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16("", "", "", "", 90.0) + "\n"
            + END)
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(len(row), 60)          # plain 60-char shape

    def test_the_fold_is_reported(self):
        result, _ = _convert(
            "*KEYWORD\n" + NODES + ORTHO_PART
            + "*ELEMENT_SHELL_BETA\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16("", "", "", "", 90.0) + "\n"
            + END)
        hit = [w for w in result.warnings if "FOLDED" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("corthini.F", hit[0])

    def test_per_element_variation_is_warned_about_not_silently_dropped(self):
        """One /PROP serves the whole part, so differing angles cannot be
        represented at all — the fibres would run along the property direction
        for every element with nothing saying so."""
        result, starter = _convert(
            "*KEYWORD\n" + NODES + ORTHO_PART
            + "*ELEMENT_SHELL_BETA\n"
            + _i8(1, 1, 1, 2, 3, 4) + "\n" + _f16("", "", "", "", 90.0) + "\n"
            + _i8(2, 1, 2, 5, 6, 3) + "\n" + _f16("", "", "", "", 45.0) + "\n"
            + END)
        hit = [w for w in result.warnings if "DIFFERENT angles" in w]
        self.assertEqual(len(hit), 1, result.warnings)
        self.assertIn("45, 90", hit[0])
        self.assertEqual(self._layer_phis(starter), [0.0, 0.0])

    def test_part_composite_keeps_its_element_angle(self):
        """/PROP/TYPE51 is one of the three classes where corthini DOES add
        ANGLE(I), and it was measured working (ratio 0.250084 for a 90 deg
        rotation). The fold must leave that path completely alone."""
        deck = ("*KEYWORD\n" + NODES
                + "*PART_COMPOSITE\nlayup\n" + _row10(1) + "\n"
                + _row10(9, 0.5, 0.0, 0, 9, 0.5, 0.0, 0) + "\n"
                + MAT002
                + "*ELEMENT_SHELL_BETA\n"
                + _i8(1, 1, 1, 2, 3, 4) + "\n"
                + _f16("", "", "", "", 90.0) + "\n" + END)
        result, starter = _convert(deck)
        row = _elem_rows(starter, "/SHELL/1")[0]
        self.assertEqual(_col_f(row, 61, 80), 90.0)
        self.assertEqual([w for w in result.warnings if "FOLDED" in w], [])

    def test_isotropic_part_is_told_the_angle_does_nothing(self):
        """IGTYP 1 returns from corthini.F:110 before any material angle is
        read, and an isotropic material has no direction to rotate anyway."""
        result, _ = _convert(_shell_deck(
            "*ELEMENT_SHELL_BETA",
            [_i8(1, 1, 1, 2, 3, 4), _f16("", "", "", "", 30.0)]))
        self.assertTrue(any("ISOTROPIC /PROP/SHELL" in w
                            for w in result.warnings), result.warnings)


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
        """No *NODE for N1 -> no third node can be placed. The beam survives and
        the loss is reported (the warning comes from the writer prepass, so the
        deck has to be CONVERTED, not merely dispatched)."""
        result, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL_PART + BEAM_PART
            + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
            + "*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 999, 998) + "\n" + _f10(0.0, 1.0, 0.0) + "\n" + END)
        self.assertEqual(len(_elem_rows(starter, "/BEAM/2")), 1)
        self.assertTrue(any("no *NODE record" in w for w in result.warnings),
                        result.warnings)

    def test_a_fixed_format_local_column_is_not_read_as_n3(self):
        """*ELEMENT_BEAM card 1 is 10 x I8 — EID PID N1 N2 N3 RT1 RR1 RT2 RR2
        LOCAL — and the manual says N3 "should be left undefined" under
        _ORIENTATION. A whitespace split of such a card returns five tokens and
        reads the LOCAL flag as the orientation node: a silently wrong local
        frame, or an id that does not exist."""
        line = _i8(201, 2, 7, 8) + " " * 40 + f"{2:>8}"
        state = _dispatch("*KEYWORD\n*ELEMENT_BEAM\n" + line + "\n*END\n")
        e = state.beam_elems[0]
        self.assertEqual((e.eid, e.pid, e.n1, e.n2, e.n3), (201, 2, 7, 8, 0))

    def test_a_free_format_card_still_reads_n3(self):
        """The positional reading must not swallow genuine free format, where
        the fifth token really is N3."""
        for line in ("201,2,7,8,6", "201 2 7 8 6"):
            with self.subTest(line=line):
                state = _dispatch(
                    "*KEYWORD\n*ELEMENT_BEAM\n" + line + "\n*END\n")
                self.assertEqual(state.beam_elems[0].n3, 6)

    def test_a_misaligned_fixed_card_still_parses(self):
        """A card whose columns do not line up exactly must keep the whitespace
        reading rather than losing its leading fields."""
        state = _dispatch(
            "*KEYWORD\n*ELEMENT_BEAM\n" + "       1        2       7       8"
            + "\n*END\n")
        e = state.beam_elems[0]
        self.assertEqual((e.eid, e.pid, e.n1, e.n2), (1, 2, 7, 8))

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

    def test_the_time_step_inputs_reach_the_card(self):
        """What makes the spring non-governing is the VALUES on the emitted
        card: r1len3.F:139 computes DT = XM/MAX(EM15, SQRT(XC^2+XM*XK)+XC), so
        with MASS just above the 1e-15 clamp and K = C = 0 the denominator
        floors at EM15 instead of dividing by zero. Measured: the starter's
        element table prints 0.55 s for these springs against 1.3e-6 s for the
        beams of the same deck."""
        _, starter = _convert(_plotel_deck([_i8(500, 1, 3)]))
        cards = self._prop_cards(starter)
        mass = _col_f(cards[0], 1, 20)
        k, c = _col_f(cards[1], 1, 20), _col_f(cards[1], 21, 40)
        self.assertGreater(mass, 1e-15)
        self.assertEqual((k, c), (0.0, 0.0))
        self.assertGreater(mass / max(1e-15, (c * c + mass * k) ** 0.5 + c), 1.0)

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

    def test_spring_id_clash_with_a_spotweld_beam_is_warned(self):
        """*ELEMENT_DISCRETE is not the only other /SPRING emitter: a MAT_100
        beam part becomes /SPRING rows under the original *ELEMENT_BEAM eids
        (_make_spotweld_beam_connectors). LS-DYNA keeps PLOTEL and BEAM ids in
        separate namespaces, so this is legal input that Radioss rejects."""
        extra = ("*PART\nweld\n" + _row10(4, 4, 4) + "\n"
                 "*SECTION_BEAM\n" + _row10(4, 9) + "\n"
                 + _row10(1.0, 1.0, 1.0) + "\n"
                 "*MAT_SPOTWELD\n"
                 + _row10(4, 7.85e-9, 210000.0, 0.3, 400.0, 1000.0) + "\n"
                 + _row10(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                 "*ELEMENT_BEAM\n" + _i8(500, 4, 7, 8) + "\n")
        result, _ = _convert(_plotel_deck([_i8(500, 1, 3)], extra=extra))
        hit = [w for w in result.warnings
               if "ERROR 79" in w and "*MAT_SPOTWELD" in w]
        self.assertEqual(len(hit), 1, result.warnings)

    def test_a_plotel_only_node_still_gets_the_implicit_free_node_guard(self):
        """The guard exists because a stiffness-free node is a zero row in the
        implicit tangent. A PLOTEL /PROP/TYPE4 is K=0/C=0 by construction and
        r1len3.F:81-105 leaves STI at zero unless XK or XC is non-zero, so
        drawing a line through a node adds NO stiffness — counting it as an
        attachment would switch the guard off for exactly the node it is for.
        (Same reasoning as the beam-orientation nodes eight lines below it.)"""
        extra_nodes = ("*NODE\n"
                       + f"{91:>8}{5.0:>16}{5.0:>16}{9.0:>16}\n"
                       + f"{92:>8}{6.0:>16}{5.0:>16}{9.0:>16}\n")
        impl = "*CONTROL_IMPLICIT_GENERAL\n" + _row10(1, 1.0e-3) + "\n"
        deck = ("*KEYWORD\n" + NODES + extra_nodes + SHELL_PART + impl
                + "*ELEMENT_SHELL\n" + _i8(1, 1, 1, 2, 3, 4) + "\n"
                + "*ELEMENT_PLOTEL\n" + _i8(5002, 91, 92) + "\n" + END)
        result, starter = _convert(deck)
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if b[1] == "free_reference_nodes"]
        self.assertEqual(len(grp), 1, starter)
        listed = {int(t) for ln in grp[0][2:] for t in ln.split()}
        self.assertTrue({91, 92} <= listed, grp)
        self.assertTrue(any("free node(s) attached to no element" in w
                            for w in result.warnings), result.warnings)

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
        """A pure id offset (no TRANID) must leave the geometry alone."""
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


class BeamOrientationTransformTests(unittest.TestCase):
    """A rotating TRANID has to reach the ORIENTATION vector.

    VX/VY/VZ is literal geometry: the nodes move with the include, so an
    untouched vector leaves the beam's local Y-Z frame behind and Iyy/Izz act on
    the wrong axes. At 90 deg it can even end up collinear with the rotated beam
    axis — a degenerate frame (starter WARNING 3051, N3 := N2). Nothing else in
    the deck records the mistake.
    """

    def _rotated(self, child_body: str, angle: float, keep_dir=True):
        tmp = tempfile.TemporaryDirectory()
        child = ("*KEYWORD\n*NODE\n"
                 + f"{1:>8}{1.0:>16}{0.0:>16}{0.0:>16}\n"
                 + f"{2:>8}{11.0:>16}{0.0:>16}{0.0:>16}\n"
                 + "*PART\nbar\n" + _row10(2, 2, 1) + "\n"
                 + "*SECTION_BEAM\n" + _row10(2, 2) + "\n"
                 + _row10(100.0, 833.0, 833.0, 1400.0) + "\n"
                 + "*MAT_ELASTIC\n"
                 + _row10(1, 7.85e-9, 210000.0, 0.3) + "\n"
                 + child_body + "*END\n")
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write(child)
        main = os.path.join(tmp.name, "main.k")
        with open(main, "w") as fh:
            # *INCLUDE_TRANSFORM cards 2-4 blank, card 5 = TRANID.
            fh.write("*KEYWORD\n"
                     + "*DEFINE_TRANSFORMATION\n" + _row10(7) + "\n"
                     + f"{'ROTATE':<10}"
                     + _row10(0.0, 0.0, 1.0, 0.0, 0.0, 0.0, angle) + "\n"
                     + "*INCLUDE_TRANSFORM\nchild.k\n\n\n\n"
                     + _row10(7) + "\n" + END)
        state = ConversionState()
        for block in parse_k_file(main):
            dispatch(block, state)
        tmp.cleanup()
        return state

    def test_the_vector_is_rotated_with_its_include(self):
        """30 deg about +Z: nodes (1,0,0)->(0.8660254,0.5,0), and V=(0,1,0) must
        become (-0.5, 0.8660254, 0) so the third node lands at
        (0.366025, 1.366025, 0) — not at pos(N1)+(0,1,0)."""
        state = self._rotated(
            "*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 1, 2) + "\n" + _f10(0.0, 1.0, 0.0) + "\n", 30.0)
        e = state.beam_elems[0]
        self.assertAlmostEqual(e.vx, -0.5, places=6)
        self.assertAlmostEqual(e.vy, 3 ** 0.5 / 2, places=6)
        self.assertAlmostEqual(e.vz, 0.0, places=9)

    def test_the_synthesized_node_lands_on_the_rotated_point(self):
        from k2rad.writer.mesh import _synthesize_beam_orientation_nodes
        state = self._rotated(
            "*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 1, 2) + "\n" + _f10(0.0, 1.0, 0.0) + "\n", 30.0)
        _synthesize_beam_orientation_nodes(state)
        n3 = state.nodes[state.beam_elems[0].n3]
        self.assertAlmostEqual(n3.x, 3 ** 0.5 / 2 - 0.5, places=6)
        self.assertAlmostEqual(n3.y, 0.5 + 3 ** 0.5 / 2, places=6)

    def test_a_pure_translation_leaves_the_vector_alone(self):
        """A direction has no origin — only the LINEAR part may be applied."""
        state = self._rotated(
            "*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 1, 2) + "\n" + _f10(0.0, 1.0, 0.0) + "\n", 0.0)
        e = state.beam_elems[0]
        self.assertEqual((e.vx, e.vy, e.vz), (0.0, 1.0, 0.0))

    def test_the_offset_card_does_not_shift_the_vector_card(self):
        """Under _OFFSET_ORIENTATION the vector is card 8, not card 7: rotating
        the wrong card would scramble the end offsets and leave V untouched."""
        state = self._rotated(
            "*ELEMENT_BEAM_OFFSET_ORIENTATION\n"
            + _i8(11, 2, 1, 2) + "\n"
            + _f10(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _f10(0.0, 1.0, 0.0) + "\n", 90.0)
        e = state.beam_elems[0]
        self.assertAlmostEqual(e.vx, -1.0, places=9)
        self.assertAlmostEqual(e.vy, 0.0, places=9)

    def test_an_unmodelled_suffix_is_warned_about_instead(self):
        """The vector card's POSITION is unknown under an option k2rad does not
        model, so it cannot be rotated — that must be said, not skipped."""
        from k2rad.parser import PARSER_WARNINGS
        PARSER_WARNINGS.clear()
        self._rotated(
            "*ELEMENT_BEAM_WARPAGE_ORIENTATION\n"
            + _i8(11, 2, 1, 2) + "\n" + _f10(0.0, 1.0, 0.0) + "\n", 30.0)
        hits = [w for w in PARSER_WARNINGS
                if "ELEMENT_BEAM_WARPAGE_ORIENTATION" in w
                and "NOT transformed" in w]
        self.assertEqual(len(hits), 1, PARSER_WARNINGS)

    def test_a_modelled_suffix_is_not_warned_about(self):
        """The spellings that ARE rotated must not also claim they were not."""
        from k2rad.parser import PARSER_WARNINGS
        PARSER_WARNINGS.clear()
        self._rotated(
            "*ELEMENT_BEAM_ORIENTATION\n"
            + _i8(11, 2, 1, 2) + "\n" + _f10(0.0, 1.0, 0.0) + "\n", 30.0)
        self.assertEqual([w for w in PARSER_WARNINGS
                          if "NOT transformed" in w], [])


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

    # (The byte-for-byte golden check lives in tests/test_golden.py, which the
    # runner collects on its own. Re-running that whole module from inside this
    # one doubled the work and reported nothing test_golden does not.)


if __name__ == "__main__":
    unittest.main()
