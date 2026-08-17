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


# ── D. *DATABASE_DEFORC / *DATABASE_DISBOUT -> /TH/SPRING ────────────────────

def _tfile(engine: str) -> str:
    return engine[engine.index("/TFILE"):].splitlines()[1].strip()


def _th_spring_eids(starter: str) -> list:
    """Element ids listed under the first /TH/SPRING block."""
    lines = starter.split("/TH/SPRING/")[1].splitlines()
    eids = []
    for ln in lines[4:]:            # id line, title, var comment, var line
        if not ln.strip() or ln.startswith("#") or ln.startswith("/"):
            break
        eids.append(int(ln))
    return eids


# Two convertible discrete springs (11, 12) plus a grounded one (13) whose
# anchor node 999 has no *NODE record — the discrete-spring writer `continue`s
# past that one, so its id must NOT reach the /TH/SPRING.
_DISCRETE = """*NODE
      41             0.0             0.0            50.0
      42             1.0             0.0            50.0
      43             2.0             0.0            50.0
*PART
spring part
        20        20        20
*SECTION_DISCRETE
        20         0
*MAT_SPRING_ELASTIC
        20    1000.0
*ELEMENT_DISCRETE
      11      20      41      42
      12      20      42      43
      13      20     999       0
"""

# *SECTION_BEAM ELFORM=6 discrete beam, element id 77.
_DBEAM = """*NODE
      51             0.0             0.0            80.0
      52             0.0             0.0            90.0
      53             1.0             0.0            80.0
*PART
discrete beam
        30        30        30
*SECTION_BEAM
        30         6
     100.0       5.0         0
*MAT_LINEAR_ELASTIC_DISCRETE_BEAM
        30    7.8E-9    1000.0    2000.0    3000.0    4000.0    5000.0\
    6000.0
      10.0      20.0      30.0      40.0      50.0      60.0
     500.0       0.0       0.0       0.0       0.0       0.0
*ELEMENT_BEAM
      77      30      51      52      53
"""


