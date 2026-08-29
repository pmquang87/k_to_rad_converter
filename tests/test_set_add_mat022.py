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


# ═════════════════════════════════════════════════════════════════════════════
# B. *MAT_COMPOSITE_DAMAGE (MAT_022)
# ═════════════════════════════════════════════════════════════════════════════

#: A shell-only MAT_022 deck. Deliberately ASYMMETRIC (EA != EB, and every
#: strength distinct) so a slot swap or a missing Poisson rescale is visible.
#: Values are the tension6.k corpus carrier's, except EC/PRCA, which are given
#: distinct numbers here for the same reason.
#:
#:   EA 38600  EB 8270  EC 5000  PRBA 0.0557  PRCA 0.0411  PRCB 0.49
#:   GAB 4140  GBC 2100  GCA 3100
#:   AOPT 2, a = (1,0,0), d = (0,1,0), BETA 0
#:   SC 72  XT 1062  YT 31  YC 118  ALPH 0
#:
#: Hand-computed: NU12 = PRBA*EA/EB = 0.0557 * 38600/8270 = 0.2599782346...
MAT22_SHELL = (
    "*MAT_COMPOSITE_DAMAGE_TITLE\n"
    "E-GLASS/EPOXY\n"
    + _row(7, "2.20000E-9", 38600.0, 8270.0, 5000.0, 0.0557, 0.0411, 0.49) + "\n"
    + _row(4140.0, 2100.0, 3100.0, 0.0, 2.0, 1, 0) + "\n"
    + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
    + _row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
    + _row(72.0, 1062.0, 31.0, 118.0, 0.0, 0.0, 0.0, 0.0) + "\n")

#: The same material with the SOLID-only extras set, so the drop report has
#: something to name: KFAIL, MACF, ATRACK, ALPH and the SN/SYZ/SZX
#: delamination strengths.
MAT22_FULL = (
    "*MAT_COMPOSITE_DAMAGE\n"
    + _row(7, "2.20000E-9", 38600.0, 8270.0, 5000.0, 0.0557, 0.0411, 0.49) + "\n"
    + _row(4140.0, 2100.0, 3100.0, 1234.0, 2.0, 3, 1) + "\n"
    + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
    + _row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
    + _row(72.0, 1062.0, 31.0, 118.0, "1.5E-7", 40.0, 35.0, 33.0) + "\n")

_MAT22_CARD2 = _row(4140.0, 2100.0, 3100.0, 0.0, 2.0, 1, 0)


def _shell_deck(mat=MAT22_SHELL) -> str:
    """MESH with the SHELL part on mid 7 and everything else on mid 1."""
    deck = MESH.replace("{EXTRA}", mat)
    return deck.replace("shell\n" + _row(2, 2, 1), "shell\n" + _row(2, 2, 7))


def _solid_deck(mat=MAT22_SHELL) -> str:
    """MESH with the SOLID part on mid 7."""
    deck = MESH.replace("{EXTRA}", mat)
    return deck.replace("solid\n" + _row(1, 1, 1), "solid\n" + _row(1, 1, 7))


