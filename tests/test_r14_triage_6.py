"""Tests for the R14 CAMPAIGN TRIAGE batch, round 6 — PART A, and PART B below:

  A1  the ELFORM-12 void cavitation floor: ``Pmin = -1e-20`` on the
      ``/MAT/HYD_VISC`` of a ``*INITIAL_VOID`` deck's fluid (default ON,
      ``--no-initial-void-floor``), the AMMG / non-ELFORM-12 / non-LAW6
      refusals, and the rewritten ``/INTER/TYPE18`` void warning
  A2  the weld failure exponents N / M on ``/PROP/TYPE13`` (default ON,
      ``--no-weld-exponents``)
  A3  the spring-token screen tests the node's OWN lumped mass
  A4  ``*CONSTRAINED_TIED_NODES_FAILURE``: a named refusal, 0 bytes
  A5  ``*CONSTRAINED_LINEAR_LOCAL`` / ``_GLOBAL`` -> ``/MPC`` (default ON,
      ``--no-constrained-linear``)
  A6  the zero-coupling ``*MAT_ANISOTROPIC_ELASTIC`` -> the orthotropic path
  A7  ``J = -SUM(IN)`` on the re-pointed ``/RBODY`` under
      ``--mass-weighted-inivel``
  A8  the shell-offset Gapmin: ``t/2`` on a solid-main ``/INTER/TYPE7``
      against shells LS-DYNA offsets (default ON,
      ``--no-shell-offset-gapmin``)

PART B:

  B1  a ``*CONTROL_IMPLICIT_SOLUTION`` whose tolerances are all 0 / blank gets
      LS-DYNA's own ECTOL default, ``/IMPL/NONLIN`` Itol 1 Toli 0.01 (default
      ON, ``--no-zero-tolerance-ectol``)
  B2  the constant-step warning for an implicit deck with no
      ``*CONTROL_IMPLICIT_AUTO`` (warning only)
  B3  ``--implicit-constant-step``: ``/IMPL/DT/STOP`` DT_MAX := DT0 (opt-in)
  B4  the implicit-dynamics + initial-velocity ENGINE-defect warning and the
      ``/IMPL/NONLIN/SOLVINFO`` remedy sentence
  B5  ``*CONSTRAINED_GLOBAL`` -> ``/BCS`` through the TC/RC union (default ON,
      ``--no-constrained-global``)
  B6  ``--spotweld-node-synthesis`` / ``--beam-contact-secondary`` (opt-in)
  B7  the corrected records and texts (the retraction guards)

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
               void=True, ammg=False, coupled=False, void_set=False,
               third_elform=None) -> str:
    """Two unit hexes sharing the x = 1 face: element 1 on part 1 (the void,
    section 1), element 2 on part 2 (the bird, section 2), both ELFORM 12 on
    a *MAT_NULL + *EOS_GRUNEISEN pair unless a variant says otherwise.
    ``third_elform`` adds a third hex (x 2..3) on part 3 / section 3 of that
    ELFORM with its OWN *MAT_NULL 3 + *EOS_GRUNEISEN 3."""
    xs = (0, 1, 2) if third_elform is None else (0, 1, 2, 3)
    nodes = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in xs]
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
    if third_elform is not None:
        deck += ("*ELEMENT_SOLID\n"
                 + "".join(f"{v:>8}" for v in [3, 3] + hexa(2)) + "\n"
                 + "*PART\nthird fluid\n" + _row(3, 3, 3) + "\n"
                 + "*SECTION_SOLID\n" + _row(3, third_elform) + "\n"
                 + "*MAT_NULL\n" + _row(3, 1.0e-9, 0.0, 0.0) + "\n"
                 "*EOS_GRUNEISEN\n" + _row(3, 1.5e6, 1.0, 0.0, 0.0, 0.0,
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

    def test_a_LAW6_fluid_off_ELFORM_12_is_not_floored(self):
        """Finalization round (the code-sweep mutation that survived: the
        ``elform == 12`` clause of the fluid set could be deleted with every
        test green, because every variant paired the void with ONE
        ELFORM-12 bird). A third *MAT_NULL + EOS fluid on ELFORM 5 is not
        the void's fluid: its /MAT/HYD_VISC keeps Pmin 0 and the floor
        warning does not name it."""
        result, starter, _e = _convert(_void_deck(third_elform=5))
        self.assertEqual(_pmin_row(starter, 1), _FLOOR_ROW)
        self.assertEqual(_pmin_row(starter, 2), _FLOOR_ROW)
        self.assertEqual(_pmin_row(starter, 3), _ZERO_ROW)
        applied = [w for w in result.warnings
                   if "cavitation floor Pmin = -1e-20 is written" in w]
        self.assertEqual(len(applied), 1, result.warnings)
        self.assertIn("/MAT/HYD_VISC [1, 2]", applied[0])
        self.assertIn("(parts [1, 2])", applied[0])
        # the control: the same third fluid ON ELFORM 12 is the fluid
        result12, starter12, _e = _convert(_void_deck(third_elform=12))
        self.assertEqual(_pmin_row(starter12, 3), _FLOOR_ROW)
        self.assertTrue(_has(result12.warnings, "/MAT/HYD_VISC [1, 2, 3]",
                             "(parts [1, 2, 3])"), result12.warnings)

    def test_a_refusal_names_only_the_Pmin_cells_the_deck_has(self):
        """Finalization round: forging_B's converted deck has NO
        /MAT/HYD_VISC at all, and the refusal said "the fluid's
        /MAT/HYD_VISC keep Pmin 0". The tail now names what exists."""
        r_none, s_none, _e = _convert(_void_deck(void_mat="elastic",
                                                  shared_mat=True))
        self.assertNotIn("/MAT/HYD_VISC/", s_none)
        refusal = [w for w in r_none.warnings
                   if "cavitation floor was NOT written" in w]
        self.assertEqual(len(refusal), 1, r_none.warnings)
        self.assertIn("the deck emits no /MAT/HYD_VISC at all", refusal[0])
        self.assertNotIn("keep Pmin 0", refusal[0])
        r_fl, _s, _e = _convert(_void_deck(void_mat="elastic"))
        refusal = [w for w in r_fl.warnings
                   if "cavitation floor was NOT written" in w]
        self.assertEqual(len(refusal), 1, r_fl.warnings)
        self.assertIn("the ELFORM-12 fluid's /MAT/HYD_VISC [2] keep Pmin 0",
                      refusal[0])
        r_opt, _s, _e = _convert(_void_deck(void_mat="elastic",
                                            shared_mat=True),
                                 initial_void_floor=False)
        self.assertTrue(_has(r_opt.warnings, "--no-initial-void-floor:",
                             "the deck emits no /MAT/HYD_VISC at all"),
                        r_opt.warnings)

    def test_the_floor_text_carries_bird_Bs_history(self):
        """Finalization round: a final-state number is not evidence without
        its history - bird_B's end KE +25.9 % sits in a history of +104 /
        +382 / +337 / +18 / +26 % at the fifths."""
        result, _s, _e = _convert(_void_deck())
        applied = [w for w in result.warnings
                   if "cavitation floor Pmin = -1e-20 is written" in w]
        self.assertEqual(len(applied), 1)
        for needle in ("+104 / +382 / +337 / +18 / +26 %",
                       "KE +765 % at cycle 0", "IE +1111..+1525 %",
                       "KE +272 / +398 / +144 / -72 / -92 %",
                       "every *MAT_NULL + *EOS_* /MAT/HYD_VISC k2rad wrote"):
            with self.subTest(needle=needle):
                self.assertIn(needle, applied[0])


# ═════════════════════════════════════════════════════════════════════════════
# A2 — the weld failure exponents on /PROP/TYPE13
# ═════════════════════════════════════════════════════════════════════════════

_TOKEN = 1.0e-4
_SHARE = _TOKEN / 2.0


def _plate(nid0=1, z0=0.0, eid=1, pid=1):
    """Four nodes + one shell, so their nodes carry element mass of their own."""
    pts = [(0.0, 0.0, z0), (10.0, 0.0, z0), (10.0, 10.0, z0), (0.0, 10.0, z0)]
    nodes = "".join(f"{nid0 + i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
                    for i, (x, y, z) in enumerate(pts))
    elem = _row(eid, pid, nid0, nid0 + 1, nid0 + 2, nid0 + 3) + "\n"
    return nodes, elem


def _weld_deck(sn=1.0e4, ss=5.0e4, n=None, m=None, gen=False,
               plate_mat="elastic", tshell=False, composite=False,
               rho=7.85e-9, part_mass=0.0, admas=0.0) -> str:
    """Two plates 1 mm apart, node 1 welded to node 11 (a finite length),
    *CONSTRAINED_SPOTWELD WITH failure forces (or the _GENERALIZED_WELD_SPOT
    spelling over a two-node set). A blank N/M cell is the reader's 2.0.

    ``plate_mat`` "orthotropic" puts the plates on *MAT_ORTHOTROPIC_ELASTIC
    (a container outside the lumper's historic six); ``tshell`` meshes them as
    *ELEMENT_TSHELL; ``composite`` puts them on a two-ply *PART_COMPOSITE;
    ``part_mass`` adds an *ELEMENT_MASS_PART on both plates; ``admas`` an
    *ELEMENT_MASS on the two weld nodes."""
    n1, e1 = _plate(1, 0.0, 1, 1)
    n2, e2 = _plate(11, 1.0, 2, 2)
    kw = "*ELEMENT_TSHELL\n" if tshell else "*ELEMENT_SHELL\n"
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            "*NODE\n" + n1 + n2 + kw + e1 + e2)
    if composite:
        deck += "".join(
            f"*PART_COMPOSITE\nplate{p}\n"
            + _row(p, 2, 0.0, 0, 0.0, 0, 0, 0) + "\n"
            + _row(1, 0.5, 0.0, 0, 1, 0.5, 0.0, 0) + "\n"
            for p in (1, 2))
    else:
        deck += ("*PART\nplate1\n" + _row(1, 1, 1) + "\n"
                 "*PART\nplate2\n" + _row(2, 1, 1) + "\n")
        if tshell:
            deck += "*SECTION_TSHELL\n" + _row(1, 1) + "\n" + _row(1.0) + "\n"
        else:
            deck += ("*SECTION_SHELL\n" + _row(1, 2) + "\n"
                     + _row(1.0, 1.0, 1.0, 1.0) + "\n")
    if plate_mat == "orthotropic":
        deck += ("*MAT_ORTHOTROPIC_ELASTIC\n"
                 + _row(1, rho, 2.0e5, 1.0e5, 1.0e5, 0.1, 0.1, 0.1) + "\n"
                 + _row(5.0e4, 5.0e4, 5.0e4, 2) + "\n"
                 + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _row(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n")
    else:
        deck += "*MAT_ELASTIC\n" + _row(1, rho, 210000.0, 0.3) + "\n"
    cells = [sn, ss] + ["" if v is None else v for v in (n, m)]
    if gen:
        deck += ("*SET_NODE_LIST\n" + _row(3) + "\n" + _row(1, 11) + "\n"
                 "*CONSTRAINED_GENERALIZED_WELD_SPOT\n" + _row(3) + "\n"
                 + _row(0.0, 0.0, *cells) + "\n")
    else:
        deck += "*CONSTRAINED_SPOTWELD\n" + _row(1, 11, *cells) + "\n"
    if part_mass:
        deck += "".join("*ELEMENT_MASS_PART\n" + _row(p, part_mass) + "\n"
                        for p in (1, 2))
    if admas:
        deck += ("*ELEMENT_MASS\n"
                 + "".join(f"{900 + i:>8}{nd:>8}{admas:>16.8G}\n"
                           for i, nd in enumerate((1, 11))))
    return deck + "*END\n"


def _type13_ab_rows(starter: str):
    """The six ``c n alpha beta`` data rows of the weld tie's /PROP/TYPE13."""
    lines = starter.splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("/PROP/TYPE13/")
                 and "(stiff weld tie)" in lines[i + 1])
    rows = []
    for i in range(start, len(lines)):
        if re.match(r"^#\s+c\d\s+n\d\s+alpha\d\s+beta\d$", lines[i]):
            rows.append(lines[i + 1])
        if len(rows) == 6:
            break
    assert len(rows) == 6, lines[start:start + 40]
    return rows


_ZERO4 = "                   0" * 4
_ONE_ONE = ("                   0                   0"
            "                   1                   1")


class WeldExponentTests(unittest.TestCase):
    """A2 — the TYPE13 ``alpha``/``beta`` cells were always blank, which the
    reader turns into 1 / 2 (``hm_read_prop13.F:1169-1170``): the converted
    criterion was exponent 2 whatever N and M the deck stated."""

    def test_N_M_1_writes_the_cells(self):
        result, starter, _e = _convert(_weld_deck(n=1.0, m=1.0))
        rows = _type13_ab_rows(starter)
        self.assertEqual(rows[:3], [_ONE_ONE] * 3)
        self.assertEqual(rows[3:], [_ZERO4] * 3)
        for row in rows[:3]:
            self.assertEqual(len(row), 80)
            self.assertEqual(row[40:60].strip(), "1")   # alpha, cols 41-60
            self.assertEqual(row[60:80].strip(), "1")   # beta, cols 61-80
        w = [x for x in result.warnings if "failure exponents N=1 / M=1" in x]
        self.assertEqual(len(w), 1, result.warnings)
        for needle in ("alpha1-3 = 1, beta1 = 1, beta2 = beta3 = 1",
                       "hm_read_prop13.F:1169-1170", "r4def3.F:361",
                       "2.460e-4", "0.899x", "--no-weld-exponents",
                       "1.414x"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w[0])

    def test_a_mixed_pair_and_the_caveat_only_when_M_is_not_2(self):
        result, starter, _e = _convert(_weld_deck(n=1.5, m=2.0))
        rows = _type13_ab_rows(starter)
        self.assertEqual(rows[0][40:60].strip(), "1")
        self.assertEqual(rows[0][60:80].strip(), "1.5")
        for row in rows[1:3]:
            self.assertEqual(row[40:60].strip(), "1")
            self.assertEqual(row[60:80].strip(), "2")
        self.assertTrue(_has(result.warnings, "N=1.5 / M=2"))
        self.assertFalse(_has(result.warnings, "RESULTANT"))
        result2, starter2, _e2 = _convert(_weld_deck(n=2.0, m=1.0))
        rows2 = _type13_ab_rows(starter2)
        self.assertEqual(rows2[0][60:80].strip(), "2")
        self.assertEqual(rows2[1][60:80].strip(), "1")
        self.assertTrue(_has(result2.warnings, "RESULTANT", "1.414x"))

    def test_the_caveat_states_the_direction_that_follows_M(self):
        """Finalization round: Radioss sums (|fy|/SS)^M + (|fz|/SS)^M per
        shear DOF (r4def3.F:374 / :449), LS-DYNA scores the resultant; with
        equal components the ratio is 2^(1 - M/2) - above 1 for M < 2
        (Radioss fails first, conservative), BELOW 1 for M > 2 (LS-DYNA fails
        first, the converted weld fails later - NON-conservative)."""
        r3, s3, _e = _convert(_weld_deck(n=1.0, m=3.0))
        rows = _type13_ab_rows(s3)
        for row in rows[1:3]:
            self.assertEqual(row[60:80].strip(), "3")
        w3 = [x for x in r3.warnings if "failure exponents N=1 / M=3" in x]
        self.assertEqual(len(w3), 1, r3.warnings)
        for needle in ("0.707x", "LS-DYNA reaches 1 first",
                       "fails LATER than LS-DYNA",
                       "NON-conservative for M > 2"):
            with self.subTest(M=3, needle=needle):
                self.assertIn(needle, w3[0])
        for needle in ("Radioss reaches 1 first", "EARLIER",
                       "(conservative for M < 2)"):
            with self.subTest(M=3, absent=needle):
                self.assertNotIn(needle, w3[0])
        r1, _s1, _e1 = _convert(_weld_deck(n=1.0, m=1.0))
        w1 = [x for x in r1.warnings if "failure exponents N=1 / M=1" in x]
        self.assertEqual(len(w1), 1, r1.warnings)
        for needle in ("1.414x", "Radioss reaches 1 first",
                       "fails EARLIER than LS-DYNA",
                       "(conservative for M < 2)"):
            with self.subTest(M=1, needle=needle):
                self.assertIn(needle, w1[0])
        self.assertNotIn("NON-conservative", w1[0])
        # the ratio is 2^(1 - M/2) at a non-integer M as well
        r15, _s15, _e15 = _convert(_weld_deck(n=1.0, m=1.5))
        self.assertTrue(_has(r15.warnings, "N=1 / M=1.5", "1.189x",
                             "EARLIER"), r15.warnings)

    def test_N_M_2_is_byte_identical_blank_or_stated(self):
        for n, m in ((None, None), (2.0, 2.0)):
            with self.subTest(n=n, m=m):
                r_on, s_on, _e = _convert(_weld_deck(n=n, m=m))
                _r, s_off, _e2 = _convert(_weld_deck(n=n, m=m),
                                          weld_exponents=False)
                self.assertEqual(s_on, s_off)
                self.assertEqual(_type13_ab_rows(s_on), [_ZERO4] * 6)
                self.assertFalse(any("failure exponent" in w
                                     for w in r_on.warnings))

    def test_the_opt_out_leaves_the_cells_blank_and_says_so(self):
        result, starter, _e = _convert(_weld_deck(n=1.0, m=1.0),
                                       weld_exponents=False)
        self.assertEqual(_type13_ab_rows(starter), [_ZERO4] * 6)
        self.assertTrue(_has(result.warnings, "--no-weld-exponents:",
                             "exponent 2 in every term"), result.warnings)

    def test_a_non_positive_exponent_is_not_written(self):
        result, starter, _e = _convert(_weld_deck(n=0.0, m=1.0))
        self.assertEqual(_type13_ab_rows(starter), [_ZERO4] * 6)
        self.assertTrue(_has(result.warnings, "N=0 / M=1",
                             "a failure exponent <= 0 is not written"),
                        result.warnings)

    def test_the_GENERALIZED_WELD_SPOT_spelling_shares_the_rule(self):
        result, starter, _e = _convert(_weld_deck(n=1.0, m=1.0, gen=True))
        self.assertEqual(_type13_ab_rows(starter)[:3], [_ONE_ONE] * 3)
        self.assertTrue(_has(result.warnings,
                             "*CONSTRAINED_GENERALIZED_WELD_SPOT",
                             "failure exponents N=1 / M=1"), result.warnings)

    def test_the_MAT_SPOTWELD_beam_route_is_untouched(self):
        """MAT_100's own criterion is quadratic in each term: every
        alpha/beta row of that property stays blank."""
        deck = (
            "*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            "*NODE\n"
            + "".join(f"{i:>8}{x:>16.4f}{0.0:>16.4f}{0.0:>16.4f}\n"
                      for i, x in ((1, 0.0), (2, 2.0), (3, 0.0)))
            + "*ELEMENT_BEAM\n" + _row(1, 7, 1, 2, 3) + "\n"
              "*PART\n" "weld\n" + _row(7, 7, 7) + "\n"
              "*SECTION_BEAM\n" + _row(7, 9) + "\n" + _row(0.0, 3.0, 3.0)
            + "\n*MAT_SPOTWELD\n" + _row(7, 7.85e-9, 210000.0, 0.3, 300.0)
            + "\n" + _row(0, 0, 0, 1000.0, 500.0, 500.0) + "\n"
              "*END\n")
        _r, starter, _e = _convert(deck)
        self.assertIn("/PROP/TYPE13/", starter)
        rows = [starter.splitlines()[i + 1]
                for i, ln in enumerate(starter.splitlines())
                if re.match(r"^#\s+c\d\s+n\d\s+alpha\d\s+beta\d$", ln)]
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows, [_ZERO4] * 6)


# ═════════════════════════════════════════════════════════════════════════════
# A3 — the spring-token screen is the node's OWN mass (element + *ELEMENT_MASS)
# ═════════════════════════════════════════════════════════════════════════════

#: G4's round-6 coupon: four TYPE4 springs K 100 from a driver (node 10,
#: *ELEMENT_MASS 1e-3); far ends node 20 on a T = 1e-6 shell (own 1.9625e-13),
#: node 30 bare with *ELEMENT_MASS 2e-5, node 40 bare with nothing, node 50 on
#: a T = 1.0 shell (own 1.9625e-7). The share is 5e-5 per far node.
_I14_COUPON = """*KEYWORD
*CONTROL_TERMINATION
    2.0E-3         0       0.0       0.0       0.0
*PART
normal shell
         1         1         1         0         0         0         0         0
*PART
thin shell
         2         2         1         0         0         0         0         0
*PART
springs
       100       100       100         0         0         0         0         0
*SECTION_SHELL
         1         2       1.0         2       1.0         0         0         1
       1.0       1.0       1.0       1.0       0.0       0.0       0.0         0
*SECTION_SHELL
         2         2       1.0         2       1.0         0         0         1
    1.0E-6    1.0E-6    1.0E-6    1.0E-6       0.0       0.0       0.0         0
*SECTION_DISCRETE
       100         0       0.0       0.0       0.0       0.0
       0.0       0.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*MAT_SPRING_ELASTIC
       100     100.0
*NODE
      10             0.0             0.0             0.0
      20            10.0             0.0             0.0
      21            20.0             0.0             0.0
      22            20.0            10.0             0.0
      23            10.0            10.0             0.0
      30            10.0            20.0             0.0
      40            10.0            30.0             0.0
      50            10.0            40.0             0.0
      51            20.0            40.0             0.0
      52            20.0            50.0             0.0
      53            10.0            50.0             0.0
*ELEMENT_SHELL
       1       2      20      21      22      23
       2       1      50      51      52      53
*ELEMENT_DISCRETE
     101     100      10      20       0             1.0       0             0.0
     102     100      10      30       0             1.0       0             0.0
     103     100      10      40       0             1.0       0             0.0
     104     100      10      50       0             1.0       0             0.0
*ELEMENT_MASS
     201      10          1.0E-3       0
     202      30          2.0E-5       0
*INITIAL_VELOCITY_NODE
        10    1000.0       0.0       0.0       0.0       0.0       0.0
*END
"""


