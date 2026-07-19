"""Tests for requested-output losses: a *DATABASE_* card the converter accepts
but for which it emits nothing, while reporting success.

Three defects, one shape:
  A. *CONSTRAINED_NODAL_RIGID_BODY_SPC + *DATABASE_SPCFORC produced no reaction
     history. The CNRB _SPC path writes its /BCS inline (writer/rbody.py) and
     never registered it, while the reaction consumers gate on the
     *BOUNDARY_SPC-only state.bcs_spcs list — so the deck got a /BCS and a
     warning claiming no node was SPC-constrained.
  B. *DATABASE_RCFORC was a no-op: the dt was stored and referenced nowhere, so
     it neither reached the /TFILE frequency nor produced a /TH/INTER.
  C. *DATABASE_MATSUM / NODOUT / ELOUT / GLSTAT have handlers, so they never
     reach state.skipped_keywords and "skipped: 0 unsupported keyword(s)" read
     as "everything converted". They are now reported as recognized-but-not-
     emitted.

Kept in a separate module from tests/test_converter.py, following the
tests/test_hourglass.py harness so the additions do not collide with other
in-flight work.
"""

import os
import tempfile
import unittest

from k2rad import convert


def _convert(deck: str, **opts):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **opts)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


# ── Decks ───────────────────────────────────────────────────────────────────

_MESH = """*KEYWORD
*NODE
         1             0.0             0.0             0.0
         2            10.0             0.0             0.0
         3            10.0            10.0             0.0
         4             0.0            10.0             0.0
         5            20.0             0.0             0.0
         6            20.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       2       5       6       3
*PART
plate
         1         1         1
*SECTION_SHELL
         1        16
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1     7.85E-9  210000.0       0.3
*SET_NODE_LIST
       100
         1         4
"""

_TERM = """*CONTROL_TERMINATION
     0.001
*END
"""

# *CONSTRAINED_NODAL_RIGID_BODY_SPC, CMO=1 CON1=7 CON2=7 — all 6 DOF fixed on
# the CNRB master node. The deck has NO *BOUNDARY_SPC at all: the only SPC in
# it comes from the _SPC option, which is precisely the case that was lost.
_CNRB_SPC = """*CONSTRAINED_NODAL_RIGID_BODY_SPC
       900         0       100         0
         1         7         7         0
*DATABASE_SPCFORC
   1.0E-05
"""

_CONTACT = """*CONTACT_AUTOMATIC_SINGLE_SURFACE
         0         0         0         0
       0.2       0.2
"""


