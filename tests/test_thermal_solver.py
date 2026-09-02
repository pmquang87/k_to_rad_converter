"""Tests for the THERMAL SOLVER batch:

  *BOUNDARY_FLUX_{SEGMENT,SET}          → /IMPFLUX   (with the SIGN FLIP)
  *BOUNDARY_CONVECTION_{SEGMENT,SET}    → /CONVEC
  *BOUNDARY_RADIATION_{SEGMENT,SET}     → /RADIATION (E = FMULT / sigma_deck)
  *CONTROL_SOLUTION SOLN=1              → the engine card /DT/THERM
  *CONTROL_THERMAL_SOLVER TSF           → the engine card /THERM
  *CONTROL_THERMAL_SOLVER FWORK         → /HEAT/MAT EFRAC
  *MAT_THERMAL_ISOTROPIC_TD[_LC]        → /HEAT/MAT by a least-squares FIT
  *MAT_THERMAL_ORTHOTROPIC              → /HEAT/MAT when K1 == K2 == K3
  *LOAD_THERMAL_{CONSTANT,VARIABLE}_ELEMENT_<F> → /IMPTEMP on the elements'
                                                  own nodes

Kept in its own module, the repo's one-module-per-batch convention.

**The numbers here are solver-measured.** Every coupon below was converted by
this code and run through OpenRadioss in a short run dir; the engine's own
``thermbilan.F:71-76`` accounting (``** THERMAL ANALYSIS **``) is the
independent checker:

  /IMPFLUX  MLC = -70000, 1 mm^2, 1.00012284e-3 s
      IMPOSED FLUX_DENSITY HEAT  +70.008599 mJ   vs q"*A*t   exact
  the MLC = +70000 twin           -70.008599 mJ   ← the sign flip, discriminated
  /CONVEC   h = 100, 6 faces, RHO0_CP 3.611
      CONVECTION HEAT            387.00946  mJ   vs 387.005245 (lumped) +0.0011%
  /RADIATION FMULT = 5.6704e-11 (eps = 1), T_inf 1000, T0 300
      RADIATION HEAT             0.056251513 mJ  vs 0.056251607     -0.0002%
      (the SI sigma would have given 56.25 mJ, 1000x off)
  /THERM 10 from *CONTROL_THERMAL_SOLVER TSF, on the /CONVEC coupon
      CONVECTION HEAT            2048.0415  mJ  vs 2047.947 (tau/10)  +0.005%
      (the same deck with no /THERM stores 387.00946 — a 5.29x twin, so the
       card's CONSUMPTION is proven, not just its emission; the starter also
       echoes FACTOR TO SPEED-UP THERMAL ANALYSIS = 10.00000)
  /DT/THERM at the default factor 0.9, ENDTIM 0.2
      diverged to HEAT STORED 7 901 590.2 mJ where saturation is 2527.7,
      at 0 ERROR / 0 WARNING / NORMAL TERMINATION
  the same deck at the warning's prescribed factor 0.225
      HEAT STORED 2527.6994 mJ vs an analytic 2527.7000

The starter echo confirms the two cells that ride on /HEAT/MAT: with
FWORK = 1.0 it prints ``FRACTION OF STRAIN ENERGY CONVERTED INTO HEAT =
1.000000000000``, and the mirrored second conductivity pair comes back as
``AL (LIQUID PHASE) = 45.00000000000`` / ``BL (LIQUID PHASE) = 0.0`` rather
than the ``AL = 0`` that would give a /DT/THERM run an unbounded thermal step
above the melting temperature.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import _OFFSET_SPECS
from k2rad.handlers import RARE_MATERIAL_KEYWORDS, dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the repo duplicates these per module) ───────────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _row16(*vals) -> str:
    """LS-DYNA *DEFINE_CURVE point row (2 x 16-char fields)."""
    return "".join(f"{v:>16}" for v in vals)


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


def _block(starter: str, header: str):
    """The lines of the first starter block whose header line equals *header*,
    up to the next '/' line."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            out = []
            for data in lines[i + 1:]:
                if data.startswith("/"):
                    break
                out.append(data)
            return out
    return None


def _data_rows(starter: str, header: str):
    body = _block(starter, header)
    if body is None:
        return None
    return [ln for ln in body if not ln.startswith("#")]


def _headers(text: str, prefix: str):
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


def _one_header(text: str, prefix: str) -> str:
    hits = _headers(text, prefix)
    if len(hits) != 1:
        raise AssertionError(f"expected exactly one {prefix}, got {hits}")
    return hits[0]


def _card_id(header: str) -> int:
    return int(header.rsplit("/", 1)[1])


def _funct_points(starter: str, fid: int):
    """The (x, y) pairs of /FUNCT/<fid>."""
    body = _block(starter, f"/FUNCT/{fid}")
    pts = []
    for ln in body[1:]:
        if ln.startswith("#"):
            continue
        pts.append((float(ln[0:20]), float(ln[20:40])))
    return pts


def _warned(state_or_result, needle: str) -> bool:
    return any(needle in w for w in state_or_result.warnings)


# ── Shared deck fragments ────────────────────────────────────────────────────

#: One 1 mm brick on part 1, material 1, thermal material 9. This is exactly
#: the coupon whose solver numbers head this module: RHO0_CP = 7.85e-9 x 4.60e8
#: = 3.611 mJ/(mm^3 K), AS = 45 mW/(mm K), in the Mg-mm-s system k2rad writes
#: to /BEGIN by default.
BRICK = (
    "*KEYWORD\n"
    "*CONTROL_TERMINATION\n"
    + _row(0.001) + "\n"
    "*NODE\n"
    "         1             0.0             0.0             0.0\n"
    "         2             1.0             0.0             0.0\n"
    "         3             1.0             1.0             0.0\n"
    "         4             0.0             1.0             0.0\n"
    "         5             0.0             0.0             1.0\n"
    "         6             1.0             0.0             1.0\n"
    "         7             1.0             1.0             1.0\n"
    "         8             0.0             1.0             1.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "*PART\n"
    "brick\n"
    + _row(1, 1, 1, 0, 0, 0, 0, 9) + "\n"
    "*SECTION_SOLID\n"
    + _row(1, 1) + "\n"
    "*MAT_ELASTIC\n"
    + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
    "*MAT_THERMAL_ISOTROPIC\n"
    + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
    + _row("4.60E+8", 45.0) + "\n"
    "{EXTRA}"
    "*END\n"
)

#: The z = 1 face, as a *SET_SEGMENT.
SEG1 = ("*SET_SEGMENT\n" + _row(50) + "\n"
        + "       5       6       7       8\n")

#: A constant T_inf = 1000 curve.
CURVE900 = ("*DEFINE_CURVE\n" + _row(900) + "\n"
            + _row16(0.0, 1000.0) + "\n" + _row16(1.0, 1000.0) + "\n")

#: The Stefan-Boltzmann constant in Mg-mm-s, which is what the STARTER derives
#: from the /BEGIN WORK line (hm_read_radiation.F:140-142,
#: SIGMA = STEFBOLTZ*FAC_T**3/FAC_M with STEFBOLTZ = 5.6704e-8 and
#: FAC_M = 1e3, FAC_T = 1). Independently confirmed by Vol I R17 p.12-567,
#: whose hot-stamping (Mg-mm-s) example writes sbc = 5.67e-11.
SIGMA_MG_MM_S = 5.6704e-11


def _deck(extra: str) -> str:
    return BRICK.replace("{EXTRA}", extra)


# ── (B) *BOUNDARY_FLUX → /IMPFLUX ────────────────────────────────────────────

class BoundaryFluxTests(unittest.TestCase):
    def _flux(self, mlc=-70000.0, lcid=0, spelling="SET", **kw):
        card = ("*BOUNDARY_FLUX_" + spelling + "\n"
                + (_row(50, 0) if spelling == "SET" else _row(5, 6, 7, 8))
                + "\n" + _row(lcid, mlc, mlc, mlc, mlc, 0, 0) + "\n")
        pre = (SEG1 if spelling == "SET" else "") + CURVE900
        return _convert(_deck(pre + card), **kw)

    def test_card_is_column_exact_and_the_sign_is_flipped(self):
        result, starter, _ = self._flux()
        header = _one_header(starter, "/IMPFLUX/")
        body = _block(starter, header)
        # cfg radioss2018/LOADS/impflux.cfg: a mandatory title line, then
        # %10d x4 and %20lf x4.
        self.assertEqual(body[0], f"impflux_{_card_id(header)}")
        self.assertEqual(body[1],
                         "#  SURF_ID  FUNCT_ID SENSOR_ID GRBRIC_ID")
        surf = _one_header(starter, "/SURF/SEG/")
        self.assertEqual(int(body[2][0:10]), _card_id(surf))
        self.assertGreater(int(body[2][10:20]), 0)      # FUNCT_ID is mandatory
        self.assertEqual(int(body[2][20:30]), 0)        # SENSOR_ID
        self.assertEqual(int(body[2][30:40]), 0)        # GRBRIC_ID
        self.assertEqual(
            body[3],
            "#             ASCALE              FSCALE              TSTART"
            "               TSTOP")
        self.assertAlmostEqual(float(body[4][0:20]), 1.0)       # ASCALE
        # THE WHOLE CONVERSION: MLC -70000 (LS-DYNA "into the volume") becomes
        # Fscale_y +70000 (Radioss "into the volume").
        self.assertAlmostEqual(float(body[4][20:40]), 70000.0)
        self.assertAlmostEqual(float(body[4][40:60]), 0.0)      # TSTART
        self.assertAlmostEqual(float(body[4][60:80]), 0.0)      # TSTOP -> 1e30
        self.assertTrue(_warned(result, "the NEGATIVE of the deck's MLC"))

    def test_a_positive_mlc_takes_heat_out(self):
        # The discriminating twin: LS-DYNA's positive flux leaves the volume,
        # so Radioss must see a NEGATIVE Fscale_y. MEASURED on this pair:
        # +70.008599 mJ stored vs -70.008599 mJ.
        _result, starter, _ = self._flux(mlc=70000.0)
        body = _block(starter, _one_header(starter, "/IMPFLUX/"))
        self.assertAlmostEqual(float(body[4][20:40]), -70000.0)

    def test_the_constant_form_gets_a_real_function_never_zero(self):
        # fct_IDT is MANDATORY: fsdcod.F answers ERROR 120 "WRONG REFERENCE TO
        # FUNCTION ID=0" once per card, measured.
        _result, starter, _ = self._flux()
        body = _block(starter, _one_header(starter, "/IMPFLUX/"))
        fid = int(body[2][10:20])
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 1.0), (1000000.0, 1.0)])

    def test_a_stated_curve_is_carried_by_its_own_id(self):
        _result, starter, _ = self._flux(lcid=900)
        body = _block(starter, _one_header(starter, "/IMPFLUX/"))
        self.assertEqual(int(body[2][10:20]), 900)
        # ...and the deck's curve must actually be in the emitted file.
        self.assertIn("/FUNCT/900", starter)

    def test_unequal_per_node_multipliers_are_refused_by_name(self):
        card = ("*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -35000.0, 0, 0) + "\n")
        result, starter, _ = _convert(_deck(SEG1 + card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "PER-NODE flux multipliers"))

    def test_a_temperature_dependent_flux_is_refused_by_name(self):
        card = ("*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                + _row(-900, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0)
                + "\n")
        result, starter, _ = _convert(_deck(SEG1 + CURVE900 + card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "a function of TEMPERATURE"))

    def test_a_user_subroutine_flux_is_refused_by_name(self):
        card = ("*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 3) + "\n"
                + _row(1.0, 2.0, 3.0) + "\n")
        result, starter, _ = _convert(_deck(SEG1 + card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertIn("usrflux",
                      dict(result.recognized_not_emitted)[
                          "BOUNDARY_FLUX_SET"])

    def test_the_segment_spelling_builds_its_own_surface(self):
        # The spelling that was UNRECOGNIZED on master: a probe deck carrying
        # *BOUNDARY_FLUX_SEGMENT came out in "Skipped (unsupported) keywords".
        result, starter, _ = self._flux(spelling="SEGMENT")
        self.assertEqual(result.skipped_keywords, [])
        rows = _data_rows(starter, _one_header(starter, "/SURF/SEG/"))
        self.assertEqual(rows[1:], [_row(1, 5, 6, 7, 8)])
        self.assertEqual(len(_headers(starter, "/IMPFLUX/")), 1)

    def test_a_refused_record_still_gets_its_field_accounting(self):
        # A refusal must not skip the "these cells have no counterpart" pass —
        # on exactly the cards a reader most needs the inventory (#129).
        card = ("*BOUNDARY_FLUX_SET\n" + _row(50, 42) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -35000.0, 1, 0) + "\n")
        result, starter, _ = _convert(_deck(SEG1 + card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "PER-NODE flux multipliers"))
        self.assertTrue(_warned(result, "PSEROD=42"))
        self.assertTrue(_warned(result, "LOC=1"))

    def test_a_missing_segment_set_drops_the_card_and_says_why(self):
        card = ("*BOUNDARY_FLUX_SET\n" + _row(77, 0) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0) + "\n")
        result, starter, _ = _convert(_deck(card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "*SET_SEGMENT 77 is not defined"))

    def test_the_segment_nodes_are_read_POSITIONALLY(self):
        # A blank N3 beside a stated N4 must leave a HOLE, not shift N4 into
        # N3's slot: the first draft filtered blanks out of the list and would
        # have built a triangle 5-6-8 from a card that states 5, 6, _, 8.
        card = ("*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, "", 8) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0) + "\n")
        result, starter, _ = _convert(_deck(card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "not in the converted deck"))

    def test_a_trailing_zero_makes_a_triangle(self):
        # Vol I R17 p.43-63: "To define a triangular segment, set N4 = N3" —
        # and a trailing blank is the other house style. Both must survive; it
        # is only an INTERIOR hole that is malformed.
        for n4 in (0, 7):
            with self.subTest(n4=n4):
                card = ("*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, n4) + "\n"
                        + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0)
                        + "\n")
                _result, starter, _ = _convert(_deck(card))
                rows = _data_rows(starter, _one_header(starter, "/SURF/SEG/"))
                self.assertEqual(rows[1:], [_row(1, 5, 6, 7, 0)])

    def test_the_bare_spelling_names_its_own_ambiguity(self):
        # *BOUNDARY_FLUX with no OPTION is not a card Vol I R17 defines
        # (p.5-46 heads it *BOUNDARY_FLUX_OPTION). It is read as _SEGMENT,
        # which drops a _SET-shaped card by name instead of building a
        # one-node surface out of an SSID.
        card = ("*BOUNDARY_FLUX\n" + _row(50, 0) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0) + "\n")
        result, starter, _ = _convert(_deck(SEG1 + card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "OPTION suffix is MANDATORY"))

    def test_pserod_and_loc_are_named_drops(self):
        card = ("*BOUNDARY_FLUX_SET\n" + _row(50, 42) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 1, 0) + "\n")
        result, starter, _ = _convert(_deck(SEG1 + card))
        self.assertEqual(len(_headers(starter, "/IMPFLUX/")), 1)
        self.assertTrue(_warned(result, "PSEROD=42"))
        self.assertTrue(_warned(result, "LOC=1"))

    # ── MLCk is "the curve multiplier at NODE Nk" (Vol I R17 p.5-48) ────────

    def test_a_triangle_is_not_refused_for_its_absent_fourth_multiplier(self):
        # On a segment this converter itself read as three-noded there is no
        # node N4, so MLC4 is blank by construction and takes p.5-47 Card 2's
        # default of 0. Comparing it against three stated multipliers refused
        # a fully convertible boundary and told the reader to "give all four
        # the same multiplier" — the #125 class. Both triangle spellings, and
        # the _SET form over an all-triangle *SET_SEGMENT.
        tri_set = ("*SET_SEGMENT\n" + _row(51) + "\n"
                   + "       5       6       7       7\n")
        cases = (
            ("trailing blank", "",
             "*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, "") + "\n"
             + _row(0, -70000.0, -70000.0, -70000.0, "", 0, 0) + "\n"),
            ("N4 = N3", "",
             "*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, 7) + "\n"
             + _row(0, -70000.0, -70000.0, -70000.0, "", 0, 0) + "\n"),
            ("all-triangle SET", tri_set,
             "*BOUNDARY_FLUX_SET\n" + _row(51, 0) + "\n"
             + _row(0, -70000.0, -70000.0, -70000.0, "", 0, 0) + "\n"),
        )
        for name, pre, card in cases:
            with self.subTest(spelling=name):
                result, starter, _ = _convert(_deck(pre + card))
                self.assertEqual(len(_headers(starter, "/IMPFLUX/")), 1)
                self.assertFalse(_warned(result, "PER-NODE flux multipliers"))

    def test_a_real_quad_still_refuses_an_unequal_fourth_multiplier(self):
        # The control in the other direction: a segment that HAS four nodes
        # must keep the refusal, whether MLC4 is blank or stated differently.
        for mlc4 in ("", -35000.0):
            with self.subTest(mlc4=mlc4):
                card = ("*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, 8) + "\n"
                        + _row(0, -70000.0, -70000.0, -70000.0, mlc4, 0, 0)
                        + "\n")
                result, starter, _ = _convert(_deck(card))
                self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
                self.assertTrue(_warned(result, "MLC1..MLC4 are PER-NODE"))

    def test_a_mixed_set_compares_all_four(self):
        # One quad in the set means SOME segment has an N4, so MLC4 is read.
        mixed = ("*SET_SEGMENT\n" + _row(52) + "\n"
                 + "       5       6       7       7\n"
                 + "       1       2       3       4\n")
        card = ("*BOUNDARY_FLUX_SET\n" + _row(52, 0) + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, "", 0, 0) + "\n")
        result, starter, _ = _convert(_deck(mixed + card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "MLC1..MLC4 are PER-NODE"))

    def test_unequal_multipliers_within_the_triangle_still_refuse(self):
        card = ("*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, "") + "\n"
                + _row(0, -70000.0, -70000.0, -35000.0, "", 0, 0) + "\n")
        result, starter, _ = _convert(_deck(card))
        self.assertEqual(_headers(starter, "/IMPFLUX/"), [])
        self.assertTrue(_warned(result, "MLC1..MLC3 are PER-NODE"))

    def test_a_stated_mlc4_on_a_triangle_is_named_not_swallowed(self):
        # It cannot be honoured (there is no node N4) and it must not be
        # silently ignored either.
        card = ("*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, "") + "\n"
                + _row(0, -70000.0, -70000.0, -70000.0, -35000.0, 0, 0) + "\n")
        result, starter, _ = _convert(_deck(card))
        self.assertEqual(len(_headers(starter, "/IMPFLUX/")), 1)
        self.assertTrue(_warned(
            result, "MLC4=-35000 names a node the segment(s) do not have"))


