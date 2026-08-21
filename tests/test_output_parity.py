"""The output / instrumentation parity batch:

  *DATABASE_HISTORY_BEAM[_SET][_ID]      -> /TH/BEAM (+ /TH/SPRING per element)
  *DATABASE_HISTORY_DISCRETE[_SET][_ID]  -> /TH/SPRING
  *DATABASE_HISTORY_NODE_SET
      / _NODE_LOCAL[_ID] / _NODE_SET_LOCAL -> /TH/NODE + per-node skew_ID
  *DATABASE_HISTORY_{SHELL,SOLID,TSHELL}_SET -> the family's existing groups
  *DATABASE_HISTORY_SEATBELT             -> recognized, honestly not emitted
  *DATABASE_NODAL_FORCE_GROUP[_TITLE]    -> /TH/NODE, seven variables
  *DATABASE_RBDOUT                       -> /TH/RBODY over every /RBODY
  *DATABASE_BNDOUT                       -> /TH/NODE REAC* on the /IMP* nodes
  *DATABASE_NODFOR / _TPRINT             -> interval only / nothing
  *CONTROL_PARALLEL                      -> engine /PARITH

Everything column-exact against layouts pinned on live starter runs at
/BEGIN 2022 AND 2612 (identical parse at both). The conventions that carry the
most risk, and why each is asserted rather than assumed:

* **The /TH id namespace is GLOBAL across types.** Four /TH/... blocks sharing
  id 1 gave three x ``ERROR ID 79 DUPLICATE ID / IN TH GROUP DEFINITION`` and
  error termination, so every group id is checked for uniqueness.
* **Only /TH/NODE (and, since radioss140, /TH/SHEL / /TH/SH3N) has a skew
  column.** Writing a skew into columns 11-20 of a /TH/BEAM or /TH/SPRING id
  card is ``WARNING 100214`` and the value is SILENTLY dropped — measured — so
  the blank-gap layout is asserted per type.
* **/TH/RBODY is a TEN-PER-LINE cell list**, not one id per line, and a leading
  0 in it means ALL rigid bodies (hm_read_thgrki_rbody.F:123-125).
* **A dangling id is a starter REFUSAL, not a lost channel** — ERROR 69 for the
  element types, ERROR 78 for nodes — so every new /TH type gets a
  dangling-id filter test, and every /SPRING and /RBODY producer gets a
  reachability test (a missed producer silently drops a user's channel; a stale
  id refuses the deck).
* **An EMPTY group is ERROR 1109 in its own right**, so a request that resolves
  to nothing writes no block at all.
* **A deck without these keywords must be byte-identical to master.**
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                                # noqa: E402
from k2rad.assembly import _OFFSET_SPECS, _offset_block  # noqa: E402
from k2rad.handlers import HANDLERS, dispatch            # noqa: E402
from k2rad.parser import parse_k_file                    # noqa: E402
from k2rad.state import ConversionState                  # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

def _convert(deck_text: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck_text)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


def _dispatch(deck_text: str) -> ConversionState:
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck_text)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _blocks(starter: str, header: str):
    out, cur = [], None
    for ln in starter.splitlines():
        if ln.startswith(header):
            cur = [ln]
            out.append(cur)
        elif cur is not None:
            if ln.startswith("#---1----") or ln.startswith("/"):
                cur = None
            else:
                cur.append(ln)
    return out


def _block(starter: str, header: str):
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _rows(block):
    """A /TH block's id cards: header, title, comments and the VAR line gone."""
    body = [ln for ln in block[2:] if not ln.startswith("#")]
    return body[1:]                     # drop the VAR line


def _var_line(block):
    return [ln for ln in block[2:] if not ln.startswith("#")][0]


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(result, needle: str):
    return [w for w in result.warnings if needle in w]


def _emitted_spring_ids(starter: str):
    """Every sprg_ID the starter text actually carries, parsed independently of
    the converter's own registries."""
    out = set()
    inside = False
    for ln in starter.splitlines():
        if ln.startswith("/SPRING/"):
            inside = True
            continue
        if not inside:
            continue
        if ln.startswith("#---1----") or ln.startswith("/"):
            inside = False
            continue
        if ln.startswith("#") or not ln.strip():
            continue
        out.add(int(ln[:10]))
    return out


def _th_headers(starter: str):
    return [ln for ln in starter.splitlines() if ln.startswith("/TH/")]


def _row(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals) + "\n"


# ── Deck fragments ───────────────────────────────────────────────────────────
#
# Eight nodes, two beams on part 1, one discrete spring on part 2, one quad on
# part 3, one hex on the RIGID part 4. Small enough to hand-count every id that
# reaches a /TH group.

NODES = "*NODE\n" + "".join(
    f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 0.0, 10.0, 0.0),
        (4, 10.0, 10.0, 0.0), (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
        (7, 20.0, 0.0, 0.0), (8, 30.0, 0.0, 0.0)))

BEAMS = ("*ELEMENT_BEAM\n"
         + f"{101:>8}{1:>8}{1:>8}{2:>8}{3:>8}\n"
         + f"{102:>8}{2:>8}{2:>8}{7:>8}{3:>8}\n"
         + "*PART\nbeams a\n" + _row(1, 1, 1)
         + "*PART\nbeams b\n" + _row(2, 1, 1)
         + "*SECTION_BEAM\n" + _row(1, 1, 1.0, 2, 1.0)
         + _row(4.0, 4.0, 2.0, 2.0))

SPRINGS = ("*ELEMENT_DISCRETE\n" + f"{201:>8}{5:>8}{7:>8}{8:>8}{0:>8}\n"
           + "*PART\nsprings\n" + _row(5, 5, 5)
           + "*SECTION_DISCRETE\n" + _row(5) + _row(0.0, 0.0)
           + "*MAT_SPRING_ELASTIC\n" + _row(5, 100.0))

SHELL = ("*ELEMENT_SHELL\n" + f"{301:>8}{3:>8}{1:>8}{2:>8}{4:>8}{3:>8}\n"
         + "*PART\nshells\n" + _row(3, 3, 1)
         + "*SECTION_SHELL\n" + _row(3, 2) + _row(1.0, 1.0, 1.0, 1.0))

RIGID = ("*ELEMENT_SOLID\n"
         + f"{401:>8}{4:>8}{1:>8}{2:>8}{4:>8}{3:>8}{5:>8}{6:>8}{6:>8}{5:>8}\n"
         + "*PART\nrigid\n" + _row(4, 4, 4)
         + "*SECTION_SOLID\n" + _row(4, 1)
         + "*MAT_RIGID\n" + _row(4, 7.85e-6, 210000.0, 0.3)
         + _row(0, 0, 0) + _row())

MAT = "*MAT_ELASTIC\n" + _row(1, 7.85e-6, 210000.0, 0.3)
TERM = "*CONTROL_TERMINATION\n" + _row(0.01)
CURVE = ("*DEFINE_CURVE\n" + _row(1)
         + f"{0.0:>20}{0.0:>20}\n{1.0:>20}{1.0:>20}\n")

SETS = ("*SET_NODE_LIST\n" + _row(10) + _row(1, 2, 3)
        + "*SET_NODE_LIST\n" + _row(11) + _row(4, 5)
        + "*SET_BEAM\n" + _row(20) + _row(101, 102)
        + "*SET_DISCRETE\n" + _row(21) + _row(201)
        + "*SET_PART_LIST\n" + _row(30) + _row(1, 2))

#: Two local systems with the SAME three nodes and different FLAGs, so the
#: REF x FLAG matrix can be exercised without any other difference.
COORDS = ("*DEFINE_COORDINATE_NODES\n" + _row(70, 1, 2, 3, 0, "X")
          + "*DEFINE_COORDINATE_NODES\n" + _row(71, 1, 2, 3, 1, "X"))


def deck(extra="", body=NODES + BEAMS + MAT + TERM):
    return "*KEYWORD\n" + body + extra + "*END\n"


