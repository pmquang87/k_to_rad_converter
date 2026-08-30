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
from k2rad.state import (
    ConversionState, PartData, DiscreteElem, InitialVelocityGeneration,
)
from k2rad.writer.loads import (
    _inivel_gen_group_nodes, _box_global_corners, _resolve_box_nodes,
)


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
        # The tiebreak's PRE-failure state is a tie (Vol I R17 p.11-9), so the
        # record goes to contacts_tiebreak and the writer emits /INTER/TYPE2.
        # This deck has no Card 4 at all, so OPTION reads 0 — not a legal value,
        # which is itself named.
        state = _dispatch(self.DECK)
        self.assertEqual(len(state.contacts_surf2surf), 0)
        self.assertEqual(len(state.contacts_tiebreak), 1)
        self.assertNotIn(
            "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK", state.skipped_keywords)
        self.assertTrue(any("OPTION) reads 0" in w for w in state.warnings))


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


# ─────────────────────────────────────────────────────────────────────────────
# *INITIAL_VELOCITY (set form) and *INITIAL_VELOCITY_GENERATION
# ─────────────────────────────────────────────────────────────────────────────

# One deformable (MAT_ELASTIC) part of two quad shells over 8 nodes, plus two
# node sets: 9 = {1,2,3,4}, 10 = {3,4}. Node 5 sits at (2,0,0) so nodes 1→5 make
# a clean +X axis for the node-defined-axis generation test.
IV_MESH = (
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
    "partA\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2\n"
    "       1.0\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       1       5       6       7       8\n"
    "*SET_NODE_LIST\n"
    "         9\n"
    "         1         2         3         4\n"
    "*SET_NODE_LIST\n"
    "        10\n"
    "         3         4\n"
)
IV_TAIL = "*CONTROL_TERMINATION\n       1.0\n*END\n"


def _card10(*vals) -> str:
    """LS-DYNA fixed 10-column card from raw values."""
    return "".join(str(v).rjust(10) for v in vals)


def _hdr(starter: str, prefix: str):
    for ln in starter.splitlines():
        if ln.startswith(prefix):
            return ln.strip()
    return None


def _block(starter: str, header_exact):
    """Data lines (title first, comments/HDR/blank skipped) of the block whose
    header line equals *header_exact*, up to the next '/' header."""
    out, grab = [], False
    for ln in starter.splitlines():
        if not grab:
            if header_exact is not None and ln.strip() == header_exact:
                grab = True
        else:
            if ln.startswith("/"):
                break
            if ln.startswith("#") or not ln.strip():
                continue
            out.append(ln)
    return out


def _floats(line: str):
    return [float(x) for x in line.split()]


def _group_ids(starter: str, inivel_prefix: str, gnod_index: int):
    """Node ids of the /GRNOD referenced by the first /INIVEL block matching
    *inivel_prefix* (gnod_index = column of the group id on that block's first
    data card: 3 for TRA/ROT, 2 for the AXIS card A)."""
    card = _block(starter, _hdr(starter, inivel_prefix))[1].split()
    grp = _block(starter, "/GRNOD/NODE/" + card[gnod_index])
    ids = []
    for ln in grp[1:]:
        ids += [int(x) for x in ln.split()]
    return sorted(ids)


def _all_header_ids(starter: str, prefix: str):
    """Trailing ids of every header line starting with *prefix* (e.g. every
    '/INIVEL/AXIS/<id>' or '/FRAME/FIX/<id>')."""
    return [int(ln.strip().rsplit("/", 1)[1])
            for ln in starter.splitlines() if ln.startswith(prefix)]


