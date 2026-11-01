"""Tests for the CARDSTACK PIPELINE batch (k2rad) — K-0P, the front-end
plumbing every later group of the batch codes against:

  (a) *CONTROL_TERMINATION ENDCYC / DTMIN / ENDENG / ENDMAS are read into
      ControlTermination (they used to be sliced and dropped)
  (b) *CONTROL_OUTPUT IKEDIT (card 1 field 7) is read into ControlOutput
  (c) *CONTROL_UNITS has a real handler (it was skipped); ``--units`` /
      ``convert(units=...)`` default to None and convert() resolves the
      /BEGIN labels after parsing: the explicit units if given, else the
      card's LENGTH / TIME / MASS mapped to Radioss labels, else Mg mm s
  (d) *SECTION_SHELL SHRF (card 1 field 3) is read into SectionShell
  (e) the *DAMPING_GLOBAL LCID > 0 warning says VALDMP is bypassed
  (f) the new levers reach the parser, convert(), ConvertOptions, cli.main()
      and the GUI with their exact names and defaults
  (g) the --shell-formulation / ValueError / GUI per-ELFORM sentence, the
      --auto-gapmin help without 'node-to-node', the --inter-gapmin /
      --soften-stfac help naming the SSID != 0 route

and the proof that a deck without the new cards converts byte-identical
to master d7652da.

The K1a contact group of the batch follows, on its own probe deck
(_k1a_deck: two paperboard shell cards over a solid block): K-01 the
single-surface route named by its SSID, K-02 the /INTER/TYPE7 Stmin floor
(--inter-stmin and the default-ON estimate warning), K-03 the shell-offset
clamp's two routes to t/2, K-04 the offset-aware --auto-gapmin, K-06
--inter-inacti 6, K-07 friction typed into card 1, K-08 the AUTOMATIC
surface-to-surface one-way note, K-08B the opt-in --s2s-type25, K-13 the
TYPE25 self-contact's gap inputs, the three K-0P review follow-ups, and -
last - the fixes of the group's adversarial review (rules no test pinned,
refusal texts that named unreachable cases, a Poisson's ratio read from the
wrong field).

The K1b contact group (wave C) closes the module on the same probe deck:
the K1a residual (a law the starter gives no contact stiffness, LAW169),
three hand-overs (the *DATABASE_EXTENT_BINARY MAXINT read, the
--stop-added-mass / --print-every / --dt2ms-tssfac-product help texts, the
*DAMPING_GLOBAL LCID sentence's beta case), K-05 the --inter-gapmin report on
the SOFT-routed general contacts, K-09 the named optional Card A / C fields,
K-10 --general-shell-edges and the SOFT 2 Iedge 22 gate, K-11 Card-2 BT / DT
on every route, K-12 the single-surface |SST| gap, K-14 the Mortar / IGNORE
texts and K-16 Card E SRNDE -> TYPE25 Ishape.

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_7.py (and the blast
deck from tests/test_converter.py) as MODULES, so no earlier TestCase is
bound in this namespace and none runs twice.
"""

import hashlib
import inspect
import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr

import test_r14_triage_7 as _t7

_row = _t7._row
_convert = _t7._convert
_dispatch = _t7._dispatch
_has = _t7._has
_collapse = _t7._collapse


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _begin_units(starter: str):
    """The two /BEGIN unit lines (input units, work units) as token lists."""
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.strip() == "/BEGIN")
    return lines[i + 3].split(), lines[i + 4].split()


# ── decks ────────────────────────────────────────────────────────────────────

_BLOCK_NODES = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0),
                (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)]
# a 1 x 1 shell plate 0.5 above the block's top face
_PLATE_NODES = [(0.0, 0.0, 1.5), (1.0, 0.0, 1.5), (1.0, 1.0, 1.5),
                (0.0, 1.0, 1.5)]


def _nodes() -> str:
    pts = _BLOCK_NODES + _PLATE_NODES
    return "*NODE\n" + "".join(
        f"{i:>8}{x:>16}{y:>16}{z:>16}\n" for i, (x, y, z) in
        enumerate(pts, 1))


def _deck(control: str = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n",
          extra: str = "", shrf: str = "") -> str:
    """An explicit hex block (*MAT_ELASTIC) under a shell plate
    (*MAT_PLASTIC_KINEMATIC, NIP 3), a surface-to-surface contact between
    them, the block's base held, GLSTAT + D3PLOT output. None of the cards
    a later group of this batch converts differently by default (tets,
    LAW1 shells, damping curves, single-surface SST, IKEDIT without GLSTAT,
    contact BT/DT) - so the pinned master bytes below stay a K-0P proof."""
    return (
        "*KEYWORD\n*TITLE\ncardstack plumbing\n"
        + control
        + _nodes()
        + "*ELEMENT_SOLID\n"
        + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 3, 4, 5, 6, 7, 8)) + "\n"
        + "*ELEMENT_SHELL\n"
        + "".join(f"{v:>8}" for v in (2, 2, 9, 10, 11, 12)) + "\n"
        + "*PART\nblock\n" + _row(1, 1, 1) + "\n"
        + "*PART\nplate\n" + _row(2, 2, 2) + "\n"
        + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
        + "*SECTION_SHELL\n" + _row(2, 2, shrf, 3) + "\n" + _row(0.1) + "\n"
        + "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
        + "*MAT_PLASTIC_KINEMATIC\n"
        + _row(2, 7.85e-9, 210000.0, 0.3, 250.0, 1000.0) + "\n"
        + _row(0.0, 0.0, 0.0) + "\n"
        + "*SET_PART_LIST\n" + _row(11) + "\n" + _row(2) + "\n"
        + "*SET_PART_LIST\n" + _row(12) + "\n" + _row(1) + "\n"
        + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
        + _row(11, 12, 2, 2) + "\n" + _row(0.2, 0.2) + "\n" + _row() + "\n"
        + "*SET_NODE_LIST\n" + _row(21) + "\n" + _row(1, 2, 3, 4) + "\n"
        + "*BOUNDARY_SPC_SET\n" + _row(21, 0, 1, 1, 1, 1, 1, 1) + "\n"
        + "*DATABASE_GLSTAT\n" + _row(1.0e-5) + "\n"
        + "*DATABASE_BINARY_D3PLOT\n" + _row(1.0e-4) + "\n"
        + extra
        + "*END\n")


# The SHA-256 of _deck()'s two files, converted at master d7652da with the
# default options (k2rad exported by `git archive d7652da k2rad`, run with
# the repo venv; the K-0P implementer's scratch sha_pin.py). A deck without
# the new cards must keep these bytes.
_PIN_STARTER = ("44626ef238d8b7f0b40dc66861bba8eab6c3698091f0f5d6212751693e"
                "2d4891")
_PIN_ENGINE = ("6d9f5932bc54f3ea642930434d1d4c0646476b327bfe37822a34841d9dd"
               "471b6")


# ═════════════════════════════════════════════════════════════════════════════
# (a) *CONTROL_TERMINATION ENDCYC / DTMIN / ENDENG / ENDMAS
# ═════════════════════════════════════════════════════════════════════════════

class ControlTerminationFields(unittest.TestCase):
    """Card 1 is ENDTIM ENDCYC DTMIN ENDENG ENDMAS NOSOL (Vol I R17
    p.12-558); the handler used to keep ENDTIM only."""

    def _term(self, row: str):
        st = _dispatch(_deck(control="*CONTROL_TERMINATION\n" + row + "\n"))
        return st.ctrl_termination

    def test_endmas_4_is_read(self):
        ct = self._term(_row(0.01, 0, 0.0, 0.0, 4.0))
        self.assertEqual(ct.endtim, 0.01)
        self.assertEqual(ct.endmas, 4.0)

    def test_all_four_fields(self):
        ct = self._term(_row(0.01, 5000, 0.05, 10.0, 4.0))
        self.assertEqual(ct.endcyc, 5000)
        self.assertIsInstance(ct.endcyc, int)
        self.assertEqual(ct.dtmin, 0.05)
        self.assertEqual(ct.endeng, 10.0)
        self.assertEqual(ct.endmas, 4.0)

    def test_blank_cells_are_stated_as_zero(self):
        """Blank = 0 / 0.0 as STATED (LS-DYNA's own ENDMAS default is
        1.0E8 = off; the consumer treats 0, blank and >= 1e8 alike)."""
        ct = self._term(_row(0.01))
        self.assertEqual((ct.endcyc, ct.dtmin, ct.endeng, ct.endmas),
                         (0, 0.0, 0.0, 0.0))

    def test_positional_construction_still_works(self):
        from k2rad.state import ControlTermination
        ct = ControlTermination(0.5)
        self.assertEqual((ct.endtim, ct.endcyc, ct.dtmin, ct.endeng,
                          ct.endmas), (0.5, 0, 0.0, 0.0, 0.0))


# ═════════════════════════════════════════════════════════════════════════════
# (b) *CONTROL_OUTPUT IKEDIT
# ═════════════════════════════════════════════════════════════════════════════

class ControlOutputIkedit(unittest.TestCase):
    """Card 1 is NPOPT NEECHO NREFUP IACCOP OPIFS IPNINT IKEDIT IFLUSH
    (Vol I R17 p.12-439); IKEDIT is field 7."""

    def _out(self, row: str):
        return _dispatch(_deck(extra="*CONTROL_OUTPUT\n" + row + "\n")
                         ).ctrl_output

    def test_ikedit_500_is_read(self):
        co = self._out(_row(1, 3, 0, 0, 0.0, 0, 500, 0))
        self.assertEqual(co.ikedit, 500)
        self.assertEqual((co.npopt, co.neecho), (1, 3))

    def test_blank_ikedit_is_zero_as_stated(self):
        """0 = not stated (LS-DYNA's own default is 100); the /PRINT
        consumer uses only a stated value."""
        self.assertEqual(self._out(_row(1, 3)).ikedit, 0)

    def test_positional_construction_still_works(self):
        from k2rad.state import ControlOutput
        self.assertEqual(ControlOutput(0, 0).ikedit, 0)


# ═════════════════════════════════════════════════════════════════════════════
# (c) *CONTROL_UNITS -> state.control_units -> the /BEGIN labels
# ═════════════════════════════════════════════════════════════════════════════

def _units_card(length="", time="", mass="", temp="", card2=None) -> str:
    out = "*CONTROL_UNITS\n" + _row(length, time, mass, temp) + "\n"
    if card2 is not None:
        out += "".join(f"{v:>20}" for v in card2) + "\n"
    return out


class ControlUnitsHandler(unittest.TestCase):
    """The card (Vol I R17 p.12-592/593): card 1 LENGTH TIME MASS TEMP
    (defaults m sec kg K), optional card 2 LENGTH_SCALE TIME_SCALE
    MASS_SCALE (meters / seconds / kilograms per deck unit, 20 wide), a
    non-zero scale overriding card 1."""

    def _cu(self, card: str):
        st = _dispatch(_deck(extra=card))
        self.assertNotIn("CONTROL_UNITS", st.skipped_keywords)
        return st.control_units

    def test_official_names_are_stored_and_mapped(self):
        cu = self._cu(_units_card("mm", "sec", "mtrc_ton", "K"))
        self.assertEqual((cu.length, cu.time, cu.mass, cu.temp),
                         ("mm", "sec", "mtrc_ton", "K"))
        self.assertEqual(cu.labels, ("Mg", "mm", "s"))
        self.assertEqual(cu.problems, [])

    def test_ton_and_s_aliases(self):
        self.assertEqual(self._cu(_units_card("mm", "s", "ton")).labels,
                         ("Mg", "mm", "s"))

    def test_other_systems(self):
        for cells, labels in ((("m", "sec", "kg"), ("kg", "m", "s")),
                              (("mm", "ms", "kg"), ("kg", "mm", "ms")),
                              (("cm", "micro_s", "g"), ("g", "cm", "mus")),
                              (("mm", "ms", "g"), ("g", "mm", "ms"))):
            with self.subTest(cells=cells):
                self.assertEqual(self._cu(_units_card(*cells)).labels, labels)

    def test_blank_cell_takes_the_manual_default(self):
        cu = self._cu(_units_card("mm"))
        self.assertEqual(cu.labels, ("kg", "mm", "s"))
        self.assertEqual(cu.defaulted, ["TIME", "MASS"])

    def test_imperial_and_unknown_names_have_no_label(self):
        cu = self._cu(_units_card("in", "sec", "lb"))
        self.assertIsNone(cu.labels)
        joined = " ".join(cu.problems)
        self.assertIn("LENGTH 'in'", joined)
        self.assertIn("MASS 'lb'", joined)
        cu = self._cu(_units_card("mm", "sec", "Mg"))
        self.assertIsNone(cu.labels)
        self.assertIn("MASS 'Mg'", " ".join(cu.problems))

    def test_empty_card_states_nothing(self):
        cu = self._cu("*CONTROL_UNITS\n")
        self.assertIsNone(cu.labels)
        self.assertTrue(any("states no unit" in p for p in cu.problems))

    def test_card2_scales_override_card1(self):
        cu = self._cu(_units_card("m", "sec", "kg",
                                  card2=(0.001, 1.0, 1000.0)))
        self.assertEqual(cu.labels, ("Mg", "mm", "s"))
        self.assertEqual((cu.length_scale, cu.time_scale, cu.mass_scale),
                         (0.001, 1.0, 1000.0))
        cu = self._cu(_units_card("mm", "sec", "mtrc_ton",
                                  card2=(0.0, 3600.0, 0.0)))
        self.assertIsNone(cu.labels)
        self.assertIn("TIME_SCALE", " ".join(cu.problems))


class ControlUnitsBeginLabels(unittest.TestCase):
    """convert() resolves state.units after parsing: --units if given,
    else the *CONTROL_UNITS labels, else Mg mm s."""

    def test_mm_sec_ton_gives_Mg_mm_s_and_no_skip(self):
        for cells in (("mm", "sec", "mtrc_ton"), ("mm", "s", "ton")):
            with self.subTest(cells=cells):
                res, starter, _e = _convert(_deck(extra=_units_card(*cells)))
                self.assertEqual(_begin_units(starter),
                                 (["Mg", "mm", "s"], ["Mg", "mm", "s"]))
                self.assertNotIn("CONTROL_UNITS", res.skipped_keywords)
                self.assertTrue(_has(res.warnings, "/BEGIN units Mg/mm/s",
                                     "from *CONTROL_UNITS"))

    def test_si_card_writes_kg_m_s(self):
        res, starter, _e = _convert(_deck(extra=_units_card("m", "sec", "kg")))
        self.assertEqual(_begin_units(starter),
                         (["kg", "m", "s"], ["kg", "m", "s"]))

    def test_explicit_units_win_and_a_disagreeing_card_warns(self):
        res, starter, _e = _convert(_deck(extra=_units_card("m", "sec", "kg")),
                                    units=("Mg", "mm", "s"))
        self.assertEqual(_begin_units(starter)[0], ["Mg", "mm", "s"])
        self.assertTrue(_has(res.warnings, "--units Mg/mm/s",
                             "disagree with the deck's *CONTROL_UNITS",
                             "kg/m/s"))

    def test_explicit_units_equal_to_the_card_are_silent(self):
        for units in (("kg", "m", "s"), ("Kg", "m", "s")):
            with self.subTest(units=units):
                res, starter, _e = _convert(
                    _deck(extra=_units_card("m", "sec", "kg")), units=units)
                self.assertEqual(_begin_units(starter)[0], list(units))
                self.assertFalse(_has(res.warnings, "*CONTROL_UNITS"))

    def test_unmappable_card_keeps_Mg_mm_s_and_names_the_cell(self):
        res, starter, _e = _convert(_deck(extra=_units_card("in", "sec",
                                                            "slinch")))
        self.assertEqual(_begin_units(starter)[0], ["Mg", "mm", "s"])
        self.assertTrue(_has(res.warnings, "*CONTROL_UNITS", "LENGTH 'in'",
                             "MASS 'slinch'", "Mg/mm/s"))

    def test_empty_card_keeps_Mg_mm_s_and_says_so(self):
        res, starter, _e = _convert(_deck(extra="*CONTROL_UNITS\n"))
        self.assertEqual(_begin_units(starter)[0], ["Mg", "mm", "s"])
        self.assertNotIn("CONTROL_UNITS", res.skipped_keywords)
        self.assertTrue(_has(res.warnings, "*CONTROL_UNITS states no unit"))

    def test_no_card_no_units_is_the_old_default_and_silent(self):
        res, starter, _e = _convert(_deck())
        self.assertEqual(_begin_units(starter),
                         (["Mg", "mm", "s"], ["Mg", "mm", "s"]))
        self.assertFalse(_has(res.warnings, "CONTROL_UNITS"))
        self.assertFalse(_has(res.warnings, "/BEGIN units"))

    def test_blast_unit_flag_wins_over_the_card_and_names_both(self):
        """The blast UNIT flag is what LS-DYNA computes the blast with, and
        /LOAD/PBLAST reads the /BEGIN labels - so a disagreeing card loses
        (and is named), exactly as an unstated --units always did."""
        import test_converter as _tc
        deck = _tc.BLAST_K.replace("*CONTROL_TERMINATION",
                                   _units_card("mm", "sec", "mtrc_ton")
                                   + "*CONTROL_TERMINATION", 1)
        res, starter, _e = _convert(deck)
        self.assertEqual(_begin_units(starter)[0], ["kg", "m", "s"])
        self.assertTrue(_has(res.warnings, "*CONTROL_UNITS",
                             "*LOAD_BLAST_ENHANCED UNIT", "Mg/mm/s",
                             "kg/m/s"))
        agreeing = _tc.BLAST_K.replace("*CONTROL_TERMINATION",
                                       _units_card("m", "sec", "kg")
                                       + "*CONTROL_TERMINATION", 1)
        res, starter, _e = _convert(agreeing)
        self.assertEqual(_begin_units(starter)[0], ["kg", "m", "s"])
        self.assertFalse(_has(res.warnings, "*CONTROL_UNITS",
                              "*LOAD_BLAST_ENHANCED UNIT"))


# ═════════════════════════════════════════════════════════════════════════════
# (d) *SECTION_SHELL SHRF
# ═════════════════════════════════════════════════════════════════════════════

class SectionShellShrf(unittest.TestCase):
    """Card 1 is SECID ELFORM SHRF NIP ...: SHRF is field 3, recorded as
    STATED (0.0 = blank), the convention of SectionTshell / *PART_COMPOSITE.
    Not converted yet (Ashear stays the starter's 5/6, ROADMAP round 10),
    so the bytes do not move."""

    def test_stated_shrf_is_read(self):
        st = _dispatch(_deck(shrf="0.8333"))
        self.assertEqual(st.sec_shells[2].shrf, 0.8333)

    def test_blank_shrf_is_zero(self):
        self.assertEqual(_dispatch(_deck()).sec_shells[2].shrf, 0.0)

    def test_shrf_changes_no_byte(self):
        _r, s1, e1 = _convert(_deck(shrf="0.8333"))
        _r, s0, e0 = _convert(_deck())
        self.assertEqual(_sha(s1), _sha(s0))
        self.assertEqual(_sha(e1), _sha(e0))


# ═════════════════════════════════════════════════════════════════════════════
# (e) the *DAMPING_GLOBAL LCID > 0 warning
# ═════════════════════════════════════════════════════════════════════════════

_DAMP_CURVE = ("*DEFINE_CURVE\n" + _row(2) + "\n"
               + "".join(f"{a:>20}{o:>20}\n" for a, o in
                         ((0.0, 50.0), (0.0005, 50.0), (0.0006, 0.0),
                          (0.001, 0.0))))
_OLD_DAMP_TEXT = ("*DAMPING_GLOBAL: lcid=2 (time-varying damping) not "
                  "supported; using constant valdmp=0.5")


class DampingGlobalLcidText(unittest.TestCase):
    """VALDMP 'is bypassed if the load curve number defined above is non
    zero' (Vol I R17 p.15-8): the default-ON text says the curve is the
    damping constant; --no-damping-curve-window keeps the old text, which
    is true of the old bytes."""

    def _warnings(self, lcid=2, **kw):
        deck = _deck(extra=_DAMP_CURVE + "*DAMPING_GLOBAL\n"
                     + _row(lcid, 0.5) + "\n")
        res, _s, _e = _convert(deck, **kw)
        return res.warnings

    def test_default_text_says_valdmp_is_bypassed(self):
        w = self._warnings()
        self.assertTrue(_has(w, "*DAMPING_GLOBAL", "LCID=2", "VALDMP=0.5",
                             "bypassed", "p.15-8",
                             "--no-damping-curve-window"))
        self.assertFalse(_has(w, "not supported; using constant valdmp"))

    def test_opt_out_keeps_the_old_text(self):
        w = self._warnings(damping_curve_window=False)
        self.assertIn(_OLD_DAMP_TEXT, w)
        self.assertFalse(_has(w, "bypassed"))

    def test_lcid_0_says_nothing(self):
        w = self._warnings(lcid=0)
        self.assertFalse(_has(w, "bypassed"))
        self.assertFalse(_has(w, "not supported; using constant valdmp"))


# ═════════════════════════════════════════════════════════════════════════════
# (f) the new levers: parser, convert(), ConvertOptions, cli.main(), GUI
# ═════════════════════════════════════════════════════════════════════════════

#: (CLI flag, ConvertOptions / convert() name, default) - every boolean
#: lever K-0P lands, and the four opt-out flags of the user's decision 8
#: (2026-11-01) for the wave-C defaults K-11, K-10's SOFT 2 Iedge gate,
#: K-16 and the MAXINT read; each is a BooleanOptionalAction with its
#: --no- twin.
_BOOL_LEVERS = (
    ("--damping-curve-window", "damping_curve_window", True),
    ("--stop-added-mass", "stop_added_mass", False),
    ("--dt2ms-tssfac-product", "dt2ms_tssfac_product", False),
    ("--tet-isolid1", "tet_isolid1", True),
    ("--law1-shell-global-n", "law1_shell_global_n", True),
    ("--s2s-type25", "s2s_type25", False),
    ("--general-shell-edges", "general_shell_edges", False),
    ("--single-surface-sst-gap", "single_surface_sst_gap", True),
    ("--contact-birth-death", "contact_birth_death", True),
    ("--soft2-iedge-gate", "soft2_iedge_gate", True),
    ("--srnde-ishape", "srnde_ishape", True),
    ("--maxint-stress-all", "maxint_stress_all", True),
)
#: the non-boolean levers and their defaults
_VALUE_LEVERS = {"print_every": None, "inter_stmin": {}, "inter_inacti": {}}


def _empty_deck_path(tmp) -> str:
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write("*KEYWORD\n*END\n")
    return path


def _main_kwargs(argv):
    """cli.main(argv) with convert() replaced: the kwargs it was called
    with (None when main returned before calling it) and main's code."""
    from k2rad import cli
    import k2rad
    seen = {}

    def fake_convert(*a, **kw):
        seen.update(kw)
        raise SystemExit(0)

    saved = k2rad.convert
    k2rad.convert = fake_convert
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code
    finally:
        k2rad.convert = saved
    return (seen or None), code, err.getvalue()


