"""Failure-criteria conversion tests:

  * *MAT_ADD_EROSION → /FAIL/GENE1 — the full card-1/card-2 scalar-criteria set
    (MXPRES/MNPRES/SIGP1/SIGVM/MXEPS/MNEPS/EFFEPS/VOLEPS/EPSSH/SIGTH/IMPULSE/
    FAILTM/NCS), the reader's sign forcing (Pmin=-ABS, Pmax=+ABS, Eps_min=-ABS),
    0 = inactive, NUMFIP → Pthickfail, EXCL exclusion, SIGVM/MXEPS load-curve
    forms, and the IDAM (GISSMO/DIEM) warn.
  * *MAT_123 EPSTHIN → /FAIL/TAB1 P_THICKFAIL, EPSMAJ → /FAIL/FLD, NUMINT warn,
    with the base /MAT/LAW36 + /FAIL/JOHNSON kept unchanged.
  * *MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION(_2D) dispatch + F_smooth=2.
  * Numeric MAT aliases (MAT_024/MAT_123) and no-regression of the MAT_024 /
    GISSMO paths.

Kept separate from tests/test_converter.py (helpers modeled on
tests/test_roadmap_keywords.py / tests/test_tables_rates.py).
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState


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
    """LS-DYNA fixed-width (10-char) card row from string/number fields."""
    return "".join(f"{v:>10}" for v in vals)


def _gene1_cards(starter: str, mid: int = 1):
    """The 7 /FAIL/GENE1 data lines (comments dropped) keyed c1..c7."""
    body = starter.split(f"/FAIL/GENE1/{mid}", 1)[1].splitlines()
    return {f"c{k}": body[2 * k] for k in range(1, 8)}


def _erosion_deck(card1: str, card2: str, card3: str = None,
                  extra: str = "") -> str:
    parts = [
        "*KEYWORD",
        "*MAT_ELASTIC",
        _row("1", "1.05E-9", "1800.0", "0.4"),
        "*MAT_ADD_EROSION",
        card1,
        card2,
    ]
    if card3 is not None:
        parts.append(card3)
    if extra:
        parts.append(extra.rstrip("\n"))
    parts += ["*CONTROL_TERMINATION", _row("1.0"), "*END", ""]
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# *MAT_ADD_EROSION → /FAIL/GENE1 : full scalar-criteria field map + signs
# ─────────────────────────────────────────────────────────────────────────────

class Gene1FieldMapTests(unittest.TestCase):
    #                MID    EXCL    MXPRES   MNEPS   EFFEPS  VOLEPS  NUMFIP  NCS
    CARD1 = _row("1", "0.0", "-500.0", "-0.1", "0.2", "0.3", "1.0", "2.0")
    #              MNPRES  SIGP1   SIGVM   MXEPS   EPSSH   SIGTH   IMPULSE FAILTM
    CARD2 = _row("300.0", "250.0", "400.0", "0.15", "0.08", "100.0", "5.0", "0.001")

    def setUp(self):
        self.result, self.starter = _convert(_erosion_deck(self.CARD1, self.CARD2))
        self.c = _gene1_cards(self.starter)

    def test_not_skipped_and_gene1_emitted(self):
        self.assertNotIn("MAT_ADD_EROSION", self.result.skipped_keywords)
        self.assertIn("/FAIL/GENE1/1", self.starter)
        self.assertNotIn("/FAIL/TENSSTRAIN/1", self.starter)

    def test_card1_pressures_and_time(self):
        c1 = self.c["c1"]
        self.assertEqual(float(c1[0:20]), -300.0)    # Pmin  = -ABS(MNPRES 300)
        self.assertEqual(float(c1[20:40]), 500.0)    # Pmax  = +ABS(MXPRES -500)
        self.assertEqual(float(c1[40:60]), 250.0)    # SigP1_max = SIGP1
        self.assertEqual(float(c1[60:80]), 0.001)    # Time_max  = FAILTM
        self.assertEqual(c1[80:100].strip(), "0")    # dtmin inactive

    def test_card2_stress_and_tuler_butcher(self):
        c2 = self.c["c2"]
        self.assertEqual(c2[0:10].strip(), "0")      # fct_IDsm (scalar SIGVM)
        self.assertEqual(float(c2[40:60]), 400.0)    # Sig_max = SIGVM
        self.assertEqual(float(c2[60:80]), 100.0)    # Sigr    = SIGTH
        self.assertEqual(float(c2[80:100]), 5.0)     # K       = IMPULSE

    def test_card3_strains(self):
        c3 = self.c["c3"]
        self.assertEqual(c3[0:10].strip(), "0")      # fct_IDps (scalar MXEPS)
        self.assertEqual(float(c3[40:60]), 0.15)     # Eps_max = MXEPS
        self.assertEqual(float(c3[60:80]), 0.2)      # Eps_eff = ABS(EFFEPS)
        self.assertEqual(float(c3[80:100]), 0.3)     # Eps_vol = VOLEPS

    def test_card4_min_strain_forced_negative(self):
        c4 = self.c["c4"]
        self.assertEqual(float(c4[0:20]), -0.1)      # Eps_min = -ABS(MNEPS)
        self.assertEqual(float(c4[20:40]), 0.08)     # Eps_s   = EPSSH

    def test_card6_pthickfail_and_ncs(self):
        c6 = self.c["c6"]
        self.assertEqual(float(c6[20:40]), -1.0e-6)  # NUMFIP=1 → first IP
        self.assertEqual(c6[40:50].strip(), "2")     # NCS

    def test_inactive_sentinel_blank_fields_stay_zero(self):
        # A deck with ONLY EFFEPS active must leave every other criterion at 0
        # (GENE1's inactive value), not invent a threshold.
        card1 = _row("1", "0.0", "0.0", "0.0", "0.25", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        _, starter = _convert(_erosion_deck(card1, card2))
        c = _gene1_cards(starter)
        self.assertEqual(c["c1"][0:20].strip(), "0")    # Pmin inactive
        self.assertEqual(c["c1"][20:40].strip(), "0")   # Pmax inactive
        self.assertEqual(c["c1"][40:60].strip(), "0")   # SigP1 inactive
        self.assertEqual(c["c2"][40:60].strip(), "0")   # Sig_max inactive
        self.assertEqual(float(c["c3"][60:80]), 0.25)   # only Eps_eff active

    def test_no_active_criterion_emits_nothing_and_warns(self):
        card1 = _row("1", "0.0", "0.0", "0.0", "0.0", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        result, starter = _convert(_erosion_deck(card1, card2))
        self.assertNotIn("/FAIL/GENE1/1", starter)
        self.assertTrue(any("no active scalar criterion" in w
                            for w in result.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# NUMFIP → Pthickfail
# ─────────────────────────────────────────────────────────────────────────────

class Gene1NumfipTests(unittest.TestCase):
    def _emit(self, numfip: str, with_section: bool = False, nip: str = "5"):
        card1 = _row("1", "0.0", "0.0", "0.0", "0.2", "0.0", numfip, "1.0")
        card2 = _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        extra = ""
        if with_section:
            extra = "\n".join([
                "*SECTION_SHELL",
                _row("7", "2", "0.0", nip),
                _row("1.0"),
                "*PART",
                "shell part",
                _row("11", "7", "1"),
            ])
        result, starter = _convert(_erosion_deck(card1, card2, extra=extra))
        return result, _gene1_cards(starter)["c6"]

    def test_percent_form_direct(self):
        # -100 <= NUMFIP < 0 → Pthk = -(|NUMFIP|/100), exact, no NIP needed.
        _, c6 = self._emit("-50.0")
        self.assertEqual(float(c6[20:40]), -0.5)

    def test_default_numfip_first_ip(self):
        _, c6 = self._emit("1.0")
        self.assertEqual(float(c6[20:40]), -1.0e-6)

    def test_count_form_with_section_nip(self):
        # NUMFIP=3 count, NIP=5 → -3/5.
        _, c6 = self._emit("3.0", with_section=True, nip="5")
        self.assertAlmostEqual(float(c6[20:40]), -0.6)

    def test_count_over_100_form_with_section(self):
        # NUMFIP<-100 → (|NUMFIP|-100) IPs; -103 → 3 IPs, NIP=5 → -0.6.
        _, c6 = self._emit("-103.0", with_section=True, nip="5")
        self.assertAlmostEqual(float(c6[20:40]), -0.6)

    def test_count_form_without_section_warns(self):
        result, c6 = self._emit("3.0", with_section=False)
        self.assertEqual(c6[20:40].strip(), "0")     # left at default
        self.assertTrue(any("NUMFIP" in w and "NIP" in w
                            for w in result.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# EXCL, IDAM, curve forms, FAILTM sign
# ─────────────────────────────────────────────────────────────────────────────

class Gene1ExclIdamCurveTests(unittest.TestCase):
    def test_excl_excludes_matching_field(self):
        # EXCL=-999: SIGP1 set to -999 is inactive; SIGVM=400 is a live threshold.
        card1 = _row("1", "-999.0", "0.0", "0.0", "0.2", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "-999.0", "400.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        result, starter = _convert(_erosion_deck(card1, card2))
        c = _gene1_cards(starter)
        self.assertEqual(c["c1"][40:60].strip(), "0")   # SigP1 excluded
        self.assertEqual(float(c["c2"][40:60]), 400.0)  # Sig_max still active
        self.assertTrue(any("EXCL" in w for w in result.warnings))

    def test_sigvm_negative_is_load_curve(self):
        # SIGVM < 0 → |SIGVM| is a load-curve id → fct_IDsm, Sig_max = 1.0 scale.
        card1 = _row("1", "0.0", "0.0", "0.0", "0.2", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "0.0", "-77.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        _, starter = _convert(_erosion_deck(card1, card2))
        c = _gene1_cards(starter)
        self.assertEqual(c["c2"][0:10].strip(), "77")   # fct_IDsm
        self.assertEqual(float(c["c2"][40:60]), 1.0)    # Sig_max scale

    def test_mxeps_negative_is_load_curve(self):
        card1 = _row("1", "0.0", "0.0", "0.0", "0.2", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "0.0", "0.0", "-88.0", "0.0", "0.0", "0.0", "0.0")
        _, starter = _convert(_erosion_deck(card1, card2))
        c = _gene1_cards(starter)
        self.assertEqual(c["c3"][0:10].strip(), "88")   # fct_IDps
        self.assertEqual(float(c["c3"][40:60]), 1.0)    # Eps_max scale

    def test_failtm_negative_maps_abs_and_warns(self):
        card1 = _row("1", "0.0", "0.0", "0.0", "0.2", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "-0.002")
        result, starter = _convert(_erosion_deck(card1, card2))
        c = _gene1_cards(starter)
        self.assertEqual(float(c["c1"][60:80]), 0.002)  # Time_max = |FAILTM|
        self.assertTrue(any("FAILTM" in w for w in result.warnings))

    def test_idam_warns_but_scalar_criteria_still_convert(self):
        card1 = _row("1", "0.0", "0.0", "0.0", "0.2", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        card3 = _row("1")   # IDAM = 1 (GISSMO embedded)
        result, starter = _convert(_erosion_deck(card1, card2, card3))
        self.assertIn("/FAIL/GENE1/1", starter)         # EFFEPS still converts
        self.assertTrue(any("IDAM" in w and "GISSMO" in w
                            for w in result.warnings))


# ─────────────────────────────────────────────────────────────────────────────
# *MAT_123 : EPSTHIN → /FAIL/TAB1, EPSMAJ → /FAIL/FLD, NUMINT
# ─────────────────────────────────────────────────────────────────────────────

def _mat123_deck(card2: str, keyword: str = "*MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY",
                 fail: str = "0.0") -> str:
    #        MID   RHO      E        PR     SIGY     ETAN    FAIL   TDEL
    card1 = _row("1", "7.85E-9", "210000.0", "0.3", "300.0", "1000.0", fail, "0.0")
    return "\n".join([
        "*KEYWORD",
        keyword,
        card1,
        card2,
        "*CONTROL_TERMINATION",
        _row("1.0"),
        "*END",
        "",
    ])


class Mat123FailureTests(unittest.TestCase):
    #             C      P      LCSS   LCSR   VP     EPSTHIN EPSMAJ NUMINT
    def _c2(self, epsthin="0.0", epsmaj="0.0", numint="0.0"):
        return _row("0.0", "0.0", "0", "0", "0.0", epsthin, epsmaj, numint)

    def test_mat123_not_skipped(self):
        result, starter = _convert(_mat123_deck(self._c2(epsthin="0.1")))
        self.assertNotIn("MAT_MODIFIED_PIECEWISE_LINEAR_PLASTICITY",
                         result.skipped_keywords)
        self.assertIn("/MAT/LAW36/1", starter)

    def test_epsthin_maps_to_tab1_pthickfail(self):
        _, starter = _convert(_mat123_deck(self._c2(epsthin="0.1")))
        self.assertIn("/FAIL/TAB1/1", starter)
        body = starter.split("/FAIL/TAB1/1", 1)[1].splitlines()
        card1 = body[2]
        self.assertEqual(card1[0:10].strip(), "2")       # Ifail_sh
        self.assertEqual(float(card1[40:60]), 0.1)       # P_THICKFAIL = EPSTHIN
        # table1_ID (mandatory) present and non-zero on card 3.
        card3 = body[6]
        self.assertNotEqual(card3[0:10].strip(), "0")

    def test_epsthin_table_is_inert_plateau_funct(self):
        _, starter = _convert(_mat123_deck(self._c2(epsthin="0.1")))
        card3 = starter.split("/FAIL/TAB1/1", 1)[1].splitlines()[6]
        tabid = card3[0:10].strip()
        self.assertIn(f"/FUNCT/{tabid}", starter)
        # flat "never" plateau at 10.0 across the triaxiality bracket.
        self.assertIn("Auto_MAT123_thinfail", starter)

    def test_negative_epsthin_dropped_with_warn(self):
        result, starter = _convert(_mat123_deck(self._c2(epsthin="-0.1")))
        self.assertNotIn("/FAIL/TAB1/1", starter)
        self.assertTrue(any("EPSTHIN" in w for w in result.warnings))

    def test_epsmaj_maps_to_fld(self):
        _, starter = _convert(_mat123_deck(self._c2(epsmaj="0.25")))
        self.assertIn("/FAIL/FLD/1", starter)
        card1 = starter.split("/FAIL/FLD/1", 1)[1].splitlines()[2]
        fctid = card1[0:10].strip()
        self.assertNotEqual(fctid, "0")                  # fct_ID mandatory
        self.assertEqual(card1[10:20].strip(), "2")      # Ifail_sh
        self.assertEqual(card1[20:30].strip(), "1")      # I_marg (no card 2)
        self.assertIn(f"/FUNCT/{fctid}", starter)
        self.assertIn("Auto_MAT123_FLD", starter)

    def test_negative_epsmaj_uses_abs(self):
        # EPSMAJ < 0 is a filtering flag, magnitude unchanged → flat FLD at |v|.
        _, starter = _convert(_mat123_deck(self._c2(epsmaj="-0.25")))
        self.assertIn("/FAIL/FLD/1", starter)
        self.assertIn(f"{0.25:g}", starter.split("Auto_MAT123_FLD", 1)[1])

    def test_numint_warns_approximation(self):
        result, _ = _convert(_mat123_deck(self._c2(epsthin="0.1", numint="3.0")))
        self.assertTrue(any("NUMINT" in w for w in result.warnings))

    def test_numint_zero_no_warn(self):
        # NUMINT = 0 (ALL points) is exactly the JOHNSON Ifail_sh=2 rule → silent.
        result, _ = _convert(_mat123_deck(self._c2(epsthin="0.1"), fail="0.2"))
        self.assertFalse(any("NUMINT" in w for w in result.warnings))

    def test_fail_still_johnson_and_epsthin_tab1_coexist(self):
        # base plasticity unchanged: FAIL → /FAIL/JOHNSON; EPSTHIN adds /FAIL/TAB1.
        _, starter = _convert(_mat123_deck(self._c2(epsthin="0.1"), fail="0.2"))
        self.assertIn("/FAIL/JOHNSON/1", starter)
        self.assertIn("/FAIL/TAB1/1", starter)

    def test_both_tab1_and_fld_on_same_mat(self):
        _, starter = _convert(_mat123_deck(self._c2(epsthin="0.1", epsmaj="0.25")))
        self.assertIn("/FAIL/TAB1/1", starter)
        self.assertIn("/FAIL/FLD/1", starter)

    def test_damg_channel_emitted_for_tab1(self):
        # The damage channel goes to the ENGINE file (like GISSMO's /FAIL/TAB2).
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(_mat123_deck(self._c2(epsthin="0.1")))
        result = convert(path, write_log=False)
        with open(result.engine_path) as fh:
            engine = fh.read()
        self.assertIn("/ANIM/ELEM/DAMG", engine)

    def test_mat123_numeric_alias(self):
        result, starter = _convert(_mat123_deck(self._c2(epsthin="0.1"),
                                                keyword="*MAT_123"))
        self.assertNotIn("MAT_123", result.skipped_keywords)
        self.assertIn("/FAIL/TAB1/1", starter)


# ─────────────────────────────────────────────────────────────────────────────
# LOG_INTERPOLATION dispatch + F_smooth
# ─────────────────────────────────────────────────────────────────────────────

def _table_rate_deck(keyword: str) -> str:
    """MAT_024 whose LCSS is a *DEFINE_TABLE (two rate curves) → LAW36 rate
    family, so the F_smooth column is meaningful."""
    return "\n".join([
        "*KEYWORD",
        keyword,
        _row("1", "7.85E-9", "210000.0", "0.3", "300.0", "0.0", "0.0", "0.0"),
        _row("0.0", "0.0", "900", "0", "0.0"),
        "*DEFINE_TABLE",
        _row("900"),
        _row("0.001", "910"),
        _row("1000.0", "920"),
        "*DEFINE_CURVE",
        _row("910"),
        _row("0.0", "300.0"),
        _row("0.5", "400.0"),
        "*DEFINE_CURVE",
        _row("920"),
        _row("0.0", "350.0"),
        _row("0.5", "460.0"),
        "*CONTROL_TERMINATION",
        _row("1.0"),
        "*END",
        "",
    ])


class LogInterpolationTests(unittest.TestCase):
    def test_log_interpolation_alias_dispatched(self):
        result, starter = _convert(_table_rate_deck(
            "*MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION"))
        self.assertNotIn("MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION",
                         result.skipped_keywords)
        self.assertIn("/MAT/LAW36/1", starter)

    def test_log_interpolation_sets_fsmooth_2(self):
        _, starter = _convert(_table_rate_deck(
            "*MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION"))
        # N_funct F_smooth card: N_funct=2 (two rate curves), F_smooth=2.
        nf = starter.split("/MAT/LAW36/1", 1)[1].splitlines()[7]
        self.assertEqual(nf[0:10].strip(), "2")     # N_funct
        self.assertEqual(nf[10:20].strip(), "2")    # F_smooth = log interp

    def test_log_interpolation_2d_alias_dispatched(self):
        result, starter = _convert(_table_rate_deck(
            "*MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION_2D"))
        self.assertNotIn("MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION_2D",
                         result.skipped_keywords)
        nf = starter.split("/MAT/LAW36/1", 1)[1].splitlines()[7]
        self.assertEqual(nf[10:20].strip(), "2")    # F_smooth = log interp

    def test_plain_mat024_stays_linear_fsmooth_0(self):
        _, starter = _convert(_table_rate_deck("*MAT_PIECEWISE_LINEAR_PLASTICITY"))
        nf = starter.split("/MAT/LAW36/1", 1)[1].splitlines()[7]
        self.assertEqual(nf[0:10].strip(), "2")     # N_funct
        self.assertEqual(nf[10:20].strip(), "0")    # F_smooth linear (default)


# ─────────────────────────────────────────────────────────────────────────────
# No-regression: plain MAT_024 numeric alias & untouched failure paths
# ─────────────────────────────────────────────────────────────────────────────

class NoRegressionTests(unittest.TestCase):
    def test_mat024_numeric_alias_not_skipped(self):
        deck = "\n".join([
            "*KEYWORD",
            "*MAT_024",
            _row("1", "7.85E-9", "210000.0", "0.3", "300.0", "1000.0", "0.0", "0.0"),
            _row("0.0", "0.0", "0", "0", "0.0"),
            "*CONTROL_TERMINATION",
            _row("1.0"),
            "*END",
            "",
        ])
        result, starter = _convert(deck)
        self.assertNotIn("MAT_024", result.skipped_keywords)
        self.assertIn("/MAT/LAW36/1", starter)

    def test_plain_mat024_emits_no_tab1_or_fld(self):
        deck = "\n".join([
            "*KEYWORD",
            "*MAT_PIECEWISE_LINEAR_PLASTICITY",
            _row("1", "7.85E-9", "210000.0", "0.3", "300.0", "1000.0", "0.0", "0.0"),
            _row("0.0", "0.0", "0", "0", "0.0"),
            "*CONTROL_TERMINATION",
            _row("1.0"),
            "*END",
            "",
        ])
        _, starter = _convert(deck)
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertNotIn("/FAIL/TAB1/1", starter)
        self.assertNotIn("/FAIL/FLD/1", starter)

    def test_gissmo_still_tab2(self):
        deck = "\n".join([
            "*KEYWORD",
            "*MAT_ELASTIC",
            _row("1", "7.85E-9", "210000.0", "0.3"),
            "*MAT_ADD_DAMAGE_GISSMO",
            _row("1", "800", "0.0", "2.0", "0.5", "1.0"),
            "*DEFINE_CURVE",
            _row("800"),
            _row("0.0", "0.5"),
            _row("1.0", "0.5"),
            "*CONTROL_TERMINATION",
            _row("1.0"),
            "*END",
            "",
        ])
        result, starter = _convert(deck)
        self.assertNotIn("MAT_ADD_DAMAGE_GISSMO", result.skipped_keywords)
        self.assertIn("/FAIL/TAB2/1", starter)


# ─────────────────────────────────────────────────────────────────────────────
# Handler-level parsing (state, before the writer)
# ─────────────────────────────────────────────────────────────────────────────

class HandlerParseTests(unittest.TestCase):
    def test_erosion_full_card_parsed(self):
        card1 = _row("1", "0.0", "500.0", "-0.1", "0.2", "0.3", "2.0", "3.0")
        card2 = _row("300.0", "250.0", "400.0", "0.15", "0.08", "100.0", "5.0", "0.001")
        state = _dispatch(_erosion_deck(card1, card2))
        ero = state.mat_add_erosion[1]
        self.assertEqual(ero.sigth, 100.0)
        self.assertEqual(ero.impulse, 5.0)
        self.assertEqual(ero.failtm, 0.001)
        self.assertEqual(ero.ncs, 3.0)
        self.assertEqual(ero.numfip, 2.0)

    def test_excl_applied_in_handler(self):
        # A field equal to a non-zero EXCL is zeroed at parse time.
        card1 = _row("1", "-999.0", "0.0", "0.0", "0.2", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "-999.0", "400.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        ero = _dispatch(_erosion_deck(card1, card2)).mat_add_erosion[1]
        self.assertEqual(ero.sigp1, 0.0)      # == EXCL → inactive
        self.assertEqual(ero.sigvm, 400.0)    # kept

    def test_mat123_reads_extras_mat024_does_not(self):
        c2 = _row("0.0", "0.0", "0", "0", "0.0", "0.12", "0.25", "3.0")
        m123 = _dispatch(_mat123_deck(c2)).mat_plas_tab[1]
        self.assertEqual(m123.epsthin, 0.12)
        self.assertEqual(m123.epsmaj, 0.25)
        self.assertEqual(m123.numint, 3.0)
        # Same byte-layout under the plain MAT_024 keyword must NOT be read as
        # EPSTHIN/EPSMAJ/NUMINT (those slots are blank/different for MAT_024).
        m024 = _dispatch(_mat123_deck(
            c2, keyword="*MAT_PIECEWISE_LINEAR_PLASTICITY")).mat_plas_tab[1]
        self.assertEqual(m024.epsthin, 0.0)
        self.assertEqual(m024.epsmaj, 0.0)
        self.assertEqual(m024.numint, 0.0)

    def test_log_interp_flag_set_only_for_log_keyword(self):
        c2 = _row("0.0", "0.0", "0", "0", "0.0")
        plain = _dispatch(_mat123_deck(
            c2, keyword="*MAT_PIECEWISE_LINEAR_PLASTICITY")).mat_plas_tab[1]
        logk = _dispatch(_mat123_deck(
            c2, keyword="*MAT_PIECEWISE_LINEAR_PLASTICITY_LOG_INTERPOLATION")
        ).mat_plas_tab[1]
        self.assertFalse(plain.log_interp)
        self.assertTrue(logk.log_interp)


# ─────────────────────────────────────────────────────────────────────────────
# Coexistence, duplicate erosion, SIGP1<0 drop, NUMINT wording, auto-curve guard
# ─────────────────────────────────────────────────────────────────────────────

def _mat024_erosion_deck(fail="0.2", card1=None, card2=None):
    """A plastic *MAT_PIECEWISE_LINEAR_PLASTICITY (FAIL>0) that ALSO carries a
    *MAT_ADD_EROSION on the same mid — the two-different-/FAIL-cards-on-one-mat
    path (/FAIL/JOHNSON from the material + /FAIL/GENE1 from erosion)."""
    if card1 is None:
        card1 = _row("1", "0.0", "0.0", "0.0", "0.0", "0.0", "1.0", "1.0")
    if card2 is None:
        card2 = _row("0.0", "250.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0")
    return "\n".join([
        "*KEYWORD",
        "*MAT_PIECEWISE_LINEAR_PLASTICITY",
        _row("1", "7.85E-9", "210000.0", "0.3", "300.0", "1000.0", fail, "0.0"),
        _row("0.0", "0.0", "0", "0", "0.0"),
        "*MAT_ADD_EROSION",
        card1,
        card2,
        "*CONTROL_TERMINATION",
        _row("1.0"),
        "*END",
        "",
    ])


class Gene1CoexistenceTests(unittest.TestCase):
    def test_johnson_and_gene1_coexist_on_one_mat(self):
        # FAIL>0 → /FAIL/JOHNSON from the material; SIGP1 active → /FAIL/GENE1
        # from erosion. Both must appear on mid 1 (legal in OpenRadioss).
        _, starter = _convert(_mat024_erosion_deck(fail="0.2"))
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertIn("/FAIL/JOHNSON/1", starter)
        self.assertIn("/FAIL/GENE1/1", starter)

    def test_gene1_still_emitted_when_material_has_no_fail(self):
        _, starter = _convert(_mat024_erosion_deck(fail="0.0"))
        self.assertNotIn("/FAIL/JOHNSON/1", starter)
        self.assertIn("/FAIL/GENE1/1", starter)


class Gene1DuplicateErosionTests(unittest.TestCase):
    def _dup_deck(self):
        return "\n".join([
            "*KEYWORD",
            "*MAT_ELASTIC",
            _row("1", "1.05E-9", "1800.0", "0.4"),
            "*MAT_ADD_EROSION",                       # first: MXPRES=500
            _row("1", "0.0", "500.0", "0.0", "0.0", "0.0", "1.0", "1.0"),
            _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
            "*MAT_ADD_EROSION",                       # second: SIGP1=250
            _row("1", "0.0", "0.0", "0.0", "0.0", "0.0", "1.0", "1.0"),
            _row("0.0", "250.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"),
            "*CONTROL_TERMINATION",
            _row("1.0"),
            "*END",
            "",
        ])

    def test_duplicate_erosion_warns(self):
        result, _ = _convert(self._dup_deck())
        self.assertTrue(any("MID 1" in w and "overwrites" in w
                            for w in result.warnings))

    def test_duplicate_erosion_last_card_wins(self):
        _, starter = _convert(self._dup_deck())
        c = _gene1_cards(starter)
        self.assertEqual(float(c["c1"][40:60]), 250.0)   # SigP1 from 2nd card
        self.assertEqual(c["c1"][20:40].strip(), "0")    # Pmax (MXPRES) from 1st gone
        self.assertEqual(starter.count("/FAIL/GENE1/1"), 1)  # only one card


class Gene1Sigp1NegativeTests(unittest.TestCase):
    def test_sigp1_negative_dropped_not_spurious_threshold(self):
        # SIGP1<0 = load-curve form. SIGVM keeps GENE1 active; SigP1_max must be
        # left inactive (0), NOT emitted as a negative spurious threshold.
        card1 = _row("1", "0.0", "0.0", "0.0", "0.0", "0.0", "1.0", "1.0")
        card2 = _row("0.0", "-5.0", "400.0", "0.0", "0.0", "0.0", "0.0", "0.0")
        result, starter = _convert(_erosion_deck(card1, card2))
        c = _gene1_cards(starter)
        self.assertEqual(c["c1"][40:60].strip(), "0")     # SigP1_max dropped
        self.assertTrue(any("SIGP1" in w and "DROPPED" in w
                            for w in result.warnings))


class Mat123NumintWordingTests(unittest.TestCase):
    def test_numint_names_tab1_when_no_johnson(self):
        # FAIL=0, EPSTHIN>0 → /FAIL/TAB1 (no JOHNSON). Warning must name TAB1.
        result, _ = _convert(_mat123_deck(
            _row("0.0", "0.0", "0", "0", "0.0", "0.1", "0.0", "3.0")))
        w = next(x for x in result.warnings if "NUMINT" in x)
        self.assertIn("/FAIL/TAB1", w)
        self.assertNotIn("/FAIL/JOHNSON", w)

    def test_numint_dropped_when_no_fail_card(self):
        # FAIL=0, EPSTHIN=0, EPSMAJ=0, NUMINT=3 → no /FAIL card at all.
        result, starter = _convert(_mat123_deck(
            _row("0.0", "0.0", "0", "0", "0.0", "0.0", "0.0", "3.0")))
        self.assertNotIn("/FAIL/JOHNSON/1", starter)
        self.assertNotIn("/FAIL/TAB1/1", starter)
        self.assertNotIn("/FAIL/FLD/1", starter)
        w = next(x for x in result.warnings if "NUMINT" in x)
        self.assertIn("no /FAIL card", w)


class AutoCurveIdCollisionTests(unittest.TestCase):
    def test_next_curve_id_skips_existing_user_curve(self):
        from k2rad.state import Curve
        st = ConversionState()
        st.curves[90001] = Curve(lcid=90001, title="user", sfa=1.0, sfo=1.0,
                                 offa=0.0, offo=0.0, pts=[(0.0, 1.0)])
        fid = st.next_curve_id()
        self.assertNotEqual(fid, 90001)       # did not hand back the occupied id
        self.assertNotIn(fid, st.curves)      # and it is genuinely free

    def test_next_curve_id_is_noop_without_collision(self):
        # No user curve at the base → next_curve_id equals next_id, so it does
        # not shift auto-ids in the common case.
        self.assertEqual(ConversionState().next_curve_id(), 90001)


if __name__ == "__main__":
    unittest.main()
