"""Tests for the CARDSTACK PIPELINE batch (k2rad) — group K4-engine, the
engine-deck changes in k2rad/writer/assembly.py:

  K-40  *CONTROL_TERMINATION ENDMAS -> an engine /STOP whose Mmax is the
        RATIO ENDMAS / 100, under the opt-in --stop-added-mass, on an
        explicit *CONTROL_TIMESTEP DT2MS < 0 deck (the only deck k2rad
        mass-scales). ENDMAS 0 / blank / >= 1e8 (LS-DYNA's own default 1e8)
        is off; ENDMAS < 0 (a load curve) is warned; the routed 2-D deck is
        warned and skipped (it carries no /DT/NODA/CST); ENDENG is warned
        only. Without the flag a stated ENDMAS is named in a warning. The
        DT2MS < 0 warning names the starter's 'INITIAL ADDED MASS
        ESTIMATION for /DT/NODA/CST' table and the engine's MAS.ERR column
        (the starter's 'ADDED MASS' lines are the /RBODY echo).
  K-41  the opt-in --dt2ms-tssfac-product: Tmin = TSSFAC x |DT2MS| on
        /DT/NODA/CST and /DT/AMS (the Tmin tests themselves sit in
        tests/test_control_timestep.py); the DT2MS > 0 texts say it is not
        converted on a 3-D deck (ROADMAP, round 9's NOT list, entry 5) and
        the drop is no longer silent when TSSFAC is blank.
  K-42  /PRINT/-N: --print-every N, else a stated *CONTROL_OUTPUT IKEDIT on
        a deck without *DATABASE_GLSTAT (LS-DYNA ignores IKEDIT when glstat
        is written, Vol I R17 p.12-441), else /PRINT/-1 as before; IKEDIT
        above 9999 is clamped (the engine reads the cell as I5).
        *DATABASE_EXTENT_BINARY MAXINT > 3 -> /ANIM/SHELL/TENS/STRESS/ALL.

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_7.py, and the 2-D
fixture from tests/test_r14_triage_9.py, as MODULES, so no earlier TestCase
is bound in this namespace and none runs twice.
"""

import unittest

import test_r14_triage_7 as _t7
import test_r14_triage_9 as _t9

from k2rad.state import DbExtentBinary

_row = _t7._row
_convert = _t7._convert
_dispatch = _t7._dispatch
_has = _t7._has


# ── decks ────────────────────────────────────────────────────────────────────

_PTS = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (0.0, 1.0), (1.0, 1.0),
        (2.0, 1.0)]


def _plate(*, dt2ms=None, tssfac="", endmas="", endeng="", ikedit=None,
           glstat=True, maxint=None, implicit=False, extra="", erode=None,
           tslimt=0.0):
    """Two explicit shells (*MAT_PLASTIC_KINEMATIC, ELFORM 2, NIP 3) with
    *CONTROL_TERMINATION ENDTIM 1e-3 plus the stated ENDENG / ENDMAS cells,
    and, when given, *CONTROL_TIMESTEP (TSSFAC, TSLIMT, DT2MS, and ERODE in
    field 7 when *erode* is given), *CONTROL_OUTPUT IKEDIT and
    *DATABASE_EXTENT_BINARY MAXINT. GLSTAT + D3PLOT output unless *glstat*
    is False. Values that do not fit a 10-character cell are passed as
    strings ("1.0E8")."""
    lines = ["*KEYWORD", "*TITLE", "k4 engine plate",
             "*CONTROL_TERMINATION", _row(0.001, "", "", endeng, endmas)]
    if dt2ms is not None:
        cells = [0.0, tssfac, 0, tslimt, dt2ms]
        if erode is not None:
            cells += ["", erode]
        lines += ["*CONTROL_TIMESTEP", _row(*cells)]
    if implicit:
        lines += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 0.0001)]
    if ikedit is not None:
        lines += ["*CONTROL_OUTPUT", _row(0, 0, 0, 0, 0.0, 0, ikedit)]
    if glstat:
        lines += ["*DATABASE_GLSTAT", _row(1.0e-5)]
    lines += ["*DATABASE_BINARY_D3PLOT", _row(1.0e-4)]
    if maxint is not None:
        lines += ["*DATABASE_EXTENT_BINARY", _row(0, 0, maxint)]
    lines += ["*NODE"] + [f"{i:>8}{x:>16}{y:>16}{0.0:>16}"
                          for i, (x, y) in enumerate(_PTS, 1)]
    lines += ["*ELEMENT_SHELL",
              "".join(f"{v:>8}" for v in (1, 1, 1, 2, 5, 4)),
              "".join(f"{v:>8}" for v in (2, 1, 2, 3, 6, 5))]
    lines += ["*PART", "plate", _row(1, 1, 1),
              "*SECTION_SHELL", _row(1, 2, "", 3), _row(0.1, 0.1, 0.1, 0.1),
              "*MAT_PLASTIC_KINEMATIC",
              _row(1, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0),
              _row(0.0, 0.0, 0.0)]
    if extra:
        lines.append(extra.rstrip("\n"))
    lines += ["*END", ""]
    return "\n".join(lines)


def _ax15(dt2ms, endmas="", tslimt=None, erode=None):
    """The round-9 B2 2-D fixture (AX-15, routed to /ANALY N2D3D 1) with a
    *CONTROL_TERMINATION that also states ENDMAS, and, when *erode* is
    given, *CONTROL_TIMESTEP TSLIMT (field 4) and ERODE (field 7)."""
    deck = _t9.b2_ax15(dt2ms=dt2ms)
    old = "*CONTROL_TERMINATION\n" + _t9._f10(1.0e-3)
    assert old in deck, "the B2 fixture changed its termination card"
    deck = deck.replace(
        old, "*CONTROL_TERMINATION\n" + _row(0.001, "", "", "", endmas))
    if erode is not None:
        old = "*CONTROL_TIMESTEP\n" + _t9._f10(0.0, 0.0, 0, 0.0, dt2ms)
        assert old in deck, "the B2 fixture changed its time-step card"
        deck = deck.replace(old, "*CONTROL_TIMESTEP\n" + _t9._f10(
            0.0, 0.0, 0, tslimt or 0.0, dt2ms, 0, erode))
    return deck