class InitialVelocitySetFormTests(unittest.TestCase):
    def _deck(self, card1: str, card2: str) -> str:
        return IV_MESH + "*INITIAL_VELOCITY\n" + card1 + "\n" + card2 + "\n" + IV_TAIL

    def test_nsid_group_and_tra(self):
        _, s = self._convert_tra()
        self.assertIn("/INIVEL/TRA/", s)
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 2, 3, 4])
        # Vx = 5 on the TRA data card
        card = _block(s, _hdr(s, "/INIVEL/TRA/"))[1].split()
        self.assertAlmostEqual(float(card[0]), 5.0)

    def _convert_tra(self):
        deck = self._deck(_card10(9, 0, 0, 0, 0), _card10(5.0, 0.0, 0.0))
        return _convert(deck)

    def test_nsidex_exclusion(self):
        deck = self._deck(_card10(9, 10, 0, 0, 0), _card10(5.0, 0.0, 0.0))
        _, s = _convert(deck)
        # {1,2,3,4} minus {3,4} = {1,2}
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 2])

    def test_whole_model_zero_nsid(self):
        deck = self._deck(_card10(0, 0, 0, 0, 0), _card10(0.0, 3.0, 0.0))
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_whole_model_blank_card1(self):
        # Truly omitted NSID: a blank Card 1 (all defaults) → whole model.
        deck = IV_MESH + "*INITIAL_VELOCITY\n" + "\n" + _card10(0.0, 0.0, 4.0) + "\n" + IV_TAIL
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_rotational_emits_rot(self):
        deck = self._deck(_card10(9, 0, 0, 0, 0), _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.5))
        _, s = _convert(deck)
        self.assertIn("/INIVEL/ROT/", s)
        self.assertNotIn("/INIVEL/TRA/", s)   # no translational component
        card = _block(s, _hdr(s, "/INIVEL/ROT/"))[1].split()
        self.assertAlmostEqual(float(card[2]), 1.5)   # Vzr

    def test_boxid_undefined_warns_and_still_converts(self):
        # BOXID referencing a box the deck never defines → warn + apply to the
        # full node group (no scoping).
        deck = self._deck(_card10(9, 0, 7, 0, 0), _card10(5.0, 0.0, 0.0))
        res, s = _convert(deck)
        self.assertTrue(any("BOXID=7" in w and "no *DEFINE_BOX" in w
                            for w in res.warnings))
        self.assertIn("/INIVEL/TRA/", s)                       # converted anyway
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 2, 3, 4])  # full set

    def test_irigid_warns(self):
        deck = self._deck(_card10(9, 0, 0, 1, 0), _card10(5.0, 0.0, 0.0))
        res, _ = _convert(deck)
        self.assertTrue(any("IRIGID" in w for w in res.warnings))

    def test_icid_without_skew_warns_global(self):
        deck = self._deck(_card10(9, 0, 0, 0, 3), _card10(5.0, 0.0, 0.0))
        res, s = _convert(deck)
        self.assertTrue(any("ICID" in w and "GLOBAL" in w.upper() for w in res.warnings))
        card = _block(s, _hdr(s, "/INIVEL/TRA/"))[1].split()
        self.assertEqual(int(card[4]), 0)   # Skew_id = 0 (global)

    def test_icid_with_matching_skew_sets_skew(self):
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 "         3       0.0       0.0       0.0       1.0       0.0       0.0\n"
                 "       0.0       1.0       0.0\n")
        deck = (IV_MESH + coord + "*INITIAL_VELOCITY\n"
                + _card10(9, 0, 0, 0, 3) + "\n" + _card10(5.0, 0.0, 0.0) + "\n" + IV_TAIL)
        res, s = _convert(deck)
        card = _block(s, _hdr(s, "/INIVEL/TRA/"))[1].split()
        self.assertEqual(int(card[4]), 3)   # Skew_id = ICID (skew exists)
        self.assertTrue(any("/SKEW/3" in w for w in res.warnings))

    def test_icid_with_coordinate_vector_sets_skew(self):
        # ICID referencing a *DEFINE_COORDINATE_VECTOR (which emits /SKEW/FIX/cid)
        # must resolve to that skew, not fall through to the GLOBAL frame with a
        # false "no converted /SKEW" warning.
        coord = ("*DEFINE_COORDINATE_VECTOR\n"
                 + _card10(3, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0) + "\n")
        deck = (IV_MESH + coord + "*INITIAL_VELOCITY\n"
                + _card10(9, 0, 0, 0, 3) + "\n" + _card10(5.0, 0.0, 0.0) + "\n" + IV_TAIL)
        res, s = _convert(deck)
        card = _block(s, _hdr(s, "/INIVEL/TRA/"))[1].split()
        self.assertEqual(int(card[4]), 3)          # Skew_id = ICID (coord-vector skew)
        self.assertIn("/SKEW/FIX/3", s)            # the coord-vector skew was emitted
        self.assertTrue(any("/SKEW/3" in w for w in res.warnings))
        # the false "no converted /SKEW … GLOBAL frame" warning must NOT fire
        self.assertFalse(any("no converted /SKEW" in w for w in res.warnings))

    def test_zero_velocity_is_noop(self):
        deck = self._deck(_card10(9, 0, 0, 0, 0), _card10(0.0, 0.0, 0.0))
        _, s = _convert(deck)
        self.assertNotIn("/INIVEL/TRA/", s)
        self.assertNotIn("/INIVEL/ROT/", s)

    def test_handler_records_raw_fields(self):
        deck = self._deck(_card10(9, 10, 0, 0, 0), _card10(5.0, 0.0, 0.0, 0.0, 0.0, 1.5))
        st = _dispatch(deck)
        self.assertEqual(len(st.inivel_general), 1)
        iv = st.inivel_general[0]
        self.assertEqual((iv.nsid, iv.nsidex), (9, 10))
        self.assertAlmostEqual(iv.vx, 5.0)
        self.assertAlmostEqual(iv.vzr, 1.5)

    def test_bare_keyword_no_longer_skipped(self):
        deck = self._deck(_card10(9, 0, 0, 0, 0), _card10(5.0, 0.0, 0.0))
        st = _dispatch(deck)
        self.assertNotIn("INITIAL_VELOCITY", st.skipped_keywords)

    def test_two_base_blocks_distinct_ids(self):
        # Two *INITIAL_VELOCITY blocks in one deck must get unique /INIVEL ids
        # and their own /GRNOD groups (no shared state between blocks).
        deck = (IV_MESH
                + "*INITIAL_VELOCITY\n" + _card10(9, 0, 0, 0, 0) + "\n"
                + _card10(5.0, 0.0, 0.0) + "\n"
                + "*INITIAL_VELOCITY\n" + _card10(10, 0, 0, 0, 0) + "\n"
                + _card10(0.0, 6.0, 0.0) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        tra_ids = _all_header_ids(s, "/INIVEL/TRA/")
        self.assertEqual(len(tra_ids), 2)
        self.assertEqual(len(set(tra_ids)), 2)          # distinct
        # each block keeps its own node scope: set 9 = {1,2,3,4}, set 10 = {3,4}
        self.assertEqual(sorted(_all_header_ids(s, "/GRNOD/NODE/")),
                         sorted(set(_all_header_ids(s, "/GRNOD/NODE/"))))


class InitialVelocityGenerationTests(unittest.TestCase):
    def _deck(self, card1: str, card2: str) -> str:
        return (IV_MESH + "*INITIAL_VELOCITY_GENERATION\n"
                + card1 + "\n" + card2 + "\n" + IV_TAIL)

    def test_axis_global_z_translation_x(self):
        # STYP=2 part 1, OMEGA=5, VX=10; axis (0,0,1) through (1,2,3).
        deck = self._deck(_card10(1, 2, 5.0, 10.0, 0.0, 0.0, 0, 0),
                          _card10(1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 0, 0))
        _, s = _convert(deck)
        self.assertIn("/INIVEL/AXIS/", s)
        self.assertIn("/FRAME/FIX/", s)
        frame = _block(s, _hdr(s, "/FRAME/FIX/"))
        self.assertEqual(_floats(frame[1]), [1.0, 2.0, 3.0])     # origin
        self.assertEqual(_floats(frame[3]), [0.0, 0.0, 1.0])     # local Z = axis
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(axis[1].split()[0], "Z")                # DIR
        self.assertEqual(_floats(axis[2]), [10.0, 0.0, 0.0, 5.0])  # Vxt Vyt Vzt VR

    def test_axis_rotated_about_x(self):
        # Axis = global X, translate along global Y=10, OMEGA=5.  The projection
        # onto the frame's local axes must give Vyt = -10 (numeric axis check).
        deck = self._deck(_card10(0, 0, 5.0, 0.0, 10.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0, 0))
        _, s = _convert(deck)
        frame = _block(s, _hdr(s, "/FRAME/FIX/"))
        self.assertEqual(_floats(frame[3]), [1.0, 0.0, 0.0])     # local Z = (1,0,0)
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(_floats(axis[2]), [0.0, -10.0, 0.0, 5.0])

    def test_translational_only_no_omega(self):
        deck = self._deck(_card10(1, 2, 0.0, 7.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0))
        _, s = _convert(deck)
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(_floats(axis[2]), [7.0, 0.0, 0.0, 0.0])  # VR = 0

    def test_styp_node_set_scope(self):
        deck = self._deck(_card10(10, 3, 0.0, 1.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0))
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/AXIS/", 2), [3, 4])   # set 10

    def test_styp_part_scope(self):
        deck = self._deck(_card10(1, 2, 0.0, 1.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0))
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/AXIS/", 2), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_styp0_whole_model(self):
        deck = self._deck(_card10(0, 0, 0.0, 1.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0))
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/AXIS/", 2), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_node_defined_axis(self):
        # NX = -999 → NY/NZ are node ids 1 and 5; origin = node1 = (0,0,0),
        # axis = node5 - node1 = (2,0,0) → (1,0,0).
        deck = self._deck(_card10(0, 0, 0.0, 1.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, -999.0, 1, 5, 0, 0))
        _, s = _convert(deck)
        frame = _block(s, _hdr(s, "/FRAME/FIX/"))
        self.assertEqual(_floats(frame[1]), [0.0, 0.0, 0.0])   # origin = node 1
        self.assertEqual(_floats(frame[3]), [1.0, 0.0, 0.0])   # local Z = +X

    def test_phase_warns(self):
        deck = self._deck(_card10(1, 2, 5.0, 10.0, 0.0, 0.0, 0, 0),
                          _card10(1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 1, 0))
        res, _ = _convert(deck)
        self.assertTrue(any("PHASE" in w for w in res.warnings))

    def test_icid_generation_warns(self):
        deck = self._deck(_card10(1, 2, 5.0, 10.0, 0.0, 0.0, 0, 4),
                          _card10(1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 0, 0))
        res, _ = _convert(deck)
        self.assertTrue(any("ICID" in w for w in res.warnings))

    def test_generation_handler_records(self):
        deck = self._deck(_card10(1, 2, 5.0, 10.0, 0.0, 0.0, 0, 0),
                          _card10(1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 0, 0))
        st = _dispatch(deck)
        self.assertEqual(len(st.inivel_generations), 1)
        g = st.inivel_generations[0]
        self.assertEqual((g.sid, g.styp), (1, 2))
        self.assertAlmostEqual(g.omega, 5.0)
        self.assertAlmostEqual(g.nz, 1.0)

    def test_node_axis_handler_records(self):
        deck = self._deck(_card10(0, 0, 0.0, 1.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, -999.0, 1, 5, 0, 0))
        st = _dispatch(deck)
        g = st.inivel_generations[0]
        self.assertEqual((g.node1, g.node2), (1, 5))

    def test_styp_part_set_scope(self):
        # STYP=1 (part SET): set 20 = {part 1} → all of part 1's nodes {1..8}.
        setpart = "*SET_PART_LIST\n" + "        20\n" + "         1\n"
        deck = (IV_MESH + setpart + "*INITIAL_VELOCITY_GENERATION\n"
                + _card10(20, 1, 0.0, 1.0, 0.0, 0.0, 0, 0) + "\n"
                + _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/AXIS/", 2), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_icid_rotates_velocity_and_axis(self):
        # ICID=3 is a system with local X = global Y (a 90° spin about Z), so the
        # local VX=100 must re-express to GLOBAL (0,100,0): the /INIVEL/AXIS card
        # (projected onto the global-Z frame) must read Vyt=100, not Vxt=100.
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _card10(3, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0) + "\n"
                 + _card10(-1.0, 0.0, 0.0) + "\n")
        deck = (IV_MESH + coord + "*INITIAL_VELOCITY_GENERATION\n"
                + _card10(1, 2, 5.0, 100.0, 0.0, 0.0, 0, 3) + "\n"
                + _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0) + "\n" + IV_TAIL)
        res, s = _convert(deck)
        frame = _block(s, _hdr(s, "/FRAME/FIX/"))
        self.assertEqual(_floats(frame[3]), [0.0, 0.0, 1.0])       # axis stays global Z
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(_floats(axis[2]), [0.0, 100.0, 0.0, 5.0])  # rotated: Vyt=100
        self.assertTrue(any("/SKEW/3" in w and "rotated" in w for w in res.warnings))

    def test_icid_generation_coordinate_vector_rotates(self):
        # ICID=3 is a *DEFINE_COORDINATE_VECTOR whose local X = global Y and local
        # Z = global Z. VX=100 (local) must re-express to GLOBAL (0,100,0): the
        # /INIVEL/AXIS card (projected onto the global-Z frame) reads Vyt=100.
        coord = ("*DEFINE_COORDINATE_VECTOR\n"
                 + _card10(3, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0) + "\n")
        deck = (IV_MESH + coord + "*INITIAL_VELOCITY_GENERATION\n"
                + _card10(1, 2, 5.0, 100.0, 0.0, 0.0, 0, 3) + "\n"
                + _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0) + "\n" + IV_TAIL)
        res, s = _convert(deck)
        frame = _block(s, _hdr(s, "/FRAME/FIX/"))
        self.assertEqual(_floats(frame[3]), [0.0, 0.0, 1.0])        # axis stays global Z
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(_floats(axis[2]), [0.0, 100.0, 0.0, 5.0])  # rotated: Vyt=100
        self.assertTrue(any("/SKEW/3" in w and "rotated" in w for w in res.warnings))

    def test_icid_generation_no_skew_stays_global(self):
        # ICID with no converted /SKEW → warn + components used verbatim (global).
        deck = self._deck(_card10(1, 2, 5.0, 100.0, 0.0, 0.0, 0, 7),
                          _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0))
        res, s = _convert(deck)
        self.assertTrue(any("ICID=7" in w and "GLOBAL" in w.upper()
                            for w in res.warnings))
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(_floats(axis[2]), [100.0, 0.0, 0.0, 5.0])  # unrotated

    def test_zero_axis_with_omega_warns(self):
        # NX=NY=NZ=0 but OMEGA≠0 → axis undefined; OMEGA dropped, VR=0, translation
        # still applied.
        deck = self._deck(_card10(1, 2, 5.0, 3.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0))
        res, s = _convert(deck)
        self.assertTrue(any("no rotation axis" in w for w in res.warnings))
        axis = _block(s, _hdr(s, "/INIVEL/AXIS/"))
        self.assertEqual(_floats(axis[2])[3], 0.0)                 # VR = 0

    def test_node_axis_missing_node_warns(self):
        # Node-defined axis whose second node is absent → axis undefined + warn.
        deck = self._deck(_card10(0, 0, 0.0, 2.0, 0.0, 0.0, 0, 0),
                          _card10(0.0, 0.0, 0.0, -999.0, 1, 999, 0, 0))
        res, _ = _convert(deck)
        self.assertTrue(any("axis node" in w and "missing" in w
                            for w in res.warnings))

    def test_discrete_element_part_nodes(self):
        # STYP=2 on a part made of *ELEMENT_DISCRETE: the spring's nodes must be
        # collected (regression for the shell/solid/beam-only scan).
        st = ConversionState()
        st.parts = {2: PartData(2, "spring", 0, 0)}
        st.discrete_elems = [DiscreteElem(1, 2, 5, 6)]
        g = InitialVelocityGeneration(
            sid=2, styp=2, omega=0.0, vx=0.0, vy=0.0, vz=0.0, ivatn=0, icid=0,
            xc=0.0, yc=0.0, zc=0.0, nx=0.0, ny=0.0, nz=1.0, node1=0, node2=0,
            phase=0, irigid=0)
        self.assertEqual(_inivel_gen_group_nodes(st, g), [5, 6])

    def test_two_generations_distinct_ids(self):
        # Two generation blocks → two distinct frames and two distinct axis cards.
        g1 = ("*INITIAL_VELOCITY_GENERATION\n"
              + _card10(1, 2, 5.0, 10.0, 0.0, 0.0, 0, 0) + "\n"
              + _card10(1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 0, 0) + "\n")
        g2 = ("*INITIAL_VELOCITY_GENERATION\n"
              + _card10(10, 3, 0.0, 0.0, 7.0, 0.0, 0, 0) + "\n"
              + _card10(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0, 0) + "\n")
        _, s = _convert(IV_MESH + g1 + g2 + IV_TAIL)
        frames = _all_header_ids(s, "/FRAME/FIX/")
        axes = _all_header_ids(s, "/INIVEL/AXIS/")
        self.assertEqual(len(frames), 2)
        self.assertEqual(len(set(frames)), 2)
        self.assertEqual(len(set(axes)), 2)

    def test_frame_id_avoids_skew_collision(self):
        # A *DEFINE_COORDINATE_SYSTEM with cid in the auto-id range (90001) must
        # not collide with a synthesized /FRAME id (shared /SKEW+/FRAME namespace →
        # starter ERROR 79). The frame must take some other id.
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _card10(90001, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _card10(0.0, 1.0, 0.0) + "\n")
        deck = (IV_MESH + coord + "*INITIAL_VELOCITY_GENERATION\n"
                + _card10(1, 2, 0.0, 1.0, 0.0, 0.0, 0, 0) + "\n"
                + _card10(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        self.assertIn("/SKEW/FIX/90001", s)
        self.assertNotIn("/FRAME/FIX/90001", s)      # frame dodged the skew id
        self.assertTrue(_all_header_ids(s, "/FRAME/FIX/"))  # a frame was emitted

    def test_generation_start_time_stays_skipped(self):
        deck = (IV_MESH + "*INITIAL_VELOCITY_GENERATION_START_TIME\n"
                + "       0.1\n" + IV_TAIL)
        st = _dispatch(deck)
        self.assertIn("INITIAL_VELOCITY_GENERATION_START_TIME", st.skipped_keywords)
        self.assertEqual(len(st.inivel_generations), 0)


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_BOX / *DEFINE_BOX_LOCAL (numeric node-membership scoping)
# ─────────────────────────────────────────────────────────────────────────────

def _rwall_grnod_ids(starter: str):
    """Node ids of the /GRNOD referenced as grnd_ID1 by the first /RWALL block."""
    hdr = _hdr(starter, "/RWALL/PLANE/")
    card = _block(starter, hdr)[1].split()      # node_ID Slide grnd_ID1 grnd_ID2 d
    grnd1 = card[2]
    if grnd1 == "0":
        return None
    grp = _block(starter, "/GRNOD/NODE/" + grnd1)
    ids = []
    for ln in grp[1:]:
        ids += [int(x) for x in ln.split()]
    return sorted(ids)


class DefineBoxTests(unittest.TestCase):
    # box 7 (global, axis-aligned): x∈[-0.5,0.5], y∈[-0.5,1.5], z∈[-0.5,0.5]
    # → of the mesh, contains nodes 1 (0,0,0) and 4 (0,1,0).
    BOX = ("*DEFINE_BOX\n"
           + _card10(7, -0.5, 0.5, -0.5, 1.5, -0.5, 0.5) + "\n")

    def test_handler_records_extents(self):
        st = _dispatch(IV_MESH + self.BOX + IV_TAIL)
        self.assertIn(7, st.boxes)
        box = st.boxes[7]
        self.assertAlmostEqual(box.xmn, -0.5)
        self.assertAlmostEqual(box.xmx, 0.5)
        self.assertAlmostEqual(box.ymx, 1.5)
        self.assertFalse(box.local)

    def test_box_scopes_inivel(self):
        deck = (IV_MESH + self.BOX + "*INITIAL_VELOCITY\n"
                + _card10(9, 0, 7, 0, 0) + "\n" + _card10(5.0, 0.0, 0.0)
                + "\n" + IV_TAIL)
        res, s = _convert(deck)
        # set 9 = {1,2,3,4}; ∩ box 7 = {1,4}
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 4])
        self.assertTrue(any("BOXID=7" in w and "scoped" in w
                            for w in res.warnings))

    def test_box_scopes_whole_model(self):
        # NSID=0 (whole model) ∩ box 7 = {1,4} of all 8 nodes.
        deck = (IV_MESH + self.BOX + "*INITIAL_VELOCITY\n"
                + _card10(0, 0, 7, 0, 0) + "\n" + _card10(5.0, 0.0, 0.0)
                + "\n" + IV_TAIL)
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 4])

    def test_local_corner_transform(self):
        # _LOCAL box: local extents [0,1]^3, local X = global Y, in-plane V =
        # global Z (so local Z = X×V = global X, local Y = global Z), origin
        # (10,0,0). Corner P1 = origin; P2 = origin + eX + eY + eZ = (11,1,1).
        deck = (IV_MESH + "*DEFINE_BOX_LOCAL\n"
                + _card10(7, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0) + "\n"
                + _card10(0.0, 1.0, 0.0, 0.0, 0.0, 1.0) + "\n"
                + _card10(10.0, 0.0, 0.0) + "\n" + IV_TAIL)
        st = _dispatch(deck)
        box = st.boxes[7]
        self.assertTrue(box.local)
        p1, p2 = _box_global_corners(box)
        self.assertEqual([round(v, 6) for v in p1], [10.0, 0.0, 0.0])
        self.assertEqual([round(v, 6) for v in p2], [11.0, 1.0, 1.0])

    def test_local_membership(self):
        # _LOCAL box, origin (0,0,0), local X = global Y, in-plane V = global Z
        # → local Z = global X, local Y = global Z. Extents select global-Y in
        # [0.5,1.5], global-Z in [-0.5,0.5], global-X in [-0.5,1.5]:
        # nodes 3 (1,1,0) and 4 (0,1,0). set 9 ∩ box = {3,4}.
        deck = (IV_MESH + "*DEFINE_BOX_LOCAL\n"
                + _card10(7, 0.5, 1.5, -0.5, 0.5, -0.5, 1.5) + "\n"
                + _card10(0.0, 1.0, 0.0, 0.0, 0.0, 1.0) + "\n"
                + _card10(0.0, 0.0, 0.0) + "\n"
                + "*INITIAL_VELOCITY\n" + _card10(9, 0, 7, 0, 0) + "\n"
                + _card10(5.0, 0.0, 0.0) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [3, 4])

    def test_empty_box_scopes_to_nothing(self):
        # A box far from every node → the group becomes empty → skipped + warn.
        far = "*DEFINE_BOX\n" + _card10(7, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0) + "\n"
        deck = (IV_MESH + far + "*INITIAL_VELOCITY\n"
                + _card10(9, 0, 7, 0, 0) + "\n" + _card10(5.0, 0.0, 0.0)
                + "\n" + IV_TAIL)
        _, s = _convert(deck)
        self.assertNotIn("/INIVEL/TRA/", s)     # empty group → nothing emitted

    def test_two_boxes_selected_independently(self):
        # Two boxes in one deck resolve to disjoint node sets, each on its own id.
        box7 = "*DEFINE_BOX\n" + _card10(7, -0.5, 0.5, -0.5, 1.5, -0.5, 0.5) + "\n"
        box8 = "*DEFINE_BOX\n" + _card10(8, 1.5, 3.5, -0.5, 1.5, -0.5, 0.5) + "\n"
        st = _dispatch(IV_MESH + box7 + box8 + IV_TAIL)
        self.assertEqual(sorted(_resolve_box_nodes(st, 7, "b7")), [1, 4])
        self.assertEqual(sorted(_resolve_box_nodes(st, 8, "b8")), [5, 6, 7, 8])

    def test_node_on_box_face_is_inclusive(self):
        # Node 2 at (1,0,0) lies exactly on the x=1.0 max face → inclusive → in.
        onface = "*DEFINE_BOX\n" + _card10(7, 0.25, 1.0, -0.5, 0.5, -0.5, 0.5) + "\n"
        st = _dispatch(IV_MESH + onface + IV_TAIL)
        self.assertEqual(sorted(_resolve_box_nodes(st, 7, "face")), [2])

    def test_degenerate_local_box_falls_back_to_full_group(self):
        # _LOCAL box with X ∥ V (both +Y) → degenerate frame → _resolve_box_nodes
        # returns None → the consumer applies to the FULL node group + warns.
        bad = ("*DEFINE_BOX_LOCAL\n"
               + _card10(7, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0) + "\n"
               + _card10(0.0, 1.0, 0.0, 0.0, 1.0, 0.0) + "\n"    # X=(0,1,0) ∥ V=(0,1,0)
               + _card10(0.0, 0.0, 0.0) + "\n")
        deck = (IV_MESH + bad + "*INITIAL_VELOCITY\n"
                + _card10(9, 0, 7, 0, 0) + "\n" + _card10(5.0, 0.0, 0.0)
                + "\n" + IV_TAIL)
        res, s = _convert(deck)
        self.assertIsNone(_resolve_box_nodes(_dispatch(IV_MESH + bad + IV_TAIL),
                                             7, "b7"))
        self.assertEqual(_group_ids(s, "/INIVEL/TRA/", 3), [1, 2, 3, 4])  # full set 9
        self.assertTrue(any("degenerate local" in w for w in res.warnings))


