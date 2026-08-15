"""Tests for the ADHESIVES / COHESIVE BATCH conversions:

  *MAT_COHESIVE_MIXED_MODE (138)              -> /MAT/LAW117
  *MAT_ARUP_ADHESIVE (169)                    -> /MAT/LAW169 (radioss2025 card)
  *MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE -> /MAT/LAW116
      (240; _THERMAL/_3MODES/_FUNCTIONS variants warn-skip)
  *MAT_TOUGHENED_ADHESIVE_POLYMER (252)       -> /MAT/LAW120 (TAPO)
  *MAT_ADD_DAMAGE_DIEM                        -> /FAIL/INIEVO (rider by MID)
  *SECTION_SOLID ELFORM +/-19/20/+/-21/22     -> /PROP/TYPE43 (CONNECT),
      plus the dyna2rad material route (a SOLID_COHESIVE law such as
      *MAT_ARUP_ADHESIVE on an ordinary ELFORM 1 brick section)

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_viscoelastic.py, tests/test_metal_plasticity_2.py and
tests/test_spotweld_joining.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant is recomputed by hand in the test rather than copied from the
implementation: the MAT_138 ultimate-displacement identity TN = 2*GIC/UND
(and its inverse deltaF = 2*GIC/TN == UND), the starter's GIC floor
TN^2/(2*EN) staying below the emitted GIC, the DIEM NUMFIP -> PTHICKFAIL
fraction -NUMFIP/100 and count/NIP forms, and the Q1 table collapse to the
minimum of the (y+OFFO)*SFO ordinates.

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic — INTFAIL=0 being LS-DYNA's never-delete state that Radioss
coerces into delete-at-first-IP, LAW169's integer PWRT/PWRS truncating a
float exponent, MAT_240's LCG1C making LS-DYNA ignore the very scalars k2rad
copies, DCTYP=-1 damage that LS-DYNA keeps OFF the stress — the assertion
pins the warning that states it. Two dyna2rad defects are FIXED consciously
and asserted as fixes: the MAT_240 mode-II rate gate (d2r keys on EDOT_G2<0,
a transcription slip; k2rad keys on G2C_0<0 like mode I and the manual) and
the MAT_252 JCFL/DOPT flag maps (d2r's switch tests `== 2`, dead code — the
legal value 1 fell through to the wrong engine branch, verified against
sigeps120_*.F:108-111).

Every emitted card in this batch was validated on a live OpenRadioss starter
run (starter_win64, /BEGIN 2022, np=1): 0 ERROR(S), exit 0, the only batch
warning being the documented non-fatal WARNING 100211 for /MAT/LAW169
("Unsupported option ... in format < 2025" — the card is then parsed with
the 2025 layout; a /BEGIN 2025 control run echoes identical fields). The
starter's own listing confirmed the field-by-field placement asserted below —
notably LAW169's "SLOPE OF YIELD SURFACE AT ZERO TENSION = 0.5" for the
SHT_SL mid-card slot, LAW116's "REFERENCE STRAIN RATE FOR GC IN MOD II = 0"
with EDOT_G2=0.4 on the card (the fixed gate), LAW120's "ITRX: FAILURE
DEPENDENCY ON TRIAXIALITY = 1" for JCFL=1, INIEVO's PTHICKFAIL=-0.3 for
NUMFIP=-30, and /PROP/TYPE43's "SMALL STRAIN FLAG = 1". A physics check that
could FAIL: the LAW117 part's rigid-body mass came back 1.1E-7 = RHO*AREA
exactly (1.1E-9 * 100), proving Imass=1 area-mass reached the element init
(volume mass would read 2.2E-7). And a NEGATIVE control — LAW36 paired with
the ELFORM 19 section — makes the same starter answer exit 2 with
"ERROR ID: 3047 ... PROPERTY ID 100 OF TYPE 43 IS NOT COMPATIBLE WITH
MATERIAL ID 5 OF TYPE 36", the exact refusal the pairing warning names.
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


# ── Harness (same shape as tests/test_viscoelastic.py) ───────────────────────

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


def _fail_cards(block):
    """A /FAIL block's data lines — no title line."""
    return [ln for ln in block[1:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(res, needle: str):
    return [w for w in res.warnings if needle in w]


# ── Decks ────────────────────────────────────────────────────────────────────

def _hex_nodes(top_z: float = 2.0) -> str:
    """One brick: nodes 1-4 bottom face z=0, 5-8 top face z=top_z (the LS-DYNA
    AND /PROP/TYPE43 cohesive convention — thickness from face 1234 to 5678).
    top_z=0.0 gives the zero-thickness cohesive pad (distinct ids, coincident
    coordinates)."""
    pts = [(1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
           (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
           (5, 0.0, 0.0, top_z), (6, 10.0, 0.0, top_z),
           (7, 10.0, 10.0, top_z), (8, 0.0, 10.0, top_z)]
    return "*NODE\n" + "".join(
        f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in pts)


SOLID = "*ELEMENT_SOLID\n" + _row(1, 7) + "\n" + _row(*range(1, 9)) + "\n"
SHELL_NODES = (
    "*NODE\n"
    + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0))))
SHELL = "*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
END = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n"


def _part(mid: int, secid: int = 7, pid: int = 7) -> str:
    return "*PART\ncohesive part\n" + _row(pid, secid, mid) + "\n"


def _sec_solid(elform: int, secid: int = 7) -> str:
    return "*SECTION_SOLID\n" + _row(secid, elform) + "\n"


SEC_SHELL = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 5) + "\n"
             + _row(1.2, 1.2, 1.2, 1.2) + "\n")


def _cohesive_deck(mat: str, mid: int, elform: int = 19,
                   extra: str = "") -> str:
    return (_hex_nodes() + SOLID + _part(mid) + _sec_solid(elform)
            + mat + extra + END)


def _shell_deck(mat: str, mid: int, extra: str = "") -> str:
    return SHELL_NODES + SHELL + _part(mid) + SEC_SHELL + mat + extra + END


def _mat138(kw="*MAT_COHESIVE_MIXED_MODE", mid=1, rho="1.1E-9", roflg=1,
            intfail=2, en=2000.0, et=1000.0, gic=0.2, giic=0.5,
            xmu=2.2, t=0.0, s=12.0, und=0.02, utd=0.0, gamma=1.2) -> str:
    return (kw + "\n"
            + _row(mid, rho, roflg, intfail, en, et, gic, giic) + "\n"
            + _row(xmu, t, s, und, utd, gamma) + "\n")


def _mat169(kw="*MAT_ARUP_ADHESIVE", mid=3, rho="1.3E-9", e=2000.0, pr=0.35,
            tenmax=40.0, gcten=4.0, shrmax=20.0, gcshr=2.0,
            pwrt=2.0, pwrs=2.0, shrp=0.2, sht_sl=0.5, edot0="", edot2="",
            thkdir="", extra="", more=()) -> str:
    deck = (kw + "\n"
            + _row(mid, rho, e, pr, tenmax, gcten, shrmax, gcshr) + "\n"
            + _row(pwrt, pwrs, shrp, sht_sl, edot0, edot2, thkdir, extra)
            + "\n")
    for card in more:
        deck += _row(*card) + "\n"
    return deck


def _mat240(kw="*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE", mid=2,
            rho="1.2E-9", roflg=0, intfail=2, emod=3000.0, gmod=1200.0,
            thick=0.2, inicrt="",
            c2=(-0.6, 1.4, 0.5, -25.0, 40.0, 0.8, -0.7, ""),
            c3=(0.9, 1.1, 0.4, 20.0, "", "", 0.55, ""),
            c4=None) -> str:
    deck = (kw + "\n"
            + _row(mid, rho, roflg, intfail, emod, gmod, thick, inicrt) + "\n"
            + _row(*c2) + "\n" + _row(*c3) + "\n")
    if c4 is not None:
        deck += _row(*c4) + "\n"
    return deck


def _mat252(kw="*MAT_TOUGHENED_ADHESIVE_POLYMER", mid=4, rho="1.4E-9",
            e=2400.0, pr=0.38, flg=2, jcfl=1, dopt=1,
            lcss="", tau0=25.0, q=15.0, b=0.6, h=12.0, c=0.01,
            gam0=0.001, gamm=0.005,
            a10=0.1, a20=0.2, a1h=0.3, a2h=0.4, a2s=0.5, pow_=1.8,
            srfilt="", ihis="", d1=0.3, d2=0.7, d3=1.9, d4=0.02,
            d1c=0.25, d2c=0.65) -> str:
    return (kw + "\n"
            + _row(mid, rho, e, pr, flg, jcfl, dopt) + "\n"
            + _row(lcss, tau0, q, b, h, c, gam0, gamm) + "\n"
            + _row(a10, a20, a1h, a2h, a2s, pow_, "", srfilt) + "\n"
            + _row(ihis, "", d1, d2, d3, d4, d1c, d2c) + "\n")


def _diem(mid=5, ndiemc=1, dinit="", deps="", numfip="", volfrac="",
          criteria=((0, 501, "", "", "", ""),
                    (0, 0, 0.08, "", "", ""))) -> str:
    """criteria = flat tuple pairs: (DITYP P1 P2 P3 P4 P5), (DETYP DCTYP Q1
    Q2 Q3 Q4), repeated per criterion."""
    deck = ("*MAT_ADD_DAMAGE_DIEM\n"
            + _row(mid, ndiemc, dinit, deps, numfip, volfrac) + "\n")
    for card in criteria:
        deck += _row(*card) + "\n"
    return deck


def _curve(lcid: int, pts, sfo="", offo="") -> str:
    return ("*DEFINE_CURVE\n" + _row(lcid, "", "", sfo, "", offo) + "\n"
            + "".join(f"{x:>20}{y:>20}\n" for x, y in pts))


