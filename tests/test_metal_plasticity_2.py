"""Tests for the METAL PLASTICITY BATCH 2 conversions:

  *MAT_PLASTICITY_WITH_DAMAGE (081/082, +options) -> /MAT/LAW36 + /FAIL/TAB1
  *MAT_DAMAGE_2 (105)                             -> /MAT/LAW36 + /FAIL/LEMAITRE
                                                     [+ /FAIL/JOHNSON on FAIL]
  *MAT_STRAIN_RATE_DEPENDENT_PLASTICITY (019)     -> /MAT/LAW121 (PLAS_RATE)
  *MAT_PLASTICITY_COMPRESSION_TENSION (124)       -> /MAT/LAW66 [+ /VISC/PRONY]
                                                     [+ /FAIL/JOHNSON or
                                                        /FAIL/TENSSTRAIN]
  *MAT_GURSON (120, +_JC/_RCDC/_BFRAC)            -> /MAT/LAW52
                                                     [+ /FAIL/JOHNSON for _JC]
  *MAT_ISOTROPIC_ELASTIC_PLASTIC (012)            -> /MAT/LAW2 (PLAS_JOHNS)
  *MAT_HILL_3R (122)                              -> /MAT/LAW43 or /MAT/LAW32

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_composites.py, tests/test_johnson_cook.py and
tests/test_hyperelastic_rubber.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant (the G/K -> E/nu derivation, the plastic-modulus rescales, the Gurson
power-law samples, the Tvergaard q3 closure) is recomputed by hand in the test
rather than copied from the implementation.

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic - MAT_012's ETAN being the PLASTIC hardening modulus, MAT_122's P1
being the TANGENT modulus while P2 is the yield stress, MAT_124's PC/PT being
the mean-stress interpolation band and NOT the pressure cut-offs - the
assertion pins the value the MANUAL's definition implies, with the citation in
the test docstring. Re-deriving the implementation's own formula from the deck
inputs verifies the arithmetic but not that the formula belongs there.

Every emitted card in this batch was additionally validated on a live
OpenRadioss starter run (starter_win64, /BEGIN 2022): 0 ERROR(S) with the one
documented cosmetic WARNING 100211 for /FAIL/LEMAITRE, and the starter's own
echo confirmed the field-by-field placement asserted below - notably LAW66's
"COMPRESSION MEAN STRESS"/"TRACTION MEAN STRESS" labels for P_c/P_t.
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
    """A block's DATA lines: everything after the title that is not a comment."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _fail_cards(block):
    """A /FAIL or /VISC block's data lines — those carry NO title line."""
    return [ln for ln in block[1:] if not ln.startswith("#")]


def _f20(line: str, i: int) -> float:
    return float(line[i * 20:(i + 1) * 20] or 0)


def _i10(line: str, i: int) -> int:
    return int(line[i * 10:(i + 1) * 10] or 0)


def _col_f(line: str, a: int, b: int) -> float:
    """Float from 1-based inclusive columns [a, b]."""
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _funct(starter: str, fid: int):
    """The (x, y) point list of /FUNCT/<fid> or /TABLE/1/<fid>."""
    for hdr in (f"/FUNCT/{fid}", f"/TABLE/1/{fid}"):
        found = _blocks(starter, hdr)
        if found:
            rows = [ln for ln in found[0][2:] if not ln.startswith("#")]
            return [(_f20(r, 0), _f20(r, 1)) for r in rows if len(r) > 20]
    raise AssertionError(f"no /FUNCT or /TABLE for id {fid}")


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


def _part(mid: int) -> str:
    return "*PART\nshell part\n" + _row(7, 7, mid) + "\n"


def _deck(mat: str, mid: int, extra: str = "") -> str:
    return NODES + SHELL + _part(mid) + SECTION + mat + extra + END


def _curve(lcid: int, pts) -> str:
    return ("*DEFINE_CURVE\n" + _row(lcid) + "\n"
            + "".join(f"{x:>20}{y:>20}\n" for x, y in pts))


def _mat081(mid=81, kw="*MAT_PLASTICITY_WITH_DAMAGE", sigy=300.0, etan=1200.0,
            eppf=0.12, tdel=0.0, c=0.0, p=0.0, lcss=0, lcsr=0, eppfr=0.35,
            vp=0, lcdm=0, numint=0, eps=(0.0, 0.05, 0.1, 0.2),
            es=(300.0, 340.0, 370.0, 400.0)):
    """*MAT_PLASTICITY_WITH_DAMAGE, four cards (Vol II R17 p.2-602)."""
    return (kw + "\n"
            + _row(mid, 7.85e-9, 210000.0, 0.3, sigy, etan, eppf, tdel) + "\n"
            + _row(c, p, lcss, lcsr, eppfr, vp, lcdm, numint) + "\n"
            + _row(*eps) + "\n" + _row(*es) + "\n")


def _mat105(mid=105, sigy=280.0, etan=900.0, fail=0.5, tdel=0.0, lcss=0,
            lcsr=0, epsd=0.08, s=1.5, dc=0.45):
    """*MAT_DAMAGE_2, five cards (Vol II R17 p.2-752)."""
    return ("*MAT_105\n"
            + _row(mid, 7.8e-9, 200000.0, 0.29, sigy, etan, fail, tdel) + "\n"
            + _row(0.0, 0.0, lcss, lcsr) + "\n"
            + _row(epsd, s, dc) + "\n"
            + _row(0.0, 0.1, 0.3) + "\n"
            + _row(280.0, 330.0, 380.0) + "\n")


def _mat019(mid=19, vp=0, lc1=901, etan=1500.0, lc2=0, lc3=0, lc4=0,
            tdel=0.0, rdef=0):
    """*MAT_STRAIN_RATE_DEPENDENT_PLASTICITY, two cards (p.2-238)."""
    return ("*MAT_019\n"
            + _row(mid, 7.8e-9, 205000.0, 0.3, vp) + "\n"
            + _row(lc1, etan, lc2, lc3, lc4, tdel, rdef) + "\n")


def _mat124(mid=124, c=50.0, p=5.0, fail=0.6, tdel=0.0,
            lcidc=911, lcidt=912, lcsrc=0, lcsrt=0, srflag=0.0, lcfail=0,
            ec=2500.0, rpct=0.5, pc=30.0, pt=20.0, pcutc=0.0, pcutt=0.0,
            pcutf=0.0, srfilt=0.0, k=0.0, prony=()):
    """*MAT_PLASTICITY_COMPRESSION_TENSION (p.2-873). Card 4 (K) is required
    even when blank, so the Prony pairs always start at card 5."""
    out = ("*MAT_PLASTICITY_COMPRESSION_TENSION\n"
           + _row(mid, 1.1e-9, 3000.0, 0.35, c, p, fail, tdel) + "\n"
           + _row(lcidc, lcidt, lcsrc, lcsrt, srflag, lcfail, ec, rpct) + "\n"
           + _row(pc, pt, pcutc, pcutt, pcutf, "", "", srfilt) + "\n"
           + _row(k) + "\n")
    for g, b in prony:
        out += _row(g, b) + "\n"
    return out


def _mat120(mid=120, kw="*MAT_GURSON", sigy=350.0, n=0.0, q1=1.5, q2=1.0,
            fc=0.05, f0=0.002, en=0.3, sn=0.1, fn=0.04, etan=0.0, atyp=0,
            ff0=0.15, eps=(0.0, 0.05, 0.1, 0.2),
            es=(350.0, 400.0, 430.0, 450.0), card5=None,
            lcss=0, lcff=0, numint=0, lcf0=0, lcfc=0, lcfn=0, vgtyp=0.0,
            dexp=0.0, card6=True):
    """*MAT_GURSON, six cards (Vol II R17 p.2-826)."""
    if card5 is None:
        card5 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    out = (kw + "\n"
           + _row(mid, 7.85e-9, 210000.0, 0.3, sigy, n, q1, q2) + "\n"
           + _row(fc, f0, en, sn, fn, etan, atyp, ff0) + "\n"
           + _row(*eps) + "\n" + _row(*es) + "\n"
           + _row(*card5) + "\n")
    if card6:
        out += _row(lcss, lcff, numint, lcf0, lcfc, lcfn, vgtyp, dexp) + "\n"
    return out


def _mat012(mid=12, g=84000.0, sigy=250.0, etan=900.0, bulk=140000.0):
    """*MAT_ISOTROPIC_ELASTIC_PLASTIC, ONE card (Vol II R17 p.2-206).

    G = 84000 / K = 140000 is the exactly-representable pair for E = 210000,
    nu = 0.25 — both fit in the card's 10-column fields, unlike the G of an
    E = 210000 / nu = 0.3 steel (80769.230769..., which overflows and would
    corrupt the following cells)."""
    return "*MAT_012\n" + _row(mid, 7.85e-9, g, sigy, etan, bulk) + "\n"


