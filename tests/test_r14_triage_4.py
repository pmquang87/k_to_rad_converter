"""Tests for the R14 CAMPAIGN TRIAGE batch, round 4 — PARTS A and B:

  A1  ``/IMPL/QSTAT/DTSCAL`` 0.1 -> 10 with the ``--qstat-dtscal VALUE|none``
      escape; ``--deformable-contact-recipe`` keeps its validated 0.05
  A2  ``*CONTROL_IMPLICIT_SOLUTION`` card-1 ``NSOLVR`` in {6,7,8,9} OR card-3
      ``ARCCTL`` != 0 -> ``/IMPL/DT/3`` (RIKS), OPT-IN behind
      ``--arclength-riks``, warned about either way
  A3  ``*ELEMENT_DISCRETE`` ``OFFSET`` -> the abscissa-shifted force law plus
      an ``/INISPRI/FULL`` pre-stretch energy (A), and the spring token-mass
      compensation on the nodes' ``/ADMAS`` (B). The headline is the BUNDLE.
  A4  ``*MAT_THERMAL_*`` ``TGMULT`` -> ``/FUNCT`` + ``/GRNOD`` + ``/IMPTEMP``
      holding the adiabatic closed form, HARD-gated on "no other temperature
      driver"
  A5  warnings only: ELFORM -1/-2/3 landing on ``Isolid`` 17;
      ``*INITIAL_VOID_PART`` naming the ALE fluid group of an emitted
      ``/INTER/TYPE18``; the unparsed ``*CONSTRAINED_LAGRANGE_IN_SOLID``
      cells; ``IAUTO``/``ITEWIN``/``KFAIL`` parsed-unused and a NEGATIVE
      ``DTMAX`` dropped

  B1  ``*DEFORMABLE_TO_RIGID`` (the plain spelling) -> the part is rigid from
      ``t = 0`` through the ``*MAT_RIGID`` / ``/RBODY`` machinery, behind ONE
      part-level predicate (``writer.common.rigid_part_ids``); the
      run-time-triggered options are refused BY NAME
  B2  the all-rigid-SSID swap on an EXPLICIT deck (default ON,
      ``--no-rigid-secondary-swap``), the both-sides-rigid KEEP, and the
      IMPLICIT drop that survives with ``bumper``'s measured divergence named
  B3  ``--derived-gapmin [--derived-gapmin-factor F]`` (default OFF) on a
      SOLID-only-main ``/INTER/TYPE7``, plus the default-ON warning that names
      the starter's own derived ``GAP MIN``
  B4  the docs: the ROADMAP round-4 column, the "deliberately does NOT close"
      list, the README rows, and the two shipped strings round 4 retracts

Kept in its own module, the repo's one-module-per-batch convention. Round 4
REPLACES two tests, and neither is moved here: A1's two round-3 assertions are
corrected IN PLACE
(``tests/test_converter.py::ImplicitEngineTests::test_qstat_and_nonlin_defaults``
and ``DeformableContactRecipeTests::test_defdef_detected_warns_without_recipe``),
and B2's
``tests/test_contact_silent_drop.py::RigidSecondaryContactDropped::
test_k2rad_does_not_silently_swap_the_sides`` is replaced by its named
successor in that same class — where the reader of the old value will look.
"""

import inspect
import os
import re
import tempfile
import unittest

from k2rad import convert
from k2rad import cli
from k2rad.handlers import HANDLERS, dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the helpers of tests/test_r14_triage_3.py) ──────────────────────

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


def _cell_after(text: str, card: str) -> str:
    """The single data line that follows *card*."""
    lines = text.splitlines()
    return lines[lines.index(card) + 1].strip()


def _has(warnings, *needles) -> bool:
    return any(all(n in w for n in needles) for w in warnings)


# ── One implicit deck, one 8-node brick ──────────────────────────────────────

_NODES = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
          (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]

_BRICK = (
    "*NODE\n"
    + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
              for i, (x, y, z) in enumerate(_NODES, start=1))
    + "*ELEMENT_SOLID\n"
      "       1       1       1       2       3       4       5       6       7       8\n"
      "*PART\n"
      "brick\n"
    + _row(1, 1, 1) + "\n"
)

_MAT_SEC = (
    "*SECTION_SOLID\n"
    + _row(1, "%ELFORM%") + "\n"
      "*MAT_ELASTIC\n"
    + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
)


def _implicit_deck(elform=1, nsolvr=2, arcctl=0, auto=None,
                   modal=False, arcmth=1) -> str:
    """A minimal QUASI-STATIC implicit deck (no *CONTROL_IMPLICIT_DYNAMICS).

    *modal* adds a ``*CONTROL_IMPLICIT_EIGENVALUE`` so the engine takes the
    ``/EIG`` branch instead — the shape ``ex_08_beam_elform_*`` has.
    """
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
            "*CONTROL_IMPLICIT_SOLUTION\n"
            + _row(nsolvr, 0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(arcctl, 1, 0.0, arcmth, 2, 0, 0, 0) + "\n")
    if modal:
        deck += "*CONTROL_IMPLICIT_EIGENVALUE\n" + _row(5) + "\n"
    if auto is not None:
        deck += "*CONTROL_IMPLICIT_AUTO\n" + _row(*auto) + "\n"
    deck += _BRICK + _MAT_SEC.replace("%ELFORM%", str(elform)) + "*END\n"
    return deck


# ═════════════════════════════════════════════════════════════════════════════
# A1 — /IMPL/QSTAT/DTSCAL
# ═════════════════════════════════════════════════════════════════════════════

class QstatDtscalDefaultTests(unittest.TestCase):
    """The stabilization scale is ``10``, and every escape works.

    ``imp_dyna.F:351`` builds ``S = (1+D_AL)*DY_B*DT2*DT2``, ``:353``
    multiplies it by ``SCAL_DTQ**2`` and ``:355`` takes ``BDT = 1/S``, so the
    diagonal k2rad adds is ``M/((1+alpha)*beta*(DTSCAL*dt)^2)`` — at the old
    0.1 that was 100x Radioss's own ``SCAL_DTQ = 1`` (``freimpl.F:135``).
    """

    def test_the_default_data_cell_is_10(self):
        _r, _s, engine = _convert(_implicit_deck())
        self.assertIn("/IMPL/QSTAT/DTSCAL", engine)
        self.assertEqual(_cell_after(engine, "/IMPL/QSTAT/DTSCAL"), "10")

    def test_0_point_1_reproduces_the_pre_round_4_line_byte_for_byte(self):
        _r, _s, engine = _convert(_implicit_deck(), qstat_dtscal=0.1)
        self.assertIn("/IMPL/QSTAT/DTSCAL\n 0.1\n", engine)

    def test_none_emits_no_qstat_card_and_keeps_the_rest_of_the_impl_block(self):
        _r, _s, engine = _convert(_implicit_deck(), qstat_dtscal="none")
        self.assertNotIn("/IMPL/QSTAT", engine)
        # The card is REMOVED, not the block: Radioss's own default is
        # SCAL_DTQ = 1 and the rest of the implicit setup is untouched.
        self.assertIn("/IMPL/NONLIN/1", engine)
        self.assertIn("/IMPL/SOLVER/2", engine)
        self.assertIn("/IMPL/DT/2", engine)

    def test_a_dynamic_implicit_deck_still_gets_no_qstat_at_all(self):
        """``/IMPL/DYNA/2`` and ``/IMPL/QSTAT`` are alternatives, and round 4
        must not have turned the option into a second way to emit one."""
        deck = _implicit_deck().replace(
            "*CONTROL_IMPLICIT_GENERAL\n",
            "*CONTROL_IMPLICIT_DYNAMICS\n" + _row(1, 0.5, 0.25) + "\n"
            "*CONTROL_IMPLICIT_GENERAL\n")
        _r, _s, engine = _convert(deck)
        self.assertIn("/IMPL/DYNA/2", engine)
        self.assertNotIn("/IMPL/QSTAT", engine)


class QstatDtscalArgumentTests(unittest.TestCase):
    """``--qstat-dtscal`` parses a number or ``none``, and nothing else."""

    def test_parser_default_is_10(self):
        args = cli.build_parser().parse_args(["m.k"])
        self.assertEqual(args.qstat_dtscal, 10.0)

    def test_the_THREE_declarations_of_every_default_agree(self):
        """``ConvertOptions``, ``convert()`` and the parser each state a
        default, and only two of the three are read on any given run.

        ``convert()`` is the package's only ``ConvertOptions`` construction and
        always passes every field, so the DATACLASS default is documentation —
        and a documentation default that drifts from the live one is exactly
        the shape MISTAKES calls "the same measurement shipping as two
        numbers". A whole-suite mutation of ``ConvertOptions.qstat_dtscal``
        10.0 -> 0.1 was MISSED by the round-4 suite until this test; it is the
        third leg of the ``--fixpoint-count`` lesson.
        """
        import inspect
        from k2rad.state import ConvertOptions
        opts = ConvertOptions()
        sig = inspect.signature(convert).parameters
        parser_defaults = vars(cli.build_parser().parse_args(["m.k"]))
        for field, parser_name in (("qstat_dtscal", "qstat_dtscal"),
                                   ("arclength_riks", "arclength_riks"),
                                   ("discrete_offset", "discrete_offset"),
                                   ("spring_token_mass_compensation",
                                    "spring_token_mass_compensation"),
                                   ("tgmult_imptemp", "tgmult_imptemp"),
                                   # part B's four levers, added for the same
                                   # reason: a whole-suite mutation of
                                   # ConvertOptions.derived_gapmin_factor
                                   # 0.005 -> 0.01 was MISSED until this row.
                                   ("derived_gapmin", "derived_gapmin"),
                                   ("derived_gapmin_factor",
                                    "derived_gapmin_factor"),
                                   ("rigid_secondary_swap",
                                    "rigid_secondary_swap"),
                                   ("deformable_to_rigid",
                                    "deformable_to_rigid")):
            with self.subTest(field=field):
                dataclass_default = getattr(opts, field)
                self.assertEqual(dataclass_default, sig[field].default,
                                 f"ConvertOptions.{field} disagrees with "
                                 f"convert()'s signature")
                self.assertEqual(dataclass_default,
                                 parser_defaults[parser_name],
                                 f"ConvertOptions.{field} disagrees with the "
                                 f"--{parser_name.replace('_', '-')} parser "
                                 f"default")

    def test_none_survives_as_the_string(self):
        args = cli.build_parser().parse_args(["m.k", "--qstat-dtscal", "none"])
        self.assertEqual(args.qstat_dtscal, "none")
        args = cli.build_parser().parse_args(["m.k", "--qstat-dtscal", "NONE"])
        self.assertEqual(args.qstat_dtscal, "none")

    def test_a_number_becomes_a_float(self):
        args = cli.build_parser().parse_args(["m.k", "--qstat-dtscal", "0.1"])
        self.assertEqual(args.qstat_dtscal, 0.1)

    def test_zero_and_garbage_are_refused(self):
        for bad in ("0", "-3", "foo"):
            with self.subTest(value=bad):
                with self.assertRaises(SystemExit) as cm:
                    cli.build_parser().parse_args(
                        ["m.k", "--qstat-dtscal", bad])
                self.assertEqual(cm.exception.code, 2)

    def test_the_help_renders_and_carries_the_measured_number(self):
        """A bare ``%`` in a help string kills ``--help`` (k2rad #135), and the
        measured figure is what makes the default defensible to a reader."""
        text = cli.build_parser().format_help()
        self.assertIn("(-0.31 %)", text)
        self.assertIn("--qstat-dtscal", text)


class GuiWiringTests(unittest.TestCase):
    """``k2rad_gui.build_convert_kwargs`` is the 13th wiring site, and nothing
    else reads it.

    Same shape as ``tie_stfac``'s: a BLANK entry means "let ``convert()``
    decide" and must not put the key in the kwargs at all, ``none`` survives as
    the string, and a bad value raises a user-facing ``ValueError`` rather than
    reaching the writer. The BooleanOptionalAction twins pass straight through
    with their ON defaults.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "a.k")
        with open(self.path, "w") as fh:
            fh.write("*KEYWORD\n*END\n")
        self.base = dict(ground_springs=False, ground_spring_k_text="",
                         soften_stfac_text="")

    def tearDown(self):
        self.tmp.cleanup()

    def _kw(self, **extra):
        import k2rad_gui
        return k2rad_gui.build_convert_kwargs(
            self.path, "", ("Mg", "mm", "s"), **self.base, **extra)

    def test_blank_leaves_the_convert_default_alone(self):
        kw = self._kw()
        self.assertNotIn("qstat_dtscal", kw)
        self.assertFalse(kw["arclength_riks"])
        self.assertTrue(kw["discrete_offset"])
        self.assertTrue(kw["spring_token_mass_compensation"])
        self.assertTrue(kw["tgmult_imptemp"])

    def test_a_value_and_none_both_survive(self):
        self.assertEqual(self._kw(qstat_dtscal_text="0.1")["qstat_dtscal"], 0.1)
        self.assertEqual(self._kw(qstat_dtscal_text="NONE")["qstat_dtscal"],
                         "none")

    def test_a_bad_value_raises_before_the_writer_sees_it(self):
        for bad in ("0", "-1", "foo"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self._kw(qstat_dtscal_text=bad)

    def test_the_options_summary_names_every_non_default(self):
        """The "options in effect" line is the 13th site: a flag wired
        everywhere but here ships silently, and the user never learns which
        conversion they got."""
        import k2rad_gui
        captured = []
        app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)   # no Tk root needed
        app._append = captured.append
        k2rad_gui.ConverterGUI._describe_options(app, self._kw(
            qstat_dtscal_text="0.1", arclength_riks=True,
            discrete_offset=False, spring_token_mass_compensation=False,
            tgmult_imptemp=False))
        text = "".join(captured)
        for needle in ("/IMPL/QSTAT/DTSCAL=0.1", "--arclength-riks",
                       "--no-discrete-offset",
                       "--no-spring-token-mass-compensation",
                       "--no-tgmult-imptemp"):
            self.assertIn(needle, text)

    def test_the_summary_stays_quiet_on_a_default_conversion(self):
        import k2rad_gui
        captured = []
        app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
        app._append = captured.append
        k2rad_gui.ConverterGUI._describe_options(app, self._kw())
        text = "".join(captured)
        for needle in ("/IMPL/QSTAT/DTSCAL", "--arclength-riks",
                       "--no-discrete-offset",
                       "--no-spring-token-mass-compensation",
                       "--no-tgmult-imptemp"):
            self.assertNotIn(needle, text)


class QstatDtscalRecipeStillWinsTests(unittest.TestCase):
    """``--deformable-contact-recipe``'s 0.05 is separately validated, opt-in,
    and must not be reachable from ``--qstat-dtscal``.

    The recipe branch is evaluated FIRST, exactly as before round 4, so the
    combination is not a conflict — the recipe simply ignores the flag.
    """

    #: a deformable/deformable TYPE7 on the two-brick mesh the recipe detects
    _DEFDEF = (
        "*KEYWORD\n"
        "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
        "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
        "*NODE\n"
        + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                  for i, (x, y, z) in enumerate(
                      _NODES + [(2, 0, 0), (2, 1, 0), (2, 0, 1), (2, 1, 1)],
                      start=1))
        + "*ELEMENT_SOLID\n"
          "       1       1       1       2       3       4       5       6       7       8\n"
          "       2       2       2       9      10       3       6      11      12       7\n"
          "*PART\n"
          "left\n" + _row(1, 1, 1) + "\n"
          "right\n" + _row(2, 1, 1) + "\n"
          "*SECTION_SOLID\n" + _row(1, 1) + "\n"
          "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
          "*SET_PART_LIST\n" + _row(1) + "\n" + _row(1) + "\n"
          "*SET_PART_LIST\n" + _row(2) + "\n" + _row(2) + "\n"
          "*CONTACT_SURFACE_TO_SURFACE\n"
        + _row(1, 2, 2, 2, 0, 0, 0, 0) + "\n"
        + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n"
        + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n"
          "*END\n"
    )

    def test_the_recipe_keeps_0_05_even_with_qstat_dtscal_none(self):
        _r, _s, engine = _convert(self._DEFDEF,
                                  deformable_contact_recipe=True,
                                  qstat_dtscal="none")
        self.assertIn("/IMPL/QSTAT/DTSCAL", engine)
        self.assertEqual(_cell_after(engine, "/IMPL/QSTAT/DTSCAL"), "0.05")

    def test_the_recipe_keeps_0_05_against_an_explicit_value(self):
        _r, _s, engine = _convert(self._DEFDEF,
                                  deformable_contact_recipe=True,
                                  qstat_dtscal=0.1)
        self.assertEqual(_cell_after(engine, "/IMPL/QSTAT/DTSCAL"), "0.05")


# ═════════════════════════════════════════════════════════════════════════════
# A2 — arc length -> /IMPL/DT/3
# ═════════════════════════════════════════════════════════════════════════════

class ArcLengthPredicateTests(unittest.TestCase):
    """THE MANUAL'S OWN RULE: ``6 <= NSOLVR <= 9``, or ``NSOLVR = 12`` with
    card-3 ``ARCMTH = 3``.

    Vol I R17 p.12-354 and p.12-358 both state it verbatim — *"The contents of
    this card are ignored unless an arc-length method is activated
    (6 <= NSOLVR <= 9, or NSOLVR = 12 and ARCMTH = 3)"* — and p.12-358 defines
    ``ARCCTL`` as *"Arc length controlling node ID (see Remark 7). EQ.0:
    Generalized arc length method"*, i.e. a NODE ID, not a switch. The
    identical sentence is in Vol I R16.

    A ``arcctl != 0`` clause used to ship here and was wrong on a deck we can
    check against LS-DYNA's own output: ``ex_06_beam_elform_1`` states
    NSOLVR 12 / ARCMTH 1 / ARCCTL 6, and its reference ``d3hsp`` reads
    ``solution method ... 12`` with ``arc length formulation 1 = Crisfield``
    beside the legend ``eq.3: Modified Crisfield (used with nonlinear solution
    method 12 only)`` — plain BFGS, no arc length. So the deck got a
    default-ON warning saying it asked for one, and ``--arclength-riks`` would
    have converted it to a solver LS-DYNA did not use.
    """

    def test_arcctl_and_arcmth_are_parsed_off_card_3(self):
        state = _dispatch(_implicit_deck(nsolvr=12, arcctl=6, arcmth=1))
        self.assertIsNotNone(state.ctrl_implicit_sol)
        self.assertEqual(state.ctrl_implicit_sol.nsolvr, 12)
        self.assertEqual(state.ctrl_implicit_sol.arcctl, 6)
        self.assertEqual(state.ctrl_implicit_sol.arcmth, 1)

    def test_a_deck_with_no_card_3_reads_both_cells_0(self):
        deck = ("*KEYWORD\n"
                "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
                "*CONTROL_IMPLICIT_SOLUTION\n"
                + _row(2, 0, 0, 0, 0, 0, 0, 0) + "\n"
                "*END\n")
        state = _dispatch(deck)
        self.assertEqual(state.ctrl_implicit_sol.arcctl, 0)
        self.assertEqual(state.ctrl_implicit_sol.arcmth, 0)

    def test_nsolvr_6_fires_and_nsolvr_2_does_not(self):
        from k2rad.writer.assembly import _arclength_requested
        self.assertTrue(_arclength_requested(_dispatch(_implicit_deck(nsolvr=6))))
        self.assertFalse(_arclength_requested(_dispatch(_implicit_deck(nsolvr=2))))

    def test_arcctl_alone_does_NOT_fire(self):
        """The successor of ``test_arcctl_alone_fires``, which pinned the
        retracted predicate on exactly ``ex_06``'s own card values."""
        from k2rad.writer.assembly import _arclength_requested
        self.assertFalse(_arclength_requested(
            _dispatch(_implicit_deck(nsolvr=12, arcctl=6, arcmth=1))))
        # ...and it does not rescue a non-arc-length NSOLVR either.
        self.assertFalse(_arclength_requested(
            _dispatch(_implicit_deck(nsolvr=2, arcctl=6, arcmth=1))))

    def test_nsolvr_12_with_ARCMTH_3_is_the_other_route(self):
        from k2rad.writer.assembly import _arclength_requested
        self.assertTrue(_arclength_requested(
            _dispatch(_implicit_deck(nsolvr=12, arcmth=3))))
        # ARCCTL is irrelevant to the predicate in BOTH directions.
        self.assertTrue(_arclength_requested(
            _dispatch(_implicit_deck(nsolvr=12, arcmth=3, arcctl=6))))
        # ARCMTH 3 is meaningless outside NSOLVR 12 ("used with nonlinear
        # solution method 12 only").
        self.assertFalse(_arclength_requested(
            _dispatch(_implicit_deck(nsolvr=2, arcmth=3))))

    def test_every_nsolvr_in_the_set_fires(self):
        from k2rad.writer.assembly import _arclength_requested
        for n in (6, 7, 8, 9):
            with self.subTest(nsolvr=n):
                self.assertTrue(
                    _arclength_requested(_dispatch(_implicit_deck(nsolvr=n))))
        for n in (1, 2, 12):
            with self.subTest(nsolvr=n):
                self.assertFalse(
                    _arclength_requested(_dispatch(_implicit_deck(nsolvr=n))))

    def test_the_ex_06_arm_is_silent_and_emits_DT2(self):
        """End to end on ``ex_06``'s own card, both arms of the flag: no
        warning, and the flag cannot turn it into ``/IMPL/DT/3``."""
        for riks in (False, True):
            with self.subTest(arclength_riks=riks):
                result, _s, engine = _convert(
                    _implicit_deck(nsolvr=12, arcctl=6, arcmth=1),
                    arclength_riks=riks)
                self.assertIn("/IMPL/DT/2", engine)
                self.assertNotIn("/IMPL/DT/3", engine)
                self.assertFalse(_has(result.warnings, "ARC-LENGTH"),
                                 result.warnings)

    def test_the_ARCMTH_3_arm_names_both_cells_in_its_warning(self):
        result, _s, _e = _convert(_implicit_deck(nsolvr=12, arcmth=3,
                                                 arcctl=6))
        self.assertTrue(_has(result.warnings, "ARC-LENGTH", "NSOLVR=12",
                             "ARCMTH=3", "ARCCTL=6"), result.warnings)


