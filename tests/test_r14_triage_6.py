"""Tests for the R14 CAMPAIGN TRIAGE batch, round 6 — PART A:

  A1  the ELFORM-12 void cavitation floor: ``Pmin = -1e-20`` on the
      ``/MAT/HYD_VISC`` of a ``*INITIAL_VOID`` deck's fluid (default ON,
      ``--no-initial-void-floor``), the AMMG / non-ELFORM-12 / non-LAW6
      refusals, and the rewritten ``/INTER/TYPE18`` void warning

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are the round-4/5 ones, copied (not imported) so this module
runs on its own.
"""

import os
import re
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the helpers of tests/test_r14_triage_5.py) ──────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text, engine_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


def _dispatch(deck: str) -> ConversionState:
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    tmp.cleanup()
    return state


def _has(warnings, *needles) -> bool:
    return any(all(n in w for n in needles) for w in warnings)


def _card_rows(text: str, header: str):
    """Every data line that immediately follows *header* in *text*."""
    lines = text.splitlines()
    return [lines[i + 1] for i, ln in enumerate(lines) if ln == header]


def _block_after(text: str, head: str, n: int):
    """*n* lines following the line that starts with *head*."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(head):
            return lines[i:i + n]
    raise AssertionError(f"{head!r} not in the emitted deck")


def _collapse(text: str) -> str:
    """One space per whitespace run — so a sentence split across source lines
    reads as the one sentence a user sees."""
    return re.sub(r"\s+", " ", text)


def _SHIPPED_TEXTS():
    """``(relative path, normalized text)`` for every text a figure can ship in
    (the round-4/5 convention): README, ROADMAP, the GUI and every module of
    the package, adjacent string literals JOINED before the whitespace
    collapses. ``CHANGELOG.md`` is the historical record and is excluded."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rels = ["README.md", "ROADMAP.md", "k2rad_gui.py"]
    for dirpath, _dirs, files in os.walk(os.path.join(root, "k2rad")):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                rels.append(os.path.relpath(
                    os.path.join(dirpath, name), root))
    out = []
    for rel in rels:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):        # a measurement, not an assumption
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        out.append((rel, _collapse(re.sub(r'"\s*\n\s*"', "", text))))
    assert len(out) >= 10, out
    return out


