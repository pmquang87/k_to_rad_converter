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
from k2rad.writer.loads import _inivel_gen_group_nodes


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

    def test_boxid_warns_and_still_converts(self):
        deck = self._deck(_card10(9, 0, 7, 0, 0), _card10(5.0, 0.0, 0.0))
        res, s = _convert(deck)
        self.assertTrue(any("BOXID" in w and "DEFINE_BOX support pending" in w
                            for w in res.warnings))
        self.assertIn("/INIVEL/TRA/", s)   # converted anyway

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


if __name__ == "__main__":
    unittest.main()