class NewLeversWiring(unittest.TestCase):

    def test_every_bool_lever_is_a_parser_option_with_its_no_twin(self):
        from k2rad import cli
        opts = {s for a in cli.build_parser()._actions
                for s in a.option_strings}
        for flag, _name, _default in _BOOL_LEVERS:
            with self.subTest(flag=flag):
                self.assertIn(flag, opts)
                self.assertIn("--no-" + flag[2:], opts)
        for flag in ("--print-every", "--inter-stmin", "--inter-inacti"):
            self.assertIn(flag, opts)

    def test_parser_defaults(self):
        from k2rad import cli
        ns = cli.build_parser().parse_args(["d.k"])
        for _flag, name, default in _BOOL_LEVERS:
            with self.subTest(name=name):
                self.assertIs(getattr(ns, name), default)
        self.assertIsNone(ns.print_every)
        self.assertEqual(ns.inter_stmin, [])
        self.assertEqual(ns.inter_inacti, [])
        self.assertIsNone(ns.units)

    def test_convert_signature_and_ConvertOptions_defaults(self):
        from k2rad import convert
        from k2rad.state import ConvertOptions
        sig = inspect.signature(convert).parameters
        opts = ConvertOptions()
        for _flag, name, default in _BOOL_LEVERS:
            with self.subTest(name=name):
                self.assertIs(sig[name].default, default)
                self.assertIs(getattr(opts, name), default)
        for name, default in _VALUE_LEVERS.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(opts, name), default)
                if default is None:
                    self.assertIsNone(sig[name].default)
                else:
                    self.assertIn(sig[name].default, (None, default))
        self.assertIsNone(sig["units"].default)

    def test_the_cli_passes_every_lever_through(self):
        tmp = tempfile.TemporaryDirectory()
        path = _empty_deck_path(tmp)
        seen, code, _err = _main_kwargs([path])
        self.assertEqual(code, 0)
        for _flag, name, default in _BOOL_LEVERS:
            self.assertIs(seen[name], default, name)
        self.assertIsNone(seen["print_every"])
        self.assertEqual(seen["inter_stmin"], {})
        self.assertEqual(seen["inter_inacti"], {})
        self.assertIsNone(seen["units"])
        for flag, name, default in _BOOL_LEVERS:
            spelled = flag if not default else "--no-" + flag[2:]
            with self.subTest(argv=spelled):
                seen, code, _err = _main_kwargs([path, spelled])
                self.assertEqual(code, 0)
                self.assertIs(seen[name], not default)
        seen, code, _err = _main_kwargs(
            [path, "--print-every", "100", "--inter-stmin", "7=0",
             "--inter-stmin", "12=250.5", "--inter-inacti", "7=6",
             "--units", "kg", "m", "s"])
        self.assertEqual(code, 0)
        self.assertEqual(seen["print_every"], 100)
        self.assertEqual(seen["inter_stmin"], {7: 0.0, 12: 250.5})
        self.assertEqual(seen["inter_inacti"], {7: 6})
        self.assertEqual(seen["units"], ("kg", "m", "s"))
        tmp.cleanup()

    def test_malformed_pairs_stop_before_converting(self):
        tmp = tempfile.TemporaryDirectory()
        path = _empty_deck_path(tmp)
        for argv, needle in (
                (["--inter-stmin", "7"], "--inter-stmin expects ID=VAL"),
                (["--inter-stmin", "x=1"], "--inter-stmin ID and VAL"),
                (["--inter-stmin", "7=-1"], ">= 0"),
                (["--inter-inacti", "7=5"], "only Inacti 6"),
                (["--inter-inacti", "7"], "--inter-inacti expects ID=6")):
            with self.subTest(argv=argv):
                seen, code, err = _main_kwargs([path] + argv)
                self.assertIsNone(seen)
                self.assertEqual(code, 1)
                self.assertIn(needle, err)
        tmp.cleanup()

    def test_print_every_range(self):
        """The engine reads /PRINT/-N's cell as I5 (freform.F:1563), so N
        must be 1..9999."""
        from k2rad import cli
        parser = cli.build_parser()
        self.assertEqual(parser.parse_args(
            ["d.k", "--print-every", "9999"]).print_every, 9999)
        for bad in ("0", "10000", "-5", "abc", "2.5"):
            with self.subTest(bad=bad):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(["d.k", "--print-every", bad])

    def test_the_api_refuses_what_the_cli_refuses(self):
        from k2rad.state import ConvertOptions
        for kw in ({"print_every": 0}, {"print_every": 10000},
                   {"print_every": 2.5}, {"inter_inacti": {7: 5}},
                   {"inter_stmin": {7: -1.0}},
                   {"inter_stmin": {7: float("nan")}}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    ConvertOptions(**kw)
        ok = ConvertOptions(print_every=100, inter_inacti={7: 6},
                            inter_stmin={7: 0.0})
        self.assertEqual((ok.print_every, ok.inter_inacti, ok.inter_stmin),
                         (100, {7: 6}, {7: 0.0}))

    def test_every_lever_reaches_state_options(self):
        """convert() really builds ConvertOptions with each lever (a kwarg
        convert() drops is a silent conversion): the options the first
        dispatch() call sees."""
        import k2rad
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(_deck())
        flipped = {name: not default for _f, name, default in _BOOL_LEVERS}
        values = {"print_every": 50, "inter_stmin": {1: 0.0},
                  "inter_inacti": {1: 6}}
        seen = {}
        real = k2rad.dispatch

        def spy(block, state):
            seen.setdefault("options", state.options)
            return real(block, state)

        k2rad.dispatch = spy
        try:
            k2rad.convert(path, write_log=False, **flipped, **values)
        finally:
            k2rad.dispatch = real
        opts = seen["options"]
        for name, value in list(flipped.items()) + list(values.items()):
            with self.subTest(name=name):
                self.assertEqual(getattr(opts, name), value)
        tmp.cleanup()

    def test_ConvertOptions_docstring_names_every_default_on_lever(self):
        """'All default to off' was false (52 default-ON levers before this
        batch); the docstring names each default-ON exception, and only
        real ones."""
        import dataclasses
        from k2rad.state import ConvertOptions
        doc = _collapse(ConvertOptions.__doc__)
        self.assertNotIn("All default to off", doc)
        on = {f.name for f in dataclasses.fields(ConvertOptions)
              if getattr(ConvertOptions(), f.name) is True}
        for name in sorted(on):
            with self.subTest(name=name):
                self.assertRegex(doc, r"\b" + re.escape(name) + r"\b")
        listed = set(re.findall(r"``([a-z0-9_]+)``", doc))
        named_on = {n for n in listed
                    if n in {f.name for f in dataclasses.fields(
                        ConvertOptions)}}
        self.assertEqual(named_on - on, set())


class NewLeversGui(unittest.TestCase):
    """The GUI's build_convert_kwargs / _describe_options carry every
    lever (the round-7 wiring checks), and blank unit boxes mean 'from the
    deck'."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = _empty_deck_path(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def _kw(self, units=("Mg", "mm", "s"), **kw):
        import k2rad_gui
        return k2rad_gui.build_convert_kwargs(
            self.path, "", units, ground_springs=False,
            ground_spring_k_text="", soften_stfac_text="", **kw)

    def _described(self, kw) -> str:
        import k2rad_gui
        captured = []
        app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
        app._append = captured.append
        k2rad_gui.ConverterGUI._describe_options(app, kw)
        return "".join(captured)

    def test_every_bool_lever_end_to_end(self):
        for flag, name, default in _BOOL_LEVERS:
            with self.subTest(name=name):
                spelled = flag if not default else "--no-" + flag[2:]
                kw = self._kw(**{name: not default})
                self.assertIs(kw[name], not default)
                self.assertIn(spelled, self._described(kw))
                kw0 = self._kw()
                self.assertIs(kw0[name], default)
                self.assertNotIn(spelled, self._described(kw0))

    def test_print_every_and_the_pair_boxes(self):
        kw = self._kw(print_every_text="250", inter_stmin_text="7=0, 9=10",
                      inter_inacti_text="7=6")
        self.assertEqual(kw["print_every"], 250)
        self.assertEqual(kw["inter_stmin"], {7: 0.0, 9: 10.0})
        self.assertEqual(kw["inter_inacti"], {7: 6})
        text = self._described(kw)
        for needle in ("--print-every 250", "--inter-stmin 7=0",
                       "--inter-inacti 7=6"):
            self.assertIn(needle, text)
        kw0 = self._kw()
        self.assertNotIn("print_every", kw0)
        self.assertEqual(kw0["inter_stmin"], {})
        self.assertEqual(kw0["inter_inacti"], {})
        for bad in ({"print_every_text": "0"}, {"print_every_text": "x"},
                    {"inter_inacti_text": "7=5"},
                    {"inter_stmin_text": "7=-2"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self._kw(**bad)

    def test_blank_unit_boxes_mean_from_the_deck(self):
        self.assertNotIn("units", self._kw(units=("", "", "")))
        # a partly filled row still falls back per slot (unchanged)
        self.assertEqual(self._kw(units=("", "cm", ""))["units"],
                         ("Mg", "cm", "s"))
        self.assertEqual(self._kw()["units"], ("Mg", "mm", "s"))


# ═════════════════════════════════════════════════════════════════════════════
# (g) help texts
# ═════════════════════════════════════════════════════════════════════════════

def _action_help(flag: str) -> str:
    from k2rad import cli
    for a in cli.build_parser()._actions:
        if flag in a.option_strings:
            return _collapse(a.help % {})
    raise AssertionError(flag)


_ELFORM16 = ("ELFORM 16", "Ishell 12", "same integration class", "dyna2rad",
             "+0.46 %")


def _gui_source_joined() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "k2rad_gui.py"), encoding="utf-8") as fh:
        text = fh.read()
    return _collapse(re.sub(r'"\s*\n\s*"', "", text))


class HelpTexts(unittest.TestCase):

    def test_the_whole_help_renders(self):
        """A bare % in a help string kills --help at a green suite."""
        from k2rad import cli
        text = cli.build_parser().format_help()
        for flag, _name, default in _BOOL_LEVERS:
            self.assertIn(flag, text)
        self.assertIn("--print-every", text)

    def test_shell_formulation_help_carries_the_per_elform_sentence(self):
        h = _action_help("--shell-formulation")
        for needle in _ELFORM16:
            with self.subTest(needle=needle):
                self.assertIn(needle, h)

    def test_the_value_error_carries_it(self):
        from k2rad import convert
        tmp = tempfile.TemporaryDirectory()
        path = _empty_deck_path(tmp)
        with self.assertRaises(ValueError) as cm:
            convert(path, write_log=False, shell_formulation="bogus")
        msg = _collapse(str(cm.exception))
        for needle in _ELFORM16:
            with self.subTest(needle=needle):
                self.assertIn(needle, msg)
        tmp.cleanup()

    def test_the_gui_frame_carries_it(self):
        src = _gui_source_joined()
        for needle in _ELFORM16:
            with self.subTest(needle=needle):
                self.assertIn(needle, src)

    def test_auto_gapmin_help_is_node_to_segment(self):
        h = _action_help("--auto-gapmin")
        self.assertNotIn("node-to-node", h)
        self.assertIn("node-to-segment", h)
        self.assertNotIn("min node distance", _gui_source_joined())

    def test_inter_gapmin_and_soften_stfac_name_the_ssid_route(self):
        for flag in ("--inter-gapmin", "--soften-stfac"):
            with self.subTest(flag=flag):
                h = _action_help(flag)
                self.assertIn("SSID != 0", h)
                self.assertIn("*CONTACT_AUTOMATIC_SINGLE_SURFACE", h)

    def test_units_help_names_the_card(self):
        h = _action_help("--units")
        self.assertIn("*CONTROL_UNITS", h)
        self.assertIn("Mg mm s", h)


# ═════════════════════════════════════════════════════════════════════════════
# A deck without the new cards converts byte-identical to master d7652da
# ═════════════════════════════════════════════════════════════════════════════

class ByteIdentityAtMaster(unittest.TestCase):

    def test_plain_deck_keeps_the_master_bytes(self):
        _r, starter, engine = _convert(_deck())
        self.assertEqual(_sha(starter), _PIN_STARTER)
        self.assertEqual(_sha(engine), _PIN_ENGINE)

    def test_the_read_only_cards_change_no_byte(self):
        """ENDCYC / DTMIN / ENDENG / ENDMAS, IKEDIT beside a
        *DATABASE_GLSTAT, SHRF and a *CONTROL_UNITS that maps to the
        default triple are read and stored - the files stay those of the
        plain deck."""
        cards = _deck(
            control="*CONTROL_TERMINATION\n"
                    + _row(0.001, 900000, 0.001, 50.0, 4.0) + "\n",
            shrf="0.8333",
            extra="*CONTROL_OUTPUT\n" + _row(0, 0, 0, 0, 0.0, 0, 2000) + "\n"
                  + _units_card("mm", "sec", "mtrc_ton", "K"))
        _r, s1, e1 = _convert(cards)
        self.assertEqual(_sha(s1), _PIN_STARTER)
        self.assertEqual(_sha(e1), _PIN_ENGINE)


# ═════════════════════════════════════════════════════════════════════════════
# K-0P fix round (the adversarial review): the table rows, resolution
# branches, refusals and GUI wiring the first suite left unguarded - each
# class names the review's surviving mutants it kills
# ═════════════════════════════════════════════════════════════════════════════

#: Every card-1 name of Vol I R17 p.12-593 per slot, plus k2rad's aliases
#: 's', 'ton' and 'tonne', -> the /BEGIN label of the SAME unit. None = an
#: imperial name no label can carry (a label is an SI prefix + g / m / s,
#: unit_code.F). The milligram has its own test: it is the one name matched
#: case-SENSITIVELY.
_CU_CARD1 = {
    "LENGTH": {"m": "m", "mm": "mm", "cm": "cm", "in": None, "ft": None},
    "TIME": {"sec": "s", "s": "s", "ms": "ms", "micro_s": "mus"},
    "MASS": {"kg": "kg", "g": "g", "mtrc_ton": "Mg", "ton": "Mg",
             "tonne": "Mg", "lb": None, "slug": None, "slinch": None},
}
#: Card 2 (meters / seconds / kilograms per deck unit) -> label, every row.
_CU_CARD2 = {
    "LENGTH": ((1.0, "m"), (0.01, "cm"), (0.001, "mm")),
    "TIME": ((1.0, "s"), (0.001, "ms"), (1.0e-6, "mus")),
    "MASS": ((1.0, "kg"), (0.001, "g"), (1.0e-6, "mg"), (1000.0, "Mg")),
}
#: the slot's index in ControlUnits.labels (mass, length, time) and on card 2
_CU_LABEL_INDEX = {"MASS": 0, "LENGTH": 1, "TIME": 2}
_CU_CARD_INDEX = {"LENGTH": 0, "TIME": 1, "MASS": 2}
#: the other two slots of a probe card hold a mapping name each
_CU_FILL = {"LENGTH": "mm", "TIME": "sec", "MASS": "mtrc_ton"}
_NO_LABEL_TEXT = "has no Radioss /BEGIN label"
_NOT_A_NAME_TEXT = "is not a *CONTROL_UNITS"


def _cu_only(card: str):
    """state.control_units of a deck that holds nothing but this card."""
    return _dispatch("*KEYWORD\n" + card + "*END\n").control_units


def _cu_card(slot: str, name: str, scale: float = 0.0) -> str:
    """A *CONTROL_UNITS card with *name* in *slot* (the other two slots
    from _CU_FILL) and, when *scale* is non-zero, a card 2 holding it in
    that slot alone."""
    cells = dict(_CU_FILL)
    cells[slot] = name
    card2 = None
    if scale:
        card2 = [0.0, 0.0, 0.0]
        card2[_CU_CARD_INDEX[slot]] = scale
    return _units_card(cells["LENGTH"], cells["TIME"], cells["MASS"],
                       card2=card2)


class ControlUnitsNameTables(unittest.TestCase):
    """Every row of the *CONTROL_UNITS name and scale tables, both cases,
    and both problem texts (the review's U1-U8). The tables decide the
    /BEGIN labels, and the starter converts its built-in constants with
    those labels (hm_read_radiation.F:140-142, hm_read_matgas.F:288-293,
    hm_read_pblast.F:293-295)."""

    def test_every_card1_name_in_each_slot_in_both_cases(self):
        for slot, names in _CU_CARD1.items():
            for name, label in names.items():
                for spelled in (name, name.upper()):
                    with self.subTest(slot=slot, name=spelled):
                        cu = _cu_only(_cu_card(slot, spelled))
                        if label is not None:
                            self.assertEqual(cu.problems, [])
                            self.assertEqual(
                                cu.labels[_CU_LABEL_INDEX[slot]], label)
                            continue
                        self.assertIsNone(cu.labels)
                        text = " ".join(cu.problems)
                        self.assertIn(f"{slot} '{spelled}' {_NO_LABEL_TEXT}",
                                      text)
                        self.assertNotIn(_NOT_A_NAME_TEXT, text)

    def test_the_milligram_is_matched_exactly(self):
        """'mg' is the milligram (the starter reads it as 1.0E-06 kg);
        'Mg' would be the megagram, 1e9 times heavier, and is no
        *CONTROL_UNITS name - LS-DYNA spells the metric ton 'mtrc_ton'."""
        self.assertEqual(_cu_only(_cu_card("MASS", "mg")).labels,
                         ("mg", "mm", "s"))
        for spelled in ("Mg", "MG", "mG"):
            with self.subTest(name=spelled):
                cu = _cu_only(_cu_card("MASS", spelled))
                self.assertIsNone(cu.labels)
                text = " ".join(cu.problems)
                self.assertIn(f"MASS '{spelled}' {_NOT_A_NAME_TEXT} MASS "
                              "name", text)
                self.assertNotIn(_NO_LABEL_TEXT, text)

    def test_unknown_names_get_the_not_a_name_text(self):
        for slot, name in (("LENGTH", "km"), ("TIME", "hour"),
                           ("MASS", "tons")):
            with self.subTest(slot=slot, name=name):
                cu = _cu_only(_cu_card(slot, name))
                self.assertIsNone(cu.labels)
                text = " ".join(cu.problems)
                self.assertIn(f"{slot} '{name}' {_NOT_A_NAME_TEXT} {slot} "
                              "name", text)
                self.assertIn("p.12-593", text)
                self.assertNotIn(_NO_LABEL_TEXT, text)

    def test_every_card2_scale_row_overrides_card1(self):
        for slot, rows in _CU_CARD2.items():
            for scale, label in rows:
                # a card-1 name of ANOTHER label: the scale has to win
                other = next(n for n, lab in _CU_CARD1[slot].items()
                             if lab not in (None, label))
                with self.subTest(slot=slot, scale=scale, card1=other):
                    cu = _cu_only(_cu_card(slot, other, scale=scale))
                    self.assertEqual(cu.problems, [])
                    self.assertEqual(cu.labels[_CU_LABEL_INDEX[slot]],
                                     label)

    def test_a_scale_without_a_label_is_named(self):
        for slot, scale, unit in (("LENGTH", 0.0254, "m"),
                                  ("TIME", 3600.0, "s"),
                                  ("MASS", 0.45359237, "kg")):
            with self.subTest(slot=slot):
                cu = _cu_only(_cu_card(slot, _CU_FILL[slot], scale=scale))
                self.assertIsNone(cu.labels)
                self.assertIn(f"{slot}_SCALE {scale:g} ({unit} per deck "
                              f"unit) {_NO_LABEL_TEXT}", " ".join(cu.problems))


class BeginResolutionBranches(unittest.TestCase):
    """The _resolve_begin_units branches the first suite left unguarded
    (the review's R1, R2, R3, R5 and R7)."""

    @staticmethod
    def _blast(card: str = "") -> str:
        import test_converter as _tc
        return _tc.BLAST_K.replace("*CONTROL_TERMINATION",
                                   card + "*CONTROL_TERMINATION", 1)

    def test_the_spelled_default_on_a_blast_deck_adopts_the_unit_flag(self):
        """An explicit Mg mm s has always counted as 'left at the default'
        on a blast deck (before K-0P the CLI passed exactly that tuple
        when --units was absent): the UNIT flag wins, with its old note."""
        for units in (None, ("Mg", "mm", "s")):
            with self.subTest(units=units):
                res, starter, _e = _convert(self._blast(), units=units)
                self.assertEqual(_begin_units(starter),
                                 (["kg", "m", "s"], ["kg", "m", "s"]))
                self.assertTrue(_has(
                    res.warnings, "/BEGIN units set to kg/m/s from the "
                    "*LOAD_BLAST_ENHANCED UNIT flag"))
                self.assertFalse(_has(res.warnings, "UNIT MISMATCH"))

    def test_a_card_against_the_flag_is_named_for_the_spelled_default(self):
        """The spelled default is the default here, so a *CONTROL_UNITS
        that disagrees with the blast flag is named exactly as it is
        without --units."""
        deck = self._blast(_units_card("mm", "sec", "mtrc_ton"))
        for units in (None, ("Mg", "mm", "s")):
            with self.subTest(units=units):
                res, starter, _e = _convert(deck, units=units)
                self.assertEqual(_begin_units(starter)[0], ["kg", "m", "s"])
                self.assertTrue(_has(
                    res.warnings, "*CONTROL_UNITS", "Mg/mm/s",
                    "disagrees with the *LOAD_BLAST_ENHANCED UNIT flag",
                    "kg/m/s"))

    def test_explicit_units_with_an_unmappable_card_name_its_cells(self):
        res, starter, _e = _convert(
            _deck(extra=_units_card("in", "sec", "lb")),
            units=("Mg", "mm", "s"))
        self.assertEqual(_begin_units(starter)[0], ["Mg", "mm", "s"])
        self.assertTrue(_has(
            res.warnings, "*CONTROL_UNITS: ",
            f"LENGTH 'in' {_NO_LABEL_TEXT}", "MASS 'lb'",
            "the explicit --units Mg/mm/s are written to /BEGIN"))
        res, starter, _e = _convert(_deck(extra="*CONTROL_UNITS\n"),
                                    units=("kg", "m", "s"))
        self.assertEqual(_begin_units(starter)[0], ["kg", "m", "s"])
        self.assertTrue(_has(
            res.warnings, "*CONTROL_UNITS: states no unit",
            "the explicit --units kg/m/s are written to /BEGIN"))

    def test_an_unparseable_explicit_label_is_compared_as_text(self):
        """'sec' is no /BEGIN label (the starter reads an SI prefix + s),
        so it cannot equal the card's 's': the disagreement is named."""
        res, starter, _e = _convert(
            _deck(extra=_units_card("m", "sec", "kg")),
            units=("kg", "m", "sec"))
        self.assertEqual(_begin_units(starter)[0], ["kg", "m", "sec"])
        self.assertTrue(_has(
            res.warnings,
            "--units kg/m/sec disagree with the deck's *CONTROL_UNITS",
            "kg/m/s"))

    def test_a_label_is_read_with_its_base_letter(self):
        import math
        from k2rad import _same_begin_units, _unit_label_factor
        for (label, base), factor in (
                (("mg", "g"), 1.0e-3), (("Kg", "g"), 1.0e3),
                (("kg", "g"), 1.0e3), (("g", "g"), 1.0),
                (("Mg", "g"), 1.0e6), (("mus", "s"), 1.0e-6),
                (("us", "s"), 1.0e-6), (("ms", "s"), 1.0e-3),
                (("cm", "m"), 1.0e-2), (("ms", "g"), None),
                (("mg", "s"), None), (("sec", "s"), None),
                (("", "g"), None), (("kgg", "g"), None)):
            with self.subTest(label=label, base=base):
                got = _unit_label_factor(label, base)
                if factor is None:
                    self.assertIsNone(got)
                else:
                    self.assertTrue(math.isclose(got, factor), got)
        self.assertTrue(_same_begin_units(("Kg", "m", "s"), ("kg", "m", "s")))
        self.assertTrue(_same_begin_units(("g", "cm", "us"),
                                          ("g", "cm", "mus")))
        self.assertFalse(_same_begin_units(("ms", "mm", "mg"),
                                           ("mg", "mm", "ms")))
        self.assertFalse(_same_begin_units(("kg", "m", "sec"),
                                           ("kg", "m", "s")))

    def test_a_swapped_mass_time_pair_is_not_the_same_system(self):
        """'ms' as a MASS label and 'mg' as a TIME label share the prefix
        of the card's mg / ms - only the base letter tells them apart."""
        res, _s, _e = _convert(_deck(extra=_units_card("mm", "ms", "mg")),
                               units=("ms", "mm", "mg"))
        self.assertTrue(_has(
            res.warnings,
            "--units ms/mm/mg disagree with the deck's *CONTROL_UNITS",
            "mg/mm/ms"))

    def test_the_card_note_names_its_defaulted_cells(self):
        res, starter, _e = _convert(_deck(extra=_units_card("mm")))
        self.assertEqual(_begin_units(starter)[0], ["kg", "mm", "s"])
        self.assertTrue(_has(
            res.warnings, "/BEGIN units kg/mm/s from *CONTROL_UNITS",
            "LENGTH mm, TIME (blank), MASS (blank)",
            "blank TIME / MASS = the manual's default sec / kg"))

    def test_the_card_note_says_which_starter_constants_follow(self):
        """No input value is rescaled, but the starter converts its
        built-in constants with the labels, while LS-DYNA reads the card
        only for an external database (Vol I R17 p.12-592) - so a stale
        card moves exactly those constants."""
        res, _s, _e = _convert(_deck(extra=_units_card("m", "sec", "kg")))
        self.assertTrue(_has(
            res.warnings, "/BEGIN units kg/m/s from *CONTROL_UNITS",
            "hm_read_radiation.F:140-142", "hm_read_matgas.F:288-293",
            "/LOAD/PBLAST", "external database", "p.12-592"))


def _gui_kw(path: str, units=("Mg", "mm", "s"), **kw) -> dict:
    import k2rad_gui
    return k2rad_gui.build_convert_kwargs(
        path, "", units, ground_springs=False, ground_spring_k_text="",
        soften_stfac_text="", **kw)


class NewLeverRefusals(unittest.TestCase):
    """Each layer's own refusal, unguarded before (the review's S1, S2,
    S3, S5, C1, G4 and G5), and a repeated interface id with two values."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = _empty_deck_path(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_convert_options_refuses_bools_infinities_and_bad_types(self):
        from k2rad.state import ConvertOptions
        for kw in ({"print_every": True}, {"print_every": False},
                   {"inter_stmin": {7: float("inf")}},
                   {"inter_stmin": {7: float("-inf")}},
                   {"inter_stmin": {"7": 1.0}}, {"inter_stmin": {True: 1.0}},
                   {"inter_stmin": {7: "1.5"}}, {"inter_stmin": {7: True}},
                   {"inter_stmin": {7: None}},
                   {"inter_inacti": {"7": 6}}, {"inter_inacti": {True: 6}},
                   {"inter_inacti": {7: 6.0}}, {"inter_inacti": {7: True}}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    ConvertOptions(**kw)
        ok = ConvertOptions(print_every=1, inter_stmin={7: 0, 8: 1.0e6})
        self.assertEqual((ok.print_every, ok.inter_stmin),
                         (1, {7: 0, 8: 1.0e6}))

    def test_the_cli_refuses_a_non_finite_stmin_before_converting(self):
        for val in ("inf", "-inf", "nan", "Infinity"):
            with self.subTest(val=val):
                seen, code, err = _main_kwargs(
                    [self.path, "--inter-stmin", f"7={val}"])
                self.assertIsNone(seen)
                self.assertEqual(code, 1)
                self.assertIn("finite", err)

    def test_the_gui_refuses_what_the_cli_refuses(self):
        for bad in ({"inter_stmin_text": "7=inf"},
                    {"inter_stmin_text": "7=nan"},
                    {"print_every_text": "10000"},
                    {"print_every_text": "-3"},
                    {"print_every_text": "2.5"},
                    {"inter_inacti_text": "7=6.0"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _gui_kw(self.path, **bad)
        for text, value in (("9999", 9999), ("1", 1)):
            with self.subTest(text=text):
                self.assertEqual(
                    _gui_kw(self.path, print_every_text=text)["print_every"],
                    value)

    def test_a_repeated_id_with_another_value_is_refused(self):
        """The last ID=VAL used to win in silence; two values for one
        interface are refused by name (one value repeated is fine)."""
        seen, code, err = _main_kwargs(
            [self.path, "--inter-stmin", "7=0", "--inter-stmin", "7=250"])
        self.assertIsNone(seen)
        self.assertEqual(code, 1)
        self.assertIn("--inter-stmin", err)
        self.assertIn("interface 7 given twice", err)
        seen, code, _err = _main_kwargs(
            [self.path, "--inter-stmin", "7=0", "--inter-stmin", "7=0",
             "--inter-inacti", "7=6", "--inter-inacti", "7=6"])
        self.assertEqual(code, 0)
        self.assertEqual((seen["inter_stmin"], seen["inter_inacti"]),
                         ({7: 0.0}, {7: 6}))
        with self.assertRaises(ValueError) as cm:
            _gui_kw(self.path, inter_stmin_text="7=0 7=250")
        self.assertIn("interface 7 given twice", str(cm.exception))
        self.assertEqual(
            _gui_kw(self.path, inter_stmin_text="7=0, 7=0")["inter_stmin"],
            {7: 0.0})


#: build_convert_kwargs parameter -> its ConverterGUI Tk variable, for each
#: lever K-0P adds to the window (the --inter-stmin / --inter-inacti boxes
#: have no widget, like --inter-gapmin's), and the four opt-out flags of
#: the user's decision 8 (2026-11-01).
_GUI_LEVER_VARS = {
    "damping_curve_window": "damping_curve_window",
    "stop_added_mass": "stop_added_mass",
    "dt2ms_tssfac_product": "dt2ms_tssfac_product",
    "print_every_text": "print_every",
    "tet_isolid1": "tet_isolid1",
    "law1_shell_global_n": "law1_shell_global_n",
    "s2s_type25": "s2s_type25",
    "general_shell_edges": "general_shell_edges",
    "single_surface_sst_gap": "single_surface_sst_gap",
    "contact_birth_death": "contact_birth_death",
    "soft2_iedge_gate": "soft2_iedge_gate",
    "srnde_ishape": "srnde_ishape",
    "maxint_stress_all": "maxint_stress_all",
}


def _gui_class_ast():
    import ast
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "k2rad_gui.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return next(n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "ConverterGUI")


def _gui_method_ast(name: str):
    import ast
    return next(n for n in _gui_class_ast().body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _self_var_get(node):
    """'X' for the expression ``self.X.get()``, else None."""
    import ast
    if (isinstance(node, ast.Call) and not node.args
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"):
        return node.func.value.attr
    return None


class GuiOnConvertWiring(unittest.TestCase):
    """_on_convert and the Tk variables, which the build_convert_kwargs
    tests never reach (the review's G1, G2, G3 and G6): read from the
    source, so they run without a display."""

    def test_on_convert_reads_each_lever_from_its_tk_variable(self):
        import ast
        call = next(n for n in ast.walk(_gui_method_ast("_on_convert"))
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", None) == "build_convert_kwargs")
        passed = {kw.arg: _self_var_get(kw.value) for kw in call.keywords}
        for param, attr in _GUI_LEVER_VARS.items():
            with self.subTest(param=param):
                self.assertEqual(passed.get(param), attr)
        units = call.args[2]
        self.assertIsInstance(units, ast.Tuple)
        self.assertEqual([_self_var_get(e) for e in units.elts],
                         ["u_mass", "u_len", "u_time"])

    def test_the_tk_variables_start_at_the_parameter_defaults(self):
        import ast
        import k2rad_gui
        start = {}
        for node in ast.walk(_gui_method_ast("__init__")):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute)
                    and isinstance(node.targets[0].value, ast.Name)
                    and node.targets[0].value.id == "self"
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == "tk"):
                kws = {k.arg: k.value for k in node.value.keywords}
                start[node.targets[0].attr] = (
                    ast.literal_eval(kws["value"]) if "value" in kws
                    else None)
        sig = inspect.signature(k2rad_gui.build_convert_kwargs).parameters
        for param, attr in _GUI_LEVER_VARS.items():
            with self.subTest(param=param):
                self.assertIn(attr, start)
                self.assertEqual(start[attr], sig[param].default)
                self.assertIs(type(start[attr]), type(sig[param].default))
        for attr in ("u_mass", "u_len", "u_time"):
            with self.subTest(attr=attr):
                self.assertEqual(start[attr], "")


class GuiWindowWiring(unittest.TestCase):
    """The real window (withdrawn), skipped without Tk or a display:
    _on_convert hands build_convert_kwargs the CLI defaults, three blank
    unit boxes, and every flipped checkbox flipped."""

    def test_the_window_hands_over_its_defaults_and_its_flips(self):
        import k2rad_gui
        if not k2rad_gui._HAVE_TK:
            self.skipTest("tkinter is not installed")
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"no display for Tk: {exc}")
        root.withdraw()
        seen = {}

        def spy(*args, **kw):
            seen.clear()
            seen["units"] = args[2]
            seen.update(kw)
            raise ValueError("intercepted by the test")

        real = k2rad_gui.build_convert_kwargs
        sig = inspect.signature(real).parameters
        k2rad_gui.build_convert_kwargs = spy
        try:
            app = k2rad_gui.ConverterGUI(root)
            app._on_convert()
            self.assertEqual(seen["units"], ("", "", ""))
            for param in _GUI_LEVER_VARS:
                with self.subTest(param=param):
                    self.assertEqual(seen[param], sig[param].default)
            for param, attr in _GUI_LEVER_VARS.items():
                var = getattr(app, attr)
                if not isinstance(var, tk.BooleanVar):
                    continue
                var.set(not var.get())
                app._on_convert()
                with self.subTest(flipped=param):
                    self.assertIs(seen[param], not sig[param].default)
                var.set(not var.get())
            app.print_every.set("250")
            app._on_convert()
            self.assertEqual(seen["print_every_text"], "250")
            # the unit row reaches build_convert_kwargs as (mass, length, time)
            app.u_mass.set("kg")
            app.u_len.set("m")
            app.u_time.set("ms")
            app._on_convert()
            self.assertEqual(seen["units"], ("kg", "m", "ms"))
        finally:
            k2rad_gui.build_convert_kwargs = real
            root.destroy()


#: build_convert_kwargs parameter -> a phrase of its checkbox label, for
#: every boolean lever of _GUI_LEVER_VARS (the wave-D review: no test read
#: which Tk variable a checkbox binds, mutant R63)
_GUI_CHECKBOX_LABELS = {
    "damping_curve_window": "Damping LCID curves converted in time",
    "stop_added_mass": "DT2MS < 0 + ENDMAS -> engine /STOP Mmax",
    "dt2ms_tssfac_product": "mass-scaled Tmin = TSSFAC x |DT2MS|",
    "tet_isolid1": "All-tet sections -> /PROP/SOLID Isolid 1",
    "law1_shell_global_n": "All-LAW1 shell sections -> /PROP/SHELL N = 0",
    "s2s_type25": "AUTOMATIC_SURFACE_TO_SURFACE -> two-surface /INTER/TYPE25",
    "general_shell_edges": "AUTOMATIC_GENERAL TYPE25 with Iedge 1",
    "single_surface_sst_gap": "Single-surface shell contact: Gapmin = |SST|",
    "contact_birth_death": "Card-2 BT / DT -> /INTER Tstart / Tstop",
    "soft2_iedge_gate": "SOFT 2 Iedge 22 only with DEPTH",
    "srnde_ishape": "Card E SRNDE 1 -> TYPE25 Ishape 2",
    "maxint_stress_all": "MAXINT > 3 -> /ANIM/SHELL/TENS/STRESS/ALL",
}


def _gui_checkboxes():
    """[(label text, self attribute)] of every Checkbutton the window
    builds in __init__, read from the source (no display needed)."""
    import ast
    out = []
    for node in ast.walk(_gui_method_ast("__init__")):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Checkbutton"):
            kws = {k.arg: k.value for k in node.keywords}
            text, var = kws.get("text"), kws.get("variable")
            out.append((
                text.value if isinstance(text, ast.Constant) else None,
                var.attr if (isinstance(var, ast.Attribute)
                             and isinstance(var.value, ast.Name)
                             and var.value.id == "self") else None))
    return out


class GuiCheckboxBinding(unittest.TestCase):
    """Each boolean lever has ONE checkbox; its label names the lever and
    the default (ON / OFF), and it binds the lever's own Tk variable - the
    one _on_convert reads (GuiOnConvertWiring). In the wave-D review the
    SRNDE checkbox bound to the MAXINT variable, and every test still
    passed (mutant R63)."""

    def test_every_bool_lever_checkbox_binds_its_own_variable(self):
        import k2rad_gui
        boxes = _gui_checkboxes()
        sig = inspect.signature(k2rad_gui.build_convert_kwargs).parameters
        self.assertEqual(set(_GUI_CHECKBOX_LABELS),
                         {p for p in _GUI_LEVER_VARS
                          if isinstance(sig[p].default, bool)})
        for param, phrase in _GUI_CHECKBOX_LABELS.items():
            attr = _GUI_LEVER_VARS[param]
            with self.subTest(param=param):
                bound = [t for t, v in boxes if v == attr]
                self.assertEqual(len(bound), 1, bound)
                self.assertIn(phrase, bound[0])
                self.assertEqual([v for t, v in boxes if t and phrase in t],
                                 [attr])
                self.assertTrue(bound[0].endswith(
                    " - ON" if sig[param].default else " - OFF"), bound[0])


def _stfac_cell(starter: str, header_prefix: str, title_prefix: str = ""):
    """The Stfac cell of the first /INTER block whose header starts with
    *header_prefix* (and whose title line starts with *title_prefix*)."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if (ln.startswith(header_prefix) and i + 1 < len(lines)
                and lines[i + 1].startswith(title_prefix)):
            for k in range(i + 2, len(lines)):
                if lines[k].startswith("/"):
                    break
                if lines[k].split()[:2] == ["#", "Stfac"]:
                    return float(lines[k + 1].split()[0])
    raise AssertionError(f"no Stfac cell under {header_prefix!r}")


class SoftenStfacReach(unittest.TestCase):
    """--soften-stfac reaches the routes its help names, and the help names
    the TYPE25 it does not reach (the review's major 5, measured: the
    *_TIEBREAK post-rupture companion keeps Stfac 0)."""

    def test_the_help_and_the_gui_name_the_tiebreak_companion(self):
        h = _action_help("--soften-stfac")
        for needle in ("post-rupture companion /INTER/TYPE25",
                       "*CONTACT_..._TIEBREAK", "keeps Stfac 0",
                       "--tie-stfac"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)
        self.assertIn("not a tiebreak's post-rupture companion",
                      _gui_source_joined())

    def test_the_named_routes_and_the_named_exception_are_real(self):
        import test_tiebreak_rupture as _tb
        _r, s, _e = _convert(_deck(), soften_stfac=0.3)
        self.assertEqual(_stfac_cell(s, "/INTER/TYPE7/"), 0.3)
        single = _deck().replace(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n" + _row(11, 12, 2, 2),
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 0, 0))
        _r, s, _e = _convert(single, soften_stfac=0.3)
        self.assertEqual(_stfac_cell(s, "/INTER/TYPE25/"), 0.3)
        tie = ("*KEYWORD\n" + _tb._MESH
               + _tb._auto_tiebreak(6, "50.0", "20.0", "0.005") + _tb._TAIL)
        _r, s, _e = _convert(tie, soften_stfac=0.3)
        self.assertEqual(
            _stfac_cell(s, "/INTER/TYPE25/", "post_rupture_contact_"), 0.0)


class FixRoundHelpTexts(unittest.TestCase):
    """Two sentences the review found untrue (its minors)."""

    def test_tet_isolid1_names_the_starters_own_tet_reset(self):
        """sgrtails.F:984-1000 resets every 4- / 10-node tet group to
        Isolid 1 for every material; WARNING 791 (:695-704) is the LAW1
        integration-point message Isolid 14 draws on the way."""
        texts = {"help": _action_help("--tet-isolid1"),
                 "convert()": _collapse(
                     __import__("k2rad").convert.__doc__)}
        for where, text in texts.items():
            with self.subTest(where=where):
                self.assertIn("sgrtails.F:984-1000", text)
                self.assertIn("WARNING 791", text)
                self.assertNotIn("resets Isolid 14 on a LAW1 tet", text)
        self.assertNotIn("no WARNING 791 reset", _gui_source_joined())

    def test_units_help_names_the_spelled_default_exception(self):
        for text in (_action_help("--units"),
                     _collapse(__import__("k2rad").convert.__doc__)):
            with self.subTest(text=text[:40]):
                self.assertIn("spelled-out default Mg mm s", text)
                self.assertIn("still adopts the UNIT flag", text)


# ═════════════════════════════════════════════════════════════════════════════
# Wave B, group K1a-contacts: K-01 K-02 K-03 K-04 K-06 K-07 K-08 K-08B K-13,
# plus the three K-0P review follow-ups handed to the group (the
# --soften-stfac routes and warning, the blast deck's unmappable
# *CONTROL_UNITS card).
#
# The probe deck: a 2 x 2 x 1 hex block (part 1, a PETG-like *MAT_ELASTIC E
# 2400) under two 2 x 2 paperboard shell cards (parts 101 / 102, E 3200, t
# 0.35) at the CardStack pitch 0.3555, card 1's mid-plane 0.0055 above t/2
# over the block top - the air gap of the D1 audit's deck_a. ton-mm-s.
# ═════════════════════════════════════════════════════════════════════════════

_T_CARD = 0.35
_PITCH = 0.3555
_Z_TOP = 2.0
_AIR = 0.0055


def _k1a_deck(contact: str, *, card_e: float = 3200.0, block_dz: float = 1.0,
              z1=None, implicit: bool = False, extra: str = "",
              block_e: float = 2400.0) -> str:
    """Part set 1 = the two cards, part set 2 = the block, node set 9 = the
    block's base (held). *contact* is inserted verbatim."""
    if z1 is None:
        z1 = _Z_TOP + _T_CARD / 2 + _AIR
    nodes = []
    nid = 1
    bid = {}
    for k, z in enumerate((_Z_TOP - block_dz, _Z_TOP)):
        for j in range(3):
            for i in range(3):
                bid[(i, j, k)] = nid
                nodes.append((nid, 6.0 * i, 6.0 * j, z))
                nid += 1
    cid = {}
    for c, z in ((101, z1), (102, z1 + _PITCH)):
        for j in range(3):
            for i in range(3):
                cid[(c, i, j)] = nid
                nodes.append((nid, 1.0 + 5.0 * i, 1.0 + 5.0 * j, z))
                nid += 1
    solids = []
    for e, (i, j) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1)), 1):
        n = [bid[(i, j, 0)], bid[(i + 1, j, 0)], bid[(i + 1, j + 1, 0)],
             bid[(i, j + 1, 0)], bid[(i, j, 1)], bid[(i + 1, j, 1)],
             bid[(i + 1, j + 1, 1)], bid[(i, j + 1, 1)]]
        solids.append("".join(f"{v:>8}" for v in [e, 1] + n))
    shells = []
    eid = 101
    for c in (101, 102):
        for i, j in ((0, 0), (1, 0), (0, 1), (1, 1)):
            n = [cid[(c, i, j)], cid[(c, i + 1, j)], cid[(c, i + 1, j + 1)],
                 cid[(c, i, j + 1)]]
            shells.append("".join(f"{v:>8}" for v in [eid, c] + n))
            eid += 1
    base = [bid[(i, j, 0)] for j in range(3) for i in range(3)]
    ctrl = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 1.0e-5) + "\n"
            if implicit else "")
    return (
        "*KEYWORD\n*TITLE\nk1a contact probe\n"
        + "*CONTROL_TERMINATION\n" + _row(1.0e-4) + "\n" + ctrl
        + "*NODE\n"
        + "".join(f"{i:>8}{x:>16.6f}{y:>16.6f}{z:>16.6f}\n"
                  for i, x, y, z in nodes)
        + "*ELEMENT_SOLID\n" + "\n".join(solids) + "\n"
        + "*ELEMENT_SHELL\n" + "\n".join(shells) + "\n"
        + "*PART\nblock\n" + _row(1, 1, 1) + "\n"
        + "*PART\ncard_1\n" + _row(101, 2, 2) + "\n"
        + "*PART\ncard_2\n" + _row(102, 2, 2) + "\n"
        + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
        + "*SECTION_SHELL\n" + _row(2, 2, 0.8333, 2) + "\n"
        + _row(_T_CARD, _T_CARD, _T_CARD, _T_CARD) + "\n"
        + "*MAT_ELASTIC\n" + _row(1, 1.25e-9, block_e, 0.38) + "\n"
        + "*MAT_ELASTIC\n" + _row(2, 1.35e-9, card_e, 0.35) + "\n"
        + "*SET_PART_LIST\n" + _row(1) + "\n" + _row(101, 102) + "\n"
        + "*SET_PART_LIST\n" + _row(2) + "\n" + _row(1) + "\n"
        + "*SET_NODE_LIST\n" + _row(9) + "\n"
        + _row(*base[:8]) + "\n" + _row(*base[8:]) + "\n"
        + "*BOUNDARY_SPC_SET\n" + _row(9, 0, 1, 1, 1, 1, 1, 1) + "\n"
        + "*DATABASE_GLSTAT\n" + _row(1.0e-5) + "\n"
        + contact + extra + "*END\n")


