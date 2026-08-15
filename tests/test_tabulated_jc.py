"""Tests for the TABULATED JOHNSON-COOK batch conversions:

  *MAT_TABULATED_JOHNSON_COOK (224)   -> /MAT/LAW109 [+ /FAIL/TAB1]
      (also the _LOG_INTERPOLATION spelling -> I_smooth=2 and the numeric
      *MAT_224 alias; *MAT_..._GYS / _ORTHO_PLASTICITY (264) warn-skip)
  *DEFINE_TABLE_3D                    -> /TABLE/1 Ndim=3 (flat, verified
      grid form), plus the *MAT_224 LCK1 SLICING of the same nesting

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_foams.py, tests/test_adhesives.py and tests/test_viscoelastic.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant is recomputed by hand in the test rather than copied from the
implementation: the triaxiality flip -(-0.667/0.333) -> (-0.333, 0.667)
(LS-DYNA LCF is pressure-based p/sigma_vm, compression-positive; Radioss
TRIAX = sigma_m/sigma_vm tension-positive), the Lode remap
theta = (2/pi)*asin(xi) with theta(0.5) = 1/3 exactly, the natural-log rate
unwrap exp(ln 0.001) = 0.001 with dyna2rad's flat-extrapolation sentinel
10*max+1 = 11, E(T) sampled at TR=300 as 2.2e5 + 0.5*(1.8e5-2.2e5) = 2e5,
NUMINT=-30 -> P_thickfail 0.30 and NUMINT=2 on a NIP=5 stack -> 0.40, and
CP passed through PER MASS (450000000, NOT rho*CP=3.5325 — LAW109's engine
divides by RHO itself, sigeps109.F:419, unlike the LAW2/LAW4 rhoC_p
convention).

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic — LCH being inexpressible because no LAW109 engine path fills
TSTAR (the /FAIL/TAB1 fct_IDT no-op trap), the 3-D LCK1 split's
separability assumption, LCKT-as-curve carrying no temperature family, the
BETA TABLE_3D axis transpose, NUMINT=-200's track-but-never-delete mode —
the assertion pins the warning that states it. Several dyna2rad defects are
FIXED consciously and asserted as fixes: LCK1/LCKT as a plain curve leaves
d2r's tab_ID slots at 0 (deck broken) while k2rad re-routes the curve to a
1-D /TABLE/1; d2r wires a 3-D LCK1 id straight into tab_ID_h, which the
engine kills at cycle 1 (table2d_vinterp_log.F ANCMSG 36 + ARRET(2)) while
k2rad splits it; d2r's FAILIP=NUMINT/100 integer-truncates every
0<NUMINT<100 to zero; d2r copies a natural-log LCG axis raw; d2r emits its
failure card unconditionally (starter ERROR 3000 on an LCF-less deck) while
k2rad emits /FAIL/TAB1 only for a usable LCF; and the _GYS /
_ORTHO_PLASTICITY variants, which d2r drops SILENTLY (part wired to
mat_ID=0), warn loudly here.

Every emitted card form in this batch was validated on a live OpenRadioss
starter run (starter_win64 2026-05-20, /BEGIN 2022, np=1): a k2rad-converted
combined deck — /MAT/LAW109 with 2-D tab_ID_h/tab_ID_t, a rerouted 1-D
TAB_ETA, a /FAIL/TAB1 whose table1_ID is the Ndim=3 (triax, LCG-rate,
Lode-angle) AutoTable, fct_IDel, plus an unreferenced *DEFINE_TABLE_3D flat
Ndim=3 emission — answered NORMAL TERMINATION, 0 ERROR(S), 0 WARNING(S).
The starter's own listing confirmed the field placement asserted below:
"YOUNG MODULUS = 210000 / POISSON'S RATIO = 0.3", "YIELD STRESS VS PL.
STRAIN (VS STRAIN RATE) TABLE ID = 100 / INTERPOLATION FLAG = 1", "YIELD
STRESS TEMPERATURE DEPENDENCY TABLE ID = 200", "HEAT FRACTION TABLE ID =
520", "SPECIFIC HEAT COEFFICIENT = 450000000" (the per-mass CP), "REFERENCE
TEMPERATURE = 293 / INITIAL TEMPERATURE = 293" (T_ini defaulted to T_ref),
TAB1's "STRAIN TABLE ID = 90003", "ELEMENT LENGTH FUNCTION = 303 /
REFERENCE ELEMENT LENGTH = 1.0", "TEMPERATURE SCALE FUNCTION = 0",
"CRITICAL DAMAGE VALUE = 1 / DAMAGE PARAMETER N = 1 / DAMAGE FLAG = 0"
(the blank-defaults F>=1 instant criterion) and "SHELL ELEMENT DELETION
AFTER FAILURE OF ONE LAYER / SOLID ELEMENT DELETION AFTER FAILURE"
(NUMINT=1). The 3-D table echo proved the math end to end: parameter axes
(-0.333, 0.667) — the FLIP — then (0.001, 100) — LCG — then
(-1, 0.3333333333) — the theta remap — with ordinate planes
[0.3, 1.2, 0.39, 1.56] and [0.25, 1.0, 0.325, 1.3], i.e. exactly
eps_f(triax)*g(rate) including 1.2*1.3 = 1.56 — the per-row Scale_y
pre-multiplication computed back by the starter itself. A NEGATIVE control
— the same converted deck with ONE row of the 4-row Ndim=3 grid deleted —
answers exit 2 with "ERROR ID: 3089 ** ERROR IN TABLE DEFINITION -- TABLE
ID: 90003" twice, the complete-rectangular-grid rule the AutoTable builders
satisfy by construction.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                        # noqa: E402
from k2rad.parser import parse_k_file            # noqa: E402
from k2rad.handlers import HANDLERS, dispatch    # noqa: E402
from k2rad.state import ConversionState          # noqa: E402
from k2rad.writer.mesh import (                  # noqa: E402
    _target_mat_law, _TYPE3_BEAM_LAWS, _TYPE18_ONLY_BEAM_LAWS)
from k2rad.writer.common import _ref_flag_materials   # noqa: E402


# ── Harness (same shape as tests/test_foams.py) ──────────────────────────────

def _convert(deck: str):
    """convert() a deck string; return (result, starter_text)."""
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
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


def _row(*vals) -> str:
    return "".join(f"{v:>10}" for v in vals)


def _w20(*vals) -> str:
    """20-char right-aligned fields (the *DEFINE_TABLE point-card width)."""
    return "".join(f"{v:>20}" for v in vals)


def _blocks(starter: str, header: str):
    out, cur = [], None
    for ln in starter.splitlines():
        if ln.startswith(header):
            cur = [ln]
            out.append(cur)
        elif cur is not None:
            if ln.startswith("#---1----"):
                cur = None
            else:
                cur.append(ln)
    return out


def _block(starter: str, header: str):
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _cards(block):
    """A /MAT or /PROP block's DATA lines (title skipped, comments skipped)."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