class Mat022LawRoutingTests(unittest.TestCase):
    """The LAW25-vs-LAW127 split, and the ONE router behind it."""

    def test_shell_only_material_is_law25_plus_fail_chang(self):
        res, starter = _convert(_shell_deck())
        self.assertEqual(res.skipped_keywords, [])
        self.assertTrue(_headers(starter, "/MAT/LAW25/7"))
        self.assertTrue(_headers(starter, "/FAIL/CHANG/7"))
        self.assertFalse(_headers(starter, "/MAT/LAW127/7"))

    def test_solid_material_is_law127_with_no_rider(self):
        res, starter = _convert(_solid_deck())
        self.assertEqual(res.skipped_keywords, [])
        self.assertTrue(_headers(starter, "/MAT/LAW127/7"))
        self.assertFalse(_headers(starter, "/MAT/LAW25/7"))
        self.assertFalse(_headers(starter, "/FAIL/CHANG/7"))
        self.assertTrue(_warns(res, "decouple direction 3"))

    def test_mixed_material_goes_to_law127_and_says_why(self):
        deck = MESH.replace("{EXTRA}", MAT22_SHELL)
        deck = deck.replace("shell\n" + _row(2, 2, 1), "shell\n" + _row(2, 2, 7))
        deck = deck.replace("solid\n" + _row(1, 1, 1), "solid\n" + _row(1, 1, 7))
        res, starter = _convert(deck)
        self.assertTrue(_headers(starter, "/MAT/LAW127/7"))
        # ONE /MAT card per MID: the /MAT id namespace is global across laws
        self.assertEqual(len(_headers(starter, "/MAT/LAW25/7")), 0)
        self.assertTrue(_warns(res, "shared by SHELL and SOLID"))
        self.assertFalse(_warns(res, "MATERIAL ID 7 is emitted by more than"))

    def test_target_mat_law_agrees_with_the_emitter(self):
        """mesh._target_mat_law is the ONE mid->law map (writer/inistate.py
        reads it for the /XREF whitelist), so it must not fork from the
        router."""
        from k2rad.writer.composites import _mat022_law
        from k2rad.writer.mesh import _target_mat_law
        for build in (_shell_deck, _solid_deck):
            st = _dispatch(build())
            with self.subTest(build=build.__name__):
                self.assertEqual(_target_mat_law(st, 7), _mat022_law(st, 7))

    def test_element_free_material_stays_on_law25(self):
        from k2rad.writer.composites import _mat022_law
        st = _dispatch(MESH.replace("{EXTRA}", MAT22_SHELL))
        self.assertEqual(_mat022_law(st, 7), 25)

    def test_thick_shell_material_is_law127_too(self):
        """LAW25's SOLID kernels serve thick shells as well, so the same dir-3
        decoupling applies — a THICK_SHELL part must not be read as "not a
        solid" and fall back to the LAW25 arm."""
        deck = (
            "*KEYWORD\n*NODE\n"
            + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
                (4, 0.0, 10.0, 0.0), (5, 0.0, 0.0, 2.0), (6, 10.0, 0.0, 2.0),
                (7, 10.0, 10.0, 2.0), (8, 0.0, 10.0, 2.0)))
            + "*ELEMENT_TSHELL\n"
            + "".join(f"{v:>8}" for v in (101, 1, 1, 2, 3, 4, 5, 6, 7, 8))
            + "\n*PART\ntshell\n" + _row(1, 1, 7) + "\n"
            "*SECTION_TSHELL\n" + _row(1, 2, 5) + "\n"
            + MAT22_SHELL
            + "*CONTROL_TERMINATION\n     0.010\n*END\n")
        res, starter = _convert(deck)
        self.assertTrue(_headers(starter, "/MAT/LAW127/7"))
        self.assertFalse(_headers(starter, "/MAT/LAW25/7"))
        self.assertEqual(res.skipped_keywords, [])