def _block(engine: str, key: str):
    """The data rows of the engine card *key* (an exact line), up to the
    next '#' / '/' line; None when the card is absent."""
    lines = engine.splitlines()
    if key not in lines:
        return None
    out = []
    for ln in lines[lines.index(key) + 1:]:
        if ln.startswith(("#", "/")):
            break
        out.append(ln)
    return out


def _print_cards(engine: str):
    return [ln for ln in engine.splitlines() if ln.startswith("/PRINT")]


# ═════════════════════════════════════════════════════════════════════════════
# K-40  ENDMAS -> /STOP Mmax (opt-in) and the added-mass warning
# ═════════════════════════════════════════════════════════════════════════════

class StopAddedMass(unittest.TestCase):
    """--stop-added-mass: ENDMAS (a PERCENT, Vol I R17 p.12-558) becomes
    the engine /STOP 'Emax Mmax Nmax Nth Nanim Nerr_posit' = '0. ENDMAS/100
    0. 1 1 0' (freform.F:767). Mmax is a RATIO: ecrit.F:516 computes EMASS =
    (M - M0) / M0 and ecrit.F:593 stops with MESSAGE 208 when EMASS > Mmax;
    Emax / Nmax 0 are off (freform.F:780-782 turn 0 into 1e30); Nth / Nanim
    1 write a time-history record and an animation file at the stop."""

    def test_flag_writes_stop_with_the_ratio(self):
        res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0),
                                stop_added_mass=True)
        rows = _block(eng, "/STOP")
        self.assertEqual(rows, ["0. 0.04 0. 1 1 0"])
        self.assertAlmostEqual(float(rows[0].split()[1]), 0.04, places=15)
        self.assertTrue(_has(res.warnings, "ENDMAS 4", "/STOP Mmax 0.04",
                             "MESSAGE 208", "--stop-added-mass"))
        # MEASURED (make_probes2.py a_stop5): the stopped run's listing ends
        # 'NORMAL TERMINATION' + 'USER BREAK' and the engine exits 0 - a
        # wrapper that reads only the exit code misses the stop
        self.assertTrue(_has(res.warnings, "ENDMAS 4", "USER BREAK",
                             "exits 0"))

    def test_mmax_follows_endmas(self):
        for endmas, mmax in ((5.0, 0.05), (12.5, 0.125), (400.0, 4.0),
                             ("1.0E-3", 1.0e-5)):
            with self.subTest(endmas=endmas):
                _r, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=endmas),
                                       stop_added_mass=True)
                rows = _block(eng, "/STOP")
                self.assertEqual(len(rows), 1)
                toks = rows[0].split()
                self.assertEqual(len(toks), 6)
                self.assertEqual((toks[0], toks[2], toks[3:]),
                                 ("0.", "0.", ["1", "1", "0"]))
                self.assertAlmostEqual(float(toks[1]) / mmax, 1.0, places=12)

    def test_mmax_keeps_six_significant_digits(self):
        # Mmax is printed with 6 significant digits: ENDMAS 12.345 % stops at
        # the ratio 0.12345, not at a rounded 0.123 (fix round: every value
        # above has at most 3 significant digits, so '.3G' survived them)
        for endmas, cell in ((12.345, "0.12345"), (1.23456, "0.0123456")):
            with self.subTest(endmas=endmas):
                _r, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=endmas),
                                       stop_added_mass=True)
                self.assertEqual(_block(eng, "/STOP"),
                                 [f"0. {cell} 0. 1 1 0"])

    def test_flag_text_names_the_restart_file_of_a_stopped_run(self):
        # MESSAGE 208 also sets MREST (ecrit.F:597). MEASURED (a_stop5): the
        # stopped run wrote p_0001_0001.rst (860043 B, listing 'RESTART
        # FILES: p_0001_[0001-0001].rst WRITTEN') although its engine deck
        # says /RFILE/OFF; the ENDMAS 400 run, never stopped, wrote none
        res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0),
                                stop_added_mass=True)
        self.assertIn("/RFILE/OFF", eng.splitlines())
        self.assertTrue(_has(res.warnings, "ENDMAS 4", "/STOP Mmax 0.04",
                             "restart file", "<stem>_0001_0001.rst",
                             "although the engine deck says /RFILE/OFF"))
        # --write-restart writes no /RFILE/OFF for the text to contradict
        res2, _s, eng2 = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0),
                                  stop_added_mass=True, write_restart=True)
        self.assertNotIn("/RFILE/OFF", eng2.splitlines())
        self.assertTrue(_has(res2.warnings, "ENDMAS 4", "/STOP Mmax 0.04",
                             "restart file"))
        self.assertFalse(_has(res2.warnings, "ENDMAS 4", "/STOP Mmax 0.04",
                              "/RFILE/OFF"))
        # without the flag there is no /STOP, so no restart text
        res3, _s, _e = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0))
        self.assertFalse(_has(res3.warnings, "ENDMAS 4", "restart file"))

    def test_stop_sits_after_the_time_step_card(self):
        _r, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0),
                               stop_added_mass=True)
        lines = eng.splitlines()
        self.assertEqual(lines.count("/STOP"), 1)
        self.assertLess(lines.index("/DT/NODA/CST/0"), lines.index("/STOP"))
        self.assertLess(lines.index("/STOP"), lines.index("/MON/ON"))

    def test_without_the_flag_no_stop_and_a_warning_names_the_flag(self):
        res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0))
        self.assertIsNone(_block(eng, "/STOP"))
        self.assertTrue(_has(res.warnings, "ENDMAS 4", "NOT converted",
                             "--stop-added-mass", "Mmax 0.04"))

    def test_the_flag_adds_only_the_stop_block(self):
        _r, _s, off = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0))
        _r, _s, on = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0),
                              stop_added_mass=True)
        self.assertEqual(on.replace("/STOP\n0. 0.04 0. 1 1 0\n#\n", ""), off)

    def test_off_values_write_nothing_and_say_nothing(self):
        # blank, 0 and LS-DYNA's own default 1.0E8 (and above) mean off. Every
        # ENDMAS text of K-40 names /STOP; the DT2MS < 0 warning's pointer
        # to the flag ('ENDMAS with --stop-added-mass ...') does not.
        for endmas in ("", 0.0, "1.0E8", "2.0E8"):
            for flag in (False, True):
                with self.subTest(endmas=endmas, flag=flag):
                    res, _s, eng = _convert(
                        _plate(dt2ms=-1.0e-6, endmas=endmas),
                        stop_added_mass=flag)
                    self.assertIsNone(_block(eng, "/STOP"))
                    self.assertFalse(_has(res.warnings, "ENDMAS", "/STOP"))
                    self.assertFalse(_has(res.warnings, "Mmax"))

    def test_no_mass_scaling_no_stop(self):
        # DT2MS >= 0, no *CONTROL_TIMESTEP, or an implicit deck: the engine
        # adds no mass, so there is nothing for Mmax to gate
        for kw in ({"dt2ms": 0.0}, {"dt2ms": 1.0e-6}, {},
                   {"dt2ms": -1.0e-6, "implicit": True}):
            with self.subTest(**kw):
                res, _s, eng = _convert(_plate(endmas=4.0, **kw),
                                        stop_added_mass=True)
                self.assertIsNone(_block(eng, "/STOP"))
                self.assertTrue(_has(res.warnings, "--stop-added-mass",
                                     "ENDMAS 4", "no /STOP"))
                res0, _s, _e = _convert(_plate(endmas=4.0, **kw))
                self.assertFalse(_has(res0.warnings, "--stop-added-mass"))

    def test_negative_endmas_is_a_curve_and_is_warned(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=-7.0),
                                        stop_added_mass=flag)
                self.assertIsNone(_block(eng, "/STOP"))
                self.assertTrue(_has(res.warnings, "ENDMAS -7",
                                     "load curve 7", "no /STOP"))

    def test_routed_2d_deck_is_warned_and_skipped(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                res, _s, eng = _convert(_ax15(-1.0e-4, endmas=5.0),
                                        stop_added_mass=flag)
                self.assertNotIn("/DT/NODA/CST", eng)
                self.assertIsNone(_block(eng, "/STOP"))
                self.assertTrue(_has(res.warnings, "ENDMAS 5",
                                     "routed 2-D deck", "no /STOP"))
                self.assertFalse(_has(res.warnings, "ENDMAS 5",
                                      "/STOP Mmax 0.05 ["))
        # the 3-D control: the same fixture off the 2-D route gets its /STOP
        _r, _s, eng = _convert(_ax15(-1.0e-4, endmas=5.0),
                               stop_added_mass=True, axisymmetric_2d=False)
        self.assertEqual(_block(eng, "/STOP"), ["0. 0.05 0. 1 1 0"])

    def test_routed_2d_density_route_is_warned_and_skipped(self):
        # DT2MS > 0 on the routed 2-D deck IS mass-scaled - by the density
        # cell, i.e. in the starter's material density - so the engine's
        # initial mass M0 already holds the added mass (ecrit.F:505), MAS.ERR
        # stays 0 and a /STOP Mmax could never fire: warned, with or without
        # the flag, and not called 'not mass-scaled'
        for flag in (False, True):
            with self.subTest(flag=flag):
                res, _s, eng = _convert(_ax15(1.0e-4, endmas=5.0),
                                        stop_added_mass=flag)
                self.assertTrue(_has(res.warnings, _t9._W_B2_DENSITY))
                self.assertIsNone(_block(eng, "/STOP"))
                self.assertTrue(_has(res.warnings, "ENDMAS 5",
                                     "routed 2-D deck", "density cell",
                                     "no /STOP", "MAS.ERR"))
                self.assertFalse(_has(res.warnings, "ENDMAS 5",
                                      "NOT converted by default"))
                self.assertFalse(_has(res.warnings, "ENDMAS 5",
                                      "not mass-scaled"))
        # without the density cell the routed DT2MS > 0 deck adds no mass at
        # all: the plain 'not converted' case, silent without the flag
        res, _s, eng = _convert(_ax15(1.0e-4, endmas=5.0),
                                positive_dt2ms_mass_scaling=False)
        self.assertIsNone(_block(eng, "/STOP"))
        self.assertFalse(_has(res.warnings, "ENDMAS 5"))

    def test_positive_dt2ms_flag_text_names_the_unconverted_dt2ms(self):
        # DT2MS > 0 is mass scaling in LS-DYNA (Vol I R17 p.12-585), so the
        # flag's 'no /STOP' text must not claim LS-DYNA would ignore ENDMAS
        # there: it names the DT2MS > 0 that k2rad does not convert
        res, _s, eng = _convert(_plate(dt2ms=1.0e-6, endmas=4.0),
                                stop_added_mass=True)
        self.assertIsNone(_block(eng, "/STOP"))
        self.assertTrue(_has(res.warnings, "--stop-added-mass", "ENDMAS 4",
                             "no /STOP", "DT2MS=1e-06 > 0", "not converted"))
        self.assertFalse(_has(res.warnings, "ENDMAS 4",
                              "LS-DYNA too reads ENDMAS only"))
        # DT2MS = 0 and a deck without *CONTROL_TIMESTEP keep that clause
        for kw in ({"dt2ms": 0.0}, {}):
            with self.subTest(**kw):
                res0, _s, _e = _convert(_plate(endmas=4.0, **kw),
                                        stop_added_mass=True)
                self.assertTrue(_has(res0.warnings, "ENDMAS 4",
                                     "LS-DYNA too reads ENDMAS only under "
                                     "mass scaling"))

    def test_ams_branch_is_warned_and_skipped(self):
        # MEASURED (make_probes.py a_ams5): /DT/AMS prints MAS.ERR 0.000 on
        # every cycle, so a /STOP Mmax beside it can never fire
        for flag in (False, True):
            with self.subTest(flag=flag):
                res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endmas=4.0),
                                        ams=True, stop_added_mass=flag)
                self.assertIsNotNone(_block(eng, "/DT/AMS"))
                self.assertIsNone(_block(eng, "/STOP"))
                self.assertTrue(_has(res.warnings, "ENDMAS 4", "--ams",
                                     "no /STOP", "MAS.ERR"))
                self.assertFalse(_has(res.warnings, "ENDMAS 4",
                                      "NOT converted by default"))

    def test_endeng_is_warned_only(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endeng=10.0),
                                        stop_added_mass=flag)
                self.assertIsNone(_block(eng, "/STOP"))
                self.assertTrue(_has(res.warnings, "ENDENG 10",
                                     "NOT converted", "/STOP Emax"))
        # beside a converted ENDMAS the Emax cell stays 0 (off)
        _r, _s, eng = _convert(_plate(dt2ms=-1.0e-6, endeng=10.0,
                                      endmas=4.0), stop_added_mass=True)
        self.assertEqual(_block(eng, "/STOP"), ["0. 0.04 0. 1 1 0"])
        # ENDENG on a deck without mass scaling is warned as well
        res, _s, _e = _convert(_plate(endeng=10.0))
        self.assertTrue(_has(res.warnings, "ENDENG 10", "NOT converted"))

    def test_endeng_and_endmas_change_no_byte_without_the_flag(self):
        _r, st0, eng0 = _convert(_plate(dt2ms=-1.0e-6))
        _r, st1, eng1 = _convert(_plate(dt2ms=-1.0e-6, endeng=10.0,
                                        endmas=4.0))
        self.assertEqual(eng1, eng0)
        self.assertEqual(st1, st0)