# ═════════════════════════════════════════════════════════════════════════════
class Dispatch(unittest.TestCase):
    """Every spelling in the batch has to be routed EXPLICITLY.

    ``parser._split_keyword`` strips only a trailing ``_ID`` / ``_TITLE``, so
    ``_SET`` and ``_LOCAL`` are part of the BASE keyword and there is no prefix
    fallback for ``DATABASE_``: a missing row is not a degraded conversion, it
    is a silent ``skipped_keywords`` entry. The lists are generated from ONE
    source so HANDLERS and _OFFSET_SPECS cannot drift apart (#116).
    """

    #: The complete R14.1/R15.0 dictionary for the family this batch touches,
    #: as (base keyword, legal option suffixes). There is NO _TITLE anywhere in
    #: *DATABASE_HISTORY_* and no _SET_ID, so those spellings are deliberately
    #: absent.
    HISTORY = [
        ("DATABASE_HISTORY_BEAM", ("", "_ID")),
        ("DATABASE_HISTORY_BEAM_SET", ("",)),
        ("DATABASE_HISTORY_DISCRETE", ("", "_ID")),
        ("DATABASE_HISTORY_DISCRETE_SET", ("",)),
        ("DATABASE_HISTORY_SEATBELT", ("", "_ID")),
        ("DATABASE_HISTORY_NODE", ("", "_ID")),
        ("DATABASE_HISTORY_NODE_SET", ("",)),
        ("DATABASE_HISTORY_NODE_LOCAL", ("", "_ID")),
        ("DATABASE_HISTORY_NODE_SET_LOCAL", ("",)),
        ("DATABASE_HISTORY_SHELL", ("", "_ID")),
        ("DATABASE_HISTORY_SHELL_SET", ("",)),
        ("DATABASE_HISTORY_SOLID", ("", "_ID")),
        ("DATABASE_HISTORY_SOLID_SET", ("",)),
        ("DATABASE_HISTORY_TSHELL", ("", "_ID")),
        ("DATABASE_HISTORY_TSHELL_SET", ("",)),
        ("DATABASE_HISTORY_SPH", ("",)),
        ("DATABASE_HISTORY_SPH_SET", ("",)),
    ]
    OTHER = [
        ("DATABASE_NODAL_FORCE_GROUP", ("", "_TITLE")),
        ("DATABASE_RBDOUT", ("",)),
        ("DATABASE_BNDOUT", ("",)),
        ("DATABASE_NODFOR", ("",)),
        ("DATABASE_TPRINT", ("",)),
        ("CONTROL_PARALLEL", ("",)),
        ("SET_DISCRETE", ("", "_TITLE")),
        ("SET_DISCRETE_LIST", ("", "_TITLE")),
    ]

    def test_every_base_keyword_has_a_handler(self):
        for base, _opts in self.HISTORY + self.OTHER:
            with self.subTest(base):
                self.assertIn(base, HANDLERS)

    def test_every_history_base_keyword_has_an_offset_row(self):
        """A keyword with a handler but no _OFFSET_SPECS row converts fine and
        then silently keeps its ORIGINAL ids under *INCLUDE_TRANSFORM."""
        for base, _opts in self.HISTORY:
            with self.subTest(base):
                self.assertIn(base, _OFFSET_SPECS)
        self.assertIn("DATABASE_NODAL_FORCE_GROUP", _OFFSET_SPECS)

    def test_the_id_less_cards_are_declared_id_less(self):
        """RBDOUT / BNDOUT / NODFOR / TPRINT / CONTROL_PARALLEL carry only
        counts and flags. Without the declaration *INCLUDE_TRANSFORM warns
        "id offsets are NOT applied" on a card that has no ids to apply them
        to."""
        from k2rad.assembly import _NO_ID_KEYWORDS
        for kw in ("DATABASE_RBDOUT", "DATABASE_BNDOUT", "DATABASE_NODFOR",
                   "DATABASE_TPRINT", "CONTROL_PARALLEL"):
            with self.subTest(kw):
                self.assertIn(kw, _NO_ID_KEYWORDS)
                self.assertNotIn(kw, _OFFSET_SPECS)

    def test_every_option_suffix_reaches_the_base_handler(self):
        """The suffix stack, exercised end to end: an unrouted spelling lands
        in skipped_keywords with no warning at all."""
        for base, opts in self.HISTORY + self.OTHER:
            for opt in opts:
                kw = base + opt
                with self.subTest(kw):
                    state = _dispatch(f"*KEYWORD\n*{kw}\n" + _row(1) + "*END\n")
                    self.assertEqual(state.skipped_keywords, [], kw)

    def test_history_is_not_matched_by_a_shorter_spelling(self):
        """_SET and _LOCAL are part of the base keyword, so
        *DATABASE_HISTORY_NODE_SET must NOT be read as *DATABASE_HISTORY_NODE
        (which would treat the SET id as a node id: starter ERROR 78)."""
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_NODE_SET\n"
                          + _row(10) + "*END\n")
        self.assertEqual([d.db_type for d in state.db_histories], ["NODE_SET"])


# ═════════════════════════════════════════════════════════════════════════════
class CardLayouts(unittest.TestCase):
    """*DATABASE_HISTORY_* card reading: plain / _SET / _ID / _LOCAL[_ID]."""

    def test_the_plain_card_is_eight_ids_per_line(self):
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_BEAM\n"
                          + _row(1, 2, 3, 4, 5, 6, 7, 8) + _row(9) + "*END\n")
        self.assertEqual(state.db_histories[0].ids, list(range(1, 10)))

    def test_the_id_card_fuses_the_id_and_the_heading(self):
        """THE YARIS DEFECT. ``   5000390Left Rear Seat`` free-splits to
        ``5000390Left``, to_int returns 0, and EVERY id was dropped — after
        which the writer emitted an empty /TH/NODE (starter ERROR 1109).
        Columns 1-10 are the id; 11-80 are the description."""
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_NODE_ID\n"
                          + f"{5000390:>10}" + "Left Rear Seat\n"
                          + f"{5000398:>10}" + "Right Rear Seat\n"
                          + "*END\n")
        dbh = state.db_histories[0]
        self.assertEqual(dbh.ids, [5000390, 5000398])
        self.assertEqual(dbh.names, ["Left Rear Seat", "Right Rear Seat"])

    def test_the_id_card_still_reads_a_free_format_deck(self):
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_NODE_ID\n"
                          + "  12  some label\n*END\n")
        self.assertEqual(state.db_histories[0].ids, [12])
        self.assertEqual(state.db_histories[0].names, ["some label"])

    def test_the_local_card_reads_id_cid_ref(self):
        """Card 1c, Vol I R16 p.16-113: ID(1-10) CID(11-20) REF(21-30)
        HFO(31-40). HFO selects LS-DYNA's nodouthf file and has no Radioss
        counterpart at all, so it is read by the layout and not stored."""
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_NODE_LOCAL\n"
                          + _row(3, 70, 2, 1) + _row(4, 71, 0, 0) + "*END\n")
        dbh = state.db_histories[0]
        self.assertEqual(dbh.ids, [3, 4])
        self.assertEqual(dbh.cids, [70, 71])
        self.assertEqual(dbh.refs, [2, 0])

    def test_the_local_id_pair_is_claimed_by_raw_contiguity(self):
        """#119. The HEADING card is positional — LS-DYNA reads the line
        IMMEDIATELY after each entity card — and a BLANK one is legal. The
        parser keeps blanks as "" placeholders which the row filter drops, so
        taking "the next filtered row" as the heading would swallow the
        FOLLOWING ENTITY CARD and lose that channel."""
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_NODE_LOCAL_ID\n"
                          + _row(3, 70, 2, 0) + "first node\n"
                          + _row(4, 71, 1, 0) + "\n"          # BLANK heading
                          + _row(5, 0, 0, 0) + "third node\n"
                          + "*END\n")
        dbh = state.db_histories[0]
        self.assertEqual(dbh.ids, [3, 4, 5])
        self.assertEqual(dbh.cids, [70, 71, 0])
        self.assertEqual(dbh.refs, [2, 1, 0])
        self.assertEqual(dbh.names, ["first node", "", "third node"])

    def test_a_blank_or_zero_id_is_dropped(self):
        """LS-DYNA pads the eight-per-line card with zeros (rod.k writes
        ``1 0 0 0 0 0 0 0``); a 0 in a /TH group is not a request."""
        state = _dispatch("*KEYWORD\n*DATABASE_HISTORY_BEAM_SET\n"
                          + _row(20, 0, 0, 0, 0, 0, 0, 0) + "*END\n")
        self.assertEqual(state.db_histories[0].ids, [20])


