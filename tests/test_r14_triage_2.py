"""Tests for the R14 CAMPAIGN TRIAGE batch, round 2 (the engine classes):

  A1  *NODE TC/RC constraint cells   -> /GRNOD/NODE + /BCS, default on
      (pinned in tests/test_side_defects_review.py and
      tests/test_side_defects_fixround.py, which already owned those
      sentences; the named successors live there)
  A3  starter ERROR 611/612          -> the stub keeps the ordinary Inacti=5,
      every Inacti-3/4/5/6 TYPE7 states Fpenmax = 0.999999 (the MEASURED
      zero-normal cut), and a tied /INTER/TYPE10 states Itied = 1
  B1  *SET_<F>_GENERATE / _GENERATE_INCREMENT / _GENERAL / _COLUMN
  B2  SSTYP/MSTYP = 0 is a *SET_SEGMENT id, 1 a *SET_SHELL id
  B3  *EOS_GRUNEISEN A = 0           -> a tiny positive a, so the Radioss
                                        reader's A = GAMMA0 default cannot fire
  B4  the modal chain's beam mass arm (tools/modal_solve.py)
  B5  the two side findings B1 exposed: an /INIVEL over rigid-body members,
      and the modal dummy /CLOAD's per-DOF screen

Kept in its own module, the repo's one-module-per-batch convention. Two
round-2 tests do NOT live here and must not be moved here: the successors of
``ForceTransducerSegmentSetTests.test_a_shell_element_set_takes_the_same_route``
(tests/test_r14_triage_1.py) and of
``TestEveryElementGroupSiteIsGuarded.test_the_call_site_count``
(tests/test_side_defects.py) replace tests this batch INVALIDATED, and the
"a moved or removed test carries its named successor IN PLACE" rule puts them
where the reader of the old test will look.
"""

import math
import os
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the four helpers of tests/test_r14_triage_1.py) ─────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _grow(option: str, *ids) -> str:
    """A ``*SET_<F>_GENERAL`` card-2e row: OPTION left-justified in cols 1-10
    (A10), then E1..E7 in 10-wide integer cells from col 11
    (``node_general_subgrp.cfg:135``; measured on
    ``show-cases/contact-overview/main.k:3613`` and ``wall.key:30``)."""
    return f"{option:<10}" + "".join(f"{v:>10}" for v in ids)


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


def _state_and_starter(deck: str):
    """Parse + dispatch + build_starter, returning the FINAL state (every
    writer prepass and every write-line register filled) and the deck text."""
    from k2rad.writer import build_starter
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    starter = build_starter(state)
    tmp.cleanup()
    return state, starter


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


def _warns(result, needle: str):
    """Every conversion warning containing *needle*."""
    return [w for w in result.warnings if needle in w]


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


def _ids(starter: str, header: str):
    """Every integer id of a 10-wide group block (skipping its title card)."""
    rows = _block(starter, header)
    assert rows is not None, f"no block {header!r} in\n{starter}"
    out = []
    for row in rows[1:]:
        if row.startswith("#"):
            continue
        for k in range(0, len(row.rstrip()), 10):
            cell = row[k:k + 10].strip()
            if cell:
                out.append(int(cell))
    return out


def _headers(starter: str, prefix: str):
    return [ln.strip() for ln in starter.splitlines()
            if ln.strip().startswith(prefix)]


# ─────────────────────────────────────────────────────────────────────────────
# B1 — the *SET_* GENERATE / GENERAL / COLUMN spellings
# ─────────────────────────────────────────────────────────────────────────────

#: Two hexes with a HOLE in the node numbering: brick 1 is nodes 1-8, brick 2
#: is nodes 11-18, and ids 9 and 10 do not exist. Coupon B-1 of the round-2
#: spec — a range 1..12 selects the 10 EXISTING ids in it, which is what
#: Vol I R17 p.43-40 says ("All DEFINED IDs between and including BnBEG to
#: BnEND ... BnBEG and BnEND may simply be limits on the IDs and not nodal
#: IDs") and what separates "filter the pool" from "materialise the range".
_TWO_BRICKS = """*NODE
         1             0.0             0.0             0.0
         2             1.0             0.0             0.0
         3             1.0             1.0             0.0
         4             0.0             1.0             0.0
         5             0.0             0.0             1.0
         6             1.0             0.0             1.0
         7             1.0             1.0             1.0
         8             0.0             1.0             1.0
        11             3.0             0.0             0.0
        12             4.0             0.0             0.0
        13             4.0             1.0             0.0
        14             3.0             1.0             0.0
        15             3.0             0.0             1.0
        16             4.0             0.0             1.0
        17             4.0             1.0             1.0
        18             3.0             1.0             1.0
*ELEMENT_SOLID
       1       1
       1       2       3       4       5       6       7       8
       2       2
      11      12      13      14      15      16      17      18
"""

_TWO_BRICK_TAIL = ("*PART\nbrick one\n" + _row(1, 1, 1) + "\n"
                   + "*PART\nbrick two\n" + _row(2, 1, 1) + "\n"
                   + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                   + "*MAT_ELASTIC\n"
                   + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
                   + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")


def _bricks(*cards: str) -> str:
    return "*KEYWORD\n" + _TWO_BRICKS + "".join(cards) + _TWO_BRICK_TAIL


class SetGenerateRanges(unittest.TestCase):
    """``*SET_<F>[_LIST]_GENERATE`` expands against the id POOL, post-parse."""

    def test_a_range_with_a_hole_selects_only_the_ids_that_exist(self):
        """Hand-computed: `B1BEG 1 / B1END 12` over a deck whose nodes are
        1-8 and 11-18 selects TEN ids — 1..8 plus 11 and 12. Nodes 9 and 10
        are not in the deck and 13..18 are outside the range."""
        res, starter = _convert(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 12) + "\n"
            + "*INITIAL_VELOCITY\n" + _row(100) + "\n"
            + _row(0.0, 0.0, -500.0) + "\n"))
        self.assertNotIn("SET_NODE_LIST_GENERATE", res.skipped_keywords)
        st = _dispatch(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 12) + "\n"))
        # The RANGE is recorded at parse time, unexpanded (p.43-40: "these
        # sets are generated after all input is read").
        self.assertEqual(st.set_generates[("NODE", 100)][1], [(1, 12, 0)])
        self.assertEqual(st.node_sets, {})
        # ... and expands in the writer prepass, against the pool.
        st2, starter2 = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 12) + "\n"))
        self.assertEqual(st2.node_sets[100][1], [1, 2, 3, 4, 5, 6, 7, 8, 11, 12])
        del starter, starter2

    def test_the_initial_velocity_lands_on_exactly_those_nodes(self):
        """The consumer end of the same coupon: `/INIVEL` over the 10 selected
        nodes and no others. Every one of the ~40 `state.node_sets` readers
        works unchanged, because the expanded set lands under its own sid."""
        _res, starter = _convert(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 12) + "\n"
            + "*INITIAL_VELOCITY\n" + _row(100) + "\n"
            + _row(0.0, 0.0, -500.0) + "\n"))
        inivel = _headers(starter, "/INIVEL/")
        self.assertEqual(len(inivel), 1, starter)
        grnod = [h for h in _headers(starter, "/GRNOD/NODE/")]
        nids = None
        for h in grnod:
            got = _ids(starter, h)
            if got == [1, 2, 3, 4, 5, 6, 7, 8, 11, 12]:
                nids = got
        self.assertEqual(nids, [1, 2, 3, 4, 5, 6, 7, 8, 11, 12], starter)

    def test_a_twenty_million_wide_range_is_bounded_by_the_pool(self):
        """Coupon B-2. `show-cases/contact-overview/main.k` really states a
        `*SET_PART_LIST_GENERATE` spanning 10 000 000..30 199 999 over 664
        parts, so `range(beg, end + 1)` is a memory bomb on a roster deck, not
        a hypothetical. The pool is bisected instead: 16 ids out, and the
        conversion is not measurably slower than the same deck without it."""
        import time
        t0 = time.time()
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 30000000) + "\n"))
        elapsed = time.time() - t0
        self.assertEqual(len(st.node_sets[100][1]), 16)
        self.assertEqual(st.node_sets[100][1][0], 1)
        self.assertEqual(st.node_sets[100][1][-1], 18)
        self.assertLess(elapsed, 10.0)

    def test_the_increment_form_samples_the_range(self):
        """Card 2d, p.43-40: "Node IDs BBEG, BBEG + INCR, BBEG + 2 x INCR, and
        so on through BEND are added to the set." 1..18 step 3 is
        {1, 4, 7, 10, 13, 16}; 10 does not exist, so the set is
        {1, 4, 7, 13, 16} — five ids, and the hole is REPORTED, not hidden."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE_INCREMENT\n" + _row(100) + "\n"
            + _row(1, 18, 3) + "\n"))
        self.assertEqual(st.node_sets[100][1], [1, 4, 7, 13, 16])
        holes = [w for w in st.warnings if "GENERATE 100" in w]
        self.assertEqual(len(holes), 1, st.warnings)
        self.assertIn("span 6 ids and 5 of them exist", holes[0])

    def test_a_non_positive_stride_is_named_and_read_as_one(self):
        """`node_list_generate.cfg:28` gives `by` no DEFAULT row, so a stated
        0 is a stated 0 — but BBEG + 0 + 0 + ... never reaches BEND, so it
        cannot be read literally either."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE_INCREMENT\n" + _row(100) + "\n"
            + _row(1, 8, 0) + "\n"))
        self.assertEqual(st.node_sets[100][1], [1, 2, 3, 4, 5, 6, 7, 8])
        w = [x for x in st.warnings if "INCR=0" in x]
        self.assertEqual(len(w), 1, st.warnings)
        self.assertIn("is not a positive stride", w[0])

    def test_a_zero_zero_pair_is_padding_and_not_a_range(self):
        """LS-PrePost fills card 2c's four `(BnBEG, BnEND)` slots with literal
        ZEROS, so `taylor2.k:113` reads `9  2008  0  0  0  0  0  0`. A blank
        cell is dropped by the strip test; a literal 0 is not, and counting
        the three padding pairs as ranges inflated the SPAN the hole report
        quotes (matfoamsoil's set 9 read "726 of 1002" against its true
        "726 of 999")."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 8, 0, 0, 0, 0, 0, 0) + "\n"))
        self.assertEqual(st.set_generates[("NODE", 100)][1], [(1, 8, 0)])
        self.assertEqual(st.node_sets[100][1], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual([w for w in st.warnings if "GENERATE 100" in w], [])

    def test_four_pairs_on_one_card_all_count(self):
        """Card 2c holds FOUR ranges (`FREE_CELL_LIST(genemax,"%10d%10d",
        start,end,80)`), and a second card continues the list."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE\n" + _row(100) + "\n"
            + _row(1, 2, 5, 6, 11, 11, 13, 13) + "\n"
            + _row(17, 18) + "\n"))
        self.assertEqual(st.node_sets[100][1], [1, 2, 5, 6, 11, 13, 17, 18])

    def test_a_part_set_generate_reaches_the_part_pool(self):
        """*SET_PART_LIST_GENERATE is the second family with a corpus carrier
        (`show-cases/contact-overview/main.k`). The range 1..99 over a
        two-part deck selects both."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_PART_LIST_GENERATE\n" + _row(42) + "\n"
            + _row(1, 99) + "\n"))
        self.assertEqual(st.part_sets[42][1], [1, 2])

    def test_a_solid_set_generate_uses_the_bare_spelling(self):
        """OPTION1 is family-specific and the asymmetry is real: SOLID/BEAM/
        DISCRETE spell it bare `GENERATE` (p.43-89 / 43-3 / 43-14,
        `solid_list_generate.cfg:102` `*SET_SOLID_GENERATE%s`), so
        `*SET_SOLID_LIST_GENERATE` must NOT fall out of the lenient
        `*SET_SOLID_LIST` alias k2rad also registers."""
        from k2rad.handlers import HANDLERS
        self.assertIn("SET_SOLID_GENERATE", HANDLERS)
        self.assertNotIn("SET_SOLID_LIST_GENERATE", HANDLERS)
        self.assertIn("SET_NODE_LIST_GENERATE", HANDLERS)
        self.assertNotIn("SET_NODE_GENERATE", HANDLERS)
        self.assertIn("SET_DISCRETE_GENERATE", HANDLERS)
        self.assertNotIn("SET_DISCRETE_GENERATE_INCREMENT", HANDLERS)
        st, _starter = _state_and_starter(_bricks(
            "*SET_SOLID_GENERATE\n" + _row(7) + "\n" + _row(1, 99) + "\n"))
        self.assertEqual(st.solid_sets[7][1], [1, 2])

    def test_a_tshell_range_spelling_stays_refused_by_name(self):
        """`*SET_TSHELL_GENERATE` DOES exist (p.43-100), unlike
        `*SET_TSHELL_ADD`. What k2rad has no room for is the RESULT: there is
        no tshell_sets container and `*SET_TSHELL` itself is unregistered, so
        registering only the range spelling would parse a set nothing can
        read."""
        res, _starter = _convert(_bricks(
            "*SET_TSHELL_GENERATE\n" + _row(7) + "\n" + _row(1, 99) + "\n"))
        self.assertIn("SET_TSHELL_GENERATE", res.skipped_keywords)

    def test_collect_and_title_are_stripped_by_the_parser(self):
        """`_COMBINE(KEY,"_INCREMENT")` -> `"_COLLECT"` -> `"_TITLE"` in every
        `Keyword971/SETS/*_list_generate.cfg`, so the suffixes stack and
        enumerating the permutations in HANDLERS would double every generated
        spelling (the #116 combinatorics trap). `parser._TRAILING` strips
        both, and two cards with the same id MERGE — which is what _COLLECT
        exists for."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST_GENERATE_COLLECT\n" + _row(100) + "\n"
            + _row(1, 4) + "\n"
            + "*SET_NODE_LIST_GENERATE_COLLECT_TITLE\nsecond half\n"
            + _row(100) + "\n" + _row(11, 14) + "\n"))
        self.assertEqual(st.node_sets[100][1], [1, 2, 3, 4, 11, 12, 13, 14])