class ArcLengthCardTests(unittest.TestCase):
    """The card, and the fact that it is OPT-IN.

    The repeat at a second thread count REFUTED it as a default:
    ``ex_05_beam_elform_3_&_6`` fails in ~2 s without the flag and with it
    runs tens of thousands of cycles to ``t ~ 1e-7`` of 1.0 and TIMES OUT, at
    nt 3 and nt 4 alike. (An ``ex_06`` nt-flip was cited beside it and is
    withdrawn twice over: it did not reproduce on a quiet machine — NORMAL at
    both nt, agreeing to 0.02 pp — and under the manual's own predicate
    ``ex_06`` is not an arc-length carrier at all.)
    """

    def test_off_by_default_the_card_is_dt2_and_the_request_is_warned(self):
        result, _s, engine = _convert(_implicit_deck(nsolvr=6))
        self.assertIn("/IMPL/DT/2", engine)
        self.assertNotIn("/IMPL/DT/3", engine)
        self.assertTrue(_has(result.warnings, "ARC-LENGTH", "NSOLVR=6",
                             "--arclength-riks"))

    def test_the_flag_emits_dt3_with_SEVEN_fields(self):
        """``freimpl.F:384-387`` READs seven list-directed values from ONE
        record; a five-field line (``/IMPL/DT/2``'s shape) would run the READ
        off the end of it."""
        _r, _s, engine = _convert(_implicit_deck(nsolvr=6), arclength_riks=True)
        self.assertIn("/IMPL/DT/3", engine)
        self.assertNotIn("/IMPL/DT/2", engine)
        cells = _cell_after(engine, "/IMPL/DT/3").split()
        self.assertEqual(len(cells), 7, f"/IMPL/DT/3 data line: {cells}")
        self.assertEqual(cells[1:], ["0"] * 6)     # lectur.F defaults

    def test_the_flag_does_nothing_on_a_deck_that_did_not_ask(self):
        _r, _s, engine = _convert(_implicit_deck(nsolvr=2), arclength_riks=True)
        self.assertIn("/IMPL/DT/2", engine)
        self.assertNotIn("/IMPL/DT/3", engine)

    def test_the_warning_names_the_measurement_and_never_claims_a_result(self):
        result, _s, _e = _convert(_implicit_deck(nsolvr=6), arclength_riks=True)
        w = next(x for x in result.warnings if "ARC-LENGTH" in x)
        self.assertIn("BUYS THE LOAD PATH, NOT THE ANSWER", w)
        self.assertIn("ex_05_beam_elform_3_&_6", w)     # the named regression
        self.assertIn("nt 3", w)
        self.assertIn("nt 4", w)

    def test_fixpoint_is_disarmed_under_riks_and_says_so(self):
        """``lectur.F:3523-3532`` prints ``** WARNING :RIKS METHOD IS NOT
        COMPATIBLE WITH FIXED TIME POINT`` and sets ``NDTFIX = 0`` itself, so
        an emitted card would be read and thrown away."""
        result, _s, engine = _convert(_implicit_deck(nsolvr=6),
                                      arclength_riks=True, fixpoint_count=10)
        self.assertNotIn("/IMPL/DT/FIXPOINT", engine)
        self.assertTrue(_has(result.warnings, "DISARMED", "RIKS"))

    def test_fixpoint_still_works_without_the_flag(self):
        _r, _s, engine = _convert(_implicit_deck(nsolvr=6), fixpoint_count=10)
        self.assertIn("/IMPL/DT/FIXPOINT", engine)


# ═════════════════════════════════════════════════════════════════════════════
# A3 — *ELEMENT_DISCRETE OFFSET (A) + the spring token mass (B)
# ═════════════════════════════════════════════════════════════════════════════

#: ex_17_spring_elform_0's own numbers: K = 0.87563418, OFFSET = 25.4, and an
#: *ELEMENT_MASS of 4.5322825e-4 on each end node.
_K = 0.87563418
_OFFSET = 25.4
_NODE_MASS = 4.5322825e-4
_TOKEN = 1.0e-4


def _spring_deck(offset=_OFFSET, mass=_NODE_MASS, k=_K, curve=False,
                 extra="") -> str:
    """A two-node axial spring with an *ELEMENT_MASS on each end."""
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(0.15) + "\n"
            "*NODE\n"
            + f"{1:>8}{0.0:>16.1f}{0.0:>16.1f}{0.0:>16.1f}\n"
            + f"{2:>8}{10.0:>16.1f}{0.0:>16.1f}{0.0:>16.1f}\n"
            + "*ELEMENT_DISCRETE\n"
            # EID(8) PID(8) N1(8) N2(8) VID(8) S(E16) PF(8) OFFSET(E16)
            + f"{1:>8}{1:>8}{1:>8}{2:>8}{0:>8}{1.0:>16.8G}{0:>8}"
              f"{offset:>16.8G}\n"
            + "*PART\n"
              "spring\n" + _row(1, 1, 1) + "\n"
              "*SECTION_DISCRETE\n" + _row(1, 0) + "\n")
    if curve:
        deck += ("*MAT_SPRING_NONLINEAR_ELASTIC\n" + _row(1, 1) + "\n"
                 "*DEFINE_CURVE\n" + _row(1) + "\n"
                 + "".join(f"{x:>20.10G}{y:>20.10G}\n"
                           for x, y in ((0.0, 0.0), (25.4, _K * 25.4),
                                        (50.8, _K * 50.8))))
    else:
        deck += "*MAT_SPRING_ELASTIC\n" + _row(1, k) + "\n"
    if mass:
        deck += ("*ELEMENT_MASS\n"
                 + f"{1:>8}{1:>8}{mass:>16.8G}\n"
                 + f"{2:>8}{2:>8}{mass:>16.8G}\n")
    return deck + extra + "*END\n"


class DiscreteOffsetLinearLawTests(unittest.TestCase):
    """A ``*MAT_SPRING_ELASTIC`` + ``OFFSET`` becomes a SHIFTED two-point law.

    Vol I R17 p.19-33: ``OFFSET`` is *"a displacement or rotation at time zero.
    For example, a positive offset on a translational spring will lead to a
    tensile force being developed at time zero."* Radioss spring deflection is
    purely geometric (``r1def3.F:206`` ``DL = ALDP - AL0DP``), so
    ``delta_LS = delta_RAD + OFFSET`` and the exact restatement is
    ``f_RAD(d) = f_LS(d + OFFSET)``.
    """

    def _funct(self, starter, title_part):
        lines = starter.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("/FUNCT/") and title_part in lines[i + 1]:
                pts = []
                for row in lines[i + 3:]:
                    if row.startswith("#") or row.startswith("/"):
                        break
                    pts.append(tuple(float(v) for v in row.split()))
                return int(line.rsplit("/", 1)[1]), pts
        return None, []

    def test_the_synthesized_law_is_exactly_two_hand_computed_points(self):
        _r, starter, _e = _convert(_spring_deck())
        fid, pts = self._funct(starter, "discrete_offset")
        self.assertIsNotNone(fid, starter)
        # f(d) = K*(d + OFFSET) over [-2*OFFSET, +OFFSET]
        self.assertEqual(len(pts), 2)
        self.assertAlmostEqual(pts[0][0], -50.8, places=9)
        self.assertAlmostEqual(pts[0][1], -22.24110817, places=7)
        self.assertAlmostEqual(pts[1][0], 25.4, places=9)
        self.assertAlmostEqual(pts[1][1], 44.48221634, places=7)

    def test_K_stays_on_the_property_card(self):
        """``r1len3.F`` reads it for the element time step and ``MAX_SLOPE``,
        and ``hm_read_prop04.F:249`` stores the stiffness as ``K/A``."""
        _r, starter, _e = _convert(_spring_deck())
        block = starter.split("/PROP/TYPE4/")[1]
        self.assertIn(f"{_K:.10G}", block)

    def test_fct_id11_points_at_the_shifted_clone(self):
        _r, starter, _e = _convert(_spring_deck())
        fid, _pts = self._funct(starter, "discrete_offset")
        lines = starter.splitlines()
        i = next(j for j, l in enumerate(lines)
                 if l.startswith("# fct_ID11"))
        self.assertEqual(int(lines[i + 1].split()[0]), fid)

    def test_the_inispri_energy_is_half_f_times_offset(self):
        """LS-DYNA's OWN datum, not an assumption: ``ex_17``'s ``deforc`` at
        ``t = 0`` reads ``y-force 2.22402E+01`` at ``change in length
        2.54000E+01`` and its ``glstat`` ``internal energy 2.82451E+02``."""
        _r, starter, _e = _convert(_spring_deck())
        self.assertIn("/INISPRI/FULL", starter)
        block = starter.split("/INISPRI/FULL\n")[1]
        rows = [r for r in block.splitlines()[:6] if not r.startswith("#")]
        ids = rows[0].split()
        self.assertEqual(ids, ["1", "4", "0"])       # spring_ID prop_type nvars
        self.assertEqual([float(v) for v in rows[1].split()], [0.0] * 5)
        l_x, ei = (float(v) for v in rows[2].split())
        self.assertEqual(l_x, 0.0)                   # rinit3.F:2022 XL0 = 0
        self.assertAlmostEqual(ei, 0.5 * _K * _OFFSET ** 2, places=6)
        self.assertAlmostEqual(ei, 282.4620738, places=6)

    def test_no_offset_emits_no_inispri_and_no_clone(self):
        _r, starter, _e = _convert(_spring_deck(offset=0.0))
        self.assertNotIn("/INISPRI", starter)
        self.assertNotIn("discrete_offset", starter)

    def test_the_opt_out_drops_it_with_a_named_warning(self):
        result, starter, _e = _convert(_spring_deck(), discrete_offset=False)
        self.assertNotIn("/INISPRI", starter)
        self.assertNotIn("discrete_offset", starter)
        self.assertTrue(_has(result.warnings, "OFFSET=25.4",
                             "--no-discrete-offset"))


class DiscreteOffsetCurveLawTests(unittest.TestCase):
    """A curve-driven law is COPIED and shifted; the original is untouched."""

    def test_every_abscissa_moves_by_minus_offset_and_the_ordinates_do_not(self):
        _r, starter, _e = _convert(_spring_deck(curve=True))
        lines = starter.splitlines()

        def pts_of(fid_line):
            i = lines.index(fid_line)
            out = []
            for row in lines[i + 3:]:
                if row.startswith("#") or row.startswith("/"):
                    break
                out.append(tuple(float(v) for v in row.split()))
            return out

        original = pts_of("/FUNCT/1")
        clone_head = next(l for l in lines
                          if l.startswith("/FUNCT/")
                          and "discrete_offset" in lines[lines.index(l) + 1])
        shifted = pts_of(clone_head)
        self.assertEqual(len(original), len(shifted))
        for (xa, ya), (xb, yb) in zip(original, shifted):
            self.assertAlmostEqual(xb, xa - _OFFSET, places=9)
            self.assertEqual(yb, ya)                 # ordinates BIT-identical

    def test_the_original_curve_id_is_not_mutated(self):
        """The same LCID may drive another part; the clone is a new id."""
        _r, starter, _e = _convert(_spring_deck(curve=True))
        lines = starter.splitlines()
        i = lines.index("/FUNCT/1")
        self.assertEqual([float(v) for v in lines[i + 3].split()], [0.0, 0.0])

    def test_the_inispri_energy_uses_the_curve_value_at_offset(self):
        _r, starter, _e = _convert(_spring_deck(curve=True))
        block = starter.split("/INISPRI/FULL\n")[1]
        rows = [r for r in block.splitlines()[:6] if not r.startswith("#")]
        _l_x, ei = (float(v) for v in rows[2].split())
        self.assertAlmostEqual(ei, 0.5 * (_K * 25.4) * _OFFSET, places=6)


class DiscreteOffsetCurveIdGuardTests(unittest.TestCase):
    """The shifted ``/FUNCT`` must dodge the ``/TABLE`` registry (k2rad #111).

    ``hm_read_table.F:88`` counts "total number /TABLE + /FUNCT" before the
    ``UDOUBLE`` duplicate pass, so ``/FUNCT`` and ``/TABLE`` are ONE starter id
    namespace and a collision is ``ERROR 79 DUPLICATE ID``.
    """

    def test_a_table_at_the_auto_id_base_does_not_collide(self):
        table = ("*DEFINE_TABLE\n" + _row(90001) + "\n"
                 + _row(0.0) + "\n"
                 "*DEFINE_TABLE\n" + _row(90002) + "\n"
                 + _row(0.0) + "\n"
                 "*DEFINE_TABLE\n" + _row(90003) + "\n"
                 + _row(0.0) + "\n"
                 "*DEFINE_TABLE\n" + _row(90004) + "\n"
                 + _row(0.0) + "\n")
        _r, starter, _e = _convert(_spring_deck(extra=table))
        ids = [int(l.rsplit("/", 1)[1]) for l in starter.splitlines()
               if l.startswith("/FUNCT/")]
        self.assertTrue(ids, starter)
        for fid in ids:
            self.assertNotIn(fid, (90001, 90002, 90003, 90004))


