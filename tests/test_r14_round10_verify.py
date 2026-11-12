"""R14 round 10 - the verification round of PR #148 (findings 6.29 - 6.32 and
the code verifier's surviving mutations).

1. Seventeen surviving mutations of the round's own code, each killed by a
   test at the class boundary it attacked (the code is right at bc2910c; the
   tests were missing).
2. The verification round's own code: the eroding /INTER/TYPE25 route's B6
   scope (the parts of the surface it WRITES) and its SURFATYP 6 / 7 drop
   text; the per-deck sentence of the shell routes the SHRF rule does not
   reach (/PROP/TYPE9 / TYPE11 / TYPE51); the conditional-TSSFAC sentence on
   a routed 2-D deck (silent at 1.00x) and under --dt-del.
3. The corrected texts (A7's mass balance, A8's force definitions, the N2S
   caution's bytes, the A5 sliver range, the transducer, the damping help,
   the A2 / S-excl / initial-state wordings) and the retraction guard over
   hyphen- and whitespace-collapsed, case-folded text.

Every test here fails on bc2910c (or on the named mutant of it).
"""

import math
import os
import re
import statistics
import unittest

import test_cardstack_pipeline as _C
import test_cardstack_pipeline_engine as _E
import test_cardstack_pipeline_props as _tp
import test_composites as _tc
import test_preload_inistate as _P
import test_r14_round10 as _r10
import test_r14_triage_7 as _t7

_row = _t7._row
_convert = _t7._convert
_has = _t7._has
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _norm(text: str) -> str:
    """Case-folded, adjacent string literals joined, every hyphen a space and
    every whitespace run one space: the form a retracted claim is matched in
    (findings 6.31 (2)(a))."""
    text = re.sub(r'"\s*\n\s*"', "", text)
    return re.sub(r"\s+", " ", text.replace("-", " ")).lower()


def _help() -> str:
    from k2rad.cli import build_parser
    return _t7._collapse(build_parser().format_help())


# ═════════════════════════════════════════════════════════════════════════════
# 1. The seventeen surviving mutations
# ═════════════════════════════════════════════════════════════════════════════

class A8PenaltyIsTheMedian(unittest.TestCase):
    """O_a8_mean: _ls_shell_penalty takes the MEDIAN of the per-segment K A /
    max diagonal (LS-DYNA Theory eq. 30.8); the A8 coupon had four equal
    quads (median = mean). Here the blank's fourth quad is stretched (node 9
    to x = 4): three segments 57500 / sqrt(2), one 57500 x 2 / sqrt(10)."""

    def test_a_stretched_blank_takes_the_median(self):
        deck = _r10._a8_deck()
        old = f"{9:8d}{2.0:16.1f}{2.0:16.1f}{0.0:16.1f}\n"
        self.assertEqual(deck.count(old), 1)
        deck = deck.replace(old, f"{9:8d}{4.0:16.1f}{2.0:16.1f}{0.0:16.1f}\n")
        _res, st, _e = _convert(deck)
        k = 69000.0 / (3.0 * (1.0 - 2.0 * 0.3))
        segs = [k * 1.0 / math.sqrt(2.0)] * 3 + [k * 2.0 / math.sqrt(10.0)]
        median, mean = statistics.median(segs), sum(segs) / len(segs)
        self.assertGreater(abs(median - mean) / median, 0.02)
        _stmin, stmax = _r10._type7_card3(st)
        # SLSFAC blank = 0.1; the blank is the softer side (the 3 x 3 tool's
        # K A / d is 121976)
        self.assertAlmostEqual(stmax, 2.0 * 0.1 * median, delta=1e-3 * stmax)
        self.assertGreater(abs(stmax - 2.0 * 0.1 * mean), 0.01 * stmax)


