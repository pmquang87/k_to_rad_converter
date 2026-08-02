"""Tests for *INTEGRATION_SHELL user through-thickness integration rules:

  *SECTION_SHELL card-1 field 6 (QR/IRID) < 0  -> the rule reference
  *INTEGRATION_SHELL S/WF/PID                  -> /PROP/TYPE11 layer cards, or
                                                  /PROP/TYPE51 + /PROP/TYPE19
  *MAT_LAMINATED_GLASS (032) + a rule          -> the REAL glass/PVB stack
  *SECTION_SHELL multi card set                -> every section, not just #1

Kept in a separate module from tests/test_composites.py so it does not collide
with other in-flight work on that file (same policy as tests/test_joints.py and
tests/test_roadmap_keywords.py).

Assertions are COLUMN-EXACT against the emitted cards, and every layer
thickness is recomputed by hand from the deck's WF values in the test rather
than copied from the implementation. Where the conversion turns on what an
LS-DYNA field MEANS rather than on arithmetic - S is a quadrature SAMPLING
coordinate and not a slab centre, WF is a thickness FRACTION, PID_i supplies a
MATERIAL and not a section - the assertion pins the value the manual's
definition implies, with the citation in the test docstring.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402


# ── Harness (same shape as tests/test_composites.py) ─────────────────────────

def _convert(deck: str):
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
    return "".join(f"{v:>10}" for v in vals)


def _blocks(starter: str, header: str):
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


def _block(starter: str, header: str):
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _cards(block):
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _i10(line: str, i: int) -> int:
    return int(line[i * 10:(i + 1) * 10] or 0)


def _warned(result, *needles):
    return any(all(n in w for n in needles) for w in result.warnings)


def _type11_layup(starter):
    """(phi, thickness, mat_ID) per layer of the single /PROP/TYPE11.

    Layer line = Phi(1-20) Thick(21-40) Z(41-60) mat_ID(61-70) F_weight(81-100).
    """
    return [(_col_f(ln, 1, 20), _col_f(ln, 21, 40), _col_i(ln, 61, 70))
            for ln in _cards(_block(starter, "/PROP/TYPE11/"))[4:]]


def _type51_layup(starter):
    """(delta_phi, t, mat_ID) per ply of the single /PROP/TYPE51, in the stack's
    OWN ply order (read off its Ply_id column, not document order).

    /PROP/TYPE19 line = mat_ID(1-10) t(11-30) delta_phi(31-50).
    """
    stack = _cards(_block(starter, "/PROP/TYPE51/"))[4:]
    ply_ids = [_col_i(ln, 1, 10) for ln in stack if ln.strip()]
    by_id = {int(b[0].rsplit("/", 1)[1]): _cards(b)[0]
             for b in _blocks(starter, "/PROP/TYPE19/")}
    return [(_col_f(by_id[p], 31, 50), _col_f(by_id[p], 11, 30),
             _col_i(by_id[p], 1, 10)) for p in ply_ids]


def _layup(starter):
    """The emitted layup, whichever layered property carries it."""
    if "/PROP/TYPE51/" in starter:
        return _type51_layup(starter)
    return _type11_layup(starter)


# ── Decks ────────────────────────────────────────────────────────────────────

NODES = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0)))
)
SHELL = "*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
SOLID_NODES = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 1.0, 0.0, 0.0), (3, 1.0, 1.0, 0.0),
        (4, 0.0, 1.0, 0.0), (5, 0.0, 0.0, 1.0), (6, 1.0, 0.0, 1.0),
        (7, 1.0, 1.0, 1.0), (8, 0.0, 1.0, 1.0)))
)
BRICK = "*ELEMENT_SOLID\n" + _row(1, 7) + "\n" + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
SECTION_SOLID = "*SECTION_SOLID\n" + _row(7, 1) + "\n"
END = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n"

# The ordinary shell material of these decks is *MAT_024 -> /MAT/LAW36, NOT
# *MAT_ELASTIC: LAW1 is banned from every layered shell property by Radioss
# itself (hm_read_part.F:289, ERROR 658), so an elastic part can never carry a
# rule - see test_law1_part_cannot_carry_a_layup.
STEEL = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
         + _row(3, 7.85e-9, 210000.0, 0.3, 300.0) + "\n")
FOAM = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
        + _row(4, 1.0e-10, 3.0, 0.45, 0.5) + "\n")
ELASTIC = "*MAT_ELASTIC\n" + _row(5, 7.85e-9, 210000.0, 0.3) + "\n"
# A part used purely as an *INTEGRATION_SHELL PID_i handle: "PID: Optional part
# ID ... The material and density are taken from this part" (Vol I R17 p.29-17).
# It holds no elements. The *SECTION_SHELL is not required - the element-free
# *PART placeholder resolves a sectionless one too (see
# test_elementless_carrier_part_still_resolves_a_property) - it is kept so these
# decks exercise the ordinary, fully-specified carrier.
CORE_PART = ("*PART\ncore\n" + _row(88, 88, 4) + "\n"
             + "*SECTION_SHELL\n" + _row(88, 2, 1.0, 3) + "\n"
             + _row(1.0, 1.0, 1.0, 1.0) + "\n")


def _mat002(mid=2, beta=0.0):
    return ("*MAT_ORTHOTROPIC_ELASTIC\n"
            + _row(mid, 1.55e-9, 150000.0, 10000.0, 10000.0, 0.02, 0.02, 0.4)
            + "\n" + _row(5000.0, 3000.0, 4000.0, 0.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, beta) + "\n")


def _mat002_aopt2(mid=2):
    """*MAT_ORTHOTROPIC_ELASTIC with AOPT = 2 (a and d vectors), which is the
    only AOPT that makes k2rad synthesize a /SKEW/FIX for the property."""
    return ("*MAT_ORTHOTROPIC_ELASTIC\n"
            + _row(mid, 1.55e-9, 150000.0, 10000.0, 10000.0, 0.02, 0.02, 0.4)
            + "\n" + _row(5000.0, 3000.0, 4000.0, 2.0) + "\n"
            + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"            # a = global X
            + _row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n")      # d = global Y


def _mat032(mid=32, f=(0.0, 1.0, 1.0, 0.0), efg=0.01):
    return ("*MAT_LAMINATED_GLASS_TITLE\nwindshield\n"
            + _row(mid, 2.5e-9, 70000.0, 0.23, 100.0, 0.0, efg, 3000.0) + "\n"
            + _row(0.40, 20.0, 10.0) + "\n" + _row(*f) + "\n")


def _mat037(mid=37):
    return ("*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC\n"
            + _row(mid, 7.85e-9, 210000.0, 0.3, 300.0, 1000.0, 1.8, 0) + "\n"
            + _row(0, 0.0, 0.0, 0, "", 0.0) + "\n")


def _rule(irid=3, nip=3, esop=0, failopt=0,
          points=((-1.0, 0.25, 0), (0.0, 0.5, 0), (1.0, 0.25, 0)),
          kw="*INTEGRATION_SHELL"):
    """*INTEGRATION_SHELL: card 1 IRID NIP ESOP FAILOPT, then ONE S/WF/PID card
    per integration point (CARD_LIST(NIP), not 8-per-card)."""
    out = kw + "\n" + _row(irid, nip, esop, failopt) + "\n"
    if esop == 0:
        for (s, wf, pid) in points:
            out += _row(s, wf, pid) + "\n"
    return out


def _section(secid=7, elform=2, nip=5, t1=2.0, qr_irid=-3.0, icomp=0,
             betas=(), title=False):
    """*SECTION_SHELL. The rule reference is card-1 field 6 (QR/IRID, cols
    51-60) NEGATED, NOT the NIP field."""
    kw = (f"*SECTION_SHELL_TITLE\nsec {secid}\n" if title
          else "*SECTION_SHELL\n")
    out = (kw + _row(secid, elform, 1.0, nip, 0.0, qr_irid, icomp) + "\n"
           + _row(t1, t1, t1, t1) + "\n")
    if icomp == 1:
        vals = list(betas)
        for k in range(((nip if nip > 0 else 2) + 7) // 8):
            out += _row(*vals[k * 8:(k + 1) * 8]) + "\n"
    return out


def _deck(mat=STEEL, mid=3, rule=None, section=None, extra="", pid=7, secid=7):
    return ("*KEYWORD\n" + NODES + SHELL
            + "*PART\np\n" + _row(pid, secid, mid) + "\n"
            + (section if section is not None else _section())
            + (rule if rule is not None else _rule())
            + mat + extra + END)


def _layered(starter) -> bool:
    return "/PROP/TYPE11/" in starter or "/PROP/TYPE51/" in starter


# ═════════════════════════════════════════════════════════════════════════════
# Parsing: the rule card and the *SECTION_SHELL QR/IRID link
# ═════════════════════════════════════════════════════════════════════════════

class IntegrationShellParseTests(unittest.TestCase):
    """Card 1 IRID NIP ESOP FAILOPT, then NIP x (S WF PID) when ESOP = 0
    (Manual Vol I R17 p.29-16)."""

    def test_card1_and_point_cards_are_parsed(self):
        state = _dispatch("*KEYWORD\n" + _rule(
            irid=3, nip=3, failopt=1,
            points=((-1.0, 0.25, 0), (0.0, 0.5, 88), (1.0, 0.25, 0)))
            + "*END\n")
        rule = state.integration_shells[3]
        self.assertEqual((rule.nip, rule.esop, rule.failopt), (3, 0, 1))
        self.assertEqual([(p.s, p.wf, p.pid) for p in rule.points],
                         [(-1.0, 0.25, 0), (0.0, 0.5, 88), (1.0, 0.25, 0)])

    def test_esop_one_reads_no_point_cards(self):
        """"Define NIP cards below if ESOP = 0" - ESOP=1 subdivides the shell
        into NIP equal layers and carries no per-point card at all."""
        state = _dispatch("*KEYWORD\n" + _rule(irid=5, nip=6, esop=1) + "*END\n")
        rule = state.integration_shells[5]
        self.assertEqual((rule.nip, rule.esop), (6, 1))
        self.assertEqual(rule.points, [])

    def test_several_rules_under_one_header(self):
        """A block ends at the next '*', so a deck may stack rules under one
        header; the reader loops card 1 -> its point cards."""
        deck = ("*KEYWORD\n" + _rule(irid=3, nip=2, esop=1)
                + _row(7, 2, 0, 0) + "\n" + _row(-1.0, 0.5, 0) + "\n"
                + _row(1.0, 0.5, 0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(sorted(state.integration_shells), [3, 7])
        self.assertEqual(state.integration_shells[7].nip, 2)
        self.assertEqual(len(state.integration_shells[7].points), 2)

    def test_blank_nip_is_zero_not_the_section_default(self):
        """*INTEGRATION_SHELL's CFG default is NIP = 0 and the manual prints no
        Default row - *SECTION_SHELL's own 2.0 must NOT be borrowed."""
        state = _dispatch("*KEYWORD\n*INTEGRATION_SHELL\n" + _row(3) + "\n"
                          + "*END\n")
        self.assertEqual(state.integration_shells[3].nip, 0)

    def test_short_point_block_is_warned(self):
        state = _dispatch("*KEYWORD\n*INTEGRATION_SHELL\n" + _row(3, 4, 0, 0)
                          + "\n" + _row(-1.0, 0.5, 0) + "\n*END\n")
        self.assertEqual(len(state.integration_shells[3].points), 1)
        self.assertTrue(any("needs 4 S/WF/PID card(s)" in w and "only 1" in w
                            for w in state.warnings), state.warnings)

    def test_negative_qr_irid_binds_the_rule(self):
        """"Quadrature rules in the *SECTION_SHELL and *SECTION_BEAM cards need
        to be specified as a negative number.  The absolute value of the
        negative number refers to user defined integration rule number"
        (Vol I R17 p.29-1). The cell is field 6 (cols 51-60)."""
        state = _dispatch("*KEYWORD\n" + _section(qr_irid=-3.0) + "*END\n")
        self.assertEqual(state.sec_shells[7].irid, 3)

    def test_positive_qr_is_a_builtin_rule_not_a_reference(self):
        """QR >= 0 selects a BUILT-IN quadrature rule (0 Gauss/Lobatto, 1
        trapezoidal) and references nothing."""
        for qr in (0.0, 1.0, 3.0):
            state = _dispatch("*KEYWORD\n" + _section(qr_irid=qr) + "*END\n")
            self.assertEqual(state.sec_shells[7].irid, 0, qr)

    def test_the_link_is_field_six_and_not_the_nip_field(self):
        """A negative NIP is NOT a rule reference - it is a mis-keyed count.
        Pinning this because the field is easy to confuse: NIP sits in cols
        31-40, QR/IRID in cols 51-60, and BOTH are typed F."""
        state = _dispatch("*KEYWORD\n*SECTION_SHELL\n"
                          + _row(7, 2, 1.0, -3.0, 0.0, 0.0) + "\n"
                          + _row(2.0) + "\n*END\n")
        self.assertEqual(state.sec_shells[7].irid, 0)
        self.assertEqual(state.sec_shells[7].nip, 3)      # |NIP|, warned
        self.assertTrue(any("NIP=-3 is negative" in w and "QR/IRID" in w
                            for w in state.warnings), state.warnings)

    def test_a_rule_id_of_zero_is_skipped_with_a_warning(self):
        state = _dispatch("*KEYWORD\n*INTEGRATION_SHELL\n" + _row(0, 2, 1)
                          + "\n*END\n")
        self.assertEqual(state.integration_shells, {})
        self.assertTrue(any("no positive IRID" in w for w in state.warnings))

    def test_a_duplicate_rule_id_keeps_the_last_definition(self):
        deck = ("*KEYWORD\n" + _rule(irid=3, nip=2, esop=1)
                + _rule(irid=3, nip=5, esop=1) + "*END\n")
        state = _dispatch(deck)
        self.assertEqual(state.integration_shells[3].nip, 5)
        self.assertTrue(any("defined more than once" in w
                            for w in state.warnings), state.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# The emitted layer cards
# ═════════════════════════════════════════════════════════════════════════════

class RuleDrivenLayupTests(unittest.TestCase):
    """t_i = WF_i / sum(WF) * T1, material from PID_i -> *PART -> MID, layers
    stacked bottom-up (Radioss Ipos = 0)."""

    def test_unequal_weights_become_real_layer_thicknesses(self):
        """T1 = 2.0 with WF = 0.25/0.5/0.25 (sum 1.0) gives 0.5 / 1.0 / 0.5 by
        hand - NOT the 3 x 0.667 even split."""
        _, starter = _convert(_deck())
        layup = _layup(starter)
        self.assertEqual(len(layup), 3)
        self.assertEqual([t for _, t, _ in layup], [0.5, 1.0, 0.5])
        self.assertNotEqual(layup[0][1], 2.0 / 3.0)

    def test_layer_thicknesses_sum_to_the_section_thickness(self):
        """The cumulative-WF stack reproduces T1 exactly, which is the whole
        reason Zi is left at 0 with Ipos = 0. Verified against the starter's own
        echo: SHELL THICKNESS = 2.000000000000."""
        _, starter = _convert(_deck())
        self.assertAlmostEqual(sum(t for _, t, _ in _layup(starter)), 2.0)

    def test_weights_are_normalized_by_their_sum(self):
        """LS-DYNA's convention is that the WF sum to 1, but nothing enforces
        it: WF = 1, 3 on T1 = 2.0 must give 0.5 and 1.5, not 2.0 and 6.0."""
        rule = _rule(nip=2, points=((-1.0, 1.0, 0), (1.0, 3.0, 0)))
        result, starter = _convert(_deck(rule=rule))
        self.assertEqual([t for _, t, _ in _layup(starter)], [0.5, 1.5])
        self.assertTrue(_warned(result, "sum(WF) = 4 != 1", "NORMALIZED"))

    def test_layers_auto_stack_instead_of_copying_the_dyna2rad_zi(self):
        """DELIBERATE divergence from dyna2rad. S is a quadrature SAMPLING
        coordinate in [-1, 1]; a Radioss layer Zi is the physical MIDDLE of a
        slab. dyna2rad writes Zi = S_i*T1/2 with Ipos = 1, and the starter then
        derives the shell thickness from the layer ENVELOPE (stackgroup.F
        THICKT = max(Zi+t/2) - min(Zi-t/2)) - which for this deck is
        (1.0+0.25) - (-1.0-0.25) = 2.5, a 25% thicker shell with gaps between
        the layers. Auto-stacking (Ipos = 0) keeps the shell at 2.0; the
        starter echoes the layer positions -0.75 / 0.0 / +0.75 itself."""
        result, starter = _convert(_deck(mat=_mat002(), mid=2))
        cards = _cards(_block(starter, "/PROP/TYPE11/"))
        self.assertEqual(_col_i(cards[3], 81, 90), 0)          # Ipos
        for ln in cards[4:]:
            self.assertEqual(_col_f(ln, 41, 60), 0.0)          # Z
        self.assertTrue(_warned(result, "Ipos=0", "2.5 thick shell"))

    def test_pid_override_takes_that_parts_material(self):
        """"PID: Optional part ID ... the material and density are taken from
        this part" - the resolution is PID_i -> *PART -> MID, and the
        referenced part's own section is never consulted."""
        rule = _rule(points=((-1.0, 0.25, 0), (0.0, 0.5, 88), (1.0, 0.25, 0)))
        _, starter = _convert(_deck(rule=rule, extra=CORE_PART + FOAM))
        self.assertEqual([m for _, _, m in _layup(starter)], [3, 4, 3])

    def test_blank_pid_inherits_the_element_part_material(self):
        _, starter = _convert(_deck())
        self.assertEqual([m for _, _, m in _layup(starter)], [3, 3, 3])

    def test_missing_pid_part_is_warned_and_inherits(self):
        """dyna2rad resolves the same dangling handle in silence."""
        rule = _rule(points=((-1.0, 0.25, 777), (0.0, 0.5, 0), (1.0, 0.25, 0)))
        result, starter = _convert(_deck(rule=rule))
        self.assertEqual([m for _, _, m in _layup(starter)], [3, 3, 3])
        self.assertTrue(_warned(result, "PID(s) 777", "reference no *PART"))

    def test_dangling_layer_material_is_warned_once(self):
        """A PID_i whose *PART points at a MID with no converted /MAT leaves a
        dangling mat_ID the starter rejects."""
        ghost = ("*PART\nghost\n" + _row(88, 88, 4242) + "\n"
                 + "*SECTION_SHELL\n" + _row(88, 2, 1.0, 3) + "\n"
                 + _row(1.0) + "\n")
        rule = _rule(points=((-1.0, 0.5, 88), (1.0, 0.5, 88)), nip=2)
        result, _ = _convert(_deck(rule=rule, extra=ghost))
        hits = [w for w in result.warnings
                if "layer material 4242" in w and "NOT emitted" in w]
        self.assertEqual(len(hits), 1, result.warnings)

    def test_top_down_rule_is_reordered_bottom_up(self):
        """"the ordering of the integration points is arbitrary" (Vol I R17
        Figure 29-25), but a Radioss Ipos = 0 stack is built in LIST order from
        the bottom face, so the card order cannot be copied verbatim."""
        rule = _rule(points=((1.0, 0.5, 0), (0.0, 0.3, 0), (-1.0, 0.2, 0)))
        result, starter = _convert(_deck(rule=rule))
        self.assertEqual([t for _, t, _ in _layup(starter)],
                         [0.4, 0.6, 1.0])      # 0.2, 0.3, 0.5 of T1 = 2.0
        self.assertTrue(_warned(result, "TOP-DOWN", "RE-ORDERED bottom-up"))

    def test_constant_s_keeps_the_card_order(self):
        """A blank/constant S column carries no ordering information; the stable
        sort must leave the deck's own order alone (and not shuffle it)."""
        rule = _rule(points=((0.0, 0.2, 0), (0.0, 0.3, 0), (0.0, 0.5, 0)))
        result, starter = _convert(_deck(rule=rule))
        self.assertEqual([t for _, t, _ in _layup(starter)], [0.4, 0.6, 1.0])
        self.assertFalse(_warned(result, "RE-ORDERED"))

    def test_s_outside_the_legal_range_is_warned(self):
        rule = _rule(points=((-1.4, 0.5, 0), (1.0, 0.5, 0)), nip=2)
        result, _ = _convert(_deck(rule=rule))
        self.assertTrue(_warned(result, "outside the legal S range"))

    def test_rule_nip_overrides_the_section_nip(self):
        """dyna2rad reads NIP off the RULE and never off the section
        (convertprops.cxx:1890-1892): a 3-point rule on a NIP=5 section is a
        3-layer laminate."""
        result, starter = _convert(_deck())
        self.assertEqual(len(_layup(starter)), 3)
        self.assertTrue(_warned(result, "NIP=5 is OVERRIDDEN",
                                "3 integration point(s)"))

    def test_ordinary_material_layup_goes_to_type51_not_type11(self):
        """/PROP/TYPE11 is a SINGLE-LAW property: hm_read_prop11.F accepts only
        Radioss laws 15, 25, 27 and >= 29 on layer 1 (ERROR 30) and demands
        every other layer repeat it (ERROR 334). /MAT/LAW36 is not in that set,
        so the layup goes on TYPE51 + TYPE19, which carries its materials on
        per-ply objects and has no whitelist - dyna2rad's own target."""
        result, starter = _convert(_deck())
        self.assertEqual(_blocks(starter, "/PROP/TYPE11"), [])
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE51/")), 1)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE19/")), 3)
        self.assertTrue(_warned(result, "SINGLE-LAW property", "ERROR 334"))

    def test_a_foreign_pid_material_pushes_a_composite_part_to_type51(self):
        """*MAT_002 alone stays on TYPE11 (LAW93 >= 29, one law), but a PID_i
        layer of a DIFFERENT law would trip ERROR 334 there."""
        _, plain = _convert(_deck(mat=_mat002(), mid=2))
        self.assertEqual(len(_blocks(plain, "/PROP/TYPE11/")), 1)
        rule = _rule(points=((-1.0, 0.25, 0), (0.0, 0.5, 88), (1.0, 0.25, 0)))
        _, mixed = _convert(_deck(mat=_mat002(), mid=2, rule=rule,
                                  extra=CORE_PART + FOAM))
        self.assertEqual(_blocks(mixed, "/PROP/TYPE11"), [])
        self.assertEqual([m for _, _, m in _layup(mixed)], [2, 4, 2])

    def test_law1_part_cannot_carry_a_layup(self):
        """Radioss bans LAW1 from IGTYP 9/10/11/16/17/51/52 outright
        (hm_read_part.F:289, ERROR 658) - it is integrated globally and has no
        through-thickness state - so an *MAT_ELASTIC part has NO layered
        property available and the rule must be warn-dropped, not emitted onto
        a deck the starter will reject."""
        result, starter = _convert(_deck(mat=ELASTIC, mid=5))
        self.assertFalse(_layered(starter))
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/7")), 1)
        self.assertTrue(_warned(result, "/MAT/ELAST (LAW1)", "ERROR 658"))

    def test_every_part_on_a_ruled_section_gets_its_own_laminate(self):
        """The rule hangs off the SECTION, so every part using that section is
        laminated - each with its own /PROP, because the blank-PID layers
        inherit that part's OWN material. The now-unused shared /PROP/SHELL is
        suppressed; a part on a different, unruled section keeps its own."""
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*ELEMENT_SHELL\n" + _row(2, 9, 1, 2, 3, 4) + "\n"
                + "*ELEMENT_SHELL\n" + _row(3, 11, 1, 2, 3, 4) + "\n"
                + "*PART\np\n" + _row(7, 7, 3) + "\n"
                + "*PART\nq\n" + _row(9, 7, 4) + "\n"
                + "*PART\nplain\n" + _row(11, 12, 3) + "\n"
                + _section() + _section(secid=12, qr_irid=0.0, nip=3)
                + _rule() + STEEL + FOAM + END)
        _, starter = _convert(deck)
        self.assertEqual(_blocks(starter, "/PROP/SHELL/7"), [])
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/12")), 1)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE51/")), 2)
        self.assertEqual(
            sorted({_col_i(_cards(b)[0], 1, 10)
                    for b in _blocks(starter, "/PROP/TYPE19/")}), [3, 4])

    def test_esop_one_keeps_the_shared_property_with_the_rules_nip(self):
        """ESOP=1 is NIP layers of EQUAL thickness on one material, which is
        exactly a plain /PROP/SHELL with N integration points - so no property
        is split, only the point count is corrected."""
        result, starter = _convert(_deck(rule=_rule(irid=3, nip=6, esop=1)))
        self.assertFalse(_layered(starter))
        prop = _cards(_block(starter, "/PROP/SHELL/7"))
        self.assertEqual(_i10(prop[2], 0), 6)                  # N
        self.assertTrue(_warned(result, "NIP=5 is OVERRIDDEN",
                                "6 integration point(s)"))

    def test_over_a_hundred_points_is_clamped_and_warned(self):
        """The layered-property card limit is 'NIP <= 100'. This is NOT the
        10-layer clamp the plain-section path uses: those are quadrature points
        through ONE material, these are real layers carrying material."""
        pts = tuple((-1.0 + 2.0 * k / 104, 1.0, 0) for k in range(105))
        rule = _rule(nip=105, points=pts)
        result, starter = _convert(_deck(rule=rule))
        self.assertEqual(len(_layup(starter)), 100)
        self.assertTrue(_warned(result, "CLAMPED to 100"))

    def test_more_than_ten_points_does_not_poison_the_shared_prop(self):
        """sec.nip is written as N on the SHARED /PROP/SHELL, and BOTH shell
        readers cap N at 10 (hm_read_prop01.F:260 ERROR 788,
        hm_read_prop09.F:368 ERROR 33). Pushing the raw rule count through made
        any rule with more than 10 points ERROR-terminate the starter, on a deck
        that converted cleanly before the feature existed. The LAYERED property
        keeps every layer — only the shared one is clamped."""
        n = 12
        pts = tuple((-1.0 + 2.0 * k / (n - 1), 1.0 / n, 0) for k in range(n))
        # a second, ELASTIC part on the same section stays on the shared prop
        second = ("*PART\nq\n" + _row(9, 7, 5) + "\n" + ELASTIC
                  + "*ELEMENT_SHELL\n" + _row(2, 9, 1, 2, 3, 4) + "\n")
        result, starter = _convert(_deck(rule=_rule(nip=n, points=pts),
                                         extra=second))
        shared = _cards(_block(starter, "/PROP/SHELL/7"))
        self.assertEqual(_i10(shared[2], 0), 10)               # N, not 12
        self.assertEqual(len(_layup(starter)), n)              # laminate intact
        self.assertTrue(_warned(result, "carries at most 10",
                                "ERROR 788"))
        self.assertTrue(_warned(result, "clamped to 10 on the shared "
                                        "/PROP/SHELL"))

    def test_esop_one_over_ten_layers_is_clamped_on_the_shared_prop(self):
        """Same ceiling, reached without any point card at all: an ESOP=1 rule
        never claims a layered property, so its NIP lands DIRECTLY on the shared
        /PROP/SHELL."""
        result, starter = _convert(_deck(rule=_rule(irid=3, nip=14, esop=1)))
        self.assertFalse(_layered(starter))
        self.assertEqual(_i10(_cards(_block(starter, "/PROP/SHELL/7"))[2], 0),
                         10)
        self.assertTrue(_warned(result, "ERROR 788"))

    def test_orthotropic_material_carries_the_rule_on_type11(self):
        """The rule composes with the *MAT_002 -> /MAT/LAW93 route, which
        already had a layered /PROP/TYPE11 with an even split. LAW93 >= 29 and
        every layer shares it, so TYPE11 still carries it."""
        _, starter = _convert(_deck(mat=_mat002(), mid=2))
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE11/")), 1)
        self.assertEqual([t for _, t, _ in _layup(starter)], [0.5, 1.0, 0.5])
        self.assertEqual([m for _, _, m in _layup(starter)], [2, 2, 2])

    def test_aopt2_plus_a_foreign_pid_emits_exactly_one_skew(self):
        """_emit_composite_props owns the synthesized /SKEW/FIX; re-emitting it
        inside the TYPE51 branch wrote the same skew id twice, and the starter
        ERROR-terminates on it (UDOUBLE -> ERROR 79 DUPLICATE ID). Only this
        combination reaches it: AOPT=2 builds a skew, and a foreign PID_i
        material is what pushes an orthotropic part off TYPE11 onto TYPE51."""
        rule = _rule(points=((-1.0, 0.25, 0), (0.0, 0.5, 88), (1.0, 0.25, 0)))
        _, starter = _convert(_deck(mat=_mat002_aopt2(), mid=2, rule=rule,
                                    extra=CORE_PART + FOAM))
        skews = [ln for ln in starter.splitlines()
                 if ln.startswith("/SKEW/FIX/")]
        self.assertEqual(len(skews), 1, skews)
        self.assertEqual(len(skews), len(set(skews)))
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE51/")), 1)

    def test_a_negative_weight_is_warned_by_name(self):
        """Only the SUM of WF is guarded upstream, so a negative weight whose
        sum is still positive turns into a negative ply thickness. WF is a
        thickness FRACTION (Vol I R17 p.29-17), so that is unphysical."""
        rule = _rule(points=((-1.0, 0.6, 0), (0.0, -0.1, 0), (1.0, 0.5, 0)))
        result, starter = _convert(_deck(rule=rule))
        self.assertEqual([t for _, t, _ in _layup(starter)],
                         [1.2, -0.2, 1.0])                    # T1 = 2.0
        self.assertTrue(_warned(result, "NEGATIVE weighting factor",
                                "2 (WF=-0.1)"))

    def test_messages_name_the_property_actually_emitted(self):
        """An ordinary isotropic part is the DEFAULT rule route and it lands on
        TYPE51 + TYPE19, so naming /PROP/TYPE11 in the conversion warning sent
        users grepping the deck for a property that was never written."""
        result, starter = _convert(_deck())
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE51/")), 1)
        self.assertEqual(_blocks(starter, "/PROP/TYPE11/"), [])
        self.assertTrue(_warned(result, "/PROP/TYPE51/90002 carries the rule's "
                                        "OWN 3 layer thickness(es)"))
        self.assertFalse(_warned(result, "/PROP/TYPE11/90002 carries"))

    def test_the_type11_route_still_names_type11(self):
        result, starter = _convert(_deck(mat=_mat002(), mid=2))
        prop = _block(starter, "/PROP/TYPE11/")[0].rsplit("/", 1)[1]
        self.assertTrue(_warned(result, f"/PROP/TYPE11/{prop} carries the "
                                        "rule's OWN 3 layer thickness(es)"))

    def test_the_sampling_tradeoff_is_stated_not_just_the_thickness_one(self):
        """The Ipos=0 stack reproduces T1 exactly (dyna2rad's Zi = S_i*T1/2 does
        not), but it integrates at the layer CENTRES, not at the rule's own
        sampling stations — so the through-thickness quadrature is not the
        deck's. Both halves of that trade have to be in the message."""
        result, _ = _convert(_deck())
        self.assertTrue(_warned(result, "BOTH HALVES OF THAT TRADE",
                                "cumulative-WF layer CENTRES",
                                "not the deck's quadrature rule"))
        # S = -1 / 0 / +1 on T1 = 2 -> centres -0.75 / 0 / +0.75, stations -1/0/+1
        self.assertTrue(_warned(result, "[-0.75, 0, 0.75]", "[-1, 0, 1]"))

    def test_a_rigid_part_is_not_told_to_pick_a_plastic_law(self):
        """*MAT_RIGID does convert to /MAT/ELAST for the /RBODY's inertia, so it
        hits the same LAW1 gate — but a rigid body has no through-thickness
        state at all, and telling the user to give it *MAT_PLASTIC_KINEMATIC is
        nonsense."""
        rigid = ("*MAT_RIGID\n" + _row(6, 7.85e-9, 210000.0, 0.3) + "\n"
                 + _row(0, 7, 7) + "\n" + _row(0.0, 0.0, 0.0) + "\n")
        result, starter = _convert(_deck(mat=rigid, mid=6))
        self.assertFalse(_layered(starter))
        self.assertTrue(_warned(result, "is *MAT_RIGID", "no through-thickness "
                                        "state"))
        self.assertFalse(_warned(result, "*MAT_PLASTIC_KINEMATIC"))

    def test_elementless_carrier_part_still_resolves_a_property(self):
        """"It may reference a part with no elements" (Vol I R17 p.29-17) is the
        idiomatic way to declare a layer material. k2rad emits a /PART for every
        *PART record, and a /PART whose property does not exist is starter
        ERROR 178 — the element-free-*PART placeholder covers exactly that, and
        this keyword is what makes the idiom common, so pin it here too.

        NO hand-added *SECTION_SHELL on the carrier: the placeholder is the only
        thing that can give /PART/88 a property. Starter-verified — this deck
        converts and runs `0 ERROR(S) 0 WARNING(S)` on starter_win64, identical
        to the control deck where the carrier IS given a *SECTION_SHELL by
        hand, which is why the pass no longer tells the user to add one."""
        carrier = "*PART\ncore\n" + _row(88, 0, 4) + "\n"
        rule = _rule(points=((-1.0, 0.25, 0), (0.0, 0.5, 88), (1.0, 0.25, 0)))
        result, starter = _convert(_deck(rule=rule, extra=carrier + FOAM))
        emitted = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                   if ln.startswith("/PROP/")}
        parts = starter.splitlines()
        for i, ln in enumerate(parts):
            if ln.startswith("/PART/"):
                self.assertIn(_i10(parts[i + 2], 0), emitted, ln)
        # the carrier's own property is the placeholder /PROP/SHELL, on its
        # DEFAULTED secid (LS-DYNA lets SECID default to the PID)
        self.assertIn(88, emitted)
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/88")), 1)
        self.assertEqual(_i10(parts[parts.index("/PART/88") + 2], 0), 88)
        # the layer still takes the carrier's material
        self.assertEqual([m for _, _, m in _layup(starter)], [3, 4, 3])
        # ...and the ERROR-178 claim is NOT repeated by this keyword's own pass
        self.assertFalse(_warned(result, "material carrier part(s) 88"))
        self.assertFalse(_warned(result, "Give the carrier part a "
                                         "*SECTION_SHELL"))
        # the synthesized /PROP is still EXPLAINED once, by the generic
        # element-free-*PART report that names the pid — no separate INFO note
        # is added here, so the log stays one message per empty part
        explains = [w for w in result.warnings if "*PART record(s) 88" in w
                    and "PLACEHOLDER" in w and "material carrier" in w]
        self.assertEqual(len(explains), 1, result.warnings)

    def test_icomp_angles_and_rule_thicknesses_compose(self):
        """ICOMP=1 gives every integration point an angle and the rule gives
        the SAME point a thickness and a material, so the two keywords compose:
        one B_i and one S/WF/PID per point. T1 = 1.2 with WF = 1/2/1 (sum 4)
        gives 0.3 / 0.6 / 0.3 by hand."""
        section = _section(nip=3, t1=1.2, icomp=1, betas=(0.0, 45.0, -45.0))
        rule = _rule(points=((-1.0, 1.0, 0), (0.0, 2.0, 0), (1.0, 1.0, 0)))
        result, starter = _convert(_deck(mat=_mat002(), mid=2, section=section,
                                         rule=rule))
        layup = _layup(starter)
        self.assertEqual([p for p, _, _ in layup], [0.0, 45.0, -45.0])
        self.assertEqual([t for _, t, _ in layup], [0.3, 0.6, 0.3])
        self.assertTrue(_warned(result, "ICOMP=1",
                                "layer THICKNESSES come from the "
                                "*INTEGRATION_SHELL 3 rule"))
        self.assertFalse(_warned(result, "still split EVENLY"))

    def test_icomp_angles_follow_their_layer_through_a_reorder(self):
        """The angle belongs to the integration POINT, so re-ordering the
        layers bottom-up must carry each B_i with its own layer."""
        section = _section(nip=3, t1=1.2, icomp=1, betas=(0.0, 45.0, -45.0))
        rule = _rule(points=((1.0, 1.0, 0), (0.0, 2.0, 0), (-1.0, 1.0, 0)))
        _, starter = _convert(_deck(mat=_mat002(), mid=2, section=section,
                                    rule=rule))
        self.assertEqual([p for p, _, _ in _layup(starter)],
                         [-45.0, 45.0, 0.0])

    def test_too_few_icomp_angles_for_the_rules_points_is_warned(self):
        """The card-3 B_i block is read with the SECTION's NIP, so a rule with
        more integration points leaves the tail padded with 0 deg. Silent
        padding turns a [0/45/90] layup into [0, 45, 90, 0, 0]."""
        section = _section(nip=3, t1=1.0, icomp=1, betas=(0.0, 45.0, 90.0))
        rule = _rule(nip=5, points=tuple((-1.0 + 0.5 * k, 0.2, 0)
                                         for k in range(5)))
        result, starter = _convert(_deck(mat=_mat002(), mid=2, section=section,
                                         rule=rule))
        self.assertEqual([p for p, _, _ in _layup(starter)],
                         [0.0, 45.0, 90.0, 0.0, 0.0])
        self.assertTrue(_warned(result, "ICOMP=1 supplies only 3 material "
                                        "angle(s)",
                                "defines 5 integration point(s)",
                                "last 2 layer(s) are emitted at 0 deg"))

    def test_icomp_even_split_warning_survives_without_a_rule(self):
        """The no-rule ICOMP path is untouched: the section thickness is still
        split evenly and the warning still names the rule as where the real
        thicknesses would come from."""
        section = _section(nip=3, t1=1.2, qr_irid=0.0, icomp=1,
                           betas=(0.0, 45.0, -45.0))
        result, starter = _convert(_deck(mat=_mat002(), mid=2, section=section,
                                         rule=""))
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE11/")), 1)
        for _, t, _ in _layup(starter):
            self.assertAlmostEqual(t, 0.4)
        self.assertTrue(_warned(result, "still split EVENLY",
                                "*INTEGRATION_SHELL"))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_LAMINATED_GLASS (032) driven by a rule
