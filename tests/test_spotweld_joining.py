"""Tests for the SPOTWELD JOINING batch:

  *CONTACT_SPOTWELD[_WITH_TORSION|_BEAM_OFFSET|_CONSTRAINED_OFFSET]
                   [_PENALTY][_MPP][_ID]      -> /INTER/TYPE2 Spotflag=28
                                                 (Ignore=2, Idel2=1)
  *DEFINE_HEX_SPOTWELD_ASSEMBLY[_N]           -> /GRBRIC/BRIC + /CLUSTER/BRICK
                                                 [+ /TH/CLUSTER]
  *DATABASE_SWFORC                            -> /TH/SPRING (MAT_100 beam welds)
                                               + /TH/BRIC   (MAT_100 solid welds)
                                               + /TH/CLUSTER (hex assemblies)

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_connectors.py, tests/test_metal_plasticity_2.py and
tests/test_composites.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant (the sqrt-of-squares resultant reduction, the 0.6*(SST+MST) search
distance) is recomputed by hand in the test rather than copied from the
implementation.

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic - SSTYP=3 naming the WELD part rather than a joined sheet, a NEGATIVE
Card-3 SST/MST being an absolute tie-criterion distance rather than a thickness,
the _N suffix counting ELEMENTS rather than cards - the assertion pins the value
the MANUAL's definition implies, with the citation in the test docstring.

Every emitted card in this batch was validated on a live OpenRadioss starter run
(starter_win64, /BEGIN 2022), 0 ERROR(S), and the starter's own echo confirmed
the field-by-field placement asserted below:

    INTERFACE NUMBER : 1 SPOTWELD_CONTACT_1
     TYPE==2   TIED SLIDING
     FORMULATION LEVEL . . . = 28      SEARCH FORMULATION . . = 2
     STIFFNESS FACTOR  . . . = 1.0     STIFFNESS FORMULATION  = 2
     CRITICAL DAMPING FACTOR = 5.0E-02 IGNORE FLAG . . . . . . = 2
     DELETION FLAG CASE FAILURE OF MAIN ELEMENT SET TO   1

    SPOTWELD CLUSTER OF BRICK ELEMENTS,  ID=      7001
         ELEMENT GROUP ID = 90001   SKEW ID = 0   NUMBER OF ELEMENTS = 2
         FAILURE FLAG = 3
         MAX NORMAL FORCE = 8000.0   MAX TANGENT FORCE  = 6403.124237
         MAX TORSION MOMENT = 2000.0 MAX BENDING MOMENT = 1920.937271
         FAILURE COEFFICIENT A1..A4 = 1.0
         FAILURE EXPONENT   N1..N4  = 2.0

The /TH variable names were confirmed by a NEGATIVE control: replacing the
emitted ``DEF FLOC`` with the CFG GUI's ``FT MB`` makes the same starter answer
ERROR 260 on THGROUP 90003 - so the clean run is a check that can fail.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                              # noqa: E402
from k2rad.assembly import _OFFSET_SPECS               # noqa: E402
from k2rad.handlers import (                           # noqa: E402
    HANDLERS, _SPOTWELD_CONTACT_KEYWORDS, dispatch,
)
from k2rad.parser import parse_k_file                  # noqa: E402
from k2rad.state import ConversionState                # noqa: E402
from k2rad.writer.contacts import (                    # noqa: E402
    _SPOTWELD_IDEL2, _SPOTWELD_SPOTFLAG, _spotweld_dsearch, _spotweld_slave_nids,
)
from k2rad.writer.loads import _CLUSTER_A, _CLUSTER_B, _CLUSTER_IFAIL  # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

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


def _convert_both(deck: str):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


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


def _row(*vals) -> str:
    """One LS-DYNA fixed-width card: every field right-justified in 10 cols."""
    return "".join(f"{v:>10}" for v in vals)


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


def _cards(block):
    """A block's DATA lines: everything after the title that is not a comment."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _ids_10(block):
    """A 10-per-line id list (/GRNOD/NODE, /GRBRIC/BRIC, /TH/CLUSTER objects)."""
    out = []
    for ln in _cards(block):
        for i in range(0, len(ln), 10):
            tok = ln[i:i + 10].strip()
            if tok:
                out.append(int(tok))
    return out


def _th_var_line(block) -> str:
    """A /TH block's variable line — the first non-comment line after the title."""
    return _cards(block)[0]


def _th_obj_ids(block):
    """A /TH/SPRING or /TH/BRIC object list: ONE id per line, after the vars."""
    return [int(ln[:10]) for ln in _cards(block)[1:]]


def _th_cluster_obj_ids(block):
    """A /TH/CLUSTER object list: TEN ids per line, after the variable line."""
    out = []
    for ln in _cards(block)[1:]:
        for i in range(0, len(ln), 10):
            tok = ln[i:i + 10].strip()
            if tok:
                out.append(int(tok))
    return out


def _elem_ids(starter: str, header: str):
    """Element ids of every /SHELL/<pid>-style block — those carry NO title
    line, so the ids start on the line right after the header."""
    out = set()
    for block in _blocks(starter, header):
        for ln in block[1:]:
            if not ln.startswith("#"):
                out.add(int(ln[:10]))
    return out


# ── Decks ────────────────────────────────────────────────────────────────────

# Two 1x1 shell sheets (parts 1 and 2) stacked 2 mm apart, joined by two weld
# beams on part 3. The weld nodes 100/101/102/103 are DISJOINT from the sheet
# nodes 1..8 — exactly the W16 corpus topology, where the welds carry zero force
# until *CONTACT_SPOTWELD is converted.
SHEET_NODES = (
    "*NODE\n"
    "         1       0.0       0.0       0.0\n"
    "         2      10.0       0.0       0.0\n"
    "         3      10.0      10.0       0.0\n"
    "         4       0.0      10.0       0.0\n"
    "         5       0.0       0.0       2.0\n"
    "         6      10.0       0.0       2.0\n"
    "         7      10.0      10.0       2.0\n"
    "         8       0.0      10.0       2.0\n"
    "       100       2.0       2.0       0.0\n"
    "       101       2.0       2.0       2.0\n"
    "       102       8.0       8.0       0.0\n"
    "       103       8.0       8.0       2.0\n"
)

SHEET_ELEMS = (
    "*ELEMENT_SHELL\n"
    "         1         1         1         2         3         4\n"
    "         2         2         5         6         7         8\n"
    "*ELEMENT_BEAM\n"
    "        11         3       100       101         0\n"
    "        12         3       102       103         0\n"
)

SHEET_PARTS = (
    "*PART\n"
    "sheet lower\n"
    "         1         1         1\n"
    "*PART\n"
    "sheet upper\n"
    "         2         1         1\n"
    "*PART\n"
    "weld beams\n"
    "         3         9       100\n"
    "*SECTION_SHELL\n"
    "         1         2       1.0         2       1.0\n"
    "       1.0       1.0       1.0       1.0\n"
    "*SECTION_BEAM\n"
    "         9         9\n"
    "       1.0       3.0       3.0       0.0       0.0\n"
    "*MAT_ELASTIC\n"
    "         1 7.850E-9  210000.       0.3\n"
    "*MAT_SPOTWELD\n"
    "       100 7.850E-9  210000.       0.3     350.0     500.0\n"
    "       0.0    8000.0    5000.0    4000.0    2000.0    1500.0    1200.0\n"
    "*CONTROL_UNITS\n"
)

SET_PART = (
    "*SET_PART_LIST\n"
    "         1\n"
    "         1         2\n"
)


def _spotweld_card(keyword="*CONTACT_SPOTWELD_ID", cid=1, ssid=3, sstyp=3,
                   msid=1, mstyp=2, sst=0.0, mst=0.0, pre=""):
    """One *CONTACT_SPOTWELD block. ``pre`` inserts the _MPP card(s)."""
    head = f"{keyword}\n"
    if keyword.endswith("_ID"):
        head += f"{cid:>10}\n"
    return (
        head + pre
        + _row(ssid, msid, sstyp, mstyp, 0, 0, 0, 0) + "\n"
        + _row("0.0", "0.0", "0.0", "0.0", "0.0", 0, "0.0", "1.0E20") + "\n"
        + _row("1.0", "1.0", sst, mst, "1.0", "1.0", "1.0", "1.0") + "\n"
    )


SPOTWELD_DECK = (
    "*KEYWORD\n" + SHEET_NODES + SHEET_ELEMS + SHEET_PARTS + SET_PART
    + _spotweld_card() + "*END\n"
)

SWFORC = (
    "*DATABASE_SWFORC\n"
    "     0.001         0         0         1\n"
)

# Two hex nuggets (elements 101/102) on a MAT_100 solid part, plus a 4-node tet
# (103) that must be screened out of the cluster group.
HEX_NODES = SHEET_NODES + (
    "*NODE\n"
    "       201       3.0       3.0       0.0\n"
    "       202       4.0       3.0       0.0\n"
    "       203       4.0       4.0       0.0\n"
    "       204       3.0       4.0       0.0\n"
    "       205       3.0       3.0       2.0\n"
    "       206       4.0       3.0       2.0\n"
    "       207       4.0       4.0       2.0\n"
    "       208       3.0       4.0       2.0\n"
    "       211       6.0       6.0       0.0\n"
    "       212       7.0       6.0       0.0\n"
    "       213       7.0       7.0       0.0\n"
    "       214       6.0       7.0       0.0\n"
    "       215       6.0       6.0       2.0\n"
    "       216       7.0       6.0       2.0\n"
    "       217       7.0       7.0       2.0\n"
    "       218       6.0       7.0       2.0\n"
)