# ── (C) *BOUNDARY_CONVECTION → /CONVEC ───────────────────────────────────────

class BoundaryConvectionTests(unittest.TestCase):
    def _convec(self, hlcid=0, hmult=100.0, tlcid=900, tmult=1.0,
                spelling="SET", extra=""):
        card = ("*BOUNDARY_CONVECTION_" + spelling + "\n"
                + (_row(50, 0) if spelling == "SET" else _row(5, 6, 7, 8))
                + "\n" + _row(hlcid, hmult, tlcid, tmult, 0) + "\n")
        pre = (SEG1 if spelling == "SET" else "") + CURVE900 + extra
        return _convert(_deck(pre + card))

    def test_card_is_column_exact_and_h_needs_no_sign_change(self):
        result, starter, _ = self._convec()
        header = _one_header(starter, "/CONVEC/")
        body = _block(starter, header)
        # cfg radioss100/LOADS/convec.cfg: title, %10d x3, %20lf x5.
        self.assertEqual(body[0], f"convec_{_card_id(header)}")
        self.assertEqual(body[1], "#  SURF_ID  FUNCT_ID SENSOR_ID")
        self.assertEqual(int(body[2][0:10]),
                         _card_id(_one_header(starter, "/SURF/SEG/")))
        self.assertEqual(int(body[2][10:20]), 900)      # the T_inf curve
        self.assertEqual(int(body[2][20:30]), 0)
        self.assertEqual(
            body[3],
            "#             ASCALE              FSCALE              TSTART"
            "               TSTOP                   H")
        self.assertAlmostEqual(float(body[4][0:20]), 1.0)       # ASCALE
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)      # FSCALE = TMULT
        self.assertAlmostEqual(float(body[4][40:60]), 0.0)      # TSTART
        self.assertAlmostEqual(float(body[4][60:80]), 0.0)      # TSTOP
        self.assertAlmostEqual(float(body[4][80:100]), 100.0)   # H = HMULT
        self.assertTrue(_warned(result, "carried through with NO sign change"))

    def test_tmult_is_baked_into_the_function_with_fscale_one(self):
        # The /PARITH/ON workaround, /CONVEC flavour: convec.F:234's cache key
        # is 'IFUNC_OLD /= IFUNC .OR. TS_OLD /= TS' with NO FCY_OLD in it (the
        # /PARITH/OFF branch at convec.F:127 HAS it), so two cards sharing one
        # T_inf curve at different Fscale_y silently reuse the first card's
        # T_inf. Measured on converter output: 136.21 mJ against a correct
        # 233.50 mJ, at 0 ERROR / 0 WARNING / NORMAL TERMINATION.
        # Distinct values per slot so a swap between H and FSCALE is visible.
        _result, starter, _ = self._convec(hmult=37.0, tmult=2.5)
        body = _block(starter, _one_header(starter, "/CONVEC/"))
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)
        self.assertAlmostEqual(float(body[4][80:100]), 37.0)
        fid = int(body[2][10:20])
        self.assertNotEqual(fid, 900)
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 2500.0), (1.0, 2500.0)])

    def test_a_unit_tmult_keeps_the_decks_own_curve_id(self):
        # Fscale_y = 1.0 is immune to the missing-FCY_OLD cache key (a stale
        # 1.0 is the same 1.0), so no copy is needed and the deck stays
        # readable.
        result, starter, _ = self._convec(tmult=1.0)
        body = _block(starter, _one_header(starter, "/CONVEC/"))
        self.assertEqual(int(body[2][10:20]), 900)
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)
        # ... and nothing claims a copy was made.
        self.assertFalse(_warned(result, "is COPIED to a synthesized"))

    def test_the_minted_copy_names_both_ids(self):
        # One source card minting a SECOND entity must name BOTH ids (#131).
        result, starter, _ = self._convec(tmult=2.5)
        fid = int(_block(starter, _one_header(starter, "/CONVEC/"))[2][10:20])
        self.assertTrue(_warned(
            result, f"*DEFINE_CURVE 900 is COPIED to a synthesized /FUNCT/{fid}"))

    def test_two_cards_on_one_curve_never_share_a_scaled_function(self):
        # The exact shape the engine defect needs: one TLCID, two multipliers.
        # Both cards must come out at Fscale_y = 1.0 on DIFFERENT functions.
        second = ("*BOUNDARY_CONVECTION_SET\n" + _row(50, 0) + "\n"
                  + _row(0, 100.0, 900, 2.0, 0) + "\n")
        _result, starter, _ = self._convec(tmult=1.0, extra=second)
        headers = _headers(starter, "/CONVEC/")
        self.assertEqual(len(headers), 2)
        fids = []
        for h in headers:
            body = _block(starter, h)
            self.assertAlmostEqual(float(body[4][20:40]), 1.0)
            fids.append(int(body[2][10:20]))
        self.assertEqual(len(set(fids)), 2)
        self.assertEqual(
            sorted(_funct_points(starter, f) for f in fids),
            [[(0.0, 1000.0), (1.0, 1000.0)], [(0.0, 2000.0), (1.0, 2000.0)]])

    def test_a_time_varying_h_is_refused_by_name(self):
        result, starter, _ = self._convec(hlcid=900)
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertTrue(_warned(result, "function of TIME"))

    def test_a_film_temperature_h_is_refused_by_name(self):
        result, starter, _ = self._convec(hlcid=-900)
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertTrue(_warned(result, "FILM temperature"))

    def test_a_constant_t_inf_gets_a_synthesized_function(self):
        _result, starter, _ = self._convec(tlcid=0, tmult=400.0)
        body = _block(starter, _one_header(starter, "/CONVEC/"))
        fid = int(body[2][10:20])
        self.assertNotEqual(fid, 0)
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 400.0), (1000000.0, 400.0)])
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)

    def test_a_blank_tmult_beside_a_curve_is_resolved_to_one_and_named(self):
        result, starter, _ = self._convec(tmult=0.0)
        body = _block(starter, _one_header(starter, "/CONVEC/"))
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)
        self.assertTrue(_warned(result, "but TMULT is blank/zero"))

    def test_a_zero_h_is_refused_rather_than_emitted_as_a_no_op(self):
        result, starter, _ = self._convec(hmult=0.0)
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertTrue(_warned(result, "imposes no convection at all"))

    def test_the_segment_spelling_is_recognized(self):
        result, starter, _ = self._convec(spelling="SEGMENT")
        self.assertEqual(result.skipped_keywords, [])
        self.assertEqual(len(_headers(starter, "/CONVEC/")), 1)


# ── (D) *BOUNDARY_RADIATION → /RADIATION ─────────────────────────────────────

