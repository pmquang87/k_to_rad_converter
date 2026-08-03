"""Tests for the VISCOELASTIC BATCH conversions:

  *MAT_VISCOELASTIC (006)                     -> /MAT/LAW34 (BOLTZMAN)
  *MAT_KELVIN-MAXWELL_VISCOELASTIC (061)      -> /MAT/LAW40 (KELVINMAX)
  *MAT_GENERAL_VISCOELASTIC (076, +_MOISTURE) -> /MAT/LAW42 + /VISC/PRONY
                                                 (Itab 0 explicit, Itab 1 fit)
  *MAT_SIMPLIFIED_RUBBER/FOAM (181, +options) -> /MAT/LAW88 [+ /VISC/PRONY]
  *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE (183)    -> /MAT/LAW88
  *MAT_SOFT_TISSUE (091) / _VISCO (092)       -> /MAT/LAW42 (Gamma/Tau arrays)

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_composites.py, tests/test_johnson_cook.py,
tests/test_hyperelastic_rubber.py and tests/test_metal_plasticity_2.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant (G1 = G0-GI, the LAW42 mu = +/-0.01*BULK carrier, Mu_1 = 2*C1, the
specimen 1/SGL and 1/(SW*ST) curve rescales, the rate x10 flat-extrapolation
guard, the LAW40 Poisson gate) is recomputed by hand in the test rather than
copied from the implementation.

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic - MAT_061's FO selecting a Kelvin retardation constant instead of a
Maxwell decay rate, MAT_181's PR being a viscous-decay input below zero and a
Hill-foam selector above it, MAT_091's S_i being DIMENSIONLESS while Radioss
reads Gamma_i as a modulus - the assertion pins the warning that states it,
with the citation in the test docstring. Reproducing dyna2rad's silence there
would pass an arithmetic check and still ship a wrong material.

Every emitted card in this batch was validated on a live OpenRadioss starter
run (starter_win64, /BEGIN 2022): 0 ERROR(S), the only warnings being two
cosmetic WARNING 1927 ("fit converged, check the parameters") for the Itab=1
Prony fit. The starter's own echo confirmed the field-by-field placement
asserted below - notably LAW40's "SHEAR MODULUS 1 = 80" for G0-GI, LAW88's
"PRESSURE DAMPING ... BETA = 5.0E-02" for a PR of -0.05, and LAW88's forced
"SPECIMEN GAUGE LENGTH (SGL) = 1.0", which is why the specimen normalization
has to be baked into the curve points.

Two checks that can FAIL rather than merely pass: the Itab=1 fit was verified
QUANTITATIVELY (curves built as 1000*exp(-t/0.05)+200 and 2500*exp(-t/0.08)+500
came back out of the starter's Levenberg-Marquardt fit as G=999.99997/BETA=20.0
and K=2499.9996/BETAK=12.5, plus the two equilibrium terms), and a NEGATIVE
control - pointing Ifunc_G at an id no /FUNCT defines - makes the same starter
answer ERROR 1928. The LAW34 mapping was additionally ENGINE-validated on a
single-element shear-relaxation run: sigma_xy(t)/gamma traces
GI + (G0-GI)*exp(-BETA*t) to a worst relative error of 0.007% over 195 output
states, once the 100 us half-ramp of the prescribed motion is accounted for.
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
from k2rad.writer.mesh import _target_mat_law    # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

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
    """Parse + dispatch a deck string into a fresh ConversionState."""
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
    """One LS-DYNA fixed-width card: every field right-justified in 10 cols."""
    return "".join(f"{v:>10}" for v in vals)


def _blocks(starter: str, header: str):
    """Every block whose first line starts with *header*, as a list of its lines
    (header line included, the trailing HDR ruler excluded)."""
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
    """The single block starting with *header* (fails the test if not unique)."""
    found = _blocks(starter, header)
    assert len(found) == 1, f"expected exactly one {header!r}, got {len(found)}"
    return found[0]


def _cards(block):
    """A /MAT block's DATA lines: everything after the title that is not a
    comment. Blank cards are KEPT — /MAT/LAW42's two mandatory blank cards hold
    real reader positions."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _fail_cards(block):
    """A /FAIL or /VISC block's data lines — those carry NO title line."""
    return [ln for ln in block[1:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _funct(starter: str, fid: int):
    """The (x, y) point list of /FUNCT/<fid> or /TABLE/1/<fid>."""
    for hdr in (f"/FUNCT/{fid}\n", f"/TABLE/1/{fid}\n"):
        found = _blocks(starter + "\n", hdr.rstrip("\n"))
        if found:
            rows = [ln for ln in found[0][2:]
                    if not ln.startswith("#") and len(ln) > 20]
            return [(_col_f(r, 1, 20), _col_f(r, 21, 40)) for r in rows]
    raise AssertionError(f"no /FUNCT or /TABLE for id {fid}")


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


# ── Decks ────────────────────────────────────────────────────────────────────

NODES = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0)))
)
SHELL = "*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
SECTION = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 5) + "\n"
           + _row(1.2, 1.2, 1.2, 1.2) + "\n")
END = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n"

SOLID_NODES = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
        (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
        (7, 10.0, 10.0, 10.0), (8, 0.0, 10.0, 10.0)))
)
SOLID = "*ELEMENT_SOLID\n" + _row(1, 7) + "\n" + _row(*range(1, 9)) + "\n"
SEC_SOLID = "*SECTION_SOLID\n" + _row(7, 1) + "\n"


def _part(mid: int) -> str:
    return "*PART\nshell part\n" + _row(7, 7, mid) + "\n"


def _deck(mat: str, mid: int, extra: str = "") -> str:
    return NODES + SHELL + _part(mid) + SECTION + mat + extra + END


def _solid_deck(mat: str, mid: int, extra: str = "") -> str:
    return (SOLID_NODES + SOLID + _part(mid) + SEC_SOLID + mat + extra + END)


def _curve(lcid: int, pts) -> str:
    return ("*DEFINE_CURVE\n" + _row(lcid) + "\n"
            + "".join(f"{x:>20}{y:>20}\n" for x, y in pts))


def _table2d(tbid: int, rows) -> str:
    return ("*DEFINE_TABLE_2D\n" + _row(tbid) + "\n"
            + "".join(f"{a:>20}{lc:>20}\n" for a, lc in rows))


def _mat006(mid=6, kw="*MAT_VISCOELASTIC", rho=1.1e-9, bulk=2000.0, g0=100.0,
            gi=20.0, beta=300.0):
    """*MAT_VISCOELASTIC, ONE card (Vol II R17 p.2-182):
    MID RHO BULK G0 GI BETA."""
    return kw + "\n" + _row(mid, rho, bulk, g0, gi, beta) + "\n"


def _mat061(mid=61, kw="*MAT_KELVIN-MAXWELL_VISCOELASTIC", rho=1.1e-9,
            bulk=2000.0, g0=100.0, gi=20.0, dc=300.0, fo=0.0, so=0.0):
    """*MAT_KELVIN-MAXWELL_VISCOELASTIC, ONE card (p.2-489):
    MID RHO BULK G0 GI DC FO SO."""
    return kw + "\n" + _row(mid, rho, bulk, g0, gi, dc, fo, so) + "\n"


def _mat076(mid=76, kw="*MAT_GENERAL_VISCOELASTIC", rho=1.1e-9, bulk=2000.0,
            pcf=0.0, ef=0.0, tref=0.0, a=0.0, b=0.0,
            lcid=0, nt=0, bstart=0.0, tramp=0.0, lcidk=0, ntk=0,
            bstartk=0.0, trampk=0.0, moisture=None,
            prony=((50.0, 10.0, 5.0, 2.0), (30.0, 3.0, 1.0, 0.4))):
    """*MAT_GENERAL_VISCOELASTIC (p.2-557). Card 2 is mandatory in the cfg —
    a deck using the Prony rows leaves it BLANK rather than omitting it."""
    out = (kw + "\n" + _row(mid, rho, bulk, pcf, ef, tref, a, b) + "\n"
           + _row(lcid, nt, bstart, tramp, lcidk, ntk, bstartk, trampk) + "\n")
    if moisture is not None:
        out += _row(*moisture) + "\n"
    for terms in prony:
        out += _row(*terms) + "\n"
    return out


def _mat181(mid=181, kw="*MAT_SIMPLIFIED_RUBBER/FOAM", rho=1.1e-9, km=2000.0,
            mu=0.0, g=0.0, sigf=0.0, ref=0, prten=0,
            sgl=0.0, sw=0.0, st=0.0, lc=901, tension=0, rtype=0, avgopt=0,
            pr=0.0, failure=None, card4=None, prony=()):
    """*MAT_SIMPLIFIED_RUBBER/FOAM (p.2-1231). Card 3 exists only with
    _WITH_FAILURE; card 4 (LCUNLD HU SHAPE STOL VISCO HISOUT) is optional and
    mandatory only when the Prony cards follow it."""
    out = (kw + "\n" + _row(mid, rho, km, mu, g, sigf, ref, prten) + "\n"
           + _row(sgl, sw, st, lc, tension, rtype, avgopt, pr) + "\n")
    if failure is not None:
        out += _row(*failure) + "\n"
    if card4 is not None:
        out += _row(*card4) + "\n"
    for terms in prony:
        out += _row(*terms) + "\n"
    return out


def _mat183(mid=183, kw="*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE", rho=1.1e-9,
            k=2000.0, mu=0.0, g=0.0, sigf=0.0,
            sgl=0.0, sw=0.0, st=0.0, lc=901, tension=0, rtype=0, avgopt=0,
            lcunld=0, ref=0.0, stol=0.0):
    """*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE (p.2-1240) — THREE mandatory cards,
    no PR, no REF/PRTEN on card 1, and card 3 is LCUNLD REF STOL."""
    return (kw + "\n" + _row(mid, rho, k, mu, g, sigf) + "\n"
            + _row(sgl, sw, st, lc, tension, rtype, avgopt) + "\n"
            + _row(lcunld, ref, stol) + "\n")