# ═════════════════════════════════════════════════════════════════════════════
class BeamHistory(unittest.TestCase):
    """*DATABASE_HISTORY_BEAM[_SET] -> /TH/BEAM (+ /TH/SPRING)."""

    def test_the_group_is_column_exact(self):
        """th_beam.cfg FORMAT(radioss51): ``%10d`` + TEN BLANK COLUMNS +
        ``%-80s``. Anything in columns 11-20 is WARNING 100214 and the value is
        silently dropped."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_BEAM\n" + _row(101, 102)))
        blk = _block(starter, "/TH/BEAM/")
        self.assertEqual(blk[1], "TH_BEAM_1")
        self.assertEqual(_var_line(blk), "DEF       ")
        ids = _rows(blk)
        self.assertEqual([_col_i(ln, 1, 10) for ln in ids], [101, 102])
        self.assertTrue(all(len(ln.rstrip()) <= 10 for ln in ids), ids)

    def test_the_id_heading_reaches_the_elem_name_column(self):
        """/TH/BEAM name starts at column 21 — columns 11-20 stay BLANK,
        because that is where /TH/NODE keeps its skew and /TH/BEAM has no such
        field (writing one is WARNING 100214)."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_BEAM_ID\n"
                  + f"{101:>10}" + "left rail beam\n"))
        ln = _rows(_block(starter, "/TH/BEAM/"))[0]
        self.assertEqual(_col_i(ln, 1, 10), 101)
        self.assertEqual(ln[10:20], " " * 10)
        self.assertEqual(ln[20:], "left rail beam")

    def test_the_set_form_expands_a_beam_set(self):
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_HISTORY_BEAM_SET\n" + _row(20)))
        ids = [_col_i(ln, 1, 10) for ln in _rows(_block(starter, "/TH/BEAM/"))]
        self.assertEqual(ids, [101, 102])

    def test_the_set_form_expands_a_part_set(self):
        """database_history_beam_set.cfg:25 takes SET_COMPONENT_IDPOOL as well
        as SET_BEAM_IDPOOL, and a part set means every beam of those parts."""
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_HISTORY_BEAM_SET\n" + _row(30)))
        ids = [_col_i(ln, 1, 10) for ln in _rows(_block(starter, "/TH/BEAM/"))]
        self.assertEqual(ids, [101, 102])

    def test_an_unresolved_set_is_named_not_written_through(self):
        """dyna2rad's *SET_PART_LIST branch keys on the literal string
        "*SET_PART_LIST_TITLE", so a plain *SET_PART_LIST falls through and its
        PART ids are pushed as ELEMENT ids — a lost channel turned into a
        starter refusal."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_BEAM_SET\n" + _row(999)))
        self.assertNotIn("/TH/BEAM", starter)
        self.assertTrue(_warns(result, "set id(s) [999] resolve to no "
                                       "converted *SET_BEAM"), result.warnings)

    def test_a_dangling_beam_id_is_screened_out(self):
        """The #106 rule. hm_read_thgrne.F:187-193 -> ERROR 69 (TH ELEMENT
        SELECTION ID=n DOES NOT EXIST) refuses the WHOLE deck; losing the
        channel is strictly better than losing the run."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_BEAM\n" + _row(101, 999)))
        ids = [_col_i(ln, 1, 10) for ln in _rows(_block(starter, "/TH/BEAM/"))]
        self.assertEqual(ids, [101])
        hits = _warns(result, "not an emitted /BEAM or /SPRING")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 69", hits[0])

    def test_a_group_that_screens_to_nothing_is_not_written(self):
        """An empty TH group is starter ERROR 1109 in its own right."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_BEAM\n" + _row(998, 999)))
        self.assertNotIn("/TH/BEAM", starter)
        self.assertNotIn("/TH/SPRING", starter)

    def test_a_beam_that_became_a_spring_lands_in_the_spring_group(self):
        """dyna2rad picks the target PER ELEMENT through FindRadElement's
        /BEAM -> /SPRING -> /TRUSS chain (convertutils.cxx:298-312, re-init
        INSIDE the loop). k2rad needs two of the three: an *ELEMENT_BEAM on a
        *SECTION_BEAM ELFORM=6 part is emitted as a /SPRING, so ONE card
        produces BOTH groups."""
        body = (NODES
                + "*ELEMENT_BEAM\n"
                + f"{101:>8}{1:>8}{1:>8}{2:>8}{3:>8}\n"
                + f"{102:>8}{6:>8}{7:>8}{8:>8}{0:>8}\n"
                + "*PART\nbeams\n" + _row(1, 1, 1)
                + "*PART\ndbeams\n" + _row(6, 6, 6)
                + "*SECTION_BEAM\n" + _row(1, 1, 1.0, 2, 1.0)
                + _row(4.0, 4.0, 2.0, 2.0)
                + "*SECTION_BEAM\n" + _row(6, 6)
                + "*MAT_LINEAR_ELASTIC_DISCRETE_BEAM\n"
                + _row(6, 7.85e-6) + _row(100.0, 100.0, 100.0)
                + _row(10.0, 10.0, 10.0)
                + MAT + TERM)
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_BEAM\n" + _row(101, 102), body=body))
        self.assertEqual([_col_i(ln, 1, 10)
                          for ln in _rows(_block(starter, "/TH/BEAM/"))], [101])
        spring = [b for b in _blocks(starter, "/TH/SPRING/")
                  if b[1].startswith("TH_SPRING_")]
        self.assertEqual(len(spring), 1, starter)
        self.assertEqual([_col_i(ln, 1, 10) for ln in _rows(spring[0])], [102])


# ═════════════════════════════════════════════════════════════════════════════
class DiscreteHistory(unittest.TestCase):
    """*DATABASE_HISTORY_DISCRETE[_SET] -> /TH/SPRING."""

    BODY = NODES + BEAMS + SPRINGS + MAT + TERM

    def test_the_group_is_column_exact(self):
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_DISCRETE\n" + _row(201), body=self.BODY))
        blk = _block(starter, "/TH/SPRING/")
        self.assertEqual(_var_line(blk), "DEF       ")
        ids = _rows(blk)
        self.assertEqual([_col_i(ln, 1, 10) for ln in ids], [201])
        self.assertTrue(all(len(ln.rstrip()) <= 10 for ln in ids), ids)

    def test_the_set_form_expands_a_discrete_set(self):
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_HISTORY_DISCRETE_SET\n" + _row(21),
            body=self.BODY))
        self.assertEqual([_col_i(ln, 1, 10)
                          for ln in _rows(_block(starter, "/TH/SPRING/"))],
                         [201])

    def test_a_dangling_discrete_id_is_screened_out(self):
        """dyna2rad's DISCRETE branch is the one element branch with NO
        existence check at all — converttimehistory.cxx:256-261 assigns the raw
        list straight into the group."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_DISCRETE\n" + _row(201, 999),
            body=self.BODY))
        self.assertEqual([_col_i(ln, 1, 10)
                          for ln in _rows(_block(starter, "/TH/SPRING/"))],
                         [201])
        hits = _warns(result, "not an emitted /SPRING")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 69", hits[0])

    def test_the_deforc_superset_qualifier_still_fires(self):
        """It used to read state.skipped_keywords, which the keyword no longer
        reaches now that it has a handler — the qualifier would have gone
        silently dead."""
        result, _, _ = _convert(deck(
            extra="*DATABASE_DEFORC\n" + _row(1.0e-5)
                  + "*DATABASE_HISTORY_DISCRETE\n" + _row(201),
            body=self.BODY))
        self.assertTrue(_warns(result, "the group above is a SUPERSET"),
                        result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
class NodeHistoryAndLocal(unittest.TestCase):
    """The _SET and _LOCAL routes, and the per-node skew_ID column."""

    BODY = NODES + BEAMS + MAT + TERM

    def test_the_node_card_is_column_exact(self):
        """th_node.cfg: ``%10d%10d%-80s`` = id, skew_ID, name. A plain request
        with neither writes the id ALONE, so decks that predate this batch are
        byte-identical."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_NODE\n" + _row(1, 2), body=self.BODY))
        ids = _rows(_block(starter, "/TH/NODE/"))
        self.assertEqual(ids, ["         1", "         2"])

    def test_the_id_heading_lands_after_the_skew_column(self):
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_NODE_ID\n" + f"{1:>10}" + "front left\n",
            body=self.BODY))
        ln = _rows(_block(starter, "/TH/NODE/"))[0]
        self.assertEqual(_col_i(ln, 1, 10), 1)
        self.assertEqual(_col_i(ln, 11, 20), 0)       # global system
        self.assertEqual(ln[20:], "front left")

    def test_an_id_card_that_resolves_to_nothing_writes_no_group(self):
        """THE YARIS DEFECT, second half: with every id lost to the free split
        the writer emitted ``/TH/NODE/1`` with NO entity — starter ERROR
        1109 — on the Yaris and Camry set files."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_NODE_ID\n" + f"{9999:>10}" + "ghost\n",
            body=self.BODY))
        self.assertNotIn("/TH/NODE", starter)
        hits = _warns(result, "are not a node in the converted deck")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 78", hits[0])

    def test_the_set_form_expands_a_node_set(self):
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_HISTORY_NODE_SET\n" + _row(10),
            body=self.BODY))
        self.assertEqual([_col_i(ln, 1, 10)
                          for ln in _rows(_block(starter, "/TH/NODE/"))],
                         [1, 2, 3])

    def test_ref_zero_on_a_fixed_system_uses_the_cid_directly(self):
        """REF=0 is "the local system FIXED for all time"; a
        *DEFINE_COORDINATE_NODES with FLAG=0 is already a /SKEW/FIX under its
        own CID, so nothing has to be synthesized."""
        _, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 70, 0),
            body=self.BODY))
        ln = _rows(_block(starter, "/TH/NODE/"))[0]
        self.assertEqual((_col_i(ln, 1, 10), _col_i(ln, 11, 20)), (1, 70))
        self.assertNotIn("/FRAME/MOV", starter)

    def test_ref_one_keeps_the_moving_skew(self):
        """REF=1 is "the PROJECTION of the node's absolute motion onto the
        local system", and that system "can change orientation according to the
        movement of the three defining nodes" — the co-rotating /SKEW/MOV."""
        _, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 71, 1),
            body=self.BODY))
        ln = _rows(_block(starter, "/TH/NODE/"))[0]
        self.assertEqual(_col_i(ln, 11, 20), 71)
        self.assertIn("/SKEW/MOV/71", starter)
        self.assertNotIn("/FRAME/MOV", starter)

    def test_ref_two_synthesizes_a_frame_mov(self):
        """REF=2 is "the motion of the node, expressed in the local system
        ATTACHED TO NODE N1 of CID" — RELATIVE motion, which is a /FRAME, not a
        /SKEW. The skew_ID column takes either: hm_read_thgrou.F:2560-2588
        scans the skew table and then falls through to the frame table, and the
        starter echoes the column as SKEW(OR FRAME)."""
        _, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 71, 2),
            body=self.BODY))
        frame = _block(starter, "/FRAME/MOV/")
        fid = int(frame[0].rsplit("/", 1)[1])
        # N1 N2 N3 Dir, cols 1-10/11-20/21-30/31-40. Dir (%10s) is a
        # FORMAT(radioss2019) addition and therefore legal at /BEGIN 2022.
        card = [ln for ln in frame[2:] if not ln.startswith("#")][0]
        self.assertEqual((_col_i(card, 1, 10), _col_i(card, 11, 20),
                          _col_i(card, 21, 30)), (1, 2, 3))
        self.assertEqual(card[30:40].strip(), "X")
        ln = _rows(_block(starter, "/TH/NODE/"))[0]
        self.assertEqual(_col_i(ln, 11, 20), fid)
        self.assertNotEqual(fid, 71)

    def test_one_frame_is_synthesized_per_cid_not_per_node(self):
        """Two /FRAME cards with the same id would be starter ERROR 79 over the
        merged /SKEW + /FRAME table."""
        _, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n"
                  + _row(1, 71, 2) + _row(2, 71, 2) + _row(3, 71, 2),
            body=self.BODY))
        self.assertEqual(len(_blocks(starter, "/FRAME/MOV/")), 1)
        skews = [_col_i(ln, 11, 20)
                 for ln in _rows(_block(starter, "/TH/NODE/"))]
        self.assertEqual(len(set(skews)), 1)

    def test_two_cards_on_one_cid_share_one_synthesized_frame(self):
        """The per-CID cache lives on the STATE, not on one call: two
        *DATABASE_HISTORY_NODE_LOCAL cards naming the same CID would otherwise
        each mint an identical twin under a fresh id out of the shared
        /SKEW+/FRAME namespace."""
        _, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 71, 2)
                  + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(2, 71, 2),
            body=self.BODY))
        frames = _blocks(starter, "/FRAME/MOV/")
        self.assertEqual(len(frames), 1, starter)
        fid = int(frames[0][0].rsplit("/", 1)[1])
        groups = _blocks(starter, "/TH/NODE/")
        self.assertEqual(len(groups), 2)
        for g in groups:
            self.assertEqual(_col_i(_rows(g)[0], 11, 20), fid)

    def test_a_second_build_re_emits_every_frame_it_references(self):
        """The per-CID cache is owned by ONE build. A state-level cache would
        make a second build_starter on the same state reference a frame it did
        not write — every /RBODY and /SPRING registry in this batch is a set
        and therefore idempotent, but an id cache is not."""
        from k2rad.writer.assembly import build_starter
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck(
                extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n"
                      + _row(1, 71, 2), body=self.BODY))
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        build_starter(state)
        second = build_starter(state)
        tmp.cleanup()
        fid = _col_i(_rows(_block(second, "/TH/NODE/"))[0], 11, 20)
        self.assertIn(f"/FRAME/MOV/{fid}", second.splitlines())

    def test_the_synthesized_frame_id_dodges_the_skew_namespace(self):
        """/SKEW and /FRAME share ONE starter id space (UDOUBLE over the
        combined table)."""
        _, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 71, 2),
            body=self.BODY))
        used = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
                if ln.startswith(("/SKEW/", "/FRAME/"))]
        self.assertEqual(len(used), len(set(used)), used)

    def test_ref_zero_on_a_corotating_system_freezes_it_and_writes_back(self):
        """LS-DYNA calls the combination invalid ("If CID is nonzero, FLAG ...
        must be set to 0"), and REF wins: a /SKEW/FIX frozen from the t=0 node
        positions. dyna2rad builds the same frozen skew and then NEVER writes
        its id back (converttimehistory.cxx:468-507 has no assignment, unlike
        :424 and :461), so its group silently keeps the co-rotating system and
        the new card is orphaned."""
        result, starter, _ = _convert(deck(
            extra=COORDS + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 71, 0),
            body=self.BODY))
        ln = _rows(_block(starter, "/TH/NODE/"))[0]
        skew = _col_i(ln, 11, 20)
        self.assertNotEqual(skew, 71)                  # written back
        self.assertNotEqual(skew, 0)
        self.assertIn(f"/SKEW/FIX/{skew}", starter)    # and not orphaned
        self.assertTrue(_warns(result, "REF=0"), result.warnings)

    def test_an_unresolved_cid_becomes_the_global_system(self):
        """dyna2rad writes the raw CID through when the lookup fails
        (converttimehistory.cxx:400), which dangles into ERROR 434 (WRONG SKEW
        SYSTEM OR REFERENCE FRAME ID) and refuses the whole deck."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 777, 1),
            body=self.BODY))
        ln = _rows(_block(starter, "/TH/NODE/"))[0]
        self.assertEqual(_col_i(ln, 11, 20), 0)
        hits = _warns(result, "CID [777] names no converted")
        self.assertTrue(hits, result.warnings)
        self.assertIn("ERROR 434", hits[0])

    def test_the_set_local_form_carries_each_sets_own_cid(self):
        """dyna2rad compares the CID column length against the EXPANDED entity
        count and, on the inevitable mismatch, broadcasts DH_cid[0] to every
        entity of every set while discarding REF entirely
        (converttimehistory.cxx:382-391). One card LINE names one set and
        carries THAT set's CID."""
        _, starter, _ = _convert(deck(
            extra=COORDS + SETS + "*DATABASE_HISTORY_NODE_SET_LOCAL\n"
                  + _row(10, 70, 1) + _row(11, 0, 0),
            body=self.BODY))
        # ONE card, so ONE group — but the two card LINES name two sets with
        # different CIDs, and each set's nodes keep their own.
        skews = {_col_i(ln, 1, 10): _col_i(ln, 11, 20)
                 for ln in _rows(_block(starter, "/TH/NODE/"))}
        self.assertEqual(skews, {1: 70, 2: 70, 3: 70, 4: 0, 5: 0})