class RigidWallBoxTests(unittest.TestCase):
    BOX = ("*DEFINE_BOX\n"
           + _card10(7, -0.5, 0.5, -0.5, 1.5, -0.5, 0.5) + "\n")   # {1,4}
    WALL_BOX = ("*RIGIDWALL_PLANAR\n"
                + _card10(0, 0, 7) + "\n"
                + _card10(0.0, 0.0, 1.0, 0.0, 0.0, 2.0) + "\n")
    WALL_NSID_BOX = ("*RIGIDWALL_PLANAR\n"
                     + _card10(9, 0, 7) + "\n"
                     + _card10(0.0, 0.0, 1.0, 0.0, 0.0, 2.0) + "\n")

    def test_boxid_scopes_tracked_nodes(self):
        res, s = _convert(IV_MESH + self.BOX + self.WALL_BOX + IV_TAIL)
        self.assertEqual(_rwall_grnod_ids(s), [1, 4])
        self.assertTrue(any("*DEFINE_BOX 7" in w and "scoped" in w
                            for w in res.warnings))

    def test_boxid_dropped_when_nsid_present(self):
        # NSID=9 AND BOXID=7 → dyna2rad drops the box; the wall tracks set 9.
        res, s = _convert(IV_MESH + self.BOX + self.WALL_NSID_BOX + IV_TAIL)
        self.assertEqual(_rwall_grnod_ids(s), [1, 2, 3, 4])
        self.assertTrue(any("BOXID dropped" in w for w in res.warnings))

    def test_empty_boxid_wall_is_inactive_and_skipped(self):
        # A box-only wall whose *DEFINE_BOX encloses no node = no slave nodes =
        # inactive wall (LS-DYNA). It must be skipped, NOT fall back to tracking
        # ALL nodes (grnd_ID1=0 distance search over the whole model).
        far = "*DEFINE_BOX\n" + _card10(7, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0) + "\n"
        res, s = _convert(IV_MESH + far + self.WALL_BOX + IV_TAIL)
        self.assertNotIn("/RWALL/", s)          # inactive wall not emitted
        self.assertTrue(any("inactive" in w and "*DEFINE_BOX 7" in w
                            for w in res.warnings))