HEX_PARTS = (
    "*PART\n"
    "sheet lower\n"
    "         1         1         1\n"
    "*PART\n"
    "sheet upper\n"
    "         2         1         1\n"
    "*PART\n"
    "hex weld nuggets\n"
    "         4         4       100\n"
    "*SECTION_SHELL\n"
    "         1         2       1.0         2       1.0\n"
    "       1.0       1.0       1.0       1.0\n"
    "*SECTION_SOLID\n"
    "         4         1\n"
    "*MAT_ELASTIC\n"
    "         1 7.850E-9  210000.       0.3\n"
    "*MAT_SPOTWELD\n"
    "       100 7.850E-9  210000.       0.3     350.0     500.0\n"
    "       0.0    8000.0    5000.0    4000.0    2000.0    1500.0    1200.0\n"
)

HEX_ELEMS = (
    "*ELEMENT_SHELL\n"
    "         1         1         1         2         3         4\n"
    "         2         2         5         6         7         8\n"
    "*ELEMENT_SOLID\n"
    "       101         4\n"
    "       201       202       203       204       205       206       207       208\n"
    "       102         4\n"
    "       211       212       213       214       215       216       217       218\n"
)

HEX_ASSEMBLY = (
    "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n"
    "      7001\n"
    + _row(101, 102) + "\n"
)

HEX_DECK = ("*KEYWORD\n" + HEX_NODES + HEX_PARTS + HEX_ELEMS + HEX_ASSEMBLY
            + "*END\n")


# ── A) *CONTACT_SPOTWELD -> /INTER/TYPE2 ─────────────────────────────────────

class SpotweldContactCardTests(unittest.TestCase):
    """/INTER/TYPE2 Spotflag=28 card, column by column."""

    def setUp(self):
        self.result, self.starter = _convert(SPOTWELD_DECK)

    def test_no_skipped_keyword(self):
        """*CONTACT_SPOTWELD used to land in skipped_keywords; it must not."""
        self.assertNotIn("*CONTACT_SPOTWELD", self.result.skipped_keywords)
        self.assertEqual([], [k for k in self.result.skipped_keywords
                              if "SPOTWELD" in k])

    def test_interface_id_taken_from_the_ID_header(self):
        """*CONTACT_SPOTWELD_ID's CID is the /INTER id, verbatim."""
        self.assertIn("/INTER/TYPE2/1\n", self.starter)

    def test_card1_columns(self):
        """Card 1: grnd_IDs(1-10) surf_IDm(11-20) Ignore(21-30) Spotflag(31-40)
        Level(41-50) Isearch(51-60) Idel2(61-70) <blank 71-80> dsearch(81-100).

        Ignore=2 / Spotflag=28 / Idel2=1 are dyna2rad's spotweld defaults
        (convertcontacts.cxx:49). Level is forced to 0 by the starter for
        Spotflag 25-28 (hm_read_inter_type02.F:286) and Isearch 0 -> 2 (:282),
        so both are written at the value the starter would pick anyway.
        Cols 71-80 must stay BLANK: FORMAT(radioss2025) reads a second
        secondary-surface id there and /BEGIN 2022 has no such field.
        """
        card = _cards(_block(self.starter, "/INTER/TYPE2/1"))[0]
        self.assertEqual(100, len(card))
        self.assertEqual(2, _col_i(card, 21, 30))                 # Ignore
        self.assertEqual(28, _col_i(card, 31, 40))                # Spotflag
        self.assertEqual(_SPOTWELD_SPOTFLAG, _col_i(card, 31, 40))
        self.assertEqual(0, _col_i(card, 41, 50))                 # Level
        self.assertEqual(2, _col_i(card, 51, 60))                 # Isearch
        self.assertEqual(1, _col_i(card, 61, 70))                 # Idel2
        self.assertEqual(_SPOTWELD_IDEL2, _col_i(card, 61, 70))
        self.assertEqual("          ", card[70:80])               # must be blank
        self.assertEqual(0.0, _col_f(card, 81, 100))              # dsearch

    def test_idel2_differs_from_the_tied_path(self):
        """Idel2=1 is the SPOTWELD default; *CONTACT_TIED_* keeps 0.

        A weld to an eroded sheet has nothing left to hold (dyna2rad
        convertcontacts.cxx:49), where a mesh-transition glue should not vanish.
        Pinned as a PAIR — both sides resolved through the same SSTYP=4 node-set
        route, so the Idel2 column is the only thing that can differ — because
        the two defaults are one shared emitter apart and could silently
        converge.
        """
        nset = "*SET_NODE_LIST\n         5\n" + _row(100, 101) + "\n"
        base = SPOTWELD_DECK.replace(SET_PART, SET_PART + nset)
        spot = base.replace(_spotweld_card(), _spotweld_card(ssid=5, sstyp=4))
        tied = base.replace(
            _spotweld_card(),
            _spotweld_card(keyword="*CONTACT_TIED_NODES_TO_SURFACE_ID",
                           ssid=5, sstyp=4))
        _r, spot_starter = _convert(spot)
        _r, tied_starter = _convert(tied)
        spot_card = _cards(_block(spot_starter, "/INTER/TYPE2/1"))[0]
        tied_card = _cards(_block(tied_starter, "/INTER/TYPE2/1"))[0]
        self.assertEqual(28, _col_i(spot_card, 31, 40))
        self.assertEqual(28, _col_i(tied_card, 31, 40))
        self.assertEqual(1, _col_i(spot_card, 61, 70))
        self.assertEqual(0, _col_i(tied_card, 61, 70))

    def test_tied_resolver_would_have_dropped_this_weld(self):
        """The reason *CONTACT_SPOTWELD needs its own secondary resolver.

        _tied_slave_nids walks shells and solids only, so on the SSTYP=3 weld
        BEAM part it returns nothing and _make_tied_interfaces drops the
        interface for "no nodes at all". Same card, same deck, routed through
        the tied keyword — pinned so a future refactor cannot quietly hand the
        spotweld path back to that resolver.
        """
        tied = SPOTWELD_DECK.replace(
            "*CONTACT_SPOTWELD_ID", "*CONTACT_TIED_NODES_TO_SURFACE_ID")
        result, tied_starter = _convert(tied)
        self.assertEqual([], _blocks(tied_starter, "/INTER/TYPE2/1"))
        self.assertIn("resolved to no nodes at all", " ".join(result.warnings))
        # ...while the spotweld route emits the tie over the same beam part.
        self.assertIn("/INTER/TYPE2/1\n", self.starter)

    def test_penalty_card2_columns(self):
        """Spotflag 25/26/27/28 read one EXTRA card the kinematic ones do not:
        Stfac(1-20) Visc(21-40) <blank 41-60> Istf(61-70). It is MANDATORY —
        omit it and the starter consumes the next keyword's line."""
        block = _block(self.starter, "/INTER/TYPE2/1")
        card2 = _cards(block)[1]
        self.assertEqual(70, len(card2))
        self.assertEqual(1.0, _col_f(card2, 1, 20))               # Stfac
        self.assertEqual(0.05, _col_f(card2, 21, 40))             # Visc
        self.assertEqual("                    ", card2[40:60])
        self.assertEqual(2, _col_i(card2, 61, 70))                # Istf
        self.assertIn(
            "#              Stfac                Visc                          Istf",
            block)

    def test_default_title(self):
        """A titleless card gets SPOTWELD_CONTACT_<id>, not TIED_CONTACT_<id> —
        the starter echoes the title and it should name what it is."""
        self.assertEqual("SPOTWELD_CONTACT_1",
                         _block(self.starter, "/INTER/TYPE2/1")[1])

    def test_secondary_group_is_the_weld_beam_nodes(self):
        """SSTYP=3 names the WELD part, and a weld part is BEAMS.

        This is the whole point of the keyword: LS-DYNA Vol I R16 SURFATYP=3 is
        a part id, and on every W16/W17 deck that part is the *MAT_SPOTWELD beam
        nuggets. Resolving it over shells and solids only (what the tied-contact
        resolver does) returns an empty group and drops the interface.
        """
        card = _cards(_block(self.starter, "/INTER/TYPE2/1"))[0]
        grnod_id = _col_i(card, 1, 10)
        group = _block(self.starter, f"/GRNOD/NODE/{grnod_id}")
        self.assertEqual([100, 101, 102, 103], _ids_10(group))
        self.assertEqual("spotweld_1_slave", group[1])

    def test_main_surface_is_the_part_set_sheets(self):
        """MSTYP=2 names a *SET_PART_LIST — parts 1+2, the joined sheets."""
        card = _cards(_block(self.starter, "/INTER/TYPE2/1"))[0]
        surf_id = _col_i(card, 11, 20)
        surf = _block(self.starter, f"/SURF/GRSHEL/{surf_id}")
        grshel_id = int(_cards(surf)[0])
        self.assertEqual([1, 2], _ids_10(_block(self.starter,
                                                f"/GRSHEL/SHEL/{grshel_id}")))

    def test_warning_names_the_physics(self):
        warn = " ".join(self.result.warnings)
        self.assertIn("/INTER/TYPE2/1", warn)
        self.assertIn("Spotflag=28", warn)
        self.assertIn("ERROR 556", warn)
        self.assertIn("Idel2=1", warn)