class B2RepresentativeInterface(unittest.TestCase):
    """O_b2_site_everypart: _select_parent_interface prefers the all-parts
    single surface through writer/common.single_surface_scope - a SURFATYP 5
    card with a stated SSID is that card, not the part-set one before it."""

    def _deck(self):
        ft = ("*CONTACT_FORCE_TRANSDUCER_PENALTY_ID\n" + _row(31) + "\n"
              + _row(1, 0, 2, 0) + "\n" + _row(0.0) + "\n" + _row(0.0) + "\n")
        return _C._k1a_deck(_C._k1a_ass(21, 1, 2) + _C._k1a_ass(22, 7, 5)
                            + ft)

    def test_the_surfatyp_5_card_is_the_representative(self):
        from k2rad.writer import contacts
        st = _t7._dispatch(self._deck())
        self.assertEqual(contacts._select_parent_interface(st), 22)

    def test_the_th_inter_lists_it(self):
        _res, st, _e = _convert(self._deck())
        lines = st.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/TH/INTER/"))
        rows = []
        for ln in lines[i + 1:]:
            if ln.startswith("/"):
                break
            if not ln.startswith("#"):
                rows.append(ln)
        ids = {int(t) for ln in rows[1:] for t in ln.split()
               if t.isdigit()}
        self.assertIn(22, ids)
        self.assertNotIn(21, ids)


class A5ClampedFixpointCount(unittest.TestCase):
    """O_a5_clamp: the end fix point keys on the CLAMPED --fixpoint-count
    (findings 6.17 D16): a negative count is clamped to 0 and gets it."""

    def test_a_negative_count_gets_the_end_fix_point(self):
        res, _st, eng = _convert(_r10._hex_block(), fixpoint_count=-3)
        lines = eng.splitlines()
        self.assertIn("/IMPL/DT/FIXPOINT", lines)
        k = lines.index("/IMPL/DT/FIXPOINT")
        self.assertAlmostEqual(float(lines[k + 1]), 0.02)
        self.assertTrue(_has(res.warnings, "/IMPL/DT/FIXPOINT 0.02 (the end "
                             "fix point"), res.warnings)


