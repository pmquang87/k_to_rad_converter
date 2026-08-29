"""Tests for MILESTONE-2 BATCH 1 (beyond dyna2rad parity):

  *SET_<FAMILY>_ADD[_TITLE]         → conversion-time boolean UNION, expanded
                                      into the family's ordinary set container
  *SET_NODE_ADD_ADVANCED            → a node union across the seven families
  *MAT_COMPOSITE_DAMAGE (022)       → /MAT/LAW25 (COMPSH) Iform=0 + /FAIL/CHANG
                                      on shells, /MAT/LAW127 on solids

Kept in its own module, the repo's one-module-per-batch convention.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import HANDLERS, dispatch, _set_add_keywords
from k2rad.parser import parse_k_file
from k2rad.state import (ConversionState, SET_ADD_ADVANCED_TYPES,
                         SET_ADD_FAMILIES)
from k2rad.writer.mesh import _SET_ADD_MAX_DEPTH, _flatten_set_adds


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


def _flat(deck: str) -> ConversionState:
    state = _dispatch(deck)
    _flatten_set_adds(state)
    return state


def _block(starter: str, header: str):
    """The lines of the first starter block whose header equals *header*,
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
    body = _block(starter, header)
    if body is None:
        return None
    return [ln for ln in body if not ln.startswith("#")]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _ids_of_group(starter: str, header: str):
    body = _block(starter, header)
    ids = []
    for ln in body[1:]:
        if ln.startswith("#"):
            continue
        ids.extend(int(t) for t in ln.split() if t.lstrip("-").isdigit())
    return ids


def _warns(result, *needles):
    return [w for w in result.warnings if all(n in w for n in needles)]


def _f20(line: str, field: int) -> float:
    """The float in 20-wide column *field* (0-based)."""
    return float(line[field * 20:(field + 1) * 20])


def _col_f(line: str, start: int, end: int) -> float:
    return float(line[start - 1:end])


def _col_i(line: str, start: int, end: int) -> int:
    return int(line[start - 1:end])


# ── Shared deck fragments ────────────────────────────────────────────────────

#: Twelve nodes; one hex (101) on part 1; a QUAD shell (201) and a 3-corner
#: shell (202) on part 2; one beam (301) and one discrete spring (401) on
#: parts 3 and 4. `{EXTRA}` carries the cards under test.
MESH = (
    "*KEYWORD\n"
    "*NODE\n"
    + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
        (4, 0.0, 10.0, 0.0), (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
        (7, 10.0, 10.0, 10.0), (8, 0.0, 10.0, 10.0), (9, 20.0, 0.0, 0.0),
        (10, 20.0, 10.0, 0.0), (11, 30.0, 0.0, 0.0), (12, 30.0, 10.0, 0.0)))
    + "*ELEMENT_SOLID\n"
    + _row(101, 1) + "\n"
    + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
    "*ELEMENT_SHELL\n"
    + _row(201, 2, 2, 3, 10, 9) + "\n"
    + _row(202, 2, 9, 10, 11, 11) + "\n"
    "*ELEMENT_BEAM\n"
    + _row(301, 3, 11, 12, 1) + "\n"
    "*ELEMENT_DISCRETE\n"
    + _row(401, 4, 5, 6, 0, 1.0) + "\n"
    "*PART\n"
    "solid\n"
    + _row(1, 1, 1) + "\n"
    "*SECTION_SOLID\n"
    + _row(1, 1) + "\n"
    "*PART\n"
    "shell\n"
    + _row(2, 2, 1) + "\n"
    "*SECTION_SHELL\n"
    + _row(2, 2, 1.0, 5) + "\n"
    + _row(1.0, 1.0, 1.0, 1.0) + "\n"
    "*PART\n"
    "beam\n"
    + _row(3, 3, 1) + "\n"
    "*SECTION_BEAM\n"
    + _row(3, 1) + "\n"
    + _row(1.0, 1.0, 1.0, 1.0, 1.0, 1.0) + "\n"
    "*PART\n"
    "spring\n"
    + _row(4, 4, 0) + "\n"
    "*SECTION_DISCRETE\n"
    + _row(4, 0) + "\n"
    + _row(0.0, 1.0, 0.0, 0.0) + "\n"
    "*MAT_SPRING_ELASTIC\n"
    + _row(4, 100.0) + "\n"
    "*MAT_ELASTIC\n"
    + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.010\n"
    "*END\n"
)


