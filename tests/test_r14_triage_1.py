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
  B1  *SECTION_BEAM ELFORM=3       -> /PROP/TYPE2 (TRUSS) + /TRUSS elements
  B2  a material stating RO <= 0   -> the 1e-24 density floor (opt-out)

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


def _state_and_starter(deck: str):
    """Parse + dispatch + build_starter, returning the FINAL state (every
    writer prepass and every write-line register filled) and the deck text."""
    from k2rad.writer import build_starter
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    state = ConversionState()
    for block in parse_k_file(path):
        dispatch(block, state)
    starter = build_starter(state)
    tmp.cleanup()
    return state, starter


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

    def test_the_standin_id_dodges_a_user_material_on_the_same_id(self):
        """#131: a collision probe must target the id the allocator would
        ACTUALLY take, not the auto-id base.

        Pass 1 learns which id ``next_mat_id()`` reaches on this deck; pass 2
        puts a user ``*MAT_ELASTIC`` on exactly that id and asserts the
        stand-in steps past it with no duplicate ``/MAT`` header. Asserting
        only ``mid >= 90001`` would pass whether or not the allocator's
        ``all_mat_ids()`` loop is there at all.
        """
        _r1, starter1 = _convert(_thermal_only_deck())
        taken = _mat_id(starter1, "ELAST")
        deck2 = _thermal_only_deck(
            extra="*MAT_ELASTIC\n"
                  + _row(taken, "7.85E-09", 210000.0, 0.3) + "\n")
        _r2, starter2 = _convert(deck2)
        heads = [ln for ln in starter2.splitlines()
                 if ln.startswith("/MAT/") and not ln.startswith("/MAT/LAW")]
        self.assertEqual(len(heads), len(set(heads)), heads)
        ids = sorted(int(h.rsplit("/", 1)[1]) for h in heads
                     if h.startswith("/MAT/ELAST/"))
        self.assertIn(taken, ids)            # the user material kept its id
        self.assertEqual(len(ids), 2, heads)  # and the stand-in moved past it
        self.assertGreater(max(ids), taken)

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

    def test_a_part_whose_thermal_material_is_refused_is_NAMED(self):
        """It gets NO stand-in (there would be no /HEAT/MAT to carry) and no
        other diagnostic either: it never reaches _resolve_heat_materials'
        `wanted` set, and _warn_dangling_part_materials treats mat_ID 0 as the
        connector convention. Named here or nowhere. MEASURED on 05_4_1 /
        05_5_1, whose weld-seam part carries *MAT_THERMAL_CWM."""
        deck = _thermal_only_deck(extra="*MAT_THERMAL_CWM" + chr(10)
                                  + _row(9, "7.85E-09", 0, 0.0) + chr(10))
        deck = deck.replace(_row(1, 1, 0, 0, 0, 0, 0, 1),
                            _row(1, 1, 0, 0, 0, 0, 0, 9))
        res, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/MAT/ELAST/"), [])
        w = [x for x in res.warnings if "/PART 1 (TMID 9)" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("a weld that never heats", w[0])
        self.assertIn("ERROR 179", w[0])

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
        """UPDATED by B2, not weakened: the refusal is now GATED on
        ``--no-zero-density-floor``. With the default floor ON the density is
        substituted and the material converts (see
        ``ZeroDensityFloor.test_law106_is_rescued_rather_than_refused``);
        with the floor OFF the original refusal stands, verbatim."""
        card = _MAT004_STEEL.replace(_row(1, "7.85000E-9"), _row(1, 0.0))
        res, starter = _convert(_mat004_deck(card), zero_density_floor=False)
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
                     "hm_read_mat03.F:190/197", "UNCONVERTED",
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
        """hm_read_fail_spalling.F90:102 turns a zero P_min into -1e20."""
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
        # The statement lives on the LAW5 side now that the /MAT/LAW51 that
        # used to carry it is not emitted by default. Nothing is SUBSTITUTED:
        # the deck states its own K.
        w = [x for x in res.warnings
             if "the card's own stated K, copied 1:1" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("Bunreacted = 9300", w[0])
        self.assertIn("mjwl.F:166-167", w[0])
        self.assertNotIn("SUBSTITUTED", " ".join(res.warnings))

    def test_zero_k_on_an_ammg_member_is_derived_from_the_jwl(self):
        """The value is the PRINCIPAL ISENTROPE's slope at V = 1,
        A*R1*e^-R1 + B*R2*e^-R2 + omega*E0
        = 371000*4.15*e^-4.15 + 3230*0.95*e^-0.95 + 0.3*4300
        = 24271.684 + 1186.715 + 1290.0 = 26748.39867 (underwater_C's TNT).

        Only under ``--ale-multimat-law51``: the derivation exists solely to
        answer ``fill_buffer_51.F:496`` on the synthesized /MAT/LAW51, which
        is orphan by construction and is not emitted by default.

        The warning's SOURCE CLAIMS are pinned alongside it. The POST-REVIEW
        round corrected the consumer a second time: ``m5law.F:135-145`` does
        branch on the cell, but it writes ``P``, a LOCAL declared at ``:72``
        and read only at ``:159`` to build ``SSP``, and the routine zeroes the
        stress tensor at ``:175-182``. The applied pressure is ``mjwl.F:166``,
        which has NO branch on the cell — so a positive value is an ADDED
        ``(1-F)*K*mu`` pre-burn stiffness at every burn fraction, not a branch
        switch. The full-EOS alternative is printed beside it because
        ``jwl51.F:191`` and ``m5law.F:126-129`` both carry the
        ``(1 - omega/(R_i*V))`` factors the principal isentrope does not.
        """
        import math
        want = (371000 * 4.15 * math.exp(-4.15)
                + 3230 * 0.95 * math.exp(-0.95) + 0.3 * 4300)
        self.assertAlmostEqual(want, 26748.39867, places=4)
        full = (371000 * math.exp(-4.15) * (4.15 - 0.3 / 4.15 - 0.3)
                + 3230 * math.exp(-0.95) * (0.95 - 0.3 / 0.95 - 0.3)
                + 0.3 * 4300)
        self.assertAlmostEqual(full, 23801.8, places=1)
        res, starter = _convert(_he_deck(), ale_multimat_law51=True)
        self.assertAlmostEqual(_bunreacted(starter, 2), want, places=3)
        w = [x for x in res.warnings if "SUBSTITUTED" in x]
        self.assertEqual(len(w), 1)
        for fact in ("PRINCIPAL ISENTROPE",
                     "A*R1*exp(-R1) + B*R2*exp(-R2) + omega*E0",
                     "fill_buffer_51.F:496", "ERROR 99",
                     "LS-DYNA carries NO unreacted stress at all",
                     # the CORRECTED consumer: mjwl, with no branch on the cell
                     "mmain.F90:1225-1261", "mjwl.F:166-167",
                     "ALWAYS burn-fraction weighted",
                     "ADDED (1-F)*K*mu pre-burn stiffness",
                     # m5law's branch is named as the SOUND SPEED one it is
                     "m5law.F:135-145", "LOCAL declared at :72",
                     "SOUND SPEED",
                     # the LAW51 path is named as the one that does NOT run
                     "jwl51.F:197",
                     # both alternatives, with their numbers
                     "rho0*D^2 = 100189", "3.75x stiffer",
                     "23801.8", "11 % below the value written",
                     "--he-bunreacted"):
            self.assertIn(fact, w[0])
        # and NOTHING of the superseded branch-switch reading survives
        for gone in ("BRANCH SWITCH", "IF (BULK == ZERO)",
                     "with no burn-fraction weighting at all"):
            self.assertNotIn(gone, w[0])

    def test_a_degenerate_jwl_is_refused_by_name_not_by_zerodivision(self):
        """Both ARMS of a back-solve must refuse the same degeneracies (#129).

        A ``*EOS_JWL`` stating ``A = B = E0 = 0`` makes the derivation exactly
        0, and the warning's own ``rho0*D^2 / Bunreacted`` ratio then divides
        by it — which used to raise ``ZeroDivisionError`` out of
        ``writer/assembly``, aborting the whole conversion with no output and
        no diagnostic. Every sibling derivation in this batch screens its
        degenerate case (LAW3 ``bulk <= 0``, LAW106 ``e_ref <= 0``), so this
        one must too.
        """
        eos = ("*EOS_JWL\n"
               + _row(2, 0.0, 0.0, 4.15, 0.95, 0.3, 0.0, 1.0) + "\n")
        res, starter = _convert(_he_deck(eos=eos),
                                ale_multimat_law51=True)
        self.assertEqual(_bunreacted(starter, 2), 0.0)
        w = [x for x in res.warnings
             if "no positive" in x or "not a positive bulk modulus" in x]
        self.assertEqual(len(w), 1, res.warnings)
        for fact in ("principal-isentrope slope of 0",
                     "fill_buffer_51.F:496", "ERROR 99", "--he-bunreacted"):
            self.assertIn(fact, w[0])
        # and NOT the SUBSTITUTED message, which would have divided by zero
        self.assertNotIn("SUBSTITUTED", " ".join(res.warnings))

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
        res, _starter = _convert(_he_deck(), ale_multimat_law51=True)
        joined = " ".join(res.warnings)
        self.assertNotIn("(ERROR 99 otherwise) — set it", joined)
        hit = [x for x in res.warnings
               if "includes JWL explosive submaterial" in x]
        self.assertEqual(len(hit), 1)
        self.assertIn("Bunreacted is written as 26748.4", hit[0])

    def test_a_member_with_no_jwl_is_refused_by_name(self):
        res, starter = _convert(_he_deck(eos=""),
                                ale_multimat_law51=True)
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
        # 0 IS legal and is now the default: fill_buffer_51.F:496 can only fire
        # on an emitted /MAT/LAW51, and mjwl.F:166 at BULK = 0 is exactly
        # LS-DYNA's p = F*p_eos. It must reach convert(), not be rejected.
        self.assertEqual(_kw(he_bunreacted="0")["he_bunreacted"], 0.0)
        # An unparseable or NEGATIVE value is still an ERROR, never a silently
        # ignored blank — a bulk modulus cannot be negative.
        for bad in ("abc", "-1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _kw(he_bunreacted=bad)

    def test_the_orphan_law51_is_not_emitted_by_default(self):
        """The card is an ORPHAN BY CONSTRUCTION — k2rad writes the LS-DYNA
        per-fluid ALE layout, so no /PART it emits can reference it — and it
        is MEASURED inert (deleting it left all 164 underwater_C T01 channels
        identical at all 172 samples). Its only real effect was its own
        starter check, fill_buffer_51.F:496, which forced a positive
        Bunreacted onto the material's LIVE /MAT/LAW5; mjwl.F:166-167 has no
        branch on that cell, so it is an ADDED (1-F)*K*mu pre-burn stiffness
        that an LS-DYNA BETA = 0 card (p = F*p_eos) does not carry."""
        res, starter = _convert(_he_deck())
        self.assertNotIn("/MAT/LAW51/", starter)
        self.assertEqual(_bunreacted(starter, 2), 0.0)
        self.assertNotIn("SUBSTITUTED", " ".join(res.warnings))
        w = [x for x in res.warnings if "NO /MAT/LAW51 is emitted" in x]
        self.assertEqual(len(w), 1, res.warnings)

    def test_the_flag_restores_the_card_and_the_derivation(self):
        """--ale-multimat-law51 is a complete restoration: on underwater_C it
        reproduces the pre-fix starter deck BYTE for byte."""
        res, starter = _convert(_he_deck(), ale_multimat_law51=True)
        self.assertIn("/MAT/LAW51/", starter)
        self.assertAlmostEqual(_bunreacted(starter, 2), 26748.39867, places=3)
        self.assertIn("SUBSTITUTED", " ".join(res.warnings))

    def test_zero_override_now_produces_a_startable_deck(self):
        """--he-bunreacted 0 is the documented way back to LS-DYNA semantics
        and used to emit a deck the starter refused with ERROR 99, because the
        orphan /MAT/LAW51 was written anyway. MEASURED, four underwater_C
        variants: card kept + 0 -> 'ERROR ID : 99'; card dropped + 0 ->
        0 ERROR / 0 WARNING / NORMAL TERMINATION / 172 cycles."""
        _res, starter = _convert(_he_deck(), he_bunreacted=0.0)
        self.assertEqual(_bunreacted(starter, 2), 0.0)
        self.assertNotIn("/MAT/LAW51/", starter)

    def test_the_cli_and_gui_expose_the_card_flag(self):
        from k2rad import cli
        self.assertFalse(
            cli.build_parser().parse_args(["deck.k"]).ale_multimat_law51)
        self.assertTrue(cli.build_parser().parse_args(
            ["deck.k", "--ale-multimat-law51"]).ale_multimat_law51)
        self.assertFalse(cli.build_parser().parse_args(
            ["deck.k", "--no-ale-multimat-law51"]).ale_multimat_law51)
        import k2rad_gui
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write("*KEYWORD" + chr(10) + "*END" + chr(10))
        kw = k2rad_gui.build_convert_kwargs(
            path, "", ("Mg", "mm", "s"), ground_springs=False,
            ground_spring_k_text="100", inter_gapmin_text="",
            soften_stfac_text="", ale_multimat_law51=True)
        self.assertTrue(kw["ale_multimat_law51"])


# ale/misc/volume-fraction-a/cylinder_impact_A.k's shape: a vacuum phase, an
# ALE *MAT_PLASTIC_KINEMATIC phase, and a Lagrangian shell on a THIRD material.
_MAT003 = "*MAT_PLASTIC_KINEMATIC\n" + _row(2, "8E-09", 200000, 0.3, 200,
                                            0.0, 0.0) + "\n" \
          + _row(0.0, 0.0, 0.0, 0.0) + "\n"


def _ammg_deck(*, vacuum: bool = True, fluid: bool = False) -> str:
    """Part 1 = a *MAT_VACUUM phase, part 2 = the *MAT_003 ALE phase.

    With ``fluid=True`` part 2's material becomes a *MAT_NULL + *EOS_GRUNEISEN
    pair - the only shape that is a LEGAL /MAT/LAW51 phase, because
    fill_buffer_51.F:281 refuses any non-explosive submaterial whose EOS_TYPE
    is 0. A probe has to reach that branch to test anything past it (#130).
    """
    mats = ("*MAT_VACUUM" + chr(10) + _row(1, "1E-12") + chr(10) if vacuum
            else "*MAT_NULL" + chr(10) + _row(1, "1.0E-09") + chr(10))
    phase2 = (("*MAT_NULL" + chr(10) + _row(2, "1.0E-09") + chr(10)
               + "*EOS_GRUNEISEN" + chr(10)
               + _row(2, 1480000.0, 1.92, 0.0, 0.0, 0.35, 0.0, 0.0) + chr(10))
              if fluid else _MAT003)
    return ("*KEYWORD" + chr(10)
            + "*CONTROL_TERMINATION" + chr(10) + _row(1.0) + chr(10)
            + _BRICK + _BRICK2
            + "*PART" + chr(10) + "p1" + chr(10) + _row(1, 1, 1) + chr(10)
            + "*PART" + chr(10) + "ale" + chr(10) + _row(2, 2, 2) + chr(10)
            + "*SECTION_SOLID" + chr(10) + _row(1, 11) + chr(10)
            + "*SECTION_SOLID" + chr(10) + _row(2, 11) + chr(10)
            + mats + phase2
            + "*ALE_MULTI-MATERIAL_GROUP" + chr(10) + _row(1, 1) + chr(10)
            + _row(2, 1) + chr(10)
            + "*END" + chr(10))


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
        res, starter = _convert(_ammg_deck(fluid=True),
                                ale_multimat_law51=True)
        law51 = _headers(starter, "/MAT/LAW51/")
        self.assertEqual(len(law51), 1)
        rows = [r for r in _data_rows(starter, law51[0])
                if r.strip() and r.strip() != "12"]
        self.assertEqual(len(rows), 2)          # the title + ONE phase row
        w = [x for x in res.warnings if "phase(s) DROPPED" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("MID 1 (*MAT_VACUUM -> /MAT/VOID)", w[0])
        self.assertIn("MIP falls to 1", w[0])

    def test_a_phase_without_an_eos_is_dropped_by_name(self):
        """MEASURED on cylinder_impact_A, and it CORRECTS the source's own
        comment: fill_buffer_51.F:213-219's THEN branch is empty and its ELSE
        raises 'SUBMATERIAL EOS IS NOT COMPATIBLE WITH MATERIAL LAW 51', while
        :281 adds 'MISSING SUBMATERIAL EOS' for EOS_TYPE 0 on any MLN /= 5.
        A *MAT_PLASTIC_KINEMATIC ALE phase carries no equation of state, so
        restating LAW44 as LAW2 would clear the law test and then die on the
        EOS one - the phase is dropped instead."""
        res, starter = _convert(_ammg_deck())
        self.assertEqual(_headers(starter, "/MAT/LAW51/"), [])
        self.assertIn("/MAT/LAW44/2", starter)      # the material is untouched
        w = [x for x in res.warnings if "phase(s) DROPPED" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("it carries no /EOS", w[0])
        self.assertIn("MISSING SUBMATERIAL EOS", w[0])
        self.assertIn("no submaterial survives", " ".join(res.warnings))

    def test_a_mat003_ale_member_is_not_silently_restated(self):
        """_target_mat_law must keep answering 44: a restatement that can
        never produce a legal phase would change the emitted law for nothing
        (and LAW44 is what the material's Lagrangian side needs)."""
        from k2rad.writer.mesh import _target_mat_law
        state = _dispatch(_ammg_deck())
        self.assertEqual(_target_mat_law(state, 2), 44)

    def test_the_allowed_submaterial_laws_are_the_starter_s_own_list(self):
        """fill_buffer_51.F:210 gates on MLN == 2/3/4/5/6/10/102/133 and :237
        prints exactly that list. The law screen built on it is a GUARD and is
        unreachable today - every material k2rad gives an /EOS to lands on law
        3, 4, 5 or 6, all four on the list, so nothing survives the EOS screen
        and then fails the law one. Pinned so the constant cannot drift from
        the message the starter prints."""
        from k2rad.writer.materials import _LAW51_ALLOWED_SUBMAT_LAWS
        self.assertEqual(sorted(_LAW51_ALLOWED_SUBMAT_LAWS),
                         [2, 3, 4, 5, 6, 10, 102, 133])

    def test_the_law51_card_states_that_nothing_references_it(self):
        """The emitted /MAT/LAW51 is an orphan: the per-fluid ALE parts are
        kept, so the phases cannot mix and the run does not reproduce the
        LS-DYNA model. That has to be unmissable (#122 at deck scale).

        Under --ale-multimat-law51, since the card is orphan BY CONSTRUCTION
        and is no longer written by default."""
        res, starter = _convert(_ammg_deck(fluid=True),
                                ale_multimat_law51=True)
        law_id = int(_headers(starter, "/MAT/LAW51/")[0].rsplit("/", 1)[1])
        self.assertNotIn(str(law_id), chr(10).join(
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


# ─────────────────────────────────────────────────────────────────────────────
# B1 — *SECTION_BEAM ELFORM=3 -> /PROP/TYPE2 (TRUSS) + /TRUSS
# ─────────────────────────────────────────────────────────────────────────────

#: A two-node bar of length 100 on part 1, section 1, material 1.
_BAR_NODES = """*NODE
         1             0.0             0.0             0.0
         2           100.0             0.0             0.0
         3           200.0             0.0             0.0
         4             0.0            50.0             0.0
"""


def _truss_deck(*, elform: int = 3, area: float = 25.0, rampt: float = 0.0,
                stress: float = 0.0, mat: str = "", extra: str = "",
                elems: str = "", n3: str = "") -> str:
    """A minimal ELFORM=3 truss deck: two bars, one section, one material."""
    mat = mat or ("*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n")
    elems = elems or ("*ELEMENT_BEAM\n"
                      + f"{10:>8}{1:>8}{1:>8}{2:>8}{n3:>8}" + "\n"
                      + f"{11:>8}{1:>8}{2:>8}{3:>8}{n3:>8}" + "\n")
    return ("*KEYWORD\n"
            + _BAR_NODES
            + "*PART\nbar\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_BEAM\n" + _row(1, elform, 1.0, 0.0, 0) + "\n"
            + _row(area, rampt, stress) + "\n"
            + mat + elems + extra
            + "*CONTROL_TERMINATION\n" + _row(0.01) + "\n*END\n")


class TrussCards(unittest.TestCase):
    """The two card layouts, resolved for /BEGIN 2022 and starter-validated on
    ``F:/dynaexamples_r14_ton-mm-s/intro-by-j.-day/elements/rod-i/rod.k``
    (0 ERROR / 0 WARNING; engine NORMAL TERMINATION, 415 cycles, element type
    echoed as TRUSS)."""

    def test_the_element_block_is_three_cells(self):
        """``radioss41/ELEM/truss.cfg``: ``CARD("%10d%10d%10d",id,node_ID1,
        node_ID2)`` — no third node, no orientation cell, no offset cell.
        ``hm_read_truss.F:148-151`` takes material and property from the
        /PART."""
        _r, starter = _convert(_truss_deck())
        rows = _data_rows(starter, "/TRUSS/1")
        self.assertEqual(rows, [f"{10:>10}{1:>10}{2:>10}",
                                f"{11:>10}{2:>10}{3:>10}"])
        for ln in rows:
            self.assertEqual(len(ln.rstrip()), 30)
        # ... and the part gets NO /BEAM block at all.
        self.assertEqual(_headers(starter, "/BEAM/"), [])

    def test_the_property_is_area_and_a_zero_gap(self):
        """``prop_p2_trus.cfg`` FORMAT(radioss51) = ``%20lg%20lg`` AREA GAP.
        GAP is written 0 ALWAYS: ``tforc3.F:184-186`` turns a positive
        ``GEO(2)`` into a compression-only GAP ELEMENT, and nothing on
        ``*SECTION_BEAM`` ELFORM 3 maps to that."""
        _r, starter = _convert(_truss_deck(area=25.0))
        self.assertEqual(_headers(starter, "/PROP/TYPE2/"), ["/PROP/TYPE2/1"])
        rows = _data_rows(starter, "/PROP/TYPE2/1")
        # row 0 is the title card, row 1 the two cells.
        self.assertEqual(_fields(rows[1]), ["25", "0"])
        self.assertEqual(_headers(starter, "/PROP/BEAM/"), [])

    def test_a_zero_area_section_is_refused_not_emitted(self):
        """Card 2b (the NAMED standard section) reaches ELFORM 3 too, and reads
        no area — ``hm_read_prop02.F:117-124`` is ERROR 497 on ``AREA <= 0``.
        Before this batch such a section became a /PROP/BEAM with Area 0
        (ERROR 314); it must not now become a /PROP/TYPE2 with Area 0."""
        deck = ("*KEYWORD\n" + _BAR_NODES
                + "*PART\nbar\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_BEAM\n" + _row(1, 3, 1.0, 0.0, 0) + "\n"
                + "SECTION_01".ljust(10) + _row(10.0, 5.0) + "\n"
                + "*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
                + "*ELEMENT_BEAM\n" + f"{10:>8}{1:>8}{1:>8}{2:>8}" + "\n"
                + "*END\n")
        res, starter = _convert(deck)
        self.assertEqual(_headers(starter, "/PROP/TYPE2/"), [])
        self.assertTrue(any("ERROR 497" in w for w in res.warnings),
                        res.warnings)
        # The elements stay: the mesh is not the defect.
        self.assertTrue(_headers(starter, "/TRUSS/"))

    def test_the_write_line_register_is_filled(self):
        """The #106 rule: ``state.truss_elem_ids`` is filled AT the row, so a
        beam whose part the writer never visits is not in it — and the register
        is the ONLY place that knows which of /BEAM and /TRUSS an id landed in,
        because both families stay in ``state.beam_elems``."""
        deck = _truss_deck(
            elems=("*ELEMENT_BEAM\n"
                   + f"{10:>8}{1:>8}{1:>8}{2:>8}" + "\n"
                   # part 99 has no *PART record -> mesh loss, never written
                   + f"{77:>8}{99:>8}{2:>8}{3:>8}" + "\n"))
        st, starter = _state_and_starter(deck)
        # PARSED: both rows are beam elements on the LS-DYNA side.
        self.assertEqual({e.eid for e in st.beam_elems}, {10, 77})
        # EMITTED: only the one whose /PART exists reached a /TRUSS row.
        self.assertEqual(st.truss_elem_ids, {10})
        self.assertEqual(st.beam_elem_ids, set())
        self.assertEqual(_data_rows(starter, "/TRUSS/1"),
                         [f"{10:>10}{1:>10}{2:>10}"])

    def test_the_offset_walk_needs_no_new_spelling(self):
        """C1: a truss is still spelled ``*ELEMENT_BEAM`` + ``*SECTION_BEAM``,
        so ``assembly._OFFSET_SPECS`` sees NO new keyword and the #116
        combinatorics table needs no new entry. That is a verdict, not an
        omission — the /TRUSS routing is decided on the WRITE side from
        ``sec.elform``, after every offset pass has run. Pinned by moving a
        whole truss deck through an *INCLUDE_TRANSFORM."""
        inner = _truss_deck()
        tmp = tempfile.TemporaryDirectory()
        child = os.path.join(tmp.name, "child.k")
        with open(child, "w") as fh:
            fh.write(inner)
        root = ("*KEYWORD\n"
                + "*INCLUDE_TRANSFORM\n" + "child.k\n"
                # card 2: idnoff ideoff idpoff idmoff idsoff idfoff iddoff
                + _row(1000, 2000, 3000, 4000, 0, 0, 0) + "\n"
                # card 3 field 1: IDROFF, which is the *SECTION id bucket
                + _row(5000) + "\n"
                # card 4: fctmas fcttim fctlen fcttem incout1
                + _row(0, 0, 0, 0.0, 0.0) + "\n"
                + "*CONTROL_TERMINATION\n" + _row(0.01) + "\n*END\n")
        path = os.path.join(tmp.name, "root.k")
        with open(path, "w") as fh:
            fh.write(root)
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        from k2rad.writer import build_starter
        starter = build_starter(state)
        tmp.cleanup()
        # Element ids +2000, node ids +1000, part id +3000, section id +5000.
        self.assertEqual(_headers(starter, "/TRUSS/"), ["/TRUSS/3001"])
        self.assertEqual(_data_rows(starter, "/TRUSS/3001"),
                         [f"{2010:>10}{1001:>10}{1002:>10}",
                          f"{2011:>10}{1002:>10}{1003:>10}"])
        self.assertEqual(_headers(starter, "/PROP/TYPE2/"),
                         ["/PROP/TYPE2/5001"])
        self.assertEqual(state.truss_elem_ids, {2010, 2011})


class TrussSectionCells(unittest.TestCase):
    """RAMPT / STRESS — screened, then named. Vol I R17 p.41-18: they are a
    DYNAMIC-RELAXATION pre-tension pair."""

    def test_an_inert_pair_is_reported_as_inert(self):
        """``ex_05_beam_elform_3_&_6.k`` states RAMPT = STRESS = 1.0 and has no
        relaxation phase, so the cells do nothing in LS-DYNA either. Calling
        that "DROPPED" would be a false alarm (#125)."""
        res, _s = _convert(_truss_deck(rampt=1.0, stress=1.0))
        hit = [w for w in res.warnings if "RAMPT" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("INERT in LS-DYNA too", hit[0])
        self.assertIn("NO dynamic-relaxation phase", hit[0])

    def test_a_live_pair_states_the_equivalent_preload_force(self):
        """With a relaxation phase the pair IS live, and the honest statement
        is the force /PRELOAD/AXIAL would take: STRESS x A."""
        res, _s = _convert(_truss_deck(
            area=25.0, rampt=0.002, stress=100.0,
            extra="*CONTROL_DYNAMIC_RELAXATION\n" + _row(250, 0.001) + "\n"))
        hit = [w for w in res.warnings if "RAMPT" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("STRESS x A = 2500", hit[0])
        self.assertIn("starts UNSTRESSED", hit[0])

    def test_a_curve_sidr_alone_starts_a_relaxation_phase(self):
        """A deck can start one from the curve alone — SIDR 1 = "load curve
        used in stress initialization", 2 = both phases (p.17-104)."""
        curve = ("*DEFINE_CURVE\n" + _row(9, 2) + "\n"
                 + _row16(0.0, 0.0) + "\n" + _row16(1.0, 1.0) + "\n")
        res, _s = _convert(_truss_deck(area=25.0, rampt=0.002, stress=100.0,
                                       extra=curve))
        hit = [w for w in res.warnings if "RAMPT" in w]
        self.assertIn("STRESS x A = 2500", hit[0])

    def test_a_zero_pair_says_nothing(self):
        res, _s = _convert(_truss_deck())
        self.assertEqual([w for w in res.warnings if "RAMPT" in w], [])


class TrussElementCells(unittest.TestCase):
    """The *ELEMENT_BEAM cells a truss cannot carry."""

    def test_a_translational_release_is_named(self):
        """RT1/RT2 (fields 6 and 8) are a REAL loss on a truss: axial
        translation is its only load path."""
        elems = ("*ELEMENT_BEAM\n"
                 + f"{10:>8}{1:>8}{1:>8}{2:>8}{'':>8}{7:>8}{0:>8}{0:>8}" + "\n")
        res, _s = _convert(_truss_deck(elems=elems))
        hit = [w for w in res.warnings if "TRANSLATIONAL release" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("TOTAL loss", hit[0])
        self.assertIn("Rotational releases (RR1/RR2)", hit[0])

    def test_a_rotational_release_alone_says_nothing(self):
        """RR1/RR2 and LOCAL are inert on a truss — a truss transmits no
        moment, and LOCAL is only the FRAME of a stated release."""
        elems = ("*ELEMENT_BEAM\n"
                 + f"{10:>8}{1:>8}{1:>8}{2:>8}{'':>8}{0:>8}{7:>8}{0:>8}"
                   f"{7:>8}{2:>8}" + "\n")
        res, _s = _convert(_truss_deck(elems=elems))
        self.assertEqual([w for w in res.warnings
                          if "TRANSLATIONAL release" in w], [])

    def test_no_orientation_node_is_synthesized_for_a_truss(self):
        """B1 of the #120 audit. A synthesized node would be referenced by
        nothing and would enter ``beam_orient_nodes``, which the implicit
        free-node sweeper SUBTRACTS."""
        elems = ("*ELEMENT_BEAM_ORIENTATION\n"
                 + f"{10:>8}{1:>8}{1:>8}{2:>8}" + "\n"
                 + f"{0.0:>10}{0.0:>10}{1.0:>10}" + "\n")
        res, starter = _convert(_truss_deck(elems=elems))
        self.assertTrue(any("no third node is synthesized" in w
                            for w in res.warnings), res.warnings)
        # Four *NODE records in, four out — nothing was minted.
        self.assertEqual(len(_data_rows(starter, "/NODE")), 4)

    def test_an_ordinary_beam_still_gets_its_orientation_node(self):
        """The exclusion is scoped to trusses: an ELFORM=2 part is
        untouched."""
        elems = ("*ELEMENT_BEAM_ORIENTATION\n"
                 + f"{10:>8}{1:>8}{1:>8}{2:>8}" + "\n"
                 + f"{0.0:>10}{0.0:>10}{1.0:>10}" + "\n")
        res, starter = _convert(_truss_deck(elform=2, elems=elems))
        self.assertTrue(any("third node(s) synthesized" in w
                            for w in res.warnings), res.warnings)
        self.assertEqual(len(_data_rows(starter, "/NODE")), 5)


class TrussMaterialGate(unittest.TestCase):
    """check_mat_elem_prop_compatibility.F:331-335 (ERROR 3046) / :373-374
    (ERROR 3047). PROP_TRUSS = 1 is declared by exactly six laws."""

    def test_the_law_set_is_the_six_init_mat_keyword_call_sites(self):
        from k2rad.writer.truss import _TRUSS_LAWS
        self.assertEqual(set(_TRUSS_LAWS), {0, 1, 2, 13, 34, 44})

    def test_law36_on_a_truss_is_named(self):
        """*MAT_PIECEWISE_LINEAR_PLASTICITY -> /MAT/LAW36 is BEAM_INTEGRATED
        only and is NOT truss-compatible; it is the single most common
        LS-DYNA metal law."""
        mat = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
               + _row(1, "7.85E-09", 210000.0, 0.3, 250.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        res, _s = _convert(_truss_deck(mat=mat))
        hit = [w for w in res.warnings if "ERROR 3046" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("/MAT/LAW36", hit[0])
        self.assertIn("part 1 on mid 1", hit[0])

    def test_law1_on_a_truss_says_nothing(self):
        res, _s = _convert(_truss_deck())
        self.assertEqual([w for w in res.warnings if "ERROR 3046" in w], [])

    def test_a_zero_force_law_is_named_separately(self):
        """LAW0 (VOID) IS accepted by the starter but its engine arm writes no
        force at all — ``tforc3.F:189-224`` dispatches only MTN 1/2/34/44."""
        mat = "*MAT_NULL\n" + _row(1, "7.85E-09") + "\n"
        res, _s = _convert(_truss_deck(mat=mat))
        hit = [w for w in res.warnings if "carries NO FORCE by design" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("/MAT/LAW0", hit[0])

    def test_a_refused_section_warns_about_no_material(self):
        """The gate is driven by the sections that ACTUALLY emitted a
        /PROP/TYPE2 — a refused one is not warned about twice."""
        deck = ("*KEYWORD\n" + _BAR_NODES
                + "*PART\nbar\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_BEAM\n" + _row(1, 3, 1.0, 0.0, 0) + "\n"
                + "SECTION_01".ljust(10) + _row(10.0, 5.0) + "\n"
                + "*MAT_BLATZ-KO_RUBBER\n" + _row(1, "1.0E-09", 5.0) + "\n"
                + "*ELEMENT_BEAM\n" + f"{10:>8}{1:>8}{1:>8}{2:>8}" + "\n"
                + "*END\n")
        res, _s = _convert(deck)
        self.assertEqual([w for w in res.warnings if "ERROR 3046" in w], [])


class TrussRegistryAudit(unittest.TestCase):
    """The #120 audit: every element-registry walk that had to grow a truss arm
    or an exclusion, reached by a probe."""

    def test_database_history_beam_splits_three_ways(self):
        """/TH/TRUSS is its own group type: ``hm_read_thgrou.F:2466-2486``
        resolves it through ``MAP_TABLES%ITRUSSM`` over NUMELT, so a truss id
        in a /TH/BEAM group matches nothing."""
        _r, starter = _convert(_truss_deck(
            extra="*DATABASE_HISTORY_BEAM\n" + _row(10, 11) + "\n"))
        self.assertTrue(_headers(starter, "/TH/TRUSS/"))
        self.assertEqual(_headers(starter, "/TH/BEAM/"), [])
        body = _block(starter, _headers(starter, "/TH/TRUSS/")[0])
        ids = [int(ln[:10]) for ln in body if ln[:10].strip().isdigit()]
        self.assertEqual(ids, [10, 11])

    def test_a_set_beam_of_truss_parts_reaches_the_th_group(self):
        """C1's verdict in action: a truss is still spelled *SET_BEAM, and
        ``_elems_of_parts(state.beam_elems, ...)`` still finds it because the
        elements never left ``beam_elems``."""
        extra = ("*SET_BEAM\n" + _row(5) + "\n" + _row(10, 11) + "\n"
                 + "*DATABASE_HISTORY_BEAM_SET\n" + _row(5) + "\n")
        _r, starter = _convert(_truss_deck(extra=extra))
        self.assertTrue(_headers(starter, "/TH/TRUSS/"))

    def test_element_death_uses_the_grtrus_slot(self):
        """``hm_read_activ.F:96`` reads GR_TRUSS_SET; a truss id in the
        grbeam column resolves to nothing and the element never dies."""
        extra = ("*DEFINE_ELEMENT_DEATH_BEAM\n" + _row(10, 0.005) + "\n")
        _r, starter = _convert(_truss_deck(extra=extra))
        self.assertTrue(_headers(starter, "/GRTRUS/TRUS/"))
        # rows: [title, the eight group columns, Tstart/Tstop]
        row = _data_rows(starter, _headers(starter, "/ACTIV/")[0])[1]
        cells = [row[i:i + 10].strip() for i in range(0, 80, 10)]
        # sens grbric grquad grshel grtrus grbeam grspr grsh3n
        self.assertEqual(cells[0], "0")
        self.assertNotEqual(cells[4], "0")      # grtrus filled
        self.assertEqual(cells[5], "0")         # grbeam empty

    def test_a_cross_section_puts_trusses_in_the_grtrus_column(self):
        """The /SECT card's grtrus_ID column, which k2rad wrote 0 into."""
        # Card: NSID HSID BSID SSID TSID DSID (Vol I R17 p.16-49).
        extra = ("*SET_NODE_LIST\n" + _row(6) + "\n" + _row(1, 2, 3) + "\n"
                 + "*SET_BEAM\n" + _row(7) + "\n" + _row(10, 11) + "\n"
                 + "*DATABASE_CROSS_SECTION_SET\n"
                 + _row(6, 0, 7, 0, 0, 0) + "\n")
        _r, starter = _convert(_truss_deck(extra=extra))
        self.assertTrue(_headers(starter, "/GRTRUS/TRUS/"))
        self.assertEqual(_headers(starter, "/GRBEAM/BEAM/"), [])
        rows = _data_rows(starter, _headers(starter, "/SECT/")[0])
        # rows: [title, node/frame card, file_name, the group columns]
        cells = [rows[3][i:i + 10].strip() for i in range(0, 70, 10)]
        # grbric <blank> grshel grtrus grbeam grsprg grtria
        self.assertNotEqual(cells[3], "0")      # grtrus filled
        self.assertEqual(cells[4], "0")         # grbeam empty

    def test_preload_axial_takes_a_grtrus_group(self):
        """``hm_read_preload_axial.F90:284-291`` scans ngrtrus and sets
        itype = 4."""
        extra = ("*SET_BEAM\n" + _row(8) + "\n" + _row(10, 11) + "\n"
                 + "*DEFINE_CURVE\n" + _row(4) + "\n"
                 + _row16(0.0, 0.0) + "\n" + _row16(0.01, 1.0) + "\n"
                 + "*INITIAL_AXIAL_FORCE_BEAM\n" + _row(8, 4, 1000.0) + "\n")
        _r, starter = _convert(_truss_deck(extra=extra))
        self.assertTrue(_headers(starter, "/GRTRUS/TRUS/"))
        self.assertTrue(_headers(starter, "/PRELOAD/AXIAL/"))
        self.assertEqual(_headers(starter, "/GRBEAM/BEAM/"), [])

    def test_the_free_node_sweeper_ignores_a_truss_n3(self):
        """B2 of the audit. A deck-stated N3 on a truss is a node the element
        does not stiffen; counting it as attached would switch the implicit
        singularity guard OFF for it. Two corpus decks state a real N3 on a
        truss (node 45012), and both are EXPLICIT, so this is closed on
        principle and probed synthetically — as the SPH arm was."""
        elems = ("*ELEMENT_BEAM\n"
                 + f"{10:>8}{1:>8}{1:>8}{2:>8}{4:>8}" + "\n"
                 + f"{11:>8}{1:>8}{2:>8}{3:>8}{4:>8}" + "\n")
        implicit = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.1) + "\n")

        def _free_nodes(starter):
            for h in _headers(starter, "/GRNOD/NODE/"):
                rows = _data_rows(starter, h)
                if rows and rows[0].strip() == "free_reference_nodes":
                    return {int(v) for ln in rows[1:]
                            for v in ln.split() if v.isdigit()}
            return set()

        # Node 4 is named as N3 by the two trusses and by nothing else, so it
        # carries no stiffness and IS a free reference node.
        _r, starter = _convert(_truss_deck(elems=elems, extra=implicit))
        self.assertEqual(_free_nodes(starter), {4})
        # CONTROL — the same deck on an ELFORM=2 section: the /BEAM node_ID3
        # column really does hold node 4, the beam arm counts it as attached,
        # and no free-node group is emitted at all. That difference is what
        # proves the probe reaches the branch under test.
        _r2, starter2 = _convert(_truss_deck(elform=2, elems=elems,
                                             extra=implicit))
        self.assertEqual(_free_nodes(starter2), set())

    def test_a_muscle_part_is_not_claimed_by_the_truss_path(self):
        """*MAT_MUSCLE parts are ELFORM=3 by convention and already become a
        /PROP/TYPE46 /SPRING; both writers emit /PART/<pid>, and two of them
        is starter ERROR 79."""
        mat = ("*MAT_MUSCLE\n"
               + _row(1, "1.0E-09", 0, 1.0, 1.0, 1.0, 0.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n")
        _r, starter = _convert(_truss_deck(mat=mat))
        self.assertEqual(_headers(starter, "/TRUSS/"), [])
        self.assertEqual(_headers(starter, "/PROP/TYPE2/"), [])
        self.assertEqual(len(_headers(starter, "/PART/1")), 1)

    def test_an_integration_rule_on_a_truss_section_is_refused(self):
        """C20. ``hm_read_prop02.F`` has no integration column at all; the
        section keeps its card-2 AREA, which is the only cell /PROP/TYPE2
        reads, so the refusal loses nothing."""
        deck = ("*KEYWORD\n" + _BAR_NODES
                + "*PART\nbar\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_BEAM\n" + _row(1, 3, 1.0, -7.0, 0) + "\n"
                + _row(25.0, 0.0, 0.0) + "\n"
                + "*INTEGRATION_BEAM\n" + _row(7, 0, 2) + "\n"
                + _row(0.5, 0.5, 0.5) + "\n" + _row(-0.5, -0.5, 0.5) + "\n"
                + "*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
                + "*ELEMENT_BEAM\n" + f"{10:>8}{1:>8}{1:>8}{2:>8}" + "\n"
                + "*END\n")
        res, starter = _convert(deck)
        self.assertTrue(any("does not integrate a cross-section" in w
                            for w in res.warnings), res.warnings)
        self.assertEqual(_fields(_data_rows(starter, "/PROP/TYPE2/1")[1]),
                         ["25", "0"])

    def test_a_composite_layup_still_refuses_a_truss_part(self):
        """B10/B11: ``beam_pids = {e.pid for e in state.beam_elems}`` still
        holds a truss part, so the composite/fabric refusal is unchanged."""
        from k2rad.writer.common import _truss_pids
        st = _dispatch(_truss_deck())
        self.assertEqual(_truss_pids(st), {1})
        self.assertEqual({e.pid for e in st.beam_elems}, {1})

    def test_a_truss_section_stays_in_sec_beams(self):
        """B9: five mixed-family SECID tests and ``next_prop_id`` all read
        ``set(state.sec_beams)``. Keeping the truss section there is what
        makes them correct with zero edits."""
        st = _dispatch(_truss_deck())
        self.assertIn(1, st.sec_beams)
        self.assertEqual(st.sec_beams[1].elform, 3)


class TrussAnalytic(unittest.TestCase):
    """The physics the two cards have to reproduce, hand-computed.

    Cross-checked on the solver: ``rod.k`` (40 x 12.7 mm bars, A = 645 mm2,
    E = 206800 MPa, rho = 7.89e-9 t/mm3, 500 N step) converted by this branch
    ran 0 ERROR / 0 WARNING in the starter and NORMAL TERMINATION / 415 cycles
    in the engine, with dt = 2.233E-06 s against the closed form
    L/c x 0.9 = 2.232593e-6, TOTAL MASS 0.2585E-02 against rho.A.L_tot =
    2.585237e-3, and node-2 DX = 3.59858e-3 mm at t = 1.875e-4 against
    LS-DYNA's own nodout 3.61857e-3 (-0.55%).
    """

    def test_the_area_reaches_the_property_verbatim(self):
        """``tmat3.F:47-50`` KX = YM*AREA/AL: the axial stiffness is EA/L and
        AREA is the only geometric input the property carries. A = 645 on a
        12.7 mm bar of E = 206800 is EA/L = 1.050283e7 N/mm."""
        _r, starter = _convert(_truss_deck(area=645.0))
        self.assertEqual(_fields(_data_rows(starter, "/PROP/TYPE2/1")[1])[0],
                         "645")
        e_a_over_l = 206800.0 * 645.0 / 12.7
        self.assertAlmostEqual(e_a_over_l, 1.0502834645669293e7, places=1)

    def test_the_wave_speed_time_step_is_the_bar_formula(self):
        """``dt1lawt.F:55-60`` SSP = SQRT(E/RHO0), DTX = DELTAX/SSP — nothing
        else from the material reaches the truss."""
        c = (206800.0 / 7.89e-9) ** 0.5
        self.assertAlmostEqual(c, 5119608.667, places=2)
        self.assertAlmostEqual(0.9 * 12.7 / c, 2.2325925e-6, places=12)
        # ... which is what the starter echoed at cycle 0 on the real deck
        # (0.2233E-05, ELEMENT type TRUSS).
        self.assertEqual(f"{0.9 * 12.7 / c:.4E}", "2.2326E-06")


# ─────────────────────────────────────────────────────────────────────────────
# B2 — RO <= 0: the density floor (starter ERROR 683)
# ─────────────────────────────────────────────────────────────────────────────

def _rho_deck(*, ro: str = "0.0", implicit: bool = True, mat: str = "",
              extra: str = "") -> str:
    """A one-brick deck whose *MAT_ELASTIC states RO as given."""
    mat = mat or ("*MAT_ELASTIC\n" + _row(1, ro, 210000.0, 0.3) + "\n")
    ctrl = ("*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.1) + "\n"
            if implicit else "")
    return ("*KEYWORD\n" + _BRICK
            + "*PART\nbrick\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + mat + ctrl + extra
            + "*CONTROL_TERMINATION\n" + _row(0.01) + "\n*END\n")


class ZeroDensityFloor(unittest.TestCase):
    """``hm_read_mat.F90:1575-1583`` refuses ``rho <= 0`` with ERROR 683 for
    every law but 0/20/51/108/151/999. Eight R14 decks state ``RO = 0.0``
    literally and ran NORMAL TERMINATION in LS-DYNA.

    MEASURED on the solver (starter, nt=6), master -> this branch: all eight
    go from ``ERROR 683`` to **0 ERROR** — 3.1_Elastic_Beams_etc,
    3.3_Composite_Analysis, 3.4_Connectors_CNRB_Interpolation,
    3.5_Linear_Elastic_QS_Plate_{Hex,Shell,Tet}, ex_20_thin_shell_elform_16
    (whose second material, a *MAT_ELASTIC_PLASTIC_THERMAL, also carried
    ERROR 179 because the LAW106 resolver refused it for the same zero) and
    6.2.PSD_Beam_Example_LSTC.
    """

    def test_the_value_is_pinned(self):
        """1e-24 is DERIVED from LS-DYNA's own substitution, not chosen: its
        d3hsp reports 'total mass of part = 0.20483830E-19' for the
        20483.83 mm3 part of 3.1_Elastic_Beams_etc."""
        from k2rad.writer.materials import _ZERO_DENSITY_FLOOR
        self.assertEqual(_ZERO_DENSITY_FLOOR, 1.0e-24)
        self.assertAlmostEqual(2.0483830e-20 / 20483.83, 1.0e-24, places=30)
        self.assertAlmostEqual(2.0324782e-19 / 203247.82, 1.0e-24, places=30)
        self.assertAlmostEqual(4.0967660e-20 / (127 * 6.35 * 50.8),
                               1.0e-24, places=30)

    def test_the_exempt_law_set_is_the_starter_gate(self):
        from k2rad.writer.materials import _RHO_EXEMPT_LAWS
        self.assertEqual(set(_RHO_EXEMPT_LAWS), {0, 20, 51, 108, 151, 999})

    def test_an_implicit_ro_zero_deck_gets_the_floor(self):
        res, starter = _convert(_rho_deck())
        rows = _data_rows(starter, "/MAT/ELAST/1")
        self.assertEqual(_fields(rows[1])[0], "1.000000E-24")
        hit = [w for w in res.warnings if w.startswith("DENSITY:")]
        self.assertEqual(len(hit), 1, res.warnings)
        # the MID, the value the SOURCE states, and the law it landed on
        self.assertIn("MID 1 (RO = 0 -> /MAT/LAW1)", hit[0])
        self.assertIn("SUBSTITUTED rho = 1e-24", hit[0])
        self.assertIn("0.20483830E-19", hit[0])          # the provenance
        self.assertIn("ERROR 683", hit[0])               # the refusal
        self.assertIn("STATIC answer is unchanged", hit[0])
        # ... and it is MEASURED, not asserted from the algebra alone
        self.assertIn("-4.4872740000E-01", hit[0])
        self.assertIn("MASS DIAGNOSTICS ARE MEANINGLESS", hit[0])
        self.assertIn("--no-zero-density-floor", hit[0])

    def test_a_negative_density_is_quoted_as_stated(self):
        """The message names the value the SOURCE states, not just '<= 0': a
        negative RO is a different deck defect from a zero one and the reader
        has to see which they wrote."""
        res, _s = _convert(_rho_deck(ro="-1.0"))
        hit = [w for w in res.warnings if w.startswith("DENSITY:")]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("MID 1 (RO = -1 -> /MAT/LAW1)", hit[0])

    def test_an_explicit_deck_gets_the_harder_second_warning(self):
        """The substitution is applied to EVERY deck — restricting it to
        implicit ones would leave an explicit RO=0 deck failing at ERROR 683
        with no explanation — but the explicit case is told what it costs."""
        res, starter = _convert(_rho_deck(implicit=False))
        self.assertEqual(_fields(_data_rows(starter, "/MAT/ELAST/1")[1])[0],
                         "1.000000E-24")
        hit = [w for w in res.warnings if "this deck is EXPLICIT" in w]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("time step", hit[0])
        self.assertIn("never reach the termination time", hit[0])

    def test_an_implicit_deck_gets_only_the_first(self):
        res, _s = _convert(_rho_deck())
        self.assertEqual([w for w in res.warnings
                          if "this deck is EXPLICIT" in w], [])

    def test_the_opt_out_restores_todays_behaviour(self):
        res, starter = _convert(_rho_deck(), zero_density_floor=False)
        self.assertEqual(_fields(_data_rows(starter, "/MAT/ELAST/1")[1])[0],
                         "0")
        self.assertEqual([w for w in res.warnings
                          if w.startswith("DENSITY:")], [])

    def test_a_positive_density_is_untouched(self):
        res, starter = _convert(_rho_deck(ro="7.85E-09"))
        self.assertEqual(_fields(_data_rows(starter, "/MAT/ELAST/1")[1])[0],
                         "7.850000E-09")
        self.assertEqual([w for w in res.warnings
                          if w.startswith("DENSITY:")], [])

    def test_an_exempt_law_keeps_its_zero(self):
        """``ale_wavehitcol.k``'s ``*MAT_VACUUM`` -> ``/MAT/VOID`` (LAW0)
        states RO = 0 and that IS the card's meaning: the starter exempts
        LAW0, so flooring it would rewrite the deck rather than rescue it."""
        deck = ("*KEYWORD\n" + _BRICK
                + "*PART\nvac\n" + _row(1, 1, 1) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + "*MAT_VACUUM\n" + _row(1, 0.0) + "\n"
                + "*END\n")
        res, starter = _convert(deck)
        self.assertEqual(_fields(_data_rows(starter, "/MAT/VOID/1")[1])[0],
                         "0")
        self.assertEqual([w for w in res.warnings
                          if w.startswith("DENSITY:")], [])

    def test_the_record_scan_is_discovered_not_enumerated(self):
        """The scan walks every ``mat_*`` field of ConversionState that is a
        ``mid -> dataclass`` dict, so a material family added later is covered
        the day it is added — the inverse of the #120 stale-list trap."""
        import dataclasses
        from k2rad.state import ConversionState
        st = ConversionState()
        n = sum(1 for f in dataclasses.fields(st)
                if f.name.startswith("mat_")
                and isinstance(getattr(st, f.name), dict))
        # 79 dicts today; _material_registries lists 47 of them by hand.
        self.assertGreaterEqual(n, 79)

    def test_law106_is_rescued_rather_than_refused(self):
        """``ex_20_thin_shell_elform_16.k``: its *MAT_ELASTIC_PLASTIC_THERMAL
        states RO = 0, and the LAW106 resolver used to SKIP it for that —
        turning ERROR 683 into ERROR 179 on the same deck. LAW106's density is
        pure inertia (E, nu, alpha and the yield all come from the temperature
        table), so the floor rescues it without touching its constitutive
        answer."""
        mat = ("*MAT_ELASTIC_PLASTIC_THERMAL\n"
               + _row(1, 0.0) + "\n"
               + _row(20.0, 500.0, 0, 0, 0, 0, 0, 0) + "\n"
               + _row(210000.0, 100000.0, 0, 0, 0, 0, 0, 0) + "\n"
               + _row(0.3, 0.3, 0, 0, 0, 0, 0, 0) + "\n"
               + _row(1.2e-5, 1.2e-5, 0, 0, 0, 0, 0, 0) + "\n"
               + _row(250.0, 150.0, 0, 0, 0, 0, 0, 0) + "\n"
               + _row(1000.0, 800.0, 0, 0, 0, 0, 0, 0) + "\n")
        res, starter = _convert(_rho_deck(mat=mat))
        self.assertTrue(_headers(starter, "/MAT/LAW106/"), res.warnings)
        self.assertEqual(_fields(_data_rows(starter, "/MAT/LAW106/1")[1])[0],
                         "1.000000E-24")
        # ... and with the floor OFF the old refusal comes back, naming the
        # flag, so the two halves cannot drift.
        res2, starter2 = _convert(_rho_deck(mat=mat),
                                  zero_density_floor=False)
        self.assertEqual(_headers(starter2, "/MAT/LAW106/"), [])
        self.assertTrue(any("--no-zero-density-floor is set" in w
                            for w in res2.warnings), res2.warnings)

    def test_law3_is_refused_either_way(self):
        """The floor CANNOT rescue a /MAT/LAW3: that law derives its whole
        elastic pair from the density (K0 = rho0*C^2 out of the *EOS_*, then
        nu and E out of K0 and G), so a floored density would turn a refused
        deck into a silently wrong one."""
        mat = ("*MAT_ELASTIC_PLASTIC_HYDRO\n"
               + _row(1, 0.0, 80000.0, 250.0, 100.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
               + "*EOS_GRUNEISEN\n"
               + _row(1, 5000.0, 1.5, 0.0, 0.0, 2.0, 0.0, 0.0) + "\n"
               + _row(0.0, 1.0) + "\n")
        res, starter = _convert(_rho_deck(mat=mat))
        self.assertEqual(_headers(starter, "/MAT/LAW3/"), [])
        self.assertTrue(any("does NOT apply here" in w for w in res.warnings),
                        res.warnings)

    def test_a_floored_density_is_not_a_usable_one_for_sph(self):
        """The floor's job is the /MAT card's ERROR-683 gate, nothing else.
        writer/sph.py fabricates a particle mass when the material states no
        density and says so LOUDLY ("MASS INVENTED ... a bare unit mass");
        computing rho x V from the substituted 1e-24 would replace that loud
        invention with a silent 1e-21 that looks measured, so
        ``state.zero_density_floored`` keeps the two apart."""
        st = _dispatch(_rho_deck())
        self.assertEqual(st.zero_density_floored, set())   # a parse-only state
        res, _s = _convert(_rho_deck())
        del res
        from k2rad.writer.sph import _mat_density
        from k2rad.state import ConversionState, MatElastic
        probe = ConversionState()
        probe.mat_elastic[1] = MatElastic(1, "", 1.0e-24, 210000.0, 0.3)
        self.assertEqual(_mat_density(probe, 1), 1.0e-24)
        probe.zero_density_floored.add(1)
        self.assertEqual(_mat_density(probe, 1), 0.0)

    def test_the_modal_shift_bound_is_below_double_precision(self):
        """The one deck class where the density is NOT inert.
        ``6.2.PSD_Beam_Example_LSTC``: a 127 mm cantilever, 6.35 x 50.8 mm
        section, plus *ELEMENT_MASS 2.2684179e-4 at the tip. Its LS-DYNA
        eigout gives f1 = 110.4521 Hz with MODAL EFFECTIVE MASS 2.268420E-04
        — exactly the lumped tip mass, i.e. the beam contributes none.

        Rayleigh: m_eff = M + (33/140) m_beam, so
        df/f ~ -0.5 (33/140) rho V / M. At rho = 1e-24 that is 2.1e-17,
        below the double-precision epsilon 2.22e-16 — literally
        unrepresentable. At the 1e-9 a "small positive floor" would have
        picked it is -2.1 %, which is what makes the DERIVED value
        load-bearing rather than cosmetic."""
        vol = 127.0 * 6.35 * 50.8
        m_tip = 2.2684179e-4
        def shift(rho):
            return -0.5 * (33.0 / 140.0) * rho * vol / m_tip
        self.assertAlmostEqual(vol, 40967.66, places=2)
        self.assertLess(abs(shift(1e-24)), 2.22e-16)
        self.assertAlmostEqual(shift(1e-9) * 100.0, -2.1285, places=4)
        # The analytic SDOF the reference itself matches to -0.09 %:
        i = 50.8 * 6.35 ** 3 / 12.0
        k = 3.0 * 68947.5729 * i / 127.0 ** 3
        f = (k / m_tip) ** 0.5 / (2.0 * 3.141592653589793)
        self.assertAlmostEqual(i, 1083.936, places=2)
        self.assertAlmostEqual(k, 109.45427, places=4)
        self.assertAlmostEqual(f, 110.556, places=2)
        self.assertLess(abs(f - 110.4521) / 110.4521, 0.001)


# ─────────────────────────────────────────────────────────────────────────────
# B3 — *CONTACT_FORCE_TRANSDUCER -> a PARENTLESS /INTER/SUB (ERROR 580/581)
# ─────────────────────────────────────────────────────────────────────────────

#: Two shell parts, a real contact between them, and a transducer on part 2.
_FT_MESH = """*NODE
         1             0.0             0.0             0.0
         2             1.0             0.0             0.0
         3             1.0             1.0             0.0
         4             0.0             1.0             0.0
         5             0.0             0.0             2.0
         6             1.0             0.0             2.0
         7             1.0             1.0             2.0
         8             0.0             1.0             2.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       5       6       7       8
"""


def _ft_deck(*, surfa: int = 2, surfb: int = 1, satyp: int = 3,
             sbtyp: int = 3, contact: bool = True) -> str:
    ctc = ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE\n"
           + _row(1, 2, 3, 3) + "\n" + _row(0.2, 0.2) + "\n") if contact else ""
    return ("*KEYWORD\n" + _FT_MESH
            + "*PART\na\n" + _row(1, 1, 1) + "\n"
            + "*PART\nb\n" + _row(2, 1, 1) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2, "", 3) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + "*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
            + ctc
            + "*CONTACT_FORCE_TRANSDUCER_PENALTY\n"
            + _row(surfa, surfb, satyp, sbtyp) + "\n"
            + "*CONTROL_TERMINATION\n" + _row(0.01) + "\n*END\n")


def _sub_cells(starter: str, sub_id: int):
    """(inter_ID, Main_ID1, Second_ID, Main_ID2) of one /INTER/SUB block."""
    rows = _data_rows(starter, f"/INTER/SUB/{sub_id}")
    assert rows is not None, f"no /INTER/SUB/{sub_id}"
    row = rows[1]                       # rows[0] is the title card
    return tuple(int(row[k:k + 10]) for k in range(0, 40, 10))


def _surf_id_by_title(starter: str, title: str) -> int:
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("/SURF/") and lines[i + 1].strip() == title:
            return int(ln.rsplit("/", 1)[1])
    raise AssertionError(f"no /SURF titled {title!r} in\n" + starter)


class ForceTransducerInterZero(unittest.TestCase):
    """``/INTER/SUB`` is written PARENTLESS.

    ``hm_read_intsub.F:225-250``: ``IF(IDINT /= 0)`` resolves a parent, ``ELSE
    INTSUB_TYP(I) = 100`` — and :448's own comment on that branch is
    ``Interf 0 : adding all contacts``. Measured on the corpus: the parented
    form gave ``plate.typ13`` 4 x ERROR 580 + ERROR 581 and ``pipe.k`` many x
    ERROR 581; with ``inter_ID = 0`` both start at 0 ERROR and run to NORMAL
    TERMINATION (251 and 6147 cycles). On a purpose-built shell-impact probe
    the accumulated normal impulse is -0.01453375 at all 1000 samples for the
    inter-0 card, for a legally parented sub-interface, and for the parent
    interface's own channel — bit-identical to the printed precision, and
    93.2 % of the elastic bound 2*m*v0 = 1.560e-2.
    """

    def test_the_card_is_four_cells_and_names_no_interface(self):
        """``radioss2021/INTER/inter_sub.cfg`` (newest FORMAT <= 2022):
        ``CARD("%10d%10d%10d%10d", InterfaceId, mainentityids,
        secondaryentityids, Main_ID2)``. k2rad used to write three."""
        _r, starter = _convert(_ft_deck())
        sub = _headers(starter, "/INTER/SUB/")
        self.assertEqual(len(sub), 1, starter)
        sid = int(sub[0].rsplit("/", 1)[1])
        rows = _data_rows(starter, sub[0])
        self.assertEqual(len(rows[1].rstrip()), 40)
        self.assertIn("Main_ID2", _block(starter, sub[0])[1])
        inter_id, main1, second, main2 = _sub_cells(starter, sid)
        self.assertEqual(inter_id, 0)
        self.assertEqual(second, 0)
        self.assertTrue(main2)
        # Main_ID2 is the SURFA surface; Main_ID1 the stated SURFB one.
        title = _block(starter, sub[0])[0]
        self.assertEqual(main2, _surf_id_by_title(starter, f"{title}_main"))
        self.assertEqual(main1, _surf_id_by_title(starter, f"{title}_main2"))

    def test_no_interface_id_ever_reaches_cell_one(self):
        """The mutation this replaces: putting the parent id back in cell 1
        is what produced ERROR 580/581. Asserted against the ids that really
        exist, so a re-introduced parent cannot pass by being 0 by luck."""
        _r, starter = _convert(_ft_deck())
        emitted = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                   if ln.startswith(("/INTER/TYPE7/", "/INTER/TYPE25/"))}
        self.assertTrue(emitted, starter)
        sid = int(_headers(starter, "/INTER/SUB/")[0].rsplit("/", 1)[1])
        self.assertNotIn(_sub_cells(starter, sid)[0], emitted)

    def test_no_secondary_node_group_is_emitted_any_more(self):
        """A behaviour change worth pinning: ``Second_ID`` is not decoded on
        the inter-0 branch (``hm_read_intsub.F:453-476`` reads Main_ID2 and
        Main_ID1 and nothing else), so the ``<title>_secnd`` /GRNOD k2rad used
        to build would be dead weight the starter never reads."""
        _r, starter = _convert(_ft_deck())
        self.assertNotIn("_secnd", starter)

    def test_surfb_zero_leaves_main_id1_at_zero(self):
        """SURFB = 0 (and SURFBTYP = 5) both mean 'everything', which is
        exactly TYPSUB = 2's own scope — the total contact force on SURFA from
        every interface (``i7for3.F:1583``). Emitting an all-parts surface
        would say the same thing more expensively."""
        for kw in ({"surfb": 0, "sbtyp": 0}, {"surfb": 1, "sbtyp": 5}):
            with self.subTest(**kw):
                _r, starter = _convert(_ft_deck(**kw))
                sid = int(_headers(starter, "/INTER/SUB/")[0]
                          .rsplit("/", 1)[1])
                self.assertEqual(_sub_cells(starter, sid)[1], 0)

    def test_a_transducer_survives_a_deck_with_no_contact_at_all(self):
        """The parented form REFUSED such a deck ('no existing /INTER to act
        as parent -> skipped'), which is backwards: a transducer measures
        whatever contact there is, and needs none of its own."""
        res, starter = _convert(_ft_deck(contact=False))
        sub = _headers(starter, "/INTER/SUB/")
        self.assertEqual(len(sub), 1, starter)
        self.assertEqual(_sub_cells(starter,
                                    int(sub[0].rsplit("/", 1)[1]))[0], 0)
        self.assertFalse([w for w in res.warnings
                          if "no existing /INTER" in w], res.warnings)

    def test_the_th_inter_list_still_carries_the_sub_id(self):
        """``hm_read_intsub.F:509-524`` sets ``NOM_OPT(5) = 1`` only for a sub
        id it finds in a /TH/INTER list; an unlisted sub-interface is read and
        then silently dropped (OUTPUT TO TH = 0)."""
        _r, starter = _convert(_ft_deck())
        sid = int(_headers(starter, "/INTER/SUB/")[0].rsplit("/", 1)[1])
        th = _headers(starter, "/TH/INTER/")
        self.assertEqual(len(th), 1, starter)
        listed = {int(t) for ln in _data_rows(starter, th[0])
                  for t in ln.split() if t.lstrip("-").isdigit()}
        self.assertIn(sid, listed)

    def test_the_semantics_warning_is_emitted_once(self):
        deck = _ft_deck() + ""
        deck = deck.replace(
            "*CONTROL_TERMINATION",
            "*CONTACT_FORCE_TRANSDUCER_PENALTY\n"
            + _row(1, 2, 3, 3) + "\n*CONTROL_TERMINATION")
        res, starter = _convert(deck)
        self.assertEqual(len(_headers(starter, "/INTER/SUB/")), 2, starter)
        hit = [w for w in res.warnings if w.startswith("/INTER/SUB inter_ID")]
        self.assertEqual(len(hit), 1, res.warnings)
        for needle in ("Interf 0 : adding all contacts", "lecint.F:531-550",
                       "TYPSUB = 2", "i7for3.F:1583", "ERROR 580",
                       "ERROR 581", "-0.01453375"):
            self.assertIn(needle, hit[0])

    def test_the_impulse_caveat_survives_verbatim(self):
        """It is correct and still applies: the T01 channel is an accumulated
        impulse whatever form the sub-interface takes."""
        res, _s = _convert(_ft_deck())
        hits = [w for w in res.warnings if "Force-transducer read-out" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("NO constant correction factor", hits[0])


# ─────────────────────────────────────────────────────────────────────────────
# B4 — *DEFINE_CURVE with a reversed abscissa (starter ERROR 156)
# ─────────────────────────────────────────────────────────────────────────────

def _curve_deck(points, lcid: int = 50) -> str:
    """A one-brick deck carrying one *DEFINE_CURVE with *points*."""
    rows = "".join(_row16(f"{x:.10G}", f"{y:.10G}") + "\n" for x, y in points)
    return ("*KEYWORD\n" + _BRICK
            + "*PART\nbrick\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
            + "*MAT_ELASTIC\n" + _row(1, "7.85E-09", 210000.0, 0.3) + "\n"
            + "*DEFINE_CURVE\n" + _row(lcid, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
            + rows
            + "*CONTROL_TERMINATION\n" + _row(0.01) + "\n*END\n")


def _funct_points(starter: str, lcid: int):
    rows = _data_rows(starter, f"/FUNCT/{lcid}")
    assert rows is not None, starter
    return [(float(r[:20]), float(r[20:40])) for r in rows[1:]]


#: The corpus carrier, verbatim from
#: ``F:/dynaexamples_r14_ton-mm-s/introduction/examples-manual/material/
#: spring/mat_spring.belted-dummy.k`` around its one reversal: point 25 is
#: (0.1195, -4910) and point 26 is (0.1125, -9810).
_BELTED = [(0.115, -9810.0), (0.1195, -4910.0), (0.1125, -9810.0),
           (0.13, -2450.0)]


class CurveAbscissaReversal(unittest.TestCase):
    """``hm_read_funct.F:143`` — ``IF (PLD(NPC(L+1)) <= PLD(NPC(L+1)-2))``,
    ``MSGID = 156``, MSGERROR: Radioss refuses a non-increasing abscissa
    outright. LS-DYNA warns (``Warning 20446``) and evaluates the curve with a
    forward-walking segment search that never enters the reversed interval.

    MEASURED, starter (nt=6), master 92460b7 -> this branch, on the corpus
    carrier: 1 x ERROR 156 -> 0 ERROR.
    """

    def test_the_reversed_point_is_re_anchored_not_nudged(self):
        """The repair is the value LS-DYNA JUMPS TO, from the segment that
        LEAVES the out-of-order point: lerp((0.1125,-9810) -> (0.13,-2450))
        at 0.1195 = -9810 + 0.4*7360 = -6866 exactly."""
        _r, starter = _convert(_curve_deck(_BELTED))
        pts = _funct_points(starter, 50)
        self.assertEqual(len(pts), len(_BELTED))
        self.assertAlmostEqual(pts[2][1], -6866.0, places=6)
        self.assertGreater(pts[2][0], pts[1][0])
        self.assertLess(pts[2][0], pts[3][0])
        # ... and every abscissa is strictly increasing AS PRINTED.
        xs = [x for x, _y in pts]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), len(xs))

    def test_the_repair_reproduces_the_ls_dyna_reference(self):
        """Hand-computed against ``mat_spring.belted-dummy.nodout``, node 1763
        x-acceleration, the first sample past the reversal: 5.15057E+03 at
        t = 0.119275 JUMPS to 6.85894E+03 at t = 0.119512.

        The three candidate repairs, evaluated on the curve each of them
        emits and negated by the deck's own ``SF = -1``:

          re-anchor (this fix)  6860.96   +0.03 %
          plain nudge           9801.60  +42.90 %
          re-sort by abscissa   4907.19  -28.46 %

        A 43 % error in a prescribed sled acceleration is why the
        smallest-looking repair is the wrong one."""
        t, ref = 0.119512, 6858.94

        def lerp(x1, y1, x2, y2, x):
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        _r, starter = _convert(_curve_deck(_BELTED))
        (xa, ya), (xb, yb) = _funct_points(starter, 50)[2:4]
        got = -lerp(xa, ya, xb, yb, t)
        self.assertAlmostEqual(got, 6860.9573, places=3)
        self.assertLess(abs(got - ref) / ref, 0.0005)
        # the two rejected candidates, on THEIR curves
        self.assertAlmostEqual(-lerp(xa, -9810.0, 0.13, -2450.0, t),
                               9801.5956, places=3)
        self.assertAlmostEqual(-lerp(0.1195, -4910.0, 0.13, -2450.0, t),
                               4907.1886, places=3)

    def test_the_warning_names_the_point_and_both_sides(self):
        res, _s = _convert(_curve_deck(_BELTED))
        hit = [w for w in res.warnings if w.startswith("*DEFINE_CURVE 50")]
        self.assertEqual(len(hit), 1, res.warnings)
        for needle in ("reverses direction at point 3", "Warning 20446",
                       "hm_read_funct.F:143", "ERROR 156", "-6866",
                       "DATTYP = 0", "p.17-106"):
            self.assertIn(needle, hit[0])

    def test_a_trailing_reversal_is_dropped_by_name(self):
        """No later point lies beyond the last accepted abscissa, so there is
        no segment to anchor onto — and LS-DYNA cannot evaluate it either."""
        res, starter = _convert(_curve_deck(
            [(0.0, 0.0), (1.0, 10.0), (0.5, 99.0)]))
        pts = _funct_points(starter, 50)
        self.assertEqual(pts, [(0.0, 0.0), (1.0, 10.0)])
        hit = [w for w in res.warnings if w.startswith("*DEFINE_CURVE 50")]
        self.assertEqual(len(hit), 1, res.warnings)
        self.assertIn("DROPPED", hit[0])
        self.assertIn("point 3", hit[0])

    def test_two_consecutive_reversals(self):
        """Each is repaired against the first LATER point that lies beyond the
        last ACCEPTED abscissa, not against its immediate neighbour — a chain
        of reversals must not anchor onto another reversed point."""
        res, starter = _convert(_curve_deck(
            [(0.0, 0.0), (1.0, 10.0), (0.4, 4.0), (0.6, 6.0), (2.0, 20.0)]))
        pts = _funct_points(starter, 50)
        xs = [x for x, _y in pts]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), len(xs))
        # point 3 (0.4, 4.0): the next point past x = 1.0 is (2.0, 20.0), so
        # the anchor is lerp((0.4,4) -> (2,20)) at 1.0 = 4 + 16*0.6/1.6 = 10.
        self.assertAlmostEqual(pts[2][1], 10.0, places=6)
        # point 4 (0.6, 6.0): same anchor point, lerp((0.6,6) -> (2,20)) at
        # 1.0 = 6 + 14*0.4/1.4 = 10.
        self.assertAlmostEqual(pts[3][1], 10.0, places=6)
        self.assertEqual(len([w for w in res.warnings
                              if w.startswith("*DEFINE_CURVE 50")]), 2)

    def test_a_tie_keeps_its_ordinate_and_is_now_named(self):
        """The original #113 REPAIR must not move: two points at one abscissa
        are not a reversal — the curve was never ambiguous about its value
        there — so the ordinate is kept and the abscissa stepped.

        What DID move is the silence. Moving the #113 guard onto the main
        /FUNCT emitter put it in front of every *DEFINE_CURVE in every deck,
        and on a curve the DECK typed a duplicate abscissa is a STATEMENT: the
        common stepped shape (0,0),(1,0),(1,100),(2,100) means "jump at x = 1"
        and the repair turns it into a ramp across the nudge. Master emitted
        the duplicate and let the starter refuse it with ERROR 156, which at
        least said something, so the repair must not be the quieter of the two.
        The synthesized builders (which pass no `state`) stay silent — there
        the tie is their own rounding.
        """
        res, starter = _convert(_curve_deck(
            [(0.0, 0.0), (1.0, 10.0), (1.0, 20.0), (2.0, 30.0)]))
        pts = _funct_points(starter, 50)
        self.assertEqual([y for _x, y in pts], [0.0, 10.0, 20.0, 30.0])
        self.assertGreater(pts[2][0], pts[1][0])
        w = [x for x in res.warnings if x.startswith("*DEFINE_CURVE 50")]
        self.assertEqual(len(w), 1, res.warnings)
        for fact in ("two points share the abscissa x = 1",
                     "hm_read_funct.F:143", "ERROR 156",
                     "KEEPS", "meant as a STEP"):
            self.assertIn(fact, w[0])

    def test_a_well_formed_curve_is_untouched(self):
        pts_in = [(0.0, 0.0), (1.0, 10.0), (2.0, 5.0), (3.0, -7.5)]
        res, starter = _convert(_curve_deck(pts_in))
        self.assertEqual(_funct_points(starter, 50), pts_in)
        self.assertEqual([w for w in res.warnings
                          if w.startswith("*DEFINE_CURVE")], [])

    def test_the_guard_reaches_the_main_emitter_at_all(self):
        """The defect this closes: the #113 nudge lived on
        ``writer/loads.py::_emit_funct`` (connector-inline curves) and on
        ``handle_define_curve_smooth``'s builder, while
        ``materials._make_functions`` — the emitter EVERY *DEFINE_CURVE goes
        through — wrote ``curve.pts`` verbatim."""
        import inspect
        from k2rad.writer import materials as M
        src = inspect.getsource(M._make_functions)
        self.assertIn("_monotonic_abscissae", src)
        self.assertNotIn("for a, o in curve.pts:", src)


# -----------------------------------------------------------------------------
# Post-review: a /MAT/LAW106 SHELL cannot thermally expand at all
# -----------------------------------------------------------------------------

def _mat004_shell_deck(card: str = _MAT004_STEEL, *, mid: int = 1,
                       extra: str = "", mesh: str = _SHELLS) -> str:
    """The *MAT_004 deck of the corpus's SHELL carriers (tempcyl.vari, ex_20,
    main_steel_frame, 05_2): one part on the material, shell by default."""
    section = ("*SECTION_SHELL\n" + _row(1, 2) + "\n" + _row(1.0) + "\n"
               if mesh is _SHELLS else
               "*SECTION_SOLID\n" + _row(1, 1) + "\n")
    return ("*KEYWORD\n"
            "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
            + mesh
            + "*PART\np1\n" + _row(1, 1, mid) + "\n"
            + section + card + extra + "*END\n")


class Law106ShellRestatementTests(unittest.TestCase):
    """A /MAT/LAW106 SHELL does not thermally expand - it is restated.

    MECHANISM, from the engine source: ``cmain3.F:348`` runs ``THERMEXPC``
    AFTER ``MULAWC`` at ``:320``, and on an ordinary ``/PROP/SHELL``
    (``IGTYP = 1``, so ``IORTH_LAY = 0``) all THERMEXPC does is SUBTRACT the
    thermal stress from the stress the law just produced
    (``thermexpc.F:269-293``). ``sigeps106c.F90:297-298`` then rebuilds
    ``signxx``/``signyy`` from the TOTAL strain
    (``aii*(epsxx - eplaxx) + aij*(epsyy - eplayy)``) and never reads
    ``sigoxx``, so the subtraction is discarded on the next cycle.
    ``sigeps36c.F:276`` is ``SIGNXX = SIGOXX + A1*DEPSXX + A2*DEPSYY`` and
    reads it back.

    MEASURED on four coupons differing only in the element family and the law
    (10 mm edge, ``*BOUNDARY_TEMPERATURE_SET`` 20 -> 120 K, alpha 1.2e-5,
    NIP 3, closed form 1.2e-2 mm, all NORMAL TERMINATION): LAW106 SHELL
    ``0.0000000e+00``, the restatement ``1.2000000e-02``, a ``*MAT_024`` +
    ``*MAT_ADD_THERMAL_EXPANSION`` control ``1.2000000e-02``, LAW106 SOLID
    ``1.2000000e-02``. The restatement and the control agree on EVERY printed
    T01 digit (internal energy 6.219282e-02, external work 2.180456e-04, last
    time step 1.437983e-06); the kept-LAW106 shell reads -4.759515e-05.
    """

    def test_a_shell_only_mat004_is_restated_to_law36(self):
        res, starter = _convert(_mat004_shell_deck())
        self.assertNotIn("/MAT/LAW106/1", starter)
        self.assertIn("/MAT/LAW36/1", starter)
        # the expansion and its mandatory /HEAT/MAT partner SURVIVE the swap
        self.assertIn("/THERM_STRESS/MAT/1", starter)
        self.assertIn("/HEAT/MAT/1", starter)
        w = [x for x in res.warnings if "RESTATED as /MAT/LAW36" in x]
        self.assertEqual(len(w), 1, res.warnings)
        for fact in ("cmain3.F:348", "sigeps106c.F90:297-298",
                     "sigeps36c.F:276", "TOTAL strain",
                     "0.0000000e+00", "1.2000000e-02",
                     "--no-law106-shell-restate"):
            self.assertIn(fact, w[0])

    def test_a_solid_mat004_is_left_alone(self):
        """mmain.F90 applies the expansion to the strain increment BEFORE the
        law dispatch, so a LAW106 SOLID was measured exact (1.2000000e-02)."""
        _res, starter = _convert(_mat004_shell_deck(mesh=_BRICK))
        self.assertIn("/MAT/LAW106/1", starter)
        self.assertNotIn("/MAT/LAW36/1", starter)

    def test_the_opt_out_keeps_law106_and_says_what_it_costs(self):
        res, starter = _convert(_mat004_shell_deck(),
                                law106_shell_restate=False)
        self.assertIn("/MAT/LAW106/1", starter)
        self.assertNotIn("/MAT/LAW36/1", starter)
        w = [x for x in res.warnings
             if "--no-law106-shell-restate was passed" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("NO THERMAL EXPANSION AT ALL", w[0])

    def test_a_mixed_material_keeps_law106_and_is_named(self):
        """Restating would take E(T) away from solids that expand correctly,
        so the law is left alone and BOTH part lists are named."""
        deck = ("*KEYWORD\n"
                "*CONTROL_TERMINATION\n" + _row(1.0) + "\n"
                + _BRICK
                + "*ELEMENT_SHELL\n"
                + "       9       2       1       2       3       4\n"
                + "*PART\nsolid\n" + _row(1, 1, 1) + "\n"
                + "*PART\nshell\n" + _row(2, 2, 1) + "\n"
                + "*SECTION_SOLID\n" + _row(1, 1) + "\n"
                + "*SECTION_SHELL\n" + _row(2, 2) + "\n" + _row(1.0) + "\n"
                + _MAT004_STEEL + "*END\n")
        res, starter = _convert(deck)
        self.assertIn("/MAT/LAW106/1", starter)
        w = [x for x in res.warnings if "shared between SHELL" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("SHELL part(s) [2]", w[0])
        self.assertIn("non-shell part(s) [1]", w[0])

    def test_no_expansion_coefficient_means_no_restatement(self):
        """With no /THERM_STRESS there is nothing to rescue and LAW36 would
        only throw E(T) away, so the law is kept - silently, by design."""
        card = _MAT004_STEEL.replace(
            _row("1.20000E-5", "1.20000E-5", "1.40000E-5", 0.0, 0.0, 0.0,
                 0.0, 0.0),
            _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        res, starter = _convert(_mat004_shell_deck(card))
        self.assertIn("/MAT/LAW106/1", starter)
        self.assertNotIn("/THERM_STRESS/MAT/1", starter)
        self.assertEqual(
            [x for x in res.warnings if "RESTATED as /MAT/LAW36" in x], [])

    def test_the_restated_yield_and_hardening_are_the_law106_cells(self):
        """The two-point curve is (sigma_y, sigma_y + B) at eps_p 0 and 1, so
        LAW36's plastic modulus IS the LAW106 B cell."""
        from k2rad.writer import build_starter
        state = _dispatch(_mat004_shell_deck())
        build_starter(state)
        self.assertIn(1, state.law106_shells_restated)
        rec = state.mat_plas_tab[1]
        pts = state.curves[rec.funct_id].pts
        self.assertEqual(len(pts), 2)
        self.assertAlmostEqual(pts[0][0], 0.0)
        self.assertAlmostEqual(pts[1][0], 1.0)
        self.assertGreater(pts[1][1] - pts[0][1], 0.0)
        self.assertAlmostEqual(pts[0][1], rec.sigy)

    def test_a_thermo_elastic_card_gets_the_far_yield_curve(self):
        """ex_20's shape: SIGY = 0 on every slot, so LAW106 wrote A = 1e20 and
        the restatement writes a flat curve at 1000 x E (never reached)."""
        card = _MAT004_STEEL.replace(
            _row(435.0, 100.0, 20.0, 1.0, 0.0, 0.0, 0.0, 0.0),
            _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        res, _starter = _convert(_mat004_shell_deck(card))
        w = [x for x in res.warnings if "RESTATED as /MAT/LAW36" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("flat far-yield curve", w[0])
        self.assertIn("1000 x E", w[0])


class MatCwmBetaTests(unittest.TestCase):
    """*MAT_CWM BETA is the ISOTROPIC fraction, so B = BETA*H(T_ref).

    Vol II R17 p.2-1838 Remark 2: ``sigma_Y = sigma_Y(T) + BETA*H(T)*eps_p``
    with a back stress ``kappa_dot = (1-BETA)*H(T)*eps_dot_p``; p.2-1836 calls
    BETA the "Fraction of isotropic hardening between 0 and 1" (EQ.0.0
    kinematic, EQ.1.0 isotropic). /MAT/LAW106 is purely isotropic, so writing
    H(T_ref) raw would make the card 1/BETA too stiff.
    """

    @staticmethod
    def _card(beta):
        return _MAT_CWM.replace(
            _row(2, "7.85000E-9", 101, 102, 103, 104, 105, 1.0),
            _row(2, "7.85000E-9", 101, 102, 103, 104, 105, beta))

    def _b_cell(self, beta) -> float:
        from k2rad.writer import build_starter
        state = _dispatch(_cwm_deck(self._card(beta)))
        build_starter(state)
        return state.mat_law106[2].b

    def test_beta_one_is_the_full_hardening_modulus(self):
        self.assertAlmostEqual(self._b_cell(1.0), 700.0, places=6)

    def test_beta_half_halves_the_isotropic_modulus(self):
        self.assertAlmostEqual(self._b_cell(0.5), 350.0, places=6)

    def test_beta_zero_leaves_no_isotropic_hardening(self):
        """LS-DYNA has NO isotropic hardening at BETA = 0, so B must be 0 -
        the case the old guard exempted from the warning entirely."""
        self.assertAlmostEqual(self._b_cell(0.0), 0.0, places=9)

    def test_every_beta_but_one_is_warned_by_name(self):
        for beta, extra in ((0.0, "NO isotropic hardening at all"),
                            (0.5, "Only BETA = 1 is lossless here")):
            res, _starter = _convert(_cwm_deck(self._card(beta)))
            w = " ".join(res.warnings)
            with self.subTest(beta=beta):
                self.assertIn("BETA*H(T)*eps_p", w)
                self.assertIn("p.2-1838 Remark 2", w)
                self.assertIn(extra, w)

    def test_beta_one_says_nothing_about_the_split(self):
        res, _starter = _convert(_cwm_deck())
        self.assertEqual(
            [x for x in res.warnings if "Fraction of isotropic" in x], [])


class MatCwmMissingPoissonTests(unittest.TestCase):
    """A missing LCPR writes nu = 0, which is a real constitutive change."""

    def test_an_unresolvable_lcpr_is_named(self):
        card = _MAT_CWM.replace(
            _row(2, "7.85000E-9", 101, 102, 103, 104, 105, 1.0),
            _row(2, "7.85000E-9", 101, 999, 103, 104, 105, 1.0))
        res, starter = _convert(_cwm_deck(card))
        self.assertIn("/MAT/LAW106/2", starter)
        w = [x for x in res.warnings if "LCPR = 999" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("E/(3(1-2nu))", w[0])

    def test_a_resolvable_lcpr_says_nothing(self):
        res, _starter = _convert(_cwm_deck())
        self.assertEqual(
            [x for x in res.warnings
             if "resolves to no usable" in x], [])


class ForceTransducerSegmentSetTests(unittest.TestCase):
    """``SURFATYP = 0`` is a ``*SET_SEGMENT`` id, not a ``*PART`` id.

    ``intro-by-j.-day/contact/force-transducer/transducer.k`` carries BOTH
    spellings and labels them itself: ``$ by part id`` (``SSTYP 3``, commented
    out) and ``$ by segment set`` (``SURFA = 10, SURFATYP = 0``, live, with
    ``*SET_SEGMENT 10``). Reading the set id as a part id skipped the whole
    transducer on a deck that had never failed. MEASURED after the fix: the
    deck emits ``/SURF/SEG`` + ``/INTER/SUB`` and the starter runs it at
    0 ERROR / 3 WARNING, NORMAL TERMINATION, 969 cycles — the same verdict and
    the same cycle count as master's parented form.
    """

    @staticmethod
    def _seg_deck(*, satyp: int = 0, sid: int = 10, define: bool = True) -> str:
        segset = ("*SET_SEGMENT\n" + _row(sid) + "\n"
                  + _row(1, 2, 3, 4) + "\n") if define else ""
        return _ft_deck(surfa=sid, satyp=satyp, surfb=0, sbtyp=0).replace(
            "*CONTROL_TERMINATION", segset + "*CONTROL_TERMINATION")

    def test_a_segment_set_becomes_a_surf_seg(self):
        res, starter = _convert(self._seg_deck())
        segs = _headers(starter, "/SURF/SEG/")
        self.assertEqual(len(segs), 1, starter)
        sub = _headers(starter, "/INTER/SUB/")
        self.assertEqual(len(sub), 1, starter)
        cells = _sub_cells(starter, int(sub[0].rsplit("/", 1)[1]))
        self.assertEqual(cells[0], 0)               # parentless
        self.assertEqual(cells[1], 0)               # no SURFB stated
        self.assertEqual(cells[2], 0)               # Second_ID never decoded
        # Main_ID2 IS the /SURF/SEG built from the *SET_SEGMENT
        self.assertEqual(cells[3], int(segs[0].rsplit("/", 1)[1]))
        self.assertEqual(
            [x for x in res.warnings if "names no *PART" in x], [])

    def test_the_segment_rows_are_the_sets_own(self):
        _res, starter = _convert(self._seg_deck())
        seg = _headers(starter, "/SURF/SEG/")[0]
        rows = _data_rows(starter, seg)
        # rows[0] is the title card; one segment row follows, nodes 1..4
        self.assertEqual([int(rows[1][k:k + 10]) for k in range(10, 50, 10)],
                         [1, 2, 3, 4])

    def test_a_shell_element_set_takes_the_same_route(self):
        """SURFATYP 1 is a shell-ELEMENT set; every other contact writer in
        the file already screens `styp in (0, 1) and sid in segment_sets`, so
        the transducer does too."""
        _res, starter = _convert(self._seg_deck(satyp=1))
        self.assertIn("/SURF/SEG/", starter)

    def test_a_missing_segment_set_is_refused_by_name_not_read_as_a_part(self):
        res, starter = _convert(self._seg_deck(define=False))
        self.assertEqual(_headers(starter, "/INTER/SUB/"), [])
        w = [x for x in res.warnings if "CONTACT_FORCE_TRANSDUCER" in x
             and "-> skipped" in x]
        self.assertEqual(len(w), 1, res.warnings)
        # names WHAT type 0 is, instead of claiming the deck defines no *PART
        self.assertIn("*SET_SEGMENT", w[0])
        self.assertNotIn("names no *PART this deck defines, so", w[0])

    def test_the_side_pids_helper_refuses_types_0_and_1_directly(self):
        """A DIRECT unit test, because the one caller pre-empts this arm.

        `_transducer_surface` handles `styp in (0, 1)` itself, so a mutation
        that deletes the same screen inside `_transducer_side_pids` is not
        caught by any deck-level test — measured, in this round's own mutation
        pass. The arm is defence in depth for a future caller (and the function
        is exported), so it is pinned here on its own: reading a *SET_SEGMENT
        id as a *PART id is the defect that skipped transducer.k, and the
        helper must never do it again even if reached another way.
        """
        from k2rad.writer.contacts import _transducer_side_pids
        state = _dispatch(self._seg_deck())
        # part 1 EXISTS, so a type-3 side resolves it ...
        self.assertEqual(_transducer_side_pids(state, 1, 3), [1])
        # ... while the same id under a SEGMENT-SET type must resolve nothing
        for styp in (0, 1):
            with self.subTest(styp=styp):
                self.assertEqual(_transducer_side_pids(state, 1, styp), [])
                self.assertEqual(_transducer_side_pids(state, 10, styp), [])
        # sid = 0 and type 5 still mean "every part"
        self.assertEqual(_transducer_side_pids(state, 0, 0),
                         sorted(state.parts))
        self.assertEqual(_transducer_side_pids(state, 7, 5),
                         sorted(state.parts))

    def test_a_part_id_side_still_takes_the_part_route(self):
        """The 2/3/5 spellings are untouched: no /SURF/SEG, a part surface."""
        _res, starter = _convert(_ft_deck())
        self.assertEqual(_headers(starter, "/SURF/SEG/"), [])
        sid = int(_headers(starter, "/INTER/SUB/")[0].rsplit("/", 1)[1])
        cells = _sub_cells(starter, sid)
        self.assertEqual(cells[0], 0)
        self.assertNotEqual(cells[3], 0)

    def test_surfb_as_a_segment_set_fills_main_id1(self):
        """Both sides go through the same builder, so SURFB = a segment set
        gives TYPSUB = 3 rather than silently falling back to TYPSUB = 2."""
        deck = _ft_deck(surfa=1, satyp=3, surfb=10, sbtyp=0).replace(
            "*CONTROL_TERMINATION",
            "*SET_SEGMENT\n" + _row(10) + "\n" + _row(5, 6, 7, 8) + "\n"
            + "*CONTROL_TERMINATION")
        res, starter = _convert(deck)
        sid = int(_headers(starter, "/INTER/SUB/")[0].rsplit("/", 1)[1])
        cells = _sub_cells(starter, sid)
        self.assertNotEqual(cells[1], 0)            # Main_ID1 really filled
        self.assertEqual(len(_headers(starter, "/SURF/SEG/")), 1)
        self.assertEqual(
            [x for x in res.warnings if "Main_ID1 stays 0" in x], [])


class ThermalStandinGateTests(unittest.TestCase):
    """The stand-in's inertness claim rests on /DT/THERM, so its gate must.

    ``writer/assembly`` writes /DT/THERM only when
    ``soln == 1 AND _thermal_solve_active AND not is_implicit AND not
    is_modal``, with a further ``not _ams_is_emitted`` arm. The stand-in used
    to fire on ``soln == 1`` alone, so an implicit / modal / --ams SOLN=1 deck
    got a synthesized /MAT/ELAST carrying ``E = 1`` AND, as the very next
    warning, "*CONTROL_SOLUTION SOLN=1 ... It is NOT written here" - two
    sentences contradicting each other in one log, with E = 1 the part's real
    structural stiffness. No corpus deck is that shape (all ten SOLN=1
    carriers get /DT/THERM), but a steady-state thermal deck driven through
    *CONTROL_IMPLICIT_* is an ordinary one.
    """

    def test_an_implicit_soln1_deck_gets_no_standin(self):
        deck = _thermal_only_deck(
            extra="*CONTROL_IMPLICIT_GENERAL\n" + _row(1, 0.001) + "\n")
        res, starter = _convert(deck)
        self.assertEqual(
            [x for x in res.warnings if "SYNTHESIZES an inert" in x], [])
        w = [x for x in res.warnings
             if "NO thermal-only stand-in /MAT is synthesized" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("implicitly", w[0])
        self.assertIn("FABRICATED structural modulus", w[0])
        self.assertNotIn("k2rad_thermal_standin", starter)

    def test_an_ams_soln1_deck_gets_no_standin(self):
        res, starter = _convert(_thermal_only_deck(), ams=True)
        w = [x for x in res.warnings
             if "NO thermal-only stand-in /MAT is synthesized" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("--ams", w[0])
        self.assertNotIn("k2rad_thermal_standin", starter)

    def test_a_plain_soln1_deck_still_gets_one(self):
        """The gate is narrower, not closed: the corpus shape is unchanged."""
        res, starter = _convert(_thermal_only_deck())
        self.assertIn("k2rad_thermal_standin", starter)
        self.assertEqual(
            [x for x in res.warnings
             if "NO thermal-only stand-in /MAT is synthesized" in x], [])

    def test_a_standin_without_dt_therm_is_named_by_assembly(self):
        """The one gate condition the stand-in pass cannot test itself -
        _thermal_solve_active reads the /HEAT/MAT the stand-in enables - is
        named where the answer IS known: writer/assembly, after the fact."""
        # SOLN=1, a thermal material, elements, but NO temperature driver at
        # all, so _thermal_solve_active is False and /DT/THERM is not written.
        res, starter = _convert(_thermal_only_deck())
        self.assertIn("k2rad_thermal_standin", starter)
        w = [x for x in res.warnings
             if "AND THAT MATTERS FOR THE STAND-IN MATERIALS" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("E = 1 is the part's REAL structural stiffness", w[0])


class ZeroInitialTemperatureTests(unittest.TestCase):
    """A stated T = 0 must not become Radioss's 300 K default.

    ``hm_read_therm.F:236-237`` is ``IF (TINI == ZERO) TINI = THREE100`` and
    ``scoor3.F:328-338`` / ``cinmas.F:900-905`` / ``c3inmas.F:1516`` /
    ``pmass.F:233`` are ``IF (TEMP(node) == ZERO) TEMP(node) = TEMP0``. Both
    are EXACT zero tests, so a sentinel of 1e-10 fails them and the field
    starts where the deck says it starts.

    MEASURED end to end on ``ex_22_solid_elform_2`` (32 cycles, NORMAL
    TERMINATION both ways). Sentinel ON: the initial anim state is min 0.0 /
    max 0.0 and node 5 ends at 35.15680. Sentinel OFF: the initial state is
    min 0.0 / max 300.0 and node 5 ends at 198.21400. The LS-DYNA reference
    (its own .tprint, interpolated to the matched time the driven node 6
    fixes, 61.32760 -> t = 31.60 s) is 34.83880 - so +0.91 % with the
    sentinel and +468.9 % without it.
    """

    @staticmethod
    def _t0(starter: str) -> float:
        rows = _data_rows(starter, "/HEAT/MAT/")
        if rows is None:
            heads = _headers(starter, "/HEAT/MAT/")
            rows = _data_rows(starter, heads[0])
        return float(rows[0][0:20])

    #: The fixture's own model-wide card, which these tests replace.
    _BUILTIN = "*INITIAL_TEMPERATURE_SET\n" + _row(0, 20.0) + "\n"

    def _deck(self, temp) -> str:
        """ex_22's shape: *INITIAL_TEMPERATURE_SET on a NAMED set (not the
        sid = 0 spelling) that covers the whole model."""
        return _thermal_only_deck().replace(
            self._BUILTIN,
            "*INITIAL_TEMPERATURE_SET\n" + _row(3, temp) + "\n"
            + "*SET_NODE_LIST\n" + _row(3) + "\n"
            + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n")

    def _deck_stating_nothing(self) -> str:
        return _thermal_only_deck().replace(self._BUILTIN, "")

    def test_a_stated_zero_becomes_the_sentinel(self):
        res, starter = _convert(self._deck(0.0))
        self.assertEqual(self._t0(starter), 1.0e-10)
        w = [x for x in res.warnings if "exactly 0.0" in x]
        self.assertEqual(len(w), 1, res.warnings)
        for fact in ("hm_read_therm.F:236-237", "scoor3.F:328-338",
                     "198.21400", "34.83880", "35.15680",
                     "--no-zero-t0-sentinel"):
            self.assertIn(fact, w[0])

    def test_the_opt_out_writes_the_decks_own_zero(self):
        res, starter = _convert(self._deck(0.0), zero_t0_sentinel=False)
        self.assertEqual(self._t0(starter), 0.0)
        w = [x for x in res.warnings if "exactly 0.0" in x]
        self.assertEqual(len(w), 1, res.warnings)
        self.assertIn("Radioss WILL substitute 300 K", w[0])

    def test_a_stated_nonzero_is_untouched(self):
        """Neither the sentinel nor the warning: nothing states a zero.

        The model-wide (sid = 0) spelling puts its own value in the T0 cell;
        the named-set spelling leaves the cell at 0, which is the "not stated"
        path and is unchanged by this round.
        """
        res, starter = _convert(_thermal_only_deck())     # sid = 0, T = 20
        self.assertEqual(self._t0(starter), 20.0)
        self.assertEqual([x for x in res.warnings if "exactly 0.0" in x], [])
        res2, starter2 = _convert(self._deck(20.0))       # named set, T = 20
        self.assertEqual(self._t0(starter2), 0.0)
        self.assertEqual([x for x in res2.warnings if "exactly 0.0" in x], [])

    def test_a_deck_that_states_nothing_keeps_zero_and_says_nothing(self):
        """There the 300 K default is Radioss's own documented behaviour and
        contradicts nothing the deck said, so firing would be noise."""
        res, starter = _convert(self._deck_stating_nothing())
        self.assertEqual(self._t0(starter), 0.0)
        self.assertEqual(
            [x for x in res.warnings if "exactly 0.0" in x], [])

    def test_a_set_spelling_is_the_same_statement_as_sid_zero(self):
        """The old gate accepted only *INITIAL_TEMPERATURE with sid == 0;
        ex_22 uses _SET over a set that covers the model, which says the same
        thing, and got no warning and no sentinel."""
        from k2rad.writer.thermal import (_global_initial_temperature,
                                          _states_a_zero_initial_temperature)
        state = _dispatch(self._deck(0.0))
        # the narrow helper still declines to call a _SET card model-wide ...
        self.assertIsNone(_global_initial_temperature(state))
        # ... and the new one catches it
        self.assertTrue(_states_a_zero_initial_temperature(state))


if __name__ == "__main__":
    unittest.main()