class Mat022Law25CardTests(unittest.TestCase):
    """Column-exact /MAT/LAW25 layout, from
    ``radioss2019/MAT/matl25_compsh.cfg FORMAT(radioss2019)`` — the newest
    block and the one a /BEGIN 2022 deck reads."""

    def setUp(self):
        _res, self.starter = _convert(_shell_deck())
        self.rows = _data_rows(self.starter, "/MAT/LAW25/7")

    def test_title_and_density(self):
        self.assertEqual(self.rows[0], "E-GLASS/EPOXY")
        self.assertAlmostEqual(_f20(self.rows[1], 0), 2.2e-9, places=15)

    def test_moduli_card_columns(self):
        """E11(20) E22(20) NU12(20) Iform(10) + 10 blanks + E33(20).
        Distinct numbers per slot, so a column swap is visible."""
        ln = self.rows[2]
        self.assertAlmostEqual(_col_f(ln, 1, 20), 38600.0, places=6)
        self.assertAlmostEqual(_col_f(ln, 21, 40), 8270.0, places=6)
        self.assertEqual(_col_i(ln, 61, 70), 0)          # Iform = Tsai-Wu
        self.assertEqual(ln[70:80].strip(), "")          # the cfg's 10 blanks
        self.assertAlmostEqual(_col_f(ln, 81, 100), 5000.0, places=6)

    def test_poisson_is_rescaled_minor_to_major(self):
        """read_mat25_tsaiwu.F90:129 reads MAT_PRAB into n12 and :282 derives
        n21 = n12*e22/e11, so the slot is the MAJOR ratio and needs the LAW93
        rescale — the OPPOSITE of /MAT/LAW127, which takes PRBA verbatim.
        Hand-computed: 0.0557 * 38600/8270 = 0.25997823458...
        A naive 1:1 copy would be wrong by EA/EB = 4.667x."""
        nu12 = _col_f(self.rows[2], 41, 60)
        self.assertAlmostEqual(nu12, 0.0557 * 38600.0 / 8270.0, places=9)
        self.assertNotAlmostEqual(nu12, 0.0557, places=3)

    def test_shear_moduli_are_g12_g23_g31(self):
        ln = self.rows[3]
        self.assertAlmostEqual(_col_f(ln, 1, 20), 4140.0, places=6)    # GAB
        self.assertAlmostEqual(_col_f(ln, 21, 40), 2100.0, places=6)   # GBC
        self.assertAlmostEqual(_col_f(ln, 41, 60), 3100.0, places=6)   # GCA

    def test_every_yield_is_out_of_reach(self):
        """MAT_022 is elastic until brittle failure, but the LAW25 reader
        hard-fails with ancmsg(msgid=198) on ANY of the six yields <= 0
        (read_mat25_tsaiwu.F90:206-241). 1e20 pushes the Tsai-Wu surface out
        of reach; the FAILURE strengths belong on the /FAIL/CHANG rider, not
        in yield slots."""
        card7, card8 = self.rows[7], self.rows[8]
        for f in range(4):                       # sig_1yt 2yt 1yc 2yc
            self.assertAlmostEqual(_f20(card7, f), 1.0e20, delta=1.0e6)
        self.assertAlmostEqual(_f20(card7, 4), 0.0, places=12)      # alpha
        for f in range(2):                       # sig_12yc, sig_12yt
            self.assertAlmostEqual(_f20(card8, f), 1.0e20, delta=1.0e6)

    def test_law25_own_damage_is_switched_off(self):
        """EPS_t*/EPS_m* (tensile-strain damage), Wpmax (plastic work) and
        GAMMA_ini/GAMMA_max (shear delamination) are all left blank, which the
        reader turns into 1e20/1.1e20/0.999 — none can express Chang-Chang,
        and the rider is what carries the failure model."""
        for f in range(5):
            self.assertAlmostEqual(_f20(self.rows[4], f), 0.0, places=12)
        # Wpmax(20) Wpref(20) Ioff(10) + 10 blanks + ratio(20)
        wp = self.rows[5]
        self.assertAlmostEqual(_col_f(wp, 1, 20), 0.0, places=12)
        self.assertAlmostEqual(_col_f(wp, 21, 40), 0.0, places=12)
        self.assertEqual(_col_i(wp, 41, 50), 0)
        self.assertEqual(wp[50:60].strip(), "")
        self.assertAlmostEqual(_col_f(wp, 61, 80), 0.0, places=12)
        for f in range(3):
            self.assertAlmostEqual(_f20(self.rows[9], f), 0.0, places=12)

    def test_zero_modulus_is_warned(self):
        mat = MAT22_SHELL.replace(
            _MAT22_CARD2, _row(4140.0, 0.0, 3100.0, 0.0, 2.0, 1, 0))
        res, _ = _convert(_shell_deck(mat))
        self.assertTrue(_warns(res, "GBC is zero", "ERROR 306"))


