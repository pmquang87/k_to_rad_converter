"""Assembly-transform tests (k2rad.assembly + k2rad.transform):

  * *INCLUDE_TRANSFORM TRANID transforms applied numerically to the included
    *NODE coordinates: TRANSL / ROTATE (direction and two-POINT forms, checked
    against a hand-built Rodrigues matrix) / SCALE / MIRROR / POINT+POS6P /
    TRANSL2ND, and the top-to-bottom row composition order.
  * Id offsets (IDNOFF/IDEOFF/IDPOFF/IDMOFF/IDSOFF/IDFOFF/IDROFF) applied to
    definitions AND references of the included blocks, with no collision
    against parent ids.
  * Deferred TRANID resolution (*DEFINE_TRANSFORMATION after the include),
    nested *INCLUDE_TRANSFORM composition (offsets accumulate additively,
    transforms compose innermost-first).
  * *NODE_TRANSFORM on a *SET_NODE_LIST (applied after include transforms).
  * Loud warnings for genuinely unsupported content only: unknown verbs,
    FCT* unit factors, missing TRANID, unmapped-keyword id offsets,
    coordinate-bearing keywords inside a transformed include.
  * End-to-end roundtrip: the converted starter /NODE block carries the
    transformed coordinates.
"""

import math
import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file, PARSER_WARNINGS
from k2rad.handlers import dispatch
from k2rad.state import ConversionState


def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _opt(verb, *vals) -> str:
    """*DEFINE_TRANSFORMATION option card: verb left-justified in cols 1-10,
    A1..A7 in the following 10-char fields."""
    return f"{verb:<10}" + "".join(f"{v:>10}" for v in vals)


def _nline(nid, x, y, z) -> str:
    """*NODE card in the standard I8 + 3×E16 layout."""
    return f"{nid:>8}{x:16.8E}{y:16.8E}{z:16.8E}"


CHILD_NODES = "\n".join([
    "*KEYWORD",
    "*NODE",
    _nline(1, 0.0, 0.0, 0.0),
    _nline(2, 1.0, 0.0, 0.0),
    _nline(3, 0.0, 2.0, 0.0),
    "*END",
]) + "\n"


class _AssemblyBase(unittest.TestCase):
    def _dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def _write(self, d, name, text):
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def _state(self, main_path) -> ConversionState:
        state = ConversionState()
        for block in parse_k_file(main_path):
            dispatch(block, state)
        return state

    def _main_with_transform(self, d, option_cards, tranid=1,
                             child="child.k"):
        """Main deck: *DEFINE_TRANSFORMATION <tranid> before an
        *INCLUDE_TRANSFORM of *child* whose cards 2-4 are blank and card 5
        carries the TRANID."""
        text = "\n".join(
            ["*KEYWORD", "*DEFINE_TRANSFORMATION", _row(tranid)]
            + option_cards
            + ["*INCLUDE_TRANSFORM", child, "", "", "", _row(tranid), "*END"]
        ) + "\n"
        return self._write(d, "main.k", text)

    def _assert_node(self, state, nid, xyz, places=7):
        self.assertIn(nid, state.nodes)
        nd = state.nodes[nid]
        for got, want in zip((nd.x, nd.y, nd.z), xyz):
            self.assertAlmostEqual(got, want, places=places)


