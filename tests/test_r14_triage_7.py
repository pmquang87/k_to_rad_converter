"""Tests for the R14 CAMPAIGN TRIAGE batch, round 7 — PART A:

  A1  the double-/BCS merge: a *NODE TC/RC (or *CONSTRAINED_GLOBAL) code
      re-pointed onto an /RBODY main node is MERGED into the /BCS the rigid
      body itself writes there (BC_rigid_<pid>, BC_cnrb_<pid> at skew 0)
      instead of being written a second time (inside --no-node-tc-rc-bcs /
      --no-constrained-global, no flag of its own)

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are the round-4/5/6 ones, copied (not imported) so this
module runs on its own.
"""

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


if __name__ == "__main__":
    unittest.main()
