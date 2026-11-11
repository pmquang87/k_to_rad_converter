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
import test_r14_triage_8 as _t8
import test_r14_triage_9 as _t9
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

    def test_the_hourglass_split_prop_carries_n_1(self):
        """Two triangle parts on section 1 (NIP 1), part 2 with its own
        *HOURGLASS: the split /PROP/SHELL of part 2 (mesh.py
        _emit_hourglass_props) is written N 1 as well, the plain one too;
        under the opt-out both are N 2."""
        second = ("*ELEMENT_SHELL\n" + _elem(3, 2, 2, 5, 6, 6)
                  + "*PART\nsecond\n" + _row(2, 1, 1, 0, 4) + "\n"
                  + "*HOURGLASS\n" + _row(4, 4, 0.02) + "\n")
        deck = _tri_deck(extra=second)
        for kw, n in (({}, 1), ({"nip1_one_point": False}, 2)):
            with self.subTest(**kw):
                _r, st, _e = _convert(deck, **kw)
                lines = st.splitlines()
                refs = {}
                for pid in (1, 2):
                    i = lines.index(f"/PART/{pid}")
                    data = [ln for ln in lines[i + 2:i + 6]
                            if not ln.startswith("#")]
                    refs[pid] = int(data[0][0:10])
                self.assertNotEqual(refs[1], refs[2], refs)
                for pid, prop in refs.items():
                    self.assertEqual(_shell_n(st, prop), n, (pid, prop))


# ═════════════════════════════════════════════════════════════════════════════
# A3  the texts that ride A1 / A2 (help, comment, docstring)
# ═════════════════════════════════════════════════════════════════════════════

def _flag_help(flag: str) -> str:
    """The rendered --help text of one option, whitespace collapsed."""
    from k2rad import cli
    parser = cli.build_parser()
    for action in parser._actions:
        if flag in action.option_strings:
            return _t7._collapse((action.help or "").replace("%%", "%"))
    raise AssertionError(flag)


