"""Tests for *RIGIDWALL_GEOMETRIC_{FLAT,PRISM,CYLINDER,SPHERE} conversion.

Card layouts asserted here follow the OpenRadioss hm_cfg_files RWALL cfgs
(config/CFG/radioss110/RWALL/{plane,paral,cyl,sphere}.cfg, FORMAT radioss51 —
the newest FORMAT block <= radioss2022), cross-checked against the starter
readers hm_read_rwall_{plane,paral,cyl,spher}.F:

    /RWALL/PLANE|PARAL|CYL|SPHER/<id>
    <title>                                       MANDATORY
    #  node_ID     Slide  grnd_ID1  grnd_ID2      (4 x I10, exactly 40 cols —
                                                   cols 41-50 are the 2026-only
                                                   Iform and are dead at 2022)
    #           D_search     fric     Diameter     ffac      ifq
    <d F20><fric F20><Diameter F20><ffac F20><ifq I10>       (90 cols)
    then  "XM YM ZM" (3 x F20, fixed wall, node_ID = 0)
    or    "Mass VX0 VY0 VZ0" (4 x F20, moving wall, node_ID > 0)
    then  "XM1 YM1 ZM1" (PLANE/CYL/PARAL; SPHER has NO card 4)
    then  "XM2 YM2 ZM2" (PARAL only).

Key semantics the numbers below encode:
  * ``Diameter`` is a DIAMETER while LS-DYNA's RADCYL/RADSPH are RADII
    (hm_read_rwall_cyl.F:272 ``DISN = SQRT(D2-D1**2) - HALF*DIAM``), so
    Phi = 2 x RAD.
  * /RWALL/CYL keeps only ``normalize(M1 - M)`` as the axis and has NO length
    field — the LS-DYNA LENCYL is unrepresentable and must be warned.
  * /RWALL/PARAL is a flat one-sided parallelogram, never a box, so a PRISM
    decomposes into six PARAL faces with outward normals.

Kept in a separate module from tests/test_rwall_variants.py (the *_PLANAR
suite) so the two families can move independently.
"""

import os
import tempfile
import unittest

from k2rad import convert


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


# One elastic quad shell at z=1, a node set the walls track, and a curve for
# the _MOTION variants. Node ids are 1..4, so the first synthesized _MOTION
# carrier node is always id 5.
BASE_K = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             1.0\n"
    "       2             1.0             0.0             1.0\n"
    "       3             1.0             1.0             1.0\n"
    "       4             0.0             1.0             1.0\n"
    "*PART\n"
    "plate\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2\n"
    "       1.0\n"
    "*MAT_ELASTIC\n"
    "         1   7.86e-9  210000.0       0.3\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "*SET_NODE_LIST\n"
    "        30\n"
    "         1         2         3         4\n"
    "*DEFINE_CURVE\n"
    "        99\n"
    "       0.0       0.0\n"
    "       1.0       1.0\n"
    "{WALL}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


def _deck(wall_cards: str) -> str:
    return BASE_K.replace("{WALL}", wall_cards)


def _blocks(starter: str, form: str):
    """Every /RWALL/<form>/ block as a list of lines (id line first)."""
    parts = starter.split(f"/RWALL/{form}/")[1:]
    return [[f"/RWALL/{form}/" + p.splitlines()[0]] + p.splitlines()[1:]
            for p in parts]


def _one(starter: str, form: str):
    blocks = _blocks(starter, form)
    assert len(blocks) == 1, f"expected one /RWALL/{form}/, got {len(blocks)}"
    return blocks[0]


def _nums(line: str):
    return [float(t) for t in line.split()]