class AddedMassWarningText(unittest.TestCase):
    """The DT2MS < 0 -> /DT/NODA/CST warning names the two places the added
    mass is printed: the starter's 'INITIAL ADDED MASS ESTIMATION for
    /DT/NODA/CST' table (add_mass_stat.F:154, DM/M at the first cycle
    against the target step) and the engine's MAS.ERR column (ecrit.F:516).
    The old 'Check the starter ADDED MASS' pointed at the /RBODY echo."""

    def test_names_the_starter_table_and_mas_err(self):
        res, _s, _e = _convert(_plate(dt2ms=-1.0e-6))
        self.assertTrue(_has(res.warnings, "DT2MS=-1e-06", "/DT/NODA/CST/0",
                             "INITIAL ADDED MASS ESTIMATION for /DT/NODA/CST",
                             "MAS.ERR", "(M - M0) / M0",
                             "the /RBODY echo", "--stop-added-mass"))
        self.assertFalse(_has(res.warnings, "Check the starter ADDED MASS"))

    def test_routed_2d_deck_gets_no_added_mass_text(self):
        # transform_engine_lines drops /DT/NODA/CST and /DT/AMS there and
        # says so; a text about the mass they add would be false
        for kw in ({}, {"ams": True}):
            with self.subTest(**kw):
                res, _s, eng = _convert(_ax15(-1.0e-4), **kw)
                self.assertNotIn("/DT/NODA/CST", eng)
                self.assertNotIn("/DT/AMS", eng)
                self.assertTrue(_has(res.warnings, "DT2MS -0.0001 < 0 on the "
                                     "routed 2-D deck: /DT/NODA/CST is NOT "
                                     "written"))
                self.assertFalse(_has(res.warnings, "MAS.ERR"))
                self.assertFalse(_has(res.warnings, "(Advanced Mass Scaling"))
        # off the 2-D route the same fixture gets the text
        res, _s, _e = _convert(_ax15(-1.0e-4), axisymmetric_2d=False)
        self.assertTrue(_has(res.warnings, "/DT/NODA/CST/0 (nodal mass",
                             "MAS.ERR"))


