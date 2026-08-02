"""Tests for the orphan-element guard (writer/assembly.py::_warn_orphan_elements).

An element carries the id of the ``*PART`` it belongs to, and k2rad emits
elements from INSIDE the ``for pid, part in sorted(state.parts.items())`` loop
of ``writer/mesh.py::_make_parts_and_elements`` (spring/damper connectors the
same way, from the per-part loops in ``writer/loads.py``). So an element whose
PID has no ``PartData`` is never reached — the loop does not visit that id, the
element is not written, and nothing further down notices, because the starter
only ever sees what was written.

That is silent MESH LOSS, and it is the worst class of converter defect: the
produced deck is valid, it runs to NORMAL TERMINATION, and it is simply not the
model the user drew — lighter, softer, and missing whatever contact surface
those elements carried. It is exactly what happened to every ``*PART_COMPOSITE``
part before that keyword got a handler (see the CHANGELOG entry), and the same
silence covers an ``*INCLUDE`` that did not resolve, a PID typo, a deck
assembled from a subset of its parts, or any future ``*PART`` variant the parser
does not recognize.

The guard therefore does not try to repair anything — it makes the loss loud,
naming every missing PID and how many elements of each type went with it.

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_gravity.py, tests/test_connectors.py and tests/test_joints.py).
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                                    # noqa: E402
from k2rad.state import (ConversionState, BeamElem,          # noqa: E402
                         PartData, ShellElem, SolidElem)
from k2rad.writer.assembly import _warn_orphan_elements      # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"

# The marker every orphan warning carries (the CLI prints state.warnings
# verbatim, so this is what the user greps for).
MARKER = "MESH LOSS"


# ─────────────────────────────────────────────────────────────────────────────
# Deck fragments
#
# Nodes 1-4 = the one REAL part (1). Nodes 5-12 exist so orphaned solids/beams
# have somewhere to attach — those elements name part ids no *PART defines.
# ─────────────────────────────────────────────────────────────────────────────

HEAD = """\
*KEYWORD
*TITLE
orphan element test deck
*CONTROL_TERMINATION
      0.01
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             2.0             0.0             0.0
       6             3.0             0.0             0.0
       7             3.0             1.0             0.0
       8             2.0             1.0             0.0
       9             2.0             0.0             1.0
      10             3.0             0.0             1.0
      11             3.0             1.0             1.0
      12             2.0             1.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*PART
real plate
         1         1         1
*SECTION_SHELL
         1         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
"""

# two shells + one solid + one beam, all on part ids that do not exist
ORPHAN_SHELLS = """\
*ELEMENT_SHELL
       2      77       5       6       7       8
       3      77       9      10      11      12
"""

ORPHAN_SOLID = """\
*ELEMENT_SOLID
     100      88       5       6       7       8       9      10      11      12
"""

ORPHAN_BEAM = """\
*ELEMENT_BEAM
     200      88       5       6
"""

ORPHAN_DISCRETE = """\
*ELEMENT_DISCRETE
     300      99       5       6
