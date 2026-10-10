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
import re
import unittest

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
        # the deck's own two-skew clash, as on a3_3.
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
    sqrt(I / (max K4..6 + max K2,3 L^2))) (r2len3.F:226-246, STI = XM/DT^2 at
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
                             "Mass x 2.5, Inertia x 13.41", "r2len3.F:226-246",
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
        self.assertEqual(_sha("\n".join(res.warnings)), _PR8_WARN_SHA["a5_d2"])
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
        "--spotweld-dt-mass-scaling": ("r2len3.F:226-246", ":233",
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


if __name__ == "__main__":
    unittest.main()
