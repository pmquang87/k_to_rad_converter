"""*CONTROL_TIMESTEP TSSFAC -> engine /DT Tsca.

Scope note, because the surrounding area is easy to misread: DT2MS < 0 already
worked before this module existed -- it emits /DT/NODA/CST/0 (or /DT/AMS under
--ams) with Tsca taken from TSSFAC. The defect fixed here is narrower: when
DT2MS >= 0 there was no mass scaling to hang TSSFAC off, so TSSFAC was dropped
entirely and no /DT card of any kind reached the engine deck. The user's safety
factor vanished and OpenRadioss fell back to its own default.

The DT2MS < 0 behaviour is pinned below so it cannot regress, and so is the
must-not-change case: a deck with no *CONTROL_TIMESTEP at all still gets no /DT.
"""

import os
import tempfile
import unittest
from pathlib import Path

from k2rad import convert


# TSSFAC = 0.8, DT2MS = 0 -- the case that silently lost the safety factor.
TSSFAC_K = """*KEYWORD
*CONTROL_TIMESTEP
$#  dtinit    tssfac      isdo    tslimt     dt2ms
       0.0       0.8         0       0.0       0.0
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
*CONTROL_TERMINATION
       1.0
*END
"""

# Same model with no *CONTROL_TIMESTEP block at all.
NO_TIMESTEP_K = """*KEYWORD
*MAT_ELASTIC
         1  7.85E-9  210000.0       0.3
*CONTROL_TERMINATION
       1.0
*END
"""


class _EngineDeckMixin:
    def _convert(self, deck, **opts):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.k")
        with open(path, "w") as fh:
            fh.write(deck)
        result = convert(path, **opts)
        return result, Path(result.engine_path).read_text()

    def _dt_card(self, engine):
        """The bare '/DT' card as an exact line, plus its value row.

        Matched on whole lines, never by substring: '/DT' is a prefix of
        '/DT/NODA/CST/0', '/DT/AMS' and every /ANIM/NODA/DT sibling, so a
        substring test here would pass for the wrong reason.
        """
        lines = engine.splitlines()
        if "/DT" not in lines:
            return None
        return lines[lines.index("/DT") + 1]


class TssfacScaleTests(_EngineDeckMixin, unittest.TestCase):
    """DT2MS >= 0: TSSFAC must survive conversion as /DT Tsca."""

    def test_tssfac_emits_bare_dt_card(self):
        _r, engine = self._convert(TSSFAC_K)
        self.assertIn("/DT", engine.splitlines(),
                      "TSSFAC=0.8 with DT2MS=0 produced no /DT card -- the "
                      "safety factor was dropped")

    def test_tsca_is_tssfac_and_tmin_is_zero(self):
        # Tsca = TSSFAC verbatim. Tmin = 0 (no lower bound) is deliberate:
        # /DT's Tmin is a run-stop threshold and LS-DYNA's TSLIMT is a field
        # this converter does not parse, so nothing is invented here.
        _r, engine = self._convert(TSSFAC_K)
        row = self._dt_card(engine)
        self.assertIsNotNone(row)
        tsca, tmin = row.split()
        self.assertEqual(float(tsca), 0.8)
        self.assertEqual(float(tmin), 0.0)

    def test_warns_that_tssfac_was_carried_over(self):
        result, _e = self._convert(TSSFAC_K)
        self.assertTrue(
            any("TSSFAC" in w and "/DT" in w for w in result.warnings),
            "carrying TSSFAC across must be reported, not done silently")

    def test_tssfac_zero_emits_nothing(self):
        # TSSFAC=0 is LS-DYNA's "use my default" (0.9), which is also the
        # OpenRadioss /DT default -- there is nothing to carry across.
        deck = TSSFAC_K.replace("       0.8", "       0.0")
        _r, engine = self._convert(deck)
        self.assertNotIn("/DT", engine.splitlines())

    def test_positive_dt2ms_still_gets_tssfac(self):
        # DT2MS > 0 IS mass scaling in LS-DYNA (quasi-static / time-history
        # runs, Vol I R17 p.12-585), but k2rad does not convert it on a 3-D
        # deck (ROADMAP, round 9's NOT list, entry 5 "Positive DT2MS on 3-D
        # decks"), so the run gets no mass scaling - TSSFAC still applies.
        deck = TSSFAC_K.replace("       0.0\n*MAT", "    1.0E-6\n*MAT")
        _r, engine = self._convert(deck)
        row = self._dt_card(engine)
        self.assertIsNotNone(row)
        self.assertEqual(float(row.split()[0]), 0.8)


class NoControlTimestepUnchangedTests(_EngineDeckMixin, unittest.TestCase):
    """The regression that matters most: a deck with no *CONTROL_TIMESTEP must
    convert exactly as it did before, i.e. with no time-step card at all."""

    def test_no_dt_card_of_any_kind(self):
        _r, engine = self._convert(NO_TIMESTEP_K)
        self.assertNotIn("/DT", engine.splitlines())
        self.assertNotIn("/DT/NODA/CST", engine)
        self.assertNotIn("/DT/AMS", engine)

    def test_no_timestep_warning(self):
        result, _e = self._convert(NO_TIMESTEP_K)
        self.assertEqual(
            [w for w in result.warnings if "TSSFAC" in w or "DT2MS" in w], [])