class SpringTokenMassCompensationTests(unittest.TestCase):
    """``rinit3.F:1926`` ``EMS = HALF*UMASS`` and ``:1937-1939``
    ``MSR(1..3,I) = EMS(I)`` — HALF the property mass on EACH end node, PER
    ELEMENT. LS-DYNA's discrete elements carry none of it."""

    def _admas(self, starter):
        """``{mass: [nodes]}`` over every emitted ``/ADMAS/0``."""
        lines = starter.splitlines()
        groups = {}
        for i, line in enumerate(lines):
            if line.startswith("/GRNOD/NODE/"):
                gid = int(line.rsplit("/", 1)[1])
                members = []
                for row in lines[i + 2:]:
                    if row.startswith("#") or row.startswith("/"):
                        break
                    members += [int(v) for v in row.split()]
                groups[gid] = members
        out = {}
        for i, line in enumerate(lines):
            if line.startswith("/ADMAS/0/"):
                mass, gid = lines[i + 3].split()
                out[float(mass)] = sorted(groups[int(gid)])
        return out

    def test_one_spring_per_node_subtracts_half_the_token(self):
        _r, starter, _e = _convert(_spring_deck())
        admas = self._admas(starter)
        want = _NODE_MASS - _TOKEN / 2
        self.assertAlmostEqual(list(admas)[0], want, places=12)
        self.assertAlmostEqual(list(admas)[0], 4.0322825e-4, places=12)
        self.assertEqual(admas[list(admas)[0]], [1, 2])

    def test_a_node_shared_by_two_springs_splits_the_admas_group(self):
        """``spring.k``'s shape: three nodes in a row, so the middle one
        carries TWO spring halves and the ends carry one. One ``/ADMAS`` group
        cannot hold both values."""
        deck = ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(0.15) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{10.0 * (i - 1):>16.1f}"
                          f"{0.0:>16.1f}{0.0:>16.1f}\n" for i in (1, 2, 3))
                + "*ELEMENT_DISCRETE\n"
                + f"{1:>8}{1:>8}{1:>8}{2:>8}{0:>8}{1.0:>16.8G}{0:>8}{0.0:>16.8G}\n"
                + f"{2:>8}{1:>8}{2:>8}{3:>8}{0:>8}{1.0:>16.8G}{0:>8}{0.0:>16.8G}\n"
                + "*PART\n"
                  "spring\n" + _row(1, 1, 1) + "\n"
                  "*SECTION_DISCRETE\n" + _row(1, 0) + "\n"
                  "*MAT_SPRING_ELASTIC\n" + _row(1, _K) + "\n"
                  "*ELEMENT_MASS\n"
                + "".join(f"{i:>8}{i:>8}{5.0e-4:>16.8G}\n" for i in (1, 2, 3))
                + "*END\n")
        _r, starter, _e = _convert(deck)
        admas = self._admas(starter)
        self.assertEqual(len(admas), 2, admas)
        ends = round(5.0e-4 - _TOKEN / 2, 12)
        middle = round(5.0e-4 - _TOKEN, 12)
        self.assertEqual({round(m, 12) for m in admas}, {ends, middle})
        self.assertEqual(admas[[m for m in admas
                                if round(m, 12) == middle][0]], [2])
        self.assertEqual(admas[[m for m in admas
                                if round(m, 12) == ends][0]], [1, 3])

    def test_the_degenerate_node_keeps_its_own_mass_and_is_named(self):
        """``gnonspring.k``: ``/ADMAS`` 1e-6 against a token half of 5e-5, 50x.
        An ``/ADMAS`` must stay positive, so nothing is subtracted."""
        result, starter, _e = _convert(_spring_deck(mass=1.0e-6))
        admas = self._admas(starter)
        self.assertEqual([round(m, 12) for m in admas], [1.0e-6])
        self.assertTrue(_has(result.warnings, "LESS /ADMAS",
                             "token share 5e-05"))

    def test_a_node_with_no_admas_and_no_element_mass_is_named(self):
        """``mat_spring.belted-dummy.k``: 122 springs, zero ``/ADMAS``.

        ROUND 5 supersedes the old name
        (``test_a_node_with_no_admas_is_named_and_none_is_invented``) and the
        old warning text: the no-``/ADMAS`` class is now compensated with a
        NEGATIVE ``/ADMAS``. What this fixture still pins is the GUARDED arm —
        these spring ends carry no element of their own, so nothing may be
        subtracted (``rcheckmass.F:126-135`` = ERROR 1870) and no ``/ADMAS``
        is invented. The compensated arm is
        ``tests/test_r14_triage_5.py::SpringTokenNegativeAdmas``.
        """
        result, starter, _e = _convert(_spring_deck(mass=0.0))
        self.assertNotIn("/ADMAS", starter)
        self.assertTrue(_has(result.warnings,
                             "carry NO element mass of their own",
                             "*ELEMENT_MASS if their dynamics matter"))

    def test_the_opt_out_leaves_the_admas_exactly_as_the_deck_states_it(self):
        _r, starter, _e = _convert(_spring_deck(),
                                   spring_token_mass_compensation=False)
        admas = self._admas(starter)
        self.assertAlmostEqual(list(admas)[0], _NODE_MASS, places=12)

    def test_the_token_mass_constant_is_named_once_and_never_a_literal(self):
        """The compensation and the EMISSION must not be able to drift: the
        constant was named at ``loads.py`` module level and then written as a
        bare ``1.0e-4`` at three emission sites and two warning strings.

        ROUND 5 strengthened this, because the LINE scan below missed a whole
        release: ``_make_constrained_spotweld_springs`` put its
        ``_emit_prop_type13(...)`` on one line and the literal ``1.0e-4`` on
        the CONTINUATION line, so no single line held both and the guard was
        satisfied while a fourth emission site invented a token nobody
        compensated. The AST half scans the STATEMENT, not the line.
        """
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "k2rad", "writer", "loads.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        lines = src.splitlines()
        offenders = [
            (i + 1, l) for i, l in enumerate(lines)
            if "1.0e-4" in l and "_SPRING_TOKEN_MASS = 1.0e-4" not in l
            and "1.0e-6" not in l]
        # The surviving 1.0e-4 literal belongs to ANOTHER emitter (the opt-in
        # --ground-springs /PROP/TYPE8), which has its own mass policy and is
        # deliberately not compensated here.
        for _n, line in offenders:
            self.assertNotIn("_emit_prop_type4(", line)
            self.assertNotIn("_emit_prop_type13(", line)

        # ── the statement-level half ──────────────────────────────────────
        import ast
        tree = ast.parse(src)
        #: The ONE function allowed to write a bare spring token mass: the
        #: opt-in grounding spring, which the LS deck does not state at all.
        allowed = {"_make_grounding_springs"}
        def _is_token(node):
            return (isinstance(node, ast.Constant)
                    and isinstance(node.value, float)
                    and node.value == 1.0e-4)

        bad = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name in allowed:
                continue
            for node in ast.walk(fn):
                # a bare token in a spring-property EMISSION call ...
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id.startswith("_emit_prop_type")
                        and any(_is_token(a) for a in node.args)):
                    bad.append(f"{fn.name}:{node.lineno} (emission call)")
                # ... or assigned to anything called a mass on its way there.
                if isinstance(node, ast.Assign) and _is_token(node.value):
                    names = [t.id for t in node.targets
                             if isinstance(t, ast.Name)]
                    if any("mass" in n.lower() for n in names):
                        bad.append(f"{fn.name}:{node.lineno} ({names})")
        self.assertEqual(
            bad, [],
            "a bare 1.0e-4 spring token mass outside "
            f"{sorted(allowed)} — use _SPRING_TOKEN_MASS so the /ADMAS "
            f"compensation cannot drift from the emission: {bad}")

    def test_the_warning_no_longer_tells_the_reader_to_ADD_mass(self):
        """The old sentence prescribed exactly the wrong fix: *"add
        \\*ELEMENT_MASS-equivalent mass if dynamics of the spring ends
        matter"*, when the defect is that k2rad had ADDED mass."""
        result, _s, _e = _convert(_spring_deck())
        joined = "\n".join(result.warnings)
        self.assertNotIn("add *ELEMENT_MASS-equivalent mass", joined)
        self.assertIn("MASSLESS", joined)


class DiscreteOffsetRefusalsTests(unittest.TestCase):
    """The two 6-DOF shapes are refused BY NAME, with the value.

    Their ``/INISPRI/FULL`` record is the type-8/13/25 subobject, a card shape
    with zero carriers on any corpus here — an unmeasured card is not shipped.
    """

    def test_a_torsional_DRO_1_section_is_refused_by_name(self):
        deck = _spring_deck().replace(
            "*SECTION_DISCRETE\n" + _row(1, 0) + "\n",
            "*SECTION_DISCRETE\n" + _row(1, 1) + "\n")
        result, starter, _e = _convert(deck)
        self.assertNotIn("/INISPRI", starter)
        self.assertTrue(_has(result.warnings, "OFFSET=25.4", "TORSIONAL"))

    def test_an_oriented_VID_element_is_refused_by_name(self):
        deck = _spring_deck().replace(
            f"{1:>8}{1:>8}{1:>8}{2:>8}{0:>8}",
            f"{1:>8}{1:>8}{1:>8}{2:>8}{7:>8}")
        deck = deck.replace(
            "*PART\n",
            "*DEFINE_SD_ORIENTATION\n"
            + _row(7, 0, 1.0, 0.0, 0.0) + "\n"
              "*PART\n", 1)
        result, starter, _e = _convert(deck)
        self.assertNotIn("/INISPRI", starter)
        self.assertTrue(_has(result.warnings, "OFFSET=25.4",
                             "*DEFINE_SD_ORIENTATION VID=7"))


# ═════════════════════════════════════════════════════════════════════════════
# A4 — *MAT_THERMAL_* TGMULT -> /IMPTEMP
# ═════════════════════════════════════════════════════════════════════════════

def _thermal_deck(tgmult=10.0, tgrlc=0, t0=10.0, hc=1.0, tro=1.0,
                  extra="", endtim=3.0) -> str:
    """A single brick with a thermal material and nothing else driving it."""
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(endtim) + "\n"
            "*CONTROL_SOLUTION\n" + _row(2) + "\n"
            "*CONTROL_THERMAL_SOLVER\n" + _row(1, 0.0, 0) + "\n"
            # *PART card 2 is PID SECID MID EOSID HGID GRAV ADPOPT TMID —
            # TMID is field 8, and it is the ONLY thing that binds a
            # *MAT_THERMAL_* to a part.
            + _BRICK.replace(_row(1, 1, 1) + "\n",
                             _row(1, 1, 1, 0, 0, 0, 0, 1) + "\n")
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
              "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
              "*MAT_THERMAL_ISOTROPIC\n"
            # TMID TRO TGRLC TGMULT TLAT HLAT / HC TC
            + _row(1, tro, tgrlc, tgmult, 0.0, 0.0) + "\n"
            + _row(hc, 1.0) + "\n"
              "*INITIAL_TEMPERATURE_SET\n" + _row(0, t0) + "\n"
            + extra + "*END\n")


class TgmultImptempTests(unittest.TestCase):
    """``T(t) = T0 + (TGMULT/(rho*Cp))*INTEGRAL(f dt)`` — the adiabatic uniform-generation
    closed form, the only shape in which a volumetric heat generation is
    expressible as an ``/IMPTEMP``."""

    def _funct_pts(self, starter, fid):
        lines = starter.splitlines()
        i = lines.index(f"/FUNCT/{fid}")
        out = []
        for row in lines[i + 3:]:
            if row.startswith("#") or row.startswith("/"):
                break
            out.append(tuple(float(v) for v in row.split()))
        return out

    def _imptemp(self, starter):
        lines = starter.splitlines()
        i = next(j for j, l in enumerate(lines)
                 if l.startswith("/IMPTEMP/")
                 and lines[j + 1].startswith("tgmult_generation_"))
        fid, sens, gid = (int(v) for v in lines[i + 3].split())
        return fid, sens, gid

    def test_the_closed_form_is_emitted_over_the_parts_own_nodes(self):
        """TGMULT 10 / RHO0_CP 1 / T0 10 / ENDTIM 3 -> T(3) = 40."""
        result, starter, _e = _convert(_thermal_deck())
        self.assertIn("/IMPTEMP/", starter)
        fid, sens, gid = self._imptemp(starter)
        self.assertEqual(sens, 0)
        self.assertEqual(self._funct_pts(starter, fid),
                         [(0.0, 10.0), (3.0, 40.0)])
        lines = starter.splitlines()
        i = lines.index(f"/GRNOD/NODE/{gid}")
        members = [int(v) for v in lines[i + 2].split()]
        self.assertEqual(sorted(members), list(range(1, 9)))
        self.assertTrue(_has(result.warnings, "TGMULT=10",
                             "--no-tgmult-imptemp"))

    def test_rho_cp_divides(self):
        """``hm_read_therm.F:244`` stores ``RHO0_CP`` verbatim in ``PM(69)``;
        the closed form divides by it."""
        _r, starter, _e = _convert(_thermal_deck(hc=2.0, tro=2.0))   # rho*Cp = 4
        fid, _s, _g = self._imptemp(starter)
        self.assertEqual(self._funct_pts(starter, fid),
                         [(0.0, 10.0), (3.0, 10.0 + 3.0 * 10.0 / 4.0)])

    def test_tgrlc_is_INTEGRATED_on_its_own_abscissae(self):
        """TGMULT is a RATE (Vol II R17 p.3-2: ``TGRLC`` GT.0 gives the
        "thermal generation rate as a function of time", ``TGMULT`` is the
        "thermal generation rate multiplier"), so the adiabatic body obeys
        ``rho*Cp*dT/dt = TGMULT*f(t)`` and the temperature is the curve's
        running TIME INTEGRAL.

        A direct map ``T0 + rate*f(t)`` shipped here and is what this test
        used to pin: on this very curve it asserted ``(1, 30) -> (3, 20)`` — a
        temperature FALLING while a strictly positive generation is still
        running. With ``rate = TGMULT/(rho*Cp) = 10`` and ``f`` the trapezoid
        of ``(0,0) (1,2) (3,1)``: ``INTEGRAL = 0, 1, 4`` so ``T = 10, 20, 50``.
        """
        curve = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + "".join(f"{x:>20.10G}{y:>20.10G}\n"
                           for x, y in ((0.0, 0.0), (1.0, 2.0), (3.0, 1.0))))
        _r, starter, _e = _convert(_thermal_deck(tgrlc=5, extra=curve))
        fid, _s, _g = self._imptemp(starter)
        self.assertEqual(self._funct_pts(starter, fid),
                         [(0.0, 10.0), (1.0, 20.0), (3.0, 50.0)])

    def test_a_strictly_positive_generation_never_cools(self):
        """The property the old law broke: while ``f > 0`` the temperature is
        strictly increasing, whatever shape the curve has."""
        pts = ((0.0, 5.0), (1.0, 2.0), (2.0, 9.0), (4.0, 0.5))
        curve = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + "".join(f"{x:>20.10G}{y:>20.10G}\n" for x, y in pts))
        _r, starter, _e = _convert(_thermal_deck(tgrlc=5, extra=curve))
        fid, _s, _g = self._imptemp(starter)
        got = self._funct_pts(starter, fid)
        self.assertEqual([t for t, _v in got], [0.0, 1.0, 2.0, 4.0])
        temps = [v for _t, v in got]
        for a, b in zip(temps, temps[1:]):
            self.assertGreater(b, a)
        # trapezoid: 0, 3.5, 9.0, 18.5 -> T0 + 10 * that
        self.assertEqual(temps, [10.0, 45.0, 100.0, 195.0])

    def test_a_curve_that_starts_after_zero_is_integrated_from_zero(self):
        """LS-DYNA holds a load curve's endpoint value outside its range, so a
        curve beginning at ``t = 1`` has been generating at its first ordinate
        since ``t = 0``; the synthesized origin sample carries that."""
        curve = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + "".join(f"{x:>20.10G}{y:>20.10G}\n"
                           for x, y in ((1.0, 2.0), (3.0, 2.0))))
        _r, starter, _e = _convert(_thermal_deck(tgrlc=5, extra=curve))
        fid, _s, _g = self._imptemp(starter)
        # f == 2 throughout, so T = 10 + 10*2*t
        self.assertEqual(self._funct_pts(starter, fid),
                         [(0.0, 10.0), (1.0, 30.0), (3.0, 70.0)])

    def test_a_negative_tgrlc_is_refused_by_name(self):
        """``|TGRLC|`` is rate against TEMPERATURE (Vol II R17 p.3-2 LT.0), a
        nonlinear ODE the closed form does not solve."""
        curve = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + "".join(f"{x:>20.10G}{y:>20.10G}\n"
                           for x, y in ((0.0, 1.0), (100.0, 2.0))))
        result, starter, _e = _convert(_thermal_deck(tgrlc=-5, extra=curve))
        self.assertNotIn("tgmult_generation_", starter)
        self.assertTrue(_has(result.warnings, "TGRLC=-5", "NEGATIVE",
                             "against TEMPERATURE"))

    def test_a_zero_tgmult_emits_nothing(self):
        _r, starter, _e = _convert(_thermal_deck(tgmult=0.0))
        self.assertNotIn("tgmult_generation_", starter)

    def test_the_opt_out_reproduces_the_pre_round_4_drop(self):
        result, starter, _e = _convert(_thermal_deck(), tgmult_imptemp=False)
        self.assertNotIn("tgmult_generation_", starter)
        self.assertTrue(_has(result.warnings, "TGMULT dropped"))


class TgmultRefusalTests(unittest.TestCase):
    """The gate is the half that matters.

    ``/IMPTEMP`` is a HARD Dirichlet reset applied to every node in its group
    on every cycle (``fixtemp.F:180-199``, the writes at ``:187`` and
    ``:198``), so on a deck with a real thermal boundary condition it would
    OVERWRITE the solution those cards drive instead of adding to it.
    """

    _DRIVERS = {
        "*BOUNDARY_TEMPERATURE_SET":
            "*BOUNDARY_TEMPERATURE_SET\n" + _row(1, 0, 400.0) + "\n"
            "*SET_NODE_LIST\n" + _row(1) + "\n" + _row(1, 2) + "\n",
        "*BOUNDARY_CONVECTION_SET":
            "*BOUNDARY_CONVECTION_SET\n" + _row(1) + "\n"
            + _row(0, 100.0) + "\n" + _row(0, 300.0) + "\n"
            "*SET_SEGMENT\n" + _row(1) + "\n" + _row(1, 2, 3, 4) + "\n",
        "*BOUNDARY_FLUX_SET":
            "*BOUNDARY_FLUX_SET\n" + _row(1) + "\n"
            + _row(0, 1.0, 1.0, 1.0, 1.0) + "\n"
            "*SET_SEGMENT\n" + _row(1) + "\n" + _row(1, 2, 3, 4) + "\n",
        "*BOUNDARY_RADIATION_SET":
            "*BOUNDARY_RADIATION_SET\n" + _row(1, 1) + "\n"
            + _row(0, 1.0, 0, 300.0) + "\n"
            "*SET_SEGMENT\n" + _row(1) + "\n" + _row(1, 2, 3, 4) + "\n",
        # UNPARSED by k2rad — it reaches no handler and lands in
        # skipped_keywords with no warning of its own. Screening only the
        # RESOLVED driver registries would be a filter keyed on a field these
        # records do not have, and this is the closest thing LS-DYNA has to a
        # second volumetric generation.
        "*LOAD_HEAT_GENERATION_SOLID":
            "*LOAD_HEAT_GENERATION_SOLID\n" + _row(1, 1, 1.0) + "\n",
    }

    def test_every_named_driver_blocks_the_synthesis(self):
        for name, extra in self._DRIVERS.items():
            with self.subTest(driver=name):
                result, starter, _e = _convert(_thermal_deck(extra=extra))
                self.assertNotIn("tgmult_generation_", starter)
                self.assertTrue(
                    _has(result.warnings, "TGMULT=10", "DROPPED",
                         "fixtemp.F:180-199"),
                    f"no refusal naming {name}: {result.warnings}")

    def test_a_blocked_deck_keeps_its_own_imptemp(self):
        """The refusal must drop the SYNTHESIZED card, never the deck's."""
        extra = self._DRIVERS["*BOUNDARY_TEMPERATURE_SET"]
        _r, starter, _e = _convert(_thermal_deck(extra=extra))
        self.assertIn("/IMPTEMP/", starter)
        self.assertIn("imposed_temperature_", starter)
        self.assertNotIn("tgmult_generation_", starter)

    def test_INITIAL_TEMPERATURE_is_not_a_blocker(self):
        """It is the ``T0`` of the closed form, a required companion. A gate
        written as "drop whenever any thermal card exists" excludes the rule's
        own only corpus carrier."""
        _r, starter, _e = _convert(_thermal_deck())
        self.assertIn("tgmult_generation_", starter)
        self.assertIn("/INITEMP/", starter)

    def test_two_distinct_initial_temperatures_refuse(self):
        extra = ("*SET_NODE_LIST\n" + _row(9) + "\n" + _row(1, 2) + "\n"
                 "*INITIAL_TEMPERATURE_SET\n" + _row(9, 99.0) + "\n")
        result, starter, _e = _convert(_thermal_deck(extra=extra))
        self.assertNotIn("tgmult_generation_", starter)
        self.assertTrue(_has(result.warnings, "MORE THAN ONE",
                             "*INITIAL_TEMPERATURE"))

    def test_LOAD_THERMAL_is_inert_on_a_COUPLED_deck_and_does_not_block(self):
        """Vol I R17 p.33-162, the family's own head page: *"Nodal temperatures
        defined by the \\*LOAD_THERMAL_OPTION method are all applied in a
        structural only analysis. They are IGNORED in a thermal only or coupled
        thermal/structural analysis."*

        TGMULT only acts on a deck that runs a thermal solve, i.e. SOLN 1 or 2
        — exactly the analyses where LS-DYNA itself ignores
        ``*LOAD_THERMAL_*``. k2rad drops those records for the same reason
        (``_drop_load_thermal_on_thermal_soln``), so a card that does nothing
        in EITHER code must not be allowed to veto a restatement.
        """
        extra = "*LOAD_THERMAL_CONSTANT\n" + _row(0) + "\n" + _row(400.0) + "\n"
        _r, starter, _e = _convert(_thermal_deck(extra=extra))
        self.assertIn("tgmult_generation_", starter)

    def test_a_zero_rho_cp_refuses_instead_of_dividing(self):
        result, starter, _e = _convert(_thermal_deck(hc=0.0))
        self.assertNotIn("tgmult_generation_", starter)
        self.assertTrue(_has(result.warnings, "TGMULT=10", "DIVIDES by it"))


# ═════════════════════════════════════════════════════════════════════════════
# A5 — warnings only
# ═════════════════════════════════════════════════════════════════════════════