def _source(*parts: str) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class A3Texts(unittest.TestCase):

    def test_law1_help_names_the_five_conditions(self):
        """The --law1-shell-global-n help names every condition of
        writer/mesh._law1_global_n_secids (it named one before round 10)."""
        text = _flag_help("--law1-shell-global-n")
        for needle in ("*MAT_RIGID written as /MAT/ELAST",
                       "Not on a section with NIP 1", "*INITIAL_STRAIN_SHELL",
                       "another material law shares", "/THERM_STRESS",
                       "c3grtails.F:710", "cgrtails.F:780-791",
                       "--no-law1-shell-global-n writes max(2, NIP)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_elform_always_qeph_comment(self):
        """common.py's _ELFORM_ALWAYS_QEPH comment gives the measured reason
        (Vol I calls the five ELFORMs FULLY integrated; 'already
        reduced-integration' was wrong)."""
        text = _t7._collapse(_source("k2rad", "writer", "common.py"))
        for needle in ("FULLY integrated forms in LS-DYNA",
                       "convertprops.cxx:781-783", "8.59 -> 9.50 %",
                       "43.78 -> 50.35 %", "cycles 81-88"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        # the '#' rule: needle each retracted comment line on its own
        for needle in ("QEPH regardless of the option: already",
                       "reduced-integration / co-rotational forms whose "
                       "Radioss counterpart is"):
            with self.subTest(retracted=needle):
                self.assertNotIn(needle, text)

    def test_shell_formulation_help_names_the_fixed_list(self):
        text = _flag_help("--shell-formulation")
        for needle in ("-16 / 9 / 20 / 21 / 26", "convertprops.cxx:781-783",
                       "43.78 -> 50.35 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_tet_reset_citation(self):
        """sgrtails.F:984-999 is the reset block; line 1000 is a comment.
        The wrong ':984-1000' ships nowhere a claim is made (the help, the
        convert() docstring, ConvertOptions, writer/mesh, README); ROADMAP's
        CardStack 'Opened by the batch' record quotes it as the defect."""
        from k2rad import cli
        import k2rad
        shipped = {
            "help": _t7._collapse(cli.build_parser().format_help()),
            "convert()": _t7._collapse(k2rad.convert.__doc__),
            "state.py": _source("k2rad", "state.py"),
            "mesh.py": _source("k2rad", "writer", "mesh.py"),
            "cli.py": _source("k2rad", "cli.py"),
            "__init__.py": _source("k2rad", "__init__.py"),
            "README.md": _source("README.md"),
        }
        for where, text in shipped.items():
            with self.subTest(where=where):
                self.assertNotIn("sgrtails.F:984-1000", text)
        for where in ("help", "convert()"):
            self.assertIn("sgrtails.F:984-999", shipped[where])
        self.assertIn("An all-tet ELFORM 2 or 16 section keeps the Isolid 17",
                      _flag_help("--tet-isolid1"))


# ═════════════════════════════════════════════════════════════════════════════
# A5 / A6  the dynamic implicit fixture (2 x 2 x 2 hexes, ex_14's controls)
# ═════════════════════════════════════════════════════════════════════════════

def _hex_block(dynamic=True, damping="*DAMPING_GLOBAL\n"
               + _row(0, 11.535, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n",
               extra="") -> str:
    """A 20 mm cube of 2 x 2 x 2 *MAT_ELASTIC hexes, the base nodes fixed,
    a -100 N load on each top node, ex_14's implicit controls (IAUTO 0,
    DT0 ... ; *CONTROL_IMPLICIT_DYNAMICS IMASS 1 when *dynamic*), ENDTIM
    0.02 and a *DAMPING_GLOBAL VALDMP 11.535 (LCID 0, ST all 0)."""
    nodes, nid = {}, 0
    for k in range(3):
        for j in range(3):
            for i in range(3):
                nid += 1
                nodes[(i, j, k)] = nid
    elems = []
    for k in range(2):
        for j in range(2):
            for i in range(2):
                c = [nodes[(i, j, k)], nodes[(i + 1, j, k)],
                     nodes[(i + 1, j + 1, k)], nodes[(i, j + 1, k)],
                     nodes[(i, j, k + 1)], nodes[(i + 1, j, k + 1)],
                     nodes[(i + 1, j + 1, k + 1)], nodes[(i, j + 1, k + 1)]]
                elems.append(c)
    base = [n for (i, j, k), n in sorted(nodes.items()) if k == 0]
    top = [n for (i, j, k), n in sorted(nodes.items()) if k == 2]
    s = ["*KEYWORD", "*TITLE", "round-10 A5/A6 fixture",
         "*CONTROL_IMPLICIT_AUTO", _row(0, 11, 5, 0.0, 0.0, 0.0, 0, 0)]
    if dynamic:
        s += ["*CONTROL_IMPLICIT_DYNAMICS",
              _row(1, 0.5, 0.25, 0.0, "1.0E28", "1.0E28", 0, 0.0)]
    s += ["*CONTROL_IMPLICIT_GENERAL", _row(1, 1.0e-4, 2, 1, 2, 0, 0, 0),
          "*CONTROL_IMPLICIT_SOLUTION",
          _row(12, 11, 15, 0.001, 0.01, "1.0E10", 0.9, 1.0),
          "*CONTROL_TERMINATION", _row(0.02, 0, 0.0, 0.0, 0.0, 0),
          "*DATABASE_GLSTAT", _row(1.0e-4),
          "*PART", "block", _row(1, 1, 1, 0, 0, 0, 0, 0),
          "*SECTION_SOLID", _row(1, 1, 0),
          "*MAT_ELASTIC", _row(1, 8.0e-9, 200000.0, 0.3, 0.0, 0.0, 0, 0),
          "*DEFINE_CURVE", _row(1, 0, 0.0, 0.0, 0.0, 0.0, 0, 0),
          f"{0.0:>20}{1.0:>20}", f"{1.0:>20}{1.0:>20}",
          "*SET_NODE_LIST", _row(1, 0.0, 0.0, 0.0, 0.0), _row(*base[:8]),
          _row(*base[8:]),
          "*SET_NODE_LIST", _row(2, 0.0, 0.0, 0.0, 0.0), _row(*top[:8]),
          _row(*top[8:]),
          "*BOUNDARY_SPC_SET", _row(1, 0, 1, 1, 1, 1, 1, 1),
          "*LOAD_NODE_SET", _row(2, 3, 1, -100.0, 0, 0, 0, 0)]
    if damping:
        s.append(damping.rstrip("\n"))
    s += ["*ELEMENT_SOLID"]
    for e, c in enumerate(elems, 1):
        s.append(f"{e:>8}{1:>8}" + "".join(f"{n:>8}" for n in c))
    s += ["*NODE"]
    for (i, j, k), n in sorted(nodes.items(), key=lambda t: t[1]):
        s.append(f"{n:>8}{10.0 * i:>16}{10.0 * j:>16}{10.0 * k:>16}")
    return "\n".join(s) + "\n" + extra + "*END\n"


def _engine_block(engine: str, head: str):
    """The data rows under the engine card *head* (None when absent)."""
    lines = engine.splitlines()
    if head not in lines:
        return None
    out = []
    for ln in lines[lines.index(head) + 1:]:
        if ln.startswith(("/", "#")):
            break
        out.append(ln)
    return out


class A5EndFixpoint(unittest.TestCase):

    def test_the_two_lines_of_fixpoint_count_1(self):
        _r, s_def, e_def = _convert(_hex_block())
        _r, s_fp1, e_fp1 = _convert(_hex_block(), implicit_end_fixpoint=False,
                                    fixpoint_count=1)
        self.assertEqual((s_def, e_def), (s_fp1, e_fp1))
        self.assertEqual(_engine_block(e_def, "/IMPL/DT/FIXPOINT"),
                         ["                0.02"])
        lines = e_def.splitlines()
        i = lines.index("/IMPL/DT/2")
        self.assertEqual(lines[i + 2:i + 4], ["/IMPL/DT/FIXPOINT",
                                              "                0.02"])

    def test_the_opt_out_restores_the_ed52c93_engine_file(self):
        _r, s_off, e_off = _convert(_hex_block(),
                                    implicit_end_fixpoint=False)
        _r, s_def, e_def = _convert(_hex_block())
        self.assertEqual(s_off, s_def)
        self.assertNotIn("/IMPL/DT/FIXPOINT", e_off)
        moved = [ln for ln in e_def.splitlines()
                 if ln not in e_off.splitlines()]
        self.assertEqual(moved, ["/IMPL/DT/FIXPOINT",
                                 "                0.02"])
        self.assertEqual(len(e_def.splitlines()),
                         len(e_off.splitlines()) + 2)

    def test_the_sentence_names_the_mechanism_and_the_sliver(self):
        res, _s, _e = _convert(_hex_block())
        hits = [w for w in res.warnings if w.startswith("/IMPL/DT/FIXPOINT")]
        self.assertEqual(len(hits), 1, hits)
        for needle in ("imp_dt.F:53-56", "resol.F:8317-8318",
                       "9 keys / 5 models", "-14.44 % at t 0.01839 -> "
                       "-33.66 % at t 0.02", "+1343.37 -> -78.46 %",
                       "imp_dt.F:311-320", "6.06e8", "0.160 -> 170.1",
                       "read the row before it"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("gain", hits[0].lower())
        res, _s, _e = _convert(_hex_block(), implicit_end_fixpoint=False)
        self.assertFalse([w for w in res.warnings
                          if w.startswith("/IMPL/DT/FIXPOINT")])

    def test_static_riks_and_a_grid_are_untouched(self):
        _r, _s, eng = _convert(_hex_block(dynamic=False))
        self.assertNotIn("/IMPL/DT/FIXPOINT", eng)
        _r, _s, eng = _convert(_hex_block(), fixpoint_count=4)
        # k/4 x 0.02: 0.005 0.01 0.015 0.02 on one line
        self.assertEqual(_engine_block(eng, "/IMPL/DT/FIXPOINT"),
                         ["               0.005                0.01"
                          "               0.015                0.02"])
        # NSOLVR 6 asks for arc-length (Vol I R17 p.12-354); with
        # --arclength-riks the step card is /IMPL/DT/3, under which the
        # engine disarms every fix point (lectur.F:3523-3532): none written
        riks = _hex_block().replace(
            _row(12, 11, 15, 0.001, 0.01, "1.0E10", 0.9, 1.0),
            _row(6, 11, 15, 0.001, 0.01, "1.0E10", 0.9, 1.0))
        self.assertIn(_row(6, 11, 15, 0.001, 0.01, "1.0E10", 0.9, 1.0), riks)
        _r, _s, eng = _convert(riks, arclength_riks=True)
        self.assertIn("/IMPL/DT/3", eng.splitlines())
        self.assertNotIn("/IMPL/DT/FIXPOINT", eng)
        _r, _s, eng = _convert(riks)                 # the control: /IMPL/DT/2
        self.assertIn("/IMPL/DT/FIXPOINT", eng.splitlines())

    def test_a_stated_imass_0_is_static_and_untouched(self):
        """*CONTROL_IMPLICIT_DYNAMICS stated with IMASS 0 is a static
        analysis: the deck gets no /IMPL/DYNA card and no end fix point,
        the same engine file as a deck without the card
        (writer/assembly._implicit_end_fixpoint keys on IMASS > 0)."""
        dyn1 = _row(1, 0.5, 0.25, 0.0, "1.0E28", "1.0E28", 0, 0.0)
        dyn0 = _row(0, 0.5, 0.25, 0.0, "1.0E28", "1.0E28", 0, 0.0)
        deck = _hex_block().replace(dyn1, dyn0)
        self.assertIn(dyn0, deck)
        res, _s, eng = _convert(deck)
        self.assertNotIn("/IMPL/DT/FIXPOINT", eng)
        self.assertFalse([ln for ln in eng.splitlines()
                          if ln.startswith("/IMPL/DYNA")], eng)
        self.assertFalse([w for w in res.warnings
                          if w.startswith("/IMPL/DT/FIXPOINT")])
        _r, _s, eng_none = _convert(_hex_block(dynamic=False))
        self.assertEqual(eng, eng_none)


# ═════════════════════════════════════════════════════════════════════════════
# A11  the *CONTROL_TIMESTEP texts (the deletion-floor bytes:
#      tests/test_dt_deletion_floor.py)
# ═════════════════════════════════════════════════════════════════════════════

class A11Texts(unittest.TestCase):

    _CURVE = ("*DEFINE_CURVE\n" + _row(5) + "\n"
              + f"{0.0:>20}{0.5:>20}\n{1.0:>20}{0.5:>20}\n")

    def _plate(self, **kw):
        import test_cardstack_pipeline_engine as _te
        return _te._plate(**kw)

    def test_a_tssfac_curve_on_dt2ms_0_is_named_with_its_range(self):
        """f3: the DT2MS >= 0 path used to drop a TSSFAC < 0 curve in
        silence (no /DT, no text, the curve an orphan /FUNCT)."""
        res, _s, eng = _convert(self._plate(dt2ms=0.0, tssfac=-5.0,
                                            extra=self._CURVE))
        self.assertNotIn("/DT", eng.splitlines())
        self.assertTrue(_has(res.warnings, "*CONTROL_TIMESTEP TSSFAC=-5 < 0 "
                             "(load curve 5, the scale factor as a function "
                             "of time, Vol I R17 p.12-584) is NOT converted",
                             "freform.F:1033-1043", "default scale 0.9",
                             "contrl.F:1148-1149",
                             "the curve ranges 0.5 .. 0.5 over 0 .. ENDTIM "
                             "0.001", "1.8x the asked step"))

    def test_the_curve_range_is_the_stored_points_once_scaled(self):
        """handle_define_curve stores ((x + OFFA) SFA, (y + OFFO) SFO): the
        range is read from those points as they are (SFO 2 on 0.25 -> 0.5),
        never scaled a second time (0.25 x 2 x 2 = 1 would be wrong)."""
        curve = ("*DEFINE_CURVE\n" + _row(5, 0, 1.0, 2.0) + "\n"
                 + f"{0.0:>20}{0.25:>20}\n{1.0:>20}{0.25:>20}\n")
        res, _s, _e = _convert(self._plate(dt2ms=0.0, tssfac=-5.0,
                                           extra=curve))
        self.assertTrue(_has(res.warnings, "the curve ranges 0.5 .. 0.5"))
        self.assertFalse(_has(res.warnings, "the curve ranges 1 .. 1"))
        # an undefined curve is said so
        res, _s, _e = _convert(self._plate(dt2ms=0.0, tssfac=-7.0))
        self.assertTrue(_has(res.warnings, "TSSFAC=-7 < 0",
                             "load curve 7 is not defined in the deck"))

    def test_the_tmin_clause_reads_dtmin(self):
        res, _s, _e = _convert(self._plate(dt2ms=0.0, tssfac=0.8))
        self.assertTrue(_has(res.warnings, "TSSFAC=0.8", "LS-DYNA has no "
                             "floor either: *CONTROL_TERMINATION DTMIN is 0"))
        deck = self._plate(dt2ms=0.0, tssfac=0.8).replace(
            "*CONTROL_TERMINATION\n" + _row(0.001, "", "", "", ""),
            "*CONTROL_TERMINATION\n" + _row(0.001, "", 0.3, "", ""))
        self.assertIn(_row(0.001, "", 0.3, "", ""), deck)
        res, _s, _e = _convert(deck)
        self.assertTrue(_has(res.warnings, "TSSFAC=0.8", "LS-DYNA's own "
                             "floor tsmin = DTMIN x dtstart "
                             "(*CONTROL_TERMINATION DTMIN=0.3, Vol I R17 "
                             "p.12-558) is not converted."))
        for w in res.warnings:
            self.assertNotIn("because LS-DYNA TSLIMT is not converted", w)


class A12QuadFloorHelp(unittest.TestCase):
    """A12: --dt-del on the routed 2-D deck writes /DT/QUAD/DEL (the bytes:
    tests/test_cardstack_pipeline_engine.Dt2msTexts
    .test_dt_del_on_the_routed_2d_deck_writes_the_quad_floor); the help and
    README name the card and its measurement."""

    def test_the_dt_del_help_names_the_quad_card(self):
        text = _flag_help("--dt-del")
        for needle in ("/DT/QUAD/DEL (Tsca = TSSFAC, else the 2-D default "
                       "0.67)", "quad 7 deleted at t 1.562",
                       "Without it no deletion floor is written since round "
                       "10 (A11)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        readme = _t7._collapse(_readme())
        self.assertIn("`--dt-del` writes **`/DT/QUAD/DEL`** since round 10",
                      readme)


class A6ImplicitDamping(unittest.TestCase):
    """The starter /DAMP is inert on an implicit run (named by default);
    --implicit-rayleigh-damping (opt-in) writes /IMPL/DYNA/DAMP."""

    def test_the_default_names_the_inert_damp(self):
        res, st, eng = _convert(_hex_block())
        self.assertIn("/DAMP/", st)
        self.assertNotIn("/IMPL/DYNA/DAMP", eng)
        hits = [w for w in res.warnings
                if "the starter /DAMP has NO effect on an implicit run" in w]
        self.assertEqual(len(hits), 1, hits)
        for needle in ("resol.F:7216-7219", "resol.F:6406 / :6547",
                       "UNDAMPED", "IE RMS 4.51 -> 5.27 %",
                       "KE RMS 2.66 -> 7.56 %"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])
        self.assertNotIn("gain", hits[0].lower())
        # a static deck: named, no 'undamped' claim about a dynamic run
        res, _s, eng = _convert(_hex_block(dynamic=False))
        self.assertTrue(_has(res.warnings, "the starter /DAMP has NO effect",
                             "(this deck is static: no "
                             "*CONTROL_IMPLICIT_DYNAMICS)"))
        self.assertNotIn("/IMPL/DYNA/DAMP", eng)
        # no /DAMP, no sentence
        res, _s, _e = _convert(_hex_block(damping=""))
        self.assertFalse(_has(res.warnings, "the starter /DAMP has NO effect"))

    def test_the_opt_in_writes_the_card_after_dyna_2(self):
        res, st, eng = _convert(_hex_block(), implicit_rayleigh_damping=True)
        lines = eng.splitlines()
        i = lines.index("/IMPL/DYNA/2")
        self.assertEqual(lines[i + 2:i + 4],
                         ["/IMPL/DYNA/DAMP",
                          "              11.535                   0"])
        self.assertIn("/DAMP/", st)                  # the starter card stays
        self.assertTrue(_has(res.warnings, "--implicit-rayleigh-damping: "
                             "/IMPL/DYNA/DAMP alpha = 11.535, beta 0"))
        _r, st0, eng0 = _convert(_hex_block())
        self.assertEqual(st, st0)
        self.assertEqual([ln for ln in lines if ln not in eng0.splitlines()],
                         ["/IMPL/DYNA/DAMP",
                          "              11.535                   0"])
        self.assertEqual(len(lines), len(eng0.splitlines()) + 2)

    def test_the_refusals_are_named(self):
        cases = (
            ({"dynamic": False}, "the deck is static"),
            ({"damping": "*DAMPING_GLOBAL\n" + _row(7, 11.535) + "\n"
              + "*DEFINE_CURVE\n" + _row(7) + "\n"
              + f"{0.0:>20}{11.535:>20}\n{1.0:>20}{11.535:>20}\n"},
             "LCID 7 > 0"),
            ({"damping": "*DAMPING_GLOBAL\n"
              + _row(0, 11.535, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0) + "\n"},
             "STX..SRZ are not uniform"),
        )
        for kw, needle in cases:
            with self.subTest(needle=needle):
                res, _s, eng = _convert(_hex_block(**kw),
                                        implicit_rayleigh_damping=True)
                self.assertNotIn("/IMPL/DYNA/DAMP", eng)
                self.assertTrue(_has(res.warnings, "--implicit-rayleigh-"
                                     "damping: /IMPL/DYNA/DAMP not written",
                                     needle), res.warnings)

    def test_a_uniform_scale_multiplies_valdmp(self):
        # Vol I R17 p.15-9 Remark 2: all six 0 -> unity; 0.5 x 11.535 = 5.7675
        deck = _hex_block(damping="*DAMPING_GLOBAL\n"
                          + _row(0, 11.535, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
                          + "\n")
        _r, _s, eng = _convert(deck, implicit_rayleigh_damping=True)
        self.assertEqual(_engine_block(eng, "/IMPL/DYNA/DAMP"),
                         ["              5.7675                   0"])


# ═════════════════════════════════════════════════════════════════════════════
# A13  the routed N2S caution (text only)
# ═════════════════════════════════════════════════════════════════════════════

class A13N2sCaution(unittest.TestCase):

    #: the two census decks (the round-10 g3l 4-node elastic-base coupon and
    #: the 9-node frictionless sliding block), repo fixtures since round 10;
    #: their bytes at ed52c93 and on this branch (A13 is text only). Their
    #: SOLVER outcome is not pinned: it varies run to run (the sentence).
    _FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "round10")
    _SHA = {
        "b6t_g3l": (
            "3f8e5fc645a8edc7807ae532d9d27238fed4b9968a47740fc0114d1c2d5b7d63",
            "185c209d0a3ed9395a76689916e194c44b48c81ec251659a80bcde1f20653e49"),
        "slide_mu0": (
            "5260b17e41cbab3631597e2e763a0aa9f680961f41232661bff3d5b7b88ba1bc",
            "a79c4e779ab95248fcb149d3a5020ec332cecf3e1246d56caa876e20b16c3bc7"),
    }

    def test_the_two_fixtures_convert_to_the_route_and_name_it(self):
        for stem, (s_sha, e_sha) in self._SHA.items():
            with self.subTest(fixture=stem):
                with open(os.path.join(self._FIX, stem + ".k")) as fh:
                    deck = fh.read()
                res, st, eng = _convert(deck)
                self.assertEqual(_tp._sha(st), s_sha)
                self.assertEqual(_tp._sha(eng), e_sha)
                self.assertEqual([ln for ln in st.splitlines()
                                  if ln.startswith("/INTER/")],
                                 ["/INTER/TYPE7/90002", "/INTER/TYPE7/90001"])
                self.assertTrue(_has(res.warnings, "5 of 7 runs NORMAL",
                                     "0.02 mm inside it"))
                # --no-implicit-n2s-type7 keeps the TYPE25 (round 9)
                _r, st25, _e = _convert(deck, implicit_n2s_type7=False)
                self.assertIn("/INTER/TYPE25/90001", st25.splitlines())

    def test_the_measured_variance_is_named_in_code_help_and_readme(self):
        from k2rad import cli
        from k2rad.writer import contacts
        texts = {"code": _t7._collapse(contacts._N2S_TYPE7_MEASURED),
                 "help": _t7._collapse(cli.build_parser().format_help()),
                 "readme": _t7._collapse(_readme())}
        for where, text in texts.items():
            with self.subTest(where=where):
                self.assertIn("5 of 7 runs NORMAL", text)
        # the round-9 instruction stays
        self.assertIn("CHECK THAT THE CONTACT CARRIES LOAD", texts["code"])


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
    # A3: the _ELFORM_ALWAYS_QEPH comment's wrong reason (writer/common; the
    # '#' rule: one needle per comment line)
    "QEPH regardless of the option: already",
    "reduced-integration / co-rotational forms whose Radioss counterpart is",
    # A3: the README K-31 bullet's help sentence
    "text names only the `*INITIAL_STRESS_SHELL` exclusion",
    # A4: the opt-in wording of --dt2ms-tssfac-product (the GUI label; the
    # ed52c93 step sentences; the product on /DT/AMS too)
    "Opt-in: mass-scaled Tmin",
    "--dt2ms-tssfac-product writes the product",
    "(Vol I R17 p.12-585) [--dt2ms-tssfac-product]",
    "the /DT/NODA/CST and /DT/AMS Tmin",
    "`/DT/NODA/CST` and `/DT/AMS` Tmin",
    "on `/DT/AMS` too",
    # A11: TSLIMT read as the stop / deletion field (the /DT sentences, the
    # ControlTimestep comments, the --dt-del help / GUI / README texts)
    "because LS-DYNA TSLIMT is not converted",
    "LS-DYNA's equivalent (TSLIMT) is a different field",
    "Carried to /DT/<elem>/DEL Tmin",
    "the user's explicit consent to LOSE ELEMENTS",
    "a deletion floor is emitted only when the deck asks",
    "a deck that asks for deletion itself",
    "either the deck asks (`ERODE=1`",
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
    ("k2rad/writer/common.py",
     "They are FULLY integrated forms in LS-DYNA (Vol I R17 p.41-64), and"),
    ("README.md",
     "R14 round 10 the `--help` text names every condition above"),
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
        "--dt2ms-tssfac-product": "dt2ms_tssfac_product",
        "--implicit-end-fixpoint": "implicit_end_fixpoint",
        "--erode-tsmin-rule": "erode_tsmin_rule",
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
        "--dt2ms-tssfac-product": ("Vol I R17 p.12-585",
                                   "convertcards.cxx:173-174",
                                   "convertcards.cxx:233-234",
                                   "13889 cycles = LS-DYNA's 13889",
                                   "KE RMS 8.54 -> 1.74 %"),
        "--implicit-end-fixpoint": ("imp_dt.F:53-56", "resol.F:8317-8318",
                                    "lectur.F:3523-3532", "9 keys / 5 models",
                                    "34 -> 35 cycles",
                                    "-14.44 % at t 0.01839 -> -33.66 % at t "
                                    "0.02", "+1343.37 -> -78.46 %",
                                    "6.06e8"),
        "--erode-tsmin-rule": ("p.12-584 / 12-585", "p.12-558",
                               "10 of 10 bricks at t 2.988e-4"),
    }

    def test_the_k41_flag_is_on_by_default_now(self):
        """A4 flips the CardStack opt-in: its help says ON (it said 'OFF by
        default'), the README bullet says ON, the GUI label ends '- ON'."""
        text = _flag_help("--dt2ms-tssfac-product")
        self.assertIn("ON by default since round 10", text)
        self.assertNotIn("OFF by default", text)
        self.assertIn("`--dt2ms-tssfac-product` / `--no-dt2ms-tssfac-product` "
                      "— **ON by default", _t7._collapse(_readme()))


class Round10OptInWiring(_t8.Round8OptInWiringB):
    """The round-10 part-A-i OPT-IN lever (default OFF): parser + --no-
    twin, README prose (the POSITIVE spelling) and its own ### heading, the
    --help figures, the GUI end to end, convert() / ConvertOptions default
    False and cli.main()'s call."""

    _OPT_IN = {"--implicit-rayleigh-damping": "implicit_rayleigh_damping"}
    _HELP_FIGURES = {
        "--implicit-rayleigh-damping": ("imp_dyna.F:1810-1828",
                                        "resol.F:6406 / :6547",
                                        "IE RMS 4.51 -> 5.27 %",
                                        "KE RMS 2.66 -> 7.56 %",
                                        "freimpl.F:171", "OFF by default"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# PART A-ii.  A7  *MAT_VACUUM -> a LAW6 light fluid (default;
# --no-vacuum-light-fluid) + the ALE velocity inlet -> /SURF/SEG +
# /EBCS/INLET/VP (default; --no-ale-inflow-ebcs)
# ═════════════════════════════════════════════════════════════════════════════

_FIX10 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "fixtures", "round10")

#: the coupon's prescribed-motion row (nsid 1, DOF 2, VAD 0, curve 1, SF 1)
_A7_BPM = ("         1         2         0         1       1.0         0"
           "       0.0       0.0")
#: its water material pair and its vacuum card
_A7_WATER = ("*MAT_NULL\n         1    1.0E-9       0.0       0.0       0.0"
             "       0.0       0.0       0.0\n*EOS_GRUNEISEN\n         1"
             " 1500000.0       0.0       0.0       0.0       0.0       0.0"
             "       0.0\n       0.0\n")
_A7_VACUUM = "*MAT_VACUUM\n         2   1.0E-14\n"
_A7_AMMG = ("*ALE_MULTI-MATERIAL_GROUP\n         1         1\n"
            "         2         1\n")


def _a7_coupon(*edits) -> str:
    """The A7 coupon ``tests/fixtures/round10/r10_ale_inlet_coupon.k`` (the
    part-A-ii research spec's ``inletc.k``, byte for byte): a 3 x 1 x 1
    column of 10 mm ELFORM-11 bricks - the vacuum cell (part 2, brick 1) at
    the bottom, two water cells (part 1) above - one AMMG of parts 1 and 2,
    a VAD-0 ``*BOUNDARY_PRESCRIBED_MOTION_SET`` DOF 2 at -20000 mm/s on the
    four top nodes 13-16, which hold x / z by ``*NODE`` TC 6. Each (old,
    new) edit is applied once (asserted)."""
    with open(os.path.join(_FIX10, "r10_ale_inlet_coupon.k")) as fh:
        deck = fh.read()
    for old, new in edits:
        assert deck.count(old) == 1, old
        deck = deck.replace(old, new)
    return deck


def _block(starter: str, header: str):
    """The lines of one card block after its header (up to the next '/')."""
    lines = starter.splitlines()
    i = lines.index(header)
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("/"):
            break
        out.append(ln)
    return out


def _cards(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _a7_state(deck: str, options):
    """The parsed ConversionState of a deck string, with *options*."""
    import tempfile
    from k2rad.handlers import dispatch
    from k2rad.parser import parse_k_file
    from k2rad.state import ConversionState
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    state.options = options
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


class VacuumLightFluid(unittest.TestCase):
    """A7 1a (default ON): a *MAT_VACUUM part of an Iale deck whose AMMG
    holds exactly one other material, a *MAT_NULL + *EOS_* LAW6 carrier, is
    written as a LAW6 light-fluid copy of that fluid under the vacuum's own
    MID - RHO_I = the vacuum RO, the fluid's /EOS copied with RHO_0 = the
    fluid RO (hm_read_eos_gruneisen.F:117-123: an /EOS RHO_0 > 0 is the
    starter's reference density), Pmin -1e-20, the fluid's Nu - instead of
    /MAT/VOID, which DELETES the fluid that advects into it (stagnation_A /
    _B: NEGATIVE RHO at cycle 832). Every other case keeps /MAT/VOID and is
    named; --no-vacuum-light-fluid writes /MAT/VOID."""

    def test_the_coupon_writes_the_light_fluid(self):
        res, st, _eng = _convert(_a7_coupon())
        self.assertNotIn("/MAT/VOID/2", st)
        mat = _block(st, "/MAT/HYD_VISC/2")
        self.assertEqual(mat[0], "VACUUM_2")
        self.assertEqual(float(mat[2]), 1e-14)                 # RHO_I
        self.assertEqual((float(mat[4][:20]), float(mat[4][20:40])),
                         (0.0, -1e-20))                        # Nu, Pmin
        eos = _block(st, "/EOS/GRUNEISEN/2")
        self.assertEqual(float(eos[2][:20]), 1.5e6)            # C
        self.assertEqual(float(eos[4][60:80]), 1e-9)           # RHO_0
        # the water's own carrier is untouched
        self.assertEqual(float(_block(st, "/MAT/HYD_VISC/1")[2]), 1e-9)
        self.assertTrue(_has(
            res.warnings, "*MAT_VACUUM 2 -> /MAT/HYD_VISC/2: a LAW6 "
            "LIGHT-FLUID copy of its *ALE_MULTI-MATERIAL_GROUP partner, fluid "
            "MID 1", "RHO_0 = the fluid RO 1e-09 and Pmin -1e-20",
            "NEGATIVE RHO element 260 at cycle 832",
            "with the ALE inlet as well KE RMS 14.40 %, IE RMS 206.79 %",
            "--no-vacuum-light-fluid writes /MAT/VOID."))

    def test_the_emitted_law_map_says_six(self):
        """mesh._target_mat_law is the ONE mid -> law map (the /XREF gate,
        the zero-density floor, the LAW51 screen read it): the vacuum MID
        is law 6 where the copy is written, 0 where it is not."""
        from k2rad.state import ConvertOptions
        from k2rad.writer.mesh import _target_mat_law
        for on, law in ((True, 6), (False, 0)):
            with self.subTest(vacuum_light_fluid=on):
                st = _a7_state(_a7_coupon(),
                               ConvertOptions(vacuum_light_fluid=on))
                self.assertEqual(_target_mat_law(st, 2), law)

    def test_every_refusal_keeps_the_void_and_says_why(self):
        mid3 = ("*PART\nsecond fluid\n         3         1         3\n"
                "*MAT_NULL\n         3    1.0E-9\n*EOS_GRUNEISEN\n         3"
                " 1500000.0\n")
        cases = {
            "a LAW44 partner (cylinder_impact-shaped)": (
                ((_A7_WATER, "*MAT_PLASTIC_KINEMATIC\n         1    7.8E-9"
                  "  200000.0       0.3     200.0\n"),),
                "its AMMG partner MID 1 is *MAT_PLASTIC_KINEMATIC -> "
                "/MAT/LAW44, not a *MAT_NULL + *EOS_* fluid k2rad writes as "
                "/MAT/HYD_VISC"),
            "a LAW0 partner (wavehitcol-shaped: *EOS_MURNAGHAN)": (
                ((_A7_WATER, "*MAT_NULL\n         1    1.0E-9\n"
                  "*EOS_MURNAGHAN\n         1       7.0  2.2E+03       1.0"
                  "\n"),),
                "its AMMG partner MID 1 is a *MAT_NULL with no converted "
                "*EOS_* (its *PART EOSID 1 names no converted *EOS_*), so it "
                "is itself /MAT/VOID (LAW0)"),
            "two partners": (
                ((_A7_AMMG, _A7_AMMG + "         3         1\n"),
                 ("*SET_NODE_LIST\n", mid3 + "*SET_NODE_LIST\n")),
                "its *ALE_MULTI-MATERIAL_GROUP holds 2 other materials "
                "[1, 3], not one fluid"),
            "RO 0": (
                ((_A7_VACUUM, "*MAT_VACUUM\n         2       0.0\n"),),
                "its RO 0 is not > 0 (a /MAT/HYD_VISC needs RHO_I > 0, "
                "ERROR 683)"),
            "no AMMG": (
                ((_A7_AMMG, ""),),
                "it is in no *ALE_MULTI-MATERIAL_GROUP"),
            "an /EOS id clash": (
                ((_A7_VACUUM, _A7_VACUUM + "*EOS_GRUNEISEN\n         2"
                  " 1500000.0\n"),),
                "an *EOS_* with id 2 is already in the deck"),
        }
        for name, (edits, why) in cases.items():
            with self.subTest(case=name):
                res, st, _e = _convert(_a7_coupon(*edits))
                self.assertIn("/MAT/VOID/2", st)
                self.assertNotIn("/MAT/HYD_VISC/2", st)
                self.assertTrue(_has(
                    res.warnings, "*MAT_VACUUM 2 stays /MAT/VOID/2 (LAW0): "
                    "the light-fluid copy (round 10, A7) is not written "
                    "because " + why,
                    "whatever advects into it is DELETED"), res.warnings)
                # a LAW0 vacuum is left in the ALE domain: no inlet either
                self.assertNotIn("/EBCS/INLET/VP/", st)
                self.assertTrue(_cards(st, "/IMPVEL/"))
                self.assertTrue(_has(
                    res.warnings, "the ALE inlet (/EBCS/INLET/VP, round 10, "
                    "A7) is NOT written - the ALE domain still holds the LAW0 "
                    "/MAT/VOID part(s)"))

    def test_the_opt_out_writes_the_void(self):
        """--no-vacuum-light-fluid = the A-i HEAD bytes (the LAW0 vacuum is
        left, so the inlet refuses by name and the /IMPVEL stays)."""
        res, st, eng = _convert(_a7_coupon(), vacuum_light_fluid=False)
        self.assertEqual(_tp._sha(st), _A7_COUPON_AI_SHA[0])
        self.assertEqual(_tp._sha(eng), _A7_COUPON_AI_SHA[1])
        self.assertIn("/MAT/VOID/2", st)
        self.assertFalse(_has(res.warnings, "LIGHT-FLUID copy"))
        self.assertTrue(_has(res.warnings, "/MAT/VOID part(s) [2]",
                             "stays an /IMPVEL"))
        # both opt-outs: the same bytes
        _r, st2, _e2 = _convert(_a7_coupon(), vacuum_light_fluid=False,
                                ale_inflow_ebcs=False)
        self.assertEqual(st2, st)


def _block_grid(nx: int, nz: int, h: float = 10.0, inlet_j: int = 1,
                extra=()) -> str:
    """An nx x 1 x nz ELFORM-11 water block (*MAT_NULL + *EOS_GRUNEISEN,
    10 mm cells, y from 0 to h), the nodes of its top (inlet_j 1, y = h) or
    bottom (inlet_j 0, y = 0) layer - and the *extra* node ids - in
    *SET_NODE_LIST 1, the layer holding x / z by TC 6, under a VAD-0 DOF-2
    row at -20000 mm/s. The bottom layer is each brick's face (1 2 3 4),
    whose node order points INTO the brick. Node ids run y-layer, then x,
    then z (nx 2, nz 1: bottom 1-6, top 7-12; x = 10 bottom: 3, 4)."""
    nodes, ids, top = [], {}, []
    nid = 0
    for j, y in enumerate((0.0, h)):
        for i in range(nx + 1):
            for k in range(nz + 1):
                nid += 1
                ids[(i, j, k)] = nid
                tc = 6 if j == inlet_j else 0
                nodes.append(f"{nid:8d}{i * 10.0:16.1f}{y:16.1f}"
                             f"{k * 10.0:16.1f}{tc:8d}{0:8d}")
                if j == inlet_j:
                    top.append(nid)
    elems, eid = [], 0
    for i in range(nx):
        for k in range(nz):
            eid += 1
            n = [ids[(i, 0, k)], ids[(i, 0, k + 1)], ids[(i + 1, 0, k + 1)],
                 ids[(i + 1, 0, k)], ids[(i, 1, k)], ids[(i, 1, k + 1)],
                 ids[(i + 1, 1, k + 1)], ids[(i + 1, 1, k)]]
            elems.append(f"{eid:8d}{1:8d}" + "".join(f"{x:8d}" for x in n))
    top = top + list(extra)
    rows = ["".join(f"{x:10d}" for x in top[r:r + 8])
            for r in range(0, len(top), 8)]
    return ("*KEYWORD\n*CONTROL_TERMINATION\n    1.0E-4\n"
            "*PART\nwater\n         1         1         1         1\n"
            "*SECTION_SOLID\n         1        11         0\n" + _A7_WATER
            + "*DEFINE_CURVE\n         1\n                 0.0"
            "            -20000.0\n                 1.0            -20000.0\n"
            "*SET_NODE_LIST\n         1\n" + "\n".join(rows) + "\n"
            "*BOUNDARY_PRESCRIBED_MOTION_SET\n" + _A7_BPM + "\n"
            "*ELEMENT_SOLID\n" + "\n".join(elems) + "\n*NODE\n"
            + "\n".join(nodes) + "\n*END\n")


def _a7_guard_decks():
    """The two A7 guards: the coupon with the vacuum removed (part 2 on the
    water) and both sections ELFORM 6 - k2rad's Lagrangian channel, Iale 0 -
    and the ELFORM-11 coupon with neither a vacuum nor a prescribed motion."""
    no_vac = ((_A7_VACUUM, ""), (_A7_AMMG, ""),
              ("vacuum\n         2         2         2",
               "vacuum\n         2         2         1"))
    return {
        "channel": _a7_coupon(*no_vac,
                              ("         1        11         0",
                               "         1         6         0"),
                              ("         2        11         0",
                               "         2         6         0")),
        "plain": _a7_coupon(*no_vac, ("*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                                      + _A7_BPM + "\n", "")),
    }


def _node_xyz(starter: str):
    out = {}
    for ln in _block(starter, "/NODE"):
        if ln.startswith("#") or not ln.strip():
            continue
        out[int(ln[:10])] = (float(ln[10:30]), float(ln[30:50]),
                             float(ln[50:70]))
    return out


def _surf_rows(starter: str, header: str):
    return [[int(ln[i:i + 10]) for i in range(0, 50, 10)]
            for ln in _block(starter, header)
            if ln.strip() and not ln.startswith("#") and ln[:10].strip()
            .isdigit() and len(ln) >= 50]


class AleInflowEbcs(unittest.TestCase):
    """A7 1b (default ON): a VAD-0 prescribed-motion row whose nodes cover
    boundary faces of an EMITTED Iale brick becomes the /SURF/SEG of those
    faces (outward order) + /EBCS/INLET/VP (vel_flag 1, the row's /FUNCT x
    Fscale on its DOF, the other two 0; one material row: alpha 1, the face
    bricks' density, p 0), in place of the covered nodes' /IMPVEL - an
    /IMPVEL on an Eulerian ALE face admits no material (aflux3.F:488-524).

    The coupon's branch bytes through the starter + engine (round 10,
    part A-ii, `C:/Users/pmqua/rcv_r10i_implA2_ic_a7`, nt 4): `FLUID INLET
    EBCS NUMBER . . . : 90002 inlet_1`, `NUMBER OF SEGMENTS FOUND . . . 1`,
    0 ERROR(S) / 0 WARNING(S); engine NORMAL TERMINATION in 20 cycles to t
    9.936e-5 (the /IMPVEL bytes: NORMAL in 19) - as the part-A-ii research
    spec's own run of these bytes (`rcv_r10i_resA2_g5_ic_a7`)."""

    def test_the_coupon_writes_the_inlet(self):
        res, st, _e = _convert(_a7_coupon())
        self.assertEqual(_surf_rows(st, "/SURF/SEG/90001"),
                         [[1, 13, 14, 15, 16]])
        self.assertEqual(_block(st, "/EBCS/INLET/VP/90002")[:7], [
            "inlet_1",
            "#  surf_ID  vel_flag",
            "     90001         1",
            "# fct_IDvx            Fscalevx  fct_IDvy            Fscalevy  "
            "fct_IDvz            Fscalevz",
            "         0                   0         1                   1"
            "         0                   0",
            "# fct_IDvf            Fscalevf fct_IDrho           Fscalerho "
            "fct_IDp_e           Fscalep_e",
            "         0                   1         0        1.000000E-09"
            "         0                   0"])
        self.assertEqual(_cards(st, "/IMPVEL/"), [])
        self.assertNotIn("SET_1", st)            # no /GRNOD for the set
        self.assertTrue(_has(
            res.warnings, "*BOUNDARY_PRESCRIBED_MOTION_SET nsid=1 dof=2 "
            "(VAD 0) drives 1 boundary face(s) of the ALE (Iale >= 1) mesh -> "
            "/SURF/SEG/90001 + /EBCS/INLET/VP/90002", "inflow density 1e-09",
            "aflux3.F:488-524", "KE RMS 53.09 -> 14.40 %",
            "--no-ale-inflow-ebcs keeps the /IMPVEL."))

    def test_four_faces_of_a_two_by_two_inlet_point_outward(self):
        """Top layer (each brick's face 5 6 7 8, already outward) and bottom
        layer (face 1 2 3 4, whose order points INTO the brick and must be
        reversed): every written segment's (n2 - n1) x (n4 - n1) points out
        of the block."""
        for inlet_j, sign in ((1, 1.0), (0, -1.0)):
            res, st, _e = _convert(_block_grid(2, 2, inlet_j=inlet_j))
            rows = _surf_rows(st, "/SURF/SEG/90001")
            self.assertEqual(len(rows), 4)
            xyz = _node_xyz(st)
            for _sid, n1, n2, n3, n4 in rows:
                a = [xyz[n2][k] - xyz[n1][k] for k in range(3)]
                b = [xyz[n4][k] - xyz[n1][k] for k in range(3)]
                nrm = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                       a[0] * b[1] - a[1] * b[0])
                with self.subTest(layer=inlet_j, face=(n1, n2, n3, n4)):
                    self.assertGreater(sign * nrm[1], 0.0)   # out of the block
                    self.assertEqual((nrm[0], nrm[2]), (0.0, 0.0))
            self.assertEqual(_cards(st, "/IMPVEL/"), [])
            self.assertTrue(_has(res.warnings, "drives 4 boundary face(s)"))

    def test_an_interior_face_is_never_an_inlet_face(self):
        """Two bricks side by side (x 0-10 / 10-20): their shared face (x =
        10: bottom nodes 3 4, top nodes 9 10) has all four nodes in the set
        and is still no segment - it belongs to two bricks. The two top faces
        are; the bottom nodes 3 4 keep an /IMPVEL (they hold nothing, so an
        inlet face through them would be refused)."""
        res, st, _e = _convert(_block_grid(2, 1, extra=(3, 4)))
        rows = _surf_rows(st, "/SURF/SEG/90001")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(set(r[1:]) <= set(range(7, 13)) for r in rows))
        imp = _cards(st, "/IMPVEL/")
        self.assertEqual(len(imp), 1)
        grnod = int(_block(st, imp[0])[2][40:50])
        self.assertEqual([int(x) for x in _block(st, f"/GRNOD/NODE/{grnod}")[1]
                          .split()], [3, 4])
        self.assertTrue(_has(res.warnings, "drives 2 boundary face(s)",
                             "The row's 2 node(s) on no inlet face"))

    def test_a_partial_cover_keeps_an_impvel_on_exactly_the_rest(self):
        """Node 9 (between the two water cells) is on no boundary face: it
        keeps an /IMPVEL on a /GRNOD/NODE of exactly itself."""
        res, st, _e = _convert(_a7_coupon(
            ("        13        14        15        16\n",
             "        13        14        15        16         9\n")))
        self.assertEqual(_surf_rows(st, "/SURF/SEG/90001"),
                         [[1, 13, 14, 15, 16]])
        imp = _cards(st, "/IMPVEL/")
        self.assertEqual(len(imp), 1)
        grnod = int(_block(st, imp[0])[2][40:50])
        self.assertEqual([int(x) for x in _block(st, f"/GRNOD/NODE/{grnod}")[1]
                          .split()], [9])
        self.assertTrue(_has(res.warnings, "The row's 1 node(s) on no inlet "
                             f"face keep an /IMPVEL ({imp[0]} on "
                             f"/GRNOD/NODE/{grnod})."))

    def test_every_refusal_is_named_and_keeps_the_card_byte_for_byte(self):
        """A refused row is decided before any id is drawn: its bytes are the
        --no-ale-inflow-ebcs bytes (the A-i route), and the sentence names
        the class."""
        bpm = _A7_BPM
        cases = {
            "VAD 2": (((bpm, bpm.replace("2         0         1",
                                         "2         2         1")),),
                      {}, "VAD 2 is not a velocity", "IMPDISP"),
            "DOF 5": (((bpm, bpm.replace("1         2         0",
                                         "1         5         0")),),
                      {}, "DOF 5 is not a global X / Y / Z translation",
                      "IMPVEL"),
            "a BIRTH": (((bpm, bpm[:-10] + "    1.0E-5"),), {},
                        "it states a time window (BIRTH 1e-05, DEATH 0)",
                        "IMPVEL"),
            "a DEATH": (((bpm, bpm[:-20] + "    5.0E-5       0.0"),), {},
                        "it states a time window (BIRTH 0, DEATH 5e-05)",
                        "IMPVEL"),
            "LCID 0": (((bpm, bpm.replace("0         1       1.0",
                                          "0         0       1.0")),),
                       {}, "its LCID 0 is not a *DEFINE_CURVE", "IMPVEL"),
            "an x-free face node": (
                (("      13             0.0            30.0             0.0"
                  "       6", "      13             0.0            30.0"
                  "             0.0       3"),),
                {}, "not every face node holds direction(s) x", "IMPVEL"),
            "a face on the vacuum brick": (
                (("        13        14        15        16\n",
                  "         1         2         3         4\n"),),
                {}, "a face brick of part 2 is not on a *MAT_NULL + *EOS_* "
                "fluid", "IMPVEL"),
            "--no-vacuum-light-fluid": (
                (), {"vacuum_light_fluid": False},
                "the ALE domain still holds the LAW0 /MAT/VOID part(s) [2]",
                "IMPVEL"),
        }
        for name, (edits, kw, why, card) in cases.items():
            with self.subTest(case=name):
                deck = _a7_coupon(*edits)
                res, st, eng = _convert(deck, **kw)
                self.assertNotIn("/EBCS/INLET/VP/", st)
                self.assertTrue(_cards(st, f"/{card}/"))
                self.assertTrue(_has(
                    res.warnings, "*BOUNDARY_PRESCRIBED_MOTION_SET nsid=1: "
                    "the ALE inlet (/EBCS/INLET/VP, round 10, A7) is NOT "
                    "written - " + why, f"so the row stays an /{card}"),
                    res.warnings)
                _r, st_off, eng_off = _convert(deck, ale_inflow_ebcs=False,
                                               **kw)
                self.assertEqual(st, st_off)
                self.assertEqual(eng, eng_off)

    def test_the_opt_out_keeps_the_impvel_with_the_light_fluid(self):
        res, st, _e = _convert(_a7_coupon(), ale_inflow_ebcs=False)
        self.assertIn("/MAT/HYD_VISC/2", st)
        self.assertEqual(len(_cards(st, "/IMPVEL/")), 1)
        self.assertNotIn("/EBCS/INLET/VP/", st)
        self.assertFalse(_has(res.warnings, "/EBCS/INLET/VP/"))
        self.assertFalse(_has(res.warnings, "the ALE inlet (/EBCS/INLET/VP"))

    def test_a_lagrangian_channel_and_a_plain_ale_deck_are_untouched(self):
        """ELFORM 6 is Lagrangian in k2rad (Iale 0): an inflow row on it is
        never reached (channel_A / _B / _C are MATCH rows); an ELFORM-11
        deck without a vacuum and without a prescribed motion moves nothing.
        Both = the A-i HEAD bytes (pinned)."""
        for name, deck in _a7_guard_decks().items():
            with self.subTest(deck=name):
                res, st, eng = _convert(deck)
                self.assertEqual((_tp._sha(st), _tp._sha(eng)),
                                 _A7_GUARD_AI_SHA[name])
                self.assertFalse(_has(res.warnings, "ALE inlet"))
                self.assertFalse(_has(res.warnings, "/EBCS/INLET/VP"))


class A7Texts(unittest.TestCase):
    """The texts that change with A7."""

    def test_the_vacuum_sentence_is_route_neutral(self):
        """A *MAT_VACUUM with no emitted Iale part (2Dlag-shaped: the
        vacuum part on a Lagrangian ELFORM 1 brick) gets the parse-time
        sentence only - route-neutral, the measured-false clause gone."""
        deck = _a7_coupon(("         2        11         0",
                           "         2         1         0"))
        res, st, _e = _convert(deck)
        w = [x for x in res.warnings if x.startswith("*MAT_VACUUM 2 (RO")]
        self.assertEqual(len(w), 1)
        for needle in ("Radioss has no vacuum MATERIAL",
                       "k2rad writes either /MAT/VOID/2 (LAW0",
                       "a light-fluid copy of that fluid (round 10, A7",
                       "so whatever advects into it is DELETED (measured on "
                       "stagnation_A)", "undeclared balance IS Radioss's "
                       "void"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w[0])
        self.assertFalse(_has(res.warnings, "light-fluid copy (round 10, A7) "
                              "is not written"))
        self.assertIn("/MAT/VOID/2", st)

    def test_the_retracted_clause_prints_nowhere(self):
        decks = (_a7_coupon(),
                 _a7_coupon((_A7_WATER, "*MAT_PLASTIC_KINEMATIC\n         1"
                             "    7.8E-9  200000.0       0.3     200.0\n")),
                 _a7_coupon(("         2        11         0",
                             "         2         1         0")))
        for k, deck in enumerate(decks):
            with self.subTest(deck=k):
                res, _st, _e = _convert(deck)
                self.assertFalse(_has(res.warnings, "nothing flows into"))

    def test_the_ammg_cycle_18_clause_is_history(self):
        res, _st, _e = _convert(_a7_coupon())
        w = [x for x in res.warnings if "NO /MAT/LAW51 is emitted" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("stagnation_A's engine stopped at cycle 18 (t = 3.9e-5 "
                      "of ENDTIM 2e-2) when that batch measured it; at round "
                      "10 its default bytes (the vacuum light fluid and the "
                      "ALE inlet, A7) run to NORMAL TERMINATION at t 0.02 in "
                      "9364 cycles (nt 4).", w[0])
        self.assertNotIn("stops at cycle 18", w[0])
        res2, _s2, _e2 = _convert(_a7_coupon(), ale_multimat_law51=True)
        w2 = [x for x in res2.warnings if "listing submaterials" in x]
        self.assertIn("stopped at cycle 18", w2[0])
        self.assertNotIn("stops at cycle 18", w2[0])
        # the LAW51 phase screen names the light-fluid route
        self.assertTrue(_has(res2.warnings, "MID 2 (*MAT_VACUUM -> a LAW6 "
                             "light-fluid copy, round 10, A7)",
                             "keeps its light-fluid /MAT/HYD_VISC"))

    def test_the_sf_sentence_names_the_inlet_route(self):
        """Round 9's SF-default sentence (a stated SF 0.0 is LS-DYNA's 1.0)
        says where the motion goes on an inlet row."""
        deck = _a7_coupon((_A7_BPM, _A7_BPM.replace("1       1.0",
                                                    "1       0.0")))
        res, _st, _e = _convert(deck)
        self.assertTrue(_has(res.warnings, "SF = 0.0 is read as the card's "
                             "default 1.0", "so the motion is IMPOSED - here "
                             "through the ALE inlet /EBCS/INLET/VP of this "
                             "set with Fscale 1 (see the inlet note)"))
        res2, _s, _e2 = _convert(deck, ale_inflow_ebcs=False)
        self.assertTrue(_has(res2.warnings, "so the motion is IMPOSED "
                             "(/IMPVEL Fscale 1)"))


#: the coupon's _0000 / _0001 sha256 at the part-A-i head (e512676 = the
#: A-i head 1792a66 + master b17c298; measured on a detached checkout of it):
#: the opt-out arm of A7 must reproduce them
_A7_COUPON_AI_SHA = (
    "a089f2b03cf96d74be7c1b29e773e4cd615a0d024bb99189e7cf8cc79d666738",
    "a6a8b01b5a3e8829f02a0367ba52a48746ba1b911e340fb35faf9ef4c0f55b0a")
#: the two A7 guard decks' _0000 / _0001 sha256 at the part-A-i head
_A7_GUARD_AI_SHA = {
    "channel": (
        "9cca15e7da2838282482fad3d9d17c15dbf98f4c19c41604c5fa6a198ca3fa2f",
        "a6a8b01b5a3e8829f02a0367ba52a48746ba1b911e340fb35faf9ef4c0f55b0a"),
    "plain": (
        "14ff025e22759df77711ad11d02d5a411b8b7e5a3c80e8689b064c229dcccb7e",
        "a6a8b01b5a3e8829f02a0367ba52a48746ba1b911e340fb35faf9ef4c0f55b0a"),
}


# ═════════════════════════════════════════════════════════════════════════════
# A9  *CONTROL_CONTACT SLSFAC named (text only)
# ═════════════════════════════════════════════════════════════════════════════

def _a9_deck(slsfac="0.02", contact="*CONTACT_SURFACE_TO_SURFACE",
             ctrl=True) -> str:
    """Two 10 x 10 mm *MAT_ELASTIC shell plates 1 mm apart (parts 1 / 2),
    one *CONTACT card between them (part sides), and a *CONTROL_CONTACT
    card whose first field is *slsfac* (blank: an empty field)."""
    nodes = "".join(f"{n:8d}{x:16.1f}{y:16.1f}{z:16.1f}\n" for n, x, y, z in (
        (1, 0, 0, 0), (2, 10, 0, 0), (3, 10, 10, 0), (4, 0, 10, 0),
        (5, 0, 0, 1), (6, 10, 0, 1), (7, 10, 10, 1), (8, 0, 10, 1)))
    cc = (f"*CONTROL_CONTACT\n{slsfac:>10}       0.0         0         0"
          "         1\n" if ctrl else "")
    con = (f"{contact}\n" + _row(1, 2, 3, 3) + "\n" + _row(0.0, 0.0) + "\n"
           + _row(1.0, 1.0) + "\n") if contact else ""
    return ("*KEYWORD\n*CONTROL_TERMINATION\n    1.0E-4\n" + cc
            + "*PART\np1\n" + _row(1, 1, 1) + "\n*PART\np2\n" + _row(2, 1, 1)
            + "\n*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0, 1.0, 1.0,
                                                             1.0)
            + "\n*MAT_ELASTIC\n" + _row(1, "7.8E-9", "2.0E5", 0.3) + "\n"
            + con + "*ELEMENT_SHELL\n" + "".join(
                f"{e:8d}{p:8d}" + "".join(f"{n:8d}" for n in ns) + "\n"
                for e, p, ns in ((1, 1, (1, 2, 3, 4)), (2, 2, (5, 6, 7, 8))))
            + "*NODE\n" + nodes + "*END\n")


def _a9_notes(res):
    return [w for w in res.warnings
            if w.startswith("*CONTROL_CONTACT SLSFAC")]


class SlsfacNamed(unittest.TestCase):
    """A9 (text only): *CONTROL_CONTACT SLSFAC (Vol I R17 p.12-69, 0 = the
    default 0.1) reaches no /INTER cell; one sentence per deck with a
    contact when it is not 0 / 0.1, from both exits of _make_interfaces."""

    def test_a_stated_slsfac_is_named_once(self):
        res, st, eng = _convert(_a9_deck("0.02"))
        self.assertEqual(len(_cards(st, "/INTER/TYPE7/")), 1)
        notes = _a9_notes(res)
        self.assertEqual(len(notes), 1)
        for needle in ("*CONTROL_CONTACT SLSFAC = 0.02 (Vol I R17 p.12-69",
                       "no /INTER cell k2rad writes carries it",
                       "reads back only SHLTHK",
                       "Theory R16 eq. 30.7 / 30.8"):
            with self.subTest(needle=needle):
                self.assertIn(needle, notes[0])
        self.assertNotIn("negative", notes[0])
        # text only: the value moves no byte
        _r, st1, eng1 = _convert(_a9_deck("0.1"))
        self.assertEqual((st, eng), (st1, eng1))

    def test_the_default_says_nothing(self):
        for value in ("0.1", "0.0", ""):
            with self.subTest(slsfac=value):
                res, _st, _e = _convert(_a9_deck(value))
                self.assertEqual(_a9_notes(res), [])

    def test_the_early_exit_names_it_too(self):
        """A deck whose only contact takes the TYPE25 route never reaches
        the surface-to-surface loop (proj-errod / projectile shape)."""
        res, st, _e = _convert(_a9_deck(
            "1.0", contact="*CONTACT_ERODING_SURFACE_TO_SURFACE"))
        self.assertTrue(_cards(st, "/INTER/TYPE25/"))
        self.assertEqual(len(_a9_notes(res)), 1)
        self.assertIn("SLSFAC = 1 (", _a9_notes(res)[0])

    def test_no_contact_no_sentence(self):
        res, _st, _e = _convert(_a9_deck("0.02", contact=""))
        self.assertEqual(_a9_notes(res), [])

    def test_a_negative_value_is_named_as_undefined(self):
        res, _st, _e = _convert(_a9_deck("-0.5"))
        notes = _a9_notes(res)
        self.assertEqual(len(notes), 1)
        self.assertIn("SLSFAC = -0.5 - a negative value LS-DYNA does not "
                      "define (", notes[0])

    def test_a_second_call_says_nothing(self):
        """A deferred implicit stub calls _make_interfaces again: the
        sentence stays once (the state flag)."""
        from k2rad.state import ConversionState, ControlContact
        from k2rad.writer import contacts
        st = ConversionState()
        st.ctrl_contact = ControlContact(0.02, 0.0, 1, 0, 1, 0)
        st.contacts_type25.append(object())       # any record will do
        contacts._warn_slsfac_dropped(st)
        contacts._warn_slsfac_dropped(st)
        self.assertEqual(len([w for w in st.warnings
                              if w.startswith("*CONTROL_CONTACT")]), 1)


# ═════════════════════════════════════════════════════════════════════════════
# A8  the rigid-tool penalty cap (default; --no-rigid-tool-penalty-cap)
# ═════════════════════════════════════════════════════════════════════════════

#: LS-DYNA Theory R16 eq. 30.8 by hand on _a8_deck (E 69000, nu 0.3: K =
#: 69000 / (3 (1 - 0.6)) = 57500): a 1 x 1 mm blank quad K A / dmax = 57500
#: / sqrt(2), the 3 x 3 mm tool quad 57500 x 9 / sqrt(18)
_A8_K_BLANK = 57500.0 / 2.0 ** 0.5
_A8_K_TOOL = 57500.0 * 9.0 / 18.0 ** 0.5


def _a8_deck(spelling="*CONTACT_ONE_WAY_SURFACE_TO_SURFACE", slsfac="",
             penopt="1", sfs="", sfm="", soft=None, tool="rigid",
             swap=False) -> str:
    """A 2 x 2 blank of 1 mm *MAT_ELASTIC quads (E 69000 nu 0.3 t 1, part 1,
    the SURFA side) under a 3 x 3 mm tool 0.5 mm above it (part 2, SURFB):
    tool 'rigid' (*MAT_RIGID shell), 'elastic' (a *MAT_ELASTIC shell - the
    ring trio's deformable wall) or 'solid' (one rigid brick). *swap* puts
    the tool on SURFA. *soft* adds Optional Card A with that SOFT."""
    blank = [(1 + i + 3 * j, float(i), float(j), 0.0)
             for j in range(3) for i in range(3)]
    tool_n = [(101, -0.5, -0.5, 0.5), (102, 2.5, -0.5, 0.5),
              (103, 2.5, 2.5, 0.5), (104, -0.5, 2.5, 0.5)]
    if tool == "solid":
        tool_n += [(105, -0.5, -0.5, 1.5), (106, 2.5, -0.5, 1.5),
                   (107, 2.5, 2.5, 1.5), (108, -0.5, 2.5, 1.5)]
    nodes = "".join(f"{n:8d}{x:16.1f}{y:16.1f}{z:16.1f}\n"
                    for n, x, y, z in blank + tool_n)
    quads = "".join(f"{e:8d}{1:8d}" + "".join(f"{n:8d}" for n in ns) + "\n"
                    for e, ns in ((1, (1, 2, 5, 4)), (2, (2, 3, 6, 5)),
                                  (3, (4, 5, 8, 7)), (4, (5, 6, 9, 8))))
    if tool == "solid":
        tool_el = ("*ELEMENT_SOLID\n" + f"{11:8d}{2:8d}" + "".join(
            f"{n:8d}" for n in range(101, 109)) + "\n")
        tool_sec = "*SECTION_SOLID\n" + _row(2, 1) + "\n"
    else:
        tool_el = ("*ELEMENT_SHELL\n" + f"{11:8d}{2:8d}" + "".join(
            f"{n:8d}" for n in (101, 102, 103, 104)) + "\n")
        tool_sec = ("*SECTION_SHELL\n" + _row(2, 2) + "\n"
                    + _row(1.0, 1.0, 1.0, 1.0) + "\n")
    tool_mat = ("*MAT_ELASTIC\n" + _row(2, "7.8E-9", "69000.0", 0.3) + "\n"
                if tool == "elastic" else
                "*MAT_RIGID\n" + _row(2, "7.8E-9", "69000.0", 0.3) + "\n"
                + _row(0.0, 0, 0) + "\n" + _row(0.0) + "\n")
    sides = _row(2, 1, 3, 3) if swap else _row(1, 2, 3, 3)
    card_a = (_row(soft) + "\n") if soft is not None else ""
    # an _MPP spelling carries its MPP card BEFORE Card 1
    # (handlers._contact_mpp_card_offset)
    if spelling.endswith("_MPP"):
        sides = _row(0, 200, 0, 3, 1, 0) + "\n" + sides
    return ("*KEYWORD\n*CONTROL_TERMINATION\n    1.0E-4\n"
            "*CONTROL_CONTACT\n" + f"{slsfac:>10}" + "       0.0         1"
            "         0" + f"{penopt:>10}" + "\n"
            "*PART\nblank\n" + _row(1, 1, 1) + "\n*PART\ntool\n"
            + _row(2, 2, 2) + "\n*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n" + tool_sec
            + "*MAT_ELASTIC\n" + _row(1, "7.8E-9", "69000.0", 0.3) + "\n"
            + tool_mat + spelling + "\n" + sides + "\n" + _row(0.0, 0.0)
            + "\n" + f"{sfs:>10}{sfm:>10}" + "\n" + card_a
            + "*ELEMENT_SHELL\n" + quads + tool_el + "*NODE\n" + nodes
            + "*END\n")


def _type7_card3(starter: str, iid: int = 90001):
    """(Stmin, Stmax) of /INTER/TYPE7/<iid> (Card 3)."""
    blk = _block(starter, f"/INTER/TYPE7/{iid}")
    assert blk[5].lstrip("# ").startswith("Stmin"), blk[5]
    c3 = blk[6]
    return float(c3[:20]), float(c3[20:40])


class RigidToolPenaltyCap(unittest.TestCase):
    """A8 (default ON): on the /INTER/TYPE7 of a non-automatic
    *CONTACT_[FORMING_]ONE_WAY_SURFACE_TO_SURFACE (+ _MPP) with an all-rigid
    shell tool, SOFT 0, PENOPT 0 / 1: Stmax = 2 x k_LS, k_LS = SLSFAC x
    min(SFM x k_tool, SFS x k_blank), k = the median LS-DYNA Theory R16 eq.
    30.8 segment stiffness K A / max diagonal; Stmin = min(1000, Stmax).

    The coupon fixture (round10/r10_type7_coupon_quad.k = the round-10
    critic's cq.k: a rigid 12 x 12 plate dropping on a fixed 4 x 4 strip of
    2 mm quads, E 100 nu 0.28 t 0.8, ONE_WAY, no *CONTROL_CONTACT) through
    the starter + engine on the branch bytes (round 10, part A-ii, nt 4,
    `C:/Users/pmqua/rcv_r10i_implA2_cq_new`): NORMAL TERMINATION, 808
    cycles; with VisS 1e-6 on both arms (`..._cq_new_v` / `..._cq_base_v`)
    the peak penetration is 0.18031 mm = the closed form of the TYPE7 law at
    K = 21.42747822 (-0.00 %; 802 cycles) and 0.02809 mm against 0.02810 at
    the card's Stmin 1000 (-0.03 %) - the cap puts eq. 30.8's node spring
    into the engine exactly."""

    def test_the_coupon_cells_and_numbers(self):
        with open(os.path.join(_FIX10, "r10_type7_coupon_quad.k")) as fh:
            deck = fh.read()
        res, st, _e = _convert(deck)
        k_blank = (100.0 / (3.0 * (1.0 - 0.56))) * 4.0 / 8.0 ** 0.5
        stmin, stmax = _type7_card3(st)
        self.assertAlmostEqual(stmax, 2.0 * 0.1 * k_blank, delta=1e-7)
        self.assertEqual(stmin, stmax)            # min(1000, Stmax) = Stmax
        self.assertAlmostEqual(stmax, 21.42747822, places=8)
        self.assertTrue(_has(
            res.warnings, "*CONTACT_ONE_WAY_SURFACE_TO_SURFACE 90001 -> "
            "/INTER/TYPE7/90001: the rigid-tool penalty cap Stmax = 2 x k_LS "
            "= 21.4275 and Stmin = min(1000, Stmax) = 21.4275",
            "0.1 x min(1 x 1.33065e+06, 1 x 107.137) = 10.7137",
            "the median over the 1 tool and 16 blank shells",
            "i7for3.F:976", "i7cor3.F:277-288"))
        # D-A8-1: the K-02 floor sentence reads the WRITTEN Stmin
        self.assertFalse(_has(res.warnings, "Stmin 1000 is above"))
        _r, st0, _e0 = _convert(deck, rigid_tool_penalty_cap=False)
        self.assertEqual(_type7_card3(st0), (1000.0, 0.0))
        self.assertTrue(_has(_r.warnings, "/INTER/TYPE7 90001: Stmin 1000 is "
                             "above the estimated contact stiffness"))
        self.assertEqual(_tp._sha(st0), _A8_COUPON_AI_SHA)

    def test_the_class_cells_by_hand(self):
        cases = (
            ({"slsfac": "0.01"}, 0.01 * _A8_K_BLANK),
            ({"slsfac": "0.1"}, 0.1 * _A8_K_BLANK),
            ({"slsfac": ""}, 0.1 * _A8_K_BLANK),           # blank = 0.1
            ({"slsfac": "0.0"}, 0.1 * _A8_K_BLANK),        # 0 = 0.1
            ({"sfs": "0.5"}, 0.1 * 0.5 * _A8_K_BLANK),
            ({"sfm": "0.1"}, 0.1 * 0.1 * _A8_K_TOOL),      # the tool is min
        )
        for spelling in ("*CONTACT_ONE_WAY_SURFACE_TO_SURFACE",
                         "*CONTACT_FORMING_ONE_WAY_SURFACE_TO_SURFACE",
                         "*CONTACT_ONE_WAY_SURFACE_TO_SURFACE_MPP"):
            for kw, k_ls in cases:
                with self.subTest(spelling=spelling, **kw):
                    res, st, _e = _convert(_a8_deck(spelling, **kw))
                    stmin, stmax = _type7_card3(st)
                    self.assertAlmostEqual(stmax / (2.0 * k_ls), 1.0,
                                           delta=1e-9)
                    self.assertAlmostEqual(stmin, min(1000.0, stmax),
                                           delta=1e-6)
                    self.assertTrue(_has(res.warnings,
                                         "the rigid-tool penalty cap Stmax"))
                    self.assertTrue(_has(res.warnings, "The rigid-tool "
                                         "penalty cap (round 10, A8) is "
                                         "LS-DYNA Theory eq. 30.8 x SLSFAC x "
                                         "SF"))
        # SLSFAC 0.01: the min(1000, Stmax) branch writes Stmin = Stmax
        _r, st, _e = _convert(_a8_deck(slsfac="0.01"))
        self.assertAlmostEqual(_type7_card3(st)[0], 813.1727984, places=6)

    def test_the_refusals_are_named_and_change_no_cell(self):
        cases = {
            "PENOPT 4": ({"penopt": "4"}, "*CONTROL_CONTACT PENOPT 4"),
            "SOFT 1": ({"soft": 1}, "SOFT 1 (its penalty is not eq. 30.8"),
            "a rigid SURFA": ({"swap": True}, "a rigid secondary side (the "
                              "all-rigid-SSID route)"),
            "SLSFAC -0.1": ({"slsfac": "-0.1"}, "*CONTROL_CONTACT SLSFAC -0.1 "
                            "(a value LS-DYNA does not define)"),
            "a negative SFS": ({"sfs": "-1.0"}, "Card 3 SFS -1 / SFM 0 (a "
                               "negative penalty scale)"),
            "a solid tool": ({"tool": "solid"}, "a solid side (eq. 30.7 has "
                             "no measured carrier)"),
        }
        for name, (kw, why) in cases.items():
            with self.subTest(case=name):
                res, st, eng = _convert(_a8_deck(**kw))
                self.assertEqual(_type7_card3(st)[1], 0.0)
                self.assertTrue(_has(
                    res.warnings, "the rigid-tool penalty cap (round 10, A8) "
                    "is not written - " + why, "keeps Stmax 0 and Stmin "),
                    res.warnings)
                self.assertFalse(_has(res.warnings, "the rigid-tool penalty "
                                      "cap Stmax"))
                _r, st0, eng0 = _convert(_a8_deck(**kw),
                                         rigid_tool_penalty_cap=False)
                self.assertEqual((st, eng), (st0, eng0))

    def test_the_classes_outside_are_silent(self):
        cases = {
            "AUTOMATIC_ONE_WAY": {"spelling": "*CONTACT_AUTOMATIC_ONE_WAY_"
                                  "SURFACE_TO_SURFACE"},
            "two-way S2S": {"spelling": "*CONTACT_SURFACE_TO_SURFACE"},
            "MORTAR": {"spelling": "*CONTACT_FORMING_SURFACE_TO_SURFACE_"
                       "MORTAR"},
            "a deformable tool": {"tool": "elastic"},
        }
        for name, kw in cases.items():
            with self.subTest(case=name):
                res, st, eng = _convert(_a8_deck(**kw))
                for iid in [int(h.rsplit("/", 1)[1])
                            for h in _cards(st, "/INTER/TYPE7/")]:
                    self.assertEqual(_type7_card3(st, iid)[1], 0.0)
                self.assertFalse(_has(res.warnings, "rigid-tool penalty cap"))
                _r, st0, eng0 = _convert(_a8_deck(**kw),
                                         rigid_tool_penalty_cap=False)
                self.assertEqual((st, eng), (st0, eng0))

    def test_an_inter_stmin_wins_over_the_cap_floor(self):
        res, st, _e = _convert(_a8_deck(slsfac="0.1"),
                               inter_stmin={90001: 500.0})
        self.assertAlmostEqual(_type7_card3(st)[0], 500.0)
        self.assertAlmostEqual(_type7_card3(st)[1], 8131.727984, places=5)
        res, st, _e = _convert(_a8_deck(slsfac="0.1"),
                               inter_stmin={90001: 9000.0})
        self.assertEqual(_type7_card3(st)[0], 9000.0)
        self.assertTrue(_has(res.warnings, "Stmin = --inter-stmin 9000 "
                             "(above Stmax: the floor then sets K, "
                             "i7cor3.F:288)"))

    def test_the_segment_stiffness_by_hand(self):
        """eq. 30.8's K A / dmax on a parallelogram whose LONGER diagonal is
        d24 (A = |d13 x d24| / 2 = 2, dmax = |d24| = sqrt(10)) and on a
        triangle (A = 1, dmax = its longest edge sqrt(5)); the median over
        the side's shells."""
        from k2rad.state import ConvertOptions
        from k2rad.writer import contacts
        deck = ("*KEYWORD\n*PART\np\n" + _row(1, 1, 1)
                + "\n*SECTION_SHELL\n" + _row(1, 2) + "\n"
                + _row(1.0, 1.0, 1.0, 1.0) + "\n*MAT_ELASTIC\n"
                + _row(1, "7.8E-9", "69000.0", 0.3) + "\n*ELEMENT_SHELL\n"
                + f"{1:8d}{1:8d}{1:8d}{2:8d}{3:8d}{4:8d}\n"
                + f"{2:8d}{1:8d}{5:8d}{6:8d}{7:8d}{7:8d}\n*NODE\n"
                + "".join(f"{n:8d}{x:16.1f}{y:16.1f}{0.0:16.1f}\n"
                          for n, x, y in ((1, 1, 1), (2, 0, 0), (3, 2, 0),
                                          (4, 3, 1), (5, 10, 0), (6, 12, 0),
                                          (7, 10, 1)))
                + "*END\n")
        st = _a7_state(deck, ConvertOptions())
        k, n = contacts._ls_shell_penalty(st, {1})
        quad = 57500.0 * 2.0 / 10.0 ** 0.5
        tri = 57500.0 * 1.0 / 5.0 ** 0.5
        self.assertEqual(n, 2)
        self.assertAlmostEqual(k / (0.5 * (quad + tri)), 1.0, delta=1e-12)

    def test_the_emitter_writes_the_old_card_without_a_cap(self):
        from k2rad.writer import contacts
        card = contacts._emit_inter_type7(7, "t", 1, 2, 0.0)
        self.assertEqual(card[7], "                1000                   0"
                         "                   0                   0         0")

    def test_the_slsfac_sentence_names_the_capped_interfaces(self):
        res, _st, _e = _convert(_a8_deck(slsfac="0.01"))
        notes = _a9_notes(res)
        self.assertEqual(len(notes), 1)
        self.assertIn("only the rigid-tool penalty cap (round 10, A8) carries "
                      "it - Stmax = 2 x LS-DYNA Theory eq. 30.8 x SLSFAC x SF "
                      "on /INTER/TYPE7 90001", notes[0])
        res, _st, _e = _convert(_a8_deck(slsfac="0.01"),
                                rigid_tool_penalty_cap=False)
        self.assertIn("The rigid-tool penalty cap (round 10, A8) reaches no "
                      "interface of this deck.", _a9_notes(res)[0])


#: the coupon's _0000 sha256 at the part-A-i head (e512676; measured on a
#: detached checkout of it): --no-rigid-tool-penalty-cap reproduces it
_A8_COUPON_AI_SHA = (
    "4a0822b57c473123416f297c8dabe6d669c2e73752eaa8e1f94b0c667db246fd")


# ═════════════════════════════════════════════════════════════════════════════
# PART A-ii.  A10  the *INITIAL_VOID void copy (2b, default;
# --no-initial-void-copy), the CLIS PFAC stiffness (2a, opt-in
# --clis-pfac-stiffness) and the converter-side first-step estimate
# ═════════════════════════════════════════════════════════════════════════════

def _a10_state(deck: str, **kw):
    """The dispatched ConversionState of *deck* with ConvertOptions(**kw)."""
    from k2rad.state import ConvertOptions
    return _a7_state(deck, ConvertOptions(**kw))


def _a10_fixture(name: str, *edits) -> str:
    with open(os.path.join(_FIX10, name)) as fh:
        deck = fh.read()
    for old, new in edits:
        assert deck.count(old) == 1, old
        deck = deck.replace(old, new)
    return deck


def _rect_almin(a: float, b: float) -> float:
    """``cndleni.F``'s ALMIN of an a x b rectangle in closed form (QBAT):
    AL1 = (a^2 + b^2) / 4, AL2 = 0, FAC1 = 1 + min(0.5, (a / b - 1) / 4),
    FAC2 = 0.78 + 0.22 (3.413 (1 - 0.7071))^3, FAC11 = 4/3."""
    import math
    a, b = max(a, b), min(a, b)
    fac1 = 1.0 + min(0.5, 0.25 * (a / b - 1.0))
    fac2 = 0.78 + 0.22 * (3.413 * (1.0 - 0.7071)) ** 3
    return a * b / math.sqrt(2.0 * fac1 * fac2 * 4.0 / 3.0
                             * (a * a + b * b) / 4.0)


def _hex_step(h: float, c: float) -> float:
    """``dtel.F`` for a cube of edge *h* at sound speed *c* (q_b 0.05)."""
    import math
    return h / (c * (0.05 + math.sqrt(1.0025)))


def _a10_pfac(deck: str, value: str) -> str:
    """*deck* with its one CLIS card-2 PFAC cell (columns 21-30) = *value*."""
    lines = deck.split("\n")
    i = lines.index("*CONSTRAINED_LAGRANGE_IN_SOLID") + 2
    lines[i] = lines[i][:20] + f"{value:>10}" + lines[i][30:]
    return "\n".join(lines)


def _a10_bird_stfval(void_copied: bool = True) -> float:
    """The 2a Stfval of ``_t9.b8_bird(clis=True)`` by hand: the plate's 1 x
    1 mm QBAT (E 1000, rho 1e-9) sets the step, Tsca 0.9 (no
    *CONTROL_TIMESTEP); m_node = the median lumped mass of the bird's (and,
    without the copy, the void host's) nodes = 7.81e-10 x 1 / 8."""
    import math
    dt0 = 0.9 * _rect_almin(1.0, 1.0) / math.sqrt(1000.0 / 1e-9)
    return 0.1 * (7.81e-10 / 8.0) / dt0 ** 2


def _a10_type18(starter: str):
    """{interface id: (grbric id, Stfval)} of every /INTER/TYPE18."""
    out = {}
    for ln in _cards(starter, "/INTER/TYPE18/"):
        rows = [r for r in _block(starter, ln) if not r.startswith("#")]
        out[int(ln.split("/")[-1])] = (int(rows[1].split()[1]),
                                       float(rows[2][:20]))
    return out


#: the part-A-i head (e512676, a detached checkout) digests of the A10 pin
#: decks: b8_bird(card=False, clis=True)'s _0000 (= --no-initial-void-copy)
#: and b8_bird(card=False, clis=False)'s _0000 + its warning list (bird-el's
#: class: a void without CLIS)
_A10_VOID_AI_SHA = (
    "403e15cc8afbc8b838075f37d66a5d970fd285dcf8335676329ebb94ffc6c78e")
_A10_BIRDEL_AI_SHA = (
    "ae44daef55fdfbc1451be619d3c7e93cc2a594f7f7bbc9257785ec62c7ce128b")
#: b8_bird(card=True, clis=True)'s _0000: at the part-A-i head (= the
#: branch under --no-ale-flow-tracking) and the branch's default package
_A10_PKG_AI_SHA = (
    "1cb4a0982ffe431111d739095209327eeda683bae0984cb3b38334f4be0583d8")
_A10_PKG_SHA = (
    "cc65b90d78f94ba4b5f1220d7b695dd1184c3f27449b16dbfa9ea93244df0ea9")
_A10_BIRDEL_AI_WARNINGS = (
    "f085e585d1fd5cac9f1a0aae1dc3dd4c3d7dd8173ca0ac1547a92a6177c78a71")


class ClisDt0Estimator(unittest.TestCase):
    """A10: ``writer/blast_ale.clis_dt0_estimate`` - Tsca x the smallest
    STARTER element step over the elements the engine integrates (8-node
    bricks by ``dtel.F`` with DELTAX = V / A_max; 4-node QBAT / QEPH shells
    by ``cndleni.F``), the ``/RBODY`` and LAW0 parts left out.

    The four fixtures ``tests/fixtures/round10/r10_clis_dt0*.k`` (the dt0
    fixture of the round-10 part-A-ii research spec, md5
    e0578a90727cb8c0a3232445984e512d, and the bird_B / quadrature /
    stagnation shapes) were converted on the branch and run through the
    STARTER (nt 4, ``C:/Users/pmqua/rcv_r10i_implA2_fx_*``): 0 ERROR(S) / 0
    WARNING(S) each, and the printed element steps are ``_STARTER``'s - the
    estimate reproduces the bricks to every printed digit and the shells to
    2.5e-8. The engine's cycle 0 of the dt0 fixture printed 0.5739E-06 (the
    research spec's run) = dt0 here; on the corpus the estimate is +0.11 %
    (bird_B), +1.77 % (quadrature_B) above the engine's first step."""

    _STARTER = {
        "r10_clis_dt0.k": {("solid", 3): 8.1987371899954E-07,
                           ("solid", 4): 9.5124921972504E-05,
                           ("shell", 1): 8.6612033409390E-07,
                           ("shell", 2): 9.7990329849817E-07},
        "r10_clis_dt0_shell.k": {("solid", 2): 1.3291984764694E-05,
                                 ("shell", 1): 3.5873266435589E-07},
        "r10_clis_dt0_solid.k": {("solid", 1): 9.5124921972504E-05,
                                 ("solid", 2): 9.5124921972504E-05},
        "r10_clis_dt0_stag.k": {("solid", 2): 6.3416614648336E-06,
                                ("shell", 1): 2.7185257370198E-06},
    }

    def test_every_element_step_is_the_starter_s(self):
        from k2rad.writer import blast_ale
        for fix, table in self._STARTER.items():
            st = _a10_state(_a10_fixture(fix))
            els = {("solid", e.eid): e for e in st.solid_elems}
            els.update({("shell", e.eid): e for e in st.shell_elems})
            for key, printed in table.items():
                with self.subTest(fixture=fix, element=key):
                    rule = (blast_ale._brick_step if key[0] == "solid"
                            else blast_ale._qbat_step)
                    dt, fam = rule(st, els[key])
                    self.assertEqual(fam, key[0])
                    self.assertAlmostEqual(dt / printed, 1.0, delta=1e-7)

    def test_dt0_leaves_the_rigid_brick_out(self):
        from k2rad.writer import blast_ale
        st = _a10_state(_a10_fixture("r10_clis_dt0.k"))
        dt0, fam, dte, tsca = blast_ale.clis_dt0_estimate(st)
        # the rigid brick's own starter step 5.7973826642121E-08 is not it
        self.assertEqual((fam, tsca), ("solid", 0.7))
        self.assertAlmostEqual(dte / 8.1987371899954E-07, 1.0, delta=1e-12)
        self.assertAlmostEqual(dt0 / (0.7 * 8.1987371899954E-07), 1.0,
                               delta=1e-12)
        self.assertEqual(f"{dt0:.4e}", "5.7391e-07")    # engine 0.5739E-06
        self.assertIs(blast_ale.clis_dt0_estimate(st), st.clis_dt0_memo)

    def test_the_hand_values(self):
        import math
        from k2rad.writer import blast_ale
        st = _a10_state(_a10_fixture("r10_clis_dt0.k"))
        els = {e.eid: e for e in st.solid_elems + st.shell_elems}
        g, c1 = 1000.0 / (2.0 * 1.3), 1000.0 / (3.0 * (1.0 - 0.6))
        law1 = math.sqrt((4.0 / 3.0 * g + c1) / 1e-9)       # 1160238.702
        self.assertAlmostEqual(law1, 1160238.702, places=2)
        for eid, rule, hand in (
                (3, blast_ale._brick_step, _hex_step(1.0, law1)),
                (4, blast_ale._brick_step, _hex_step(10.0, 1e5)),
                (1, blast_ale._qbat_step,
                 _rect_almin(1.0, 1.0) / math.sqrt(1000.0 / 1e-9)),
                (2, blast_ale._qbat_step,
                 _rect_almin(2.0, 1.0) / math.sqrt(1000.0 / 1e-9))):
            with self.subTest(element=eid):
                self.assertAlmostEqual(rule(st, els[eid])[0] / hand, 1.0,
                                       delta=1e-12)
        self.assertAlmostEqual(_rect_almin(1.0, 1.0), 0.8661203553,
                               places=9)

    def test_the_three_carrier_shapes(self):
        import math
        from k2rad.writer import blast_ale
        for fix, tsca, fam, hand in (
                ("r10_clis_dt0_shell.k", 0.7, "shell",
                 _rect_almin(0.661, 0.367) / math.sqrt(1000.0 / 1e-9)),
                ("r10_clis_dt0_solid.k", 0.7, "solid",
                 _hex_step(10.0, 1e5)),
                ("r10_clis_dt0_stag.k", 0.8, "shell",
                 _rect_almin(15.03, 10.0) / math.sqrt(1e5 / 8e-9))):
            with self.subTest(fixture=fix):
                st = _a10_state(_a10_fixture(fix))
                dt0, f, _dte, ts = blast_ale.clis_dt0_estimate(st)
                self.assertEqual((f, ts), (fam, tsca))
                self.assertAlmostEqual(dt0 / (tsca * hand), 1.0, delta=1e-9)
        st = _a10_state(_a10_fixture("r10_clis_dt0_solid.k"))
        self.assertAlmostEqual(blast_ale.clis_dt0_estimate(st)[0],
                               6.6587445e-05, delta=1e-12)

    def test_the_refusals_are_named(self):
        from k2rad.writer import blast_ale
        shell = "r10_clis_dt0_shell.k"
        for why, deck, needle in (
                ("mass-scaled", _a10_fixture(shell, (
                    "       0.0       0.7         0       0.0       0.0",
                    "       0.0       0.7         0       0.0  -1.0E-7")),
                 "mass-scaled (DT2MS < 0"),
                ("triangle", _a10_fixture(shell, (
                    "       1       1       1       2       3       4",
                    "       1       1       1       2       3       3")),
                 "part 1: a triangle"),
                ("tet", _a10_fixture(shell, (
                    "      15      16      17      18",
                    "      15      15      15      15")),
                 "part 2: a degenerate or non-8-node solid")):
            with self.subTest(case=why):
                st = _a10_state(deck)
                dt0, reason, _d, _t = blast_ale.clis_dt0_estimate(st)
                self.assertIsNone(dt0)
                self.assertIn(needle, reason)
        st = _a10_state(_a10_fixture(shell))
        st.beam_elems.append(object())                     # a beam family
        dt0, reason, _d, _t = blast_ale.clis_dt0_estimate(st)
        self.assertIsNone(dt0)
        self.assertIn("beam elements", reason)


class InitialVoidCopy(unittest.TestCase):
    """A10 2b (default ON, ``--no-initial-void-copy``): an *INITIAL_VOID
    part in the fluid set of a CLIS coupling is a LAW6 copy of its fluid at
    1e-3 x RO (the ``/EOS`` RHO_0 = RO) on its own ``/GRBRIC/PART`` +
    ``/INTER/TYPE18`` at the fluid's Stfval x 1e-3. The deck is round 9's
    bird_B miniature ``_t9.b8_bird(clis=True)``. MEASURED on quadrature_B
    (nt 4, README 9.1, ``C:/Users/pmqua/rcv_r10i_implA2_q_{base,2b}``): 1094
    -> 1109 cycles, KE RMS 28.17 -> 10.42 %, IE RMS 142.04 -> 161.11 %;
    its converted bytes ran the starter with 0 ERROR(S) and both
    ``/INTER/TYPE18`` echoed. STARTER probes of this class's decks on the
    branch bytes (nt 4, ``C:/Users/pmqua/rcv_r10i_implA2_pr_b8_{2b,pkg}``):
    b8_bird(card=False, clis=True) 0 ERROR(S) / 0 WARNING(S), both
    interfaces (90006, 90008) echoed; b8_bird(card=True, clis=True) - the
    package - 0 ERROR(S) / 1 WARNING (100211: /ALE/GRID/FLOW-TRACKING read
    under /BEGIN 2022)."""

    def test_the_copy_cells(self):
        res, st, _e = _convert(_t9.b8_bird(card=False, clis=True))
        self.assertEqual(_block(st, "/MAT/HYD_VISC/90001")[:4],
                         ["FLUID_2 (void copy)", "#              RHO_I",
                          "        7.810000E-13",
                          "#                 Nu                Pmin"])
        eos = [r for r in _block(st, "/EOS/POLYNOMIAL/90001")
               if not r.startswith("#")]
        self.assertEqual(float(eos[2][80:100]), 7.81e-10)   # RHO_0 = RO
        self.assertEqual(_block(st, "/PART/4")[1].split()[:2], ["2", "90001"])
        self.assertEqual(_block(st, "/PART/5")[1].split()[:2], ["2", "2"])
        self.assertEqual(_block(st, "/GRBRIC/PART/90005")[:2],
                         ["fsi_fluid_1", "         5"])
        self.assertEqual(_block(st, "/GRBRIC/PART/90007")[:2],
                         ["fsi_void_4", "         4"])
        self.assertEqual(_a10_type18(st), {90006: (90005, 1.0),
                                           90008: (90007, 0.001)})
        self.assertTrue(_has(
            res.warnings, "*INITIAL_VOID_PART 4 is the ALE fluid group",
            "a LAW6 COPY of its fluid (part 4: RHO_I = 0.001 x RO = 7.81e-13 "
            "on /MAT/HYD_VISC/90001",
            "its own /GRBRIC/PART/90007 and /INTER/TYPE18/90008 at Stfval "
            "0.001", "a numerical floor of this converter, not a value "
            "LS-DYNA states", "KE RMS 28.17 -> 10.42 %",
            "RMS 142.04 -> 161.11 %", "--no-initial-void-copy"))
        self.assertFalse(_has(res.warnings, "THE FSI RESULT ON THIS DECK IS "
                              "NOT VALID"))
        # F-A10a on the A10 texts: f is no VFACT density
        for text in [w for w in res.warnings if "LAW6 COPY" in w] + [
                _flag_help("--initial-void-copy")]:
            self.assertNotIn("vfact x ro", _t7._collapse(text).lower())
        # the floor sentence points at the copy
        self.assertTrue(_has(res.warnings, "The void itself is written as a "
                             "LAW6 copy at 0.001 x RO (round 10, A10 2b"))

    def test_the_opt_out_is_the_part_A_i_deck(self):
        deck = _t9.b8_bird(card=False, clis=True)
        res, st, _e = _convert(deck, initial_void_copy=False)
        self.assertEqual(_tp._sha(st), _A10_VOID_AI_SHA)
        self.assertTrue(_has(res.warnings, "THE FSI RESULT ON THIS DECK IS "
                             "NOT VALID"))
        self.assertFalse(_has(res.warnings, "The void copy (round 10"))

    def test_the_refusals_are_named_and_change_no_byte(self):
        # an *ALE_REFERENCE_SYSTEM_* deck (bird_B's class) with the package
        # off: the void copy without the FLOW-TRACKING grid stalls
        ars = _t9.b8_bird(card=True, clis=True)
        res, st, _e = _convert(ars, ale_flow_tracking=False)
        _r0, st0, _e0 = _convert(ars, ale_flow_tracking=False,
                                 initial_void_copy=False)
        self.assertEqual(st, st0)
        self.assertEqual(_tp._sha(st), _A10_PKG_AI_SHA)
        self.assertTrue(_has(res.warnings, "The void copy (round 10, A10 2b) "
                             "is NOT written for part 4: the deck states an "
                             "*ALE_REFERENCE_SYSTEM_* card and "
                             "--no-ale-flow-tracking turns the round-10 "
                             "package off", "3.787e-18 s"))
        # ... and with the package on but its PFAC stiffness impossible
        res, st, _e = _convert(_a10_pfac(ars, "-2.0"))
        self.assertNotIn("/ALE/GRID/FLOW-TRACKING", st)
        self.assertEqual(_block(st, "/PART/4")[1].split()[:2], ["2", "2"])
        self.assertTrue(_has(res.warnings, "is NOT written for part 4: the "
                             "deck states an *ALE_REFERENCE_SYSTEM_* card and "
                             "the round-10 package needs the PFAC stiffness, "
                             "which cannot apply here (PFAC -2 of the "
                             "coupling of master 1 is a load-curve id)"))
        self.assertTrue(_has(res.warnings, "*ALE_REFERENCE_SYSTEM_GROUP 1 "
                             "(PRTYPE 4) is skipped: its OpenRadioss analogue "
                             "/ALE/GRID/FLOW-TRACKING is written only under "
                             "--ale-flow-tracking (ON by default since R14 "
                             "round 10) and only inside the measured package",
                             "and here the void copy is refused here"))
        # a void that is not a *MAT_NULL + *EOS_* fluid
        lines = _t9.b8_bird(card=False, clis=True).split("\n")
        i = lines.index("*MAT_NULL")
        lines[i:i + 2] = ["*MAT_ELASTIC", _row(2, "7.81E-10", 1000.0, 0.3)]
        j = lines.index("*EOS_LINEAR_POLYNOMIAL")
        del lines[j:j + 3]
        ela = "\n".join(lines)
        res, st, _e = _convert(ela)
        _r0, st0, _e0 = _convert(ela, initial_void_copy=False)
        self.assertEqual(st, st0)
        self.assertTrue(_has(res.warnings, "is NOT written for part 4: part "
                             "4's material 2 is not a *MAT_NULL + *EOS_* fluid"))

    def test_the_package_is_the_default_on_the_ars_deck(self):
        """D-6 (the findings' 6.3a: the gate PASSED): on an accepted
        PRTYPE-4 card with an *INITIAL_VOID part in the CLIS fluid set the
        DEFAULT is the measured package - the copy, the FLOW-TRACKING card
        and the PFAC stiffness (x 1e-3 on the void's interface);
        --no-ale-flow-tracking is the part-A-i deck (above). bird_B's own
        default bytes ran as the package arm (nt 4,
        ``C:/Users/pmqua/rcv_r10i_implA2_b_pkg``): 2976 cycles, END IE
        +8.15 %, END KE -14.44 %, RMS 6.71 / 3.37 % (n 600)."""
        res, st, _e = _convert(_t9.b8_bird(card=True, clis=True))
        self.assertEqual(_tp._sha(st), _A10_PKG_SHA)
        self.assertIn("/ALE/GRID/FLOW-TRACKING", st)
        self.assertEqual(_block(st, "/PART/4")[1].split()[:2], ["2", "90001"])
        s = _a10_bird_stfval()
        stf = sorted(v[1] for v in _a10_type18(st).values())
        self.assertAlmostEqual(stf[1] / s, 1.0, delta=1e-9)
        self.assertAlmostEqual(stf[0] / (s * 1e-3), 1.0, delta=1e-9)
        self.assertTrue(_has(res.warnings, "it is the measured package, ON "
                             "by default since R14 round 10",
                             "END IE +1484.66 -> +8.15 %", "133.1",
                             "0.2 % change of Stfval",
                             "FLOW-TRACKING alone (round 9) is no longer "
                             "written"))
        self.assertTrue(_has(res.warnings, "the round-10 ALE package "
                             "(--ale-flow-tracking) writes Stfval = PFAC x "
                             "m_node / dt0^2"))
        # the opt-in pair of part A10's first commit gives the same bytes
        _r, st2, _e = _convert(_t9.b8_bird(card=True, clis=True),
                               ale_flow_tracking=True,
                               clis_pfac_stiffness=True)
        self.assertEqual(st2, st)

    def test_the_void_copy_opt_out_turns_the_package_off(self):
        """--no-initial-void-copy on the package deck: no copy, so no
        package - the FLOW-TRACKING card is not written and the skip
        sentence names the opt-out and its measured reason (FLOW-TRACKING
        with the PFAC stiffness but without the copy: KE +1248.28 % on
        bird_B), never that the deck has no void (the D-6 mutation pass)."""
        res, st, _e = _convert(_t9.b8_bird(card=True, clis=True),
                               initial_void_copy=False)
        self.assertNotIn("/ALE/GRID/FLOW-TRACKING", st)
        self.assertEqual(_tp._sha(st), _A10_PKG_AI_SHA)
        self.assertTrue(_has(res.warnings, "*ALE_REFERENCE_SYSTEM_GROUP 1 "
                             "(PRTYPE 4) is skipped", "and here "
                             "--no-initial-void-copy turns the package off",
                             "+1248.28 %"))
        self.assertFalse(_has(res.warnings, "and the deck has none"))

    def test_a_void_without_clis_is_untouched(self):
        """bird-el's class (a void, no CLIS): bytes AND warnings = the
        part-A-i head (A10.6 (f))."""
        res, st, _e = _convert(_t9.b8_bird(card=False, clis=False))
        self.assertEqual(_tp._sha(st), _A10_BIRDEL_AI_SHA)
        self.assertEqual(_tp._sha("\n".join(res.warnings)),
                         _A10_BIRDEL_AI_WARNINGS)


class ClisPfacStiffness(unittest.TestCase):
    """A10 2a (OPT-IN ``--clis-pfac-stiffness``): Stfval = PFAC x m_node /
    dt0^2 on every CLIS ``/INTER/TYPE18`` (PFAC 0 = 0.1, < 0 refused), a
    void copy's interface x 1e-3. MEASURED (nt 4,
    ``C:/Users/pmqua/rcv_r10i_implA2_{sA_2a,q_2b2a}``): stagnation_A with
    the light fluid and the inlet at 13176.1086 - 9288 cycles, 86 % of
    LS-DYNA's inflow work by t 2.40e-4, IE RMS 223.42 %; quadrature_B at
    11.27678492 - IE RMS 492.61 %."""

    def test_the_stfval_by_hand(self):
        res, st, _e = _convert(_t9.b8_bird(card=False, clis=True),
                               clis_pfac_stiffness=True)
        s = _a10_bird_stfval()
        self.assertEqual(set(_a10_type18(st)), {90006, 90008})
        self.assertAlmostEqual(_a10_type18(st)[90006][1] / s, 1.0,
                               delta=1e-9)
        self.assertAlmostEqual(_a10_type18(st)[90008][1] / (s * 1e-3), 1.0,
                               delta=1e-9)
        self.assertTrue(_has(res.warnings, "--clis-pfac-stiffness writes "
                             "Stfval = PFAC x m_node / dt0^2 = 0.1 x "
                             "9.7625e-11", "Tsca 0.9 x the shell element step",
                             "/INTER/TYPE18/90008 (void copy part 4)",
                             "86 %", "IE RMS 206.79 -> 223.42 %"))
        # PFAC 0 is LS-DYNA's default 0.1: the same Stfval
        _r, st0, _e = _convert(_a10_pfac(_t9.b8_bird(card=False, clis=True),
                                         "0.0"), clis_pfac_stiffness=True)
        self.assertEqual(_a10_type18(st0), _a10_type18(st))

    def test_a_curve_pfac_is_refused(self):
        deck = _a10_pfac(_t9.b8_bird(card=False, clis=True), "-2.0")
        res, st, _e = _convert(deck, clis_pfac_stiffness=True)
        self.assertEqual(_a10_type18(st), {90006: (90005, 1.0),
                                           90008: (90007, 0.001)})
        self.assertTrue(_has(res.warnings, "--clis-pfac-stiffness: "
                             "/INTER/TYPE18/90006 keeps Stfval 1 - PFAC -2 is "
                             "a LOAD CURVE id"))
        state = _a10_state(deck)
        cls = state.lagrange_in_solid[0]
        self.assertEqual((cls.pfac_stated, cls.pfac), (-2.0, 0.1))

    def test_a_law0_vacuum_deck_is_refused(self):
        from k2rad.state import ConstrainedLagrangeInSolid
        from k2rad.writer import blast_ale
        st = _a10_state(_a7_coupon(), vacuum_light_fluid=False)
        cls = ConstrainedLagrangeInSolid(slave=9, master=1, mstyp=1,
                                         pfac_stated=0.1)
        stf = blast_ale._clis_pfac_stiffness(st, cls)
        self.assertIsNone(stf.would)
        self.assertIn("*MAT_VACUUM part 2 is a LAW0 /MAT/VOID", stf.refusal)
        st = _a10_state(_a7_coupon())                  # the light fluid: on
        self.assertIsNotNone(blast_ale._clis_pfac_stiffness(st, cls).would)

    def test_the_default_clis_sentence_names_the_stated_pfac(self):
        base = _t9.b8_bird(card=False, clis=True)
        for value, needle in (
                ("0.1", "PFAC 0.1 is read only by the opt-in "
                        "--clis-pfac-stiffness, which would write Stfval "),
                ("0.0", "PFAC 0 (0 = the default 0.1) is read only by the "
                        "opt-in --clis-pfac-stiffness"),
                ("-2.0", "PFAC -2 is a LOAD CURVE id (a penalty-stiffness "
                         "curve) - /INTER/TYPE18 has no field for one, so "
                         "--clis-pfac-stiffness refuses this card.")):
            with self.subTest(pfac=value):
                res, st, _e = _convert(_a10_pfac(base, value))
                self.assertTrue(_has(res.warnings, needle))
                self.assertEqual(_a10_type18(st)[90006][1], 1.0)


# ═════════════════════════════════════════════════════════════════════════════
# Part A-ii: retracted statements and the flags
# ═════════════════════════════════════════════════════════════════════════════

#: Part A-ii statements round 10 made false. CHANGELOG may quote them.
_RETRACTED_ROUND_10_A2 = (
    # A7: the *MAT_VACUUM handler's clause, MEASURED false (the water that
    # advects into a LAW0 cell is deleted there; stagnation_A)
    "so nothing flows into it",
    # A7: the README's copy of the same claim
    "here it is a separate single-material ALE region nothing flows into",
    # A7: the AMMG warning's row-state clause (stagnation_A now runs NORMAL)
    "stagnation_A's engine stops at cycle",
)

#: Never shipped, CHANGELOG included: a census mover count that was wrong
#: before it could ship (1a moves 2 / 2: ale_wavehitcol's water is
#: /MAT/VOID).
_FORBIDDEN_ROUND_10_A2 = (
    "3 / 3 movers",
    # A8: the cap's value is LS-DYNA Theory eq. 30.8 x SLSFAC x SF - a
    # formula; LS-DYNA's own measured holder penalty on the anisotropic
    # cup-draw is ~100x below it (findings 6.8; conventions F-A8)
    "effective penalty",
    # A10 2b: f = 1e-3 is a numerical floor of this converter; *CONTROL_ALE
    # VFACT is a stress cut-off on the volume fraction (conventions F-A10a;
    # its second needle 'VFACT x RO' is round 8's TRUE --shell-in-solid-
    # coupling cell, so InitialVoidCopy checks it on the A10 texts only)
    "VFACT is the void density",
)

#: (shipped file, the replacement text it now carries) - with A10's
#: gate PASSED the --no- spelling of the ALE package is shipped (F-A10b)
_REPLACEMENTS_ROUND_10_A2 = (
    ("README.md", "--no-ale-flow-tracking"),
    ("k2rad/handlers.py",
     "a LAW0 cell takes no material, so whatever advects into it is DELETED "
     "(measured on stagnation_A)"),
    ("README.md",
     "a LAW0 cell takes no material, so whatever advects into it is DELETED"),
    ("k2rad/writer/blast_ale.py",
     "stagnation_A's engine stopped at cycle 18 (t = 3.9e-5 of ENDTIM 2e-2) "
     "when that batch measured it"),
)


class Round10RetractedStatementsA2(unittest.TestCase):
    """No shipped text carries a retracted part-A-ii spelling; the guard
    fires on each needle split across two adjacent literals; a PREFIX still
    fires; the replacements ARE shipped; the forbidden sentences appear
    nowhere, CHANGELOG included."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _t7._SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_10_A2:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_10_A2 + _FORBIDDEN_ROUND_10_A2:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "')
                        + ' y')
                self.assertIn(_t7._collapse(needle).lower(), _t7._collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_10_A2 + _FORBIDDEN_ROUND_10_A2:
            with self.subTest(needle=needle):
                self.assertIn(_t7._collapse(needle[:max(4, len(needle) // 2)]),
                              _t7._collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_t7._SHIPPED_TEXTS())
        for rel, needle in _REPLACEMENTS_ROUND_10_A2:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_t7._collapse(needle), texts[key])

    def test_no_document_carries_a_forbidden_sentence(self):
        for rel, joined in _with_changelog():
            for needle in _FORBIDDEN_ROUND_10_A2:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_t7._collapse(needle).lower(),
                                     joined.lower())


class Round10FlagWiringA2(_t7.Round7FlagWiringA):
    """The round-10 default-ON levers of part A-ii (the positive spelling;
    README and the GUI summary carry the --no- one)."""

    _FLAGS = {
        "--vacuum-light-fluid": "vacuum_light_fluid",
        "--ale-inflow-ebcs": "ale_inflow_ebcs",
        "--rigid-tool-penalty-cap": "rigid_tool_penalty_cap",
        "--initial-void-copy": "initial_void_copy",
        # D-6 (the findings' 6.3a gate PASSED): round 9's opt-in, moved here
        # from test_r14_triage_9.Round9OptInWiringB
        "--ale-flow-tracking": "ale_flow_tracking",
    }
    _HELP_FIGURES = {
        "--vacuum-light-fluid": ("NEGATIVE RHO", "832 -> 9364 cycles",
                                 "LAW44 / LAW0 partner is refused by name",
                                 "RHO_I = the vacuum RO, the /EOS RHO_0 = "
                                 "the fluid RO"),
        "--ale-inflow-ebcs": ("aflux3.F:488-524", "KE RMS 53.09 -> 14.40 %",
                              "IE RMS 172.71 -> 206.79 %",
                              "(3.85e-5, 0.02]", "Never on ELFORM 5 / 6"),
        "--rigid-tool-penalty-cap": (
            "eq. 30.8", "i7for3.F:976", "Stmin = min(1000, Stmax)",
            "IE RMS 10.85 -> 4.01 %", "-13.33 / -82.43 -> -96.70 / -99.15 %",
            "END -42.14 -> -49.31 %", "KE RMS 29.17 -> 28.83 %",
            "It is the manual's formula, not a penalty"),
        "--initial-void-copy": (
            "at 1e-3 x RO", "a numerical floor of this converter",
            "(a stress cut-off)", "KE RMS 28.17 -> 10.42 %",
            "IE RMS 142.04 -> 161.11 %", "ON by default"),
        "--ale-flow-tracking": (
            "/ALE/GRID/FLOW-TRACKING", "I_def -1", "2935 -> 2976 cycles",
            "+1484.66 -> +8.15 %", "+25.88 -> -14.44 %",
            "1189.95 -> 6.71 %", "253.09 -> 3.37 %", "Stfval 133.1",
            "0.37 point", "ON by default", "none of the three"),
    }


class Round10OptInWiringA2(_t8.Round8OptInWiringB):
    """The round-10 part-A-ii OPT-IN lever (default OFF): parser + --no-
    twin, README prose (the POSITIVE spelling) and its own ### heading, the
    --help figures, the GUI end to end, convert() / ConvertOptions default
    False and cli.main()'s call."""

    _OPT_IN = {"--clis-pfac-stiffness": "clis_pfac_stiffness"}
    _HELP_FIGURES = {
        "--clis-pfac-stiffness": (
            "PFAC x m_node / dt0^2", "86 % of", "IE RMS 206.79 -> 223.42 %",
            "161.11 -> 492.61 %", "+0.11 / +1.77 % above",
            "OFF by default"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Part B - the CardStack batch's contact and damping leftovers (the behaviour
# tests sit beside the CardStack classes they re-pin, in
# tests/test_cardstack_pipeline*.py and tests/test_preload_inistate.py)
# ═════════════════════════════════════════════════════════════════════════════

class Round10FlagWiringB(_t7.Round7FlagWiringA):
    """The round-10 default-ON levers of part B (the positive spelling;
    README and the GUI summary carry the --no- one)."""

    _FLAGS = {
        "--surfatyp-all-parts": "surfatyp_all_parts",
        "--tiebreak-companion-stfac": "tiebreak_companion_stfac",
    }
    _HELP_FIGURES = {
        "--surfatyp-all-parts": ("Vol I R17 p.11-25", "0.3489 mm",
                                 "t_s/2 + t_m/2 = 0.35",
                                 "R14: 0 decks move"),
        "--tiebreak-companion-stfac": (
            "hm_read_inter_type25.F:620-622",
            "STIFFNESS FACTOR 1.000 -> 0.300", "0.000914 -> 0.002344 mm",
            "685 -> 515 cycles"),
    }


if __name__ == "__main__":
    unittest.main()