class BoundaryRadiationTests(unittest.TestCase):
    def _radia(self, flcid=0, fmult=SIGMA_MG_MM_S, tlcid=900, tmult=1.0,
               rtype=1, spelling="SET", **kw):
        c1 = (_row(50, rtype, "", "", "", "", 0) if spelling == "SET"
              else _row(5, 6, 7, 8, rtype))
        card = ("*BOUNDARY_RADIATION_" + spelling + "\n" + c1 + "\n"
                + _row(flcid, fmult, tlcid, tmult, 0) + "\n")
        pre = (SEG1 if spelling == "SET" else "") + CURVE900
        return _convert(_deck(pre + card), **kw)

    def test_card_is_column_exact_and_e_is_fmult_over_sigma(self):
        result, starter, _ = self._radia(fmult=2.8352e-11)
        header = _one_header(starter, "/RADIATION/")
        body = _block(starter, header)
        # cfg radioss110/LOADS/radiation.cfg: title, %10d x3, %20lg x5.
        self.assertEqual(body[0], f"radiation_{_card_id(header)}")
        self.assertEqual(body[1], "#  SURF_ID  FUNCT_ID SENSOR_ID")
        self.assertEqual(int(body[2][0:10]),
                         _card_id(_one_header(starter, "/SURF/SEG/")))
        self.assertEqual(int(body[2][20:30]), 0)
        self.assertEqual(
            body[3],
            "#             ASCALE              FSCALE              TSTART"
            "               TSTOP                   E")
        self.assertAlmostEqual(float(body[4][0:20]), 1.0)
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)
        self.assertAlmostEqual(float(body[4][40:60]), 0.0)
        self.assertAlmostEqual(float(body[4][60:80]), 0.0)
        # THE HIGH-RISK CELL: LS-DYNA's FMULT is f = sigma*eps*F with sigma
        # already in it; Radioss's E is a bare emissivity.
        self.assertAlmostEqual(float(body[4][80:100]), 0.5, places=9)
        self.assertTrue(_warned(result, "DIVIDED by sigma"))

    def test_sigma_follows_the_emitted_begin_unit_system(self):
        # kg-m-s: FAC_M = 1, FAC_T = 1 -> sigma = 5.6704e-8. The SAME deck
        # therefore needs a 1000x larger FMULT for the same emissivity, and
        # that is exactly what makes writing FMULT straight through wrong.
        _result, starter, _ = self._radia(fmult=5.6704e-8,
                                          units=("kg", "m", "s"))
        body = _block(starter, _one_header(starter, "/RADIATION/"))
        self.assertAlmostEqual(float(body[4][80:100]), 1.0, places=9)

    def test_an_impossible_emissivity_is_refused_with_both_numbers(self):
        # FMULT written as if it were a bare emissivity: 1.0 / 5.6704e-11 is
        # 1.76e10, which is not an emissivity — and shipping it would be
        # invisible to the starter.
        result, starter, _ = self._radia(fmult=1.0)
        self.assertEqual(_headers(starter, "/RADIATION/"), [])
        self.assertTrue(_warned(result, "not a physical emissivity"))

    def test_t_inf_is_baked_into_the_function_with_fscale_one(self):
        # The /PARITH/ON workaround: radiation.F:249 applies Fscale_y OUTSIDE
        # its cache guard, so a multi-segment card with Fscale_y != 1
        # re-scales T_inf once per segment and reaches NaN (measured).
        result, starter, _ = self._radia(tmult=2.0)
        body = _block(starter, _one_header(starter, "/RADIATION/"))
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)
        fid = int(body[2][10:20])
        self.assertNotEqual(fid, 900)
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 2000.0), (1.0, 2000.0)])
        # One source card minting a SECOND entity names BOTH ids (#131).
        self.assertTrue(_warned(
            result,
            f"*DEFINE_CURVE 900 is COPIED to a synthesized /FUNCT/{fid}"))

    def test_a_unit_tmult_keeps_the_decks_own_curve_id(self):
        # Fscale_y = 1.0 already neutralises the /PARITH/ON defect (1.0
        # re-applied per segment is still 1.0), so no copy is needed and the
        # deck stays readable.
        _result, starter, _ = self._radia(tmult=1.0)
        body = _block(starter, _one_header(starter, "/RADIATION/"))
        self.assertEqual(int(body[2][10:20]), 900)
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)

    def test_a_constant_t_inf_gets_a_synthesized_function(self):
        _result, starter, _ = self._radia(tlcid=0, tmult=1200.0)
        body = _block(starter, _one_header(starter, "/RADIATION/"))
        fid = int(body[2][10:20])
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 1200.0), (1000000.0, 1200.0)])

    def test_a_varying_f_is_refused_by_name(self):
        result, starter, _ = self._radia(flcid=900)
        self.assertEqual(_headers(starter, "/RADIATION/"), [])
        self.assertTrue(_warned(result, "function of TIME"))

    def test_type_2_on_a_set_is_dropped_naming_the_view_factors(self):
        result, starter, _ = self._radia(rtype=2)
        self.assertEqual(_headers(starter, "/RADIATION/"), [])
        self.assertTrue(_warned(result, "TYPE=2 on segment set 50"))
        self.assertTrue(_warned(result, "VIEW FACTORS"))
        # The refusal is PER RECORD, so it must not be filed under the
        # KEYWORD: on a mixed deck that would list the keyword as unemitted
        # while a /RADIATION built from its sibling record is in the .rad.
        self.assertNotIn("BOUNDARY_RADIATION_SET",
                         dict(result.recognized_not_emitted))

    def test_type_2_on_a_segment_is_dropped(self):
        result, starter, _ = self._radia(rtype=2, spelling="SEGMENT")
        self.assertEqual(_headers(starter, "/RADIATION/"), [])
        self.assertTrue(_warned(result, "TYPE=2 on an explicit segment"))
        self.assertTrue(_warned(result, "p.5-117"))

    def test_a_stated_type_zero_takes_the_manual_default(self):
        # Vol I R17 p.5-122 (_SET) and p.5-117 (_SEGMENT) BOTH print TYPE with
        # Default 1 and list exactly one value, "EQ.1: Radiation to
        # environment"; TYPE=2 and p.5-126 belong to the SEPARATE _VF /
        # _ENCLOSURE keywords. So a `0` typed into a defaulted fixed-width
        # integer column — the ordinary way to write "use the default" — is
        # the default, not an unknown radiation type. It used to lose a fully
        # convertible boundary under a message asserting a value the deck
        # never wrote (#130).
        for spelling in ("SET", "SEGMENT"):
            for rtype in (0, 1, ""):
                with self.subTest(spelling=spelling, rtype=rtype):
                    _result, starter, _ = self._radia(rtype=rtype,
                                                      spelling=spelling)
                    self.assertEqual(len(_headers(starter, "/RADIATION/")), 1)

    def test_a_partly_refused_keyword_is_not_listed_as_unemitted(self):
        # One TYPE=1 record and one TYPE=2 record under the same keyword.
        card = ("*BOUNDARY_RADIATION_SET\n" + _row(50, 1) + "\n"
                + _row(0, SIGMA_MG_MM_S, 900, 1.0, 0) + "\n"
                + _row(51, 2) + "\n"
                + _row(0, SIGMA_MG_MM_S, 900, 1.0, 0) + "\n")
        seg2 = ("*SET_SEGMENT\n" + _row(51) + "\n"
                + "       1       2       3       4\n")
        result, starter, _ = _convert(_deck(SEG1 + seg2 + CURVE900 + card))
        self.assertEqual(len(_headers(starter, "/RADIATION/")), 1)
        self.assertTrue(_warned(result, "TYPE=2 on segment set 51"))
        self.assertNotIn("BOUNDARY_RADIATION_SET",
                         dict(result.recognized_not_emitted))

    def test_the_set_spelling_reads_pserod_from_field_seven(self):
        # Vol I R17 p.5-122: *BOUNDARY_RADIATION_SET card 1 is
        # "SSID TYPE _ _ _ _ PSEROD" — PSEROD is field 7, where the FLUX and
        # CONVECTION cards put it in field 2.
        result, _starter, _ = self._radia()
        self.assertFalse(_warned(result, "PSEROD"))
        c1 = _row(50, 1, "", "", "", "", 99)
        card = ("*BOUNDARY_RADIATION_SET\n" + c1 + "\n"
                + _row(0, SIGMA_MG_MM_S, 900, 1.0, 0) + "\n")
        result, _starter, _ = _convert(_deck(SEG1 + CURVE900 + card))
        self.assertTrue(_warned(result, "PSEROD=99"))


class ViewFactorSpellingTests(unittest.TestCase):
    def test_every_view_factor_spelling_is_named_not_skipped(self):
        for kw in ("BOUNDARY_RADIATION_ENCLOSURE",
                   "BOUNDARY_RADIATION_SET_VF_READ",
                   "BOUNDARY_RADIATION_SET_VF_CALCULATE",
                   "BOUNDARY_RADIATION_SET_VF_READ_RESTART",
                   "BOUNDARY_RADIATION_SET_VF_CALCULATE_RESTART",
                   "BOUNDARY_RADIATION_SEGMENT_VF_READ",
                   "BOUNDARY_RADIATION_SEGMENT_VF_CALCULATE",
                   "BOUNDARY_RADIATION_SEGMENT_VF_READ_RESTART",
                   "BOUNDARY_RADIATION_SEGMENT_VF_CALCULATE_RESTART",
                   "BOUNDARY_FLUX_TRAJECTORY"):
            with self.subTest(kw=kw):
                state = _dispatch(f"*KEYWORD\n*{kw}\n" + _row(50, 2) + "\n"
                                  + _row(0, 1.0) + "\n*END\n")
                self.assertEqual(state.skipped_keywords, [])
                self.assertIn(kw, dict(state.recognized_not_emitted))


# ── (A) *CONTROL_SOLUTION / *CONTROL_THERMAL_* ───────────────────────────────

CONVEC_CARD = ("*BOUNDARY_CONVECTION_SET\n" + _row(50, 0) + "\n"
               + _row(0, 100.0, 900, 1.0, 0) + "\n")
THERMAL_LOAD = SEG1 + CURVE900 + CONVEC_CARD


class EngineThermalCardTests(unittest.TestCase):
    def test_soln_1_writes_dt_therm_bare(self):
        deck = _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n" + THERMAL_LOAD)
        result, _starter, engine = _convert(deck)
        self.assertIn("/DT/THERM", engine.splitlines())
        # The value line is deliberately omitted: freform.F:958's zero guard
        # writes the WRONG variable, leaving DTFACTHERM at 0.
        lines = engine.splitlines()
        i = lines.index("/DT/THERM")
        self.assertEqual(lines[i + 1], "#")
        self.assertTrue(_warned(result, "ICODT = ICODR = 7 on EVERY node"))

    def test_soln_0_and_2_write_nothing(self):
        for soln in (0, 2):
            with self.subTest(soln=soln):
                deck = _deck("*CONTROL_SOLUTION\n" + _row(soln) + "\n"
                             + THERMAL_LOAD)
                _result, _starter, engine = _convert(deck)
                self.assertNotIn("/DT/THERM", engine)

    def test_soln_1_without_a_thermal_solve_refuses_and_says_why(self):
        # /DT/THERM on a deck that integrates nothing would freeze the whole
        # model for no reason.
        deck = ("*KEYWORD\n*CONTROL_TERMINATION\n" + _row(0.001) + "\n"
                "*CONTROL_SOLUTION\n" + _row(1) + "\n*END\n")
        result, _starter, engine = _convert(deck)
        self.assertNotIn("/DT/THERM", engine)
        self.assertTrue(_warned(result, "this deck arms no thermal solve"))

    def test_soln_1_with_ams_is_refused_naming_the_hard_stop(self):
        # freform.F:1327-1330: IDT_THERM == 1 .AND. IDTMINS /= 0 is
        # ANCMSG(301) + ARRET(0).
        deck = _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n"
                     "*CONTROL_TIMESTEP\n" + _row(0.0, 0.9, 0, 0.0, -1.0e-4)
                     + "\n" + THERMAL_LOAD)
        result, _starter, engine = _convert(deck, ams=True)
        self.assertNotIn("/DT/THERM", engine)
        self.assertIn("/DT/AMS", engine)
        self.assertTrue(_warned(result, "ANCMSG(301)"))

    def test_the_endtim_window_guard_fires_when_it_is_too_short(self):
        # MEASURED on this exact coupon: ENDTIM 1e-3 against a thermal step of
        # 0.03611 gave ONE cycle at DT1 = 0 and HEAT STORED 0.0000000, at
        # 0 ERROR / 0 WARNING / NORMAL TERMINATION.
        deck = _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n" + THERMAL_LOAD)
        result, _starter, _engine = _convert(deck)
        self.assertTrue(_warned(result, "is NOT larger than one thermal time"))
        self.assertTrue(any("0.03611" in w for w in result.warnings))

    def test_the_surface_rate_guard_fires_on_the_diverging_shape(self):
        # MEASURED: the same coupon at ENDTIM 0.2 diverged to HEAT STORED
        # 7 901 590.2 mJ where the physical saturation is 2527.7.
        deck = _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n"
                     + THERMAL_LOAD).replace(_row(0.001), _row(0.2))
        result, _starter, _engine = _convert(deck)
        self.assertTrue(_warned(result, "/DT/THERM is UNSAFE on this deck"))
        # ...and the prescription it gives is the one that was measured to work
        # (0.225 -> HEAT STORED 2527.6994 vs an analytic 2527.7000). This deck
        # loads ONE face, so the loaded-face concentration is 1 and the factor
        # is the unscaled 0.25*tau — see the six-face twin below.
        self.assertTrue(any("about 0.225 puts the step" in w
                            for w in result.warnings))
        self.assertFalse(_warned(result, "loaded face(s) per element"))

    def test_a_body_loaded_on_every_face_gets_a_smaller_prescription(self):
        # A ONE-ELEMENT body with all six faces convecting: each corner node
        # carries 3 loaded segments and is fed by 1 element, so its real
        # surface time constant is tau/(2*3) = RHO0_CP*(V/A)/h, six times
        # shorter than tau. The old prescription (0.25*tau) is 1.5x that and
        # OVERSHOOTS the environment temperature on the first step; scaling by
        # the concentration puts it back inside a monotone approach.
        faces = ("*SET_SEGMENT\n" + _row(50) + "\n"
                 + "       5       6       7       8\n"
                 + "       1       2       3       4\n"
                 + "       1       2       6       5\n"
                 + "       2       3       7       6\n"
                 + "       3       4       8       7\n"
                 + "       4       1       5       8\n")
        deck = _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n"
                     + faces + CURVE900 + CONVEC_CARD).replace(
            _row(0.001), _row(0.2))
        result, starter, _engine = _convert(deck)
        self.assertEqual(len(_data_rows(
            starter, _one_header(starter, "/SURF/SEG/"))) - 1, 6)
        self.assertTrue(_warned(result, "/DT/THERM is UNSAFE on this deck"))
        self.assertTrue(_warned(result, "3 loaded face(s) per element"))
        # 0.9 * 0.25 * (tau/3) / dt_th with tau = dt_th = 0.03611.
        self.assertTrue(any("about 0.075 puts the step" in w
                            for w in result.warnings))

    def test_tsf_writes_the_therm_card(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 5.6704e-11) + "\n"
                     + _row(0, 500, 1.0e-10, 1.0e-6, 1.0, "", "", 10.0) + "\n"
                     + THERMAL_LOAD)
        result, _starter, engine = _convert(deck)
        lines = engine.splitlines()
        i = lines.index("/THERM")
        self.assertEqual(lines[i + 1], "10")
        self.assertTrue(_warned(result, "THEACCFACT"))

    def test_tsf_of_one_writes_nothing(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 0.0) + "\n"
                     + _row(0, 500, 1.0e-10, 1.0e-6, 1.0, "", "", 1.0) + "\n"
                     + THERMAL_LOAD)
        _result, _starter, engine = _convert(deck)
        self.assertNotIn("/THERM\n", engine)

    def test_a_negative_tsf_is_a_named_drop(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 0.0) + "\n"
                     + _row(0, 500, 1.0e-10, 1.0e-6, 1.0, "", "", -900.0)
                     + "\n" + THERMAL_LOAD)
        result, _starter, engine = _convert(deck)
        self.assertNotIn("/THERM\n", engine)
        self.assertTrue(_warned(result, "makes |TSF| a load curve id"))

    def test_tsf_on_an_implicit_deck_writes_nothing(self):
        # THEACCFACT is read by frethermal.F either way, but everything that
        # consumes it is called from the EXPLICIT loop in resol.F.
        deck = _deck("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
                     "*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 0.0) + "\n"
                     + _row(0, 500, 1.0e-10, 1.0e-6, 1.0, "", "", 10.0) + "\n"
                     + THERMAL_LOAD)
        result, _starter, engine = _convert(deck)
        self.assertNotIn("/THERM\n", engine)
        self.assertTrue(_warned(result, "there is nothing to speed up"))

    def test_tsf_without_a_thermal_solve_writes_nothing(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 0.0) + "\n"
                     + _row(0, 500, 1.0e-10, 1.0e-6, 1.0, "", "", 10.0) + "\n")
        result, _starter, engine = _convert(deck)
        self.assertNotIn("/THERM\n", engine)
        self.assertTrue(_warned(result, "there is nothing for it to speed up"))