class SetGeneralOptions(unittest.TestCase):
    """``*SET_<F>_GENERAL`` — clauses applied IN ORDER, exclusions only
    against what is already in the set."""

    def test_the_manuals_own_worked_example(self):
        """Coupon B-3, Vol I R17 p.43-41 verbatim: part 6 = {10,15,20,32},
        box 7 = {5,20,32}, part 10 = {5,22,106}; `PART 6 / DBOX 7 / PART 10`
        -> **{5, 10, 15, 22, 106}**. A set-semantics implementation gives
        {10,15,22,106} (5 excluded by the box before it was ever added) or
        {5,10,15,20,22,32,106} (no exclusion at all)."""
        mesh = ["*NODE"]
        # part 6's nodes, on a plane the box does not reach except 20 and 32
        for nid, x in ((10, 0.0), (15, 1.0), (20, 5.0), (32, 6.0)):
            mesh.append(_row(nid, x, 0.0, 0.0))
        for nid, x in ((5, 5.5), (22, 0.5), (106, 1.5)):
            mesh.append(_row(nid, x, 10.0, 0.0))
        deck = ("*KEYWORD\n" + "\n".join(mesh) + "\n"
                # two 1-D "parts" so PART 6 and PART 10 have a node census
                + "*ELEMENT_BEAM\n" + _row(1, 6, 10, 15, 0) + "\n"
                + _row(2, 6, 20, 32, 0) + "\n"
                + _row(3, 10, 5, 22, 0) + "\n" + _row(4, 10, 106, 5, 0) + "\n"
                + "*PART\nsix\n" + _row(6, 1, 1) + "\n"
                + "*PART\nten\n" + _row(10, 1, 1) + "\n"
                + "*SECTION_BEAM\n" + _row(1, 1) + "\n"
                + _row(1.0, 1.0, 1.0, 1.0) + "\n"
                + "*MAT_ELASTIC\n"
                + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
                # the box covers x in [4.5, 6.5], y in [-1, 1]: nodes 20, 32
                # from part 6 and, at y = 10, nothing -- so node 5 is NOT in
                # it geometrically. Give it y up to 11 so 5 IS in it, which is
                # what makes the ORDER observable.
                + "*DEFINE_BOX\n"
                + _row(7, 4.5, 6.5, -1.0, 11.0, -1.0, 1.0) + "\n"
                + "*SET_NODE_GENERAL\n" + _row(1) + "\n"
                + _grow("PART", 6) + "\n"
                + _grow("DBOX", 7) + "\n"
                + _grow("PART", 10) + "\n"
                + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")
        st, _starter = _state_and_starter(deck)
        self.assertEqual(sorted(st.node_sets[1][1]), [5, 10, 15, 22, 106])

    def test_a_general_part_clause_is_the_parts_node_census(self):
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_GENERAL\n" + _row(1) + "\n" + _grow("PART", 2) + "\n"))
        self.assertEqual(st.node_sets[1][1],
                         [11, 12, 13, 14, 15, 16, 17, 18])

    def test_a_general_all_clause_is_every_node(self):
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_GENERAL\n" + _row(1) + "\n" + _grow("ALL") + "\n"))
        self.assertEqual(len(st.node_sets[1][1]), 16)

    def test_a_general_box_clause_intersects_the_source_nodes(self):
        """`*DEFINE_BOX` sweeps must intersect `state.source_node_ids` so a box
        drawn round the user's model does not also catch k2rad's own
        synthesized nodes (`writer/assembly.py`'s existing rule)."""
        st, _starter = _state_and_starter(_bricks(
            "*DEFINE_BOX\n"
            + _row(7, 2.5, 5.0, -1.0, 2.0, -1.0, 2.0) + "\n"
            + "*SET_NODE_GENERAL\n" + _row(1) + "\n" + _grow("BOX", 7) + "\n"))
        self.assertEqual(st.node_sets[1][1],
                         [11, 12, 13, 14, 15, 16, 17, 18])

    def test_a_general_dpart_clause_excludes(self):
        """The only two `DPART` rows in either corpus are inside the Yaris and
        Camry `*INCLUDE` trees, which no sweep converts — so this is a
        CORRECTNESS requirement with no mover behind it, and a test is the
        only thing that can hold it."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_GENERAL\n" + _row(1) + "\n"
            + _grow("ALL") + "\n" + _grow("DPART", 1) + "\n"))
        self.assertEqual(st.node_sets[1][1],
                         [11, 12, 13, 14, 15, 16, 17, 18])

    def test_a_segment_general_seg_row_shares_the_triangle_collapse(self):
        """Coupon B-4. A face written `n1 n2 n3 n3` (the manual's N4 = N3
        spelling, which `Model-318_Achshebel-fein_tobi.k:392` really uses) and
        the same face written `n1 n2 n3 0` on a `*SET_SEGMENT` must become ONE
        segment, or one `*LOAD_SEGMENT_SET` pressure is applied twice — the
        #131-measured EXT-WORK 18.35 -> 73.39 trap."""
        st, starter = _state_and_starter(_bricks(
            "*SET_SEGMENT\n" + _row(9) + "\n" + _row(1, 2, 3, 0) + "\n"
            + "*SET_SEGMENT_GENERAL\n" + _row(9) + "\n"
            + _grow("SEG", 1, 2, 3, 3) + "\n"
            + "*LOAD_SEGMENT_SET\n" + _row(9, 1, 1.0) + "\n"
            + "*DEFINE_CURVE\n" + _row(1) + "\n"
            + f"{0.0:>20}{1.0:>20}\n" + f"{1.0:>20}{1.0:>20}\n"))
        self.assertEqual(len(st.segment_sets[9].segments), 1)
        self.assertEqual(st.segment_sets[9].segments[0], [1, 2, 3])
        self.assertEqual(len(_headers(starter, "/PLOAD/")), 1, starter)

    def test_a_segment_general_part_clause_keeps_the_part_ids(self):
        """Vol I R17 p.43-64: "For shell elements, one segment per shell is
        generated. For solid elements, only those segments wrapping the solid
        part and pointing outward from the part will be generated." That is
        what `_make_master_surface` already emits, so the PART ids ride
        through on `SegmentSet.part_scope` instead of being tessellated in
        Python (and E4..E7 on that option are FLOAT attributes, not part ids
        — reading them as ids would add phantom parts)."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_SEGMENT_GENERAL\n" + _row(9) + "\n"
            + _grow("PART", 2) + "\n"))
        self.assertEqual(st.segment_sets[9].part_scope, [2])
        self.assertEqual(st.segment_sets[9].segments, [])

    def test_an_option_with_no_resolver_is_refused_by_name(self):
        st, _starter = _state_and_starter(_bricks(
            "*SET_SEGMENT_GENERAL\n" + _row(9) + "\n"
            + _grow("SEG", 1, 2, 3, 4) + "\n"
            + _grow("BOX_SHELL", 7) + "\n"))
        w = [x for x in st.warnings if "BOX_SHELL" in x]
        self.assertEqual(len(w), 1, st.warnings)
        self.assertIn("*SET_SEGMENT_GENERAL 9", w[0])
        self.assertIn("_SEGMENT_GENERAL_OPTIONS", w[0])
        # the other clause still built the set
        self.assertEqual(len(st.segment_sets[9].segments), 1)

    def test_a_part_general_refusal_cites_the_part_option_table(self):
        """A warning's CITED FACT needs the same audit as its conclusion: the
        `*SET_PART_GENERAL` reader is `_PART_GENERAL_OPTIONS`, and sending the
        reader to the element table would name a list that does not hold this
        family's options."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_PART_GENERAL\n" + _row(3) + "\n"
            + _grow("MATTYPE", 1) + "\n"))
        w = [x for x in st.warnings if "MATTYPE" in x]
        self.assertEqual(len(w), 1, st.warnings)
        self.assertIn("_PART_GENERAL_OPTIONS", w[0])
        self.assertNotIn("_ELEM_GENERAL_OPTIONS", w[0])

    def test_an_add_union_named_by_a_general_clause_is_named(self):
        """The one back-edge the pass order cannot serve — GENERAL resolves
        before `_flatten_set_adds`, so a clause naming an `_ADD` union is
        warned by name rather than silently dropped. No corpus deck does it."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2) + "\n"
            + "*SET_NODE_ADD\n" + _row(6) + "\n" + _row(5) + "\n"
            + "*SET_NODE_GENERAL\n" + _row(1) + "\n"
            + _grow("SET_NODE", 6) + "\n"))
        w = [x for x in st.warnings if "*SET_NODE_ADD 6" in x]
        self.assertEqual(len(w), 1, st.warnings)


class SetColumnSpelling(unittest.TestCase):
    def test_a_node_column_set_is_a_plain_node_list(self):
        """Card 2b, p.43-39: one `NID A1 A2 A3 A4` per card, the A cells
        overriding the header's DA1..DA4 for THAT node (Remark 2, p.43-44).
        No k2rad consumer reads a per-ENTITY attribute, so a COLUMN set is a
        plain id list — and the dropped cells are named, not ignored."""
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_COLUMN\n" + _row(100) + "\n"
            + _row(1, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(5, 2.5, 0.0, 0.0, 0.0) + "\n"))
        self.assertEqual(st.node_sets[100][1], [1, 5])
        w = [x for x in st.warnings if "SET_NODE_COLUMN 100" in x]
        self.assertEqual(len(w), 1, st.warnings)
        self.assertIn("A1..A4", w[0])

    def test_a_column_set_with_no_attributes_is_silent(self):
        st, _starter = _state_and_starter(_bricks(
            "*SET_NODE_COLUMN\n" + _row(100) + "\n" + _row(1) + "\n"))
        self.assertEqual(st.node_sets[100][1], [1])
        self.assertEqual([x for x in st.warnings if "SET_NODE_COLUMN" in x], [])


class SetSpellingsAreRegistered(unittest.TestCase):
    """One `assertNotIn(<spelling>, skipped_keywords)` per newly registered
    family, so a dropped registration is caught as a test failure rather than
    as a silently empty set."""

    def test_every_registered_spelling_leaves_skipped_keywords(self):
        cards = {
            "SET_NODE_LIST_GENERATE":
                "*SET_NODE_LIST_GENERATE\n" + _row(101) + "\n" + _row(1, 8),
            "SET_NODE_LIST_GENERATE_INCREMENT":
                "*SET_NODE_LIST_GENERATE_INCREMENT\n" + _row(102) + "\n"
                + _row(1, 8, 2),
            "SET_NODE_GENERAL":
                "*SET_NODE_GENERAL\n" + _row(103) + "\n" + _grow("ALL"),
            "SET_NODE_COLUMN":
                "*SET_NODE_COLUMN\n" + _row(104) + "\n" + _row(1),
            "SET_PART_LIST_GENERATE":
                "*SET_PART_LIST_GENERATE\n" + _row(105) + "\n" + _row(1, 9),
            "SET_PART_LIST_GENERATE_INCREMENT":
                "*SET_PART_LIST_GENERATE_INCREMENT\n" + _row(120) + "\n"
                + _row(1, 9, 1),
            "SET_SHELL_LIST_GENERATE_INCREMENT":
                "*SET_SHELL_LIST_GENERATE_INCREMENT\n" + _row(121) + "\n"
                + _row(1, 9, 1),
            "SET_PART_COLUMN":
                "*SET_PART_COLUMN\n" + _row(106) + "\n" + _row(1),
            "SET_PART_GENERAL":
                "*SET_PART_GENERAL\n" + _row(107) + "\n" + _grow("ALL"),
            "SET_SHELL_LIST_GENERATE":
                "*SET_SHELL_LIST_GENERATE\n" + _row(108) + "\n" + _row(1, 9),
            "SET_SHELL_COLUMN":
                "*SET_SHELL_COLUMN\n" + _row(109) + "\n" + _row(1),
            "SET_SHELL_GENERAL":
                "*SET_SHELL_GENERAL\n" + _row(110) + "\n" + _grow("ALL"),
            "SET_SOLID_GENERATE":
                "*SET_SOLID_GENERATE\n" + _row(111) + "\n" + _row(1, 9),
            "SET_SOLID_GENERATE_INCREMENT":
                "*SET_SOLID_GENERATE_INCREMENT\n" + _row(112) + "\n"
                + _row(1, 9, 1),
            "SET_SOLID_GENERAL":
                "*SET_SOLID_GENERAL\n" + _row(113) + "\n" + _grow("ALL"),
            "SET_BEAM_GENERATE":
                "*SET_BEAM_GENERATE\n" + _row(114) + "\n" + _row(1, 9),
            "SET_BEAM_GENERATE_INCREMENT":
                "*SET_BEAM_GENERATE_INCREMENT\n" + _row(115) + "\n"
                + _row(1, 9, 1),
            "SET_BEAM_GENERAL":
                "*SET_BEAM_GENERAL\n" + _row(116) + "\n" + _grow("ALL"),
            "SET_DISCRETE_GENERATE":
                "*SET_DISCRETE_GENERATE\n" + _row(117) + "\n" + _row(1, 9),
            "SET_DISCRETE_GENERAL":
                "*SET_DISCRETE_GENERAL\n" + _row(118) + "\n" + _grow("ALL"),
            "SET_SEGMENT_GENERAL":
                "*SET_SEGMENT_GENERAL\n" + _row(119) + "\n"
                + _grow("SEG", 1, 2, 3, 4),
        }
        # Every generated spelling needs a probe card, or a registration that
        # stops generating is caught by nothing (the two _INCREMENT rows above
        # were missing exactly that way until the round-2 review counted them).
        from k2rad.handlers import _set_range_keywords
        self.assertEqual(
            {kw for kw, _f, _k, _i in _set_range_keywords()} - set(cards),
            set())
        for kw, card in sorted(cards.items()):
            with self.subTest(kw=kw):
                res, _starter = _convert(_bricks(card + "\n"))
                self.assertNotIn(kw, res.skipped_keywords)

    def test_the_three_generators_read_the_same_family_table(self):
        """`state.SET_RANGE_FAMILIES` generates the parser keys, the
        `*INCLUDE_TRANSFORM` offset rows and the expansion pass's family loop.
        A spelling read by one and invisible to the others is the #116 silent
        failure, so the two generated key sets must be equal."""
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import _set_range_keywords
        generated = {kw for kw, _f, _k, _i in _set_range_keywords()}
        self.assertTrue(generated)
        self.assertEqual(generated - set(_OFFSET_SPECS), set())
        # ...and the HANDLERS side too: a table row that stopped generating a
        # PARSER key would show up in neither of the other assertions, and the
        # spelling would land in skipped_keywords with the set silently empty.
        from k2rad.handlers import HANDLERS
        self.assertEqual(generated - set(HANDLERS), set())


class SetSpellingOffsets(unittest.TestCase):
    """`*INCLUDE_TRANSFORM` — every range CELL is an entity id."""

    @staticmethod
    def _with_include(child: str, idnoff: int = 100000, ideoff: int = 0,
                      idpoff: int = 0, idsoff: int = 0):
        """Card 2 of `*INCLUDE_TRANSFORM` is
        `IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF IDDOFF IDROFF` — IDSOFF is
        field FIVE, and putting it in field four offsets materials instead."""
        tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write("*KEYWORD\n" + child + "*END\n")
        parent = ("*KEYWORD\n"
                  + "*INCLUDE_TRANSFORM\nchild.k\n"
                  + _row(idnoff, ideoff, idpoff, 0, idsoff, 0, 0, 0) + "\n"
                  + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n"
                  + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")
        path = os.path.join(tmp.name, "parent.k")
        with open(path, "w") as fh:
            fh.write(parent)
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        tmp.cleanup()
        return state

    def test_a_generate_range_moves_with_the_node_offset(self):
        """A range 1..999 under IDNOFF = 100000 must become 100001..100999,
        or the include's nodes move, the range does not, and the set resolves
        EMPTY at zero diagnostics."""
        st = self._with_include(
            "*SET_NODE_LIST_GENERATE\n" + _row(7) + "\n"
            + _row(1, 999) + "\n", idnoff=100000, idsoff=500)
        self.assertEqual(st.set_generates[("NODE", 507)][1],
                         [(100001, 100999, 0)])

    def test_the_increment_stride_is_not_an_id(self):
        """Field 2 of card 2d is a STRIDE. An `(ALL, ...)` spec would offset
        it and re-sample the range."""
        st = self._with_include(
            "*SET_NODE_LIST_GENERATE_INCREMENT\n" + _row(7) + "\n"
            + _row(1, 999, 3) + "\n", idnoff=100000)
        self.assertEqual(st.set_generates[("NODE", 7)][1],
                         [(100001, 100999, 3)])

    def test_a_column_set_offsets_field_zero_only(self):
        """A1..A4 are floats."""
        st = self._with_include(
            "*SET_NODE_COLUMN\n" + _row(7) + "\n"
            + _row(4, 2.5, 0.0, 0.0, 0.0) + "\n", idnoff=100000)
        self.assertEqual(st.node_sets[7][1], [100004])

    def test_a_general_clause_offsets_by_its_own_option(self):
        """The id columns depend on the OPTION in cols 1-10 of the SAME row,
        so the walker is callable: SEG's E1..E4 are NODE ids, PART's E1..E3
        are PART ids and its E4..E7 are FLOAT attributes
        (`segment_general_subgrp.cfg:258`), and SET_* names SET ids."""
        st = self._with_include(
            "*SET_SEGMENT_GENERAL\n" + _row(7) + "\n"
            + _grow("SEG", 1, 2, 3, 4) + "\n"
            + _grow("PART", 5) + "\n",
            idnoff=100000, idpoff=300, idsoff=20)
        clauses = st.set_generals[("SEGMENT", 27)][1]
        self.assertEqual(clauses[0], ("SEG", [100001, 100002, 100003, 100004]))
        self.assertEqual(clauses[1], ("PART", [305]))

    def test_a_general_all_clause_has_nothing_to_offset(self):
        st = self._with_include(
            "*SET_NODE_GENERAL\n" + _row(7) + "\n" + _grow("ALL") + "\n",
            idnoff=100000)
        self.assertEqual(st.set_generals[("NODE", 7)][1], [("ALL", [])])


# ─────────────────────────────────────────────────────────────────────────────
# B2 — SSTYP/MSTYP = 0 is a *SET_SEGMENT id, 1 a *SET_SHELL id
# ─────────────────────────────────────────────────────────────────────────────

#: A 2x2 shell plate (part 1) plus a separate impactor shell (part 2). The
#: shape of `intro-by-k.-weimar/contact/contact-ii/plate.typ13.k`: a
#: `*SET_SEGMENT 1` that spans BOTH bodies beside a `*PART 1` that is the
#: plate alone, so part-first precedence and set precedence give visibly
#: different interfaces.
_PLATE_MESH = """*NODE
         1             0.0             0.0             0.0
         2             1.0             0.0             0.0
         3             2.0             0.0             0.0
         4             0.0             1.0             0.0
         5             1.0             1.0             0.0
         6             2.0             1.0             0.0
         7             0.0             2.0             0.0
         8             1.0             2.0             0.0
         9             2.0             2.0             0.0
       101             0.0             0.0             5.0
       102             1.0             0.0             5.0
       103             1.0             1.0             5.0
       104             0.0             1.0             5.0