class CylinderTests(unittest.TestCase):
    # tail (0,0,0) on the axis, head (0,0,1) → axis +Z; RADCYL 2.5 → Phi 5.0;
    # FRIC 0.3 → Slide 2 with the coefficient on card 2.
    WALL = (
        "*RIGIDWALL_GEOMETRIC_CYLINDER_ID\n"
        "       501cyl wall\n"
        "        30         0         0\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0       0.3\n"
        "       2.5       0.0\n"
    )

    def test_cylinder_card_layout(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_GEOMETRIC_CYLINDER",
                         result.skipped_keywords)
        b = _one(starter, "CYL")
        self.assertEqual(b[0], "/RWALL/CYL/501")
        self.assertEqual(b[1], "cyl wall")            # title line is mandatory
        self.assertEqual(b[2], "#  node_ID     Slide  grnd_ID1  grnd_ID2")
        card1 = b[3]
        self.assertEqual(len(card1), 40)              # nothing in the Iform slot
        self.assertEqual(card1[0:10], "         0")   # fixed wall
        self.assertEqual(card1[10:20], "         2")  # Slide = 2 (Coulomb)
        self.assertNotEqual(card1[20:30].strip(), "0")   # grnd_ID1 emitted
        self.assertEqual(card1[30:40], "         0")  # grnd_ID2
        self.assertEqual(
            b[4],
            "#           D_search                fric            Diameter"
            "                ffac       ifq")
        card2 = b[5]
        self.assertEqual(len(card2), 90)
        self.assertEqual(card2[0:20], "                   0")     # d
        self.assertEqual(card2[20:40], "                 0.3")    # fric
        self.assertEqual(card2[40:60], "                   5")    # 2 x RADCYL
        self.assertEqual(card2[60:80], "                   0")    # ffac
        self.assertEqual(card2[80:90], "         0")              # ifq
        self.assertEqual(
            b[6], "#                 XM                  YM                  ZM")
        self.assertEqual(_nums(b[7]), [0.0, 0.0, 0.0])            # M = tail
        self.assertEqual(
            b[8], "#                XM1                 YM1                 ZM1")
        self.assertEqual(_nums(b[9]), [0.0, 0.0, 1.0])            # M1 = head

    def test_diameter_is_twice_the_radius(self):
        wall = self.WALL.replace("       2.5       0.0\n",
                                 "      12.5       0.0\n")
        _result, starter = _convert(_deck(wall))
        self.assertEqual(_one(starter, "CYL")[5][40:60], "                  25")

    def test_lencyl_is_warned_not_silently_dropped(self):
        wall = self.WALL.replace("       2.5       0.0\n",
                                 "       2.5      70.0\n")
        result, starter = _convert(_deck(wall))
        self.assertIn("/RWALL/CYL/501", starter)
        self.assertTrue(any("LENCYL = 70" in w and "AXIALLY INFINITE" in w
                            for w in result.warnings))

    def test_zero_lencyl_produces_no_warning(self):
        result, _starter = _convert(_deck(self.WALL))
        self.assertFalse(any("LENCYL" in w for w in result.warnings))

    def test_degenerate_axis_is_dropped_not_emitted_as_error_167(self):
        # head == tail → the starter aborts with ERROR 167; refuse instead.
        wall = self.WALL.replace(
            "       0.0       0.0       0.0       0.0       0.0       1.0       0.3\n",
            "       0.0       0.0       0.0       0.0       0.0       0.0       0.3\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/", starter)
        self.assertTrue(any("ERROR 167" in w for w in result.warnings))

    def test_nsegs_subcards_are_skipped_and_warned(self):
        # NSEGS sub-cards sit between the shape card and the MOTION card, so
        # mis-counting them would read "1.0 2.0" as the MOTION card.
        wall = (
            "*RIGIDWALL_GEOMETRIC_CYLINDER_MOTION_ID\n"
            "       501cyl wall\n"
            "        30         0         0\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       2.5       0.0         2\n"
            "       1.0       2.0\n"
            "       3.0       4.0\n"
            "        99         0       0.0       1.0       0.0\n"
        )
        result, starter = _convert(_deck(wall))
        self.assertTrue(any("NSEGS=2" in w for w in result.warnings))
        self.assertIn("/IMPVEL/", starter)
        impvel = starter.split("/IMPVEL/")[1].splitlines()
        # funct_IDT is the LS-DYNA LCID, not the "1.0" of a VL/HEIGHT card.
        self.assertEqual(impvel[3][0:10], "        99")