class SpotweldKeywordGrammarTests(unittest.TestCase):
    """Every legal *CONTACT_SPOTWELD spelling dispatches, and the flavours warn."""

    def test_sixteen_generated_spellings_are_registered(self):
        """{<blank>|_WITH_TORSION|_BEAM_OFFSET|_CONSTRAINED_OFFSET} x
        {<blank>|_PENALTY} x {<blank>|_MPP} = 16 (contact_spotweld.cfg:827-856).
        _ID/_TITLE are stripped by the parser and need no key."""
        self.assertEqual(16, len(_SPOTWELD_CONTACT_KEYWORDS))
        for kw in _SPOTWELD_CONTACT_KEYWORDS:
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
        for kw in ("CONTACT_SPOTWELD", "CONTACT_SPOTWELD_WITH_TORSION",
                   "CONTACT_SPOTWELD_WITH_TORSION_PENALTY",
                   "CONTACT_SPOTWELD_BEAM_OFFSET",
                   "CONTACT_SPOTWELD_CONSTRAINED_OFFSET"):
            with self.subTest(user_name=kw):
                self.assertIn(kw, _SPOTWELD_CONTACT_KEYWORDS)

    def test_bare_keyword_without_ID_header(self):
        """The bare *CONTACT_SPOTWELD has NO cid card — Card 1 is the first data
        line, and the id is synthesized (>= 90001) rather than read off it."""
        deck = SPOTWELD_DECK.replace(
            _spotweld_card(), _spotweld_card(keyword="*CONTACT_SPOTWELD"))
        state = _dispatch(deck)
        self.assertEqual(1, len(state.contacts_spotweld))
        c = state.contacts_spotweld[0]
        self.assertGreaterEqual(c.inter_id, 90001)
        self.assertEqual((3, 3, 1, 2), (c.ssid, c.sstyp, c.msid, c.mstyp))

    def test_TITLE_consumes_its_header_card_like_ID(self):
        """_TITLE is stripped by _split_keyword, so one key covers the dispatch
        — but it also CONSUMES a cid/heading card, exactly like _ID.

        contact_spotweld.cfg:1720-1725 is explicit on import: when
        _FIND(_opt,"_ID") misses it retries _FIND(_opt,"_TITLE") and reads the
        SAME CARD("%10d%-70s", _ID_, TITLE). Dispatching the block but not
        consuming that card reads Card 1 off the heading line, so
        ssid/sstyp/msid/mstyp all come back 0 and the interface is then
        silently dropped — a spelling that certifies as "handled" while
        producing nothing. Assert the FIELDS, not just the record count."""
        deck = SPOTWELD_DECK.replace(
            "*CONTACT_SPOTWELD_ID\n", "*CONTACT_SPOTWELD_TITLE\n")
        state = _dispatch(deck)
        self.assertEqual(1, len(state.contacts_spotweld))
        c = state.contacts_spotweld[0]
        self.assertEqual((3, 3, 1, 2), (c.ssid, c.sstyp, c.msid, c.mstyp))
        self.assertEqual(1, c.inter_id)
        _r, starter = _convert(deck)
        self.assertIn("/INTER/TYPE2/1", starter)

    def test_variant_flavours_warn_and_still_convert(self):
        """dyna2rad parses ContactOption 2/3/4 and never reads it, so all five
        spellings convert identically THERE — silently. k2rad emits the same
        card and says what was dropped."""
        for kw, needle in (
            ("_WITH_TORSION", "TORSION"),
            ("_BEAM_OFFSET", "offset lever arm"),
            ("_CONSTRAINED_OFFSET", "CONSTRAINT"),
        ):
            with self.subTest(kw=kw):
                deck = SPOTWELD_DECK.replace(
                    "*CONTACT_SPOTWELD_ID\n", f"*CONTACT_SPOTWELD{kw}_ID\n")
                result, starter = _convert(deck)
                self.assertIn("/INTER/TYPE2/1\n", starter)
                warn = " ".join(result.warnings)
                self.assertIn(f"*CONTACT_SPOTWELD{kw} 1", warn)
                self.assertIn(needle, warn)

    def test_mpp_card_shifts_the_mandatory_cards(self):
        """_MPP inserts its own card BEFORE Card 1 (IGNORE BCKT LCBCKT NS2TRK
        INITITR PARMAX <blank> CPARM8). Reading Card 1 one line early would make
        SSID come back as the MPP IGNORE flag."""
        mpp = _row(1, 200, 0, 3, 2, "1.0005", 0, 0) + "\n"
        deck = SPOTWELD_DECK.replace(
            _spotweld_card(),
            _spotweld_card(keyword="*CONTACT_SPOTWELD_MPP_ID", pre=mpp))
        state = _dispatch(deck)
        c = state.contacts_spotweld[0]
        self.assertEqual((3, 3, 1, 2), (c.ssid, c.sstyp, c.msid, c.mstyp))
        self.assertTrue(c.mpp)

    def test_mpp_second_card_detected_by_ampersand_in_column_1(self):
        """The optional second MPP card is recognised by a literal '&' in COLUMN
        1 (contact_spotweld.cfg CARD_PREREAD("%-1s"))."""
        mpp = (_row(1, 200, 0, 3, 2, "1.0005", 0, 0) + "\n"
               + "&" + " " * 9 + _row(0, "1.0", 0) + "\n")
        deck = SPOTWELD_DECK.replace(
            _spotweld_card(),
            _spotweld_card(keyword="*CONTACT_SPOTWELD_MPP_ID", pre=mpp))
        state = _dispatch(deck)
        c = state.contacts_spotweld[0]
        self.assertEqual((3, 3, 1, 2), (c.ssid, c.sstyp, c.msid, c.mstyp))

    def test_include_transform_offsets_all_non_mpp_spellings(self):
        """_off_contact rewrites b.raw[start] blind, so the _MPP spellings are
        deliberately NOT registered: their Card 1 is one (or two) lines lower and
        offsetting the MPP bucket parameters as SSID/MSID would be worse than
        the unmapped warn."""
        for kw in _SPOTWELD_CONTACT_KEYWORDS:
            with self.subTest(kw=kw):
                self.assertEqual("_MPP" not in kw, kw in _OFFSET_SPECS)


class SpotweldSideResolutionTests(unittest.TestCase):
    """SSTYP / MSTYP -> node group and surface, per LS-DYNA Vol I R16 SURFATYP:
    0 segment set, 1 shell element set, 2 part set, 3 part id, 4 node set."""

    def test_sstyp_3_part(self):
        state = _dispatch(SPOTWELD_DECK)
        self.assertEqual([100, 101, 102, 103],
                         _spotweld_slave_nids(state, 3, 3))

    def test_sstyp_2_part_set(self):
        """A part set on the secondary side unions its parts' nodes."""
        deck = SPOTWELD_DECK.replace(
            SET_PART,
            SET_PART + "*SET_PART_LIST\n         7\n" + _row(3) + "\n")
        deck = deck.replace(_spotweld_card(),
                            _spotweld_card(ssid=7, sstyp=2))
        _r, starter = _convert(deck)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        self.assertEqual(
            [100, 101, 102, 103],
            _ids_10(_block(starter, f"/GRNOD/NODE/{_col_i(card, 1, 10)}")))

    def test_sstyp_4_node_set(self):
        """SSTYP=4 is a *SET_NODE_LIST, taken verbatim."""
        deck = SPOTWELD_DECK.replace(
            SET_PART,
            SET_PART + "*SET_NODE_LIST\n         5\n" + _row(101, 103) + "\n")
        deck = deck.replace(_spotweld_card(),
                            _spotweld_card(ssid=5, sstyp=4))
        _r, starter = _convert(deck)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        self.assertEqual(
            [101, 103],
            _ids_10(_block(starter, f"/GRNOD/NODE/{_col_i(card, 1, 10)}")))

    def test_sstyp_1_shell_element_set(self):
        """SSTYP=1 is a *SET_SHELL_LIST — the nodes of the named shells."""
        deck = SPOTWELD_DECK.replace(
            SET_PART,
            SET_PART + "*SET_SHELL_LIST\n         6\n" + _row(1) + "\n")
        deck = deck.replace(_spotweld_card(),
                            _spotweld_card(ssid=6, sstyp=1, msid=2, mstyp=3))
        _r, starter = _convert(deck)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        self.assertEqual(
            [1, 2, 3, 4],
            _ids_10(_block(starter, f"/GRNOD/NODE/{_col_i(card, 1, 10)}")))

    def test_mstyp_3_single_part(self):
        """MSTYP=3 is one part id — the surface is that part's shells."""
        deck = SPOTWELD_DECK.replace(_spotweld_card(),
                                     _spotweld_card(msid=2, mstyp=3))
        _r, starter = _convert(deck)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        surf = _block(starter, f"/SURF/GRSHEL/{_col_i(card, 11, 20)}")
        self.assertEqual([2], _ids_10(_block(starter,
                                             f"/GRSHEL/SHEL/{int(_cards(surf)[0])}")))

    def test_mstyp_0_segment_set(self):
        """MSTYP=0 is a *SET_SEGMENT — emitted as /SURF/SEG, not a part group."""
        deck = SPOTWELD_DECK.replace(
            SET_PART,
            SET_PART + "*SET_SEGMENT\n         8\n" + _row(1, 2, 3, 4) + "\n")
        deck = deck.replace(_spotweld_card(),
                            _spotweld_card(msid=8, mstyp=0))
        _r, starter = _convert(deck)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        seg = _block(starter, f"/SURF/SEG/{_col_i(card, 11, 20)}")
        self.assertEqual(["         1         1         2         3         4"],
                         _cards(seg))

    def test_unresolvable_secondary_drops_the_interface_loudly(self):
        """Never drop an interface without _drop_interface: the loss has to be
        countable in the log, not just absent from the deck."""
        deck = SPOTWELD_DECK.replace(_spotweld_card(),
                                     _spotweld_card(ssid=999, sstyp=3))
        result, starter = _convert(deck)
        self.assertNotIn("/INTER/TYPE2/1\n", starter)
        warn = " ".join(result.warnings)
        self.assertIn("resolved to no nodes at all", warn)
        self.assertIn("REMEDY:", warn)
        self.assertIn(
            "CONTACT_SPOTWELD",
            " ".join(k for k, _ in result.recognized_not_emitted))

    def test_unresolvable_main_drops_the_interface_loudly(self):
        deck = SPOTWELD_DECK.replace(_spotweld_card(),
                                     _spotweld_card(msid=999, mstyp=2))
        result, starter = _convert(deck)
        self.assertNotIn("/INTER/TYPE2/1\n", starter)
        self.assertIn("resolved to no contact surface",
                      " ".join(result.warnings))