# ═════════════════════════════════════════════════════════════════════════════

class LaminatedGlassRuleTests(unittest.TestCase):
    """*MAT_032 is the material that REQUIRES an *INTEGRATION_SHELL rule in
    LS-DYNA, so the rule is where its real layer thicknesses live."""

    # A 2 mm windshield: 0.8 glass / 0.2 PVB / 0.2 PVB / 0.8 glass.
    GLASS_RULE = _rule(irid=4, nip=4,
                       points=((-1.0, 0.4, 0), (-0.3, 0.1, 0),
                               (0.3, 0.1, 0), (1.0, 0.4, 0)))

    def _glass(self, rule=None, f=(0.0, 1.0, 1.0, 0.0), section=None,
               extra=""):
        return _convert(_deck(
            mat=_mat032(f=f), mid=32,
            section=(section if section is not None
                     else _section(nip=4, qr_irid=-4.0)),
            rule=(self.GLASS_RULE if rule is None else rule), extra=extra))

    def _glass_mid(self, starter):
        return int([b[0] for b in _blocks(starter, "/MAT/LAW27/")
                    if b[0] != "/MAT/LAW27/32"][0].rsplit("/", 1)[1])

    def test_rule_thicknesses_replace_the_even_split(self):
        """T1 = 2.0 with WF = 0.4/0.1/0.1/0.4 gives 0.8/0.2/0.2/0.8 by hand -
        the even split would have been 4 x 0.5, i.e. a 0.5 mm interlayer where
        the deck asked for 0.2."""
        _, starter = self._glass()
        self.assertEqual([t for _, t, _ in _layup(starter)],
                         [0.8, 0.2, 0.2, 0.8])

    def test_the_glass_pair_stays_on_a_single_type11(self):
        """Both phases are /MAT/PLAS_BRIT (LAW27), which is on TYPE11's law
        whitelist and is ONE law across every layer - so this route keeps the
        single layered property it always had."""
        _, starter = self._glass()
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE11/")), 1)
        self.assertEqual(_blocks(starter, "/PROP/TYPE51"), [])

    def test_glass_and_polymer_land_on_the_right_layers(self):
        """LS-DYNA F_i = 0 -> glass, F_i = 1 -> polymer; the POLYMER keeps the
        LS-DYNA MID and the GLASS takes the synthesized id."""
        _, starter = self._glass()
        gid = self._glass_mid(starter)
        self.assertEqual([m for _, _, m in _layup(starter)],
                         [gid, 32, 32, gid])

    def test_even_split_warning_is_retired_when_a_rule_exists(self):
        result, _ = self._glass()
        self.assertFalse(_warned(result, "split EVENLY"), result.warnings)
        self.assertTrue(_warned(result, "*MAT_LAMINATED_GLASS 32",
                                "come from the *INTEGRATION_SHELL 4 rule"))

    def test_even_split_warning_is_kept_without_a_rule(self):
        """No rule in the deck: nothing to derive the thicknesses from, so the
        even split - and the warning that names it - must stand."""
        result, starter = self._glass(rule="",
                                      section=_section(nip=4, qr_irid=0.0))
        for _, t, _ in _layup(starter):
            self.assertAlmostEqual(t, 0.5)
        self.assertTrue(_warned(result, "split EVENLY", "*INTEGRATION_SHELL"))
        self.assertTrue(_warned(result, "this section references none"))

    def test_an_esop_one_rule_is_not_reported_as_no_rule_at_all(self):
        """_layered_rule() is None for an ESOP=1 rule BY DESIGN — equal layers
        need no layered property — so the no-rule branch also ran when the deck
        DID bind one, and told the user to add a rule that was already there.
        Four equal layers is exactly what ESOP=1 means, so the split is right;
        only the explanation was wrong."""
        result, starter = self._glass(rule=_rule(irid=4, nip=4, esop=1))
        for _, t, _ in _layup(starter):
            self.assertAlmostEqual(t, 0.5)
        self.assertFalse(_warned(result, "this section references none"))
        self.assertTrue(_warned(result, "*INTEGRATION_SHELL 4 rule this "
                                        "section references is ESOP=1",
                                "the even split IS the rule"))

    def test_a_dropped_rule_is_reported_as_dropped_not_as_absent(self):
        result, _ = self._glass(rule=_rule(irid=4, nip=4, esop=7))
        self.assertFalse(_warned(result, "this section references none"))
        self.assertTrue(_warned(result, "*INTEGRATION_SHELL 4 rule this "
                                        "section references was DROPPED"))

    def test_pid_wins_over_the_f_flag(self):
        """dyna2rad's precedence, verbatim: the isMat032 branch sits in the
        ELSE of 'if (matHandle.IsValid())', so a resolved PID_i beats F_i.
        The foreign LAW36 layer also pushes the stack off TYPE11."""
        rule = _rule(irid=4, nip=4,
                     points=((-1.0, 0.4, 0), (-0.3, 0.1, 88),
                             (0.3, 0.1, 0), (1.0, 0.4, 0)))
        _, starter = self._glass(rule=rule, extra=CORE_PART + FOAM)
        gid = self._glass_mid(starter)
        self.assertEqual([m for _, _, m in _layup(starter)],
                         [gid, 4, 32, gid])
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE51/")), 1)

    def test_f_count_mismatch_names_the_rules_nip(self):
        """The old message compared against the *SECTION_SHELL NIP, which is
        dead once a rule is bound."""
        result, _ = self._glass(f=(0.0, 1.0))
        self.assertTrue(_warned(result, "F array has 2 entries",
                                "from *INTEGRATION_SHELL 4"))

    def test_no_f_array_leaves_every_rule_layer_glass(self):
        result, starter = self._glass(f=())
        gid = self._glass_mid(starter)
        self.assertEqual([m for _, _, m in _layup(starter)], [gid] * 4)