class SphereTests(unittest.TestCase):
    # M = the sphere centre (the tail point); RADSPH 4 → Phi 8; FRIC 1.0 is
    # LS-DYNA's "no sliding" → Slide 1 (tied), NOT a Coulomb mu of 1.0.
    WALL = (
        "*RIGIDWALL_GEOMETRIC_SPHERE_ID\n"
        "       502sphere wall\n"
        "        30\n"
        "       1.0       2.0       3.0       1.0       2.0       4.0       1.0\n"
        "       4.0\n"
    )

    def test_sphere_card_layout_has_no_xm1_card(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_GEOMETRIC_SPHERE", result.skipped_keywords)
        b = _one(starter, "SPHER")
        self.assertEqual(b[0], "/RWALL/SPHER/502")
        self.assertEqual(b[1], "sphere wall")
        self.assertEqual(b[3][10:20], "         1")            # Slide = 1
        self.assertEqual(b[5][40:60], "                   8")  # 2 x RADSPH
        self.assertEqual(b[5][20:40], "                   0")  # no fric card
        self.assertEqual(
            b[6], "#                 XM                  YM                  ZM")
        self.assertEqual(_nums(b[7]), [1.0, 2.0, 3.0])         # centre = tail
        # /RWALL/SPHER stops after card 3 — the block separator follows.
        self.assertNotIn("XM1", "\n".join(b))

    def test_zero_radius_is_dropped(self):
        wall = self.WALL.replace("       4.0\n", "       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/", starter)
        self.assertTrue(any("RADSPH = 0" in w for w in result.warnings))

    def test_fractional_fric_becomes_coulomb(self):
        wall = self.WALL.replace(
            "       1.0       2.0       3.0       1.0       2.0       4.0       1.0\n",
            "       1.0       2.0       3.0       1.0       2.0       4.0      0.25\n")
        _result, starter = _convert(_deck(wall))
        b = _one(starter, "SPHER")
        self.assertEqual(b[3][10:20], "         2")
        self.assertEqual(b[5][20:40], "                0.25")


class FlatTests(unittest.TestCase):
    # n = (0,0,1); HEV (2,0,0) is already in-plane → l = (1,0,0),
    # m = n x l = (0,1,0). LENL 4, LENM 3 → M1 = (4,0,0), M2 = (0,3,0).
    WALL = (
        "*RIGIDWALL_GEOMETRIC_FLAT_ID\n"
        "       503flat wall\n"
        "        30\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0\n"
        "       2.0       0.0       0.0       4.0       3.0\n"
    )

    def test_finite_flat_becomes_paral_with_corner_points(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_GEOMETRIC_FLAT", result.skipped_keywords)
        b = _one(starter, "PARAL")
        self.assertEqual(b[0], "/RWALL/PARAL/503")
        self.assertEqual(_nums(b[7]), [0.0, 0.0, 0.0])       # M = tail
        self.assertEqual(
            b[8], "#                XM1                 YM1                 ZM1")
        self.assertEqual(_nums(b[9]), [4.0, 0.0, 0.0])       # M + LENL*l
        self.assertEqual(
            b[10], "#                XM2                 YM2                 ZM2")
        self.assertEqual(_nums(b[11]), [0.0, 3.0, 0.0])      # M + LENM*m
        self.assertEqual(b[5][40:60], "                   0")  # Diameter unused

    def test_hev_is_projected_into_the_wall_plane(self):
        # HEV (2,0,5): its in-plane projection is (2,0,0), so the corner
        # points are unchanged. dyna2rad normalizes (HEV - T) raw, which would
        # shorten the m edge by sin(theta).
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0\n",
            "       2.0       0.0       5.0       4.0       3.0\n")
        _result, starter = _convert(_deck(wall))
        b = _one(starter, "PARAL")
        self.assertEqual(_nums(b[9]), [4.0, 0.0, 0.0])
        self.assertEqual(_nums(b[11]), [0.0, 3.0, 0.0])

    def test_non_axis_aligned_wall(self):
        # n = (1,0,0) from tail (1,1,1) to head (2,1,1); HEV (1,1,4) gives
        # v = (0,0,3), already in-plane → l = (0,0,1); m = n x l = (0,-1,0).
        # LENL 2, LENM 6 → M1 = (1,1,3), M2 = (1,-5,1).
        wall = (
            "*RIGIDWALL_GEOMETRIC_FLAT_ID\n"
            "       503flat wall\n"
            "        30\n"
            "       1.0       1.0       1.0       2.0       1.0       1.0\n"
            "       1.0       1.0       4.0       2.0       6.0\n"
        )
        _result, starter = _convert(_deck(wall))
        b = _one(starter, "PARAL")
        self.assertEqual(_nums(b[7]), [1.0, 1.0, 1.0])
        self.assertEqual(_nums(b[9]), [1.0, 1.0, 3.0])
        self.assertEqual(_nums(b[11]), [1.0, -5.0, 1.0])

    def test_blank_hev_is_the_infinite_plane_exactly(self):
        # cfg geometrytype 2: a blank edge-vector head IS LS-DYNA's infinite
        # plane, which /RWALL/PLANE expresses exactly — no loss, no warning.
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0\n",
            "       0.0       0.0       0.0       0.0       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/PARAL/", starter)
        b = _one(starter, "PLANE")
        self.assertEqual(b[0], "/RWALL/PLANE/503")
        self.assertEqual(_nums(b[7]), [0.0, 0.0, 0.0])       # M = tail
        self.assertEqual(_nums(b[9]), [0.0, 0.0, 1.0])       # M1 = head
        self.assertFalse(any("RIGIDWALL_GEOMETRIC_FLAT id=503" in w
                             for w in result.warnings))

    def test_zero_lenl_falls_back_to_infinite_plane_with_warning(self):
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0\n",
            "       2.0       0.0       0.0       0.0       3.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/PARAL/", starter)
        self.assertIn("/RWALL/PLANE/503", starter)
        self.assertTrue(any("semi-infinite wall" in w and "INFINITE" in w
                            for w in result.warnings))

    def test_degenerate_normal_is_dropped(self):
        wall = self.WALL.replace(
            "       0.0       0.0       0.0       0.0       0.0       1.0\n",
            "       0.0       0.0       0.0       0.0       0.0       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/", starter)
        self.assertTrue(any("head == tail" in w for w in result.warnings))