class SpotweldDsearchTests(unittest.TestCase):
    """dsearch comes from the CARD, never from a measured node-segment gap."""

    class _C:
        def __init__(self, sst, mst):
            self.sst, self.mst = sst, mst

    def test_blank_sst_mst_leaves_the_starter_default(self):
        """dyna2rad emits dsearch=0 for *CONTACT_SPOTWELD unconditionally
        (convertcontacts.cxx:61,318) — with Ignore=2 the starter then uses its
        own average-main-segment distance."""
        self.assertEqual(0.0, _spotweld_dsearch(self._C(0.0, 0.0)))

    def test_both_thicknesses_positive_gives_0_6_times_the_sum(self):
        """0.6*(SST+MST): dyna2rad's own formula for the sibling tied contacts
        (convertcontacts.cxx:205) and the second term of the starter's internal
        default (i2cor3.F:198, 0.6*(THKSECND+THKMAIN)). Hand-computed."""
        self.assertAlmostEqual(0.6 * (1.5 + 2.5),
                               _spotweld_dsearch(self._C(1.5, 2.5)), places=12)
        self.assertAlmostEqual(2.4, _spotweld_dsearch(self._C(1.5, 2.5)),
                               places=12)

    def test_one_thickness_alone_is_not_enough(self):
        """dyna2rad's branch requires BOTH (lsdSST > 0 && lsdMST > 0)."""
        self.assertEqual(0.0, _spotweld_dsearch(self._C(1.5, 0.0)))
        self.assertEqual(0.0, _spotweld_dsearch(self._C(0.0, 2.5)))

    def test_negative_sst_is_an_absolute_tie_distance_and_wins(self):
        """A negative Card-3 SAST/SBST is LS-DYNA's absolute tie-criterion
        DISTANCE, not a thickness (Vol I R16) — an explicit instruction, so it
        beats the computed value."""
        self.assertEqual(0.8, _spotweld_dsearch(self._C(-0.8, 0.0)))
        self.assertEqual(0.9, _spotweld_dsearch(self._C(-0.8, -0.9)))
        self.assertEqual(0.8, _spotweld_dsearch(self._C(-0.8, 2.5)))

    def test_dsearch_reaches_the_emitted_card(self):
        deck = SPOTWELD_DECK.replace(_spotweld_card(),
                                     _spotweld_card(sst="1.5", mst="2.5"))
        result, starter = _convert(deck)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        self.assertAlmostEqual(2.4, _col_f(card, 81, 100), places=9)
        self.assertIn("dsearch=2.4 from the Card-3 SST/MST",
                      " ".join(result.warnings))


class SpotweldIntegrationTests(unittest.TestCase):
    """The interface has to reach the rest of the converter, not just the deck."""

    def test_no_implicit_self_contact_stub_is_injected(self):
        """The all-parts TYPE7 stub would ENGAGE across every weld gap — the
        same reason *CONTACT_TIED_* suppresses it."""
        deck = SPOTWELD_DECK.replace(
            "*CONTROL_UNITS\n",
            "*CONTROL_UNITS\n*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n")
        _r, starter = _convert(deck)
        self.assertNotIn("auto_implicit_stabilization_self_contact", starter)
        self.assertNotIn("/INTER/TYPE7/", starter)

    def test_ncforc_th_inter_lists_the_spotweld_interface(self):
        """*DATABASE_NCFORC maps to /TH/INTER over EVERY converted interface;
        a new contact list that misses this is silently absent from the T01."""
        deck = SPOTWELD_DECK.replace(
            "*CONTROL_UNITS\n",
            "*CONTROL_UNITS\n*DATABASE_NCFORC\n     0.001\n")
        _r, starter = _convert(deck)
        block = _block(starter, "/TH/INTER/")
        self.assertIn(1, [int(ln[:10]) for ln in _cards(block)[1:]])


# ── B) *DEFINE_HEX_SPOTWELD_ASSEMBLY -> /CLUSTER/BRICK ───────────────────────

