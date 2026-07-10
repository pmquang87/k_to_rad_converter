"""Golden-file end-to-end regression fixtures for k2rad.

Each ``tests/fixtures/<name>.k`` is a small, representative LS-DYNA deck.  For
every fixture the checked-in ``tests/fixtures/expected/<name>_0000.rad`` (starter)
and ``<name>_0001.rad`` (engine) capture the EXACT text ``convert()`` produced.
The test reconverts each fixture into a fresh temp dir and asserts the produced
starter+engine text equals the golden byte-for-byte (after normalization), so any
unintended change to the emitted decks is caught as a whole-file diff — something
the substring assertions in tests/test_converter.py cannot do.

Fixtures (each exercises a distinct handler path):
  * shell_explicit.k  — minimal explicit shell: *NODE / *PART / *SECTION_SHELL /
                        *MAT_ELASTIC / *ELEMENT_SHELL / *CONTACT_AUTOMATIC_SINGLE_SURFACE
                        / *CONTROL_TERMINATION.
  * solid_plastic.k   — tet solid with *MAT_PIECEWISE_LINEAR_PLASTICITY and
                        *DATABASE_EXTENT_BINARY (Istrain path).
  * rigid_contact.k   — *MAT_RIGID rigid body + *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE
                        + *LOAD_RIGID_BODY (implicit).
  * tied_weld.k       — *CONTACT_TIED_NODES_TO_SURFACE (/INTER/TYPE2) with a
                        *SET_NODE_LIST slave and *SET_SEGMENT master.
  * implicit_qstat.k  — small implicit quasi-static deck (*CONTROL_IMPLICIT_GENERAL).

Regenerating the goldens
------------------------
When an intentional change to the converter alters the output, regenerate the
checked-in .rad files by running::

    UPDATE_GOLDENS=1 python -m unittest tests.test_golden

That rewrites every ``expected/*.rad`` from the current converter output and
reports which files changed.  Review the diff before committing.

Volatile-content normalization
-------------------------------
Investigation (converting a fixture twice into two different temp dirs and
diffing both the starter and the engine) found the output to be **byte-identical
and fully path-independent**: the .rad files embed no timestamps, no absolute
paths, no run dates and no build/version strings.  The ``2022`` in the /BEGIN
header is the static Radioss block-format version (a constant, not volatile), and
the engine ``/RUN/<name>/1`` line is derived from the deck *title*, not the file
path.  So no normalization is strictly required today.

``_normalize()`` is therefore intentionally minimal but defensive, so the test
stays robust if a future change starts embedding volatile data:
  * The temp directory path is replaced with the placeholder ``<TMPDIR>`` (guards
    against any future absolute-path leak into the deck).
  * Line endings are unified to ``\n`` (convert() writes ``\n`` explicitly, but
    this keeps the golden comparison immune to any checkout that alters EOLs).
Both transforms are applied to the produced AND the golden text before comparing,
so they never mask a real regression between the two.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Make the package importable when tests are run from any directory.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"

# Fixture stems (the <name> in <name>.k / expected/<name>_0000.rad).
FIXTURES = [
    "shell_explicit",
    "solid_plastic",
    "rigid_contact",
    "tied_weld",
    "implicit_qstat",
]

UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"


def _normalize(text: str, tmpdir: str) -> str:
    """Strip/replace volatile content before comparison.

    See the module docstring: the output is currently fully deterministic, so
    this only (a) replaces the run's temp directory with a stable placeholder
    (defensive against a future absolute-path leak) and (b) normalizes EOLs.
    Applied identically to produced and golden text.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if tmpdir:
        text = text.replace(tmpdir, "<TMPDIR>")
    return text


def _convert_fixture(stem: str, tmpdir: str):
    """Copy fixtures/<stem>.k into ``tmpdir`` and convert it there.

    Returns (starter_text, engine_text). Converting inside a temp dir keeps the
    source tree clean and lets _normalize() scrub the temp path if it ever leaks.
    """
    src = FIXTURES_DIR / f"{stem}.k"
    dst = os.path.join(tmpdir, f"{stem}.k")
    shutil.copy(src, dst)
    result = convert(dst, write_log=False)
    starter = Path(result.starter_path).read_text()
    engine = Path(result.engine_path).read_text()
    return starter, engine


class GoldenFileTests(unittest.TestCase):
    """Whole-file starter+engine regression against checked-in goldens."""

    def _check(self, stem: str):
        with tempfile.TemporaryDirectory() as tmp:
            starter, engine = _convert_fixture(stem, tmp)
            for suffix, produced in (("0000", starter), ("0001", engine)):
                golden_path = EXPECTED_DIR / f"{stem}_{suffix}.rad"
                prod_norm = _normalize(produced, tmp)
                if UPDATE:
                    # Store the normalized text so the checked-in golden matches
                    # exactly what the test compares against.
                    old = golden_path.read_text() if golden_path.exists() else None
                    golden_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(golden_path, "w", newline="\n", encoding="utf-8") as fh:
                        fh.write(prod_norm)
                    if old != prod_norm:
                        print(f"UPDATED golden: {golden_path.name}")
                    continue
                self.assertTrue(
                    golden_path.exists(),
                    f"missing golden {golden_path} — regenerate with "
                    f"UPDATE_GOLDENS=1 python -m unittest tests.test_golden",
                )
                golden_norm = _normalize(golden_path.read_text(), tmp)
                self.assertEqual(
                    prod_norm,
                    golden_norm,
                    f"{stem}_{suffix}.rad differs from its golden. If this change "
                    f"is intentional, regenerate with UPDATE_GOLDENS=1 python -m "
                    f"unittest tests.test_golden and review the diff.",
                )

    def test_shell_explicit(self):
        self._check("shell_explicit")

    def test_solid_plastic(self):
        self._check("solid_plastic")

    def test_rigid_contact(self):
        self._check("rigid_contact")

    def test_tied_weld(self):
        self._check("tied_weld")

    def test_implicit_qstat(self):
        self._check("implicit_qstat")

    def test_determinism_second_run_matches_golden(self):
        # Convert every fixture a SECOND time (fresh temp dirs) and confirm the
        # output still matches the golden — guards against nondeterministic output
        # (e.g. dict/set ordering) that a single run would not expose.
        for stem in FIXTURES:
            with self.subTest(fixture=stem):
                with tempfile.TemporaryDirectory() as tmp:
                    starter, engine = _convert_fixture(stem, tmp)
                    for suffix, produced in (("0000", starter), ("0001", engine)):
                        golden_path = EXPECTED_DIR / f"{stem}_{suffix}.rad"
                        if not golden_path.exists():
                            continue
                        self.assertEqual(
                            _normalize(produced, tmp),
                            _normalize(golden_path.read_text(), tmp),
                            f"{stem}_{suffix}.rad not reproducible across runs",
                        )


if __name__ == "__main__":
    unittest.main()
