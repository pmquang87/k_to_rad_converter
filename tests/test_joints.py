"""Tests for the JOINT conversions:

  *CONSTRAINED_JOINT_SPHERICAL / _REVOLUTE / _CYLINDRICAL / _PLANAR /
  _UNIVERSAL / _TRANSLATIONAL / _LOCKING (+ _LOCAL / _FAILURE / _ID / _TITLE)
      -> /PROP/TYPE45 (KJOINT2) + /PART + 2..4-node /SPRING (+ /SKEW/FIX)
  *CONSTRAINED_JOINT_STIFFNESS_GENERALIZED / _TRANSLATIONAL
      -> that property's per-DOF stiffness / damping / friction / stop blocks

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_connectors.py and tests/test_roadmap_keywords.py).
"""

import math
import os
import re
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"


# ── Harness ──────────────────────────────────────────────────────────────────

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


def _row(*vals) -> str:
    """One LS-DYNA fixed-width card: every field right-justified in 10 cols."""
    return "".join(f"{v:>10}" for v in vals)


def _blocks(starter: str, header: str):
    """Every block whose first line starts with *header*, as a list of its lines
    (header line included, the trailing HDR ruler excluded)."""
    out, cur = [], None
    for ln in starter.splitlines():
        if ln.startswith(header):
            cur = [ln]
            out.append(cur)
        elif cur is not None:
            if ln.startswith("#---1----"):
                cur = None
            else:
                cur.append(ln)
    return out


def _cards(block):
    """A block's DATA lines: everything after the title that is not a comment.

    For /PROP/TYPE45 that is card 1 followed by three cards per free DOF:
      [0] Type/Kn/ScF/Cr/sens/Skew1/Skew2
      [1] Kr|Kt, fct_K, stop-, stop+, Icomb     (DOF 1, card A)
      [2] Cr|Ct, fct_C                          (DOF 1, card B)
      [3] Kfr|Kft, FM|FF, fct_fm|fct_ff         (DOF 1, card C)
      [4..] the same three for each further DOF
    """
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _f20(line: str, i: int) -> float:
    return float(line[i * 20:(i + 1) * 20] or 0)


# ── Decks ────────────────────────────────────────────────────────────────────

# Node 1/2 = the coincident joint point (body A / body B).
# Node 3/4 = the coincident axis point,  10 mm along +X.
# Node 5/6 = the coincident roll point,   4 mm along +Y.
# Node 7   = a NON-coincident cross-axle point for the universal joint.
NODES = (
    "*NODE\n"
    + "".join(
        f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
            (1, 0.0, 0.0, 0.0), (2, 0.0, 0.0, 0.0),
            (3, 10.0, 0.0, 0.0), (4, 10.0, 0.0, 0.0),
            (5, 0.0, 4.0, 0.0), (6, 0.0, 4.0, 0.0),
            (7, 0.0, 4.0, 0.0),
            (11, 0.0, 0.0, 0.0), (12, 1.0, 0.0, 0.0),
            (13, 1.0, 1.0, 0.0), (14, 0.0, 1.0, 0.0),
            (21, 5.0, 0.0, 0.0), (22, 6.0, 0.0, 0.0),
            (23, 6.0, 1.0, 0.0), (24, 5.0, 1.0, 0.0),
        ))
)

BODIES = (
    "*PART\n"
    "body A\n"
    + _row(1, 1, 1) + "\n"
    "*PART\n"
    "body B\n"
    + _row(2, 1, 1) + "\n"
    "*SECTION_SHELL\n"
    + _row(1, 2) + "\n"
    + _row(1.0) + "\n"
    "*MAT_RIGID\n"
    + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
    "*ELEMENT_SHELL\n"
    "       1       1      11      12      13      14\n"
    "       2       2      21      22      23      24\n"
    # Put every joint node on one of the two rigid bodies, so the
    # "node belongs to no /RBODY" check stays quiet unless a test wants it.
    "*CONSTRAINED_EXTRA_NODES_NODE\n"
    + "".join(_row(p, n) + "\n" for p, n in
             ((1, 1), (1, 3), (1, 5), (2, 2), (2, 4), (2, 6), (2, 7)))
)


def _deck(joints: str, extra: str = "", bodies: str = BODIES) -> str:
    return ("*KEYWORD\n" + NODES + bodies + joints + extra
            + "*CONTROL_TERMINATION\n" + _row(1.0) + "\n*END\n")


def _joint(kind: str, *nodes, rps="", damp="", opts="", jid=0,
           title="") -> str:
    """One *CONSTRAINED_JOINT_<kind> card. A non-zero *jid* adds the _ID option
    and its heading line, which is what a *CONSTRAINED_JOINT_STIFFNESS JID
    points at."""
    vals = list(nodes) + [""] * (6 - len(nodes)) + [rps, damp]
    head = ""
    if jid:
        if "_ID" not in opts:
            opts += "_ID"
        head = f"{jid:>10}{title}\n"
    return f"*CONSTRAINED_JOINT_{kind}{opts}\n" + head + _row(*vals) + "\n"


# ── Per-kind /PROP/TYPE45 Type integer and /SPRING node selection ────────────

class TestEveryJointKind(unittest.TestCase):
    """The Type integer and the /SPRING node list, per joint kind.

    Type integers are verified against prop_p45_kjoint2.cfg:261-272 and against
    dyna2rad's own dispatch. LOCKING is 8 (Fixed/Rigid), NOT 7 (Oldham).
    """

    # kind -> (Type, spring nodes, number of 3-card DOF blocks the Type needs)
    CASES = {
        "SPHERICAL":     (1, [1, 2], 3),
        "REVOLUTE":      (2, [1, 2, 3], 1),
        "CYLINDRICAL":   (3, [1, 2, 3], 2),
        "PLANAR":        (4, [1, 2, 3], 3),
        "UNIVERSAL":     (5, [1, 2, 3, 7], 2),
        "TRANSLATIONAL": (6, [1, 2, 3], 1),
        "LOCKING":       (8, [1, 2, 3, 5], 0),
    }

    def test_type_integer_and_spring_nodes(self):
        for kind, (jtype, nodes, _ndof) in self.CASES.items():
            with self.subTest(kind=kind):
                if kind == "UNIVERSAL":
                    card = _joint(kind, 1, 2, 3, 7)
                elif kind in ("TRANSLATIONAL", "LOCKING"):
                    card = _joint(kind, 1, 2, 3, 4, 5, 6)
                elif kind == "SPHERICAL":
                    card = _joint(kind, 1, 2)
                else:
                    card = _joint(kind, 1, 2, 3, 4)
                _, starter = _convert(_deck(card))

                prop = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
                self.assertEqual(int(prop[0][0:10]), jtype)

                spring = _blocks(starter, "/SPRING/")[0]
                got = [int(spring[-1][i * 10:(i + 1) * 10])
                       for i in range(1, len(nodes) + 1)]
                self.assertEqual(got, nodes)
                # No trailing node slot beyond the ones the kind uses.
                self.assertEqual(len(spring[-1].rstrip()),
                                 10 * (len(nodes) + 1))

    def test_locking_forwards_n5_and_drops_n4_n6(self):
        """LOCKING's /SPRING is {N1, N2, N3, N5} — both of body A's auxiliary
        nodes. N4 and N6 (body B's, coincident with them) are dropped, so the
        4-node frame is x = N3-N1, ybar = N5-N1."""
        _, starter = _convert(_deck(_joint("LOCKING", 1, 2, 3, 4, 5, 6)))
        row = _blocks(starter, "/SPRING/")[0][-1]
        self.assertEqual([int(row[i * 10:(i + 1) * 10]) for i in range(1, 5)],
                         [1, 2, 3, 5])

    def test_kinematic_joint_emits_no_dof_blocks(self):
        """Without a stiffness card a joint is header + title + card 1 only.

        The DOF blocks are all-or-nothing: the starter counts them against the
        Type's requirement and raises ERROR 973 (ONLY %d DOF DEFINED %d
        REQUIRED) on a partial set, so 'none' is the only safe empty state."""
        for kind in self.CASES:
            with self.subTest(kind=kind):
                _, starter = _convert(_deck(_joint(kind, 1, 2, 3, 4, 5, 6)))
                self.assertEqual(len(_cards(_blocks(starter,
                                                    "/PROP/TYPE45/")[0])), 1)

    def test_part_carries_mat_id_zero_and_owns_the_spring_block(self):
        """/PART data card is prop_ID, mat_ID, subset_ID. mat_ID = 0 is legal
        for IGTYP 45 (hm_read_part.F:215-236 excludes 45 from the ERROR 179
        list and substitutes an internal spring material), and the /SPRING
        block id IS the /PART id."""
        _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        part = _blocks(starter, "/PART/9")[0]
        prop_id = int(_blocks(starter, "/PROP/TYPE45/")[0][0].rsplit("/", 1)[1])
        part_id = int(part[0].rsplit("/", 1)[1])
        self.assertEqual(int(part[2][0:10]), prop_id)
        self.assertEqual(int(part[2][10:20]), 0)        # mat_ID
        self.assertEqual(int(part[2][20:30]), 0)        # subset_ID
        self.assertIn(f"/SPRING/{part_id}", starter)
        self.assertNotIn("/MAT/VOID", starter)


