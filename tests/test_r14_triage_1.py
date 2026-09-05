"""Tests for the R14 STARTER-ERROR TRIAGE batch, round 1 (classes 1 and 2):

  A1  *CONTROL_SOLUTION SOLN=1 + *PART with no structural material
                                    → a synthesized inert /MAT/ELAST stand-in
  A2  *MAT_ELASTIC_PLASTIC_THERMAL / *MAT_004
                                    → /MAT/LAW106 + /THERM_STRESS/MAT
  A3  *MAT_CWM / *MAT_270           → /MAT/LAW106 + /THERM_STRESS/MAT (curves)
  A4  *MAT_ELASTIC_PLASTIC_HYDRO / *MAT_010
                                    → /MAT/LAW3 (+ the same-id /EOS)
  A5  *MAT_SOIL_AND_FOAM_FAILURE / *MAT_014
                                    → /MAT/LAW21 + /FAIL/SPALLING
      *MAT_INV_HYPERBOLIC_SIN, *MAT_ACOUSTIC, *MAT_FRAZER_NASH_RUBBER_MODEL,
      *MAT_GAS_MIXTURE, *MAT_VACUUM  → refused BY NAME with the part/element
                                       count they cost
  A6  *MAT_HIGH_EXPLOSIVE_BURN K/G/SIGY, and the LAW51 `Bunreacted` derivation
  A7  /MAT/LAW51 submaterial restatement, the vacuum phase, the AMMG clone

Kept in its own module, the repo's one-module-per-batch convention.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.handlers import dispatch
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness (the four helpers of tests/test_rare_materials.py) ───────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _row16(*vals) -> str:
    """LS-DYNA *DEFINE_CURVE point row (2 x 16-char fields)."""
    return "".join(f"{v:>16}" for v in vals)


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    tmp.cleanup()
    return result, starter


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
    """The non-comment, non-ruler data rows of a starter block."""
    body = _block(starter, header)
    if body is None:
        return None
    return [ln for ln in body if not ln.startswith("#")]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _fields(row: str, w: int = 20):
    """Slice a fixed-width Radioss card row into stripped w-char cells."""
    return [row[i:i + w].strip() for i in range(0, len(row.rstrip()), w)]


def _mat_id(starter: str, kind: str) -> int:
    """The id of the (single) /MAT/<kind> block in a starter deck."""
    for ln in starter.splitlines():
        if ln.startswith(f"/MAT/{kind}/"):
            return int(ln.rsplit("/", 1)[1])
    raise AssertionError(f"no /MAT/{kind} in the deck")


# Eight nodes of a unit brick + one *ELEMENT_SOLID, the smallest carrier that
# reaches the solid element registry (a stand-in is only made for a part that
# holds a CONTINUUM element).
_BRICK = """*NODE
         1             0.0             0.0             0.0
         2             1.0             0.0             0.0
         3             1.0             1.0             0.0
         4             0.0             1.0             0.0
         5             0.0             0.0             1.0
         6             1.0             0.0             1.0
         7             1.0             1.0             1.0
         8             0.0             1.0             1.0
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
"""

# The same eight nodes as two quad shells on part 1 (the shell arm of the
# stand-in screen).
_SHELLS = """*NODE
         1             0.0             0.0             0.0
         2             1.0             0.0             0.0
         3             1.0             1.0             0.0
         4             0.0             1.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