def _admas_cards(starter: str):
    """{mass value: [node ids]} over every emitted /ADMAS/0."""
    out = {}
    lines = starter.splitlines()
    grnods = {}
    for i, ln in enumerate(lines):
        if ln.startswith("/GRNOD/NODE/"):
            gid = int(ln.rsplit("/", 1)[1])
            nids = []
            j = i + 2
            while j < len(lines) and not lines[j].startswith(("/", "#")):
                nids += [int(v) for v in lines[j].split()]
                j += 1
            grnods[gid] = nids
    for i, ln in enumerate(lines):
        if ln.startswith("/ADMAS/0/"):
            mass, gid = lines[i + 3].split()
            out.setdefault(round(float(mass), 12), []).extend(
                grnods[int(gid)])
    return {m: sorted(v) for m, v in out.items()}


def _tshell_weld_deck() -> str:
    """Two 8-node THICK-shell plates, node 1 welded to node 11 with failure
    forces: the weld nodes sit on thick shells ONLY."""
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    nodes = ""
    for base, z0 in ((1, 0.0), (11, 1.0)):
        for k, z in enumerate((z0, z0 + 0.5)):
            for i, (x, y) in enumerate(pts):
                nodes += f"{base + 4 * k + i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            "*NODE\n" + nodes
            + "*ELEMENT_TSHELL\n"
            + _row(1, 1, 1, 2, 3, 4, 5, 6, 7, 8) + "\n"
            + _row(2, 2, 11, 12, 13, 14, 15, 16, 17, 18) + "\n"
            + "*PART\nplate1\n" + _row(1, 1, 1) + "\n"
            + "*PART\nplate2\n" + _row(2, 1, 1) + "\n"
            + "*SECTION_TSHELL\n" + _row(1, 1) + "\n"
            + "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            + "*CONSTRAINED_SPOTWELD\n" + _row(1, 11, 1.0e4, 5.0e4) + "\n"
            + "*END\n")


class SpringTokenLumpedScreen(unittest.TestCase):
    """A3 — the round-5 screen was an element-INCIDENCE test: a node with
    only an ``*ELEMENT_MASS`` was refused (gnonspring.k: TOTAL MASS 1.02e-4
    against LS-DYNA's 2.0e-6). The node's OWN mass decides now."""

    def test_the_four_classes_of_the_i14_coupon(self):
        result, starter, _e = _convert(_I14_COUPON)
        cards = _admas_cards(starter)
        # node 10: its 1e-3 minus four half-shares; node 30 keeps its own
        # +2e-05 (degenerate) AND takes the full share off; 20 / 30 / 50 get
        # the negative card; bare node 40 keeps the token
        self.assertEqual(cards[round(-_SHARE, 12)], [20, 30, 50], cards)
        self.assertEqual(cards[round(2.0e-5, 12)], [30], cards)
        self.assertEqual(cards[round(1.0e-3 - 4 * _SHARE, 12)], [10], cards)
        guarded = [w for w in result.warnings
                   if "carry NO element mass of their own" in w]
        self.assertEqual(len(guarded), 1, result.warnings)
        self.assertIn("[40]", guarded[0])
        for needle in ("chkmsin.F:52-59", "chkmsin.F:53", "resol.F:5460",
                       "accele.F:67-80", "ERROR 1870 is NOT it",
                       "*ELEMENT_MASS if their dynamics matter",
                       "EXACTLY zero mass"):
            with self.subTest(needle=needle):
                self.assertIn(needle, guarded[0])

    def test_the_light_clause_names_every_node_below_its_share(self):
        result, _s, _e = _convert(_I14_COUPON)
        neg = [w for w in result.warnings if "was REMOVED again" in w]
        self.assertEqual(len(neg), 1, result.warnings)
        self.assertIn("3 of these node(s) keep LESS mass", neg[0])
        for needle in ("node 20: own 1.9625e-13", "node 30: own 2e-05",
                       "node 50: own 1.9625e-07", "r1def3.F:113",
                       "r1len3.F:175", "IE 1.58e22 at cycle 7",
                       "per-spring stability rule"):
            with self.subTest(needle=needle):
                self.assertIn(needle, neg[0])
        self.assertNotIn("node 40", neg[0])

    def test_the_opt_out_writes_no_negative_card_and_no_light_clause(self):
        result, starter, _e = _convert(_I14_COUPON,
                                       spring_token_mass_compensation=False)
        cards = _admas_cards(starter)
        self.assertFalse([m for m in cards if m < 0], cards)
        self.assertFalse(any("keep LESS mass" in w for w in result.warnings))

    def test_a_material_outside_the_historic_six_is_weighed(self):
        """*MAT_ORTHOTROPIC_ELASTIC lands in state.mat_orthotropic, which the
        lumper's six dictionaries never read."""
        _r, starter, _e = _convert(_weld_deck(plate_mat="orthotropic"))
        self.assertEqual(_admas_cards(starter),
                         {round(-_SHARE, 12): [1, 11]})

    def test_a_node_on_a_thick_shell_only_is_weighed(self):
        _r, starter, _e = _convert(_tshell_weld_deck())
        self.assertEqual(_admas_cards(starter),
                         {round(-_SHARE, 12): [1, 11]})

    def test_a_composite_part_is_weighed_by_its_ply_stack(self):
        _r, starter, _e = _convert(_weld_deck(composite=True))
        self.assertEqual(_admas_cards(starter),
                         {round(-_SHARE, 12): [1, 11]})

    def test_ELEMENT_MASS_PART_on_a_deformable_part_does_not_count(self):
        """The writer puts *ELEMENT_MASS_PART only into /RBODY Mass, so on a
        deformable part it never reaches a node — a node whose only element is
        a zero-density (floored) part stays GUARDED however much part mass the
        deck adds."""
        result, starter, _e = _convert(_weld_deck(rho=0.0, part_mass=1.0e-3))
        self.assertNotIn("spring_token_compensation", starter)
        self.assertTrue(_has(result.warnings,
                             "carry NO element mass of their own", "[1, 11]"),
                        result.warnings)

    def test_an_element_free_node_with_an_ELEMENT_MASS_is_compensated(self):
        """gnonspring.k's shape: both spring ends carry ONLY *ELEMENT_MASS
        1e-6 (degenerate, 50x below the share)."""
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n*NODE\n"
                + f"{1:>8}{0.0:>16.4f}{0.0:>16.4f}{0.0:>16.4f}\n"
                + f"{2:>8}{10.0:>16.4f}{0.0:>16.4f}{0.0:>16.4f}\n"
                + "*ELEMENT_DISCRETE\n"
                + f"{1:>8}{1:>8}{1:>8}{2:>8}{0:>8}{1.0:>16.8G}{0:>8}"
                  f"{0.0:>16.8G}\n"
                + "*PART\nspring\n" + _row(1, 1, 1) + "\n"
                  "*SECTION_DISCRETE\n" + _row(1, 0) + "\n"
                + "*MAT_SPRING_ELASTIC\n" + _row(1, 100.0) + "\n"
                  "*ELEMENT_MASS\n"
                + f"{1:>8}{1:>8}{1.0e-6:>16.8G}\n"
                + f"{2:>8}{2:>8}{1.0e-6:>16.8G}\n"
                + "*END\n")
        result, starter, _e = _convert(deck)
        self.assertEqual(_admas_cards(starter),
                         {round(1.0e-6, 12): [1, 2],
                          round(-_SHARE, 12): [1, 2]})
        deg = [w for w in result.warnings if "LESS /ADMAS" in w]
        self.assertEqual(len(deg), 1, result.warnings)
        self.assertIn("The full share was taken off 2 of them", deg[0])
        self.assertIn("TOTAL MASS 1.02e-4 -> 2.0e-6", deg[0])
        self.assertNotIn("NONE of them", deg[0])

    def test_the_element_mass_helper_by_hand(self):
        """lumping.element_mass_by_node on the coupon, against the hand
        values: a 10 x 10 shell of T 1e-6 / 1.0 at rho 7.85e-9, a quarter per
        corner."""
        from k2rad.lumping import element_mass_by_node
        from k2rad.writer.sph import _mat_density
        state = _dispatch(_I14_COUPON)
        got = element_mass_by_node(state, {20, 30, 40, 50},
                                   lambda mid: _mat_density(state, mid))
        self.assertAlmostEqual(got[20], 100.0 * 1.0e-6 * 7.85e-9 / 4,
                               delta=1e-25)
        self.assertAlmostEqual(got[50], 100.0 * 1.0 * 7.85e-9 / 4,
                               delta=1e-19)
        self.assertNotIn(30, got)     # *ELEMENT_MASS is NOT element mass
        self.assertNotIn(40, got)

    def test_the_lumper_weighs_every_material_container(self):
        """lumping._material_rho was six dictionaries; an orthotropic plate
        weighed ZERO in the modal mass matrix."""
        from k2rad.lumping import _material_rho, nodal_masses_from_state
        state = _dispatch(_weld_deck(plate_mat="orthotropic"))
        self.assertIn(1, state.mat_orthotropic)
        self.assertEqual(_material_rho(state)[1], 7.85e-9)
        mass, _inertia = nodal_masses_from_state(state)
        self.assertAlmostEqual(mass[1], 100.0 * 1.0 * 7.85e-9 / 4,
                               delta=1e-19)
        # thermal dicts are a separate (TMID) namespace and never weighed
        import inspect
        from k2rad import lumping
        src = inspect.getsource(lumping._material_rho)
        self.assertIn('name.startswith("mat_thermal")', src)


# ═════════════════════════════════════════════════════════════════════════════
# A4 — *CONSTRAINED_TIED_NODES_FAILURE: a named refusal, 0 bytes
# ═════════════════════════════════════════════════════════════════════════════

def _tied_failure_deck(cards=("101 0.085", "102 0.5"), extra="") -> str:
    """Two shells sharing an edge by COINCIDENT nodes (2/5 and 3/6), the two
    coincident pairs as node sets 101 and 102, and one
    *CONSTRAINED_TIED_NODES_FAILURE card per entry of *cards* ("NSID EPPF
    [ETYPE PID]")."""
    pts = {1: (0, 0), 2: (1, 0), 3: (1, 1), 4: (0, 1),
           5: (1, 0), 6: (1, 1), 7: (2, 0), 8: (2, 1)}
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            "*NODE\n"
            + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n"
                      for i, (x, y) in pts.items())
            + "*ELEMENT_SHELL\n" + _row(1, 1, 1, 2, 3, 4) + "\n"
            + _row(2, 1, 5, 7, 8, 6) + "\n"
            + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            + "*SET_NODE_LIST\n" + _row(101) + "\n" + _row(2, 5) + "\n"
            + "*SET_NODE_LIST\n" + _row(102) + "\n" + _row(3, 6) + "\n")
    for card in cards:
        deck += ("*CONSTRAINED_TIED_NODES_FAILURE\n"
                 + _row(*card.split()) + "\n")
    return deck + extra + "*END\n"


class TiedNodesFailureRefusal(unittest.TestCase):
    """A4 — LS-DYNA releases a tied group on the surrounding elements'
    plastic strain (Vol I R17 p.10-226/227); no Radioss tie reads an
    element's strain, so the card is refused BY NAME: one warning per deck,
    the keyword still listed as skipped, not one byte moved."""

    def _warnings(self, result):
        return [w for w in result.warnings
                if w.startswith("*CONSTRAINED_TIED_NODES_FAILURE:")]

    def test_not_one_byte_moves_against_the_unregistered_keyword(self):
        """The handler vs no handler at all (the dispatch fall-through the
        keyword took before this round): identical starter and engine."""
        from k2rad import handlers
        _r, s_on, e_on = _convert(_tied_failure_deck())
        saved = handlers.HANDLERS.pop("CONSTRAINED_TIED_NODES_FAILURE")
        try:
            r_off, s_off, e_off = _convert(_tied_failure_deck())
        finally:
            handlers.HANDLERS["CONSTRAINED_TIED_NODES_FAILURE"] = saved
        self.assertEqual(s_on, s_off)
        self.assertEqual(e_on, e_off)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_TIED_NODES_FAILURE", s_on)
        for card in ("/RBODY/", "/MERGE", "/INTER/TYPE2/"):
            self.assertNotIn(card, s_on)
        self.assertFalse(self._warnings(r_off))

    def test_the_registries(self):
        result, _s, _e = _convert(_tied_failure_deck())
        self.assertIn("CONSTRAINED_TIED_NODES_FAILURE",
                      result.skipped_keywords)
        self.assertNotIn("CONSTRAINED_TIED_NODES_FAILURE",
                         [k for k, _w in result.recognized_not_emitted])

    def test_ONE_warning_with_the_rule_and_the_measured_arms(self):
        result, _s, _e = _convert(_tied_failure_deck())
        w = self._warnings(result)
        self.assertEqual(len(w), 1, result.warnings)
        for needle in ("2 card(s)", "4 nodes", "EPPF 0.085 x1", "0.5 x1",
                       "ETYPE 0", "p.10-226/227", "rgbodv.F:248-267",
                       "ruptint2.F:138-151", "hm_read_sensors.F:175-250",
                       "-71.8 %", "+333 %", "-16.9 %", "NOT converted"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w[0])

    def test_fifty_cards_are_still_ONE_warning(self):
        cards = [f"{101 + (k % 2)} {0.1 + k * 0.001:.3f}" for k in range(50)]
        result, _s, _e = _convert(_tied_failure_deck(cards=cards))
        w = self._warnings(result)
        self.assertEqual(len(w), 1)
        self.assertIn("50 card(s)", w[0])

    def test_the_PID_form_is_named(self):
        result, _s, _e = _convert(_tied_failure_deck(
            cards=("101 0.085", "0 0.1 0 7")))
        w = self._warnings(result)
        self.assertEqual(len(w), 1)
        self.assertIn("1 card(s) use the PID form", w[0])
        self.assertIn("part(s) [7]", w[0])

    def test_an_undefined_node_set_is_counted_not_raised(self):
        result, _s, _e = _convert(_tied_failure_deck(
            cards=("101 0.085", "999 0.5")))
        w = self._warnings(result)
        self.assertEqual(len(w), 1)
        self.assertIn("2 card(s) tying 2 nodes", w[0])
        self.assertIn("(1 card(s) name a node set the deck does not "
                      "define.)", w[0])

    def test_a_refusal_carries_no_offset_spec(self):
        """The #130 rule: a keyword that resolves nothing gets no
        *INCLUDE_TRANSFORM offset spec."""
        from k2rad.assembly import _OFFSET_SPECS
        self.assertNotIn("CONSTRAINED_TIED_NODES_FAILURE", _OFFSET_SPECS)

    def test_the_record_is_kept_per_card(self):
        st = _dispatch(_tied_failure_deck(cards=("101 0.085 0 0",
                                                 "102 0.5 1 3")))
        self.assertEqual(st.tied_nodes_failures,
                         [(101, 0.085, 0, 0), (102, 0.5, 1, 3)])


# ═════════════════════════════════════════════════════════════════════════════
# A5 — *CONSTRAINED_LINEAR_LOCAL / _GLOBAL -> /MPC
# ═════════════════════════════════════════════════════════════════════════════

_MPC_ROW_40 = "        40         3         0                   1"
_MPC_ROW_42 = "        42         3         0                  -1"


def _linear_deck(terms=("40 3 0 1.0", "42 3 0 -1.0"),
                 kw="*CONSTRAINED_LINEAR_LOCAL", extra="", rigid=False,
                 tc42=0, cards=None, free_node=False) -> str:
    """plates.lce's shape: a two-shell strip, nodes 40/41/42 at (15,20) /
    (20,20) / (25,20), the constraint tying DZ(40) to DZ(42)."""
    pts = [(40, 15.0, 20.0, 0), (41, 20.0, 20.0, 0), (42, 25.0, 20.0, tc42),
           (50, 15.0, 25.0, 0), (51, 20.0, 25.0, 0), (52, 25.0, 25.0, 0)]
    if free_node:
        pts.append((60, 40.0, 20.0, 0))
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n"
            + "".join(f"{n:>8}{x:>16.4f}{y:>16.4f}{0.0:>16.4f}{tc:>8}{0:>8}\n"
                      for n, x, y, tc in pts)
            + "*ELEMENT_SHELL\n" + _row(1, 1, 40, 41, 51, 50) + "\n"
            + _row(2, 1, 41, 42, 52, 51) + "\n"
            + "*PART\nplate\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n")
    if rigid:
        deck += "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
    else:
        deck += "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
    for card in (cards if cards is not None else [(kw, terms)]):
        ckw, cterms = card
        deck += ckw + "\n" + _row(1) + "\n"
        for t in cterms:
            deck += _row(*t.split()) + "\n"
    return deck + extra + "*END\n"


def _mpc_blocks(starter: str):
    """[(header, title, [rows])] for every /MPC block."""
    lines = starter.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if ln.startswith("/MPC/"):
            rows = []
            for r in lines[i + 3:]:
                if r.startswith("#") or r.startswith("/"):
                    break
                rows.append(r)
            out.append((ln, lines[i + 1], rows))
    return out