# ── /SKEW axis construction from node geometry ───────────────────────────────

class TestJointFrame(unittest.TestCase):
    """The /SKEW/FIX carries local Y' then Z'; the starter rebuilds X' = Y' x Z'.

    The construction mirrors GET_SKEW45 (rini45.F:380-658) so the skew is the
    same frame the starter would build from the nodes — it is a fallback branch
    (tested last), and writing it is what suppresses ERROR 936 on a short node
    list.
    """

    def _skew_axes(self, starter):
        blk = _blocks(starter, "/SKEW/FIX/")[0]
        rows = [ln for ln in blk[2:] if not ln.startswith("#")]
        return [tuple(round(_f20(r, i), 9) for i in range(3)) for r in rows]

    def test_three_node_axis_is_n1_to_n3(self):
        """3 nodes -> x = spring node 3 - node 1, transverse axes by the
        largest-|component| rule: x=(1,0,0) -> y=(0,1,0), z=x cross y=(0,0,1)."""
        _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        origin, yax, zax = self._skew_axes(starter)
        self.assertEqual(origin, (0.0, 0.0, 0.0))
        self.assertEqual(yax, (0.0, 1.0, 0.0))
        self.assertEqual(zax, (0.0, 0.0, 1.0))

    def test_four_node_frame_uses_n1_n3_n5(self):
        """LOCKING: x = N3-N1 = +X, ybar = N5-N1 = +Y, z = x cross ybar = +Z,
        y = z cross x = +Y."""
        _, starter = _convert(_deck(_joint("LOCKING", 1, 2, 3, 4, 5, 6)))
        _origin, yax, zax = self._skew_axes(starter)
        self.assertEqual(yax, (0.0, 1.0, 0.0))
        self.assertEqual(zax, (0.0, 0.0, 1.0))

    def test_universal_frame_is_y_z_not_x_y(self):
        """Type 5 alone assigns the two node directions to y and z and derives
        x = y cross z (rini45.F:587-612). With N3 on +X and N4 on +Y that is
        y=(1,0,0), z=(0,1,0), so the rebuilt X' = Y' x Z' = (0,0,1)."""
        _, starter = _convert(_deck(_joint("UNIVERSAL", 1, 2, 3, 7)))
        _origin, yax, zax = self._skew_axes(starter)
        self.assertEqual(yax, (1.0, 0.0, 0.0))
        self.assertEqual(zax, (0.0, 1.0, 0.0))
        # X' = Y' x Z' must come back out as +Z.
        xax = (yax[1] * zax[2] - yax[2] * zax[1],
               yax[2] * zax[0] - yax[0] * zax[2],
               yax[0] * zax[1] - yax[1] * zax[0])
        self.assertEqual(xax, (0.0, 0.0, 1.0))

    def test_skew_axes_are_orthonormal_and_right_handed(self):
        """For an oblique axis the transverse rule must still produce a unit,
        right-handed triad — Radioss reads Y'/Z' verbatim."""
        nodes = NODES.replace(f"{3:>8}{10.0:>16}{0.0:>16}{0.0:>16}",
                              f"{3:>8}{3.0:>16}{4.0:>16}{12.0:>16}")
        deck = ("*KEYWORD\n" + nodes + BODIES + _joint("REVOLUTE", 1, 2, 3, 4)
                + "*CONTROL_TERMINATION\n" + _row(1.0) + "\n*END\n")
        _, starter = _convert(deck)
        _origin, y, z = self._skew_axes(starter)
        self.assertAlmostEqual(math.dist(y, (0, 0, 0)), 1.0, places=8)
        self.assertAlmostEqual(math.dist(z, (0, 0, 0)), 1.0, places=8)
        self.assertAlmostEqual(sum(a * b for a, b in zip(y, z)), 0.0, places=8)
        x = (y[1] * z[2] - y[2] * z[1], y[2] * z[0] - y[0] * z[2],
             y[0] * z[1] - y[1] * z[0])
        # X' = Y' x Z' must be the joint axis N1->N3 = (3,4,12)/13.
        for got, want in zip(x, (3 / 13, 4 / 13, 12 / 13)):
            self.assertAlmostEqual(got, want, places=8)

    def test_skew_id_lands_in_prop_card_field_and_is_referenced(self):
        _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        sid = int(_blocks(starter, "/SKEW/FIX/")[0][0].rsplit("/", 1)[1])
        card1 = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(int(card1[80:90]), sid)       # Skew_ID1
        self.assertEqual(int(card1[90:100]), 0)        # Skew_ID2 stays unset

    def test_coincident_spherical_gets_no_skew_and_no_warning(self):
        """N1/N2 of a spherical joint are coincident by design, so no frame is
        derivable — and none is needed: with 2 nodes and Skew_ID1 = 0 the
        starter uses the global frame for Type 1/8 (rini45.F:439-454), and all
        three rotations are free anyway."""
        res, starter = _convert(_deck(_joint("SPHERICAL", 1, 2)))
        self.assertEqual(_blocks(starter, "/SKEW/FIX/"), [])
        self.assertEqual(int(_cards(_blocks(starter,
                                            "/PROP/TYPE45/")[0])[0][80:90]), 0)
        self.assertFalse([w for w in res.warnings if "degenerate" in w])

    def test_degenerate_axis_is_warned(self):
        """A revolute joint whose N3 sits on N1 has no axis. The starter would
        abort with ERROR 935 (NODE 1 AND NODE 3 ARE COINCIDENT); say so first."""
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 2, 2)))
        hits = [w for w in res.warnings if "axis is degenerate" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("ERROR 935", hits[0])

    def test_short_node_list_warns_about_error_936(self):
        """Type 2 needs 3 spring nodes. With N3 blank there are 2, and no frame
        to stand in for them -> starter ERROR 936."""
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2)))
        hits = [w for w in res.warnings if "ERROR 936" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("needs 3 spring nodes", hits[0])


# ── RPS / DAMP ───────────────────────────────────────────────────────────────

class TestPenaltyAndDamping(unittest.TestCase):
    """RPS -> ScF, DAMP -> nothing. Neither is the same quantity as its target:
    RPS is a dimensionless relative penalty multiplier while ScF is a
    length-squared floor in Kn*MAX(ScF, L^2); DAMP scales an internal damping
    while Cr is an absolute critical-damping ratio in [0,1]."""

    def _card1(self, deck):
        _, starter = _convert(deck)
        return _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]

    def test_kn_and_cr_stay_zero(self):
        """Kn = 0 asks the starter to derive the blocking stiffness from the
        time step; Cr = 0 takes its 0.05 default (hm_read_prop45.F:155)."""
        c = self._card1(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        self.assertEqual(float(c[10:30]), 0.0)            # Kn  (cols 11-30)
        self.assertEqual(float(c[50:70]), 0.0)            # Cr  (cols 51-70)
        self.assertEqual(int(c[70:80]), 0)                # sens_ID

    def test_default_rps_gives_scf_one_without_a_warning(self):
        res, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(float(c[30:50]), 1.0)
        self.assertFalse([w for w in res.warnings if "ScF" in w])

    def test_positive_rps_is_carried_into_scf_without_a_warning(self):
        """With Kn = 0 the engine applies ScF as a plain multiplier on the
        stiffness it computes (KX = ScF*KX, joint_block_stiffness.F:220), which
        is exactly LS-DYNA's dimensionless RPS — so the mapping is EXACT and
        must not be warned about."""
        res, starter = _convert(
            _deck(_joint("REVOLUTE", 1, 2, 3, 4, rps=2.5)))
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(float(c[30:50]), 2.5)
        self.assertFalse([w for w in res.warnings if "RPS" in w])

    def test_zero_rps_gives_the_lsdyna_default_scf_one(self):
        """LS-DYNA's fixed-format reader cannot tell a blank RPS column from an
        explicit 0.0, and its default is 1.0. Writing 0.01 (dyna2rad's fallback)
        would make the joint 100x softer than the deck asks for."""
        res, starter = _convert(
            _deck(_joint("REVOLUTE", 1, 2, 3, 4, rps=0.0)))
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(float(c[30:50]), 1.0)
        self.assertFalse([w for w in res.warnings if "RPS" in w])

    def test_negative_rps_drops_the_curve_and_uses_scf_one(self):
        """RPS < 0 means -RPS is a load-curve id for the penalty scale, which
        /PROP/TYPE45 cannot express: the curve is dropped loudly and ScF falls
        back to LS-DYNA's own default of 1.0, not to 0.01."""
        res, starter = _convert(
            _deck(_joint("REVOLUTE", 1, 2, 3, 4, rps=-7)))
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(float(c[30:50]), 1.0)
        self.assertTrue([w for w in res.warnings if "load-curve id" in w])

    def test_stiffness_card_rps_is_honoured_only_for_translational(self):
        """R16 Vol I p.10-91: RPS on *CONSTRAINED_JOINT_STIFFNESS "only applies
        for keyword options TRANSLATIONAL and CYLINDRICAL"."""
        _, starter = _convert(_deck(
            _joint("REVOLUTE", 1, 2, 3, 4, rps=2.5, jid=77, title="hinge"),
            extra=COORD_X + CURVES + _stiff_gen(jid=77, rps=7.0)))
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(float(c[30:50]), 2.5)     # the JOINT card's RPS wins

        _, starter = _convert(_deck(
            _joint("TRANSLATIONAL", 1, 2, 3, 4, rps=2.5, jid=78,
                   title="slider"),
            extra=COORD_X + CURVES + _stiff_trans(jid=78, rps=7.0)))
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(float(c[30:50]), 7.0)     # the STIFFNESS card's RPS

    def test_non_default_damp_is_dropped_loudly(self):
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4, damp=0.5)))
        hits = [w for w in res.warnings if "DAMP=0.5 was DROPPED" in w]
        self.assertEqual(len(hits), 1)

    def test_default_damp_is_silent(self):
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4, damp=1.0)))
        self.assertFalse([w for w in res.warnings if "DAMP" in w])

    def test_zero_damp_is_the_lsdyna_default_and_stays_silent(self):
        """R16 Vol I p.10-64: "EQ.0.0: Default is set to 1.0". A deck written
        with explicit zeros must not collect a spurious drop warning."""
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4, damp=0.0)))
        self.assertFalse([w for w in res.warnings if "DAMP" in w])

    def test_tiny_damp_means_no_damping_and_says_cr_cannot_express_it(self):
        """0 < DAMP <= 0.01 is LS-DYNA's "no damping"; Radioss replaces a zero
        Cr with 0.05, so the converted joint keeps 5% critical damping."""
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4, damp=0.005)))
        hits = [w for w in res.warnings if "NO joint damping" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("0.05", hits[0])


# ── *CONSTRAINED_JOINT_STIFFNESS ─────────────────────────────────────────────

CURVES = (
    "*DEFINE_CURVE\n" + _row(900) + "\n"
    + f"{0.0:>20}{0.0:>20}\n{1.0:>20}{1000.0:>20}\n"
    "*DEFINE_CURVE\n" + _row(901) + "\n"
    + f"{0.0:>20}{0.0:>20}\n{1.0:>20}{10.0:>20}\n"
    "*DEFINE_CURVE\n" + _row(902) + "\n"
    + f"{0.0:>20}{0.0:>20}\n{1.0:>20}{5.0:>20}\n"
)

COORD_X = ("*DEFINE_COORDINATE_SYSTEM\n"
           + _row(1, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
           + _row(0.0, 1.0, 0.0) + "\n")


def _stiff_gen(jid=0, pida=0, pidb=0, cida=1, cidb=1,
               lcid=(900, 0, 0), dlcid=(901, 0, 0),
               es=(500.0, 0.0, 0.0), fm=(25.0, 0.0, 0.0),
               nsa=(15.0, 0.0, 0.0), psa=(30.0, 0.0, 0.0), rps="") -> str:
    return ("*CONSTRAINED_JOINT_STIFFNESS_GENERALIZED\n"
            + _row(1, pida, pidb, cida, cidb, jid, rps) + "\n"
            + _row(*lcid, *dlcid) + "\n"
            + _row(es[0], fm[0], es[1], fm[1], es[2], fm[2]) + "\n"
            + _row(nsa[0], psa[0], nsa[1], psa[1], nsa[2], psa[2]) + "\n")


def _stiff_trans(jid=0, pida=1, pidb=2, cida=1, cidb=1, rps="",
                 es=(0.0, 0.0, 0.0), ff=(0.0, 0.0, 0.0),
                 lcid=(0, 0, 0), dlcid=(0, 0, 0),
                 nsd=(0.0, 0.0, 0.0), psd=(0.0, 0.0, 0.0),
                 fs="", fd="") -> str:
    return ("*CONSTRAINED_JOINT_STIFFNESS_TRANSLATIONAL\n"
            + _row(2, pida, pidb, cida, cidb, jid, rps) + "\n"
            + _row(*lcid, *dlcid) + "\n"
            + _row(es[0], ff[0], es[1], ff[1], es[2], ff[2]) + "\n"
            + _row(nsd[0], psd[0], nsd[1], psd[1], nsd[2], psd[2], fs, fd)
            + "\n")


class TestGeneralizedStiffness(unittest.TestCase):
    DECK = _deck(
        _joint("REVOLUTE", 1, 2, 3, 4, opts="_ID").replace(
            "*CONSTRAINED_JOINT_REVOLUTE_ID\n",
            "*CONSTRAINED_JOINT_REVOLUTE_ID\n" + f"{77:>10}" + "hinge\n"),
        extra=COORD_X + CURVES + _stiff_gen(jid=77))

    def test_dof_block_field_positions(self):
        """Card A: K(20) fct_K(10) stop-(20) stop+(20) Icomb(10).
           Card B: C(20) fct_C(10).      Card C: Kf(20) limit(20) fct_f(10)."""
        _, starter = _convert(self.DECK)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(len(c), 4)                 # card 1 + one Rx DOF block
        a, b, cc = c[1], c[2], c[3]
        self.assertEqual(float(a[0:20]), 0.0)       # Krx = the curve's scale
        self.assertEqual(int(a[20:30]), 900)        # fct_Krx  <- LCIDPH
        self.assertEqual(int(a[70:80]), 0)          # Icomb_rx stays independent
        self.assertEqual(float(b[0:20]), 0.0)       # Crx
        self.assertEqual(int(b[20:30]), 901)        # fct_Crx  <- DLCIDPH
        self.assertEqual(float(cc[0:20]), 500.0)    # Kfrx     <- ESPH
        self.assertEqual(float(cc[20:40]), 25.0)    # FMx      <- FMPH
        self.assertEqual(int(cc[40:50]), 0)         # fct_fmx

    def test_stop_angles_are_converted_to_radians_and_sign_forced(self):
        """LS-DYNA NSA*/PSA* are DEGREES, Radioss SA+/- are RADIANS. SA- > 0 is
        ERROR 943 and SA+ < 0 is ERROR 944, so the signs are forced regardless
        of how the .k wrote them."""
        _, starter = _convert(self.DECK)
        a = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[1]
        self.assertAlmostEqual(float(a[30:50]), -15.0 * math.pi / 180, places=9)
        self.assertAlmostEqual(float(a[50:70]), 30.0 * math.pi / 180, places=9)

    def test_stop_signs_are_forced_even_when_the_deck_inverts_them(self):
        deck = _deck(
            _joint("REVOLUTE", 1, 2, 3, 4),
            extra=COORD_X + CURVES + _stiff_gen(pida=1, pidb=2,
                                                nsa=(-15.0, 0, 0),
                                                psa=(-30.0, 0, 0)))
        _, starter = _convert(deck)
        a = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[1]
        self.assertLess(float(a[30:50]), 0.0)
        self.assertGreater(float(a[50:70]), 0.0)

    def test_negative_fm_becomes_the_friction_curve_field(self):
        """A negative FM*/FF* means -FM* is a curve id for the yield moment. In
        Radioss that is the separate fct_fm* field, and the magnitude must stay
        blank (the starter then reads it as a 1.0 scale)."""
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES
                     + _stiff_gen(pida=1, pidb=2, fm=(-902.0, 0.0, 0.0)))
        _, starter = _convert(deck)
        cc = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[3]
        self.assertEqual(float(cc[20:40]), 0.0)
        self.assertEqual(int(cc[40:50]), 902)

    def test_missing_curve_reference_is_dropped_and_warned(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES + _stiff_gen(pida=1, pidb=2,
                                                         lcid=(4242, 0, 0)))
        res, starter = _convert(deck)
        a = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[1]
        self.assertEqual(int(a[20:30]), 0)
        self.assertTrue([w for w in res.warnings
                         if "4242 is not defined by any *DEFINE_CURVE" in w])

    def test_spherical_joint_gets_all_three_rotational_blocks(self):
        """Type 1 has Rx, Ry, Rz — phi/theta/psi map onto them directly, which
        is the documented Euler approximation and must be warned about."""
        deck = _deck(_joint("SPHERICAL", 1, 2),
                     extra=COORD_X + CURVES
                     + _stiff_gen(pida=1, pidb=2, lcid=(900, 901, 902),
                                  es=(1.0, 2.0, 3.0), fm=(4.0, 5.0, 6.0)))
        res, starter = _convert(deck)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(len(c), 1 + 3 * 3)
        self.assertEqual([int(c[i][20:30]) for i in (1, 4, 7)],
                         [900, 901, 902])
        self.assertEqual([float(c[i][0:20]) for i in (3, 6, 9)],
                         [1.0, 2.0, 3.0])
        self.assertTrue([w for w in res.warnings if "z-y-z EULER angles" in w])

    def test_spherical_stiffness_reuses_cida_as_the_joint_frame(self):
        """A coincident-node spherical joint has no node-derived frame, so the
        coordinate system its LS-DYNA angles are measured in is the right one
        for Rx/Ry/Rz."""
        deck = _deck(_joint("SPHERICAL", 1, 2),
                     extra=COORD_X + CURVES + _stiff_gen(pida=1, pidb=2))
        res, starter = _convert(deck)
        card1 = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[0]
        self.assertEqual(int(card1[80:90]), 1)          # /SKEW of CIDA=1
        self.assertTrue([w for w in res.warnings
                         if "Skew_ID1 = the converted /SKEW of CIDA=1" in w])

    def test_channel_the_type_cannot_hold_is_dropped_loudly(self):
        """A revolute joint has one free DOF. theta/psi data has nowhere to go."""
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES
                     + _stiff_gen(pida=1, pidb=2, lcid=(900, 901, 902)))
        res, starter = _convert(deck)
        self.assertEqual(len(_cards(_blocks(starter, "/PROP/TYPE45/")[0])), 4)
        dropped = [w for w in res.warnings if "channel carries data" in w]
        self.assertEqual(len(dropped), 2)
        self.assertTrue(any("theta" in w for w in dropped))
        self.assertTrue(any("psi" in w for w in dropped))

    def test_zero_stop_stiffness_with_stops_is_warned(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES
                     + _stiff_gen(pida=1, pidb=2, es=(0.0, 0.0, 0.0)))
        res, _ = _convert(deck)
        self.assertTrue([w for w in res.warnings
                         if "simply violated" in w])

    def test_axis_match_picks_the_aligned_euler_channel(self):
        """CIDA's LOCAL Y is the joint axis here, so theta (channel 1), not phi,
        drives Rx. dyna2rad's equivalent branch writes two colliding /SKEWs; the
        joint's own frame already has the axis as its local X, so nothing extra
        is needed."""
        # O=(0,0,0), L on local x = +Y, P in the x-y plane = +X. That makes
        # local x = (0,1,0), z = x cross (P-O) = (0,0,-1), y = z cross x =
        # (1,0,0) — so CIDA's local Y is the joint axis N1->N3.
        coord_y = ("*DEFINE_COORDINATE_SYSTEM\n"
                   + _row(1, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0) + "\n"
                   + _row(1.0, 0.0, 0.0) + "\n")
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=coord_y + CURVES
                     + _stiff_gen(pida=1, pidb=2, lcid=(0, 900, 0),
                                  dlcid=(0, 901, 0), es=(0.0, 77.0, 0.0),
                                  fm=(0.0, 0.0, 0.0), nsa=(0.0, 15.0, 0.0),
                                  psa=(0.0, 30.0, 0.0)))
        res, starter = _convert(deck)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(int(c[1][20:30]), 900)     # fct_Krx <- LCIDT
        self.assertEqual(int(c[2][20:30]), 901)     # fct_Crx <- DLCIDT
        self.assertEqual(float(c[3][0:20]), 77.0)   # Kfrx    <- EST
        self.assertFalse([w for w in res.warnings if "is ambiguous" in w])

    def test_unmatched_cida_axis_warns_and_uses_channel_zero(self):
        coord_skew = ("*DEFINE_COORDINATE_SYSTEM\n"
                      + _row(1, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0) + "\n"
                      + _row(0.0, 1.0, 0.0) + "\n")
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=coord_skew + CURVES + _stiff_gen(pida=1, pidb=2))
        res, starter = _convert(deck)
        self.assertEqual(int(_cards(_blocks(starter,
                                            "/PROP/TYPE45/")[0])[1][20:30]), 900)
        self.assertTrue([w for w in res.warnings if "is ambiguous" in w])