class IncludeTransformGeometryTests(_AssemblyBase):
    def test_transl_applied_exactly(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(
            d, [_opt("TRANSL", 10.0, 20.0, 30.0)])
        st = self._state(main)
        self._assert_node(st, 1, (10.0, 20.0, 30.0))
        self._assert_node(st, 2, (11.0, 20.0, 30.0))
        self._assert_node(st, 3, (10.0, 22.0, 30.0))
        # a fully-supported transform must not warn
        self.assertFalse([w for w in PARSER_WARNINGS
                          if "INCLUDE_TRANSFORM" in w])

    def test_rotate_direction_form_90deg(self):
        # axis +z through (1,0,0), 90 deg CCW (right-hand rule)
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(
            d, [_opt("ROTATE", 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 90.0)])
        st = self._state(main)
        self._assert_node(st, 1, (1.0, -1.0, 0.0))
        self._assert_node(st, 2, (1.0, 0.0, 0.0))     # on the axis: fixed
        self._assert_node(st, 3, (-1.0, -1.0, 0.0))

    def test_rotate_matches_hand_computed_rodrigues(self):
        # General axis/angle vs an independently built Rodrigues rotation.
        axis = (1.0, 2.0, 2.0)          # |axis| = 3
        center = (0.5, -1.0, 2.0)
        ang = 37.0
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(
            d, [_opt("ROTATE", *axis, *center, ang)])
        st = self._state(main)
        n = tuple(c / 3.0 for c in axis)
        th = math.radians(ang)
        c, s = math.cos(th), math.sin(th)

        def rodrigues(p):
            v = tuple(p[i] - center[i] for i in range(3))
            cross = (n[1] * v[2] - n[2] * v[1],
                     n[2] * v[0] - n[0] * v[2],
                     n[0] * v[1] - n[1] * v[0])
            dot = sum(n[i] * v[i] for i in range(3))
            return tuple(center[i] + v[i] * c + cross[i] * s
                         + n[i] * dot * (1 - c) for i in range(3))

        self._assert_node(st, 1, rodrigues((0.0, 0.0, 0.0)))
        self._assert_node(st, 2, rodrigues((1.0, 0.0, 0.0)))
        self._assert_node(st, 3, rodrigues((0.0, 2.0, 0.0)))

    def test_rotate_two_point_form(self):
        # POINT rows + ROTATE alt form (A4-A7 all blank): axis POINT1→POINT2,
        # angle in A3. Same 90-deg z-rotation about (1,0,0) as above.
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(d, [
            _opt("POINT", 1, 1.0, 0.0, 0.0),
            _opt("POINT", 2, 1.0, 0.0, 1.0),
            _opt("ROTATE", 1, 2, 90.0),
        ])
        st = self._state(main)
        self._assert_node(st, 1, (1.0, -1.0, 0.0))
        self._assert_node(st, 2, (1.0, 0.0, 0.0))

    def test_scale_componentwise_and_zero_means_unity(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(
            d, [_opt("SCALE", 2.0, 3.0, 0.0)])   # SZ=0 → 1.0
        st = self._state(main)
        self._assert_node(st, 2, (2.0, 0.0, 0.0))
        self._assert_node(st, 3, (0.0, 6.0, 0.0))

    def test_mirror_about_yz_plane(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(
            d, [_opt("MIRROR", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)])
        st = self._state(main)
        self._assert_node(st, 2, (-1.0, 0.0, 0.0))
        self._assert_node(st, 3, (0.0, 2.0, 0.0))

    def test_pos6p_pure_translation(self):
        # Start frame (origin, +x, +y) onto the same frame at (3,4,5): the
        # rigid POSITION map degenerates to translation by (3,4,5).
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(d, [
            _opt("POINT", 1, 0.0, 0.0, 0.0),
            _opt("POINT", 2, 1.0, 0.0, 0.0),
            _opt("POINT", 3, 0.0, 1.0, 0.0),
            _opt("POINT", 4, 3.0, 4.0, 5.0),
            _opt("POINT", 5, 4.0, 4.0, 5.0),
            _opt("POINT", 6, 3.0, 5.0, 5.0),
            _opt("POS6P", 1, 2, 3, 4, 5, 6),
        ])
        st = self._state(main)
        self._assert_node(st, 1, (3.0, 4.0, 5.0))
        self._assert_node(st, 2, (4.0, 4.0, 5.0))
        self._assert_node(st, 3, (3.0, 6.0, 5.0))

    def test_transl2nd_along_parent_node_pair(self):
        # Direction from parent nodes 100→101 (+z), magnitude 5.
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(100, 0.0, 0.0, 0.0),
            _nline(101, 0.0, 0.0, 2.0),
            "*DEFINE_TRANSFORMATION",
            _row(1),
            _opt("TRANSL2ND", 100, 101, 5.0),
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", "", _row(1),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 0.0, 5.0))
        self._assert_node(st, 2, (1.0, 0.0, 5.0))
        # the reference nodes themselves stay put (not part of the include)
        self._assert_node(st, 100, (0.0, 0.0, 0.0))
        self._assert_node(st, 101, (0.0, 0.0, 2.0))

    def test_composition_order_is_top_to_bottom(self):
        # TRANSL then ROTATE: x' = R·(x+T). Node 1 at origin → (1,0,0) →
        # 90 deg about z → (0,1,0). The reverse order would give (1,0,0).
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(d, [
            _opt("TRANSL", 1.0, 0.0, 0.0),
            _opt("ROTATE", 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 90.0),
        ])
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 1.0, 0.0))
        self._assert_node(st, 2, (0.0, 2.0, 0.0))

    def test_tranid_defined_after_include_still_applies(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", "", _row(7),
            "*DEFINE_TRANSFORMATION",
            _row(7),
            _opt("TRANSL", 0.0, 0.0, 100.0),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 0.0, 100.0))
        self._assert_node(st, 3, (0.0, 2.0, 100.0))