"""


def _thermal_only_deck(*, mid: int = 0, secid: int = 1, extra: str = "",
                       mesh: str = _BRICK, soln: int = 1,
                       tro: str = "7.85E-09") -> str:
    """A minimal *CONTROL_SOLUTION SOLN=1 deck of the ten corpus decks' shape:
    one part, MID as given, TMID naming a *MAT_THERMAL_ISOTROPIC."""
    section = ("*SECTION_SOLID\n" + _row(secid, 1) + "\n"
               if mesh is _BRICK else
               "*SECTION_SHELL\n" + _row(secid, 2) + "\n" + _row(1.0) + "\n")
    return (
        "*KEYWORD\n"
        "*CONTROL_SOLUTION\n" + _row(soln) + "\n"
        "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
        + mesh
        + "*PART\np1\n" + _row(1, secid, mid, 0, 0, 0, 0, 1) + "\n"
        + section
        + "*MAT_THERMAL_ISOTROPIC\n"
        + _row(1, tro, 0, 0.0, 0.0, 0.0) + "\n"
        + _row(460000000, 55.6) + "\n"
        + "*INITIAL_TEMPERATURE_SET\n" + _row(0, 20.0) + "\n"
        + "*BOUNDARY_TEMPERATURE_NODE\n" + _row(1, 100.0) + "\n"
        + extra
        + "*END\n")


class ThermalOnlyStandinTests(unittest.TestCase):
    """A1 — the SOLN=1 stand-in /MAT/ELAST."""

    def test_soln1_part_with_mid_zero_gets_a_standin(self):
        """MID = 0 on a SOLN=1 deck: a /MAT/ELAST is synthesized, the /PART is
        repointed at it and the /HEAT/MAT is keyed on the SAME id."""
        res, starter = _convert(_thermal_only_deck())
        mid = _mat_id(starter, "ELAST")
        self.assertGreaterEqual(mid, 90001)         # a next_mat_id() auto id
        self.assertIn(f"/HEAT/MAT/{mid}", starter)
        part = _data_rows(starter, "/PART/1")
        self.assertIsNotNone(part)
        # row 0 is the title; row 1 is `prop_ID mat_ID subset_ID`, three
        # 10-char cells.
        self.assertEqual(int(part[1][10:20]), mid)
        # ...and no /PART points at a material the deck does not write.
        self.assertNotIn("reference a material id that NO /MAT card",
                         " ".join(res.warnings))

    def test_standin_values_are_the_stated_tro_and_the_named_constants(self):
        """rho = the *MAT_THERMAL_* TRO verbatim; E = 1; nu = 0.3."""
        _res, starter = _convert(_thermal_only_deck(tro="2.5E-09"))
        body = _data_rows(starter, f"/MAT/ELAST/{_mat_id(starter, 'ELAST')}")
        # body[0] is the title line, body[1] RHO_I, body[2] E + nu.
        self.assertEqual(float(_fields(body[1])[0]), 2.5e-09)
        self.assertEqual([float(c) for c in _fields(body[2])], [1.0, 0.3])

    def test_standin_warning_names_the_substitution_and_its_evidence(self):
        _res, _starter = _convert(_thermal_only_deck())
        w = [x for x in _res.warnings if "SOLN=1 (thermal analysis only)" in x]
        self.assertEqual(len(w), 1)
        text = w[0]
        for fact in ("/PART 1 (mat_ID 0) -> /MAT/ELAST/", "rho=7.85e-09",
                     "E = 1", "nu = 0.3", "THE MODULUS IS INERT",
                     "resol.F:5807-5809", "resol.F:1738",
                     "960 of 960 byte-identical", "Do NOT substitute /MAT/VOID",
                     "hm_read_therm.F:244"):
            self.assertIn(fact, text)

    def test_no_standin_on_a_structural_deck(self):
        """SOLN=0: the modulus would NOT be inert, so the path must not fire —
        the deck keeps its dangling material and its existing diagnostic."""
        _res, starter = _convert(_thermal_only_deck(soln=0))
        self.assertEqual(_headers(starter, "/MAT/ELAST/"), [])
        self.assertEqual(_headers(starter, "/HEAT/MAT/"), [])

    def test_no_standin_when_the_mid_resolves_to_an_emitted_mat(self):
        """The screen is the EMITTED registry: a part naming a real material
        must not be shadowed by a stand-in (#130)."""
        deck = _thermal_only_deck(
            mid=7,
            extra="*MAT_ELASTIC\n" + _row(7, 7.85e-9, 210000.0, 0.3) + "\n")
        _res, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/MAT/ELAST/"), ["/MAT/ELAST/7"])
        self.assertIn("/HEAT/MAT/7", starter)

    def test_standin_for_a_nonzero_but_nonexistent_mid(self):
        """`MID = 0`, a MID absent from the source and a MID the converter
        dropped all take the same branch."""
        _res, starter = _convert(_thermal_only_deck(mid=42))
        mid = _mat_id(starter, "ELAST")
        self.assertNotEqual(mid, 42)
        part = _data_rows(starter, "/PART/1")
        self.assertEqual(int(part[1][10:20]), mid)

    def test_no_standin_for_an_element_free_part(self):
        """The CONNECTOR shape of mat_ID 0 needs no material — and the
        ERROR-1663 message must say WHY it got none, not announce a loss the
        stand-in already prevents."""
        deck = _thermal_only_deck(mesh=_BRICK).replace(
            "*ELEMENT_SOLID\n"
            "       1       1       1       2       3       4"
            "       5       6       7       8\n", "")
        res, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/MAT/ELAST/"), [])
        w = [x for x in res.warnings if "ERROR 1663" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("carry no solid/shell/tshell element", w[0])
        self.assertIn("[1]", w[0])          # the part is named

    def test_shell_standin_names_the_law1_integration_limit(self):
        _res, _starter = _convert(_thermal_only_deck(mesh=_SHELLS))
        w = [x for x in _res.warnings if "stand-in on shell/tshell part" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("thermexpc.F:172-174", w[0])
        self.assertIn("[1]", w[0])

    def test_zero_tro_refuses_the_standin_by_name(self):
        """ERROR 683 exempts only laws 0/20/51/151/108/999, so a stand-in with
        no density would trade one fatal for another."""
        res, starter = _convert(_thermal_only_deck(tro="0.0"))
        self.assertEqual(_headers(starter, "/MAT/ELAST/"), [])
        w = [x for x in res.warnings if "ERROR 683" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("hm_read_mat.F90:1575-1583", w[0])

    def test_standin_is_recorded_for_later_diagnostics(self):
        """part.mid is REWRITTEN in place, so ``state.thermal_standin_mats`` is
        the only record of the substitution's two halves."""
        state = ConversionState()
        state.ctrl_solution_soln = 1
        from k2rad.writer.thermal import _resolve_thermal_standins
        _resolve_thermal_standins(state)          # no parts: a clean no-op
        self.assertEqual(state.thermal_standin_mats, {})



# The eight-slot *MAT_004 rows of thermal/welding-new/welding-solids/
# 05_1_welding_solid.k ("steel"), the richest carrier in the corpus.
_MAT004_STEEL = (
    "*MAT_ELASTIC_PLASTIC_THERMAL\n"
    + _row(1, "7.85000E-9") + "\n"
    + _row(273.0, 493.0, 1273.0, 10000.0, 0.0, 0.0, 0.0, 0.0) + "\n"
    + _row(210000.0, 210000.0, 75000.0, 1000.0, 0.0, 0.0, 0.0, 0.0) + "\n"
    + _row(0.285, 0.285, 0.3, 0.45, 0.0, 0.0, 0.0, 0.0) + "\n"
    + _row("1.20000E-5", "1.20000E-5", "1.40000E-5", 0.0, 0.0, 0.0, 0.0, 0.0)
    + "\n"
    + _row(435.0, 100.0, 20.0, 1.0, 0.0, 0.0, 0.0, 0.0) + "\n"
    + _row(1000.0, 1000.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0) + "\n")


def _mat004_deck(card: str = _MAT004_STEEL, mid: int = 1,
                 extra: str = "") -> str:
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + _BRICK
            + "*PART\np1\n" + _row(1, 1, mid) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + card + extra + "*END\n")


class Mat004Law106Tests(unittest.TestCase):
    """A2 — *MAT_ELASTIC_PLASTIC_THERMAL / *MAT_004 → /MAT/LAW106."""

    def test_registered_under_all_three_spellings(self):
        for kw in ("*MAT_ELASTIC_PLASTIC_THERMAL", "*MAT_004", "*MAT_4"):
            with self.subTest(kw=kw):
                deck = _mat004_deck(
                    _MAT004_STEEL.replace("*MAT_ELASTIC_PLASTIC_THERMAL", kw))
                res, starter = _convert(deck)
                self.assertIn("/MAT/LAW106/1", starter)
                self.assertNotIn(kw.lstrip("*"), res.skipped_keywords)

    def test_live_point_count_is_the_increasing_prefix(self):
        """An unused slot is 0.0, which is also a legal temperature — three
        corpus decks put it in T1."""
        from k2rad.handlers import _mat004_live_points
        cases = [
            ([273.0, 493.0, 1273.0, 10000.0, 0, 0, 0, 0], 4),   # 05_1
            ([-1000.0, 0.0, 1000.0, 0, 0, 0, 0, 0], 3),         # tempcyl
            ([0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 0, 0], 6),     # thermal-stress
            ([0.0, 400.0, 0, 0, 0, 0, 0, 0], 2),                # steel_frame
            ([0.0, 0, 0, 0, 0, 0, 0, 0], 1),                    # degenerate
        ]
        for t, want in cases:
            with self.subTest(t=t[:4]):
                self.assertEqual(_mat004_live_points(t), want)

    def test_card_layout_is_the_2019_block(self):
        """C2 E/nu/fct1/fct2/fct3, C3 A/B/n, C4+C5 blank, C6 RHO_Cp/../Tr."""
        _res, starter = _convert(_mat004_deck())
        body = _block(starter, "/MAT/LAW106/1")
        rows = [ln for ln in body if not ln.startswith("#")]
        # rows: title, RHO_I, E-line, A-line, C4(blank), C5(blank), C6
        self.assertEqual(len(rows), 7)
        self.assertEqual(float(_fields(rows[1])[0]), 7.85e-9)
        e_line = rows[2]
        self.assertEqual(float(e_line[0:20]), 210000.0)
        self.assertEqual(float(e_line[20:40]), 0.285)
        f1 = int(e_line[40:50])
        f2 = int(e_line[50:60])
        f3 = int(e_line[60:70])
        # fct_ID1 (heating) and fct_ID2 (cooling) must be the SAME function:
        # sigeps106.F90:231-240 uses table(2) while the element cools, so a 0
        # there would use the unscaled E on every cooling step.
        self.assertEqual(f1, f2)
        self.assertNotEqual(f3, f1)
        self.assertEqual(rows[4].strip(), "")     # Pmin/Nmax/Tol
        self.assertEqual(rows[5].strip(), "")     # m/Tmelt/Tmax
        self.assertEqual(float(_fields(rows[6])[3]), 273.0)   # Tr

    def test_scalars_are_the_table_values_at_the_reference_temperature(self):
        """Hand-computed from the 05_1 steel card at Tr = T1 = 273:
        E = 210000, nu = 0.285, A = SIGY(273) = 435,
        B = E*ETAN/(E-ETAN) = 210000*1000/209000 = 1004.784688995215."""
        _res, starter = _convert(_mat004_deck())
        rows = [ln for ln in _block(starter, "/MAT/LAW106/1")
                if not ln.startswith("#")]
        self.assertEqual(float(rows[2][0:20]), 210000.0)
        self.assertEqual(float(rows[2][20:40]), 0.285)
        a, b, n = (float(c) for c in _fields(rows[3])[:3])
        self.assertEqual(a, 435.0)
        self.assertAlmostEqual(b, 210000.0 * 1000.0 / 209000.0, places=4)
        self.assertEqual(n, 1.0)

    def test_e_function_is_normalised_by_the_scalar(self):
        """hm_read_mat106.F90:262 sets fscale(1:2) = e, so the function is a
        MULTIPLIER: E(10000)/E(273) = 1000/210000."""
        _res, starter = _convert(_mat004_deck())
        rows = [ln for ln in _block(starter, "/MAT/LAW106/1")
                if not ln.startswith("#")]
        fid = int(rows[2][40:50])
        pts = [[float(c) for c in _fields(ln)]
               for ln in _data_rows(starter, f"/FUNCT/{fid}")[1:]]
        self.assertEqual([p[0] for p in pts], [273.0, 493.0, 1273.0, 10000.0])
        self.assertAlmostEqual(pts[0][1], 1.0)
        self.assertAlmostEqual(pts[3][1], 1000.0 / 210000.0, places=10)

    def test_alpha_reaches_therm_stress_one_to_one(self):
        """Two term-for-term identical incremental forms need no factor."""
        _res, starter = _convert(_mat004_deck())
        rows = _data_rows(starter, "/THERM_STRESS/MAT/1")
        self.assertIsNotNone(rows)
        fid = int(rows[0][0:10])
        self.assertEqual(float(rows[0][10:30]), 1.0)          # Fscale_y
        pts = [[float(c) for c in _fields(ln)]
               for ln in _data_rows(starter, f"/FUNCT/{fid}")[1:]]
        self.assertEqual([p[1] for p in pts],
                         [1.2e-5, 1.2e-5, 1.4e-5, 0.0])
        # ...and the mandatory /HEAT/MAT partner (ERROR 1129 without it).
        self.assertIn("/HEAT/MAT/1", starter)

    def test_thermo_elastic_card_gets_an_unreachable_yield(self):
        """SIGY = 0 is Remark 2's 'do not define', not 'yields at zero'."""
        card = (
            "*MAT_ELASTIC_PLASTIC_THERMAL\n"
            + _row(1, "1E-9") + "\n"
            + _row(0.0, 1000.0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(210000.0, 210000.0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(0.3, 0.3, 0, 0, 0, 0, 0, 0) + "\n"
            + _row("2.30000E-4", "2.30000E-4", 0, 0, 0, 0, 0, 0) + "\n"
            + _row(0.0, 0.0, 0, 0, 0, 0, 0, 0) + "\n"
            + _row(0.0, 0.0, 0, 0, 0, 0, 0, 0) + "\n")
        res, starter = _convert(_mat004_deck(card))
        rows = [ln for ln in _block(starter, "/MAT/LAW106/1")
                if not ln.startswith("#")]
        self.assertEqual(float(_fields(rows[3])[0]), 1.0e20)
        self.assertIn("THERMO-ELASTIC", " ".join(res.warnings))

    def test_one_point_table_is_refused_by_name(self):
        card = _MAT004_STEEL.replace(
            _row(273.0, 493.0, 1273.0, 10000.0, 0.0, 0.0, 0.0, 0.0),
            _row(273.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        res, starter = _convert(_mat004_deck(card))
        self.assertEqual(_headers(starter, "/MAT/LAW106/"), [])
        self.assertIn("only 1 temperature point(s)", " ".join(res.warnings))

    def test_zero_density_is_refused_by_name(self):
        card = _MAT004_STEEL.replace(_row(1, "7.85000E-9"), _row(1, 0.0))
        res, starter = _convert(_mat004_deck(card))
        self.assertEqual(_headers(starter, "/MAT/LAW106/"), [])
        w = " ".join(res.warnings)
        self.assertIn("ERROR 683", w)
        self.assertIn("hm_read_mat.F90:1575-1583", w)

    def test_warning_names_the_frozen_yield_with_the_deck_s_own_spread(self):
        res, _starter = _convert(_mat004_deck())
        w = [x for x in res.warnings if "-> /MAT/LAW106" in x]
        self.assertEqual(len(w), 1)
        for fact in ("SIGY 435 … 1 over T = 273 … 10000 (factor 435)",
                     "sigeps106.F90:306-310", "NOTHING IS FITTED",
                     "Tmelt is left BLANK", "EXTRAPOLATES",
                     "lost BY VERSION, not by mapping"):
            self.assertIn(fact, w[0])

    def test_reference_temperature_follows_the_deck_s_own_t0(self):
        deck = _mat004_deck(
            extra="*INITIAL_TEMPERATURE_SET\n" + _row(0, 493.0) + "\n")
        res, starter = _convert(deck)
        rows = [ln for ln in _block(starter, "/MAT/LAW106/1")
                if not ln.startswith("#")]
        self.assertEqual(float(_fields(rows[6])[3]), 493.0)
        # E(493) = 210000 too, but SIGY(493) = 100 — the value that moves.
        self.assertEqual(float(_fields(rows[3])[0]), 100.0)
        self.assertIn("model-wide temperature at t = 0 (493)",
                      " ".join(res.warnings))

    def test_out_of_range_t0_falls_back_to_the_first_point(self):
        deck = _mat004_deck(
            extra="*INITIAL_TEMPERATURE_SET\n" + _row(0, 20000.0) + "\n")
        res, starter = _convert(deck)
        rows = [ln for ln in _block(starter, "/MAT/LAW106/1")
                if not ln.startswith("#")]
        self.assertEqual(float(_fields(rows[6])[3]), 273.0)
        self.assertIn("lies OUTSIDE the stated range", " ".join(res.warnings))

    def test_offset_spec_moves_the_mid_and_nothing_else(self):
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("MAT_ELASTIC_PLASTIC_THERMAL", "MAT_004", "MAT_4"):
            self.assertEqual(_OFFSET_SPECS[kw], {"cards": {0: [(0, "m")]}})


# The *MAT_CWM card and its five curves, verbatim from 05_1_welding_solid.k.
_CWM_CURVES = (
    "*DEFINE_CURVE\n" + _row(101, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
    + _row16(273.0, 210000.0) + "\n" + _row16(493.0, 210000.0) + "\n"
    + _row16(10000.0, 1000.0) + "\n"
    "*DEFINE_CURVE\n" + _row(102, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
    + _row16(273.0, 0.3) + "\n" + _row16(473.0, 0.3) + "\n"
    + _row16(10000.0, 0.49) + "\n"
    "*DEFINE_CURVE\n" + _row(103, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
    + _row16(273.0, 240.0) + "\n" + _row16(473.0, 240.0) + "\n"
    + _row16(10000.0, 5.0) + "\n"
    "*DEFINE_CURVE\n" + _row(104, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
    + _row16(273.0, 700.0) + "\n" + _row16(473.0, 700.0) + "\n"
    + _row16(10000.0, 5.0) + "\n"
    "*DEFINE_CURVE\n" + _row(105, 0, 1.0, "1.00000E-6", 0.0, 0.0) + "\n"
    + _row16(273.0, 17.0) + "\n" + _row16(473.0, 17.0) + "\n"
    + _row16(1000.0, 22.0) + "\n" + _row16(10000.0, 0.0) + "\n")

_MAT_CWM = (
    "*MAT_CWM\n"
    + _row(2, "7.85000E-9", 101, 102, 103, 104, 105, 1.0) + "\n"
    + _row(1300.0, 1400.0, 1200.0, 1400.0, 10000.0, 0.49, 0.0, 0.0) + "\n"
    + _row(800.0, 500.0, 0.0, 0, 0.0, 0) + "\n")


def _cwm_deck(card: str = _MAT_CWM, extra: str = "") -> str:
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + _BRICK
            + "*PART\np1\n" + _row(1, 1, 2) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + card + _CWM_CURVES + extra + "*END\n")


class MatCwmLaw106Tests(unittest.TestCase):
    """A3 — *MAT_CWM / *MAT_270 → /MAT/LAW106, curves instead of tables."""

    def test_registered_under_both_spellings(self):
        for kw in ("*MAT_CWM", "*MAT_270"):
            with self.subTest(kw=kw):
                res, starter = _convert(
                    _cwm_deck(_MAT_CWM.replace("*MAT_CWM", kw)))
                self.assertIn("/MAT/LAW106/2", starter)
                self.assertNotIn(kw.lstrip("*"), res.skipped_keywords)

    def test_lchr_is_written_unconverted(self):
        """LCHR is ALREADY the plastic hardening modulus (Remark 2), so
        B = H(Tr) = 700 — NOT E*Et/(E-Et) = 210000*700/209300 = 702.3."""
        _res, starter = _convert(_cwm_deck())
        rows = [ln for ln in _block(starter, "/MAT/LAW106/2")
                if not ln.startswith("#")]
        a, b, n = (float(c) for c in _fields(rows[3])[:3])
        self.assertEqual(a, 240.0)              # LCSY at 273
        self.assertEqual(b, 700.0)              # LCHR at 273, UNCONVERTED
        self.assertNotAlmostEqual(b, 210000.0 * 700.0 / 209300.0, places=2)
        self.assertEqual(n, 1.0)

    def test_lcat_scale_factor_is_applied_exactly_once(self):
        """The corpus card's SFO is 1e-6 with ordinates 17..22, so alpha is
        1.7e-5. Curve.pts is ALREADY scaled — re-applying SFO here squared it
        to 1.7e-11 (measured on 05_1_welding_solid.k before the fix)."""
        _res, starter = _convert(_cwm_deck())
        rows = _data_rows(starter, "/THERM_STRESS/MAT/2")
        fid = int(rows[0][0:10])
        pts = [[float(c) for c in _fields(ln)]
               for ln in _data_rows(starter, f"/FUNCT/{fid}")[1:]]
        self.assertEqual([p[1] for p in pts],
                         [1.7e-5, 1.7e-5, 2.2e-5, 0.0])

    def test_e_and_nu_curves_become_normalised_functions(self):
        _res, starter = _convert(_cwm_deck())
        rows = [ln for ln in _block(starter, "/MAT/LAW106/2")
                if not ln.startswith("#")]
        self.assertEqual(float(rows[2][0:20]), 210000.0)
        self.assertEqual(float(rows[2][20:40]), 0.3)
        f_e = int(rows[2][40:50])
        self.assertEqual(int(rows[2][50:60]), f_e)
        f_nu = int(rows[2][60:70])
        e_pts = [[float(c) for c in _fields(ln)]
                 for ln in _data_rows(starter, f"/FUNCT/{f_e}")[1:]]
        self.assertAlmostEqual(e_pts[-1][1], 1000.0 / 210000.0, places=10)
        nu_pts = [[float(c) for c in _fields(ln)]
                  for ln in _data_rows(starter, f"/FUNCT/{f_nu}")[1:]]
        # 8 places, not 10: the card format is 10 significant digits, so the
        # written 1.633333333 is the emitted value, not a rounding of it.
        self.assertAlmostEqual(nu_pts[-1][1], 0.49 / 0.3, places=8)

    def test_annealing_and_ghost_losses_are_named(self):
        res, _starter = _convert(_cwm_deck())
        w = [x for x in res.warnings if "NOT carried" in x]
        self.assertEqual(len(w), 1)
        for fact in ("ANNEALING (TASTART=1300, TAEND=1400)",
                     "p.2-1838 Remark 3",
                     "GHOST -> LIVE weld-metal deposition",
                     "read_sensor_temp.F:81-87",
                     "residual stress that is NOT VALIDATED"):
            self.assertIn(fact, w[0])

    def test_card3_is_named_as_post_processing_only(self):
        res, _starter = _convert(_cwm_deck())
        w = [x for x in res.warnings if "POST-PROCESSING ONLY" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("HISTORY VARIABLE 11", w[0])
        self.assertIn("T2PHASE=800", w[0])

    def test_partial_beta_names_the_kinematic_loss(self):
        card = _MAT_CWM.replace(
            _row(2, "7.85000E-9", 101, 102, 103, 104, 105, 1.0),
            _row(2, "7.85000E-9", 101, 102, 103, 104, 105, 0.5))
        res, _starter = _convert(_cwm_deck(card))
        self.assertIn("splits the hardening between isotropic and KINEMATIC",
                      " ".join(res.warnings))

    def test_missing_lcem_refuses_the_material_by_name(self):
        card = _MAT_CWM.replace(
            _row(2, "7.85000E-9", 101, 102, 103, 104, 105, 1.0),
            _row(2, "7.85000E-9", 999, 102, 103, 104, 105, 1.0))
        res, starter = _convert(_cwm_deck(card))
        self.assertEqual(_headers(starter, "/MAT/LAW106/"), [])
        self.assertIn("LCEM = 999 names no *DEFINE_CURVE",
                      " ".join(res.warnings))

    def test_offset_spec_moves_the_mid_and_the_five_curve_ids(self):
        from k2rad.assembly import _OFFSET_SPECS
        want = {"cards": {0: [(0, "m"), (2, "f"), (3, "f"), (4, "f"),
                              (5, "f"), (6, "f")]}}
        for kw in ("MAT_CWM", "MAT_270"):
            self.assertEqual(_OFFSET_SPECS[kw], want)

    def test_registry_and_offset_key_sets_agree(self):
        """A spelling with no offset verdict is a KeyError at import, never a
        silent gap (#116) — this pins the four new rows into that contract."""
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import HANDLERS, RARE_MATERIAL_KEYWORDS
        for kw in ("MAT_ELASTIC_PLASTIC_THERMAL", "MAT_004", "MAT_4",
                   "MAT_CWM", "MAT_270"):
            self.assertIn(kw, RARE_MATERIAL_KEYWORDS)
            self.assertIn(kw, HANDLERS)
            self.assertIn(kw, _OFFSET_SPECS)


# sph/bar-iv/taylor1.k's copper: G = 37593, SIG0 = 180, EH = PC = FS = 0,
# with an *EOS_GRUNEISEN of the same id (C = 3.958e6, S1 = 1.497, gamma0 = 2).
_MAT010 = ("*MAT_ELASTIC_PLASTIC_HYDRO\n"
           + _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0) + "\n"
           + _row(*([0.0] * 8)) + "\n" + _row(*([0.0] * 8)) + "\n"
           + _row(*([0.0] * 8)) + "\n" + _row(*([0.0] * 8)) + "\n")
_EOS_GRUN = ("*EOS_GRUNEISEN\n"
             + _row(2, 3958000.0, 1.497, 0.0, 0.0, 2.0, 0.0, 0.0) + "\n")


def _mat010_deck(card: str = _MAT010, eos: str = _EOS_GRUN) -> str:
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + _BRICK
            + "*PART\np1\n" + _row(1, 1, 2) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + card + eos + "*END\n")


class Mat010Law3Tests(unittest.TestCase):
    """A4 — *MAT_ELASTIC_PLASTIC_HYDRO / *MAT_010 → /MAT/LAW3 + same-id /EOS."""

    def test_registered_under_every_spelling(self):
        for kw in ("*MAT_ELASTIC_PLASTIC_HYDRO", "*MAT_010", "*MAT_10"):
            with self.subTest(kw=kw):
                res, starter = _convert(_mat010_deck(
                    _MAT010.replace("*MAT_ELASTIC_PLASTIC_HYDRO", kw)))
                self.assertIn("/MAT/LAW3/2", starter)
                self.assertNotIn(kw.lstrip("*"), res.skipped_keywords)

    def test_e_nu_derived_from_ro_and_the_eos_sound_speed(self):
        """K0 = rho0*C^2 = 8.9e-9*3.958e6^2 = 139425.2996;
        nu = (3K0-2G)/(2(3K0+G)) = 0.3763032526;
        E  = 9*K0*G/(3K0+G)     = 103478.7364;  and E/(2(1+nu)) = G exactly."""
        _res, starter = _convert(_mat010_deck())
        rows = [ln for ln in _block(starter, "/MAT/LAW3/2")
                if not ln.startswith("#")]
        self.assertEqual(float(_fields(rows[1])[0]), 8.9e-9)
        e, nu = (float(c) for c in _fields(rows[2]))
        k0 = 8.9e-9 * 3958000.0 ** 2
        g = 37593.0
        self.assertAlmostEqual(k0, 139425.2996, places=4)
        self.assertAlmostEqual(nu, (3 * k0 - 2 * g) / (2 * (3 * k0 + g)),
                               places=9)
        self.assertAlmostEqual(e, 9 * k0 * g / (3 * k0 + g), places=3)
        self.assertAlmostEqual(e / (2 * (1 + nu)), g, places=3)

    def test_eh_goes_into_b_unconverted(self):
        """Remark 2 states sigma_y = sigma_0 + E_h*eps_p, so EH is ALREADY the
        plastic modulus: E*Et/(E-Et) here would be a silent factor error."""
        card = _MAT010.replace(
            _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0),
            _row(2, "8.9E-09", 37593.0, 180.0, 1000.0, 0.0, 0.0, 0.0))
        _res, starter = _convert(_mat010_deck(card))
        rows = [ln for ln in _block(starter, "/MAT/LAW3/2")
                if not ln.startswith("#")]
        a, b, n = (float(c) for c in _fields(rows[3])[:3])
        self.assertEqual(a, 180.0)
        self.assertEqual(b, 1000.0)
        e = float(_fields(rows[2])[0])
        self.assertNotAlmostEqual(b, e * 1000.0 / (e - 1000.0), places=2)
        self.assertEqual(n, 1.0)

    def test_pc_and_fs_reach_pmin_and_eps_max(self):
        """hvi.k states PC = -2000; Pmin = -abs(PC)."""
        card = _MAT010.replace(
            _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0),
            _row(2, "8.9E-09", 37593.0, 180.0, 0.0, -2000.0, 0.35, 0.0))
        _res, starter = _convert(_mat010_deck(card))
        rows = [ln for ln in _block(starter, "/MAT/LAW3/2")
                if not ln.startswith("#")]
        self.assertEqual(float(_fields(rows[3])[3]), 0.35)     # eps_max = FS
        self.assertEqual(float(_fields(rows[4])[0]), -2000.0)  # Pmin

    def test_zero_pc_is_written_as_a_plain_zero(self):
        """-abs(0.0) is -0.0, which formats as '-0' and reads as a typo; a
        stated 0 means 'no cutoff' (hm_read_mat03.F:182 -> -1e20)."""
        _res, starter = _convert(_mat010_deck())
        rows = [ln for ln in _block(starter, "/MAT/LAW3/2")
                if not ln.startswith("#")]
        self.assertEqual(_fields(rows[4])[0], "0")

    def test_the_same_id_eos_is_emitted_beside_the_mat(self):
        _res, starter = _convert(_mat010_deck())
        self.assertIn("/EOS/GRUNEISEN/2", starter)
        lines = starter.splitlines()
        i = lines.index("/MAT/LAW3/2")
        j = lines.index("/EOS/GRUNEISEN/2")
        self.assertLess(i, j)
        self.assertLess(j - i, 15)          # adjacent blocks, not scattered

    def test_the_eos_is_not_also_reported_as_an_orphan(self):
        """A warning that says the EOS was NOT emitted while the deck holds it
        is a false cited fact (#129)."""
        res, _starter = _convert(_mat010_deck())
        joined = " ".join(res.warnings)
        self.assertNotIn("The equation of state was NOT emitted", joined)
        self.assertNotIn("no material to attach it to", joined)

    def test_missing_eos_refuses_the_material_by_name(self):
        res, starter = _convert(_mat010_deck(eos=""))
        self.assertEqual(_headers(starter, "/MAT/LAW3/"), [])
        self.assertIn("no *EOS_* of the same id", " ".join(res.warnings))

    def test_tabulated_yield_curve_refuses_the_material_by_name(self):
        card = ("*MAT_ELASTIC_PLASTIC_HYDRO\n"
                + _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                + _row(0.0, 0.05, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                + _row(*([0.0] * 8)) + "\n"
                + _row(180.0, 220.0, 260.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                + _row(*([0.0] * 8)) + "\n")
        res, starter = _convert(_mat010_deck(card))
        self.assertEqual(_headers(starter, "/MAT/LAW3/"), [])
        self.assertIn("TABULATED yield curve", " ".join(res.warnings))

    def test_spall_option_is_refused_by_name(self):
        card = ("*MAT_ELASTIC_PLASTIC_HYDRO_SPALL\n"
                + _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                + _row(1.0, 2.0, 3.0) + "\n"
                + _row(*([0.0] * 8)) + "\n" + _row(*([0.0] * 8)) + "\n"
                + _row(*([0.0] * 8)) + "\n" + _row(*([0.0] * 8)) + "\n")
        res, starter = _convert(_mat010_deck(card))
        self.assertEqual(_headers(starter, "/MAT/LAW3/"), [])
        w = " ".join(res.warnings)
        self.assertIn("_SPALL", w)
        self.assertIn("A1=1, A2=2", w)
        self.assertIn("SPALL=3", w)

    def test_spall_card_shifts_the_eps_table_by_one_row(self):
        """The option's card 1a sits BETWEEN card 1 and EPS1..8, so a handler
        that did not stride it would read A1/A2/SPALL as the first three
        plastic strains."""
        deck = ("*KEYWORD\n*MAT_ELASTIC_PLASTIC_HYDRO_SPALL\n"
                + _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0) + "\n"
                + _row(1.0, 2.0, 3.0) + "\n"
                + _row(*([0.0] * 8)) + "\n" + _row(*([0.0] * 8)) + "\n"
                + _row(*([0.0] * 8)) + "\n" + _row(*([0.0] * 8)) + "\n"
                + "*END\n")
        state = _dispatch(deck)
        mat = state.mat_ep_hydro[2]
        self.assertTrue(mat.spall_option)
        self.assertEqual((mat.a1, mat.a2, mat.spall), (1.0, 2.0, 3.0))
        self.assertEqual(mat.eps[:3], [0.0, 0.0, 0.0])

    def test_zero_density_and_zero_shear_are_refused_by_name(self):
        for cell, needle in (
                (_row(2, 0.0, 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0),
                 "ERROR 683"),
                (_row(2, "8.9E-09", 0.0, 180.0, 0.0, 0.0, 0.0, 0.0),
                 "shear modulus is the card's only elastic cell")):
            with self.subTest(needle=needle):
                card = _MAT010.replace(
                    _row(2, "8.9E-09", 37593.0, 180.0, 0.0, 0.0, 0.0, 0.0),
                    cell)
                res, starter = _convert(_mat010_deck(card))
                self.assertEqual(_headers(starter, "/MAT/LAW3/"), [])
                self.assertIn(needle, " ".join(res.warnings))

    def test_warning_names_the_derivation_and_its_consequence(self):
        res, _starter = _convert(_mat010_deck())
        w = [x for x in res.warnings if "-> /MAT/LAW3 (HYDPLA)" in x]
        self.assertEqual(len(w), 1)
        for fact in ("K0 = rho0*C^2 = 139425", "nu = (3K0-2G)/(2(3K0+G))",
                     "= G exactly", "CONTACT STIFFNESS",
                     "hm_read_mat03.F:191", "UNCONVERTED",
                     "substitutes 1.0001"):
            self.assertIn(fact, w[0])

    def test_target_mat_law_answers_3(self):
        from k2rad.writer.mesh import _target_mat_law
        state = _dispatch(_mat010_deck())
        from k2rad.writer.materials import _resolve_mat_law3
        _resolve_mat_law3(state)
        self.assertEqual(_target_mat_law(state, 2), 3)

    def test_offset_spec_moves_the_mid_and_nothing_else(self):
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import HANDLERS, RARE_MATERIAL_KEYWORDS
        for kw in ("MAT_ELASTIC_PLASTIC_HYDRO",
                   "MAT_ELASTIC_PLASTIC_HYDRO_SPALL",
                   "MAT_010", "MAT_10", "MAT_010_SPALL", "MAT_10_SPALL"):
            self.assertEqual(_OFFSET_SPECS[kw], {"cards": {0: [(0, "m")]}})
            self.assertIn(kw, RARE_MATERIAL_KEYWORDS)
            self.assertIn(kw, HANDLERS)


# introduction/intro-by-a.-tabiei/contact/contact-foam/matfoamsoil.k's soil.
_MAT014 = ("*MAT_SOIL_AND_FOAM_FAILURE\n"
           + _row(2, "1.874E-9", 358.55, 1523.82, 0.158, 0.124, 0.024, -0.55)
           + "\n" + _row(0.0, 0.0, 0) + "\n"
           + _row(0.0, -0.05, -0.1, -0.15, -0.2, -0.25, -0.3, -0.35) + "\n"
           + _row(-0.4, -0.45) + "\n"
           + _row(0.0, 1.0, 2.5, 4.5, 7.0, 10.0, 14.0, 19.0) + "\n"
           + _row(25.0, 32.0) + "\n")


def _mat014_deck(card: str = _MAT014) -> str:
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + _BRICK
            + "*PART\np1\n" + _row(1, 1, 2) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + card + "*END\n")


class Mat014SpallingTests(unittest.TestCase):
    """A5 — *MAT_SOIL_AND_FOAM_FAILURE → /MAT/LAW21 + /FAIL/SPALLING."""

    def test_every_spelling_is_registered(self):
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import HANDLERS
        for kw in ("MAT_SOIL_AND_FOAM_FAILURE", "MAT_014", "MAT_14"):
            self.assertIn(kw, HANDLERS)
            self.assertEqual(_OFFSET_SPECS[kw],
                             {"cards": {0: [(0, "m")], 1: [(2, "f")]}})

    def test_law21_and_the_spalling_rider_are_both_emitted(self):
        _res, starter = _convert(_mat014_deck())
        self.assertIn("/MAT/LAW21/2", starter)
        rows = _data_rows(starter, "/FAIL/SPALLING/2")
        self.assertIsNotNone(rows)
        self.assertEqual([float(c) for c in _fields(rows[0])],
                         [0.0, 0.0, 0.0, 0.0, 0.0])       # D1..D5
        self.assertEqual(float(rows[1][0:20]), 0.0)       # Epsilon_Dot_0
        self.assertEqual(float(rows[1][20:40]), -0.55)    # P_min = PC
        self.assertEqual(int(rows[1][40:50]), 1)          # Ifail_so

    def test_the_plain_spelling_gets_no_rider(self):
        """MAT_005 and MAT_014 share every input cell; only the LATCH differs,
        so the plain keyword must not gain one."""
        _res, starter = _convert(_mat014_deck(
            _MAT014.replace("*MAT_SOIL_AND_FOAM_FAILURE",
                            "*MAT_SOIL_AND_FOAM")))
        self.assertIn("/MAT/LAW21/2", starter)
        self.assertEqual(_headers(starter, "/FAIL/SPALLING/"), [])

    def test_warning_names_the_latch_and_what_law21_alone_does(self):
        res, _starter = _convert(_mat014_deck())
        w = [x for x in res.warnings if "/FAIL/SPALLING/2" in x]
        self.assertEqual(len(w), 1)
        for fact in ("p.2-209", "loses its ability to carry tension",
                     "m21law.F:189", "RECOVERS",
                     "fail_spalling_s.F90:241-268", "MONOTONICALLY",
                     "NOT deleted"):
            self.assertIn(fact, w[0])

    def test_zero_pc_is_named_as_a_latch_that_can_never_trip(self):
        """hm_read_fail_spalling.F90:103 turns a zero P_min into -1e20."""
        card = _MAT014.replace(
            _row(2, "1.874E-9", 358.55, 1523.82, 0.158, 0.124, 0.024, -0.55),
            _row(2, "1.874E-9", 358.55, 1523.82, 0.158, 0.124, 0.024, 0.0))
        res, _starter = _convert(_mat014_deck(card))
        self.assertIn("the latch can never trip", " ".join(res.warnings))


class RefusedMaterialTests(unittest.TestCase):
    """A5 — the three families with no Radioss counterpart, refused BY NAME."""

    _CARDS = {
        "*MAT_INV_HYPERBOLIC_SIN":
            _row(1, "7.85E-9", 210000.0, 0.3, 1.0, 1.0, 1.0, 1.0),
        "*MAT_ACOUSTIC": _row(1, "1.0E-9", 1500.0, 0.0, 0.0),
        "*MAT_FRAZER_NASH_RUBBER_MODEL":
            _row(1, "1.0E-9", 0.495, 1.0, 0.0, 0.0, 1.0, 0.0),
    }

    def _deck(self, kw: str) -> str:
        return ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                + _BRICK
                + "*PART\np1\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + kw + "\n" + self._CARDS[kw] + "\n*END\n")

    def test_each_is_recognized_not_skipped(self):
        for kw in self._CARDS:
            with self.subTest(kw=kw):
                res, starter = _convert(self._deck(kw))
                self.assertEqual(_headers(starter, "/MAT/"), [])
                self.assertNotIn(kw.lstrip("*"), res.skipped_keywords)
                self.assertIn(kw.lstrip("*"),
                              [k for k, _ in res.recognized_not_emitted])

    def test_the_refusal_names_the_parts_and_their_element_count(self):
        res, _starter = _convert(self._deck("*MAT_INV_HYPERBOLIC_SIN"))
        w = [x for x in res.warnings if "REFUSED BY NAME" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("/PART(s) [1] name this material and hold 1 solid", w[0])
        self.assertIn("ERROR 179", w[0])
        self.assertIn("ERROR 402", w[0])       # why the part is not dropped

    def test_each_reason_is_specific_to_its_law(self):
        needles = {
            "*MAT_INV_HYPERBOLIC_SIN": "arcsinh[(Z/A)^(1/N)]",
            "*MAT_ACOUSTIC": "frequency-domain solver",
            "*MAT_FRAZER_NASH_RUBBER_MODEL": "INCLUSION FLAGS",
        }
        for kw, needle in needles.items():
            with self.subTest(kw=kw):
                res, _starter = _convert(self._deck(kw))
                self.assertIn(needle, " ".join(res.warnings))

    def test_the_dangling_part_scan_still_names_the_culprit(self):
        """A refused material is NOT in skipped_keywords, so the scan that
        quotes 'the deck's UNCONVERTED material keyword(s)' has to read the
        refusal registry too — otherwise it answers 'look above' on exactly
        the decks whose culprit is already known by name."""
        res, _starter = _convert(self._deck("*MAT_ACOUSTIC"))
        hits = [x for x in res.warnings
                if "reference a material id that NO /MAT" in x]
        self.assertTrue(hits)
        self.assertIn("*MAT_ACOUSTIC", hits[0])

    def test_numeric_aliases_reach_the_same_refusal(self):
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import HANDLERS
        for kw in ("MAT_102", "MAT_090", "MAT_031"):
            self.assertIn(kw, HANDLERS)
            self.assertEqual(_OFFSET_SPECS[kw], {"cards": {0: [(0, "m")]}})


# ale/explosion/underwater-c/underwater_C.k's TNT, verbatim.
_HE_CARD = ("*MAT_HIGH_EXPLOSIVE_BURN\n"
            + _row(2, "1.63E-09", 7840000, 26000, 0.0, 0.0, 0.0, 0.0) + "\n")
_EOS_JWL = ("*EOS_JWL\n"
            + _row(2, 371000, 3230, 4.15, 0.95, 0.3, 4300, 1.0) + "\n")
# The water: a *MAT_NULL + *EOS_GRUNEISEN pair, the other AMMG phase.
_WATER = ("*MAT_NULL\n" + _row(1, "1.0E-09") + "\n"
          "*EOS_GRUNEISEN\n"
          + _row(1, 1480000.0, 1.92, 0.0, 0.0, 0.35, 0.0, 0.0) + "\n")

_BRICK2 = """*ELEMENT_SOLID
       2       2       1       2       3       4       5       6       7       8
"""


def _he_deck(*, ammg: bool = True, card: str = _HE_CARD,
             eos: str = _EOS_JWL) -> str:
    """One water part and one explosive part, optionally an AMMG over both."""
    group = ("*ALE_MULTI-MATERIAL_GROUP\n" + _row(1, 1) + "\n" + _row(2, 1)
             + "\n") if ammg else ""
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + _BRICK + _BRICK2
            + "*PART\nwater\n" + _row(1, 1, 1) + "\n"
            + "*PART\nhe\n" + _row(2, 2, 2) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 11) + "\n"
            + "*SECTION_SOLID\n" + _row(2, 11) + "\n"
            + _WATER + card + eos + group + "*END\n")


def _bunreacted(starter: str, mid: int) -> float:
    rows = [ln for ln in _block(starter, f"/MAT/LAW5/{mid}")
            if not ln.startswith("#")]
    return float(_fields(rows[4])[2])


class HeBunreactedTests(unittest.TestCase):
    """A6 — the /MAT/LAW5 `Bunreacted` cell and its derivation."""

    def test_k_g_sigy_are_read_from_the_card(self):
        card = ("*MAT_HIGH_EXPLOSIVE_BURN\n"
                + _row(2, "1.63E-09", 7840000, 26000, 2.0, 9300.0, 3500.0,
                       200.0) + "\n")
        state = _dispatch(_he_deck(card=card, ammg=False))
        heb = state.mat_high_explosive[2]
        self.assertEqual((heb.k, heb.g, heb.sigy), (9300.0, 3500.0, 200.0))

    def test_a_stated_k_is_copied_one_to_one(self):
        """Vol II R17 p.2-188 `p = K(1/V - 1)` against jwl51.F:197
        `Psol = C01 + C11*MU1` — the same form, so no factor."""
        card = ("*MAT_HIGH_EXPLOSIVE_BURN\n"
                + _row(2, "1.63E-09", 7840000, 26000, 2.0, 9300.0, 0.0, 0.0)
                + "\n")
        res, starter = _convert(_he_deck(card=card))
        self.assertEqual(_bunreacted(starter, 2), 9300.0)
        self.assertIn("the card's own stated K = 9300", " ".join(res.warnings))

    def test_zero_k_on_an_ammg_member_is_derived_from_the_jwl(self):
        """K_s(V=1) = A*R1*e^-R1 + B*R2*e^-R2 + omega*E0
        = 371000*4.15*e^-4.15 + 3230*0.95*e^-0.95 + 0.3*4300
        = 24271.684 + 1186.715 + 1290.0 = 26748.39867 (underwater_C's TNT)."""
        import math
        want = (371000 * 4.15 * math.exp(-4.15)
                + 3230 * 0.95 * math.exp(-0.95) + 0.3 * 4300)
        self.assertAlmostEqual(want, 26748.39867, places=4)
        res, starter = _convert(_he_deck())
        self.assertAlmostEqual(_bunreacted(starter, 2), want, places=3)
        w = [x for x in res.warnings if "SUBSTITUTED" in x]
        self.assertEqual(len(w), 1)
        for fact in ("K_s(V=1) = A*R1*exp(-R1) + B*R2*exp(-R2) + omega*E0",
                     "fill_buffer_51.F:496", "ERROR 99",
                     "LS-DYNA carries NO unreacted stress at all",
                     "jwl51.F:197", "rho0*D^2 = 100189",
                     "--he-bunreacted"):
            self.assertIn(fact, w[0])

    def test_a_standalone_law5_keeps_zero(self):
        """ERROR 99 lives in the Iform = 12 branch alone, so a deck with no
        *ALE_MULTI-MATERIAL_GROUP starts fine with 0 and must not move
        (underwater_A/B, exploding-sphere, 2Dlag)."""
        res, starter = _convert(_he_deck(ammg=False))
        self.assertEqual(_bunreacted(starter, 2), 0.0)
        self.assertNotIn("SUBSTITUTED", " ".join(res.warnings))

    def test_the_override_wins_everywhere(self):
        _res, starter = _convert(_he_deck(), he_bunreacted=1234.0)
        self.assertEqual(_bunreacted(starter, 2), 1234.0)
        _res2, starter2 = _convert(_he_deck(ammg=False), he_bunreacted=1234.0)
        self.assertEqual(_bunreacted(starter2, 2), 1234.0)

    def test_g_and_sigy_are_named_as_dropped(self):
        card = ("*MAT_HIGH_EXPLOSIVE_BURN\n"
                + _row(2, "1.63E-09", 7840000, 26000, 2.0, 9300.0, 3500.0,
                       200.0) + "\n")
        res, _starter = _convert(_he_deck(card=card, ammg=False))
        w = " ".join(res.warnings)
        self.assertIn("G=3500 and SIGY=200", w)
        self.assertIn("no deviator at all", w)

    def test_the_law51_warning_no_longer_prescribes_what_k2rad_writes(self):
        """It used to end 'set it' — a prescription the converter now carries
        out itself, which would be a false cited fact (#129)."""
        res, _starter = _convert(_he_deck())
        joined = " ".join(res.warnings)
        self.assertNotIn("(ERROR 99 otherwise) — set it", joined)
        hit = [x for x in res.warnings
               if "includes JWL explosive submaterial" in x]
        self.assertEqual(len(hit), 1)
        self.assertIn("Bunreacted is written as 26748.4", hit[0])

    def test_a_member_with_no_jwl_is_refused_by_name(self):
        res, starter = _convert(_he_deck(eos=""))
        self.assertEqual(_bunreacted(starter, 2), 0.0)
        self.assertIn("The derivation reads the companion *EOS_JWL",
                      " ".join(res.warnings))

    def test_the_cli_exposes_the_override(self):
        from k2rad import cli
        args = cli.build_parser().parse_args(["deck.k"])
        self.assertIsNone(args.he_bunreacted)
        args = cli.build_parser().parse_args(["deck.k", "--he-bunreacted",
                                              "9300"])
        self.assertEqual(args.he_bunreacted, 9300.0)

    def test_the_gui_mirrors_the_cli_flag(self):
        """A CLI flag with no GUI mirror is a silently missing option, and the
        GUI is what the user actually runs."""
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD" + chr(10) + "*END" + chr(10))

        def _kw(**extra):
            return k2rad_gui.build_convert_kwargs(
                path, "", ("Mg", "mm", "s"), ground_springs=False,
                ground_spring_k_text="100", inter_gapmin_text="",
                soften_stfac_text="", **extra)

        self.assertNotIn("he_bunreacted", _kw())     # blank -> k2rad's rule
        self.assertEqual(_kw(he_bunreacted=" 9300 ")["he_bunreacted"], 9300.0)
        # An unparseable or non-positive value is an ERROR, never a silently
        # ignored blank: fill_buffer_51.F:496 refuses <= 0 with ERROR 99.
        for bad in ("abc", "0", "-1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _kw(he_bunreacted=bad)


# ale/misc/volume-fraction-a/cylinder_impact_A.k's shape: a vacuum phase, an
# ALE *MAT_PLASTIC_KINEMATIC phase, and a Lagrangian shell on a THIRD material.
_MAT003 = "*MAT_PLASTIC_KINEMATIC\n" + _row(2, "8E-09", 200000, 0.3, 200,
                                            0.0, 0.0) + "\n" \
          + _row(0.0, 0.0, 0.0, 0.0) + "\n"


def _ammg_deck(*, vacuum: bool = True, shared: bool = False,
               extra_mat: str = "") -> str:
    """Part 1 = the phase-1 material, part 2 = the *MAT_003 ALE phase, and
    (when *shared*) part 3 = a Lagrangian part on the SAME *MAT_003."""
    mats = ("*MAT_VACUUM\n" + _row(1, "1E-12") + "\n" if vacuum
            else "*MAT_NULL\n" + _row(1, "1.0E-09") + "\n"
                 "*EOS_GRUNEISEN\n"
                 + _row(1, 1480000.0, 1.92, 0.0, 0.0, 0.35, 0.0, 0.0) + "\n")
    third = ("*PART\nlag\n" + _row(3, 3, 2) + "\n"
             "*SECTION_SHELL\n" + _row(3, 2) + "\n" + _row(1.0) + "\n"
             "*ELEMENT_SHELL\n"
             "       9       3       1       2       3       4\n"
             ) if shared else ""
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + _BRICK + _BRICK2
            + "*PART\np1\n" + _row(1, 1, 1) + "\n"
            + "*PART\nale\n" + _row(2, 2, 2) + "\n"
            + third
            + "*SECTION_SOLID\n" + _row(1, 11) + "\n"
            + "*SECTION_SOLID\n" + _row(2, 11) + "\n"
            + mats + _MAT003 + extra_mat
            + "*ALE_MULTI-MATERIAL_GROUP\n" + _row(1, 1) + "\n"
            + _row(2, 1) + "\n"
            + "*END\n")


class AleSubmaterialTests(unittest.TestCase):
    """A7 — the /MAT/LAW51 phase list: vacuum, restatement, the clone."""

    def test_vacuum_and_gas_mixture_are_registered(self):
        from k2rad.assembly import _OFFSET_SPECS
        from k2rad.handlers import HANDLERS
        for kw in ("MAT_VACUUM", "MAT_140", "MAT_GAS_MIXTURE", "MAT_148"):
            self.assertIn(kw, HANDLERS)
            self.assertEqual(_OFFSET_SPECS[kw], {"cards": {0: [(0, "m")]}})

    def test_the_vacuum_part_keeps_a_material(self):
        """*MAT_VACUUM -> /MAT/VOID so the vacuum *PART resolves (a /PART
        naming no /MAT is ERROR 179, which four corpus ALE decks used to get
        on top of their LAW51 error). RHO is written verbatim, 0.0 included:
        hm_read_mat.F90:1575-1583 exempts law 0 from ERROR 683."""
        res, starter = _convert(_ammg_deck())
        self.assertIn("/MAT/VOID/1", starter)
        rows = _data_rows(starter, "/MAT/VOID/1")
        self.assertEqual([float(c) for c in _fields(rows[1])],
                         [1e-12, 0.0, 0.0])
        self.assertNotIn("reference a material id that NO /MAT",
                         " ".join(res.warnings))
        w = [x for x in res.warnings if "-> /MAT/VOID/1" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("undeclared balance IS Radioss's void", w[0])
        self.assertIn("nothing flows into it", w[0])

    def test_a_zero_density_vacuum_needs_no_substitution(self):
        deck = _ammg_deck().replace(_row(1, "1E-12"), _row(1, 0.0))
        _res, starter = _convert(deck)
        rows = _data_rows(starter, "/MAT/VOID/1")
        self.assertEqual(float(_fields(rows[1])[0]), 0.0)

    def test_the_vacuum_phase_is_dropped_and_mip_falls(self):
        """hm_read_mat51.F:608-627 reads exactly MIP rows and a tMID <= 0
        inside them is fatal, so a vacuum cannot be declared as MID 0; the
        undeclared balance of the volume fractions IS the void."""
        res, starter = _convert(_ammg_deck())
        rows = _data_rows(starter, _headers(starter, "/MAT/LAW51/")[0])
        # rows: title, card1(blank), Iform, NU/Nu_Vol(blank), then one row per
        # phase.
        phases = [r for r in rows if r.strip() and r.strip() != "12"]
        self.assertEqual(len(phases), 2)            # the title + ONE phase
        w = [x for x in res.warnings if "phase(s) DROPPED" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("MID 1 (*MAT_VACUUM -> /MAT/VOID)", w[0])
        self.assertIn("MIP falls to 1", w[0])

    def test_an_ammg_only_mat003_is_restated_under_its_own_id(self):
        _res, starter = _convert(_ammg_deck())
        self.assertIn("/MAT/LAW2/2", starter)
        self.assertEqual(_headers(starter, "/MAT/LAW44/"), [])

    def test_the_restatement_is_never_silent(self):
        """_target_mat_law already answers 2 for an AMMG-only material, so an
        'is this law allowed?' test alone would change the emitted law from 44
        to 2 with nothing said."""
        res, _starter = _convert(_ammg_deck())
        w = [x for x in res.warnings if "RESTATED as /MAT/LAW2" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("fill_buffer_51.F:210", w[0])
        self.assertIn("b = E*ETAN/(E-ETAN) = 0", w[0])

    def test_a_shared_mat003_is_cloned_instead(self):
        """A material shared with a Lagrangian part keeps /MAT/LAW44 and the
        phase list points at a minted /MAT/LAW2 — the SPH clone discipline."""
        res, starter = _convert(_ammg_deck(shared=True))
        self.assertIn("/MAT/LAW44/2", starter)
        clones = [h for h in _headers(starter, "/MAT/LAW2/")]
        self.assertEqual(len(clones), 1)
        clone_id = int(clones[0].rsplit("/", 1)[1])
        self.assertGreaterEqual(clone_id, 90001)
        w = [x for x in res.warnings if "is CLONED" in x]
        self.assertEqual(len(w), 1)
        # ...and the phase list names the CLONE, not the original.
        rows = _data_rows(starter, _headers(starter, "/MAT/LAW51/")[0])
        listed = [int(r[:10]) for r in rows
                  if r[:10].strip().isdigit() and r.strip() != "12"]
        self.assertIn(clone_id, listed)
        self.assertNotIn(2, listed)

    def test_an_unrestatable_law_is_dropped_by_name(self):
        """LAW1 is not on fill_buffer_51.F:210's list and cannot be restated
        without changing the material, so the phase goes and says so."""
        deck = _ammg_deck(vacuum=False).replace(
            "*MAT_NULL\n" + _row(1, "1.0E-09") + "\n"
            "*EOS_GRUNEISEN\n"
            + _row(1, 1480000.0, 1.92, 0.0, 0.0, 0.35, 0.0, 0.0) + "\n",
            "*MAT_ELASTIC\n" + _row(1, "1.0E-09", 210000.0, 0.3) + "\n")
        res, _starter = _convert(deck)
        w = [x for x in res.warnings if "phase(s) DROPPED" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("MID 1 (/MAT/LAW1)", w[0])
        self.assertIn("unreachable yield", w[0])

    def test_the_law51_card_states_that_nothing_references_it(self):
        """The emitted /MAT/LAW51 is an orphan: the per-fluid ALE parts are
        kept, so the phases cannot mix and the run does not reproduce the
        LS-DYNA model. That has to be unmissable (#122 at deck scale)."""
        res, starter = _convert(_ammg_deck())
        law_id = int(_headers(starter, "/MAT/LAW51/")[0].rsplit("/", 1)[1])
        self.assertNotIn(f"         {law_id}", "\n".join(
            _data_rows(starter, "/PART/1") or []))
        w = [x for x in res.warnings if "listing submaterials" in x]
        self.assertEqual(len(w), 1)
        for fact in ("no /PART in the emitted deck references this /MAT/LAW51",
                     "CANNOT MIX",
                     "DOES NOT REPRODUCE THE LS-DYNA MODEL",
                     "ALPHA_MAT values are a PLACEHOLDER"):
            self.assertIn(fact, w[0])

    def test_an_all_dropped_group_emits_no_law51(self):
        deck = _ammg_deck().replace(
            "*ALE_MULTI-MATERIAL_GROUP\n" + _row(1, 1) + "\n" + _row(2, 1)
            + "\n",
            "*ALE_MULTI-MATERIAL_GROUP\n" + _row(1, 1) + "\n")
        res, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/MAT/LAW51/"), [])
        self.assertIn("no submaterial survives", " ".join(res.warnings))

if __name__ == "__main__":
    unittest.main()