class ConstrainedLinearMpc(unittest.TestCase):
    """A5 — one /MPC per *CONSTRAINED_LINEAR_* card, refused BY NAME where
    it would fight another kinematic condition or divide by nothing."""

    def _refused_is_the_opt_out(self, deck, *needles):
        r_on, s_on, _e = _convert(deck)
        _r, s_off, _e2 = _convert(deck, constrained_linear=False)
        self.assertEqual(s_on, s_off)
        self.assertNotIn("/MPC/", s_on)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_LINEAR", s_on)
        self.assertTrue(_has(r_on.warnings, "NOT converted to /MPC",
                             *needles), r_on.warnings)
        return r_on

    def test_the_plates_lce_card(self):
        result, starter, _e = _convert(_linear_deck())
        blocks = _mpc_blocks(starter)
        self.assertEqual(len(blocks), 1, starter)
        head, title, rows = blocks[0]
        self.assertEqual(title, "CONSTRAINED_LINEAR_LOCAL_1")
        self.assertEqual(rows, [_MPC_ROW_40, _MPC_ROW_42])
        for row, alpha in zip(rows, ("1", "-1")):
            self.assertEqual(len(row), 50)
            self.assertEqual(row[30:50].strip(), alpha)   # alpha cols 31-50
        self.assertNotIn("#-- SKIPPED: *CONSTRAINED_LINEAR_LOCAL", starter)
        self.assertNotIn("CONSTRAINED_LINEAR_LOCAL", result.skipped_keywords)
        self.assertTrue(_has(result.warnings, "-> /MPC",
                             "LS-DYNA assumes the constant C0 is zero"))

    def test_the_GLOBAL_and_legacy_spellings(self):
        for kw in ("*CONSTRAINED_LINEAR_GLOBAL", "*CONSTRAINED_LINEAR"):
            with self.subTest(kw=kw):
                _r, starter, _e = _convert(_linear_deck(
                    kw=kw, terms=("40 3 1.0", "42 3 -1.0")))
                self.assertEqual(_mpc_blocks(starter)[0][2],
                                 [_MPC_ROW_40, _MPC_ROW_42])

    def test_a_local_CID_is_the_row_skew(self):
        csys = ("*DEFINE_COORDINATE_SYSTEM\n"
                + _row(5, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                + _row(0.0, 1.0, 0.0) + "\n")
        _r, starter, _e = _convert(_linear_deck(
            terms=("40 3 5 1.0", "42 3 5 -1.0"), extra=csys))
        rows = _mpc_blocks(starter)[0][2]
        self.assertEqual([r[20:30].strip() for r in rows], ["5", "5"])
        self.assertTrue(re.search(r"^/SKEW/\w+/5$", starter, re.M), starter)

    def test_an_undefined_CID_is_refused(self):
        self._refused_is_the_opt_out(
            _linear_deck(terms=("40 3 9 1.0", "42 3 9 -1.0")),
            "CID 9", "ERROR 137")

    def test_a_BCS_on_the_DOF_is_refused(self):
        spc = ("*BOUNDARY_SPC_NODE\n" + _row(40, 0, 0, 0, 1, 0, 0, 0) + "\n")
        self._refused_is_the_opt_out(_linear_deck(extra=spc),
                                     "node 40 DOF 3", "/BCS", "WARNING 312")

    def test_a_BCS_on_ANOTHER_dof_is_not_a_conflict(self):
        spc = ("*BOUNDARY_SPC_NODE\n" + _row(40, 0, 1, 0, 0, 0, 0, 0) + "\n")
        _r, starter, _e = _convert(_linear_deck(extra=spc))
        self.assertEqual(len(_mpc_blocks(starter)), 1)

    def test_a_NODE_TC_on_the_DOF_is_refused(self):
        self._refused_is_the_opt_out(_linear_deck(tc42=3),
                                     "node 42 DOF 3", "*NODE TC/RC")

    def test_an_imposed_motion_on_the_DOF_is_refused(self):
        pm = ("*BOUNDARY_PRESCRIBED_MOTION_NODE\n"
              + _row(40, 3, 2, 7, 1.0) + "\n"
              "*DEFINE_CURVE\n" + _row(7) + "\n"
              + f"{0.0:>20.10G}{0.0:>20.10G}\n{1.0:>20.10G}{1.0:>20.10G}\n")
        self._refused_is_the_opt_out(_linear_deck(extra=pm),
                                     "node 40 DOF 3", "imposed motion")

    def test_a_rigid_body_node_is_refused(self):
        self._refused_is_the_opt_out(_linear_deck(rigid=True),
                                     "rigid-body node")

    def test_an_element_free_node_is_refused(self):
        self._refused_is_the_opt_out(
            _linear_deck(terms=("60 3 0 1.0", "42 3 0 -1.0"),
                         free_node=True),
            "node 60 carries no element")

    def test_a_zero_COEF_is_refused(self):
        self._refused_is_the_opt_out(
            _linear_deck(terms=("40 3 0 1.0", "42 3 0 0.0")),
            "COEF 0", "hm_read_mpc.F:124")

    def test_DOF_7_is_refused(self):
        self._refused_is_the_opt_out(
            _linear_deck(kw="*CONSTRAINED_LINEAR_GLOBAL",
                         terms=("40 7 1.0", "42 7 -1.0")),
            "piezoelectric")

    def test_a_rotation_on_a_solid_only_node_is_refused(self):
        nodes = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                          for i, (x, y, z) in enumerate(nodes, start=1))
                + "*ELEMENT_SOLID\n"
                + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 4, 3, 5, 6, 8, 7))
                + "\n*PART\nbrick\n" + _row(1, 1, 1) + "\n"
                "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                "*CONSTRAINED_LINEAR_GLOBAL\n" + _row(1) + "\n"
                + _row(1, 5, 1.0) + "\n" + _row(2, 5, -1.0) + "\n*END\n")
        self._refused_is_the_opt_out(deck, "rotary inertia")

    def test_a_node_DOF_pair_in_two_cards_refuses_the_second(self):
        cards = [("*CONSTRAINED_LINEAR_LOCAL", ("40 3 0 1.0", "42 3 0 -1.0")),
                 ("*CONSTRAINED_LINEAR_LOCAL", ("40 3 0 1.0", "41 3 0 -1.0"))]
        result, starter, _e = _convert(_linear_deck(cards=cards))
        self.assertEqual(len(_mpc_blocks(starter)), 1)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_LINEAR_LOCAL", starter)
        self.assertEqual(result.skipped_keywords.count(
            "CONSTRAINED_LINEAR_LOCAL"), 1)
        self.assertTrue(_has(result.warnings, "already in an earlier /MPC"))

    def test_the_opt_out(self):
        result, starter, _e = _convert(_linear_deck(),
                                       constrained_linear=False)
        self.assertNotIn("/MPC/", starter)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_LINEAR_LOCAL", starter)
        opt = [w for w in result.warnings if "--no-constrained-linear:" in w]
        self.assertEqual(len(opt), 1)

    def test_the_include_transform_offset_specs(self):
        from k2rad.assembly import _OFFSET_SPECS
        self.assertEqual(_OFFSET_SPECS["CONSTRAINED_LINEAR_LOCAL"],
                         {"cards": {0: [(0, "r")]},
                          "data": (1, [(0, "n"), (2, "d")])})
        for kw in ("CONSTRAINED_LINEAR_GLOBAL", "CONSTRAINED_LINEAR"):
            self.assertEqual(_OFFSET_SPECS[kw],
                             {"cards": {0: [(0, "r")]},
                              "data": (1, [(0, "n")])})

    def test_no_keyword_no_section(self):
        from k2rad.writer import loads
        st = ConversionState()
        self.assertEqual(loads._make_constrained_linear_mpcs(st, {}, set()),
                         [])
        self.assertEqual(st.warnings, [])


# ═════════════════════════════════════════════════════════════════════════════
# A6 — the zero-coupling *MAT_ANISOTROPIC_ELASTIC is orthotropic: convert it
# ═════════════════════════════════════════════════════════════════════════════

#: The twelve coupling cells of *MAT_ANISOTROPIC_ELASTIC as (name, card,
#: field), written out from the manual's card layout (Vol II R17: card 2 =
#: C14 C24 C34 C44 C15 C25 C35 C45, card 3 = C55 C16 C26 C36 C46 C56 C66
#: AOPT) - NOT imported from the handler, so a wrong table there is caught.
_COUPLING_POSITIONS = (
    ("C14", 1, 0), ("C24", 1, 1), ("C34", 1, 2), ("C15", 1, 4),
    ("C25", 1, 5), ("C35", 1, 6), ("C45", 1, 7),
    ("C16", 2, 1), ("C26", 2, 2), ("C36", 2, 3), ("C46", 2, 4), ("C56", 2, 5),
)


def _aniso_deck(c=(5940.0, 760.0, 5940.0, 980.0, 980.0, 2270.0),
                c44=2590.0, c55=1180.0, c66=1180.0, c14=0.0,
                coupling=None, elform=1, aopt=0.0, a=(0.0, 0.0, 0.0),
                d=(0.0, 0.0, 0.0), tets=False) -> str:
    """One brick on *MAT_ANISOTROPIC_ELASTIC 3 — 11.1.sbrake's pad by
    default (C11 = C22 5940, C12 760, C13 = C23 980, C33 2270, C44 2590,
    C55 = C66 1180, every coupling cell 0, AOPT 0, ELFORM 1).

    ``coupling`` is ``{(card, field): value}`` over ``_COUPLING_POSITIONS``;
    ``aopt`` 2 with ``a``/``d`` gives the global-vector (skew) frame;
    ``tets`` meshes the part as one four-node tetrahedron instead."""
    nodes = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    cards = [[0.0, 0.0, 0.0, c44, 0.0, 0.0, 0.0, 0.0],
             [c55, 0.0, 0.0, 0.0, 0.0, 0.0, c66, aopt]]
    cards[0][0] = c14
    for (card, field), val in (coupling or {}).items():
        cards[card - 1][field] = val
    elem = ((1, 5, 1, 2, 4, 5, 5, 5, 5, 5) if tets
            else (1, 5, 1, 2, 4, 3, 5, 6, 8, 7))
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n"
            + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                      for i, (x, y, z) in enumerate(nodes, start=1))
            + "*ELEMENT_SOLID\n"
            + "".join(f"{v:>8}" for v in elem)
            + "\n*PART\npad\n" + _row(5, 1, 3) + "\n"
            "*SECTION_SOLID\n" + _row(1, elform) + "\n"
            "*MAT_ANISOTROPIC_ELASTIC_TITLE\npad\n"
            + _row(3, 2.51e-9, *c) + "\n"
            + _row(*cards[0]) + "\n"
            + _row(*cards[1]) + "\n"
            + _row(0.0, 0.0, 0.0, *a, 1, 0) + "\n"
            + _row(0.0, 0.0, 0.0, *d, 0.0, 0.0) + "\n"
            "*END\n")


def _type6_cells(starter: str):
    """``[(prop id, Isolid, Ip, skew_ID)]`` of every /PROP/TYPE6 block."""
    lines = starter.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith("/PROP/TYPE6/"):
            continue
        rows = []
        for nxt in lines[i + 2:]:
            if nxt.startswith("/"):
                break
            if not nxt.startswith("#"):
                rows.append(nxt)
        out.append((int(ln.split("/")[3]), int(rows[0][0:10]),
                    int(rows[2][70:80]), int(rows[2][60:70])))
    return out


def _law93_cells(starter: str, mid: int):
    """{E11, E22, E33, G12, NU12, G13, G23, NU13, NU23} of /MAT/LAW93/<mid>."""
    block = _mat_block(starter, f"/MAT/LAW93/{mid}")
    rows = [ln for ln in block if not ln.startswith("#")]
    # rows: header, title, RHO_I, the E/G/NU row, the G/NU row, ...
    r1 = [float(rows[3][i:i + 20]) for i in range(0, 100, 20)]
    r2 = [float(rows[4][i:i + 20]) for i in range(0, 80, 20)]
    names = ("E11", "E22", "E33", "G12", "NU12", "G13", "G23", "NU13", "NU23")
    return dict(zip(names, r1 + r2))


class AnisotropicZeroCouplingRoute(unittest.TestCase):
    """A6 — a *MAT_ANISOTROPIC_ELASTIC with every coupling cell 0 and a
    positive-definite matrix IS orthotropic; the 3x3 normal block inverts to
    EA/EB/EC and LS-DYNA's MINOR ratios (Vol II R17 p.2-164 Remark 1), and
    GAB/GBC/GCA = C44/C55/C66. Hand values computed with numpy outside the
    package (k2rad itself has no import-time numpy)."""

    def test_sbrakes_card_restates_to_the_hand_values(self):
        st = _dispatch(_aniso_deck())
        m = st.mat_orthotropic[3]
        for name, got, want in (
                ("EA", m.ea, 5496.34093), ("EB", m.eb, 5496.34093),
                ("EC", m.ec, 1983.31343), ("PRBA", m.prba, 0.0610696776),
                ("PRCA", m.prca, 0.146268657), ("PRCB", m.prcb, 0.146268657),
                ("GAB", m.gab, 2590.0), ("GBC", m.gbc, 1180.0),
                ("GCA", m.gca, 1180.0), ("RHO", m.rho, 2.51e-9)):
            with self.subTest(cell=name):
                self.assertAlmostEqual(got / want, 1.0, delta=1e-8)
        self.assertEqual(m.macf, 1)
        self.assertNotIn("MAT_ANISOTROPIC_ELASTIC",
                         [k for k, _w in st.recognized_not_emitted])

    def test_the_emitted_LAW93_carries_the_major_ratios(self):
        """_emit_mat_law93 rescales the MINOR ratios itself (NU13 = PRCA *
        EA / EC): the card must read 0.405353, never the double-rescaled
        1.1234 the naive -S13*EA would give."""
        result, starter, _e = _convert(_aniso_deck())
        cells = _law93_cells(starter, 3)
        for name, want in (("E11", 5496.34093), ("E22", 5496.34093),
                           ("E33", 1983.31343), ("G12", 2590.0),
                           ("NU12", 0.0610696776), ("G13", 1180.0),
                           ("G23", 1180.0), ("NU13", 0.405353179),
                           ("NU23", 0.405353179)):
            with self.subTest(cell=name):
                self.assertAlmostEqual(cells[name] / want, 1.0, delta=1e-8)
        w = [x for x in result.warnings
             if x.startswith("*MAT_ANISOTROPIC_ELASTIC 3:")]
        self.assertEqual(len(w), 1, result.warnings)
        for needle in ("restated EXACTLY", "EA 5496.34", "EC 1983.31",
                       "PRBA 0.0610697", "PRCA 0.146269", "GAB = C44 2590",
                       "p.2-164 Remark 1", "5940 / 3.4706e+07"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w[0])

    def test_the_closed_loop_rebuilds_the_deck_matrix(self):
        """C from the EMITTED LAW93 constants (the major ratios, NU21 =
        NU12*E22/E11 etc.) must give back the deck's normal block."""
        for c in ((5940.0, 760.0, 5940.0, 980.0, 980.0, 2270.0),
                  (150000.0, 3000.0, 10000.0, 3000.0, 3000.0, 10000.0)):
            with self.subTest(c=c):
                _r, starter, _e = _convert(_aniso_deck(c=c))
                k = _law93_cells(starter, 3)
                e1, e2, e3 = k["E11"], k["E22"], k["E33"]
                n12, n13, n23 = k["NU12"], k["NU13"], k["NU23"]
                s = [[1 / e1, -n12 / e1, -n13 / e1],
                     [-n12 / e1, 1 / e2, -n23 / e2],
                     [-n13 / e1, -n23 / e2, 1 / e3]]
                a, d, e_ = s[0][0], s[0][1], s[0][2]
                b, f, cc = s[1][1], s[1][2], s[2][2]
                det = (a * (b * cc - f * f) - d * (d * cc - f * e_)
                       + e_ * (d * f - b * e_))
                c11 = (b * cc - f * f) / det
                c22 = (a * cc - e_ * e_) / det
                c33 = (a * b - d * d) / det
                c12 = -(d * cc - e_ * f) / det
                c13 = (d * f - e_ * b) / det
                c23 = -(a * f - d * e_) / det
                for got, want in ((c11, c[0]), (c12, c[1]), (c22, c[2]),
                                  (c13, c[3]), (c23, c[4]), (c33, c[5])):
                    self.assertAlmostEqual(got / want, 1.0, delta=1e-6)

    def test_a_coupling_cell_keeps_the_refusal(self):
        result, starter, _e = _convert(_aniso_deck(c14=100.0))
        self.assertNotIn("/MAT/LAW93", starter)
        self.assertTrue(_has(result.warnings, "1 coupling cell(s) are "
                             "non-zero (C14)", "NOT emitted"), result.warnings)
        self.assertIn("MAT_ANISOTROPIC_ELASTIC",
                      [k for k, _w in result.recognized_not_emitted])

    def test_every_coupling_position_refuses_at_either_sign(self):
        """Finalization round (the code-sweep mutation that survived: the
        screen's ``!= 0`` turned into ``> 0`` stayed green because only
        C14 = +100 was ever probed). Each of the twelve cells, at +100 AND
        -100, keeps the refusal and names that cell."""
        for name, card, field in _COUPLING_POSITIONS:
            for val in (100.0, -100.0):
                with self.subTest(cell=name, value=val):
                    st = _dispatch(_aniso_deck(coupling={(card, field): val}))
                    self.assertNotIn(3, st.mat_orthotropic)
                    self.assertTrue(_has(st.warnings, "1 coupling cell(s) "
                                         f"are non-zero ({name})"),
                                    st.warnings)

    def test_a_negative_coupling_cell_is_refused_end_to_end(self):
        result, starter, _e = _convert(_aniso_deck(c14=-100.0))
        self.assertNotIn("/MAT/LAW93", starter)
        self.assertEqual(_type6_cells(starter), [])
        self.assertTrue(_has(result.warnings, "non-zero (C14)"),
                        result.warnings)


class OrthotropicConnectivityFrameIsolid(unittest.TestCase):
    """Finalization round, the A6 orientation blocker: an orthotropic brick
    whose /PROP/TYPE6 frame comes from the element connectivity (Ip 20 =
    AOPT 0, Ip 23 = AOPT 3) was MEASURED misoriented on Isolid 17 and right
    on Isolid 14 / 24 (a 1 mm cube of sbrake's MID 3, 8 of 8 Ip 20 arms
    explicit + implicit, Ip 23 on 4 of 6 faces); the skew mode (AOPT 2) was
    right on 17. So Ip 20 / 23 on an ELFORM-derived 17 is written as 14."""

    def test_the_sbrake_card_on_AOPT_0_is_written_on_Isolid_14(self):
        for elform in (1, 2, 0):
            with self.subTest(elform=elform):
                result, starter, _e = _convert(_aniso_deck(elform=elform))
                cells = _type6_cells(starter)
                self.assertEqual(len(cells), 1, starter[:2000])
                _pid, isolid, ip, skew = cells[0]
                self.assertEqual((isolid, ip, skew), (14, 20, 0))
                w = [x for x in result.warnings if "Isolid 14 (HA8" in x]
                self.assertEqual(len(w), 1, result.warnings)
                for needle in ("(Ip=20, LS-DYNA AOPT 0)", "8 of 8",
                               f"ELFORM {elform} is written as Isolid 14",
                               "skew mode (AOPT 2"):
                    self.assertIn(needle, w[0])

    def test_the_skew_frame_stays_on_Isolid_17(self):
        result, starter, _e = _convert(_aniso_deck(
            elform=2, aopt=2.0, a=(1.0, 0.0, 0.0), d=(0.0, 1.0, 0.0)))
        cells = _type6_cells(starter)
        self.assertEqual(len(cells), 1)
        _pid, isolid, ip, skew = cells[0]
        self.assertEqual((isolid, ip), (17, 0))
        self.assertGreater(skew, 0)
        self.assertFalse(_has(result.warnings, "Isolid 14 (HA8"))

    def test_AOPT_3_is_a_connectivity_frame_too(self):
        deck = _aniso_deck(elform=2).replace(
            "*MAT_ANISOTROPIC_ELASTIC_TITLE\npad\n"
            + _row(3, 2.51e-9, 5940.0, 760.0, 5940.0, 980.0, 980.0, 2270.0)
            + "\n" + _row(0.0, 0.0, 0.0, 2590.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(1180.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1180.0, 0.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1, 0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n",
            "*MAT_ORTHOTROPIC_ELASTIC_TITLE\npad\n"
            + _row(3, 2.51e-9, 5496.34093, 5496.34093, 1983.31343,
                   0.06106968, 0.14626866, 0.14626866) + "\n"
            + _row(2590.0, 1180.0, 1180.0, 3.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        self.assertIn("*MAT_ORTHOTROPIC_ELASTIC_TITLE", deck)
        result, starter, _e = _convert(deck)
        cells = _type6_cells(starter)
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0][1:3], (14, 23))
        self.assertTrue(_has(result.warnings, "(Ip=23, LS-DYNA AOPT 3)",
                             "ELFORM 2 is written as Isolid 14"),
                        result.warnings)

    def test_an_assumed_strain_24_is_left_alone(self):
        result, starter, _e = _convert(_aniso_deck(elform=-2),
                                       assumed_strain_isolid="24")
        self.assertEqual(_type6_cells(starter)[0][1:3], (24, 20))
        self.assertFalse(_has(result.warnings, "Isolid 14 (HA8"))

    def test_a_part_with_no_eight_node_element_is_left_alone(self):
        result, starter, _e = _convert(_aniso_deck(elform=2, tets=True))
        cells = _type6_cells(starter)
        self.assertEqual(len(cells), 1)
        self.assertNotEqual(cells[0][1], 14, starter[:3000])
        self.assertFalse(_has(result.warnings, "Isolid 14 (HA8"))

    def test_a_matrix_that_is_not_positive_definite_is_refused(self):
        result, starter, _e = _convert(_aniso_deck(
            c=(5940.0, 200000.0, 5940.0, 980.0, 980.0, 2270.0)))
        self.assertNotIn("/MAT/LAW93", starter)
        self.assertTrue(_has(result.warnings, "not positive definite",
                             "C11*C22 - C12^2"), result.warnings)

    def test_a_non_positive_shear_modulus_is_refused(self):
        result, starter, _e = _convert(_aniso_deck(c44=0.0))
        self.assertNotIn("/MAT/LAW93", starter)
        self.assertTrue(_has(result.warnings, "not positive definite",
                             "C44 = 0 <= 0"), result.warnings)

    def test_the_ORTHO_dialect_is_untouched(self):
        deck = _aniso_deck().replace(
            "*MAT_ANISOTROPIC_ELASTIC_TITLE\npad\n"
            + _row(3, 2.51e-9, 5940.0, 760.0, 5940.0, 980.0, 980.0, 2270.0)
            + "\n" + _row(0.0, 0.0, 0.0, 2590.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(1180.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1180.0, 0.0) + "\n",
            "*MAT_ORTHOTROPIC_ELASTIC_TITLE\npad\n"
            + _row(3, 2.51e-9, 5496.34093, 5496.34093, 1983.31343,
                   0.06106968, 0.14626866, 0.14626866) + "\n"
            + _row(2590.0, 1180.0, 1180.0, 0.0) + "\n")
        self.assertIn("*MAT_ORTHOTROPIC_ELASTIC_TITLE", deck)
        _r, s_ortho, _e = _convert(deck)
        _r2, s_aniso, _e2 = _convert(_aniso_deck())
        a, b = _law93_cells(s_ortho, 3), _law93_cells(s_aniso, 3)
        for name in a:
            with self.subTest(cell=name):
                # the ORTHO card states 10-column (8-digit) cells
                self.assertAlmostEqual(a[name] / b[name], 1.0, delta=1e-7)


# ═════════════════════════════════════════════════════════════════════════════
# A7 — --mass-weighted-inivel writes J = -SUM(IN) on the re-pointed /RBODY
# ═════════════════════════════════════════════════════════════════════════════

def _j_plate_deck(covered=(3, 4), second_rigid=False, icomp=False,
                  thickness=False) -> str:
    """G4's rigid 20 x 20 x 2 plate (rho 7.85e-9, m 6.28e-6) plus one elastic
    shell; an *INITIAL_VELOCITY_NODE of vx 1000 on the plate nodes named in
    *covered*. With --mass-weighted-inivel the plate's synthesized main node
    (15) gets /INIVEL/TRA + /INIVEL/ROT (omega -25 about z when 2 of 4 nodes
    move). Hand: SUM(IN) = 4 x (m/4)(A + t^2)/12 = 6.28e-6 x 404 / 12 =
    2.114266667e-4."""
    sec1 = (_row(1, 2, 1.0, 2, 1.0, 0, 1 if icomp else 0, 1) + "\n"
            + _row(2.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0) + "\n"
            + (_row(0.0, 0.0) + "\n" if icomp else ""))
    deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-4) + "\n"
            "*PART\nrigid plate\n" + _row(1, 1, 1) + "\n"
            "*SECTION_SHELL\n" + sec1
            + "*PART\nclock shell\n" + _row(2, 2, 2) + "\n"
            "*SECTION_SHELL\n" + _row(2, 2, 1.0, 2, 1.0, 0, 0, 1) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0) + "\n"
            "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
            "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, 0.0)
            + "\n" + _row(0.0, 0, 0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            "*NODE\n"
            + "".join(f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n"
                      for n, x, y in ((1, -10, -10), (2, 10, -10), (3, 10, 10),
                                      (4, -10, 10), (11, 100, 0), (12, 101, 0),
                                      (13, 101, 1), (14, 100, 1))))
    if thickness:
        deck += ("*ELEMENT_SHELL_THICKNESS\n"
                 + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)) + "\n"
                 + "".join(f"{v:>16}" for v in (2.0, 2.0, 2.0, 2.0)) + "\n")
    else:
        deck += ("*ELEMENT_SHELL\n"
                 + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4)) + "\n")
    deck += "*ELEMENT_SHELL\n" + "".join(f"{v:>8}" for v in
                                         (2, 2, 11, 12, 13, 14)) + "\n"
    if second_rigid:
        deck += ("*PART\nsecond rigid\n" + _row(3, 1, 1) + "\n"
                 "*NODE\n"
                 + "".join(f"{n:>8}{x:>16.1f}{y:>16.1f}{0.0:>16.1f}\n"
                           for n, x, y in ((21, 50, 0), (22, 60, 0),
                                           (23, 60, 10), (24, 50, 10)))
                 + "*ELEMENT_SHELL\n"
                 + "".join(f"{v:>8}" for v in (3, 3, 21, 22, 23, 24)) + "\n")
    deck += "*INITIAL_VELOCITY_NODE\n" + "".join(
        _row(n, 1000.0, 0.0, 0.0) + "\n" for n in covered)
    return deck + "*END\n"


