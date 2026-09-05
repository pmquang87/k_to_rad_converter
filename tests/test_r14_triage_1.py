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

if __name__ == "__main__":
    unittest.main()