def _mat091(mid=91, kw="*MAT_SOFT_TISSUE", rho=1.1e-9, c1=20.0, c2=10.0,
            c3=5.0, c4=2.0, c5=100.0, ref=0, xk=2000.0, xlam=1.05, fang=30.0,
            xlam0=1.0, failsf=0.0, failsm=0.0, failshr=0.0,
            aopt=2.0, macf=0, s=None, t=None):
    """*MAT_SOFT_TISSUE (p.2-669) — FOUR mandatory cards (cards 3/4 exist even
    for the non-VISCO variant), plus S1..S6 / T1..T6 for _VISCO."""
    out = (kw + "\n" + _row(mid, rho, c1, c2, c3, c4, c5, ref) + "\n"
           + _row(xk, xlam, fang, xlam0, failsf, failsm, failshr) + "\n"
           + _row(aopt, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0) + "\n"
           + _row(0.0, 0.0, 0.0, macf) + "\n")
    if s is not None:
        out += _row(*(list(s) + [0.0] * 6)[:6]) + "\n"
        out += _row(*(list(t or []) + [0.0] * 6)[:6]) + "\n"
    return out


LC_LOAD = _curve(901, ((0.0, 0.0), (1.0, 100.0), (3.0, 240.0), (6.0, 500.0)))
LC_UNLD = _curve(902, ((0.0, 0.0), (1.0, 70.0), (3.0, 190.0), (6.0, 500.0)))
LC_RELAX_G = _curve(801, tuple((i * 0.01, 1000.0 * (0.9 ** i) + 200.0)
                               for i in range(21)))
LC_RELAX_K = _curve(802, tuple((i * 0.01, 2500.0 * (0.9 ** i) + 500.0)
                               for i in range(21)))


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / keyword registry
# ═════════════════════════════════════════════════════════════════════════════

class DispatchTests(unittest.TestCase):
    """Every documented keyword, option spelling and numeric alias reaches its
    handler.

    The dispatcher is an EXACT dict match after only _ID/_TITLE/_SUBTITLE are
    stripped (k2rad/parser.py::_split_keyword — note the literal "/" of
    *MAT_SIMPLIFIED_RUBBER/FOAM survives it, because the splitter only splits
    on "_"), so an option spelling with no key of its own falls through to
    skipped_keywords and the part silently loses its material. For MAT_181
    that is worse than a skip: _WITH_FAILURE inserts a whole card, so a missing
    key would shift the parse of every following card."""

    def test_every_spelling_is_registered(self):
        for kw in ("MAT_VISCOELASTIC", "MAT_006", "MAT_6",
                   "MAT_KELVIN-MAXWELL_VISCOELASTIC",
                   "MAT_KELVIN_MAXWELL_VISCOELASTIC", "MAT_061", "MAT_61",
                   "MAT_GENERAL_VISCOELASTIC",
                   "MAT_GENERAL_VISCOELASTIC_MOISTURE", "MAT_076", "MAT_76",
                   "MAT_SIMPLIFIED_RUBBER/FOAM",
                   "MAT_SIMPLIFIED_RUBBER/FOAM_WITH_FAILURE",
                   "MAT_SIMPLIFIED_RUBBER/FOAM_LOG_LOG_INTERPOLATION",
                   "MAT_SIMPLIFIED_RUBBER/FOAM_WITH_FAILURE"
                   "_LOG_LOG_INTERPOLATION",
                   "MAT_SIMPLIFIED_RUBBER", "MAT_SIMPLIFIED_RUBBER_FOAM",
                   "MAT_181", "MAT_181_WITH_FAILURE",
                   "MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE",
                   "MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE"
                   "_LOG_LOG_INTERPOLATION",
                   "MAT_183", "MAT_183_LOG_LOG_INTERPOLATION",
                   "MAT_SOFT_TISSUE", "MAT_091", "MAT_91",
                   "MAT_SOFT_TISSUE_VISCO", "MAT_092", "MAT_92"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_offset_specs_cover_every_spelling(self):
        """A keyword missing from _OFFSET_SPECS keeps its original ids inside an
        *INCLUDE_TRANSFORM while the rest of the include moves — a dangling
        material or curve reference, reported only as a generic warning."""
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("MAT_VISCOELASTIC", "MAT_006", "MAT_6",
                   "MAT_KELVIN-MAXWELL_VISCOELASTIC", "MAT_061",
                   "MAT_GENERAL_VISCOELASTIC",
                   "MAT_GENERAL_VISCOELASTIC_MOISTURE", "MAT_076",
                   "MAT_SIMPLIFIED_RUBBER/FOAM",
                   "MAT_SIMPLIFIED_RUBBER/FOAM_WITH_FAILURE", "MAT_181",
                   "MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE", "MAT_183",
                   "MAT_SOFT_TISSUE", "MAT_091",
                   "MAT_SOFT_TISSUE_VISCO", "MAT_092"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_title_option_is_stripped_and_read(self):
        """_TITLE adds one 80a line before card 1 for every one of them."""
        cases = (
            ("*MAT_VISCOELASTIC_TITLE", 6,
             _mat006(kw="*MAT_VISCOELASTIC_TITLE\nviscoelastic")),
            ("*MAT_061_TITLE", 61,
             "*MAT_061_TITLE\nkelvin max\n" + _mat061().split("\n", 1)[1]),
            ("*MAT_076_TITLE", 76,
             "*MAT_076_TITLE\ngeneral visco\n" + _mat076().split("\n", 1)[1]),
            ("*MAT_181_TITLE", 181,
             "*MAT_181_TITLE\nsimple rubber\n" + _mat181().split("\n", 1)[1]),
            ("*MAT_183_TITLE", 183,
             "*MAT_183_TITLE\nrubber damage\n" + _mat183().split("\n", 1)[1]),
            ("*MAT_SOFT_TISSUE_TITLE", 91,
             "*MAT_SOFT_TISSUE_TITLE\ntendon\n" + _mat091().split("\n", 1)[1]),
        )
        for kw, mid, mat in cases:
            with self.subTest(kw=kw):
                _, starter = _convert(_deck(mat, mid, LC_LOAD))
                titles = [ln for ln in starter.splitlines()
                          if ln in ("viscoelastic", "kelvin max",
                                    "general visco", "simple rubber",
                                    "rubber damage", "tendon")]
                self.assertTrue(titles, f"{kw} title line not emitted")


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_VISCOELASTIC (006) -> /MAT/LAW34
# ═════════════════════════════════════════════════════════════════════════════

class Mat006Tests(unittest.TestCase):
    """*MAT_VISCOELASTIC is the one EXACT 1:1 in this batch: LS-DYNA's
    G(t) = GI + (G0-GI)*exp(-BETA*t) is literally LAW34's kernel
    (sigeps34.F:88-101), and BETA is a decay RATE on both sides."""

    def test_card_columns(self):
        """/MAT/LAW34 layout (matl34_boltzman.cfg FORMAT(radioss51)):
        C1 Init.dens.(1-20) / C2 K(1-20) / C3 G0(1-20) Gl(21-40) Beta(41-60) /
        C4 P0(1-20) Phi(21-40) Gamma0(41-60). All four cards unconditional."""
        _, starter = _convert(_deck(_mat006(), 6))
        c = _cards(_block(starter, "/MAT/LAW34/6"))
        self.assertEqual(len(c), 4)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.1e-9)
        # the reference-density pre-scan reads columns 21-40 of the density
        # card; anything non-blank there switches the reader to the two-field
        # form, so the line must stop at column 20.
        self.assertEqual(len(c[0].rstrip()), 20)
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 2000.0)
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 100.0)     # G0
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 20.0)     # Gl
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 300.0)    # Beta
        for a, b in ((1, 20), (21, 40), (41, 60)):
            self.assertEqual(_col_f(c[3], a, b), 0.0)          # P0/Phi/Gamma0

    def test_beta_is_not_inverted(self):
        """LS-DYNA BETA and LAW34 Beta are both 1/time — a 1/BETA inversion
        (which the MAT_077_O embedded-LAW42 path DOES need, because LAW42's
        Tau is a relaxation TIME) would be wrong here."""
        _, starter = _convert(_deck(_mat006(beta=0.004), 6))
        c = _cards(_block(starter, "/MAT/LAW34/6"))
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 0.004)

    def test_temperature_curve_is_collapsed_to_the_first_ordinate(self):
        """A negative BULK/G0/GI/BETA is -LCID of a temperature curve (R6.1
        SCALAR_OR_OBJECT). LAW34 has no temperature slot, so dyna2rad takes the
        ordinate of the curve's FIRST point — the value at the lowest tabulated
        temperature — and says nothing. k2rad does the same and warns."""
        deck = _deck(_mat006(g0=-950.0),
                     6, _curve(950, ((20.0, 133.0), (80.0, 77.0))))
        res, starter = _convert(deck)
        c = _cards(_block(starter, "/MAT/LAW34/6"))
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 133.0)
        self.assertTrue(any("TEMPERATURE" in w and "133" in w
                            for w in _warns(res, "*MAT_VISCOELASTIC")),
                        res.warnings)

    def test_bulk_temperature_curve_is_resolved_not_zeroed(self):
        """dyna2rad reads G0_CURVES/GI_CURVES/BETA_CURVES but NEVER BULK_CURVES
        (CM:4701-4716), so a negative BULK leaves K=0 and the LAW34 CHECK
        rejects the material. k2rad resolves the fourth curve the same way as
        the other three."""
        deck = _deck(_mat006(bulk=-951.0),
                     6, _curve(951, ((20.0, 2200.0), (80.0, 1800.0))))
        res, starter = _convert(deck)
        c = _cards(_block(starter, "/MAT/LAW34/6"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 2200.0)
        self.assertTrue(any("dyna2rad never reads the BULK curve" in w
                            for w in res.warnings), res.warnings)

    def test_missing_temperature_curve_warns_and_zeroes(self):
        res, starter = _convert(_deck(_mat006(beta=-777.0), 6))
        c = _cards(_block(starter, "/MAT/LAW34/6"))
        self.assertEqual(_col_f(c[2], 41, 60), 0.0)
        self.assertTrue(any("777" in w and "no parsed *DEFINE_CURVE" in w
                            for w in res.warnings), res.warnings)

    def test_g0_equals_gi_warns_but_still_converts(self):
        """dyna2rad's only message in this whole batch is error 200003 on
        G0 == GI, and it converts anyway."""
        res, starter = _convert(_deck(_mat006(g0=40.0, gi=40.0), 6))
        self.assertTrue(_blocks(starter, "/MAT/LAW34/6"))
        self.assertTrue(any("G0=GI" in w and "200003" in w
                            for w in res.warnings), res.warnings)

    def test_non_positive_fields_are_graded_by_what_the_solver_does(self):
        """matl34_boltzman.cfg's CHECK block asks for BULK/DECAY/G0/GI/RHO > 0,
        but that is HyperMesh-side: hm_read_mat34.F contains NO ANCMSG at all.
        Each field was therefore MEASURED on starter_win64 + engine_win64, and
        the four outcomes differ, so one blanket "the deck will not read"
        message is wrong for three of them:

          RHO=0   starter ERROR 683 (the only hard stop on this card)
          G0=0    starter clean; YOUNG=0 and the solid time step came out 1E+21
          BULK=0  starter clean; YOUNG=0, no volumetric stiffness
          GI=0    LEGAL — full relaxation; starter AND engine clean
          BETA=0  starter clean, then sigeps34.F:101 forms C2 = -(1-exp(0))/0,
                  so I-ENERGY/EXT-WORK go NaN for 1114 cycles and the run still
                  reports NORMAL TERMINATION

        Pinning the DECISION, not the prose: GI=0 must not claim the deck is
        unreadable (that pushes the user to change a correct card) and BETA=0
        must not be softened to "unreadable" (a silent NaN run is worse)."""
        res, _ = _convert(_deck(_mat006(rho=0.0), 6))
        self.assertTrue([w for w in res.warnings
                         if "RHO=0" in w and "ERROR 683" in w], res.warnings)

        res, _ = _convert(_deck(_mat006(gi=0.0), 6))
        gi = [w for w in res.warnings if "GI=0" in w]
        self.assertTrue(gi, res.warnings)
        self.assertNotIn("will not read", gi[0])
        self.assertNotIn("ERROR", gi[0])

        res, _ = _convert(_deck(_mat006(beta=0.0), 6))
        beta = [w for w in res.warnings if "BETA=0" in w]
        self.assertTrue(beta, res.warnings)
        self.assertIn("NaN", beta[0])
        self.assertIn("sigeps34.F:101", beta[0])

        res, _ = _convert(_deck(_mat006(bulk=0.0, g0=0.0), 6))
        self.assertTrue([w for w in res.warnings if "BULK=0" in w],
                        res.warnings)
        self.assertTrue([w for w in res.warnings if "G0=0" in w], res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_KELVIN-MAXWELL_VISCOELASTIC (061) -> /MAT/LAW40
# ═════════════════════════════════════════════════════════════════════════════

class Mat061Tests(unittest.TestCase):
    """dyna2rad p_ConvertMatL61 (CM:3317-3350): G_inf = GI, G1 = G0-GI,
    BETA1 = DC, everything else zeroed."""

    def test_card_columns_and_g1_split(self):
        """/MAT/LAW40 layout (matl40_kelvinmax.cfg FORMAT(radioss90)):
        C1 RHO_I(1-20) / C2 K(1-20) G_inf(21-40) Astass(41-60) Bstass(61-80)
        Kvm(81-100) / C3 G1..G5 / C4 BETA1..BETA5.

        G1 = G0 - GI is the whole conversion: LS-DYNA states the INSTANTANEOUS
        modulus G0, Radioss the branch modulus on top of G_inf. Starter echo:
        "SHEAR MODULUS 1 = 80.00000000000" for G0=100, GI=20."""
        _, starter = _convert(_solid_deck(_mat061(), 61))
        c = _cards(_block(starter, "/MAT/LAW40/61"))
        self.assertEqual(len(c), 4)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.1e-9)
        self.assertEqual(len(c[0].rstrip()), 20)               # no rho_o field
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 2000.0)    # K
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 20.0)     # G_inf = GI
        for a, b in ((41, 60), (61, 80), (81, 100)):           # Stassi/von Mises
            self.assertEqual(_col_f(c[1], a, b), 0.0)
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 100.0 - 20.0)   # G1
        for i in range(1, 5):
            self.assertEqual(_col_f(c[2], 1 + 20 * i, 20 + 20 * i), 0.0)
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 300.0)     # BETA1 = DC
        for i in range(1, 5):
            self.assertEqual(_col_f(c[3], 1 + 20 * i, 20 + 20 * i), 0.0)

    def test_astass_zero_disables_the_yield_surface(self):
        """0 is deliberate: hm_read_mat40.F:122-124 turns anything <= 1e-20 into
        INFINITY, which switches the Stassi/von-Mises cap off. Starter echo:
        "STASSI A COEFFICIENT = 1.0000000200409E+20"."""
        _, starter = _convert(_solid_deck(_mat061(), 61))
        c = _cards(_block(starter, "/MAT/LAW40/61"))
        self.assertEqual(c[1][40:100].split(), ["0", "0", "0"])
        self.assertEqual(len(c[1]), 100)

    def test_kelvin_flag_is_warned_loudly(self):
        """FO=1 makes DC a RETARDATION constant under a different evolution
        equation; LAW40's kernel is exp(-BETA*dt), i.e. Maxwell only. dyna2rad
        converts it as a Maxwell decay rate SILENTLY."""
        res, _ = _convert(_solid_deck(_mat061(fo=1.0), 61))
        hits = [w for w in res.warnings
                if "KELVIN" in w and "RETARDATION" in w]
        self.assertTrue(hits, res.warnings)

    def test_maxwell_flag_is_silent(self):
        res, _ = _convert(_solid_deck(_mat061(fo=0.0), 61))
        self.assertFalse([w for w in res.warnings if "RETARDATION" in w])

    def test_so_is_reported_as_output_only(self):
        res, _ = _convert(_solid_deck(_mat061(so=2.0), 61))
        self.assertTrue([w for w in res.warnings
                         if "SO=2" in w and "DROPPED" in w],
                        res.warnings)

    def test_poisson_gate_error_49(self):
        """hm_read_mat40.F:126-143 computes nu from K against G_inf and against
        G_inf+sum(G_i) and rejects the material unless BOTH land in [0, 0.5).
        With BULK = 0 the first is (0-2*20)/(2*20+0) = -1."""
        res, _ = _convert(_solid_deck(_mat061(bulk=0.0), 61))
        hits = [w for w in res.warnings if "ERROR 49" in w]
        self.assertTrue(hits, res.warnings)
        # remedy quoted in the message: BULK >= (2/3)*G0
        self.assertIn(f"{2.0 * 100.0 / 3.0:g}", hits[0])

    def test_poisson_gate_passes_for_a_sane_card(self):
        res, _ = _convert(_solid_deck(_mat061(), 61))
        self.assertFalse([w for w in res.warnings if "ERROR 49" in w])

    def test_negative_g1_is_warned(self):
        res, _ = _convert(_solid_deck(_mat061(g0=10.0, gi=40.0), 61))
        self.assertTrue([w for w in res.warnings if "NEGATIVE" in w],
                        res.warnings)

    def test_shell_part_is_rejected_with_error_3046(self):
        """LAW40 declares only SOLID_ISOTROPIC and SPH
        (hm_read_mat40.F:184-185), and its engine kernel sigeps40 is never
        called from the shell path — a *MAT_061 shell part is ERROR 3046.
        dyna2rad never checks this."""
        res, _ = _convert(_deck(_mat061(), 61))
        hits = [w for w in res.warnings if "ERROR 3046" in w and "LAW40" in w]
        self.assertTrue(hits, res.warnings)
        self.assertIn("*MAT_VISCOELASTIC", hits[0])   # names the shell-capable
                                                      # alternative

    def test_solid_part_is_not_warned(self):
        res, _ = _convert(_solid_deck(_mat061(), 61))
        self.assertFalse([w for w in res.warnings if "ERROR 3046" in w])


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_GENERAL_VISCOELASTIC (076) -> /MAT/LAW42 + /VISC/PRONY
# ═════════════════════════════════════════════════════════════════════════════