# ═════════════════════════════════════════════════════════════════════════════
class Seatbelt(unittest.TestCase):
    """*DATABASE_HISTORY_SEATBELT: recognized, honestly not emitted."""

    def test_nothing_is_emitted_and_the_gap_is_named(self):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_SEATBELT\n" + _row(1, 2, 3)))
        self.assertNotIn("/TH/", starter)
        self.assertEqual(result.skipped_keywords, [])
        notes = dict(result.recognized_not_emitted)
        self.assertIn("DATABASE_HISTORY_SEATBELT", notes)
        note = notes["DATABASE_HISTORY_SEATBELT"]
        self.assertIn("*ELEMENT_SEATBELT", note)
        self.assertIn("ERROR 69", note)
        self.assertIn("seatbelt", note.lower())


# ═════════════════════════════════════════════════════════════════════════════
class NodalForceGroup(unittest.TestCase):
    """*DATABASE_NODAL_FORCE_GROUP[_TITLE] -> /TH/NODE."""

    BODY = NODES + BEAMS + MAT + TERM

    def test_the_seven_variables_are_written_in_ten_char_cells(self):
        """convertcards.cxx:1042-1045, verbatim, with Number_Of_Variables
        hard-coded to 7. TH variable names are read in FIXED 10-char columns,
        not free format."""
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 0),
            body=self.BODY))
        blk = _block(starter, "/TH/NODE/")
        var = _var_line(blk)
        self.assertEqual(len(var), 70)
        self.assertEqual([var[i:i + 10].strip() for i in range(0, 70, 10)],
                         ["DEF", "REACX", "REACY", "REACZ",
                          "REACXX", "REACYY", "REACZZ"])

    def test_the_cid_becomes_the_per_node_skew_column(self):
        _, starter, _ = _convert(deck(
            extra=COORDS + SETS + "*DATABASE_NODAL_FORCE_GROUP\n"
                  + _row(10, 70), body=self.BODY))
        rows = _rows(_block(starter, "/TH/NODE/"))
        self.assertEqual([(_col_i(ln, 1, 10), _col_i(ln, 11, 20))
                          for ln in rows], [(1, 70), (2, 70), (3, 70)])

    def test_a_blank_cid_is_an_explicit_zero_column(self):
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10),
            body=self.BODY))
        self.assertEqual([_col_i(ln, 11, 20)
                          for ln in _rows(_block(starter, "/TH/NODE/"))],
                         [0, 0, 0])

    def test_the_title_option_names_the_group(self):
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_NODAL_FORCE_GROUP_TITLE\n"
                  + "left rail cut\n" + _row(10, 0), body=self.BODY))
        self.assertEqual(_block(starter, "/TH/NODE/")[1], "left rail cut")

    def test_without_the_title_option_the_name_is_the_dyna2rad_literal(self):
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 0),
            body=self.BODY))
        self.assertEqual(_block(starter, "/TH/NODE/")[1],
                         "DATABASE NODAL FORCE GROUP NSET 10")

    def test_a_blank_nsid_is_warned_not_dropped_in_silence(self):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_NODAL_FORCE_GROUP\n" + _row(0, 0),
            body=self.BODY))
        self.assertNotIn("/TH/NODE", starter)
        self.assertTrue(_warns(result, "NSID is blank or 0"), result.warnings)

    def test_an_unresolved_nsid_is_warned(self):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_NODAL_FORCE_GROUP\n" + _row(99, 0),
            body=self.BODY))
        self.assertNotIn("/TH/NODE", starter)
        self.assertTrue(_warns(result, "no converted *SET_NODE with that id"),
                        result.warnings)

    def test_the_free_body_caveat_is_stated(self):
        """LS-DYNA nodfor is a free-body cut; Radioss REAC* is the KINEMATIC
        CONSTRAINT reaction and is identically zero on an unconstrained node.
        dyna2rad maps them onto each other with no comment at all."""
        result, _, _ = _convert(deck(
            extra=SETS + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 0),
            body=self.BODY))
        hits = _warns(result, "FREE-BODY CUT")
        self.assertTrue(hits, result.warnings)
        self.assertIn("impulse", hits[0])
        self.assertIn("*DATABASE_CROSS_SECTION", hits[0])

    def test_each_card_gets_its_own_group(self):
        """dyna2rad never merges: every source card gets its own CreateEntity,
        and the same node may legitimately appear in several /TH/NODE groups
        because the variable sets differ."""
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 0)
                  + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(11, 0),
            body=self.BODY))
        self.assertEqual(len(_blocks(starter, "/TH/NODE/")), 2)


