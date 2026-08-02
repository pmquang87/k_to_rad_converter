"""Unit tests for k2rad — runnable with the standard library only::

    python -m unittest discover -s tests

The project has no third-party dependencies, so these tests deliberately
avoid pytest and use unittest.  They cover the parser, a few keyword
handlers, the unit-system header, and a small end-to-end conversion.
"""

import math
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

# Make the package importable when tests are run from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert  # noqa: E402
from k2rad.handlers import dispatch  # noqa: E402
from k2rad.state import (  # noqa: E402
    ConversionState,
    ContactAutoSingle,
    ContactAutoSurf2Surf,
    CoordNodes,
    NodeData,
    PartData,
    ShellElem,
    SolidElem,
)
from k2rad.gapmin import (  # noqa: E402
    apply_auto_gapmin,
    fast_proximity_available,
    min_point_to_triangles,
    point_triangle_distance,
    suggest_gapmins,
)
from k2rad.writer import _skew_axes_from_nodes  # noqa: E402
from k2rad.parser import (  # noqa: E402
    Block,
    _split_keyword,
    parse_fixed,
    parse_free,
    parse_k_file,
    to_float,
    to_int,
)

# tools/modal_solve.py (offline eigensolver for the modal stiffness-export
# recipe) lives outside the package; its scipy-dependent tests self-skip.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import modal_solve  # noqa: E402
# the modal post-processing tools guard numpy the same way (their
# numpy-dependent tests self-skip; the d3plot writer also needs lasso-python)
import modal_common  # noqa: E402
import modal_shapes_export  # noqa: E402
import modal_random_response  # noqa: E402


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


def _th_comment_lines(starter, th_title):
    """The run of "#" comment lines between a /TH block's title line and its
    variable line, joined with newlines.

    Scoped to that one block (it stops at the first non-comment line), so an
    assertion on the text cannot be satisfied by an unrelated comment further
    down the deck.
    """
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.strip() == th_title)
    out = []
    for ln in lines[i + 1:]:
        if not ln.startswith("#"):
            break
        out.append(ln)
    return "\n".join(out)


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

    def test_to_float_fortran_eless_exponent(self):
        # LS-DYNA drops the 'E' to fit a 10-col field: "7.85000-9" == 7.85e-9.
        self.assertAlmostEqual(to_float("7.85000-9"), 7.85e-9)
        self.assertAlmostEqual(to_float("1.5+10"), 1.5e10)
        self.assertAlmostEqual(to_float("-2.7-9"), -2.7e-9)

    def test_to_float_fortran_d_exponent(self):
        self.assertAlmostEqual(to_float("7.85D-9"), 7.85e-9)
        self.assertAlmostEqual(to_float("1.5d9"), 1.5e9)

    def test_to_float_normal_forms_unchanged(self):
        # The repair is a fallback; well-formed numbers parse as before.
        for s, v in [("210000.00", 210000.0), ("0.300", 0.3),
                     ("1.5e-9", 1.5e-9), ("1.5E+9", 1.5e9), ("100", 100.0)]:
            self.assertAlmostEqual(to_float(s), v)
        self.assertEqual(to_float(""), 0.0)
        self.assertEqual(to_float("abc"), 0.0)

    def test_to_int_fortran_exponent(self):
        # Routed through to_float, so an E-less exponent is honoured.
        self.assertEqual(to_int("1+1"), 10)


class NodeFixedFormatTests(unittest.TestCase):
    """*NODE in the standard fixed I8+3E16 layout: a negative coordinate fills
    its 16-char field completely and glues onto the previous field, which a
    whitespace split mis-reads — such nodes used to be dropped silently (an
    entire plate at z < 0 vanished from the panel-tool decks)."""

    def test_glued_negative_z_is_parsed(self):
        state = ConversionState()
        dispatch(Block("NODE", [], [
            " 1000001 0.000000000e+00 0.000000000e+00-1.250000000e+00",
        ]), state)
        nd = state.nodes[1000001]
        self.assertEqual((nd.x, nd.y, nd.z), (0.0, 0.0, -1.25))

    def test_all_coordinates_glued(self):
        state = ConversionState()
        dispatch(Block("NODE", [], [
            " 1000002-1.000000000e+01-2.000000000e+01-3.000000000e+00",
        ]), state)
        nd = state.nodes[1000002]
        self.assertEqual((nd.x, nd.y, nd.z), (-10.0, -20.0, -3.0))

    def test_glue_with_trailing_tc_rc_fields(self):
        # Enough whitespace tokens (>= 4) but one is an over-long merged pair —
        # must still be recognised as fixed format.
        state = ConversionState()
        dispatch(Block("NODE", [], [
            " 1000003 1.000000000e+00-1.250000000e+00 2.000000000e+00       0       0",
        ]), state)
        nd = state.nodes[1000003]
        self.assertEqual((nd.x, nd.y, nd.z), (1.0, -1.25, 2.0))

    def test_free_format_unchanged(self):
        state = ConversionState()
        dispatch(Block("NODE", [], ["5 1.0 2.0 -3.0"]), state)
        nd = state.nodes[5]
        self.assertEqual((nd.x, nd.y, nd.z), (1.0, 2.0, -3.0))


class ElementDenseFixedFormatTests(unittest.TestCase):
    """Element connectivity in the dense fixed I8 layout: an 8-digit id fills
    its whole field and glues onto the next one, so a whitespace split
    under-counts the fields.  Decks with ids >= 10,000,000 (e.g. LS-PrePost
    output) used to lose every such element silently — the panel-tool
    platen/stripe meshes at ids 90,000,001+ converted to .rad decks whose
    rigid parts reported "no elements found"."""

    @staticmethod
    def _dense(*vals):
        """Right-justified I8 fields, no separators (LS-PrePost dense form)."""
        return "".join("%8d" % v for v in vals)

    def test_dense_shell_quad(self):
        # eid=90000001 pid=91 n1..n4 — whitespace-splits into just two tokens
        # ("90000001" and the 34-char glued remainder).
        state = ConversionState()
        dispatch(Block("ELEMENT_SHELL", [], [
            "90000001      9190000001900000409000004190000002",
        ]), state)
        self.assertEqual(len(state.shell_elems), 1)
        el = state.shell_elems[0]
        self.assertEqual(el.eid, 90000001)
        self.assertEqual(el.pid, 91)
        self.assertEqual(el.nodes, [90000001, 90000040, 90000041, 90000002])

    def test_dense_solid_hex_one_line(self):
        state = ConversionState()
        line = self._dense(90000001, 92, 90000011, 90000012, 90000013,
                           90000014, 90000015, 90000016, 90000017, 90000018)
        dispatch(Block("ELEMENT_SOLID", [], [line]), state)
        self.assertEqual(len(state.solid_elems), 1)
        el = state.solid_elems[0]
        self.assertEqual((el.eid, el.pid), (90000001, 92))
        self.assertEqual(el.nodes, [90000011, 90000012, 90000013, 90000014,
                                    90000015, 90000016, 90000017, 90000018])

    def test_dense_solid_tet_one_line(self):
        state = ConversionState()
        line = self._dense(90000002, 92, 90000021, 90000022, 90000023, 90000024)
        dispatch(Block("ELEMENT_SOLID", [], [line]), state)
        self.assertEqual(len(state.solid_elems), 1)
        el = state.solid_elems[0]
        self.assertEqual((el.eid, el.pid), (90000002, 92))
        self.assertEqual(el.nodes, [90000021, 90000022, 90000023, 90000024])

    def test_dense_solid_two_line_tet10(self):
        state = ConversionState()
        dispatch(Block("ELEMENT_SOLID", [], [
            self._dense(90000003, 93),
            self._dense(90000031, 90000032, 90000033, 90000034, 90000035,
                        90000036, 90000037, 90000038, 90000039, 90000040),
        ]), state)
        self.assertEqual(len(state.solid_elems), 1)
        el = state.solid_elems[0]
        self.assertEqual((el.eid, el.pid), (90000003, 93))
        self.assertEqual(el.nodes, [90000031, 90000032, 90000033, 90000034,
                                    90000035, 90000036, 90000037, 90000038,
                                    90000039, 90000040])

    def test_dense_solid_two_line_hex(self):
        # Two-line format with n9=n10=0: only n1..n8 kept.
        state = ConversionState()
        dispatch(Block("ELEMENT_SOLID", [], [
            self._dense(90000004, 93),
            self._dense(90000041, 90000042, 90000043, 90000044, 90000045,
                        90000046, 90000047, 90000048, 0, 0),
        ]), state)
        self.assertEqual(len(state.solid_elems), 1)
        el = state.solid_elems[0]
        self.assertEqual((el.eid, el.pid), (90000004, 93))
        self.assertEqual(el.nodes, [90000041, 90000042, 90000043, 90000044,
                                    90000045, 90000046, 90000047, 90000048])

    def test_dense_beam(self):
        state = ConversionState()
        line = self._dense(90000005, 91, 90000051, 90000052, 90000053)
        dispatch(Block("ELEMENT_BEAM", [], [line]), state)
        self.assertEqual(len(state.beam_elems), 1)
        el = state.beam_elems[0]
        self.assertEqual((el.eid, el.pid), (90000005, 91))
        self.assertEqual((el.n1, el.n2, el.n3), (90000051, 90000052, 90000053))

    def test_dense_beam_glue_only_in_trailing_fields(self):
        # Glue past the 5 fields the handler reads (rt1/rr1) must still flip
        # the line to fixed slicing — otherwise the mis-split leading tokens
        # would be consumed positionally.
        state = ConversionState()
        line = self._dense(1, 1, 1, 2, 0, 90000001, 90000002)
        dispatch(Block("ELEMENT_BEAM", [], [line]), state)
        self.assertEqual(len(state.beam_elems), 1)
        el = state.beam_elems[0]
        self.assertEqual((el.eid, el.pid, el.n1, el.n2, el.n3), (1, 1, 1, 2, 0))

    def test_free_format_wide_ids_not_mistaken_for_dense(self):
        # Free format allows ids wider than I8; a >8-char token alone must not
        # trigger fixed re-slicing (which would cut these numbers mid-token).
        state = ConversionState()
        dispatch(Block("ELEMENT_SHELL", [], [
            "1234567890 1 1234567891 1234567892 1234567893 1234567894",
        ]), state)
        self.assertEqual(len(state.shell_elems), 1)
        el = state.shell_elems[0]
        self.assertEqual(el.eid, 1234567890)
        self.assertEqual(el.pid, 1)
        self.assertEqual(el.nodes, [1234567891, 1234567892, 1234567893,
                                    1234567894])

    def test_short_id_fixed_lines_unchanged(self):
        # Ordinary fixed I8 lines with small ids have no glue and keep the
        # whitespace-split path.
        state = ConversionState()
        dispatch(Block("ELEMENT_SHELL", [], [
            "       1       1       1       2       3       4",
        ]), state)
        self.assertEqual(len(state.shell_elems), 1)
        self.assertEqual(state.shell_elems[0].nodes, [1, 2, 3, 4])


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

    def test_eless_exponent_density_survives(self):
        # Regression: a density written in LS-DYNA's E-less exponent form
        # ("7.85000-9") must not be parsed as 0 — a zero density makes the
        # OpenRadioss starter fail with ERROR 683 (density <= 0).
        deck = TINY_K.replace("         1   7.86e-9    210000.0      0.3",
                              "         1 7.85000-9 210000.00     0.300")
        path = os.path.join(self.tmp.name, "eless.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, write_log=False)
        starter = Path(result.starter_path).read_text()
        block = starter.split("/MAT/ELAST/1", 1)[1].split("/MAT", 1)[0]
        rho = float(block.split("RHO_I")[1].split("\n")[1])
        self.assertAlmostEqual(rho, 7.85e-9)

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
        # MUMPS AUTOCORE is the default memory mode: starts in-core (fast) and
        # auto-switches to out-of-core only if the factors don't fit, superseding
        # the obsolete in-core-only AUTOC and the always-on-disk (slow) OUTCORE.
        self.assertIn("/IMPL/MUMPS/AUTOCORE", engine)
        self.assertNotIn("/IMPL/MUMPS/OUTCORE", engine)

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
        # End-to-end guard for a *CONTROL_IMPLICIT_SOLUTION whose first
        # (nsolvr…abstol) card is blank. The parser now PRESERVES that blank card
        # so card 2's "2" stays in the nlprint column (see
        # BlankCardPreservationTests for the column-level check); the writer's
        # tolerance sanity-check (reject Toli >= 1.0) remains as defense-in-depth.
        # Either way the engine must keep the robust default, not emit "2 3 2".
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

    def test_large_model_still_uses_autocore_mumps(self):
        # AUTOCORE manages the in-core/out-of-core decision itself, so model size
        # no longer changes the keyword: even a very large 3D model uses
        # /IMPL/MUMPS/AUTOCORE (not the slow always-on-disk OUTCORE). Validated on
        # the ~834k-node elevator-linkage (np=1 -nt 12).
        from k2rad.state import ConversionState, NodeData, ControlImplicitGeneral
        from k2rad.writer import build_engine
        st = ConversionState()
        st.is_implicit = True
        st.ctrl_implicit_gen = ControlImplicitGeneral(1, 0.001, 2, 1)
        st.nodes = {i: NodeData(0.0, 0.0, 0.0) for i in range(1, 250_002)}  # >250k
        engine = build_engine(st)
        self.assertIn("/IMPL/MUMPS/AUTOCORE", engine)
        self.assertNotIn("/IMPL/MUMPS/OUTCORE", engine)

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

    @staticmethod
    def _fixpoints(engine: str):
        """Parse the time points of the (single) /IMPL/DT/FIXPOINT card."""
        lines = engine.splitlines()
        idx = lines.index("/IMPL/DT/FIXPOINT")
        vals = []
        for ln in lines[idx + 1:]:
            s = ln.strip()
            if not s or s.startswith("/") or s.startswith("#"):
                break
            vals.extend(float(tok) for tok in s.split())
        return sorted(vals)

    def _engine_with_opts(self, deck: str, **opts) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "impl.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path, **opts).engine_path).read_text()

    def test_fixpoint_written_every_one_percent_by_default(self):
        # Auto /IMPL/DT/FIXPOINT makes the implicit time-step controller land
        # exactly on evenly spaced fractions of the run end (endtim=1.0 here) so
        # a clean animation/TH state is produced at each milestone. The default
        # count is 100, so we emit 100 points 0.01*T … 1.00*T; the engine reads
        # them free-format and sorts ascending.
        engine = self._engine_for(IMPL_QSTAT_K)
        self.assertIn("/IMPL/DT/FIXPOINT", engine)
        vals = self._fixpoints(engine)
        self.assertEqual(len(vals), 100)
        self.assertEqual([round(v, 10) for v in vals],
                         [round(k / 100.0, 10) for k in range(1, 101)])
        # Must sit inside the implicit block (before its terminating comment),
        # so /IMPL/DT/3 (RIKS, which would ignore it) is not in play — we use
        # /IMPL/DT/2.
        self.assertIn("/IMPL/DT/2", engine)
        self.assertNotIn("/IMPL/DT/3", engine)

    def test_fixpoint_scales_with_endtim(self):
        # The points track the actual termination time, not a hard-coded 1.0:
        # for a 10 s run the 100 default milestones are 0.1,0.2,…,10.0 s.
        deck = IMPL_QSTAT_K.replace("       1.0\n*END", "      10.0\n*END")
        vals = self._fixpoints(self._engine_for(deck))
        self.assertEqual([round(v, 6) for v in vals],
                         [round(k / 10.0, 6) for k in range(1, 101)])

    def test_fixpoint_count_configurable(self):
        # The number of /IMPL/DT/FIXPOINT milestones follows fixpoint_count: ask
        # for 10 and the controller lands on every 10% of the run end again.
        vals = self._fixpoints(self._engine_with_opts(IMPL_QSTAT_K, fixpoint_count=10))
        self.assertEqual([round(v, 10) for v in vals],
                         [round(0.1 * k, 10) for k in range(1, 11)])

    def test_fixpoint_count_clamped_to_engine_max(self):
        # The OpenRadioss engine caps the FIXPOINT list at 100, so a larger
        # request is clamped to 100 points rather than emitting an over-long card.
        vals = self._fixpoints(self._engine_with_opts(IMPL_QSTAT_K, fixpoint_count=250))
        self.assertEqual(len(vals), 100)

    def test_fixpoint_count_zero_disables_card(self):
        # 0 turns the milestone card off entirely.
        engine = self._engine_with_opts(IMPL_QSTAT_K, fixpoint_count=0)
        self.assertNotIn("/IMPL/DT/FIXPOINT", engine)

    def test_no_fixpoint_lines_exceed_radioss_line_width(self):
        # The engine input buffer is NCHARLINE100 (100 chars). The ≤5-fields-per
        # -line layout must never overflow it.
        engine = self._engine_for(IMPL_QSTAT_K)
        lines = engine.splitlines()
        idx = lines.index("/IMPL/DT/FIXPOINT")
        for ln in lines[idx + 1:]:
            if ln.strip().startswith("#") or ln.strip().startswith("/"):
                break
            self.assertLessEqual(len(ln), 100)


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
        # A real parent contact interface must also be present for the sub to attach
        # to — an explicit *CONTACT_AUTOMATIC_SINGLE_SURFACE now emits /INTER/TYPE25.
        self.assertIn("/INTER/TYPE25/", starter)

    def test_explicit_single_surface_is_type25_self_contact(self):
        # *CONTACT_AUTOMATIC_SINGLE_SURFACE (surfa=0) in an EXPLICIT deck → native-
        # style /INTER/TYPE25 self-impact over one all-parts /SURF/PART/EXT surface
        # (symmetric self-contact), NOT the implicit TYPE7 node→surface — the latter
        # is an asymmetric ~half-model contact that lets the driven part blow through
        # in explicit dynamics. See writer._emit_inter_type25_self.
        result, starter = self._convert(TRANSDUCER_K)
        self.assertIn("/INTER/TYPE25/", starter)
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertIn("/SURF/PART/EXT/", starter)
        self.assertTrue(any("explicit analysis" in w and "TYPE25" in w
                            for w in result.warnings),
                        f"no explicit-TYPE25 warning in {result.warnings}")

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

    def test_impulse_scaling_caveat_when_transducer_present(self):
        # OpenRadioss stores T01 contact forces as impulse-scaled values (~half on
        # implicit); the log must warn so users read in HyperView or scale x2.
        result, _ = self._convert(TRANSDUCER_K)
        self.assertTrue(any("impulse-scaled" in w and "#2451" in w
                            for w in result.warnings))

    def test_no_impulse_caveat_without_transducer(self):
        result, _ = self._convert(TRANSDUCER_K.replace(
            "*CONTACT_FORCE_TRANSDUCER_PENALTY\n         2         1         3         3\n",
            ""))
        self.assertFalse(any("impulse-scaled" in w for w in result.warnings))


class ImplicitContactStubTests(unittest.TestCase):
    """A contact-free implicit model must get one inert /INTER/TYPE7 self-contact:
    the OpenRadioss engine segfaults in implicit setup when no interface exists."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "m.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_contactfree_implicit_gets_inert_interface(self):
        result, starter = self._convert(IMPL_QSTAT_K)
        self.assertEqual(starter.count("/INTER/TYPE7/"), 1)
        self.assertTrue(any("no contact interface" in w for w in result.warnings))

    def test_explicit_model_gets_no_injected_contact(self):
        # Same deck minus *CONTROL_IMPLICIT_GENERAL -> explicit -> no injection.
        deck = IMPL_QSTAT_K.replace(
            "*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n", "")
        result, starter = self._convert(deck)
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertFalse(any("no contact interface" in w for w in result.warnings))

    def test_existing_contact_is_not_duplicated(self):
        # Implicit deck that already defines contact -> exactly one interface,
        # and no stub-injection warning.
        deck = IMPL_QSTAT_K.replace(
            "*CONTROL_TERMINATION",
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
            "         0         0         5         0\n"
            "       0.1\n"
            "*CONTROL_TERMINATION",
        )
        result, starter = self._convert(deck)
        self.assertEqual(starter.count("/INTER/TYPE7/"), 1)
        self.assertFalse(any("no contact interface" in w for w in result.warnings))


# Two tets sharing one face + an all-parts self-contact: exercises a solid-part
# contact MAIN surface (/SURF/PART/EXT).  In an IMPLICIT deck this surface makes
# the OpenRadioss SPMD engine segfault (MESSAGE ID 44) at the first implicit
# solve when run multi-domain (np>1) -- an upstream engine bug, independent of
# the surface representation -- so the converter must warn the user to run np=1.
SOLID_SELFCONTACT_K = """\
*KEYWORD
*TITLE
solid self-contact
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
       5             1.0             1.0             1.0
*ELEMENT_SOLID
       1       1       1       2       3       4
       2       1       2       3       4       5
*PART
solid
         1         1         1
*SECTION_SOLID
         1        10
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SINGLE_SURFACE
         0         0         5         0
       0.1
*CONTROL_IMPLICIT_GENERAL
         1     0.001
*CONTROL_TERMINATION
       1.0
*END
"""


class SolidContactSurfaceTests(unittest.TestCase):
    """An implicit deck with a solid-part contact surface still emits the compact
    /SURF/PART/EXT, but must warn that OpenRadioss SPMD (np>1) segfaults on it so
    the user runs np=1.  (The np>1 crash is an upstream engine bug in the
    distributed implicit solve, not the surface, so the converter cannot rewrite
    the deck around it -- verified that a /SURF/GRSHEL null-shell skin crashes
    identically.)"""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "s.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _np1_warning(result):
        return [w for w in result.warnings
                if "np=1" in w and "solid-part contact" in w]

    def test_implicit_solid_contact_warns_run_np1(self):
        result, starter = self._convert(SOLID_SELFCONTACT_K)
        self.assertIn("/SURF/PART/EXT", starter)        # surface unchanged
        warns = self._np1_warning(result)
        self.assertEqual(len(warns), 1)
        self.assertIn("MESSAGE ID 44", warns[0])

    def test_explicit_solid_contact_does_not_warn(self):
        # Same model without *CONTROL_IMPLICIT_GENERAL -> explicit -> the np>1
        # implicit engine bug does not apply, so no np=1 warning.
        deck = SOLID_SELFCONTACT_K.replace(
            "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n", "")
        result, starter = self._convert(deck)
        self.assertIn("/SURF/PART/EXT", starter)
        self.assertEqual(self._np1_warning(result), [])

    def test_contactfree_implicit_solid_also_warns(self):
        # A contact-free implicit solid deck gets an injected all-parts self
        # contact (ImplicitContactStubTests) -> that is a solid-part contact too,
        # so it must also carry the np=1 warning.
        deck = SOLID_SELFCONTACT_K.replace(
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n         0         0         5         0\n"
            "       0.1\n", "")
        result, _ = self._convert(deck)
        self.assertEqual(len(self._np1_warning(result)), 1)


# Deformable shell part 1 vs rigid shell part 2, surface-to-surface contact
# whose Card3 carries SST/MST (optional contact thickness per side).  LS-DYNA
# engages contact at a separation of (SST+MST)/2 — the writer carries that to
# /INTER/TYPE7 Gapmin so per-pair gap pre-engagement survives conversion.
GAPMIN_K = """\
*KEYWORD
*TITLE
sst/mst -> gapmin
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
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                              pin_pair
         1         2         3         3         0         0         0         0
       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20
       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0
*CONTROL_TERMINATION
       1.0
*END
"""


class ContactGapminTests(unittest.TestCase):
    """*CONTACT Card3 SST/MST → /INTER/TYPE7 Gapmin = (SST+MST)/2.

    The .k-side knob for force control through a clearance fit: one contact
    per pair, each with SST/MST giving Gapmin just above that pair's
    clearance (+ ignore=0 → Inacti=0) pre-engages the contact without the
    uniform-Gapmin press-fit artifact.  Without SST/MST the card is
    byte-identical to the pre-mapping writer output (Gapmin 0)."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "g.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_sst_mst_map_to_gapmin(self):
        result, starter = self._convert(GAPMIN_K)
        self.assertIn("/INTER/TYPE7/9", starter)
        # Stfac=0  Fric=0.2  Gapmin=(0+0.22)/2=0.11  Tstart=0  Tstop=0
        self.assertIn(
            "                   0                 0.2                0.11"
            "                   0                   0", starter)
        self.assertTrue(any("Gapmin=0.11" in w for w in result.warnings))

    def test_single_surface_sast_sbst_also_map(self):
        deck = GAPMIN_K.replace(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n"
            "         9                                                              pin_pair\n"
            "         1         2         3         3         0         0         0         0\n",
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID\n"
            "        11                                                          part1_self\n"
            "         1         0         3         0         0         0         0         0\n",
        ).replace(
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0",
            "       1.0       1.0      0.02      0.04       1.0       1.0       1.0       1.0",
        )
        result, starter = self._convert(deck)
        self.assertIn("/INTER/TYPE7/11", starter)
        self.assertIn("                0.03", starter)   # (0.02+0.04)/2
        self.assertTrue(any("Gapmin=0.03" in w for w in result.warnings))

    def test_negative_thickness_uses_magnitude_and_warns(self):
        deck = GAPMIN_K.replace(
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0",
            "       1.0       1.0     -0.22       0.0       1.0       1.0       1.0       1.0",
        )
        result, starter = self._convert(deck)
        self.assertIn("                0.11", starter)
        self.assertTrue(any("negative SST/MST" in w for w in result.warnings))

    def test_no_card3_keeps_gapmin_zero(self):
        deck = GAPMIN_K.replace(
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0\n",
            "")
        result, starter = self._convert(deck)
        # Gapmin back to 0 — byte-identical to the pre-SST/MST writer output.
        self.assertIn(
            "                   0                 0.2                   0"
            "                   0                   0", starter)
        self.assertFalse(any("Gapmin=" in w for w in result.warnings))

    def test_multiple_contacts_without_id_get_unique_interface_ids(self):
        # LS-PrePost usually writes *CONTACT_... WITHOUT the _ID suffix.  The
        # old no-_ID fallback derived the interface id from the block's line
        # count, so several contacts of the same card shape all collided on
        # one id and the starter died with ERROR 117 "INTERFACE ID USED TWICE
        # OR MORE" (seen on the 3-contact split-gap elevator deck).
        deck = GAPMIN_K.replace(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n"
            "         9                                                              pin_pair\n"
            "         1         2         3         3         0         0         0         0\n"
            "       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20\n"
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0\n",
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            "         1         2         3         3         0         0         0         0\n"
            "       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20\n"
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0\n"
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            "         1         2         3         3         0         0         0         0\n"
            "       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20\n"
            "       1.0       1.0       0.0      0.28       1.0       1.0       1.0       1.0\n"
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
            "         1         1         3         3         0         0         0         0\n"
            "       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20\n"
            "       1.0       1.0      0.06       0.0       1.0       1.0       1.0       1.0\n",
        )
        _, starter = self._convert(deck)
        ids = re.findall(r"^/INTER/TYPE7/(\d+)$", starter, flags=re.M)
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3, f"duplicate interface ids: {ids}")


# One deformable solid part (1) + two rigid shell parts (2=pin, 3=cyl), three
# split per-pair contacts with the SELF-contact deliberately defined FIRST,
# plus one force transducer per rigid pair.  /INTER/SUB segments must be
# subsets of the parent interface's main surface, so each transducer has to
# parent on ITS pair — the old "first contact defined" pick parented both on
# the self-contact and the starter died with ERROR 581 per foreign segment.
TRANSD_MATCH_K = """\
*KEYWORD
*TITLE
transducer parent matching
*NODE
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
*ELEMENT_SHELL
       1       2       1       2       3       4
       2       3       5       6       7       8
*ELEMENT_SOLID
       3       1      11      12      13      14       5
*PART
bracket
         1         3         1
*PART
pin
         2         1         2
*PART
cyl
         3         1         3
*SECTION_SHELL
         1         2       1.0         3
      0.05
*SECTION_SOLID
         3        10
*MAT_ELASTIC
         1   2.7e-9     70000.0      0.33
*MAT_RIGID
         2   7.86e-9    210000.0      0.3
*MAT_RIGID
         3   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
        11                                                          bracket_self
         1         1         3         3         0         0         0         0
       0.2
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                        bracket_vs_pin
         1         2         3         3         0         0         0         0
       0.2
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
        10                                                        bracket_vs_cyl
         1         3         3         3         0         0         0         0
       0.2
*CONTACT_FORCE_TRANSDUCER_PENALTY_ID
       101                                                             pin_force
         2         1         3         3
*CONTACT_FORCE_TRANSDUCER_PENALTY_ID
       102                                                             cyl_force
         3         1         3         3
*CONTROL_TERMINATION
       1.0
*END
"""


class TransducerParentMatchTests(unittest.TestCase):
    """Each /INTER/SUB must parent on the interface whose main surface and
    secondary group actually contain its segments/nodes (starter ERROR 581
    otherwise), independent of contact definition order."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _sub_parent(starter: str, sub_id: int) -> int:
        lines = starter.splitlines()
        i = lines.index(f"/INTER/SUB/{sub_id}")
        # block: keyword, title, comment, data card (parent main_surf grnod)
        return int(lines[i + 3].split()[0])

    def test_each_transducer_parents_on_its_own_pair(self):
        _, starter = self._convert(TRANSD_MATCH_K)
        self.assertEqual(self._sub_parent(starter, 101), 9)    # pin pair
        self.assertEqual(self._sub_parent(starter, 102), 10)   # cyl pair

    def test_unmatched_transducer_falls_back_with_warning(self):
        # Remove the cyl pair contact: transducer 102 has no covering interface
        # -> falls back to the first contact and warns loudly.
        deck = TRANSD_MATCH_K.replace(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n"
            "        10                                                        bracket_vs_cyl\n"
            "         1         3         3         3         0         0         0         0\n"
            "       0.2\n",
            "")
        result, starter = self._convert(deck)
        self.assertEqual(self._sub_parent(starter, 101), 9)
        self.assertEqual(self._sub_parent(starter, 102), 11)   # fallback: first
        self.assertTrue(any("no contact interface covers" in w
                            for w in result.warnings))


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

    @staticmethod
    def _impdisp_grnod_id(starter: str) -> int:
        """grnod_ID referenced by the first /IMPDISP card (fixed 10-char cols)."""
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/IMPDISP/"):
                data = lines[i + 3]            # /IMPDISP, title, #funct hdr, DATA
                fields = [data[j:j + 10] for j in range(0, len(data), 10)]
                return int(fields[4])
        raise AssertionError("no /IMPDISP card found")

    @staticmethod
    def _grnod_node_count(starter: str, grnod_id: int) -> int:
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.strip() == f"/GRNOD/NODE/{grnod_id}":
                j, n = i + 2, 0               # skip /GRNOD line + title
                while j < len(lines) and not lines[j].lstrip().startswith(("/", "#")):
                    n += len(lines[j].split())
                    j += 1
                return n
        raise AssertionError(f"/GRNOD/NODE/{grnod_id} not found")

    def test_impdisp_targets_rigid_body_master_node_only(self):
        # Regression: imposed motion on a rigid part must drive ONLY the /RBODY
        # master node. Targeting every node of the rigid part collides with the
        # rigid-body kinematics (Starter WARNING ID 312); OpenRadioss then drops
        # the motion silently → part never moves → zero reaction/strain/stress.
        starter = self._starter(DISPCTRL_K)
        grnod_id = self._impdisp_grnod_id(starter)
        self.assertEqual(self._grnod_node_count(starter, grnod_id), 1)

    def test_reaction_th_node_with_reac_vars(self):
        starter = self._starter(DISPCTRL_K)
        self.assertIn("/TH/NODE/", starter)
        self.assertIn("REACX", starter)
        self.assertIn("REACY", starter)
        self.assertIn("REACZ", starter)

    def test_no_reaction_th_node_without_prescribed_motion(self):
        # TRANSDUCER_K has the rigid part but no prescribed motion → no reaction block.
        self.assertNotIn("REACX", self._starter(TRANSDUCER_K))

    def test_reaction_block_says_reac_is_an_impulse(self):
        # /TH/NODE REAC* accumulates m*a*dt (reaction_forces_th.F:60) and is
        # never reset inside the cycle loop (resol.F:1901 vs. loop head :2612),
        # so a force-vs-displacement curve needs d(REAC)/dt, not REAC.
        starter = self._starter(DISPCTRL_K)
        block = _th_comment_lines(starter, "TH_reaction")
        self.assertIn("reaction IMPULSE (REACX/Y/Z)", block)
        self.assertIn("REAC* accumulates m*a*dt over the run: "
                      "reaction force = d(REAC*)/dt", block)
        self.assertNotIn("reaction (REACX/Y/Z) + displacement", starter)


# A *CONTROL_IMPLICIT_SOLUTION whose card-1 (nsolvr…abstol) is an all-blank
# "all defaults" card written in the real-world LS-PrePost form: whitespace
# followed by a trailing "$" comment (strips to empty, but is NOT a column-1
# comment).  Card-2 carries nlprint=2 in its 4th fixed-width field (cols 31-40),
# which sits in the same column as card-1's dctol.  If the blank card-1 is
# dropped during parsing, the "2" shifts up into the dctol slot.
IMPL_BLANKCARD_K = (
    "*KEYWORD\n"
    "*CONTROL_IMPLICIT_SOLUTION\n"
    "$#  nsolvr    ilimit    maxref     dctol     ectol     rctol     lstol    abstol\n"
    + " " * 20 + "$\n"                 # card 1: all defaults (blank + trailing comment)
    + "$#   dnorm    diverg     istif   nlprint    nlnorm   d3itctl     cpchk\n"
    + " " * 30 + "2\n"                 # card 2: nlprint = 2 (field 4, columns 31-40)
    + "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


# *NODE / *ELEMENT_SHELL / *ELEMENT_SOLID blocks, each with an embedded blank
# line between data cards.  The blank lines are now preserved during parsing
# (to keep fixed-format card positions aligned for multi-card keywords), so the
# list-building handlers must skip them instead of emitting id-0 entries.
EMBEDDED_BLANK_K = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "\n"                               # embedded blank line
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "\n"                               # embedded blank line
    "       2       1       1       2       3       4\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "\n"                               # embedded blank line
    "       2       1       1       2       3       4       5       6       7       8\n"
    "*BOUNDARY_SPC_NODE\n"
    "         5         0         1         1         1         0         0         0\n"
    "\n"                               # trailing blank before next keyword
    "*END\n"
)


class BlankCardPreservationTests(unittest.TestCase):
    """Parser preserves intentionally blank fixed-format cards (so columns stay
    aligned), while raw-iterating handlers skip the "" placeholders."""

    def _state(self, deck: str) -> ConversionState:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "blank.k")
        with open(path, "w") as fh:
            fh.write(deck)
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        return state

    def _blocks(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "blank.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return parse_k_file(path)

    # (a) Blank leading card keeps the following cards' columns aligned.
    def test_blank_leading_card_is_preserved_in_raw(self):
        cis = next(b for b in self._blocks(IMPL_BLANKCARD_K)
                   if b.keyword == "CONTROL_IMPLICIT_SOLUTION")
        # Card-1 survives as an empty placeholder; card-2 (the "2") follows it.
        self.assertEqual(cis.raw[0], "")
        self.assertGreaterEqual(len(cis.raw), 2)
        self.assertTrue(cis.raw[1].rstrip().endswith("2"))

    def test_blank_leading_card_yields_correct_columns(self):
        sol = self._state(IMPL_BLANKCARD_K).ctrl_implicit_sol
        self.assertIsNotNone(sol)
        # The "2" stays in card-2's nlprint column and does NOT leak into dctol.
        self.assertEqual(sol.dctol, 0.0)
        self.assertEqual(sol.nlprint, 2)

    # (b) Embedded blank lines never create spurious id-0 entries.
    def test_embedded_blank_adds_no_spurious_node(self):
        nodes = self._state(EMBEDDED_BLANK_K).nodes
        self.assertNotIn(0, nodes)
        self.assertEqual(sorted(nodes), [1, 2, 3, 4])

    def test_embedded_blank_adds_no_spurious_element(self):
        state = self._state(EMBEDDED_BLANK_K)
        self.assertEqual(len(state.shell_elems), 2)
        self.assertTrue(all(e.eid != 0 for e in state.shell_elems))
        self.assertEqual(len(state.solid_elems), 2)
        self.assertTrue(all(e.eid != 0 for e in state.solid_elems))

    def test_trailing_blank_adds_no_spurious_boundary_condition(self):
        # The blank line after the single SPC card must not become a 2nd BC
        # (which would reference an auto-created node set holding node 0).
        self.assertEqual(len(self._state(EMBEDDED_BLANK_K).bcs_spcs), 1)


# Nodal-rigid-body strategy: a node set becomes a *CONSTRAINED_NODAL_RIGID_BODY_
# SPC, loaded by *LOAD_RIGID_BODY in a local system from *DEFINE_COORDINATE_NODES
# (no contact, no extra rigid part). The local frame here is rotated: with N1=1,
# N2=4, N3=2 and Dir=X, local X = +Y(global), local Y = +X(global), Z = -Z.
CNRB_K = """\
*KEYWORD
*TITLE
Nodal rigid body strategy test
*NODE
       1             0.0             0.0             0.0
       2             2.0             0.0             0.0
       3             2.0             2.0             0.0
       4             0.0             2.0             0.0
       5             0.0             0.0             2.0
       6             2.0             0.0             2.0
       7             2.0             2.0             2.0
       8             0.0             2.0             2.0
*SET_NODE_LIST
       100
         1         2         3         4         5         6         7         8
*DEFINE_COORDINATE_NODES
         7         1         4         2         0         X
*CONSTRAINED_NODAL_RIGID_BODY_SPC
        10         7       100         0
        -1         7    101111         0
*DEFINE_CURVE
         1         0       1.0       1.0
                 0.0                 0.0
                 1.0              6000.0
*LOAD_RIGID_BODY
        10         2         1       1.0         7
*CONTROL_IMPLICIT_GENERAL
         1     0.001
*CONTROL_TERMINATION
       1.0
*END
"""


class NodalRigidBodyTests(unittest.TestCase):
    """*CONSTRAINED_NODAL_RIGID_BODY_SPC + *DEFINE_COORDINATE_NODES +
    *LOAD_RIGID_BODY — the new node-set rigid-body + local-frame strategy."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "cnrb.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _data_after(starter: str, header_prefix: str):
        """Return the fixed-width 10-char fields of the first data line of the
        first card whose header starts with *header_prefix*. The data line is the
        first non-'/' , non-blank line AFTER the card's '#' column header (so the
        title line, which precedes that header, is skipped)."""
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith(header_prefix):
                seen_comment = False
                for j in range(i + 1, len(lines)):
                    s = lines[j]
                    if s.startswith("#"):
                        seen_comment = True
                        continue
                    if s.startswith("/") or not s.strip():
                        continue
                    if seen_comment:
                        return [s[k:k + 10] for k in range(0, len(s), 10)]
        raise AssertionError(f"no data line after {header_prefix}")

    def test_keywords_are_handled_not_skipped(self):
        result, _ = self._convert(CNRB_K)
        self.assertNotIn("CONSTRAINED_NODAL_RIGID_BODY_SPC", result.skipped_keywords)
        self.assertNotIn("DEFINE_COORDINATE_NODES", result.skipped_keywords)

    def test_rbody_inertia_is_two_cards(self):
        # OpenRadioss /RBODY needs the inertia tensor on TWO cards (Jxx Jyy Jzz,
        # then Jxy Jyz Jxz). Emitting all six on one line makes the reader stop
        # after Jxx Jyy Jzz and hit the next keyword where card 2 is expected ->
        # WARNING 100217 "card is missing" + a malformed rigid body that
        # segfaults the SPMD (np>1) setup (MESSAGE ID 44).
        _, starter = self._convert(CNRB_K)
        self.assertIn("Jyy                 Jzz", starter)                    # inertia card 1
        self.assertIn("Jxy                 Jyz                 Jxz", starter)  # inertia card 2
        self.assertNotIn("Jzz                 Jxy", starter)   # old 6-on-one-line header gone
        # Card 4 (Ioptoff/Iexpams) must be present: Ioptoff governs the rigid
        # body's domain decomposition for HMPP — omitting it segfaults np>1.
        self.assertIn("Ioptoff", starter)

    @staticmethod
    def _rbody_master(starter: str) -> int:
        for ln in starter.splitlines():
            if ln.startswith("/RBODY/"):
                return int(ln.split("/")[2])
        raise AssertionError("no /RBODY card")

    def test_rbody_master_is_a_free_centroid_node(self):
        # pnode=0 and every set node (1-8) is attached to the shell element, so a
        # mesh node as master would be inverted by the ICoG move. The master must
        # therefore be a synthesized free node (id beyond the mesh) that also
        # appears in /NODE and is NOT in the secondary (cnrb_nodes) group.
        _, starter = self._convert(CNRB_K)
        master = self._rbody_master(starter)
        self.assertGreater(master, 8)                     # not one of nodes 1-8
        self.assertIn(f"\n{str(master).rjust(10)}", starter)  # present in /NODE
        # Secondary group must be the 8 mesh nodes, master excluded.
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip().startswith("/GRNOD/NODE/") and "cnrb_nodes" in lines[k + 1])
        grp = []
        for ln in lines[i + 2:]:
            if ln.startswith(("#", "/")):
                break
            grp += [int(x) for x in ln.split()]
        self.assertEqual(sorted(grp), list(range(1, 9)))
        self.assertNotIn(master, grp)

    def test_rbody_group_has_all_set_nodes(self):
        _, starter = self._convert(CNRB_K)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip().startswith("/GRNOD/NODE/")
                 and "cnrb_nodes" in lines[k + 1])
        nids = []
        for ln in lines[i + 2:]:
            if ln.startswith(("#", "/")):
                break
            nids += ln.split()
        self.assertEqual(sorted(int(x) for x in nids), list(range(1, 9)))

    def test_fixed_skew_emitted_for_flag0(self):
        # flag=0 (default) → a fixed /SKEW/FIX evaluated at t=0.
        _, starter = self._convert(CNRB_K)
        self.assertIn("/SKEW/FIX/7", starter)
        self.assertNotIn("/SKEW/MOV/7", starter)
        # The two vector cards are the LOCAL Y and Z axes (X' = Y'×Z').
        # Fixture frame: X=+Yg, Y=+Xg, Z=X×Y=−Zg. Writing X/Y instead would
        # hand the reader a cyclically permuted frame.
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/SKEW/FIX/7"))
        data = [ln for ln in lines[i + 1:i + 9]
                if ln.strip() and not ln.startswith(("#", "/"))]
        # data = [title, origin, Y axis, Z axis]
        yvec = [float(x) for x in data[2].split()]
        zvec = [float(x) for x in data[3].split()]
        self.assertEqual(yvec, [1.0, 0.0, 0.0])     # local Y = +Xg
        self.assertEqual(zvec, [0.0, 0.0, -1.0])    # local Z = −Zg

    def test_moving_skew_emitted_for_flag1(self):
        deck = CNRB_K.replace(
            "         7         1         4         2         0         X",
            "         7         1         4         2         1         X")
        _, starter = self._convert(deck)
        self.assertIn("/SKEW/MOV/7", starter)
        self.assertNotIn("/SKEW/FIX/7", starter)

    def test_local_spc_becomes_bcs_in_local_skew(self):
        # CMO=-1, CON1=7 (local skew), CON2=101111 → constrain local Tx,Tz + all
        # rotations, in skew 7, on the master-node group.
        _, starter = self._convert(CNRB_K)
        self.assertIn("/BCS/", starter)
        fields = self._data_after(starter, "/BCS/")
        self.assertEqual(fields[0], "   101 111")     # Tra rot
        self.assertEqual(int(fields[1]), 7)           # skew_ID = local coord sys

    def test_load_rigid_body_cload_uses_local_skew(self):
        # /CLOAD direction is expressed in the local skew (cid=7 on LOAD_RIGID_BODY).
        _, starter = self._convert(CNRB_K)
        self.assertIn("/CLOAD/", starter)
        fields = self._data_after(starter, "/CLOAD/")
        self.assertEqual(int(fields[0]), 1)           # funct (curve) ID
        self.assertEqual(fields[1].strip(), "Y")      # dof=2 → Y
        self.assertEqual(int(fields[2]), 7)           # skew_ID = local coord sys

    def test_cload_single_card_2026_layout(self):
        # /CLOAD data is ONE 100-col card (radioss51…2026): fct_IDT(10) Dir(10)
        # skew_ID(10) sens_ID(10) grnd_ID(10) Itypfun(10) Ascalex(20) Fscaley(20).
        # Regression: Ascalex/Fscaley used to go on a bogus second card, so the
        # starter read Fscaley from blank cols of card 1 → default 1.0 (SF lost).
        # Itypfun (cols 51-60) stays blank: /BEGIN-2022 readers warn 100214 on
        # non-blank skipped columns; 2023+ readers default blank to 1 (= time).
        deck = CNRB_K.replace(
            "        10         2         1       1.0         7",
            "        10         2         1       2.5         7")
        _, starter = self._convert(deck)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/CLOAD/"))
        data = lines[i + 3]                       # keyword, title, #header, data
        self.assertEqual(len(data), 100)
        self.assertGreater(int(data[40:50]), 0)       # grnd_ID
        self.assertEqual(data[50:60], " " * 10)       # Itypfun blank → default 1
        self.assertEqual(data[60:80].strip(), "1")    # Ascalex
        self.assertEqual(data[80:100].strip(), "2.5")  # Fscaley = LS-DYNA SF
        self.assertTrue(lines[i + 4].startswith("#"))  # no second data card

    def test_global_spc_uses_global_frame(self):
        # CMO=+1 → CON1/CON2 are global translation/rotation codes; skew_ID=0.
        deck = CNRB_K.replace(
            "        -1         7    101111         0",
            "         1         7         7         0")  # cmo=1 con1=7(xyz tra) con2=7(xyz rot)
        _, starter = self._convert(deck)
        fields = self._data_after(starter, "/BCS/")
        self.assertEqual(fields[0], "   111 111")
        self.assertEqual(int(fields[1]), 0)           # global → skew 0

    def test_skew_axes_match_lsdyna_dir_convention(self):
        # N1=1(0,0,0) N2=4(0,2,0) N3=2(2,0,0), Dir=X:
        #   local X = N1->N2 = +Y(global); Z = X x (N1->N3) = -Z; Y = Z x X = +X.
        state = ConversionState()
        state.nodes = {1: NodeData(0, 0, 0), 4: NodeData(0, 2, 0), 2: NodeData(2, 0, 0)}
        origin, X, Y = _skew_axes_from_nodes(state, CoordNodes(7, 1, 4, 2, 0, "X"))
        self.assertEqual(origin, (0.0, 0.0, 0.0))
        self.assertEqual(tuple(round(c, 9) for c in X), (0.0, 1.0, 0.0))
        self.assertEqual(tuple(round(c, 9) for c in Y), (1.0, 0.0, 0.0))


# *BOUNDARY_PRESCRIBED_MOTION_SET fixing rotational DOFs (sf=0). LS-DYNA DOF
# 5/6/7 = Rx/Ry/Rz; here dof 1,6,7 = "fix X translation + Ry + Rz" (a symmetry
# plane). All fixed DOFs of one set must collapse into a single /BCS = "100 011",
# with no dead "000 000" card (regression: DOF 7 used to fall through unmapped).
PM_SET_FIX_K = """\
*KEYWORD
*TITLE
Prescribed-motion-set fixed-DOF mapping
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*PART
shell
         1         1         1
*SECTION_SHELL
         1         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*SET_NODE_LIST
       100
         1         2
*BOUNDARY_PRESCRIBED_MOTION_SET
       100         1         2         0       0.0
       100         6         2         0       0.0
       100         7         2         0       0.0
*CONTROL_TERMINATION
       1.0
*END
"""


class PrescribedMotionSetFixTests(unittest.TestCase):
    """*BOUNDARY_PRESCRIBED_MOTION_SET sf=0 → /BCS, with the correct LS-DYNA DOF
    map (5/6/7 = Rx/Ry/Rz) and all fixed DOFs of a set combined into one card."""

    def _starter(self, deck: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "pm.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path).starter_path).read_text()

    def _bcs_codes(self, starter: str):
        """(tra, rot) strings of every /BCS data line."""
        lines = starter.splitlines()
        out = []
        for i, ln in enumerate(lines):
            if ln.startswith("/BCS/"):
                data = lines[i + 3]            # /BCS, title, '# Tra rot…', DATA
                out.append((data[3:6], data[7:10]))
        return out

    def test_rotational_dofs_5_6_7_map_to_rx_ry_rz(self):
        codes = self._bcs_codes(self._starter(PM_SET_FIX_K))
        # Exactly one combined /BCS; X translation + Ry + Rz fixed.
        self.assertEqual(codes, [("100", "011")])

    def test_no_empty_bcs_for_dof7(self):
        # DOF 7 (Rz) must not fall through to a dead "000 000" /BCS.
        self.assertNotIn(("000", "000"), self._bcs_codes(self._starter(PM_SET_FIX_K)))


# A solid (tet) part with a plasticity material. *DATABASE_EXTENT_BINARY strflg=11
# asks LS-DYNA for the strain + plastic-strain tensors; OpenRadioss needs Istrain=1
# in /PROP/SOLID for strains (and the solid /ANIM/ELEM/EPSP plastic strain) to be
# stored for post-processing.
STRAIN_SOLID_K = """\
*KEYWORD
*TITLE
Solid plastic-strain output
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
*ELEMENT_SOLID
       1       1       1       2       3       4       4       4       4       4
*PART
solid
         1         1         1
*SECTION_SOLID
         1        10
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   2.7e-9   72000.0       0.3     200.0
*DATABASE_EXTENT_BINARY
         0         0         0        11         1         1         1         1
*CONTROL_TERMINATION
       1.0
*END
"""


class StrainOutputTests(unittest.TestCase):
    """*DATABASE_EXTENT_BINARY strflg>0 → Istrain=1 in /PROP/SOLID so OpenRadioss
    stores strains / plastic strain for post-processing; engine emits EPSP."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "strain.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return Path(result.starter_path).read_text(), Path(result.engine_path).read_text()

    @staticmethod
    def _solid_istrain(starter: str) -> int:
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/PROP/SOLID/"):
                for j in range(i, len(lines)):
                    if "istrain" in lines[j]:                 # the column header
                        return int(lines[j + 1][20:30])       # dt_min(20) | istrain(10)
        raise AssertionError("no /PROP/SOLID with an istrain line")

    def test_strflg_enables_istrain_on_solids(self):
        starter, engine = self._convert(STRAIN_SOLID_K)
        self.assertEqual(self._solid_istrain(starter), 1)
        # Plastic strain is written to the animation files for solids.
        self.assertIn("/ANIM/ELEM/EPSP", engine)

    def test_law36_emits_strain_rate_list_card(self):
        # With N_funct=1 the cfg expects THREE list cards: func_ID1, Fscale_1,
        # Eps_dot_1. Regression: Eps_dot_1 was missing, so the reader ran into
        # the next keyword ("card is missing" warning, fragile parse).
        starter, _ = self._convert(STRAIN_SOLID_K)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/MAT/LAW36/"))
        data = []
        for ln in lines[i + 2:]:              # skip keyword + title
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            data.append(ln)
        # rho, E/nu/eps, Nfunct/Fsmooth, fctIDp/Fscale, fctID1, Fscale1, Epsdot1
        self.assertEqual(len(data), 7)
        self.assertEqual(data[-1].strip(), "0")          # Eps_dot_1 = static
        self.assertGreater(int(data[-3][0:10]), 0)       # fct_ID1 = yield curve

    def test_no_strflg_leaves_istrain_off(self):
        # Without a strain request (no *DATABASE_EXTENT_BINARY) Istrain stays 0.
        deck = STRAIN_SOLID_K.replace(
            "*DATABASE_EXTENT_BINARY\n"
            "         0         0         0        11         1         1         1         1\n",
            "")
        starter, _ = self._convert(deck)
        self.assertEqual(self._solid_istrain(starter), 0)


# A single 10-node quadratic tet in the two-line *ELEMENT_SOLID form (eid/pid on
# card 1, the 10 node IDs on card 2). Must become /TETRA10 keeping ALL 10 nodes —
# dropping the 6 mid-edge nodes would orphan them (zero-stiffness DOFs → singular
# implicit matrix), the bug that crashed the elevator-linkage run.
# NOTE: the midside geometry here is in **Abaqus/Radioss C3D10 order** (node8=
# mid(1,4), node9=mid(2,4), node10=mid(3,4)) — NOT LS-DYNA apex order. It is the
# "already-Radioss, must-not-permute" case for _normalize_tet10_ordering, which
# detects it geometrically and leaves the connectivity untouched (emitted 1..10).
# See TET10_DYNA_K below for the LS-DYNA-ordered counterpart that IS permuted.
TET10_K = """\
*KEYWORD
*TITLE
Quadratic tet10 conversion
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
       5             0.5             0.0             0.0
       6             0.5             0.5             0.0
       7             0.0             0.5             0.0
       8             0.0             0.0             0.5
       9             0.5             0.0             0.5
      10             0.0             0.5             0.5
*ELEMENT_SOLID
       1       1
       1       2       3       4       5       6       7       8       9      10
*PART
tet10 part
         1         1         1
*SECTION_SOLID
         1        10
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   2.7e-9   72000.0       0.3     200.0
*CONTROL_TERMINATION
       1.0
*END
"""


SH3N_K = """\
*KEYWORD
*TITLE
Mixed quad / collapsed-quad / 3-node shell part
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             2.0             0.0             0.0
       6             2.0             1.0             0.0
       7             3.0             0.5             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       2       5       6       3
       3       1       5       7       6       6
       4       1       6       7       3
*PART
mixed shell part
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   7.8e-9  210000.0       0.3     300.0
*CONTROL_TERMINATION
       1.0
*END
"""


class Sh3nCollapsedQuadTests(unittest.TestCase):
    """Triangular shells → /SH3N, never a 4-node /SHELL with a repeated corner.

    LS-DYNA writes a triangle either as 3 IDs (blank N4) or as a quad with the
    last corner repeated (n1 n2 n3 n3). Radioss sizes /SH3N with the triangle
    critical-time-step rule and /SHELL with the quad rule, so passing a collapsed
    quad through as /SHELL halves dt for the whole model off one degenerate
    element (W13: 370 of 38,218 held dt at 8.361e-7 s instead of 1.6919e-6 s).
    """

    def _starter(self, deck: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "sh3n.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path).starter_path).read_text()

    def _block(self, starter: str, header: str):
        """Element id/connectivity rows under *header* (e.g. '/SH3N/1')."""
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == header)
        rows = []
        for ln in lines[i + 1:]:
            if ln.startswith(("/", "#")):
                break
            if ln.strip():
                rows.append([int(x) for x in ln.split()])
        return rows

    def test_emits_both_blocks_for_a_mixed_part(self):
        s = self._starter(SH3N_K)
        self.assertIn("/SHELL/1", s)
        self.assertIn("/SH3N/1", s)

    def test_collapsed_quad_becomes_a_three_node_sh3n(self):
        # eid 3 is "5 7 6 6" — a quad with the last corner repeated.
        s = self._starter(SH3N_K)
        tri = {r[0]: r[1:4] for r in self._block(s, "/SH3N/1")}
        self.assertIn(3, tri)
        self.assertEqual(tri[3], [5, 7, 6])      # winding preserved, dup dropped

    def test_blank_n4_triangle_becomes_sh3n(self):
        # eid 4 is "6 7 3" — a triangle whose trailing N4 column was blank.
        s = self._starter(SH3N_K)
        tri = {r[0]: r[1:4] for r in self._block(s, "/SH3N/1")}
        self.assertIn(4, tri)
        self.assertEqual(tri[4], [6, 7, 3])

    def test_real_quads_stay_in_shell(self):
        s = self._starter(SH3N_K)
        quad_ids = {r[0] for r in self._block(s, "/SHELL/1")}
        self.assertEqual(quad_ids, {1, 2})
        self.assertNotIn(3, quad_ids)            # the collapsed quad moved out

    def test_no_elements_are_lost(self):
        s = self._starter(SH3N_K)
        ids = ({r[0] for r in self._block(s, "/SHELL/1")}
               | {r[0] for r in self._block(s, "/SH3N/1")})
        self.assertEqual(ids, {1, 2, 3, 4})

    def test_sh3n_rows_carry_no_fourth_node(self):
        # A /SH3N row is eid n1 n2 n3 + the trailing 0 field — emitting a 4th
        # connectivity node here would be read as garbage.
        s = self._starter(SH3N_K)
        for row in self._block(s, "/SH3N/1"):
            self.assertEqual(len(row), 5)
            self.assertEqual(row[4], 0)

    def test_zero_area_shell_is_dropped_with_a_warning(self):
        deck = SH3N_K.replace(
            "       3       1       5       7       6       6",
            "       3       1       5       7       7       7")   # 2 distinct nodes
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "degen.k")
        with open(path, "w") as fh:
            fh.write(deck)
        res = convert(path)
        starter = Path(res.starter_path).read_text()
        ids = ({r[0] for r in self._block(starter, "/SHELL/1")}
               | {r[0] for r in self._block(starter, "/SH3N/1")})
        self.assertNotIn(3, ids)
        self.assertTrue(any("distinct node" in w and "zero area" in w
                            for w in res.warnings),
                        f"expected a zero-area warning, got: {res.warnings}")


class TetraTenTests(unittest.TestCase):
    """10-node quadratic tets → /TETRA10 (all nodes kept, no orphans, Itetra10)."""

    def _starter(self, deck: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t10.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path).starter_path).read_text()

    def test_emits_tetra10_not_tetra4_or_brick(self):
        s = self._starter(TET10_K)
        self.assertIn("/TETRA10/1", s)
        self.assertNotIn("/TETRA4/1", s)
        self.assertNotIn("/BRICK/1", s)

    def test_all_ten_nodes_kept_no_orphans(self):
        s = self._starter(TET10_K)
        lines = s.splitlines()
        # element node line follows "/TETRA10/1" then the eid line.
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "/TETRA10/1")
        node_line = lines[i + 2]
        nodes = [int(x) for x in node_line.split()]
        self.assertEqual(nodes, list(range(1, 11)))   # all 10, in order
        # No orphan nodes: every node in /NODE is referenced by the element.
        elem_nodes = set(nodes)
        node_ids = set()
        in_node = False
        for ln in lines:
            if ln.startswith("/NODE"):
                in_node = True
                continue
            if in_node:
                if ln.startswith(("/", "#")):
                    in_node = False
                    continue
                if ln.strip():
                    node_ids.add(int(ln[:10]))
        self.assertEqual(node_ids - elem_nodes, set())  # zero orphans

    def test_prop_solid_sets_itetra10(self):
        s = self._starter(TET10_K)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/PROP/SOLID/"))
        card1 = lines[i + 3]              # /PROP/SOLID, title, '#…', DATA
        # cfg radioss2022 card 1: Isolid Ismstr Iale Icpre Itetra10 Inpts
        # Itetra4 Iframe Dn — Itetra10 is field 5 (cols 41-50). Regressions:
        # (a) the writer used the 8-field PDF layout without Iale, which
        # shifted Itetra10 into Icpre and the reader's Itetra10 defaulted;
        # (b) the value must be 1000 (quadratic, 4 int. points), NOT 2 — the
        # tet4-timestep variant errors out (ERROR 1216) when kinematic
        # conditions touch tet10 nodes (e.g. the elevator's CNRB/RBODY).
        self.assertEqual(int(card1[40:50]), 1000)        # Itetra10
        self.assertEqual(int(card1[20:30]), 0)           # Iale
        self.assertEqual(int(card1[30:40]), 0)           # Icpre

    def test_offmidpoint_midside_is_snapped_to_midpoint(self):
        # Node 5 = mid-edge of corners 1,2 = mid((0,0,0),(1,0,0)) = (0.5,0,0).
        # Displace it; the converter must snap it back to the exact midpoint so
        # the quadratic tet cannot fold (OpenRadioss ERROR 489 / negative subvol).
        deck = TET10_K.replace(
            "       5             0.5             0.0             0.0",
            "       5             0.4             0.1             0.0")
        s = self._starter(deck)
        lines = s.splitlines()
        in_node = False
        for ln in lines:
            if ln.startswith("/NODE"):
                in_node = True
                continue
            if in_node and ln.startswith("/"):
                break
            if in_node and ln.strip() and not ln.startswith("#") and int(ln[:10]) == 5:
                self.assertAlmostEqual(float(ln[10:30]), 0.5, places=6)
                self.assertAlmostEqual(float(ln[30:50]), 0.0, places=6)
                self.assertAlmostEqual(float(ln[50:70]), 0.0, places=6)
                return
        self.fail("node 5 not found in /NODE block")


# ── TET10 midside-ordering normalization ─────────────────────────────────────
# LS-DYNA *ELEMENT_SOLID and Radioss /TETRA10 agree on corners 1-4 and the base
# midsides 5/6/7 but disagree on the three APEX midsides 8/9/10:
#            slot8      slot9      slot10
#   LS-DYNA: mid(2,4)   mid(3,4)   mid(1,4)
#   Radioss: mid(1,4)   mid(2,4)   mid(3,4)
# The converter must permute LS-DYNA order → Radioss order before emit, else the
# snap pass collapses shared midsides (ERROR 558) and /TETRA10 volume drops ~30%.

def _t10_node(nid, x, y, z):
    """One *NODE card (I8 id + whitespace coords; parse_free reads it)."""
    return f"{nid:>8}{x:>16}{y:>16}{z:>16}"


def _t10_elem(eid, pid, nodes):
    """One two-line ten-node *ELEMENT_SOLID card (eid/pid, then 10 node IDs)."""
    return f"{eid:>8}{pid:>8}\n" + "".join(f"{n:>8}" for n in nodes)


def _t10_deck(title, node_lines, elem_lines):
    return (
        "*KEYWORD\n*TITLE\n" + title + "\n*NODE\n"
        + "\n".join(node_lines) + "\n*ELEMENT_SOLID\n"
        + "\n".join(elem_lines) + "\n"
        "*PART\ntet10 part\n         1         1         1\n"
        "*SECTION_SOLID\n         1        10\n"
        "*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
        "         1   2.7e-9   72000.0       0.3     200.0\n"
        "*CONTROL_TERMINATION\n       1.0\n*END\n"
    )


# A single LS-DYNA-ordered unit tet: same corners as TET10_K, but the three apex
# midsides carry LS-DYNA coordinates (node8=mid(2,4), node9=mid(3,4),
# node10=mid(1,4)). _normalize_tet10_ordering must permute it to Radioss order so
# the emitted /TETRA10 line reads 1 2 3 4 5 6 7 10 8 9.
TET10_DYNA_K = _t10_deck(
    "Quadratic tet10 (LS-DYNA apex order)",
    [
        _t10_node(1, 0.0, 0.0, 0.0),
        _t10_node(2, 1.0, 0.0, 0.0),
        _t10_node(3, 0.0, 1.0, 0.0),
        _t10_node(4, 0.0, 0.0, 1.0),
        _t10_node(5, 0.5, 0.0, 0.0),    # mid(1,2)  (agrees)
        _t10_node(6, 0.5, 0.5, 0.0),    # mid(2,3)  (agrees)
        _t10_node(7, 0.0, 0.5, 0.0),    # mid(1,3)  (agrees)
        _t10_node(8, 0.5, 0.0, 0.5),    # mid(2,4)  LS-DYNA n8
        _t10_node(9, 0.0, 0.5, 0.5),    # mid(3,4)  LS-DYNA n9
        _t10_node(10, 0.0, 0.0, 0.5),   # mid(1,4)  LS-DYNA n10
    ],
    [_t10_elem(1, 1, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])],
)


# Two LS-DYNA-ordered tets sharing the corner face {2,3,4} (and thus its three
# midside nodes 6/7/8). Under the wrong (unpermuted) map, the two elements imply
# different snap targets for the shared apex midsides → last-write-wins collapses
# distinct nodes (the ERROR 558 storm). Correctly normalized, the shared nodes
# resolve to one consistent midpoint each.
#   Tet A corners 1,2,3,4 ; Tet B corners 5,2,3,4 (apex 5 on the far side).
TET10_TWO_TET_SHARED_K = _t10_deck(
    "Two shared-face tet10 (LS-DYNA apex order)",
    [
        _t10_node(1, 0.0, 0.0, 0.0),    # tet A apex
        _t10_node(2, 1.0, 0.0, 0.0),
        _t10_node(3, 0.0, 1.0, 0.0),
        _t10_node(4, 0.0, 0.0, 1.0),
        _t10_node(5, 1.0, 1.0, 1.0),    # tet B apex
        _t10_node(6, 0.5, 0.5, 0.0),    # mid(2,3)  shared
        _t10_node(7, 0.5, 0.0, 0.5),    # mid(2,4)  shared
        _t10_node(8, 0.0, 0.5, 0.5),    # mid(3,4)  shared
        _t10_node(9, 0.5, 0.0, 0.0),    # mid(1,2)  tet A
        _t10_node(10, 0.0, 0.5, 0.0),   # mid(1,3)  tet A
        _t10_node(11, 0.0, 0.0, 0.5),   # mid(1,4)  tet A
        _t10_node(12, 1.0, 0.5, 0.5),   # mid(5,2)  tet B
        _t10_node(13, 0.5, 1.0, 0.5),   # mid(5,3)  tet B
        _t10_node(14, 0.5, 0.5, 1.0),   # mid(5,4)  tet B
    ],
    [
        # DYNA order: n5=mid(1,2),n6=mid(2,3),n7=mid(1,3),n8=mid(2,4),n9=mid(3,4),n10=mid(1,4)
        _t10_elem(1, 1, [1, 2, 3, 4, 9, 6, 10, 7, 8, 11]),
        _t10_elem(2, 1, [5, 2, 3, 4, 12, 6, 13, 7, 8, 14]),
    ],
)


class Tet10OrderingTests(unittest.TestCase):
    """LS-DYNA→Radioss /TETRA10 apex midside-ordering normalization."""

    # ── helpers ──────────────────────────────────────────────────────────────
    def _convert_deck(self, deck, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t10.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _tetra10_line(starter):
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip().startswith("/TETRA10/"))
        # eid line at i+1, node-id line at i+2
        return [int(x) for x in lines[i + 2].split()]

    @staticmethod
    def _node_coords(starter):
        # /NODE is followed by a "#  Node ID  X  Y  Z" comment header, so skip
        # "#" lines rather than treating them as the block terminator; the block
        # ends at the next "/" keyword.
        coords = {}
        in_node = False
        for ln in starter.splitlines():
            if ln.startswith("/NODE"):
                in_node = True
                continue
            if in_node:
                if ln.startswith("/"):
                    break
                if not ln.strip() or ln.startswith("#"):
                    continue
                coords[int(ln[:10])] = (
                    float(ln[10:30]), float(ln[30:50]), float(ln[50:70]))
        return coords

    @staticmethod
    def _tet_volume(p0, p1, p2, p3):
        a = [p1[k] - p0[k] for k in range(3)]
        b = [p2[k] - p0[k] for k in range(3)]
        c = [p3[k] - p0[k] for k in range(3)]
        cx = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
              a[0] * b[1] - a[1] * b[0])
        return abs(cx[0] * c[0] + cx[1] * c[1] + cx[2] * c[2]) / 6.0

    # ── 1. pure detector + permutation ───────────────────────────────────────
    def test_classify_and_permutation_index(self):
        from k2rad.topology import (
            classify_tet10_apex_order, TET10_DYNA_TO_RADIOSS)
        corners = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        dyna_apex = [(0.5, 0, 0.5), (0, 0.5, 0.5), (0, 0, 0.5)]   # mid(2,4)/(3,4)/(1,4)
        rad_apex = [(0, 0, 0.5), (0.5, 0, 0.5), (0, 0.5, 0.5)]    # mid(1,4)/(2,4)/(3,4)
        self.assertEqual(classify_tet10_apex_order(corners, dyna_apex), "dyna")
        self.assertEqual(classify_tet10_apex_order(corners, rad_apex), "radioss")
        self.assertEqual(classify_tet10_apex_order(corners, [None, None, None]),
                         "ambiguous")
        self.assertEqual(TET10_DYNA_TO_RADIOSS, (0, 1, 2, 3, 4, 5, 6, 9, 7, 8))
        dyna_conn = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual([dyna_conn[p] for p in TET10_DYNA_TO_RADIOSS],
                         [1, 2, 3, 4, 5, 6, 7, 10, 8, 9])

    # ── 2. cross-element consistency (BUG 1 / ERROR 558) ─────────────────────
    def test_shared_midsides_not_collapsed(self):
        _result, starter = self._convert_deck(TET10_TWO_TET_SHARED_K)
        coords = self._node_coords(starter)
        # The three shared midside nodes must land on their true edge midpoints…
        for nid, want in ((6, (0.5, 0.5, 0.0)), (7, (0.5, 0.0, 0.5)),
                          (8, (0.0, 0.5, 0.5))):
            got = coords[nid]
            for k in range(3):
                self.assertAlmostEqual(got[k], want[k], places=6,
                                       msg=f"node {nid} coord {k}")
        # …and no two of the 14 nodes may collapse onto one point.
        rounded = [tuple(round(v, 6) for v in c) for c in coords.values()]
        self.assertEqual(len(rounded), len(set(rounded)),
                         "distinct nodes collapsed onto one coordinate")

    # ── 3. permuted /TETRA10 emit (BUG 2 / silent −30% volume) ───────────────
    def test_tetra10_emit_is_permuted_to_radioss(self):
        _result, starter = self._convert_deck(TET10_DYNA_K)
        conn = self._tetra10_line(starter)
        # LS-DYNA input 1..10 → Radioss order 1 2 3 4 5 6 7 10 8 9. Emitting the
        # LS-DYNA order verbatim was the silent −30%-volume bug.
        self.assertEqual(conn, [1, 2, 3, 4, 5, 6, 7, 10, 8, 9])
        coords = self._node_coords(starter)
        # Each Radioss apex slot now carries the geometrically-correct midside.
        for slot, want in ((7, (0.0, 0.0, 0.5)),    # n8 = mid(1,4)
                           (8, (0.5, 0.0, 0.5)),     # n9 = mid(2,4)
                           (9, (0.0, 0.5, 0.5))):    # n10 = mid(3,4)
            got = coords[conn[slot]]
            for k in range(3):
                self.assertAlmostEqual(got[k], want[k], places=6)
        # Corner-tet volume is the analytic 1/6 (not 0.7×1/6), corners intact.
        vol = self._tet_volume(*[coords[conn[k]] for k in range(4)])
        self.assertAlmostEqual(vol, 1.0 / 6.0, places=6)

    # ── 4. --tet10-to-tet4 keeps the (unchanged) corners ─────────────────────
    def test_tet10_to_tet4_unaffected_by_normalization(self):
        _result, starter = self._convert_deck(TET10_DYNA_K, tet10_to_tet4=True)
        self.assertNotIn("/TETRA10", starter)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip().startswith("/TETRA4/"))
        corners = [int(x) for x in lines[i + 1].split()][1:]   # drop eid
        self.assertEqual(corners, [1, 2, 3, 4])                # corners never moved
        coords = self._node_coords(starter)
        vol = self._tet_volume(*[coords[c] for c in corners])
        self.assertAlmostEqual(vol, 1.0 / 6.0, places=6)

    # ── 5. already-Radioss deck is left untouched ────────────────────────────
    def test_radioss_ordered_deck_not_permuted(self):
        result, starter = self._convert_deck(TET10_K)
        self.assertEqual(self._tetra10_line(starter), list(range(1, 11)))
        self.assertTrue(
            any("Radioss/Abaqus" in w and "no permutation" in w
                for w in result.warnings),
            f"expected a 'detected Radioss order' note in {result.warnings}")

    # ── 6. idempotency guard (3-cycle must not double-apply) ─────────────────
    def test_normalization_is_idempotent(self):
        from k2rad.writer import _normalize_tet10_ordering
        state = ConversionState()
        state.nodes = {
            1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0), 3: NodeData(0, 1, 0),
            4: NodeData(0, 0, 1), 5: NodeData(0.5, 0, 0), 6: NodeData(0.5, 0.5, 0),
            7: NodeData(0, 0.5, 0), 8: NodeData(0.5, 0, 0.5),
            9: NodeData(0, 0.5, 0.5), 10: NodeData(0, 0, 0.5),
        }
        state.solid_elems = [SolidElem(1, 1, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])]
        n1 = _normalize_tet10_ordering(state)
        conn1 = list(state.solid_elems[0].nodes)
        n2 = _normalize_tet10_ordering(state)          # guarded → no-op
        conn2 = list(state.solid_elems[0].nodes)
        self.assertEqual((n1, n2), (1, 0))
        self.assertEqual(conn1, [1, 2, 3, 4, 5, 6, 7, 10, 8, 9])
        self.assertEqual(conn2, conn1)                 # not double-permuted

    # ── 7. no-op / no mutation on a non-tet10 mesh ───────────────────────────
    def test_no_tet10_is_noop(self):
        from k2rad.writer import _normalize_tet10_ordering
        state = ConversionState()
        state.nodes = {i: NodeData(float(i), 0.0, 0.0) for i in range(1, 9)}
        # tet4 (4), penta6 (6) and hex8 (8) all lack the 10-node signature, so the
        # apex permutation must never touch them — an 8/6-node solid in a mixed
        # deck stays byte-identical (the permutation only ever filters len==10).
        state.solid_elems = [
            SolidElem(1, 1, [1, 2, 3, 4]),                    # tet4
            SolidElem(2, 1, [1, 2, 3, 4, 5, 6]),              # penta6
            SolidElem(3, 1, [1, 2, 3, 4, 5, 6, 7, 8]),        # hex8
        ]
        state.shell_elems = [ShellElem(4, 1, [1, 2, 3, 4])]
        before = [list(e.nodes) for e in state.solid_elems]
        self.assertEqual(_normalize_tet10_ordering(state), 0)
        self.assertEqual([list(e.nodes) for e in state.solid_elems], before)

    # ── 8. ambiguous / coordinate-less tet10 → DYNA default + loud warn ──────
    def test_ambiguous_defaults_to_dyna_with_warning(self):
        from k2rad.writer import _normalize_tet10_ordering
        state = ConversionState()
        # Corners defined, apex midside coords absent → classify == "ambiguous".
        state.nodes = {
            1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0),
            3: NodeData(0, 1, 0), 4: NodeData(0, 0, 1),
        }
        state.solid_elems = [SolidElem(1, 1, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])]
        n = _normalize_tet10_ordering(state)
        self.assertEqual(n, 1)
        self.assertEqual(state.solid_elems[0].nodes,
                         [1, 2, 3, 4, 5, 6, 7, 10, 8, 9])   # DYNA-default permute
        self.assertTrue(
            any("ambiguous" in w and "LS-DYNA" in w for w in state.warnings),
            f"expected a loud ambiguity warning in {state.warnings}")

    # ── helper: build a disjoint, shifted tet10 in a chosen apex convention ───
    @staticmethod
    def _apex_tet(base, x0, order):
        """A single well-shaped tet10 (node ids base..base+9, translated by *x0*)
        whose apex midsides are laid out in ``"dyna"`` or ``"radioss"`` order.
        Returns ({nid: NodeData}, SolidElem)."""
        c = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0),
             2: (0.0, 1.0, 0.0), 3: (0.0, 0.0, 1.0)}

        def mid(a, b):
            return NodeData((c[a][0] + c[b][0]) / 2 + x0,
                            (c[a][1] + c[b][1]) / 2,
                            (c[a][2] + c[b][2]) / 2)

        nodes = {base + k: NodeData(c[k][0] + x0, c[k][1], c[k][2]) for k in c}
        nodes[base + 4] = mid(0, 1)          # base midsides (agree)
        nodes[base + 5] = mid(1, 2)
        nodes[base + 6] = mid(0, 2)
        if order == "dyna":                  # apex slots 8/9/10 = mid(2,4)/(3,4)/(1,4)
            nodes[base + 7] = mid(1, 3)
            nodes[base + 8] = mid(2, 3)
            nodes[base + 9] = mid(0, 3)
        else:                                # radioss = mid(1,4)/(2,4)/(3,4)
            nodes[base + 7] = mid(0, 3)
            nodes[base + 8] = mid(1, 3)
            nodes[base + 9] = mid(2, 3)
        return nodes, SolidElem(base, 1, [base + k for k in range(10)])

    # ── 9. majority vote: a stray unclassifiable element cannot flip a Radioss
    #      mesh into a wrongful permutation (all-or-nothing → majority) ─────────
    def test_radioss_majority_survives_stray_ambiguous(self):
        from k2rad.writer import _normalize_tet10_ordering
        state = ConversionState()
        na, ea = self._apex_tet(1, 0.0, "radioss")
        nb, eb = self._apex_tet(11, 10.0, "radioss")
        state.nodes = {**na, **nb}
        # A single coordinate-less (ambiguous) sliver element ids 21..30.
        for i, xyz in zip(range(21, 25),
                          [(0, 0, 5), (1, 0, 5), (0, 1, 5), (0, 0, 6)]):
            state.nodes[i] = NodeData(*xyz)                # corners only; apex absent
        ec = SolidElem(21, 1, list(range(21, 31)))
        state.solid_elems = [ea, eb, ec]
        before = [list(e.nodes) for e in state.solid_elems]
        n = _normalize_tet10_ordering(state)
        self.assertEqual(n, 0, "one ambiguous element wrongly flipped a Radioss mesh")
        self.assertEqual([list(e.nodes) for e in state.solid_elems], before)
        self.assertTrue(
            any("majority" in w and "NO permutation" in w for w in state.warnings),
            f"expected a Radioss-majority no-op note in {state.warnings}")

    # ── 10. majority vote the other way: dyna-majority permutes ALL + warns ───
    def test_dyna_majority_permutes_all_with_mixed_warning(self):
        from k2rad.writer import _normalize_tet10_ordering
        state = ConversionState()
        na, ea = self._apex_tet(1, 0.0, "dyna")
        nb, eb = self._apex_tet(11, 10.0, "dyna")
        nc, ec = self._apex_tet(21, 20.0, "radioss")       # the minority
        state.nodes = {**na, **nb, **nc}
        state.solid_elems = [ea, eb, ec]
        n = _normalize_tet10_ordering(state)
        self.assertEqual(n, 3)                              # 2 dyna > 1 radioss → all
        self.assertEqual(ea.nodes, [1, 2, 3, 4, 5, 6, 7, 10, 8, 9])
        self.assertEqual(eb.nodes, [11, 12, 13, 14, 15, 16, 17, 20, 18, 19])
        self.assertEqual(ec.nodes, [21, 22, 23, 24, 25, 26, 27, 30, 28, 29])
        self.assertTrue(
            any("not uniform" in w for w in state.warnings),
            f"expected a mixed-order warning in {state.warnings}")

    # ── 11. off-edge apex midside → ambiguous (distance guard, not None) ──────
    def test_off_edge_apex_classifies_ambiguous(self):
        from k2rad.topology import classify_tet10_apex_order
        corners = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        # First apex node sits ~half an edge off every apex-edge midpoint.
        off = [(0.5, 0.5, 0.5), (0.0, 0.5, 0.5), (0.0, 0.0, 0.5)]
        self.assertEqual(classify_tet10_apex_order(corners, off), "ambiguous")

    # ── 12. genuinely inconsistent shared midside trips the disagree verifier ─
    def test_inconsistent_shared_midside_trips_verifier(self):
        from k2rad.writer.mesh import _warn_tet10_order_inconsistent
        state = ConversionState()
        # Two tets both name node 100 as their slot-5 base midside (mid of corners
        # 1&2), but their corner geometry implies DIFFERENT midpoints for it — an
        # inconsistency no single apex permutation can repair; the straight-edge
        # snap would collapse node 100, so the verifier must flag it.
        state.nodes = {
            1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0),        # tet A → mid (0.5,0,0)
            3: NodeData(0, 1, 0), 4: NodeData(0, 0, 1),
            11: NodeData(0, 0, 0), 12: NodeData(10, 0, 0),     # tet B → mid (5,0,0)
            13: NodeData(0, 1, 0), 14: NodeData(0, 0, 1),
            100: NodeData(0.5, 0, 0),                          # the shared midside
        }
        for i in range(201, 211):                              # distinct dummy midsides
            state.nodes[i] = NodeData(float(i), 0.0, 0.0)
        eA = SolidElem(1, 1, [1, 2, 3, 4, 100, 201, 202, 203, 204, 205])
        eB = SolidElem(2, 1, [11, 12, 13, 14, 100, 206, 207, 208, 209, 210])
        disagree = _warn_tet10_order_inconsistent(state, [eA, eB])
        self.assertGreaterEqual(disagree, 1)
        self.assertTrue(
            any("verifier" in w and "conflicting" in w for w in state.warnings),
            f"expected a shared-midside inconsistency warning in {state.warnings}")


# A model with a free reference node (node 99, in no element) under implicit.
# OpenRadioss implicit makes its zero-stiffness DOFs singular, so the converter
# must constrain it; under explicit, free nodes are fine and must be left alone.
FREE_NODE_K = """\
*KEYWORD
*TITLE
Free reference node guard
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
      99             5.0             5.0             5.0
*ELEMENT_SOLID
       1       1       1       2       3       4       4       4       4       4
*PART
solid
         1         1         1
*SECTION_SOLID
         1        10
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTROL_IMPLICIT_GENERAL
         1      0.01
*CONTROL_TERMINATION
       1.0
*END
"""


# Two 10-node tets: element 1 well-shaped, element 2 a sliver (corners 13 & 14
# nearly coincident → ~zero volume). OpenRadioss rejects sliver /TETRA10 (ERROR
# 489), so the converter must drop element 2 while keeping element 1.
TET10_SLIVER_K = """\
*KEYWORD
*TITLE
Sliver tet10 dropped
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
       5             0.5             0.0             0.0
       6             0.5             0.5             0.0
       7             0.0             0.5             0.0
       8             0.0             0.0             0.5
       9             0.5             0.0             0.5
      10             0.0             0.5             0.5
      11             5.0             0.0             0.0
      12             7.0             0.0             0.0
      13             5.0             2.0             0.0
      14             5.0             2.0            0.02
      15             6.0             0.0             0.0
      16             6.0             1.0             0.0
      17             5.0             1.0             0.0
      18             5.0             1.0            0.01
      19             6.0             1.0            0.01
      20             5.0             2.0            0.01
*ELEMENT_SOLID
       1       1
       1       2       3       4       5       6       7       8       9      10
       2       1
      11      12      13      14      15      16      17      18      19      20
*PART
tet10 part
         1         1         1
*SECTION_SOLID
         1        10
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   2.7e-9   72000.0       0.3     200.0
*CONTROL_TERMINATION
       1.0
*END
"""


class Tet10SliverTests(unittest.TestCase):
    """Near-degenerate (sliver) 10-node tets are dropped (OpenRadioss ERROR 489)."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "sliver.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_sliver_dropped_good_kept(self):
        result, s = self._convert(TET10_SLIVER_K)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/TETRA10/"))
        eids = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith(("/", "#")):
            toks = lines[j].split()
            if len(toks) == 1:           # eid line
                eids.append(int(toks[0]))
                j += 2
            else:
                j += 1
        self.assertIn(1, eids)            # well-shaped element kept
        self.assertNotIn(2, eids)         # sliver dropped
        self.assertTrue(any("sliver" in w for w in result.warnings))


# Three 4-node tets under implicit: element 1 well-shaped (AR 1.4), element 2 a
# moderate sliver (AR ~11 — warn but keep), element 3 an extreme near-duplicate-
# node sliver (AR ~224, shortest edge 0.5% of the mean — drop). Mirrors the
# hr-anlenkung bracket failure: implicit contact crushes extreme TET4 slivers to
# zero volume → AUTOSPC dimension-flip dt-cut loops / element inversion. Nodes
# 9-12 belong only to element 3, so dropping it must hand them to the free-node
# guard (otherwise their zero-stiffness DOFs make the implicit tangent singular).
TET4_SLIVER_K = """\
*KEYWORD
*TITLE
Sliver tet4 screening
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
       5            10.0             0.0             0.0
       6            11.0             0.0             0.0
       7            10.5            0.08             0.0
       8            10.5            0.04            0.08
       9            20.0             0.0             0.0
      10            21.0             0.0             0.0
      11            20.5             1.0             0.0
      12            20.5             1.0           0.005
*ELEMENT_SOLID
       1       1       1       2       3       4       4       4       4       4
       2       1       5       6       7       8       8       8       8       8
       3       1       9      10      11      12      12      12      12      12
*PART
tet4 part
         1         1         1
*SECTION_SOLID
         1        10
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTROL_IMPLICIT_GENERAL
         1      0.01
*CONTROL_TERMINATION
       1.0
*END
"""


class Tet4SliverTests(unittest.TestCase):
    """Implicit decks screen 4-node tets: extreme slivers dropped (their orphaned
    nodes picked up by the free-node guard), moderate slivers kept but warned
    with the element list; explicit decks are left untouched."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "sliver4.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def _tetra4_eids(self, starter: str):
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/TETRA4/"))
        eids = []
        for ln in lines[i + 1:]:
            if ln.startswith(("/", "#")):
                break
            eids.append(int(ln.split()[0]))
        return eids

    def test_implicit_drops_extreme_keeps_good_and_moderate(self):
        result, s = self._convert(TET4_SLIVER_K)
        eids = self._tetra4_eids(s)
        self.assertIn(1, eids)            # well-shaped kept
        self.assertIn(2, eids)            # moderate sliver kept (warn only)
        self.assertNotIn(3, eids)         # extreme sliver dropped
        warn = next(w for w in result.warnings if "extreme-sliver" in w)
        self.assertRegex(warn, r"Dropped element\(s\): 3$")

    def test_implicit_warns_moderate_sliver_with_element_list(self):
        result, _ = self._convert(TET4_SLIVER_K)
        warn = next(w for w in result.warnings if "4-node tet(s) kept" in w)
        self.assertRegex(warn, r"Element\(s\): 2$")

    def test_dropped_tet_nodes_constrained_by_free_node_guard(self):
        # Nodes 9-12 are referenced only by dropped element 3 → they must land
        # in the free-node /BCS group, which requires the screening to mutate
        # state.solid_elems before the guard runs (not skip at write time).
        _, s = self._convert(TET4_SLIVER_K)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip() == "free_reference_nodes")
        grp = []
        for ln in lines[i + 1:]:
            if ln.startswith(("/", "#")):
                break
            grp += [int(x) for x in ln.split()]
        self.assertEqual(grp, [9, 10, 11, 12])

    def test_explicit_keeps_all_tets_and_stays_silent(self):
        deck = TET4_SLIVER_K.replace(
            "*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n", "")
        result, s = self._convert(deck)
        self.assertEqual(sorted(self._tetra4_eids(s)), [1, 2, 3])
        self.assertFalse(any("4-node tet" in w for w in result.warnings))


# A sound 8-node brick plus two zero-volume degenerates: element 2 collapsed to
# a single point (all eight nodes identical — the elevator-linkage foxcore-rund
# failure: such elements written as /BRICK abort the starter with ERROR 245
# "ZERO OR NEGATIVE 3D SOLID VOLUME") and element 3 collapsed to an edge (two
# distinct nodes). Both must be dropped and logged, never written; the sound
# brick stays. The deck is explicit on purpose: the degenerate screen is
# unconditional, unlike the implicit-only tet4 sliver screen.
DEGENERATE_SOLID_K = """\
*KEYWORD
*TITLE
Degenerate solid screening
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             0.0             0.0             1.0
       6             1.0             0.0             1.0
       7             1.0             1.0             1.0
       8             0.0             1.0             1.0
       9             5.0             5.0             5.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
       2       1       9       9       9       9       9       9       9       9
       3       1       1       2       2       2       2       2       2       2
*PART
brick part
         1         1         1
*SECTION_SOLID
         1         1
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTROL_TERMINATION
       1.0
*END
"""


class DegenerateSolidTests(unittest.TestCase):
    """Solids with fewer than 4 distinct nodes have exactly zero volume; written
    as /BRICK the OpenRadioss starter rejects the deck (ERROR 245), so the
    converter must drop them with a logged warning instead."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "degen.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_collapsed_solids_dropped_sound_brick_kept(self):
        result, s = self._convert(DEGENERATE_SOLID_K)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/BRICK/"))
        eids = []
        for ln in lines[i + 1:]:
            if ln.startswith(("/", "#")):
                break
            eids.append(int(ln.split()[0]))
        self.assertEqual(eids, [1])       # point/edge collapses never written

    def test_drop_is_logged_with_element_ids(self):
        result, _ = self._convert(DEGENERATE_SOLID_K)
        warn = next(w for w in result.warnings if "degenerate solid" in w)
        self.assertIn("ERROR 245", warn)
        self.assertRegex(warn, r"Dropped element\(s\): 2, 3$")


class FreeNodeGuardTests(unittest.TestCase):
    """Implicit: free nodes (no element/rigid body) are constrained to avoid a
    singular tangent; explicit leaves them untouched."""

    def _starter(self, deck: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "free.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return Path(convert(path).starter_path).read_text()

    def test_implicit_constrains_free_node(self):
        s = self._starter(FREE_NODE_K)
        self.assertIn("free_reference_nodes", s)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "free_reference_nodes")
        grp = []
        for ln in lines[i + 1:]:
            if ln.startswith(("/", "#")):
                break
            grp += [int(x) for x in ln.split()]
        self.assertEqual(grp, [99])

    def test_explicit_leaves_free_node_alone(self):
        # Drop the implicit control → explicit run → no free-node guard.
        deck = FREE_NODE_K.replace(
            "*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n", "")
        self.assertNotIn("free_reference_nodes", self._starter(deck))


class AnimDtFromD3plotTests(unittest.TestCase):
    """/ANIM/DT frequency comes from *DATABASE_BINARY_D3PLOT (dt, else
    endtim/npltc); endtim/40 is only a last-resort default when no d3plot
    output frequency is given."""

    # 10 s run; {d3plot} is replaced with a D3PLOT block (or "").
    BASE = (
        "*KEYWORD\n*TITLE\nanim dt test\n*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2             1.0             0.0             0.0\n"
        "       3             1.0             1.0             0.0\n"
        "       4             0.0             1.0             0.0\n"
        "*ELEMENT_SHELL\n       1       1       1       2       3       4\n"
        "*PART\nshell part\n         1         1         1\n"
        "*SECTION_SHELL\n         1         2       1.0         3\n       1.0\n"
        "*MAT_ELASTIC\n         1   7.86e-9    210000.0      0.3\n"
        "{d3plot}*CONTROL_TERMINATION\n      10.0\n*END\n"
    )

    def _anim_dt(self, d3plot_block: str) -> float:
        deck = self.BASE.format(d3plot=d3plot_block)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "anim.k")
        with open(path, "w") as fh:
            fh.write(deck)
        engine = Path(convert(path).engine_path).read_text().splitlines()
        i = engine.index("/ANIM/DT")
        # "/ANIM/DT" then "0. <freq>"
        return float(engine[i + 1].split()[1])

    def test_uses_d3plot_dt(self):
        # dt explicitly given -> use it verbatim (NOT endtim/40 = 0.25).
        freq = self._anim_dt(
            "*DATABASE_BINARY_D3PLOT\n"
            "$#      dt      lcdt      beam     npltc    psetid\n"
            "     0.005         0         0         0         0\n")
        self.assertAlmostEqual(freq, 0.005)

    def test_uses_npltc_when_dt_zero(self):
        # dt=0 but npltc=50 over a 10 s run -> endtim/npltc = 0.2 (NOT 0.25).
        # Regression guard for the field-index bug (npltc was read from the
        # PSETID column, so this used to fall back to endtim/40).
        freq = self._anim_dt(
            "*DATABASE_BINARY_D3PLOT\n"
            "$#      dt      lcdt      beam     npltc    psetid\n"
            "       0.0         0         0        50         0\n")
        self.assertAlmostEqual(freq, 0.2)

    def test_falls_back_to_endtim_over_40_without_d3plot(self):
        # No *DATABASE_BINARY_D3PLOT at all -> default endtim/40 = 0.25.
        self.assertAlmostEqual(self._anim_dt(""), 0.25)


# One quad shell part exercising the card layouts audited against the
# hm_cfg_files FORMAT blocks (the exact reader spec of the user's OpenRadioss
# build): LAW44 (VP column), /DAMP (explicit beta), /INIVEL/TRA+ROT,
# /SURF/SEG + /PLOAD, and /SKEW/FIX from *DEFINE_COORDINATE_SYSTEM points.
CARD_LAYOUT_K = """\
*KEYWORD
*TITLE
Card layout regression deck
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       0.1
*MAT_PLASTIC_KINEMATIC
         1    7.8E-9  210000.0       0.3     350.0    1000.0       0.0
      40.0       5.0       0.0         1
*ELEMENT_SHELL
       1       1       1       2       3       4
*DEFINE_CURVE
         1         0       1.0       1.0
                 0.0                 0.0
                 1.0                 1.0
*LOAD_SEGMENT
         1       2.5       0.0         1         2         3         4
*INITIAL_VELOCITY_NODE
       1       5.0       0.0       0.0       0.0       0.0       2.0
       2       5.0       0.0       0.0       0.0       0.0       2.0
*DAMPING_GLOBAL
         0       0.3
*DEFINE_COORDINATE_SYSTEM
         9      10.0       0.0       0.0      10.0       1.0       0.0
       9.0       0.0       0.0
*CONTROL_TERMINATION
       1.0
*END
"""


class CardLayoutTests(unittest.TestCase):
    """Field-position regressions for cards the CFG audit (2026-06-10) found
    misaligned: every assertion below slices the exact columns the OpenRadioss
    reader (hm_cfg_files FORMAT blocks at /BEGIN 2022) reads."""

    def _starter(self, deck: str = CARD_LAYOUT_K) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "layout.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return Path(result.starter_path).read_text()

    @staticmethod
    def _block(starter: str, prefix: str):
        """Return (lines, index of keyword line) for the first block whose
        keyword line starts with *prefix*."""
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith(prefix))
        return lines, i

    @staticmethod
    def _data_lines(lines, i):
        """All data lines (non-comment, non-keyword) following lines[i] until
        the next keyword."""
        out = []
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            out.append(ln)
        return out

    def test_law44_hardening_mapping(self):
        # b must be the PLASTIC hardening modulus H = E*ETAN/(E-ETAN), not raw
        # ETAN (DYNA's tangent modulus of the TOTAL stress-strain curve), and
        # DYNA BETA=0 (kinematic) must land as Chard=1 (Radioss kinematic) —
        # the conventions run in opposite directions.
        s = self._starter()
        lines, i = self._block(s, "/MAT/LAW44/")
        card3 = self._data_lines(lines, i)[1 + 2]       # title, rho, E/nu, [a/b/n/Chard]
        self.assertAlmostEqual(float(card3[0:20]), 350.0)               # a = SIGY
        self.assertAlmostEqual(float(card3[20:40]),
                               210000.0 * 1000.0 / 209000.0, places=4)  # b = H
        self.assertAlmostEqual(float(card3[60:80]), 1.0)                # Chard = 1-BETA

    def test_mat_failure_becomes_fail_johnson_all_layers(self):
        # A failure strain on the material must NOT populate LAW44 EpsMax
        # (one-integration-point deletion) but a /FAIL/JOHNSON with D1=FS and
        # Ifail_sh=2 (all-layers deletion), matching LS-DYNA's built-in
        # material-erosion rule. Layout: fail_johnson.cfg FORMAT(radioss2017).
        deck = CARD_LAYOUT_K.replace(
            "      40.0       5.0       0.0         1",
            "      40.0       5.0    0.0015         1")
        s = self._starter(deck)
        lines, i = self._block(s, "/MAT/LAW44/")
        card5 = self._data_lines(lines, i)[1 + 4]       # [EpsMax/Et1/Et2]
        self.assertAlmostEqual(float(card5[0:20]), 0.0)  # EpsMax stays empty
        lines, i = self._block(s, "/FAIL/JOHNSON/1")
        d = self._data_lines(lines, i)
        self.assertAlmostEqual(float(d[0][0:20]), 0.0015)   # D1
        self.assertAlmostEqual(float(d[0][20:40]), 0.0)     # D2
        self.assertEqual(d[1][20:30].strip(), "2")          # IFAIL_SH = all layers
        self.assertEqual(d[1][30:40].strip(), "1")          # IFAIL_SO
        # fs=0 deck must NOT emit a /FAIL card at all
        self.assertNotIn("/FAIL/JOHNSON/", self._starter())

    def test_law44_vp_in_cols_91_100(self):
        # cfg card 4: C(20) P(20) ICC(10) ISMOOTH(10) F_CUT(20) blank(10) VP(10).
        # Regression: VP used to be written at cols 81-90 (the blank), so the
        # reader's VP (cols 91-100) silently defaulted to 0.
        s = self._starter()
        lines, i = self._block(s, "/MAT/LAW44/")
        card4 = self._data_lines(lines, i)[1 + 3]   # title, rho, E/nu, a/b/n, c/p...
        self.assertEqual(card4[0:20].strip(), "40")     # C  (SRC)
        self.assertEqual(card4[20:40].strip(), "5")     # P  (SRP)
        self.assertEqual(card4[80:90].strip(), "")      # blank column
        self.assertEqual(card4[90:100].strip(), "1")    # VP
        self.assertEqual(len(card4), 100)

    def test_damp_beta_written_explicitly(self):
        # cfg /DAMP card: Alpha(20) Beta(20) grnod(10) skew(10) Tstart(20)
        # Tstop(20). Regression: the alpha-only path skipped Beta, so the
        # grnod_ID digits were parsed as a huge stiffness-damping Beta.
        s = self._starter()
        lines, i = self._block(s, "/DAMP/")
        card = self._data_lines(lines, i)[1]            # after title
        self.assertEqual(card[0:20].strip(), "0.3")     # alpha = valdmp
        self.assertEqual(card[20:40].strip(), "0")      # beta explicit 0
        self.assertGreater(int(card[40:50]), 0)         # grnod_ID
        self.assertEqual(int(card[50:60]), 0)           # skew_ID
        self.assertEqual(len(card), 100)

    def test_inivel_tra_and_rot_blocks(self):
        # Valid subtypes are TRA/ROT (not NODE/RBODY) and the data is ONE card:
        # Vx(20) Vy(20) Vz(20) Gnod_id(10) Skew_id(10).
        s = self._starter()
        self.assertNotIn("/INIVEL/NODE/", s)
        lines, i = self._block(s, "/INIVEL/TRA/")
        card = self._data_lines(lines, i)[1]
        self.assertEqual(card[0:20].strip(), "5")       # Vx
        self.assertGreater(int(card[60:70]), 0)         # Gnod_id
        self.assertEqual(int(card[70:80]), 0)           # Skew_id
        lines, i = self._block(s, "/INIVEL/ROT/")
        card = self._data_lines(lines, i)[1]
        self.assertEqual(card[40:60].strip(), "2")      # Wz in the Vz slot
        self.assertGreater(int(card[60:70]), 0)

    def test_load_segment_becomes_surf_seg_plus_pload(self):
        # /PLOAD's single card references a /SURF/SEG (seg_ID n1 n2 n3 n4);
        # scales sit at cols 61-80 / 81-100. Regression: segments used to be
        # inlined into /PLOAD with invented Dir/Tstart fields.
        s = self._starter()
        lines, i = self._block(s, "/SURF/SEG/")
        surf_id = int(lines[i].split("/")[3])
        seg = self._data_lines(lines, i)[1]             # after title
        self.assertEqual(
            [int(seg[k:k + 10]) for k in range(0, 50, 10)], [1, 1, 2, 3, 4])
        lines, i = self._block(s, "/PLOAD/")
        card = self._data_lines(lines, i)[1]
        self.assertEqual(int(card[0:10]), surf_id)      # surf_ID
        self.assertEqual(int(card[10:20]), 1)           # fct_IDT
        self.assertEqual(card[60:80].strip(), "1")      # Ascale_x
        self.assertEqual(card[80:100].strip(), "2.5")   # Fscale_y = SF
        self.assertEqual(len(card), 100)

    def test_skew_fix_writes_local_y_and_z_vectors(self):
        # /SKEW/FIX cards are the local Y and Z AXIS VECTORS (X' = Y'×Z'), and
        # *DEFINE_COORDINATE_SYSTEM gives POINTS that must be origin-subtracted.
        # Here: O=(10,0,0), L=(10,1,0) → X=(0,1,0); P=(9,0,0) → Z=X×(P−O)=(0,0,1),
        # Y=Z×X=(−1,0,0). Regression: raw points went out as X/Y vectors, which
        # the reader interprets as Y'/Z' → a cyclically permuted frame.
        s = self._starter()
        lines, i = self._block(s, "/SKEW/FIX/9")
        cards = self._data_lines(lines, i)
        origin = [float(x) for x in cards[1].split()]
        yvec = [float(x) for x in cards[2].split()]
        zvec = [float(x) for x in cards[3].split()]
        self.assertEqual(origin, [10.0, 0.0, 0.0])
        self.assertEqual(yvec, [-1.0, 0.0, 0.0])
        self.assertEqual(zvec, [0.0, 0.0, 1.0])


# Implicit force-control deck: rigid pin (part 2, nodes 5-8, master node 5)
# pulled in Y and Z by two *LOAD_RIGID_BODY cards, held to the deformable part 1
# only by a clearance-fit TYPE7 contact (id 9) whose Card3 SST/MST → Gapmin 0.11.
# This is the minimal analogue of the RB_pull elevator model (open item 0b): the
# three opt-in stabilization fixes target exactly this shape of deck.
FORCE_RB_K = """\
*KEYWORD
*TITLE
force-control grounding spring test
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
*DEFINE_CURVE
         1         0       1.0       1.0
                 0.0                 0.0
                 1.0                 1.0
*CONTROL_IMPLICIT_GENERAL
         1     0.001
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                              pin_pair
         1         2         3         3         0         0         0         0
       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20
       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0
*LOAD_RIGID_BODY
         2         2         1   -5800.0
*LOAD_RIGID_BODY
         2         3         1   -1200.0
*CONTROL_TERMINATION
       1.0
*END
"""

# Stfac / Fric / Gapmin / Tstart / Tstop data line of /INTER/TYPE7/9 in each
# configuration (fixed 20-char fields).
_TYPE7_9_DEFAULT = ("                   0                 0.2                0.11"
                    "                   0                   0")          # Stfac 0, Gapmin 0.11
_TYPE7_9_SOFTENED = ("                 0.3                 0.2                0.11"
                     "                   0                   0")         # Stfac 0.3
_TYPE7_9_GAPMIN03 = ("                   0                 0.2                0.03"
                     "                   0                   0")         # Gapmin 0.03
_TYPE7_9_FULL_RECIPE = ("                 0.3                 0.2                0.03"
                        "                   0                   0")      # Stfac 0.3 + Gapmin 0.03
# One SPR_GENE DOF K/C/A/B/D data line with the stiffness in field 1.
_SPR_K = lambda k: (f"{str(k).rjust(20)}                   0                   0"
                    "                   0                   0")


class ForceControlStabilizationTests(unittest.TestCase):
    """The three opt-in force-control fixes (--ground-springs / --inter-gapmin /
    --soften-stfac).  Each must leave the deck byte-identical when absent and
    reproduce the validated RB_pull manual patches when present (open item 0b)."""

    def _convert(self, deck: str, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "fc.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _spring_nodes(starter: str):
        """(node_ID1, node_ID2) of the first /SPRING element = (master, ground)."""
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/SPRING/"):
                fields = lines[i + 2].split()      # /SPRING, "# sprg_ID...", data
                return int(fields[1]), int(fields[2])
        raise AssertionError("no /SPRING block found")

    @staticmethod
    def _prop_type8_block(starter: str):
        """Lines of the first /PROP/TYPE8 block: its header through the last data
        card (i.e. up to, but excluding, the next keyword line — the /PART)."""
        lines = starter.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("/PROP/TYPE8/"):
                block = [ln]
                for nxt in lines[i + 1:]:
                    if nxt.startswith("/"):
                        break
                    block.append(nxt)
                return block
        raise AssertionError("no /PROP/TYPE8 block found")

    # ── off by default: byte-stability ──────────────────────────────────────
    def test_defaults_emit_no_stabilization(self):
        result, starter = self._convert(FORCE_RB_K)
        self.assertNotIn("/PROP/TYPE8", starter)
        self.assertNotIn("/SPRING/", starter)
        self.assertNotIn("GROUNDING SPRINGS", starter)
        self.assertIn(_TYPE7_9_DEFAULT, starter)            # Stfac 0, Gapmin 0.11
        self.assertFalse(any("--ground-springs" in w or "--soften-stfac" in w
                             or "--inter-gapmin" in w for w in result.warnings))

    def test_explicit_default_options_match_no_options(self):
        # Passing the option defaults explicitly must be byte-identical to omitting them.
        _, plain = self._convert(FORCE_RB_K)
        _, defaulted = self._convert(FORCE_RB_K, ground_springs=False,
                                     ground_spring_k=100.0, inter_gapmin={},
                                     soften_stfac=None)
        self.assertEqual(plain, defaulted)

    # ── --ground-springs ─────────────────────────────────────────────────────
    def test_ground_springs_inject_spr_gene_on_loaded_axes(self):
        result, starter = self._convert(FORCE_RB_K, ground_springs=True)
        self.assertIn("/PROP/TYPE8/", starter)
        self.assertIn("/SPRING/", starter)
        # K=100 on exactly the two loaded translational axes (Y, Z); X/RX/RY/RZ are 0.
        self.assertEqual(starter.count(_SPR_K(100)), 2)
        # The spring connects the /RBODY master node to a new fixed ground node.
        # With element-free masters on by default the master is the synthesized
        # node 9 (max mesh node 8 + 1) and the ground node follows at 10.
        master, ground = self._spring_nodes(starter)
        self.assertEqual(master, 9)
        self.assertEqual(ground, 10)
        self.assertIn("   111 111         0", starter)        # ground node fully fixed
        self.assertTrue(any("grounding spring" in w and "master node 9" in w
                            for w in result.warnings))

    def test_ground_spring_prop_block_closes_with_strain_rate_card(self):
        # Regression for starter WARNING 100217 ("card is missing"): the newest
        # SPR_GENE reader cfg ≤ /BEGIN-2022, FORMAT(radioss2018), closes /PROP/TYPE8
        # with a trailing Fsmooth/Fcut (ISRATE, Asrate) card after the 6 DOF blocks.
        # Without it the reader overran the property into the following /PART.
        _, starter = self._convert(FORCE_RB_K, ground_springs=True)
        block = self._prop_type8_block(starter)
        self.assertIn("#  Fsmooth                Fcut", block)
        # 20 data cards = 1 (Mass/Inertia) + 6×3 (DOF) + 1 (Fsmooth/Fcut); block[0]
        # is the header, block[1] the title, the rest comments (#) or data cards.
        data_cards = [ln for ln in block[2:] if not ln.startswith("#")]
        self.assertEqual(len(data_cards), 20)
        # The block's last card — immediately before /PART — is the all-zero
        # strain-rate card (ISRATE=0, Asrate=0): %10d then %20lg.
        self.assertEqual(block[-1], "0".rjust(10) + "0".rjust(20))

    def test_ground_spring_k_is_configurable(self):
        _, starter = self._convert(FORCE_RB_K, ground_springs=True, ground_spring_k=250.0)
        self.assertEqual(starter.count(_SPR_K(250)), 2)
        self.assertEqual(starter.count(_SPR_K(100)), 0)

    def test_single_axis_load_springs_only_that_axis(self):
        # Drop the Z load → only Y is a loaded axis → K on one DOF only.
        deck = FORCE_RB_K.replace("         2         3         1   -1200.0\n", "")
        _, starter = self._convert(deck, ground_springs=True)
        self.assertEqual(starter.count(_SPR_K(100)), 1)

    def test_ground_springs_noop_without_rigid_load(self):
        # TINY_K has no *LOAD_RIGID_BODY → nothing to ground, even with the flag.
        _, starter = self._convert(TINY_K, ground_springs=True)
        self.assertNotIn("/PROP/TYPE8", starter)
        self.assertNotIn("/SPRING/", starter)

    # ── --inter-gapmin ────────────────────────────────────────────────────────
    def test_inter_gapmin_overrides_pulled_interface(self):
        result, starter = self._convert(FORCE_RB_K, inter_gapmin={9: 0.03})
        self.assertIn(_TYPE7_9_GAPMIN03, starter)            # 0.03, not the SST/MST 0.11
        self.assertNotIn(_TYPE7_9_DEFAULT, starter)
        self.assertTrue(any("Gapmin overridden 0.11 -> 0.03" in w
                            for w in result.warnings))

    def test_inter_gapmin_unknown_id_warns_and_no_op(self):
        result, starter = self._convert(FORCE_RB_K, inter_gapmin={777: 0.03})
        self.assertIn(_TYPE7_9_DEFAULT, starter)             # interface 9 unchanged
        self.assertTrue(any("no /INTER/TYPE7/777 was emitted" in w
                            for w in result.warnings))

    # ── --soften-stfac ────────────────────────────────────────────────────────
    def test_soften_stfac_sets_all_interfaces(self):
        result, starter = self._convert(FORCE_RB_K, soften_stfac=0.3)
        self.assertIn(_TYPE7_9_SOFTENED, starter)
        self.assertTrue(any("Stfac=0.3 forced on all /INTER/TYPE7" in w
                            for w in result.warnings))

    def test_soften_stfac_zero_is_explicit(self):
        # An explicit 0.0 differs from None only in that it is *requested*; the
        # emitted Stfac column is the same all-zero default field either way.
        _, starter = self._convert(FORCE_RB_K, soften_stfac=0.0)
        self.assertIn(_TYPE7_9_DEFAULT, starter)

    # ── *CONTACT Card-3 SFS → Stfac (.k-native penalty softening) ─────────────
    def test_kfile_sfs_maps_to_stfac(self):
        # SFS=0.3 on the contact's Card 3 (field 1) → Stfac 0.3, no flag needed.
        deck = FORCE_RB_K.replace(
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0",
            "       0.3       1.0       0.0      0.22       1.0       1.0       1.0       1.0")
        result, starter = self._convert(deck)
        self.assertIn("                 0.3                 0.2                0.11"
                      "                   0                   0", starter)   # Stfac 0.3, Gapmin 0.11
        self.assertTrue(any("SFS=0.3" in w and "Stfac=0.3" in w for w in result.warnings))

    def test_kfile_sfs_unity_leaves_engine_default(self):
        # FORCE_RB_K already carries SFS=1.0 ("no scaling") → Stfac 0 → byte default.
        _, starter = self._convert(FORCE_RB_K)
        self.assertIn(_TYPE7_9_DEFAULT, starter)

    def test_soften_stfac_option_overrides_kfile_sfs(self):
        deck = FORCE_RB_K.replace(
            "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0",
            "       0.3       1.0       0.0      0.22       1.0       1.0       1.0       1.0")
        _, starter = self._convert(deck, soften_stfac=0.5)
        self.assertIn("                 0.5                 0.2                0.11", starter)
        self.assertNotIn("                 0.3                 0.2                0.11", starter)

    # ── all three together = the validated RB_pull recipe ─────────────────────
    def test_full_recipe_combines_all_three(self):
        result, starter = self._convert(
            FORCE_RB_K, ground_springs=True, inter_gapmin={9: 0.03}, soften_stfac=0.3)
        self.assertIn(_TYPE7_9_FULL_RECIPE, starter)         # Stfac 0.3 + Gapmin 0.03
        self.assertIn("/PROP/TYPE8/", starter)
        self.assertEqual(starter.count(_SPR_K(100)), 2)
        master, ground = self._spring_nodes(starter)
        self.assertEqual((master, ground), (9, 10))   # synth master 9, ground 10


class GuiInputParsingTests(unittest.TestCase):
    """The GUI's pure field-parsing helpers (k2rad_gui). These never touch
    tkinter, so the suite runs on a headless box (the import is guarded)."""

    def setUp(self):
        import k2rad_gui  # noqa: E402  (guarded tkinter import; safe headless)
        self.g = k2rad_gui
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kpath = os.path.join(self.tmp.name, "m.k")
        with open(self.kpath, "w") as fh:
            fh.write("*KEYWORD\n*END\n")

    def test_parse_inter_gapmin_pairs(self):
        self.assertEqual(self.g.parse_inter_gapmin(""), {})
        self.assertEqual(self.g.parse_inter_gapmin("90002=0.03"), {90002: 0.03})
        self.assertEqual(self.g.parse_inter_gapmin("9=0.03, 10=0.05  11=0.1"),
                         {9: 0.03, 10: 0.05, 11: 0.1})

    def test_parse_inter_gapmin_rejects_malformed(self):
        for bad in ("9", "abc=0.1", "9=x"):
            with self.assertRaises(ValueError):
                self.g.parse_inter_gapmin(bad)

    def test_build_kwargs_blank_is_standard_conversion(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="100", inter_gapmin_text="", soften_stfac_text="")
        self.assertEqual(kw["input_path"], self.kpath)
        self.assertEqual(kw["units"], ("Mg", "mm", "s"))
        self.assertFalse(kw["ground_springs"])
        self.assertEqual(kw["inter_gapmin"], {})
        self.assertNotIn("soften_stfac", kw)        # None → omitted → default
        self.assertNotIn("ground_spring_k", kw)     # off → not passed
        self.assertNotIn("output_stem", kw)

    def test_build_kwargs_full_recipe(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "out/stem", ("", "cm", ""), ground_springs=True,
            ground_spring_k_text="250", inter_gapmin_text="9=0.03", soften_stfac_text="0.3")
        self.assertEqual(kw["units"], ("Mg", "cm", "s"))     # blanks fall back per slot
        self.assertEqual(kw["output_stem"], "out/stem")
        self.assertTrue(kw["ground_springs"])
        self.assertEqual(kw["ground_spring_k"], 250.0)
        self.assertEqual(kw["inter_gapmin"], {9: 0.03})
        self.assertEqual(kw["soften_stfac"], 0.3)

    def test_build_kwargs_deformable_contact_recipe(self):
        off = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="")
        self.assertFalse(off["deformable_contact_recipe"])          # default off
        on = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
            deformable_contact_recipe=True)
        self.assertTrue(on["deformable_contact_recipe"])

    def test_build_kwargs_write_restart(self):
        common = dict(ground_springs=False, ground_spring_k_text="",
                      inter_gapmin_text="", soften_stfac_text="")
        default = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), **common)
        self.assertFalse(default["write_restart"])                 # default off
        on = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), write_restart=True, **common)
        self.assertTrue(on["write_restart"])

    def test_build_kwargs_blast_ground(self):
        common = dict(ground_springs=False, ground_spring_k_text="",
                      inter_gapmin_text="", soften_stfac_text="")
        default = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), **common)
        self.assertEqual(default["blast_ground"], "auto")          # default
        for mode in ("none", "Y", "-Z"):
            kw = self.g.build_convert_kwargs(
                self.kpath, "", ("Mg", "mm", "s"), blast_ground=mode, **common)
            self.assertEqual(kw["blast_ground"], mode)

    def test_build_kwargs_blast_ground_rejects_bad(self):
        with self.assertRaises(ValueError):
            self.g.build_convert_kwargs(
                self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="", inter_gapmin_text="",
                soften_stfac_text="", blast_ground="up")

    def test_build_kwargs_missing_file_raises(self):
        with self.assertRaises(ValueError):
            self.g.build_convert_kwargs(
                "", "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="")
        with self.assertRaises(ValueError):
            self.g.build_convert_kwargs(
                os.path.join(self.tmp.name, "nope.k"), "", ("Mg", "mm", "s"),
                ground_springs=False, ground_spring_k_text="",
                inter_gapmin_text="", soften_stfac_text="")

    def test_build_kwargs_non_numeric_stfac_raises(self):
        with self.assertRaises(ValueError):
            self.g.build_convert_kwargs(
                self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="soft")

    def test_build_kwargs_passes_tet10_to_tet4(self):
        common = dict(ground_springs=False, ground_spring_k_text="",
                      inter_gapmin_text="", soften_stfac_text="")
        on = self.g.build_convert_kwargs(self.kpath, "", ("Mg", "mm", "s"),
                                         tet10_to_tet4=True, **common)
        off = self.g.build_convert_kwargs(self.kpath, "", ("Mg", "mm", "s"), **common)
        self.assertTrue(on["tet10_to_tet4"])
        self.assertFalse(off["tet10_to_tet4"])

    def test_build_kwargs_fixpoint_count_passes_int(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
            fixpoint_count_text="40")
        self.assertEqual(kw["fixpoint_count"], 40)

    def test_build_kwargs_fixpoint_count_blank_uses_default(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
            fixpoint_count_text="")
        self.assertNotIn("fixpoint_count", kw)        # blank → convert() default (100)

    def test_build_kwargs_non_numeric_fixpoint_raises(self):
        with self.assertRaises(ValueError):
            self.g.build_convert_kwargs(
                self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
                fixpoint_count_text="lots")

    def test_build_kwargs_auto_gapmin_off_omits_factor(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
            auto_gapmin=False, gapmin_factor_text="0.5")
        self.assertFalse(kw["auto_gapmin"])
        self.assertNotIn("gapmin_factor", kw)        # off → factor not passed

    def test_build_kwargs_auto_gapmin_on_passes_factor(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
            auto_gapmin=True, gapmin_factor_text="0.5")
        self.assertTrue(kw["auto_gapmin"])
        self.assertEqual(kw["gapmin_factor"], 0.5)

    def test_build_kwargs_auto_gapmin_blank_factor_uses_default(self):
        kw = self.g.build_convert_kwargs(
            self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
            auto_gapmin=True, gapmin_factor_text="")
        self.assertTrue(kw["auto_gapmin"])
        self.assertNotIn("gapmin_factor", kw)        # blank → convert() default

    def test_build_kwargs_non_numeric_factor_raises(self):
        with self.assertRaises(ValueError):
            self.g.build_convert_kwargs(
                self.kpath, "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="", inter_gapmin_text="", soften_stfac_text="",
                auto_gapmin=True, gapmin_factor_text="huge")


class TetraDowngradeTests(unittest.TestCase):
    """tet10_to_tet4 / --tet10-to-tet4: 10-node quadratic tets become /TETRA4
    with the mid-edge nodes dropped. Off by default (byte-identical /TETRA10)."""

    def _convert(self, deck: str, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _node_ids(starter: str):
        # Node data lines carry the id right-justified in cols 0-10; the block
        # opens with "/NODE" + a "#" column header and ends at the next keyword.
        ids, in_node = set(), False
        for ln in starter.splitlines():
            if ln.startswith("/NODE"):
                in_node = True
                continue
            if in_node:
                if ln.startswith("/"):           # next keyword ends the block
                    in_node = False
                    continue
                head = ln[:10].strip()           # skips "#" comments and blanks
                if head.isdigit():
                    ids.add(int(head))
        return ids

    def test_off_by_default_keeps_tetra10(self):
        _, s = self._convert(TET10_K)
        self.assertIn("/TETRA10/1", s)
        self.assertNotIn("/TETRA4/1", s)
        self.assertEqual(self._node_ids(s), set(range(1, 11)))   # all 10 kept

    def test_downgrade_emits_tetra4_and_drops_midedge(self):
        result, s = self._convert(TET10_K, tet10_to_tet4=True)
        self.assertIn("/TETRA4/1", s)
        self.assertNotIn("/TETRA10", s)
        self.assertEqual(self._node_ids(s), {1, 2, 3, 4})        # only the 4 corners
        self.assertTrue(any("downgraded 1 /TETRA10 to /TETRA4" in w
                            for w in result.warnings))

    def test_downgrade_turns_off_itetra10(self):
        _, s = self._convert(TET10_K, tet10_to_tet4=True)
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/PROP/SOLID/"))
        self.assertEqual(int(lines[i + 3][40:50]), 0)            # Itetra10 off

    def test_midedge_node_only_in_nodeset_is_pruned_and_dropped(self):
        # A mid-edge node referenced ONLY by a *SET_NODE_LIST is removed from the
        # mesh by the downgrade, so it is pruned from the set and dropped — NOT
        # kept as an orphan. Keeping it (the old behaviour) made it carry both the
        # set's BC and the implicit free-node /BCS → OpenRadioss WARNING 312
        # INCOMPATIBLE KINEMATIC CONDITIONS (the elevator symmetry-set bug).
        deck = TET10_K.replace(
            "*CONTROL_TERMINATION",
            "*SET_NODE_LIST_TITLE\nkeep5\n         9\n         5\n*CONTROL_TERMINATION")
        result, s = self._convert(deck, tet10_to_tet4=True)
        ids = self._node_ids(s)
        self.assertEqual(ids, {1, 2, 3, 4})          # mid-edge 5 (and 6) gone
        self.assertTrue(any("node set" in w and "WARNING 312" in w
                            for w in result.warnings))

    def test_midedge_nodeset_pruned_but_genuine_reference_kept(self):
        # The node-set prune must not drop a mid-edge node that a GENUINE non-set
        # entity still needs (e.g. an added mass) — that node is kept (and the
        # free-node guard constrains it harmlessly, with no second BC).
        from k2rad import writer
        st = ConversionState()
        st.options.tet10_to_tet4 = True
        st.nodes = {i: NodeData(float(i), 0.0, 0.0) for i in range(1, 11)}
        st.solid_elems = [SolidElem(1, 1, list(range(1, 11)))]
        st.node_sets = {500: ("sym", [1, 5])}        # corner 1 + mid-edge 5
        st.added_node_masses = {7: 1.0}              # genuine ref on mid-edge 7
        writer._downgrade_tet10_to_tet4(st)
        self.assertEqual(st.node_sets[500][1], [1])  # mid-edge 5 pruned, corner kept
        self.assertNotIn(5, st.nodes)                # dropped (set-only reference)
        self.assertIn(1, st.nodes)                   # corner survives
        self.assertIn(7, st.nodes)                   # genuine reference keeps it
        self.assertNotIn(6, st.nodes)                # plain mid-edge dropped

    def test_no_tet10_reports_unchanged(self):
        result, _ = self._convert(TINY_K, tet10_to_tet4=True)   # shells only
        self.assertTrue(any("no 10-node tetrahedra found" in w
                            for w in result.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Gapmin: suggest /INTER/TYPE7 Gapmin from the minimum node-to-node
# clearance between each surface-to-surface contact's two parts.
# ─────────────────────────────────────────────────────────────────────────────

# Two solid tets in two parts, closest approach 0.5 (node 1 at origin vs node 5
# at x=0.5).  No Card-3 SST/SBST, so the default Gapmin is 0 and --auto-gapmin
# alone drives it.  _ID=9 makes the interface id deterministic.
AUTO_GAPMIN_K = """\
*KEYWORD
*TITLE
auto gapmin solid pair
*NODE
       1             0.0             0.0             0.0
       2            -1.0             0.0             0.0
       3             0.0             1.0             0.0
       4             0.0             0.0             1.0
       5             0.5             0.0             0.0
       6             1.5             0.0             0.0
       7             0.5             1.0             0.0
       8             0.5             0.0             1.0
*ELEMENT_SOLID
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
deformable part
         1         1         1
*PART
rigid pin
         2         1         2
*SECTION_SOLID
         1        10
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*MAT_RIGID
         2   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                              pin_pair
         1         2         3         3         0         0         0         0
       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20
*CONTROL_TERMINATION
       1.0
*END
"""


class PointTriangleTests(unittest.TestCase):
    """The exact point-to-triangle (node-to-segment) distance kernel."""

    A = (0.0, 0.0, 0.0)
    B = (6.0, 0.0, 0.0)
    C = (0.0, 6.0, 0.0)

    def test_point_above_interior_is_perpendicular(self):
        # Projects to (1,1,0), inside the triangle → perpendicular height 1.
        self.assertAlmostEqual(point_triangle_distance((1, 1, 1), self.A, self.B, self.C),
                               1.0, places=9)

    def test_point_above_edge(self):
        # (3,-4,0) projects outside in -y → nearest point (3,0,0) on edge AB.
        self.assertAlmostEqual(point_triangle_distance((3, -4, 0), self.A, self.B, self.C),
                               4.0, places=9)

    def test_point_beyond_vertex(self):
        # (-3,-4,0) is past vertex A → nearest point is A itself, distance 5.
        self.assertAlmostEqual(point_triangle_distance((-3, -4, 0), self.A, self.B, self.C),
                               5.0, places=9)

    def test_node_segment_is_less_than_node_node(self):
        # A node facing a facet's interior: distance to the facet (1.0) is smaller
        # than the distance to any of its vertices (√3) — the over-estimate that
        # made node-to-node useless for Gapmin.
        import math
        verts = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0)]
        faces = [(0, 1, 2)]
        p = (1.0, 1.0, 1.0)
        seg = min_point_to_triangles([p], verts, faces)
        node_node = min(math.dist(p, v) for v in verts)
        self.assertAlmostEqual(seg, 1.0, places=9)
        self.assertAlmostEqual(node_node, math.sqrt(3.0), places=9)
        self.assertLess(seg, node_node)

    def test_empty_inputs_return_none(self):
        self.assertIsNone(min_point_to_triangles([], [(0.0, 0.0, 0.0)], [(0, 0, 0)]))
        self.assertIsNone(min_point_to_triangles([(0.0, 0.0, 0.0)], [], []))

    @unittest.skipUnless(fast_proximity_available(), "needs numpy+scipy")
    def test_fast_matches_bruteforce(self):
        import numpy as np
        from k2rad.gapmin import _min_point_to_triangles_fast
        verts = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0),
                 (2.0, 2.0, 0.0), (1.0, 1.0, 5.0)]
        faces = [(0, 1, 2), (1, 3, 2)]                 # a 2x2 quad in z=0, split
        pts = [(0.5, 0.5, 1.0), (3.0, 3.0, 3.0), (-1.0, -1.0, 0.2), (1.0, 1.0, 0.25)]
        brute = min_point_to_triangles(pts, verts, faces)
        fast = _min_point_to_triangles_fast(
            np.asarray(pts, float), np.asarray(verts, float), np.asarray(faces, np.intp))
        self.assertAlmostEqual(fast, brute, places=9)


class SurfaceFacetTests(unittest.TestCase):
    """MAIN-side surface facet extraction (_surface_triangles)."""

    def test_tet4_has_four_faces(self):
        from k2rad.gapmin import _surface_triangles
        st = ConversionState()
        st.nodes = {1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0),
                    3: NodeData(0, 1, 0), 4: NodeData(0, 0, 1)}
        st.solid_elems = [SolidElem(1, 7, [1, 2, 3, 4])]
        st.parts = {7: PartData(7, "t", 1, 1)}
        _verts, faces = _surface_triangles(st, {7})
        self.assertEqual(len(faces), 4)

    def test_tet10_face_subdivides_into_four_subtriangles(self):
        from k2rad.gapmin import _surface_triangles
        c = [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2)]

        def mid(i, j):
            return tuple((c[i][k] + c[j][k]) / 2.0 for k in range(3))

        coords = {1: c[0], 2: c[1], 3: c[2], 4: c[3], 5: mid(0, 1), 6: mid(1, 2),
                  7: mid(0, 2), 8: mid(1, 3), 9: mid(2, 3), 10: mid(0, 3)}
        st = ConversionState()
        st.nodes = {i: NodeData(*xyz) for i, xyz in coords.items()}
        st.solid_elems = [SolidElem(1, 7, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])]
        st.parts = {7: PartData(7, "t", 1, 1)}
        _verts, faces = _surface_triangles(st, {7})
        self.assertEqual(len(faces), 16)               # 4 boundary faces x 4 sub-tris

    def test_interior_solid_faces_dropped(self):
        from k2rad.gapmin import _surface_triangles
        st = ConversionState()
        st.nodes = {1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0), 3: NodeData(0, 1, 0),
                    4: NodeData(0, 0, 1), 5: NodeData(1, 1, 1)}
        # Two tets sharing face (2,3,4) → that face appears twice and is dropped.
        st.solid_elems = [SolidElem(1, 7, [1, 2, 3, 4]), SolidElem(2, 7, [2, 3, 4, 5])]
        st.parts = {7: PartData(7, "t", 1, 1)}
        _verts, faces = _surface_triangles(st, {7})
        self.assertEqual(len(faces), 6)                # 4+4-2 shared

    def test_shell_quad_is_two_triangles(self):
        from k2rad.gapmin import _surface_triangles
        st = ConversionState()
        st.nodes = {1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0),
                    3: NodeData(1, 1, 0), 4: NodeData(0, 1, 0)}
        st.shell_elems = [ShellElem(1, 7, [1, 2, 3, 4])]
        st.parts = {7: PartData(7, "t", 1, 1)}
        _verts, faces = _surface_triangles(st, {7})
        self.assertEqual(len(faces), 2)


class SuggestGapminNormalizesTet10Tests(unittest.TestCase):
    """--suggest-gapmin (gapmin.analyze_file) must normalize LS-DYNA tet10 apex
    midsides to Radioss order BEFORE measuring, so the clearance/Gapmin it prints
    matches the surface the engine builds and the value --auto-gapmin bakes into
    the converted deck. Regression: the read-only path was left on the un-permuted
    DYNA connectivity and reported a geometrically wrong surface."""

    def _write(self, deck):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t10.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return path

    def test_analyze_file_invokes_normalization(self):
        # Wiring lock: analyze_file must run the same _normalize_tet10_ordering pass
        # convert()/--auto-gapmin runs. It imports the symbol lazily from
        # writer.mesh, so patch it there.
        import k2rad.writer.mesh as _wm
        from k2rad.gapmin import analyze_file
        calls = []
        orig = _wm._normalize_tet10_ordering

        def spy(state):
            calls.append(state)
            return orig(state)

        _wm._normalize_tet10_ordering = spy
        self.addCleanup(setattr, _wm, "_normalize_tet10_ordering", orig)
        analyze_file(self._write(TET10_DYNA_K))
        self.assertEqual(len(calls), 1,
                         "analyze_file did not normalize tet10 ordering before measuring")

    def test_suggest_surface_matches_true_geometry_only_after_normalize(self):
        # Geometric consequence: TET10_DYNA_K and the Radioss-ordered TET10_K are the
        # SAME physical tet (identical corner + midside coordinates, different
        # connectivity order). After normalization the suggest-path surface facets
        # (compared by GEOMETRY, not node id) match the true Radioss surface; on the
        # un-normalized DYNA connectivity they do NOT (apex midsides face off-edge).
        from k2rad.parser import parse_k_file
        from k2rad.handlers import dispatch
        from k2rad.gapmin import _surface_triangles
        from k2rad.writer.mesh import _normalize_tet10_ordering

        def surface(deck, normalize):
            st = ConversionState()
            for blk in parse_k_file(self._write(deck)):
                dispatch(blk, st)
            if normalize:
                _normalize_tet10_ordering(st)
            verts, faces = _surface_triangles(st, {1})
            return {frozenset(tuple(round(c, 6) for c in verts[v]) for v in tri)
                    for tri in faces}

        true_surface = surface(TET10_K, normalize=True)       # already Radioss
        norm_dyna = surface(TET10_DYNA_K, normalize=True)     # the fixed suggest path
        raw_dyna = surface(TET10_DYNA_K, normalize=False)     # the pre-fix behaviour
        self.assertEqual(norm_dyna, true_surface,
                         "normalized DYNA suggest-surface must equal the true surface")
        self.assertNotEqual(raw_dyna, true_surface,
                            "un-normalized DYNA suggest-surface should be wrong (the bug)")


class SuggestGapminTests(unittest.TestCase):
    """suggest_gapmins (node-to-segment) on a directly-built state."""

    def _state(self):
        st = ConversionState()
        st.nodes = {
            1: NodeData(0.0, 0.0, 0.0),
            2: NodeData(-1.0, 0.0, 0.0),
            3: NodeData(0.0, 1.0, 0.0),
            4: NodeData(0.0, 0.0, 1.0),
            5: NodeData(0.5, 0.0, 0.0),
            6: NodeData(1.5, 0.0, 0.0),
            7: NodeData(0.5, 1.0, 0.0),
            8: NodeData(0.5, 0.0, 1.0),
        }
        st.solid_elems = [
            SolidElem(1, 1, [1, 2, 3, 4]),
            SolidElem(2, 2, [5, 6, 7, 8]),
        ]
        st.parts = {1: PartData(1, "deformable", 1, 1),
                    2: PartData(2, "pin", 1, 2)}
        return st

    @unittest.skipUnless(fast_proximity_available(), "needs numpy+scipy")
    def test_surf2surf_suggestion(self):
        st = self._state()
        st.contacts_surf2surf.append(
            ContactAutoSurf2Surf(9, "pin_pair", 1, 3, 2, 3, 0.2, 0.1, 0.0, 1e20))
        sugg, skipped = suggest_gapmins(st, factor=0.8)
        self.assertIn(9, sugg)
        # Closest secondary node (origin) sits opposite vertex node 5 of the main
        # tet, so node-to-segment == 0.5 here.
        self.assertAlmostEqual(sugg[9].min_distance, 0.5, places=9)
        self.assertAlmostEqual(sugg[9].suggested_gapmin, 0.4, places=9)
        self.assertEqual(skipped, {})

    @unittest.skipUnless(fast_proximity_available(), "needs numpy+scipy")
    def test_factor_scales_suggestion(self):
        st = self._state()
        st.contacts_surf2surf.append(
            ContactAutoSurf2Surf(9, "pin_pair", 1, 3, 2, 3, 0.2, 0.1, 0.0, 1e20))
        sugg, _ = suggest_gapmins(st, factor=0.5)
        self.assertAlmostEqual(sugg[9].suggested_gapmin, 0.25, places=9)

    def test_self_contact_is_skipped(self):
        st = self._state()
        # same part on both sides → no two-part clearance
        st.contacts_surf2surf.append(
            ContactAutoSurf2Surf(7, "self", 1, 3, 1, 3, 0.0, 0.0, 0.0, 1e20))
        sugg, skipped = suggest_gapmins(st)
        self.assertNotIn(7, sugg)
        self.assertIn(7, skipped)

    def test_single_surface_contact_is_skipped(self):
        st = self._state()
        st.contacts_single.append(
            ContactAutoSingle(5, "selfsurf", 0, 0, 0.0, 0.0, 0.0, 1e20))
        sugg, skipped = suggest_gapmins(st)
        self.assertNotIn(5, sugg)
        self.assertIn(5, skipped)

    @unittest.skipUnless(fast_proximity_available(), "needs numpy+scipy")
    def test_apply_merges_and_respects_explicit_override(self):
        st = self._state()
        st.contacts_surf2surf.append(
            ContactAutoSurf2Surf(9, "pin_pair", 1, 3, 2, 3, 0.2, 0.1, 0.0, 1e20))
        st.contacts_surf2surf.append(
            ContactAutoSurf2Surf(10, "pin_pair2", 2, 3, 1, 3, 0.2, 0.1, 0.0, 1e20))
        st.options.gapmin_factor = 0.8
        st.options.inter_gapmin = {10: 0.01}        # explicit override on 10
        apply_auto_gapmin(st)
        self.assertAlmostEqual(st.options.inter_gapmin[9], 0.4, places=9)   # auto
        self.assertEqual(st.options.inter_gapmin[10], 0.01)                 # kept


class AutoGapminEndToEndTests(unittest.TestCase):
    """convert(..., auto_gapmin=True) drives the emitted /INTER/TYPE7 Gapmin."""

    def _convert(self, deck: str, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "ag.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **kw)
        return result, Path(result.starter_path).read_text()

    def test_default_off_keeps_gapmin_zero(self):
        # No auto_gapmin and no Card-3 SST/SBST → Gapmin stays 0 (engine default).
        result, starter = self._convert(AUTO_GAPMIN_K)
        self.assertIn("/INTER/TYPE7/9", starter)
        self.assertIn(
            "                   0                 0.2                   0"
            "                   0                   0", starter)
        self.assertFalse(any("auto-gapmin" in w for w in result.warnings))

    @unittest.skipUnless(fast_proximity_available(), "needs numpy+scipy")
    def test_auto_gapmin_sets_gapmin_from_clearance(self):
        result, starter = self._convert(AUTO_GAPMIN_K, auto_gapmin=True)
        self.assertIn("/INTER/TYPE7/9", starter)
        # Stfac=0  Fric=0.2  Gapmin=0.8*0.5=0.4  Tstart=0  Tstop=0
        self.assertIn(
            "                   0                 0.2                 0.4"
            "                   0                   0", starter)
        self.assertTrue(any("auto-gapmin INTER 9" in w and "0.4" in w
                            for w in result.warnings))

    @unittest.skipUnless(fast_proximity_available(), "needs numpy+scipy")
    def test_factor_changes_emitted_gapmin(self):
        _, starter = self._convert(AUTO_GAPMIN_K, auto_gapmin=True, gapmin_factor=0.5)
        # Gapmin = 0.5 * 0.5 = 0.25
        self.assertIn(
            "                   0                 0.2                0.25"
            "                   0                   0", starter)

    def test_explicit_override_wins_over_auto(self):
        # Explicit override is independent of the node-to-segment backend, so this
        # holds with or without numpy+scipy.
        _, starter = self._convert(
            AUTO_GAPMIN_K, auto_gapmin=True, inter_gapmin={9: 0.05})
        self.assertIn(
            "                   0                 0.2                0.05"
            "                   0                   0", starter)


class GapminBackendAbsentTests(unittest.TestCase):
    """When numpy+scipy are absent the node-to-segment path falls back to *no*
    suggestion (there is no node-to-node fallback) and says so clearly."""

    def _state_with_contact(self):
        st = ConversionState()
        st.nodes = {
            1: NodeData(0.0, 0.0, 0.0), 2: NodeData(-1.0, 0.0, 0.0),
            3: NodeData(0.0, 1.0, 0.0), 4: NodeData(0.0, 0.0, 1.0),
            5: NodeData(0.5, 0.0, 0.0), 6: NodeData(1.5, 0.0, 0.0),
            7: NodeData(0.5, 1.0, 0.0), 8: NodeData(0.5, 0.0, 1.0),
        }
        st.solid_elems = [SolidElem(1, 1, [1, 2, 3, 4]), SolidElem(2, 2, [5, 6, 7, 8])]
        st.parts = {1: PartData(1, "deformable", 1, 1), 2: PartData(2, "pin", 1, 2)}
        st.contacts_surf2surf.append(
            ContactAutoSurf2Surf(9, "pin_pair", 1, 3, 2, 3, 0.2, 0.1, 0.0, 1e20))
        return st

    def test_suggest_skips_every_interface_without_backend(self):
        import k2rad.gapmin as gm
        st = self._state_with_contact()
        saved = gm._HAVE_FAST_PROXIMITY
        try:
            gm._HAVE_FAST_PROXIMITY = False
            sugg, skipped = gm.suggest_gapmins(st, 0.8)
        finally:
            gm._HAVE_FAST_PROXIMITY = saved
        self.assertEqual(sugg, {})
        self.assertIn(9, skipped)
        self.assertIn("numpy+scipy", skipped[9])

    def test_apply_auto_gapmin_warns_and_applies_nothing(self):
        import k2rad.gapmin as gm
        st = self._state_with_contact()
        st.options.gapmin_factor = 0.8
        saved = gm._HAVE_FAST_PROXIMITY
        try:
            gm._HAVE_FAST_PROXIMITY = False
            gm.apply_auto_gapmin(st)
        finally:
            gm._HAVE_FAST_PROXIMITY = saved
        self.assertEqual(st.options.inter_gapmin, {})           # nothing applied
        self.assertTrue(any("numpy+scipy" in w for w in st.warnings))


class ConversionLogTests(unittest.TestCase):
    """convert() auto-saves warnings/skips to <stem>_conversion.log."""

    def _convert(self, deck, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "m.k")
        with open(path, "w") as fh:
            fh.write(deck)
        return convert(path, **kw)

    def test_log_written_when_there_are_skips(self):
        # TINY_K carries *SOME_UNSUPPORTED_KEYWORD → a skipped keyword.
        result = self._convert(TINY_K)
        self.assertIsNotNone(result.log_path)
        self.assertTrue(os.path.isfile(result.log_path))
        content = Path(result.log_path).read_text()
        self.assertIn("SOME_UNSUPPORTED_KEYWORD", content)
        self.assertIn("conversion log", content)

    def test_no_log_when_disabled(self):
        result = self._convert(TINY_K, write_log=False)
        self.assertIsNone(result.log_path)


class ProgressCallbackTests(unittest.TestCase):
    """convert(progress=...) reports a non-decreasing 0.0 → 1.0 fraction."""

    def test_progress_runs_monotonically_to_one(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "m.k")
        with open(path, "w") as fh:
            fh.write(TINY_K)
        events = []
        convert(path, progress=lambda fr, lab: events.append((fr, lab)))
        self.assertTrue(events)
        fracs = [fr for fr, _ in events]
        self.assertTrue(all(0.0 <= f <= 1.0 for f in fracs))
        self.assertAlmostEqual(fracs[0], 0.0, places=9)
        self.assertAlmostEqual(fracs[-1], 1.0, places=9)
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(fracs, fracs[1:])),
                        f"progress not non-decreasing: {fracs}")
        self.assertTrue(all(isinstance(lab, str) for _, lab in events))


# A minimal IMPLICIT deck with deformable-vs-deformable surface-to-surface
# contact: two MAT_ELASTIC shell parts, contact 9 between them (sstyp=mstyp=3).
DEFDEF_K = """\
*KEYWORD
*TITLE
deformable-deformable implicit contact
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
deformable part A
         1         1         1
*PART
deformable part B
         2         1         1
*SECTION_SHELL
         1         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                              defdef
         1         2         3         3         0         0         0         0
       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20
       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0
*CONTROL_IMPLICIT_GENERAL
         1      0.01
*CONTROL_TERMINATION
       1.0
*END
"""


class DeformableContactRecipeTests(unittest.TestCase):
    """--deformable-contact-recipe: warn on deformable-vs-deformable contact in
    an implicit deck, and apply the validated stabilization (per-interface
    Inacti=5 + /IMPL/DT/2 L_dtn=50 + /IMPL/QSTAT/DTSCAL=0.05) only when opted in.
    Also pins that L_dtn is NOT forced to 50 by default."""

    def _convert(self, deck, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "dd.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return (result,
                Path(result.starter_path).read_text(),
                Path(result.engine_path).read_text())

    @staticmethod
    def _inter_inacti(starter, inter_id):
        lines = starter.splitlines()
        i = lines.index(f"/INTER/TYPE7/{inter_id}")
        hdr = next(j for j in range(i, len(lines)) if lines[j].startswith("#      IBC"))
        return lines[hdr + 1].split()[1]            # IBC, [Inacti], VisS, ...

    @staticmethod
    def _inter_gapmin(starter, inter_id):
        lines = starter.splitlines()
        i = lines.index(f"/INTER/TYPE7/{inter_id}")
        hdr = next(j for j in range(i, len(lines))
                   if lines[j].startswith("#              Stfac"))
        return lines[hdr + 1].split()[2]            # Stfac, Fric, [Gapmin], ...

    @staticmethod
    def _impl_dt2_l_dtn(engine):
        lines = engine.splitlines()
        i = lines.index("/IMPL/DT/2")
        return lines[i + 1].split()[2]              # It_w  L_arc  [L_dtn] ...

    @staticmethod
    def _qstat_dtscal(engine):
        lines = engine.splitlines()
        i = lines.index("/IMPL/QSTAT/DTSCAL")
        return lines[i + 1].strip()

    def test_defdef_detected_warns_without_recipe(self):
        # Default: detect + warn, but apply NOTHING (no silent stabilization).
        result, starter, engine = self._convert(DEFDEF_K)
        self.assertTrue(any("Deformable-deformable contact detected" in w
                            and "--deformable-contact-recipe" in w
                            for w in result.warnings),
                        f"no recommendation warning in {result.warnings}")
        self.assertEqual(self._inter_inacti(starter, 9), "0")     # Inacti untouched
        self.assertEqual(self._impl_dt2_l_dtn(engine), "0")       # engine default cap
        self.assertEqual(self._qstat_dtscal(engine), "0.1")       # default stabilization

    def test_recipe_applies_inacti_ldtn_qstat(self):
        result, starter, engine = self._convert(DEFDEF_K, deformable_contact_recipe=True)
        self.assertEqual(self._inter_inacti(starter, 9), "5")     # Inacti=5
        self.assertEqual(self._impl_dt2_l_dtn(engine), "50")      # L_dtn=50
        self.assertEqual(self._qstat_dtscal(engine), "0.05")      # tighter QSTAT
        self.assertTrue(any("recipe APPLIED" in w and "[9]" in w
                            for w in result.warnings),
                        f"no 'applied' confirmation in {result.warnings}")

    def test_recipe_protects_gap_from_auto_gapmin(self):
        # The footgun that broke a real re-run: --auto-gapmin shrinks the def-def
        # Gapmin below mesh scale and re-triggers the chatter the recipe fixes.
        # The recipe must keep the mesh-scale SST/MST gap (auto-gapmin skipped),
        # while an explicit --inter-gapmin still wins over both.
        from k2rad.gapmin import fast_proximity_available
        if not fast_proximity_available():
            self.skipTest("auto-gapmin needs numpy+scipy")
        # auto-gapmin ALONE shrinks it to 0.8 (= 0.8 x the 1.0 part-to-part clearance)
        _, starter_auto, _ = self._convert(DEFDEF_K, auto_gapmin=True)
        self.assertEqual(self._inter_gapmin(starter_auto, 9), "0.8")
        # recipe + auto-gapmin: keep the mesh-scale SST/MST Gapmin 0.11, not 0.8
        res, starter_rec, _ = self._convert(
            DEFDEF_K, auto_gapmin=True, deformable_contact_recipe=True)
        self.assertEqual(self._inter_gapmin(starter_rec, 9), "0.11")
        self.assertEqual(self._inter_inacti(starter_rec, 9), "5")
        self.assertTrue(any("auto-gapmin skipped" in w for w in res.warnings),
                        f"no skip note in {res.warnings}")
        # explicit --inter-gapmin still wins over the recipe protection
        _, starter_pin, _ = self._convert(
            DEFDEF_K, auto_gapmin=True, deformable_contact_recipe=True,
            inter_gapmin={9: 0.05})
        self.assertEqual(self._inter_gapmin(starter_pin, 9), "0.05")

    def test_l_dtn_not_defaulted_to_50(self):
        # No deformable-deformable contact, no recipe → L_dtn must be the engine
        # default (0), NOT the old hard-coded 50.
        _, _, engine = self._convert(IMPL_QSTAT_K)
        self.assertEqual(self._impl_dt2_l_dtn(engine), "0")

    def test_recipe_off_is_default_engine(self):
        # Opting the recipe OFF explicitly == not passing it.
        _, _, e_off = self._convert(DEFDEF_K, deformable_contact_recipe=False)
        _, _, e_def = self._convert(DEFDEF_K)
        self.assertEqual(e_off, e_def)

    def test_rigid_backed_contact_not_flagged(self):
        # part B rigid → deformable-vs-RIGID, not deformable-deformable.
        deck = DEFDEF_K.replace(
            "*MAT_ELASTIC\n         1   7.86e-9    210000.0      0.3\n",
            "*MAT_ELASTIC\n         1   7.86e-9    210000.0      0.3\n"
            "*MAT_RIGID\n         2   7.86e-9    210000.0      0.3\n",
        ).replace(
            "deformable part B\n         2         1         1",
            "rigid part B\n         2         1         2",
        )
        result, starter, engine = self._convert(deck, deformable_contact_recipe=True)
        self.assertFalse(any("Deformable-deformable contact" in w
                             for w in result.warnings))
        self.assertEqual(self._inter_inacti(starter, 9), "0")     # recipe leaves it alone
        self.assertEqual(self._impl_dt2_l_dtn(engine), "0")

    def test_explicit_deck_not_flagged(self):
        deck = DEFDEF_K.replace("*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n", "")
        result, _, _ = self._convert(deck)
        self.assertFalse(any("Deformable-deformable contact" in w
                             for w in result.warnings))


class IgnoreToInactiTests(unittest.TestCase):
    """*CONTACT ignore=0 → /INTER/TYPE7 Inacti mapping.

    LS-DYNA ignore=0 (default) MOVES initially penetrating nodes at
    initialization — it never applies a t=0 penetration force. Mapping it to
    Inacti=0 pre-loaded 3.4e10 mJ of elastic contact energy on the
    W13_BlastVehicle z-ground deck (vehicle resting on the ground plane) and
    blew kinetic energy up 5 orders of magnitude over the LS-DYNA reference.
    ignore=0 must map to Inacti=5, EXCEPT the documented implicit
    pre-engagement bootstrap (SST/MST-derived Gapmin > 0 on an implicit deck),
    which needs the t=0 spring force as Newton's stiffness path."""

    _convert = DeformableContactRecipeTests._convert
    _inter_inacti = staticmethod(DeformableContactRecipeTests._inter_inacti)

    # DEFDEF_K card 3 carries MST=0.22 → Gapmin 0.11 (the bootstrap trigger).
    _CARD3_MST = "       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0"
    _CARD3_NOMST = "       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0"

    def test_explicit_ignore0_maps_to_inacti5(self):
        # Explicit deck: ALWAYS Inacti=5, even with an SST/MST Gapmin (there is
        # no Newton bootstrap to protect, only the t=0 force spike to avoid).
        deck = DEFDEF_K.replace("*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n", "")
        result, starter, _ = self._convert(deck)
        self.assertEqual(self._inter_inacti(starter, 9), "5")
        self.assertTrue(any("ignore=0 mapped to Inacti=5" in w
                            for w in result.warnings),
                        f"no ignore=0 mapping warning in {result.warnings}")

    def test_implicit_ignore0_without_gapmin_maps_to_inacti5(self):
        deck = DEFDEF_K.replace(self._CARD3_MST, self._CARD3_NOMST)
        result, starter, _ = self._convert(deck)
        self.assertEqual(self._inter_inacti(starter, 9), "5")

    def test_implicit_ignore0_with_gapmin_keeps_inacti0(self):
        # The validated pre-engagement bootstrap (implicit_hr-anlenkung).
        result, starter, _ = self._convert(DEFDEF_K)
        self.assertEqual(self._inter_inacti(starter, 9), "0")
        self.assertTrue(any("pre-engagement" in w and "Inacti=0 kept" in w
                            for w in result.warnings),
                        f"no bootstrap-kept warning in {result.warnings}")


class ModalEigenvalueTests(unittest.TestCase):
    """*CONTROL_IMPLICIT_EIGENVALUE conversion.

    Default: the stiffness-export recipe the open-source engine can actually
    run — NO /EIG (the engine lacks the eigensolver kernel and segfaults on
    NEIG>0), one /IMPL/LINEAR step with /IMPL/PRINT/STIF writing the assembled
    K for tools/modal_solve.py, plus the inert probe rigid body the implicit
    engine needs, and no inert contact stub (it would pollute the exported K).

    Opt-in (emit_eig / --eig): the classic /EIG request + one-shot eigensolve
    engine for commercial Altair Radioss.
    """

    MODAL_K = IMPL_QSTAT_K.replace(
        "*CONTROL_TERMINATION",
        "*CONTROL_IMPLICIT_EIGENVALUE\n"
        "        10\n"
        "*ELEMENT_MASS\n"
        "       1       2           100.0       0\n"
        "*CONTROL_TERMINATION",
    )

    def _convert(self, deck: str, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "modal.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return (result,
                Path(result.starter_path).read_text(),
                Path(result.engine_path).read_text())

    def test_default_modal_has_no_eig_block(self):
        # The open-source engine cannot solve /EIG, so the default modal deck
        # must not request it (that is the commercial-only --eig path).
        result, starter, _ = self._convert(self.MODAL_K)
        self.assertNotIn("/EIG/", starter)
        # CONTROL_IMPLICIT_EIGENVALUE is handled, not skipped.
        self.assertNotIn("CONTROL_IMPLICIT_EIGENVALUE", result.skipped_keywords)

    def test_default_modal_engine_exports_stiffness(self):
        _, _, engine = self._convert(self.MODAL_K)
        lines = engine.splitlines()
        self.assertIn("/IMPL/LINEAR", lines)
        self.assertIn("/IMPL/PRINT/STIF", lines)
        # /IMPL/PRINT/STIF data line: PRSTIFMAT_TOL PRSTIFMAT_NC PRSTIFMAT_IT.
        self.assertEqual(lines[lines.index("/IMPL/PRINT/STIF") + 1], "0 1 0")
        self.assertIn("/IMPL/SOLVER/2", lines)
        self.assertIn("/IMPL/MUMPS/AUTOCORE", lines)
        # One step covers the whole run: DTINI = endtim (1.0 here).
        self.assertEqual(lines[lines.index("/IMPL/DTINI") + 1], "1")
        # None of the nonlinear time-marching cards belong in a modal run.
        self.assertNotIn("/IMPL/QSTAT", engine)
        self.assertNotIn("/IMPL/NONLIN", engine)
        self.assertNotIn("/IMPL/DT/2", engine)

    def test_default_modal_starter_has_probe_rbody(self):
        # The implicit engine segfaults with no rigid body in the model, and a
        # modal deck must not get the contact stub — so the probe rigid body is
        # REQUIRED for the exported-K run to work.
        result, starter, _ = self._convert(self.MODAL_K)
        self.assertIn("inert_probe_rbody", starter)
        self.assertIn("inert_probe_fix", starter)
        self.assertTrue(any("no rigid body" in w for w in result.warnings))

    def test_modal_skips_contact_stub(self):
        result, starter, _ = self._convert(self.MODAL_K)
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertFalse(any("no contact interface" in w for w in result.warnings))

    def test_emit_eig_restores_eig_block(self):
        result, starter, engine = self._convert(self.MODAL_K, emit_eig=True)
        self.assertIn("/EIG/", starter)
        lines = starter.splitlines()
        eig_idx = next(i for i, ln in enumerate(lines) if ln.startswith("/EIG/"))
        # Card 1: whole structure (grnd_ID 0), free eigenmodes (grnd_bc 0).
        self.assertEqual(lines[eig_idx + 3], "         0         0   000 000         0")
        # Card 2 data: Nmod = neig = 10 in the first 10-col field, Inorm 0 next.
        card2 = lines[eig_idx + 5]
        self.assertEqual(card2[:10].strip(), "10")
        self.assertEqual(card2[10:20].strip(), "0")
        # Commercial /EIG engine: one-shot eigensolve, no K export needed.
        self.assertIn("/IMPL/LINEAR", engine)
        self.assertNotIn("/IMPL/PRINT/STIF", engine)
        self.assertNotIn("/IMPL/QSTAT", engine)

    def test_neig_value_is_carried_through(self):
        deck = self.MODAL_K.replace("        10\n", "         7\n")
        _, starter, _ = self._convert(deck, emit_eig=True)
        lines = starter.splitlines()
        eig_idx = next(i for i, ln in enumerate(lines) if ln.startswith("/EIG/"))
        self.assertEqual(lines[eig_idx + 5][:10].strip(), "7")


class ProbeRigidBodyTests(unittest.TestCase):
    """Inert probe rigid body for implicit decks without any /RBODY.

    The OpenRadioss implicit engine segfaults at solver init (MESSAGE ID 44)
    when the model contains no rigid body — independent of contact. The
    converter injects 3 far-away nodes tied into a fully fixed /RBODY (zero
    effect on results). Validated on the W14 bogie contact-free /IMPL/LINEAR
    static + modal stiffness-export runs.
    """

    def _convert(self, deck: str, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "probe.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return result, Path(result.starter_path).read_text()

    def test_implicit_deck_without_rbody_gets_probe(self):
        result, starter = self._convert(IMPL_QSTAT_K)
        self.assertIn("inert_probe_rbody", starter)
        self.assertTrue(any("MESSAGE ID 44" in w for w in result.warnings))
        # The mesh has nodes 1-4, so the probe claims 5, 6, 7.
        self.assertIn("/RBODY/5", starter)
        lines = starter.splitlines()
        # Master node fully fixed -> the body adds no equations.
        fix_idx = lines.index("inert_probe_fix")
        self.assertIn("111 111", lines[fix_idx + 2])
        # Nonzero Mass and Jxx/Jyy/Jzz (zero rigid-body inertia is ERROR 274).
        rb_idx = lines.index("/RBODY/5")
        self.assertIn("0.001", lines[rb_idx + 3])          # Mass field
        self.assertEqual(lines[rb_idx + 5].split(),
                         ["0.001", "0.001", "0.001"])       # Jxx Jyy Jzz

    def test_probe_and_contact_stub_coexist_for_nonmodal(self):
        # Non-modal implicit deck without contact: the inert self-contact stub
        # is kept (belt-and-braces) ALONGSIDE the probe rigid body.
        result, starter = self._convert(IMPL_QSTAT_K)
        self.assertIn("/INTER/TYPE7/", starter)
        self.assertIn("inert_probe_rbody", starter)

    def test_implicit_deck_with_rbody_gets_no_probe(self):
        deck = IMPL_QSTAT_K.replace(
            "*MAT_ELASTIC\n         1   7.86e-9    210000.0      0.3\n",
            "*MAT_ELASTIC\n         1   7.86e-9    210000.0      0.3\n"
            "*MAT_RIGID\n         2   7.86e-9    210000.0      0.3\n"
            "*PART\nrigid part\n         2         1         2\n"
            "*ELEMENT_SHELL\n       2       2       1       2       3       4\n",
        )
        result, starter = self._convert(deck)
        self.assertNotIn("inert_probe_rbody", starter)
        self.assertFalse(any("MESSAGE ID 44" in w for w in result.warnings))

    def test_explicit_deck_gets_no_probe(self):
        deck = IMPL_QSTAT_K.replace(
            "*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n", "")
        result, starter = self._convert(deck)
        self.assertNotIn("inert_probe_rbody", starter)
        self.assertNotIn("/RBODY", starter)


class AddedMassTests(unittest.TestCase):
    """*ELEMENT_MASS on ordinary (non-rigid) nodes -> /ADMAS/0. Previously these
    were silently dropped: the writer folded added_node_masses only into
    rigid-body masters, so a point mass on a plain mesh node vanished."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "m.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def _with_masses(self, mass_cards: str) -> str:
        # True LS-DYNA columns: eid(I8) nid(I8) mass(F16.0) pid(I8).
        return IMPL_QSTAT_K.replace(
            "*CONTROL_TERMINATION",
            "*ELEMENT_MASS\n" + mass_cards + "*CONTROL_TERMINATION",
        )

    def test_ordinary_node_mass_emits_admas(self):
        deck = self._with_masses("       1       2           100.0       0\n")
        result, starter = self._convert(deck)
        self.assertIn("/ADMAS/0/", starter)
        # The /ADMAS card carries the mass value (100) and a grnod reference.
        m = re.search(r"/ADMAS/0/\d+\n.*\n#\s+MASS\s+grnd_ID\n\s*([\d.eE+-]+)\s+(\d+)",
                      starter)
        self.assertIsNotNone(m)
        self.assertEqual(float(m.group(1)), 100.0)
        self.assertTrue(any("/ADMAS" in w and "ordinary" in w for w in result.warnings))

    def test_equal_masses_grouped_into_one_admas(self):
        deck = self._with_masses(
            "       1       2           100.0       0\n"
            "       2       3           100.0       0\n")
        _, starter = self._convert(deck)
        # Same value -> one /ADMAS/0 over a grnod holding both nodes.
        self.assertEqual(starter.count("/ADMAS/0/"), 1)

    def test_distinct_masses_get_separate_admas(self):
        deck = self._with_masses(
            "       1       2           100.0       0\n"
            "       2       3            50.0       0\n")
        _, starter = self._convert(deck)
        self.assertEqual(starter.count("/ADMAS/0/"), 2)

    def test_f16_mass_column_not_truncated(self):
        # Regression: mass sits right-justified in its F16 column (line chars
        # 16-32). The old uniform 10-wide slicing read chars 20-30 and cut the
        # last two characters off the field, so "            0.05" parsed as
        # "0." -> 0.0 and the mass was silently dropped (integer-valued masses
        # like 50.0 -> "50" survived by luck; the W13 blast deck rescaled to
        # ton/mm/s lost all 356 lumped masses, 2.05 t total).
        deck = self._with_masses(
            "       1       2            0.05       0\n")
        result, starter = self._convert(deck)
        m = re.search(r"/ADMAS/0/\d+\n.*\n#\s+MASS\s+grnd_ID\n\s*([\d.eE+-]+)\s+(\d+)",
                      starter)
        self.assertIsNotNone(m)
        self.assertEqual(float(m.group(1)), 0.05)
        self.assertFalse(any("lumped mass dropped" in w for w in result.warnings))

    def test_zero_parsed_mass_warns(self):
        # A non-blank *ELEMENT_MASS row whose mass parses <= 0 must warn
        # instead of vanishing silently.
        deck = self._with_masses(
            "       1       2             0.0       0\n")
        result, starter = self._convert(deck)
        self.assertNotIn("/ADMAS", starter)
        self.assertTrue(any("lumped mass dropped" in w for w in result.warnings))


class ModalSolveToolTests(unittest.TestCase):
    """tools/modal_solve.py — the offline eigensolver for the modal
    stiffness-export recipe: /IMPL/PRINT/STIF matrix reader, .k lumped-mass
    builder, and the static/eigen solves (numpy+scipy; skipped without them).

    Matrix-format ground truth (validated on the W14 bogie): header "N N NZ";
    "II JJ V" lines holding ONE triangle (II >= JJ) with duplicate (II,JJ)
    entries SUMMED, and II = 6*(USER_node_id-1)+dof, dof 1..6 = TX..RZ.
    """

    # Two nodes (user ids 1 and 3 — a gap, like real free-DOF exports), three
    # translational DOFs + one duplicate + one off-diagonal coupling.
    SYNTH_MATRIX = (
        "         3         3         6\n"
        "         1         1  0.2000000000000000E+01\n"
        "         1         1  0.1000000000000000E+01\n"   # duplicate: sums to 3
        "         2         1  0.5000000000000000E+00\n"   # off-diag: mirrored
        "         2         2  0.4000000000000000E+01\n"
        "        13        13  0.5000000000000000E+01\n"
        "        13         1 -0.1000000000000000E+01\n"
    )

    def setUp(self):
        if not modal_solve._HAVE_SCIPY:
            self.skipTest("modal_solve needs numpy+scipy")

    def _write(self, text: str, name: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_read_stiffness_indices_and_symmetry(self):
        import numpy as np
        stiff = modal_solve.read_stiffness(self._write(self.SYNTH_MATRIX, "m"))
        self.assertEqual(stiff.n_declared, 3)
        self.assertEqual(list(stiff.gids), [1, 2, 13])
        # II = 6*(user_node-1)+dof: 1 -> node 1 TX, 2 -> node 1 TY,
        # 13 = 6*2+1 -> node 3 TX.
        self.assertEqual(list(stiff.user_node), [1, 1, 3])
        self.assertEqual(list(stiff.dof), [1, 2, 1])
        expected = np.array([[3.0, 0.5, -1.0],     # duplicate (1,1) summed
                             [0.5, 4.0, 0.0],      # (2,1) mirrored to (1,2)
                             [-1.0, 0.0, 5.0]])
        np.testing.assert_allclose(stiff.K.toarray(), expected)
        self.assertFalse(stiff.low_precision)      # full-precision mantissas

    def test_read_stiffness_detects_stock_low_precision(self):
        # The stock engine prints FORMAT(I10,I10,E10.2): 2 significant digits.
        text = ("         1         1         1\n"
                "         1         1  0.21E+04\n")
        stiff = modal_solve.read_stiffness(self._write(text, "m"))
        self.assertTrue(stiff.low_precision)

    def test_static_solve_matches_dense(self):
        import numpy as np
        stiff = modal_solve.read_stiffness(self._write(self.SYNTH_MATRIX, "m"))
        u = modal_solve.solve_static(stiff, load_node=1, load_dof=1, force=2.0)
        expected = np.linalg.solve(stiff.K.toarray(), [2.0, 0.0, 0.0])
        np.testing.assert_allclose(u, expected)
        # Loading a DOF that is not in the matrix (constrained) must be an error.
        with self.assertRaises(SystemExit):
            modal_solve.solve_static(stiff, load_node=2, load_dof=1, force=1.0)

    def test_solve_modes_diagonal_oscillators(self):
        import math
        import numpy as np
        # Three uncoupled unit-mass oscillators: K = diag(4, 9, 25) ->
        # omega = 2, 3 for the two lowest modes.
        text = ("         3         3         3\n"
                "         1         1  0.4000000000000000E+01\n"
                "         2         2  0.9000000000000000E+01\n"
                "        13        13  0.2500000000000000E+02\n")
        stiff = modal_solve.read_stiffness(self._write(text, "m"))
        md = modal_solve.build_mass_diagonal(stiff, {1: 1.0, 3: 1.0}, {})
        np.testing.assert_allclose(md, [1.0, 1.0, 1.0])
        freq, phi = modal_solve.solve_modes(stiff, md, n_modes=2)
        np.testing.assert_allclose(freq, [2.0 / (2 * math.pi),
                                          3.0 / (2 * math.pi)])
        self.assertEqual(phi.shape, (3, 2))

    def test_lumped_mass_matches_radioss_lumping(self):
        # TINY_K: one 1x1 mm quad shell, t=1, rho=7.86e-9 -> element mass
        # split evenly over 4 nodes; nodal rotary inertia = the Radioss shell
        # lumping (m/nn)*(A + t^2)/12 (verified == engine MS/IN on W14 bogie).
        path = self._write(TINY_K, "tiny.k")
        mass, inertia = modal_solve.nodal_masses_from_k(path)
        m_elem = 1.0 * 1.0 * 7.86e-9                # A * t * rho
        for nid in (1, 2, 3, 4):
            self.assertAlmostEqual(mass[nid], m_elem / 4, places=15)
            self.assertAlmostEqual(inertia[nid],
                                   (m_elem / 4) * (1.0 + 1.0) / 12, places=18)

    def test_element_mass_added_to_node(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*ELEMENT_MASS\n       1       2           100.0       0\n"
            "*CONTROL_TERMINATION")
        mass, _ = modal_solve.nodal_masses_from_k(self._write(deck, "m.k"))
        m_elem = 7.86e-9
        self.assertAlmostEqual(mass[2], 100.0 + m_elem / 4)
        self.assertAlmostEqual(mass[1], m_elem / 4)

    def test_n_modes_defaults_to_deck_neig(self):
        # Without -n, the solver extracts what the LS-DYNA deck asked for
        # (*CONTROL_IMPLICIT_EIGENVALUE neig); an explicit -n wins; a deck
        # without the card falls back to 12.
        modal = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*CONTROL_IMPLICIT_EIGENVALUE\n        10\n*CONTROL_TERMINATION")
        state = modal_solve.parse_deck(self._write(modal, "m.k"))
        self.assertEqual(modal_solve.default_n_modes(state), 10)
        self.assertEqual(modal_solve.default_n_modes(state, requested=7), 7)
        plain = modal_solve.parse_deck(self._write(TINY_K, "p.k"))
        self.assertEqual(modal_solve.default_n_modes(plain), 12)

    def test_mass_diagonal_places_inertia_on_rotational_dofs(self):
        import numpy as np
        # gid 4 = node 1 RX (rotational) alongside two translational DOFs.
        text = ("         3         3         3\n"
                "         1         1  0.1000000000000000E+01\n"
                "         4         4  0.1000000000000000E+01\n"
                "        13        13  0.1000000000000000E+01\n")
        stiff = modal_solve.read_stiffness(self._write(text, "m"))
        self.assertEqual(list(stiff.dof), [1, 4, 1])
        md = modal_solve.build_mass_diagonal(
            stiff, {1: 2.0, 3: 5.0}, {1: 0.25})
        np.testing.assert_allclose(md, [2.0, 0.25, 5.0])


MODAL_FREQ_K = """\
*KEYWORD
*TITLE
modal frequency-domain deck
*CONTROL_IMPLICIT_EIGENVALUE
        10         0
*CONTROL_IMPLICIT_GENERAL
         1       1.0
*CONTROL_TERMINATION
       1.0
*DATABASE_FREQUENCY_BINARY_D3FTG
         1         3                             0
*DATABASE_FREQUENCY_BINARY_D3PSD
         1         3                             0
       0.1       2.0         5         0         0
*DATABASE_FREQUENCY_BINARY_D3RMS
         1         3                             0
*LOAD_GRAVITY_PART
         1         2         0    0.0098
*MAT_ADD_FATIGUE
         1         2         0       0.0       0.0       0.0         0         0
*DEFINE_CURVE
         1         0       1.0       2.0       0.0       0.0
                 0.1                0.15
                 2.0                0.08
*DEFINE_CURVE
         2         0       1.0       1.0       0.0       0.0
                10.0                 0.8
               100.0                 0.8
    1.0000000000e+07                0.35
    9.9999997952e+10                0.35
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
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   7.85e-6     209.0      0.29      0.56      12.0
       0.0       0.0         0         0       0.0                 0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
*BOUNDARY_SPC_SET
         1         0         1         1         1         1         1         1
*SET_NODE_LIST
         1
         1         2
*END
"""


def _convert_string_deck(deck: str):
    """convert() a deck given as a string; returns (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    # The converter reads/writes UTF-8; be explicit so tests are byte-identical
    # across platforms (Windows' default cp1252 would mangle non-ASCII titles).
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path, encoding="utf-8") as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


class GravityLoadTests(unittest.TestCase):
    """*LOAD_GRAVITY_PART → /GRAV (non-modal) / informational note (modal).

    The R16/R17 manual fixes NO sign for ACCEL, so the convention comes from
    the Radioss dyna-reader, which negates it (``convertloads.cxx:859``): DOF
    1/2/3 loads the part along the NEGATIVE axis and /GRAV carries
    Fscaley = -accel. Sign, column layout, and the /RBODY-main-node routing are
    covered in depth in tests/test_gravity.py.
    """

    NONMODAL = TINY_K.replace(
        "*CONTROL_TERMINATION",
        "*LOAD_GRAVITY_PART\n"
        "         1         3         0      9810\n"
        "*CONTROL_TERMINATION")

    def test_handler_parses_rows(self):
        state = ConversionState()
        for block in parse_k_file(self._write(self.NONMODAL)):
            dispatch(block, state)
        self.assertEqual(len(state.gravity_loads), 1)
        g = state.gravity_loads[0]
        self.assertEqual((g.pid, g.dof, g.lc), (1, 3, 0))
        self.assertAlmostEqual(g.accel, 9810.0)

    def _write(self, text: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_nonmodal_deck_emits_grav(self):
        result, starter = _convert_string_deck(self.NONMODAL)
        self.assertNotIn("LOAD_GRAVITY_PART", result.skipped_keywords)
        self.assertIn("/GRAV/", starter)
        self.assertIn("/GRNOD/PART/", starter)
        # constant gravity: fct_IDT = 0, Fscaley = -accel, direction Z.
        # Asserted by COLUMN, not by substring: the /GRAV data line is 100
        # fixed-width characters (grav.cfg puts ten literal blanks between
        # grnod_ID and Ascale_x), and a value longer than 10 characters used to
        # straddle the Ascale_x/Fscale_Y boundary and lose its sign.
        grav_data = starter.split("/GRAV/")[1].splitlines()[3]
        self.assertEqual(len(grav_data), 100)
        self.assertEqual(grav_data[0:10].strip(), "0")
        self.assertEqual(grav_data[10:20].strip(), "Z")
        self.assertEqual(grav_data[60:80].strip(), "1")       # Ascale_x
        self.assertEqual(grav_data[80:100].strip(), "-9810")  # Fscale_Y

    def test_modal_deck_notes_instead_of_grav(self):
        result, starter = _convert_string_deck(MODAL_FREQ_K)
        self.assertNotIn("LOAD_GRAVITY_PART", result.skipped_keywords)
        self.assertNotIn("/GRAV/", starter)
        self.assertTrue(any("LOAD_GRAVITY_PART" in w and "NOTE" in w
                            for w in result.warnings))
        self.assertIn("intentionally NOT converted", starter)


class FreqDomainKeywordTests(unittest.TestCase):
    """D3PSD/D3RMS/D3FTG + *MAT_ADD_FATIGUE: parsed, never bare-skipped, and
    the conversion points at the offline post-processing chain."""

    def test_cards_parse_into_state(self):
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(MODAL_FREQ_K)
            for block in parse_k_file(path):
                dispatch(block, state)
        self.assertEqual(set(state.db_freq_binary), {"D3PSD", "D3RMS", "D3FTG"})
        psd = state.db_freq_binary["D3PSD"]
        self.assertAlmostEqual(psd.fmin, 0.1)
        self.assertAlmostEqual(psd.fmax, 2.0)
        self.assertEqual(psd.nfreq, 5)
        fat = state.mat_add_fatigue[1]
        self.assertEqual((fat.lcid, fat.ltype, fat.sntype), (2, 0, 0))

    def test_modal_conversion_never_bare_skips_the_five(self):
        result, starter = _convert_string_deck(MODAL_FREQ_K)
        for kw in ("DATABASE_FREQUENCY_BINARY_D3PSD",
                   "DATABASE_FREQUENCY_BINARY_D3RMS",
                   "DATABASE_FREQUENCY_BINARY_D3FTG",
                   "MAT_ADD_FATIGUE", "LOAD_GRAVITY_PART"):
            self.assertNotIn(kw, result.skipped_keywords)
        self.assertTrue(any("modal_random_response.py" in w
                            for w in result.warnings))
        self.assertIn("FREQUENCY-DOMAIN REQUESTS", starter)
        self.assertIn("modal_shapes_export.py", starter)


class ModalCommonTests(unittest.TestCase):
    """tools/modal_common.py — mesh arrays, shape scatter, unit heuristic,
    VTK writer (numpy required; self-skips without it)."""

    def setUp(self):
        if not modal_common._HAVE_NUMPY:
            self.skipTest("modal_common needs numpy")

    def _tiny_state(self):
        state = ConversionState()
        for block in parse_k_file(self._write(TINY_K)):
            dispatch(block, state)
        return state

    def _write(self, text: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def _tiny_modes(self):
        import numpy as np
        # nodes 1 and 3 free (TX + node-3 RX), node 2/4 constrained (absent)
        return modal_common.ModeSet(
            freq=np.array([0.05, 0.1]),
            phi=np.array([[1.0, 0.0], [2.0, -1.0], [9.0, 9.0]]),
            user_node=np.array([1, 3, 3]),
            dof=np.array([1, 1, 4]))

    def test_build_mesh_orders_by_id(self):
        import numpy as np
        mesh = modal_common.build_mesh(self._tiny_state())
        np.testing.assert_array_equal(mesh.node_ids, [1, 2, 3, 4])
        self.assertEqual(mesh.shell_conn, [[0, 1, 2, 3]])
        self.assertEqual(list(mesh.part_ids), [1])
        self.assertEqual(mesh.n_cells, 1)

    def test_shapes_scatter_and_constrained_zero(self):
        mesh = modal_common.build_mesh(self._tiny_state())
        disp = modal_common.shapes_on_mesh(mesh, self._tiny_modes())
        self.assertEqual(disp.shape, (2, 4, 3))
        self.assertAlmostEqual(disp[0, 0, 0], 1.0)   # node 1 TX mode 1
        self.assertAlmostEqual(disp[1, 2, 0], -1.0)  # node 3 TX mode 2
        self.assertEqual(disp[:, 1, :].max(), 0.0)   # node 2 constrained
        # rotations=True picks up the RX row too
        disp6 = modal_common.shapes_on_mesh(mesh, self._tiny_modes(),
                                            rotations=True)
        self.assertAlmostEqual(disp6[0, 2, 3], 9.0)

    def test_shapes_reject_foreign_nodes(self):
        import numpy as np
        mesh = modal_common.build_mesh(self._tiny_state())
        modes = self._tiny_modes()
        modes.user_node = np.array([1, 99, 99])      # not in the mesh
        with self.assertRaises(ValueError):
            modal_common.shapes_on_mesh(mesh, modes)

    def test_freq_scale_from_gravity(self):
        from k2rad.state import GravityLoadPart
        state = self._tiny_state()
        mesh = modal_common.build_mesh(state)
        state.gravity_loads.append(GravityLoadPart(1, 2, 0, 0.0098))
        scale, why = modal_common.detect_freq_scale(state, mesh)
        self.assertEqual(scale, 1000.0)
        state.gravity_loads[:] = [GravityLoadPart(1, 2, 0, 9810.0)]
        scale, _ = modal_common.detect_freq_scale(state, mesh)
        self.assertEqual(scale, 1.0)

    def test_freq_scale_cli_override_wins(self):
        state = self._tiny_state()
        mesh = modal_common.build_mesh(state)
        self.assertEqual(
            modal_common.freq_scale_from_args("ms", state, mesh)[0], 1000.0)
        self.assertEqual(
            modal_common.freq_scale_from_args("s", state, mesh)[0], 1.0)

    def test_parse_mode_list(self):
        self.assertEqual(modal_common.parse_mode_list(None, 3), [1, 2, 3])
        self.assertEqual(modal_common.parse_mode_list("1,3-5", 6), [1, 3, 4, 5])
        with self.assertRaises(ValueError):
            modal_common.parse_mode_list("7", 6)

    def test_default_output_stem(self):
        self.assertEqual(
            Path(modal_common.default_output_stem("a/b/job_modes.npz")).name,
            "job")

    def test_write_vtk_structure(self):
        import numpy as np
        mesh = modal_common.build_mesh(self._tiny_state())
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.vtk")
            modal_common.write_vtk(
                path, mesh,
                point_vectors={"mode_shape": np.ones((4, 3))},
                point_scalars={"mag": np.zeros(4)},
                cell_scalars={"vm": np.array([2.5])})
            lines = open(path).read().splitlines()
        self.assertEqual(lines[0], "# vtk DataFile Version 3.0")
        self.assertIn("POINTS 4 double", lines)
        self.assertIn("CELLS 1 5", lines)
        self.assertIn("CELL_TYPES 1", lines)
        self.assertIn("9", lines[lines.index("CELL_TYPES 1") + 1])  # quad
        self.assertIn("VECTORS mode_shape double", lines)
        self.assertIn("SCALARS vm double 1", lines)


class ModalShapesExportTests(unittest.TestCase):
    """tools/modal_shapes_export.py — VTK always; d3plot when lasso-python is
    installed (self-skips without numpy / lasso)."""

    def setUp(self):
        if not modal_common._HAVE_NUMPY:
            self.skipTest("modal_shapes_export needs numpy")

    def _fixture(self):
        import numpy as np
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        k_path = os.path.join(tmp.name, "job.k")
        with open(k_path, "w") as fh:
            fh.write(TINY_K)
        npz_path = os.path.join(tmp.name, "job_modes.npz")
        np.savez(npz_path,
                 freq=np.array([0.05, 0.08]),
                 phi=np.array([[0.5, 0.25], [0.0, 1.0]]),
                 user_node=np.array([1, 3]),
                 dof=np.array([3, 3]),
                 gids=np.array([3, 15]))
        return tmp.name, npz_path, k_path

    def test_vtk_export_names_and_warp_vector(self):
        tmp, npz_path, k_path = self._fixture()
        rc = modal_shapes_export.main(
            [npz_path, k_path, "--formats", "vtk", "--time-unit", "ms"])
        self.assertEqual(rc, 0)
        vtk_dir = os.path.join(tmp, "job_modes_vtk")
        names = sorted(os.listdir(vtk_dir))
        self.assertEqual(names, ["mode_01_50.0Hz.vtk", "mode_02_80.0Hz.vtk"])
        text = open(os.path.join(vtk_dir, names[0])).read()
        self.assertIn("VECTORS mode_shape double", text)

    def test_vtk_stale_mode_files_removed(self):
        """A re-export with fewer modes must not leave old mode files around
        (a re-solve with the deck's neig default previously left stale
        mode_11/12 files from a 12-mode export)."""
        tmp, npz_path, k_path = self._fixture()
        vtk_dir = os.path.join(tmp, "job_modes_vtk")
        os.makedirs(vtk_dir)
        stale_file = os.path.join(vtk_dir, "mode_99_999.9Hz.vtk")
        with open(stale_file, "w") as fh:
            fh.write("stale")
        stale_anim = os.path.join(vtk_dir, "mode_98_888.8Hz_anim")
        os.makedirs(stale_anim)
        keep = os.path.join(vtk_dir, "notes.txt")
        with open(keep, "w") as fh:
            fh.write("user file - not a mode export")
        rc = modal_shapes_export.main(
            [npz_path, k_path, "--formats", "vtk", "--time-unit", "ms"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(stale_file))
        self.assertFalse(os.path.exists(stale_anim))
        self.assertTrue(os.path.exists(keep))

    def test_animate_writes_series_index(self):
        import json
        tmp, npz_path, k_path = self._fixture()
        rc = modal_shapes_export.main(
            [npz_path, k_path, "--formats", "vtk", "--time-unit", "ms",
             "--modes", "1", "--animate", "4"])
        self.assertEqual(rc, 0)
        anim = os.path.join(tmp, "job_modes_vtk", "mode_01_50.0Hz_anim")
        series = [f for f in os.listdir(anim) if f.endswith(".vtk.series")]
        self.assertEqual(len(series), 1)
        data = json.load(open(os.path.join(anim, series[0])))
        self.assertEqual(len(data["files"]), 4)

    def test_d3plot_roundtrip(self):
        if not modal_shapes_export.have_lasso():
            self.skipTest("lasso-python not installed")
        import numpy as np
        from lasso.dyna import D3plot, ArrayType
        tmp, npz_path, k_path = self._fixture()
        rc = modal_shapes_export.main(
            [npz_path, k_path, "--formats", "d3plot", "--time-unit", "ms"])
        self.assertEqual(rc, 0)
        root = os.path.join(tmp, "job_modes.d3plot")
        self.assertTrue(os.path.isfile(root))
        self.assertTrue(os.path.isfile(root + "01"),
                        "lasso writes the states to <name>01 - keep the family")
        d3 = D3plot(root)
        np.testing.assert_allclose(
            d3.arrays[ArrayType.global_timesteps], [50.0, 80.0], rtol=1e-6)
        shape = (d3.arrays[ArrayType.node_displacement]
                 - d3.arrays[ArrayType.node_coordinates][None])
        # node 1 (index 0) TZ carries phi = 0.5 in mode 1
        self.assertAlmostEqual(shape[0, 0, 2], 0.5, places=5)
        self.assertAlmostEqual(shape[1, 2, 2], 1.0, places=5)

    def test_rewrite_does_not_append_states(self):
        """lasso appends to an existing <name>01 (case-sensitively matched) -
        the export must clean the family so a re-export stays valid."""
        if not modal_shapes_export.have_lasso():
            self.skipTest("lasso-python not installed")
        from lasso.dyna import D3plot, ArrayType
        tmp, npz_path, k_path = self._fixture()
        for _ in range(2):
            rc = modal_shapes_export.main(
                [npz_path, k_path, "--formats", "d3plot", "--time-unit", "ms"])
            self.assertEqual(rc, 0)
        d3 = D3plot(os.path.join(tmp, "job_modes.d3plot"))
        self.assertEqual(len(d3.arrays[ArrayType.global_timesteps]), 2)


class DrillingStiffnessTests(unittest.TestCase):
    """modal_solve.drilling_stiffness — the LS-DYNA-parity drilling-rotation
    augmentation (validated on the W14 bogie vs LS-DYNA R14 eigout/d3eigv:
    factor 1e-3 gives modes 1-8 within 0.5% at MAC 1.000; without it the
    eigensolve grows spurious 63-81 Hz rotation modes)."""

    def setUp(self):
        if not modal_solve._HAVE_SCIPY:
            self.skipTest("modal_solve needs numpy+scipy")

    # unit quad in the XY plane (normal = Z), E=1000, nu=0.3, t=0.1
    def _state(self):
        from k2rad.state import (NodeData, ShellElem, PartData, SectionShell,
                                 MatElastic)
        state = ConversionState()
        state.nodes = {1: NodeData(0, 0, 0), 2: NodeData(1, 0, 0),
                       3: NodeData(1, 1, 0), 4: NodeData(0, 1, 0)}
        state.shell_elems = [ShellElem(1, 1, [1, 2, 3, 4])]
        state.parts = {1: PartData(1, "p", 1, 1)}
        state.sec_shells = {1: SectionShell(1, "s", 2, 3, 0.1)}
        state.mat_elastic = {1: MatElastic(1, "m", 7.8e-9, 1000.0, 0.3)}
        return state

    def _stiff(self, gids):
        """A StiffnessMatrix stub with identity K on the given global ids."""
        import numpy as np
        import scipy.sparse as sp
        gids = np.asarray(gids, dtype=np.int64)
        return modal_solve.StiffnessMatrix(
            n_declared=len(gids), gids=gids,
            K=sp.identity(len(gids), format="csc"),
            user_node=((gids - 1) // 6 + 1).astype(np.int64),
            dof=((gids - 1) % 6 + 1).astype(np.int64),
            low_precision=False)

    def test_block_lands_on_drilling_direction(self):
        # node 1 carries all 3 rotational dofs: II = 6*(1-1)+dof = 4,5,6
        stiff = self._stiff([4, 5, 6])
        kd = modal_solve.drilling_stiffness(self._state(), stiff, 2.0e-3)
        # normal = Z -> only the RZ/RZ entry; kd = f*G*t*A/nn
        G = 0.5 * 1000.0 / 1.3
        expect = 2.0e-3 * G * 0.1 * 1.0 / 4.0
        dense = kd.toarray()
        self.assertAlmostEqual(dense[2, 2], expect, places=10)
        self.assertAlmostEqual(abs(dense).sum(), expect, places=10)

    def test_missing_rotational_dofs_are_skipped(self):
        # node 1 has only RX+RY in K (RZ constrained/absent) -> nothing added
        stiff = self._stiff([4, 5])
        kd = modal_solve.drilling_stiffness(self._state(), stiff, 1.0e-3)
        self.assertEqual(kd.nnz, 0)

    def test_factor_zero_disables(self):
        stiff = self._stiff([4, 5, 6])
        kd = modal_solve.drilling_stiffness(self._state(), stiff, 0.0)
        self.assertEqual(kd.nnz, 0)

    def test_symmetric_for_tilted_shell(self):
        import numpy as np
        from k2rad.state import NodeData
        state = self._state()
        # tilt the quad out of plane so n-hat has all 3 components
        state.nodes[3] = NodeData(1, 1, 0.5)
        state.nodes[4] = NodeData(0, 1, 0.3)
        stiff = self._stiff([4, 5, 6])
        dense = modal_solve.drilling_stiffness(state, stiff, 1e-3).toarray()
        np.testing.assert_allclose(dense, dense.T, atol=1e-15)
        # rank-1 n n^T block: eigvals (0, 0, kd)
        w = np.linalg.eigvalsh(dense)
        self.assertAlmostEqual(w[0], 0.0, places=12)
        self.assertAlmostEqual(w[1], 0.0, places=12)
        self.assertGreater(w[2], 0.0)

    def test_spurious_drilling_mode_is_expelled(self):
        import numpy as np
        import scipy.sparse as sp
        # 1 free node with soft RZ stiffness + small inertia -> junk mode;
        # the drilling term (kd = f*G*t*A/nn ~ 9.6e-3 here) must push it far
        # above the real (translational) mode instead of below it
        stiff = self._stiff([1, 6])       # node 1: TX + RZ
        K = sp.diags([100.0, 1e-6]).tocsc()
        stiff = modal_solve.StiffnessMatrix(
            n_declared=2, gids=stiff.gids, K=K, user_node=stiff.user_node,
            dof=stiff.dof, low_precision=False)
        md = np.array([1.0, 1e-6])        # mass, rotary inertia
        f_raw, _ = modal_solve.solve_modes(stiff, md, 1)
        kd = modal_solve.drilling_stiffness(self._state(), stiff, 1e-3)
        stiff.K = (stiff.K + kd).tocsc()
        f_fix, _ = modal_solve.solve_modes(stiff, md, 1)
        f_tx = math.sqrt(100.0 / 1.0) / (2 * math.pi)
        self.assertLess(f_raw[0], 0.2 * f_tx)          # junk mode below
        self.assertAlmostEqual(f_fix[0], f_tx, places=6)  # real mode first


class ModalRandomResponseTests(unittest.TestCase):
    """tools/modal_random_response.py — the physics is validated against
    closed-form / direct-solve references (numpy required; self-skips)."""

    def setUp(self):
        if not modal_common._HAVE_NUMPY:
            self.skipTest("modal_random_response needs numpy")

    # ── modal machinery vs direct frequency-domain solve ──────────────────
    def test_two_dof_rms_matches_direct_solve(self):
        import numpy as np
        M = np.diag([2.0, 1.0])
        K = np.array([[700.0, -200.0], [-200.0, 200.0]])
        L = np.linalg.cholesky(M)
        Linv = np.linalg.inv(L)
        lam, Y = np.linalg.eigh(Linv @ K @ Linv.T)
        phi = Linv.T @ Y                      # mass-normalized
        f_hz = np.sqrt(lam) / (2 * math.pi)
        zeta, r = 0.03, np.array([1.0, 1.0])
        gamma = phi.T @ M @ r
        grid = np.linspace(0.5, 12.0, 3000)
        sa = np.where((grid > 1.0) & (grid < 10.0), 2.5, 0.0)
        H = modal_random_response.frf_matrix(f_hz, grid, zeta, gamma)
        G = modal_random_response.modal_covariance(H, sa, grid)
        rms = modal_random_response.rms_from_modal(phi.T[:, :, None], G).ravel()
        # direct solve with the modal damping matrix
        C = sum(2 * zeta * math.sqrt(lam[j])
                * np.outer(M @ phi[:, j], M @ phi[:, j]) for j in range(2))
        U = np.array([np.linalg.solve(K - w * w * M + 1j * w * C, -M @ r)
                      for w in 2 * math.pi * grid])
        ref = np.sqrt(modal_random_response._trapz(
            np.abs(U) ** 2 * sa[:, None], grid, axis=0))
        np.testing.assert_allclose(rms, ref, rtol=1e-6)

    # ── shell stress recovery patch tests ─────────────────────────────────
    # TINY_K's MAT_ELASTIC card is not 10-char aligned (its "210000.0" spills
    # into the PR field, so nu parses as 0) — the patch tests need a real
    # Poisson ratio, so they use their own properly aligned deck.
    QUAD_K = TINY_K.replace(
        "*MAT_ELASTIC\n         1   7.86e-9    210000.0      0.3\n",
        "*MAT_ELASTIC\n         1   7.8e-09    1000.0       0.3\n")

    def _quad_model(self):
        state = ConversionState()
        for block in parse_k_file(self._write(self.QUAD_K)):
            dispatch(block, state)
        self.assertAlmostEqual(state.mat_elastic[1].nu, 0.3)
        mesh = modal_common.build_mesh(state)
        model = modal_random_response.build_shell_stress_model(state, mesh)
        return state, mesh, model

    def _write(self, text: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_shell_stress_uniaxial_and_bending(self):
        import numpy as np
        state, mesh, model = self._quad_model()
        E, nu, t = 1000.0, 0.3, 1.0
        D = E / (1 - nu * nu)
        d6 = np.zeros((1, 4, 6))
        d6[0, 1, 0] = d6[0, 2, 0] = 0.01          # u_x = 0.01x
        sig = modal_random_response.shell_modal_stress(model, d6)[0, 0]
        np.testing.assert_allclose(sig[0], [D * 0.01, D * 0.01 * nu, 0.0],
                                   atol=1e-6)
        d6 = np.zeros((1, 4, 6))
        d6[0, 1, 4] = d6[0, 2, 4] = 0.002         # theta_y = c x -> kxx = c
        sig = modal_random_response.shell_modal_stress(model, d6)[0, 0]
        sx = D * (t / 2) * 0.002
        np.testing.assert_allclose(sig[0], [sx, nu * sx, 0.0], atol=1e-9)
        np.testing.assert_allclose(sig[1], [-sx, -nu * sx, 0.0], atol=1e-9)

    def test_shell_stress_rigid_motion_is_stress_free(self):
        import numpy as np
        state, mesh, model = self._quad_model()
        d6 = np.zeros((1, 4, 6))
        rot = 0.01
        for i in range(4):
            x, y = mesh.coords[i, 0], mesh.coords[i, 1]
            d6[0, i, 0] = 5.0 - rot * y
            d6[0, i, 1] = -2.0 + rot * x
            d6[0, i, 5] = rot
        sig = modal_random_response.shell_modal_stress(model, d6)
        self.assertLess(abs(sig).max(), 1e-9)

    # ── S-N data ──────────────────────────────────────────────────────────
    def _fatigue_state(self):
        from k2rad.state import Curve
        state = ConversionState()
        state.curves[2] = Curve(2, "SN", 1.0, 1.0, 0.0, 0.0,
                                [(10.0, 0.8), (100.0, 0.8),
                                 (1.0e7, 0.35), (1.0e11, 0.35)])
        return state

    def test_sn_curve_semilog(self):
        from k2rad.state import MatAddFatigue
        state = self._fatigue_state()
        sn = modal_random_response.sn_function(
            state, MatAddFatigue(1, 2, 0, 0.0, 0.0, 0.0, 0, 0))
        # plateaus resolve conservatively (smallest N)
        self.assertAlmostEqual(float(sn.cycles(0.8)), 10.0, places=4)
        self.assertAlmostEqual(float(sn.cycles(0.35)), 1.0e7, delta=1e3)
        # semi-log midpoint: log10 N linear in S
        mid = float(sn.cycles(0.575))
        self.assertAlmostEqual(math.log10(mid), 4.0, places=2)
        # above the curve: clamp to the strongest damage
        self.assertAlmostEqual(float(sn.cycles(2.0)), 10.0, places=4)
        # below the curve, snlimt=0: the life of the last point
        self.assertAlmostEqual(float(sn.cycles(0.1)), 1.0e11, delta=1e7)

    def test_sn_snlimt_infinity_and_amplitude(self):
        from k2rad.state import MatAddFatigue
        state = self._fatigue_state()
        sn2 = modal_random_response.sn_function(
            state, MatAddFatigue(1, 2, 0, 0.0, 0.0, 0.0, 2, 0))
        self.assertGreater(float(sn2.cycles(0.1)), 1e100)   # infinite life
        # sntype=1: the curve S is an amplitude -> a range of 1.6 = ampl 0.8
        sn3 = modal_random_response.sn_function(
            state, MatAddFatigue(1, 2, 0, 0.0, 0.0, 0.0, 0, 1))
        self.assertAlmostEqual(float(sn3.cycles(1.6)), 10.0, places=4)

    def test_sn_power_law(self):
        from k2rad.state import MatAddFatigue
        sn = modal_random_response.sn_function(
            ConversionState(), MatAddFatigue(1, 0, 0, 1e12, 3.0, 0.0, 0, 0))
        self.assertAlmostEqual(float(sn.cycles(100.0)), 1e6, delta=1)

    # ── damage rates ──────────────────────────────────────────────────────
    def test_narrowband_damage_matches_analytic(self):
        import numpy as np
        from k2rad.state import MatAddFatigue
        grid = np.linspace(5, 15, 3000)
        g = 1.0 / (1 + ((grid - 10) / 0.05) ** 2)
        m = [float(modal_random_response._trapz(grid ** k * g, grid))
             for k in (0, 1, 2, 4)]
        mom = np.array([[m[0], m[1], m[2], m[3]]])
        sn = modal_random_response.sn_function(
            ConversionState(), MatAddFatigue(1, 0, 0, 1e12, 3.0, 0.0, 0, 0))
        d_nb = modal_random_response.damage_rates(mom, sn, "narrowband")[0]
        # analytic Rayleigh damage: nu0 (2 sqrt(2 m0))^b Gamma(1+b/2) / a
        d_ana = (math.sqrt(m[2] / m[0]) * (2 * math.sqrt(2 * m[0])) ** 3
                 * math.gamma(2.5) / 1e12)
        self.assertAlmostEqual(d_nb, d_ana, delta=0.02 * d_ana)
        # Dirlik approaches the narrow-band answer for a narrow-band PSD
        d_dk = modal_random_response.damage_rates(mom, sn, "dirlik")[0]
        self.assertLess(abs(d_dk - d_nb) / d_nb, 0.2)

    def test_zero_stress_means_zero_damage(self):
        import numpy as np
        from k2rad.state import MatAddFatigue
        sn = modal_random_response.sn_function(
            ConversionState(), MatAddFatigue(1, 0, 0, 1e12, 3.0, 0.0, 0, 0))
        mom = np.zeros((3, 4))
        np.testing.assert_array_equal(
            modal_random_response.damage_rates(mom, sn), [0.0, 0.0, 0.0])

    # ── deck-driven configuration ─────────────────────────────────────────
    def test_curve_pick_and_direction_from_deck(self):
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(MODAL_FREQ_K)
            for block in parse_k_file(path):
                dispatch(block, state)
        lcid, _ = modal_random_response.pick_psd_curve(state, None)
        self.assertEqual(lcid, 1)          # curve 2 is S-N data
        d, _ = modal_random_response.excitation_direction(state, "auto")
        self.assertEqual(d, 1)             # deck gravity is Y
        d, _ = modal_random_response.excitation_direction(state, "Z")
        self.assertEqual(d, 2)

    def test_psd_interpolator_units_and_clamping(self):
        import numpy as np
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(MODAL_FREQ_K)
            for block in parse_k_file(path):
                dispatch(block, state)
        # deck units, ms deck: abscissa x1000 -> Hz, ordinate x 1000^3
        sa, band = modal_random_response.psd_interpolator(
            state, 1, 1000.0, "deck", 9810.0, "deck")
        self.assertEqual(band, (100.0, 2000.0))
        # curve pts carry sfo=2: 0.15 * 2 = 0.3 deck units at 100 Hz
        self.assertAlmostEqual(float(sa(np.array([100.0]))[0]), 0.3e9)
        # LS-DYNA convention: end values held constant outside the curve
        self.assertAlmostEqual(float(sa(np.array([10.0]))[0]), 0.3e9)
        # g2hz: ordinate x g^2, no freq_scale^3
        sa_g, _ = modal_random_response.psd_interpolator(
            state, 1, 1000.0, "g2hz", 9810.0, "deck")
        self.assertAlmostEqual(float(sa_g(np.array([100.0]))[0]),
                               0.3 * 9810.0 ** 2)


# ── Blast loading (*LOAD_BLAST_ENHANCED / _SEGMENT_SET / *SET_SEGMENT) ────────

BLAST_K = """\
*KEYWORD
*TITLE
Blast vehicle test
*CONTROL_TERMINATION
     0.006
*NODE
       1       0.0       0.0       0.0
       2       1.0       0.0       0.0
       3       1.0       1.0       0.0
       4       0.0       1.0       0.0
       5       0.0       0.0       1.0
       6       1.0       0.0       1.0
       7       1.0       1.0       1.0
       8       0.0       1.0       1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
target plate
         1         1         1
*PART
ground plane
         2         1         2
*SECTION_SHELL
         1         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_PLASTIC_KINEMATIC
         1    7500.02.10000E11       0.31.200000E91.10000E10       0.0
       0.0       0.0    0.0015       0.0
*MAT_RIGID
         2    7850.02.10000E11       0.3
       0.0         0         0
*DEFINE_CURVE_TITLE
Weight
         1         0       1.0       1.0       0.0       0.0
                 0.0                 9.8
                 1.0                 9.8
*SET_SEGMENT
         1       0.0       0.0       0.0       0.0MECH               0
         1         2         3         4       0.0       0.0       0.0       0.0
*LOAD_BLAST_SEGMENT_SET
         1         1         0       0.0       1.0
*LOAD_BLAST_ENHANCED
         1      50.0       2.5       0.0       5.0       0.0         2         1
       0.0       0.0       0.0       0.0         01.00000E20         0
*LOAD_BODY_Y
         1      -1.0         0       0.0       0.0       0.0         0
*DATABASE_BINARY_BLSTFOR
2.00000E-5         0         0         0         0
*END
"""


class BlastLoadTests(unittest.TestCase):
    """LS-DYNA blast keywords → OpenRadioss /LOAD/PBLAST + /SURF/SEG + /GRAV."""

    def _state(self, deck=BLAST_K):
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            for block in parse_k_file(path):
                dispatch(block, state)
        return state

    def _convert(self, deck=BLAST_K, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path, **kwargs)
            starter = Path(result.starter_path).read_text()
            engine = Path(result.engine_path).read_text()
        return result, starter, engine

    @staticmethod
    def _data_after(starter, prefix):
        """Non-comment, non-keyword lines after the first block whose keyword
        line starts with *prefix* (the title line is included as index 0)."""
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith(prefix))
        out = []
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            out.append(ln)
        return out

    # ── handler-level ────────────────────────────────────────────────
    def test_set_segment_parsed(self):
        state = self._state()
        self.assertIn(1, state.segment_sets)
        self.assertEqual(state.segment_sets[1].segments, [[1, 2, 3, 4]])

    def test_set_segment_triangle_strips_trailing_zero(self):
        deck = BLAST_K.replace(
            "         1         2         3         4       0.0       0.0       0.0       0.0",
            "         1         2         3         0       0.0       0.0       0.0       0.0")
        state = self._state(deck)
        self.assertEqual(state.segment_sets[1].segments, [[1, 2, 3]])

    def test_load_blast_enhanced_parsed(self):
        state = self._state()
        self.assertIn(1, state.blast_sources)
        src = state.blast_sources[1]
        self.assertAlmostEqual(src.m, 50.0)
        self.assertAlmostEqual(src.xbo, 2.5)
        self.assertAlmostEqual(src.zbo, 5.0)
        self.assertEqual(src.unit, 2)
        self.assertEqual(src.blast, 1)
        # UNIT=2 → kg, m, s (the TM5-1300 blast formula is unit-dependent)
        self.assertEqual(state.blast_unit_system, ("kg", "m", "s"))

    def test_load_blast_segment_set_parsed(self):
        state = self._state()
        self.assertEqual(len(state.blast_segment_loads), 1)
        load = state.blast_segment_loads[0]
        self.assertEqual((load.bid, load.ssid), (1, 1))

    # ── emission-level ───────────────────────────────────────────────
    def test_begin_units_from_blast_flag(self):
        # /BEGIN input+work unit lines must both read kg / m / s so the
        # empirical blast pressures come out right.
        _r, starter, _e = self._convert()
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "/BEGIN")
        # /BEGIN, title, version, input-units, work-units
        self.assertEqual(lines[i + 3].split(), ["kg", "m", "s"])
        self.assertEqual(lines[i + 4].split(), ["kg", "m", "s"])

    def test_explicit_units_override_not_clobbered(self):
        # An explicit caller units= must win over the blast-flag default.
        _r, starter, _e = self._convert(units=("g", "cm", "micros"))
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "/BEGIN")
        self.assertEqual(lines[i + 3].split(), ["g", "cm", "micros"])

    def test_explicit_units_mismatch_warns(self):
        # Explicit units that DISAGREE with the deck's *LOAD_BLAST_ENHANCED UNIT
        # flag (here UNIT=2 = kg/m/s) must trigger a loud UNIT MISMATCH warning:
        # mislabelled /BEGIN units make /LOAD/PBLAST rescale its cm/g/µs data
        # wrongly (e.g. an SI-metre deck labelled "mm" reads every distance
        # 1000x too small -> 'Rg too close to the charge' on every segment).
        result, _s, _e = self._convert(units=("Kg", "mm", "s"))
        hits = [w for w in result.warnings if "UNIT MISMATCH" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("kg/m/s", hits[0])

    def test_explicit_units_match_case_insensitive_no_warning(self):
        # Explicit units equal to the UNIT-flag system (any case) are fine.
        result, _s, _e = self._convert(units=("KG", "M", "S"))
        self.assertFalse(any("UNIT MISMATCH" in w for w in result.warnings))

    def test_pblast_card_fields(self):
        _r, starter, _e = self._convert()
        # the /LOAD/PBLAST surface is a /SURF/SEG carrying the segment set
        surf = self._data_after(starter, "/SURF/SEG/")
        self.assertEqual(surf[1].split(), ["1", "1", "2", "3", "4"])  # seg n1..n4
        surf_id = starter.splitlines()[
            next(k for k, ln in enumerate(starter.splitlines())
                 if ln.startswith("/SURF/SEG/"))].rsplit("/", 1)[1]

        data = self._data_after(starter, "/LOAD/PBLAST/")
        card1, card2 = data[1], data[2]        # data[0] is the title line
        self.assertEqual(card1[0:10].strip(), surf_id)     # surf_ID
        self.assertEqual(card1[10:20].strip(), "2")        # Exp_data (surface burst)
        self.assertEqual(card1[30:40].strip(), "100")      # Ndt
        self.assertEqual(card1[40:50].strip(), "2")        # IZ
        self.assertEqual(card1[50:60].strip(), "2")        # Imodel (see below)
        self.assertEqual(len(card1), 100)
        self.assertAlmostEqual(float(card2[0:20]), 2.5)    # Xdet
        self.assertAlmostEqual(float(card2[40:60]), 5.0)   # Zdet
        self.assertAlmostEqual(float(card2[80:100]), 50.0)  # WTNT

    def test_blast_uses_impulse_matched_friedlander_imodel2(self):
        """/LOAD/PBLAST must use Imodel=2, not the b=1.0 classical Friedlander.

        Imodel=2 (the Radioss default) solves the decay coefficient b so the pulse
        reproduces the tabulated Kingery-Bulmash IMPULSE, which is what LS-DYNA's
        *LOAD_BLAST_ENHANCED does. Imodel=1 pins b=1.0, leaving peak pressure and
        positive-phase duration right but the delivered impulse wrong — and wrong
        non-uniformly with standoff. Impulse is what drives panel response, so a
        regression here silently changes every blast result.
        """
        _r, starter, _e = self._convert()
        card1 = self._data_after(starter, "/LOAD/PBLAST/")[1]
        self.assertEqual(card1[50:60].strip(), "2")

    def test_blast_type2_maps_to_free_air_exp_data1(self):
        # LS-DYNA BLAST=2 (spherical free-air) → OpenRadioss Exp_data=1.
        deck = BLAST_K.replace(
            "         1      50.0       2.5       0.0       5.0       0.0         2         1",
            "         1      50.0       2.5       0.0       5.0       0.0         2         2")
        _r, starter, _e = self._convert(deck)
        card1 = self._data_after(starter, "/LOAD/PBLAST/")[1]
        self.assertEqual(card1[10:20].strip(), "1")        # Exp_data free-air

    def test_load_body_becomes_grav(self):
        _r, starter, _e = self._convert()
        self.assertIn("/GRAV/", starter)
        grav = self._data_after(starter, "/GRAV/")
        # funct_IDT(10) DIR(10) skew(10) sensor(10) grnod(10) + 10 blank
        # columns + Ascale_x(20) Fscale_Y(20) — grav.cfg's own layout.
        card = grav[1]
        self.assertEqual(card[10:20].strip(), "Y")         # direction
        self.assertEqual(card[0:10].strip(), "1")          # curve id
        # BLAST_K's *LOAD_BODY_Y carries SF = -1.0, and Fscale_Y = -SF: a
        # POSITIVE LS-DYNA body load acts along the NEGATIVE axis (Manual Vol I
        # R16 p.33-28, "Positive body load acts in the negative direction").
        # k2rad <= PR #88 transcribed SF unnegated and wrote -1 here.
        self.assertEqual(card[80:100].strip(), "1")

    def test_blstfor_not_skipped(self):
        result, _s, _e = self._convert()
        self.assertNotIn("DATABASE_BINARY_BLSTFOR", result.skipped_keywords)
        self.assertTrue(any("*DATABASE_BINARY_BLSTFOR" in w and "/TH/SURF" in w
                            for w in result.warnings))

    def test_blstfor_emits_th_surf_on_blast_surface(self):
        _r, starter, _e = self._convert()
        lines = starter.splitlines()
        # the /TH/SURF must reference the /SURF/SEG the blast load created
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/SURF/SEG/"))
        surf_id = int(lines[i].rsplit("/", 1)[1])
        j = next(k for k, ln in enumerate(lines) if ln.startswith("/TH/SURF/"))
        self.assertEqual(lines[j + 1], "TH_blast_surf")
        var_line = lines[j + 3]                    # j+2 is the comment line
        self.assertEqual(var_line[0:10].strip(), "P")
        self.assertEqual(var_line[10:20].strip(), "A")
        self.assertEqual(int(lines[j + 4].strip()), surf_id)

    def test_blstfor_engine_pext_fext_and_tfile_dt(self):
        _r, _s, engine = self._convert()
        self.assertIn("/ANIM/NODA/PEXT", engine)
        self.assertIn("/ANIM/VECT/FEXT", engine)
        # the *DATABASE_BINARY_BLSTFOR dt reaches /TFILE (sole TH request)
        lines = engine.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "/TFILE")
        self.assertAlmostEqual(float(lines[i + 1]), 2.0e-5)

    def test_no_blstfor_keyword_leaves_output_unchanged(self):
        deck = BLAST_K.replace("*DATABASE_BINARY_BLSTFOR\n"
                               "2.00000E-5         0         0         0"
                               "         0\n", "")
        _r, starter, engine = self._convert(deck)
        self.assertNotIn("/TH/SURF", starter)
        self.assertNotIn("/ANIM/NODA/PEXT", engine)
        self.assertNotIn("/ANIM/VECT/FEXT", engine)

    def test_blstfor_without_blast_load_warns(self):
        deck = BLAST_K.replace(
            "*LOAD_BLAST_SEGMENT_SET\n         1         1         0"
            "       0.0       1.0\n", "")
        result, starter, engine = self._convert(deck)
        self.assertNotIn("/TH/SURF", starter)
        self.assertNotIn("/ANIM/NODA/PEXT", engine)
        self.assertTrue(any("*DATABASE_BINARY_BLSTFOR" in w
                            and "no /LOAD/PBLAST" in w
                            for w in result.warnings))

    def test_explicit_engine_has_no_implicit(self):
        _r, _s, engine = self._convert()
        self.assertIn("/RUN/", engine)
        self.assertNotIn("/IMPL", engine)

    def test_exp_data_mapping_via_writer(self):
        # Direct check of the surface-burst → Exp_data=2 / free-air → 1 map
        # without a full convert, exercising _make_blast_loads.
        from k2rad.writer import _make_blast_loads
        from k2rad.state import (SegmentSet, LoadBlastEnhanced,
                                 LoadBlastSegmentSet)

        def emit(blast):
            st = ConversionState()
            st.segment_sets[1] = SegmentSet(1, "", [[1, 2, 3, 4]])
            st.blast_sources[1] = LoadBlastEnhanced(
                bid=1, m=10.0, xbo=0.0, ybo=0.0, zbo=1.0, tbo=0.0,
                unit=2, blast=blast)
            st.blast_segment_loads.append(LoadBlastSegmentSet(1, 1))
            return "\n".join(_make_blast_loads(st))

        def pblast_card1(text):
            lines = text.splitlines()
            j = next(k for k, ln in enumerate(lines)
                     if ln.startswith("#  surf_ID"))
            return lines[j + 1]

        self.assertIn("/LOAD/PBLAST/", emit(1))
        # surface burst → Exp_data 2, free-air → 1 (col 11-20 of card 1)
        self.assertEqual(pblast_card1(emit(1))[10:20].strip(), "2")
        self.assertEqual(pblast_card1(emit(2))[10:20].strip(), "1")

    # ── ground plane (surface-burst reflecting plane) ────────────────
    @staticmethod
    def _ground_id(starter):
        lines = starter.splitlines()
        j = next(k for k, ln in enumerate(lines) if ln.startswith("#Ground_ID"))
        return int(lines[j + 1].strip())

    @staticmethod
    def _plane_normal(starter):
        """(M1 - M) of the emitted /SURF/PLANE."""
        data = BlastLoadTests._data_after(starter, "/SURF/PLANE/")
        m = [float(x) for x in data[1].split()]
        m1 = [float(x) for x in data[2].split()]
        return tuple(round(a - b, 6) for a, b in zip(m1, m))

    def test_infer_up_axis(self):
        from k2rad.writer import _infer_blast_up_axis
        bbox = ((1.1, 4.1), (0.03, 1.96), (1.87, 8.32))
        # charge below the target in Y → up = +Y
        self.assertEqual(_infer_blast_up_axis((2.5, 0.0, 5.0), bbox), "Y")
        # charge above in Y → up = -Y
        self.assertEqual(_infer_blast_up_axis((2.5, 5.0, 5.0), bbox), "-Y")
        # charge within the target range on every axis → no confident inference
        self.assertIsNone(_infer_blast_up_axis((2.5, 1.0, 5.0), bbox))

    def test_infer_up_axis_enclosed_fallback(self):
        # An under-body charge sits inside the bbox on every axis; the enclosed
        # fallback picks the axis on which the charge is nearest a bounding face.
        from k2rad.writer import _infer_blast_up_axis_enclosed
        bbox = ((1.1, 4.1), (0.03, 1.96), (0.3, 1.96))
        # charge closest to the low Z face (0.5-0.3=0.2) → up = +Z
        self.assertEqual(_infer_blast_up_axis_enclosed((2.5, 1.0, 0.5), bbox), "Z")
        # charge closest to the high X face (4.1-4.0=0.1) → up = -X
        self.assertEqual(_infer_blast_up_axis_enclosed((4.0, 1.0, 1.0), bbox), "-X")

    def test_auto_ground_enclosed_charge_still_makes_plane(self):
        # Charge INSIDE the target bbox on every axis (under-body case): auto must
        # still synthesize a /SURF/PLANE via the enclosed fallback rather than
        # fall through to OpenRadioss's degenerate perpendicular-to-Z default.
        from k2rad.writer import _resolve_blast_ground
        from k2rad.state import (ConversionState, NodeData, SegmentSet,
                                 LoadBlastEnhanced)
        st = ConversionState()
        box = {1: (0, 0, 0), 2: (1, 0, 0), 3: (1, 1, 0), 4: (0, 1, 0),
               5: (0, 0, 1), 6: (1, 0, 1), 7: (1, 1, 1), 8: (0, 1, 1)}
        for nid, (x, y, z) in box.items():
            st.nodes[nid] = NodeData(float(x), float(y), float(z))
        st.segment_sets[1] = SegmentSet(1, "", [[1, 2, 3, 4], [5, 6, 7, 8]])
        # charge just above the bottom face (z=0.1), inside x/y → enclosed → +Z
        src = LoadBlastEnhanced(bid=1, m=10.0, xbo=0.5, ybo=0.5, zbo=0.1,
                                tbo=0.0, unit=2, blast=1)
        gid, lines = _resolve_blast_ground(st, src, st.segment_sets[1])
        self.assertNotEqual(gid, 0)
        self.assertTrue(any(ln.startswith("/SURF/PLANE/") for ln in lines))
        self.assertTrue(any("GUESSED" in w for w in st.warnings))

    def test_auto_ground_plane_synthesized(self):
        # Default "auto" emits a /SURF/PLANE and points the PBLAST Ground_ID at it.
        _r, starter, _e = self._convert()
        self.assertIn("/SURF/PLANE/", starter)
        surf_id = int(starter.splitlines()[
            next(k for k, ln in enumerate(starter.splitlines())
                 if ln.startswith("/SURF/PLANE/"))].rsplit("/", 1)[1])
        self.assertEqual(self._ground_id(starter), surf_id)
        # normal is an axis-aligned unit vector (M→M1)
        nrm = self._plane_normal(starter)
        self.assertEqual(sum(abs(c) for c in nrm), 1.0)

    def test_ground_none_disables_plane(self):
        _r, starter, _e = self._convert(blast_ground="none")
        self.assertNotIn("/SURF/PLANE/", starter)
        self.assertEqual(self._ground_id(starter), 0)

    def test_ground_forced_axis(self):
        _r, starter, _e = self._convert(blast_ground="Y")
        self.assertIn("/SURF/PLANE/", starter)
        self.assertEqual(self._plane_normal(starter), (0.0, 1.0, 0.0))
        self.assertNotEqual(self._ground_id(starter), 0)


# ── Legacy blast (*LOAD_BLAST / *LOAD_BLAST_SEGMENT) ─────────────────────────

_LEGACY_MESH = """\
*KEYWORD
*TITLE
Legacy blast test
*CONTROL_TERMINATION
     0.006
*NODE
       1       0.0       0.0       0.0
       2       1.0       0.0       0.0
       3       1.0       1.0       0.0
       4       0.0       1.0       0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*PART
target
         1         1         1
*SECTION_SHELL
         1         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_PLASTIC_KINEMATIC
         1    7500.02.10000E11       0.31.200000E91.10000E10       0.0
       0.0       0.0    0.0015       0.0
"""

LEGACY_BLAST_K = _LEGACY_MESH + """\
*LOAD_BLAST
      50.0       2.5       0.0       5.0       0.0         2         2
*LOAD_BLAST_SEGMENT_SET
         7         1
*SET_SEGMENT
         1
         1         2         3         4
*END
"""

PERSEG_BLAST_K = _LEGACY_MESH + """\
*LOAD_BLAST_ENHANCED
         1      50.0       2.5       0.0       5.0       0.0         2         1
       0.0       0.0       0.0       0.0         01.00000E20         0
*LOAD_BLAST_SEGMENT
         1         1         2         3         4
*END
"""


class LegacyBlastLoadTests(unittest.TestCase):
    """Legacy CONWEP *LOAD_BLAST + per-segment *LOAD_BLAST_SEGMENT → /LOAD/PBLAST."""

    def _state(self, deck):
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            for block in parse_k_file(path):
                dispatch(block, state)
        return state

    def _convert(self, deck, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path, **kwargs)
            starter = Path(result.starter_path).read_text()
        return result, starter

    # ── legacy *LOAD_BLAST ───────────────────────────────────────────
    def test_legacy_load_blast_creates_source(self):
        state = self._state(LEGACY_BLAST_K)
        self.assertEqual(len(state.blast_sources), 1)
        src = next(iter(state.blast_sources.values()))
        self.assertAlmostEqual(src.m, 50.0)
        self.assertAlmostEqual(src.xbo, 2.5)
        self.assertAlmostEqual(src.zbo, 5.0)
        self.assertEqual(src.unit, 2)
        self.assertEqual(src.blast, 2)                 # ISURF passed through
        self.assertEqual(state.blast_unit_system, ("kg", "m", "s"))

    def test_legacy_blast_segment_set_fallback_emits_pblast(self):
        # The *LOAD_BLAST_SEGMENT_SET names bid=7, which does NOT match the
        # legacy source's synthetic bid; the sole-source fallback still emits.
        _r, starter = self._convert(LEGACY_BLAST_K)
        self.assertIn("/LOAD/PBLAST/", starter)
        self.assertIn("/SURF/SEG/", starter)

    def test_legacy_blast_verify_warning(self):
        result, _s = self._convert(LEGACY_BLAST_K)
        self.assertTrue(any("legacy" in w.lower() and "burst" in w.lower()
                            for w in result.warnings))

    # ── per-segment *LOAD_BLAST_SEGMENT ──────────────────────────────
    def test_per_segment_builds_segment_set(self):
        state = self._state(PERSEG_BLAST_K)
        self.assertEqual(len(state.blast_segment_loads), 1)
        load = state.blast_segment_loads[0]
        self.assertEqual(load.bid, 1)                  # matches _ENHANCED bid
        segset = state.segment_sets[load.ssid]
        self.assertEqual(segset.segments, [[1, 2, 3, 4]])

    def test_per_segment_emits_pblast_surf(self):
        _r, starter = self._convert(PERSEG_BLAST_K)
        self.assertIn("/LOAD/PBLAST/", starter)
        # the /SURF/SEG carries the inline segment nodes 1 2 3 4 (the data line
        # right after the "#   seg_ID ..." column header)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("#   seg_ID"))
        self.assertEqual(lines[i + 1].split()[1:5], ["1", "2", "3", "4"])

    def test_per_segment_triangle_strips_zero(self):
        deck = PERSEG_BLAST_K.replace(
            "         1         1         2         3         4",
            "         1         1         2         3         0")
        state = self._state(deck)
        load = state.blast_segment_loads[0]
        self.assertEqual(state.segment_sets[load.ssid].segments, [[1, 2, 3]])


# ── High explosive + EOS (*MAT_HIGH_EXPLOSIVE_BURN, *EOS_*, *INITIAL_DETONATION) ─

def _fix(*vals):
    """One LS-DYNA fixed-format card: 10-char right-justified fields."""
    return "".join(f"{v:>10}" for v in vals)


def _cube_nodes(base, x0):
    corners = [(x0, 0, 0), (x0 + 1, 0, 0), (x0 + 1, 1, 0), (x0, 1, 0),
               (x0, 0, 1), (x0 + 1, 0, 1), (x0 + 1, 1, 1), (x0, 1, 1)]
    return [f"{base + k:>8}{x:>16}{y:>16}{z:>16}"
            for k, (x, y, z) in enumerate(corners, start=1)]


def _explosive_eos_deck():
    L = ["*KEYWORD", "*TITLE", "JWL EOS test", "*CONTROL_TERMINATION", "     1.0e-3",
         "*NODE"]
    for c in range(2):
        L += _cube_nodes(8 * c, 2 * c)
    L.append("*ELEMENT_SOLID")
    for c in range(2):
        L.append(_fix(c + 1, c + 1) + "".join(f"{8 * c + k:>10}" for k in range(1, 9)))
    L += ["*PART", "explosive", _fix(1, 1, 1),
          "*PART", "air", _fix(2, 1, 2),
          "*SECTION_SOLID", _fix(1, 1),
          "*MAT_HIGH_EXPLOSIVE_BURN", _fix(1, "1.63E-9", "6.93E+6", "2.1E+4", "0.0"),
          "*EOS_JWL", _fix(1, "3.7E+5", "3.2E+3", "4.15", "0.95", "0.30", "7.0E+3", "1.0"),
          "*MAT_NULL", _fix(2, "1.2E-12"),
          "*EOS_LINEAR_POLYNOMIAL",
          _fix(2, "0.0", "0.0", "0.0", "0.0", "0.4", "0.4", "0.0"),
          _fix("2.5E-1", "1.0"),
          "*INITIAL_DETONATION", _fix(1, "0.5", "0.5", "0.5", "0.0"),
          "*END"]
    return "\n".join(L) + "\n"


class ExplosiveEosTests(unittest.TestCase):
    """*MAT_HIGH_EXPLOSIVE_BURN + *EOS_* → /MAT/LAW5, /MAT/LAW6 + /EOS/*,
    *INITIAL_DETONATION → /DFS/DETPOINT."""

    def _state(self, deck):
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            for block in parse_k_file(path):
                dispatch(block, state)
        return state

    def _convert(self, deck, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path, **kw)
            starter = Path(result.starter_path).read_text()
        return result, starter

    @staticmethod
    def _block(starter, header):
        """Data lines of the block whose keyword line starts with *header*."""
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith(header))
        out = []
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            out.append(ln)
        return out

    # ── parse ────────────────────────────────────────────────────────
    def test_high_explosive_and_jwl_parsed(self):
        st = self._state(_explosive_eos_deck())
        self.assertIn(1, st.mat_high_explosive)
        heb = st.mat_high_explosive[1]
        self.assertAlmostEqual(heb.rho, 1.63e-9)
        self.assertAlmostEqual(heb.d, 6.93e6)
        self.assertAlmostEqual(heb.pcj, 2.1e4)
        jwl = st.eos_jwl[1]
        self.assertAlmostEqual(jwl.a, 3.7e5)
        self.assertAlmostEqual(jwl.r1, 4.15)
        self.assertAlmostEqual(jwl.omega, 0.30)

    def test_eos_polynomial_parsed(self):
        st = self._state(_explosive_eos_deck())
        eos = st.eos_cards[2]
        self.assertEqual(eos.kind, "POLYNOMIAL")
        self.assertAlmostEqual(eos.params["c4"], 0.4)
        self.assertAlmostEqual(eos.params["e0"], 0.25)

    def test_detonation_parsed(self):
        st = self._state(_explosive_eos_deck())
        self.assertEqual(len(st.detonations), 1)
        det = st.detonations[0]
        self.assertEqual(det.pid, 1)
        self.assertAlmostEqual(det.x, 0.5)

    # ── emit ─────────────────────────────────────────────────────────
    def test_law5_merges_material_and_jwl(self):
        _r, starter = self._convert(_explosive_eos_deck())
        law5 = self._block(starter, "/MAT/LAW5/1")   # [0]=title
        self.assertAlmostEqual(float(law5[1]), 1.63e-9)          # RHO
        abr = law5[2].split()
        self.assertAlmostEqual(float(abr[0]), 3.7e5)             # A (from EOS_JWL)
        self.assertAlmostEqual(float(abr[4]), 0.30)              # OMEGA
        dcj = law5[3].split()
        self.assertAlmostEqual(float(dcj[0]), 6.93e6)            # D (from MAT_008)
        self.assertAlmostEqual(float(dcj[1]), 2.1e4)             # P_CJ

    def test_mat_null_with_eos_becomes_hyd_visc_not_void(self):
        _r, starter = self._convert(_explosive_eos_deck())
        self.assertIn("/MAT/HYD_VISC/2", starter)
        self.assertNotIn("/MAT/VOID/2", starter)

    def test_bare_mat_null_stays_void(self):
        deck = _explosive_eos_deck().replace(
            "*EOS_LINEAR_POLYNOMIAL\n" +
            _fix(2, "0.0", "0.0", "0.0", "0.0", "0.4", "0.4", "0.0") + "\n" +
            _fix("2.5E-1", "1.0") + "\n", "")
        _r, starter = self._convert(deck)
        self.assertIn("/MAT/VOID/2", starter)
        self.assertNotIn("/MAT/HYD_VISC/2", starter)

    def test_eos_block_id_equals_material_id(self):
        _r, starter = self._convert(_explosive_eos_deck())
        self.assertIn("/EOS/POLYNOMIAL/2", starter)    # id == carrier mat id

    def test_ideal_gas_gamma_and_positive_p0(self):
        deck = _explosive_eos_deck().replace(
            "*INITIAL_DETONATION\n" + _fix(1, "0.5", "0.5", "0.5", "0.0") + "\n",
            "*MAT_NULL\n" + _fix(3, "1.2E-12") + "\n"
            "*EOS_IDEAL_GAS\n" + _fix(3, "717.6", "1004.5", "0.0", "0.0", "288.0", "1.0")
            + "\n")
        _r, starter = self._convert(deck)
        gas = self._block(starter, "/EOS/IDEAL-GAS/3")   # [0]=title
        card = gas[1].split()
        self.assertAlmostEqual(float(card[0]), 1004.5 / 717.6, places=4)   # gamma
        self.assertGreater(float(card[1]), 0.0)                            # P0 > 0

    def test_detpoint_no_title_line_and_matid(self):
        _r, starter = self._convert(_explosive_eos_deck())
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/DFS/DETPOINT/"))
        # next non-comment line is the data card directly (no title line)
        self.assertTrue(lines[i + 1].startswith("#"))
        card = lines[i + 2].split()
        self.assertAlmostEqual(float(card[0]), 0.5)     # Xdet
        self.assertEqual(card[4], "1")                  # mat_ID resolved from part 1

    def test_jwl_without_eos_warns(self):
        deck = _explosive_eos_deck().replace(
            "*EOS_JWL\n" +
            _fix(1, "3.7E+5", "3.2E+3", "4.15", "0.95", "0.30", "7.0E+3", "1.0") + "\n",
            "")
        result, _s = self._convert(deck)
        self.assertTrue(any("companion *EOS_JWL" in w for w in result.warnings))

    def test_detonation_pid0_lights_all_explosives(self):
        deck = _explosive_eos_deck().replace(
            _fix(1, "0.5", "0.5", "0.5", "0.0"),
            _fix(0, "0.5", "0.5", "0.5", "0.0"))
        _r, starter = self._convert(deck)
        self.assertEqual(starter.count("/DFS/DETPOINT/"), 1)   # one explosive


# ── Coupled ALE / FSI (LAW51, TYPE18, EBCS/NRF, Iale) ────────────────────────

def _ale_fsi_deck():
    def i8(v): return f"{v:>8}"
    L = ["*KEYWORD", "*TITLE", "ALE FSI test", "*CONTROL_TERMINATION", "     1.0e-3",
         "*CONTROL_ALE", _fix(1, 1, 2, "0.0", "0.0"), "*NODE"]
    for c in range(2):
        L += _cube_nodes(8 * c, c)                        # two fluid cubes
    L += [f"{17:>8}{2.0:>16}{0.0:>16}{0.0:>16}",          # structure shell nodes
          f"{18:>8}{2.0:>16}{1.0:>16}{0.0:>16}",
          f"{19:>8}{2.0:>16}{1.0:>16}{1.0:>16}",
          f"{20:>8}{2.0:>16}{0.0:>16}{1.0:>16}"]
    L.append("*ELEMENT_SOLID")
    L.append(_fix(1, 11) + "".join(f"{k:>10}" for k in range(1, 9)))
    L.append(_fix(2, 10) + "".join(f"{8 + k:>10}" for k in range(1, 9)))
    L += ["*ELEMENT_SHELL", i8(3) + i8(20) + i8(17) + i8(18) + i8(19) + i8(20)]
    L += ["*PART", "water", _fix(11, 1, 4),
          "*PART", "air", _fix(10, 1, 2),
          "*PART", "structure", _fix(20, 2, 3),
          "*SECTION_SOLID", _fix(1, 11),                  # ELFORM 11 → ALE
          "*SECTION_SHELL", _fix(2, 2, "1.0", 3), _fix("1.0", "1.0", "1.0", "1.0"),
          "*MAT_NULL", _fix(2, "1.2E-12"),
          "*EOS_LINEAR_POLYNOMIAL",
          _fix(2, "0.0", "0.0", "0.0", "0.0", "0.4", "0.4", "0.0"), _fix("2.5E-1", "1.0"),
          "*MAT_NULL", _fix(4, "1.0E-9"),
          "*EOS_GRUNEISEN", _fix(4, "1.48E+6", "1.92", "0.0", "0.0", "0.35", "0.0", "0.0"),
          "*MAT_ELASTIC", _fix(3, "7.85E-9", "2.1E+5", "0.3"),
          "*SET_PART_LIST", _fix(1), _fix(10, 11),
          "*SET_PART_LIST", _fix(2), _fix(20),
          "*SET_SEGMENT", _fix(5), _fix(13, 14, 15, 16),
          "*ALE_MULTI-MATERIAL_GROUP", _fix(11, 1), _fix(10, 1),
          "*CONSTRAINED_LAGRANGE_IN_SOLID",
          _fix(2, 1, 0, 0, 1, 4, 0, 0), _fix("0.0", "0.0", "0.1"),
          "*BOUNDARY_NON_REFLECTING", _fix(5, 0, 0),
          "*END"]
    return "\n".join(L) + "\n"


class AleFsiTests(unittest.TestCase):
    """ALE multimaterial / FSI coupling / non-reflecting boundaries."""

    def _state(self, deck):
        state = ConversionState()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            for block in parse_k_file(path):
                dispatch(block, state)
        return state

    def _convert(self, deck, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path, **kw)
            starter = Path(result.starter_path).read_text()
        return result, starter

    def test_elform11_sets_iale(self):
        st = self._state(_ale_fsi_deck())
        self.assertEqual(st.sec_solids[1].iale, 1)

    def test_prop_solid_iale_and_isolid(self):
        _r, starter = self._convert(_ale_fsi_deck())
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/PROP/SOLID/1"))
        card = lines[i + 3]                       # Isolid Ismstr Iale ...
        self.assertEqual(card[0:10].strip(), "0")     # Isolid 0 (ALE-compatible)
        self.assertEqual(card[20:30].strip(), "1")    # Iale = 1 (field 3)

    def test_ale_mmg_becomes_law51(self):
        _r, starter = self._convert(_ale_fsi_deck())
        self.assertIn("/MAT/LAW51/", starter)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/MAT/LAW51/"))
        # Iform card is 12
        iform = next(lines[k + 1] for k, ln in enumerate(lines[i:], start=i)
                     if ln.strip().startswith("#    Iform"))
        self.assertEqual(iform.strip(), "12")
        # submaterials in AMMG order: water(4) then air(2)
        j = next(k for k, ln in enumerate(lines) if ln.startswith("#    MatID"))
        mids = []
        for ln in lines[j + 1:]:
            if ln.startswith(("#", "/")) or not ln.strip():
                break
            mids.append(ln.split()[0])
        self.assertEqual(mids[:2], ["4", "2"])

    def test_fsi_type18_and_grbric(self):
        _r, starter = self._convert(_ale_fsi_deck())
        self.assertIn("/INTER/TYPE18/", starter)
        self.assertIn("/GRBRIC/PART/", starter)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/INTER/TYPE18/"))
        card2 = lines[i + 5]                       # title, hdr, card1, hdr, card2
        self.assertGreater(float(card2[0:20]), 0.0)     # Stfval > 0
        self.assertGreater(float(card2[40:60]), 0.0)    # Gap > 0

    def test_boundary_non_reflecting_ebcs(self):
        _r, starter = self._convert(_ale_fsi_deck())
        self.assertIn("/EBCS/NRF/", starter)
        # the NRF references a /SURF/SEG built from set-segment 5
        self.assertIn("/SURF/SEG/", starter)

    def test_control_ale_warns(self):
        result, _s = self._convert(_ale_fsi_deck())
        self.assertTrue(any("CONTROL_ALE" in w for w in result.warnings))

    def test_volume_fraction_geometry_recognized(self):
        deck = _ale_fsi_deck().replace(
            "*BOUNDARY_NON_REFLECTING\n" + _fix(5, 0, 0) + "\n",
            "*INITIAL_VOLUME_FRACTION_GEOMETRY\n" + _fix(11, 1, 2, 0) + "\n"
            + _fix(6, 1, 2) + "\n")
        result, _s = self._convert(deck)
        st = self._state(deck)
        self.assertEqual(len(st.volume_fractions), 1)
        self.assertTrue(any("INITIAL_VOLUME_FRACTION" in w for w in result.warnings))


# ── --rigid-cog-master (element-free /RBODY masters for *MAT_RIGID parts) ────

class RigidCogMasterTests(unittest.TestCase):
    """Synthesized element-free CoG masters for *MAT_RIGID parts (ON by default).

    By default each rigid part gets a NEW node at its nodal centroid as the
    /RBODY master, so mesh nodes keep their source coordinates (OpenRadioss
    relocates only the free master to the CoM) and starter WARNINGs 448/1624
    (master connected to an element / removed from secondary set) disappear.
    --no-rigid-cog-master (rigid_cog_master=False) opts out, reusing the part's
    lowest-id mesh node as the master.
    """

    def _convert(self, deck: str, **opts):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path, **opts)
            starter = Path(result.starter_path).read_text()
        return result, starter

    def test_default_master_is_synthesized_element_free(self):
        # ON by default: the master is the synthesized node (max mesh node 8 + 1),
        # not the part's lowest mesh node.
        _r, starter = self._convert(FORCE_RB_K)
        self.assertIn("/RBODY/9", starter)
        self.assertNotIn("/RBODY/5", starter)

    def test_opt_out_reuses_mesh_node_master(self):
        # --no-rigid-cog-master reuses the part's lowest-id mesh node (5).
        _r, starter = self._convert(FORCE_RB_K, rigid_cog_master=False)
        self.assertIn("/RBODY/5", starter)
        self.assertNotIn("/RBODY/9", starter)

    def test_flag_synthesizes_element_free_master(self):
        result, starter = self._convert(FORCE_RB_K, rigid_cog_master=True)
        self.assertIn("/RBODY/9", starter)          # new id above max mesh node 8
        self.assertNotIn("/RBODY/5", starter)
        self.assertTrue(any("rigid-cog-master" in w for w in result.warnings))
        # the synthesized master is written to /NODE at the part's centroid
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/NODE"))
        node9 = next(ln for ln in lines[i:] if ln.split()[:1] == ["9"])
        x, y, z = (float(v) for v in node9.split()[1:4])
        self.assertAlmostEqual((x, y, z)[0], 0.5)   # centroid of nodes 5-8
        self.assertAlmostEqual(y, 0.5)
        self.assertAlmostEqual(z, 1.0)

    def test_flag_mesh_nodes_unchanged(self):
        _r, starter = self._convert(FORCE_RB_K, rigid_cog_master=True)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/NODE"))
        node5 = next(ln for ln in lines[i:] if ln.split()[:1] == ["5"])
        self.assertEqual([float(v) for v in node5.split()[1:4]], [0.0, 0.0, 1.0])

    def test_flag_load_follows_new_master(self):
        # *LOAD_RIGID_BODY pid=2 → the /CLOAD grnod must hold the NEW master.
        _r, starter = self._convert(FORCE_RB_K, rigid_cog_master=True)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip().startswith("rb_indnode_pid2"))
        self.assertEqual(lines[i + 1].split(), ["9"])

    def test_flag_folds_secondary_element_mass(self):
        # *ELEMENT_MASS on a secondary rigid node must land in /RBODY Mass
        # (with a synthesized master it is no longer the master node, and the
        # ordinary-node /ADMAS path skips rigid nodes).
        deck = FORCE_RB_K.replace(
            "*CONTROL_TERMINATION",
            "*ELEMENT_MASS\n       1       6           0.005\n*CONTROL_TERMINATION")
        _r, starter = self._convert(deck, rigid_cog_master=True)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/RBODY/9"))
        card1 = lines[i + 3]                        # node sens skew Ispher Mass...
        self.assertAlmostEqual(float(card1[40:60]), 0.005)
        self.assertNotIn("/ADMAS", starter)


SPCFORC_K = """\
*KEYWORD
*TITLE
SPC reaction output test
*CONTROL_TERMINATION
     0.006
*NODE
       1       0.0       0.0       0.0
       2       1.0       0.0       0.0
       3       1.0       1.0       0.0
       4       0.0       1.0       0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2       1.0         2
      0.05      0.05      0.05      0.05
*MAT_PLASTIC_KINEMATIC
         1    7500.02.10000E11       0.31.200000E91.10000E10       0.0
       0.0       0.0    0.0015       0.0
*SET_NODE_LIST
         1
         1         2
*BOUNDARY_SPC_SET
         1         0         1         1         1         0         0         0
*DATABASE_SPCFORC
2.00000E-5         0         0         1
*END
"""


class DatabaseSpcforcTests(unittest.TestCase):
    """*DATABASE_SPCFORC → /TH/NODE REACX/Y/Z on /BCS nodes + /ANIM/VECT/FREAC."""

    def _convert(self, deck=SPCFORC_K, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path, **kwargs)
            starter = Path(result.starter_path).read_text()
            engine = Path(result.engine_path).read_text()
        return result, starter, engine

    @staticmethod
    def _th_block(starter):
        """(var_line, node_lines) of the TH_spc_reactions /TH/NODE block."""
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip() == "TH_spc_reactions")
        # the title is followed by one or more "#" comment lines, then the
        # fixed-column variable line
        j = i + 1
        while lines[j].startswith("#"):
            j += 1
        var_line = lines[j]
        node_lines = []
        for ln in lines[j + 1:]:
            if ln.startswith(("#", "/")):
                break
            node_lines.append(ln.strip())
        return var_line, node_lines

    def test_spcforc_parsed_and_not_skipped(self):
        result, _s, _e = self._convert()
        self.assertNotIn("DATABASE_SPCFORC", result.skipped_keywords)

    def test_spcforc_emits_th_node_reac(self):
        _r, starter, _e = self._convert()
        var_line, node_lines = self._th_block(starter)
        # fixed 10-char variable fields
        self.assertEqual(var_line[0:10].strip(), "REACX")
        self.assertEqual(var_line[10:20].strip(), "REACY")
        self.assertEqual(var_line[20:30].strip(), "REACZ")
        # translation-only SPC → no moment channels
        self.assertNotIn("REACXX", var_line)
        self.assertEqual(node_lines, ["1", "2"])

    def test_spcforc_rotational_adds_moment_channels(self):
        deck = SPCFORC_K.replace(
            "         1         0         1         1         1         0         0         0",
            "         1         0         1         1         1         1         1         1")
        _r, starter, engine = self._convert(deck)
        var_line, _nodes = self._th_block(starter)
        self.assertEqual(var_line[30:40].strip(), "REACXX")
        self.assertEqual(var_line[50:60].strip(), "REACZZ")
        self.assertIn("/ANIM/VECT/MREAC", engine)

    def test_spcforc_engine_freac_and_tfile_dt(self):
        _r, _s, engine = self._convert()
        self.assertIn("/ANIM/VECT/FREAC", engine)
        # translation-only SPC → no moment reaction vectors
        self.assertNotIn("/ANIM/VECT/MREAC", engine)
        # the *DATABASE_SPCFORC dt reaches /TFILE (no other TH request here)
        lines = engine.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "/TFILE")
        self.assertAlmostEqual(float(lines[i + 1]), 2.0e-5)

    def test_spcforc_without_spc_warns_and_emits_nothing(self):
        deck = SPCFORC_K.replace("*BOUNDARY_SPC_SET\n"
                                 "         1         0         1         1"
                                 "         1         0         0         0\n", "")
        result, starter, engine = self._convert(deck)
        self.assertNotIn("TH_spc_reactions", starter)
        self.assertNotIn("/ANIM/VECT/FREAC", engine)
        self.assertTrue(any("*DATABASE_SPCFORC" in w and "BOUNDARY_SPC" in w
                            for w in result.warnings))

    def test_no_spcforc_keyword_leaves_output_unchanged(self):
        deck = SPCFORC_K.replace("*DATABASE_SPCFORC\n"
                                 "2.00000E-5         0         0         1\n", "")
        _r, starter, engine = self._convert(deck)
        self.assertNotIn("TH_spc_reactions", starter)
        self.assertNotIn("REACX", starter)
        self.assertNotIn("/ANIM/VECT/FREAC", engine)

    # ---- REAC* is an accumulated impulse, not a force -------------------
    # engine/source/output/reaction_forces_th.F:60 sums
    #   FTHREAC(k,n) = FTHREAC(k,n) + IFLAG*MS(n)*A(k,n)*DT12
    # and the only "FTHREAC = ZERO" (resol.F:1901) runs BEFORE the iteration
    # loop head (:2612, back edge :9294), so it is never reset per cycle;
    # thnod.F:178-208 writes it out undivided. A deck converted without saying
    # so invites plotting an impulse against an LS-DYNA spcforc force.

    def test_spcforc_warns_that_reac_is_an_accumulated_impulse(self):
        result, _s, _e = self._convert()
        hits = [w for w in result.warnings
                if "*DATABASE_SPCFORC" in w and "REAC" in w]
        self.assertTrue(hits, "converting *DATABASE_SPCFORC must warn about "
                              f"the REAC* units; warnings were {result.warnings}")
        w = " ".join(hits)
        self.assertIn("impulse", w.lower())
        # tells the user what to actually do with the column
        self.assertIn("d(REAC)/dt", w)
        self.assertIn("reaction_forces_th.F", w)

    def test_spcforc_impulse_note_in_emitted_comment(self):
        _r, starter, _e = self._convert()
        block = _th_comment_lines(starter, "TH_spc_reactions")
        self.assertIn("reaction IMPULSE (REACX/Y/Z)", block)
        self.assertIn("[+ angular impulse (REACXX/YY/ZZ)]", block)
        self.assertIn("REAC* accumulates m*a*dt over the run: "
                      "spcforc force = d(REAC*)/dt", block)
        # the stale claim must not survive anywhere in the deck
        self.assertNotIn("reaction force (REACX/Y/Z)", starter)

    def test_spcforc_comment_lines_do_not_disturb_the_card(self):
        """The extra comment must not shift the fixed-column variable line or
        the node list — the starter reads those by position."""
        _r, starter, _e = self._convert()
        var_line, node_lines = self._th_block(starter)
        self.assertEqual(var_line[0:10].strip(), "REACX")
        self.assertEqual(node_lines, ["1", "2"])
        # every inserted line is a comment, so the starter skips it
        i = starter.index("TH_spc_reactions")
        between = starter[i:starter.index(var_line, i)].splitlines()[1:]
        self.assertTrue(between)
        self.assertTrue(all(ln.startswith("#") for ln in between), between)

    def test_no_spcforc_no_impulse_warning(self):
        deck = SPCFORC_K.replace("*DATABASE_SPCFORC\n"
                                 "2.00000E-5         0         0         1\n", "")
        result, _s, _e = self._convert(deck)
        self.assertFalse([w for w in result.warnings if "d(REAC)/dt" in w])


class DatabaseNcforcTests(unittest.TestCase):
    """*DATABASE_NCFORC → /TH/INTER on every converted contact interface."""

    NCFORC_CARD = ("*DATABASE_NCFORC\n"
                   "2.00000E-5         0         0         1\n")

    def _convert(self, deck):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(deck)
            result = convert(path)
            starter = Path(result.starter_path).read_text()
            engine = Path(result.engine_path).read_text()
        return result, starter, engine

    def _with_ncforc(self, base=None):
        deck = base if base is not None else TRANSDUCER_K
        return deck.replace("*CONTROL_TERMINATION",
                            self.NCFORC_CARD + "*CONTROL_TERMINATION")

    @staticmethod
    def _th_inter_ids(starter):
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/TH/INTER/"))
        ids = []
        # skip title, "#     var1" comment and the DEF variable line
        for ln in lines[i + 4:]:
            if ln.startswith(("#", "/")) or not ln.strip():
                break
            ids.append(int(ln.strip()))
        return ids

    def test_ncforc_not_skipped_and_warn_names_anim_vectors(self):
        result, _s, _e = self._convert(self._with_ncforc())
        self.assertNotIn("DATABASE_NCFORC", result.skipped_keywords)
        self.assertTrue(any("*DATABASE_NCFORC" in w and "/ANIM/VECT/CONT" in w
                            for w in result.warnings))

    def test_ncforc_without_transducer_lists_contact_interface(self):
        # Drop the transducer: /TH/INTER must still appear, listing the
        # /INTER/TYPE25 converted from *CONTACT_AUTOMATIC_SINGLE_SURFACE (explicit).
        base = TRANSDUCER_K.replace(
            "*CONTACT_FORCE_TRANSDUCER_PENALTY\n         2         1         3         3\n",
            "")
        _r, starter, _e = self._convert(self._with_ncforc(base))
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/INTER/TYPE25/"))
        inter_id = int(lines[i].rsplit("/", 1)[1])
        self.assertEqual(self._th_inter_ids(starter), [inter_id])

    def test_ncforc_merges_into_transducer_th_inter(self):
        # With a transducer AND NCFORC there must be exactly ONE /TH/INTER
        # block covering parent, sub-interface and any remaining contacts.
        _r, starter, _e = self._convert(self._with_ncforc())
        self.assertEqual(starter.count("/TH/INTER/"), 1)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/INTER/SUB/"))
        sub_id = int(lines[i].rsplit("/", 1)[1])
        self.assertIn(sub_id, self._th_inter_ids(starter))

    def test_ncforc_tfile_dt(self):
        _r, _s, engine = self._convert(self._with_ncforc())
        lines = engine.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.strip() == "/TFILE")
        self.assertAlmostEqual(float(lines[i + 1]), 2.0e-5)

    def test_ncforc_without_contact_warns(self):
        deck = SPCFORC_K.replace("*DATABASE_SPCFORC", "*DATABASE_NCFORC")
        result, starter, _e = self._convert(deck)
        self.assertNotIn("/TH/INTER", starter)
        self.assertTrue(any("*DATABASE_NCFORC" in w and "no *CONTACT" in w
                            for w in result.warnings))


# A laser-weld miniature: face plate (PID 1, thickness 2.0, mid-plane z=0) and
# a vertical core stripe (PID 2) whose bottom-edge nodes sit at z=1.0 — ON the
# plate's physical surface, i.e. HALF THE PLATE THICKNESS above the plate's
# shell mid-plane (the segment set).  The weld is a *CONTACT_TIED_NODES_TO_
# SURFACE tying node set 111 to segment set 103, exactly like the
# lightweight_panel_dev_tool main-deck templates — the /INTER/TYPE2 dsearch
# must accept that 1.0 offset or the starter unties every weld node.
TIED_WELD_K = """\
*KEYWORD
*TITLE
tied laser weld
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             2.0             0.0             1.0
       6             2.0            10.0             1.0
       7             2.0             0.0            11.0
       8             2.0            10.0            11.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       8       7
*PART
face plate
         1         1         1
*PART
core stripe
         2         2         1
*SECTION_SHELL
         1         2       1.0         3
       2.0
*SECTION_SHELL
         2         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*SET_NODE_LIST_TITLE
weld_bottom_nodes
       111
         5         6
*SET_SEGMENT_TITLE
plate_core_face
       103
         1         2         3         4
*CONTACT_TIED_NODES_TO_SURFACE
       111       103         4         0
       0.0       0.0       0.0       0.0       0.0         0       0.01.0000E+28
       1.0       1.0       0.0       0.0
*CONTROL_TERMINATION
       1.0
*END
"""

# Face-to-face glue: a small patch (PID 2) hovering 1.0 above the plate's
# mid-plane, tied part-to-part (SSTYP=3 / MSTYP=3).
TIED_S2S_K = """\
*KEYWORD
*TITLE
tied surface to surface
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             2.0             2.0             1.0
       6             8.0             2.0             1.0
       7             8.0             8.0             1.0
       8             2.0             8.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
face plate
         1         1         1
*PART
patch
         2         2         1
*SECTION_SHELL
         1         2       1.0         3
       2.0
*SECTION_SHELL
         2         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTACT_TIED_SURFACE_TO_SURFACE
         2         1         3         3
       0.0       0.0       0.0       0.0       0.0         0       0.01.0000E+28
       1.0       1.0       0.0       0.0
*CONTROL_TERMINATION
       1.0
*END
"""


class TiedContactTests(unittest.TestCase):
    """*CONTACT_TIED_* → /INTER/TYPE2 (tied kinematic interface): slave
    *SET_NODE_LIST → /GRNOD, master *SET_SEGMENT → /SURF/SEG, and a dsearch
    measured from the mesh so the shell mid-plane offset (half the plate
    thickness between the tied nodes and the master segments) stays tied."""

    def _convert(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "w.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    @staticmethod
    def _type2_card(starter: str):
        """Parse the first /INTER/TYPE2 data card into (7 ints, dsearch)."""
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/INTER/TYPE2/"))
        data = lines[i + 3]                       # keyword, title, comment, card
        ints = [int(data[c * 10:(c + 1) * 10]) for c in range(7)]
        dsearch = float(data[80:100])
        return ints, dsearch

    def test_tied_nodes_to_surface_is_handled_not_skipped(self):
        result, starter = self._convert(TIED_WELD_K)
        self.assertNotIn("CONTACT_TIED_NODES_TO_SURFACE", result.skipped_keywords)
        self.assertIn("/INTER/TYPE2/", starter)
        self.assertTrue(any("/INTER/TYPE2" in w for w in result.warnings))

    def test_slave_node_set_becomes_grnod(self):
        _, starter = self._convert(TIED_WELD_K)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/NODE/") and "tied" in lines[k + 1])
        self.assertEqual(lines[i + 2].split(), ["5", "6"])

    def test_master_segment_set_becomes_surf_seg(self):
        _, starter = self._convert(TIED_WELD_K)
        self.assertIn("/SURF/SEG/", starter)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/SURF/SEG/"))
        self.assertEqual(lines[i + 1], "plate_core_face")
        # seg_ID n1 n2 n3 n4 — the plate quad, orientation preserved.
        self.assertEqual(lines[i + 3].split(), ["1", "1", "2", "3", "4"])

    def test_card_fields_and_referenced_ids(self):
        _, starter = self._convert(TIED_WELD_K)
        ints, _ = self._type2_card(starter)
        grnod_id, surf_id, ignore, spotflag, level, isearch, idel2 = ints
        self.assertIn(f"/GRNOD/NODE/{grnod_id}", starter)
        self.assertIn(f"/SURF/SEG/{surf_id}", starter)
        self.assertEqual(ignore, 2)      # drop-and-print unfound nodes
        self.assertEqual(spotflag, 28)   # spotweld formulation + auto-penalty
        self.assertEqual(level, 0)
        self.assertEqual(isearch, 2)     # improved closest-segment search
        self.assertEqual(idel2, 0)

    def test_penalty_spotflag_emits_its_extra_card(self):
        """Spotflag 25-28 read one more card than the kinematic ones.

        hm_read_inter_type02.F "Optional Card2 : ILEV = 25,26,27,28" pulls
        Stfac/Visc/Istf off it. Omitting the card would leave the starter
        reading the NEXT keyword line as interface data.
        """
        _, starter = self._convert(TIED_WELD_K)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/INTER/TYPE2/"))
        self.assertIn("Stfac", lines[i + 4])
        self.assertIn("Visc", lines[i + 4])
        card2 = lines[i + 5]
        self.assertAlmostEqual(float(card2[0:20]), 1.0)      # Stfac
        self.assertAlmostEqual(float(card2[20:40]), 0.05)    # Visc (crit. damping)
        self.assertEqual(int(card2[60:70]), 2)               # Istf

    def test_tie_sharing_nodes_with_its_own_main_surface_stays_legal(self):
        """A purely kinematic Spotflag is ERROR 556 on a conformal tie.

        chktyp2.F tags a TYPE2's secondary nodes only when Spotflag is NOT
        25/26/27/28, and every MAIN node carrying that tag raises the hard
        ERROR 556 "MAIN NODE ID=n IS ALSO SECONDARY NODE OF ANOTHER INTERFACE
        TYPE2". Two conformally meshed parts tied together share nodes on their
        common boundary, so those nodes land in both the secondary /GRNOD and
        the main /SURF — which is exactly the deck below.
        """
        _, starter = self._convert(TIED_S2S_K)
        ints, _ = self._type2_card(starter)
        self.assertIn(ints[3], (25, 26, 27, 28))

    def test_dsearch_covers_the_midplane_offset(self):
        # Tied nodes are 1.0 above the master segments (half the plate
        # thickness); the emitted dsearch must accept that gap with margin.
        result, starter = self._convert(TIED_WELD_K)
        _, dsearch = self._type2_card(starter)
        self.assertGreaterEqual(dsearch, 1.0)
        self.assertLessEqual(dsearch, 2.0)          # …but not reach across the mesh
        self.assertTrue(any("dsearch" in w for w in result.warnings))

    def test_id_variant_keeps_id_and_title(self):
        deck = TIED_WELD_K.replace(
            "*CONTACT_TIED_NODES_TO_SURFACE\n",
            "*CONTACT_TIED_NODES_TO_SURFACE_ID\n"
            "         7                                                              weld_a\n")
        _, starter = self._convert(deck)
        self.assertIn("/INTER/TYPE2/7", starter)
        lines = starter.splitlines()
        i = lines.index("/INTER/TYPE2/7")
        self.assertEqual(lines[i + 1], "weld_a")

    def test_offset_variant_is_handled(self):
        deck = TIED_WELD_K.replace("*CONTACT_TIED_NODES_TO_SURFACE\n",
                                   "*CONTACT_TIED_NODES_TO_SURFACE_OFFSET\n")
        result, starter = self._convert(deck)
        self.assertNotIn("CONTACT_TIED_NODES_TO_SURFACE_OFFSET",
                         result.skipped_keywords)
        self.assertIn("/INTER/TYPE2/", starter)

    def test_shell_edge_variant_uses_spotweld_formulation(self):
        deck = TIED_WELD_K.replace("*CONTACT_TIED_NODES_TO_SURFACE\n",
                                   "*CONTACT_TIED_SHELL_EDGE_TO_SURFACE\n")
        result, starter = self._convert(deck)
        self.assertNotIn("CONTACT_TIED_SHELL_EDGE_TO_SURFACE",
                         result.skipped_keywords)
        ints, _ = self._type2_card(starter)
        self.assertEqual(ints[3], 28)    # Spotflag=28 = spotweld + auto-penalty
        # SHELL_EDGE ties rotations in LS-DYNA too — no rotation-semantics note.
        self.assertFalse(any("ROTATIONS" in w for w in result.warnings))

    def test_surface_to_surface_part_sides(self):
        result, starter = self._convert(TIED_S2S_K)
        self.assertNotIn("CONTACT_TIED_SURFACE_TO_SURFACE",
                         result.skipped_keywords)
        ints, dsearch = self._type2_card(starter)
        self.assertEqual(ints[3], 27)    # Spotflag=27: standard tie + auto-penalty
        # Master is a shell part → /SURF/GRSHEL, and the patch hovers 1.0 above.
        self.assertIn("/SURF/GRSHEL/", starter)
        # A whole-PART secondary side is the part's entire node cloud, not a tie
        # surface, so the worst-node measurement is skipped: dsearch=0 hands the
        # decision to the starter's average-main-segment default (Ignore=2).
        self.assertEqual(dsearch, 0.0)
        self.assertTrue(any("whole part/part set" in w for w in result.warnings))

    def test_part_side_dsearch_still_honours_negative_sst(self):
        """A negative Card-3 SST is an EXPLICIT absolute tie distance from the
        deck, so it survives the part-side "leave dsearch to the starter" rule."""
        deck = TIED_S2S_K.replace(
            "       1.0       1.0       0.0       0.0\n",
            "       1.0       1.0      -3.0       0.0\n")
        _, starter = self._convert(deck)
        _, dsearch = self._type2_card(starter)
        self.assertAlmostEqual(dsearch, 3.0)

    def test_negative_sst_floors_dsearch(self):
        # LS-DYNA: a NEGATIVE Card-3 SST is an absolute tie-criterion distance.
        deck = TIED_WELD_K.replace(
            "       1.0       1.0       0.0       0.0\n",
            "       1.0       1.0      -5.0       0.0\n")
        _, starter = self._convert(deck)
        _, dsearch = self._type2_card(starter)
        self.assertAlmostEqual(dsearch, 5.0)

    def test_implicit_tied_only_deck_gets_no_type7_stub(self):
        # The inert all-parts self-contact stub would ENGAGE across the weld
        # gap (tied nodes sit within the TYPE7 thickness-derived gap of their
        # main surface), so a tied deck must not receive it.
        deck = TIED_WELD_K.replace(
            "*CONTROL_TERMINATION",
            "*CONTROL_IMPLICIT_GENERAL\n         1      0.01\n*CONTROL_TERMINATION")
        result, starter = self._convert(deck)
        self.assertIn("/INTER/TYPE2/", starter)
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertFalse(any("no contact interface" in w for w in result.warnings))

    def test_ncforc_lists_tied_interface(self):
        # *DATABASE_NCFORC maps to /TH/INTER over every converted interface —
        # a tied interface counts.
        deck = TIED_WELD_K.replace("*CONTROL_TERMINATION",
                                   "*DATABASE_NCFORC\n      0.01\n*CONTROL_TERMINATION")
        result, starter = self._convert(deck)
        self.assertIn("/TH/INTER", starter)
        self.assertFalse(any("no *CONTACT" in w for w in result.warnings))


MAT187_K = """*KEYWORD
*MAT_187_TITLE
Iglidur I3-PL SAMP (approx - see flags)
$#     mid        ro      bulk      gmod      emod       nue    rbcfac    numint
       187 1.0500E-9       0.0       0.0    1800.0       0.4       0.0         0
$#  lcid-t    lcid-c    lcid-s    lcid-b      nuep    lcid-p         -    incdam
       761       762       763         0       0.4         0                   0
$#  lcid_d    epfail    deprpt  lcid-tri   lcid_lc
         0       0.0       0.0         0         0
$#   miter      mips         -   incfail     iconv      asaf         -      nhsv
         0         0                   0         1         0                   0
$#  lcemod      beta      filt
         0       0.0       0.0
*DEFINE_CURVE
       761         0       1.0       1.0       0.0       0.0         0
                 0.0                35.0
                0.08                41.0
*DEFINE_CURVE
       762         0       1.0       1.0       0.0       0.0         0
                 0.0                39.0
                0.08                46.0
*DEFINE_CURVE
       763         0       1.0       1.0       0.0       0.0         0
                 0.0                20.2
                0.08                23.7
*CONTROL_TERMINATION
       1.0
*END
"""


class Mat187SampTests(unittest.TestCase):
    """*MAT_187 / *MAT_SAMP-1 → /MAT/LAW76 with /TABLE/1 yield curves."""

    def _convert(self, deck: str = MAT187_K):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_mat_187_not_skipped(self):
        result, _ = self._convert()
        self.assertNotIn("MAT_187", result.skipped_keywords)

    def test_emits_law76(self):
        _, starter = self._convert()
        self.assertIn("/MAT/LAW76/187", starter)

    def test_law76_field_values(self):
        _, starter = self._convert()
        block = starter.split("/MAT/LAW76/187", 1)[1]
        # RHO, E, Nu, the three TAB ids, Nu_p and ICONV must all survive.
        self.assertIn("1.050000E-09", block)
        self.assertRegex(block, r"1800\b")
        self.assertIn("       761       762       763", block)
        self.assertIn("0.4", block)  # E's Poisson and Nu_p

    def test_iquad_is_quadratic(self):
        # IFORM IQUAD ICONV — IQUAD=1 (quadratic von Mises yield surface) is
        # Altair's recommended setting for SAMP's asymmetric yield.
        _, starter = self._convert()
        block = starter.split("/MAT/LAW76/187", 1)[1]
        line = block.split("#    IFORM     IQUAD     ICONV", 1)[1].splitlines()[1]
        iform, iquad, iconv = line.split()[:3]
        self.assertEqual(iquad, "1")
        self.assertEqual(iform, "0")

    def test_yield_curves_become_tables_not_functions(self):
        _, starter = self._convert()
        for tid in (761, 762, 763):
            self.assertIn(f"/TABLE/1/{tid}", starter)
            self.assertNotIn(f"/FUNCT/{tid}", starter)

    def test_table_has_dimension_card(self):
        # /TABLE/1 requires the "#dimension" ORDER card (=1) before the points,
        # otherwise the starter raises ERROR 777 (NDIM undefined).
        _, starter = self._convert()
        tbl = starter.split("/TABLE/1/761", 1)[1].splitlines()
        # title, "#dimension", "         1", comment, first data row
        self.assertEqual(tbl[2].strip(), "#dimension")
        self.assertEqual(tbl[3].strip(), "1")

    def test_samp1_named_variant_also_handled(self):
        _, starter = self._convert(MAT187_K.replace("*MAT_187_TITLE",
                                                    "*MAT_SAMP-1_TITLE"))
        self.assertIn("/MAT/LAW76/187", starter)

    CARD1 = ("       187 1.0500E-9       0.0       0.0    1800.0"
             "       0.4       0.0         0")
    CARD2 = ("       761       762       763         0       0.4"
             "         0                   0")
    CARD3 = "         0       0.0       0.0         0         0"
    CARD4 = ("         0         0                   0         1"
             "         0                   0")

    def _mutated(self, *pairs):
        # guard against silent no-op replaces: a fixture tweak that stops the
        # old-string matching would otherwise leave the base deck in place and
        # let the mutation test pass vacuously
        deck = MAT187_K
        for old, new in pairs:
            self.assertIn(old, deck)
            deck = deck.replace(old, new)
        return deck

    def test_fused_mid_ro_parses_fixed_width(self):
        # Real-world card where RO fills its whole 10-char field and fuses
        # with MID ("1871.05000E-9") — a free split shifted every value and
        # emitted /MAT/LAW76/0 with zero density (starter ERROR 683).
        fused = ("       1871.05000E-9       0.0       0.0    1800.0"
                 "       0.4       0.0         0")
        _, starter = self._convert(self._mutated((self.CARD1, fused)))
        self.assertIn("/MAT/LAW76/187", starter)
        self.assertNotIn("/MAT/LAW76/0", starter)
        block = starter.split("/MAT/LAW76/187", 1)[1]
        self.assertIn("1.050000E-09", block)
        self.assertRegex(block, r"1800\b")

    def test_e_nu_derived_from_bulk_gmod_when_emod_blank(self):
        # E = 9KG/(3K+G) = 9·1500·643/5143 ≈ 1687.8; ν = (3K−2G)/(6K+2G) ≈ 0.3125
        kg = ("       187 1.0500E-9    1500.0     643.0       0.0"
              "       0.0       0.0         0")
        # NUEP 0.4 > derived ν 0.3125 keeps the Remark-6 min() out of the way
        result, starter = self._convert(self._mutated((self.CARD1, kg)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        self.assertRegex(block, r"1687\.8")
        self.assertRegex(block, r"0\.31246")
        self.assertTrue(any("derived E" in w for w in result.warnings))

    def test_comma_free_format_official_card(self):
        card1 = "187,1.05e-9,0,0,1800.0,0.4,0,0"
        _, starter = self._convert(self._mutated((self.CARD1, card1)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        self.assertIn("1.050000E-09", block)
        self.assertRegex(block, r"1800\b")

    def test_wide_spaced_free_format_straddling_slices(self):
        # Free-format tokens that straddle the 10-char slice boundaries
        # ("1.0500E-9" → slices "1.0500" + "E-9") pass _card's internal-
        # whitespace check; the numeric-junk check must force a free split —
        # otherwise rho comes out 1e9× too big with zero warnings.
        card1 = "     187      1.0500E-9       1500.0    643.0"
        result, starter = self._convert(self._mutated((self.CARD1, card1)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        self.assertIn("1.050000E-09", block)
        self.assertRegex(block, r"1687\.8")

    def test_tab_delimited_free_format_card(self):
        card1 = "187\t1.05e-9\t0\t0\t1800.0\t0.4\t0\t0"
        _, starter = self._convert(self._mutated((self.CARD1, card1)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        self.assertIn("1.050000E-09", block)
        self.assertRegex(block, r"1800\b")

    def test_zero_density_warns_error_683(self):
        blank_ro = ("       187                 0.0       0.0    1800.0"
                    "       0.4       0.0         0")
        result, _ = self._convert(self._mutated((self.CARD1, blank_ro)))
        self.assertTrue(any("683" in w for w in result.warnings))

    def test_zero_modulus_warns(self):
        no_e = ("       187 1.0500E-9       0.0       0.0       0.0"
                "       0.0       0.0         0")
        result, _ = self._convert(self._mutated((self.CARD1, no_e)))
        self.assertTrue(any("elastic modulus" in w for w in result.warnings))

    def test_legacy_condensed_card_gets_breadcrumb(self):
        # The pre-2026-07 handler assumed a condensed "mid ro e nu numint"
        # layout. Such a card read as the official layout lands E in BULK and
        # ν in GMOD, so the derived ν comes out ≈0.5 — the warning must point
        # at the legacy layout as the likely cause.
        condensed = ("       187 1.0500E-9    1800.0       0.4         0")
        result, _ = self._convert(self._mutated((self.CARD1, condensed)))
        self.assertTrue(any("legacy condensed" in w for w in result.warnings))

    def test_nuep_blank_reads_as_zero_and_lowers_elastic_nu(self):
        # LS-DYNA reads a blank NUEP as 0.0 (strongly dilatant flow), and per
        # MAT_187 Remark 6 the effective elastic ν becomes min(NUE, NUEP)=0.
        blank_nuep = ("       761       762       763         0          "
                      "         0                   0")
        result, starter = self._convert(self._mutated((self.CARD2, blank_nuep)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        nu_line = block.split("#                  E", 1)[1].splitlines()[1]
        self.assertEqual(nu_line.split()[1], "0")
        nu_p_line = block.split("#               Nu_p", 1)[1].splitlines()[1]
        self.assertEqual(nu_p_line.split()[0], "0")
        self.assertTrue(any("NUEP blank" in w for w in result.warnings))

    def test_remark6_lowers_elastic_nu_to_nuep(self):
        lower = self.CARD2.replace("       0.4", "       0.3")
        result, starter = self._convert(self._mutated((self.CARD2, lower)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        nu_line = block.split("#                  E", 1)[1].splitlines()[1]
        self.assertEqual(nu_line.split()[1], "0.3")
        self.assertTrue(any("Remark 6" in w for w in result.warnings))

    def test_deprpt_increment_becomes_absolute_rupture_strain(self):
        # DYNA: rupture at EPFAIL+DEPRPT; LAW76 Epsilon_r_p is absolute.
        card3 = "         0       0.6      0.05         0         0"
        _, starter = self._convert(self._mutated((self.CARD3, card3)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        eps = block.split("#        Epsilon_f_p", 1)[1].splitlines()[1].split()
        self.assertEqual([float(x) for x in eps], [0.6, 0.65])

    def test_epfail_without_deprpt_ruptures_just_past_epfail(self):
        # DYNA with DEPRPT blank ruptures AT EPFAIL; Epsilon_r_p must sit just
        # above Epsilon_f_p (a raw 0 would let the starter default EPSR=2*EPSF,
        # a fade zone the DYNA model does not have).
        card3 = "         0       0.6       0.0         0         0"
        _, starter = self._convert(self._mutated((self.CARD3, card3)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        eps = block.split("#        Epsilon_f_p", 1)[1].splitlines()[1].split()
        f, r = (float(x) for x in eps)
        self.assertEqual(f, 0.6)
        self.assertGreater(r, f)
        self.assertLess(r, f * 1.01)

    def test_lcid_d_with_epfail_warns_mutual_exclusivity(self):
        card3 = "       764       0.6      0.05         0         0"
        result, _ = self._convert(self._mutated((self.CARD3, card3)))
        self.assertTrue(any("mutually exclusive" in w for w in result.warnings))

    def test_negative_epfail_curve_convention_dropped(self):
        # EPFAIL<0 references an EPFAIL-vs-strain-rate curve in LS-DYNA; a
        # literal negative Epsilon_f_p would give negative damage (stress
        # amplification) in the LAW76 engine.
        card3 = "         0    -101.0       0.0         0         0"
        result, starter = self._convert(self._mutated((self.CARD3, card3)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        eps = block.split("#        Epsilon_f_p", 1)[1].splitlines()[1].split()
        self.assertEqual([float(x) for x in eps], [0.0, 0.0])
        self.assertTrue(any("negative" in w.lower() for w in result.warnings))

    def test_incfail_minus_one_disables_erosion(self):
        card3 = "         0       0.6      0.05         0         0"
        card4 = ("         0         0                  -1         1"
                 "         0                   0")
        result, starter = self._convert(
            self._mutated((self.CARD3, card3), (self.CARD4, card4)))
        block = starter.split("/MAT/LAW76/187", 1)[1]
        eps = block.split("#        Epsilon_f_p", 1)[1].splitlines()[1].split()
        self.assertEqual([float(x) for x in eps], [0.0, 0.0])
        self.assertTrue(any("INCFAIL" in w for w in result.warnings))

    def test_incdam_and_rbcfac_warn_unmapped(self):
        card1 = self.CARD1.replace("       0.0         0",
                                   "       1.5         0")   # RBCFAC=1.5
        card2 = self.CARD2.replace("                   0",
                                   "                   1")   # INCDAM=1
        result, _ = self._convert(
            self._mutated((self.CARD1, card1), (self.CARD2, card2)))
        warnings = " ".join(result.warnings)
        self.assertIn("RBCFAC", warnings)
        self.assertIn("INCDAM", warnings)

    def test_unmapped_nonzero_fields_warn(self):
        with_lcid_b = ("       761       762       763       764       0.4"
                       "         0                   0")
        result, _ = self._convert(self._mutated((self.CARD2, with_lcid_b)))
        self.assertTrue(any("LCID-B" in w for w in result.warnings))


GISSMO_K = """*KEYWORD
*MAT_PIECEWISE_LINEAR_PLASTICITY
         1  7.85E-9  210000.0       0.3     400.0    1000.0
*MAT_ADD_DAMAGE_GISSMO
         1                   0       0.0       1.0
       900       0.0       2.0       1.0       2.0         0
*DEFINE_CURVE
       900
                -1.0                 2.0
                 0.0                 1.0
                 1.0                 0.5
*CONTROL_TERMINATION
       1.0
*END
"""


class GissmoFailTab2Tests(unittest.TestCase):
    """*MAT_ADD_DAMAGE_GISSMO → /FAIL/TAB2."""

    def _convert(self, deck: str = GISSMO_K):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_gissmo_not_skipped(self):
        result, _ = self._convert()
        self.assertNotIn("MAT_ADD_DAMAGE_GISSMO", result.skipped_keywords)

    def test_emits_fail_tab2_on_material(self):
        _, starter = self._convert()
        self.assertIn("/FAIL/TAB2/1", starter)

    def test_core_field_mapping(self):
        _, starter = self._convert()
        block = starter.split("/FAIL/TAB2/1", 1)[1]
        rows = [r for r in block.splitlines() if r and not r.startswith("#")]
        # Row 1: EPSF_ID FCRIT (blank) FAILIP PTHK  -> LCSDG=900, FAILIP=1
        self.assertEqual(rows[0].split()[0], "900")
        # Row 2: N DCRIT INST_ID ECRIT -> N=DMGEXP=2, DCRIT=1
        self.assertEqual(rows[1].split()[0], "2")
        self.assertEqual(rows[1].split()[1], "1")

    def test_lcsdg_stays_a_function(self):
        # TAB2's EPSF_ID accepts a /FUNCT id for the 1-D case; the curve must not
        # be forced to /TABLE (that is only for LAW76 yield curves).
        _, starter = self._convert()
        self.assertIn("/FUNCT/900", starter)
        self.assertNotIn("/TABLE/1/900", starter)

    def test_positive_ecrit_warns(self):
        # A fixed (positive) ECRIT has no direct TAB2 slot -> warn.
        deck = GISSMO_K.replace("       900       0.0       2.0",
                                "       900       0.1       2.0")
        result, _ = self._convert(deck)
        self.assertTrue(any("ECRIT" in w and "TAB2" in w for w in result.warnings))

    def test_negative_ecrit_becomes_inst_id(self):
        # ECRIT<0 is an instability curve id -> INST_ID.
        deck = GISSMO_K.replace("       900       0.0       2.0",
                                "       900    -901.0       2.0")
        _, starter = self._convert(deck)
        block = starter.split("/FAIL/TAB2/1", 1)[1]
        rows = [r for r in block.splitlines() if r and not r.startswith("#")]
        self.assertEqual(rows[1].split()[2], "901")  # INST_ID

    def test_fail_tab2_block_is_complete(self):
        # /FAIL/TAB2 has 7 mandatory data cards; a missing last card (FCT_DLIM /
        # FSCALE_DLIM) makes the starter read into the next block (WARNING 100217)
        # and drop the material link (WARNING 3050, failure ignored).
        _, starter = self._convert()
        block = starter.split("/FAIL/TAB2/1", 1)[1].split("#---", 1)[0]
        data_rows = [r for r in block.splitlines() if r and not r.startswith("#")]
        self.assertEqual(len(data_rows), 7)
        self.assertIn("FCT_DLIM", block)

    def test_engine_requests_damage_output(self):
        # GISSMO damage reaches the d3plot only via /ANIM/ELEM/DAMG (NEIPH has no
        # effect on the OpenRadioss path). It must be added when GISSMO is present.
        result, _ = self._convert()
        engine = Path(result.engine_path).read_text()
        self.assertIn("/ANIM/ELEM/DAMG", engine)

    def test_no_damage_output_without_gissmo(self):
        # Drop the GISSMO card entirely -> no damage channel requested.
        deck = (GISSMO_K.split("*MAT_ADD_DAMAGE_GISSMO")[0]
                + "*CONTROL_TERMINATION\n       1.0\n*END\n")
        result, _ = self._convert(deck)
        engine = Path(result.engine_path).read_text()
        self.assertNotIn("/ANIM/ELEM/DAMG", engine)


CONSTRAINT_EROSION_K = """*KEYWORD
*MAT_ELASTIC
         1  1.05E-9    1800.0       0.4
*MAT_ADD_EROSION
         1       0.0       0.0       0.0       0.0       0.0       1.0       1.0
       0.0       0.0       0.0     0.038       0.0       0.0       0.0       0.0
*SET_NODE_LIST_TITLE
top face nodes
  20000001
         5         6         7         8
*CONSTRAINED_NODE_SET
  20000001         21.00000E20
*CONTROL_TERMINATION
       1.0
*END
"""


class ConstrainedNodeSetTests(unittest.TestCase):
    """*CONSTRAINED_NODE_SET → /RLINK."""

    def _convert(self, deck: str = CONSTRAINT_EROSION_K):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_not_skipped(self):
        result, _ = self._convert()
        self.assertNotIn("CONSTRAINED_NODE_SET", result.skipped_keywords)

    def test_emits_rlink_with_group_on_same_line(self):
        _, starter = self._convert()
        self.assertIn("/RLINK/20000001", starter)
        line = starter.split("/RLINK/20000001", 1)[1].splitlines()[3]
        # "   Tra rot   skew_ID  grnod_ID" -> code, skew, then the grnod id
        self.assertEqual(line.split(), ["010", "000", "0", "20000001"])

    def test_dof_codes(self):
        for dof, tra in ((1, "100"), (2, "010"), (3, "001"), (4, "111")):
            deck = CONSTRAINT_EROSION_K.replace(
                "  20000001         21.00000E20",
                f"  20000001         {dof}1.00000E20")
            _, starter = self._convert(deck)
            line = starter.split("/RLINK/20000001", 1)[1].splitlines()[3]
            self.assertEqual(line.split()[0], tra, f"DOF={dof}")

    def test_finite_failure_time_warns(self):
        deck = CONSTRAINT_EROSION_K.replace("21.00000E20", "2       0.5")
        result, _ = self._convert(deck)
        self.assertTrue(any("failure time" in w and "RLINK" in w
                            for w in result.warnings))


class MatAddErosionTests(unittest.TestCase):
    """*MAT_ADD_EROSION → /FAIL model."""

    def _convert(self, deck: str = CONSTRAINT_EROSION_K):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.starter_path).read_text()

    def test_not_skipped(self):
        result, _ = self._convert()
        self.assertNotIn("MAT_ADD_EROSION", result.skipped_keywords)

    def test_mxeps_maps_to_gene1_eps_max(self):
        # MXEPS (max principal strain) now maps to /FAIL/GENE1 Eps_max (card 3,
        # cols 41-60), consolidated with every other scalar criterion, rather
        # than to a standalone /FAIL/TENSSTRAIN.
        _, starter = self._convert()
        self.assertIn("/FAIL/GENE1/1", starter)
        self.assertNotIn("/FAIL/TENSSTRAIN/1", starter)
        card3 = starter.split("/FAIL/GENE1/1", 1)[1].splitlines()[6]
        self.assertEqual(card3[40:60].strip(), "0.038")   # Eps_max

    def test_effeps_maps_to_gene1_eps_eff(self):
        # EFFEPS (max effective strain) now maps to /FAIL/GENE1 Eps_eff (card 3,
        # cols 61-80), not a standalone /FAIL/JOHNSON.
        deck = CONSTRAINT_EROSION_K.replace(
            "         1       0.0       0.0       0.0       0.0       0.0       1.0       1.0",
            "         1       0.0       0.0       0.0      0.05       0.0       1.0       1.0")
        _, starter = self._convert(deck)
        self.assertIn("/FAIL/GENE1/1", starter)
        card3 = starter.split("/FAIL/GENE1/1", 1)[1].splitlines()[6]
        self.assertEqual(card3[60:80].strip(), "0.05")   # Eps_eff

    def test_gissmo_in_erosion_warns(self):
        # IDAM>=1 (GISSMO embedded in *MAT_ADD_EROSION) is reported, not converted.
        deck = CONSTRAINT_EROSION_K.replace(
            "       0.0       0.0       0.0     0.038       0.0       0.0       0.0       0.0",
            "       0.0       0.0       0.0     0.038       0.0       0.0       0.0       0.0\n"
            "         1")
        result, _ = self._convert(deck)
        self.assertTrue(any("IDAM" in w and "GISSMO" in w for w in result.warnings))


RESTART_K = """*KEYWORD
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
*CONTROL_TERMINATION
       1.0
*END
"""


DT2MS_K = """*KEYWORD
*CONTROL_TIMESTEP
$#  dtinit    tssfac      isdo    tslimt     dt2ms
       0.0       0.0         0       0.0-1.1120E-6
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
*CONTROL_TERMINATION
       1.0
*END
"""


class MassScalingTests(unittest.TestCase):
    """*CONTROL_TIMESTEP DT2MS<0 → engine /DT/NODA/CST (mass scaling)."""

    def _engine(self, deck=DT2MS_K):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path)
        return result, Path(result.engine_path).read_text()

    def test_dt2ms_emits_dt_noda_cst(self):
        _, engine = self._engine()
        self.assertIn("/DT/NODA/CST/0", engine)

    def test_tmin_is_abs_dt2ms(self):
        # Tmin = |DT2MS| holds the run at the LS-DYNA target; Tsca defaults to 0.9
        # when *CONTROL_TIMESTEP TSSFAC is 0.
        _, engine = self._engine()
        row = engine.split("/DT/NODA/CST/0", 1)[1].splitlines()[1]
        tsca, tmin = row.split()
        self.assertEqual(float(tsca), 0.9)
        self.assertAlmostEqual(float(tmin), 1.112e-6, places=12)

    def test_positive_dt2ms_no_mass_scaling(self):
        # DT2MS >= 0 is init-only / no mass scaling -> no /DT/NODA/CST.
        deck = DT2MS_K.replace("-1.1120E-6", "       0.0")
        _, engine = self._engine(deck)
        self.assertNotIn("/DT/NODA/CST", engine)

    def test_warns_about_mass_scaling(self):
        result, _ = self._engine()
        self.assertTrue(any("DT2MS" in w and "/DT/NODA/CST" in w
                            for w in result.warnings))


class AdvancedMassScalingTests(unittest.TestCase):
    """--ams: a mass-scaled explicit deck (*CONTROL_TIMESTEP DT2MS<0) gets
    engine /DT/AMS + starter /AMS instead of /DT/NODA/CST, and element-free
    rigid masters are forced (AMS ERROR 1066 otherwise)."""

    def _convert(self, deck=DT2MS_K, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return (result,
                Path(result.engine_path).read_text(),
                Path(result.starter_path).read_text())

    def test_ams_emits_dt_ams_not_noda_cst(self):
        _r, engine, _s = self._convert(ams=True)
        self.assertIn("/DT/AMS", engine)
        self.assertNotIn("/DT/NODA/CST", engine)

    def test_ams_tsca_is_067_and_tmin_is_abs_dt2ms(self):
        # AMS uses the OpenRadioss-recommended 0.67 scale factor (the PCG needs
        # more margin than /DT/NODA/CST's 0.9); Tmin still = |DT2MS|.
        _r, engine, _s = self._convert(ams=True)
        row = engine.split("/DT/AMS", 1)[1].splitlines()[1]
        tsca, tmin = row.split()
        self.assertEqual(float(tsca), 0.67)
        self.assertAlmostEqual(float(tmin), 1.112e-6, places=12)

    def test_ams_emits_starter_card_for_all_parts(self):
        _r, _e, starter = self._convert(ams=True)
        lines = starter.splitlines()
        self.assertIn("/AMS", lines)
        i = lines.index("/AMS")
        self.assertEqual(lines[i + 1], "#grpart_ID")
        self.assertEqual(lines[i + 2].strip(), "0")   # 0 = all parts

    def test_default_off_still_noda_cst(self):
        _r, engine, starter = self._convert()          # ams not passed
        self.assertIn("/DT/NODA/CST/0", engine)
        self.assertNotIn("/DT/AMS", engine)
        self.assertNotIn("/AMS", starter.splitlines())

    def test_ams_positive_dt2ms_emits_no_ams(self):
        # DT2MS >= 0 is init-only / no mass scaling → neither the engine nor the
        # starter AMS card is emitted even with --ams.
        deck = DT2MS_K.replace("-1.1120E-6", "       0.0")
        _r, engine, starter = self._convert(deck, ams=True)
        self.assertNotIn("/DT/AMS", engine)
        self.assertNotIn("/AMS", starter.splitlines())

    def test_ams_warns_with_divergence_note(self):
        result, _e, _s = self._convert(ams=True)
        self.assertTrue(any("/DT/AMS" in w and "DIVERG" in w.upper()
                            for w in result.warnings))

    def test_ams_overrides_rigid_master_opt_out(self):
        # Element-free rigid masters are on by default; --ams REQUIRES them, so it
        # overrides an explicit --no-rigid-cog-master (a mesh-node master would
        # trip AMS ERROR 1066).
        result, _e, starter = self._convert(FORCE_RB_K, ams=True,
                                            rigid_cog_master=False)
        self.assertIn("/RBODY/9", starter)      # synthesized despite the opt-out
        self.assertNotIn("/RBODY/5", starter)
        self.assertTrue(any("overriding --no-rigid-cog-master" in w
                            for w in result.warnings))


class EngineRestartTests(unittest.TestCase):
    """/RFILE/OFF is emitted by default; write_restart keeps OpenRadioss's
    default restart (.rst) writing."""

    def _engine(self, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(RESTART_K)
        result = convert(path, **opts)
        return Path(result.engine_path).read_text()

    def test_rfile_off_is_default(self):
        self.assertIn("/RFILE/OFF", self._engine())

    def test_write_restart_keeps_restart(self):
        self.assertNotIn("/RFILE", self._engine(write_restart=True))


def _state_from_deck(deck: str) -> ConversionState:
    """Parse+dispatch a deck given as a string; returns the filled state."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


class FreeFormatParsingTests(unittest.TestCase):
    """LS-DYNA comma-delimited free format must parse everywhere."""

    def test_parse_free_commas(self):
        self.assertEqual(parse_free("1,10.0,20.0,30.0"),
                         ["1", "10.0", "20.0", "30.0"])
        # consecutive commas hold an EMPTY field in position
        self.assertEqual(parse_free("1,,3"), ["1", "", "3"])
        # mixed comma/space delimiters
        self.assertEqual(parse_free("10, 20 30"), ["10", "20", "30"])

    def test_comma_format_nodes_and_material(self):
        state = _state_from_deck(
            "*KEYWORD\n*NODE\n1,10.0,20.0,30.0\n2,1.5,2.5,3.5\n"
            "*MAT_ELASTIC\n7,7.85e-9,210000.0,0.3\n*END\n")
        self.assertEqual(len(state.nodes), 2)
        self.assertAlmostEqual(state.nodes[1].y, 20.0)
        self.assertIn(7, state.mat_elastic)
        self.assertAlmostEqual(state.mat_elastic[7].E, 210000.0)
        self.assertAlmostEqual(state.mat_elastic[7].nu, 0.3)

    def test_free_format_part_card(self):
        # A *PART data card written "1 1 1" must not be fixed-sliced to pid 0.
        state = _state_from_deck(
            "*KEYWORD\n*PART\nfree part\n1 1 1\n*END\n")
        self.assertIn(1, state.parts)
        self.assertEqual(state.parts[1].secid, 1)
        self.assertEqual(state.parts[1].mid, 1)

    def test_free_format_set_segment(self):
        state = _state_from_deck(
            "*KEYWORD\n*SET_SEGMENT\n1\n1 2 3 4\n5 6 7 8\n*END\n")
        self.assertEqual(state.segment_sets[1].segments,
                         [[1, 2, 3, 4], [5, 6, 7, 8]])


class IncludeHandlingTests(unittest.TestCase):
    def _dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def test_multiple_include_files(self):
        d = self._dir()
        with open(os.path.join(d, "a.k"), "w") as fh:
            fh.write("*MAT_ELASTIC\n         1   7.85e-9    210000       0.3\n")
        with open(os.path.join(d, "b.k"), "w") as fh:
            fh.write("*MAT_ELASTIC\n         2   7.85e-9    210000       0.3\n")
        main = os.path.join(d, "m.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE\na.k\nb.k\n*END\n")
        kws = [b.keyword for b in parse_k_file(main)]
        self.assertEqual(kws.count("MAT_ELASTIC"), 2)

    def test_include_transform_offsets_now_applied(self):
        # The IDNOFF on card 2 is applied numerically at parse time
        # (k2rad.assembly), so the historic "NOT applied" warning is gone and
        # the node id carries the offset. (Full coverage lives in
        # tests/test_include_transform.py.)
        from k2rad.parser import PARSER_WARNINGS
        d = self._dir()
        with open(os.path.join(d, "c.k"), "w") as fh:
            fh.write("*NODE\n         1             0.0             0.0             0.0\n")
        main = os.path.join(d, "m.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nc.k\n"
                     "      1000\n*END\n")
        blocks = parse_k_file(main)
        node_blocks = [b for b in blocks if b.keyword == "NODE"]
        self.assertTrue(node_blocks)
        self.assertIn("1001", node_blocks[0].raw[0])
        self.assertFalse(any("NOT applied" in w for w in PARSER_WARNINGS))


class ParameterSubstitutionTests(unittest.TestCase):
    def test_fixed_format_parameters_resolve(self):
        state = _state_from_deck(
            "*KEYWORD\n*PARAMETER\n"
            + "R endtim  " + "      0.05" + "Isteps    " + "       200" + "\n"
            + "*CONTROL_TERMINATION\n&endtim\n*END\n")
        self.assertIsNotNone(state.ctrl_termination)
        self.assertAlmostEqual(state.ctrl_termination.endtim, 0.05)

    def test_free_format_and_negation(self):
        state = _state_from_deck(
            "*KEYWORD\n*PARAMETER\nR accel, 9810.0\n"
            "*DEFINE_CURVE\n         9\n0.0,0.0\n1.0,-&accel\n*END\n")
        self.assertEqual(state.curves[9].pts[1], (1.0, -9810.0))

    def test_unresolved_parameter_warns(self):
        result, _ = _convert_string_deck(
            TINY_K.replace("*CONTROL_TERMINATION\n       1.0",
                           "*CONTROL_TERMINATION\n&nodef"))
        self.assertTrue(any("undefined" in w and "&nodef" in w
                            for w in result.warnings))


class CurveOffsetScaleOrderTests(unittest.TestCase):
    def test_offset_applied_before_scale(self):
        # LS-DYNA: X = SFA·(x + OFFA), Y = SFO·(y + OFFO)
        state = _state_from_deck(
            "*KEYWORD\n*DEFINE_CURVE\n"
            "         7         0       2.0       3.0       1.0      10.0\n"
            "                 1.0                 1.0\n*END\n")
        self.assertEqual(state.curves[7].pts, [(4.0, 33.0)])


class HandlerCardLayoutTests(unittest.TestCase):
    def test_mat_null_reads_ym_pr_columns(self):
        # Card: mid ro pc mu terod cerod ym pr
        state = _state_from_deck(
            "*KEYWORD\n*MAT_NULL\n"
            "         9    1.0e-9    -1.0e6     0.001       0.0       0.0"
            "     2.0e3      0.30\n*END\n")
        self.assertAlmostEqual(state.mat_null[9].E, 2000.0)
        self.assertAlmostEqual(state.mat_null[9].nu, 0.30)

    def test_multi_part_block(self):
        state = _state_from_deck(
            "*KEYWORD\n*PART\npart one\n"
            "         1         1         1\npart two\n"
            "         2         2         2\npart three\n"
            "         3         3         3\n*END\n")
        self.assertEqual(sorted(state.parts), [1, 2, 3])
        self.assertEqual(state.parts[2].title, "part two")

    def test_load_segment_multiple_cards(self):
        state = _state_from_deck(
            "*KEYWORD\n*LOAD_SEGMENT\n"
            "         5       1.0       0.0         1         2         3         4\n"
            "         5       1.0       0.0         2         5         6         3\n"
            "*END\n")
        self.assertEqual(len(state.pressure_loads), 2)
        self.assertEqual(state.pressure_loads[1].nodes, [2, 5, 6, 3])

    def test_blank_sf_defaults_to_one(self):
        # SF column blank on prescribed motions / rigid-body loads = 1.0
        state = _state_from_deck(
            "*KEYWORD\n*BOUNDARY_PRESCRIBED_MOTION_SET\n"
            "         3         1         2         7\n"
            "*BOUNDARY_PRESCRIBED_MOTION_RIGID\n"
            "         4         1         0         8\n"
            "*LOAD_RIGID_BODY\n"
            "         4         3         9\n*END\n")
        self.assertAlmostEqual(state.prescribed_motion_sets[0].sf, 1.0)
        self.assertAlmostEqual(state.prescribed_motion_sets[0].death, 1e28)
        self.assertAlmostEqual(state.prescribed_motions[0].sf, 1.0)
        self.assertAlmostEqual(state.load_rigid_bodies[0].sf, 1.0)

    def test_triangle_shell_and_two_node_beam_kept(self):
        state = _state_from_deck(
            "*KEYWORD\n*ELEMENT_SHELL\n"
            "       1       1       1       2       3\n"
            "*ELEMENT_BEAM\n"
            "      10       2     101     102\n*END\n")
        self.assertEqual(len(state.shell_elems), 1)
        self.assertEqual(state.shell_elems[0].nodes, [1, 2, 3])
        self.assertEqual(len(state.beam_elems), 1)
        self.assertEqual(state.beam_elems[0].n3, 0)

    def test_define_coordinate_system_short_card(self):
        # trailing XL/YL/ZL blank (default 0) must not crash
        state = _state_from_deck(
            "*KEYWORD\n*DEFINE_COORDINATE_SYSTEM\n"
            "4 1.0 2.0 3.0\n*END\n")
        self.assertIn(4, state.coord_sys)
        self.assertAlmostEqual(state.coord_sys[4].zo, 3.0)

    def test_simplified_johnson_cook_mapping(self):
        state = _state_from_deck(
            "*KEYWORD\n*MAT_SIMPLIFIED_JOHNSON_COOK\n"
            "         3   7.85e-9    210000       0.3       1.0\n"
            "     350.0     275.0      0.36     0.022\n*END\n")
        mat = state.mat_plas_tab[3]
        self.assertAlmostEqual(mat.sigy, 350.0)
        self.assertAlmostEqual(mat.E, 210000.0)
        # sampled hardening σ = A + B·εpⁿ
        self.assertAlmostEqual(mat.es_pts[0], 350.0)
        i = mat.eps_pts.index(0.1)
        self.assertAlmostEqual(mat.es_pts[i], 350.0 + 275.0 * 0.1 ** 0.36, places=6)
        # nonzero C → rate-term warning
        self.assertTrue(any("SIMPLIFIED_JOHNSON_COOK" in w for w in state.warnings))


class Tet10MidedgeMapTests(unittest.TestCase):
    """The mid-edge map must match the LS-DYNA ten-node tet convention:
    n5=mid(1,2) n6=mid(2,3) n7=mid(1,3) n8=mid(1,4) n9=mid(2,4) n10=mid(3,4).
    A standard straight-edged tet10 must therefore snap ZERO nodes."""

    STD_TET10 = (
        "*KEYWORD\n*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2             1.0             0.0             0.0\n"
        "       3             0.0             1.0             0.0\n"
        "       4             0.0             0.0             1.0\n"
        "       5             0.5             0.0             0.0\n"
        "       6             0.5             0.5             0.0\n"
        "       7             0.0             0.5             0.0\n"
        "       8             0.0             0.0             0.5\n"
        "       9             0.5             0.0             0.5\n"
        "      10             0.0             0.5             0.5\n"
        "*ELEMENT_SOLID\n"
        "       1       1\n"
        "       1       2       3       4       5       6       7       8"
        "       9      10\n"
        "*END\n")

    def test_standard_tet10_snaps_zero_nodes(self):
        from k2rad.writer import _snap_tet10_midsides
        state = _state_from_deck(self.STD_TET10)
        self.assertEqual(len(state.solid_elems), 1)
        self.assertEqual(len(state.solid_elems[0].nodes), 10)
        moved = _snap_tet10_midsides(state)
        self.assertEqual(moved, 0)
        # coordinates untouched
        self.assertEqual((state.nodes[8].x, state.nodes[8].y, state.nodes[8].z),
                         (0.0, 0.0, 0.5))
        self.assertEqual((state.nodes[9].x, state.nodes[9].y, state.nodes[9].z),
                         (0.5, 0.0, 0.5))


class BcsSkewAndGrnodTests(unittest.TestCase):
    DECK = TINY_K.replace(
        "*CONTROL_TERMINATION",
        "*DEFINE_COORDINATE_SYSTEM\n"
        "         7       0.0       0.0       0.0       0.0       1.0       0.0\n"
        "       0.0       0.0       1.0\n"
        "*SET_NODE_LIST\n         5\n         1         2\n"
        "*BOUNDARY_SPC_SET\n"
        "         5         7         1         0         0         0         0         0\n"
        "         5         0         0         1         0         0         0         0\n"
        "*CONTROL_TERMINATION")

    def test_bcs_carries_skew_and_grnod_emitted_once(self):
        result, starter = _convert_string_deck(self.DECK)
        self.assertIn("/SKEW/FIX/7", starter)
        # first /BCS references skew 7
        bcs1 = starter.split("/BCS/1\n")[1].splitlines()[2]
        self.assertIn("         7", bcs1)
        # the shared node-set /GRNOD appears exactly once
        self.assertEqual(starter.count("/GRNOD/NODE/5\n"), 1)

    def test_unknown_cid_warns_and_falls_back_to_global(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*SET_NODE_LIST\n         5\n         1         2\n"
            "*BOUNDARY_SPC_SET\n"
            "         5        99         1         0         0         0         0         0\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertTrue(any("cid=99" in w for w in result.warnings))


class BilinearHardeningSlopeTests(unittest.TestCase):
    def test_etan_converted_to_plastic_hardening_slope(self):
        deck = TINY_K.replace("*MAT_ELASTIC", "*MAT_PIECEWISE_LINEAR_PLASTICITY")
        deck = deck.replace(
            "         1   7.86e-9    210000.0      0.3\n",
            "         1   7.86e-9    210000.0      0.3     350.0   21000.0\n"
            "       0.0       0.0         0\n")
        result, starter = _convert_string_deck(deck)
        self.assertIn("Auto_SY_ET_mid1", starter)
        # H = E·ETAN/(E−ETAN) = 210000·21000/189000 = 23333.33;
        # curve point at εp=1 is sigy + H = 23683.33 (raw ETAN would give 21350)
        self.assertIn("23683.3", starter)
        self.assertNotIn("21350", starter)


class HexaMassDecompositionTests(unittest.TestCase):
    def test_hexa_tets_cover_full_volume(self):
        from modal_solve import _HEXA_TETS, _tet_volume
        cube = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
        vol = sum(_tet_volume(*(cube[i] for i in t)) for t in _HEXA_TETS)
        self.assertAlmostEqual(vol, 1.0, places=12)
        # every tet must be non-degenerate
        for t in _HEXA_TETS:
            self.assertGreater(_tet_volume(*(cube[i] for i in t)), 0.0)


class GroundingSpringScriptTests(unittest.TestCase):
    def test_prop_type8_block_is_closed(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from add_grounding_springs import build_spring_block
        block = build_spring_block(
            1, ("0.0", "0.0", "0.0"), 100.0, 100.0, ground_node=88000001,
            grnod=88000010, bcs=88000011, prop=8001, part=8002, elem=8003)
        prop = block.split("/PROP/TYPE8/8001")[1].split("/PART/")[0]
        self.assertIn("Fsmooth", prop)
        data_cards = [ln for ln in prop.splitlines()
                      if ln.strip() and not ln.startswith(("#", "/"))]
        # title + Mass/Inertia + 6 DOFs × 3 + closing Fsmooth/Fcut = 21
        self.assertEqual(len(data_cards), 21)
        self.assertRegex(data_cards[-1], r"^\s+0\s+0(\.0)?$")


class OutputRobustnessTests(unittest.TestCase):
    def test_output_stem_in_new_directory(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(TINY_K)
        stem = os.path.join(tmp.name, "does", "not", "exist", "run")
        result = convert(path, stem, write_log=False)
        self.assertTrue(os.path.isfile(result.starter_path))

    def test_non_ascii_title_written_as_utf8(self):
        # Build the non-ASCII title programmatically (chr(0xE4)=a-umlaut,
        # chr(0xF6)=o-umlaut) so the test SOURCE stays pure ASCII. A literal
        # non-ASCII byte in the source is decoded per the interpreter's source
        # encoding, which is not guaranteed UTF-8 on every CI runner (Windows),
        # and would spuriously fail this assertion regardless of the converter.
        title = "Tr" + chr(0xE4) + "ger sch" + chr(0xF6) + "n"
        deck = TINY_K.replace("shell part", title)
        result, starter = _convert_string_deck(deck)
        self.assertIn(title, starter)


class PrescribedMotionNodeTests(unittest.TestCase):
    def test_motion_node_becomes_impdisp(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*DEFINE_CURVE\n         7\n0.0,0.0\n1.0,2.0\n"
            "*BOUNDARY_PRESCRIBED_MOTION_NODE\n"
            "         3         1         2         7\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertNotIn("BOUNDARY_PRESCRIBED_MOTION_NODE",
                         result.skipped_keywords)
        self.assertIn("/IMPDISP/", starter)
        # the auto-created single-node group holds node 3
        grnod = starter.split("/IMPDISP/")[1].split("/GRNOD/NODE/")[1]
        self.assertEqual(grnod.splitlines()[2].strip(), "3")

    def test_motion_node_sf_zero_becomes_bcs(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*BOUNDARY_PRESCRIBED_MOTION_NODE\n"
            "         3         1         2         7       0.0\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertIn("/BCS/", starter)
        self.assertNotIn("/IMPDISP/", starter)


class LoadNodeTests(unittest.TestCase):
    def test_load_node_point_emits_cload(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*DEFINE_CURVE\n         9\n0.0,0.0\n1.0,1000.0\n"
            "*LOAD_NODE_POINT\n"
            "         2         3         9       2.0\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertIn("/CLOAD/", starter)
        cload = starter.split("/CLOAD/")[1]
        data = cload.splitlines()[3]
        self.assertIn("         9", data)   # funct id
        self.assertIn("Z", data)            # dof 3 = Z force
        self.assertIn("2", data)            # scale factor
        self.assertIn("/GRNOD/NODE/", starter)

    def test_load_node_set_and_moment_dof(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*DEFINE_CURVE\n         9\n0.0,0.0\n1.0,1.0\n"
            "*SET_NODE_LIST\n        11\n         1         2\n"
            "*LOAD_NODE_SET\n"
            "        11         6         9\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        cload_data = starter.split("/CLOAD/")[1].splitlines()[3]
        self.assertIn("YY", cload_data)     # dof 6 = moment about Y

    def test_follower_load_warns(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*DEFINE_CURVE\n         9\n0.0,0.0\n1.0,1.0\n"
            "*LOAD_NODE_POINT\n"
            "         2         4         9\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertNotIn("/CLOAD/", starter)
        self.assertTrue(any("follower" in w for w in result.warnings))


class ConstrainedExtraNodesTests(unittest.TestCase):
    RIGID_K = TINY_K.replace("*MAT_ELASTIC", "*MAT_RIGID").replace(
        "*CONTROL_TERMINATION",
        "*NODE\n"
        "     100             5.0             5.0             5.0\n"
        "     101             6.0             5.0             5.0\n"
        "*SET_NODE_LIST\n        20\n       100       101\n"
        "*CONSTRAINED_EXTRA_NODES_SET\n"
        "         1        20\n"
        "*CONTROL_TERMINATION")

    def test_extra_nodes_join_rbody_group(self):
        result, starter = _convert_string_deck(self.RIGID_K)
        self.assertIn("/RBODY/", starter)
        body = starter.split("rb_nodes_pid1")[1]
        ids = []
        for ln in body.splitlines()[1:]:
            if ln.startswith(("/", "#")):
                break
            ids.extend(int(t) for t in ln.split())
        self.assertIn(100, ids)
        self.assertIn(101, ids)

    def test_extra_node_on_deformable_part_warns(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*CONSTRAINED_EXTRA_NODES_NODE\n"
            "         1         4\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertTrue(any("EXTRA_NODES" in w for w in result.warnings))


class RigidWallPlanarTests(unittest.TestCase):
    def _deck(self, extra=""):
        return TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*SET_NODE_LIST\n        30\n         1         2         3\n"
            "*RIGIDWALL_PLANAR\n"
            "        30         0         0\n"
            "       0.0       0.0      -1.0       0.0       0.0       1.0"
            + extra + "\n"
            "*CONTROL_TERMINATION")

    def test_basic_wall(self):
        result, starter = _convert_string_deck(self._deck())
        self.assertNotIn("RIGIDWALL_PLANAR", result.skipped_keywords)
        self.assertIn("/RWALL/PLANE/", starter)
        block = starter.split("/RWALL/PLANE/")[1]
        data = block.splitlines()[3]
        # node_ID=0, Slide=0 (frictionless), grnd_ID1 nonzero
        self.assertEqual(data.split()[0], "0")
        self.assertEqual(data.split()[1], "0")
        self.assertNotEqual(data.split()[2], "0")
        # geometry: M=(0,0,-1), M1=(0,0,1)
        self.assertIn("-1", block.splitlines()[5])
        self.assertIn("1", block.splitlines()[7])

    def test_friction_wall_gets_slide2_and_fric_card(self):
        result, starter = _convert_string_deck(self._deck("       0.3"))
        block = starter.split("/RWALL/PLANE/")[1]
        data = block.splitlines()[3]
        self.assertEqual(data.split()[1], "2")
        self.assertIn("0.3", block.splitlines()[5])

    def test_stick_wall_gets_slide1(self):
        result, starter = _convert_string_deck(self._deck("       1.0"))
        block = starter.split("/RWALL/PLANE/")[1]
        self.assertEqual(block.splitlines()[3].split()[1], "1")

    def test_all_nodes_wall_uses_bbox_search_distance(self):
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*RIGIDWALL_PLANAR\n"
            "         0         0         0\n"
            "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        data = starter.split("/RWALL/PLANE/")[1].splitlines()[3]
        self.assertEqual(data.split()[2], "0")     # grnd_ID1 = 0 (all nodes)
        self.assertGreater(float(data.split()[4]), 0.0)

    def test_moving_flavour_now_converts(self):
        # _MOVING used to warn-skip; it now converts to a moving /RWALL/PLANE
        # (carrier node with Mass + V0 along the wall normal). The detailed
        # field assertions live in tests/test_rwall_variants.py.
        deck = TINY_K.replace(
            "*CONTROL_TERMINATION",
            "*RIGIDWALL_PLANAR_MOVING\n"
            "         0         0         0\n"
            "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
            "      10.0       1.0\n"
            "*CONTROL_TERMINATION")
        result, starter = _convert_string_deck(deck)
        self.assertIn("/RWALL/PLANE/", starter)
        self.assertNotIn("RIGIDWALL_PLANAR_MOVING", result.skipped_keywords)

    def test_rwforc_emits_th_rwall(self):
        deck = self._deck().replace(
            "*RIGIDWALL_PLANAR\n",
            "*DATABASE_RWFORC\n      1e-4\n*RIGIDWALL_PLANAR\n")
        result, starter = _convert_string_deck(deck)
        self.assertIn("/TH/RWALL/", starter)


class LoadSegmentSetTests(unittest.TestCase):
    """*LOAD_SEGMENT_SET → /SURF/SEG + /PLOAD over a *SET_SEGMENT surface.

    Regression: the keyword used to dispatch to handle_skip, so the pressure
    load silently vanished from the converted deck.
    """

    # One quad shell whose face is a *SET_SEGMENT loaded by *LOAD_SEGMENT_SET.
    DECK = (
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
        "*DEFINE_CURVE\n"
        "         7         0       1.0       1.0\n"
        "                 0.0                 0.0\n"
        "                 1.0                 1.0\n"
        "*SET_SEGMENT\n"
        "         5\n"
        "         1         2         3         4\n"
        "*LOAD_SEGMENT_SET\n"
        "         5         7       2.5       0.0\n"
        "*CONTROL_TERMINATION\n"
        "       1.0\n"
        "*END\n"
    )

    @staticmethod
    def _block(starter, prefix):
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith(prefix))
        return lines, i

    @staticmethod
    def _data_lines(lines, i):
        out = []
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            out.append(ln)
        return out

    def test_not_skipped(self):
        result, _ = _convert_string_deck(self.DECK)
        self.assertNotIn("LOAD_SEGMENT_SET", result.skipped_keywords)

    def test_emits_surf_seg_and_pload(self):
        _, starter = _convert_string_deck(self.DECK)
        self.assertIn("/PLOAD/", starter)
        lines, i = self._block(starter, "/SURF/SEG/")
        surf_id = int(lines[i].split("/")[3])
        seg = self._data_lines(lines, i)[1]                 # after the title line
        self.assertEqual(
            [int(seg[k:k + 10]) for k in range(0, 50, 10)], [1, 1, 2, 3, 4])
        lines, i = self._block(starter, "/PLOAD/")
        card = self._data_lines(lines, i)[1]
        self.assertEqual(int(card[0:10]), surf_id)          # surf_ID
        self.assertEqual(int(card[10:20]), 7)               # fct_IDT = lcid
        self.assertEqual(card[80:100].strip(), "2.5")       # Fscale_y = sf

    def test_missing_set_segment_warns_not_crashes(self):
        deck = self.DECK.replace(
            "*SET_SEGMENT\n"
            "         5\n"
            "         1         2         3         4\n", "")
        result, starter = _convert_string_deck(deck)
        self.assertNotIn("/PLOAD/", starter)
        self.assertTrue(any("SET_SEGMENT 5" in w for w in result.warnings))

    def test_handler_stores_load(self):
        state = ConversionState()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "seg.k")
        with open(path, "w") as fh:
            fh.write(self.DECK)
        for block in parse_k_file(path):
            dispatch(block, state)
        self.assertEqual(len(state.segment_set_pressure_loads), 1)
        ssl = state.segment_set_pressure_loads[0]
        self.assertEqual((ssl.ssid, ssl.lcid, ssl.sf), (5, 7, 2.5))


def _c10(*vals):
    """Render fields as LS-DYNA fixed 10-wide columns."""
    return "".join(str(v).rjust(10) for v in vals)


def _curve(cid, y):
    return "\n".join([
        "*DEFINE_CURVE", _c10(cid, 0, "1.0", "1.0"),
        "                 0.0                 0.0",
        "                 0.5" + str(y).rjust(20),
    ])


FOAM_HONEYCOMB_K = "\n".join([
    "*KEYWORD",
    "*NODE",
    "       1             0.0             0.0             0.0",
    "       2             1.0             0.0             0.0",
    "       3             1.0             1.0             0.0",
    "       4             0.0             1.0             0.0",
    "*ELEMENT_SHELL", "       1       1       1       2       3       4",
    "*PART", "foam part", _c10(1, 1, 1),
    "*SECTION_SHELL", _c10(1, 2), "       1.0",
    # MAT_063: MID RHO E PR LCID TSC DAMP
    "*MAT_CRUSHABLE_FOAM",
    _c10(1, "1.0e-9", "50000.0", "0.0", 100, "1.5", "0.05"),
    # MAT_057: card1 MID RHO E LCID TC HU BETA DAMP / card2 SHAPE FAIL ...
    "*MAT_LOW_DENSITY_FOAM",
    _c10(2, "3.0e-11", "2.0", 200, "0.2", "0.5", "10.0", "0.1"),
    _c10("4.0", 0, 0, 0, 0, 0, 0),
    # MAT_083: card1 MID RHO E ED TC FAIL DAMP TBID / card2 (HU@8) / card3 analytic (SHAPE@8)
    "*MAT_FU_CHANG_FOAM",
    _c10(3, "5.0e-11", "3.0", "0.0", "0.1", "0.0", "0.05", 300),
    _c10(0, 0, 0, 0, 0, "0.0", "0.0", "0.4"),
    _c10("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
    _c10("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "2.5"),
    # MAT_026: card1 MID RO E PR SIGY VF MU BULK / card2 curves / card3 moduli
    "*MAT_HONEYCOMB",
    _c10(4, "2.7e-9", "70000.0", "0.0", "200.0", "0.1", "0.0", "0.0"),
    _c10(400, 401, 402, 403, 410, 411, 412, 0),
    _c10("500.0", "600.0", "700.0", "250.0", "260.0", "270.0", "2.0", "0"),
    _curve(100, 50.0), _curve(200, 5.0), _curve(300, 8.0),
    _curve(400, 100.0), _curve(401, 110.0), _curve(402, 120.0),
    _curve(403, 50.0), _curve(410, 30.0), _curve(411, 31.0), _curve(412, 32.0),
    "*CONTROL_TERMINATION", "       1.0", "*END", "",
])


class FoamHoneycombMaterialTests(unittest.TestCase):
    """*MAT_CRUSHABLE_FOAM/LOW_DENSITY_FOAM/FU_CHANG_FOAM/HONEYCOMB → LAW50/38/70/28.

    Column positions checked against the OpenRadioss cfg FORMAT blocks used for a
    /BEGIN 2022 deck (matl28/mat_law50 radioss90, matl38/matl70 radioss2019).
    """

    def setUp(self):
        self.result, self.starter = _convert_string_deck(FOAM_HONEYCOMB_K)

    def _law(self, header):
        """Data (non-comment) lines of the material block whose keyword line
        starts with *header* (e.g. '/MAT/LAW50/1'), up to the next keyword."""
        lines = self.starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith(header))
        out = []
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            out.append(ln)
        return out

    def test_all_four_emitted_none_skipped(self):
        for kw in ("MAT_CRUSHABLE_FOAM", "MAT_LOW_DENSITY_FOAM",
                   "MAT_FU_CHANG_FOAM", "MAT_HONEYCOMB"):
            self.assertNotIn(kw, self.result.skipped_keywords)
        for law in ("/MAT/LAW50/1", "/MAT/LAW38/2", "/MAT/LAW70/3", "/MAT/LAW28/4"):
            self.assertIn(law, self.starter)

    def test_law50_isotropic_moduli_and_yield_functions(self):
        d = self._law("/MAT/LAW50/1")
        # d: title, rho, E11/E22/E33, G12/G23/G31, asrate, Iflag1, funID11 ...
        self.assertAlmostEqual(float(d[2][0:20]), 50000.0)   # E11
        self.assertAlmostEqual(float(d[2][20:40]), 50000.0)  # E22
        self.assertAlmostEqual(float(d[2][40:60]), 50000.0)  # E33
        self.assertAlmostEqual(float(d[3][0:20]), 25000.0)   # G12 = E/2(1+nu)
        # The LCID drives every direction's first yield function: six funID header
        # lines, all pointing at curve 100.
        fun_lines = [ln for ln in d if ln[0:10].strip() == "100"]
        self.assertEqual(len(fun_lines), 6)

    def test_law50_drops_tsc_and_damp(self):
        w = " ".join(self.result.warnings)
        self.assertIn("TSC=1.5", w)
        self.assertIn("DAMP=0.05", w)
        self.assertIn("isotropic", w.lower())

    def test_law38_e0_loading_curve_and_cutoff(self):
        d = self._law("/MAT/LAW38/2")
        # d: title, rho, E0-card, beta, Kair, P0, ful, Nfunct, Efinal,
        #    Scale, StrainRate, Loading, Unloading
        self.assertAlmostEqual(float(d[2][0:20]), 2.0)       # E0 = E
        nfunct_card = d[7]
        self.assertEqual(nfunct_card[0:10].strip(), "1")     # N_funct
        self.assertAlmostEqual(float(nfunct_card[20:40]), 0.2)  # CUToff = TC
        # loading function is the last-but-one data line, unloading the last
        self.assertEqual(d[-2].strip(), "200")               # Loading function = LCID
        self.assertEqual(d[-1].strip(), "0")                 # Unloading function

    def test_law38_hysteresis_is_warned_approximate(self):
        w = " ".join(self.result.warnings)
        self.assertIn("HU=0.5", w)
        self.assertTrue(any("LOW_DENSITY_FOAM 2" in x and "approx" in x.lower()
                            for x in self.result.warnings))

    def test_law70_maps_curve_family_and_unloading(self):
        d = self._law("/MAT/LAW70/3")
        # d: title, rho, EO-card, Fcut/Nload/Shape/Hys card, one loading card
        self.assertAlmostEqual(float(d[2][0:20]), 3.0)       # EO = E
        # F_cut(20) Ismooth(10) Nload(10) Nunload(10) Iflag(10) Shape(20) Hys(20)
        ctrl = d[3]
        self.assertEqual(ctrl[30:40].strip(), "1")           # Nload = 1
        self.assertEqual(ctrl[40:50].strip(), "0")           # Nunload = 0
        self.assertAlmostEqual(float(ctrl[60:80]), 2.5)      # Shape = SHAPE
        self.assertAlmostEqual(float(ctrl[80:100]), 0.4)     # Hys = HU
        self.assertEqual(d[4][0:10].strip(), "300")          # loading funcID = TBID

    def test_law70_is_flagged_approximate(self):
        self.assertTrue(any("FU_CHANG_FOAM 3" in w and "APPROXIMATE" in w
                            for w in self.result.warnings))

    def test_law28_direction_moduli_and_curves(self):
        d = self._law("/MAT/LAW28/4")
        # d: title, rho, E11/E22/E33, G12/G23/G31, funID11-33, Eps_max, funID12-31
        self.assertAlmostEqual(float(d[2][0:20]), 500.0)     # E_11 = EAAU
        self.assertAlmostEqual(float(d[2][20:40]), 600.0)    # E_22 = EBBU
        self.assertAlmostEqual(float(d[2][40:60]), 700.0)    # E_33 = ECCU
        self.assertAlmostEqual(float(d[3][0:20]), 250.0)     # G_12 = GABU
        normal = d[4]
        self.assertEqual(normal[0:10].strip(), "400")        # fun_ID11 = LCA
        self.assertEqual(normal[10:20].strip(), "401")       # fun_ID22 = LCB
        self.assertEqual(normal[20:30].strip(), "402")       # fun_ID33 = LCC
        self.assertAlmostEqual(float(normal[40:60]), 1.0)    # Fscale11
        shear = d[6]
        self.assertEqual(shear[0:10].strip(), "410")         # fun_ID12 = LCAB
        self.assertEqual(shear[10:20].strip(), "411")        # fun_ID23 = LCBC
        self.assertEqual(shear[20:30].strip(), "412")        # fun_ID31 = LCCA

    def test_law28_drops_compacted_fields(self):
        self.assertTrue(any("HONEYCOMB 4" in w and "70000" in w
                            for w in self.result.warnings))

    def test_referenced_curves_become_functions(self):
        for cid in (100, 200, 300, 400, 401, 402, 410):
            self.assertIn(f"/FUNCT/{cid}", self.starter)


if __name__ == "__main__":
    unittest.main()