class ControlThermalSolverTests(unittest.TestCase):
    def test_every_card_1_field_lands_in_its_own_slot(self):
        # Distinct values per slot so a transposition is visible. Field 4 is
        # the OBSOLETE cgtol column and must NOT be read (Vol I R17 p.12-579
        # Remark 11; the header on p.12-567 still prints it).
        state = _dispatch("*KEYWORD\n*CONTROL_THERMAL_SOLVER\n"
                          + _row(1, 2, 17, 0.5, 1, 3.0, 0.7, 5.67e-11) + "\n"
                          + _row(4, 6, 1.0e-9, 1.0e-5, 0.0, "", "", 8.0) + "\n"
                          + _row(5, 0.25, 2, "", 7) + "\n*END\n")
        ct = state.ctrl_thermal_solver
        self.assertEqual(ct.atype, 1)
        self.assertEqual(ct.ptype, 2)
        self.assertEqual(ct.solver, 17)
        self.assertEqual(ct.gpt, 1)
        self.assertAlmostEqual(ct.eqheat, 3.0)
        self.assertAlmostEqual(ct.fwork, 0.7)
        self.assertAlmostEqual(ct.sbc, 5.67e-11)
        # SOLVER == 17 selects card 2b: NINNER/NOUTER, not MAXITR/OMEGA/TSF.
        self.assertEqual(ct.msglvl, 4)
        self.assertEqual(ct.ninner, 6)
        self.assertEqual(ct.nouter, 0)
        self.assertEqual(ct.maxitr, 0)
        self.assertAlmostEqual(ct.tsf, 0.0)
        self.assertEqual(ct.mxdmp, 5)
        self.assertAlmostEqual(ct.dtvf, 0.25)
        self.assertEqual(ct.varden, 2)
        self.assertEqual(ct.ncycl, 7)

    def test_card_2a_is_read_when_solver_is_not_17(self):
        state = _dispatch("*KEYWORD\n*CONTROL_THERMAL_SOLVER\n"
                          + _row(1, 1, 11, "", 0, 1.0, 1.0, 0.0) + "\n"
                          + _row(4, 6, 1.0e-9, 1.0e-5, 1.5, "", "", 8.0) + "\n"
                          + "*END\n")
        ct = state.ctrl_thermal_solver
        self.assertEqual(ct.maxitr, 6)
        self.assertAlmostEqual(ct.omega, 1.5)
        self.assertAlmostEqual(ct.tsf, 8.0)
        self.assertEqual(ct.ninner, 0)

    def test_fwork_drives_efrac_on_every_heat_mat(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 0.6, 0.0) + "\n"
                     + THERMAL_LOAD)
        _result, starter, _ = _convert(deck)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[1][60:80]), 0.6)

    def test_a_zero_fwork_becomes_one(self):
        # Both sides use the same convention: "EQ.0.0: Use default value 1.0"
        # (Vol I R17 p.12-575) and hm_read_therm.F:239-241 clamps 0 -> 1.
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 0.0, 0.0) + "\n"
                     + THERMAL_LOAD)
        _result, starter, _ = _convert(deck)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[1][60:80]), 1.0)

    def test_without_the_card_efrac_stays_at_the_no_source_value(self):
        _result, starter, _ = _convert(_deck(THERMAL_LOAD))
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[1][60:80]), 1.0e-20)

    def test_sbc_is_cross_checked_against_the_derived_sigma(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 5.67e-8) + "\n"
                     + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "SBC="))

    def test_a_matching_sbc_is_not_warned_about(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 1.0, 5.6704e-11) + "\n"
                     + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertFalse(_warned(result, "SBC="))

    def test_the_unmappable_fields_are_named_one_by_one(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(0, 2, 13, "", 1, 4.2, 1.0, 0.0) + "\n"
                     + _row(2, 99, 1.0e-9, 1.0e-5, 1.5, "", "", 0.0) + "\n"
                     + _row(5, 0.25, 2, "", 7) + "\n" + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        joined = " ".join(result.warnings)
        for name in ("ATYPE", "PTYPE", "SOLVER", "GPT", "EQHEAT", "MSGLVL",
                     "MAXITR", "OMEGA", "VARDEN", "DTVF", "NCYCL", "MXDMP"):
            self.assertIn(name, joined, name)


class ControlThermalDropTests(unittest.TestCase):
    def test_timestep_names_all_eight_fields(self):
        state = _dispatch("*KEYWORD\n*CONTROL_THERMAL_TIMESTEP\n"
                          + _row(1, 0.5, 1.0e-5, -11, -12, -13, 0.4, 14)
                          + "\n*END\n")
        text = dict(state.recognized_not_emitted)["CONTROL_THERMAL_TIMESTEP"]
        for cell in ("TS=1", "TIP=0.5", "ITS=1e-05", "TMIN=-11", "TMAX=-12",
                     "DTEMP=-13", "TSCP=0.4", "LCTS=14"):
            self.assertIn(cell, text, cell)
        # The registry used to promise a card that does not exist.
        self.assertIn("/DTTHERM", text)
        self.assertIn("no such engine keyword exists", text)

    def test_nonlinear_names_all_seven_fields(self):
        state = _dispatch("*KEYWORD\n*CONTROL_THERMAL_NONLINEAR\n"
                          + _row(11, 1.0e-4, 0.5, 1, 0.3, 2, 90.0)
                          + "\n*END\n")
        text = dict(state.recognized_not_emitted)["CONTROL_THERMAL_NONLINEAR"]
        for cell in ("REFMAX=11", "TOL=0.0001", "DCP=0.5", "LUMPBC=1",
                     "THLSTL=0.3", "NLTHPR=2", "PHCHPN=90.0"):
            self.assertIn(cell, text, cell)

    def test_control_solution_drops_its_vectorisation_cells_by_name(self):
        state = _dispatch("*KEYWORD\n*CONTROL_SOLUTION\n"
                          + _row(2, 96, 1, 200, 1, 0, 1, 1) + "\n*END\n")
        joined = " ".join(state.warnings)
        for cell in ("NLQ=96", "ISNAN=1", "LCINT=200", "LCACC=1", "NOCOPY=1",
                     "CRVP=1"):
            self.assertIn(cell, joined, cell)


# ── (E) The richer thermal materials ─────────────────────────────────────────

class ThermalMaterialTdTests(unittest.TestCase):
    #: Steel-like k(T), monotonically falling. Constant specific heat so
    #: RHO0_CP is exact.
    TD = ("*MAT_THERMAL_ISOTROPIC_TD\n"
          + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
          + _row(300.0, 500.0, 700.0, 900.0) + "\n"
          + _row("4.60E+8", "4.60E+8", "4.60E+8", "4.60E+8") + "\n"
          + _row(50.0, 44.0, 38.0, 32.0) + "\n")

    def _deck_td(self, mat=None):
        base = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", mat if mat is not None else self.TD)
        return base.replace("{EXTRA}", THERMAL_LOAD)

    def test_the_table_lands_field_by_field(self):
        state = _dispatch("*KEYWORD\n" + self.TD + "*END\n")
        tm = state.mat_thermal_iso_td[9]
        self.assertEqual(tm.temps, [300.0, 500.0, 700.0, 900.0])
        self.assertEqual(tm.ks, [50.0, 44.0, 38.0, 32.0])
        self.assertEqual(tm.cps, [4.6e8] * 4)
        self.assertAlmostEqual(tm.tro, 7.85e-9)

    def test_the_fit_is_exact_on_a_linear_table(self):
        # k = 59 - 0.03*T through all four points, so the least-squares line is
        # the table itself and AL/BL mirror it (T1 is blank here — /MAT_ELASTIC
        # states no melting temperature).
        _result, starter, _ = _convert(self._deck_td())
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][0:20]), 0.0)        # T0
        self.assertAlmostEqual(float(body[0][20:40]), 3.611)     # RHO0_CP
        self.assertAlmostEqual(float(body[0][40:60]), 59.0, places=6)   # AS
        self.assertAlmostEqual(float(body[0][60:80]), -0.03, places=9)  # BS
        self.assertAlmostEqual(float(body[1][0:20]), 0.0)        # T1
        self.assertAlmostEqual(float(body[1][20:40]), 59.0, places=6)   # AL
        self.assertAlmostEqual(float(body[1][40:60]), -0.03, places=9)  # BL

    def test_the_warning_states_all_six_coefficients_and_the_deviation(self):
        result, _starter, _ = _convert(self._deck_td())
        hit = [w for w in result.warnings if "is FITTED onto" in w]
        self.assertEqual(len(hit), 1)
        for token in ("AS = 59", "BS = -0.03", "AL = 59", "BL = -0.03",
                      "Maximum deviation", "RHO0_CP = 3.611"):
            self.assertIn(token, hit[0], token)

    def test_a_wildly_varying_specific_heat_is_refused_by_name(self):
        mat = ("*MAT_THERMAL_ISOTROPIC_TD\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(300.0, 900.0) + "\n"
               + _row("4.60E+8", "1.60E+9") + "\n"
               + _row(50.0, 32.0) + "\n")
        result, starter, _ = _convert(self._deck_td(mat))
        self.assertTrue(_warned(result, "the specific heat varies by a factor"))
        # No conductivity is written either — the material is refused whole.
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][40:60]), 0.0)

    def test_a_refused_material_is_not_called_unbound(self):
        # The no-conductivity fallback used to assert "no *MAT_THERMAL_* is
        # bound to this material (no *PART TMID names one)" — a FALSE premise
        # on a material that is bound and merely unconvertible (the #129 class:
        # a true conclusion resting on a false premise still misinforms).
        mat = ("*MAT_THERMAL_ISOTROPIC_TD\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(300.0, 900.0) + "\n"
               + _row("4.60E+8", "1.60E+9") + "\n"
               + _row(50.0, 32.0) + "\n")
        result, _starter, _ = _convert(self._deck_td(mat))
        self.assertFalse(_warned(result, "no *PART TMID names one"))
        self.assertTrue(_warned(result, "IS bound to this material through a "
                                        "*PART TMID but could NOT be "
                                        "converted"))

    def test_one_point_is_refused(self):
        mat = ("*MAT_THERMAL_ISOTROPIC_TD\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(300.0) + "\n" + _row("4.60E+8") + "\n" + _row(50.0)
               + "\n")
        result, _starter, _ = _convert(self._deck_td(mat))
        self.assertTrue(_warned(result, "fewer than two"))

    def test_the_lc_spelling_samples_its_curves(self):
        # The curves are stated AFTER the material on purpose: dispatch is
        # sequential, so sampling them at parse time (the first draft) left a
        # deck in this ordinary order with no conductivity at all. They are
        # sampled in the writer prepass instead.
        mat = ("*MAT_THERMAL_ISOTROPIC_TD_LC\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(801, 802, 0, 0, 0) + "\n"
               "*DEFINE_CURVE\n" + _row(801) + "\n"
               + _row16(300.0, "4.60E+8") + "\n"
               + _row16(900.0, "4.60E+8") + "\n"
               "*DEFINE_CURVE\n" + _row(802) + "\n"
               + _row16(300.0, 50.0) + "\n"
               + _row16(900.0, 32.0) + "\n")
        result, starter, _ = _convert(self._deck_td(mat))
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][40:60]), 59.0, places=6)
        self.assertAlmostEqual(float(body[0][60:80]), -0.03, places=9)
        self.assertTrue(_warned(result, "Sampled from curves HCLC=801"))

    def test_a_history_variable_property_is_refused_by_name(self):
        mat = ("*MAT_THERMAL_ISOTROPIC_TD_LC\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(801, 802, 0, 7, 0) + "\n"
               "*DEFINE_CURVE\n" + _row(801) + "\n"
               + _row16(300.0, "4.60E+8") + "\n"
               + _row16(900.0, "4.60E+8") + "\n"
               "*DEFINE_CURVE\n" + _row(802) + "\n"
               + _row16(300.0, 50.0) + "\n"
               + _row16(900.0, 32.0) + "\n")
        result, _starter, _ = _convert(self._deck_td(mat))
        self.assertTrue(_warned(result, "TCHSV=7"))
        self.assertTrue(_warned(result, "MECHANICAL HISTORY VARIABLE"))


class ThermalMaterialOrthotropicTests(unittest.TestCase):
    def _ortho(self, k1=45.0, k2=45.0, k3=45.0, aopt=0.0):
        mat = ("*MAT_THERMAL_ORTHOTROPIC\n"
               + _row(9, "7.85E-9", 0, 0.0, aopt, 0.0, 0.0) + "\n"
               + _row("4.60E+8", k1, k2, k3) + "\n"
               + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
               + _row(0.0, 1.0, 0.0) + "\n")
        base = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", mat)
        return _convert(base.replace("{EXTRA}", THERMAL_LOAD))

    def test_the_fields_land_in_their_own_slots(self):
        # AOPT sits in field 5 here, where the ISOTROPIC card has TLAT — the
        # two layouts are not the same card with an extra column.
        state = _dispatch("*KEYWORD\n*MAT_THERMAL_ORTHOTROPIC\n"
                          + _row(9, "7.85E-9", 77, 1.5, 2.0, 800.0, 250.0)
                          + "\n" + _row("4.60E+8", 41.0, 42.0, 43.0) + "\n"
                          + _row(0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                          + _row(0.0, 1.0, 0.0) + "\n*END\n")
        tm = state.mat_thermal_ortho[9]
        self.assertEqual(tm.tgrlc, 77)
        self.assertAlmostEqual(tm.tgmult, 1.5)
        self.assertAlmostEqual(tm.aopt, 2.0)
        self.assertAlmostEqual(tm.tlat, 800.0)
        self.assertAlmostEqual(tm.hlat, 250.0)
        self.assertAlmostEqual(tm.hc, 4.6e8)
        self.assertAlmostEqual(tm.k1, 41.0)
        self.assertAlmostEqual(tm.k2, 42.0)
        self.assertAlmostEqual(tm.k3, 43.0)

    def test_an_isotropic_in_fact_card_converts(self):
        result, starter, _ = self._ortho(aopt=2.0)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][40:60]), 45.0)
        self.assertAlmostEqual(float(body[0][20:40]), 3.611)
        self.assertTrue(_warned(result, "ISOTROPIC in fact"))

    def test_three_different_conductivities_are_refused_with_the_values(self):
        result, starter, _ = self._ortho(k1=45.0, k2=30.0, k3=15.0)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][40:60]), 0.0)
        self.assertTrue(_warned(result, "K1=45, K2=30, K3=15"))
        self.assertTrue(_warned(result, "/HEAT/MAT is ISOTROPIC"))


class HeatMatSecondSegmentTests(unittest.TestCase):
    def test_al_and_bl_mirror_as_and_bs(self):
        # AL = BL = 0.0 beside a real T1 gives a /DT/THERM run an UNBOUNDED
        # thermal step above the melt point (dttherm.F90:105/116 divides by
        # max(akk, 1e-20)) and a zero interface conductance CONDE. The heat
        # FLOW never reads those cells (stherm.F:106 is AS + BS*T).
        _result, starter, _ = _convert(_deck(THERMAL_LOAD))
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][40:60]), 45.0)   # AS
        self.assertAlmostEqual(float(body[1][20:40]), 45.0)   # AL
        self.assertAlmostEqual(float(body[1][40:60]), 0.0)    # BL = BS