# ═════════════════════════════════════════════════════════════════════════════
# Interaction rules and the routes a rule cannot reach
# ═════════════════════════════════════════════════════════════════════════════

class IntegrationShellInteractionTests(unittest.TestCase):

    def test_dangling_irid_falls_back_and_is_warned(self):
        """dyna2rad drops the same dangling reference in silence."""
        result, starter = _convert(_deck(section=_section(nip=3, qr_irid=-9.0),
                                         rule=_rule(irid=4, nip=2, esop=1)))
        self.assertFalse(_layered(starter))
        self.assertEqual(_i10(_cards(_block(starter, "/PROP/SHELL/7"))[2], 0), 3)
        self.assertTrue(_warned(result, "QR/IRID) is -9", "does NOT define"))

    def test_a_rule_nobody_references_is_recognized_not_emitted(self):
        """The keyword has a handler, so it never lands in skipped_keywords -
        without this channel it would vanish from the accounting entirely."""
        result, _ = _convert(_deck(section=_section(qr_irid=0.0),
                                   rule=_rule(irid=4, nip=2, esop=1)))
        kws = [kw for kw, _ in result.recognized_not_emitted]
        self.assertIn("*INTEGRATION_SHELL", kws)
        reason = dict(result.recognized_not_emitted)["*INTEGRATION_SHELL"]
        self.assertIn("rule(s) 4", reason)

    def test_esop_other_than_zero_or_one_is_dropped_and_warned(self):
        """dyna2rad's bare switch(ESOP) has no default branch and emits a
        property declaring NIP plies with no ply objects at all."""
        result, starter = _convert(_deck(rule=_rule(nip=3, esop=2)))
        self.assertFalse(_layered(starter))
        self.assertTrue(_warned(result, "ESOP=2 is neither 0"))

    def test_zero_nip_rule_is_dropped_and_warned(self):
        result, starter = _convert(_deck(
            rule="*INTEGRATION_SHELL\n" + _row(3, 0, 0, 0) + "\n"))
        self.assertFalse(_layered(starter))
        self.assertTrue(_warned(result, "NIP=0 defines no integration point"))

    def test_zero_weight_sum_is_dropped_and_warned(self):
        """dyna2rad divides by that sum unguarded and writes inf/nan."""
        rule = _rule(nip=2, points=((-1.0, 0.0, 0), (1.0, 0.0, 0)))
        result, starter = _convert(_deck(rule=rule))
        self.assertFalse(_layered(starter))
        self.assertTrue(_warned(result, "weighting factors sum to 0"))

    def test_failopt_drop_is_warned(self):
        result, _ = _convert(_deck(rule=_rule(failopt=1)))
        self.assertTrue(_warned(result, "FAILOPT=1 is DROPPED",
                                "P_Thick_Fail"))

    def test_solid_part_rule_is_dropped_and_warned(self):
        deck = ("*KEYWORD\n" + SOLID_NODES + BRICK
                + "*PART\np\n" + _row(7, 7, 3) + "\n"
                + _section() + SECTION_SOLID + _rule() + STEEL + END)
        result, starter = _convert(deck)
        self.assertFalse(_layered(starter))
        self.assertTrue(_warned(result, "SOLID elements",
                                "no /PROP/SOLID counterpart"))

    def test_part_composite_wins_over_a_rule(self):
        """*PART_COMPOSITE replaces the *PART/*SECTION_SHELL pair outright, so
        the section - and the rule it references - is never consulted."""
        # *PART_COMPOSITE always carries a heading line, like *PART; the ply
        # cards then pack MID THICK B TMID, two plies per card.
        pc = ("*PART_COMPOSITE\ncarbon layup\n"
              + _row(7, 2, 1.0, 0.0, 0.0) + "\n"
              + _row(2, 0.3, 0.0, 0, 2, 0.4, 45.0, 0) + "\n")
        deck = ("*KEYWORD\n" + NODES + SHELL + pc + _section() + _rule()
                + _mat002() + END)
        result, starter = _convert(deck)
        self.assertEqual(_blocks(starter, "/PROP/TYPE11"), [])
        self.assertEqual([_col_f(_cards(b)[0], 11, 30)
                          for b in _blocks(starter, "/PROP/TYPE19/")],
                         [0.3, 0.4])
        self.assertTrue(_warned(result, "*PART_COMPOSITE layup, which WINS"))

    def test_mat037_type9_route_drops_the_rule(self):
        """/MAT/LAW43 lands on /PROP/TYPE9 (SH_ORTH), a single-layer
        orthotropic shell with no per-layer thickness column."""
        result, starter = _convert(_deck(mat=_mat037(), mid=37))
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE9")), 1)
        self.assertFalse(_layered(starter))
        self.assertTrue(_warned(result, "LAW43", "single-layer orthotropic"))