def _rbody_j_rows(starter: str, main: int):
    lines = starter.splitlines()
    i = lines.index(f"/RBODY/{main}")
    return lines[i + 3], lines[i + 4], lines[i + 5], lines[i + 7]


_J_PLATE = "    -0.0002114266667    -0.0002114266667    -0.0002114266667"
_J_ZERO_ROW = "                   0                   0                   0"


class MassWeightedRbodyInertia(unittest.TestCase):
    """A7 — the starter ADDS every member's nodal rotary inertia IN to a
    body's tensor (inirby.F:166-168, :355) and the J cells are additive, while
    LS-DYNA's rigid-body inertia is the point-mass sum; under
    --mass-weighted-inivel the re-pointed body's J cells take IN back out."""

    def test_the_plate_coupon_gets_minus_SUM_IN(self):
        result, starter, _e = _convert(_j_plate_deck(),
                                       mass_weighted_inivel=True)
        self.assertIn("/INIVEL/ROT/", starter)
        card1, hdr, j1, j2 = _rbody_j_rows(starter, 15)
        self.assertEqual(hdr, "#                Jxx                 Jyy"
                              "                 Jzz")
        self.assertEqual(j1, _J_PLATE)
        self.assertEqual(j2, _J_ZERO_ROW)          # Jxy Jyz Jxz untouched
        self.assertEqual(card1[70:80].strip(), "0")    # ICoG untouched
        self.assertTrue(_has(result.warnings, "also wrote J = -0.000211427",
                             "/RBODY/15", "4 shell node(s)", "0.1977227E-02",
                             "189.96", "1.156x"), result.warnings)

    def test_the_flag_OFF_arm_is_untouched_and_the_pass_is_gated(self):
        from k2rad.writer import assembly
        _r, s_off, _e = _convert(_j_plate_deck())
        self.assertEqual(_rbody_j_rows(s_off, 15)[2], _J_ZERO_ROW)
        saved = assembly._apply_mass_weighted_rbody_inertia
        assembly._apply_mass_weighted_rbody_inertia = (
            lambda state, lines, rbody_info: None)
        try:
            _r2, s_nopass, _e2 = _convert(_j_plate_deck())
        finally:
            assembly._apply_mass_weighted_rbody_inertia = saved
        self.assertEqual(s_off, s_nopass)

    def test_only_the_re_pointed_body_gets_the_cells(self):
        """Two rigid bodies, the card on the plate only: one J row changes."""
        _r, starter, _e = _convert(_j_plate_deck(second_rigid=True),
                                   mass_weighted_inivel=True)
        mains = [int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                 if ln.startswith("/RBODY/")]
        self.assertEqual(len(mains), 2, mains)
        rows = sorted(_rbody_j_rows(starter, m)[2] for m in mains)
        self.assertEqual(rows, sorted([_J_PLATE, _J_ZERO_ROW]))

    def test_a_fully_covered_body_keeps_its_J(self):
        _r, starter, _e = _convert(_j_plate_deck(covered=(1, 2, 3, 4)),
                                   mass_weighted_inivel=True)
        self.assertNotIn("/INIVEL/ROT/", starter)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)

    def test_a_layered_section_is_skipped_by_name(self):
        result, starter, _e = _convert(_j_plate_deck(icomp=True),
                                       mass_weighted_inivel=True)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)
        self.assertTrue(_has(result.warnings, "/RBODY/15 keeps its J",
                             "ICOMP 1"), result.warnings)

    def test_an_element_thickness_is_skipped_by_name(self):
        result, starter, _e = _convert(_j_plate_deck(thickness=True),
                                       mass_weighted_inivel=True)
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)
        self.assertTrue(_has(result.warnings, "/RBODY/15 keeps its J",
                             "*ELEMENT_SHELL_THICKNESS"), result.warnings)

    def test_Ishell_below_11_is_skipped_by_name(self):
        """k2rad only writes Ishell 12 / 24 today (reach 0), so the branch is
        probed by making the shared mapper answer 1."""
        from k2rad.writer import common
        saved = common._elform_to_ishell
        common._elform_to_ishell = lambda *a, **k: 1
        try:
            result, starter, _e = _convert(_j_plate_deck(),
                                           mass_weighted_inivel=True)
        finally:
            common._elform_to_ishell = saved
        self.assertEqual(_rbody_j_rows(starter, 15)[2], _J_ZERO_ROW)
        self.assertTrue(_has(result.warnings, "Ishell 1 < 11", "FAC 9"),
                        result.warnings)

    def _direct(self, rec, j_row=None):
        from k2rad.writer import loads
        from k2rad.writer.rbody import _inertia_lines
        state = _dispatch(_j_plate_deck())
        state.options.mass_weighted_inivel = True
        state.nodes[15] = state.nodes[1].__class__(0.0, 0.0, 0.0)
        state.mass_weighted_rot_mains[15] = (0.0, 0.0, -25.0)
        rows = _inertia_lines(rec["j"])
        if j_row is not None:
            rows[1] = j_row
        lines = ["/RBODY/15", "RBODY_1", "#hdr", "card1"] + rows
        loads._apply_mass_weighted_rbody_inertia(state, lines, {1: rec})
        return state, lines

    def test_an_ICoG_4_body_is_skipped_by_name(self):
        rec = {"ind_node": 15, "nodes": [1, 2, 3, 4], "icog": 4,
               "j": (1.0, 2.0, 3.0, 0.0, 0.0, 0.0)}
        state, lines = self._direct(rec)
        self.assertEqual(lines[5], _inertia_lines_row((1.0, 2.0, 3.0)))
        self.assertTrue(_has(state.warnings, "ICoG 4", "*PART_INERTIA"),
                        state.warnings)

    def test_a_row_that_is_not_the_recorded_one_raises(self):
        rec = {"ind_node": 15, "nodes": [1, 2, 3, 4], "icog": 0,
               "j": (0.0,) * 6}
        with self.assertRaises(RuntimeError):
            self._direct(rec, j_row="   1   2   3")

    def test_a_non_positive_principal_value_is_refused(self):
        """A J already so negative that -SUM(IN) would drive the tensor
        indefinite: ERROR 274 (inirby.F:823) is refused before it is
        written."""
        rec = {"ind_node": 15, "nodes": [1, 2, 3, 4], "icog": 0,
               "j": (-1.0, -1.0, -1.0, 0.0, 0.0, 0.0)}
        state, lines = self._direct(rec)
        self.assertEqual(lines[5], _inertia_lines_row((-1.0, -1.0, -1.0)))
        self.assertTrue(_has(state.warnings, "ERROR 274", "<= 0"),
                        state.warnings)


def _inertia_lines_row(j3):
    from k2rad.writer.rbody import _inertia_lines
    return _inertia_lines(tuple(j3) + (0.0, 0.0, 0.0))[1]


# ═════════════════════════════════════════════════════════════════════════════
# A8 — the shell-offset Gapmin (a solid main against shells LS-DYNA offsets)
# ═════════════════════════════════════════════════════════════════════════════

def _offset_deck(shlthk=2, kw="*CONTACT_SURFACE_TO_SURFACE_ID",
                 thick=(0.381,), edge=0.254, implicit=False,
                 card3=(0, 0, 0, 0), cards_ab="", solid_secondary=False,
                 rigid=(), composite=False, swap=False, skin=False,
                 extra_node=False) -> str:
    """The A8 coupon: a cube of side *edge* (part 1, the MAIN; its smallest
    segment side is *edge*) and, 0.5 above it, one 4-node shell per entry of
    *thick* (parts 2, 3, ...; the SECONDARY, a *SET_PART_LIST when there are
    several) - or, with *solid_secondary*, a second cube (part 2). *rigid*
    names the parts on *MAT_RIGID; *composite* puts part 2 on a two-ply
    *PART_COMPOSITE of half its thickness each; *swap* writes the card the
    sphere1 way round (SSID = the cube, MSID = the shell); *skin* (with
    *solid_secondary*) adds a shell skin on the upper cube's top face, part 3
    t *thick[0]*, and makes IT the SSID; *extra_node* makes the SSID a
    *SET_NODE_LIST of the shell nodes PLUS one node on no element. Card 3 is
    ``SFS SFM SST MST`` = *card3*; *cards_ab* is appended after it."""
    a = edge
    z = a + 0.5
    nodes = [(0.0, 0.0, 0.0), (a, 0.0, 0.0), (a, a, 0.0), (0.0, a, 0.0),
             (0.0, 0.0, a), (a, 0.0, a), (a, a, a), (0.0, a, a)]
    solids = [(1, 1, tuple(range(1, 9)))]
    shells = []
    parts = []
    if solid_secondary:
        nodes += [(x, y, zz + z) for (x, y, zz) in nodes[:8]]
        solids.append((2, 2, tuple(range(9, 17))))
        if skin:
            shells.append((20, 3, (13, 14, 15, 16)))
            parts.append((3, thick[0]))
    else:
        for k, t in enumerate(thick):
            x0 = k * a
            base = len(nodes)
            nodes += [(x0, 0.0, z), (x0 + a, 0.0, z), (x0 + a, a, z),
                      (x0, a, z)]
            shells.append((10 + k, k + 2, tuple(range(base + 1, base + 5))))
            parts.append((k + 2, t))
    if extra_node:
        nodes.append((a / 2.0, a / 2.0, z + 1.0))
    deck = "*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
    if implicit:
        deck += "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
    if shlthk is not None:
        deck += "*CONTROL_CONTACT\n" + _row(0.1, 0.0, 1, shlthk, 1, 0) + "\n"
    deck += "*NODE\n" + "".join(f"{i:>8}{x:>16}{y:>16}{zz:>16}\n"
                                for i, (x, y, zz) in enumerate(nodes, start=1))
    deck += "*ELEMENT_SOLID\n" + "".join(
        "".join(f"{v:>8}" for v in (eid, pid) + ns) + "\n"
        for eid, pid, ns in solids)
    if shells:
        deck += "*ELEMENT_SHELL\n" + "".join(
            "".join(f"{v:>8}" for v in (eid, pid) + ns) + "\n"
            for eid, pid, ns in shells)
    deck += ("*PART\nbrick\n" + _row(1, 1, 1) + "\n"
             "*SECTION_SOLID\n" + _row(1, 1) + "\n")
    mids = [1]
    if solid_secondary:
        deck += "*PART\nupper brick\n" + _row(2, 1, 2) + "\n"
        mids.append(2)
    for pid, t in parts:
        if composite and pid == 2:
            deck += ("*PART_COMPOSITE\nsheet\n"
                     + _row(pid, 16, 0.0, 0, 0.0, 0, 0, 0) + "\n"
                     + _row(pid, t / 2.0, 0.0, 0, pid, t / 2.0, 0.0, 0) + "\n")
        else:
            deck += (f"*PART\nsheet {pid}\n" + _row(pid, pid, pid) + "\n"
                     "*SECTION_SHELL\n" + _row(pid, 16) + "\n"
                     + _row(t, t, t, t) + "\n")
        mids.append(pid)
    for mid in mids:
        card = "*MAT_RIGID\n" if mid in rigid else "*MAT_ELASTIC\n"
        deck += card + _row(mid, 7.85e-9, 210000.0, 0.3) + "\n"
    if len(parts) > 1:
        deck += ("*SET_PART_LIST\n" + _row(200) + "\n"
                 + _row(*[p for p, _t in parts]) + "\n")
        ssid, sstyp = 200, 2
    elif skin:
        ssid, sstyp = 3, 3
    elif extra_node:
        deck += ("*SET_NODE_LIST\n" + _row(300) + "\n"
                 + _row(9, 10, 11, 12, len(nodes)) + "\n")
        ssid, sstyp = 300, 4
    else:
        ssid, sstyp = 2, 3
    if swap:
        ssid, sstyp, msid, mstyp = 1, 3, ssid, sstyp
    else:
        msid, mstyp = 1, 3
    deck += (kw + "\n" + _row(7) + "\n"
             + _row(ssid, msid, sstyp, mstyp, 0, 0, 0, 0) + "\n"
             + _row(0.2, 0.1) + "\n" + _row(*card3) + "\n" + cards_ab)
    return deck + "*END\n"


def _type7_cells(starter: str, inter_id: int = 7):
    """``(Gapmin cell, Inacti)`` of ``/INTER/TYPE7/<inter_id>``: the Gapmin
    cell is the raw 20-column field (cols 41-60), so a test pins the
    spelling the card carries."""
    lines = starter.splitlines()
    i = lines.index(f"/INTER/TYPE7/{inter_id}")
    gap = inacti = None
    for j in range(i + 1, min(i + 20, len(lines) - 1)):
        if lines[j].startswith("#              Stfac"):
            gap = lines[j + 1][40:60]
        if lines[j].startswith("#      IBC") and "Inacti" in lines[j]:
            inacti = lines[j + 1].split()[1]
    assert gap is not None and inacti is not None, lines[i:i + 20]
    return gap, inacti


_G0127 = "               0.127"
_G0 = "                   0"
_A8 = "LS-DYNA offsets the secondary SHELLS by half their thickness"
_CLASS = "GAP MIN = 0.1 x"