# ── Decks ────────────────────────────────────────────────────────────────────

NODES = "*NODE\n" + "".join(
    f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
        (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
        (7, 10.0, 10.0, 10.0), (8, 0.0, 10.0, 10.0)))
SOLID = "*ELEMENT_SOLID\n" + _row(1, 7) + "\n" + _row(*range(1, 9)) + "\n"
SHELL = "*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
PART = "*PART\njc part\n" + _row(7, 7, 7) + "\n"
SEC = "*SECTION_SOLID\n" + _row(7, 1) + "\n"
SEC_SHELL = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 5) + "\n"
             + _row(1.2, 1.2, 1.2, 1.2) + "\n")

# ln(0.001) to full double precision — the natural-log rate axis marker.
LN0001 = -6.907755278982137


def _curve(lcid, pts):
    out = f"*DEFINE_CURVE\n{_row(lcid)}\n"
    for x, y in pts:
        out += _w20(x, y) + "\n"
    return out


def _table2d(tbid, rows):
    out = f"*DEFINE_TABLE_2D\n{_row(tbid, 1.0, 0.0)}\n"
    for v, lcid in rows:
        out += _w20(v, lcid) + "\n"
    return out


def _table3d(tbid, rows):
    out = f"*DEFINE_TABLE_3D\n{_row(tbid, 1.0, 0.0)}\n"
    for v, tid in rows:
        out += _w20(v, tid) + "\n"
    return out


def _mat224(card1, card2, card3=None, kw="*MAT_TABULATED_JOHNSON_COOK",
            title=None):
    out = kw + "\n"
    if title is not None:
        out += title + "\n"
    out += _row(*card1) + "\n" + _row(*card2) + "\n"
    if card3 is not None:
        out += _row(*card3) + "\n"
    return out


MESH = "*KEYWORD\n" + NODES + SOLID + PART + SEC

# The full 2-D deck: LCK1 = rate table 100, LCKT = temperature table 200,
# LCF = curve 300, LCG = curve 301, LCH = curve 302 (dropped), LCI = curve 303.
FULL_2D = (
    MESH
    + _mat224((7, "7.85E-9", "2.1E5", 0.3, "4.5E8", 293.0, 0.9, 1),
              (100, 200, 300, 301, 302, 303))
    + _table2d(100, [(0.001, 110), (100.0, 111)])
    + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
    + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
    + _table2d(200, [(293.0, 210), (493.0, 211)])
    + _curve(210, [(0.0, 350.0), (0.5, 500.0)])
    + _curve(211, [(0.0, 280.0), (0.5, 400.0)])
    + _curve(300, [(-0.667, 1.2), (0.333, 0.3)])
    + _curve(301, [(0.001, 1.0), (100.0, 1.3)])
    + _curve(302, [(200.0, 1.1), (800.0, 0.6)])
    + _curve(303, [(1.0, 1.0), (10.0, 1.2)])
    + "*END\n")