# ═════════════════════════════════════════════════════════════════════════════
class Rbdout(unittest.TestCase):
    """*DATABASE_RBDOUT -> /TH/RBODY over every emitted /RBODY."""

    BODY = NODES + BEAMS + RIGID + MAT + TERM

    def test_the_id_list_is_ten_per_line_with_no_name_column(self):
        """th_rbody.cfg is a FREE_CELL_LIST, not the one-id-per-line layout the
        element groups use — and it has no name and no skew column at all."""
        rigid_parts = "".join(
            "*ELEMENT_SOLID\n"
            + f"{400 + k:>8}{40 + k:>8}{1:>8}{2:>8}{4:>8}{3:>8}"
              f"{5:>8}{6:>8}{6:>8}{5:>8}\n"
            + f"*PART\nrigid {k}\n" + _row(40 + k, 4, 40 + k)
            + "*MAT_RIGID\n" + _row(40 + k, 7.85e-6, 210000.0, 0.3)
            + _row(0, 0, 0) + _row()
            for k in range(12))
        _, starter, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5),
            body=NODES + rigid_parts + "*SECTION_SOLID\n" + _row(4, 1)
                 + MAT + TERM))
        rows = _rows(_block(starter, "/TH/RBODY/"))
        self.assertEqual(len(rows), 2)                 # 12 ids -> 10 + 2
        self.assertEqual(len(rows[0]), 100)
        self.assertEqual(len(rows[1]), 20)
        ids = [int(rows[0][i:i + 10]) for i in range(0, 100, 10)]
        ids += [int(rows[1][i:i + 10]) for i in range(0, 20, 10)]
        self.assertEqual(len(ids), 12)
        self.assertEqual(len(set(ids)), 12)

    def test_no_leading_zero_is_ever_written(self):
        """hm_read_thgrki_rbody.F:123-125: a leading id of 0 makes the reader
        loop over the WHOLE /RBODY table instead of the requested list."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5), body=self.BODY))
        rows = _rows(_block(starter, "/TH/RBODY/"))
        self.assertNotEqual(int(rows[0][:10]), 0)

    def test_the_group_lists_the_emitted_rbody_ids(self):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5), body=self.BODY))
        emitted = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                   if ln.startswith("/RBODY/")}
        rows = _rows(_block(starter, "/TH/RBODY/"))
        listed = {int(rows[0][i:i + 10]) for i in range(0, len(rows[0]), 10)}
        self.assertEqual(listed, emitted)
        self.assertTrue(_warns(result, "over all 1 converted rigid body"),
                        result.warnings)

    def test_the_impulse_and_rotation_halves_are_both_named(self):
        """FX..MZ accumulate a*dt (rgbodfp.F:261-266) so the force is d(FX)/dt;
        RX..RZ integrate the angular velocity (rgbodv.F:91-93) and ARE the
        rotation angle. LS-DYNA's rbdout is a MOTION file, so half of the group
        is not what its name suggests."""
        result, _, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5), body=self.BODY))
        hits = _warns(result, "/TH/RBODY")
        self.assertTrue(hits, result.warnings)
        self.assertIn("rgbodfp.F", hits[0])
        self.assertIn("rgbodv.F", hits[0])
        self.assertIn("rotation angle", hits[0])

    def test_a_deck_with_no_rigid_body_writes_no_group(self):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5)))
        self.assertNotIn("/TH/RBODY", starter)
        self.assertTrue(_warns(result, "no /RBODY"), result.warnings)

    def test_the_keyword_no_longer_lands_in_skipped(self):
        """It was an explicit handle_skip row while handlers.py:1568 already
        told users it "maps to /TH/RBODY"."""
        result, _, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5), body=self.BODY))
        self.assertEqual([k for k in result.skipped_keywords if "RBDOUT" in k],
                         [])


# ═════════════════════════════════════════════════════════════════════════════
class RbodyProducerReach(unittest.TestCase):
    """Every /RBODY producer must be reachable from *DATABASE_RBDOUT.

    A missed producer is a MISSING channel, and rbody_info (the obvious
    stand-in) misses three ways: the implicit probe body is not in it, a
    CNRB/part id collision drops one record, and a *CONSTRAINED_RIGID_BODIES
    merge aliases several keys onto one main node.
    """

    def _listed(self, extra_body):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5), body=extra_body))
        emitted = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                   if ln.startswith("/RBODY/")}
        blocks = _blocks(starter, "/TH/RBODY/")
        listed = set()
        for blk in blocks:
            for ln in _rows(blk):
                listed |= {int(ln[i:i + 10]) for i in range(0, len(ln), 10)}
        return emitted, listed, result

    def test_mat_rigid_parts_are_reachable(self):
        emitted, listed, _ = self._listed(NODES + BEAMS + RIGID + MAT + TERM)
        self.assertTrue(emitted)
        self.assertEqual(listed, emitted)

    def test_constrained_nodal_rigid_bodies_are_reachable(self):
        body = (NODES + BEAMS + MAT + TERM
                # PID CID NSID (Vol I R16): CID stays 0, the node set is field 3
                + "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(900, 0, 10)
                + "*SET_NODE_LIST\n" + _row(10) + _row(1, 2, 3))
        emitted, listed, _ = self._listed(body)
        self.assertTrue(emitted)
        self.assertEqual(listed, emitted)

    def test_part_inertia_bodies_are_reachable(self):
        body = (NODES + BEAMS + MAT + TERM
                + "*ELEMENT_SOLID\n"
                + f"{401:>8}{4:>8}{1:>8}{2:>8}{4:>8}{3:>8}"
                  f"{5:>8}{6:>8}{6:>8}{5:>8}\n"
                + "*PART_INERTIA\nrigid inertia\n"
                + _row(4, 4, 4) + _row(1.0, 1.0, 1.0, 2.5)
                + _row(1.0, 0.0, 0.0, 1.0, 0.0, 1.0) + _row(0.0, 0.0, 0.0)
                + "*SECTION_SOLID\n" + _row(4, 1)
                + "*MAT_RIGID\n" + _row(4, 7.85e-6, 210000.0, 0.3)
                + _row(0, 0, 0) + _row())
        emitted, listed, _ = self._listed(body)
        self.assertTrue(emitted)
        self.assertEqual(listed, emitted)

    def test_the_element_free_cog_master_is_reachable(self):
        """The default rigid-body master is a SYNTHESIZED element-free node at
        the part's nodal centroid, so the /RBODY id is not any deck node."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_RBDOUT\n" + _row(1.0e-5),
            body=NODES + BEAMS + RIGID + MAT + TERM))
        rbody_ids = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                     if ln.startswith("/RBODY/")}
        self.assertTrue(rbody_ids)
        self.assertTrue(min(rbody_ids) > 8, rbody_ids)   # not a deck node
        rows = _rows(_block(starter, "/TH/RBODY/"))
        listed = {int(rows[0][i:i + 10]) for i in range(0, len(rows[0]), 10)}
        self.assertEqual(listed, rbody_ids)

    def test_the_implicit_probe_body_is_reachable(self):
        """It is appended straight to rbody_lines and never reaches
        rbody_info, so a *DATABASE_RBDOUT deck whose ONLY rigid body is the
        probe would get NO group if the dict were the source."""
        implicit = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01)
                    + "*CONTROL_TERMINATION\n" + _row(1.0))
        emitted, listed, _ = self._listed(
            NODES + BEAMS + MAT + implicit)
        self.assertEqual(len(emitted), 1, emitted)
        self.assertEqual(listed, emitted)