def _mat122(mid=122, hr=1.0, p1=1500.0, p2=280.0, r00=1.2, r45=1.5, r90=1.8,
            lcid=0, e0=0.0, aopt=0.0, a=(0.0, 0.0, 0.0), v=(0.0, 0.0, 0.0),
            d=(0.0, 0.0, 0.0), beta=0.0):
    """*MAT_HILL_3R, five cards (Vol II R17 p.2-851)."""
    return ("*MAT_HILL_3R\n"
            + _row(mid, 7.85e-9, 210000.0, 0.3, hr, p1, p2) + "\n"
            + _row(r00, r45, r90, lcid, e0) + "\n"
            + _row(aopt) + "\n"
            + _row("", "", "", a[0], a[1], a[2]) + "\n"
            + _row(v[0], v[1], v[2], d[0], d[1], d[2], beta) + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / keyword registry
# ═════════════════════════════════════════════════════════════════════════════

class DispatchTests(unittest.TestCase):
    """Every documented keyword and numeric alias reaches its handler.

    The dispatcher is an EXACT dict match after only _ID/_TITLE/_SUBTITLE are
    stripped (k2rad/parser.py::_split_keyword), so an option spelling with no
    key of its own falls through to skipped_keywords and the part silently
    loses its material."""

    def test_every_spelling_is_registered(self):
        for kw in ("MAT_PLASTICITY_WITH_DAMAGE",
                   "MAT_PLASTICITY_WITH_DAMAGE_ORTHO",
                   "MAT_PLASTICITY_WITH_DAMAGE_ORTHO_RCDC",
                   "MAT_PLASTICITY_WITH_DAMAGE_ORTHO_RCDC1980",
                   "MAT_PLASTICITY_WITH_DAMAGE_STOCHASTIC",
                   "MAT_081", "MAT_81", "MAT_081_STOCHASTIC",
                   "MAT_082", "MAT_82", "MAT_082_RCDC", "MAT_082_RCDC1980",
                   "MAT_DAMAGE_2", "MAT_105",
                   "MAT_STRAIN_RATE_DEPENDENT_PLASTICITY", "MAT_019", "MAT_19",
                   "MAT_PLASTICITY_COMPRESSION_TENSION", "MAT_124",
                   "MAT_GURSON", "MAT_120", "MAT_GURSON_JC", "MAT_120_JC",
                   "MAT_GURSON_RCDC", "MAT_120_RCDC",
                   "MAT_GURSON_BFRAC", "MAT_120_BFRAC",
                   "MAT_ISOTROPIC_ELASTIC_PLASTIC", "MAT_012", "MAT_12",
                   "MAT_HILL_3R", "MAT_122"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_title_option_is_stripped_and_read(self):
        """_TITLE adds one 80a line before card 1 for every one of them."""
        for kw, mid, deck in (
                ("*MAT_PLASTICITY_WITH_DAMAGE_TITLE", 81,
                 _mat081(kw="*MAT_PLASTICITY_WITH_DAMAGE_TITLE\nsteel dmg")),
                ("*MAT_105_TITLE", 105,
                 "*MAT_105_TITLE\ndamaged steel\n"
                 + _mat105().split("\n", 1)[1]),
                ("*MAT_019_TITLE", 19,
                 "*MAT_019_TITLE\nrate steel\n" + _mat019().split("\n", 1)[1]),
                ("*MAT_124_TITLE", 124,
                 "*MAT_124_TITLE\nfoam\n" + _mat124().split("\n", 1)[1]),
                ("*MAT_120_TITLE", 120,
                 "*MAT_120_TITLE\nporous\n" + _mat120().split("\n", 1)[1]),
                ("*MAT_012_TITLE", 12,
                 "*MAT_012_TITLE\nGK steel\n" + _mat012().split("\n", 1)[1]),
                ("*MAT_122_TITLE", 122,
                 "*MAT_122_TITLE\nsheet\n" + _mat122().split("\n", 1)[1])):
            with self.subTest(kw=kw):
                _, starter = _convert(_deck(deck, mid, _curve(
                    911, ((0.0, 50.0), (0.5, 70.0))) + _curve(
                    912, ((0.0, 40.0), (0.5, 55.0))) + _curve(
                    901, ((0.0, 300.0), (1.0, 340.0)))))
                self.assertIn("/MAT/LAW", starter)
                titles = [ln for ln in starter.splitlines()
                          if ln in ("steel dmg", "damaged steel", "rate steel",
                                    "foam", "porous", "GK steel", "sheet")]
                self.assertTrue(titles, f"{kw} title line not emitted")


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_081 / *MAT_082 -> /MAT/LAW36 + /FAIL/TAB1
# ═════════════════════════════════════════════════════════════════════════════

class Mat081Tests(unittest.TestCase):
    """*MAT_PLASTICITY_WITH_DAMAGE rides the MAT_024 LAW36 machinery and adds a
    LIVE /FAIL/TAB1 built from EPPF/EPPFR."""

    def test_card_fields_are_read_at_their_own_columns(self):
        """MAT_081 card 1 field 7 is EPPF where MAT_024 has FAIL, and card 2
        field 6 is VP where MAT_024 has it at field 5 — the reason this cannot
        share the MAT_024 handler."""
        state = _dispatch(_deck(_mat081(eppf=0.12, eppfr=0.35, vp=1,
                                        lcdm=931, numint=3, tdel=1e-8), 81))
        mat = state.mat_plas_tab[81]
        self.assertEqual(mat.family, "081")
        self.assertAlmostEqual(mat.eppf, 0.12)
        self.assertAlmostEqual(mat.eppfr, 0.35)
        self.assertEqual(mat.vp, 1)
        self.assertEqual(mat.lcdm, 931)
        self.assertAlmostEqual(mat.numint, 3.0)
        self.assertAlmostEqual(mat.tdel, 1e-8)
        # EPPF must NOT land in `fail`: that would emit a second, duplicated
        # plastic-strain criterion as /FAIL/JOHNSON.
        self.assertEqual(mat.fail, 0.0)

    def test_law36_plus_tab1_only(self):
        _, starter = _convert(_deck(_mat081(), 81))
        self.assertTrue(_blocks(starter, "/MAT/LAW36/81"))
        self.assertTrue(_blocks(starter, "/FAIL/TAB1/81"))
        self.assertFalse(_blocks(starter, "/FAIL/JOHNSON/81"),
                         "EPPF must not also become a /FAIL/JOHNSON")

    def test_tab1_columns(self):
        """/FAIL/TAB1 layout (fail_tab1.cfg FORMAT(radioss2021)):
        C1 Ifail_sh(1-10) Ifail_so(11-20) [20 sp] P_thickfail(41-60)
           P_thinfail(61-80) [10 sp] Ixfem(91-100)
        C3 table1(1-10) Xscale1(11-30) Xscale2(31-50) table2(51-60)
           Xscale3(61-80) Xscale4(81-100)"""
        _, starter = _convert(_deck(_mat081(eppf=0.12, eppfr=0.35), 81))
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertEqual(_col_i(c[0], 1, 10), 2)     # Ifail_sh: ALL layers
        self.assertEqual(_col_i(c[0], 11, 20), 1)    # Ifail_so: delete solid
        self.assertEqual(_col_f(c[0], 41, 60), 0.0)  # no NUMINT here
        self.assertEqual(_col_i(c[0], 91, 100), 0)   # Ixfem
        # Card 2 blanks -> reader defaults Dcrit=1, D=0, n=1: exactly LS-DYNA's
        # linear omega = (eps_p - EPPF)/(EPPFR - EPPF).
        self.assertEqual([_f20(c[1], i) for i in range(4)], [0.0] * 4)
        self.assertEqual(_col_i(c[1], 81, 90), 0)    # fct_IDd
        t1 = _col_i(c[2], 1, 10)
        t2 = _col_i(c[2], 51, 60)
        self.assertNotEqual(t1, 0, "TABLE1_ID is mandatory (starter ERROR 2068)")
        self.assertNotEqual(t2, 0)
        # TABLE1 is the FAILURE-strain table -> EPPFR; TABLE2 the INSTABILITY
        # (softening-onset) table -> EPPF (Vol II R17 p.2-603/606).
        self.assertEqual(_funct(starter, t1), [(-1.0, 0.35), (1.0, 0.35)])
        self.assertEqual(_funct(starter, t2), [(-1.0, 0.12), (1.0, 0.12)])

    def test_blank_strain_becomes_the_no_failure_sentinel(self):
        """A blank cell reads as 0.0, but LS-DYNA's own defaults are EPPF=1e12
        and EPPFR=1e14 (p.2-602) — write a large finite value so the missing
        leg never engages."""
        _, starter = _convert(_deck(_mat081(eppf=0.12, eppfr=0.0), 81))
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertEqual(_funct(starter, _col_i(c[2], 1, 10)),
                         [(-1.0, 1e14), (1.0, 1e14)])

    def test_no_damage_at_all_emits_no_tab1(self):
        _, starter = _convert(_deck(_mat081(eppf=0.0, eppfr=0.0), 81))
        self.assertTrue(_blocks(starter, "/MAT/LAW36/81"))
        self.assertFalse(_blocks(starter, "/FAIL/TAB1/81"))

    def test_numint_becomes_a_positive_pthickfail(self):
        """NUMINT counts failed IPs, so the count is divided by the section NIP
        (5 in SECTION) — but the RATIO must be written POSITIVE.

        hm_read_fail_tab1.F:181-187 only honours P_thickfail on the
        ``> ZERO .and. IFAIL_SH > 1`` branch; a negative value falls through to
        ``IFAIL_SH == 2 -> PTHKF = 1 - 1e-6``, i.e. it is silently replaced by
        "the whole thickness must fail" and :216 pins UPARAM(3) to 0 with the
        comment "not used (P_THICK)". Only fail_setoff_c.F reads a negative
        FAIL%PTHK as a failed-IP ratio, and /FAIL/TAB1 never lets one reach
        it, so the positive broken-thickness fraction is the only channel that
        survives the reader."""
        res, starter = _convert(_deck(_mat081(numint=3), 81))
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertAlmostEqual(_col_f(c[0], 41, 60), 3.0 / 5.0)
        self.assertTrue(any("NUMINT=3" in w and "P_thickfail=0.6" in w
                            and "APPROXIMATION" in w
                            for w in res.warnings), res.warnings)

    def test_numint_ratio_is_clamped_to_one(self):
        """NUMINT above the section NIP would put P_thickfail past 1.0, which
        the reader clamps anyway (:178) — do it here so the card stays sane."""
        _, starter = _convert(_deck(_mat081(numint=9), 81))
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertAlmostEqual(_col_f(c[0], 41, 60), 1.0)

    def test_fad_exp_is_one_so_the_softening_half_is_live(self):
        """EPPF is inert unless the reader turns the damage flag on.

        hm_read_fail_tab1.F:153-157 zeroes ECRIT as soon as a TABLE2 is given,
        so :170-174 (``DMG_FLAG = 1`` iff ``FADE_EXPO > 0 .or. ECRIT /= 0``)
        leaves DMG_FLAG at 0 for a blank FAD_EXP — and fail_tab_c.F:441-455
        gates the necking block, the ONLY reader of EPSF_N (= EPPF), on
        ``DMG_FLAG == 1``. With FAD_EXP=1 and D=0 that block gives
        ``DMG_SCALE = 1 - (eps_p-EPPF)/(EPPFR-EPPF)``, LS-DYNA's own 1-omega.
        Card 4 is fct_IDEL(1-10) Fscale_EL(11-30) EI_REF(31-50)
        INST_START(51-70) FAD_EXP(71-90) CH_I_F(91-100)."""
        res, starter = _convert(_deck(_mat081(eppf=0.12, eppfr=0.35), 81))
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertEqual(_col_i(c[3], 1, 10), 0)        # fct_IDEL
        self.assertEqual(_col_f(c[3], 51, 70), 0.0)     # INST_START
        self.assertAlmostEqual(_col_f(c[3], 71, 90), 1.0)   # FAD_EXP
        self.assertEqual(_col_i(c[3], 91, 100), 0)      # CH_I_F
        self.assertTrue(any("FAD_EXP=1" in w and "SHELLS only" in w
                            for w in res.warnings), res.warnings)

    def test_numint_without_a_nip_is_dropped_loudly(self):
        deck = (NODES + SHELL + _part(81) + SECTION.replace(
            _row(7, 2, 1.0, 5), _row(7, 2, 1.0, 0))
            + _mat081(numint=3) + END)
        res, starter = _convert(deck)
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertEqual(_col_f(c[0], 41, 60), 0.0)
        self.assertTrue(any("NUMINT" in w and "DROPPED" in w
                            for w in res.warnings), res.warnings)

    def test_lcdm_is_dropped_with_the_reason(self):
        """LCDM is omega(eps_p); TAB1's fct_IDd is a multiplier of the CURRENT
        DAMAGE D — a different independent variable, so no direct transfer."""
        res, starter = _convert(_deck(_mat081(lcdm=931), 81,
                                      _curve(931, ((0.0, 0.0), (0.3, 1.0)))))
        c = _fail_cards(_block(starter, "/FAIL/TAB1/81"))
        self.assertEqual(_col_i(c[1], 81, 90), 0, "LCDM must not reach fct_IDd")
        self.assertTrue(any("LCDM=931" in w and "DROPPED" in w
                            for w in res.warnings), res.warnings)
        self.assertTrue(any("IGNORES EPPFR" in w for w in res.warnings),
                        res.warnings)

    def test_tdel_is_reported_as_dropped(self):
        res, _ = _convert(_deck(_mat081(tdel=1e-8), 81))
        self.assertTrue(any("TDEL=1e-08" in w and "DROPPED" in w
                            for w in res.warnings), res.warnings)

    def test_mat082_converts_and_names_the_dropped_orthotropy(self):
        """dyna2rad has no *MAT_082 entry at all and drops the keyword
        silently, leaving the /PART with mat_id 0."""
        res, starter = _convert(_deck(_mat081(mid=82, kw="*MAT_082"), 82))
        self.assertTrue(_blocks(starter, "/MAT/LAW36/82"))
        self.assertTrue(_blocks(starter, "/FAIL/TAB1/82"))
        self.assertTrue(any("_ORTHO" in w and "DIRECTIONAL" in w
                            for w in res.warnings), res.warnings)

    def test_rcdc_card_is_named_not_read(self):
        res, starter = _convert(_deck(
            _mat081(mid=82, kw="*MAT_082_RCDC")
            + _row(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8) + "\n", 82))
        self.assertTrue(_blocks(starter, "/MAT/LAW36/82"))
        self.assertTrue(any("Rc-Dc" in w for w in res.warnings), res.warnings)

    def test_stochastic_option_is_named(self):
        res, _ = _convert(_deck(_mat081(kw="*MAT_081_STOCHASTIC"), 81))
        self.assertTrue(any("STOCHASTIC" in w or "scatter" in w
                            for w in res.warnings), res.warnings)

    def test_lcsr_becomes_a_rate_function_family(self):
        """LCSR is a SCALE FACTOR vs strain rate on the one static yield curve
        (p.2-606 remark 1b). LAW36's rate family is (function, scale, rate)
        triples, so the same function is repeated once per LCSR point."""
        deck = _deck(_mat081(lcss=921, lcsr=922), 81,
                     _curve(921, ((0.0, 300.0), (0.2, 400.0)))
                     + _curve(922, ((0.0, 1.0), (10.0, 1.2), (100.0, 1.4))))
        res, starter = _convert(deck)
        c = _cards(_block(starter, "/MAT/LAW36/81"))
        # RHO / E-Nu-Epsmax / N_funct / fct_IDp / func_ID / Fscale / Eps_dot
        self.assertEqual(_col_i(c[2], 1, 10), 3)          # N_funct
        self.assertEqual([_i10(c[4], i) for i in range(3)], [921, 921, 921])
        self.assertEqual([_f20(c[5], i) for i in range(3)], [1.0, 1.2, 1.4])
        self.assertEqual([_f20(c[6], i) for i in range(3)], [0.0, 10.0, 100.0])
        self.assertTrue(any("LCSR=922" in w for w in res.warnings),
                        res.warnings)

    def test_lcsr_is_ignored_when_lcss_is_a_table(self):
        """"C, P, LCSR ... are ignored if a table ID is defined" (p.2-604)."""
        deck = _deck(_mat081(lcss=930, lcsr=922), 81,
                     "*DEFINE_TABLE\n" + _row(930) + "\n"
                     + _row(0.0, 921) + "\n" + _row(10.0, 923) + "\n"
                     + _curve(921, ((0.0, 300.0), (0.2, 400.0)))
                     + _curve(923, ((0.0, 320.0), (0.2, 430.0)))
                     + _curve(922, ((0.0, 1.0), (10.0, 1.2))))
        res, starter = _convert(deck)
        c = _cards(_block(starter, "/MAT/LAW36/81"))
        self.assertEqual([_i10(c[4], i) for i in range(2)], [921, 923])
        self.assertTrue(any("LCSR=922 is ignored" in w for w in res.warnings),
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_105 -> /MAT/LAW36 + /FAIL/LEMAITRE
# ═════════════════════════════════════════════════════════════════════════════

class Mat105Tests(unittest.TestCase):
    """*MAT_DAMAGE_2 card 3 (EPSD S DC) is an exact /FAIL/LEMAITRE triple."""

    def test_both_failure_models_are_emitted(self):
        _, starter = _convert(_deck(_mat105(fail=0.5, epsd=0.08), 105))
        self.assertTrue(_blocks(starter, "/MAT/LAW36/105"))
        self.assertTrue(_blocks(starter, "/FAIL/JOHNSON/105"))
        self.assertTrue(_blocks(starter, "/FAIL/LEMAITRE/105"))

    def test_lemaitre_columns(self):
        """fail_lemaitre.cfg FORMAT(radioss2026), ONE card:
        EPS_D(1-20) S_D(21-40) DC(41-60) [10 sp] FAILIP(71-80)
        P_THICKFAIL(81-100)."""
        _, starter = _convert(_deck(_mat105(epsd=0.08, s=1.5, dc=0.45), 105))
        c = _fail_cards(_block(starter, "/FAIL/LEMAITRE/105"))
        self.assertEqual(len(c), 1)
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 0.08)
        self.assertAlmostEqual(_col_f(c[0], 21, 40), 1.5)
        self.assertAlmostEqual(_col_f(c[0], 41, 60), 0.45)
        self.assertEqual(_col_i(c[0], 71, 80), 0)
        self.assertEqual(_col_f(c[0], 81, 100), 0.0)

    def test_blank_dc_takes_the_lsdyna_default_not_the_reader_one(self):
        """LS-DYNA's DC default is 0.5 (p.2-754); the /FAIL/LEMAITRE reader
        would clamp a 0 to 1.0, i.e. no softening before full rupture."""
        res, starter = _convert(_deck(_mat105(dc=0.0), 105))
        c = _fail_cards(_block(starter, "/FAIL/LEMAITRE/105"))
        self.assertAlmostEqual(_col_f(c[0], 41, 60), 0.5)
        self.assertTrue(any("DC is blank" in w for w in res.warnings),
                        res.warnings)

    def test_no_epsd_means_no_lemaitre(self):
        res, starter = _convert(_deck(_mat105(epsd=0.0, s=1.5, dc=0.4), 105))
        self.assertFalse(_blocks(starter, "/FAIL/LEMAITRE/105"))
        self.assertTrue(any("EPSD" in w and "DROPPED" in w
                            for w in res.warnings), res.warnings)

    def test_zero_s_is_reported_as_no_damage_growth(self):
        res, _ = _convert(_deck(_mat105(s=0.0), 105))
        self.assertTrue(any("S_D=0 as INFINITY" in w for w in res.warnings),
                        res.warnings)

    def test_johnson_uses_the_all_layers_rule(self):
        _, starter = _convert(_deck(_mat105(fail=0.5), 105))
        c = _fail_cards(_block(starter, "/FAIL/JOHNSON/105"))
        self.assertAlmostEqual(_f20(c[0], 0), 0.5)          # D1 = FAIL
        self.assertEqual([_f20(c[0], i) for i in range(1, 5)], [0.0] * 4)
        self.assertEqual(_col_i(c[1], 21, 30), 2)           # Ifail_sh
        self.assertEqual(_col_i(c[1], 31, 40), 1)           # Ifail_so

    def test_lemaitre_family_and_no_vp_column(self):
        state = _dispatch(_deck(_mat105(), 105))
        mat = state.mat_plas_tab[105]
        self.assertEqual(mat.family, "105")
        self.assertEqual(mat.vp, 0, "MAT_105 has no VP field to carry")


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_019 -> /MAT/LAW121
# ═════════════════════════════════════════════════════════════════════════════

LC_RATE = (_curve(901, ((0.0, 300.0), (1.0, 340.0), (100.0, 420.0)))
           + _curve(902, ((0.0, 205000.0), (1.0, 206000.0)))
           + _curve(903, ((0.0, 1500.0), (1.0, 1400.0)))
           + _curve(904, ((0.0, 600.0), (1.0, 640.0))))


class Mat019Tests(unittest.TestCase):
    """LAW121's kernel is literally MAT_019's law, so the map is 1:1:
    sigma_y = sigma_0(eps_dot) + E*Et/(E-Et)*eps_p (p.2-239/240 vs
    mat121c_newton.F:194) — Radioss does the Ep conversion itself, so ETAN
    goes into TANG verbatim."""

    def test_card_layout(self):
        """matl121_plasrate.cfg FORMAT(radioss2022):
        C2 E(1-20) Nu(21-40) Ires(41-50) Ivisc(51-60) Fcut(61-80) DTMIN(81-100)
        C3..C6 Fct(1-10) [blank 11-20] Xscale(21-40) Yscale/TANG(41-60)"""
        _, starter = _convert(_deck(
            _mat019(vp=1, lc1=901, etan=1500.0, lc4=904, tdel=1e-9, rdef=2),
            19, LC_RATE))
        c = _cards(_block(starter, "/MAT/LAW121/19"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 205000.0)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.3)
        self.assertEqual(_col_i(c[1], 41, 50), 0)         # Ires -> reader 2
        self.assertEqual(_col_i(c[1], 51, 60), 1)         # Ivisc <- VP
        self.assertEqual(_col_f(c[1], 61, 80), 0.0)       # Fcut default
        self.assertAlmostEqual(_col_f(c[1], 81, 100), 1e-9)   # DTMIN <- TDEL
        self.assertEqual(_col_i(c[2], 1, 10), 901)        # Fct_SIG0 <- LC1
        self.assertEqual(_col_i(c[3], 1, 10), 0)          # Fct_YOUN (no LC2)
        self.assertEqual(_col_i(c[4], 1, 10), 0)          # Fct_TANG (no LC3)
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 1500.0)  # TANG <- ETAN
        self.assertEqual(_col_i(c[5], 1, 10), 904)        # Fct_FAIL <- LC4
        self.assertEqual(_col_i(c[5], 11, 20), 2)         # Ifail <- RDEF

    def test_tang_is_a_scale_factor_when_lc3_is_given(self):
        """"if Fct_TANG != 0 -> ORDINATE SCALE FACTOR on that curve" — leaving
        the dyna2rad 0 there would zero the hardening."""
        _, starter = _convert(_deck(_mat019(lc3=903, etan=1500.0), 19, LC_RATE))
        c = _cards(_block(starter, "/MAT/LAW121/19"))
        self.assertEqual(_col_i(c[4], 1, 10), 903)
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 1.0)

    def test_scale_factors_are_zero_without_a_function(self):
        _, starter = _convert(_deck(_mat019(lc4=0), 19, LC_RATE))
        c = _cards(_block(starter, "/MAT/LAW121/19"))
        self.assertEqual(_col_f(c[5], 21, 40), 0.0)
        self.assertEqual(_col_f(c[5], 41, 60), 0.0)

    def test_rdef_maps_value_for_value(self):
        for rdef, ifail in ((0, 0), (1, 1), (2, 2), (3, 3)):
            with self.subTest(rdef=rdef):
                _, starter = _convert(_deck(_mat019(lc4=904, rdef=rdef), 19,
                                            LC_RATE))
                c = _cards(_block(starter, "/MAT/LAW121/19"))
                self.assertEqual(_col_i(c[5], 11, 20), ifail)

    def test_missing_lc1_is_reported_with_the_starter_error(self):
        res, _ = _convert(_deck(_mat019(lc1=0), 19, LC_RATE))
        self.assertTrue(any("ERROR 2060" in w for w in res.warnings),
                        res.warnings)

    def test_vp_with_lc2_names_warning_2061(self):
        res, _ = _convert(_deck(_mat019(vp=1, lc2=902), 19, LC_RATE))
        self.assertTrue(any("WARNING 2061" in w for w in res.warnings),
                        res.warnings)

    def test_no_fail_card_is_emitted(self):
        _, starter = _convert(_deck(_mat019(lc4=904, tdel=1e-9), 19, LC_RATE))
        self.assertFalse(_blocks(starter, "/FAIL/JOHNSON/19"))
        self.assertFalse(_blocks(starter, "/FAIL/TAB1/19"))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_124 -> /MAT/LAW66