# ═════════════════════════════════════════════════════════════════════════════
# A. *SET_<FAMILY>_ADD — the spelling grammar
# ═════════════════════════════════════════════════════════════════════════════

class SetAddSpellingTests(unittest.TestCase):
    """The parser table and the *INCLUDE_TRANSFORM offset table are generated
    from ONE source (state.SET_ADD_FAMILIES). A spelling that dispatches but
    has no offset spec silently keeps its un-offset MEMBER SET ids under an
    *INCLUDE_TRANSFORM while the member sets themselves move — the union then
    resolves to nothing; one with a spec but no handler is a bag that never
    inflates."""

    def test_parser_and_offset_tables_cover_the_same_set(self):
        expect = set(_set_add_keywords()) | {"SET_NODE_ADD_ADVANCED"}
        self.assertEqual(expect - set(HANDLERS), set())
        self.assertEqual(expect - set(_OFFSET_SPECS), set())

    def test_every_family_row_is_registered(self):
        for family, kw, ncells, adds, target in SET_ADD_FAMILIES:
            with self.subTest(family=family):
                self.assertIn(kw, HANDLERS)
                self.assertIn(kw, _OFFSET_SPECS)
                self.assertTrue(hasattr(ConversionState(), adds))
                self.assertTrue(hasattr(ConversionState(), target))
                self.assertIn(ncells, (1, 2, 6))

    def test_tshell_add_is_not_a_keyword(self):
        """*SET_TSHELL_ADD is in NEITHER the R17 nor the R16 *SET chapter
        index — it exists only in HyperMesh's cfg pool
        (Keyword971/SETS/tshell_add.cfg:60). It must not be invented: a deck
        carrying it stays in skipped_keywords, named."""
        self.assertNotIn("SET_TSHELL_ADD", [r[1] for r in SET_ADD_FAMILIES])
        self.assertNotIn("SET_TSHELL_ADD", HANDLERS)
        self.assertNotIn("SET_TSHELL_ADD", _OFFSET_SPECS)
        deck = MESH.replace("{EXTRA}",
                            "*SET_TSHELL_ADD\n" + _row(70) + "\n"
                            + _row(71) + "\n")
        res, _ = _convert(deck)
        self.assertIn("SET_TSHELL_ADD", res.skipped_keywords)

    def test_title_needs_no_key_of_its_own(self):
        """Vol I R17 p.43-2: "an additional keyword option TITLE may be
        appended to all the *SET keywords" — exactly ONE 80a line between the
        header and card 1. parser._split_keyword strips it."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_NODE_LIST\n" + _row(51) + "\n"
                            + _row(1, 2) + "\n"
                            + "*SET_NODE_ADD_TITLE\n"
                            + "RBD_ACTOR_STIFT_CNS_\n"
                            + _row(50) + "\n" + _row(51) + "\n")
        st = _flat(deck)
        self.assertEqual(st.node_sets[50], ("RBD_ACTOR_STIFT_CNS_", [1, 2]))
        res, _ = _convert(deck)
        self.assertEqual(res.skipped_keywords, [])


class SetAddOffsetTests(unittest.TestCase):

    def test_member_cells_take_the_SET_bucket_not_the_entity_one(self):
        """LS-DYNA has ONE set bucket: Vol I R17 *INCLUDE_{OPTION} Card
        2b.1/2b.2 gives "IDSOFF: Offset to set ID" and no per-family split.
        An _ADD's members are SET ids, so they take "s" — where the BASE
        keyword's members take "n"/"e"/"p"."""
        for _family, kw, _n, _a, _t in SET_ADD_FAMILIES:
            with self.subTest(kw=kw):
                spec = _OFFSET_SPECS[kw]
                self.assertEqual(spec["cards"], {0: [(0, "s")]})
                self.assertEqual(spec["data"], (1, [(-1, "s")]))
        # ... and the base keywords still use their own entity buckets.
        self.assertEqual(_OFFSET_SPECS["SET_NODE_LIST"]["data"], (1, [(-1, "n")]))
        self.assertEqual(_OFFSET_SPECS["SET_SHELL"]["data"], (1, [(-1, "e")]))

    def test_advanced_offsets_only_the_odd_cells(self):
        """Card 2b is four (SID, TYPE) PAIRS (Vol I R17 p.43-46). An
        (ALL, "s") spec would offset every TYPE enumeration too and turn a
        "node set" member into a "TYPE 10000002" one."""
        spec = _OFFSET_SPECS["SET_NODE_ADD_ADVANCED"]
        self.assertEqual(spec["data"],
                         (1, [(0, "s"), (2, "s"), (4, "s"), (6, "s")]))

    def test_include_transform_moves_header_and_members_together(self):
        from k2rad.assembly import _offset_block
        from k2rad.parser import Block
        b = Block(keyword="SET_NODE_ADD", options=[],
                  raw=[_row(50), _row(51, 52, 0, 0)])
        _offset_block(b, _OFFSET_SPECS["SET_NODE_ADD"],
                      {"s": 1000, "n": 7, "e": 9}, lambda m: None)
        self.assertEqual([int(t) for t in b.raw[0].split()], [1050])
        # trailing zero padding is NOT a member and must stay 0
        self.assertEqual([int(t) for t in b.raw[1].split()],
                         [1051, 1052, 0, 0])


