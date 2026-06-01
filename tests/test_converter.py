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


IMPL_QSTAT_K = """\
*KEYWORD
*TITLE
Implicit QSTAT test
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
*CONTROL_IMPLICIT_GENERAL
         1      0.01
*CONTROL_TERMINATION
       1.0
*END
"""


class ImplicitEngineTests(unittest.TestCase):
    """Engine /IMPL generation: QSTAT/DTSCAL + /IMPL/NONLIN defaults and
    *CONTROL_IMPLICIT_SOLUTION overrides."""

    def _engine_for(self, deck: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "impl.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path).engine_path).read_text()

    def test_qstat_and_nonlin_defaults(self):
        engine = self._engine_for(IMPL_QSTAT_K)
        # Quasi-static (no *CONTROL_IMPLICIT_DYNAMICS) -> QSTAT with strong anchoring.
        self.assertIn("/IMPL/QSTAT/DTSCAL", engine)
        self.assertIn(" 0.1", engine)
        self.assertNotIn(" 1000", engine)
        # Robust nonlinear defaults: reform every 2 iters, force, tol 1e-2.
        self.assertIn("/IMPL/NONLIN/1", engine)
        self.assertIn("2 2 0.01", engine)

    def test_solution_overrides_nonlin(self):
        deck = IMPL_QSTAT_K.replace(
            "*CONTROL_TERMINATION",
            "*CONTROL_IMPLICIT_SOLUTION\n"
            "         2         5         0     0.001     0.005\n"
            "*CONTROL_TERMINATION",
        )
        engine = self._engine_for(deck)
        # ilimit=5 -> L_A=5; ectol=0.005 (rctol unset) -> Itol=1 (energy), Toli=0.005.
        self.assertIn("5 1 0.005", engine)

    def test_blank_leading_card_does_not_corrupt_tolerance(self):
        # A *CONTROL_IMPLICIT_SOLUTION whose first (nsolvr…abstol) card is blank:
        # the blank line is dropped in parsing, so card 2's value shifts into the
        # dctol column and would otherwise emit Toli=2.0 (200%, useless). The
        # converter must reject the implausible tolerance and keep the robust
        # default instead of "2 3 2".
        deck = IMPL_QSTAT_K.replace(
            "*CONTROL_TERMINATION",
            "*CONTROL_IMPLICIT_SOLUTION\n"
            "$#  nsolvr    ilimit    maxref     dctol     ectol     rctol\n"
            "\n"
            "$#   dnorm    diverg     istif   nlprint\n"
            "                              2\n"
            "*CONTROL_TERMINATION",
        )
        engine = self._engine_for(deck)
        self.assertIn("2 2 0.01", engine)
        self.assertNotIn("2 3 2", engine)

    def test_imass_selects_dyna_not_qstat(self):
        deck = IMPL_QSTAT_K.replace(
            "*CONTROL_TERMINATION",
            "*CONTROL_IMPLICIT_DYNAMICS\n"
            "         1       0.6      0.38\n"
            "*CONTROL_TERMINATION",
        )
        engine = self._engine_for(deck)
        self.assertIn("/IMPL/DYNA/2", engine)
        self.assertNotIn("/IMPL/QSTAT", engine)


TRANSDUCER_K = """\
*KEYWORD
*TITLE
Force transducer test
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             0.0             0.0             1.0
       6             1.0             0.0             1.0
       7             1.0             1.0             1.0
       8             0.0             1.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
deformable part
         1         1         1
*PART
rigid pin
         2         1         2
*SECTION_SHELL
         1         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*MAT_RIGID
         2   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SINGLE_SURFACE
         0         0         5         0
       0.1
*CONTACT_FORCE_TRANSDUCER_PENALTY
         2         1         3         3
*CONTROL_TERMINATION
       1.0
*END
"""


class ForceTransducerTests(unittest.TestCase):
    """*CONTACT_FORCE_TRANSDUCER_PENALTY → /INTER/SUB (+ /TH/INTER output)."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_transducer_is_handled_not_skipped(self):
        result, _ = self._convert(TRANSDUCER_K)
        self.assertNotIn("CONTACT_FORCE_TRANSDUCER_PENALTY", result.skipped_keywords)

    def test_emits_inter_sub_with_parent(self):
        _, starter = self._convert(TRANSDUCER_K)
        self.assertIn("/INTER/SUB/", starter)
        # A real parent /INTER/TYPE7 must also be present for the sub to attach to.
        self.assertIn("/INTER/TYPE7/", starter)

    def test_emits_th_inter_for_force_output(self):
        _, starter = self._convert(TRANSDUCER_K)
        self.assertIn("/TH/INTER", starter)

    def test_no_transducer_means_no_th_inter(self):
        # The /TH/INTER block is only added when a transducer exists.
        _, starter = self._convert(TRANSDUCER_K.replace(
            "*CONTACT_FORCE_TRANSDUCER_PENALTY\n         2         1         3         3\n",
            ""))
        self.assertNotIn("/INTER/SUB/", starter)
        self.assertNotIn("/TH/INTER", starter)


DISPCTRL_K = TRANSDUCER_K.replace(
    "*CONTROL_TERMINATION",
    "*DEFINE_CURVE\n"
    "         1         0       1.0       1.0\n"
    "                 0.0                 0.0\n"
    "                 1.0                 1.0\n"
    "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
    "         2         2         2         1       3.5\n"
    "*CONTROL_TERMINATION",
)


class ReactionReadoutTests(unittest.TestCase):
    """*BOUNDARY_PRESCRIBED_MOTION_RIGID → /IMPDISP + /TH/NODE reaction output."""

    def _starter(self, deck: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path).starter_path).read_text()

    def test_imposed_motion_emits_impdisp(self):
        self.assertIn("/IMPDISP/", self._starter(DISPCTRL_K))

    def test_reaction_th_node_with_reac_vars(self):
        starter = self._starter(DISPCTRL_K)
        self.assertIn("/TH/NODE/", starter)
        self.assertIn("REACX", starter)
        self.assertIn("REACY", starter)
        self.assertIn("REACZ", starter)

    def test_no_reaction_th_node_without_prescribed_motion(self):
        # TRANSDUCER_K has the rigid part but no prescribed motion → no reaction block.
        self.assertNotIn("REACX", self._starter(TRANSDUCER_K))


if __name__ == "__main__":
    unittest.main()