# ── (F) *LOAD_THERMAL_*_ELEMENT ──────────────────────────────────────────────

TWO_BRICKS = (
    "*KEYWORD\n"
    "*CONTROL_TERMINATION\n" + _row(0.001) + "\n"
    "*NODE\n"
    "         1             0.0             0.0             0.0\n"
    "         2             1.0             0.0             0.0\n"
    "         3             1.0             1.0             0.0\n"
    "         4             0.0             1.0             0.0\n"
    "         5             0.0             0.0             1.0\n"
    "         6             1.0             0.0             1.0\n"
    "         7             1.0             1.0             1.0\n"
    "         8             0.0             1.0             1.0\n"
    "         9             0.0             0.0             2.0\n"
    "        10             1.0             0.0             2.0\n"
    "        11             1.0             1.0             2.0\n"
    "        12             0.0             1.0             2.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "       2       1       5       6       7       8       9      10      11      12\n"
    "*PART\n"
    "col\n"
    + _row(1, 1, 1, 0, 0, 0, 0, 9) + "\n"
    "*SECTION_SOLID\n" + _row(1, 1) + "\n"
    "*MAT_ELASTIC\n" + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
    "*MAT_THERMAL_ISOTROPIC\n"
    + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
    + _row("4.60E+8", 45.0) + "\n"
    "{EXTRA}"
    "*END\n"
)


class LoadThermalElementTests(unittest.TestCase):
    def test_a_uniform_field_converts_onto_the_elements_own_nodes(self):
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID\n"
            + _row(1, 500.0) + "\n" + _row(2, 500.0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(len(_headers(starter, "/IMPTEMP/")), 1)
        grp = _data_rows(starter, _one_header(starter, "/GRNOD/NODE/"))
        ids = sorted(int(t) for ln in grp[1:] for t in ln.split())
        self.assertEqual(ids, list(range(1, 13)))
        self.assertTrue(_warned(result, "-> /IMPTEMP over the elements' OWN"))

    def test_a_collision_drops_the_card_and_names_the_shared_nodes(self):
        # Nodes 5-8 belong to both elements, which state different
        # temperatures — LS-DYNA holds two ELEMENT fields there and /IMPTEMP
        # can hold one.
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID\n"
            + _row(1, 500.0) + "\n" + _row(2, 700.0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPTEMP/"), [])
        self.assertTrue(_warned(result, "OVER-DETERMINED at 4 shared node"))

    def test_the_variable_spelling_carries_ts_tb_and_the_curve(self):
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            CURVE900
            + "*LOAD_THERMAL_VARIABLE_ELEMENT_SOLID\n"
            + _row(1, 0.5, 20.0, 900) + "\n" + _row(2, 0.5, 20.0, 900) + "\n")
        _result, starter, _ = _convert(deck)
        body = _block(starter, _one_header(starter, "/IMPTEMP/"))
        fid = int(body[2][0:10])
        # T = TB + TS*f(t) = 20 + 0.5*1000 = 520, baked into a synthesized copy.
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 520.0), (1.0, 520.0)])
        self.assertAlmostEqual(float(body[4][20:40]), 1.0)

    def test_an_element_card_is_not_read_as_the_model_wide_t0(self):
        # An element record carries sid = 0 (it names no set) beside an
        # EXPLICIT node list, so a t = 0 scan testing sid alone would read a
        # handful of elements' temperature as the WHOLE MODEL's initial state
        # and write it into /HEAT/MAT's T0.
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID\n"
            + _row(1, 500.0) + "\n" + _row(2, 500.0) + "\n")
        _result, starter, _ = _convert(deck)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][0:20]), 0.0)
        # ...while a genuinely model-wide driver DOES set it.
        wide = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT\n" + _row(0, 0, 0) + "\n"
            + _row(500.0) + "\n")
        _result, starter, _ = _convert(wide)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[0][0:20]), 500.0)

    def test_an_element_of_the_wrong_family_is_dropped_by_name(self):
        # Element ids are per-FAMILY namespaces: a _BEAM card must not find a
        # SOLID with the same id (the #125/#128 two-namespace class).
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT_ELEMENT_BEAM\n" + _row(1, 500.0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPTEMP/"), [])
        self.assertTrue(_warned(result, "no BEAM elements at all"))

    def test_a_missing_element_id_is_named(self):
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID\n"
            + _row(1, 500.0) + "\n" + _row(77, 500.0) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "[77] are not in the converted deck"))

    def test_every_option_spelling_is_registered(self):
        for stem in ("CONSTANT", "VARIABLE"):
            for fam in ("BEAM", "SHELL", "SOLID", "TSHELL"):
                kw = f"LOAD_THERMAL_{stem}_ELEMENT_{fam}"
                with self.subTest(kw=kw):
                    self.assertIn(kw, RARE_MATERIAL_KEYWORDS)
                    state = _dispatch(f"*KEYWORD\n*{kw}\n"
                                      + _row(1, 500.0) + "\n*END\n")
                    self.assertEqual(state.skipped_keywords, [])
                    self.assertEqual(len(state.load_thermal_elements), 1)
                    self.assertEqual(state.load_thermal_elements[0].family, fam)


# ── (G) The gate and the outputs ─────────────────────────────────────────────

class ThermalSolveGateTests(unittest.TestCase):
    def test_a_convec_only_deck_arms_the_solve_and_its_outputs(self):
        result, starter, engine = _convert(_deck(THERMAL_LOAD))
        self.assertEqual(len(_headers(starter, "/CONVEC/")), 1)
        self.assertIn("/ANIM/NODA/TEMP", engine.splitlines())
        self.assertEqual(len(_headers(starter, "/TH/NODE/")), 1)
        self.assertEqual(result.skipped_keywords, [])

    def test_the_th_group_covers_the_loaded_segment_nodes(self):
        # A /CONVEC-only deck has NO driven nodes at all, so without this the
        # deck would run a real thermal solve and write no history.
        _result, starter, _ = _convert(_deck(THERMAL_LOAD))
        body = _block(starter, _one_header(starter, "/TH/NODE/"))
        ids = sorted(int(ln) for ln in body[2:] if ln.strip().isdigit())
        self.assertEqual(ids, [5, 6, 7, 8])

    def test_no_th_channel_is_invented_for_the_boundary_cards(self):
        # hm_read_thgrou.F:1255 gives /TH/SURF exactly AREA, MASSFLOW,
        # VELOCITY, P, A, MASS — there is no thermal channel to wire (#122).
        _result, starter, _ = _convert(_deck(THERMAL_LOAD))
        self.assertEqual(_headers(starter, "/TH/SURF"), [])

    def test_a_boundary_without_a_heat_mat_emits_nothing_and_says_why(self):
        # ITHERM_FE gates CONVEC/RADIATION/FIXFLUX (resol.F:2994/3006/3025) and
        # only /HEAT/MAT sets it, so the card would be read, echoed and inert.
        deck = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", "").replace(
            _row(1, 1, 1, 0, 0, 0, 0, 9), _row(1, 1, 1)).replace(
            "{EXTRA}", THERMAL_LOAD)
        result, starter, engine = _convert(deck)
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertNotIn("/ANIM/NODA/TEMP", engine)
        self.assertTrue(_warned(result, "no thermal solve is armed at all"))

    def test_a_conduction_free_heat_mat_is_named(self):
        # AS = BS = 0 means the heat cannot leave the loaded surface.
        deck = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n",
            "*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 0, 1.2e-5) + "\n"
        ).replace(_row(1, 1, 1, 0, 0, 0, 0, 9), _row(1, 1, 1)).replace(
            "{EXTRA}", THERMAL_LOAD)
        result, starter, _ = _convert(deck)
        self.assertEqual(len(_headers(starter, "/CONVEC/")), 1)
        self.assertTrue(_warned(result, "NO CONDUCTIVITY"))

    def test_a_boundary_makes_a_therm_stress_live_not_inert(self):
        deck = BRICK.replace(
            "{EXTRA}",
            "*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 0, 1.2e-5) + "\n"
            + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertFalse(_warned(result, "is INERT on this deck"))

    def test_the_implicit_guard_reaches_a_boundary_only_deck(self):
        deck = _deck("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
                     + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(
            result, "the field they describe will not develop"))

    def test_one_surface_is_shared_by_every_card_on_one_segment_set(self):
        deck = _deck(SEG1 + CURVE900 + CONVEC_CARD
                     + "*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                     + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0)
                     + "\n")
        _result, starter, _ = _convert(deck)
        self.assertEqual(len(_headers(starter, "/SURF/SEG/")), 1)
        self.assertEqual(len(_headers(starter, "/CONVEC/")), 1)
        self.assertEqual(len(_headers(starter, "/IMPFLUX/")), 1)


class ThermalUnitDerivationTests(unittest.TestCase):
    def test_sigma_is_derived_from_the_begin_work_line(self):
        from k2rad.writer.thermal import _sigma_deck
        state = ConversionState()
        for units, expect in ((("Mg", "mm", "s"), 5.6704e-11),
                              (("kg", "m", "s"), 5.6704e-8),
                              (("g", "cm", "s"), 5.6704e-5),
                              (("kg", "mm", "ms"), 5.6704e-17)):
            with self.subTest(units=units):
                state.units = units
                self.assertAlmostEqual(_sigma_deck(state) / expect, 1.0,
                                       places=9)

    def test_an_unreadable_unit_label_refuses_rather_than_guessing(self):
        from k2rad.writer.thermal import _sigma_deck
        state = ConversionState()
        state.units = ("slug", "in", "s")
        self.assertIsNone(_sigma_deck(state))

    def test_the_thermal_step_estimate_matches_the_engine(self):
        # MEASURED: the engine chose TIME-STEP 0.3611E-01 on exactly this
        # coupon (1 mm brick, RHO0_CP 3.611, AS 45, DTFACTHERM 0.9).
        from k2rad.writer.thermal import _thermal_step_estimate
        state = ConversionState()
        state.heat_mat_cards[1] = (0.0, 3.611, 45.0, 0.0, 0.0, 45.0, 0.0, 1e-20)
        from k2rad.state import NodeData, SolidElem
        for nid, xyz in ((1, (0, 0, 0)), (2, (1, 0, 0)), (3, (1, 1, 0)),
                         (4, (0, 1, 0)), (5, (0, 0, 1)), (6, (1, 0, 1)),
                         (7, (1, 1, 1)), (8, (0, 1, 1))):
            state.nodes[nid] = NodeData(*[float(v) for v in xyz])
        state.solid_elems.append(
            SolidElem(eid=1, pid=1, nodes=[1, 2, 3, 4, 5, 6, 7, 8]))
        self.assertAlmostEqual(_thermal_step_estimate(state), 0.036110,
                               places=6)


# ── Registry / offset coverage ───────────────────────────────────────────────

class DispatchAndOffsetCoverageTests(unittest.TestCase):
    #: Every spelling this batch CONVERTS must have a real offset spec; every
    #: spelling it warn-drops must have none (an unmodelled card stack must not
    #: have its cells rewritten by position — the *AIRBAG rule).
    CONVERTED = (
        "BOUNDARY_FLUX", "BOUNDARY_FLUX_SET", "BOUNDARY_FLUX_SEGMENT",
        "BOUNDARY_CONVECTION", "BOUNDARY_CONVECTION_SET",
        "BOUNDARY_CONVECTION_SEGMENT",
        "BOUNDARY_RADIATION", "BOUNDARY_RADIATION_SET",
        "BOUNDARY_RADIATION_SEGMENT",
        "MAT_THERMAL_ORTHOTROPIC", "MAT_T02",
        "MAT_THERMAL_ISOTROPIC_TD", "MAT_T03",
        "MAT_THERMAL_ISOTROPIC_TD_LC", "MAT_T10", "MAT_T01",
        "LOAD_THERMAL_CONSTANT_ELEMENT_BEAM",
        "LOAD_THERMAL_CONSTANT_ELEMENT_SHELL",
        "LOAD_THERMAL_CONSTANT_ELEMENT_SOLID",
        "LOAD_THERMAL_CONSTANT_ELEMENT_TSHELL",
        "LOAD_THERMAL_VARIABLE_ELEMENT_BEAM",
        "LOAD_THERMAL_VARIABLE_ELEMENT_SHELL",
        "LOAD_THERMAL_VARIABLE_ELEMENT_SOLID",
        "LOAD_THERMAL_VARIABLE_ELEMENT_TSHELL",
    )
    DROPPED = (
        "CONTROL_THERMAL_TIMESTEP", "CONTROL_THERMAL_NONLINEAR",
        "CONTROL_THERMAL_SOLVER", "CONTROL_THERMAL_FORMING",
        "CONTROL_THERMAL_EIGENVALUE", "CONTROL_SOLUTION",
        "MAT_THERMAL_CWM",
        "LOAD_THERMAL_VARIABLE_BEAM", "LOAD_THERMAL_VARIABLE_BEAM_SET",
        "LOAD_THERMAL_VARIABLE_SHELL", "LOAD_THERMAL_VARIABLE_SHELL_SET",
        "LOAD_THERMAL_RSW", "LOAD_THERMAL_TOPAZ", "LOAD_THERMAL_D3PLOT",
        "LOAD_THERMAL_BINOUT",
        "BOUNDARY_FLUX_TRAJECTORY", "BOUNDARY_RADIATION_ENCLOSURE",
    )

    def test_every_converted_spelling_has_an_offset_spec(self):
        for kw in self.CONVERTED:
            with self.subTest(kw=kw):
                self.assertIn(kw, RARE_MATERIAL_KEYWORDS)
                self.assertIn(kw, _OFFSET_SPECS)

    def test_every_dropped_spelling_has_none(self):
        for kw in self.DROPPED:
            with self.subTest(kw=kw):
                self.assertIn(kw, RARE_MATERIAL_KEYWORDS)
                self.assertNotIn(kw, _OFFSET_SPECS)

    def test_no_batch_spelling_lands_in_skipped_keywords(self):
        for kw in self.CONVERTED + self.DROPPED:
            with self.subTest(kw=kw):
                state = _dispatch(f"*KEYWORD\n*{kw}\n" + _row(1, 1) + "\n"
                                  + _row(1, 1) + "\n*END\n")
                self.assertEqual(state.skipped_keywords, [])


class IncludeTransformOffsetTests(unittest.TestCase):
    def _dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def _offset(self, inner: str, **offs) -> str:
        d = self._dir()
        with open(os.path.join(d, "inc.k"), "w") as fh:
            fh.write("*KEYWORD\n" + inner + "*END\n")
        cells = [offs.get(k, 0) for k in
                 ("idnoff", "ideoff", "idpoff", "idmoff", "idsoff", "idfoff",
                  "iddoff")]
        with open(os.path.join(d, "main.k"), "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\ninc.k\n"
                     + _row(*cells) + "\n"
                     + _row(offs.get("idroff", 0)) + "\n*END\n")
        for b in parse_k_file(os.path.join(d, "main.k")):
            if b.keyword in RARE_MATERIAL_KEYWORDS:
                return "\n".join(b.raw)
        return ""

    def test_flux_set_moves_ssid_pserod_and_the_curve(self):
        inner = ("*BOUNDARY_FLUX_SET\n" + _row(50, 60) + "\n"
                 + _row(900, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0)
                 + "\n")
        out = self._offset(inner, idsoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1050)       # SSID
        self.assertEqual(int(out[0][10:20]), 1060)      # PSEROD (a part SET)
        self.assertEqual(int(out[1][0:10]), 1400)       # LCID
        self.assertAlmostEqual(float(out[1][10:20]), -70000.0)

    def test_a_negative_flux_curve_moves_sign_preserved(self):
        inner = ("*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                 + _row(-900, -70000.0, 0, 0, 0, 0, 0) + "\n")
        out = self._offset(inner, idsoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[1][0:10]), -1400)

    def test_flux_segment_moves_its_nodes(self):
        inner = ("*BOUNDARY_FLUX_SEGMENT\n" + _row(5, 6, 7, 8) + "\n"
                 + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0) + "\n")
        out = self._offset(inner, idnoff=200).splitlines()
        self.assertEqual([int(out[0][i:i + 10]) for i in range(0, 40, 10)],
                         [205, 206, 207, 208])

    def test_the_history_variable_rows_do_not_shift_the_walk(self):
        inner = ("*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                 + _row(900, -1.0, -1.0, -1.0, -1.0, 0, 9) + "\n"
                 + _row(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0) + "\n"
                 + _row(9.0) + "\n"
                 + _row(51, 0) + "\n"
                 + _row(901, -2.0, -2.0, -2.0, -2.0, 0, 0) + "\n")
        out = self._offset(inner, idsoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1050)
        self.assertEqual(int(out[1][0:10]), 1400)
        # The two HISV rows must be untouched...
        self.assertAlmostEqual(float(out[2][0:10]), 1.0)
        self.assertAlmostEqual(float(out[3][0:10]), 9.0)
        # ...and the SECOND card set must still be found in its own slots.
        self.assertEqual(int(out[4][0:10]), 1051)
        self.assertEqual(int(out[5][0:10]), 1401)

    def test_convection_moves_both_curve_cells(self):
        inner = ("*BOUNDARY_CONVECTION_SET\n" + _row(50, 60) + "\n"
                 + _row(0, 100.0, 900, 1.0, 0) + "\n")
        out = self._offset(inner, idsoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1050)
        self.assertEqual(int(out[0][10:20]), 1060)
        self.assertEqual(int(out[1][20:30]), 1400)      # TLCID
        self.assertAlmostEqual(float(out[1][10:20]), 100.0)

    def test_radiation_set_moves_pserod_from_field_seven(self):
        inner = ("*BOUNDARY_RADIATION_SET\n"
                 + _row(50, 1, "", "", "", "", 60) + "\n"
                 + _row(0, 5.6704e-11, 900, 1.0, 0) + "\n")
        out = self._offset(inner, idsoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1050)
        self.assertEqual(int(out[0][10:20]), 1)         # TYPE is a flag
        self.assertEqual(int(out[0][60:70]), 1060)      # PSEROD
        self.assertEqual(int(out[1][20:30]), 1400)      # TLCID

    def test_mat_thermal_td_moves_tmid_and_tgrlc(self):
        inner = ("*MAT_THERMAL_ISOTROPIC_TD\n"
                 + _row(9, "7.85E-9", 77, 0.0, 0.0, 0.0) + "\n"
                 + _row(300.0, 900.0) + "\n"
                 + _row("4.60E+8", "4.60E+8") + "\n"
                 + _row(50.0, 32.0) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1009)
        self.assertEqual(int(out[0][20:30]), 577)
        # The data cards must be untouched.
        self.assertAlmostEqual(float(out[1][0:10]), 300.0)
        self.assertAlmostEqual(float(out[3][0:10]), 50.0)

    def test_mat_thermal_td_lc_moves_its_property_curves(self):
        inner = ("*MAT_THERMAL_ISOTROPIC_TD_LC\n"
                 + _row(9, "7.85E-9", -77, 0.0, 0.0, 0.0) + "\n"
                 + _row(801, 802, 0, 0, 0) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1009)
        self.assertEqual(int(out[0][20:30]), -577)      # sign preserved
        self.assertEqual(int(out[1][0:10]), 1301)       # HCLC
        self.assertEqual(int(out[1][10:20]), 1302)      # TCLC
        self.assertEqual(int(out[1][20:30]), 0)         # HCHSV is an INDEX

    def test_mat_thermal_orthotropic_moves_tmid_and_tgrlc(self):
        inner = ("*MAT_THERMAL_ORTHOTROPIC\n"
                 + _row(9, "7.85E-9", 77, 0.0, 2.0, 0.0, 0.0) + "\n"
                 + _row("4.60E+8", 41.0, 42.0, 43.0) + "\n")
        out = self._offset(inner, idmoff=1000, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 1009)
        self.assertEqual(int(out[0][20:30]), 577)
        self.assertAlmostEqual(float(out[0][40:50]), 2.0)   # AOPT is a flag
        self.assertAlmostEqual(float(out[1][10:20]), 41.0)

    def test_load_thermal_element_rows_all_move(self):
        inner = ("*LOAD_THERMAL_VARIABLE_ELEMENT_SOLID\n"
                 + _row(1, 0.5, 20.0, 900) + "\n"
                 + _row(2, 0.5, 20.0, 901) + "\n")
        out = self._offset(inner, ideoff=100, idfoff=500).splitlines()
        self.assertEqual(int(out[0][0:10]), 101)
        self.assertEqual(int(out[0][30:40]), 1400)
        self.assertEqual(int(out[1][0:10]), 102)
        self.assertEqual(int(out[1][30:40]), 1401)

    def test_no_offsets_leaves_the_cards_untouched(self):
        inner = ("*BOUNDARY_CONVECTION_SET\n" + _row(50, 60) + "\n"
                 + _row(0, 100.0, 900, 1.0, 0) + "\n")
        self.assertEqual(self._offset(inner).splitlines(),
                         inner.splitlines()[1:])


