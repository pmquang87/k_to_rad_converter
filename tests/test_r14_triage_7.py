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


if __name__ == "__main__":
    unittest.main()