#: the nodes of the two cards in _k1a_deck (18 block nodes come first)
_CARD_NODES = list(range(19, 37))


def _k1a_ass(cid: int, ssid: int, sstyp: int, card2=(0.2, 0.2), card3=(),
             kw: str = "CONTACT_AUTOMATIC_SINGLE_SURFACE_ID",
             tail: str = "") -> str:
    """A single-surface *CONTACT with an _ID card (cards 1-3, then *tail*)."""
    return (f"*{kw}\n{cid:>10}card_self\n" + _row(ssid, 0, sstyp, 0) + "\n"
            + _row(*card2) + "\n" + _row(*card3) + "\n" + tail)


def _k1a_s2s(cid: int, ssid: int = 1, msid: int = 2, sstyp: int = 2,
             mstyp: int = 2, card2=(0.2, 0.2), card3=(),
             kw: str = "CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID",
             tail: str = "") -> str:
    """A two-sided *CONTACT with an _ID card (cards 1-3, then *tail*)."""
    return (f"*{kw}\n{cid:>10}tool_to_cards\n"
            + _row(ssid, msid, sstyp, mstyp) + "\n" + _row(*card2) + "\n"
            + _row(*card3) + "\n" + tail)


def _inter_rows(starter: str, header: str):
    """The data rows (token lists) of the block whose first line is
    *header* - the title line and the '#' comment rows skipped."""
    lines = starter.splitlines()
    i = lines.index(header)
    rows = []
    for ln in lines[i + 2:]:
        if ln.startswith("/"):
            break
        if not ln.startswith("#"):
            rows.append(ln.split())
    return rows


def _ids_under(starter: str, header: str):
    """Every integer of the id-list card *header* (/GRNOD, /SURF, /GRSHEL)."""
    return [int(v) for row in _inter_rows(starter, header) for v in row]


def _type7(starter: str, iid: int) -> dict:
    """The /INTER/TYPE7 cells the K1a tests read, by name."""
    r = _inter_rows(starter, f"/INTER/TYPE7/{iid}")
    return {"slav": int(r[0][0]), "mast": int(r[0][1]), "istf": r[0][2],
            "igap": r[0][4], "fpenmax": r[1][2], "stmin": r[2][0],
            "stfac": float(r[3][0]), "fric": float(r[3][1]),
            "gapmin": float(r[3][2]), "inacti": r[4][1]}


def _k1a_has_fast_proximity() -> bool:
    from k2rad import gapmin as _gm
    return _gm.fast_proximity_available()


# ── K-01 ─────────────────────────────────────────────────────────────────────

#: /INTER/TYPE7/7 and /INTER/TYPE25/21 of _k1a_deck(_k1a_ass(7, 1, 2)) and
#: _k1a_deck(_k1a_ass(21, 0, 0)) as the tree before the K1a changes wrote
#: them (scratch probe_now.py on the wave-B snapshot).
_K01_TYPE7_7 = (
    "/INTER/TYPE7/7",
    "card_self",
    "#  Slav_id   Mast_id      Istf      Ithe      Igap                Ibag"
    "      Idel     Icurv      Iadm",
    "     90001     90002         4         0         0                   0"
    "         2         0         0",
    "#          Fscalegap             GAP_MAX             Fpenmax",
    "                   0                   0            0.999999",
    "#              Stmin               Stmax          %mesh_size"
    "               dtmin  Irem_gap",
    "                1000                   0                   0"
    "                   0         0",
    "#              Stfac                Fric              Gapmin"
    "              Tstart               Tstop",
    "                   0                 0.2                   0"
    "                   0                   0",
    "#      IBC                        Inacti                VisS"
    "                VisF              Bumult",
    "       000                             5                   0"
    "                   0                   0",
    "#    Ifric    Ifiltr               Xfreq     Iform   sens_ID",
    "         0         0                   0         2         0",
)
_K01_TYPE25_21 = (
    "/INTER/TYPE25/21",
    "card_self",
    "# surf_ID1  surf_ID2      Istf      Ithe      Igap   Irem_i2"
    "                Idel     Iedge    IPSTIF",
    "     90001         0         4         0         2         0"
    "                   2      1000         0",
    "# grnd_IDs                     Gap_scale          %mesh_size"
    "           Gap_max_s           Gap_max_m",
    "         0                           1.0                   0"
    "                1e30                1e30",
    "#              Stmin               Stmax     Igap0    Ishape"
    "          Edge_angle          STFAC_MDT",
    "                   0                1e30      1000         0"
    "                   0                   0",
    "#              Stfac                Fric           Tpressfit"
    "              Tstart               Tstop",
    "                   1                 0.2                   0"
    "                   0                   0",
    "#      IBC               IVIS2    Inacti                VISs    Ithick"
    "                          Pmax",
    "       000                   0         5                0.05         0"
    "                             0",
)


class AssRouteIsNamed(unittest.TestCase):
    """K-01: which *CONTACT_AUTOMATIC_SINGLE_SURFACE route was taken. SSID =
    0 -> the all-parts /INTER/TYPE25 (explicit); SSID != 0 -> the
    /INTER/TYPE7 self-contact on explicit decks too; SURFATYP 5 with SSID !=
    0 is dropped and named. No byte moves."""

    def test_a_part_set_ssid_is_a_type7_self_contact_on_an_explicit_deck(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2)))
        self.assertIn("/INTER/TYPE7/7", s)
        self.assertNotIn("/INTER/TYPE25/", s)
        t7 = _type7(s, 7)
        self.assertEqual(_ids_under(s, f"/GRNOD/NODE/{t7['slav']}"),
                         _CARD_NODES)
        grshel = _ids_under(s, f"/SURF/GRSHEL/{t7['mast']}")
        self.assertEqual(_ids_under(s, f"/GRSHEL/SHEL/{grshel[0]}"),
                         list(range(101, 109)))
        self.assertTrue(_has(
            res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE 7: SSID = 1",
            "/INTER/TYPE7/7 self-contact", f"/GRNOD/{t7['slav']}",
            "18 non-rigid nodes", f"/SURF/{t7['mast']}", "SSID = 0 gives"))

    def test_ssid_0_is_the_all_parts_type25_with_its_own_text(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)))
        self.assertIn("/INTER/TYPE25/21", s)
        self.assertTrue(_has(
            res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE 21: SSID = 0",
            "explicit analysis", "/INTER/TYPE25/21 all-parts self-contact",
            "A part or part set in SSID", "/INTER/TYPE7"))
        self.assertFalse(_has(res.warnings, "is kept for implicit only"))

    def test_the_route_text_names_the_decks_own_keyword(self):
        for kw in ("CONTACT_AUTOMATIC_GENERAL_ID", "CONTACT_SINGLE_SURFACE_ID"):
            with self.subTest(kw=kw):
                res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, kw=kw)))
                self.assertTrue(_has(
                    res.warnings, f"*{kw[:-3]} 21: SSID = 0",
                    "all-parts self-contact"))

    def test_surfatyp_5_with_a_nonzero_ssid_is_dropped_and_named(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(22, 7, 5)))
        self.assertNotIn("/INTER/", s)
        self.assertTrue(_has(
            res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE 22",
            "SURFATYP 5", "Vol I R17 p.11-25", "SSID = 7",
            "REMEDY: set SSID to 0"))
        self.assertFalse(_has(res.warnings, "22", "it names no part, part set"))

    def test_the_route_texts_change_no_byte(self):
        """The two interfaces the texts describe are the cards k2rad wrote
        before them (the blocks below were printed by the pre-K1a tree; the
        pinned plain deck's S2S is ByteIdentityAtMaster's)."""
        for deck, want in ((_k1a_deck(_k1a_ass(7, 1, 2)), _K01_TYPE7_7),
                           (_k1a_deck(_k1a_ass(21, 0, 0)), _K01_TYPE25_21)):
            with self.subTest(head=want[0]):
                _r, s, _e = _convert(deck)
                lines = s.splitlines()
                i = lines.index(want[0])
                self.assertEqual(lines[i:i + len(want)], list(want))

    def test_the_docstrings_state_the_ssid_condition(self):
        from k2rad import handlers, state
        from k2rad.writer import contacts
        for where, doc in (
                ("handle_contact_automatic_general",
                 handlers.handle_contact_automatic_general.__doc__),
                ("ContactAutoGeneral", state.ContactAutoGeneral.__doc__),
                ("_emit_inter_type25_self",
                 contacts._emit_inter_type25_self.__doc__)):
            with self.subTest(where=where):
                text = _collapse(doc)
                self.assertIn("SSID = 0", text)
                self.assertIn("SSID != 0", text)

    def test_an_implicit_deck_names_the_same_type7_route(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2), implicit=True))
        self.assertIn("/INTER/TYPE7/7", s)
        self.assertTrue(_has(
            res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE 7: SSID = 1",
            "(a part set, SURFATYP 2)", "/INTER/TYPE7/7 self-contact",
            "on this implicit deck", "18 non-rigid nodes"))

    def test_the_surfatyp_5_drop_draws_no_id(self):
        """The drop comes before the side resolvers, so the next contact's
        groups keep the ids they get without the dropped card."""
        _r, alone, _e = _convert(_k1a_deck(_k1a_s2s(12)))
        _r, both, _e = _convert(_k1a_deck(_k1a_ass(22, 7, 5) + _k1a_s2s(12)))
        self.assertEqual(_type7(both, 12), _type7(alone, 12))

    def test_ssid_0_on_an_implicit_deck_has_no_type25_text(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0), implicit=True))
        self.assertIn("/INTER/TYPE7/21", s)
        self.assertFalse(_has(res.warnings, "all-parts self-contact (one "))


# ── K-02 ─────────────────────────────────────────────────────────────────────

def _stmin_warnings(res):
    return [w for w in res.warnings if "is above the estimated contact "
            "stiffness" in w]


class StminOverrideAndFloor(unittest.TestCase):
    """K-02: --inter-stmin ID=VAL writes the Stmin cell of that TYPE7 only
    (default 1000 = today's bytes); a default-ON warning names the floor
    where it is above the estimated Istf stiffness (shell main Km = Stfac x
    E x t, i7sti3.F:615; shell secondary Ks = E x t, asstifi.F:52)."""

    def test_the_default_writes_1000(self):
        _r, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2) + _k1a_s2s(8)))
        self.assertEqual(_type7(s, 7)["stmin"], "1000")
        self.assertEqual(_type7(s, 8)["stmin"], "1000")

    def test_the_override_reaches_its_own_interface_only(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2) + _k1a_s2s(8)),
                              inter_stmin={7: 0.0})
        self.assertEqual(_type7(s, 7)["stmin"], "0")
        self.assertEqual(_type7(s, 8)["stmin"], "1000")
        self.assertTrue(_has(res.warnings, "--inter-stmin 7=0",
                             "/INTER/TYPE7/7 Stmin 0"))
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2)),
                              inter_stmin={7: 250.0})
        self.assertEqual(_type7(s, 7)["stmin"], "250")

    def test_paperboard_with_sfs_0_15_names_the_estimate(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2, card3=(0.15,))))
        self.assertEqual(_type7(s, 7)["stfac"], 0.15)
        self.assertEqual(_type7(s, 7)["stmin"], "1000")    # bytes as before
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        for needle in ("/INTER/TYPE7 7: Stmin 1000", "Istf 4",
                       "Km = Stfac x E x t = 0.15 x 3200 x 0.35 = 168",
                       "Ks = E x t = 3200 x 0.35 = 1120",
                       "K = min(Km, Ks) = 168",
                       "MAX(Stmin, K) = 1000",
                       "i7sti3.F:615", "asstifi.F:52", "i7cor3.F:277-288",
                       "below Stfac 0.893",
                       "1000 = 1000 N/mm in this deck's Mg/mm/s units",
                       "--inter-stmin 7=0"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])

    def test_sfs_0_95_and_a_steel_card_stay_silent(self):
        for deck in (_k1a_deck(_k1a_ass(7, 1, 2, card3=(0.95,))),
                     _k1a_deck(_k1a_ass(7, 1, 2, card3=(0.15,)),
                               card_e=210000.0),
                     _k1a_deck(_k1a_ass(7, 1, 2))):
            with self.subTest(deck=deck[-260:-200]):
                res, _s, _e = _convert(deck)
                self.assertEqual(_stmin_warnings(res), [])

    def test_an_overridden_floor_is_compared_as_written(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2, card3=(0.15,))),
                               inter_stmin={7: 0.0})
        self.assertEqual(_stmin_warnings(res), [])
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2, card3=(0.95,))),
                               inter_stmin={7: 5000.0})
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("Stmin 5000 (--inter-stmin 7=5000)", ws[0])

    def test_the_unit_sentence_follows_the_begin_labels(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2, card3=(0.15,))),
                               units=("kg", "mm", "ms"))
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("1000 = 1e+06 N/mm in this deck's kg/mm/ms units",
                      ws[0])

    def test_istf_2_takes_the_average(self):
        """The SOFT = -7 GENERAL route writes Istf 2: K = (Km + Ks) / 2."""
        deck = _k1a_deck(_k1a_ass(
            31, 1, 2, card3=(0.15,), kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_row(-7) + "\n"))
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 31)["istf"], "2")
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("K = (Km + Ks) / 2 = 644", ws[0])
        self.assertIn("Istf 2", ws[0])

    def test_an_id_no_type7_took_is_named(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)),
                               inter_stmin={21: 0.0, 99: 0.0})
        self.assertTrue(_has(res.warnings, "--inter-stmin 21=0",
                             "/INTER/TYPE25", "override ignored"))
        self.assertTrue(_has(res.warnings, "--inter-stmin 99=0",
                             "no /INTER/TYPE7/99", "override ignored"))

    def test_the_help_names_the_roadmap_record(self):
        h = _action_help("--inter-stmin")
        self.assertIn("ROADMAP round-9 NOT entry 11", h)
        self.assertIn("K = 0", h)
        for needle in ("i7sti3.F:615", "asstifi.F:52", "i7sti3.F:444",
                       "A default-ON warning"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)

    def test_a_soft_solid_main_gets_the_solid_formula(self):
        """S2S cards (shell secondary, Ks = 3200 x 0.35 = 1120) on a
        foam-soft block E 10, nu 0.38: B = 10 / (3 (1 - 0.76)) = 13.89; the
        block's 16 boundary faces give A^2/V = 36 (8 top / bottom 6 x 6
        faces on 36-volume hexes) and 1 (8 side 6 x 1 faces), median 18.5;
        Km = 1 x 13.89 x 18.5 = 256.9 (blank SFS -> Stfac 0 -> 1.0)."""
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_e=10.0))
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        for needle in ("/INTER/TYPE7 12: Stmin 1000",
                       "Km = Stfac x B x A^2/V = 1 x 13.89 x 18.5 = 256.9 "
                       "(the median of 16 main faces)", "i7sti3.F:444",
                       "Ks = E x t = 3200 x 0.35 = 1120",
                       "K = min(Km, Ks) = 256.9", "below Stfac 3.89"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])
        self.assertEqual(_type7(s, 12)["stmin"], "1000")
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(12)))      # E 2400: silent
        self.assertEqual(_stmin_warnings(res), [])

    def test_a_solid_secondary_gets_the_nodal_formula(self):
        """The block on the cards: the 18 block nodes are all surface nodes,
        V_node = 36 / 8 x (1 | 2 | 4) elements, the median (2 V_node)^(1/3)
        = 18^(1/3) = 2.621; B 13.89 -> Ks = 36.4 under Km = 1120, and no
        Stfac lifts K above the floor (Stfac scales the main side only)."""
        res, _s, _e = _convert(_k1a_deck(
            _k1a_s2s(15, ssid=2, msid=1), block_e=10.0))
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        for needle in ("Ks = B x (2 V_node)^(1/3) = 13.89 x 2.621 = 36.4 "
                       "(the median of 18 surface nodes)", "asstifi.F:50",
                       "Km = Stfac x E x t = 1 x 3200 x 0.35 = 1120",
                       "no Stfac lifts K above the floor"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])

    def test_the_general_type7_takes_the_override(self):
        deck = _k1a_deck(_k1a_ass(
            31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_row(-7) + "\n"))
        res, s, _e = _convert(deck, inter_stmin={31: 0.0})
        self.assertEqual(_type7(s, 31)["stmin"], "0")
        self.assertEqual(_stmin_warnings(res), [])

    def test_a_stiff_pair_skips_the_exact_walk(self):
        """The cost bound: steel cards on a steel block - the sampled
        estimate (Ks = E x t = 73 500) is more than 10 x the floor, so the
        per-element walk of _part_stiffness never runs."""
        from k2rad.writer import contacts
        calls = []
        real = contacts._part_stiffness

        def spy(state, pids):
            calls.append(sorted(pids))
            return real(state, pids)

        contacts._part_stiffness = spy
        try:
            res, _s, _e = _convert(_k1a_deck(
                _k1a_s2s(12), card_e=210000.0, block_e=210000.0))
            self.assertEqual(calls, [])
            self.assertEqual(_stmin_warnings(res), [])
            _convert(_k1a_deck(_k1a_s2s(12)))           # paperboard: walked
            self.assertEqual(calls, [[1, 101, 102]])
        finally:
            contacts._part_stiffness = real

    def test_the_implicit_stub_is_not_estimated(self):
        """k2rad's own stub is no card of the deck: no floor warning for it,
        even where every part is soft enough to draw one (the SSID = 0
        implicit route of a deck card, below, does)."""
        res, s, _e = _convert(_k1a_deck("", implicit=True, card_e=10.0,
                                        block_e=10.0))
        self.assertIn("/INTER/TYPE7/", s)            # the injected stub
        self.assertEqual(_stmin_warnings(res), [])
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0), implicit=True,
                                         card_e=10.0, block_e=10.0))
        self.assertEqual(len(_stmin_warnings(res)), 1)


# ── K-03 ─────────────────────────────────────────────────────────────────────

class ShellOffsetClampNamesTheRoutes(unittest.TestCase):
    """K-03 (text only): a clamped shell-offset Gapmin names the two routes
    that give t/2 - Card-3 SST = the card thickness, or --inter-gapmin
    <id>=<t/2> - and the count of main sides shorter than t."""

    def test_the_clamp_warning_names_sst_inter_gapmin_and_the_count(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_dz=0.3))
        self.assertEqual(_type7(s, 12)["gapmin"], 0.15)     # unchanged
        w = [x for x in res.warnings if "/INTER/TYPE7 12: LS-DYNA offsets" in x]
        self.assertEqual(len(w), 1, w)
        for needle in ("CLAMPED", "8 of the main surface's 32 unique "
                       "segment sides are shorter than t = 0.35",
                       "the shortest 0.3",
                       "Card-3 SST = 0.35", "--inter-gapmin 12=0.175",
                       "--no-shell-offset-gapmin", "0.1 x 0.3 = 0.03"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w[0])
        self.assertNotIn("defeature", w[0])

    def test_sst_on_card_3_gives_t_half_without_the_clamp(self):
        res, s, _e = _convert(_k1a_deck(
            _k1a_s2s(12, card3=(1.0, 1.0, _T_CARD)), block_dz=0.3))
        self.assertEqual(_type7(s, 12)["gapmin"], 0.175)
        self.assertFalse(_has(res.warnings, "CLAMPED"))

    def test_the_help_names_both_routes(self):
        h = _action_help("--shell-offset-gapmin")
        for needle in ("Card-3 SST", "--inter-gapmin", "0.1 x"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)

    def test_the_inter_gapmin_route_gives_t_half_without_the_clamp(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_dz=0.3),
                              inter_gapmin={12: 0.175})
        self.assertEqual(_type7(s, 12)["gapmin"], 0.175)
        self.assertFalse(_has(res.warnings, "CLAMPED"))

    def test_an_unclamped_offset_names_no_route(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12)))
        self.assertEqual(_type7(s, 12)["gapmin"], 0.175)
        w = [x for x in res.warnings if "/INTER/TYPE7 12: LS-DYNA offsets" in x]
        self.assertEqual(len(w), 1, w)
        self.assertNotIn("unique segment sides", w[0])
        self.assertNotIn("smaller still", w[0])


# ── K-04 ─────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_k1a_has_fast_proximity(),
                     "--auto-gapmin needs numpy + scipy")
class AutoGapminOffsetAware(unittest.TestCase):
    """K-04: --auto-gapmin (opt-in) writes T + f x (d - T) on a shell side,
    T = t_s / 2 (+ t_m / 2 for a shell main), names itself on the override
    line and says which route a skipped interface took."""

    def test_cards_over_the_block_get_t_half_plus_f_times_the_air(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12)), auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.1794)
        self.assertTrue(_has(
            res.warnings, "--auto-gapmin INTER 12", "0.1805",
            "T = 0.175", "Gapmin=0.1794", "T + 0.8 x (d - T)"))
        self.assertTrue(_has(res.warnings, "INTER 12: Gapmin overridden",
                             "0.1794", "via --auto-gapmin"))
        self.assertFalse(_has(res.warnings, "INTER 12: Gapmin overridden",
                              "via --inter-gapmin"))

    def test_a_shell_main_adds_its_own_half_thickness(self):
        deck = _k1a_deck(_k1a_s2s(13, ssid=102, msid=101, sstyp=3, mstyp=3))
        _r, s, _e = _convert(deck, auto_gapmin=True)
        self.assertEqual(_type7(s, 13)["gapmin"], 0.3544)  # 0.35 + 0.8 x 0.0055

    def test_sst_and_sfst_set_the_secondary_thickness(self):
        """Vol I R17 p.11-33/34: SAST overrides the thickness and SFSAT
        scales it, ignored when SAST is non-zero."""
        for card3, want in (((1.0, 1.0, 0.2), 0.1644),
                            ((1.0, 1.0, 0.0, 0.0, 0.5), 0.1619),
                            ((1.0, 1.0, 0.2, 0.0, 0.5), 0.1644)):
            with self.subTest(card3=card3):
                _r, s, _e = _convert(_k1a_deck(_k1a_s2s(12, card3=card3)),
                                     auto_gapmin=True)
                self.assertEqual(_type7(s, 12)["gapmin"], want)

    def test_an_overlapping_pair_keeps_f_times_d_and_warns(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), z1=_Z_TOP + 0.1),
                              auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.08)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 12",
                             "overlap", "d = 0.1", "T = 0.175"))

    def test_the_self_contact_skip_names_its_route(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2) + _k1a_s2s(12)),
                               auto_gapmin=True)
        self.assertTrue(_has(
            res.warnings, "--auto-gapmin INTER 7: no clearance suggestion",
            "/INTER/TYPE7 self-contact", "leave SST/MST blank",
            "i7sti3.F:1055-1066"))
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)),
                               auto_gapmin=True)
        self.assertTrue(_has(
            res.warnings, "--auto-gapmin INTER 21: no clearance suggestion",
            "/INTER/TYPE25", "Gap_scale"))

    def test_a_deck_without_a_measurable_interface_says_what_it_has(self):
        deck = _k1a_deck(_k1a_s2s(
            41, kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
            tail=_row(0, 1, 1) + "\n"))
        res, _s, _e = _convert(deck, auto_gapmin=True)
        self.assertFalse(_has(res.warnings, "no contact interfaces found"))
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 41",
                             "/INTER/TYPE25"))

    def test_the_offset_value_is_capped_at_half_the_smallest_main_side(self):
        """A 0.3-thick block: 0.1794 > 0.5 x 0.3, so 0.15 is written, the
        cap of the shell-offset Gapmin."""
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_dz=0.3),
                              auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.15)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 12",
                             "Gapmin=0.15", "CAPPED at 0.5 x the smallest "
                             "main-segment side = 0.15", "WARNING 94"))

    def test_the_other_routes_are_named(self):
        deck = _k1a_deck(_k1a_ass(31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                                  tail=_row(-11) + "\n"))
        res, _s, _e = _convert(deck, auto_gapmin=True)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 31",
                             "SOFT = -11", "/INTER/TYPE11", "SOFT-routed"))
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(12)), auto_gapmin=True,
                               s2s_type25=True)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 12",
                             "two-surface /INTER/TYPE25 (--s2s-type25)",
                             "Gap_scale"))

    def test_the_suggestion_carries_its_offset_fields(self):
        """suggest_gapmins (the --suggest-gapmin path, no writer run)."""
        from k2rad import gapmin
        st = _dispatch(_k1a_deck(_k1a_s2s(12)))
        sugg, _skipped = gapmin.suggest_gapmins(st, 0.8)
        self.assertEqual(sugg[12].suggested_gapmin, 0.1794)
        self.assertEqual(sugg[12].offset, 0.175)
        self.assertIn("secondary t/2 = 0.175 (/SHELL t 0.35",
                      sugg[12].offset_note)
        self.assertFalse(sugg[12].overlap)
        self.assertEqual(sugg[12].cap, 0.0)
        st = _dispatch(_k1a_deck(_k1a_s2s(12, kw="CONTACT_SURFACE_TO_"
                                          "SURFACE_ID")))
        sugg, _skipped = gapmin.suggest_gapmins(st, 0.8)
        # the non-AUTOMATIC spelling offsets nothing without SHLTHK
        self.assertEqual(sugg[12].offset, 0.0)
        self.assertEqual(sugg[12].suggested_gapmin, 0.1444)

    def test_suggest_gapmin_prints_the_offset(self):
        import k2rad.cli as _cli
        from k2rad.gapmin import analyze_file
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "k1a.k")
            with open(path, "w") as fh:
                fh.write(_k1a_deck(_k1a_s2s(12)))
            buf = io.StringIO()
            from contextlib import redirect_stdout
            with redirect_stdout(buf):
                _cli._print_gapmin_suggestions(path, 0.8, analyze_file)
        out = buf.getvalue()
        self.assertIn("Gapmin = 0.1794", out)
        self.assertIn("T = 0.175", out)
        self.assertIn("--inter-gapmin 12=0.1794", out)


# ── K-06 ─────────────────────────────────────────────────────────────────────

class InterInactiSix(unittest.TestCase):
    """K-06: --inter-inacti ID=6 replaces the 5 written for IGNORE on a
    TYPE7 / TYPE11 / TYPE19; a TYPE25 id is refused by name (WARNING 1559);
    the *_INTERFERENCE 0, the implicit bootstrap 0 and the
    --deformable-contact-recipe 5 are never overridden."""

    def test_a_type7_takes_6_with_its_fpenmax(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12) + _k1a_ass(7, 1, 2)),
                              inter_inacti={12: 6})
        self.assertEqual(_type7(s, 12)["inacti"], "6")
        self.assertEqual(_type7(s, 12)["fpenmax"], "0.999999")
        self.assertEqual(_type7(s, 7)["inacti"], "5")
        self.assertTrue(_has(res.warnings, "--inter-inacti 12=6",
                             "/INTER/TYPE7/12 Inacti 6", "i7pwr3.F:250-257"))

    def test_a_type25_id_is_refused_by_name(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)),
                              inter_inacti={21: 6})
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/21")[4][2], "5")
        self.assertTrue(_has(res.warnings, "--inter-inacti 21=6", "refused",
                             "/INTER/TYPE25/21", "WARNING 1559",
                             "hm_read_inter_type25.F:603-610"))

    def test_the_general_type11_and_type19_take_6(self):
        for soft, head in ((-11, "/INTER/TYPE11/31"), (-19, "/INTER/TYPE19/31")):
            with self.subTest(soft=soft):
                deck = _k1a_deck(_k1a_ass(
                    31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                    tail=_row(soft) + "\n"))
                _r, s, _e = _convert(deck, inter_inacti={31: 6})
                rows = _inter_rows(s, head)
                ibc = next(r for r in rows if r[0] == "000")
                self.assertEqual(ibc[1], "6")

    def test_interference_and_the_implicit_bootstrap_are_untouched(self):
        deck = _k1a_deck(_k1a_s2s(
            13, kw="CONTACT_SURFACE_TO_SURFACE_INTERFERENCE_ID",
            tail=_row(0, 0) + "\n"))
        res, s, _e = _convert(deck, inter_inacti={13: 6})
        self.assertEqual(_type7(s, 13)["inacti"], "0")
        self.assertTrue(_has(res.warnings, "--inter-inacti 13=6",
                             "not applied", "INTERFERENCE"))
        deck = _k1a_deck(_k1a_s2s(12, card3=(1.0, 1.0, 0.2, 0.2)),
                         implicit=True)
        res, s, _e = _convert(deck, inter_inacti={12: 6})
        self.assertEqual(_type7(s, 12)["inacti"], "0")
        self.assertTrue(_has(res.warnings, "--inter-inacti 12=6",
                             "not applied", "bootstrap"))

    def test_the_recipe_5_is_untouched(self):
        deck = _k1a_deck(_k1a_s2s(14, ssid=101, msid=102, sstyp=3, mstyp=3),
                         implicit=True)
        res, s, _e = _convert(deck, inter_inacti={14: 6},
                              deformable_contact_recipe=True)
        self.assertEqual(_type7(s, 14)["inacti"], "5")
        self.assertTrue(_has(res.warnings, "--inter-inacti 14=6",
                             "not applied", "--deformable-contact-recipe"))

    def test_an_id_no_interface_took_is_named(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(12)),
                               inter_inacti={98: 6})
        self.assertTrue(_has(res.warnings, "--inter-inacti 98=6",
                             "no interface 98", "override ignored"))

    def test_the_docstrings_no_longer_say_inacti_6_moves_nodes(self):
        from k2rad.writer import contacts
        for fn in (contacts._ignore_to_inacti,
                   contacts._make_general_interfaces):
            with self.subTest(fn=fn.__name__):
                text = _collapse(fn.__doc__)
                self.assertNotIn("Inacti=3/6", text)
                self.assertIn("Inacti 3 / 4", text)
                self.assertIn("ae17cbf", text)

    def test_the_routed_implicit_node_to_surface_type7_takes_6(self):
        """Gated at the TYPE25-section call: the routed implicit
        *CONTACT_NODES_TO_SURFACE is an /INTER/TYPE7."""
        nset = "*SET_NODE_LIST\n" + _row(5) + "\n" + "".join(
            _row(*_CARD_NODES[k:k + 8]) + "\n" for k in range(0, 9, 8))
        deck = _k1a_deck(_k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3,
                                  kw="CONTACT_NODES_TO_SURFACE_ID"),
                         implicit=True, extra=nset)
        res, s, _e = _convert(deck, inter_inacti={16: 6})
        self.assertEqual(_type7(s, 16)["inacti"], "6")
        self.assertTrue(_has(res.warnings, "--inter-inacti 16=6",
                             "/INTER/TYPE7/16 Inacti 6"))

    def test_an_eroding_type25_id_is_refused_too(self):
        deck = _k1a_deck(_k1a_s2s(
            41, kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
            tail=_row(0, 1, 1) + "\n"))
        res, s, _e = _convert(deck, inter_inacti={41: 6})
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/41")[4][2], "5")
        self.assertTrue(_has(res.warnings, "--inter-inacti 41=6", "refused",
                             "WARNING 1559"))


# ── K-07 ─────────────────────────────────────────────────────────────────────

_K07 = "are output flags"


