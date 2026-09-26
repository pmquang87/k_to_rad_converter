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
    }
    #: figures each flag's --help must carry (matched on the collapsed render)
    _HELP_FIGURES = {
        "--initial-void-floor": ("1095 cycles", "2936 cycles",
                                 "hm_read_mat06.F:154"),
        "--weld-exponents": ("2.460e-4", "+29.4 %", "0.899x",
                             "hm_read_prop13.F:1169-1170"),
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
            ("README.md", "`--no-weld-exponents`"),
            ("k2rad/writer/loads.py", "The deck names these nodes but does "
             "not define them: it is a fragment"),
            ("k2rad/cli.py", "which nothing catches (chkmsin.F:53 aborts "
             "only on MS < 0; accele.F:67-80 then freezes the node's "
             "velocity)"),
            ("README.md", "the screen is the node's OWN mass, not element "
             "incidence"),
        )
        for rel, needle in pairs:
            with self.subTest(file=rel, needle=needle):
                key = next((k for k in texts
                            if k.replace("\\", "/") == rel), None)
                self.assertIsNotNone(key, f"{rel} was not scanned")
                self.assertIn(_collapse(needle), texts[key])


if __name__ == "__main__":
    unittest.main()