class TestTranslationalStiffness(unittest.TestCase):
    """*CONSTRAINED_JOINT_STIFFNESS_TRANSLATIONAL fills the TRANSLATIONAL DOF
    blocks (Ktx/Ctx/Kftx/FFx and SDx+-), NOT the rotational ones.

    dyna2rad writes ESX into Kfrx and the stop displacements into SAx+- for
    Type 3/6 — rotational fields that Type 6 does not even export, so the whole
    card is silently lost (spec §7 defects 5 and 6)."""

    def test_translational_data_lands_in_the_translational_dof(self):
        deck = _deck(_joint("TRANSLATIONAL", 1, 2, 3, 4, 5, 6),
                     extra=COORD_X + CURVES
                     + _stiff_trans(lcid=(900, 0, 0), dlcid=(901, 0, 0),
                                         es=(800.0, 0, 0), ff=(12.0, 0, 0),
                                         nsd=(2.0, 0, 0), psd=(3.0, 0, 0)))
        _, starter = _convert(deck)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(int(c[0][0:10]), 6)        # Type 6, one Tx block
        self.assertEqual(len(c), 4)
        self.assertEqual(int(c[1][20:30]), 900)     # fct_Ktx <- LCIDX
        self.assertEqual(int(c[2][20:30]), 901)     # fct_Ctx <- DLCIDX
        self.assertEqual(float(c[3][0:20]), 800.0)  # Kftx    <- ESX
        self.assertEqual(float(c[3][20:40]), 12.0)  # FFx     <- FFX

    def test_stop_displacements_are_not_degree_converted(self):
        """SDx+- are lengths. Applying the deg->rad factor here (as dyna2rad's
        equivalent branch does for GENERALIZED) would shrink them 57-fold."""
        deck = _deck(_joint("TRANSLATIONAL", 1, 2, 3, 4, 5, 6),
                     extra=COORD_X + CURVES
                     + _stiff_trans(es=(800.0, 0, 0), nsd=(2.0, 0, 0),
                                         psd=(3.0, 0, 0)))
        _, starter = _convert(deck)
        a = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[1]
        self.assertEqual(float(a[30:50]), -2.0)
        self.assertEqual(float(a[50:70]), 3.0)

    def test_z_channel_is_read_from_its_own_columns(self):
        """dyna2rad reads "NSDY","PSDY" twice and never reads NSDZ/PSDZ, so the
        Z stop silently gets the Y value. On a Type-3 cylindrical joint aligned
        with global Z the Z channel is the one that matters."""
        state = _dispatch(_deck(
            _joint("CYLINDRICAL", 1, 2, 3, 4),
            extra=_stiff_trans(nsd=(1.0, 2.0, 3.0),
                                    psd=(4.0, 5.0, 6.0))))
        st = state.joint_stiffnesses[0]
        self.assertEqual(st.nstop, (1.0, 2.0, 3.0))
        self.assertEqual(st.pstop, (4.0, 5.0, 6.0))

    def test_cylindrical_gets_both_tx_and_rx_blocks(self):
        deck = _deck(_joint("CYLINDRICAL", 1, 2, 3, 4),
                     extra=COORD_X + CURVES
                     + _stiff_trans(lcid=(900, 0, 0), es=(800.0, 0, 0)))
        _, starter = _convert(deck)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(int(c[0][0:10]), 3)
        self.assertEqual(len(c), 1 + 2 * 3)         # Tx block then Rx block
        self.assertEqual(int(c[1][20:30]), 900)     # Tx carries the data
        self.assertEqual(int(c[4][20:30]), 0)       # Rx stays empty