*ELEMENT_SHELL
       1       1       1       2       5       4
       2       1       2       3       6       5
       3       1       4       5       8       7
       4       1       5       6       9       8
      11       2     101     102     103     104
"""


def _plate(*cards: str, seg: bool = True) -> str:
    segset = ("*SET_SEGMENT\n" + _row(1) + "\n"
              + _row(101, 102, 103, 104) + "\n"
              + _row(1, 2, 5, 4) + "\n") if seg else ""
    return ("*KEYWORD\n" + _PLATE_MESH
            + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
            + "*PART\nimpactor\n" + _row(2, 1, 1) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2, "", 3) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + "*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
            + segset + "".join(cards)
            + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")


class SstypZeroIsASegmentSet(unittest.TestCase):
    """Vol I R17 p.11-24: SURFATYP EQ.0 is a Segment set ID. p.11-25 settles
    it from the other side — SABOXID "can be used only if SURFATYP is set to
    2, 3, 5, or 6, meaning SURFA is a part ID or part set ID"."""

    def test_the_segment_set_wins_over_a_part_of_the_same_id(self):
        """`plate.typ13`'s shape. Master resolved `sid=1, styp=0` through
        `sid in state.parts` and built a self-contact of PART 1 — the
        impactor was not in the interface at all and passed through. Measured
        on the real deck: /GRNOD 90003 held nodes 1..25 (the target alone) and
        the main surface was a /SURF/GRSHEL over shells 1..16."""
        _res, starter = _convert(_plate(
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(1, 0, 0, 0) + "\n"))
        segs = _headers(starter, "/SURF/SEG/")
        self.assertEqual(len(segs), 1, starter)
        rows = _block(starter, segs[0])
        assert rows is not None
        data = [r for r in rows[1:] if not r.startswith("#")]
        self.assertEqual(len(data), 2, starter)     # the set's TWO segments
        # ... and the secondary group holds the segment set's nodes, ONLY.
        grnods = {h: _ids(starter, h) for h in _headers(starter, "/GRNOD/NODE/")}
        self.assertIn([1, 2, 4, 5, 101, 102, 103, 104], list(grnods.values()),
                      starter)
        for nids in grnods.values():
            self.assertNotIn(9, nids, starter)      # a plate node NOT in the set

    def test_a_missing_segment_set_is_named_and_never_read_as_a_part(self):
        """The WARN-BY-NAME case (`W7_SETUP_3P BendTest_implicit.k` states
        SURFA 1 / SURFB 2 typed 0 with no `*SET_SEGMENT` anywhere in the
        file). LS-DYNA's own behaviour on a missing set is not quoted: no
        corpus run produces one, so there is no d3hsp line to cite."""
        res, starter = _convert(_plate(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            + _row(7, 2, 0, 3) + "\n", seg=False))
        self.assertEqual(_headers(starter, "/INTER/TYPE7/"), [], starter)
        self.assertEqual(_headers(starter, "/INTER/TYPE25/"), [], starter)
        w = [x for x in res.warnings if "SURFATYP=0" in x]
        self.assertTrue(w, res.warnings)
        self.assertIn("*SET_SEGMENT 7", w[0])
        self.assertIn("*INCLUDE", w[0])

    def test_a_same_numbered_part_is_named_in_the_refusal(self):
        """Naming the clash is what tells the reader "the deck states the
        wrong type" apart from "the set lives in an *INCLUDE I did not read"."""
        res, _starter = _convert(_plate(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            + _row(1, 2, 0, 3) + "\n", seg=False))
        w = [x for x in res.warnings if "SURFATYP=0" in x]
        self.assertTrue(w, res.warnings)
        self.assertIn("*PART 1", w[0])
        self.assertIn("p.11-25", w[0])

    def test_a_two_way_contact_with_mstyp_zero_takes_the_main_side(self):
        """`_resolve_contact_master` is a DIFFERENT emission site from
        `_resolve_contact_slave` and needs its own carrier (the #131/#132
        rule): a two-way contact whose MAIN side is typed 0."""
        _res, starter = _convert(_plate(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            + _row(2, 1, 3, 0) + "\n"))
        self.assertEqual(len(_headers(starter, "/SURF/SEG/")), 1, starter)
        self.assertEqual(_headers(starter, "/SURF/GRSHEL/"), [], starter)

    def test_sstyp_one_builds_a_shell_surface_not_a_segment_one(self):
        """Coupon C-2. SURFATYP 1 is a shell ELEMENT set, a different
        namespace from 0 — so a deck with BOTH a `*SET_SHELL_LIST 1` and a
        `*SET_SEGMENT 1` must take the shell set."""
        _res, starter = _convert(_plate(
            "*SET_SHELL_LIST\n" + _row(1) + "\n" + _row(1, 2) + "\n"
            + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            + _row(2, 1, 3, 1) + "\n"))
        self.assertEqual(_headers(starter, "/SURF/SEG/"), [], starter)
        grshel = _headers(starter, "/GRSHEL/SHEL/")
        self.assertEqual(len(grshel), 1, starter)
        self.assertEqual(_ids(starter, grshel[0]), [1, 2])
        self.assertEqual(len(_headers(starter, "/SURF/GRSHEL/")), 1, starter)

    def test_ssid_zero_still_means_all_parts(self):
        """k2rad's own implicit-stabilization stub is `ssid=0, sstyp=0`, so a
        blanket "styp 0 -> look up a *SET_SEGMENT" would break it on every
        implicit deck."""
        _res, starter = _convert(_plate(
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 0, 0) + "\n"))
        self.assertTrue(_headers(starter, "/INTER/TYPE25/")
                        or _headers(starter, "/INTER/TYPE7/"), starter)
        self.assertEqual(_headers(starter, "/SURF/SEG/"), [], starter)

    def test_gapmin_describes_the_side_by_its_type(self):
        """`--auto-gapmin`'s `_describe_side` printed "part 1 (plate)" for the
        segment side of plate.typ13 — a label agreeing with a resolution that
        was itself wrong."""
        from k2rad import gapmin
        st = _dispatch(_plate(
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(1, 0, 0, 0) + "\n"))
        self.assertEqual(gapmin._describe_side(st, 1, 0),
                         "segment set 1 (2 segment(s))")
        self.assertEqual(gapmin._describe_side(st, 1, 3), "part 1 (plate)")
        self.assertEqual(gapmin._describe_side(st, 9, 1),
                         "shell element set 9 (not defined in this deck)")


