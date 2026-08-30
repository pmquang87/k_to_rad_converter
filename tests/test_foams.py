"""Tests for the FOAM BATCH conversions:

  *MAT_SOIL_AND_FOAM (005)            -> /MAT/LAW21 (DPRAG) + the P(mu)
      abscissa transform mu = exp(-EPS) - 1
  *MAT_LOW_DENSITY_VISCOUS_FOAM (073) -> /MAT/LAW90 [+ /VISC/PRONY same id]
  *MAT_MODIFIED_HONEYCOMB (126)       -> /MAT/LAW50 on a synthesized
      /PROP/TYPE6 (SOL_ORTH) via the AOPT machinery
  *MAT_DESHPANDE_FLECK_FOAM (154)     -> /MAT/LAW115 (deterministic Istat=0)
  *MAT_HILL_FOAM (177)                -> /MAT/LAW62 (constants branch;
      LCID>0 fit branch warn-skips at parse — LAW62 has no fit path)
  *CONTACT_INTERIOR                   -> Icontrol=1 resolution + warnings
      (the input column is radioss2025-only; a /BEGIN 2022 deck cannot
      carry it — measured, see below — so nothing is emitted)

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_adhesives.py, tests/test_viscoelastic.py and
tests/test_metal_plasticity_2.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant is recomputed by hand in the test rather than copied from the
implementation: MAT_005's E = 9GK/(3K+G) = 900 and Nu = (3K-2G)/(6K+2G)
= 0.2 for G=375/KUN=500, Kt = B = KUN (the solver-measured fix over
dyna2rad's dead-B Kt=KUN/100 — see _emit_mat_law21; VCR=1 keeps KUN/100 on
purpose), the curve transform mu = exp(-EPS)-1 point by point, MAT_126's
G-row fallback E/2(1+PR) = 200, the V/V0 recompute 1 - x, MAT_154's
verbatim Deshpande-Fleck constants, and MAT_177's Hill → Ogden identity
mu_i = Ci*Bi/2 / alpha_i = Bi with Nu = N/(1+2N) = 0.25 for N=0.5 — the
_mat177 fixture states card 1 in the MANUAL's MID RO K N MU order, so the
Nu assertion pins the parse columns.

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic — VCR=1's B=0 that the starter replaces by Kt (its WARNING 829),
the LCA<0 transversely-isotropic surface whose damage curves become yield
curves, LCSR=-1's dropped per-direction rate cards, DERFI being a derivative
flag while Ires picks the return-mapping algorithm, the MAT_073 LCID2>0
relaxation-fit branch nobody fits — the assertion pins the warning that
states it. Two dyna2rad defects are FIXED consciously and asserted as fixes:
MAT_154 PFAIL -> SIGP_F (d2r's cfg never parses PFAIL, so its SIGP_F is
silently always 0) and MAT_177's index-aligned Ogden pairs (d2r compacts the
C and B lists independently and mispairs them when a Ci is zero mid-list).
A third d2r gap is closed loudly: an all-positive MAT_005 pressure curve
(both d2r branches require a negative abscissa and silently create NO
function) converts with a warning.

Every emitted card in this batch was validated on a live OpenRadioss starter
run (starter_win64 2026-05-20, /BEGIN 2022, np=1): the all-five-materials
combined deck reads back NORMAL TERMINATION, 0 ERROR(S), 0 WARNING(S). The
starter's own listing confirmed the field-by-field placement asserted
below: LAW21's "PRESSURE FUNCTION NUMBER = 90001 / TENSILE BULK = 500 /
UNLOADING BULK = 500" (Kt=B=KUN for KUN=500 — the dead-B fix), LAW90's
"SHAPE FACTOR FOR UNLOADING = 2 / HYSTERETIC UNLOADING FACTOR = 0.2" plus
"ORDER OF PRONY SERIES = 2" from the same-id /VISC/PRONY, LAW50's "YIELD
STRESS 11" block listing exactly the five sampled "STRAIN RATE" lines
1e-3..100 (the LCSR first-five rule), LAW62's "EQUIVALENT POISSON RATIO =
0.25" = N/(1+2N) for N=0.5 read from FIELD 4 of a manual-order deck (a
transposed read would print 0.0454 from MU=0.05), and — a check that could
FAIL — LAW115's "MAX.
PRINCIPAL STRESS AT FAILURE = 50", proving the PFAIL->SIGP_F fix reached
the starter (dyna2rad reads 0 there). MAT_154 now starts warning-free: the
Isolid=24 routing clears WARNING 1905, whose Isolid-17 pairing was
ENGINE-fatal (dt collapse at cycle 0, 1-cycle "NORMAL TERMINATION" with an
empty result — the trap the routing closes).
A NEGATIVE control — the same MAT_005 on a SHELL part —
answers exit 2 with "ERROR ID: 3046 ... ELEMENTS OF TYPE SHELL ARE NOT
COMPATIBLE WITH MATERIAL ID 7 OF TYPE 21", the exact refusal the shell
warning names.

*CONTACT_INTERIOR's version gate was MEASURED, not guessed: a /PROP/SOLID
with the trailing "Ndir sphpartID Icontrol" card under /BEGIN 2022 leaves
the starter's per-part echo at ICONTROL 0 and draws WARNING 100213
(unsupported field at end of line); the identical deck under /BEGIN 2025
echoes ICONTROL 1 with 0 warnings. Emitting a dead field that claims to be
set would be silently wrong, so the conversion is the loud warning chain
asserted below.
"""

import math
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
from k2rad.writer.mesh import _target_mat_law    # noqa: E402
from k2rad.writer.common import _ref_flag_materials   # noqa: E402


# ── Harness (same shape as tests/test_adhesives.py) ──────────────────────────

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
PART = "*PART\nfoam part\n" + _row(7, 7, 7) + "\n"
SEC = "*SECTION_SOLID\n" + _row(7, 1) + "\n"
SEC_SHELL = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 5) + "\n"
             + _row(1.2, 1.2, 1.2, 1.2) + "\n")
END = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n"

REF_GEOM = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
            "       1             0.0             0.0             0.0\n"
            "       2            10.5             0.0             0.0\n"
            "       3            10.5            10.5             0.0\n"
            "       4             0.0            10.5             0.0\n")


def _curve(lcid: int, pts, sfa="", sfo="") -> str:
    return ("*DEFINE_CURVE\n" + _row(lcid, "", sfa, sfo) + "\n"
            + "".join(f"{x:>20}{y:>20}\n" for x, y in pts))


def _solid_deck(mat: str, extra: str = "") -> str:
    return NODES + SOLID + PART + SEC + mat + extra + END


def _shell_deck(mat: str, extra: str = "") -> str:
    return NODES + SHELL + PART + SEC_SHELL + mat + extra + END


# G=375, KUN=500 -> E = 9*375*500/(3*500+375) = 900 and
# Nu = (3*500-2*375)/(6*500+2*375) = 750/3750 = 0.2, both exact.
def _mat005(kw="*MAT_SOIL_AND_FOAM", mid=7, rho="1.8E-9", g=375.0, kun=500.0,
            a0=0.01, a1=0.4, a2=0.3, pc=-0.05, vcr=0.0, ref=0.0, lcid="",
            eps=(0.0, -0.05, -0.10, -0.15), p=(0.0, 10.0, 20.0, 30.0)) -> str:
    e = list(eps) + [""] * (10 - len(eps))
    pv = list(p) + [""] * (10 - len(p))
    return (kw + "\n"
            + _row(mid, rho, g, kun, a0, a1, a2, pc) + "\n"
            + _row(vcr, ref, lcid) + "\n"
            + _row(*e[:8]) + "\n" + _row(*e[8:]) + "\n"
            + _row(*pv[:8]) + "\n" + _row(*pv[8:]) + "\n")


def _mat073(kw="*MAT_LOW_DENSITY_VISCOUS_FOAM", mid=7, rho="5.0E-11", e=0.5,
            lcid=300, tc="", hu=0.2, beta="", damp="", shape=2.0, fail="",
            bvflag="", kcon="", lcid2=0, bstart="", tramp="", nv="",
            prony=((0.12, 800.0, ""), (0.06, 40.0, "")), tail=()) -> str:
    deck = (kw + "\n"
            + _row(mid, rho, e, lcid, tc, hu, beta, damp) + "\n"
            + _row(shape, fail, bvflag, kcon, lcid2, bstart, tramp, nv) + "\n")
    for card in prony:
        deck += _row(*card) + "\n"
    for card in tail:
        deck += _row(*card) + "\n"
    return deck


LC073 = _curve(300, ((0.0, 0.0), (0.5, 0.1), (0.9, 1.5)))