class ContactBoxWarnTests(unittest.TestCase):
    def test_sboxid_warns_loudly(self):
        contact = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                   + _card10(0, 0, 0, 0, 7) + "\n"      # sboxid = field 5 = 7
                   + _card10(0.1, 0.1) + "\n")
        res, _ = _convert(IV_MESH + contact + IV_TAIL)
        self.assertTrue(any("SBOXID/MBOXID" in w and "NOT converted" in w
                            for w in res.warnings))

    def test_force_transducer_box_warns_loudly(self):
        # The ONE contact where dyna2rad DOES honour the box; k2rad cannot map it
        # onto a surface, so it must warn loudly rather than drop it silently.
        contact = ("*CONTACT_FORCE_TRANSDUCER_PENALTY\n"
                   + _card10(0, 0, 0, 0, 7) + "\n")     # saboxid = field 5 = 7
        st = _dispatch(IV_MESH + contact + IV_TAIL)
        self.assertTrue(any("SABOXID/SBBOXID" in w and "NOT converted" in w
                            for w in st.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_COORDINATE_VECTOR / *DEFINE_VECTOR / *DEFINE_VECTOR_NODES → /SKEW
# ─────────────────────────────────────────────────────────────────────────────

class DefineCoordinateVectorTests(unittest.TestCase):
    def test_handler_records(self):
        deck = (IV_MESH + "*DEFINE_COORDINATE_VECTOR\n"
                + _card10(3, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0) + "\n" + IV_TAIL)
        st = _dispatch(deck)
        self.assertIn(3, st.coord_vectors)
        cv = st.coord_vectors[3]
        self.assertEqual((cv.xx, cv.yx, cv.zx), (0.0, 0.0, 1.0))
        self.assertEqual((cv.xv, cv.yv, cv.zv), (1.0, 0.0, 0.0))

    def test_skew_axes_math(self):
        # local X = (0,0,1); local Z = X×V = (0,0,1)×(1,0,0) = (0,1,0);
        # local Y = Z×X = (0,1,0)×(0,0,1) = (1,0,0). The /SKEW/FIX cards carry
        # Y' then Z'.
        deck = (IV_MESH + "*DEFINE_COORDINATE_VECTOR\n"
                + _card10(3, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        blk = _block(s, "/SKEW/FIX/3")
        self.assertEqual(_floats(blk[1]), [0.0, 0.0, 0.0])     # origin
        self.assertEqual(_floats(blk[2]), [1.0, 0.0, 0.0])     # Y'
        self.assertEqual(_floats(blk[3]), [0.0, 1.0, 0.0])     # Z'

    def test_replaces_handle_skip(self):
        deck = (IV_MESH + "*DEFINE_COORDINATE_VECTOR\n"
                + _card10(3, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0) + "\n" + IV_TAIL)
        st = _dispatch(deck)
        self.assertNotIn("DEFINE_COORDINATE_VECTOR", st.skipped_keywords)


class DefineVectorTests(unittest.TestCase):
    def test_value_form_handler_records(self):
        deck = (IV_MESH + "*DEFINE_VECTOR\n"
                + _card10(5, 1.0, 2.0, 3.0, 1.0, 2.0, 5.0) + "\n" + IV_TAIL)
        st = _dispatch(deck)
        dv = st.define_vectors[5]
        self.assertFalse(dv.is_nodes)
        self.assertEqual((dv.xt, dv.yt, dv.zt), (1.0, 2.0, 3.0))
        self.assertEqual((dv.xh, dv.yh, dv.zh), (1.0, 2.0, 5.0))

    def test_value_form_skew_fix(self):
        # tail (1,2,3) → head (1,2,5): direction (0,0,1). /SKEW/FIX at the tail,
        # local Z' = (1,0,0) and X' (rebuilt Y'×Z') = the tail→head direction.
        deck = (IV_MESH + "*DEFINE_VECTOR\n"
                + _card10(5, 1.0, 2.0, 3.0, 1.0, 2.0, 5.0) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        blk = _block(s, "/SKEW/FIX/5")
        self.assertEqual(_floats(blk[1]), [1.0, 2.0, 3.0])     # origin = tail
        yv, zv = _floats(blk[2]), _floats(blk[3])
        # rebuilt X' = Y' × Z' must be the tail→head unit direction (0,0,1)
        xr = (yv[1] * zv[2] - yv[2] * zv[1],
              yv[2] * zv[0] - yv[0] * zv[2],
              yv[0] * zv[1] - yv[1] * zv[0])
        self.assertEqual([round(v, 6) for v in xr], [0.0, 0.0, 1.0])

    def test_nodes_form_skew_mov(self):
        # VID 6, tail node 1 (0,0,0), head node 5 (2,0,0) → /SKEW/MOV N1=1 N2=5.
        deck = (IV_MESH + "*DEFINE_VECTOR_NODES\n"
                + _card10(6, 1, 5) + "\n" + IV_TAIL)
        _, s = _convert(deck)
        blk = _block(s, "/SKEW/MOV/6")
        card = blk[1].split()                       # n1 n2 n3 Dir
        self.assertEqual(card[0], "1")
        self.assertEqual(card[1], "5")
        self.assertEqual(card[3], "X")
        self.assertGreater(int(card[2]), 8)          # synthesized third node

    def test_nodes_form_handler_records(self):
        deck = (IV_MESH + "*DEFINE_VECTOR_NODES\n"
                + _card10(6, 1, 5) + "\n" + IV_TAIL)
        st = _dispatch(deck)
        dv = st.define_vectors[6]
        self.assertTrue(dv.is_nodes)
        self.assertEqual((dv.nodet, dv.nodeh), (1, 5))

    def test_coord_cid_and_vector_vid_id_collision(self):
        # A *DEFINE_COORDINATE_SYSTEM cid=5 and a *DEFINE_VECTOR vid=5 share id 5
        # across two disjoint LS-DYNA id spaces. /SKEW and /FRAME share ONE starter
        # namespace, so the coord keeps /SKEW/FIX/5 and the vector's skew must dodge
        # to a fresh reserved id (>=90001) — never a duplicate /SKEW/FIX/5.
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _card10(5, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _card10(0.0, 1.0, 0.0) + "\n")
        vec = "*DEFINE_VECTOR\n" + _card10(5, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + "\n"
        _, s = _convert(IV_MESH + coord + vec + IV_TAIL)
        skew_ids = _all_header_ids(s, "/SKEW/FIX/")
        self.assertEqual(skew_ids.count(5), 1)            # coord keeps id 5, no dup
        self.assertTrue(any(i >= 90001 for i in skew_ids))  # vector dodged the collision

    def test_unreferenced_vector_skew_warns_about_dead_output(self):
        # *DEFINE_VECTOR_NODES has no k2rad consumer; the injected /SKEW/MOV helper
        # node must be surfaced so it is not a silent surprise.
        deck = (IV_MESH + "*DEFINE_VECTOR_NODES\n"
                + _card10(6, 1, 5) + "\n" + IV_TAIL)
        res, _ = _convert(deck)
        self.assertTrue(any("Unreferenced /SKEW" in w
                            and "injected a free helper node" in w
                            for w in res.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# *DEFINE_SD_ORIENTATION + oriented *ELEMENT_DISCRETE (VID)
# ─────────────────────────────────────────────────────────────────────────────

# One discrete spring (nodes 1-2) whose *ELEMENT_DISCRETE carries VID=4.
SD_SPRING = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "*PART\n"
    "spring\n"
    "         1         1         1\n"
    "*SECTION_DISCRETE\n"
    "         1         0\n"
    "*MAT_SPRING_ELASTIC\n"
    "         1     250.0\n"
    "{ORIENT}"
    "*ELEMENT_DISCRETE\n"
    "       1       1       1       2       4\n"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


class SdOrientationTests(unittest.TestCase):
    def test_handler_records(self):
        deck = SD_SPRING.replace(
            "{ORIENT}", "*DEFINE_SD_ORIENTATION\n" + _card10(4, 0, 1.0, 0.0, 0.0) + "\n")
        st = _dispatch(deck)
        so = st.sd_orientations[4]
        self.assertEqual(so.iop, 0)
        self.assertEqual((so.xt, so.yt, so.zt), (1.0, 0.0, 0.0))

    def test_iop0_oriented_spring_type8(self):
        deck = SD_SPRING.replace(
            "{ORIENT}", "*DEFINE_SD_ORIENTATION\n" + _card10(4, 0, 1.0, 0.0, 0.0) + "\n")
        res, s = _convert(deck)
        self.assertIn("/PROP/TYPE8/", s)                 # oriented → SPR_GENE
        self.assertNotIn("/PROP/TYPE4/", s)              # not the axial path
        skew_ids = _all_header_ids(s, "/SKEW/FIX/")
        self.assertEqual(len(skew_ids), 1)
        # TYPE8 card 1 field 3 = skew_ID must be the emitted /SKEW/FIX id
        card1 = _block(s, _hdr(s, "/PROP/TYPE8/"))[1].split()
        self.assertEqual(int(card1[2]), skew_ids[0])
        self.assertIn("/SPRING/", s)
        self.assertTrue(any("oriented by *DEFINE_SD_ORIENTATION VID=4" in w
                            for w in res.warnings))

    def test_iop0_skew_x_aligns_with_orientation(self):
        # IOP=0 direction (1,0,0): the skew's rebuilt X' = Y'×Z' must be (1,0,0).
        deck = SD_SPRING.replace(
            "{ORIENT}", "*DEFINE_SD_ORIENTATION\n" + _card10(4, 0, 1.0, 0.0, 0.0) + "\n")
        _, s = _convert(deck)
        hdr = _hdr(s, "/SKEW/FIX/")
        blk = _block(s, hdr)
        yv, zv = _floats(blk[2]), _floats(blk[3])
        xr = (yv[1] * zv[2] - yv[2] * zv[1],
              yv[2] * zv[0] - yv[0] * zv[2],
              yv[0] * zv[1] - yv[1] * zv[0])
        self.assertEqual([round(v, 6) for v in xr], [1.0, 0.0, 0.0])

    def test_iop2_skew_mov(self):
        deck = SD_SPRING.replace(
            "{ORIENT}", "*DEFINE_SD_ORIENTATION\n" + _card10(4, 2, 0.0, 0.0, 0.0, 1, 2) + "\n")
        res, s = _convert(deck)
        self.assertIn("/SKEW/MOV/", s)
        self.assertIn("/PROP/TYPE8/", s)
        mov = _block(s, _hdr(s, "/SKEW/MOV/"))[1].split()
        self.assertEqual((mov[0], mov[1]), ("1", "2"))    # N1→N2 = node pair

    def test_iop1_warns_and_element_not_converted(self):
        deck = SD_SPRING.replace(
            "{ORIENT}", "*DEFINE_SD_ORIENTATION\n" + _card10(4, 1, 1.0, 0.0, 0.0) + "\n")
        res, s = _convert(deck)
        self.assertTrue(any("IOP=1" in w for w in res.warnings))
        self.assertNotIn("/PROP/TYPE8/", s)               # not converted
        self.assertNotIn("/SPRING/", s)
        self.assertTrue(any("NOT converted" in w and "DEFINE_SD_ORIENTATION" in w
                            for w in res.warnings))

    def test_undefined_vid_still_skips(self):
        # No *DEFINE_SD_ORIENTATION at all → the VID can't resolve → warn + skip.
        deck = SD_SPRING.replace("{ORIENT}", "")
        res, s = _convert(deck)
        self.assertNotIn("/SPRING/", s)
        self.assertTrue(any("DEFINE_SD_ORIENTATION" in w and "NOT converted" in w
                            for w in res.warnings))

    def test_mixed_axial_and_oriented_springs_on_one_part(self):
        # One part carrying an axial (VID=0 → /PROP/TYPE4) and an oriented
        # (VID=4 → /PROP/TYPE8) discrete element. Both must convert, and the two
        # groups must land on distinct part ids (shared _alloc_part_id sequencing
        # across the TYPE4 and TYPE8 loops — no id collision, nothing dropped).
        deck = (
            "*KEYWORD\n"
            "*NODE\n"
            "       1             0.0             0.0             0.0\n"
            "       2             1.0             0.0             0.0\n"
            "       3             2.0             0.0             0.0\n"
            "*PART\n"
            "springs\n"
            "         1         1         1\n"
            "*SECTION_DISCRETE\n"
            "         1         0\n"
            "*MAT_SPRING_ELASTIC\n"
            "         1     250.0\n"
            "*DEFINE_SD_ORIENTATION\n" + _card10(4, 0, 0.0, 1.0, 0.0) + "\n"
            + "*ELEMENT_DISCRETE\n"
            "       1       1       1       2       0\n"   # axial (VID=0)
            "       2       1       2       3       4\n"   # oriented (VID=4)
            "*CONTROL_TERMINATION\n"
            "       1.0\n"
            "*END\n"
        )
        _, s = _convert(deck)
        self.assertIn("/PROP/TYPE4/", s)                 # axial spring
        self.assertIn("/PROP/TYPE8/", s)                 # oriented spring
        self.assertIn("/SKEW/FIX/", s)                   # the orientation skew
        self.assertEqual(s.count("/SPRING/"), 2)         # both springs, none dropped
        spring_ids = _all_header_ids(s, "/SPRING/")
        self.assertEqual(len(set(spring_ids)), 2)        # distinct part ids, no collision


# ─────────────────────────────────────────────────────────────────────────────
# *CONTACT_AUTOMATIC_GENERAL — dyna2rad SOFT-sentinel routing
#   (SOFT -7 → TYPE7, -11 → TYPE11 edge, -19 → TYPE19, else → single-surface)
# ─────────────────────────────────────────────────────────────────────────────

# Minimal single-shell deck; a contact block is spliced in before *CONTROL.
_GEN_MESH = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2            10.0             0.0             0.0\n"
    "       3            10.0            10.0             0.0\n"
    "       4             0.0            10.0             0.0\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "*PART\n"
    "plate\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2       1.0         3\n"
    "       2.0\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9    210000.0      0.3\n"
)
_GEN_TAIL = "*CONTROL_TERMINATION\n       1.0\n*END\n"


def _general_contact(soft, ssid=1, sstyp=3, fs=0.1, sst=0.0, mst=0.0):
    """A *CONTACT_AUTOMATIC_GENERAL_ID block (id 50). ``soft`` None → no Card A."""
    soft_card = f"{soft:>10}\n" if soft is not None else ""
    return (
        "*CONTACT_AUTOMATIC_GENERAL_ID\n"
        "        50                                                          gen\n"
        f"{ssid:>10}{0:>10}{sstyp:>10}{0:>10}         0         0         0         0\n"
        f"{fs:>10}{fs:>10}       0.0       0.0       0.0         0       0.01.0000E+28\n"
        f"       1.0       1.0{sst:>10}{mst:>10}       1.0       1.0       1.0       1.0\n"
        + soft_card
    )


def _inter_card1_floats(starter: str, type_prefix: str):
    """First data card (after the title) of the first /INTER/<type> block."""
    hdr = _hdr(starter, type_prefix)
    body = _block(starter, hdr)          # [title, card1, card2, …]
    return body[0], _floats(body[1])     # (title, card1 numeric fields)


def _num_row(line: str):
    """Parse a line into floats, or [] if any field is non-numeric (e.g. the
    interface title line, which _block includes as a data row)."""
    try:
        return [float(x) for x in line.split()]
    except ValueError:
        return []


class AutomaticGeneralSoftRoutingTests(unittest.TestCase):
    """SOFT-sentinel routing of *CONTACT_AUTOMATIC_GENERAL."""

    def test_general_is_handled_not_skipped(self):
        _, s = _convert(_GEN_MESH + _general_contact(-11) + _GEN_TAIL)
        state = _dispatch(_GEN_MESH + _general_contact(-11) + _GEN_TAIL)
        self.assertNotIn("CONTACT_AUTOMATIC_GENERAL", state.skipped_keywords)

    def test_soft_minus7_routes_to_type7(self):
        _, s = _convert(_GEN_MESH + _general_contact(-7) + _GEN_TAIL)
        self.assertIn("/INTER/TYPE7/50", s)
        self.assertNotIn("/INTER/TYPE11/", s)
        self.assertNotIn("/INTER/TYPE19/", s)

    def test_soft_minus11_routes_to_type11(self):
        _, s = _convert(_GEN_MESH + _general_contact(-11) + _GEN_TAIL)
        self.assertIn("/INTER/TYPE11/50", s)
        self.assertNotIn("/INTER/TYPE7/50", s)

    def test_soft_minus19_routes_to_type19(self):
        _, s = _convert(_GEN_MESH + _general_contact(-19) + _GEN_TAIL)
        self.assertIn("/INTER/TYPE19/50", s)
        self.assertNotIn("/INTER/TYPE11/", s)

    def test_soft_minus11_synthesizes_and_references_a_line(self):
        # THE key TYPE11 capability: a /LINE group is synthesized and the
        # interface's line_IDs field references it.
        _, s = _convert(_GEN_MESH + _general_contact(-11) + _GEN_TAIL)
        self.assertIn("/LINE/", s)                       # a line entity exists
        _, card1 = _inter_card1_floats(s, "/INTER/TYPE11/")
        line_ids = int(card1[0])
        self.assertIn(line_ids, _all_header_ids(s, "/LINE/"))   # referenced by the interface

    def test_soft_minus11_part_side_uses_line_surf_over_a_surface(self):
        # A part-resolved side builds a /SURF and wraps it in /LINE/SURF so the
        # starter derives the edges (no hand-enumerated node pairs).
        _, s = _convert(_GEN_MESH + _general_contact(-11, ssid=1, sstyp=3) + _GEN_TAIL)
        self.assertIn("/LINE/SURF/", s)
        self.assertIn("/SURF/GRSHEL/", s)               # the surface the line derives edges from

    def test_soft_minus11_self_contact_sets_line_idm_zero(self):
        # msid==0 → self edge-impact; line_IDm must be 0 (starter reads it as
        # self-contact of line_IDs).
        _, s = _convert(_GEN_MESH + _general_contact(-11) + _GEN_TAIL)
        _, card1 = _inter_card1_floats(s, "/INTER/TYPE11/")
        self.assertEqual(int(card1[1]), 0)              # line_IDm == 0

    def test_soft_minus11_segment_set_emits_line_seg_edges(self):
        # A *SET_SEGMENT slave (sstyp=0) is turned into an explicit /LINE/SEG
        # whose rows are the segment's consecutive node-pair edges.
        deck = (
            _GEN_MESH
            + "*SET_SEGMENT_TITLE\ngenseg\n       200\n"
              "         1         2         3         4\n"
            + "*CONTACT_AUTOMATIC_GENERAL_ID\n"
              "        50                                                          gen\n"
              "       200         0         0         0         0         0         0         0\n"
              "       0.1       0.1       0.0       0.0       0.0         0       0.01.0000E+28\n"
              "       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0\n"
              "       -11\n"
            + _GEN_TAIL
        )
        _, s = _convert(deck)
        self.assertIn("/LINE/SEG/", s)
        self.assertIn("/INTER/TYPE11/50", s)
        # The quad [1,2,3,4] → 4 boundary edges (1-2, 2-3, 3-4, 4-1).
        seg_block = _block(s, _hdr(s, "/LINE/SEG/"))
        edge_rows = [ln for ln in seg_block if len(ln.split()) == 3 and ln.split()[0].isdigit()
                     and ln.strip()[0] != "g"]          # skip the title line
        # each row is "seg_ID n1 n2"; the four unordered pairs must all appear
        pairs = {tuple(sorted(int(x) for x in r.split()[1:3])) for r in edge_rows}
        self.assertEqual(pairs, {(1, 2), (2, 3), (3, 4), (1, 4)})

    def test_soft_minus11_friction_passes_through(self):
        # Card2 FS → scalar Coulomb Fric on the TYPE11 Stfac/Fric/GAPmin card.
        _, s = _convert(_GEN_MESH + _general_contact(-11, fs=0.1) + _GEN_TAIL)
        body = _block(s, _hdr(s, "/INTER/TYPE11/"))
        # find the Stfac/Fric/GAPmin/Tstart/Tstop card (five floats, Fric second)
        card = next(r for ln in body if len(r := _num_row(ln)) == 5)
        self.assertEqual(card[1], 0.1)                  # Fric == FS

    def test_soft_minus11_sst_mst_map_to_gapmin(self):
        # Card3 SST/MST → TYPE11 GAPmin = (|SST|+|MST|)/2.
        res, s = _convert(_GEN_MESH + _general_contact(-11, sst=0.02, mst=0.04) + _GEN_TAIL)
        body = _block(s, _hdr(s, "/INTER/TYPE11/"))
        card = next(r for ln in body if len(r := _num_row(ln)) == 5)
        self.assertEqual(card[2], 0.03)                 # GAPmin third field
        self.assertTrue(any("Gapmin=0.03" in w and "TYPE11" in w for w in res.warnings))

    def test_default_soft_delegates_to_single_surface(self):
        # SOFT absent / 0 / 2 → the ordinary single-surface path (a specific-part
        # self contact resolves to /INTER/TYPE7), and NOT the general list.
        for soft in (None, 0, 2):
            res, s = _convert(_GEN_MESH + _general_contact(soft) + _GEN_TAIL)
            self.assertIn("/INTER/TYPE7/50", s, f"soft={soft}")
            self.assertNotIn("/INTER/TYPE11/", s)
            self.assertNotIn("/INTER/TYPE19/", s)
            self.assertNotIn("/LINE/", s)
            st = _dispatch(_GEN_MESH + _general_contact(soft) + _GEN_TAIL)
            self.assertEqual(st.contacts_general, [])           # not sentinel-routed
            self.assertEqual(len(st.contacts_single), 1)        # single-surface record

    def test_sentinel_recorded_in_contacts_general(self):
        st = _dispatch(_GEN_MESH + _general_contact(-11) + _GEN_TAIL)
        self.assertEqual(len(st.contacts_general), 1)
        c = st.contacts_general[0]
        self.assertEqual(c.soft, -11)
        self.assertEqual(c.ssid, 1)
        # self-mirror applied: msid == ssid when the card's MSID was 0
        self.assertEqual(c.msid, 1)


# ─────────────────────────────────────────────────────────────────────────────
# *CONTACT_TIED_SURFACE_TO_SURFACE — negative-gap discriminator → TYPE10/TYPE2
# ─────────────────────────────────────────────────────────────────────────────

_TIED_MESH = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2            10.0             0.0             0.0\n"
    "       3            10.0            10.0             0.0\n"
    "       4             0.0            10.0             0.0\n"
    "       5             2.0             0.0             1.0\n"
    "       6             2.0            10.0             1.0\n"
    "       7             2.0             0.0            11.0\n"
    "       8             2.0            10.0            11.0\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "       2       2       5       6       8       7\n"
    "*PART\n"
    "plate\n"
    "         1         1         1\n"
    "*PART\n"
    "stripe\n"
    "         2         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2       1.0         3\n"
    "       2.0\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9    210000.0      0.3\n"
    "*SET_NODE_LIST_TITLE\n"
    "weld_nodes\n"
    "       111\n"
    "         5         6\n"
    "*SET_SEGMENT_TITLE\n"
    "seg_master\n"
    "       103\n"
    "         1         2         3         4\n"
)
_TIED_TAIL = "*CONTROL_TERMINATION\n       1.0\n*END\n"


def _tied_contact(sfs=1.0, sfm=1.0, sst=0.0, mst=0.0, sfst=0.0, sfmt=0.0,
                  kw="SURFACE_TO_SURFACE"):
    """A *CONTACT_TIED_<kw>_ID block (id 60): node-set slave, segment master."""
    return (
        f"*CONTACT_TIED_{kw}_ID\n"
        "        60                                                          tied\n"
        "       111       103         4         0\n"
        "       0.0       0.0       0.0       0.0       0.0         0       0.01.0000E+28\n"
        f"{sfs:>10}{sfm:>10}{sst:>10}{mst:>10}{sfst:>10}{sfmt:>10}\n"
    )


class TiedNegativeGapRoutingTests(unittest.TestCase):
    """(SFST*SST + SFMT*MST)/2 < 0 → /INTER/TYPE10 (penalty), else /INTER/TYPE2."""

    def test_negative_discriminator_emits_type10(self):
        res, s = _convert(_TIED_MESH + _tied_contact(sst=-0.5, sfst=1.0) + _TIED_TAIL)
        self.assertIn("/INTER/TYPE10/60", s)
        self.assertNotIn("/INTER/TYPE2/", s)
        self.assertTrue(any("penalty tie" in w and "TYPE10" in w for w in res.warnings))

    def test_nonnegative_discriminator_stays_type2(self):
        _, s = _convert(_TIED_MESH + _tied_contact(sst=0.5, sfst=1.0) + _TIED_TAIL)
        self.assertIn("/INTER/TYPE2/60", s)
        self.assertNotIn("/INTER/TYPE10/", s)

    def test_discriminator_boundary_zero_is_type2(self):
        # (1*-0.5 + 1*0.5)/2 == 0 → NOT < 0 → kinematic TYPE2.
        _, s = _convert(_TIED_MESH
                        + _tied_contact(sst=-0.5, mst=0.5, sfst=1.0, sfmt=1.0)
                        + _TIED_TAIL)
        self.assertIn("/INTER/TYPE2/60", s)
        self.assertNotIn("/INTER/TYPE10/", s)

    def test_blank_sfst_stays_type2_even_with_negative_sst(self):
        # The reimplementation trap: a blank SFST/SFMT (0) → dSearch 0 → TYPE2,
        # regardless of a negative SST. TYPE10 needs BOTH a nonzero SFST/SFMT and
        # a negative SST/MST.
        _, s = _convert(_TIED_MESH + _tied_contact(sst=-0.5, sfst=0.0) + _TIED_TAIL)
        self.assertIn("/INTER/TYPE2/60", s)
        self.assertNotIn("/INTER/TYPE10/", s)

    def test_type10_entities_are_grnod_and_surf(self):
        _, s = _convert(_TIED_MESH + _tied_contact(sst=-0.5, sfst=1.0) + _TIED_TAIL)
        _, card1 = _inter_card1_floats(s, "/INTER/TYPE10/")
        grnod_id, surf_id = int(card1[0]), int(card1[1])
        self.assertIn(f"/GRNOD/NODE/{grnod_id}", s)
        self.assertIn(surf_id, _all_header_ids(s, "/SURF/"))
        self.assertEqual(int(card1[2]), 1)             # Idel == 1

    def test_type10_gap_from_sst_mst(self):
        # GAP = (|SST| + |MST|)/2 = (0.5 + 0)/2 = 0.25 on the STFAC/…/GAP card.
        _, s = _convert(_TIED_MESH + _tied_contact(sst=-0.5, sfst=1.0) + _TIED_TAIL)
        body = _block(s, _hdr(s, "/INTER/TYPE10/"))
        gap_card = next(r for ln in body
                        if len(r := _num_row(ln)) == 4 and 0.25 in r)
        self.assertEqual(gap_card, [0.0, 0.25, 0.0, 0.0])   # STFAC GAP Tstart Tstop

    def test_offset_variant_also_discriminates_to_type10(self):
        # _OFFSET / _CONSTRAINED_OFFSET share the branch — routed only by sign.
        _, s = _convert(_TIED_MESH
                        + _tied_contact(sst=-0.5, sfst=1.0, kw="SURFACE_TO_SURFACE_OFFSET")
                        + _TIED_TAIL)
        self.assertIn("/INTER/TYPE10/60", s)

    def test_nodes_to_surface_never_type10(self):
        # The discriminator is a SURFACE_TO_SURFACE construct; a NODES_TO_SURFACE
        # tie stays kinematic TYPE2 even with a negative SST.
        deck = (_TIED_MESH
                + _tied_contact(sst=-0.5, sfst=1.0, kw="NODES_TO_SURFACE")
                + _TIED_TAIL)
        _, s = _convert(deck)
        self.assertIn("/INTER/TYPE2/60", s)
        self.assertNotIn("/INTER/TYPE10/", s)

    def test_sst_mst_sfst_sfmt_are_parsed(self):
        st = _dispatch(_TIED_MESH
                       + _tied_contact(sfs=1.0, sfm=1.0, sst=-0.5, mst=-0.25,
                                       sfst=2.0, sfmt=3.0)
                       + _TIED_TAIL)
        self.assertEqual(len(st.contacts_tied), 1)
        c = st.contacts_tied[0]
        self.assertEqual((c.sst, c.mst), (-0.5, -0.25))
        self.assertEqual((c.sfst, c.sfmt), (2.0, 3.0))
        self.assertEqual((c.sfs, c.sfm), (1.0, 1.0))

    def test_plain_tied_no_thickness_still_type2(self):
        # No SST/MST/SFST/SFMT at all → kinematic TYPE2 (no regression on the
        # ordinary tied weld).
        _, s = _convert(_TIED_MESH + _tied_contact() + _TIED_TAIL)
        self.assertIn("/INTER/TYPE2/60", s)
        self.assertNotIn("/INTER/TYPE10/", s)


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATIC_GENERAL — card fidelity + the contacts_general threading regressions
#   (moving SOFT-routed general contacts into their own state list must not make
#    the "all converted contacts" sites blind to them)
# ─────────────────────────────────────────────────────────────────────────────

# *CONTROL_IMPLICIT_GENERAL makes the deck implicit, which is what arms the
# contact-free stabilization stub (_inject_implicit_contact_stub).
_GEN_IMPLICIT_TAIL = (
    "*CONTROL_IMPLICIT_GENERAL\n         1       0.1\n"
    "*CONTROL_TERMINATION\n       1.0\n*END\n"
)


def _card_after_header(starter: str, header_prefix: str, min_int_fields: int):
    """First data row (all-integer, >= min_int_fields cols) after the header line
    that starts with *header_prefix* — for fixed-column card assertions."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(header_prefix):
            for j in range(i + 1, i + 8):
                parts = lines[j].split()
                if (len(parts) >= min_int_fields
                        and all(p.lstrip("-").isdigit() for p in parts[:min_int_fields])):
                    return parts
    return None


class AutomaticGeneralFidelityAndThreadingTests(unittest.TestCase):
    """dyna2rad-fidelity of the routed cards + the three sites that must include
    ``state.contacts_general`` alongside single/surf2surf/tied."""

    # --- SOFT=-7 routed TYPE7 must match dyna2rad's Istf=2 / Igap=2 (cc:52,626),
    #     not the plain single-surface emitter defaults (Istf=4, Igap=0). ------
    def test_soft_minus7_emits_istf2_igap2(self):
        _, s = _convert(_GEN_MESH + _general_contact(-7, ssid=1, sstyp=3) + _GEN_TAIL)
        parts = _card_after_header(s, "/INTER/TYPE7/50", 5)
        self.assertIsNotNone(parts, "no /INTER/TYPE7/50 card1 found")
        # slav_id  mast_id  Istf  Ithe  Igap  ...  Idel ...
        self.assertEqual(parts[2], "2", "Istf must be 2 (dyna2rad SOFT<1)")
        self.assertEqual(parts[4], "2", "Igap must be 2 (dyna2rad TYPE7 map)")
        self.assertEqual(parts[6], "2", "Idel must be 2")

    def test_single_surface_type7_still_istf4_igap0(self):
        # No-regression: the ordinary single-surface TYPE7 (implicit) keeps the
        # validated Istf=4 / Igap=0 emitter defaults.
        _, s = _convert(_GEN_MESH + _general_contact(0, ssid=1, sstyp=3)
                        + "*CONTROL_IMPLICIT_GENERAL\n         1       0.1\n" + _GEN_TAIL)
        parts = _card_after_header(s, "/INTER/TYPE7/50", 5)
        self.assertIsNotNone(parts)
        self.assertEqual(parts[2], "4")
        self.assertEqual(parts[4], "0")

    # --- SOFT=-19 routed TYPE19 references two /SURF ids and self-mirrors. -----
    def test_soft_minus19_references_two_surfaces_self_mirror(self):
        _, s = _convert(_GEN_MESH + _general_contact(-19, ssid=1, sstyp=3) + _GEN_TAIL)
        parts = _card_after_header(s, "/INTER/TYPE19/50", 2)
        self.assertIsNotNone(parts, "no /INTER/TYPE19/50 card1 found")
        surf_ids, surf_idm = int(parts[0]), int(parts[1])
        surf_headers = _all_header_ids(s, "/SURF/")
        self.assertIn(surf_ids, surf_headers)
        self.assertIn(surf_idm, surf_headers)
        # msid was 0 → self-mirror → the same surface on both sides.
        self.assertEqual(surf_ids, surf_idm)

    def test_soft_minus19_two_surface_non_self(self):
        # Distinct slave/master parts → two DIFFERENT /SURF ids (not the mirror).
        deck = (_GEN_MESH
                + "*ELEMENT_SHELL\n       2       2       2       3       4       1\n"
                + "*PART\nplate2\n         2         1         1\n"
                + "*CONTACT_AUTOMATIC_GENERAL_ID\n"
                  "        50                                                          gen\n"
                  "         1         2         3         3         0         0         0         0\n"
                  "       0.1       0.1       0.0       0.0       0.0         0       0.01.0000E+28\n"
                  "       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0\n"
                  "       -19\n"
                + _GEN_TAIL)
        _, s = _convert(deck)
        parts = _card_after_header(s, "/INTER/TYPE19/50", 2)
        self.assertIsNotNone(parts)
        self.assertNotEqual(int(parts[0]), int(parts[1]))

    # --- unresolved geometry on each route → clean warn+skip (no crash, no card).
    def test_soft_minus11_empty_segment_set_skips_cleanly(self):
        deck = (_GEN_MESH
                + "*SET_SEGMENT_TITLE\nempty\n       200\n"
                + "*CONTACT_AUTOMATIC_GENERAL_ID\n"
                  "        50                                                          gen\n"
                  "       200         0         0         0         0         0         0         0\n"
                  "       0.1       0.1       0.0       0.0       0.0         0       0.01.0000E+28\n"
                  "       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0\n"
                  "       -11\n"
                + _GEN_TAIL)
        res, s = _convert(deck)
        self.assertNotIn("/INTER/TYPE11/50", s)
        self.assertTrue(any("no edge/line geometry" in w for w in res.warnings))

    def test_soft_minus19_node_set_side_skips_cleanly(self):
        # A node-set (sstyp=4) side does not resolve to a /SURF on the -19 route.
        deck = (_GEN_MESH
                + "*SET_NODE_LIST_TITLE\nnodes\n       300\n         1         2\n"
                + "*CONTACT_AUTOMATIC_GENERAL_ID\n"
                  "        50                                                          gen\n"
                  "       300         0         4         0         0         0         0         0\n"
                  "       0.1       0.1       0.0       0.0       0.0         0       0.01.0000E+28\n"
                  "       1.0       1.0       0.0       0.0       1.0       1.0       1.0       1.0\n"
                  "       -19\n"
                + _GEN_TAIL)
        res, s = _convert(deck)
        self.assertNotIn("/INTER/TYPE19/50", s)
        self.assertTrue(any("no surface" in w for w in res.warnings))

    # --- REGRESSION: the implicit stabilization stub must NOT fire on a deck
    #     whose only contact is a SOFT-routed general contact. -----------------
    def test_implicit_general_only_no_stabilization_stub(self):
        res, s = _convert(_GEN_MESH + _general_contact(-11) + _GEN_IMPLICIT_TAIL)
        self.assertIn("/INTER/TYPE11/50", s)
        self.assertNotIn("auto_implicit_stabilization_self_contact", s)
        self.assertNotIn("/INTER/TYPE7/", s)   # no spurious all-parts self-contact
        self.assertFalse(any("no contact interface" in w for w in res.warnings))

    def test_implicit_no_contact_still_gets_stub(self):
        # Control: a truly contact-free implicit deck DOES still get the stub.
        res, s = _convert(_GEN_MESH + _GEN_IMPLICIT_TAIL)
        self.assertIn("auto_implicit_stabilization_self_contact", s)

    # --- REGRESSION: *DATABASE_NCFORC must map a general interface to /TH/INTER
    #     and must NOT raise the false "no *CONTACT was converted" warning. -----
    def test_ncforc_includes_general_interface(self):
        deck = _GEN_MESH + _general_contact(-11) + "*DATABASE_NCFORC\n       1.0\n" + _GEN_TAIL
        res, s = _convert(deck)
        self.assertIn("/TH/INTER/", s)
        th_block = _block(s, _hdr(s, "/TH/INTER/"))
        listed = {int(x) for ln in th_block for x in ln.split() if x.isdigit()}
        self.assertIn(50, listed)              # the general interface id
        self.assertFalse(any("no *CONTACT was converted" in w for w in res.warnings))

    # --- the force-transducer parent fallback now sees contacts_general. -------
    def test_force_transducer_parent_falls_back_to_general(self):
        from k2rad.writer.contacts import _select_parent_interface
        from k2rad.state import ContactAutoGeneral
        st = ConversionState()
        st.contacts_general.append(
            ContactAutoGeneral(inter_id=77, title="g", ssid=1, sstyp=3,
                               msid=1, mstyp=3, soft=-7, fs=0.0, fd=0.0,
                               bt=0.0, dt=1e28))
        self.assertEqual(_select_parent_interface(st), 77)
        # a -11 (edge/line) interface cannot host an /INTER/SUB → no fallback.
        st2 = ConversionState()
        st2.contacts_general.append(
            ContactAutoGeneral(inter_id=88, title="g", ssid=1, sstyp=3,
                               msid=1, mstyp=3, soft=-11, fs=0.0, fd=0.0,
                               bt=0.0, dt=1e28))
        self.assertIsNone(_select_parent_interface(st2))


if __name__ == "__main__":
    unittest.main()