class TestLaw109Card(unittest.TestCase):
    def setUp(self):
        self.res, self.starter = _convert(FULL_2D)
        self.mat = _cards(_block(self.starter, "/MAT/LAW109/7"))

    def test_card1_rho(self):
        self.assertEqual(_col_f(self.mat[0], 1, 20), 7.85e-9)

    def test_card2_elasticity(self):
        self.assertEqual(_col_f(self.mat[1], 1, 20), 2.1e5)
        self.assertEqual(_col_f(self.mat[1], 21, 40), 0.3)

    def test_card3_cp_is_per_mass_not_rho_cp(self):
        # LAW109's C_p is energy/(mass*K): the engine divides by RHO itself
        # (sigeps109.F:419 TEMP += FTHERM*YLD*DPLA/(CP*RHO)), so LS-DYNA CP
        # copies 1:1. The LAW2/LAW4 convention would write rho*CP = 3.5325.
        cp = _col_f(self.mat[2], 1, 20)
        self.assertEqual(cp, 4.5e8)
        self.assertNotAlmostEqual(cp, 7.85e-9 * 4.5e8)

    def test_card3_eta_tref_tini(self):
        self.assertEqual(_col_f(self.mat[2], 21, 40), 0.9)     # BETA -> ETA
        self.assertEqual(_col_f(self.mat[2], 41, 60), 293.0)   # TR -> T_ref
        self.assertEqual(_col_f(self.mat[2], 61, 80), 0.0)     # T_ini -> TREF

    def test_card4_tables_and_ismooth(self):
        # tab_ID_h(10) tab_ID_t(10) Xscale_h(20) Yscale_h(20) [30sp] I_smooth(10)
        self.assertEqual(_col_i(self.mat[3], 1, 10), 100)
        self.assertEqual(_col_i(self.mat[3], 11, 20), 200)
        self.assertEqual(_col_f(self.mat[3], 21, 40), 0.0)   # -> default 1.0
        self.assertEqual(_col_f(self.mat[3], 41, 60), 0.0)   # -> default 1.0
        self.assertEqual(self.mat[3][60:90], " " * 30)
        self.assertEqual(_col_i(self.mat[3], 91, 100), 1)    # linear
        self.assertEqual(len(self.mat[3]), 100)

    def test_card5_tab_eta(self):
        self.assertEqual(_col_i(self.mat[4], 1, 10), 0)
        self.assertEqual(_col_f(self.mat[4], 11, 30), 0.0)
        self.assertEqual(len(self.mat), 5)

    def test_no_heat_mat_emitted(self):
        # /HEAT/MAT would SWITCH LAW109 to the imposed-temperature path and
        # kill the adiabatic self-heating (sigeps109.F:411-414).
        self.assertNotIn("/HEAT/MAT", self.starter)

    def test_lck1_table_kept_by_id(self):
        tab = _block(self.starter, "/TABLE/1/100")
        self.assertEqual(tab[3].strip(), "2")            # dimension card
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(_col_i(rows[0], 1, 10), 110)
        self.assertEqual(_col_f(rows[0], 21, 40), 0.001)
        self.assertEqual(_col_i(rows[1], 1, 10), 111)
        self.assertEqual(_col_f(rows[1], 21, 40), 100.0)


class TestFailTab1(unittest.TestCase):
    def setUp(self):
        self.res, self.starter = _convert(FULL_2D)
        self.tab1 = [ln for ln in _block(self.starter, "/FAIL/TAB1/7")[1:]
                     if not ln.startswith("#")]

    def test_card1_first_ip_deletion(self):
        # NUMINT=1 (the default): one failed IP deletes the element.
        self.assertEqual(_col_i(self.tab1[0], 1, 10), 1)     # Ifail_sh
        self.assertEqual(_col_i(self.tab1[0], 11, 20), 1)    # Ifail_so
        self.assertEqual(self.tab1[0][20:40], " " * 20)
        self.assertEqual(_col_f(self.tab1[0], 41, 60), 0.0)  # P_thickfail
        self.assertEqual(_col_f(self.tab1[0], 61, 80), 0.0)  # P_thinfail
        self.assertEqual(_col_i(self.tab1[0], 91, 100), 0)   # Ixfem

    def test_card2_blank_defaults_are_the_f_criterion(self):
        # Blank keeps Dcrit=1, D=0, n=1, Dadv=Dcrit (hm_read_fail_tab1.F):
        # dD = d(eps_p)/eps_f, instant deletion at D>=1 — MAT_224's F>=1.
        self.assertEqual(self.tab1[1].strip(), "0" + " " * 19 + "0"
                         + " " * 19 + "0" + " " * 19 + "0" + " " * 9 + "0")

    def test_card3_table1_is_the_lcf_lcg_grid(self):
        self.assertEqual(_col_i(self.tab1[2], 1, 10), 90002)
        self.assertEqual(_col_f(self.tab1[2], 11, 30), 0.0)   # Yscale1 -> 1
        self.assertEqual(_col_f(self.tab1[2], 31, 50), 0.0)   # Xscale1 -> 1
        self.assertEqual(_col_i(self.tab1[2], 51, 60), 0)     # no TABLE2
        # No instability table and FAD_EXP=0 keep DMG_FLAG=0: no softening,
        # matching MAT_224 (erosion without stress fade).
        self.assertEqual(_col_f(self.tab1[3], 71, 90), 0.0)   # FAD_EXP

    def test_card4_lci_function_with_absolute_size_axis(self):
        self.assertEqual(_col_i(self.tab1[3], 1, 10), 303)    # fct_IDel = LCI
        self.assertEqual(_col_f(self.tab1[3], 11, 30), 0.0)   # Fscale_el -> 1
        self.assertEqual(_col_f(self.tab1[3], 31, 50), 0.0)   # EI_ref -> 1.0
        self.assertEqual(_col_i(self.tab1[3], 91, 100), 0)    # Ch_i_f -> 1

    def test_card5_no_temperature_function(self):
        # LCH must NOT land on fct_IDT: no LAW109 path fills TSTAR, so the
        # function would be evaluated at 0 every cycle.
        self.assertEqual(_col_i(self.tab1[4], 1, 10), 0)
        self.assertEqual(_col_f(self.tab1[4], 61, 80), 0.0)   # Shear_limit
        self.assertEqual(_col_f(self.tab1[4], 81, 100), 0.0)  # Biax_limit
        self.assertTrue(_warns(self.res, "LCH=302"))
        self.assertTrue(_warns(self.res, "TSTAR"))

    def test_triaxiality_flip(self):
        # LS-DYNA LCF abscissa is p/sigma_vm (compression-positive); Radioss
        # TRIAX is sigma_m/sigma_vm (tension-positive): x -> -x, re-sorted.
        fn = _block(self.starter, "/FUNCT/90001")
        self.assertIn("Auto_MAT224_LCF_flip300_mid7", fn[1])
        pts = [ln for ln in fn[2:] if not ln.startswith("#")]
        self.assertEqual(_col_f(pts[0], 1, 20), -0.333)
        self.assertEqual(_col_f(pts[0], 21, 40), 0.3)
        self.assertEqual(_col_f(pts[1], 1, 20), 0.667)
        self.assertEqual(_col_f(pts[1], 21, 40), 1.2)

    def test_lcg_grid_premultiplied_scale(self):
        # table1_ID = flipped-LCF (x) LCG tensor grid: one row per rate with
        # Scale_y = g(rate) — /FAIL/TAB1 has no rate-scale FUNCTION slot, the
        # rate must be table dim 2.
        tab = _block(self.starter, "/TABLE/1/90002")
        self.assertEqual(tab[3].strip(), "2")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(len(rows), 2)
        for r, (rate, scale) in zip(rows, ((0.001, 1.0), (100.0, 1.3))):
            self.assertEqual(_col_i(r, 1, 10), 90001)
            self.assertEqual(_col_f(r, 21, 40), rate)
            self.assertEqual(r[40:80], " " * 40)
            self.assertEqual(_col_f(r, 81, 100), scale)
            self.assertEqual(len(r), 100)