class IncludeTransformOffsetTests(_AssemblyBase):
    CHILD = "\n".join([
        "*KEYWORD",
        "*NODE",
        _nline(1, 0.0, 0.0, 0.0),
        _nline(2, 1.0, 0.0, 0.0),
        _nline(3, 1.0, 1.0, 0.0),
        _nline(4, 0.0, 1.0, 0.0),
        "*ELEMENT_SHELL",
        "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)),
        "*PART",
        "child part",
        _row(1, 1, 1),
        "*SECTION_SHELL",
        _row(1, 2, 1.0, 3),
        _row(1.5),
        "*MAT_ELASTIC",
        _row(1, "7.85E-9", 210000.0, 0.3),
        "*SET_NODE_LIST",
        _row(1),
        _row(1, 2),
        "*BOUNDARY_SPC_SET",
        _row(1, 0, 1, 1, 1, 0, 0, 0),
        "*DEFINE_CURVE",
        _row(7),
        "0.0,0.0",
        "1.0,10.0",
        "*END",
    ]) + "\n"

    def test_id_offsets_applied_to_definitions_and_references(self):
        d = self._dir()
        self._write(d, "child.k", self.CHILD)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 9.0, 9.0, 9.0),
            "*INCLUDE_TRANSFORM",
            "child.k",
            _row(100, 200, 10, 20, 30, 40, 50),
            _row(60),
            "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        # nodes: parent node 1 intact, child nodes at 101-104 (no collision)
        self._assert_node(st, 1, (9.0, 9.0, 9.0))
        for nid in (101, 102, 103, 104):
            self.assertIn(nid, st.nodes)
        # element: eid+IDEOFF, pid+IDPOFF, connectivity re-pointed at 1xx nodes
        self.assertEqual(len(st.shell_elems), 1)
        el = st.shell_elems[0]
        self.assertEqual(el.eid, 201)
        self.assertEqual(el.pid, 11)
        self.assertEqual(el.nodes, [101, 102, 103, 104])
        # part: pid+IDPOFF, secid+IDROFF, mid+IDMOFF
        self.assertIn(11, st.parts)
        self.assertEqual(st.parts[11].secid, 61)
        self.assertEqual(st.parts[11].mid, 21)
        # section + material definitions moved consistently with the refs
        self.assertIn(61, st.sec_shells)
        self.assertIn(21, st.mat_elastic)
        # set: sid+IDSOFF, members re-pointed at the offset nodes
        self.assertIn(31, st.node_sets)
        self.assertEqual(st.node_sets[31][1], [101, 102])
        # BC references the offset set
        self.assertEqual(st.bcs_spcs[0].nsid, 31)
        # curve: lcid+IDFOFF
        self.assertIn(47, st.curves)
        # a fully-mapped include emits no offset warnings
        self.assertFalse([w for w in PARSER_WARNINGS
                          if "INCLUDE_TRANSFORM" in w])

    def test_offsets_and_transform_combine(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*DEFINE_TRANSFORMATION",
            _row(3),
            _opt("TRANSL", 0.0, 0.0, 50.0),
            "*INCLUDE_TRANSFORM",
            "child.k", _row(1000), "", "", _row(3),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1001, (0.0, 0.0, 50.0))
        self._assert_node(st, 1002, (1.0, 0.0, 50.0))
        self.assertNotIn(1, st.nodes)

    def test_nested_include_transform_composes_innermost_first(self):
        d = self._dir()
        self._write(d, "grand.k", "\n".join([
            "*KEYWORD", "*NODE", _nline(1, 0.0, 0.0, 0.0), "*END"]) + "\n")
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(2, 0.0, 0.0, 0.0),
            "*DEFINE_TRANSFORMATION",
            _row(1),
            _opt("TRANSL", 0.0, 0.0, 1.0),
            "*INCLUDE_TRANSFORM",
            "grand.k", _row(10), "", "", _row(1),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*DEFINE_TRANSFORMATION",
            _row(5),
            _opt("TRANSL", 10.0, 0.0, 0.0),
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100), "", "", _row(5),
            "*END",
        ]) + "\n")
        st = self._state(main)
        # grandchild node: id 1 + 10 (inner) + 100 (outer) = 111,
        # coords: inner TRANSL (0,0,1), then outer TRANSL (10,0,0) on top
        self._assert_node(st, 111, (10.0, 0.0, 1.0))
        # child's own node: only the outer offset/transform
        self._assert_node(st, 102, (10.0, 0.0, 0.0))
        self.assertNotIn(1, st.nodes)
        self.assertNotIn(2, st.nodes)