class ShellOffsetGapmin(unittest.TestCase):
    """A8: Gapmin = t/2 (capped at 0.5 x the smallest main-segment side) on a
    solid-only-main /INTER/TYPE7 whose EMITTED secondary is shells LS-DYNA
    offsets (General Remark 12 spelling, SHLTHK 1/2, or Card B THKOPT 1)."""

    def test_SHLTHK_2_writes_the_clamped_half_thickness(self):
        """bend's shape: t 0.381 -> t/2 0.1905 > 0.5 x 0.254 -> 0.127."""
        result, starter, _ = _convert(_offset_deck(shlthk=2))
        self.assertEqual(_type7_cells(starter), (_G0127, "5"))
        w = [x for x in result.warnings if _A8 in x]
        self.assertEqual(len(w), 1, result.warnings)
        for needle in ("*CONTROL_CONTACT SHLTHK 2 (p.12-70)", "t/2 = 0.1905",
                       "CLAMPED to 0.5 x the smallest main-segment side "
                       "0.254", "0.1 x 0.254 = 0.0254", "i7sti3.F:1055-1063",
                       ":1075-1083", "bend.k", "-45.60 %", "0.98x",
                       "--no-shell-offset-gapmin"):
            self.assertIn(needle, w[0])
        self.assertFalse(_has(result.warnings, _CLASS), result.warnings)

    def test_SHLTHK_0_is_unchanged_and_keeps_the_class_warning(self):
        result, starter, _ = _convert(_offset_deck(shlthk=0))
        self.assertEqual(_type7_cells(starter), (_G0, "5"))
        self.assertTrue(_has(result.warnings, _CLASS, "0.254"))
        self.assertFalse(_has(result.warnings, _A8))

    def test_no_CONTROL_CONTACT_reads_as_SHLTHK_0(self):
        result, starter, _ = _convert(_offset_deck(shlthk=None))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertFalse(_has(result.warnings, _A8))

    def test_an_AUTOMATIC_spelling_always_offsets(self):
        """General Remark 12: SHLTHK is ignored for these types."""
        result, starter, _ = _convert(_offset_deck(
            shlthk=0, kw="*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID",
            thick=(0.1,)))
        self.assertEqual(_type7_cells(starter)[0], "                0.05")
        w = [x for x in result.warnings if _A8 in x]
        self.assertEqual(len(w), 1, result.warnings)
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE always does", w[0])
        self.assertNotIn("CLAMPED", w[0])

    def test_SHLTHK_1_excludes_a_rigid_shell_and_SHLTHK_2_includes_it(self):
        """Both sides rigid -> the KEEP arm, so the emitted secondary IS the
        rigid shell: SHLTHK 1 excludes rigid bodies, SHLTHK 2 does not."""
        one = _convert(_offset_deck(shlthk=1, rigid=(1, 2)))
        two = _convert(_offset_deck(shlthk=2, rigid=(1, 2)))
        self.assertEqual(_type7_cells(one[1])[0], _G0)
        self.assertFalse(_has(one[0].warnings, _A8))
        # an ALL-rigid surface is a clean exclusion, not the mixed refusal
        self.assertFalse(_has(one[0].warnings, "mixes"))
        self.assertTrue(_has(one[0].warnings, _CLASS))
        self.assertEqual(_type7_cells(two[1])[0], _G0127)
        # ... and on a DEFORMABLE shell SHLTHK 1 does offset
        dfm = _convert(_offset_deck(shlthk=1))
        self.assertEqual(_type7_cells(dfm[1])[0], _G0127)
        self.assertTrue(_has(dfm[0].warnings, _A8, "SHLTHK 1"))

    def test_a_surface_mixing_rigid_and_deformable_shells_under_SHLTHK_1(self):
        """Refused as ambiguous. The writer's own route cannot build it (the
        resolver drops the rigid nodes unless BOTH sides are rigid), so the
        rule is called directly with the rigid filter off."""
        from k2rad.writer.contacts import _shell_offset_gapmin
        state = _dispatch(_offset_deck(shlthk=1, thick=(0.381, 0.381),
                                       rigid=(2,)))
        c = state.contacts_surf2surf[0]
        self.assertEqual(_shell_offset_gapmin(state, c, 0.0, 1, 3, 200, 2,
                                              set(), True), (0.0, False))
        self.assertTrue(_has(state.warnings, "mixes 1 rigid and 1 deformable",
                             "SHLTHK 1"))

    def test_a_solid_secondary_is_unchanged(self):
        result, starter, _ = _convert(_offset_deck(solid_secondary=True))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertTrue(_has(result.warnings, _CLASS))
        self.assertFalse(_has(result.warnings, _A8))

    def test_a_shell_skin_on_a_solid_is_not_a_shell_secondary(self):
        """Every node of the skin is ALSO a solid node: the surface is not
        shell-only, so the rule stays out (the solid-node screen, not the
        coverage one, is what refuses it)."""
        result, starter, _ = _convert(_offset_deck(solid_secondary=True,
                                                   skin=True))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertFalse(_has(result.warnings, _A8))
        self.assertTrue(_has(result.warnings, _CLASS))

    def test_a_shell_MAIN_is_never_touched(self):
        """AUTOMATIC (always offsets), but the main is a shell plate: the
        starter's own default there is the mean shell thickness."""
        deck = _offset_deck(kw="*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID",
                            thick=(0.381, 0.5))
        # part 3 becomes the MAIN: SSID part 2, MSID part 3, no set
        deck = deck.replace(_row(200, 1, 2, 3, 0, 0, 0, 0),
                            _row(2, 3, 3, 3, 0, 0, 0, 0))
        self.assertIn(_row(2, 3, 3, 3, 0, 0, 0, 0), deck)
        base = _convert(deck)
        self.assertEqual(_type7_cells(base[1])[0], _G0)
        self.assertFalse(_has(base[0].warnings, _A8))
        self.assertEqual(base[1], _convert(deck, shell_offset_gapmin=False)[1])

    def test_a_node_on_no_shell_keeps_the_rule_out(self):
        """A node-set SSID: the four shell nodes plus one node on no element.
        Not every emitted secondary node lies on a shell of the group."""
        result, starter, _ = _convert(_offset_deck(extra_node=True))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertFalse(_has(result.warnings, _A8))
        # ... the same node set WITHOUT the stray node is a shell surface
        deck = _offset_deck(extra_node=True).replace(
            _row(9, 10, 11, 12, 13), _row(9, 10, 11, 12))
        self.assertEqual(_type7_cells(_convert(deck)[1])[0], _G0127)

    def test_the_rule_reads_the_group_the_resolver_wrote(self):
        """A partly rigid secondary (deformable t 0.381 + rigid t 0.1): the
        resolver drops the rigid nodes, so the surface the rule judges is
        the 0.381 shell alone - not a refused [0.1, 0.381] mix."""
        result, starter, _ = _convert(_offset_deck(thick=(0.381, 0.1),
                                                   rigid=(3,)))
        self.assertEqual(_type7_cells(starter)[0], _G0127)
        self.assertFalse(_has(result.warnings, "at least one t/2 is below"))

    def test_the_interference_family_is_excluded(self):
        """A press-fit needs the large derived gap to engage at all."""
        result, starter, _ = _convert(_offset_deck(
            kw="*CONTACT_SURFACE_TO_SURFACE_INTERFERENCE_ID"))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertFalse(_has(result.warnings, _A8))

    def test_mixed_thicknesses_all_above_the_cap(self):
        result, starter, _ = _convert(_offset_deck(thick=(0.381, 1.0)))
        self.assertEqual(_type7_cells(starter)[0], _G0127)
        w = [x for x in result.warnings if _A8 in x]
        self.assertEqual(len(w), 1, result.warnings)
        self.assertIn("CLAMPED", w[0])
        self.assertIn("carries shells of thickness [0.381, 1.0]; every t/2 "
                      "is above the ceiling", w[0])

    def test_mixed_thicknesses_one_below_the_cap_is_refused(self):
        result, starter, _ = _convert(_offset_deck(thick=(0.1, 1.0)))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertTrue(_has(result.warnings, "thickness [0.1, 1.0] and at "
                             "least one t/2 is below the ceiling",
                             "no single constant Gapmin"))
        self.assertFalse(_has(result.warnings, _A8))
        self.assertTrue(_has(result.warnings, _CLASS))

    def test_a_composite_secondary_offsets_by_its_ply_sum(self):
        """Ryan_Lee W6's face sheets have no *SECTION_SHELL: the thickness is
        the ply stack (2 x 0.3 = 0.6 -> t/2 0.3, below the 0.5 x 10 cap)."""
        result, starter, _ = _convert(_offset_deck(thick=(0.6,), edge=10.0,
                                                   composite=True))
        self.assertEqual(_type7_cells(starter)[0], "                 0.3")
        self.assertTrue(_has(result.warnings, _A8, "t/2 = 0.3"))

    def test_a_stated_SST_wins(self):
        result, starter, _ = _convert(_offset_deck(card3=(0, 0, 0.2, 0)))
        self.assertEqual(_type7_cells(starter)[0], "                 0.1")
        self.assertFalse(_has(result.warnings, _A8))

    def test_inter_gapmin_wins(self):
        result, starter, _ = _convert(_offset_deck(), inter_gapmin={7: 0.03})
        self.assertEqual(_type7_cells(starter)[0], "                0.03")
        self.assertFalse(_has(result.warnings, _A8))

    def test_derived_gapmin_yields_to_it(self):
        result, starter, _ = _convert(_offset_deck(), derived_gapmin=True)
        self.assertEqual(_type7_cells(starter)[0], _G0127)
        self.assertTrue(_has(result.warnings, _A8))
        self.assertFalse(_has(result.warnings, "--derived-gapmin wrote"))

    def test_implicit_keeps_Inacti_5(self):
        """The PRE-A8 gap (0) reaches _ignore_to_inacti: the implicit
        "stated engagement gap -> Inacti 0" branch is not taken."""
        result, starter, _ = _convert(_offset_deck(implicit=True))
        self.assertEqual(_type7_cells(starter), (_G0127, "5"))
        self.assertFalse(_has(result.warnings, "explicit engagement Gapmin"))

    def test_the_sphere1_shape_is_the_negative_control(self):
        """All-rigid SSID cube, deformable shell MSID t 2.5, non-automatic,
        SHLTHK 0: the swap makes the shell the emitted secondary, and LS-DYNA
        does NOT offset it - unchanged. Under SHLTHK 2 the same sides give
        t/2 = 1.25 (below the 0.5 x 10 cap): the SHLTHK test is what holds."""
        d0 = _offset_deck(shlthk=0, thick=(2.5,), edge=10.0, rigid=(1,),
                          swap=True)
        result, starter, _ = _convert(d0)
        self.assertTrue(_has(result.warnings, "SWAPPED the roles"))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertFalse(_has(result.warnings, _A8))
        self.assertTrue(_has(result.warnings, _CLASS, "0.1 x 10"))
        d2 = _offset_deck(shlthk=2, thick=(2.5,), edge=10.0, rigid=(1,),
                          swap=True)
        self.assertEqual(_type7_cells(_convert(d2)[1])[0],
                         "                1.25")

    def test_the_opt_out_changes_exactly_the_one_cell(self):
        on = _convert(_offset_deck())
        off = _convert(_offset_deck(), shell_offset_gapmin=False)
        self.assertEqual(_type7_cells(off[1])[0], _G0)
        self.assertEqual(on[1].replace(_G0127, _G0), off[1])
        self.assertEqual(off[1], _convert(_offset_deck(shlthk=0))[1])
        self.assertTrue(_has(off[0].warnings, _CLASS))
        self.assertFalse(_has(off[0].warnings, _A8))

    def test_Card_B_THKOPT_1_uses_its_own_SHLTHK(self):
        card_ab = _row(0) + "\n" + _row(0.0, 1, 2) + "\n"
        result, starter, _ = _convert(_offset_deck(shlthk=0,
                                                   cards_ab=card_ab))
        self.assertEqual(_type7_cells(starter)[0], _G0127)
        self.assertTrue(_has(result.warnings, _A8,
                             "its own Card B THKOPT 1 / SHLTHK 2"))

    def test_Card_B_THKOPT_2_never_offsets(self):
        card_ab = _row(0) + "\n" + _row(0.0, 2, 0) + "\n"
        result, starter, _ = _convert(_offset_deck(shlthk=2,
                                                   cards_ab=card_ab))
        self.assertEqual(_type7_cells(starter)[0], _G0)
        self.assertFalse(_has(result.warnings, _A8))

    def test_the_handler_stores_Card_B(self):
        card_ab = _row(0) + "\n" + _row(0.0, 1, 2) + "\n"
        c = _dispatch(_offset_deck(cards_ab=card_ab)).contacts_surf2surf[0]
        self.assertEqual((c.thkopt, c.shlthk_c), (1, 2))
        c = _dispatch(_offset_deck()).contacts_surf2surf[0]
        self.assertEqual((c.thkopt, c.shlthk_c), (0, 0))

    def test_the_base_spelling(self):
        from k2rad.writer.contacts import (_LS_ALWAYS_OFFSETS_SHELLS,
                                           _contact_base_spelling)
        for kw, base in (
                ("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
                 "AUTOMATIC_SURFACE_TO_SURFACE"),
                ("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_MPP",
                 "AUTOMATIC_SURFACE_TO_SURFACE"),
                ("*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID_MPP",
                 "AUTOMATIC_SINGLE_SURFACE"),
                ("CONTACT_SURFACE_TO_SURFACE_TITLE", "SURFACE_TO_SURFACE"),
                ("CONTACT_SURFACE_TO_SURFACE_THERMAL",
                 "SURFACE_TO_SURFACE_THERMAL")):
            with self.subTest(kw=kw):
                self.assertEqual(_contact_base_spelling(kw), base)
        self.assertEqual(len(_LS_ALWAYS_OFFSETS_SHELLS), 8)
        self.assertNotIn("SURFACE_TO_SURFACE", _LS_ALWAYS_OFFSETS_SHELLS)
        self.assertNotIn("AUTOMATIC_SURFACE_TO_SURFACE_MORTAR",
                         _LS_ALWAYS_OFFSETS_SHELLS)


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
        "--weld-exponents": "weld_exponents",
        "--constrained-linear": "constrained_linear",
        "--shell-offset-gapmin": "shell_offset_gapmin",
    }
    #: figures each flag's --help must carry (matched on the collapsed render)
    _HELP_FIGURES = {
        "--initial-void-floor": ("1095 cycles", "2936 cycles",
                                 "hm_read_mat06.F:154"),
        "--weld-exponents": ("2.460e-4", "+29.4 %", "0.899x",
                             "hm_read_prop13.F:1169-1170"),
        "--constrained-linear": ("NUMMPC 1", "683 rows",
                                 "hm_read_mpc.F:124"),
        "--shell-offset-gapmin": ("the capped 0.127", "-45.60 %", "0.98x",
                                  "i7sti3.F:1055-1063"),
        "--mass-weighted-inivel": ("J = -SUM(IN)", "0.1977227E-02",
                                   "189.96", "1.156x"),
        "--spring-token-mass-compensation": (
            "TOTAL MASS 1.02e-4 -> 2.0e-6", "chkmsin.F:53",
            "accele.F:67-80"),
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
            self.assertIn(flag, text)
            if flag in self._FLAGS:          # the default-ON opt-outs
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
    # A2: the TYPE13 alpha/beta cells now carry the deck's N / M
    "criterion is quadratic (N=M=2)",
    "is quadratic (N=M=2)",
    "non-quadratic exponents are warned",
    # A3: two *INCLUDE fragments reach the orphan sentence; MS = 0 is caught
    # by nothing (chkmsin.F:53 is strict), so "aborts" was false for MS = 0
    "no deck on any corpus here reaches this",
    "MS <= 0 aborts the engine",
    # A6: the zero-coupling class IS inverted now; the re-state advice is
    # true only "in OTHER axes"
    "Inverting C to engineering constants is deliberately NOT attempted",
    "Re-state the material as *MAT_ORTHOTROPIC_ELASTIC",
    # A7: the J cells ARE written now (J = -SUM(IN)); additivity is why it
    # works, not a reason against it
    "not compensated here",
    "would double-count",
    # A8: a solid main against shells LS-DYNA offsets now gets t/2
    "on every `/INTER/TYPE7` it emits unless the card states Card-3",
    # A2 (finalization round): the direction of the shear-sum difference
    # follows M - conservative only for M < 2, NON-conservative for M > 2
    "M != 2 is conservative",
    "M ≠ 2 is conservative",
    "`M ≠ 2` is conservative",
    "resultant) - conservative.",
    "``M != 2`` is conservative",
)

#: The same family as regexes, matched on the collapsed text (a phrase whose
#: punctuation drifted between the sites that shipped it).
_RETRACTED_ROUND_6_A_RE = (
    r"MS <= 0\W{0,4},? which the engine aborts on",
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

    def test_no_shipped_text_matches_a_retracted_regex(self):
        for rel, joined in _SHIPPED_TEXTS():
            for pat in _RETRACTED_ROUND_6_A_RE:
                with self.subTest(file=rel, pattern=pat):
                    self.assertIsNone(re.search(pat, joined, re.I))

    def test_each_retracted_regex_fires_on_the_spelling_it_retracts(self):
        samples = (
            "there leaves ``MS <= 0``, which the engine aborts on",
            "would leave MS <= 0, which the ENGINE aborts on",
        )
        for pat in _RETRACTED_ROUND_6_A_RE:
            for sample in samples:
                with self.subTest(pattern=pat, sample=sample):
                    split = sample.replace(" ", ' "\n            "')
                    joined = _collapse(re.sub(r'"\s*\n\s*"', "", split))
                    self.assertIsNotNone(re.search(pat, joined, re.I))

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
            ("k2rad/writer/loads.py", "beta2 = beta3 = {m:g}, so the Ifail = 1"),
            ("k2rad/writer/loads.py", "(NON-conservative for M > 2)."),
            ("README.md", "an `M > 2` weld fails LATER (0.707× at `M = 3`, "
             "non-conservative)"),
            ("k2rad/cli.py", "M > 2 weld fails later (non-conservative)"),
            ("README.md", "`--no-weld-exponents`"),
            ("k2rad/writer/loads.py", "The deck names these nodes but does "
             "not define them: it is a fragment"),
            ("k2rad/cli.py", "which nothing catches (chkmsin.F:53 aborts "
             "only on MS < 0; accele.F:67-80 then freezes the node's "
             "velocity)"),
            ("README.md", "the screen is the node's OWN mass, not element "
             "incidence"),
            ("k2rad/handlers.py", "the material IS orthotropic and its "
             "constants are restated EXACTLY through the "
             "*MAT_ORTHOTROPIC_ELASTIC path"),
            ("README.md", "the `/PROP/TYPE6` is written on **`Isolid 14`** "
             "(HA8, fully integrated, 2×2×2 points) instead of the "
             "ELFORM-derived `17`"),
            ("k2rad/writer/composites.py", "Ip=23 wrong on 4 of 6 loaded "
             "faces against LS-DYNA's AOPT 3 frame"),
            ("k2rad/handlers.py", "state it as *MAT_ORTHOTROPIC_ELASTIC in "
             "those axes (AOPT)"),
            ("README.md", "restated **EXACTLY through the orthotropic path "
             "when all 12 coupling cells are 0 and C is positive definite**"),
            ("k2rad/writer/loads.py", "so the J cells take the difference "
             "back out"),
            ("README.md", "the flag also writes `J = −ΣIN` into every body "
             "it re-points"),
            ("ROADMAP.md", "CLOSED under the flag by A7"),
            ("README.md", "or LS-DYNA offsets a SHELL secondary (the "
             "shell-offset Gapmin"),
            ("README.md", "**The shell-offset Gapmin takes precedence**"),
            ("ROADMAP.md", "Round 6: `bend` left this flag's reach."),
            ("k2rad/writer/contacts.py", "LS-DYNA offsets the secondary "
             "SHELLS by"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])



# ═════════════════════════════════════════════════════════════════════════════
# PART B
# ═════════════════════════════════════════════════════════════════════════════

def _fixture_text(name: str) -> str:
    root = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(root, "fixtures", name)) as fh:
        return fh.read()


def _impl_deck(solution=None, extra: str = "", general=None,
               termination=None) -> str:
    """The ``implicit_qstat`` golden deck (DT0 0.01, ENDTIM 1.0, no
    ``*CONTROL_IMPLICIT_AUTO``) plus a ``*CONTROL_IMPLICIT_SOLUTION`` whose
    card 1 is *solution* (a row, or None for no card) and any *extra* cards.
    *general* / *termination* replace the two data rows when given."""
    deck = _fixture_text("implicit_qstat.k")
    if general is not None:
        deck = deck.replace("         1      0.01\n", general + "\n")
    if termination is not None:
        deck = deck.replace("*CONTROL_TERMINATION\n       1.0\n",
                            "*CONTROL_TERMINATION\n" + termination + "\n")
    add = ""
    if solution is not None:
        add += "*CONTROL_IMPLICIT_SOLUTION\n" + solution + "\n"
    add += extra
    return deck.replace("*CONTROL_TERMINATION", add + "*CONTROL_TERMINATION")


def _nonlin_row(engine: str) -> str:
    """The ``L_A Itol Toli`` data line of ``/IMPL/NONLIN/1``."""
    lines = engine.splitlines()
    i = lines.index("/IMPL/NONLIN/1")
    return lines[i + 2]


_B1_HEAD = "*CONTROL_IMPLICIT_SOLUTION states no usable convergence tolerance"


class ZeroToleranceEctol(unittest.TestCase):
    """B1: all-zero ``*CONTROL_IMPLICIT_SOLUTION`` tolerances -> LS-DYNA's
    ECTOL default, and every other branch byte-identical (the spec's table,
    one row per test; expectations hand-derived from the rule)."""

    def _arm(self, row, **kw):
        res, _starter, engine = _convert(_impl_deck(row), **kw)
        return res.warnings, _nonlin_row(engine)

    def test_stated_zeros_get_the_ECTOL_default(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "0.0", "0.0"))
        self.assertEqual(line, "  2 1 0.01")
        self.assertTrue(_has(warns, _B1_HEAD, "0.1000E-01",
                             "--no-zero-tolerance-ectol", "Itol 1, Toli 0.01",
                             "-0.54 %", "+582.00 %", "-99.87 %"))

    def test_blank_tolerances_are_the_same_class(self):
        warns, line = self._arm(_row(12))
        self.assertEqual(line, "  2 1 0.01")
        self.assertTrue(_has(warns, _B1_HEAD))

    def test_the_opt_out_keeps_the_force_default(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "0.0", "0.0"),
                                zero_tolerance_ectol=False)
        self.assertEqual(line, "  2 2 0.01")
        self.assertFalse(_has(warns, _B1_HEAD))

    def test_the_RCTOL_branch_is_unchanged(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "0.0", "0.005"))
        self.assertEqual(line, "  2 2 0.005")
        self.assertFalse(_has(warns, _B1_HEAD))

    def test_the_ECTOL_branch_is_unchanged(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "0.02", "0.0"))
        self.assertEqual(line, "  2 1 0.02")
        self.assertFalse(_has(warns, _B1_HEAD))

    def test_the_DCTOL_branch_is_unchanged(self):
        warns, line = self._arm(_row(12, 0, 0, "0.003", "0.0", "0.0"))
        self.assertEqual(line, "  2 3 0.003")
        self.assertFalse(_has(warns, _B1_HEAD))

    def test_ILIMIT_is_kept_as_L_A(self):
        warns, line = self._arm(_row(12, 11, 15, "0.0", "0.0", "0.0"))
        self.assertEqual(line, "  11 1 0.01")
        self.assertTrue(_has(warns, _B1_HEAD))

    def test_a_value_ge_1_beside_zeros_names_the_ECTOL_default(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "0.0", "1.0E+10"))
        self.assertEqual(line, "  2 1 0.01")
        self.assertTrue(_has(warns, _B1_HEAD))
        ge1 = [w for w in warns if "rctol=1e+10 is >= 1.0" in w]
        self.assertEqual(len(ge1), 1, warns)
        self.assertTrue(ge1[0].endswith(
            "Using LS-DYNA's own ECTOL default instead (Itol 1, Toli 0.01; "
            "see the warning below)."), ge1[0])

    def test_a_value_ge_1_beside_a_real_ECTOL_keeps_the_old_text(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "0.01", "1.0E+10"))
        self.assertEqual(line, "  2 1 0.01")
        self.assertFalse(_has(warns, _B1_HEAD))
        ge1 = [w for w in warns if "rctol=1e+10 is >= 1.0" in w]
        self.assertEqual(len(ge1), 1, warns)
        self.assertTrue(ge1[0].endswith(
            "Using robust /IMPL/NONLIN default Toli=0.01."), ge1[0])

    def test_no_card_keeps_the_force_default(self):
        warns, line = self._arm(None)
        self.assertEqual(line, "  2 2 0.01")
        self.assertFalse(_has(warns, _B1_HEAD))

    def test_a_negative_ECTOL_is_a_curve_not_a_stated_zero(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "-7", "0.0"))
        self.assertEqual(line, "  2 2 0.01")
        self.assertFalse(_has(warns, _B1_HEAD))
        self.assertTrue(_has(warns, "ECTOL=-7 is NEGATIVE",
                             "The curve is DROPPED", "Itol 2, Toli 0.01"))

    def test_a_negative_ECTOL_under_the_opt_out(self):
        warns, line = self._arm(_row(12, 0, 0, "0.0", "-7", "0.0"),
                                zero_tolerance_ectol=False)
        self.assertEqual(line, "  2 2 0.01")
        self.assertFalse(_has(warns, _B1_HEAD))
        self.assertTrue(_has(warns, "ECTOL=-7 is NEGATIVE",
                             "The curve is DROPPED"))

    def test_the_warning_fires_once_per_deck(self):
        warns, _line = self._arm(_row(12, 0, 0, "0.0", "0.0", "0.0"))
        self.assertEqual(sum(_B1_HEAD in w for w in warns), 1)

    def test_the_golden_deck_is_not_reached(self):
        """``implicit_qstat`` states no SOLUTION card: B1's own control."""
        res, _s, engine = _convert(_fixture_text("implicit_qstat.k"))
        self.assertEqual(_nonlin_row(engine), "  2 2 0.01")
        self.assertFalse(_has(res.warnings, _B1_HEAD))



def _auto_card(iauto=0, iteopt=11, itewin=0, dtmin="0.0", dtmax="0.0") -> str:
    """``*CONTROL_IMPLICIT_AUTO`` card 1: IAUTO ITEOPT ITEWIN DTMIN DTMAX."""
    return ("*CONTROL_IMPLICIT_AUTO\n"
            + _row(iauto, iteopt, itewin, dtmin, dtmax) + "\n")


def _dt_stop_row(engine: str) -> str:
    """The ``DT_MIN DT_MAX`` data line of ``/IMPL/DT/STOP``."""
    lines = engine.splitlines()
    return lines[lines.index("/IMPL/DT/STOP") + 1]


_B3_ON = "--implicit-constant-step: /IMPL/DT/STOP DT_MAX := DT0"
_B3_OFF = "--implicit-constant-step was passed but wrote nothing"