class PrismTests(unittest.TestCase):
    # Box corner T = (0,0,0); n = (0,0,1), l = (1,0,0), m = (0,1,0);
    # LENL 4 along l, LENM 3 along m, LENP 5 along -n. Six /RWALL/PARAL faces,
    # every normal (M1-M) x (M2-M) pointing OUT of the box.
    WALL = (
        "*RIGIDWALL_GEOMETRIC_PRISM_ID\n"
        "       504prism wall\n"
        "        30\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0\n"
        "       2.0       0.0       0.0       4.0       3.0       5.0\n"
    )

    #: (title suffix, M, M1, M2) per face — hand-computed from the triad.
    FACES = [
        ("prism wall",       [0, 0, 0], [4, 0, 0], [0, 3, 0]),   # +n (top)
        ("prism wall_FACE2", [0, 0, 0], [0, 0, -5], [4, 0, 0]),  # -m
        ("prism wall_FACE3", [0, 0, 0], [0, 3, 0], [0, 0, -5]),  # -l
        ("prism wall_FACE4", [0, 3, 0], [4, 3, 0], [0, 3, -5]),  # +m
        ("prism wall_FACE5", [4, 3, 0], [4, 0, 0], [4, 3, -5]),  # +l
        ("prism wall_FACE6", [0, 0, -5], [0, 3, -5], [4, 0, -5]),  # -n (bottom)
    ]

    def test_prism_becomes_six_outward_paral_faces(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_GEOMETRIC_PRISM", result.skipped_keywords)
        blocks = _blocks(starter, "PARAL")
        self.assertEqual(len(blocks), 6)
        for b, (title, m, m1, m2) in zip(blocks, self.FACES):
            self.assertEqual(b[1], title)
            self.assertEqual(_nums(b[7]), [float(x) for x in m])
            self.assertEqual(_nums(b[9]), [float(x) for x in m1])
            self.assertEqual(_nums(b[11]), [float(x) for x in m2])

    def test_face_normals_all_point_out_of_the_box(self):
        _result, starter = _convert(_deck(self.WALL))
        expect = [(0, 0, 1), (0, -1, 0), (-1, 0, 0),
                  (0, 1, 0), (1, 0, 0), (0, 0, -1)]
        for b, want in zip(_blocks(starter, "PARAL"), expect):
            m, m1, m2 = _nums(b[7]), _nums(b[9]), _nums(b[11])
            e1 = [m1[i] - m[i] for i in range(3)]
            e2 = [m2[i] - m[i] for i in range(3)]
            # starter: RWL(1..3) = normalize((M1-M) x (M2-M))
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]
            mag = (nx * nx + ny * ny + nz * nz) ** 0.5
            self.assertGreater(mag, 0.0)                # no ERROR 168
            got = (round(nx / mag, 9), round(ny / mag, 9), round(nz / mag, 9))
            self.assertEqual(got, tuple(float(c) for c in want))

    def test_faces_get_unique_ids_and_share_the_tracked_group(self):
        _result, starter = _convert(_deck(self.WALL))
        blocks = _blocks(starter, "PARAL")
        ids = [int(b[0].rsplit("/", 1)[1]) for b in blocks]
        self.assertEqual(ids[0], 504)                   # the LS-DYNA RWID
        self.assertEqual(len(set(ids)), 6)
        grnods = {b[3][20:30] for b in blocks}
        self.assertEqual(len(grnods), 1)                # one shared /GRNOD
        self.assertEqual({b[3][10:20] for b in blocks}, {"         0"})

    def test_zero_lenp_emits_the_top_face_only(self):
        # LENP = 0 is an infinitely deep prism; dyna2rad emits four faces with
        # a zero edge vector, which the starter rejects with ERROR 168 x4.
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0       5.0\n",
            "       2.0       0.0       0.0       4.0       3.0       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertEqual(len(_blocks(starter, "PARAL")), 1)
        self.assertTrue(any("LENP = 0" in w and "only the top face" in w
                            for w in result.warnings))

    def test_zero_lenl_degrades_to_an_infinite_plane(self):
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0       5.0\n",
            "       2.0       0.0       0.0       0.0       3.0       5.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/PARAL/", starter)
        self.assertIn("/RWALL/PLANE/504", starter)
        self.assertTrue(any("four side faces and its bottom face are lost" in w
                            for w in result.warnings))