# ═════════════════════════════════════════════════════════════════════════════
class SpringProducerReach(unittest.TestCase):
    """Every /SPRING producer must be visible to the ERROR-69 screen.

    SEVEN producers, three id sources. The three per-database registries
    (discrete / spotweld-beam / discrete-beam) each answer ONE LS-DYNA card and
    must not report the others' elements; ``state.spring_elem_ids`` answers
    "does a /SPRING with this id exist?", which is the question the
    *DATABASE_HISTORY_DISCRETE and _BEAM screens have to ask before naming an
    id. A producer missing from it silently DROPS a user's requested channel;
    a stale id in it refuses the whole deck with ERROR 69.

    Each test parses the emitted /SPRING rows out of the starter TEXT — an
    independent check, not the registry reporting on itself — and asserts the
    registry covers them exactly, plus the id this producer wrote.
    """

    def _run(self, body, **opts):
        """(state, starter) from ONE build, so the registry and the emitted
        text can never come from different runs."""
        from k2rad.writer.assembly import build_starter
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck(body=body))
        state = ConversionState()
        for k, v in opts.items():
            setattr(state.options, k, v)
        for block in parse_k_file(path):
            dispatch(block, state)
        starter = build_starter(state)
        tmp.cleanup()
        return state, starter

    def _check(self, body, expect_id=None, **opts):
        state, starter = self._run(body, **opts)
        emitted = _emitted_spring_ids(starter)
        self.assertTrue(emitted, "the deck emitted no /SPRING at all")
        self.assertEqual(emitted, set(state.spring_elem_ids),
                         emitted ^ set(state.spring_elem_ids))
        if expect_id is not None:
            self.assertIn(expect_id, emitted)
        return emitted

    def test_1_element_discrete_springs_are_registered(self):
        self._check(NODES + BEAMS + SPRINGS + MAT + TERM, 201)

    def test_2_spotweld_beam_springs_are_registered(self):
        self._check(
            NODES + MAT + TERM
            + "*ELEMENT_BEAM\n" + f"{801:>8}{8:>8}{1:>8}{2:>8}{3:>8}\n"
            + "*PART\nwelds\n" + _row(8, 8, 8)
            + "*SECTION_BEAM\n" + _row(8, 9, 1.0, 2, 1.0)
            + _row(4.0, 4.0, 2.0, 2.0)
            + "*MAT_SPOTWELD\n" + _row(8, 7.85e-6, 210000.0, 0.3, 400.0)
            + _row(0.0, 0.0, 1000.0, 1000.0), 801)

    def test_3_discrete_beam_springs_are_registered(self):
        self._check(
            NODES + MAT + TERM
            + "*ELEMENT_BEAM\n" + f"{901:>8}{9:>8}{7:>8}{8:>8}{0:>8}\n"
            + "*PART\ndbeams\n" + _row(9, 9, 9)
            + "*SECTION_BEAM\n" + _row(9, 6)
            + "*MAT_LINEAR_ELASTIC_DISCRETE_BEAM\n"
            + _row(9, 7.85e-6) + _row(100.0, 100.0, 100.0)
            + _row(10.0, 10.0, 10.0), 901)

    def test_4_plotel_springs_are_registered(self):
        """PLOTELs keep their SOURCE eid, so they share the /SPRING id
        namespace with the real connectors — and state.py deliberately keeps
        them out of the three per-database sets, which is exactly why a
        separate "does this /SPRING exist?" registry is needed."""
        self._check(NODES + BEAMS + MAT + TERM
                    + "*ELEMENT_PLOTEL\n" + f"{701:>8}{7:>8}{8:>8}\n", 701)

    def test_5_grounding_springs_are_registered(self):
        """--ground-springs mints its id with next_id(), so it matches no
        LS-DYNA element and was recorded nowhere before this batch."""
        emitted = self._check(
            NODES + BEAMS + RIGID + MAT + TERM
            + "*LOAD_RIGID_BODY\n" + _row(4, 1, 1, 1.0) + CURVE,
            ground_springs=True)
        self.assertTrue(any(e > 90000 for e in emitted), emitted)

    def test_6_constrained_spotweld_tie_springs_are_registered(self):
        emitted = self._check(NODES + BEAMS + SHELL + MAT + TERM
                              + "*CONSTRAINED_SPOTWELD\n"
                              + _row(1, 2, 1000.0, 1000.0))
        self.assertTrue(any(e > 90000 for e in emitted), emitted)

    def test_7_joint_springs_are_registered(self):
        emitted = self._check(NODES + BEAMS + RIGID + MAT + TERM
                              + "*CONSTRAINED_JOINT_SPHERICAL\n" + _row(1, 2))
        self.assertTrue(any(e > 90000 for e in emitted), emitted)

    def test_a_history_request_resolves_a_synthesized_spring(self):
        """The consequence of the registry, end to end: a PLOTEL id named by a
        *DATABASE_HISTORY_DISCRETE must survive the ERROR-69 screen."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_DISCRETE\n" + _row(701),
            body=NODES + BEAMS + MAT + TERM
                 + "*ELEMENT_PLOTEL\n" + f"{701:>8}{7:>8}{8:>8}\n"))
        blk = _blocks(starter, "/TH/SPRING/")[0]
        self.assertEqual([_col_i(ln, 1, 10) for ln in _rows(blk)], [701])

    def test_the_beam_registry_excludes_the_connector_families(self):
        """state.beam_elem_ids must be the EMITTED /BEAM rows, not
        state.beam_elems: a beam on a *MAT_SPOTWELD or ELFORM=6 part is a
        /SPRING, and a beam whose PID has no *PART record is emitted nowhere.
        Deriving the set from the parsed list would route a /SPRING id into a
        /TH/BEAM group — still ERROR 69, because SET_USRTOS is a per-FAMILY
        map and an id that exists as a different element type returns 0."""
        state, starter = self._run(
            NODES + MAT + TERM
            + "*ELEMENT_BEAM\n"
            + f"{101:>8}{1:>8}{1:>8}{2:>8}{3:>8}\n"
            + f"{901:>8}{9:>8}{7:>8}{8:>8}{0:>8}\n"
            + "*PART\nbeams\n" + _row(1, 1, 1)
            + "*PART\ndbeams\n" + _row(9, 9, 9)
            + "*SECTION_BEAM\n" + _row(1, 1, 1.0, 2, 1.0)
            + _row(4.0, 4.0, 2.0, 2.0)
            + "*SECTION_BEAM\n" + _row(9, 6)
            + "*MAT_LINEAR_ELASTIC_DISCRETE_BEAM\n"
            + _row(9, 7.85e-6) + _row(100.0, 100.0, 100.0)
            + _row(10.0, 10.0, 10.0))
        self.assertEqual({b.eid for b in state.beam_elems}, {101, 901})
        self.assertEqual(state.beam_elem_ids, {101})
        self.assertEqual(_emitted_spring_ids(starter), {901})


# ═════════════════════════════════════════════════════════════════════════════
class Bndout(unittest.TestCase):
    """*DATABASE_BNDOUT -> /TH/NODE REAC* over the imposed-motion nodes."""

    MOTION = ("*BOUNDARY_PRESCRIBED_MOTION_SET\n" + _row(10, 1, 2, 1, 1.0)
              + CURVE)
    BODY = NODES + BEAMS + MAT + TERM

    def test_the_group_carries_the_six_reac_names_and_no_def(self):
        """dyna2rad.cxx:454, verbatim: six variables, no DEF. The rotational
        trio is gated on a prescribed motion actually driving a rotational
        dof, the same discipline the SPC block applies."""
        _, starter, _ = _convert(deck(
            extra=SETS + self.MOTION + "*DATABASE_BNDOUT\n" + _row(1.0e-5),
            body=self.BODY))
        blk = [b for b in _blocks(starter, "/TH/NODE/")
               if b[1] == "TH_NODE_BNDOUT"]
        self.assertEqual(len(blk), 1, starter)
        var = _var_line(blk[0])
        self.assertEqual([var[i:i + 10].strip()
                          for i in range(0, len(var), 10)],
                         ["REACX", "REACY", "REACZ"])

    def test_a_rotational_motion_adds_the_angular_channels(self):
        rot = ("*BOUNDARY_PRESCRIBED_MOTION_SET\n" + _row(10, 5, 2, 1, 1.0)
               + CURVE)
        _, starter, _ = _convert(deck(
            extra=SETS + rot + "*DATABASE_BNDOUT\n" + _row(1.0e-5),
            body=self.BODY))
        blk = [b for b in _blocks(starter, "/TH/NODE/")
               if b[1] == "TH_NODE_BNDOUT"][0]
        var = _var_line(blk)
        self.assertEqual([var[i:i + 10].strip()
                          for i in range(0, len(var), 10)],
                         ["REACX", "REACY", "REACZ",
                          "REACXX", "REACYY", "REACZZ"])

    def test_the_scope_is_the_driven_nodes(self):
        _, starter, _ = _convert(deck(
            extra=SETS + self.MOTION + "*DATABASE_BNDOUT\n" + _row(1.0e-5),
            body=self.BODY))
        blk = [b for b in _blocks(starter, "/TH/NODE/")
               if b[1] == "TH_NODE_BNDOUT"][0]
        self.assertEqual([_col_i(ln, 1, 10) for ln in _rows(blk)], [1, 2, 3])

    def test_a_zero_scale_row_is_not_in_scope(self):
        """sf == 0 means "fix this dof" and k2rad folds it into a /BCS instead
        of an /IMP* — that is dyna2rad's SPCFORC scope, not its BNDOUT one."""
        fixed = "*BOUNDARY_PRESCRIBED_MOTION_SET\n" + _row(10, 1, 2, 1, 0.0)
        result, starter, _ = _convert(deck(
            extra=SETS + fixed + CURVE + "*DATABASE_BNDOUT\n" + _row(1.0e-5),
            body=self.BODY))
        self.assertNotIn("TH_NODE_BNDOUT", starter)
        self.assertTrue(_warns(result, "drives no node with a prescribed "
                                       "motion"), result.warnings)

    def test_a_deck_with_no_prescribed_motion_writes_no_group(self):
        result, starter, _ = _convert(deck(
            extra="*DATABASE_BNDOUT\n" + _row(1.0e-5), body=self.BODY))
        self.assertNotIn("TH_NODE_BNDOUT", starter)
        self.assertTrue(_warns(result, "*DATABASE_SPCFORC"), result.warnings)

    def test_a_dangling_scope_node_can_never_reach_the_group(self):
        """The scope is recorded AT the /IMP* emission point, so a row the
        writer warned about and dropped contributes nothing — a /TH/NODE naming
        an undefined node is starter ERROR 78."""
        bad = ("*SET_NODE_LIST\n" + _row(12) + _row(1, 4242)
               + "*BOUNDARY_PRESCRIBED_MOTION_SET\n" + _row(12, 1, 2, 1, 1.0)
               + CURVE)
        _, starter, _ = _convert(deck(
            extra=bad + "*DATABASE_BNDOUT\n" + _row(1.0e-5), body=self.BODY))
        blk = [b for b in _blocks(starter, "/TH/NODE/")
               if b[1] == "TH_NODE_BNDOUT"][0]
        self.assertEqual([_col_i(ln, 1, 10) for ln in _rows(blk)], [1])

    def test_the_rigid_form_reaches_the_rbody_main_node(self):
        body = NODES + BEAMS + RIGID + MAT + TERM
        motion = ("*BOUNDARY_PRESCRIBED_MOTION_RIGID\n" + _row(4, 1, 2, 1, 1.0)
                  + CURVE)
        _, starter, _ = _convert(deck(
            extra=motion + "*DATABASE_BNDOUT\n" + _row(1.0e-5), body=body))
        blk = [b for b in _blocks(starter, "/TH/NODE/")
               if b[1] == "TH_NODE_BNDOUT"][0]
        mains = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                 if ln.startswith("/RBODY/")}
        self.assertEqual({_col_i(ln, 1, 10) for ln in _rows(blk)}, mains)