class OffsetLayoutTests(_AssemblyBase):
    """Layouts the flat card map cannot express: ten-node solids, the
    I8/F16-mixed mass and discrete-element cards, SSTYP-dependent contact
    sides, and the _TITLE header variant."""

    def test_element_solid_ten_node_format(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
        ] + [_nline(i, float(i), 0.0, 0.0) for i in range(1, 9)] + [
            "*ELEMENT_SOLID",
            "".join(f"{v:>8}" for v in (1, 2)),
            "".join(f"{v:>8}" for v in (1, 2, 3, 4, 5, 6, 7, 8)),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100, 200, 10), "", "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        self.assertEqual(len(st.solid_elems), 1)
        el = st.solid_elems[0]
        self.assertEqual(el.eid, 201)
        self.assertEqual(el.pid, 12)
        self.assertEqual(el.nodes, [101, 102, 103, 104, 105, 106, 107, 108])

    def test_element_mass_and_discrete_cards(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            _nline(2, 1.0, 0.0, 0.0),
            "*ELEMENT_MASS",
            f"{1:>8}{2:>8}{'0.05':>16}{3:>8}",
            "*ELEMENT_DISCRETE",
            f"{1:>8}{1:>8}{1:>8}{2:>8}{4:>8}{'1.5':>16}",
            "*DEFINE_SD_ORIENTATION",
            _row(4, 0, 1.0, 0.0, 0.0),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100, 200, 10, 0, 0, 0, 50), "",
            "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        # *ELEMENT_MASS: nid+IDNOFF keeps the lumped mass on the moved node
        self.assertAlmostEqual(st.added_node_masses.get(102, 0.0), 0.05)
        # *ELEMENT_DISCRETE: eid/pid/n1/n2 offset, VID follows IDDOFF and
        # still resolves against the offset *DEFINE_SD_ORIENTATION
        self.assertEqual(len(st.discrete_elems), 1)
        de = st.discrete_elems[0]
        self.assertEqual((de.eid, de.pid, de.n1, de.n2, de.vid),
                         (201, 11, 101, 102, 54))
        self.assertAlmostEqual(de.s, 1.5)
        self.assertIn(54, st.sd_orientations)

    def test_contact_sides_follow_sstyp_namespaces(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID",
            f"{5:>10} child contact",
            _row(1, 2, 2, 3),          # ssid=1 (part set), msid=2 (part)
            "", "",
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(0, 0, 10, 0, 30), _row(60),
            "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        self.assertEqual(len(st.contacts_surf2surf), 1)
        ct = st.contacts_surf2surf[0]
        self.assertEqual(ct.inter_id, 65)       # _ID heading + IDROFF
        self.assertEqual(ct.ssid, 31)           # sstyp=2 → set namespace
        self.assertEqual(ct.msid, 12)           # mstyp=3 → part namespace

    def test_define_transformation_title_variant(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*DEFINE_TRANSFORMATION_TITLE",
            "shift the child",
            _row(1),
            _opt("TRANSL", 0.0, 7.0, 0.0),
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", "", _row(1),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 7.0, 0.0))
        self._assert_node(st, 2, (1.0, 7.0, 0.0))


class NodeTransformTests(_AssemblyBase):
    def test_node_transform_moves_only_the_set(self):
        d = self._dir()
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            _nline(2, 1.0, 0.0, 0.0),
            _nline(3, 5.0, 5.0, 5.0),
            "*SET_NODE_LIST",
            _row(1),
            _row(1, 2),
            "*DEFINE_TRANSFORMATION",
            _row(9),
            _opt("TRANSL", 0.0, 0.0, 10.0),
            "*NODE_TRANSFORM",
            _row(9, 1),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 0.0, 10.0))
        self._assert_node(st, 2, (1.0, 0.0, 10.0))
        self._assert_node(st, 3, (5.0, 5.0, 5.0))   # not in the set
        # neither keyword lands in skipped_keywords
        self.assertNotIn("NODE_TRANSFORM", st.skipped_keywords)
        self.assertNotIn("DEFINE_TRANSFORMATION", st.skipped_keywords)

    def test_node_transform_applies_after_include_transform(self):
        # LS-DYNA/Radioss order: submodel (include) transform first, node-set
        # transform acts on the already-moved geometry.
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*DEFINE_TRANSFORMATION",
            _row(1),
            _opt("TRANSL", 10.0, 0.0, 0.0),
            "*DEFINE_TRANSFORMATION",
            _row(2),
            _opt("ROTATE", 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 90.0),
            "*SET_NODE_LIST",
            _row(4),
            _row(1),
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", "", _row(1),
            "*NODE_TRANSFORM",
            _row(2, 4),
            "*END",
        ]) + "\n")
        st = self._state(main)
        # node 1: include TRANSL → (10,0,0), then 90 deg about z → (0,10,0)
        self._assert_node(st, 1, (0.0, 10.0, 0.0))
        # node 2 is not in the set: include transform only
        self._assert_node(st, 2, (11.0, 0.0, 0.0))