"""

END = "*END\n"


def _convert(deck, **kw):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path, encoding="utf-8") as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _orphan_warnings(result):
    return [w for w in result.warnings if MARKER in w]


def _the_orphan_warning(testcase, result):
    """The single orphan warning — asserting there is exactly one."""
    hits = _orphan_warnings(result)
    testcase.assertEqual(1, len(hits),
                         f"expected exactly one {MARKER} warning, got: {hits}")
    return hits[0]


# ─────────────────────────────────────────────────────────────────────────────


class OrphanElementWarningTests(unittest.TestCase):
    """A deck whose elements name a part id no *PART defines must say so."""

    def test_shells_on_missing_part_warn_with_counts(self):
        result, _ = _convert(HEAD + ORPHAN_SHELLS + END)
        w = _the_orphan_warning(self, result)
        self.assertIn("2 element(s)", w)
        self.assertIn("1 part id(s)", w)
        self.assertIn("PID 77 (2 shell)", w)

    def test_counts_are_split_per_pid_and_per_element_type(self):
        result, _ = _convert(HEAD + ORPHAN_SHELLS + ORPHAN_SOLID
                             + ORPHAN_BEAM + END)
        w = _the_orphan_warning(self, result)
        # 2 shells on 77; 1 solid + 1 beam on 88
        self.assertIn("4 element(s)", w)
        self.assertIn("2 part id(s)", w)
        self.assertIn("PID 77 (2 shell)", w)
        self.assertIn("PID 88 (1 solid, 1 beam)", w)
        # PIDs are listed in ascending order, so the message is stable
        self.assertLess(w.index("PID 77"), w.index("PID 88"))

    def test_discrete_elements_are_covered(self):
        # *ELEMENT_DISCRETE is the one store that already had a guard of its own
        # (_make_discrete_springs warns per part). It is scanned here anyway so
        # this stays the single place that answers "did I lose any mesh?".
        result, _ = _convert(HEAD + ORPHAN_DISCRETE + END)
        w = _the_orphan_warning(self, result)
        self.assertIn("PID 99 (1 discrete)", w)

    def test_warning_names_the_cause_and_the_consequence(self):
        result, _ = _convert(HEAD + ORPHAN_SHELLS + END)
        w = _the_orphan_warning(self, result)
        self.assertIn("*PART", w)
        self.assertIn("NOT in the converted deck", w)

    def test_the_loss_the_warning_describes_is_real(self):
        # The orphaned elements are genuinely absent — the warning is not
        # describing a hypothetical.
        _, starter = _convert(HEAD + ORPHAN_SHELLS + ORPHAN_SOLID
                              + ORPHAN_BEAM + END)
        self.assertIn("/PART/1", starter)          # the real part IS emitted
        self.assertNotIn("/PART/77", starter)
        self.assertNotIn("/PART/88", starter)
        self.assertNotIn("/SHELL/77", starter)
        self.assertNotIn("/BRICK/88", starter)
        self.assertNotIn("/BEAM/88", starter)

    def test_deck_with_no_parts_at_all_warns_for_everything(self):
        # state.parts empty → _make_parts_and_elements returns early and the
        # whole mesh is lost. The most catastrophic case, and the quietest one
        # before this guard.
        deck = ("*KEYWORD\n*TITLE\nno parts\n*CONTROL_TERMINATION\n      0.01\n"
                "*NODE\n"
                "       1             0.0             0.0             0.0\n"
                "       2             1.0             0.0             0.0\n"
                "       3             1.0             1.0             0.0\n"
                "       4             0.0             1.0             0.0\n"
                "*ELEMENT_SHELL\n"
                "       1       5       1       2       3       4\n"
                + END)
        result, _ = _convert(deck)
        w = _the_orphan_warning(self, result)
        self.assertIn("1 element(s)", w)
        self.assertIn("PID 5 (1 shell)", w)


class NoFalsePositiveTests(unittest.TestCase):
    """A deck whose element PIDs all resolve must stay silent — and unchanged."""

    def test_clean_deck_does_not_warn(self):
        result, _ = _convert(HEAD + END)
        self.assertEqual([], _orphan_warnings(result))

    def test_clean_deck_with_every_element_type_does_not_warn(self):
        # Same element mix as the orphan decks above, but every PID now has a
        # *PART: the guard must key on the part id, not on the element type.
        deck = (HEAD
                + ORPHAN_SHELLS.replace("      77", "       1")
                + ORPHAN_SOLID.replace("      88", "       2")
                + ORPHAN_BEAM.replace("      88", "       3")
                + "*PART\nsolid block\n         2         2         1\n"
                  "*SECTION_SOLID\n         2         1\n"
                  "*PART\nbeam\n         3         3         1\n"
                  "*SECTION_BEAM\n         3         2       1.0\n"
                  "      10.0      10.0      10.0      10.0\n"
                + END)
        result, _ = _convert(deck)
        self.assertEqual([], _orphan_warnings(result))

    def test_golden_fixture_output_is_byte_identical(self):
        # The guard is a read-only prepass: it must not perturb a single byte of
        # a deck it has nothing to say about.
        stem = "shell_explicit"
        with tempfile.TemporaryDirectory() as tmp:
            src = FIXTURES_DIR / f"{stem}.k"
            dst = os.path.join(tmp, f"{stem}.k")
            shutil.copy(src, dst)
            result = convert(dst, write_log=False)
            for suffix, path in (("0000", result.starter_path),
                                 ("0001", result.engine_path)):
                produced = Path(path).read_text().replace("\r\n", "\n")
                golden = (EXPECTED_DIR / f"{stem}_{suffix}.rad"
                          ).read_text().replace("\r\n", "\n")
                self.assertEqual(golden, produced,
                                 f"{stem}_{suffix}.rad changed")
            self.assertEqual([], _orphan_warnings(result))


class OrphanMessageShapeTests(unittest.TestCase):
    """Unit-level checks on the message itself (no .k round trip needed)."""

    def _state_with_orphans(self, n_pids, per_pid=1):
        state = ConversionState()
        state.parts[1] = PartData(1, "real", 1, 1)
        state.shell_elems.append(ShellElem(1, 1, [1, 2, 3, 4]))
        eid = 100
        for pid in range(1001, 1001 + n_pids):
            for _ in range(per_pid):
                state.shell_elems.append(ShellElem(eid, pid, [1, 2, 3, 4]))
                eid += 1
        return state

    def test_pid_list_is_capped_but_the_total_is_exact(self):
        state = self._state_with_orphans(20, per_pid=3)
        _warn_orphan_elements(state)
        w = state.warnings[0]
        self.assertIn("60 element(s)", w)          # 20 pids x 3
        self.assertIn("20 part id(s)", w)
        self.assertIn("PID 1001 (3 shell)", w)     # lowest ids are the ones shown
        self.assertIn("PID 1012 (3 shell)", w)     # 12th = the cap
        self.assertNotIn("PID 1013", w)
        self.assertIn("and 8 more part id(s)", w)

    def test_no_orphans_no_warning(self):
        state = ConversionState()
        state.parts[1] = PartData(1, "real", 1, 1)
        state.shell_elems.append(ShellElem(1, 1, [1, 2, 3, 4]))
        state.solid_elems.append(SolidElem(2, 1, [1, 2, 3, 4]))
        state.beam_elems.append(BeamElem(3, 1, 1, 2, 3))
        _warn_orphan_elements(state)
        self.assertEqual([], state.warnings)

    def test_empty_state_is_a_no_op(self):
        state = ConversionState()
        _warn_orphan_elements(state)
        self.assertEqual([], state.warnings)

    def test_one_warning_covers_all_element_stores(self):
        state = ConversionState()
        state.shell_elems.append(ShellElem(1, 42, [1, 2, 3, 4]))
        state.solid_elems.append(SolidElem(2, 42, [1, 2, 3, 4]))
        state.beam_elems.append(BeamElem(3, 42, 1, 2, 3))
        _warn_orphan_elements(state)
        self.assertEqual(1, len(state.warnings))
        self.assertIn("PID 42 (1 shell, 1 solid, 1 beam)", state.warnings[0])


if __name__ == "__main__":
    unittest.main()