class Mat076Tests(unittest.TestCase):
    """The LAW42 carrier is dyna2rad p_ConvertMatL76 verbatim; the Prony series
    goes to /VISC/PRONY, the only Radioss card with all four LS-DYNA columns."""

    def test_law42_carrier_columns(self):
        """/MAT/LAW42 layout (matl42_Ogden.cfg FORMAT(radioss140)):
        C1 rho / C2 Nu(1-20) sigma_cut(21-40) [phantom Jstrain 41-50]
        funIDbulk(51-60) Fscale_bulk(61-80) M(81-90) I_form(91-100) /
        C3 Mu_1..Mu_5 / BLANK / C5 alpha_1..alpha_5 / BLANK.

        Nu = 0.495, Mu = +/-0.01*BULK, alpha = +/-2 (CM:4457-4472). GS =
        sum(mu_i*alpha_i) = 0.04*BULK, so the ground shear modulus is
        0.02*BULK — starter echo "INITIAL SHEAR MODULUS = 40.00000000000"
        for BULK = 2000."""
        _, starter = _convert(_solid_deck(_mat076(), 76))
        c = _cards(_block(starter, "/MAT/LAW42/76"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 0.495)
        self.assertEqual(_col_f(c[1], 21, 40), 0.0)            # sigma_cut
        self.assertEqual(_col_i(c[1], 51, 60), 0)              # funIDbulk
        self.assertEqual(_col_i(c[1], 81, 90), 0)              # M stays on
                                                               # /VISC/PRONY
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 0.01 * 2000.0)
        self.assertAlmostEqual(_col_f(c[2], 21, 40), -0.01 * 2000.0)
        self.assertEqual(c[3].strip(), "")                     # mandatory blank
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 2.0)
        self.assertAlmostEqual(_col_f(c[4], 21, 40), -2.0)
        self.assertEqual(c[5].strip(), "")                     # mandatory blank

    def test_prony_carries_all_four_columns(self):
        """/VISC/PRONY Itab=0 (mat_VISC_PRONY.cfg FORMAT(radioss2021)):
        M(1-10) gap(11-20) K_v(21-40) Itab(41-50) Ishape(51-60), then M rows of
        G_i(1-20) Beta_i(21-40) Ki(41-60) Beta_ki(61-80).

        dyna2rad copies GI/BETAI/KI but asks for "BETAK" instead of the array's
        real name BETAKI (CM:4526), so every bulk decay constant is lost there.
        Starter echo confirms all four: "BETAK DECAY BULK MODULUS = 2.0"."""
        _, starter = _convert(_solid_deck(_mat076(), 76))
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 2)               # M
        self.assertEqual(c[0][10:20], " " * 10)                # literal gap
        self.assertEqual(_col_f(c[0], 21, 40), 0.0)            # K_v
        self.assertEqual(_col_i(c[0], 41, 50), 0)              # Itab
        self.assertEqual(_col_i(c[0], 51, 60), 0)              # Ishape
        self.assertEqual([_col_f(c[1], a, b) for a, b in
                          ((1, 20), (21, 40), (41, 60), (61, 80))],
                         [50.0, 10.0, 5.0, 2.0])
        self.assertEqual([_col_f(c[2], a, b) for a, b in
                          ((1, 20), (21, 40), (41, 60), (61, 80))],
                         [30.0, 3.0, 1.0, 0.4])

    def test_prony_has_no_title_line(self):
        """/VISC blocks carry NO title after the header — one would be read as
        the M card."""
        _, starter = _convert(_solid_deck(_mat076(), 76))
        raw = _block(starter, "/VISC/PRONY/76")
        self.assertTrue(raw[1].startswith("#"))

    def test_curve_fit_form_is_itab_1(self):
        """LCID+NT is exactly /VISC/PRONY Itab=1: the STARTER fits an M-term
        Prony series (LM_LEAST_SQUARE_PRONY). Layout: Ifunc(1-10)
        Xscale(11-30) Yscale(31-50), EXACTLY two rows. dyna2rad can never reach
        this branch — it reads the second curve through sdiIdentifier
        ("LSD_LCIDK"), a name that does not exist (the attribute is LSD_LCID2),
        so lcIdk is always 0 and it emits an EMPTY /VISC/PRONY (ERROR 2026)."""
        deck = _solid_deck(_mat076(lcid=801, nt=3, lcidk=802, ntk=3, prony=()),
                           76, LC_RELAX_G + LC_RELAX_K)
        _, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(len(c), 3)
        self.assertEqual(_col_i(c[0], 1, 10), 3)               # M = max(NT,NTK)
        self.assertEqual(_col_i(c[0], 41, 50), 1)              # Itab
        self.assertEqual(_col_i(c[1], 1, 10), 801)             # Ifunc_G
        self.assertEqual(_col_f(c[1], 11, 30), 0.0)            # XGscale -> 1.0
        self.assertEqual(_col_i(c[2], 1, 10), 802)             # Ifunc_K

    def test_blank_nt_defaults_to_six_and_clamps(self):
        """LS-DYNA NT blank means 6 (max 18); dyna2rad's own expression is
        min(max(NT,NTK),6), so a blank must not become M=0 (ERROR 2026)."""
        deck = _solid_deck(_mat076(lcid=801, prony=()), 76, LC_RELAX_G)
        _, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 6)
        deck = _solid_deck(_mat076(lcid=801, nt=12, prony=()), 76, LC_RELAX_G)
        res, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 6)
        self.assertTrue([w for w in res.warnings if "clamped" in w])

    def test_absent_second_curve_does_not_default_its_order_to_six(self):
        """"If zero, the default is 6" belongs to a fit that RUNS: LS-DYNA fits
        the bulk series only when LCIDK is given (p.2-560). Defaulting the
        ABSENT curve's order to 6 pins M at 6 for every single-curve card,
        which (a) throws away NT and (b) breaks decks LS-DYNA converts fine,
        because the starter needs 2*M < npoints (hm_read_visc_prony.F:473,
        ERROR 1921) — a 10-point curve fits with NT=2 and dies at M=6."""
        pts = tuple((0.1 * i, 100.0 * 0.9 ** i + 20.0) for i in range(10))
        crv = _curve(801, pts)
        deck = _solid_deck(_mat076(lcid=801, nt=2, prony=()), 76, crv)
        res, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 2)
        self.assertEqual(_col_i(c[1], 1, 10), 801)             # Ifunc_G
        self.assertEqual(_col_i(c[2], 1, 10), 0)               # no bulk fit
        self.assertFalse([w for w in res.warnings if "ERROR 1921" in w],
                         res.warnings)
        # ... and the mirror: bulk curve only, NTK=3, NT blank -> M = 3.
        deck = _solid_deck(_mat076(lcidk=801, ntk=3, prony=()), 76, crv)
        _, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 3)

    def test_differing_nt_and_ntk_are_warned_because_prony_has_one_m(self):
        """/VISC/PRONY carries a SINGLE M for both the shear and the bulk fit,
        so NT != NTK cannot be honoured — the larger wins."""
        deck = _solid_deck(_mat076(lcid=801, nt=2, lcidk=802, ntk=4,
                                   prony=()), 76, LC_RELAX_G + LC_RELAX_K)
        res, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 4)
        self.assertTrue([w for w in res.warnings
                         if "NT=2" in w and "NTK=4" in w], res.warnings)

    def test_no_prony_and_no_curve_emits_no_visc_block(self):
        """dyna2rad creates /VISC/PRONY unconditionally, so an elastic MAT_076
        gets M=0 and the starter stops the WHOLE deck with ERROR 2026."""
        res, starter = _convert(_solid_deck(_mat076(prony=()), 76))
        self.assertEqual(_blocks(starter, "/VISC/PRONY/76"), [])
        self.assertTrue([w for w in res.warnings if "ERROR 2026" in w],
                        res.warnings)

    def test_too_few_curve_points_warns_error_1921(self):
        """LM_LEAST_SQUARE_PRONY requires 2*M < npoints."""
        short = _curve(801, ((0.0, 100.0), (1.0, 50.0), (2.0, 30.0)))
        deck = _solid_deck(_mat076(lcid=801, nt=3, prony=()), 76, short)
        res, _ = _convert(deck)
        self.assertTrue([w for w in res.warnings if "ERROR 1921" in w],
                        res.warnings)

    def test_missing_fit_curve_warns_error_1928(self):
        res, _ = _convert(_solid_deck(_mat076(lcid=888, nt=3, prony=()), 76))
        self.assertTrue([w for w in res.warnings if "ERROR 1928" in w],
                        res.warnings)

    def test_explicit_rows_win_over_the_curve_form(self):
        deck = _solid_deck(_mat076(lcid=801, nt=3), 76, LC_RELAX_G)
        res, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 41, 50), 0)              # Itab 0
        self.assertTrue([w for w in res.warnings if "IGNORED" in w])

    def test_bulk_fidelity_warning_states_the_real_numbers(self):
        """LAW42 has no bulk field — the LS-DYNA BULK only reaches Radioss
        through Nu. GS = 0.04*BULK and Nu = 0.495 give
        BULK_rad = GS*(1+Nu)/(3*(1-2*Nu)) = 1.9933*BULK; the starter echoed
        "BULK MODULUS = 3986.666666667" for BULK = 2000."""
        res, _ = _convert(_solid_deck(_mat076(bulk=2000.0), 76))
        hits = [w for w in res.warnings if "does NOT become a bulk modulus" in w]
        self.assertTrue(hits, res.warnings)
        gs = 0.04 * 2000.0
        self.assertIn(f"{gs * 1.495 / (3.0 * 0.01):g}", hits[0])
        self.assertIn(f"{0.02 * 2000.0:g}", hits[0])

    def test_dropped_fields_are_warned(self):
        res, _ = _convert(_solid_deck(
            _mat076(pcf=1.0, ef=1.0, tref=293.0, a=10.0, b=50.0), 76))
        for needle in ("PCF=1", "EF=1", "TREF=293"):
            with self.subTest(needle=needle):
                self.assertTrue([w for w in res.warnings if needle in w],
                                res.warnings)
        # PCF must NOT land in sigma_cut: it is a flag, that field is a stress.
        _, starter = _convert(_solid_deck(_mat076(pcf=1.0), 76))
        c = _cards(_block(starter, "/MAT/LAW42/76"))
        self.assertEqual(_col_f(c[1], 21, 40), 0.0)

    def test_moisture_variant_parses_and_warns(self):
        """*MAT_GENERAL_VISCOELASTIC_MOISTURE inserts one card before the Prony
        list — missing it would read MO/ALPHA/BETA/GAMMA/MST as a Prony term."""
        deck = _solid_deck(
            _mat076(kw="*MAT_GENERAL_VISCOELASTIC_MOISTURE",
                    moisture=(0.02, 1.0, 2.0, 3.0, 4.0)), 76)
        res, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/VISC/PRONY/76"))
        self.assertEqual(_col_i(c[0], 1, 10), 2)               # still 2 rows
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 50.0)
        self.assertTrue([w for w in res.warnings if "_MOISTURE" in w],
                        res.warnings)

    def test_bstart_tramp_are_warned_on_the_fit_path(self):
        deck = _solid_deck(
            _mat076(lcid=801, nt=3, bstart=0.5, tramp=0.01, prony=()),
            76, LC_RELAX_G)
        res, _ = _convert(deck)
        self.assertTrue([w for w in res.warnings if "BSTART=0.5" in w],
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_SIMPLIFIED_RUBBER/FOAM (181) -> /MAT/LAW88
# ═════════════════════════════════════════════════════════════════════════════

class Mat181Tests(unittest.TestCase):
    """dyna2rad ConvertMatL181ToMatL88 (CM:4912-5152). The /BEGIN 2022 LAW88
    card is exactly three cards plus the NL rows — the radioss2026 revision's
    SGL/SW/ST/G/SIGF and KFAIL/GAM1/GAM2/EH cards are SWALLOWED without an
    error by a 2022 starter (measured: SGL 0.05 reads back as 1.0), so the
    specimen normalization must live in the curve points instead."""

    def test_card_columns(self):
        """/MAT/LAW88 layout (mat_law88.cfg FORMAT(radioss2017)):
        C1 RHO_I(1-20) / C2 NU(1-20) K(21-40) F_CUT(41-60) F_SMOOTH(61-70)
        NL(71-80) / C3 FCT_ID_UN(1-10) gap(11-20) F_SCALE_UN(21-40) HYS(41-60)
        SHAPE(61-80) TENSION(81-90) / NL x [FCT_ID_LI(1-10) gap(11-20)
        F_SCALE_LI(21-40) EPSI_LI(41-60)].

        F_SMOOTH is left BLANK: the current starter never calls
        hm_get_intv('LAW88_Fsmooth'), so those ten columns are consumed by the
        format and discarded."""
        _, starter = _convert(_deck(_mat181(tension=1), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.1e-9)
        self.assertEqual(_col_f(c[1], 1, 20), 0.0)             # NU = PR
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 2000.0)   # K = KM
        self.assertEqual(_col_f(c[1], 41, 60), 0.0)            # F_CUT
        self.assertEqual(c[1][60:70], " " * 10)                # F_SMOOTH blank
        self.assertEqual(_col_i(c[1], 71, 80), 1)              # NL
        self.assertEqual(c[2][10:20], " " * 10)                # literal gap
        self.assertEqual(_col_i(c[2], 81, 90), 1)              # TENSION
        self.assertEqual(_col_i(c[3], 1, 10), 901)             # FCT_ID_LI
        self.assertEqual(_col_f(c[3], 21, 40), 0.0)            # F_SCALE -> 1.0
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 1.0)      # EPSI_LI

    def test_tension_flag_is_transferred(self):
        """dyna2rad asks for "TENSIOM" for MAT_181 (CM:5150) — the only
        occurrence of that string in the whole Radioss tree — so its rate-effect
        flag never arrives and the material silently falls back to 0
        ("compressive loading only"). Starter echo: "RATE EFFECT FLAG
        (TENSION) = 1"."""
        for tension in (-1, 0, 1):
            with self.subTest(tension=tension):
                _, starter = _convert(
                    _deck(_mat181(tension=tension), 181, LC_LOAD))
                c = _cards(_block(starter, "/MAT/LAW88/181"))
                self.assertEqual(_col_i(c[2], 81, 90), tension)

    def test_specimen_normalization_is_baked_into_the_points(self):
        """LS-DYNA states the curve as FORCE vs change in gauge length;
        LAW88 at /BEGIN 2022 forces SGL=SW=ST=1.0 (hm_read_mat88.F90:205-215,
        starter echo "SPECIMEN GAUGE LENGTH (SGL) = 1.0"), so the abscissa must
        be pre-divided by SGL and the ordinate by SW*ST."""
        _, starter = _convert(
            _deck(_mat181(sgl=10.0, sw=2.0, st=0.5), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        fid = _col_i(c[3], 1, 10)
        self.assertNotEqual(fid, 901)                  # a new duplicate curve
        pts = _funct(starter, fid)
        self.assertEqual(pts[1], (1.0 / 10.0, 100.0 / (2.0 * 0.5)))
        self.assertEqual(pts[3], (6.0 / 10.0, 500.0 / (2.0 * 0.5)))
        # the original is left untouched
        self.assertEqual(_funct(starter, 901)[1], (1.0, 100.0))

    def test_one_duplicate_per_source_curve(self):
        """A curve used for BOTH loading and unloading must yield ONE rescaled
        function, not two. With two distinct ids the starter's self-unloading
        rule (`if ifunc_unload == ifunc(1) then ifunc_unload = 0`,
        hm_read_mat88.F90:221-225) no longer fires and the material unloads
        along a separate-but-identical curve instead of being flagged
        hysteresis-free."""
        _, starter = _convert(_deck(
            _mat181(sgl=10.0, sw=2.0, st=0.5, card4=(901, 0.7, 2.0)),
            181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[2], 1, 10), _col_i(c[3], 1, 10))
        synthesized = [ln for ln in starter.splitlines()
                       if ln.startswith("/FUNCT/9000")]
        self.assertEqual(len(synthesized), 1, synthesized)

    def test_blank_specimen_dimensions_keep_the_curve(self):
        """dyna2rad REFUSES to write any curve unless SGL, SW and ST are ALL
        non-zero (CM:4955), which turns a curve already given in engineering
        stress-strain into NL = 0, i.e. starter ERROR 866. Blank reads as 1.0
        here — the same thing the starter itself assumes."""
        _, starter = _convert(_deck(_mat181(), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[1], 71, 80), 1)
        self.assertEqual(_col_i(c[3], 1, 10), 901)     # unscaled, reused as-is

    def test_table_rate_family_repeats_the_top_curve_at_ten_times(self):
        """dyna2rad's deliberate flat-extrapolation guard (CM:5022-5027):
        NL = nFunct + 1, the last curve duplicated at 10x the highest rate so
        Radioss holds it flat instead of extrapolating the rate axis."""
        curves = (_curve(910, ((0.0, 0.0), (1.0, 100.0)))
                  + _curve(911, ((0.0, 0.0), (1.0, 115.0)))
                  + _curve(912, ((0.0, 0.0), (1.0, 130.0)))
                  + _table2d(900, ((0.001, 910), (1.0, 911), (100.0, 912))))
        _, starter = _convert(_deck(_mat181(lc=900), 181, curves))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[1], 71, 80), 4)              # NL = 3 + 1
        rates = [_col_f(c[3 + i], 41, 60) for i in range(4)]
        self.assertEqual(rates, [0.001, 1.0, 100.0, 1000.0])
        fcts = [_col_i(c[3 + i], 1, 10) for i in range(4)]
        self.assertEqual(fcts[2], fcts[3])                     # same curve id
        self.assertEqual(fcts[:3], [910, 911, 912])

    def test_rate_family_stays_strictly_increasing(self):
        """LAW88 rejects a non-increasing EPSI_LI list with ERROR 478
        (hm_read_mat88.F90:196-206). Two ways that could happen and does not:
        *DEFINE_TABLE rows given out of order are sorted ascending by
        _resolve_define_tables, and a top rate of 0 would make dyna2rad's blind
        `rate * 10` REPEAT it — guarded here with `rate + 1` instead."""
        curves = (_curve(910, ((0.0, 0.0), (1.0, 100.0)))
                  + _curve(911, ((0.0, 0.0), (1.0, 115.0)))
                  + _curve(912, ((0.0, 0.0), (1.0, 130.0))))
        # rows deliberately out of order
        deck = _deck(_mat181(lc=900), 181, curves + _table2d(
            900, ((100.0, 912), (0.001, 910), (1.0, 911))))
        _, starter = _convert(deck)
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        rates = [_col_f(c[3 + i], 41, 60) for i in range(4)]
        self.assertEqual(rates, [0.001, 1.0, 100.0, 1000.0])
        # a single row at rate 0: rate*10 would repeat it
        deck = _deck(_mat181(lc=900), 181,
                     curves + _table2d(900, ((0.0, 910),)))
        _, starter = _convert(deck)
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        rates = [_col_f(c[3 + i], 41, 60) for i in range(2)]
        self.assertEqual(rates, [0.0, 1.0])
        self.assertTrue(all(b > a for a, b in zip(rates, rates[1:])))

    def test_rate_family_is_clamped_to_the_starter_maxfunc(self):
        """hm_read_mat.F90:294 declares `parameter (maxfunc = 128)` and
        hm_read_mat88.F90:103-108 sizes ifunc/rate/yfac/lambda at maxfunc+1,
        then reads `do i = 1,nl` with NO bound on NL — so an over-long rate
        family is an out-of-bounds WRITE, not a diagnosable error. Same
        treatment as the >100-term /VISC/PRONY case: clamp and say so."""
        n = 140
        curves = "".join(_curve(2000 + i, ((0.0, 0.0), (1.0, 100.0 + i)))
                         for i in range(n))
        tab = _table2d(900, tuple((float(i + 1), 2000 + i) for i in range(n)))
        res, starter = _convert(_deck(_mat181(lc=900), 181, curves + tab))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[1], 71, 80), 128)            # NL == maxfunc
        self.assertTrue([w for w in res.warnings
                         if "maxfunc=128" in w and "DROPPED" in w],
                        res.warnings)
        # the flat-extrapolation duplicate still made it in
        fcts = [_col_i(c[3 + i], 1, 10) for i in range(128)]
        self.assertEqual(fcts[-1], fcts[-2])

    def test_unresolved_table_is_not_reported_as_a_missing_curve(self):
        """A legacy *DEFINE_TABLE with too few following curves stays
        unresolved. It must not fall through to the single-curve branch, which
        would name the wrong keyword: "loading curve 900 has no parsed
        *DEFINE_CURVE" for what is a table id."""
        legacy = ("*DEFINE_TABLE\n" + _row(900) + "\n"
                  + f"{0.001:>20}\n{1.0:>20}\n")
        res, _ = _convert(_deck(_mat181(lc=900), 181, legacy))
        self.assertTrue([w for w in res.warnings
                         if "*DEFINE_TABLE" in w and "could not be resolved"
                         in w and "ERROR 866" in w], res.warnings)
        self.assertFalse([w for w in res.warnings
                          if "loading curve 900 has no parsed" in w],
                         res.warnings)

    def test_tension_only_loading_curve_is_warned(self):
        """LAW88 interpolates the SAME curve at all three principal stretches
        (sigeps88.F90:375-377), so uniaxial tension drives the two lateral
        stretches into compression, where a tension-only table is
        EXTRAPOLATED. Measured: the cell bifurcated at eps=0.65 (lam2 0.79 ->
        0.41, lam3 -> 1.45, KE up 4 decades) and still reached NORMAL
        TERMINATION; adding the compression branch fixed it exactly."""
        res, _ = _convert(_deck(_mat181(), 181, LC_LOAD))
        self.assertTrue([w for w in res.warnings
                         if "compression" in w and "sigeps88" in w],
                        res.warnings)
        both = _curve(901, ((-0.6, -240.0), (0.0, 0.0), (1.0, 100.0),
                            (3.0, 240.0)))
        res, _ = _convert(_deck(_mat181(), 181, both))
        self.assertFalse([w for w in res.warnings if "sigeps88" in w],
                         res.warnings)

    def test_unloading_priority_lcunld_then_hu_then_loading(self):
        """dyna2rad's three branches (CM:5085-5145), in order."""
        # 1) LCUNLD present
        _, starter = _convert(
            _deck(_mat181(card4=(902, 0.7, 2.0)), 181, LC_LOAD + LC_UNLD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[2], 1, 10), 902)
        self.assertEqual(_col_f(c[2], 41, 60), 0.0)            # HYS unused
        # 2) no LCUNLD but a present card 4 with HU > 0
        _, starter = _convert(
            _deck(_mat181(card4=(0, 0.6, 3.0)), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[2], 1, 10), 0)
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 0.6)      # HYS = HU
        self.assertAlmostEqual(_col_f(c[2], 61, 80), 3.0)      # SHAPE
        # 3) no card 4 at all -> the loading curve, which the starter nulls out
        _, starter = _convert(_deck(_mat181(), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[2], 1, 10), 901)
        self.assertEqual(_col_i(c[3], 1, 10), 901)

    def test_blank_hu_on_a_present_card_defaults_to_one(self):
        """The cfg DEFAULTS give HU = 1.0 (no dissipation), so a blank HU on a
        card that IS there is 1.0, not 0."""
        _, starter = _convert(
            _deck(_mat181(card4=(0, "", 2.0)), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 1.0)

    def test_negative_pr_becomes_the_viscous_pressure_decay(self):
        """LAW88's own rule is `nu <= 0 -> beta = |nu|, nu := 0.495`
        (hm_read_mat88.F90:186-191), which IS LS-DYNA's PR <= 0 viscous
        pressure input — so PR goes into NU verbatim. dyna2rad writes NU = 0
        and loses it. Starter echo: "EXPONENTIAL FILTERING FREQUENCY (BETA) =
        5.0000000000000E-02" for PR = -0.05."""
        res, starter = _convert(_deck(_mat181(pr=-0.05), 181, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), -0.05)
        self.assertTrue([w for w in res.warnings
                         if "viscous" in w and "beta = 0.05" in w],
                        res.warnings)

    def test_hill_foam_branch_is_warned_loudly(self):
        """0 < PR < 0.49 selects LS-DYNA's COMPRESSIBLE Hill foam.
        ConvertMatL181ToMatL70 exists in the dyna2rad source but has NO CALLER,
        so every simplified foam silently becomes an incompressible rubber."""
        res, _ = _convert(_deck(_mat181(pr=0.3), 181, LC_LOAD))
        hits = [w for w in res.warnings if "Hill FOAM" in w]
        self.assertTrue(hits, res.warnings)
        self.assertIn("/MAT/LAW70", hits[0])

    def test_with_failure_card_is_parsed_and_warned(self):
        """_WITH_FAILURE inserts K/GAMA1/GAMA2/EH between card 2 and the
        optional card 4 — reading it wrong would shift LCUNLD. LAW88 has the
        matching KFAIL/GAM1/GAM2/EH, but only on the radioss2026 card."""
        res, starter = _convert(_deck(
            _mat181(kw="*MAT_SIMPLIFIED_RUBBER/FOAM_WITH_FAILURE",
                    failure=(0.8, 0.11, 0.22, 0.33),
                    card4=(902, 0.7, 2.0)), 181, LC_LOAD + LC_UNLD))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[2], 1, 10), 902)     # card 4 still found
        hits = [w for w in res.warnings if "_WITH_FAILURE" in w]
        self.assertTrue(hits, res.warnings)
        self.assertIn("KFAIL", hits[0])
        self.assertIn("radioss2026", hits[0])
        self.assertIn("GAMA1=0.11", hits[0])

    def test_prony_cards_become_visc_prony(self):
        res, starter = _convert(_deck(
            _mat181(card4=(0, 0.7, 2.0, 0.0, 1, 0),
                    prony=((50.0, 3.0, 0), (25.0, 12.0, ""))), 181, LC_LOAD))
        c = _fail_cards(_block(starter, "/VISC/PRONY/181"))
        self.assertEqual(_col_i(c[0], 1, 10), 2)
        self.assertEqual([_col_f(c[1], a, b) for a, b in
                          ((1, 20), (21, 40), (41, 60), (61, 80))],
                         [50.0, 3.0, 0.0, 0.0])
        self.assertEqual(_col_f(c[2], 1, 20), 25.0)
        self.assertTrue([w for w in res.warnings if "VISCO=1" in w],
                        res.warnings)

    def test_dropped_fields_are_warned(self):
        res, _ = _convert(_deck(
            _mat181(mu=0.1, g=1.2e6, sigf=4.5e4, rtype=1, avgopt=-0.002,
                    ref=1, prten=1), 181, LC_LOAD))
        for needle in ("MU=0.1", "G=1.2e+06", "RTYPE=1", "AVGOPT=-0.002",
                       "REF=1", "PRTEN=1"):
            with self.subTest(needle=needle):
                self.assertTrue([w for w in res.warnings if needle in w],
                                res.warnings)

    def test_log_log_option_is_warned(self):
        res, _ = _convert(_deck(
            _mat181(kw="*MAT_SIMPLIFIED_RUBBER/FOAM_LOG_LOG_INTERPOLATION"),
            181, LC_LOAD))
        self.assertTrue([w for w in res.warnings if "_LOG_LOG" in w],
                        res.warnings)

    def test_missing_loading_curve_warns_error_866(self):
        res, starter = _convert(_deck(_mat181(lc=0), 181))
        c = _cards(_block(starter, "/MAT/LAW88/181"))
        self.assertEqual(_col_i(c[1], 71, 80), 0)
        self.assertTrue([w for w in res.warnings if "ERROR 866" in w],
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE (183) -> /MAT/LAW88
# ═════════════════════════════════════════════════════════════════════════════

class Mat183Tests(unittest.TestCase):
    """Card 3 is MANDATORY here and is LCUNLD REF STOL — NOT the 181
    _WITH_FAILURE card — and card 1 has no REF/PRTEN, card 2 no PR."""

    def test_card_three_is_lcunld_ref_stol(self):
        _, starter = _convert(
            _deck(_mat183(lcunld=902, ref=1.0, stol=-1.0), 183,
                  LC_LOAD + LC_UNLD))
        c = _cards(_block(starter, "/MAT/LAW88/183"))
        self.assertEqual(_col_i(c[2], 1, 10), 902)             # FCT_ID_UN
        self.assertEqual(_col_i(c[1], 71, 80), 1)              # NL

    def test_no_pr_field_so_nu_is_zero(self):
        """MAT_183 is always incompressible — the card has no PR at all, and
        LAW88's NU = 0 makes the starter substitute 0.495."""
        _, starter = _convert(_deck(_mat183(), 183, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/183"))
        self.assertEqual(_col_f(c[1], 1, 20), 0.0)

    def test_tension_is_at_columns_81_90(self):
        _, starter = _convert(_deck(_mat183(tension=-1), 183, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/183"))
        self.assertEqual(_col_i(c[2], 81, 90), -1)

    def test_no_visc_prony(self):
        """MAT_183 has no Prony cards at all."""
        _, starter = _convert(_deck(_mat183(), 183, LC_LOAD))
        self.assertEqual(_blocks(starter, "/VISC/PRONY/183"), [])

    def test_specimen_normalization(self):
        """dyna2rad leaves radSFA/radSFO UNINITIALISED for MAT_183 when any of
        SGL/SW/ST is zero (CM:5165-5166, 5297) — undefined behaviour on the
        /MOVE_FUNCT scale. k2rad treats a blank dimension as 1.0."""
        _, starter = _convert(
            _deck(_mat183(sgl=4.0, sw=2.0, st=0.0), 183, LC_LOAD))
        c = _cards(_block(starter, "/MAT/LAW88/183"))
        pts = _funct(starter, _col_i(c[3], 1, 10))
        self.assertEqual(pts[1], (1.0 / 4.0, 100.0 / 2.0))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_SOFT_TISSUE (091) / _VISCO (092) -> /MAT/LAW42
# ═════════════════════════════════════════════════════════════════════════════

class Mat091Tests(unittest.TestCase):
    """dyna2rad p_ConvertMatL91_92 (CM:10973-11026) keeps ONLY the isotropic
    Mooney-Rivlin ground substance."""

    def test_mooney_rivlin_to_ogden_identity(self):
        """Mu_1 = 2*C1, alpha_1 = 2, Mu_2 = -2*C2, alpha_2 = -2 is the standard
        Mooney-Rivlin <-> Ogden identity for W = C1(I1-3) + C2(I2-3).
        GS = sum(mu_i*alpha_i) = 4*(C1+C2), so MU0 = 2*(C1+C2) — starter echo
        "INITIAL SHEAR MODULUS = 60.00000000000" for C1=20, C2=10."""
        _, starter = _convert(_solid_deck(_mat091(c1=20.0, c2=10.0), 91))
        c = _cards(_block(starter, "/MAT/LAW42/91"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 0.495)
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 40.0)      # 2*C1
        self.assertAlmostEqual(_col_f(c[2], 21, 40), -20.0)    # -2*C2
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 2.0)
        self.assertAlmostEqual(_col_f(c[4], 21, 40), -2.0)
        self.assertEqual(_col_i(c[1], 81, 90), 0)              # no Prony (091)

    def test_cards_three_and_four_are_not_mistaken_for_the_prony_cards(self):
        """Cards 3 (AOPT + the a/b fibre vectors) and 4 (LA1-3 MACF) are
        mandatory even for the NON-VISCO variant. The builder writes non-zero
        values on card 3 (2.0 1.0 ... 1.0), so a handler that read S1..S6 from
        the wrong card would emit M != 0 with Gamma_1 = 2.0 instead of no Prony
        arrays at all."""
        _, starter = _convert(_solid_deck(_mat091(), 91))
        c = _cards(_block(starter, "/MAT/LAW42/91"))
        self.assertEqual(_col_i(c[1], 81, 90), 0)              # M
        self.assertEqual(len(c), 6)                            # no Gamma/Tau

    def test_fibre_direction_warning_names_the_parsed_values(self):
        """AOPT and MACF are parsed off cards 3 and 4; the drop warning must
        report what it read, not a fixed list of field NAMES — otherwise the
        two fields are write-only and a parse regression is invisible."""
        res, _ = _convert(_solid_deck(_mat091(aopt=3.0, macf=2), 91))
        hits = [w for w in res.warnings if "fibre DIRECTION" in w]
        self.assertTrue(hits, res.warnings)
        self.assertIn("AOPT=3", hits[0])
        self.assertIn("MACF=2", hits[0])

    def test_visco_prony_arrays(self):
        """S_i/T_i go into LAW42's OWN Gamma_arr/Tau_arr (no /VISC/PRONY): both
        codes state relaxation TIMES, so T_i needs no inversion. Starter echo:
        "RELAXATION TIME = 1.0000000000000E-02"."""
        _, starter = _convert(_solid_deck(
            _mat091(kw="*MAT_SOFT_TISSUE_VISCO", mid=92,
                    s=(0.3, 0.2), t=(0.01, 0.05)), 92))
        c = _cards(_block(starter, "/MAT/LAW42/92"))
        self.assertEqual(_col_i(c[1], 81, 90), 2)              # M
        self.assertAlmostEqual(_col_f(c[6], 1, 20), 0.3)       # Gamma_1
        self.assertAlmostEqual(_col_f(c[6], 21, 40), 0.2)
        self.assertAlmostEqual(_col_f(c[7], 1, 20), 0.01)      # Tau_1
        self.assertAlmostEqual(_col_f(c[7], 21, 40), 0.05)
        self.assertEqual(_blocks(starter, "/VISC/PRONY/92"), [])

    def test_non_contiguous_prony_terms_are_compacted(self):
        """dyna2rad counts every non-zero S_i but then copies slots 0..M-1
        (CM:11010-11021), so S1=0 with S2,S3 set converts the WRONG terms — and
        it indexes an sdiDoubleList that was only reserve()d, not resize()d."""
        _, starter = _convert(_solid_deck(
            _mat091(kw="*MAT_SOFT_TISSUE_VISCO", mid=92,
                    s=(0.0, 0.4, 0.25), t=(0.0, 0.02, 0.09)), 92))
        c = _cards(_block(starter, "/MAT/LAW42/92"))
        self.assertEqual(_col_i(c[1], 81, 90), 2)
        self.assertAlmostEqual(_col_f(c[6], 1, 20), 0.4)
        self.assertAlmostEqual(_col_f(c[6], 21, 40), 0.25)
        self.assertAlmostEqual(_col_f(c[7], 1, 20), 0.02)
        self.assertAlmostEqual(_col_f(c[7], 21, 40), 0.09)

    def test_fibre_term_loss_is_warned_loudly(self):
        """For a ligament or tendon the fibre term dominates, so the converted
        isotropic rubber is NOT physically equivalent. dyna2rad says nothing."""
        res, _ = _convert(_solid_deck(_mat091(), 91))
        hits = [w for w in res.warnings if "NOT physically equivalent" in w]
        self.assertTrue(hits, res.warnings)
        for needle in ("C3=5", "C4=2", "C5=100", "XLAM=1.05", "FANG=30"):
            self.assertIn(needle, hits[0])

    def test_bulk_modulus_warning_states_the_substitute(self):
        """XK is dropped; LAW42 derives its bulk modulus from the hard-coded
        Nu = 0.495. Starter echo "BULK MODULUS = 5980.000000000" for
        C1=20/C2=10, i.e. GS*(1+Nu)/(3*(1-2*Nu)) with GS = 4*(C1+C2)."""
        res, _ = _convert(_solid_deck(_mat091(xk=2000.0), 91))
        hits = [w for w in res.warnings if "bulk modulus XK=2000" in w]
        self.assertTrue(hits, res.warnings)
        gs = 4.0 * (20.0 + 10.0)
        self.assertIn(f"{gs * 1.495 / (3.0 * 0.01):g}", hits[0])

    def test_failure_modes_are_warned(self):
        res, _ = _convert(_solid_deck(
            _mat091(failsf=1.4, failsm=1.2, failshr=0.8), 91))
        hits = [w for w in res.warnings if "FAILSF=1.4" in w]
        self.assertTrue(hits, res.warnings)
        self.assertIn("never", hits[0])

    def test_unit_mismatch_of_the_relaxation_factors_is_warned(self):
        """LS-DYNA's S_i are DIMENSIONLESS relaxation factors; Radioss
        multiplies Gamma_i by a strain-history term (sigeps42.F:475), i.e. it
        is a shear MODULUS. The warning must give the scaled values."""
        res, _ = _convert(_solid_deck(
            _mat091(kw="*MAT_SOFT_TISSUE_VISCO", mid=92, c1=20.0, c2=10.0,
                    s=(0.3, 0.2), t=(0.01, 0.05)), 92))
        hits = [w for w in res.warnings if "UNIT MISMATCH" in w]
        self.assertTrue(hits, res.warnings)
        mu0 = 2.0 * (20.0 + 10.0)
        self.assertIn(f"{0.3 * mu0:g}", hits[0])
        self.assertIn(f"{0.2 * mu0:g}", hits[0])


# ═════════════════════════════════════════════════════════════════════════════
# Routing map + id-namespace coverage
# ═════════════════════════════════════════════════════════════════════════════

class TargetMatLawTests(unittest.TestCase):
    """_target_mat_law is the ONE mid -> emitted-law map (writer/mesh.py); a
    family missing from it makes the beam-compat check silently `continue` AND
    makes writer/inistate.py's solid-/XREF gate treat the part as having no
    /MAT at all."""

    CASES = (
        (6, _mat006(), 34),
        (61, _mat061(), 40),
        (76, _mat076(), 42),
        (181, _mat181(), 88),
        (183, _mat183(), 88),
        (91, _mat091(), 42),
        (92, _mat091(kw="*MAT_SOFT_TISSUE_VISCO", mid=92,
                     s=(0.3,), t=(0.01,)), 42),
    )

    def test_every_new_family_is_mapped(self):
        from k2rad.writer.assembly import build_starter
        for mid, mat, law in self.CASES:
            with self.subTest(mid=mid, law=law):
                state = _dispatch(_solid_deck(mat, mid, LC_LOAD))
                build_starter(state)
                self.assertEqual(_target_mat_law(state, mid), law)

    def test_all_mat_ids_covers_the_new_containers(self):
        """next_mat_id() guards synthesized ids against all_mat_ids(); a family
        left out of that union is a starter ERROR 79 DUPLICATE ID waiting to
        happen."""
        deck = (NODES + SHELL + _part(6) + SECTION
                + _mat006() + _mat061() + _mat076() + _mat181() + _mat183()
                + _mat091()
                + _mat091(kw="*MAT_SOFT_TISSUE_VISCO", mid=92,
                          s=(0.3,), t=(0.01,))
                + LC_LOAD + END)
        state = _dispatch(deck)
        ids = state.all_mat_ids()
        for mid in (6, 61, 76, 181, 183, 91, 92):
            self.assertIn(mid, ids)

    def test_xref_whitelist_consequence(self):
        """LAW42 and LAW88 are BOTH in inistate._XREF_SOLID_LAWS, so a
        *MAT_076/091/092/181/183 solid part with an
        *INITIAL_FOAM_REFERENCE_GEOMETRY newly RECEIVES a /XREF (and its
        section switches to Ismstr=10); LAW34 and LAW40 are not on that list,
        so those parts are warn-skipped instead. Asserted rather than assumed —
        it is a behaviour change on any deck combining the two keywords."""
        from k2rad.writer.inistate import _XREF_SOLID_LAWS
        self.assertEqual({42, 88} & _XREF_SOLID_LAWS, {42, 88})
        self.assertEqual({34, 40} & _XREF_SOLID_LAWS, set())
        xref = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
                + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n"
                          for n, x, y, z in (
                              (1, 0.0, 0.0, 0.0), (2, 9.9, 0.0, 0.0),
                              (3, 9.9, 9.9, 0.0), (4, 0.0, 9.9, 0.0),
                              (5, 0.0, 0.0, 9.9), (6, 9.9, 0.0, 9.9),
                              (7, 9.9, 9.9, 9.9), (8, 0.0, 9.9, 9.9))))
        _, starter = _convert(_solid_deck(_mat091(), 91, xref))
        self.assertTrue(_blocks(starter, "/XREF/"), "LAW42 part lost its /XREF")
        res, starter = _convert(_solid_deck(_mat006(), 6, xref))
        self.assertEqual(_blocks(starter, "/XREF/"), [])
        self.assertTrue([w for w in res.warnings
                         if "/MAT/LAW34" in w and "ERROR 2014" in w],
                        res.warnings)

    def test_beam_compat_classification(self):
        """LAW34 is BEAM_INTEGRATED (hm_read_mat34.F:162) and already listed as
        TYPE18-only, so a *MAT_006 beam part on a plain /PROP/BEAM must be
        named with ERROR 3047 (property test), NOT the ERROR 3046 a
        PROP_BEAM=0 law gets. LAW40/42/88 declare no beam class at all."""
        from k2rad.writer.mesh import (_TYPE3_BEAM_LAWS,
                                       _TYPE18_ONLY_BEAM_LAWS)
        self.assertIn(34, _TYPE18_ONLY_BEAM_LAWS)
        for law in (40, 42, 88):
            self.assertNotIn(law, _TYPE3_BEAM_LAWS)
            self.assertNotIn(law, _TYPE18_ONLY_BEAM_LAWS)
        deck = (
            "*NODE\n"
            + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 0.0, 10.0, 0.0)))
            + "*ELEMENT_BEAM\n" + _row(1, 7, 1, 2, 3) + "\n"
            + "*PART\nbeam\n" + _row(7, 7, 6) + "\n"
            + "*SECTION_BEAM\n" + _row(7, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + _mat006() + END)
        res, _ = _convert(deck)
        self.assertTrue(any("/MAT/LAW34" in w and "ERROR 3047" in w
                            for w in res.warnings), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Multi-material deck + byte-identity
# ═════════════════════════════════════════════════════════════════════════════

class BatchIntegrationTests(unittest.TestCase):

    def test_all_seven_keywords_in_one_deck(self):
        """One part per keyword, every material referenced — the shape of the
        deck that was validated on a live starter run (0 ERROR(S), two
        cosmetic WARNING 1927 for the Itab=1 Prony fit)."""
        mids = [6, 61, 76, 77, 181, 183, 91, 92]
        nodes, nid = [], 1
        for i in range(len(mids) + 1):
            nodes.append((nid, 10.0 * i, 0.0, 0.0)); nid += 1
            nodes.append((nid, 10.0 * i, 10.0, 0.0)); nid += 1
        deck = "*NODE\n" + "".join(
            f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in nodes)
        shells, parts, sections = [], [], []
        for k, mid in enumerate(mids):
            pid, n1 = 100 + k, 1 + 2 * k
            shells.append(_row(pid, pid, n1, n1 + 2, n1 + 3, n1 + 1))
            parts.append(f"*PART\np{pid}\n" + _row(pid, pid, mid))
            sections.append(_row(pid, 2, 1.0, 5) + "\n"
                            + _row(1.2, 1.2, 1.2, 1.2))
        deck += ("*ELEMENT_SHELL\n" + "\n".join(shells) + "\n"
                 + "".join(p + "\n" for p in parts)
                 + "*SECTION_SHELL\n" + "\n".join(sections) + "\n"
                 + _mat006() + _mat061() + _mat076()
                 + _mat076(mid=77, lcid=801, nt=3, lcidk=802, ntk=3, prony=())
                 + _mat181(card4=(0, 0.7, 2.0, 0.0, 1, 0),
                           prony=((50.0, 3.0, 0),))
                 + _mat183(lcunld=902)
                 + _mat091()
                 + _mat091(kw="*MAT_SOFT_TISSUE_VISCO", mid=92,
                           s=(0.3, 0.2), t=(0.01, 0.05))
                 + LC_LOAD + LC_UNLD + LC_RELAX_G + LC_RELAX_K + END)
        res, starter = _convert(deck)
        for header in ("/MAT/LAW34/6", "/MAT/LAW40/61", "/MAT/LAW42/76",
                       "/MAT/LAW42/77", "/MAT/LAW88/181", "/MAT/LAW88/183",
                       "/MAT/LAW42/91", "/MAT/LAW42/92",
                       "/VISC/PRONY/76", "/VISC/PRONY/77", "/VISC/PRONY/181"):
            with self.subTest(header=header):
                self.assertTrue(_blocks(starter, header),
                                f"{header} missing from the converted deck")
        self.assertEqual(res.skipped_keywords, [])
        # No /VISC/PRONY without a /MAT of the same id — starter ERROR 1663.
        mat_ids = {ln.rsplit("/", 1)[1] for ln in starter.splitlines()
                   if ln.startswith("/MAT/LAW")}
        for ln in starter.splitlines():
            if ln.startswith("/VISC/PRONY/"):
                self.assertIn(ln.rsplit("/", 1)[1], mat_ids)
        # Every /MAT id is distinct — no family shadows another's dict entry.
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/MAT/LAW")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_goldens_are_unchanged(self):
        """A pure-addition batch adds no card to a deck that does not use the
        new keywords, so the five checked-in goldens must be byte-identical —
        if one moves, the change leaked into a shared emitter. The named risks
        here are _law42_lines (shared with MAT_007/027/077_O), the
        _emit_visc_prony/_emit_visc_prony_kv refactor onto the common
        _visc_prony_lines core (shared with MAT_077_H and MAT_124), and
        _make_functions' curve numbering, which the LAW88 specimen-normalized
        duplicates draw from."""
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


# ═════════════════════════════════════════════════════════════════════════════
# REF flags vs *INITIAL_FOAM_REFERENCE_GEOMETRY (/XREF)
# ═════════════════════════════════════════════════════════════════════════════

REF_GEOM = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
            + "".join(f"{n:>8}{0.0:>16}{0.0:>16}{0.0:>16}\n"
                      for n in range(1, 9)))