class FrictionTypedIntoCardOne(unittest.TestCase):
    """K-07: friction typed into card 1's SAPR / SBPR (fields 7 / 8, the
    integer output flags 0 / 1 / 2) with no card 2 is named: Fric = 0."""

    def test_the_agents_card_one_is_named(self):
        deck = _k1a_deck("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                         + _row(1, 0, 2, 0, 0, 0, 0.22, 0.20) + "\n")
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 90001 if "/INTER/TYPE7/90001" in s
                                else int(re.search(r"/INTER/TYPE7/(\d+)",
                                                   s).group(1)))["fric"], 0.0)
        self.assertTrue(_has(
            res.warnings, "SAPR = 0.22", "SBPR = 0.2", _K07,
            "Vol I R17 p.11-24", "no Card 2", "Fric = 0 (frictionless)",
            "Card 2 FS -> Fric", "Card 3 SFS -> Stfac"))

    def test_legal_flags_with_a_card_two_are_silent(self):
        deck = _k1a_deck("*CONTACT_AUTOMATIC_SINGLE_SURFACE_ID\n"
                         + f"{7:>10}card_self\n"
                         + _row(1, 0, 2, 0, 0, 0, 1, 1) + "\n"
                         + _row(0.22, 0.20) + "\n" + _row() + "\n")
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 7)["fric"], 0.22)
        self.assertFalse(_has(res.warnings, _K07))

    def test_a_non_flag_value_with_a_card_two_is_named_without_fric_0(self):
        deck = _k1a_deck(_k1a_ass(7, 1, 2).replace(
            _row(1, 0, 2, 0), _row(1, 0, 2, 0, 0, 0, 0.22, 0)))
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 7)["fric"], 0.2)
        self.assertTrue(_has(res.warnings, "SAPR = 0.22", _K07))
        self.assertFalse(_has(res.warnings, "Fric = 0 (frictionless)"))

    def test_an_integer_outside_0_1_2_is_named_and_1_0_is_legal(self):
        for cell, named in ((3, True), ("1.0", False), (2, False)):
            with self.subTest(cell=cell):
                deck = _k1a_deck("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                                 + _row(1, 0, 2, 0, 0, 0, cell, 0) + "\n")
                res, _s, _e = _convert(deck)
                self.assertEqual(_has(res.warnings, _K07), named)
                if named:
                    self.assertTrue(_has(res.warnings, "SAPR = 3", _K07,
                                         "Fric = 0 (frictionless)"))

    def test_the_airbag_iflag_slot_is_tested_for_an_integer_only(self):
        card = ("*CONTACT_AIRBAG_SINGLE_SURFACE\n"
                + _row(1, "", 2, "", 0, "", 0, "{iflag}") + "\n")
        res, _s, _e = _convert(_k1a_deck(card.format(iflag=1)))
        self.assertFalse(_has(res.warnings, _K07))
        res, _s, _e = _convert(_k1a_deck(card.format(iflag=0.5)))
        self.assertTrue(_has(res.warnings, "IFLAG = 0.5", _K07))


# ── K-08 ─────────────────────────────────────────────────────────────────────

class AutomaticS2sIsOneWay(unittest.TestCase):
    """K-08: the AUTOMATIC two-way pair gets the 'twoway' note - one-way
    TYPE7, and the levers that check both sides. Log only."""

    def test_the_note_names_one_way_and_the_remedies(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(12)))
        self.assertTrue(_has(
            res.warnings, "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE 12:",
            "is one-way", "--s2s-type25", "*CONTACT_ERODING_SURFACE_TO_SURFACE",
            "/SURF/PART/ALL", "a second contact with SSID and MSID swapped",
            "lip coupon"))

    def test_the_note_names_no_flag_a_plain_deck_must_not_see(self):
        """The plain-deck guarantees of tests/test_converter.py
        (ForceControlStabilizationTests) and tests/test_eroding_contacts.py
        (ByteIdentityTests) hold for the new note."""
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        note = _CONTACT_SPELLING_NOTES["twoway_auto"]
        for needle in ("--inter-gapmin", "--soften-stfac", "--ground-springs",
                       "eroding"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, note)

    def test_the_non_automatic_spelling_keeps_its_twoway_record(self):
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, kw="CONTACT_SURFACE_TO_SURFACE_ID")))
        self.assertTrue(_has(res.warnings,
                             _CONTACT_SPELLING_NOTES["twoway"][:80]))
        self.assertFalse(_has(res.warnings, "lip coupon"))

    def test_the_one_way_spelling_does_not_get_it(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, kw="CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_ID")))
        self.assertFalse(_has(res.warnings, "--s2s-type25"))

    def test_the_twoway_note_keeps_its_records(self):
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        note = _CONTACT_SPELLING_NOTES["twoway"]
        for needle in ("NO remedy is", "p.11-8 item 1b", "3036.17",
                       "sphere1", "--no-rigid-secondary-swap"):
            with self.subTest(needle=needle):
                self.assertIn(needle, note)


# ── K-08B ────────────────────────────────────────────────────────────────────

class S2sType25OptIn(unittest.TestCase):
    """K-08B: --s2s-type25 writes an explicit *CONTACT_AUTOMATIC_SURFACE_
    TO_SURFACE as a two-surface /INTER/TYPE25 (SSID /SURF vs the MSID
    /SURF/PART/EXT, Istf 4, Igap 2, Gap_max 0, Inacti 5)."""

    def test_the_flag_writes_a_two_surface_type25(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12)), s2s_type25=True)
        self.assertNotIn("/INTER/TYPE7/12", s)
        rows = _inter_rows(s, "/INTER/TYPE25/12")
        surf1, surf2 = int(rows[0][0]), int(rows[0][1])
        self.assertEqual(rows[0][2:5], ["4", "0", "2"])        # Istf Ithe Igap
        self.assertEqual(rows[1][1:], ["1", "0", "0", "0"])    # Gap_scale, Gap_max
        self.assertEqual(rows[4][2], "5")                      # Inacti
        self.assertEqual(float(rows[3][1]), 0.2)               # Fric
        grshel = _ids_under(s, f"/SURF/GRSHEL/{surf1}")
        self.assertEqual(_ids_under(s, f"/GRSHEL/SHEL/{grshel[0]}"),
                         list(range(101, 109)))
        self.assertEqual(_ids_under(s, f"/SURF/PART/EXT/{surf2}"), [1])
        self.assertTrue(_has(res.warnings, "--s2s-type25",
                             "/INTER/TYPE25/12", "two-surface",
                             "approximation"))

    def test_off_by_default(self):
        _r, s, _e = _convert(_k1a_deck(_k1a_s2s(12)))
        self.assertIn("/INTER/TYPE7/12", s)
        self.assertNotIn("/INTER/TYPE25/", s)

    def test_the_one_way_spelling_is_refused(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, kw="CONTACT_AUTOMATIC_ONE_WAY_SURFACE_TO_SURFACE_ID")),
            s2s_type25=True)
        self.assertIn("/INTER/TYPE7/12", s)
        self.assertTrue(_has(res.warnings, "--s2s-type25", "refused",
                             "ONE_WAY"))

    def test_an_implicit_deck_is_refused(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), implicit=True),
                              s2s_type25=True)
        self.assertIn("/INTER/TYPE7/12", s)
        self.assertTrue(_has(res.warnings, "--s2s-type25", "refused",
                             "implicit"))

    def test_an_inacti_6_request_on_it_is_refused(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12)), s2s_type25=True,
                              inter_inacti={12: 6})
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/12")[4][2], "5")
        self.assertTrue(_has(res.warnings, "--inter-inacti 12=6",
                             "WARNING 1559"))

    def test_birth_death_stfac_and_the_levers_reach_it(self):
        """Card-2 BT / DT -> Tstart / Tstop, SFS -> Stfac (blank = 1.0),
        --soften-stfac named as a TYPE25, --inter-gapmin named by route."""
        deck = _k1a_deck(_k1a_s2s(12, card2=(0.2, 0.2, 0, 0, 0, 0, 1.0e-5,
                                             5.0e-5), card3=(0.5,)))
        _r, s, _e = _convert(deck, s2s_type25=True)
        rows = _inter_rows(s, "/INTER/TYPE25/12")
        self.assertEqual([float(v) for v in rows[3]],
                         [0.5, 0.2, 0.0, 1.0e-5, 5.0e-5])
        _r, s, _e = _convert(_k1a_deck(_k1a_s2s(12)), s2s_type25=True)
        self.assertEqual(float(_inter_rows(s, "/INTER/TYPE25/12")[3][0]), 1.0)
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12)), s2s_type25=True,
                              soften_stfac=0.3, inter_gapmin={12: 0.1})
        self.assertEqual(_stfac_cell(s, "/INTER/TYPE25/12"), 0.3)
        self.assertTrue(_has(res.warnings, "--soften-stfac:",
                             "/INTER/TYPE25 12"))
        self.assertTrue(_has(res.warnings, "--inter-gapmin 12=0.1",
                             "two-surface /INTER/TYPE25 (--s2s-type25)",
                             "override ignored"))

    def test_a_non_automatic_spelling_is_refused_by_name(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, kw="CONTACT_SURFACE_TO_SURFACE_ID")), s2s_type25=True)
        self.assertIn("/INTER/TYPE7/12", s)
        self.assertTrue(_has(res.warnings, "--s2s-type25 refused",
                             "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE only"))

    def test_a_node_set_side_is_refused(self):
        nset = "*SET_NODE_LIST\n" + _row(5) + "\n" + _row(*_CARD_NODES[:8]) + "\n"
        res, s, _e = _convert(_k1a_deck(
            _k1a_s2s(12, ssid=5, sstyp=4), extra=nset), s2s_type25=True)
        self.assertIn("/INTER/TYPE7/12", s)
        self.assertTrue(_has(res.warnings, "--s2s-type25 refused",
                             "*SET_NODE side"))


# ── K-13 ─────────────────────────────────────────────────────────────────────

class Type25SelfGapInputs(unittest.TestCase):
    """K-13: on the SSID = 0 TYPE25 route SST / MST / SFST are not gap
    inputs; the warning names *PART_CONTACT OPTT and Gap_scale. No byte
    moves."""

    def test_a_stated_sst_is_named_with_the_levers(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                 card3=(1.0, 1.0, 0.1))))
        self.assertTrue(_has(
            res.warnings, "/INTER/TYPE25/21", "SST = 0.1",
            "not TYPE25 gap inputs", "min(Gap_scale x t/2, Gap_max)",
            "*PART_CONTACT OPTT", "Gap_scale", "i25sti3.F"))
        _r, s0, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)))
        self.assertEqual(_sha(s), _sha(s0))

    def test_sfst_is_named(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            21, 0, 0, card3=(1.0, 1.0, 0.0, 0.0, 0.5))))
        self.assertTrue(_has(res.warnings, "/INTER/TYPE25/21", "SFST = 0.5",
                             "Gap_scale"))

    def test_without_them_it_is_silent(self):
        for card3 in ((), (1.0, 1.0, 0.0, 0.0, 1.0)):
            with self.subTest(card3=card3):
                res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                          card3=card3)))
                self.assertFalse(_has(res.warnings, "not TYPE25 gap inputs"))

    def test_mst_is_named_and_the_type7_route_is_not_warned(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            21, 0, 0, card3=(1.0, 1.0, 0.0, 0.2))))
        self.assertTrue(_has(res.warnings, "/INTER/TYPE25/21", "MST = 0.2",
                             "not TYPE25 gap inputs"))
        # SSID != 0: the TYPE7 route reads SST as Gapmin, so no K-13 text
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                  card3=(1.0, 1.0, 0.1))))
        self.assertFalse(_has(res.warnings, "not TYPE25 gap inputs"))

    def test_the_sfs_line_names_the_type25(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, card3=(0.15,))))
        self.assertTrue(_has(res.warnings, "CONTACT 21: SFS=0.15",
                             "-> /INTER/TYPE25 Stfac=0.15"))
        self.assertFalse(_has(res.warnings, "CONTACT 21: SFS=0.15",
                              "/INTER/TYPE7"))


# ── the K-0P review follow-ups ───────────────────────────────────────────────

class SoftenStfacEveryNamedRoute(unittest.TestCase):
    """Follow-up 1: --soften-stfac reaches every route its help names, each
    pinned by its Stfac cell (the review's W3 / W4 survivors)."""

    def _cell(self, deck, header, **kw):
        _r, s, _e = _convert(deck, soften_stfac=0.3, **kw)
        return _stfac_cell(s, header)

    def test_the_ssid_type7(self):
        self.assertEqual(
            self._cell(_k1a_deck(_k1a_ass(7, 1, 2)), "/INTER/TYPE7/7"), 0.3)

    def test_the_eroding_and_the_node_to_surface_type25(self):
        for kw, tail in (("CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
                          _row(0, 1, 1) + "\n"),
                         ("CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID", "")):
            with self.subTest(kw=kw):
                self.assertEqual(self._cell(
                    _k1a_deck(_k1a_s2s(41, kw=kw, tail=tail)),
                    "/INTER/TYPE25/41"), 0.3)

    def test_the_soft_routed_general_type7_type11_type19(self):
        for soft, header in ((-7, "/INTER/TYPE7/31"),
                             (-11, "/INTER/TYPE11/31"),
                             (-19, "/INTER/TYPE19/31")):
            with self.subTest(soft=soft):
                deck = _k1a_deck(_k1a_ass(
                    31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                    tail=_row(soft) + "\n"))
                self.assertEqual(self._cell(deck, header), 0.3)


def _soften_warnings(res):
    return [w for w in res.warnings if w.startswith("--soften-stfac:")]


class SoftenStfacWarningFollowsTheRoutes(unittest.TestCase):
    """Follow-up 2: ONE --soften-stfac warning, naming the interfaces the
    flag reached by type - it said 'all /INTER/TYPE7' on a TYPE25 deck and
    nothing on a TYPE25-family deck."""

    def test_a_type25_deck_is_not_called_type7(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)),
                               soften_stfac=0.3)
        ws = _soften_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("Stfac=0.3", ws[0])
        self.assertIn("/INTER/TYPE25 21", ws[0])
        self.assertNotIn("TYPE7", ws[0])

    def test_a_type25_family_deck_gets_its_warning(self):
        for kw, tail in (("CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
                          _row(0, 1, 1) + "\n"),
                         ("CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID", "")):
            with self.subTest(kw=kw):
                res, _s, _e = _convert(
                    _k1a_deck(_k1a_s2s(41, kw=kw, tail=tail)),
                    soften_stfac=0.3)
                ws = _soften_warnings(res)
                self.assertEqual(len(ws), 1, ws)
                self.assertIn("/INTER/TYPE25 41", ws[0])

    def test_a_mixed_deck_names_each_type(self):
        deck = _k1a_deck(_k1a_ass(21, 0, 0) + _k1a_s2s(12))
        res, _s, _e = _convert(deck, soften_stfac=0.3)
        ws = _soften_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("forced on all /INTER/TYPE7 interfaces (12)", ws[0])
        self.assertIn("/INTER/TYPE25 21", ws[0])

    def test_the_tiebreak_companion_is_named_as_not_reached(self):
        import test_tiebreak_rupture as _tb
        tie = ("*KEYWORD\n" + _tb._MESH
               + _tb._auto_tiebreak(6, "50.0", "20.0", "0.005") + _tb._TAIL)
        res, _s, _e = _convert(tie, soften_stfac=0.3)
        ws = _soften_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("reached no interface", ws[0])
        self.assertIn("post-rupture companion /INTER/TYPE25", ws[0])

    def test_the_soft_routed_types_are_named(self):
        for soft, name in ((-11, "/INTER/TYPE11 31"), (-19, "/INTER/TYPE19 31"),
                           (-7, "/INTER/TYPE7 interfaces (31)")):
            with self.subTest(soft=soft):
                deck = _k1a_deck(_k1a_ass(
                    31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                    tail=_row(soft) + "\n"))
                res, _s, _e = _convert(deck, soften_stfac=0.3)
                ws = _soften_warnings(res)
                self.assertEqual(len(ws), 1, ws)
                self.assertIn(name, ws[0])

    def test_without_the_flag_there_is_no_line(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0) + _k1a_s2s(12)))
        self.assertEqual(_soften_warnings(res), [])


class BlastDeckUnmappableUnitsCard(unittest.TestCase):
    """Follow-up 3: on a *LOAD_BLAST_ENHANCED deck an unmappable or empty
    *CONTROL_UNITS card is named, as it is without a blast load."""

    @staticmethod
    def _blast(card: str) -> str:
        import test_converter as _tc
        return _tc.BLAST_K.replace("*CONTROL_TERMINATION",
                                   card + "*CONTROL_TERMINATION", 1)

    def test_an_imperial_card_is_named_beside_the_flag(self):
        for units in (None, ("Mg", "mm", "s")):
            with self.subTest(units=units):
                res, starter, _e = _convert(
                    self._blast(_units_card("in", "sec", "lb")), units=units)
                self.assertEqual(_begin_units(starter)[0], ["kg", "m", "s"])
                self.assertTrue(_has(
                    res.warnings, "*CONTROL_UNITS: ",
                    f"LENGTH 'in' {_NO_LABEL_TEXT}",
                    "the *LOAD_BLAST_ENHANCED UNIT flag sets /BEGIN to "
                    "kg/m/s"))

    def test_an_empty_card_is_named_beside_the_flag(self):
        res, starter, _e = _convert(self._blast("*CONTROL_UNITS\n"))
        self.assertEqual(_begin_units(starter)[0], ["kg", "m", "s"])
        self.assertTrue(_has(
            res.warnings, "*CONTROL_UNITS: states no unit",
            "the *LOAD_BLAST_ENHANCED UNIT flag sets /BEGIN to kg/m/s"))


# ═════════════════════════════════════════════════════════════════════════════
# The K1a review fixes (wave B2): what the adversarial review of the K1a
# contact group found - rules no test pinned (an override reported as ignored
# although its cell was written, the IGNORE 1 / 2 branch of Inacti 6, the
# card-1 flag check on four of the six penalty readers, the Istf 2 lever, the
# routed node-to-surface TYPE7's floor warning), a refusal text naming cases
# the code does not reach (--s2s-type25 on _MPP / _THERMAL), and a Poisson's
# ratio read from the wrong field. Each test below was first run against the
# review's mutation of the rule it pins and seen to fail.
# ═════════════════════════════════════════════════════════════════════════════

def _ignored(res, flag: str, iid: int):
    """The end-of-deck 'override ignored' lines of *flag* for id *iid*."""
    return [w for w in res.warnings
            if w.startswith(f"{flag} {iid}=") and "override ignored" in w]


def _card_nset(sid: int = 5) -> str:
    """*SET_NODE_LIST *sid* = 16 of the card nodes (the routed
    node-to-surface decks of K-06)."""
    return ("*SET_NODE_LIST\n" + _row(sid) + "\n" + "".join(
        _row(*_CARD_NODES[k:k + 8]) + "\n" for k in range(0, 9, 8)))


def _routed_n2s_deck(**kw) -> str:
    """The implicit *CONTACT_NODES_TO_SURFACE 16 (node set 5 against the
    block, part 1) that k2rad writes as the one-way /INTER/TYPE7/16."""
    return _k1a_deck(_k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3,
                              kw="CONTACT_NODES_TO_SURFACE_ID"),
                     implicit=True, extra=_card_nset(), **kw)


#: the block's *MAT_ELASTIC card in _k1a_deck(..., block_e=10.0)
_SOFT_BLOCK_MAT = "*MAT_ELASTIC\n" + _row(1, 1.25e-9, 10.0, 0.38) + "\n"


class LeverReachNamesOnlyWhatNothingTook(unittest.TestCase):
    """K-02 / K-06 (review): the end-of-deck report calls an --inter-stmin /
    --inter-inacti id 'override ignored' only when no interface took it. An
    id whose cell was written, that was refused by name, or that was not
    applied on purpose is never reported as ignored (the review's M07 / M28
    / M29 deleted the three .add() calls and no test noticed)."""

    def test_a_written_stmin_is_not_called_ignored(self):
        cases = (
            ("ASS SSID != 0 + S2S",
             _k1a_deck(_k1a_ass(7, 1, 2) + _k1a_s2s(12)), {7: 0.0, 12: 250.0}),
            ("SOFT -7 GENERAL",
             _k1a_deck(_k1a_ass(31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                                tail=_row(-7) + "\n")), {31: 0.0}),
            ("routed implicit N2S", _routed_n2s_deck(), {16: 0.0}),
        )
        for name, deck, stmin in cases:
            with self.subTest(name):
                res, s, _e = _convert(deck, inter_stmin=stmin)
                for iid, val in stmin.items():
                    self.assertEqual(_type7(s, iid)["stmin"], f"{val:g}")
                    self.assertEqual(_ignored(res, "--inter-stmin", iid), [])

    def test_a_taken_inacti_request_is_not_called_ignored(self):
        """Applied (the TYPE7 12), refused by name (the TYPE25 21), not
        applied on purpose (the *_INTERFERENCE 0, the implicit bootstrap 0,
        the --deformable-contact-recipe 5)."""
        cases = (
            ("applied", _k1a_deck(_k1a_s2s(12)), 12, {},
             "/INTER/TYPE7/12 Inacti 6"),
            ("refused", _k1a_deck(_k1a_ass(21, 0, 0)), 21, {}, "refused"),
            ("interference", _k1a_deck(_k1a_s2s(
                13, kw="CONTACT_SURFACE_TO_SURFACE_INTERFERENCE_ID",
                tail=_row(0, 0) + "\n")), 13, {}, "not applied"),
            ("bootstrap", _k1a_deck(_k1a_s2s(12, card3=(1.0, 1.0, 0.2, 0.2)),
                                    implicit=True), 12, {}, "not applied"),
            ("recipe", _k1a_deck(_k1a_s2s(14, ssid=101, msid=102, sstyp=3,
                                          mstyp=3), implicit=True), 14,
             {"deformable_contact_recipe": True}, "not applied"),
        )
        for name, deck, iid, kw, said in cases:
            with self.subTest(name):
                res, _s, _e = _convert(deck, inter_inacti={iid: 6}, **kw)
                self.assertTrue(_has(res.warnings, f"--inter-inacti {iid}=6",
                                     said))
                self.assertEqual(_ignored(res, "--inter-inacti", iid), [])

    def test_a_soft_routed_id_is_named_with_its_written_type(self):
        """The review's M40: the report names the type a SOFT-routed general
        contact was written as."""
        for soft, kind in ((-11, "/INTER/TYPE11"), (-19, "/INTER/TYPE19")):
            with self.subTest(soft=soft):
                deck = _k1a_deck(_k1a_ass(
                    31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                    tail=_row(soft) + "\n"))
                res, _s, _e = _convert(deck, inter_stmin={31: 0.0})
                self.assertTrue(_has(_ignored(res, "--inter-stmin", 31),
                                     f"was emitted as {kind}, not as an "
                                     "/INTER/TYPE7"))


class StminFloorReviewFixes(unittest.TestCase):
    """K-02 (review): the Istf 2 lever number, the routed node-to-surface
    TYPE7's floor warning, a Poisson's ratio stored as 'pr', an elastic
    fluid's bulk modulus, a rigid part in the SSID set, and the four Istf
    combinations."""

    def test_the_istf_2_lever_is_the_average_threshold(self):
        """Istf 2: K = (Stfac x Km1 + Ks) / 2 reaches the floor at Stfac =
        (2 Stmin - Ks) / Km1 = (2000 - 1120) / 1120 = 0.786 (the review's
        M08 wrote -0.107)."""
        deck = _k1a_deck(_k1a_ass(
            31, 1, 2, card3=(0.15,), kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_row(-7) + "\n"))
        res, _s, _e = _convert(deck)
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("below Stfac 0.786 the floor sets K", ws[0])

    def test_the_routed_implicit_node_to_surface_type7_gets_its_warning(self):
        """The routed implicit *CONTACT_NODES_TO_SURFACE is an /INTER/TYPE7
        (round 9, A2): the card nodes on the foam-soft block, Km = 1 x 13.89
        x 18.5 = 256.9 under Ks = 3200 x 0.35 = 1120 (the review's M11)."""
        res, s, _e = _convert(_routed_n2s_deck(block_e=10.0))
        self.assertEqual(_type7(s, 16)["stmin"], "1000")
        ws = [w for w in _stmin_warnings(res)
              if w.startswith("/INTER/TYPE7 16:")]
        self.assertEqual(len(ws), 1, _stmin_warnings(res))
        for needle in ("Km = Stfac x B x A^2/V = 1 x 13.89 x 18.5 = 256.9",
                       "Ks = E x t = 3200 x 0.35 = 1120",
                       "K = min(Km, Ks) = 256.9"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])
        res, _s, _e = _convert(_routed_n2s_deck())          # E 2400: silent
        self.assertEqual([w for w in _stmin_warnings(res)
                          if w.startswith("/INTER/TYPE7 16:")], [])

    def test_a_poisson_ratio_stored_as_pr_is_read(self):
        """*MAT_TOUGHENED_ADHESIVE_POLYMER keeps Poisson's ratio as 'pr': the
        E 10, 0.38 block gives B = 10 / (3 (1 - 0.76)) = 13.89 as the
        *MAT_ELASTIC one does, not E / 3 = 3.333 (the review's nu_probe) -
        the bulk modulus /MAT/LAW120 stores (hm_read_mat120.F:146/238).
        Re-pinned in wave C: the K1a fix pinned this on *MAT_ARUP_ADHESIVE,
        whose /MAT/LAW169 the starter gives no bulk modulus at all
        (StminFloorNoStiffnessLaw)."""
        base = _k1a_deck(_k1a_s2s(12), block_e=10.0)
        self.assertEqual(base.count(_SOFT_BLOCK_MAT), 1)
        res, s, _e = _convert(base.replace(_SOFT_BLOCK_MAT, _TAPO_BLOCK_MAT))
        self.assertIn("/MAT/LAW120/1", s)
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("Km = Stfac x B x A^2/V = 1 x 13.89 x 18.5 = 256.9",
                      ws[0])

    def test_every_registered_pr_record_gives_its_poisson_ratio(self):
        """_part_e_nu on each registered record type that names the ratio
        'pr' and whose law stores a bulk modulus (MAT_224 -> LAW109,
        hm_read_mat109.F:113/163; MAT_252 -> LAW120): (E, pr), not (E, 0).
        MAT_169 -> LAW169 gives None (wave C re-pin): the starter stores no
        bulk modulus for that law, so there is no (E, nu) to estimate a
        contact stiffness from."""
        from k2rad.state import (ConversionState, MatArupAdhesive,
                                 MatTabulatedJC, MatToughenedAdhesive,
                                 PartData)
        from k2rad.writer import contacts
        for cls, reg, want in (
                (MatArupAdhesive, "mat_arup_adhesive", None),
                (MatTabulatedJC, "mat_tabulated_jc", (10.0, 0.38)),
                (MatToughenedAdhesive, "mat_toughened_adhesive",
                 (10.0, 0.38))):
            with self.subTest(cls=cls.__name__):
                st = ConversionState()
                st.parts[1] = PartData(1, "p", 1, 7)
                getattr(st, reg)[7] = cls(mid=7, title="", rho=1.0e-9,
                                          e=10.0, pr=0.38)
                self.assertEqual(contacts._part_e_nu(st, 1), want)

    def test_an_elastic_fluid_takes_its_bulk_modulus(self):
        """*MAT_ELASTIC_FLUID: LS-DYNA ignores E and PR under FLUID (Remark
        5) and k2rad writes K as the /EOS/POLYNOMIAL C1 the starter takes as
        the bulk modulus (PM(32) = C1 + C4 E0, hm_read_eos_polynomial.F:110):
        B = K = 50, Km = 1 x 50 x 18.5 = 925. A blank K falls back to E / (3
        (1 - 2 PR)) = 13.89, the record's own rule."""
        base = _k1a_deck(_k1a_s2s(12), block_e=10.0)
        for k_cell, km in ((50.0, "1 x 50 x 18.5 = 925"),
                           (0.0, "1 x 13.89 x 18.5 = 256.9")):
            with self.subTest(k=k_cell):
                fluid = ("*MAT_ELASTIC_FLUID\n"
                         + _row(1, 1.25e-9, 10.0, 0.38, 0.0, 0.0, k_cell)
                         + "\n" + _row(0.0, 0.0) + "\n")
                res, s, _e = _convert(base.replace(_SOFT_BLOCK_MAT, fluid))
                self.assertIn("/EOS/POLYNOMIAL/1", s)
                ws = _stmin_warnings(res)
                self.assertEqual(len(ws), 1, ws)
                self.assertIn(f"Km = Stfac x B x A^2/V = {km}", ws[0])

    def test_a_rigid_part_of_the_set_is_main_side_only(self):
        """A part-set SSID holding the cards and a RIGID block (E 10): the
        secondary side is the set's non-rigid nodes - the 18 card nodes, Ks
        = 1120 from the cards alone (the review's M18, M03) - and the main
        side is the whole set, a count-weighted median over its 24 segments
        (16 block faces at 256.9, 8 card shells at 1120: 256.9, the review's
        M15)."""
        deck = _k1a_deck(_k1a_ass(7, 1, 2))
        old_set = "*SET_PART_LIST\n" + _row(1) + "\n" + _row(101, 102) + "\n"
        old_mat = "*MAT_ELASTIC\n" + _row(1, 1.25e-9, 2400.0, 0.38) + "\n"
        self.assertEqual(deck.count(old_set), 1)
        self.assertEqual(deck.count(old_mat), 1)
        deck = deck.replace(old_set, "*SET_PART_LIST\n" + _row(1) + "\n"
                            + _row(101, 102, 1) + "\n")
        deck = deck.replace(old_mat, "*MAT_RIGID\n"
                            + _row(1, 1.25e-9, 10.0, 0.38) + "\n"
                            + _row(0, 0, 0) + "\n" + _row() + "\n")
        res, s, _e = _convert(deck)
        self.assertIn("/INTER/TYPE7/7", s)
        self.assertTrue(_has(res.warnings, "SSID = 1 (a part set",
                             "(the 18 non-rigid nodes of the set)"))
        ws = _stmin_warnings(res)
        self.assertEqual(len(ws), 1, ws)
        for needle in ("Km = Stfac x the median main segments stiffness = "
                       "256.9 (over 24 main segments of 3 parts)",
                       "Ks = E x t = 3200 x 0.35 = 1120",
                       "K = min(Km, Ks) = 256.9"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])

    def test_the_four_istf_combinations(self):
        """i7cor3.F:251-301 on Km 100, Ks 300: Istf 2 the average, 3 the
        maximum, 4 the minimum, 5 the series stiffness (no route writes Istf 3
        or 5 today; pinned so the warning stays right when one does - the
        review's M09 / M10)."""
        from k2rad.writer.contacts import _combine_istf
        for istf, want in ((2, 200.0), (3, 300.0), (4, 100.0), (5, 75.0)):
            with self.subTest(istf=istf):
                self.assertAlmostEqual(_combine_istf(100.0, 300.0, istf), want)


class InterInactiSixIgnoreBranch(unittest.TestCase):
    """K-06 (review): the IGNORE 1 / 2 branch of _ignore_to_inacti - the
    first of the two 'return 5' branches --inter-inacti 6 replaces - takes 6
    as the IGNORE 0 one does (the review's M27)."""

    def test_the_ignore_1_and_2_branch_takes_6_too(self):
        for ign in (1, 2):
            with self.subTest(ignore=ign):
                # optional Cards A and B blank, Card C: IGAP 0, IGNORE ign
                tail = _row() + "\n" + _row() + "\n" + _row(0, ign) + "\n"
                deck = _k1a_deck(_k1a_s2s(12, tail=tail))
                res, s, _e = _convert(deck, inter_inacti={12: 6})
                self.assertEqual(_type7(s, 12)["inacti"], "6")
                self.assertEqual(_type7(s, 12)["fpenmax"], "0.999999")
                self.assertTrue(_has(res.warnings, f"CONTACT 12: ignore={ign} "
                                     "mapped to Inacti=5"))
                self.assertTrue(_has(res.warnings, "--inter-inacti 12=6",
                                     "/INTER/TYPE7/12 Inacti 6"))
                _r, s, _e = _convert(deck)
                self.assertEqual(_type7(s, 12)["inacti"], "5")


#: the penalty *CONTACT readers that run the K-07 card-1 check, with a card
#: 1 head (SURFA SURFB SURFATYP SURFBTYP) each accepts on _k1a_deck
_K07_READERS = (
    ("CONTACT_AUTOMATIC_SINGLE_SURFACE", (1, 0, 2, 0)),
    ("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", (1, 2, 2, 2)),
    ("CONTACT_AUTOMATIC_GENERAL", (1, 0, 2, 0)),
    ("CONTACT_SINGLE_EDGE", (1, 0, 2, 0)),
    ("CONTACT_AIRBAG_SINGLE_SURFACE", (1, 0, 2, 0)),
    ("CONTACT_ERODING_SURFACE_TO_SURFACE", (1, 2, 2, 2)),
)