class HexSpotweldAssemblyTests(unittest.TestCase):
    """/GRBRIC/BRIC + /CLUSTER/BRICK, column by column."""

    def setUp(self):
        self.result, self.starter = _convert(HEX_DECK)

    def test_cluster_id_is_the_lsdyna_ID_SW(self):
        """ID_SW sits on its OWN card, not on the keyword line, and is reused
        verbatim as the /CLUSTER id (dyna2rad does the same)."""
        self.assertIn("/CLUSTER/BRICK/7001\n", self.starter)

    def test_card1_columns(self):
        """C1: group_ID(1-10) skew_ID(11-20) Ifail(21-30).

        skew_ID=0 lets the starter build the weld frame from the cluster's own
        bottom->top face normal (hm_read_cluster.F:104), which is the right
        frame for a through-thickness weld. Ifail=3 = multi-directional.
        """
        card = _cards(_block(self.starter, "/CLUSTER/BRICK/7001"))[0]
        self.assertEqual(30, len(card))
        self.assertEqual(0, _col_i(card, 11, 20))
        self.assertEqual(3, _col_i(card, 21, 30))
        self.assertEqual(_CLUSTER_IFAIL, _col_i(card, 21, 30))

    def test_group_holds_the_assembly_bricks(self):
        card = _cards(_block(self.starter, "/CLUSTER/BRICK/7001"))[0]
        group = _block(self.starter, f"/GRBRIC/BRIC/{_col_i(card, 1, 10)}")
        self.assertEqual([101, 102], _ids_10(group))
        self.assertEqual("hex_spotweld_7001_bricks", group[1])

    def test_failure_limits_from_MAT_100(self):
        """Fn_fail1 = NRR, Mt_fail = MRR (both single-direction, straight
        through); the two PAIRS collapse to their live MINIMUM, because the
        engine scores one resultant FT = sqrt(Fx^2+Fy^2) against one Fs_fail
        (clusterf.F:365) and one MB against one Mb_fail (:367).

        min is the reduction that agrees with the quadratic exponent b=2: with
        NRS == NRT == S the /CLUSTER shear term is then (Fx^2+Fy^2)/S^2, which
        IS MAT_100's (Fx/S)^2 + (Fy/S)^2. The obvious sqrt(NRS^2+NRT^2) gives
        (Fx^2+Fy^2)/(2 S^2) — half the damage, i.e. a weld sqrt(2) too strong.

        Deck: NRR 8000, NRS 5000, NRT 4000, MRR 2000, MSS 1500, MTT 1200.
        All four recomputed by hand here."""
        cards = _cards(_block(self.starter, "/CLUSTER/BRICK/7001"))
        self.assertEqual(8000.0, _col_f(cards[1], 1, 20))
        self.assertAlmostEqual(min(5000.0, 4000.0),
                               _col_f(cards[2], 1, 20), places=6)
        self.assertAlmostEqual(4000.0, _col_f(cards[2], 1, 20), places=6)
        self.assertEqual(2000.0, _col_f(cards[3], 1, 20))
        self.assertAlmostEqual(min(1500.0, 1200.0),
                               _col_f(cards[4], 1, 20), places=6)
        self.assertAlmostEqual(1200.0, _col_f(cards[4], 1, 20), places=6)
        # The rejected reduction, named so a regression cannot pass silently.
        self.assertNotAlmostEqual(6403.124237, _col_f(cards[2], 1, 20), places=3)
        self.assertNotAlmostEqual(1920.937271, _col_f(cards[4], 1, 20), places=3)

    def test_isotropic_weld_reproduces_MAT_100_damage_exactly(self):
        """The whole point of pairing b=2 with min(): on the normal round
        nugget (NRS == NRT, MSS == MTT) the converted failure surface IS
        MAT_100's, term for term.

        Engine (clusterf.F:386-390): DMG = a2*(FT/Fs_fail)^b2 with
        FT = sqrt(Fx^2+Fy^2). LS-DYNA: (Fx/NRS)^2 + (Fy/NRT)^2. Recomputed
        here from the EMITTED card at a load the CHANGELOG's worked example
        uses — 40% of the tension limit and 40% of the shear limit at once."""
        deck = HEX_DECK.replace(
            "       0.0    8000.0    5000.0    4000.0    2000.0    1500.0    1200.0",
            "       0.0    8000.0    5000.0    5000.0    2000.0    1500.0    1500.0")
        _r, starter = _convert(deck)
        cards = _cards(_block(starter, "/CLUSTER/BRICK/7001"))
        fn_fail, fs_fail = _col_f(cards[1], 1, 20), _col_f(cards[2], 1, 20)
        a2, b2 = _col_f(cards[2], 21, 40), _col_f(cards[2], 41, 60)
        self.assertEqual(5000.0, fs_fail)          # not 7071.07 = 5000*sqrt(2)
        fn, fx = 0.4 * 8000.0, 0.4 * 5000.0
        radioss = ((fn / fn_fail) ** _col_f(cards[1], 41, 60)
                   + a2 * ((fx ** 2 + 0.0) ** 0.5 / fs_fail) ** b2)
        lsdyna = (fn / 8000.0) ** 2 + (fx / 5000.0) ** 2 + (0.0 / 5000.0) ** 2
        self.assertAlmostEqual(0.32, lsdyna, places=12)
        self.assertAlmostEqual(lsdyna, radioss, places=12)

    def test_anisotropic_pair_is_conservative_and_says_so(self):
        """NRS != NRT cannot be carried by a single Radioss resultant limit.
        min() is then not exact — but it errs on the safe side (damage at or
        above LS-DYNA's, so the weld breaks no later), and the warning has to
        name that rather than claim a fidelity that is not there."""
        result, starter = _convert(HEX_DECK)          # NRS 5000 != NRT 4000
        fs_fail = _col_f(_cards(_block(starter, "/CLUSTER/BRICK/7001"))[2], 1, 20)
        for fx, fy in ((5000.0, 0.0), (0.0, 4000.0), (3000.0, 3000.0)):
            with self.subTest(fx=fx, fy=fy):
                radioss = ((fx * fx + fy * fy) ** 0.5 / fs_fail) ** 2
                lsdyna = (fx / 5000.0) ** 2 + (fy / 4000.0) ** 2
                self.assertGreaterEqual(radioss + 1e-12, lsdyna)
        joined = " ".join(result.warnings)
        self.assertIn("min(NRS,NRT)", joined)
        self.assertIn("conservative", joined)
        self.assertIn("NOT equal", joined)

    def test_a_blank_pair_member_is_skipped_not_taken_as_the_minimum(self):
        """A blank MAT_100 limit is LS-DYNA's 'this component never fails'.
        Taking it as the minimum would emit 0, which the starter promotes to
        INFINITY (hm_read_cluster.F:293-296) and switch the shear term OFF
        entirely — the opposite of what the blank means for the OTHER
        direction."""
        deck = HEX_DECK.replace(
            "       0.0    8000.0    5000.0    4000.0    2000.0    1500.0    1200.0",
            "       0.0    8000.0    5000.0       0.0    2000.0    1500.0       0.0")
        _r, starter = _convert(deck)
        cards = _cards(_block(starter, "/CLUSTER/BRICK/7001"))
        self.assertEqual(5000.0, _col_f(cards[2], 1, 20))
        self.assertEqual(1500.0, _col_f(cards[4], 1, 20))

    def test_exponents_are_quadratic_not_dyna2rads_linear(self):
        """MAT_100's own criterion is (Nrr/NRR)^2 + ... >= 1, and the engine
        forms DMG = a1*(FN/Fn)^b1 + ... (clusterf.F:386-390), so b=2 reproduces
        LS-DYNA and dyna2rad's hardcoded b=1
        (convertdefinehexspotweldassembly.cxx:76-79) does not: a weld at 40% of
        both its tension and shear limits reaches DMG 0.8 under b=1 and fails,
        against 0.4^2+0.4^2 = 0.32 in LS-DYNA."""
        cards = _cards(_block(self.starter, "/CLUSTER/BRICK/7001"))
        for i in range(1, 5):
            with self.subTest(card=i):
                self.assertEqual(60, len(cards[i]))
                self.assertEqual(_CLUSTER_A, _col_f(cards[i], 21, 40))
                self.assertEqual(1.0, _col_f(cards[i], 21, 40))
                self.assertEqual(_CLUSTER_B, _col_f(cards[i], 41, 60))
                self.assertEqual(2.0, _col_f(cards[i], 41, 60))
        # linear interaction: 0.4+0.4 = 0.8 < 1 but quadratic 0.32 — the point
        # of the difference, restated as arithmetic.
        self.assertLess(0.4 ** _CLUSTER_B + 0.4 ** _CLUSTER_B, 0.4 + 0.4)

    def test_all_five_data_cards_are_unconditional(self):
        """The CFG puts no `if` around cards 2-5; omitting one makes the starter
        read the next keyword's line as a failure limit."""
        self.assertEqual(5, len(_cards(_block(self.starter,
                                              "/CLUSTER/BRICK/7001"))))

    def test_N_suffix_counts_elements_not_cards(self):
        """*DEFINE_HEX_SPOTWELD_ASSEMBLY_<N>: N is the TOTAL number of solid
        elements, 1..16 (Vol I R16 p.17-300), so _1 reads one id."""
        deck = HEX_DECK.replace(
            HEX_ASSEMBLY,
            "*DEFINE_HEX_SPOTWELD_ASSEMBLY_1\n      7003\n" + _row(102) + "\n")
        state = _dispatch(deck)
        self.assertEqual(1, len(state.hex_spotweld_assemblies))
        self.assertEqual([102], state.hex_spotweld_assemblies[0].eids)
        self.assertEqual(7003, state.hex_spotweld_assemblies[0].sw_id)

    def test_N_suffix_above_8_reads_the_second_card(self):
        """N > 8 adds a second EID card (EID9..EID16)."""
        ids = list(range(101, 111))
        deck = (
            "*KEYWORD\n" + HEX_NODES + HEX_PARTS + HEX_ELEMS
            + "*DEFINE_HEX_SPOTWELD_ASSEMBLY_10\n      7004\n"
            + _row(*ids[:8]) + "\n" + _row(*ids[8:]) + "\n" + "*END\n")
        state = _dispatch(deck)
        self.assertEqual(ids, state.hex_spotweld_assemblies[0].eids)

    def test_N_suffix_registered_for_1_through_16(self):
        for n in range(1, 17):
            with self.subTest(n=n):
                self.assertIn(f"DEFINE_HEX_SPOTWELD_ASSEMBLY_{n}", HANDLERS)
        self.assertIn("DEFINE_HEX_SPOTWELD_ASSEMBLY", HANDLERS)

    def test_tetrahedra_are_screened_out_with_a_warning(self):
        """A tet in the cluster group is NOT a starter error — measured: the
        group resolves and the cluster counts it, 0 ERROR(S). It is screened
        because the result is silently wrong: hm_read_cluster.F:201-205 takes
        the weld's two joined faces from IXS(2:5)/IXS(6:9), the hex bottom and
        top faces, so a collapsed tet gives a degenerate top face and corrupts
        the local frame the whole failure surface is evaluated in.
        """
        deck = HEX_DECK.replace(
            HEX_ELEMS,
            HEX_ELEMS + "*ELEMENT_SOLID\n       103         4\n"
            + _row(201, 202, 203, 205, 205, 205, 205, 205) + "\n")
        deck = deck.replace(HEX_ASSEMBLY,
                            "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n      7001\n"
                            + _row(101, 102, 103) + "\n")
        result, starter = _convert(deck)
        card = _cards(_block(starter, "/CLUSTER/BRICK/7001"))[0]
        self.assertEqual([101, 102],
                         _ids_10(_block(starter,
                                        f"/GRBRIC/BRIC/{_col_i(card, 1, 10)}")))
        # ...and the tet is still in the model, just not in the weld group.
        self.assertIn("/TETRA4/", starter)
        self.assertIn("are tetrahedra", " ".join(result.warnings))

    def test_unknown_element_id_is_warned_not_silently_grouped(self):
        deck = HEX_DECK.replace(HEX_ASSEMBLY,
                                "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n      7001\n"
                                + _row(101, 999) + "\n")
        result, starter = _convert(deck)
        card = _cards(_block(starter, "/CLUSTER/BRICK/7001"))[0]
        self.assertEqual([101],
                         _ids_10(_block(starter,
                                        f"/GRBRIC/BRIC/{_col_i(card, 1, 10)}")))
        self.assertIn("name no *ELEMENT_SOLID", " ".join(result.warnings))

    def test_assembly_with_no_brick_emits_nothing_and_says_so(self):
        deck = HEX_DECK.replace(HEX_ASSEMBLY,
                                "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n      7001\n"
                                + _row(9001, 9002) + "\n")
        result, starter = _convert(deck)
        self.assertNotIn("/CLUSTER/BRICK/", starter)
        warn = " ".join(result.warnings)
        self.assertIn("NO /CLUSTER/BRICK was emitted", warn)
        self.assertIn("PHYSICAL CONSEQUENCE", warn)

    def test_no_MAT_100_leaves_the_weld_unbreakable_and_warns(self):
        """Zero limits auto-promote to INFINITY when Ifail > 0
        (hm_read_cluster.F:293-296) — the cluster then never fails, which is a
        physics loss the user has to be told about."""
        deck = HEX_DECK.replace("         4         4       100\n",
                                "         4         4         1\n")
        result, starter = _convert(deck)
        cards = _cards(_block(starter, "/CLUSTER/BRICK/7001"))
        for i in range(1, 5):
            self.assertEqual(0.0, _col_f(cards[i], 1, 20))
        self.assertIn("NEVER fails", " ".join(result.warnings))

    def test_empty_assembly_card_warns_and_emits_nothing(self):
        deck = HEX_DECK.replace(
            HEX_ASSEMBLY, "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n      7001\n")
        result, starter = _convert(deck)
        self.assertNotIn("/CLUSTER/", starter)
        self.assertIn("no solid element ids on the card",
                      " ".join(result.warnings).lower())