class CollisionProbeTests(unittest.TestCase):
    """A user set at the id the ALLOCATOR WOULD ACTUALLY TAKE (#131).

    The allocation order on a /CONVEC deck, printed before the probe was
    written: /SURF/SEG takes the first auto id, the /CONVEC card the second,
    the /TH/NODE group the third. The synthesized T_inf /FUNCT (when the deck
    states no curve) comes from ``next_curve_id`` instead, and THAT is the
    allocator whose guard this probes: a user *DEFINE_CURVE sitting at the
    auto-id base must not be overwritten.
    """

    def test_the_allocation_order_is_what_the_probe_assumes(self):
        _result, starter, _ = _convert(_deck(THERMAL_LOAD))
        self.assertEqual(_one_header(starter, "/SURF/SEG/"), "/SURF/SEG/90001")
        self.assertEqual(_one_header(starter, "/CONVEC/"), "/CONVEC/90002")
        self.assertEqual(_one_header(starter, "/TH/NODE/"), "/TH/NODE/90003")

    def test_a_user_curve_at_the_auto_base_is_not_overwritten(self):
        # The constant-T_inf form synthesizes a /FUNCT through next_curve_id,
        # which dodges state.curves — a user *DEFINE_CURVE 90001 must survive.
        card = ("*BOUNDARY_CONVECTION_SET\n" + _row(50, 0) + "\n"
                + _row(0, 100.0, 0, 400.0, 0) + "\n")
        user = ("*DEFINE_CURVE\n" + _row(90001) + "\n"
                + _row16(0.0, 1.0) + "\n" + _row16(1.0, 2.0) + "\n")
        _result, starter, _ = _convert(_deck(SEG1 + user + card))
        self.assertEqual(_funct_points(starter, 90001), [(0.0, 1.0), (1.0, 2.0)])
        body = _block(starter, _one_header(starter, "/CONVEC/"))
        fid = int(body[2][10:20])
        self.assertNotEqual(fid, 90001)
        self.assertEqual(_funct_points(starter, fid),
                         [(0.0, 400.0), (1000000.0, 400.0)])

    def test_a_user_node_set_at_the_auto_base_is_not_overwritten(self):
        # The element-temperature path mints a /GRNOD through next_grnod_id.
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*SET_NODE_LIST\n" + _row(90001) + "\n" + _row(1, 2) + "\n"
            "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID\n"
            + _row(1, 500.0) + "\n" + _row(2, 500.0) + "\n")
        _result, starter, _ = _convert(deck)
        heads = _headers(starter, "/GRNOD/NODE/")
        self.assertEqual(len(heads), len(set(heads)))


class ThermalBoundaryDuplicateScanTests(unittest.TestCase):
    """The starter does NOT refuse a duplicate id on any of these cards.

    MEASURED: two ``/CONVEC`` cards on one id are BOTH read and BOTH applied,
    at 0 ERROR and 0 WARNING — none of the four readers calls ``UDOUBLE``. The
    writer cannot produce one (every id comes from the monotonic
    ``next_id()``), so the scan is called directly on a hand-built line list,
    the shape the #128 ``_warn_duplicate_thermal_ids`` probe established.
    """

    def _scan(self, lines):
        from k2rad.state import ConversionState
        from k2rad.writer.assembly import _warn_duplicate_thermal_bc_ids
        st = ConversionState()
        _warn_duplicate_thermal_bc_ids(st, lines)
        return st.warnings

    def test_a_duplicate_is_named_per_card_family(self):
        for card in ("IMPFLUX", "CONVEC", "RADIATION", "IMPTEMP", "INITEMP"):
            with self.subTest(card=card):
                w = self._scan([f"/{card}/7", "x", f"/{card}/7", "y"])
                self.assertEqual(len(w), 1)
                self.assertIn(f"/{card}/7 is emitted 2 times", w[0])

    def test_the_four_namespaces_are_independent(self):
        # /CONVEC/7 + /RADIATION/7 + /IMPFLUX/7 + /IMPTEMP/7 in one deck was
        # measured at 0 ERROR / 0 WARNING, so this must NOT warn.
        self.assertEqual(self._scan(["/CONVEC/7", "/RADIATION/7",
                                     "/IMPFLUX/7", "/IMPTEMP/7"]), [])

    def test_a_real_deck_allocates_distinct_ids(self):
        result, _starter, _ = _convert(
            _deck(SEG1 + CURVE900 + CONVEC_CARD
                  + "*BOUNDARY_FLUX_SET\n" + _row(50, 0) + "\n"
                  + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0)
                  + "\n"))
        self.assertFalse(_warned(result, "is emitted 2 times"))


class ByteIdentityTests(unittest.TestCase):
    def test_a_deck_without_the_batch_keywords_is_untouched(self):
        plain = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", "").replace(
            _row(1, 1, 1, 0, 0, 0, 0, 9), _row(1, 1, 1)).replace("{EXTRA}", "")
        _r1, s1, e1 = _convert(plain)
        _r2, s2, e2 = _convert(plain)
        self.assertEqual(s1, s2)
        self.assertEqual(e1, e2)
        for card in ("/CONVEC", "/RADIATION", "/IMPFLUX", "/HEAT/MAT"):
            self.assertNotIn(card, s1)
        for card in ("/DT/THERM", "/THERM\n", "/ANIM/NODA/TEMP"):
            self.assertNotIn(card, e1)


# ── The verification round's fixes ───────────────────────────────────────────

class MatT10AliasTests(unittest.TestCase):
    """``*MAT_T10`` IS ``*MAT_THERMAL_ISOTROPIC_TD_LC`` (Vol II R17 p.2-9, and
    p.3-37 heads the card with both names). Reading it with the ``_TD`` layout
    put card 2's ``HCLC TCLC HCHSV TCHSV TGHSV`` into the T1..T8 row and lost
    the whole thermal material silently, while the *INCLUDE_TRANSFORM offset
    walker had always treated it as ``_TD_LC`` — two readers of one card
    disagreeing (the #132 class)."""

    CURVES = ("*DEFINE_CURVE\n" + _row(801) + "\n"
              + _row16(300.0, "4.60E+8") + "\n"
              + _row16(900.0, "4.60E+8") + "\n"
              "*DEFINE_CURVE\n" + _row(802) + "\n"
              + _row16(300.0, 50.0) + "\n"
              + _row16(900.0, 32.0) + "\n")

    def _deck_for(self, spelling):
        mat = ("*" + spelling + "\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(801, 802, 0, 0, 0) + "\n" + self.CURVES)
        base = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", mat)
        return base.replace("{EXTRA}", THERMAL_LOAD)

    def test_both_spellings_give_the_same_heat_mat(self):
        rows = []
        for spelling in ("MAT_THERMAL_ISOTROPIC_TD_LC", "MAT_T10"):
            _result, starter, _ = _convert(self._deck_for(spelling))
            rows.append(_data_rows(starter, "/HEAT/MAT/1"))
        self.assertEqual(rows[0], rows[1])
        # and the values are the real ones, not the _RHO_CP_PLACEHOLDER the
        # mis-parsed layout produced.
        self.assertAlmostEqual(float(rows[1][0][20:40]), 3.611)
        self.assertAlmostEqual(float(rows[1][0][40:60]), 59.0, places=6)
        self.assertAlmostEqual(float(rows[1][0][60:80]), -0.03, places=9)

    def test_the_message_names_the_decks_own_spelling(self):
        result, _starter, _ = _convert(self._deck_for("MAT_T10"))
        hit = [w for w in result.warnings if "is FITTED onto" in w]
        self.assertEqual(len(hit), 1)
        self.assertIn("*MAT_T10 (*MAT_THERMAL_ISOTROPIC_TD_LC)", hit[0])

    def test_the_offset_walker_reads_the_same_layout(self):
        # Card 2 of the _TD_LC layout is CURVE ids, so an *INCLUDE_TRANSFORM
        # IDFOFF must offset them. The dispatch pass and this pass have to
        # agree about which layout the card has (#132), so the assertion walks
        # a real *MAT_T10 block rather than comparing two registry entries
        # (which are the same function object and would pass either way).
        self.assertIn("MAT_T10", _OFFSET_SPECS)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "inc.k"), "w") as fh:
            fh.write("*KEYWORD\n*MAT_T10\n"
                     + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
                     + _row(801, 802, 0, 0, 0) + "\n*END\n")
        with open(os.path.join(tmp.name, "main.k"), "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\ninc.k\n"
                     + _row(0, 0, 0, 100, 0, 500, 0) + "\n"
                     + _row(0) + "\n*END\n")
        rows = None
        for b in parse_k_file(os.path.join(tmp.name, "main.k")):
            if b.keyword.endswith("MAT_T10"):
                rows = b.raw
        self.assertIsNotNone(rows)
        self.assertEqual(int(rows[0][0:10]), 109)       # TMID -> IDMOFF
        self.assertEqual(int(rows[1][0:10]), 1301)      # HCLC -> IDFOFF
        self.assertEqual(int(rows[1][10:20]), 1302)     # TCLC -> IDFOFF