class TestStiffnessBinding(unittest.TestCase):
    def test_jid_binds_to_the_joint_with_that_id(self):
        joints = (
            "*CONSTRAINED_JOINT_SPHERICAL_ID\n" + f"{55:>10}" + "ball\n"
            + _row(1, 2, "", "", "", "", "", "") + "\n"
            + "*CONSTRAINED_JOINT_REVOLUTE_ID\n" + f"{77:>10}" + "hinge\n"
            + _row(1, 2, 3, 4, "", "", "", "") + "\n")
        deck = _deck(joints, extra=COORD_X + CURVES + _stiff_gen(jid=77))
        _, starter = _convert(deck)
        props = [_cards(b) for b in _blocks(starter, "/PROP/TYPE45/")]
        self.assertEqual([int(p[0][0:10]) for p in props], [1, 2])
        self.assertEqual(len(props[0]), 1)          # spherical: untouched
        self.assertEqual(len(props[1]), 4)          # revolute: got the blocks

    def test_unresolvable_jid_is_warned(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES + _stiff_gen(jid=999))
        res, starter = _convert(deck)
        self.assertEqual(len(_cards(_blocks(starter, "/PROP/TYPE45/")[0])), 1)
        self.assertTrue([w for w in res.warnings
                         if "JID=999 matches no *CONSTRAINED_JOINT" in w])

    def test_blank_jid_matches_through_part_node_membership(self):
        """PIDA/PIDB carry their *CONSTRAINED_EXTRA_NODES, which is how a joint
        node usually reaches a rigid part."""
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES + _stiff_gen(pida=1, pidb=2))
        res, starter = _convert(deck)
        self.assertEqual(len(_cards(_blocks(starter, "/PROP/TYPE45/")[0])), 4)
        self.assertFalse([w for w in res.warnings if "no joint has a node" in w])

    def test_unmatched_parts_are_warned(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra=COORD_X + CURVES + _stiff_gen(pida=1, pidb=99))
        res, _ = _convert(deck)
        self.assertTrue([w for w in res.warnings
                         if "no joint has a node on both PIDA=1 and PIDB=99" in w])

    def test_unsupported_stiffness_option_is_recognized_not_emitted(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4),
                     extra="*CONSTRAINED_JOINT_STIFFNESS_FLEXION-TORSION\n"
                     + _row(1, 1, 2, 1, 1, 0) + "\n")
        res, starter = _convert(deck)
        self.assertEqual(len(_cards(_blocks(starter, "/PROP/TYPE45/")[0])), 1)
        self.assertEqual([kw for kw, _ in res.recognized_not_emitted],
                         ["CONSTRAINED_JOINT_STIFFNESS_FLEXION-TORSION"])
        self.assertEqual(res.skipped_keywords, [])