# ═════════════════════════════════════════════════════════════════════════════
# K-41  the DT2MS texts (the Tmin values: tests/test_control_timestep.py)
# ═════════════════════════════════════════════════════════════════════════════

_OLD_DT2MS0_TEXT = (
    "*CONTROL_TIMESTEP TSSFAC=0.8 (DT2MS=0, no mass scaling) -> /DT "
    "Tsca=0.8. The time-step safety factor is carried over; Tmin=0 (no "
    "lower bound) because LS-DYNA TSLIMT is not converted, so the engine "
    "will not stop or delete on a small step.")


class Dt2msTexts(unittest.TestCase):

    def test_default_text_states_the_step_and_names_the_flag(self):
        # R14 round 10, A4: the product is the default
        res, _s, _e = _convert(_plate(dt2ms=-1.0e-6, tssfac=0.9))
        self.assertTrue(_has(res.warnings,
                             "Tmin = TSSFAC x |DT2MS| = 0.9 x 1e-06 = 9e-07",
                             "Vol I R17 p.12-585", "convertcards.cxx:173-174",
                             "--no-dt2ms-tssfac-product writes Tmin = "
                             "|DT2MS| = 1e-06"))
        self.assertFalse(_has(res.warnings, "[--dt2ms-tssfac-product]"))

    def test_default_text_says_a_nodal_step_below_tmin_is_lifted(self):
        # /DT/NODA/CST (IDTMIN(11) = 8, freform.F:1057-1059) adds mass only to
        # a node whose own step is below Tmin (dtnoda.F:270-303) and clamps
        # the global step only when it fell below Tmin (:654-655), so a deck
        # whose nodal steps all exceed Tmin keeps its own larger step - 'the
        # run steps at Tmin' overstated it (fix round)
        res, _s, _e = _convert(_plate(dt2ms=-1.0e-6, tssfac=0.9))
        self.assertTrue(_has(res.warnings, "Tmin = TSSFAC x |DT2MS|",
                             "every nodal step below 9e-07 is lifted to it",
                             "a floor 1/TSSFAC higher"))
        self.assertFalse(_has(res.warnings, "the run steps at 9e-07"))
        # the opt-out keeps the ed52c93 Tmin and its sentence
        res, _s, _e = _convert(_plate(dt2ms=-1.0e-6, tssfac=0.9),
                               dt2ms_tssfac_product=False)
        self.assertTrue(_has(res.warnings, "Tmin = |DT2MS| = 1e-06 "
                             "[--no-dt2ms-tssfac-product]",
                             "every nodal step below 1e-06 is lifted to it",
                             "a floor 1/TSSFAC higher"))
        self.assertFalse(_has(res.warnings, "the run steps at 1e-06"))

    def test_negative_tssfac_is_a_curve_and_takes_0_9(self):
        # TSSFAC < 0 names a load curve of the scale factor, not converted:
        # 0.9 is written, and said, by default, with the flag and on the AMS
        # branch (Tsca 0.67 there); the Tmin values sit in
        # tests/test_control_timestep.py (fix round: no test had a TSSFAC <
        # 0, so the branch could flip the default Tsca unseen)
        for kw in ({}, {"dt2ms_tssfac_product": True}, {"ams": True}):
            with self.subTest(**kw):
                res, _s, eng = _convert(_plate(dt2ms=-1.0e-6, tssfac=-3.0),
                                        **kw)
                card = "/DT/AMS" if kw.get("ams") else "/DT/NODA/CST/0"
                rows = _block(eng, card)
                self.assertEqual(float(rows[0].split()[0]),
                                 0.67 if kw.get("ams") else 0.9)
                self.assertTrue(_has(res.warnings, "TSSFAC -3 < 0 (load "
                                     "curve 3, not converted) -> 0.9; "))
                self.assertFalse(_has(res.warnings, "TSSFAC blank"))

    def test_the_ams_text_keeps_dt2ms_on_both_arms(self):
        # R14 round 10, A4 (D12): /DT/AMS keeps Tmin = |DT2MS| whatever
        # the lever, as dyna2rad writes it; the sentence says why
        for kw in ({}, {"dt2ms_tssfac_product": False}):
            with self.subTest(**kw):
                res, _s, _e = _convert(_plate(dt2ms=-1.0e-6, tssfac=0.9),
                                       ams=True, **kw)
                self.assertTrue(_has(
                    res.warnings, "Tmin = |DT2MS| = 1e-06 on /DT/AMS",
                    "convertcards.cxx:233-234", "TSSFAC x |DT2MS| = 9e-07",
                    "resol.F:5847-5857"))
                self.assertFalse(_has(res.warnings, "Tmin = TSSFAC x "
                                      "|DT2MS| = 0.9 x 1e-06"))

    def test_blank_tssfac_is_named_as_0_9(self):
        res, _s, _e = _convert(_plate(dt2ms=-1.0e-6),
                               dt2ms_tssfac_product=True)
        self.assertTrue(_has(res.warnings, "TSSFAC blank -> 0.9",
                             "Tmin = TSSFAC x |DT2MS| = 0.9 x 1e-06 = 9e-07"))

    def test_dt_del_coexistence_text_states_the_written_tmin(self):
        # ERODE 1 + TSLIMT > 0 beside DT2MS < 0: the /DT/<elem>/DEL warning
        # restates the /DT/NODA/CST Tmin - the one actually written
        for flag, tmin, cell in ((False, "1e-06", 1.0e-6),
                                 (True, "9e-07", 9.0e-7)):
            with self.subTest(flag=flag):
                res, _s, eng = _convert(
                    _plate(dt2ms=-1.0e-6, tssfac=0.9, tslimt=1.0e-9,
                           erode=1), dt2ms_tssfac_product=flag)
                rows = _block(eng, "/DT/NODA/CST/0")
                self.assertAlmostEqual(float(rows[0].split()[1]), cell,
                                       places=15)
                self.assertIsNotNone(_block(eng, "/DT/SHELL/DEL"))
                self.assertTrue(_has(res.warnings, "/DT/{SHELL,SH_3N,BRICK}"
                                     "/DEL", "It coexists with /DT/NODA/CST "
                                     f"(Tmin={tmin})"))

    def test_dt_del_text_on_the_routed_2d_deck_names_no_noda_cst(self):
        # the routed 2-D deck carries no /DT/NODA/CST and no /DT/AMS
        # (transform_engine_lines drops both and says so), so the
        # /DT/<elem>/DEL warning must not say it coexists with one, nor give
        # the --ams note (fix round; measured with the reviewer's
        # probe_2d_del.py: '/DT/NODA/CST in engine: False' beside 'It
        # coexists with /DT/NODA/CST (Tmin=0.0001)')
        for kw in ({}, {"ams": True}):
            with self.subTest(**kw):
                res, _s, eng = _convert(
                    _ax15(-1.0e-4, tslimt=1.0e-9, erode=1), **kw)
                self.assertNotIn("/DT/NODA/CST", eng)
                self.assertNotIn("/DT/AMS", eng)
                self.assertIsNotNone(_block(eng, "/DT/SHELL/DEL"))
                self.assertTrue(_has(res.warnings, "ERODE=1 TSLIMT=1e-09",
                                     "/DT/{SHELL,SH_3N,BRICK}/DEL",
                                     "On this routed 2-D deck no "
                                     "/DT/NODA/CST or /DT/AMS is written"))
                self.assertFalse(_has(res.warnings, "It coexists with "
                                      "/DT/NODA/CST"))
                self.assertFalse(_has(res.warnings, "ERODE=1",
                                      "NOTE --ams"))
        # off the 2-D route the same fixture keeps the coexistence text, with
        # the written Tmin: TSSFAC blank -> 0.9, so 0.9 x 1e-4 = 9e-05 since
        # round 10 (A4; 0.0001 under --no-dt2ms-tssfac-product)
        res, _s, eng = _convert(_ax15(-1.0e-4, tslimt=1.0e-9, erode=1),
                                axisymmetric_2d=False)
        self.assertIsNotNone(_block(eng, "/DT/NODA/CST/0"))
        self.assertTrue(_has(res.warnings, "It coexists with /DT/NODA/CST "
                             "(Tmin=9e-05)"))
        res, _s, eng = _convert(_ax15(-1.0e-4, tslimt=1.0e-9, erode=1),
                                axisymmetric_2d=False,
                                dt2ms_tssfac_product=False)
        self.assertTrue(_has(res.warnings, "It coexists with /DT/NODA/CST "
                             "(Tmin=0.0001)"))
        self.assertFalse(_has(res.warnings, "On this routed 2-D deck no "
                              "/DT/NODA/CST"))
        self.assertFalse(_has(res.warnings, "/DT/QUAD/DEL"))

    def test_dt_del_text_on_the_routed_2d_deck_names_the_quad_floor(self):
        # the routed 2-D deck's elements are /QUAD; the quad floor is
        # /DT/QUAD/DEL (IDTMIN(2), freform.F:1103-1106; the element test
        # reads IDTMIN(ITY), mqviscb.F:425-498) and k2rad writes only the
        # SHELL / SH_3N / BRICK cards (IDTMIN(3), (7), (1)): the text says so,
        # whatever DT2MS. MEASURED (fix round, mk_quad_probe.py, TSLIMT 1e-6
        # above every element's step): as written 0 of 6 quads deleted,
        # engine echo 'QUAD MINIMUM TIME STEP 0.000000'; with /DT/QUAD/DEL
        # added by hand 6 of 6 deleted
        for dt2ms in (-1.0e-4, 1.0e-4):
            with self.subTest(dt2ms=dt2ms):
                res, st, eng = _convert(
                    _ax15(dt2ms, tslimt=1.0e-9, erode=1))
                self.assertIn("/QUAD/1", st.splitlines())
                self.assertIsNone(_block(eng, "/DT/QUAD/DEL"))
                self.assertTrue(_has(res.warnings, "ERODE=1 TSLIMT=1e-09",
                                     "whose elements are /QUAD",
                                     "/DT/QUAD/DEL (IDTMIN(2)",
                                     "none of these three cards reaches "
                                     "them", "0 quads deleted"))

    def test_dt2ms_zero_keeps_the_old_text_byte_for_byte(self):
        res, _s, _e = _convert(_plate(dt2ms=0.0, tssfac=0.8))
        self.assertIn(_OLD_DT2MS0_TEXT, res.warnings)

    def test_positive_dt2ms_text_is_honest(self):
        res, _s, eng = _convert(_plate(dt2ms=1.0e-6, tssfac=0.8))
        rows = _block(eng, "/DT")
        self.assertEqual([float(v) for v in rows[0].split()], [0.8, 0.0])
        self.assertFalse(_has(res.warnings, "DT2MS=1e-06, no mass scaling"))
        self.assertTrue(_has(res.warnings, "TSSFAC=0.8", "/DT Tsca=0.8",
                             "DT2MS=1e-06 > 0", "NOT converted",
                             "ROADMAP", "Positive DT2MS on 3-D decks"))
        # the 3-D wording, not the routed 2-D deck's (fix round: a swapped
        # where-clause survived every test)
        self.assertTrue(_has(res.warnings, "DT2MS=1e-06 > 0",
                             "is NOT converted on a 3-D deck:"))
        self.assertFalse(_has(res.warnings, "--no-positive-dt2ms-mass-"
                              "scaling"))

    def test_positive_dt2ms_with_blank_tssfac_is_no_longer_silent(self):
        res, _s, eng = _convert(_plate(dt2ms=1.0e-6))
        self.assertNotIn("/DT", eng.splitlines())
        self.assertTrue(_has(res.warnings, "DT2MS=1e-06 > 0", "NOT converted",
                             "ROADMAP", "Positive DT2MS on 3-D decks"))
        self.assertTrue(_has(res.warnings, "DT2MS=1e-06 > 0",
                             "is NOT converted on a 3-D deck:"))

    def test_routed_2d_density_cell_is_not_called_a_drop(self):
        res, _s, _e = _convert(_ax15(1.0e-4))
        self.assertTrue(_has(res.warnings, _t9._W_B2_DENSITY))
        self.assertFalse(_has(res.warnings, "> 0", "NOT converted",
                              "ROADMAP"))
        # without the density cell the drop is named
        res2, _s, _e = _convert(_ax15(1.0e-4),
                                positive_dt2ms_mass_scaling=False)
        self.assertFalse(_has(res2.warnings, _t9._W_B2_DENSITY))
        self.assertTrue(_has(res2.warnings, "DT2MS=0.0001 > 0",
                             "NOT converted", "ROADMAP"))
        # ... in the routed 2-D deck's words, not the 3-D deck's
        self.assertTrue(_has(res2.warnings, "DT2MS=0.0001 > 0",
                             "is NOT converted on this routed 2-D deck "
                             "(--no-positive-dt2ms-mass-scaling"))
        self.assertFalse(_has(res2.warnings, "DT2MS=0.0001 > 0",
                              "on a 3-D deck"))


