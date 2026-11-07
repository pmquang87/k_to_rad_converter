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


if __name__ == "__main__":
    unittest.main()
