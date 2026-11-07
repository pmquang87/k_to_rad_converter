"""``/DT/<elem>/DEL`` — the time-step deletion floor, and its two consents.

Issue #78. There was no ``/DT/.../DEL`` emitter anywhere in the package, and
``*CONTROL_TIMESTEP`` fields 3 (``TSLIMT``) and 6 (``ERODE``) were sliced off
the card and dropped on the floor. A user who wrote ``ERODE=1`` — explicitly
asking for elements to be deleted below a time-step floor — got a converted
deck with no such behaviour and no warning that the request had gone missing.

The card is not a neutral fidelity improvement: it **deletes elements**, so a
floor k2rad invented would silently cost the model mass and stiffness the
LS-DYNA original kept. Hence exactly two ways in, both explicit:

* the DECK asks — ``ERODE=1`` **and** ``TSLIMT>0``;
* the USER asks — ``--dt-del <seconds>`` / ``convert(dt_del=...)``.

Nothing else emits it. These tests pin both routes, the refusal in every other
case, and the interaction with mass scaling that #78 called the crux.

R14 round 10 (A11): the deck route is GONE by default. TSLIMT is LS-DYNA's
shell minimum-step ASSIGNMENT (the moduli of four plasticity laws are
modified, Vol I R17 p.12-584 / 12-585), not an erosion floor, and ERODE erodes
below tsmin = DTMIN x dtstart of *CONTROL_TERMINATION (p.12-558, p.12-590
Remark 6), which k2rad cannot compute; both are named in ONE
recognized-not-emitted record instead. ``--no-erode-tsmin-rule`` restores the
deck route; the user route is unchanged.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from k2rad import convert
from k2rad.state import ConversionState, ControlTimestep, ConvertOptions
from k2rad.writer.assembly import _make_engine_dt_deletion

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _state(dt2ms=0.0, tslimt=0.0, erode=0, dt_del=None, ams=False,
           tssfac=0.9, erode_tsmin_rule=True):
    st = ConversionState()
    st.options = ConvertOptions(ams=ams, dt_del=dt_del,
                                erode_tsmin_rule=erode_tsmin_rule)
    st.ctrl_timestep = ControlTimestep(0.0, tssfac, dt2ms, tslimt, erode)
    return st


#: the ed52c93 deck route, restored by --no-erode-tsmin-rule (round 10, A11)
_LEGACY = dict(erode_tsmin_rule=False)


def _cards(lines):
    return [ln for ln in lines if ln.startswith("/DT/")]


class TestNothingIsEmittedUninvited(unittest.TestCase):
    """The default has to be silence, because the card deletes elements."""

    def test_a_plain_deck_gets_no_deletion_floor(self):
        self.assertEqual(_make_engine_dt_deletion(_state()), [])

    def test_mass_scaling_alone_does_not_imply_deletion(self):
        self.assertEqual(_make_engine_dt_deletion(_state(dt2ms=-1e-7)), [])

    def test_erode_without_a_threshold_emits_nothing(self):
        st = _state(erode=1, tslimt=0.0)
        self.assertEqual(_make_engine_dt_deletion(st), [])

    def test_threshold_without_erode_emits_nothing(self):
        """TSLIMT alone is a step LIMIT in LS-DYNA, not permission to delete."""
        st = _state(erode=0, tslimt=3.5e-8)
        self.assertEqual(_make_engine_dt_deletion(st), [])

    def test_a_half_request_is_reported_not_dropped(self):
        """The original defect was the SILENT drop, so a partial request has
        to surface even though nothing is emitted for it."""
        st = _state(erode=1, tslimt=0.0)
        _make_engine_dt_deletion(st)
        kws = [kw for kw, _reason in st.recognized_not_emitted]
        self.assertIn("CONTROL_TIMESTEP", kws)
        reason = dict(st.recognized_not_emitted)["CONTROL_TIMESTEP"]
        self.assertIn("ERODE", reason)
        self.assertIn("--dt-del", reason)


class TestTheDeckAsking(unittest.TestCase):
    """The ed52c93 deck route, now the --no-erode-tsmin-rule arm."""

    def test_erode_plus_tslimt_emits_all_three_families(self):
        st = _state(erode=1, tslimt=3.5e-8, **_LEGACY)
        cards = _cards(_make_engine_dt_deletion(st))
        self.assertEqual(cards, ["/DT/SHELL/DEL", "/DT/SH_3N/DEL",
                                 "/DT/BRICK/DEL"])

    def test_sh3n_is_not_forgotten(self):
        """3-node shells are a SEPARATE family in Radioss: a deck whose ESORT
        generates triangles would otherwise leave them with no floor."""
        st = _state(erode=1, tslimt=3.5e-8, **_LEGACY)
        self.assertIn("/DT/SH_3N/DEL", _make_engine_dt_deletion(st))

    def test_tmin_is_tslimt_and_tsca_is_tssfac(self):
        st = _state(erode=1, tslimt=3.5e-8, tssfac=0.8, **_LEGACY)
        lines = _make_engine_dt_deletion(st)
        data = lines[lines.index("/DT/SHELL/DEL") + 1]
        self.assertAlmostEqual(float(data.split()[0]), 0.8)
        self.assertAlmostEqual(float(data.split()[1]), 3.5e-8)

    def test_the_deletion_is_warned_about(self):
        st = _state(erode=1, tslimt=3.5e-8, **_LEGACY)
        _make_engine_dt_deletion(st)
        w = " ".join(st.warnings)
        self.assertIn("DELETE", w)
        self.assertIn("removes mass and stiffness", w)


class TestTheDeckAskingRound10(unittest.TestCase):
    """R14 round 10, A11 (the default): ERODE 1 + TSLIMT > 0 is no deletion
    floor; the one record names what each field is in LS-DYNA."""

    def _rne(self, st):
        return dict(st.recognized_not_emitted).get("CONTROL_TIMESTEP", "")

    def test_erode_plus_tslimt_emits_no_floor(self):
        for kw in ({}, {"dt2ms": -1e-7}):
            with self.subTest(**kw):
                st = _state(erode=1, tslimt=3.5e-8, **kw)
                self.assertEqual(_make_engine_dt_deletion(st), [])
                self.assertEqual(st.warnings, [])

    def test_one_record_names_tslimt_and_erode(self):
        st = _state(erode=1, tslimt=3.5e-8)
        _make_engine_dt_deletion(st)
        why = self._rne(st)
        for needle in ("TSLIMT=3.5e-08", "MODULI (not the masses)",
                       "*MAT_PIECEWISE_LINEAR_PLASTICITY",
                       "p.12-584 / 12-585", "NOT an erosion floor",
                       "--no-erode-tsmin-rule", "ERODE=1",
                       "solid and thick-shell elements",
                       "tsmin = DTMIN x dtstart", "p.12-558",
                       "DTMIN is 0 here, so LS-DYNA has no tsmin",
                       "--dt-del"):
            with self.subTest(needle=needle):
                self.assertIn(needle, why)

    def test_the_digits_and_dtmin_are_read(self):
        from k2rad.state import ControlTermination
        st = _state(erode=111, tslimt=0.0)
        st.ctrl_termination = ControlTermination(1.0e-3, dtmin=0.3)
        _make_engine_dt_deletion(st)
        why = self._rne(st)
        self.assertIn("ERODE=111: LS-DYNA erodes the solid and thick-shell "
                      "elements (SPH particles are deactivated), the shell "
                      "elements and the beam elements whose time step", why)
        self.assertIn("DTMIN=0.3 here", why)
        self.assertNotIn("TSLIMT", why)

    def test_the_dt2ms_interplay_of_tslimt_is_named(self):
        for tslimt, needle in ((3.5e-8, "a positive TSLIMT is disabled, "
                                "TSLIMT defaulting to 1e-18"),
                               (-3.5e-8, "a negative TSLIMT is applied "
                                "before the mass is scaled")):
            with self.subTest(tslimt=tslimt):
                st = _state(tslimt=tslimt, dt2ms=-1e-7)
                _make_engine_dt_deletion(st)
                self.assertIn(needle, self._rne(st))


class TestTheUserAsking(unittest.TestCase):

    def test_dt_del_emits_on_a_deck_that_never_asked(self):
        st = _state(dt_del=2e-8)
        lines = _make_engine_dt_deletion(st)
        self.assertEqual(len(_cards(lines)), 3)
        data = lines[lines.index("/DT/SHELL/DEL") + 1]
        self.assertAlmostEqual(float(data.split()[1]), 2e-8)

    def test_dt_del_overrides_tslimt(self):
        """An explicit number beats the deck's, and the log says which won."""
        st = _state(erode=1, tslimt=3.5e-8, dt_del=9e-9)
        lines = _make_engine_dt_deletion(st)
        data = lines[lines.index("/DT/SHELL/DEL") + 1]
        self.assertAlmostEqual(float(data.split()[1]), 9e-9)
        self.assertIn("--dt-del", " ".join(st.warnings))

    def test_a_non_positive_value_emits_nothing(self):
        for bad in (0.0, -1e-8):
            self.assertEqual(_make_engine_dt_deletion(_state(dt_del=bad)), [])