LC_TRIAX = _curve(501, ((-0.33, 0.5), (0.0, 0.4), (0.33, 0.3), (0.66, 0.25)))
LC_SIZE = _curve(502, ((1.0, 1.0), (10.0, 1.2)))
LC_YLD = _curve(801, ((0.0, 25.0), (0.5, 40.0)))
MAT024 = ("*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
          + _row(5, "7.8E-9", 210000.0, 0.3, 355.0, 1000.0) + "\n"
          + _row(0.0, 0.0) + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / keyword registry
# ═════════════════════════════════════════════════════════════════════════════

class DispatchTests(unittest.TestCase):
    """Every documented keyword, option spelling and numeric alias reaches its
    handler. The dispatcher is an EXACT dict match after only
    _ID/_TITLE/_SUBTITLE are stripped, so every MAT_240 option spelling needs
    its own key — and for MAT_240 a missing key is worse than a generic skip:
    the variant would fall into skipped_keywords with no hint that its cards
    hold curve ids the base parse would have read as modulus floats. The
    numeric aliases *MAT_138 and *MAT_252 are absent from dyna2rad's own
    keyword table (broken Convert1To1 fallback: no /MAT, no message); k2rad
    registers them."""

    def test_every_spelling_is_registered(self):
        for kw in ("MAT_COHESIVE_MIXED_MODE", "MAT_138",
                   "MAT_ARUP_ADHESIVE", "MAT_169",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_3MODES",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_FUNCTIONS",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL_3MODES",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_FUNCTIONS"
                   "_3MODES",
                   "MAT_240", "MAT_240_THERMAL", "MAT_240_3MODES",
                   "MAT_TOUGHENED_ADHESIVE_POLYMER", "MAT_252",
                   "MAT_ADD_DAMAGE_DIEM", "SECTION_SOLID_MISC"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_offset_specs_cover_every_spelling(self):
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("MAT_COHESIVE_MIXED_MODE", "MAT_138",
                   "MAT_ARUP_ADHESIVE", "MAT_169",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL",
                   "MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL"
                   "_3MODES",
                   "MAT_240", "MAT_240_FUNCTIONS",
                   "MAT_TOUGHENED_ADHESIVE_POLYMER", "MAT_252",
                   "MAT_ADD_DAMAGE_DIEM", "SECTION_SOLID_MISC"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_title_option_is_stripped_and_read(self):
        cases = (
            ("*MAT_COHESIVE_MIXED_MODE_TITLE", 1, "cohesive 138",
             _mat138(kw="*MAT_COHESIVE_MIXED_MODE_TITLE\ncohesive 138")),
            ("*MAT_ARUP_ADHESIVE_TITLE", 3, "arup bond",
             "*MAT_ARUP_ADHESIVE_TITLE\narup bond\n"
             + _mat169().split("\n", 1)[1]),
            ("*MAT_240_TITLE", 2, "epr bond",
             "*MAT_240_TITLE\nepr bond\n" + _mat240().split("\n", 1)[1]),
            ("*MAT_252_TITLE", 4, "tapo bond",
             "*MAT_252_TITLE\ntapo bond\n" + _mat252().split("\n", 1)[1]),
        )
        for kw, mid, title, mat in cases:
            with self.subTest(kw=kw):
                elform = 1 if mid in (3, 4) else 19
                _, starter = _convert(_cohesive_deck(mat, mid, elform))
                self.assertIn(title, starter.splitlines(),
                              f"{kw} title line not emitted")

    def test_diem_title_variant_parses(self):
        """_TITLE on the DIEM rider consumes one line; /FAIL has no title
        card, so the only observable is that the criteria still parse."""
        diem = ("*MAT_ADD_DAMAGE_DIEM_TITLE\ndiem title\n"
                + _row(5, 1, "", "", "", "") + "\n"
                + _row(0, 501) + "\n" + _row(0, 0, 0.08) + "\n")
        state = _dispatch(_shell_deck(MAT024, 5, diem + LC_TRIAX))
        self.assertIn(5, state.fail_diem)
        self.assertEqual(state.fail_diem[5].criteria[0].p1, 501)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_COHESIVE_MIXED_MODE (138) -> /MAT/LAW117
# ═════════════════════════════════════════════════════════════════════════════

class Mat138Tests(unittest.TestCase):
    """/MAT/LAW117 layout (mat117.cfg FORMAT(radioss2022) — NOT the 2021
    block, which has no Fct_TN/Fct_TT/Fscale_x card): C1 RHO_I(1-20) /
    C2 EN(1-20) ET(21-40) Imass(41-50) Idel(51-60) Irupt(61-70) /
    C3 Fct_TN(1-10) Fct_TT(11-20) TN(21-40) TT(41-60) Fscale_x(61-80) /
    C4 GIC(1-20) GIIC(21-40) EXP_G(41-60) EXP_BK(61-80) GAMMA(81-100)."""

    def test_card_columns_power_law(self):
        _, starter = _convert(_cohesive_deck(_mat138(t=30.0, und=0.0), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertEqual(len(c), 4)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.1e-9)
        self.assertEqual(len(c[0].rstrip()), 20)
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 2000.0)   # EN
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 1000.0)  # ET
        self.assertEqual(_col_i(c[1], 41, 50), 1)             # Imass (ROFLG=1)
        self.assertEqual(_col_i(c[1], 51, 60), 2)             # Idel = INTFAIL
        self.assertEqual(_col_i(c[1], 61, 70), 1)             # Irupt: XMU>0
        self.assertEqual(_col_i(c[2], 1, 10), 0)              # Fct_TN
        self.assertEqual(_col_i(c[2], 11, 20), 0)             # Fct_TT
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 30.0)    # TN scalar
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 12.0)    # TT scalar
        self.assertAlmostEqual(_col_f(c[2], 61, 80), 0.0)     # Fscale_x
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 0.2)      # GIC
        self.assertAlmostEqual(_col_f(c[3], 21, 40), 0.5)     # GIIC
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 2.2)     # EXP_G = XMU
        self.assertAlmostEqual(_col_f(c[3], 61, 80), 0.0)     # EXP_BK
        self.assertAlmostEqual(_col_f(c[3], 81, 100), 1.2)    # GAMMA

    def test_xmu_sign_is_the_bk_switch(self):
        """XMU < 0 selects Benzeggagh-Kenane with exponent |XMU|: Irupt=2 and
        EXP_BK written explicitly (EXP_BK has NO starter default — leaving it
        0 under Irupt=2 is a zero exponent, not a default). A converter that
        copies XMU straight into EXP_G loses the whole B-K case."""
        _, starter = _convert(_cohesive_deck(_mat138(xmu=-1.45), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertEqual(_col_i(c[1], 61, 70), 2)             # Irupt = B-K
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 0.0)     # EXP_G
        self.assertAlmostEqual(_col_f(c[3], 61, 80), 1.45)    # EXP_BK = |XMU|

    def test_und_backcomputes_tn(self):
        """T=0 with UND>0: LS-DYNA back-computes the traction-separation
        triangle from GIC = T*UND/2, i.e. TN = 2*GIC/UND. Hand math:
        GIC=0.2, UND=0.02 -> TN = 2*0.2/0.02 = 20; the inverse ultimate
        displacement 2*GIC/TN = 0.02 recovers UND exactly; and the starter's
        GIC floor TN^2/(2*EN) = 400/4000 = 0.1 stays below the emitted
        GIC=0.2, so no starter auto-raise (WARNING 3016) is triggered by a
        consistent input set."""
        tn = 2.0 * 0.2 / 0.02
        self.assertAlmostEqual(tn, 20.0)
        self.assertAlmostEqual(2.0 * 0.2 / tn, 0.02)          # deltaF == UND
        self.assertLessEqual(tn ** 2 / (2.0 * 2000.0), 0.2)   # starter floor
        _, starter = _convert(_cohesive_deck(_mat138(), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 20.0)

    def test_utd_backcomputes_tt(self):
        """S=0 with UTD>0: TT = 2*GIIC/UTD = 2*0.5/0.05 = 20."""
        _, starter = _convert(
            _cohesive_deck(_mat138(s=0.0, utd=0.05), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 2.0 * 0.5 / 0.05)

    def test_curve_valued_t_suppresses_the_und_fallback(self):
        """T < 0: |T| is a peak-traction-vs-element-size curve -> Fct_TN with
        TMAX_N = 1.0, and the UND fallback must NOT overwrite that 1.0 (the
        dyna2rad curve branch sets lsdT=1.0 exactly to suppress it)."""
        _, starter = _convert(_cohesive_deck(
            _mat138(t=-77.0), 1, extra=_curve(77, ((1.0, 30.0), (5.0, 20.0)))))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertEqual(_col_i(c[2], 1, 10), 77)
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 1.0)

    def test_missing_t_curve_warns(self):
        res, _ = _convert(_cohesive_deck(_mat138(t=-77.0), 1))
        self.assertTrue(any("77" in w and "dangle" in w
                            for w in _warns(res, "*MAT_COHESIVE_MIXED_MODE")),
                        res.warnings)

    def test_roflg_maps_to_imass_volume_and_area(self):
        """ROFLG=0 (LS-DYNA default, volume density) MUST become the explicit
        Imass=2: the starter coerces a blank/0 Imass to 1 = AREA density
        (hm_read_mat117.F:140), which would silently flip the default. The
        starter run measured the difference: area mass RHO*A = 1.1e-7 vs
        volume mass RHO*V = 2.2e-7 on the validation brick."""
        for roflg, imass in ((0, 2), (1, 1)):
            with self.subTest(roflg=roflg):
                _, starter = _convert(
                    _cohesive_deck(_mat138(roflg=roflg), 1))
                c = _cards(_block(starter, "/MAT/LAW117/1"))
                self.assertEqual(_col_i(c[1], 41, 50), imass)

    def test_intfail_semantics(self):
        """INTFAIL=0 is LS-DYNA's NEVER-delete state — inexpressible (starter
        coerces Idel 0->1) and warned; negative INTFAIL is the Newton-Cotes
        scheme, only the count |INTFAIL| carries (warned); positive counts
        copy through. dyna2rad copies the raw float and says nothing."""
        res, starter = _convert(_cohesive_deck(_mat138(intfail=0), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertEqual(_col_i(c[1], 51, 60), 0)
        self.assertTrue(any("NEVER deleted" in w and "Idel 0 -> 1" in w
                            for w in res.warnings), res.warnings)
        res, starter = _convert(_cohesive_deck(_mat138(intfail=-3), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertEqual(_col_i(c[1], 51, 60), 3)
        self.assertTrue(_warns(res, "Newton-Cotes"), res.warnings)
        res, starter = _convert(_cohesive_deck(_mat138(intfail=4), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertEqual(_col_i(c[1], 51, 60), 4)

    def test_negative_gic_is_a_curve_id_not_a_toughness(self):
        """GIC < 0 references an element-size curve (R13 form); LAW117 has no
        curve slot, so emitting the negative number as a toughness would be
        silently wrong — the field is zeroed (the starter then floors it with
        its own WARNING 3016) and warned. The TN fallback must see the ZEROED
        value: with GIC dropped there is no 2*GIC/UND to compute."""
        res, starter = _convert(_cohesive_deck(_mat138(gic=-9.0), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 0.0)
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 0.0)     # no TN fallback
        self.assertTrue(any("GIC=-9" in w and "WARNING 3016" in w
                            for w in res.warnings), res.warnings)
        self.assertTrue(_warns(res, "no peak normal traction"), res.warnings)

    def test_zero_shear_traction_warns_like_the_normal_side(self):
        """The TT=0 mirror of the TN warning — and worse in the starter:
        hm_read_mat117.F:162-166 derives DELTA0S = TT/ET, then
        UTD = 2*GIIC/(DELTA0S*ET) — a DIVISION BY ZERO in the derived
        ultimate displacement when TT lands 0."""
        res, starter = _convert(_cohesive_deck(_mat138(s=0.0, utd=0.0), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 0.0)     # TT written 0
        self.assertTrue(any("no peak shear traction" in w
                            and "DELTA0S" in w for w in res.warnings),
                        res.warnings)

    def test_gamma_copies_raw(self):
        """GAMMA 0 stays 0 (starter default 1.0 = the LS-DYNA default);
        dyna2rad's `GAMMA==0 -> 2` branch is dead code — its post-handler
        attribMap copy overwrites it (CM:6357 vs CM:609)."""
        _, starter = _convert(_cohesive_deck(_mat138(gamma=""), 1))
        c = _cards(_block(starter, "/MAT/LAW117/1"))
        self.assertAlmostEqual(_col_f(c[3], 81, 100), 1.0)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_ARUP_ADHESIVE (169) -> /MAT/LAW169
# ═════════════════════════════════════════════════════════════════════════════

class Mat169Tests(unittest.TestCase):
    """/MAT/LAW169 layout (radioss2025/MAT/LAW169.cfg, the card's only FORMAT
    block): C1 Rho_I(1-20) / C2 E(1-20) PR(21-40) SHT_SL(41-60) TENMAX(61-80)
    GCTEN(81-100) / C3 SHRMAX(1-20) GCSHR(21-40) PWRT(41-50,int)
    PWRS(51-60,int) SHRP(61-80)."""

    def test_card_columns_and_the_sht_sl_position_trap(self):
        """SHT_SL sits in the MIDDLE of LAW169 card 2 (between PR and TENMAX)
        while *MAT_169 has it on card 2 field 4 — a positional copy is wrong.
        Starter echo: 'SLOPE OF YIELD SURFACE AT ZERO TENSION = 0.5'."""
        _, starter = _convert(_cohesive_deck(_mat169(), 3, elform=1))
        c = _cards(_block(starter, "/MAT/LAW169/3"))
        self.assertEqual(len(c), 3)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.3e-9)
        self.assertEqual(len(c[0].rstrip()), 20)
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 2000.0)   # E
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.35)    # PR
        self.assertAlmostEqual(_col_f(c[1], 41, 60), 0.5)     # SHT_SL (!)
        self.assertAlmostEqual(_col_f(c[1], 61, 80), 40.0)    # TENMAX
        self.assertAlmostEqual(_col_f(c[1], 81, 100), 4.0)    # GCTEN
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 20.0)     # SHRMAX
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 2.0)     # GCSHR
        self.assertEqual(_col_i(c[2], 41, 50), 2)             # PWRT int
        self.assertEqual(_col_i(c[2], 51, 60), 2)             # PWRS int
        self.assertAlmostEqual(_col_f(c[2], 61, 80), 0.2)     # SHRP

    def test_non_integer_power_is_rounded_and_warned(self):
        """PWRT/PWRS are %10lg floats in LS-DYNA (default 2.0) but %10d
        INTEGERS in LAW169 — 3.7 must land as 4, with the warning naming the
        exponent change (dyna2rad truncates via its float->int attribute
        conversion and says nothing)."""
        res, starter = _convert(
            _cohesive_deck(_mat169(pwrs=3.7), 3, elform=1))
        c = _cards(_block(starter, "/MAT/LAW169/3"))
        self.assertEqual(_col_i(c[2], 51, 60), 4)
        self.assertTrue(any("PWRS=3.7" in w and "ROUNDED to 4" in w
                            for w in res.warnings), res.warnings)

    def test_negative_strength_is_a_curve_id(self):
        """TENMAX < 0 is the function form (R9.0+); LAW169 has no curve
        inputs, so the field is blanked to the 1e20 no-failure default and
        the warning says exactly that consequence."""
        res, starter = _convert(
            _cohesive_deck(_mat169(tenmax=-333.0), 3, elform=1))
        c = _cards(_block(starter, "/MAT/LAW169/3"))
        self.assertAlmostEqual(_col_f(c[1], 61, 80), 0.0)
        self.assertTrue(any("TENMAX=-333" in w and "NO TENMAX failure" in w
                            for w in res.warnings), res.warnings)

    def test_negative_shrp_names_the_plateau_not_a_1e20_default(self):
        """SHRP is the shear PLATEAU RATIO, absent from LAW169.cfg's
        DEFAULTS(COMMON) block — its blank default is 0 (no plateau), NOT
        the 1e20 no-failure value the four strengths/energies get. The
        curve-form drop must say that consequence, not claim a 'no SHRP
        failure' that does not exist."""
        res, starter = _convert(
            _cohesive_deck(_mat169(shrp=-77.0), 3, elform=1))
        c = _cards(_block(starter, "/MAT/LAW169/3"))
        self.assertAlmostEqual(_col_f(c[2], 61, 80), 0.0)
        self.assertTrue(any("SHRP=-77" in w and "NO shear plateau" in w
                            for w in res.warnings), res.warnings)
        self.assertFalse(any("SHRP" in w and "1e20" in w
                             for w in res.warnings), res.warnings)

    def test_rate_edge_and_bthk_cards_walk_and_warn(self):
        """EXTRA=3 + EDOT2!=0 activates ALL conditional cards in the order
        3,4,5,6 (the EDOT2 card sits BETWEEN the edge cards and the BTHK
        card). The walk must stride them and the drops must be warned; BTHK
        is read off card 6 across the two edge cards AND the rate card.
        THKDIR=1 (bond normal from face 1234 to 5678) IS /PROP/TYPE43's
        convention, so it must NOT warn."""
        mat = _mat169(edot0=1.0, edot2=0.001, thkdir=1, extra=3, more=(
            (50.0, 5.0, 25.0, 2.5, 2.0, 2.0),        # card 3: edge strengths
            (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),          # card 4: edge factors
            (1.1, 1.2, 1.0, 1.0),                    # card 5: SDFAC...
            (0.42, 0.0, 0.0, 0.0),                   # card 6: BTHK
        ))
        res, starter = _convert(_cohesive_deck(mat, 3, elform=1))
        self.assertTrue(_blocks(starter, "/MAT/LAW169/3"))
        self.assertTrue(any("EDOT2=0.001" in w and "RATE-INDEPENDENT" in w
                            for w in res.warnings), res.warnings)
        self.assertTrue(any("EXTRA=3" in w and "edge" in w
                            for w in res.warnings), res.warnings)
        self.assertTrue(any("BTHK=0.42" in w for w in res.warnings),
                        res.warnings)
        self.assertFalse(_warns(res, "THKDIR"), res.warnings)

    def test_thkdir_default_warns_the_orientation_trap(self):
        """THKDIR=0 (the LS-DYNA DEFAULT, blank field): the bond normal is
        the SMALLEST element dimension ('Unless THKDIR = 1, the smallest
        dimension of the element is assumed to be the through-thickness
        dimension of the bond', R16 p.2-1128); /PROP/TYPE43 always uses face
        1234->5678. An element whose smallest dimension is another axis gets
        its traction-separation directions rotated 90 deg with no starter
        complaint — the DEFAULT case must warn, the THKDIR=1 case (asserted
        above) must not. Guard direction matters: warning on !=0 instead
        would silence every deck that relied on the default."""
        res, _ = _convert(_cohesive_deck(_mat169(), 3, elform=1))
        self.assertTrue(any("THKDIR=0" in w and "SMALLEST" in w
                            and "90 deg" in w for w in res.warnings),
                        res.warnings)

    def test_version_gate_warning_names_100211(self):
        """LAW169 exists only from the radioss2025 profile. Under the emitted
        /BEGIN 2022 the starter prints non-fatal WARNING 100211 and parses
        the card with the 2025 layout anyway (measured: byte-identical field
        echo vs a /BEGIN 2025 run, NORMAL TERMINATION) — the k2rad warning
        must say so, or the starter output reads as a conversion defect."""
        res, _ = _convert(_cohesive_deck(_mat169(), 3, elform=1))
        self.assertTrue(any("WARNING 100211" in w and "non-fatal" in w
                            for w in res.warnings), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE (240) -> /MAT/LAW116
# ═════════════════════════════════════════════════════════════════════════════

class Mat240Tests(unittest.TestCase):
    """/MAT/LAW116 layout (mat116.cfg FORMAT(radioss2021), no 2022 revision):
    C1 RHO_I / C2 E(1-20) G(21-40) Thick(41-60) Imass(61-70) Idel(71-80)
    Icrit(81-90) / C3 GC1_ini GC1_inf SRATG1 FG1 / C4 GC2... / C5 SIGA1
    SIGB1 SRATE1 ORDER1(61-70) FAIL1(71-80) / C6 SIGA2 ...

    E/G are TRUE moduli — the starter divides by Thick itself (UPARAM(1) =
    E/THICK, hm_read_mat116.F:197), unlike LAW117's per-length EN/ET, so the
    emitter must NOT divide (the divide-twice trap)."""

    def test_card_columns_and_rate_forms(self):
        """Mode I: G1C_0=-0.6 < 0 activates the rate branch -> GC1_ini=0.6,
        GC1_inf=|1.4|, SRATG1=0.5. T0=-25 < 0 with T1=40 > 0 selects the
        quadratic-log yield interpolation -> ORDER1=2; FG1=-0.7 < 0 selects
        the displacement-ratio failure criterion -> FAIL1=2, FG1=0.7.
        Sanity of the probe values against the starter's own FG1 gate
        (WARNING 1825 if FG1 >= 1 - SIGA1^2/(2*E*GC1_ini)): 1 - 625/
        (2*3000*0.6) = 1 - 0.1736 = 0.826 > 0.7, so the set is consistent."""
        self.assertLess(0.7, 1.0 - 25.0 ** 2 / (2.0 * 3000.0 * 0.6))
        _, starter = _convert(_cohesive_deck(_mat240(), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertEqual(len(c), 6)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.2e-9)
        self.assertEqual(len(c[0].rstrip()), 20)
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 3000.0)   # E (true modulus)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 1200.0)  # G
        self.assertAlmostEqual(_col_f(c[1], 41, 60), 0.2)     # Thick
        self.assertEqual(_col_i(c[1], 61, 70), 2)             # Imass (ROFLG=0)
        self.assertEqual(_col_i(c[1], 71, 80), 2)             # Idel = |INTFAIL|
        self.assertEqual(_col_i(c[1], 81, 90), 0)             # Icrit (INICRT=0)
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 0.6)      # GC1_ini
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 1.4)     # GC1_inf
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 0.5)     # SRATG1
        self.assertAlmostEqual(_col_f(c[2], 61, 80), 0.7)     # FG1 = |FG1|
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 25.0)     # SIGA1 = |T0|
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 40.0)    # SIGB1
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 0.8)     # SRATE1
        self.assertEqual(_col_i(c[4], 61, 70), 2)             # ORDER1
        self.assertEqual(_col_i(c[4], 71, 80), 2)             # FAIL1 (FG1<0)

    def test_mode2_rate_gate_is_g2c0_not_edot_g2(self):
        """CONSCIOUS FIX of dyna2rad: d2r gates the mode-II rate fields on
        EDOT_G2 < 0 (convertmats.cxx:6715) — a slip against both its own
        mode-I branch and the LS-DYNA manual (G2C_0 <= 0 activates the rate
        branch; EDOT_G2 is a positive reference rate). Two directions:

        (a) G2C_0 < 0 with a positive EDOT_G2 — a VALID rate-dependent deck —
            must keep GC2_inf and SRATG2 (d2r zeroes both);
        (b) G2C_0 > 0 with EDOT_G2 set — static mode II — must zero them
            (d2r would smuggle a negative EDOT_G2 through as-is)."""
        _, starter = _convert(_cohesive_deck(
            _mat240(c3=(-0.9, 1.1, 0.4, 20.0, "", "", 0.55, "")), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 0.9)      # GC2_ini
        self.assertAlmostEqual(_col_f(c[3], 21, 40), 1.1)     # GC2_inf kept
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 0.4)     # SRATG2 kept
        _, starter = _convert(_cohesive_deck(_mat240(), 2))   # G2C_0 = +0.9
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertAlmostEqual(_col_f(c[3], 21, 40), 0.0)     # GC2_inf zeroed
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 0.0)     # SRATG2 zeroed

    def test_static_yield_and_linear_log_order(self):
        """T0 >= 0: no yield rate dependence -> ORDER 0 (starter default 1);
        T0 < 0 with T1 < 0: linear-log -> ORDER1=1. SRATE follows |T1| > 0."""
        _, starter = _convert(_cohesive_deck(
            _mat240(c2=(-0.6, 1.4, 0.5, -25.0, -40.0, 0.8, 0.7, "")), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertEqual(_col_i(c[4], 61, 70), 1)             # linear-log
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 40.0)    # SIGB1 = |T1|
        self.assertEqual(_col_i(c[4], 71, 80), 1)             # FAIL1 (FG1>0)
        _, starter = _convert(_cohesive_deck(
            _mat240(c2=(0.6, "", "", 25.0, "", "", 0.7, "")), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertEqual(_col_i(c[4], 61, 70), 0)
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 0.0)     # SRATE1 off

    def test_static_t0_zeroes_stale_rate_terms(self):
        """T1/EDOT_T are 'only considered if T0 < 0' (R16 p.2-1545; same for
        S1/EDOT_S vs S0) — LS-DYNA runs a CONSTANT yield at the static
        limit whatever sits in them. The LAW116 engine has no such gate: it
        activates rate hardening for ANY SIGB > 0 (sigeps116.F:143, and the
        starter fills ORDER 0 -> 1), so a raw copy of a stale T1 adds a
        yield rate term LS-DYNA never ran (live-confirmed in the starter
        echo: S0=+30/S1=7/EDOT_S=0.003 echoed as an active
        'DYNAMIC YIELD 7 / ORDER 1'). SIGB/SRATE must be zeroed on T0>=0,
        warned; dyna2rad copies them through (CM:6725)."""
        res, starter = _convert(_cohesive_deck(
            _mat240(c2=(0.6, "", "", 25.0, 40.0, 0.8, 0.7, ""),
                    c3=(0.9, "", "", 30.0, 7.0, 0.003, 0.55, "")), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 25.0)     # SIGA1 = T0
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 0.0)     # SIGB1 zeroed
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 0.0)     # SRATE1 zeroed
        self.assertAlmostEqual(_col_f(c[5], 1, 20), 30.0)     # SIGA2 = S0
        self.assertAlmostEqual(_col_f(c[5], 21, 40), 0.0)     # SIGB2 zeroed
        self.assertAlmostEqual(_col_f(c[5], 41, 60), 0.0)     # SRATE2 zeroed
        self.assertTrue(any("mode I (T0)" in w and "only" in w.lower()
                            and "zeroed" in w for w in res.warnings),
                        res.warnings)
        self.assertTrue(any("mode II (S0)" in w for w in res.warnings),
                        res.warnings)
        # The rate-dependent form (T0 < 0) must be untouched by the gate —
        # covered field-by-field in test_card_columns_and_rate_forms; the
        # static form with BLANK T1 must not warn.
        res, _ = _convert(_cohesive_deck(
            _mat240(c2=(0.6, "", "", 25.0, "", "", 0.7, ""),
                    c3=(0.9, "", "", 30.0, "", "", 0.55, "")), 2))
        self.assertFalse(any("static yield" in w for w in res.warnings),
                         res.warnings)

    def test_fg_zero_warns_the_starter_auto_disable(self):
        """FG=0 (or GC_ini=0) makes the STARTER disable that mode's failure
        (hm_read_mat116.F:147-148, IFAIL:=0) — a converter that stays silent
        ships a cohesive that never softens in that mode."""
        res, _ = _convert(_cohesive_deck(
            _mat240(c3=(0.9, "", "", 20.0, "", "", "", "")), 2))
        self.assertTrue(any("FG2=0" in w and "never softens" in w
                            for w in res.warnings), res.warnings)

    def test_inicrt_maps_to_icrit(self):
        """INICRT=1 (max nominal stress) -> Icrit=2, verified against the
        engine kernel (sigeps116.F:226: ICRIT==1 is the quadratic interaction
        branch, everything else the pure-mode maximum). dyna2rad never reads
        the field (its cfg calls it OUTPUT). Negative INICRT (flexible
        exponent) has no LAW116 slot -> warned, default kept."""
        _, starter = _convert(_cohesive_deck(_mat240(inicrt=1), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertEqual(_col_i(c[1], 81, 90), 2)
        res, starter = _convert(_cohesive_deck(_mat240(inicrt=-2.5), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertEqual(_col_i(c[1], 81, 90), 0)
        self.assertTrue(any("INICRT=-2.5" in w for w in res.warnings),
                        res.warnings)

    def test_thick_zero_semantic_gap_is_warned(self):
        """LS-DYNA THICK=0 = per-element geometric thickness; LAW116 THICK=0
        = 1.0 LENGTH UNIT (hm_read_mat116.F:149-152). Stiffness E/THICK
        diverges silently unless warned."""
        res, _ = _convert(_cohesive_deck(_mat240(thick=""), 2))
        self.assertTrue(any("THICK=0" in w and "1.0 LENGTH UNIT" in w
                            for w in res.warnings), res.warnings)

    def test_negative_thick_is_written_zero_not_copied(self):
        """LS-DYNA THICK 'LE.0.0: initial thickness is calculated from nodal
        coordinates' — zero and negative are the SAME state there. The
        starter's default guard is `IF (THICK == ZERO)` only, so a raw
        negative copy survives to UPARAM(1)=E/THICK as a NEGATIVE stiffness.
        Must emit 0.0 (starter default 1.0 length unit) and warn."""
        res, starter = _convert(_cohesive_deck(_mat240(thick=-0.3), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertAlmostEqual(_col_f(c[1], 41, 60), 0.0)
        self.assertTrue(any("THICK=-0.3" in w and "NEGATIVE stiffness" in w
                            for w in res.warnings), res.warnings)

    def test_lcg_curve_override_is_loudly_warned(self):
        """LCG1C set: LS-DYNA IGNORES G1C_0/G1C_INF and uses the thickness
        curve — the scalars k2rad emits are then NOT what the LS-DYNA run
        used. The warning must say that, not just 'dropped'."""
        res, _ = _convert(_cohesive_deck(
            _mat240(c2=(-0.6, 1.4, 0.5, -25.0, 40.0, 0.8, -0.7, 901)), 2))
        self.assertTrue(any("LCG1C=901" in w and "IGNORES" in w
                            for w in res.warnings), res.warnings)

    def test_optional_card6_fields_warn(self):
        """The RFILTF/COMPY/SMOLIM/XMU card is the manual's Card 6 (cards
        4/5 are the _3MODES mode-III cards) — parsed at position 4 of the
        option-free spelling."""
        res, _ = _convert(_cohesive_deck(
            _mat240(c4=(1000.0, 1.0, 0.05, 1.2)), 2))
        self.assertTrue(any("card 6" in w and "RFILTF=1000" in w
                            for w in res.warnings), res.warnings)

    def test_thermal_variant_warn_skips(self):
        """_THERMAL turns EMOD/GMOD/G*C_0/T0/S0/FG* into curve ids — parsing
        them as the base card would read curve ids as moduli. The variant is
        warn-skipped: no /MAT, a warning naming the dangling part, an entry
        in recognized_not_emitted, and NOT in skipped_keywords (it was
        recognized). dyna2rad drops these with no message at all."""
        mat = ("*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL\n"
               + _row(2, "1.2E-9", 0, 2, 701, 702, 0.2, "") + "\n"
               + _row(703, "", "", 704, "", "", 705, "") + "\n"
               + _row(706, "", "", 707, "", "", 708, "") + "\n")
        res, starter = _convert(_cohesive_deck(mat, 2))
        self.assertEqual(_blocks(starter, "/MAT/LAW116/"), [])
        self.assertTrue(any("THERMAL" in w and "SKIPPED" in w
                            for w in res.warnings), res.warnings)
        self.assertNotIn("MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL",
                         res.skipped_keywords)
        self.assertTrue([kw for kw, _r in res.recognized_not_emitted
                         if "THERMAL" in kw], res.recognized_not_emitted)

    def test_intfail_count_is_transferred_not_collapsed(self):
        """CONSCIOUS FIX of dyna2rad: d2r maps ANY positive INTFAIL to Idel=1
        (convertmats.cxx:6754), so INTFAIL=4 (delete only when all four IPs
        fail) became delete-on-first-IP — a ~4x over-erosion of the bondline.
        k2rad transfers the count."""
        _, starter = _convert(_cohesive_deck(_mat240(intfail=4), 2))
        c = _cards(_block(starter, "/MAT/LAW116/2"))
        self.assertEqual(_col_i(c[1], 71, 80), 4)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_TOUGHENED_ADHESIVE_POLYMER (252) -> /MAT/LAW120 (TAPO)
# ═════════════════════════════════════════════════════════════════════════════

class Mat252Tests(unittest.TestCase):
    """/MAT/LAW120 layout (mat120_tapo.cfg FORMAT(radioss2022)): C1 RHO_I
    (cols 21-40 MUST stay blank — CARD_PREREAD reference-density trap) /
    C2 E nu Iform(41-50) Itrx(51-60) Idam(61-70) blank(71-80) THICK(81-100) /
    C3 Table_Id(1-10) Xscale(11-30) Yscale(31-50) / C4 T0 Q Beta H /
    C5 AF1 AF2 AH1 AH2 AS / C6 C EPSD0 EPSDF / C7 D1C D2C D1F D2F /
    C8 Dtrx Djc EXP_N."""

    def test_card_columns(self):
        _, starter = _convert(_cohesive_deck(_mat252(), 4, elform=1))
        c = _cards(_block(starter, "/MAT/LAW120/4"))
        self.assertEqual(len(c), 8)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.4e-9)
        self.assertEqual(len(c[0].rstrip()), 20)              # PREREAD trap
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 2400.0)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.38)
        self.assertEqual(_col_i(c[1], 41, 50), 2)             # Iform (FLG=2)
        self.assertEqual(_col_i(c[1], 51, 60), 1)             # Itrx  (JCFL=1)
        self.assertEqual(_col_i(c[1], 61, 70), 1)             # Idam  (DOPT=1)
        self.assertEqual(c[1][70:80].strip(), "")             # blank 71-80
        self.assertAlmostEqual(_col_f(c[1], 81, 100), 0.0)    # THICK
        self.assertEqual(_col_i(c[2], 1, 10), 0)              # Table_Id
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 25.0)     # T0
        self.assertAlmostEqual(_col_f(c[3], 21, 40), 15.0)    # Q
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 0.6)     # Beta = B
        self.assertAlmostEqual(_col_f(c[3], 61, 80), 12.0)    # H
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 0.1)      # AF1 = A10
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 0.2)     # AF2 = A20
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 0.3)     # AH1 = A1H
        self.assertAlmostEqual(_col_f(c[4], 61, 80), 0.4)     # AH2 = A2H
        self.assertAlmostEqual(_col_f(c[4], 81, 100), 0.5)    # AS  = A2S
        self.assertAlmostEqual(_col_f(c[5], 1, 20), 0.01)     # C
        self.assertAlmostEqual(_col_f(c[5], 21, 40), 0.001)   # EPSD0 = GAM0
        self.assertAlmostEqual(_col_f(c[5], 41, 60), 0.005)   # EPSDF = GAMM
        self.assertAlmostEqual(_col_f(c[6], 1, 20), 0.25)     # D1C
        self.assertAlmostEqual(_col_f(c[6], 21, 40), 0.65)    # D2C
        self.assertAlmostEqual(_col_f(c[6], 41, 60), 0.3)     # D1F = D1
        self.assertAlmostEqual(_col_f(c[6], 61, 80), 0.7)     # D2F = D2
        self.assertAlmostEqual(_col_f(c[7], 1, 20), 1.9)      # Dtrx = D3
        self.assertAlmostEqual(_col_f(c[7], 21, 40), 0.02)    # Djc = D4
        self.assertAlmostEqual(_col_f(c[7], 41, 60), 1.8)     # EXP_N = POW

    def test_flag_maps_fix_the_dyna2rad_dead_branches(self):
        """Verified against the engine kernels (sigeps120_*.F:108-111:
        ITRX=1 pressure-dependent for ALL T / ITRX=2 no dependency for T<0;
        IDAM=1 plain arc length / IDAM=2 scaled damage plastic strain):
        JCFL 0->Itrx 2, 1->Itrx 1; DOPT 0->Idam 2, 1->Idam 1; FLG 0->1,
        2->2. dyna2rad's switch tests JCFL==2/DOPT==2 — DEAD branches (the
        fields are 0/1 in LS-DYNA), so its JCFL=1 decks silently ran with
        tension-only triaxiality. Starter echo confirmed 'ITRX: FAILURE
        DEPENDENCY ON TRIAXIALITY = 1' for JCFL=1."""
        for flg, jcfl, dopt, iform, itrx, idam in (
                (0, 0, 0, 1, 2, 2),
                (2, 1, 1, 2, 1, 1)):
            with self.subTest(flg=flg, jcfl=jcfl, dopt=dopt):
                _, starter = _convert(_cohesive_deck(
                    _mat252(flg=flg, jcfl=jcfl, dopt=dopt), 4, elform=1))
                c = _cards(_block(starter, "/MAT/LAW120/4"))
                self.assertEqual(_col_i(c[1], 41, 50), iform)
                self.assertEqual(_col_i(c[1], 51, 60), itrx)
                self.assertEqual(_col_i(c[1], 61, 70), idam)

    def test_lcss_curve_is_rerouted_to_a_1d_table(self):
        """LAW120's Table_Id is a TABLE slot: a *DEFINE_CURVE named there
        must be emitted as a 1-D /TABLE/1 (with the mandatory '#dimension'
        card), not a /FUNCT — the LAW76/LAW52 mechanism. Both codes ignore
        the analytic TAU0..GAMM when the table is set (LS-DYNA drops them;
        the LAW120 reader zeroes them, hm_read_mat120.F:183-189), so the
        analytic fields still copy through unchanged."""
        _, starter = _convert(_cohesive_deck(
            _mat252(lcss=801), 4, elform=1, extra=LC_YLD))
        c = _cards(_block(starter, "/MAT/LAW120/4"))
        self.assertEqual(_col_i(c[2], 1, 10), 801)
        tab = _block(starter, "/TABLE/1/801")
        self.assertEqual(_blocks(starter, "/FUNCT/801"), [])
        self.assertIn("#dimension", tab[2])
        self.assertAlmostEqual(_col_f(c[3], 1, 20), 25.0)     # T0 still copied

    def test_missing_lcss_warns_error_779(self):
        res, _ = _convert(_cohesive_deck(_mat252(lcss=888), 4, elform=1))
        self.assertTrue(any("LCSS=888" in w and "ERROR 779" in w
                            for w in res.warnings), res.warnings)

    def test_srfilt_and_ihis_parse_from_the_r16_positions(self):
        """The local Altair R7.1 cfg blanks card-3 col 71-80 (SRFILT) and
        card-4 col 1-10 (IHIS) — parsing with it drops both SILENTLY. k2rad
        parses the R16 manual layout and warns each."""
        res, _ = _convert(_cohesive_deck(
            _mat252(srfilt=1000.0, ihis=1.0), 4, elform=1))
        self.assertTrue(any("SRFILT=1000" in w for w in res.warnings),
                        res.warnings)
        self.assertTrue(any("IHIS=1" in w for w in res.warnings),
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_ADD_DAMAGE_DIEM -> /FAIL/INIEVO
# ═════════════════════════════════════════════════════════════════════════════

class DiemTests(unittest.TestCase):
    """/FAIL/INIEVO layout (fail_inievo.cfg FORMAT(radioss2022)): C1
    NINIEVO(1-10) ISHEAR(11-20) ILEN(21-30) blank(31-70) FAILIP(71-80)
    PTHICKFAIL(81-100), then EXACTLY four lines per criterion: INITYPE/
    EVOTYPE/EVOSHAP/COMPTYP (4x10) / TAB_ID(1-10) SR_REF(11-30) FSCALE(31-50)
    PARAM(51-70) / TAB_EL(1-10) EL_REF(11-30) ELSCAL(31-50) / DISP(1-20)
    ALPHA(21-40) ENER(41-60) — DISP, ALPHA, ENER, not the order the
    starter's own listing prints."""

    def _one(self, diem_kw: str, extra: str = ""):
        res, starter = _convert(_shell_deck(MAT024, 5,
                                            diem_kw + LC_TRIAX + LC_SIZE
                                            + extra))
        return res, starter

    def test_inievo_structure_and_columns(self):
        res, starter = self._one(_diem(
            numfip=-30,
            criteria=((0, 501, "", "", "", 502),
                      (0, 0, 0.08, "", 1.5, ""))))
        blk = _block(starter, "/FAIL/INIEVO/5")
        c = _fail_cards(blk)
        self.assertEqual(len(c), 1 + 4)               # header + 4 per criterion
        self.assertEqual(_col_i(c[0], 1, 10), 1)      # NINIEVO
        self.assertEqual(_col_i(c[0], 11, 20), 1)     # ISHEAR (P4=0 -> 1)
        self.assertEqual(_col_i(c[0], 21, 30), 0)     # ILEN
        self.assertEqual(c[0][30:70].strip(), "")     # blank 31-70
        self.assertEqual(_col_i(c[0], 71, 80), 0)     # FAILIP (no solid use)
        # NUMFIP=-30 -> PTHICKFAIL = -30/100 = -0.3 (fraction of failed IPs)
        self.assertAlmostEqual(_col_f(c[0], 81, 100), -30.0 / 100.0)
        self.assertEqual(_col_i(c[1], 1, 10), 1)      # INITYPE = DITYP+1
        self.assertEqual(_col_i(c[1], 11, 20), 1)     # EVOTYPE = DETYP+1
        self.assertEqual(_col_i(c[1], 21, 30), 2)     # EVOSHAP (Q3>0)
        self.assertEqual(_col_i(c[1], 31, 40), 1)     # COMPTYP = DCTYP+1
        self.assertEqual(_col_i(c[2], 1, 10), 501)    # TAB_ID = P1
        self.assertAlmostEqual(_col_f(c[2], 11, 30), 0.0)   # SR_REF
        self.assertAlmostEqual(_col_f(c[2], 31, 50), 0.0)   # FSCALE
        self.assertAlmostEqual(_col_f(c[2], 51, 70), 0.0)   # PARAM (DITYP 0)
        self.assertEqual(_col_i(c[3], 1, 10), 502)    # TAB_EL = P5
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 0.08)   # DISP
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 1.5)   # ALPHA
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 0.0)   # ENER
        # P1/P5 are TABLE slots: the curves must re-emit as 1-D /TABLE/1.
        self.assertTrue(_blocks(starter, "/TABLE/1/501"))
        self.assertTrue(_blocks(starter, "/TABLE/1/502"))
        self.assertEqual(_blocks(starter, "/FUNCT/501"), [])

    def test_dityp_to_initype_all_five(self):
        """DITYP 0..4 -> INITYPE 1..5, SAME criterion order (ductile-triax,
        shear, MSFLD, FLD, ductile-normalized-principal). P2 reaches PARAM
        for DITYP 1/4, P3 for DITYP 2/3."""
        for dityp, initype, p2, p3, param in (
                (0, 1, "", "", 0.0), (1, 2, 0.3, "", 0.3),
                (2, 3, "", 1.0, 1.0), (3, 4, "", 1.0, 1.0),
                (4, 5, 0.7, "", 0.7)):
            with self.subTest(dityp=dityp):
                _, starter = self._one(_diem(
                    criteria=((dityp, 501, p2, p3, "", ""),
                              (0, 0, 0.08, "", "", ""))))
                c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
                self.assertEqual(_col_i(c[1], 1, 10), initype)
                self.assertAlmostEqual(_col_f(c[2], 51, 70), param)

    def test_numfip_count_form_uses_the_section_nip(self):
        """NUMFIP=2 on a NIP=5 shell: PTHICKFAIL = -min(2/5, 1) = -0.4 —
        the count converted to a failed-IP fraction through the *SECTION_
        SHELL NIP, the same GENE1 rule (engine fail_setoff_c.F reads
        Pthk<0 as count/NPTT >= |Pthk|)."""
        _, starter = self._one(_diem(numfip=2))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertAlmostEqual(_col_f(c[0], 81, 100), -2.0 / 5.0)

    def test_numfip_solid_use_fills_failip(self):
        """A SOLID part on the MID: NUMFIP>0 is the failed-IP count ->
        FAILIP, resolved from the parts that reference the MID (dyna2rad
        instead uses whole-model element counts and whatever *PART happened
        to convert last for NIP)."""
        deck = (_hex_nodes() + SOLID + _part(5) + _sec_solid(1)
                + MAT024 + _diem(numfip=2,
                                 criteria=((0, 501, "", "", "", ""),
                                           (0, 0, 0.08, "", "", "")))
                + LC_TRIAX + END)
        _, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertEqual(_col_i(c[0], 71, 80), 2)
        self.assertAlmostEqual(_col_f(c[0], 81, 100), 0.0)   # no shell use

    def test_numfip_below_minus_100_is_clamped_not_reinterpreted(self):
        """_numfip_to_pthickfail carries *MAT_ADD_EROSION's 'NUMFIP < -100
        -> (|NUMFIP|-100) integration points' convention; DIEM has NO such
        form — LT.0 is a percentage of layers ONLY (R16 p.2-56). A raw
        NUMFIP=-102 through the helper would silently become '2 IPs' =
        PTHICKFAIL -min(2/5, 1) = -0.4 on this NIP=5 section; DIEM must
        clamp to -100 % (all layers, -1.0) WITH a warning naming the
        missing convention."""
        res, starter = self._one(_diem(numfip=-102))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertAlmostEqual(_col_f(c[0], 81, 100), -1.0)
        self.assertTrue(any("NUMFIP=-102" in w and "PERCENTAGE" in w
                            and "clamped" in w for w in res.warnings),
                        res.warnings)

    def test_p1_log_rate_table_warns_the_axis_convention(self):
        """R16, every DITYP: 'If the first strain rate value in the table is
        negative, it is assumed to be given with respect to logarithmic
        strain rate' — /TABLE interpolation reads the same abscissae as
        LITERAL rates, silently changing the rate axis. A P1 table whose
        first (sorted-ascending) rate value is negative must warn; a plain
        positive-rate table must not."""
        curves = (_curve(511, ((0.0, 0.4), (0.5, 0.3)))
                  + _curve(512, ((0.0, 0.5), (0.5, 0.4))))
        table = ("*DEFINE_TABLE\n" + _row(510) + "\n"
                 + f"{-6.9:>20}\n{0.0:>20}\n")     # log(0.001), log(1.0)
        res, starter = self._one(
            _diem(criteria=((0, 510, "", "", "", ""),
                            (0, 0, 0.08, "", "", ""))),
            extra=table + curves)
        self.assertTrue(_blocks(starter, "/TABLE/1/510"))
        self.assertTrue(any("P1 table 510" in w and "LOGARITHMIC" in w
                            for w in res.warnings), res.warnings)
        table_pos = ("*DEFINE_TABLE\n" + _row(510) + "\n"
                     + f"{0.001:>20}\n{1.0:>20}\n")
        res, _ = self._one(
            _diem(criteria=((0, 510, "", "", "", ""),
                            (0, 0, 0.08, "", "", ""))),
            extra=table_pos + curves)
        self.assertFalse(any("LOGARITHMIC" in w for w in res.warnings),
                         res.warnings)

    def test_ishear_inversion_and_conflict(self):
        """LS-DYNA P4=0 INCLUDES the transverse shear stresses; Radioss
        ISHEAR=1 CONSIDERS them (hm_read_fail_inievo.F:291-293) — the flags
        have opposite sense, so P4=1 -> ISHEAR=0. ISHEAR is GLOBAL but P4 is
        per-criterion: on conflict the last criterion wins (dyna2rad parity,
        CM:10273 writes it inside the loop) and k2rad warns."""
        res, starter = self._one(_diem(
            ndiemc=2,
            criteria=((0, 501, "", "", 0.0, ""), (0, 0, 0.08, "", "", ""),
                      (1, 501, 0.3, "", 1.0, ""), (1, 1, 0.9, "", "", ""))))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertEqual(_col_i(c[0], 11, 20), 0)     # last wins (P4=1 -> 0)
        self.assertTrue(any("disagree on P4" in w and "last" in w.lower()
                            for w in res.warnings), res.warnings)

    def test_q1_table_collapses_to_the_minimum_ordinate(self):
        """DETYP=0 with Q1=-503: |Q1| is a displacement table; INIEVO DISP is
        scalar, so it collapses to the MINIMUM ordinate (dyna2rad's rule,
        CM:10399/10473 — min over (y+OFFO)*SFO). k2rad bakes SFO/OFFO into
        the parsed points, so with SFO=2, OFFO=0.01 over raw ordinates
        (0.1, 0.06, 0.09) the minimum is (0.06+0.01)*2 = 0.14 — hand-
        computed here, not read back from the code."""
        pts = ((-0.33, 0.1), (0.0, 0.06), (0.33, 0.09))
        expected = min((y + 0.01) * 2.0 for _, y in pts)
        self.assertAlmostEqual(expected, 0.14)
        res, starter = self._one(
            _diem(criteria=((0, 501, "", "", "", ""),
                            (0, 0, -503, "", "", ""))),
            extra=_curve(503, pts, sfo=2.0, offo=0.01))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertAlmostEqual(_col_f(c[4], 1, 20), expected)
        self.assertTrue(any("COLLAPSED" in w and "0.14" in w
                            for w in res.warnings), res.warnings)

    def test_energy_evolution(self):
        """DETYP=1: Q1 is the fracture energy -> ENER (col 41-60 of line 5,
        NOT col 21-40 — the DISP, ALPHA, ENER order trap); EVOTYPE=2."""
        _, starter = self._one(_diem(
            criteria=((1, 501, 0.3, "", "", ""), (1, 1, 0.9, "", "", ""))))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertEqual(_col_i(c[1], 11, 20), 2)
        self.assertEqual(_col_i(c[1], 31, 40), 2)     # COMPTYP (DCTYP=1)
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 0.0)
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 0.9)

    def test_zero_q1_names_the_starter_error(self):
        for detyp, err in ((0, "ERROR 2089"), (1, "ERROR 2090")):
            with self.subTest(detyp=detyp):
                res, _ = self._one(_diem(
                    criteria=((0, 501, "", "", "", ""),
                              (detyp, 0, 0.0, "", "", ""))))
                self.assertTrue(_warns(res, err), res.warnings)

    def test_p1_zero_names_error_2088(self):
        res, _ = self._one(_diem(criteria=((0, 0, "", "", "", ""),
                                           (0, 0, 0.08, "", "", ""))))
        self.assertTrue(any("P1=0" in w and "ERROR 2088" in w
                            for w in res.warnings), res.warnings)

    def test_dctyp_minus_one_has_no_counterpart(self):
        """DCTYP=-1 keeps the damage OFF the stress in LS-DYNA (bookkeeping
        only); INIEVO always couples — the conversion changes physics, so the
        warning must say the criterion now softens."""
        res, starter = self._one(_diem(
            criteria=((0, 501, "", "", "", ""), (0, -1, 0.08, "", "", ""))))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertEqual(_col_i(c[1], 31, 40), 0)
        self.assertTrue(any("DCTYP=-1" in w and "DOES soften" in w
                            for w in res.warnings), res.warnings)

    def test_q4_and_dinit_and_volfrac_warn(self):
        res, _ = self._one(_diem(
            dinit=0.1, volfrac=0.6,
            criteria=((0, 501, "", "", "", ""),
                      (0, 0, 0.08, "", "", 502))))
        self.assertTrue(_warns(res, "DINIT=0.1"), res.warnings)
        self.assertTrue(_warns(res, "VOLFRAC=0.6"), res.warnings)
        self.assertTrue(any("Q4=502" in w for w in res.warnings),
                        res.warnings)

    def test_coexists_with_add_erosion_and_gissmo_riders(self):
        """DIEM + ADD_EROSION on one MID: two independent /FAIL entities
        (INIEVO + GENE1) bound by the same trailing mat id — legal in
        Radioss, and exactly dyna2rad's design (each rider converts on its
        own)."""
        ero = ("*MAT_ADD_EROSION\n"
               + _row(5, "", "", "", 1.2) + "\n"
               + _row("", "", 800.0) + "\n")
        _, starter = self._one(_diem(), extra=ero)
        self.assertTrue(_blocks(starter, "/FAIL/INIEVO/5"))
        self.assertTrue(_blocks(starter, "/FAIL/GENE1/5"))

    def test_duplicate_diem_overwrites_with_warning(self):
        res, starter = self._one(_diem() + _diem(
            criteria=((1, 501, 0.3, "", "", ""), (1, 0, 0.9, "", "", ""))))
        self.assertEqual(len(_blocks(starter, "/FAIL/INIEVO/5")), 1)
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertEqual(_col_i(c[1], 1, 10), 2)      # the SECOND card won
        self.assertTrue(any("second card for MID 5" in w
                            for w in res.warnings), res.warnings)

    def test_ndiemc_truncated_cards_reduce_ninievo(self):
        res, starter = self._one(_diem(
            ndiemc=3,
            criteria=((0, 501, "", "", "", ""), (0, 0, 0.08, "", "", ""))))
        c = _fail_cards(_block(starter, "/FAIL/INIEVO/5"))
        self.assertEqual(_col_i(c[0], 1, 10), 1)
        self.assertTrue(any("NDIEMC=3" in w for w in res.warnings),
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *SECTION_SOLID cohesive ELFORMs -> /PROP/TYPE43
# ═════════════════════════════════════════════════════════════════════════════

class Type43Tests(unittest.TestCase):
    """/PROP/TYPE43 (prop_p43_connect.cfg FORMAT(radioss140), the newest
    block): title, then ONE card — Ismstr(1-10) blank(11-80)
    True_thickness(81-100). Node ordering: LS-DYNA cohesive bottom face
    1-2-3-4 / top face 5-6-7-8 is IDENTICAL to TYPE43's t-axis convention,
    so *ELEMENT_SOLID connectivity passes into /BRICK unpermuted."""

    def test_elform19_routes_to_type43(self):
        _, starter = _convert(_cohesive_deck(_mat138(), 1, elform=19))
        blk = _block(starter, "/PROP/TYPE43/7")
        c = _cards(blk)
        self.assertEqual(len(c), 1)
        self.assertEqual(_col_i(c[0], 1, 10), 1)              # Ismstr
        self.assertEqual(c[0][10:80].strip(), "")             # blank 11-80
        self.assertAlmostEqual(_col_f(c[0], 81, 100), 0.0)    # True_thickness
        self.assertEqual(_blocks(starter, "/PROP/SOLID/7"), [])

    def test_all_cohesive_elforms_route(self):
        for elform in (19, -19, 20, 21, -21, 22):
            with self.subTest(elform=elform):
                _, starter = _convert(
                    _cohesive_deck(_mat138(), 1, elform=elform))
                self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))

    def test_material_route_arup_on_elform1(self):
        """*MAT_ARUP_ADHESIVE runs on ORDINARY ELFORM 1/2/15 bricks in
        LS-DYNA — dyna2rad routes the section to /PROP/CONNECT off the
        MATERIAL keyword, and a /MAT/LAW169 on a plain /PROP/SOLID would be
        ERROR 3047. The section must become TYPE43 with the routing warn."""
        res, starter = _convert(_cohesive_deck(_mat169(), 3, elform=1))
        self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))
        self.assertEqual(_blocks(starter, "/PROP/SOLID/7"), [])
        self.assertTrue(any("ELFORM=1 is not a cohesive formulation" in w
                            for w in res.warnings), res.warnings)

    def test_mat252_stays_on_the_plain_solid_prop(self):
        """MAT_252 is NOT in dyna2rad's CONNECT material list — LAW120 is
        SOLID_ALL and its normal home is an ordinary solid. ELFORM 1 with
        MAT_252 must stay /PROP/SOLID."""
        _, starter = _convert(_cohesive_deck(_mat252(), 4, elform=1))
        self.assertTrue(_blocks(starter, "/PROP/SOLID/7"))
        self.assertEqual(_blocks(starter, "/PROP/TYPE43/7"), [])

    def test_mat252_on_cohesive_elform_takes_type43(self):
        """...but an explicit ELFORM 19 with MAT_252 is legal on TYPE43
        (SOLID_ALL is in the accepted classes) and warns the LAW120 Thick
        default."""
        res, starter = _convert(_cohesive_deck(_mat252(), 4, elform=19))
        self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))
        self.assertTrue(any("LAW120" in w and "1.0 LENGTH UNIT" in w
                            for w in res.warnings), res.warnings)

    def test_incompatible_pairing_names_error_3047(self):
        """LAW36 on a cohesive section: the starter refuses with ERROR 3047 —
        measured verbatim on the negative-control run: 'PROPERTY ID 100 OF
        TYPE 43 IS NOT COMPATIBLE WITH MATERIAL ID 5 OF TYPE 36' (exit 2).
        The warning must name that id."""
        res, starter = _convert(_cohesive_deck(MAT024, 5, elform=19,
                                               extra=LC_TRIAX))
        self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))
        self.assertTrue(any("/MAT/LAW36" in w and "ERROR 3047" in w
                            for w in res.warnings), res.warnings)

    def test_penta_cohesive_pattern_passes_through_verbatim(self):
        """ELFORM 21 pentahedron cohesive: *ELEMENT_SOLID N1 N2 N3 N3 N5 N6
        N7 N7 (6 distinct nodes). Radioss TYPE43 is 8-node-hex-only, so the
        degenerate pattern must reach /BRICK VERBATIM — collapsing it to
        another element type would lose the cohesive mid-plane pairing
        (1-5, 2-6, 3-7, 4-8). Known, accepted delta (no warning): LS-DYNA
        integrates ELFORM 21/-21/22 pentas with ONE in-plane point, TYPE43
        runs the degenerate hex with its fixed 4 mid-plane Gauss points —
        an integration-order change (two of the four points coincide at the
        collapsed edge), not a formulation change; the starter accepted the
        pattern with 0 errors/0 warnings on the live probe."""
        deck = (_hex_nodes()
                + "*ELEMENT_SOLID\n" + _row(1, 7) + "\n"
                + _row(1, 2, 3, 3, 5, 6, 7, 7) + "\n"
                + _part(1) + _sec_solid(21) + _mat138() + END)
        _, starter = _convert(deck)
        self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))
        brick = _block(starter, "/BRICK/7")
        row = brick[1]
        self.assertEqual([_col_i(row, 10 * k + 11, 10 * k + 20)
                          for k in range(8)],
                         [1, 2, 3, 3, 5, 6, 7, 7])

    def test_zero_thickness_cohesive_survives_the_screens(self):
        """A zero-height ELFORM 19 pad (8 DISTINCT node ids on coincident
        top/bottom coordinates) has exactly zero volume — on a /PROP/SOLID
        that is starter ERROR 245; TYPE43 computes area-based response and
        legally takes zero height (the validation run started it with 0
        errors and gave it the full area-mass 1.1e-7). NOTE the scope of the
        degenerate-screen half: k2rad's degenerate-solid screen keys on
        DISTINCT NODE IDS, and this pad has 8 of them, so that screen could
        not fire on this deck under either routing — the load-bearing
        assertion here is the TYPE43 routing itself (a /PROP/SOLID routing
        would be the ERROR 245 above)."""
        deck = (_hex_nodes(top_z=0.0) + SOLID + _part(1) + _sec_solid(19)
                + _mat138() + END)
        res, starter = _convert(deck)
        self.assertTrue(_blocks(starter, "/BRICK/7"))
        self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))
        self.assertFalse(_warns(res, "degenerate solid"), res.warnings)

    def test_elform20_shell_offset_moments_warned(self):
        res, _ = _convert(_cohesive_deck(_mat138(), 1, elform=20))
        self.assertTrue(any("ELFORM=20" in w and "moments" in w
                            for w in res.warnings), res.warnings)

    def test_cohoff_and_gaskett_warned(self):
        deck = (_hex_nodes() + SOLID + _part(1)
                + "*SECTION_SOLID\n"
                + _row(7, 19, "", "", "", "", 0.5, 1.0) + "\n"
                + _mat138() + END)
        res, _ = _convert(deck)
        self.assertTrue(any("COHOFF=0.5" in w for w in res.warnings),
                        res.warnings)
        self.assertTrue(any("GASKETT=1" in w for w in res.warnings),
                        res.warnings)

    def test_misc_cohthk_becomes_true_thickness(self):
        """*SECTION_SOLID_MISC card 2c COHTHK supersedes *MAT_240 THICK in
        LS-DYNA; /PROP/TYPE43 True_thickness (cols 81-100) is its exact
        analogue (overrides the geometric height)."""
        deck = (_hex_nodes() + SOLID + _part(2)
                + "*SECTION_SOLID_MISC\n" + _row(7, 19) + "\n"
                + _row(0.25) + "\n"
                + _mat240() + END)
        res, starter = _convert(deck)
        c = _cards(_block(starter, "/PROP/TYPE43/7"))
        self.assertAlmostEqual(_col_f(c[0], 81, 100), 0.25)
        self.assertEqual(res.skipped_keywords, [])

    def test_misc_card2c_is_optional_in_a_multiset_block(self):
        """Card 2c 'is optional' (Vol I R16 p.41-83). A two-set _MISC block
        that omits it must NOT eat the next set's card 1 as the MISC card —
        unconditional consumption read /PROP/TYPE43/7 True_thickness = 8.0
        (the NEXT SECID!) and dropped section 8 entirely. The card is
        positionally detectable: it holds ONLY COHTHK, fields 2..8 blank."""
        deck = (_hex_nodes() + SOLID
                + "*ELEMENT_SOLID\n" + _row(2, 8) + "\n"
                + _row(*range(1, 9)) + "\n"
                + _part(2, secid=7, pid=7) + _part(2, secid=8, pid=8)
                + "*SECTION_SOLID_MISC\n"
                + _row(7, 19) + "\n"                  # set 1: no card 2c
                + _row(8, 19) + "\n"                  # set 2: card 1
                + _row(0.25) + "\n"                   # set 2: card 2c
                + _mat240() + END)
        _, starter = _convert(deck)
        c7 = _cards(_block(starter, "/PROP/TYPE43/7"))
        self.assertAlmostEqual(_col_f(c7[0], 81, 100), 0.0)   # NOT 8.0
        c8 = _cards(_block(starter, "/PROP/TYPE43/8"))        # set survived
        self.assertAlmostEqual(_col_f(c8[0], 81, 100), 0.25)

    def test_cohesive_material_on_a_shell_part_warns_error_3046(self):
        """LS-DYNA runs MAT_138/240 on cohesive SHELLS (*SECTION_SHELL
        ELFORM 29); Radioss has NO cohesive-shell element, so the emitted
        /MAT/LAW117 + /PROP/SHELL pairing is starter ERROR 3046 + 658
        (live-confirmed). Without a warning the only k2rad message is the
        generic ELFORM->Ishell remap note, which mislabels the formulation
        as an integration choice."""
        res, _ = _convert(_shell_deck(_mat138(), 1))
        self.assertTrue(any("SHELL part(s) [7]" in w and "ERROR 3046" in w
                            and "LAW117" in w for w in res.warnings),
                        res.warnings)
        # ...and a cohesive SOLID deck must NOT draw the shell warning.
        res, _ = _convert(_cohesive_deck(_mat138(), 1))
        self.assertFalse(any("ERROR 3046" in w and "SHELL part" in w
                             for w in res.warnings), res.warnings)

    def test_pairing_warnings_aggregate_over_parts(self):
        """state.warn does not deduplicate; a 12-part deck sharing one
        cohesive section used to emit 12 near-identical lines. One warning
        per (section, defect class), naming all part ids."""
        deck = (_hex_nodes() + SOLID
                + "*ELEMENT_SOLID\n" + _row(2, 8) + "\n"
                + _row(*range(1, 9)) + "\n"
                + _part(5, secid=7, pid=7) + _part(5, secid=7, pid=8)
                + _sec_solid(19) + MAT024 + LC_TRIAX + END)
        res, _ = _convert(deck)
        hits = [w for w in res.warnings
                if "/MAT/LAW36" in w and "ERROR 3047" in w]
        self.assertEqual(len(hits), 1, res.warnings)
        self.assertIn("[7, 8]", hits[0])

    def test_arup_zero_height_mass_trap_warned_on_cohesive_elform(self):
        """LAW169 is missing from the sini43.F area-mass list — volume
        density ALWAYS — so a zero-height ARUP cohesive has zero mass. Warned
        when (and only when) MAT_169 lands on a cohesive ELFORM."""
        res, _ = _convert(_cohesive_deck(_mat169(), 3, elform=19))
        self.assertTrue(any("VOLUME density" in w and "zero" in w
                            for w in res.warnings), res.warnings)
        res, _ = _convert(_cohesive_deck(_mat169(), 3, elform=1))
        self.assertFalse(any("VOLUME density" in w and "LAW169" in w
                             for w in res.warnings), res.warnings)

    def test_hourglass_control_never_splits_a_cohesive_part(self):
        """*CONTROL_HOURGLASS remaps plain solid props (IHQ->Isolid) by
        splitting parts onto /PROP/SOLID clones — a cohesive part must stay
        on its /PROP/TYPE43 (the clone would drop the formulation AND refuse
        with ERROR 3047)."""
        deck = (_hex_nodes() + SOLID + _part(1) + _sec_solid(19)
                + _mat138()
                + "*CONTROL_HOURGLASS\n" + _row(4, 0.05) + "\n" + END)
        _, starter = _convert(deck)
        self.assertTrue(_blocks(starter, "/PROP/TYPE43/7"))
        self.assertEqual(_blocks(starter, "/PROP/SOLID/"), [])
        # /PART data card: prop_ID(1-10) mat_ID(11-20) — must still point at
        # the SECID-verbatim /PROP/TYPE43, not a synthesized clone id.
        part_line = _cards(_block(starter, "/PART/7"))[0]
        self.assertEqual(_col_i(part_line, 1, 10), 7)