class AssemblyWarningTests(_AssemblyBase):
    def test_unsupported_verb_warns_and_other_rows_still_apply(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._main_with_transform(d, [
            _opt("TRANSL", 0.0, 0.0, 5.0),
            _opt("FROBNICATE", 1.0, 2.0, 3.0),
        ])
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 0.0, 5.0))
        self.assertTrue(any("FROBNICATE" in w and "unsupported" in w
                            for w in PARSER_WARNINGS))

    def test_missing_tranid_warns_and_leaves_geometry(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", "", _row(99),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 0.0, 0.0))
        self.assertTrue(any("TRANID=99" in w for w in PARSER_WARNINGS))

    def test_unit_factors_warn_and_are_not_applied(self):
        d = self._dir()
        self._write(d, "child.k", CHILD_NODES)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", _row(1000.0, 0.001, 1000.0), "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 2, (1.0, 0.0, 0.0))   # NOT rescaled
        self.assertTrue(any("FCTLEN" in w and "NOT applied" in w
                            for w in PARSER_WARNINGS))

    def test_unmapped_keyword_offset_warns(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            "*CONSTRAINED_INTERPOLATION",     # not in the offset map
            _row(1, 1, 123456),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100, 200), "", "", "",
            "*END",
        ]) + "\n")
        self._state(main)
        self.assertTrue(any("CONSTRAINED_INTERPOLATION" in w
                            and "NOT applied" in w for w in PARSER_WARNINGS))

    def test_coordinate_bearing_keyword_warns_under_transform(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            "*DEFINE_COORDINATE_SYSTEM",
            _row(4, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            _row(0.0, 1.0, 0.0),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("TRANSL", 1.0, 0.0, 0.0)])
        self._state(main)
        self.assertTrue(any("DEFINE_COORDINATE_SYSTEM" in w
                            and "NOT transformed" in w
                            for w in PARSER_WARNINGS))


