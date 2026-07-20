"""``*SECTION_SHELL`` ELFORM -> ``/PROP/SHELL`` Ishell, as a USER CHOICE.

Issue #77: ``ELFORM=2`` (Belytschko-Tsay, the most common shell formulation
in LS-DYNA decks) fell through to ``Ishell=12`` (QBAT, FULLY integrated) with
no warning of any kind. LS-DYNA ELFORM=2 is UNDER-integrated, so the element's
integration class changed silently, and with ``/FAIL/JOHNSON Ifail_sh=2`` that
costs erosion: 4 Gauss x 2 through-thickness = 8 failure events to delete an
element instead of 2, measured at up to ~1.7x under-erosion.

The resolution is deliberately NOT "map ELFORM=2 to 24 and be done". QEPH
changes results on every existing shell deck, so it is offered as a choice
whose DEFAULT preserves what every previous conversion produced. Two things
therefore have to be true and are tested here:

1. the default output is unchanged — the goldens do not move;
2. the mapping is no longer SILENT either way, because "a default" and "a
   silent default" are different things and the second was the actual bug.

The blast radius of choosing QEPH is asserted rather than described, so the
number in the PR is checked by the suite: 4 ``/PROP/SHELL`` props across 3
golden fixtures flip 12 -> 24.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from k2rad.state import ConvertOptions
from k2rad.writer.common import (ISHELL_QBAT, ISHELL_QEPH, SHELL_FORMULATIONS,
                                 _elform_to_ishell)


class TestTheMapping(unittest.TestCase):

    def test_default_is_qbat_which_is_the_existing_behaviour(self):
        """ELFORM=2 -> 12 by default. This is the pre-#77 behaviour and the
        whole point of the default: no deck changes underfoot."""
        self.assertEqual(_elform_to_ishell(2, False), ISHELL_QBAT)

    def test_qeph_is_selectable_for_the_unmapped_elforms(self):
        self.assertEqual(
            _elform_to_ishell(2, False, ISHELL_QEPH), ISHELL_QEPH)

    def test_explicitly_mapped_elforms_are_qeph_either_way(self):
        """-16/9/20/21/26 have an unambiguous Radioss counterpart, so the
        option must not touch them -- it governs the FALLBACK only."""
        for elform in (-16, 9, 20, 21, 26):
            for default in (ISHELL_QBAT, ISHELL_QEPH):
                self.assertEqual(
                    _elform_to_ishell(elform, False, default), ISHELL_QEPH,
                    f"ELFORM={elform} must stay QEPH regardless of the option")

    def test_implicit_is_qeph_regardless_of_the_option(self):
        """Implicit predates this option and is not a choice being made."""
        for default in (ISHELL_QBAT, ISHELL_QEPH):
            self.assertEqual(
                _elform_to_ishell(2, True, default), ISHELL_QEPH)

    def test_under_integrated_ishell_is_not_offered(self):
        """1..4 would activate the hourglass path this repo documents as
        inert AND set inistate npg 4 -> 1, corrupting /INISHE. Both offered
        values keep npg at 4."""
        self.assertEqual(set(SHELL_FORMULATIONS.values()),
                         {ISHELL_QBAT, ISHELL_QEPH})
        for ishell in SHELL_FORMULATIONS.values():
            self.assertIn(ishell, (12, 24),
                          "inistate.py: npg = 4 if ishell in (12, 24) else 1")


class TestTheOptionResolves(unittest.TestCase):

    def test_options_default_to_qbat(self):
        self.assertEqual(ConvertOptions().shell_formulation, "qbat")
        self.assertEqual(ConvertOptions().shell_default_ishell, ISHELL_QBAT)

    def test_qeph_resolves(self):
        o = ConvertOptions(shell_formulation="qeph")
        self.assertEqual(o.shell_default_ishell, ISHELL_QEPH)

    def test_an_unknown_name_falls_back_to_the_safe_default(self):
        """convert() rejects a bad name outright; if one reaches the options
        object anyway it must degrade to the value that does not change
        anybody's results."""
        o = ConvertOptions(shell_formulation="nonsense")
        self.assertEqual(o.shell_default_ishell, ISHELL_QBAT)


class TestConvertRejectsABadName(unittest.TestCase):

    def test_convert_raises_and_names_both_choices(self):
        import k2rad
        with self.assertRaises(ValueError) as cm:
            k2rad.convert(__file__, shell_formulation="belytschko")
        msg = str(cm.exception)
        self.assertIn("qbat", msg)
        self.assertIn("qeph", msg)