# ═════════════════════════════════════════════════════════════════════════════
class TprintAndNodfor(unittest.TestCase):
    """The two cards that pace something (or nothing) rather than select it."""

    def test_tprint_emits_nothing_and_says_why(self):
        """k2rad converts NO thermal keyword, so the TEMP channels dyna2rad
        switches on would read all-zero (/MAT/ELAST) or a frozen 300
        (/MAT/PLAS_JOHNS) — a flat fringe that looks like data. The starter's
        own diagnostic for the TH half is WARNING 1087; there is none at all
        for the ANIM half."""
        result, starter, engine = _convert(deck(
            extra="*DATABASE_TPRINT\n" + _row(1.0e-5)))
        self.assertNotIn("TEMP", starter)
        self.assertNotIn("TEMP", engine)
        notes = dict(result.recognized_not_emitted)
        self.assertIn("DATABASE_TPRINT", notes)
        self.assertIn("WARNING 1087", notes["DATABASE_TPRINT"])

    def test_tprint_does_not_pace_the_tfile(self):
        """The documented /TFILE membership rule: a card with no /TH consumer
        stays out, or it only thickens the T01 for channels that are not in
        it. TPRINT's dt is the SMALLEST here, so an accidental inclusion is
        immediately visible."""
        _, _, engine = _convert(deck(
            extra="*DATABASE_NODOUT\n" + _row(1.0e-3)
                  + "*DATABASE_TPRINT\n" + _row(1.0e-9)))
        tfile = engine.splitlines()[engine.splitlines().index("/TFILE") + 1]
        self.assertEqual(float(tfile), 1.0e-3)

    def test_nodfor_paces_the_nodal_force_group(self):
        """*DATABASE_NODAL_FORCE_GROUP has no DT of its own — "the output
        interval must be specified using *DATABASE_NODFOR"."""
        _, _, engine = _convert(deck(
            extra=SETS + "*DATABASE_NODOUT\n" + _row(1.0e-3)
                  + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 0)
                  + "*DATABASE_NODFOR\n" + _row(2.5e-6),
            body=NODES + BEAMS + MAT + TERM))
        tfile = engine.splitlines()[engine.splitlines().index("/TFILE") + 1]
        self.assertEqual(float(tfile), 2.5e-6)

    def test_bndout_and_rbdout_pace_the_tfile(self):
        body = NODES + BEAMS + RIGID + MAT + TERM
        _, _, engine = _convert(deck(
            extra="*DATABASE_NODOUT\n" + _row(1.0e-3)
                  + "*DATABASE_RBDOUT\n" + _row(4.0e-6),
            body=body))
        tfile = engine.splitlines()[engine.splitlines().index("/TFILE") + 1]
        self.assertEqual(float(tfile), 4.0e-6)

    def test_nodfor_alone_is_reported_as_an_interval_only_card(self):
        result, _, _ = _convert(deck(extra="*DATABASE_NODFOR\n" + _row(1.0e-5)))
        notes = dict(result.recognized_not_emitted)
        self.assertIn("DATABASE_NODFOR", notes)
        self.assertIn("*DATABASE_NODAL_FORCE_GROUP", notes["DATABASE_NODFOR"])

    def test_nodfor_before_the_group_card_is_not_reported_as_orphaned(self):
        """The two keywords may appear in either order, and every r14 deck
        writes the *DATABASE_ frequency block FIRST. A handler-side "do I have
        a group card yet?" test therefore reported a deck that DOES carry one
        as having none — measured on
        introduction/example-06/ex_06_beam_elform_1.k, which emitted the
        /TH/NODE group and the "no group card" note at the same time."""
        result, starter, _ = _convert(deck(
            extra="*DATABASE_NODFOR\n" + _row(1.0e-5)
                  + SETS + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 0),
            body=NODES + BEAMS + MAT + TERM))
        self.assertIn("/TH/NODE/", starter)
        self.assertNotIn("DATABASE_NODFOR",
                         dict(result.recognized_not_emitted))


# ═════════════════════════════════════════════════════════════════════════════
class ControlParallel(unittest.TestCase):
    """*CONTROL_PARALLEL -> engine /PARITH."""

    def test_const_one_is_parith_on(self):
        _, _, engine = _convert(deck(
            extra="*CONTROL_PARALLEL\n" + _row(4, 0, 1, 0)))
        self.assertIn("/PARITH/ON", engine.splitlines())
        self.assertNotIn("/PARITH/OFF", engine.splitlines())

    def test_const_two_is_parith_off(self):
        _, _, engine = _convert(deck(
            extra="*CONTROL_PARALLEL\n" + _row(4, 0, 2, 0)))
        self.assertIn("/PARITH/OFF", engine.splitlines())

    def test_a_blank_const_is_parith_off(self):
        _, _, engine = _convert(deck(extra="*CONTROL_PARALLEL\n" + _row(4)))
        self.assertIn("/PARITH/OFF", engine.splitlines())

    def test_const_one_on_any_card_wins(self):
        """convertcards.cxx:978-986 ORs across every card; a later CONST=2
        cannot turn it back off."""
        _, _, engine = _convert(deck(
            extra="*CONTROL_PARALLEL\n" + _row(4, 0, 2, 0)
                  + "*CONTROL_PARALLEL\n" + _row(4, 0, 1, 0)))
        self.assertIn("/PARITH/ON", engine.splitlines())

    def test_no_card_means_no_card(self):
        """dyna2rad creates /PARITH unconditionally and defaults it to OFF
        (convertcards.cxx:973-974), which silently FLIPS OpenRadioss's own
        default of ON (contrl.F:400 IPARI0=1) on every deck it converts —
        including decks that say nothing about parallelism."""
        _, _, engine = _convert(deck())
        self.assertNotIn("/PARITH", engine)

    def test_the_card_is_header_only(self):
        """FORMAT(radioss51) HEADER("/PARITH/%s", KEYWORD2) — no data card. An
        optional trailing integer is clamped away by rdresa.F:309 anyway."""
        _, _, engine = _convert(deck(
            extra="*CONTROL_PARALLEL\n" + _row(4, 0, 1, 0)))
        lines = engine.splitlines()
        self.assertEqual(lines[lines.index("/PARITH/ON") + 1], "#")

    def test_the_dropped_fields_are_named(self):
        result, _, _ = _convert(deck(
            extra="*CONTROL_PARALLEL\n" + _row(8, 1, 1, 2)))
        hits = _warns(result, "no OpenRadioss counterpart, DROPPED")
        self.assertTrue(hits, result.warnings)
        for f in ("NCPU", "NUMRHS", "PARA"):
            self.assertIn(f, hits[0])

    def test_the_implicit_veto_is_named(self):
        """lectur.F:681 resets PARITH/ON to OFF on an implicit run."""
        implicit = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01)
                    + "*CONTROL_TERMINATION\n" + _row(1.0))
        result, _, _ = _convert(deck(
            extra="*CONTROL_PARALLEL\n" + _row(4, 0, 1, 0),
            body=NODES + BEAMS + MAT + implicit))
        hits = _warns(result, "/PARITH/ON")
        self.assertTrue(hits, result.warnings)
        self.assertIn("IMPLICIT", hits[0])


# ═════════════════════════════════════════════════════════════════════════════
class GroupIdNamespace(unittest.TestCase):
    """/TH group ids are unique across the WHOLE time-history namespace."""

    def test_a_deck_using_every_new_route_has_no_duplicate_group_id(self):
        """Measured: four /TH/... blocks on id 1 give three x ERROR ID 79
        (DUPLICATE ID / IN TH GROUP DEFINITION) and error termination."""
        body = NODES + BEAMS + SPRINGS + SHELL + RIGID + MAT + TERM
        extra = (COORDS + SETS
                 + "*DATABASE_HISTORY_BEAM\n" + _row(101, 102)
                 + "*DATABASE_HISTORY_BEAM_SET\n" + _row(20)
                 + "*DATABASE_HISTORY_DISCRETE\n" + _row(201)
                 + "*DATABASE_HISTORY_NODE_LOCAL\n" + _row(1, 70, 0)
                 + "*DATABASE_HISTORY_NODE_SET_LOCAL\n" + _row(11, 71, 2)
                 + "*DATABASE_HISTORY_SHELL\n" + _row(301)
                 + "*DATABASE_NODAL_FORCE_GROUP\n" + _row(10, 70)
                 + "*DATABASE_RBDOUT\n" + _row(1.0e-5)
                 + "*DATABASE_BNDOUT\n" + _row(1.0e-5)
                 + "*BOUNDARY_PRESCRIBED_MOTION_SET\n" + _row(10, 1, 2, 1, 1.0)
                 + CURVE)
        result, starter, _ = _convert(deck(extra=extra, body=body))
        heads = _th_headers(starter)
        ids = [int(h.rsplit("/", 1)[1]) for h in heads]
        self.assertGreaterEqual(len(ids), 8, heads)
        self.assertEqual(len(ids), len(set(ids)), heads)
        self.assertEqual(_warns(result, "is emitted by more than one"), [])

    def test_the_batch_groups_draw_from_next_id(self):
        """The three new sections must not use a literal or a private counter:
        a hard-coded /TH/INTER/1 already cost this converter an ERROR 79 with
        no restart file (PR #83)."""
        body = NODES + BEAMS + RIGID + MAT + TERM
        _, starter, _ = _convert(deck(
            extra=SETS + "*DATABASE_RBDOUT\n" + _row(1.0e-5), body=body))
        rb = _block(starter, "/TH/RBODY/")
        self.assertGreater(int(rb[0].rsplit("/", 1)[1]), 90000)


