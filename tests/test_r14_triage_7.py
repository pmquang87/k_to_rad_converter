"""Tests for the R14 CAMPAIGN TRIAGE batch, round 7 — PART A:

  A1  the double-/BCS merge: a *NODE TC/RC (or *CONSTRAINED_GLOBAL) code
      re-pointed onto an /RBODY main node is MERGED into the /BCS the rigid
      body itself writes there (BC_rigid_<pid>, BC_cnrb_<pid> at skew 0)
      instead of being written a second time (inside --no-node-tc-rc-bcs /
      --no-constrained-global, no flag of its own)
  A2  J = -SUM(IN) on every *MAT_RIGID / *DEFORMABLE_TO_RIGID part /RBODY
      carrying shell rotary inertia (default ON,
      --no-rigid-shell-rotary-inertia) + the two --mass-weighted-inivel
      guards
  A3  the *MAT_SPOTWELD weld: (i) a yielding TYPE13 shear (default ON,
      --no-spotweld-shear-yield); (ii) EFAIL with no resultant cell ->
      Ifail 1 / Ifail2 0 displacement failure (default ON,
      --no-spotweld-efail-displacement)
  A4  the implicit *MAT_ELASTIC thick shell -> /PROP/SOLID Isolid 14 on the
      same /BRICK rows (default ON, --no-implicit-tshell-solid) and the
      lumper that skipped thick shells
  A5  the implicit / spring texts (0 bytes): the vdc remedy is not about
      k2rad's own stub; the EFG placeholder is named; IMFLAG < 0 and
      2/4/5/6 are named; the LIGHT clause states its per-pair numbers

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are the round-4/5/6 ones, copied (not imported) so this
module runs on its own.
"""

import math
import os
import re
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the helpers of tests/test_r14_triage_6.py) ──────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


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


def _has(warnings, *needles) -> bool:
    return any(all(n in w for n in needles) for w in warnings)


def _bcs_groups(starter: str):
    """``{title: (codes, sorted node ids)}`` for every ``/BCS`` whose group is
    a ``/GRNOD/NODE`` of this deck (the round-6 helper)."""
    lines = starter.splitlines()
    grnod = {}
    i = 0
    while i < len(lines):
        m = re.match(r"^/GRNOD/NODE/(\d+)$", lines[i])
        if m:
            ids = []
            j = i + 2
            while (j < len(lines) and not lines[j].startswith("/")
                   and not lines[j].startswith("#-")):
                if not lines[j].startswith("#"):
                    ids += [int(t) for t in lines[j].split()]
                j += 1
            grnod[int(m.group(1))] = ids
            i = j
            continue
        i += 1
    out = {}
    for i, ln in enumerate(lines):
        if ln.startswith("/BCS/"):
            data = lines[i + 3].split()
            out[lines[i + 1]] = (" ".join(data[:2]),
                                 sorted(grnod.get(int(data[-1]), [])))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# A1 — the rigid body's own /BCS absorbs a re-pointed member TC/RC code
# ═════════════════════════════════════════════════════════════════════════════

def _a1_deck(cmo=1.0, con1=7, con2=7, tc=3, rc=0, elastic_tc=(0, 0),
             extra="") -> str:
    """The A1 starter probes (part-A spec A1.6): a 2 x 2 *MAT_RIGID shell
    plate (part 1, nodes 1-9, z = 0) whose *NODE rows state (*tc*, *rc*), and
    a separate 2 x 2 *MAT_ELASTIC plate (part 2, nodes 10-18, z = 5) whose
    rows state *elastic_tc*. Converted, the rigid plate's synthesized main
    node is 19. P1 = (CMO 1, CON1 7, CON2 7, TC 3 RC 0): the TC/RC union
    001 000 lies inside BC_rigid 111 111. P2 = (CMO 1, CON1 1, CON2 7, TC 6
    RC 7): union 101 111 against BC_rigid 100 111 - 4 common DOFs merged, the
    remainder 001 000 is disjoint."""
    lines = ["*KEYWORD", "*CONTROL_TERMINATION", _row(0.001),
             "*PART", "rigid plate", _row(1, 1, 1),
             "*PART", "elastic plate", _row(2, 1, 2),
             "*SECTION_SHELL", _row(1, 2, 1.0, 2), _row(1.0, 1.0, 1.0, 1.0),
             "*MAT_RIGID", _row(1, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0),
             f"{cmo:10.1f}{con1:10d}{con2:10d}",
             _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
             "*MAT_ELASTIC", _row(2, 7.85e-9, 210000.0, 0.3),
             "*NODE"]
    nid = 0
    for z, (t, r) in ((0.0, (tc, rc)), (5.0, elastic_tc)):
        for j in range(3):
            for i in range(3):
                nid += 1
                lines.append(f"{nid:>8}{10.0 * i:>16.6f}{10.0 * j:>16.6f}"
                             f"{z:>16.6f}{t:>8}{r:>8}")
    lines.append("*ELEMENT_SHELL")
    eid = 0
    for base, pid in ((0, 1), (9, 2)):
        for j in range(2):
            for i in range(2):
                n1 = base + j * 3 + i + 1
                eid += 1
                lines.append("".join(f"{v:>8}" for v in
                                     (eid, pid, n1, n1 + 1, n1 + 4, n1 + 3)))
    return "\n".join(lines) + "\n" + extra + "*END\n"


_A1_NEW = "rigid-body main node(s)"
_A1_SPC = "already stated by a *BOUNDARY_SPC"


def _node_warning(result):
    hit = [w for w in result.warnings if w.startswith("*NODE: ")]
    assert len(hit) == 1, result.warnings
    return hit[0]


class RigidOwnBcsAbsorbsMemberTcRc(unittest.TestCase):
    """A1 — ``BC_rigid_<pid>`` (``*MAT_RIGID`` CMO 1 CON1/CON2) and
    ``BC_cnrb_<pid>`` (CNRB ``_SPC`` at skew 0) sit on the /RBODY main node
    rule (a) re-points the members' TC/RC cells onto; screen (c') merges the
    common DOFs into the rigid body's own card. ``hm_read_bcs.F:198`` unions
    the codes (MY_OR), so the old second /BCS was 0 physics and only starter
    WARNING 312. MEASURED for the spec at nt 4 (starter only): P1's base
    gives 1 x WARNING 312 (1 INCOMPATIBLE KINEMATIC CONDITION) and the merged
    form none; P2's base 4 conditions, its merged remainder 001 000 none."""

    def test_1_P1_merged_and_emptied(self):
        res, starter, _e = _convert(_a1_deck())
        groups = _bcs_groups(starter)
        self.assertEqual(groups["BC_rigid_1"], ("111 111", [19]))
        self.assertEqual([t for t in groups if t.startswith("node_tc_rc_")],
                         [], groups)
        w = _node_warning(res)
        self.assertIn("1 DOF(s) on 1 rigid-body main node(s) (node 19)", w)
        self.assertIn("(BC_rigid_1: *MAT_RIGID CMO 1 CON1/CON2", w)
        self.assertIn("had every stated DOF removed", w)
        self.assertIn("hm_read_bcs.F:198 unions the codes (MY_OR)", w)
        self.assertNotIn(_A1_SPC, w)

    def test_2_P2_keeps_the_disjoint_remainder(self):
        res, starter, _e = _convert(_a1_deck(con1=1, con2=7, tc=6, rc=7))
        groups = _bcs_groups(starter)
        self.assertEqual(groups, {
            "BC_rigid_1": ("100 111", [19]),
            "node_tc_rc_001_000": ("001 000", [19]),
        })
        a = groups["BC_rigid_1"][0].replace(" ", "")
        b = groups["node_tc_rc_001_000"][0].replace(" ", "")
        self.assertFalse(any(x == y == "1" for x, y in zip(a, b)),
                         "the two codes must share no DOF (no WARNING 312)")
        w = _node_warning(res)
        self.assertIn("4 DOF(s) on 1 rigid-body main node(s) (node 19)", w)
        self.assertNotIn("had every stated DOF removed", w)

    def test_3_a_CNRB_SPC_card_at_skew_0_absorbs_the_code_too(self):
        extra = ("*SET_NODE_LIST\n" + _row(7) + "\n"
                 + _row(10, 11, 12, 13, 14, 15, 16, 17) + "\n" + _row(18)
                 + "\n*CONSTRAINED_NODAL_RIGID_BODY_SPC\n" + _row(50, 0, 7)
                 + "\n" + _row(1.0, 7, 0) + "\n")
        res, starter, _e = _convert(_a1_deck(tc=0, elastic_tc=(3, 0),
                                             extra=extra))
        groups = _bcs_groups(starter)
        cnrb = groups["BC_cnrb_50"]
        self.assertEqual(cnrb[0], "111 000")
        main = cnrb[1]
        self.assertEqual(len(main), 1, groups)
        self.assertEqual([t for t, (_c, ids) in groups.items()
                          if t.startswith("node_tc_rc_") and main[0] in ids],
                         [], groups)
        w = _node_warning(res)
        self.assertIn(f"(node {main[0]}) are already fixed by the /BCS the "
                      "rigid body itself writes there (BC_cnrb_50:", w)

    def test_4_a_skewed_CNRB_SPC_card_is_NOT_merged(self):
        """CMO -1: CON1 is a local system, CON2 a 6-digit code - its digits
        are axes of that skew, so no global TC/RC bit can be cancelled
        against them (reach 0; this pins the skew rule)."""
        extra = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _row(5, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _row(0.0, 1.0, 0.0) + "\n"
                 "*SET_NODE_LIST\n" + _row(7) + "\n"
                 + _row(10, 11, 12, 13, 14, 15, 16, 17) + "\n" + _row(18)
                 + "\n*CONSTRAINED_NODAL_RIGID_BODY_SPC\n" + _row(50, 0, 7)
                 + "\n" + _row(-1.0, 5, 111000) + "\n")
        res, starter, _e = _convert(_a1_deck(tc=0, elastic_tc=(3, 0),
                                             extra=extra))
        groups = _bcs_groups(starter)
        main = groups["BC_cnrb_50"][1]
        self.assertEqual(groups["node_tc_rc_001_000"], ("001 000", main))
        self.assertFalse(_has(res.warnings, _A1_NEW), res.warnings)

    def test_5_the_CONSTRAINED_GLOBAL_provenance_prints_its_own_sentence(self):
        extra = "*CONSTRAINED_GLOBAL\n" + _row(3, 0, 3, 0.0, 0.0, 0.0, 0.0) + "\n"
        res, starter, _e = _convert(_a1_deck(tc=0, extra=extra))
        groups = _bcs_groups(starter)
        self.assertEqual(groups["BC_rigid_1"], ("111 111", [19]))
        self.assertEqual([t for t in groups
                          if t.startswith("constrained_global_")], [], groups)
        glob = [w for w in res.warnings
                if w.startswith("*CONSTRAINED_GLOBAL: ")]
        self.assertEqual(len(glob), 1, res.warnings)
        self.assertIn("1 DOF(s) on 1 rigid-body main node(s) (node 19)",
                      glob[0])
        self.assertIn("BC_rigid_1", glob[0])

    def test_6_which_screen_fired(self):
        """Two screens that return the same bytes hide each other's deletion:
        P1 is screen (c') and NOT (c); an ordinary node with *BOUNDARY_SPC
        dofz 1 and *NODE TC 3 (the ex_12-family shape) is (c) and NOT (c')."""
        res, _s, _e = _convert(_a1_deck())
        w = _node_warning(res)
        self.assertIn(_A1_NEW, w)
        self.assertNotIn(_A1_SPC, w)
        extra = ("*BOUNDARY_SPC_NODE\n" + _row(10, 0, 0, 0, 1, 0, 0, 0)
                 + "\n")
        res2, starter2, _e2 = _convert(_a1_deck(tc=0, elastic_tc=(3, 0),
                                                extra=extra))
        w2 = _node_warning(res2)
        self.assertIn(_A1_SPC, w2)
        self.assertNotIn(_A1_NEW, w2)
        groups = _bcs_groups(starter2)
        self.assertNotIn(10, [n for t, (_c, ids) in groups.items()
                              if t.startswith("node_tc_rc_") for n in ids])

    def test_7_the_opt_out_scope_is_unchanged(self):
        """--no-node-tc-rc-bcs drops the *NODE cells, so nothing is left to
        merge: the file equals the one with screen (c')'s source emptied."""
        from k2rad.writer import loads
        res, s_off, e_off = _convert(_a1_deck(), node_tc_rc_bcs=False)
        groups = _bcs_groups(s_off)
        self.assertEqual(groups, {"BC_rigid_1": ("111 111", [19])})
        self.assertTrue(_has(res.warnings, "--no-node-tc-rc-bcs", "FREE"))
        self.assertFalse(_has(res.warnings, _A1_NEW))
        saved = loads._rigid_auto_spc_dofs
        loads._rigid_auto_spc_dofs = lambda state: {}
        try:
            _r, s_ctl, e_ctl = _convert(_a1_deck(), node_tc_rc_bcs=False)
        finally:
            loads._rigid_auto_spc_dofs = saved
        self.assertEqual(s_off, s_ctl)
        self.assertEqual(e_off, e_ctl)

    def test_8_without_the_merge_source_the_old_double_BCS_returns(self):
        """The control arm: screen (c')'s source emptied reproduces the
        65ff389 layout (the main node in TWO /BCS groups with a common DOF),
        so the test above is reached by the branch under test."""
        from k2rad.writer import loads
        saved = loads._rigid_auto_spc_dofs
        loads._rigid_auto_spc_dofs = lambda state: {}
        try:
            res, starter, _e = _convert(_a1_deck())
        finally:
            loads._rigid_auto_spc_dofs = saved
        groups = _bcs_groups(starter)
        self.assertEqual(groups["BC_rigid_1"], ("111 111", [19]))
        self.assertEqual(groups["node_tc_rc_001_000"], ("001 000", [19]))
        self.assertFalse(_has(res.warnings, _A1_NEW))

    def test_9_the_record_is_reset_before_the_early_returns(self):
        """``state.rigid_auto_bcs`` mirrors the cards ONE call emits: a second
        call on a state that has no rigid body any more must leave it empty
        (the reset sits above both early returns)."""
        from k2rad.writer.rbody import _make_rbodies
        state = _dispatch(_a1_deck())
        _make_rbodies(state)
        self.assertEqual(state.rigid_auto_bcs, {19: ("111", "111",
                                                     "BC_rigid_1")})
        state.mat_rigid.clear()
        _make_rbodies(state)
        self.assertEqual(state.rigid_auto_bcs, {})

    def test_10_the_record_holds_the_EMITTED_digits(self):
        """The implicit stabilisation of an unloaded free translation edits
        the code BEFORE it is written; the record must hold what was
        written (here CON1 0 / CON2 0 + a z force: x and y auto-pinned)."""
        from k2rad.writer.rbody import _make_rbodies
        deck = _a1_deck(con1=0, con2=0, tc=0).replace(
            "*CONTROL_TERMINATION",
            "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
            "*CONTROL_TERMINATION").replace(
            "*END\n", "*LOAD_RIGID_BODY\n" + _row(1, 3, 1, 1.0) + "\n"
            "*DEFINE_CURVE\n" + _row(1) + "\n" + _row(0.0, 1.0) + "\n"
            + _row(1.0, 1.0) + "\n*END\n")
        state = _dispatch(deck)
        lines, _rn, _ri = _make_rbodies(state)
        self.assertEqual(state.rigid_auto_bcs[19][:2], ("110", "000"))
        self.assertIn("   110 000         0", "\n".join(lines))


# ═════════════════════════════════════════════════════════════════════════════
# A2 — J = -SUM(IN) on every *MAT_RIGID / *DEFORMABLE_TO_RIGID part body
# ═════════════════════════════════════════════════════════════════════════════

def _j_plate_deck(covered=(3, 4), second_rigid=False, icomp=False,
                  thickness=False, extra="") -> str:
    """Round 6's A7 coupon (copied from tests/test_r14_triage_6.py), = G3's
    K1z plate: a rigid 20 x 20 x 2 mm plate (part 1, nodes 1-4, rho 7.85e-9,
    m 6.28e-6; its synthesized main node is 15) plus one 1 x 1 elastic shell
    (part 2, nodes 11-14, t 1.0: m 7.85e-9) and an *INITIAL_VELOCITY_NODE of
    vx 1000 on the plate nodes in *covered*. Hand: SUM(IN) of the plate =
    4 x (m/4)(A + t^2)/12 = 6.28e-6 x 404 / 12 = 2.114266667e-4; IN of one
    elastic-shell node = (7.85e-9/4)(1 + 1)/12 = 3.2708333e-10. *extra* is
    appended before *END."""
    sec1 = (_row(1, 2, 1.0, 2, 1.0, 0, 1 if icomp else 0, 1) + "\n"
            + _row(2.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0) + "\n"
            + (_row(0.0, 0.0) + "\n" if icomp else ""))
    deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-4) + "\n"
            "*PART\nrigid plate\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SHELL\n" + sec1
            + "*PART\nclock shell\n" + _row(2, 2, 2) + "\n"
            "*SECTION_SHELL\n" + _row(2, 2, 1.0, 2, 1.0, 0, 0, 1) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0) + "\n"
            "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
            "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0)
            + "\n" + _row(0.0, 0, 0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            "*NODE\n"
            + "".join(f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n"
                      for n, x, y in ((1, -10, -10), (2, 10, -10), (3, 10, 10),
                                      (4, -10, 10), (11, 100, 0), (12, 101, 0),
                                      (13, 101, 1), (14, 100, 1))))
    if thickness:
        deck += ("*ELEMENT_SHELL_THICKNESS\n"
                 + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)) + "\n"
                 + "".join(f"{v:>16}" for v in (2.0, 2.0, 2.0, 2.0)) + "\n")
    else:
        deck += ("*ELEMENT_SHELL\n"
                 + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)) + "\n")
    deck += "*ELEMENT_SHELL\n" + "".join(f"{v:>8}" for v in
                                         (2, 2, 11, 12, 13, 14)) + "\n"
    if second_rigid:
        deck += ("*PART\nsecond rigid\n" + _row(3, 1, 1) + "\n"
                 "*NODE\n"
                 + "".join(f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n"
                           for n, x, y in ((21, 50, 0), (22, 60, 0),
                                           (23, 60, 10), (24, 50, 10)))
                 + "*ELEMENT_SHELL\n"
                 + "".join(f"{v:>8}" for v in (3, 3, 21, 22, 23, 24)) + "\n")
    deck += "*INITIAL_VELOCITY_NODE\n" + "".join(
        _row(n, 1000.0, 0.0, 0.0) + "\n" for n in covered)
    return deck + extra + "*END\n"


def _rbody_j_rows(starter: str, main: int):
    """(card 1, the Jxx header, the Jxx Jyy Jzz row, the Jxy Jyz Jxz row)."""
    lines = starter.splitlines()
    i = lines.index(f"/RBODY/{main}")
    return lines[i + 3], lines[i + 4], lines[i + 5], lines[i + 7]


def _rbody_main_by_title(starter: str, title: str) -> int:
    """The main node of the ONE /RBODY titled *title* (a /PART may carry the
    same title, so the /RBODY header line is required right above it)."""
    lines = starter.splitlines()
    hits = [int(lines[i - 1].rsplit("/", 1)[1]) for i, ln in enumerate(lines)
            if ln == title and i and lines[i - 1].startswith("/RBODY/")]
    assert len(hits) == 1, (title, hits)
    return hits[0]


def _floats(row: str):
    return [float(row[k:k + 20]) for k in range(0, len(row), 20)]


_J_PLATE = "    -0.0002114266667    -0.0002114266667    -0.0002114266667"
_J_ZERO_ROW = "                   0                   0                   0"
_IN_ELASTIC_NODE = 7.85e-9 / 4.0 * 2.0 / 12.0           # 3.2708333e-10
_A2_APPLIED = "J = -SUM(IN) written into the Jxx/Jyy/Jzz cells"


def _floating_rigid(nodes, pid=5) -> str:
    """An element-free *MAT_RIGID part *pid* formed by
    *CONSTRAINED_EXTRA_NODES_NODE on *nodes* (the elastic shell's, or the
    sliver's below): its synthesized main node is 16."""
    return ("*PART\nfloating rigid\n" + _row(pid, 2, 1) + "\n"
            "*CONSTRAINED_EXTRA_NODES_NODE\n"
            + "".join(_row(pid, n) + "\n" for n in nodes))


def _sliver(dy=1.0e-5) -> str:
    """A 1 x *dy* elastic shell (part 6, nodes 31-34 at y = 200): its corner
    nodes 31 / 32 / 33 are NEARLY collinear - the point-mass tensor's
    smallest principal value is ~1e-10 of its largest, positive."""
    return ("*PART\nsliver\n" + _row(6, 2, 2) + "\n*NODE\n"
            + "".join(f"{n:>8}{x:>16.1f}{y:>16.8f}{0.0:>16.1f}\n"
                      for n, x, y in ((31, 0.0, 200.0), (32, 1.0, 200.0),
                                      (33, 1.0, 200.0 + dy),
                                      (34, 0.0, 200.0 + dy)))
            + "*ELEMENT_SHELL\n"
            + "".join(f"{v:>8}" for v in (6, 6, 31, 32, 33, 34)) + "\n")