class MotionTests(unittest.TestCase):
    # OPT = 0 → /IMPVEL; the direction cosines become a /SKEW/FIX whose local
    # X' is the motion vector, and the card asks for Dir = "X".
    WALL = (
        "*RIGIDWALL_GEOMETRIC_SPHERE_MOTION_ID\n"
        "       505moving sphere\n"
        "        30\n"
        "       1.0       2.0       3.0       1.0       2.0       4.0\n"
        "       4.0\n"
        "        99         0       0.0       1.0       0.0\n"
    )

    def test_motion_wall_takes_the_moving_rwall_form(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_GEOMETRIC_SPHERE_MOTION",
                         result.skipped_keywords)
        b = _one(starter, "SPHER")
        self.assertEqual(b[3][0:10], "         5")     # carrier node id 5
        # A moving wall has NO "XM YM ZM" card: M comes from the node.
        self.assertIn("Mass", b[6])
        self.assertEqual(_nums(b[7]), [0.0, 0.0, 0.0, 0.0])
        self.assertNotIn("XM", "\n".join(b))
        # The carrier node sits at the LS-DYNA tail point (1,2,3).
        self.assertIn(
            "         5                   1"
            "                   2                   3\n", starter)

    def test_skew_local_x_is_the_motion_direction(self):
        _result, starter = _convert(_deck(self.WALL))
        skew = starter.split("/SKEW/FIX/")[1].splitlines()
        # V = (0,1,0): Y' = z x V = (-1,0,0), Z' = V x Y' = (0,0,1);
        # the starter then rebuilds X' = Y' x Z' = (0,1,0) = V.
        self.assertEqual(_nums(skew[3]), [0.0, 0.0, 0.0])        # origin
        self.assertEqual(_nums(skew[5]), [-1.0, 0.0, 0.0])       # local Y'
        self.assertEqual(_nums(skew[7]), [0.0, 0.0, 1.0])        # local Z'

    def test_motion_direction_parallel_to_global_z_uses_the_fallback(self):
        wall = self.WALL.replace(
            "        99         0       0.0       1.0       0.0\n",
            "        99         0       0.0       0.0       1.0\n")
        _result, starter = _convert(_deck(wall))
        skew = starter.split("/SKEW/FIX/")[1].splitlines()
        # z x V = 0 → fall back to x x V: Y' = (0,-1,0), Z' = V x Y' = (1,0,0),
        # so X' = Y' x Z' = (0,0,1) = V.
        self.assertEqual(_nums(skew[5]), [0.0, -1.0, 0.0])
        self.assertEqual(_nums(skew[7]), [1.0, 0.0, 0.0])

    def test_impvel_drives_the_carrier_node_along_skew_x(self):
        _result, starter = _convert(_deck(self.WALL))
        self.assertIn("/IMPVEL/", starter)
        self.assertNotIn("/IMPDISP/", starter)
        imp = starter.split("/IMPVEL/")[1].splitlines()
        skew_id = int(starter.split("/SKEW/FIX/")[1].splitlines()[0])
        card = imp[3]
        self.assertEqual(card[0:10], "        99")          # funct_IDT = LCID
        self.assertEqual(card[10:20], "         X")         # Dir along skew X'
        self.assertEqual(int(card[20:30]), skew_id)
        grnod_id = int(card[40:50])
        grnod = starter.split(f"/GRNOD/NODE/{grnod_id}\n")[1].splitlines()
        self.assertEqual(grnod[1].split(), ["5"])

    def test_opt_nonzero_selects_impdisp(self):
        wall = self.WALL.replace(
            "        99         0       0.0       1.0       0.0\n",
            "        99         1       0.0       1.0       0.0\n")
        _result, starter = _convert(_deck(wall))
        self.assertIn("/IMPDISP/", starter)
        self.assertNotIn("/IMPVEL/", starter)

    def test_missing_curve_falls_back_to_a_fixed_wall(self):
        wall = self.WALL.replace(
            "        99         0       0.0       1.0       0.0\n",
            "         0         0       0.0       1.0       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/IMPVEL/", starter)
        b = _one(starter, "SPHER")
        self.assertEqual(b[3][0:10], "         0")          # fixed wall
        self.assertEqual(_nums(b[7]), [1.0, 2.0, 3.0])      # XM card is back
        self.assertTrue(any("LCID = 0" in w for w in result.warnings))

    def test_zero_direction_cosines_fall_back_to_a_fixed_wall(self):
        wall = self.WALL.replace(
            "        99         0       0.0       1.0       0.0\n",
            "        99         0       0.0       0.0       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/IMPVEL/", starter)
        self.assertEqual(_one(starter, "SPHER")[3][0:10], "         0")
        self.assertTrue(any("direction cosines VX/VY/VZ are all zero" in w
                            for w in result.warnings))

    def test_prism_motion_drives_all_six_face_nodes(self):
        wall = (
            "*RIGIDWALL_GEOMETRIC_PRISM_MOTION_ID\n"
            "       506moving prism\n"
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       2.0       0.0       0.0       4.0       3.0       5.0\n"
            "        99         0       1.0       0.0       0.0\n"
        )
        _result, starter = _convert(_deck(wall))
        blocks = _blocks(starter, "PARAL")
        self.assertEqual(len(blocks), 6)
        node_ids = [int(b[3][0:10]) for b in blocks]
        self.assertEqual(node_ids, [5, 6, 7, 8, 9, 10])
        imp = starter.split("/IMPVEL/")[1].splitlines()
        grnod_id = int(imp[3][40:50])
        grnod = starter.split(f"/GRNOD/NODE/{grnod_id}\n")[1].splitlines()
        self.assertEqual(grnod[1].split(),
                         ["5", "6", "7", "8", "9", "10"])