# ═════════════════════════════════════════════════════════════════════════════
# K-42  /PRINT/-N and MAXINT > 3
# ═════════════════════════════════════════════════════════════════════════════

class PrintEvery(unittest.TestCase):
    """/PRINT/-N: the engine reads N from the keyword line with
    FMT='(7X,I5,X,I5)' (freform.F:1563) and prints a cycle row every N
    cycles to <stem>_0001.out and, N < 0, also to the console
    (ecrit.F:156 / 652)."""

    def test_flag_writes_print_minus_n(self):
        _r, _s, eng = _convert(_plate(), print_every=100)
        self.assertEqual(_print_cards(eng), ["/PRINT/-100"])

    def test_ikedit_without_glstat(self):
        res, _s, eng = _convert(_plate(ikedit=50, glstat=False))
        self.assertEqual(_print_cards(eng), ["/PRINT/-50"])
        self.assertTrue(_has(res.warnings, "IKEDIT 50", "/PRINT/-50",
                             "--print-every 1",
                             "up to N - 1 cycles before the end"))

    def test_ikedit_with_glstat_is_ignored_like_ls_dyna(self):
        res, _s, eng = _convert(_plate(ikedit=50, glstat=True))
        self.assertEqual(_print_cards(eng), ["/PRINT/-1"])
        self.assertFalse(_has(res.warnings, "IKEDIT"))

    def test_a_glstat_card_with_a_blank_dt_still_counts(self):
        # presence, not DT: a blank-DT glstat card can be paced by its LCUR
        # curve, which k2rad does not read - such a deck keeps /PRINT/-1
        deck = _plate(ikedit=50, glstat=False,
                      extra="*DATABASE_GLSTAT\n" + _row(""))
        state = _dispatch(deck)
        self.assertEqual(state.db_glstat_dt, 0.0)
        self.assertIn("DATABASE_GLSTAT", state.deck_keywords)
        res, _s, eng = _convert(deck)
        self.assertEqual(_print_cards(eng), ["/PRINT/-1"])
        self.assertFalse(_has(res.warnings, "IKEDIT"))

    def test_a_glstat_option_spelling_counts(self):
        # *DATABASE_GLSTAT_MASS_PROPERTIES writes the glstat file too ('an
        # option for the glstat file to include mass and inertial
        # properties', Vol I R17 p.16-7). k2rad has no handler for it, so
        # db_glstat_dt stays 0 and only the DATABASE_GLSTAT_<option> spelling
        # test of _glstat_requested keeps the deck at /PRINT/-1 (fix round:
        # dropping that test survived every module)
        for dt in (1.0e-5, ""):
            with self.subTest(dt=dt):
                deck = _plate(ikedit=50, glstat=False,
                              extra="*DATABASE_GLSTAT_MASS_PROPERTIES\n"
                              + _row(dt))
                state = _dispatch(deck)
                self.assertEqual(state.db_glstat_dt, 0.0)
                self.assertNotIn("DATABASE_GLSTAT", state.deck_keywords)
                self.assertIn("DATABASE_GLSTAT_MASS_PROPERTIES",
                              state.deck_keywords)
                res, _s, eng = _convert(deck)
                self.assertEqual(_print_cards(eng), ["/PRINT/-1"])
                self.assertFalse(_has(res.warnings, "IKEDIT"))

    def test_flag_wins_over_ikedit(self):
        _r, _s, eng = _convert(_plate(ikedit=50, glstat=False),
                               print_every=7)
        self.assertEqual(_print_cards(eng), ["/PRINT/-7"])

    def test_blank_or_absent_ikedit_keeps_print_minus_1(self):
        for kw in ({"ikedit": ""}, {"ikedit": 0}, {}):
            with self.subTest(**kw):
                res, _s, eng = _convert(_plate(glstat=False, **kw))
                self.assertEqual(_print_cards(eng), ["/PRINT/-1"])
                self.assertFalse(_has(res.warnings, "IKEDIT"))

    def test_ikedit_above_9999_is_clamped(self):
        res, _s, eng = _convert(_plate(ikedit=20000, glstat=False))
        self.assertEqual(_print_cards(eng), ["/PRINT/-9999"])
        self.assertTrue(_has(res.warnings, "IKEDIT 20000", "/PRINT/-9999",
                             "I5"))

    def test_ikedit_9999_fits_and_is_not_called_clamped(self):
        # 9999 is the widest N the I5 cell holds: written as given, and the
        # warning does not claim it was cut (fix round: '>' -> '>=' in the
        # clamp clause survived every test)
        res, _s, eng = _convert(_plate(ikedit=9999, glstat=False))
        self.assertEqual(_print_cards(eng), ["/PRINT/-9999"])
        self.assertTrue(_has(res.warnings, "IKEDIT 9999", "/PRINT/-9999"))
        self.assertFalse(_has(res.warnings, "IKEDIT 9999", "is above 9999"))

    def test_print_every_1_is_the_old_line(self):
        _r, _s, old = _convert(_plate(glstat=False))
        _r, _s, new = _convert(_plate(ikedit=50, glstat=False),
                               print_every=1)
        self.assertEqual(new, old)