class CardOneFlagsEveryPenaltyReader(unittest.TestCase):
    """K-07 (review): every penalty reader that passes card2_present - the
    single-surface, surface-to-surface, general, single-edge, airbag and
    TYPE25-family ones - names friction typed into SAPR (the review's M30 /
    M31 dropped it on two of them unnoticed), and card 2 counts as present
    without a card 3 (M32). A *CONTACT_AUTOMATIC_GENERAL or
    *CONTACT_AIRBAG_SINGLE_SURFACE without a SOFT sentinel is read by the
    single-surface reader it delegates to; their own readers run on the SOFT
    = -7 / -11 / -19 (GENERAL) and SOFT = -19 (AIRBAG) routes only."""

    def test_the_soft_routed_readers_name_it_too(self):
        for kw, soft in (("CONTACT_AUTOMATIC_GENERAL", -7),
                         ("CONTACT_AUTOMATIC_GENERAL", -11),
                         ("CONTACT_AUTOMATIC_GENERAL", -19),
                         ("CONTACT_AIRBAG_SINGLE_SURFACE", -19)):
            with self.subTest(kw=kw, soft=soft):
                card = _k1a_ass(31, 1, 2, card2=(0.3, 0.3), kw=kw + "_ID",
                                tail=_row(soft) + "\n")
                self.assertEqual(card.count(_row(1, 0, 2, 0) + "\n"), 1)
                card = card.replace(_row(1, 0, 2, 0) + "\n",
                                    _row(1, 0, 2, 0, 0, 0, 0.22, 0) + "\n")
                res, _s, _e = _convert(_k1a_deck(card))
                self.assertTrue(_has(res.warnings, f"*{kw} 31: card 1",
                                     "SAPR = 0.22", _K07,
                                     "The friction written is Card 2's"))

    def test_without_a_card_two_each_reader_says_frictionless(self):
        for kw, head in _K07_READERS:
            with self.subTest(kw=kw):
                deck = _k1a_deck(f"*{kw}\n" + _row(*head, 0, 0, 0.22, 0)
                                 + "\n")
                res, _s, _e = _convert(deck)
                self.assertTrue(_has(res.warnings, f"*{kw} ", "SAPR = 0.22",
                                     _K07, "Fric = 0 (frictionless)",
                                     "Card 2 FS -> Fric"))

    def test_a_card_two_without_a_card_three_is_a_card_two(self):
        for kw, head in _K07_READERS:
            with self.subTest(kw=kw):
                deck = _k1a_deck(f"*{kw}\n" + _row(*head, 0, 0, 0.22, 0)
                                 + "\n" + _row(0.3, 0.3) + "\n")
                res, _s, _e = _convert(deck)
                self.assertTrue(_has(res.warnings, f"*{kw} ", "SAPR = 0.22",
                                     _K07, "The friction written is Card 2's"))
                self.assertFalse(_has(res.warnings, f"*{kw} ",
                                      "Fric = 0 (frictionless)"))
        res, s, _e = _convert(_k1a_deck(
            "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
            + _row(1, 0, 2, 0, 0, 0, 0.22, 0) + "\n" + _row(0.3, 0.3) + "\n"))
        iid = int(re.search(r"/INTER/TYPE7/(\d+)", s).group(1))
        self.assertEqual(_type7(s, iid)["fric"], 0.3)


class S2sType25RefusalsAsBuilt(unittest.TestCase):
    """K-08B (review): the --s2s-type25 refusals name only the cases the
    code reaches. No handler takes *CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_MPP
    or _THERMAL (both skipped, as at master), the _THERMAL spellings the
    surface-to-surface handler does read are refused by their spelling, an
    --inter-inacti 6 request on the TYPE25 is refused on its own (Inacti 5
    kept), and a *SET_NODE MAIN side is dropped by the TYPE7 route."""

    def test_a_thermal_spelling_is_refused_by_its_spelling(self):
        for kw in ("CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_MORTAR_THERMAL_ID",
                   "CONTACT_SURFACE_TO_SURFACE_THERMAL_ID"):
            with self.subTest(kw=kw):
                res, s, _e = _convert(_k1a_deck(_k1a_s2s(
                    12, kw=kw, tail=_row(1.0) + "\n")), s2s_type25=True)
                self.assertIn("/INTER/TYPE7/12", s)
                self.assertNotIn("/INTER/TYPE25/", s)
                self.assertTrue(_has(
                    res.warnings, "--s2s-type25 refused",
                    "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE only"))

    def test_the_refusal_texts_name_no_mpp_and_no_thermal_card_rule(self):
        """The spelling refusal and the two docstrings no longer say the flag
        takes an _MPP spelling, the help no longer names a _THERMAL rule of
        its own, and the refusal's docstring says why there is none."""
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, kw="CONTACT_SURFACE_TO_SURFACE_ID")), s2s_type25=True)
        w = [x for x in res.warnings if x.startswith("--s2s-type25 refused")]
        self.assertEqual(len(w), 1, w)
        self.assertNotIn("_MPP", w[0])
        from k2rad.writer import contacts
        for fn in (contacts._s2s_type25_route, contacts._s2s_type25_refusal):
            with self.subTest(fn=fn.__name__):
                doc = _collapse(fn.__doc__).replace("``", "")
                self.assertNotIn("_TITLE / _MPP", doc)
        doc = _collapse(contacts._s2s_type25_refusal.__doc__).replace("``", "")
        for needle in ("no handler takes", "_THERMAL or ..._MPP",
                       "refused as such"):
            with self.subTest(needle=needle):
                self.assertIn(needle, doc)
        h = _collapse(_action_help("--s2s-type25"))
        self.assertNotIn("a _THERMAL card", h)
        self.assertIn("the _THERMAL ones among them", h)

    def test_a_node_set_main_side_is_refused_and_not_said_to_stay(self):
        """MSID a *SET_NODE (the review's M35): refused like an SSID one,
        and the text does not say the /INTER/TYPE7 stays - that route drops
        a node-set MAIN side by name."""
        nset = ("*SET_NODE_LIST\n" + _row(5) + "\n"
                + _row(*_CARD_NODES[:8]) + "\n")
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12, msid=5, mstyp=4),
                                        extra=nset), s2s_type25=True)
        self.assertNotIn("/INTER/TYPE25/", s)
        w = [x for x in res.warnings if x.startswith("--s2s-type25 refused")]
        self.assertEqual(len(w), 1, w)
        self.assertIn("*SET_NODE side", w[0])
        self.assertNotIn("the /INTER/TYPE7 stays", w[0])
        self.assertTrue(_has(res.warnings, "MAIN (MSID) side msid=5 mstyp=4",
                             "resolved to no contact surface"))

    def test_card_2_vdc_sets_viss(self):
        """VDC 20 (% of critical) -> VISs 0.2; blank -> the Radioss 0.05
        (the review's M36)."""
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, card2=(0.2, 0.2, 0, 0, 20))), s2s_type25=True)
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/12")[4][3], "0.2")
        _r, s, _e = _convert(_k1a_deck(_k1a_s2s(12)), s2s_type25=True)
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/12")[4][3], "0.05")

    def test_the_twobar_record_is_the_flags_own(self):
        """The no-load caveat now cites the flag's own TYPE25 on twobar
        respelled AUTOMATIC (fix round: peak IE 0.78, the TYPE7 4.46e4), not
        only the hand-built one."""
        h = _collapse(_action_help("--s2s-type25"))
        self.assertIn("the flag's own TYPE25 carries no load", h)
        self.assertIn("0.78", h)
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(12)), s2s_type25=True)
        self.assertTrue(_has(res.warnings, "--s2s-type25 -> two-surface",
                             "this route's own TYPE25 carries no load",
                             "peak IE 0.78", "4.46e4"))


class ReviewTextFixes(unittest.TestCase):
    """The review's text minors: the shell-offset clamp line states each
    fact once (K-03 had repeated the WARNING 94 clause and the 0.1 x side
    value), and the K-08 note is true under --s2s-type25 and does not call
    the eroding TYPE25 the same as the flag's."""

    def test_the_clamp_warning_states_each_fact_once(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_dz=0.3))
        w = [x for x in res.warnings if "/INTER/TYPE7 12: LS-DYNA offsets" in x]
        self.assertEqual(len(w), 1, w)
        for needle in (":1075-1083", "0.1 x 0.3 = 0.03", "WARNING 94 without "
                       "clamping", "smaller still than the cap"):
            with self.subTest(needle=needle):
                self.assertEqual(w[0].count(needle), 1, w[0])

    def test_the_one_way_note_holds_under_the_flag(self):
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        note = _CONTACT_SPELLING_NOTES["twoway_auto"]
        self.assertIn("the /INTER/TYPE7 k2rad writes for it by default is "
                      "one-way", note)
        self.assertNotIn("the same two-surface /INTER/TYPE25", note)
        self.assertIn("a two-surface /INTER/TYPE25 too, with Istf 2", note)


@unittest.skipUnless(_k1a_has_fast_proximity(),
                     "--auto-gapmin needs numpy + scipy")
class AutoGapminReviewFixes(unittest.TestCase):
    """K-04 (review): a cap below T is named (the written gap lies inside
    LS-DYNA's offset contact surfaces); the offset predicates of
    _offset_term - the thinnest shell of the side, no main offset on a mixed
    shell / solid main - and the tie / implicit-stub skip texts are pinned
    (the review's M21-M25 survivors, M21 excepted)."""

    def test_a_cap_below_t_is_named(self):
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_dz=0.3),
                              auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.15)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 12",
                             "0.15 is below T = 0.175",
                             "--inter-gapmin 12=0.175"))
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12), block_dz=0.4,
                                        z1=_Z_TOP + 0.275), auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.2)    # capped, above T
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 12", "CAPPED"))
        self.assertFalse(_has(res.warnings, "--auto-gapmin INTER 12",
                              "is below T"))

    def test_the_thinnest_secondary_shell_sets_t(self):
        """Card 2 at t 0.5 beside card 1 at 0.35: T = 0.35 / 2, so 0.1794;
        the thickest would give T 0.25 > d and the overlap value 0.1444."""
        deck = _k1a_deck(_k1a_s2s(12))
        old = "*PART\ncard_2\n" + _row(102, 2, 2) + "\n"
        self.assertEqual(deck.count(old), 1)
        deck = deck.replace(old, "*PART\ncard_2\n" + _row(102, 3, 2) + "\n"
                            + "*SECTION_SHELL\n" + _row(3, 2, 0.8333, 2) + "\n"
                            + _row(0.5, 0.5, 0.5, 0.5) + "\n")
        _r, s, _e = _convert(deck, auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.1794)

    def test_a_mixed_shell_and_solid_main_adds_no_main_offset(self):
        """MSID = {block, card 2}: the main side mixes shells and solids, so
        only card 1's t/2 counts (0.1794); a main offset would make T 0.35 >
        d and the overlap value 0.1444."""
        extra = "*SET_PART_LIST\n" + _row(3) + "\n" + _row(1, 102) + "\n"
        deck = _k1a_deck(_k1a_s2s(12, ssid=101, msid=3, sstyp=3, mstyp=2),
                         extra=extra)
        _r, s, _e = _convert(deck, auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.1794)

    def test_a_shell_skin_on_solid_nodes_gets_no_secondary_offset(self):
        """SSID = four shells glued on the block's top face (part 103, on the
        block's own nodes, so every secondary node is a solid node) against
        card 1: no secondary t/2, only card 1's main one - T = 0.175, so
        0.1794; a secondary offset as well would give T 0.35 > d and the
        overlap value 0.1444 (the review's M21)."""
        def top(i, j):
            return 10 + i + 3 * j       # _k1a_deck's block node at (i, j, 1)
        skin = "*ELEMENT_SHELL\n" + "".join(
            "".join(f"{v:>8}" for v in [201 + k, 103, top(i, j),
                                        top(i + 1, j), top(i + 1, j + 1),
                                        top(i, j + 1)]) + "\n"
            for k, (i, j) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))))
        skin += "*PART\nskin\n" + _row(103, 2, 2) + "\n"
        deck = _k1a_deck(_k1a_s2s(12, ssid=103, msid=101, sstyp=3, mstyp=3),
                         extra=skin)
        res, s, _e = _convert(deck, auto_gapmin=True)
        self.assertEqual(_type7(s, 12)["gapmin"], 0.1794)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 12",
                             "T = 0.175", "main t/2 = 0.175"))
        self.assertFalse(_has(res.warnings, "--auto-gapmin INTER 12",
                              "secondary t/2"))

    def test_a_tie_and_the_implicit_stub_are_named(self):
        tie = ("*CONTACT_TIED_SURFACE_TO_SURFACE_ID\n" + f"{17:>10}tie_it\n"
               + _row(101, 1, 3, 3) + "\n" + _row() + "\n" + _row() + "\n")
        res, _s, _e = _convert(_k1a_deck(tie), auto_gapmin=True)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 17: no "
                             "clearance suggestion",
                             "*CONTACT_TIED_SURFACE_TO_SURFACE -> a tie"))
        res, _s, _e = _convert(_k1a_deck("", implicit=True), auto_gapmin=True)
        self.assertTrue(_has(res.warnings, "no clearance suggestion",
                             "the all-parts implicit stub k2rad injects"))


# ═════════════════════════════════════════════════════════════════════════════
# Wave C, group K1b-contacts-p2: the K1a residual of wave B2 (a law the
# starter gives no contact stiffness), the three hand-overs (MAXINT, the
# --stop-added-mass / --print-every help texts, the *DAMPING_GLOBAL LCID
# sentence), then K-05 K-09 K-10 K-11 K-12 K-14 K-16. Same probe deck
# (_k1a_deck); each test was run red before its code.
# ═════════════════════════════════════════════════════════════════════════════

#: the K1a review's *MAT_ARUP_ADHESIVE block (E 10, PR 0.38) -> /MAT/LAW169
_ADHESIVE_BLOCK_MAT = ("*MAT_ARUP_ADHESIVE\n"
                       + _row(1, 1.25e-9, 10.0, 0.38, 1.0, 1.0, 1.0, 1.0)
                       + "\n" + _row(1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                       + "\n")
#: the same block as *MAT_TOUGHENED_ADHESIVE_POLYMER -> /MAT/LAW120, a law
#: that stores PARMAT(1) = E / (3 (1 - 2 nu)) (hm_read_mat120.F:146/238)
_TAPO_BLOCK_MAT = ("*MAT_TOUGHENED_ADHESIVE_POLYMER\n"
                   + _row(1, 1.25e-9, 10.0, 0.38, 0, 0, 0) + "\n"
                   + _row(0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                   + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                   + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")


def _inert_warnings(res, iid: int = 12):
    return [w for w in res.warnings
            if w.startswith(f"/INTER/TYPE7 {iid}:")
            and "gives the starter no contact stiffness" in w]


class StminFloorNoStiffnessLaw(unittest.TestCase):
    """K-02 residual (the K1a second review's major): the starter gives
    /MAT/LAW169 no bulk modulus - hm_read_mat169.F90:202 leaves PARMAT(1)
    unset, so PM(32) = 0 (hm_read_mat.F90:1451/1464/1546) - so a LAW169
    part's main segments get STF = 0 (i7sti3.F:442-444) and its nodes
    STFNS = 0 (sbulk3.F, asstifi.F:50, i7stslav.F:58), and the engine search
    skips both (i7trivox.F:221/342). The estimate names the law instead of
    a number; on a side that also holds other parts it estimates those.
    MEASURED (wave C, run_or.ps1 -Both on the K1a probe, the 18 card nodes
    thrown at the block at 1000 mm/s for 1e-3 s): a LAW169 main side -
    POSSIBLE IMPACT NUMBER 0, the cards' KE 0.04725 unchanged (0.00 %);
    *MAT_ELASTIC E 10 control 48 and an 85.76 % drop. A LAW169 secondary
    side: KE unchanged (0.00 %, IE 0), control 91.60 %."""

    def _deck(self, contact, mat=_ADHESIVE_BLOCK_MAT):
        base = _k1a_deck(contact, block_e=10.0)
        self.assertEqual(base.count(_SOFT_BLOCK_MAT), 1)
        return base.replace(_SOFT_BLOCK_MAT, mat)

    def test_a_law169_main_side_gets_the_law_not_a_number(self):
        for stmin in ({}, {12: 0.0}):
            with self.subTest(inter_stmin=stmin):
                res, s, _e = _convert(self._deck(_k1a_s2s(12)),
                                      inter_stmin=stmin)
                self.assertIn("/MAT/LAW169/1", s)
                self.assertEqual(_stmin_warnings(res), [])
                ws = _inert_warnings(res)
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in ("the main side's part 1", "/MAT/LAW169",
                               "*MAT_ARUP_ADHESIVE", "hm_read_mat169.F90:202",
                               "PM(32) = 0", "i7sti3.F:442-444",
                               "i7trivox.F:221/342", "whatever the Stmin or "
                               "Stfac", "POSSIBLE IMPACT NUMBER 0"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
                for absent in ("13.89", "256.9", "below Stfac",
                               "MAX(Stmin, K)", "secondary side's part",
                               "the other parts of a side"):
                    with self.subTest(absent=absent):
                        self.assertNotIn(absent, ws[0])

    def test_a_law169_secondary_side_is_named_too(self):
        res, _s, _e = _convert(self._deck(_k1a_s2s(12, ssid=2, msid=1)))
        self.assertEqual(_stmin_warnings(res), [])
        ws = _inert_warnings(res)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("the secondary side's part 1", ws[0])
        self.assertIn("asstifi.F:50", ws[0])
        self.assertNotIn("main side's part", ws[0])
        # the whole secondary side is inert: no 'other parts' are estimated
        self.assertNotIn("the other parts of a side", ws[0])

    def test_the_rest_of_a_mixed_side_is_still_estimated(self):
        """SSID = {cards, LAW169 block}: the set's TYPE7 self-contact keeps
        the cards' estimate (Km = Ks = 1120 > 1000, no floor line) and names
        part 1 on both sides; with soft cards (E 1000) the floor line is
        computed over the cards alone (350 each side)."""
        deck = self._deck(_k1a_ass(7, 1, 2))
        old_set = "*SET_PART_LIST\n" + _row(1) + "\n" + _row(101, 102) + "\n"
        self.assertEqual(deck.count(old_set), 1)
        deck = deck.replace(old_set, "*SET_PART_LIST\n" + _row(1) + "\n"
                            + _row(101, 102, 1) + "\n")
        res, s, _e = _convert(deck)
        self.assertIn("/INTER/TYPE7/7", s)
        self.assertEqual(_stmin_warnings(res), [])
        ws = _inert_warnings(res, 7)
        self.assertEqual(len(ws), 1, res.warnings)
        for needle in ("the main side's part 1", "the secondary side's part 1",
                       "the other parts of a side"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])
        old_card = "*MAT_ELASTIC\n" + _row(2, 1.35e-9, 3200.0, 0.35) + "\n"
        self.assertEqual(deck.count(old_card), 1)
        res, _s, _e = _convert(deck.replace(
            old_card, "*MAT_ELASTIC\n" + _row(2, 1.35e-9, 1000.0, 0.35)
            + "\n"))
        fl = [w for w in _stmin_warnings(res) if w.startswith("/INTER/TYPE7 7:")]
        self.assertEqual(len(fl), 1, res.warnings)
        self.assertIn("Km = Stfac x E x t = 1 x 1000 x 0.35 = 350", fl[0])
        self.assertIn("Ks = E x t = 1000 x 0.35 = 350", fl[0])
        self.assertNotIn("13.89", fl[0])
        self.assertEqual(len(_inert_warnings(res, 7)), 1)

    def test_no_estimate_and_the_label_for_a_law169_part(self):
        """On the dispatched probe (elements present, so an estimate CAN be
        made): the LAW169 block gets none, the LAW120 one gets B 13.89."""
        from k2rad.writer import contacts
        st = _dispatch(self._deck(_k1a_s2s(12)))
        self.assertIsNone(contacts._part_e_nu(st, 1))
        self.assertEqual(contacts._part_stiffness(st, [1]), {1: None})
        self.assertEqual(contacts._part_stiffness_quick(st, [1]), {1: None})
        lab = contacts._part_no_contact_stiffness(st, 1)
        self.assertIsNotNone(lab)
        self.assertIn("/MAT/LAW169", str(lab))
        self.assertIsNone(contacts._part_no_contact_stiffness(st, 101))
        st = _dispatch(self._deck(_k1a_s2s(12), _TAPO_BLOCK_MAT))
        self.assertIsNone(contacts._part_no_contact_stiffness(st, 1))
        est = contacts._part_stiffness(st, [1])[1]
        self.assertIsNotNone(est)
        self.assertAlmostEqual(est.b, 10.0 / (3.0 * (1.0 - 0.76)))


# ── the hand-overs: MAXINT, two help texts, the *DAMPING_GLOBAL sentence ─────

class DbExtentBinaryMaxint(unittest.TestCase):
    """The K4-engine hand-over: K-42's writer rule 'MAXINT > 3 ->
    /ANIM/SHELL/TENS/STRESS/ALL' could not fire from a .k deck, because
    handle_database_extent_binary read card 1 fields 4-8 and not field 3,
    MAXINT (Vol I R17 p.16-67: NEIPH NEIPS MAXINT STRFLG SIGFLG EPSFLG
    RLTFLG ENGFLG; MAXINT 'def = 3')."""

    _ALL = "/ANIM/SHELL/TENS/STRESS/ALL"

    @staticmethod
    def _ext(*cells) -> str:
        return "*DATABASE_EXTENT_BINARY\n" + _row(*cells) + "\n"

    def test_the_handler_reads_field_3(self):
        for cell, want in ((5, 5), ("", 3), (3, 3), (-3, -3), (8, 8)):
            with self.subTest(maxint=cell):
                st = _dispatch(_deck(extra=self._ext(0, 0, cell)))
                self.assertEqual(st.db_extent_binary.maxint, want)
        st = _dispatch(_deck(extra=self._ext(0, 0, 5, 1, 0, 0, 0, 0)))
        ext = st.db_extent_binary
        self.assertEqual((ext.maxint, ext.strflg, ext.sigflg, ext.epsflg,
                          ext.rltflg, ext.engflg), (5, 1, 0, 0, 0, 0))

    def test_maxint_5_writes_stress_all_end_to_end(self):
        _r, _s, eng = _convert(_deck(extra=self._ext(0, 0, 5)))
        lines = eng.splitlines()
        self.assertIn(self._ALL, lines)
        self.assertEqual(lines.index(self._ALL),
                         lines.index("/ANIM/SHELL/TENS/STRESS/LOWER") + 1)

    def test_maxint_blank_3_or_below_writes_no_stress_all(self):
        # -5 asks LS-DYNA for |MAXINT| = 5 points with no averaging (p.16-67)
        # but K-42's rule reads MAXINT > 3 only: what is pinned here is that
        # rule as it stands, and the handler names the gap
        # (DbExtentBinaryMaxintNamed, the fix round of the K1b review)
        _r, _s, plain = _convert(_deck(extra=self._ext(0, 0, 3)))
        for cell in ("", 3, 2, -5):
            with self.subTest(maxint=cell):
                _r, _s, eng = _convert(_deck(extra=self._ext(0, 0, cell)))
                self.assertNotIn(self._ALL, eng)
                self.assertEqual(eng, plain)


class HandOverHelpTexts(unittest.TestCase):
    """The K4-engine hand-over (fix_K4-engine.json, HELP TEXTS): the
    wave-B2 review found --stop-added-mass and --print-every overstating
    (a DT2MS < 0 deck under --ams, an ENDMAS < 0 curve or the routed 2-D
    deck gets no /STOP; the IKEDIT clause left out the 9999 cap and the
    glstat spellings); --dt2ms-tssfac-product gets its blank / AMS clause."""

    def test_stop_added_mass(self):
        h = _action_help("--stop-added-mass")
        for needle in ("On an explicit *CONTROL_TIMESTEP DT2MS < 0 deck that "
                       "gets /DT/NODA/CST", "the MAS.ERR column "
                       "(ecrit.F:516/593), with MESSAGE 208",
                       "A stopped run's listing ends USER BREAK, the engine "
                       "exits 0", "although the deck says /RFILE/OFF "
                       "(measured)", "An ENDMAS < 0 curve, --ams (MAS.ERR "
                       "stays 0 under /DT/AMS, measured) and the routed 2-D "
                       "deck get a warning and no /STOP", "OFF by default"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)
        self.assertNotIn("On a *CONTROL_TIMESTEP DT2MS < 0 deck, write", h)

    def test_print_every(self):
        h = _action_help("--print-every")
        for needle in ("IKEDIT above 9999 is written as 9999",
                       "any *DATABASE_GLSTAT_<option> card counts as glstat",
                       "--print-every 1 keeps /PRINT/-1 on a deck the IKEDIT "
                       "rule moves", "freform.F:1563"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)

    def test_dt2ms_tssfac_product(self):
        h = _action_help("--dt2ms-tssfac-product")
        for needle in ("TSSFAC blank or a curve = 0.9", "the /DT/AMS Tsca "
                       "stays 0.67", "billet-forge deck: the step then "
                       "equals LS-DYNA's 1.08e-7 (1.2e-7 without it)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)

    def test_the_whole_help_renders_with_them(self):
        from k2rad import cli
        text = _collapse(cli.build_parser().format_help())
        for needle in ("--stop-added-mass", "--dt2ms-tssfac-product",
                       "--print-every N", "IKEDIT above 9999"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_k1b_flags_say_what_they_reach(self):
        """--general-shell-edges (K-10) and --single-surface-sst-gap (K-12)
        name their guards, routes and starter probes as built."""
        h = _action_help("--general-shell-edges")
        for needle in ("no shell keeps 1000", "SSID != 0 or implicit card "
                       "keeps its /INTER/TYPE7", "EDGE FLAG 1, 0 ERROR(S)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)
        h = _action_help("--single-surface-sst-gap")
        for needle in ("self-mirrored SOFT -11 / -19", "MST is named as "
                       "unused", "*PART_CONTACT OPTT", "MINIMUM GAP 0.35",
                       "TYPE7, TYPE11 and TYPE19"):
            with self.subTest(needle=needle):
                self.assertIn(needle, h)


class DampingGlobalLcidBetaText(unittest.TestCase):
    """The K2-loads hand-over (fix_K2-loads.json, rejected item 3): the
    K-0P handler sentence 'the /DAMP writer converts the curve in time, not
    VALDMP' left out K-20's beta case - beside a non-zero
    *DAMPING_PART_STIFFNESS beta a curve that varies in time is ONE ungated
    /DAMP at its value at t 0 (writer/loads.py, its LOST warning)."""

    _BETA = "*DAMPING_PART_STIFFNESS\n" + _row(1, 1.0e-7) + "\n"

    def _run(self, beta: bool):
        deck = _deck(extra=_DAMP_CURVE + "*DAMPING_GLOBAL\n" + _row(2, 0.5)
                     + "\n" + (self._BETA if beta else ""))
        return _convert(deck)

    def test_the_sentence_names_the_beta_case(self):
        for beta in (False, True):
            with self.subTest(beta=beta):
                res, _s, _e = self._run(beta)
                self.assertTrue(_has(
                    res.warnings, "*DAMPING_GLOBAL: LCID=2 > 0",
                    "converts the curve in time, not VALDMP - except beside "
                    "a non-zero *DAMPING_PART_STIFFNESS beta, where a curve "
                    "that varies in time becomes ONE ungated /DAMP at its "
                    "value at t 0"), res.warnings)

    @staticmethod
    def _damps(starter: str):
        """(header, alpha, beta, Tstart, Tstop) of every /DAMP card."""
        lines = starter.splitlines()
        out = []
        for i, ln in enumerate(lines):
            if ln.startswith("/DAMP"):
                row = lines[i + 3].split()
                out.append((ln.split("/")[2], row[0], row[1], row[4],
                            row[5]))
        return out

    def test_the_sentence_is_what_the_writer_does(self):
        """_DAMP_CURVE is 50 to t 0.0005, 0 from 0.0006: alone, ONE gated
        alpha-only card (Tstop 0.00055, the edge's midpoint); beside beta
        1e-7, ONE ungated card (Tstop 1e30) carrying both, and the LOST
        warning."""
        writer = "So ONE ungated /DAMP is written with the curve's value at t 0"
        res, s, _e = self._run(True)
        self.assertTrue(_has(res.warnings, writer, "LOST"))
        self.assertEqual([d[1:] for d in self._damps(s)],
                         [("50", "1.000000E-07", "0", "1.000000E+30")])
        res, s, _e = self._run(False)
        self.assertFalse(_has(res.warnings, writer))
        self.assertEqual([d[1:] for d in self._damps(s)],
                         [("50", "0", "0", "0.00055")])


# ── K-05 ─────────────────────────────────────────────────────────────────────

def _soft_deck(soft: int, cid: int = 101,
               kw: str = "CONTACT_AUTOMATIC_GENERAL_ID", card3=(),
               extra: str = "", **kw_deck) -> str:
    """A SOFT-sentinel single-surface card over the two paperboard cards
    (part set 1, MSID 0 = the self mirror); Card A = SOFT only."""
    return _k1a_deck(_k1a_ass(cid, 1, 2, card3=card3, kw=kw,
                              tail=_row(soft) + "\n"), extra=extra,
                     **kw_deck)


#: (SOFT, keyword, what the --inter-gapmin line must say of the route)
_K05_ROUTES = (
    (-7, "CONTACT_AUTOMATIC_GENERAL_ID",
     ("SOFT -7 *CONTACT_AUTOMATIC_GENERAL", "/INTER/TYPE7 with Istf 2, Igap "
      "2", "max(Gapmin, t_s/2 + t_m/2)", "only its Gapmin floor")),
    (-11, "CONTACT_AUTOMATIC_GENERAL_ID",
     ("SOFT -11 *CONTACT_AUTOMATIC_GENERAL", "/INTER/TYPE11 with a constant "
      "gap", "(|SST| + |MST|)/2", "|SST| on a self-contact of shells only "
      "(CardStack K-12")),
    (-19, "CONTACT_AUTOMATIC_GENERAL_ID",
     ("SOFT -19 *CONTACT_AUTOMATIC_GENERAL", "/INTER/TYPE19 with a constant "
      "gap", "(|SST| + |MST|)/2", "|SST| on a self-contact of shells only "
      "(CardStack K-12")),
    (-19, "CONTACT_AIRBAG_SINGLE_SURFACE_ID",
     ("SOFT -19 *CONTACT_AIRBAG_SINGLE_SURFACE", "/INTER/TYPE19",
      "|SST|/2 x SFST")),
)


class InterGapminOnSoftRoutes(unittest.TestCase):
    """K-05 (D5-19): an --inter-gapmin id on a SOFT-routed general contact
    used to read 'no /INTER/TYPE7/101 was emitted (unknown interface id)'
    although the .rad carries it. The end-of-section report names the
    route's own gap rule instead - neutral about emission (it runs before
    the general section writes anything) and not hardwired to TYPE7."""

    def test_the_route_reason_replaces_the_unknown_id_text(self):
        for soft, kw, needles in _K05_ROUTES:
            with self.subTest(soft=soft, kw=kw):
                res, _s, _e = _convert(_soft_deck(soft, kw=kw),
                                       inter_gapmin={101: 0.2})
                ws = [w for w in res.warnings
                      if w.startswith("--inter-gapmin 101=0.2")]
                self.assertEqual(len(ws), 1, ws)
                self.assertIn("override ignored", ws[0])
                self.assertIn("does not reach the SOFT-routed", ws[0])
                for absent in ("unknown interface id", "was emitted",
                               "no /INTER/TYPE7/101"):
                    with self.subTest(absent=absent):
                        self.assertNotIn(absent, ws[0])
                for needle in needles:
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])

    def test_a_single_edge_card_is_named_by_its_spelling(self):
        deck = _k1a_deck("*CONTACT_SINGLE_EDGE_ID\n" + f"{101:>10}edges\n"
                         + _row(1, 0, 2, 0) + "\n" + _row() + "\n" + _row()
                         + "\n")
        res, _s, _e = _convert(deck, inter_gapmin={101: 0.2})
        ws = [w for w in res.warnings if w.startswith("--inter-gapmin 101")]
        self.assertEqual(len(ws), 1, ws)
        self.assertIn("is a *CONTACT_SINGLE_EDGE routed to /INTER/TYPE11", ws[0])
        self.assertNotIn("SOFT -11", ws[0])

    def test_the_bytes_do_not_move(self):
        """The override never reaches the SOFT route: the starter deck is
        the one written without it."""
        for soft, kw, _n in _K05_ROUTES:
            with self.subTest(soft=soft, kw=kw):
                _r, s0, e0 = _convert(_soft_deck(soft, kw=kw))
                _r, s1, e1 = _convert(_soft_deck(soft, kw=kw),
                                      inter_gapmin={101: 0.2})
                self.assertEqual((s0, e0), (s1, e1))

    def test_auto_gapmin_names_the_route_rule(self):
        res, _s, _e = _convert(_soft_deck(-7), auto_gapmin=True)
        self.assertTrue(_has(res.warnings, "--auto-gapmin INTER 101: no "
                             "clearance suggestion", "SOFT = -7",
                             "max(Gapmin, t_s/2 + t_m/2)", "SOFT-routed"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, "no contact interface"))
        self.assertFalse(_has(res.warnings, "whose gap is the Card-3 SST/MST"))

    def test_the_general_docstring_says_the_gap_is_element_derived(self):
        from k2rad.writer import contacts
        doc = _collapse(contacts._make_general_interfaces.__doc__)
        self.assertIn("element-derived", doc)
        self.assertNotIn("their engagement gap is the Card-3 SST/MST only",
                         doc)


# ── K-09 ─────────────────────────────────────────────────────────────────────

def _cards_ac(card_a=(), card_c=None) -> str:
    """Optional Card A (and, when *card_c* is given, a blank Card B and Card
    C) for a *CONTACT tail."""
    tail = _row(*card_a) + "\n"
    if card_c is not None:
        tail += _row() + "\n" + _row(*card_c) + "\n"
    return tail


def _soft_field_lines(res, iid: int):
    return [w for w in res.warnings
            if f" {iid}: optional Card A / C " in w]


class DroppedSoftCardFields(unittest.TestCase):
    """K-09 (D1-4, D6-64): the single-surface, surface-to-surface and
    non-sentinel AUTOMATIC_GENERAL readers never read optional Card A or
    Card C, so SOFT 1 / 2, SOFSCL, SBOPT, DEPTH and DTSTIF vanished without
    a line. They are read now and named by the route that drops them; no
    byte moves (the Istf 7 / IPSTIF opt-in was left out on purpose: the
    plan's not_changing list)."""

    def test_ass_soft_1_and_sofscl_are_named_with_the_sfs_lever(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                  tail=_cards_ac((1, 0.2)))))
        ws = _soft_field_lines(res, 7)
        self.assertEqual(len(ws), 1, res.warnings)
        for needle in ("*CONTACT_AUTOMATIC_SINGLE_SURFACE 7", "SOFT 1",
                       "SOFSCL 0.2", "eq. 30.9-30.10",
                       "/INTER/TYPE7 has no mass / time-step stiffness",
                       "Istf 5 the two in series", "Card-3 SFS > 1",
                       "No byte moves"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])

    def test_the_ssid_0_type25_route_names_the_dead_columns(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            21, 0, 0, tail=_cards_ac((1, 0.2, 0, 1.025, 3, 5)))))
        ws = _soft_field_lines(res, 21)
        self.assertEqual(len(ws), 1, res.warnings)
        for needle in ("SOFT 1", "SOFSCL 0.2", "DEPTH 5", "/INTER/TYPE25",
                       "IPSTIF, STFAC_MDT and DTSTIF",
                       "radioss2022/INTER/inter_type25.cfg:509/516/525"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])
        self.assertNotIn("SBOPT", ws[0])        # a SOFT 2 option, unused

    def test_s2s_dtstif_is_named(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, tail=_cards_ac((1,), (0, 0, 0, 1.0e-6)))))
        ws = _soft_field_lines(res, 12)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("Card C DTSTIF 1e-06", ws[0])
        self.assertIn("SOFT 1", ws[0])

    def test_soft_2_names_its_options_on_the_general_route(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_cards_ac((2, 0.0, 0, 0.0, 3, 5)))))
        ws = _soft_field_lines(res, 31)
        self.assertEqual(len(ws), 1, res.warnings)
        for needle in ("*CONTACT_AUTOMATIC_GENERAL 31", "SOFT 2",
                       "segment-to-segment", "SBOPT 3", "DEPTH 5"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])

    def test_defaults_say_nothing(self):
        for name, contact in (
                ("ASS", _k1a_ass(7, 1, 2, tail=_cards_ac((0, 0.1, 0, 0, 2,
                                                          2)))),
                ("GENERAL DEPTH 3", _k1a_ass(
                    31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
                    tail=_cards_ac((0, 0.0, 0, 0.0, 0, 3)))),
                ("S2S", _k1a_s2s(12, tail=_cards_ac(()))),
                ("SOFSCL without SOFT 1", _k1a_s2s(12, tail=_cards_ac(
                    (0, 0.5))))):
            with self.subTest(name):
                res, _s, _e = _convert(_k1a_deck(contact))
                self.assertEqual([w for w in res.warnings
                                  if "optional Card A / C" in w], [])

    def test_the_bytes_do_not_move(self):
        """Card A / C read and named, nothing written: the decks convert to
        the bytes of the same decks without those cards."""
        cases = (
            (_k1a_ass(7, 1, 2), _k1a_ass(7, 1, 2, tail=_cards_ac(
                (1, 0.2, 0, 1.025, 3, 5)))),
            (_k1a_ass(21, 0, 0), _k1a_ass(21, 0, 0, tail=_cards_ac(
                (2, 0.0, 0, 0.0, 1, 5)))),
            (_k1a_s2s(12), _k1a_s2s(12, tail=_cards_ac((1,),
                                                        (0, 0, 0, 1e-6)))))
        for plain, carded in cases:
            with self.subTest(carded=carded.splitlines()[0]):
                _r, s0, e0 = _convert(_k1a_deck(plain))
                _r, s1, e1 = _convert(_k1a_deck(carded))
                self.assertEqual((s0, e0), (s1, e1))

    def test_the_handlers_store_the_fields(self):
        st = _dispatch(_k1a_deck(
            _k1a_ass(7, 1, 2, tail=_cards_ac((1, 0.2, 0, 1.025, 3, 5),
                                             (0, 1, 0, 2.5e-6)))
            + _k1a_s2s(12, tail=_cards_ac((2, 0.0, 0, 0.0, 1, 25),
                                          (0, 0, 0, 1e-6)))))
        a = st.contacts_single[0]
        self.assertEqual((a.soft, a.sofscl, a.sbopt, a.depth, a.dtstif,
                          a.ignore), (1, 0.2, 3, 5, 2.5e-6, 1))
        b = st.contacts_surf2surf[0]
        self.assertEqual((b.soft, b.sbopt, b.depth, b.dtstif),
                         (2, 1, 25, 1e-6))

    def test_soft_2_on_general_says_ls_dyna_does_not_support_it(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            31, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_cards_ac((2,)))))
        ws = _soft_field_lines(res, 31)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("not for AUTOMATIC_GENERAL", ws[0])
        self.assertIn("p.11-123", ws[0])