_EIGEN_CARD = ("*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(10) + "\n")
_RIKS_SOLUTION = _row(6, 0, 0, "0.001", "0.01", "1.0E+10")


class ImplicitConstantStep(unittest.TestCase):
    """B3: ``--implicit-constant-step`` writes the deck's own DT0 into the
    SECOND ``/IMPL/DT/STOP`` cell inside its scope, and nothing else, ever.
    One fixture per branch; expected rows hand-derived from ``_f``."""

    def _arm(self, deck, **kw):
        res, _s, engine = _convert(deck, **kw)
        return res.warnings, engine

    def test_1_no_AUTO_card_gets_the_cap(self):
        warns, engine = self._arm(_impl_deck(),
                                  implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                0.01")
        self.assertTrue(_has(warns, _B3_ON, "DT0 = 0.01",
                             "IAUTO is 0 by default (no "
                             "*CONTROL_IMPLICIT_AUTO)", "It_w = 8",
                             "+74.1 % -> -0.9 %", "75 -> 168",
                             "-0.54 % -> -4.36 %", "+1343 %"))

    def test_2_the_same_deck_without_the_flag_is_the_golden(self):
        warns, engine = self._arm(_impl_deck())
        root = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(root, "fixtures", "expected",
                               "implicit_qstat_0001.rad")) as fh:
            golden = fh.read()
        self.assertEqual(engine, golden)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                   0")
        self.assertFalse(_has(warns, _B3_ON))
        self.assertFalse(_has(warns, _B3_OFF))

    def test_3_a_stated_DTMAX_below_DT0_already_caps(self):
        deck = _impl_deck(extra=_auto_card(0, 11, 0, "0.0", "0.005"))
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06               0.005")
        self.assertTrue(_has(warns, _B3_OFF, "already caps the step"))
        self.assertFalse(_has(warns, _B3_ON))

    def test_4_DT0_zero_is_one_LS_step(self):
        deck = _impl_deck(general=_row(1, "0.0"))
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                   0")
        self.assertTrue(_has(warns, _B3_OFF, "DT0 = 0: LS-DYNA takes ONE step"))

    def test_5_DT0_at_ENDTIM_is_one_LS_step(self):
        deck = _impl_deck(general=_row(1, "1.0"))
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "              0.0001                   0")
        self.assertTrue(_has(warns, _B3_OFF, ">= ENDTIM = 1"))

    def test_6_IAUTO_1_is_automatic_control(self):
        deck = _impl_deck(extra=_auto_card(1))
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                   0")
        self.assertTrue(_has(warns, _B3_OFF, "IAUTO=1"))

    def test_7_a_modal_deck_writes_no_DT_card(self):
        deck = _impl_deck(extra=_EIGEN_CARD)
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertNotIn("/IMPL/DT/STOP", engine)
        self.assertTrue(_has(warns, _B3_OFF,
                             "not an implicit time-marching analysis"))

    def test_8_the_RIKS_arm_is_not_touched(self):
        deck = _impl_deck(_RIKS_SOLUTION)
        warns, engine = self._arm(deck, implicit_constant_step=True,
                                  arclength_riks=True)
        self.assertIn("/IMPL/DT/3", engine)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                   0")
        self.assertTrue(_has(warns, _B3_OFF, "--arclength-riks"))

    def test_9_a_dynamic_deck_caps_at_DT0_not_at_DTINI(self):
        deck = _impl_deck(extra="*CONTROL_IMPLICIT_DYNAMICS\n" + _row(1)
                          + "\n")
        warns, engine = self._arm(deck, implicit_constant_step=True)
        lines = engine.splitlines()
        self.assertEqual(lines[lines.index("/IMPL/DTINI") + 1].strip(),
                         "0.001")
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-07                0.01")
        self.assertTrue(_has(warns, _B3_ON, "DT0 = 0.01"))

    def test_10_a_DTMIN_at_or_above_DT0_is_a_pinned_step(self):
        deck = _impl_deck(extra=_auto_card(0, 11, 0, "0.02", "0.0"))
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "                0.02                   0")
        self.assertTrue(_has(warns, _B3_OFF, "a pinned step"))

    def test_11_a_stated_DTMAX_above_DT0_is_replaced_and_named(self):
        deck = _impl_deck(extra=_auto_card(0, 11, 0, "0.0", "0.05"))
        warns, engine = self._arm(deck, implicit_constant_step=True)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                0.01")
        self.assertTrue(_has(warns, _B3_ON, "IAUTO is 0 (stated)",
                             "It_w = 11",
                             "the deck's own DTMAX = 0.05 is replaced by DT0"))

    def test_12_the_same_deck_without_the_flag_keeps_its_DTMAX(self):
        deck = _impl_deck(extra=_auto_card(0, 11, 0, "0.0", "0.05"))
        warns, engine = self._arm(deck)
        self.assertEqual(_dt_stop_row(engine),
                         "        1.000000E-06                0.05")
        self.assertFalse(_has(warns, _B3_ON))
        self.assertFalse(_has(warns, _B3_OFF))

    def test_only_the_second_DT_STOP_cell_moves(self):
        """Flag ON vs OFF on the golden deck: exactly one line differs."""
        _w, on = self._arm(_impl_deck(), implicit_constant_step=True)
        _w, off = self._arm(_impl_deck())
        diff = [(a, b) for a, b in zip(on.splitlines(), off.splitlines())
                if a != b]
        self.assertEqual(len(on.splitlines()), len(off.splitlines()))
        self.assertEqual(diff, [("        1.000000E-06                0.01",
                                 "        1.000000E-06                   0")])

    def test_an_explicit_deck_is_silent(self):
        deck = _fixture_text("shell_explicit.k")
        warns, _engine = self._arm(deck, implicit_constant_step=True)
        self.assertFalse(_has(warns, "--implicit-constant-step"))

    def test_the_scope_helper_answers_WOULD_it_act(self):
        """``assume_flag=True`` is what the absent-card sentence asks."""
        from k2rad.writer.assembly import _constant_step_scope
        state = _dispatch(_impl_deck())
        state.is_implicit = True
        self.assertEqual(_constant_step_scope(state), (False,
                                                       "the flag is not set"))
        self.assertEqual(_constant_step_scope(state, assume_flag=True),
                         (True, ""))



_B2_ABSENT = "*CONTROL_IMPLICIT_AUTO is ABSENT"
_B2_STATED = "*CONTROL_IMPLICIT_AUTO: IAUTO=0"


class ConstantStepSentence(unittest.TestCase):
    """B2: the constant-step sentence for an implicit deck with NO
    ``*CONTROL_IMPLICIT_AUTO`` (IAUTO's default 0), one builder shared with a
    stated IAUTO 0, keyed on DT0 against ENDTIM. Warning only."""

    def _warns(self, deck, **kw):
        res, _s, _e = _convert(deck, **kw)
        return res.warnings

    def _one(self, warns, prefix):
        hits = [w for w in warns if w.startswith(prefix)]
        self.assertEqual(len(hits), 1, warns)
        return hits[0]

    def test_1_the_absent_card_is_named_with_DT0_and_no_byte_moves(self):
        res, starter, engine = _convert(_fixture_text("implicit_qstat.k"))
        hit = self._one(res.warnings, _B2_ABSENT)
        for needle in ("'Constant time step size'", "p.12-277",
                       "DT0 = 0.01", "100 steps", "ENDTIM = 1",
                       "/IMPL/DT/2 (AUTOMATIC", "It_w = 8",
                       "--implicit-constant-step caps"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit)
        root = os.path.dirname(os.path.abspath(__file__))
        for text, name in ((starter, "implicit_qstat_0000.rad"),
                           (engine, "implicit_qstat_0001.rad")):
            with open(os.path.join(root, "fixtures", "expected", name)) as fh:
                golden = fh.read()
            with self.subTest(file=name):
                self.assertEqual(text, golden)

    def test_2_DT0_zero_is_ONE_step_of_ENDTIM(self):
        hit = self._one(self._warns(_impl_deck(general=_row(1, "0.0"))),
                        _B2_ABSENT)
        self.assertIn("ONE implicit step of ENDTIM = 1", hit)
        self.assertIn("/IMPL/DTINI 0.01", hit)
        self.assertNotIn("caps the Radioss step", hit)

    def test_3_DT0_at_ENDTIM_is_one_step_that_Radioss_can_cut(self):
        hit = self._one(self._warns(_impl_deck(general=_row(1, "1.0"))),
                        _B2_ABSENT)
        self.assertIn("ONE implicit step", hit)
        self.assertIn("imp_init.F:95", hit)
        self.assertNotIn("caps the Radioss step", hit)

    def test_4_a_dynamic_DT0_above_ENDTIM_marches_under_the_1e_3_cap(self):
        deck = _impl_deck(general=_row(1, "0.01"), termination="     0.005",
                          extra="*CONTROL_IMPLICIT_DYNAMICS\n" + _row(1)
                          + "\n")
        hit = self._one(self._warns(deck), _B2_ABSENT)
        self.assertIn("1e-3 cap", hit)
        self.assertIn("ENDTIM = 0.005", hit)

    def test_5_a_stated_IAUTO_0_shares_the_builder(self):
        deck = _impl_deck(extra=_auto_card(0, 11, 0, "0.0", "0.0"))
        warns = self._warns(deck)
        hit = self._one(warns, _B2_STATED)
        self.assertIn("DT0 = 0.01", hit)
        self.assertIn("100 steps", hit)
        self.assertIn("GROWS the step above DT0", hit)
        self.assertFalse(any(w.startswith(_B2_ABSENT) for w in warns))

    def test_5b_the_stated_arm_keeps_its_ITEWIN_KFAIL_and_DTMAX_sentences(self):
        card = ("*CONTROL_IMPLICIT_AUTO\n"
                + _row(0, 11, 5, "0.0", "-5.0", "", 3) + "\n")
        hit = self._one(self._warns(_impl_deck(extra=card)), _B2_STATED)
        for needle in ("ITEWIN=5", "KFAIL=3", "DTMAX=-5 is NEGATIVE",
                       "DT0 = 0.01"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit)

    def test_5c_a_stated_DTMAX_below_DT0_is_not_told_the_step_GROWS(self):
        deck = _impl_deck(extra=_auto_card(0, 11, 0, "0.0", "0.001"))
        hit = self._one(self._warns(deck), _B2_STATED)
        self.assertIn("the deck's own DTMAX = 0.001 keeps the step at or "
                      "below DT0", hit)
        self.assertNotIn("GROWS the step above DT0", hit)
        self.assertNotIn("--implicit-constant-step", hit)

    def test_5d_under_the_flag_the_sentence_says_the_growth_is_capped(self):
        warns = self._warns(_fixture_text("implicit_qstat.k"),
                            implicit_constant_step=True)
        hit = self._one(warns, _B2_ABSENT)
        self.assertIn("can no longer GROW the step above DT0", hit)
        self.assertNotIn("GROWS the step above DT0 on easy", hit)

    def test_6_a_modal_deck_with_no_card_is_silent(self):
        warns = self._warns(_impl_deck(extra=_EIGEN_CARD))
        self.assertFalse(any(w.startswith("*CONTROL_IMPLICIT_AUTO")
                             for w in warns), warns)

    def test_6b_a_modal_deck_stating_IAUTO_0_names_its_own_engine(self):
        deck = _impl_deck(extra=_EIGEN_CARD + _auto_card(0))
        hit = self._one(self._warns(deck), _B2_STATED)
        self.assertIn("ONE /IMPL/LINEAR step", hit)
        self.assertNotIn("grows", hit.lower())

    def test_7_the_RIKS_arm_names_IMPL_DT_3(self):
        hit = self._one(self._warns(_impl_deck(_RIKS_SOLUTION),
                                    arclength_riks=True), _B2_ABSENT)
        self.assertIn("/IMPL/DT/3", hit)
        self.assertNotIn("--implicit-constant-step caps", hit)

    def test_a_negative_DT0_is_named_as_the_geometric_stiffness_option(self):
        """Vol I R17 p.12-321; reach 0 of the 136 roster keys that state the
        card, so this fixture is the only probe of the arm."""
        hit = self._one(self._warns(_impl_deck(general=_row(1, "-0.05"))),
                        _B2_ABSENT)
        self.assertIn("DT0 = -0.05 is NEGATIVE", hit)
        self.assertIn("|DT0| = 0.05", hit)
        self.assertIn("geometric-stiffness option", hit)
        self.assertIn("/IMPL/DTINI 0.01", hit)

    def test_an_explicit_deck_is_silent(self):
        warns = self._warns(_fixture_text("shell_explicit.k"))
        self.assertFalse(any(w.startswith("*CONTROL_IMPLICIT_AUTO")
                             for w in warns), warns)



_HEX_NODES = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
              (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))


def _iv_deck(imass=1, iv="node", general=True, modal=False) -> str:
    """One elastic brick. *imass* None = no ``*CONTROL_IMPLICIT_DYNAMICS``;
    *general* False = an EXPLICIT deck (no ``*CONTROL_IMPLICIT_GENERAL``);
    *iv* picks the initial-velocity spelling (one probe per registry) or
    None for none; *modal* adds ``*CONTROL_IMPLICIT_EIGENVALUE``."""
    deck = "*KEYWORD\n*NODE\n" + "".join(
        f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
        for i, (x, y, z) in enumerate(_HEX_NODES, start=1))
    deck += ("*ELEMENT_SOLID\n"
             "       1       1       1       2       3       4       5       6"
             "       7       8\n"
             "*PART\nbrick\n" + _row(1, 1, 1) + "\n"
             "*SECTION_SOLID\n" + _row(1, 2) + "\n"
             "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
             "*CONTROL_TERMINATION\n" + _row("8.0E-05") + "\n")
    if general:
        deck += "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, "1.0E-06") + "\n"
    if imass is not None:
        deck += "*CONTROL_IMPLICIT_DYNAMICS\n" + _row(imass) + "\n"
    if modal:
        deck += _EIGEN_CARD
    if iv == "node":
        deck += "*INITIAL_VELOCITY_NODE\n" + "".join(
            _row(n, "0.0", "0.0", "-1000.0") + "\n" for n in range(1, 9))
    elif iv == "set":
        deck += ("*SET_NODE_LIST\n" + _row(7) + "\n"
                 + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                 "*INITIAL_VELOCITY\n" + _row(7) + "\n"
                 + _row("0.0", "0.0", "-1000.0") + "\n")
    elif iv == "generation":
        deck += ("*INITIAL_VELOCITY_GENERATION\n"
                 + _row(1, 2, "0.0", "0.0", "0.0", "-1000.0") + "\n"
                 + _row("0.0", "0.0", "0.0", "0.0", "0.0", "1.0") + "\n")
    elif iv == "rigid":
        deck += ("*INITIAL_VELOCITY_RIGID_BODY\n"
                 + _row(1, "0.0", "0.0", "-1000.0") + "\n")
    return deck + "*END\n"


_B4_HEAD = "*CONTROL_IMPLICIT_DYNAMICS IMASS="


class ImplicitDynamicInitialVelocityDefect(unittest.TestCase):
    """B4 (i): the engine-defect warning on the emitter's own branch
    (non-modal, IMASS > 0, ``/IMPL/DYNA/2`` written) with any registered
    initial velocity - and not one byte moves."""

    def test_the_warning_describes_the_measurement(self):
        res, _s, engine = _convert(_iv_deck())
        self.assertIn("/IMPL/DYNA/2", engine)
        hits = [w for w in res.warnings if w.startswith(_B4_HEAD)]
        self.assertEqual(len(hits), 1, res.warnings)
        for needle in ("IMASS=1", "*INITIAL_VELOCITY_NODE",
                       "/IMPL/DYNA/2 0.5 0.25", "-3.0000000",
                       "kinetic energy x 9.00000", "Run this model EXPLICIT",
                       "A smaller /IMPL/DTINI is therefore NOT a fix",
                       "/IMPL/NONLIN/SOLVINFO"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hits[0])

    def test_not_one_byte_moves(self):
        """Both .rad files against the same deck with the warning stubbed
        out: the warning is text only."""
        from k2rad.writer import assembly as wa
        _r, s_on, e_on = _convert(_iv_deck())
        saved = wa._warn_implicit_dynamic_initial_velocity
        wa._warn_implicit_dynamic_initial_velocity = (
            lambda *a, **k: None)
        try:
            res_off, s_off, e_off = _convert(_iv_deck())
        finally:
            wa._warn_implicit_dynamic_initial_velocity = saved
        self.assertFalse(_has(res_off.warnings, _B4_HEAD))
        self.assertEqual(s_on, s_off)
        self.assertEqual(e_on, e_off)

    def test_absent_on_a_quasi_static_deck(self):
        res, _s, _e = _convert(_iv_deck(imass=0))
        self.assertFalse(_has(res.warnings, _B4_HEAD))

    def test_absent_without_an_initial_velocity(self):
        res, _s, _e = _convert(_iv_deck(iv=None))
        self.assertFalse(_has(res.warnings, _B4_HEAD))

    def test_absent_on_an_explicit_deck(self):
        res, _s, engine = _convert(_iv_deck(imass=None, general=False))
        self.assertNotIn("/IMPL/", engine)
        self.assertFalse(_has(res.warnings, _B4_HEAD))

    def test_absent_on_a_modal_deck(self):
        """IMASS 1 beside *CONTROL_IMPLICIT_EIGENVALUE: the modal recipe
        writes no /IMPL/DYNA/2 (the tire.k / 11.1.sbrake shape)."""
        res, _s, engine = _convert(_iv_deck(modal=True))
        self.assertNotIn("/IMPL/DYNA/2", engine)
        self.assertFalse(_has(res.warnings, _B4_HEAD))

    def test_every_registry_fires_it(self):
        for iv, kw in (("set", "(*INITIAL_VELOCITY)"),
                       ("generation", "*INITIAL_VELOCITY_GENERATION"),
                       ("rigid", "*INITIAL_VELOCITY_RIGID_BODY"),
                       ("node", "*INITIAL_VELOCITY_NODE")):
            with self.subTest(iv=iv):
                res, _s, _e = _convert(_iv_deck(iv=iv))
                self.assertTrue(_has(res.warnings, _B4_HEAD, kw),
                                res.warnings)


DEFDEF_K = """\
*KEYWORD
*TITLE
deformable-deformable implicit contact
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             0.0             0.0             1.0
       6             1.0             0.0             1.0
       7             1.0             1.0             1.0
       8             0.0             1.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
deformable part A
         1         1         1
*PART
deformable part B
         2         1         1
*SECTION_SHELL
         1         2       1.0         3
       1.0
*MAT_ELASTIC
         1   7.86e-9    210000.0      0.3
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID
         9                                                              defdef
         1         2         3         3         0         0         0         0
       0.2       0.1     0.001       0.0      10.0         0       0.01.00000E20
       1.0       1.0       0.0      0.22       1.0       1.0       1.0       1.0
*CONTROL_IMPLICIT_GENERAL
         1      0.01
*CONTROL_TERMINATION
       1.0
*END
"""

_DEFDEF_HEADS = ("Deformable-deformable contact detected",
                 "Deformable-deformable contact recipe APPLIED")


class SolvinfoRemedyHint(unittest.TestCase):
    """B4 (ii): ``/IMPL/NONLIN/SOLVINFO`` in the implicit remedy texts, once
    in the package, and never on a MODAL deck (radioss2.F:691)."""

    def test_both_deformable_arms_carry_it(self):
        for recipe, head in ((False, _DEFDEF_HEADS[0]),
                             (True, _DEFDEF_HEADS[1])):
            with self.subTest(recipe=recipe):
                res, _s, _e = _convert(DEFDEF_K,
                                       deformable_contact_recipe=recipe)
                self.assertTrue(_has(res.warnings, head,
                                     "/IMPL/NONLIN/SOLVINFO",
                                     "freimpl.F:320-321",
                                     "imp_solv.F:1715-1725"), res.warnings)

    def test_the_constant_step_and_the_engine_defect_warnings_carry_it(self):
        res, _s, _e = _convert(_impl_deck(), implicit_constant_step=True)
        self.assertTrue(_has(res.warnings, _B3_ON, "/IMPL/NONLIN/SOLVINFO"))
        res, _s, _e = _convert(_iv_deck())
        self.assertTrue(_has(res.warnings, _B4_HEAD, "/IMPL/NONLIN/SOLVINFO"))

    def test_a_modal_deck_is_not_told_to_add_it(self):
        """The 11.1.sbrake shape: the deformable-deformable warning still
        fires on a modal deck, without the hint."""
        deck = DEFDEF_K.replace("*CONTROL_TERMINATION",
                                _EIGEN_CARD + "*CONTROL_TERMINATION")
        res, _s, engine = _convert(deck)
        self.assertIn("/IMPL/LINEAR", engine)
        hits = [w for w in res.warnings if w.startswith(_DEFDEF_HEADS[0])]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertNotIn("/IMPL/NONLIN/SOLVINFO", hits[0])

    def test_the_hint_is_defined_once(self):
        from k2rad.writer.common import _SOLVINFO_HINT
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        opening = _SOLVINFO_HINT[:40]
        self.assertTrue(opening.startswith("To see WHERE an implicit run"))
        hits = []
        for dirpath, _dirs, files in os.walk(os.path.join(root, "k2rad")):
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(dirpath, name),
                              encoding="utf-8") as fh:
                        text = _collapse(re.sub(r'"\s*\n\s*"', "", fh.read()))
                    hits += [name] * text.count(opening)
        self.assertEqual(hits, ["common.py"])



def _grid_ids():
    """(x, y, z) -> node id on the 3 x 3 x 2 grid: z = 0 is 1-9, z = 1 is
    10-18, x fastest."""
    ids = {}
    nid = 0
    for z in (0, 1):
        for y in (0, 1, 2):
            for x in (0, 1, 2):
                nid += 1
                ids[(x, y, z)] = nid
    return ids