class AnimShellStressAll(unittest.TestCase):
    """*DATABASE_EXTENT_BINARY MAXINT > 3 asks for 'the first MAXINT
    integration points' (Vol I R17 p.16-67) -> /ANIM/SHELL/TENS/STRESS/ALL
    (anim_dcod_key_0.F:302-304: ISTRESALL, every layer of
    anim_build_index_all.F:152-167, plus UPPER / LOWER), beside the MEMB /
    UPPER / LOWER lines k2rad always writes."""

    _ALL = "/ANIM/SHELL/TENS/STRESS/ALL"

    def _state(self, maxint):
        state = _dispatch(_plate())
        if maxint is not None:
            state.db_extent_binary = DbExtentBinary()
            # DbExtentBinary.maxint (card 1 field 3) as the handler stores it
            state.db_extent_binary.maxint = maxint
        return state

    def test_writer_rule_maxint_above_3(self):
        from k2rad.writer.assembly import _make_engine_output
        for maxint, want in ((5, True), (4, True), (3, False), (0, False),
                             (-5, False), (None, False)):
            with self.subTest(maxint=maxint):
                lines = _make_engine_output(self._state(maxint))
                self.assertEqual(self._ALL in lines, want)
                self.assertIn("/ANIM/SHELL/TENS/STRESS/MEMB", lines)
                if want:
                    self.assertEqual(
                        lines.index(self._ALL),
                        lines.index("/ANIM/SHELL/TENS/STRESS/LOWER") + 1)

    def test_maxint_3_deck_unchanged(self):
        _r, _s, eng3 = _convert(_plate(maxint=3))
        _r, _s, eng0 = _convert(_plate())
        self.assertNotIn(self._ALL, eng3)
        self.assertEqual(eng3, eng0)

    def test_maxint_5_deck_writes_stress_all(self):
        _r, _s, eng = _convert(_plate(maxint=5))
        lines = eng.splitlines()
        self.assertIn(self._ALL, lines)
        self.assertEqual(lines.index(self._ALL),
                         lines.index("/ANIM/SHELL/TENS/STRESS/LOWER") + 1)