class TestLck1Routing(unittest.TestCase):
    def test_plain_curve_becomes_1d_table(self):
        # dyna2rad's LCK1 branch requires "TABLE" (CM:11196) and leaves
        # tab_ID_h=0 for a curve — deck broken. k2rad re-routes the curve to
        # a 1-D /TABLE/1 under its own id.
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[3], 1, 10), 110)
        tab = _block(starter, "/TABLE/1/110")
        self.assertEqual(tab[3].strip(), "1")
        self.assertNotIn("/FUNCT/110", starter)

    def test_log_rate_table_exp_unwrap_and_sentinel(self):
        # First VALUE negative -> the whole axis is ln(rate) (Vol II p.357):
        # exp() every rate, duplicate the last curve at 10*max+1 (dyna2rad's
        # flat-extrapolation sentinel), I_smooth=2.
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (100, 0, 0, 0, 0, 0))
                + _table2d(100, [(LN0001, 110), (0.0, 111)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[3], 1, 10), 90001)
        self.assertEqual(_col_i(mat[3], 91, 100), 2)         # I_smooth = log
        tab = _block(starter, "/TABLE/1/90001")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(len(rows), 3)
        # exp(ln 0.001) = 0.001, exp(0) = 1, sentinel = 1*10+1 = 11
        self.assertEqual(_col_i(rows[0], 1, 10), 110)
        self.assertEqual(rows[0][20:40].strip(), "0.001")
        self.assertEqual(_col_i(rows[1], 1, 10), 111)
        self.assertEqual(_col_f(rows[1], 21, 40), 1.0)
        self.assertEqual(_col_i(rows[2], 1, 10), 111)        # duplicated last
        self.assertEqual(_col_f(rows[2], 21, 40), 11.0)
        self.assertTrue(_warns(res, "flat-extrapolation sentinel"))

    def test_3d_lck1_split(self):
        # sigma(eps_p, rate, T) cannot enter tab_ID_h (the engine ARRETs on
        # NDIM>2 at cycle 1 — dyna2rad wires the 3-D id through and produces
        # exactly that crash). Split: tab_ID_h = the plane nearest T_ref,
        # tab_ID_t = the (eps_p, T) table of every plane's lowest-rate curve.
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 293.0, 1.0, 1),
                          (400, 200, 0, 0, 0, 0))
                + _table3d(400, [(293.0, 101), (493.0, 102)])
                + _table2d(101, [(0.001, 110), (1.0, 111)])
                + _table2d(102, [(0.001, 120), (1.0, 121)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
                + _curve(120, [(0.0, 280.0), (0.5, 400.0)])
                + _curve(121, [(0.0, 330.0), (0.5, 480.0)])
                + _table2d(200, [(293.0, 110), (493.0, 120)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[3], 1, 10), 101)     # plane at T=293
        self.assertEqual(_col_i(mat[3], 11, 20), 90001)  # synthesized (eps,T)
        tab = _block(starter, "/TABLE/1/90001")
        self.assertEqual(tab[3].strip(), "2")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        # lowest-rate curve of each plane over the plane temperatures
        self.assertEqual(_col_i(rows[0], 1, 10), 110)
        self.assertEqual(_col_f(rows[0], 21, 40), 293.0)
        self.assertEqual(_col_i(rows[1], 1, 10), 120)
        self.assertEqual(_col_f(rows[1], 21, 40), 493.0)
        self.assertTrue(_warns(res, "multiplicatively separable"))
        # LS-DYNA ignores LCKT when LCK1 is 3-D — pinned, and tab_ID_t is the
        # synthesized table, NOT the deck's LCKT=200.
        self.assertTrue(_warns(res, "LCKT=200 is IGNORED"))

    def test_3d_lck1_flat_table_also_emitted(self):
        # The generic *DEFINE_TABLE_3D emission is independent of the split:
        # dim2 (A) = the INNER tables' rates, dim3 (B) = the OUTER T values,
        # rows ascending by (B, A), Scale_y=1 — the starter-verified form.
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 293.0, 1.0, 1),
                          (400, 0, 0, 0, 0, 0))
                + _table3d(400, [(293.0, 101), (493.0, 102)])
                + _table2d(101, [(0.001, 110), (1.0, 111)])
                + _table2d(102, [(0.001, 120), (1.0, 121)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
                + _curve(120, [(0.0, 280.0), (0.5, 400.0)])
                + _curve(121, [(0.0, 330.0), (0.5, 480.0)])
                + "*END\n")
        res, starter = _convert(deck)
        tab = _block(starter, "/TABLE/1/400")
        self.assertEqual(tab[3].strip(), "3")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        expect = [(110, 0.001, 293.0), (111, 1.0, 293.0),
                  (120, 0.001, 493.0), (121, 1.0, 493.0)]
        self.assertEqual(len(rows), 4)
        for r, (fct, a, b) in zip(rows, expect):
            self.assertEqual(_col_i(r, 1, 10), fct)
            self.assertEqual(_col_f(r, 21, 40), a)
            self.assertEqual(_col_f(r, 41, 60), b)
            self.assertEqual(r[60:80], " " * 20)
            self.assertEqual(_col_f(r, 81, 100), 1.0)
            self.assertEqual(len(r), 100)

    def test_dangling_lck1(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (999, 0, 0, 0, 0, 0))
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[3], 1, 10), 0)
        self.assertTrue(_warns(res, "LCK1=999"))
        self.assertTrue(_warns(res, "ERROR 781"))

    def test_missing_lck1_warns(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (0, 0, 0, 0, 0, 0))
                + "*END\n")
        res, starter = _convert(deck)
        self.assertTrue(_warns(res, "LCK1=0"))