# ── Dispatch, options, ids ───────────────────────────────────────────────────

class TestDispatchAndOptions(unittest.TestCase):
    def test_id_option_sets_jid_and_title(self):
        state = _dispatch(_deck(
            "*CONSTRAINED_JOINT_REVOLUTE_ID\n" + f"{77:>10}" + "hinge title\n"
            + _row(1, 2, 3, 4, "", "", 2.5, 1.0) + "\n"))
        j = state.constrained_joints[0]
        self.assertEqual((j.jid, j.title, j.kind), (77, "hinge title", "REVOLUTE"))
        self.assertEqual((j.n1, j.n2, j.n3, j.n4), (1, 2, 3, 4))
        self.assertEqual((j.rps, j.damp), (2.5, 1.0))

    def test_title_option_sets_title_without_an_id(self):
        state = _dispatch(_deck(
            "*CONSTRAINED_JOINT_CYLINDRICAL_TITLE\n"
            "slider bearing\n" + _row(1, 2, 3, 4) + "\n"))
        j = state.constrained_joints[0]
        self.assertEqual((j.jid, j.title), (0, "slider bearing"))

    def test_title_reaches_the_part_and_property(self):
        _, starter = _convert(_deck(
            "*CONSTRAINED_JOINT_REVOLUTE_TITLE\n"
            "front hinge\n" + _row(1, 2, 3, 4) + "\n"))
        self.assertIn("front hinge (KJOINT2 Type 2)", starter)
        self.assertIn("\nfront hinge\n", starter)

    def test_blank_rps_and_damp_default_to_one(self):
        """Fixed-format cards always slice to 8 fields, so a BLANK RPS must fall
        back to the LS-DYNA default 1.0, not to 0.0."""
        state = _dispatch(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        j = state.constrained_joints[0]
        self.assertEqual((j.rps, j.damp), (1.0, 1.0))

    def test_local_option_is_parsed_and_dropped_loudly(self):
        deck = _deck("*CONSTRAINED_JOINT_REVOLUTE_LOCAL\n"
                     + _row(1, 2, 3, 4) + "\n" + _row(1, 0) + "\n")
        state = _dispatch(deck)
        self.assertTrue(state.constrained_joints[0].has_local)
        res, starter = _convert(deck)
        self.assertIn("/PROP/TYPE45/", starter)
        self.assertTrue([w for w in res.warnings if "_LOCAL option" in w])

    def test_failure_option_is_parsed_and_dropped_loudly(self):
        deck = _deck("*CONSTRAINED_JOINT_REVOLUTE_FAILURE\n"
                     + _row(1, 2, 3, 4) + "\n" + _row(0, 0.0, 0.0) + "\n"
                     + _row(1000.0, 0, 0, 0, 0, 0) + "\n")
        res, starter = _convert(deck)
        self.assertIn("/PROP/TYPE45/", starter)
        hits = [w for w in res.warnings if "NEVER FAILS" in w]
        self.assertEqual(len(hits), 1)

    def test_motor_joint_is_not_misread_as_translational(self):
        """dyna2rad classifies with keyWord.find("TRANS"), so a future profile
        registering _TRANSLATIONAL_MOTOR would silently convert it as a plain
        translational joint. Exact-match dispatch cannot."""
        res, starter = _convert(_deck(
            "*CONSTRAINED_JOINT_TRANSLATIONAL_MOTOR\n"
            + _row(1, 2, 3, 4, 5, 6) + "\n" + _row(1.0, 0, 0) + "\n"))
        self.assertNotIn("/PROP/TYPE45/", starter)
        self.assertEqual(res.skipped_keywords,
                         ["CONSTRAINED_JOINT_TRANSLATIONAL_MOTOR"])

    def test_missing_body_node_drops_the_joint_loudly(self):
        res, starter = _convert(_deck(_joint("REVOLUTE", 1, "", 3, 4)))
        self.assertNotIn("/PROP/TYPE45/", starter)
        self.assertTrue([w for w in res.warnings
                         if "left unconstrained" in w])

    def test_undefined_node_drops_the_joint_loudly(self):
        res, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 4242, 4)))
        self.assertNotIn("/PROP/TYPE45/", starter)
        self.assertTrue([w for w in res.warnings
                         if "not defined by any *NODE card" in w])


class TestMultiJointDeck(unittest.TestCase):
    """Every synthesized /PART, /PROP, /SPRING and /SKEW id must be unique —
    the starter rejects a duplicate outright (ERROR 79, no restart file)."""

    DECK = _deck(
        _joint("REVOLUTE", 1, 2, 3, 4)
        + _joint("SPHERICAL", 1, 2)
        + _joint("CYLINDRICAL", 1, 2, 3, 4)
        + _joint("UNIVERSAL", 1, 2, 3, 7)
        + _joint("LOCKING", 1, 2, 3, 4, 5, 6)
        + _joint("PLANAR", 1, 2, 3, 4)
        + _joint("TRANSLATIONAL", 1, 2, 3, 4, 5, 6))

    def test_one_property_and_part_per_joint(self):
        """dyna2rad shares ONE /PROP/TYPE45 per joint KIND across the whole
        model, which throws away the RPS of every joint after the first."""
        _, starter = _convert(self.DECK)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE45/")), 7)
        self.assertEqual(len(_blocks(starter, "/SPRING/")), 7)

    def test_all_synthesized_ids_are_unique(self):
        _, starter = _convert(self.DECK)
        # /PART and /SPRING intentionally share an id (the /SPRING block is
        # keyed on its part), so compare per prefix and across the rest.
        for prefix in ("/PROP/TYPE45/", "/PART/", "/SKEW/FIX/"):
            got = [b[0].rsplit("/", 1)[1] for b in _blocks(starter, prefix)]
            self.assertEqual(len(got), len(set(got)), prefix)
        props = {b[0].rsplit("/", 1)[1] for b in _blocks(starter, "/PROP/TYPE45/")}
        parts = {b[0].rsplit("/", 1)[1] for b in _blocks(starter, "/PART/")}
        skews = {b[0].rsplit("/", 1)[1] for b in _blocks(starter, "/SKEW/FIX/")}
        self.assertEqual(props & parts, set())
        self.assertEqual(props & skews, set())

    def test_per_joint_rps_is_preserved(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4, rps=2.0)
                     + _joint("REVOLUTE", 1, 2, 3, 4, rps=7.0))
        _, starter = _convert(deck)
        scf = [float(_cards(b)[0][30:50])
               for b in _blocks(starter, "/PROP/TYPE45/")]
        self.assertEqual(scf, [2.0, 7.0])

    def test_synthesized_part_id_avoids_a_real_part(self):
        """next_id() starts at 90001; a deck that already numbers a *PART there
        would collide."""
        bodies = BODIES.replace(_row(2, 1, 1), _row(90001, 1, 1)).replace(
            "       2       2      21", "       2   90001      21").replace(
            _row(2, 2) + "\n", _row(90001, 2) + "\n").replace(
            _row(2, 4) + "\n", _row(90001, 4) + "\n").replace(
            _row(2, 6) + "\n", _row(90001, 6) + "\n").replace(
            _row(2, 7) + "\n", _row(90001, 7) + "\n")
        _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4),
                                    bodies=bodies))
        part_ids = [int(b[0].rsplit("/", 1)[1])
                    for b in _blocks(starter, "/PART/")]
        self.assertEqual(len(part_ids), len(set(part_ids)))
        self.assertIn(90001, part_ids)              # the real one survives