# ── K-10 ─────────────────────────────────────────────────────────────────────

def _type25_card1(starter: str, iid: int):
    """Card 1 tokens of /INTER/TYPE25/<iid>: surf_ID1 surf_ID2 Istf Ithe
    Igap Irem_i2 Idel Iedge [IPSTIF]."""
    return _inter_rows(starter, f"/INTER/TYPE25/{iid}")[0]


def _general0(cid: int = 41, tail: str = "") -> str:
    """An ordinary (non-sentinel) SSID = 0 *CONTACT_AUTOMATIC_GENERAL."""
    return _k1a_ass(cid, 0, 0, kw="CONTACT_AUTOMATIC_GENERAL_ID", tail=tail)


def _without_shells(deck: str) -> str:
    out = re.sub(r"\*ELEMENT_SHELL\n(?:[^*].*\n)*", "", deck)
    assert out != deck
    return out


def _eroding_s2s(cid: int = 51, card_a=(2,)) -> str:
    """*CONTACT_ERODING_SURFACE_TO_SURFACE: the cards on the block, its
    mandatory Card 4 (ISYM 0, EROSOP 1, IADJ 1), then Card A."""
    return _k1a_s2s(cid, kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
                    tail=_row(0, 1, 1) + "\n" + _row(*card_a) + "\n")


class GeneralShellEdges(unittest.TestCase):
    """K-10 (D1-6): an ordinary SSID = 0 *CONTACT_AUTOMATIC_GENERAL - which
    checks the exterior shell edges along their whole length (Vol I R17
    p.11-123 General Remark 2) - took the all-parts /INTER/TYPE25 with Iedge
    1000 (no edge contact). --general-shell-edges (opt-in) writes Iedge 1,
    the shells' external border edges (2022 Reference Guide /INTER/TYPE25
    Iedge 1). Guards: no shell -> 1000 kept; beams named; an SSID != 0 or
    implicit card keeps its /INTER/TYPE7, said."""

    def test_the_flag_writes_iedge_1_and_moves_nothing_else(self):
        _r, s0, _e = _convert(_k1a_deck(_general0()))
        self.assertEqual(_type25_card1(s0, 41)[7], "1000")
        res, s1, _e = _convert(_k1a_deck(_general0()),
                               general_shell_edges=True)
        self.assertEqual(_type25_card1(s1, 41)[7], "1")
        diff = [(a, b) for a, b in zip(s0.splitlines(), s1.splitlines())
                if a != b]
        self.assertEqual(len(diff), 1, diff)
        self.assertEqual(len(s0.splitlines()), len(s1.splitlines()))
        self.assertTrue(_has(res.warnings, "--general-shell-edges",
                             "/INTER/TYPE25/41 Iedge 1", "external border "
                             "edges of the shell segments", "p.11-123",
                             "WARNING 1633 (Inacti 5, inint3.F:2368)"))

    def test_a_single_surface_card_keeps_1000(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0)),
                              general_shell_edges=True)
        self.assertEqual(_type25_card1(s, 21)[7], "1000")
        self.assertFalse(_has(res.warnings, "--general-shell-edges"))

    def test_where_the_flag_does_not_reach_it_says_so(self):
        for name, deck in (
                ("SSID != 0", _k1a_deck(_k1a_ass(
                    42, 1, 2, kw="CONTACT_AUTOMATIC_GENERAL_ID"))),
                ("implicit", _k1a_deck(_general0(), implicit=True))):
            with self.subTest(name):
                res, s, _e = _convert(deck, general_shell_edges=True)
                self.assertNotIn("/INTER/TYPE25/", s)
                self.assertTrue(_has(res.warnings, "--general-shell-edges "
                                     "does not reach", "/INTER/TYPE7"),
                                res.warnings)

    def test_no_shell_keeps_1000_and_says_why(self):
        res, s, _e = _convert(_without_shells(_k1a_deck(_general0())),
                              general_shell_edges=True)
        self.assertEqual(_type25_card1(s, 41)[7], "1000")
        self.assertTrue(_has(res.warnings, "--general-shell-edges",
                             "no shell", "Iedge 1000"), res.warnings)

    def test_beams_are_named(self):
        beam = ("*ELEMENT_BEAM\n" + "".join(f"{v:>8}" for v in
                                             (301, 103, 19, 20)) + "\n"
                + "*PART\ntruss\n" + _row(103, 3, 3) + "\n"
                + "*SECTION_BEAM\n" + _row(3, 3) + "\n" + _row(1.0) + "\n"
                + "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n")
        res, s, _e = _convert(_k1a_deck(_general0(), extra=beam),
                              general_shell_edges=True)
        self.assertEqual(_type25_card1(s, 41)[7], "1")
        self.assertTrue(_has(res.warnings, "--general-shell-edges",
                             "1 beam element", "beam-to-beam"), res.warnings)


class Soft2EdgeGate(unittest.TestCase):
    """K-10: dyna2rad writes Iedge 22 (all edges) for every SOFT 2 card of
    the ERODING_SURFACE_TO_SURFACE / AUTOMATIC_NODES_TO_SURFACE family, but
    LS-DYNA's SOFT 2 checks edge-to-edge penetration only with DEPTH 5 / 15
    / 25 / 35 / 45 / 55 or SBOPT 1 (Vol I R17 p.11-91/97; 'By default, we do
    not enable edge treatment for SOFT = 2', p.11-94). The gate follows
    LS-DYNA; Istf 2 stays."""

    def test_soft_2_without_an_edge_depth_writes_no_iedge_22(self):
        res, s, _e = _convert(_k1a_deck(_eroding_s2s()))
        c1 = _type25_card1(s, 51)
        self.assertEqual((c1[2], c1[7]), ("2", "1000"))
        self.assertTrue(_has(res.warnings, "SOFT=2", "Iedge=1000",
                             "DEPTH 5/15/25/35/45/55 or SBOPT 1"),
                        res.warnings)

    def test_an_edge_depth_or_sbopt_1_writes_iedge_22(self):
        for card_a in ((2, 0, 0, 0, 0, 5), (2, 0, 0, 0, 0, 25),
                       (2, 0, 0, 0, 0, 55), (2, 0, 0, 0, 1, 0)):
            with self.subTest(card_a=card_a):
                _r, s, _e = _convert(_k1a_deck(_eroding_s2s(card_a=card_a)))
                c1 = _type25_card1(s, 51)
                self.assertEqual((c1[2], c1[7]), ("2", "22"))

    def test_the_other_soft_values_keep_their_cells(self):
        for card_a, istf in (((0,), "2"), ((1,), "4"), ((0, 0, 0, 0, 0, 5),
                                                        "2")):
            with self.subTest(card_a=card_a):
                _r, s, _e = _convert(_k1a_deck(_eroding_s2s(card_a=card_a)))
                c1 = _type25_card1(s, 51)
                self.assertEqual((c1[2], c1[7]), (istf, "1000"))


# ── K-11 ─────────────────────────────────────────────────────────────────────

_TERM_SHORT = "*CONTROL_TERMINATION\n" + _row(1.0e-4) + "\n"


def _endtim(deck: str, endtim: float = 0.01) -> str:
    """_k1a_deck with ENDTIM *endtim* instead of 1e-4."""
    assert deck.count(_TERM_SHORT) == 1
    return deck.replace(_TERM_SHORT, "*CONTROL_TERMINATION\n" + _row(endtim)
                        + "\n")


#: the row index of the Stfac / Fric / ... / Tstart / Tstop card per type
_T_ROW = {"TYPE7": 3, "TYPE25": 3, "TYPE11": 2, "TYPE19": 3}


def _t_cells(starter: str, kind: str, iid: int):
    """(Tstart, Tstop) as written on /INTER/<kind>/<iid>."""
    row = _inter_rows(starter, f"/INTER/{kind}/{iid}")[_T_ROW[kind]]
    return row[3], row[4]


def _card2(bt=0.0, dt="", vdc=0.0):
    return (0.2, 0.2, 0, 0, vdc, 0, bt, dt)


def _k11_routes(card2):
    """(name, deck, convert kwargs, kind, id) for every route K-11 reaches."""
    gen = "CONTACT_AUTOMATIC_GENERAL_ID"
    n2s = _k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3, card2=card2,
                   kw="CONTACT_NODES_TO_SURFACE_ID")
    return (
        ("ASS SSID != 0", _k1a_deck(_k1a_ass(7, 1, 2, card2=card2)), {},
         "TYPE7", 7),
        ("ASS SSID = 0 explicit", _k1a_deck(_k1a_ass(21, 0, 0, card2=card2)),
         {}, "TYPE25", 21),
        ("ASS SSID = 0 implicit", _k1a_deck(_k1a_ass(21, 0, 0, card2=card2),
                                            implicit=True), {}, "TYPE7", 21),
        ("S2S", _k1a_deck(_k1a_s2s(12, card2=card2)), {}, "TYPE7", 12),
        ("S2S --s2s-type25", _k1a_deck(_k1a_s2s(12, card2=card2)),
         {"s2s_type25": True}, "TYPE25", 12),
        ("GENERAL SOFT -7", _k1a_deck(_k1a_ass(31, 1, 2, card2=card2, kw=gen,
                                               tail=_row(-7) + "\n")), {},
         "TYPE7", 31),
        ("GENERAL SOFT -11", _k1a_deck(_k1a_ass(32, 1, 2, card2=card2, kw=gen,
                                                tail=_row(-11) + "\n")), {},
         "TYPE11", 32),
        ("GENERAL SOFT -19", _k1a_deck(_k1a_ass(33, 1, 2, card2=card2, kw=gen,
                                                tail=_row(-19) + "\n")), {},
         "TYPE19", 33),
        ("ERODING S2S", _k1a_deck(_k1a_s2s(
            51, card2=card2, kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
            tail=_row(0, 1, 1) + "\n")), {}, "TYPE25", 51),
        ("routed implicit N2S", _k1a_deck(n2s, implicit=True,
                                          extra=_card_nset()), {}, "TYPE7",
         16),
    )


class BirthDeathTimes(unittest.TestCase):
    """K-11 (D1-14): Card-2 BT / DT reached only the ERODING / node-to-
    surface TYPE25s and the routed N2S TYPE7, and with no sign rule (a
    negative DT was written as a negative Tstop). Every route carries them
    now, by the rules of Vol I R17 p.11-29/30: DT = -9999 -> both 0 and
    named; BT < 0 -> Tstart 0 (after dynamic relaxation the contact is
    active whatever BT); DT < 0 -> Tstart |BT| / Tstop |DT| (after dynamic
    relaxation the times are |BT| and |DT|); Tstop 0 for a blank, >= 1e19
    or >= ENDTIM death time. A converted run has no dynamic-relaxation
    phase, which is what the negative values are about."""

    def test_every_route_carries_bt_and_dt(self):
        for name, deck, kw, kind, iid in _k11_routes(_card2(0.001, 0.004)):
            with self.subTest(name):
                res, s, _e = _convert(_endtim(deck), **kw)
                self.assertEqual(_t_cells(s, kind, iid), ("0.001", "0.004"))
                self.assertTrue(_has(res.warnings, f" {iid}: Card-2 BT 0.001 "
                                     "/ DT 0.004", f"/INTER/{kind}/{iid} "
                                     "Tstart 0.001 / Tstop 0.004"),
                                res.warnings)

    def test_dt_minus_9999_writes_both_0_and_names_the_curve(self):
        for name, deck, kw, kind, iid in _k11_routes(_card2(3, -9999)):
            with self.subTest(name):
                res, s, _e = _convert(_endtim(deck), **kw)
                self.assertEqual(_t_cells(s, kind, iid), ("0", "0"))
                self.assertTrue(_has(res.warnings, "DT = -9999", "BT = 3",
                                     "birth-time / death-time pairs",
                                     "Remark 2"), res.warnings)

    def test_the_sign_rules(self):
        """BT < 0 with DT >= 0: after dynamic relaxation LS-DYNA activates
        the contact whatever BT (p.11-29) - Tstart 0. DT < 0: after
        dynamic relaxation the birth and death times are |BT| and |DT|
        (p.11-30), so with both negative Tstart is |BT| (an earlier
        revision wrote 0 there)."""
        for card2, want, needles in (
                (_card2(-0.001, 0.004), ("0", "0.004"),
                 ("BT -0.001 < 0", "whatever BT", "Tstart 0")),
                (_card2(-0.001, -0.004), ("0.001", "0.004"),
                 ("DT -0.004 < 0", "|BT| and |DT|",
                  "Tstart 0.001 / Tstop 0.004")),
                (_card2(0.002, -0.004), ("0.002", "0.004"),
                 ("DT -0.004 < 0", "|BT| and |DT|",
                  "Tstart 0.002 / Tstop 0.004"))):
            with self.subTest(bt=card2[6], dt=card2[7]):
                res, s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
                    7, 1, 2, card2=card2))))
                self.assertEqual(_t_cells(s, "TYPE7", 7), want)
                self.assertTrue(_has(res.warnings, *needles), res.warnings)
        res, _s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
            7, 1, 2, card2=_card2(-0.001, -0.004)))))
        self.assertFalse(_has(res.warnings, "whatever BT"), res.warnings)
        for dt in ("", 0.0, 1.0e20, 0.01, 0.02):
            with self.subTest(dt=dt):
                res, s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
                    7, 1, 2, card2=_card2(0.001, dt)))))
                self.assertEqual(_t_cells(s, "TYPE7", 7), ("0.001", "0"))

    def test_the_eroding_route_no_longer_writes_a_negative_tstop(self):
        deck = _endtim(_k1a_deck(_k1a_s2s(
            51, card2=_card2(0.0, -0.004),
            kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
            tail=_row(0, 1, 1) + "\n")))
        _r, s, _e = _convert(deck)
        self.assertEqual(_t_cells(s, "TYPE25", 51), ("0", "0.004"))

    def test_the_defaults_keep_their_bytes(self):
        for (n0, d0, k0, _k, _i), (_n1, d1, _k1, _k2, _i2) in zip(
                _k11_routes((0.2, 0.2)), _k11_routes(_card2(0.0, 1.0e20))):
            with self.subTest(n0):
                _r, s0, e0 = _convert(d0, **k0)
                _r, s1, e1 = _convert(d1, **k0)
                self.assertEqual((s0, e0), (s1, e1))

    def test_vdc_on_the_type25_self_route_is_named_not_written(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                 card2=_card2(vdc=20.0))))
        # card 5: IBC IVIS2 Inacti VISs Ithick Pmax
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/21")[4][3], "0.05")
        self.assertTrue(_has(res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE "
                             "21: Card-2 VDC 20", "not written",
                             "VISs 0.05"), res.warnings)
        card_e = _row() + "\n" + _row() + "\n" + _row() + "\n" + _row() \
            + "\n" + _row(0, 0, 0, 0, 0, 1) + "\n"
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                 card2=_card2(vdc=20.0),
                                                 tail=card_e)))
        self.assertEqual(_inter_rows(s, "/INTER/TYPE25/21")[4][3], "0.05")
        self.assertFalse(_has(res.warnings, "21: Card-2 VDC 20", "not "
                              "written"))
        self.assertTrue(_has(res.warnings, "ICOR 1", "coefficient of "
                             "restitution"), res.warnings)


# ── K-12 ─────────────────────────────────────────────────────────────────────

def _gap11(starter: str, iid: int) -> float:
    return float(_inter_rows(starter, f"/INTER/TYPE11/{iid}")[2][2])


def _gap19(starter: str, iid: int) -> float:
    return float(_inter_rows(starter, f"/INTER/TYPE19/{iid}")[3][2])


class SingleSurfaceSstGap(unittest.TestCase):
    """K-12 (D1-15, D5-15; default ON, --no-single-surface-sst-gap): every
    segment of a single-surface contact is SURFA, so two shells that each
    carry the contact thickness SST meet at SST/2 + SST/2 = |SST| (Vol I R17
    p.11-33 SAST); the two-surface (|SST| + |MST|)/2 engaged them at half
    that. Shell-only Igap-0 routes only: a mixed shell / solid set is refused
    by name, the SOFT -7 TYPE7 (Igap 2) gets a warning, the airbag route and
    every two-surface route are untouched."""

    def test_the_shell_ass_route_takes_sst(self):
        deck = _k1a_deck(_k1a_ass(7, 1, 2, card3=(0, 0, 0.35)))
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 7)["gapmin"], 0.35)
        self.assertTrue(_has(res.warnings, "CONTACT 7:", "Gapmin=0.35",
                             "|SST|/2 + |SST|/2", "--no-single-surface-sst-gap"),
                        res.warnings)
        res, s, _e = _convert(deck, single_surface_sst_gap=False)
        self.assertEqual(_type7(s, 7)["gapmin"], 0.175)
        self.assertFalse(_has(res.warnings, "|SST|/2 + |SST|/2"))

    def test_mst_is_named_as_unused(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                 card3=(0, 0, 0.35, 0.1))))
        self.assertEqual(_type7(s, 7)["gapmin"], 0.35)
        self.assertTrue(_has(res.warnings, "CONTACT 7:", "MST 0.1 is not "
                             "used", "no SURFB"), res.warnings)

    def test_a_negative_sst_is_named(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                 card3=(0, 0, -0.35))))
        self.assertEqual(_type7(s, 7)["gapmin"], 0.35)
        self.assertTrue(_has(res.warnings, "negative SST"), res.warnings)

    def test_a_mixed_shell_and_solid_set_is_refused_by_name(self):
        deck = _k1a_deck(_k1a_ass(7, 1, 2, card3=(0, 0, 0.35)))
        old_set = "*SET_PART_LIST\n" + _row(1) + "\n" + _row(101, 102) + "\n"
        deck = deck.replace(old_set, "*SET_PART_LIST\n" + _row(1) + "\n"
                            + _row(101, 102, 1) + "\n")
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 7)["gapmin"], 0.175)
        self.assertTrue(_has(res.warnings, "CONTACT 7:", "mixes shells and "
                             "solids", "refused", "(|SST| + |MST|)/2 = 0.175"),
                        res.warnings)
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, card3=(0, 0, 0.35)),
                                        implicit=True))
        self.assertEqual(_type7(s, 21)["gapmin"], 0.175)
        self.assertTrue(_has(res.warnings, "CONTACT 21:", "mixes shells and "
                             "solids"), res.warnings)

    def test_the_soft_11_and_19_self_mirrors_take_sst(self):
        gen = "CONTACT_AUTOMATIC_GENERAL_ID"
        for soft, gap in ((-11, _gap11), (-19, _gap19)):
            with self.subTest(soft=soft):
                deck = _k1a_deck(_k1a_ass(31, 1, 2, card3=(0, 0, 0.35), kw=gen,
                                          tail=_row(soft) + "\n"))
                _r, s, _e = _convert(deck)
                self.assertEqual(gap(s, 31), 0.35)
                _r, s, _e = _convert(deck, single_surface_sst_gap=False)
                self.assertEqual(gap(s, 31), 0.175)

    def test_soft_7_names_optt_below_the_shell_thickness(self):
        gen = "CONTACT_AUTOMATIC_GENERAL_ID"
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            31, 1, 2, card3=(0, 0, 0.2), kw=gen, tail=_row(-7) + "\n")))
        self.assertEqual(_type7(s, 31)["gapmin"], 0.1)
        self.assertTrue(_has(res.warnings, "CONTACT 31:", "Igap 2",
                             "below the shell thickness t = 0.35",
                             "no effect", "*PART_CONTACT OPTT 0.2"),
                        res.warnings)
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            31, 1, 2, card3=(0, 0, 0.5), kw=gen, tail=_row(-7) + "\n")))
        self.assertFalse(_has(res.warnings, "*PART_CONTACT OPTT"))

    def test_the_airbag_and_two_surface_routes_are_untouched(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            31, 1, 2, card3=(0, 0, 0.35), kw="CONTACT_AIRBAG_SINGLE_SURFACE_ID",
            tail=_row(-19) + "\n")))
        self.assertEqual(_gap19(s, 31), 0.175)
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(12, card3=(0, 0, 0.35))))
        self.assertEqual(_type7(s, 12)["gapmin"], 0.175)
        self.assertFalse(_has(res.warnings, "|SST|/2 + |SST|/2"))


# ── K-14 ─────────────────────────────────────────────────────────────────────

def _ignore_tail(ignore) -> str:
    """Blank Cards A and B, then Card C with IGNORE *ignore*."""
    return _row() + "\n" + _row() + "\n" + _row(0, ignore) + "\n"


class MortarAndIgnoreTexts(unittest.TestCase):
    """K-14 (D1-8), text only: the 'mortar' note called IGNORE 2's MPAR1 a
    'prestress/ramp variant' - it is an initial contact PRESSURE, the
    removal over time is IGNORE 3 / 4 (Vol I R17 p.11-133/134 General Remark
    14) - and said 'converts to the node-to-segment /INTER/TYPE7', false on
    the SSID = 0 explicit route; the AUTOMATIC_SINGLE_SURFACE_MORTAR row
    printed no note at all; the IGNORE 3 / 4 fallback said 'LS-DYNA removes
    initial penetrations at initialization (moves nodes)'."""

    _MORTAR = "CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID"

    def test_the_mortar_note_says_what_ignore_2_and_mpar1_are(self):
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        note = _collapse(_CONTACT_SPELLING_NOTES["mortar"])
        for needle in ("IGNORE default of 2", "initial contact PRESSURE",
                       "not a removal over time", "IGNORE 3 / 4",
                       "between t = 0 and MPAR1", "p.11-133/134",
                       "/INTER/TYPE25 for an SSID = 0"):
            with self.subTest(needle=needle):
                self.assertIn(needle, note)
        self.assertNotIn("prestress/ramp variants", note)

    def test_the_single_surface_mortar_row_prints_it(self):
        for ssid, sstyp in ((1, 2), (0, 0)):
            with self.subTest(ssid=ssid):
                res, s, e = _convert(_k1a_deck(_k1a_ass(7, ssid, sstyp,
                                                        kw=self._MORTAR)))
                self.assertTrue(_has(
                    res.warnings, "*CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR 7",
                    "MORTAR is a segment-to-segment contact"), res.warnings)
                _r, s0, e0 = _convert(_k1a_deck(_k1a_ass(7, ssid, sstyp)))
                self.assertEqual((s, e), (s0, e0))         # no byte moves

    def test_mortar_card_a_fields_are_not_named(self):
        """Table 11-1 (p.11-135): on a Mortar contact only BSORT of Card A
        applies - LS-DYNA ignores SOFT / SOFSCL / DEPTH there too."""
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, kw=self._MORTAR, tail=_cards_ac((1, 0.2, 0, 0, 3, 5)))))
        self.assertEqual(_soft_field_lines(res, 7), [])

    def test_the_ignore_3_and_4_fallback(self):
        for ignore in (3, 4):
            with self.subTest(ignore=ignore):
                res, s, _e = _convert(_k1a_deck(_k1a_ass(
                    7, 1, 2, kw=self._MORTAR, tail=_ignore_tail(ignore))))
                self.assertEqual(_type7(s, 7)["inacti"], "5")
                w = [x for x in res.warnings
                     if x.startswith(f"CONTACT 7: ignore={ignore}")]
                self.assertEqual(len(w), 1, res.warnings)
                for needle in ("Mortar only", "between t = 0 and MPAR1",
                               "Inacti=5", "zero-force state",
                               "no closure over time"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, w[0])
                self.assertNotIn("moves nodes", w[0])
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, kw=self._MORTAR, tail=_ignore_tail(4))))
        self.assertTrue(_has(res.warnings, "CONTACT 7: ignore=4", "MPAR2"))
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2)))
        self.assertTrue(_has(res.warnings, "CONTACT 7: ignore=0",
                             "moves nodes"))              # IGNORE 0 unchanged

    def test_a_negative_ignore_is_named(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, kw=self._MORTAR, tail=_ignore_tail(-2))))
        self.assertEqual(_type7(s, 7)["inacti"], "5")
        self.assertTrue(_has(res.warnings, "CONTACT 7: ignore=-2", "Mortar "
                             "only", "same part"), res.warnings)


# ── K-16 ─────────────────────────────────────────────────────────────────────

def _cards_ae(srnde=0, icor=0, shledg=0, card_a=()) -> str:
    """Optional Cards A (*card_a*), B and C blank, D with SHLEDG, E with
    SRNDE / ICOR - "If using Optional Card E, then you must define Optional
    Cards A, B, C, and D" (Vol I R17 p.11-114)."""
    return (_row(*card_a) + "\n" + _row() + "\n" + _row() + "\n"
            + _row(0, 0, 0, 0, 0, 0, 0, shledg) + "\n"
            + _row(0, 0, 0, srnde, 0, icor) + "\n")


def _ishape(starter: str, iid: int) -> str:
    """Card 3 of /INTER/TYPE25/<iid>: Stmin Stmax Igap0 Ishape ..."""
    return _inter_rows(starter, f"/INTER/TYPE25/{iid}")[2][3]


_REACH = "(t_s + t_m)/2"


class SrndeIshape(unittest.TestCase):
    """K-16 (D1-19): optional Card E SRNDE (Vol I R17 p.11-114/115, Remark 3
    p.11-116/117) is read. SRNDE 1 - exterior shell edges rounded, not
    extended - writes TYPE25 Ishape 2 (round gap) on both TYPE25 emitters;
    SRNDE 0 / blank keeps today's cell (0 = /DEFAULT = 1, square) with a
    note: LS-DYNA's default cap reaches (t_s + t_m)/2 past a free edge,
    TYPE25's gap never more than t_s/2 (2022 Reference Guide /INTER/TYPE25
    comment 4). For SOFT 2, SHLEDG (Card D) or DEPTH 23/33/35/55 take
    precedence; on a Mortar card Cards D-G do not apply (p.11-135)."""

    def test_srnde_1_writes_ishape_2_on_the_self_route(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                 tail=_cards_ae(srnde=1))))
        self.assertEqual(_ishape(s, 21), "2")
        self.assertTrue(_has(res.warnings, "21: Card E SRNDE 1", "Ishape 2",
                             "round"), res.warnings)
        self.assertFalse(_has(res.warnings, "21:", _REACH))

    def test_srnde_1_on_the_other_type25_emitter(self):
        for name, contact, kw in (
                ("ERODING S2S", _k1a_s2s(
                    51, kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
                    tail=_row(0, 1, 1) + "\n" + _cards_ae(srnde=1)), {}),
                ("--s2s-type25", _k1a_s2s(51, tail=_cards_ae(srnde=1)),
                 {"s2s_type25": True})):
            with self.subTest(name):
                res, s, _e = _convert(_k1a_deck(contact), **kw)
                self.assertEqual(_ishape(s, 51), "2")
                self.assertTrue(_has(res.warnings, "51: Card E SRNDE 1",
                                     "Ishape 2"), res.warnings)

    def test_blank_keeps_the_cell_with_the_reach_note(self):
        _r, s0, e0 = _convert(_k1a_deck(_k1a_ass(21, 0, 0)))
        res, s1, e1 = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                  tail=_cards_ae(srnde=0))))
        self.assertEqual(_ishape(s1, 21), "0")
        self.assertEqual((s0, e0), (s1, e1))
        for r in (_r, res):
            self.assertTrue(_has(r.warnings, "21:", _REACH, "t_s/2",
                                 "Ishape"), r.warnings)

    def test_srnde_2_keeps_the_cell_without_a_note(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                 tail=_cards_ae(srnde=2))))
        self.assertEqual(_ishape(s, 21), "0")
        self.assertFalse(_has(res.warnings, "21:", _REACH))
        self.assertFalse(_has(res.warnings, "21: Card E SRNDE"))

    def test_soft_2_shledg_or_depth_takes_precedence(self):
        for shledg, depth in ((1, 0), (0, 23), (0, 55)):
            with self.subTest(shledg=shledg, depth=depth):
                res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(
                    srnde=1, shledg=shledg, card_a=(2, 0, 0, 0, 0, depth)))))
                self.assertEqual(_ishape(s, 21), "0")
                self.assertTrue(_has(res.warnings, "21: Card E SRNDE 1 is not "
                                     "used", "SOFT 2"), res.warnings)

    def test_mortar_has_no_card_e(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            21, 0, 0, kw="CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID",
            tail=_cards_ae(srnde=1))))
        self.assertEqual(_ishape(s, 21), "0")
        self.assertFalse(_has(res.warnings, "21: Card E SRNDE"))
        self.assertFalse(_has(res.warnings, "21:", _REACH))

    def test_no_shell_no_note(self):
        res, s, _e = _convert(_without_shells(_k1a_deck(_k1a_ass(21, 0, 0))))
        self.assertEqual(_ishape(s, 21), "0")
        self.assertFalse(_has(res.warnings, "21:", _REACH))

    def test_a_type7_route_names_srnde_as_not_converted(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                 tail=_cards_ae(srnde=1))))
        self.assertIn("/INTER/TYPE7/7", s)
        self.assertTrue(_has(res.warnings, "7: Card E SRNDE 1 is not "
                             "converted", "/INTER/TYPE7"), res.warnings)

    def test_the_handlers_store_srnde_shledg_icor(self):
        st = _dispatch(_k1a_deck(
            _k1a_ass(21, 0, 0, tail=_cards_ae(srnde=1, icor=1, shledg=2))
            + _k1a_s2s(51, kw="CONTACT_ERODING_SURFACE_TO_SURFACE_ID",
                       tail=_row(0, 1, 1) + "\n" + _cards_ae(
                           srnde=2, shledg=1, card_a=(2, 0, 0, 0, 1, 25)))))
        a = st.contacts_single[0]
        self.assertEqual((a.srnde, a.icor, a.shledg), (1, 1, 2))
        b = st.contacts_type25[0]
        self.assertEqual((b.srnde, b.shledg, b.soft, b.sbopt, b.depth),
                         (2, 1, 2, 1, 25))