class A6RefusalsByName(unittest.TestCase):
    """O_a6_partmass_ok / O_a6_valdmp_ok: under --implicit-rayleigh-damping a
    uniform *DAMPING_GLOBAL beside a part-scoped card, and a VALDMP < 0, are
    refused by name and write no /IMPL/DYNA/DAMP (VALDMP 0 writes no /DAMP at
    all, so < 0 is the reachable case)."""

    _GLOBAL = ("*DAMPING_GLOBAL\n"
               + _row(0, 11.535, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")

    def test_a_part_scoped_card_refuses_the_global_alpha(self):
        damping = (self._GLOBAL + "*DAMPING_PART_MASS\n" + _row(1, 7, 1.0, 0)
                   + "\n*DEFINE_CURVE\n" + _row(7) + "\n"
                   + f"{0.0:>20}{5.0:>20}\n{1.0:>20}{5.0:>20}\n")
        res, _st, eng = _convert(_r10._hex_block(damping=damping),
                                 implicit_rayleigh_damping=True)
        self.assertNotIn("/IMPL/DYNA/DAMP", eng.splitlines())
        self.assertTrue(_has(res.warnings, "part-scoped"), res.warnings)
        # the control: the global card alone is written
        _r, _s, eng0 = _convert(_r10._hex_block(damping=self._GLOBAL),
                                implicit_rayleigh_damping=True)
        self.assertIn("/IMPL/DYNA/DAMP", eng0.splitlines())

    def test_a_negative_valdmp_is_refused(self):
        damping = ("*DAMPING_GLOBAL\n"
                   + _row(0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        res, _st, eng = _convert(_r10._hex_block(damping=damping),
                                 implicit_rayleigh_damping=True)
        self.assertNotIn("/IMPL/DYNA/DAMP", eng.splitlines())
        self.assertTrue(_has(res.warnings, "VALDMP"), res.warnings)


class A7LightFluidPminFallback(unittest.TestCase):
    """O_a7_pmin: the light fluid's Pmin is the fluid's resolved Pmin or, when
    that is 0 (--no-mat-null-pc-mu leaves a stated PC 0 as 0), -1e-20 - a 0
    would be -INFINITY on /MAT/LAW6 (hm_read_mat06.F:154)."""

    def test_the_fallback_under_no_mat_null_pc_mu(self):
        res, _st, _e = _convert(_r10._a7_coupon(), mat_null_pc_mu=False)
        lf = [w for w in res.warnings if w.startswith("*MAT_VACUUM 2 -> ")]
        self.assertEqual(len(lf), 1, res.warnings)
        self.assertIn("and Pmin -1e-20", lf[0])
        self.assertNotIn("and Pmin 0,", lf[0])


class B2SolidMainRegistry(unittest.TestCase):
    """O_b2_site_solidmain: the implicit np=1 SPMD safety warning reads the
    all-parts scope of a SURFATYP-5 card with a stated SSID."""

    def test_the_implicit_surfatyp_5_card_names_the_solid_part(self):
        res, _st, _e = _convert(_C._k1a_deck(_C._k1a_ass(22, 7, 5),
                                             implicit=True))
        self.assertTrue(_has(res.warnings, "Implicit deck with a solid-part "
                             "contact surface (parts [1])"), res.warnings)


class B2AutoGapminSentence(unittest.TestCase):
    """O_b2_site_gapmin: --auto-gapmin names a SURFATYP-5 card as the
    all-parts self-contact written as /INTER/TYPE25."""

    def test_the_surfatyp_5_card_is_named_as_all_parts(self):
        res, _st, _e = _convert(_C._k1a_deck(_C._k1a_ass(22, 7, 5)),
                                auto_gapmin=True)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 22: no "
                             "clearance suggestion — a SURFATYP 5 (SSID 7) "
                             "all-parts self-contact, written as "
                             "/INTER/TYPE25"), res.warnings)
        self.assertFalse(_has(res.warnings, "the /INTER/TYPE7 self-contact "
                              "of SSID 7"))


class B1SoftMinus11HasNoIgap2Clause(unittest.TestCase):
    """O_b1_igap2_m11: only SOFT -7 writes Igap 2; a self-mirrored SOFT -11
    K-12 card keeps the |SST| sentence without the Igap-2 clause."""

    def test_soft_minus_11(self):
        deck = _C._k1a_deck(_C._k1a_ass(
            31, 1, 2, card3=(0, 0, 0.35), kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_row(-11) + "\n"))
        res, _st, _e = _convert(deck)
        hits = [w for w in res.warnings if w.startswith("CONTACT 31: ")
                and "/INTER/TYPE11 Gapmin=0.35 = |SST|" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertNotIn("Igap 2", hits[0])


class B9StableSetMembersAreSilent(unittest.TestCase):
    """O_b9_drop_17 / O_b9_drop_14: Isolid 17 (ELFORM 1, the default bar) and
    Isolid 14 (ELFORM 10 on hexes) are in the measured /PRELOAD stable set
    {5, 14, 17} (writer/preload._PRELOAD_STABLE_ISOLID) and print no
    formulation warning."""

    def _isolid_warnings(self, res):
        return [w for w in res.warnings
                if "preloaded part(s)" in w and "emit /PROP/SOLID Isolid=" in w]

    def test_isolid_17_and_14_do_not_warn(self):
        base = _P._bar_deck()
        sec1 = "*SECTION_SOLID\n" + _row(1, 1) + "\n"
        self.assertEqual(base.count(sec1), 1)
        for elform, isolid in ((1, 17), (10, 14)):
            with self.subTest(elform=elform):
                deck = base.replace(sec1, "*SECTION_SOLID\n"
                                    + _row(1, elform) + "\n")
                res, st, _e = _convert(deck)
                self.assertIn("/PRELOAD/", st)
                rows = _tp._prop_rows(st, "/PROP/SOLID/1")
                self.assertEqual(int(rows[0][0:10]), isolid, rows)
                self.assertEqual(self._isolid_warnings(res), [])


class A9NearDefaultSlsfac(unittest.TestCase):
    """O_a9_window: only 0 and 0.1 (to 1e-12) are LS-DYNA's default; a
    near-default SLSFAC 0.10005 is named."""

    def test_0_10005_is_named(self):
        res, _st, _e = _convert(_r10._a9_deck("0.10005"))
        notes = _r10._a9_notes(res)
        self.assertEqual(len(notes), 1, res.warnings)
        self.assertTrue(notes[0].startswith(
            "*CONTROL_CONTACT SLSFAC = 0.10005"), notes[0])


class ConditionalTssfacBoundaries(unittest.TestCase):
    """The fix round's conditional-TSSFAC code at its class boundaries
    (O_ts_dyna_blank, O_ts_curve_tssfac, O_ts_ptr_any_class,
    O_ts_skipped_contact, O_ts_routed_orv)."""

    def test_a_blank_tssfac_under_dt2ms_negative_is_dyna2rads_product(self):
        """dyna2rad replaces a 0.0 TSSFAC (convertcards.cxx:166), so a BLANK
        one is the same product (the billet / cup-draw class)."""
        res, _s, _e = _convert(_r10._ts_deck("0.1", extra=_r10._TS_DT2MS))
        self.assertTrue(_has(res.warnings, "dyna2rad writes the same "
                             "product, convertcards.cxx:173-174"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, "dyna2rad keeps the negative "
                              "curve id"))

    def test_a_tssfac_curve_prints_no_default_sentence_and_no_pointer(self):
        curve = "*DEFINE_CURVE\n" + _row(3) + "\n0.0,0.6\n1.0,0.6\n"
        deck = _r10._ts_deck("10.0", extra="*CONTROL_TIMESTEP\n"
                             + _row(0.0, -3.0, 0, 0.0, 0.0) + "\n" + curve)
        res, _s, _e = _convert(deck)
        self.assertEqual(_r10._ts_notes(res), [])
        a9 = _r10._a9_notes(res)
        self.assertEqual(len(a9), 1, res.warnings)
        self.assertNotIn("SLSFAC also sets", a9[0])

    def test_the_slsfac_pointer_is_for_class_a_only(self):
        """Class b by *INITIAL_DETONATION with a non-default SLSFAC < 1: the
        TSSFAC sentence is the detonation's, the A9 sentence has no
        pointer."""
        res, _s, _e = _convert(_r10._ts_deck("0.5", extra=_r10._DET))
        notes = _r10._ts_notes(res)
        self.assertEqual(len(notes), 1, res.warnings)
        self.assertTrue(notes[0].startswith("*INITIAL_DETONATION sets"))
        a9 = _r10._a9_notes(res)
        self.assertEqual(len(a9), 1, res.warnings)
        self.assertNotIn("SLSFAC also sets", a9[0])

    def test_a_skipped_contact_keyword_counts_as_a_contact(self):
        res, _s, _e = _convert(_r10._ts_deck(
            "10.0", contact="*CONTACT_GUIDED_CABLE"))
        notes = _r10._ts_notes(res)
        self.assertEqual(len(notes), 1, res.warnings)
        for needle in ("TSSFAC = 0.333", "2.70x LS-DYNA's factor"):
            self.assertIn(needle, notes[0])

    def test_the_routed_2d_deck_at_1_00x_is_silent(self):
        """The routed 2-D deck steps at OpenRadioss's 2-D default 0.67
        (contrl.F:1148): against a class-b 0.667 that is 1.00x - nothing
        substituted, nothing named (the mutant orv = 0.9 named 1.35x)."""
        deck = _E._ax15(1.0e-4)
        self.assertEqual(deck.count("*END"), 1)
        res, st, _e = _convert(deck.replace("*END", _r10._DET + "*END"))
        self.assertTrue(any(ln.startswith("/QUAD") for ln in st.splitlines()),
                        "the deck is no longer routed to the 2-D /QUAD deck")
        self.assertEqual(_r10._ts_notes(res), [])
        # the same deck un-routed names the 3-D 0.9 (1.35x)
        res, st, _e = _convert(deck.replace("*END", _r10._DET + "*END"),
                               axisymmetric_2d=False)
        notes = _r10._ts_notes(res)
        self.assertEqual(len(notes), 1, res.warnings)
        self.assertIn("1.35x LS-DYNA's factor", notes[0])

    def test_under_dt_del_the_sentence_names_the_floor_card(self):
        """--dt-del writes /DT/{SHELL,SH_3N,BRICK}/DEL Tsca 0.9 for a blank
        TSSFAC: the sentence no longer says 'writes no /DT scale factor'."""
        res, _s, eng = _convert(_r10._ts_deck("10.0"), dt_del=1.0e-9)
        self.assertIn("/DT/SHELL/DEL", eng.splitlines())
        notes = _r10._ts_notes(res)
        self.assertEqual(len(notes), 1, res.warnings)
        self.assertIn("the /DT .../DEL card of the deletion floor (--dt-del "
                      "1e-09) carries Tsca 0.9", notes[0])
        self.assertNotIn("writes no /DT scale factor", notes[0])
        self.assertIn("2.70x LS-DYNA's factor", notes[0])

    def test_the_docstring_spells_2_70x(self):
        from k2rad.writer import assembly
        doc = assembly._warn_ls_default_tssfac.__doc__ or ""
        self.assertIn("1.35x - 2.70x", _t7._collapse(doc))
        self.assertNotIn("2.7x", doc)


# ═════════════════════════════════════════════════════════════════════════════
# 2. The eroding /INTER/TYPE25 route: B6 scope and the SURFATYP 6 / 7 drop
# ═════════════════════════════════════════════════════════════════════════════

class ErodingRouteScope(unittest.TestCase):
    """An *CONTACT_ERODING_SINGLE_SURFACE is a state.contacts_type25 record
    with its own SSID = 0 / SURFATYP 5 expansion (_type25_surface): its B6
    sentence names a LAW169 part of the surface it WRITES (a SURFATYP 5
    card over a stated SSID writes every part), and a SURFATYP 6 / 7 side
    is dropped with the type's meaning, not 'names no part or part set'.
    The bytes do not move (the 356-key sweep of the verification round)."""

    def _deck(self, ssid, sstyp, cid=12):
        base = _C._k1a_deck(_C._k1a_ass(
            cid, ssid, sstyp, kw="CONTACT_ERODING_SINGLE_SURFACE_ID",
            tail=_row(0, 1, 1) + "\n"), block_e=10.0)
        self.assertEqual(base.count(_C._SOFT_BLOCK_MAT), 1)
        return base.replace(_C._SOFT_BLOCK_MAT, _C._ADHESIVE_BLOCK_MAT)

    def test_surfatyp_5_names_the_law169_part_it_writes(self):
        res, st, _e = _convert(self._deck(1, 5))
        self.assertIn("/INTER/TYPE25/12", st)
        ws = _C._type25_law_lines(res)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("/INTER/TYPE25 12: part 1 (/MAT/LAW169", ws[0])

    def test_a_part_set_side_still_leaves_the_block_out(self):
        res, st, _e = _convert(self._deck(1, 2))
        self.assertIn("/INTER/TYPE25/12", st)
        self.assertEqual(_C._type25_law_lines(res), [])

    def test_surfatyp_6_and_7_are_dropped_by_their_meaning(self):
        for sstyp, needle in ((6, "SURFATYP 6 means 'Part set ID for "
                                  "exempted parts"),
                              (7, "SURFATYP 7 means 'Branch ID; see "
                                  "*SET_PART_TREE'")):
            with self.subTest(sstyp=sstyp):
                res, st, _e = _convert(self._deck(2, sstyp))
                self.assertNotIn("/INTER/TYPE25/12", st)
                drops = [w for w in res.warnings if "12" in w
                         and "eroding /INTER/TYPE25 route builds its "
                         "surface" in w]
                self.assertEqual(len(drops), 1, res.warnings)
                self.assertIn(needle, drops[0])
                self.assertNotIn("names no part or part set", drops[0])


# ═════════════════════════════════════════════════════════════════════════════
# 2b. The shell routes the SHRF rule does not reach
# ═════════════════════════════════════════════════════════════════════════════

def _route_lines(res):
    return [w for w in res.warnings
            if "a shell route the SHRF rule" in w]


class ShrfOtherRoutes(unittest.TestCase):
    """Findings 6.32 (2)(f): /PROP/TYPE9 (Ashear 0), /PROP/TYPE11 and the
    /PROP/TYPE51 of a layup (0.833333) run at the starter's 5/6
    (hm_read_prop09.F:266, hm_read_prop11.F:280, hm_read_prop51.F:255) where
    LS-DYNA runs the stated SHRF or its default 1.0. ONE sentence per deck;
    the cells do not move."""

    def test_type9_names_a_stated_1(self):
        deck = _tp._shell_deck(nip="5", mat=_tc._mat037(mid=1), shrf="1.0")
        res, st, _e = _convert(deck)
        self.assertIn("/PROP/TYPE9/", st)
        lines = _route_lines(res)
        self.assertEqual(len(lines), 1, res.warnings)
        for needle in ("*SECTION_SHELL 1 (SHRF 1) -> /PROP/TYPE9",
                       "hm_read_prop09.F:266", "Vol I R17 p.41-63",
                       "no byte moves here"):
            self.assertIn(needle, lines[0])

    def test_type9_silent_where_nothing_is_substituted(self):
        for shrf, nip in (("0.8333", "5"), ("1.0", "1")):
            with self.subTest(shrf=shrf, nip=nip):
                deck = _tp._shell_deck(nip=nip, mat=_tc._mat037(mid=1),
                                       shrf=shrf)
                res, st, _e = _convert(deck)
                self.assertIn("/PROP/TYPE9/", st)
                self.assertEqual(_route_lines(res), [])

    def test_a_part_composite_with_a_blank_shrf_is_named(self):
        def pc(shrf):
            deck = ("*KEYWORD\n" + _tc.NODES + _tc.SHELL
                    + _tc._part_composite(shrf=shrf) + _tc._mat002()
                    + _tc.END)
            return _convert(deck)
        res, st, _e = pc("")
        self.assertIn("/PROP/TYPE51/", st)
        lines = _route_lines(res)
        self.assertEqual(len(lines), 1, res.warnings)
        self.assertIn("*PART_COMPOSITE 7 (SHRF blank: LS-DYNA's 1.0) -> "
                      "/PROP/TYPE51", lines[0])
        # a stated 0 < SHRF <= 1 is carried: nothing named
        res, st, _e = pc(0.9)
        self.assertEqual(_route_lines(res), [])

    def test_a_plain_shell_is_never_named(self):
        res, _st, _e = _convert(_r10._plate(shrf="1.0"))
        self.assertEqual(_route_lines(res), [])


# ═════════════════════════════════════════════════════════════════════════════
# 3. The corrected texts
# ═════════════════════════════════════════════════════════════════════════════

class A7MassBalanceNamed(unittest.TestCase):
    """Findings 6.31 (1)(f): every site that describes A7 1b carries the mass
    balance - LS-DYNA's face admits the inflow too (0.995 x rho v A), LS-DYNA
    lets it out at the open faces of its Eulerian mesh, OpenRadioss closes
    them: +71.65 % at the end, mass RMS 35.53 % against 26.05 %."""

    def test_the_conversion_sentence(self):
        from k2rad.writer import blast_ale
        text = _t7._collapse(blast_ale._A7_INLET_MEASURED)
        for needle in ("0.995 x rho v A", "+0.11 / +0.43 / +1.41 %",
                       "*CONTROL_ALE EBC 0", "+71.65 %", "+153.8 %",
                       "+47.88 %", "stagnation_B +63.60 %", "35.53 %",
                       "26.05 %", "-32.37 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_help_and_the_gui(self):
        h = _help()
        for needle in ("where LS-DYNA's own face admits it",
                       "0.995 x rho v A", "+71.65 % above LS-DYNA's",
                       "mass RMS 35.53 % of its peak against 26.05 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)
        self.assertIn("no outflow: fluid mass +71.65 % at the end",
                      _t7._collapse(_src("k2rad_gui.py").replace(
                          '"\n                     "', "")))


class A8ForceDefinitionsNamed(unittest.TestCase):
    """Findings 6.31 (2)(d): a contact force figure names its definition -
    |FN + FT|, the like-for-like of LS-DYNA's rcforc resultant (FN alone is
    named as such) - and control_adaptive's three forces by it."""

    def test_the_sentence_and_the_help(self):
        from k2rad.writer import contacts
        text = _t7._collapse(contacts._A8_MEASURED)
        for needle in ("|FN + FT| (the like-for-like of LS-DYNA's rcforc "
                       "resultant) RMS 474.43 -> 46.72 %",
                       "normal force FN alone 448.56 -> 41.63 %",
                       "13.49 / 15.40 / 20.79 -> 14.34 / 15.62 / 22.16 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        h = _help()
        self.assertIn("|FN + FT| RMS 474.43 -> 46.72 %", h)
        self.assertIn("13.49 / 15.40 / 20.79 -> 14.34 / 15.62 / 22.16 %", h)


class N2sCautionNamesItsBytes(unittest.TestCase):
    """Findings 6.32 (2)(b): the 125-run spread is the pre-round-10 bytes';
    the round-10 bytes' 12 runs end at -21.37 .. -21.41 %."""

    def test_the_sentence_and_the_help(self):
        from k2rad.writer import contacts
        text = _t7._collapse(contacts._N2S_TYPE7_MEASURED)
        for needle in ("with the part drive, on the pre-round-10 bytes",
                       "12 runs at nt 4 and nt 2 end at -21.37 .. -21.41 %",
                       "which does not exclude one"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        h = _help()
        for needle in ("the pre-round-10 default with --implicit-n2s-type7",
                       "the round-10 bytes -21.37 .. -21.41 % in 12 runs",
                       "on the pre-round-10 bytes: IE END -0.78 .. -28.12 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)


class A5SliverIsARange(unittest.TestCase):
    """Findings 6.32 (2)(e): the metal-cutting sliver is a range of four
    runs of the same bytes, with the ratio 0.115 probe beside it."""

    def test_the_sentence_and_the_help(self):
        res, _s, _e = _convert(_r10._hex_block())
        hits = [w for w in res.warnings if w.startswith("/IMPL/DT/FIXPOINT")]
        self.assertEqual(len(hits), 1, hits)
        for needle in ("KE 52.3 .. 111.0 -> 3.57e8 .. 6.06e8",
                       "over four runs of the same bytes at nt 4",
                       "ratio 0.115: KE 0.160 -> 37.16"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        h = _help()
        self.assertIn("KE 52.3 .. 111.0 -> 3.57e8 .. 6.06e8 over four runs", h)


class ShrfHelpNamesTheTransducerPair(unittest.TestCase):
    """Findings 6.32 (2)(g): the transducer row is MIXED - KE RMS worse, IE
    RMS better - with n on both sides."""

    def test_the_help(self):
        self.assertIn("the transducer KE RMS 15.19 -> 17.28 % (n 947 / 948) "
                      "while its IE RMS improves 18.66 -> 17.32 % (IE END "
                      "+39.12 -> +42.52 %)", _help())


class RayleighHelpSaysWhen(unittest.TestCase):
    """Findings 6.32 (2)(h): no measured case of the round favours the
    opt-in, and the help says so."""

    def test_the_help(self):
        self.assertIn("No case measured in round 10 favours it: choose it "
                      "only where a run of your own deck shows a gain",
                      _help())


class SentencesWordedForTheirDecks(unittest.TestCase):
    """Findings 6.32 (2)(d) / (i): the A2 figure is the coupon's; the S-excl
    parenthetical covers the N-1 property; the initial-state keep says what
    happens to an NTHICK 1 record."""

    def test_the_mesh_texts(self):
        text = _t7._collapse(re.sub(r'"\s*\n\s*"', "",
                                    _src("k2rad/writer/mesh.py")))
        for needle in ("(the coupon's default bytes, nt 4)",
                       "(it stays 0: the starter's 5/6, or 0 on an N-1 "
                       "property)",
                       "a record whose NTHICK is not that N (an NTHICK 1 "
                       "record) is skipped by name"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


#: The verification round's retracted spellings (shipped texts; CHANGELOG
#: may quote them), matched case-folded with hyphens and whitespace runs
#: collapsed (:func:`_norm`).
_RETRACTED_ROUND_10_VERIFY = (
    # B9 (findings 6.31 (2)(a)): the false cycle-0 claim in its lowercase /
    # hyphenated spellings ('hit negative volume at cycle 0', 'hit
    # zero-or-negative volume at cycle 0', '= zero-or-negative volume at
    # cycle 0')
    "negative volume at cycle 0",
    # the unconditional blank-TSSFAC 0.9 (code verifier, minor)
    "LS-DYNA's default 0.9 is also the `/DT` default",
    "TSSFAC = 0 is LS-DYNA's \"use my default\" (0.9)",
    # the A2 / S-excl wordings (findings 6.32 (2)(d))
    "(these default bytes, nt 4)",
    "(it stays 0, the starter's 5/6)",
    # the single-sample sliver (6.32 (2)(e)) and the unscoped N2S default
    "KE 91.3 -> 6.06e8",
    "the shipped default with --implicit-n2s-type7",
    # A8's FN figure without its definition (6.31 (2)(d))
    "contact-1 force RMS 448.66",
)

#: the three B9 spellings as they stood at bc2910c (README.md:5003,
#: k2rad/cli.py:1660, k2rad/state.py:9253)
_OLD_CYCLE_0 = (
    "(1 and 2 hit negative volume at cycle 0, 12 is a silent no-op",
    '"*INITIAL_STRESS_SECTION (Isolid 1/2 hit zero-or-negative volume "\n'
    '             "at cycle 0 under /PRELOAD)',
    "*INITIAL_STRESS_SECTION (Isolid 1/2 = zero-or-negative volume at "
    "cycle 0\n    # under /PRELOAD Itype=2)",
)


class Round10VerifyRetractions(unittest.TestCase):
    """No shipped text carries a verification-round retracted spelling in
    any case, hyphenation or line split; the guard fires on the three old
    B9 spellings and on each needle split across literals."""

    def test_no_shipped_text_carries_one(self):
        for rel, _joined in _t7._SHIPPED_TEXTS():
            text = _norm(_src(rel))
            for needle in _RETRACTED_ROUND_10_VERIFY:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_norm(needle), text)

    def test_the_guard_matches_the_three_old_b9_spellings(self):
        for old in _OLD_CYCLE_0:
            with self.subTest(old=old[:40]):
                self.assertIn(_norm("negative volume at cycle 0"), _norm(old))
                # the round-10 B needle missed two of them
        self.assertEqual(sum(_t7._collapse("ZERO OR NEGATIVE VOLUME at cycle "
                                           "0").lower() in
                             _t7._collapse(o).lower() for o in _OLD_CYCLE_0),
                         0)

    def test_the_guard_fires_on_a_split_needle(self):
        for needle in _RETRACTED_ROUND_10_VERIFY:
            with self.subTest(needle=needle):
                fake = 'x "' + needle.replace(" ", ' "\n    "') + '" y'
                self.assertIn(_norm(needle), _norm(fake))

    def test_the_b9_replacement_is_shipped(self):
        for rel in ("README.md", "k2rad/cli.py", "k2rad/state.py"):
            with self.subTest(file=rel):
                self.assertIn(_norm("lose the cut element to ZERO OR NEGATIVE "
                                    "VOLUME"), _norm(_src(rel)))


if __name__ == "__main__":
    unittest.main()