def _mat126(kw="*MAT_MODIFIED_HONEYCOMB", mid=7, rho="2.0E-10", e=500.0,
            pr=0.25, sigy="", vf="", mu="", bulk="",
            lca=401, lcb=402, lcc=403, lcs=404, lcab=405, lcbc=406, lcca=407,
            lcsr="", eaau=0.5, ebbu=0.6, eccu=0.7, gabu=0.2, gbcu=0.25,
            gcau=0.3, aopt=2.0, macf="",
            card4=("", "", "", 1.0, 0.0, 0.0, "", ""),
            card5=(0.0, 1.0, 0.0, 0.08, 0.12, "", "", ""),
            extra_cards=()) -> str:
    deck = (kw + "\n"
            + _row(mid, rho, e, pr, sigy, vf, mu, bulk) + "\n"
            + _row(lca, lcb, lcc, lcs, lcab, lcbc, lcca, lcsr) + "\n"
            + _row(eaau, ebbu, eccu, gabu, gbcu, gcau, aopt, macf) + "\n"
            + _row(*card4) + "\n" + _row(*card5) + "\n")
    for card in extra_cards:
        deck += _row(*card) + "\n"
    return deck


CRVS126 = "".join(_curve(400 + i, ((0.0, 1.0 + i), (0.8, 2.0 + i)))
                  for i in range(1, 8))


def _mat154(kw="*MAT_DESHPANDE_FLECK_FOAM", mid=7, rho="2.7E-10", e=1000.0,
            pr=0.05, alpha=1.5, gamma=2.0, epsd=1.6, alpha2=40.0, beta=3.0,
            sigp=1.2, derfi="", cfail=0.1, pfail=25.0, num="") -> str:
    return (kw + "\n"
            + _row(mid, rho, e, pr, alpha, gamma) + "\n"
            + _row(epsd, alpha2, beta, sigp, derfi, cfail, pfail, num) + "\n")


def _mat177(kw="*MAT_HILL_FOAM", mid=7, rho="1.0E-10", k="", n=0.5, mu="",
            lcid="", fittype="", lcsr="",
            c=(0.8, "", 0.4, "", "", "", "", ""),
            b=(4.0, 5.0, 2.0, "", "", "", "", ""), rm=None) -> str:
    # Card 1 in the MANUAL's field order MID RO K N MU (Vol II R17 p.2-1216;
    # the shipped mat_177.cfg agrees) — with the deck stated in that order,
    # the Nu = N/(1+2N) assertions below are real checks of the parse
    # columns, not echoes of a fixture that mirrors the implementation.
    deck = kw + "\n" + _row(mid, rho, k, n, mu, lcid, fittype, lcsr) + "\n"
    if not lcid:
        deck += _row(*c) + "\n" + _row(*b) + "\n"
    if rm is not None:
        deck += _row(*rm) + "\n"
    return deck


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / keyword registry
# ═════════════════════════════════════════════════════════════════════════════