class AssumedStrainElformWarningTests(unittest.TestCase):
    """``ELFORM -1/-2/3`` land on ``Isolid`` 17 through ``_elform_to_isolid``'s
    ``.get`` default and STAY there — ``_ONE_POINT_SOLID_ELFORMS`` keeps them
    out of round 3's hourglass remap — so the warning is the only thing that
    distinguishes them from an ELFORM 2 in the converted deck.

    ``ex_03_solid_elform_{-1,2,18}`` really do share a byte-identical
    ``_0000.rad``.
    """

    def _solid_deck(self, elform):
        return ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                + _BRICK + _MAT_SEC.replace("%ELFORM%", str(elform))
                + "*END\n")

    def test_it_fires_on_minus_1_and_minus_2(self):
        for elform in (-1, -2):
            with self.subTest(elform=elform):
                result, _s, _e = _convert(self._solid_deck(elform))
                self.assertTrue(
                    _has(result.warnings, f"ELFORM {elform}",
                         "ASSUMED-STRAIN", "p.41-104 Remark 13"),
                    result.warnings)

    def test_it_fires_on_elform_3_with_its_own_text(self):
        result, _s, _e = _convert(self._solid_deck(3))
        self.assertTrue(_has(result.warnings, "ELFORM 3",
                             "FULLY INTEGRATED", "-99.65 %"), result.warnings)

    def test_it_does_NOT_fire_on_elform_2(self):
        result, _s, _e = _convert(self._solid_deck(2))
        self.assertFalse(any("ASSUMED-STRAIN" in w for w in result.warnings),
                         result.warnings)

    def test_it_does_NOT_fire_on_a_1_point_elform(self):
        """ELFORM 1 gets the round-3 default-hourglass remap and leaves 17."""
        result, _s, starter = _convert(self._solid_deck(1))
        self.assertFalse(any("ASSUMED-STRAIN" in w for w in result.warnings),
                         result.warnings)

    def test_it_fires_ONCE_per_section_not_per_part(self):
        deck = self._solid_deck(-1).replace(
            "*PART\nbrick\n" + _row(1, 1, 1) + "\n",
            "*PART\nbrick\n" + _row(1, 1, 1) + "\n"
            "second\n" + _row(2, 1, 1) + "\n")
        result, _s, _e = _convert(deck)
        hits = [w for w in result.warnings if "ASSUMED-STRAIN" in w]
        self.assertEqual(len(hits), 1, hits)

    def test_it_fires_from_the_PER_PART_SPLIT_property_too(self):
        """There are TWO ``/PROP/SOLID`` emission sites and the warning has to
        be called from BOTH.

        When a ``*PART`` carries its own ``*HOURGLASS`` the section is split
        out into a per-part ``/PROP/SOLID`` and the shared-section emitter
        never runs for it — on
        ``ex_27_solid_elform_-2_rigidwall`` the split ``/PROP/SOLID/90001`` at
        ``Isolid 17`` is the ONLY solid property in the whole file, so a hook
        on the shared path alone was silent on a real carrier (found by
        converting the corpus, not by reading the code).
        """
        # ex_27's own shape, verbatim: a per-part *HOURGLASS at IHQ 0 / QM 0.0
        # and no *CONTROL_HOURGLASS at all, so the part is split out and its
        # split property stays on the ELFORM-derived Isolid 17 — which is
        # exactly the case the warning exists for.
        deck = self._solid_deck(-2).replace(
            "*PART\nbrick\n" + _row(1, 1, 1) + "\n",
            "*HOURGLASS\n" + _row(7, 0, 0.0) + "\n"
            "*PART\nbrick\n" + _row(1, 1, 1, 0, 7) + "\n")
        result, starter, _e = _convert(deck)
        self.assertIn("HG_PROP_", starter)          # the split really happened
        lines = starter.splitlines()
        i = next(j for j, l in enumerate(lines)
                 if l.startswith("/PROP/SOLID/") and "HG_PROP_" in lines[j + 1])
        self.assertEqual(int(lines[i + 3].split()[0]), 17)   # …and stayed at 17
        self.assertTrue(_has(result.warnings, "ELFORM -2", "ASSUMED-STRAIN"),
                        result.warnings)

    def test_the_Isolid_24_split_gets_its_OWN_sentence_not_the_17_one(self):
        """The predicate is the EMITTED ``Isolid``, not the ELFORM — and
        round 5 changed what the 24 arm is told.

        Round 4 shipped SILENCE here, on the reading that an ``*HOURGLASS``
        remap to 24 gives a DIFFERENT element and the 17 sentence's premise
        (that ``Isolid`` 17 is the locking ELFORM-2 hex) is false there. That
        half is still true and still asserted below. What was wrong was the
        conclusion: ROADMAP item 16 is CLOSED in the opposite direction — an
        8-point assumed-strain element becoming a 1-POINT HEPH is a
        substitution of its own, simply the SMALLEST measured one (a bending
        coupon reads −2.9 % at 24 against −28.8 % at 17), so the user is told
        about it in a sentence of its own instead of being told nothing.
        ``ex_12_solid_elform_{-1,-2}`` is the corpus carrier of that shape."""
        deck = self._solid_deck(-1).replace(
            "*PART\nbrick\n" + _row(1, 1, 1) + "\n",
            "*HOURGLASS\n" + _row(7, 6, 0.05) + "\n"
            "*PART\nbrick\n" + _row(1, 1, 1, 0, 7) + "\n")
        result, starter, _e = _convert(deck)
        lines = starter.splitlines()
        i = next(j for j, l in enumerate(lines) if l.startswith("/PROP/SOLID/"))
        self.assertEqual(int(lines[i + 3].split()[0]), 24)
        hits = [w for w in result.warnings if "ASSUMED-STRAIN" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        # the 24 sentence, not the 17 one
        self.assertIn("lands on Isolid 24", hits[0])
        self.assertIn("*HOURGLASS IHQ 6 overlay", hits[0])
        self.assertNotIn("Isolid 17 IS the locking", hits[0])

    def test_elform_2_still_maps_to_isolid_17_EXPLICITLY(self):
        """``_elform_to_isolid``'s ``2: 17`` entry must never ride the ``.get``
        default: ELFORM 2 IS the fully-integrated hex 17 reproduces, and the
        three ELFORMs this warning names are the ones that are NOT."""
        import inspect
        from k2rad.writer.common import _elform_to_isolid
        src = inspect.getsource(_elform_to_isolid)
        self.assertIn("2: 17", src)
        self.assertEqual(_elform_to_isolid(2), 17)


class InitialVoidInFsiWarningTests(unittest.TestCase):
    """An ``*INITIAL_VOID_*`` part that IS the ALE fluid group of an emitted
    ``/INTER/TYPE18``: the region LS-DYNA empties converts as ORDINARY FLUID.

    The predicate is the INTERSECTION, not the presence of either card.
    ``bird-el.k`` (a void with no coupling) and ``quadrature_A.k`` (a coupling
    with no void, carrying the SAME ``vy = -5000``) are the two controls.
    """

    def _ale_deck(self, void_pid=None, coupling=True):
        nodes = _NODES + [(2, 0, 0), (2, 1, 0), (2, 0, 1), (2, 1, 1)]
        deck = ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                          for i, (x, y, z) in enumerate(nodes, start=1))
                + "*ELEMENT_SOLID\n"
                  "       1       1       1       2       3       4       5       6       7       8\n"
                  "       2       2       2       9      10       3       6      11      12       7\n"
                  "*PART\n"
                  "fluid\n" + _row(1, 1, 1) + "\n"
                  "struct\n" + _row(2, 2, 1) + "\n"
                  "*SECTION_SOLID\n" + _row(1, 11) + "\n"
                  "*SECTION_SOLID\n" + _row(2, 1) + "\n"
                  "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n")
        if coupling:
            deck += ("*CONSTRAINED_LAGRANGE_IN_SOLID\n"
                     + _row(2, 1, 1, 1, 1, 4, 2, 1) + "\n"
                     + _row(0.0, 0.0, 0.1, 0.0) + "\n")
        if void_pid is not None:
            deck += "*INITIAL_VOID_PART\n" + _row(void_pid) + "\n"
        return deck + "*END\n"

    def test_it_fires_when_the_void_IS_the_coupled_fluid_group(self):
        result, _s, _e = _convert(self._ale_deck(void_pid=1))
        self.assertTrue(_has(result.warnings, "*INITIAL_VOID_PART 1",
                             "NOT VALID", "quadrature_B"), result.warnings)

    def test_it_does_NOT_fire_on_a_void_with_no_coupling(self):
        result, _s, _e = _convert(self._ale_deck(void_pid=1, coupling=False))
        self.assertFalse(any("NOT VALID" in w for w in result.warnings),
                         result.warnings)

    def test_it_does_NOT_fire_on_a_coupling_with_no_void(self):
        result, _s, _e = _convert(self._ale_deck(void_pid=None))
        self.assertFalse(any("INITIAL_VOID" in w for w in result.warnings),
                         result.warnings)

    def test_it_does_NOT_fire_when_the_void_is_the_LAGRANGIAN_side(self):
        result, _s, _e = _convert(self._ale_deck(void_pid=2))
        self.assertFalse(any("NOT VALID" in w for w in result.warnings),
                         result.warnings)

    def test_the_keyword_is_registered_but_still_listed_as_skipped(self):
        """Registering a handler normally REMOVES the ``#-- SKIPPED:`` line
        from the starter. This item adds a warning and not one byte, so the
        keyword stays in the skipped list — where it belongs, because the card
        really is not converted."""
        self.assertIn("INITIAL_VOID_PART", HANDLERS)
        self.assertIn("INITIAL_VOID_SET", HANDLERS)
        result, starter, _e = _convert(self._ale_deck(void_pid=1))
        self.assertIn("INITIAL_VOID_PART", result.skipped_keywords)
        self.assertIn("#-- SKIPPED: *INITIAL_VOID_PART", starter)


class ClisDroppedCellsWarningTests(unittest.TestCase):
    """``*CONSTRAINED_LAGRANGE_IN_SOLID``: eight cells unparsed, two parsed and
    never read.

    The corpus carries the controlled experiment: ``quadrature_B`` and
    ``quadrature_C`` differ in EXACTLY one cell (``NQUAD`` 1 vs 3) and convert
    to byte-identical files.
    """

    def test_it_names_every_dropped_cell_and_the_constant_stiffness(self):
        deck = InitialVoidInFsiWarningTests()._ale_deck(void_pid=None)
        result, _s, _e = _convert(deck)
        w = next((x for x in result.warnings if "NOT PARSED" in x), None)
        self.assertIsNotNone(w, result.warnings)
        for cell in ("NQUAD", "DIREC", "MCOUP", "FRCMIN", "NORM", "DAMP",
                     "ILEAK", "PLEAK"):
            self.assertIn(cell, w)
        self.assertIn("CTYPE=4", w)
        self.assertIn("Stfval = 1.0", w)
        self.assertIn("quadrature_C", w)

    def test_it_does_NOT_fire_on_a_deck_with_no_coupling(self):
        deck = InitialVoidInFsiWarningTests()._ale_deck(coupling=False)
        result, _s, _e = _convert(deck)
        self.assertFalse(any("NOT PARSED" in w for w in result.warnings))


class ImplicitAutoDroppedCellsWarningTests(unittest.TestCase):
    """``*CONTROL_IMPLICIT_AUTO``: ``IAUTO``/``ITEWIN``/``KFAIL`` parsed and
    unused, and a NEGATIVE ``DTMAX`` dropped outright.

    ``assembly`` reads ``ITEOPT`` (into ``/IMPL/DT/2`` ``It_w``) and
    ``DTMIN``/``DTMAX`` (into ``/IMPL/DT/STOP``) and nothing else. A negative
    ``DTMAX`` is LS-DYNA's "this is a load-curve id" idiom, and
    ``/IMPL/DT/STOP`` takes a constant.
    """

    #: IAUTO ITEOPT ITEWIN DTMIN DTMAX (field 6 blank) KFAIL
    def test_the_unused_cells_are_named_with_their_values(self):
        result, _s, _e = _convert(
            _implicit_deck(auto=(1, 11, 5, 0.0, 0.0, 0, 0)))
        self.assertTrue(_has(result.warnings, "IAUTO=1", "ITEWIN=5",
                             "parsed and NOT used"), result.warnings)

    def test_a_negative_dtmax_is_named_as_a_LOAD_CURVE_id(self):
        result, _s, _e = _convert(
            _implicit_deck(auto=(1, 11, 5, 0.0, -901.0, 0, 0)))
        self.assertTrue(_has(result.warnings, "DTMAX=-901",
                             "LOAD CURVE id", "UNBOUNDED"), result.warnings)

    def test_kfail_is_named_when_a_deck_states_it(self):
        """Zero carriers on the R14 roster, so this is the only place the
        branch is exercised at all."""
        result, _s, _e = _convert(
            _implicit_deck(auto=(0, 11, 0, 0.0, 0.0, 0, 4)))
        self.assertTrue(_has(result.warnings, "KFAIL=4"), result.warnings)

    def test_IAUTO_0_is_NAMED_as_the_constant_step_LS_DYNA_asks_for(self):
        """Successor to ``test_it_does_NOT_fire_on_a_card_that_states_none_of
        _them``, which asserted silence on exactly the card where the
        substitution is LARGEST.

        Vol I R17 p.12-277: ``IAUTO EQ.0: Constant time step size`` — and that
        is the card's own default, so a blank field says the same thing
        (MISTAKES #136: a value the deck omits still has a solver default and
        the default can be load-bearing). k2rad writes ``/IMPL/DT/2``,
        AUTOMATIC step control, on every implicit deck regardless. 11 of the
        356 roster keys state or blank ``IAUTO = 0``, ``tensile2`` and the
        whole ``ex_14_solid_elform_*`` family among them.
        """
        result, _s, _e = _convert(
            _implicit_deck(auto=(0, 11, 0, 0.0, 0.001, 0, 0)))
        self.assertTrue(_has(result.warnings, "*CONTROL_IMPLICIT_AUTO:",
                             "IAUTO=0", "Constant time step size",
                             "p.12-277", "AUTOMATIC step control"),
                        result.warnings)
        # ...and the cells this deck really does leave blank are NOT named.
        hit = [w for w in result.warnings if "*CONTROL_IMPLICIT_AUTO:" in w][0]
        self.assertNotIn("ITEWIN", hit)
        self.assertNotIn("KFAIL", hit)

    def test_a_NEGATIVE_IAUTO_gets_the_load_curve_gloss(self):
        """p.12-277 ``IAUTO LT.0: Curve ID = (-IAUTO) gives time step size as a
        function of time`` — the same idiom ``DTMAX < 0`` already had spelled
        out, where the truthiness filter used to print a generic
        "auto-step on/off switch" gloss instead. 0 roster carriers."""
        result, _s, _e = _convert(
            _implicit_deck(auto=(-77, 11, 0, 0.0, 0.0, 0, 0)))
        self.assertTrue(_has(result.warnings, "IAUTO=-77", "NEGATIVE",
                             "Curve ID", "DROPPED"), result.warnings)

    def test_a_MODAL_deck_is_warned_too_and_names_its_own_engine(self):
        """The two "asked for and did not get" warnings used to sit BELOW
        ``_make_engine_implicit``'s modal early return, so a ``/EIG`` deck was
        told nothing — measured on ``ex_08_beam_elform_{1,2,13}``, which state
        ``*CONTROL_IMPLICIT_AUTO`` IAUTO 1 / ITEWIN 15 beside
        ``*CONTROL_IMPLICIT_EIGENVALUE``. The modal recipe ignores those cells
        exactly as ``/IMPL/DT/2`` does, and the sentence must not name a card
        the deck will not carry."""
        result, _s, engine = _convert(
            _implicit_deck(auto=(1, 11, 15, 0.0, 0.0, 0, 0), modal=True))
        hits = [w for w in result.warnings if "*CONTROL_IMPLICIT_AUTO:" in w]
        self.assertEqual(len(hits), 1, result.warnings)
        self.assertIn("ITEWIN=15", hits[0])
        self.assertIn("no /IMPL/DT card at all", hits[0])
        self.assertNotIn("/IMPL/DT/2", hits[0])
        self.assertNotIn("/IMPL/DT/2", engine)

    def test_it_does_NOT_fire_without_the_card(self):
        result, _s, _e = _convert(_implicit_deck())
        self.assertFalse(any("*CONTROL_IMPLICIT_AUTO:" in w
                             for w in result.warnings), result.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Doc corrections — the retracted strings must be gone everywhere
# ═════════════════════════════════════════════════════════════════════════════

class RoadmapRoundFourCorrectionsTests(unittest.TestCase):
    """The four ROADMAP statements round 4 retracts, and what replaces them."""

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _roadmap(self):
        with open(os.path.join(self._ROOT, "ROADMAP.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_IHQ_8_entry_states_the_shell_warping_reading(self):
        text = self._roadmap()
        self.assertIn("full projection warping stiffness", text)
        self.assertIn("Belytschko-Bindeman", text)   # IHQ 6, named as such

    def test_the_ex_27_rigidwall_attribution_is_corrected(self):
        text = self._roadmap()
        self.assertIn("*CONSTRAINED_GLOBAL", text)
        self.assertIn("nl_solv.F:520", text)

    def test_the_tied_offset_entry_states_spotflag_27(self):
        text = self._roadmap()
        self.assertIn("Spotflag 27", text)
        self.assertIn("i24pen3.F:317-319", text)

    def test_the_stub_predicate_item_is_closed_with_the_bumper_arm(self):
        text = self._roadmap()
        self.assertIn("CLOSED in round 4", text)
        self.assertIn("auto_implicit_stabilization_self_contact", text)

    def test_the_contacts_docstring_no_longer_says_TYPE2_projects(self):
        from k2rad.writer import contacts
        import inspect
        src = inspect.getsource(contacts)
        self.assertNotIn("projects the secondary nodes", src)
        self.assertIn("_TIED_PENALTY_SPOTFLAGS", src)


# ═════════════════════════════════════════════════════════════════════════════
# B1 — *DEFORMABLE_TO_RIGID (the plain spelling)
# ═════════════════════════════════════════════════════════════════════════════

#: Two 8-node bricks on two parts, gravity over the whole model, and one
#: *CONTACT so the /INTER path is exercised too. Part 1 is the one the
#: *DEFORMABLE_TO_RIGID card names in :func:`_d2r_deck`; the *MAT_RIGID twin
#: makes the same part rigid through its MATERIAL instead, which is the
#: comparison that says "the same machinery".
_D2R_NODES = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
              (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
              (0, 0, 2), (1, 0, 2), (1, 1, 2), (0, 1, 2),
              (0, 0, 3), (1, 0, 3), (1, 1, 3), (0, 1, 3)]


def _d2r_mesh() -> str:
    return (
        "*NODE\n"
        + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                  for i, (x, y, z) in enumerate(_D2R_NODES, start=1))
        + "*ELEMENT_SOLID\n"
          "       1       1       1       2       3       4       5       6       7       8\n"
          "       2       2       9      10      11      12      13      14      15      16\n"
    )


def _d2r_deck(card="*DEFORMABLE_TO_RIGID", rows=((1, 0, "PART"),),
              mat_rigid_pid=0, gravity=True, contact=True) -> str:
    """One coupon, three arms: the D2R card, the *MAT_RIGID twin, or neither."""
    deck = "*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n" + _d2r_mesh()
    for pid in (1, 2):
        mid = 2 if pid == mat_rigid_pid else 1
        deck += f"*PART\npart {pid}\n" + _row(pid, 1, mid) + "\n"
    deck += ("*SECTION_SOLID\n" + _row(1, 1) + "\n"
             "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n")
    if mat_rigid_pid:
        deck += "*MAT_RIGID\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
    if rows and card:
        for pid, lrb, ptype in rows:
            deck += card + "\n" + f"{pid:>10}{lrb:>10}" + ptype + "\n"
    if gravity:
        deck += ("*DEFINE_CURVE\n" + _row(1) + "\n"
                 "             0.0             1.0\n"
                 "             1.0             1.0\n"
                 "*LOAD_BODY_Z\n" + _row(1, 1.0) + "\n")
    if contact:
        deck += ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
                 + _row(1, 2, 3, 3, 0, 0, 0, 0) + "\n"
                 + _row(0.2, 0.1) + "\n")
    return deck + "*END\n"


class DeformableToRigidRegistrationTests(unittest.TestCase):
    """The keyword was in NO dispatch table: `dispatch` filed it under
    ``skipped_keywords`` with no warning at all."""

    def test_the_plain_card_is_registered(self):
        self.assertIn("DEFORMABLE_TO_RIGID", HANDLERS)

    def test_it_no_longer_lands_in_skipped_keywords(self):
        result, starter, _ = _convert(_d2r_deck())
        self.assertNotIn("DEFORMABLE_TO_RIGID", result.skipped_keywords)
        self.assertNotIn("#-- SKIPPED: *DEFORMABLE_TO_RIGID", starter)

    def test_the_offset_spec_travels_the_pid_through_include_transform(self):
        from k2rad.assembly import _OFFSET_SPECS
        self.assertIn("DEFORMABLE_TO_RIGID", _OFFSET_SPECS)
        spec = _OFFSET_SPECS["DEFORMABLE_TO_RIGID"]
        self.assertEqual(spec, {"data": (0, [(0, "p"), (1, "p")])})

    def test_the_card_is_parsed_into_a_part_keyed_map(self):
        state = _dispatch(_d2r_deck())
        self.assertEqual(state.deformable_to_rigid, {1: 0})


class DeformableToRigidRbodyTests(unittest.TestCase):
    """The part becomes an /RBODY at t = 0, through the *MAT_RIGID path."""

    def setUp(self):
        self.result, self.starter, _ = _convert(_d2r_deck())

    def test_an_rbody_is_emitted_over_the_named_part(self):
        self.assertIn("#-  RIGID BODIES:", self.starter)
        lines = self.starter.splitlines()
        i = lines.index("rb_nodes_pid1")
        self.assertEqual(lines[i + 1].split(),
                         ["1", "2", "3", "4", "5", "6", "7", "8"])
        self.assertNotIn("rb_nodes_pid2", self.starter)

    def test_the_material_is_NOT_re_emitted_as_a_rigid_one(self):
        """The pid is recorded, not the MID: adding the MID to state.mat_rigid
        would re-title the law AND make part 2 (which shares it) rigid too."""
        self.assertNotIn("(rigid body material)", self.starter)
        state = _dispatch(_d2r_deck())
        self.assertEqual(state.mat_rigid, {})

    def test_the_warning_states_the_card_and_the_measurement(self):
        w = [x for x in self.result.warnings
             if x.startswith("*DEFORMABLE_TO_RIGID PID 1:")]
        self.assertEqual(len(w), 1, repr(self.result.warnings))
        self.assertIn("rigid FROM t = 0", w[0])
        self.assertIn("p.18-1", w[0])
        self.assertIn("hm_read_rbody.F:700-722", w[0])
        self.assertIn("5.03545e-06", w[0])         # the LS-DYNA reference
        self.assertIn("9 480", w[0])
        self.assertIn("--no-deformable-to-rigid", w[0])

    def test_the_gravity_scope_sees_the_new_rigid_body(self):
        """The arm this guards was MEASURED: an /RBODY the /GRAV group builder
        does not see makes pend.imp a 0.000 / 0.000 zero model at 9 480 NORMAL
        cycles, because rgbodv.F overwrites a rigid secondary's acceleration."""
        lines = self.starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/PART/"))
        self.assertEqual(lines[i + 2].split(), ["2"])   # part 1 is gone
        self.assertIn("body_load_rbody_mains_", self.starter)
        self.assertIn("/GRNOD/GRNOD/", self.starter)

    def test_the_mat_rigid_twin_emits_the_same_rigid_body_section(self):
        _, twin, _ = _convert(_d2r_deck(card="", rows=(), mat_rigid_pid=1))

        def section(text):
            ls = text.splitlines()
            a = ls.index("#-  RIGID BODIES:")
            b = next(k for k in range(a + 1, len(ls))
                     if ls[k].startswith("#-  ") and k > a)
            return [ln for ln in ls[a:b] if not ln.startswith("part ")]

        self.assertEqual(section(self.starter), section(twin))


    def test_a_LOCAL_prescribed_motion_gets_its_co_rotating_triad(self):
        """``_synthesize_local_motion_frames`` builds the /SKEW/MOV triad only
        for a part it considers RIGID. On ``state.mat_rigid`` alone a
        *DEFORMABLE_TO_RIGID part is skipped, the motion falls back to the
        GLOBAL axes and the error grows as cos(theta(t)) — the same silence the
        /GRAV re-point had. Reach on the corpus: 0 decks combine the two, so
        this is the predicate's pin, not a live carrier."""
        deck = (_d2r_deck(gravity=False, contact=False).replace("*END@", "")
                + "*DEFINE_CURVE@" + _row(1) + "@"
                  "             0.0             0.0@"
                  "             1.0             1.0@"
                + "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL@"
                + _row(1, 1, 2, 1, 1.0) + "@*END@").replace("@", "\n")
        result, starter, _ = _convert(deck)
        self.assertIn("/SKEW/MOV/", starter)
        self.assertTrue(_has(result.warnings,
                             "*BOUNDARY_PRESCRIBED_MOTION_RIGID_LOCAL pid=1",
                             "CO-ROTATING"))


    def test_a_reference_geometry_on_the_part_is_skipped_by_name(self):
        """``writer/inistate``'s ``/XREF`` screen asks the same PART question.
        On ``state.mat_rigid`` alone a *DEFORMABLE_TO_RIGID part would take a
        stress-free reference geometry it has no strain state for, and would
        drag its whole *SECTION_SOLID to ``Ismstr = 10`` with it. Corpus reach:
        0 decks combine the two — this is the predicate's pin."""
        coords = ((1, 0.0, 0.0, 0.0), (2, 0.9, 0.0, 0.0), (3, 0.9, 0.9, 0.0),
                  (4, 0.0, 0.9, 0.0), (5, 0.0, 0.0, 0.9), (6, 0.9, 0.0, 0.9),
                  (7, 0.9, 0.9, 0.9), (8, 0.0, 0.9, 0.9))
        xref = ("*INITIAL_FOAM_REFERENCE_GEOMETRY@"
                + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}@"
                          for n, x, y, z in coords))
        deck = (_d2r_deck(gravity=False, contact=False).replace("*END@", "")
                + xref + "*END@").replace("@", "\n")
        result, starter, _ = _convert(deck)
        self.assertNotIn("/XREF/", starter)
        self.assertTrue(_has(result.warnings,
                             "*INITIAL_FOAM_REFERENCE_GEOMETRY",
                             "*DEFORMABLE_TO_RIGID part",
                             "keeps its own deformable law"),
                        repr(result.warnings))