class Mat022FailChangTests(unittest.TestCase):
    """The /FAIL/CHANG rider — layout from
    ``radioss2018/FAIL/fail_chang.cfg FORMAT(radioss130)``, the newest block a
    /BEGIN 2022 deck resolves to."""

    def setUp(self):
        self.res, self.starter = _convert(_shell_deck())
        self.rows = _data_rows(self.starter, "/FAIL/CHANG/7")

    def test_strength_columns_are_exact(self):
        """Five 20-wide cells: SIGMA_1T SIGMA_2T SIGMA_12 SIGMA_1C SIGMA_2C.
        Distinct numbers per slot (XT 1062, YT 31, SC 72, YC 118), so a swap
        is visible — note SIGMA_12 sits BETWEEN the two tensile strengths and
        the transverse compressive one is LAST."""
        ln = self.rows[0]
        self.assertAlmostEqual(_col_f(ln, 1, 20), 1062.0, places=6)    # XT
        self.assertAlmostEqual(_col_f(ln, 21, 40), 31.0, places=6)     # YT
        self.assertAlmostEqual(_col_f(ln, 41, 60), 72.0, places=6)     # SC
        self.assertEqual(ln[60:80].strip(), "")                        # 1C
        self.assertAlmostEqual(_col_f(ln, 81, 100), 118.0, places=6)   # YC

    def test_sigma_1c_is_blank_not_invented(self):
        """MAT_022 has NO compressive-fibre strength. hm_read_fail_chang.F90:
        102 turns the blank into infinity, i.e. "that mode never trips" —
        exactly MAT_022. Measured on starter_win64: the echo reads
        LONGITUDINAL COMPRESSIVE STRENGTH (SIGMA1_C) = 1.0000000200409E+20."""
        self.assertEqual(self.rows[0][60:80].strip(), "")

    def test_beta_and_tau_and_ifail_are_written_explicitly(self):
        """All three default to a value that silently changes the physics:
        Beta 0 deletes the shear term from the fibre criterion (there is no
        `if (beta == zero) beta = one` in the reader), a blank Tau_max becomes
        infinity so dmg_scale stays 1 forever, and Ifail_sh 0 gates the whole
        relaxation off (fail_changchang_c.F90:191)."""
        ln = self.rows[1]
        self.assertAlmostEqual(_col_f(ln, 1, 20), 1.0, places=12)
        # Tau_max = 1e-4 * ENDTIM; the MESH fixture terminates at 0.010 s
        self.assertAlmostEqual(_col_f(ln, 21, 40), 1.0e-6, places=15)
        self.assertEqual(_col_i(ln, 41, 50), 2)

    def test_failip_and_fcut_are_not_written(self):
        """FAILIP is a 2023 column and FCUT a 2025 one. MEASURED: a /BEGIN
        2022 deck carrying them draws WARNING 100213 "unsupported field exists
        at the end of line" and reads the value back as 0."""
        self.assertEqual(len(self.rows[1].rstrip()), 50)

    def test_onset_is_the_hand_computed_criterion(self):
        """Hand-check of the EMITTED numbers against Theory Manual R16
        eq 23.22.3/.4/.5 at ALPH = 0, where tau_bar collapses to (t12/SC)^2:

          F_fiber = (s1/XT)^2 + Beta*(t12/SC)^2  reaches 1 at s1 = XT with
          t12 = 0, and at t12 = SC with s1 = 0;
          F_comp  = (s2/2SC)^2 + [(YC/2SC)^2 - 1]*s2/YC reaches 1 at s2 = -YC.

        MEASURED on starter+engine (a 10x10x1 quad built from these very
        cards, /IMPDISP ramp, /TH/SHEL): peak sigma_xx = 2502.248 MPa against
        a hand-computed XT = 2500 (+0.0899 %, inside one 3.938 MPa TH sample),
        then a collapse to zero within 1.6e-6 s of the Tau_max = 1e-7
        relaxation window."""
        ln = self.rows[0]
        xt = _col_f(ln, 1, 20)
        sc = _col_f(ln, 41, 60)
        yc = _col_f(ln, 81, 100)
        beta = _col_f(self.rows[1], 1, 20)
        self.assertAlmostEqual((xt / xt) ** 2 + beta * (0.0 / sc) ** 2,
                               1.0, places=12)
        self.assertAlmostEqual((0.0 / xt) ** 2 + beta * (sc / sc) ** 2,
                               1.0, places=12)
        f_comp = ((-yc / (2 * sc)) ** 2
                  + ((yc / (2 * sc)) ** 2 - 1.0) * (-yc) / yc)
        self.assertAlmostEqual(f_comp, 1.0, places=12)

    def test_no_termination_time_makes_it_an_indicator_and_says_so(self):
        deck = _shell_deck().replace("*CONTROL_TERMINATION\n     0.010\n", "")
        res, starter = _convert(deck)
        rows = _data_rows(starter, "/FAIL/CHANG/7")
        self.assertEqual(_col_i(rows[1], 41, 50), 0)
        self.assertTrue(_warns(res, "no run time scale", "DAMAGE INDEX"))