def _mat_block(text: str, head: str):
    """The lines of the ``/MAT/...`` block *head* (up to the next ``/`` card
    or the ``#---`` separator)."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln == head:
            out = [ln]
            for nxt in lines[i + 1:]:
                if nxt.startswith("/") or nxt.startswith("#---"):
                    break
                out.append(nxt)
            return out
    raise AssertionError(f"{head!r} not in the emitted deck")


def _pmin_row(text: str, mid: int) -> str:
    """The ``Nu Pmin`` data row of ``/MAT/HYD_VISC/<mid>``."""
    block = _mat_block(text, f"/MAT/HYD_VISC/{mid}")
    for j, ln in enumerate(block):
        if ln.startswith("#") and "Pmin" in ln:
            return block[j + 1]
    raise AssertionError(f"no Pmin row in /MAT/HYD_VISC/{mid}: {block}")


# ═════════════════════════════════════════════════════════════════════════════
# A1 — the ELFORM-12 void cavitation floor
# ═════════════════════════════════════════════════════════════════════════════

_FLOOR_ROW = "                   0       -1.000000E-20"
_ZERO_ROW = "                   0                   0"


def _void_deck(pc1=0.0, elform1=12, void_mat="null", shared_mat=False,
               void=True, ammg=False, coupled=False, void_set=False) -> str:
    """Two unit hexes sharing the x = 1 face: element 1 on part 1 (the void,
    section 1), element 2 on part 2 (the bird, section 2), both ELFORM 12 on
    a *MAT_NULL + *EOS_GRUNEISEN pair unless a variant says otherwise."""
    nodes = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1, 2)]
    nid = {c: i for i, c in enumerate(nodes, start=1)}

    def hexa(x0):
        return [nid[(x0, 0, 0)], nid[(x0 + 1, 0, 0)], nid[(x0 + 1, 1, 0)],
                nid[(x0, 1, 0)], nid[(x0, 0, 1)], nid[(x0 + 1, 0, 1)],
                nid[(x0 + 1, 1, 1)], nid[(x0, 1, 1)]]

    mid2 = 1 if shared_mat else 2
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n"
            + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                      for i, (x, y, z) in enumerate(nodes, start=1))
            + "*ELEMENT_SOLID\n"
            + "".join(f"{v:>8}" for v in [1, 1] + hexa(0)) + "\n"
            + "".join(f"{v:>8}" for v in [2, 2] + hexa(1)) + "\n"
            + "*PART\nvoid\n" + _row(1, 1, 1) + "\n"
            + "*PART\nbird\n" + _row(2, 2, mid2) + "\n"
            + "*SECTION_SOLID\n" + _row(1, elform1) + "\n"
            + "*SECTION_SOLID\n" + _row(2, 12) + "\n")
    if void_mat == "null":
        deck += ("*MAT_NULL\n" + _row(1, 1.0e-9, pc1, 0.0) + "\n"
                 "*EOS_GRUNEISEN\n" + _row(1, 1.5e6, 1.0, 0.0, 0.0, 0.0,
                                           0.0, 0.0) + "\n"
                 + _row(1.0) + "\n")
    else:
        deck += "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
    if not shared_mat:
        deck += ("*MAT_NULL\n" + _row(2, 1.0e-9, 0.0, 0.0) + "\n"
                 "*EOS_GRUNEISEN\n" + _row(2, 1.5e6, 1.0, 0.0, 0.0, 0.0,
                                           0.0, 0.0) + "\n"
                 + _row(1.0) + "\n")
    if ammg:
        deck += ("*ALE_MULTI-MATERIAL_GROUP\n" + _row(1, 1) + "\n"
                 + _row(2, 1) + "\n")
    if coupled:
        deck += ("*NODE\n"
                 + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                           for i, (x, y, z) in enumerate(
                               [(0, 0, 2), (2, 0, 2), (2, 1, 2), (0, 1, 2)],
                               start=101))
                 + "*ELEMENT_SHELL\n" + _row(101, 3, 101, 102, 103, 104)
                 + "\n*PART\nplate\n" + _row(3, 3, 3) + "\n"
                 "*SECTION_SHELL\n" + _row(3, 2) + "\n"
                 + _row(0.1, 0.1, 0.1, 0.1) + "\n"
                 "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
                 "*SET_PART_LIST\n" + _row(9) + "\n" + _row(1, 2) + "\n"
                 "*CONSTRAINED_LAGRANGE_IN_SOLID\n"
                 + _row(3, 9, 1, 0, 1, 4, 2, 1) + "\n"
                 + _row(0.0, 0.0, 0.1, 0.0) + "\n")
    if void:
        if void_set:
            deck += ("*SET_PART_LIST\n" + _row(7) + "\n" + _row(1) + "\n"
                     "*INITIAL_VOID_SET\n" + _row(7) + "\n")
        else:
            deck += "*INITIAL_VOID_PART\n" + _row(1) + "\n"
    return deck + "*END\n"


class InitialVoidFloorTests(unittest.TestCase):
    """A1 — ``Pmin 0`` on ``/MAT/HYD_VISC`` is read as -INFINITY
    (``hm_read_mat06.F:154``), an unbounded tension in the cells the fluid of
    an ELFORM-12 void deck leaves; the floor is ``-1e-20`` on EVERY LAW6
    material of that fluid, and nothing else moves."""

    def _floor_warnings(self, result):
        return [w for w in result.warnings if "cavitation floor" in w]

    def test_the_floor_is_written_on_both_LAW6_cards(self):
        result, starter, _e = _convert(_void_deck())
        self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)
        self.assertEqual(_pmin_row(starter, 2), _FLOOR_ROW)
        applied = [w for w in result.warnings
                   if "cavitation floor Pmin = -1e-20 is written" in w]
        self.assertEqual(len(applied), 1, result.warnings)
        self.assertIn("/MAT/HYD_VISC [1, 2]", applied[0])
        self.assertIn("(parts [1, 2])", applied[0])
        self.assertIn("hm_read_mat06.F:154", applied[0])
        self.assertIn("--no-initial-void-floor", applied[0])
        self.assertNotIn("OVERRIDDEN", applied[0])

    def test_the_Pmin_cell_is_columns_21_to_40(self):
        """``radioss2020/MAT/mat_law6.cfg``: ``%20lg%20lg`` = Nu, Pmin."""
        _r, starter, _e = _convert(_void_deck())
        row = _pmin_row(starter, 1)
        self.assertEqual(len(row), 40)
        self.assertEqual(row[:20].strip(), "0")
        self.assertEqual(row[20:40].strip(), "-1.000000E-20")

    def test_a_stated_PC_is_overridden_and_named(self):
        result, starter, _e = _convert(_void_deck(pc1=-1.0e5))
        self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)
        self.assertEqual(_pmin_row(starter, 2), _FLOOR_ROW)
        self.assertTrue(_has(result.warnings, "PC -100000", "OVERRIDDEN",
                             "*MAT_NULL 1"), result.warnings)
        # a Gruneisen EOS is not the linear P = C1*mu case
        self.assertFalse(_has(result.warnings, "own tensile limit"))

    def test_a_shared_material_is_one_floored_card(self):
        _r, starter, _e = _convert(_void_deck(shared_mat=True))
        self.assertEqual(starter.count("/MAT/HYD_VISC/"), 1)
        self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)

    def test_a_void_SET_reaches_the_same_rule(self):
        result, starter, _e = _convert(_void_deck(void_set=True))
        self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)
        self.assertEqual(_pmin_row(starter, 2), _FLOOR_ROW)
        self.assertTrue(_has(result.warnings, "*INITIAL_VOID_SET [1]",
                             "is written"), result.warnings)

    def test_AMMG_refuses_and_the_deck_is_the_opt_out_arm(self):
        r_on, s_on, _e = _convert(_void_deck(ammg=True))
        _r_off, s_off, _e2 = _convert(_void_deck(ammg=True),
                                      initial_void_floor=False)
        self.assertEqual(s_on, s_off)
        self.assertEqual(_pmin_row(s_on, 1), _ZERO_ROW)
        self.assertTrue(_has(r_on.warnings, "NOT written",
                             "*ALE_MULTI-MATERIAL_GROUP", "p.28-134"),
                        r_on.warnings)

    def test_a_void_that_is_not_ELFORM_12_is_refused(self):
        result, starter, _e = _convert(_void_deck(elform1=11))
        self.assertEqual(_pmin_row(starter, 2), _ZERO_ROW)
        self.assertEqual(_pmin_row(starter, 1), _ZERO_ROW)
        self.assertTrue(_has(result.warnings, "NOT written", "ELFORM 11",
                             "not 12"), result.warnings)

    def test_a_non_LAW6_void_is_refused(self):
        """forging_B's shape: the void part's material has no LAW6 carrier."""
        result, starter, _e = _convert(_void_deck(void_mat="elastic"))
        self.assertNotIn("/MAT/HYD_VISC/1", starter)
        self.assertEqual(_pmin_row(starter, 2), _ZERO_ROW)
        self.assertTrue(_has(result.warnings, "NOT written", "material 1",
                             "not a *MAT_NULL + *EOS_* carrier"),
                        result.warnings)

    def test_no_void_no_change_and_no_warning(self):
        result, starter, _e = _convert(_void_deck(void=False))
        self.assertEqual(_pmin_row(starter, 1), _ZERO_ROW)
        self.assertEqual(_pmin_row(starter, 2), _ZERO_ROW)
        self.assertFalse(any("INITIAL_VOID" in w or "cavitation" in w
                             for w in result.warnings), result.warnings)

    def test_the_opt_out_keeps_Pmin_0_and_says_so_once(self):
        result, starter, _e = _convert(_void_deck(), initial_void_floor=False)
        self.assertEqual(_pmin_row(starter, 1), _ZERO_ROW)
        self.assertEqual(_pmin_row(starter, 2), _ZERO_ROW)
        opt = [w for w in result.warnings if "--no-initial-void-floor:" in w]
        self.assertEqual(len(opt), 1, result.warnings)
        self.assertIn("-INFINITY", opt[0])

    def test_refusal_and_opt_out_texts_never_say_NOT_VALID(self):
        """Round 4's controls assert no warning says NOT VALID on a deck
        without the coupling; the floor's own texts must not trip them."""
        for kw in ({"ammg": True}, {"elform1": 11}, {"void_mat": "elastic"}):
            with self.subTest(**kw):
                result, _s, _e = _convert(_void_deck(**kw))
                self.assertFalse(any("NOT VALID" in w
                                     for w in result.warnings))
        result, _s, _e = _convert(_void_deck(), initial_void_floor=False)
        self.assertFalse(any("NOT VALID" in w for w in result.warnings))

    def test_the_TYPE18_coupled_void_gets_the_rewritten_warning(self):
        result, starter, _e = _convert(_void_deck(coupled=True))
        self.assertIn("/INTER/TYPE18/", starter)
        self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)
        self.assertEqual(_pmin_row(starter, 2), _FLOOR_ROW)
        fsi = [w for w in result.warnings if "NOT VALID" in w]
        self.assertEqual(len(fsi), 1, result.warnings)
        for needle in ("*INITIAL_VOID_PART 1", "quadrature_B", "2.15e-18",
                       "47.2x", "intcrit.F:508-518",
                       "k2rad writes the cavitation floor"):
            with self.subTest(needle=needle):
                self.assertIn(needle, fsi[0])
        self.assertNotIn("No /INTER/TYPE18 parameter", fsi[0])

    def test_the_coupled_void_warning_names_a_refused_floor(self):
        result, _s, _e = _convert(_void_deck(coupled=True),
                                  initial_void_floor=False)
        fsi = [w for w in result.warnings if "NOT VALID" in w]
        self.assertEqual(len(fsi), 1, result.warnings)
        self.assertIn("The cavitation floor is NOT written: "
                      "--no-initial-void-floor.", fsi[0])

    def test_the_coupled_void_warning_names_a_refusal_clause(self):
        """forging_B's shape: a coupled void whose material has no LAW6
        carrier — the TYPE18 warning names the refusal itself."""
        deck = _void_deck(coupled=True, void_mat="elastic")
        result, _s, _e = _convert(deck)
        fsi = [w for w in result.warnings if "NOT VALID" in w]
        self.assertEqual(len(fsi), 1, result.warnings)
        self.assertIn("The cavitation floor is NOT written: part 1: "
                      "material 1 is not a *MAT_NULL + *EOS_* carrier",
                      fsi[0])

    def test_ONE_decision_the_warning_reads_the_record_not_the_option(self):
        """Flip the option AFTER the materials section decided: the TYPE18
        warning must still report the decision the card carries."""
        from k2rad.writer import blast_ale, materials
        state = _dispatch(_void_deck(coupled=True))
        state.options.initial_void_floor = True
        lines = materials._make_explosive_and_eos_materials(state)
        self.assertIn(_FLOOR_ROW, lines)
        state.options.initial_void_floor = False      # after the decision
        blast_ale._make_fsi_coupling(state)
        fsi = [w for w in state.warnings if "NOT VALID" in w]
        self.assertEqual(len(fsi), 1, state.warnings)
        self.assertIn("k2rad writes the cavitation floor", fsi[0])
        self.assertFalse(any("--no-initial-void-floor:" in w
                             for w in state.warnings))

    def test_a_direct_TYPE18_caller_still_resolves_the_floor(self):
        from k2rad.writer import blast_ale
        state = _dispatch(_void_deck(coupled=True))
        self.assertIsNone(state.initial_void_floor)
        blast_ale._make_fsi_coupling(state)
        self.assertEqual(state.initial_void_floor, {1: 0.0, 2: 0.0})

    def test_the_linear_EOS_clause_is_computed_not_assumed(self):
        """bird_B's shape: *EOS_LINEAR_POLYNOMIAL C1 = 1, every other
        coefficient 0, PC -1 — the stated cutoff equals the EOS's own
        tensile limit, and the warning says so; PC -0.5 is a real cutoff and
        gets no such clause."""
        base = _void_deck(shared_mat=True)
        lin = base.replace(
            "*EOS_GRUNEISEN\n" + _row(1, 1.5e6, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            + "\n" + _row(1.0) + "\n",
            "*EOS_LINEAR_POLYNOMIAL\n" + _row(1, 0.0, 1.0, 0.0, 0.0, 0.0,
                                              0.0, 0.0) + "\n"
            + _row(0.0, 1.0) + "\n")
        self.assertIn("*EOS_LINEAR_POLYNOMIAL", lin)
        for pc, clause in ((-1.0, True), (-0.5, False)):
            deck = lin.replace("*MAT_NULL\n" + _row(1, 1.0e-9, 0.0, 0.0),
                               "*MAT_NULL\n" + _row(1, 1.0e-9, pc, 0.0))
            with self.subTest(pc=pc):
                result, starter, _e = _convert(deck)
                self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)
                self.assertEqual(_has(result.warnings, "own tensile limit",
                                      f"PC {pc:g}"), clause, result.warnings)

    def test_MAT_NULL_reads_PC_and_keeps_its_other_fields(self):
        st = _dispatch(_void_deck(pc1=-7.5))
        m = st.mat_null[1]
        self.assertEqual((m.rho, m.pc, m.E, m.nu), (1.0e-9, -7.5, 0.0, 0.0))