# ─────────────────────────────────────────────────────────────────────────────
# B3 — *EOS_GRUNEISEN A = 0
# ─────────────────────────────────────────────────────────────────────────────

def _gruneisen(a, gamma0) -> str:
    """taylor1's numbers: C 3958000, S1 1.497, S2 = S3 = 0, E0 = 0.

    The EOS needs a carrier: a same-id `*MAT_NULL` is the spelling k2rad
    resolves (no `*EOS_*` keyword carries a density, so a synthesized
    `/MAT/LAW6` would be starter ERROR 683)."""
    return ("*KEYWORD\n" + _TWO_BRICKS
            + "*PART\nbrick one\n" + _row(1, 1, 1) + "\n"
            + "*PART\nfluid\n" + _row(2, 1, 2, 0, 0, 0, 0, 2) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + "*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
            + "*MAT_NULL\n" + _row(2, "8.90E-09", 0.0, 0.0, 0.0) + "\n"
            + "*EOS_GRUNEISEN\n"
            + _row(2, 3958000.0, 1.497, 0.0, 0.0, gamma0, a, 0.0) + "\n"
            + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")


class GruneisenZeroA(unittest.TestCase):
    """`hm_read_eos_gruneisen.F:102` is `IF(A == ZERO) A=GAMA0` — the only
    test on A in that file — and LS-DYNA states no Default for A (Vol II R17
    p.1-16), so a blank or a literal 0 IS zero."""

    def test_a_zero_a_beside_a_nonzero_gamma0_becomes_the_sentinel(self):
        """MEASURED on a four-brick starter coupon at these numbers
        (RHO_I/RHO_0 = 9.79e-9/8.9e-9, so the reader's own MU0 = 0.1): the
        starter echoes `A = 1.0000000000000E-20` verbatim and an INITIAL
        PRESSURE of 15439.03415072, the a = 0 closed form to 13 digits,
        against 15284.64380921 for A = GAMMA0. 1e-8 already differs in the
        12th digit, so 1e-20 is the value."""
        st, starter = _state_and_starter(_gruneisen(0.0, 2.0))
        self.assertEqual(st.eos_cards[2].params["a"], 1e-20)
        rows = _block(starter, "/EOS/GRUNEISEN/2")
        assert rows is not None, starter
        cells = [r for r in rows if "E-20" in r]
        self.assertEqual(len(cells), 1, starter)
        self.assertIn("1.000000E-20", cells[0])

    def test_the_warning_names_the_reader_line_and_the_size(self):
        st, _starter = _state_and_starter(_gruneisen(0.0, 2.0))
        w = [x for x in st.warnings if "GRUNEISEN" in x]
        self.assertEqual(len(w), 1, st.warnings)
        self.assertIn("hm_read_eos_gruneisen.F:102", w[0])
        self.assertIn("IF(A == ZERO) A=GAMA0", w[0])
        self.assertIn("A = GAMMA0 = 2", w[0])
        # bulk -(g0/2)mu^2 / (1 + (1 - g0/2)mu) at mu = 0.1, g0 = 2 = -1.00 %;
        # energy +mu = +10.00 %, and that half is GAMMA0-independent.
        self.assertIn("changes -1.00 %", w[0])
        self.assertIn("rises 10.00 %", w[0])

    def test_a_zero_gamma0_is_left_alone_because_the_default_is_a_no_op(self):
        """`IF(A == ZERO) A = GAMA0` is a NO-OP when GAMMA0 is itself 0, and
        23 of the 25 A = 0 cards on the R14 roster have GAMMA0 = 0.0. Writing
        the sentinel there would move 23 emitted decks for no physical reason
        — "never fabricate an unstated value"."""
        st, starter = _state_and_starter(_gruneisen(0.0, 0.0))
        self.assertEqual(st.eos_cards[2].params["a"], 0.0)
        self.assertEqual([x for x in st.warnings if "GRUNEISEN" in x], [])
        self.assertNotIn("E-20", "\n".join(_block(starter, "/EOS/GRUNEISEN/2")
                                           or []))

    def test_a_stated_a_passes_through_untouched(self):
        st, _starter = _state_and_starter(_gruneisen(0.47, 2.0))
        self.assertEqual(st.eos_cards[2].params["a"], 0.47)
        self.assertEqual([x for x in st.warnings if "GRUNEISEN" in x], [])

    def test_the_substitution_size_is_derived_from_the_cards_own_gamma0(self):
        """Only the ENERGY half is card-independent (`BB = g0 + a*mu` makes it
        `+mu` whatever GAMMA0 is). Quoting the coupon's -1.00 % as "with this
        card's numbers" would be false on any other GAMMA0."""
        from k2rad.writer.materials import _gruneisen_substitution_size
        # hand-computed -(g0/2)*0.01 / (1 + (1 - g0/2)*0.1) * 100
        for g0, expect in ((2.0, -1.0000), (1.0, -0.4762), (4.0, -2.2222)):
            with self.subTest(g0=g0):
                ff0 = 1.0 + (1.0 - g0 / 2.0) * 0.1
                want = -(g0 / 2.0) * 0.01 / ff0 * 100.0
                self.assertAlmostEqual(want, expect, places=4)
                self.assertIn(f"changes {want:+.2f} %",
                              _gruneisen_substitution_size(g0))
        # a GAMMA0 large enough to make the reference value non-positive
        # reports the energy term alone rather than a percentage of a sign
        # change: 1 + (1 - 25/2)*0.1 = -0.15.
        big = _gruneisen_substitution_size(25.0)
        self.assertIn("rises 10.00 %", big)
        self.assertNotIn("compression pressure changes", big)


# ─────────────────────────────────────────────────────────────────────────────
# B5 — the two side findings the set batch exposed
# ─────────────────────────────────────────────────────────────────────────────

class InivelOnRigidBodyMembers(unittest.TestCase):
    """`matfoamsoil`'s shape: a `*SET_NODE_LIST_GENERATE` that now resolves,
    an `*INITIAL_VELOCITY` over it, and every node of it a member of a
    `*MAT_RIGID` part."""

    def _deck(self, rigid: bool) -> str:
        mat = ("*MAT_RIGID\n" + _row(2, "7.85E-09", 210000.0, 0.3) + "\n"
               + _row(0, 7, 7) + "\n" + _row(0.0, 0.0, 0.0) + "\n") if rigid \
            else ("*MAT_ELASTIC\n"
                  + _row(2, "7.85E-09", 210000.0, 0.3) + "\n")
        return ("*KEYWORD\n" + _TWO_BRICKS
                + "*PART\nbrick one\n" + _row(1, 1, 1) + "\n"
                + "*PART\nbrick two\n" + _row(2, 1, 2) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + "*MAT_ELASTIC\n"
                + _row(1, "7.85E-09", 210000.0, 0.3) + "\n" + mat
                + "*SET_NODE_LIST_GENERATE\n" + _row(99) + "\n"
                + _row(11, 18) + "\n"
                + "*INITIAL_VELOCITY\n" + _row(99) + "\n"
                + _row(25000.0, 0.0, 0.0) + "\n"
                + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")

    def test_an_inivel_entirely_on_rigid_members_is_named(self):
        """`inirby.F` rebuilds a /RBODY secondary node's velocity from the
        body's main node every cycle, so the /INIVEL is overwritten before
        cycle 1 and the body starts at rest — at 0 starter diagnostics."""
        res, starter = _convert(self._deck(rigid=True))
        self.assertEqual(len(_headers(starter, "/INIVEL/")), 1, starter)
        w = [x for x in res.warnings
             if "*INITIAL_VELOCITY NSID=99" in x and "rigid body" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("8 of its 8 node(s)", w[0])
        self.assertIn("inirby.F", w[0])
        self.assertIn("EVERY node of this card is a rigid-body member", w[0])
        self.assertIn("*INITIAL_VELOCITY_RIGID_BODY", w[0])

    def test_a_deformable_twin_says_nothing(self):
        """The negative control — the same deck with part 2 deformable."""
        res, starter = _convert(self._deck(rigid=False))
        self.assertEqual(len(_headers(starter, "/INIVEL/")), 1, starter)
        self.assertEqual([x for x in res.warnings if "rigid body" in x], [])


class ModalDummyCloadScreensPerDof(unittest.TestCase):
    """`ex_08_beam_elform_1`'s shape: a `*CONTROL_IMPLICIT_EIGENVALUE` deck
    whose `*BOUNDARY_SPC_SET` cards sit on `_GENERATE` sets."""

    def _deck(self, spc: str) -> str:
        return ("*KEYWORD\n" + _TWO_BRICKS
                + "*PART\nbrick one\n" + _row(1, 1, 1) + "\n"
                + "*PART\nbrick two\n" + _row(2, 1, 1) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + "*MAT_ELASTIC\n"
                + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
                + "*SET_NODE_LIST_GENERATE\n" + _row(1) + "\n"
                + _row(1, 18) + "\n" + spc
                + "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
                + "*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(3) + "\n"
                + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n")

    def test_a_node_pinned_in_z_can_still_carry_the_dummy_load_in_x(self):
        """The whole-node screen dropped every node named by any
        `*BOUNDARY_SPC`, whatever it pins — harmless while few node sets
        resolved, and not harmless once `*SET_NODE_LIST_GENERATE` is read. A
        unit /CLOAD along a FREE direction is perfectly good loading data for
        a load-independent stiffness export."""
        res, starter = _convert(self._deck(
            "*BOUNDARY_SPC_SET\n" + _row(1, 0, 0, 0, 1, 1, 1, 1) + "\n"))
        self.assertEqual(len(_headers(starter, "/CLOAD/")), 1, starter)
        w = [x for x in res.warnings if "dummy unit /CLOAD" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("dir X", w[0])
        self.assertIn("--static", w[0])
        self.assertIn(" X 1", w[0])

    def test_z_is_still_tried_first(self):
        """The historical choice, so no already-correct deck moves."""
        res, starter = _convert(self._deck(""))
        self.assertEqual(len(_headers(starter, "/CLOAD/")), 1, starter)
        w = [x for x in res.warnings if "dummy unit /CLOAD" in x]
        self.assertIn("dir Z", w[0])

    def test_a_fully_pinned_model_still_refuses_by_name(self):
        res, starter = _convert(self._deck(
            "*BOUNDARY_SPC_SET\n" + _row(1, 0, 1, 1, 1, 1, 1, 1) + "\n"))
        self.assertEqual(_headers(starter, "/CLOAD/"), [], starter)
        w = [x for x in res.warnings
             if "no node with a FREE translational DOF" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("MESSAGE ID 79", w[0])


# ─────────────────────────────────────────────────────────────────────────────
# B4 — the modal chain's beam mass arm (tools/modal_solve.py)
# ─────────────────────────────────────────────────────────────────────────────

_PSD_DECK = ("C:/Users/pmqua/PycharmProjects/FEM_solver/verification/"
             "dynaexamples_r14_ton-mm-s/nvh/example-06-02/"
             "6.2.PSD_Beam_Example_LSTC.k")


def _modal_solve():
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tools = os.path.join(root, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import modal_solve
    return modal_solve


class ModalBeamMassArm(unittest.TestCase):
    """`*SECTION_BEAM` ELFORM 0/1/4/5/11 state THICKNESSES, not section
    constants, so `sec.area` is 0 and every such beam weighed nothing."""

    #: 6.2.PSD's own section: elform 1, CST 0, TS1 6.35, TT1 50.8.
    def test_the_area_comes_from_the_writers_own_derivation(self):
        """6.35 x 50.8 = 322.58 by hand, and that is the number k2rad wrote
        into the deck's emitted `/PROP/BEAM/1` — the property the engine built
        its stiffness matrix from. The derivation is IMPORTED from
        `writer/beams._constants_from_thicknesses`, not repeated."""
        ms = _modal_solve()
        from k2rad.state import SectionBeam
        sec = SectionBeam(secid=1, title="", elform=1, cst=0, ts1=6.35,
                          tt1=50.8)
        self.assertEqual(sec.area, 0.0)
        self.assertAlmostEqual(ms._beam_section_area(sec), 322.58, places=6)

    def test_a_section_that_states_its_constants_is_left_alone(self):
        """ELFORM 2 states A/Iss/Itt directly, so there is nothing to derive
        and the fallback must not fire."""
        ms = _modal_solve()
        from k2rad.state import SectionBeam
        sec = SectionBeam(secid=1, title="", elform=2, cst=0, ts1=6.35,
                          tt1=50.8)
        self.assertEqual(ms._beam_section_area(sec), 0.0)

    def test_the_zero_density_floor_mirrors_the_converters(self):
        """Not a fabrication: the K this module pairs the mass with was
        exported from the CONVERTED .rad, in which k2rad had already written
        1e-24 for a material stating RO <= 0."""
        ms = _modal_solve()
        from k2rad.writer.materials import _ZERO_DENSITY_FLOOR
        st = _dispatch("*KEYWORD\n*MAT_ELASTIC\n"
                       + _row(1, 0.0, 68947.5729, 0.33) + "\n*END\n")
        self.assertEqual(ms._material_rho(st)[1], _ZERO_DENSITY_FLOOR)
        self.assertEqual(ms._material_rho(st, False)[1], 0.0)

    def test_the_two_together_give_the_beam_nodes_mass(self):
        """Hand-computed on 6.2.PSD: 50 elements over 127 mm, so Le = 2.54 and
        m_elem = rho*A*Le = 1e-24 * 322.58 * 2.54 = 8.193532e-22 — split
        evenly, an INTERIOR node carries two halves and gets the whole of it.
        Negligible beside the 2.26842e-4 tip mass (Df/f ~ 1e-18), which is the
        point: the arm exists to give M its RANK back, not to add mass."""
        if not os.path.exists(_PSD_DECK):
            self.skipTest("the R14 deck-only corpus is not on this machine")
        ms = _modal_solve()
        st = ms.parse_deck(_PSD_DECK)
        mass, _inertia = ms.nodal_masses_from_state(st)
        self.assertEqual(len(mass), 51)
        interior = [m for n, m in mass.items() if n not in (1, 2)]
        self.assertEqual(len(interior), 49)
        for m in interior:
            self.assertAlmostEqual(m, 1e-24 * 322.58 * 2.54, delta=1e-30)
        self.assertAlmostEqual(mass[2], 0.00022684179, places=12)
        # ... and with the floor off, every beam node is massless again.
        mass0, _i0 = ms.nodal_masses_from_state(st, zero_density_floor=False)
        self.assertEqual(sorted(n for n, m in mass0.items() if m > 0.0), [2])

    def test_the_rank_guard_names_itself(self):
        """ARPACK's shift-invert operator is `OP = K^-1 M`, whose RANK is the
        number of non-zero mass DOFs; asking for more modes than that breaks
        the Arnoldi factorization and returns -9999 — a failure that reads
        like a singular stiffness matrix and is not one."""
        try:
            import numpy as np
            import scipy.sparse as sp                       # noqa: F401
        except Exception:                                   # pragma: no cover
            self.skipTest("numpy/scipy not installed")
        ms = _modal_solve()
        n = 12
        rows = [(i, i, 1000.0 + i) for i in range(n)]
        K = sp.coo_matrix(
            ([v for _i, _j, v in rows],
             ([i for i, _j, _v in rows], [j for _i, j, _v in rows])),
            shape=(n, n)).tocsc()
        stiff = ms.StiffnessMatrix(
            n_declared=n, gids=np.arange(n), K=K,
            user_node=np.ones(n, dtype=int), dof=np.arange(1, n + 1),
            low_precision=False)
        md = np.zeros(n)
        md[:3] = 1.0e-3
        freq, _phi = ms.solve_modes(stiff, md, 6)
        self.assertEqual(len(freq), 2)          # clamped to rank - 1

    def test_f1_of_6_2_psd_against_its_own_eigout(self):
        """The end-to-end target, on an EXACT stiffness matrix.

        This machine's stock engine prints `/IMPL/PRINT/STIF` with
        `FORMAT(...,E10.2)`, and 2 significant digits destroy a slender beam's
        soft bending mode: the exported matrix gives a NEGATIVE tip stiffness
        and f1 = 334.196 Hz. So the matrix here is assembled exactly, from the
        very section constants k2rad wrote into the deck's own
        `/PROP/BEAM/1` (Area 322.58, Iyy 69371.90427, Izz 1083.936004,
        Ixx 70455.84027) — 50 Euler-Bernoulli elements over 127 mm with the
        root node pinned — and fed through the shipped reader.

        MEASURED: f1 = 110.5541 Hz against the deck's own `.eigout`
        f1 = 110.4521 Hz, **+0.092 %**; the tip stiffness of that matrix is
        109.454 = 3EI/L^3 to six figures; f2 = 884.4330 = f1 x 8 (the
        sqrt(Iyy/Izz) = 8 pair) and f3 = 4422.1651 is the axial mode. The
        control `zero_density_floor=False` on the SAME exact matrix still dies
        ARPACK -9999, so both halves of the arm are necessary.
        """
        if not os.path.exists(_PSD_DECK):
            self.skipTest("the R14 deck-only corpus is not on this machine")
        try:
            import numpy                                    # noqa: F401
            import scipy                                    # noqa: F401
        except Exception:                                   # pragma: no cover
            self.skipTest("numpy/scipy not installed")
        ms = _modal_solve()
        E, nu = 68947.5729, 0.33
        A, iyy, izz, ixx = 322.58, 69371.90427, 1083.936004, 70455.84027
        st = ms.parse_deck(_PSD_DECK)
        order = [nid for _x, nid in
                 sorted((n.x, nid) for nid, n in st.nodes.items())]
        span = st.nodes[order[-1]].x - st.nodes[order[0]].x
        le = span / (len(order) - 1)
        G = E / (2.0 * (1.0 + nu))
        ke = [[0.0] * 12 for _ in range(12)]
        ke[0][0] = ke[6][6] = E * A / le
        ke[0][6] = ke[6][0] = -E * A / le
        ke[3][3] = ke[9][9] = G * ixx / le
        ke[3][9] = ke[9][3] = -G * ixx / le
        for inertia, (t1, t2, r1, r2), sgn in ((izz, (1, 7, 5, 11), 1.0),
                                               (iyy, (2, 8, 4, 10), -1.0)):
            a12 = 12 * E * inertia / le ** 3
            a6 = 6 * E * inertia / le ** 2
            a4, a2 = 4 * E * inertia / le, 2 * E * inertia / le
            ke[t1][t1] += a12; ke[t2][t2] += a12
            ke[t1][t2] -= a12; ke[t2][t1] -= a12
            ke[r1][r1] += a4; ke[r2][r2] += a4
            ke[r1][r2] += a2; ke[r2][r1] += a2
            for t, s in ((t1, 1.0), (t2, -1.0)):
                for r in (r1, r2):
                    ke[t][r] += sgn * s * a6
                    ke[r][t] += sgn * s * a6
        root = order[0]
        dead = {6 * (root - 1) + d for d in range(1, 7)}
        entries = {}
        for e in range(len(order) - 1):
            idx = [6 * (order[e] - 1) + d for d in range(1, 7)] + \
                  [6 * (order[e + 1] - 1) + d for d in range(1, 7)]
            for i in range(12):
                for j in range(12):
                    if ke[i][j] == 0.0 or idx[i] < idx[j]:
                        continue
                    if idx[i] in dead or idx[j] in dead:
                        continue
                    key = (idx[i], idx[j])
                    entries[key] = entries.get(key, 0.0) + ke[i][j]
        ndof = 6 * (len(order) - 1)
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "K")
        with open(path, "w") as fh:
            fh.write(f"{ndof} {ndof} {len(entries)}\n")
            for (ii, jj), v in sorted(entries.items()):
                fh.write(f"{ii:10d}{jj:10d}{v:24.16E}\n")
        stiff = ms.read_stiffness(path)
        self.assertFalse(stiff.low_precision)
        mass, inertia_d = ms.nodal_masses_from_state(st)
        md = ms.build_mass_diagonal(stiff, mass, inertia_d)
        freq, _phi = ms.solve_modes(stiff, md, 1)
        tmp.cleanup()
        self.assertAlmostEqual(freq[0], 110.5541, places=3)
        self.assertLess(abs(freq[0] - 110.4521) / 110.4521, 0.01)
        # the analytic cantilever with the SOFT-axis inertia, hand-derived
        analytic = math.sqrt(
            3 * E * izz / span ** 3 / 0.00022684179) / (2 * math.pi)
        self.assertAlmostEqual(freq[0], analytic, places=3)


# ═════════════════════════════════════════════════════════════════════════════
# A1  *NODE TC/RC -> /GRNOD/NODE + /BCS  (the conversion, the four screens,
#     the opt-out, the free-node interaction and the id allocation)
# ═════════════════════════════════════════════════════════════════════════════

def _n16(nid, x, y, z, tc=None, rc=None) -> str:
    """One fixed-layout ``*NODE`` row, ``(I8,3E16.0,2I8)`` — TC in cols 57-64,
    RC in 65-72 (Vol I R17 p.35-2)."""
    row = f"{nid:>8}{x:>16}{y:>16}{z:>16}"
    if tc is not None or rc is not None:
        row += f"{tc or 0:>8}{rc or 0:>8}"
    return row


def _tcrc_shell_deck(node_rows, extra=()) -> str:
    """A one-shell deck whose four nodes may carry TC/RC cells."""
    return "\n".join(["*KEYWORD", "*NODE", *node_rows,
                      "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4),
                      "*SECTION_SHELL", _row(1, 2),
                      _row("1.0", "1.0", "1.0", "1.0"),
                      "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
                      "*PART", "plate", _row(1, 1, 1),
                      *extra,
                      "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])


def _bcs_group_list(starter: str):
    """``[((Tra, Rot), sorted node ids), ...]`` for every ``/BCS``, in emission
    order — two groups can share a code (a TC/RC ``111 111`` group and the
    implicit free-node group), which a dict would collapse."""
    lines = starter.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith("/BCS/"):
            continue
        card = lines[i + 3]                  # title, column header, then data
        tra, rot, _skew, grnod = card.split()
        out.append(((tra, rot),
                    sorted(_ids(starter, f"/GRNOD/NODE/{int(grnod)}"))))
    return out


def _bcs_groups(starter: str):
    """``{(Tra, Rot): sorted node ids}`` for every ``/BCS`` in the starter."""
    return dict(_bcs_group_list(starter))


class TestNodeTcRcToBcs(unittest.TestCase):
    """``*NODE`` card 1's own TC/RC cells become ``/GRNOD/NODE`` + ``/BCS``.

    The named successor promised by
    ``tests/test_side_defects_review.TestNodeTcRcIsNamed``: that class keeps
    the READING of both card layouts, this one pins what the conversion
    EMITS — the code table, each screen with its own carrier deck, the
    opt-out, the free-node interaction and the id allocation. Every test here
    was written against a mutation the round-2 review proved
    behaviour-changing on a real deck and that the suite did not catch.
    """

    def test_every_code_emits_its_own_digits(self):
        """The 0-7 table of Vol I R17 p.35-2, hand-written so a transposition
        (the 4 <-> 6 swap the review mutated in) fails."""
        want = {1: "100", 2: "010", 3: "001",
                4: "110", 5: "011", 6: "101", 7: "111"}
        for code, digits in want.items():
            with self.subTest(code=code):
                rows = [_n16(1, 0.0, 0.0, 0.0, code, 0),
                        _n16(2, 10.0, 0.0, 0.0), _n16(3, 10.0, 10.0, 0.0),
                        _n16(4, 0.0, 10.0, 0.0)]
                _res, starter = _convert(_tcrc_shell_deck(rows))
                self.assertEqual(_bcs_groups(starter), {(digits, "000"): [1]})

    def test_the_rotation_cell_drives_the_rot_digits(self):
        """TC and RC come from their OWN columns: a deck with TC != RC fails
        if the two fixed slices are swapped."""
        rows = [_n16(1, 0.0, 0.0, 0.0, 1, 2), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)]
        _res, starter = _convert(_tcrc_shell_deck(rows))
        self.assertEqual(_bcs_groups(starter), {("100", "010"): [1]})

    def test_one_group_per_distinct_pair(self):
        rows = [_n16(1, 0.0, 0.0, 0.0, 7, 7), _n16(2, 10.0, 0.0, 0.0, 7, 7),
                _n16(3, 10.0, 10.0, 0.0, 3, 0), _n16(4, 0.0, 10.0, 0.0)]
        _res, starter = _convert(_tcrc_shell_deck(rows))
        self.assertEqual(_bcs_groups(starter),
                         {("111", "111"): [1, 2], ("001", "000"): [3]})

    def test_rule_a_drops_rigid_body_member_nodes(self):
        """A ``*MAT_RIGID`` part's nodes get NO ``/BCS`` — rgbodv.F:150-155
        overwrites it — and the message says so with the count and the ids."""
        rows = [_n16(1, 0.0, 0.0, 0.0, 7, 7), _n16(2, 10.0, 0.0, 0.0, 7, 7),
                _n16(3, 10.0, 10.0, 0.0, 7, 7), _n16(4, 0.0, 10.0, 0.0, 7, 7)]
        deck = "\n".join(["*KEYWORD", "*NODE", *rows,
                          "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4),
                          "*SECTION_SHELL", _row(1, 2),
                          _row("1.0", "1.0", "1.0", "1.0"),
                          "*MAT_RIGID", _row(1, "7.85E-9", "2.1E5", "0.3"),
                          _row("0.0", 0, 0), _row(0, 0, 0),
                          "*PART", "rigid", _row(1, 1, 1),
                          "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        res, starter = _convert(deck)
        self.assertEqual(_bcs_groups(starter), {})
        w = _warns(res, "state a constraint in the card's own TC/RC cells")[0]
        self.assertIn("4 node(s) (node 1, 2, 3, 4) belong to a rigid body", w)
        self.assertIn("rgbodv.F:150-155", w)

    def test_rule_b_leaves_a_driven_dof_to_the_motion(self):
        """A ``*BOUNDARY_PRESCRIBED_MOTION_NODE`` in x clears the x digit and
        keeps the other two."""
        rows = [_n16(1, 0.0, 0.0, 0.0, 7, 0), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)]
        extra = ["*DEFINE_CURVE", _row(9), _row("0.0", "0.0"),
                 _row("1.0", "1.0"),
                 "*BOUNDARY_PRESCRIBED_MOTION_NODE",
                 _row(1, 1, 0, 9, "1.0")]
        res, starter = _convert(_tcrc_shell_deck(rows, extra))
        self.assertEqual(_bcs_groups(starter), {("011", "000"): [1]})
        w = _warns(res, "state a constraint in the card's own TC/RC cells")[0]
        self.assertIn("already driven by a *BOUNDARY_PRESCRIBED_MOTION", w)
        self.assertIn("1 DOF(s) on 1 node(s) (node 1)", w)

    def test_rule_c_merges_a_dof_a_boundary_spc_already_states(self):
        """A ``*BOUNDARY_SPC_NODE`` pinning z removes the z digit, so
        hm_read_bcs.F:198's union is not restated (starter WARNING 312)."""
        rows = [_n16(1, 0.0, 0.0, 0.0, 7, 0), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)]
        extra = ["*BOUNDARY_SPC_NODE", _row(1, 0, 0, 0, 1)]
        res, starter = _convert(_tcrc_shell_deck(rows, extra))
        self.assertEqual(_bcs_groups(starter)[("110", "000")], [1])
        w = _warns(res, "state a constraint in the card's own TC/RC cells")[0]
        self.assertIn("already stated by a *BOUNDARY_SPC", w)
        self.assertIn("1 DOF(s) on 1 node(s) (node 1)", w)

    def test_rule_d_names_a_rotational_code_on_a_rotation_free_mesh(self):
        """A solid-only deck has no rotational DOF (bcs10.F:66's IRODDL gate),
        so an RC code is emitted AND named inert."""
        coords = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0),
                  (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0),
                  (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)]
        rows = [_n16(i + 1, x, y, z, 0, 7) for i, (x, y, z) in enumerate(coords)]
        deck = "\n".join(["*KEYWORD", "*NODE", *rows,
                          "*ELEMENT_SOLID", _row(1, 1),
                          _row(1, 2, 3, 4, 5, 6, 7, 8),
                          "*SECTION_SOLID", _row(1, 1),
                          "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
                          "*PART", "block", _row(1, 1, 1),
                          "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        res, starter = _convert(deck)
        self.assertEqual(sorted(_bcs_groups(starter)), [("000", "111")])
        w = _warns(res, "state a constraint in the card's own TC/RC cells")[0]
        self.assertIn("no rotational DOF at all", w)
        self.assertIn("IF(IRODDL/=0)", w)

    def test_the_opt_out_emits_nothing_and_says_what_is_lost(self):
        rows = [_n16(1, 0.0, 0.0, 0.0, 7, 7), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)]
        res, starter = _convert(_tcrc_shell_deck(rows), node_tc_rc_bcs=False)
        self.assertEqual(_bcs_groups(starter), {})
        self.assertNotIn("node_tc_rc_", starter)
        w = _warns(res, "--no-node-tc-rc-bcs")
        self.assertTrue(w)
        self.assertIn("FREE in the converted model", w[0])

    def test_a_pinned_node_is_not_clamped_twice_by_the_free_node_guard(self):
        """The fifth interaction: ``_make_free_node_constraints`` subtracts a
        node this pass already pinned in all six DOFs — which it learns from
        ``state.node_tc_rc_emitted``."""
        # Node 9 is BOTH an orphan (so the free-node guard wants it) and a
        # TC/RC carrier pinned in all six DOFs (so this pass already has it) —
        # the only shape that reaches the interaction. Node 10 is the control.
        rows = [_n16(1, 0.0, 0.0, 0.0), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0),
                _n16(9, 50.0, 50.0, 50.0, 7, 7),
                _n16(10, 60.0, 60.0, 60.0)]
        extra = ["*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1")]
        _res, starter = _convert(_tcrc_shell_deck(rows, extra))
        groups = _bcs_group_list(starter)
        free = [ids for _key, ids in groups if 10 in ids]
        self.assertTrue(free, f"no free-node group in {groups}")
        self.assertNotIn(9, free[0])
        self.assertEqual(sum(1 for _key, ids in groups if 9 in ids), 1)

    def test_an_out_of_range_code_is_named_and_not_guessed(self):
        rows = [_n16(1, 0.0, 0.0, 0.0, 9, 0), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)]
        res, starter = _convert(_tcrc_shell_deck(rows))
        self.assertEqual(_bcs_groups(starter), {})
        w = _warns(res, "exactly eight")
        self.assertTrue(w)
        self.assertIn("no /BCS", w[0])

    def test_the_group_dodges_a_user_set_on_the_auto_id(self):
        """``/GRNOD`` ids come from ``next_grnod_id()``, so a user
        ``*SET_NODE`` sitting on the id the allocator would actually reach is
        not duplicated (starter ERROR 79) — the #131 probe rule."""
        rows = [_n16(1, 0.0, 0.0, 0.0, 7, 7), _n16(2, 10.0, 0.0, 0.0),
                _n16(3, 10.0, 10.0, 0.0), _n16(4, 0.0, 10.0, 0.0)]
        _res, plain = _convert(_tcrc_shell_deck(rows))
        taken = [int(ln.rsplit("/", 1)[1]) for ln in plain.splitlines()
                 if ln.startswith("/GRNOD/NODE/")]
        self.assertTrue(taken)
        extra = ["*SET_NODE_LIST", _row(taken[0]), _row(2, 3)]
        _res, starter = _convert(_tcrc_shell_deck(rows, extra))
        gids = [int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                if ln.startswith("/GRNOD/NODE/")]
        self.assertEqual(len(gids), len(set(gids)))


# ═════════════════════════════════════════════════════════════════════════════
# A3 (fix round)  the zero-normal initial-penetration policy
# ═════════════════════════════════════════════════════════════════════════════

class TestZeroNormalPenetrationPolicy(unittest.TestCase):
    """``i7pwr3.F:118`` refuses a zero-normal initial penetration unless Inacti
    is 1/2 or Fpenmax is non-zero, and ``:193-199`` deactivates every node with
    ``PENE > Fpenmax*GAPV`` BEFORE the Inacti branches. Four starter runs of
    ``4.3_General_Nonlinearity`` differing only in that cell measured 928
    deactivations at 0.99 against its 486 zero-normal nodes, and exactly 486
    at 0.999999.
    """

    def test_the_constant_is_the_measured_one(self):
        from k2rad.writer import contacts as ct
        self.assertEqual(ct._FPENMAX_ZERO_NORMAL, 0.999999)
        self.assertEqual(ct._FPENMAX_INACTI, (3, 4, 5, 6))

    def test_the_implicit_stub_keeps_the_ordinary_inacti_5(self):
        """Inacti = 1 on the stub zeroes EVERY penetrating node's stiffness and
        cost ``efg/metal-cutting/main.k`` its NORMAL TERMINATION (218 cycles to
        t = 0.03 became a TIMESTEP-LIMIT death at t = 0.0084). The stub is back
        on the ordinary mapping and clears ERROR 611 through Fpenmax."""
        coords = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0),
                  (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0),
                  (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)]
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            *[_n16(i + 1, x, y, z) for i, (x, y, z) in enumerate(coords)],
            "*ELEMENT_SOLID", _row(1, 1), _row(1, 2, 3, 4, 5, 6, 7, 8),
            "*SECTION_SOLID", _row(1, 1),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*PART", "block", _row(1, 1, 1),
            "*BOUNDARY_SPC_NODE", _row(1, 0, 1, 1, 1),
            "*CONTROL_IMPLICIT_GENERAL", _row(1, "0.1"),
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        res, starter = _convert(deck)
        parts = starter.split("auto_implicit_stabilization_self_contact", 1)
        self.assertEqual(len(parts), 2, "no stabilization stub emitted")
        body = parts[1].splitlines()
        inacti_row = [ln for ln in body if ln.startswith("       000")][0]
        self.assertEqual(inacti_row.split()[1], "5")
        fp = [i for i, ln in enumerate(body) if "Fpenmax" in ln][0]
        self.assertEqual(body[fp + 1].split()[-1], "0.999999")
        w = _warns(res, "Implicit model has no contact interface")
        self.assertTrue(w)
        self.assertIn("ordinary Inacti=5", w[0])
        self.assertIn("Inacti=1 was tried and rejected", w[0])

    def test_a_tied_type10_states_itied_1(self):
        """``hm_read_inter_type10.F:188-190``: Itied 0 authorizes rebound, 1
        does not — and ``i7pwr3.F:117`` skips the initial-penetration refusal
        only for a TYPE10 whose Itied is non-zero (measured: 310 x ERROR 612
        -> 0 on 05_4_2_welding_uncoupled_link_d3plot_structuralstep)."""
        from k2rad.writer.contacts import _emit_inter_type10
        lines = _emit_inter_type10(7, "tie", 11, 12, 0.1)
        hdr = [i for i, ln in enumerate(lines) if "ITIED" in ln][0]
        cells = lines[hdr + 1].split()
        self.assertEqual(cells[0], "1")            # Itied
        self.assertEqual(cells[1], "0")            # INACTI


# ═════════════════════════════════════════════════════════════════════════════
# B1 (fix round)  the *SET_<F>_GENERAL clause row: FAMILY-dependent id columns,
#                 and the free/comma forms the manual's own example uses
# ═════════════════════════════════════════════════════════════════════════════

class TestSetGeneralClauseColumns(unittest.TestCase):
    """How many of ``E1..E7`` are entity ids depends on the FAMILY, not just
    the option: Vol I R17 p.43-41 Card 2e types all seven ``I`` for the NODE
    family (``node_general_subgrp.cfg:141`` FREE_CELL_LIST), while p.43-65 /
    ``segment_general_subgrp.cfg:274`` gives the SEGMENT family's
    attribute-bearing options three ids and four floats.
    """

    def test_the_table_is_family_dependent(self):
        from k2rad.state import set_general_id_cols as n
        self.assertEqual(n("NODE", "PART"), 7)
        self.assertEqual(n("NODE", "BOX"), 7)
        self.assertEqual(n("SEGMENT", "PART"), 3)
        self.assertEqual(n("SEGMENT", "SEG"), 4)
        self.assertEqual(n("SEGMENT", "DPART"), 7)   # p.43-70 Remark 4
        self.assertEqual(n("SEGMENT", "DSET"), 7)
        self.assertEqual(n("SHELL", "PART"), 7)
        self.assertEqual(n("PART", "PART"), 7)

    def test_a_node_general_part_clause_takes_all_seven_ids(self):
        """Five parts on one row: cells 4 and 5 are ids too, and a 3-cell
        table would silently drop them."""
        rows = ["*KEYWORD", "*NODE"]
        pid_nodes = {}
        nid = 1
        for pid in range(1, 6):
            base = nid
            for dx in (0.0, 1.0, 1.0, 0.0):
                rows.append(_n16(nid, dx + 10 * pid, 0.0, 0.0))
                nid += 1
            pid_nodes[pid] = list(range(base, base + 4))
        rows.append("*ELEMENT_SHELL")
        for pid, ns in pid_nodes.items():
            rows.append(_row(pid, pid, *ns))
        rows += ["*SECTION_SHELL", _row(1, 2),
                 _row("1.0", "1.0", "1.0", "1.0"),
                 "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3")]
        for pid in pid_nodes:
            rows += ["*PART", f"p{pid}", _row(pid, 1, 1)]
        rows += ["*SET_NODE_GENERAL", _row(77),
                 _grow("PART", 1, 2, 3, 4, 5),
                 "*BOUNDARY_SPC_SET", _row(77, 0, 1, 1, 1, 1, 1, 1),
                 "*CONTROL_TERMINATION", _row("1.0"), "*END", ""]
        st = _dispatch("\n".join(rows))
        from k2rad.writer.mesh import _expand_set_ranges_and_generals
        _expand_set_ranges_and_generals(st)
        self.assertEqual(len(st.node_sets[77][1]), 20)

    def test_a_segment_general_part_clause_ignores_the_attribute_cells(self):
        """``PART 1 0 0 100.0 50.0 1.0 1.0`` — E4..E7 are NFLS/SFLS/FSF/VSF
        (p.43-70 Remark 1), not three more part ids."""
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 1.0, 0.0, 0.0),
            _n16(3, 1.0, 1.0, 0.0), _n16(4, 0.0, 1.0, 0.0),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4),
            "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*PART", "plate", _row(1, 1, 1),
            "*SET_SEGMENT_GENERAL", _row(5),
            f"{'PART':<10}{1:>10}{0:>10}{0:>10}"
            f"{'100.0':>10}{'50.0':>10}{'1.0':>10}{'1.0':>10}",
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        st = _dispatch(deck)
        self.assertEqual(st.set_generals[("SEGMENT", 5)][1],
                         [("PART", [1])])

    def test_the_clause_row_may_be_comma_delimited(self):
        """Vol I R17 p.43-41 writes its own worked example as ``PART, 6``."""
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 1.0, 0.0, 0.0),
            _n16(3, 1.0, 1.0, 0.0), _n16(4, 0.0, 1.0, 0.0),
            "*ELEMENT_SHELL", _row(1, 1, 1, 2, 3, 4),
            "*SECTION_SHELL", _row(1, 2), _row("1.0", "1.0", "1.0", "1.0"),
            "*MAT_ELASTIC", _row(1, "7.85E-9", "2.1E5", "0.3"),
            "*PART", "plate", _row(1, 1, 1),
            "*SET_NODE_GENERAL", _row(8), "PART, 1",
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        st = _dispatch(deck)
        self.assertEqual(st.set_generals[("NODE", 8)][1], [("PART", [1])])
        from k2rad.writer.mesh import _expand_set_ranges_and_generals
        _expand_set_ranges_and_generals(st)
        self.assertEqual(sorted(st.node_sets[8][1]), [1, 2, 3, 4])

    def test_a_generate_range_row_may_be_comma_delimited_too(self):
        deck = "\n".join([
            "*KEYWORD", "*NODE",
            _n16(1, 0.0, 0.0, 0.0), _n16(2, 1.0, 0.0, 0.0),
            _n16(3, 1.0, 1.0, 0.0), _n16(4, 0.0, 1.0, 0.0),
            "*SET_NODE_LIST_GENERATE", _row(4), "1,3",
            "*CONTROL_TERMINATION", _row("1.0"), "*END", ""])
        st = _dispatch(deck)
        from k2rad.writer.mesh import _expand_set_ranges_and_generals
        _expand_set_ranges_and_generals(st)
        self.assertEqual(sorted(st.node_sets[4][1]), [1, 2, 3])

    def test_the_five_operand_part_clause_offsets_every_cell(self):
        """Under ``*INCLUDE_TRANSFORM`` IDPOFF every operand must move: an
        under-counted table leaves the tail behind and the set resolves to the
        WRONG parts at zero diagnostics (the #116 class)."""
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.parser import Block
        b = Block(keyword="SET_NODE_GENERAL", options=[],
                  raw=[_row(7), _grow("PART", 1, 2, 3, 4, 5)])
        _OFFSET_SPECS["SET_NODE_GENERAL"](b, {"p": 300, "s": 20},
                                          lambda *_a, **_k: None)
        self.assertEqual(b.raw[0].strip(), "27")
        self.assertEqual([int(x) for x in b.raw[1][10:].split()],
                         [301, 302, 303, 304, 305])

    def test_a_segment_part_clause_offsets_only_its_three_id_cells(self):
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.parser import Block
        row = (f"{'PART':<10}{1:>10}{2:>10}{3:>10}"
               f"{'100.0':>10}{'50.0':>10}{'1.0':>10}{'1.0':>10}")
        b = Block(keyword="SET_SEGMENT_GENERAL", options=[],
                  raw=[_row(7), row])
        _OFFSET_SPECS["SET_SEGMENT_GENERAL"](b, {"p": 300, "s": 20},
                                             lambda *_a, **_k: None)
        cells = b.raw[1].split()
        self.assertEqual(cells[:4], ["PART", "301", "302", "303"])
        self.assertEqual([float(c) for c in cells[4:]],
                         [100.0, 50.0, 1.0, 1.0])


if __name__ == "__main__":                       # pragma: no cover
    unittest.main()