class MassScalingPathUnchangedTests(_EngineDeckMixin, unittest.TestCase):
    """DT2MS < 0 already worked. Pin it so this change does not disturb it."""

    def _deck(self):
        return TSSFAC_K.replace("       0.0\n*MAT", "-1.1120E-6\n*MAT")

    def test_still_emits_noda_cst_with_tssfac_as_tsca(self):
        # R14 round 10, A4: Tmin = TSSFAC x |DT2MS| = 0.8 x 1.112e-6 =
        # 8.896e-7 by default; --no-dt2ms-tssfac-product keeps |DT2MS|
        for kw, want in (({}, 8.896e-7),
                         ({"dt2ms_tssfac_product": False}, 1.112e-6)):
            with self.subTest(**kw):
                _r, engine = self._convert(self._deck(), **kw)
                self.assertIn("/DT/NODA/CST/0", engine)
                row = engine.split("/DT/NODA/CST/0", 1)[1].splitlines()[1]
                tsca, tmin = row.split()
                self.assertEqual(float(tsca), 0.8)
                self.assertAlmostEqual(float(tmin), want, places=12)

    def test_mass_scaling_deck_gets_no_extra_bare_dt(self):
        # The two paths are exclusive -- /DT/NODA/CST already carries Tsca.
        _r, engine = self._convert(self._deck())
        self.assertNotIn("/DT", engine.splitlines())

    def test_ams_path_gets_no_extra_bare_dt(self):
        _r, engine = self._convert(self._deck(), ams=True)
        self.assertIn("/DT/AMS", engine)
        self.assertNotIn("/DT", engine.splitlines())


class Dt2msTssfacProductTests(_EngineDeckMixin, unittest.TestCase):
    """--dt2ms-tssfac-product (the CardStack batch, K-41; the DEFAULT since
    R14 round 10, A4). For DT2MS < 0 LS-DYNA makes TSSFAC x |DT2MS| the
    minimum step (Vol I R17 p.12-585); /DT/NODA/CST writes that product as
    Tmin, --no-dt2ms-tssfac-product writes |DT2MS| (a step 1/TSSFAC
    larger). /DT/AMS keeps |DT2MS| on both arms, as dyna2rad writes it
    (convertcards.cxx:233-234; D12)."""

    def _deck(self, tssfac="       0.9"):
        return (TSSFAC_K.replace("       0.8", tssfac)
                .replace("       0.0\n*MAT", "   -1.0E-6\n*MAT"))

    def _cells(self, engine, card):
        row = engine.split(card, 1)[1].splitlines()[1]
        return [float(v) for v in row.split()]

    def test_flag_holds_tmin_at_the_product(self):
        _r, engine = self._convert(self._deck(), dt2ms_tssfac_product=True)
        tsca, tmin = self._cells(engine, "/DT/NODA/CST/0")
        self.assertEqual(tsca, 0.9)
        self.assertAlmostEqual(tmin, 9.0e-7, places=15)

    def test_default_holds_tmin_at_the_product(self):
        _r, engine = self._convert(self._deck())
        tsca, tmin = self._cells(engine, "/DT/NODA/CST/0")
        self.assertEqual(tsca, 0.9)
        self.assertAlmostEqual(tmin, 9.0e-7, places=15)

    def test_the_opt_out_keeps_tmin_at_dt2ms(self):
        _r, engine = self._convert(self._deck(), dt2ms_tssfac_product=False)
        tsca, tmin = self._cells(engine, "/DT/NODA/CST/0")
        self.assertEqual(tsca, 0.9)
        self.assertAlmostEqual(tmin, 1.0e-6, places=15)

    def test_ams_keeps_tmin_at_dt2ms_on_both_arms(self):
        # Tsca stays AMS's 0.67; Tmin is |DT2MS| whatever the lever (D12)
        for flag in (True, False):
            with self.subTest(flag=flag):
                _r, engine = self._convert(self._deck(), ams=True,
                                           dt2ms_tssfac_product=flag)
                tsca, tmin = self._cells(engine, "/DT/AMS")
                self.assertEqual(tsca, 0.67)
                self.assertAlmostEqual(tmin, 1.0e-6, places=15)

    def test_blank_tssfac_takes_0_9(self):
        _r, engine = self._convert(self._deck(tssfac="       0.0"),
                                   dt2ms_tssfac_product=True)
        tsca, tmin = self._cells(engine, "/DT/NODA/CST/0")
        self.assertEqual(tsca, 0.9)
        self.assertAlmostEqual(tmin, 9.0e-7, places=15)

    def test_negative_tssfac_curve_takes_0_9(self):
        # TSSFAC < 0 names a load curve of the scale factor, which is not
        # converted: Tsca 0.9 and Tmin 0.9 x |DT2MS| by default (round 10,
        # A4), |DT2MS| under --no-dt2ms-tssfac-product; /DT/AMS: Tsca 0.67
        # and |DT2MS| on both arms (D12) - never the negative curve id as a
        # factor. Fix round: no test had a TSSFAC < 0, so the branch could
        # change the DEFAULT Tsca unseen.
        for flag, ams, card, want_tsca, want_tmin in (
                (False, False, "/DT/NODA/CST/0", 0.9, 1.0e-6),
                (True, False, "/DT/NODA/CST/0", 0.9, 9.0e-7),
                (False, True, "/DT/AMS", 0.67, 1.0e-6),
                (True, True, "/DT/AMS", 0.67, 1.0e-6)):
            with self.subTest(flag=flag, ams=ams):
                _r, engine = self._convert(self._deck(tssfac="      -3.0"),
                                           dt2ms_tssfac_product=flag,
                                           ams=ams)
                tsca, tmin = self._cells(engine, card)
                self.assertEqual(tsca, want_tsca)
                self.assertAlmostEqual(tmin, want_tmin, places=15)


if __name__ == "__main__":
    unittest.main()
