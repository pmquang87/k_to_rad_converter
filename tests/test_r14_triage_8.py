"""Tests for the R14 CAMPAIGN TRIAGE batch, round 8 — PART A:

  A1  *MAT_RIGID CMO -1 -> /BCS in the /SKEW of CON1, one skew per node
      (default ON, --no-rigid-local-constraints)
  A3  the non-rigid double /BCS union: P1 BC_n + BC_n, P2 BC_n + the
      free-node guard, P3 the guard + *NODE TC/RC (default ON, --no-bcs-union)
  A2  mainboltaexpl: the bolt-end rigid members stay on the penalty secondary
      sides (--no-bolt-rigid-contact) + the fixed 2E20.0 *DEFINE_CURVE read
      (--no-fixed-curve-columns)
  A4  *SECTION_SHELL Card 2 T1..T4 -> their mean, with its named energy-error
      cost (--no-section-nodal-thickness-mean)
  A7  plane-strain ELFORM 13 / 43 / 52 / 55 -> thickness 1.0, axisymmetric
      named (--no-plane-strain-unit-thickness)
  A8  *ELEMENT_MASS on a rigid SECONDARY node -> /ADMAS on that node, both
      producers (--no-rigid-element-mass-admas)
  A6  *MAT_SPOTWELD DT -> the TYPE13 Mass / Inertia closed form
      (--no-spotweld-dt-mass-scaling)
  A5  the adaptive spring token MASS with the driven-end skip
      (--no-adaptive-spring-token)
  A9  the records (the merge probe's starter echo) and the part-A guards:
      the nine flags' wiring and the retracted spellings

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_5.py / _6.py / _7.py
(functions and deck constants only, so no earlier TestCase runs twice).

Every byte-pinning probe deck below was run through the OpenRadioss starter
once (nt 4, C:/Users/pmqua/rcv_r8i_implA_<name>, harvested and deleted); the
named outcome is recorded in the test's docstring.
"""

import hashlib
import math
import os
import re
import unittest
from typing import Dict, List, Set, Tuple

import test_r14_triage_5 as _t5
import test_r14_triage_6 as _t6
import test_r14_triage_7 as _t7

_row = _t7._row
_convert = _t7._convert
_dispatch = _t7._dispatch
_has = _t7._has
_bcs_groups = _t7._bcs_groups
_a1_deck = _t7._a1_deck
_node_warning = _t7._node_warning


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bcs_card(starter: str, title: str):
    """``(Tra, Rot, skew_ID, grnod_ID)`` of the ``/BCS`` titled *title*, or
    None."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/BCS/") and lines[i + 1] == title:
            d = lines[i + 3].split()
            return d[0], d[1], int(d[2]), int(d[3])
    return None


def _skew_fix(starter: str, sid: int):
    """``(title, origin, Y', Z')`` of ``/SKEW/FIX/<sid>``, or None."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln == f"/SKEW/FIX/{sid}":
            vals = [[float(x) for x in lines[i + k].split()] for k in (3, 5, 7)]
            return lines[i + 1], tuple(vals[0]), tuple(vals[1]), tuple(vals[2])
    return None


# ═════════════════════════════════════════════════════════════════════════════
# A1 — *MAT_RIGID CMO -1 -> /BCS in the /SKEW of CON1
# ═════════════════════════════════════════════════════════════════════════════

_VEC3 = ("*DEFINE_COORDINATE_VECTOR\n"
         + _row(3, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0) + "\n")
