"""Tests for the R14 CAMPAIGN TRIAGE batch, round 8 — PART A:

  A1  *MAT_RIGID CMO -1 -> /BCS in the /SKEW of CON1, one skew per node
      (default ON, --no-rigid-local-constraints)
  A3  the non-rigid double /BCS union: P1 BC_n + BC_n, P2 BC_n + the
      free-node guard, P3 the guard + *NODE TC/RC (default ON, --no-bcs-union)

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_7.py (functions only,
so no round-7 TestCase runs twice).

Every byte-pinning probe deck below was run through the OpenRadioss starter
once (nt 4, C:/Users/pmqua/rcv_r8i_implA_<name>, harvested and deleted); the
named outcome is recorded in the test's docstring.
"""

import hashlib
import unittest

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
}
_PR8_WARN_SHA = {
    "a": "02c3df87ca83a12d9f437789ad15ab19a028efd5cb0d22e4617e5cfbb385a325",
    "d": "575a7470039d51c90a8786c87752ccfcc607f7ab59916377555dd9a42a1fee64",
    "e": "02c3df87ca83a12d9f437789ad15ab19a028efd5cb0d22e4617e5cfbb385a325",
    "j": "2e5113acdacb3e65d25737a27722e6b42670d61fa0bad24c1483c8ef51059258",
    "o": "cbee9879c41b3e6d9c1c3664ee4c4f17406477c9b2e2a27f4a02a31ba1dcc09a",
}


if __name__ == "__main__":
    unittest.main()