class DeformableToRigidOptOutTests(unittest.TestCase):

    def setUp(self):
        self.result, self.starter, _ = _convert(
            _d2r_deck(), deformable_to_rigid=False)

    def test_no_rbody_is_emitted(self):
        self.assertNotIn("#-  RIGID BODIES:", self.starter)

    def test_the_loss_is_warned_and_accounted(self):
        self.assertTrue(_has(self.result.warnings,
                             "--no-deformable-to-rigid", "[1]"))
        self.assertIn("DEFORMABLE_TO_RIGID",
                      dict(self.result.recognized_not_emitted))

    def test_the_parser_still_records_the_card(self):
        """The option is honoured in the WRITER, so every later screen sees the
        same parsed state whichever way the flag is set."""
        state = _dispatch(_d2r_deck())
        self.assertEqual(state.deformable_to_rigid, {1: 0})


class DeformableToRigidRefusalTests(unittest.TestCase):
    """The run-time-triggered spellings are refused BY NAME, with the Radioss
    mechanism that would be needed spelled out."""

    def _arm(self, card):
        return _convert(_d2r_deck(card=card))

    def test_automatic_is_refused_by_name(self):
        result, starter, _ = self._arm("*DEFORMABLE_TO_RIGID_AUTOMATIC")
        self.assertNotIn("#-  RIGID BODIES:", starter)
        self.assertTrue(_has(result.warnings,
                             "*DEFORMABLE_TO_RIGID_AUTOMATIC",
                             "/SENSOR/TIME", "hm_read_rbody.F:363-388",
                             "rbyonf.F:331/399"))
        self.assertIn("DEFORMABLE_TO_RIGID_AUTOMATIC",
                      dict(result.recognized_not_emitted))

    def test_inertia_names_part_inertia_as_the_supported_route(self):
        result, _, _ = self._arm("*DEFORMABLE_TO_RIGID_INERTIA")
        self.assertTrue(_has(result.warnings,
                             "*DEFORMABLE_TO_RIGID_INERTIA", "*PART_INERTIA"))

    def test_rigid_deformable_is_refused_through_the_prefix(self):
        for spelling in ("*RIGID_DEFORMABLE_CONTROL", "*RIGID_DEFORMABLE_D2R",
                         "*RIGID_DEFORMABLE_R2D"):
            with self.subTest(spelling=spelling):
                result, starter, _ = self._arm(spelling)
                self.assertNotIn("#-  RIGID BODIES:", starter)
                self.assertTrue(_has(result.warnings, spelling, "/SENSOR/TIME"))

    def test_pset_is_refused_with_the_offset_caveat(self):
        result, starter, _ = _convert(
            _d2r_deck(rows=((77, 0, "PSET"),)))
        self.assertNotIn("#-  RIGID BODIES:", starter)
        self.assertTrue(_has(result.warnings, "PTYPE=PSET",
                             "*INCLUDE_TRANSFORM"))


class DeformableToRigidLrbTests(unittest.TestCase):
    """LRB folds through the SAME union-find *CONSTRAINED_RIGID_BODIES uses."""

    def test_lrb_merges_the_two_parts_into_one_rbody(self):
        result, starter, _ = _convert(
            _d2r_deck(rows=((1, 0, "PART"), (2, 1, "PART"))))
        self.assertEqual(starter.count("/RBODY/"), 1)
        lines = starter.splitlines()
        i = lines.index("rb_nodes_pid1")
        self.assertEqual(len(lines[i + 1].split() + lines[i + 2].split()), 16)

    def test_lrb_naming_a_deformable_part_is_warned_and_dropped(self):
        result, starter, _ = _convert(
            _d2r_deck(rows=((1, 2, "PART"),)))
        self.assertTrue(_has(result.warnings, "*DEFORMABLE_TO_RIGID LRB (2,1)",
                             "merge skipped"))


class RigidPartPredicateTests(unittest.TestCase):
    """ONE predicate, and every part-level consumer tests it."""

    def test_it_covers_both_routes(self):
        from k2rad.writer.common import rigid_part_ids
        self.assertEqual(rigid_part_ids(_dispatch(_d2r_deck())), {1})
        twin = _dispatch(_d2r_deck(card="", rows=(), mat_rigid_pid=1))
        self.assertEqual(rigid_part_ids(twin), {1})
        plain = _dispatch(_d2r_deck(card="", rows=()))
        self.assertEqual(rigid_part_ids(plain), set())

    #: Module -> how many times it must CALL the one predicate. Counting the
    #: calls, not the import, is what makes this a pin: a revert to
    #: ``part.mid in state.mat_rigid`` leaves the import untouched and only the
    #: call site disappears. ``rbody.py`` is absent on purpose — ``_make_rbodies``
    #: needs the two halves separately (it carries the LRB map into the merge
    #: union-find) and spells the union out, which the source scan above
    #: allowlists BY NAME.
    _PREDICATE_CALLS = {
        "contacts.py": 2,     # _side_has_deformable_part, all_deformable_nodes
        "loads.py": 2,        # the _LOCAL triads, the *DAMPING_GLOBAL scope
        "inistate.py": 1,     # the /XREF skip
        "composites.py": 1,   # the *INTEGRATION_SHELL layup drop
    }

    def test_every_part_level_consumer_calls_the_predicate(self):
        """Two mutations that reverted a consumer to ``state.mat_rigid`` ran the
        WHOLE suite green, because the consumers they hit have no corpus carrier
        that combines *DEFORMABLE_TO_RIGID with their own keyword. The functional
        pins for those two are above; this counts the call sites, so a revert
        anywhere in the list fails even where no deck exercises it."""
        import os as _os
        for base, n in sorted(self._PREDICATE_CALLS.items()):
            with self.subTest(module=base):
                path = _os.path.join(self._ROOT, "k2rad", "writer", base)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                self.assertEqual(text.count("rigid_part_ids(state)"), n,
                                 f"{base} must call writer.common."
                                 f"rigid_part_ids {n} time(s)")


    def test_no_writer_module_answers_the_part_question_from_mat_rigid(self):
        """A consumer left on ``state.mat_rigid`` alone is the defect. The
        MATERIAL registries may still use it (they answer a MID question), so
        the scan is for the PART-level shape ``parts[...].mid in mat_rigid``."""
        import glob
        import os as _os
        import re as _re
        root = _os.path.join(self._ROOT, "k2rad", "writer")
        # Matched over the WHOLE file, not line by line: the shape a revert
        # takes is usually WRAPPED across two lines
        # (`state.parts.items()` / `if part.mid in state.mat_rigid`), which a
        # per-line scan misses entirely — a mutation that reverted
        # writer/loads._synthesize_local_motion_frames to exactly that shape
        # stayed GREEN against the first version of this test.
        shape = _re.compile(r"state\.parts[\s\S]{0,80}?\.mid\s+(?:not\s+)?"
                            r"in\s+state\.mat_rigid")
        # The TWO places the union is legitimately spelled out: the predicate
        # itself, and _make_rbodies, which needs the two halves separately (it
        # carries the LRB map into the merge union-find). Named, not inferred.
        allowed = {("common.py", "rigid_part_ids"), ("rbody.py", "_make_rbodies")}
        offenders = []
        for path in glob.glob(_os.path.join(root, "*.py")):
            base = _os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for m in shape.finditer(text):
                before = text[:m.start()]
                defs = _re.findall(r"^def ([A-Za-z_][A-Za-z_0-9]*)",
                                   before, _re.M)
                where = defs[-1] if defs else "<module>"
                if (base, where) in allowed:
                    continue
                offenders.append(f"{base}:{before.count(chr(10)) + 1} "
                                 f"in {where}()")
        self.assertEqual(offenders, [], "use writer.common.rigid_part_ids")

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═════════════════════════════════════════════════════════════════════════════
# B2 — the explicit all-rigid-SSID swap
# ═════════════════════════════════════════════════════════════════════════════

_RS_MESH = """\
*NODE
         1             0.0             0.0             0.0
         2            10.0             0.0             0.0
         3            10.0            10.0             0.0
         4             0.0            10.0             0.0
         5             0.0             0.0             1.0
         6            10.0             0.0             1.0
         7            10.0            10.0             1.0
         8             0.0            10.0             1.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
*PART
plate
         1         1         1
*PART
platen
         2         2         2
*SECTION_SHELL
         1        16
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85e-9    210000.0      0.3
*MAT_RIGID
         2   7.86e-9    210000.0      0.3
"""


def _rs_deck(ssid=2, msid=1, implicit=False, rcforc=False, both_rigid=False,
             keyword="*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", extra=""):
    deck = "*KEYWORD\n" + _RS_MESH
    if both_rigid:
        deck = deck.replace("         1         1         1\n",
                            "         1         1         2\n")
    if implicit:
        deck += ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n")
    if rcforc:
        deck += "*DATABASE_RCFORC\n" + _row(1.0e-4) + "\n"
    deck += (keyword + "\n" + _row(ssid, msid, 3, 3, 0, 0, 0, 0) + "\n"
             + _row(0.2, 0.1) + "\n")
    return deck + extra + "*CONTROL_TERMINATION\n" + _row(1.0) + "\n*END\n"


class RigidSecondarySwapTests(unittest.TestCase):
    """SSID wholly rigid + MSID deformable, EXPLICIT -> the roles are swapped."""

    def setUp(self):
        self.result, self.starter, _ = _convert(_rs_deck())

    def test_the_interface_survives(self):
        self.assertIn("/INTER/TYPE7/", self.starter)
        self.assertEqual(dict(self.result.recognized_not_emitted), {})

    def test_the_deformable_side_supplies_the_tracked_nodes(self):
        lines = self.starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/GRNOD/NODE/") and lines[k + 1] ==
                 "contact_slave_1")
        self.assertEqual(lines[i + 2].split(), ["1", "2", "3", "4"])
        self.assertIn("contact_master_2", self.starter)

    def test_the_warning_carries_the_rewritten_rationale(self):
        w = [x for x in self.result.warnings if "SWAPPED the roles" in x]
        self.assertEqual(len(w), 1, repr(self.result.warnings))
        self.assertIn("ASYMMETRIC node-to-segment", w[0])
        self.assertIn("p.11-10", w[0])            # the one-sided citation
        self.assertIn("CHANGES WHICH SIDE IS PENALISED", w[0].upper())
        self.assertIn("sphere1", w[0])
        self.assertIn("-1.66", w[0])
        self.assertIn("blow-mold", w[0])
        self.assertIn("--no-rigid-secondary-swap", w[0])

    def test_the_opt_out_restores_the_drop(self):
        result, starter, _ = _convert(_rs_deck(), rigid_secondary_swap=False)
        self.assertNotIn("/INTER/TYPE7/", starter)
        self.assertTrue(_has(result.warnings, "NO /INTER was emitted",
                             "--no-rigid-secondary-swap"))

    def test_a_correctly_ordered_contact_is_untouched(self):
        """The deck that was already right must not move."""
        a = _convert(_rs_deck(ssid=1, msid=2))[1]
        b = _convert(_rs_deck(ssid=1, msid=2),
                     rigid_secondary_swap=False)[1]
        self.assertEqual(a, b)


class SwappedSecondaryLabelTests(unittest.TestCase):
    """After a swap the surviving secondary nodes come from the MSID side, so
    the thinning warning must NAME that cell — calling the MSID id an ``ssid``
    sends the reader to the wrong column of the *CONTACT card (#131's label
    class). MEASURED carrier: Ryan_Lee ``W2_Door_Impact``, where 66 of 1545,
    97 of 2439, 13 of 379 and 18 of 927 MSID nodes are rigid.
    """

    _SET = "*SET_PART_LIST@       200@         1         2@"

    def _deck(self, ssid, msid, sstyp, mstyp):
        return ("*KEYWORD@" + _RS_MESH + self._SET
                + "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE@"
                + _row(ssid, msid, sstyp, mstyp, 0, 0, 0, 0) + "@"
                + _row(0.2, 0.1) + "@"
                + "*CONTROL_TERMINATION@" + _row(1.0) + "@*END@").replace("@", "\n")

    def test_the_thinning_warning_names_the_msid_cell(self):
        """SSID = the rigid platen, MSID = a part set holding BOTH parts: the
        swap fires and the new secondary group loses the rigid half."""
        result, starter, _ = _convert(self._deck(2, 200, 3, 2))
        self.assertIn("/INTER/TYPE7/", starter)
        self.assertTrue(_has(result.warnings, "SWAPPED the roles"))
        w = [x for x in result.warnings
             if "on the SECONDARY side" in x and "belong to a rigid body" in x]
        self.assertEqual(len(w), 1, repr(result.warnings))
        self.assertIn("(msid (swapped)=200)", w[0])
        self.assertNotIn("(ssid=200)", w[0])

    def test_an_unswapped_thinning_still_says_ssid(self):
        result, _, _ = _convert(self._deck(200, 1, 2, 3))
        self.assertFalse(_has(result.warnings, "SWAPPED the roles"))
        self.assertTrue(_has(result.warnings,
                             "on the SECONDARY side (ssid=200)"))