# ═════════════════════════════════════════════════════════════════════════════

LC_CT = (_curve(911, ((0.0, 50.0), (0.5, 70.0)))
         + _curve(912, ((0.0, 40.0), (0.5, 55.0)))
         + _curve(913, ((0.0, 1.0), (100.0, 1.5)))
         + _curve(914, ((0.0, 1.0), (100.0, 1.4)))
         + _curve(915, ((0.0, 0.4), (100.0, 0.2))))


class Mat124Tests(unittest.TestCase):
    """*MAT_PLASTICITY_COMPRESSION_TENSION -> /MAT/LAW66."""

    def test_card_layout_cowper_branch(self):
        """mat_law66.cfg FORMAT(radioss2022):
        C2 E(1-20) Nu(21-40) C_hard(41-60) F_cut(61-80) F_smooth(81-90)
           Iyld_rate(91-100)
        C3 P_c(1-20) P_t(21-40) EC(41-60) RPCT(61-80)
        C4 funct_IDc(1-10) funct_IDt(11-20) Fscalec(21-40) Fscalet(41-60)
        C5 Epsilon_0(1-20) c(21-40) Sigma_Y0(41-60) VP(61-70)"""
        _, starter = _convert(_deck(_mat124(srflag=2.0), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 3000.0)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.35)
        self.assertEqual(_col_f(c[1], 41, 60), 0.0)        # C_hard
        self.assertEqual(_col_i(c[1], 81, 90), 1)          # F_smooth
        self.assertEqual(_col_i(c[1], 91, 100), 1)         # Iyld_rate
        self.assertAlmostEqual(_col_f(c[2], 41, 60), 2500.0)   # EC
        self.assertAlmostEqual(_col_f(c[2], 61, 80), 0.5)      # RPCT
        self.assertEqual(_col_i(c[3], 1, 10), 911)
        self.assertEqual(_col_i(c[3], 11, 20), 912)
        self.assertAlmostEqual(_col_f(c[3], 21, 40), 1.0)
        self.assertAlmostEqual(_col_f(c[3], 41, 60), 1.0)
        self.assertEqual(_col_i(c[4], 61, 70), 1)          # VP <- SRFLAG=2

    def test_pc_pt_are_the_mean_stress_band(self):
        """LS-DYNA PC/PT are "compressive/tensile mean stress at which the
        yield stress follows LCIDC/LCIDT" (p.2-876) — LAW66's P_c/P_t, which
        the starter echoes as COMPRESSION/TRACTION MEAN STRESS. RPCT is stated
        as a fraction of that same pair on BOTH sides, which pins the
        correspondence. dyna2rad puts PCUTC/PCUTT there instead."""
        _, starter = _convert(_deck(_mat124(pc=30.0, pt=20.0, pcutc=7.0,
                                            pcutt=-8.0, pcutf=1.0), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertAlmostEqual(_col_f(c[2], 1, 20), 30.0)
        self.assertAlmostEqual(_col_f(c[2], 21, 40), 20.0)

    def test_pressure_cutoffs_are_dropped_loudly(self):
        res, _ = _convert(_deck(_mat124(pcutc=7.0, pcutt=-8.0, pcutf=1.0),
                                124, LC_CT))
        self.assertTrue(any("PCUTC=7" in w and "DROPPED" in w
                            for w in res.warnings), res.warnings)

    def test_cowper_symonds_reference_rate_and_exponent(self):
        """1 + (eps_dot/C)^(1/P): C is the reference rate (-> Epsilon_0) and P
        the exponent (-> c, which the starter echoes as 1/c). dyna2rad writes
        c <- P but never Epsilon_0, losing the reference rate."""
        _, starter = _convert(_deck(_mat124(c=50.0, p=5.0), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertAlmostEqual(_col_f(c[4], 1, 20), 50.0)
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 5.0)

    def test_incomplete_cowper_pair_is_dropped(self):
        res, starter = _convert(_deck(_mat124(c=50.0, p=0.0), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertEqual(_col_f(c[4], 1, 20), 0.0)
        self.assertEqual(_col_f(c[4], 21, 40), 0.0)
        self.assertTrue(any("Cowper-Symonds pair is incomplete" in w
                            for w in res.warnings), res.warnings)

    def test_rate_curves_promote_to_iyld_rate_3(self):
        _, starter = _convert(_deck(_mat124(lcsrc=913, lcsrt=914), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertEqual(_col_i(c[1], 91, 100), 3)
        self.assertEqual(_col_i(c[4], 1, 10), 913)
        self.assertEqual(_col_i(c[4], 11, 20), 914)
        self.assertAlmostEqual(_col_f(c[4], 21, 40), 1.0)
        self.assertAlmostEqual(_col_f(c[4], 41, 60), 1.0)

    def test_vp_is_lost_on_the_rate_curve_branch(self):
        res, _ = _convert(_deck(_mat124(lcsrc=913, srflag=2.0), 124, LC_CT))
        self.assertTrue(any("VP column only exists" in w
                            for w in res.warnings), res.warnings)

    def test_a_lone_rate_curve_gets_a_flat_unit_partner(self):
        """LCSRC and LCSRT are documented independently Optional (p.2-875), so
        an LCSRC-only deck is valid LS-DYNA input — but hm_read_mat66.F:269-278
        loops IFUNC(1..MFUNC) (4 once Iyld_rate=3) and raises MSGID=126
        MSGERROR "WRONG REFERENCE TO FUNCTION ID=0" on any empty slot, so the
        starter would ERROR-TERMINATE. LAW66 applies IFUNC(3)/IFUNC(4) as
        multiplicative yield factors (sigeps66.F:481-487), so a flat 1.0 curve
        on the missing side is exactly LS-DYNA's "no rate effect there"."""
        res, starter = _convert(_deck(_mat124(lcsrc=913), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertEqual(_col_i(c[1], 91, 100), 3)
        self.assertEqual(_col_i(c[4], 1, 10), 913)
        synth = _col_i(c[4], 11, 20)
        self.assertNotEqual(synth, 0, "an empty fnYrt slot is starter ERROR 126")
        self.assertEqual(_funct(starter, synth), [(0.0, 1.0), (1.0, 1.0)])
        self.assertTrue(any("LCSRC=913" in w and "ERROR 126" in w
                            for w in res.warnings), res.warnings)

    def test_a_lone_tension_rate_curve_is_handled_the_same_way(self):
        _, starter = _convert(_deck(_mat124(lcsrt=914), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertEqual(_col_i(c[4], 11, 20), 914)
        synth = _col_i(c[4], 1, 10)
        self.assertNotEqual(synth, 0)
        self.assertEqual(_funct(starter, synth), [(0.0, 1.0), (1.0, 1.0)])

    def test_a_lone_yield_curve_is_mirrored_into_the_empty_slot(self):
        """"Two curves must be defined giving the yield stress ... for both the
        tension and compression regimes" (p.2-877 remark 1), so a one-curve
        deck is already degenerate — but it must not become an ERROR 126
        starter abort. Mirroring keeps the stated branch and makes the other
        identical."""
        res, starter = _convert(_deck(_mat124(lcidc=0, lcidt=912), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertEqual(_col_i(c[3], 1, 10), 912)    # funct_IDc, mirrored
        self.assertEqual(_col_i(c[3], 11, 20), 912)   # funct_IDt, as stated
        self.assertTrue(any("only LCIDT=912" in w and "MIRRORED" in w
                            for w in res.warnings), res.warnings)

    def test_no_yield_curve_at_all_is_still_reported(self):
        """Nothing can be synthesized when neither curve exists — the material
        has no yield input at all, and the warning has to say so."""
        res, starter = _convert(_deck(_mat124(lcidc=0, lcidt=0), 124, LC_CT))
        c = _cards(_block(starter, "/MAT/LAW66/124"))
        self.assertEqual(_col_i(c[3], 1, 10), 0)
        self.assertEqual(_col_i(c[3], 11, 20), 0)
        self.assertTrue(any("neither LCIDC nor LCIDT" in w
                            for w in res.warnings), res.warnings)

    def test_prony_branch(self):
        """/VISC/PRONY shares the material id; Ki/Beta_ki stay 0 because the
        LS-DYNA card carries only the deviatoric Gi/BETAi pairs."""
        _, starter = _convert(_deck(
            _mat124(k=2000.0, prony=((120.0, 55.0), (60.0, 12.0))), 124, LC_CT))
        c = _fail_cards(_block(starter, "/VISC/PRONY/124"))
        self.assertEqual(_col_i(c[0], 1, 10), 2)              # M
        self.assertAlmostEqual(_col_f(c[0], 21, 40), 2000.0)  # K_v
        self.assertEqual([_f20(c[1], i) for i in range(4)],
                         [120.0, 55.0, 0.0, 0.0])
        self.assertEqual([_f20(c[2], i) for i in range(4)],
                         [60.0, 12.0, 0.0, 0.0])

    def test_prony_without_bulk_modulus_is_dropped(self):
        res, starter = _convert(_deck(
            _mat124(k=0.0, prony=((120.0, 55.0),)), 124, LC_CT))
        self.assertFalse(_blocks(starter, "/VISC/PRONY/124"))
        self.assertTrue(any("K=0" in w and "DROPPED" in w
                            for w in res.warnings), res.warnings)

    def test_fail_becomes_johnson(self):
        _, starter = _convert(_deck(_mat124(fail=0.6), 124, LC_CT))
        c = _fail_cards(_block(starter, "/FAIL/JOHNSON/124"))
        self.assertAlmostEqual(_f20(c[0], 0), 0.6)
        self.assertEqual(_col_i(c[1], 21, 30), 2)

    def test_lcfail_becomes_tensstrain_when_active(self):
        """LCFAIL is only applicable under one of four conditions (p.2-878);
        SRFLAG=2 is one of them."""
        _, starter = _convert(_deck(
            _mat124(fail=0.6, lcfail=915, srflag=2.0), 124, LC_CT))
        self.assertFalse(_blocks(starter, "/FAIL/JOHNSON/124"))
        c = _fail_cards(_block(starter, "/FAIL/TENSSTRAIN/124"))
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.0)     # Epsilon_t1
        self.assertAlmostEqual(_col_f(c[0], 21, 40), 1.1)    # Epsilon_t2
        self.assertEqual(_col_i(c[0], 41, 50), 915)          # fct_ID
        self.assertEqual(_col_i(c[0], 91, 100), 0)           # S_Flag

    def test_lcfail_outside_its_gate_falls_back_to_fail(self):
        """dyna2rad's else-if swallows BOTH here and emits no failure at all."""
        res, starter = _convert(_deck(
            _mat124(fail=0.6, lcfail=915, srflag=0.0), 124, LC_CT))
        self.assertFalse(_blocks(starter, "/FAIL/TENSSTRAIN/124"))
        self.assertTrue(_blocks(starter, "/FAIL/JOHNSON/124"))
        self.assertTrue(any("none of the four conditions" in w
                            for w in res.warnings), res.warnings)

    def test_negative_fail_emits_nothing(self):
        res, starter = _convert(_deck(_mat124(fail=-1.0), 124, LC_CT))
        self.assertFalse(_blocks(starter, "/FAIL/JOHNSON/124"))
        self.assertTrue(any("matusr_24" in w for w in res.warnings),
                        res.warnings)

    def test_tdel_and_srfilt_are_reported(self):
        res, _ = _convert(_deck(_mat124(tdel=1e-8, srfilt=0.4), 124, LC_CT))
        self.assertTrue(any("TDEL=1e-08" in w for w in res.warnings))
        self.assertTrue(any("SRFILT=0.4" in w for w in res.warnings))

    def test_prony_pairs_start_at_card_five(self):
        """Card 4 (K) is required even when blank — reading the Prony pairs
        from the first non-blank line after card 3 would eat the K card."""
        state = _dispatch(_deck(
            _mat124(k=0.0, prony=((120.0, 55.0),)), 124))
        mat = state.mat_plas_comp_tens[124]
        self.assertEqual(mat.k, 0.0)
        self.assertEqual(mat.gi, [120.0])
        self.assertEqual(mat.betai, [55.0])


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_120 -> /MAT/LAW52
# ═════════════════════════════════════════════════════════════════════════════

class Mat120Tests(unittest.TestCase):
    """*MAT_GURSON -> /MAT/LAW52 (GURSON)."""

    def test_card_layout_and_porosity_map(self):
        """matl52_gurson.cfg FORMAT(radioss130):
        C2 E(1-20) NU_12(21-40) Iflag(41-50) Fsmooth(51-60) Fcut(61-80)
           Iyield(81-90)
        C3 A(1-20) B(21-40) N(41-60) c(61-80) p(81-100)
        C4 alpha_1 alpha_2 alpha_3 SN EpsN     C5 Fi FN Fc FF"""
        _, starter = _convert(_deck(_mat120(atyp=0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 210000.0)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.3)
        self.assertEqual(_col_i(c[1], 41, 50), 1)      # Iflag: von Mises
        self.assertEqual(_col_i(c[1], 81, 90), 0)      # Iyield: analytic
        self.assertAlmostEqual(_f20(c[2], 0), 350.0)   # A  <- SIGY
        self.assertAlmostEqual(_f20(c[3], 0), 1.5)     # alpha_1 <- Q1
        self.assertAlmostEqual(_f20(c[3], 1), 1.0)     # alpha_2 <- Q2
        self.assertAlmostEqual(_f20(c[3], 3), 0.1)     # SN
        self.assertAlmostEqual(_f20(c[3], 4), 0.3)     # EpsN <- EN
        self.assertAlmostEqual(_f20(c[4], 0), 0.002)   # Fi <- F0
        self.assertAlmostEqual(_f20(c[4], 1), 0.04)    # FN
        self.assertAlmostEqual(_f20(c[4], 2), 0.05)    # Fc <- FC
        self.assertAlmostEqual(_f20(c[4], 3), 0.15)    # FF <- FF0

    def test_q3_is_the_tvergaard_closure(self):
        """LAW52 does NOT default alpha_3 to q1^2 — it stays 0, which is a
        different flow surface. q3 = q1^2 is the standard closure."""
        _, starter = _convert(_deck(_mat120(q1=1.5, q2=1.0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertAlmostEqual(_f20(c[3], 2), 1.5 * 1.5)

    def test_atyp0_is_ideally_plastic(self):
        _, starter = _convert(_deck(_mat120(atyp=0, etan=1500.0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_f20(c[2], 1), 0.0)           # B
        self.assertAlmostEqual(_f20(c[2], 2), 1.0)     # N
        self.assertEqual(_col_i(c[1], 81, 90), 0)

    def test_atyp2_uses_the_plastic_modulus(self):
        """The manual states the linear rule as
        sigma_Y = SIGY + E*ETAN/(E-ETAN)*eps_p (p.2-828), so ETAN here is the
        TOTAL-curve tangent modulus and B is the rescaled plastic slope."""
        _, starter = _convert(_deck(_mat120(atyp=2, etan=1500.0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        expected = 210000.0 * 1500.0 / (210000.0 - 1500.0)
        self.assertAlmostEqual(_f20(c[2], 1), expected, places=4)
        self.assertAlmostEqual(_f20(c[2], 2), 1.0)

    def test_atyp3_builds_a_table_from_the_eight_points(self):
        _, starter = _convert(_deck(_mat120(atyp=3), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_col_i(c[1], 81, 90), 1)      # Iyield
        tab = _col_i(c[5], 1, 10)
        self.assertAlmostEqual(_col_f(c[5], 21, 40), 1.0)   # XFAC
        self.assertAlmostEqual(_col_f(c[5], 41, 60), 1.0)   # YFAC
        self.assertEqual(_funct(starter, tab),
                         [(0.0, 350.0), (0.05, 400.0), (0.1, 430.0),
                          (0.2, 450.0)])
        self.assertIn(f"/TABLE/1/{tab}", starter,
                      "LAW52's Tab_ID slot reads a /TABLE, not a /FUNCT")

    def test_atyp1_power_law_is_sampled(self):
        """sigma_Y = SIGY*((eps_p + SIGY/E)/(SIGY/E))^(1/N) (p.2-828).
        dyna2rad has no conversion at all here and leaves LAW52 with n = 0."""
        res, starter = _convert(_deck(_mat120(atyp=1, n=5.0, sigy=350.0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_col_i(c[1], 81, 90), 1)
        pts = _funct(starter, _col_i(c[5], 1, 10))
        e_y = 350.0 / 210000.0
        self.assertAlmostEqual(pts[0][1], 350.0, places=4)
        for eps, sig in pts:
            self.assertAlmostEqual(
                sig, 350.0 * ((eps + e_y) / e_y) ** (1.0 / 5.0), places=3)
        self.assertTrue(any("ATYP=1 power-law" in w for w in res.warnings),
                        res.warnings)

    def test_atyp1_without_usable_inputs_falls_back_to_ideal(self):
        res, starter = _convert(_deck(_mat120(atyp=1, n=0.0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_col_i(c[1], 81, 90), 0)
        self.assertTrue(any("IDEALLY PLASTIC" in w for w in res.warnings),
                        res.warnings)

    def test_lcss_wins_over_atyp(self):
        """Every ATYP-driven field is documented "only used if LCSS = 0"."""
        _, starter = _convert(_deck(
            _mat120(atyp=2, etan=1500.0, lcss=931), 120,
            _curve(931, ((0.0, 350.0), (0.2, 450.0)))))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_col_i(c[1], 81, 90), 1)
        self.assertEqual(_col_i(c[5], 1, 10), 931)
        self.assertIn("/TABLE/1/931", starter)

    def test_ff_ladder_lcff_over_points_over_ff0(self):
        """FF0 "is only used if no curve is given by (L1,FF1)-(L4,FF4) and
        LCFF = 0" (p.2-828). dyna2rad averages (FF1..FF4)/4 unconditionally,
        which zeroes FF0 whenever the table is absent."""
        # (a) FF0 alone survives
        _, s0 = _convert(_deck(_mat120(ff0=0.15), 120))
        self.assertAlmostEqual(
            _f20(_cards(_block(s0, "/MAT/LAW52/120"))[4], 3), 0.15)
        # (b) the (L, FF) points win, averaged over the STATED ones
        _, s1 = _convert(_deck(_mat120(
            ff0=0.15, card5=(1.0, 2.0, 0.0, 0.0, 0.14, 0.16, 0.0, 0.0)), 120))
        self.assertAlmostEqual(
            _f20(_cards(_block(s1, "/MAT/LAW52/120"))[4], 3), 0.15)
        _, s2 = _convert(_deck(_mat120(
            ff0=0.15, card5=(1.0, 2.0, 3.0, 0.0, 0.10, 0.20, 0.30, 0.0)), 120))
        self.assertAlmostEqual(
            _f20(_cards(_block(s2, "/MAT/LAW52/120"))[4], 3), 0.2)
        # (c) LCFF wins over both, as the mean of its ordinates
        _, s3 = _convert(_deck(
            _mat120(ff0=0.15, card5=(1.0, 2.0, 0.0, 0.0, 0.14, 0.16, 0.0, 0.0),
                    lcff=942), 120,
            _curve(942, ((1.0, 0.10), (2.0, 0.20), (4.0, 0.30)))))
        self.assertAlmostEqual(
            _f20(_cards(_block(s3, "/MAT/LAW52/120"))[4], 3), 0.2)

    def test_lcff_wins_even_when_its_mean_equals_ff0(self):
        """Precedence must be tracked with a FLAG, not by comparing the result
        against FF0: an LCFF whose collapse happens to land ON FF0 still wins
        over the (L, FF) table (p.2-828).

        The ordinates are deliberately equal so the mean is EXACTLY FF0 —
        anything else (mean(0.10, 0.20) = 0.15000000000000002) misses the
        float comparison by luck and the case never fires."""
        _, starter = _convert(_deck(
            _mat120(ff0=0.15, card5=(1.0, 2.0, 0.0, 0.0, 0.30, 0.40, 0.0, 0.0),
                    lcff=942), 120,
            _curve(942, ((1.0, 0.15), (2.0, 0.15)))))
        # LCFF collapses to 0.15 == FF0; the (L, FF) mean would be 0.35.
        self.assertAlmostEqual(
            _f20(_cards(_block(starter, "/MAT/LAW52/120"))[4], 3), 0.15)

    def test_lcf0_lcfc_lcfn_take_the_mean_ordinate(self):
        """All four element-length inputs collapse the same way — the MEAN.
        With the mesh-size regularization gone there is no defensible "the
        model runs at this element size" ordinate, and the mean is the only
        choice independent of how the curve was ordered.

        dyna2rad reads the LCF0 slot under the wrong attribute name and never
        applies it at all (convertmats.cxx:5996 looks up "L1")."""
        _, starter = _convert(_deck(
            _mat120(lcf0=941, lcfc=942, lcfn=943), 120,
            _curve(941, ((1.0, 0.004), (2.0, 0.006)))
            + _curve(942, ((1.0, 0.06), (2.0, 0.08)))
            + _curve(943, ((1.0, 0.05), (2.0, 0.07)))))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertAlmostEqual(_f20(c[4], 0), 0.005)   # Fi  <- LCF0
        self.assertAlmostEqual(_f20(c[4], 1), 0.06)    # FN  <- LCFN
        self.assertAlmostEqual(_f20(c[4], 2), 0.07)    # Fc  <- LCFC

    def test_lcss_on_an_unresolvable_table_falls_back_to_atyp(self):
        """_make_functions writes only tables that are `resolved and rows`, so
        naming an unresolved one as Tab_ID leaves it dangling — starter
        ERROR 779 WRONG REFERENCE TO TABLE ID. The legacy *DEFINE_TABLE form
        takes its curves from the *DEFINE_CURVE blocks that FOLLOW it; with
        none there, the table never resolves."""
        table = ("*DEFINE_TABLE\n" + _row(930) + "\n"
                 + f"{0.0:>20}\n{50.0:>20}\n")   # 2 values, no curves follow
        res, starter = _convert(_deck(
            _mat120(atyp=2, etan=1500.0, lcss=930), 120, table))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_col_i(c[1], 81, 90), 0, "Iyield must fall back to 0")
        self.assertNotIn("/TABLE/1/930", starter)
        self.assertTrue(any("LCSS=930" in w and "could not be resolved" in w
                            and "779" in w for w in res.warnings),
                        res.warnings)
        # ... and the ATYP=2 ladder actually took over: B = E*ETAN/(E-ETAN).
        self.assertAlmostEqual(_f20(c[2], 1),
                               210000.0 * 1500.0 / (210000.0 - 1500.0), 3)

    def test_negative_en_sn_are_curve_ids_and_are_dropped(self):
        res, starter = _convert(_deck(_mat120(en=-941.0, sn=-942.0), 120))
        c = _cards(_block(starter, "/MAT/LAW52/120"))
        self.assertEqual(_f20(c[3], 3), 0.0)
        self.assertEqual(_f20(c[3], 4), 0.0)
        self.assertTrue(any("EN, SN < 0" in w for w in res.warnings),
                        res.warnings)

    def test_error_1745_ordering_is_reported(self):
        res, _ = _convert(_deck(_mat120(f0=0.2, fc=0.05, ff0=0.15), 120))
        self.assertTrue(any("ERROR 1745" in w for w in res.warnings),
                        res.warnings)

    def test_dropped_fields_are_named(self):
        res, _ = _convert(_deck(_mat120(numint=3, vgtyp=1.0, dexp=3.0), 120))
        for token in ("NUMINT=3", "VGTYP=1", "DEXP=3"):
            self.assertTrue(any(token in w for w in res.warnings),
                            f"{token} not reported: {res.warnings}")

    def test_jc_variant_adds_a_fail_johnson(self):
        """*MAT_GURSON_JC card 5 is LCDAM L1 L2 D1 D2 D3 D4 LCJC; D3 is copied
        VERBATIM.

        This keyword's failure strain is written against sigma_H/sigma_M with
        sigma_H the MEAN HYDROSTATIC STRESS (p.2-839/840) — tension-positive
        across the manual (GISSMO p.2-76 "eta = sigma_H/sigma_M, with
        hydrostatic stress sigma_H"; *MAT_252 p.2-1694 "sigma_m = I1/3 ... as
        in Johnson and Cook [1985]") — which is exactly Radioss's
        P = (sigxx+sigyy)/3 over sigma_VM (fail_johnson_c.F:113-117). Only
        *MAT_JOHNSON_COOK's sigma* = p/sigma_eff uses LS-DYNA's
        compression-positive PRESSURE and needs the flip.

        The literature sign is carried here on purpose: a POSITIVE D3 must
        survive as positive, so this pins the "verbatim" behaviour rather than
        an -abs() that could not tell the two apart."""
        res, starter = _convert(_deck(
            _mat120(mid=1200, kw="*MAT_GURSON_JC", atyp=3,
                    card5=(0, 1.0, 2.0, 0.05, 3.44, 2.12, 0.002, 0)), 1200))
        self.assertTrue(_blocks(starter, "/MAT/LAW52/1200"))
        c = _fail_cards(_block(starter, "/FAIL/JOHNSON/1200"))
        self.assertAlmostEqual(_f20(c[0], 0), 0.05)
        self.assertAlmostEqual(_f20(c[0], 1), 3.44)
        self.assertAlmostEqual(_f20(c[0], 2), 2.12)
        self.assertAlmostEqual(_f20(c[0], 3), 0.002)
        self.assertEqual(_f20(c[0], 4), 0.0)
        self.assertEqual(_col_i(c[1], 21, 30), 2)
        self.assertTrue(any("_JC variant" in w for w in res.warnings),
                        res.warnings)

    def test_jc_negative_d3_stays_negative(self):
        """The 4340-steel constants of Johnson & Cook [1985] have D3 = -2.12.
        An -abs() would leave that untouched and so could never be told apart
        from a verbatim copy — this is the case that separates them."""
        _, starter = _convert(_deck(
            _mat120(mid=1200, kw="*MAT_GURSON_JC", atyp=3,
                    card5=(0, 1.0, 2.0, 0.05, 3.44, -2.12, 0.002, 0)), 1200))
        c = _fail_cards(_block(starter, "/FAIL/JOHNSON/1200"))
        self.assertAlmostEqual(_f20(c[0], 2), -2.12)

    def test_lcjc_suppresses_the_johnson_card(self):
        """"If LCJC > 0, parameters D1, D2 and D3 are ignored" (p.2-838): the
        curve replaces the whole D1 + D2*exp(D3*eta) term. /FAIL/JOHNSON has no
        slot for it and only the analytic form, so building one from card-5
        leftovers would erode on a criterion the source deck never evaluates."""
        res, starter = _convert(_deck(
            _mat120(mid=1200, kw="*MAT_GURSON_JC", atyp=3,
                    card5=(0, 1.0, 2.0, 0.05, 3.44, -2.12, 0.002, 802)), 1200,
            _curve(802, ((0.0, 1.2), (1.0, 0.4)))))
        self.assertTrue(_blocks(starter, "/MAT/LAW52/1200"))
        self.assertFalse(_blocks(starter, "/FAIL/JOHNSON/1200"))
        self.assertTrue(any("LCJC=802" in w and "IGNORES D1, D2 and D3" in w
                            for w in res.warnings), res.warnings)

    def test_jc_variant_does_not_read_card5_as_the_ff_table(self):
        state = _dispatch(_deck(
            _mat120(mid=1200, kw="*MAT_GURSON_JC", ff0=0.2,
                    card5=(0, 1.0, 2.0, 0.05, 3.44, 2.12, 0.002, 0)), 1200))
        mat = state.mat_gurson[1200]
        self.assertEqual(mat.ffs, [])
        self.assertEqual(mat.jc_d, [0.05, 3.44, 2.12, 0.002])

    def test_rcdc_variant_leaves_cards_5_and_6_unread(self):
        res, starter = _convert(_deck(
            _mat120(mid=1201, kw="*MAT_GURSON_RCDC", lcss=931,
                    card5=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)), 1201,
            _curve(931, ((0.0, 350.0), (0.2, 450.0)))))
        self.assertTrue(_blocks(starter, "/MAT/LAW52/1201"))
        c = _cards(_block(starter, "/MAT/LAW52/1201"))
        self.assertEqual(_col_i(c[1], 81, 90), 0,
                         "card 6 must not be read at a guessed stride")
        self.assertTrue(any("cards 5 AND 6 are left UNREAD" in w
                            for w in res.warnings), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_012 -> /MAT/LAW2
# ═════════════════════════════════════════════════════════════════════════════

class Mat012Tests(unittest.TestCase):
    """The one LS-DYNA plasticity card written in SHEAR + BULK modulus."""

    def test_g_bulk_to_e_nu(self):
        """E = 9KG/(3K+G), nu = (3K-2G)/(2(3K+G)) — hand-computed from a pair
        chosen so the answer is exact: G = 84000, K = 140000 is the isotropic
        pair of E = 210000, nu = 0.25 (G = E/(2(1+nu)), K = E/(3(1-2nu))).

          3K+G = 420000 + 84000            = 504000
          E    = 9*140000*84000 / 504000   = 210000
          nu   = (420000 - 168000)/1008000 = 0.25
        """
        _, starter = _convert(_deck(_mat012(g=84000.0, bulk=140000.0), 12))
        c = _cards(_block(starter, "/MAT/LAW2/12"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 210000.0, places=6)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.25, places=12)
        self.assertEqual(_col_i(c[1], 41, 50), 0)      # Iflag

    def test_etan_is_the_plastic_hardening_modulus(self):
        """Vol II R17 p.2-206 calls MAT_012's ETAN the "Plastic hardening
        modulus", i.e. dSIGMA/dEPS_PLASTIC — exactly LAW2's b with n = 1. It
        must NOT get the E*ET/(E-ET) rescale *MAT_003's identically-named
        TANGENT modulus needs."""
        _, starter = _convert(_deck(_mat012(sigy=250.0, etan=900.0), 12))
        c = _cards(_block(starter, "/MAT/LAW2/12"))
        self.assertAlmostEqual(_f20(c[2], 0), 250.0)   # a <- SIGY
        self.assertAlmostEqual(_f20(c[2], 1), 900.0)   # b <- ETAN verbatim
        self.assertAlmostEqual(_f20(c[2], 2), 1.0)     # n

    def test_no_rate_thermal_or_failure_terms(self):
        _, starter = _convert(_deck(_mat012(), 12))
        c = _cards(_block(starter, "/MAT/LAW2/12"))
        self.assertEqual([_f20(c[2], i) for i in (3, 4)], [0.0, 0.0])
        self.assertEqual([_f20(c[3], i) for i in (0, 1)], [0.0, 0.0])
        self.assertEqual([_f20(c[4], i) for i in range(4)], [0.0] * 4)
        self.assertFalse(_blocks(starter, "/FAIL/JOHNSON/12"))

    def test_degenerate_moduli_are_reported_not_nan(self):
        """dyna2rad evaluates both expressions through exprtk with no zero
        guard, writing NaN into the /MAT."""
        res, starter = _convert(_deck(_mat012(g=0.0, bulk=0.0), 12))
        c = _cards(_block(starter, "/MAT/LAW2/12"))
        self.assertEqual(_col_f(c[1], 1, 20), 0.0)
        self.assertEqual(_col_f(c[1], 21, 40), 0.0)
        self.assertNotIn("nan", starter.lower())
        self.assertTrue(any("3K+G" in w for w in res.warnings), res.warnings)

    def test_unphysical_poisson_is_reported(self):
        res, _ = _convert(_deck(_mat012(g=1000.0, bulk=100.0), 12))
        self.assertTrue(any("outside the physical" in w for w in res.warnings),
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_122 -> /MAT/LAW43 or /MAT/LAW32
# ═════════════════════════════════════════════════════════════════════════════

class Mat122Tests(unittest.TestCase):
    """*MAT_HILL_3R: three independent Lankford values and an HR-driven law."""

    def test_three_independent_r_values(self):
        """matl43_HILL_TAB.cfg FORMAT(radioss2021) C4:
        r00(1-20) r45(21-40) r90(41-60) C_hard(61-80) Iyield0(81-90). MAT_037
        collapses to r00=r45=r90=|R|; MAT_122 states all three."""
        _, starter = _convert(_deck(_mat122(r00=1.2, r45=1.5, r90=1.8), 122))
        c = _cards(_block(starter, "/MAT/LAW43/122"))
        self.assertAlmostEqual(_f20(c[3], 0), 1.2)
        self.assertAlmostEqual(_f20(c[3], 1), 1.5)
        self.assertAlmostEqual(_f20(c[3], 2), 1.8)
        self.assertEqual(_f20(c[3], 3), 0.0)          # C_hard
        self.assertEqual(_col_i(c[3], 81, 90), 0)     # Iyield0

    def test_hr1_curve_uses_p2_as_yield_and_p1_as_tangent(self):
        """Vol II R17 p.2-852: for HR=1, P1 is the TANGENT modulus and P2 the
        YIELD STRESS. dyna2rad builds {(0, P1), (1, P1+P2)}, i.e. the two
        swapped. The curve is stress vs PLASTIC strain, so P1 (a total-curve
        tangent modulus) becomes the plastic slope E*P1/(E-P1)."""
        _, starter = _convert(_deck(_mat122(hr=1.0, p1=1500.0, p2=280.0), 122))
        c = _cards(_block(starter, "/MAT/LAW43/122"))
        fid = _col_i(c[5], 1, 10)
        h = 210000.0 * 1500.0 / (210000.0 - 1500.0)
        pts = _funct(starter, fid)
        self.assertAlmostEqual(pts[0][0], 0.0)
        self.assertAlmostEqual(pts[0][1], 280.0)
        self.assertAlmostEqual(pts[1][0], 1.0)
        self.assertAlmostEqual(pts[1][1], 280.0 + h, places=4)
        self.assertAlmostEqual(_col_f(c[5], 21, 40), 1.0)   # Fscale_i
        self.assertEqual(_col_f(c[5], 41, 60), 0.0)         # EPS_dot_i

    def test_hr3_binds_the_deck_curve(self):
        _, starter = _convert(_deck(_mat122(hr=3.0, lcid=931), 122,
                                    _curve(931, ((0.0, 300.0), (0.5, 420.0)))))
        c = _cards(_block(starter, "/MAT/LAW43/122"))
        self.assertEqual(_col_i(c[5], 1, 10), 931)

    def test_hr3_without_a_curve_names_error_366(self):
        res, _ = _convert(_deck(_mat122(hr=3.0, lcid=0), 122))
        self.assertTrue(any("ERROR 366" in w for w in res.warnings),
                        res.warnings)

    def test_hr2_routes_to_law32(self):
        """sigma = k*(E0 + eps_p)^n is LAW32's analytic Swift law exactly:
        A <- P1 (k), EPSILON_0 <- E0, n <- P2. dyna2rad emits NOTHING for
        HR=2 (no third branch), leaving NUM_CURVES=0 and starter ERROR 366."""
        res, starter = _convert(_deck(
            _mat122(hr=2.0, p1=700.0, p2=0.25, e0=0.005), 122))
        self.assertFalse(_blocks(starter, "/MAT/LAW43/122"))
        c = _cards(_block(starter, "/MAT/LAW32/122"))
        self.assertAlmostEqual(_col_f(c[1], 1, 20), 210000.0)
        self.assertAlmostEqual(_col_f(c[1], 21, 40), 0.3)
        self.assertAlmostEqual(_f20(c[2], 0), 700.0)     # A         <- P1 (k)
        self.assertAlmostEqual(_f20(c[2], 1), 0.005)     # EPSILON_0 <- E0
        self.assertAlmostEqual(_f20(c[2], 2), 0.25)      # n         <- P2
        self.assertAlmostEqual(_f20(c[4], 0), 1.2)       # r00
        self.assertAlmostEqual(_f20(c[4], 1), 1.5)
        self.assertAlmostEqual(_f20(c[4], 2), 1.8)
        self.assertTrue(any("LAW32" in w for w in res.warnings), res.warnings)

    def test_zero_r_value_fallback_is_reported(self):
        res, starter = _convert(_deck(_mat122(r00=0.0), 122))
        c = _cards(_block(starter, "/MAT/LAW43/122"))
        self.assertAlmostEqual(_f20(c[3], 0), 1.0)
        self.assertTrue(any("VON MISES" in w for w in res.warnings),
                        res.warnings)

    def test_part_moves_to_a_prop_type9(self):
        """LAW43/LAW32 register SHELL_ORTHOTROPIC only; /PROP/SHELL (IGTYP 1)
        accepts PROP_SHELL 1 or 5, so a meshed part hard-fails with starter
        ERROR 3047 unless it is repointed."""
        res, starter = _convert(_deck(_mat122(), 122))
        self.assertTrue(_blocks(starter, "/PROP/TYPE9/"),
                        "no orthotropic property synthesized")
        part = _block(starter, "/PART/7")
        prop_id = _i10(part[2], 0)
        self.assertTrue(_blocks(starter, f"/PROP/TYPE9/{prop_id}"))
        self.assertTrue(any("ERROR 3047" in w for w in res.warnings),
                        res.warnings)

    def test_aopt2_reaches_the_property_reference_vector(self):
        """/PROP/TYPE9 card 4: Vx(1-20) Vy(21-40) Vz(41-60) Phi(61-80).
        dyna2rad reads none of MAT_122's AOPT block at all."""
        _, starter = _convert(_deck(
            _mat122(aopt=2.0, a=(0.0, 1.0, 0.0), beta=15.0), 122))
        blocks = _blocks(starter, "/PROP/TYPE9/")
        self.assertEqual(len(blocks), 1)
        c = _cards(blocks[0])
        self.assertAlmostEqual(_f20(c[3], 0), 0.0)
        self.assertAlmostEqual(_f20(c[3], 1), 1.0)
        self.assertAlmostEqual(_f20(c[3], 2), 0.0)
        self.assertAlmostEqual(_f20(c[3], 3), 15.0)     # Phi <- BETA

    def test_unmapped_aopt_falls_back_and_warns(self):
        res, starter = _convert(_deck(
            _mat122(aopt=3.0, v=(1.0, 0.0, 0.0)), 122))
        c = _cards(_blocks(starter, "/PROP/TYPE9/")[0])
        self.assertAlmostEqual(_f20(c[3], 0), 1.0)      # default global X
        self.assertEqual(_f20(c[3], 1), 0.0)
        self.assertTrue(any("only AOPT=2" in w for w in res.warnings),
                        res.warnings)

    def test_aopt0_names_the_element_node_axes_it_drops(self):
        """AOPT=0 is the card's DEFAULT and what a blank field means: "material
        axes determined by element nodes 1, 2, and 4 ... then rotated about the
        shell element normal by an angle BETA" (p.2-853). /PROP/TYPE9 has one
        global vector for the whole property, so that rule is DROPPED — and on
        a Hill sheet law the rolling direction is the point of the model, so
        the fallback to global X has to be stated, not implied by a generic
        "AOPT=2 is not set"."""
        res, starter = _convert(_deck(_mat122(aopt=0.0, beta=20.0), 122))
        c = _cards(_blocks(starter, "/PROP/TYPE9/")[0])
        self.assertAlmostEqual(_f20(c[3], 0), 1.0)      # default global X
        self.assertAlmostEqual(_f20(c[3], 3), 20.0)     # Phi <- BETA
        self.assertTrue(any("AOPT=0" in w and "nodes 1, 2 and 4" in w
                            and "DROPPED" in w for w in res.warnings),
                        res.warnings)

    def test_solid_part_on_law43_is_refused(self):
        solid_nodes = (
            "*NODE\n" + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n"
                                for n, x, y, z in (
                (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
                (4, 0.0, 10.0, 0.0), (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
                (7, 10.0, 10.0, 10.0), (8, 0.0, 10.0, 10.0))))
        deck = (solid_nodes
                + "*ELEMENT_SOLID\n" + _row(1, 7) + "\n"
                + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
                + _part(122) + "*SECTION_SOLID\n" + _row(7, 1) + "\n"
                + _mat122() + END)
        res, _ = _convert(deck)
        self.assertTrue(any("SHELL-ONLY law" in w and "MAT_HILL_3R" in w
                            for w in res.warnings), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Routing map + id-namespace coverage
# ═════════════════════════════════════════════════════════════════════════════

class TargetMatLawTests(unittest.TestCase):
    """_target_mat_law is the ONE mid -> emitted-law map (writer/mesh.py); a
    family missing from it makes the beam-compat check silently `continue`, so
    a beam part on the new law goes back to being converted into an
    unrunnable deck with no message."""

    CASES = (
        (81, _mat081(), 36),
        (82, _mat081(mid=82, kw="*MAT_082"), 36),
        (105, _mat105(), 36),
        (19, _mat019(), 121),
        (124, _mat124(), 66),
        (120, _mat120(), 52),
        (12, _mat012(), 2),
        (122, _mat122(hr=1.0), 43),
        (122, _mat122(hr=2.0, p1=700.0, p2=0.25), 32),
    )

    def test_every_new_family_is_mapped(self):
        from k2rad.writer.assembly import build_starter
        for mid, mat, law in self.CASES:
            with self.subTest(mid=mid, law=law):
                state = _dispatch(_deck(mat, mid, LC_CT + LC_RATE))
                build_starter(state)
                self.assertEqual(_target_mat_law(state, mid), law)

    def test_all_mat_ids_covers_the_new_containers(self):
        """next_mat_id() guards synthesized ids against all_mat_ids(); a family
        left out of that union is a starter ERROR 79 DUPLICATE ID waiting to
        happen."""
        deck = (NODES + SHELL + _part(81) + SECTION
                + _mat081() + _mat105() + _mat019() + _mat124()
                + _mat120() + _mat012() + _mat122()
                + LC_CT + LC_RATE + END)
        state = _dispatch(deck)
        ids = state.all_mat_ids()
        for mid in (81, 105, 19, 124, 120, 12, 122):
            self.assertIn(mid, ids)

    def test_beam_compat_warning_names_the_new_laws(self):
        """None of LAW52/66/121/32 declares a beam keyword (PROP_BEAM = 0), so
        a beam part on one of them is starter ERROR 3046 — the warning must
        name it rather than silently skip the part."""
        deck = (
            "*NODE\n"
            + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 0.0, 10.0, 0.0)))
            + "*ELEMENT_BEAM\n" + _row(1, 7, 1, 2, 3) + "\n"
            + _part(19) + "*SECTION_BEAM\n" + _row(7, 2) + "\n"
            + _row(1.0, 1.0, 1.0, 1.0) + "\n"
            + _mat019() + LC_RATE + END)
        res, _ = _convert(deck)
        self.assertTrue(any("/MAT/LAW121" in w and "ERROR 3046" in w
                            for w in res.warnings), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# Multi-material deck + byte-identity
# ═════════════════════════════════════════════════════════════════════════════

class BatchIntegrationTests(unittest.TestCase):

    def test_all_seven_families_in_one_deck(self):
        """Nine parts, one per keyword, every material referenced — the shape
        of the deck that was validated on a live starter run (0 ERROR(S), the
        one documented /FAIL/LEMAITRE WARNING 100211)."""
        mids = [81, 82, 105, 19, 124, 120, 1200, 12, 122]
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
                 + _mat081() + _mat081(mid=82, kw="*MAT_082")
                 + _mat105() + _mat019() + _mat124()
                 + _mat120(atyp=1, n=5.0)
                 + _mat120(mid=1200, kw="*MAT_GURSON_JC", atyp=3,
                           card5=(0, 1.0, 2.0, 0.05, 3.44, 2.12, 0.002, 0))
                 + _mat012() + _mat122()
                 + LC_CT + LC_RATE + END)
        res, starter = _convert(deck)
        for header in ("/MAT/LAW36/81", "/MAT/LAW36/82", "/MAT/LAW36/105",
                       "/MAT/LAW121/19", "/MAT/LAW66/124", "/MAT/LAW52/120",
                       "/MAT/LAW52/1200", "/MAT/LAW2/12", "/MAT/LAW43/122",
                       "/FAIL/TAB1/81", "/FAIL/TAB1/82", "/FAIL/JOHNSON/105",
                       "/FAIL/LEMAITRE/105", "/FAIL/JOHNSON/124",
                       "/FAIL/JOHNSON/1200"):
            with self.subTest(header=header):
                self.assertTrue(_blocks(starter, header),
                                f"{header} missing from the converted deck")
        self.assertEqual(res.skipped_keywords, [])
        # Every /MAT id is distinct — no family shadows another's dict entry.
        mat_ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
                   if ln.startswith("/MAT/LAW")]
        self.assertEqual(len(mat_ids), len(set(mat_ids)))

    def test_goldens_are_unchanged(self):
        """A pure-addition batch adds no card to a deck that does not use the
        new keywords, so the five checked-in goldens must be byte-identical —
        if one moves, the change leaked into a shared emitter (the two known
        risks here are _emit_fail_johnson_all_layers' positional defaults and
        the LAW36 single-curve header block)."""
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
