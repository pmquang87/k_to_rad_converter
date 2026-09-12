"""Tests for the R14 CAMPAIGN TRIAGE batch, round 4 — PART A:

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

Kept in its own module, the repo's one-module-per-batch convention. Round 4
REPLACES no round-3 test, so nothing is moved here; the two round-3
assertions A1 invalidates are corrected IN PLACE
(``tests/test_converter.py::ImplicitEngineTests::test_qstat_and_nonlin_defaults``
and ``DeformableContactRecipeTests::test_defdef_detected_warns_without_recipe``),
where the reader of the old value will look.
"""

import os
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


def _implicit_deck(elform=1, nsolvr=2, arcctl=0, auto=None) -> str:
    """A minimal QUASI-STATIC implicit deck (no *CONTROL_IMPLICIT_DYNAMICS)."""
    deck = ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
            "*CONTROL_IMPLICIT_SOLUTION\n"
            + _row(nsolvr, 0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(0, 0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(arcctl, 1, 0.0, 1, 2, 0, 0, 0) + "\n")
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
    """``NSOLVR`` in {6,7,8,9} OR card-3 ``ARCCTL`` != 0 — the OR, not either
    half.

    ``ex_06_beam_elform_1`` is the reason: it states ``NSOLVR 12`` and asks for
    the arc-length method through ``ARCCTL 6`` alone, so an NSOLVR-only
    predicate would miss the corpus's only ARCCTL carrier.
    """

    def test_arcctl_is_parsed_off_card_3(self):
        state = _dispatch(_implicit_deck(nsolvr=12, arcctl=6))
        self.assertIsNotNone(state.ctrl_implicit_sol)
        self.assertEqual(state.ctrl_implicit_sol.nsolvr, 12)
        self.assertEqual(state.ctrl_implicit_sol.arcctl, 6)

    def test_a_deck_with_no_card_3_reads_arcctl_0(self):
        deck = ("*KEYWORD\n"
                "*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.01) + "\n"
                "*CONTROL_IMPLICIT_SOLUTION\n"
                + _row(2, 0, 0, 0, 0, 0, 0, 0) + "\n"
                "*END\n")
        state = _dispatch(deck)
        self.assertEqual(state.ctrl_implicit_sol.arcctl, 0)

    def test_nsolvr_6_fires_and_nsolvr_2_does_not(self):
        from k2rad.writer.assembly import _arclength_requested
        self.assertTrue(_arclength_requested(_dispatch(_implicit_deck(nsolvr=6))))
        self.assertFalse(_arclength_requested(_dispatch(_implicit_deck(nsolvr=2))))

    def test_arcctl_alone_fires(self):
        from k2rad.writer.assembly import _arclength_requested
        self.assertTrue(
            _arclength_requested(_dispatch(_implicit_deck(nsolvr=12, arcctl=6))))

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


class ArcLengthCardTests(unittest.TestCase):
    """The card, and the fact that it is OPT-IN.

    The repeat at a second thread count REFUTED it as a default:
    ``ex_05_beam_elform_3_&_6`` turns a 1.5 s ``error_engine`` into a 600 s
    timeout at ``t = 5e-11``, and ``ex_06``'s NORMAL flips to an ERROR at
    ``t = 0`` between nt 3 and nt 4.
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
        self.assertIn(f"{_K:.10G}", block.replace(" ", "").join([" ", " "])
                      if False else block)

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

    def test_a_node_with_no_admas_is_named_and_none_is_invented(self):
        """``mat_spring.belted-dummy.k``: 122 springs, zero ``/ADMAS``."""
        result, starter, _e = _convert(_spring_deck(mass=0.0))
        self.assertNotIn("/ADMAS", starter)
        self.assertTrue(_has(result.warnings, "carry NO /ADMAS",
                             "*ELEMENT_MASS if their dynamics matter"))

    def test_the_opt_out_leaves_the_admas_exactly_as_the_deck_states_it(self):
        _r, starter, _e = _convert(_spring_deck(),
                                   spring_token_mass_compensation=False)
        admas = self._admas(starter)
        self.assertAlmostEqual(list(admas)[0], _NODE_MASS, places=12)

    def test_the_token_mass_constant_is_named_once_and_never_a_literal(self):
        """The compensation and the EMISSION must not be able to drift: the
        constant was named at ``loads.py`` module level and then written as a
        bare ``1.0e-4`` at three emission sites and two warning strings."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "k2rad", "writer", "loads.py"),
                  encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        offenders = [
            (i + 1, l) for i, l in enumerate(lines)
            if "1.0e-4" in l and "_SPRING_TOKEN_MASS = 1.0e-4" not in l
            and "1.0e-6" not in l]
        # The two surviving 1.0e-4 literals belong to OTHER emitters (the
        # grounding-spring /PROP/TYPE8 and the muscle-spring fallback), which
        # have their own mass policies and are not compensated here.
        for _n, line in offenders:
            self.assertNotIn("_emit_prop_type4(", line)
            self.assertNotIn("_emit_prop_type13(", line)

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
    """``T(t) = T0 + TGMULT*f(t)/(rho*Cp)`` — the adiabatic uniform-generation
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

    def test_tgrlc_samples_that_curve_on_its_own_abscissae(self):
        curve = ("*DEFINE_CURVE\n" + _row(5) + "\n"
                 + "".join(f"{x:>20.10G}{y:>20.10G}\n"
                           for x, y in ((0.0, 0.0), (1.0, 2.0), (3.0, 1.0))))
        _r, starter, _e = _convert(_thermal_deck(tgrlc=5, extra=curve))
        fid, _s, _g = self._imptemp(starter)
        self.assertEqual(self._funct_pts(starter, fid),
                         [(0.0, 10.0), (1.0, 30.0), (3.0, 20.0)])

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

    def test_it_does_NOT_fire_on_a_card_that_states_none_of_them(self):
        result, _s, _e = _convert(
            _implicit_deck(auto=(0, 11, 0, 0.0, 0.001, 0, 0)))
        self.assertFalse(any("*CONTROL_IMPLICIT_AUTO:" in w
                             for w in result.warnings), result.warnings)

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


if __name__ == "__main__":
    unittest.main()
