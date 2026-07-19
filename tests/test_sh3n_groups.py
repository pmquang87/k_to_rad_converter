"""Regression tests: 3-node shells must land in /SH3N-flavoured groups.

Since d1ade12 (PR #76) a *ELEMENT_SHELL with only 3 distinct corners is
emitted as a real /SH3N element rather than a collapsed 4-node /SHELL. Any
writer that puts shell element IDs into a group has to split the list by
topology, because the 4-node containers do not resolve a /SH3N ID and fail
SILENTLY -- the group simply comes up short:

  *DATABASE_CROSS_SECTION_* -> /SECT   quads -> /GRSHEL/SHEL via grshel_ID
                                       tris  -> /GRSH3N/SH3N via grtria_ID
  *DATABASE_HISTORY_SHELL   -> /TH     quads -> /TH/SHEL
                                       tris  -> /TH/SH3N

Before the fix the triangle IDs were written into /GRSHEL/SHEL and /TH/SHEL,
so the triangle contributed no force to the cross-section and never appeared
in the T01 -- with no warning anywhere.
"""

import os
import tempfile
import unittest

from k2rad import convert


# A flat plate: two 4-node quads (elements 1 and 2) spanning x = 0..20, plus a
# triangle (element 3) hanging off their top edge, written in LS-DYNA's
# "collapsed quad" form (n1 n2 n3 n3) so the collapse detection is exercised
# too. The cross-section plane x = 15 cuts quad 2 AND the triangle, so both
# grshel_ID and grtria_ID must come out non-zero. The history request names
# all three elements, so the /TH split is exercised on a genuinely mixed list.
MIXED_DECK = """*KEYWORD
*TITLE
mixed quad/tri cut by a plane and named in a history request
*NODE
         1             0.0             0.0             0.0
         2            10.0             0.0             0.0
         3            10.0            10.0             0.0
         4             0.0            10.0             0.0
         5            20.0             0.0             0.0
         6            20.0            10.0             0.0
         7            15.0            20.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       2       5       6       3
       3       1       3       6       7       7
*PART
plate
         1         1         1
*SECTION_SHELL
         1        16
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1     7.85E-9  210000.0       0.3
*SET_PART_LIST
       200
         1
*DATABASE_CROSS_SECTION_PLANE
         0      15.0       5.0       0.0       1.0       0.0       0.0
       0.0       1.0       0.0     100.0     100.0       200
*DATABASE_SECFORC
     1.0E-5
*DATABASE_HISTORY_SHELL
         1         2         3
*CONTROL_TERMINATION
     0.001
*END
"""

QUAD_EIDS = [1, 2]
TRI_EID = 3


def _starter(deck: str) -> str:
    """convert() a deck string and return the starter (_0000.rad) text."""
    tmp = tempfile.TemporaryDirectory()
    try:
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, write_log=False)
        with open(result.starter_path) as fh:
            return fh.read()
    finally:
        tmp.cleanup()


def _all_ints(line: str):
    """The line's tokens as ints, or None if it is not a pure integer row."""
    toks = line.split()
    if not toks:
        return None
    try:
        return [int(t) for t in toks]
    except ValueError:
        return None


def _blocks(text: str, header: str):
    """Every block whose first line starts with *header*, as (id, [int ids]).

    A block runs from its "/KEYWORD/<id>" line to the next "/" line or to the
    HDR ruler, whichever comes first. Non-numeric rows inside the block (the
    title, /TH's "#var1 var2" banner and its "DEF" row) are skipped rather
    than treated as terminators.
    """
    out = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(header):
            continue
        block_id = int(line.rsplit("/", 1)[1])
        ids = []
        for body in lines[i + 1:]:
            if body.startswith("/") or body.startswith("#---"):
                break
            row = _all_ints(body)
            if row is not None:
                ids.extend(row)
        out.append((block_id, ids))
    return out