class TestLcktAndBeta(unittest.TestCase):
    def test_lckt_plain_curve_dropped(self):
        # tab_ID_t forms the RATIO kt(eps,T)/kt(eps,T_ref); a 1-D curve makes
        # it identically 1 — dropped LOUDLY (d2r drops it silently).
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 210, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(210, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[3], 11, 20), 0)
        self.assertTrue(_warns(res, "LCKT=210"))
        self.assertTrue(_warns(res, "no temperature family"))

    def test_beta_negative_curve_positive_axis(self):
        # BETA=-500: a rate curve with an all-positive axis keeps its id and
        # is re-routed to a 1-D /TABLE/1 for the TAB_ETA table slot.
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, -500, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(500, [(0.001, 1.0), (100.0, 0.8)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_f(mat[2], 21, 40), 1.0)    # ETA default 1.0
        self.assertEqual(_col_i(mat[4], 1, 10), 500)     # TAB_ETA
        self.assertEqual(_block(starter, "/TABLE/1/500")[3].strip(), "1")

    def test_beta_negative_curve_log_axis(self):
        # Negative abscissas are natural-log rates: exp()-unwrapped POINT-WISE
        # (dyna2rad CM:11318-11327) into a fresh 1-D table. d2r's side effect
        # of forcing the YIELD table's I_smooth to 2 off a BETA curve is NOT
        # replicated — I_smooth stays with LCK1's own axis convention.
        ln01 = -2.302585092994046      # ln(0.1)
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, -500, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(500, [(LN0001, 1.0), (ln01, 0.8)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[4], 1, 10), 90001)
        self.assertEqual(_col_i(mat[3], 91, 100), 1)     # I_smooth untouched
        tab = _block(starter, "/TABLE/1/90001")
        self.assertEqual(tab[3].strip(), "1")
        pts = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(pts[0][:20].strip(), "0.001")   # exp(ln 0.001)
        self.assertEqual(_col_f(pts[0], 21, 40), 1.0)
        self.assertEqual(pts[1][:20].strip(), "0.1")     # exp(ln 0.1)
        self.assertEqual(_col_f(pts[1], 21, 40), 0.8)
        self.assertTrue(_warns(res, "BETA curve 500"))

    def test_beta_negative_2d_table_direct(self):
        # LS-DYNA nests a 2-D BETA table as T -> curves-over-rate, which lands
        # dim1=rate / dim2=T — exactly TAB_ETA's (rate, T) axes: direct ref.
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, -500, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _table2d(500, [(293.0, 510), (493.0, 511)])
                + _curve(510, [(0.001, 1.0), (100.0, 0.9)])
                + _curve(511, [(0.001, 0.95), (100.0, 0.8)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[4], 1, 10), 500)

    def test_beta_table_3d_dropped(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, -500, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _table3d(500, [(293.0, 501)])
                + _table2d(501, [(0.001, 510)])
                + _curve(510, [(0.0, 1.0), (0.5, 0.9)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[4], 1, 10), 0)
        self.assertTrue(_warns(res, "axis TRANSPOSE"))

    def test_beta_above_one_warns(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.2, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_f(mat[2], 21, 40), 1.2)
        self.assertTrue(_warns(res, "BETA=1.2 > 1"))

    def test_e_negative_curve_sampled_at_tr(self):
        # E(T) curve sampled at TR=300: 2.2e5 + (300-200)/(400-200)*(1.8e5-
        # 2.2e5) = 2.0e5. dyna2rad takes the first ordinate (2.2e5) instead.
        deck = (MESH
                + _mat224((7, "7.85E-9", -77, 0.3, 0, 300.0, 1.0, 1),
                          (110, 0, 0, 0, 0, 0))
                + _curve(77, [(200.0, "2.2E5"), (400.0, "1.8E5")])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_f(mat[1], 1, 20), 2.0e5)
        self.assertTrue(_warns(res, "sampled at T_ref"))


class TestFailVariants(unittest.TestCase):
    def _deck(self, card1, card2, extra="", mesh=None):
        return ((mesh or MESH) + _mat224(card1, card2)
                + _curve(300, [(-0.667, 1.2), (0.333, 0.3)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + extra + "*END\n")

    def test_lode_table_with_dummy_rate_axis(self):
        # Lode-dependent LCF without LCG: dim 2 of a 3-D failure table IS the
        # strain rate (fail_tab_s.F:316-333), so the Lode angle must sit on
        # dim 3 — two identical flat rate planes carry it. theta = (2/pi)*
        # asin(xi): theta(-1) = -1, theta(0.5) = 1/3 exactly (Radioss
        # interpolates the normalized Lode ANGLE, not the Lode parameter).
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 500, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _table2d(500, [(-1.0, 300), (0.5, 301)])
                + _curve(300, [(-0.667, 1.2), (0.333, 0.3)])
                + _curve(301, [(-0.667, 1.0), (0.333, 0.25)])
                + "*END\n")
        res, starter = _convert(deck)
        tab1 = [ln for ln in _block(starter, "/FAIL/TAB1/7")[1:]
                if not ln.startswith("#")]
        self.assertEqual(_col_i(tab1[2], 1, 10), 90003)
        tab = _block(starter, "/TABLE/1/90003")
        self.assertEqual(tab[3].strip(), "3")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(len(rows), 4)
        third = 1.0 / 3.0
        # rows ascending by (B=theta, A=rate); fct 90001 = flip of curve 300
        # (xi=-1), fct 90002 = flip of curve 301 (xi=0.5)
        expect = [(90001, 0.0, -1.0), (90001, 1.0e30, -1.0),
                  (90002, 0.0, third), (90002, 1.0e30, third)]
        for r, (fct, a, b) in zip(rows, expect):
            self.assertEqual(_col_i(r, 1, 10), fct)
            self.assertEqual(_col_f(r, 21, 40), a)
            self.assertAlmostEqual(_col_f(r, 41, 60), b, places=9)
            self.assertEqual(_col_f(r, 81, 100), 1.0)
        self.assertTrue(_warns(res, "Lode ANGLE"))

    def test_numint_percent_form(self):
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, -30),
                          (110, 0, 300, 0, 0, 0))
        res, starter = _convert(deck)
        tab1 = [ln for ln in _block(starter, "/FAIL/TAB1/7")[1:]
                if not ln.startswith("#")]
        self.assertEqual(_col_i(tab1[0], 1, 10), 2)          # Ifail_sh
        self.assertEqual(_col_f(tab1[0], 41, 60), 0.3)       # 30% -> 0.30
        self.assertTrue(_warns(res, "NUMINT=-30"))

    def test_numint_count_with_shell_nip(self):
        # NUMINT=2 on a NIP=5 shell stack: P_thickfail = 2/5 = 0.4 —
        # dyna2rad's FAILIP=NUMINT/100 integer-truncates 2/100 to 0 (starter
        # then defaults to 1); the fraction route is the conscious fix.
        mesh = "*KEYWORD\n" + NODES + SHELL + PART + SEC_SHELL
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 2),
                          (110, 0, 300, 0, 0, 0), mesh=mesh)
        res, starter = _convert(deck)
        tab1 = [ln for ln in _block(starter, "/FAIL/TAB1/7")[1:]
                if not ln.startswith("#")]
        self.assertEqual(_col_i(tab1[0], 1, 10), 2)
        self.assertEqual(_col_f(tab1[0], 41, 60), 0.4)
        self.assertTrue(_warns(res, "NUMINT=2"))

    def test_numint_count_without_nip_and_solid_warning(self):
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 3),
                          (110, 0, 300, 0, 0, 0))
        res, starter = _convert(deck)
        tab1 = [ln for ln in _block(starter, "/FAIL/TAB1/7")[1:]
                if not ln.startswith("#")]
        self.assertEqual(_col_i(tab1[0], 1, 10), 2)
        self.assertEqual(_col_f(tab1[0], 41, 60), 0.0)
        self.assertTrue(_warns(res, "NUMINT=3 > 1 but no shell"))
        self.assertTrue(_warns(res, "NUMINT=3 on SOLID"))

    def test_numint_minus_200_no_fail_card(self):
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, -200),
                          (110, 0, 300, 0, 0, 0))
        res, starter = _convert(deck)
        self.assertNotIn("/FAIL/TAB1", starter)
        self.assertTrue(_warns(res, "NUMINT=-200"))

    def test_no_lcf_no_fail_card(self):
        # dyna2rad emits /FAIL/TAB2 for EVERY MAT_224 -> starter ERROR 3000
        # without a failure table. k2rad emits nothing and says why.
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 0, 301, 0, 0),
                          extra=_curve(301, [(0.001, 1.0), (100.0, 1.3)]))
        res, starter = _convert(deck)
        self.assertNotIn("/FAIL/TAB1", starter)
        self.assertTrue(_warns(res, "LCF=0 but"))

    def test_lcg_log_axis_unwrapped(self):
        # A negative first LCG abscissa is LS-DYNA's ln(rate) axis — dyna2rad
        # copies it RAW into its rate slot (wrong axis); k2rad exp()-unwraps.
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 300, 301, 0, 0),
                          extra=_curve(301, [(LN0001, 1.0), (0.0, 1.3)]))
        res, starter = _convert(deck)
        tab = _block(starter, "/TABLE/1/90002")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(rows[0][20:40].strip(), "0.001")
        self.assertEqual(_col_f(rows[0], 81, 100), 1.0)
        self.assertEqual(_col_f(rows[1], 21, 40), 1.0)
        self.assertEqual(_col_f(rows[1], 81, 100), 1.3)
        self.assertTrue(_warns(res, "natural-log strain rates"))

    def test_lcf_3d_table_no_fail(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 500, 0, 0, 0))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _table3d(500, [(293.0, 501)])
                + _table2d(501, [(0.5, 300)])
                + _curve(300, [(-0.667, 1.2), (0.333, 0.3)])
                + "*END\n")
        res, starter = _convert(deck)
        self.assertNotIn("/FAIL/TAB1", starter)
        self.assertTrue(_warns(res, "LCF=500"))

    def test_dangling_lcf_no_fail(self):
        deck = self._deck((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 998, 0, 0, 0))
        res, starter = _convert(deck)
        self.assertNotIn("/FAIL/TAB1", starter)
        self.assertTrue(_warns(res, "LCF=998"))

    def test_lci_multi_row_table_dropped_single_row_collapsed(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 300, 0, 0, 600))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(300, [(-0.667, 1.2), (0.333, 0.3)])
                + _table2d(600, [(-0.333, 610), (0.333, 611)])
                + _curve(610, [(1.0, 1.0), (10.0, 1.2)])
                + _curve(611, [(1.0, 1.0), (10.0, 1.4)])
                + "*END\n")
        res, starter = _convert(deck)
        tab1 = [ln for ln in _block(starter, "/FAIL/TAB1/7")[1:]
                if not ln.startswith("#")]
        self.assertEqual(_col_i(tab1[3], 1, 10), 0)
        self.assertTrue(_warns(res, "LCI=600"))
        deck1 = (MESH
                 + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                           (110, 0, 300, 0, 0, 600))
                 + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                 + _curve(300, [(-0.667, 1.2), (0.333, 0.3)])
                 + _table2d(600, [(0.0, 610)])
                 + _curve(610, [(1.0, 1.0), (10.0, 1.2)])
                 + "*END\n")
        res1, starter1 = _convert(deck1)
        tab1 = [ln for ln in _block(starter1, "/FAIL/TAB1/7")[1:]
                if not ln.startswith("#")]
        self.assertEqual(_col_i(tab1[3], 1, 10), 610)
        self.assertTrue(_warns(res1, "1-row table"))

    def test_card3_drops_warned(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 0, 0, 0, 0, 1),
                          card3=(1, 5, 3, 1, 42))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        self.assertTrue(_warns(res, "FAILOPT=1"))
        self.assertTrue(_warns(res, "NUMAVG=5"))
        self.assertTrue(_warns(res, "ERODE=1"))
        self.assertTrue(_warns(res, "LCPS=42"))
        self.assertTrue(_warns(res, "BFLG=1"))

    def test_bflg_with_beta_table_drops_tab_eta(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, -500, 1),
                          (110, 0, 0, 0, 0, 0, 1))
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(500, [(0.001, 1.0), (100.0, 0.8)])
                + "*END\n")
        res, starter = _convert(deck)
        mat = _cards(_block(starter, "/MAT/LAW109/7"))
        self.assertEqual(_col_i(mat[4], 1, 10), 0)
        self.assertTrue(_warns(res, "BFLG=1 reinterprets"))