class RigidShellRotaryInertiaDefault(unittest.TestCase):
    """A2 — the starter ADDS every shell node's lumped rotary inertia IN to a
    rigid body's tensor (inirby.F:166-168, :355-363) and the /RBODY J cells
    are additive, while LS-DYNA's rigid-part inertia is the point-mass sum:
    the producer writes Jxx = Jyy = Jzz = -SUM(IN) BY DEFAULT (round 7)."""

    def test_1_the_plate_coupon_by_default(self):
        from k2rad.writer.rbody import _A2_REVO_CYCLES, _A2_REVO_RMS
        res, starter, _e = _convert(_j_plate_deck())
        card1, hdr, j1, j2 = _rbody_j_rows(starter, 15)
        self.assertEqual(hdr, "#                Jxx                 Jyy"
                              "                 Jzz")
        self.assertEqual(j1, _J_PLATE)
        self.assertEqual(j2, _J_ZERO_ROW)              # Jxy Jyz Jxz untouched
        self.assertEqual(card1[80:90].strip(), "0")    # ICoG untouched
        self.assertEqual(card1[40:60].strip(), "0")    # Mass untouched
        hit = [w for w in res.warnings if _A2_APPLIED in w]
        self.assertEqual(len(hit), 1, res.warnings)    # ONE line per deck
        for needle in ("1 /RBODY block(s) (/RBODY/15)", "inirby.F:166-168",
                       ":355-363", "cinmas.F:1379", "+16.83", "+33.66",
                       "-> 0.00 %", _A2_REVO_RMS, _A2_REVO_CYCLES,
                       "--no-rigid-shell-rotary-inertia"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit[0])

    def test_2_the_opt_out_moves_exactly_the_J_row(self):
        res, s_off, e_off = _convert(_j_plate_deck(),
                                     rigid_shell_rotary_inertia=False)
        _r, s_on, e_on = _convert(_j_plate_deck())
        self.assertEqual(_rbody_j_rows(s_off, 15)[2], _J_ZERO_ROW)
        self.assertFalse(_has(res.warnings, _A2_APPLIED))
        a, b = s_off.splitlines(), s_on.splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(diff, [(_J_ZERO_ROW, _J_PLATE)])
        self.assertEqual(e_off, e_on)

    def test_3_a_CNRB_over_shell_nodes_keeps_J_0(self):
        """LS-DYNA keeps the nodal inertia in a nodal rigid body (rigid_tip
        CNRB 99: point mass + 1.373e-4 on every axis); 4528 CNRB / spotweld
        bodies on the roster are two-node / collinear (ERROR 274)."""
        extra = ("*SET_NODE_LIST\n" + _row(9) + "\n" + _row(11, 12, 13, 14)
                 + "\n*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(60, 0, 9) + "\n")
        _r, starter, _e = _convert(_j_plate_deck(extra=extra))
        cnrb = _rbody_main_by_title(starter, "CNRB_60")
        self.assertEqual(_rbody_j_rows(starter, cnrb)[2], _J_ZERO_ROW)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_PLATE)

    def test_4_an_ICoG_4_body_keeps_the_decks_tensor(self):
        deck = _j_plate_deck().replace(
            "*PART\nrigid plate\n" + _row(1, 1, 1) + "\n",
            "*PART_INERTIA\nrigid plate\n" + _row(1, 1, 1) + "\n"
            + _row(0.0, 0.0, 0.0, 6.28e-6) + "\n"
            + _row(1.0e-3, 0.0, 0.0, 2.0e-3, 0.0, 3.0e-3) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        res, starter, _e = _convert(deck)
        main = _rbody_main_by_title(starter, "rigid plate")
        card1, _h, j1, _j2 = _rbody_j_rows(starter, main)
        self.assertEqual(card1[80:90].strip(), "4")    # ICoG (cols 81-90)
        self.assertEqual(_floats(j1), [1.0e-3, 2.0e-3, 3.0e-3])
        self.assertFalse(_has(res.warnings, _A2_APPLIED), res.warnings)

    def test_5_a_merged_body_takes_SUM_IN_once_over_the_union(self):
        merged = _j_plate_deck(second_rigid=True,
                               extra="*CONSTRAINED_RIGID_BODIES\n"
                                     + _row(1, 3) + "\n")
        _r, starter, _e = _convert(merged)
        mains = [int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                 if ln.startswith("/RBODY/")]
        self.assertEqual(len(mains), 1, mains)
        # by hand: -(6.28e-6 x 404 / 12 + 1.57e-6 x 104 / 12)
        expect = -(6.28e-6 * 404 / 12 + 1.57e-6 * 104 / 12)
        for v in _floats(_rbody_j_rows(starter, mains[0])[2]):
            self.assertAlmostEqual(v / expect, 1.0, places=9)
        _r2, s2, _e2 = _convert(_j_plate_deck(second_rigid=True))
        got = sorted(_floats(_rbody_j_rows(s2, int(ln.rsplit("/", 1)[1]))[2])[0]
                     for ln in s2.splitlines() if ln.startswith("/RBODY/"))
        want = sorted([-6.28e-6 * 404 / 12, -1.57e-6 * 104 / 12])
        self.assertEqual(len(got), 2, got)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g / w, 1.0, places=6)   # 7-digit E print

    def test_6_a_collinear_body_is_refused_and_its_control_is_written(self):
        res, starter, _e = _convert(_j_plate_deck(
            extra=_floating_rigid((11, 12))))
        self.assertEqual(_rbody_j_rows(starter, 16)[2], _J_ZERO_ROW)
        self.assertTrue(_has(res.warnings, "*MAT_RIGID pid=5: /RBODY/16 "
                             "keeps J = 0 - with J = -SUM(IN)", "ERROR 274",
                             "inirby.F:823-830"), res.warnings)
        res2, s2, _e2 = _convert(_j_plate_deck(
            extra=_floating_rigid((11, 12, 13))))
        for v in _floats(_rbody_j_rows(s2, 16)[2]):
            self.assertAlmostEqual(v / (-3 * _IN_ELASTIC_NODE), 1.0,
                                   places=9)
        self.assertFalse(_has(res2.warnings, "ERROR 274"), res2.warnings)
        self.assertTrue(_has(res2.warnings, _A2_APPLIED,
                             "2 /RBODY block(s) (/RBODY/15, /RBODY/16)"))

    def test_7_the_margin_is_RELATIVE(self):
        """A NEARLY collinear body (ev_min ~1e-10 x ev_max, positive): the
        starter's own '<= 0' would write it, the 1e-6 margin refuses it. The
        probe proves it reaches that window before asserting the refusal."""
        from k2rad.lumping import _sym3_eigen, nodal_masses_from_state
        from k2rad.writer.rbody import RIGID_IN_MARGIN, _body_tensor
        deck = _j_plate_deck(extra=_sliver() + _floating_rigid((31, 32, 33)))
        state = _dispatch(deck)
        mass, _in = nodal_masses_from_state(state)
        ev = sorted(_sym3_eigen(_body_tensor(state, {31, 32, 33}, mass))[0])
        self.assertGreater(ev[0], 0.0)
        self.assertLess(ev[0], RIGID_IN_MARGIN * ev[-1])
        res, starter, _e = _convert(deck)
        main = _rbody_main_by_title(starter, "floating rigid")
        self.assertEqual(_rbody_j_rows(starter, main)[2], _J_ZERO_ROW)
        self.assertTrue(_has(res.warnings, f"/RBODY/{main} keeps J = 0",
                             "would not exceed 1e-06 x the largest"),
                        res.warnings)
        # the plate beside it is still corrected (the refusal is per body)
        plate = _rbody_main_by_title(starter, "rigid plate")
        self.assertEqual(_rbody_j_rows(starter, plate)[2], _J_PLATE)

    def test_8_each_skip_reason_is_named_and_keeps_J_0(self):
        for kw, needle in ((dict(icomp=True), "ICOMP 1"),
                           (dict(thickness=True),
                            "*ELEMENT_SHELL_THICKNESS")):
            with self.subTest(needle=needle):
                res, starter, _e = _convert(_j_plate_deck(**kw))
                self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)
                self.assertTrue(_has(res.warnings, "*MAT_RIGID pid=1: "
                                     "/RBODY/15 keeps J = 0 -", needle),
                                res.warnings)
                self.assertFalse(_has(res.warnings, _A2_APPLIED))

    def test_9_Ishell_below_11_is_skipped_by_name(self):
        """k2rad only writes Ishell 12 / 24 today (reach 0), so the branch is
        probed by making the shared mapper answer 1 (round 6's probe)."""
        from k2rad.writer import common
        saved = common._elform_to_ishell
        common._elform_to_ishell = lambda *a, **k: 1
        try:
            res, starter, _e = _convert(_j_plate_deck())
        finally:
            common._elform_to_ishell = saved
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)
        self.assertTrue(_has(res.warnings, "/RBODY/15 keeps J = 0 -",
                             "Ishell 1 < 11", "FAC 9"), res.warnings)

    def test_10_a_part_body_shadowed_by_a_CNRB_PID_is_still_corrected(self):
        """doorbeam's shape: a CNRB whose PID equals the rigid part's id
        replaces the part's rbody_info record in the merge, so a post-pass
        keyed on the merged dict would never see the part's body."""
        extra = ("*SET_NODE_LIST\n" + _row(9) + "\n" + _row(11, 12, 13, 14)
                 + "\n*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(1, 0, 9) + "\n")
        res, starter, _e = _convert(_j_plate_deck(extra=extra))
        self.assertTrue(_has(res.warnings, "PID 1 collides with the id of "
                             "a *MAT_RIGID part"), res.warnings)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_PLATE)

    def test_11_a_DEFORMABLE_TO_RIGID_plate_is_corrected_too(self):
        """The producer's body set is *MAT_RIGID parts AND
        *DEFORMABLE_TO_RIGID parts (the pendulum pair's body is the
        latter): a predicate on state.mat_rigid alone would miss it."""
        deck = _j_plate_deck().replace(
            "*PART\nrigid plate\n" + _row(1, 1, 1) + "\n",
            "*PART\nrigid plate\n" + _row(1, 1, 3) + "\n"
            "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
            "*DEFORMABLE_TO_RIGID\n" + _row(1, 0) + "\n")
        res, starter, _e = _convert(deck)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_PLATE)
        self.assertTrue(_has(res.warnings, _A2_APPLIED, "/RBODY/15"))

    def test_12_the_flag_pass_never_subtracts_twice(self):
        """Default A2 + --mass-weighted-inivel: the body carries -SUM(IN)
        ONCE (not -4.228533333e-4) and the flag's J sentence is silent."""
        res, starter, _e = _convert(_j_plate_deck(covered=(3, 4)),
                                    mass_weighted_inivel=True)
        self.assertIn("/INIVEL/ROT/", starter)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_PLATE)
        self.assertFalse(_has(res.warnings, "--mass-weighted-inivel also "
                              "wrote J"), res.warnings)
        self.assertTrue(_has(res.warnings, "MOMENTUM AVERAGE",
                             "k2rad already wrote J = -SUM(IN) into this "
                             "body's /RBODY by default"), res.warnings)

    def test_13_the_flag_alone_keeps_its_round_6_behaviour(self):
        res, starter, _e = _convert(_j_plate_deck(covered=(3, 4)),
                                    mass_weighted_inivel=True,
                                    rigid_shell_rotary_inertia=False)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_PLATE)
        self.assertTrue(_has(res.warnings, "--mass-weighted-inivel also "
                             "wrote J = -0.000211427", "/RBODY/15"),
                        res.warnings)
        self.assertTrue(_has(res.warnings, "so the flag also writes "
                             "J = -SUM(IN) into this body's /RBODY"))
        self.assertFalse(_has(res.warnings, _A2_APPLIED))

    def _direct(self, rec):
        from k2rad.writer import loads
        from k2rad.writer.rbody import _inertia_lines
        state = _dispatch(_j_plate_deck())
        state.options.mass_weighted_inivel = True
        state.nodes[15] = state.nodes[1].__class__(0.0, 0.0, 0.0)
        state.mass_weighted_rot_mains[15] = (0.0, 0.0, -25.0)
        lines = (["/RBODY/15", "RBODY_1", "#hdr", "card1"]
                 + _inertia_lines(rec["j"]))
        loads._apply_mass_weighted_rbody_inertia(state, lines, {1: rec})
        return state, lines

    def test_14_flag_pass_guard_1_never_writes_J_on_a_CNRB(self):
        base = {"ind_node": 15, "nodes": [1, 2, 3, 4], "icog": 0,
                "j": (0.0,) * 6}
        state, lines = self._direct(dict(base, kind="cnrb"))
        self.assertEqual(lines[5], _J_ZERO_ROW)
        self.assertTrue(_has(state.warnings, "/RBODY/15 keeps its J",
                             "*CONSTRAINED_NODAL_RIGID_BODY", "-25.08 %"),
                        state.warnings)
        # control: the same record as a PART body is written
        state2, lines2 = self._direct(dict(base, kind="part"))
        self.assertEqual(lines2[5], _J_PLATE)

    def test_15_flag_pass_guard_2_skips_a_corrected_or_refused_body(self):
        base = {"ind_node": 15, "nodes": [1, 2, 3, 4], "icog": 0,
                "kind": "part"}
        for status, j in (("applied", (-2.114266667e-4,) * 3 + (0.0,) * 3),
                          ("refused", (0.0,) * 6)):
            with self.subTest(status=status):
                from k2rad.writer.rbody import _inertia_lines
                state, lines = self._direct(dict(base, j=j, j_in=status))
                self.assertEqual(lines[5], _inertia_lines(j)[1])
                self.assertFalse(_has(state.warnings, "also wrote J"))

    def test_16_a_body_without_shell_IN_writes_nothing(self):
        """icfd's main_fsi.k: rigid shells with t1 = 0.0 lump IN = 0 - no
        J cell is written (and no '-0')."""
        deck = _j_plate_deck().replace(
            _row(2.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0),
            _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0))
        res, starter, _e = _convert(deck)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)
        self.assertFalse(_has(res.warnings, _A2_APPLIED), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# A3 — the MAT_100 weld: the yielding TYPE13 shear and EFAIL -> displacement
# ═════════════════════════════════════════════════════════════════════════════

def _weld_deck(efail=10.0, resultants=(1.0e4, 5.0e4, 5.0e4, 99999.0, 99999.0,
                                      99999.0), sigy=5000.0, eh=1000.0) -> str:
    """plates.mat100's weld on two 1-element plates: ONE 2-node ELFORM-9
    beam (part 10, nodes 1 -> 5, L = 2.0), *SECTION_BEAM TS1 = TS2 = 3.0
    (A = 7.0685835), *MAT_SPOTWELD RO 7.85e-9 E 210000 PR 0.3 SIGY / EH, DT
    1e-9, card 2 = EFAIL + *resultants* (NRR NRS NRT MRR MSS MTT)."""
    nodes = "".join(f"{n:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n" for n, x, y, z in
                    ((1, 0, 0, 0), (2, 5, 0, 0), (3, 5, 5, 0), (4, 0, 5, 0),
                     (5, 0, 0, 2), (6, 5, 0, 2), (7, 5, 5, 2), (8, 0, 5, 2)))
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n" + nodes
            + "*PART\nlower\n" + _row(1, 1, 1) + "\n"
            "*PART\nupper\n" + _row(2, 1, 1) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0) + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            "*ELEMENT_SHELL\n"
            + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)) + "\n"
            + "".join(f"{v:>8}" for v in (2, 2, 5, 6, 7, 8)) + "\n"
            "*PART\nweld\n" + _row(10, 10, 10) + "\n"
            "*SECTION_BEAM\n" + _row(10, 9, 1.0, 4, 1) + "\n"
            + _row(3.0, 3.0, 0.0, 0.0) + "\n"
            "*MAT_SPOTWELD\n"
            + _row(10, 7.85e-9, 210000.0, 0.3, sigy, eh, 1.0e-9, 0.0) + "\n"
            + _row(efail, *resultants, 0.0) + "\n"
            "*ELEMENT_BEAM\n" + "".join(f"{v:>8}" for v in (10, 10, 1, 5))
            + "\n*END\n")


#: hand values of the plates.mat100 weld (part-A spec A3.3)
_W_A = math.pi * 9.0 / 4.0
_W_L = 2.0
_W_G = 210000.0 / 2.6
_W_K23 = _W_G * _W_A / _W_L                       # 285462.0247733033
_W_K1 = 210000.0 * _W_A / _W_L
_W_FYS = 5000.0 / math.sqrt(3.0) * _W_A           # 20405.24284763495
_W_DYS = _W_FYS / _W_K23 * (1.0 + 1e-8)           # 0.07148146261
_W_KTS = _W_G * 1000.0 / (3.0 * _W_G + 1000.0) * _W_A / _W_L


def _type13_cards(starter: str):
    """(card 1, [(K card, delta card) for the 6 DOFs]) of the ONE MAT_100
    /PROP/TYPE13 block."""
    lines = starter.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("/PROP/TYPE13/")
             and "(MAT_100 spotweld)" in lines[i + 1]]
    assert len(heads) == 1, heads
    i = heads[0]
    card1 = lines[i + 3]
    dofs = [(lines[i + 5 + 6 * k], lines[i + 7 + 6 * k]) for k in range(6)]
    return card1, dofs


def _funct_points(starter: str, title: str):
    """(id, [(x, y), ...]) of the /FUNCT titled *title*."""
    lines = starter.splitlines()
    hit = [i for i, ln in enumerate(lines)
           if ln.startswith("/FUNCT/") and lines[i + 1] == title]
    assert len(hit) == 1, (title, hit)
    i = hit[0]
    pts = []
    for ln in lines[i + 3:]:
        if ln.startswith(("#", "/")):
            break
        pts.append((float(ln[0:20]), float(ln[20:40])))
    return int(lines[i].rsplit("/", 1)[1]), pts


def _close(a: float, b: float, rel: float = 2e-9) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


_W_SHEAR_ON = "and a bilinear SHEAR /FUNCT/"
_W_EFAIL_ON = "-> /PROP/TYPE13 Ifail 1 / Ifail2 0 displacement failure"
_W_OLD_SHEAR = "Shear/bending DOFs stay elastic up to the failure surface"


class SpotweldShearYieldAndEfail(unittest.TestCase):
    """A3 — (i) every 2-node *MAT_SPOTWELD beam's /PROP/TYPE13 gets a
    bilinear SHEAR curve on Ty / Tz (yield (SIGY/sqrt3) A, the von Mises
    shear yield; hardening G EH / (3G + EH) A / L; H2 = H3 = 1); (ii) EFAIL
    with no resultant cells -> Ifail 1 / Ifail2 0 displacement failure."""

    def test_1_the_mixed_plates_mat100_weld(self):
        res, starter, _e = _convert(_weld_deck())
        card1, dofs = _type13_cards(starter)
        fid, pts = _funct_points(starter, "spotweld_shear_bilinear_pid10")
        for k in (1, 2):                                   # Ty, Tz
            with self.subTest(dof=k + 1):
                self.assertEqual(int(dofs[k][1][0:10]), fid)
                self.assertEqual(dofs[k][1][10:20].strip(), "1")
        dend = 101.0 * _W_DYS
        fend = _W_FYS + _W_KTS * (dend - _W_DYS)
        want = [(-dend, -fend), (-_W_DYS, -_W_FYS), (0.0, 0.0),
                (_W_DYS, _W_FYS), (dend, fend)]
        self.assertEqual(len(pts), 5)
        for (x, y), (wx, wy) in zip(pts, want):
            self.assertTrue(_close(x, wx) and _close(y, wy), (x, y, wx, wy))
        # rkini3.F:70-99: WARNING 506 when the printed K is below the
        # steepest segment of the printed function - check the PRINTED card
        k2 = float(dofs[1][0][0:20])
        slopes = [(y2 - y1) / (x2 - x1)
                  for (x1, y1), (x2, y2) in zip(pts, pts[1:])]
        self.assertLessEqual(max(slopes), k2)
        self.assertEqual(card1[70:80].strip(), "1")        # Ifail 1
        self.assertEqual(card1[90:100].strip(), "2")       # Ifail2 2 (force)
        self.assertEqual(dofs[1][1][80:100].strip(), "50000")
        self.assertTrue(_has(res.warnings, "EFAIL=10 is NOT converted",
                             "Ifail2 = 2 force criteria"), res.warnings)
        self.assertTrue(_has(res.warnings, _W_SHEAR_ON, "20405.2"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, _W_OLD_SHEAR))
        self.assertFalse(_has(res.warnings, _W_EFAIL_ON))

    def test_2_an_EFAIL_only_weld_fails_on_displacement(self):
        res, starter, _e = _convert(_weld_deck(efail=0.3,
                                               resultants=(0.0,) * 6))
        card1, dofs = _type13_cards(starter)
        self.assertEqual(card1[70:80].strip(), "1")        # Ifail 1
        self.assertEqual(card1[90:100].strip(), "0")       # Ifail2 0 (disp.)
        self.assertEqual(dofs[0][1][60:80].strip(), "0")   # tension only
        d1 = float(dofs[0][1][80:100])
        self.assertTrue(_close(d1, 5000.0 * 2.0 / 210000.0 + 0.3 * 2.0),
                        d1)                                # 0.6476190476
        _fid, pts = _funct_points(starter, "spotweld_shear_bilinear_pid10")
        dys_printed = pts[3][0]
        d2 = dys_printed + math.sqrt(3.0) * 0.3 * 2.0      # 1.110711947
        for k in (1, 2):
            with self.subTest(dof=k + 1):
                self.assertTrue(_close(float(dofs[k][1][60:80]), -d2, 1e-9))
                self.assertTrue(_close(float(dofs[k][1][80:100]), d2, 1e-9))
        for k in (3, 4, 5):
            with self.subTest(dof=k + 1):
                self.assertEqual(dofs[k][1][60:80].strip(), "0")
                self.assertEqual(dofs[k][1][80:100].strip(), "0")
        self.assertTrue(_has(res.warnings, "EFAIL=0.3", _W_EFAIL_ON,
                             "sqrt(eps^2 + gamma^2/3)"), res.warnings)
        self.assertFalse(_has(res.warnings, "plastic-strain failure"),
                         res.warnings)

    def test_3_a_1e20_class_EFAIL_is_no_failure_and_writes_nothing(self):
        """LS-DYNA's 'never' idiom (the Yaris door sag states 2e20): the
        threshold is the dropped-field filter's 1e19 - ONE number."""
        deck = _weld_deck(efail=2.0e20, resultants=(0.0,) * 6)
        res, starter, _e = _convert(deck)
        card1, dofs = _type13_cards(starter)
        self.assertEqual(card1[70:80].strip(), "0")
        self.assertEqual(card1[90:100].strip(), "0")
        for k in range(6):
            self.assertEqual(dofs[k][1][60:80].strip(), "0")
            self.assertEqual(dofs[k][1][80:100].strip(), "0")
        self.assertFalse(_has(res.warnings, _W_EFAIL_ON))
        self.assertFalse(_has(res.warnings, "EFAIL"), res.warnings)
        _r2, s_off, _e2 = _convert(deck, spotweld_efail_displacement=False)
        self.assertEqual(starter, s_off)

    def test_4_SIGY_0_writes_no_curve_and_the_strain_alone(self):
        res, starter, _e = _convert(_weld_deck(efail=0.3,
                                               resultants=(0.0,) * 6,
                                               sigy=0.0))
        self.assertNotIn("spotweld_shear_bilinear", starter)
        self.assertNotIn("spotweld_axial_bilinear", starter)
        _card1, dofs = _type13_cards(starter)
        for k in (1, 2):
            self.assertEqual(dofs[k][1][0:20].split(), ["0", "0"])
            self.assertTrue(_close(float(dofs[k][1][80:100]),
                                   math.sqrt(3.0) * 0.3 * 2.0, 1e-9))
        self.assertTrue(_close(float(dofs[0][1][80:100]), 0.6, 1e-9))

    def test_5_EH_0_falls_back_like_the_axial_curve(self):
        _r, starter, _e = _convert(_weld_deck(eh=0.0))
        _fid, pts = _funct_points(starter, "spotweld_shear_bilinear_pid10")
        want = _W_FYS + 1e-4 * _W_K23 * (101.0 - 1.0) * _W_DYS
        self.assertTrue(_close(pts[4][1], want, 1e-8), (pts[4], want))

    def test_6_the_shear_opt_out_restores_the_elastic_shear(self):
        from k2rad.writer.loads import _emit_spring_dof
        res, starter, _e = _convert(_weld_deck(), spotweld_shear_yield=False)
        self.assertNotIn("spotweld_shear_bilinear", starter)
        _card1, dofs = _type13_cards(starter)
        for k, cell in ((1, 5.0e4), (2, 5.0e4)):
            want = _emit_spring_dof(k + 1, (_W_K23, 0, 0, -cell, cell))
            self.assertEqual(list(dofs[k]), [want[1], want[3]])
        self.assertTrue(_has(res.warnings, _W_OLD_SHEAR), res.warnings)
        self.assertFalse(_has(res.warnings, _W_SHEAR_ON))

    def test_7_the_efail_opt_out_keeps_EFAIL_dropped(self):
        res, starter, _e = _convert(_weld_deck(efail=0.3,
                                               resultants=(0.0,) * 6),
                                    spotweld_efail_displacement=False)
        card1, dofs = _type13_cards(starter)
        self.assertEqual(card1[70:80].strip(), "0")
        self.assertEqual(card1[90:100].strip(), "0")
        self.assertEqual(dofs[0][1][80:100].strip(), "0")
        self.assertTrue(_has(res.warnings, "DT, EFAIL have no /PROP/TYPE13 "
                             "slot", "plastic-strain failure"), res.warnings)
        self.assertFalse(_has(res.warnings, _W_EFAIL_ON))

    def test_8_piece_ii_without_piece_i_names_the_unreached_criterion(self):
        """--no-spotweld-shear-yield + EFAIL: the cells are written with the
        same delta_y,s but the shear stays elastic, which G4 measured never
        reaches them on spotweld.k - the sentence says so on that arm."""
        res, starter, _e = _convert(_weld_deck(efail=0.3,
                                               resultants=(0.0,) * 6),
                                    spotweld_shear_yield=False)
        card1, dofs = _type13_cards(starter)
        self.assertEqual(card1[90:100].strip(), "0")
        d2 = _W_DYS + math.sqrt(3.0) * 0.3 * 2.0
        self.assertTrue(_close(float(dofs[1][1][80:100]), d2, 1e-8))
        self.assertTrue(_has(res.warnings, _W_EFAIL_ON,
                             "--no-spotweld-shear-yield"), res.warnings)

    def test_9_the_shear_curve_draws_a_FUNCT_TABLE_free_id(self):
        """next_curve_id, not the raw counter: a user *DEFINE_TABLE at the
        id the counter would hand out next must not collide (ERROR 79)."""
        from k2rad.writer import loads
        state = _dispatch(_weld_deck())
        state._auto_id = 91000
        state.define_tables[91001] = object()      # the shear curve's id
        lines = loads._make_spotweld_beam_connectors(state)
        ids = [int(ln.rsplit("/", 1)[1]) for ln in lines
               if ln.startswith("/FUNCT/")]
        self.assertEqual(len(ids), 2, ids)
        self.assertNotIn(91001, ids)