# ═════════════════════════════════════════════════════════════════════════════
# K1b FIX ROUND (the wave-C review of K-05 .. K-16): the rules whose mutants
# survived the whole suite. Each test names the review's mutant id (the
# review's rv_mutate.py table) it kills; the fix round's mutation log has
# the KILLED line of every one.
# ═════════════════════════════════════════════════════════════════════════════

def _no_termination(deck: str) -> str:
    """_k1a_deck without its *CONTROL_TERMINATION card: ENDTIM unknown."""
    assert deck.count(_TERM_SHORT) == 1
    return deck.replace(_TERM_SHORT, "")


def _type25_ids_by_title(starter: str):
    """``{title: id}`` of every /INTER/TYPE25 block of *starter*."""
    lines = starter.splitlines()
    return {lines[i + 1]: int(ln.split("/")[3])
            for i, ln in enumerate(lines) if ln.startswith("/INTER/TYPE25/")}


class BirthDeathReviewPins(unittest.TestCase):
    """K-11: the Card-2 BT / DT rules the review's mutants showed unpinned."""

    def test_a_far_death_without_endtim_writes_tstop_0(self):
        """R11a: with no *CONTROL_TERMINATION (ENDTIM unknown) a DT >= 1e19
        - LS-DYNA's 1e20 - is still Tstop 0 (never), not the raw value; a
        blank DT (read as 0, fixed or comma format alike) is 0 too."""
        eroding = "CONTACT_ERODING_SURFACE_TO_SURFACE_ID"
        for name, contact, kind, iid in (
                ("ASS blank DT", _k1a_ass(7, 1, 2), "TYPE7", 7),
                ("ASS DT 1e20", _k1a_ass(7, 1, 2, card2=_card2(0.0, 1.0e20)),
                 "TYPE7", 7),
                ("ASS BT 0.001 DT 1e20", _k1a_ass(
                    7, 1, 2, card2=_card2(0.001, 1.0e20)), "TYPE7", 7),
                ("ERODING S2S blank DT", _k1a_s2s(
                    51, kw=eroding, tail=_row(0, 1, 1) + "\n"), "TYPE25", 51),
                ("ERODING S2S DT 1e20", _k1a_s2s(
                    51, card2=_card2(0.0, 1.0e20), kw=eroding,
                    tail=_row(0, 1, 1) + "\n"), "TYPE25", 51)):
            with self.subTest(name):
                _r, s, _e = _convert(_no_termination(_k1a_deck(contact)))
                self.assertEqual(float(_t_cells(s, kind, iid)[1]), 0.0)

    def test_a_late_death_rides_on_a_line_printed_anyway(self):
        """R11b: a death time at / past ENDTIM is said on the line the
        birth time prints; 0, blank and >= 1e19 are not late deaths."""
        for dt, late in ((0.02, True), (0.01, True), (0.004, False),
                         (1.0e20, False), ("", False), (0.0, False)):
            with self.subTest(dt=dt):
                res, _s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
                    7, 1, 2, card2=_card2(0.001, dt)))))
                ws = [w for w in res.warnings if " 7: Card-2 BT 0.001" in w]
                self.assertEqual(len(ws), 1, res.warnings)
                self.assertEqual("at or past ENDTIM 0.01" in ws[0], late,
                                 ws[0])

    def test_a_death_time_alone_is_named(self):
        """R11c: BT 0 with a death time inside the run writes Tstop and
        says so - the line does not need a birth time."""
        res, s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
            7, 1, 2, card2=_card2(0.0, 0.004)))))
        self.assertEqual(_t_cells(s, "TYPE7", 7), ("0", "0.004"))
        self.assertTrue(_has(res.warnings, " 7: Card-2 BT 0 / DT 0.004",
                             "/INTER/TYPE7/7 Tstart 0 / Tstop 0.004"),
                        res.warnings)

    def test_no_vdc_says_nothing_on_the_type25_self_route(self):
        """R11d: a VDC of 0, with or without a Card E ICOR, prints neither
        the VDC line nor the restitution line."""
        icor = (_row() + "\n" + _row() + "\n" + _row() + "\n" + _row() + "\n"
                + _row(0, 0, 0, 0, 0, 1) + "\n")
        for name, tail in (("no Card E", ""), ("ICOR 1", icor)):
            with self.subTest(name):
                res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0,
                                                         tail=tail)))
                self.assertIn("/INTER/TYPE25/21", s)
                self.assertFalse(_has(res.warnings, "21: Card-2 VDC"),
                                 res.warnings)
                self.assertFalse(_has(res.warnings, "coefficient of "
                                      "restitution"), res.warnings)

    def test_the_joint_screw_split_copies_the_new_cells(self):
        """R11e: the *CONSTRAINED_JOINT_SCREW split of the SSID = 0
        /INTER/TYPE25 copies Iedge (K-10, --general-shell-edges), Tstart /
        Tstop (K-11) and Ishape (K-16) from its parent - the B2 mini screw
        deck, its contact turned into an AUTOMATIC_GENERAL with BT 1e-4, DT
        0.05 and Card E SRNDE 1."""
        deck = _t7._screw_deck()
        old = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 5, 0) + "\n"
               + _row(0.1, 0.0, 0.0, 0.0) + "\n\n")
        self.assertEqual(deck.count(old), 1)
        new = ("*CONTACT_AUTOMATIC_GENERAL\n" + _row(0, 0, 5, 0) + "\n"
               + _row(0.1, 0.0, 0.0, 0.0, 0.0, 0, 1.0e-4, 0.05) + "\n"
               + _row() + "\n" + _cards_ae(srnde=1))
        res, s, _e = _convert(deck.replace(old, new),
                              general_shell_edges=True)
        ids = _type25_ids_by_title(s)
        split = [t for t in ids if t.endswith("_screw_9_body_A")]
        self.assertEqual(len(split), 1, ids)
        parent = [t for t in ids if t not in split]
        self.assertEqual(len(parent), 1, ids)
        for title in parent + split:
            iid = ids[title]
            with self.subTest(title=title):
                self.assertEqual(_type25_card1(s, iid)[7], "1")      # Iedge
                self.assertEqual(tuple(float(v) for v in
                                       _t_cells(s, "TYPE25", iid)),
                                 (1.0e-4, 0.05))
                self.assertEqual(_ishape(s, iid), "2")
        self.assertTrue(_has(res.warnings, "is split out"), res.warnings)


class SingleSurfaceSstGapReviewPins(unittest.TestCase):
    """K-12: the |SST| rule's guards the review's mutants showed unpinned."""

    def test_a_thick_shell_counts_as_a_solid(self):
        """R12a: a set of shells and thick shells mixes the two kinds the
        |SST| rule refuses - a thick shell is a /BRICK, which a shell meets
        at |SST|/2."""
        tsh = ("*ELEMENT_TSHELL\n" + "".join(
            f"{v:>8}" for v in (201, 103, 1, 2, 5, 4, 10, 11, 14, 13)) + "\n"
            + "*PART\ntshell\n" + _row(103, 3, 1) + "\n"
            + "*SECTION_TSHELL\n" + _row(3, 1, 0.8333, 2) + "\n")
        deck = _k1a_deck(_k1a_ass(7, 1, 2, card3=(0, 0, 0.35)), extra=tsh)
        old_set = "*SET_PART_LIST\n" + _row(1) + "\n" + _row(101, 102) + "\n"
        self.assertEqual(deck.count(old_set), 1)
        deck = deck.replace(old_set, "*SET_PART_LIST\n" + _row(1) + "\n"
                            + _row(101, 102, 103) + "\n")
        res, s, _e = _convert(deck)
        self.assertEqual(_type7(s, 7)["gapmin"], 0.175)
        self.assertTrue(_has(res.warnings, "CONTACT 7:", "mixes shells and "
                             "solids", "refused"), res.warnings)

    def test_a_solid_only_set_keeps_the_old_value_without_a_refusal(self):
        """R12b: no shell in the set - the |SST| rule has nothing to act
        on: the old (|SST| + |MST|)/2 stands and no refusal is printed."""
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 2, 2,
                                                 card3=(0, 0, 0.35))))
        self.assertEqual(_type7(s, 7)["gapmin"], 0.175)
        self.assertFalse(_has(res.warnings, "mixes shells and solids"),
                         res.warnings)
        self.assertFalse(_has(res.warnings, "|SST|/2 + |SST|/2"),
                         res.warnings)

    def test_soft_7_with_a_gapmin_at_the_thickness_says_nothing(self):
        """R12c: SST below t but an MST that lifts the written Gapmin to t
        or more - the floor acts, no OPTT warning."""
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            31, 1, 2, card3=(0, 0, 0.1, 1.0),
            kw="CONTACT_AUTOMATIC_GENERAL_ID", tail=_row(-7) + "\n")))
        self.assertEqual(_type7(s, 31)["gapmin"], 0.55)
        self.assertFalse(_has(res.warnings, "*PART_CONTACT OPTT"),
                         res.warnings)

    def test_soft_7_without_sst_says_nothing(self):
        """R12d: no Card-3 SST - no 'OPTT 0' advice."""
        res, s, _e = _convert(_soft_deck(-7))
        self.assertIn("/INTER/TYPE7/101", s)
        self.assertFalse(_has(res.warnings, "*PART_CONTACT OPTT"),
                         res.warnings)
        self.assertFalse(_has(res.warnings, "below the shell thickness"),
                         res.warnings)

    def test_a_two_surface_soft_11_or_19_card_keeps_the_old_formula(self):
        """R12e: the |SST| rule is the self-mirrored cards'; a two-surface
        SOFT -11 / -19 card (the cards against the block) keeps (|SST| +
        |MST|)/2."""
        for soft, gap in ((-11, _gap11), (-19, _gap19)):
            with self.subTest(soft=soft):
                res, s, _e = _convert(_k1a_deck(_k1a_s2s(
                    32, card3=(0, 0, 0.35), kw="CONTACT_AUTOMATIC_GENERAL_ID",
                    tail=_row(soft) + "\n")))
                self.assertEqual(gap(s, 32), 0.175)
                self.assertFalse(_has(res.warnings, "|SST|/2 + |SST|/2"),
                                 res.warnings)

    def test_a_two_surface_soft_7_card_gets_no_optt_warning(self):
        """R12f: the OPTT warning belongs to the single-surface rule."""
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            31, card3=(0, 0, 0.2), kw="CONTACT_AUTOMATIC_GENERAL_ID",
            tail=_row(-7) + "\n")))
        self.assertIn("/INTER/TYPE7/31", s)
        self.assertFalse(_has(res.warnings, "*PART_CONTACT OPTT"),
                         res.warnings)


class SrndeIshapeReviewPins(unittest.TestCase):
    """K-16: the SRNDE rules the review's mutants showed unpinned."""

    def test_soft_2_depth_33_and_35_take_precedence_too(self):
        """R16a: DEPTH 33 and 35 are flush depths as well (Vol I R17
        p.11-117: 'for DEPTH = 23, 33, 35, and 55, SRNDE is ignored')."""
        for depth in (33, 35):
            with self.subTest(depth=depth):
                res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(
                    srnde=1, card_a=(2, 0, 0, 0, 0, depth)))))
                self.assertEqual(_ishape(s, 21), "0")
                self.assertTrue(_has(res.warnings, "21: Card E SRNDE 1 is not "
                                     "used", f"DEPTH {depth}"), res.warnings)

    def test_shledg_2_is_named_on_shells(self):
        """R16b: SOFT 2 with SHLEDG 2 names the rounded, extended edges."""
        res, s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(
            shledg=2, card_a=(2,)))))
        self.assertEqual(_ishape(s, 21), "0")
        self.assertTrue(_has(res.warnings, "21: SHLEDG 2 rounds the shell "
                             "edges"), res.warnings)

    def test_a_mortar_card_on_a_type7_route_names_no_srnde(self):
        """R16c: a Mortar card reads no Card E (Table 11-1, p.11-135)."""
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, kw="CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID",
            tail=_cards_ae(srnde=1))))
        self.assertIn("/INTER/TYPE7/7", s)
        self.assertFalse(_has(res.warnings, "Card E SRNDE"), res.warnings)

    def test_the_node_to_surface_reach_note_reads_the_main_side(self):
        """R16f: on the explicit node-to-surface TYPE25 the shells that
        count for the reach note are the MAIN side's - the cards (shells)
        as the main side get it, the block (solids) does not."""
        top = "*SET_NODE_LIST\n" + _row(6) + "\n" + _row(*range(10, 18)) \
            + "\n" + _row(18) + "\n"
        n2s = "CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID"
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            16, ssid=6, msid=1, sstyp=4, mstyp=2, kw=n2s), extra=top))
        self.assertIn("/INTER/TYPE25/16", s)
        self.assertTrue(_has(res.warnings, "16:", _REACH), res.warnings)
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            16, ssid=5, msid=1, sstyp=4, mstyp=3, kw=n2s),
            extra=_card_nset()))
        self.assertIn("/INTER/TYPE25/16", s)
        self.assertFalse(_has(res.warnings, "16:", _REACH), res.warnings)


class Soft2EdgeGateReviewPins(unittest.TestCase):
    """K-10: every edge depth of the SOFT 2 Iedge 22 gate."""

    def test_every_edge_depth_opens_the_gate(self):
        """R10a: DEPTH 15, 35 and 45 check edge-to-edge penetration too
        (Vol I R17 p.11-97), so they write Iedge 22 like 5 / 25 / 55."""
        for depth in (15, 35, 45):
            with self.subTest(depth=depth):
                _r, s, _e = _convert(_k1a_deck(_eroding_s2s(
                    card_a=(2, 0, 0, 0, 0, depth))))
                c1 = _type25_card1(s, 51)
                self.assertEqual((c1[2], c1[7]), ("2", "22"))


class GeneralShellEdgesReviewPins(unittest.TestCase):
    """K-10: the 'does not reach' line is for AUTOMATIC_GENERAL cards."""

    def test_an_ordinary_single_surface_card_is_not_told_the_flag_misses_it(
            self):
        """R10c: --general-shell-edges says nothing to an ordinary
        AUTOMATIC_SINGLE_SURFACE card, on either TYPE7 route."""
        for name, deck in (
                ("SSID != 0", _k1a_deck(_k1a_ass(7, 1, 2))),
                ("implicit SSID = 0", _k1a_deck(_k1a_ass(21, 0, 0),
                                                implicit=True))):
            with self.subTest(name):
                res, s, _e = _convert(deck, general_shell_edges=True)
                self.assertIn("/INTER/TYPE7/", s)
                self.assertFalse(_has(res.warnings, "--general-shell-edges"),
                                 res.warnings)


class DroppedSoftCardFieldsReviewPins(unittest.TestCase):
    """K-09: the cells and routes the review's mutants showed unpinned."""

    def test_sbopt_2_is_soft_2s_default(self):
        """R09a: SBOPT 2 is the default under SOFT 2 (p.11-90) - the SOFT 2
        line does not name it."""
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, tail=_cards_ac((2, 0, 0, 0, 2)))))
        ws = _soft_field_lines(res, 7)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("SOFT 2", ws[0])
        self.assertNotIn("SBOPT", ws[0])

    def test_any_other_soft_value_is_named(self):
        """R09b: a SOFT that is not 0 / 1 / 2 is named by its value."""
        for soft in (4, 6):
            with self.subTest(soft=soft):
                res, _s, _e = _convert(_k1a_deck(_k1a_ass(
                    7, 1, 2, tail=_cards_ac((soft,)))))
                ws = _soft_field_lines(res, 7)
                self.assertEqual(len(ws), 1, res.warnings)
                self.assertIn(f"SOFT {soft}", ws[0])

    def test_the_implicit_ssid_0_route_names_them(self):
        """R09f: the implicit all-parts /INTER/TYPE7 route prints the line."""
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            21, 0, 0, tail=_cards_ac((1, 0.2))), implicit=True))
        self.assertIn("/INTER/TYPE7/21", s)
        ws = _soft_field_lines(res, 21)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("SOFT 1", ws[0])
        self.assertIn("/INTER/TYPE7 has no mass / time-step stiffness", ws[0])

    def test_the_s2s_type25_route_names_them(self):
        """R09g: --s2s-type25 prints the line with the TYPE25 reason."""
        res, s, _e = _convert(_k1a_deck(_k1a_s2s(
            12, tail=_cards_ac((1, 0.2)))), s2s_type25=True)
        self.assertIn("/INTER/TYPE25/12", s)
        ws = _soft_field_lines(res, 12)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("SOFT 1", ws[0])
        self.assertIn("IPSTIF, STFAC_MDT and DTSTIF", ws[0])


class AutoGapminSingleEdgeReviewPin(unittest.TestCase):
    """K-05: --auto-gapmin's skip line for a *CONTACT_SINGLE_EDGE."""

    def test_a_single_edge_card_has_no_soft_value_in_the_skip_line(self):
        """R05a: the card files a soft = -11 record, but its own spelling
        has no SOFT, so the skip line names none."""
        deck = _k1a_deck("*CONTACT_SINGLE_EDGE_ID\n" + f"{101:>10}edges\n"
                         + _row(1, 0, 2, 0) + "\n" + _row() + "\n" + _row()
                         + "\n")
        res, _s, _e = _convert(deck, auto_gapmin=True)
        ws = [w for w in res.warnings if w.startswith("--auto-gapmin INTER 101")]
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("*CONTACT_SINGLE_EDGE -> /INTER/TYPE11", ws[0])
        self.assertNotIn("SOFT =", ws[0])


class RoutedN2sCardE(unittest.TestCase):
    """K-16 (review major): the routed implicit node-to-surface
    /INTER/TYPE7 (round 9, A2) left the TYPE25 path before
    _type25_ishape, so a stated Card E SRNDE vanished without a line - the
    other /INTER/TYPE7 routes name it."""

    _N2S = "CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID"

    def _deck(self, tail: str = "") -> str:
        return _k1a_deck(_k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3,
                                  kw=self._N2S, tail=tail),
                         implicit=True, extra=_card_nset())

    def test_srnde_on_the_routed_type7_is_named(self):
        res, s, _e = _convert(self._deck(_cards_ae(srnde=1)))
        self.assertIn("/INTER/TYPE7/16", s)
        self.assertNotIn("/INTER/TYPE25/16", s)
        self.assertTrue(_has(res.warnings, "16: Card E SRNDE 1 is not "
                             "converted", "/INTER/TYPE7"), res.warnings)

    def test_the_bytes_do_not_move(self):
        _r, s0, e0 = _convert(self._deck())
        _r, s1, e1 = _convert(self._deck(_cards_ae(srnde=1)))
        self.assertEqual((s0, e0), (s1, e1))

    def test_no_srnde_says_nothing(self):
        res, _s, _e = _convert(self._deck(_cards_ae(srnde=0)))
        self.assertFalse(_has(res.warnings, "Card E SRNDE"), res.warnings)


#: (name, contact, convert kwargs, kind, id) of the routes that wrote the raw
#: Card-2 DT before CardStack K-11 (``tstop = 0 if DT >= 1e19 else DT``)
def _raw_dt_routes(card2):
    eroding = "CONTACT_ERODING_SURFACE_TO_SURFACE_ID"
    n2s = "CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID"
    return (
        ("ERODING S2S", _k1a_deck(_k1a_s2s(
            51, card2=card2, kw=eroding, tail=_row(0, 1, 1) + "\n")), {},
         "TYPE25", 51),
        ("explicit N2S", _k1a_deck(_k1a_s2s(
            16, ssid=5, msid=1, sstyp=4, mstyp=3, card2=card2, kw=n2s),
            extra=_card_nset()), {}, "TYPE25", 16),
        ("routed implicit N2S", _k1a_deck(_k1a_s2s(
            16, ssid=5, msid=1, sstyp=4, mstyp=3, card2=card2, kw=n2s),
            implicit=True, extra=_card_nset()), {}, "TYPE7", 16),
        ("--s2s-type25", _k1a_deck(_k1a_s2s(12, card2=card2)),
         {"s2s_type25": True}, "TYPE25", 12),
    )


class LateDeathOnTheRawDtRoutes(unittest.TestCase):
    """K-11 (review major): the eroding / node-to-surface TYPE25 family,
    the routed implicit node-to-surface TYPE7 and --s2s-type25 wrote a
    stated DT as it stood before K-11; a DT at / past ENDTIM (below 1e19)
    now writes Tstop 0, so the cell moves - five R14 decks (DT 1e14 / 1e17)
    did so with no line. It is named now. The starter reads a Tstop of 0 as
    1e30 (hm_read_inter_type25.F:579, hm_read_inter_type07.F:544): the
    contact acts to the end of the run either way."""

    def test_the_moved_cell_is_named(self):
        # "1.0E+14" as the R14 decks write it: f"{1e14:>10}" would print
        # 100000000000000.0, which overflows the 10-column cell
        for name, deck, kw, kind, iid in _raw_dt_routes(_card2(0.0,
                                                               "1.0E+14")):
            with self.subTest(name):
                res, s, _e = _convert(_endtim(deck), **kw)
                self.assertEqual(_t_cells(s, kind, iid), ("0", "0"))
                ws = [w for w in res.warnings
                      if f" {iid}: Card-2 DT 1e+14 is at or past ENDTIM" in w]
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in (f"/INTER/{kind}/{iid} Tstop 0 (never",
                               "1e30", "to the end of the run"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
                self.assertIn("hm_read_inter_type25.F:579" if kind == "TYPE25"
                              else "hm_read_inter_type07.F:544", ws[0])

    def test_a_route_that_dropped_dt_keeps_its_silence(self):
        """The other routes wrote Tstop 0 for any DT before K-11: the same
        cell now, so nothing is said."""
        res, s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
            7, 1, 2, card2=_card2(0.0, "1.0E+14")))))
        self.assertEqual(_t_cells(s, "TYPE7", 7), ("0", "0"))
        self.assertFalse(_has(res.warnings, " 7: Card-2"), res.warnings)

    def test_far_or_blank_deaths_say_nothing_there_either(self):
        for dt in (1.0e20, "", 0.0):
            for name, deck, kw, kind, iid in _raw_dt_routes(_card2(0.0, dt)):
                with self.subTest(name, dt=dt):
                    res, s, _e = _convert(_endtim(deck), **kw)
                    self.assertEqual(_t_cells(s, kind, iid), ("0", "0"))
                    self.assertFalse(_has(res.warnings, f" {iid}: Card-2"),
                                     res.warnings)

    def test_the_docstring_names_the_raw_dt_routes(self):
        from k2rad.writer import contacts
        doc = _collapse(contacts._birth_death.__doc__)
        self.assertNotIn("says nothing - today's bytes", doc)
        self.assertIn("dt_was_written", doc)


class DbExtentBinaryMaxintNamed(unittest.TestCase):
    """The MAXINT hand-over (review major): nine R14 engine decks gained
    /ANIM/SHELL/TENS/STRESS/ALL with no log line. The handler now names
    what a stated MAXINT reaches; a negative MAXINT - |MAXINT| points at
    every in-plane point, no averaging (Vol I R17 p.16-67) - is named as
    not reaching K-42's MAXINT > 3 rule."""

    _ALL = "/ANIM/SHELL/TENS/STRESS/ALL"

    @staticmethod
    def _ext(*cells) -> str:
        return "*DATABASE_EXTENT_BINARY\n" + _row(*cells) + "\n"

    def test_maxint_above_3_is_named_with_what_it_writes(self):
        for cell in (4, 5, 8):
            with self.subTest(maxint=cell):
                res, _s, eng = _convert(_deck(extra=self._ext(0, 0, cell)))
                self.assertIn(self._ALL, eng.splitlines())
                self.assertTrue(_has(res.warnings, "*DATABASE_EXTENT_BINARY",
                                     f"MAXINT {cell}", self._ALL,
                                     "p.16-67"), res.warnings)

    def test_a_negative_maxint_below_minus_3_is_named_as_not_reached(self):
        res, _s, eng = _convert(_deck(extra=self._ext(0, 0, -5)))
        self.assertNotIn(self._ALL, eng)
        self.assertTrue(_has(res.warnings, "*DATABASE_EXTENT_BINARY",
                             "MAXINT -5", "no averaging", "not written"),
                        res.warnings)

    def test_maxint_3_or_blank_or_minus_3_say_nothing(self):
        for cell in ("", 3, 2, 0, -3):
            with self.subTest(maxint=cell):
                res, _s, _e = _convert(_deck(extra=self._ext(0, 0, cell)))
                self.assertFalse(_has(res.warnings, "MAXINT"), res.warnings)


class Inacti5Wording(unittest.TestCase):
    """K-14 (review minor): the IGNORE 3 / 4, negative-IGNORE and mortar
    texts said Inacti 5 'keeps each initial overlap as the zero-force state
    for the whole run'. The engine relaxes the stored overlap toward a
    smaller current penetration each cycle (i7for3.F:725-726) and drops it
    when the pair leaves the gap (i7dst3.F:428-433): the overlap only
    shrinks, nothing closes it on a schedule."""

    _MORTAR = "CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID"

    def _check(self, text: str):
        self.assertNotIn("for the whole run", text)
        for needle in ("zero-force state", "only shrinks",
                       "i7for3.F:725-726", "i7dst3.F:428-433"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_ignore_lines(self):
        for ignore in (3, 4, -2):
            with self.subTest(ignore=ignore):
                res, _s, _e = _convert(_k1a_deck(_k1a_ass(
                    7, 1, 2, kw=self._MORTAR, tail=_ignore_tail(ignore))))
                w = [x for x in res.warnings
                     if x.startswith(f"CONTACT 7: ignore={ignore}")]
                self.assertEqual(len(w), 1, res.warnings)
                self._check(w[0])

    def test_the_mortar_note(self):
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        self._check(_collapse(_CONTACT_SPELLING_NOTES["mortar"]))


class SrndeReviewMinors(unittest.TestCase):
    """K-16 (review minors): SRNDE acts on exterior SHELL edges (Vol I R17
    p.11-114/116), so on a surface with no shell it has nothing to act on
    and the cell stays 0; the SHLEDG 2 note no longer promises an Ishape 2
    that SHLEDG's precedence rules out (p.11-117)."""

    def test_srnde_1_without_a_shell_keeps_ishape_0_and_says_why(self):
        res, s, _e = _convert(_without_shells(_k1a_deck(_k1a_ass(
            21, 0, 0, tail=_cards_ae(srnde=1)))))
        self.assertEqual(_ishape(s, 21), "0")
        self.assertTrue(_has(res.warnings, "21: Card E SRNDE 1", "no shell",
                             "Ishape 0"), res.warnings)
        self.assertFalse(_has(res.warnings, "21:", "-> /INTER/TYPE25/21 "
                              "Ishape 2"), res.warnings)
        _r, s0, e0 = _convert(_without_shells(_k1a_deck(_k1a_ass(21, 0, 0))))
        _r, s1, e1 = _convert(_without_shells(_k1a_deck(_k1a_ass(
            21, 0, 0, tail=_cards_ae(srnde=1)))))
        self.assertEqual((s0, e0), (s1, e1))

    def test_the_shledg_2_note_keeps_to_its_own_rule(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(
            shledg=2, card_a=(2,)))))
        ws = [w for w in res.warnings if "21: SHLEDG 2" in w]
        self.assertEqual(len(ws), 1, res.warnings)
        for needle in ("p.11-112", _REACH, "t_s/2", "Ishape 0",
                       "SHLEDG takes precedence over Card E SRNDE"):
            with self.subTest(needle=needle):
                self.assertIn(needle, ws[0])
        self.assertNotIn("writes Ishape 2", ws[0])
        self.assertNotIn("SRNDE 0:", ws[0])


class DepthOnlyLine(unittest.TestCase):
    """K-09 (review minor): a line that names only a search DEPTH got the
    stiffness reason and the SFS lever; a negative DEPTH is the id of a
    curve of search depth over time (Vol I R17 p.11-91 LT.0)."""

    def test_a_depth_only_line_says_why_depth_is_lost(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, tail=_cards_ac((0, 0, 0, 0, 0, 5)))))
        ws = _soft_field_lines(res, 7)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("DEPTH 5 (the search depth, in segments", ws[0])
        self.assertIn("no search-depth cell", ws[0])
        for absent in ("SFS > 1", "stiffness"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, ws[0])

    def test_a_negative_depth_is_named_as_a_curve(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, tail=_cards_ac((0, 0, 0, 0, 0, -12)))))
        ws = _soft_field_lines(res, 7)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("DEPTH -12 (|DEPTH| = 12 is the curve of the search "
                      "depth over time", ws[0])
        self.assertIn("p.11-91", ws[0])

    def test_depth_beside_a_stiffness_cell_keeps_the_stiffness_reason(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(
            7, 1, 2, tail=_cards_ac((1, 0.2, 0, 0, 0, 5)))))
        ws = _soft_field_lines(res, 7)
        self.assertEqual(len(ws), 1, res.warnings)
        self.assertIn("SOFT 1", ws[0])
        self.assertIn("DEPTH 5", ws[0])
        self.assertIn("Card-3 SFS > 1", ws[0])


def _icor_tail(icor=1, card_a=()) -> str:
    """Cards A (*card_a*) to E with ICOR *icor* (Card E field 6)."""
    return _cards_ae(icor=icor, card_a=card_a)