class FworkDefaultTests(unittest.TestCase):
    """Vol I R17 p.12-573's Card 1 Default row prints ``1.`` under FWORK, so a
    BLANK cell is full conversion. Gating on "was the cell typed" gave the same
    card two different physics depending on whitespace."""

    def test_a_blank_fwork_is_one(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 0, 11) + "\n" + THERMAL_LOAD)
        _result, starter, _ = _convert(deck)
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[1][60:80]), 1.0)

    def test_the_blank_case_is_named_in_the_message(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 0, 11) + "\n" + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "the cell is BLANK on this card"))

    def test_the_consumption_scope_is_stated(self):
        deck = _deck("*CONTROL_THERMAL_SOLVER\n"
                     + _row(1, 1, 11, "", 0, 1.0, 0.6, 0.0) + "\n"
                     + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        hit = [w for w in result.warnings if "FWORK = 0.6" in w]
        self.assertEqual(len(hit), 1)
        for token in ("mmain.F90:2035-2037", "cmain3.F:360", "pforc3.F:321",
                      "sigeps02c.F:223", "TOTAL internal-energy increment"):
            self.assertIn(token, hit[0], token)

    def test_no_control_card_means_no_heat_mat_claim(self):
        deck = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", "").replace(
            _row(1, 1, 1, 0, 0, 0, 0, 9), _row(1, 1, 1)).replace(
            "{EXTRA}", "*CONTROL_THERMAL_SOLVER\n" + _row(1, 0, 11) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "this deck emits no /HEAT/MAT at all"))


class LoadThermalVersusSolnTests(unittest.TestCase):
    """Vol I R17 p.33-162: the *LOAD_THERMAL_* nodal temperatures *"are all
    applied in a structural only analysis. They are ignored in a thermal only
    or coupled thermal/structural analysis"*."""

    DRIVER = ("*LOAD_THERMAL_CONSTANT_NODE\n" + _row(1, 700.0) + "\n")

    def test_soln_2_drops_the_family_by_name(self):
        deck = _deck("*CONTROL_SOLUTION\n" + _row(2) + "\n"
                     + self.DRIVER + THERMAL_LOAD)
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPTEMP/"), [])
        self.assertTrue(_warned(result, "IGNORES the whole *LOAD_THERMAL_*"))
        self.assertTrue(_warned(result, "*LOAD_THERMAL_CONSTANT_NODE"))
        # the heat source is untouched
        self.assertEqual(len(_headers(starter, "/CONVEC/")), 1)

    def test_soln_1_drops_the_family_too(self):
        deck = _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n"
                     + self.DRIVER + THERMAL_LOAD)
        _result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPTEMP/"), [])

    def test_soln_0_keeps_it(self):
        deck = _deck("*CONTROL_SOLUTION\n" + _row(0) + "\n"
                     + self.DRIVER + THERMAL_LOAD)
        _result, starter, _ = _convert(deck)
        self.assertEqual(len(_headers(starter, "/IMPTEMP/")), 1)

    def test_boundary_temperature_survives_a_thermal_soln(self):
        # p.33-162 scopes its sentence to *LOAD_THERMAL_OPTION alone; a
        # prescribed boundary temperature IS a thermal boundary condition.
        deck = _deck("*CONTROL_SOLUTION\n" + _row(2) + "\n"
                     "*SET_NODE_LIST\n" + _row(60) + "\n" + _row(1, 2) + "\n"
                     "*BOUNDARY_TEMPERATURE_SET\n" + _row(60, 0, 700.0) + "\n"
                     + THERMAL_LOAD)
        _result, starter, _ = _convert(deck)
        self.assertEqual(len(_headers(starter, "/IMPTEMP/")), 1)

    def test_a_stated_soln_0_with_thermal_cards_is_named(self):
        deck = _deck("*CONTROL_SOLUTION\n" + _row(0) + "\n" + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "structural analysis ONLY"))

    def test_an_absent_control_solution_says_nothing(self):
        result, _starter, _ = _convert(_deck(THERMAL_LOAD))
        self.assertFalse(_warned(result, "structural analysis ONLY"))

    def test_the_element_spellings_are_dropped_without_announcing(self):
        # The element resolver PRINTS "-> /IMPTEMP over the elements' OWN
        # nodes" as it builds its records, so the SOLN screen has to run
        # BEFORE it — otherwise that sentence stands on a deck that emits no
        # /IMPTEMP at all (#130). Caught on the composition deck.
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*CONTROL_SOLUTION\n" + _row(2) + "\n"
            "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID\n"
            + _row(1, 500.0) + "\n" + _row(2, 500.0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPTEMP/"), [])
        self.assertFalse(_warned(result, "over the elements' OWN nodes"))
        self.assertTrue(_warned(result, "IGNORES the whole *LOAD_THERMAL_*"))
        self.assertTrue(_warned(result,
                                "*LOAD_THERMAL_CONSTANT_ELEMENT_SOLID"))


class BoundaryRefusalOrderTests(unittest.TestCase):
    """A record whose segments cannot be built must be refused BEFORE anything
    announces what it converts to, and before a /FUNCT is minted for it."""

    def test_an_undefined_segment_set_is_refused_without_announcing(self):
        card = ("*BOUNDARY_CONVECTION_SET\n" + _row(77, 0) + "\n"
                + _row(0, 100.0, 900, 1.0, 0) + "\n")
        result, starter, _ = _convert(_deck(CURVE900 + card))
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertTrue(_warned(result, "*SET_SEGMENT 77 is not defined"))
        self.assertFalse(_warned(result, "-> /CONVEC with H ="))

    def test_no_orphan_function_is_left_behind(self):
        card = ("*BOUNDARY_RADIATION_SET\n" + _row(77, 1, 0, 0, 0, 0, 0) + "\n"
                + _row(0, SIGMA_MG_MM_S, 0, 1000.0) + "\n")
        _result, starter, _ = _convert(_deck(card))
        self.assertNotIn("radiation_tinf", starter)

    def test_the_common_field_drops_still_fire_on_a_refused_record(self):
        # The #129 rule: a refusal must not skip the card's field inventory.
        # PSEROD is field 2 on the _SET spelling of FLUX and CONVECTION.
        card = ("*BOUNDARY_CONVECTION_SET\n" + _row(77, 88)
                + "\n" + _row(0, 100.0, 900, 1.0, 0) + "\n")
        result, _starter, _ = _convert(_deck(CURVE900 + card))
        self.assertTrue(_warned(result, "PSEROD=88"))


class PserodCitationTests(unittest.TestCase):
    """The erosion paragraph is a different page and remark on each card."""

    def test_each_kind_cites_its_own_page(self):
        cases = (
            ("*BOUNDARY_FLUX_SET\n" + _row(50, 88) + "\n"
             + _row(0, -70000.0, -70000.0, -70000.0, -70000.0, 0, 0) + "\n",
             "p.5-49 Remark 5"),
            ("*BOUNDARY_CONVECTION_SET\n" + _row(50, 88) + "\n"
             + _row(0, 100.0, 900, 1.0, 0) + "\n",
             "p.5-32 Remark 4"),
            ("*BOUNDARY_RADIATION_SET\n" + _row(50, 1, 0, 0, 0, 0, 88) + "\n"
             + _row(0, SIGMA_MG_MM_S, 0, 1000.0) + "\n",
             "p.5-124 Remark 4"),
        )
        for card, cite in cases:
            with self.subTest(cite=cite):
                result, _starter, _ = _convert(_deck(SEG1 + CURVE900 + card))
                self.assertTrue(_warned(result, "PSEROD=88"))
                self.assertTrue(_warned(result, cite))


class BareElementSpellingTests(unittest.TestCase):
    def test_the_bare_spelling_names_the_mandatory_suffix(self):
        deck = TWO_BRICKS.replace(
            "{EXTRA}",
            "*LOAD_THERMAL_CONSTANT_ELEMENT\n" + _row(1, 500.0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPTEMP/"), [])
        self.assertTrue(_warned(result, "the _OPTION suffix is MANDATORY"))
        # NOT the "no <family> elements at all" message, on a deck full of them.
        self.assertFalse(_warned(result, "elements at all"))


class UnparsedThermalMaterialTests(unittest.TestCase):
    def test_a_tmid_naming_an_unparsed_sibling_is_named(self):
        # The *MAT_ADD_THERMAL_EXPANSION is what puts material 1 on the
        # /HEAT/MAT list at all; the *PART TMID then names a *MAT_THERMAL_*
        # spelling k2rad does not parse, so "no *PART TMID names one" would be
        # a FALSE premise (the #130 class).
        deck = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n",
            "*MAT_THERMAL_ORTHOTROPIC_TD\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0, 0.0) + "\n").replace(
            "{EXTRA}",
            "*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 0, 1.2e-5) + "\n"
            + "*LOAD_THERMAL_CONSTANT_NODE\n" + _row(1, 350.0) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(
            result, "*PART TMID names thermal material 9, whose "
                    "*MAT_THERMAL_* spelling k2rad does not parse"))
        self.assertFalse(_warned(result, "no *PART TMID names one"))
        # The spelling is RECOGNIZED (it has a named drop of its own) rather
        # than left in the generic unsupported-keyword list.
        self.assertNotIn("MAT_THERMAL_ORTHOTROPIC_TD", result.skipped_keywords)
        self.assertIn("MAT_THERMAL_ORTHOTROPIC_TD",
                      dict(result.recognized_not_emitted))

    def test_the_boundary_screen_names_an_unparsed_tmid_too(self):
        # _resolve_heat_materials' `wanted` set only holds mids whose *PART
        # TMID RESOLVES, so its own "unparsed" arm cannot fire on a deck that
        # states nothing but a TMID and a heat-source boundary. Without a
        # screen of its own, the no-/HEAT/MAT message prescribed exactly what
        # this deck already has — the #125 class.
        deck = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n",
            "*MAT_THERMAL_ORTHOTROPIC_TD\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0, 0.0) + "\n").replace(
            "{EXTRA}",
            SEG1 + CURVE900 + "*BOUNDARY_CONVECTION_SET\n" + _row(50, 0)
            + "\n" + _row(0, 100.0, 900, 1.0, 0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertTrue(_warned(
            result, "*PART TMID [9] names a thermal material whose "
                    "*MAT_THERMAL_* spelling k2rad does not CONVERT"))
        self.assertFalse(_warned(
            result, "Add *MAT_THERMAL_ISOTROPIC + *PART TMID"))

    def test_a_deck_with_no_tmid_at_all_still_gets_the_generic_advice(self):
        # The control: without a *PART TMID the generic sentence is the RIGHT
        # one, so the new arm must not swallow it.
        deck = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", "").replace(
            _row(1, 1, 1, 0, 0, 0, 0, 9), _row(1, 1, 1)).replace(
            "{EXTRA}",
            SEG1 + CURVE900 + "*BOUNDARY_CONVECTION_SET\n" + _row(50, 0)
            + "\n" + _row(0, 100.0, 900, 1.0, 0) + "\n")
        result, starter, _ = _convert(deck)
        self.assertEqual(_headers(starter, "/CONVEC/"), [])
        self.assertTrue(_warned(
            result, "Add *MAT_THERMAL_ISOTROPIC + *PART TMID"))


class DuplicateTmidTests(unittest.TestCase):
    def test_one_tmid_under_two_types_is_named(self):
        deck = BRICK.replace(
            "{EXTRA}",
            "*MAT_THERMAL_ISOTROPIC_TD\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row(300.0, 900.0) + "\n"
            + _row("4.60E+8", "4.60E+8") + "\n"
            + _row(50.0, 32.0) + "\n" + THERMAL_LOAD)
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "TMID 9 is stated by 2 different"))

    def test_a_clean_deck_is_quiet(self):
        result, _starter, _ = _convert(_deck(THERMAL_LOAD))
        self.assertFalse(_warned(result, "is stated by 2 different"))