class SecondaryNodeTests(unittest.TestCase):
    BODY = (
        "        30\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0\n"
        "       4.0\n"
    )

    def _sphere(self, card1: str) -> str:
        return ("*RIGIDWALL_GEOMETRIC_SPHERE_ID\n"
                "       507sphere\n" + card1
                + "       0.0       0.0       0.0       0.0       0.0       1.0\n"
                  "       4.0\n")

    def test_nsid_becomes_grnd_id1_and_zeroes_the_search_distance(self):
        _result, starter = _convert(_deck(self._sphere("        30\n")))
        b = _one(starter, "SPHER")
        grnd1 = int(b[3][20:30])
        self.assertGreater(grnd1, 0)
        self.assertEqual(b[5][0:20], "                   0")   # d = 0
        grnod = starter.split(f"/GRNOD/NODE/{grnd1}\n")[1].splitlines()
        self.assertEqual(grnod[1].split(), ["1", "2", "3", "4"])

    def test_blank_nsid_tracks_all_nodes_via_the_bbox_search_distance(self):
        # LS-DYNA NSID = 0 tracks ALL nodes; /RWALL has no "all" group id, so
        # grnd_ID1 stays 0 and d is the model bounding-box diagonal.
        _result, starter = _convert(_deck(self._sphere("         0\n")))
        b = _one(starter, "SPHER")
        self.assertEqual(b[3][20:30], "         0")
        self.assertGreater(float(b[5][0:20]), 0.0)

    def test_nsidex_becomes_grnd_id2(self):
        deck = _deck(self._sphere("        30        31\n")).replace(
            "*DEFINE_CURVE\n",
            "*SET_NODE_LIST\n        31\n         3         4\n"
            "*DEFINE_CURVE\n")
        _result, starter = _convert(deck)
        b = _one(starter, "SPHER")
        grnd2 = int(b[3][30:40])
        self.assertGreater(grnd2, 0)
        grnod = starter.split(f"/GRNOD/NODE/{grnd2}\n")[1].splitlines()
        self.assertEqual(grnod[1].split(), ["3", "4"])

    def test_boxid_alone_scopes_the_tracked_group(self):
        deck = _deck(self._sphere("         0         0        77\n")).replace(
            "*DEFINE_CURVE\n",
            "*DEFINE_BOX\n"
            "        77      -0.1       0.6      -0.1       1.1      0.5      1.5\n"
            "*DEFINE_CURVE\n")
        result, starter = _convert(deck)
        b = _one(starter, "SPHER")
        grnd1 = int(b[3][20:30])
        self.assertGreater(grnd1, 0)
        grnod = starter.split(f"/GRNOD/NODE/{grnd1}\n")[1].splitlines()
        self.assertEqual(grnod[1].split(), ["1", "4"])
        self.assertTrue(any("inside *DEFINE_BOX 77" in w
                            for w in result.warnings))

    def test_nsid_wins_over_boxid(self):
        deck = _deck(self._sphere("        30         0        77\n")).replace(
            "*DEFINE_CURVE\n",
            "*DEFINE_BOX\n"
            "        77      -0.1       0.6      -0.1       1.1      0.5      1.5\n"
            "*DEFINE_CURVE\n")
        result, starter = _convert(deck)
        grnd1 = int(_one(starter, "SPHER")[3][20:30])
        grnod = starter.split(f"/GRNOD/NODE/{grnd1}\n")[1].splitlines()
        self.assertEqual(grnod[1].split(), ["1", "2", "3", "4"])
        self.assertTrue(any("BOXID dropped" in w for w in result.warnings))

    def test_birth_death_is_warned(self):
        wall = ("*RIGIDWALL_GEOMETRIC_SPHERE_ID\n"
                "       507sphere\n"
                "        30         0         0       0.1       0.5\n"
                "       0.0       0.0       0.0       0.0       0.0       1.0\n"
                "       4.0\n")
        result, _starter = _convert(_deck(wall))
        self.assertTrue(any("BIRTH/DEATH" in w for w in result.warnings))