def _grid_deck(rows=((3, 0, 3, "0.0", "0.0", "0.0", "0.0"),
                     (1, 0, 1, "0.0", "0.0", "0.0", "0.0")),
               node_tc=None, mat="elastic", extra="", raw_rows=None,
               zs=None) -> str:
    """18 nodes on a 3 x 3 x 2 grid (x, y in {0, 1, 2}, z in {0, 1}), 4
    hexes, one part, and one ``*CONSTRAINED_GLOBAL`` holding *rows*
    (``TC RC DIR X Y Z TOL``) or the literal *raw_rows*. *node_tc* maps a node
    id to its ``*NODE`` (TC, RC) cells; *zs* overrides node z coordinates."""
    ids = _grid_ids()
    node_tc = node_tc or {}
    zs = zs or {}
    nodes = "*NODE\n"
    for (x, y, z), nid in sorted(ids.items(), key=lambda kv: kv[1]):
        z = zs.get(nid, z)
        nodes += f"{nid:>8}{x:>16.1f}{y:>16.1f}{z:>16.8g}"
        if nid in node_tc:
            tc, rc = node_tc[nid]
            nodes += f"{tc:>8}{rc:>8}"
        nodes += "\n"
    hexes = "*ELEMENT_SOLID\n"
    for eid, (i, j) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1)), start=1):
        ring = [ids[(i, j, 0)], ids[(i + 1, j, 0)], ids[(i + 1, j + 1, 0)],
                ids[(i, j + 1, 0)]]
        ring += [ids[(i, j, 1)], ids[(i + 1, j, 1)], ids[(i + 1, j + 1, 1)],
                 ids[(i, j + 1, 1)]]
        hexes += f"{eid:>8}{1:>8}" + "".join(f"{n:>8}" for n in ring) + "\n"
    mcard = ("*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
             if mat == "elastic" else
             "*MAT_RIGID\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
             + _row("0.0", 0, 0) + "\n" + _row("0.0") + "\n")
    body = (raw_rows if raw_rows is not None else
            "".join(_row(*r) + "\n" for r in rows))
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row("1.0") + "\n"
            + nodes + hexes
            + "*PART\ngrid\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n" + mcard
            + ("*CONSTRAINED_GLOBAL\n" + body if body else "")
            + extra + "*END\n")


def _bcs_groups(starter: str):
    """``{title: (codes, sorted node ids)}`` for every ``/BCS`` whose group is
    a ``/GRNOD/NODE`` of this deck."""
    lines = starter.splitlines()
    grnod = {}
    i = 0
    while i < len(lines):
        m = re.match(r"^/GRNOD/NODE/(\d+)$", lines[i])
        if m:
            ids = []
            j = i + 2
            while (j < len(lines) and not lines[j].startswith("/")
                   and not lines[j].startswith("#-")):
                if not lines[j].startswith("#"):
                    ids += [int(t) for t in lines[j].split()]
                j += 1
            grnod[int(m.group(1))] = ids
            i = j
            continue
        i += 1
    out = {}
    for i, ln in enumerate(lines):
        if ln.startswith("/BCS/"):
            data = lines[i + 3].split()
            out[lines[i + 1]] = (" ".join(data[:2]),
                                 sorted(grnod.get(int(data[-1]), [])))
    return out


_B5_HEAD = "*CONSTRAINED_GLOBAL: "


class ConstrainedGlobalBcs(unittest.TestCase):
    """B5: ``*CONSTRAINED_GLOBAL`` -> ``/BCS`` through the TC/RC union (default
    ON, ``--no-constrained-global``). Expectations hand-derived on the grid:
    extent 2 -> tol 2e-6; z = 0 is nodes 1-9, x = 0 is 1, 4, 7, 10, 13, 16."""

    def test_1_two_planes_sharing_nodes_give_one_BCS_per_union_code(self):
        res, starter, _e = _convert(_grid_deck())
        groups = _bcs_groups(starter)
        self.assertEqual(groups, {
            "constrained_global_001_000": ("001 000", [2, 3, 5, 6, 8, 9]),
            "constrained_global_100_000": ("100 000", [10, 13, 16]),
            "constrained_global_101_000": ("101 000", [1, 4, 7]),
        })
        seen = [n for _c, ids in groups.values() for n in ids]
        self.assertEqual(len(seen), len(set(seen)))   # no node in two /BCS
        self.assertNotIn("#-- SKIPPED: *CONSTRAINED_GLOBAL", starter)
        self.assertNotIn("CONSTRAINED_GLOBAL", res.skipped_keywords)
        self.assertIn("#-  BOUNDARY CONDITIONS (*CONSTRAINED_GLOBAL planes):",
                      starter)
        hit = [w for w in res.warnings if w.startswith(_B5_HEAD)]
        self.assertEqual(len(hit), 1, res.warnings)
        for needle in ("2 constraint plane(s)",
                       "TC 3 RC 0 on z = 0 (9 node(s) within 2e-06)",
                       "TC 1 RC 0 on x = 0 (6 node(s) within 2e-06)",
                       "12 node(s) in 3 union code(s)",
                       "Tra 101 Rot 000: 3", "WARNING 312",
                       "1e-6 x the model extent (2,",
                       "--no-constrained-global"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit[0])

    def test_2_the_tolerance_default_and_a_stated_TOL(self):
        from k2rad.writer.loads import _resolve_constrained_globals
        zs = {1: 0.0, 2: 1.5e-6, 3: 3e-6}          # extent stays 2
        for tol, expect in (("0.0", [1, 2]), ("1.0E-05", [1, 2, 3])):
            with self.subTest(tol=tol):
                state = _dispatch(_grid_deck(
                    rows=((3, 0, 3, "0.0", "0.0", "0.0", tol),), zs=zs))
                _resolve_constrained_globals(state)
                self.assertEqual(
                    sorted(n for n in state.constrained_global_tc_rc
                           if n in (1, 2, 3)), expect)
        warns = _dispatch(_grid_deck(
            rows=((3, 0, 3, "0.0", "0.0", "0.0", "-1.0"),))).warnings
        self.assertTrue(_has(warns, "TOL=-1 < 0 has no meaning",
                             "the row is NOT converted"))

    def test_3_a_NODE_cell_is_unioned_and_keeps_the_old_title(self):
        res, starter, _e = _convert(_grid_deck(node_tc={2: (2, 0)}))
        groups = _bcs_groups(starter)
        self.assertEqual(groups["node_tc_rc_011_000"], ("011 000", [2]))
        self.assertEqual(groups["constrained_global_001_000"],
                         ("001 000", [3, 5, 6, 8, 9]))
        self.assertIn("#-  BOUNDARY CONDITIONS (*NODE TC/RC cells + "
                      "*CONSTRAINED_GLOBAL planes):", starter)
        node_w = [w for w in res.warnings if w.startswith("*NODE: ")]
        glob_w = [w for w in res.warnings if w.startswith(_B5_HEAD)]
        self.assertEqual(len(node_w), 1)
        self.assertIn("*NODE: 1 node(s) state a constraint", node_w[0])
        self.assertIn("TC=2 RC=0: 1 node(s)", node_w[0])
        self.assertIn("12 node(s) in 4 union code(s)", glob_w[0])

    def test_4_the_opt_out_is_the_pre_round_6_file(self):
        from k2rad.handlers import HANDLERS
        deck = _grid_deck()
        res, s_off, e_off = _convert(deck, constrained_global=False)
        self.assertIn("CONSTRAINED_GLOBAL", res.skipped_keywords)
        self.assertNotIn("CONSTRAINED_GLOBAL",
                         [k for k, _r in res.recognized_not_emitted])
        self.assertIn("#-- SKIPPED: *CONSTRAINED_GLOBAL", s_off)
        self.assertEqual(_bcs_groups(s_off), {})
        self.assertTrue(_has(res.warnings, "NOT converted "
                             "(--no-constrained-global)", "FREE"))
        saved = HANDLERS.pop("CONSTRAINED_GLOBAL")
        try:
            _r, s_old, e_old = _convert(deck)
        finally:
            HANDLERS["CONSTRAINED_GLOBAL"] = saved
        self.assertEqual(s_off, s_old)
        self.assertEqual(e_off, e_old)

    def test_4b_node_tc_rc_off_keeps_the_planes(self):
        res, starter, _e = _convert(_grid_deck(node_tc={2: (2, 0)}),
                                    node_tc_rc_bcs=False)
        groups = _bcs_groups(starter)
        self.assertEqual(groups["constrained_global_001_000"],
                         ("001 000", [2, 3, 5, 6, 8, 9]))
        self.assertNotIn("node_tc_rc_011_000", groups)
        self.assertTrue(_has(res.warnings, "--no-node-tc-rc-bcs",
                             "FREE in the converted model"))

    def test_5_a_rigid_member_is_re_pointed_onto_its_main_node(self):
        res, starter, _e = _convert(_grid_deck(mat="rigid"))
        groups = _bcs_groups(starter)
        self.assertEqual(len(groups), 1, groups)
        (title, (codes, ids)), = groups.items()
        self.assertEqual((title, codes), ("constrained_global_101_000",
                                          "101 000"))
        self.assertEqual(len(ids), 1)
        self.assertNotIn(ids[0], range(1, 19))       # the /RBODY main node
        self.assertTrue(_has(res.warnings, _B5_HEAD, "12 node(s)",
                             "RE-POINTED onto its /RBODY main node"))

    def test_6_bad_rows_are_refused_by_name(self):
        bad = ((3, 0, 4, "0.0", "0.0", "0.0", "0.0"),
               (8, 0, 3, "0.0", "0.0", "0.0", "0.0"),
               (3, 0, 3, "0.0", "0.0", "0.0", "-1.0"))
        res, s_bad, e_bad = _convert(_grid_deck(rows=bad))
        for needle in ("DIR=4 is not 1, 2 or 3",
                       "TC=8 is not a Vol I R17 p.10-38 code",
                       "TOL=-1 < 0"):
            with self.subTest(needle=needle):
                self.assertTrue(_has(res.warnings, needle,
                                     "the row is NOT converted"))
        self.assertIn("CONSTRAINED_GLOBAL", res.skipped_keywords)
        _r, s_off, e_off = _convert(_grid_deck(rows=bad),
                                    constrained_global=False)
        self.assertEqual(s_bad, s_off)        # refused == the opt-out arm
        self.assertEqual(e_bad, e_off)
        res, starter, _e = _convert(_grid_deck(
            rows=bad[:2] + ((3, 0, 3, "0.0", "0.0", "0.0", "0.0"),)))
        self.assertEqual(_bcs_groups(starter), {
            "constrained_global_001_000": ("001 000", list(range(1, 10)))})
        self.assertEqual(sum("the row is NOT converted" in w
                             for w in res.warnings), 2)

    def test_6b_a_plane_that_selects_nothing_is_the_skipped_arm(self):
        res, starter, _e = _convert(_grid_deck(
            rows=((3, 0, 3, "0.0", "0.0", "5.0", "0.0"),)))
        self.assertEqual(_bcs_groups(starter), {})
        self.assertIn("CONSTRAINED_GLOBAL", res.skipped_keywords)
        self.assertIn("#-- SKIPPED: *CONSTRAINED_GLOBAL", starter)
        self.assertTrue(_has(res.warnings, "passes within its tolerance of "
                             "any node", "NOTHING is converted"))

    def test_8_the_registries(self):
        from k2rad.handlers import HANDLERS
        from k2rad.assembly import _NO_ID_KEYWORDS, _POINT_BEARING
        self.assertIn("CONSTRAINED_GLOBAL", HANDLERS)
        self.assertIn("CONSTRAINED_GLOBAL", _NO_ID_KEYWORDS)
        # refused under a transform instead (the handler), so not "moved"
        self.assertNotIn("CONSTRAINED_GLOBAL", _POINT_BEARING)

    def test_8b_a_card_inside_a_transformed_include_is_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        child = _grid_deck().replace("*KEYWORD\n", "*KEYWORD\n", 1)
        with open(os.path.join(tmp.name, "child.k"), "w") as fh:
            fh.write(child.replace("*CONTROL_TERMINATION\n"
                                   + _row("1.0") + "\n", ""))
        main = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row("1.0") + "\n"
                "*DEFINE_TRANSFORMATION\n" + _row(1) + "\n"
                + f"{'TRANSL':<10}" + "".join(f"{v:>10}" for v in
                                               ("0.0", "0.0", "5.0")) + "\n"
                "*INCLUDE_TRANSFORM\nchild.k\n\n\n\n" + _row(1) + "\n*END\n")
        path = os.path.join(tmp.name, "main.k")
        with open(path, "w") as fh:
            fh.write(main)
        res = convert(path, write_log=False)
        self.assertTrue(_has(res.warnings, "inside a geometrically "
                             "transformed *INCLUDE_TRANSFORM", "NOT converted"))
        self.assertIn("CONSTRAINED_GLOBAL", res.skipped_keywords)
        with open(res.starter_path) as fh:
            self.assertEqual(_bcs_groups(fh.read()), {})

    def test_9_comment_rows_between_data_rows(self):
        raw = (_row(3, 0, 3, "0.0", "0.0", "0.0", "0.0") + "\n$\n"
               "$--- a comment between the rows\n$\n"
               + _row(1, 0, 1, "0.0", "0.0", "0.0", "0.0") + "\n")
        state = _dispatch(_grid_deck(raw_rows=raw))
        self.assertEqual(len(state.constrained_globals), 2)
        _res, starter, _e = _convert(_grid_deck(raw_rows=raw))
        self.assertIn("constrained_global_100_000", _bcs_groups(starter))

    def test_the_MPC_refusal_sees_a_GLOBAL_BCS(self):
        """A5 x B5: a /BCS from a plane on the MPC's DOF refuses the card,
        naming its source (grep every consumer of a new producer)."""
        extra = ("*CONSTRAINED_LINEAR_GLOBAL\n" + _row(1) + "\n"
                 + _row(2, 3, "1.0") + "\n" + _row(11, 3, "-1.0") + "\n")
        res, starter, _e = _convert(_grid_deck(extra=extra))
        self.assertNotIn("/MPC/", starter)
        self.assertTrue(_has(res.warnings, "NOT converted to /MPC",
                             "node 2 DOF 3 already carries "
                             "*CONSTRAINED_GLOBAL /BCS"))

    def test_the_rbody_WARNING_312_note_sees_a_GLOBAL_BCS(self):
        """The shell-to-solid tie's WARNING-312 pre-warning reads the node
        set of every /BCS producer; its fibre on a plane must be named, with
        the plane named as the source - and without the plane, nothing."""
        pts = {1: (0, 0, 0), 2: (10, 0, 0), 3: (10, 10, 0), 4: (0, 10, 0),
               11: (0, 0, 10), 12: (10, 0, 10), 13: (10, 10, 10),
               14: (0, 10, 10), 5: (0, 0, 20), 6: (10, 0, 20),
               7: (10, 10, 20)}

        def deck(plane):
            return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                    "*NODE\n" + "".join(
                        f"{i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
                        for i, (x, y, z) in sorted(pts.items()))
                    + "*ELEMENT_SOLID\n"
                    + _row(1, 2, 1, 2, 3, 4, 11, 12, 13, 14) + "\n"
                    "*ELEMENT_SHELL\n" + _row(2, 1, 5, 6, 7, 7) + "\n"
                    "*PART\nshell\n" + _row(1, 1, 1) + "\n"
                    "*PART\nbrick\n" + _row(2, 2, 1) + "\n"
                    "*SECTION_SHELL\n" + _row(1, 2) + "\n"
                    + _row(1.0, 1.0, 1.0, 1.0) + "\n"
                    "*SECTION_SOLID\n" + _row(2, 1) + "\n"
                    "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                    "*SET_NODE_LIST\n" + _row(9) + "\n" + _row(1, 2, 3) + "\n"
                    "*CONSTRAINED_SHELL_TO_SOLID\n" + _row(5, 9) + "\n"
                    + ("*CONSTRAINED_GLOBAL\n"
                       + _row(3, 0, 3, "0.0", "0.0", "0.0", "0.0") + "\n"
                       if plane else "")
                    + "*END\n")
        res, _s, _e = _convert(deck(True))
        self.assertTrue(_has(res.warnings, "also carry a /BCS from *NODE "
                             "TC/RC, *CONSTRAINED_GLOBAL or *BOUNDARY_SPC_*",
                             "WARNING ID 312"))
        res, _s, _e = _convert(deck(False))
        self.assertFalse(_has(res.warnings, "WARNING ID 312 INCOMPATIBLE"))

    _F = "F:/dynaexamples_r14_ton-mm-s"

    @unittest.skipUnless(os.path.isdir("F:/dynaexamples_r14_ton-mm-s"),
                         "the R14 corpus on F: is not mounted")
    def test_7_the_corpus_carriers_select_LS_DYNAs_own_nodes(self):
        """Read-only: converted from F: into a temp dir. LS-DYNA's own d3hsp
        'nodal spc summary' lists ids 1-305 on the ex_27 twin and 36 x
        001/111 + 18 x 111/111 on metal-cutting."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ex27 = os.path.join(self._F, "introduction", "Introduction",
                            "example-27", "ex_27_solid_elform_2_rigidwall_"
                            "constrained_nodes_implicit.k")
        res = convert(ex27, output_stem=os.path.join(tmp.name, "e27"),
                      write_log=False)
        with open(res.starter_path) as fh:
            groups = _bcs_groups(fh.read())
        self.assertEqual({t: g for t, g in groups.items()
                          if t.startswith("constrained_global")},
                         {"constrained_global_001_000":
                          ("001 000", list(range(1, 306)))})
        self.assertIn("inert_probe_fix", groups)      # the implicit probe
        mc = os.path.join(self._F, "efg", "metal-cutting", "main.k")
        res = convert(mc, output_stem=os.path.join(tmp.name, "mc"),
                      write_log=False)
        with open(res.starter_path) as fh:
            groups = _bcs_groups(fh.read())
        self.assertEqual({t: (c, len(ids)) for t, (c, ids) in groups.items()
                          if t.startswith("constrained_global")},
                         {"constrained_global_001_111": ("001 111", 36),
                          "constrained_global_111_111": ("111 111", 18)})



def _r1fix(n1=100, n1_xyz=(5.0, 5.0, 1.0), tie=True, second_sheet=True,
           ts="1.5", extra_elems="") -> str:
    """The rule-1 probe: sheet part 1 at z 0 and sheet part 2 at z 2 (2 x 2
    quads of 10 mm each; nodes 1-9 / 11-19, shells 1-4 / 11-14, t 1.0), and a
    weld part 3 = *SECTION_BEAM ELFORM 9 (TS1 = TS2 = *ts*) + *MAT_SPOTWELD
    whose ONE beam names node *n1* only. The sheet DISTANCE (2.0), the sheet
    thickness (1.0) and TS1 (1.5) all differ, so a test tells the manual's
    projection rule (L = 2.0) from the two alternatives."""
    nodes = []
    for base, z in ((0, 0.0), (10, 2.0)):
        k = 0
        for y in (0.0, 10.0, 20.0):
            for x in (0.0, 10.0, 20.0):
                k += 1
                nodes.append((base + k, x, y, z))
    nodes.append((100, *n1_xyz))
    txt = "*KEYWORD\n*CONTROL_TERMINATION\n" + _row("1.0e-3") + "\n*NODE\n"
    txt += "".join(f"{i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
                   for i, x, y, z in nodes)
    txt += "*ELEMENT_SHELL\n"
    for base, pid in ((0, 1), (10, 2)):
        if pid == 2 and not second_sheet:
            continue
        for eid, (a, b, c, d) in enumerate(((1, 2, 5, 4), (2, 3, 6, 5),
                                             (4, 5, 8, 7), (5, 6, 9, 8)),
                                            start=1):
            txt += (f"{base + eid:>8}{pid:>8}{base + a:>8}{base + b:>8}"
                    f"{base + c:>8}{base + d:>8}\n")
    txt += extra_elems
    txt += ("*ELEMENT_BEAM\n" + f"{1:>8}{3:>8}{n1:>8}{0:>8}{0:>8}\n"
            "*PART\nsheet 1\n" + _row(1, 1, 1) + "\n"
            "*PART\nsheet 2\n" + _row(2, 1, 1) + "\n"
            "*PART\nweld\n" + _row(3, 3, 3) + "\n"
            "*SECTION_SHELL\n" + _row(1, 2) + "\n"
            + _row("1.0", "1.0", "1.0", "1.0") + "\n"
            "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
            "*SECTION_BEAM\n" + _row(3, 9, "1.0", 2, 1) + "\n"
            + _row(ts, ts, "0.0", "0.0") + "\n"
            "*MAT_SPOTWELD\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
            + _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0") + "\n"
            "*SET_PART_LIST\n" + _row(200) + "\n" + _row(1, 2) + "\n")
    if tie:
        txt += ("*CONTACT_TIED_SHELL_EDGE_TO_SURFACE\n"
                + _row(3, 200, 3, 2) + "\n" + _row() + "\n" + _row() + "\n")
    return txt + "*END\n"


def _spring_rows(starter: str, sid: int):
    """The data rows of ``/SPRING/<sid>``."""
    lines = starter.splitlines()
    out = []
    if f"/SPRING/{sid}" not in lines:
        return out
    i = lines.index(f"/SPRING/{sid}") + 1
    while i < len(lines) and not lines[i].startswith(("/", "#-")):
        if not lines[i].startswith("#"):
            out.append(lines[i])
        i += 1
    return out


def _tied_slave_ids(starter: str):
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("tied_") and ln.endswith("_slave"):
            ids = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith(("/", "#")):
                ids += [int(t) for t in lines[j].split()]
                j += 1
            return ids
    return None


_R1_HEAD = "*ELEMENT_BEAM 1 (part 3: *SECTION_BEAM ELFORM 9, *MAT_SPOTWELD)"
_R2_HEAD = "--beam-contact-secondary: contact side 3 (type 3) gains"


class SpotweldOptInPair(unittest.TestCase):
    """B6: ``--spotweld-node-synthesis`` (rule 1) and
    ``--beam-contact-secondary`` (rule 2), both default OFF, on the r1fix
    probe - the four arms of the spec, hand-derived."""

    def _arm(self, **kw):
        res, starter, engine = _convert(_r1fix(**kw.pop("fix", {})), **kw)
        return res.warnings, starter, engine

    def test_both_off_is_todays_refusal_with_the_lever_named(self):
        warns, starter, _e = self._arm()
        self.assertTrue(_has(warns, "*MAT_SPOTWELD part 3: zero-length (or "
                             "node-less) spotweld beams",
                             "1 weld(s) NOT converted"))
        self.assertEqual(_spring_rows(starter, 3), [])
        self.assertIsNone(_tied_slave_ids(starter))
        self.assertTrue(_has(warns, "ssid=3 sstyp=3 resolved to no nodes at "
                             "all", "Part(s) [3] of this side carry only "
                             "*ELEMENT_BEAM elements",
                             "--beam-contact-secondary does"))

    def test_rule_1_places_the_second_node_by_the_manuals_projection(self):
        warns, starter, _e = self._arm(spotweld_node_synthesis=True)
        rows = _spring_rows(starter, 3)
        self.assertEqual(rows, ["         1       100       101         0"])
        node_rows = {int(ln[:10]): ln for ln in starter.splitlines()
                     if re.match(r"^\s+\d+\s+-?[\d.]", ln)
                     and ln[:10].strip() in ("100", "101")}
        self.assertEqual(node_rows[100].split()[1:], ["5", "5", "0"])
        self.assertEqual(node_rows[101].split()[1:], ["5", "5", "2"])
        hit = [w for w in warns if w.startswith(_R1_HEAD)]
        self.assertEqual(len(hit), 1, warns)
        for needle in ("moved from (5, 5, 1) to (5, 5, 0) on shell 1 (part 1)",
                       "new element-free node 101 created at (5, 5, 2) on "
                       "shell 11 (part 2)", "weld length 2.",
                       "WITHOUT --beam-contact-secondary", "7.64x"):
            with self.subTest(needle=needle):
                self.assertIn(needle, hit[0])
        # L = the sheet distance 2.0, not the thickness 1.0 or TS1 1.5:
        # K_axial = E*A/L with A = pi*1.5^2/4 = 1.76715
        self.assertTrue(_has(warns, "K_axial=E·A/L=185550",
                             "K_shear=G·A/L=71365.5"))
        self.assertIsNone(_tied_slave_ids(starter))      # the tie still drops

    def test_rule_2_puts_the_beam_node_on_the_tie(self):
        warns, starter, _e = self._arm(beam_contact_secondary=True)
        self.assertEqual(_tied_slave_ids(starter), [100])
        self.assertEqual(_spring_rows(starter, 3), [])
        self.assertTrue(_has(warns, _R2_HEAD, "1 node(s)", "part(s) [3]"))
        self.assertFalse(_has(warns, "--beam-contact-secondary does"))

    def test_both_flags(self):
        warns, starter, _e = self._arm(spotweld_node_synthesis=True,
                                       beam_contact_secondary=True)
        self.assertEqual(_spring_rows(starter, 3),
                         ["         1       100       101         0"])
        self.assertEqual(_tied_slave_ids(starter), [100, 101])
        hit = [w for w in warns if w.startswith(_R1_HEAD)]
        self.assertTrue(hit and "MEASURED with both flags" in hit[0], warns)
        self.assertTrue(_has(warns, _R2_HEAD, "2 node(s)"))

    def test_every_rule_1_refusal_is_byte_identical_to_rule_1_off(self):
        shell_node = ("*ELEMENT_SHELL\n" + f"{50:>8}{1:>8}{100:>8}{2:>8}"
                      f"{5:>8}{4:>8}\n")
        cases = (
            ({"extra_elems": shell_node}, "also belongs to another element"),
            ({"tie": False}, "no *CONTACT_TIED_*/_SPOTWELD names part 3"),
            ({"n1_xyz": (5.0, 5.0, 0.0)}, "lies ON a reference sheet"),
            ({"second_sheet": False}, "no reference segment lies on the "
                                      "other side"),
        )
        for fix, needle in cases:
            with self.subTest(needle=needle):
                w_on, s_on, e_on = self._arm(fix=dict(fix),
                                             spotweld_node_synthesis=True)
                w_off, s_off, e_off = self._arm(fix=dict(fix))
                self.assertTrue(_has(w_on, "--spotweld-node-synthesis:",
                                     "was NOT given a second one", needle),
                                w_on)
                self.assertEqual(s_on, s_off)
                self.assertEqual(e_on, e_off)

    def test_rule_2_on_rigid_beam_nodes_changes_nothing(self):
        """The mainboltaexpl shape: the side's only part is a spotweld beam
        whose two nodes are *CONSTRAINED_NODAL_RIGID_BODY members. The walk
        gains them, the rigid filter removes them again: no gain warning, the
        drop names the rigid nodes, both .rad identical to the flag-off arm,
        and the flag-off arm is NOT pointed at the flag."""
        pts = {1: (0, 0, 0), 2: (0, 0, 1), 20: (1, 0, 0), 21: (0, 1, 0),
               22: (1, 0, 1), 23: (0, 1, 1)}
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row("1.0e-3") + "\n"
                "*NODE\n" + "".join(f"{i:>8}{x:>16.4f}{y:>16.4f}{z:>16.4f}\n"
                                    for i, (x, y, z) in sorted(pts.items()))
                + "*ELEMENT_BEAM\n" + f"{1:>8}{5:>8}{1:>8}{2:>8}{0:>8}\n"
                "*PART\nbolt weld\n" + _row(5, 5, 5) + "\n"
                "*SECTION_BEAM\n" + _row(5, 9, "1.0", 2, 1) + "\n"
                + _row("1.0", "1.0", "0.0", "0.0") + "\n"
                "*MAT_SPOTWELD\n" + _row(5, 7.85e-9, 210000.0, 0.3) + "\n"
                + _row("0.0") + "\n"
                "*SET_NODE_LIST\n" + _row(110) + "\n" + _row(1, 20, 21) + "\n"
                "*SET_NODE_LIST\n" + _row(120) + "\n" + _row(2, 22, 23) + "\n"
                "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(501, 0, 110) + "\n"
                "*CONSTRAINED_NODAL_RIGID_BODY\n" + _row(502, 0, 120) + "\n"
                "*SET_PART_LIST\n" + _row(10013) + "\n" + _row(5) + "\n"
                "*CONTACT_AUTOMATIC_GENERAL_ID\n" + _row(10013) + "\n"
                + _row(10013, 0, 2, 0) + "\n" + _row() + "\n" + _row() + "\n"
                "*END\n")
        r_off, s_off, e_off = _convert(deck)
        r_on, s_on, e_on = _convert(deck, beam_contact_secondary=True)
        self.assertEqual(s_on, s_off)
        self.assertEqual(e_on, e_off)
        self.assertFalse(_has(r_on.warnings,
                              "--beam-contact-secondary: contact side"))
        self.assertTrue(_has(r_on.warnings, "ssid=10013 sstyp=2 resolved to 2 "
                             "node(s) and ALL 2 of them belong to a rigid "
                             "body"))
        self.assertTrue(_has(r_on.warnings, "--beam-contact-secondary was "
                             "passed but no emitted contact side"))
        self.assertTrue(_has(r_off.warnings, "ssid=10013 sstyp=2 resolved to "
                             "no nodes at all"))
        self.assertFalse(_has(r_off.warnings, "--beam-contact-secondary does"))

    def test_rule_2_takes_a_truss_part_too(self):
        deck = _r1fix().replace(
            "*SECTION_BEAM\n" + _row(3, 9, "1.0", 2, 1) + "\n"
            + _row("1.5", "1.5", "0.0", "0.0") + "\n"
            "*MAT_SPOTWELD\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
            + _row("0.0", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0") + "\n",
            "*SECTION_BEAM\n" + _row(3, 3, "1.0", 2, 1) + "\n"
            + _row("1.0") + "\n"
            "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n").replace(
            f"{1:>8}{3:>8}{100:>8}{0:>8}{0:>8}\n",
            f"{1:>8}{3:>8}{100:>8}{5:>8}{0:>8}\n")
        _r, starter, _e = _convert(deck, beam_contact_secondary=True)
        self.assertEqual(_tied_slave_ids(starter), [5, 100])
        _r, starter, _e = _convert(deck)
        self.assertIsNone(_tied_slave_ids(starter))

    def test_the_tied_walk_IS_the_shared_walk(self):
        """The refactor's equivalence, flag OFF, over a part holding one
        element of every family the walk takes (shell, solid, thick shell,
        1-D seatbelt, SPH) - and a beam, which it must NOT take."""
        from k2rad.state import (BeamElem, SeatbeltElem, ShellElem, SolidElem,
                                 SphCell, TshellElem)
        from k2rad.writer.contacts import _contact_part_nodes, _tied_slave_nids
        state = ConversionState()
        state.shell_elems.append(ShellElem(1, 7, [1, 2, 3, 4]))
        state.solid_elems.append(SolidElem(2, 7, [5, 6, 7, 8, 9, 10, 11, 12]))
        state.tshell_elems.append(TshellElem(3, 7, [13, 14, 15, 16, 17, 18,
                                                   19, 20]))
        state.seatbelt_elems.append(SeatbeltElem(4, 7, 21, 22))
        state.sph_elems.append(SphCell(23, 7))
        state.beam_elems.append(BeamElem(5, 7, 24, 25, 0))
        want = list(range(1, 24))
        self.assertEqual(_tied_slave_nids(state, 7, 3), want)
        self.assertEqual(sorted(_contact_part_nodes(state, 7)), want)
        state.options.beam_contact_secondary = True
        self.assertEqual(_tied_slave_nids(state, 7, 3), want + [24, 25])
        self.assertEqual(state.beam_side_gain, {7: {24, 25}})

    def test_the_docstring_no_longer_claims_a_shared_walk_it_did_not_have(self):
        from k2rad.writer.contacts import _contact_part_nodes
        doc = _collapse(_contact_part_nodes.__doc__)
        self.assertIn("since R14 triage round 6 - ``_tied_slave_nids``", doc)



# ═════════════════════════════════════════════════════════════════════════════
# PART B: wiring and the retracted statements
# ═════════════════════════════════════════════════════════════════════════════

class Round6FlagWiringB(unittest.TestCase):
    """Every new Part-B lever reaches the parser, the API, the GUI and the
    README (the round-5 ``Round5FlagWiring`` checks, for this part's list)."""

    #: default-ON opt-outs (README and the GUI summary carry the --no- form)
    _FLAGS = {
        "--zero-tolerance-ectol": "zero_tolerance_ectol",
        "--constrained-global": "constrained_global",
    }
    #: opt-in levers, each with its OWN README heading
    _OPT_IN_FLAGS = {
        "--implicit-constant-step": "implicit_constant_step",
        "--spotweld-node-synthesis": "spotweld_node_synthesis",
        "--beam-contact-secondary": "beam_contact_secondary",
    }
    _HELP_FIGURES = {
        "--zero-tolerance-ectol": ("+7.36 % -> -0.54 %", "+582.00 %",
                                   "-99.87 %", "p.12-354"),
        "--constrained-global": ("305, 54, 24737 nodes", "p.10-38"),
        "--implicit-constant-step": ("+74.1 % -> -0.9 %", "3.81x",
                                     "16.07 % -> 1.16 %", "75 -> 168",
                                     "-0.54 % -> -4.36 %",
                                     "33 R14 deck keys on 22 emitted models"),
        "--spotweld-node-synthesis": ("7.64x", "+82.0 %", "p.19-3"),
        "--beam-contact-secondary": ("4 R14 deck keys on 4 emitted models",),
        "--derived-gapmin": ("-91 %", "ZERO campaign verdict promotions",
                             "i7for3.F:762-770"),
    }

    def _readme(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_every_flag_is_a_parser_option(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        for flag in self._FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts)
                self.assertIn("--no-" + flag[2:], opts)
        for flag in self._OPT_IN_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts)

    def test_README_prose_and_own_headings(self):
        readme = self._readme()
        body = [ln for ln in readme.splitlines()
                if not re.match(r"^\s*[-*]?\s*\[.*\]\(#.*\)\s*$", ln)]
        for flag in self._FLAGS:
            neg = "--no-" + flag[2:]
            with self.subTest(flag=neg):
                self.assertTrue(any(neg in ln for ln in body))
        headings = re.findall(r"^#{2,4}\s+(.*)$", readme, re.M)
        for flag in self._OPT_IN_FLAGS:
            with self.subTest(flag=flag):
                self.assertTrue(any(flag in h for h in headings),
                                f"{flag} has no README section of its own")

    def test_the_help_renders_and_carries_the_measured_numbers(self):
        from k2rad import cli
        text = cli.build_parser().format_help()
        flat = _collapse(text)
        for flag, figures in self._HELP_FIGURES.items():
            self.assertIn(flag, text)
            for figure in figures:
                with self.subTest(flag=flag, figure=figure):
                    self.assertIn(figure, flat)

    def test_the_gui_wires_every_lever_end_to_end(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        base = dict(ground_springs=False, ground_spring_k_text="",
                    soften_stfac_text="")
        cases = ([(f, n, False, "--no-" + f[2:]) for f, n in
                  self._FLAGS.items()]
                 + [(f, n, True, f) for f, n in self._OPT_IN_FLAGS.items()])
        for flag, name, value, spelled in cases:
            with self.subTest(name=name):
                kw = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), **base, **{name: value})
                self.assertIs(kw[name], value)
                captured = []
                app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
                app._append = captured.append
                k2rad_gui.ConverterGUI._describe_options(app, kw)
                self.assertIn(spelled, "".join(captured))
                kw_def = k2rad_gui.build_convert_kwargs(
                    path, "", ("Mg", "mm", "s"), **base)
                self.assertIs(kw_def[name], not value)
                captured_def = []
                app._append = captured_def.append
                k2rad_gui.ConverterGUI._describe_options(app, kw_def)
                self.assertNotIn(spelled, "".join(captured_def))

    def test_every_lever_reaches_convert_and_ConvertOptions(self):
        import inspect
        from k2rad.state import ConvertOptions
        sig = inspect.signature(convert).parameters
        fields = set(ConvertOptions.__dataclass_fields__)
        for name, default in ([(n, True) for n in self._FLAGS.values()]
                              + [(n, False)
                                 for n in self._OPT_IN_FLAGS.values()]):
            with self.subTest(name=name):
                self.assertIn(name, sig)
                self.assertIs(sig[name].default, default)
                self.assertIn(name, fields)
                self.assertIs(getattr(ConvertOptions(), name), default)