# ═════════════════════════════════════════════════════════════════════════════
# _target_mat_law / beam-compat / XREF gate coverage
# ═════════════════════════════════════════════════════════════════════════════

class TargetMatLawTests(unittest.TestCase):
    """_target_mat_law is the ONE mid -> emitted-law map (writer/mesh.py); a
    family missing from it makes the beam-compat check silently `continue`,
    makes writer/inistate.py's solid-/XREF gate misreport the part as having
    no /MAT at all, and now also blinds the /PROP/TYPE43 pairing check."""

    CASES = (
        (1, _mat138(), 19, 117),
        (3, _mat169(), 1, 169),
        (2, _mat240(), 19, 116),
        (4, _mat252(), 1, 120),
    )

    def test_every_new_family_is_mapped(self):
        from k2rad.writer.assembly import build_starter
        for mid, mat, elform, law in self.CASES:
            with self.subTest(mid=mid, law=law):
                state = _dispatch(_cohesive_deck(mat, mid, elform))
                build_starter(state)
                self.assertEqual(_target_mat_law(state, mid), law)

    def test_all_mat_ids_covers_the_new_containers(self):
        """next_mat_id() guards synthesized ids against all_mat_ids(); a
        family left out of that union is a starter ERROR 79 DUPLICATE ID
        waiting to happen."""
        deck = (_hex_nodes() + SOLID + _part(1) + _sec_solid(19)
                + _mat138() + _mat169() + _mat240() + _mat252() + END)
        state = _dispatch(deck)
        ids = state.all_mat_ids()
        for mid in (1, 2, 3, 4):
            self.assertIn(mid, ids)

    def test_xref_whitelist_consequence(self):
        """NONE of 116/117/120/169 is in inistate._XREF_SOLID_LAWS, so a
        cohesive part hit by an *INITIAL_FOAM_REFERENCE_GEOMETRY node table
        is warn-skipped NAMING the law (ERROR 2014) — not misreported as
        having no /MAT at all (the failure mode _target_mat_law coverage
        exists to prevent)."""
        from k2rad.writer.inistate import _XREF_SOLID_LAWS
        self.assertEqual({116, 117, 120, 169} & _XREF_SOLID_LAWS, set())
        xref = ("*INITIAL_FOAM_REFERENCE_GEOMETRY\n"
                + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n"
                          for n, x, y, z in (
                              (1, 0.0, 0.0, 0.0), (2, 9.9, 0.0, 0.0),
                              (3, 9.9, 9.9, 0.0), (4, 0.0, 9.9, 0.0),
                              (5, 0.0, 0.0, 1.9), (6, 9.9, 0.0, 1.9),
                              (7, 9.9, 9.9, 1.9), (8, 0.0, 9.9, 1.9))))
        res, starter = _convert(_cohesive_deck(_mat138(), 1, 19, xref))
        self.assertEqual(_blocks(starter, "/XREF/"), [])
        self.assertTrue([w for w in res.warnings
                         if "/MAT/LAW117" in w and "ERROR 2014" in w],
                        res.warnings)

    def test_beam_compat_classification(self):
        """None of LAW116/117/120/169 declares any BEAM_* keyword in the
        starter (hm_read_mat116.F:236/239, mat117:208/211, mat120:257-262,
        mat169.F90:191 — HOOK and the SOLID classes only), so neither beam
        frozenset changes and a beam part on any of them draws the
        'no beam keyword at all' warning naming ERROR 3046 (the
        material-vs-element refusal, not the 3047 property one)."""
        from k2rad.writer.mesh import (_TYPE3_BEAM_LAWS,
                                       _TYPE18_ONLY_BEAM_LAWS)
        for law in (116, 117, 120, 169):
            self.assertNotIn(law, _TYPE3_BEAM_LAWS)
            self.assertNotIn(law, _TYPE18_ONLY_BEAM_LAWS)
        deck = (
            "*NODE\n"
            + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 0.0, 10.0, 0.0)))
            + "*ELEMENT_BEAM\n" + _row(1, 7, 1, 2, 3) + "\n"
            + "*PART\nbeam\n" + _row(7, 7, 1) + "\n"
            + "*SECTION_BEAM\n" + _row(7, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + _mat138() + END)
        res, _ = _convert(deck)
        self.assertTrue(any("/MAT/LAW117" in w and "ERROR 3046" in w
                            for w in res.warnings), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Multi-material deck + byte-identity
# ═════════════════════════════════════════════════════════════════════════════

class BatchIntegrationTests(unittest.TestCase):

    def test_all_five_keywords_in_one_deck(self):
        """One part per keyword — the shape of the deck validated on the live
        starter run (0 ERROR(S), exit 0; the sole batch warning was the
        documented WARNING 100211 for /MAT/LAW169 under /BEGIN 2022)."""
        nodes, deck_nodes = [], ""
        nid = 1
        for k in range(5):
            x0 = 20.0 * k
            top_z = 2.0 if k < 4 else 0.0
            for (x, y) in ((x0, 0.0), (x0 + 10, 0.0), (x0 + 10, 10.0),
                           (x0, 10.0)):
                nodes.append((nid, x, y, 0.0)); nid += 1
            for (x, y) in ((x0, 0.0), (x0 + 10, 0.0), (x0 + 10, 10.0),
                           (x0, 10.0)):
                nodes.append((nid, x, y, top_z)); nid += 1
        deck_nodes = "*NODE\n" + "".join(
            f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in nodes)
        deck = deck_nodes + "*ELEMENT_SOLID\n"
        for k in range(5):
            deck += _row(k + 1, 100 + k, *(range(1 + 8 * k, 9 + 8 * k))) + "\n"
        deck += ("*NODE\n"
                 + f"{90001:>8}{0.0:>16}{50.0:>16}{0.0:>16}\n"
                 + f"{90002:>8}{10.0:>16}{50.0:>16}{0.0:>16}\n"
                 + f"{90003:>8}{10.0:>16}{60.0:>16}{0.0:>16}\n"
                 + f"{90004:>8}{0.0:>16}{60.0:>16}{0.0:>16}\n"
                 + "*ELEMENT_SHELL\n"
                 + _row(900, 200, 90001, 90002, 90003, 90004) + "\n")
        for pid, secid, mid in ((100, 100, 1), (101, 101, 2), (102, 102, 3),
                                (103, 103, 4), (104, 100, 1)):
            deck += f"*PART\npart {pid}\n" + _row(pid, secid, mid) + "\n"
        deck += "*PART\nshell part\n" + _row(200, 200, 5) + "\n"
        deck += (_sec_solid(19, 100) + _sec_solid(19, 101)
                 + _sec_solid(1, 102) + _sec_solid(1, 103)
                 + "*SECTION_SHELL\n" + _row(200, 2, 1.0, 5) + "\n"
                 + _row(1.2, 1.2, 1.2, 1.2) + "\n")
        deck += (_mat138() + _mat240() + _mat169() + _mat252(lcss=801)
                 + MAT024
                 + _diem(numfip=-30,
                         criteria=((0, 501, "", "", "", 502),
                                   (0, 0, 0.08, "", 1.5, "")))
                 + "*MAT_ADD_EROSION\n"
                 + _row(5, "", "", "", 1.2) + "\n"
                 + _row("", "", 800.0) + "\n"
                 + LC_TRIAX + LC_SIZE + LC_YLD + END)
        res, starter = _convert(deck)
        for header in ("/MAT/LAW117/1", "/MAT/LAW116/2", "/MAT/LAW169/3",
                       "/MAT/LAW120/4", "/MAT/LAW36/5",
                       "/FAIL/INIEVO/5", "/FAIL/GENE1/5",
                       "/PROP/TYPE43/100", "/PROP/TYPE43/101",
                       "/PROP/TYPE43/102", "/PROP/SOLID/103",
                       "/TABLE/1/501", "/TABLE/1/502", "/TABLE/1/801"):
            with self.subTest(header=header):
                self.assertTrue(_blocks(starter, header),
                                f"{header} missing from the converted deck")
        self.assertEqual(res.skipped_keywords, [])
        # /FAIL binds by the trailing id: every /FAIL id must have a /MAT.
        mat_ids = {ln.rsplit("/", 1)[1] for ln in starter.splitlines()
                   if ln.startswith("/MAT/")}
        for ln in starter.splitlines():
            if ln.startswith(("/FAIL/INIEVO/", "/FAIL/GENE1/")):
                self.assertIn(ln.rsplit("/", 1)[1], mat_ids)
        # Every /MAT id distinct — no family shadows another's dict entry.
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/MAT/LAW")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_goldens_are_unchanged(self):
        """A pure-addition batch adds no card to a deck that does not use the
        new keywords, so the five checked-in goldens must be byte-identical —
        if one moves, the change leaked into a shared emitter. The named
        risks here are the _make_properties solid loop (the cohesive branch
        sits ABOVE _elform_to_isolid), _solid_hg_values (a new gate line),
        _assign_hourglass_props (the cohesive-section skip) and
        _make_functions (the table_1d_ids rerouting the batch adds ids to)."""
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
# *INCLUDE_TRANSFORM id offsets (the three hand-written callables)
# ═════════════════════════════════════════════════════════════════════════════

class IncludeTransformOffsetTests(unittest.TestCase):
    """_off_mat_138, _off_mat_169 and _off_mat_add_damage_diem key off
    CONTENT: MAT_138/169 offset cells only when NEGATIVE (curve ids hiding in
    strength/toughness fields — a static spec would rewrite real physics),
    MAT_169's SDFAC card index moves with EXTRA and exists only under
    EDOT2!=0, and the DIEM criterion cells repeat NDIEMC times. Registry
    membership alone cannot catch any of that."""

    def _convert_with_transform(self, mat: str, extra: str,
                                idmoff: int, idfoff: int):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        child = os.path.join(tmp.name, "child.k")
        with open(child, "w") as fh:
            fh.write("*KEYWORD\n" + mat + extra + "*END\n")
        master = os.path.join(tmp.name, "master.k")
        with open(master, "w") as fh:
            # IDNOFF IDEOFF IDPOFF IDMOFF IDSOFF IDFOFF
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     + _row(0, 0, 0, idmoff, 0, idfoff) + "\n*END\n")
        state = ConversionState()
        for block in parse_k_file(master):
            dispatch(block, state)
        return state

    def test_mat138_offsets_only_the_negative_curve_cells(self):
        mat = _mat138(gic=-9, giic=0.5, t=-77, s=12.0)
        state = self._convert_with_transform(mat, "", 4000, 6000)
        m = state.mat_cohesive_mixed_mode[4001]
        self.assertEqual(m.gic, -6009.0)      # curve id moved, sign kept
        self.assertEqual(m.giic, 0.5)         # real toughness untouched
        self.assertEqual(m.t, -6077.0)
        self.assertEqual(m.s, 12.0)

    def test_mat169_offsets_negative_strengths_and_the_moving_sdfac_card(self):
        """EXTRA=1 inserts the two edge cards BETWEEN card 2 and the SDFAC
        card — offsetting the wrong row would rewrite an edge factor as a
        curve id. The negative SDFAC on the correctly-located card 5 must
        move; the positive SGFAC next to it must not."""
        mat = _mat169(tenmax=-333, gcten=4.0, shrp=-44, edot2=0.001,
                      extra=1, more=(
                          (50.0, 5.0, 25.0, 2.5, 2.0, 2.0),
                          (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
                          (-55, 1.2, 1.0, 1.0),
                      ))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        child = os.path.join(tmp.name, "child.k")
        with open(child, "w") as fh:
            fh.write("*KEYWORD\n" + mat + "*END\n")
        master = os.path.join(tmp.name, "master.k")
        with open(master, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     + _row(0, 0, 0, 4000, 0, 6000) + "\n*END\n")
        blocks = [b for b in parse_k_file(master)
                  if b.keyword == "MAT_ARUP_ADHESIVE"]
        self.assertEqual(len(blocks), 1)
        raw = blocks[0].raw
        self.assertEqual(raw[0].split()[0], "4003")           # MID
        self.assertIn("-6333", raw[0])                        # TENMAX curve
        self.assertIn("-6044", raw[1])                        # SHRP curve
        self.assertIn("50", raw[2])                           # edge card as-is
        self.assertIn("-6055", raw[4])                        # SDFAC moved
        self.assertIn("1.2", raw[4])                          # SGFAC untouched

    def test_diem_offsets_repeat_per_criterion(self):
        diem = _diem(ndiemc=2, criteria=(
            (0, 501, "", "", "", 502), (0, 0, -503, "", "", 504),
            (1, 511, 0.3, "", "", ""), (1, 1, 0.9, "", "", "")))
        state = self._convert_with_transform(MAT024 + diem, "", 4000, 6000)
        d = state.fail_diem[4005]
        self.assertEqual(d.criteria[0].p1, 6501)
        self.assertEqual(d.criteria[0].p5, 6502)
        self.assertEqual(d.criteria[0].q1, -6503.0)   # table id, sign kept
        self.assertEqual(d.criteria[0].q4, 6504.0)
        self.assertEqual(d.criteria[1].p1, 6511)
        self.assertEqual(d.criteria[1].q1, 0.9)       # scalar untouched

    def test_mat240_thermal_cells_offset_per_spelling(self):
        """The base spelling must offset ONLY LCG1C/LCG2C (cards 2/3 field
        8); the _THERMAL spelling turns EMOD/GMOD/G*C_0/T0/S0/FG* into curve
        ids too. Same cells under the base spelling are float physics and
        must not move."""
        base = _mat240(c2=(-0.6, 1.4, 0.5, -25.0, 40.0, 0.8, -0.7, 901),
                       c3=(0.9, 1.1, 0.4, 20.0, "", "", 0.55, 902))
        state = self._convert_with_transform(base, "", 4000, 6000)
        m = state.mat_cohesive_mm_epr[4002]
        self.assertEqual(m.lcg1c, 6901)
        self.assertEqual(m.lcg2c, 6902)
        self.assertEqual(m.emod, 3000.0)              # modulus untouched
        self.assertEqual(m.g1c_0, -0.6)               # toughness untouched
        thermal = ("*MAT_COHESIVE_MIXED_MODE_ELASTOPLASTIC_RATE_THERMAL\n"
                   + _row(2, "1.2E-9", 0, 2, 701, 702, 0.2, "") + "\n"
                   + _row(703, "", "", 704, "", "", 705, 711) + "\n"
                   + _row(706, "", "", 707, "", "", 708, 712) + "\n")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        child = os.path.join(tmp.name, "child.k")
        with open(child, "w") as fh:
            fh.write("*KEYWORD\n" + thermal + "*END\n")
        master = os.path.join(tmp.name, "master.k")
        with open(master, "w") as fh:
            fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nchild.k\n"
                     + _row(0, 0, 0, 4000, 0, 6000) + "\n*END\n")
        blocks = [b for b in parse_k_file(master)
                  if "THERMAL" in b.keyword]
        self.assertEqual(len(blocks), 1)
        raw = blocks[0].raw
        self.assertIn("6701", raw[0])                 # EMOD curve id moved
        self.assertIn("6703", raw[1])                 # G1C_0 curve id moved
        self.assertIn("6711", raw[1])                 # LCG1C moved
        self.assertIn("6708", raw[2])                 # FG2 curve id moved


if __name__ == "__main__":
    unittest.main()