class SuffixDispatchTests(unittest.TestCase):
    def test_all_shape_and_option_permutations_are_registered(self):
        from k2rad.handlers import HANDLERS
        keys = [k for k in HANDLERS if k.startswith("RIGIDWALL_GEOMETRIC")]
        # 4 shapes x every ORDERING of {_MOTION,_DISPLAY} (+ _INTERIOR for
        # CYLINDER/SPHERE) — the manual says the option NAMES may appear in
        # any order (p. 3659), only the DATA CARDS are ordered.
        self.assertEqual(len(keys), 42)
        for kw in ("RIGIDWALL_GEOMETRIC_FLAT",
                   "RIGIDWALL_GEOMETRIC_PRISM_MOTION",
                   "RIGIDWALL_GEOMETRIC_CYLINDER_DISPLAY_MOTION",
                   "RIGIDWALL_GEOMETRIC_SPHERE_MOTION_DISPLAY",
                   "RIGIDWALL_GEOMETRIC_CYLINDER_INTERIOR"):
            self.assertIn(kw, HANDLERS)

    def test_id_option_supplies_the_rwall_id_and_title(self):
        wall = (
            "*RIGIDWALL_GEOMETRIC_SPHERE_ID\n"
            "       777my sphere wall\n"          # canonical %10d%-70s, fused
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       4.0\n"
        )
        _result, starter = _convert(_deck(wall))
        b = _one(starter, "SPHER")
        self.assertEqual(b[0], "/RWALL/SPHER/777")
        self.assertEqual(b[1], "my sphere wall")

    def test_display_card_is_parsed_away_and_warned(self):
        wall = (
            "*RIGIDWALL_GEOMETRIC_SPHERE_DISPLAY_ID\n"
            "       508sphere\n"
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       4.0\n"
            "         1    1.0e-9    1.0e-4       0.3\n"
        )
        result, starter = _convert(_deck(wall))
        self.assertIn("/RWALL/SPHER/508", starter)
        self.assertTrue(any("visualization mesh only" in w
                            for w in result.warnings))

    def test_motion_then_display_stack(self):
        wall = (
            "*RIGIDWALL_GEOMETRIC_SPHERE_MOTION_DISPLAY_ID\n"
            "       509sphere\n"
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       4.0\n"
            "        99         0       1.0       0.0       0.0\n"
            "         1    1.0e-9    1.0e-4       0.3\n"
        )
        result, starter = _convert(_deck(wall))
        self.assertIn("/IMPVEL/", starter)
        self.assertTrue(any("visualization mesh only" in w
                            for w in result.warnings))

    def test_interior_warn_skips_instead_of_inverting_the_physics(self):
        wall = (
            "*RIGIDWALL_GEOMETRIC_CYLINDER_INTERIOR\n"
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       2.5       0.0\n"
        )
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/", starter)
        self.assertIn("RIGIDWALL_GEOMETRIC_CYLINDER_INTERIOR",
                      result.skipped_keywords)
        self.assertTrue(any("invert the wall physics" in w
                            for w in result.warnings))

    def test_deform_option_is_not_silently_converted(self):
        # *RIGIDWALL_GEOMETRIC_CYLINDER_DEFORM (R17 manual, absent from the
        # R10.1 cfg) carries two extra cards k2rad does not parse — it must
        # land in skipped_keywords, not be read as a plain cylinder.
        wall = (
            "*RIGIDWALL_GEOMETRIC_CYLINDER_DEFORM\n"
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       2.5       0.0\n"
        )
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/", starter)
        self.assertIn("RIGIDWALL_GEOMETRIC_CYLINDER_DEFORM",
                      result.skipped_keywords)