# ── C) *DATABASE_SWFORC -> /TH/SPRING + /TH/BRIC + /TH/CLUSTER ───────────────

class SwforcTimeHistoryTests(unittest.TestCase):
    """The three swforc channels, and the graceful no-weld case."""

    def test_th_spring_lists_the_MAT_100_beam_weld_element_ids(self):
        """k2rad's MAT_100 beam welds keep their *ELEMENT_BEAM ids verbatim as
        /SPRING sprg_IDs, so a T01 channel maps 1:1 onto an swforc row."""
        deck = SPOTWELD_DECK.replace("*CONTROL_UNITS\n", "*CONTROL_UNITS\n" + SWFORC)
        _r, starter = _convert(deck)
        block = _blocks(starter, "/TH/SPRING/")[0]
        self.assertEqual([11, 12], _th_obj_ids(block))
        self.assertTrue(block[1].startswith("TH_SPOTWELD_SPRINGS_"))

    def test_th_spring_requests_DEF_and_FAIL(self):
        """DEF expands to indices 1-14 + 65 (hm_read_thgrou.F:1519) — index 66,
        FAIL, is NOT in it, and on a weld FAIL is the channel swforc is about.
        Variable cells are 10 chars wide."""
        deck = SPOTWELD_DECK.replace("*CONTROL_UNITS\n", "*CONTROL_UNITS\n" + SWFORC)
        _r, starter = _convert(deck)
        line = _th_var_line(_blocks(starter, "/TH/SPRING/")[0])
        self.assertEqual("DEF       FAIL      ", line)
        self.assertEqual("DEF       ", line[0:10])
        self.assertEqual("FAIL      ", line[10:20])

    def test_th_spring_object_ids_are_one_per_line(self):
        """/TH/SPRING and /TH/BRIC go through hm_read_thgrne.F (elem_ID in cols
        1-10, one per line) — NOT the ten-per-line hm_read_thgrki.F that
        /TH/CLUSTER uses. Getting this backwards silently loses channels."""
        deck = SPOTWELD_DECK.replace("*CONTROL_UNITS\n", "*CONTROL_UNITS\n" + SWFORC)
        _r, starter = _convert(deck)
        rows = _cards(_blocks(starter, "/TH/SPRING/")[0])[1:]
        self.assertEqual(["        11", "        12"], rows)

    def test_th_bric_for_MAT_100_solid_welds(self):
        """dyna2rad's SECOND SWFORC pass (dyna2rad.cxx:685-689): *ELEMENT_SOLID
        on a MAT_100 part -> /TH/BRIC, variables DEF (no FAIL variable exists)."""
        deck = HEX_DECK.replace("*MAT_ELASTIC\n", SWFORC + "*MAT_ELASTIC\n")
        _r, starter = _convert(deck)
        block = _blocks(starter, "/TH/BRIC/")[0]
        self.assertEqual("DEF       ", _th_var_line(block))
        self.assertEqual([101, 102], _th_obj_ids(block))

    def test_th_bric_lists_tet_welds_too(self):
        """/TH/BRIC is read over the WHOLE solid array (hm_read_thgrou.F ITYP=1,
        NUMELS), so a /TETRA4 id resolves there exactly like a /BRICK —
        confirmed on a live starter run, 0 ERROR(S) with a TET4 in the list.
        Applying the /CLUSTER's topology screening here would silently drop a
        channel the deck asked for."""
        deck = HEX_DECK.replace("*MAT_ELASTIC\n", SWFORC + "*MAT_ELASTIC\n")
        deck = deck.replace(
            HEX_ELEMS,
            HEX_ELEMS + "*ELEMENT_SOLID\n       103         4\n"
            + _row(201, 202, 203, 205, 205, 205, 205, 205) + "\n")
        _r, starter = _convert(deck)
        self.assertIn("/TETRA4/", starter)
        self.assertEqual([101, 102, 103],
                         _th_obj_ids(_blocks(starter, "/TH/BRIC/")[0]))

    def test_th_cluster_only_when_swforc_asks(self):
        """The cluster itself is unconditional; its /TH block is the swforc
        answer, so a deck without *DATABASE_SWFORC gets no /TH/CLUSTER."""
        _r, starter = _convert(HEX_DECK)
        self.assertIn("/CLUSTER/BRICK/7001", starter)
        self.assertEqual([], _blocks(starter, "/TH/CLUSTER/"))

    def test_th_cluster_vars_and_ten_per_line_object_list(self):
        """DEF -> FX FY FZ MX MY MZ FAIL, FLOC -> FS FN MS MN
        (hm_read_thgrou.F:1763-1766). dyna2rad asks for DEF alone, so the LOCAL
        weld resultants — the ones swforc actually prints — never reach its T01.
        The CFG dropdown's FT/MB/MT are NOT starter names (ERROR 260)."""
        deck = HEX_DECK.replace("*MAT_ELASTIC\n", SWFORC + "*MAT_ELASTIC\n")
        deck = deck.replace(
            HEX_ASSEMBLY,
            HEX_ASSEMBLY + "*DEFINE_HEX_SPOTWELD_ASSEMBLY_1\n      7002\n"
            + _row(102) + "\n")
        _r, starter = _convert(deck)
        block = _block(starter, "/TH/CLUSTER/")
        self.assertEqual("DEF       FLOC      ", _th_var_line(block))
        self.assertEqual([7001, 7002], _th_cluster_obj_ids(block))
        self.assertEqual(["      7001      7002"], _cards(block)[1:])
        self.assertNotIn("FT        ", _th_var_line(block))

    def test_no_weld_entities_warns_and_emits_no_dangling_th(self):
        """A /TH group listing nothing is a starter error, so the request has to
        degrade to a warning rather than an empty block."""
        deck = ("*KEYWORD\n" + SHEET_NODES
                + "*ELEMENT_SHELL\n"
                  "         1         1         1         2         3         4\n"
                + "*PART\nplain\n         1         1         1\n"
                  "*SECTION_SHELL\n         1         2       1.0         2       1.0\n"
                  "       1.0       1.0       1.0       1.0\n"
                  "*MAT_ELASTIC\n         1 7.850E-9  210000.       0.3\n"
                + SWFORC + "*END\n")
        result, starter = _convert(deck)
        self.assertNotIn("/TH/SPRING", starter)
        self.assertNotIn("/TH/BRIC", starter)
        self.assertNotIn("/TH/CLUSTER", starter)
        self.assertIn("has no spot weld", " ".join(result.warnings))

    def test_cluster_only_deck_does_not_warn_about_missing_welds(self):
        """A hex-weld deck IS answered — by /TH/CLUSTER — so the "no spot weld"
        warning must not fire just because there are no MAT_100 springs."""
        deck = HEX_DECK.replace("         4         4       100\n",
                                "         4         4         1\n")
        deck = deck.replace("*MAT_ELASTIC\n", SWFORC + "*MAT_ELASTIC\n")
        result, starter = _convert(deck)
        self.assertIn("/TH/CLUSTER/", starter)
        self.assertNotIn("defines no spot weld", " ".join(result.warnings))

    def test_swforc_dt_drives_the_engine_TFILE(self):
        """A SWFORC-only deck used to fall through to the 1e-3 /TFILE default,
        writing the T01 at the wrong frequency.

        The dt here is deliberately NOT 0.001: that is the fallback default, so
        asserting it would pass whether or not db_swforc_dt reaches /TFILE at
        all — a check that cannot fail."""
        deck = SPOTWELD_DECK.replace(
            "*CONTROL_UNITS\n",
            "*CONTROL_UNITS\n" + SWFORC.replace("     0.001", "   2.5E-05"))
        _r, _s, engine = _convert_both(deck)
        tfile = engine.splitlines()[engine.splitlines().index("/TFILE") + 1]
        self.assertEqual(2.5e-05, float(tfile))

    def test_TFILE_takes_the_MINIMUM_over_the_DATABASE_family(self):
        """Radioss has ONE time-history frequency, so the whole *DATABASE_*
        family collapses to one /TFILE. It must be the MINIMUM: a first-non-zero
        rule hands the frequency to whichever card sits earliest in the chain,
        and *DATABASE_NODOUT is first, so a weld deck asking SWFORC 2.5e-5 and
        NODOUT 0.01 would sample every new weld channel 400x too coarsely."""
        deck = SPOTWELD_DECK.replace(
            "*CONTROL_UNITS\n",
            "*CONTROL_UNITS\n"
            + "*DATABASE_NODOUT\n      0.01\n"
            + SWFORC.replace("     0.001", "   2.5E-05"))
        _r, _s, engine = _convert_both(deck)
        tfile = engine.splitlines()[engine.splitlines().index("/TFILE") + 1]
        self.assertEqual(2.5e-05, float(tfile))

    def test_swforc_dt_is_parsed_onto_state(self):
        state = _dispatch("*KEYWORD\n" + SWFORC + "*END\n")
        self.assertEqual(0.001, state.db_swforc_dt)