class DispatchTests(unittest.TestCase):
    """Every documented keyword spelling and numeric alias reaches its
    handler; *MAT_SOIL_AND_FOAM_FAILURE (014) deliberately does NOT — its
    dyna2rad law 14 has no dispatch case (generic 1:1 dump), and silently
    converting away its failure semantics onto LAW21 would be worse than the
    skip."""

    def test_every_spelling_is_registered(self):
        for kw in ("MAT_SOIL_AND_FOAM", "MAT_005", "MAT_5",
                   "MAT_LOW_DENSITY_VISCOUS_FOAM", "MAT_073", "MAT_73",
                   "MAT_MODIFIED_HONEYCOMB", "MAT_126",
                   "MAT_DESHPANDE_FLECK_FOAM", "MAT_154",
                   "MAT_HILL_FOAM", "MAT_177",
                   "CONTACT_INTERIOR", "SET_PART_ADD"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_soil_and_foam_failure_is_not_routed(self):
        self.assertNotIn("MAT_SOIL_AND_FOAM_FAILURE", HANDLERS)
        state = _dispatch(_solid_deck(
            "*MAT_SOIL_AND_FOAM_FAILURE\n" + _row(7, "1.8E-9", 375.0, 500.0)
            + "\n" + _row(0.0, 0.0) + "\n"))
        self.assertNotIn(7, state.mat_soil_and_foam)
        self.assertIn("MAT_SOIL_AND_FOAM_FAILURE", state.skipped_keywords)

    def test_offset_specs_cover_every_spelling(self):
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("MAT_SOIL_AND_FOAM", "MAT_005", "MAT_5",
                   "MAT_LOW_DENSITY_VISCOUS_FOAM", "MAT_073", "MAT_73",
                   "MAT_MODIFIED_HONEYCOMB", "MAT_126",
                   "MAT_DESHPANDE_FLECK_FOAM", "MAT_154",
                   "MAT_HILL_FOAM", "MAT_177",
                   "CONTACT_INTERIOR", "SET_PART_ADD"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_title_option_is_stripped_and_read(self):
        cases = (
            ("*MAT_SOIL_AND_FOAM_TITLE", "soil foam title",
             _mat005(kw="*MAT_SOIL_AND_FOAM_TITLE\nsoil foam title")),
            ("*MAT_DESHPANDE_FLECK_FOAM_TITLE", "df foam title",
             _mat154(kw="*MAT_DESHPANDE_FLECK_FOAM_TITLE\ndf foam title")),
            ("*MAT_HILL_FOAM_TITLE", "hill title",
             _mat177(kw="*MAT_HILL_FOAM_TITLE\nhill title")),
        )
        for kw, title, mat in cases:
            with self.subTest(kw=kw):
                _, starter = _convert(_solid_deck(mat))
                self.assertIn(title, starter.splitlines(),
                              f"{kw} title line not emitted")


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_SOIL_AND_FOAM (005) -> /MAT/LAW21
# ═════════════════════════════════════════════════════════════════════════════

class Mat005Tests(unittest.TestCase):
    """/MAT/LAW21 layout (matl21_dprag.cfg FORMAT(radioss130)): C1 RHO_I /
    C2 E(1-20) Nu(21-40) / C3 A0 A1 A2 Amax / C4 func_IDf(1-10) blank(11-20)
    Kt(21-40) FscaleP(41-60) / C5 P_min(1-20) P_ext(21-40) /
    C6 B(1-20) Mu_max(21-40)."""

    def test_card_layout(self):
        res, starter = _convert(_solid_deck(_mat005()))
        cards = _cards(_block(starter, "/MAT/LAW21/7"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 1.8e-9)
        # E = 9GK/(3K+G) = 9*375*500/1875 = 900; Nu = 750/3750 = 0.2
        self.assertEqual(_col_f(cards[1], 1, 20), 900.0)
        self.assertEqual(_col_f(cards[1], 21, 40), 0.2)
        self.assertEqual(_col_f(cards[2], 1, 20), 0.01)
        self.assertEqual(_col_f(cards[2], 21, 40), 0.4)
        self.assertEqual(_col_f(cards[2], 41, 60), 0.3)
        self.assertEqual(_col_f(cards[2], 61, 80), 0.0)    # Amax -> 1e30
        fid = _col_i(cards[3], 1, 10)
        self.assertEqual(fid, 90001)
        self.assertEqual(cards[3][10:20], " " * 10)        # literal gap
        self.assertEqual(_col_f(cards[3], 21, 40), 500.0)  # Kt = KUN (VCR=0)
        self.assertEqual(_col_f(cards[3], 41, 60), 0.0)    # FscaleP -> 1.0
        self.assertEqual(_col_f(cards[4], 1, 20), -0.05)   # P_min = PC
        self.assertEqual(_col_f(cards[4], 21, 40), 0.0)    # P_ext
        self.assertEqual(_col_f(cards[5], 1, 20), 500.0)   # B = KUN
        self.assertEqual(_col_f(cards[5], 21, 40), 0.0)    # Mu_max -> 1e20
        # The Kt = B = KUN fix over dyna2rad's dead-B Kt=KUN/100 is warned
        # with the engine mechanism named.
        hits = _warns(res, "Kt = B = KUN = 500")
        self.assertTrue(hits)
        self.assertIn("Mu_max", hits[0])

    def test_eps_p_transform(self):
        """mu_i = exp(-EPS_i) - 1, ascending, ordinates unchanged."""
        _, starter = _convert(_solid_deck(_mat005()))
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(len(pts), 4)      # trailing blank card slots stripped
        self.assertEqual(pts[0], (0.0, 0.0))
        for (x, y), (eps, p) in zip(pts[1:], ((-0.05, 10.0), (-0.10, 20.0),
                                              (-0.15, 30.0))):
            self.assertAlmostEqual(x, math.exp(-eps) - 1.0, places=9)
            self.assertEqual(y, p)
        self.assertEqual([x for x, _ in pts], sorted(x for x, _ in pts))

    def test_zero_point_prepended_when_eps1_nonzero(self):
        """LS-DYNA auto-generates (0,0) when EPS1 != 0 (Remark 1)."""
        _, starter = _convert(_solid_deck(
            _mat005(eps=(-0.05, -0.10), p=(10.0, 20.0))))
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(pts[0], (0.0, 0.0))
        self.assertEqual(len(pts), 3)

    def test_lcid_curve_preferred_and_scaled_before_transform(self):
        """LCID wins over the EPS/P pairs, and the *DEFINE_CURVE SFA bakes
        into the points BEFORE the exp transform (the physical EPS is
        SFA*x): raw -0.1 with SFA=0.5 -> EPS=-0.05 -> mu=exp(0.05)-1."""
        deck = _solid_deck(
            _mat005(lcid=333, eps=(0.0,), p=(0.0,)),
            _curve(333, ((0.0, 0.0), (-0.1, 40.0)), sfa=0.5))
        res, starter = _convert(deck)
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(len(pts), 2)
        self.assertAlmostEqual(pts[1][0], math.exp(0.05) - 1.0, places=9)
        self.assertEqual(pts[1][1], 40.0)
        self.assertTrue(_warns(res, "pressure curve (LCID=333)"))

    def test_dangling_lcid_falls_back_to_pairs(self):
        res, starter = _convert(_solid_deck(_mat005(lcid=999)))
        self.assertTrue(_warns(res, "LCID=999 has no parsed"))
        self.assertTrue(_blocks(starter, "/FUNCT/90001"))

    def test_vcr_1_zeroes_unloading_bulk(self):
        """VCR=1 keeps dyna2rad's B=0 + Kt=KUN/100 pair ON PURPOSE: the
        starter substitutes B=Kt (WARNING 829) and the soft modulus makes
        the engine retrace the loading curve — VCR=1's load=unload
        semantics — where the VCR=0 Kt=KUN fix would unload elastically."""
        res, starter = _convert(_solid_deck(_mat005(vcr=1.0)))
        cards = _cards(_block(starter, "/MAT/LAW21/7"))
        self.assertEqual(_col_f(cards[5], 1, 20), 0.0)     # B = 0
        self.assertEqual(_col_f(cards[3], 21, 40), 5.0)    # Kt = KUN/100
        self.assertTrue(_warns(res, "VCR=1"))
        self.assertTrue(_warns(res, "WARNING 829"))
        self.assertFalse(_warns(res, "Kt = B = KUN"))

    def test_mixed_sign_curve_drops_negative_branch(self):
        res, starter = _convert(_solid_deck(
            _mat005(eps=(-0.2, 0.0, 0.05, 0.10), p=(5.0, 0.0, 10.0, 20.0))))
        self.assertTrue(_warns(res, "mixes negative and positive"))
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(len(pts), 3)      # the -0.2 point dropped
        self.assertAlmostEqual(pts[1][0], math.exp(0.05) - 1.0, places=9)

    def test_all_positive_curve_converts_with_warning(self):
        """dyna2rad creates NO function here (both branches require a
        negative abscissa) — k2rad converts, loudly."""
        res, starter = _convert(_solid_deck(
            _mat005(eps=(0.0, 0.05, 0.10), p=(0.0, 10.0, 20.0))))
        self.assertTrue(_warns(res, "every pressure-curve abscissa"))
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertAlmostEqual(pts[1][0], math.exp(0.05) - 1.0, places=9)

    def test_no_points_warns_func_zero(self):
        res, starter = _convert(_solid_deck(_mat005(eps=(), p=())))
        self.assertTrue(_warns(res, "no usable pressure-curve points"))
        cards = _cards(_block(starter, "/MAT/LAW21/7"))
        self.assertEqual(_col_i(cards[3], 1, 10), 0)

    def test_pc_positive_warns(self):
        res, _ = _convert(_solid_deck(_mat005(pc=0.05)))
        self.assertTrue(_warns(res, "PC=0.05 is POSITIVE"))

    def test_pc_blank_semantic_flip_warns(self):
        """LS-DYNA PC=0 is an ACTIVE zero-tension floor (Remark 1: pressure
        below the cutoff is reset to it); LAW21 P_min=0 becomes -INFINITY
        (unlimited tension) — the most common card state, warned."""
        res, starter = _convert(_solid_deck(_mat005(pc=0.0)))
        self.assertTrue(_warns(res, "PC is 0/blank"))
        cards = _cards(_block(starter, "/MAT/LAW21/7"))
        self.assertEqual(_col_f(cards[4], 1, 20), 0.0)     # still verbatim
        res2, _ = _convert(_solid_deck(_mat005()))         # pc=-0.05 default
        self.assertFalse(_warns(res2, "PC is 0/blank"))

    def test_nu_clamp_warns_when_it_fires(self):
        """G > 1.5*KUN drives (3K-2G)/(6K+2G) negative — clamped to 0 AND
        warned (dyna2rad clamps silently); the normal G/KUN pair stays
        unwarned."""
        res, starter = _convert(_solid_deck(_mat005(g=900.0, kun=500.0)))
        hits = _warns(res, "CLAMPED")
        self.assertTrue(hits)
        self.assertIn("outside the [0, 0.495]", hits[0])
        cards = _cards(_block(starter, "/MAT/LAW21/7"))
        self.assertEqual(_col_f(cards[1], 21, 40), 0.0)
        res2, _ = _convert(_solid_deck(_mat005()))
        self.assertFalse(_warns(res2, "CLAMPED"))

    def test_huge_abscissa_dropped_not_crashed(self):
        """|EPS| > 700 would overflow exp() — dropped with a warning naming
        the wrong-curve suspicion instead of aborting the conversion."""
        res, starter = _convert(_solid_deck(
            _mat005(lcid=334, eps=(0.0,), p=(0.0,)),
            _curve(334, ((0.0, 0.0), (-0.1, 10.0), (-800.0, 99.0)))))
        self.assertTrue(_warns(res, "|EPS| > 700"))
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(len(pts), 2)                      # the -800 dropped
        self.assertAlmostEqual(pts[1][0], math.exp(0.1) - 1.0, places=9)

    def test_duplicate_mu_abscissa_collapsed(self):
        """Two source points folding onto one mu (a pressure step) collapse
        to the LAST ordinate — a /FUNCT cannot carry a vertical step — and
        the collapse is warned."""
        res, starter = _convert(_solid_deck(
            _mat005(eps=(0.0, -0.1, -0.1, -0.2), p=(0.0, 10.0, 15.0, 30.0))))
        self.assertTrue(_warns(res, "duplicated mu abscissa"))
        fn = _block(starter, "/FUNCT/90001")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(len(pts), 3)
        self.assertEqual(pts[1][1], 15.0)                  # keep-last

    def test_ref_flag_without_geometry_warns(self):
        res, _ = _convert(_solid_deck(_mat005(ref=1.0)))
        self.assertTrue(_warns(res, "REF=1 requests stress-free"))

    def test_xref_off_whitelist_warn_skips(self):
        """LAW21 is not in the starter's solid-/XREF law whitelist —
        the part warn-skips NAMING the law, no /XREF emitted."""
        res, starter = _convert(_solid_deck(_mat005(ref=1.0), REF_GEOM))
        hits = _warns(res, "solid-/XREF whitelist")
        self.assertTrue(hits)
        self.assertIn("/MAT/LAW21", hits[0])
        self.assertFalse(_blocks(starter, "/XREF"))

    def test_shell_part_warns_error_3046(self):
        res, _ = _convert(_shell_deck(_mat005()))
        hits = _warns(res, "ERROR 3046")
        self.assertTrue(any("/MAT/LAW21" in w for w in hits))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_LOW_DENSITY_VISCOUS_FOAM (073) -> /MAT/LAW90 [+ /VISC/PRONY]
# ═════════════════════════════════════════════════════════════════════════════

class Mat073Tests(unittest.TestCase):
    """/MAT/LAW90 layout (LAW90.cfg FORMAT(radioss2022)): C1 Rho_I / C2
    E0(1-20) Nu(21-40) / C3 NL(1-10) Ismooth(11-20) Fcut(21-40) Shape(41-60)
    Hys(61-80) Alpha(81-100) / NL rows fct_IDL(1-10) Eps_dot(11-30)
    Fscale(31-50); + /VISC/PRONY of the SAME id."""

    def test_card_layout(self):
        _, starter = _convert(_solid_deck(_mat073(), LC073))
        cards = _cards(_block(starter, "/MAT/LAW90/7"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 5.0e-11)
        self.assertEqual(_col_f(cards[1], 1, 20), 0.5)     # E -> E0
        self.assertEqual(_col_f(cards[1], 21, 40), 0.0)    # no PR on MAT_073
        self.assertEqual(_col_i(cards[2], 1, 10), 1)       # NL = 1
        self.assertEqual(_col_i(cards[2], 11, 20), 1)      # Ismooth = 1 (d2r)
        self.assertEqual(_col_f(cards[2], 21, 40), 0.0)    # Fcut
        self.assertEqual(_col_f(cards[2], 41, 60), 2.0)    # SHAPE -> Shape
        self.assertEqual(_col_f(cards[2], 61, 80), 0.2)    # HU -> Hys
        self.assertEqual(_col_f(cards[2], 81, 100), 0.0)   # Alpha -> 1.0
        self.assertEqual(_col_i(cards[3], 1, 10), 300)     # LCID by id
        self.assertEqual(_col_f(cards[3], 11, 30), 0.0)    # quasi-static rate
        self.assertEqual(_col_f(cards[3], 31, 50), 0.0)    # Fscale -> 1.0

    def test_visc_prony_same_id(self):
        _, starter = _convert(_solid_deck(_mat073(), LC073))
        blk = _block(starter, "/VISC/PRONY/7")
        rows = [ln for ln in blk[1:] if not ln.startswith("#")]
        self.assertEqual(_col_i(rows[0], 1, 10), 2)        # M = 2
        self.assertEqual(_col_f(rows[1], 1, 20), 0.12)     # G_1
        self.assertEqual(_col_f(rows[1], 21, 40), 800.0)   # Beta_1
        self.assertEqual(_col_f(rows[2], 1, 20), 0.06)
        self.assertEqual(_col_f(rows[2], 21, 40), 40.0)

    def test_beta_nonpositive_terms_filtered(self):
        res, starter = _convert(_solid_deck(
            _mat073(prony=((0.12, 800.0, ""), (0.03, 0.0, ""))), LC073))
        blk = _block(starter, "/VISC/PRONY/7")
        rows = [ln for ln in blk[1:] if not ln.startswith("#")]
        self.assertEqual(_col_i(rows[0], 1, 10), 1)
        self.assertTrue(_warns(res, "BETAi <= 0"))

    def test_no_prony_terms_no_block(self):
        _, starter = _convert(_solid_deck(_mat073(prony=()), LC073))
        self.assertFalse(_blocks(starter, "/VISC/PRONY"))

    def test_blank_hu_and_shape_default_to_one(self):
        """LS-DYNA blank HU/SHAPE = 1.0 — a bare to_float would turn them
        into 0, which flips LAW90 into a different unloading regime."""
        _, starter = _convert(_solid_deck(_mat073(hu="", shape=""), LC073))
        cards = _cards(_block(starter, "/MAT/LAW90/7"))
        self.assertEqual(_col_f(cards[2], 41, 60), 1.0)
        self.assertEqual(_col_f(cards[2], 61, 80), 1.0)

    def test_lcid2_fit_branch_warns_and_drops_prony(self):
        res, starter = _convert(_solid_deck(
            _mat073(lcid2=350, bstart=0.01, nv=4, prony=()), LC073))
        self.assertTrue(_warns(res, "LCID2=350"))
        self.assertTrue(_warns(res, "RATE-INDEPENDENT"))
        self.assertFalse(_blocks(starter, "/VISC/PRONY"))

    def test_lcid2_minus1_branch_consumes_card_and_warns(self):
        """The LCID3/LCID4 card must be consumed — and never misread as a
        Gi/BETAi pair (curve ids as moduli)."""
        res, starter = _convert(_solid_deck(
            _mat073(lcid2=-1, prony=(), tail=((301, 302, 1.0, 1.0),)), LC073))
        self.assertTrue(_warns(res, "frequency-data"))
        self.assertFalse(_blocks(starter, "/VISC/PRONY"))

    def test_dropped_fields_warn(self):
        res, _ = _convert(_solid_deck(
            _mat073(tc=0.4, beta=1.5, damp=0.08, fail=1.0, bvflag=1.0,
                    kcon=2.0), LC073))
        for needle in ("TC=0.4", "BETA=1.5", "DAMP=0.08", "FAIL=1",
                       "BVFLAG=1", "KCON=2"):
            with self.subTest(needle=needle):
                self.assertTrue(_warns(res, needle))
        # Tcut/FAIL/Kcont are radioss2026-only fields — the warnings say so.
        self.assertTrue(_warns(res, "radioss2026"))

    def test_blank_damp_still_warns_the_default(self):
        """A blank DAMP is LS-DYNA's 0.05 default damping — dropped physics
        either way, so the warning names the default explicitly."""
        res, _ = _convert(_solid_deck(_mat073(), LC073))
        self.assertTrue(_warns(res, "DAMP=0.05 (the LS-DYNA default"))

    def test_missing_loading_curve_warns_error_126(self):
        res, _ = _convert(_solid_deck(_mat073(lcid=0)))
        self.assertTrue(_warns(res, "ERROR 126"))

    def test_xref_whitelisted_law90_receives_block(self):
        """LAW90 IS on the starter's solid-/XREF whitelist — the MAT_073
        part receives the /XREF and its solid section flips to Ismstr=10."""
        res, starter = _convert(_solid_deck(_mat073(), LC073 + REF_GEOM))
        self.assertTrue(_blocks(starter, "/XREF"))
        prop = _cards(_block(starter, "/PROP/SOLID/7"))
        self.assertEqual(_col_i(prop[0], 11, 20), 10)      # Ismstr = 10
        self.assertFalse(_warns(res, "solid-/XREF whitelist"))

    def test_ismstr10_pinned_without_reference_geometry(self):
        """dyna2rad pins Ismstr=10 on every MAT_073 solid property
        UNCONDITIONALLY (CP:484-495) — not only on the /XREF path; LAW90
        is a total-strain law. A MAT_073 deck with NO reference geometry
        must still emit Ismstr=10."""
        _, starter = _convert(_solid_deck(_mat073(), LC073))
        self.assertFalse(_blocks(starter, "/XREF"))
        prop = _cards(_block(starter, "/PROP/SOLID/7"))
        self.assertEqual(_col_i(prop[0], 11, 20), 10)      # Ismstr = 10

    def test_shell_part_warns_error_3046(self):
        res, _ = _convert(_shell_deck(_mat073(), LC073))
        hits = _warns(res, "ERROR 3046")
        self.assertTrue(any("/MAT/LAW90" in w for w in hits))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_MODIFIED_HONEYCOMB (126) -> /MAT/LAW50 + /PROP/TYPE6
# ═════════════════════════════════════════════════════════════════════════════

class Mat126Tests(unittest.TestCase):
    """/MAT/LAW50 layout (mat_law50.cfg FORMAT(radioss90), the block a
    /BEGIN 2022 deck reads — 24 cards, no compaction card): RHO_I; E11 E22
    E33; G12 G23 G31; asrate; [Iflag1(1-10) Eps_max11(11-30) ..22(31-50)
    ..33(51-70)]; per direction funID x5 (10 cols) / Fscale x5 (20) /
    Eps_rate x5 (20); [Iflag2 + shear Eps_max]; shear directions. Slot order
    11/22/33/12/23/31 (hm_read_mat50.F90:308-315)."""

    def test_card_layout_normal_variant(self):
        res, starter = _convert(_solid_deck(_mat126(), CRVS126))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        # moduli a/b/c -> 11/22/33, identity map
        self.assertEqual(_col_f(cards[1], 1, 20), 0.5)     # EAAU
        self.assertEqual(_col_f(cards[1], 21, 40), 0.6)    # EBBU
        self.assertEqual(_col_f(cards[1], 41, 60), 0.7)    # ECCU
        self.assertEqual(_col_f(cards[2], 1, 20), 0.2)     # GABU
        self.assertEqual(_col_f(cards[2], 21, 40), 0.25)   # GBCU
        self.assertEqual(_col_f(cards[2], 41, 60), 0.3)    # GCAU
        self.assertEqual(_col_f(cards[3], 1, 20), 0.0)     # asrate
        # Iflag1 card: -1 (yield vs -strain), Eps_max = TSEF
        self.assertEqual(_col_i(cards[4], 1, 10), -1)
        self.assertEqual(_col_f(cards[4], 11, 30), 0.08)
        self.assertEqual(_col_f(cards[4], 31, 50), 0.08)
        self.assertEqual(_col_f(cards[4], 51, 70), 0.08)
        # direction blocks: funID row, Fscale row, Eps_rate row per direction
        fun_rows = cards[5::3][:3] + cards[15::3][:3]
        self.assertEqual([_col_i(r, 1, 10) for r in fun_rows[:3]],
                         [401, 402, 403])                  # LCA LCB LCC
        # Iflag2 card sits at index 14: -1 + SSEF
        self.assertEqual(_col_i(cards[14], 1, 10), -1)
        self.assertEqual(_col_f(cards[14], 11, 30), 0.12)
        shear_rows = cards[15::3][:3]
        self.assertEqual([_col_i(r, 1, 10) for r in shear_rows],
                         [405, 406, 407])                  # LCAB LCBC LCCA
        # single (static) slot: Fscale1=1.0, Eps_rate1=0
        self.assertEqual(_col_f(cards[6], 1, 20), 1.0)
        self.assertEqual(_col_f(cards[7], 1, 20), 0.0)
        self.assertEqual(_col_i(cards[5], 11, 20), 0)      # slot 2 empty
        self.assertTrue(_warns(res, "compaction card"))

    def test_modulus_fallbacks(self):
        """Blank EBBU -> E; blank GBCU -> E/2(1+PR) = 500/2.5 = 200."""
        _, starter = _convert(_solid_deck(
            _mat126(ebbu="", gbcu=""), CRVS126))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        self.assertEqual(_col_f(cards[1], 21, 40), 500.0)
        self.assertEqual(_col_f(cards[2], 21, 40), 200.0)

    def test_curve_fallback_chain(self):
        """LCB/LCC default to LCA; LCS defaults to LCA; LCAB/LCBC/LCCA
        default to LCS — the LS-DYNA defaults dyna2rad reproduces."""
        _, starter = _convert(_solid_deck(
            _mat126(lcb="", lcc="", lcs=404, lcab="", lcbc="", lcca=""),
            CRVS126))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        fun_norm = [_col_i(r, 1, 10) for r in cards[5::3][:3]]
        fun_shear = [_col_i(r, 1, 10) for r in cards[15::3][:3]]
        self.assertEqual(fun_norm, [401, 401, 401])
        self.assertEqual(fun_shear, [404, 404, 404])

    def test_lcsr_five_point_sampling(self):
        """The curve's FIRST FIVE points (dyna2rad's MODIFIED rule,
        CM:9017-9021: curvePnts[8]/[9] = point 5); funID replicated per
        rate with Fscale = the ordinate. The 6-point curve DISCRIMINATES
        the rules: the plain MAT_026 rule (first 4 + the LAST point) would
        emit 1000.0 in the 5th rate slot — asserted absent."""
        lcsr_crv = _curve(408, ((0.001, 1.0), (0.1, 1.1), (1.0, 1.2),
                                (10.0, 1.3), (100.0, 1.4), (1000.0, 1.5)))
        res, starter = _convert(_solid_deck(
            _mat126(lcsr=408), CRVS126 + lcsr_crv))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        fun_row, fsc_row, eps_row = cards[5], cards[6], cards[7]
        self.assertEqual([_col_i(fun_row, 1 + 10 * i, 10 + 10 * i)
                          for i in range(5)], [401] * 5)
        self.assertEqual([_col_f(fsc_row, 1 + 20 * i, 20 + 20 * i)
                          for i in range(5)], [1.0, 1.1, 1.2, 1.3, 1.4])
        self.assertEqual([_col_f(eps_row, 1 + 20 * i, 20 + 20 * i)
                          for i in range(5)], [0.001, 0.1, 1.0, 10.0, 100.0])
        self.assertNotIn("1000", eps_row)                  # not first-4+LAST
        self.assertTrue(_warns(res, "FIRST FIVE points"))

    def test_lcsr_minus1_drops_rate_data_loudly(self):
        res, starter = _convert(_solid_deck(
            _mat126(lcsr=-1.0, extra_cards=((411, 412, 413, 414, 415, 416),)),
            CRVS126))
        self.assertTrue(_warns(res, "LCSR=-1"))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        self.assertEqual(_col_i(cards[5], 11, 20), 0)      # no rate slots

    def test_vv0_first_abscissa_transform(self):
        """A curve starting at x>0 is stress vs V/V0: abscissae -> 1 - x,
        re-sorted, as a NEW /FUNCT; the original curve stays unchanged."""
        vv0 = _curve(409, ((1.0, 5.0), (0.7, 8.0)))
        res, starter = _convert(_solid_deck(
            _mat126(lca=409, lcb=402, lcc=403), CRVS126 + vv0))
        self.assertTrue(_warns(res, "RELATIVE VOLUME V/V0"))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        fid = _col_i(cards[5], 1, 10)
        self.assertNotEqual(fid, 409)
        fn = _block(starter, f"/FUNCT/{fid}")
        pts = [(_col_f(ln, 1, 20), _col_f(ln, 21, 40))
               for ln in fn[3:] if not ln.startswith("#")]
        self.assertEqual(pts[0], (0.0, 5.0))
        self.assertAlmostEqual(pts[1][0], 0.3, places=9)
        self.assertEqual(pts[1][1], 8.0)
        # the original curve is still emitted untouched
        orig = _block(starter, "/FUNCT/409")
        self.assertEqual(_col_f([ln for ln in orig[3:]
                                 if not ln.startswith("#")][0], 1, 20), 1.0)

    def test_lca_negative_variant_remap(self):
        """LCA<0: fun11<-LCB, fun22=fun33<-LCC, shears<-LCS; E22=E33=EBBU,
        G12=GBCU, G23=G31=GABU; Iflag1=0, Iflag2=1 — dyna2rad's remap,
        warned as an approximation (damage curves become yield curves)."""
        res, starter = _convert(_solid_deck(
            _mat126(lca=-401, eccu=-0.7), CRVS126))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        self.assertEqual(_col_f(cards[1], 1, 20), 0.5)     # E11 = EAAU
        self.assertEqual(_col_f(cards[1], 21, 40), 0.6)    # E22 = EBBU
        self.assertEqual(_col_f(cards[1], 41, 60), 0.6)    # E33 = EBBU
        self.assertEqual(_col_f(cards[2], 1, 20), 0.25)    # G12 = GBCU
        self.assertEqual(_col_f(cards[2], 21, 40), 0.2)    # G23 = GABU
        self.assertEqual(_col_f(cards[2], 41, 60), 0.2)    # G31 = GABU
        self.assertEqual(_col_i(cards[4], 1, 10), 0)       # Iflag1
        self.assertEqual(_col_i(cards[14], 1, 10), 1)      # Iflag2
        fun_norm = [_col_i(r, 1, 10) for r in cards[5::3][:3]]
        fun_shear = [_col_i(r, 1, 10) for r in cards[15::3][:3]]
        self.assertEqual(fun_norm, [402, 403, 403])        # LCB, LCC, LCC
        self.assertEqual(fun_shear, [404, 404, 404])       # LCS everywhere
        self.assertTrue(_warns(res, "transversely isotropic"))
        self.assertTrue(_warns(res, "THIRD yield surface"))

    def test_prop_type6_with_skew_and_part_repointed(self):
        """AOPT=2 (a=(1,0,0), d=(0,1,0)) -> /SKEW/FIX with Y'=(0,1,0),
        Z'=(0,0,1); the /PART repoints at the /PROP/TYPE6 and the unused
        isotropic /PROP/SOLID is suppressed. Card 1 pins Isolid=1 +
        Ismstr=1 (dyna2rad CP:415/472): MAT_126's yield curves are
        ENGINEERING strain for the default corotational elements, which
        only a small-strain Radioss solid preserves — the ELFORM-derived
        Isolid=17/Ismstr=0(->4) evaluated them at LOG strain (measured
        28% early densification onset for a knee at 0.70)."""
        res, starter = _convert(_solid_deck(_mat126(), CRVS126))
        prop = _block(starter, "/PROP/TYPE6/")
        prop_id = int(prop[0].rsplit("/", 1)[1])
        prow = _cards(prop)
        self.assertEqual(_col_i(prow[0], 1, 10), 1)        # Isolid = 1
        self.assertEqual(_col_i(prow[0], 11, 20), 1)       # Ismstr = 1
        skew_id = _col_i(prow[2], 61, 70)
        self.assertGreater(skew_id, 0)
        self.assertEqual(_col_i(prow[2], 71, 80), 0)       # Ip=0 with skew
        skew = _block(starter, f"/SKEW/FIX/{skew_id}")
        srows = [ln for ln in skew[2:] if not ln.startswith("#")]
        self.assertEqual((_col_f(srows[1], 1, 20), _col_f(srows[1], 21, 40),
                          _col_f(srows[1], 41, 60)), (0.0, 1.0, 0.0))  # Y'
        self.assertEqual((_col_f(srows[2], 1, 20), _col_f(srows[2], 21, 40),
                          _col_f(srows[2], 41, 60)), (0.0, 0.0, 1.0))  # Z'
        part = _block(starter, "/PART/7")
        pcard = [ln for ln in part[2:] if not ln.startswith("#")][0]
        self.assertEqual(_col_i(pcard, 1, 10), prop_id)
        self.assertFalse(_blocks(starter, "/PROP/SOLID/7"))
        self.assertTrue(_warns(res, "SMORTH3"))

    def test_aopt3_vector_card_parses_to_ip23(self):
        """AOPT=3 pulls the conditional V card; Ip=23 with v on Vx/Vy/Vz."""
        _, starter = _convert(_solid_deck(
            _mat126(aopt=3.0, extra_cards=((0.0, 0.0, 1.0),)), CRVS126))
        prow = _cards(_block(starter, "/PROP/TYPE6/"))
        self.assertEqual(_col_i(prow[2], 71, 80), 23)
        self.assertEqual(_col_f(prow[2], 41, 60), 1.0)     # Vz
        self.assertEqual(_col_i(prow[2], 61, 70), 0)       # no skew

    def test_shell_part_refused(self):
        res, starter = _convert(_shell_deck(_mat126(), CRVS126))
        self.assertTrue(_warns(res, "SOLID-ONLY law"))
        self.assertFalse(_blocks(starter, "/PROP/TYPE6/"))

    def test_dropped_fields_warn(self):
        res, _ = _convert(_solid_deck(
            _mat126(mu=0.05, bulk=1.0, sigy=3.0, vf=0.1,
                    card4=("", "", "", 1.0, 0.0, 0.0, 2.0, 1.0),
                    card5=(0.0, 1.0, 0.0, -0.08, -0.12, 1.0, 2.0, 1.0),
                    extra_cards=((0.3, 0.3, 0.3, 0.3, 0.3, 0.3),)),
            CRVS126))
        for needle in ("viscosity coefficient MU=0.05", "bulk-viscosity",
                       "compaction card", "VREF=1", "TREF=2", "SHDFLG=1",
                       "RFAC=2", "PRU=1", "TSEF=-0.08", "SSEF=-0.12"):
            with self.subTest(needle=needle):
                self.assertTrue(_warns(res, needle))

    def test_dangling_yield_curve_slots_empty(self):
        res, starter = _convert(_solid_deck(_mat126(lca=499, lcb=402,
                                                    lcc=403), CRVS126))
        self.assertTrue(_warns(res, "yield curve 499"))
        cards = _cards(_block(starter, "/MAT/LAW50/7"))
        self.assertEqual(_col_i(cards[5], 1, 10), 0)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_DESHPANDE_FLECK_FOAM (154) -> /MAT/LAW115
# ═════════════════════════════════════════════════════════════════════════════

class Mat154Tests(unittest.TestCase):
    """/MAT/LAW115 layout (matl115_deshfleck.cfg FORMAT(radioss2021),
    Istat=0 branch): C1 RHO_I / C2 E(1-20) nu(21-40) Ires(41-50)
    Istat(51-60) / C3 ALPHA EPSVP_F SIGP_F / C4 SIGP GAMMA EPSD ALPHA2
    BETA. The hardening constants transfer verbatim — identical flow law."""

    def test_card_layout(self):
        _, starter = _convert(_solid_deck(_mat154()))
        cards = _cards(_block(starter, "/MAT/LAW115/7"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 2.7e-10)
        self.assertEqual(_col_f(cards[1], 1, 20), 1000.0)
        self.assertEqual(_col_f(cards[1], 21, 40), 0.05)
        self.assertEqual(_col_i(cards[1], 41, 50), 0)      # Ires -> Newton
        self.assertEqual(_col_i(cards[1], 51, 60), 0)      # Istat = 0
        self.assertEqual(_col_f(cards[2], 1, 20), 1.5)     # ALPHA
        self.assertEqual(_col_f(cards[2], 21, 40), 0.1)    # CFAIL -> EPSVP_F
        self.assertEqual(_col_f(cards[2], 41, 60), 25.0)   # PFAIL -> SIGP_F
        self.assertEqual(_col_f(cards[3], 1, 20), 1.2)     # SIGP
        self.assertEqual(_col_f(cards[3], 21, 40), 2.0)    # GAMMA
        self.assertEqual(_col_f(cards[3], 41, 60), 1.6)    # EPSD
        self.assertEqual(_col_f(cards[3], 61, 80), 40.0)   # ALPHA2
        self.assertEqual(_col_f(cards[3], 81, 100), 3.0)   # BETA

    def test_pfail_fix_over_dyna2rad(self):
        """d2r's cfg has no PFAIL attribute -> its SIGP_F is silently always
        0; k2rad carries the value AND warns about the NUM semantics gap
        (LS-DYNA needs NUM sustained steps, Radioss fails on the first)."""
        res, starter = _convert(_solid_deck(_mat154(pfail=25.0, num=500)))
        cards = _cards(_block(starter, "/MAT/LAW115/7"))
        self.assertEqual(_col_f(cards[2], 41, 60), 25.0)
        hits = _warns(res, "NUM=500")
        self.assertTrue(hits)
        self.assertIn("FIRST violation", hits[0])

    def test_derfi_warns(self):
        res, _ = _convert(_solid_deck(_mat154(derfi=1.0)))
        self.assertTrue(_warns(res, "DERFI=1"))

    def test_starter_bound_checks_pre_warned(self):
        res, _ = _convert(_solid_deck(_mat154(alpha=2.5, pr=0.6)))
        self.assertTrue(_warns(res, "ERROR 1897"))
        self.assertTrue(_warns(res, "ERROR 49"))

    def test_hex_isolid_routed_to_24(self):
        """LAW115 on the ELFORM-derived full-integration Isolid=17 is
        ENGINE-fatal (dt collapses below DTMIN at cycle 0, 1-cycle 'NORMAL
        TERMINATION' with an empty result — measured), so the /PROP/SOLID
        of a MAT_154 hex part is emitted with Isolid=24 (HEPH, dyna2rad's
        own hex default), announced with the mechanism named."""
        res, starter = _convert(_solid_deck(_mat154()))
        prop = _cards(_block(starter, "/PROP/SOLID/7"))
        self.assertEqual(_col_i(prop[0], 1, 10), 24)       # Isolid = 24
        hits = _warns(res, "UNRUNNABLE")
        self.assertTrue(hits)
        self.assertIn("Isolid=24", hits[0])
        self.assertIn("NORMAL TERMINATION after 1 cycle", hits[0])

    def test_tet_formulation_left_with_warning(self):
        """A MAT_154 TET part (ELFORM 10 -> Isolid 14) is NOT remapped —
        only the measured-fatal hex 17 is — but the WARNING-1905 window
        pre-announcement survives, telling the user to verify the engine
        time step."""
        tet = ("*ELEMENT_SOLID\n" + _row(1, 7)
               + "\n" + _row(1, 2, 3, 5, 5, 5, 5, 5) + "\n")
        deck = (NODES + tet + PART
                + "*SECTION_SOLID\n" + _row(7, 10) + "\n"
                + _mat154() + END)
        res, starter = _convert(deck)
        prop = _cards(_block(starter, "/PROP/SOLID/7"))
        self.assertEqual(_col_i(prop[0], 1, 10), 14)       # tet Isolid kept
        hits = _warns(res, "WARNING 1905")
        self.assertTrue(hits)
        self.assertIn("VERIFY", hits[0])
        self.assertFalse(_warns(res, "UNRUNNABLE"))

    def test_shared_section_drag_warned(self):
        """A non-LAW115 part sharing the *SECTION_SOLID switches to
        Isolid=24 along with the foam part — warned by name."""
        deck = (NODES + SOLID + PART
                + "*NODE\n" + "".join(
                    f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                        (21, 0.0, 0.0, 30.0), (22, 10.0, 0.0, 30.0),
                        (23, 10.0, 10.0, 30.0), (24, 0.0, 10.0, 30.0),
                        (25, 0.0, 0.0, 40.0), (26, 10.0, 0.0, 40.0),
                        (27, 10.0, 10.0, 40.0), (28, 0.0, 10.0, 40.0)))
                + "*ELEMENT_SOLID\n" + _row(2, 8) + "\n"
                + _row(*range(21, 29)) + "\n"
                + "*PART\nsteel\n" + _row(8, 7, 8) + "\n"   # same SECID 7
                + "*MAT_ELASTIC\n" + _row(8, "7.8E-9", 210000.0, 0.3) + "\n"
                + SEC + _mat154() + END)
        res, starter = _convert(deck)
        prop = _cards(_block(starter, "/PROP/SOLID/7"))
        self.assertEqual(_col_i(prop[0], 1, 10), 24)
        hits = _warns(res, "share a *SECTION_SOLID with a LAW115")
        self.assertTrue(hits)
        self.assertIn("[8]", hits[0])

    def test_pre_r61_short_card2(self):
        """The pre-R6.1 card 2 stops after CFAIL: PFAIL reads 0 (no
        principal-stress failure), NUM keeps its 1000 default silently."""
        mat = ("*MAT_DESHPANDE_FLECK_FOAM\n"
               + _row(7, "2.7E-10", 1000.0, 0.05, 1.5, 2.0) + "\n"
               + _row(1.6, 40.0, 3.0, 1.2, 0.0, 0.1) + "\n")
        res, starter = _convert(_solid_deck(mat))
        cards = _cards(_block(starter, "/MAT/LAW115/7"))
        self.assertEqual(_col_f(cards[2], 41, 60), 0.0)
        self.assertFalse(_warns(res, "NUM="))

    def test_shell_part_warns_error_3046(self):
        res, _ = _convert(_shell_deck(_mat154()))
        hits = _warns(res, "ERROR 3046")
        self.assertTrue(any("/MAT/LAW115" in w for w in hits))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_HILL_FOAM (177) -> /MAT/LAW62
# ═════════════════════════════════════════════════════════════════════════════

class Mat177Tests(unittest.TestCase):
    """/MAT/LAW62 layout (matl62_visc_hyp.cfg FORMAT(radioss2022)): C1 RHO_I
    / C2 Nu(1-20) N(21-30) M(31-40) mu_max(41-60) Flag_Visc(61-70)
    Flag_Rigi(71-80) / CELL_LIST blocks of 5 x 20 columns: mu_i, alpha_i,
    nu_i (the 2022-format block the starter reads even though the 2022
    Reference Guide omits it — emitted as zeros so the card-2 Nu stays in
    charge)."""

    def test_card_layout(self):
        _, starter = _convert(_solid_deck(_mat177()))
        cards = _cards(_block(starter, "/MAT/LAW62/7"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 1.0e-10)
        # Nu = N/(1+2N) = 0.5/2 = 0.25 exact
        self.assertEqual(_col_f(cards[1], 1, 20), 0.25)
        self.assertEqual(_col_i(cards[1], 21, 30), 2)      # N = nonzero C's
        self.assertEqual(_col_i(cards[1], 31, 40), 0)      # M = 0
        self.assertEqual(_col_f(cards[1], 41, 60), 0.0)    # mu_max -> 1e20
        self.assertEqual(_col_i(cards[1], 61, 70), 0)      # Flag_Visc
        self.assertEqual(_col_i(cards[1], 71, 80), 0)      # Flag_Rigi
        # mu_i = Ci*Bi/2: 0.8*4/2 = 1.6 and 0.4*2/2 = 0.4
        self.assertEqual(_col_f(cards[2], 1, 20), 1.6)
        self.assertEqual(_col_f(cards[2], 21, 40), 0.4)
        # alpha_i = Bi
        self.assertEqual(_col_f(cards[3], 1, 20), 4.0)
        self.assertEqual(_col_f(cards[3], 21, 40), 2.0)
        # nu_i block: zeros
        self.assertEqual(_col_f(cards[4], 1, 20), 0.0)
        self.assertEqual(_col_f(cards[4], 21, 40), 0.0)
        self.assertEqual(len(cards), 5)

    def test_pair_alignment_fix_over_dyna2rad(self):
        """C2 is zero mid-list: k2rad pairs C3 with B3 (0.4*2/2 = 0.4,
        alpha=2) — dyna2rad's independent compaction would pair C3 with B2=5
        (mu = 1.0, alpha = 5), a different material."""
        _, starter = _convert(_solid_deck(_mat177()))
        cards = _cards(_block(starter, "/MAT/LAW62/7"))
        self.assertEqual(_col_f(cards[2], 21, 40), 0.4)
        self.assertEqual(_col_f(cards[3], 21, 40), 2.0)

    def test_five_per_line_wrap(self):
        _, starter = _convert(_solid_deck(_mat177(
            c=(0.2, 0.2, 0.2, 0.2, 0.2, 0.2, "", ""),
            b=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, "", ""))))
        cards = _cards(_block(starter, "/MAT/LAW62/7"))
        self.assertEqual(_col_i(cards[1], 21, 30), 6)
        # mu_i rows: 5 cells then 1 cell
        self.assertEqual(len(cards[2].rstrip()), 100)
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 0.6, places=9)
        # alpha rows follow at cards[4]/[5], nu rows at [6]/[7]
        self.assertEqual(_col_f(cards[4], 81, 100), 5.0)
        self.assertEqual(_col_f(cards[5], 1, 20), 6.0)
        self.assertEqual(len(cards), 8)

    def test_zero_b_with_nonzero_c_warns(self):
        res, _ = _convert(_solid_deck(_mat177(
            c=(0.8, 0.4, "", "", "", "", "", ""),
            b=(4.0, "", "", "", "", "", "", ""))))
        self.assertTrue(_warns(res, "ZERO B"))

    def test_lcid_fit_branch_skips_loudly(self):
        """LCID>0 has no LAW62 counterpart (no fit path) — dyna2rad silently
        wires mat_ID 0; k2rad skips with the warning and emits no /MAT."""
        mat = ("*MAT_HILL_FOAM\n"
               + _row(7, "1.0E-10", 100.0, 0.5, "", 340, 1, "") + "\n")
        res, starter = _convert(_solid_deck(
            mat, _curve(340, ((1.0, 0.0), (1.5, 12.0)))))
        self.assertTrue(_warns(res, "curve-fit branch"))
        self.assertFalse(_blocks(starter, "/MAT/LAW62"))
        state = _dispatch(_solid_deck(mat))
        self.assertNotIn(7, state.mat_hill_foam)

    def test_dropped_fields_warn(self):
        res, _ = _convert(_solid_deck(_mat177(k=100.0, mu=0.1, lcsr=341,
                                              rm=(2.0, 4.0))))
        for needle in ("bulk modulus K=100", "MU=0.1", "LCSR=341",
                       "Mullins-effect card (R=2, M=4)"):
            with self.subTest(needle=needle):
                self.assertTrue(_warns(res, needle))

    def test_shell_part_is_allowed(self):
        """LAW62 declares SHELL_ISOTROPIC (hm_read_mat62.F:273) — the only
        shell-capable law of the batch; no 3046-class warning fires."""
        res, starter = _convert(_shell_deck(_mat177()))
        self.assertFalse(_warns(res, "ERROR 3046"))
        self.assertTrue(_blocks(starter, "/MAT/LAW62/7"))


# ═════════════════════════════════════════════════════════════════════════════
# *CONTACT_INTERIOR -> Icontrol (resolved, warned, not emitted)
# ═════════════════════════════════════════════════════════════════════════════

class ContactInteriorTests(unittest.TestCase):
    """The measured version gate: Icontrol exists only in the radioss2025
    property format; under /BEGIN 2022 the starter reads the trailing card
    as 'Ndir sphpartID' only (ICONTROL echo 0 + WARNING 100213), so nothing
    is emitted and the parts are NAMED in the warnings."""

    def _deck(self, sets, mat=None):
        return _solid_deck(mat or _mat073(), LC073 + sets)

    def test_direct_set_resolution_and_note(self):
        sets = ("*SET_PART_LIST\n" + _row(51) + "\n" + _row(7) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(51) + "\n")
        res, starter = _convert(self._deck(sets))
        hits = _warns(res, "*CONTACT_INTERIOR (set 51")
        self.assertTrue(any("[7]" in w and "ICONTROL 0" in w
                            and "WARNING 100213" in w for w in hits))
        self.assertIn("*CONTACT_INTERIOR",
                      [kw for kw, _ in res.recognized_not_emitted])
        self.assertNotIn("Icontrol", starter)
        self.assertEqual(res.skipped_keywords, [])

    def test_set_part_add_expands_and_names_dangling_member(self):
        sets = ("*SET_PART_LIST\n" + _row(51) + "\n" + _row(7) + "\n"
                + "*SET_PART_ADD\n" + _row(52) + "\n" + _row(51, 53) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(52) + "\n")
        res, _ = _convert(self._deck(sets))
        hits = _warns(res, "*CONTACT_INTERIOR (set 52")
        self.assertTrue(any("[7]" in w for w in hits))
        self.assertTrue(any("[53]" in w for w in
                           _warns(res, "member set id(s)")))

    def test_unresolved_psid_warns(self):
        res, _ = _convert(self._deck(
            "*CONTACT_INTERIOR\n" + _row(99) + "\n"))
        self.assertTrue(_warns(res, "part set 99 is not defined"))

    def test_non_solid_parts_named(self):
        """A shell part in the PSID: its property type has no Icontrol
        field at ANY format version — named separately."""
        deck = (NODES + SOLID + PART + SEC
                + "*NODE\n"
                + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in
                          ((11, 0.0, 0.0, 20.0), (12, 10.0, 0.0, 20.0),
                           (13, 10.0, 10.0, 20.0), (14, 0.0, 10.0, 20.0)))
                + "*ELEMENT_SHELL\n" + _row(2, 8, 11, 12, 13, 14) + "\n"
                + "*PART\nplate\n" + _row(8, 8, 8) + "\n"
                + "*SECTION_SHELL\n" + _row(8, 2, 1.0, 5) + "\n"
                + _row(1.2, 1.2, 1.2, 1.2) + "\n"
                + "*MAT_ELASTIC\n" + _row(8, "7.8E-9", 210000.0, 0.3) + "\n"
                + _mat073() + LC073
                + "*SET_PART_LIST\n" + _row(51) + "\n" + _row(7, 8, 9) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(51) + "\n" + END)
        res, _ = _convert(deck)
        self.assertTrue(any("[7]" in w
                            for w in _warns(res, "arms interior contact")))
        self.assertTrue(any("[8]" in w for w in
                            _warns(res, "NO Icontrol field at ANY")))
        self.assertTrue(any("[9]" in w for w in _warns(res, "no *PART card")))

    def test_set_attributes_warn(self):
        """DA1..DA4 on the referenced set header (the Yaris pattern: the
        *SET_PART_ADD itself carries Fa=0.2): PSF/Fa/ED dropped, TYPE=2
        formulation dropped."""
        sets = ("*SET_PART_LIST\n" + _row(51) + "\n" + _row(7) + "\n"
                + "*SET_PART_ADD\n" + _row(52, 0.5, 0.2, 3.0, 2.0) + "\n"
                + _row(51) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(52) + "\n")
        res, _ = _convert(self._deck(sets))
        attr = _warns(res, "set attribute(s)")
        self.assertTrue(attr)
        self.assertIn("PSF=0.5", attr[0])
        self.assertIn("Fa=0.2", attr[0])
        self.assertIn("ED=3", attr[0])
        self.assertTrue(_warns(res, "TYPE=2"))

    def test_multiple_keyword_instances_accumulate(self):
        sets = ("*SET_PART_LIST\n" + _row(51) + "\n" + _row(7) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(51) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(51, 88) + "\n")
        res, _ = _convert(self._deck(sets))
        self.assertTrue(_warns(res, "*CONTACT_INTERIOR (set 51"))
        self.assertTrue(_warns(res, "part set 88 is not defined"))


class SetPartAddFlattenTests(unittest.TestCase):
    """_flatten_part_set_adds: *SET_PART_ADD becomes a plain part set for
    EVERY consumer, not only *CONTACT_INTERIOR — before it, a contact side
    with SSTYP=2 on an _ADD set silently resolved to an EMPTY /GRNOD with
    a warning blaming the set for naming no parts."""

    def test_contact_side_resolves_through_add_set(self):
        deck = (NODES + SOLID + PART + SEC + _mat073() + LC073
                + "*SET_PART_LIST\n" + _row(61) + "\n" + _row(7) + "\n"
                + "*SET_PART_ADD\n" + _row(62) + "\n" + _row(61) + "\n"
                + "*CONTACT_AUTOMATIC_SINGLE_SURFACE\n"
                + _row(62, 0, 2, 0) + "\n" + _row() + "\n" + _row() + "\n"
                + END)
        res, starter = _convert(deck)
        self.assertFalse(_warns(res, "resolved to no nodes at all"))
        grnods = _blocks(starter, "/GRNOD/NODE/")
        self.assertTrue(any(len([ln for ln in g
                                 if not ln.startswith(("#", "/"))
                                 and ln.strip()]) >= 1 for g in grnods))
        self.assertNotIn("SET_PART_ADD", res.skipped_keywords)

    def test_direct_set_wins_id_collision(self):
        deck = (NODES + SOLID + PART + SEC + _mat073() + LC073
                + "*SET_PART_LIST\n" + _row(61) + "\n" + _row(7) + "\n"
                + "*SET_PART_ADD\n" + _row(61) + "\n" + _row(99) + "\n"
                + END)
        res, _ = _convert(deck)
        hits = _warns(res, "same id")
        self.assertTrue(hits)
        self.assertIn("_ADD block is IGNORED", hits[0])

    def test_nested_add_child_is_expanded_recursively(self):
        """An _ADD whose member is another _ADD resolves in FULL since the
        M2 batch-1 shared resolver replaced the one-level rule (which used to
        warn-drop the nested slice). dyna2rad's set converter recurses without
        a limit too (convertsets.cxx:1248-1277)."""
        deck = (NODES + SOLID + PART + SEC + _mat073() + LC073
                + "*SET_PART_LIST\n" + _row(61) + "\n" + _row(7) + "\n"
                + "*SET_PART_ADD\n" + _row(62) + "\n" + _row(61) + "\n"
                + "*SET_PART_ADD\n" + _row(63) + "\n" + _row(62) + "\n"
                + "*CONTACT_INTERIOR\n" + _row(63) + "\n"
                + END)
        res, _ = _convert(deck)
        self.assertFalse(_warns(res, "exactly ONE level"))
        self.assertFalse(_warns(res, "member set id(s)"))
        # part 7 reached the consumer through TWO levels of union
        self.assertTrue(any("[7]" in w for w in
                            _warns(res, "arms interior contact")))


# ═════════════════════════════════════════════════════════════════════════════
# Cross-cutting: _target_mat_law, registries, multi-material deck, goldens
# ═════════════════════════════════════════════════════════════════════════════

class RegistryTests(unittest.TestCase):

    def test_target_mat_law_entries(self):
        cases = ((_mat005(), 21), (_mat073() + LC073, 90),
                 (_mat126() + CRVS126, 50), (_mat154(), 115),
                 (_mat177(), 62))
        for mat, law in cases:
            with self.subTest(law=law):
                state = _dispatch(_solid_deck(mat))
                self.assertEqual(_target_mat_law(state, 7), law)

    def test_all_mat_ids_covers_foams(self):
        """next_mat_id collision avoidance reads all_mat_ids — a family
        missing there could hand a synthesized material the same id
        (starter ERROR 79)."""
        for mat in (_mat005(), _mat073(), _mat126(), _mat154(), _mat177()):
            state = _dispatch(_solid_deck(mat))
            self.assertIn(7, state.all_mat_ids())

    def test_ref_registry_contains_the_two_ref_bearing_foams(self):
        state = ConversionState()
        kws = [kw for kw, _ in _ref_flag_materials(state)]
        self.assertIn("*MAT_SOIL_AND_FOAM", kws)
        self.assertIn("*MAT_LOW_DENSITY_VISCOUS_FOAM", kws)

    def test_mat073_prony_ref_flag_feeds_registry(self):
        """The per-term REF flag on a Gi/BETAi card folds to mat.ref=1 and
        draws the no-reference-geometry warning through the registry."""
        res, _ = _convert(_solid_deck(
            _mat073(prony=((0.12, 800.0, 1.0),)), LC073))
        hits = _warns(res, "REF=1 requests stress-free")
        self.assertTrue(any("*MAT_LOW_DENSITY_VISCOUS_FOAM" in w
                            for w in hits))

    def test_multi_material_deck(self):
        """All five foams in one deck, each on its own brick part — every
        /MAT header present, ids distinct, nothing skipped."""
        deck = ""
        nid = 0
        for i, mat in enumerate((_mat005(mid=1), _mat073(mid=2),
                                 _mat126(mid=3), _mat154(mid=4),
                                 _mat177(mid=5))):
            pid = i + 1
            deck += "*NODE\n" + "".join(
                f"{nid + k:>8}{x:>16}{y:>16}{z + 20.0 * i:>16}\n"
                for k, (x, y, z) in enumerate(
                    ((0., 0., 0.), (10., 0., 0.), (10., 10., 0.),
                     (0., 10., 0.), (0., 0., 10.), (10., 0., 10.),
                     (10., 10., 10.), (0., 10., 10.)), start=1))
            deck += ("*ELEMENT_SOLID\n" + _row(pid, pid) + "\n"
                     + _row(*range(nid + 1, nid + 9)) + "\n")
            deck += ("*PART\npart\n" + _row(pid, pid, pid) + "\n"
                     + "*SECTION_SOLID\n" + _row(pid, 1) + "\n")
            deck += mat
            nid += 8
        deck = deck + LC073 + CRVS126 + END
        res, starter = _convert(deck)
        for header in ("/MAT/LAW21/1", "/MAT/LAW90/2", "/MAT/LAW50/3",
                       "/MAT/LAW115/4", "/MAT/LAW62/5", "/VISC/PRONY/2",
                       "/PROP/TYPE6/"):
            with self.subTest(header=header):
                self.assertTrue(_blocks(starter, header),
                                f"{header} missing from the converted deck")
        self.assertEqual(res.skipped_keywords, [])
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/MAT/LAW")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_goldens_are_unchanged(self):
        """A pure-addition batch adds no card to a deck that does not use
        the new keywords, so the five checked-in goldens must be
        byte-identical — if one moves, the change leaked into a shared
        emitter. The named risks here are _make_materials (five new loops),
        _composite_material_mids/_assign_composite_props (the MAT_126
        claim), handle_set_part_list (the DA-attribute recording) and the
        build_starter prepass ordering around _resolve_mat_foams."""
        import shutil
        fixtures = Path(__file__).resolve().parent / "fixtures"
        expected = fixtures / "expected"
        for stem in ("shell_explicit", "solid_plastic", "rigid_contact",
                     "tied_weld", "implicit_qstat"):
            with self.subTest(stem=stem):
                with tempfile.TemporaryDirectory() as tmp:
                    dst = os.path.join(tmp, f"{stem}.k")
                    shutil.copy(fixtures / f"{stem}.k", dst)
                    result = convert(dst, write_log=False)
                    for suffix, path in (("0000", result.starter_path),
                                         ("0001", result.engine_path)):
                        produced = Path(path).read_text().replace(
                            "\r\n", "\n").replace(tmp, "<TMPDIR>")
                        golden = (expected / f"{stem}_{suffix}.rad").read_text()
                        self.assertEqual(produced.replace("\r\n", "\n"),
                                         golden.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