class MultiWallAndThTests(unittest.TestCase):
    WALLS = (
        "*RIGIDWALL_GEOMETRIC_CYLINDER_ID\n"
        "       601cyl\n"
        "        30\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0\n"
        "       2.5       0.0\n"
        "*RIGIDWALL_GEOMETRIC_SPHERE_ID\n"
        "       602sph\n"
        "        30\n"
        "       5.0       0.0       0.0       5.0       0.0       1.0\n"
        "       1.0\n"
        "*RIGIDWALL_PLANAR_ID\n"
        "       603plane\n"
        "        30         0         0\n"
        "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
        "*DATABASE_RWFORC\n"
        "     0.001\n"
    )

    def test_planar_and_geometric_walls_coexist(self):
        result, starter = _convert(_deck(self.WALLS))
        self.assertEqual([b[0] for b in _blocks(starter, "CYL")],
                         ["/RWALL/CYL/601"])
        self.assertEqual([b[0] for b in _blocks(starter, "SPHER")],
                         ["/RWALL/SPHER/602"])
        self.assertEqual([b[0] for b in _blocks(starter, "PLANE")],
                         ["/RWALL/PLANE/603"])
        self.assertEqual(result.skipped_keywords, [])

    def test_th_rwall_lists_every_wall_including_prism_faces(self):
        walls = self.WALLS.replace(
            "*DATABASE_RWFORC\n",
            "*RIGIDWALL_GEOMETRIC_PRISM_ID\n"
            "       604prism\n"
            "        30\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       2.0       0.0       0.0       4.0       3.0       5.0\n"
            "*DATABASE_RWFORC\n")
        result, starter = _convert(_deck(walls))
        th = starter.split("/TH/RWALL/")[1].splitlines()
        ids = [int(t) for t in th[5:] if t.strip().isdigit()]
        for want in (601, 602, 603, 604):
            self.assertIn(want, ids)
        self.assertEqual(len(ids), 9)      # 3 singles + 6 prism faces
        self.assertTrue(any("split across 6 entries" in w
                            for w in result.warnings))

    def test_no_th_rwall_without_database_rwforc(self):
        walls = self.WALLS.replace("*DATABASE_RWFORC\n     0.001\n", "")
        _result, starter = _convert(_deck(walls))
        self.assertNotIn("/TH/RWALL/", starter)


class PlanarUnchangedTests(unittest.TestCase):
    """A deck WITHOUT the new keywords must emit byte-identical output."""

    WALL = (
        "*RIGIDWALL_PLANAR\n"
        "        30         0         0\n"
        "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
    )

    EXPECTED = (
        "#-  RIGID WALLS:\n"
        "#---1----|----2----|----3----|----4----|----5----|----6----|"
        "----7----|----8----|----9----|---10----|\n"
        "/RWALL/PLANE/{rwid}\n"
        "RWALL_{rwid}\n"
        "#  node_ID     Slide  grnd_ID1  grnd_ID2                   d\n"
        "         0         0{grnd1:>10}         0                   0\n"
        "#                 XM                  YM                  ZM\n"
        "                   0                   0                  -1\n"
        "#                XM1                 YM1                 ZM1\n"
        "                   0                   0                   1\n"
    )

    def test_plain_planar_block_is_byte_identical(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertEqual(result.skipped_keywords, [])
        b = _one(starter, "PLANE")
        rwid = int(b[0].rsplit("/", 1)[1])
        grnd1 = int(b[3][20:30])
        block = starter[starter.index("#-  RIGID WALLS:"):]
        self.assertTrue(block.startswith(
            self.EXPECTED.format(rwid=rwid, grnd1=grnd1)))
        # No geometric-path leakage into a planar-only deck.
        self.assertNotIn("D_search", starter)
        self.assertNotIn("/RWALL/CYL/", starter)
        self.assertNotIn("/RWALL/SPHER/", starter)

    def test_deck_without_any_rigidwall_has_no_rwall_section(self):
        _result, starter = _convert(_deck(""))
        self.assertNotIn("/RWALL", starter)
        self.assertNotIn("#-  RIGID WALLS:", starter)


if __name__ == "__main__":
    unittest.main()