class Mat022Law127CardTests(unittest.TestCase):

    def setUp(self):
        _res, self.starter = _convert(_solid_deck())
        self.rows = _data_rows(self.starter, "/MAT/LAW127/7")

    def test_poisson_is_raw_not_rescaled(self):
        """hm_read_mat127.F90:127 reads LSDYNA_PRBA into nu21 and :187 derives
        nu12 = nu21*e1/e2 itself, so the LAW25 rescale would be double-applied
        here. The two arms of ONE keyword use OPPOSITE conventions."""
        ln = self.rows[4]
        self.assertAlmostEqual(_col_f(ln, 1, 20), 0.0557, places=9)
        self.assertAlmostEqual(_col_f(ln, 21, 40), 0.0411, places=9)
        self.assertAlmostEqual(_col_f(ln, 41, 60), 0.49, places=9)
        self.assertNotAlmostEqual(_col_f(ln, 1, 20),
                                  0.0557 * 38600.0 / 8270.0, places=3)

    def test_moduli_and_shear_order(self):
        self.assertEqual([_f20(self.rows[2], f) for f in range(3)],
                         [38600.0, 8270.0, 5000.0])
        # LAW127 card order is G12 G13 G23, i.e. GAB GCA GBC
        self.assertEqual([_f20(self.rows[3], f) for f in range(3)],
                         [4140.0, 3100.0, 2100.0])

    def test_strengths_and_the_blank_xc(self):
        self.assertAlmostEqual(_f20(self.rows[5], 0), 1062.0, places=6)  # XT
        self.assertAlmostEqual(_f20(self.rows[6], 0), 31.0, places=6)    # YT
        self.assertAlmostEqual(_f20(self.rows[7], 0), 72.0, places=6)    # SC
        self.assertAlmostEqual(_f20(self.rows[8], 0), 0.0, places=12)    # XC
        self.assertAlmostEqual(_f20(self.rows[9], 0), 118.0, places=6)   # YC

    def test_slim_is_a_vanishing_residual_not_the_readers_one(self):
        """A blank SLIM becomes 1.0 (hm_read_mat127.F90:289-293) and
        sigeps127c.F90:400-403 then clamps the failed mode's stress at 1.0x
        its strength — a perfect-plastic plateau, i.e. an inert failure model.
        MAT_022 zeroes the failed ply's moduli, so the residual is zero."""
        from k2rad.writer.composites import _LAW127_NO_RESIDUAL
        for row in range(5, 10):
            with self.subTest(row=row):
                self.assertAlmostEqual(_f20(self.rows[row], 1),
                                       _LAW127_NO_RESIDUAL, places=15)
        self.assertLess(_LAW127_NO_RESIDUAL, 1.0e-6)

    def test_beta_one_and_ycfac_neutralised(self):
        """BETA has no reader default at all (a blank one is 0 and deletes the
        shear term from the fibre criterion); YCFAC defaults to 2 and
        sigeps127.F90:289 then runs xc = ycfac*yc after matrix-compression
        failure, inventing a compressive-FIBRE limit MAT_022 does not have."""
        from k2rad.writer.composites import _LAW127_NO_YCFAC
        self.assertAlmostEqual(_f20(self.rows[11], 1), 1.0, places=12)
        self.assertAlmostEqual(_f20(self.rows[13], 3), _LAW127_NO_YCFAC,
                               delta=1.0e6)
        self.assertGreater(_LAW127_NO_YCFAC, 1.0e12)

    def test_alph_is_carried_verbatim_and_its_partiality_named(self):
        res, starter = _convert(_solid_deck(MAT22_FULL))
        rows = _data_rows(starter, "/MAT/LAW127/7")
        self.assertAlmostEqual(_f20(rows[11], 0), 1.5e-7, places=15)
        self.assertTrue(_warns(res, "MATRIX-TENSION mode only"))


