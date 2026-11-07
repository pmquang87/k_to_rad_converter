"""R14 parity round 10.

Each class pins one item of the round: the rule, its card text, its
sentences with their measured figures, the opt-out that restores the
ed52c93 bytes, and the wiring of its flag. Part A-i (A1 A2 A3 A4 A5 A6 A11
A12 A13 A14) comes first; parts A-ii and B extend the module. The moved pins
of the older modules (goldens, the K3 historical-bytes helpers, the K-41 /
TSSFAC texts) carry their own round-10 comments.
"""
import os
import re
import unittest

import test_r14_triage_7 as _t7
import test_cardstack_pipeline_props as _tp

_row = _t7._row
_convert = _t7._convert
_has = _t7._has
_prop_rows = _tp._prop_rows
_elem = _tp._elem
_node_rows = _tp._node_rows
_EXPLICIT = _tp._EXPLICIT
_IMPLICIT = _tp._IMPLICIT
_LAW44 = _tp._K32_LAW44
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ashear(starter: str, prop: int = 1) -> str:
    """/PROP/SHELL card 3 field 4 (Ashear, cols 41-60), as written."""
    return _prop_rows(starter, f"/PROP/SHELL/{prop}")[2][40:60].strip()


def _shell_n(starter: str, prop: int = 1) -> int:
    return int(_prop_rows(starter, f"/PROP/SHELL/{prop}")[2][0:10])


def _plate(shrf="", elform=2, nip=3, mat=_LAW44, control=_EXPLICIT,
           extra="") -> str:
    return _tp._shell_deck(nip=str(nip), elform=elform, mat=mat,
                           control=control, shrf=shrf, extra=extra)


def _shrf_notes(res):
    return [w for w in res.warnings if w.startswith("*SECTION_SHELL")
            and "SHRF" in w and "Ashear" in w]


def _readme() -> str:
    with open(os.path.join(_ROOT, "README.md"), encoding="utf-8") as fh:
        return fh.read()


# ═════════════════════════════════════════════════════════════════════════════
# A1  *SECTION_SHELL SHRF -> /PROP/SHELL Ashear (default; --no-shrf-ashear)
# ═════════════════════════════════════════════════════════════════════════════