class TestOrderingAgainstMassScaling(unittest.TestCase):
    """#78 called this the crux and feared one card would be dead config.

    Verified in engine/source/elements/shell/coque/cdt3.F:
      * element step = DTFAC1(3)*ALDT/SSP (cdt3.F:111-115) — length over sound
        speed, NO mass term, so nodal scaling cannot lift an element off the
        threshold;
      * the IDTMIN(3)==2 deletion block (cdt3.F:146) runs BEFORE the
        IF (NODADT/=0...) RETURN at cdt3.F:200.
    So the two coexist. Under AMS they do not, and that is warned about
    separately.
    """

    def test_nodal_scaling_and_deletion_coexist_and_the_log_says_why(self):
        for kw in ({"dt_del": 3.5e-8},
                   dict(erode=1, tslimt=3.5e-8, **_LEGACY)):
            with self.subTest(**kw):
                st = _state(dt2ms=-1e-7, **kw)
                self.assertEqual(len(_cards(_make_engine_dt_deletion(st))), 3)
                w = " ".join(st.warnings)
                self.assertIn("cdt3.F:146", w)
                self.assertIn("does NOT make this floor unreachable", w)

    def test_ams_is_flagged_as_a_different_interaction(self):
        st = _state(dt2ms=-1e-7, dt_del=3.5e-8, ams=True)
        _make_engine_dt_deletion(st)
        w = " ".join(st.warnings)
        self.assertIn("--ams", w)
        self.assertIn("SQRT(mass/stiffness)", w)
        self.assertNotIn("does NOT make this floor unreachable", w)


