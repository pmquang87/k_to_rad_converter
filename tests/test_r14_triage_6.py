"""Tests for the R14 CAMPAIGN TRIAGE batch, round 6 — PART A:

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

def _aniso_deck(c=(5940.0, 760.0, 5940.0, 980.0, 980.0, 2270.0),
                c44=2590.0, c55=1180.0, c66=1180.0, c14=0.0) -> str:
    """One brick on *MAT_ANISOTROPIC_ELASTIC 3 — 11.1.sbrake's pad by
    default (C11 = C22 5940, C12 760, C13 = C23 980, C33 2270, C44 2590,
    C55 = C66 1180, every coupling cell 0, AOPT 0)."""
    nodes = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0e-3) + "\n"
            "*NODE\n"
            + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                      for i, (x, y, z) in enumerate(nodes, start=1))
            + "*ELEMENT_SOLID\n"
            + "".join(f"{v:>8}" for v in (1, 5, 1, 2, 4, 3, 5, 6, 8, 7))
            + "\n*PART\npad\n" + _row(5, 1, 3) + "\n"
            "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            "*MAT_ANISOTROPIC_ELASTIC_TITLE\npad\n"
            + _row(3, 2.51e-9, *c) + "\n"
            + _row(c14, 0.0, 0.0, c44, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(c55, 0.0, 0.0, 0.0, 0.0, 0.0, c66, 0.0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1, 0) + "\n"
            + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            "*END\n")


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
        for needle in ("converted EXACTLY", "EA 5496.34", "EC 1983.31",
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
            ("k2rad/handlers.py", "the material IS orthotropic and is "
             "converted EXACTLY through the *MAT_ORTHOTROPIC_ELASTIC path"),
            ("k2rad/handlers.py", "state it as *MAT_ORTHOTROPIC_ELASTIC in "
             "those axes (AOPT)"),
            ("README.md", "converted **EXACTLY through the orthotropic path "
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


if __name__ == "__main__":
    unittest.main()