# ═════════════════════════════════════════════════════════════════════════════
# RIDER: multi card set *SECTION_SHELL
# ═════════════════════════════════════════════════════════════════════════════

class SectionShellMultiSetTests(unittest.TestCase):
    """"Card Sets.  For each shell section, of a type matching the keyword's
    options, include one set of data cards.  This input ends at the next keyword
    ("*") card." (Manual Vol I R17 p.41-62).

    Reading only the first set dropped every later section silently, and a
    *PART pointing at one of them fell through to the zero-thickness
    _auto_section_shell placeholder, which the starter rejects.
    """

    TWO_SETS = ("*SECTION_SHELL\n"
                + _row(8, 2, 1.0, 3) + "\n" + _row(2.0) + "\n"
                + _row(9, 16, 1.0, 5) + "\n" + _row(3.5) + "\n")

    def test_both_card_sets_are_parsed(self):
        state = _dispatch("*KEYWORD\n" + self.TWO_SETS + "*END\n")
        self.assertEqual(sorted(state.sec_shells), [8, 9])
        self.assertEqual((state.sec_shells[9].elform, state.sec_shells[9].nip,
                          state.sec_shells[9].t1), (16, 5, 3.5))

    def test_a_later_set_reaches_its_part(self):
        """The regression this rider exists for: SECID 9's real 3.5 thickness
        instead of the auto-section's 0.0."""
        deck = ("*KEYWORD\n" + NODES
                + "*ELEMENT_SHELL\n" + _row(1, 9, 1, 2, 3, 4) + "\n"
                + "*PART\np\n" + _row(9, 9, 3) + "\n"
                + self.TWO_SETS + STEEL + END)
        _, starter = _convert(deck)
        prop = _cards(_block(starter, "/PROP/SHELL/9"))
        self.assertAlmostEqual(_col_f(prop[2], 21, 40), 3.5)
        self.assertEqual(_i10(prop[2], 0), 5)

    def test_an_icomp_set_advances_the_cursor_by_its_angle_cards(self):
        """A set consumes 2 + ceil(NIP/8) cards when ICOMP = 1, so a fixed
        stride of 2 would read the angle card as the next section."""
        deck = ("*KEYWORD\n*SECTION_SHELL\n"
                + _row(8, 2, 1.0, 4, 0.0, 0.0, 1) + "\n" + _row(2.0) + "\n"
                + _row(0.0, 45.0, -45.0, 90.0) + "\n"
                + _row(9, 2, 1.0, 2) + "\n" + _row(3.0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(sorted(state.sec_shells), [8, 9])
        self.assertEqual(state.sec_shells[8].betas, [0.0, 45.0, -45.0, 90.0])
        self.assertEqual(state.sec_shells[9].t1, 3.0)

    def test_the_title_option_repeats_per_set(self):
        """"An additional option TITLE may be appended ... an addition line is
        read for each section in 80a format" (Vol I R17 p.41-1)."""
        deck = ("*KEYWORD\n*SECTION_SHELL_TITLE\nouter skin\n"
                + _row(8, 2, 1.0, 3) + "\n" + _row(2.0) + "\n"
                + "inner skin\n" + _row(9, 2, 1.0, 4) + "\n"
                + _row(3.0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(state.sec_shells[8].title, "outer skin")
        self.assertEqual(state.sec_shells[9].title, "inner skin")
        self.assertEqual(state.sec_shells[9].t1, 3.0)

    def test_each_set_binds_its_own_rule(self):
        state = _dispatch("*KEYWORD\n*SECTION_SHELL\n"
                          + _row(8, 2, 1.0, 3, 0.0, -3.0) + "\n"
                          + _row(2.0) + "\n"
                          + _row(9, 2, 1.0, 3, 0.0, 0.0) + "\n"
                          + _row(3.0) + "\n*END\n")
        self.assertEqual(state.sec_shells[8].irid, 3)
        self.assertEqual(state.sec_shells[9].irid, 0)

    def test_a_single_set_deck_is_unchanged(self):
        state = _dispatch("*KEYWORD\n" + _section(qr_irid=0.0) + "*END\n")
        self.assertEqual(sorted(state.sec_shells), [7])
        self.assertEqual(state.warnings, [])

    def test_unreadable_trailing_cards_stop_the_walk_loudly(self):
        """A set holding cards k2rad does not model (the ELFORM 101-105
        user-shell block) desynchronizes the cursor; stopping there must be
        reported, not silent."""
        deck = ("*KEYWORD\n" + self.TWO_SETS + _row("", 2, 1.0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(sorted(state.sec_shells), [8, 9])
        self.assertTrue(any("2 complete card set(s)" in w
                            for w in state.warnings), state.warnings)

    def test_negative_nip_is_warned_and_taken_absolute(self):
        """Previously silent AND doubly wrong: NIP clamped to 2, and
        _read_icomp_angles trimmed the deck's four angles to the first two
        without tripping its own truncation warning."""
        deck = ("*KEYWORD\n*SECTION_SHELL\n"
                + _row(7, 2, 1.0, -4, 0.0, 0.0, 1) + "\n" + _row(1.2) + "\n"
                + _row(0.0, 45.0, -45.0, 90.0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(state.sec_shells[7].nip, 4)
        self.assertEqual(state.sec_shells[7].betas, [0.0, 45.0, -45.0, 90.0])
        self.assertTrue(any("NIP=-4 is negative" in w for w in state.warnings))

    def test_a_blank_title_line_is_the_title_card_not_padding(self):
        """The 80a title card is read once per set unconditionally, so a blank
        (or all-spaces) title IS the card. Skipping it as padding shifted the
        set up one line, read card 1 as the title and card 2 as card 1, and
        registered a phantom section under int(T1) that OVERWROTE a real one.
        """
        deck = ("*KEYWORD\n*SECTION_SHELL_TITLE\n"
                + "skin section\n" + _row(2, 2, 1.0, 3) + "\n"
                + _row(1.5, 1.5, 1.5, 1.5) + "\n"
                + "   \n" + _row(8, 2, 1.0, 5) + "\n"
                + _row(2.0, 2.0, 2.0, 2.0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(sorted(state.sec_shells), [2, 8])
        self.assertEqual((state.sec_shells[2].title, state.sec_shells[2].t1,
                          state.sec_shells[2].nip), ("skin section", 1.5, 3))
        self.assertEqual((state.sec_shells[8].title, state.sec_shells[8].t1,
                          state.sec_shells[8].nip), ("", 2.0, 5))
        self.assertEqual(state.warnings, [])

    def test_trailing_blank_lines_end_the_walk_quietly(self):
        deck = ("*KEYWORD\n" + self.TWO_SETS + "\n   \n\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(sorted(state.sec_shells), [8, 9])
        self.assertEqual(state.warnings, [])

    def test_user_shell_elform_cards_are_strided_over(self):
        """Cards 5 / 5.1 / 5.2 exist for ELFORM 101-105 (Vol I R17 p.41-63) and
        card 5 starts with NIPP, a POSITIVE integer — so the "no positive SECID"
        stop never fires on it. Striding by 1 + NIPP + ceil(LMC/8) is what keeps
        the PRECEDING section from being clobbered by a phantom read out of
        card 5's own columns."""
        deck = ("*KEYWORD\n*SECTION_SHELL\n"
                + _row(4, 2, 1.0, 3) + "\n" + _row(1.0) + "\n"
                + _row(20, 101, 1.0, 3) + "\n" + _row(2.0) + "\n"
                # card 5: NIPP=4 NXDOF=1 ... LMC=2
                + _row(4, 1, 0, 0, 0, 2, 0, 0) + "\n"
                + _row(0.0, 0.0, 0.0) + "\n" + _row(0.0, 0.0, 0.0) + "\n"
                + _row(0.0, 0.0, 0.0) + "\n" + _row(0.0, 0.0, 0.0) + "\n"
                + _row(1.0, 2.0) + "\n"
                + _row(9, 2, 1.0, 4) + "\n" + _row(3.0) + "\n*END\n")
        state = _dispatch(deck)
        self.assertEqual(sorted(state.sec_shells), [4, 9, 20])
        self.assertEqual((state.sec_shells[4].t1, state.sec_shells[4].elform),
                         (1.0, 2))
        self.assertEqual(state.sec_shells[20].t1, 2.0)
        self.assertEqual(state.sec_shells[9].t1, 3.0)
        self.assertTrue(any("ELFORM=101 is a USER-DEFINED shell" in w
                            for w in state.warnings), state.warnings)

    def test_a_duplicate_secid_is_warned(self):
        state = _dispatch("*KEYWORD\n*SECTION_SHELL\n"
                          + _row(8, 2, 1.0, 3) + "\n" + _row(2.0) + "\n"
                          + _row(8, 2, 1.0, 5) + "\n" + _row(4.0) + "\n*END\n")
        self.assertEqual(state.sec_shells[8].t1, 4.0)       # last wins
        self.assertTrue(any("*SECTION_SHELL 8 is defined more than once" in w
                            for w in state.warnings), state.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Regression: no flag, no behaviour change on a deck without these cards
# ═════════════════════════════════════════════════════════════════════════════

class IntegrationShellRegressionTests(unittest.TestCase):

    def test_plain_deck_emits_no_layered_property(self):
        deck = ("*KEYWORD\n" + NODES + SHELL + "*PART\np\n" + _row(7, 7, 3)
                + "\n" + _section(qr_irid=0.0) + STEEL + END)
        result, starter = _convert(deck)
        for kw in ("/PROP/TYPE11", "/PROP/TYPE51", "/PROP/TYPE19",
                   "COMPOSITE PROPERTIES"):
            self.assertNotIn(kw, starter, kw)
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/7")), 1)
        self.assertEqual([w for w in result.warnings
                          if "INTEGRATION_SHELL" in w], [])

    def test_goldens_are_unchanged(self):
        """No checked-in fixture contains an *INTEGRATION_SHELL, a multi-set
        *SECTION_SHELL or a negative QR/IRID, so all five golden decks must
        still match byte-for-byte (asserted here per repo policy for a no-flag
        feature)."""
        from tests import test_golden
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(test_golden)
        result = unittest.TextTestRunner(
            stream=open(os.devnull, "w"), verbosity=0).run(suite)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])


if __name__ == "__main__":
    unittest.main()