class RigidSecondaryImplicitGateTests(unittest.TestCase):
    """An IMPLICIT deck keeps the drop, and says why with the measured arm."""

    def setUp(self):
        self.result, self.starter, _ = _convert(_rs_deck(implicit=True))

    def test_the_interface_is_still_dropped(self):
        self.assertNotIn("/INTER/TYPE7/90", self.starter.replace(
            "auto_implicit_stabilization_self_contact", ""))
        self.assertTrue(_has(self.result.warnings, "NO /INTER was emitted"))

    def test_the_drop_names_bumper_and_the_measured_divergence(self):
        """Round 5 re-measured the arm this sentence reports and renamed the
        flag it points at: the BARE swap still ERRORs at ``t = 3.0e-4``
        (ISTOP −2), but the swap WITH the derived Gapmin reaches NORMAL
        TERMINATION in 131 cycles — so the drop message now names
        ``--implicit-rigid-secondary-swap`` instead of claiming that every
        restoration arm diverges. The facts asserted here are the same ones;
        the spellings are the new text's."""
        w = [x for x in self.result.warnings if "NO /INTER was emitted" in x][0]
        self.assertIn("IMPLICIT deck", w)
        self.assertIn("bumper.k", w)
        self.assertIn("ISTOP -2", w)
        self.assertIn("nt 2 AND nt 4", w)
        self.assertIn("--implicit-rigid-secondary-swap", w)
        self.assertIn("131 cycles", w)

    def test_the_remedy_states_the_solver_accepts_rigid_nodes(self):
        w = [x for x in self.result.warnings if "NO /INTER was emitted" in x][0]
        self.assertIn("does NOT refuse /RBODY member nodes", w)
        self.assertIn("policy, not a solver constraint", w)


class RigidVsRigidKeepTests(unittest.TestCase):
    """BOTH sides wholly rigid: there is nothing to swap to, and the interface
    is emitted anyway rather than dropping a load path silently."""

    def setUp(self):
        self.result, self.starter, _ = _convert(_rs_deck(both_rigid=True))

    def test_the_interface_is_emitted_with_the_rigid_secondary(self):
        self.assertIn("/INTER/TYPE7/", self.starter)
        lines = self.starter.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if lines[k] == "contact_slave_2")
        self.assertEqual(lines[i + 1].split(), ["5", "6", "7", "8"])

    def test_the_warning_names_the_measured_inertness_and_its_cost(self):
        w = [x for x in self.result.warnings
             if "BOTH sides are wholly rigid" in x]
        self.assertEqual(len(w), 1, repr(self.result.warnings))
        self.assertIn("i7stslav.F:55-58", w[0])
        self.assertIn("mat_spring.belted-dummy", w[0])
        self.assertIn("16.5 %", w[0])
        self.assertIn("--no-rigid-secondary-swap", w[0])

    def test_the_opt_out_drops_it_again(self):
        _, starter, _ = _convert(_rs_deck(both_rigid=True),
                                 rigid_secondary_swap=False)
        self.assertNotIn("/INTER/TYPE7/", starter)


class RigidSecondaryIdStreamTests(unittest.TestCase):
    """The renumber signature, pinned — a sweep classifier has to treat every
    B2 deck as RENUMBERED, never byte- or id-compared.

    Two things move and they are independent:

    * the restored interface allocates its own ids. How MANY depends on the two
      sides' surface KINDS, not on the swap: MEASURED on
      ``intro-by-j.-day/contact/sphere/sphere1.k`` the count is unchanged (the
      dropped arm's orphaned ``/SURF/GRSHEL`` + ``/GRSHEL/SHEL`` pair becomes a
      ``/GRNOD/NODE`` + ``/SURF/PART/EXT`` pair at the same two ids, 90129 and
      90130, with only the CARD KIND changing); on a shell-vs-shell coupon the
      swapped arm allocates ONE more, because a ``/SURF/GRSHEL`` main needs two
      ids and a secondary ``/GRNOD`` only one.
    * the restored ``/TH/INTER``: ``_drop_interface`` registers the id in
      ``state.dropped_inter_ids``, which suppresses the time-history record, so
      a deck carrying ``*DATABASE_RCFORC`` gains one FURTHER id — measured on
      ``sphere1`` as ``/TH/NODE/90134 -> /TH/INTER/90134`` plus a new 90135.
    """

    @staticmethod
    def _auto_ids(text):
        import re as _re
        return [int(m.group(1)) for m in
                _re.finditer(r"^/[A-Z0-9_/]+/(9\d{4})\s*$", text, _re.M)]

    @staticmethod
    def _auto_kinds(text):
        import re as _re
        return {int(m.group(2)): m.group(1) for m in
                _re.finditer(r"^(/[A-Z0-9_/]+)/(9\d{4})\s*$", text, _re.M)}

    def test_the_card_kind_at_an_auto_id_changes(self):
        dropped = _convert(_rs_deck(), rigid_secondary_swap=False)[1]
        swapped = _convert(_rs_deck())[1]
        a, b = self._auto_kinds(dropped), self._auto_kinds(swapped)
        shared = set(a) & set(b)
        self.assertTrue(any(a[i] != b[i] for i in shared),
                        "a B2 deck must not be compared by id")

    def test_the_restored_TH_INTER_costs_one_further_id(self):
        plain_d = self._auto_ids(_convert(_rs_deck(),
                                          rigid_secondary_swap=False)[1])
        plain_s = self._auto_ids(_convert(_rs_deck())[1])
        rc_d_txt = _convert(_rs_deck(rcforc=True),
                            rigid_secondary_swap=False)[1]
        rc_s_txt = _convert(_rs_deck(rcforc=True))[1]
        self.assertNotIn("/TH/INTER/", rc_d_txt)
        self.assertIn("/TH/INTER/", rc_s_txt)
        rc_d = self._auto_ids(rc_d_txt)
        rc_s = self._auto_ids(rc_s_txt)
        self.assertEqual(len(rc_s) - len(rc_d),
                         len(plain_s) - len(plain_d) + 1)


class OneSidedSelfContactIsNotASwapSiteTests(unittest.TestCase):
    """``*CONTACT_AUTOMATIC_SINGLE_SURFACE`` with SSID != 0 names ONE side and
    uses it for both roles, so there is no second side to move to."""

    def test_the_drop_says_so_instead_of_offering_the_swap(self):
        deck = _rs_deck(ssid=2, msid=0,
                        keyword="*CONTACT_AUTOMATIC_SINGLE_SURFACE")
        result, starter, _ = _convert(deck)
        self.assertNotIn("/INTER/TYPE7/", starter)
        w = [x for x in result.warnings if "NO /INTER was emitted" in x][0]
        self.assertIn("names ONE side", w)
        self.assertIn("cannot deform", w)


class AllPartsSelfContactGuardTests(unittest.TestCase):
    """The SSID = 0 guard's two halves belong to DIFFERENT branches.

    Fusing them threw away an explicit all-rigid deck's whole /INTER/TYPE25,
    which never reads ``all_deformable_nodes`` at all — the degenerate arm of a
    more-faithful rule (measured on
    ``introduction/examples-manual/misc/defo2rigid/deformable_to_rigid.pendulum.k``,
    whose only two shell parts are exactly the two *DEFORMABLE_TO_RIGID makes
    rigid).
    """

    def _deck(self, implicit):
        deck = "*KEYWORD\n" + _RS_MESH.replace(
            "         1         1         1\n", "         1         1         2\n")
        if implicit:
            deck += "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
        deck += ("*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                 + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n" + _row(0.2, 0.1) + "\n"
                 "*CONTROL_TERMINATION\n" + _row(1.0) + "\n*END\n")
        return deck

    def test_explicit_all_rigid_keeps_its_type25_self_contact(self):
        result, starter, _ = _convert(self._deck(implicit=False))
        self.assertIn("/INTER/TYPE25/", starter)
        self.assertEqual(dict(result.recognized_not_emitted), {})

    def test_implicit_all_rigid_still_drops_the_node_to_surface_route(self):
        result, starter, _ = _convert(self._deck(implicit=True))
        w = [x for x in result.warnings if "NO /INTER was emitted" in x]
        self.assertEqual(len(w), 1, repr(result.warnings))
        self.assertIn("IMPLICIT", w[0])
        self.assertIn("no deformable nodes left", w[0])


class Type25NodesToSurfaceSwapTests(unittest.TestCase):
    """Implemented for symmetry; measured reach on the R14 roster is 0."""

    def test_the_swap_reaches_the_type25_node_to_surface_route(self):
        deck = _rs_deck(
            keyword="*CONTACT_ERODING_NODES_TO_SURFACE")
        result, starter, _ = _convert(deck)
        self.assertIn("/INTER/TYPE25/", starter)
        self.assertTrue(_has(result.warnings, "SWAPPED the roles"))


class RigidSecondaryStringCorrectionTests(unittest.TestCase):
    """The two shipped strings round 4 RETRACTS, and what replaces them."""

    def test_the_twoway_note_no_longer_says_the_swap_was_never_measured(self):
        from k2rad.handlers import _CONTACT_SPELLING_NOTES
        note = _CONTACT_SPELLING_NOTES["twoway"]
        self.assertNotIn("never been measured to help", note)
        self.assertIn("sphere1", note)
        self.assertIn("--no-rigid-secondary-swap", note)

    def test_the_remedy_constant_is_the_implicit_one(self):
        from k2rad.writer import contacts
        self.assertFalse(hasattr(contacts, "_RIGID_SECONDARY_REMEDY"))
        text = contacts._RIGID_SECONDARY_REMEDY_IMPLICIT
        self.assertNotIn("deliberately does NOT swap", text)
        self.assertIn("bumper.k", text)
        self.assertIn("policy, not a solver constraint", text)


# ═════════════════════════════════════════════════════════════════════════════
# B3 — --derived-gapmin (OPT-IN) on a SOLID-only-main /INTER/TYPE7
# ═════════════════════════════════════════════════════════════════════════════

def _gapmin_cell(starter: str) -> str:
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines)
             if ln.startswith("#              Stfac"))
    return lines[i + 1].split()[2]


class DerivedGapminTests(unittest.TestCase):
    """``AUTO_GAPMIN_K`` (tests/test_converter.py) is the only fixture in the
    repo the predicate selects: two 4-node tets, part 2 *MAT_RIGID, the main
    side a ``/SURF/PART/EXT``, no Card-3 SAST/SBST.

    Hand-computed ``min_edge``: part 2's nodes are 5 (0.5,0,0), 6 (1.5,0,0),
    7 (0.5,1,0), 8 (0.5,0,1); the four faces are all external and the edge
    lengths are 1.0 (5-6, 5-7, 5-8) and sqrt(2) (6-7, 7-8, 8-6), so
    ``min_edge = 1.0``.
    """

    @staticmethod
    def _conv(**kw):
        from test_converter import AUTO_GAPMIN_K
        return _convert(AUTO_GAPMIN_K, **kw)

    def test_default_off_leaves_the_cell_at_zero(self):
        result, starter, _ = self._conv()
        self.assertEqual(_gapmin_cell(starter), "0")
        self.assertEqual(starter, self._conv(derived_gapmin=False)[1])

    def test_the_solid_main_warns_by_default(self):
        result, _, _ = self._conv()
        w = [x for x in result.warnings if "SOLID segments only" in x]
        self.assertEqual(len(w), 1, repr(result.warnings))
        self.assertIn("GAP MIN = 0.1 x 1", w[0])
        self.assertIn("i7sti3.F:1055-1063", w[0])
        self.assertIn("i4gmx3.F:58-66", w[0])
        self.assertIn("twobar", w[0])
        self.assertIn("--derived-gapmin", w[0])
        # The two substrings other tests forbid on this very deck.
        self.assertFalse(any("Gapmin=" in x for x in result.warnings))
        self.assertFalse(any("auto-gapmin" in x for x in result.warnings))

    def test_the_flag_writes_factor_times_min_edge(self):
        self.assertEqual(_gapmin_cell(self._conv(derived_gapmin=True)[1]),
                         "0.005")

    def test_the_factor_changes_the_cell(self):
        self.assertEqual(
            _gapmin_cell(self._conv(derived_gapmin=True,
                                    derived_gapmin_factor=0.01)[1]), "0.01")

    def test_the_ceiling_is_half_the_min_edge(self):
        result, starter, _ = self._conv(derived_gapmin=True,
                                        derived_gapmin_factor=0.8)
        self.assertEqual(_gapmin_cell(starter), "0.5")
        self.assertTrue(_has(result.warnings, "CLAMPED to the ceiling",
                             "i7sti3.F:1075"))

    def test_inter_gapmin_still_wins(self):
        result, starter, _ = self._conv(derived_gapmin=True,
                                        inter_gapmin={9: 0.03})
        self.assertEqual(_gapmin_cell(starter), "0.03")
        self.assertFalse(any("--derived-gapmin wrote" in x
                             for x in result.warnings))

    def test_card3_sst_mst_still_wins(self):
        from test_converter import GAPMIN_K
        result, starter, _ = _convert(GAPMIN_K, derived_gapmin=True)
        self.assertEqual(_gapmin_cell(starter), "0.11")

    def test_a_shell_main_is_untouched_and_unwarned(self):
        from test_converter import GAPMIN_K, DEFDEF_K, FORCE_RB_K
        for name, deck in (("GAPMIN_K", GAPMIN_K), ("DEFDEF_K", DEFDEF_K),
                           ("FORCE_RB_K", FORCE_RB_K)):
            with self.subTest(deck=name):
                base = _convert(deck)[1]
                flagged = _convert(deck, derived_gapmin=True)
                self.assertEqual(base, flagged[1])
                self.assertFalse(any("SOLID segments only" in x
                                     for x in flagged[0].warnings))

    def test_a_MIXED_shell_and_solid_main_is_excluded(self):
        """A main side that resolves to BOTH shell and solid segments feeds the
        starter's SHELL-THICKNESS branch (``DXM``), not the mesh-size one, so it
        is out of this rule's scope — and per part SHELLS WIN, exactly as
        ``_make_master_surface`` decides it. Measured roster population: 3 real
        mixed mains (``mainboltaexpl``, ``show-cases/contact-overview/main``,
        ``EXP_SC_PRELOAD``), whose starter ``GAP MIN / min edge`` ratios are
        0.500, 0.277 and 0.124 — NOT the 0.100 a solid-only main takes."""
        from test_converter import AUTO_GAPMIN_K
        # Part 3: one shell on four of the existing nodes, and a *SET_PART that
        # scopes the contact's MAIN side over the rigid tet part AND that shell.
        deck = AUTO_GAPMIN_K.replace(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n"
            "         9                                                              pin_pair\n"
            "         1         2         3         3         0         0         0         0\n",
            "*ELEMENT_SHELL\n"
            "       9       3       5       6       7       8\n"
            "*PART\nshell skin\n"
            + _row(3, 3, 1) + "\n"
            "*SECTION_SHELL\n" + _row(3, 16) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            "*SET_PART_LIST\n" + _row(300) + "\n" + _row(2, 3) + "\n"
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID\n"
            "         9                                                              pin_pair\n"
            "         1       300         3         2         0         0         0         0\n")
        result, starter, _ = _convert(deck, derived_gapmin=True)
        self.assertEqual(_gapmin_cell(starter), "0")
        self.assertFalse(any("SOLID segments only" in x
                             for x in result.warnings), result.warnings)


    def test_the_injected_implicit_stub_is_excluded(self):
        """27 of the roster's 42 solid-only mains are k2rad's OWN stabilization
        card (27 deck keys, censused WITH the stub injected), measured
        byte-inert on 5 of 5 carriers — deriving a gap for it would be noise
        about a card the user did not write."""
        from k2rad.writer.common import AUTO_IMPLICIT_STUB_TITLE
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
                + _d2r_mesh()
                + "*PART\np1\n" + _row(1, 1, 1) + "\n"
                + "*PART\np2\n" + _row(2, 1, 1) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                  "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n*END\n")
        base = _convert(deck)
        flagged = _convert(deck, derived_gapmin=True)
        self.assertIn(AUTO_IMPLICIT_STUB_TITLE, base[1])
        self.assertEqual(base[1], flagged[1])
        self.assertFalse(any("SOLID segments only" in x
                             for x in flagged[0].warnings))

    def test_the_interference_family_is_excluded(self):
        from test_converter import AUTO_GAPMIN_K
        deck = AUTO_GAPMIN_K.replace(
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE_ID",
            "*CONTACT_SURFACE_TO_SURFACE_INTERFERENCE_ID")
        result, starter, _ = _convert(deck, derived_gapmin=True)
        self.assertEqual(_gapmin_cell(starter), "0")
        self.assertTrue(_has(result.warnings, "EXCLUDED from --derived-gapmin",
                             "EXP_SC_CONTACT_INTERFERENCE"))

    def test_a_collapsed_face_side_is_skipped_like_i4gmx3(self):
        """``i4gmx3.F:58-66`` skips a collapsed side. Both of its tests —
        ``N1 == N2`` and a zero length — reduce to ONE here, because equal ids
        name the same node and the distance is then identically 0; the code
        says so at the guard rather than carrying a branch that cannot fail."""
        from k2rad.writer.contacts import _min_segment_side
        from k2rad.state import ConversionState, NodeData
        st = ConversionState()
        st.nodes = {1: NodeData(0.0, 0.0, 0.0), 2: NodeData(3.0, 0.0, 0.0),
                    3: NodeData(3.0, 4.0, 0.0),
                    4: NodeData(3.0, 4.0, 0.0)}      # coincident with node 3
        self.assertEqual(_min_segment_side(st, [[1, 2, 3, 3]]), 3.0)
        self.assertEqual(_min_segment_side(st, [[1, 2, 3]]), 3.0)
        # Two DISTINCT ids at the same point are skipped by the same guard.
        self.assertEqual(_min_segment_side(st, [[1, 2, 3, 4]]), 3.0)
        # A missing node id contributes no side at all.
        self.assertEqual(_min_segment_side(st, [[1, 2, 99]]), 3.0)

    def test_the_CLOSING_side_of_a_segment_is_measured_too(self):
        """``i4gmx3.F:58-66`` walks all FOUR sides of a quad, the n4->n1
        closing one included, and ``_min_segment_side`` does the same through
        ``(a + 1) % k``.

        Every other fixture in this file happens to carry its minimum on a
        NON-closing side (AUTO_GAPMIN_K's min is 1.0, the TET10 coupon's 5.0,
        the collapsed-face coupon's 3.0), so a mutation to ``range(k - 1)`` —
        skip the closing side — left the WHOLE suite green while changing the
        written Gapmin and the quoted starter ``GAP MIN`` by 4x on this shape.
        """
        from k2rad.writer.contacts import _min_segment_side
        from k2rad.state import ConversionState, NodeData
        st = ConversionState()
        st.nodes = {1: NodeData(0.0, 0.0, 0.0), 2: NodeData(10.0, 0.0, 0.0),
                    3: NodeData(10.0, 8.0, 0.0), 4: NodeData(0.0, 2.0, 0.0)}
        # sides: 1->2 = 10, 2->3 = 8, 3->4 = 10.0 (sqrt(100+36)=11.66), and the
        # CLOSING 4->1 = 2.0, which is the unique minimum.
        self.assertEqual(_min_segment_side(st, [[1, 2, 3, 4]]), 2.0)
        # A triangle's closing side counts the same way: 3->1 here.
        st.nodes[5] = NodeData(0.0, 1.5, 0.0)
        self.assertEqual(_min_segment_side(st, [[1, 2, 5]]), 1.5)

    def test_the_written_cell_keeps_FOUR_significant_digits(self):
        """``_round_sig``'s digit count is part of the emitted cell, not
        cosmetic: on a main surface whose minimum edge is not a round number
        the Gapmin k2rad writes, and the value its default-ON warning quotes,
        both come out of it.

        Pinned on ``sphere1``'s own measured minimum edge (5.841288355312,
        read back from the starter's ``GAP MIN = 0.5841288355312`` echo): at
        the shipped ``sig = 4`` the cell is ``0.02921``. Every other fixture's
        minimum edge is exactly 1.0, where every digit count agrees, so
        ``sig = 6`` used to leave the whole suite green.
        """
        from k2rad.writer.contacts import _round_sig
        min_edge = 5.841288355312
        self.assertEqual(_round_sig(0.005 * min_edge), 0.02921)
        self.assertEqual(_round_sig(min_edge), 5.841)
        self.assertEqual(_round_sig(0.1 * min_edge), 0.5841)
        self.assertEqual(_round_sig(0.0), 0.0)

    def test_the_two_goldens_that_carry_a_TYPE7_have_shell_mains(self):
        """Zero golden moves under B3, verified from the fixtures themselves."""
        import glob
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "expected")
        carriers = [p for p in glob.glob(os.path.join(root, "*.rad"))
                    if "/INTER/TYPE7" in open(p, encoding="utf-8").read()
                    .replace("\r\n", "\n")]
        self.assertEqual(sorted(os.path.basename(p) for p in carriers),
                         ["implicit_qstat_0000.rad", "rigid_contact_0000.rad"])
        for p in carriers:
            with self.subTest(golden=os.path.basename(p)):
                self.assertIn("/SURF/GRSHEL/",
                              open(p, encoding="utf-8").read())