class TestCnrbSpcReactionOutput(unittest.TestCase):
    """A. *CONSTRAINED_NODAL_RIGID_BODY_SPC is an SPC for reaction purposes."""

    def setUp(self):
        self.result, self.starter, self.engine = _convert(
            _MESH + _CNRB_SPC + _TERM)

    def test_th_node_reaction_block_is_emitted(self):
        """Before the fix no /TH/NODE was emitted at all for this deck."""
        self.assertIn("/TH/NODE", self.starter,
                      "*DATABASE_SPCFORC on a CNRB _SPC deck emitted no "
                      "/TH/NODE — the requested reaction history is lost")
        self.assertIn("TH_spc_reactions", self.starter)

    def test_reaction_channels_present(self):
        for var in ("REACX", "REACY", "REACZ"):
            self.assertIn(var, self.starter)

    def test_rotational_channels_follow_the_rot_mask(self):
        """CON2=7 fixes all three rotations, so the moment channels apply."""
        for var in ("REACXX", "REACYY", "REACZZ"):
            self.assertIn(var, self.starter,
                          "CNRB _SPC rot mask 111 must gate REAC*X/Y/Z on")

    def test_reaction_is_on_the_rbody_master_node(self):
        """The /BCS acts on the master node, so that is the spcforc node.

        Node 7 is the synthesized CNRB master (the mesh has nodes 1-6). This is
        the same node the plain-CNRB + *BOUNDARY_SPC_SET control deck reports.
        """
        block = self.starter[self.starter.index("TH_spc_reactions"):]
        block = block[:block.index("/END")]
        nodes = [ln.strip() for ln in block.splitlines()
                 if ln.strip().isdigit()]
        self.assertEqual(nodes, ["7"])

    def test_false_no_boundary_spc_warning_is_gone(self):
        """The old warning denied the constraint the converter itself wrote."""
        for w in self.result.warnings:
            self.assertNotIn("no node is SPC-constrained", w)
            self.assertNotIn("the deck has no *BOUNDARY_SPC", w)

    def test_bcs_card_text_is_unchanged(self):
        """Registering the constraint must not alter the emitted /BCS."""
        self.assertIn("/BCS/90003", self.starter)
        self.assertIn("BC_cnrb_900", self.starter)
        self.assertIn("   111 111         0     90002", self.starter)

    def test_bcs_is_emitted_exactly_once(self):
        """Guard the trap: routing the CNRB _SPC through state.bcs_spcs would
        make _make_bcs emit a second, duplicate /BCS for the same constraint."""
        self.assertEqual(self.starter.count("/BCS/"), 1)
        self.assertEqual(self.starter.count("BC_cnrb_900"), 1)

    def test_engine_reaction_vectors_enabled(self):
        self.assertIn("/ANIM/VECT/FREAC", self.engine)
        self.assertIn("/ANIM/VECT/MREAC", self.engine)

    def test_deck_with_no_spc_at_all_still_warns(self):
        """The warning must keep firing when it is actually true."""
        result, starter, _ = _convert(
            _MESH + "*DATABASE_SPCFORC\n   1.0E-05\n" + _TERM)
        self.assertNotIn("TH_spc_reactions", starter)
        self.assertTrue(
            any("SPC-constrains no node" in w for w in result.warnings),
            "a deck with no SPC of any kind must still be told why it got "
            f"no reaction output; warnings were {result.warnings}")


class TestRcforcInterfaceOutput(unittest.TestCase):
    """B. *DATABASE_RCFORC was stored and never used."""

    def test_rcforc_drives_the_tfile_frequency(self):
        """Tier 1: rcforc was absent from the /TFILE dt chain, so a deck whose
        only output request was rcforc silently got the 1e-3 fallback."""
        _, _, engine = _convert(
            _MESH + "*DATABASE_RCFORC\n   2.5E-06\n" + _CONTACT + _TERM)
        tfile = engine[engine.index("/TFILE"):].splitlines()[1].strip()
        self.assertEqual(tfile, "2.5E-06",
                         "*DATABASE_RCFORC dt must set the /TFILE frequency")

    def test_rcforc_emits_th_inter_over_converted_contacts(self):
        """Tier 2: rcforc is the per-contact force resultant, which is exactly
        what a /TH/INTER channel carries."""
        _, starter, _ = _convert(
            _MESH + "*DATABASE_RCFORC\n   1.0E-05\n" + _CONTACT + _TERM)
        self.assertIn("/TH/INTER", starter,
                      "*DATABASE_RCFORC with a converted *CONTACT emitted no "
                      "/TH/INTER — the requested contact forces are lost")
        self.assertIn("TH_interface_forces", starter)

    def test_rcforc_reports_the_mapping(self):
        result, _, _ = _convert(
            _MESH + "*DATABASE_RCFORC\n   1.0E-05\n" + _CONTACT + _TERM)
        self.assertTrue(
            any("*DATABASE_RCFORC" in w and "/TH/INTER" in w
                for w in result.warnings),
            f"the rcforc -> /TH/INTER mapping must be stated; got "
            f"{result.warnings}")

    def test_rcforc_without_contact_warns_instead_of_silence(self):
        result, starter, _ = _convert(
            _MESH + "*DATABASE_RCFORC\n   1.0E-05\n" + _TERM)
        self.assertNotIn("/TH/INTER", starter)
        self.assertTrue(
            any("*DATABASE_RCFORC" in w and "no *CONTACT" in w
                for w in result.warnings),
            f"got {result.warnings}")

    def test_rcforc_does_not_disturb_a_deck_without_it(self):
        _, starter, _ = _convert(_MESH + _CONTACT + _TERM)
        self.assertNotIn("/TH/INTER", starter)