class TestImplicitAndModalAreExempt(unittest.TestCase):
    """No CFL step to floor."""

    def test_implicit(self):
        st = _state(erode=1, tslimt=3.5e-8)
        st.is_implicit = True
        self.assertEqual(_make_engine_dt_deletion(st), [])

    def test_modal(self):
        st = _state(erode=1, tslimt=3.5e-8)
        st.is_modal = True
        self.assertEqual(_make_engine_dt_deletion(st), [])


class TestEndToEnd(unittest.TestCase):

    def _engine(self, stem, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            src = FIXTURES_DIR / f"{stem}.k"
            dst = os.path.join(tmp, f"{stem}.k")
            shutil.copy(src, dst)
            res = convert(dst, write_log=False, **kw)
            return Path(res.engine_path).read_text()

    def test_default_engine_deck_has_no_del_card(self):
        self.assertNotIn("/DEL", self._engine("shell_explicit"))

    def test_dt_del_reaches_the_engine_deck(self):
        engine = self._engine("shell_explicit", dt_del=3.5e-8)
        for kind in ("SHELL", "SH_3N", "BRICK"):
            self.assertIn(f"/DT/{kind}/DEL", engine)

    def test_the_del_card_does_not_displace_the_timestep_card(self):
        """/DT/NODA/CST and /DT/.../DEL are different cards and both belong in
        the deck; matching '/DT' by substring would hide one behind the
        other."""
        engine = self._engine("shell_explicit", dt_del=3.5e-8)
        lines = [ln.strip() for ln in engine.splitlines()]
        self.assertIn("/DT/SHELL/DEL", lines)


if __name__ == "__main__":
    unittest.main()