class IcorOnTheOtherRoutes(unittest.TestCase):
    """Card E ICOR != 0 makes Card-2 VDC a coefficient of restitution in
    percent (Vol I R17 p.11-115) - under SOFT 0 / 1 on the AUTOMATIC
    NODES_TO_SURFACE / SURFACE_TO_SURFACE / SINGLE_SURFACE spellings only,
    under SOFT 2 on every contact. The routes that map VDC to a VisS / VISs
    damping cell (every /INTER/TYPE7 route, the eroding / node-to-surface
    TYPE25 family, --s2s-type25) used to say nothing of it (review minor).
    Named, not converted: no byte moves."""

    def test_the_type7_routes_name_it(self):
        n2s = _k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3,
                       card2=_card2(vdc=20.0),
                       kw="CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID",
                       tail=_icor_tail())
        for name, deck, kw, iid in (
                ("ASS SSID != 0", _k1a_deck(_k1a_ass(
                    7, 1, 2, card2=_card2(vdc=20.0), tail=_icor_tail())), {},
                 7),
                ("S2S", _k1a_deck(_k1a_s2s(12, card2=_card2(vdc=20.0),
                                           tail=_icor_tail())), {}, 12),
                ("routed implicit N2S", _k1a_deck(
                    n2s, implicit=True, extra=_card_nset()), {}, 16)):
            with self.subTest(name):
                res, s, _e = _convert(deck, **kw)
                self.assertIn(f"/INTER/TYPE7/{iid}", s)
                self.assertTrue(_has(res.warnings, f" {iid}: Card E ICOR 1",
                                     "coefficient of restitution",
                                     "p.11-115", "VisS 0.2"), res.warnings)

    def test_the_type25_damping_routes_name_it(self):
        n2s = _k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3,
                       card2=_card2(vdc=20.0),
                       kw="CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID",
                       tail=_icor_tail())
        for name, deck, kw, iid in (
                ("--s2s-type25", _k1a_deck(_k1a_s2s(
                    12, card2=_card2(vdc=20.0), tail=_icor_tail())),
                 {"s2s_type25": True}, 12),
                ("explicit N2S", _k1a_deck(n2s, extra=_card_nset()), {}, 16)):
            with self.subTest(name):
                res, s, _e = _convert(deck, **kw)
                self.assertIn(f"/INTER/TYPE25/{iid}", s)
                self.assertTrue(_has(res.warnings, f" {iid}: Card E ICOR 1",
                                     "coefficient of restitution",
                                     "VISs 0.2"), res.warnings)

    def test_the_bytes_do_not_move(self):
        for contact in (_k1a_ass(7, 1, 2, card2=_card2(vdc=20.0)),
                        _k1a_s2s(12, card2=_card2(vdc=20.0))):
            with self.subTest(contact=contact.splitlines()[0]):
                _r, s0, e0 = _convert(_k1a_deck(contact + _icor_tail(0)))
                _r, s1, e1 = _convert(_k1a_deck(contact + _icor_tail(1)))
                self.assertEqual((s0, e0), (s1, e1))

    def test_no_vdc_or_a_spelling_icor_does_not_reach_says_nothing(self):
        for name, contact in (
                ("VDC 0", _k1a_ass(7, 1, 2, tail=_icor_tail())),
                ("AUTOMATIC_GENERAL SOFT 0", _k1a_ass(
                    7, 1, 2, card2=_card2(vdc=20.0),
                    kw="CONTACT_AUTOMATIC_GENERAL_ID", tail=_icor_tail()))):
            with self.subTest(name):
                res, _s, _e = _convert(_k1a_deck(contact))
                self.assertFalse(_has(res.warnings, "coefficient of "
                                      "restitution"), res.warnings)

    def test_the_type25_self_route_follows_the_same_rule(self):
        """An AUTOMATIC_GENERAL card under SOFT 0 is not one ICOR acts on:
        its VDC is the plain viscous damping, named as such."""
        res, s, _e = _convert(_k1a_deck(_k1a_ass(
            41, 0, 0, card2=_card2(vdc=20.0),
            kw="CONTACT_AUTOMATIC_GENERAL_ID", tail=_icor_tail())))
        self.assertIn("/INTER/TYPE25/41", s)
        self.assertTrue(_has(res.warnings, "41: Card-2 VDC 20", "not "
                             "written"), res.warnings)
        self.assertFalse(_has(res.warnings, "coefficient of restitution"),
                         res.warnings)


class SingleSurfaceSstZeroMst(unittest.TestCase):
    """K-12 (review minor): a single-surface shell set with SST 0 and MST
    != 0 keeps the old (|SST| + |MST|)/2 - from MST, which a single-surface
    contact does not use (no SURFB, Vol I R17 p.11-33) - and now says so."""

    def test_mst_alone_is_named(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                 card3=(0, 0, 0, 0.3))))
        self.assertEqual(_type7(s, 7)["gapmin"], 0.15)
        self.assertTrue(_has(res.warnings, "CONTACT 7:", "MST 0.3 is not "
                             "used", "no SURFB", "SST 0"), res.warnings)

    def test_no_sst_and_no_mst_says_nothing(self):
        res, _s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2)))
        self.assertFalse(_has(res.warnings, "CONTACT 7:", "is not used"),
                         res.warnings)

    def test_the_opt_out_keeps_the_old_text(self):
        res, s, _e = _convert(_k1a_deck(_k1a_ass(7, 1, 2,
                                                 card3=(0, 0, 0, 0.3))),
                              single_surface_sst_gap=False)
        self.assertEqual(_type7(s, 7)["gapmin"], 0.15)
        self.assertFalse(_has(res.warnings, "MST 0.3 is not used"),
                         res.warnings)


class GeneralShellEdgesBeamCount(unittest.TestCase):
    """K-10 (review minor): the beam sentence counted every *ELEMENT_BEAM,
    spot-weld (ELFORM 9) beams too - which AUTOMATIC_GENERAL leaves out
    unless Card E CPARM8 is 2 (Vol I R17 p.11-114) - so they are counted
    apart now; and one beam 'takes' no part."""

    _TRUSS = ("*ELEMENT_BEAM\n" + "".join(f"{v:>8}" for v in (301, 103, 19,
                                                               20)) + "\n"
              + "*PART\ntruss\n" + _row(103, 3, 3) + "\n"
              + "*SECTION_BEAM\n" + _row(3, 3) + "\n" + _row(1.0) + "\n"
              + "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n")
    _WELD = ("*ELEMENT_BEAM\n" + "".join(f"{v:>8}" for v in (401, 104, 21,
                                                              30)) + "\n"
             + "*PART\nweld\n" + _row(104, 4, 4) + "\n"
             + "*SECTION_BEAM\n" + _row(4, 9) + "\n"
             + _row(1.0, 1.0, 0.0, 0.0) + "\n"
             + "*MAT_SPOTWELD\n"
             + _row(4, 7.85e-9, 210000.0, 0.3, 300.0, 0.0, 0.0, 0.0) + "\n"
             + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")

    def _line(self, extra: str) -> str:
        res, s, _e = _convert(_k1a_deck(_general0(), extra=extra),
                              general_shell_edges=True)
        self.assertEqual(_type25_card1(s, 41)[7], "1")
        ws = [w for w in res.warnings
              if "--general-shell-edges -> /INTER/TYPE25/41 Iedge 1" in w]
        self.assertEqual(len(ws), 1, res.warnings)
        return ws[0]

    def test_one_beam_takes_no_part(self):
        w = self._line(self._TRUSS)
        self.assertIn("1 beam element (*ELEMENT_BEAM) takes no part", w)
        self.assertNotIn("spot-weld", w)

    def test_a_spot_weld_beam_is_no_beam_to_beam_loss(self):
        w = self._line(self._WELD)
        self.assertNotIn("beam-to-beam contact is not converted", w)
        for needle in ("spot-weld beam (*SECTION_BEAM ELFORM 9)",
                       "CPARM8 is 2", "p.11-114"):
            with self.subTest(needle=needle):
                self.assertIn(needle, w)

    def test_both_kinds_are_counted_apart(self):
        w = self._line(self._TRUSS + self._WELD)
        self.assertIn("1 beam element (*ELEMENT_BEAM) takes no part", w)
        self.assertIn("beam-to-beam contact is not converted", w)
        self.assertIn("spot-weld beam (*SECTION_BEAM ELFORM 9)", w)


# ═════════════════════════════════════════════════════════════════════════════
# The opt-out flags of the user's decision 8 (2026-11-01, wave D): K-11
# (--no-contact-birth-death), K-10's SOFT 2 Iedge gate
# (--no-soft2-iedge-gate) and K-16 (--no-srnde-ishape); the MAXINT one
# (--no-maxint-stress-all) is pinned in tests/test_cardstack_pipeline_engine.py
# beside the K-42 rule it gates. Each flag restores the cells its route
# wrote before the item, and one line names it where it moves a byte. The
# parser / convert() / ConvertOptions / cli.main() / GUI wiring of the four is
# the _BOOL_LEVERS and _GUI_LEVER_VARS tables above.
# ═════════════════════════════════════════════════════════════════════════════

#: the _k11_routes / _raw_dt_routes names whose route wrote the raw Card-2
#: BT / DT before K-11 (dt_was_written); the other seven dropped them
_RAW_DT_NAMES = frozenset({"S2S --s2s-type25", "--s2s-type25", "ERODING S2S",
                           "explicit N2S", "routed implicit N2S"})

#: K-11's own line (the opt-out does not print it)
_K11_LINE = "(Vol I R17 p.11-29/30: the interface acts between them)"

#: the raw-route opt-out line's sentence for a DT of -9999 (Remark 2)
_CURVE_AS_TIME = ("DT = -9999 makes BT the id of a curve of birth / death "
                  "pairs (Remark 2), written here as a time")


def _data_line(starter: str, header: str, row: int) -> int:
    """The line index of data row *row* of the block *header* (the title
    line and the '#' rows skipped, as _inter_rows counts them)."""
    lines = starter.splitlines()
    i = lines.index(header)
    data = []
    for k in range(i + 2, len(lines)):
        if lines[k].startswith("/"):
            break
        if not lines[k].startswith("#"):
            data.append(k)
    return data[row]


def _differing_lines(a: str, b: str):
    la, lb = a.splitlines(), b.splitlines()
    assert len(la) == len(lb), (len(la), len(lb))
    return [k for k, (x, y) in enumerate(zip(la, lb)) if x != y]


def _opt_out_lines(res, flag: str):
    return [w for w in res.warnings if flag in w]


class ContactBirthDeathOptOut(unittest.TestCase):
    """--no-contact-birth-death (D-02): every K-11 route writes the cells it
    wrote before K-11. The single-surface, surface-to-surface and SOFT -7
    TYPE7, the SSID = 0 TYPE25 (and its joint-screw split) and the SOFT -11
    / -19 TYPE11 / TYPE19 dropped Card-2 BT / DT (Tstart 0 / Tstop 0); the
    eroding / node-to-surface TYPE25 family, the routed implicit
    node-to-surface TYPE7 and --s2s-type25 wrote BT and DT as stated, Tstop
    0 for a DT >= 1e19 (``tstop = 0 if DT >= 1e19 else DT``, the code at
    0562f3c's parent and the K1b before-snapshot). One line names the
    opt-out on each interface whose cells it moves."""

    _FLAG = "--no-contact-birth-death"

    def test_the_dropping_routes_write_the_bytes_of_no_bt_dt(self):
        plain = {n: (d, k) for n, d, k, _t, _i in _k11_routes((0.2, 0.2))}
        seen = 0
        for name, deck, kw, kind, iid in _k11_routes(_card2(0.001, 0.004)):
            if name in _RAW_DT_NAMES:
                continue
            seen += 1
            with self.subTest(name):
                res, s, e = _convert(_endtim(deck), contact_birth_death=False,
                                     **kw)
                self.assertEqual(_t_cells(s, kind, iid), ("0", "0"))
                d0, k0 = plain[name]
                _r, s0, e0 = _convert(_endtim(d0), **k0)
                self.assertEqual((s, e), (s0, e0))
                ws = _opt_out_lines(res, self._FLAG)
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in (f" {iid}: Card-2 BT 0.001 / DT 0.004",
                               f"/INTER/{kind}/{iid} keeps Tstart 0 / Tstop 0",
                               "active for the whole run",
                               "K-11 writes Tstart 0.001 / Tstop 0.004",
                               "p.11-29/30"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
                self.assertFalse(_has(res.warnings, _K11_LINE), res.warnings)
        self.assertEqual(seen, 7)

    def test_the_raw_routes_write_bt_and_dt_as_stated(self):
        plain = {n: (d, k) for n, d, k, _t, _i in _raw_dt_routes((0.2, 0.2))}
        for card2, raw, k11 in (
                (_card2(-0.001, 0.004), ("-0.001", "0.004"),
                 "K-11 writes Tstart 0 / Tstop 0.004"),
                (_card2(0.002, -0.004), ("0.002", "-0.004"),
                 "K-11 writes Tstart 0.002 / Tstop 0.004"),
                (_card2(0.0, "1.0E+14"), ("0", "1E+14"),
                 "K-11 writes Tstart 0 / Tstop 0"),
                (_card2(3, -9999), ("3", "-9999"),
                 "K-11 writes Tstart 0 / Tstop 0")):
            for name, deck, kw, kind, iid in _raw_dt_routes(card2):
                with self.subTest(name, bt=card2[6], dt=card2[7]):
                    res, s, e = _convert(_endtim(deck),
                                         contact_birth_death=False, **kw)
                    self.assertEqual(_t_cells(s, kind, iid), raw)
                    # nothing else moves: the deck without BT / DT, but the
                    # one Tstart / Tstop row
                    d0, k0 = plain[name]
                    _r, s0, e0 = _convert(_endtim(d0), **k0)
                    self.assertEqual(
                        _differing_lines(s, s0),
                        [_data_line(s, f"/INTER/{kind}/{iid}", _T_ROW[kind])])
                    self.assertEqual(e, e0)
                    ws = _opt_out_lines(res, self._FLAG)
                    self.assertEqual(len(ws), 1, res.warnings)
                    for needle in (f" {iid}: Card-2 BT", "as stated",
                                   "before CardStack K-11", k11):
                        with self.subTest(needle=needle):
                            self.assertIn(needle, ws[0])
                    # DT = -9999 is named as a curve id written as a time,
                    # on that row only (the wave-D review, mutant R03)
                    if card2[7] == -9999:
                        self.assertIn(_CURVE_AS_TIME, ws[0])
                    else:
                        self.assertNotIn(_CURVE_AS_TIME, ws[0])
                    self.assertFalse(_has(res.warnings, _K11_LINE))
                    self.assertFalse(_has(res.warnings, "pairs are LOST"))
                    self.assertFalse(_has(res.warnings,
                                          "is at or past ENDTIM"))

    def test_a_negative_raw_tstop_is_named_as_switching_the_contact_off(self):
        for name, deck, kw, kind, iid in _raw_dt_routes(_card2(0.002,
                                                               -0.004)):
            with self.subTest(name):
                res, _s, _e = _convert(_endtim(deck),
                                       contact_birth_death=False, **kw)
                ws = _opt_out_lines(res, self._FLAG)
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in ("Tstop -0.004 < 0", "from t 0",
                               "i7mainf.F:264-265" if kind == "TYPE7"
                               else "i25mainf.F:310-311"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
        res, _s, _e = _convert(_endtim(_raw_dt_routes(_card2(-0.001, 0.004))
                                       [0][1]), contact_birth_death=False)
        self.assertFalse(_has(res.warnings, "from t 0"), res.warnings)
        # a Tstop of 0 means never (the starter reads it as 1e30), not a
        # switch-off: BT < 0 with a blank DT prints the line with Tstop 0 on
        # every raw route, and it must not say the contact never acts (the
        # wave-D review, mutant R04: <= for <)
        for name, deck, kw, kind, iid in _raw_dt_routes(_card2(-0.001, "")):
            with self.subTest(name, tstop=0):
                res, s, _e = _convert(_endtim(deck),
                                      contact_birth_death=False, **kw)
                self.assertEqual(_t_cells(s, kind, iid), ("-0.001", "0"))
                ws = _opt_out_lines(res, self._FLAG)
                self.assertEqual(len(ws), 1, res.warnings)
                self.assertIn(f"/INTER/{kind}/{iid} Tstart -0.001 / Tstop 0 "
                              "as stated", ws[0])
                self.assertFalse(_has(res.warnings, "from t 0"), res.warnings)
                self.assertNotIn("never acts", ws[0])

    def test_where_the_cells_agree_nothing_moves_and_nothing_is_said(self):
        for card2 in ((0.2, 0.2), _card2(0.0, 1.0e20), _card2(0.001, 0.004)):
            for name, deck, kw, kind, iid in _raw_dt_routes(card2):
                with self.subTest(name, card2=card2):
                    res, s, e = _convert(_endtim(deck),
                                         contact_birth_death=False, **kw)
                    _r, s1, e1 = _convert(_endtim(deck), **kw)
                    self.assertEqual((s, e), (s1, e1))
                    self.assertFalse(_opt_out_lines(res, self._FLAG),
                                     res.warnings)
                    self.assertFalse(_has(res.warnings, _K11_LINE))
        for card2 in ((0.2, 0.2), _card2(0.0, 1.0e20), _card2(0.0, 0.02)):
            for name, deck, kw, kind, iid in _k11_routes(card2):
                if name in _RAW_DT_NAMES:
                    continue
                with self.subTest(name, card2=card2):
                    res, s, e = _convert(_endtim(deck),
                                         contact_birth_death=False, **kw)
                    _r, s1, e1 = _convert(_endtim(deck), **kw)
                    self.assertEqual((s, e), (s1, e1))
                    self.assertFalse(_opt_out_lines(res, self._FLAG),
                                     res.warnings)

    def test_a_dt_of_1e19_is_the_raw_routes_cut_off(self):
        """The raw routes wrote ``tstop = 0 if DT >= 1e19 else DT`` (d7652da
        contacts.py:4906): a DT of exactly 1e19 writes Tstop 0 under the
        flag, the cell K-11 writes too, so nothing moves and nothing is
        said (the wave-D review, mutant R01: > for >=)."""
        for name, deck, kw, kind, iid in _raw_dt_routes(_card2(0.0, 1.0e19)):
            with self.subTest(name):
                res, s, e = _convert(_endtim(deck),
                                     contact_birth_death=False, **kw)
                self.assertEqual(_t_cells(s, kind, iid), ("0", "0"))
                _r, s1, e1 = _convert(_endtim(deck), **kw)
                self.assertEqual((s, e), (s1, e1))
                self.assertFalse(_opt_out_lines(res, self._FLAG),
                                 res.warnings)

    def test_the_k11_texts_are_not_printed_under_the_flag(self):
        """DT = -9999 on a dropping route writes 0 / 0 both ways (no byte
        moves, so no opt-out line), and K-11's 'pairs are LOST' line - a
        K-11 conversion text - is not printed either."""
        res, s, _e = _convert(_endtim(_k1a_deck(_k1a_ass(
            7, 1, 2, card2=_card2(3, -9999)))), contact_birth_death=False)
        self.assertEqual(_t_cells(s, "TYPE7", 7), ("0", "0"))
        self.assertFalse(_has(res.warnings, "pairs are LOST"), res.warnings)
        self.assertFalse(_opt_out_lines(res, self._FLAG), res.warnings)

    def test_the_joint_screw_split_takes_the_parent_cells(self):
        """The *CONSTRAINED_JOINT_SCREW split copies the SSID = 0 TYPE25's
        Tstart / Tstop (R11e): under the flag both write 0 / 0."""
        deck = _t7._screw_deck()
        old = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 5, 0) + "\n"
               + _row(0.1, 0.0, 0.0, 0.0) + "\n\n")
        self.assertEqual(deck.count(old), 1)
        new = ("*CONTACT_AUTOMATIC_GENERAL\n" + _row(0, 0, 5, 0) + "\n"
               + _row(0.1, 0.0, 0.0, 0.0, 0.0, 0, 1.0e-4, 0.05) + "\n"
               + _row() + "\n")
        res, s, _e = _convert(deck.replace(old, new),
                              contact_birth_death=False)
        ids = _type25_ids_by_title(s)
        self.assertEqual(len(ids), 2, ids)
        for title, iid in ids.items():
            with self.subTest(title=title):
                self.assertEqual(_t_cells(s, "TYPE25", iid), ("0", "0"))
        _r, s1, _e = _convert(deck.replace(old, new))
        for title, iid in _type25_ids_by_title(s1).items():
            with self.subTest(default=title):
                self.assertEqual(tuple(float(v) for v in
                                       _t_cells(s1, "TYPE25", iid)),
                                 (1.0e-4, 0.05))
        self.assertEqual(len(_opt_out_lines(res, self._FLAG)), 1,
                         res.warnings)


def _n2s_soft(card_a=(2,)) -> str:
    """The explicit *CONTACT_AUTOMATIC_NODES_TO_SURFACE 16 (node set 5 on
    the block) with Card A *card_a* - the other family of the K-10 gate."""
    return _k1a_s2s(16, ssid=5, msid=1, sstyp=4, mstyp=3,
                    kw="CONTACT_AUTOMATIC_NODES_TO_SURFACE_ID",
                    tail=_row(*card_a) + "\n")


class Soft2IedgeGateOptOut(unittest.TestCase):
    """--no-soft2-iedge-gate (D-03): K-10 writes SOFT 2's Iedge 22 on the
    ERODING_SURFACE_TO_SURFACE / AUTOMATIC_NODES_TO_SURFACE TYPE25 only with
    Card A DEPTH 5 / 15 / 25 / 35 / 45 / 55 or SBOPT 1 (Vol I R17
    p.11-91/94/97); the flag writes 22 for every SOFT 2 card of that family,
    as the native reader does (dyna2rad convertcontacts.cxx:593-611) and as
    k2rad did before K-10."""

    _FLAG = "--no-soft2-iedge-gate"

    def test_the_flag_writes_iedge_22_where_the_gate_holds_it_back(self):
        blank = "neither (DEPTH blank = 2, SBOPT blank = 2)"
        for name, contact, extra, iid, gate in (
                ("ERODING S2S", _eroding_s2s(), "", 51, blank),
                ("AUTOMATIC N2S", _n2s_soft(), _card_nset(), 16, blank),
                ("ERODING S2S, DEPTH 3 / SBOPT 3",
                 _eroding_s2s(card_a=(2, 0, 0, 0, 3, 3)), "", 51,
                 "neither (DEPTH 3, SBOPT 3)")):
            with self.subTest(name):
                deck = _k1a_deck(contact, extra=extra)
                _r, s0, e0 = _convert(deck)
                self.assertEqual(_type25_card1(s0, iid)[7], "1000")
                res, s, e = _convert(deck, soft2_iedge_gate=False)
                c1 = _type25_card1(s, iid)
                self.assertEqual((c1[2], c1[7]), ("2", "22"))
                self.assertEqual(_differing_lines(s, s0),
                                 [_data_line(s, f"/INTER/TYPE25/{iid}", 0)])
                self.assertEqual(e, e0)
                ws = _opt_out_lines(res, self._FLAG)
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in ("SOFT=2", "Iedge=22",
                               "DEPTH 5/15/25/35/45/55 or SBOPT 1",
                               "convertcontacts.cxx:593-611",
                               "the default writes Iedge 1000", "IPSTIF=1"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
                # the card's own gate text: the flag opens no gate, so the
                # line never says SBOPT 1 (the wave-D review, mutants R20 /
                # R22)
                self.assertIn(f"and this card has {gate}, so the default "
                              "writes Iedge 1000", ws[0])
                self.assertNotIn("this card has SBOPT 1", ws[0])
                self.assertFalse(_has(res.warnings, "Iedge=1000 (no "
                                      "edge-to-edge contact)"), res.warnings)

    def test_where_the_gate_is_open_the_flag_moves_nothing(self):
        for card_a in ((2, 0, 0, 0, 0, 5), (2, 0, 0, 0, 0, 45),
                       (2, 0, 0, 0, 1, 0)):
            with self.subTest(card_a=card_a):
                deck = _k1a_deck(_eroding_s2s(card_a=card_a))
                r0, s0, e0 = _convert(deck)
                res, s, e = _convert(deck, soft2_iedge_gate=False)
                self.assertEqual(_type25_card1(s, 51)[7], "22")
                self.assertEqual((s, e, res.warnings), (s0, e0, r0.warnings))

    def test_the_other_soft_values_and_spellings_are_untouched(self):
        eroding_self = _k1a_ass(61, 1, 2,
                                kw="CONTACT_ERODING_SINGLE_SURFACE_ID",
                                tail=_row(0, 1, 1) + "\n" + _row(2) + "\n")
        for name, contact in (("SOFT 0", _eroding_s2s(card_a=(0,))),
                              ("SOFT 1", _eroding_s2s(card_a=(1,))),
                              ("ERODING_SINGLE_SURFACE SOFT 2", eroding_self)):
            with self.subTest(name):
                deck = _k1a_deck(contact)
                r0, s0, e0 = _convert(deck)
                res, s, e = _convert(deck, soft2_iedge_gate=False)
                self.assertEqual((s, e, res.warnings), (s0, e0, r0.warnings))
                self.assertFalse(_opt_out_lines(res, self._FLAG))


class SrndeIshapeOptOut(unittest.TestCase):
    """--no-srnde-ishape (D-04): K-16 writes a stated Card E SRNDE 1 as
    /INTER/TYPE25 Ishape 2 where the interface holds a shell; the flag keeps
    Ishape 0 (the square gap of the code before K-16) and names the dropped
    SRNDE in K-16's wording. The TYPE7 routes name SRNDE and never apply it,
    either way; their line and the SRNDE 0 reach note say what SRNDE 1
    writes on the TYPE25 routes, so under the flag they say Ishape 0."""

    _FLAG = "--no-srnde-ishape"

    @staticmethod
    def _emitters(srnde):
        eroding = "CONTACT_ERODING_SURFACE_TO_SURFACE_ID"
        return (
            ("SSID = 0 self", _k1a_ass(21, 0, 0, tail=_cards_ae(srnde=srnde)),
             {}, 21),
            ("ERODING S2S", _k1a_s2s(51, kw=eroding, tail=_row(0, 1, 1) + "\n"
                                     + _cards_ae(srnde=srnde)), {}, 51),
            ("--s2s-type25", _k1a_s2s(51, tail=_cards_ae(srnde=srnde)),
             {"s2s_type25": True}, 51))

    def test_the_flag_keeps_ishape_0_on_both_type25_emitters(self):
        plain = {n: c for n, c, _k, _i in self._emitters(0)}
        for name, contact, kw, iid in self._emitters(1):
            with self.subTest(name):
                _r, s1, _e = _convert(_k1a_deck(contact), **kw)
                self.assertEqual(_ishape(s1, iid), "2")
                res, s, e = _convert(_k1a_deck(contact), srnde_ishape=False,
                                     **kw)
                self.assertEqual(_ishape(s, iid), "0")
                _r0, s0, e0 = _convert(_k1a_deck(plain[name]), **kw)
                self.assertEqual((s, e), (s0, e0))
                ws = _opt_out_lines(res, self._FLAG)
                self.assertEqual(len(ws), 1, res.warnings)
                for needle in (f"{iid}: Card E SRNDE 1 is not converted",
                               f"/INTER/TYPE25/{iid} keeps Ishape 0 (square)",
                               "Ishape 2 (round)", "p.11-115/116 Remark 3"):
                    with self.subTest(needle=needle):
                        self.assertIn(needle, ws[0])
                self.assertFalse(_has(res.warnings, f"/INTER/TYPE25/{iid} "
                                      "Ishape 2: a round gap"), res.warnings)
                self.assertFalse(_has(res.warnings, f"{iid}:", _REACH),
                                 res.warnings)

    def test_where_srnde_1_writes_ishape_0_anyway_the_flag_moves_nothing(self):
        for name, deck in (
                ("SOFT 2 SHLEDG 1", _k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(
                    srnde=1, shledg=1, card_a=(2,))))),
                ("SOFT 2 DEPTH 23", _k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(
                    srnde=1, card_a=(2, 0, 0, 0, 0, 23))))),
                ("no shell", _without_shells(_k1a_deck(_k1a_ass(
                    21, 0, 0, tail=_cards_ae(srnde=1))))),
                ("Mortar", _k1a_deck(_k1a_ass(
                    21, 0, 0, kw="CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR_ID",
                    tail=_cards_ae(srnde=1))))):
            with self.subTest(name):
                r0, s0, e0 = _convert(deck)
                res, s, e = _convert(deck, srnde_ishape=False)
                self.assertEqual((s, e, res.warnings), (s0, e0, r0.warnings))
                self.assertFalse(_opt_out_lines(res, self._FLAG))
        # the TYPE7 route moves no byte either; its SRNDE line follows the
        # flag (test_the_srnde_notes_follow_the_flag)

    def _one_line_moves(self, deck, needle):
        """Convert *deck* both ways: the same bytes, and the same lines but
        the ONE line holding *needle* - returned as (default, flag)."""
        r0, s0, e0 = _convert(deck)
        res, s, e = _convert(deck, srnde_ishape=False)
        self.assertEqual((s, e), (s0, e0))
        w0 = [w for w in r0.warnings if needle in w]
        w1 = [w for w in res.warnings if needle in w]
        self.assertEqual((len(w0), len(w1)), (1, 1),
                         (r0.warnings, res.warnings))
        self.assertEqual([w for w in res.warnings if w not in w1],
                         [w for w in r0.warnings if w not in w0])
        # no SRNDE 1 lost an Ishape 2 here: no D-04 opt-out line
        self.assertFalse(_has(res.warnings,
                              "is not converted (--no-srnde-ishape)"))
        return w0[0], w1[0]

    def test_the_srnde_notes_follow_the_flag(self):
        """The SRNDE 0 reach note (a shell TYPE25) and the TYPE7 route's
        SRNDE line say what SRNDE 1 writes on the TYPE25 routes: Ishape 2 by
        default, Ishape 0 under the flag (the wave-D review: both said
        Ishape 2 either way). No byte moves."""
        d0, d1 = self._one_line_moves(
            _k1a_deck(_k1a_ass(21, 0, 0, tail=_cards_ae(srnde=0))), _REACH)
        self.assertIn("21: LS-DYNA's default free-edge treatment", d1)
        self.assertIn("SRNDE 1 - rounded, not extended - writes Ishape 2 "
                      "(round). No byte moves.", d0)
        self.assertNotIn(self._FLAG, d0)
        for needle in ("the card keeps Ishape 0 (= 1, a square gap there), "
                       "and under --no-srnde-ishape SRNDE 1 - rounded, not "
                       "extended - keeps Ishape 0 too (the default writes "
                       "it as Ishape 2, round). No byte moves.", _REACH):
            with self.subTest(needle=needle):
                self.assertIn(needle, d1)
        self.assertNotIn("writes Ishape 2 (round)", d1)
        t0, t1 = self._one_line_moves(
            _k1a_deck(_k1a_ass(7, 1, 2, tail=_cards_ae(srnde=1))),
            "7: Card E SRNDE 1 is not converted")
        self.assertTrue(t0.endswith("(the /INTER/TYPE25 routes write SRNDE 1 "
                                    "as Ishape 2)."), t0)
        self.assertTrue(t1.endswith("(the /INTER/TYPE25 routes write SRNDE 1 "
                                    "as Ishape 2 by default, and keep Ishape "
                                    "0 under --no-srnde-ishape)."), t1)

    def test_the_joint_screw_split_keeps_ishape_0(self):
        deck = _t7._screw_deck()
        old = ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n" + _row(0, 0, 5, 0) + "\n"
               + _row(0.1, 0.0, 0.0, 0.0) + "\n\n")
        new = ("*CONTACT_AUTOMATIC_GENERAL\n" + _row(0, 0, 5, 0) + "\n"
               + _row(0.1, 0.0, 0.0, 0.0) + "\n" + _row() + "\n"
               + _cards_ae(srnde=1))
        res, s, _e = _convert(deck.replace(old, new), srnde_ishape=False)
        ids = _type25_ids_by_title(s)
        self.assertEqual(len(ids), 2, ids)
        for title, iid in ids.items():
            with self.subTest(title=title):
                self.assertEqual(_ishape(s, iid), "0")
        self.assertEqual(len(_opt_out_lines(res, self._FLAG)), 1,
                         res.warnings)


class OptOutFlagHelpTexts(unittest.TestCase):
    """The four help texts say what the default writes, what the --no-
    spelling restores and what it was measured to move (the R14 numbers
    are the wave-D census of 2026-11-01)."""

    def test_each_help_names_its_item_and_what_the_opt_out_restores(self):
        for flag, needles in (
                ("--contact-birth-death", (
                    "Card-2 BT / DT", "Tstart / Tstop", "CardStack K-11",
                    "p.11-29/30", "ON by default", "--no-contact-birth-death",
                    "before K-11", "Tstart 0 / Tstop 0", "as stated",
                    "i7mainf.F:264-265", "i25mainf.F:310-311",
                    "6 starter decks", "STOP TIME -4.0E-03", "0.00 %",
                    "58.05 %",
                    # the split moves with its card and has no line of its
                    # own (the wave-D review)
                    "A line names each contact card whose cells the flag "
                    "moves", "a *CONSTRAINED_JOINT_SCREW split copies the "
                    "cells of its card, as its own line says")),
                ("--soft2-iedge-gate", (
                    "SOFT 2", "Iedge 22", "DEPTH 5 / 15 / 25 / 35 / 45 / 55",
                    "SBOPT 1", "p.11-94", "CardStack K-10", "ON by default",
                    "--no-soft2-iedge-gate", "convertcontacts.cxx:593-611",
                    "EDGE FLAG 22", "R14: 0 decks move")),
                ("--srnde-ishape", (
                    "SRNDE 1", "Ishape 2", "CardStack K-16", "ON by default",
                    "--no-srnde-ishape", "Ishape 0",
                    "GAP SHAPE ALONG MAIN FREE EDGES 1", "R14: 0 decks move")),
                ("--maxint-stress-all", (
                    "MAXINT", "/ANIM/SHELL/TENS/STRESS/ALL", "p.16-67",
                    "ON by default", "--no-maxint-stress-all", "K-42",
                    "9 engine decks", "MAXINT 4, 5, 7 or 8"))):
            h = _action_help(flag)
            for needle in needles:
                with self.subTest(flag=flag, needle=needle):
                    self.assertIn(needle, h)
            self.assertNotIn("names each interface the flag moves", h)

    def test_the_gui_names_each_opt_out_on_its_checkbox(self):
        src = _gui_source_joined()
        for needle in ("Card-2 BT / DT -> /INTER Tstart / Tstop",
                       "SOFT 2 Iedge 22 only with DEPTH",
                       "Card E SRNDE 1 -> TYPE25 Ishape 2",
                       "MAXINT > 3 -> /ANIM/SHELL/TENS/STRESS/ALL"):
            with self.subTest(needle=needle):
                self.assertIn(needle, src)


if __name__ == "__main__":
    unittest.main()