class DerivedGapminCliTests(unittest.TestCase):

    def test_the_parser_defaults(self):
        args = cli.build_parser().parse_args(["deck.k"])
        self.assertIs(args.derived_gapmin, False)
        self.assertEqual(args.derived_gapmin_factor, 0.005)
        self.assertIs(args.rigid_secondary_swap, True)
        self.assertIs(args.deformable_to_rigid, True)

    def test_the_positional_output_stem_is_not_eaten(self):
        """``--derived-gapmin`` is store_true, NOT ``nargs='?'``: the parser
        already declares an optional positional ``output_stem``, so an optional
        argument to the flag would silently swallow it."""
        args = cli.build_parser().parse_args(
            ["deck.k", "out/stem", "--derived-gapmin"])
        self.assertEqual(args.output_stem, "out/stem")
        self.assertIs(args.derived_gapmin, True)

    def test_help_renders(self):
        text = cli.build_parser().format_help()
        self.assertIn("--derived-gapmin", text)
        self.assertIn("--no-rigid-secondary-swap", text)
        self.assertIn("--no-deformable-to-rigid", text)


class PartBGuiWiringTests(unittest.TestCase):

    def test_build_convert_kwargs_carries_the_three_levers(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        open(path, "w").write("*KEYWORD\n*END\n")
        kw = k2rad_gui.build_convert_kwargs(
            input_path=path, output_stem="", units=("Mg", "mm", "s"),
            ground_springs=False, ground_spring_k_text="",
            soften_stfac_text="", derived_gapmin=True,
            derived_gapmin_factor_text="0.01",
            rigid_secondary_swap=False, deformable_to_rigid=False)
        self.assertIs(kw["derived_gapmin"], True)
        self.assertEqual(kw["derived_gapmin_factor"], 0.01)
        self.assertIs(kw["rigid_secondary_swap"], False)
        self.assertIs(kw["deformable_to_rigid"], False)
        tmp.cleanup()

    def test_the_factor_is_only_read_when_the_box_is_ticked(self):
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        open(path, "w").write("*KEYWORD\n*END\n")
        kw = k2rad_gui.build_convert_kwargs(
            input_path=path, output_stem="", units=("Mg", "mm", "s"),
            ground_springs=False, ground_spring_k_text="",
            soften_stfac_text="", derived_gapmin=False,
            derived_gapmin_factor_text="not a number")
        self.assertNotIn("derived_gapmin_factor", kw)
        tmp.cleanup()

    def test_the_summary_names_every_non_default(self):
        import k2rad_gui
        captured = []
        app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
        app._append = captured.append
        k2rad_gui.ConverterGUI._describe_options(app, {
            "derived_gapmin": True, "derived_gapmin_factor": 0.005,
            "rigid_secondary_swap": False, "deformable_to_rigid": False})
        text = "".join(captured)
        self.assertIn("derived gapmin", text)
        self.assertIn("--no-rigid-secondary-swap", text)
        self.assertIn("--no-deformable-to-rigid", text)

    def test_the_summary_stays_quiet_on_a_default_conversion(self):
        import k2rad_gui
        captured = []
        app = k2rad_gui.ConverterGUI.__new__(k2rad_gui.ConverterGUI)
        app._append = captured.append
        k2rad_gui.ConverterGUI._describe_options(app, {})
        text = "".join(captured)
        for needle in ("derived gapmin", "--no-rigid-secondary-swap",
                       "--no-deformable-to-rigid"):
            self.assertNotIn(needle, text)


# ═════════════════════════════════════════════════════════════════════════════
# B4 — the docs
# ═════════════════════════════════════════════════════════════════════════════

class PartBDocsTests(unittest.TestCase):

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(self, name):
        with open(os.path.join(self._ROOT, name), encoding="utf-8") as fh:
            return fh.read()

    def test_the_roadmap_queue_table_gained_a_round_4_column(self):
        text = self._read("ROADMAP.md")
        header = next(ln for ln in text.splitlines()
                      if ln.startswith("| # | class | decks |"))
        self.assertIn("round 4", header)

    def test_the_roadmap_lists_what_round_4_does_not_close(self):
        text = self._read("ROADMAP.md")
        self.assertIn("What round 4 deliberately does NOT close", text)
        for item in ("mass-weighted", "pseudo-inverse", "transducer",
                     "advection_B", "CNRB DOF releases"):
            with self.subTest(item=item):
                self.assertIn(item, text)

    def test_the_refuted_solver_constraint_is_gone_from_the_docs(self):
        for name in ("README.md", "ROADMAP.md"):
            with self.subTest(doc=name):
                text = self._read(name)
                self.assertNotIn("cannot hold `/RBODY` members", text)
                self.assertNotIn("cannot form a secondary node group", text)

    def test_the_readme_has_the_three_new_rows(self):
        text = self._read("README.md")
        self.assertIn("*DEFORMABLE_TO_RIGID", text)
        self.assertIn("--no-rigid-secondary-swap", text)
        self.assertIn("--derived-gapmin", text)

    def test_EVERY_new_flag_reaches_the_README(self):
        """The round shipped nine new levers and documented seven. The two
        missing ones were the IMPLICIT pair — ``--qstat-dtscal``, the round's
        largest default change (51 keys on 40 models) and its only lost
        NORMAL, whose escape ``--qstat-dtscal 0.1`` is exactly what a user hit
        by that regression needs to find, and ``--arclength-riks``. Round 3's
        own flipped default has a full paragraph three lines away in the same
        README section, so the precedent was there to match.

        Scoped to ROUND 4's own nine levers rather than to every flag the
        parser owns: several older options are documented under their
        ``--no-`` spelling only or not at all, which is a separate debt and
        not what this guard is about. Each name is also asserted to BE a real
        parser option, so a renamed flag fails here instead of quietly passing
        on a stale string.
        """
        text = self._read("README.md")
        parser = cli.build_parser()
        known = {opt for action in parser._actions
                 for opt in action.option_strings}
        for flag in ("--qstat-dtscal", "--arclength-riks",
                     "--no-discrete-offset",
                     "--no-spring-token-mass-compensation",
                     "--no-tgmult-imptemp", "--no-deformable-to-rigid",
                     "--no-rigid-secondary-swap", "--derived-gapmin",
                     "--derived-gapmin-factor"):
            with self.subTest(flag=flag):
                self.assertIn(flag, known, "not a parser option any more")
                self.assertIn(flag, text, "absent from README.md")

    def test_the_changelog_quotes_pend_imp_and_sphere1(self):
        text = self._read("CHANGELOG.md")
        self.assertIn("5.03545e-06", text)
        self.assertIn("79 147.3", text)
        self.assertIn("25 675 cycles", text)


# ═════════════════════════════════════════════════════════════════════════════
# The finalize round — every defect the four validators confirmed
# ═════════════════════════════════════════════════════════════════════════════

class TgmultGateReadsEveryDropBucketTests(unittest.TestCase):
    """A registered-and-declined driver lands in ``recognized_not_emitted``
    and in NEITHER other registry.

    The gate screened ``skipped_keywords`` alone, which is a filter keyed on a
    field those records do not have (MISTAKES #136). MEASURED on
    ``thermal/thermal-stress`` with one card added: ``*BOUNDARY_THERMAL_WELD``,
    ``*BOUNDARY_TEMPERATURE_RSW``, ``*BOUNDARY_TEMPERATURE_TRAJECTORY`` and
    ``*BOUNDARY_THERMAL_BULKNODE`` — 4 of 4 — passed a gate that exists to stop
    them, and an ``/IMPTEMP`` was emitted that would clamp away the very field
    the source drives (``fixtemp.F:180-199``).
    """

    DECLINED = ("BOUNDARY_THERMAL_WELD", "BOUNDARY_TEMPERATURE_RSW",
                "BOUNDARY_TEMPERATURE_TRAJECTORY",
                "BOUNDARY_THERMAL_BULKNODE", "BOUNDARY_FLUX_TRAJECTORY")

    def test_each_declined_driver_blocks_the_restatement(self):
        for kw in self.DECLINED:
            with self.subTest(keyword=kw):
                result, starter, _e = _convert(
                    _thermal_deck(extra=f"*{kw}\n" + _row(1, 0) + "\n"))
                self.assertNotIn("/IMPTEMP/", starter)
                self.assertTrue(_has(result.warnings, "TGMULT=10",
                                     "DROPPED", f"*{kw}"), result.warnings)

    def test_the_declined_drivers_really_are_in_that_bucket(self):
        """The probe must REACH the branch it claims to test: if these landed
        in ``skipped_keywords`` the old gate would already have caught them and
        the test above would prove nothing."""
        for kw in self.DECLINED:
            with self.subTest(keyword=kw):
                st = _dispatch(_thermal_deck(
                    extra=f"*{kw}\n" + _row(1, 0) + "\n"))
                self.assertIn(kw, [k for k, _ in st.recognized_not_emitted])
                self.assertNotIn(kw, st.skipped_keywords)

    def test_LOAD_THERMAL_on_a_thermal_solve_deck_still_does_NOT_block(self):
        """Vol I R17 p.33-162: LS-DYNA ignores the whole
        ``*LOAD_THERMAL_OPTION`` family in a thermal-only or coupled analysis,
        and ``_drop_load_thermal_on_thermal_soln`` drops it for the same
        reason. A card inert in BOTH codes cannot veto a restatement — and the
        rule now applies to the declined spellings too, not just the parsed
        ones."""
        result, starter, _e = _convert(
            _thermal_deck(extra="*LOAD_THERMAL_D3PLOT\n" + _row(1) + "\n"))
        self.assertIn("/IMPTEMP/", starter)
        self.assertTrue(_has(result.warnings, "TGMULT=10", "/IMPTEMP/"),
                        result.warnings)

    def test_LOAD_HEAT_is_not_in_that_family_and_does_block(self):
        """A volumetric generation is not a ``*LOAD_THERMAL_OPTION``; the
        SOLN exemption must not reach it."""
        result, starter, _e = _convert(
            _thermal_deck(extra="*LOAD_HEAT_GENERATION_SOLID\n"
                                + _row(1, 0) + "\n"))
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertTrue(_has(result.warnings, "TGMULT=10", "DROPPED",
                             "LOAD_HEAT_GENERATION_SOLID"), result.warnings)


class TgmultDoesNotShipAFalseInertExpansionNoteTests(unittest.TestCase):
    """``_warn_constant_driver_expansion`` ran every test over
    ``imposed_temperatures``, which is EMPTY for a TGMULT record.

    With nothing in that list no early return fired and the message printed an
    empty constant — telling the reader the deck "develops NO thermal strain
    from these cards" on the one deck where round 4 makes it develop some, and
    three lines after the A4 warning reported node 2 moving 0.0 to
    1.49531e-04 mm.
    """

    def _deck(self):
        return _thermal_deck(extra="*MAT_ADD_THERMAL_EXPANSION\n"
                                   + _row(1, 1.0e-7) + "\n")

    def test_the_NEVER_MOVE_sentence_is_absent(self):
        result, starter, _e = _convert(self._deck())
        self.assertIn("/IMPTEMP/", starter)
        for w in result.warnings:
            self.assertNotIn("NEVER MOVE", w)

    def test_no_shipped_warning_carries_an_empty_parenthesis(self):
        """The visible symptom was ``a constant ()`` — the same class as a doc
        template placeholder shipping."""
        result, _s, _e = _convert(self._deck())
        for w in result.warnings:
            self.assertNotIn(" ()", w)


class RefusedTgmultWithdrawsItsCurveTests(unittest.TestCase):
    """``_resolve_tgmult_generation`` mints the ``/FUNCT`` before the deck-wide
    screen can withdraw the record, and the single ``/FUNCT`` emitter runs at
    the "functions" assembly step — long before "thermal". A refusal therefore
    used to leave an orphan curve behind and shift every later auto id."""

    def _two_material_deck(self):
        """Two *HEAT/MAT materials, only one of which carries TGMULT — the
        ``uncovered`` branch of ``_screen_tgmult_generations``."""
        return ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(3.0) + "\n"
                "*CONTROL_SOLUTION\n" + _row(2) + "\n"
                "*CONTROL_THERMAL_SOLVER\n" + _row(1, 0.0, 0) + "\n"
                "*NODE\n"
                + "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                          for i, (x, y, z) in enumerate(_D2R_NODES, start=1))
                + "*ELEMENT_SOLID\n"
                  "       1       1       1       2       3       4       5"
                  "       6       7       8\n"
                  "       2       2       9      10      11      12      13"
                  "      14      15      16\n"
                + "*PART\np1\n" + _row(1, 1, 1, 0, 0, 0, 0, 1) + "\n"
                + "*PART\np2\n" + _row(2, 1, 2, 0, 0, 0, 0, 2) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                  "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n"
                  "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
                  "*MAT_THERMAL_ISOTROPIC\n"
                + _row(1, 1.0, 0, 10.0, 0.0, 0.0) + "\n" + _row(1.0, 1.0) + "\n"
                  "*MAT_THERMAL_ISOTROPIC\n"
                + _row(2, 1.0, 0, 0.0, 0.0, 0.0) + "\n" + _row(1.0, 1.0) + "\n"
                  "*INITIAL_TEMPERATURE_SET\n" + _row(0, 10.0) + "\n*END\n")

    def test_the_uncovered_screen_refuses_and_leaves_no_orphan_FUNCT(self):
        result, starter, _e = _convert(self._two_material_deck())
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertTrue(_has(result.warnings, "TGMULT", "DROPPED",
                             "carry NO TGMULT"), result.warnings)
        self.assertNotIn("Auto_tgmult_T_tmid", starter)

    def test_a_refused_deck_is_byte_identical_to_the_opt_out_arm(self):
        """The orphan's real cost: it shifted every later auto id, so the
        refused deck was NOT the deck ``--no-tgmult-imptemp`` produces."""
        _r1, refused, _e1 = _convert(self._two_material_deck())
        _r2, optout, _e2 = _convert(self._two_material_deck(),
                                    tgmult_imptemp=False)
        self.assertEqual(refused, optout)

    def test_two_different_rates_are_refused_too(self):
        """The other branch of the deck-wide screen — no test reached it."""
        deck = self._two_material_deck().replace(
            _row(2, 1.0, 0, 0.0, 0.0, 0.0), _row(2, 1.0, 0, 99.0, 0.0, 0.0))
        result, starter, _e = _convert(deck)
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertTrue(_has(result.warnings, "DIFFERENT rates"),
                        result.warnings)
        self.assertNotIn("Auto_tgmult_T_tmid", starter)

    def test_one_rate_on_two_DIFFERENT_curves_is_refused_too(self):
        """The scalar rate is not the whole generation. With a ``TGRLC``
        curve the history is ``rate * INTEGRAL(f dt)``, so two ``/HEAT/MAT``s
        can share one ``TGMULT/(rho*Cp)`` and still drive their parts apart —
        which is exactly the non-uniform field the ``/IMPTEMP`` may not clamp.
        The screen compared only the scalar and let that pass."""
        curves = ""
        for lcid, pts in ((7, ((0.0, 0.0), (3.0, 2.0))),
                          (8, ((0.0, 2.0), (3.0, 0.0)))):
            curves += ("*DEFINE_CURVE\n" + _row(lcid) + "\n"
                       + "".join(f"{x:>20.10G}{y:>20.10G}\n" for x, y in pts))
        deck = self._two_material_deck().replace(
            _row(1, 1.0, 0, 10.0, 0.0, 0.0), _row(1, 1.0, 7, 10.0, 0.0, 0.0)
        ).replace(
            _row(2, 1.0, 0, 0.0, 0.0, 0.0), _row(2, 1.0, 8, 10.0, 0.0, 0.0)
        ).replace("*END\n", curves + "*END\n")
        result, starter, _e = _convert(deck)
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertTrue(_has(result.warnings, "DIFFERENT TGRLC",
                             "temperature histories separate"),
                        result.warnings)
        self.assertNotIn("Auto_tgmult_T_tmid", starter)

    def test_parts_with_no_element_are_refused_before_the_curve_is_minted(self):
        """The empty-node drop used to live at emit time, where it could not
        withdraw the curve it was rejecting."""
        deck = _thermal_deck().replace(
            "*ELEMENT_SOLID\n"
            "       1       1       1       2       3       4       5"
            "       6       7       8\n", "")
        result, starter, _e = _convert(deck)
        self.assertNotIn("/IMPTEMP/", starter)
        self.assertNotIn("Auto_tgmult_T_tmid", starter)
        self.assertTrue(_has(result.warnings, "TGMULT=10", "DROPPED"),
                        result.warnings)