#: Statements Part B of round 6 measured (or read) to be wrong or retired.
#: CHANGELOG may quote them (the history); no other shipped text may.
_RETRACTED_ROUND_6_B = (
    # B7.4: the constant-step census (98 / 76 counted modal keys)
    "98 deck keys on 76 emitted models",
    "81 of the 98",
    "13 are unmeasured",
    # B7.5: the ex_02 family's way back is not a step-control cell
    "the family's way back to NORMAL is the step-scale cell",
    "the family's way back is the step-SCALE cell",
    # B7.1: twobar's END value is not an improvement
    "twobar improves",
    "twobar better",
    "`twobar` better",
    "1 better, 3 worse",
    "-5.60 % (better)",
    "The derived `Gapmin` IS.",
    "was measured down to −5.6 % by changing the derived",
    "0.005 is -5.6 %",
    # B4 (preventive): the DOF dump EXISTS (/IMPL/NONLIN/SOLVINFO)
    "DOF dump is a solver limitation",
    "DOF dump is a SOLVER LIMITATION",
    "freimpl.F:250-259",
    "only imp_solv.F:1978 prints a node",
    "What is missing is a DOF-level residual dump",
    # B7.2: the thermal-weld refusal's retired absolutes and count
    "about 33 on 05_1's 425-element seam",
    "which every carrier of this keyword hits first",
    "no Radioss counterpart at all — /HEAT/MAT holds ONE",
    # B6: the one-walk docstring that was false
    "ONE walk shared by ``_resolve_contact_slave``, ``_tied_slave_nids``",
    # B5: rule (a) re-points, it does not drop
    "whose members rule (a) drops from the TC/RC set anyway",
)


class Round6RetractedStatementsB(unittest.TestCase):
    """The round-4/5 four-test shape, for Part B's retired spellings."""

    def test_no_shipped_text_carries_a_retracted_statement(self):
        for rel, joined in _SHIPPED_TEXTS():
            for needle in _RETRACTED_ROUND_6_B:
                with self.subTest(file=rel, needle=needle):
                    self.assertNotIn(_collapse(needle), joined)

    def test_the_guard_fires_on_each_retracted_spelling(self):
        for needle in _RETRACTED_ROUND_6_B:
            with self.subTest(needle=needle):
                fake = ('x ' + needle.replace(" ", ' "\n            "') + ' y')
                self.assertIn(_collapse(needle), _collapse(
                    re.sub(r'"\s*\n\s*"', "", fake)))

    def test_a_PREFIX_of_a_retracted_string_still_fires(self):
        for needle in _RETRACTED_ROUND_6_B:
            with self.subTest(needle=needle):
                self.assertIn(_collapse(needle[:max(8, len(needle) // 2)]),
                              _collapse(needle))

    def test_the_replacements_really_are_shipped(self):
        texts = dict(_SHIPPED_TEXTS())
        pairs = (
            ("k2rad/writer/common.py", "/IMPL/NONLIN/SOLVINFO"),
            ("k2rad/writer/contacts.py", "THE COST LAW"),
            ("k2rad/writer/contacts.py",
             "7 now have a measured arm and 8 are still UNJUDGEABLE"),
            ("k2rad/handlers.py", "/IMPFLUX DOES have a volumetric form"),
            ("k2rad/handlers.py", "ZERO-HEATING"),
            ("k2rad/writer/loads.py", "rule (a) RE-POINTS the members' cells"),
            ("k2rad/writer/contacts.py",
             "since R14 triage round 6 - ``_tied_slave_nids``"),
            ("ROADMAP.md", "What round 6 deliberately does NOT close"),
            ("ROADMAP.md", "50 deck keys on 34 emitted models"),
            ("ROADMAP.md", "ANSWERED in round 6, and the answer is the ENGINE"),
            ("ROADMAP.md", "The DOF-level residual dump is "
             "`/IMPL/NONLIN/SOLVINFO`; round 6 ran it"),
            ("README.md", "--implicit-constant-step"),
            ("README.md", "--no-constrained-global"),
            ("README.md", "--no-zero-tolerance-ectol"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])

    def test_the_roadmap_carries_a_round_6_column(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ROADMAP.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(
            "| # | class | decks | closed by round 1 | round 2 | round 3 | "
            "round 4 | round 5 | round 6 |", text)
        self.assertIn(
            "| family | decks | death | verdict after round 3 | round 4 | "
            "round 5 | round 6 |", text)
        self.assertIn("What round 6 closes, and what it does NOT", text)
        # the round-5 pins the census correction had to keep
        self.assertIn("152 811", text)
        self.assertIn("1 888", text)


def _text_units():
    """``(file, unit)`` for every blank-line-separated unit of every shipped
    text, adjacent string literals JOINED first and each unit collapsed. A
    ``#`` comment block (state.py's ConvertOptions notes) is one unit, since
    its lines are not blank."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rels = ["README.md", "ROADMAP.md", "k2rad_gui.py"]
    for dirpath, _dirs, files in os.walk(os.path.join(root, "k2rad")):
        if "__pycache__" in dirpath:
            continue
        rels += [os.path.relpath(os.path.join(dirpath, n), root)
                 for n in sorted(files) if n.endswith(".py")]
    out = []
    for rel in rels:
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            text = re.sub(r'"\s*\n\s*"', "", fh.read())
        for unit in re.split(r"\n\s*\n", text):
            out.append((rel, _collapse(unit)))
    return out


_END_VALUE = re.compile(r"[-−]5\.60? ?%")
_HISTORY = re.compile(r"[-−]91 ?%")


def _end_value_violations(units):
    return [(rel, u[:120]) for rel, u in units
            if "twobar" in u and _END_VALUE.search(u)
            and not _HISTORY.search(u)]


class Round6TwobarEndValueCarriesItsHistory(unittest.TestCase):
    """The paired-figure rule (B7.1): every shipped text unit that still
    states twobar's END value (-5.60 % / -5.6 %) states its history (-91 %
    at the first impact) in the same unit - a final-state number is not
    evidence without its history. CHANGELOG is the history and excluded."""

    def test_every_unit_pairs_the_end_value_with_its_history(self):
        units = _text_units()
        checked = [u for rel, u in units
                   if "twobar" in u and _END_VALUE.search(u)]
        self.assertGreaterEqual(len(checked), 8, "the rule matched too little")
        self.assertEqual(_end_value_violations(units), [])

    def test_the_rule_fails_a_unit_without_the_history(self):
        bad = [("x", _collapse("twobar reads -5.60 % against its reference."))]
        good = [("x", _collapse("twobar ends at -5.60 % but reads -91 % at "
                                "the first impact."))]
        self.assertEqual(len(_end_value_violations(bad)), 1)
        self.assertEqual(_end_value_violations(good), [])
        uni = [("x", "twobar ends at −5.6 % (history −91 %)")]
        self.assertEqual(_end_value_violations(uni), [])


if __name__ == "__main__":
    unittest.main()