class A1ShrfAshear(unittest.TestCase):
    """The rule (default ON): blank / 0 -> 1.0 (Vol I R17 p.41-63); within
    0.005 of 5/6 -> the starter's own 5/6 (cell 0, hm_read_prop01.F:244);
    (0, 1] as stated; outside -> 1.0, named. Kept 0 on NIP 1, the membranes
    5 / 9, the 2-D ELFORMs and k2rad's own placeholder sections."""

    def test_the_cell_by_value(self):
        # hand-computed: |5/6 - 0.83| = 0.00333 < 0.005 -> 0; |5/6 - 0.84|
        # = 0.00667 >= 0.005 -> as stated
        for shrf, cell in (("", "1"), ("0.0", "1"), ("0.7", "0.7"),
                           ("1.0", "1"), ("0.8333", "0"), ("0.83", "0"),
                           ("0.84", "0.84"), ("1.2", "1"), ("-0.5", "1")):
            with self.subTest(shrf=shrf):
                _r, st, _e = _convert(_plate(shrf=shrf))
                self.assertEqual(_ashear(st), cell)

    def test_the_window_edges(self):
        # 5/6 = 0.833333: |0.8285 - 5/6| = 0.004833 and |0.8383 - 5/6| =
        # 0.004967 are inside 0.005 (cell 0); 0.828 (0.005333) and 0.839
        # (0.005667) are outside (as stated)
        for shrf, cell in (("0.828", "0.828"), ("0.8285", "0"),
                           ("0.8383", "0"), ("0.839", "0.839")):
            with self.subTest(shrf=shrf):
                _r, st, _e = _convert(_plate(shrf=shrf))
                self.assertEqual(_ashear(st), cell)
        # |5/6 - 0.8285| / 0.8285 = 0.0058338 -> '0.58 %'
        res, _s, _e = _convert(_plate(shrf="0.8285"))
        self.assertTrue(_has(_shrf_notes(res), "(SHRF 0.8285): SHRF within "
                             "0.005 of 5/6", "0.58 % from the stated value."))

    def test_the_card_spellings_and_the_property_paths(self):
        comma = ("*KEYWORD\n" + _EXPLICIT + "*NODE\n"
                 + _node_rows(_tp._QUAD_PTS) + "*ELEMENT_SHELL\n"
                 + _elem(1, 1, 1, 2, 3, 4) + "*PART\nplate\n" + _row(1, 1, 1)
                 + "\n*SECTION_SHELL\n1,2,0.7,3\n1.0,1.0,1.0,1.0\n" + _LAW44
                 + "*END\n")
        titled = _plate(shrf="0.7").replace(
            "*SECTION_SHELL\n", "*SECTION_SHELL_TITLE\nnamed section\n")
        decks = {"comma": comma, "title": titled,
                 "implicit (Ishell 24)": _plate(shrf="0.7",
                                                control=_IMPLICIT),
                 "LAW1, K-31 N 0": _plate(shrf="0.7", mat=_tp._ELASTIC)}
        for name, deck in decks.items():
            with self.subTest(deck=name):
                _r, st, _e = _convert(deck)
                self.assertEqual(_ashear(st), "0.7")
        _r, st, _e = _convert(_plate(shrf="0.7", mat=_tp._ELASTIC))
        self.assertEqual(_shell_n(st), 0)                 # K-31 untouched

    def test_a_one_point_integration_rule_counts_as_nip_1(self):
        """writer/composites pushes a one-point *INTEGRATION_SHELL's count
        onto sec.nip before the property is written, so the stated NIP 5 is
        read as the NIP 1 LS-DYNA runs: the cell stays 0. (On LAW1 the rule
        is dropped and the section stays a /PROP/SHELL; another law writes
        it as a layered TYPE11 / TYPE51, which A1 does not reach.)"""
        rule = ("*INTEGRATION_SHELL\n" + _row(3, 1, 0) + "\n"
                + _row(0.0, 1.0) + "\n")
        deck = _tp._shell_deck().replace(
            "*SECTION_SHELL\n" + _row(1, 2, "", "5"),
            "*SECTION_SHELL\n" + _row(1, 2, "", "5", 1.0, -3))
        self.assertIn(_row(1, 2, "", "5", 1.0, -3), deck)
        res, st, _e = _convert(deck.replace("*END\n", rule + "*END\n"))
        self.assertEqual(_ashear(st), "0")
        self.assertTrue(_has(_shrf_notes(res), "*SECTION_SHELL 1 (NIP 1): "
                             "SHRF is NOT written"))

    def test_only_the_ashear_cell_moves(self):
        _r, on, e_on = _convert(_plate(shrf="0.7"))
        _r, off, e_off = _convert(_plate(shrf="0.7"), shrf_ashear=False)
        self.assertEqual(e_on, e_off)
        moved = _tp._diff_lines(off, on)
        self.assertEqual(len(moved), 1, moved)
        a, b = moved[0]
        self.assertEqual((a[:40], a[60:]), (b[:40], b[60:]))
        self.assertEqual((a[40:60].strip(), b[40:60].strip()), ("0", "0.7"))

    def test_the_window_sentence(self):
        # |5/6 - 0.83| / 0.83 = 0.0040161 -> '0.40 %'
        res, _s, _e = _convert(_plate(shrf="0.83"))
        notes = _shrf_notes(res)
        self.assertEqual(len(notes), 1, notes)
        self.assertEqual(
            notes[0],
            "*SECTION_SHELL 1 (SHRF 0.83): SHRF within 0.005 of 5/6 is "
            "written as the starter's own 5/6 (Ashear 0, "
            "hm_read_prop01.F:244), 0.40 % from the stated value.")
        for shrf in ("0.8333", "0.833"):     # within 1e-3: nothing to name
            with self.subTest(shrf=shrf):
                res, _s, _e = _convert(_plate(shrf=shrf))
                self.assertEqual(_shrf_notes(res), [])

    def test_two_window_values_keep_their_order(self):
        """Two sections, 0.8285 and 0.83: the ids grouped by label in label
        order and one percentage per label in the SAME order."""
        second = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                  + "*PART\nsecond\n" + _row(2, 2, 1) + "\n"
                  + "*SECTION_SHELL\n" + _row(2, 2, "0.8285", 3) + "\n"
                  + _row(1.0) + "\n")
        deck = _tp._shell_deck(nip="3", mat=_LAW44, shrf="0.83",
                               second=second)
        res, _s, _e = _convert(deck)
        notes = _shrf_notes(res)
        self.assertEqual(len(notes), 1, notes)
        # labels sort 'SHRF 0.8285' < 'SHRF 0.83': 0.58 % then 0.40 %
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 2 (SHRF 0.8285); 1 (SHRF 0.83): SHRF within"),
            notes[0])
        self.assertTrue(notes[0].endswith(
            "0.58 %, 0.40 % from the stated values."), notes[0])

    def test_the_range_sentence(self):
        for shrf in ("1.2", "-0.5"):
            with self.subTest(shrf=shrf):
                res, _s, _e = _convert(_plate(shrf=shrf))
                notes = _shrf_notes(res)
                self.assertEqual(len(notes), 1, notes)
                self.assertTrue(notes[0].startswith(
                    f"*SECTION_SHELL 1 (SHRF {float(shrf):g}): SHRF outside "
                    "(0, 1] cannot be a shear correction factor"), notes)
                self.assertIn("written as LS-DYNA's default 1.0", notes[0])

    def test_the_exclusion_keeps_the_cell_and_says_why(self):
        for kw, label in (({"nip": 1}, "NIP 1"),
                          ({"elform": 5}, "ELFORM 5"),
                          ({"elform": 9}, "ELFORM 9")):
            with self.subTest(**kw):
                res, st, _e = _convert(_plate(shrf="1.0", **kw))
                self.assertEqual(_ashear(st), "0")
                notes = _shrf_notes(res)
                self.assertEqual(len(notes), 1, notes)
                self.assertTrue(notes[0].startswith(
                    f"*SECTION_SHELL 1 ({label}): SHRF is NOT written to the "
                    "/PROP/SHELL Ashear cell (it stays 0, the starter's 5/6)"),
                    notes)
                for needle in ("p.41-66", "hm_read_prop01.F:246-259",
                               "p.41-67"):
                    self.assertIn(needle, notes[0])
        # a blank NIP-1 section is LS-DYNA's echoed 1.0 too: named
        res, st, _e = _convert(_plate(shrf="", nip=1))
        self.assertEqual(_ashear(st), "0")
        self.assertTrue(_has(_shrf_notes(res), "*SECTION_SHELL 1 (NIP 1): "
                             "SHRF is NOT written"))
        # ... a ~5/6 one is not (nothing differs)
        res, _s, _e = _convert(_plate(shrf="0.8333", nip=1))
        self.assertEqual(_shrf_notes(res), [])

    def test_the_kirchhoff_elements_take_the_rule_and_are_named(self):
        for elform in (3, 17, 18):
            with self.subTest(elform=elform):
                res, st, _e = _convert(_plate(elform=elform))
                self.assertEqual(_ashear(st), "1")
                notes = _shrf_notes(res)
                self.assertEqual(len(notes), 1, notes)
                self.assertTrue(notes[0].startswith(
                    f"*SECTION_SHELL 1 (ELFORM {elform}): SHRF is written to "
                    "the /PROP/SHELL Ashear cell (blank / 0 -> 1.0) although "
                    "LS-DYNA's BCIZ (ELFORM 3) and DK (17, 18) elements do "
                    "not use it"), notes)

    def test_a_placeholder_section_keeps_0(self):
        """A *PART whose SECID names no *SECTION_SHELL gets k2rad's own
        AutoPropShell (mesh.py _auto_section_shell): no deck SHRF exists."""
        deck = _tp._shell_deck(shrf="0.7").replace(
            "*SECTION_SHELL\n" + _row(1, 2, "0.7", "5") + "\n"
            + _row(1.0) + "\n", "")
        self.assertNotIn("*SECTION_SHELL", deck)
        res, st, _e = _convert(deck)
        heads = [ln for ln in st.splitlines() if ln.startswith("/PROP/SHELL/")]
        self.assertTrue(heads, st[:400])
        for h in heads:
            self.assertEqual(_prop_rows(st, h)[2][40:60].strip(), "0", h)
        self.assertEqual(_shrf_notes(res), [])

    def test_the_hourglass_split_prop_carries_the_cell(self):
        """Two parts on section 1 (SHRF 0.7), part 2 with its own
        *HOURGLASS: the split /PROP/SHELL of part 2 (mesh.py
        _emit_hourglass_props) carries the same Ashear; the section is named
        once (nothing to name for a stated 0.7)."""
        second = ("*ELEMENT_SHELL\n" + _elem(2, 2, 2, 5, 6, 3)
                  + "*PART\nsecond\n" + _row(2, 1, 1, 0, 4) + "\n"
                  + "*HOURGLASS\n" + _row(4, 4, 0.02) + "\n")
        deck = _tp._shell_deck(nip="3", mat=_LAW44, shrf="0.7",
                               second=second)
        res, st, _e = _convert(deck)
        lines = st.splitlines()
        refs = {}
        for pid in (1, 2):
            i = lines.index(f"/PART/{pid}")
            data = [ln for ln in lines[i + 2:i + 6] if not ln.startswith("#")]
            refs[pid] = int(data[0][0:10])
        self.assertNotEqual(refs[1], refs[2], refs)
        for pid, prop in refs.items():
            with self.subTest(pid=pid, prop=prop):
                self.assertEqual(_ashear(st, prop), "0.7")
        self.assertEqual(_shrf_notes(res), [])
        # under the opt-out both cells are 0 and the section is named ONCE
        res, st, _e = _convert(deck, shrf_ashear=False)
        for pid, prop in refs.items():
            self.assertEqual(_ashear(st, prop), "0")
        self.assertEqual(len(_shrf_notes(res)), 1, _shrf_notes(res))

    def test_the_opt_out_names_stated_and_blank_with_the_cap(self):
        res, st, _e = _convert(_plate(shrf=""), shrf_ashear=False)
        self.assertEqual(_ashear(st), "0")
        notes = _shrf_notes(res)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith(
            "*SECTION_SHELL 1 (SHRF blank / 0): SHRF, the transverse shear "
            "correction factor, is NOT carried to the /PROP/SHELL Ashear cell "
            "(--no-shrf-ashear)"), notes)
        self.assertTrue(notes[0].endswith(
            "The default writes the factor (a value within 0.005 of 5/6 keeps "
            "the starter's own 5/6)."), notes[0])

    def test_the_opt_out_keeps_the_k32_selection(self):
        """--no-shrf-ashear names every STATED SHRF more than 1e-3 from 5/6
        (the K-32 note's selection of ed52c93, _SHRF_FIVE_SIXTHS_TOL), the
        window values and the excluded sections included, plus every blank
        the default writes; a blank on an excluded section is not named (its
        cell is 0 on both arms) and a value within 1e-3 of 5/6 never is."""
        for kw, named in ((dict(shrf="0.83"), True),
                          (dict(shrf="0.8333"), False),
                          (dict(shrf="1.0", nip=1), True),
                          (dict(shrf="", nip=1), False),
                          (dict(shrf="", elform=9), False)):
            with self.subTest(**kw):
                res, st, _e = _convert(_plate(**kw), shrf_ashear=False)
                self.assertEqual(_ashear(st), "0")
                self.assertEqual(len(_shrf_notes(res)), int(named),
                                 _shrf_notes(res))
        res, _s, _e = _convert(_plate(shrf="1.0", nip=1), shrf_ashear=False)
        self.assertTrue(_has(_shrf_notes(res), "(--no-shrf-ashear)",
                             "section(s) 1 are NIP-1 / membrane / 2-D "
                             "sections LS-DYNA does not shear transversely "
                             "at all, whose cell the default keeps 0 too."))