class TestDeforcDiscreteSpringOutput(unittest.TestCase):
    """*DATABASE_DEFORC was parsed into state and consumed by nothing: no /TH
    block, and not even a contribution to the /TFILE frequency.

    Vol I R16 p.1944: DEFORC is "discrete spring and discrete damper
    (*ELEMENT_DISCRETE) data" — k2rad turns those into /SPRING elements, so
    /TH/SPRING is where the channel belongs.
    """

    DECK = _MESH + _DISCRETE + "*DATABASE_DEFORC\n       0.1\n" + _TERM

    def test_deforc_emits_a_th_spring_group(self):
        _r, starter, _e = _convert(self.DECK)
        self.assertIn("/TH/SPRING/", starter)
        self.assertIn("TH_DISCRETE_SPRINGS_", starter)

    def test_only_actually_emitted_eids_are_listed(self):
        """hm_read_thgrne.F:189 — a /TH/SPRING naming an element the deck does
        not define is starter ERROR 69 and the WHOLE deck is refused. Element
        13 is grounded on a node with no coordinates, so the spring writer
        skips it and it must not appear."""
        result, starter, _e = _convert(self.DECK)
        self.assertEqual(_th_spring_eids(starter), [11, 12])
        self.assertTrue(any("element skipped" in w for w in result.warnings),
                        result.warnings)

    def test_group_carries_a_title_and_the_def_variable(self):
        """The title line is MANDATORY: the reader takes the first line after
        the header as the title unconditionally, so dropping it feeds ``DEF``
        to the title and the deck dies with ERROR 260 + ERROR 1109."""
        _r, starter, _e = _convert(self.DECK)
        blk = starter.split("/TH/SPRING/")[1].splitlines()
        self.assertTrue(blk[1].startswith("TH_DISCRETE_SPRINGS_"))
        self.assertEqual(blk[3].strip(), "DEF")

    def test_ids_go_one_per_line(self):
        """/TH/SPRING is read by hm_read_thgrne.F (one %10d id per line), not
        the ten-per-line hm_read_thgrki.F that /TH/CLUSTER uses — measured, a
        second id on the same line is WARNING 100214 and is SILENTLY DROPPED."""
        _r, starter, _e = _convert(self.DECK)
        blk = starter.split("/TH/SPRING/")[1].splitlines()
        for ln in blk[4:6]:
            self.assertEqual(len(ln), 10, repr(ln))
            self.assertEqual(ln, f"{int(ln):>10d}")

    def test_deforc_reaches_the_tfile_frequency(self):
        _r, _s, engine = _convert(
            _MESH + _DISCRETE + "*DATABASE_DEFORC\n   2.5E-06\n" + _TERM)
        self.assertEqual(_tfile(engine), "2.5E-06")

    def test_deforc_reports_the_mapping_and_the_units(self):
        result, _s, _e = _convert(self.DECK)
        hits = [w for w in result.warnings
                if "*DATABASE_DEFORC" in w and "/TH/SPRING" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("DECK'S OWN UNITS", hits[0])

    def test_deforc_without_a_discrete_element_warns_instead_of_silence(self):
        """An empty /TH group is starter ERROR 1109, so emitting nothing is
        right — but it must be said out loud, and the dt must still land."""
        result, starter, engine = _convert(
            _MESH + "*DATABASE_DEFORC\n   2.5E-06\n" + _TERM)
        self.assertNotIn("/TH/SPRING/", starter)
        self.assertEqual(_tfile(engine), "2.5E-06")
        self.assertTrue(
            any("*DATABASE_DEFORC requested" in w for w in result.warnings),
            result.warnings)

    def test_deforc_does_not_claim_the_discrete_beams(self):
        """DISBOUT, not DEFORC, is "discrete beam element, type 6" (p.1945).
        A DEFORC-only deck must leave the ELFORM=6 connector out."""
        _r, starter, _e = _convert(
            _MESH + _DISCRETE + _DBEAM + "*DATABASE_DEFORC\n       0.1\n"
            + _TERM)
        self.assertEqual(_th_spring_eids(starter), [11, 12])

    def test_deck_without_deforc_gets_no_th_spring(self):
        _r, starter, _e = _convert(_MESH + _DISCRETE + _TERM)
        self.assertNotIn("/TH/SPRING/", starter)

    def test_synthesized_springs_are_not_claimed(self):
        """`*ELEMENT_PLOTEL` also becomes a `/SPRING`, but with a converter-
        invented part and no LS-DYNA deforc row behind it. Only the springs
        `_emit_spring_part` writes for `*ELEMENT_DISCRETE` may be listed —
        the same boundary that keeps `--ground-springs`, the
        `*CONSTRAINED_SPOTWELD` ties and the joint springs out."""
        _r, starter, _e = _convert(
            _MESH + _DISCRETE + "*ELEMENT_PLOTEL\n     501       1       2\n"
            + "*DATABASE_DEFORC\n       0.1\n" + _TERM)
        self.assertIn("PLOTEL", starter)         # the PLOTEL spring was emitted
        self.assertEqual(_th_spring_eids(starter), [11, 12])


class TestDeforcPrintFlag(unittest.TestCase):
    """`PF` on *ELEMENT_DISCRETE is the deforc PRINT flag — "EQ.0: forces are
    printed in DEFORC file, EQ.1: forces are not printed DEFORC file" (Vol I
    R16 p.19-32) — and p.1944 names it as one of the two ways a deck narrows
    the deforc selection. It is an OUTPUT flag only: the /SPRING is emitted
    either way, and only the /TH group shrinks.
    """

    # element 11 carries PF=1 (fixed columns: eid pid n1 n2 vid S(E16) PF)
    _PF = """*NODE
      41             0.0             0.0            50.0
      42             1.0             0.0            50.0
      43             2.0             0.0            50.0
*PART
spring part
        20        20        20
*SECTION_DISCRETE
        20         0
*MAT_SPRING_ELASTIC
        20    1000.0
*ELEMENT_DISCRETE
      11      20      41      42       0             1.0       1
      12      20      42      43
"""

    def test_pf_one_is_left_out_of_the_group(self):
        _r, starter, _e = _convert(
            _MESH + self._PF + "*DATABASE_DEFORC\n       0.1\n" + _TERM)
        self.assertEqual(_th_spring_eids(starter), [12])

    def test_pf_one_still_emits_the_spring_itself(self):
        """PF suppresses OUTPUT, not the connector — dropping the element
        would change the model, which the flag never asks for."""
        _r, starter, _e = _convert(
            _MESH + self._PF + "*DATABASE_DEFORC\n       0.1\n" + _TERM)
        lines = starter.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/SPRING/"))
        # "# sprg_ID  node_ID1  node_ID2" then one line per element
        self.assertEqual([ln.split()[0] for ln in lines[i + 2:i + 4]],
                         ["11", "12"])

    def test_pf_zero_and_absent_are_both_reported(self):
        _r, starter, _e = _convert(
            _MESH + self._PF.replace("       1\n", "       0\n")
            + "*DATABASE_DEFORC\n       0.1\n" + _TERM)
        self.assertEqual(_th_spring_eids(starter), [11, 12])

    def test_all_suppressed_emits_no_group_and_says_why(self):
        """An empty /TH group is starter ERROR 1109, so the block must be
        omitted — and the warning must name PF rather than claim the deck has
        no connectors at all."""
        deck = self._PF.replace(
            "      12      20      42      43\n",
            "      12      20      42      43       0             1.0       1\n")
        result, starter, _e = _convert(
            _MESH + deck + "*DATABASE_DEFORC\n       0.1\n" + _TERM)
        self.assertNotIn("/TH/SPRING/", starter)
        hits = [w for w in result.warnings if "*DATABASE_DEFORC" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("PF=1", hits[0])

    def test_history_discrete_qualifies_the_one_to_one_claim(self):
        """*DATABASE_HISTORY_DISCRETE has no handler, so a deck that uses it to
        select elements gets a group that is a SUPERSET of its deforc file.
        Over-reporting is harmless data; an unqualified 1:1 claim is not."""
        result, _s, _e = _convert(
            _MESH + _DISCRETE + "*DATABASE_DEFORC\n       0.1\n"
            + "*DATABASE_HISTORY_DISCRETE\n        11\n" + _TERM)
        hits = [w for w in result.warnings if "/TH/SPRING/" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("SUPERSET", hits[0])

    def test_no_superset_note_without_the_history_card(self):
        result, _s, _e = _convert(
            _MESH + _DISCRETE + "*DATABASE_DEFORC\n       0.1\n" + _TERM)
        hits = [w for w in result.warnings if "/TH/SPRING/" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertNotIn("SUPERSET", hits[0])


class TestDisboutDiscreteBeamOutput(unittest.TestCase):
    """*DATABASE_DISBOUT: "discrete beam element, type 6, relative
    displacements, rotations, and forces" (Vol I R16 p.1945)."""

    DECK = _MESH + _DBEAM + "*DATABASE_DISBOUT\n       0.1\n" + _TERM

    def test_disbout_emits_a_th_spring_group_over_the_beams(self):
        _r, starter, _e = _convert(self.DECK)
        self.assertIn("TH_DISCRETE_BEAMS_", starter)
        self.assertEqual(_th_spring_eids(starter), [77])

    def test_disbout_reaches_the_tfile_frequency(self):
        _r, _s, engine = _convert(
            _MESH + _DBEAM + "*DATABASE_DISBOUT\n   2.5E-06\n" + _TERM)
        self.assertEqual(_tfile(engine), "2.5E-06")

    def test_disbout_without_a_discrete_beam_warns(self):
        result, starter, _e = _convert(
            _MESH + "*DATABASE_DISBOUT\n       0.1\n" + _TERM)
        self.assertNotIn("/TH/SPRING/", starter)
        self.assertTrue(
            any("*DATABASE_DISBOUT requested" in w for w in result.warnings),
            result.warnings)

    def test_both_cards_emit_two_separately_attributed_groups(self):
        result, starter, _e = _convert(
            _MESH + _DISCRETE + _DBEAM + "*DATABASE_DEFORC\n       0.1\n"
            + "*DATABASE_DISBOUT\n       0.2\n" + _TERM)
        self.assertEqual(starter.count("/TH/SPRING/"), 2)
        self.assertIn("TH_DISCRETE_SPRINGS_", starter)
        self.assertIn("TH_DISCRETE_BEAMS_", starter)
        # /TH ids are ONE namespace across every /TH type (PR #83, ERROR 79).
        ids = [int(ln.split("/")[-1]) for ln in starter.splitlines()
               if ln.startswith("/TH/SPRING/")]
        self.assertEqual(len(set(ids)), 2, ids)


# ── C/E. Invented output frequencies: /TFILE and /ANIM/DT ────────────────────

class TestTfileFallbackFrequency(unittest.TestCase):
    """With no *DATABASE_ dt anywhere, the T01 frequency has to be invented.
    A hard-coded 1e-3 is wrong at both ends of the scale: on a 0.01 s impact it
    writes 10 records for the whole event."""

    def _deck(self, endtim=None, extra=""):
        term = "" if endtim is None else f"*CONTROL_TERMINATION\n{endtim}\n"
        return _MESH + extra + term + "*END\n"

    def test_fallback_scales_with_the_termination_time(self):
        for endtim, expected in (("      0.01", "1E-05"),
                                 ("       1.0", "0.001"),
                                 ("       2.0", "0.002"),
                                 ("     100.0", "0.1")):
            with self.subTest(endtim=endtim):
                _r, _s, engine = _convert(self._deck(endtim))
                self.assertEqual(_tfile(engine), expected)

    def test_no_termination_card_keeps_the_floor(self):
        """Nothing states a time scale, and a zero /TFILE is silently ignored
        by the engine (lectur.F:335), so the historical constant is the floor."""
        _r, _s, engine = _convert(self._deck(None))
        self.assertEqual(_tfile(engine), "0.001")

    def test_sentinel_endtim_is_not_treated_as_a_run_length(self):
        """`ENDTIM = 1e20` is the idiom for a deck that really terminates on
        ENDCYC/ENDENG. Scaling from it would derive /TFILE 1E+17 — a T01 that
        never fires at all, i.e. a silent TOTAL loss of time-history output,
        strictly worse than the constant it replaced."""
        # ENDTIM is a strict 10-column field, so the literals below are exactly
        # 10 characters wide — a wider one silently truncates (see the module
        # note on *CONTROL_TERMINATION field slicing).
        for endtim in ("   1.0E+20", "   1.0E+10", "   1.0E+06"):
            with self.subTest(endtim=endtim):
                _r, _s, engine = _convert(self._deck(endtim))
                self.assertEqual(_tfile(engine), "0.001")

    def test_the_largest_real_run_length_still_scales(self):
        """The sentinel window must not swallow long but genuine runs: the
        whole 201-deck corpus lives between 8.5e-5 and 30."""
        _r, _s, engine = _convert(self._deck("      30.0"))
        self.assertEqual(_tfile(engine), "0.03")

    def test_sentinel_warning_names_the_reason(self):
        result, starter, _e = _convert(
            _MESH + "*DATABASE_HISTORY_NODE\n         1\n"
            + "*CONTROL_TERMINATION\n   1.0E+20\n*END\n")
        self.assertIn("/TH/", starter)
        hits = [w for w in result.warnings if w.startswith("TIME HISTORY:")]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("SENTINEL", hits[0])

    def test_a_negative_dt_is_reported_not_silently_ignored(self):
        """"If DT < 0.0, the result will be output every -DT time steps"
        (Manual p. 16-7). Radioss's /TFILE is a TIME interval with no
        cycle-based form, so the request cannot be honoured — but the warning
        must not go on claiming the deck stated no interval at all."""
        result, starter, engine = _convert(
            _MESH + "*DATABASE_HISTORY_NODE\n         1\n"
            + "*DATABASE_GLSTAT\n    -100.0\n"
            + "*CONTROL_TERMINATION\n      0.01\n*END\n")
        self.assertIn("/TH/", starter)
        # the negative dt takes no part in the minimum...
        self.assertEqual(_tfile(engine), "1E-05")
        hits = [w for w in result.warnings if w.startswith("TIME HISTORY:")]
        self.assertEqual(len(hits), 1, result.warnings)
        # ...but it is named, and the claim is narrowed from "no *DATABASE_
        # card states an output interval" to "no POSITIVE output interval".
        self.assertIn("negative DT", hits[0])
        self.assertIn("no *DATABASE_ card states a positive output interval",
                      hits[0])

    def test_a_positive_dt_says_nothing_about_negatives(self):
        result, _s, _e = _convert(
            _MESH + "*DATABASE_HISTORY_NODE\n         1\n"
            + "*DATABASE_GLSTAT\n     0.002\n"
            + "*CONTROL_TERMINATION\n      0.01\n*END\n")
        self.assertEqual([w for w in result.warnings
                          if w.startswith("TIME HISTORY:")], [])

    def test_zero_termination_keeps_the_floor(self):
        _r, _s, engine = _convert(self._deck("       0.0      1000"))
        self.assertEqual(_tfile(engine), "0.001")

    def test_a_stated_dt_always_wins(self):
        _r, _s, engine = _convert(
            self._deck("      0.01", "*DATABASE_GLSTAT\n     0.002\n"))
        self.assertEqual(_tfile(engine), "0.002")

    def test_derived_frequency_is_silent_without_a_th_group(self):
        """With no /TH block in the deck the invented number governs nothing
        anyone reads, so it must not add noise."""
        result, _s, _e = _convert(self._deck("      0.01"))
        self.assertEqual([w for w in result.warnings if "TIME HISTORY" in w],
                         [])

    def test_derived_frequency_warns_once_when_a_th_group_exists(self):
        result, starter, engine = _convert(
            _MESH + _CONTACT
            + "*DATABASE_HISTORY_NODE\n         1\n"
            + "*CONTROL_TERMINATION\n      0.01\n*END\n")
        self.assertIn("/TH/", starter)
        self.assertEqual(_tfile(engine), "1E-05")
        hits = [w for w in result.warnings if w.startswith("TIME HISTORY:")]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("DERIVED", hits[0])
        self.assertIn("/TFILE 1E-05", hits[0])


class TestAnimDtZeroGuard(unittest.TestCase):
    """``/ANIM/DT  0. 0`` is not a harmless no-op: freanim.F:131-134 raises
    engine MESSAGE 293 ("TIME FREQUENCY ... MUST BE GREATER THAN ZERO") and
    calls ARRET(0), so the run stops before cycle 1. Verified end to end: the
    same deck ERROR-TERMINATES on master and NORMAL-TERMINATES with the card
    omitted."""

    ZERO_TERM = "*CONTROL_TERMINATION\n       0.0      1000\n*END\n"
    # NPLTC is *DATABASE_BINARY_D3PLOT field 4 (index 3): DT | LCDT | BEAM |
    # NPLTC, 10 columns each. A "20" in columns 11-20 is LCDT and leaves NPLTC
    # at 0, which made this deck exercise nothing at all.
    D3PLOT_NPLTC_20 = ("*DATABASE_BINARY_D3PLOT\n"
                       "       0.0                            20\n")

    def test_zero_endtim_omits_the_anim_dt_card(self):
        _r, _s, engine = _convert(_MESH + self.ZERO_TERM)
        self.assertNotIn("/ANIM/DT", engine)

    def test_zero_endtim_warns_that_no_animation_is_written(self):
        result, _s, _e = _convert(_MESH + self.ZERO_TERM)
        hits = [w for w in result.warnings if "/ANIM/DT" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("NO ANIMATION", hits[0])

    def test_a_d3plot_dt_rescues_the_animation(self):
        _r, _s, engine = _convert(
            _MESH + "*DATABASE_BINARY_D3PLOT\n     1.0E-4\n" + self.ZERO_TERM)
        self.assertIn("/ANIM/DT\n0. 0.0001", engine)

    def test_npltc_does_not_invent_a_run_length_on_a_zero_endtim(self):
        """NPLTC with ENDTIM 0 would divide zero by the frame count; inventing
        a 1 s run instead would fabricate a frequency the deck never stated."""
        _r, _s, engine = _convert(
            _MESH + self.D3PLOT_NPLTC_20 + self.ZERO_TERM)
        self.assertNotIn("/ANIM/DT", engine)

    def test_the_warning_does_not_deny_a_stated_npltc(self):
        """A deck that DOES state NPLTC must not be told it stated none: it is
        the zero ENDTIM that makes ENDTIM/NPLTC useless, and naming the wrong
        cause sends the user to edit the wrong card."""
        result, _s, _e = _convert(
            _MESH + self.D3PLOT_NPLTC_20 + self.ZERO_TERM)
        hits = [w for w in result.warnings if "/ANIM/DT" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("its NPLTC 20", hits[0])
        self.assertNotIn("no *DATABASE_BINARY_D3PLOT states a positive DT or "
                         "NPLTC", hits[0])

    def test_the_warning_still_reports_a_truly_absent_d3plot(self):
        result, _s, _e = _convert(_MESH + self.ZERO_TERM)
        hits = [w for w in result.warnings if "/ANIM/DT" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("no *DATABASE_BINARY_D3PLOT states a positive DT or "
                      "NPLTC", hits[0])

    def test_positive_endtim_is_untouched(self):
        _r, _s, engine = _convert(
            _MESH + "*CONTROL_TERMINATION\n       2.0\n*END\n")
        self.assertIn("/ANIM/DT\n0. 0.05", engine)

    def test_no_termination_card_keeps_the_historical_default(self):
        _r, _s, engine = _convert(_MESH + "*END\n")
        self.assertIn("/ANIM/DT\n0. 0.01", engine)


if __name__ == "__main__":
    unittest.main()