# ═════════════════════════════════════════════════════════════════════════════
# Wiring and the retracted statements (every Part-A item)
# ═════════════════════════════════════════════════════════════════════════════

class Round6FlagWiringA(unittest.TestCase):
    """Every new Part-A lever reaches the parser, the API, the GUI and the
    README (the round-5 ``Round5FlagWiring`` checks, for this round's list)."""

    #: default-ON opt-outs: the spelling the README and the GUI summary carry
    #: is the ``--no-`` one.
    _FLAGS = {
        "--initial-void-floor": "initial_void_floor",
    }
    #: figures each flag's --help must carry (matched on the collapsed render)
    _HELP_FIGURES = {
        "--initial-void-floor": ("1095 cycles", "2936 cycles",
                                 "hm_read_mat06.F:154"),
    }

    def _readme(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_every_flag_is_a_parser_option_with_its_no_twin(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        for flag in self._FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts)
                self.assertIn("--no-" + flag[2:], opts)

    def test_every_no_spelling_is_in_README_prose(self):
        readme = self._readme()
        body = [ln for ln in readme.splitlines()
                if not re.match(r"^\s*[-*]?\s*\[.*\]\(#.*\)\s*$", ln)]
        for flag in self._FLAGS:
            neg = "--no-" + flag[2:]
            with self.subTest(flag=neg):
                self.assertTrue(any(neg in ln for ln in body),
                                f"{neg} is not in README.md prose")

    def test_the_help_renders_and_carries_the_measured_numbers(self):
        """A bare % in a help string kills --help at a green suite."""
        from k2rad import cli
        text = cli.build_parser().format_help()
        flat = _collapse(text)
        for flag, figures in self._HELP_FIGURES.items():
            self.assertIn("--no-" + flag[2:], text)
            for figure in figures:
                with self.subTest(flag=flag, figure=figure):
                    self.assertIn(figure, flat)

    def test_the_gui_wires_every_lever_end_to_end(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        for name in self._FLAGS.values():
            with self.subTest(name=name):
                kw = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="",
                    **{name: False})
                self.assertIs(kw[name], False)
                captured = []
                app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
                app._append = captured.append
                k2rad_gui.ConverterGUI._describe_options(app, kw)
                self.assertIn("--no-" + name.replace("_", "-"),
                              "".join(captured))
                # ... and the default arm says NOTHING about it
                kw_on = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), ground_springs=False,
                    ground_spring_k_text="", soften_stfac_text="")
                self.assertIs(kw_on[name], True)
                captured_on = []
                app._append = captured_on.append
                k2rad_gui.ConverterGUI._describe_options(app, kw_on)
                self.assertNotIn("--no-" + name.replace("_", "-"),
                                 "".join(captured_on))
        tmp.cleanup()

    def test_every_lever_reaches_convert_and_ConvertOptions(self):
        import inspect
        from k2rad.state import ConvertOptions
        sig = inspect.signature(convert).parameters
        fields = set(ConvertOptions.__dataclass_fields__)
        for name in self._FLAGS.values():
            with self.subTest(name=name):
                self.assertIn(name, sig)
                self.assertIs(sig[name].default, True)
                self.assertIn(name, fields)
                self.assertIs(ConvertOptions().__getattribute__(name), True)


