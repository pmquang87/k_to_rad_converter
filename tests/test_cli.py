"""CLI-boundary tests for k2rad.cli.

These drive k2rad.cli.main(argv=...) directly (argparse + exit codes + the
--inter-gapmin/--units/--suggest-gapmin plumbing), which the main
tests/test_converter.py suite bypasses by calling convert() with kwargs.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import cli  # noqa: E402


MINI_K = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "*PART\n"
    "plate\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2\n"
    "       0.1\n"
    "*MAT_ELASTIC\n"
    "         1    7.8E-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


def _run(argv):
    """Run cli.main(argv); return (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kpath = os.path.join(self.tmp.name, "model.k")
        with open(self.kpath, "w") as fh:
            fh.write(MINI_K)

    def test_missing_input_returns_1(self):
        rc, _out, err = _run([os.path.join(self.tmp.name, "nope.k"), "--quiet"])
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_basic_conversion_writes_rad_files(self):
        rc, out, _err = _run([self.kpath, "--quiet"])
        self.assertEqual(rc, 0)
        stem = os.path.join(self.tmp.name, "model")
        self.assertTrue(os.path.exists(stem + "_0000.rad"))
        self.assertTrue(os.path.exists(stem + "_0001.rad"))
        self.assertIn("Conversion complete", out)

    def test_output_stem_positional(self):
        stem = os.path.join(self.tmp.name, "sub", "out")
        os.makedirs(os.path.dirname(stem))
        rc, _out, _err = _run([self.kpath, stem, "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(stem + "_0000.rad"))

    def test_units_labels_reach_begin_header(self):
        rc, _out, _err = _run([self.kpath, "--units", "kg", "m", "s", "--quiet"])
        self.assertEqual(rc, 0)
        starter = Path(os.path.join(self.tmp.name, "model_0000.rad")).read_text()
        begin = starter.split("/BEGIN")[1].splitlines()
        # The unit labels appear on the /BEGIN unit-system cards.
        self.assertTrue(any("kg" in ln for ln in begin[:8]))

    def test_inter_gapmin_bad_format_returns_1(self):
        rc, _out, err = _run([self.kpath, "--inter-gapmin", "3", "--quiet"])
        self.assertEqual(rc, 1)
        self.assertIn("ID=VAL", err)

    def test_inter_gapmin_non_numeric_returns_1(self):
        rc, _out, err = _run([self.kpath, "--inter-gapmin", "abc=xyz", "--quiet"])
        self.assertEqual(rc, 1)
        self.assertIn("numeric", err)

    def test_inter_gapmin_valid_pair_parsed(self):
        # A valid pair on a deck with no matching interface still converts fine.
        rc, _out, _err = _run([self.kpath, "--inter-gapmin", "7=0.05", "--quiet"])
        self.assertEqual(rc, 0)

    def test_suggest_gapmin_exits_without_converting(self):
        # Read-only mode: prints suggestions/notes and does NOT write .rad files.
        rc, out, _err = _run([self.kpath, "--suggest-gapmin"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "model_0000.rad")))
        self.assertIn("clearance", out.lower())

    def test_build_parser_defaults(self):
        args = cli.build_parser().parse_args([self.kpath])
        self.assertEqual(tuple(args.units), ("Mg", "mm", "s"))
        self.assertEqual(args.gapmin_factor, 0.8)
        self.assertTrue(args.rigid_cog_master)      # BooleanOptionalAction default
        self.assertFalse(args.ams)
        self.assertEqual(args.inter_gapmin, [])

    def test_no_such_flag_errors(self):
        # argparse exits with SystemExit(2) on an unknown option.
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([self.kpath, "--does-not-exist"])


if __name__ == "__main__":
    unittest.main()