class TranidResolutionTests(_AssemblyBase):
    """TRANID binds AFTER the id-offset pass (dyna2rad semantics): a child
    *DEFINE_TRANSFORMATION whose pre-offset id equals the parent's never
    shadows it, the post-offset id is referenceable, and a TRANID written
    inside an offset include shifts with its file's cumulative IDDOFF."""

    CHILD_WITH_DEFN = "\n".join([
        "*KEYWORD",
        "*NODE",
        _nline(1, 0.0, 0.0, 0.0),
        _nline(2, 1.0, 0.0, 0.0),
        "*DEFINE_TRANSFORMATION",
        _row(1),
        _opt("TRANSL", 0.0, 0.0, 99.0),
        "*END",
    ]) + "\n"

    def test_child_definition_does_not_shadow_parent(self):
        # child defines TRANID 1 (→ 101 after IDDOFF=100); the include's
        # TRANID=1 must bind the PARENT's definition placed after the include.
        d = self._dir()
        self._write(d, "child.k", self.CHILD_WITH_DEFN)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k",
            _row(100, "", "", "", "", "", 100),
            "", "",
            _row(1),
            "*DEFINE_TRANSFORMATION",
            _row(1),
            _opt("TRANSL", 10.0, 0.0, 0.0),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 101, (10.0, 0.0, 0.0))
        self._assert_node(st, 102, (11.0, 0.0, 0.0))
        self.assertFalse(any("matches no *DEFINE_TRANSFORMATION" in w
                             for w in PARSER_WARNINGS))

    def test_post_offset_child_definition_is_referenceable(self):
        # dyna2rad spelling: TRANID=101 references the child's definition at
        # its post-IDDOFF id.
        d = self._dir()
        self._write(d, "child.k", self.CHILD_WITH_DEFN)
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k",
            _row(100, "", "", "", "", "", 100),
            "", "",
            _row(101),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 101, (0.0, 0.0, 99.0))
        self._assert_node(st, 102, (1.0, 0.0, 99.0))
        self.assertFalse(any("matches no *DEFINE_TRANSFORMATION" in w
                             for w in PARSER_WARNINGS))

    def test_nested_tranid_shifts_with_enclosing_iddoff(self):
        # The TRANID reference inside b.k lives in b.k's namespace: the outer
        # IDDOFF=100 moves b.k's definition 7 → 107 AND the nested include's
        # TRANID=7 reference with it.
        d = self._dir()
        self._write(d, "c.k", "\n".join([
            "*KEYWORD", "*NODE", _nline(1, 0.0, 0.0, 0.0), "*END"]) + "\n")
        self._write(d, "b.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(2, 0.0, 0.0, 0.0),
            "*DEFINE_TRANSFORMATION",
            _row(7),
            _opt("TRANSL", 0.0, 0.0, 1.0),
            "*INCLUDE_TRANSFORM",
            "c.k", "", "", "", _row(7),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "b.k",
            _row(1000, "", "", "", "", "", 100),
            "", "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 1001, (0.0, 0.0, 1.0))    # c.k node, moved
        self._assert_node(st, 1002, (0.0, 0.0, 0.0))    # b.k node, untouched
        self.assertFalse(any("matches no *DEFINE_TRANSFORMATION" in w
                             for w in PARSER_WARNINGS))


class RigidwallTransformTests(_AssemblyBase):
    def test_planar_wall_moves_with_include(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 5.0),
            "*RIGIDWALL_PLANAR",
            _row(0, 0, 0),
            _row(1.0, 2.0, 0.0, 1.0, 2.0, 1.0, 0.3),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("TRANSL", 0.0, 0.0, 100.0)])
        st = self._state(main)
        self._assert_node(st, 1, (0.0, 0.0, 105.0))
        rw = st.rigid_walls[0]
        self.assertAlmostEqual(rw.xt, 1.0)
        self.assertAlmostEqual(rw.yt, 2.0)
        self.assertAlmostEqual(rw.zt, 100.0)
        self.assertAlmostEqual(rw.xh, 1.0)
        self.assertAlmostEqual(rw.yh, 2.0)
        self.assertAlmostEqual(rw.zh, 101.0)
        self.assertAlmostEqual(rw.fric, 0.3)            # non-point field kept
        self.assertFalse([w for w in PARSER_WARNINGS if "RIGIDWALL" in w])

    def test_planar_wall_rotates_with_include(self):
        # 90 deg about +z through the origin: base (1,0,0) → (0,1,0), the
        # +x normal (head-base) → +y.
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 2.0, 0.0, 0.0),
            "*RIGIDWALL_PLANAR",
            _row(0, 0, 0),
            _row(1.0, 0.0, 0.0, 2.0, 0.0, 0.0),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("ROTATE", 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 90.0)])
        st = self._state(main)
        rw = st.rigid_walls[0]
        for got, want in zip((rw.xt, rw.yt, rw.zt, rw.xh, rw.yh, rw.zh),
                             (0.0, 1.0, 0.0, 0.0, 2.0, 0.0)):
            self.assertAlmostEqual(got, want, places=9)

    def test_finite_wall_edge_head_moves_lengths_kept(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 5.0),
            "*RIGIDWALL_PLANAR_FINITE",
            _row(0, 0, 0),
            _row(0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            _row(1.0, 0.0, 0.0, 4.0, 2.0),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("TRANSL", 10.0, 20.0, 30.0)])
        st = self._state(main)
        rw = st.rigid_walls[0]
        self.assertTrue(rw.finite)
        self.assertAlmostEqual(rw.zt, 30.0)
        self.assertAlmostEqual(rw.zh, 31.0)
        self.assertAlmostEqual(rw.xhev, 11.0)           # edge head is a point
        self.assertAlmostEqual(rw.yhev, 20.0)
        self.assertAlmostEqual(rw.zhev, 30.0)
        self.assertAlmostEqual(rw.lenl, 4.0)            # extents untouched
        self.assertAlmostEqual(rw.lenm, 2.0)
        self.assertFalse([w for w in PARSER_WARNINGS if "RIGIDWALL" in w])

    def test_finite_wall_warns_under_scale(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 5.0),
            "*RIGIDWALL_PLANAR_FINITE",
            _row(0, 0, 0),
            _row(1.0, 1.0, 0.0, 1.0, 1.0, 1.0),
            _row(2.0, 1.0, 0.0, 4.0, 2.0),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(d, [_opt("SCALE", 2.0, 2.0, 2.0)])
        st = self._state(main)
        rw = st.rigid_walls[0]
        self.assertAlmostEqual(rw.xt, 2.0)              # points still scale
        self.assertAlmostEqual(rw.zh, 2.0)
        self.assertTrue(any("LENL/LENM are NOT rescaled" in w
                            for w in PARSER_WARNINGS))