# ═════════════════════════════════════════════════════════════════════════════
# A4 — the implicit LAW1 thick shell -> /PROP/SOLID Isolid 14; the lumper
# ═════════════════════════════════════════════════════════════════════════════

_TS_NODES = "*NODE\n" + "".join(
    f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
        (5, 0.0, 0.0, 2.0), (6, 10.0, 0.0, 2.0),
        (7, 10.0, 10.0, 2.0), (8, 0.0, 10.0, 2.0),
        (9, 20.0, 0.0, 0.0), (10, 20.0, 10.0, 0.0),
        (11, 20.0, 0.0, 2.0), (12, 20.0, 10.0, 2.0)))
_TS_TWO = ("*ELEMENT_TSHELL\n"
           + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4, 5, 6, 7, 8)) + "\n"
           + "".join(f"{v:>8}" for v in (2, 1, 2, 9, 10, 3, 6, 11, 12, 7))
           + "\n")
_TS_ELASTIC = "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
_TS_IMPLICIT = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
                "*CONTROL_TERMINATION\n" + _row(1.0) + "\n")
_TS_EXPLICIT = "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"


def _ts_deck(control=_TS_IMPLICIT, elform=2, nip=5, icomp="", shrf=0.833,
             mat=_TS_ELASTIC, part="*PART\ntshell part\n" + _row(1, 1, 1)
             + "\n", elem=_TS_TWO, extra="") -> str:
    """The A4 coupon: two 10 x 10 x 2 thick shells (part 1, nodes 1-12) on
    *SECTION_TSHELL 1 (ELFORM *elform*, NIP *nip*, SHRF *shrf*)."""
    sec = ("*SECTION_TSHELL\n" + _row(1, elform, shrf, nip, "", "", icomp, "")
           + "\n" + ("".join(_row(0.0, 0.0) for _ in range(1)) + "\n"
                     if icomp == 1 else ""))
    return ("*KEYWORD\n" + control + _TS_NODES + elem + part + sec + mat
            + extra + "*END\n")