_SYS5 = ("*DEFINE_COORDINATE_SYSTEM\n" + _row(5, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
         + "\n" + _row(0.0, 1.0, 0.0) + "\n")


def _nod7(flag: int) -> str:
    """*DEFINE_COORDINATE_NODES 7 on the rigid plate's nodes 1 (0, 0, 0),
    3 (20, 0, 0) and 7 (0, 20, 0): X' = x, Y' = y, Z' = z."""
    return "*DEFINE_COORDINATE_NODES\n" + _row(7, 1, 3, 7, flag) + "\n"


def _cmo(con1, con2, extra="", tc=0, cmo=-1.0, **kw) -> str:
    return _a1_deck(cmo=cmo, con1=con1, con2=con2, tc=tc, extra=extra, **kw)


_W1 = "written as /BCS/"
_W5_1051 = "ERROR 1051"
_W5_137 = "ERROR 137"
_W7 = "were DROPPED: the starter accepts ONE skew per node"

# The g3p pre-research coupon (PREV8/r8pre/g3p/coupon/cmo_coupon.k): a rigid
# hex cube and a rigid shell plate, both CMO -1 in one oblique frame cid 5
# (e1 = (1,2,2)/3, e2 = (2,1,-2)/3, e3 = (-2,2,-1)/3). Measured there (nt 4,
# nine arms): every digit on its own skew axis within 0.04 % of the closed
# form; the branch's emission is pinned below.
_CMO_COUPON = """*KEYWORD
*TITLE
g3p CMO -1 coupon: rigid cube (hex) + rigid plate (shell), oblique local frame
*CONTROL_TERMINATION
      0.01         0       0.0       0.0       0.0
*DATABASE_GLSTAT
    1.0E-4         0         0         1
*DEFINE_COORDINATE_SYSTEM
         5       0.0       0.0       0.0       3.0       6.0       6.0         0
       6.0       3.0      -6.0
*PART
cube
         1         1         1         0         0         0         0         0
*SECTION_SOLID
         1         1         0
*MAT_RIGID
         1   7.85E-9  210000.0       0.3       0.0       0.0       0.0
      -1.0         5    100000         0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0         0
*PART
plate
         2         2         2         0         0         0         0         0
*SECTION_SHELL
         2         2       1.0         2       1.0
       1.0       1.0       1.0       1.0
*MAT_RIGID
         2   7.85E-9  210000.0       0.3       0.0       0.0       0.0
      -1.0         5    100111         0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0         0
*DEFINE_CURVE
         1         0       1.0       1.0
                 0.0                 1.0
                 1.0                 1.0
*LOAD_BODY_X
         1    1000.0
*LOAD_BODY_Y
         1    2000.0
*LOAD_BODY_Z
         1    3000.0
*LOAD_RIGID_BODY
         1         5         1       3.0
         1         6         1       1.0
         1         7         1       2.0
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             0.0             0.0            10.0
       6            10.0             0.0            10.0
       7            10.0            10.0            10.0
       8             0.0            10.0            10.0
      11             0.0             0.0            50.0
      12            10.0             0.0            50.0
      13            10.0            10.0            50.0
      14             0.0            10.0            50.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
*ELEMENT_SHELL
       2       2      11      12      13      14
*END
"""


def _merge_deck(mid2_code=None) -> str:
    """Two *MAT_RIGID plates merged by *CONSTRAINED_RIGID_BODIES 1 2: part 1
    on mid 1 (CMO -1 CON1 5 CON2 010000); part 2 on its own mid 3 with
    *mid2_code* (CMO, CON1, CON2), or on mid 1 too when None."""
    deck = _cmo(5, 10000, extra=_SYS5 + "*CONSTRAINED_RIGID_BODIES\n"
                + _row(1, 2) + "\n")
    if mid2_code is None:
        return deck.replace("*PART\nelastic plate\n" + _row(2, 1, 2),
                            "*PART\nrigid plate 2\n" + _row(2, 1, 1))
    cmo, c1, c2 = mid2_code
    mat3 = ("*MAT_RIGID\n" + _row(3, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0)
            + "\n" + f"{cmo:10.1f}{c1:10d}{c2:10d}\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
    return deck.replace("*PART\nelastic plate\n" + _row(2, 1, 2),
                        "*PART\nrigid plate 2\n" + _row(2, 1, 3)).replace(
        "*MAT_ELASTIC", mat3 + "*MAT_ELASTIC")


class RigidLocalConstraints(unittest.TestCase):
    """A1 (round 8): a *MAT_RIGID CMO -1 card was written as NOTHING
    (rbody.py read CON1 / CON2 only for CMO +1). Vol II R17 *MAT_RIGID: CMO
    -1 makes CON1 the local system ("fixed in time") and CON2 a six-digit
    code; the starter reads the digits as axes of the /BCS skew
    (bcs.cfg:98, hm_read_bcs.F:164-185). The rigid plate's synthesized main
    node is 19 in every probe (round 7's _a1_deck).

    Starter runs of the byte-pinning probes (nt 4, run dirs
    rcv_r8i_implA_a1_<x>, harvested into implA_out/runs/): see each test."""

    def _rb(self, deck, **kw):
        res, starter, _e = _convert(deck, **kw)
        return res, starter, _bcs_card(starter, "BC_rigid_1")

    def test_a_vector_frame(self):
        """(a) CON1 3 = *DEFINE_COORDINATE_VECTOR (x (1,0,1), v (0,0,1)),
        CON2 100111, LCO 0. Starter (a1_a): 0 errors."""
        res, starter, card = self._rb(_cmo(3, 100111, _VEC3))
        self.assertEqual(card[:3], ("100", "111", 3))
        self.assertIn("   100 111         3", starter)
        self.assertIn("/SKEW/FIX/3\n", starter)
        self.assertTrue(_has(res.warnings, _W1, "in /SKEW/3", "(VECTOR)",
                             "not LCO", "+100.10 -> +0.05 %"), res.warnings)
        from k2rad.writer.rbody import _make_rbodies
        st = _dispatch(_cmo(3, 100111, _VEC3))
        _make_rbodies(st)
        self.assertEqual(st.rigid_skewed_bcs,
                         {19: [("100", "111", 3, "BC_rigid_1")]})
        self.assertEqual(st.rigid_auto_bcs, {})
        self.assertEqual(st.rigid_auto_cmo_neg, set())

    def test_b_system_frame(self):
        """(b) CON1 5 = *DEFINE_COORDINATE_SYSTEM, CON2 100000. Starter
        (a1_b): 0 errors."""
        _res, starter, card = self._rb(_cmo(5, 100000, _SYS5))
        self.assertEqual(card[:3], ("100", "000", 5))
        self.assertIn("   100 000         5", starter)

    def test_c_nodes_flag0_frame(self):
        """(c) CON1 7 = *DEFINE_COORDINATE_NODES FLAG 0, CON2 011111."""
        res, starter, card = self._rb(_cmo(7, 11111, _nod7(0)))
        self.assertEqual(card[:3], ("011", "111", 7))
        self.assertIn("   011 111         7", starter)
        self.assertTrue(_has(res.warnings, _W1, "(NODES FLAG 0)"))

    def test_d_nodes_flag1_frame_gets_a_t0_skew(self):
        """(d) FLAG 1 is the co-rotating /SKEW/MOV/7; the CMO -1 frame is
        fixed in time, so the code goes into a NEW /SKEW/FIX at the t = 0
        axes (decision D2). Starter (a1_d): 0 errors."""
        res, starter, card = self._rb(_cmo(7, 100000, _nod7(1)))
        sid = card[2]
        self.assertNotIn(sid, (0, 7))
        self.assertEqual(card[:2], ("100", "000"))
        title, origin, y, z = _skew_fix(starter, sid)
        self.assertEqual(title, "SKEW_CON1_T0_7")
        self.assertEqual(origin, (0.0, 0.0, 0.0))
        self.assertEqual(y, (0.0, 1.0, 0.0))
        self.assertEqual(z, (0.0, 0.0, 1.0))
        self.assertIn("/SKEW/MOV/7\n", starter)
        self.assertTrue(_has(res.warnings, "FLAG 1 (the co-rotating "
                             "/SKEW/MOV/7)", f"NEW /SKEW/FIX/{sid}",
                             "fixed in time"), res.warnings)

    def test_e_con1_0_is_the_global_frame(self):
        """(e) CON1 0 -> skew 0 (billet-forge's case; LS-DYNA's results hold
        the code although d3hsp prints 000000). Starter (a1_e): 0 errors."""
        res, starter, card = self._rb(_cmo(0, 110111))
        self.assertEqual(card[:3], ("110", "111", 0))
        self.assertIn("   110 111         0", starter)
        self.assertTrue(_has(res.warnings, _W1, "in the GLOBAL frame",
                             "-99.97 -> +0.13 %"), res.warnings)
        from k2rad.writer.rbody import _make_rbodies
        st = _dispatch(_cmo(0, 110111))
        _make_rbodies(st)
        self.assertEqual(st.rigid_auto_bcs, {19: ("110", "111", "BC_rigid_1")})
        self.assertEqual(st.rigid_auto_cmo_neg, {19})
        self.assertEqual(st.rigid_skewed_bcs, {})

    def test_f_an_undefined_con1_writes_nothing(self):
        res, starter, card = self._rb(_cmo(9, 100111))
        self.assertIsNone(card)
        self.assertTrue(_has(res.warnings, "CON1 9 names no "
                             "*DEFINE_COORDINATE_*", _W5_137,
                             "NO /BCS written"), res.warnings)

    def test_g_a_bad_code_writes_nothing_and_allocates_nothing(self):
        """(g) a digit >= 2 or a seventh digit: no card, no t = 0 skew id
        drawn (the deck's CON1 is a FLAG-1 frame, which would allocate one) -
        the file equals the 000000 deck's."""
        _r0, s0, c0 = self._rb(_cmo(7, 0, _nod7(1)))
        self.assertIsNone(c0)
        for code in (200000, 20000, 2000, 200, 20, 2, 900000, 1000000,
                     1100111):
            with self.subTest(con2=code):
                res, starter, card = self._rb(_cmo(7, code, _nod7(1)))
                self.assertIsNone(card)
                self.assertTrue(_has(res.warnings, f"CON2 {code} is not a "
                                     "six-digit 0/1 code", _W5_1051),
                                res.warnings)
                self.assertEqual(starter, s0)

    def test_h_five_digits_are_left_padded(self):
        _res, starter, card = self._rb(_cmo(5, 11111, _SYS5))
        self.assertEqual(card[:3], ("011", "111", 5))

    def test_i_merged_parts_carry_the_leads_code(self):
        """(i) *CONSTRAINED_RIGID_BODIES 1 2: one /RBODY, one card (the
        lead's 010 000 in skew 5) + the slave's code named; same mid: no
        sentence."""
        res, starter, card = self._rb(_merge_deck((-1.0, 5, 100000)))
        self.assertEqual(card[:3], ("010", "000", 5))
        self.assertIsNone(_bcs_card(starter, "BC_rigid_2"))
        self.assertTrue(_has(res.warnings, "*CONSTRAINED_RIGID_BODIES: part 2 "
                             "(mid 3, CMO -1 CON1 5 CON2 100000) is merged "
                             "into part 1"), res.warnings)
        res1, _s1, card1 = self._rb(_merge_deck())
        self.assertEqual(card1[:3], ("010", "000", 5))
        self.assertFalse(_has(res1.warnings, "is merged into part 1; the "
                              "merged /RBODY carries only"), res1.warnings)

    def test_j_one_skew_per_node(self):
        """(j) the ERROR-148 clash: member TC 3 (z, skew 0) re-pointed onto
        main node 19, whose CMO -1 card is in skew 3. The rule keeps the
        rigid body's card and drops the member code, named. Starter (a1_j):
        0 errors; the TWO-SKEW CONTROL (this .rad + the dropped code written
        back as a skew-0 /BCS on node 19's group, a1_j148) stops with ERROR
        148 'A SKEW IS ALREADY DEFINED WITH THE NODE'."""
        res, starter, card = self._rb(_cmo(3, 100000, _VEC3, tc=3))
        self.assertEqual(card[:3], ("100", "000", 3))
        groups = _bcs_groups(starter)
        self.assertEqual([t for t, (_c, ids) in groups.items()
                          if t.startswith("node_tc_rc_") and 19 in ids], [])
        w = _node_warning(res)
        for needle in ("(node 19) carry the SKEWED /BCS of their rigid body "
                       "(BC_rigid_1 at skew 3)", "'001 000' (skew 0)", _W7,
                       "not exact: node 19 no longer holds global z",
                       "ERROR 148"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w)
        # CON2 111111: every translation held in the skew -> exact
        res2, _s2, _c2 = self._rb(_cmo(3, 111111, _VEC3, tc=3))
        w2 = _node_warning(res2)
        self.assertIn("exact: the kept card's Tra / Rot is 111", w2)
        self.assertNotIn("not exact", w2)
        # a *CONSTRAINED_GLOBAL plane through the rigid plate drops too
        cg = "*CONSTRAINED_GLOBAL\n" + _row(3, 0, 3, 0.0, 0.0, 0.0, 0.0) + "\n"
        rg, sg, _cg = self._rb(_cmo(3, 100000, _VEC3 + cg))
        g = [w for w in rg.warnings if w.startswith("*CONSTRAINED_GLOBAL: ")]
        self.assertEqual(len(g), 1)
        self.assertIn("the *CONSTRAINED_GLOBAL code(s) '001 000' (skew 0)",
                      g[0])
        self.assertEqual([t for t, (_c, ids) in _bcs_groups(sg).items()
                          if t.startswith("constrained_global_")
                          and 19 in ids], [])
        # a global *BOUNDARY_SPC on a member: the card loses node 19 (here
        # its only node) and is named; an SPC in the SAME skew 3 stays
        spc = "*BOUNDARY_SPC_NODE\n" + _row(1, 0, 0, 0, 1, 0, 0, 0) + "\n"
        rs, ss, _cs = self._rb(_cmo(3, 100000, _VEC3 + spc))
        self.assertTrue(_has(rs.warnings, "*BOUNDARY_SPC:", "(node 19)",
                             "'001 000' (skew 0)", _W7), rs.warnings)
        self.assertNotIn("\nBC_1\n", ss)
        # (a *BOUNDARY_SPC CID resolves only a SYSTEM / NODES frame today -
        # a VECTOR CID is the round-9 side finding D13 - so the same-skew
        # control uses the SYSTEM frame 5 on both cards)
        spc5 = "*BOUNDARY_SPC_NODE\n" + _row(1, 5, 0, 0, 1, 0, 0, 0) + "\n"
        r5, s5, c5 = self._rb(_cmo(5, 100000, _SYS5 + spc5))
        self.assertEqual(c5[:3], ("100", "000", 5))
        self.assertEqual(_bcs_card(s5, "BC_1")[:3], ("001", "000", 5))
        self.assertFalse(_has(r5.warnings, _W7), r5.warnings)

    def test_k_implicit_stabilisation_never_joins_a_skewed_card(self):
        imp = "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 1.0e-4) + "\n"
        load = ("*LOAD_RIGID_BODY\n" + _row(1, 3, 7, 1.0) + "\n"
                "*DEFINE_CURVE\n" + _row(7) + "\n"
                f"{0.0:>20.6f}{1.0:>20.6f}\n{1.0:>20.6f}{1.0:>20.6f}\n")
        res, _s, card = self._rb(_cmo(3, 111, _VEC3 + imp + load))
        self.assertEqual(card[:3], ("000", "111", 3))
        self.assertTrue(_has(res.warnings, "the stabilisation of an unloaded "
                             "free translation is NOT added to BC_rigid_1, "
                             "whose /BCS sits in /SKEW/3"), res.warnings)
        res0, _s0, card0 = self._rb(_cmo(0, 111, imp + load))
        self.assertEqual(card0[:3], ("110", "111", 0))
        self.assertTrue(_has(res0.warnings, "auto-constrained non-loaded "
                             "free translation(s) X,Y"), res0.warnings)

    def test_m_cmo_plus_1_cards_do_not_move(self):
        """(m) round 7's P1 / P2 probes (CMO +1) are byte-identical to
        4f5b6e8 (SHA measured from the pristine checkout)."""
        for deck, sha in ((_a1_deck(), _PR8_SHA["p1"]),
                          (_a1_deck(con1=1, con2=7, tc=6, rc=7),
                           _PR8_SHA["p2"])):
            with self.subTest(sha=sha[:12]):
                _r, starter, _e = _convert(deck)
                self.assertEqual(_sha(starter), sha)

    def test_l_the_opt_out_restores_the_4f5b6e8_bytes_and_warnings(self):
        """(l) --no-rigid-local-constraints on (a), (d), (e), (j), (o): the
        starter file and the warning list equal 4f5b6e8's (SHA measured from
        the pristine checkout, PYTHONDONTWRITEBYTECODE=1, porcelain --ignored
        empty before and after)."""
        for key, deck in _OPT_OUT_DECKS().items():
            with self.subTest(probe=key):
                res, starter, _e = _convert(deck,
                                            rigid_local_constraints=False)
                self.assertEqual(_sha(starter), _PR8_SHA[key])
                self.assertEqual(_sha("\n".join(res.warnings)),
                                 _PR8_WARN_SHA[key])

    def test_n_the_coupon(self):
        """(n) the g3p coupon: the cube's 100 000 and the plate's 100 111,
        both in skew 5."""
        res, starter, _e = _convert(_CMO_COUPON)
        self.assertEqual(_bcs_card(starter, "BC_rigid_1")[:3], ("100", "000", 5))
        self.assertEqual(_bcs_card(starter, "BC_rigid_2")[:3], ("100", "111", 5))
        self.assertIn("   100 000         5", starter)
        self.assertIn("   100 111         5", starter)

    def test_o_the_CNRB_SPC_card_shares_the_helper(self):
        """(o) CNRB _SPC CMO -1 on a VECTOR CON1: the card in that skew and
        no false 'will dangle'; FLAG 1 -> a t = 0 skew; 1100111 refused.
        Starter (a1_o): 0 errors."""
        def cnrb(con1, con2, frame):
            return _a1_deck(tc=0, extra=frame + (
                "*SET_NODE_LIST\n" + _row(7) + "\n"
                + _row(10, 11, 12, 13, 14, 15, 16, 17) + "\n" + _row(18)
                + "\n*CONSTRAINED_NODAL_RIGID_BODY_SPC\n" + _row(50, 0, 7)
                + "\n" + _row(-1.0, con1, con2) + "\n"))
        res, starter, _e = _convert(cnrb(3, 110000, _VEC3))
        self.assertEqual(_bcs_card(starter, "BC_cnrb_50")[:3],
                         ("110", "000", 3))
        self.assertFalse(_has(res.warnings, "will dangle"), res.warnings)
        r_off, s_off, _e2 = _convert(cnrb(3, 110000, _VEC3),
                                     rigid_local_constraints=False)
        self.assertTrue(_has(r_off.warnings, "will dangle"))
        # FLAG 1: a t = 0 /SKEW/FIX instead of the moving skew
        node_frame = "*DEFINE_COORDINATE_NODES\n" + _row(7, 10, 12, 16, 1) + "\n"
        r1, s1, _e1 = _convert(cnrb(7, 100000, node_frame))
        c1 = _bcs_card(s1, "BC_cnrb_50")
        self.assertNotIn(c1[2], (0, 7))
        self.assertEqual(_skew_fix(s1, c1[2])[0], "SKEW_CON1_T0_7")
        self.assertTrue(_has(r1.warnings, "*CONSTRAINED_NODAL_RIGID_BODY_SPC "
                             "pid=50: CMO -1 CON1 7", "NEW /SKEW/FIX"))
        # a seventh digit: no card at all
        r7, s7, _e7 = _convert(cnrb(3, 1100111, _VEC3))
        self.assertIsNone(_bcs_card(s7, "BC_cnrb_50"))
        self.assertTrue(_has(r7.warnings, "CON2 1100111 is not a six-digit"))

    def test_p_cmo_2_is_named_and_writes_nothing(self):
        res, starter, card = self._rb(_cmo(0, 0, cmo=2.0))
        self.assertIsNone(card)
        self.assertTrue(_has(res.warnings, "CMO 2 constrains the body at "
                             "XSPC/YSPC/ZSPC or node SPCNID"), res.warnings)
        res_m, _s, card_m = self._rb(_cmo(0, 0, cmo=-2.0))
        self.assertIsNone(card_m)
        self.assertTrue(_has(res_m.warnings, "CMO -2 constrains the body"))
        # opt-out: nothing said, as 4f5b6e8
        r_off, _so, _co = self._rb(_cmo(0, 0, cmo=2.0),
                                   rigid_local_constraints=False)
        self.assertFalse(_has(r_off.warnings, "constrains the body at XSPC"))


# ═════════════════════════════════════════════════════════════════════════════
# A3 — the non-rigid double /BCS union (P1 BC_n + BC_n, P2 BC_n + fix_free,
#      P3 fix_free + node_tc_rc)
# ═════════════════════════════════════════════════════════════════════════════

def _digits(code: str):
    return [int(c) for c in code]


def _spc_node(nid: int, cid: int, code: str) -> str:
    return "*BOUNDARY_SPC_NODE\n" + _row(nid, cid, *_digits(code)) + "\n"


def _spc_set(sid: int, cid: int, code: str) -> str:
    return "*BOUNDARY_SPC_SET\n" + _row(sid, cid, *_digits(code)) + "\n"


def _nset(sid: int, nodes) -> str:
    return "*SET_NODE_LIST\n" + _row(sid) + "\n" + _row(*nodes) + "\n"


_IMP = "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"


def _free_node(tc: int = 0, rc: int = 0) -> str:
    """Node 50, attached to nothing: the implicit free-node guard's node."""
    return ("*NODE\n" + f"{50:>8}{100.0:>16.6f}{100.0:>16.6f}{0.0:>16.6f}"
            f"{tc:>8}{rc:>8}\n")


def _plates(extra: str) -> str:
    """round 7's probe pair with a CMO-0 *MAT_RIGID plate (nodes 1-9, main 19)
    and the elastic plate (nodes 10-18) - the A3 probes' carrier."""
    return _a1_deck(cmo=0.0, con1=0, con2=0, tc=0, extra=extra)


_P2_SHARED = (_nset(101, [10, 11]) + _nset(102, [10, 12]) + _nset(103, [10, 13])
              + _spc_set(101, 0, "110001") + _spc_set(102, 0, "011100")
              + _spc_set(103, 0, "001010"))
_WT1 = "are stated by two or more *BOUNDARY_SPC cards in one system"


class NonRigidBcsUnion(unittest.TestCase):
    """A3 (round 8): a node that two *BOUNDARY_SPC cards (P1), a global deck
    SPC and the implicit free-node guard (P2), or a *NODE TC/RC code and the
    guard (P3) constrain was written in TWO /BCS. LS-DYNA keeps ONE
    constraint per node and the starter ORs the cards (hm_read_bcs.F:198
    MY_OR), so the second card only fed starter WARNING 312 (one condition
    per DOF both cards fix). Now one union per (node, skew).

    Starter runs (nt 4, rcv_r8i_implA_a3_<x>, harvested into
    implA_out/runs/): recorded in each test."""

    def test_1_two_identical_cards_on_one_node(self):
        res, starter, _e = _convert(_plates(_spc_node(14, 0, "111111")
                                            + _spc_node(14, 0, "111111")))
        self.assertEqual(_bcs_card(starter, "BC_1")[:2], ("111", "111"))
        self.assertIsNone(_bcs_card(starter, "BC_2"))
        self.assertTrue(_has(res.warnings, "*BOUNDARY_SPC: 6 DOF(s) on 1 "
                             "node(s) (node 14)", _WT1,
                             "1 card(s) write no /BCS (BC_2)"), res.warnings)

    def test_2_three_sets_on_one_corner_keep_the_union(self):
        """Hand derivation: card 2 (011 100) meets 110 001 on Ty -> corner 10
        keeps z + rx in BC_2_001_100, node 12 stays on BC_2 in a
        not_restated group; card 3 (001 010) meets 111 101 on Tz -> 10 keeps
        ry in BC_3_000_010. The union on 10 is 111 111. Starter (a3_2): 0
        errors, no WARNING 312; the opt-out arm (a3_2off): WARNING 312, '2
        INCOMPATIBLE KINEMATIC CONDITIONS' (Ty and Tz restated)."""
        res, starter, _e = _convert(_plates(_P2_SHARED))
        g = _bcs_groups(starter)
        self.assertEqual(g["BC_1"], ("110 001", [10, 11]))
        self.assertEqual(g["BC_2"], ("011 100", [12]))
        self.assertEqual(g["BC_2_001_100"], ("001 100", [10]))
        self.assertEqual(g["BC_3"], ("001 010", [13]))
        self.assertEqual(g["BC_3_000_010"], ("000 010", [10]))
        self.assertIn("\nBC_2_not_restated\n", starter)
        union = ["0"] * 6
        for t in ("BC_1", "BC_2_001_100", "BC_3_000_010"):
            for i, c in enumerate(g[t][0].replace(" ", "")):
                if c == "1":
                    union[i] = "1"
        self.assertEqual("".join(union), "111111")
        self.assertTrue(_has(res.warnings, "2 DOF(s) on 1 node(s) (node 10)",
                             "0 card(s) write no /BCS",
                             "1 node(s) keep the remaining DOFs"),
                        res.warnings)

    def test_2b_the_union_carries_every_earlier_card(self):
        """Card 3 (100 010) restates x, which only card 1 (110 001) stated:
        the union carries card 1 past card 2 (011 100), so corner 10 keeps
        only ry in BC_3_000_010 (a union keyed on the last card alone would
        write BC_3 on node 10 again - the mutation pass's survivor A3-04).
        Starter (a3_2b, nt 4): 0 errors."""
        res, starter, _e = _convert(_plates(
            _nset(101, [10, 11]) + _nset(102, [10, 12]) + _nset(103, [10, 13])
            + _spc_set(101, 0, "110001") + _spc_set(102, 0, "011100")
            + _spc_set(103, 0, "100010")))
        g = _bcs_groups(starter)
        self.assertEqual(g["BC_3"], ("100 010", [13]))
        self.assertEqual(g["BC_3_000_010"], ("000 010", [10]))
        # card 2 restates y (card 1's), card 3 restates x (card 1's only)
        self.assertTrue(_has(res.warnings, "2 DOF(s) on 1 node(s) (node 10)"),
                        res.warnings)

    def test_3_two_skews_are_never_merged(self):
        """A SYSTEM-CID card and a global card on one node: both written and
        named. Starter (a3_3 and a3_3off): ERROR 148 on BOTH arms - the
        deck's own clash, which the union neither causes nor hides."""
        res, starter, _e = _convert(_plates(_SYS5 + _spc_node(14, 5, "100000")
                                            + _spc_node(14, 0, "010000")))
        self.assertEqual(_bcs_card(starter, "BC_1")[:3], ("100", "000", 5))
        self.assertEqual(_bcs_card(starter, "BC_2")[:3], ("010", "000", 0))
        self.assertTrue(_has(res.warnings, "node(s) 14 are constrained in "
                             "two different systems (skews 0, 5)", "ERROR 148"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, _WT1), res.warnings)
        # the same digit in two skews is two DIFFERENT axes: never a restated
        # DOF (a union keyed by node alone would drop BC_2 here - the
        # mutation pass's survivor A3-01). Starter (a3_3b, nt 4): ERROR 148,
        # the deck's own two-skew clash, as on a3_3 - plus one WARNING 312
        # (incompatible kinematic conditions) that a3_3 does not print: here
        # both cards state x.
        r2, s2, _e2 = _convert(_plates(_SYS5 + _spc_node(14, 5, "110000")
                                       + _spc_node(14, 0, "100000")))
        self.assertEqual(_bcs_card(s2, "BC_1")[:3], ("110", "000", 5))
        self.assertEqual(_bcs_card(s2, "BC_2")[:3], ("100", "000", 0))
        self.assertFalse(_has(r2.warnings, _WT1), r2.warnings)

    def test_4_no_shared_node_is_byte_identical(self):
        deck = _plates(_spc_node(14, 0, "111000") + _spc_node(15, 0, "000111"))
        res, s_on, e_on = _convert(deck)
        _r, s_off, e_off = _convert(deck, bcs_union=False)
        self.assertEqual(s_on, s_off)
        self.assertEqual(e_on, e_off)
        self.assertFalse(_has(res.warnings, _WT1))

    def test_5_P2_the_guard_skips_what_the_SPC_fixes(self):
        res, starter, _e = _convert(_plates(_IMP + _free_node()
                                            + _spc_node(50, 0, "110001")))
        g = _bcs_groups(starter)
        self.assertEqual(g["fix_free_reference_nodes_001_110"],
                         ("001 110", [50]))
        self.assertNotIn("fix_free_reference_nodes", g)
        self.assertTrue(_has(res.warnings, "Free-node guard x *BOUNDARY_SPC: "
                             "3 DOF(s) on 1 free node(s) (node 50)",
                             "0 node(s) need no guard /BCS"), res.warnings)
        res6, s6, _e6 = _convert(_plates(_IMP + _free_node()
                                         + _spc_node(50, 0, "111111")))
        self.assertEqual([t for t in _bcs_groups(s6)
                          if t.startswith("fix_free_reference")], [])
        self.assertTrue(_has(res6.warnings, "6 DOF(s) on 1 free node(s) "
                             "(node 50)", "1 node(s) need no guard /BCS"))

    def test_5b_the_111_111_group_comes_first(self):
        """Free node 51 (nothing fixed) and free node 50 (SPC 110 001): the
        guard writes the 111 111 card FIRST under its old title (the byte
        identity of every deck without a hit), then the remainder (the
        mutation pass's survivor A3-10 reversed them). Starter (a3_5b, nt 4):
        0 errors."""
        free51 = ("*NODE\n" + f"{51:>8}{120.0:>16.6f}{100.0:>16.6f}"
                  f"{0.0:>16.6f}{0:>8}{0:>8}\n")
        res, starter, _e = _convert(_plates(_IMP + _free_node() + free51
                                            + _spc_node(50, 0, "110001")))
        g = _bcs_groups(starter)
        self.assertEqual(g["fix_free_reference_nodes"], ("111 111", [51]))
        self.assertEqual(g["fix_free_reference_nodes_001_110"],
                         ("001 110", [50]))
        lines = starter.splitlines()
        first = lines.index("fix_free_reference_nodes")
        rem = lines.index("fix_free_reference_nodes_001_110")
        self.assertLess(first, rem)
        self.assertLess(int(lines[first - 1].split("/")[-1]),
                        int(lines[rem - 1].split("/")[-1]))

    def test_6_P3_the_guard_skips_what_the_TC_RC_code_fixes(self):
        """*NODE TC 4 (x, y) on the free node. Starter (a3_6): 0 errors, no
        WARNING 312 (the opt-out arm a3_6off: WARNING 312, 2 conditions)."""
        res, starter, _e = _convert(_plates(_IMP + _free_node(tc=4)))
        g = _bcs_groups(starter)
        self.assertEqual(g["node_tc_rc_110_000"], ("110 000", [50]))
        self.assertEqual(g["fix_free_reference_nodes_001_111"],
                         ("001 111", [50]))
        self.assertTrue(_has(res.warnings, "Free-node guard x *NODE TC/RC: "
                             "2 DOF(s) on 1 free node(s) (node 50)",
                             "(0 need none)"), res.warnings)

    def test_7_a_rigid_main_node_takes_the_union_too(self):
        """The W7_3P_Bending shape (two SPC cards on members of one rigid
        indenter, re-pointed onto its main node): 010 000 then 011 000 ->
        the second restates Ty, its remainder 001 000 stays. *MAT_RIGID body
        (main 19) and a CNRB over the elastic plate (its synthesized main).
        Starter (a3_7): 0 errors, no WARNING 312 (opt-out a3_7off: WARNING
        312, 1 condition)."""
        res, starter, _e = _convert(_plates(_spc_node(1, 0, "010000")
                                            + _spc_node(2, 0, "011000")))
        g = _bcs_groups(starter)
        self.assertEqual(g["BC_1"], ("010 000", [19]))
        self.assertNotIn("BC_2", g)
        self.assertEqual(g["BC_2_001_000"], ("001 000", [19]))
        self.assertTrue(_has(res.warnings, "1 DOF(s) on 1 node(s) (node 19)",
                             "1 card(s) write no /BCS (BC_2)"), res.warnings)
        cnrb = (_nset(7, [10, 11, 12, 13, 14, 15, 16, 17, 18])
                + "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(50, 0, 7) + "\n"
                + _spc_node(10, 0, "010000") + _spc_node(11, 0, "011000"))
        rc, sc, _ec = _convert(_plates(cnrb))
        gc = _bcs_groups(sc)
        main = gc["BC_1"][1]
        self.assertEqual(len(main), 1)
        self.assertEqual(gc["BC_2_001_000"], ("001 000", main))
        self.assertNotIn("BC_2", gc)

    def test_8_a_skewed_SPC_on_a_free_node_is_named(self):
        """The guard cannot subtract a skewed SPC (its digits are axes of the
        skew) and keeps 111 111 at skew 0 - ERROR 148, named (reach 0).
        Starter (a3_8): ERROR 148 on both arms."""
        res, starter, _e = _convert(_plates(_IMP + _SYS5 + _free_node()
                                            + _spc_node(50, 5, "110000")))
        g = _bcs_groups(starter)
        self.assertEqual(g["fix_free_reference_nodes"], ("111 111", [50]))
        self.assertTrue(_has(res.warnings, "Free-node guard: free node(s) 50 "
                             "carry a *BOUNDARY_SPC in /SKEW 5", "ERROR 148"),
                        res.warnings)

    def test_9_the_opt_out_restores_the_4f5b6e8_bytes(self):
        """--no-bcs-union on probes 1, 2, 5, 6, 7 = the pristine 4f5b6e8
        starter file (SHA measured from the pristine checkout)."""
        for key, deck in _A3_DECKS().items():
            with self.subTest(probe=key):
                _r, starter, _e = _convert(deck, bcs_union=False)
                self.assertEqual(_sha(starter), _PR8_SHA[key])


# ═════════════════════════════════════════════════════════════════════════════
# A2 — mainboltaexpl: the bolt clamp (l)-2 and the fixed-column curve (l)-3
# ═════════════════════════════════════════════════════════════════════════════

def _curve_state(lines, header=None, **opts):
    """Dispatch a lone *DEFINE_CURVE 11 with the given point lines; return the
    state (``opts`` set on ConvertOptions before dispatch)."""
    deck = ("*KEYWORD\n*DEFINE_CURVE\n" + (header or _row(11)) + "\n"
            + "\n".join(lines) + "\n*END\n")
    import os
    import tempfile
    from k2rad.handlers import dispatch
    from k2rad.parser import parse_k_file
    from k2rad.state import ConversionState
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "c.k")
    with open(path, "w") as fh:
        fh.write(deck)
    st = ConversionState()
    for k, v in opts.items():
        setattr(st.options, k, v)
    for block in parse_k_file(path):
        dispatch(block, st)
    tmp.cleanup()
    return st


_MB_LINES = ["                 0.0                 0.0",
             "              0.0025                 0.0",
             "               0.0055.0",
             "             0.005055.0"]


def _grid(base: int, z: float):
    """A 4 x 4 node grid (10 mm pitch) and its 3 x 3 quads: ids base+1..+16."""
    nodes = [(base + 1 + j * 4 + i, 10.0 * i, 10.0 * j, z)
             for j in range(4) for i in range(4)]
    quads = []
    for j in range(3):
        for i in range(3):
            n1 = base + 1 + j * 4 + i
            quads.append((n1, n1 + 1, n1 + 5, n1 + 4))
    return nodes, quads


def _bolt_deck(cnrb120=True, tied=False, rigid20=False, extra="") -> str:
    """The (i) probe: plates 10 (z 0, nodes 1001-1016) and 20 (z 2, nodes
    2001-2016) in ONE *CONTACT_AUTOMATIC_SINGLE_SURFACE on a part set; an
    ELFORM-9 *MAT_SPOTWELD bolt (beam 900, nodes 1 -> 2) under
    *INITIAL_AXIAL_FORCE_BEAM; CNRB 110 = 4 plate-10 nodes + bolt end 1, CNRB
    120 = 4 plate-20 nodes + bolt end 2, CNRB 130 = 4 OTHER plate-10 nodes.
    ``rigid20``: plate 20 is a *MAT_RIGID part with bolt end 2 as an extra
    node instead of CNRB 120; ``tied``: a *CONTACT_TIED_SURFACE_TO_SURFACE
    (plate 10 on plate 20) instead of the single-surface contact."""
    n10, q10 = _grid(1000, 0.0)
    n20, q20 = _grid(2000, 2.0)
    lines = ["*KEYWORD", "*CONTROL_TERMINATION", _row(0.001), "*NODE"]
    for nid, x, y, z in n10 + n20 + [(1, 15.0, 15.0, -1.0),
                                     (2, 15.0, 15.0, 3.0),
                                     (3, 15.0, 25.0, -1.0)]:
        lines.append(f"{nid:>8}{x:>16.6f}{y:>16.6f}{z:>16.6f}")
    lines += ["*PART", "plate 10", _row(10, 10, 10),
              "*PART", "plate 20", _row(20, 10, 21 if rigid20 else 10),
              "*PART", "bolt", _row(30, 30, 30),
              "*SECTION_SHELL", _row(10, 2, 1.0, 2), _row(1.0, 1.0, 1.0, 1.0),
              "*MAT_ELASTIC", _row(10, 7.85e-9, 210000.0, 0.3),
              "*SECTION_BEAM", _row(30, 9), _row(10.0, 10.0, 0.0, 0.0),
              "*MAT_SPOTWELD", _row(30, 7.85e-9, 210000.0, 0.3, 640.0, 9500.0),
              "*ELEMENT_SHELL"]
    eid = 0
    for pid, quads in ((10, q10), (20, q20)):
        for q in quads:
            eid += 1
            lines.append("".join(f"{v:>8}" for v in (eid, pid) + q))
    lines += ["*ELEMENT_BEAM", "".join(f"{v:>8}" for v in (900, 30, 1, 2, 3)),
              "*SET_BEAM", _row(100), _row(900),
              "*DEFINE_CURVE", _row(9), f"{0.0:>20.6f}{0.0:>20.6f}",
              f"{0.001:>20.6f}{1000.0:>20.6f}",
              "*INITIAL_AXIAL_FORCE_BEAM", _row(100, 9, 1.0, 0),
              "*SET_NODE_LIST", _row(110), _row(1006, 1007, 1010, 1011, 1),
              "*SET_NODE_LIST", _row(130), _row(1001, 1002, 1005, 1013),
              "*CONSTRAINED_NODAL_RIGID_BODY", _row(110, 0, 110),
              "*CONSTRAINED_NODAL_RIGID_BODY", _row(130, 0, 130)]
    if rigid20:
        lines += ["*MAT_RIGID", _row(21, 7.85e-9, 210000.0, 0.3),
                  _row(0.0, 0, 0), _row(0.0),
                  "*CONSTRAINED_EXTRA_NODES_NODE", _row(20, 2)]
    elif cnrb120:
        lines += ["*SET_NODE_LIST", _row(120), _row(2006, 2007, 2010, 2011, 2),
                  "*CONSTRAINED_NODAL_RIGID_BODY", _row(120, 0, 120)]
    if tied:
        lines += ["*CONTACT_TIED_SURFACE_TO_SURFACE", _row(10, 20, 3, 3),
                  _row(0.0), _row(0.0)]
    else:
        lines += ["*SET_PART_LIST", _row(1), _row(10, 20),
                  "*CONTACT_AUTOMATIC_SINGLE_SURFACE", _row(1, 0, 2, 0),
                  _row(0.1, 0.1), _row(0.0)]
    return "\n".join(lines) + "\n" + extra + "*END\n"


def _single_surface_group(starter: str):
    """Node ids of the single-surface contact's secondary /GRNOD."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/GRNOD/NODE/") and lines[i + 1].startswith(
                "contact_slave_"):
            ids = []
            j = i + 2
            while j < len(lines) and not lines[j].startswith(("/", "#")):
                ids += [int(t) for t in lines[j].split()]
                j += 1
            return ids
    return None


class BoltClampAndFixedCurveColumns(unittest.TestCase):
    """A2 (round 8): mainboltaexpl lost its bolt clamp and its pull. (l)-2: the
    TYPE7 secondary side dropped every rigid member, incl. the 68 CNRB 110 /
    120 members holding the bolt's ends (LS-DYNA counts them: 1601 nodes);
    (l)-3: *DEFINE_CURVE read point lines by a whitespace split only, so the
    fused '0.0055.0' lines LS-DYNA reads in 2E20.0 columns were dropped
    (/FUNCT/11 kept 2 of 4 points)."""

    def test_a_the_fused_lines_are_read_in_2E20_columns(self):
        st = _curve_state(_MB_LINES)
        self.assertEqual(st.curves[11].pts, [(0.0, 0.0), (0.0025, 0.0),
                                             (0.005, 5.0), (0.00505, 5.0)])
        self.assertTrue(_has(st.warnings, "*DEFINE_CURVE 11: 2 point line(s)",
                             "= (0.005, 5)",
                             "the curve keeps 4 points (the split kept 2)"),
                        st.warnings)
        off = _curve_state(_MB_LINES, fixed_curve_columns=False)
        self.assertEqual(off.curves[11].pts, [(0.0, 0.0), (0.0025, 0.0)])
        self.assertFalse(_has(off.warnings, "2E20.0"))

    def test_b_a_blank_abscissa_is_zero(self):
        st = _curve_state([" " * 20 + "               180.0"])
        self.assertEqual(st.curves[11].pts, [(0.0, 180.0)])

    def test_c_comma_lines_keep_the_split(self):
        st = _curve_state(["0.0,1.0", "0.0, 1.0", "5.0,"])
        self.assertEqual(st.curves[11].pts, [(0.0, 1.0), (0.0, 1.0),
                                             (5.0, 0.0)])
        self.assertFalse(_has(st.warnings, "2E20.0"))

    def test_d_two_tokens_keep_the_split_and_garbage_is_no_point(self):
        """Decision D4: a misaligned two-token line (here straddling column
        20) keeps the free read - a fixed-first read would misread it."""
        st = _curve_state(["   1.0e-3    5.0",
                           " " * 21 + "0.0" + " " * 17 + "900.",
                           "abc", "&undefined_param"])
        self.assertEqual(st.curves[11].pts, [(0.001, 5.0), (0.0, 900.0)])
        self.assertFalse(_has(st.warnings, "2E20.0"))

    def test_e_a_parameter_in_a_fixed_column(self):
        lines = ["               &tend5.0"]
        deck_params = "*PARAMETER\n" + "R tend    0.005\n"
        import os
        import tempfile
        from k2rad.handlers import dispatch
        from k2rad.parser import parse_k_file
        from k2rad.state import ConversionState
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "c.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n" + deck_params + "*DEFINE_CURVE\n" + _row(11)
                     + "\n" + "\n".join(lines) + "\n*END\n")
        st = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, st)
        tmp.cleanup()
        self.assertEqual(st.curves[11].pts, [(0.005, 5.0)])

    def test_f_a_blank_line_is_no_point(self):
        st = _curve_state(["", "                 1.0                 2.0"])
        self.assertEqual(st.curves[11].pts, [(1.0, 2.0)])

    def test_g_SFA_and_OFFA_apply_to_a_fixed_line(self):
        st = _curve_state(["               0.0055.0"],
                          header=_row(11, 0, 2.0, 3.0, 0.001, 1.0))
        a, o = st.curves[11].pts[0]
        self.assertAlmostEqual(a, (0.005 + 0.001) * 2.0)
        self.assertAlmostEqual(o, (5.0 + 1.0) * 3.0)

    def test_h_smooth_and_function_curves_are_untouched(self):
        deck = ("*KEYWORD\n*DEFINE_CURVE_SMOOTH\n"
                + _row(12, 0, 1.0, 1.0, 0.0, 0.01, 0.002) + "\n"
                "*DEFINE_FUNCTION\n" + _row(13) + "\nf(t)=t\n"
                + _plates("").split("*KEYWORD\n", 1)[1])
        _r, s_on, e_on = _convert(deck)
        _r2, s_off, e_off = _convert(deck, fixed_curve_columns=False)
        self.assertEqual((s_on, e_on), (s_off, e_off))

    def test_i_the_bolt_end_bodies_keep_their_members(self):
        """CNRB 110 / 120 hold the bolt's ends: their plate nodes stay on the
        single-surface secondary side; CNRB 130's are still removed and named
        by the partial-rigid sentence. Starter (a2_i): 0 errors."""
        res, starter, _e = _convert(_bolt_deck())
        ids = set(_single_surface_group(starter))
        self.assertTrue({1006, 1007, 1010, 1011, 2006, 2007, 2010,
                         2011} <= ids)
        self.assertFalse({1001, 1002, 1005, 1013} & ids)
        self.assertEqual(len(ids), 28)
        self.assertTrue(_has(res.warnings, "8 member node(s) of the rigid "
                             "body(ies) 110, 120 holding an end node of the "
                             "*INITIAL_AXIAL_FORCE_BEAM bolt (BSID 100) were "
                             "KEPT"), res.warnings)
        self.assertTrue(_has(res.warnings, "4 of the 32 node(s) on the "
                             "SECONDARY side"), res.warnings)
        # the opt-out removes all twelve, as 4f5b6e8
        r0, s0, _e0 = _convert(_bolt_deck(), bolt_rigid_contact=False)
        self.assertEqual(len(_single_surface_group(s0)), 20)
        self.assertTrue(_has(r0.warnings, "12 of the 32 node(s)"))
        self.assertFalse(_has(r0.warnings, "were KEPT on the secondary"))

    def test_l_the_beam_hint_stays_silent_on_a_bolt_end(self):
        """The fix round (code-sweep F7 = the campaign validator's
        mainboltaexpl contact 10013): a contact whose secondary side is the
        bolt's beam-only part is dropped (its main side, the same beam part,
        has no surface either). The bolt's end nodes are CNRB members that
        A2 keeps on the penalty contacts, but they are rigid-body members:
        the --beam-contact-secondary hint must not promise the flag rescues
        the side (with it the side gains the two ends and the contact is
        still dropped) - the hint reads the FULL rigid set, as at 4f5b6e8."""
        extra = ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n" + _row(77)
                 + "\n" + _row(30, 30, 3, 3) + "\n" + _row(0.1, 0.1) + "\n"
                 + _row() + "\n")
        for kw in ({}, {"bolt_rigid_contact": False}):
            with self.subTest(**kw):
                res, starter, _e = _convert(_bolt_deck(extra=extra), **kw)
                drops = [w for w in res.warnings
                         if w.startswith("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"
                                         " 77:")
                         and "NO /INTER was emitted" in w]
                self.assertEqual(len(drops), 1, res.warnings)
                self.assertNotIn("--beam-contact-secondary does", drops[0])
                self.assertNotIn("/INTER/TYPE7/77", starter)

    def test_j_a_rigid_part_with_the_end_as_an_extra_node(self):
        """Plate 20 is a *MAT_RIGID part holding bolt end 2 through
        *CONSTRAINED_EXTRA_NODES: all 16 of its nodes stay."""
        res, starter, _e = _convert(_bolt_deck(rigid20=True))
        ids = set(_single_surface_group(starter))
        self.assertTrue(set(range(2001, 2017)) <= ids)
        self.assertTrue(_has(res.warnings, "20 member node(s) of the rigid "
                             "body(ies) 20, 110"), res.warnings)

    def test_k_a_tied_contact_keeps_the_filter(self):
        """Decision D5: only the penalty builders keep the members; a TYPE2
        tied side still drops every rigid member."""
        res, starter, _e = _convert(_bolt_deck(tied=True))
        self.assertFalse(_has(res.warnings, "were KEPT on the secondary"),
                         res.warnings)
        r0, s0, _e0 = _convert(_bolt_deck(tied=True),
                               bolt_rigid_contact=False)
        self.assertEqual(starter, s0)


# ═════════════════════════════════════════════════════════════════════════════
# A4 / A7 — the *SECTION_SHELL Card-2 thickness: the nodal mean (A4) and the
#           plane-strain unit depth (A7)
# ═════════════════════════════════════════════════════════════════════════════

def _quad_deck(elform=2, t=(1.0, "", "", ""), rigid=False) -> str:
    """One 10 x 10 mm quad (nodes 1-4) on *SECTION_SHELL 1 with Card 2 = *t*
    ('' = blank), RO 7.85e-9, *MAT_RIGID (CMO 0) when *rigid*."""
    mat = ("*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
           + _row(0.0, 0, 0) + "\n" + _row(0.0) + "\n") if rigid else (
        "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n")
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(0.001) + "\n"
            "*PART\nquad\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SHELL\n" + _row(1, elform, 1.0, 2) + "\n" + _row(*t)
            + "\n" + mat + "*NODE\n"
            + "".join(f"{n:>8}{x:>16.6f}{y:>16.6f}{0.0:>16.6f}\n"
                      for n, x, y in ((1, 0.0, 0.0), (2, 10.0, 0.0),
                                      (3, 10.0, 10.0), (4, 0.0, 10.0)))
            + "*ELEMENT_SHELL\n" + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4))
            + "\n*END\n")


def _prop_thick(starter: str, pid: int = 1) -> float:
    lines = starter.splitlines()
    i = lines.index(f"/PROP/SHELL/{pid}")
    data = [ln for ln in lines[i + 2:i + 9] if not ln.startswith("#")]
    return float(data[2].split()[2])


def _j_row(starter: str):
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/RBODY/"):
            data = [x for x in lines[i + 1:i + 9] if not x.startswith("#")]
            return [float(v) for v in data[2].split()]
    return None


_WA4 = "the /PROP/SHELL thickness is their MEAN"
_WA7A = "is a 2-D PLANE-STRAIN formulation; LS-DYNA ignores Card 2's"
_WA7B = "is a 2-D AXISYMMETRIC formulation"


class SectionNodalThicknessMean(unittest.TestCase):
    """A4 (round 8): *SECTION_SHELL Card 2's T1..T4 are the thickness at the
    nodes; k2rad read T1 only. LS-DYNA's d3hsp reproduces mean(T1..T4) on
    every element (cup-draw's rigid tools to the printed digit), so a card
    with a written, nonzero T2..T4 different from T1 writes the mean (blank
    / 0.0 = T1) - with its named energy-error cost on cup-draw."""

    def test_1_the_mean_and_its_blank_and_zero_readings(self):
        for t, want, warned in (((1000.0, 1.0, 1.0, 1.0), 250.75, True),
                                ((4.7625, 4.762, 4.762, 4.762), 4.762125,
                                 True),
                                ((2.0, "", "", ""), 2.0, False),
                                ((2.0, 0.0, 0.0, 0.0), 2.0, False),
                                ((2.0, 4.0, "", 0.0), 2.5, True),
                                ((1.5, 1.5, 1.5, 1.5), 1.5, False)):
            with self.subTest(card2=t):
                res, starter, _e = _convert(_quad_deck(t=t))
                self.assertAlmostEqual(_prop_thick(starter), want, places=9)
                self.assertEqual(_has(res.warnings, _WA4), warned)
        res, _s, _e = _convert(_quad_deck(t=(2.0, 4.0, "", 0.0)))
        self.assertTrue(_has(res.warnings, "Card 2 states T1..T4 = 2 / 4 / "
                             "blank / 0; the /PROP/SHELL thickness is their "
                             "MEAN 2.5", "-4.39 -> -17.88 %"), res.warnings)
        _r, s_u, _e2 = _convert(_quad_deck(t=(1.5, 1.5, 1.5, 1.5)))
        self.assertEqual(_sha(s_u), _PR8_SHA["a4_uniform"])

    def test_2_the_2D_formulations_are_A7s(self):
        _r, s13, _e = _convert(_quad_deck(elform=13, t=(25.4, 1.0, 1.0, 1.0)))
        self.assertEqual(_prop_thick(s13), 1.0)
        r15, s15, _e15 = _convert(_quad_deck(elform=15,
                                              t=(25.4, 1.0, 1.0, 1.0)))
        self.assertEqual(_prop_thick(s15), 25.4)
        self.assertFalse(_has(r15.warnings, _WA4))

    def test_3_a_rigid_body_takes_the_mean_thickness(self):
        """Rigid quad, T 4 / 1 / 1 / 1 -> 1.75: mass 7.85e-9 x 100 x 1.75 =
        1.37375e-6, IN per node (m/4)(100 + 1.75^2)/12 = 2.949627e-6, J =
        -SUM(IN) = -1.179851e-5. Starter (a4_3): NEW MASS 0.1373750E-05,
        the point-mass tensor xx = yy = 3.434375e-5, zz = 6.868750e-5."""
        _r, starter, _e = _convert(_quad_deck(t=(4.0, 1.0, 1.0, 1.0),
                                              rigid=True))
        self.assertAlmostEqual(_prop_thick(starter), 1.75)
        j = _j_row(starter)
        for v in j:
            self.assertAlmostEqual(v / -1.179851e-5, 1.0, places=5)

    def test_4_the_opt_out_keeps_T1(self):
        _r, starter, _e = _convert(_quad_deck(t=(4.0, 1.0, 1.0, 1.0),
                                              rigid=True),
                                   section_nodal_thickness_mean=False)
        self.assertEqual(_prop_thick(starter), 4.0)
        self.assertEqual(_sha(starter), _PR8_SHA["a4_rigid"])


class TwoDimensionalShellThickness(unittest.TestCase):
    """A7 (round 8): Vol I R17 *SECTION_SHELL Remark 6 - formulations 13,
    14, 15, 43, 44, 52 and 55 ignore Card 2's thickness. The plane-strain
    ones (13 / 43 / 52 / 55) integrate a UNIT depth, so
    the /PROP/SHELL thickness is 1.0; the axisymmetric ones (14 / 15 / 44)
    integrate per radian, which no thickness reproduces - named."""

    def test_1_plane_strain_gets_a_unit_thickness(self):
        for e in (13, 43, 52, 55):
            with self.subTest(elform=e):
                res, starter, _e = _convert(_quad_deck(elform=e,
                                                       t=(25.4, "", "", "")))
                self.assertEqual(_prop_thick(starter), 1.0)
                self.assertTrue(_has(res.warnings, _WA7A,
                                     "(the card states 25.4)"), res.warnings)
        for e in (12, 2):
            with self.subTest(elform=e):
                res, starter, _e = _convert(_quad_deck(elform=e,
                                                       t=(25.4, "", "", "")))
                self.assertEqual(_prop_thick(starter), 25.4)
                self.assertFalse(_has(res.warnings, "PLANE-STRAIN"))

    def test_2_axisymmetric_is_named_never_changed(self):
        for e in (14, 15, 44):
            with self.subTest(elform=e):
                deck = _quad_deck(elform=e, t=(1000.0, "", "", ""))
                res, starter, _e = _convert(deck)
                self.assertEqual(_prop_thick(starter), 1000.0)
                _r0, s0, _e0 = _convert(deck,
                                        plane_strain_unit_thickness=False)
                self.assertEqual(starter, s0)
                self.assertTrue(_has(res.warnings, _WA7B, "Remark 6",
                                     "NOT LS-DYNA's"), res.warnings)
                self.assertTrue(_has(_r0.warnings, _WA7B))

    def test_3_a_rigid_plane_strain_body(self):
        """Rigid ELFORM-13 quad, T 25.4 -> 1: mass 7.85e-7, IN per node
        (7.85e-7 / 4)(100 + 1)/12 = 1.651771e-6, J = -6.607083e-6. Starter
        (a7_3): NEW MASS 0.7850000E-06, xx = yy = 1.9625e-5, zz = 3.925e-5."""
        _r, starter, _e = _convert(_quad_deck(elform=13, t=(25.4, "", "", ""),
                                              rigid=True))
        for v in _j_row(starter):
            self.assertAlmostEqual(v / -6.607083e-6, 1.0, places=5)

    def test_4_the_opt_out_keeps_T1_and_says_so(self):
        res, starter, _e = _convert(_quad_deck(elform=13,
                                               t=(25.4, "", "", ""),
                                               rigid=True),
                                    plane_strain_unit_thickness=False)
        self.assertEqual(_prop_thick(starter), 25.4)
        self.assertEqual(_sha(starter), _PR8_SHA["a7_rigid"])
        self.assertTrue(_has(res.warnings, "the card's T1 25.4 is written",
                             "integrates a unit thickness"), res.warnings)

    def test_5_a_plane_strain_card_never_takes_the_mean(self):
        res, starter, _e = _convert(_quad_deck(elform=13,
                                               t=(25.4, 1.0, 1.0, 1.0)))
        self.assertEqual(_prop_thick(starter), 1.0)
        self.assertFalse(_has(res.warnings, _WA4))


# ═════════════════════════════════════════════════════════════════════════════
# A8 — *ELEMENT_MASS on a rigid SECONDARY node -> /ADMAS on that node
# ═════════════════════════════════════════════════════════════════════════════

def _emass(nid: int, mass: float, eid: int = 1) -> str:
    return ("*ELEMENT_MASS\n" + f"{eid:>8}{nid:>8}{mass:>16.8g}{0:>8}\n")


def _admas(starter: str):
    """{mass: sorted node ids} of every /ADMAS/0 card."""
    lines = starter.splitlines()
    groups = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("/GRNOD/NODE/"):
            gid = int(lines[i].split("/")[-1])
            ids = []
            j = i + 2
            while j < len(lines) and not lines[j].startswith(("/", "#")):
                ids += [int(t) for t in lines[j].split()]
                j += 1
            groups[gid] = ids
            i = j
            continue
        i += 1
    out = {}
    for i, ln in enumerate(lines):
        if ln.startswith("/ADMAS/0/"):
            m, g = lines[i + 3].split()
            out[float(m)] = sorted(groups[int(g)])
    return out


def _rbody_mass(starter: str, rid: int) -> float:
    lines = starter.splitlines()
    i = lines.index(f"/RBODY/{rid}")
    return float(lines[i + 3].split()[4])


_WA8 = "sit on SECONDARY nodes"


class RigidSecondaryElementMass(unittest.TestCase):
    """A8 (round 8): an *ELEMENT_MASS on a rigid body's SECONDARY node was
    folded into the /RBODY Mass field (a *MAT_RIGID body, which the starter
    places at the CoG of the secondaries WITHOUT it) or dropped (a CNRB
    secondary). Now /ADMAS/0 on its node; the main node's own mass stays in
    the Mass field; ICoG-4 bodies are unchanged."""

    def test_1_a_part_body_writes_the_mass_on_its_node(self):
        """Rigid 2 x 2 plate (20 x 20 mm, T 1, RO 7.85e-9: 3.14e-6) + 0.01 on
        corner 9 (20, 20): the body's CoG x = y = (3.14e-6 x 10 + 0.01 x 20)
        / 0.01000314 = 19.99686. Starter (a8_1): NEW MASS 0.1000314E-01 and
        the CoG at 19.99686 (the opt-out arm a8_1off: the same mass at
        (10, 10))."""
        res, starter, _e = _convert(_plates(_emass(9, 0.01)))
        self.assertEqual(_rbody_mass(starter, 19), 0.0)
        self.assertEqual(_admas(starter), {0.01: [9]})
        self.assertTrue(_has(res.warnings, "*ELEMENT_MASS: 1 nodal mass(es) "
                             "on 1 rigid body/bodies", _WA8, "(node 9)",
                             "folded into the /RBODY Mass field"),
                        res.warnings)
        r0, s0, _e0 = _convert(_plates(_emass(9, 0.01)),
                               rigid_element_mass_admas=False)
        self.assertEqual(_rbody_mass(s0, 19), 0.01)
        self.assertEqual(_admas(s0), {})
        self.assertEqual(_sha(s0), _PR8_SHA["a8_1"])

    def test_2_the_main_node_mass_stays_in_the_Mass_field(self):
        """--no-rigid-cog-master makes the lowest mesh node (1) the main:
        its own mass stays in Mass, the mass on node 9 moves to /ADMAS (it
        was DROPPED before)."""
        res, starter, _e = _convert(_plates(_emass(1, 0.02) + _emass(9, 0.01, 2)),
                                    rigid_cog_master=False)
        self.assertEqual(_rbody_mass(starter, 1), 0.02)
        self.assertEqual(_admas(starter), {0.01: [9]})
        self.assertTrue(_has(res.warnings, _WA8, "being DROPPED (1"),
                        res.warnings)

    def test_3_a_CNRB_secondary_mass_is_no_longer_lost(self):
        """A CNRB over elastic-plate nodes 10-13 with 0.01 on node 12: the
        mass was neither folded nor written (TOTAL MASS lacked it). Starter
        (a8_3, nt 4, 0 errors): the CNRB body 20's NEW MASS 0.1000118E-01,
        CoG (19.99843, 0.0003925, 5) - the 0.01 at node 12 (20, 0, 5)
        included; a8_3off: 0.1177500E-05 at (6.666667, 3.333333, 5)."""
        cnrb = (_nset(7, [10, 11, 12, 13])
                + "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(50, 0, 7) + "\n"
                + _emass(12, 0.01))
        res, starter, _e = _convert(_plates(cnrb))
        self.assertEqual(_admas(starter), {0.01: [12]})
        self.assertTrue(_has(res.warnings, _WA8, "LOST before",
                             "being DROPPED"), res.warnings)
        r0, s0, _e0 = _convert(_plates(cnrb), rigid_element_mass_admas=False)
        self.assertEqual(_admas(s0), {})
        self.assertEqual(_sha(s0), _PR8_SHA["a8_3"])

    def test_3b_two_CNRBs_are_counted_as_two_bodies(self):
        """Two CNRBs over the elastic plate (nodes 10-13 and 14-17), 0.01 on a
        secondary of each: W-A8 counts 2 masses on 2 bodies (without the
        per-body record both read as one - the mutation pass's survivor
        A8-10). Starter (a8_3b, nt 4): 0 errors."""
        cnrb = (_nset(7, [10, 11, 12, 13]) + _nset(8, [14, 15, 16, 17])
                + "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(50, 0, 7) + "\n"
                + "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(51, 0, 8) + "\n"
                + _emass(12, 0.01) + _emass(16, 0.01, 2))
        res, starter, _e = _convert(_plates(cnrb))
        self.assertEqual(_admas(starter), {0.01: [12, 16]})
        self.assertTrue(_has(res.warnings, "*ELEMENT_MASS: 2 nodal mass(es) "
                             "on 2 rigid body/bodies", _WA8), res.warnings)

    def test_4_an_ICoG_4_body_is_unchanged(self):
        """*PART_INERTIA: TM supersedes every lumped mass (the SUPERSEDED
        sentence as before), no /ADMAS."""
        pin = ("*PART_INERTIA\nrigid plate\n" + _row(1, 1, 1) + "\n"
               + _row(10.0, 10.0, 0.0, 0.01) + "\n"
               + _row(1.0, 0.0, 0.0, 1.0, 0.0, 1.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        deck = _plates(_emass(9, 0.01)).replace(
            "*PART\nrigid plate\n" + _row(1, 1, 1) + "\n", pin)
        res, starter, _e = _convert(deck)
        self.assertEqual(_admas(starter), {})
        self.assertTrue(_has(res.warnings, "is SUPERSEDED by TM=0.01"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, _WA8))
        _r0, s0, _e0 = _convert(deck, rigid_element_mass_admas=False)
        self.assertEqual(starter, s0)

    def test_5_the_momentum_average_acts_at_the_true_centre_of_mass(self):
        """A8.3: --mass-weighted-inivel forms v_cm / omega from the lumped
        masses, *ELEMENT_MASS included (the TRUE centre of mass), and the
        starter rebuilds the body about ITS centre of mass - which the fold
        put elsewhere. Rigid plate (3.14e-6) + 1e-4 on corner node 9 (20,
        20): M = 1.0314e-4, CoG x = y = 19.695559. *INITIAL_VELOCITY_NODE
        names rigid node 1 (vx 1000; the body's other nodes at rest -
        UNEQUAL nodal velocities) and the elastic nodes 10-18 (vx 1000):
        v_cm = 1.9625e-7 x 1000 / M = 1.902754, L_z = 1.9625e-7 x 19.695559
        x 1000 = 3.865254e-3, I_zz (point masses about the CoG) =
        9.228811e-4, omega_z = 4.188246; LS-DYNA's rotational KE L_z^2 /
        (2 I_zz) = 8.0943e-3. Starter + engine (a8iv_on / a8iv_off, nt 4,
        0 errors, NORMAL TERMINATION): the default's NEW X,Y 19.69556, NEW
        INERTIA zz 0.9228811E-03 and cycle-0 K-ENERGY R 0.8094E-02 = the
        closed form; the opt-out (the fold) NEW X,Y 10.0, zz 0.3140000E-03,
        K-ENERGY R 0.2754E-02 (-66 %) from the same written omega. K-ENERGY
        T 1.570 on both (the elastic plate's 1.57 + the body's 1.867e-4)."""
        mc, me, mm = 1.9625e-7, 3.925e-7, 7.85e-7
        pts = [(0.0, 0.0, mc), (10.0, 0.0, me), (20.0, 0.0, mc),
               (0.0, 10.0, me), (10.0, 10.0, mm), (20.0, 10.0, me),
               (0.0, 20.0, mc), (10.0, 20.0, me), (20.0, 20.0, mc + 1.0e-4)]
        big_m = sum(p[2] for p in pts)
        c = sum(p[0] * p[2] for p in pts) / big_m
        izz = sum(p[2] * ((p[0] - c) ** 2 + (p[1] - c) ** 2) for p in pts)
        v_cm = mc * 1000.0 / big_m
        omega = mc * c * 1000.0 / izz
        self.assertAlmostEqual(c, 19.695559, places=5)
        self.assertAlmostEqual(0.5 * (mc * c * 1000.0) ** 2 / izz / 8.0943e-3,
                               1.0, places=4)
        deck = _plates(_emass(9, 1.0e-4) + _IV_PROBE)
        for kw, mass, admas in (({}, 0.0, {1.0e-4: [9]}),
                                ({"rigid_element_mass_admas": False}, 1.0e-4,
                                 {})):
            with self.subTest(**kw):
                res, starter, _e = _convert(deck, mass_weighted_inivel=True,
                                            **kw)
                tra, rot = _inivel_mw(starter)
                self.assertAlmostEqual(tra[0] / v_cm, 1.0, places=6)
                self.assertEqual(tra[1:], (0.0, 0.0))
                self.assertEqual(rot[:2], (0.0, 0.0))
                self.assertAlmostEqual(rot[2] / omega, 1.0, places=6)
                self.assertEqual(_rbody_mass(starter, 19), mass)
                self.assertEqual(_admas(starter), admas)
                self.assertTrue(_has(res.warnings, "MOMENTUM AVERAGE"),
                                res.warnings)

    def test_6_two_bodies_share_one_ADMAS_group(self):
        """sph/foam's shape (conventions spec 0.2: BOTH foam bodies move):
        two rigid plates, 0.02 on a corner of the first (node 9) and on the
        centre of the second (node 14, its CoG). Both Mass fields 0, ONE
        /ADMAS/0 0.02 on [9, 14]. Starter (a8_6, nt 4, 0 errors): body 19
        NEW MASS 0.2000314E-01 at CoG 19.99843, body 20 0.2000314E-01 at
        (10, 10, 5) - unchanged by the move (a8_6off: 10.0 / 10.0)."""
        deck = _two_rigid_plates(_emass(9, 0.02) + _emass(14, 0.02, 2))
        res, starter, _e = _convert(deck)
        self.assertEqual(_rbody_masses(starter), [0.0, 0.0])
        self.assertEqual(_admas(starter), {0.02: [9, 14]})
        self.assertTrue(_has(res.warnings, "*ELEMENT_MASS: 2 nodal mass(es) "
                             "on 2 rigid body/bodies", _WA8), res.warnings)
        _r0, s0, _e0 = _convert(deck, rigid_element_mass_admas=False)
        self.assertEqual(_rbody_masses(s0), [0.02, 0.02])
        self.assertEqual(_admas(s0), {})


def _two_rigid_plates(extra: str) -> str:
    """_plates with the elastic plate (nodes 10-18) a second *MAT_RIGID body
    on its own material 3 (not merged)."""
    mat3 = ("*MAT_RIGID\n" + _row(3, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0)
            + "\n" + f"{0.0:10.1f}{0:10d}{0:10d}\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
    return _plates(extra).replace(
        "*PART\nelastic plate\n" + _row(2, 1, 2),
        "*PART\nrigid plate 2\n" + _row(2, 1, 3)).replace(
        "*MAT_ELASTIC", mat3 + "*MAT_ELASTIC")


def _rbody_masses(starter: str):
    """The Mass field of every /RBODY, in file order."""
    lines = starter.splitlines()
    return [float(lines[i + 3].split()[4]) for i, ln in enumerate(lines)
            if ln.startswith("/RBODY/")]


_IV_PROBE = ("*INITIAL_VELOCITY_NODE\n" + "".join(
    f"{n:>10}{1000.0:>10.1f}{0.0:>10.1f}{0.0:>10.1f}\n"
    for n in [1] + list(range(10, 19))))


def _inivel_mw(starter: str):
    """The value triples of the momentum-average /INIVEL/TRA and /ROT."""
    lines = starter.splitlines()
    out = {}
    for i, ln in enumerate(lines):
        for kind in ("TRA", "ROT"):
            if (ln.startswith(f"/INIVEL/{kind}/")
                    and lines[i + 1].startswith("InitVelMW")):
                out[kind] = tuple(float(v) for v in lines[i + 3].split()[:3])
    return out.get("TRA"), out.get("ROT")


# ═════════════════════════════════════════════════════════════════════════════
# A6 — *MAT_SPOTWELD DT -> the TYPE13 Mass / Inertia closed form
# ═════════════════════════════════════════════════════════════════════════════

def _dt_weld_deck(dt=1.0e-6, ts=2.0, e=1.0e7, ro=1.0e-6, lengths=(2.0,),
                  tfail=0.0, plate_e=210.0, endtim=1.0e-5) -> str:
    """spotweld.k's weld on soft plates: *MAT_SPOTWELD E *e*, PR 0.3, RO *ro*,
    DT *dt*, SIGY 0 (elastic), *SECTION_BEAM TS1 = TS2 = *ts*; one ELFORM-9
    beam per entry of *lengths* (from z = 0 to z = L). The plates are soft
    (E *plate_e*) so the WELD controls the time step."""
    base = [(1, 0.0, 0.0, 0.0), (2, 5.0, 0.0, 0.0), (3, 5.0, 5.0, 0.0),
            (4, 0.0, 5.0, 0.0)]
    nodes = list(base)
    beams = []
    for k, ln in enumerate(lengths):
        # top plate k (ids 10(k+1)..+3) at z = L_k; weld k from base node
        # k+1 straight up to the top node above it: length exactly L_k
        top = [(10 * (k + 1) + i, x, y, ln) for i, (_n, x, y, _z)
               in enumerate(base)]
        nodes += top
        beams.append((100 + k, base[k][0], top[k][0]))
    lines = ["*KEYWORD", "*CONTROL_TERMINATION", _row(endtim), "*NODE"]
    lines += [f"{n:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}" for n, x, y, z in nodes]
    lines += ["*PART", "plates", _row(1, 1, 1),
              "*SECTION_SHELL", _row(1, 2), _row(1.0),
              "*MAT_ELASTIC", _row(1, 7.85e-9, plate_e, 0.3), "*ELEMENT_SHELL",
              "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4))]
    for k in range(len(lengths)):
        b = 10 + 10 * k
        lines.append("".join(f"{v:>8}" for v in (2 + k, 1, b, b + 1, b + 2,
                                                  b + 3)))
    lines += ["*PART", "weld", _row(10, 10, 10),
              "*SECTION_BEAM", _row(10, 9, 1.0, 4, 1), _row(ts, ts, 0.0, 0.0),
              "*MAT_SPOTWELD", _row(10, ro, e, 0.3, 0.0, 0.0, dt, tfail),
              _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), "*ELEMENT_BEAM"]
    for k, (eid, n1, n2) in enumerate(beams):
        lines.append("".join(f"{v:>8}" for v in (eid, 10, n1, n2)))
    return "\n".join(lines) + "\n*END\n"


def _type13_mass_inertia(starter: str):
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/PROP/TYPE13/"):
            v = lines[i + 3].split()
            return float(v[0]), float(v[1])
    return None


class SpotweldDtClosedForm(unittest.TestCase):
    """A6 (round 8): *MAT_SPOTWELD DT was dropped ('no /PROP/TYPE13 slot').
    Vol II R17 *MAT_SPOTWELD Remark 4 scales the weld inertias UP so the
    stable step is DT; the TYPE13 step is 0.9 min(sqrt(M / max K1..3),
    sqrt(I / (max K4..6 + max K2,3 L^2))) (r2len3.F:221-247, STI = XM/DT^2 at
    :233), so Mass' = max(M, max K1..3 DT^2) and Inertia' = max(I, (max K4..6
    + max K2,3 L_max^2) DT^2)."""

    def test_1_spotweld_k_weld(self):
        """A = pi (d 2), L 2, E 1e7, nu 0.3, RO 1e-6, DT 1e-6: K1 15707963.3,
        K2 = K3 6041524.3, K4 3020762.1, K5 = K6 3926990.8; Mass 6.283185e-6
        -> K1 DT^2 = 1.570796e-5 (x2.5), Inertia 2.094395e-6 -> (3926990.8 +
        6041524.3 x 4) 1e-12 = 2.809309e-5 (x13.41). Starter + engine
        (a6_coupon_br, nt 4, 0 errors, NORMAL TERMINATION): the starter's
        SPRING time step 9.9999990E-07 for element 100 (= DT), the engine's
        step 0.9000E-06 on SPRING 100 on all 12 printed cycles (0..11),
        TOTAL MASS 0.1610E-04."""
        res, starter, _e = _convert(_dt_weld_deck())
        m, i = _type13_mass_inertia(starter)
        self.assertAlmostEqual(m / 1.570796e-5, 1.0, places=6)
        self.assertAlmostEqual(i / 2.809309e-5, 1.0, places=6)
        self.assertIn("        1.570796E-05        2.809309E-05", starter)
        self.assertTrue(_has(res.warnings, "DT=1e-06 -> /PROP/TYPE13/",
                             "Mass x 2.5, Inertia x 13.41", "r2len3.F:221-247",
                             "starts at 0.9 DT"), res.warnings)
        self.assertFalse(_has(res.warnings, "have no /PROP/TYPE13 slot"))

    def test_2_an_inert_DT_changes_no_byte(self):
        """plates.mat100's weld card (DT 1e-9): both factors stay 1, the
        bytes equal the opt-out's, and the sentence says inert."""
        deck = _t7._weld_deck()
        res, starter, _e = _convert(deck)
        _r0, s0, _e0 = _convert(deck, spotweld_dt_mass_scaling=False)
        self.assertEqual(starter, s0)
        self.assertTrue(_has(res.warnings, "DT=1e-09 is inert",
                             "2.99951e-7 s with DT 1e-9"), res.warnings)
        self.assertTrue(_has(_r0.warnings, "DT have no /PROP/TYPE13 slot"))

    def test_3_the_longest_weld_sets_the_inertia(self):
        """Welds 2.0 and 3.0 on one part: K from the MEAN length 2.5, the
        rotational term from L_max = 3.0."""
        res, starter, _e = _convert(_dt_weld_deck(lengths=(2.0, 3.0)))
        a = math.pi
        g = 1.0e7 / 2.6
        k23 = g * a / 2.5
        k56 = 1.0e7 * (math.pi / 4.0) / 2.5
        k4 = g * (math.pi / 2.0) / 2.5
        _m, i = _type13_mass_inertia(starter)
        want = (max(k4, k56) + k23 * 3.0 ** 2) * 1.0e-12
        self.assertAlmostEqual(i / want, 1.0, places=6)
        self.assertNotAlmostEqual(
            i / ((max(k4, k56) + k23 * 2.5 ** 2) * 1.0e-12), 1.0, places=3)

    def test_4_a_token_weld_takes_the_closed_form_too(self):
        """RO 0 (no density floor): the 1e-4 token weld; with DT 1e-5 the
        closed form raises it to K1 DT^2 = 1.570796e-3 (decision D11), and
        the weld stays a token property (its 1e-4 still comes off its ends
        as before; the added DT mass stays). With DT 1e-6 (K1 DT^2 =
        1.57e-5 < 1e-4) the token already exceeds it: inert."""
        res, starter, _e = _convert(_dt_weld_deck(ro=0.0, dt=1.0e-5),
                                    zero_density_floor=False)
        m, _i = _type13_mass_inertia(starter)
        self.assertAlmostEqual(m / 1.570796e-3, 1.0, places=6)
        self.assertTrue(_has(res.warnings, "DT=1e-05 -> /PROP/TYPE13/"))
        r6, _s6, _e6 = _convert(_dt_weld_deck(ro=0.0),
                                zero_density_floor=False)
        self.assertTrue(_has(r6.warnings, "DT=1e-06 is inert"), r6.warnings)
        self.assertTrue(_has(res.warnings, "token mass 0.0001 used"),
                        res.warnings)

    def test_5_the_opt_out_drops_DT_as_4f5b6e8(self):
        res, starter, _e = _convert(_dt_weld_deck(),
                                    spotweld_dt_mass_scaling=False)
        self.assertEqual(_sha(starter), _PR8_SHA["a6_off"])
        self.assertTrue(_has(res.warnings, "DT have no /PROP/TYPE13 slot"))


# ═════════════════════════════════════════════════════════════════════════════
# A5 — the adaptive spring token MASS with the driven-end skip
# ═════════════════════════════════════════════════════════════════════════════

_BIG = 1.0e28


def _a5_coupon(m1=1.0e-9, m2=1.0e-9, p2=(10.0, 0.0), extra="", n2=2,
               tc1=0) -> str:
    """The g3n coupon P: one *ELEMENT_DISCRETE 101 (K 100,
    *MAT_SPRING_ELASTIC) from node 1 (0, 0, 0; *NODE TC *tc1*) to node *n2*
    at *p2* (n2 = 0: grounded), *ELEMENT_MASS m1 / m2 on nodes 1 / 2, TSSFAC
    0.9, t_end 0.02, GLSTAT every 1e-4; curve 1 = 100 (the motions' speed);
    *extra* carries the end conditions."""
    return ("*KEYWORD\n*TITLE\nA5 adaptive token coupon\n"
            "*CONTROL_TERMINATION\n" + _row(0.02) + "\n"
            "*CONTROL_TIMESTEP\n" + _row(0.0, 0.9) + "\n"
            "*DATABASE_GLSTAT\n" + _row(1.0e-4) + "\n"
            "*PART\nsprings\n" + _row(100, 100, 100) + "\n"
            "*SECTION_DISCRETE\n" + _row(100, 0) + "\n" + _row(0.0, 0.0) + "\n"
            "*MAT_SPRING_ELASTIC\n" + _row(100, 100.0) + "\n"
            "*DEFINE_CURVE\n" + _row(1) + "\n"
            + f"{0.0:>20.1f}{100.0:>20.1f}\n{1.0:>20.1f}{100.0:>20.1f}\n"
            "*NODE\n"
            + f"{1:>8}{0.0:>16.7f}{0.0:>16.7f}{0.0:>16.7f}{tc1:>8}{0:>8}\n"
            + f"{2:>8}{p2[0]:>16.7f}{p2[1]:>16.7f}{0.0:>16.7f}\n"
            "*ELEMENT_DISCRETE\n"
            + f"{101:>8}{100:>8}{1:>8}{n2:>8}{0:>8}{1.0:>16.1f}{0:>8}"
              f"{0.0:>16.1f}\n"
            "*ELEMENT_MASS\n"
            + f"{201:>8}{1:>8}{m1:>16.6E}{0:>8}\n"
            + f"{202:>8}{2:>8}{m2:>16.6E}{0:>8}\n"
            + extra + "*END\n")


def _pm(nid, dof=1, vad=0, sf=1.0, vid=0, death=_BIG, birth=0.0) -> str:
    """*BOUNDARY_PRESCRIBED_MOTION_NODE on curve 1."""
    return ("*BOUNDARY_PRESCRIBED_MOTION_NODE\n"
            + f"{nid:>10}{dof:>10}{vad:>10}{1:>10}{sf:>10.1f}{vid:>10}"
              f"{death:>10.3G}{birth:>10.3G}\n")


def _spcn(nid, code="111", cid=0) -> str:
    """*BOUNDARY_SPC_NODE: the translations of *code*, no rotation."""
    return ("*BOUNDARY_SPC_NODE\n"
            + f"{nid:>10}{cid:>10}" + "".join(f"{int(c):>10}" for c in code)
            + f"{0:>10}{0:>10}{0:>10}\n")


_D_COUPONS = {
    # g3n: D1 node 1 driven (light), node 2 heavy; D2 both light; D3 both
    # ends driven (gnonspring's class); D4 the spring at 45 degrees, node 2
    # driven along x only, so NOT along the spring
    "D1": dict(m1=1.0e-9, m2=1.0e-3, extra=_pm(1)),
    "D2": dict(m1=1.0e-9, m2=1.0e-9, extra=_pm(1)),
    "D3": dict(m1=1.0e-6, m2=1.0e-6, extra=_spcn(1) + _pm(2)),
    "D4": dict(m1=1.0e-9, m2=1.0e-9, p2=(10.0 / 2 ** 0.5, 10.0 / 2 ** 0.5),
               extra=_spcn(1) + _pm(2)),
}

# one source per row: (name, coupon kwargs, the cell)
_A5_SOURCES = (
    ("global SPC", dict(extra=_spcn(1, "100")), "2.000000E-09"),
    ("*NODE TC", dict(tc1=1), "2.000000E-09"),
    ("*CONSTRAINED_GLOBAL", dict(extra="*CONSTRAINED_GLOBAL\n"
                                 + _row(1, 0, 1, 0.0, 0.0, 0.0, 0.01) + "\n"),
     "2.000000E-09"),
    ("SF-0 motion", dict(extra=_pm(1, sf=0.0)), "2.000000E-09"),
    ("/IMPVEL whole run", dict(extra=_pm(1, vad=0)), "2.000000E-09"),
    ("/IMPDISP whole run", dict(extra=_pm(1, vad=2)), "2.000000E-09"),
    ("/IMPACC whole run", dict(extra=_pm(1, vad=1)), "2.000000E-09"),
    ("rigid member", dict(extra=(
        "*NODE\n" + f"{3:>8}{0.0:>16.7f}{5.0:>16.7f}{0.0:>16.7f}\n"
        "*SET_NODE_LIST\n" + _row(77) + "\n" + _row(1, 3) + "\n"
        "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(88, 0, 77) + "\n")),
     "2.000000E-09"),
    # PNODE 1: node 1 IS the CNRB's main node (/RBODY/1); nodes 3 / 4 carry
    # 1e-6 each so the body's inertia is not degenerate (starter ERROR 274
    # without them)
    ("CNRB main", dict(extra=(
        "*NODE\n" + "".join(f"{n:>8}{x:>16.7f}{5.0:>16.7f}{0.0:>16.7f}\n"
                            for n, x in ((3, 0.0), (4, 5.0)))
        + "*ELEMENT_MASS\n" + f"{203:>8}{3:>8}{1.0e-6:>16.6E}{0:>8}\n"
        + f"{204:>8}{4:>8}{1.0e-6:>16.6E}{0:>8}\n"
        + "*SET_NODE_LIST\n" + _row(77) + "\n" + _row(3, 4) + "\n"
        "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(88, 0, 77, 1) + "\n")),
     "2.000000E-09"),
    ("ground (N2 = 0)", dict(n2=0), "2.000000E-09"),
    ("SYSTEM-CID SPC", dict(extra=(
        "*DEFINE_COORDINATE_SYSTEM\n" + _row(5, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0)
        + "\n" + _row(-1.0, 1.0, 0.0) + "\n" + _spcn(1, "111", cid=5))),
     "1.000000E-09"),
    # DOF 4 along *DEFINE_VECTOR 7 = the vector's own /SKEW: a LOCAL motion,
    # not counted even though this vector IS the spring's axis (the rule
    # never reads a skew's axes - conservative)
    ("local motion", dict(extra=(
        "*DEFINE_VECTOR\n" + _row(7, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
        + _pm(1, dof=4, vid=7))), "1.000000E-09"),
    ("tied secondary", dict(extra=(
        "*NODE\n" + "".join(f"{n:>8}{x:>16.7f}{y:>16.7f}{0.0:>16.7f}\n"
                            for n, x, y in ((3, -5.0, -5.0), (4, 5.0, -5.0),
                                            (5, 5.0, 5.0), (6, -5.0, 5.0)))
        + "*PART\nplate\n" + _row(9, 9, 9) + "\n"
        "*SECTION_SHELL\n" + _row(9, 2) + "\n" + _row(1.0, 1.0, 1.0, 1.0)
        + "\n*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
        "*ELEMENT_SHELL\n" + _row(9, 9, 3, 4, 5, 6) + "\n"
        "*SET_NODE_LIST\n" + _row(66) + "\n" + _row(1) + "\n"
        "*CONTACT_TIED_NODES_TO_SURFACE\n" + _row(66, 9, 4, 3) + "\n"
        + _row() + "\n" + _row() + "\n")), "1.000000E-09"),
)


def _weld_tie_deck(spc: str = "") -> str:
    """LightClauseNumbers test_5's shape: a *CONSTRAINED_SPOTWELD tie
    (TYPE13) between corners 1 / 11 of two 10 x 10 x 1 shells 2 mm apart
    (own 1.9625e-7 each); *spc* = node 1's SPC translation code."""
    def plate(nid0, z0, eid, pid):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        nodes = "".join(f"{nid0 + i:>8}{x:>16.4f}{y:>16.4f}{z0:>16.4f}\n"
                        for i, (x, y) in enumerate(pts))
        return nodes, _row(eid, pid, nid0, nid0 + 1, nid0 + 2,
                           nid0 + 3) + "\n"

    n1, e1 = plate(1, 0.0, 1, 1)
    n2, e2 = plate(11, 2.0, 2, 2)
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n" + n1 + n2 + "*ELEMENT_SHELL\n" + e1 + e2
            + "*PART\nplate1\n" + _row(1, 1, 1) + "\n"
            "*PART\nplate2\n" + _row(2, 1, 1) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            "*CONSTRAINED_SPOTWELD\n" + _row(1, 11, 1.0e4, 5.0e4) + "\n"
            + (_spcn(1, spc) if spc else "") + "*END\n")


def _token_cells(starter: str):
    """The printed MASS cell of every /PROP/TYPE4 | TYPE8 | TYPE13 block."""
    lines = starter.splitlines()
    return [lines[i + 3][:20].strip() for i, ln in enumerate(lines)
            if ln.startswith(("/PROP/TYPE4/", "/PROP/TYPE8/",
                              "/PROP/TYPE13/"))]


_WA5 = "spring token: MASS set from the end-node masses"


class AdaptiveSpringToken(unittest.TestCase):
    """A5 (round 8): a token /PROP steps on its PROPERTY mass (r1len3.F:175
    sqrt(M / K)), and the S2 screen takes the token back off light ends, so
    a light compensated end could outrun it silently. MASS := max(1.1e-15,
    min(1e-4, 2 mu min(1, 2/n))) per /PROP from the end-node masses; a
    rigid, ground or DRIVEN end (held or imposed along the spring for the
    whole run) counts infinitely heavy, a spring with both ends infinite
    keeps the token, a guarded end sets no cap. Starter + engine runs in
    each docstring (nt 4, rcv_r8i_implA_<name>, harvested and deleted)."""

    def test_1_the_g3n_coupons(self):
        """D1 (driven light end + free heavy end, cap 2e-3) and D3 (both
        driven) keep 0.0001; D2 (driven + free 1e-9) and D4 (node 2 driven
        along x, the spring at 45 degrees: not along it) -> 2 x 1e-9.
        ENGINE RECORDS: see the a5_* rows of the report."""
        for name, want in (("D1", "0.0001"), ("D2", "2.000000E-09"),
                           ("D3", "0.0001"), ("D4", "2.000000E-09")):
            with self.subTest(coupon=name):
                _r, starter, _e = _convert(_a5_coupon(**_D_COUPONS[name]))
                self.assertEqual(_token_cells(starter), [want])

    def test_1b_the_i14_coupon_and_its_guarded_spring(self):
        """Round 6's i14 coupon: node 20 (own 1.9625e-13, n 4 at node 10)
        bounds the shared /PROP 90003 -> 1.9625e-13; node 40 (no own mass)
        is GUARDED and its spring carries the smaller MASS (decision D7):
        the share left on it 9.8125e-14, named."""
        res, starter, _e = _convert(_t6._I14_COUPON)
        self.assertEqual(_token_cells(starter), ["1.962500E-13"])
        self.assertIn("/PROP/TYPE4/90003", starter)
        self.assertTrue(_has(res.warnings, _WA5, "(90003: 0.0001 -> "
                             "1.9625e-13)", "1 guarded spring(s)"),
                        res.warnings)
        self.assertTrue(_has(res.warnings, "carry NO element mass of their "
                             "own", "the token share left on them (node 40: "
                             "9.8125e-14)"), res.warnings)

    def test_2_one_probe_per_driven_source(self):
        for name, kw, want in _A5_SOURCES:
            with self.subTest(source=name):
                res, starter, _e = _convert(_a5_coupon(**kw))
                self.assertEqual(_token_cells(starter), [want], res.warnings)

    def test_3_the_axis_tolerance(self):
        """Node 1 held in x only: the spring's free-direction components
        must stay <= 1e-6 (1e-7 drives, 1e-5 does not)."""
        for y2, want in ((1.0e-6, "2.000000E-09"), (1.0e-4, "1.000000E-09")):
            with self.subTest(y2=y2):
                _r, starter, _e = _convert(_a5_coupon(
                    p2=(10.0, y2), extra=_spcn(1, "100")))
                self.assertEqual(_token_cells(starter), [want])

    def test_4_a_TYPE13_needs_all_three_translations(self):
        """The weld tie (TYPE13): node 1 SPC 110 is not driven (mu =
        1.9625e-7 / 2 -> 1.9625e-7), 111 is (mu = 1.9625e-7 -> 3.925e-7)."""
        for spc, want in (("110", "1.962500E-07"), ("111", "3.925000E-07")):
            with self.subTest(spc=spc):
                _r, starter, _e = _convert(_weld_tie_deck(spc))
                self.assertEqual(_token_cells(starter), [want])

    def test_5_Ileng_1_is_per_unit_length(self):
        """T5's cable (Ileng 1, L 10): cap 9.8125e-8 per element -> 9.8125e-9
        per unit length; each end sheds 0.5 x 9.8125e-9 x 10."""
        _r, starter, _e = _convert(_t5._CABLE_DECK.replace("%RO%",
                                                           "      0.0"),
                                   zero_density_floor=False)
        self.assertEqual(_token_cells(starter), ["9.812500E-09"])
        self.assertEqual(_t5._admas_cards(starter), {-4.90625e-08: [1, 2]})

    def test_6_the_floor(self):
        _r, starter, _e = _convert(_a5_coupon(m1=1.0e-16, m2=1.0e-16))
        self.assertEqual(_token_cells(starter), ["1.100000E-15"])

    def test_7_inert_without_compensation_and_the_opt_out(self):
        deck = _a5_coupon(**_D_COUPONS["D2"])
        _r, starter, _e = _convert(deck,
                                   spring_token_mass_compensation=False)
        self.assertEqual(_token_cells(starter), ["0.0001"])
        res, s0, _e0 = _convert(deck, adaptive_spring_token=False)
        self.assertEqual(_token_cells(s0), ["0.0001"])
        self.assertEqual(_sha(s0), _PR8_SHA["a5_d2"])
        # the 4f5b6e8 warnings but for the r2len3.F citation the fix round
        # corrected (:182-186 is the nodal-step / AMS branch; the default
        # element step is :221-247)
        joined = "\n".join(res.warnings)
        self.assertIn("r2len3.F:221-247", joined)
        self.assertEqual(
            _sha(joined.replace("r2len3.F:221-247", "r2len3.F:182-186")),
            _PR8_WARN_SHA["a5_d2"])
        self.assertFalse(_has(res.warnings, _WA5))

    def test_8_a_windowed_motion_is_not_driving(self):
        """BIRTH 0.005 or DEATH 0.01 inside t_end 0.02 -> not driven
        (1e-9); the whole run -> 2e-9. ENGINE RECORDS: see the report."""
        for kw, want in ((dict(birth=0.005), "1.000000E-09"),
                         (dict(death=0.01), "1.000000E-09"),
                         (dict(), "2.000000E-09")):
            with self.subTest(**kw):
                _r, starter, _e = _convert(_a5_coupon(extra=_pm(1, **kw)))
                self.assertEqual(_token_cells(starter), [want])

    def test_9_a_both_driven_spring_is_DRIVEN_in_the_light_clause(self):
        """D3: both ends held along the spring for the whole run -> the token
        is kept and the light end is labelled DRIVEN, never compared."""
        res, _s, _e = _convert(_a5_coupon(**_D_COUPONS["D3"]))
        w = [x for x in res.warnings if "was REMOVED again" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("DRIVEN (both ends of spring 101", w[0])
        self.assertIn("bcs1.F:56-89 / fixvel.F:370-372", w[0])
        self.assertNotIn("UNPROTECTED", w[0])

    def test_10_a_DT_raised_token_weld_is_left_alone(self):
        """A token weld (RO 0) whose *MAT_SPOTWELD DT raised its Mass (A6,
        decision D11) is not a token any more: its step is 0.9 DT and the
        raised part stays on its ends as LS-DYNA's added mass, so A5 does not
        rewrite it (the cell differs from the token its springs
        registered)."""
        res, starter, _e = _convert(_dt_weld_deck(ro=0.0, dt=1.0e-5),
                                    zero_density_floor=False)
        self.assertEqual(_token_cells(starter), ["0.001570796327"])
        self.assertFalse(_has(res.warnings, _WA5))


# ═════════════════════════════════════════════════════════════════════════════
# A9 — records and the part-A guards
# ═════════════════════════════════════════════════════════════════════════════

#: g3o's PREV8/r8pre/g3o/probe/mrg_flat.k, inlined: two *MAT_RIGID 20 x 20
#: plates (2 x 2 quads, T 2.0, RO 7.85e-9) side by side, sharing the nodes at
#: x = 20, merged by *CONSTRAINED_RIGID_BODIES 1 2.
_MRG_FLAT = """*KEYWORD
*TITLE
g3o merge probe flat
*CONTROL_TERMINATION
    1.0E-6
*DATABASE_GLSTAT
    1.0E-7
*PART
plate A
         1         1         1
*PART
plate B
         2         1         2
*SECTION_SHELL
         1         2       1.0         2
    2.0000    2.0000    2.0000    2.0000
*MAT_RIGID
         1 7.850E-09  200000.0       0.3
       0.0         0         0
       0.0       0.0       0.0       0.0       0.0       0.0
*MAT_RIGID
         2 7.850E-09  200000.0       0.3
       0.0         0         0
       0.0       0.0       0.0       0.0       0.0       0.0
*CONSTRAINED_RIGID_BODIES
         1         2         0
*NODE
       1        0.000000        0.000000        0.000000       0       0
       2       10.000000        0.000000        0.000000       0       0
       3       20.000000        0.000000        0.000000       0       0
       4        0.000000       10.000000        0.000000       0       0
       5       10.000000       10.000000        0.000000       0       0
       6       20.000000       10.000000        0.000000       0       0
       7        0.000000       20.000000        0.000000       0       0
       8       10.000000       20.000000        0.000000       0       0
       9       20.000000       20.000000        0.000000       0       0
     101       30.000000        0.000000        0.000000       0       0
     102       40.000000        0.000000        0.000000       0       0
     103       30.000000       10.000000        0.000000       0       0
     104       40.000000       10.000000        0.000000       0       0
     105       30.000000       20.000000        0.000000       0       0
     106       40.000000       20.000000        0.000000       0       0
*ELEMENT_SHELL
       1       1       1       2       5       4
       2       1       2       3       6       5
       3       1       4       5       8       7
       4       1       5       6       9       8
       5       2       3     101     103       6
       6       2     101     102     104     103
       7       2       6     103     105       9
       8       2     103     104     106     105
*END
"""


class Round8Records(unittest.TestCase):
    """A9.3: round 7's merge byte test (T7
    RigidShellRotaryInertiaDefault.test_5) pins bytes only; this one carries
    the starter record of the same rule."""

    def test_a_merged_body_takes_SUM_IN_once_over_the_union(self):
        """ONE /RBODY for the merged pair, J = -SUM(IN) over the union =
        -1.088533e-4 on all three (a per-body sum would read -1.360667e-4:
        the shared x = 20 nodes counted twice). Starter (a9_mrg, nt 4, 0
        errors): NEW MASS 0.1256000E-04, NEW INERTIA 0.6280000E-03 /
        0.1884000E-02 / 0.2512000E-02 with zero products = the point-mass
        tensor to the 7 printed digits."""
        _r, starter, _e = _convert(_MRG_FLAT)
        self.assertEqual(starter.count("\n/RBODY/"), 1)
        for v in _j_row(starter):
            self.assertAlmostEqual(v / -1.088533333e-4, 1.0, places=8)


class Round8FlagWiringA(_t7.Round7FlagWiringA):
    """A9.4: every round-8 part-A lever reaches the parser (with its --no-
    twin), the README prose, the --help render with its measured figures,
    the GUI end to end, convert() / ConvertOptions (default True) and
    cli.main()'s call - the round-7 checks, for this round's nine flags."""

    _FLAGS = {
        "--rigid-local-constraints": "rigid_local_constraints",
        "--bcs-union": "bcs_union",
        "--bolt-rigid-contact": "bolt_rigid_contact",
        "--fixed-curve-columns": "fixed_curve_columns",
        "--section-nodal-thickness-mean": "section_nodal_thickness_mean",
        "--plane-strain-unit-thickness": "plane_strain_unit_thickness",
        "--rigid-element-mass-admas": "rigid_element_mass_admas",
        "--spotweld-dt-mass-scaling": "spotweld_dt_mass_scaling",
        "--adaptive-spring-token": "adaptive_spring_token",
    }
    _HELP_FIGURES = {
        "--rigid-local-constraints": ("+100.10 % -> +0.05 %",
                                      "RMS 44.81 -> 0.006 %", "CON1",
                                      "hm_read_bcs.F:199-205", "ERROR 148",
                                      "-99.97 % -> +0.13 %"),
        "--bcs-union": ("WARNING 312", "1592 = 1592", "hm_read_bcs.F:198",
                        "MY_OR"),
        "--bolt-rigid-contact": ("-81.87 % -> -8.49 %", "1.131x",
                                 "68 CNRB 110 / 120 members",
                                 "31.32 / 28.24 -> 9.19 / 10.22 %"),
        "--fixed-curve-columns": ("2E20.0", "/FUNCT/11 kept 2 of 4 points",
                                  "IE END +19.20 %"),
        "--section-nodal-thickness-mean": (
            "0.0888 / 0.0655 / 0.0555 -> 0.0223 / 0.0164 / 0.0139",
            "7.54 / 65.93 -> 2.89 / 29.15 %", "-4.39 -> -17.88 %"),
        "--plane-strain-unit-thickness": ("0.08756308 -> 0.003447366",
                                          "Remark 6"),
        "--rigid-element-mass-admas": ("121.4891 -> 150.9633", "150.96326"),
        "--spotweld-dt-mass-scaling": ("r2len3.F:221-247", ":233",
                                       "0.9 DT", "x2.5", "x13.41",
                                       "last cycle 1332"),
        "--adaptive-spring-token": ("2 mu min(1, 2/n)", "1.1e-15",
                                    "1e-4 -> 5.483321e-7", "1.000x",
                                    "3-6 cycles", "r1len3.F:175"),
    }


#: Part-A statements a round-8 measurement superseded. CHANGELOG may quote
#: them (it is the history); no other shipped text may.
_RETRACTED_ROUND_8_A = (
    # A2 (l)-4: the partial-rigid sentence and the 'run sensitivity' texts
    "MOSTLY USELESS",
    "COLLAPSES to -62.05",
    "-62.05 %",
    "moves too, by run sensitivity",
    "by run sensitivity, not by the yield",
    "moves by run sensitivity",
    # A6.5: round 7's x13.42 'calibration' and its STI claim
    "calibration ×13.42",
    "×13.42 reaches",
    "STI formula was not located",
    "+7.85 % at the matched end",
    # the fix round: the retraction NOTES may not re-ship the number either
    # (README / ROADMAP / state.py quoted it; only CHANGELOG may)
    "×13.42", "x13.42", "13.42 was", "the 91.2 % was",
    # A4: the critic's attributions of cup-draw's energy error
    "not caused by the cell",
    "the mass cell does not create it",
    "pre-existing balance problem",
)

#: ... and the new spellings, which ARE shipped: (file, text).
_REPLACEMENTS_ROUND_8_A = (
    ("k2rad/cli.py", "the row was hypersensitive because its /PRELOAD/AXIAL "
                     "bolt collapsed"),
    ("README.md", "the row was hypersensitive because its"),
    ("ROADMAP.md", "**closed in round 8 by the closed form**"),
    ("ROADMAP.md", "the IE END it read at the matched end was an artefact "
                   "of that mass"),
    ("ROADMAP.md", "takes ΣIN once over the union — MEASURED (round 8)"),
    ("k2rad/writer/mesh.py", "OpenRadioss's energy error grows: mean -4.39 "
                             "-> -17.88 %"),
)


class Round8RetractedStatementsA(unittest.TestCase):
    """A9.4: no shipped text (README, ROADMAP, the GUI, every package
    module, docs/*.md, tools/*.py; CHANGELOG exempt) carries a retracted
    part-A spelling; the guard fires on each needle split across two
    adjacent literals; a PREFIX still fires; the replacements ARE
    shipped."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _t7._SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_8_A:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_8_A:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "')
                        + ' y')
                self.assertIn(_t7._collapse(needle).lower(), _t7._collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_8_A:
            with self.subTest(needle=needle):
                self.assertIn(_t7._collapse(needle[:max(8, len(needle) // 2)]),
                              _t7._collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_t7._SHIPPED_TEXTS())
        for rel, needle in _REPLACEMENTS_ROUND_8_A:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_t7._collapse(needle), texts[key])


def _A3_DECKS():
    return {"t1": _plates(_spc_node(14, 0, "111111") + _spc_node(14, 0, "111111")),
            "t2": _plates(_P2_SHARED),
            "t5": _plates(_IMP + _free_node() + _spc_node(50, 0, "110001")),
            "t6": _plates(_IMP + _free_node(tc=4)),
            "t7": _plates(_spc_node(1, 0, "010000") + _spc_node(2, 0, "011000"))}


def _OPT_OUT_DECKS():
    """The (l) probes, keyed like _PR8_SHA."""
    cnrb = _a1_deck(tc=0, extra=_VEC3 + (
        "*SET_NODE_LIST\n" + _row(7) + "\n"
        + _row(10, 11, 12, 13, 14, 15, 16, 17) + "\n" + _row(18)
        + "\n*CONSTRAINED_NODAL_RIGID_BODY_SPC\n" + _row(50, 0, 7)
        + "\n" + _row(-1.0, 3, 110000) + "\n"))
    return {"a": _cmo(3, 100111, _VEC3),
            "d": _cmo(7, 100000, _nod7(1)),
            "e": _cmo(0, 110111),
            "j": _cmo(3, 100000, _VEC3, tc=3),
            "o": cnrb}


# SHA-256 of the 4f5b6e8 starter file / warning list of each probe, measured
# from the pristine checkout C:/Users/pmqua/PycharmProjects/k2rad-wt-pristine8
# (PYTHONDONTWRITEBYTECODE=1; git status --porcelain --ignored empty before and
# after). Filled by SCR/r8/implA_work/pin_sha8.py.
_PR8_SHA = {
    "a": "1137e557f9a81a472b4a474f8f1add8bd56eab8e4449e8732caef00fe29e2369",
    "d": "975064aae26bfaf6ca08781c04e61d9c9090059c2e108211d79d8e1b8dd9df60",
    "e": "b228b477ae7c894186449db09b7c6169fd2f6b6823f41d5ffe7a5e013a378fa5",
    "j": "1e79e2362280c85a1e11690c5da28bdf312b7a7e0ccf9dc2a855cbb48942fbab",
    "o": "8c3d5135082bf7ea3a345ba3a7bca07e1ad1e53c33901b700a5070819b10bee8",
    "p1": "ac5e5999f2e6d2f30573a6394fe0a13170ebeb86499c5dfd3b55671856e0f7bb",
    "p2": "e590033746a3c2519a1afc298c208cec7621a397010195f10934d1a5585801d2",
    "t1": "1a7619913c039e8af216b50dbaca64b291a9b3f0206b86c0775ea5d2f0ce151f",
    "t2": "9f219b9a06fffd711d7d0f69691480ba5df8fb9b525ca2fc749d1b3558cce203",
    "t5": "8db993b10febc693848c688d07b6d3ebeab8a3c4f0db63bd9e3c9afc4675656d",
    "t6": "71c4891f4964f5e3cf349de4222351ab0043b41141757559db5caa1ccf7f41dc",
    "t7": "748a64ea6d848388762e6cfcbeb7fc5f5db1dd9e0cac352580b4b45342fe2cc0",
    "a4_uniform": "e4d1017e1bde702f54c51eafd66b994945a9287a9b9d8ebc4bd9e9b9b2c2c382",
    "a4_rigid": "9ce06be37a721237c58e1df030acf1f45595ad19fe037a7d62568fec28463dc4",
    "a7_rigid": "a500d7f4cc93b80a80f91986eabc07b14d8e7982e5c647416a14551b7efaa001",
    "a8_1": "feb58b9abe31c1bbd111ba949ad80ef936aca3f9de8fed087ffd394dde68291d",
    "a8_3": "241040e6b0db056d11d4de8656eee7dfd50c2d5c892ac854ddb18b1646e44324",
    "a6_off": "64223e00c130ddcb62abf0c71ef419539eeb107864555ca1d35ed2ea5ab0dcbb",
    "a5_d2": "5594ae707bfb4b925e9ef81034f93e0fb6644f4a060b364d4953350421f5fd2b",
}
_PR8_WARN_SHA = {
    "a": "02c3df87ca83a12d9f437789ad15ab19a028efd5cb0d22e4617e5cfbb385a325",
    "d": "575a7470039d51c90a8786c87752ccfcc607f7ab59916377555dd9a42a1fee64",
    "e": "02c3df87ca83a12d9f437789ad15ab19a028efd5cb0d22e4617e5cfbb385a325",
    "j": "2e5113acdacb3e65d25737a27722e6b42670d61fa0bad24c1483c8ef51059258",
    "o": "cbee9879c41b3e6d9c1c3664ee4c4f17406477c9b2e2a27f4a02a31ba1dcc09a",
    "a5_d2": "cfa0c72ad12c7fdc53e990d1d8dc26bfb17bca097a01386008263cfbbd8ada20",
}


# ═════════════════════════════════════════════════════════════════════════════
# PART B (implement agent B)
# ═════════════════════════════════════════════════════════════════════════════

from k2rad import handlers as _handlers  # noqa: E402
from k2rad.writer.common import _f  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# B1 - *CONTROL_IMPLICIT_GENERAL IMFLAG 0 + *CONTROL_IMPLICIT_EIGENVALUE NEIG 0
#      -> the EXPLICIT route (default ON, --no-imflag0-eigen-explicit)
# ─────────────────────────────────────────────────────────────────────────────


def _eig_deck(imflag="0", neig="0", order="eig_first", general=True,
              extra="", n_general=1, first_imflag="1") -> str:
    """Four ELFORM-2 *MAT_ELASTIC shells on a 3 x 3 node grid (10 mm), the
    x = 0 edge held, a *LOAD_NODE_POINT on the far corner, t_end 0.001,
    *CONTROL_IMPLICIT_EIGENVALUE with NEIG as TEXT (a blank can be written)
    and, when *general*, *CONTROL_IMPLICIT_GENERAL with IMFLAG as text in
    the given card order (*n_general* 2 states ``first_imflag`` first)."""
    nodes = "*NODE\n" + "".join(
        f"{3 * j + i + 1:>8}{10.0 * i:>16.1f}{10.0 * j:>16.1f}{0.0:>16.1f}\n"
        for j in range(3) for i in range(3))
    shells = "*ELEMENT_SHELL\n" + "".join(
        "".join(f"{v:>8}" for v in (e, 1, n, n + 1, n + 4, n + 3)) + "\n"
        for e, n in ((1, 1), (2, 2), (3, 4), (4, 5)))
    eig = ("*CONTROL_IMPLICIT_EIGENVALUE\n" + f"{neig:>10}"
           + _row(0.0, 0, 0.0, 0, 0.0, 2) + "\n")
    gen = ""
    if general:
        if n_general == 2:
            gen += ("*CONTROL_IMPLICIT_GENERAL\n" + f"{first_imflag:>10}"
                    + _row(0.001) + "\n")
        gen += ("*CONTROL_IMPLICIT_GENERAL\n" + f"{imflag:>10}"
                + _row(0.001) + "\n")
    controls = eig + gen if order == "eig_first" else gen + eig
    return ("*KEYWORD\n" + controls
            + "*CONTROL_TERMINATION\n" + _row(0.001) + "\n" + nodes
            + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0) + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            + shells
            + "*SET_NODE_LIST\n" + _row(1) + "\n" + _row(1, 4, 7) + "\n"
            "*BOUNDARY_SPC_SET\n" + _row(1, 0, 1, 1, 1, 1, 1, 1) + "\n"
            "*DEFINE_CURVE\n" + _row(5) + "\n"
            + f"{0.0:>20}{0.0:>20}\n{0.001:>20}{1.0:>20}\n"
            "*LOAD_NODE_POINT\n" + _row(9, 3, 5, 10.0) + "\n"
            + extra + "*END\n")


def _ishell(starter: str, pid: int = 1) -> int:
    """The Ishell field (first 10 columns of the first data row) of
    /PROP/SHELL/<pid>."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines)
             if ln.startswith(f"/PROP/SHELL/{pid}"))
    row = next(ln for ln in lines[i + 2:] if not ln.startswith("#"))
    return int(row[:10])


_B1_S = _handlers._IMFLAG0_EIGEN_SENTENCE


class Imflag0EigenExplicit(unittest.TestCase):
    """B1: LS-DYNA runs a deck that states IMFLAG 0 and NEIG 0 EXPLICIT
    (tire.d3hsp:1056-1057 'eq.0: explicit analysis', :1316 NEIG 0); k2rad
    routes it explicit whatever the card order, once, with one sentence.
    Every other eigen deck keeps the modal K-export route.

    Starter + engine of the (0, 0) probe (nt 4, rcv_r8i_implB_b1_00,
    harvested and deleted): 0 starter ERROR, NORMAL TERMINATION (see the
    implement report B1)."""

    def _assert_explicit(self, res, starter, engine):
        self.assertNotIn("/IMPL", engine)
        self.assertNotIn("/EIG", engine)
        self.assertNotIn("/IMPL/PRINT/STIF", engine)
        self.assertEqual(_ishell(starter), 12)
        self.assertEqual(sum(w == _B1_S for w in res.warnings), 1,
                         res.warnings)

    def test_imflag0_neig0_converts_explicit(self):
        for order in ("eig_first", "general_first"):
            with self.subTest(order=order):
                self._assert_explicit(*_convert(_eig_deck(order=order)))

    def test_the_state_flags_follow_the_route(self):
        for order in ("eig_first", "general_first"):
            with self.subTest(order=order):
                st = _dispatch(_eig_deck(order=order))
                self.assertFalse(st.is_modal)
                self.assertFalse(st.is_implicit)
                self.assertTrue(st.imflag0_eigen_explicit_route)

    def test_imflag0_neig0_equals_its_twin(self):
        """M8, synthetic: the deck as stated vs the deck minus its
        EIGENVALUE block - identical starter AND engine; the warning lists
        differ by exactly the B1 sentence."""
        res, starter, engine = _convert(_eig_deck())
        twin = _eig_deck().replace(
            "*CONTROL_IMPLICIT_EIGENVALUE\n" + f"{'0':>10}"
            + _row(0.0, 0, 0.0, 0, 0.0, 2) + "\n", "")
        self.assertNotIn("EIGENVALUE", twin)
        res_t, starter_t, engine_t = _convert(twin)
        self.assertEqual(starter, starter_t)
        self.assertEqual(engine, engine_t)
        self.assertEqual([w for w in res.warnings if w != _B1_S],
                         list(res_t.warnings))
        self.assertEqual(len(res.warnings), len(res_t.warnings) + 1)

    def test_imflag1_neig0_stays_modal(self):
        """The 12 ex_19 meshes' shape: IMFLAG 1 + NEIG 0 has LS eigen
        products, so it stays modal."""
        res, starter, engine = _convert(_eig_deck(imflag="1"))
        self.assertIn("/IMPL/PRINT/STIF", engine)
        self.assertNotIn(_B1_S, res.warnings)

    def test_imflag0_neig5_stays_modal(self):
        res, starter, engine = _convert(_eig_deck(neig="5"))
        self.assertIn("/IMPL/PRINT/STIF", engine)
        self.assertNotIn(_B1_S, res.warnings)

    def test_blank_imflag_and_blank_neig_read_zero(self):
        for imflag, neig in ((" ", "0"), ("0", " "), (" ", " ")):
            with self.subTest(imflag=imflag, neig=neig):
                self._assert_explicit(*_convert(_eig_deck(imflag=imflag,
                                                          neig=neig)))

    def test_no_general_card_stays_modal(self):
        """DECISION B1-a: NEIG 0 with no *CONTROL_IMPLICIT_GENERAL keeps the
        modal route (0 carriers on five corpora)."""
        res, starter, engine = _convert(_eig_deck(general=False))
        self.assertIn("/IMPL/PRINT/STIF", engine)
        self.assertNotIn(_B1_S, res.warnings)
        st = _dispatch(_eig_deck(general=False))
        self.assertTrue(st.is_modal and st.is_implicit)

    def test_two_general_cards_one_nonzero_stays_modal(self):
        """IMFLAG 1 then 0 (NEIG 0): the LAST card reads 0, but a card
        stated IMFLAG 1 - the guard reads every card, not
        ``ctrl_implicit_gen`` (mutation target: ``gen.imflag == 0`` alone
        fails this test)."""
        for order in ("eig_first", "general_first"):
            with self.subTest(order=order):
                res, starter, engine = _convert(_eig_deck(
                    n_general=2, first_imflag="1", order=order))
                self.assertIn("/IMPL/PRINT/STIF", engine)
                self.assertNotIn(_B1_S, res.warnings)

    def test_opt_out_keeps_the_modal_route(self):
        res, starter, engine = _convert(_eig_deck(),
                                        imflag0_eigen_explicit=False)
        res_g, starter_g, engine_g = _convert(_eig_deck(
            order="general_first"), imflag0_eigen_explicit=False)
        for r, s, e in ((res, starter, engine), (res_g, starter_g, engine_g)):
            self.assertIn("/IMPL/PRINT/STIF", e)
            self.assertEqual(_ishell(s), 24)
            self.assertNotIn(_B1_S, r.warnings)

    def test_negative_neig_is_not_zero(self):
        res, starter, engine = _convert(_eig_deck(neig="-3"))
        self.assertIn("/IMPL/PRINT/STIF", engine)
        self.assertNotIn(_B1_S, res.warnings)

    def test_the_sentence_carries_its_facts(self):
        for needle in ("tire.d3hsp:1056-1057", "(:1316)", "24329 cycles",
                       "+3.68 / -0.35 / -3.58 / -3.89 / +3.93 %",
                       "-1.18 / -4.86 / +0.95 / -0.90 / -18.30 %",
                       "END +3.93 / -18.30 %", "RMS 2.06 / 2.23 %",
                       "the last row of a printed time",
                       "--no-imflag0-eigen-explicit"):
            with self.subTest(needle=needle):
                self.assertIn(needle, _B1_S)


# ─────────────────────────────────────────────────────────────────────────────
# B2 - implicit *DEFINE_CURVE_SMOOTH -> a sampled sine /FUNCT (default ON,
#      --no-implicit-smooth-curve-sampling)
# ─────────────────────────────────────────────────────────────────────────────


def _smooth_deck(implicit=True, modal=False, tstart="0.0", tend="0.03",
                 trise="0.005", dist="9.0", vmax="", endtim="0.03",
                 consumer="motion", extra="") -> str:
    """One ELFORM-1 *MAT_ELASTIC brick (10 mm, nodes 1-8), y / z held, its
    x = 0 face held in x and its x = 10 face (nodes 2, 3, 6, 7) driven
    along x by *DEFINE_CURVE_SMOOTH 1 (``*BOUNDARY_PRESCRIBED_MOTION_SET``
    VAD 0, or ``*LOAD_NODE_SET`` when *consumer* is "load"). Implicit:
    GENERAL IMFLAG 1 DT0 0.001 + DYNAMICS IMASS 1 (+ EIGENVALUE NEIG 5 when
    *modal*)."""
    pts = ((1, 0, 0, 0), (2, 10, 0, 0), (3, 10, 10, 0), (4, 0, 10, 0),
           (5, 0, 0, 10), (6, 10, 0, 10), (7, 10, 10, 10), (8, 0, 10, 10))
    nodes = "*NODE\n" + "".join(
        f"{n:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n" for n, x, y, z in pts)
    ctrl = ""
    if implicit:
        ctrl = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
                "*CONTROL_IMPLICIT_DYNAMICS\n" + _row(1) + "\n")
        if modal:
            ctrl += "*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(5) + "\n"
    smooth = ("*DEFINE_CURVE_SMOOTH\n" + _row(1, 0) + f"{dist:>10}"
              + f"{tstart:>10}{tend:>10}{trise:>10}{vmax:>10}" + "\n")
    if consumer == "motion":
        drive = ("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                 + _row(2, 1, 0, 1, 1.0) + "\n")
    else:
        drive = "*LOAD_NODE_SET\n" + _row(2, 1, 1, 1.0) + "\n"
    return ("*KEYWORD\n" + ctrl + "*CONTROL_TERMINATION\n"
            + f"{endtim:>10}" + "\n" + nodes
            + "*PART\nbrick\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            "*ELEMENT_SOLID\n"
            + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4, 5, 6, 7, 8))
            + "\n"
            "*SET_NODE_LIST\n" + _row(1) + "\n" + _row(1, 4, 5, 8) + "\n"
            "*SET_NODE_LIST\n" + _row(2) + "\n" + _row(2, 3, 6, 7) + "\n"
            "*SET_NODE_LIST\n" + _row(3) + "\n"
            + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
            "*BOUNDARY_SPC_SET\n" + _row(1, 0, 1, 0, 0, 0, 0, 0) + "\n"
            "*BOUNDARY_SPC_SET\n" + _row(3, 0, 0, 1, 1, 0, 0, 0) + "\n"
            + smooth + drive + extra + "*END\n")


def _funct_rows(starter: str, fid: int, kind: str = "/FUNCT/"):
    """The (X, Y) text cells of /FUNCT/<fid> (or /FUNCT_SMOOTH/<fid>)."""
    lines = starter.splitlines()
    i = lines.index(f"{kind}{fid}")
    j = i + 1
    while not lines[j].startswith("#                  X"):
        j += 1
    rows = []
    for ln in lines[j + 1:]:
        if ln.startswith(("/", "#")) or not ln.strip():
            break
        rows.append((ln[:20].strip(), ln[20:40].strip()))
    return rows


def _area(rows):
    pts = [(float(a), float(o)) for a, o in rows]
    return sum((b[0] - a[0]) * (a[1] + b[1]) / 2.0
               for a, b in zip(pts, pts[1:]))


_B2_HEAD = "*DEFINE_CURVE_SMOOTH LCID 1: written as /FUNCT/1 sampling a SINE"


class ImplicitSmoothCurveSampling(unittest.TestCase):
    """B2: the implicit solver integrates a /FUNCT_SMOOTH's raw points
    piecewise-linearly (fv_imp0.F:209 FV_IMP -> :333 DINTERI; no implicit
    path dispatches on ISMOOTH), so an implicit, non-modal deck gets the
    sine ramp sampled into a plain /FUNCT under the same id. Hand values:
    41 points per ramp at TSTART + TRISE k / 40 with 0.5 VMAX (1 -/+ cos(pi
    k / 40)); VMAX 360 = 9 / (0.03 - 0.005), metal-cutting's own cells.

    Solver probe (_smooth_deck(trise 0.01, tend 0.04, dist 3.0, endtim
    0.05) + node 2's history; S default / L opt-out, starter + engine, nt
    4, rcv_r8i_implB_b2_probe_{S,L}, harvested and deleted): 0 starter
    ERROR and NORMAL in 20 cycles on both; node 2's DX equals the integral
    of the emitted points to 1.6e-7 (S) / 1.2e-7 (L) at every printed step
    - S the sampled sine, held at DIST 3.0 past TEND by its end point; L the
    STRAIGHT 4-point ramp (DX 0.0928805 = 5000 t^2 at t 0.00431), run back
    to 2.782 at t 0.0466 by DINTERI's linear extrapolation."""

    def test_implicit_writes_the_sampled_funct(self):
        res, starter, _e = _convert(_smooth_deck())
        self.assertNotIn("/FUNCT_SMOOTH", starter)
        rows = _funct_rows(starter, 1)
        self.assertEqual(len(rows), 82)
        self.assertEqual(rows[0], ("0", "0"))
        self.assertEqual(rows[1], ("0.000125", "0.554879928"))
        self.assertEqual(rows[2], ("0.00025", "2.216098693"))
        self.assertEqual(rows[40], ("0.005", "360"))
        self.assertEqual(rows[41], ("0.025", "360"))
        self.assertEqual(rows[42], ("0.025125", "359.4451201"))
        self.assertEqual(rows[80], ("0.029875", "0.554879928"))
        self.assertEqual(rows[81], ("0.03", "0"))
        xs = [float(a) for a, _o in rows]
        self.assertTrue(all(b > a for a, b in zip(xs, xs[1:])))
        hits = [w for w in res.warnings if w.startswith(_B2_HEAD)]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("(82 points: 41 per ramp", "area 9 = DIST",
                       "fv_imp0.F:209", ":333 DINTERI", "fixvel.F:248-268",
                       "--no-implicit-smooth-curve-sampling"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])

    def test_area_is_dist(self):
        """The printed trapezoid area is DIST to 1e-9 (measured 3.2e-12);
        the VMAX-stated card gives the same 82 rows."""
        _r, starter, _e = _convert(_smooth_deck())
        rows = _funct_rows(starter, 1)
        self.assertAlmostEqual(_area(rows) / 9.0, 1.0, places=9)
        _r2, starter2, _e2 = _convert(_smooth_deck(vmax="360.0", tend=""))
        self.assertEqual(_funct_rows(starter2, 1), rows)

    def test_explicit_twin_unchanged(self):
        res, starter, _e = _convert(_smooth_deck(implicit=False))
        self.assertEqual(len(_funct_rows(starter, 1, "/FUNCT_SMOOTH/")), 4)
        self.assertNotIn("\n/FUNCT/1\n", starter)
        self.assertFalse(_has(res.warnings, _B2_HEAD))

    def test_modal_unchanged(self):
        res, starter, _e = _convert(_smooth_deck(modal=True))
        self.assertIn("/FUNCT_SMOOTH/1", starter)
        self.assertFalse(_has(res.warnings, _B2_HEAD))

    def test_opt_out_keeps_funct_smooth(self):
        res, starter, _e = _convert(_smooth_deck(),
                                    implicit_smooth_curve_sampling=False)
        _rx, starter_x, _ex = _convert(_smooth_deck(implicit=False))
        self.assertEqual(_funct_rows(starter, 1, "/FUNCT_SMOOTH/"),
                         _funct_rows(starter_x, 1, "/FUNCT_SMOOTH/"))
        self.assertFalse(_has(res.warnings, _B2_HEAD))

    def test_tstart_guard(self):
        """TSTART 0.002: (0, 0) first, then (0.002, 0); 83 points; area
        9.0."""
        _r, starter, _e = _convert(_smooth_deck(tstart="0.002"))
        rows = _funct_rows(starter, 1)
        self.assertEqual(len(rows), 83)
        self.assertEqual(rows[:2], [("0", "0"), ("0.002", "0")])
        self.assertAlmostEqual(_area(rows) / 9.0, 1.0, places=9)

    def test_endtim_guard(self):
        """ENDTIM 0.05 > TEND: the last point (TEND + TRISE, 0) = (0.035,
        0); at ENDTIM = TEND none (82)."""
        _r, starter, _e = _convert(_smooth_deck(endtim="0.05"))
        rows = _funct_rows(starter, 1)
        self.assertEqual(len(rows), 83)
        self.assertEqual(rows[-2:], [("0.03", "0"), ("0.035", "0")])
        _r2, starter2, _e2 = _convert(_smooth_deck(endtim="0.03"))
        self.assertEqual(len(_funct_rows(starter2, 1)), 82)

    def test_zero_width_plateau(self):
        """TRISE 0.015 = half the window: the shared vertex (0.015, VMAX
        600) once, 81 points."""
        _r, starter, _e = _convert(_smooth_deck(trise="0.015"))
        rows = _funct_rows(starter, 1)
        self.assertEqual(len(rows), 81)
        self.assertEqual(sum(a == "0.015" for a, _o in rows), 1)
        self.assertIn(("0.015", "600"), rows)
        self.assertAlmostEqual(_area(rows) / 9.0, 1.0, places=9)

    def test_degenerate_shapes_keep_funct_smooth(self):
        for trise in ("0.0", "0.02"):
            with self.subTest(trise=trise):
                res, starter, _e = _convert(_smooth_deck(trise=trise))
                self.assertIn("/FUNCT_SMOOTH/1", starter)
                self.assertFalse(_has(res.warnings, _B2_HEAD))

    def test_load_consumer_sampled_too(self):
        res, starter, _e = _convert(_smooth_deck(consumer="load"))
        self.assertNotIn("/FUNCT_SMOOTH", starter)
        self.assertEqual(len(_funct_rows(starter, 1)), 82)
        self.assertTrue(_has(res.warnings, _B2_HEAD))

    def test_sampler_is_idempotent(self):
        from k2rad.writer import assembly
        state = _dispatch(_smooth_deck())
        assembly._sample_implicit_smooth_curves(state)
        pts = list(state.curves[1].pts)
        n_warn = len(state.warnings)
        self.assertEqual(len(pts), 82)
        assembly._sample_implicit_smooth_curves(state)
        self.assertEqual(state.curves[1].pts, pts)
        self.assertEqual(len(state.warnings), n_warn)
        self.assertNotIn(1, state.funct_smooth_ids)

    def test_redefinition_drops_stale_params(self):
        """A smooth LCID 1 redefined by a degenerate smooth card (TRISE 0)
        keeps no stale ramp: /FUNCT_SMOOTH, no B2 sentence."""
        extra = ("*DEFINE_CURVE_SMOOTH\n" + _row(1, 0) + f"{'9.0':>10}"
                 + f"{'0.0':>10}{'0.03':>10}{'0.0':>10}{'':>10}" + "\n")
        state = _dispatch(_smooth_deck(extra=extra))
        self.assertNotIn(1, state.smooth_curve_params)
        res, starter, _e = _convert(_smooth_deck(extra=extra))
        self.assertIn("/FUNCT_SMOOTH/1", starter)
        self.assertFalse(_has(res.warnings, _B2_HEAD))

    def test_a_plain_curve_redefinition_drops_the_params_too(self):
        extra = ("*DEFINE_CURVE\n" + _row(1) + "\n"
                 + f"{0.0:>20}{0.0:>20}\n{0.03:>20}{1.0:>20}\n")
        state = _dispatch(_smooth_deck(extra=extra))
        self.assertNotIn(1, state.smooth_curve_params)
        self.assertNotIn(1, state.funct_smooth_ids)

    def test_the_sentence_carries_the_measured_tallies(self):
        for needle in ("on 13 of 13 runs", "on 7 of 7 runs",
                       "1.48e5 .. 2.75e5 mJ over the seven runs",
                       "0.01431 mm against LS 0.014681",
                       "2.782 at t 0.0466 against DIST 3",
                       "t^2.68 .. t^2.89"):
            with self.subTest(needle=needle):
                self.assertIn(needle, _handlers._SMOOTH_SAMPLING_CORE)

    def test_the_A5_placeholder_sentence_is_corrected(self):
        """B2.4 (b): the EFG placeholder sentence quotes the status split,
        the climbing IE and LS-DYNA's six d3plot states (the round-7
        needles of EfgPlaceholderNamed sit in its unchanged head)."""
        res, _s, _e = _convert(_t7._efg_deck())
        hit = [w for w in res.warnings if w.startswith("*SECTION_SOLID_EFG 3")]
        self.assertEqual(len(hit), 1, res.warnings)
        for needle in ("six d3plot states to t 1.07344e-3 s",
                       "header-only glstat", "on 13 of 13 runs",
                       "on 7 of 7 runs", "11.59 / 82.60 mJ",
                       "on 10 of 10 runs", "802x / 49.8x",
                       "imp_glob_k.F:176-193", "then CLIMBS",
                       "2.391e5 mJ"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit[0])

    def test_the_sampler_against_its_hand_points(self):
        pts = _handlers.sampled_smooth_points(0.0, 0.005, 0.03, 360.0, 0.03)
        self.assertEqual(len(pts), 82)
        for k in (0, 7, 23, 40):
            self.assertAlmostEqual(pts[k][0], 0.005 * k / 40, places=15)
            self.assertAlmostEqual(
                pts[k][1], 180.0 * (1.0 - math.cos(math.pi * k / 40)),
                places=9)
        for k in (0, 13, 40):
            self.assertAlmostEqual(pts[41 + k][0], 0.025 + 0.005 * k / 40,
                                   places=15)
            self.assertAlmostEqual(
                pts[41 + k][1], 180.0 * (1.0 + math.cos(math.pi * k / 40)),
                places=9)


# ─────────────────────────────────────────────────────────────────────────────
# B4 - the *MAT_NULL MU package: F5 Nu on SPH-only materials, F1 the R guard,
#      the F2 / F3 / _NU_SPH_FACT texts (under --no-mat-null-pc-mu)
# ─────────────────────────────────────────────────────────────────────────────

_null_fluid_deck = _t7._null_fluid_deck
_nu_pmin = _t7._nu_pmin
_w = _t7._w
_WN1 = _t7._WN1
_WN = _t7._WN
_WN1_SPH = "*MAT_NULL MU -> /MAT/HYD_VISC Nu on SPH parts: "
_WR = "*MAT_NULL MU -> Nu on /PROP/SOLID/"
#: sha256 of the ELFORM-6 Nu sentence 4f5b6e8 prints on
#: _null_fluid_deck(pc="-1.0E4", mu="1.0E-6", elform=6) - converted from the
#: pristine checkout (B4-a: the w_n1 family split keeps its bytes)
_WN1_4F5B6E8_SHA = (
    "86d1b36070e872ed0db2ffe2e53de8514989a44fd9c9a30e628dde624fdff8d2")


def _visc_brick_deck(sizes=(1.0, 1.0), c="31622.7766", mu="1.0E-5",
                     eos="gruneisen", hourglass="", ro="1.0E-9") -> str:
    """Part 1 = one cubic *SECTION_SOLID ELFORM-6 brick per entry of
    *sizes* (edge s mm, each on its own 8 nodes, side by side along x), on
    *MAT_NULL 1 (RO 1e-9, PC -1, MU *mu*) + *EOS_GRUNEISEN 1 C *c* (or
    *EOS_LINEAR_POLYNOMIAL C1 = *c*, or *EOS_IDEAL_GAS); *hourglass* = a
    QH cell puts the part on *HOURGLASS 1 IHQ 1 (the split /PROP site)."""
    nodes, elems, x0, nid = [], [], 0.0, 1
    for eid, s in enumerate(sizes, start=1):
        ids = []
        for z in (0.0, s):
            for y, x in ((0.0, 0.0), (0.0, s), (s, s), (s, 0.0)):
                nodes.append(f"{nid:>8}{x0 + x:>16.4f}{y:>16.4f}{z:>16.4f}")
                ids.append(nid)
                nid += 1
        elems.append("".join(f"{v:>8}" for v in [eid, 1] + ids))
        x0 += s + 1.0
    if eos == "gruneisen":
        eos_card = ("*EOS_GRUNEISEN\n" + _row(1) + f"{c:>10}"
                    + _row(1.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n" + _row(1.0)
                    + "\n")
    elif eos == "linpoly":
        eos_card = ("*EOS_LINEAR_POLYNOMIAL\n" + _row(1, 0.0) + f"{c:>10}"
                    + _row(0.0, 0.0, 0.0, 0.0, 0.0) + "\n" + _row(0.0, 1.0)
                    + "\n")
    else:
        eos_card = ("*EOS_IDEAL_GAS\n" + _row(1, 718.0, 1005.0, 0.0, 0.0,
                                               293.0, 1.0) + "\n")
    hg = ""
    hgid = 0
    if hourglass:
        hg = "*HOURGLASS\n" + _row(1, 1) + f"{hourglass:>10}" + "\n"
        hgid = 1
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(0.02) + "\n*NODE\n"
            + "\n".join(nodes) + "\n*ELEMENT_SOLID\n" + "\n".join(elems)
            + "\n*PART\nviscous fluid\n" + _row(1, 1, 1, 1, hgid) + "\n"
            "*SECTION_SOLID\n" + _row(1, 6) + "\n"
            + f"*MAT_NULL\n{1:>10}{ro:>10}{'-1.0':>10}{mu:>10}\n"
            + eos_card + hg + "*END\n")


def _prop_h(starter: str, prop: int) -> str:
    """The h cell (card 2, columns 41-60) of /PROP/SOLID/<prop>."""
    lines = starter.splitlines()
    i = lines.index(f"/PROP/SOLID/{prop}")
    return lines[i + 5][40:60]


def _prop_isolid(starter: str, prop: int) -> int:
    lines = starter.splitlines()
    i = lines.index(f"/PROP/SOLID/{prop}")
    return int(lines[i + 3][:10])


class MatNullSphNuAndRGuard(unittest.TestCase):
    """B4: F5 writes Nu = MU / RO on an SPH-ONLY *MAT_NULL material (the SPH
    stress takes the same LAW6 routine, spstres.F:250; the SPH Couette
    coupon converges, sph/bird inert); F1 divides a /PROP/SOLID's hourglass
    coefficient by R = 10 Nu / (c0 dmin) when R > 1 (shvis3.F:182 / :185);
    the F2 / F3 / SPH texts carry the round-8 measurements. Hand values: Nu
    1e-5 / 1e-9 = 1e4, R = 10 x 1e4 / (31622.7766 x 1) = 3.16228, h = 0.1 /
    R = 0.0316227766.

    R > 1 probe (the critic's Couette coupon couc_M1 converted on this
    code: only its /PROP/SOLID/1 h moves, 0.1 -> 0.0316227766; starter +
    engine, nt 4, rcv_r8i_implB_b4_cM1g, harvested and deleted): 0 starter
    ERROR / 0 WARNING, NORMAL in 1352 cycles, the analytic profile to 0.191
    / 0.078 / 0 / 0 % of U at 0.1 / 0.2 / 1 / 2 t_d, hourglass energy
    3.8e-11 mJ."""

    def test_sph_only_writes_nu(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0", mu="1.0E-9",
                                             ro=1.0e-9, sph=True))
        self.assertEqual(_nu_pmin(s), "                   1                  -1")
        hits = _w(r, _WN1_SPH)
        self.assertEqual(len(hits), 1, r.warnings)
        for needle in ("Nu 1 (MU 1e-09 / RO 1e-09, parts [1])",
                       "spstres.F:250", "mdtsph.F:126", "9.9 -> 6.0 % of U",
                       "1616 = 1616 cycles"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertEqual([w for w in r.warnings
                          if w.startswith(_WN1) and not w.startswith(
                              _WN1_SPH)], [])
        self.assertEqual(_w(r, _WN), [])

    def test_sph_plus_elform1_keeps_nu_0(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0", mu="1.0E-6",
                                             sph=True, second_part_elform=1))
        self.assertEqual(_nu_pmin(s)[:20], " " * 19 + "0")
        hits = _w(r, _WN)
        self.assertEqual(len(hits), 1, r.warnings)
        for needle in ("16.60 -> 29.58", "'plaque sous SPH'",
                       "+51.91 -> +52.61 %", "or every part is SPH",
                       "the two families where it was measured right"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        for gone in ("44.37", "1942", "10.3 -> 29.6"):
            self.assertNotIn(gone, hits[0])
        self.assertEqual(_w(r, _WN1_SPH), [])

    def test_sph_on_a_void_deck_keeps_nu_0(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0", mu="1.0E-6",
                                             sph=True, void="other"))
        self.assertEqual(_nu_pmin(s)[:20], " " * 19 + "0")
        self.assertEqual(_w(r, _WN1_SPH), [])
        self.assertTrue(_has(r.warnings, "the deck states *INITIAL_VOID, "
                             "which the Nu cell's scope excludes",
                             "open fixed-grid ALE faces (walled: -0.1 %)"))

    def test_elform6_sentence_unchanged(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0E4", mu="1.0E-6",
                                             elform=6))
        hit = _w(r, _WN1)
        self.assertEqual(len(hit), 1, r.warnings)
        self.assertEqual(hashlib.sha256(hit[0].encode("utf-8")).hexdigest(),
                         _WN1_4F5B6E8_SHA)
        self.assertEqual(_w(r, _WN1_SPH), [])

    def test_opt_out_writes_nu_0_on_sph(self):
        r, s, _e = _convert(_null_fluid_deck(pc="-1.0", mu="1.0E-9",
                                             sph=True), mat_null_pc_mu=False)
        self.assertEqual(_nu_pmin(s)[:20], " " * 19 + "0")
        self.assertEqual(_w(r, _WN1_SPH), [])

    def test_the_bird_B_and_void_texts_name_the_open_faces(self):
        r, _s, _e = _convert(_null_fluid_deck(pc="-1.0", mu="1.0E-6",
                                              elform=12, void="other"))
        hits = [w for w in r.warnings
                if w.startswith(_WN) and "+20691.23 %" in w]
        self.assertEqual(len(hits), 1, r.warnings)
        for needle in ("OPEN fixed-grid ALE faces", "-0.1 %", "+2.4 %",
                       "*ALE_REFERENCE_SYSTEM_GROUP PRTYPE 4",
                       "the reference-system item first"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("mechanism not found", hits[0])

    # ---- F1: the R guard ------------------------------------------------

    def _guarded(self, deck, prop=1):
        r, s, _e = _convert(deck)
        return r, s, _w(r, f"{_WR}{prop} ")

    def test_R_guard_gruneisen(self):
        r, s, hits = self._guarded(_visc_brick_deck())
        self.assertEqual(_prop_h(s, 1), _f(0.1 / (1.0e5 / 31622.7766)))
        self.assertEqual(_prop_h(s, 1), "        0.0316227766")
        self.assertEqual(len(hits), 1, r.warnings)
        for needle in ("(parts [1])", "R = 10 Nu / (c0 dmin) = 3.16 > 1",
                       "Nu 10000", "c0 31622.8 from /EOS/GRUNEISEN",
                       "dmin 1,", "0.0316228 = 0.1 / R",
                       "shvis3.F:182 / :185", "--no-mat-null-pc-mu"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("graded part", hits[0])

    def test_R_guard_linear_polynomial(self):
        """C1 1.0 (= K) with RO 1e-9: c0 = sqrt(1 / 1e-9) = 31622.7766."""
        r, s, hits = self._guarded(_visc_brick_deck(c="1.0", eos="linpoly"))
        self.assertEqual(_prop_h(s, 1), "        0.0316227766")
        self.assertEqual(len(hits), 1, r.warnings)
        self.assertIn("c0 31622.8 from /EOS/POLYNOMIAL", hits[0])

    def test_R_below_one_untouched(self):
        """The channel family: Nu 1000, C 1.5e6, a 0.5714 mm cube: R =
        10 x 1000 / (1.5e6 x 0.5714) = 0.011667 -> today's cell."""
        r, s, hits = self._guarded(_visc_brick_deck(
            sizes=(0.5714,), c="1500000.0", mu="1.0E-6"))
        r0, s0, _e0 = _convert(_visc_brick_deck(
            sizes=(0.5714,), c="1500000.0", mu="1.0E-6"),
            mat_null_pc_mu=False)
        self.assertEqual(_prop_h(s, 1), _prop_h(s0, 1))
        self.assertEqual(hits, [])

    def test_graded_part_uses_dmin(self):
        """1 mm + 0.5 mm cubes on one part: dmin 0.5, R = 6.32456, h =
        0.1 / R = 0.0158113883; the graded caveat is named."""
        r, s, hits = self._guarded(_visc_brick_deck(sizes=(1.0, 0.5)))
        self.assertEqual(_prop_h(s, 1), _f(0.1 / (1.0e5 / (31622.7766 * 0.5))))
        self.assertEqual(_prop_h(s, 1), "        0.0158113883")
        self.assertEqual(len(hits), 1, r.warnings)
        self.assertIn("dmin 0.5,", hits[0])
        self.assertIn("On a graded part h / R_max also weakens", hits[0])

    def test_stated_h_is_divided_on_the_split_prop(self):
        """*HOURGLASS IHQ 1 QH 0.05: the split /PROP/SOLID (mesh.py's second
        emission site) gets 0.05 / R."""
        r, s, _e = _convert(_visc_brick_deck(hourglass="0.05"))
        props = [ln for ln in s.splitlines() if ln.startswith("/PROP/SOLID/")]
        self.assertEqual(len(props), 1, props)
        pid = int(props[0].rsplit("/", 1)[1])
        self.assertIn(_prop_isolid(s, pid), (1, 2))
        r_val = 1.0e5 / 31622.7766
        self.assertEqual(_prop_h(s, pid), _f(0.05 / r_val))
        self.assertEqual(len(_w(r, f"{_WR}{pid} ")), 1, r.warnings)

    def test_an_isolid_24_prop_is_not_guarded(self):
        """The fix round (fidelity minor): the R ratio describes SHVIS3's
        fluid hourglass term (shvis3.F:182 / :185), and SHVIS3 is called
        only from SFORC3 (sforc3.F:1250, forint.F's JHBE 1 / 2 / 101 / 102
        branch); Isolid 24 runs SZFORC3 -> SZHOUR3 (forint.F:1090-1096,
        szforc3.F:962), whose LAW6 hourglass is GG = MAX(G0, VIS)
        (szhour3.F:158-160) with no VIS in its damping term (:238-240). So
        the guard's set is Isolid 1 and 2. Unreachable through a deck today
        - the Nu cell is written on ELFORM-6 bricks, which get Isolid 1
        whatever the *HOURGLASS IHQ or the analysis (probed below) - so the
        set is pinned and the rule called directly with Isolid 24."""
        from k2rad.writer import materials
        self.assertEqual(materials._HG_GUARD_ISOLIDS, (1, 2))
        deck = _visc_brick_deck(hourglass="0.05")
        for d in (deck, deck.replace("*HOURGLASS\n" + _row(1, 1),
                                     "*HOURGLASS\n" + _row(1, 6)),
                  deck.replace("*CONTROL_TERMINATION",
                               "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001)
                               + "\n*CONTROL_TERMINATION")):
            with self.subTest(deck=d[:60]):
                _r, s, _e = _convert(d)
                props = [ln for ln in s.splitlines()
                         if ln.startswith("/PROP/SOLID/")]
                self.assertEqual(len(props), 1, props)
                pid = int(props[0].rsplit("/", 1)[1])
                self.assertEqual(_prop_isolid(s, pid), 1)
        st = _dispatch(_visc_brick_deck())
        r_val = 1.0e5 / 31622.7766
        self.assertAlmostEqual(materials.guarded_prop_h(st, 1, [1], 1, None),
                               0.1 / r_val, places=9)
        self.assertIsNone(materials.guarded_prop_h(st, 1, [1], 24, None))
        self.assertEqual(materials.guarded_prop_h(st, 1, [1], 24, 0.05), 0.05)

    def test_unsupported_eos_kind_named(self):
        r, s, _e = _convert(_visc_brick_deck(eos="ideal"))
        r0, s0, _e0 = _convert(_visc_brick_deck(eos="ideal"),
                               mat_null_pc_mu=False)
        if "/PROP/SOLID/1" in s:
            self.assertEqual(_prop_h(s, 1), _prop_h(s0, 1))
        self.assertTrue(_has(r.warnings, "*MAT_NULL 1: the Nu cell's "
                             "hourglass guard", "/EOS/IDEAL-GAS"),
                        r.warnings)

    def test_opt_out_removes_the_guard(self):
        r, s, _e = _convert(_visc_brick_deck(), mat_null_pc_mu=False)
        self.assertEqual(_w(r, _WR), [])
        self.assertNotEqual(_prop_h(s, 1), "        0.0316227766")

    def test_the_texts_carry_the_round_8_figures(self):
        from k2rad.writer import materials as m
        self.assertIn("16.60 -> 29.58 mJ", m._NU_LAGRANGIAN_FACT)
        self.assertIn("+51.91 -> +52.61 %", m._NU_SPH_FACT)
        self.assertIn("1616 = 1616 cycles", m._NU_SPH_WRITTEN_FACTS)


# ─────────────────────────────────────────────────────────────────────────────
# B5 - *MAT_ELASTIC_FLUID stated CP 0.0 -> /MAT/HYD_VISC Pmin -1e-20
#      (default ON, --no-elastic-fluid-cp-cutoff)
# ─────────────────────────────────────────────────────────────────────────────

import test_impact_mats as _tim  # noqa: E402


def _ef_deck(card2) -> str:
    return _tim.MESH(3) + _tim._fluid(card2=card2) + "*END\n"


def _ef_pmin_cell(starter: str) -> str:
    """The Pmin cell (card 2 columns 21-40) of /MAT/HYD_VISC/3, as text."""
    return _tim._cards(_tim._block(starter, "/MAT/HYD_VISC/3"))[1][20:40]


_B5_HEAD = "CP=0.0 is stated on card 2"


class ElasticFluidCpCutoff(unittest.TestCase):
    """B5: LS-DYNA keeps a stated CP 0.0 as its cavitation pressure
    (9.1.acoustic.compartment.hex.d3hsp:3471 'cavitation pressure =
    0.00000E+00'), the Radioss reader takes a Pmin of exactly 0 as -INFINITY
    (hm_read_mat06.F:154): the explicit-0.0 branch writes -1e-20 (the cell
    *MAT_NULL PC 0 gets). Every other CP branch is unchanged in both arms.

    Starter probe (this class's CP 0.0 deck, nt 4,
    rcv_r8i_implB_b5_probe, harvested and deleted): 0 ERROR, the echo
    PRESSURE CUTOFF -1.0000000000000E-20 (see the implement report B5)."""

    def test_stated_zero_cp_is_minus_1e_20(self):
        res, starter = _tim._convert(_ef_deck((0.0, 0.0)))
        self.assertEqual(_ef_pmin_cell(starter), _f(-1.0e-20))
        self.assertEqual(_ef_pmin_cell(starter), _t7._NU_PMIN_FLOOR[20:40])
        hits = [w for w in res.warnings if _B5_HEAD in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("hm_read_mat06.F:154", "0.00000E+00",
                       "d3hsp:3471", "eospolyno.F:104",
                       "--no-elastic-fluid-cp-cutoff", "18 identical rows"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertEqual(_tim._warns(res, "CP=0.0 is written explicitly"), [])

    def test_opt_out_keeps_pmin_0(self):
        res, starter = _tim._convert(_ef_deck((0.0, 0.0)),
                                     elastic_fluid_cp_cutoff=False)
        self.assertEqual(_tim._col_f(
            _tim._cards(_tim._block(starter, "/MAT/HYD_VISC/3"))[1], 21, 40),
            0.0)
        hits = _tim._warns(res, "CP=0.0 is written explicitly")
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("is NOT WRITTEN here", hits[0])
        self.assertIn("--no-elastic-fluid-cp-cutoff was passed", hits[0])
        self.assertNotIn("this card's mapping is not changed yet", hits[0])
        self.assertFalse(_has(res.warnings, _B5_HEAD))

    def test_every_other_branch_unchanged_in_both_arms(self):
        cases = ((("0.0", ""), 0.0), (("0.0", "1.0E20"), 0.0),
                 (("0.0", "1.0E6"), -1.0e6), (("0.0", "-1.0E6"), -1.0e6))
        for card2, want in cases:
            for on in (True, False):
                with self.subTest(card2=card2, on=on):
                    res, starter = _tim._convert(
                        _ef_deck(card2), elastic_fluid_cp_cutoff=on)
                    self.assertEqual(_tim._col_f(_tim._cards(_tim._block(
                        starter, "/MAT/HYD_VISC/3"))[1], 21, 40), want)
                    self.assertFalse(_has(res.warnings, _B5_HEAD))

    def test_the_unit_screen_branch_unchanged(self):
        """CP 1e14 with K 2200: the 'rescaled default' screen (|CP| >= 1e6
        K) -> Pmin 0 in both arms."""
        for on in (True, False):
            with self.subTest(on=on):
                deck = (_tim.MESH(3) + _tim._fluid(k="2200.0",
                                                   card2=(0.0, "1.0E14"))
                        + "*END\n")
                res, starter = _tim._convert(deck,
                                             elastic_fluid_cp_cutoff=on)
                self.assertEqual(_tim._col_f(_tim._cards(_tim._block(
                    starter, "/MAT/HYD_VISC/3"))[1], 21, 40), 0.0)
                self.assertFalse(_has(res.warnings, _B5_HEAD))

    def test_mat_null_flag_does_not_touch_it(self):
        res, starter = _tim._convert(_ef_deck((0.0, 0.0)),
                                     mat_null_pc_mu=False)
        self.assertEqual(_ef_pmin_cell(starter), _f(-1.0e-20))


# ─────────────────────────────────────────────────────────────────────────────
# B6 - the implicit contact stub beside a TYPE25-route contact. Round 8
#      shipped the skip as the default; the round's validation INVERTED it:
#      the stub STAYS by default (the 4f5b6e8 deck), the skip is the opt-in
#      --skip-implicit-stub-with-type25, keyed on the WRITTEN TYPE25 set.
# ─────────────────────────────────────────────────────────────────────────────

_shell_plate = _t7._shell_plate
_IMPL1 = _t7._IMPL1
_STUB_TITLE = "auto_implicit_stabilization_self_contact"
_B6_HEAD = "Implicit deck with TYPE25-route contact(s)"
_B6_FLAG = "--skip-implicit-stub-with-type25"
_B6_STUB_SENTENCE = "Injected an inert all-parts"
_N2S_78 = ("*SET_NODE_LIST\n" + _row(5) + "\n" + _row(1, 2, 3) + "\n"
           "*CONTACT_NODES_TO_SURFACE_ID\n" + _row(78) + "\n"
           + _row(5, 1, 4, 3) + "\n" + _row(0.1) + "\n" + _row() + "\n")
#: sha256 of the 4f5b6e8 starter of _shell_plate(_IMPL1, _N2S_78) - the stub
#: beside the TYPE25 (converted from the pristine checkout through
#: test_r14_triage_7._convert); the DEFAULT must reproduce it byte for byte
_B6_DEFAULT_4F5B6E8_SHA = (
    "ec7e3d3fa5ca310d70c6045f96fd15ff97fc1457d03862f87b85f079ec305892")
#: The solver-physics validator's coupon b6t, verbatim: an implicit
#: quasi-static deck (IMFLAG 1, DT0 0.1, NSOLVR 12, IAUTO 1, ENDTIM 1.0); a
#: lower block 20 x 20 x 5 mm (2 x 2 x 1 ELFORM-2 hexes, bottom fixed), an
#: upper block 10 x 10 x 5 mm 0.1 mm above it whose top face is pushed down
#: 0.3 mm over the run; the upper block's bottom nodes on the lower part
#: through *CONTACT_NODES_TO_SURFACE -> /INTER/TYPE25 (the gap closes at
#: t 1/3, then the contact carries the load).
_B6T_DECK = """*KEYWORD
*TITLE
vphys B6 b6t
*CONTROL_IMPLICIT_GENERAL
         1       0.1
*CONTROL_IMPLICIT_SOLUTION
        12
*CONTROL_IMPLICIT_AUTO
         1        11         5         0       0.1
*CONTROL_TERMINATION
         1
*DATABASE_GLSTAT
       0.1
*DEFINE_CURVE
         1         0         1         1         0         0
                   0                   0
                   1                 0.3
*PART
lower
         1         1         1
*PART
upper
         2         1         1
*SECTION_SOLID
         1         2
*MAT_ELASTIC
         1  7.85e-09    210000       0.3
*NODE
       1      0.00000000      0.00000000      0.00000000       0       0
       2     10.00000000      0.00000000      0.00000000       0       0
       3     20.00000000      0.00000000      0.00000000       0       0
       4      0.00000000     10.00000000      0.00000000       0       0
       5     10.00000000     10.00000000      0.00000000       0       0
       6     20.00000000     10.00000000      0.00000000       0       0
       7      0.00000000     20.00000000      0.00000000       0       0
       8     10.00000000     20.00000000      0.00000000       0       0
       9     20.00000000     20.00000000      0.00000000       0       0
      10      0.00000000      0.00000000      5.00000000       0       0
      11     10.00000000      0.00000000      5.00000000       0       0
      12     20.00000000      0.00000000      5.00000000       0       0
      13      0.00000000     10.00000000      5.00000000       0       0
      14     10.00000000     10.00000000      5.00000000       0       0
      15     20.00000000     10.00000000      5.00000000       0       0
      16      0.00000000     20.00000000      5.00000000       0       0
      17     10.00000000     20.00000000      5.00000000       0       0
      18     20.00000000     20.00000000      5.00000000       0       0
     101      5.00000000      5.00000000      5.10000000       0       0
     102     15.00000000      5.00000000      5.10000000       0       0
     103      5.00000000     15.00000000      5.10000000       0       0
     104     15.00000000     15.00000000      5.10000000       0       0
     105      5.00000000      5.00000000     10.10000000       0       0
     106     15.00000000      5.00000000     10.10000000       0       0
     107      5.00000000     15.00000000     10.10000000       0       0
     108     15.00000000     15.00000000     10.10000000       0       0
*ELEMENT_SOLID
       1       1       1       2       5       4      10      11      14      13
       2       1       2       3       6       5      11      12      15      14
       3       1       4       5       8       7      13      14      17      16
       4       1       5       6       9       8      14      15      18      17
     101       2     101     102     104     103     105     106     108     107
*SET_NODE_LIST
         1
         1         4         7         2         5         8         3         6
         9
*SET_NODE_LIST
         2
       101       103       102       104
*SET_NODE_LIST
         3
       105       107       106       108
*SET_PART_LIST
         1
         1
*BOUNDARY_SPC_SET
         1         0         1         1         1         0         0         0
*BOUNDARY_SPC_SET
         3         0         1         1         0         0         0         0
*BOUNDARY_PRESCRIBED_MOTION_SET
         3         3         2         1        -1
*CONTACT_NODES_TO_SURFACE
         2         1         4         2
         0         0

*END
"""
#: sha256 of the 4f5b6e8 starter of _B6T_DECK (the pristine checkout through
#: test_r14_triage_7._convert) = the default; and of the opt-in's starter
_B6T_DEFAULT_4F5B6E8_SHA = "9271da9ad4651577a08d6815f1e64e6af71b26a767b0c74b11d8d0f88242323a"
_B6T_SKIP_SHA = "0c6c760fc1910378103e89dd43ec6379d4f4d108e3479aa603b6b240a7079dc3"


def _stub_ids(starter: str):
    lines = starter.splitlines()
    return [int(lines[i - 1].rsplit("/", 1)[1])
            for i, ln in enumerate(lines) if ln == _STUB_TITLE]


class ImplicitStubWithType25(unittest.TestCase):
    """B6, as the validation round left it: OpenRadioss builds implicit
    contact stiffness only for TYPE 7 / 10 / 11 (imp_int_k.F:847; a TYPE25
    acts through the residual, intfop2.F:595), so beside a TYPE25-route
    contact the all-parts stub is the deck's only implicit contact
    stiffness. Round 8 first skipped it by default; the solver-physics
    validator's coupon b6t then turned NORMAL into ERROR TERMINATION without
    it, so the stub STAYS by default and the skip is the opt-in
    --skip-implicit-stub-with-type25, decided after the TYPE25 writer (the
    WRITTEN set).

    Starter + engine of the b6t coupon, both arms, nt 4 AND nt 2 (the fix
    round, run dirs rcv_r8i_fixpr_b6t_*, harvested and deleted): the
    default (the stub; starter 0 errors, 1 WARNING = 343, the stub's
    initial penetrations) NORMAL TERMINATION in 11 cycles to t 1.0, IE 311.5
    at t 0.1 -> 1.189e5 at t 1.0; the opt-in (0 errors, 0 warnings) IE 0 to
    t 0.4, 391.5 / 2469 / 4225 / 7953 / 1.145e4 at t 0.5 .. 0.9, then 23 x
    ITERATION DIVERGE, MESSAGE 79 'SOLVER IMPLICIT STOPPED DUE TO TIMESTEP
    LIMIT', ERROR TERMINATION at cycle 9, t 0.9. MESSAGE 232 (TYPE25 ignored
    in implicit) on both engines; every printed cycle row identical at nt 4
    and nt 2 but the controlling-node label."""

    def test_default_keeps_the_stub_and_names_both_arms(self):
        res, starter, _e = _convert(_shell_plate(_IMPL1, _N2S_78))
        self.assertEqual(_sha(starter), _B6_DEFAULT_4F5B6E8_SHA)
        self.assertIn("/INTER/TYPE25/78", starter)
        self.assertEqual(len(_stub_ids(starter)), 1, starter)
        heads = [i for i, w in enumerate(res.warnings)
                 if w.startswith(_B6_HEAD)]
        self.assertEqual(len(heads), 1, res.warnings)
        kept = res.warnings[heads[0]]
        # printed right after the stub's own sentence it refers to
        self.assertIn(_B6_STUB_SENTENCE, res.warnings[heads[0] - 1])
        for needle in ("[78]", "is KEPT", "imp_int_k.F:847",
                       "intfop2.F:595", "MESSAGE 232", "NORMAL in 11 cycles",
                       "23 ITERATION DIVERGE", "MESSAGE 79",
                       "ERROR TERMINATION at cycle 9", "+582.00", "393.31",
                       "+689.08", "313.05", "MIXED", _B6_FLAG,
                       "/INTER/TYPE7 %d" % _stub_ids(starter)[0]):
            with self.subTest(needle=needle):
                self.assertIn(needle, kept)

    def test_opt_in_skips_the_stub_where_a_type25_is_written(self):
        res, starter, _e = _convert(_shell_plate(_IMPL1, _N2S_78),
                                    skip_implicit_stub_with_type25=True)
        self.assertIn("/INTER/TYPE25/78", starter)
        self.assertNotIn(_STUB_TITLE, starter)
        self.assertFalse(_has(res.warnings, _B6_STUB_SENTENCE))
        hits = [w for w in res.warnings if w.startswith(_B6_HEAD)]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("[78] written", _B6_FLAG + " left out",
                       "ERROR TERMINATION at cycle 9", "MIXED",
                       "Without the flag the stub is kept."):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("is KEPT", hits[0])

    def test_contact_free_implicit_deck_keeps_the_stub(self):
        for kw in ({}, {"skip_implicit_stub_with_type25": True}):
            with self.subTest(**kw):
                res, starter, _e = _convert(_shell_plate(_IMPL1), **kw)
                self.assertIn(_STUB_TITLE, starter)
                self.assertFalse(_has(res.warnings, _B6_HEAD))

    def test_modal_and_explicit_decks_unchanged(self):
        modal = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
                 "*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(5) + "\n"
                 "*CONTROL_TERMINATION\n" + _row(0.01) + "\n")
        explicit = "*CONTROL_TERMINATION\n" + _row(0.01) + "\n"
        for name, ctrl in (("modal", modal), ("explicit", explicit)):
            for kw in ({}, {"skip_implicit_stub_with_type25": True}):
                with self.subTest(deck=name, **kw):
                    res, starter, _e = _convert(_shell_plate(ctrl, _N2S_78),
                                                **kw)
                    self.assertNotIn(_STUB_TITLE, starter)
                    self.assertFalse(_has(res.warnings, _B6_HEAD))
                    self.assertIn("/INTER/TYPE25/78", starter)

    def test_soft_minus7_eroding_single_surface_unchanged(self):
        """dyna2rad's SOFT -7 sentinel routes an ERODING_SINGLE_SURFACE to
        contacts_general, whose own guard returns first: no stub, no B6
        sentence, the /INTER/TYPE7 of the contact itself - on both arms."""
        extra = ("*CONTACT_ERODING_SINGLE_SURFACE_ID\n" + _row(77) + "\n"
                 + _row(0, 0, 0, 0) + "\n" + _row(0.1) + "\n" + _row() + "\n"
                 + _row(0, 1, 0) + "\n" + _row(-7) + "\n")
        for kw in ({}, {"skip_implicit_stub_with_type25": True}):
            with self.subTest(**kw):
                res, starter, _e = _convert(_shell_plate(_IMPL1, extra), **kw)
                self.assertNotIn(_STUB_TITLE, starter)
                self.assertFalse(_has(res.warnings, _B6_HEAD))
                self.assertTrue(_has(res.warnings, "SOFT=-7"), res.warnings)

    def test_tied_plus_type25_keeps_todays_silence(self):
        """DECISION B6-a: a tied + TYPE25 deck returns at the tied guard,
        silently, as at 4f5b6e8 - on both arms."""
        extra = _N2S_78 + ("*CONTACT_TIED_NODES_TO_SURFACE_ID\n" + _row(79)
                           + "\n" + _row(5, 1, 4, 3) + "\n" + _row() + "\n"
                           + _row() + "\n")
        for kw in ({}, {"skip_implicit_stub_with_type25": True}):
            with self.subTest(**kw):
                res, starter, _e = _convert(_shell_plate(_IMPL1, extra), **kw)
                self.assertNotIn(_STUB_TITLE, starter)
                self.assertFalse(_has(res.warnings, _B6_HEAD))

    def test_opt_in_with_every_type25_dropped_writes_the_stub_after_all(self):
        """The TYPE25's secondary node set does not exist: the writer drops
        it, so under the opt-in nothing stands beside the stub - keyed on the
        WRITTEN set, the deferred section writes it after all (its id drawn
        after the TYPE25 section) and names why; the default arm writes the
        stub as at 4f5b6e8."""
        extra = ("*CONTACT_NODES_TO_SURFACE_ID\n" + _row(78) + "\n"
                 + _row(99, 1, 4, 3) + "\n" + _row(0.1) + "\n" + _row()
                 + "\n")
        deck = _shell_plate(_IMPL1, extra)
        res, starter, _e = _convert(deck, skip_implicit_stub_with_type25=True)
        inters = [ln for ln in starter.splitlines()
                  if ln.startswith("/INTER/")]
        self.assertEqual(len(inters), 1, inters)
        self.assertTrue(inters[0].startswith("/INTER/TYPE7/"), inters)
        stub = _stub_ids(starter)
        self.assertEqual(len(stub), 1, starter)
        self.assertTrue(_has(res.warnings, _B6_STUB_SENTENCE,
                             "/INTER/TYPE7 id %d" % stub[0]), res.warnings)
        self.assertTrue(_has(res.warnings, _B6_FLAG, "[78] reached the deck",
                             "written after all",
                             "/INTER/TYPE7 %d" % stub[0]), res.warnings)
        self.assertFalse(_has(res.warnings, _B6_FLAG + " left out"), res.warnings)
        r0, s0, _e0 = _convert(deck)
        self.assertEqual(len(_stub_ids(s0)), 1, s0)
        self.assertTrue(_has(r0.warnings, _B6_HEAD, "is KEPT"))

    def test_the_opt_in_draws_no_id_before_the_writer(self):
        """The opt-in defers the decision to the writer and returns before
        any id is drawn; the default draws the stub's id there."""
        from k2rad import _inject_implicit_contact_stub
        st = _dispatch(_shell_plate(_IMPL1, _N2S_78))
        st.options.skip_implicit_stub_with_type25 = True
        before = st._auto_id
        _inject_implicit_contact_stub(st)
        self.assertEqual(st._auto_id, before)
        self.assertEqual(st.implicit_stub_deferred_for, [78])
        self.assertEqual(st.contacts_single, [])
        st0 = _dispatch(_shell_plate(_IMPL1, _N2S_78))
        _inject_implicit_contact_stub(st0)
        self.assertEqual(st0.implicit_stub_deferred_for, [])
        self.assertEqual([c.title for c in st0.contacts_single],
                         [_STUB_TITLE])

    def test_the_b6t_coupon_both_arms(self):
        """The coupon of the class docstring: the default is the 4f5b6e8
        deck byte for byte (the stub /INTER/TYPE7 beside /INTER/TYPE25);
        the opt-in writes the TYPE25 alone."""
        res, starter, _e = _convert(_B6T_DECK)
        self.assertEqual(_sha(starter), _B6T_DEFAULT_4F5B6E8_SHA)
        self.assertEqual(len(_stub_ids(starter)), 1, starter)
        self.assertEqual(sum(ln.startswith("/INTER/TYPE25/")
                             for ln in starter.splitlines()), 1)
        r1, s1, _e1 = _convert(_B6T_DECK, skip_implicit_stub_with_type25=True)
        self.assertEqual(_sha(s1), _B6T_SKIP_SHA)
        self.assertEqual(_stub_ids(s1), [])
        self.assertEqual([ln for ln in s1.splitlines()
                          if ln.startswith("/INTER/")],
                         [ln for ln in starter.splitlines()
                          if ln.startswith("/INTER/TYPE25/")])


# ─────────────────────────────────────────────────────────────────────────────
# B7 - (f') the ELFORM 1 / 2 / 6 thick-shell text, (g) the implicit
#      /PROP/SOLID route widened to LAW2 / LAW36 / LAW44 with the NIP
# ─────────────────────────────────────────────────────────────────────────────

_ts_deck = _t7._ts_deck
_TS_TWO = _t7._TS_TWO
_TS_ELASTIC = _t7._TS_ELASTIC
_TS_EXPLICIT = _t7._TS_EXPLICIT
_block_lines = _t7._block_lines
_PLP = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
        + _row(1, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
        + _row(0.0, 0.0, 0.0) + "\n" + _row() + "\n" + _row() + "\n")
_B7_ROUTED = "Isolid 14 with Inpts"
#: sha256 of the 4f5b6e8 starter of _ts_deck() (the all-LAW1 routed card,
#: Inpts 222) - converted from the pristine checkout through
#: test_r14_triage_7._convert; B7 (g) must not move it
_B7_LAW1_4F5B6E8_SHA = (
    "bfb14bbfa5ebd7d7fb0e324bbb715289a2db7474ff341bdddcc23d774263a1c0")


def _solid_card(starter: str, prop: int = 1):
    """(Isolid, Icpre, Inpts) of /PROP/SOLID/<prop>."""
    row = _block_lines(starter, f"/PROP/SOLID/{prop}")[3]
    return int(row[0:10]), int(row[30:40]), int(row[50:60])


class TshellTextAndPlasticRoute(unittest.TestCase):
    """B7: (f') the ELFORM 1 / 2 / 6 sentence names distortion locking (the
    plate coupons, scored AT the node); (g) the implicit route takes the
    plastic laws a coupon measured, LAW2 / LAW36 / LAW44, with Inpts
    _tshell_inpts(14, NIP) = 2*100 + NIP*10 + 2 (LAW1 stays 222).

    Starter + engine runs (nt 4, rcv_r8i_implB_b7_probe{2,9}, harvested
    and deleted): test 2's deck (LAW36, Inpts 252) 0 ERROR, no WARNING 791,
    NORMAL in 101 cycles; the mixed LAW1 + LAW36 deck 0 ERROR with WARNING
    791 on the LAW1 group ('... NOT EQUAL TO 2, SET IT TO 2'), NORMAL in 101
    cycles; the pre-research's free-root plastic cantilever converted here
    ends NORMAL in 21 cycles."""

    def test_f_prime_sentence(self):
        res, _s, _e = _convert(_ts_deck(control=_TS_EXPLICIT))
        hits = [w for w in res.warnings if "PLANE-STRESS" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("-78.75 %", "0.210006 mm", "-2.01 %", "-0.18 %",
                       "+4.61 %", "distortion sensitive", "p.41-116",
                       "0.771729", "18.7x"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        for gone in ("stiffer through the thickness", "-78.88", "-2.63"):
            self.assertNotIn(gone, hits[0])

    def test_plastic_law_is_routed_with_nip(self):
        res, starter, _e = _convert(_ts_deck(mat=_PLP))
        self.assertNotIn("/PROP/TYPE20/1", starter)
        self.assertEqual(_solid_card(starter), (14, 0, 2 * 100 + 5 * 10 + 2))
        hits = [w for w in res.warnings if _B7_ROUTED in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("/MAT/LAW36", "Inpts 252", "NIP=5", "21 cycles",
                       "-3.64 %", "-2.54 %", "hm_read_prop14.F:305",
                       "--no-implicit-tshell-solid"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("WARNING 791", hits[0])
        self.assertFalse(_has(res.warnings, "kept on /PROP/TYPE20"))

    def test_law2_and_law44_routed(self):
        mats = {
            "*MAT_ISOTROPIC_ELASTIC_PLASTIC": (
                "*MAT_ISOTROPIC_ELASTIC_PLASTIC\n"
                + _row(1, 7.85e-9, 80000.0, 250.0, 1000.0, 160000.0) + "\n"),
            "*MAT_PLASTIC_KINEMATIC": (
                "*MAT_PLASTIC_KINEMATIC\n"
                + _row(1, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0, 0.0) + "\n"
                + _row(0.0, 0.0, 0.0) + "\n"),
        }
        for name, card in mats.items():
            with self.subTest(mat=name):
                res, starter, _e = _convert(_ts_deck(mat=card))
                self.assertNotIn("/PROP/TYPE20/1", starter)
                self.assertEqual(_solid_card(starter)[2], 252)
                hits = [w for w in res.warnings if _B7_ROUTED in w]
                self.assertEqual(len(hits), 1, res.warnings)
                self.assertTrue(any(f"/MAT/LAW{n}" in hits[0]
                                    for n in (2, 44)), hits[0])

    def test_nip_digit(self):
        res3, s3, _e = _convert(_ts_deck(mat=_PLP, nip=3))
        self.assertEqual(_solid_card(s3)[2], 232)
        res12, s12, _e = _convert(_ts_deck(mat=_PLP, nip=12))
        self.assertEqual(_solid_card(s12)[2], 292)
        self.assertTrue(_has(res12.warnings, "NIP=12 exceeds",
                             "/PROP/SOLID Inpts on the implicit route, 292"),
                        res12.warnings)

    def test_unmeasured_law_keeps_type20(self):
        foam = ("*MAT_LOW_DENSITY_FOAM\n"
                + _row(1, 1.0e-10, 1.0, 9) + "\n" + _row() + "\n"
                "*DEFINE_CURVE\n" + _row(9) + "\n"
                + f"{0.0:>20}{0.0:>20}\n{0.5:>20}{1.0:>20}\n")
        res, starter, _e = _convert(_ts_deck(mat=foam))
        self.assertIn("/PROP/TYPE20/1", starter)
        self.assertTrue(_has(res.warnings, "kept on /PROP/TYPE20",
                             "LAW2 / LAW36 / LAW44 a coupon measured"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, "applied to *MAT_ELASTIC only"))

    def test_explicit_plastic_keeps_type20(self):
        res, starter, _e = _convert(_ts_deck(control=_TS_EXPLICIT, mat=_PLP))
        self.assertIn("/PROP/TYPE20/1", starter)
        self.assertNotIn("/PROP/SOLID/1", starter)
        self.assertFalse(_has(res.warnings, _B7_ROUTED))

    def test_opt_out_keeps_type20_on_plastic(self):
        res, starter, _e = _convert(_ts_deck(mat=_PLP),
                                    implicit_tshell_solid=False)
        self.assertIn("/PROP/TYPE20/1", starter)
        self.assertFalse(_has(res.warnings, _B7_ROUTED))

    def test_law1_byte_pinned(self):
        res, starter, _e = _convert(_ts_deck())
        self.assertEqual(_solid_card(starter), (14, 0, 222))
        self.assertTrue(_has(res.warnings, _t7._TS_ROUTED), res.warnings)
        self.assertFalse(_has(res.warnings, _B7_ROUTED))
        self.assertEqual(_sha(starter), _B7_LAW1_4F5B6E8_SHA)

    def test_mixed_law1_and_plastic_names_the_791_reset(self):
        two = (_TS_TWO.replace("       2       1       2       9",
                               "       2       2       2       9"))
        parts = ("*PART\ntshell part\n" + _row(1, 1, 1) + "\n"
                 "*PART\nplastic part\n" + _row(2, 1, 2) + "\n")
        plp2 = _PLP.replace(_row(1, 7.85e-9), _row(2, 7.85e-9), 1)
        res, starter, _e = _convert(_ts_deck(elem=two, part=parts,
                                             mat=_TS_ELASTIC + plp2))
        self.assertEqual(_solid_card(starter)[2], 252)
        hits = [w for w in res.warnings if _B7_ROUTED in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("reset to 222 per element group", hits[0])
        self.assertIn("WARNING 791, sgrtails.F:694-704", hits[0])


# ═════════════════════════════════════════════════════════════════════════════
# B8 — the screw joint: the undriven screw + its inertia pad, refusal 11 by
# DOF class, the Lagrange-held contact sentence, the synthetic CI fixture
# ═════════════════════════════════════════════════════════════════════════════

_screw_deck = _t7._screw_deck
_rbody_main = _t7._rbody_main
_screw_synthetic = _t7._screw_synthetic

#: the 4f5b6e8 starter of the DRIVEN mini screw (_screw_deck()), measured
#: through the round-7 harness with the PRISTINE k2rad: a driven screw gets
#: no pad and its bodies carry no standard code, so B8 moves no byte of it
_B8_DRIVEN_4F5B6E8_SHA = (
    "2a0af96aa06a437ceaf145306413fb0a8eaa73b6112dfb829f68953010facac1")

#: the undriven sentence's needle and the merge sentence's
_B8_UNDRIVEN = "has NO drive: converted without /IMPVEL/LAGMUL"
_B8_MERGED = "acts on DOFs the converted joint already holds"


def _rbody_j(starter: str, main: int) -> Tuple[float, float, float]:
    """``(Jxx, Jyy, Jzz)`` of ``/RBODY/<main>`` (its card 2)."""
    lines = starter.splitlines()
    i = lines.index(f"/RBODY/{main}")
    row = lines[i + 5]
    return (float(row[0:20]), float(row[20:40]), float(row[40:60]))


def _standard_bcs_nodes(starter: str) -> Set[int]:
    """Every node a STANDARD /BCS card (not /BCS/LAGMUL) holds."""
    lines = starter.splitlines()
    groups: Dict[int, List[int]] = {}
    i = 0
    while i < len(lines):
        m = re.match(r"^/GRNOD/NODE/(\d+)$", lines[i])
        if m:
            ids: List[int] = []
            j = i + 2
            while (j < len(lines) and not lines[j].startswith("/")
                   and not lines[j].startswith("#-")):
                if not lines[j].startswith("#"):
                    ids += [int(t) for t in lines[j].split()]
                j += 1
            groups[int(m.group(1))] = ids
            i = j
            continue
        i += 1
    out: Set[int] = set()
    for i, ln in enumerate(lines):
        if re.match(r"^/BCS/\d+$", ln):
            out.update(groups.get(int(lines[i + 3].split()[-1]), []))
    return out


def _flat_a(deck: str) -> str:
    """The mini screw with A FLAT: its hex 2 mm along the axis (x 18 .. 20)
    and 20 x 20 mm across (y / z 0 .. 20) - N3 (node 1) moves to (18, 0, 0),
    N1 stays at (20, 0, 0), so the axis runs along an edge of the hex. About
    the lumped CoG (19, 10, 10): I_axis = 200 m > I_t = 101 m."""
    out = []
    for ln in deck.splitlines():
        if (len(ln) == 56 and ln[:8].strip().isdigit()
                and 1 <= int(ln[:8]) <= 8):
            x, y, z = (float(ln[8:24]), float(ln[24:40]), float(ln[40:56]))
            ln = (f"{ln[:8]}{18.0 + 0.2 * (x - 10.0):>16.4f}"
                  f"{2.0 * y:>16.4f}{2.0 * z:>16.4f}")
        out.append(ln)
    return "\n".join(out) + "\n"


class JointScrewRound8(unittest.TestCase):
    """B8 (round 8; under the existing --no-joint-screw-gjoint, no new flag):
    (q-i) a screw whose deck states NO drive converts without
    /IMPVEL/LAGMUL and pads A's J row so the Lagrange solver's ONE scalar
    (the main node's smallest principal inertia, inirby.F:838 /
    lag_mult_solv.F:393) is A's screw-axis inertia; (q-ii) refusal 11 by DOF
    class - a code on DOFs the joint holds is merged (written nowhere); (q-iii)
    the split names the residual drift; (q-iv) the synthetic CI fixture."""

    def test_undriven_screw_converts_with_the_pad(self):
        res, starter, _e = _convert(_screw_deck(drive=False))
        self.assertIn("/GJOINT/RACK/", starter)
        self.assertEqual(starter.count("/BCS/LAGMUL/"), 2)
        self.assertNotIn("/IMPVEL/LAGMUL/", starter)
        self.assertNotIn("SCREW_9_dTHETA_dt", starter)
        self.assertFalse(_has(res.warnings, ": NOT converted - "),
                         res.warnings)
        # A = one 10 mm hex (x 10 .. 20, y / z 0 .. 10): 8 lumped corner
        # masses m/8 at (y, z) = (5 +- 5, 5 +- 5) about the CoG (15, 5, 5)
        m = 7.85e-9 * 1000.0
        d_j = 8 * (m / 8.0) * (25.0 + 25.0)          # = 50 m
        jxx, jyy, jzz = _rbody_j(starter, _rbody_main(starter, 2))
        self.assertEqual(jxx, 0.0)
        self.assertAlmostEqual(jyy / d_j, 1.0, delta=1e-9)
        self.assertAlmostEqual(jzz / d_j, 1.0, delta=1e-9)
        hits = [w for w in res.warnings if _B8_UNDRIVEN in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("147.716", "145.989", "+75.5 %", "inirby.F:838",
                       "lag_mult_solv.F:393", f"added inertia {d_j:g}"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        # the rack sentence no longer claims a drive it does not write
        self.assertNotIn("the drive are re-written", hits[0])

    def test_flat_A_pad_makes_the_axis_the_smallest_principal(self):
        """Mutation target: a pad of 0.5 (I_axis - I_t,min) leaves the
        transverse value at 150.5 m < 200 m and fails this test."""
        from k2rad.lumping import _sym3_eigen
        res, starter, _e = _convert(_flat_a(_screw_deck(drive=False)))
        self.assertIn("/GJOINT/RACK/", starter)
        m = 7.85e-9 * 2.0 * 20.0 * 20.0
        # the point-mass tensor about the CoG (19, 10, 10): d = (+-1, +-10,
        # +-10), every product of inertia 0 by symmetry
        t = [[200.0 * m, 0.0, 0.0], [0.0, 101.0 * m, 0.0],
             [0.0, 0.0, 101.0 * m]]
        j = _rbody_j(starter, _rbody_main(starter, 2))
        self.assertEqual(j[0], 0.0)
        self.assertAlmostEqual(j[1] / (200.0 * m), 1.0, delta=1e-9)
        for k in range(3):
            t[k][k] += j[k]
        smallest = min(_sym3_eigen(t)[0])
        self.assertAlmostEqual(smallest / (200.0 * m), 1.0, delta=1e-9)
        hits = [w for w in res.warnings if _B8_UNDRIVEN in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertNotIn("below it", hits[0])

    def test_a_refused_vad3_drive_is_not_no_drive(self):
        """Mutation target: testing the converted registry (on_a) instead of
        state.pm_rigid_stated_pids converts this deck as undriven."""
        res, starter, _e = _convert(_screw_deck(vad=3))
        self.assertNotIn("/GJOINT/", starter)
        hits = [w for w in res.warnings if ": NOT converted - " in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("is not converted (a VAD 3 / 4 card is not converted "
                      "at all; a refused drive is not 'no drive')", hits[0])
        st = _t7._dispatch(_screw_deck(vad=3))
        self.assertEqual(st.pm_rigid_stated_pids, {2})
        self.assertEqual(st.prescribed_motions, [])

    def test_driven_screw_bytes_unchanged(self):
        res, starter, _e = _convert(_screw_deck())
        self.assertEqual(_rbody_j(starter, _rbody_main(starter, 2)),
                         (0.0, 0.0, 0.0))
        self.assertIn("/IMPVEL/LAGMUL/", starter)
        self.assertFalse(_has(res.warnings, _B8_UNDRIVEN), res.warnings)
        self.assertEqual(_sha(starter), _B8_DRIVEN_4F5B6E8_SHA)

    def test_refusal_11_by_class(self):
        """Mutation targets: a merge that writes the card (the 'no standard
        /BCS' assertion fails); a drive-DOF code that merges (the RC 1
        subtest fails)."""
        held = (("a *NODE TC 3 on A (A's z: held)", {"a_node_tc": 3}, 2,
                 "the *NODE TC 3 / RC 0 of its node 3 on body A (part 2)"),
                ("a *BOUNDARY_SPC DOFY on B (B's y: held)", {"b_spc": True},
                 1, "on body B (part 1)"))
        for name, kw, part, needle in held:
            with self.subTest(case=name):
                res, starter, _e = _convert(_screw_deck(**kw))
                self.assertIn("/GJOINT/RACK/", starter)
                hits = [w for w in res.warnings if _B8_MERGED in w]
                self.assertEqual(len(hits), 1, res.warnings)
                self.assertIn(needle, hits[0])
                self.assertIn("-0.07 %", hits[0])
                self.assertIn("+2.57 %", hits[0])
                main = _rbody_main(starter, part)
                self.assertNotIn(main, _standard_bcs_nodes(starter))
        refused = (
            ("a *CONSTRAINED_GLOBAL TC 1 through B (axial: free)",
             {"b_global": True},
             "on a free DOF of the joint (the axial translation)"),
            ("a nodal prescribed motion on A", {"a_node_motion": True},
             "a nodal prescribed motion"),
            ("a *NODE RC 1 on A (the drive's DOF)", {"a_node_rc": 1},
             "on the drive's DOF (A's rotation about the screw axis)"),
            ("a *NODE RC 1 on an undriven A (its spin: free)",
             {"a_node_rc": 1, "drive": False},
             "on a free DOF of the joint (A's spin about the screw axis)"),
            ("a *NODE TC 1 on A (axial: free)", {"a_node_tc": 1},
             "on a free DOF of the joint (the axial translation)"))
        for name, kw, needle in refused:
            with self.subTest(case=name):
                res, starter, _e = _convert(_screw_deck(**kw))
                self.assertNotIn("/GJOINT/", starter)
                hits = [w for w in res.warnings if ": NOT converted - " in w]
                self.assertEqual(len(hits), 1, res.warnings)
                self.assertIn(needle, hits[0])
                if "motion" not in name:
                    self.assertIn("starter WARNING 312", hits[0])

    def test_round7_refusal_list_moves(self):
        """The round-7 refusal list keeps every class the joint still
        refuses; the two held codes and 'no drive' left it (re-homed in the
        tests above) and VAD 3's needle names the stated drive."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_r14_triage_7.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for gone in ('("a *NODE TC on A"', '("a *BOUNDARY_SPC on B"',
                     '("no drive"'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, src)
        for kept in ('("a *CONSTRAINED_GLOBAL plane through B"',
                     '("a nodal prescribed motion on A"', '("VAD 3"'):
            with self.subTest(kept=kept):
                self.assertIn(kept, src)

    def test_the_split_sentence_names_the_drift(self):
        res, _s, _e = _convert(_screw_deck())
        hits = [w for w in res.warnings if "is split out" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("drifts off its main node by the cancelled impulse",
                       "0.0560 mm", "0.0250 mm", "0.0145 mm", "178.67 mm",
                       "The rigid-to-deformable pairs of part 2 and part 1 "
                       "stay"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])

    def test_the_lagrange_pair_helper_is_the_split_predicate(self):
        from k2rad.writer.joint_screw import lagrange_held_pairs
        from k2rad.writer.assembly import build_starter
        st = _t7._dispatch(_screw_deck())
        build_starter(st)
        pairs = lagrange_held_pairs(st, 90001)
        self.assertEqual([(p.a_pid, p.b_pid, p.tag, p.label) for p in pairs],
                         [(2, 1, "screw_9", "*CONSTRAINED_JOINT_SCREW 9")])
        self.assertEqual(lagrange_held_pairs(st, 90002), [])

    def test_the_synthetic_deck(self):
        """B8.5 (q-iv): the opt-out, the undriven and the merge variants of
        the synthetic look-alike (its six round-7 assertions are
        test_r14_triage_7.JointScrewGjoint.test_the_synthetic_deck)."""
        ss = _screw_synthetic()
        ids = ss.node_ids()
        # the opt-out: the 65ff389 skip
        r0, s0, _e0 = _convert(ss.build_deck(), joint_screw_gjoint=False)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_JOINT_SCREW", s0)
        self.assertNotIn("/GJOINT/", s0)
        self.assertTrue(_has(r0.warnings, "--no-joint-screw-gjoint: 1 "
                             "*CONSTRAINED_JOINT_SCREW card(s) left "
                             "unconverted"), r0.warnings)
        # the undriven variant: no drive, A's J row (0, dJ, dJ) with dJ the
        # lumped Ixx of A's 27-node block (x 4000 .. 4100 in 2 x 50 mm,
        # y / z -10 .. 10 in 2 x 10 mm): a node at index (i, j, k) carries
        # c(i) c(j) c(k) / 8 of a hex's mass, c = 1 at an end, 2 in the middle
        r1, s1, _e1 = _convert(ss.build_deck(drive=False))
        self.assertIn("/GJOINT/RACK/", s1)
        self.assertNotIn("/IMPVEL/LAGMUL/", s1)
        self.assertNotIn("SCREW_9000002_dTHETA_dt", s1)
        m_hex = ss.RO * 50.0 * 10.0 * 10.0
        c = (1, 2, 1)
        d_j = math.fsum(c[i] * c[j] * c[k] * m_hex / 8.0
                        * ((-10.0 + 10.0 * j) ** 2 + (-10.0 + 10.0 * k) ** 2)
                        for i in range(3) for j in range(3) for k in range(3))
        jxx, jyy, jzz = _rbody_j(s1, 10059663)
        self.assertEqual(jxx, 0.0)
        self.assertAlmostEqual(jyy / d_j, 1.0, delta=1e-9)
        self.assertAlmostEqual(jzz / d_j, 1.0, delta=1e-9)
        self.assertTrue(_has(r1.warnings, _B8_UNDRIVEN), r1.warnings)
        # the merge variant: a *BOUNDARY_SPC DOFY on N1 (A's y: held)
        spc = "*BOUNDARY_SPC_NODE\n" + ss._row(ids["N1"], 0, 0, 1, 0, 0, 0, 0)
        r2, s2, _e2 = _convert(ss.build_deck(extra=spc))
        self.assertIn("/GJOINT/RACK/", s2)
        self.assertTrue(_has(r2.warnings, _B8_MERGED,
                             f"its node {ids['N1']} on body A (part "
                             "10000046)"), r2.warnings)
        self.assertNotIn(10059663, _standard_bcs_nodes(s2))
        self.assertNotIn(ids["N1"], _standard_bcs_nodes(s2))


# ═════════════════════════════════════════════════════════════════════════════
# B9 — B4's two tied-node refusal notes state the measured mechanism
# ═════════════════════════════════════════════════════════════════════════════

_tied_plates = _t7._tied_plates


class MpcTiedNotesRound8(unittest.TestCase):
    """B9 (text only, 0 bytes): the 'tied' note no longer implies a
    Spotflag-27 exemption nor calls the mechanism uncharacterised; the
    'tied_main' note carries the mechanism read from the code order and the
    second geometries (the round-8 critic's G4 S / U arms, nt 4 = nt 2)."""

    def _sentence(self, deck):
        res, starter, _e = _convert(deck)
        self.assertNotIn("/MPC/", starter)
        hits = [w for w in res.warnings if "NOT converted to /MPC" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        return hits[0]

    def test_the_secondary_note(self):
        """Node 20 is a secondary node of the Spotflag-28 tie, node 26 on
        neither side: only the 'tied' note fires."""
        why = self._sentence(_tied_plates(
            "NODES", terms=((20, 3, 1.0), (26, 3, -1.0))))
        for needle in ("i2vit3.F:386-389", "lag_ntag.F:131",
                       "the redundant term is not redundant on Spotflag 28",
                       "p.10-135", "itagsl2.F:92", "6237", "19.6 %",
                       "no Spotflag is exempt"):
            with self.subTest(needle=needle):
                self.assertIn(needle, why)
        for gone in ("held on that probe", "not characterised"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, why)

    def test_the_main_side_note(self):
        why = self._sentence(_tied_plates(
            "NODES", terms=((8, 3, 1.0), (5, 3, -1.0))))
        for needle in ("READ from the code order", "lag_ntag.F:131",
                       "resol.F:7675", "resol.F:7901", "i2vit3.F:504-509",
                       "x130.9", "x50.54", "x1983",
                       "-0.01 % with the tie's contact energy counted",
                       # the round-7 needles, every one kept
                       "MEMBERS, not one side",
                       "IE 1.25e6 against external work -3.9",
                       "IE 3.83e4 against 48.2", "IE 1.80e6",
                       "IE 20.27 against 20.28", "20.35 against 20.36",
                       "can only refuse more"):
            with self.subTest(needle=needle):
                self.assertIn(needle, why)
        self.assertNotIn("held on that probe", why)


# ═════════════════════════════════════════════════════════════════════════════
# B10 — *CONSTRAINED_SHELL_IN_SOLID -> /INTER/TYPE18 (opt-in
# --shell-in-solid-coupling) + the rewritten default warning
# ═════════════════════════════════════════════════════════════════════════════

def _sis_ale_deck(card2: str = "", void: bool = True, host_iale: bool = True,
                  eos: str = "gruneisen", shstyp: int = 0, sstyp: int = 0,
                  shared_mid: bool = False, no_shells: bool = False,
                  ro: float = 1.0e-9, c: float = 1.5e6, penalty: bool = False,
                  host=(12.5, 12.5, 12.5), plate: float = 12.5,
                  clis: bool = False, vfact: str = "1.0E-6",
                  extra: str = "") -> str:
    """bird-el's shape, by hand: part 1 = a 2 x 2 x 2 block of *host* bricks
    (ELFORM 12, or 1 when not *host_iale*) on *MAT_NULL 1 (RO *ro*) + its EOS
    (``gruneisen`` C *c*, ``linpoly`` C1 = RO C^2, ``ideal_gas``); part 3 = a
    2 x 2 plate of *plate* squares (ELFORM 2, t 1, *MAT_ELASTIC 3) at the
    block's mid-height; *INITIAL_VOID_PART 1 when *void*; *CONTROL_ALE with
    VFACT *vfact*; *SET_PART_LIST 1 = {3}, 2 = {1}; one
    *CONSTRAINED_SHELL_IN_SOLID[_PENALTY]_ID 1 (SHSID / SSID the sets, or
    the part ids when the type cells say 1) with *card2* as its card 2.
    *shared_mid* adds part 2 = one more brick column on the SAME *MAT_NULL 1
    (not a void); *no_shells* makes SHSID name the host; *clis* writes a
    *CONSTRAINED_LAGRANGE_IN_SOLID (structure part 3, fluid part 1) instead
    of the shell-in-solid card; *extra* goes before *END."""
    dx, dy, dz = host
    out = ["*KEYWORD", "*CONTROL_TERMINATION", _row(1.0e-3),
           "*CONTROL_ALE", _row(3, 1, 1, 0.0),
           _row(0.0, 0.0, 0.0) + f"{vfact:>10}", "*NODE"]
    nid = 0
    ids = {}
    for k in range(3):
        for j in range(3):
            for i in range(3 + (1 if shared_mid else 0)):
                nid += 1
                ids[(i, j, k)] = nid
                out.append(f"{nid:>8}{dx * i:>16.4f}{dy * j:>16.4f}"
                           f"{dz * k:>16.4f}")
    plate_ids = {}
    for j in range(3):
        for i in range(3):
            nid += 1
            plate_ids[(i, j)] = nid
            out.append(f"{nid:>8}{plate * i:>16.4f}{plate * j:>16.4f}"
                       f"{dz:>16.4f}")
    out.append("*ELEMENT_SOLID")
    eid = 0
    for k in range(2):
        for j in range(2):
            for i in range(3 if shared_mid else 2):
                eid += 1
                hx = [ids[(i, j, k)], ids[(i + 1, j, k)],
                      ids[(i + 1, j + 1, k)], ids[(i, j + 1, k)],
                      ids[(i, j, k + 1)], ids[(i + 1, j, k + 1)],
                      ids[(i + 1, j + 1, k + 1)], ids[(i, j + 1, k + 1)]]
                pid = 2 if i == 2 else 1
                out.append("".join(f"{v:>8}" for v in [eid, pid] + hx))
    out.append("*ELEMENT_SHELL")
    for j in range(2):
        for i in range(2):
            eid += 1
            out.append("".join(f"{v:>8}" for v in (
                eid, 3, plate_ids[(i, j)], plate_ids[(i + 1, j)],
                plate_ids[(i + 1, j + 1)], plate_ids[(i, j + 1)])))
    out += ["*PART", "host", _row(1, 1, 1, 1),
            "*PART", "plate", _row(3, 3, 3)]
    if shared_mid:
        out += ["*PART", "fluid 2", _row(2, 1, 1, 1)]
    out += ["*SECTION_SOLID", _row(1, 12 if host_iale else 1),
            "*SECTION_SHELL", _row(3, 2), _row(1.0, 1.0, 1.0, 1.0),
            "*MAT_NULL", _row(1, ro, 0.0, 0.0),
            "*MAT_ELASTIC", _row(3, 7.85e-9, 210000.0, 0.3)]
    if eos == "gruneisen":
        out += ["*EOS_GRUNEISEN", _row(1, c, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _row(0.0)]
    elif eos == "linpoly":
        out += ["*EOS_LINEAR_POLYNOMIAL",
                _row(1, 0.0, ro * c * c, 0.0, 0.0, 0.0, 0.0, 0.0),
                _row(0.0, 1.0)]
    elif eos == "ideal_gas":
        out += ["*EOS_IDEAL_GAS", _row(1, 718.0, 1005.0, 0.0, 0.0, 293.0)]
    out += ["*SET_PART_LIST", _row(1), _row(3),
            "*SET_PART_LIST", _row(2), _row(1)]
    if void:
        out += ["*INITIAL_VOID_PART", _row(1)]
    if clis:
        out += ["*CONSTRAINED_LAGRANGE_IN_SOLID", _row(3, 1, 1, 1, 0, 4),
                _row(0.0, 0.0, 0.1), ""]
    else:
        shsid = (1 if shstyp == 1 else 2) if no_shells else (
            3 if shstyp == 1 else 1)
        ssid = 1 if sstyp == 1 else 2
        out += ["*CONSTRAINED_SHELL_IN_SOLID"
                + ("_PENALTY" if penalty else "") + "_ID",
                _row(1), _row(shsid, ssid, shstyp, sstyp)]
        if card2:
            out.append(card2)
    if extra:
        out.append(extra.rstrip("\n"))
    out.append("*END")
    return "\n".join(out) + "\n"


def _type18(starter: str):
    """``(surf parts, grbric parts, line-2 text)`` of the one
    /INTER/TYPE18, or None."""
    lines = starter.splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("/INTER/TYPE18/")]
    if not heads:
        return None
    i = heads[0]
    data = [ln for ln in lines[i + 2:i + 7] if not ln.startswith("#")]
    surf, grb = int(data[0][10:20]), int(data[0][20:30])

    def members(prefix, gid):
        k = lines.index(f"{prefix}{gid}")
        return [int(t) for t in lines[k + 2].split()]
    return (members("/SURF/PART/EXT/", surf), members("/GRBRIC/PART/", grb),
            data[1])


def _hyd_visc(starter: str, mid: int):
    """``(RHO_I text, Pmin text)`` of /MAT/HYD_VISC/<mid>."""
    lines = starter.splitlines()
    i = lines.index(f"/MAT/HYD_VISC/{mid}")
    return lines[i + 3], lines[i + 5]


def _eos_rho0(starter: str, kind: str, mid: int) -> str:
    lines = starter.splitlines()
    i = lines.index(f"/EOS/{kind}/{mid}")
    return lines[i + 5][-20:]


_SIS_ON = "(--shell-in-solid-coupling): shell part(s)"
_SIS_LINE2 = _f(2812.5) + _f(0.0) + _f(6.25) + _f(0.0) + _f(0.0)


class ShellInSolidCoupling(unittest.TestCase):
    """B10: the opt-in writes *CONSTRAINED_SHELL_IN_SOLID as an /INTER/TYPE18
    with Stfval = 0.1 K A^2 / V (PSSF on _PENALTY), Gap = half the mean host
    edge, and the void density on an *INITIAL_VOID host of the card only;
    the default is the 4f5b6e8 deck with the rewritten warning."""

    def test_flag_off_is_the_4f5b6e8_deck(self):
        res, starter, _e = _convert(_sis_ale_deck())
        self.assertIn("#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLID", starter)
        self.assertNotIn("/INTER/TYPE18", starter)
        hits = [w for w in res.warnings
                if w.startswith("*CONSTRAINED_SHELL_IN_SOLID: 1 card(s)")]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("2812.5", "-28.26 %", "8.936x", "30.51 / 4.88",
                       "2.227e-4", "3.6 %", "--shell-in-solid-coupling"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertEqual(_hyd_visc(starter, 1)[0], _f(1.0e-9))
        self.assertEqual(_eos_rho0(starter, "GRUNEISEN", 1), _f(0.0))

    def test_flag_on_writes_the_coupling(self):
        """Stfval 0.1 x 2250 x 156.25^2 / 1953.125 = 2812.5; Gap 6.25. A
        starter run of this deck (nt 4) reads 0 errors (B10 evidence).
        Mutation target: Stfval without the 0.1."""
        res, starter, _e = _convert(_sis_ale_deck(),
                                    shell_in_solid_coupling=True)
        surf, grb, line2 = _type18(starter)
        self.assertEqual((surf, grb, line2), ([3], [1], _SIS_LINE2))
        self.assertEqual(_hyd_visc(starter, 1)[0], _f(1.0e-15))
        self.assertEqual(_eos_rho0(starter, "GRUNEISEN", 1), _f(1.0e-9))
        self.assertNotIn("#-- SKIPPED: *CONSTRAINED_SHELL_IN_SOLID", starter)
        self.assertNotIn("CONSTRAINED_SHELL_IN_SOLID", res.skipped_keywords)
        hits = [w for w in res.warnings if _SIS_ON in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("Stfval = 0.1 x K 2250 x A^2 156.25^2 / V 1953.12",
                       "= 2812.5", "Gap 6.25", "RHO_I 1e-15 (VFACT x RO)",
                       "-28.26 %", "8.936x", "+284.04 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertFalse(_has(res.warnings,
                              "*CONSTRAINED_SHELL_IN_SOLID: 1 card(s)"))

    def test_stfval_on_a_non_cubic_host(self):
        """Host bricks 10 x 10 x 20, plate squares 10 x 10: Stfval = 0.1 x
        2250 x 100^2 / 2000 = 1125; Gap = 0.5 x the mean FIRST edge = 5."""
        _r, starter, _e = _convert(_sis_ale_deck(host=(10.0, 10.0, 20.0),
                                                 plate=10.0),
                                   shell_in_solid_coupling=True)
        self.assertEqual(_type18(starter)[2],
                         _f(1125.0) + _f(0.0) + _f(5.0) + _f(0.0) + _f(0.0))

    def test_penalty_pssf(self):
        res, starter, _e = _convert(
            _sis_ale_deck(penalty=True, card2=_row(0.0, 0.0, 0, 0, 0, 0.05)),
            shell_in_solid_coupling=True)
        self.assertEqual(_type18(starter)[2][:20], _f(1406.25))
        self.assertTrue(_has(res.warnings, _SIS_ON, "_PENALTY PSSF 0.05"),
                        res.warnings)
        self.assertNotIn("CONSTRAINED_SHELL_IN_SOLID_PENALTY",
                         res.skipped_keywords)

    def test_start_and_end(self):
        """START 1e-4 -> Tstart; END 5e-4 -> Tstop; END 0 / 1e20 -> 0
        (never, the starter's 1e30)."""
        _r, s1, _e = _convert(_sis_ale_deck(card2=_row(1.0e-4, 5.0e-4)),
                              shell_in_solid_coupling=True)
        self.assertEqual(_type18(s1)[2][60:],
                         _f(1.0e-4) + _f(5.0e-4))
        _r, s2, _e = _convert(_sis_ale_deck(card2=_row(0.0, 0.0)),
                              shell_in_solid_coupling=True)
        self.assertEqual(_type18(s2)[2][60:], _f(0.0) + _f(0.0))

    def test_linear_polynomial_host(self):
        _r, starter, _e = _convert(_sis_ale_deck(eos="linpoly"),
                                   shell_in_solid_coupling=True)
        self.assertEqual(_type18(starter)[2], _SIS_LINE2)
        lines = starter.splitlines()
        i = lines.index("/EOS/POLYNOMIAL/1")
        self.assertEqual(lines[i + 5][-20:], _f(1.0e-9))
        self.assertEqual(_hyd_visc(starter, 1)[0], _f(1.0e-15))

    def test_set_types(self):
        for shstyp in (0, 1):
            for sstyp in (0, 1):
                with self.subTest(shstyp=shstyp, sstyp=sstyp):
                    _r, starter, _e = _convert(
                        _sis_ale_deck(shstyp=shstyp, sstyp=sstyp),
                        shell_in_solid_coupling=True)
                    self.assertEqual(_type18(starter)[:2], ([3], [1]))

    def test_non_void_host_gets_no_density(self):
        _r, starter, _e = _convert(_sis_ale_deck(void=False),
                                   shell_in_solid_coupling=True)
        self.assertEqual(_type18(starter)[2], _SIS_LINE2)
        self.assertEqual(_hyd_visc(starter, 1)[0], _f(1.0e-9))
        self.assertEqual(_eos_rho0(starter, "GRUNEISEN", 1), _f(0.0))

    def test_shared_mid_gets_a_copy(self):
        res, starter, _e = _convert(_sis_ale_deck(shared_mid=True),
                                    shell_in_solid_coupling=True)
        lines = starter.splitlines()
        part1 = lines[lines.index("/PART/1") + 2]
        part2 = lines[lines.index("/PART/2") + 2]
        copy = int(part1[10:20])
        self.assertNotEqual(copy, 1)
        self.assertEqual(int(part2[10:20]), 1)
        self.assertEqual(_hyd_visc(starter, copy)[0], _f(1.0e-15))
        self.assertEqual(_eos_rho0(starter, "GRUNEISEN", copy), _f(1.0e-9))
        self.assertEqual(_hyd_visc(starter, 1)[0], _f(1.0e-9))
        self.assertEqual(_eos_rho0(starter, "GRUNEISEN", 1), _f(0.0))
        # the copy keeps the original's Pmin cell (the void floor)
        self.assertEqual(_hyd_visc(starter, copy)[1],
                         _hyd_visc(starter, 1)[1])
        self.assertTrue(_has(res.warnings, _SIS_ON,
                             "a copy of *MAT_NULL 1"), res.warnings)

    def test_every_refusal_class(self):
        """Each refused card keeps the flag-OFF bytes (no id drawn before
        the last screen) plus ONE refusal sentence. Every probe passed a
        starter run (nt 4, 0 errors; B10 evidence). Mutation target: an id
        drawn before the refusal screen."""
        cases = (
            ("an ELFORM 1 host", {"host_iale": False},
             "is not an ALE solid"),
            ("an ideal-gas host", {"eos": "ideal_gas"},
             "its EOS is *EOS_IDEAL_GAS"),
            ("RO 0", {"ro": 0.0}, "RO 0 / C 1.5e+06"),
            ("C 0", {"c": 0.0}, "C 0 - the stiffness RO C^2"),
            ("no shells", {"no_shells": True},
             "names no part with shell elements"),
            ("START < 0", {"card2": _row(-0.1)}, "START < 0"),
            ("END -9999", {"card2": _row(0.0, -9999.0)}, "END -9999"),
            ("END < 0", {"card2": _row(0.0, -0.5)}, "END < 0"))
        # an all-parts self-contact draws auto ids AFTER the prepass, so an
        # id drawn before the last screen would shift its bytes
        contact = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 5, 0)
                   + "\n" + _row(0.1, 0.0) + "\n")
        for name, kw, needle in cases:
            with self.subTest(case=name):
                deck = _sis_ale_deck(**kw)
                r_on, s_on, e_on = _convert(deck,
                                            shell_in_solid_coupling=True)
                _r0, s_off, e_off = _convert(deck)
                self.assertEqual(s_on, s_off)
                self.assertEqual(e_on, e_off)
                deck_c = _sis_ale_deck(extra=contact, **kw)
                _r1, s1_on, _e1 = _convert(deck_c,
                                           shell_in_solid_coupling=True)
                _r2, s1_off, _e2 = _convert(deck_c)
                self.assertIn("/INTER/", s1_on)
                self.assertEqual(s1_on, s1_off)
                self.assertNotIn("/INTER/TYPE18", s_on)
                hits = [w for w in r_on.warnings
                        if "not converted under --shell-in-solid-coupling"
                        in w]
                self.assertEqual(len(hits), 1, r_on.warnings)
                self.assertIn(needle, hits[0])
                self.assertIn("CONSTRAINED_SHELL_IN_SOLID",
                              r_on.skipped_keywords)

    def test_clis_void_decks_unchanged_under_the_flag(self):
        """The density gate is the SIS card, never *INITIAL_VOID alone: a
        CLIS + *INITIAL_VOID deck (bird_B's shape) is byte-identical with
        and without the flag. Mutation target: the density written on a
        CLIS host."""
        deck = _sis_ale_deck(clis=True)
        r_on, s_on, e_on = _convert(deck, shell_in_solid_coupling=True)
        _r0, s_off, e_off = _convert(deck)
        self.assertEqual(s_on, s_off)
        self.assertEqual(e_on, e_off)
        self.assertEqual(_hyd_visc(s_on, 1)[0], _f(1.0e-9))


# ═════════════════════════════════════════════════════════════════════════════
# B3 (h.2) — --imflag-curve-restart: one engine file per IMFLAG segment
# ═════════════════════════════════════════════════════════════════════════════

_IE_POINTS = ((0.0, 1.0), (0.00999, 1.0), (0.01, 0.0), (1.0, 0.0))


def _ie_strip_deck(curve_pts=_IE_POINTS, endtim: float = 0.025,
                   dt0: float = 5.0e-4, timestep: bool = False,
                   sfa: float = 1.0, imflag: int = -9) -> str:
    """ie_shell's shape, by hand (no repo copy of the LS-DYNA example): a 10
    x 1 strip of 10 mm shells (22 nodes, ELFORM 16, t 1, *MAT_ELASTIC) on
    x 0..100, its root edge (x 0) held by *NODE TC 7 / RC 7, a
    *LOAD_NODE_POINT on the two tip nodes along z with curve 98 = ie_shell's
    (0, 0) (0.01, 5) (0.01001, 0) (1, 0); *CONTROL_IMPLICIT_GENERAL IMFLAG
    *imflag* DT0 *dt0* (IMFORM 2, NSBS 1, IGS 2 as ie_shell) and ie_shell's
    *CONTROL_IMPLICIT_SOLUTION NSOLVR 12 / NLNORM 2 (without them the
    converted /IMPL/NONLIN's Itol 2 diverges on this strip from cycle 0 -
    measured, the B3 evidence), curve 9 = *curve_pts* (SFA *sfa*), ENDTIM
    *endtim*, and *CONTROL_TIMESTEP DT2MS -1e-6 when *timestep*."""
    out = ["*KEYWORD", "*TITLE", "ie strip", "*CONTROL_TERMINATION",
           _row(endtim), "*CONTROL_IMPLICIT_GENERAL",
           _row(imflag, dt0, 2, 1, 2),
           "*CONTROL_IMPLICIT_SOLUTION", _row(12), _row(0, 1, 0, 0, 2)]
    if timestep:
        out += ["*CONTROL_TIMESTEP", _row(0.0, 0.9, 0, 0.0, -1.0e-6)]
    out.append("*NODE")
    for j in range(2):
        for i in range(11):
            nid = 1 + i + 11 * j
            tail = f"{7:>8}{7:>8}" if i == 0 else ""
            out.append(f"{nid:>8}{10.0 * i:>16.4f}{10.0 * j:>16.4f}"
                       f"{0.0:>16.4f}" + tail)
    out.append("*ELEMENT_SHELL")
    for i in range(10):
        out.append("".join(f"{v:>8}" for v in (
            i + 1, 1, 1 + i, 2 + i, 13 + i, 12 + i)))
    out += ["*PART", "strip", _row(1, 1, 1),
            "*SECTION_SHELL", _row(1, 16), _row(1.0, 1.0, 1.0, 1.0),
            "*MAT_ELASTIC", _row(1, 7.85e-9, 210000.0, 0.3),
            "*LOAD_NODE_POINT", _row(11, 3, 98, 1.0), _row(22, 3, 98, 1.0),
            "*DEFINE_CURVE", _row(98)]
    out += [f"{x:>20}{y:>20}" for x, y in
            ((0.0, 0.0), (0.01, 5.0), (0.01001, 0.0), (1.0, 0.0))]
    out += ["*DEFINE_CURVE", _row(9, 0, sfa)]
    out += [f"{x:>20}{y:>20}" for x, y in curve_pts]
    out.append("*END")
    return "\n".join(out) + "\n"


def _convert_files(deck: str, **kw):
    """convert() a deck; return (result, starter, [engine texts in run
    order])."""
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    res = convert(path, write_log=False, **kw)
    with open(res.starter_path) as fh:
        starter = fh.read()
    engines = []
    for p in res.engine_paths:
        with open(p) as fh:
            engines.append(fh.read())
    names = [os.path.basename(p) for p in res.engine_paths]
    tmp.cleanup()
    return res, starter, engines, names


from k2rad import convert  # noqa: E402

#: the two engine files of the strip deck under the flag, as the
#: implementation writes them (pinned on the round-8 branch)
_IE_STRIP_PINS = (
    "6795df969a38908f5639ed2d0131608d735e4a338986292bb9b2550f2f285701",
    "77a88e5d53781e2477c8b9b3cf107c0c1df0ca587edb9a98470fb8788f840da4")


class ImflagCurveRestart(unittest.TestCase):
    """B3 (h.2): --imflag-curve-restart writes an IMFLAG < 0 deck whose curve
    switches the method as ONE ENGINE FILE PER SEGMENT; the flag off
    (``--no-imflag-curve-restart``; ON by default since h.3) is the single
    implicit file of 4f5b6e8."""

    def test_segments_through_the_restart_rule(self):
        from k2rad.writer.assembly import imflag_restart_segments
        st = _dispatch(_ie_strip_deck())
        st.options.imflag_curve_restart = False
        self.assertEqual(imflag_restart_segments(st), [])
        st.options.imflag_curve_restart = True
        segs = imflag_restart_segments(st)
        self.assertEqual([(s.run, s.t_stop, s.implicit, s.last,
                           s.first_implicit) for s in segs],
                         [(1, 0.01, True, False, True),
                          (2, 0.025, False, True, False)])

    def test_two_files_under_the_flag(self):
        res, s_on, eng, names = _convert_files(_ie_strip_deck(),
                                               imflag_curve_restart=True)
        _r0, s_off, eng_off, names_off = _convert_files(
            _ie_strip_deck(), imflag_curve_restart=False)
        self.assertEqual(names, ["deck_0001.rad", "deck_0002.rad"])
        self.assertEqual(names_off, ["deck_0001.rad"])
        self.assertEqual(s_on, s_off)
        f1, f2 = (e.splitlines() for e in eng)
        self.assertEqual(f1[:2], ["/RUN/ie_strip/1", "0.01"])
        self.assertNotIn("/RFILE/OFF", f1)
        self.assertIn("/IMPL/NONLIN/1", f1)
        self.assertEqual(f1[f1.index("/IMPL/DTINI") + 1].strip(), "0.0005")
        self.assertEqual(f2[:2], ["/RUN/ie_strip/2", "0.025"])
        self.assertIn("/RFILE/OFF", f2)
        self.assertFalse([ln for ln in f2 if ln.startswith("/IMPL")])
        self.assertEqual((_sha(eng[0]), _sha(eng[1])), _IE_STRIP_PINS)
        # the flag-off file is the single implicit one, ENDTIM and all
        self.assertEqual(eng_off[0].splitlines()[:4],
                         ["/RUN/ie_strip/1", "0.025", "#", "/RFILE/OFF"])

    def test_explicit_first_curve(self):
        pts = ((0.0, 0.0), (0.00999, 0.0), (0.01, 1.0), (1.0, 1.0))
        _r, _s, eng, _n = _convert_files(_ie_strip_deck(pts, timestep=True),
                                         imflag_curve_restart=True)
        f1, f2 = eng
        self.assertNotIn("/IMPL", f1)
        self.assertNotIn("/RFILE/OFF", f1)
        self.assertIn("/DT/NODA/CST/0", f1)
        self.assertIn("/IMPL/NONLIN/1", f2)
        self.assertIn("/RFILE/OFF", f2)
        self.assertNotIn("/DT/NODA/CST", f2)

    def test_three_segments(self):
        pts = ((0.0, 1.0), (0.00499, 1.0), (0.005, 0.0), (0.00999, 0.0),
               (0.01, 1.0), (1.0, 1.0))
        res, _s, eng, names = _convert_files(_ie_strip_deck(pts),
                                             imflag_curve_restart=True)
        self.assertEqual(len(eng), 3)
        self.assertEqual(["/RFILE/OFF" in e for e in eng],
                         [False, False, True])
        self.assertEqual(["/IMPL/NONLIN" in e for e in eng],
                         [True, False, True])
        self.assertEqual([e.splitlines()[1] for e in eng],
                         ["0.005", "0.01", "0.025"])
        # the per-deck warnings print once, not once per file
        self.assertEqual(len(res.warnings), len(set(res.warnings)))
        hits = [w for w in res.warnings if "IAUTO" in w]
        self.assertLessEqual(len(hits), 1, hits)
        # two EXPLICIT segments build the /DT cards twice; the deck's
        # *CONTROL_TIMESTEP sentence still prints once (mutation target:
        # the de-duplication in build_engines)
        pts2 = ((0.0, 0.0), (0.00499, 0.0), (0.005, 1.0), (0.00999, 1.0),
                (0.01, 0.0), (1.0, 0.0))
        r2, _s2, eng2, _n2 = _convert_files(_ie_strip_deck(pts2,
                                                           timestep=True),
                                            imflag_curve_restart=True)
        self.assertEqual(["/DT/NODA/CST/0" in e for e in eng2],
                         [True, False, True])
        self.assertEqual(len(r2.warnings), len(set(r2.warnings)),
                         r2.warnings)

    def test_sfa_scales_the_boundary(self):
        """The curve's points are scaled at parse time (SFA 2: the switch at
        0.01 becomes 0.02)."""
        from k2rad.writer.assembly import imflag_restart_segments
        st = _dispatch(_ie_strip_deck(sfa=2.0))
        st.options.imflag_curve_restart = True
        self.assertEqual([(s.t_stop, s.implicit)
                          for s in imflag_restart_segments(st)],
                         [(0.02, True), (0.025, False)])

    def test_one_segment_is_todays_file(self):
        cases = (("constant 1", ((0.0, 1.0), (1.0, 1.0))),
                 ("switch at ENDTIM", ((0.0, 1.0), (0.025, 0.0))),
                 ("constant 0", ((0.0, 0.0), (1.0, 0.0))))
        for name, pts in cases:
            with self.subTest(case=name):
                deck = _ie_strip_deck(pts)
                r_on, s_on, e_on, n_on = _convert_files(
                    deck, imflag_curve_restart=True)
                _r, s_off, e_off, _n = _convert_files(
                    deck, imflag_curve_restart=False)
                self.assertEqual(n_on, ["deck_0001.rad"])
                self.assertEqual((s_on, e_on), (s_off, e_off))
                if name == "constant 0":
                    self.assertTrue(_has(r_on.warnings, "state IMFLAG 0"))

    def test_flag_off_is_byte_identical(self):
        root = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(root, "fixtures", "implicit_qstat.k")) as fh:
            qstat = fh.read()
        for name, deck in (("implicit_qstat", qstat),
                           ("IMFLAG 4", _ie_strip_deck(imflag=4))):
            with self.subTest(deck=name):
                _r1, s1, e1, n1 = _convert_files(deck,
                                                 imflag_curve_restart=True)
                _r0, s0, e0, n0 = _convert_files(
                    deck, imflag_curve_restart=False)
                self.assertEqual((s1, e1, n1), (s0, e0, n0))
                self.assertEqual(len(n1), 1)

    def test_the_warning_names_the_order_and_the_unmeasured_branches(self):
        res, _s, _e, _n = _convert_files(_ie_strip_deck(),
                                         imflag_curve_restart=True)
        hits = [w for w in res.warnings if "IMFLAG=-9" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("_0001.rad (implicit to 0.01, restart written)",
                       "_0002.rad (explicit to 0.025)", "run k restarts",
                       "IN ORDER", "implicit DYNAMIC segment after an "
                       "explicit one", "KE 316.1 -> 0", "more than two engine files",
                       "18 + 11 127 cycles", "-4.54 %", "12.07 / 12.04 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("IMPLICIT THROUGHOUT", hits[0])
        r0, _s0, _e0, _n0 = _convert_files(_ie_strip_deck(),
                                           imflag_curve_restart=False)
        hits0 = [w for w in r0.warnings if "IMFLAG=-9" in w]
        self.assertEqual(len(hits0), 1, r0.warnings)
        self.assertIn("IMPLICIT THROUGHOUT", hits0[0])
        self.assertIn("--imflag-curve-restart writes one engine file per "
                      "segment", hits0[0])

    def test_write_restart_keeps_every_rst(self):
        _r, _s, eng, _n = _convert_files(_ie_strip_deck(),
                                         imflag_curve_restart=True,
                                         write_restart=True)
        self.assertEqual(len(eng), 2)
        self.assertFalse(any("/RFILE/OFF" in e for e in eng))

    def test_conversion_log_and_cli_list_every_file(self):
        import contextlib
        import io
        import tempfile
        from k2rad import cli
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "strip.k")
        with open(path, "w") as fh:
            fh.write(_ie_strip_deck())
        res = convert(path, imflag_curve_restart=True)
        with open(res.log_path, encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("_0000.rad / strip_0001.rad / strip_0002.rad", log)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main([path, "--imflag-curve-restart"])
        printed = buf.getvalue()
        self.assertEqual(printed.count("  Engine  -> "), 2, printed)
        self.assertIn("Run the engine files IN ORDER", printed)

    def test_default_writes_the_chain(self):
        """h.3 (round 8): ON by default - no kwarg, two engine files,
        the same bytes as the explicit opt-in."""
        _r, _s, eng, names = _convert_files(_ie_strip_deck())
        self.assertEqual(names, ["deck_0001.rad", "deck_0002.rad"])
        self.assertEqual((_sha(eng[0]), _sha(eng[1])), _IE_STRIP_PINS)

    def test_build_engine_direct_caller_unchanged(self):
        from k2rad.writer.assembly import build_engine, build_starter
        for flag in (False, True):
            with self.subTest(flag=flag):
                st = _dispatch(_ie_strip_deck())
                st.options.imflag_curve_restart = flag
                build_starter(st)
                text = build_engine(st)
                self.assertEqual(text.splitlines()[:4],
                                 ["/RUN/ie_strip/1", "0.025", "#",
                                  "/RFILE/OFF"])
                self.assertIn("/IMPL/NONLIN/1", text)


# ─────────────────────────────────────────────────────────────────────────────
# Part B's flags at every wiring site
# ─────────────────────────────────────────────────────────────────────────────


class Round8OptInWiringB(unittest.TestCase):
    """B12.1: every round-8 part-B OPT-IN lever (default OFF) reaches the
    parser (with its --no- twin), the README prose (its POSITIVE spelling),
    the --help render with its measured figures, the GUI end to end,
    convert() / ConvertOptions (default False) and cli.main()'s call."""

    _OPT_IN = {
        "--skip-implicit-stub-with-type25": "skip_implicit_stub_with_type25",
        "--shell-in-solid-coupling": "shell_in_solid_coupling",
    }
    _HELP_FIGURES = {
        "--skip-implicit-stub-with-type25": ("+582.00 -> +689.08 %",
                                             "393.31 -> 313.05 %",
                                             "imp_int_k.F:847",
                                             "ERROR TERMINATION at cycle 9"),
        "--shell-in-solid-coupling": ("0.1 K A^2 / V", "-100 -> -28.26 %",
                                      "+1134.62 -> +42.28 %", "8.936x"),
    }

    def _readme(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_every_flag_is_a_parser_option_with_its_no_twin(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        for flag in self._OPT_IN:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts)
                self.assertIn("--no-" + flag[2:], opts)

    def test_every_positive_spelling_is_in_README_prose(self):
        readme = self._readme()
        body = [ln for ln in readme.splitlines()
                if not re.match(r"^\s*[-*]?\s*\[.*\]\(#.*\)\s*$", ln)]
        for flag in self._OPT_IN:
            with self.subTest(flag=flag):
                self.assertTrue(any(flag in ln for ln in body),
                                f"{flag} is not in README.md prose")

    def test_every_opt_in_has_its_OWN_README_SECTION_and_its_links_resolve(self):
        """The round-5 rule: a ``### `--flag``` heading of its own (a renamed
        heading leaves a presence check green), and every in-README link to
        an opt-in section resolves to a heading that exists."""
        readme = self._readme()
        headings = re.findall(r"^#{2,4}\s+(.*)$", readme, re.M)
        anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip()
                   .replace(" ", "-") for h in headings}
        for flag in self._OPT_IN:
            with self.subTest(flag=flag):
                self.assertTrue(any(h.startswith(f"`{flag}`")
                                    for h in headings), flag)
                for link in re.findall(r"\]\(#(" + re.escape(flag) + r"[^)]*)\)",
                                       readme):
                    self.assertIn(link, anchors)

    def test_the_help_renders_and_carries_the_measured_numbers(self):
        from k2rad import cli
        flat = _t7._collapse(cli.build_parser().format_help())
        for flag, figures in self._HELP_FIGURES.items():
            for figure in figures:
                with self.subTest(flag=flag, figure=figure):
                    self.assertIn(figure, flat)

    def test_convert_and_ConvertOptions_default_off(self):
        import inspect
        from k2rad import convert
        from k2rad.state import ConvertOptions
        sig = inspect.signature(convert).parameters
        for name in self._OPT_IN.values():
            with self.subTest(name=name):
                self.assertIs(sig[name].default, False)
                self.assertIs(getattr(ConvertOptions(), name), False)

    def test_the_gui_wires_every_lever_end_to_end(self):
        import tempfile
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for flag, name in self._OPT_IN.items():
            with self.subTest(name=name):
                kw = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="",
                    **{name: True})
                self.assertIs(kw[name], True)
                captured = []
                app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
                app._append = captured.append
                k2rad_gui.ConverterGUI._describe_options(app, kw)
                self.assertIn(flag, "".join(captured))
                kw_off = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="")
                self.assertIs(kw_off[name], False)
                captured_off = []
                app._append = captured_off.append
                k2rad_gui.ConverterGUI._describe_options(app, kw_off)
                self.assertNotIn(flag, "".join(captured_off))
        tmp.cleanup()

    def test_the_cli_passes_the_flag_through(self):
        import tempfile
        from k2rad import cli
        import k2rad
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for flag, name in self._OPT_IN.items():
            for argv, want in (([path, flag], True), ([path], False),
                               ([path, "--no-" + flag[2:]], False)):
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


class Round8FlagWiringB(_t7.Round7FlagWiringA):
    """B12.1: every round-8 part-B DEFAULT-ON lever reaches the parser (with
    its --no- twin), the README prose, the --help render with its measured
    figures, the GUI end to end, convert() / ConvertOptions (default True)
    and cli.main()'s call - the round-7 checks, for this half's flags."""

    _FLAGS = {
        "--imflag0-eigen-explicit": "imflag0_eigen_explicit",
        "--implicit-smooth-curve-sampling": "implicit_smooth_curve_sampling",
        "--elastic-fluid-cp-cutoff": "elastic_fluid_cp_cutoff",
        # h.3 (round 8): ON by default
        "--imflag-curve-restart": "imflag_curve_restart",
    }
    _HELP_FIGURES = {
        "--elastic-fluid-cp-cutoff": ("0.00000E+00", "hm_read_mat06.F:154",
                                      "18 rows"),
        "--imflag-curve-restart": ("freimpl.F:82", "18 + 11 127 cycles",
                                   "-99.87 -> -4.54 %",
                                   "58.96 / 58.79 -> 12.07 / 12.04 %"),
        "--imflag0-eigen-explicit": ("24329 cycles", "+3.93 %", "-18.30 %",
                                     "2.06 / 2.23 %",
                                     "tire.d3hsp:1056-1057"),
        "--implicit-smooth-curve-sampling": ("13 of 13", "7 of 7",
                                             "202 cycles", "fv_imp0.F:209"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# B12 — the round-8 record (ROADMAP, CHANGELOG) and part B's retracted
# spellings
# ═════════════════════════════════════════════════════════════════════════════

_read7 = _t7._read7
_md_cells = _t7._md_cells
_collapse = _t7._collapse
_SHIPPED_TEXTS = _t7._SHIPPED_TEXTS


class Round8RoadmapRecord(unittest.TestCase):
    """B12.3 / B12.5: the ROADMAP record of round 8 - a round-8 column in the
    queue table and in the implicit residue table (every row as wide as its
    header), the `efg/metal-cutting` residue row, the residue restated, ONE
    ``**Round 8:**`` line on each round-7 NOT item 1-22, the round-8 NOT list
    numbered 1-26 with no placeholder, and the closes paragraph's ledger
    marked EXPECTED (the campaign validator re-sums it)."""

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

    def test_the_queue_table_has_a_round_8_column(self):
        rows = self._table("| # | class | decks | closed by round 1 |")
        self.assertTrue(rows[0].endswith("| round 7 | round 8 |"), rows[0])
        self.assertEqual(len(rows), 10)
        self._same_width(rows)

    def test_the_residue_table_has_a_round_8_column_and_its_rows(self):
        rows = self._table("| family | decks | death | verdict after round 3 |")
        self.assertTrue(rows[0].endswith("| round 7 | round 8 |"), rows[0])
        self.assertEqual(len(rows), 19)
        self._same_width(rows)
        mc = [r for r in rows if r.startswith("| `efg/metal-cutting`")]
        self.assertEqual(len(mc), 1)
        tire = [r for r in rows if r.startswith("| `eigenvalue/tire.k`")]
        self.assertEqual(len(tire), 1)
        last = tire[0].rstrip(" |").rsplit("|", 1)[1]
        self.assertIn("explicit route", last)
        self.assertIn("24329", last)
        text = _collapse("\n".join(self.lines))
        self.assertIn("**27 keys / 27 models**", text)
        self.assertIn("134 / 107", text)

    def test_every_round_7_item_carries_one_round_8_line(self):
        s = self._at("**What round 7 deliberately does NOT close**")
        e = self._at("**What round 8 closes, and what it does NOT.**")
        starts = [k for k in range(s, e)
                  if re.match(r"^\d+\. \*\*", self.lines[k])]
        self.assertEqual(len(starts), 22)
        for n, (a, b) in enumerate(zip(starts, starts[1:] + [e]), 1):
            with self.subTest(item=n):
                self.assertTrue(self.lines[a].startswith(f"{n}. **"))
                self.assertEqual(
                    sum("**Round 8:**" in ln for ln in self.lines[a:b]), 1)

    def test_the_round_8_not_list_is_numbered_1_to_26(self):
        s = self._at("**What round 8 deliberately does NOT close**")
        e = self._at("**52 of the 59 starter failures.**")
        nums = [int(m.group(1)) for m in
                (re.match(r"^(\d+)\. \*\*", ln) for ln in self.lines[s:e])
                if m]
        self.assertEqual(nums, list(range(1, 27)))
        self.assertNotRegex("\n".join(self.lines[s:e]), r"<[a-z_ ]+>")

    def test_the_closes_paragraph_states_an_EXPECTED_ledger(self):
        s = self._at("**What round 8 closes, and what it does NOT.**")
        e = self._at("**What round 8 deliberately does NOT close**")
        para = _collapse("\n".join(self.lines[s:e]))
        self.assertIn("EXPECTATION", para)
        self.assertIn("normal 291 → 293", para)
        self.assertIn("8 deck keys on 8 emitted models", para)


class Round8ChangelogReSums(unittest.TestCase):
    """B12.2: the "re-add every headline total" rule - part B's header
    bullet's byte-mover count re-sums from its per-item counts, and every
    per-item bullet states the same count."""

    def _text(self) -> str:
        return _collapse(_read7("CHANGELOG.md"))

    def test_the_part_B_total_re_sums(self):
        # B6 left the list when the validation round inverted its default
        # (the stub stays; 8 / 8 -> 7 / 7)
        m = re.search(
            r"Part B's default bytes move (\d+) deck keys / (\d+) emitted "
            r"models \(B1 (\d+) / (\d+), B2 (\d+) / (\d+), B4 (\d+) / (\d+), "
            r"B5 (\d+) / (\d+); B3 h\.2, B6, B7, B8, B9 and B10 0 ",
            self._text())
        self.assertIsNotNone(m)
        tot_k, tot_m, *items = map(int, m.groups())
        self.assertEqual((sum(items[0::2]), sum(items[1::2])),
                         (tot_k, tot_m))
        self.assertEqual((tot_k, tot_m), (7, 7))

    def test_the_item_bullets_state_the_same_counts(self):
        text = self._text()
        for needle in (
                # B1 tire.k, B2 metal-cutting; B6 0 by default, its opt-in
                # doorbeam
                "Reach 1 deck key on 1 emitted model; the",
                "Reach 1 deck key on 1 emitted model (0 explicit carriers)",
                "Default bytes: 0 movers (doorbeam's `_0000.rad` = the "
                "4f5b6e8 deck",
                "Reach of the opt-in 1 deck key on 1 emitted model (the only "
                "stub carrier",
                # B4 sph/bird, B5 the four nvh keys
                "bytes 1 deck key on 1 emitted model (`sph/bird`, one cell)",
                "`nvh` 8.7 / 9.1 / 9.2 / 9.4, 4 deck keys on",
                # B7, B8, B10 and h.2 move no default byte
                "Reach 0 deck keys on 0 emitted models (every implicit "
                "thick-shell carrier",
                "Reach: 0 byte movers; EXP_SC_JOINT_SCREW SHA-identical",
                "bytes: 0 movers (bird-el SHA-identical",
                "Default bytes: 0 movers (ie_shell SHA-identical"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_h3_bullet_states_its_count(self):
        """h.3 (the gated default flip) moves exactly `ie_shell`, and the
        header announces that it adds 1 / 1 outside the re-summed 8 / 8."""
        text = self._text()
        for needle in (
                "Default bytes: 1 deck key on 1 emitted model (`ie_shell`",
                "the h.3 default flip, its own last commit, adds "
                "`ie_shell` 1 / 1 if it is kept"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


#: Part B statements a round-8 measurement made false (B12.6). CHANGELOG may
#: quote them (it is the history); no other shipped text may.
_RETRACTED_ROUND_8_B = (
    # B2 - the A5 placeholder sentence (91.2 % is one run of seven)
    "energy error of 91.2 %", "ERR 91.2 %", "a flat internal energy",
    "a flat mid-run IE", "That row has no LS-DYNA reference",
    "on 3 of 3 runs but with an energy error",
    # B4 - the no-PC-cell pair, the pre-PC-cell sph/bird arm, the mechanism
    "10.3 -> 29.6", "10.3 → 29.6", "IE 10.3 ", "1942 -> 1917", "1942 → 1917",
    "IE RMS 44.37 % on both arms", "mechanism not found",
    "ROADMAP: the bird_B mechanism first", "+ sph/boot",
    # B5 - the CP 0.0 mapping
    "this card's mapping is not changed yet", "is still written `Pmin = 0`",
    # B7 - (f') and the LAW1-only route
    "stiffer through the thickness", "-78.88", "−78.88", "-2.63 %", "−2.63 %",
    "HA8, locking-free full integration", "applied to *MAT_ELASTIC only",
    "so the route is never widened past LAW1",
    # B8 - the screw's round-7 open points
    "a screw without a drive is unmeasured", "a conflicting code is unmeasured",
    "the next step is to fold a redundant code",
    # B9 - the /MPC notes
    "not characterised", "uncharacterised", "uncharacterized",
    "Spotflag 27 held on that", "Spotflag-28 mechanism is not",
    # B10 - round 7's SIS arms
    "refuted as a general rule in round 6", "+195.21 %", "1.016x", "1.016×",
    "4.506x", "4.506×",
    # B6 - the first default (the stub skipped) and its opt-in flag, both
    # gone when the validation round inverted the default
    "--implicit-stub-with-type25", "carries NO /INTER",
    "the stub is NOT injected when the deck's only",
)

#: ... and their replacements, which ARE shipped: (file, text).
_REPLACEMENTS_ROUND_8_B = (
    ("k2rad/writer/contacts.py", "is KEPT"),
    ("README.md", "`--skip-implicit-stub-with-type25` — skip the implicit"),
    ("k2rad/writer/mesh.py", "13 of 13"),
    ("k2rad/writer/materials.py", "29.58"),
    ("k2rad/writer/materials.py", "-1e-20"),
    ("k2rad/writer/tshell.py", "distortion"),
    ("k2rad/writer/joint_screw.py", "has NO drive: converted without"),
    ("k2rad/writer/loads.py", "READ from the code order"),
    ("k2rad/writer/blast_ale.py", "2812.5 on this deck"),
    ("ROADMAP.md", "**Characterised in round 8**"),
    ("README.md", "`--shell-in-solid-coupling` — the embedded shells"),
)


class NodalMassMemoIsPerState(unittest.TestCase):
    """The --mass-weighted-inivel lumped masses are memoised ON the state:
    the old module dict keyed by id(state) returned a freed state's masses
    to a new state (CPython reuses ids; 53 of 150 alternating conversions
    wrote the other deck's /INIVEL/TRA)."""

    def test_the_memo_lives_on_the_state(self):
        from k2rad.writer import loads
        self.assertFalse(hasattr(loads, "_NODAL_MASS_CACHE"))
        st = _dispatch(_plates(_emass(9, 1.0e-4)))
        self.assertIsNone(st.lumped_nodal_masses_memo)
        got = loads._lumped_nodal_masses(st)
        self.assertIs(st.lumped_nodal_masses_memo, got)
        self.assertIs(loads._lumped_nodal_masses(st), got)

    def test_alternating_conversions_keep_their_own_masses(self):
        mc = 1.9625e-7
        v_cm = mc * 1000.0 / (3.14e-6 + 1.0e-4)
        deck_y = _plates(_emass(9, 1.0e-4) + _IV_PROBE)
        deck_x = _plates(_emass(9, 5.0e-4) + _IV_PROBE)
        for i in range(30):
            _convert(deck_x, mass_weighted_inivel=True)
            _r, starter, _e = _convert(deck_y, mass_weighted_inivel=True)
            tra, _rot = _inivel_mw(starter)
            self.assertAlmostEqual(tra[0] / v_cm, 1.0, places=6,
                                   msg=f"iteration {i}")


class Round8RetractedStatementsB(unittest.TestCase):
    """B12.6, the round-7 four-test shape: no retracted spelling in any
    shipped text; the guard fires on a spelling split across adjacent
    literals; the replacements ARE shipped; CHANGELOG still quotes each old
    spelling that ever shipped, as its history."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_8_B:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_8_B:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "')
                        + ' y')
                self.assertIn(_collapse(needle).lower(), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_the_replacements_really_are_shipped(self):
        texts = {k.replace("\\", "/"): v for k, v in _SHIPPED_TEXTS()}
        for rel, needle in _REPLACEMENTS_ROUND_8_B:
            with self.subTest(file=rel, needle=needle):
                self.assertIn(_collapse(needle), texts[rel])

    def test_the_changelog_keeps_the_history(self):
        text = _collapse(_read7("CHANGELOG.md"))
        for needle in ("91.2 %", "10.3 → 29.6", "+195.21 %", "1.016×",
                       "4.506×", "refuted as a general rule in round 6",
                       "not characterised"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