class ReferenceOffsetEdgeTests(_AssemblyBase):
    def test_cnrb_spc_local_system_reference_offset(self):
        # CMO<0 → CON1 is a *DEFINE_COORDINATE_* id and follows IDDOFF.
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            _nline(2, 1.0, 0.0, 0.0),
            "*DEFINE_COORDINATE_NODES",
            _row(1, 1, 2, 1),
            "*SET_NODE_LIST",
            _row(1),
            _row(1, 2),
            "*CONSTRAINED_NODAL_RIGID_BODY_SPC",
            _row(1, 0, 1),
            _row(-1, 1, 100),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row("", "", "", "", "", "", 50), "", "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        self.assertIn(51, st.coord_nodes)
        self.assertEqual(st.cnrbs[0].con1, 51)

    def test_cnrb_spc_global_dof_code_not_offset(self):
        # CMO>0 → CON1 is a DOF code (0-7), NOT an id: must stay untouched.
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            "*SET_NODE_LIST",
            _row(1),
            _row(1),
            "*CONSTRAINED_NODAL_RIGID_BODY_SPC",
            _row(1, 0, 1),
            _row(1, 7, 7),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row("", "", "", "", "", "", 50), "", "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        self.assertEqual(st.cnrbs[0].con1, 7)
        self.assertEqual(st.cnrbs[0].con2, 7)

    def test_mat_rigid_local_system_reference_offset(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*MAT_RIGID",
            _row(1, "7.85E-9", 210000.0, 0.3),
            _row(-1.0, 3, 111111),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row("", "", "", 10, "", "", 50), "", "", "",
            "*END",
        ]) + "\n")
        st = self._state(main)
        mr = st.mat_rigid[11]
        self.assertEqual(mr.con1, 53)
        # CMO=1 → CON1 is a DOF code: untouched
        d2 = self._dir()
        self._write(d2, "child.k", "\n".join([
            "*KEYWORD",
            "*MAT_RIGID",
            _row(1, "7.85E-9", 210000.0, 0.3),
            _row(1.0, 4, 7),
            "*END",
        ]) + "\n")
        main2 = self._write(d2, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row("", "", "", 10, "", "", 50), "", "", "",
            "*END",
        ]) + "\n")
        st2 = self._state(main2)
        self.assertEqual(st2.mat_rigid[11].con1, 4)

    def test_bpm_continuation_card_fields(self):
        # |DOF|=9 → next card is OFFSET1 OFFSET2 MRB NODE1 NODE2: the axis
        # offsets stay verbatim, MRB follows IDPOFF, the nodes IDNOFF.
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(201, 0.0, 0.0, 0.0),
            _nline(202, 1.0, 0.0, 0.0),
            "*SET_NODE_LIST",
            _row(5),
            _row(201, 202),
            "*DEFINE_CURVE",
            _row(9),
            "0.0,0.0",
            "1.0,10.0",
            "*BOUNDARY_PRESCRIBED_MOTION_SET",
            _row(5, 9, 2, 9, 1.0),
            _row(12.5, 7.5, 3, 201, 202),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(1000, "", 10, "", 100, 5000), "", "", "",
            "*END",
        ]) + "\n")
        blocks = parse_k_file(main)
        bpm = next(b for b in blocks
                   if b.keyword == "BOUNDARY_PRESCRIBED_MOTION_SET")
        card1 = bpm.raw[0].split()
        card2 = bpm.raw[1].split()
        self.assertEqual(card1[0], "105")           # set id + IDSOFF
        self.assertEqual(card1[3], "5009")          # lcid + IDFOFF
        self.assertEqual(card2[0], "12.5")          # OFFSET1 verbatim
        self.assertEqual(card2[1], "7.5")           # OFFSET2 verbatim
        self.assertEqual(card2[2], "13")            # MRB + IDPOFF
        self.assertEqual(card2[3], "1201")          # NODE1 + IDNOFF
        self.assertEqual(card2[4], "1202")          # NODE2 + IDNOFF

    def test_load_segment_n6_n8_card_offsets_as_nodes(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*DEFINE_CURVE",
            _row(9),
            "0.0,0.0",
            "*LOAD_SEGMENT",
            _row(9, 1.0, 0.0, 11, 12, 13, 14, 15),
            _row(16, 17, 18),
            _row(9, 1.0, 0.0, 21, 22, 23, 24),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(1000, "", "", "", "", 5000), "", "", "",
            "*END",
        ]) + "\n")
        blocks = parse_k_file(main)
        ls = next(b for b in blocks if b.keyword == "LOAD_SEGMENT")
        self.assertEqual(ls.raw[0].split(),
                         ["5009", "1.0", "0.0", "1011", "1012", "1013",
                          "1014", "1015"])
        self.assertEqual(ls.raw[1].split(), ["1016", "1017", "1018"])
        # the entry AFTER a continuation card is a normal card 1 again
        self.assertEqual(ls.raw[2].split(),
                         ["5009", "1.0", "0.0", "1021", "1022", "1023",
                          "1024"])

    def test_ivg_axis_point_warns_under_pure_translation(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            "*INITIAL_VELOCITY_GENERATION",
            _row(0, 1, 5.0, 0.0, 0.0, 0.0),
            _row(2.0, 3.0, 4.0, 0.0, 0.0, 1.0),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("TRANSL", 0.0, 0.0, 100.0)])
        self._state(main)
        self.assertTrue(any("INITIAL_VELOCITY_GENERATION" in w
                            and "NOT transformed" in w
                            for w in PARSER_WARNINGS))

    def test_ivg_without_rotation_silent_under_pure_translation(self):
        # OMEGA=0: only velocity directions — invariant under translation.
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            "*INITIAL_VELOCITY_GENERATION",
            _row(0, 1, 0.0, 1000.0, 0.0, 0.0),
            _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("TRANSL", 0.0, 0.0, 100.0)])
        self._state(main)
        self.assertFalse(any("INITIAL_VELOCITY_GENERATION" in w
                             for w in PARSER_WARNINGS))