class RefFlagTests(unittest.TestCase):
    """MAT_181/183 (R17 p.2-1231 / p.2-1240) and MAT_091/092 (p.2-669) all
    carry REF — "use reference geometry to initialize the stress tensor",
    EQ.0.0 Off / EQ.1.0 On — and both convert to laws on the starter's
    solid-/XREF whitelist (LAW88 and LAW42), so the keyword really does reach
    them. Both directions must be reported:

      REF=1, no usable geometry  -> nothing is initialized (the four older
                                    rubber families already said so)
      REF=0, geometry present    -> a /XREF IS still emitted (dyna2rad's
                                    unconditional rule, kept so validated
                                    rubber decks do not move), which LS-DYNA
                                    would NOT apply

    The second case shipped SILENT for all six families, and for 181/183 the
    batch's own message said the opposite of what it emitted ("REF is DROPPED
    — REF needs *INITIAL_FOAM_REFERENCE_GEOMETRY for a real /XREF", printed on
    a run that wrote /XREF/7)."""

    def _mats(self):
        return (("*MAT_SIMPLIFIED_RUBBER/FOAM", 181,
                 lambda r: _mat181(ref=r), LC_LOAD),
                ("*MAT_SIMPLIFIED_RUBBER_WITH_DAMAGE", 183,
                 lambda r: _mat183(ref=r), LC_LOAD),
                ("*MAT_SOFT_TISSUE", 91, lambda r: _mat091(ref=r), ""))

    def test_ref_zero_with_reference_geometry_warns_and_still_emits(self):
        for kw, mid, build, extra in self._mats():
            with self.subTest(kw=kw):
                res, starter = _convert(
                    _solid_deck(build(0), mid, extra + REF_GEOM))
                self.assertTrue(_blocks(starter, "/XREF/7"),
                                "the /XREF must still be emitted")
                hits = [w for w in res.warnings
                        if "REF=0" in w and "/XREF" in w]
                self.assertTrue(hits, res.warnings)
                self.assertIn(f"mid={mid}", hits[0])

    def test_ref_one_without_reference_geometry_is_diagnosed(self):
        for kw, mid, build, extra in self._mats():
            with self.subTest(kw=kw):
                res, starter = _convert(_solid_deck(build(1), mid, extra))
                self.assertEqual(_blocks(starter, "/XREF/7"), [])
                self.assertTrue(
                    [w for w in res.warnings
                     if f"mid={mid}" in w and "REF=1" in w
                     and "INITIAL_FOAM_REFERENCE_GEOMETRY" in w],
                    res.warnings)

    def test_ref_one_with_geometry_is_the_quiet_case(self):
        """REF=1 + coverage is what the flag asks for — no REF complaint."""
        for kw, mid, build, extra in self._mats():
            with self.subTest(kw=kw):
                res, starter = _convert(
                    _solid_deck(build(1), mid, extra + REF_GEOM))
                self.assertTrue(_blocks(starter, "/XREF/7"))
                self.assertFalse([w for w in res.warnings
                                  if "REF=0" in w or "REF=1" in w],
                                 res.warnings)

    def test_mat181_no_longer_calls_ref_a_dropped_field(self):
        """The old message listed REF alongside PRTEN/STOL/HISOUT/VFLAG as
        having no counterpart — while the same run wrote the /XREF."""
        res, _ = _convert(_deck(_mat181(ref=1, prten=1), 181, LC_LOAD))
        hits = [w for w in res.warnings if "are DROPPED" in w and "PRTEN" in w]
        self.assertTrue(hits, res.warnings)
        self.assertNotIn("REF=", hits[0])
        # REF=1 is still reported — by the pass that knows what it means.
        self.assertTrue([w for w in res.warnings
                         if "REF=1" in w
                         and "INITIAL_FOAM_REFERENCE_GEOMETRY" in w],
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *INCLUDE_TRANSFORM id offsets (the two hand-written callables)
# ═════════════════════════════════════════════════════════════════════════════

class IncludeTransformOffsetTests(unittest.TestCase):
    """_off_mat_006 and _off_mat_181 are the only two offset callables in this
    batch that are not a fixed cell list, and both key off content: MAT_006
    offsets a cell by IDFOFF only when it is NEGATIVE (a temperature-curve id
    hiding in a modulus field), and MAT_181 shifts the unloading-card index by
    one more when _WITH_FAILURE inserted a card. Registry membership alone
    cannot catch either — replacing MAT_181's
    `3 if "_WITH_FAILURE" in b.keyword else 2` with a constant 2 leaves the
    whole suite green while rewriting a Feng-Hallquist K as a curve id."""

    def _child_deck(self, mat: str, extra: str = "") -> str:
        return "*KEYWORD\n" + mat + extra + "*END\n"

    def _convert_with_transform(self, mat: str, extra: str,
                                idmoff: int, idfoff: int):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        child = os.path.join(tmp.name, "child.k")
        with open(child, "w") as fh:
            fh.write(self._child_deck(mat, extra))
        master = os.path.join(tmp.name, "master.k")
        with open(master, "w") as fh:
            # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF
            fh.write("*KEYWORD\n"
                     "*INCLUDE_TRANSFORM\n"
                     "child.k\n"
                     + _row(0, 0, 0, idmoff, 0, idfoff) + "\n"
                     + "*END\n")
        state = ConversionState()
        for block in parse_k_file(master):
            dispatch(block, state)
        return state

    def test_mat006_offsets_the_id_and_only_the_negative_curve_cells(self):
        """MID by IDMOFF; a NEGATIVE BULK/G0/GI/BETA is a *DEFINE_CURVE id and
        moves by IDFOFF (staying negative); positive moduli must NOT move."""
        mat = ("*MAT_VISCOELASTIC\n"
               + _row(6, "1.1E-9", -951, -950, 20.0, 300.0) + "\n")
        state = self._convert_with_transform(mat, "", 4000, 6000)
        m = state.mat_viscoelastic[4006]
        self.assertEqual(m.mid, 4006)
        self.assertEqual(m.bulk, -6951.0)
        self.assertEqual(m.g0, -6950.0)
        self.assertEqual(m.gi, 20.0)          # positive modulus untouched
        self.assertEqual(m.beta, 300.0)

    def test_mat181_with_failure_shifts_the_unloading_card(self):
        """_WITH_FAILURE inserts K/GAMA1/GAMA2/EH, so the LCUNLD card is one
        row later. Offsetting the wrong row would rewrite K as a curve id."""
        mat = _mat181(kw="*MAT_SIMPLIFIED_RUBBER/FOAM_WITH_FAILURE",
                      lc=901, failure=(0.8, 0.11, 0.22, 0.33),
                      card4=(902, 0.7, 2.0))
        state = self._convert_with_transform(mat, "", 4000, 6000)
        m = state.mat_simplified_rubber[4181]
        self.assertEqual(m.mid, 4181)
        self.assertEqual(m.lc_tbid, 6901)
        self.assertEqual(m.lcunld, 6902)
        self.assertEqual(m.kfail, 0.8)        # failure card left alone
        self.assertEqual(m.gama1, 0.11)

    def test_mat181_without_failure_offsets_the_earlier_unloading_card(self):
        mat = _mat181(lc=901, card4=(902, 0.7, 2.0))
        state = self._convert_with_transform(mat, "", 4000, 6000)
        m = state.mat_simplified_rubber[4181]
        self.assertEqual(m.lc_tbid, 6901)
        self.assertEqual(m.lcunld, 6902)

    def test_mat183_and_mat076_curve_cells_offset(self):
        state = self._convert_with_transform(
            _mat183(lc=901, lcunld=902), "", 4000, 6000)
        m = state.mat_simplified_rubber[4183]
        self.assertEqual(m.lc_tbid, 6901)
        self.assertEqual(m.lcunld, 6902)
        state = self._convert_with_transform(
            _mat076(lcid=801, nt=3, lcidk=802, ntk=3, prony=()), "",
            4000, 6000)
        m = state.mat_general_visco[4076]
        self.assertEqual(m.lcid, 6801)
        self.assertEqual(m.lcidk, 6802)


if __name__ == "__main__":
    unittest.main()