class MaxintStressAllOptOut(unittest.TestCase):
    """--no-maxint-stress-all (wave D, the user's decision 8 of 2026-11-01):
    since wave C the handler stores MAXINT and K-42's rule writes
    /ANIM/SHELL/TENS/STRESS/ALL for MAXINT > 3 (nine R14 engine decks gain
    the line). The flag writes no such line whatever MAXINT says - the
    engine deck of the code before the read - and the handler's MAXINT line
    says so; the read itself stays."""

    _ALL = "/ANIM/SHELL/TENS/STRESS/ALL"
    _FLAG = "--no-maxint-stress-all"

    def test_maxint_5_by_default_writes_the_line(self):
        res, _s, eng = _convert(_plate(maxint=5))
        lines = eng.splitlines()
        self.assertEqual(lines.index(self._ALL),
                         lines.index("/ANIM/SHELL/TENS/STRESS/LOWER") + 1)
        self.assertTrue(_has(res.warnings, "MAXINT 5",
                             "-> /ANIM/SHELL/TENS/STRESS/ALL in the engine "
                             "deck"), res.warnings)
        self.assertFalse(_has(res.warnings, self._FLAG), res.warnings)

    def test_maxint_5_under_the_flag_writes_no_line_and_says_so(self):
        for maxint in (4, 5, 8):
            with self.subTest(maxint=maxint):
                res, s, eng = _convert(_plate(maxint=maxint),
                                       maxint_stress_all=False)
                _r3, s3, eng3 = _convert(_plate(maxint=3))
                self.assertNotIn(self._ALL, eng)
                self.assertEqual((s, eng), (s3, eng3))
                ws = [w for w in res.warnings if f"MAXINT {maxint}" in w]
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in (self._FLAG, "is not written",
                               "STRESS/MEMB / UPPER / LOWER", "p.16-67"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
                self.assertNotIn("-> /ANIM/SHELL/TENS/STRESS/ALL in the "
                                 "engine deck", ws[0])

    def test_the_read_stays_under_the_flag(self):
        import os
        import tempfile
        from k2rad.handlers import dispatch
        from k2rad.parser import parse_k_file
        from k2rad.state import ConversionState, ConvertOptions
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(_plate(maxint=5))
        state = ConversionState()
        state.options = ConvertOptions(maxint_stress_all=False)
        for block in parse_k_file(path):
            dispatch(block, state)
        tmp.cleanup()
        self.assertEqual(state.db_extent_binary.maxint, 5)

    def test_maxint_3_or_blank_is_unchanged_both_ways(self):
        _r, _s, eng0 = _convert(_plate())
        for maxint in (None, 3, 0):
            for flag in (True, False):
                with self.subTest(maxint=maxint, flag=flag):
                    res, _s, eng = _convert(_plate(maxint=maxint),
                                            maxint_stress_all=flag)
                    self.assertEqual(eng, eng0)
                    self.assertFalse(_has(res.warnings, "MAXINT"),
                                     res.warnings)

    def test_a_negative_maxint_moves_nothing_and_names_the_flag(self):
        """A MAXINT below -3 never reaches the rule, so the engine deck is
        the same both ways; under the flag its line says that no MAXINT
        reaches it (the wave-D review: it said MAXINT > 3 does, either
        way). Every other line is the same."""
        r1, _s, e1 = _convert(_plate(maxint=-5))
        r0, _s, e0 = _convert(_plate(maxint=-5), maxint_stress_all=False)
        self.assertEqual(e1, e0)
        self.assertNotIn(self._ALL, e0)
        w1 = [w for w in r1.warnings if "MAXINT -5" in w]
        w0 = [w for w in r0.warnings if "MAXINT -5" in w]
        self.assertEqual((len(w1), len(w0)), (1, 1),
                         (r1.warnings, r0.warnings))
        self.assertIn("k2rad writes it for MAXINT > 3 only, so the engine "
                      "deck keeps STRESS/MEMB / UPPER / LOWER.", w1[0])
        self.assertNotIn(self._FLAG, w1[0])
        self.assertIn("k2rad writes it for MAXINT > 3 only, and for no "
                      "MAXINT under --no-maxint-stress-all, so the engine "
                      "deck keeps STRESS/MEMB / UPPER / LOWER.", w0[0])
        self.assertEqual([w for w in r1.warnings if w not in w1],
                         [w for w in r0.warnings if w not in w0])

    def test_the_writer_rule_reads_the_option(self):
        from k2rad.writer.assembly import _make_engine_output
        state = _dispatch(_plate())
        state.db_extent_binary = DbExtentBinary(maxint=5)
        self.assertIn(self._ALL, _make_engine_output(state))
        state.options.maxint_stress_all = False
        self.assertNotIn(self._ALL, _make_engine_output(state))

    def test_the_help_and_the_gui_carry_the_opt_out(self):
        import os
        import tempfile
        import k2rad_gui
        from k2rad import cli
        acts = {s: a for a in cli.build_parser()._actions
                for s in a.option_strings}
        self.assertIs(acts["--maxint-stress-all"],
                      acts["--no-maxint-stress-all"])
        self.assertIs(acts["--maxint-stress-all"].default, True)
        h = " ".join(acts["--maxint-stress-all"].help.split())
        for needle in ("MAXINT", self._ALL, "ON by default", self._FLAG,
                       "K-42"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        kw = dict(ground_springs=False, ground_spring_k_text="",
                  soften_stfac_text="")
        on = k2rad_gui.build_convert_kwargs(path, "", ("Mg", "mm", "s"),
                                            **kw)
        off = k2rad_gui.build_convert_kwargs(path, "", ("Mg", "mm", "s"),
                                             maxint_stress_all=False, **kw)
        tmp.cleanup()
        self.assertIs(on["maxint_stress_all"], True)
        self.assertIs(off["maxint_stress_all"], False)


if __name__ == "__main__":
    unittest.main()