class CoordinatePrecisionTests(_AssemblyBase):
    def test_offset_only_rewrite_preserves_coordinate_text(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            f"{1:>8}{'123.4567890123':>16}{'-1.05000E-9':>16}{'0.0':>16}",
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100), "", "", "",
            "*END",
        ]) + "\n")
        blocks = parse_k_file(main)
        node = next(b for b in blocks if b.keyword == "NODE")
        self.assertIn("123.4567890123", node.raw[0])
        self.assertIn("-1.05000E-9", node.raw[0])
        st = ConversionState()
        for b in blocks:
            dispatch(b, st)
        self.assertEqual(st.nodes[101].x, 123.4567890123)

    def test_transformed_coordinates_carry_ten_significant_digits(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            f"{1:>8}{'123.4567891':>16}{'0.0':>16}{'0.0':>16}",
            "*END",
        ]) + "\n")
        main = self._main_with_transform(
            d, [_opt("TRANSL", 1.0, 0.0, 0.0)])
        st = self._state(main)
        # %16.9G (9 digits) would flatten this to 124.456789
        self.assertAlmostEqual(st.nodes[1].x, 124.4567891, places=8)


class WhitespaceFormatTests(_AssemblyBase):
    def test_whitespace_transl2nd_node_refs_offset_and_resolve(self):
        # Compact free format "TRANSL2ND 1 2 5.0" inside an IDNOFF include:
        # the node references must offset (1→101, 2→102) so the geometry
        # pass resolves them; exercised through *NODE_TRANSFORM.
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            _nline(2, 1.0, 0.0, 0.0),
            "*DEFINE_TRANSFORMATION",
            _row(5),
            "TRANSL2ND 1 2 5.0",
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*SET_NODE_LIST",
            _row(4),
            _row(101),
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100), "", "", "",
            "*NODE_TRANSFORM",
            _row(5, 4),
            "*END",
        ]) + "\n")
        st = self._state(main)
        self._assert_node(st, 101, (5.0, 0.0, 0.0))
        self._assert_node(st, 102, (1.0, 0.0, 0.0))
        self.assertFalse(any("SKIPPED" in w for w in PARSER_WARNINGS))


class RoundtripConvertTests(_AssemblyBase):
    def test_starter_node_lines_carry_transformed_coords(self):
        d = self._dir()
        self._write(d, "child.k", "\n".join([
            "*KEYWORD",
            "*NODE",
            _nline(1, 0.0, 0.0, 0.0),
            _nline(2, 1.0, 0.0, 0.0),
            _nline(3, 1.0, 1.0, 0.0),
            _nline(4, 0.0, 1.0, 0.0),
            "*ELEMENT_SHELL",
            "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)),
            "*PART",
            "plate",
            _row(1, 1, 1),
            "*SECTION_SHELL",
            _row(1, 2, 1.0, 3),
            _row(1.5),
            "*MAT_ELASTIC",
            _row(1, "7.85E-9", 210000.0, 0.3),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*DEFINE_TRANSFORMATION",
            _row(1),
            _opt("TRANSL", 100.0, -50.0, 25.0),
            "*INCLUDE_TRANSFORM",
            "child.k", "", "", "", _row(1),
            "*CONTROL_TERMINATION",
            _row(0.001),
            "*END",
        ]) + "\n")
        result = convert(main, write_log=False)
        with open(result.starter_path) as fh:
            starter = fh.read()
        body = starter.split("/NODE", 1)[1].splitlines()
        coords = {}
        for line in body[1:]:
            if line.startswith("/"):
                break
            if line.startswith("#") or not line.strip():
                continue
            toks = line.split()
            if len(toks) >= 4:
                coords[int(toks[0])] = tuple(float(t) for t in toks[1:4])
        expected = {
            1: (100.0, -50.0, 25.0),
            2: (101.0, -50.0, 25.0),
            3: (101.0, -49.0, 25.0),
            4: (100.0, -49.0, 25.0),
        }
        for nid, xyz in expected.items():
            self.assertIn(nid, coords)
            for got, want in zip(coords[nid], xyz):
                self.assertAlmostEqual(got, want, places=6)


if __name__ == "__main__":
    unittest.main()