def _block_lines(text: str, head: str):
    """The lines of the card block whose header line starts with *head* (up
    to the next ``/`` card or ``#---`` separator)."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(head):
            out = [ln]
            for nxt in lines[i + 1:]:
                if nxt.startswith("/") or nxt.startswith("#---"):
                    break
                out.append(nxt)
            return out
    raise AssertionError(f"{head!r} not in the emitted deck")


def _brick_rows(text: str):
    return [ln for ln in _block_lines(text, "/BRICK/1")[1:]
            if not ln.startswith("#")]


_TS_ROUTED = "IMPLICIT deck, *MAT_ELASTIC on part(s) [1] — written as /PROP/SOLID"
_TS_KEPT = "IMPLICIT deck,"
_TS_791 = "force-RESETS the through-thickness integration"   # the 791 note


class ImplicitThickShellSolidRoute(unittest.TestCase):
    """A4 (i) — the implicit thick-shell tangent integrates the thickness
    with ONE mid-plane point (s8cke3.F:354-364; Isolid 15 has no 8-node
    tangent): on an IMPLICIT deck a *MAT_ELASTIC *SECTION_TSHELL becomes
    /PROP/SOLID Isolid 14 Inpts 222 on the SAME /BRICK rows (default ON,
    --no-implicit-tshell-solid). Explicit decks keep TYPE20."""

    def _card(self, starter):
        blk = _block_lines(starter, "/PROP/SOLID/1")
        self.assertEqual(blk[1], "PROP_1")
        return blk

    def test_1_the_implicit_LAW1_section_is_routed(self):
        res, starter, _e = _convert(_ts_deck())
        self.assertNotIn("/PROP/TYPE20", starter)
        blk = self._card(starter)
        c1 = blk[3]
        self.assertEqual(c1[0:10].strip(), "14")       # Isolid
        self.assertEqual(c1[10:20].strip(), "0")       # Ismstr
        self.assertEqual(c1[30:40].strip(), "0")       # Icpre
        self.assertEqual(c1[50:60].strip(), "222")     # Inpts
        self.assertEqual(c1[70:80].strip(), "0")       # Iframe
        self.assertEqual(blk[5][40:60].strip(), "0")   # h
        _r2, s_exp, _e2 = _convert(_ts_deck(control=_TS_EXPLICIT))
        self.assertEqual(_brick_rows(starter), _brick_rows(s_exp))
        self.assertTrue(_has(res.warnings, _TS_ROUTED, "s8cke3.F:354-364",
                             "28 cycles", "100 624", "NIP=5",
                             "--no-implicit-tshell-solid"), res.warnings)
        self.assertFalse(_has(res.warnings, _TS_791), res.warnings)
        self.assertTrue(_has(res.warnings, "*SECTION_TSHELL 1 → /PROP/SOLID. "
                             "Dropped: SHRF=0.833"), res.warnings)

    def test_2_an_explicit_deck_keeps_TYPE20(self):
        res, starter, _e = _convert(_ts_deck(control=_TS_EXPLICIT))
        self.assertIn("/PROP/TYPE20/1", starter)
        self.assertNotIn("/PROP/SOLID/1", starter)
        self.assertTrue(_has(res.warnings, _TS_791))
        self.assertFalse(_has(res.warnings, _TS_KEPT))
        _r2, s_off, _e2 = _convert(_ts_deck(control=_TS_EXPLICIT),
                                   implicit_tshell_solid=False)
        self.assertEqual(starter, s_off)

    def test_3_ELFORM_1_is_routed_to_Isolid_14_too(self):
        _r, starter, _e = _convert(_ts_deck(elform=1))
        self.assertEqual(self._card(starter)[3][0:10].strip(), "14")
        _r2, s_off, _e2 = _convert(_ts_deck(elform=1),
                                   implicit_tshell_solid=False)
        self.assertEqual(_block_lines(s_off, "/PROP/TYPE20/1")[3][0:10]
                         .strip(), "15")

    def test_4_the_modal_path_is_routed(self):
        modal = ("*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(5) + "\n"
                 + _TS_EXPLICIT)
        res, starter, _e = _convert(_ts_deck(control=modal))
        self.assertIn("/PROP/SOLID/1", starter)
        self.assertTrue(_has(res.warnings, _TS_ROUTED))

    def test_5_the_opt_out_keeps_TYPE20_and_its_791_note(self):
        res, starter, _e = _convert(_ts_deck(), implicit_tshell_solid=False)
        self.assertNotIn("/PROP/SOLID/1", starter)
        c1 = _block_lines(starter, "/PROP/TYPE20/1")[3]
        self.assertEqual(c1[0:10].strip(), "14")
        self.assertEqual(c1[50:60].strip(), "252")     # 2 j 2, j = NIP 5
        self.assertTrue(_has(res.warnings, _TS_791))
        self.assertFalse(_has(res.warnings, _TS_KEPT))
        self.assertTrue(_has(res.warnings, "→ /PROP/TYPE20. Dropped: SHRF"))

    def test_6_TYPE22_and_TYPE21_keep_their_card_and_are_named(self):
        res, starter, _e = _convert(_ts_deck(icomp=1, nip=2))
        self.assertIn("/PROP/TYPE22/", starter)
        self.assertNotIn("/PROP/SOLID/1", starter)
        self.assertTrue(_has(res.warnings, _TS_KEPT, "kept on /PROP/TYPE22",
                             "s8cke3.F:354-364"), res.warnings)
        ortho = ("*MAT_ORTHOTROPIC_ELASTIC\n"
                 + _row(1, 7.85e-9, 200000.0, 10000.0, 10000.0, 0.3, 0.3, 0.3)
                 + "\n" + _row(5000.0, 5000.0, 5000.0, 2.0, 0.0, 0.0) + "\n"
                 + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0) + "\n"
                 + _row(0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        res2, s2, _e2 = _convert(_ts_deck(mat=ortho))
        self.assertIn("/PROP/TYPE21/1", s2)
        self.assertTrue(_has(res2.warnings, _TS_KEPT, "kept on /PROP/TYPE21"),
                        res2.warnings)

    def test_7_a_plastic_law_keeps_TYPE20_and_is_named(self):
        plp = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
               + _row(1, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
               + _row(0.0, 0.0, 0.0) + "\n" + _row() + "\n" + _row() + "\n")
        res, starter, _e = _convert(_ts_deck(mat=plp))
        self.assertIn("/PROP/TYPE20/1", starter)
        self.assertNotIn("/PROP/SOLID/1", starter)
        self.assertTrue(_has(res.warnings, _TS_KEPT, "kept on /PROP/TYPE20",
                             "*MAT_ELASTIC only"), res.warnings)

    def test_8_the_solid_hourglass_remap_never_touches_the_card(self):
        hg = ("*CONTROL_HOURGLASS\n" + _row(6, 0.1) + "\n"
              "*HOURGLASS\n" + _row(7, 6, 0.1) + "\n")
        part = "*PART\ntshell part\n" + _row(1, 1, 1, 0, 7) + "\n"
        _r, starter, _e = _convert(_ts_deck(part=part, extra=hg))
        blk = self._card(starter)
        self.assertEqual(blk[5][40:60].strip(), "0")   # h stays 0
        solids = [ln for ln in starter.splitlines()
                  if ln.startswith("/PROP/SOLID/")]
        self.assertEqual(solids, ["/PROP/SOLID/1"])
        part_card = _block_lines(starter, "/PART/1")
        self.assertEqual(int(part_card[2][0:10]), 1)   # prop_ID = the SECID

    def test_9_mixed_laws_on_one_section_are_not_routed(self):
        two = (_TS_TWO.replace("       2       1       2       9",
                               "       2       2       2       9"))
        parts = ("*PART\ntshell part\n" + _row(1, 1, 1) + "\n"
                 "*PART\nplastic part\n" + _row(2, 1, 2) + "\n")
        plp = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
               + _row(2, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
               + _row(0.0, 0.0, 0.0) + "\n" + _row() + "\n" + _row() + "\n")
        res, starter, _e = _convert(_ts_deck(elem=two, part=parts,
                                             mat=_TS_ELASTIC + plp))
        self.assertIn("/PROP/TYPE20/1", starter)
        self.assertNotIn("/PROP/SOLID/1", starter)
        self.assertTrue(_has(res.warnings, _TS_KEPT, "/MAT/LAW1",
                             "kept on /PROP/TYPE20"), res.warnings)

    def test_10_the_routed_elements_stay_thick_shells_for_every_walk(self):
        """The route changes the PROPERTY only: the elements stay in
        tshell_elems, so a thick-shell walk still reaches them. Pinned on
        the history walk: a *DATABASE_HISTORY_TSHELL_SET over a *SET_PART
        holding the routed part expands through tshell_elems
        (writer/output._TH_SET_SOURCES) and must still list both elements in
        /TH/BRIC. Moving the routed elements into solid_elems empties it."""
        extra = ("*SET_PART_LIST\n" + _row(9) + "\n" + _row(1) + "\n"
                 "*DATABASE_HISTORY_TSHELL_SET\n" + _row(9) + "\n")
        _r, starter, _e = _convert(_ts_deck(extra=extra))
        self.assertIn("/PROP/SOLID/1", starter)
        th = _block_lines(starter, "/TH/BRIC/")
        ids = [int(ln) for ln in th if ln.strip().isdigit()]
        self.assertEqual(ids, [1, 2], th)


class LumperCountsThickShells(unittest.TestCase):
    """A4 (ii) — ``lumping.nodal_masses_from_state`` lumps thick shells like
    the hexa they are emitted as (tools/modal_solve.py gave ex_13 a total
    mass of 0 and ARPACK stopped with error -9)."""

    def test_an_8_node_thick_shell_gets_rho_V(self):
        from k2rad.lumping import nodal_masses_from_state
        one = ("*ELEMENT_TSHELL\n" + "".join(f"{v:>8}" for v in
               (1, 1, 1, 2, 3, 4, 5, 6, 7, 8)) + "\n")
        state = _dispatch(_ts_deck(elem=one))
        mass, inertia = nodal_masses_from_state(state)
        self.assertAlmostEqual(sum(mass.values()) / 1.57e-6, 1.0, places=12)
        for n in range(1, 9):
            self.assertAlmostEqual(mass[n] / 1.9625e-7, 1.0, places=12)
        self.assertEqual(inertia, {})                  # IN stays shell-only

    def test_a_degenerate_6_node_wedge_gets_half(self):
        from k2rad.lumping import nodal_masses_from_state
        wedge = ("*ELEMENT_TSHELL\n" + "".join(f"{v:>8}" for v in
                 (1, 1, 1, 2, 3, 3, 5, 6, 7, 7)) + "\n")
        state = _dispatch(_ts_deck(elem=wedge))
        mass, _in = nodal_masses_from_state(state)
        self.assertAlmostEqual(sum(mass.values()) / 7.85e-7, 1.0, places=12)

    def test_a_FINMASS_on_a_thick_shell_part_reaches_its_nodes(self):
        from k2rad.lumping import nodal_masses_from_state
        one = ("*ELEMENT_TSHELL\n" + "".join(f"{v:>8}" for v in
               (1, 1, 1, 2, 3, 4, 5, 6, 7, 8)) + "\n")
        fin = "*ELEMENT_MASS_PART\n" + _row(1, 0.0, 2.0e-6) + "\n"
        state = _dispatch(_ts_deck(elem=one, extra=fin))
        mass, _in = nodal_masses_from_state(state)
        self.assertAlmostEqual(sum(mass.values()) / 2.0e-6, 1.0, places=12)


# ═════════════════════════════════════════════════════════════════════════════
# A5 — the implicit / spring texts (0 .rad bytes)
# ═════════════════════════════════════════════════════════════════════════════

def _shell_plate(control: str, extra: str = "") -> str:
    """A 2 x 1 elastic shell plate (part 1, nodes 1-6) under *control*."""
    nodes = "*NODE\n" + "".join(
        f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n" for n, x, y in
        ((1, 0, 0), (2, 10, 0), (3, 20, 0), (4, 0, 10), (5, 10, 10),
         (6, 20, 10)))
    return ("*KEYWORD\n" + control + nodes
            + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0) + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            "*ELEMENT_SHELL\n"
            + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 5, 4)) + "\n"
            + "".join(f"{v:>8}" for v in (2, 1, 2, 3, 6, 5)) + "\n"
            + extra + "*END\n")


_IMPL1 = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
          "*CONTROL_TERMINATION\n" + _row(0.01) + "\n")
_VDC_RE = re.compile(r"^CONTACT \d+: vdc=0 -> VisS=0")


class VdcRemedyNotAboutTheStub(unittest.TestCase):
    """A5 (i) — the 'set vdc on *CONTACT Card2' remedy is not printed about
    k2rad's own injected implicit stub (the deck states no *CONTACT at all);
    gated on the stub title exactly as _maybe_derived_gapmin is."""

    def test_1_a_contact_free_implicit_deck_gets_no_remedy(self):
        res, starter, _e = _convert(_shell_plate(_IMPL1))
        self.assertTrue(_has(res.warnings, "Injected an inert all-parts "
                             "self-contact"), res.warnings)
        self.assertEqual([w for w in res.warnings if _VDC_RE.match(w)], [])
        self.assertIn("auto_implicit_stabilization_self_contact", starter)

    def test_2_a_stated_vdc_0_contact_still_gets_it(self):
        extra = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID\n" + _row(77) + "\n"
                 + _row(1, 0, 3, 0) + "\n" + _row(0.1, 0.0, 0.0, 0.0, 0.0)
                 + "\n" + _row() + "\n")
        res, _s, _e = _convert(_shell_plate(_IMPL1, extra))
        hits = [w for w in res.warnings if _VDC_RE.match(w)]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertTrue(hits[0].startswith("CONTACT 77: vdc=0 -> VisS=0"))

    def test_3_a_TYPE25_only_deck_gets_the_stub_and_no_stub_sentence(self):
        """doorbeam's shape: its one contact takes the TYPE25 route and the
        stub is injected beside it (the stub guard does not read
        contacts_type25 - ROADMAP); no vdc sentence names the stub."""
        extra = ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2, 3) + "\n"
                 "*CONTACT_NODES_TO_SURFACE_ID\n" + _row(78) + "\n"
                 + _row(5, 1, 4, 3) + "\n" + _row(0.1) + "\n" + _row() + "\n")
        res, starter, _e = _convert(_shell_plate(_IMPL1, extra))
        stub_ids = [int(starter.splitlines()[i - 1].rsplit("/", 1)[1])
                    for i, ln in enumerate(starter.splitlines())
                    if ln == "auto_implicit_stabilization_self_contact"]
        self.assertEqual(len(stub_ids), 1, starter)     # the stub IS there
        self.assertIn("/INTER/TYPE25/78", starter)
        self.assertFalse(_has(res.warnings, f"CONTACT {stub_ids[0]}: vdc=0"),
                         res.warnings)


def _efg_deck(title: bool = False) -> str:
    """efg/metal-cutting's card shape: *SECTION_SOLID_EFG SECID 3 ELFORM 42
    (+ its two EFG cards) under part 3 with three tetrahedra written
    n4 = ... = n8, plus *CONTROL_ADAPTIVE and *CONTROL_REMESHING_EFG."""
    nodes = "*NODE\n" + "".join(
        f"{n:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n" for n, x, y, z in
        ((1, 0, 0, 0), (2, 1, 0, 0), (3, 0, 1, 0), (4, 0, 0, 1),
         (5, 1, 1, 0), (6, 1, 0, 1)))
    tets = "".join(
        "".join(f"{v:>8}" for v in (eid, 3, a, b, c, d, d, d, d, d)) + "\n"
        for eid, (a, b, c, d) in ((1, (1, 2, 3, 4)), (2, (2, 5, 3, 4)),
                                  (3, (2, 6, 5, 4))))
    sec = ("*SECTION_SOLID_EFG" + ("_TITLE\nworkpiece efg\n" if title else
                                   "\n")
           + _row(3, 42, 0) + "\n"
           + _row(1.25, 1.25, 1.25, 0, 0, 3, 2, 0.01) + "\n"
           + _row(1, 1.0e20, 0, 0.0, 0, 1, 0.01, 0.01) + "\n")
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(0.001) + "\n"
            "*CONTROL_ADAPTIVE\n" + _row(0.001, 0, 7) + "\n" + _row(1) + "\n"
            "*CONTROL_REMESHING_EFG\n" + _row(0.15, 2.25, 1.0) + "\n"
            + _row(1) + "\n" + nodes
            + "*PART\nWorkpiece\n" + _row(3, 3, 3, 0, 0, 0, 2) + "\n" + sec
            + "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
            "*ELEMENT_SOLID\n" + tets + "*END\n")


class EfgPlaceholderNamed(unittest.TestCase):
    """A5 (ii) — a skipped *SECTION_SOLID_EFG's part lands on k2rad's
    placeholder /PROP/SOLID; it is now NAMED (0 bytes)."""

    def test_1_the_metal_cutting_shape_is_named(self):
        res, starter, engine = _convert(_efg_deck())
        hit = [w for w in res.warnings if w.startswith("*SECTION_SOLID_EFG 3")]
        self.assertEqual(len(hit), 1, res.warnings)
        for needle in ("(ELFORM 42)", "part(s) [3] (3 element(s))",
                       "'AutoPropSolid_3'", "*CONTROL_ADAPTIVE",
                       "*CONTROL_REMESHING_EFG",
                       "'efg 3d for 4-noded background'",
                       "efg/metal-cutting/main.k"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit[0])
        for kw in ("SECTION_SOLID_EFG", "CONTROL_ADAPTIVE",
                   "CONTROL_REMESHING_EFG"):
            self.assertIn(kw, res.skipped_keywords)
        self.assertIn("#-- SKIPPED: *SECTION_SOLID_EFG", starter)
        # the control: the recorder removed = the pre-round-7 read
        from k2rad.handlers import HANDLERS
        saved = {k: HANDLERS.pop(k) for k in list(HANDLERS)
                 if k.startswith(("SECTION_SOLID_EFG", "SECTION_SHELL_EFG"))}
        try:
            res0, s0, e0 = _convert(_efg_deck())
        finally:
            HANDLERS.update(saved)
        self.assertEqual(starter, s0)
        self.assertEqual(engine, e0)
        self.assertEqual(res.skipped_keywords, res0.skipped_keywords)
        self.assertFalse(_has(res0.warnings, "*SECTION_SOLID_EFG 3"))

    def test_2_the_TITLE_spelling_records_the_right_SECID(self):
        state = _dispatch(_efg_deck(title=True))
        self.assertEqual(state.efg_sections,
                         {3: ("SECTION_SOLID_EFG", 42)})


_IE_CURVE = ("*DEFINE_CURVE\n" + _row(9) + "\n"
             + "".join(f"{x:>20}{y:>20}\n" for x, y in
                       ((0.0, 1.0), (0.00999, 1.0), (0.01, 0.0), (1.0, 0.0))))


def _imflag_control(imflag: int, endtim: float = 0.025) -> str:
    return ("*CONTROL_IMPLICIT_GENERAL\n" + _row(imflag, 0.001) + "\n"
            "*CONTROL_TERMINATION\n" + _row(endtim) + "\n")


class ImflagNamed(unittest.TestCase):
    """A5 (iii) — IMFLAG < 0 (a method-switching curve) and IMFLAG 2/4/5/6
    are named; the deck is emitted implicit throughout (0 bytes)."""

    def test_1_the_segmentation(self):
        from k2rad.writer.assembly import imflag_segments as seg
        cases = (
            ([(0, 1), (0.00999, 1), (0.01, 0), (1.0, 0)], 0.025,
             [(0.0, 0.01, "implicit"), (0.01, 0.025, "explicit")]),
            ([(0, 0), (0.005, 1), (1, 1)], 0.02,
             [(0.0, 0.005, "explicit"), (0.005, 0.02, "implicit")]),
            ([(0, 1), (0.01, 0), (0.02, 1), (1, 1)], 0.03,
             [(0.0, 0.01, "implicit"), (0.01, 0.02, "explicit"),
              (0.02, 0.03, "implicit")]),
            ([(0, 0), (1, 0)], 0.02, [(0.0, 0.02, "explicit")]),
            ([(0, 1), (1, 1)], 0.02, [(0.0, 0.02, "implicit")]),
            ([(0, 1), (0.03, 0)], 0.025, [(0.0, 0.025, "implicit")]),
            ([(0, 0), (0, 1), (1, 1)], 0.02, [(0.0, 0.02, "implicit")]),
        )
        for pts, endtim, want in cases:
            with self.subTest(pts=pts):
                self.assertEqual(seg(pts, endtim), want)

    def test_2_the_ie_shell_curve_is_named_and_0_bytes(self):
        from k2rad.writer import assembly
        deck = _shell_plate(_imflag_control(-9), _IE_CURVE)
        res, starter, engine = _convert(deck)
        hit = [w for w in res.warnings if "IMFLAG=-9" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        for needle in ("curve 9", "implicit 0 -> 0.01, explicit 0.01 -> "
                       "0.025", "freimpl.F:82", "-99.87", "92 cycles",
                       "IMPLICIT THROUGHOUT"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit[0])
        saved = assembly._warn_imflag
        assembly._warn_imflag = lambda state: None
        try:
            _r0, s0, e0 = _convert(deck)
        finally:
            assembly._warn_imflag = saved
        self.assertEqual((starter, engine), (s0, e0))

    def test_3_IMFLAG_4_gets_the_text_only_sentence(self):
        res, _s, _e = _convert(_shell_plate(_imflag_control(4)))
        self.assertTrue(_has(res.warnings, "IMFLAG=4", "IMPLICIT THROUGHOUT",
                             "freimpl.F:82"), res.warnings)

    def test_4_IMFLAG_1_gets_neither(self):
        res, _s, _e = _convert(_shell_plate(_imflag_control(1)))
        self.assertFalse(_has(res.warnings, "*CONTROL_IMPLICIT_GENERAL "
                              "IMFLAG"), res.warnings)

    def test_5_a_constant_0_curve_says_explicit_whole_run(self):
        curve = ("*DEFINE_CURVE\n" + _row(9) + "\n"
                 + "".join(f"{x:>20}{y:>20}\n" for x, y in
                           ((0.0, 0.0), (1.0, 0.0))))
        res, _s, _e = _convert(_shell_plate(_imflag_control(-9), curve))
        self.assertTrue(_has(res.warnings, "selects EXPLICIT for the whole "
                             "run"), res.warnings)


def _spring_coupon(m30: float = 2.0e-5, implicit: bool = False) -> str:
    """G3's i14 coupon (round-7 pre-research): node 10 (*ELEMENT_MASS 1e-3)
    tied by four *MAT_SPRING_ELASTIC K = 100 springs to node 20 (a corner of
    a T 1e-6 shell: own 1.9625e-13), node 30 (*ELEMENT_MASS *m30*), node 40
    (no mass: GUARDED) and node 50 (a corner of a 1 mm shell: own
    1.9625e-7); TSSFAC 0.9."""
    control = ("*CONTROL_TERMINATION\n" + _row(2.0e-3) + "\n"
               "*CONTROL_TIMESTEP\n" + _row(0.0, 0.9) + "\n")
    if implicit:
        control = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 1.0e-4) + "\n"
                   + control)
    nodes = "*NODE\n" + "".join(
        f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n" for n, x, y in
        ((10, 0, 0), (20, 10, 0), (21, 20, 0), (22, 20, 10), (23, 10, 10),
         (30, 10, 20), (40, 10, 30), (50, 10, 40), (51, 20, 40), (52, 20, 50),
         (53, 10, 50)))
    return ("*KEYWORD\n" + control
            + "*PART\nnormal shell\n" + _row(1, 1, 1) + "\n"
            "*PART\nthin shell\n" + _row(2, 2, 1) + "\n"
            "*PART\nsprings\n" + _row(100, 100, 100) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2, 1.0, 2) + "\n" + _row(1.0) + "\n"
            "*SECTION_SHELL\n" + _row(2, 2, 1.0, 2) + "\n" + _row(1.0e-6)
            + "\n*SECTION_DISCRETE\n" + _row(100, 0) + "\n" + _row() + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            "*MAT_SPRING_ELASTIC\n" + _row(100, 100.0) + "\n" + nodes
            + "*ELEMENT_SHELL\n"
            + "".join(f"{v:>8}" for v in (1, 2, 20, 21, 22, 23)) + "\n"
            + "".join(f"{v:>8}" for v in (2, 1, 50, 51, 52, 53)) + "\n"
            "*ELEMENT_DISCRETE\n"
            + "".join("".join(f"{v:>8}" for v in (eid, 100, 10, n2)) + "\n"
                      for eid, n2 in ((101, 20), (102, 30), (103, 40),
                                      (104, 50)))
            + "*ELEMENT_MASS\n"
            + "".join(f"{v:>8}" for v in (201, 10)) + f"{1.0e-3:>16}\n"
            + "".join(f"{v:>8}" for v in (202, 30)) + f"{m30:>16}\n"
            + "*END\n")


def _token_warning(res):
    hit = [w for w in res.warnings if "was REMOVED again" in w]
    assert len(hit) == 1, res.warnings
    return hit[0]


class LightClauseNumbers(unittest.TestCase):
    """A5 (iv) — inside the LIGHT arm only: per light node and spring, the
    two-mass critical step 2 sqrt(mu / K) against Tsca x the spring's own
    step. Hand values: dt_s = sqrt(M / K) = sqrt(1e-4 / 100) = 1e-3 s; node
    10's engine mass is its *ELEMENT_MASS 1e-3 (the compensation subtracts
    the four token halves from its /ADMAS and the engine puts them back, so
    the node holds exactly the deck's mass - the part-A spec's 8e-4 left the
    halves out; its PROTECTED / UNPROTECTED labels are the same either way).
    node 20: mu ~ 1.9625e-13 -> 2 sqrt(1.9625e-15) = 8.86e-8 s;
    node 50: mu = 1.9625e-7 x 1e-3 / (1e-3 + 1.9625e-7) -> 8.86e-5 s;
    node 30: mu = 2e-5 x 1e-3 / 1.02e-3 = 1.9608e-5 -> 8.86e-4 s;
    all three < 0.9 x 1e-3 -> UNPROTECTED."""

    def test_1_the_coupon_pairs(self):
        res, starter, _e = _convert(_spring_coupon())
        w = _token_warning(res)
        for needle in (
                "node 20 on spring 101: 8.86e-08 s vs 0.9 x 0.001 s -> "
                "UNPROTECTED",
                "node 50 on spring 104: 8.86e-05 s vs 0.9 x 0.001 s -> "
                "UNPROTECTED",
                "node 30 on spring 102: 0.000886 s vs 0.9 x 0.001 s -> "
                "UNPROTECTED",
                "r1len3.F:175", "ERROR column at 99.9 %",
                "(Tsca^2 / 4) x M", "token mass 0.0001", "/DT/NODA",
                "--no-spring-token-mass-compensation"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w)
        self.assertNotIn("node 40 on spring", w)      # GUARDED, not LIGHT
        self.assertTrue(_has(res.warnings, "spring node(s) [40]"),
                        res.warnings)
        self.assertNotIn("This deck runs implicit", w)

    def test_2_the_PROTECTED_arm_is_reached(self):
        """node 30 at 4.5e-5 (still below its 5e-5 share, so still LIGHT):
        mu = 4.5e-5 x 1e-3 / 1.045e-3 = 4.306e-5 -> 1.31e-3 s >= 9e-4."""
        res, _s, _e = _convert(_spring_coupon(m30=4.5e-5))
        w = _token_warning(res)
        self.assertIn("node 30 on spring 102: 0.00131 s vs 0.9 x 0.001 s -> "
                      "PROTECTED", w)

    def test_3_an_implicit_deck_says_the_comparison_is_explicit_only(self):
        res, _s, _e = _convert(_spring_coupon(implicit=True))
        self.assertIn("This deck runs implicit", _token_warning(res))

    def test_4_the_numbers_move_no_byte(self):
        from k2rad.writer import loads
        _r, s1, e1 = _convert(_spring_coupon())
        saved = loads._light_pair_clause
        loads._light_pair_clause = lambda *a, **k: ""
        try:
            _r0, s0, e0 = _convert(_spring_coupon())
        finally:
            loads._light_pair_clause = saved
        self.assertEqual((s1, e1), (s0, e0))

    def test_5_a_TYPE13_weld_tie_steps_on_its_shear_K_times_L2(self):
        """The R14 spotweld plates' shape: a *CONSTRAINED_SPOTWELD stiff
        tie (TYPE13, K = 10 E L = 4.2e6, K_rot = K L^2 / 12 = 1.4e6, I =
        1e-6) between two 10 x 10 x 1 shells 2 mm apart (own 1.9625e-7 per
        corner, both LIGHT). The engine's rotational step stiffness adds
        the shear K x L^2 (r4def3.F:173): 1.4e6 + 4.2e6 x 4 = 1.82e7, so
        dt_r = sqrt(1e-6 / 1.82e7) = 2.344e-7 governs (dt_t 4.88e-6).
        mu = 1.9625e-7 / 2 -> crit 2 sqrt(9.8125e-8 / 4.2e6) = 3.057e-7
        >= 0.9 x 2.344e-7 -> PROTECTED. Without the L^2 term dt_r would
        read 8.45e-7 and the pair UNPROTECTED - the label plates.nrbc and
        the constrained plates keys printed before the fix."""
        def plate(nid0, z0, eid, pid):
            pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
            nodes = "".join(f"{nid0 + i:>8}{x:>16.4f}{y:>16.4f}{z0:>16.4f}\n"
                            for i, (x, y) in enumerate(pts))
            return nodes, _row(eid, pid, nid0, nid0 + 1, nid0 + 2,
                               nid0 + 3) + "\n"

        n1, e1 = plate(1, 0.0, 1, 1)
        n2, e2 = plate(11, 2.0, 2, 2)
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
                "*NODE\n" + n1 + n2 + "*ELEMENT_SHELL\n" + e1 + e2
                + "*PART\nplate1\n" + _row(1, 1, 1) + "\n"
                "*PART\nplate2\n" + _row(2, 1, 1) + "\n"
                "*SECTION_SHELL\n" + _row(1, 2) + "\n"
                + _row(1.0, 1.0, 1.0, 1.0) + "\n"
                "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                "*CONSTRAINED_SPOTWELD\n" + _row(1, 11, 1.0e4, 5.0e4) + "\n"
                "*END\n")
        res, starter, _e = _convert(deck)
        w = _token_warning(res)
        for node in (1, 11):
            with self.subTest(node=node):
                self.assertRegex(
                    w, rf"node {node} on spring \d+: 3\.06e-07 s vs 0\.9 x "
                       r"2\.34e-07 s -> PROTECTED")
        self.assertNotIn("8.45e-07", w)
        self.assertIn("r4def3.F:173", w)

    def test_6_spring_kc_adds_the_shear_term_on_TYPE13_only(self):
        from k2rad.writer.loads import _spring_kc
        dofs = [(4.2e6, 0, 0, 0.0, 0.0)] * 3 + [(1.4e6, 0, 0, 0.0, 0.0)] * 3
        self.assertEqual(_spring_kc(dofs), (4.2e6, 1.4e6, 0.0, 0.0))
        k_t, k_r, c_t, c_r = _spring_kc(dofs, l13=2.0)
        self.assertEqual((k_t, c_t, c_r), (4.2e6, 0.0, 0.0))
        self.assertAlmostEqual(k_r / 1.82e7, 1.0, places=12)

    def test_7_a_compensated_carrier_with_no_LIGHT_node_prints_no_pairs(self):
        """The pair numbers live INSIDE the LIGHT arm only. Node 60 is a
        corner of a 10 x 10 x 1 shell of RO 7.85e-6 (own 1.9625e-4, above
        its token share 5e-5): its token is removed with a negative /ADMAS
        and it is NOT light, so the shared 'REMOVED again' sentence carries
        no per-pair clause - the shape of the roster's non-LIGHT carrier
        nvh/example-06-07/6.7.spring.psd.k. The code validator's mutation
        A5-4 computed the clause for every compensated node and the whole
        suite stayed green."""
        nodes = "*NODE\n" + "".join(
            f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n" for n, x, y in
            ((10, 0, 0), (60, 10, 0), (61, 20, 0), (62, 20, 10),
             (63, 10, 10)))
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(2.0e-3) + "\n"
                "*PART\nheavy shell\n" + _row(1, 1, 1) + "\n"
                "*PART\nspring\n" + _row(100, 100, 100) + "\n"
                "*SECTION_SHELL\n" + _row(1, 2, 1.0, 2) + "\n" + _row(1.0)
                + "\n*SECTION_DISCRETE\n" + _row(100, 0) + "\n" + _row()
                + "\n*MAT_ELASTIC\n" + _row(1, 7.85e-6, 210000.0, 0.3) + "\n"
                "*MAT_SPRING_ELASTIC\n" + _row(100, 100.0) + "\n" + nodes
                + "*ELEMENT_SHELL\n"
                + "".join(f"{v:>8}" for v in (1, 1, 60, 61, 62, 63)) + "\n"
                + "*ELEMENT_DISCRETE\n"
                + "".join(f"{v:>8}" for v in (101, 100, 10, 60)) + "\n"
                + "*ELEMENT_MASS\n"
                + "".join(f"{v:>8}" for v in (201, 10)) + f"{1.0e-3:>16}\n"
                + "*END\n")
        res, _s, _e = _convert(deck)
        w = _token_warning(res)
        self.assertIn("REMOVED again from 1 node(s) [60]", w)
        for needle in ("Per pair", "two-mass critical step", "PROTECTED",
                       "keep LESS mass"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, w)
        # control: node 50 of the coupon IS light, and its pair is printed
        self.assertIn("node 50 on spring 104",
                      _token_warning(_convert(_spring_coupon())[0]))


# ═════════════════════════════════════════════════════════════════════════════
# The flags of part A reach the parser, the API, the GUI and the README
# ═════════════════════════════════════════════════════════════════════════════

def _collapse(text: str) -> str:
    """One space per whitespace run (a sentence split across source lines
    reads as the one sentence a user sees)."""
    return re.sub(r"\s+", " ", text)


class Round7FlagWiringA(unittest.TestCase):
    """Every new Part-A lever reaches the parser, the API, the GUI and the
    README (the round-6 ``Round6FlagWiringA`` checks, for this round's
    list)."""

    #: default-ON opt-outs: the spelling the README and the GUI summary carry
    #: is the ``--no-`` one.
    _FLAGS = {
        "--rigid-shell-rotary-inertia": "rigid_shell_rotary_inertia",
        "--spotweld-shear-yield": "spotweld_shear_yield",
        "--spotweld-efail-displacement": "spotweld_efail_displacement",
        "--implicit-tshell-solid": "implicit_tshell_solid",
    }
    #: figures each flag's --help must carry (matched on the collapsed render)
    _HELP_FIGURES = {
        "--rigid-shell-rotary-inertia": ("+16.83 / +33.66 % -> 0.00 %",
                                         "4.96 / 2.94 -> 0.78 / 0.73 %",
                                         "1.156x", "inirby.F:355-363",
                                         "0.1977227E-02"),
        "--spotweld-shear-yield": ("20374..20408", "= 20405",
                                   "8.58 / 26.74 %", "1.107x",
                                   "mainboltaexpl"),
        "--spotweld-efail-displacement": ("1.12650e-3", "4.6-6.0 %",
                                          "sqrt(eps^2 + gamma^2/3)",
                                          "1e19"),
        "--implicit-tshell-solid": ("28 cycles", "100 624",
                                    "s8cke3.F:354-364", "74.1 -> -0.7 %",
                                    "+0.03 -> +36.49 %"),
    }

    def _readme(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_every_flag_is_a_parser_option_with_its_no_twin(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        for flag in self._FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts)
                self.assertIn("--no-" + flag[2:], opts)

    def test_every_no_spelling_is_in_README_prose(self):
        readme = self._readme()
        body = [ln for ln in readme.splitlines()
                if not re.match(r"^\s*[-*]?\s*\[.*\]\(#.*\)\s*$", ln)]
        for flag in self._FLAGS:
            neg = "--no-" + flag[2:]
            with self.subTest(flag=neg):
                self.assertTrue(any(neg in ln for ln in body),
                                f"{neg} is not in README.md prose")

    def test_the_help_renders_and_carries_the_measured_numbers(self):
        """A bare % in a help string kills --help at a green suite."""
        from k2rad import cli
        text = cli.build_parser().format_help()
        flat = _collapse(text)
        for flag, figures in self._HELP_FIGURES.items():
            self.assertIn(flag, text)
            if flag in self._FLAGS:          # the default-ON opt-outs
                self.assertIn("--no-" + flag[2:], text)
            for figure in figures:
                with self.subTest(flag=flag, figure=figure):
                    self.assertIn(figure, flat)

    def test_the_gui_wires_every_lever_end_to_end(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for name in self._FLAGS.values():
            with self.subTest(name=name):
                kw = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="",
                    **{name: False})
                self.assertIs(kw[name], False)
                captured = []
                app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
                app._append = captured.append
                k2rad_gui.ConverterGUI._describe_options(app, kw)
                self.assertIn("--no-" + name.replace("_", "-"),
                              "".join(captured))
                kw_on = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="")
                self.assertIs(kw_on[name], True)
                captured_on = []
                app._append = captured_on.append
                k2rad_gui.ConverterGUI._describe_options(app, kw_on)
                self.assertNotIn("--no-" + name.replace("_", "-"),
                                 "".join(captured_on))
        tmp.cleanup()

    def test_every_lever_reaches_convert_and_ConvertOptions(self):
        import inspect
        from k2rad.state import ConvertOptions
        sig = inspect.signature(convert).parameters
        fields = set(ConvertOptions.__dataclass_fields__)
        for name in self._FLAGS.values():
            with self.subTest(name=name):
                self.assertIn(name, sig)
                self.assertIs(sig[name].default, True)
                self.assertIn(name, fields)
                self.assertIs(ConvertOptions().__getattribute__(name), True)

    def test_the_cli_passes_the_flag_through(self):
        """``main()`` really forwards each opt-out (a parser option the call
        drops is a silent conversion)."""
        from k2rad import cli
        import k2rad
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for flag, name in self._FLAGS.items():
            for argv, want in (([path, "--no-" + flag[2:]], False),
                               ([path], True)):
                with self.subTest(flag=flag, argv=argv[1:]):
                    seen = {}

                    def fake_convert(*a, **kw):
                        seen.update(kw)
                        raise SystemExit(0)

                    saved = k2rad.convert
                    k2rad.convert = fake_convert
                    try:
                        with self.assertRaises(SystemExit):
                            cli.main(argv)
                    finally:
                        k2rad.convert = saved
                    self.assertIs(seen.get(name), want, seen)
        tmp.cleanup()


# ═════════════════════════════════════════════════════════════════════════════
# Retracted spellings (part A): measured wrong, or superseded by a measurement
# ═════════════════════════════════════════════════════════════════════════════

def _shipped_rels(root: str):
    """Every shipped text file: README, ROADMAP, the GUI, every module of the
    package, every ``docs/*.md`` and ``tools/*.py`` (the round-6 set)."""
    rels = ["README.md", "ROADMAP.md", "k2rad_gui.py"]
    for dirpath, _dirs, files in os.walk(os.path.join(root, "k2rad")):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                rels.append(os.path.relpath(
                    os.path.join(dirpath, name), root))
    for sub, ext in (("docs", ".md"), ("tools", ".py")):
        folder = os.path.join(root, sub)
        if os.path.isdir(folder):
            rels += [os.path.join(sub, n) for n in sorted(os.listdir(folder))
                     if n.endswith(ext)]
    return rels


def _SHIPPED_TEXTS():
    """``(relative path, normalized text)``: adjacent string literals JOINED
    before the whitespace collapses. ``CHANGELOG.md`` is the historical record
    and is excluded."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    for rel in _shipped_rels(root):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        out.append((rel, _collapse(re.sub(r'"\s*\n\s*"', "", text))))
    assert len(out) >= 10, out
    return out


#: Part A statements that a round-7 measurement superseded. CHANGELOG may
#: quote them (it is the history); no other shipped text may.
_RETRACTED_ROUND_7_A = (
    # A2: the critic's revo-stiff KE RMS. Re-measured on the implementation
    # (nt 4, the same scorer): 0.73 - ONE number ships.
    "0.78 / 0.72",
    # A1: the _global_spc_dofs docstring that called the merge a ROADMAP item
    "Merging the auto-constraint in screen (c)",
    "5 roster decks do this today",
)


class Round7RetractedStatementsA(unittest.TestCase):
    """The round-4/5/6 shape: no needle in any shipped text; the guard fires
    on each needle split across two adjacent literals; a PREFIX still fires;
    the replacement text IS shipped."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_7_A:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_7_A:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "') + ' y')
                self.assertIn(_collapse(needle).lower(), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_7_A:
            with self.subTest(needle=needle):
                self.assertIn(_collapse(needle[:max(8, len(needle) // 2)]),
                              _collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_SHIPPED_TEXTS())
        pairs = (
            ("k2rad/writer/rbody.py", "4.96 / 2.94 -> 0.78 / 0.73"),
            ("k2rad/cli.py", "4.96 / 2.94 -> 0.78 / 0.73 %%"),
            ("k2rad/__init__.py", "4.96 / 2.94 -> 0.78 / 0.73 %"),
            ("k2rad_gui.py", "4.96 / 2.94 -> 0.78 / 0.73 %"),
            ("README.md", "4.96 / 2.94 → 0.78 / 0.73 %"),
            ("k2rad/writer/loads.py", "screen (c') of :func:`_make_node_tc_rc_bcs`"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])


# ═════════════════════════════════════════════════════════════════════════════
# ═════════════════════════════════════════════════════════════════════════════
# PART B — B1 *MAT_NULL PC / MU, B2 *CONSTRAINED_JOINT_SCREW, B3 the
# /PROP/TYPE6 frame, B4 the /MPC tied-node refusal, B5 the
# *CONSTRAINED_SHELL_IN_SOLID warning, B6 the docs
# ═════════════════════════════════════════════════════════════════════════════
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# B4 — an /MPC term on a tied-interface SECONDARY node is refused
# ═════════════════════════════════════════════════════════════════════════════

def _tied_plates(tie: str = "NODES", terms=((20, 3, 1.0), (5, 3, -1.0)),
                 linear: bool = True) -> str:
    """The critic's two-plate probe (r7pre/critic/gen_mpc_probe.py), by hand:
    plate A (part 1, nodes 1-15, id = 3 i + j + 1) spans x 0..20, y 0..10 at
    z 0 in 4 x 2 shells of 5 mm and is clamped at x 0 by *NODE TC 7 RC 7
    (nodes 1-3); plate B (part 2, nodes 16-30, id = 16 + 3 i + j) spans
    x 10..30 at z 1, its x = 30 edge (nodes 28-30) pushed in z. The tie's
    secondary side is plate B over plate A: *SET_NODE_LIST 10 = nodes 16-24.

    *tie*: ``NODES`` -> *CONTACT_TIED_NODES_TO_SURFACE (Spotflag 28),
    ``SURFACE`` -> *CONTACT_TIED_SURFACE_TO_SURFACE on the same node set (27),
    ``CCRIT`` -> an AUTOMATIC tiebreak OPTION 6 with CCRIT 0.005 on part 2
    (the rupture tie, Spotflag 21 on a shell secondary side), ``SPOTWELD`` ->
    *CONTACT_SPOTWELD on the node set (28). *terms* = the
    *CONSTRAINED_LINEAR_GLOBAL 1 rows (NID, DOF, COEF)."""
    out = ["*KEYWORD", "*CONTROL_TERMINATION", "    3.0E-3"]
    for pid in (1, 2):
        out += ["*PART", f"plate{pid}", _row(pid, 1, 1)]
    out += ["*SECTION_SHELL", _row(1, 2), _row(1.0, 1.0, 1.0, 1.0),
            "*MAT_ELASTIC", _row(1, 7.85e-9, 210000.0, 0.3), "*NODE"]
    for i in range(5):
        for j in range(3):
            t = 7 if i == 0 else 0
            out.append(f"{3 * i + j + 1:>8}{5.0 * i:>16.6f}{5.0 * j:>16.6f}"
                       f"{0.0:>16.6f}{t:>8}{t:>8}")
    for i in range(5):
        for j in range(3):
            out.append(f"{16 + 3 * i + j:>8}{10.0 + 5.0 * i:>16.6f}"
                       f"{5.0 * j:>16.6f}{1.0:>16.6f}{0:>8}{0:>8}")
    out.append("*ELEMENT_SHELL")
    eid = 0
    for base, pid in ((1, 1), (16, 2)):
        for i in range(4):
            for j in range(2):
                eid += 1
                n = [base + 3 * i + j, base + 3 * (i + 1) + j,
                     base + 3 * (i + 1) + j + 1, base + 3 * i + j + 1]
                out.append(f"{eid:>8}{pid:>8}" + "".join(f"{x:>8}" for x in n))
    out += ["*SET_NODE_LIST", _row(10), _row(16, 17, 18, 19, 20, 21, 22, 23),
            _row(24)]
    if tie == "NODES":
        out += ["*CONTACT_TIED_NODES_TO_SURFACE", _row(10, 1, 4, 3),
                _row(0.0, 0.0), ""]
    elif tie == "SURFACE":
        out += ["*CONTACT_TIED_SURFACE_TO_SURFACE", _row(10, 1, 4, 3),
                _row(0.0, 0.0), ""]
    elif tie == "SPOTWELD":
        out += ["*CONTACT_SPOTWELD", _row(10, 1, 4, 3), _row(0.0, 0.0), ""]
    elif tie == "CCRIT":
        out += ["*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_TIEBREAK_ID",
                f"{20:>10}glue joint", _row(2, 1, 3, 3, 0, 0, 0, 0),
                _row(0.3, 0.2, 0.0, 0.0, 0.0, 0, 0.0, 0.0),
                _row(1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _row(6, 50.0, 20.0, 0.005, 0.0, 0.0, 0.0, 0.0)]
    else:
        raise ValueError(tie)
    out += ["*SET_NODE_LIST", _row(20), _row(28, 29, 30),
            "*DEFINE_CURVE", _row(5), f"{0.0:>20.6f}{0.0:>20.6f}",
            f"{2.0e-3:>20.6f}{1.0:>20.6f}", f"{1.0:>20.6f}{1.0:>20.6f}",
            "*BOUNDARY_PRESCRIBED_MOTION_SET", _row(20, 3, 2, 5, 1.0)]
    if linear:
        out += ["*CONSTRAINED_LINEAR_GLOBAL", _row(1)]
        out += [f"{n:>10}{d:>10}{c:>10.1f}" for n, d, c in terms]
    out.append("*END")
    return "\n".join(out) + "\n"


def _type2_cards(starter: str):
    """{inter_id: (Spotflag, grnod_id)} for every /INTER/TYPE2 block."""
    lines = starter.splitlines()
    out = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^/INTER/TYPE2/(\d+)$", ln)
        if m:
            row = lines[i + 3]
            out[int(m.group(1))] = (int(row[30:40]), int(row[0:10]))
    return out


def _mpc_rows(starter: str):
    """[(title, [rows])] for every /MPC block (the round-6 helper's shape)."""
    lines = starter.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if ln.startswith("/MPC/"):
            rows = []
            for r in lines[i + 3:]:
                if r.startswith("#") or r.startswith("/"):
                    break
                rows.append(r)
            out.append((lines[i + 1], rows))
    return out


#: one sentence-fragment of every OTHER /MPC refusal note: the tied refusal
#: must be the ONE that fired (two refusals that return the same bytes hide
#: each other's deletion - round 6)
_MPC_OTHER_NOTES = ("WARNING 312 (round 5", "rigid bodies in a constraint",
                    "divides by the nodal mass", "rotary inertia IN",
                    "would read 0 as 1", "starter ERROR 137",
                    "piezoelectric voltage", "may not carry two constraint")


class MpcOnTiedSecondaryNode(unittest.TestCase):
    """B4 — a ``*CONSTRAINED_LINEAR_*`` term on a SECONDARY node of ANY emitted
    ``/INTER/TYPE2`` refuses the card, whatever the Spotflag (the critic
    refuted 'Spotflag 27/28 are safe': Spotflag 28 + a conflicting OR a
    redundant /MPC ran NORMAL at ERR 99.9 %). Reach 0 on every corpus, so the
    probes are hand-built, each with its control."""

    _SPOT = {"NODES": 28, "SURFACE": 27, "CCRIT": 21, "SPOTWELD": 28}

    def _tied_sentence(self, result):
        hits = [w for w in result.warnings if "NOT converted to /MPC" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        return hits[0]

    def test_a_term_on_a_tied_secondary_node_is_refused(self):
        for tie, sp in self._SPOT.items():
            with self.subTest(tie=tie):
                deck = _tied_plates(tie)
                r_on, s_on, _e = _convert(deck)
                _r, s_off, _e2 = _convert(deck, constrained_linear=False)
                # (a) the probe REACHES the Spotflag it names
                cards = _type2_cards(s_on)
                self.assertEqual(len(cards), 1, s_on)
                (iid, (got_sp, _g)), = cards.items()
                self.assertEqual(got_sp, sp)
                # (b) no /MPC, (c) byte-identical to the opt-out arm
                self.assertNotIn("/MPC/", s_on)
                self.assertEqual(s_on, s_off)
                self.assertIn("#-- SKIPPED: *CONSTRAINED_LINEAR_GLOBAL", s_on)
                # (d) the tied refusal's own sentence
                why = self._tied_sentence(r_on)
                for needle in (
                        f"node 20 is a secondary node of /INTER/TYPE2/{iid}",
                        f"(Spotflag {sp})", "p.10-135", "itagsl2.F:92",
                        "6237", "19.6 %", "no Spotflag is exempt"):
                    self.assertIn(needle, why)
                # (e) and NO other reason's note
                for other in _MPC_OTHER_NOTES:
                    self.assertNotIn(other, why)

    def test_a_term_on_main_side_nodes_only_is_converted(self):
        """Nodes 8 and 5 are plate-A (main side) nodes, neither clamped."""
        for tie in ("NODES", "CCRIT"):
            with self.subTest(tie=tie):
                r, s, _e = _convert(_tied_plates(
                    tie, terms=((8, 3, 1.0), (5, 3, -1.0))))
                blocks = _mpc_rows(s)
                self.assertEqual(len(blocks), 1, s)
                self.assertEqual(blocks[0][1], [
                    "         8         3         0                   1",
                    "         5         3         0                  -1"])
                self.assertTrue(_has(r.warnings, "-> /MPC"))
                self.assertFalse(_has(r.warnings, "NOT converted to /MPC"))

    def test_a_node_on_neither_side_is_converted(self):
        """Node 26 = plate B at x 25: outside the tie set, not pushed."""
        r, s, _e = _convert(_tied_plates(
            "NODES", terms=((26, 3, 1.0), (5, 3, -1.0))))
        self.assertEqual(len(_mpc_rows(s)), 1, s)
        self.assertFalse(_has(r.warnings, "NOT converted to /MPC"))

    def test_the_registry_holds_every_emitted_TYPE2(self):
        from k2rad.writer.assembly import build_starter
        for tie, sp in self._SPOT.items():
            with self.subTest(tie=tie):
                state = _dispatch(_tied_plates(tie))
                build_starter(state)
                self.assertEqual(len(state.type2_secondary), 1)
                (iid, (got_sp, nodes)), = state.type2_secondary.items()
                self.assertEqual(got_sp, sp)
                want = (set(range(16, 31)) if tie == "CCRIT"
                        else set(range(16, 25)))
                self.assertEqual(set(nodes), want)

    def test_every_TYPE2_write_line_records_its_secondary_group(self):
        """A SOURCE guard: a fifth /INTER/TYPE2 producer without the recorder
        would put a tie the screen cannot see."""
        import inspect
        from k2rad.writer import contacts
        src = inspect.getsource(contacts)
        n_emit = len(re.findall(r"^\s+lines \+= _emit_inter_type2\(", src,
                                re.M))
        n_rec = len(re.findall(r"^\s+_record_type2_secondary\(", src, re.M))
        self.assertEqual(n_emit, 4)
        self.assertEqual(n_rec, n_emit)

    def test_no_tie_no_refusal(self):
        """The control: without a tie the same term is converted."""
        deck = _tied_plates("NODES").replace(
            "*CONTACT_TIED_NODES_TO_SURFACE\n" + _row(10, 1, 4, 3) + "\n"
            + _row(0.0, 0.0) + "\n\n", "")
        self.assertNotIn("*CONTACT_TIED", deck)
        r, s, _e = _convert(deck)
        self.assertEqual(len(_mpc_rows(s)), 1, s)
        self.assertNotIn("/INTER/TYPE2/", s)


# ═════════════════════════════════════════════════════════════════════════════
# B5 — *CONSTRAINED_SHELL_IN_SOLID: one named warning, still skipped, 0 bytes
# ═════════════════════════════════════════════════════════════════════════════

def _shell_in_solid_deck(option: str = "_ID", n_cards: int = 1,
                         shstyp: int = 0, sstyp: int = 0,
                         keyword: str = "CONSTRAINED_SHELL_IN_SOLID") -> str:
    """Two unit hexes (part 1, *SECTION_SOLID ELFORM 1) with one shell (part
    3, ELFORM 2, t 0.1) at z 0.5 inside them; *SET_PART_LIST 1 = {3},
    *SET_PART_LIST 2 = {1}; *n_cards* *CONSTRAINED_SHELL_IN_SOLID cards
    (SHSID 1 SSID 2 by default, or the part ids 3 / 1 when the type cells
    say 1)."""
    out = ["*KEYWORD", "*CONTROL_TERMINATION", _row(0.001),
           "*PART", "solid", _row(1, 1, 1),
           "*PART", "plate", _row(3, 3, 1),
           "*SECTION_SOLID", _row(1, 1),
           "*SECTION_SHELL", _row(3, 2), _row(0.1, 0.1, 0.1, 0.1),
           "*MAT_ELASTIC", _row(1, 7.85e-9, 210000.0, 0.3), "*NODE"]
    nid = 0
    for k in range(2):
        for j in range(2):
            for i in range(3):
                nid += 1
                out.append(f"{nid:>8}{float(i):>16.6f}{float(j):>16.6f}"
                           f"{float(k):>16.6f}")
    for x, y in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
        nid += 1
        out.append(f"{nid:>8}{x:>16.6f}{y:>16.6f}{0.5:>16.6f}")
    out += ["*ELEMENT_SOLID",
            "       1       1       1       2       5       4       7       8"
            "      11      10",
            "       2       1       2       3       6       5       8       9"
            "      12      11",
            "*ELEMENT_SHELL", "       3       3      13      14      15      16",
            "*SET_PART_LIST", _row(1), _row(3),
            "*SET_PART_LIST", _row(2), _row(1)]
    shsid = 3 if shstyp == 1 else 1
    ssid = 1 if sstyp == 1 else 2
    for c in range(n_cards):
        out.append(f"*{keyword}{option}")
        if option == "_ID":
            out.append(_row(c + 1))
        elif option == "_TITLE":
            out.append("embedded plate")
        out.append(_row(shsid, ssid, shstyp, sstyp))
    out.append("*END")
    return "\n".join(out) + "\n"


def _sis_warnings(result):
    return [w for w in result.warnings
            if w.startswith("*CONSTRAINED_SHELL_IN_SOLID:")]


class ShellInSolidNamed(unittest.TestCase):
    """B5 — the card is recorded for ONE named warning per deck and stays in
    ``skipped_keywords`` (its ``#-- SKIPPED:`` line is part of the .rad), so
    the item moves 0 bytes. bird-el (1 deck key on 1 emitted model) is the
    only corpus carrier."""

    def test_one_named_warning_and_still_skipped(self):
        r, s, e = _convert(_shell_in_solid_deck())
        hits = _sis_warnings(r)
        self.assertEqual(len(hits), 1, r.warnings)
        for needle in ("*CONSTRAINED_SHELL_IN_SOLID: 1 card(s)",
                       "1 - shell part(s) [3] in solid part(s) [1]",
                       "NOT converted", "p.10-179", "4.9377e5 (-100 %)",
                       "+1134.62 %", "+195.21 %", "1.016x", "4.506x",
                       "refuted as a general rule in round 6"):
            self.assertIn(needle, hits[0])
        self.assertIn("CONSTRAINED_SHELL_IN_SOLID", r.skipped_keywords)
        self.assertNotIn("CONSTRAINED_SHELL_IN_SOLID",
                         [k for k, _r in r.recognized_not_emitted])
        self.assertIn("#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLID", s)
        self.assertNotIn("/INTER/TYPE18", s)
        self.assertNotIn("/INTER/TYPE18", e)

    def test_zero_bytes(self):
        """The record adds a warning and not one byte: the deck converts to
        the same .rad as the same deck with an UNREGISTERED spelling, except
        the one '#-- SKIPPED:' line that names the keyword."""
        r_on, s_on, e_on = _convert(_shell_in_solid_deck())
        r_off, s_off, e_off = _convert(_shell_in_solid_deck(
            keyword="CONSTRAINED_SHELL_IN_SOLIDX"))
        self.assertEqual(e_on, e_off)
        a, b = s_on.splitlines(), s_off.splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(diff, [("#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLID",
                                 "#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLIDX")])
        self.assertEqual(len(_sis_warnings(r_on)), 1)
        self.assertEqual(_sis_warnings(r_off), [])

    def test_the_PENALTY_and_TITLE_spellings_share_the_handler(self):
        r, _s, _e = _convert(_shell_in_solid_deck(
            keyword="CONSTRAINED_SHELL_IN_SOLID_PENALTY"))
        hits = _sis_warnings(r)
        self.assertEqual(len(hits), 1, r.warnings)
        self.assertIn("in solid part(s) [1] (_PENALTY)", hits[0])
        self.assertIn("CONSTRAINED_SHELL_IN_SOLID_PENALTY", r.skipped_keywords)
        r2, _s2, _e2 = _convert(_shell_in_solid_deck(option="_TITLE"))
        hits2 = _sis_warnings(r2)
        self.assertEqual(len(hits2), 1, r2.warnings)
        self.assertIn("(no id) - shell part(s) [3] in solid part(s) [1]",
                      hits2[0])
        r3, _s3, _e3 = _convert(_shell_in_solid_deck(option=""))
        self.assertIn("(no id) - shell part(s) [3]", _sis_warnings(r3)[0])

    def test_two_cards_are_ONE_warning(self):
        r, _s, _e = _convert(_shell_in_solid_deck(n_cards=2))
        hits = _sis_warnings(r)
        self.assertEqual(len(hits), 1, r.warnings)
        self.assertIn("2 card(s) (1 - shell part(s) [3] in solid part(s) [1]; "
                      "2 - shell part(s) [3] in solid part(s) [1])", hits[0])

    def test_part_type_sides(self):
        r, _s, _e = _convert(_shell_in_solid_deck(shstyp=1, sstyp=1))
        self.assertIn("1 - shell part(s) [3] in solid part(s) [1]",
                      _sis_warnings(r)[0])
        deck = _shell_in_solid_deck().replace(
            _row(1, 2, 0, 0), _row(9, 2, 0, 0))
        r2, _s2, _e2 = _convert(deck)
        self.assertIn("shell part(s) (set 9 not defined) in solid part(s) [1]",
                      _sis_warnings(r2)[0])

    def test_the_card_is_read_where_the_record_says(self):
        """SHSID / SSID are not swapped: a deck whose shell set and solid set
        differ reads each on its own side."""
        state = _dispatch(_shell_in_solid_deck(shstyp=1, sstyp=0))
        (c,) = state.shell_in_solid_cards
        self.assertEqual((c.coupid, c.shsid, c.ssid, c.shstyp, c.sstyp,
                          c.penalty), (1, 3, 2, 1, 0, False))

    def test_an_include_transform_offsets_each_id_in_its_bucket(self):
        """SHSTYP / SSTYP pick the namespace of the id beside them (the #125
        class): a part id moves by IDPOFF, a part-set id by IDSOFF."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write("*KEYWORD\n*CONSTRAINED_SHELL_IN_SOLID\n"
                     + _row(7, 2, 1, 0) + "\n*END\n")
        master = os.path.join(tmp.name, "master.k")
        with open(master, "w") as fh:
            # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     + _row(0, 0, 100, 0, 1000, 0) + "\n*END\n")
        state = ConversionState()
        for block in parse_k_file(master):
            dispatch(block, state)
        (c,) = state.shell_in_solid_cards
        self.assertEqual((c.shsid, c.ssid), (107, 1002))

    def test_BEAM_IN_SOLID_stays_a_plain_skip(self):
        r, s, _e = _convert(_shell_in_solid_deck(
            keyword="CONSTRAINED_BEAM_IN_SOLID"))
        self.assertIn("CONSTRAINED_BEAM_IN_SOLID", r.skipped_keywords)
        self.assertEqual(_sis_warnings(r), [])
        self.assertIn("#-- SKIPPED: *CONSTRAINED_BEAM_IN_SOLID", s)


# ═════════════════════════════════════════════════════════════════════════════
# B3 — the element-frame orthotropic /PROP/TYPE6 written co-rotational
# ═════════════════════════════════════════════════════════════════════════════

_CUBE8 = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
_CUBE_HEX = (1, 5, 1, 2, 4, 3, 5, 6, 8, 7)
_CUBE_TET = (1, 5, 1, 2, 4, 5, 5, 5, 5, 5)        # a hex collapsed to 4 nodes
#: the reference point of the AOPT 1 / 4 probes: element centre - P = +x
_P = (-10.0, 0.5, 0.5)


def _cube_mesh(tets: bool = False) -> str:
    return ("*NODE\n"
            + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                      for i, (x, y, z) in enumerate(_CUBE8, start=1))
            + "*ELEMENT_SOLID\n"
            + "".join(f"{v:>8}" for v in (_CUBE_TET if tets else _CUBE_HEX))
            + "\n")


def _hc126_deck(aopt: float = 0.0, p=(0.0, 0.0, 0.0), a=(0.0, 0.0, 0.0),
                d=(0.0, 0.0, 0.0), v=(0.0, 0.0, 0.0),
                tets: bool = False) -> str:
    """One cube on *MAT_MODIFIED_HONEYCOMB 7 in the manual's card order
    (Vol II R17 *MAT_126; card 3 EAAU..GCAU AOPT MACF, card 4 XP YP ZP A1 A2
    A3 RFAC PRU, card 5 D1 D2 D3 TSEF SSEF VREF TREF SHDFLG, and card 6 V1
    V2 V3 only when AOPT is 3 or 4)."""
    out = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
           + _cube_mesh(tets)
           + "*PART\ncore\n" + _row(5, 1, 7) + "\n"
           "*SECTION_SOLID\n" + _row(1, 0) + "\n"
           "*MAT_MODIFIED_HONEYCOMB\n"
           + _row(7, 1.0e-10, 1000.0, 0.0, 1.0, 0.2, 0.05, 0.0) + "\n"
           + _row(11, 11, 11, 11, 0, 0, 0, 0) + "\n"
           + _row(100.0, 100.0, 10.0, 50.0, 50.0, 50.0, aopt, 0) + "\n"
           + _row(*p, *a) + "\n"
           + _row(*d, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
    if int(aopt) in (3, 4):
        out += _row(*v) + "\n"
    return (out + "*DEFINE_CURVE\n" + _row(11) + "\n"
            + _row("0.0", "1.0") + "\n" + _row("1.0", "1.0") + "\n*END\n")


def _ortho93_deck(aopt: float = 1.0, p=_P, v=(0.0, 0.0, 0.0), elform=2,
                  shell_part: bool = False, tets: bool = False) -> str:
    """One cube on *MAT_ORTHOTROPIC_ELASTIC 3 - the B3.2 worked card (EA
    6000, EB 3000, EC 1500, PRBA = PRCA = PRCB 0.05, GAB 800, GBC 400, GCA
    200); *shell_part* adds a shell part 6 on the SAME material."""
    out = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
           + _cube_mesh(tets)
           + "*PART\npad\n" + _row(5, 1, 3) + "\n"
           "*SECTION_SOLID\n" + _row(1, elform) + "\n"
           "*MAT_ORTHOTROPIC_ELASTIC\n"
           + _row(3, 2.51e-9, 6000.0, 3000.0, 1500.0, 0.05, 0.05, 0.05) + "\n"
           + _row(800.0, 400.0, 200.0, aopt) + "\n"
           + _row(*p, 0.0, 0.0, 0.0, 0.0) + "\n"
           + _row(*v, 0.0, 0.0, 0.0, 0.0) + "\n")
    if shell_part:
        out += ("*PART\nskin\n" + _row(6, 2, 3) + "\n"
                "*SECTION_SHELL\n" + _row(2, 2) + "\n"
                + _row(0.5, 0.5, 0.5, 0.5) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{5.0:>16.1f}\n"
                          for i, (x, y) in ((9, (0.0, 0.0)), (10, (1.0, 0.0)),
                                            (11, (1.0, 1.0)), (12, (0.0, 1.0))))
                + "*ELEMENT_SHELL\n" + "".join(
                    f"{q:>8}" for q in (2, 6, 9, 10, 11, 12)) + "\n")
    return out + "*END\n"


def _ecd054_deck(aopt: float = 1.0, p=_P) -> str:
    """One cube on *MAT_ENHANCED_COMPOSITE_DAMAGE 4 (-> /MAT/LAW127)."""
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            + _cube_mesh()
            + "*PART\nply\n" + _row(5, 1, 4) + "\n"
            "*SECTION_SOLID\n" + _row(1, 2) + "\n"
            "*MAT_ENHANCED_COMPOSITE_DAMAGE\n"
            + _row(4, 1.6e-9, 135000.0, 9000.0, 9000.0, 0.02, 0.02, 0.4) + "\n"
            + _row(4700.0, 3200.0, 4100.0, "", aopt, 1, 2) + "\n"
            + _row(*p, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.033, 0.044) + "\n"
            + _row(0.0, 0.2, 0.8, 0.5, 2.5, 0.02, -0.015, 0.06) + "\n"
            + _row(1500.0, 2000.0, 200.0, 50.0, 70.0, 54.0, 0.5) + "\n"
            "*END\n")


def _type6_card(starter: str):
    """``(card-1 row, Ip, skew_ID)`` of the one /PROP/TYPE6 block."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("/PROP/TYPE6/"))
    rows = [r for r in lines[i + 2:i + 10] if not r.startswith("#")]
    return rows[0], int(rows[2][70:80]), int(rows[2][60:70])


def _law93_rows(starter: str, mid: int = 3):
    lines = starter.splitlines()
    i = lines.index(f"/MAT/LAW93/{mid}")
    return lines[i + 5], lines[i + 7]


#: card 1 of the honeycomb TYPE6: Isolid 1, Ismstr 1 pinned, Iframe 2
_HC_IFRAME2 = ("         1         1                   0         0         0"
               "         0         2                   0")
_HC_IFRAME0 = ("         1         1                   0         0         0"
               "         0         0                   0")
_L93_SWAPPED = ("                6000                1500                3000"
                "                 200                 0.2",
                "                 800                 400                 0.1"
                "                0.05")
_L93_ASIS = ("                6000                3000                1500"
             "                 800                 0.1",
             "                 200                 400                 0.2"
             "                 0.1")


class CorotationalOrthotropicFrame(unittest.TestCase):
    """B3 — R1: an element-frame /PROP/TYPE6 (Ip 20 / 21 / 23 / 24) is
    written CO-ROTATIONAL: the MAT_126 honeycomb's pinned Isolid 1 gets
    Iframe 2 on a brick part, an Ip 21 / 24 orthotropic brick on Isolid 17
    takes the round-6 Isolid-14 route. R2: on Ip 21 /MAT/LAW93's 2 / 3
    constants are exchanged (Radioss b = e_z x a). R3: element-frame
    tetrahedra are NAMED, cells unchanged. ``--no-corotational-orthotropic``
    restores the 65ff389 cells. Reach 0 on every corpus, so every case is a
    hand-built cube with hand-pinned rows."""

    def _r1(self, warnings, ip):
        hit = [w for w in warnings if "written CO-ROTATIONAL (Iframe 2)" in w]
        self.assertEqual(len(hit), 1, warnings)
        self.assertIn(f"(Ip={ip}, LS-DYNA AOPT", hit[0])
        return hit[0]

    def test_MAT_126_on_a_brick_gets_Iframe_2(self):
        for aopt, kw, ip in ((0.0, {}, 20),
                             (3.0, {"v": (0.0, 1.0, 0.0)}, 23),
                             (1.0, {"p": _P}, 21),
                             (4.0, {"p": _P, "v": (0.0, 0.0, 1.0)}, 24)):
            with self.subTest(aopt=aopt):
                r, s, _e = _convert(_hc126_deck(aopt, **kw))
                row, got_ip, skew = _type6_card(s)
                self.assertEqual((row, got_ip, skew), (_HC_IFRAME2, ip, 0))
                w = self._r1(r.warnings, ip)
                for needle in ("mmain.F90:2106-2113", "6.0047", "1.5049",
                               "RMS 0.164 %", "/DEF_SOLID Iframe -2"):
                    self.assertIn(needle, w)
                # the Ip-21 clause belongs to the Ip-21 arm only
                self.assertEqual("/MAT/LAW50's b / c cells are NOT permuted"
                                 in w, ip == 21)

    def test_the_skew_frame_honeycomb_is_untouched(self):
        r, s, _e = _convert(_hc126_deck(2.0, a=(1.0, 0.0, 0.0),
                                        d=(0.0, 1.0, 0.0)))
        row, ip, skew = _type6_card(s)
        self.assertEqual((row, ip), (_HC_IFRAME0, 0))
        self.assertGreater(skew, 0)
        self.assertFalse(_has(r.warnings, "CO-ROTATIONAL (Iframe 2)"))
        self.assertFalse(_has(r.warnings, "never co-rotates a tetrahedron"))

    def test_MAT_126_on_tetrahedra_is_named_not_changed(self):
        for aopt, kw, ip in ((0.0, {}, 20), (3.0, {"v": (0.0, 1.0, 0.0)}, 23)):
            for on in (True, False):
                with self.subTest(aopt=aopt, on=on):
                    r, s, _e = _convert(_hc126_deck(aopt, tets=True, **kw),
                                        corotational_orthotropic=on)
                    row, got_ip, _sk = _type6_card(s)
                    self.assertEqual((row, got_ip), (_HC_IFRAME0, ip))
                    hit = [w for w in r.warnings
                           if "never co-rotates a tetrahedron" in w]
                    self.assertEqual(len(hit), 1, r.warnings)
                    for needle in (f"(Ip={ip}, LS-DYNA AOPT {int(aopt)})",
                                   "holds 1 tetrahedra",
                                   "-40.88 .. +23.48 %", "/INIBRI/ORTHO",
                                   "sgrtails.F:972-1008"):
                        self.assertIn(needle, hit[0])
                    self.assertEqual("ERROR 1920" in hit[0], ip == 23)
                    self.assertFalse(_has(r.warnings, "CO-ROTATIONAL"))

    def test_LAW93_on_Ip_21_exchanges_b_and_c(self):
        r, s, _e = _convert(_ortho93_deck())
        self.assertEqual(_law93_rows(s), _L93_SWAPPED)
        row, ip, _sk = _type6_card(s)
        self.assertEqual((int(row[0:10]), ip), (14, 21))
        self.assertTrue(_has(r.warnings, "/MAT/LAW93/3: AOPT 1 -> /PROP/TYPE6 "
                             "Ip 21 builds b = e_z x a",
                             "NU23 x E33 / E22 = 0.05", "2 of 6 right",
                             "E 5996 / 1499.4 / 2998"), r.warnings)
        self.assertTrue(_has(r.warnings, "(Ip=21, LS-DYNA AOPT 1)",
                             "ELFORM 2 is written as Isolid 14"), r.warnings)
        r0, s0, _e0 = _convert(_ortho93_deck(), corotational_orthotropic=False)
        self.assertEqual(_law93_rows(s0), _L93_ASIS)
        self.assertEqual(int(_type6_card(s0)[0][0:10]), 17)
        self.assertTrue(_has(r0.warnings, "--no-corotational-orthotropic: "
                             "/MAT/LAW93/3 keeps its 2 / 3 constants"))
        self.assertFalse(_has(r0.warnings, "Ip 21 builds b = e_z x a"))

    def test_a_shared_material_is_not_exchanged(self):
        r, s, _e = _convert(_ortho93_deck(shell_part=True))
        self.assertEqual(_law93_rows(s), _L93_ASIS)
        self.assertTrue(_has(r.warnings, "*MAT_ORTHOTROPIC_ELASTIC 3: AOPT 1 "
                             "-> Ip 21 on part(s) [5]",
                             "part 6 (shell elements)",
                             "the material card is shared"), r.warnings)
        self.assertFalse(_has(r.warnings, "Ip 21 builds b = e_z x a"))

    def test_a_tetrahedron_part_blocks_the_exchange(self):
        r, s, _e = _convert(_ortho93_deck(tets=True))
        self.assertEqual(_law93_rows(s), _L93_ASIS)
        self.assertTrue(_has(r.warnings, "never co-rotates a tetrahedron",
                             "(Ip=21, LS-DYNA AOPT 1)"), r.warnings)

    def test_LAW127_on_Ip_21_keeps_its_cells_and_is_named(self):
        r, s, _e = _convert(_ecd054_deck())
        r0, s0, _e0 = _convert(_ecd054_deck(), corotational_orthotropic=False)
        law = [ln for ln in s.splitlines() if ln.startswith("/MAT/LAW127/")]
        self.assertEqual(len(law), 1, s[:3000])

        def block(text):
            lines = text.splitlines()
            i = lines.index(law[0])
            return lines[i:i + 30]
        self.assertEqual(block(s), block(s0))
        self.assertTrue(_has(r.warnings, "(part 5, /MAT/LAW127): AOPT 1 -> "
                             "Ip 21", "/MAT/LAW127's 2 / 3 cells are NOT "
                             "exchanged"), r.warnings)
        self.assertFalse(_has(r.warnings, "Ip 21 builds b = e_z x a"))

    def test_AOPT_4_takes_the_Isolid_14_route(self):
        r, s, _e = _convert(_ortho93_deck(aopt=4.0, v=(0.0, 0.0, 1.0)))
        row, ip, _sk = _type6_card(s)
        self.assertEqual((int(row[0:10]), ip), (14, 24))
        self.assertEqual(_law93_rows(s), _L93_ASIS)     # no exchange on 24
        self.assertTrue(_has(r.warnings, "(Ip=24, LS-DYNA AOPT 4)",
                             "on Isolid 14 right on 6 of 6"), r.warnings)
        r0, s0, _e0 = _convert(_ortho93_deck(aopt=4.0, v=(0.0, 0.0, 1.0)),
                               corotational_orthotropic=False)
        self.assertEqual(int(_type6_card(s0)[0][0:10]), 17)
        r24, s24, _e24 = _convert(
            _ortho93_deck(aopt=4.0, v=(0.0, 0.0, 1.0), elform=-2),
            assumed_strain_isolid="24")
        self.assertEqual(int(_type6_card(s24)[0][0:10]), 24)

    def test_the_opt_out_restores_the_65ff389_cards(self):
        for aopt, kw, ip in ((0.0, {}, 20), (1.0, {"p": _P}, 21),
                             (3.0, {"v": (0.0, 1.0, 0.0)}, 23),
                             (4.0, {"p": _P, "v": (0.0, 0.0, 1.0)}, 24)):
            with self.subTest(aopt=aopt):
                r, s, _e = _convert(_hc126_deck(aopt, **kw),
                                    corotational_orthotropic=False)
                self.assertEqual(_type6_card(s)[:2], (_HC_IFRAME0, ip))
                self.assertTrue(_has(r.warnings,
                                     "--no-corotational-orthotropic: "
                                     "/PROP/TYPE6", f"(Ip={ip})"))

    def test_the_sbrake_shape_is_byte_identical_in_both_arms(self):
        """Isolid 14 is already co-rotational (the reader forces JCVT 2,
        hm_read_prop06.F:297-298), so R1 leaves the round-6 card alone."""
        deck = _ortho93_deck(aopt=0.0, p=(0.0, 0.0, 0.0), elform=1)
        _r, s_on, e_on = _convert(deck)
        _r0, s_off, e_off = _convert(deck, corotational_orthotropic=False)
        self.assertEqual((s_on, e_on), (s_off, e_off))
        row, ip, _sk = _type6_card(s_on)
        self.assertEqual((int(row[0:10]), int(row[70:80]), ip), (14, 0, 20))


# ═════════════════════════════════════════════════════════════════════════════
# B1 — the *MAT_NULL PC / MU cells on /MAT/HYD_VISC
# ═════════════════════════════════════════════════════════════════════════════

_NU_PMIN_FLOOR = "                   0       -1.000000E-20"    # A1's row
_NU_PMIN_ZERO = "                   0                   0"
_GRUNEISEN_1 = ("*EOS_GRUNEISEN\n" + _row(1, 1.5e6, 1.0, 0.0, 0.0, 0.0, 0.0,
                                          0.0) + "\n" + _row(1.0) + "\n")


def _hex_nodes_x(nx: int) -> str:
    nodes = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in range(nx + 1)]
    return "*NODE\n" + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                               for i, (x, y, z) in enumerate(nodes, start=1))


def _hex_x(eid: int, pid: int, x0: int, nx: int) -> str:
    """One unit hex at x0..x0+1 of a lattice _hex_nodes_x(nx) numbered x
    fastest, then y, then z."""
    def nid(x, y, z):
        return 1 + x + (nx + 1) * (y + 2 * z)
    n = [nid(x0, 0, 0), nid(x0 + 1, 0, 0), nid(x0 + 1, 1, 0), nid(x0, 1, 0),
         nid(x0, 0, 1), nid(x0 + 1, 0, 1), nid(x0 + 1, 1, 1), nid(x0, 1, 1)]
    return "".join(f"{v:>8}" for v in [eid, pid] + n) + "\n"


def _null_card(mid: int, ro, pc: str, mu, terod="", cerod="") -> str:
    """*MAT_NULL card 1 with PC as TEXT, so a blank field can be written."""
    return ("*MAT_NULL\n" + f"{mid:>10}{ro:>10}{pc:>10}{mu:>10}{terod:>10}"
            f"{cerod:>10}" + "\n")


def _null_fluid_deck(pc: str = "0.0", mu="0.0", ro=1.0e-9, elform=1,
                     sph: bool = False, void: str = "", ammg: bool = False,
                     eos: str = "gruneisen", terod="", cerod="",
                     second_part_elform=None, no_part: bool = False) -> str:
    """Part 1 = one unit hex (x 0..1) on *SECTION_SOLID 1 ELFORM *elform*,
    material *MAT_NULL 1 + its EOS: ``gruneisen`` = *EOS_GRUNEISEN 1 (C 1.5e6:
    with RO 1e-9 the tension floor -RO C^2 is -2250), ``linpoly`` =
    *EOS_LINEAR_POLYNOMIAL 1 (C0 0, C1 1, C3 0: floor -1), ``eosid`` = the
    material is *MAT_NULL 3 bound to *EOS_GRUNEISEN 1 by the *PART EOSID
    field (sph/bird's route).
    ``second_part_elform`` adds part 2 (x 1..2, section 2) on the SAME
    material; ``sph`` moves part 1 onto an SPH section (8 particles);
    ``void`` = "self" states *INITIAL_VOID_PART 1, "other" adds part 9 (x
    2..3, ELFORM 12, *MAT_NULL 9 + *EOS_GRUNEISEN 9) as the void;
    ``ammg`` adds an *ALE_MULTI-MATERIAL_GROUP over part 1; ``no_part``
    leaves *MAT_NULL 1 unused (part 1 goes to a *MAT_ELASTIC 5)."""
    mid = 3 if eos == "eosid" else 1
    out = ["*KEYWORD", "*CONTROL_TERMINATION", _row(1.0e-3), _hex_nodes_x(3)]
    if sph:
        out += ["*ELEMENT_SPH"] + [f"{n:>8}{1:>8}" for n in (1, 2, 5, 6, 9, 10,
                                                          13, 14)]
        out += ["*SECTION_SPH", _row(1, 1.2, 0.2, 2.0)]
    else:
        out += ["*ELEMENT_SOLID", _hex_x(1, 1, 0, 3).rstrip("\n"),
                "*SECTION_SOLID", _row(1, elform)]
    part_mid = 5 if no_part else mid
    out += ["*PART", "fluid",
            _row(1, 1, part_mid, 1 if eos == "eosid" else 0)]
    if no_part:
        out += ["*MAT_ELASTIC", _row(5, 7.85e-9, 210000.0, 0.3)]
    if second_part_elform is not None:
        out += ["*ELEMENT_SOLID", _hex_x(2, 2, 1, 3).rstrip("\n"),
                "*SECTION_SOLID", _row(2, second_part_elform),
                "*PART", "fluid 2", _row(2, 2, mid)]
    out.append(_null_card(mid, ro, pc, mu, terod, cerod).rstrip("\n"))
    if eos == "linpoly":
        out += ["*EOS_LINEAR_POLYNOMIAL",
                _row(1, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0), _row(0.0, 1.0)]
    else:
        out.append(_GRUNEISEN_1.rstrip("\n"))
    if void == "self":
        out += ["*INITIAL_VOID_PART", _row(1)]
    elif void == "other":
        out += ["*ELEMENT_SOLID", _hex_x(9, 9, 2, 3).rstrip("\n"),
                "*SECTION_SOLID", _row(9, 12), "*PART", "void",
                _row(9, 9, 9), _null_card(9, 1.0e-9, "0.0", "0.0").rstrip(),
                _GRUNEISEN_1.replace(_row(1, 1.5e6), _row(9, 1.5e6)).rstrip(),
                "*INITIAL_VOID_PART", _row(9)]
    if ammg:
        out += ["*ALE_MULTI-MATERIAL_GROUP", _row(1, 1)]
    out.append("*END")
    return "\n".join(out) + "\n"


def _hyd_block(starter: str, mid: int):
    lines = starter.splitlines()
    i = lines.index(f"/MAT/HYD_VISC/{mid}")
    return lines[i:i + 6]


def _nu_pmin(starter: str, mid: int = 1) -> str:
    return _hyd_block(starter, mid)[5]


def _w(result, head: str):
    return [w for w in result.warnings if w.startswith(head)]


_WP = "*MAT_NULL PC -> /MAT/HYD_VISC Pmin"
_WN1 = "*MAT_NULL MU -> /MAT/HYD_VISC Nu"
_WN = "*MAT_NULL MU is NOT carried (Nu 0)"


class MatNullPcMu(unittest.TestCase):
    """B1 — every *MAT_NULL + *EOS_* /MAT/HYD_VISC carrier the void floor does
    not cover gets Pmin = PC (PC 0 / blank -> -1e-20, LS-DYNA cuts at zero;
    PC > 0 refused), and Nu = MU / RO only where every part of the material
    is a *SECTION_SOLID ELFORM 6 on a deck without *INITIAL_VOID; every
    excluded class is named. Keyed on the *MAT_NULL record, never on the
    emitted card. --no-mat-null-pc-mu restores the 65ff389 cells."""

    def test_PC_zero_is_written_minus_1e_20(self):
        r, s, _e = _convert(_null_fluid_deck(pc="0.0"))
        self.assertEqual(_nu_pmin(s), _NU_PMIN_FLOOR)
        hit = _w(r, _WP)
        self.assertEqual(len(hit), 1, r.warnings)
        for needle in ("/MAT/HYD_VISC/1 Pmin -1e-20 (PC 0; it can act",
                       "-2250", "884 340", "hm_read_mat06.F:154",
                       "--no-mat-null-pc-mu"):
            self.assertIn(needle, hit[0])
        for w in r.warnings:
            self.assertNotIn("cavitation floor", w)
            self.assertNotIn("INITIAL_VOID", w)

    def test_PC_blank_is_the_same_rule(self):
        r, s, _e = _convert(_null_fluid_deck(pc=""))
        self.assertEqual(_nu_pmin(s), _NU_PMIN_FLOOR)
        self.assertTrue(_has(r.warnings, "/MAT/HYD_VISC/1 Pmin -1e-20 (PC 0;"))

    def test_a_negative_PC_is_written_as_stated(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-0.1"))
        self.assertEqual(_nu_pmin(s), "                   0                -0.1")
        r2, s2, _e2 = _convert(_null_fluid_deck(pc="-1.0E4"))
        self.assertEqual(_nu_pmin(s2),
                         "                   0              -10000")
        self.assertTrue(_has(r2.warnings, "/MAT/HYD_VISC/1 Pmin -10000 (PC "
                             "-10000; it cannot act: the /EOS/GRUNEISEN "
                             "pressure never goes below -2250"), r2.warnings)

    def test_a_positive_PC_is_refused_by_name(self):
        r, s, _e = _convert(_null_fluid_deck(pc="5.0"))
        self.assertEqual(_nu_pmin(s), _NU_PMIN_ZERO)
        self.assertTrue(_has(r.warnings, "*MAT_NULL 1: PC 5 is POSITIVE",
                             "p.2-189"), r.warnings)
        self.assertEqual(_w(r, _WP), [])

    def test_the_linear_polynomial_floor(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0", eos="linpoly"))
        self.assertEqual(_nu_pmin(s), "                   0                  -1")
        self.assertTrue(_has(r.warnings, "/EOS/POLYNOMIAL pressure never goes "
                             "below -1"), r.warnings)
        r2, _s2, _e2 = _convert(_null_fluid_deck(pc="-0.5", eos="linpoly"))
        self.assertTrue(_has(r2.warnings, "Pmin -0.5 (PC -0.5; it can act: the "
                             "/EOS/POLYNOMIAL pressure reaches -1"),
                        r2.warnings)

    def test_both_EOS_routes(self):
        for route, mid in (("gruneisen", 1), ("eosid", 3)):
            with self.subTest(route=route):
                r, s, _e = _convert(_null_fluid_deck(pc="-1.0", eos=route))
                self.assertEqual(_nu_pmin(s, mid),
                                 "                   0                  -1")
                self.assertTrue(_has(r.warnings, f"/MAT/HYD_VISC/{mid} Pmin -1 "
                                     "(PC -1; it can act: the /EOS/GRUNEISEN "
                                     "pressure reaches -2250"), r.warnings)

    def test_MU_over_RO_on_ELFORM_6(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0E4", mu="1.0E-6",
                                             elform=6))
        self.assertEqual(_nu_pmin(s), "                1000              -10000")
        hit = _w(r, _WN1)
        self.assertEqual(len(hit), 1, r.warnings)
        for needle in ("Nu 1000 (MU 1e-06 / RO 1e-09, parts [1])",
                       "m6law.F:98", "channel_B goes IE -98.89 -> -0.09 %",
                       "emits as a Lagrangian one-point /PROP/SOLID"):
            self.assertIn(needle, hit[0])
        self.assertEqual(_w(r, _WN), [])

    def test_the_Nu_scope_names_every_excluded_class(self):
        cases = (
            ("ELFORM 1", {"elform": 1}, "Lagrangian solid (ELFORM 1)",
             "10.3 -> 29.6"),
            ("SPH", {"sph": True}, "parts [1]: SPH", "sph/bird"),
            ("ELFORM 12, no void", {"elform": 12}, "ELFORM 12", "+20691.23 %"),
            ("ELFORM 6 + a void elsewhere", {"elform": 6, "void": "other"},
             "parts [1]: ELFORM 6", "+20691.23 %"),
            ("ELFORM 11 + AMMG", {"elform": 11, "ammg": True},
             "ELFORM 11 (multi-material ALE)", "*ALE_MULTI-MATERIAL_GROUP"),
            ("ELFORM 6 + ELFORM 1 (mixed)",
             {"elform": 6, "second_part_elform": 1},
             "parts [1, 2]: ELFORM 6, Lagrangian solid (ELFORM 1)",
             "the cell is per MATERIAL"),
            ("no part", {"no_part": True}, "no *PART uses it",
             "carries no Nu either"),
        )
        heads = {"+20691.23 %": "on the ELFORM-12 fluid of a *INITIAL_VOID",
                 "*ALE_MULTI-MATERIAL_GROUP": "the cell is unmeasured there"}
        for name, kw, cls, fact in cases:
            with self.subTest(case=name):
                r, s, _e = _convert(_null_fluid_deck(pc="-1.0", mu="1.0E-6",
                                                     **kw))
                self.assertEqual(_nu_pmin(s)[:20], " " * 19 + "0")
                hits = _w(r, _WN)
                self.assertEqual(len(hits), 1, r.warnings)
                self.assertIn("/MAT/HYD_VISC/1 (MU 1e-06;", hits[0])
                self.assertIn(cls, hits[0])
                self.assertIn(fact, hits[0])
                # WHICH sentence fired: the void / AMMG / class ones differ
                want = heads.get(fact, "the one family where it was "
                                       "measured right")
                self.assertIn(want, hits[0])
                self.assertEqual(_w(r, _WN1), [])

    def test_A1_keeps_precedence(self):
        r, s, _e = _convert(_null_fluid_deck(pc="0.0", elform=12, void="self"))
        self.assertEqual(_nu_pmin(s), _NU_PMIN_FLOOR)
        self.assertTrue(_has(r.warnings,
                             "cavitation floor Pmin = -1e-20 is written"))
        self.assertEqual(_w(r, _WP), [])      # no non-A1 carrier
        r2, s2, _e2 = _convert(_null_fluid_deck(pc="-7.5", elform=12,
                                                void="self"))
        self.assertEqual(_nu_pmin(s2), _NU_PMIN_FLOOR)
        self.assertTrue(_has(r2.warnings, "The deck's PC -7.5 on *MAT_NULL 1 "
                             "is OVERRIDDEN"), r2.warnings)
        self.assertEqual(_w(r2, _WP), [])

    def test_the_A1_opt_out_falls_back_to_the_PC_cell(self):
        deck = _null_fluid_deck(pc="0.0", elform=12, void="self")
        r, s, _e = _convert(deck, initial_void_floor=False)
        self.assertEqual(_nu_pmin(s), _NU_PMIN_FLOOR)
        self.assertTrue(_has(r.warnings, _WP, "/MAT/HYD_VISC/1 Pmin -1e-20"))
        self.assertTrue(_has(r.warnings, "--no-initial-void-floor:",
                             "carry the *MAT_NULL PC cell instead"))
        self.assertFalse(_has(r.warnings, "--no-initial-void-floor:",
                              "keep Pmin 0"))
        r2, s2, _e2 = _convert(_null_fluid_deck(pc="-7.5", elform=12,
                                                void="self"),
                               initial_void_floor=False)
        self.assertEqual(_nu_pmin(s2), "                   0                -7.5")
        self.assertTrue(_has(r2.warnings, "/MAT/HYD_VISC/1 Pmin -7.5 (the "
                             "stated PC)"), r2.warnings)
        r3, s3, _e3 = _convert(deck, initial_void_floor=False,
                               mat_null_pc_mu=False)
        self.assertEqual(_nu_pmin(s3), _NU_PMIN_ZERO)
        self.assertTrue(_has(r3.warnings, "--no-initial-void-floor:",
                             "keep Pmin 0", "-INFINITY"), r3.warnings)

    def test_MAT_NULL_reads_MU_TEROD_CEROD(self):
        st = _dispatch(_null_card(1, 1.0e-9, "-7.5", 1.0e-6, 1.1, 0.8)
                       .replace("*MAT_NULL", "*KEYWORD\n*MAT_NULL") + "*END\n")
        m = st.mat_null[1]
        self.assertEqual((m.pc, m.mu, m.terod, m.cerod),
                         (-7.5, 1.0e-6, 1.1, 0.8))
        for on in (True, False):
            with self.subTest(on=on):
                r, _s, _e = _convert(_null_fluid_deck(terod=1.1, cerod=0.8),
                                     mat_null_pc_mu=on)
                self.assertTrue(_has(r.warnings, "*MAT_NULL 1: TEROD 1.1 / "
                                     "CEROD 0.8", "is DROPPED"), r.warnings)

    def test_negative_MU_and_zero_RO_are_refused(self):
        r, s, _e = _convert(_null_fluid_deck(mu="-1.0E-6", elform=6))
        self.assertEqual(_nu_pmin(s)[:20], " " * 19 + "0")
        self.assertTrue(_has(r.warnings, "*MAT_NULL 1: MU -1e-06 is negative"))
        r2, s2, _e2 = _convert(_null_fluid_deck(mu="1.0E-6", ro=0.0,
                                                elform=6))
        self.assertEqual(_nu_pmin(s2)[:20], " " * 19 + "0")
        self.assertTrue(_has(r2.warnings, "*MAT_NULL 1: RO <= 0 as stated - "
                             "Nu = MU / RO cannot be formed"), r2.warnings)
        # the zero-density floor's 1e-24 is not a density to divide by: the
        # refusal holds in both arms of that floor
        r3, s3, _e3 = _convert(_null_fluid_deck(mu="1.0E-6", ro=0.0,
                                                elform=6),
                               zero_density_floor=False)
        self.assertEqual(_nu_pmin(s3)[:20], " " * 19 + "0")
        self.assertTrue(_has(r3.warnings, "RO <= 0 as stated"), r3.warnings)

    def test_the_opt_out_restores_the_65ff389_cells(self):
        deck = _null_fluid_deck(pc="-1.0E4", mu="1.0E-6", elform=6)
        r_on, s_on, e_on = _convert(deck)
        r_off, s_off, e_off = _convert(deck, mat_null_pc_mu=False)
        self.assertEqual(_nu_pmin(s_off), _NU_PMIN_ZERO)
        self.assertEqual(e_on, e_off)
        a, b = s_on.splitlines(), s_off.splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(diff, [("                1000              -10000",
                                 _NU_PMIN_ZERO)])
        self.assertTrue(_has(r_off.warnings, "--no-mat-null-pc-mu: the "
                             "*MAT_NULL PC / MU cells are not carried on "
                             "/MAT/HYD_VISC [1]"), r_off.warnings)
        self.assertEqual(_w(r_off, _WP) + _w(r_off, _WN1), [])

    def test_MAT_ELASTIC_FLUID_is_untouched(self):
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
                + _hex_nodes_x(1) + "*ELEMENT_SOLID\n" + _hex_x(1, 1, 0, 1)
                + "*SECTION_SOLID\n" + _row(3, 2) + "\n"
                "*PART\nair\n" + _row(1, 3, 3) + "\n"
                "*MAT_ELASTIC_FLUID\n"
                + _row(3, 1.22, 0.0, 0.0, 0.0, 0.0, 141.03, 0) + "\n"
                + _row(0.0, 0.0) + "\n*END\n")
        r_on, s_on, e_on = _convert(deck)
        _r, s_off, e_off = _convert(deck, mat_null_pc_mu=False)
        self.assertIn("/MAT/HYD_VISC/3", s_on)
        self.assertEqual((s_on, e_on), (s_off, e_off))
        self.assertFalse(any(w.startswith("*MAT_NULL") for w in r_on.warnings))

    def test_golden_underwater_A_and_channel_B_cards(self):
        """The two corpus carriers' own cards: underwater_A (*MAT_NULL 1 RO
        1E-09 PC 0.0 MU 0.0, *EOS_GRUNEISEN C 15000000, ELFORM 1) and channel_B
        (RO 1E-09 PC -10000 MU 1E-06, *EOS_GRUNEISEN C 1500000, ELFORM 6)."""
        uw = _null_fluid_deck(pc="0.0", elform=1).replace(
            _row(1, 1.5e6), _row(1, 1.5e7))
        ch = _null_fluid_deck(pc="-10000", mu="1E-06", elform=6)
        for deck, row in ((uw, _NU_PMIN_FLOOR),
                          (ch, "                1000              -10000")):
            with self.subTest(row=row):
                _r, s, _e = _convert(deck)
                self.assertEqual(_hyd_block(s, 1), [
                    "/MAT/HYD_VISC/1", "FLUID_1", "#              RHO_I",
                    "        1.000000E-09",
                    "#                 Nu                Pmin", row])
        r_uw, _s, _e = _convert(uw)
        self.assertTrue(_has(r_uw.warnings, "/EOS/GRUNEISEN pressure reaches "
                             "-225000"), r_uw.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# B2 — *CONSTRAINED_JOINT_SCREW -> /GJOINT/RACK + the contact split
# ═════════════════════════════════════════════════════════════════════════════

#: EXP_SC_JOINT_SCREW's drive curve LCID 10000007 (its six points)
_SCREW_CURVE = ((0.0, 0.0), (0.006, 1.0), (0.03, 5.0), (0.06, 5.0),
                (0.1, 15.0), (0.6, 100.0))


def _screw_deck(keyword: str = "*CONSTRAINED_JOINT_SCREW_ID", parm=25.0,
                con2_a: int = 5, vad: int = 2, sf=1.0, birth=0.0,
                drive: bool = True, drive_on_b: bool = False,
                implicit: bool = False, s2s: bool = False,
                n5_on_plate: bool = False, n2_off_axis: bool = False,
                diagonal: bool = False, swap_axis: bool = False,
                a_elastic_cnrb: bool = False, bndout: bool = False,
                a_rigid_cnrb: bool = False, a_node_tc: int = 0,
                b_spc: bool = False, b_global: bool = False,
                a_node_motion: bool = False) -> str:
    """The B2 mini screw (ton-mm-s, explicit, ENDTIM 0.1): part 2 "screw out"
    (A) = one hex x 10..20, y 0..10, z 0..10 on *MAT_RIGID 2 (CMO 1, CON1 5,
    CON2 *con2_a*); part 1 "screw in" (B) = one hex x -15..-5 on *MAT_RIGID 1
    (CMO 1, CON1 5, CON2 7); part 3 = a 2 x 2 *ELEMENT_SHELL plate at x 30
    (*MAT_ELASTIC). N1 (20, 0, 0) / N3 (10, 0, 0) / N5 (20, 0, 10) on A, N2
    (-5, 0, 0) / N4 (-15, 0, 0) / N6 (-5, 0, 10) on B; PARM 25; the drive
    *BOUNDARY_PRESCRIBED_MOTION_RIGID pid 2 DOF 5 VAD *vad* LCID 7 on the
    deck's six points; *CONTACT_AUTOMATIC_SINGLE_SURFACE SSID 0. A's nodal
    centroid (the element-free /RBODY main) is (15, 5, 5); |N1N3| = 10, so
    the carriage offset is 1.0. *diagonal* moves B to y -25..-15 and puts
    N1 on (20, 10, 0): the axis is (1, 1, 0). The validation round's probes
    (each a standard condition on a body, refusal 11, or the CNRB case of
    refusal 5): *a_rigid_cnrb* puts A's eight nodes in a
    *CONSTRAINED_NODAL_RIGID_BODY while A stays *MAT_RIGID; *a_node_tc*
    writes that *NODE TC on A's member node 3 (20, 10, 0); *b_spc* a
    *BOUNDARY_SPC_NODE (DOFY) on B's member node 11 (-5, 10, 0); *b_global*
    a *CONSTRAINED_GLOBAL plane x = -15 (TC 1) through B's face; and
    *a_node_motion* a *BOUNDARY_PRESCRIBED_MOTION_NODE (DOF 3, VAD 2,
    LCID 7) on A's node 3."""
    by = -25.0 if diagonal else 0.0
    pts = {}
    nid = 0

    def hexa(x0, y0):
        nonlocal nid
        ids = []
        for z in (0.0, 10.0):
            for y, x in ((y0, x0), (y0, x0 + 10.0), (y0 + 10.0, x0 + 10.0),
                         (y0 + 10.0, x0)):
                nid += 1
                pts[nid] = (x, y, z)
                ids.append(nid)
        return ids
    a_ids = hexa(10.0, 0.0)        # nodes 1-8: A
    b_ids = hexa(-15.0, by)        # nodes 9-16: B
    plate = {}
    for j, z in enumerate((0.0, 5.0, 10.0)):
        for i, y in enumerate((0.0, 5.0, 10.0)):
            nid += 1
            pts[nid] = (30.0, y, z)
            plate[(i, j)] = nid

    def node_at(xyz):
        return next(k for k, v in pts.items() if v == xyz)
    n1 = node_at((20.0, 10.0 if diagonal else 0.0, 0.0))
    n3 = node_at((10.0, 0.0, 0.0))
    n5 = (plate[(0, 0)] if n5_on_plate
          else node_at((20.0, 10.0 if diagonal else 0.0, 10.0)))
    n2 = node_at((-5.0, 10.0, 0.0) if n2_off_axis
                 else (-5.0, -15.0 if diagonal else 0.0, 0.0))
    n4 = node_at((-15.0, -25.0 if diagonal else 0.0, 0.0))
    n6 = node_at((-5.0, -15.0 if diagonal else 0.0, 10.0))
    if swap_axis:
        n1, n3, n2, n4 = n3, n1, n4, n2
    out = ["*KEYWORD", "*CONTROL_TERMINATION", _row(0.1), "*NODE"]
    out += [f"{k:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}"
            + (f"{a_node_tc:>8}{0:>8}" if a_node_tc and k == 3 else "")
            for k, (x, y, z) in sorted(pts.items())]
    out += ["*ELEMENT_SOLID",
            "".join(f"{v:>8}" for v in [1, 2] + a_ids),
            "".join(f"{v:>8}" for v in [2, 1] + b_ids),
            "*ELEMENT_SHELL"]
    eid = 2
    for j in range(2):
        for i in range(2):
            eid += 1
            out.append("".join(f"{v:>8}" for v in (
                eid, 3, plate[(i, j)], plate[(i + 1, j)],
                plate[(i + 1, j + 1)], plate[(i, j + 1)])))
    out += ["*PART", "screw in", _row(1, 1, 1),
            "*PART", "screw out", _row(2, 1, 2),
            "*PART", "plate", _row(3, 3, 3),
            "*SECTION_SOLID", _row(1, 1),
            "*SECTION_SHELL", _row(3, 2), _row(1.0, 1.0, 1.0, 1.0),
            "*MAT_RIGID", _row(1, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0),
            _row(1.0, 5, 7), _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
    if a_elastic_cnrb:
        out += ["*MAT_ELASTIC", _row(2, 7.85e-9, 210000.0, 0.3),
                "*SET_NODE_LIST", _row(77), _row(*a_ids),
                "*CONSTRAINED_NODAL_RIGID_BODY", _row(88, 0, 77)]
    else:
        out += ["*MAT_RIGID", _row(2, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0),
                _row(1.0, 5, con2_a), _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
    if a_rigid_cnrb:
        out += ["*SET_NODE_LIST", _row(77), _row(*a_ids),
                "*CONSTRAINED_NODAL_RIGID_BODY", _row(88, 0, 77)]
    if b_spc:
        out += ["*BOUNDARY_SPC_NODE", _row(11, 0, 0, 1, 0, 0, 0, 0)]
    if b_global:
        out += ["*CONSTRAINED_GLOBAL", _row(1, 0, 1, -15.0, 0.0, 0.0, 0.0)]
    if a_node_motion:
        out += ["*BOUNDARY_PRESCRIBED_MOTION_NODE",
                _row(3, 3, 2, 7, 1.0, 0, 1e25, 0.0)]
    out += ["*MAT_ELASTIC", _row(3, 7.85e-9, 210000.0, 0.3),
            "*DEFINE_CURVE", _row(7)]
    out += [f"{x:>20}{y:>20}" for x, y in _SCREW_CURVE]
    if drive:
        out += ["*BOUNDARY_PRESCRIBED_MOTION_RIGID",
                _row(2, 5, vad, 7, sf, 0, 1e25, birth)]
    if drive_on_b:
        out += ["*BOUNDARY_PRESCRIBED_MOTION_RIGID",
                _row(1, 1, 0, 7, 1.0, 0, 1e25, 0.0)]
    out += ["*CONTACT_AUTOMATIC_SINGLE_SURFACE",
            _row(0, 0, 5, 0), _row(0.1, 0.0, 0.0, 0.0), ""]
    if s2s:
        out += ["*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
                _row(1, 2, 3, 3), _row(0.1, 0.0), ""]
    if implicit:
        out += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 0.01)]
    if bndout:
        out += ["*DATABASE_BNDOUT", _row(1e-4)]
    out += [keyword, _row(9) + "screw",
            _row(n1, n2, n3, n4, n5, n6, 1.0, 0.0), _row(parm, 0, 0, 0.0),
            "*END"]
    return "\n".join(out) + "\n"


def _block_after(text: str, head_prefix: str, n: int):
    """The *n* lines after the first line starting with *head_prefix*."""
    lines = text.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(head_prefix))
    return lines[i:i + n]


def _rbody_main(starter: str, part: int) -> int:
    """The main node of the /RBODY whose secondary group is
    rb_nodes_pid<part> (the *MAT_RIGID producer's naming)."""
    lines = starter.splitlines()
    grnods = {int(lines[i].split("/")[3]): lines[i + 1]
              for i, ln in enumerate(lines) if ln.startswith("/GRNOD/NODE/")}
    for i, ln in enumerate(lines):
        if ln.startswith("/RBODY/"):
            g = int(lines[i + 3][60:70])      # grnd_ID, cols 61-70
            if grnods.get(g) == f"rb_nodes_pid{part}":
                return int(ln.split("/")[2])
    raise AssertionError(f"no /RBODY for part {part}")


def _surf_parts(starter: str, title: str):
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/SURF/PART/EXT/") and lines[i + 1] == title:
            return [int(t) for t in lines[i + 2].split()]
    raise AssertionError(f"no surface titled {title}")


class JointScrewGjoint(unittest.TestCase):
    """B2 — a *CONSTRAINED_JOINT_SCREW between two *MAT_RIGID bodies on a
    global axis -> /GJOINT/RACK on a synthesized carriage, the bodies' CMO
    /BCS and drive re-written as /BCS/LAGMUL + /IMPVEL/LAGMUL, the rigid pair
    split out of the all-parts self-contact; anything else keeps the 65ff389
    skip with a named reason."""

    def test_the_rack_card(self):
        _r, s, _e = _convert(_screw_deck())
        a_main, b_main = _rbody_main(s, 2), _rbody_main(s, 1)
        rack = [ln for ln in _block_after(s, "/GJOINT/RACK/", 10)
                if not ln.startswith("#")]
        self.assertEqual(rack[1], "SCREW_9")
        row0 = rack[2]
        self.assertEqual(row0[10:30], "               -0.04")
        self.assertEqual(row0[30:70], "                   0" * 2)
        self.assertEqual((int(row0[70:80]), int(row0[80:90]),
                          int(row0[90:100])), (a_main, b_main, 0))
        axis = ("                   0                   0                   1"
                "                   0                   0")
        self.assertEqual(rack[3:5], [axis, axis])
        self.assertEqual(rack[5], "                   0" * 5)
        self.assertEqual(s.count("/GJOINT/RACK/"), 1)

    def test_the_carriage(self):
        r, s, _e = _convert(_screw_deck())
        rack = [ln for ln in _block_after(s, "/GJOINT/RACK/", 6)
                if not ln.startswith("#")]
        n0 = int(rack[2][0:10])
        body = _block_after(s, f"/RBODY/{n0}", 9)
        self.assertEqual(body[1], "SCREW_9_CARRIAGE")
        # node_ID sens skew Ispher (4 x 10) | Mass (20) | grnd Ikrem ICoG surf
        self.assertEqual(body[3][40:60], "        1.000000E-06")   # Mass
        self.assertEqual(int(body[3][80:90]), 3)                  # ICoG
        self.assertEqual(body[5], "        1.000000E-06" * 3)
        g = int(body[3][60:70])
        grp = _block_after(s, f"/GRNOD/NODE/{g}", 3)
        self.assertEqual(grp[1], "SCREW_9_carriage_secondaries")
        n1, n2 = (int(t) for t in grp[2].split())
        st = _dispatch(_screw_deck())
        from k2rad.writer.assembly import build_starter
        build_starter(st)
        self.assertEqual([(st.nodes[n].x, st.nodes[n].y, st.nodes[n].z)
                          for n in (n0, n1, n2)],
                         [(15.0, 5.0, 5.0), (15.0, 6.0, 5.0),
                          (15.0, 5.0, 6.0)])
        self.assertIn(n0, st.rbody_ids)
        self.assertTrue(_has(r.warnings, "a synthesized carriage /RBODY/"))

    def test_the_two_BCS_LAGMUL(self):
        _r, s, _e = _convert(_screw_deck())
        lag = [_block_after(s, ln, 4) for ln in s.splitlines()
               if ln.startswith("/BCS/LAGMUL/")]
        self.assertEqual(len(lag), 2)
        rows = {b[1]: b[3] for b in lag}
        car = rows["SCREW_9_carriage"]
        self.assertEqual(car[:20], "   011 111         0")
        a_ind = [ln for ln in s.splitlines()]
        a_grp = next(int(a_ind[i].split("/")[3]) for i in range(len(a_ind))
                     if a_ind[i].startswith("/GRNOD/NODE/")
                     and a_ind[i + 1] == "rb_indnode_pid2")
        self.assertEqual(rows["SCREW_9_body_A"],
                         f"   000 011         0{a_grp:>10}")
        self.assertNotIn("BC_rigid_1", s)
        self.assertNotIn("BC_rigid_2", s)
        self.assertNotIn("/IMPDISP/", s)

    def test_the_differentiated_drive(self):
        _r, s, _e = _convert(_screw_deck())
        imp = _block_after(s, "/IMPVEL/LAGMUL/", 6)
        fid = int(imp[3][0:10])
        self.assertEqual(imp[3][10:20], "        XX")
        self.assertEqual(imp[5], "                   1                   1")
        fn = _block_after(s, f"/FUNCT/{fid}", 12)
        self.assertEqual(fn[1], "SCREW_9_dTHETA_dt_7")
        rows = [ln for ln in fn[3:11] if not ln.startswith("#")]
        self.assertEqual(rows, [
            "                   0         166.6666667",
            "                0.03         166.6666667",
            "           0.0300001                   0",
            "                0.06                   0",
            "           0.0600001                 250",
            "                 0.1                 250",
            "           0.1000001                 170",
            "                 0.6                 170"])
        self.assertTrue(fn[11].startswith("#---"), fn)   # exactly 8 rows
        # VAD 0: the deck's own velocity curve, no new /FUNCT
        _r0, s0, _e0 = _convert(_screw_deck(vad=0))
        imp0 = _block_after(s0, "/IMPVEL/LAGMUL/", 6)
        self.assertEqual(int(imp0[3][0:10]), 7)
        self.assertNotIn("dTHETA_dt", s0)
        # SF 2: Fscale_y, the points unchanged
        _r2, s2, _e2 = _convert(_screw_deck(sf=2.0))
        imp2 = _block_after(s2, "/IMPVEL/LAGMUL/", 6)
        self.assertEqual(imp2[5], "                   1                   2")
        fid2 = int(imp2[3][0:10])
        self.assertEqual(_block_after(s2, f"/FUNCT/{fid2}", 5)[3:5],
                         rows[:2])

    def test_the_derivative_merges_equal_slopes(self):
        from k2rad.writer.joint_screw import screw_drive_derivative
        out = screw_drive_derivative(_SCREW_CURVE)
        self.assertEqual(len(out), 8)
        self.assertAlmostEqual(out[0][1], 1.0 / 0.006)
        self.assertEqual([round(x, 9) for x, _y in out],
                         [0.0, 0.03, 0.0300001, 0.06, 0.0600001, 0.1,
                          0.1000001, 0.6])

    def test_the_split(self):
        _r, s, _e = _convert(_screw_deck())
        self.assertEqual(_surf_parts(s, "contact_90001_self"), [1, 3])
        self.assertEqual(_surf_parts(s, "contact_90001_screw_9_rest"), [3])
        self.assertEqual(_surf_parts(s, "contact_90001_screw_9_body_A"), [2])
        lines = s.splitlines()
        inters = [i for i, ln in enumerate(lines)
                  if ln.startswith("/INTER/TYPE25/")]
        self.assertEqual(len(inters), 2)
        a = lines[inters[0]:inters[0] + 15]
        b = lines[inters[1]:inters[1] + 15]
        self.assertEqual(b[1], "CONTACT_90001_screw_9_body_A")
        for k, (x, y) in enumerate(zip(a, b)):
            if k in (0, 1):
                continue
            if k == 3:
                self.assertEqual(x[20:], y[20:])
                self.assertNotEqual(int(y[10:20]), 0)
                continue
            self.assertEqual(x, y)

    def test_the_keyword_leaves_the_skip_bucket(self):
        r, s, _e = _convert(_screw_deck())
        self.assertNotIn("CONSTRAINED_JOINT_SCREW", r.skipped_keywords)
        self.assertNotIn("#-- SKIPPED: *CONSTRAINED_JOINT_SCREW", s)
        self.assertTrue(_has(r.warnings, "*CONSTRAINED_JOINT_SCREW 9 -> "
                             "/GJOINT/RACK/", "-1/PARM = -0.04",
                             "NSPMD > 1", "185.70", "183.59"), r.warnings)
        self.assertTrue(_has(r.warnings, "the rigid pair of "
                             "*CONSTRAINED_JOINT_SCREW 9 is split out",
                             "resol.F:7572", "178.67 mm"), r.warnings)

    def test_every_refusal_class_keeps_the_65ff389_bytes(self):
        cases = (
            ("_COOR_SCREW", {"keyword": "*CONSTRAINED_JOINT_COOR_SCREW_ID"},
             "_COOR_SCREW / _LOCAL / _FAILURE spelling"),
            ("_LOCAL", {"keyword": "*CONSTRAINED_JOINT_SCREW_LOCAL_ID"},
             "_COOR_SCREW / _LOCAL / _FAILURE spelling"),
            ("_FAILURE", {"keyword": "*CONSTRAINED_JOINT_SCREW_FAILURE_ID"},
             "_COOR_SCREW / _LOCAL / _FAILURE spelling"),
            ("implicit", {"implicit": True}, "the deck is implicit"),
            ("PARM 0", {"parm": 0.0}, "PARM is 0"),
            ("N5 on the plate", {"n5_on_plate": True},
             "not on two different rigid parts"),
            ("A deformable under a CNRB", {"a_elastic_cnrb": True},
             "is not a *MAT_RIGID part"),
            # the validation round: A stays *MAT_RIGID, so only the
            # shared-node arm of refusal 5 can fire (mutation B2-9)
            ("A rigid, its nodes in a CNRB", {"a_rigid_cnrb": True},
             "part 2 shares nodes with a *CONSTRAINED_NODAL_RIGID_BODY"),
            # refusal 11: a standard condition on either body
            ("a *NODE TC on A", {"a_node_tc": 3},
             "body A (part 2) carries the *NODE TC 3 / RC 0 of its node 3"),
            ("a *BOUNDARY_SPC on B", {"b_spc": True},
             "body B (part 1) carries the *BOUNDARY_SPC (/BCS/"),
            ("a *CONSTRAINED_GLOBAL plane through B", {"b_global": True},
             "body B (part 1) carries a *CONSTRAINED_GLOBAL plane through "
             "its node 9"),
            ("a nodal prescribed motion on A", {"a_node_motion": True},
             "body A (part 2) carries a *BOUNDARY_PRESCRIBED_MOTION_NODE / "
             "_SET on its node 3"),
            ("N2 off the axis", {"n2_off_axis": True}, "are not coaxial"),
            ("diagonal axis", {"diagonal": True},
             "is not along a global axis"),
            ("A's CON2 7", {"con2_a": 7},
             "constraints are not the screw's own"),
            ("a drive on B", {"drive_on_b": True}, "is driven too"),
            ("VAD 1", {"vad": 1}, "VAD 1 is not converted"),
            # VAD 3 never reaches state.prescribed_motions (the handler
            # refuses it by name, _pm_vad_supported): the screw has no drive
            ("VAD 3", {"vad": 3}, "a VAD 3 / 4 card is not converted at all"),
            ("a birth window", {"birth": 0.01}, "has a time window"),
            ("no drive", {"drive": False}, "there is none"),
            ("an unsplittable contact", {"s2s": True},
             "which the split does not handle"),
        )
        for name, kw, reason in cases:
            with self.subTest(case=name):
                deck = _screw_deck(**kw)
                r_on, s_on, e_on = _convert(deck)
                _r_off, s_off, e_off = _convert(deck, joint_screw_gjoint=False)
                self.assertEqual(s_on, s_off)
                self.assertEqual(e_on, e_off)
                self.assertNotIn("/GJOINT/", s_on)
                hits = [w for w in r_on.warnings if ": NOT converted - " in w
                        and "SCREW" in w]
                self.assertEqual(len(hits), 1, r_on.warnings)
                self.assertIn(reason, hits[0])

    def test_refusal_11_mirrors_what_is_written(self):
        """A *NODE TC cell that --no-node-tc-rc-bcs drops is written
        nowhere, so it conflicts with nothing: the screw converts. The
        refused arm's member code is then merged by A1 into the body's own
        BC_rigid card (no node_tc_rc group of its own)."""
        r, s, _e = _convert(_screw_deck(a_node_tc=3), node_tc_rc_bcs=False)
        self.assertIn("/GJOINT/RACK/", s)
        self.assertFalse(_has(r.warnings, ": NOT converted - "), r.warnings)
        r1, s1, _e1 = _convert(_screw_deck(a_node_tc=3))
        self.assertNotIn("/GJOINT/RACK/", s1)
        self.assertIn("BC_rigid_2", s1)
        self.assertNotIn("node_tc_rc_", s1)

    def test_the_A1_record_mirrors_the_written_cards(self):
        """A1's state.rigid_auto_bcs records exactly the BC_rigid cards the
        /RBODY producer writes (ONE predicate, screw_cmo_skip_pids, gates
        both): a record without its card would merge a member TC/RC code
        into a card that never reaches the deck. The code validator's
        mutation A1-5b kept the record and dropped the card on the screw
        bodies, and the whole suite stayed green."""
        from k2rad.writer.assembly import build_starter
        for on, want in ((True, set()),
                         (False, {"BC_rigid_1", "BC_rigid_2"})):
            with self.subTest(joint_screw_gjoint=on):
                st = _dispatch(_screw_deck())
                st.options.joint_screw_gjoint = on
                s = build_starter(st)
                written = set(re.findall(r"^/BCS/\d+\r?\n(BC_rigid_\d+)\r?$",
                                         s, re.M))
                recorded = {t.strip() for _tra, _rot, title
                            in st.rigid_auto_bcs.values()
                            for t in title.split(",")}
                self.assertEqual(written, want)
                self.assertEqual(recorded, written)

    def test_the_opt_out_restores_65ff389(self):
        r, s, _e = _convert(_screw_deck(), joint_screw_gjoint=False)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_JOINT_SCREW", s)
        self.assertIn("BC_rigid_1", s)
        self.assertIn("BC_rigid_2", s)
        self.assertIn("/IMPDISP/1", s)
        self.assertEqual(_surf_parts(s, "contact_90001_self"), [1, 2, 3])
        for absent in ("/GJOINT/", "/BCS/LAGMUL/", "/IMPVEL/LAGMUL/",
                       "SCREW_9_CARRIAGE"):
            self.assertNotIn(absent, s)
        self.assertTrue(_has(r.warnings, "--no-joint-screw-gjoint: 1 "
                             "*CONSTRAINED_JOINT_SCREW card(s) left "
                             "unconverted"), r.warnings)

    def test_bndout_names_the_lagmul_drive_instead_of_no_drive(self):
        # The /IMPVEL/LAGMUL drive registers no BNDOUT node (a Lagrange
        # drive has no REAC*), so the old "drives no node" sentence would be
        # false: the deck does drive one. Found by the part-B sweep on
        # EXP_SC_JOINT_SCREW.
        r, s, _e = _convert(_screw_deck(bndout=True))
        self.assertNotIn("TH_NODE_BNDOUT", s)
        hits = [w for w in r.warnings if w.startswith("*DATABASE_BNDOUT")]
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("1 *BOUNDARY_PRESCRIBED_MOTION_RIGID drive(s) of a "
                      "converted *CONSTRAINED_JOINT_SCREW are written as "
                      "/IMPVEL/LAGMUL", hits[0])
        self.assertIn("thbcs.F:62 / :77", hits[0])
        self.assertFalse(_has(r.warnings, "drives no node"), r.warnings)
        # the opt-out keeps the /IMPDISP, so its channel comes back
        r0, s0, _e0 = _convert(_screw_deck(bndout=True),
                               joint_screw_gjoint=False)
        self.assertIn("TH_NODE_BNDOUT", s0)
        self.assertFalse(_has(r0.warnings, "/IMPVEL/LAGMUL and are NOT"),
                         r0.warnings)

    def test_the_axis_sign_is_immaterial(self):
        _r, s, _e = _convert(_screw_deck())
        _r2, s2, _e2 = _convert(_screw_deck(swap_axis=True))
        a, b = s.splitlines(), s2.splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        neg = ("                   0                   0                  -1"
               "                   0                   0")
        pos = ("                   0                   0                   1"
               "                   0                   0")
        self.assertEqual(diff, [(pos, neg), (pos, neg)])

    def test_the_F_deck(self):
        path = ("F:/dynaexamples_r14_ton-mm-s/show-cases/joint-screw/"
                "EXP_SC_JOINT_SCREW.k")
        if not os.path.isfile(path):
            self.skipTest("F: corpus not mounted")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        res = convert(path, output_stem=os.path.join(tmp.name, "scr"),
                      write_log=False)
        with open(res.starter_path) as fh:
            s = fh.read()
        rack = [ln for ln in _block_after(s, "/GJOINT/RACK/", 6)
                if not ln.startswith("#")]
        self.assertEqual(rack[2][10:30], "               -0.04")
        self.assertEqual((int(rack[2][70:80]), int(rack[2][80:90])),
                         (10059663, 10059662))
        self.assertEqual(_surf_parts(s, "contact_90001_self"),
                         [1000000, 1000001, 1000002, 1000003, 1000004,
                          1000005, 1000006, 1000007, 10000045])
        self.assertEqual(_surf_parts(s, "contact_90001_screw_9000002_rest"),
                         [1000000, 1000001, 1000002, 1000003, 1000004,
                          1000005, 1000006, 1000007])
        self.assertEqual(
            _surf_parts(s, "contact_90001_screw_9000002_body_A"), [10000046])
        self.assertIn("SCREW_9000002_dTHETA_dt_10000007", s)


# ═════════════════════════════════════════════════════════════════════════════
# The flags of part B reach the parser, the API, the GUI and the README
# ═════════════════════════════════════════════════════════════════════════════

class Round7FlagWiringB(Round7FlagWiringA):
    """Every new Part-B lever reaches the parser, the API, the GUI and the
    README - the ``Round7FlagWiringA`` checks, inherited, over part B's
    list."""

    _FLAGS = {
        "--corotational-orthotropic": "corotational_orthotropic",
        "--mat-null-pc-mu": "mat_null_pc_mu",
        "--joint-screw-gjoint": "joint_screw_gjoint",
    }
    _HELP_FIGURES = {
        "--joint-screw-gjoint": ("-1/PARM", "185.70", "183.59", "0.9998x"),
        "--corotational-orthotropic": ("6.0047", "1.5049",
                                       "smorth3.F:324-327", "0.164 %"),
        "--mat-null-pc-mu": ("hm_read_mat06.F:154", "m6law.F:98", "+4.50 %",
                             "-0.09 %", "0.832x"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Retracted spellings (part B): measured wrong, or superseded by a measurement
# ═════════════════════════════════════════════════════════════════════════════

#: Part B statements a round-7 change made false. CHANGELOG may quote them
#: (it is the history); no other shipped text may.
_RETRACTED_ROUND_7_B = (
    # B3: the honeycomb TYPE6 is written co-rotational since round 7
    "The card is left as dyna2rad writes it, because the honeycomb's crush "
    "under a co-rotational frame has no LS-DYNA reference here",
    "the point/vector modes 21 / 24 take GLOBAL directions and are not in "
    "the set",
    "it is NOT changed (its crush under a co-rotational frame has no "
    "reference here)",
    # B1: the *MAT_NULL PC / MU cells are carried since round 7
    "Only the ELFORM-12 void cavitation floor passes a value",
    "MU (field 4) stays unread",
    "it is mapped nowhere else (see ROADMAP, the *MAT_NULL PC/MU item)",
    "--no-initial-void-floor to keep Pmin 0",
    "*INITIAL_VOID fluids keep Pmin 0",
    # B2: the screw has its own route since round 7
    "rack-and-pinion / pulley / screw / constant-velocity joints have no "
    "OpenRadioss counterpart",
)

#: The README spells the cell with backticks; one regex for both spellings.
_RETRACTED_ROUND_7_B_RE = (r"\*MAT_NULL`? PC cell is not carried",)


class Round7RetractedStatementsB(unittest.TestCase):
    """The round-4/5/6 shape: no needle in any shipped text; the guard fires
    on each needle split across two adjacent literals; a PREFIX still fires;
    the replacement text IS shipped."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_7_B:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle).lower(),
                                     joined.lower())
            for pattern in _RETRACTED_ROUND_7_B_RE:
                with self.subTest(file=rel, pattern=pattern):
                    self.assertIsNone(re.search(pattern, joined), rel)

    def test_the_regex_fires_on_both_spellings(self):
        for pattern in _RETRACTED_ROUND_7_B_RE:
            for text in ("(the *MAT_NULL PC cell is not carried)",
                         "(the `*MAT_NULL` PC cell is not carried)"):
                with self.subTest(pattern=pattern, text=text):
                    self.assertIsNotNone(re.search(pattern, _collapse(
                        re.sub(r'"\s*\n\s*"', "", text))))

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_7_B:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "') + ' y')
                self.assertIn(_collapse(needle).lower(), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_7_B:
            with self.subTest(needle=needle):
                self.assertIn(_collapse(needle[:max(8, len(needle) // 2)]),
                              _collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_SHIPPED_TEXTS())
        pairs = (
            ("k2rad/writer/composites.py",
             "so the pinned Isolid 1 property is written CO-ROTATIONAL "
             "(Iframe 2)"),
            ("k2rad/writer/composites.py",
             "_ELEMENT_FRAME_IPS_ALL = (20, 21, 23, 24)"),
            ("README.md", "Since round 7 every element-frame orthotropic "
             "`/PROP/TYPE6` is written CO-ROTATIONAL"),
            ("k2rad/writer/materials.py", "Two callers' values: the "
             "ELFORM-12 void cavitation floor"),
            ("k2rad/writer/materials.py", "carry the *MAT_NULL PC cell "
             "instead: "),
            ("k2rad/writer/materials.py", "--no-initial-void-floor to fall "
             "back to the *MAT_NULL PC cell"),
            ("k2rad/handlers.py", "# PC / MU / TEROD / CEROD: card 1 fields "
             "3-6."),
            ("k2rad/cli.py", "Use --no-initial-void-floor to fall back to "
             "the *MAT_NULL PC cell"),
            ("k2rad_gui.py", "*INITIAL_VOID fluids get no cavitation floor"),
            ("README.md", "before round 7 the `*MAT_NULL` PC cell was not "
             "carried"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])


# ── B6: the round's record (CHANGELOG re-sums, ROADMAP completeness) ─────────

_ROOT7 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read7(rel: str) -> str:
    with open(os.path.join(_ROOT7, rel), encoding="utf-8") as fh:
        return fh.read()


def _md_cells(row: str) -> int:
    """The unescaped pipes of a Markdown table row (a ``\\|`` inside a code
    span is not a cell border)."""
    return len(re.findall(r"(?<!\\)\|", row))


class Round7ChangelogReSums(unittest.TestCase):
    """B6.6 — the "re-add every headline total" rule (rounds 5 and 6): the
    round-7 header bullet's byte-mover counts must add up (the halves are
    disjoint, so part A + part B = the round; B1 + B2 = part B; B3, B4 and
    B5 move nothing) and equal the two-tree sweeps' labelled totals: part A
    70 / 61 (its sweep at 564d179), part B 21 / 18 (0c82dbe against part A's
    head), 91 / 79 against 65ff389."""

    def _head(self) -> str:
        text = _collapse(_read7("CHANGELOG.md"))
        i = text.index("- **R14 CAMPAIGN TRIAGE batch, round 7** —")
        j = text.index("- **R14 CAMPAIGN TRIAGE batch, round 7 — PART B", i)
        return text[i:j]

    def test_the_halves_add_up_to_the_round(self):
        m = re.search(
            r"part A (\d+) deck keys / (\d+) emitted models, part B (\d+) / "
            r"(\d+) \(B1 (\d+) / (\d+), B2 (\d+) / (\d+); B3, B4 and B5 0\), "
            r"round 7 (\d+) / (\d+) against 65ff389", self._head())
        self.assertIsNotNone(m, self._head())
        a_k, a_m, b_k, b_m, b1_k, b1_m, b2_k, b2_m, r_k, r_m = map(
            int, m.groups())
        self.assertEqual((b1_k + b2_k, b1_m + b2_m), (b_k, b_m))
        self.assertEqual((a_k + b_k, a_m + b_m), (r_k, r_m))
        self.assertEqual((a_k, a_m, b_k, b_m, r_k, r_m),
                         (70, 61, 21, 18, 91, 79))

    def test_the_item_entries_state_the_same_counts(self):
        text = _collapse(_read7("CHANGELOG.md"))
        self.assertIn("Byte movers 20 keys / 17 models (the 3 Nu keys among "
                      "them", text)
        self.assertIn("Reach 1 deck key on 1 emitted model. Tests: "
                      "`JointScrewGjoint`", text)
        roadmap = _collapse(_read7("ROADMAP.md"))
        self.assertIn("70 / 61 + 21 / 18 = 91 deck keys / 79 emitted models "
                      "against 65ff389", roadmap)


class Round7RoadmapRecord(unittest.TestCase):
    """B6.3 — the ROADMAP record of round 7 is complete: a round-7 column in
    the R14 defect-queue table and in the implicit residue table (every row
    as wide as its header), the `tire.k` residue row, one ``**Round 7:**``
    line on each of the 27 round-6 items, the round-7 NOT list numbered 1-22
    with no unfilled placeholder, and the residue restated with its rule."""

    @classmethod
    def setUpClass(cls):
        cls.lines = _read7("ROADMAP.md").splitlines()

    def _at(self, prefix: str) -> int:
        hits = [k for k, ln in enumerate(self.lines) if ln.startswith(prefix)]
        self.assertEqual(len(hits), 1, prefix)
        return hits[0]

    def _table(self, header_prefix: str):
        rows = []
        for ln in self.lines[self._at(header_prefix):]:
            if not ln.startswith("|"):
                break
            rows.append(ln)
        return rows

    def _same_width(self, rows):
        width = _md_cells(rows[0])
        for r in rows[1:]:
            with self.subTest(row=r[:48]):
                self.assertEqual(_md_cells(r), width)

    def test_the_queue_table_has_a_round_7_column(self):
        rows = self._table("| # | class | decks | closed by round 1 |")
        self.assertTrue(rows[0].endswith("| round 6 | round 7 |"), rows[0])
        self.assertEqual(len(rows), 10)          # header, separator, 8 rows
        self._same_width(rows)

    def test_the_residue_table_has_a_round_7_column_and_the_tire_row(self):
        rows = self._table("| family | decks | death | verdict after round 3 |")
        self.assertTrue(rows[0].endswith("| round 6 | round 7 |"), rows[0])
        self.assertEqual(len(rows), 18)          # 15 families + tire.k
        self._same_width(rows)
        tire = [r for r in rows if r.startswith("| `eigenvalue/tire.k`")]
        self.assertEqual(len(tire), 1)
        self.assertIn("STOPPED DUE TO LOADING DATA", tire[0])
        text = _collapse("\n".join(self.lines))
        self.assertIn("the residue is the set of `/IMPL` emitters that are "
                      "NOT `normal` — **32 keys / 30 models at 65ff389**", text)
        self.assertIn("after A4, **29 keys / 29 models**", text)

    def test_every_round_6_item_carries_one_round_7_line(self):
        s = self._at("**What round 6 deliberately does NOT close**")
        e = self._at("**What round 7 closes, and what it does NOT.**")
        starts = [k for k in range(s, e)
                  if re.match(r"^\d+\. \*\*", self.lines[k])]
        self.assertEqual(len(starts), 27)
        for n, (a, b) in enumerate(zip(starts, starts[1:] + [e]), 1):
            with self.subTest(item=n):
                self.assertTrue(self.lines[a].startswith(f"{n}. **"))
                self.assertEqual(
                    sum("**Round 7:**" in ln for ln in self.lines[a:b]), 1)

    def test_the_round_7_not_list_is_numbered_1_to_22(self):
        s = self._at("**What round 7 deliberately does NOT close**")
        e = self._at("**52 of the 59 starter failures.**")
        nums = [int(m.group(1)) for m in
                (re.match(r"^(\d+)\. \*\*", ln) for ln in self.lines[s:e])
                if m]
        self.assertEqual(nums, list(range(1, 23)))
        self.assertNotRegex("\n".join(self.lines[s:e]), r"<[a-z_ ]+>")


if __name__ == "__main__":
    unittest.main()