class TestRigidBodyAttachment(unittest.TestCase):
    def test_joint_node_off_every_rigid_body_is_warned(self):
        """A joint acts between two RIGID bodies. On loose mesh nodes the
        /PROP/TYPE45 spring constrains bare points instead."""
        bodies = BODIES.split("*CONSTRAINED_EXTRA_NODES_NODE")[0]
        res, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4),
                                      bodies=bodies))
        self.assertIn("/PROP/TYPE45/", starter)
        hits = [w for w in res.warnings if "belong to no /RBODY" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("[1, 2, 3]", hits[0])

    def test_attached_joint_nodes_are_silent(self):
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        self.assertFalse([w for w in res.warnings if "belong to no /RBODY" in w])

    def test_implicit_guard_leaves_joint_nodes_free(self):
        """The implicit free-node guard would /BCS 111 111 a joint node attached
        to no element, welding the joint solid."""
        bodies = BODIES.split("*CONSTRAINED_EXTRA_NODES_NODE")[0].replace(
            "*MAT_RIGID\n" + _row(1, "7.85E-9", 210000.0, 0.3) + "\n",
            "*MAT_ELASTIC\n" + _row(1, "7.85E-9", 210000.0, 0.3) + "\n")
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4), bodies=bodies,
                     extra="*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.1) + "\n")
        _, starter = _convert(deck)
        self.assertIn("fix_free_reference_nodes", starter)
        grp = [b for b in _blocks(starter, "/GRNOD/NODE/")
               if b[1].strip() == "free_reference_nodes"]
        self.assertEqual(len(grp), 1)
        # /GRNOD/NODE packs up to 10 ids of 10 columns per line.
        fixed = {int(ln[i * 10:(i + 1) * 10])
                 for ln in grp[0][2:] for i in range(len(ln) // 10)}
        # Nodes 4/5/6/7 touch nothing at all and MUST be caught, proving the
        # guard really ran on this deck; 1/2/3 carry the joint spring.
        self.assertTrue({4, 5, 6, 7} <= fixed)
        self.assertEqual(fixed & {1, 2, 3}, set())


class TestJointForceOutput(unittest.TestCase):
    def test_database_jntforc_emits_a_th_spring_group(self):
        deck = _deck(_joint("REVOLUTE", 1, 2, 3, 4) + _joint("SPHERICAL", 1, 2),
                     extra="*DATABASE_JNTFORC\n" + _row(0.001) + "\n")
        _, starter = _convert(deck)
        blk = _blocks(starter, "/TH/SPRING/")
        self.assertEqual(len(blk), 1)
        elems = [int(ln) for ln in blk[0][3:] if ln.strip().isdigit()]
        self.assertEqual(len(elems), 2)
        spring_eids = [int(_blocks(starter, "/SPRING/")[i][-1][0:10])
                       for i in range(2)]
        self.assertEqual(elems, spring_eids)

    def test_no_th_spring_without_the_request(self):
        _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        self.assertNotIn("/TH/SPRING/", starter)


DEFORMABLE = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (31, 0.0, -5.0, 0.0), (32, 1.0, -5.0, 0.0),
        (33, 1.0, -4.0, 0.0), (34, 0.0, -4.0, 0.0)))
    + "*PART\nweb\n" + _row(3, 3, 3) + "\n"
    + "*SECTION_SHELL\n" + _row(3, 2) + "\n" + _row(1.0) + "\n"
    + "*MAT_ELASTIC\n" + _row(3, "7.85E-9", 210000.0, 0.3) + "\n"
    + "*ELEMENT_SHELL\n"
    + "       3       3      31      32      33      34\n"
)


def _bodies_with_secid(secid: int) -> str:
    """BODIES, but with the shared *SECTION_SHELL renumbered to *secid*.
    /PROP/SHELL is emitted under the SECID verbatim, so a SECID in the auto-id
    range is what collides with a synthesized property id."""
    return (
        "*PART\nbody A\n" + _row(1, secid, 1) + "\n"
        "*PART\nbody B\n" + _row(2, secid, 1) + "\n"
        "*SECTION_SHELL\n" + _row(secid, 2) + "\n" + _row(1.0) + "\n"
        "*MAT_RIGID\n" + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
        "*ELEMENT_SHELL\n"
        "       1       1      11      12      13      14\n"
        "       2       2      21      22      23      24\n"
        "*CONSTRAINED_EXTRA_NODES_NODE\n"
        + "".join(_row(p, n) + "\n" for p, n in
                 ((1, 1), (1, 3), (1, 5), (2, 2), (2, 4), (2, 6), (2, 7)))
    )


_PROP_RE = re.compile(r"^/PROP/[A-Z0-9_]+/(\d+)\s*$")


def _all_prop_ids(starter: str):
    return [int(m.group(1)) for m in
            (_PROP_RE.match(ln) for ln in starter.splitlines()) if m]


class TestIdAllocators(unittest.TestCase):
    """The guarded allocators, tested DIRECTLY. Exercising them only through a
    converted deck is not enough: the auto counter has usually walked past the
    seeded id by the time the /PART or /PROP is drawn, so the collision loop
    never runs and a broken guard still ships a green suite."""

    def test_next_part_id_steps_over_a_real_part(self):
        state = ConversionState()
        base = state.next_id()
        state._auto_id = base
        state.parts = {base: object(), base + 1: object()}
        self.assertEqual(state.next_part_id(), base + 2)

    def test_next_prop_id_steps_over_a_real_section(self):
        for attr in ("sec_shells", "sec_solids", "sec_beams"):
            with self.subTest(section=attr):
                state = ConversionState()
                base = state.next_id()
                state._auto_id = base
                setattr(state, attr, {base: object(), base + 1: object()})
                self.assertEqual(state.next_prop_id(), base + 2)

    def test_next_prop_id_is_a_plain_next_id_without_a_clash(self):
        state = ConversionState()
        base = state.next_id()
        state._auto_id = base
        self.assertEqual(state.next_prop_id(), base)


class TestSynthesizedPropertyIdCollision(unittest.TestCase):
    """/PROP/SHELL, /PROP/SOLID and /PROP/BEAM carry the *SECTION_* SECID
    verbatim, so a SECID at or above the auto-id base (90001) lands on the same
    id as the joint's synthesized /PROP/TYPE45."""

    def test_no_duplicate_prop_id_for_any_secid_in_the_auto_range(self):
        for secid in range(90001, 90013):
            with self.subTest(secid=secid):
                _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4),
                                            bodies=_bodies_with_secid(secid)))
                ids = _all_prop_ids(starter)
                self.assertEqual(len(ids), len(set(ids)))
                self.assertIn(secid, ids)      # the real property survives

    def test_six_joints_and_a_swept_secid_stay_unique(self):
        joints = "".join(_joint("REVOLUTE", 1, 2, 3, 4) for _ in range(6))
        for secid in range(90001, 90031):
            with self.subTest(secid=secid):
                _, starter = _convert(_deck(joints,
                                            bodies=_bodies_with_secid(secid)))
                ids = _all_prop_ids(starter)
                self.assertEqual(len(ids), len(set(ids)))


