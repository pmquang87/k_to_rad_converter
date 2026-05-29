"""Unit tests for k2rad — runnable with the standard library only::

    python -m unittest discover -s tests

The project has no third-party dependencies, so these tests deliberately
avoid pytest and use unittest.  They cover the parser, a few keyword
handlers, the unit-system header, and a small end-to-end conversion.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the package importable when tests are run from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert  # noqa: E402
from k2rad.parser import (  # noqa: E402
    _split_keyword,
    parse_fixed,
    parse_free,
    parse_k_file,
    to_float,
    to_int,
)


TINY_K = """\
*KEYWORD
*TITLE
Tiny test model
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*PART
shell part
         1         1         1
*SECTION_SHELL
         1         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTROL_TERMINATION
       1.0
*SOME_UNSUPPORTED_KEYWORD
       1.0
*END
"""


class SplitKeywordTests(unittest.TestCase):
    def test_plain_keyword(self):
        self.assertEqual(_split_keyword("CONTROL_IMPLICIT_GENERAL"),
                         ("CONTROL_IMPLICIT_GENERAL", []))

    def test_title_option_stripped(self):
        self.assertEqual(_split_keyword("SET_NODE_LIST_TITLE"),
                         ("SET_NODE_LIST", ["TITLE"]))

    def test_id_option_stripped(self):
        self.assertEqual(_split_keyword("CONTACT_AUTOMATIC_SINGLE_SURFACE_ID"),
                         ("CONTACT_AUTOMATIC_SINGLE_SURFACE", ["ID"]))

    def test_rigid_suffix_is_not_an_option(self):
        self.assertEqual(_split_keyword("BOUNDARY_PRESCRIBED_MOTION_RIGID"),
                         ("BOUNDARY_PRESCRIBED_MOTION_RIGID", []))

    def test_case_insensitive(self):
        self.assertEqual(_split_keyword("node"), ("NODE", []))


class FieldParsingTests(unittest.TestCase):
    def test_parse_fixed_width(self):
        line = "       1       2       3"
        self.assertEqual(parse_fixed(line, n=3, w=8), ["1", "2", "3"])

    def test_parse_free_strips_comment(self):
        self.assertEqual(parse_free("1 2 3 $ a comment"), ["1", "2", "3"])

    def test_to_float_default(self):
        self.assertEqual(to_float("abc", default=1.5), 1.5)
        self.assertEqual(to_float("2.5"), 2.5)

    def test_to_int_from_float_string(self):
        self.assertEqual(to_int("3.0"), 3)
        self.assertEqual(to_int("bad", default=7), 7)


class ParserBlockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tiny.k")
        with open(self.path, "w") as fh:
            fh.write(TINY_K)

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocks_parsed(self):
        blocks = parse_k_file(self.path)
        keywords = [b.keyword for b in blocks]
        self.assertIn("NODE", keywords)
        self.assertIn("ELEMENT_SHELL", keywords)
        self.assertIn("MAT_ELASTIC", keywords)

    def test_comment_lines_skipped(self):
        # Title block keeps exactly one data line.
        blocks = parse_k_file(self.path)
        title = next(b for b in blocks if b.keyword == "TITLE")
        self.assertEqual(title.raw, ["Tiny test model"])


class ConvertEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "tiny.k")
        with open(self.path, "w") as fh:
            fh.write(TINY_K)

    def tearDown(self):
        self.tmp.cleanup()

    def test_files_written(self):
        result = convert(self.path)
        self.assertTrue(os.path.isfile(result.starter_path))
        self.assertTrue(os.path.isfile(result.engine_path))

    def test_title_and_mesh_in_starter(self):
        result = convert(self.path)
        starter = Path(result.starter_path).read_text()
        self.assertIn("Tiny test model", starter)
        self.assertIn("/NODE", starter)
        self.assertIn("/SHELL/1", starter)
        self.assertIn("/MAT/ELAST/1", starter)

    def test_unsupported_keyword_reported(self):
        result = convert(self.path)
        self.assertIn("SOME_UNSUPPORTED_KEYWORD", result.skipped_keywords)

    def test_default_units_are_ton_mm_s(self):
        result = convert(self.path)
        starter = Path(result.starter_path).read_text()
        self.assertIn("Mg", starter)
        self.assertIn("mm", starter)

    def test_custom_units_reach_header(self):
        result = convert(self.path, units=("kg", "m", "s"))
        starter = Path(result.starter_path).read_text()
        header = starter.split("/TITLE")[0]
        self.assertIn("kg", header)
        self.assertIn(" m ", " " + header.replace("\n", " ") + " ")
        self.assertNotIn("Mg", header)


if __name__ == "__main__":
    unittest.main()