# ═════════════════════════════════════════════════════════════════════════════
# A. *SET_<FAMILY>_ADD — the union semantics
# ═════════════════════════════════════════════════════════════════════════════

class SetAddUnionTests(unittest.TestCase):

    def test_node_union_dedups_and_keeps_first_seen_order(self):
        deck = MESH.replace("{EXTRA}",
                            "*SET_NODE_LIST\n" + _row(51) + "\n"
                            + _row(1, 2, 3) + "\n"
                            + "*SET_NODE_LIST\n" + _row(52) + "\n"
                            + _row(3, 4, 5) + "\n"
                            + "*SET_NODE_ADD\n"
                            + _row(50, 0.0, 0.0, 0.0, 0.0, "MECH") + "\n"
                            + _row(51, 52, 0, 0, 0, 0, 0, 0) + "\n")
        st = _flat(deck)
        # node 3 is in BOTH children and appears ONCE; the trailing zero
        # padding of the member row is not a member set.
        self.assertEqual(st.node_sets[50][1], [1, 2, 3, 4, 5])

    def test_da_cells_are_read_only_on_node_and_part(self):
        """Card-1 cell counts differ per family (each spelling's own manual
        page): SID DA1..DA4 SOLVER on NODE/PART, SID SOLVER on SEGMENT/SOLID,
        SID alone on SHELL/BEAM/DISCRETE. Reading six cells on a SID-only
        family would take the following blanks as DA1..DA4."""
        counts = {row[0]: row[2] for row in SET_ADD_FAMILIES}
        self.assertEqual(counts["NODE"], 6)
        self.assertEqual(counts["PART"], 6)
        self.assertEqual(counts["SEGMENT"], 2)
        self.assertEqual(counts["SOLID"], 2)
        self.assertEqual(counts["SHELL"], 1)
        self.assertEqual(counts["BEAM"], 1)
        self.assertEqual(counts["DISCRETE"], 1)
        # Only *SET_PART_ADD's DA1..DA4 have a consumer (*CONTACT_INTERIOR).
        deck = MESH.replace("{EXTRA}",
                            "*SET_PART_ADD\n"
                            + _row(60, 0.5, 0.2, 3.0, 2.0) + "\n"
                            + _row(61) + "\n"
                            + "*SET_SHELL_ADD\n" + _row(70) + "\n"
                            + _row(71) + "\n")
        st = _dispatch(deck)
        self.assertEqual(st.part_set_attrs[60], (0.5, 0.2, 3.0, 2.0))
        self.assertNotIn(70, st.part_set_attrs)

    def test_every_family_unions(self):
        """One deck exercising all seven families at once — the shared
        resolver must not have a per-family gap (the #124 lesson: a guard
        gated on one card SPELLING goes dead on its sibling)."""
        extra = (
            "*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
            "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(51) + "\n"
            "*SET_PART_LIST\n" + _row(61) + "\n" + _row(1) + "\n"
            "*SET_PART_ADD\n" + _row(60) + "\n" + _row(61) + "\n"
            "*SET_SHELL_LIST\n" + _row(71) + "\n" + _row(201) + "\n"
            "*SET_SHELL_ADD\n" + _row(70) + "\n" + _row(71) + "\n"
            "*SET_SOLID_LIST\n" + _row(81) + "\n" + _row(101) + "\n"
            "*SET_SOLID_ADD\n" + _row(80) + "\n" + _row(81) + "\n"
            "*SET_BEAM_LIST\n" + _row(91) + "\n" + _row(301) + "\n"
            "*SET_BEAM_ADD\n" + _row(90) + "\n" + _row(91) + "\n"
            "*SET_DISCRETE_LIST\n" + _row(96) + "\n" + _row(401) + "\n"
            "*SET_DISCRETE_ADD\n" + _row(95) + "\n" + _row(96) + "\n"
            "*SET_SEGMENT\n" + _row(86) + "\n" + _row(2, 3, 10, 9) + "\n"
            "*SET_SEGMENT_ADD\n" + _row(85) + "\n" + _row(86) + "\n"
        )
        st = _flat(MESH.replace("{EXTRA}", extra))
        self.assertEqual(st.node_sets[50][1], [1, 2])
        self.assertEqual(st.part_sets[60][1], [1])
        self.assertEqual(st.shell_sets[70][1], [201])
        self.assertEqual(st.solid_sets[80][1], [101])
        self.assertEqual(st.beam_sets[90][1], [301])
        self.assertEqual(st.discrete_sets[95][1], [401])
        self.assertEqual(st.segment_sets[85].segments, [[2, 3, 10, 9]])
        res, _ = _convert(MESH.replace("{EXTRA}", extra))
        self.assertEqual(res.skipped_keywords, [])

    def test_nested_add_of_add_is_expanded_recursively(self):
        extra = ("*SET_NODE_LIST\n" + _row(53) + "\n" + _row(7, 8) + "\n"
                 + "*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_NODE_ADD\n" + _row(52) + "\n" + _row(51) + "\n"
                 + "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(52, 53) + "\n")
        st = _flat(MESH.replace("{EXTRA}", extra))
        self.assertEqual(st.node_sets[50][1], [1, 2, 7, 8])
        self.assertEqual(st.node_sets[52][1], [1, 2])

    def test_cycle_is_cut_and_named(self):
        extra = ("*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(51, 52) + "\n"
                 + "*SET_NODE_ADD\n" + _row(52) + "\n" + _row(50) + "\n")
        res, _ = _convert(MESH.replace("{EXTRA}", extra))
        hits = _warns(res, "reached from itself")
        self.assertTrue(hits)
        self.assertIn("50", hits[0])
        st = _flat(MESH.replace("{EXTRA}", extra))
        # the non-cyclic half survives
        self.assertEqual(st.node_sets[50][1], [1, 2])

    def test_depth_cap_warns_and_drops(self):
        chain = "*SET_NODE_LIST\n" + _row(1000) + "\n" + _row(1, 2) + "\n"
        # 1000 <- 1001 <- ... <- 1000+N, so the top is N levels above the leaf
        n = _SET_ADD_MAX_DEPTH + 3
        for k in range(1, n + 1):
            chain += ("*SET_NODE_ADD\n" + _row(1000 + k) + "\n"
                      + _row(1000 + k - 1) + "\n")
        res, _ = _convert(MESH.replace("{EXTRA}", chain))
        hits = _warns(res, "levels deep")
        self.assertTrue(hits)
        self.assertIn(f"more than {_SET_ADD_MAX_DEPTH} levels", hits[0])
        st = _flat(MESH.replace("{EXTRA}", chain))
        # every link up to the cap resolves; past it the member is dropped,
        # and a union that resolves to nothing is NOT registered as an empty
        # set (see test_empty_union_is_not_registered)
        self.assertEqual(st.node_sets[1001][1], [1, 2])
        self.assertEqual(st.node_sets[1000 + _SET_ADD_MAX_DEPTH][1], [1, 2])
        self.assertNotIn(1000 + n, st.node_sets)

    def test_dangling_member_is_dropped_by_name(self):
        extra = ("*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(51, 59) + "\n")
        res, _ = _convert(MESH.replace("{EXTRA}", extra))
        hits = _warns(res, "*SET_NODE_ADD 50", "member set id(s)")
        self.assertTrue(hits)
        self.assertIn("[59]", hits[0])
        st = _flat(MESH.replace("{EXTRA}", extra))
        # dropped, never written into the group as a dangling member
        self.assertEqual(st.node_sets[50][1], [1, 2])

    def test_direct_set_of_the_same_id_wins(self):
        extra = ("*SET_NODE_LIST\n" + _row(50) + "\n" + _row(9, 10) + "\n"
                 + "*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(51) + "\n")
        res, _ = _convert(MESH.replace("{EXTRA}", extra))
        hits = _warns(res, "direct set with the same id")
        self.assertTrue(hits)
        self.assertIn("_ADD block is IGNORED", hits[0])
        st = _flat(MESH.replace("{EXTRA}", extra))
        self.assertEqual(st.node_sets[50][1], [9, 10])

    def test_empty_union_is_not_registered(self):
        """A union none of whose members resolve is NOT written as an empty
        set: that would claim the deck's union is empty when it is only
        unresolved here, and MEASURED on starter_win64 an empty /GRNOD draws
        "WARNING ID : 690 ... THE NODE GROUP ID=... IS EMPTY" pointing at the
        wrong culprit (0 ERRORS, NORMAL TERMINATION)."""
        extra = ("*SET_NODE_ADD\n" + _row(50) + "\n" + _row(59) + "\n")
        res, starter = _convert(MESH.replace("{EXTRA}", extra))
        st = _flat(MESH.replace("{EXTRA}", extra))
        self.assertNotIn(50, st.node_sets)
        self.assertNotIn("/GRNOD/NODE/50", starter)
        self.assertTrue(_warns(res, "*SET_NODE_ADD 50",
                               "resolves to NO member at all"))

    def test_flatten_is_idempotent(self):
        extra = ("*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(51) + "\n")
        st = _flat(MESH.replace("{EXTRA}", extra))
        before = dict(st.node_sets)
        _flatten_set_adds(st)
        self.assertEqual(st.node_sets, before)


class SegmentUnionDedupTests(unittest.TestCase):
    """/SURF/SEG does NOT de-duplicate: measured on a free-floating /PLOAD
    impulse, the same four nodes on two seg rows applies exactly 2.0000x the
    load at 0 ERROR (only /SURF/DSURF de-duplicates, and k2rad emits the flat
    /SURF/SEG form). So the union has to do it at conversion time."""

    def _seg(self, rows_a, rows_b):
        extra = ("*SET_SEGMENT\n" + _row(86) + "\n"
                 + "".join(_row(*r) + "\n" for r in rows_a)
                 + "*SET_SEGMENT\n" + _row(87) + "\n"
                 + "".join(_row(*r) + "\n" for r in rows_b)
                 + "*SET_SEGMENT_ADD\n" + _row(85) + "\n"
                 + _row(86, 87) + "\n")
        return _flat(MESH.replace("{EXTRA}", extra)).segment_sets[85].segments

    def test_identical_segment_appears_once(self):
        self.assertEqual(self._seg([(2, 3, 10, 9)], [(2, 3, 10, 9)]),
                         [[2, 3, 10, 9]])

    def test_cyclic_rotation_is_the_same_segment(self):
        """A quad 2-3-10-9 and 3-10-9-2 have the same normal and the same
        area — one segment, not two."""
        self.assertEqual(self._seg([(2, 3, 10, 9)], [(3, 10, 9, 2)]),
                         [[2, 3, 10, 9]])

    def test_reversed_segment_is_kept(self):
        """A REVERSED row is the opposite face normal; dropping it would
        silently delete a load direction."""
        self.assertEqual(self._seg([(2, 3, 10, 9)], [(9, 10, 3, 2)]),
                         [[2, 3, 10, 9], [9, 10, 3, 2]])

    def test_distinct_segments_both_survive(self):
        self.assertEqual(self._seg([(2, 3, 10, 9)], [(9, 10, 11, 11)]),
                         [[2, 3, 10, 9], [9, 10, 11, 11]])


class SetNodeAddAdvancedTests(unittest.TestCase):
    """Card 2b is SID1 TYPE1 .. SID4 TYPE4 (Vol I R17 p.43-46), a UNION across
    the seven families whose non-node members contribute THEIR NODES. There is
    no operator column anywhere on the page. dyna2rad matches the substring
    "ADD" and never dispatches on TYPE (convertsets.cxx:103), so there the
    TYPE column is read as another set id."""

    def _adv(self, pairs, extra=""):
        deck = MESH.replace(
            "{EXTRA}",
            extra
            + "*SET_NODE_ADD_ADVANCED\n" + _row(50) + "\n"
            + _row(*[v for p in pairs for v in p]) + "\n")
        return deck

    def test_type_column_is_a_family_not_an_id(self):
        extra = ("*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_SHELL_LIST\n" + _row(71) + "\n" + _row(201) + "\n")
        st = _flat(self._adv([(51, 1), (71, 2)], extra))
        # node set 51 = {1,2}; shell 201 = nodes 2,3,10,9 -> 2 is deduped
        self.assertEqual(st.node_sets[50][1], [1, 2, 3, 10, 9])
        # the TYPE cells were NOT taken as member set ids
        self.assertEqual(sorted(i for i, _t in
                                st.node_set_add_advanced[50][1]), [51, 71])

    def test_each_family_type_contributes_its_nodes(self):
        extra = (
            "*SET_SOLID_LIST\n" + _row(81) + "\n" + _row(101) + "\n"
            "*SET_BEAM_LIST\n" + _row(91) + "\n" + _row(301) + "\n"
            "*SET_DISCRETE_LIST\n" + _row(96) + "\n" + _row(401) + "\n"
            "*SET_SEGMENT\n" + _row(86) + "\n" + _row(9, 10, 11, 11) + "\n"
        )
        st = _flat(self._adv([(81, 4), (91, 3), (96, 6), (86, 5)], extra))
        got = st.node_sets[50][1]
        self.assertEqual(got[:8], [1, 2, 3, 4, 5, 6, 7, 8])   # the hex
        self.assertIn(12, got)                                # beam n2
        self.assertIn(11, got)                                # segment
        self.assertEqual(len(got), len(set(got)))             # deduped

    def test_tshell_type_7_is_warn_dropped_by_name(self):
        res, _ = _convert(self._adv([(77, 7)]))
        hits = _warns(res, "*SET_NODE_ADD_ADVANCED 50", "TYPE=7")
        self.assertTrue(hits)
        self.assertIn("[77]", hits[0])
        self.assertIn("*SET_TSHELL", hits[0])

    def test_undocumented_type_is_warn_dropped_by_name(self):
        res, _ = _convert(self._adv([(77, 9)]))
        hits = _warns(res, "*SET_NODE_ADD_ADVANCED 50", "TYPE=9")
        self.assertTrue(hits)
        self.assertIn("does not define", hits[0])

    def test_advanced_type_table_matches_the_manual(self):
        self.assertEqual(
            {k: v[0] for k, v in SET_ADD_ADVANCED_TYPES.items()},
            {1: "NODE", 2: "SHELL", 3: "BEAM", 4: "SOLID", 5: "SEGMENT",
             6: "DISCRETE", 7: "TSHELL"})


# ═════════════════════════════════════════════════════════════════════════════
# A. The unions reach their CONSUMERS
# ═════════════════════════════════════════════════════════════════════════════

class SetAddConsumerTests(unittest.TestCase):
    """The union id must resolve wherever a plain set id resolves. Before this
    batch a *BOUNDARY_SPC_SET on a *SET_NODE_ADD lost its constraint at ZERO
    starter diagnostics — the /BCS simply was not written."""

    def test_boundary_spc_set_resolves_through_a_node_union(self):
        extra = ("*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n"
                 + "*SET_NODE_LIST\n" + _row(52) + "\n" + _row(3, 4) + "\n"
                 + "*SET_NODE_ADD\n" + _row(50) + "\n" + _row(51, 52) + "\n"
                 + "*BOUNDARY_SPC_SET\n"
                 + _row(50, 0, 1, 1, 1, 1, 1, 1) + "\n")
        res, starter = _convert(MESH.replace("{EXTRA}", extra))
        self.assertFalse(_warns(res, "mapped to empty set"))
        self.assertTrue(_headers(starter, "/BCS/"))
        self.assertEqual(_ids_of_group(starter, "/GRNOD/NODE/50"),
                         [1, 2, 3, 4])

    def test_shell_union_splits_quads_and_trias_per_emission(self):
        """A /GRSHEL/SHEL group may hold only 4-node /SHELL ids; 3-corner
        shells are written as /SH3N and need a /GRSH3N/SH3N."""
        extra = ("*SET_SHELL_LIST\n" + _row(71) + "\n" + _row(201) + "\n"
                 + "*SET_SHELL_LIST\n" + _row(72) + "\n" + _row(202) + "\n"
                 + "*SET_SHELL_ADD\n" + _row(70) + "\n" + _row(71, 72) + "\n"
                 + "*DATABASE_HISTORY_SHELL_SET\n" + _row(70) + "\n")
        res, starter = _convert(MESH.replace("{EXTRA}", extra))
        self.assertFalse(_warns(res, "resolve to no converted"))
        th_shel = _data_rows(starter, "/TH/SHEL/1") or []
        th_sh3n = _data_rows(starter, "/TH/SH3N/2") or []
        self.assertTrue(any("201" in ln for ln in th_shel))
        self.assertTrue(any("202" in ln for ln in th_sh3n))

    def test_segment_union_reaches_a_pressure_load(self):
        extra = ("*SET_SEGMENT\n" + _row(86) + "\n"
                 + _row(2, 3, 10, 9) + "\n"
                 + "*SET_SEGMENT\n" + _row(87) + "\n"
                 + _row(9, 10, 11, 11) + "\n"
                 + "*SET_SEGMENT_ADD\n" + _row(85) + "\n"
                 + _row(86, 87) + "\n"
                 + "*DEFINE_CURVE\n"
                 + _row(901, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
                 + "                 0.0                 0.0\n"
                 + "                0.01                 1.0\n"
                 + "*LOAD_SEGMENT_SET\n" + _row(85, 901, 1.0) + "\n")
        res, starter = _convert(MESH.replace("{EXTRA}", extra))
        # one /PLOAD per (lcid, sf, at) group; BOTH segments of the union
        # land on its /SURF/SEG
        self.assertEqual(len(_headers(starter, "/PLOAD/")), 1)
        surf = _data_rows(starter, "/SURF/SEG/90001")
        self.assertEqual([ln.split() for ln in surf[1:] if ln.strip()],
                         [["1", "2", "3", "10", "9"],
                          ["2", "9", "10", "11", "11"]])
        self.assertEqual(res.skipped_keywords, [])

    def test_part_union_reaches_a_contact_side(self):
        extra = ("*SET_PART_LIST\n" + _row(61) + "\n" + _row(1) + "\n"
                 + "*SET_PART_ADD\n" + _row(60) + "\n" + _row(61) + "\n"
                 + "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                 + _row(60, 0, 2, 0) + "\n" + _row() + "\n" + _row() + "\n")
        res, starter = _convert(MESH.replace("{EXTRA}", extra))
        self.assertFalse(_warns(res, "resolved to no nodes at all"))
        self.assertTrue(_headers(starter, "/INTER/"))


class SetAddNonInterferenceTests(unittest.TestCase):

    def test_deck_without_the_keywords_is_byte_identical(self):
        """The resolver must not touch a deck that carries no union: every
        emitter draws its first id only when its keyword is present."""
        base = MESH.replace("{EXTRA}", "")
        with_sets = MESH.replace(
            "{EXTRA}",
            "*SET_NODE_LIST\n" + _row(51) + "\n" + _row(1, 2) + "\n")
        _res_a, a = _convert(base)
        _res_b, b = _convert(base)
        self.assertEqual(a, b)
        # and a plain *SET_NODE_LIST still emits exactly its own /GRNOD
        _res_c, c = _convert(with_sets)
        self.assertEqual(_ids_of_group(c, "/GRNOD/NODE/51"), [1, 2])
