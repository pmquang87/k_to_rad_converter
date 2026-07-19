"""The /TH group id namespace is GLOBAL across /TH types, not per type.

Six independent builders emit /TH blocks and they did not share an allocator:
``writer/output.py:_make_starter_th`` numbers its blocks 1..N off a local
counter, while ``_make_starter_th_node_reac`` / ``_th_surf`` / ``_th_node_spc``,
``inistate._make_starter_th_sectio`` and the ``/TH/RWALL`` in ``loads`` all draw
from ``state.next_id()`` (90001+). ``_make_starter_th_inter`` did neither — it
hard-coded ``/TH/INTER/1``.

So any deck asking for BOTH a ``*DATABASE_HISTORY_*`` and a ``*DATABASE_RCFORC``
/ ``*DATABASE_NCFORC`` / ``*CONTACT_FORCE_TRANSDUCER`` got ``/TH/NODE/1`` and
``/TH/INTER/1``, and the OpenRadioss starter refused the whole deck::

    ERROR ID :     79
    ** ERROR: DUPLICATE ID
    DESCRIPTION :
       IN TH GROUP DEFINITION
       ID=1 is DUPLICATED
     .. ERROR ==> NO RESTART FILE

Note the failure is total — no restart file, so the engine cannot run at all —
and nothing in the conversion reported a problem: ``convert()`` returned
success with 0 skipped keywords. That combination (converter says fine, solver
says no) is what the guard in ``_warn_duplicate_th_group_ids`` exists to close:
it scans the emitted deck rather than trusting the builders to agree, so a
seventh /TH builder cannot reintroduce this silently.

Ids are matched on WHOLE LINES throughout. ``/TH/INTER/1`` is a prefix of
``/TH/INTER/10``, so a substring assertion would pass on the unfixed code.
"""

import os
import re
import tempfile
import unittest

from k2rad import convert
from k2rad.state import ConversionState
from k2rad.writer.assembly import _warn_duplicate_th_group_ids

_TH_GROUP_RE = re.compile(r"^/TH/([A-Z0-9_]+)/(\d+)\s*$")


def _convert(deck: str, **opts):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **opts)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _th_groups(starter: str):
    """[(type, id)] for every /TH group header in the deck, whole-line match."""
    out = []
    for ln in starter.splitlines():
        m = _TH_GROUP_RE.match(ln)
        if m:
            out.append((m.group(1), int(m.group(2))))
    return out


_MESH = """*KEYWORD
*NODE
         1             0.0             0.0             0.0
         2            10.0             0.0             0.0
         3            10.0            10.0             0.0
         4             0.0            10.0             0.0
         5            20.0             0.0             0.0
         6            20.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       2       5       6       3
*PART
plate
         1         1         1
*SECTION_SHELL
         1        16
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1     7.85E-9  210000.0       0.3
"""

_CONTACT = """*CONTACT_AUTOMATIC_SINGLE_SURFACE
         0         0         0         0
       0.2       0.2
"""

_TERM = """*CONTROL_TERMINATION
     0.001
*END
"""

# The collision deck: a nodal time history (-> /TH/NODE from the 1..N counter)
# AND rcforc (-> /TH/INTER, formerly the hard-coded 1).
_HISTORY_AND_RCFORC = (_MESH
                       + "*DATABASE_HISTORY_NODE\n         1         2\n"
                       + "*DATABASE_RCFORC\n   1.0E-05\n"
                       + _CONTACT + _TERM)


class TestThGroupIdsAreGloballyUnique(unittest.TestCase):
    def setUp(self):
        self.result, self.starter = _convert(_HISTORY_AND_RCFORC)

    def test_both_blocks_are_actually_emitted(self):
        """Guard the guard: if either block stopped being emitted the
        uniqueness assertion below would pass vacuously."""
        types = {t for t, _ in _th_groups(self.starter)}
        self.assertIn("NODE", types, "the *DATABASE_HISTORY_NODE request "
                                     "produced no /TH/NODE block")
        self.assertIn("INTER", types, "the *DATABASE_RCFORC request produced "
                                      "no /TH/INTER block")

    def test_no_two_th_groups_share_an_id(self):
        """THE regression. Before the fix this deck emitted /TH/NODE/1 and
        /TH/INTER/1 and the starter died with ERROR 79, no restart file."""
        groups = _th_groups(self.starter)
        ids = [i for _t, i in groups]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertFalse(
            dupes,
            f"/TH group id(s) {sorted(dupes)} emitted more than once: "
            f"{groups}. The /TH id namespace is global across types, so the "
            "OpenRadioss starter rejects this deck with ERROR 79 (DUPLICATE "
            "ID, IN TH GROUP DEFINITION) and writes no restart file")

    def test_th_inter_id_is_allocated_not_hardcoded(self):
        """It must come from state.next_id() (the 90001+ auto-id band), which
        is what keeps it clear of _make_starter_th's local 1..N counter."""
        inter = [i for t, i in _th_groups(self.starter) if t == "INTER"]
        self.assertEqual(len(inter), 1)
        self.assertGreaterEqual(
            inter[0], 90001,
            "/TH/INTER must draw its id from the auto-id allocator, not a "
            f"literal; got {inter[0]}")

    def test_conversion_reports_no_duplicate_warning(self):
        for w in self.result.warnings:
            self.assertNotIn("is emitted by more than one /TH block", w)


class TestDuplicateThGuard(unittest.TestCase):
    """The guard itself, driven directly — a seventh /TH builder must not be
    able to reintroduce the collision without the converter saying so."""

    def test_guard_fires_on_a_collision(self):
        state = ConversionState()
        _warn_duplicate_th_group_ids(state, [
            "/TH/NODE/1", "TH_NODE_1", "DEF", "         7",
            "/TH/INTER/1", "TH_interface_forces", "DEF", "     90001",
        ])
        self.assertTrue(
            any("group id 1 is emitted by more than one /TH block" in w
                and "ERROR 79" in w for w in state.warnings),
            f"the guard stayed silent on a collision; warnings={state.warnings}")

    def test_guard_is_silent_on_distinct_ids(self):
        state = ConversionState()
        _warn_duplicate_th_group_ids(state, [
            "/TH/NODE/1", "/TH/INTER/90031", "/TH/SECTIO/90032",
        ])
        self.assertEqual(
            [w for w in state.warnings if "/TH block" in w], [])

    def test_guard_matches_whole_lines_only(self):
        """/TH/INTER/1 is a prefix of /TH/INTER/10; a substring-based guard
        would report a false collision here (and, worse, the mirror-image
        assertion in a test would pass on unfixed code)."""
        state = ConversionState()
        _warn_duplicate_th_group_ids(state, ["/TH/NODE/1", "/TH/INTER/10"])
        self.assertEqual(
            [w for w in state.warnings if "/TH block" in w], [])


if __name__ == "__main__":
    unittest.main()