class RigidPartIdsHonoursTheOptOutTests(unittest.TestCase):
    """``rigid_part_ids`` unioned ``deformable_to_rigid`` unconditionally while
    the EMITTER honoured ``--no-deformable-to-rigid``, so the six consumers of
    the shared predicate called a part rigid that the emitted deck leaves
    deformable."""

    def _damping_deck(self):
        return _d2r_deck(gravity=False, contact=False).replace(
            "*END\n", "*DAMPING_GLOBAL\n" + _row(0, 1.0) + "\n*END\n")

    def test_with_the_flag_OFF_the_part_is_rigid_for_every_consumer(self):
        _r, starter, _e = _convert(self._damping_deck())
        self.assertIn("/RBODY", starter)

    def test_with_the_flag_ON_no_RBODY_and_no_consumer_calls_it_rigid(self):
        from k2rad.parser import parse_k_file as _p
        from k2rad.writer.common import rigid_part_ids
        _r, starter, _e = _convert(self._damping_deck(),
                                   deformable_to_rigid=False)
        self.assertNotIn("/RBODY", starter)
        self.assertEqual(_p, _p)                       # keep the import honest
        # ...and the predicate itself agrees with the emitter.
        st = _dispatch(self._damping_deck())
        st.options.deformable_to_rigid = False
        self.assertEqual(rigid_part_ids(st), set())
        st.options.deformable_to_rigid = True
        self.assertEqual(rigid_part_ids(st), {1})

    def test_the_XREF_screen_follows_the_option_too(self):
        deck = self._damping_deck().replace(
            "*END\n", "*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
                      "       1             0.0             0.0             0.0\n"
                      "*END\n")
        result, _s, _e = _convert(deck, deformable_to_rigid=False)
        hits = [w for w in result.warnings if "/XREF" in w and "rigid" in w]
        self.assertEqual(hits, [], hits)

    def test_an_ELEMENT_FREE_part_is_the_ONE_stated_exception(self):
        """The invariant is "the predicate and ``_deformable_to_rigid_map``
        name the same set", and it holds. What does NOT follow from it is
        "the predicate and the EMITTED deck agree": ``_make_rbodies`` declines
        a part that contributes no node at all, and this pins that the
        predicate still calls it rigid — the exception the docstring now
        states by name, so nobody re-derives it as a bug or as a guarantee.

        Reach on the R14 roster: 0 (all four ``*DEFORMABLE_TO_RIGID`` keys own
        elements). Recorded as a ROADMAP NOT-closed item.
        """
        from k2rad.writer.common import rigid_part_ids
        # part 3 exists and is named by a *DEFORMABLE_TO_RIGID card, but owns
        # no element: the mesh helper only ever makes parts 1 and 2.
        deck = _d2r_deck(rows=((1, 0, "PART"), (3, 0, "PART")),
                         gravity=False, contact=False).replace(
            "*SECTION_SOLID\n", "*PART\npart 3\n" + _row(3, 1, 1) + "\n"
                                "*SECTION_SOLID\n", 1)
        result, starter, _e = _convert(deck)
        self.assertIn("/RBODY", starter)                       # part 1 emits
        self.assertTrue(_has(result.warnings, "*DEFORMABLE_TO_RIGID pid=3",
                             "NO /RBODY was emitted for it",
                             "NOT rigid in the converted model"),
                        result.warnings)
        self.assertEqual(rigid_part_ids(_dispatch(deck)), {1, 3})


class SolidBoundaryFacesReportsAPartialSkinTests(unittest.TestCase):
    """A 6-node pentahedron on a short ``*ELEMENT_SOLID`` card is stored with
    SIX nodes and is not faceted. On a part that MIXES hexes with wedges the
    face they share is then seen once and counted EXTERNAL, so the minimum edge
    — hence the written ``Gapmin`` and the quoted starter ``GAP MIN`` — comes
    out too small. The side must stop being ``all_solid`` instead."""

    def test_a_wedge_makes_the_side_not_all_solid(self):
        from k2rad.writer.contacts import _main_surface_segments
        base = _d2r_deck(card="", rows=(), gravity=False, contact=False)
        st = _dispatch(base)
        _segs, all_solid = _main_surface_segments(st, 1, 3)
        self.assertTrue(all_solid, "the hex-only control must be all_solid")
        mixed = base.replace(
            "       2       2       9      10      11      12      13"
            "      14      15      16\n",
            "       2       1       9      10      11      12      13      14\n")
        st2 = _dispatch(mixed)
        self.assertEqual(
            [len(e.nodes) for e in st2.solid_elems if e.pid == 1], [8, 6])
        _segs2, all_solid2 = _main_surface_segments(st2, 1, 3)
        self.assertFalse(all_solid2)

    def test_the_helper_reports_completeness(self):
        from k2rad.writer.contacts import _solid_boundary_faces
        st = _dispatch(_d2r_deck(card="", rows=(), gravity=False,
                                 contact=False))
        faces, complete = _solid_boundary_faces(st, [1])
        self.assertTrue(complete)
        self.assertEqual(len(faces), 6)


class ConvertOptionsRefusesAnImpossibleLeverTests(unittest.TestCase):
    """``convert()`` is a public entry point of its own; the CLI's and the
    GUI's validation never ran for it."""

    def test_a_non_positive_qstat_dtscal_raises(self):
        for bad in (0.0, -3.0):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError) as cm:
                    _convert(_implicit_deck(), qstat_dtscal=bad)
                self.assertIn("qstat_dtscal", str(cm.exception))
                self.assertIn("imp_dyna.F", str(cm.exception))

    def test_the_CONSTRUCTION_guard_fires_on_its_own(self):
        """A mutation check found this: with BOTH guards in place, disabling
        the ``ConvertOptions.__post_init__`` one changed nothing, because
        ``_qstat_dtscal_cell`` raised instead and the test above still passed.

        Two layers are wanted here — the dataclass is mutable, so a caller can
        still set the field after construction and only the writer-side guard
        can catch that — but each layer needs a test that reaches ONLY it.
        This one constructs the options directly."""
        from k2rad.state import ConvertOptions
        for bad in (0.0, -3.0, "fast"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    ConvertOptions(qstat_dtscal=bad)
        ConvertOptions(qstat_dtscal="none")          # the escape still works
        ConvertOptions(qstat_dtscal=0.1)

    def test_the_construction_guard_reaches_an_EXPLICIT_deck_too(self):
        """`_qstat_dtscal_cell` never runs on an explicit deck —
        `_make_engine_implicit` returns before it — so this arm can only be
        caught by the construction guard."""
        explicit = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                    + _BRICK + _MAT_SEC.replace("%ELFORM%", "1") + "*END\n")
        _r, _s, engine = _convert(explicit)
        self.assertNotIn("/IMPL/QSTAT", engine)      # the arm really is dead
        with self.assertRaises(ValueError) as cm:
            _convert(explicit, qstat_dtscal=-3.0)
        self.assertIn("qstat_dtscal", str(cm.exception))

    def test_the_WRITER_side_guard_fires_on_its_own(self):
        """The other layer: a field set AFTER construction reaches only
        ``_qstat_dtscal_cell``."""
        from k2rad.state import ConversionState
        from k2rad.writer.assembly import _qstat_dtscal_cell
        st = ConversionState()
        self.assertEqual(_qstat_dtscal_cell(st), "10")
        st.options.qstat_dtscal = -3.0
        with self.assertRaises(ValueError) as cm:
            _qstat_dtscal_cell(st)
        self.assertIn("imp_dyna.F", str(cm.exception))
        st.options.qstat_dtscal = "fast"
        with self.assertRaises(ValueError):
            _qstat_dtscal_cell(st)

    def test_an_unparsable_qstat_dtscal_raises_instead_of_defaulting(self):
        with self.assertRaises(ValueError):
            _convert(_implicit_deck(), qstat_dtscal="fast")

    def test_none_and_a_positive_number_are_both_accepted(self):
        _r, _s, engine = _convert(_implicit_deck(), qstat_dtscal="none")
        self.assertNotIn("/IMPL/QSTAT", engine)
        _r, _s, engine = _convert(_implicit_deck(), qstat_dtscal=0.1)
        self.assertIn(" 0.1", engine)

    def test_a_non_positive_derived_gapmin_factor_raises(self):
        """A non-positive Gapmin is starter ERROR 785 (``i7sti3.F:1068``)."""
        for bad in (0.0, -0.005):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError) as cm:
                    _convert(_implicit_deck(), derived_gapmin=True,
                             derived_gapmin_factor=bad)
                self.assertIn("derived_gapmin_factor", str(cm.exception))


class UntestedBranchesTheFinalizeAuditFoundTests(unittest.TestCase):
    """Branches that no test reached — a grep for each message returned
    nothing. The TET10 one matters most: it decides the derived GAP MIN on a
    quadratic-tet main, and it is the only ``TET10_EDGEMID`` consumer in
    ``writer/contacts``."""

    _T10 = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10),
            (5, 0, 0), (5, 5, 0), (0, 5, 0), (0, 0, 5), (5, 0, 5), (0, 5, 5)]

    def _tet10_deck(self):
        """ONE /TETRA10 in Radioss corner+midside order, as its own part."""
        nodes = "".join(f"{i:>8}{x:>16.1f}{y:>16.1f}{z:>16.1f}\n"
                        for i, (x, y, z) in enumerate(self._T10, start=1))
        return ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                "*NODE\n" + nodes
                # The TEN-NODE format: card 1 is EID PID, card 2 is n1..n10.
                + "*ELEMENT_SOLID\n"
                + f"{1:>8}{1:>8}\n"
                + "".join(f"{i:>8}" for i in range(1, 11)) + "\n"
                + "*PART\np1\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 10) + "\n"
                  "*MAT_ELASTIC\n" + _row(1, 7.85e-9, 210000.0, 0.3) + "\n*END\n")

    def test_a_TET10_face_is_split_into_the_starters_four_sub_triangles(self):
        """The starter builds four linear sub-triangles per /TETRA10 boundary
        face, so its own GAPMX — and the derived GAP MIN — is measured on the
        HALF-edges. The TET10 ordering is already normalised to Radioss by
        ``_normalize_tet10_ordering`` long before the interfaces section, so
        this consumer only ever sees Radioss-ordered midsides."""
        from k2rad.writer.contacts import (_solid_boundary_faces,
                                           _min_segment_side)
        st = _dispatch(self._tet10_deck())
        self.assertEqual([len(e.nodes) for e in st.solid_elems], [10])
        faces, complete = _solid_boundary_faces(st, [1])
        self.assertTrue(complete)
        # 4 boundary faces x 4 sub-triangles, every one a TRIANGLE.
        self.assertEqual(len(faces), 16)
        self.assertEqual({len(f) for f in faces}, {3})
        # Every emitted node id is a real node of the element.
        self.assertTrue(set().union(*faces) <= set(range(1, 11)))
        # The shortest side is a HALF-edge (5.0), not a corner edge (10.0).
        self.assertAlmostEqual(_min_segment_side(st, faces), 5.0, places=9)

    def test_a_D2R_part_with_no_element_is_named_as_NOT_rigid(self):
        """The one place a ``*DEFORMABLE_TO_RIGID`` card silently does nothing.
        LS-DYNA still deactivates that part's elements at t = 0
        (Vol I R17 p.18-1), so the log has to say the converted model is
        different."""
        deck = _d2r_deck(rows=((77, 0, "PART"),), gravity=False,
                         contact=False).replace(
            "*END\n", "*PART\nempty\n" + _row(77, 1, 1) + "\n*END\n")
        result, starter, _e = _convert(deck)
        self.assertTrue(_has(result.warnings, "*DEFORMABLE_TO_RIGID pid=77",
                             "NOT rigid in the converted model"),
                        result.warnings)
        self.assertNotIn("/RBODY", starter)

    def test_the_SAME_note_on_the_partly_emitted_path(self):
        """``_make_rbodies`` has TWO such branches — the all-empty one above
        (``not nodes_by_pid``) and the per-pid sweep that runs when some D2R
        parts DID emit. Only the second cites Vol I R17 p.18-1, and neither
        had a test."""
        deck = _d2r_deck(rows=((1, 0, "PART"), (77, 0, "PART")),
                         gravity=False, contact=False).replace(
            "*END\n", "*PART\nempty\n" + _row(77, 1, 1) + "\n*END\n")
        result, starter, _e = _convert(deck)
        self.assertIn("/RBODY", starter)              # part 1 did emit
        self.assertTrue(_has(result.warnings, "*DEFORMABLE_TO_RIGID pid=77",
                             "NOT rigid in the converted model", "p.18-1"),
                        result.warnings)

    def test_the_TGMULT_FUNCT_id_never_collides_with_a_deck_curve(self):
        """A4 mints through ``next_curve_id()``; ``/FUNCT`` and ``/TABLE``
        share ONE starter duplicate scan (``hm_read_table.F:88``) and a
        collision is ERROR 79 (k2rad #111). A3 has a probe aimed at
        90001-90004; A4 had none."""
        deck = _thermal_deck(
            extra="".join("*DEFINE_CURVE\n" + _row(i) + "\n"
                          "             0.0             0.0\n"
                          "             1.0             1.0\n"
                          for i in (90001, 90002, 90003, 90004, 90005)))
        _r, starter, _e = _convert(deck)
        ids = [int(ln.split("/")[-1]) for ln in starter.splitlines()
               if ln.startswith(("/FUNCT/", "/FUNCT_SMOOTH/", "/TABLE/"))]
        self.assertEqual(len(ids), len(set(ids)), sorted(ids))
        auto = [ln for ln in starter.splitlines()
                if ln.startswith("Auto_tgmult_T_tmid")]
        self.assertEqual(len(auto), 1, auto)
        self.assertNotIn(int(auto[0].rsplit("_", 1)[1]), range(90001, 90006))


class TheCorrectedSourceCitationsTests(unittest.TestCase):
    """A true conclusion resting on a false premise still misinforms. The
    round-4 retraction of the tied ``_OFFSET`` claim cited ``i24pen3.F:317-319``
    as "the only such assignment among the interface initialisers" — which
    contradicts its own ``no i2*.F routine`` clause and is false: an anchored
    grep over ``starter/source/interfaces`` returns FOUR files."""

    MOVERS = ("i3pen3.F:187-197", "i7pwr3.F:213-242", "i24pen3.F:317-319",
              "in12r.F:120-133")

    def _read(self, name):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            return fh.read()

    def test_the_code_names_all_four_node_movers(self):
        from k2rad.writer import contacts
        src = inspect.getsource(contacts)
        for cite in self.MOVERS:
            with self.subTest(cite=cite):
                self.assertIn(cite, src)

    def test_the_roadmap_names_all_four_too(self):
        text = self._read("ROADMAP.md")
        for cite in self.MOVERS:
            with self.subTest(cite=cite):
                self.assertIn(cite, text)

    def test_the_self_contradicting_exclusivity_claim_is_gone(self):
        from k2rad.writer import contacts
        for text in (inspect.getsource(contacts), self._read("ROADMAP.md"),
                     self._read("CHANGELOG.md")):
            self.assertNotIn("the only such assignment among the interface",
                             text)


class EveryBatchFigureIsOneNumberTests(unittest.TestCase):
    """Re-summed from its own detail table, and re-measured on the COMBINED
    arm — MISTAKES #137 twice over."""

    def _read(self, name):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            return fh.read()

    #: Every place a figure may be STATED. CHANGELOG.md is deliberately NOT
    #: here: it is the one file that may quote a retracted value, exactly as
    #: ``RetractedSourceCitationsAreGoneEverywhere`` scopes its own guard — and
    #: ``test_the_changelog_records_both_retractions`` below asserts that it
    #: does, so the exclusion cannot become a place for a stale figure to hide.
    _STATING_DOCS = ("README.md", "ROADMAP.md")

    def _everywhere(self):
        """EVERY shipped text a figure can be stated in.

        The narrow version of this helper read only ``cli``, ``state``, the
        package ``__init__`` and the two docs — so the three sites that really
        carried the stale ``--derived-gapmin`` count (the default-ON runtime
        warning in ``writer/contacts``, the GUI tooltip, and the ``__init__``
        docstring under a spelling the literal did not match) were either not
        scanned or not matched. A guard that cannot fail is worse than no
        guard, so this now walks the whole package plus the GUI.

        Each text is also NORMALIZED before it is searched: adjacent string
        literals are joined and every whitespace run collapses to one space,
        so a figure split across two source lines reads as the one sentence a
        user sees. A mutation check caught that too — the GUI tooltip's
        ``"… and 12 of the class's "`` / ``"15 R14-roster interfaces …"`` pair
        put 46 characters of quote-newline-indent between the two numbers and
        walked straight through a window that allowed 40.
        """
        import k2rad as pkg
        from k2rad import cli, state
        import k2rad_gui
        mods = [cli, state, pkg, k2rad_gui]
        pkg_dir = os.path.dirname(inspect.getfile(pkg))
        srcs = []
        for root, _dirs, files in os.walk(pkg_dir):
            if "__pycache__" in root:
                continue
            for name in sorted(files):
                if name.endswith(".py"):
                    with open(os.path.join(root, name), "r",
                              encoding="utf-8") as fh:
                        srcs.append(fh.read())
        texts = (srcs + [inspect.getsource(m) for m in mods]
                 + [self._read(n) for n in self._STATING_DOCS])
        return [self._normalise(t) for t in texts]

    @staticmethod
    def _normalise(text):
        """Join adjacent string literals, then collapse whitespace runs."""
        text = re.sub(r"""(['"])\s*\n\s*\1""", "", text)
        return re.sub(r"\s+", " ", text)

    def test_the_stale_ex_01_fixpoint_figure_is_gone(self):
        """``-13.7 %`` was the DTSCAL-0.1 arm; the shipped combined arm reads
        ``-14.12 %`` and the campaign row agrees (``ie_dev -14.1249``)."""
        for text in self._everywhere():
            self.assertNotIn("IE -13.7 %", text)
            self.assertNotIn("IE −13.7 %", text)

    def test_the_derived_gapmin_unmeasured_count_re_sums(self):
        """15 carriers, 2 with a measured solver arm -> 13 unmeasured. The
        shipped 12 contradicted the same sentence's own "the only OTHER
        carrier with a measured arm".

        Matched as a REGEX, not as one exact literal: the count survived a
        first correction pass at three sites purely because they spell it
        ``12 of the class's 15`` while the guard asserted on ``12 of the 15``.
        """
        pat = re.compile(
            r"\b(?:12|twelve)\b[^.]{0,40}\b(?:15|fifteen)\b"
            r"[^.]{0,70}?(?:measured arm|unmeasured|interface)", re.I)
        for text in self._everywhere():
            self.assertIsNone(pat.search(text),
                              "a '12 ... 15' derived-gapmin count survives")
            self.assertNotIn("12 of them unmeasured", text)

    def test_that_guard_can_actually_fire(self):
        """The predecessor of the guard above asserted on the literal
        ``"12 of the 15"`` while the three surviving sites spelled it
        ``"12 of the class's 15"`` — an assertion that could never fail. This
        runs the guard's own regex over each retracted spelling and requires a
        match, so the guard is proven to have teeth rather than assumed to."""
        pat = re.compile(
            r"\b(?:12|twelve)\b[^.]{0,40}\b(?:15|fifteen)\b"
            r"[^.]{0,70}?(?:measured arm|unmeasured|interface)", re.I)
        norm = EveryBatchFigureIsOneNumberTests._normalise
        for spelling in (
                "and 12 of the 15 have no measured arm at all.",
                "and 12 of the class's 15 interfaces on the R14 roster have "
                "no measured arm at all.",
                "and 12 of the class's 15 R14-roster interfaces are "
                "unmeasured.",
                "TWELVE of the fifteen have no measured arm",
                # the SOURCE form that walked through the first window: two
                # adjacent literals with a newline and 27 spaces between them
                '                           "…and 12 of the class\'s "\n'
                '                           "15 R14-roster interfaces are '
                'unmeasured.",'):
            with self.subTest(spelling=spelling[:40]):
                self.assertIsNotNone(pat.search(norm(spelling)))
        # ...and does not fire on an unrelated pair of numbers.
        self.assertIsNone(pat.search(norm(
            "fills 1-12 and 15-18: the mixture CP")))

    def test_the_changelog_records_both_retractions(self):
        """The exclusion above is only sound while the CHANGELOG really does
        carry the retracted values — a reader has to be able to find out what
        the number used to be and why it moved."""
        text = self._read("CHANGELOG.md")
        for quoted in ("IE -13.7 %", "TWELVE of the fifteen",
                       "28 of the roster's 41 solid-only mains"):
            with self.subTest(quoted=quoted):
                self.assertIn(quoted, text)

    def test_the_stub_split_is_the_measured_one(self):
        from k2rad.writer import contacts
        src = inspect.getsource(contacts)
        self.assertIn("27 are", src)
        self.assertNotIn("28 of the roster's 41", src)


if __name__ == "__main__":
    unittest.main()