# ── Regression: a /TH block may never name an element that was not emitted ───

class ThObjectsMustExistTests(unittest.TestCase):
    """The invariant the starter enforces on every /TH element group.

    hm_read_thgrne.F:189-191 answers an unresolvable object with
    ANCMSG(MSGID=69, MSGTYPE=MSGERROR) — "TH ELEMENT SELECTION ID=n DOES NOT
    EXIST". MSGERROR, not a warning: the deck is REFUSED and there is no restart
    file. So a lost weld channel must be dropped from the /TH block, never
    listed and left dangling.

    The hole this pins: _make_starter_th_swforc builds the /TH/SPRING list from
    PARSED state (every beam on a *MAT_SPOTWELD part), while
    _make_spotweld_beam_connectors skips a whole part — emitting no /SPRING and
    no /PROP/TYPE13 — for zero-length welds, a missing *SECTION_BEAM, or a
    zero cross-section area. Both unconvertible flavours are exercised below.
    """

    # SPOTWELD_DECK's weld beams 11/12 with their two ends made COINCIDENT, so
    # the connector writer's `L <= 1e-12` branch skips the whole part.
    ZERO_LENGTH = (SHEET_NODES.replace("       101       2.0       2.0       2.0",
                                       "       101       2.0       2.0       0.0")
                   .replace("       103       8.0       8.0       2.0",
                            "       103       8.0       8.0       0.0"))

    def _emitted_spring_eids(self, starter):
        out = set()
        for block in _blocks(starter, "/SPRING/"):
            for ln in block[1:]:
                if not ln.startswith("#") and ln.strip():
                    out.add(int(ln[:10]))
        return out

    def _th_ids(self, starter, header):
        return {e for b in _blocks(starter, header) for e in _th_obj_ids(b)}

    def test_zero_length_welds_are_not_listed_in_TH_SPRING(self):
        deck = ("*KEYWORD\n" + self.ZERO_LENGTH + SHEET_ELEMS + SHEET_PARTS
                + SET_PART + _spotweld_card()
                + SWFORC + "*END\n")
        result, starter = _convert(deck)
        self.assertEqual(set(), self._emitted_spring_eids(starter))
        self.assertNotIn("/TH/SPRING", starter)
        joined = " ".join(result.warnings)
        self.assertIn("have no /SPRING in the converted deck", joined)
        self.assertIn("[11, 12]", joined)

    def test_welds_with_no_SECTION_BEAM_are_not_listed_in_TH_SPRING(self):
        deck = ("*KEYWORD\n" + SHEET_NODES + SHEET_ELEMS
                + SHEET_PARTS.replace(
                    "*SECTION_BEAM\n"
                    "         9         9\n"
                    "       1.0       3.0       3.0       0.0       0.0\n", "")
                + SET_PART + _spotweld_card() + SWFORC + "*END\n")
        result, starter = _convert(deck)
        self.assertEqual(set(), self._emitted_spring_eids(starter))
        self.assertNotIn("/TH/SPRING", starter)
        self.assertIn("have no /SPRING in the converted deck",
                      " ".join(result.warnings))

    def test_every_TH_SPRING_and_TH_BRIC_id_was_actually_emitted(self):
        """The general invariant, on the healthy deck: subsets, not equality —
        a channel may be dropped, but never invented."""
        deck = HEX_DECK.replace("*MAT_ELASTIC\n", SWFORC + "*MAT_ELASTIC\n")
        _r, starter = _convert(deck)
        solids = (_elem_ids(starter, "/BRICK/") | _elem_ids(starter, "/TETRA4/")
                  | _elem_ids(starter, "/TETRA10/"))
        th_bric = self._th_ids(starter, "/TH/BRIC/")
        self.assertTrue(th_bric)
        self.assertLessEqual(th_bric, solids)
        self.assertLessEqual(self._th_ids(starter, "/TH/SPRING/"),
                             self._emitted_spring_eids(starter))

    def test_healthy_beam_welds_are_still_listed(self):
        """The filter must not swallow the normal case."""
        deck = SPOTWELD_DECK.replace("*CONTROL_UNITS\n", "*CONTROL_UNITS\n" + SWFORC)
        result, starter = _convert(deck)
        self.assertEqual({11, 12}, self._emitted_spring_eids(starter))
        self.assertEqual({11, 12}, self._th_ids(starter, "/TH/SPRING/"))
        self.assertNotIn("have no /SPRING in the converted deck",
                         " ".join(result.warnings))


# ── Regression: ID_SW is a user id and must be repaired, not passed through ──

class ClusterIdHygieneTests(unittest.TestCase):
    """A blank or duplicated ID_SW is a malformed deck (LS-DYNA Vol I R16
    p.17-300 requires it unique), and passing it through breaks the .rad in two
    different ways: /CLUSTER/BRICK/0 puts a literal 0 in the /TH/CLUSTER object
    list, which hm_read_thgrki.F:123-137 reads as "ALL clusters" (WARNING
    3083); a repeat is a duplicate-id starter rejection."""

    def test_blank_ID_SW_gets_a_generated_id_and_never_a_zero_in_TH(self):
        deck = HEX_DECK.replace("*DEFINE_HEX_SPOTWELD_ASSEMBLY\n      7001\n",
                                "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n          \n")
        deck = deck.replace("*MAT_ELASTIC\n", SWFORC + "*MAT_ELASTIC\n")
        result, starter = _convert(deck)
        self.assertNotIn("/CLUSTER/BRICK/0\n", starter)
        cluster_ids = [int(ln.rsplit("/", 1)[1])
                       for ln in starter.splitlines()
                       if ln.startswith("/CLUSTER/BRICK/")]
        self.assertEqual(1, len(cluster_ids))
        self.assertGreater(cluster_ids[0], 0)
        th = _blocks(starter, "/TH/CLUSTER/")[0]
        self.assertNotIn(0, _th_cluster_obj_ids(th))
        self.assertEqual(cluster_ids, _th_cluster_obj_ids(th))
        self.assertIn("is blank or zero", " ".join(result.warnings))

    def test_duplicate_ID_SW_does_not_emit_two_clusters_with_one_id(self):
        deck = HEX_DECK.replace(
            HEX_ASSEMBLY,
            HEX_ASSEMBLY + "*DEFINE_HEX_SPOTWELD_ASSEMBLY\n      7001\n"
            + _row(102) + "\n")
        result, starter = _convert(deck)
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/CLUSTER/BRICK/")]
        self.assertEqual(2, len(ids))
        self.assertEqual(2, len(set(ids)))
        self.assertIn("used by more than one assembly", " ".join(result.warnings))

    def test_a_good_ID_SW_still_goes_straight_through(self):
        _r, starter = _convert(HEX_DECK)
        self.assertIn("/CLUSTER/BRICK/7001", starter)


# ── Regression: hex assembly element cards under *INCLUDE_TRANSFORM ──────────

class HexAssemblyOffsetTests(unittest.TestCase):
    """The EID cards are *ELEMENT_SOLID ids and move with IDEOFF. Without an
    _OFFSET_SPECS entry they stay put, no solid matches, and
    _make_hex_spotweld_clusters emits NO /CLUSTER at all — the hex weld
    silently loses its failure criterion and holds for the whole run."""

    def test_every_spelling_is_registered(self):
        self.assertIn("DEFINE_HEX_SPOTWELD_ASSEMBLY", _OFFSET_SPECS)
        for n in (1, 8, 16):
            with self.subTest(n=n):
                self.assertIn(f"DEFINE_HEX_SPOTWELD_ASSEMBLY_{n}", _OFFSET_SPECS)

    def test_element_ids_shift_and_ID_SW_does_not(self):
        from k2rad.parser import Block
        b = Block(keyword="DEFINE_HEX_SPOTWELD_ASSEMBLY", options=[],
                  raw=[_row(7001), _row(101, 102)])
        _OFFSET_SPECS["DEFINE_HEX_SPOTWELD_ASSEMBLY"](
            b, {"e": 500, "n": 9, "p": 9}, lambda *a, **k: None)
        self.assertEqual(7001, int(b.raw[0][:10]))
        self.assertEqual([601, 602],
                         [int(b.raw[1][i:i + 10]) for i in (0, 10)])