class ConstantDriverExpansionTests(unittest.TestCase):
    """A /THERM_STRESS/MAT beside a driver that never moves gets exactly zero
    thermal strain, because the companion /INITEMP starts the nodes at the
    driver's own constant."""

    EXPANSION = "*MAT_ADD_THERMAL_EXPANSION\n" + _row(1, 0, 1.2e-5) + "\n"

    def test_a_constant_driver_is_named(self):
        deck = _deck(self.EXPANSION
                     + "*LOAD_THERMAL_CONSTANT_NODE\n" + _row(1, 350.0) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertTrue(_warned(result, "drivers that NEVER MOVE"))
        self.assertTrue(_warned(result, "null state"))

    def test_a_curve_driver_is_not(self):
        deck = _deck(CURVE900 + self.EXPANSION
                     + "*LOAD_THERMAL_LOAD_CURVE\n" + _row(900) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertFalse(_warned(result, "drivers that NEVER MOVE"))

    def test_a_heat_source_beside_it_is_not(self):
        deck = _deck(self.EXPANSION + THERMAL_LOAD
                     + "*LOAD_THERMAL_CONSTANT_NODE\n" + _row(1, 350.0) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertFalse(_warned(result, "drivers that NEVER MOVE"))

    def test_a_stated_initial_temperature_elsewhere_is_not(self):
        # The nodes then DO jump on the first cycle, so the expansion works.
        deck = _deck(self.EXPANSION
                     + "*INITIAL_TEMPERATURE_SET\n" + _row(0, 300.0) + "\n"
                     + "*LOAD_THERMAL_CONSTANT_NODE\n" + _row(1, 350.0) + "\n")
        result, _starter, _ = _convert(deck)
        self.assertFalse(_warned(result, "drivers that NEVER MOVE"))


class ThermalTimeHistoryChannelTests(unittest.TestCase):
    """A node the USER asked for should carry its temperature on a deck that
    really runs a thermal solve — measured, the T01 column goes 300 -> 941.3 K
    on the converted brick, and the starter reports 0 ERROR / 0 WARNING (no
    WARNING 1087, which needs a missing /HEAT/MAT)."""

    HIST = "*DATABASE_HISTORY_NODE\n" + _row(1, 8) + "\n"

    def test_the_user_group_gains_temp_on_a_thermal_deck(self):
        _result, starter, _ = _convert(_deck(self.HIST + THERMAL_LOAD))
        body = _block(starter, "/TH/NODE/1")
        self.assertEqual(body[2].split(), ["DEF", "A", "AR", "VR", "TEMP"])

    def test_it_does_not_on_a_deck_with_no_thermal_solve(self):
        plain = BRICK.replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", "").replace(
            _row(1, 1, 1, 0, 0, 0, 0, 9), _row(1, 1, 1)).replace(
            "{EXTRA}", self.HIST)
        _result, starter, _ = _convert(plain)
        body = _block(starter, "/TH/NODE/1")
        self.assertEqual(body[2].split(), ["DEF", "A", "AR", "VR"])

    def test_an_implicit_deck_gets_no_temperature_channels(self):
        # MEASURED: an implicit run leaves every undriven node at exactly its
        # initial temperature and reports HEAT STORED = 0.0000000, while its
        # explicit twin conducts 300 -> 400 K.
        deck = _deck("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n"
                     + self.HIST + THERMAL_LOAD)
        _result, starter, engine = _convert(deck)
        self.assertNotIn("/ANIM/NODA/TEMP", engine)
        body = _block(starter, "/TH/NODE/1")
        self.assertEqual(body[2].split(), ["DEF", "A", "AR", "VR"])
        self.assertEqual(_headers(starter, "/TH/NODE/"), ["/TH/NODE/1"])


class ConductivityFitSegmentTests(unittest.TestCase):
    """AL/BL never enter the Lagrangian conduction — every conduction operator
    reads AS + BS*T_element (stherm.F:106, s4therm.F:84, s10therm.F:81,
    cbatherm.F:67, pforc3.F:382). The two-segment form lives only in the
    thermal TIME-STEP routines, gated on IDT_THERM == 1. So the table is fitted
    with ONE line and mirrored, even when the law states a melt temperature."""

    #: TM = 600 K sits INSIDE the tabulated range below, which is what makes
    #: the probe reach the branch under test: with a melt temperature above the
    #: whole table (the first draft used 1800) a two-segment fit degenerates to
    #: the one-segment one and the test passes either way — the #130 "a probe
    #: must REACH the branch" trap, caught by mutation M8.
    JC = ("*MAT_JOHNSON_COOK\n"
          + _row(1, "7.85E-9", 80000.0, 210000.0, 0.3) + "\n"
          + _row(0.35, 0.275, 0.36, 0.022, 1.0, 600.0, 293.0) + "\n"
          + _row(0.0, 0.0, 0.0, 0.0, 0.0, "4.60E+8", 1.0e-6, 0.0) + "\n"
          + _row(0.0, 0.0, 0.0, 0.0, 0.0) + "\n")

    def _jc_deck(self, mat, extra):
        return BRICK.replace(
            "*MAT_ELASTIC\n"
            + _row(1, "7.85E-9", 210000.0, 0.3) + "\n", self.JC).replace(
            "*MAT_THERMAL_ISOTROPIC\n"
            + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
            + _row("4.60E+8", 45.0) + "\n", mat).replace("{EXTRA}", extra)

    def test_a_melt_temperature_does_not_split_the_fit(self):
        # A NON-LINEAR table straddling T1 = 600, so the one-line fit and the
        # old two-segment one give different numbers in every cell:
        #   one line over all four points → 66.8 − 0.048·T
        #   split at 600 → 59 − 0.03·T below, 101 − 0.09·T above
        mat = ("*MAT_THERMAL_ISOTROPIC_TD\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row(300.0, 500.0, 700.0, 900.0) + "\n"
               + _row("4.60E+8", "4.60E+8", "4.60E+8", "4.60E+8") + "\n"
               + _row(50.0, 44.0, 38.0, 20.0) + "\n")
        result, starter, _ = _convert(self._jc_deck(mat, THERMAL_LOAD))
        body = _data_rows(starter, "/HEAT/MAT/1")
        self.assertAlmostEqual(float(body[1][0:20]), 600.0)             # T1
        self.assertAlmostEqual(float(body[0][40:60]), 66.8, places=6)   # AS
        self.assertAlmostEqual(float(body[0][60:80]), -0.048, places=9)  # BS
        self.assertAlmostEqual(float(body[1][20:40]), 66.8, places=6)   # AL
        self.assertAlmostEqual(float(body[1][40:60]), -0.048, places=9)  # BL
        self.assertTrue(_warned(result, "deliberately NOT used as a second "
                                        "fit segment"))
        self.assertTrue(_warned(result, "stherm.F:106"))

    def test_the_law2_message_reads_the_emitted_efrac(self):
        # It used to assert the literal 1e-20 that the same commit made
        # variable.
        mat = ("*MAT_THERMAL_ISOTROPIC\n"
               + _row(9, "7.85E-9", 0, 0.0, 0.0, 0.0) + "\n"
               + _row("4.60E+8", 45.0) + "\n")
        extra = ("*CONTROL_THERMAL_SOLVER\n"
                 + _row(1, 1, 11, "", 0, 1.0, 1.0, 0.0) + "\n" + THERMAL_LOAD)
        result, _starter, _ = _convert(self._jc_deck(mat, extra))
        hit = [w for w in result.warnings
               if "adiabatic plastic-work heating is switched OFF" in w]
        self.assertEqual(len(hit), 1)
        self.assertIn("EFRAC is 1 on this deck", hit[0])
        self.assertNotIn("written at 1e-20", hit[0])


class BlankTmultSymmetryTests(unittest.TestCase):
    """A blank TMULT beside a TLCID is resolved to 1.0 on BOTH cards, and
    both say so. p.5-31 (CONVECTION) and p.5-123 / p.5-118 (RADIATION) give
    TMULT the same 'curve multiplier' definition and the same printed default
    of 0., and the two starter readers carry the same
    ``IF (FCY == ZERO) FCY = FCY_DIM`` (hm_read_convec.F:132,
    hm_read_radiation.F:137) — so the substitution is the same and it must be
    named on both. It used to be silent on /RADIATION, where T_inf enters to
    the FOURTH power."""

    def test_both_kinds_name_the_substitution(self):
        cases = (
            ("CONVECTION", _row(0, 100.0, 900, "", 0), "/CONVEC/", "p.5-31"),
            ("RADIATION", _row(0, SIGMA_MG_MM_S, 900, "", 0), "/RADIATION/",
             "p.5-123"),
        )
        for kind, c2, header, page in cases:
            with self.subTest(kind=kind):
                card = ("*BOUNDARY_" + kind + "_SET\n" + _row(50, 0) + "\n"
                        + c2 + "\n")
                result, starter, _ = _convert(_deck(SEG1 + CURVE900 + card))
                self.assertEqual(len(_headers(starter, header)), 1)
                hits = [w for w in result.warnings
                        if "TMULT is blank/zero" in w]
                self.assertEqual(len(hits), 1)
                self.assertIn(page, hits[0])
                self.assertIn("resolved to FSCALE = 1.0", hits[0])

    def test_a_stated_tmult_is_not_reported_as_blank(self):
        card = ("*BOUNDARY_RADIATION_SET\n" + _row(50, 0) + "\n"
                + _row(0, SIGMA_MG_MM_S, 900, 2.0, 0) + "\n")
        result, _starter, _ = _convert(_deck(SEG1 + CURVE900 + card))
        self.assertFalse(_warned(result, "TMULT is blank/zero"))


class AmsScreenMirrorsTheEmitterTests(unittest.TestCase):
    """``--ams`` is a REQUEST; ``/DT/AMS`` is written only for a mass-scaled
    explicit deck. ``freform.F:1327`` refuses ``/DT/THERM`` on ``IDTMINS /= 0``,
    which comes from the /DT/AMS card — so screening on ``options.ams`` alone
    withheld a legal card and said "/DT/AMS is kept" on a deck that has
    none (#130)."""

    CTS = "*CONTROL_TIMESTEP\n" + _row(0.0, 0.9, 0, 0.0, -1e-6) + "\n"

    def _deck(self, with_timestep):
        return _deck("*CONTROL_SOLUTION\n" + _row(1) + "\n" + THERMAL_LOAD
                     + (self.CTS if with_timestep else ""))

    def test_ams_without_a_timestep_card_keeps_dt_therm(self):
        result, starter, engine = _convert(self._deck(False), ams=True)
        self.assertIn("/DT/THERM", engine.splitlines())
        self.assertNotIn("/DT/AMS", engine.splitlines())
        self.assertEqual(_headers(starter, "/AMS"), [])
        self.assertFalse(_warned(result, "refuses the pair OUTRIGHT"))

    def test_ams_with_a_mass_scaled_timestep_still_refuses_the_pair(self):
        result, starter, engine = _convert(self._deck(True), ams=True)
        self.assertNotIn("/DT/THERM", engine.splitlines())
        self.assertIn("/DT/AMS", engine.splitlines())
        self.assertEqual(len(_headers(starter, "/AMS")), 1)
        self.assertTrue(_warned(result, "refuses the pair OUTRIGHT"))


class ControlSolutionDefaultCellTests(unittest.TestCase):
    """Vol I R17 p.12-532's Card 1 Default row gives LCINT 100 and NCDCF 1.
    A cell holding its own documented default states nothing, so listing it
    asks the reader of a plain structural deck to look at a cell that carries
    no information."""

    def _warns(self, row):
        result, _starter, _ = _convert(
            _deck("*CONTROL_SOLUTION\n" + row + "\n"))
        return [w for w in result.warnings if "*CONTROL_SOLUTION:" in w]

    def test_the_documented_defaults_are_not_listed(self):
        self.assertEqual(self._warns(_row(0, "", "", 100, "", 1)), [])
        # ...and so is the LCINT = 0 form, since the same page says "A minimum
        # number of 100 is always used, that is, only larger input values are
        # possible".
        self.assertEqual(self._warns(_row(0, "", "", 0, "", 0)), [])

    def test_a_real_value_is_still_named(self):
        for row, needle in ((_row(0, "", "", 500), "LCINT=500"),
                            (_row(0, "", "", "", "", 5), "NCDCF=5"),
                            (_row(0, 96), "NLQ=96")):
            with self.subTest(needle=needle):
                hits = self._warns(row)
                self.assertEqual(len(hits), 1)
                self.assertIn(needle, hits[0])


class MatThermalAliasCoverageTests(unittest.TestCase):
    """Vol II R17 p.2-9's ``*MAT_T##`` alias table, generated from ONE source.

    Hand-listing the aliases had already drifted: this PR registered T01, T02,
    T03 and T10 but not their siblings, so ``*MAT_T07`` fell into the generic
    "Skipped (unsupported) keywords" list while its exact synonym
    ``*MAT_THERMAL_CWM``, registered two screens away, got a named drop."""

    #: p.2-9 verbatim. T11-T15 are five aliases of one card, there is no T16,
    #: and T17/T18 exist — the gaps are the MANUAL's.
    PAGE_2_9 = {
        "MAT_T01": "MAT_THERMAL_ISOTROPIC",
        "MAT_T02": "MAT_THERMAL_ORTHOTROPIC",
        "MAT_T03": "MAT_THERMAL_ISOTROPIC_TD",
        "MAT_T04": "MAT_THERMAL_ORTHOTROPIC_TD",
        "MAT_T05": "MAT_THERMAL_DISCRETE_BEAM",
        "MAT_T06": "MAT_THERMAL_CHEMICAL_REACTION",
        "MAT_T07": "MAT_THERMAL_CWM",
        "MAT_T08": "MAT_THERMAL_ORTHOTROPIC_TD_LC",
        "MAT_T09": "MAT_THERMAL_ISOTROPIC_PHASE_CHANGE",
        "MAT_T10": "MAT_THERMAL_ISOTROPIC_TD_LC",
        "MAT_T11": "MAT_THERMAL_USER_DEFINED",
        "MAT_T12": "MAT_THERMAL_USER_DEFINED",
        "MAT_T13": "MAT_THERMAL_USER_DEFINED",
        "MAT_T14": "MAT_THERMAL_USER_DEFINED",
        "MAT_T15": "MAT_THERMAL_USER_DEFINED",
        "MAT_T17": "MAT_THERMAL_CHEMICAL_REACTION_ORTHOTROPIC",
        "MAT_T18": "MAT_THERMAL_ISPG",
    }

    def test_every_alias_dispatches_to_its_canonical_handler(self):
        from k2rad.handlers import HANDLERS
        for alias, canon in sorted(self.PAGE_2_9.items()):
            with self.subTest(alias=alias):
                self.assertIn(alias, HANDLERS)
                self.assertIn(canon, HANDLERS)
                self.assertIs(HANDLERS[alias], HANDLERS[canon])

    def test_no_thermal_spelling_falls_into_the_generic_list(self):
        names = sorted(set(self.PAGE_2_9) | set(self.PAGE_2_9.values())
                       | {"BOUNDARY_TEMPERATURE_PERIODIC_SET",
                          "BOUNDARY_TEMPERATURE_RSW",
                          "BOUNDARY_TEMPERATURE_TRAJECTORY",
                          "BOUNDARY_THERMAL_BULKFLOW",
                          "BOUNDARY_THERMAL_BULKNODE",
                          "BOUNDARY_THERMAL_WELD",
                          "BOUNDARY_THERMAL_WELD_TRAJECTORY"})
        deck = "*KEYWORD\n" + "".join(
            "*" + kw + "\n" + _row(500 + i, 1.0) + "\n"
            for i, kw in enumerate(names)) + "*END\n"
        state = _dispatch(deck)
        self.assertEqual(state.skipped_keywords, [])

    def test_an_alias_names_the_spelling_the_deck_wrote(self):
        # A log answering *MAT_THERMAL_CWM to a deck writing *MAT_T07 would
        # name a card the deck does not contain.
        state = _dispatch("*KEYWORD\n*MAT_T07\n" + _row(7, 1.0) + "\n*END\n")
        rne = dict(state.recognized_not_emitted)
        self.assertIn("MAT_T07", rne)
        self.assertNotIn("MAT_THERMAL_CWM", rne)
        self.assertIn("numeric alias for *MAT_THERMAL_CWM", rne["MAT_T07"])


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
