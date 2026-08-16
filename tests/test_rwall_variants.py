"""Tests for the *RIGIDWALL_PLANAR variant conversions (MOVING / FINITE /
ORTHO).

Card layouts asserted here follow the OpenRadioss hm_cfg_files RWALL cfgs
(config/CFG/radioss110/RWALL/plane.cfg and paral.cfg, FORMAT radioss51 — the
newest FORMAT block <= radioss2022), cross-checked against the starter readers
hm_read_rwall_plane.F / hm_read_rwall_paral.F and the QA decks in the
OpenRadioss repository:

    /RWALL/PLANE|PARAL/<id>
    <title>
    #  node_ID     Slide  grnd_ID1  grnd_ID2          (4 x I10)
    #           D_search                fric            Diameter        ffac ifq
    <d F20><fric F20><Diameter F20><ffac F20><ifq I10>
    then  "XM YM ZM" (3 x F20, fixed wall, node_ID = 0)
    or    "Mass VX0 VY0 VZ0" (4 x F20, moving wall, node_ID > 0)
    then  "XM1 YM1 ZM1" (3 x F20; + "XM2 YM2 ZM2" for PARAL corner points).

Kept in a separate module from tests/test_converter.py so the additions do not
collide with other in-flight work on that large file.
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


# One elastic quad shell at z=1 plus a node set the wall tracks. Node ids are
# 1..4, so a synthesized moving-wall carrier node always gets id 5.
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
    "{WALL}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)


def _deck(wall_cards: str) -> str:
    return BASE_K.replace("{WALL}", wall_cards)


def _rwall_block(starter: str, form: str):
    """Return the /RWALL/<form>/ block's lines (title line first).

    splitlines()[0] is the wall id left over from the split — drop it so
    [0] = title, [1] = first comment, [2] = card 1, ...
    """
    assert f"/RWALL/{form}/" in starter, f"no /RWALL/{form}/ in starter"
    return starter.split(f"/RWALL/{form}/")[1].splitlines()[1:]


class MovingWallTests(unittest.TestCase):
    # tail (0,0,-1), head (0,0,1) → outward unit normal (0,0,1);
    # MASS=10, V0=2 → initial velocity (0,0,2).
    WALL = (
        "*RIGIDWALL_PLANAR_MOVING\n"
        "        30         0         0\n"
        "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
        "      10.0       2.0\n"
    )

    def test_moving_wall_not_skipped(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_PLANAR_MOVING", result.skipped_keywords)
        self.assertIn("/RWALL/PLANE/", starter)

    def test_moving_wall_card_layout(self):
        result, starter = _convert(_deck(self.WALL))
        lines = _rwall_block(starter, "PLANE")
        # lines[0] = title, [1] = card-1 comment, [2] = card 1, [3] = d/fric
        # comment, [4] = d/fric card, [5] = Mass comment, [6] = Mass card,
        # [7] = M1 comment, [8] = M1 card.
        self.assertEqual(lines[1], "#  node_ID     Slide  grnd_ID1  grnd_ID2")
        card1 = lines[2]
        # node_ID = synthesized carrier node 5 (I10), Slide = 0, grnd_ID1 > 0
        self.assertEqual(card1[0:10], "         5")
        self.assertEqual(card1[10:20], "         0")
        self.assertNotEqual(card1[20:30].strip(), "0")
        self.assertEqual(card1[30:40], "         0")
        self.assertEqual(len(card1), 40)          # d is NOT on card 1
        # Card 2: D_search fric Diameter ffac (F20 each) + ifq (I10);
        # d = 0 because a tracked node group is given.
        self.assertIn("D_search", lines[3])
        card2 = lines[4]
        self.assertEqual(card2[0:20].strip(), "0")
        self.assertEqual(card2[20:40].strip(), "0")
        self.assertEqual(card2[40:60].strip(), "0")
        self.assertEqual(card2[60:80].strip(), "0")
        self.assertEqual(card2[80:90], "         0")
        # Moving form: "Mass VX0 VY0 VZ0" replaces "XM YM ZM".
        self.assertIn("Mass", lines[5])
        mass_card = lines[6]
        self.assertEqual(mass_card[0:20].strip(), "10")
        self.assertEqual(mass_card[20:40].strip(), "0")    # VX0
        self.assertEqual(mass_card[40:60].strip(), "0")    # VY0
        self.assertEqual(mass_card[60:80].strip(), "2")    # VZ0 = V0 * nz
        # M1 card is still the head point.
        self.assertEqual(
            [float(t) for t in lines[8].split()], [0.0, 0.0, 1.0])

    def test_moving_wall_synthesizes_carrier_node_at_tail(self):
        result, starter = _convert(_deck(self.WALL))
        # Node 5 at the wall tail (0,0,-1) in the /NODE block.
        self.assertIn(
            "         5                   0"
            "                   0                  -1\n", starter)
        self.assertTrue(any("synthesized free node 5" in w
                            for w in result.warnings))

    def test_moving_forces_flavour_converts_too(self):
        wall = self.WALL.replace("_MOVING", "_MOVING_FORCES")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("RIGIDWALL_PLANAR_MOVING_FORCES",
                         result.skipped_keywords)
        lines = _rwall_block(starter, "PLANE")
        self.assertEqual(lines[6][0:20].strip(), "10")

    def test_moving_wall_zero_mass_falls_back_to_fixed(self):
        wall = self.WALL.replace("      10.0       2.0\n",
                                 "       0.0       2.0\n")
        result, starter = _convert(_deck(wall))
        self.assertTrue(any("non-positive" in w for w in result.warnings))
        lines = _rwall_block(starter, "PLANE")
        # legacy fixed emission: node_ID = 0 and d on card 1
        self.assertIn("d", lines[1])
        self.assertEqual(lines[2][0:10], "         0")


class FiniteWallTests(unittest.TestCase):
    # z-up wall: tail (0,0,0), head (0,0,1) → n = (0,0,1). HEV = (2,0,0) is
    # already in-plane → l = (1,0,0); m = n × l = (0,1,0). LENL=4, LENM=3 →
    # corner points M1 = (4,0,0), M2 = (0,3,0).
    WALL = (
        "*RIGIDWALL_PLANAR_FINITE\n"
        "        30         0         0\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0\n"
        "       2.0       0.0       0.0       4.0       3.0\n"
    )

    def test_finite_wall_emits_paral(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_PLANAR_FINITE", result.skipped_keywords)
        lines = _rwall_block(starter, "PARAL")
        # [0] title, [1] card-1 comment, [2] card 1 (node_ID = 0: fixed),
        # [3]/[4] d card, [5]/[6] XM card, [7]/[8] M1, [9]/[10] M2.
        self.assertEqual(lines[2][0:10], "         0")
        self.assertIn("XM", lines[5])
        self.assertEqual([float(t) for t in lines[6].split()],
                         [0.0, 0.0, 0.0])                     # M = tail
        self.assertIn("XM1", lines[7])
        self.assertEqual([float(t) for t in lines[8].split()],
                         [4.0, 0.0, 0.0])                     # M + LENL*l
        self.assertIn("XM2", lines[9])
        self.assertEqual([float(t) for t in lines[10].split()],
                         [0.0, 3.0, 0.0])                     # M + LENM*(n×l)

    def test_finite_edges_projected_in_plane(self):
        # HEV with an out-of-plane component (2,0,5): projection onto the
        # z=0 plane is (2,0,0) → same l direction as the base case.
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0\n",
            "       2.0       0.0       5.0       4.0       3.0\n")
        result, starter = _convert(_deck(wall))
        lines = _rwall_block(starter, "PARAL")
        self.assertEqual([float(t) for t in lines[8].split()],
                         [4.0, 0.0, 0.0])
        self.assertEqual([float(t) for t in lines[10].split()],
                         [0.0, 3.0, 0.0])

    def test_zero_lenm_falls_back_to_infinite_plane(self):
        # LENM = 0 → infinite extent in the m direction in LS-DYNA;
        # /RWALL/PARAL is strictly finite → documented fallback: infinite
        # /RWALL/PLANE plus a warning.
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0\n",
            "       2.0       0.0       0.0       4.0       0.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/PARAL/", starter)
        self.assertIn("/RWALL/PLANE/", starter)
        self.assertTrue(any("semi-infinite" in w for w in result.warnings))
        # fallback uses the legacy fixed-plane layout (d on card 1)
        lines = _rwall_block(starter, "PLANE")
        self.assertIn("d", lines[1])

    def test_degenerate_hev_falls_back_to_infinite_plane(self):
        # HEV parallel to the normal → no in-plane l direction.
        wall = self.WALL.replace(
            "       2.0       0.0       0.0       4.0       3.0\n",
            "       0.0       0.0       9.0       4.0       3.0\n")
        result, starter = _convert(_deck(wall))
        self.assertNotIn("/RWALL/PARAL/", starter)
        self.assertIn("/RWALL/PLANE/", starter)
        self.assertTrue(any("no in-plane" in w for w in result.warnings))

    def test_finite_moving_combined(self):
        # LS-DYNA appends the option cards in keyword-name order:
        # FINITE card first, then the MOVING card.
        wall = (
            "*RIGIDWALL_PLANAR_FINITE_MOVING\n"
            "        30         0         0\n"
            "       0.0       0.0       0.0       0.0       0.0       1.0\n"
            "       2.0       0.0       0.0       4.0       3.0\n"
            "      10.0       2.0\n"
        )
        result, starter = _convert(_deck(wall))
        self.assertNotIn("RIGIDWALL_PLANAR_FINITE_MOVING",
                         result.skipped_keywords)
        lines = _rwall_block(starter, "PARAL")
        self.assertEqual(lines[2][0:10], "         5")   # carrier node
        self.assertIn("Mass", lines[5])
        mass_card = lines[6]
        self.assertEqual(mass_card[0:20].strip(), "10")
        self.assertEqual(mass_card[60:80].strip(), "2")  # VZ0 = V0 * nz
        self.assertEqual([float(t) for t in lines[8].split()],
                         [4.0, 0.0, 0.0])
        self.assertEqual([float(t) for t in lines[10].split()],
                         [0.0, 3.0, 0.0])


class OrthoWallTests(unittest.TestCase):
    WALL = (
        "*RIGIDWALL_PLANAR_ORTHO\n"
        "        30         0         0\n"
        "       0.0       0.0       0.0       0.0       0.0       1.0\n"
        "         1       0.2       0.1\n"
    )

    def test_ortho_still_warn_skips_with_specific_reason(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("/RWALL", starter)
        self.assertIn("RIGIDWALL_PLANAR_ORTHO", result.skipped_keywords)
        self.assertTrue(any("orthotropic friction" in w
                            for w in result.warnings))


class PlainWallLayoutTests(unittest.TestCase):
    """The fixed infinite wall uses the cfg FORMAT(radioss51) card layout.

    Same 40-column card 1 + 90-column card 2 as every other /RWALL k2rad
    writes (RWALL/plane.cfg). The old emission appended ``d`` to card 1 and
    put a Slide-2 friction on a card of its own; the starter then read every
    following card one line early and the wall came back mis-oriented and
    inert with 0 ERRORS.
    """

    WALL = (
        "*RIGIDWALL_PLANAR\n"
        "        30         0         0\n"
        "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
    )

    def test_plain_planar_uses_the_cfg_layout(self):
        result, starter = _convert(_deck(self.WALL))
        self.assertNotIn("RIGIDWALL_PLANAR", result.skipped_keywords)
        lines = _rwall_block(starter, "PLANE")
        self.assertEqual(
            lines[1], "#  node_ID     Slide  grnd_ID1  grnd_ID2")
        card1 = lines[2]
        self.assertEqual(len(card1), 40)                # exactly 4 x I10
        self.assertEqual(card1[0:10], "         0")     # node_ID = 0
        self.assertEqual(card1[10:20], "         0")    # Slide = 0
        self.assertNotEqual(card1[20:30].strip(), "0")  # grnd_ID1 emitted
        self.assertEqual(
            lines[3],
            "#           D_search                fric            Diameter"
            "                ffac       ifq")
        self.assertEqual(len(lines[4]), 90)             # 20/20/20/20/10
        self.assertEqual(lines[4][0:20].strip(), "0")   # d = 0 (group given)
        self.assertEqual(
            lines[5],
            "#                 XM                  YM                  ZM")
        self.assertEqual([float(t) for t in lines[6].split()],
                         [0.0, 0.0, -1.0])
        self.assertEqual(
            lines[7],
            "#                XM1                 YM1                 ZM1")
        self.assertEqual([float(t) for t in lines[8].split()],
                         [0.0, 0.0, 1.0])
        # A fixed wall never carries the moving form's Mass/V0 card.
        self.assertNotIn("Mass", starter.split("/RWALL/PLANE/")[1])

    def _with_fric(self, fric: str) -> str:
        return self.WALL.replace(
            "       0.0       0.0      -1.0       0.0       0.0       1.0\n",
            "       0.0       0.0      -1.0       0.0       0.0       1.0"
            + fric.rjust(10) + "\n")

    def test_fric_maps_by_exact_value_not_by_threshold(self):
        # *RIGIDWALL_PLANAR Card 2 (Manual p. 40-20): "Coulomb friction
        # coefficient except as noted below: EQ.0.0 frictionless sliding;
        # EQ.1.0 no sliding; EQ.2.0/3.0 node is WELDED after contact ... if
        # and only if the normal impact velocity exceeds WVEL. In summary,
        # FRIC could be any positive value." So the table is a set of exact
        # matches: FRIC = 1.5 is a Coulomb mu of 1.5, not a tie.
        for fric, slide, coeff in (("0.0", 0, 0.0), ("0.3", 2, 0.3),
                                   ("1.0", 1, 0.0), ("1.5", 2, 1.5),
                                   ("4.0", 2, 4.0)):
            with self.subTest(fric=fric):
                result, starter = _convert(_deck(self._with_fric(fric)))
                lines = _rwall_block(starter, "PLANE")
                self.assertEqual(int(lines[2][10:20]), slide)
                self.assertEqual(float(lines[4][20:40]), coeff)
                self.assertFalse([w for w in result.warnings if "FRIC" in w])

    def test_velocity_gated_weld_values_degrade_loudly(self):
        # FRIC 2.0 = weld above WVEL with frictionless sliding; 3.0 = weld
        # above WVEL with no sliding. /RWALL has no velocity gate, so take the
        # closest unconditional mode and say what changed.
        for fric, slide, phrase in (("2.0", 0, "will rebound"),
                                    ("3.0", 1, "UNCONDITIONALLY")):
            with self.subTest(fric=fric):
                result, starter = _convert(_deck(self._with_fric(fric)))
                lines = _rwall_block(starter, "PLANE")
                self.assertEqual(int(lines[2][10:20]), slide)
                self.assertTrue(any("WVEL" in w and phrase in w
                                    for w in result.warnings), result.warnings)


class ForcesCardTests(unittest.TestCase):
    """The ``_FORCES`` option's Card 7: ``SOFT SSID N1 N2 N3 N4``.

    The Card Summary (Manual p. 40-17) fixes the order regardless of how the
    options are spelled in the keyword name — ID, 1, 2, [ORTHO 3+4], [FINITE 5],
    [MOVING 6], [FORCES 7] — so the FORCES card is ALWAYS last. (There is no
    second FORCES card and no ``WPSET`` field: a full-text scan of Vol I R16 and
    R17 returns zero pages containing that string.)

    The card used to go unread, which cost two things: SOFT/SSID vanished with
    no trace, and the "further card line(s)" multi-card-set guard could not be
    extended to the planar family at all, because the wall's own FORCES card
    would have been counted as a phantom second wall on all 15 corpus
    *RIGIDWALL_PLANAR_MOVING_FORCES decks.
    """

    PLAIN = (
        "*RIGIDWALL_PLANAR_FORCES\n"
        "        30         0         0\n"
        "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
        "{FORCES}"
    )
    # The shape every corpus _FORCES deck actually uses (W8 CrushBox): all
    # defaults except a visualization node.
    W8_SHAPE = "         0         0     99999\n"

    def test_forces_card_defaults_stay_silent(self):
        """W8's own card set: SOFT=0, SSID=0, N1 only → nothing to report."""
        result, starter = _convert(
            _deck(self.PLAIN.replace("{FORCES}", self.W8_SHAPE)))
        self.assertIn("/RWALL/PLANE/", starter)
        self.assertEqual(
            [w for w in result.warnings if "FORCES" in w or "further card" in w],
            [])

    def test_soft_and_ssid_are_reported_not_dropped(self):
        result, _s = _convert(_deck(
            self.PLAIN.replace("{FORCES}", "         3         7     99999\n")))
        self.assertTrue(any("SOFT=3" in w for w in result.warnings),
                        result.warnings)
        self.assertTrue(any("SSID=7" in w for w in result.warnings),
                        result.warnings)

    def test_visualization_nodes_alone_stay_silent(self):
        """N1..N4 are "Optional node for visualization" — no solution effect,
        so all four present must still produce no warning."""
        result, _s = _convert(_deck(self.PLAIN.replace(
            "{FORCES}", "         0         0         1         2         3"
                        "         4\n")))
        self.assertEqual([w for w in result.warnings if "FORCES" in w], [])

    def test_moving_forces_stacks_mass_card_then_forces_card(self):
        """_MOVING_FORCES: Card 6 (MASS V0) then Card 7 — the FORCES card must
        not be read as the moving card, nor counted as a second wall."""
        wall = ("*RIGIDWALL_PLANAR_MOVING_FORCES\n"
                "        30         0         0\n"
                "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
                "      10.0       2.0\n"
                "         5         9     99999\n")
        result, starter = _convert(_deck(wall))
        lines = _rwall_block(starter, "PLANE")
        # The MOVING card still landed on the Mass card, not the FORCES card.
        self.assertEqual(lines[6][0:20].strip(), "10")
        self.assertEqual(lines[6][60:80].strip(), "2")     # VZ0 = V0 * nz
        self.assertTrue(any("SOFT=5" in w for w in result.warnings))
        self.assertTrue(any("SSID=9" in w for w in result.warnings))
        self.assertEqual(
            [w for w in result.warnings if "further card line" in w], [])

    def test_second_card_set_is_caught_on_the_plain_family(self):
        """A planar keyword may carry several walls; k2rad converts the first
        only and must never let the rest vanish (Manual p. 40-5)."""
        wall = ("*RIGIDWALL_PLANAR\n"
                "        30         0         0\n"
                "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
                "        30         0         0\n"
                "       0.0       0.0       5.0       0.0       0.0      -1.0\n")
        result, _s = _convert(_deck(wall))
        hits = [w for w in result.warnings if "further card line" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("2 further card line(s)", hits[0])
        self.assertIn(
            ("RIGIDWALL_PLANAR",
             "only the first of several card sets under the keyword was "
             "converted"),
            result.recognized_not_emitted)

    def test_second_card_set_counted_past_the_forces_card(self):
        """The guard must start counting AFTER Card 7, not at it."""
        wall = (
            "*RIGIDWALL_PLANAR_FORCES\n"
            "        30         0         0\n"
            "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
            "         0         0     99999\n"
            "        30         0         0\n"
            "       0.0       0.0       5.0       0.0       0.0      -1.0\n"
            "         0         0\n")
        result, _s = _convert(_deck(wall))
        hits = [w for w in result.warnings if "further card line" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("3 further card line(s)", hits[0])

    def test_comments_around_the_cards_do_not_trip_the_guard(self):
        """`$` comments are stripped by the parser (parser.py:287) and never
        reach block.raw, so a commented deck must not read as a second wall —
        the false positive that would make the guard unusable in practice."""
        wall = ("*RIGIDWALL_PLANAR_FORCES\n"
                "$ card 1\n"
                "        30         0         0\n"
                "$ card 2: tail, head, fric\n"
                "       0.0       0.0      -1.0       0.0       0.0       1.0\n"
                "$ card 7: soft ssid n1\n"
                "         0         0     99999\n"
                "$ nothing follows\n")
        result, starter = _convert(_deck(wall))
        self.assertIn("/RWALL/PLANE/", starter)
        self.assertEqual(
            [w for w in result.warnings if "further card line" in w], [])

    def test_every_ortho_spelling_warn_skips_with_a_reason(self):
        """All 8 ORTHO spellings must reach handle_rigidwall_ortho. Three of
        them had no registry row, so they fell through to the generic
        skipped-keyword list with no reason attached (there is no
        RIGIDWALL_PLANAR prefix fallback to catch them)."""
        for opts in ("", "_FORCES", "_FINITE", "_MOVING", "_FINITE_MOVING",
                     "_MOVING_FORCES", "_FINITE_FORCES",
                     "_FINITE_MOVING_FORCES"):
            kw = f"RIGIDWALL_PLANAR_ORTHO{opts}"
            with self.subTest(kw=kw):
                wall = (
                    f"*{kw}\n"
                    "        30         0         0\n"
                    "       0.0       0.0      -1.0       0.0       0.0"
                    "       1.0\n")
                result, starter = _convert(_deck(wall))
                self.assertNotIn("/RWALL/", starter)
                self.assertEqual(result.skipped_keywords, [kw])
                self.assertTrue(
                    any("orthotropic friction (ORTHO)" in w
                        for w in result.warnings), result.warnings)


if __name__ == "__main__":
    unittest.main()