class TestRecognizedButNotEmittedReporting(unittest.TestCase):
    """C. "has a handler" was standing in for "is supported"."""

    def _kws(self, deck):
        result, _, _ = _convert(deck)
        return [kw for kw, _reason in result.recognized_not_emitted]

    def test_matsum_is_reported(self):
        kws = self._kws(_MESH + "*DATABASE_MATSUM\n   1.0E-05\n" + _TERM)
        self.assertIn("DATABASE_MATSUM", kws,
                      "*DATABASE_MATSUM produced no card and was not reported "
                      "anywhere — 'skipped: 0' implied it was converted")

    def test_nodout_elout_glstat_are_reported(self):
        deck = (_MESH
                + "*DATABASE_NODOUT\n   1.0E-05\n"
                + "*DATABASE_ELOUT\n   1.0E-05\n"
                + "*DATABASE_GLSTAT\n   1.0E-05\n" + _TERM)
        kws = self._kws(deck)
        for kw in ("DATABASE_NODOUT", "DATABASE_ELOUT", "DATABASE_GLSTAT"):
            self.assertIn(kw, kws)

    def test_each_report_carries_a_reason(self):
        result, _, _ = _convert(_MESH + "*DATABASE_MATSUM\n   1.0E-05\n" + _TERM)
        for kw, reason in result.recognized_not_emitted:
            self.assertTrue(reason.strip(),
                            f"*{kw} reported with no explanation")
        reason = dict(result.recognized_not_emitted)["DATABASE_MATSUM"]
        self.assertIn("/TH/PART", reason,
                      "the MATSUM reason must name the missing emitter")

    def test_these_keywords_are_not_double_counted_as_skipped(self):
        """They have handlers; the new channel is in addition to, not a
        reclassification of, skipped_keywords."""
        result, _, _ = _convert(_MESH + "*DATABASE_MATSUM\n   1.0E-05\n" + _TERM)
        self.assertNotIn("DATABASE_MATSUM", result.skipped_keywords)

    def test_report_is_deduplicated(self):
        deck = (_MESH + "*DATABASE_MATSUM\n   1.0E-05\n"
                + "*DATABASE_MATSUM\n   2.0E-05\n" + _TERM)
        kws = self._kws(deck)
        self.assertEqual(kws.count("DATABASE_MATSUM"), 1)

    def test_dt_zero_is_not_reported(self):
        """dt 0 disables the output in LS-DYNA — nothing was requested, so
        there is nothing to report as lost."""
        kws = self._kws(_MESH + "*DATABASE_MATSUM\n       0.0\n" + _TERM)
        self.assertNotIn("DATABASE_MATSUM", kws)

    def test_rcforc_is_not_reported_now_that_it_emits(self):
        kws = self._kws(_MESH + "*DATABASE_RCFORC\n   1.0E-05\n"
                        + _CONTACT + _TERM)
        self.assertNotIn("DATABASE_RCFORC", kws)

    def test_clean_deck_reports_nothing(self):
        result, _, _ = _convert(_MESH + _TERM)
        self.assertEqual(result.recognized_not_emitted, [])

    def test_log_file_carries_the_section(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "deck.k")
        with open(path, "w") as fh:
            fh.write(_MESH + "*DATABASE_MATSUM\n   1.0E-05\n" + _TERM)
        result = convert(path)
        self.assertIsNotNone(result.log_path,
                             "a deck with a lost output must produce a log")
        with open(result.log_path) as fh:
            log = fh.read()
        self.assertIn("Recognized but not emitted", log)
        self.assertIn("*DATABASE_MATSUM", log)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
