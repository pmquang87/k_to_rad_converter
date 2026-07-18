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
            "*ELEMENT_SHELL_THICKNESS",       # not in the offset map
            "".join(f"{v:>8}" for v in (1, 1, 1, 1, 1, 1)),
            _row(1.0, 1.0, 1.0, 1.0),
            "*END",
        ]) + "\n")
        main = self._write(d, "main.k", "\n".join([
            "*KEYWORD",
            "*INCLUDE_TRANSFORM",
            "child.k", _row(100, 200), "", "", "",
            "*END",
        ]) + "\n")
        self._state(main)
        self.assertTrue(any("ELEMENT_SHELL_THICKNESS" in w
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