class TestStiffnessCardMerge(unittest.TestCase):
    """A cylindrical (Tx, Rx) or planar (Ty, Tz, Rx) joint is canonically
    written with a _GENERALIZED card for the rotation AND a _TRANSLATIONAL card
    for the translation. They fill disjoint DOF blocks, so both must survive."""

    DECK = _deck(
        _joint("CYLINDRICAL", 1, 2, 3, 4, jid=88, title="sleeve"),
        extra=COORD_X + CURVES
        + _stiff_gen(jid=88, lcid=(0, 0, 0), dlcid=(0, 0, 0),
                     es=(1000.0, 0, 0), fm=(50.0, 0, 0),
                     nsa=(5.0, 0, 0), psa=(30.0, 0, 0))
        + _stiff_trans(jid=88, es=(7000.0, 0, 0), ff=(250.0, 0, 0),
                       nsd=(2.0, 0, 0), psd=(3.0, 0, 0)))

    def test_both_dof_families_are_filled(self):
        res, starter = _convert(self.DECK)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(int(c[0][0:10]), 3)            # Type 3
        self.assertEqual(len(c), 1 + 2 * 3)             # Tx block then Rx block
        # Tx (from _TRANSLATIONAL): stops unconverted, Kftx/FFx present.
        self.assertEqual(float(c[1][30:50]), -2.0)      # SDx-
        self.assertEqual(float(c[1][50:70]), 3.0)       # SDx+
        self.assertEqual(float(c[3][0:20]), 7000.0)     # Kftx <- ESX
        self.assertEqual(float(c[3][20:40]), 250.0)     # FFx  <- FFX
        # Rx (from _GENERALIZED): stops in radians, Kfrx/FMx present.
        self.assertAlmostEqual(float(c[4][30:50]), -5.0 * math.pi / 180.0, places=9)
        self.assertAlmostEqual(float(c[4][50:70]), 30.0 * math.pi / 180.0, places=9)
        self.assertEqual(float(c[6][0:20]), 1000.0)     # Kfrx <- ESPH
        self.assertEqual(float(c[6][20:40]), 50.0)      # FMx  <- FMPH
        self.assertFalse([w for w in res.warnings
                          if "only the first" in w])

    def test_card_order_does_not_change_the_result(self):
        flipped = _deck(
            _joint("CYLINDRICAL", 1, 2, 3, 4, jid=88, title="sleeve"),
            extra=COORD_X + CURVES
            + _stiff_trans(jid=88, es=(7000.0, 0, 0), ff=(250.0, 0, 0),
                           nsd=(2.0, 0, 0), psd=(3.0, 0, 0))
            + _stiff_gen(jid=88, lcid=(0, 0, 0), dlcid=(0, 0, 0),
                         es=(1000.0, 0, 0), fm=(50.0, 0, 0),
                         nsa=(5.0, 0, 0), psa=(30.0, 0, 0)))
        _, a = _convert(self.DECK)
        _, b = _convert(flipped)
        self.assertEqual(_cards(_blocks(a, "/PROP/TYPE45/")[0]),
                         _cards(_blocks(b, "/PROP/TYPE45/")[0]))

    def test_two_cards_of_the_same_option_still_conflict(self):
        deck = _deck(
            _joint("CYLINDRICAL", 1, 2, 3, 4, jid=88),
            extra=COORD_X + CURVES
            + _stiff_gen(jid=88, es=(1000.0, 0, 0))
            + _stiff_gen(jid=88, es=(2000.0, 0, 0)))
        res, starter = _convert(deck)
        hits = [w for w in res.warnings if "SAME option" in w]
        self.assertEqual(len(hits), 1)
        c = _cards(_blocks(starter, "/PROP/TYPE45/")[0])
        self.assertEqual(float(c[6][0:20]), 1000.0)     # the FIRST card wins


class TestAntiParallelCida(unittest.TestCase):
    """A CIDA axis pointing OPPOSITE to the joint axis makes a positive LS-DYNA
    rotation a NEGATIVE Radioss one, so the asymmetric stop pair must be
    mirrored — otherwise the joint travels 30 deg where LS-DYNA limits it to 5."""

    COORD_NEG_X = ("*DEFINE_COORDINATE_SYSTEM\n"
                   + _row(7, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0) + "\n"
                   + _row(0.0, 1.0, 0.0) + "\n")

    def _stops(self, coord, cid, **kw):
        _, starter = _convert(_deck(
            _joint("REVOLUTE", 1, 2, 3, 4, jid=77),
            extra=coord + CURVES + _stiff_gen(jid=77, cida=cid, cidb=cid,
                                              nsa=(5.0, 0, 0),
                                              psa=(30.0, 0, 0), **kw)))
        a = _cards(_blocks(starter, "/PROP/TYPE45/")[0])[1]
        return float(a[30:50]), float(a[50:70])

    def test_parallel_cida_keeps_the_stop_pair(self):
        lo, hi = self._stops(COORD_X, 1, lcid=(0, 0, 0), dlcid=(0, 0, 0))
        self.assertAlmostEqual(lo, -5.0 * math.pi / 180.0, places=9)
        self.assertAlmostEqual(hi, 30.0 * math.pi / 180.0, places=9)

    def test_anti_parallel_cida_mirrors_the_stop_pair(self):
        lo, hi = self._stops(self.COORD_NEG_X, 7,
                             lcid=(0, 0, 0), dlcid=(0, 0, 0))
        self.assertAlmostEqual(lo, -30.0 * math.pi / 180.0, places=9)
        self.assertAlmostEqual(hi, 5.0 * math.pi / 180.0, places=9)

    def test_anti_parallel_cida_with_a_curve_warns_it_was_not_mirrored(self):
        res, _ = _convert(_deck(
            _joint("REVOLUTE", 1, 2, 3, 4, jid=77),
            extra=self.COORD_NEG_X + CURVES
            + _stiff_gen(jid=77, cida=7, cidb=7, lcid=(900, 0, 0),
                         nsa=(5.0, 0, 0), psa=(30.0, 0, 0))))
        hits = [w for w in res.warnings if "points OPPOSITE" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("curve", hits[0])

    def test_no_mirror_warning_when_no_curve_is_referenced(self):
        res, _ = _convert(_deck(
            _joint("REVOLUTE", 1, 2, 3, 4, jid=77),
            extra=self.COORD_NEG_X + CURVES
            + _stiff_gen(jid=77, cida=7, cidb=7, lcid=(0, 0, 0),
                         dlcid=(0, 0, 0), fm=(0.0, 0, 0),
                         nsa=(5.0, 0, 0), psa=(30.0, 0, 0))))
        self.assertFalse([w for w in res.warnings if "points OPPOSITE" in w])


class TestTwoNodeSpringFrame(unittest.TestCase):
    """GET_SKEW45 only READS Skew_ID1 for a 2-node spring whose nodes are
    coincident (rini45.F:643). Above that tolerance the node branches win — and
    for a Type 1 / Type 8 joint a non-zero Skew_ID1 pushes the starter OFF its
    clean global-frame branch (line 439, gated on IDSK1 == 0) and onto the
    N1->N2 mesh offset. So a 2-node frame is never derived from the nodes."""

    OFFSET_NODE = ("*NODE\n" + f"{8:>8}{0.0:>16}{0.0:>16}{0.001:>16}\n"
                   + "*CONSTRAINED_EXTRA_NODES_NODE\n" + _row(2, 8) + "\n")

    def _skew1(self, starter):
        return int(_cards(_blocks(starter, "/PROP/TYPE45/")[0])[0][80:90])

    def test_coincident_spherical_with_cida_uses_the_cida_skew(self):
        res, starter = _convert(_deck(
            _joint("SPHERICAL", 1, 2, jid=55),
            extra=COORD_X + CURVES + _stiff_gen(jid=55)))
        self.assertEqual(self._skew1(starter), 1)       # COORD_X's cid
        self.assertTrue([w for w in res.warnings
                         if "no joint frame is derivable" in w])

    def test_offset_spherical_never_gets_a_noise_skew(self):
        res, starter = _convert(_deck(
            _joint("SPHERICAL", 1, 8, jid=55),
            extra=self.OFFSET_NODE + COORD_X + CURVES + _stiff_gen(jid=55)))
        self.assertEqual(self._skew1(starter), 0)
        self.assertNotIn("SKEW_JOINT_", starter)
        hits = [w for w in res.warnings if "IGNORES Skew_ID1" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("0.001", hits[0])

    def test_offset_spherical_without_a_stiffness_card_is_silent(self):
        res, starter = _convert(_deck(_joint("SPHERICAL", 1, 8),
                                      extra=self.OFFSET_NODE))
        self.assertEqual(self._skew1(starter), 0)
        self.assertFalse([w for w in res.warnings if "Skew_ID1" in w])

    def test_three_node_joint_still_writes_its_derived_skew(self):
        _, starter = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        self.assertIn("SKEW_JOINT_", starter)
        self.assertNotEqual(self._skew1(starter), 0)


class TestStarterErrorPredicates(unittest.TestCase):
    """The ERROR 936 / degenerate-axis diagnostics must fire on exactly the
    starter's own conditions — NNOD2 (rini45.F:421-425), not the raw node
    count."""

    OFFSET_NODE = ("*NODE\n" + f"{9:>8}{0.5:>16}{0.0:>16}{0.0:>16}\n"
                   + "*CONSTRAINED_EXTRA_NODES_NODE\n" + _row(2, 9) + "\n")

    def test_coincident_two_node_revolute_predicts_error_936(self):
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2)))
        self.assertTrue([w for w in res.warnings if "ERROR 936" in w])

    def test_offset_two_node_revolute_predicts_the_noise_axis_not_936(self):
        """NNOD2 is bumped 2 -> 3 when N1 and N2 are apart, so the starter does
        NOT raise ERROR 936 — it silently uses the N1->N2 offset as the axis."""
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 9),
                                extra=self.OFFSET_NODE))
        self.assertFalse([w for w in res.warnings if "ERROR 936" in w])
        self.assertTrue([w for w in res.warnings
                         if "substitutes the N1->N2 direction" in w])

    def test_locking_with_four_colinear_nodes_is_warned(self):
        """Type 8 carries a 4-node spring (N1, N2, N3, N5). The starter's
        NNOD>=4 branch runs its own ERROR 934/1009 checks regardless of
        Skew_ID1, so suppressing the diagnostic for Type 8 hid a hard abort."""
        res, _ = _convert(_deck(_joint("LOCKING", 1, 2, 3, 4, 4, 6)))
        hits = [w for w in res.warnings if "axis is degenerate" in w]
        self.assertEqual(len(hits), 1)

    def test_universal_colinearity_uses_the_starters_own_scaled_test(self):
        """rini45.F:610 divides by (|y x z| + |y|), a SUM — so its rejection
        angle depends on how long the offsets are. The same 8 deg between the
        cross-axle directions is rejected at 10 mm and accepted at 0.1 mm; a
        plain |cos| >= 0.98 test would reject both."""
        from k2rad.writer.joints import _joint_frame
        c8, s8 = math.cos(math.radians(8.0)), math.sin(math.radians(8.0))
        for scale, expect_frame in ((10.0, False), (0.1, True)):
            with self.subTest(scale=scale):
                nodes = "*NODE\n" + "".join(
                    f"{nid:>8}{x:>16.8f}{y:>16.8f}{z:>16.8f}\n"
                    for nid, x, y, z in (
                        (1, 0.0, 0.0, 0.0), (2, 0.0, 0.0, 0.0),
                        (3, 0.0, scale, 0.0),
                        (4, 0.0, scale * c8, scale * s8)))
                state = _dispatch("*KEYWORD\n" + nodes + "*END\n")
                got = _joint_frame(state, 5, [1, 2, 3, 4])
                self.assertEqual(got is not None, expect_frame)