class TestDefineTable3D(unittest.TestCase):
    def test_standalone_flat_emission(self):
        deck = (MESH.replace(_row(7, 7, 7), _row(7, 7, 8))
                + "*MAT_ELASTIC\n" + _row(8, "7.85E-9", "2.1E5", 0.3) + "\n"
                + _table3d(400, [(493.0, 102), (293.0, 101)])
                + _table2d(101, [(0.001, 110), (1.0, 111)])
                + _table2d(102, [(0.001, 120), (1.0, 121)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
                + _curve(120, [(0.0, 280.0), (0.5, 400.0)])
                + _curve(121, [(0.0, 330.0), (0.5, 480.0)])
                + "*END\n")
        res, starter = _convert(deck)
        tab = _block(starter, "/TABLE/1/400")
        self.assertEqual(tab[3].strip(), "3")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        # deck order is (493, 293); rows re-sorted ascending by (B, A)
        self.assertEqual([_col_f(r, 41, 60) for r in rows],
                         [293.0, 293.0, 493.0, 493.0])
        self.assertEqual([_col_i(r, 1, 10) for r in rows],
                         [110, 111, 120, 121])

    def test_ragged_grid_not_emitted(self):
        # hm_read_table2_1.F requires a COMPLETE rectangular secondary grid;
        # emitting a ragged one would be starter ERROR 3089 (negative-control
        # verified) — warn and skip instead.
        deck = (MESH.replace(_row(7, 7, 7), _row(7, 7, 8))
                + "*MAT_ELASTIC\n" + _row(8, "7.85E-9", "2.1E5", 0.3) + "\n"
                + _table3d(400, [(293.0, 101), (493.0, 102)])
                + _table2d(101, [(0.001, 110), (1.0, 111)])
                + _table2d(102, [(0.001, 120)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
                + _curve(120, [(0.0, 280.0), (0.5, 400.0)])
                + "*END\n")
        res, starter = _convert(deck)
        self.assertNotIn("/TABLE/1/400", starter)
        self.assertTrue(_warns(res, "ERROR 3089"))

    def test_rows_missing_inner_table_dropped(self):
        deck = (MESH.replace(_row(7, 7, 7), _row(7, 7, 8))
                + "*MAT_ELASTIC\n" + _row(8, "7.85E-9", "2.1E5", 0.3) + "\n"
                + _table3d(400, [(293.0, 101), (493.0, 999)])
                + _table2d(101, [(0.001, 110), (1.0, 111)])
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + _curve(111, [(0.0, 420.0), (0.5, 600.0)])
                + "*END\n")
        res, starter = _convert(deck)
        tab = _block(starter, "/TABLE/1/400")
        rows = [ln for ln in tab[4:] if not ln.startswith("#")]
        self.assertEqual(len(rows), 2)      # only the resolvable plane
        self.assertTrue(_warns(res, "missing/unresolved"))


class TestDispatchAndRegistry(unittest.TestCase):
    def test_title_variant_and_log_interpolation(self):
        deck = (MESH
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 0, 0, 0, 0),
                          kw="*MAT_TABULATED_JOHNSON_COOK_LOG_INTERPOLATION"
                             "_TITLE",
                          title="my tabulated jc")
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        blk = _block(starter, "/MAT/LAW109/7")
        self.assertEqual(blk[1], "my tabulated jc")
        mat = _cards(blk)
        self.assertEqual(_col_i(mat[3], 91, 100), 2)     # I_smooth = log

    def test_numeric_alias(self):
        state = _dispatch(
            _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                    (110, 0, 0, 0, 0, 0), kw="*MAT_224"))
        self.assertIn(7, state.mat_tabulated_jc)

    def test_gys_and_ortho_warn_skip(self):
        for kw, mat_id in (("*MAT_TABULATED_JOHNSON_COOK_GYS", "224_GYS"),
                           ("*MAT_224_GYS", "224_GYS"),
                           ("*MAT_TABULATED_JOHNSON_COOK_ORTHO_PLASTICITY",
                            "264"),
                           ("*MAT_264", "264")):
            with self.subTest(kw=kw):
                deck = (MESH
                        + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                                  (110, 0, 0, 0, 0, 0), kw=kw)
                        + "*END\n")
                res, starter = _convert(deck)
                self.assertNotIn("/MAT/LAW109", starter)
                w = _warns(res, "DROPPED")
                self.assertTrue(w)
                self.assertTrue(_warns(res, "mid=7"))
                self.assertTrue(_warns(res, mat_id))
                self.assertIn(kw.lstrip("*"), res.skipped_keywords)

    def test_multi_material_deck(self):
        deck = (MESH
                + "*PART\nelastic part\n" + _row(8, 8, 8) + "\n"
                + "*SECTION_SOLID\n" + _row(8, 1) + "\n"
                + _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                          (110, 0, 0, 0, 0, 0))
                + "*MAT_ELASTIC\n" + _row(8, "7.85E-9", "2.1E5", 0.3) + "\n"
                + _curve(110, [(0.0, 350.0), (0.5, 500.0)])
                + "*END\n")
        res, starter = _convert(deck)
        _block(starter, "/MAT/LAW109/7")
        _block(starter, "/MAT/ELAST/8")

    def test_target_mat_law_and_beam_classes(self):
        state = _dispatch(
            _mat224((7, "7.85E-9", "2.1E5", 0.3, 0, 0, 1.0, 1),
                    (110, 0, 0, 0, 0, 0)))
        self.assertEqual(_target_mat_law(state, 7), 109)
        # LAW109 declares no BEAM_* class (hm_read_mat109.F:182-191) — beam
        # parts draw the existing ERROR-3046 warning through these sets.
        self.assertNotIn(109, _TYPE3_BEAM_LAWS)
        self.assertNotIn(109, _TYPE18_ONLY_BEAM_LAWS)
        # *MAT_224 carries no REF flag — not a REF-diagnostics family.
        self.assertTrue(all(fam is not state.mat_tabulated_jc
                            for _, fam in _ref_flag_materials(state)))

    def test_handler_registry_spellings(self):
        for kw in ("MAT_TABULATED_JOHNSON_COOK",
                   "MAT_TABULATED_JOHNSON_COOK_LOG_INTERPOLATION",
                   "MAT_224", "MAT_TABULATED_JOHNSON_COOK_GYS",
                   "MAT_224_GYS",
                   "MAT_TABULATED_JOHNSON_COOK_ORTHO_PLASTICITY",
                   "MAT_264", "DEFINE_TABLE_3D"):
            self.assertIn(kw, HANDLERS)


if __name__ == "__main__":
    unittest.main()
