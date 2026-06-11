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
from k2rad.handlers import dispatch  # noqa: E402
from k2rad.state import ConversionState, CoordNodes, NodeData  # noqa: E402
from k2rad.writer import _skew_axes_from_nodes  # noqa: E402
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

    def test_fixpoint_written_every_ten_percent(self):
        # Auto /IMPL/DT/FIXPOINT makes the implicit time-step controller land
        # exactly on every 10% of the run end (endtim=1.0 here) so a clean
        # animation/TH state is produced at each milestone. We emit 10 points
        # 0.1*T … 1.0*T; the engine reads them free-format and sorts ascending.
        engine = self._engine_for(IMPL_QSTAT_K)
        self.assertIn("/IMPL/DT/FIXPOINT", engine)
        vals = self._fixpoints(engine)
        self.assertEqual([round(v, 10) for v in vals],
                         [round(0.1 * k, 10) for k in range(1, 11)])
        # Must sit inside the implicit block (before its terminating comment),
        # so /IMPL/DT/3 (RIKS, which would ignore it) is not in play — we use
        # /IMPL/DT/2.
        self.assertIn("/IMPL/DT/2", engine)
        self.assertNotIn("/IMPL/DT/3", engine)

    def test_fixpoint_scales_with_endtim(self):
        # The points track the actual termination time, not a hard-coded 1.0:
        # for a 10 s run the milestones are 1,2,…,10 s.
        deck = IMPL_QSTAT_K.replace("       1.0\n*END", "      10.0\n*END")
        vals = self._fixpoints(self._engine_for(deck))
        self.assertEqual([round(v, 6) for v in vals],
                         [float(k) for k in range(1, 11)])

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


# A single 10-node quadratic tet (LS-DYNA *ELEMENT_SOLID 10-node form: eid/pid on
# card 1, the 10 node IDs on card 2). Must become /TETRA10 keeping ALL 10 nodes —
# dropping the 6 mid-edge nodes would orphan them (zero-stiffness DOFs → singular
# implicit matrix), the bug that crashed the elevator-linkage run.
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


if __name__ == "__main__":
    unittest.main()