class Mat022DroppedFieldTests(unittest.TestCase):
    """Every cell with no counterpart is reported BY NAME, from BOTH arms."""

    def test_all_dropped_fields_are_named_on_the_shell_arm(self):
        res, _ = _convert(_shell_deck(MAT22_FULL))
        text = " ".join(_warns(res, "*MAT_COMPOSITE_DAMAGE 7"))
        for needle in ("KFAIL=1234", "MACF=3", "ATRACK=1",
                       "SN=40", "SYZ=35", "SZX=33", "ALPH=1.5e-07"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertIn("*MAT_COMPOSITE_DAMAGE",
                      [kw for kw, _ in res.recognized_not_emitted])

    def test_all_dropped_fields_are_named_on_the_solid_arm(self):
        res, _ = _convert(_solid_deck(MAT22_FULL))
        text = " ".join(_warns(res, "*MAT_COMPOSITE_DAMAGE 7"))
        for needle in ("KFAIL=1234", "MACF=3", "ATRACK=1", "SN=40"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        # ALPH IS carried on this arm, so it is not in the drop list
        self.assertNotIn("nonlinear shear term", text)

    def test_hashin_is_not_substituted_for_the_delamination_mode(self):
        res, starter = _convert(_solid_deck(MAT22_FULL))
        self.assertFalse(_headers(starter, "/FAIL/HASHIN"))
        self.assertTrue(_warns(res, "NOT substituted"))

    def test_a_clean_card_reports_nothing(self):
        res, _ = _convert(_shell_deck())
        self.assertFalse(_warns(res, "*MAT_COMPOSITE_DAMAGE 7", "DROPPED"))


class Mat022AxisAndPropTests(unittest.TestCase):
    """AOPT reaches the /PROP through the SHARED composite axis machinery."""

    def test_aopt2_builds_a_skew_and_ip22(self):
        res, starter = _convert(_shell_deck())
        self.assertTrue(_warns(res, "AOPT=2 global vector a=(1, 0, 0)",
                               "Ip=22"))
        self.assertTrue(_headers(starter, "/SKEW/FIX/"))

    def test_aopt0_and_aopt3_discriminate(self):
        for aopt, needle in ((0.0, "AOPT=0"), (3.0, "AOPT=3 vector v=")):
            mat = MAT22_SHELL.replace(
                _MAT22_CARD2, _row(4140.0, 2100.0, 3100.0, 0.0, aopt, 1, 0))
            if aopt == 3.0:
                mat = mat.replace(_row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                                  _row(0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 15.0))
            res, _ = _convert(_shell_deck(mat))
            with self.subTest(aopt=aopt):
                self.assertTrue(_warns(res, needle))

    def test_negative_aopt_uses_the_define_coordinate_skew(self):
        mat = MAT22_SHELL.replace(
            _MAT22_CARD2, _row(4140.0, 2100.0, 3100.0, 0.0, -55.0, 1, 0))
        deck = _shell_deck(mat).replace(
            "*CONTROL_TERMINATION",
            "*DEFINE_COORDINATE_SYSTEM\n"
            + _row(55, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
            + _row(0.0, 1.0, 0.0) + "\n"
            "*CONTROL_TERMINATION")
        res, _ = _convert(deck)
        self.assertTrue(_warns(res, "*DEFINE_COORDINATE "))

    def test_beta_reaches_the_property_phi(self):
        mat = MAT22_SHELL.replace(
            _row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            _row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 30.0))
        res, _ = _convert(_shell_deck(mat))
        self.assertTrue(_warns(res, "Phi=30deg"))

    def test_part_is_repointed_off_the_isotropic_property(self):
        """Both laws register orthotropic-class in the starter, and IGTYP 1
        accepts only PROP_SHELL 1 or 5 (check_mat_elem_prop_compatibility.F:
        173-176) — ERROR 3047 otherwise."""
        _res, starter = _convert(_shell_deck())
        self.assertTrue(_headers(starter, "/PROP/TYPE11/"))
        _res, starter = _convert(_solid_deck())
        self.assertTrue(_headers(starter, "/PROP/TYPE6/"))

    def test_icomp_angles_reach_the_layered_property(self):
        """*SECTION_SHELL ICOMP=1 layer angles are carried only when the part
        is on a law _resolve_icomp_sections knows — a family missing from that
        membership test has its layup reported as DROPPED."""
        deck = _shell_deck().replace(
            "*SECTION_SHELL\n" + _row(2, 2, 1.0, 5) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n",
            "*SECTION_SHELL\n" + _row(2, 2, 1.0, 4, 0.0, 0.0, 1) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + _row(0.0, 45.0, -45.0, 90.0) + "\n")
        res, _starter = _convert(deck)
        self.assertFalse(_warns(res, "ICOMP=1 angles", "are DROPPED"))
        self.assertTrue(_warns(res, "ICOMP=1", "45, -45, 90"))

    def test_type11_is_not_lost_to_type51(self):
        """hm_read_prop11.F names law 25 in its own whitelist ("PLEASE USE ONE
        OF THE FOLLOWING COMPATIBLE MATERIAL LAWS: 15,25,27, OR > 28"), so a
        MAT_022 shell keeps the layered TYPE11. Gating _type11_carries on two
        card spellings is how a third family with the same property silently
        drops to TYPE51 + TYPE19."""
        _res, starter = _convert(_shell_deck())
        self.assertTrue(_headers(starter, "/PROP/TYPE11/"))
        self.assertFalse(_headers(starter, "/PROP/TYPE51/"))


class Mat022RegistryTests(unittest.TestCase):

    def test_spellings_dispatch(self):
        for kw in ("MAT_COMPOSITE_DAMAGE", "MAT_022", "MAT_22"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_title_form_is_free(self):
        st = _dispatch(_shell_deck())
        self.assertEqual(st.mat_composite_damage[7].title, "E-GLASS/EPOXY")

    def test_offset_spec_moves_the_mid(self):
        self.assertEqual(_OFFSET_SPECS["MAT_COMPOSITE_DAMAGE"]["cards"],
                         {0: [(0, "m")]})

    def test_card_shift_fingerprint_is_warned(self):
        res, _ = _convert(_shell_deck(MAT22_SHELL + _row(1.0) + "\n"))
        self.assertTrue(_warns(res, "6 data cards were read"))

    def test_solid_class_table_knows_law25(self):
        """A thick shell on LAW25 must reach /PROP/TYPE21, not TYPE20:
        init_mat_keyword gives LAW25 SOLID_ORTHOTROPIC = class 2, and
        check_mat_elem_prop_compatibility.F:198-234 rejects class 2 on
        TYPE20 (ERROR 3047)."""
        from k2rad.writer.tshell import _SOLID_MAT_CLASS
        self.assertEqual(_SOLID_MAT_CLASS[25], 2)
        self.assertEqual(_SOLID_MAT_CLASS[127], 2)

    def test_duplicate_mat_scan_sees_the_card(self):
        """assembly._warn_duplicate_mat_ids regexes /MAT/<LAW>/<id> out of the
        assembled deck, so the /MAT/LAW25/<id> spelling joins it for free —
        the /MAT/COMPSH/<id> alias would match too, but LAW25 keeps the deck
        self-describing next to LAW93/LAW127."""
        from k2rad.writer.assembly import _MAT_CARD_LAW_ID_RE
        self.assertTrue(_MAT_CARD_LAW_ID_RE.match("/MAT/LAW25/7"))

    def test_material_is_in_the_composite_prop_split_set(self):
        from k2rad.writer.composites import _composite_material_mids
        st = _dispatch(_shell_deck())
        self.assertIn(7, _composite_material_mids(st))