def _sect_group_fields(text: str):
    """(grshel_ID, grtria_ID) off the /SECT group-reference line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#grbric_ID") and "grtria_ID" in line:
            toks = lines[i + 1].split()
            # grbric grshel grtrus grbeam grsprg grtria Niter Iframe
            return int(toks[1]), int(toks[5])
    raise AssertionError("no /SECT group-reference line in the starter")


class TestSh3nElementEmission(unittest.TestCase):
    """Baseline: the fixture really does produce one /SH3N and two /SHELL."""

    def setUp(self):
        self.starter = _starter(MIXED_DECK)

    def test_triangle_is_emitted_as_sh3n(self):
        sh3n = _blocks(self.starter, "/SH3N/")
        self.assertEqual(len(sh3n), 1, "expected exactly one /SH3N block")
        # rows are "eid n1 n2 n3 0" -> the eid is the first token of the row
        self.assertEqual(sh3n[0][1][0], TRI_EID)

    def test_quads_are_emitted_as_shell(self):
        shell = _blocks(self.starter, "/SHELL/")
        self.assertEqual(len(shell), 1)
        row_len = 6  # eid + 4 nodes + trailing 0
        eids = shell[0][1][::row_len]
        self.assertEqual(eids, QUAD_EIDS)


class TestCrossSectionGroupSplit(unittest.TestCase):
    """*DATABASE_CROSS_SECTION_PLANE -> /SECT grshel_ID + grtria_ID."""

    def setUp(self):
        self.starter = _starter(MIXED_DECK)
        self.grshel_id, self.grtria_id = _sect_group_fields(self.starter)

    def test_grtria_id_is_wired_through(self):
        """grtria_ID was hard-coded 0 before the fix, stranding every /SH3N."""
        self.assertNotEqual(
            self.grtria_id, 0,
            "/SECT grtria_ID is 0, so the cut triangle contributes no force")

    def test_grtria_id_names_a_grsh3n_group_holding_the_triangle(self):
        groups = dict(_blocks(self.starter, "/GRSH3N/SH3N/"))
        self.assertIn(self.grtria_id, groups,
                      "grtria_ID does not name any /GRSH3N/SH3N group")
        self.assertIn(TRI_EID, groups[self.grtria_id])

    def test_triangle_is_not_in_any_grshel_group(self):
        """The actual defect: a /SH3N id in /GRSHEL/SHEL is never resolved."""
        for gid, ids in _blocks(self.starter, "/GRSHEL/SHEL/"):
            self.assertNotIn(
                TRI_EID, ids,
                f"/SH3N element {TRI_EID} was put in 4-node group /GRSHEL/"
                f"SHEL/{gid}, which cannot resolve it")

    def test_cut_quad_still_reaches_the_shell_group(self):
        """The split must not cost the quads their existing routing."""
        self.assertNotEqual(self.grshel_id, 0)
        groups = dict(_blocks(self.starter, "/GRSHEL/SHEL/"))
        self.assertIn(self.grshel_id, groups)
        self.assertIn(2, groups[self.grshel_id])

    def test_the_two_groups_are_distinct(self):
        self.assertNotEqual(self.grshel_id, self.grtria_id)


class TestTimeHistorySplit(unittest.TestCase):
    """*DATABASE_HISTORY_SHELL -> /TH/SHEL for quads, /TH/SH3N for triangles."""

    def setUp(self):
        self.starter = _starter(MIXED_DECK)

    def test_triangle_goes_to_th_sh3n(self):
        blocks = _blocks(self.starter, "/TH/SH3N/")
        self.assertTrue(blocks, "no /TH/SH3N block was emitted")
        self.assertIn(TRI_EID, [i for _, ids in blocks for i in ids])

    def test_triangle_is_not_in_th_shel(self):
        for gid, ids in _blocks(self.starter, "/TH/SHEL/"):
            self.assertNotIn(
                TRI_EID, ids,
                f"/SH3N element {TRI_EID} was requested via /TH/SHEL/{gid}, "
                "which records only 4-node /SHELL -- it is silently absent "
                "from the T01")

    def test_quads_still_go_to_th_shel(self):
        blocks = _blocks(self.starter, "/TH/SHEL/")
        self.assertTrue(blocks, "no /TH/SHEL block was emitted")
        recorded = [i for _, ids in blocks for i in ids]
        for eid in QUAD_EIDS:
            self.assertIn(eid, recorded)

    def test_no_th_block_is_empty(self):
        """An id-less /TH block is a reader error, so the split must not
        emit one when a request turns out to be all-quad or all-triangle."""
        for header in ("/TH/SHEL/", "/TH/SH3N/"):
            for gid, ids in _blocks(self.starter, header):
                self.assertTrue(ids, f"{header}{gid} has no element ids")


class TestPureRequestsAreUnchanged(unittest.TestCase):
    """A request with no triangles must not grow a stray /TH/SH3N or
    /GRSH3N, and one with only triangles must not grow an empty /TH/SHEL."""

    def test_all_quad_history_emits_no_sh3n_block(self):
        deck = MIXED_DECK.replace(
            "*DATABASE_HISTORY_SHELL\n         1         2         3\n",
            "*DATABASE_HISTORY_SHELL\n         1         2\n")
        starter = _starter(deck)
        self.assertEqual(_blocks(starter, "/TH/SH3N/"), [])
        self.assertTrue(_blocks(starter, "/TH/SHEL/"))

    def test_all_triangle_history_emits_no_shel_block(self):
        deck = MIXED_DECK.replace(
            "*DATABASE_HISTORY_SHELL\n         1         2         3\n",
            "*DATABASE_HISTORY_SHELL\n         3\n")
        starter = _starter(deck)
        self.assertEqual(_blocks(starter, "/TH/SHEL/"), [])
        blocks = _blocks(starter, "/TH/SH3N/")
        self.assertTrue(blocks)
        self.assertIn(TRI_EID, [i for _, ids in blocks for i in ids])


if __name__ == "__main__":
    unittest.main()