# ═════════════════════════════════════════════════════════════════════════════
class OffsetSpecs(unittest.TestCase):
    """*INCLUDE_TRANSFORM id offsets. The offset walk and the handler must
    agree on which raw line is a card (#119) or the ids move in one and not in
    the other."""

    OFF = {"n": 1000, "e": 30, "p": 30, "m": 40, "s": 500, "f": 60, "d": 7000,
           "r": 80}

    def _off(self, keyword: str, body: str):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n" + keyword + "\n" + body + "*END\n")
        base = keyword[1:]
        # parse_k_file strips a trailing _ID/_TITLE into Block.options
        blocks = [b for b in parse_k_file(path)
                  if keyword[1:].startswith(b.keyword)]
        assert len(blocks) == 1, blocks
        _offset_block(blocks[0], _OFFSET_SPECS[blocks[0].keyword], self.OFF,
                      lambda m: None)
        tmp.cleanup()
        del base
        return blocks[0].raw

    def test_the_plain_card_takes_the_element_offset(self):
        raw = self._off("*DATABASE_HISTORY_BEAM", _row(101, 102))
        self.assertEqual([_col_i(raw[0], 1, 10), _col_i(raw[0], 11, 20)],
                         [131, 132])

    def test_the_set_card_takes_the_SET_offset(self):
        raw = self._off("*DATABASE_HISTORY_BEAM_SET", _row(20))
        self.assertEqual(_col_i(raw[0], 1, 10), 520)

    def test_the_node_card_takes_the_NODE_offset(self):
        raw = self._off("*DATABASE_HISTORY_NODE", _row(1, 2))
        self.assertEqual([_col_i(raw[0], 1, 10), _col_i(raw[0], 11, 20)],
                         [1001, 1002])

    def test_the_id_card_offsets_the_id_and_keeps_the_heading(self):
        """A flat spec starts at _title_offset, which is 1 for the _ID option —
        so the FIRST entity card was skipped while the handler read it. And
        _rewrite_line cannot touch the card at all: _split_card sees the space
        inside the heading and field 0 becomes ``5000390Left``."""
        raw = self._off("*DATABASE_HISTORY_NODE_ID",
                        f"{5000390:>10}" + "Left Rear Seat\n"
                        + f"{5000398:>10}" + "Right Rear Seat\n")
        self.assertEqual(len(raw), 2)
        self.assertEqual(_col_i(raw[0], 1, 10), 5001390)
        self.assertEqual(raw[0][10:], "Left Rear Seat")
        self.assertEqual(_col_i(raw[1], 1, 10), 5001398)
        self.assertEqual(raw[1][10:], "Right Rear Seat")

    def test_the_local_card_offsets_the_id_and_the_cid_only(self):
        """REF (field 2) and HFO (field 3) are flags, not ids — an (ALL, ...)
        spec would rewrite REF=2 into REF=1002."""
        raw = self._off("*DATABASE_HISTORY_NODE_LOCAL", _row(3, 70, 2, 1))
        self.assertEqual(_col_i(raw[0], 1, 10), 1003)     # + IDNOFF
        self.assertEqual(_col_i(raw[0], 11, 20), 7070)    # + IDDOFF
        self.assertEqual(_col_i(raw[0], 21, 30), 2)       # REF untouched
        self.assertEqual(_col_i(raw[0], 31, 40), 1)       # HFO untouched

    def test_the_local_id_heading_card_is_stridden_by_raw_contiguity(self):
        """The heading card holds no ids. Stepping onto it would try to offset
        the text; stepping over "the next filtered row" instead of the RAW next
        line would skip a real entity card whenever a heading is blank."""
        raw = self._off("*DATABASE_HISTORY_NODE_LOCAL_ID",
                        _row(3, 70, 2, 0) + "first node\n"
                        + _row(4, 71, 1, 0) + "\n"
                        + _row(5, 0, 0, 0) + "third node\n")
        self.assertEqual(_col_i(raw[0], 1, 10), 1003)
        self.assertEqual(raw[1], "first node")
        self.assertEqual(_col_i(raw[2], 1, 10), 1004)
        self.assertEqual(_col_i(raw[2], 11, 20), 7071)
        self.assertEqual(raw[3], "")
        self.assertEqual(_col_i(raw[4], 1, 10), 1005)
        self.assertEqual(raw[5], "third node")

    def test_the_nodal_force_group_offsets_nsid_and_cid(self):
        raw = self._off("*DATABASE_NODAL_FORCE_GROUP", _row(10, 70))
        self.assertEqual([_col_i(raw[0], 1, 10), _col_i(raw[0], 11, 20)],
                         [510, 7070])

    def test_the_titled_nodal_force_group_keeps_its_title_line(self):
        raw = self._off("*DATABASE_NODAL_FORCE_GROUP_TITLE",
                        "left rail cut\n" + _row(10, 70))
        self.assertEqual(raw[0], "left rail cut")
        self.assertEqual([_col_i(raw[1], 1, 10), _col_i(raw[1], 11, 20)],
                         [510, 7070])

    def test_the_offset_walk_and_the_handler_read_the_same_rows(self):
        """The #119 invariant, asserted directly: offset a block, then dispatch
        the SAME block, and check every id moved by exactly its bucket."""
        for kw, body, bucket in (
                ("*DATABASE_HISTORY_BEAM", _row(101, 102), "e"),
                ("*DATABASE_HISTORY_BEAM_SET", _row(20), "s"),
                ("*DATABASE_HISTORY_NODE_ID",
                 f"{7:>10}" + "seat\n", "n"),
                ("*DATABASE_HISTORY_NODE_LOCAL", _row(3, 70, 2, 0), "n"),
        ):
            with self.subTest(kw):
                before = _dispatch("*KEYWORD\n" + kw + "\n" + body + "*END\n")
                raw = self._off(kw, body)
                state = ConversionState()
                tmp = tempfile.TemporaryDirectory()
                path = os.path.join(tmp.name, "d.k")
                with open(path, "w") as fh:
                    fh.write("*KEYWORD\n" + kw + "\n" + "\n".join(raw)
                             + "\n*END\n")
                for block in parse_k_file(path):
                    dispatch(block, state)
                tmp.cleanup()
                self.assertEqual(
                    [i + self.OFF[bucket] for i in before.db_histories[0].ids],
                    state.db_histories[0].ids, kw)


# ═════════════════════════════════════════════════════════════════════════════
class ByteIdentity(unittest.TestCase):
    """A deck WITHOUT any of the new keywords must be byte-identical."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures"

    def test_the_golden_fixtures_are_unchanged(self):
        """The five checked-in fixtures carry no keyword from this batch, so
        every line of both decks must still match. (test_golden.py compares
        them too; this states the batch's own contract.)"""
        for stem in ("implicit_qstat", "rigid_contact", "shell_explicit",
                     "solid_plastic", "tied_weld"):
            src = self.FIXTURES / f"{stem}.k"
            if not src.is_file():
                self.skipTest(f"fixture {stem}.k not present")
            with self.subTest(stem):
                tmp = tempfile.TemporaryDirectory()
                out = os.path.join(tmp.name, stem)
                result = convert(str(src), output_stem=out, write_log=False)
                for suffix, path in (("_0000.rad", result.starter_path),
                                     ("_0001.rad", result.engine_path)):
                    exp = self.FIXTURES / "expected" / f"{stem}{suffix}"
                    if not exp.is_file():
                        continue
                    self.assertEqual(open(path).read(), exp.read_text(),
                                     f"{stem}{suffix}")
                tmp.cleanup()

    def test_a_plain_history_node_deck_writes_the_bare_id_card(self):
        """The skew and name columns are written ONLY when there is something
        to put in them, so a pre-batch deck's /TH/NODE card is unchanged."""
        _, starter, _ = _convert(deck(
            extra="*DATABASE_HISTORY_NODE\n" + _row(1, 2, 3),
            body=NODES + BEAMS + MAT + TERM))
        self.assertEqual(_rows(_block(starter, "/TH/NODE/")),
                         ["         1", "         2", "         3"])

    def test_no_parith_and_no_extra_group_on_a_bare_deck(self):
        _, starter, engine = _convert(deck())
        self.assertNotIn("/PARITH", engine)
        self.assertNotIn("/TH/", starter)


if __name__ == "__main__":
    unittest.main()
