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


if __name__ == "__main__":
    unittest.main()
