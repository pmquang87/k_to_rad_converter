"""Tests for the ROADMAP keyword/lossy conversions added in the coverage pass.

Kept in a separate module from tests/test_converter.py so the additions do not
collide with other in-flight work on that large file.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch, _sample_curve_function
from k2rad.state import ConversionState


def _convert(deck: str):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


def _dispatch(deck: str) -> ConversionState:
    """Parse + dispatch a deck string into a fresh ConversionState."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


# Two rigid quad-shell parts, optionally merged by *CONSTRAINED_RIGID_BODIES.
TWO_RIGID = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             2.0             0.0             0.0\n"
    "       6             3.0             0.0             0.0\n"
    "       7             3.0             1.0             0.0\n"
    "       8             2.0             1.0             0.0\n"
    "*PART\n"
    "rigidA\n"
    "         1         1         1\n"
    "*PART\n"
    "rigidB\n"
    "         2         1         2\n"
    "*SECTION_SHELL\n"
    "         1         2\n"
    "       1.0\n"
    "*MAT_RIGID\n"
    "         1   7.86e-9  210000.0       0.3\n"
    "*MAT_RIGID\n"
    "         2   7.86e-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       2       5       6       7       8\n"
    "{MERGE}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


class ConstrainedRigidBodiesTests(unittest.TestCase):
    def test_two_rigid_parts_merge_to_one_rbody(self):
        merged = TWO_RIGID.replace(
            "{MERGE}", "*CONSTRAINED_RIGID_BODIES\n         1         2\n")
        _, starter = _convert(merged)
        self.assertEqual(starter.count("/RBODY/"), 1,
                         "merged rigid bodies must emit a single /RBODY")

    def test_unmerged_two_rigid_parts_emit_two_rbodies(self):
        unmerged = TWO_RIGID.replace("{MERGE}", "")
        _, starter = _convert(unmerged)
        self.assertEqual(starter.count("/RBODY/"), 2)

    def test_handler_records_pair(self):
        merged = TWO_RIGID.replace(
            "{MERGE}", "*CONSTRAINED_RIGID_BODIES\n         1         2\n")
        state = _dispatch(merged)
        self.assertIn((1, 2), state.rigid_body_merges)

    def test_non_rigid_merge_warns(self):
        # PID 2 is deformable here → merge should be refused with a warning.
        deck = TWO_RIGID.replace(
            "*MAT_RIGID\n         2   7.86e-9  210000.0       0.3\n",
            "*MAT_ELASTIC\n         2   7.86e-9  210000.0       0.3\n").replace(
            "{MERGE}", "*CONSTRAINED_RIGID_BODIES\n         1         2\n")
        result, _ = _convert(deck)
        self.assertTrue(any("CONSTRAINED_RIGID_BODIES" in w for w in result.warnings))


class EosC6WarningTests(unittest.TestCase):
    DECK = (
        "*KEYWORD\n"
        "*EOS_LINEAR_POLYNOMIAL\n"
        "         9       0.0       1.0       2.0       0.0       0.0       0.0     5.0\n"
        "       0.0       1.0\n"
        "*END\n"
    )

    def test_c6_nonzero_warns(self):
        state = _dispatch(self.DECK)
        self.assertTrue(any("C6" in w for w in state.warnings))

    def test_c0_c5_still_parsed(self):
        state = _dispatch(self.DECK)
        eos = state.eos_cards[9]
        self.assertEqual(eos.params["c1"], 1.0)
        self.assertEqual(eos.params["c2"], 2.0)


class ContactTiebreakTests(unittest.TestCase):
    DECK = (
        "*KEYWORD\n"
        "*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2             1.0             0.0             0.0\n"
        "       3             1.0             1.0             0.0\n"
        "       4             0.0             1.0             0.0\n"
        "*PART\n"
        "p\n"
        "         1         1         1\n"
        "*SECTION_SHELL\n"
        "         1         2\n"
        "       0.1\n"
        "*MAT_ELASTIC\n"
        "         1    7.8E-9  210000.0       0.3\n"
        "*ELEMENT_SHELL\n"
        "       1       1       1       2       3       4\n"
        "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK\n"
        "         0         0         0         0\n"
        "       0.1       0.1\n"
        "*CONTROL_TERMINATION\n"
        "       1.0\n"
        "*END\n"
    )

    def test_records_contact_and_warns(self):
        # The tiebreak delegates to the surface-to-surface (TYPE7) path and warns
        # that the cohesive bond is dropped. (A rendered /INTER/TYPE7 needs real
        # resolved surfaces; here we assert the contact is recorded + the warning.)
        state = _dispatch(self.DECK)
        self.assertEqual(len(state.contacts_surf2surf), 1)
        self.assertNotIn(
            "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK", state.skipped_keywords)
        self.assertTrue(any("TIEBREAK" in w and "DROPPED" in w for w in state.warnings))


class DefineCurveFunctionTests(unittest.TestCase):
    def test_sampler_accepts_pure_expression(self):
        pts = _sample_curve_function("sin(2*pi*x)", 1.0, npts=11)
        self.assertIsNotNone(pts)
        self.assertEqual(len(pts), 11)
        self.assertAlmostEqual(pts[0][0], 0.0)
        self.assertAlmostEqual(pts[-1][0], 1.0)

    def test_sampler_rejects_unknown_identifier(self):
        # A free parameter (A) that is not the abscissa variable → not sampleable.
        self.assertIsNone(_sample_curve_function("A*sin(x)", 1.0))

    def test_sampler_rejects_constant_expression(self):
        self.assertIsNone(_sample_curve_function("3.0*2.0", 1.0))

    def test_curve_function_becomes_funct(self):
        deck = (
            "*KEYWORD\n"
            "*DEFINE_CURVE_FUNCTION\n"
            "         7\n"
            "sin(2*pi*x)\n"
            "*CONTROL_TERMINATION\n"
            "       1.0\n"
            "*END\n"
        )
        state = _dispatch(deck)
        self.assertIn(7, state.curves)
        self.assertGreater(len(state.curves[7].pts), 10)

    def test_curve_function_unsupported_skipped(self):
        deck = (
            "*KEYWORD\n"
            "*DEFINE_CURVE_FUNCTION\n"
            "         8\n"
            "LC(3,x) + A\n"
            "*CONTROL_TERMINATION\n"
            "       1.0\n"
            "*END\n"
        )
        state = _dispatch(deck)
        self.assertNotIn(8, state.curves)
        self.assertIn("DEFINE_CURVE_FUNCTION", state.skipped_keywords)


if __name__ == "__main__":
    unittest.main()