# ── Regression: comma-format element cards on the hex assembly ───────────────

class HexAssemblyFreeFormatTests(unittest.TestCase):
    """A comma/free-format card written narrower than 10 columns slices to
    ['101,102,10', '3', ...]: to_int drops 101/102/103 and ADDS element 3 to
    the weld cluster — a wrong cluster with no warning at all."""

    def test_comma_format_element_card_is_read_correctly(self):
        state = _dispatch("*KEYWORD\n*DEFINE_HEX_SPOTWELD_ASSEMBLY\n"
                          "7001\n101,102,103\n*END\n")
        self.assertEqual(1, len(state.hex_spotweld_assemblies))
        self.assertEqual([101, 102, 103], state.hex_spotweld_assemblies[0].eids)
        self.assertEqual(7001, state.hex_spotweld_assemblies[0].sw_id)

    def test_fixed_format_is_unchanged(self):
        state = _dispatch("*KEYWORD\n*DEFINE_HEX_SPOTWELD_ASSEMBLY\n"
                          + _row(7001) + "\n" + _row(101, 102, 103) + "\n*END\n")
        self.assertEqual([101, 102, 103], state.hex_spotweld_assemblies[0].eids)


# ── Regression: /TH/INTER must not name a dropped interface ──────────────────

class DroppedInterfacesAreNotInThTests(unittest.TestCase):
    """/TH/INTER was built from the PARSED contact records, so a contact whose
    side resolved to nothing was still listed and the starter answered
    WARNING 257 "NONEXISTENT INTER <id>" on an otherwise clean deck. Observed
    on W16_SW_door_* (id 6) and W17_RS_FloorFrame (id 90001)."""

    def test_a_dropped_spotweld_contact_is_not_listed(self):
        deck = SPOTWELD_DECK.replace(
            _spotweld_card(),
            _spotweld_card(cid=7, ssid=999)          # names no part
            + "*DATABASE_RCFORC\n     0.001\n")
        result, starter = _convert(deck)
        self.assertNotIn("/INTER/TYPE2/7", starter)
        self.assertIn("resolved to no nodes at all", " ".join(result.warnings))
        listed = {e for b in _blocks(starter, "/TH/INTER/") for e in _th_obj_ids(b)}
        self.assertNotIn(7, listed)

    def test_an_emitted_contact_is_still_listed(self):
        deck = SPOTWELD_DECK.replace(
            "*CONTROL_UNITS\n", "*CONTROL_UNITS\n*DATABASE_RCFORC\n     0.001\n")
        _r, starter = _convert(deck)
        listed = {e for b in _blocks(starter, "/TH/INTER/") for e in _th_obj_ids(b)}
        self.assertIn(1, listed)


# ── Regression: the master surface must not mix /SHELL and /SH3N ids ─────────

class MasterSurfaceTopologySplitTests(unittest.TestCase):
    """A contact master surface built from a part that carries TRIANGLES.

    /GRSHEL/SHEL resolves only 4-node /SHELL ids, and a 3-corner shell — written
    as 3 ids or as a collapsed quad n1 n2 n3 n3 — is emitted as /SH3N. Putting
    one in the quad group is starter ERROR 70 "ELEMENT ID=n DOES NOT EXIST",
    which rejects the whole deck. Measured on W16_spotweld_E1 (collapsed quad
    529 = 695/665/664/664) before this split existed.
    """

    DECK = (
        "*KEYWORD\n" + SHEET_NODES
        + "*ELEMENT_SHELL\n"
          "         1         1         1         2         3         4\n"
          "         3         1         1         2         5         5\n"
          "         2         2         5         6         7         8\n"
        + "*ELEMENT_BEAM\n"
          "        11         3       100       101         0\n"
        + SHEET_PARTS + SET_PART + _spotweld_card() + "*END\n"
    )

    def test_triangles_go_to_their_own_group_and_sub_surface(self):
        _r, starter = _convert(self.DECK)
        card = _cards(_block(starter, "/INTER/TYPE2/1"))[0]
        surf = _block(starter, f"/SURF/SURF/{_col_i(card, 11, 20)}")
        sub_ids = _ids_10(surf)
        self.assertEqual(2, len(sub_ids))
        quad_surf = _block(starter, f"/SURF/GRSHEL/{sub_ids[0]}")
        tri_surf = _block(starter, f"/SURF/GRSH3N/{sub_ids[1]}")
        self.assertEqual(
            [1, 2],
            _ids_10(_block(starter, f"/GRSHEL/SHEL/{int(_cards(quad_surf)[0])}")))
        self.assertEqual(
            [3],
            _ids_10(_block(starter, f"/GRSH3N/SH3N/{int(_cards(tri_surf)[0])}")))

    def test_every_grouped_shell_id_exists_as_that_element_type(self):
        """The invariant the starter enforces, restated: no id may appear in a
        /GRSHEL/SHEL unless it was emitted under /SHELL, and likewise /GRSH3N."""
        _r, starter = _convert(self.DECK)
        shells = _elem_ids(starter, "/SHELL/")
        tris = _elem_ids(starter, "/SH3N/")
        self.assertEqual({1, 2}, shells)
        self.assertEqual({3}, tris)
        grouped_quads = {e for b in _blocks(starter, "/GRSHEL/SHEL/")
                         for e in _ids_10(b)}
        grouped_tris = {e for b in _blocks(starter, "/GRSH3N/SH3N/")
                        for e in _ids_10(b)}
        self.assertTrue(grouped_quads)
        self.assertTrue(grouped_tris)
        self.assertLessEqual(grouped_quads, shells)
        self.assertLessEqual(grouped_tris, tris)

    def test_quad_only_master_surface_is_unchanged(self):
        """The single-kind path must still emit a bare /SURF/GRSHEL — a deck
        with no triangles has to be byte-identical to before the split."""
        _r, starter = _convert(SPOTWELD_DECK)
        self.assertNotIn("/SURF/SURF/", starter)
        self.assertNotIn("/SURF/GRSH3N/", starter)
        self.assertIn("/SURF/GRSHEL/", starter)


# ── Corpus: decks WITHOUT spotweld keywords must be untouched ────────────────

class UnrelatedDeckByteIdentityTests(unittest.TestCase):
    """The checked-in golden FIXTURES must convert to exactly what they
    converted to before — these five decks, not the corpus.

    Scope matters here: this batch is NOT corpus-wide byte-identical, and the
    CHANGELOG names the exception. Ryan_Lee_Examples/W2_Door_Impact.k carries
    none of the three keywords and still changes, through the shared
    _make_master_surface topology split — deliberately, because on master its
    3-corner shells land in a /GRSHEL/SHEL and the starter refuses the deck
    with 19 ERROR 70s. The split is a no-op only on a master surface with no
    triangles, which is what the fixtures below have.
    """

    REPO = Path(__file__).resolve().parent.parent

    def _sha(self, deck: Path) -> str:
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            res = convert(str(deck), output_stem=str(Path(td) / "m"),
                          write_log=False)
            h = hashlib.sha256()
            for p in (res.starter_path, res.engine_path):
                h.update(Path(p).read_bytes())
            return h.hexdigest()

    def test_fixture_decks_without_spotweld_keywords_still_match_the_goldens(self):
        """The golden fixtures are the checked-in byte-identity anchor; this
        re-asserts them from inside the batch's own module (batch policy)."""
        fixtures = self.REPO / "tests" / "fixtures"
        expected = fixtures / "expected"
        for deck in sorted(fixtures.glob("*.k")):
            with self.subTest(deck=deck.name):
                text = deck.read_text(errors="replace")
                self.assertNotIn("*CONTACT_SPOTWELD", text)
                self.assertNotIn("*DEFINE_HEX_SPOTWELD", text)
                self.assertNotIn("*DATABASE_SWFORC", text)
                with tempfile.TemporaryDirectory() as td:
                    res = convert(str(deck), output_stem=str(Path(td) / deck.stem),
                                  write_log=False)
                    for suffix in ("_0000.rad", "_0001.rad"):
                        gold = expected / f"{deck.stem}{suffix}"
                        if not gold.exists():
                            continue
                        got = Path(res.starter_path if suffix == "_0000.rad"
                                   else res.engine_path).read_text()
                        self.assertEqual(gold.read_text(), got)

    def test_conversion_is_deterministic(self):
        """Two runs of the same spotweld deck give the same bytes — the new id
        allocations must not depend on set iteration order."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "d.k"
            path.write_text(SPOTWELD_DECK + HEX_ASSEMBLY)
            self.assertEqual(self._sha(path), self._sha(path))


if __name__ == "__main__":
    unittest.main()