class TestCylindricalWithoutN3(unittest.TestCase):
    """R16 Vol I p.10-62: "For cylindrical joints, by setting node 3 to zero, it
    is possible to use a cylindrical joint to join a node that is not on a rigid
    body (node 1) to a rigid body (nodes 2 and 4)." N3 == N4 by design, so N4
    is the axis node N3 would have been."""

    def test_n4_stands_in_for_a_blank_n3(self):
        res, starter = _convert(_deck(_joint("CYLINDRICAL", 1, 2, "", 4)))
        spring = _blocks(starter, "/SPRING/")[0][-1]
        self.assertEqual([int(spring[i:i + 10]) for i in (10, 20, 30)],
                         [1, 2, 4])
        self.assertFalse([w for w in res.warnings if "ERROR 936" in w])
        self.assertTrue([w for w in res.warnings
                         if "N3 is blank, so N4=4" in w])

    def test_both_missing_still_predicts_error_936(self):
        res, _ = _convert(_deck(_joint("CYLINDRICAL", 1, 2)))
        self.assertTrue([w for w in res.warnings if "ERROR 936" in w])

    def test_a_given_n3_is_not_overridden(self):
        _, starter = _convert(_deck(_joint("CYLINDRICAL", 1, 2, 3, 4)))
        spring = _blocks(starter, "/SPRING/")[0][-1]
        self.assertEqual(int(spring[30:40]), 3)


class TestDroppedTranslationalFriction(unittest.TestCase):
    def test_fs_and_fd_are_warned_not_silently_dropped(self):
        res, _ = _convert(_deck(
            _joint("TRANSLATIONAL", 1, 2, 3, 4, jid=78),
            extra=COORD_X + CURVES
            + _stiff_trans(jid=78, es=(800.0, 0, 0), nsd=(2.0, 0, 0),
                           psd=(3.0, 0, 0), fs=0.3, fd=0.25)))
        hits = [w for w in res.warnings if "FS=0.3/FD=0.25" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("COEFFICIENTS", hits[0])

    def test_the_fields_are_parsed_off_card_2c3(self):
        state = _dispatch(_deck(
            _joint("TRANSLATIONAL", 1, 2, 3, 4),
            extra=_stiff_trans(fs=0.3, fd=0.25)))
        st = state.joint_stiffnesses[0]
        self.assertEqual((st.fs, st.fd), (0.3, 0.25))

    def test_no_warning_without_friction_coefficients(self):
        res, _ = _convert(_deck(
            _joint("TRANSLATIONAL", 1, 2, 3, 4, jid=78),
            extra=COORD_X + CURVES + _stiff_trans(jid=78, es=(800.0, 0, 0))))
        self.assertFalse([w for w in res.warnings if "FS=" in w])


class TestFreeFormatIdHeading(unittest.TestCase):
    """A comma-delimited _ID heading whose id+title fits inside the first ten
    columns has no space, so a space-only test takes the fixed branch and
    to_int("77,hinge") silently yields JID = 0."""

    def test_comma_heading_still_yields_the_jid(self):
        state = _dispatch(_deck(
            "*CONSTRAINED_JOINT_REVOLUTE_ID\n77,hinge\n"
            + _row(1, 2, 3, 4, "", "", "", "") + "\n"))
        j = state.constrained_joints[0]
        self.assertEqual((j.jid, j.title), (77, "hinge"))

    def test_the_stiffness_card_binds_through_it(self):
        res, starter = _convert(_deck(
            "*CONSTRAINED_JOINT_REVOLUTE_ID\n77,hinge\n"
            + _row(1, 2, 3, 4, "", "", "", "") + "\n",
            extra=COORD_X + CURVES + _stiff_gen(jid=77)))
        self.assertFalse([w for w in res.warnings if "matches no" in w])
        self.assertEqual(len(_cards(_blocks(starter, "/PROP/TYPE45/")[0])), 4)

    def test_the_canonical_fixed_heading_still_works(self):
        state = _dispatch(_deck(
            "*CONSTRAINED_JOINT_REVOLUTE_ID\n" + f"{77:>10}" + "hinge\n"
            + _row(1, 2, 3, 4, "", "", "", "") + "\n"))
        self.assertEqual(state.constrained_joints[0].jid, 77)


class TestDuplicateJid(unittest.TestCase):
    def test_a_jid_on_two_joints_is_warned(self):
        res, _ = _convert(_deck(
            _joint("REVOLUTE", 1, 2, 3, 4, jid=77, title="a")
            + _joint("SPHERICAL", 1, 2, jid=77, title="b"),
            extra=COORD_X + CURVES + _stiff_gen(jid=77)))
        hits = [w for w in res.warnings if "is carried by 2 joints" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("CONSTRAINED_JOINT_REVOLUTE", hits[0])
        self.assertIn("CONSTRAINED_JOINT_SPHERICAL", hits[0])

    def test_unique_jids_are_silent(self):
        res, _ = _convert(_deck(
            _joint("REVOLUTE", 1, 2, 3, 4, jid=77)
            + _joint("SPHERICAL", 1, 2, jid=78)))
        self.assertFalse([w for w in res.warnings if "carried by" in w])


class TestEngineTimeStepPacing(unittest.TestCase):
    """An all-rigid mechanism gives the ENGINE nothing to compute a time step
    from, and Kn = 0 asks it for exactly that: joint_block_stiffness.F:92-99
    aborts at cycle 0. The STARTER is clean, so only a converter warning can
    surface it before the run."""

    def test_all_rigid_joint_deck_is_warned(self):
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4)))
        hits = [w for w in res.warnings if "NO TARGET TIME STEP" in w]
        self.assertEqual(len(hits), 1)

    def test_one_deformable_part_silences_it(self):
        res, _ = _convert(_deck(_joint("REVOLUTE", 1, 2, 3, 4),
                                extra=DEFORMABLE))
        self.assertFalse([w for w in res.warnings
                          if "NO TARGET TIME STEP" in w])

    def test_a_joint_free_deck_is_never_warned(self):
        res, _ = _convert(_deck(""))
        self.assertFalse([w for w in res.warnings
                          if "NO TARGET TIME STEP" in w])


class TestJointFreeDecksAreUnchanged(unittest.TestCase):
    """A deck with no joint must be byte-identical to before this batch."""

    def test_no_joint_section_without_joints(self):
        _, starter = _convert(_deck(""))
        self.assertNotIn("#-  JOINTS", starter)
        self.assertNotIn("/PROP/TYPE45", starter)

    def test_golden_fixtures_still_match(self):
        for stem in ("shell_explicit", "solid_plastic", "rigid_contact",
                     "tied_weld", "implicit_qstat"):
            with self.subTest(fixture=stem):
                with tempfile.TemporaryDirectory() as tmp:
                    src = os.path.join(tmp, f"{stem}.k")
                    with open(FIXTURES_DIR / f"{stem}.k", "rb") as fh:
                        data = fh.read()
                    with open(src, "wb") as fh:
                        fh.write(data)
                    result = convert(src, write_log=False)
                    with open(result.starter_path) as fh:
                        produced = fh.read().replace("\r\n", "\n")
                with open(EXPECTED_DIR / f"{stem}_0000.rad") as fh:
                    golden = fh.read().replace("\r\n", "\n")
                self.assertEqual(produced.replace(tmp, "<TMPDIR>"), golden)


if __name__ == "__main__":
    unittest.main()