#: Statements Part A of round 6 measured to be wrong. CHANGELOG may quote
#: them (it is the history); no other shipped text may.
_RETRACTED_ROUND_6_A = (
    # A1: the cavitation floor moves quadrature_B from a timeout to NORMAL
    "No /INTER/TYPE18 parameter moves this",
)


class Round6RetractedStatementsA(unittest.TestCase):
    """The round-4/5 four-test shape: no needle in any shipped text; the
    guard fires on each needle split across two adjacent literals; a PREFIX
    still fires; the replacement text IS shipped."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_6_A:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle).lower(),
                                     joined.lower())

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_6_A:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "') + ' y')
                self.assertIn(_collapse(needle).lower(), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)).lower())

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_6_A:
            with self.subTest(needle=needle):
                self.assertIn(_collapse(needle[:max(8, len(needle) // 2)]),
                              _collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_SHIPPED_TEXTS())
        pairs = (
            ("k2rad/writer/blast_ale.py", "STALLS at t 2.227e-4"),
            ("k2rad/writer/materials.py",
             "-1e-20 is the zero-pressure cavitation limit *MAT_NULL "
             "Remark 4"),
            ("README.md", "--no-initial-void-floor"),
            ("ROADMAP.md", "PARTLY closed — the cavitation FLOOR shipped"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])


if __name__ == "__main__":
    unittest.main()