# ── end-to-end: the blast radius, asserted rather than described ───────────

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

#: /PROP/SHELL props that flip 12 -> 24 when QEPH is chosen, per fixture.
#: implicit_qstat is 0 because implicit already returned 24 before this option
#: existed -- it is listed to prove the option does NOT disturb implicit.
EXPECTED_FLIPS = {
    "tied_weld": 2,
    "shell_explicit": 1,
    "rigid_contact": 1,
    "implicit_qstat": 0,
}


def _ishell_values(starter_text):
    """Every Ishell field of every /PROP/SHELL block in a starter deck.

    /PROP/SHELL/<id>
    <title>
    #   Ishell     Ismstr ...
         <ishell>  ...
    """
    out = []
    lines = starter_text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.strip().startswith("/PROP/SHELL/"):
            continue
        for j in range(i + 1, min(i + 6, len(lines))):
            body = lines[j].strip()
            if body.startswith("#") or not body:
                continue
            toks = body.split()
            if toks and toks[0].lstrip("-").isdigit():
                out.append(int(toks[0]))
                break
    return out


def _convert(stem, tmpdir, **kw):
    from k2rad import convert
    src = FIXTURES_DIR / f"{stem}.k"
    dst = os.path.join(tmpdir, f"{stem}.k")
    shutil.copy(src, dst)
    result = convert(dst, write_log=False, **kw)
    return Path(result.starter_path).read_text(), result


class TestGoldenBlastRadius(unittest.TestCase):
    """What choosing QEPH actually costs, in this repo's own fixtures.

    The PR states "4 props across 3 fixtures". That number is asserted here
    so it cannot quietly drift -- a claim about blast radius that nothing
    checks is exactly the kind of thing that goes stale.
    """

    def test_default_leaves_every_fixture_on_qbat(self):
        for stem, _ in EXPECTED_FLIPS.items():
            with self.subTest(stem=stem), tempfile.TemporaryDirectory() as tmp:
                starter, _ = _convert(stem, tmp)
                vals = _ishell_values(starter)
                if stem == "implicit_qstat":
                    self.assertTrue(all(v == ISHELL_QEPH for v in vals), vals)
                else:
                    self.assertTrue(all(v == ISHELL_QBAT for v in vals),
                                    f"{stem}: {vals}")

    def test_qeph_flips_exactly_the_documented_props(self):
        total = 0
        for stem, n_expected in EXPECTED_FLIPS.items():
            with self.subTest(stem=stem), tempfile.TemporaryDirectory() as tmp:
                base, _ = _convert(stem, tmp)
            with tempfile.TemporaryDirectory() as tmp:
                qeph, _ = _convert(stem, tmp, shell_formulation="qeph")
            a, b = _ishell_values(base), _ishell_values(qeph)
            self.assertEqual(len(a), len(b), f"{stem}: prop count changed")
            flips = sum(1 for x, y in zip(a, b)
                        if x == ISHELL_QBAT and y == ISHELL_QEPH)
            self.assertEqual(flips, n_expected,
                             f"{stem}: {a} -> {b}")
            self.assertEqual([y for x, y in zip(a, b) if x != y] or [ISHELL_QEPH],
                             [ISHELL_QEPH] * (flips or 1),
                             f"{stem}: a prop moved somewhere other than 24")
            total += flips
        self.assertEqual(total, 4, "the documented blast radius is 4 props")

    def test_implicit_is_untouched_by_the_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, _ = _convert("implicit_qstat", tmp)
        with tempfile.TemporaryDirectory() as tmp:
            qeph, _ = _convert("implicit_qstat", tmp,
                               shell_formulation="qeph")
        self.assertEqual(_ishell_values(base), _ishell_values(qeph))


class TestTheMappingIsNoLongerSilent(unittest.TestCase):
    """The ACTUAL defect in #77 was the absence of any warning.

    A default and a silent default are different things, so the log has to
    name the mapping whichever way the option is set.
    """

    def _warnings(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            _starter, result = _convert("shell_explicit", tmp, **kw)
        return " ".join(result.warnings)

    def test_default_says_what_it_did_and_that_there_is_a_choice(self):
        w = self._warnings()
        self.assertIn("Ishell=12", w)
        self.assertIn("qeph", w)          # tells the user the alternative
        self.assertIn("under-erosion", w)

    def test_choosing_qeph_says_results_will_differ(self):
        w = self._warnings(shell_formulation="qeph")
        self.assertIn("Ishell=24", w)
        self.assertIn("results WILL differ", w)


if __name__ == "__main__":
    unittest.main()