# ═════════════════════════════════════════════════════════════════════════════
# A2  NIP 1 -> /PROP/SHELL N 1 on triangle-only sections (default;
#     --no-nip1-one-point)
# ═════════════════════════════════════════════════════════════════════════════

def _tri_deck(nip=1, quads=False, mat=_tp._ELASTIC, extra="") -> str:
    """Two triangles (degenerate quads n4 = n3) on part 1 / *SECTION_SHELL 1,
    or two quads when *quads*."""
    rows = ((_elem(1, 1, 1, 2, 3, 4) + _elem(2, 1, 2, 5, 6, 3)) if quads
            else (_elem(1, 1, 1, 2, 3, 3) + _elem(2, 1, 1, 3, 4, 4)))
    return ("*KEYWORD\n" + _EXPLICIT + "*NODE\n" + _node_rows(_tp._QUAD_PTS)
            + "*ELEMENT_SHELL\n" + rows
            + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2, "", nip) + "\n" + _row(1.0)
            + "\n" + mat + extra + "*END\n")


class A2Nip1OnePoint(unittest.TestCase):

    def test_triangles_are_written_n_1_and_named(self):
        for mat in (_tp._ELASTIC, _LAW44):        # LAW1 too: K-31 skips NIP 1
            with self.subTest(mat=mat[:14]):
                res, st, _e = _convert(_tri_deck(mat=mat))
                self.assertEqual(_shell_n(st), 1)
                self.assertEqual(_ashear(st), "0")    # A1's exclusion
                self.assertTrue(_has(res.warnings, "*SECTION_SHELL 1: NIP 1 "
                                     "on a section of triangles only -> "
                                     "/PROP/SHELL N 1", "c3grtails.F:710",
                                     "-81.76 mm", "IE END +65.73 -> +46.57 %",
                                     "22.79 -> 14.23 %"))

    def test_quads_keep_n_2_and_are_named(self):
        res, st, _e = _convert(_tri_deck(quads=True))
        self.assertEqual(_shell_n(st), 2)
        self.assertTrue(_has(res.warnings, "*SECTION_SHELL 1: NIP 1",
                             "keeps /PROP/SHELL N max(2, NIP) = 2",
                             "cycles 81-88"))
        self.assertFalse(_has(res.warnings, "on a section of triangles only"))

    def test_an_initial_state_section_keeps_n_2(self):
        ini = ("*INITIAL_STRESS_SHELL\n" + _row(1, 1, 2, 0, 0, 0) + "\n"
               + _row(-0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.5, 10.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        res, st, _e = _convert(_tri_deck(extra=ini))
        self.assertEqual(_shell_n(st), 2)
        self.assertTrue(_has(res.warnings, "*SECTION_SHELL 1: NIP 1 keeps "
                             "/PROP/SHELL N max(2, NIP) = 2 because an "
                             "*INITIAL_STRESS_SHELL"))

    def test_nip_2_triangles_do_not_move(self):
        _r, on, _e = _convert(_tri_deck(nip=2, mat=_LAW44))
        _r, off, _e = _convert(_tri_deck(nip=2, mat=_LAW44),
                               nip1_one_point=False)
        self.assertEqual(on, off)
        self.assertEqual(_shell_n(on), 2)

    def test_the_opt_out_writes_n_2_and_says_it_bends(self):
        res, st, _e = _convert(_tri_deck(), nip1_one_point=False)
        self.assertEqual(_shell_n(st), 2)
        self.assertTrue(_has(res.warnings, "*SECTION_SHELL 1: NIP 1",
                             "(--no-nip1-one-point)", "BENDS"))
        _r, on, _e = _convert(_tri_deck())
        moved = _tp._diff_lines(st, on)
        self.assertEqual(len(moved), 1, moved)
        self.assertEqual((int(moved[0][0][:10]), int(moved[0][1][:10])),
                         (2, 1))
        self.assertEqual(moved[0][0][10:], moved[0][1][10:])   # N cell only

    def test_a_one_point_rule_on_triangles_names_the_n_1_written(self):
        """A one-point *INTEGRATION_SHELL on a LAW1 triangle-only section
        (stated NIP 5): writer/composites drops the rule (LAW1) and its
        sentence names the N the plain /PROP/SHELL really carries - 1 under
        A2, not the max(2, NIP) the starter would switch to N = 0."""
        rule = ("*INTEGRATION_SHELL\n" + _row(3, 1, 0) + "\n"
                + _row(0.0, 1.0) + "\n")
        deck = _tri_deck(nip=5).replace(
            "*SECTION_SHELL\n" + _row(1, 2, "", 5),
            "*SECTION_SHELL\n" + _row(1, 2, "", 5, 1.0, -3))
        self.assertIn(_row(1, 2, "", 5, 1.0, -3), deck)
        res, st, _e = _convert(deck.replace("*END\n", rule + "*END\n"))
        self.assertEqual(_shell_n(st), 1)
        msg = [w for w in res.warnings if "the rule is DROPPED" in w
               and "LAW1" in w]
        self.assertEqual(len(msg), 1, res.warnings)
        self.assertIn("written N = 1 (LS-DYNA's one point, no bending; no "
                      "starter switch acts on N 1, c3grtails.F:710", msg[0])
        res, st, _e = _convert(deck.replace("*END\n", rule + "*END\n"),
                               nip1_one_point=False)
        self.assertEqual(_shell_n(st), 2)


# ═════════════════════════════════════════════════════════════════════════════
# Retracted statements and forbidden sentences (the rounds 4-9 shape:
# _t7._SHIPPED_TEXTS = README, ROADMAP, the GUI, k2rad.py, k2rad/, docs/*.md,
# tools/*.py with adjacent literals joined; CHANGELOG is the history)
# ═════════════════════════════════════════════════════════════════════════════

#: Part A-i statements round 10 made false. CHANGELOG may quote them.
_RETRACTED_ROUND_10_A = (
    # A1: the K-32 'NOT converted' note of the default path (writer/mesh)
    "Carrying SHRF to Ashear is a ROADMAP round-10 item",
    "run with a shear factor of 5/6 whatever SHRF says",
    "the stated SHRF, the transverse",
    # A1: the SectionShell.shrf comment (state.py)
    "NOT converted: /PROP/SHELL Ashear stays 0",
    # A1: the K_ROUTE /PROP/SHELL row
    "SHRF is NOT converted",
    # A1: the README K-32 paragraph
    "carrying SHRF over is a round-10 item",
    "it runs at 5/6 the same way and is not named",
)

#: (shipped file, the replacement text it now carries)
_REPLACEMENTS_ROUND_10_A = (
    ("k2rad/writer/mesh.py",
     "is NOT carried to the /PROP/SHELL Ashear cell (--no-shrf-ashear)"),
    ("k2rad/writer/mesh.py",
     "SHRF is NOT written to the /PROP/SHELL Ashear cell (it stays 0, the "
     "starter's 5/6) because LS-DYNA does not shear these sections"),
    # (a comment needle is cut at its comment line's end: the guard keeps #)
    ("k2rad/state.py",
     "--no-shrf-ashear): written to the /PROP/SHELL Ashear cell by the rule"),
    ("README.md",
     "**`*SECTION_SHELL` SHRF is written to the `/PROP/SHELL` Ashear cell "
     "since R14 round 10**"),
    ("docs/K_ROUTE_FOR_RADIOSS_CARDS.md",
     "Ashear carries `*SECTION_SHELL` SHRF since R14 round 10"),
)

#: sentences that must never ship, CHANGELOG included (measured false before
#: they could ship): the round-10 census wrote that A1's default does not
#: touch the CardStack pipeline - all 28 of its 28 shell-carrying keyword
#: decks move (run_03 .. run_21 SHRF 1.0, run_22 .. run_26 blank).
_FORBIDDEN_ROUND_10_A = (
    "does not touch the CardStack pipeline",
)


def _with_changelog():
    texts = list(_t7._SHIPPED_TEXTS())
    with open(os.path.join(_ROOT, "CHANGELOG.md"), encoding="utf-8") as fh:
        texts.append(("CHANGELOG.md", _t7._collapse(fh.read())))
    return texts


class Round10RetractedStatementsA(unittest.TestCase):
    """No shipped text carries a retracted part-A-i spelling; the guard fires
    on each needle split across two adjacent literals; a PREFIX still fires;
    the replacements ARE shipped; the forbidden sentences appear nowhere,
    CHANGELOG included."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _t7._SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_10_A:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_10_A + _FORBIDDEN_ROUND_10_A:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "')
                        + ' y')
                self.assertIn(_t7._collapse(needle).lower(), _t7._collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_10_A + _FORBIDDEN_ROUND_10_A:
            with self.subTest(needle=needle):
                self.assertIn(_t7._collapse(needle[:max(4, len(needle) // 2)]),
                              _t7._collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_t7._SHIPPED_TEXTS())
        for rel, needle in _REPLACEMENTS_ROUND_10_A:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_t7._collapse(needle), texts[key])

    def test_no_document_carries_a_forbidden_sentence(self):
        for rel, joined in _with_changelog():
            for needle in _FORBIDDEN_ROUND_10_A:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())


# ═════════════════════════════════════════════════════════════════════════════
# The flags: parser, convert(), ConvertOptions, cli.main(), GUI, README, help
# ═════════════════════════════════════════════════════════════════════════════

class Round10FlagWiringA(_t7.Round7FlagWiringA):
    """The round-10 default-ON levers of part A-i."""

    _FLAGS = {
        "--shrf-ashear": "shrf_ashear",
        "--nip1-one-point": "nip1_one_point",
    }
    _HELP_FIGURES = {
        "--shrf-ashear": ("-0.041 % (L/t 3) / -0.018 % (L/t 5)",
                          "-0.024 / -0.025 %", "all 2642 R14 shell parts",
                          "hm_read_prop01.F:246-259",
                          "0 verdict flips, largest END move 1.54 points"),
        "--nip1-one-point": ("p.41-66", "c3grtails.F:710", "-81.76 mm",
                             "-0.4761 mm", "110032 cycles",
                             "IE END +65.73 -> +46.57 %",
                             "22.79 -> 14.23 %"),
    }


if __name__ == "__main__":
    unittest.main()
