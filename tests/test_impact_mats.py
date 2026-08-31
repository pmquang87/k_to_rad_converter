"""Tests for the IMPACT / BLAST materials batch conversions:

  *MAT_JOHNSON_HOLMQUIST_CERAMICS (110)  -> /MAT/LAW79  (JOHN_HOLM, JH-2)
  *MAT_JOHNSON_HOLMQUIST_CONCRETE (111)  -> /MAT/LAW126
  *MAT_ELASTIC + _FLUID option    (001)  -> /MAT/LAW6 (HYD_VISC)
                                            + /EOS/POLYNOMIAL of the same id

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_foams.py, tests/test_adhesives.py, tests/test_viscoelastic.py and
tests/test_tabulated_jc.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant is recomputed by hand in the test rather than copied from the
implementation.

The batch's defining property is that NOTHING is normalized on conversion, and
that is what the arithmetic here pins from both ends. For JH-2 the test
recomputes sigma_HEL = 1.5*(HEL-PHEL) = 1.5*(19e9-1.46e9) = 2.631e10 and
T* = T/PHEL = 0.2e9/1.46e9 = 0.1369863..., then asserts NEITHER appears in any
emitted field -- HEL, PHEL and T go out as physical stresses and the starter
re-derives both itself (hm_read_mat79.F:211-213, sigeps79.F:153,190), so a
converter that pre-divided would soften the ceramic silently. The same test
runs for JHC: T* = T/FC = 4e6/48e6 = 1/12 = 0.08333... is asserted ABSENT and
the physical 4e6 present (sigeps126.F90:338 forms it from FC at run time). The
elastic constants LAW79 derives from the two fields most at risk of a slot
mix-up are recomputed independently and matched against the starter's own
echo: E = 9*K1*G/(3*K1+G) = 9*130.95e9*90.16e9/(392.85e9+90.16e9)
= 2.19991445e11 and nu = (3*K1-2G)/(6*K1+2G) = 212.53e9/966.02e9 = 0.2200058,
which is what a live starter prints for this card; LAW126's region-1 bulk
modulus k0 = PC/MUC = 16e6/1e-3 = 16e9 likewise. And the *MAT_ELASTIC_FLUID
K == 0 fallback is computed the manual's way, K = E/(3(1-2*PR))
= 3e9/(3*0.5) = 2.0e9, with the dyna2rad value E/3 = 1.0e9 asserted ABSENT --
that converter's expression uses the token 'NU' where the attribute is spelled
'Nu', identifier lookup is case-sensitive, and an unresolved token silently
becomes 0 (convertutilsbase.cxx:192), so it loses Poisson's ratio entirely.

Two fields are NOT straight copies, and each is pinned from both ends. PHEL: a
blank/0 PHEL is a documented LS-DYNA derivation request ("These are calculated
automatically by LS-DYNA if p_hel is zero on input", Vol II R16 p.2-764), which
Radioss does not implement, so the test Newton-solves
HEL = K1*mu + K2*mu^2 + K3*mu^3 + (4/3)*G*mu/(1+mu) itself -- mu_hel =
0.07837428750607 and PHEL = 1.0263112948920e10 for the card in use -- and
asserts the emitted field against that, plus that a stated PHEL is untouched
and that an underivable card still draws the hard warning. EPS0: it is a
1/TIME quantity and k2rad rescales nothing, so the value substituted for an
unusable EPS0 is asserted to be 1 s^-1 expressed in the DECK's time unit (1.0
on Mg-mm-s, 1e-3 on ms, 1e-6 on us), with the label parser checked against the
starter's own rule (unit_code.F:99-143: at most three characters, last one 's')
including the labels it rejects.

Where a conversion turns on what an LS-DYNA field MEANS rather than on
arithmetic -- MAT_110's FS being inexpressible at /BEGIN 2022 because LAW79's
IDEL/EPSMAX are radioss2023 fields, MAT_111's FS mapping onto a DIFFERENT
three-way IDEL rule than MAT_110's would use (the LS-DYNA meanings and the
Radioss enumerations both differ between the two laws), the unguarded
k0 = PC/MUC and h = (PL-PC)/MUL divisions that produce a silent NaN with 0
ERROR / 0 WARNING, PHEL <= 0 passing LAW79's only guard (PHEL > HEL) and then
poisoning T* with Inf, VC being a dimensionless tensor-viscosity coefficient
rather than the kinematic viscosity its Radioss slot expects, and a defaulted
CP = 1e20 meaning "no cavitation limit" rather than a finite one -- the
assertion pins the warning that states it. The CP sentinel additionally has to
be unit-INVARIANT, since 1e20 is a raw literal a unit converter rescales: the
corpus bird-strike fluid carries CP = 1e20 with K = 2.2e9 in its kg-m-s copy
and CP = 1e14 with K = 2200 in the ton-mm-s one, the same material, and both
are asserted to emit the same Pmin.

Several dyna2rad defects are FIXED consciously and asserted as fixes:
MAT_110's FS is dropped SILENTLY there at every format version (it is absent
from p_ConvertMatL110's attribute map, CM:12491-12506) though the same
converter implements the flag for MAT_111; the *MAT_ELASTIC_FLUID K == 0
expression loses PR as described above; K < 0 matches neither of its two
branches and leaves the EOS bulk modulus at 0 (a fluid with zero sound speed);
a defaulted CP lands on Pmin = -1e20 instead of -INFINITY; VC is copied
verbatim into a slot that means something else; and *MAT_001_FLUID is missing
from dynamatlawkeywordmap.h entirely, so it produces no /MAT at all and the
part is wired to mat_ID 0 (starter ERROR 3046) -- k2rad registers that
spelling, and the bare *MAT_001 / *MAT_1 numerics with it.

The byte-identity of the pre-existing plain *MAT_ELASTIC path is asserted
directly (TestMat001BaseVsFluidSplit): the FLUID variant lives in its own
container, so /MAT/ELAST, its LAW1 entry in _target_mat_law and therefore its
place on the starter's solid-/XREF law whitelist are untouched.

Card layouts audited against hm_cfg_files at the revision a /BEGIN 2022 deck
reads: radioss120/MAT/matl79_79.cfg FORMAT(radioss120):207-236 for LAW79
(native at 2022, no version warning -- radioss2022/data_hierarchy.cfg:1301-1307
lists it), radioss2024/MAT/matl126_johnson_holmquist_concrete.cfg
FORMAT(radioss2024):189-202 for LAW126 (the oldest block that exists for this
law, so a 2022 deck falls forward into it under one cosmetic WARNING 100211),
radioss2020/MAT/mat_law6.cfg FORMAT(radioss2018):318-326 for LAW6 and
radioss2022/MAT/mat_EOS.cfg FORMAT(radioss2022) for /EOS/POLYNOMIAL. The two
version-gated omissions are asserted as omissions: LAW79 card 4 stops at
SIGMA_FMAX (no Fcut) and card 6 at D2 (no IDEL/EPSMAX), and LAW126 card 7
stops at EPS_MAX (no IFAILSO) with no CT/POWT/CC/POWC card 8.
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


# ── Harness (same shape as tests/test_tabulated_jc.py) ───────────────────────

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
    out = "".join(f"{v:>10}" for v in vals)
    assert len(out) == 10 * len(vals), f"field overflow in {out!r}"
    return out


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
    """A /MAT or /EOS block's DATA lines (title skipped, comments skipped)."""
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
SEC_SOLID = "*SECTION_SOLID\n" + _row(7, 1) + "\n"
SEC_SHELL = ("*SECTION_SHELL\n" + _row(8, 2, 1.0, 5) + "\n"
             + _row(1.2, 1.2, 1.2, 1.2) + "\n")


def _solid(eid, pid):
    return "*ELEMENT_SOLID\n" + _row(eid, pid) + "\n" + _row(*range(1, 9)) + "\n"


def _shell(eid, pid):
    return "*ELEMENT_SHELL\n" + _row(eid, pid, 1, 2, 3, 4) + "\n"


def _part(pid, secid, mid, name="impact part"):
    return f"*PART\n{name}\n" + _row(pid, secid, mid) + "\n"


# A solid mesh whose single part carries material *mid*.
def MESH(mid, pid=7):
    return "*KEYWORD\n" + NODES + _solid(1, pid) + _part(pid, 7, mid) + SEC_SOLID


# ── Card values, verbatim from the starter-verified probe in the batch spec ──
# *MAT_110 SI (kg-m-s) alumina: RHO 3700, G 90.16e9, A .93, B .31, C .007,
# M .6, N .64 / EPS0 1.0, T 0.2e9, SFMAX .8, HEL 19e9, PHEL 1.46e9, BETA 1.0 /
# D1 .005, D2 1.0, K1 130.95e9, K2 0, K3 0, FS 0.2
MAT110_C1 = (110, 3700.0, "90.16E9", 0.93, 0.31, 0.007, 0.6, 0.64)
MAT110_C2 = (1.0, "0.2E9", 0.8, "19E9", "1.46E9", 1.0)


def _mat110(c1=MAT110_C1, c2=MAT110_C2, fs=0.2,
            kw="*MAT_JOHNSON_HOLMQUIST_CERAMICS", title=None,
            c3=(0.005, 1.0, "130.95E9", 0.0, 0.0)):
    out = kw + "\n"
    if title is not None:
        out += title + "\n"
    return out + _row(*c1) + "\n" + _row(*c2) + "\n" + _row(*c3, fs) + "\n"


# *MAT_111 SI concrete: RHO 2440, G 14.86e9, A .79, B 1.6, C .007, N .61,
# FC 48e6 / T 4e6, EPS0 1.0, EFMIN .01, SFMAX 7.0, PC 16e6, UC 1e-3, PL 800e6,
# UL 0.10 / D1 .04, D2 1.0, K1 85e9, K2 -171e9, K3 208e9, FS 0.30
MAT111_C1 = (111, 2440.0, "14.86E9", 0.79, 1.6, 0.007, 0.61, "48E6")
MAT111_C2 = ("4E6", 1.0, 0.01, 7.0, "16E6", "1E-3", "800E6", 0.10)


def _mat111(c1=MAT111_C1, c2=MAT111_C2, fs=0.30,
            kw="*MAT_JOHNSON_HOLMQUIST_CONCRETE", title=None,
            c3=(0.04, 1.0, "85E9", "-171E9", "208E9")):
    out = kw + "\n"
    if title is not None:
        out += title + "\n"
    return out + _row(*c1) + "\n" + _row(*c2) + "\n" + _row(*c3, fs) + "\n"


def _fluid(mid=3, rho=2600.0, e=0.0, pr=0.0, da=0.0, db=0.0, k="2.2E9",
           card2=(0.0, "1.0E20"), kw="*MAT_ELASTIC_FLUID", title=None):
    out = kw + "\n"
    if title is not None:
        out += title + "\n"
    out += _row(mid, rho, e, pr, da, db, k) + "\n"
    if card2 is not None:
        out += _row(*card2) + "\n"
    return out


DECK_110 = MESH(110) + _mat110() + "*END\n"
DECK_111 = MESH(111) + _mat111() + "*END\n"
DECK_FLUID = MESH(3) + _fluid() + "*END\n"


# ─────────────────────────────────────────────────────────────────────────────
# A) *MAT_JOHNSON_HOLMQUIST_CERAMICS (110) -> /MAT/LAW79
# ─────────────────────────────────────────────────────────────────────────────

class TestLaw79Card(unittest.TestCase):
    """Column-exact /MAT/LAW79, FORMAT(radioss120) -- the block a /BEGIN 2022
    deck reads (7 data cards, all fields 20 wide)."""

    def setUp(self):
        self.res, self.starter = _convert(DECK_110)
        self.blk = _block(self.starter, "/MAT/LAW79/110")
        self.mat = _cards(self.blk)

    def test_header_and_card_count(self):
        # /MAT/LAW79/<mid>, not /MAT/JOHN_HOLM: both parse identically
        # (hm_read_mat.F90:911 case ('LAW79','JOHN_HOLM')), LAW79 is shorter.
        self.assertEqual(self.blk[0], "/MAT/LAW79/110")
        self.assertEqual(self.blk[1], "MAT_110")          # no *_TITLE given
        self.assertEqual(len(self.mat), 7)                # exactly 7 data cards

    def test_card1_density_is_a_SINGLE_field(self):
        # The CFG runs CARD_PREREAD("%20s") on cols 21-40 and ANY non-blank
        # there switches card 1 to the two-field rho_i/rho_0 form. Emitting one
        # field is the unambiguous "reference density = initial density".
        self.assertEqual(_col_f(self.mat[0], 1, 20), 3700.0)
        self.assertEqual(len(self.mat[0]), 20)

    def test_card2_shear_modulus(self):
        self.assertEqual(_col_f(self.mat[1], 1, 20), 90.16e9)
        self.assertEqual(len(self.mat[1]), 20)

    def test_card3_a_b_m_n_field_order_swap(self):
        # LS-DYNA card 1 runs "... C M N" (M at field 7, N at field 8) while
        # LAW79 card 3 runs "a b m n" with c moved to card 4 -- the one field
        # reordering of this conversion. m is the FRACTURED pressure exponent
        # and n the INTACT one; swapping them inverts the two yield surfaces.
        self.assertEqual(_col_f(self.mat[2], 1, 20), 0.93)     # a  <- A
        self.assertEqual(_col_f(self.mat[2], 21, 40), 0.31)    # b  <- B
        self.assertEqual(_col_f(self.mat[2], 41, 60), 0.6)     # m  <- M (fld 7)
        self.assertEqual(_col_f(self.mat[2], 61, 80), 0.64)    # n  <- N (fld 8)
        self.assertEqual(len(self.mat[2]), 80)

    def test_card4_c_eps0_sfmax_and_NO_fcut(self):
        self.assertEqual(_col_f(self.mat[3], 1, 20), 0.007)    # c    <- C
        self.assertEqual(_col_f(self.mat[3], 21, 40), 1.0)     # EPS0 <- EPS0
        self.assertEqual(_col_f(self.mat[3], 41, 60), 0.8)     # SIGMA_FMAX
        # Fcut is a FORMAT(radioss2023) field (card 4 col 61-80). A /BEGIN 2022
        # deck reads FORMAT(radioss120), which ends at SIGMA_FMAX -- writing it
        # would draw WARNING 100213 for a field the starter then discards.
        self.assertEqual(len(self.mat[3]), 60)

    def test_card5_T_HEL_PHEL_are_PHYSICAL_stresses(self):
        self.assertEqual(_col_f(self.mat[4], 1, 20), 0.2e9)    # T
        self.assertEqual(_col_f(self.mat[4], 21, 40), 19e9)    # HEL
        self.assertEqual(_col_f(self.mat[4], 41, 60), 1.46e9)  # PHEL
        self.assertEqual(len(self.mat[4]), 60)

    def test_card6_D1_D2_and_NO_idel_epsmax(self):
        self.assertEqual(_col_f(self.mat[5], 1, 20), 0.005)
        self.assertEqual(_col_f(self.mat[5], 21, 40), 1.0)
        # IDEL (%10d at cols 51-60) and EPSMAX (cols 61-80) are
        # FORMAT(radioss2023) fields. See TestMat110FSNotExpressible.
        self.assertEqual(len(self.mat[5]), 40)

    def test_card7_K1_K2_K3_BETA(self):
        # BETA moves from LS-DYNA card 2 field 6 to the END of LAW79 card 7.
        self.assertEqual(_col_f(self.mat[6], 1, 20), 130.95e9)  # K1
        self.assertEqual(_col_f(self.mat[6], 21, 40), 0.0)      # K2
        self.assertEqual(_col_f(self.mat[6], 41, 60), 0.0)      # K3
        self.assertEqual(_col_f(self.mat[6], 61, 80), 1.0)      # BETA
        self.assertEqual(len(self.mat[6]), 80)

    def test_no_EOS_is_emitted_for_the_JH_polynomial(self):
        # K1/K2/K3 are LAW79's OWN pressure law, P = K1*mu + K2*mu^2 + K3*mu^3
        # (sigeps79.F:143-147, UPARAM(15..17)) -- an /EOS block would be both
        # unnecessary and, sharing the material id, a starter ERROR 79.
        self.assertNotIn("/EOS/", self.starter)


class TestLaw79NoNormalization(unittest.TestCase):
    """The batch's classic trap: sigma_HEL, T* and P* are all derived by the
    Radioss starter/engine, so the converter must NOT pre-apply them."""

    def setUp(self):
        self.res, self.starter = _convert(DECK_110)
        self.mat = _cards(_block(self.starter, "/MAT/LAW79/110"))
        self.fields = [_col_f(ln, a, a + 19)
                       for ln in self.mat
                       for a in range(1, len(ln), 20)]

    def test_sigma_hel_is_never_written(self):
        # hm_read_mat79.F:213  UPARAM(12) = THREE_HALF*(HEL-PHEL)
        sigma_hel = 1.5 * (19e9 - 1.46e9)
        self.assertEqual(sigma_hel, 2.631e10)
        for v in self.fields:
            self.assertNotAlmostEqual(v, sigma_hel, delta=1.0)

    def test_T_is_not_pre_divided_by_PHEL(self):
        # hm_read_mat79.F:211  UPARAM(10) = TMAX/PHEL -- the starter forms t*.
        t_star = 0.2e9 / 1.46e9
        self.assertAlmostEqual(t_star, 0.1369863013698630, places=12)
        self.assertEqual(_col_f(self.mat[4], 1, 20), 0.2e9)
        for v in self.fields:
            self.assertNotAlmostEqual(v, t_star, places=6)

    def test_HEL_and_PHEL_are_not_swapped_or_combined(self):
        self.assertEqual(_col_f(self.mat[4], 21, 40), 19e9)
        self.assertEqual(_col_f(self.mat[4], 41, 60), 1.46e9)
        self.assertGreater(_col_f(self.mat[4], 21, 40),
                           _col_f(self.mat[4], 41, 60))   # else ERROR 907

    def test_derived_elastic_constants_match_the_starter_echo(self):
        # PARMAT(2) = E = 9*K1*G/(3*K1+G), PARMAT(3) = nu = (3K1-2G)/(6K1+2G).
        # Recomputed here from the values the test itself asserted into the K1
        # and G slots; a live starter prints exactly these for this card.
        k1 = _col_f(self.mat[6], 1, 20)
        g = _col_f(self.mat[1], 1, 20)
        e = 9.0 * k1 * g / (3.0 * k1 + g)
        nu = (3.0 * k1 - 2.0 * g) / (6.0 * k1 + 2.0 * g)
        self.assertAlmostEqual(e, 219991445311.7, delta=1.0)
        self.assertAlmostEqual(nu, 0.2200057970, places=9)

    def test_A_B_C_M_N_SFMAX_are_dimensionless_on_both_sides(self):
        # No unit factor may be applied to the normalized-strength constants:
        # sigeps79.F:160 SIGYI = AA*(PSTAR+TSTAR)**NN, :170 SIGYF =
        # BB*(PSTAR)**MM, :183 SIGYF = MIN(SIGYF, SIGFMAX) -- all in sigma*.
        for a, b, want in ((1, 20, 0.93), (21, 40, 0.31),
                           (41, 60, 0.6), (61, 80, 0.64)):
            self.assertEqual(_col_f(self.mat[2], a, b), want)
        self.assertEqual(_col_f(self.mat[3], 1, 20), 0.007)
        self.assertEqual(_col_f(self.mat[3], 41, 60), 0.8)


class TestMat110FSNotExpressible(unittest.TestCase):
    """FS in all three sign cases. At /BEGIN 2022 LAW79's IDEL/EPSMAX simply do
    not exist, so the only correct behaviour is a loud warning."""

    NEEDLE = "NOT EXPRESSIBLE"

    def test_fs_positive_warns_naming_idel2_and_epsmax(self):
        res, starter = _convert(MESH(110) + _mat110(fs=0.25) + "*END\n")
        hits = _warns(res, self.NEEDLE)
        self.assertEqual(len(hits), 1)
        self.assertIn("FS=0.25 > 0", hits[0])
        self.assertIn("IDEL=2 with EPSMAX=0.25", hits[0])
        self.assertIn("radioss2023", hits[0])
        self.assertIn("*MAT_ADD_EROSION", hits[0])      # the remedy
        # and nothing resembling IDEL/EPSMAX reaches the card
        mat = _cards(_block(starter, "/MAT/LAW79/110"))
        self.assertEqual(len(mat[5]), 40)

    def test_fs_negative_warns_naming_idel1_tension(self):
        res, _ = _convert(MESH(110) + _mat110(fs=-0.5) + "*END\n")
        hits = _warns(res, self.NEEDLE)
        self.assertEqual(len(hits), 1)
        self.assertIn("FS=-0.5 < 0", hits[0])
        # LS-DYNA FS<0 = "fail if p*+t* < 0"; LAW79 IDEL 1 = "deletion in
        # tension only". NOTE this is NOT MAT_111's mapping (which sends FS<0
        # to IDEL 3) -- both the LS-DYNA meanings and the Radioss IDEL
        # enumerations differ between the two laws.
        self.assertIn("IDEL=1", hits[0])
        self.assertIn("p* + t* < 0", hits[0])

    def test_fs_zero_is_the_default_on_BOTH_sides_so_no_warning(self):
        # LS-DYNA FS = 0 -> "no failure" (the card default); LAW79 IDEL = 0 ->
        # "no element deletion" (the reader default). Nothing is lost.
        res, _ = _convert(MESH(110) + _mat110(fs=0.0) + "*END\n")
        self.assertEqual(_warns(res, self.NEEDLE), [])

    def test_warning_names_that_dyna2rad_drops_FS_silently(self):
        res, _ = _convert(MESH(110) + _mat110(fs=0.25) + "*END\n")
        hit = _warns(res, self.NEEDLE)[0]
        self.assertIn("dyna2rad drops MAT_110's FS SILENTLY", hit)

    def test_warning_states_the_tensile_cutoff_survives(self):
        # sigeps79.F:149-151 applies PMIN = -T*.PHEL.(1-D) in the ELSEIF
        # (IDEL /= 1) branch, so IDEL=0 keeps tensile softening -- only the
        # element DELETION is lost. Saying so stops the warning reading as
        # "all failure is gone".
        res, _ = _convert(MESH(110) + _mat110(fs=0.25) + "*END\n")
        self.assertIn("only element deletion",
                      _warns(res, self.NEEDLE)[0])


class TestMat110Guards(unittest.TestCase):
    def test_eps0_zero_with_rate_term_is_substituted_with_1(self):
        # Starter ERROR 910 is FATAL and dyna2rad walks straight into it.
        c2 = (0.0, "0.2E9", 0.8, "19E9", "1.46E9", 1.0)     # EPS0 blank, C=.007
        res, starter = _convert(MESH(110) + _mat110(c2=c2) + "*END\n")
        mat = _cards(_block(starter, "/MAT/LAW79/110"))
        self.assertEqual(_col_f(mat[3], 21, 40), 1.0)       # substituted
        self.assertEqual(_col_f(mat[3], 1, 20), 0.007)      # C untouched
        hits = _warns(res, "ERROR 910")
        self.assertEqual(len(hits), 1)
        # EPS0 is a 1/TIME quantity (Vol II R16 *MAT_015: "input in units of
        # [time]^-1"), so the substituted value has to name its unit. On the
        # default Mg-mm-s deck 1 s^-1 IS 1.0, so the emitted number is
        # unchanged; TestEps0UnitDependence pins the ms/us cases.
        self.assertIn("k2rad writes EPS0 = 1 per the deck's time unit 's' "
                      "(= 1 s^-1)", hits[0])
        self.assertIn("sigeps79.F:178-182", hits[0])

    def test_eps0_zero_with_C_zero_is_left_alone(self):
        # hm_read_mat79.F:159 IF(CC==ZERO) EPS0 = ONE -- the starter fixes it
        # itself and 910 never fires, so the converter must not interfere.
        c1 = (110, 3700.0, "90.16E9", 0.93, 0.31, 0.0, 0.6, 0.64)
        c2 = (0.0, "0.2E9", 0.8, "19E9", "1.46E9", 1.0)
        res, starter = _convert(MESH(110) + _mat110(c1=c1, c2=c2) + "*END\n")
        mat = _cards(_block(starter, "/MAT/LAW79/110"))
        self.assertEqual(_col_f(mat[3], 21, 40), 0.0)
        self.assertEqual(_warns(res, "ERROR 910"), [])

    def test_phel_zero_is_derived_the_way_LS_DYNA_derives_it(self):
        # A blank/0 PHEL is a DOCUMENTED LS-DYNA input mode, not a malformed
        # card: Vol II R16 p.2-763/764 -- "Given HEL and G, mu_hel can be found
        # iteratively from HEL = k1*mu + k2*mu^2 + k3*mu^3 + (4/3)*g*mu/(1+mu)"
        # and "These are calculated automatically by LS-DYNA if p_hel is zero
        # on input."  Radioss has no such derivation (hm_read_mat79.F:211 just
        # divides), so the converter has to reproduce it or the emitted deck
        # runs with T* = T/0 and P* = P/0 while the starter reports 0 ERROR /
        # 0 WARNING.
        #
        # Hand-solved for THIS card (K1 = 130.95e9, G = 90.16e9, K2 = K3 = 0,
        # HEL = 19e9), independently of the implementation:
        #   f(mu) = 130.95e9*mu + (4/3)*90.16e9*mu/(1+mu) - 19e9 = 0
        # Newton from mu = 0.08 converges to mu_hel = 0.07837428750607,
        # whence PHEL = K1*mu = 1.0263112948920e10 and
        # sigma_HEL = 1.5*(19e9 - PHEL) = 1.3105330576620e10.
        k1, g, hel = 130.95e9, 90.16e9, 19.0e9
        mu = 0.08
        for _ in range(60):
            f = k1 * mu + (4.0 / 3.0) * g * mu / (1.0 + mu) - hel
            df = k1 + (4.0 / 3.0) * g / (1.0 + mu) ** 2
            mu -= f / df
        phel = k1 * mu
        self.assertAlmostEqual(mu, 0.07837428750607, places=12)
        self.assertAlmostEqual(phel, 1.0263112948920e10, delta=1.0)

        c2 = (1.0, "0.2E9", 0.8, "19E9", 0.0, 1.0)
        res, starter = _convert(
            MESH(110) + _mat110(c2=c2, fs=0.0) + "*END\n")
        mat = _cards(_block(starter, "/MAT/LAW79/110"))
        # The 20-char field carries 10 significant digits, so compare
        # RELATIVELY -- the emitted 1.026311295E+10 is the hand value rounded.
        self.assertAlmostEqual(_col_f(mat[4], 41, 60) / phel, 1.0, places=9)
        self.assertNotEqual(_col_f(mat[4], 41, 60), 0.0)
        # T and HEL are still the physical card values -- the derivation
        # touches PHEL and nothing else.
        self.assertEqual(_col_f(mat[4], 1, 20), 0.2e9)
        self.assertEqual(_col_f(mat[4], 21, 40), 19.0e9)
        hits = _warns(res, "calculated automatically by LS-DYNA")
        self.assertEqual(len(hits), 1)
        self.assertIn("p.2-764", hits[0])
        self.assertIn("DERIVED PHEL", hits[0])
        # The derived PHEL can never exceed HEL (PHEL = HEL - (4/3)G*mu/(1+mu)
        # and G > 0), so it cannot manufacture an ERROR 907.
        self.assertLess(_col_f(mat[4], 41, 60), _col_f(mat[4], 21, 40))
        self.assertEqual(_warns(res, "rejects this with ERROR 907"), [])

    def test_phel_zero_that_cannot_be_derived_still_warns(self):
        # The derivation needs HEL > 0, K1 > 0 and G > 0. With HEL = 0 there is
        # nothing to solve, so the original hard warning has to stand.
        c2 = (1.0, "0.2E9", 0.8, 0.0, 0.0, 1.0)
        res, starter = _convert(MESH(110) + _mat110(c2=c2) + "*END\n")
        mat = _cards(_block(starter, "/MAT/LAW79/110"))
        self.assertEqual(_col_f(mat[4], 41, 60), 0.0)
        hits = _warns(res, "PHEL=0 <= 0")
        self.assertEqual(len(hits), 1)
        self.assertIn("NO error and NO warning", hits[0])
        self.assertIn("PRESSURE NORMALIZER", hits[0])
        self.assertEqual(_warns(res, "calculated automatically by LS-DYNA"), [])

    def test_a_supplied_phel_is_never_touched(self):
        # The derivation is gated on PHEL <= 0 only: a card that states PHEL
        # keeps it verbatim and draws no derivation warning.
        res, starter = _convert(MESH(110) + _mat110() + "*END\n")
        mat = _cards(_block(starter, "/MAT/LAW79/110"))
        self.assertEqual(_col_f(mat[4], 41, 60), 1.46e9)
        self.assertEqual(_warns(res, "calculated automatically by LS-DYNA"), [])

    def test_phel_greater_than_hel_warns_error_907(self):
        c2 = (1.0, "0.2E9", 0.8, "1.46E9", "19E9", 1.0)     # HEL/PHEL swapped
        res, _ = _convert(MESH(110) + _mat110(c2=c2) + "*END\n")
        hits = _warns(res, "ERROR 907")
        self.assertEqual(len(hits), 1)
        self.assertIn("sigma_HEL = 1.5*(HEL-PHEL) would come out NEGATIVE",
                      hits[0].replace("\n", " "))

    def test_zero_shear_modulus_warns_error_908(self):
        c1 = (110, 3700.0, 0.0, 0.93, 0.31, 0.007, 0.6, 0.64)
        res, _ = _convert(MESH(110) + _mat110(c1=c1) + "*END\n")
        self.assertEqual(len(_warns(res, "ERROR 908")), 1)

    def test_zero_k1_warns_error_909(self):
        res, _ = _convert(MESH(110)
                          + _mat110(c3=(0.005, 1.0, 0.0, 0.0, 0.0))
                          + "*END\n")
        self.assertEqual(len(_warns(res, "ERROR 909")), 1)

    def test_beta_outside_0_1_warns_error_911(self):
        for beta in (-0.1, 1.5):
            with self.subTest(beta=beta):
                c2 = (1.0, "0.2E9", 0.8, "19E9", "1.46E9", beta)
                res, _ = _convert(MESH(110) + _mat110(c2=c2) + "*END\n")
                self.assertEqual(len(_warns(res, "ERROR 911")), 1)

    def test_valid_card_is_warning_free(self):
        res, _ = _convert(MESH(110) + _mat110(fs=0.0) + "*END\n")
        self.assertEqual(
            [w for w in res.warnings
             if "JOHNSON_HOLMQUIST_CERAMICS" in w], [])


class TestMat110Blanks(unittest.TestCase):
    """mat_110.cfg declares no DEFAULTS block, so blanks are real zeros on both
    sides and the starter's own substitutions take over."""

    def setUp(self):
        c2 = (1.0, "", "", "19E9", "1.46E9", "")     # T, SFMAX, BETA blank
        c3 = (0.005, "", "130.95E9", "", "")         # D2, K2, K3 blank
        self.res, starter = _convert(
            MESH(110) + _mat110(c2=c2, c3=c3, fs=0.0) + "*END\n")
        self.mat = _cards(_block(starter, "/MAT/LAW79/110"))

    def test_blank_fields_become_explicit_zeros(self):
        self.assertEqual(_col_f(self.mat[3], 41, 60), 0.0)   # SFMAX -> INFINITY
        self.assertEqual(_col_f(self.mat[4], 1, 20), 0.0)    # T
        self.assertEqual(_col_f(self.mat[5], 21, 40), 0.0)   # D2 -> EPFAIL = D1
        self.assertEqual(_col_f(self.mat[6], 21, 40), 0.0)   # K2
        self.assertEqual(_col_f(self.mat[6], 41, 60), 0.0)   # K3
        self.assertEqual(_col_f(self.mat[6], 61, 80), 0.0)   # BETA (no bulking)

    def test_blank_beta_zero_still_passes_the_0_1_check(self):
        self.assertEqual(_warns(self.res, "ERROR 911"), [])


# ─────────────────────────────────────────────────────────────────────────────
# B) *MAT_JOHNSON_HOLMQUIST_CONCRETE (111) -> /MAT/LAW126
# ─────────────────────────────────────────────────────────────────────────────

class TestLaw126Card(unittest.TestCase):
    """Column-exact /MAT/LAW126, FORMAT(radioss2024) -- the oldest block that
    exists for this law, which a /BEGIN 2022 deck falls forward into."""

    def setUp(self):
        self.res, self.starter = _convert(DECK_111)
        self.blk = _block(self.starter, "/MAT/LAW126/111")
        self.mat = _cards(self.blk)

    def test_header_and_card_count(self):
        self.assertEqual(self.blk[0], "/MAT/LAW126/111")
        self.assertEqual(len(self.mat), 7)

    def test_card1_density_takes_EXACTLY_one_field(self):
        # Unlike LAW79 there is no CARD_PREREAD and no Refer_Rho attribute: a
        # second field on this card raises WARNING 100213.
        self.assertEqual(_col_f(self.mat[0], 1, 20), 2440.0)
        self.assertEqual(len(self.mat[0]), 20)

    def test_card2_shear_modulus(self):
        self.assertEqual(_col_f(self.mat[1], 1, 20), 14.86e9)

    def test_card3_A_B_N_FC_T(self):
        # *MAT_111 card 1 is NOT the *MAT_110 layout: field 7 is N and field 8
        # is FC, where 110 has M then N. There is no M on this card at all.
        self.assertEqual(_col_f(self.mat[2], 1, 20), 0.79)      # A
        self.assertEqual(_col_f(self.mat[2], 21, 40), 1.6)      # B
        self.assertEqual(_col_f(self.mat[2], 41, 60), 0.61)     # N  <- fld 7
        self.assertEqual(_col_f(self.mat[2], 61, 80), 48e6)     # FC <- fld 8
        self.assertEqual(_col_f(self.mat[2], 81, 100), 4e6)     # T  <- card2 f1
        self.assertEqual(len(self.mat[2]), 100)

    def test_card4_C_EPS0_FCUT_SFMAX_EFMIN(self):
        self.assertEqual(_col_f(self.mat[3], 1, 20), 0.007)     # C
        self.assertEqual(_col_f(self.mat[3], 21, 40), 1.0)      # EPS0
        self.assertEqual(_col_f(self.mat[3], 41, 60), 0.0)      # FCUT: no filter
        self.assertEqual(_col_f(self.mat[3], 61, 80), 7.0)      # SFMAX
        self.assertEqual(_col_f(self.mat[3], 81, 100), 0.01)    # EFMIN
        self.assertEqual(len(self.mat[3]), 100)

    def test_card5_PC_MUC_PL_MUL_renaming(self):
        # LS-DYNA UC/UL are Radioss MUC/MUL -- same quantity, different name.
        self.assertEqual(_col_f(self.mat[4], 1, 20), 16e6)      # PC
        self.assertEqual(_col_f(self.mat[4], 21, 40), 1e-3)     # MUC <- UC
        self.assertEqual(_col_f(self.mat[4], 41, 60), 800e6)    # PL
        self.assertEqual(_col_f(self.mat[4], 61, 80), 0.10)     # MUL <- UL
        self.assertEqual(len(self.mat[4]), 80)

    def test_card6_K1_K2_K3_on_their_OWN_card(self):
        # LAW126 groups K1/K2/K3 on card 6 and D1/D2 on card 7; the LS-DYNA
        # card 3 interleaves them (D1 D2 K1 K2 K3 FS).
        self.assertEqual(_col_f(self.mat[5], 1, 20), 85e9)
        self.assertEqual(_col_f(self.mat[5], 21, 40), -171e9)
        self.assertEqual(_col_f(self.mat[5], 41, 60), 208e9)
        self.assertEqual(len(self.mat[5]), 60)

    def test_card7_D1_D2_blank_IDEL_EPSMAX_column_placement(self):
        # CARD("%20lg%20lg%10s%10d%20lg", D1, D2, _BLANK_, IDEL, EPSMAX):
        # IDEL is a 10-char INTEGER at cols 51-60 after a 10-char blank run.
        self.assertEqual(_col_f(self.mat[6], 1, 20), 0.04)
        self.assertEqual(_col_f(self.mat[6], 21, 40), 1.0)
        self.assertEqual(self.mat[6][40:50], " " * 10)          # literal blanks
        self.assertEqual(_col_i(self.mat[6], 51, 60), 2)        # IDEL <- FS>0
        self.assertEqual(_col_f(self.mat[6], 61, 80), 0.30)     # EPS_MAX = FS
        # IFAILSO (cols 91-100) is a radioss2025 field and CT/POWT/CC/POWC a
        # radioss2026 card -- neither is emitted at /BEGIN 2022.
        self.assertEqual(len(self.mat[6]), 80)

    def test_no_EOS_is_emitted(self):
        # K1/K2/K3 are uparam(14..16) of LAW126 itself; the INIT_MAT_KEYWORD
        # "HYDRO_EOS" tag is a pressure-treatment capability, not a request
        # for a companion /EOS block.
        self.assertNotIn("/EOS/", self.starter)

    def test_version_gate_is_reported_once(self):
        hits = _warns(self.res, "WARNING 100211")
        self.assertEqual(len(hits), 1)
        self.assertIn("radioss2024", hits[0])
        self.assertIn("No action needed", hits[0])
        self.assertIn("IFAILSO", hits[0])


class TestLaw126NoNormalization(unittest.TestCase):
    def setUp(self):
        self.res, starter = _convert(DECK_111)
        self.mat = _cards(_block(starter, "/MAT/LAW126/111"))
        self.fields = [_col_f(ln, a, a + 19)
                       for ln in self.mat
                       for a in range(1, len(ln), 20)
                       if ln[a - 1:a + 19].strip()]

    def test_T_is_not_pre_divided_by_FC(self):
        # sigeps126.F90:338  epfail = d1*(pstar + t0/fc)**d2 -- the engine
        # forms T* itself, exactly as LS-DYNA does.
        t_star = 4e6 / 48e6
        self.assertAlmostEqual(t_star, 1.0 / 12.0, places=12)
        self.assertEqual(_col_f(self.mat[2], 81, 100), 4e6)
        for v in self.fields:
            self.assertNotAlmostEqual(v, t_star, places=6)

    def test_FC_is_written_as_a_physical_stress(self):
        # :264 pstar = pnew/fc, :305 sigstar = vm/fc, :383 sigy = fc*sigy.
        self.assertEqual(_col_f(self.mat[2], 61, 80), 48e6)

    def test_region1_bulk_modulus_matches_the_starter_echo(self):
        # hm_read_mat126.F90:140  k0 = pc/muc
        pc = _col_f(self.mat[4], 1, 20)
        muc = _col_f(self.mat[4], 21, 40)
        self.assertEqual(pc / muc, 16e9)

    def test_region2_tangent_bulk_modulus_is_finite(self):
        # :146  h = (pl - pc)/mul
        pc = _col_f(self.mat[4], 1, 20)
        pl = _col_f(self.mat[4], 41, 60)
        mul = _col_f(self.mat[4], 61, 80)
        self.assertAlmostEqual((pl - pc) / mul, 7.84e9, delta=1.0)


class TestMat111FSMapping(unittest.TestCase):
    """FS -> IDEL/EPS_MAX. Unlike MAT_110 this DOES work at /BEGIN 2022, and
    the three-way rule is NOT the one MAT_110 would use."""

    def _idel_epsmax(self, fs):
        _, starter = _convert(MESH(111) + _mat111(fs=fs) + "*END\n")
        card = _cards(_block(starter, "/MAT/LAW126/111"))[6]
        return _col_i(card, 51, 60), _col_f(card, 61, 80)

    def test_fs_positive_is_idel2_plastic_strain(self):
        self.assertEqual(self._idel_epsmax(0.30), (2, 0.30))

    def test_fs_zero_is_idel1_tensile_the_LSDYNA_DEFAULT(self):
        # LS-DYNA MAT_111 FS = 0 means "fail if P* + T* <= 0" -- a real
        # criterion, not "no failure" as on MAT_110. LAW126's own default IDEL
        # would be 0 (no deletion), so writing 1 explicitly is REQUIRED.
        self.assertEqual(self._idel_epsmax(0.0), (1, 0.0))

    def test_fs_negative_is_idel3_sigy_exhausted(self):
        # LAW126 IDEL 3 = "failure if SIGY <= 0" matches LS-DYNA's "damage
        # strength < 0". EPS_MAX carries the negative FS verbatim, exactly as
        # dyna2rad does (CM:5654); IDEL=3 never reads it, so it is inert.
        self.assertEqual(self._idel_epsmax(-0.30), (3, -0.30))

    def test_the_idel_codes_differ_from_what_MAT_110_would_use(self):
        # Guard against transplanting one law's rule onto the other: MAT_110's
        # FS<0 is "p*+t*<0" -> LAW79 IDEL 1, while MAT_111's FS<0 is "damage
        # strength < 0" -> LAW126 IDEL 3; MAT_110's FS=0 is "no failure" ->
        # IDEL 0, while MAT_111's FS=0 is tensile -> IDEL 1.
        self.assertEqual(self._idel_epsmax(-1.0)[0], 3)
        self.assertEqual(self._idel_epsmax(0.0)[0], 1)


class TestMat111Guards(unittest.TestCase):
    def test_uc_zero_warns_about_the_silent_NaN(self):
        c2 = ("4E6", 1.0, 0.01, 7.0, "16E6", 0.0, "800E6", 0.10)
        res, _ = _convert(MESH(111) + _mat111(c2=c2) + "*END\n")
        hits = _warns(res, "UC=0")
        self.assertEqual(len(hits), 1)
        self.assertIn("k0 = PC/MUC (:140)", hits[0])
        self.assertIn("SILENT NaN", hits[0])
        self.assertIn("0 ERROR / 0 WARNING", hits[0])

    def test_ul_zero_warns(self):
        c2 = ("4E6", 1.0, 0.01, 7.0, "16E6", "1E-3", "800E6", 0.0)
        res, _ = _convert(MESH(111) + _mat111(c2=c2) + "*END\n")
        hits = _warns(res, "UL=0")
        self.assertEqual(len(hits), 1)
        self.assertIn("h = (PL-PC)/MUL (:146)", hits[0])

    def test_eps0_zero_with_rate_term_is_substituted_with_1(self):
        # LAW126 has NO ANCMSG check at all, so unlike LAW79 this does not
        # hard-fail -- it divides by zero in the engine instead.
        c2 = ("4E6", 0.0, 0.01, 7.0, "16E6", "1E-3", "800E6", 0.10)
        res, starter = _convert(MESH(111) + _mat111(c2=c2) + "*END\n")
        mat = _cards(_block(starter, "/MAT/LAW126/111"))
        self.assertEqual(_col_f(mat[3], 21, 40), 1.0)
        hits = _warns(res, "C*log(eps_dot/0)")
        self.assertEqual(len(hits), 1)

    def test_zero_G_K1_FC_each_warn_that_the_starter_checks_nothing(self):
        cases = (
            ((111, 2440.0, 0.0, 0.79, 1.6, 0.007, 0.61, "48E6"), "G=0 <= 0"),
            ((111, 2440.0, "14.86E9", 0.79, 1.6, 0.007, 0.61, 0.0), "FC=0 <= 0"),
        )
        for c1, needle in cases:
            with self.subTest(needle=needle):
                res, _ = _convert(MESH(111) + _mat111(c1=c1) + "*END\n")
                self.assertEqual(len(_warns(res, needle)), 1)
        res, _ = _convert(MESH(111)
                          + _mat111(c3=(0.04, 1.0, 0.0, "-171E9", "208E9"))
                          + "*END\n")
        self.assertEqual(len(_warns(res, "K1=0 <= 0")), 1)

    def test_negative_derived_poisson_is_warned(self):
        # A too-soft PC/UC pair against G drives nu = (3k0-2G)/(6k0+2G) < 0,
        # which hm_read_mat126.F90 prints without complaint. k0 = 1e6/1e-3
        # = 1e9 against G = 14.86e9 gives nu = (3e9-29.72e9)/(6e9+29.72e9)
        # = -26.72/35.72 = -0.748.
        c2 = ("4E6", 1.0, 0.01, 7.0, "1E6", "1E-3", "800E6", 0.10)
        res, _ = _convert(MESH(111) + _mat111(c2=c2) + "*END\n")
        hits = _warns(res, "outside [0, 0.5)")
        self.assertEqual(len(hits), 1)
        k0, g = 1e6 / 1e-3, 14.86e9
        nu = (3.0 * k0 - 2.0 * g) / (6.0 * k0 + 2.0 * g)
        self.assertAlmostEqual(nu, -0.7480403135, places=9)
        self.assertIn(f"{nu:g}", hits[0])

    def test_valid_card_warns_only_the_cosmetic_version_gate(self):
        res, _ = _convert(DECK_111)
        hits = [w for w in res.warnings if "JOHNSON_HOLMQUIST_CONCRETE" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("WARNING 100211", hits[0])


class TestEps0UnitDependence(unittest.TestCase):
    """EPS0 is a 1/TIME quantity and k2rad rescales nothing, so the value
    substituted for an unusable EPS0 has to be expressed in the DECK's time
    unit. Vol II R16 *MAT_015 -- which both *MAT_110 and *MAT_111 point at for
    this field -- states it outright: "input in units of [time]^-1 ... if the
    system of units for the model input is {kg, mm, ms}, then EPS0 should be
    set to 10^-5".  A bare 1.0 on a ton-mm-ms deck is 1000 s^-1, and both
    engines CLAMP the rate factor to 1 below EPS0 (sigeps79.F:178-182,
    sigeps126.F90:279), so it would switch rate hardening off rather than
    shift its onset."""

    def _eps0(self, deck, units, header, col=(21, 40), card=3):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck)
        res = convert(path, write_log=False, units=units)
        with open(res.starter_path) as fh:
            starter = fh.read()
        tmp.cleanup()
        got = _col_f(_cards(_block(starter, header))[card], *col)
        return res, got

    # EPS0 = 0 with C != 0 on both laws.
    DECK_110 = (MESH(110)
                + _mat110(c2=(0.0, "0.2E9", 0.8, "19E9", "1.46E9", 1.0))
                + "*END\n")
    DECK_111 = (MESH(111)
                + _mat111(c2=("4E6", 0.0, 0.01, 7.0, "16E6", "1E-3",
                              "800E6", 0.10))
                + "*END\n")

    def test_seconds_deck_is_unchanged(self):
        for deck, header in ((self.DECK_110, "/MAT/LAW79/110"),
                             (self.DECK_111, "/MAT/LAW126/111")):
            with self.subTest(header=header):
                _, got = self._eps0(deck, ("Mg", "mm", "s"), header)
                self.assertEqual(got, 1.0)

    def test_millisecond_deck_gets_1_per_second_expressed_in_ms(self):
        # 1 s^-1 = 1e-3 ms^-1. The raw 1.0 would be 1000 s^-1.
        for deck, header in ((self.DECK_110, "/MAT/LAW79/110"),
                             (self.DECK_111, "/MAT/LAW126/111")):
            with self.subTest(header=header):
                res, got = self._eps0(deck, ("Mg", "mm", "ms"), header)
                self.assertEqual(got, 1.0e-3)
                self.assertNotEqual(got, 1.0)
                self.assertIn("per the deck's time unit 'ms' (= 1 s^-1)",
                              "\n".join(res.warnings))

    def test_microsecond_deck_scales_too(self):
        for label in ("mus", "us"):
            with self.subTest(label=label):
                _, got = self._eps0(self.DECK_110, ("g", "cm", label),
                                    "/MAT/LAW79/110")
                self.assertEqual(got, 1.0e-6)

    def test_an_unparseable_time_label_falls_back_to_the_raw_default(self):
        # The starter itself rejects a label of more than three characters
        # (unit_code.F:99-143 -> ERROR 573), so guessing would be worse than
        # keeping the starter's own EPS0 = 1 substitution.
        _, got = self._eps0(self.DECK_110, ("g", "cm", "micros"),
                            "/MAT/LAW79/110")
        self.assertEqual(got, 1.0)

    def test_the_time_unit_parser_mirrors_the_starter(self):
        from k2rad.writer.materials import _time_unit_in_seconds
        for label, want in (("s", 1.0), ("ms", 1.0e-3), ("us", 1.0e-6),
                            ("mus", 1.0e-6), ("ns", 1.0e-9), ("ks", 1.0e3),
                            (" s ", 1.0),
                            # rejected by unit_code.F for the same reasons
                            ("micros", None), ("sec", None), ("m", None),
                            ("", None), ("qs", None)):
            with self.subTest(label=label):
                self.assertEqual(_time_unit_in_seconds(label), want)

    def test_a_supplied_EPS0_is_never_rescaled(self):
        # Only the SUBSTITUTION is unit-aware; a stated EPS0 is a deck value
        # and passes through verbatim on every unit system, like every other
        # number in this converter.
        for units in (("Mg", "mm", "s"), ("Mg", "mm", "ms")):
            with self.subTest(units=units):
                _, got = self._eps0(DECK_110, units, "/MAT/LAW79/110")
                self.assertEqual(got, 1.0)     # MAT110_C2's EPS0 = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# C) *MAT_ELASTIC_FLUID (001 + FLUID) -> /MAT/LAW6 + /EOS/POLYNOMIAL
# ─────────────────────────────────────────────────────────────────────────────

class TestLaw6FluidCard(unittest.TestCase):
    def setUp(self):
        self.res, self.starter = _convert(DECK_FLUID)
        self.blk = _block(self.starter, "/MAT/HYD_VISC/3")
        self.mat = _cards(self.blk)
        self.eos = _cards(_block(self.starter, "/EOS/POLYNOMIAL/3"))

    def test_law6_header_and_two_cards(self):
        # The modern 2-card form, NOT the legacy embedded-EOS form (which is
        # gated on the trailing free-card COUNT, hm_read_mat06.F:105,113-116,
        # and binds Pmin twice with the LATER value winning).
        self.assertEqual(self.blk[0], "/MAT/HYD_VISC/3")
        self.assertEqual(_col_f(self.mat[0], 1, 20), 2600.0)
        # The /MAT and its same-id /EOS share ONE HDR terminator (the
        # _emit_mat_law6_carrier convention: LAW6 writes no HDR of its own
        # because an /EOS block always follows), so the LAW6 payload is
        # exactly the first two data lines and the /EOS header comes next.
        self.assertEqual(self.mat[2], "/EOS/POLYNOMIAL/3")
        self.assertEqual(self.blk.index("/EOS/POLYNOMIAL/3"), 6)

    def test_law6_card2_Nu_and_Pmin(self):
        self.assertEqual(_col_f(self.mat[1], 1, 20), 0.0)      # Nu  <- VC = 0
        self.assertEqual(_col_f(self.mat[1], 21, 40), 0.0)     # Pmin <- CP dflt
        self.assertEqual(len(self.mat[1]), 40)

    def test_eos_binds_by_MATERIAL_id(self):
        # Radioss binds an /EOS to the material of the SAME id -- there is no
        # pointer field, so the block id IS the binding.
        self.assertEqual(len(_blocks(self.starter, "/EOS/POLYNOMIAL/3")), 1)
        self.assertEqual(len(_blocks(self.starter, "/MAT/HYD_VISC/3")), 1)

    def test_eos_is_the_pure_linear_form_C1_equals_K(self):
        # P = C0 + C1*mu with C0 = C2 = C3 = C4 = C5 = E0 = Psh = 0.
        self.assertEqual(_col_f(self.eos[0], 1, 20), 0.0)      # C0
        self.assertEqual(_col_f(self.eos[0], 21, 40), 2.2e9)   # C1 <- K
        self.assertEqual(_col_f(self.eos[0], 41, 60), 0.0)     # C2
        self.assertEqual(_col_f(self.eos[0], 61, 80), 0.0)     # C3
        for a, b in ((1, 20), (21, 40), (41, 60), (61, 80), (81, 100)):
            self.assertEqual(_col_f(self.eos[1], a, b), 0.0)   # C4 C5 E0 Psh r0

    def test_the_EOS_is_never_omitted(self):
        # A LAW6 with no /EOS passes the starter with 0 errors and 0 warnings
        # but leaves PM(32) = C1 = 0: zero bulk modulus, zero sound speed.
        self.assertIn("/EOS/POLYNOMIAL/3", self.starter)

    def test_E_and_PR_never_reach_the_card(self):
        # LAW6 has no shear-modulus slot at all, so LS-DYNA's "under FLUID the
        # shear modulus is set to zero" is exact rather than approximated --
        # and E/PR, which LS-DYNA itself ignores here, must not be smuggled
        # into any field. K is given, so they are not even used as a fallback.
        _, starter = _convert(MESH(3) + _fluid(e="8.5E8", pr=0.24) + "*END\n")
        # The LAW6 payload is exactly the first two data lines of the shared
        # block (the /EOS header + title + cards follow it).
        fields = [_col_f(ln, a, a + 19)
                  for ln in _cards(_block(starter, "/MAT/HYD_VISC/3"))[:2]
                  for a in range(1, len(ln), 20)]
        self.assertNotIn(8.5e8, fields)
        self.assertNotIn(0.24, fields)
        # ... and the bulk modulus is K, not the E/PR-derived value
        # 8.5e8/(3*(1-0.48)) = 544871794.87...
        eos = _cards(_block(starter, "/EOS/POLYNOMIAL/3"))
        self.assertEqual(_col_f(eos[0], 21, 40), 2.2e9)
        self.assertNotAlmostEqual(_col_f(eos[0], 21, 40),
                                  8.5e8 / (3.0 * (1.0 - 0.48)), delta=1.0)

    def test_clean_card_warns_only_about_the_dropped_E_and_PR(self):
        res, _ = _convert(MESH(3) + _fluid(e="8.5E8", pr=0.24) + "*END\n")
        hits = [w for w in res.warnings if "MAT_ELASTIC_FLUID" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("are DROPPED", hits[0])
        self.assertIn("Remark 5", hits[0])


class TestFluidBulkModulus(unittest.TestCase):
    def _c1(self, **kw):
        _, starter = _convert(MESH(3) + _fluid(**kw) + "*END\n")
        return _col_f(_cards(_block(starter, "/EOS/POLYNOMIAL/3"))[0], 21, 40)

    def test_K_positive_is_copied_verbatim(self):
        self.assertEqual(self._c1(k="2.2E9"), 2.2e9)

    def test_K_zero_derives_from_E_and_the_REAL_poisson_ratio(self):
        # The manual's own relation, Vol II R16 p.2-148 Remark 5:
        #   K = E/(3(1-2nu)) = 3e9/(3*(1-0.5)) = 3e9/1.5 = 2.0e9
        # dyna2rad computes E/3 = 1.0e9 because its expression spells the
        # token 'NU' while the attribute is 'Nu' and lookup is case-sensitive,
        # so the token resolves to nothing and silently becomes 0.
        got = self._c1(mid=3, rho=1200.0, e="3.0E9", pr=0.25, k=0.0)
        self.assertEqual(got, 2.0e9)
        self.assertNotAlmostEqual(got, 3.0e9 / 3.0, delta=1.0)

    def test_K_zero_warns_and_names_the_dyna2rad_defect(self):
        res, _ = _convert(MESH(3)
                          + _fluid(rho=1200.0, e="3.0E9", pr=0.25, k=0.0)
                          + "*END\n")
        hits = _warns(res, "K = E/(3(1-2*PR))")
        self.assertEqual(len(hits), 1)
        self.assertIn("case-sensitive", hits[0])
        self.assertIn("loses Poisson's ratio", hits[0])

    def test_K_negative_falls_back_instead_of_leaving_zero(self):
        # dyna2rad matches NEITHER of its branches for K < 0 and leaves B = 0:
        # a fluid with zero sound speed, silently.
        got = self._c1(rho=1200.0, e="3.0E9", pr=0.25, k="-2.2E9")
        self.assertEqual(got, 2.0e9)
        res, _ = _convert(MESH(3)
                          + _fluid(rho=1200.0, e="3.0E9", pr=0.25, k="-2.2E9")
                          + "*END\n")
        self.assertEqual(len(_warns(res, "is NEGATIVE")), 1)

    def test_incompressible_poisson_cannot_be_used_and_is_warned(self):
        res, starter = _convert(MESH(3)
                                + _fluid(e="3.0E9", pr=0.5, k=0.0) + "*END\n")
        c1 = _col_f(_cards(_block(starter, "/EOS/POLYNOMIAL/3"))[0], 21, 40)
        self.assertEqual(c1, 0.0)
        self.assertEqual(len(_warns(res, "PR=0.5 >= 0.5")), 1)
        self.assertEqual(len(_warns(res, "ZERO bulk modulus")), 1)

    def test_the_singular_fallback_is_never_quoted_as_a_value(self):
        # At PR >= 0.5 the expression K = E/(3(1-2*PR)) is singular or
        # negative, so `derived` stays at its 0.0 SENTINEL -- printing
        # "K = E/(3(1-2*PR)) = 0" would state a value the formula does not
        # have. Exactly ONE warning covers the case, and it says so.
        for pr in (0.5, 0.6):
            with self.subTest(pr=pr):
                res, _ = _convert(MESH(3)
                                  + _fluid(e="3.0E9", pr=pr, k=0.0) + "*END\n")
                hits = _warns(res, "MAT_ELASTIC_FLUID mid=3: K=")
                self.assertEqual(len(hits), 1)
                self.assertIn("is infinite or negative and cannot be used",
                              hits[0])
                self.assertNotIn("K = E/(3(1-2*PR)) = 0", hits[0])
                self.assertEqual(_warns(res, "the bulk modulus is derived"), [])

    def test_a_negative_K_at_incompressible_PR_reports_the_same_way(self):
        res, starter = _convert(
            MESH(3) + _fluid(e="3.0E9", pr=0.5, k="-2.2E9") + "*END\n")
        c1 = _col_f(_cards(_block(starter, "/EOS/POLYNOMIAL/3"))[0], 21, 40)
        self.assertEqual(c1, 0.0)
        hits = _warns(res, "MAT_ELASTIC_FLUID mid=3: K=-2.2e+09")
        self.assertEqual(len(hits), 1)
        self.assertIn("is infinite or negative and cannot be used", hits[0])
        self.assertNotIn("= 0 from card 1 fields 3 and 4", hits[0])

    def test_all_zero_card_warns_about_the_inert_fluid(self):
        res, _ = _convert(MESH(3) + _fluid(e=0.0, pr=0.0, k=0.0) + "*END\n")
        self.assertEqual(len(_warns(res, "the fluid would be completely inert")),
                         1)


class TestFluidViscosity(unittest.TestCase):
    def test_VC_zero_needs_no_warning(self):
        res, starter = _convert(DECK_FLUID)
        self.assertEqual(_warns(res, "VC="), [])
        mat = _cards(_block(starter, "/MAT/HYD_VISC/3"))
        self.assertEqual(_col_f(mat[1], 1, 20), 0.0)

    def test_VC_nonzero_is_dropped_not_copied_into_the_wrong_slot(self):
        # LS-DYNA VC is DIMENSIONLESS (it scales S'ij = VC*dL*a*rho*edot'ij);
        # Radioss Nu is a kinematic viscosity in L^2/T. dyna2rad copies the
        # number verbatim, wrong by the factor dL*a.
        res, starter = _convert(MESH(3)
                                + _fluid(card2=(0.1, "1.0E20")) + "*END\n")
        mat = _cards(_block(starter, "/MAT/HYD_VISC/3"))
        self.assertEqual(_col_f(mat[1], 1, 20), 0.0)
        self.assertNotAlmostEqual(_col_f(mat[1], 1, 20), 0.1)
        self.assertEqual(len(_warns(res, "VC=0.1 is DROPPED")), 1)

    def test_the_warning_carries_a_usable_hand_conversion_recipe(self):
        # a = sqrt(K/rho) = sqrt(2.2e9/2600) = sqrt(846153.846...) = 919.865...
        # so nu ~= VC*dL*a = 0.1*dL*919.865 = 91.9865*dL.
        res, _ = _convert(MESH(3) + _fluid(card2=(0.1, "1.0E20")) + "*END\n")
        hit = _warns(res, "VC=0.1 is DROPPED")[0]
        sound = (2.2e9 / 2600.0) ** 0.5
        self.assertAlmostEqual(sound, 919.8662, places=3)
        self.assertIn(f"{0.1 * sound:g}*dL", hit)


class TestFluidCavitation(unittest.TestCase):
    def _pmin(self, card2):
        _, starter = _convert(MESH(3) + _fluid(card2=card2) + "*END\n")
        return _col_f(_cards(_block(starter, "/MAT/HYD_VISC/3"))[1], 21, 40)

    def test_default_CP_1e20_means_NO_cutoff_not_minus_1e20(self):
        # LS-DYNA's CP default is 1e20 = "no cavitation limit". Radioss reads
        # Pmin = 0 as "no cut-off" (hm_read_mat06.F:154 -> -INFINITY), so the
        # defaulted card must map to 0. dyna2rad lands on -1e20 instead.
        got = self._pmin((0.0, "1.0E20"))
        self.assertEqual(got, 0.0)
        self.assertNotAlmostEqual(got, -1.0e20, delta=1.0)

    def test_absent_card2_means_NO_cutoff(self):
        _, starter = _convert(MESH(3) + _fluid(card2=None) + "*END\n")
        mat = _cards(_block(starter, "/MAT/HYD_VISC/3"))
        self.assertEqual(_col_f(mat[1], 21, 40), 0.0)

    def test_blank_CP_cell_means_NO_cutoff(self):
        self.assertEqual(self._pmin((0.1, "")), 0.0)

    def test_finite_CP_becomes_a_negative_cutoff(self):
        for cp, want in (("1.0E6", -1.0e6), ("5.0E6", -5.0e6),
                         ("2.0E6", -2.0e6)):
            with self.subTest(cp=cp):
                self.assertEqual(self._pmin((0.0, cp)), want)

    def test_explicit_zero_CP_is_inexpressible_and_warned(self):
        # An explicit CP = 0.0 means "cavitate at p = 0", but Pmin = 0 is the
        # reader's sentinel for NO cut-off -- the one semantic the Radioss
        # card cannot state. dyna2rad has the same loss, silently.
        res, _ = _convert(MESH(3) + _fluid(card2=(0.0, 0.0)) + "*END\n")
        self.assertEqual(self._pmin((0.0, 0.0)), 0.0)
        hits = _warns(res, "CP=0.0 is written explicitly")
        self.assertEqual(len(hits), 1)
        self.assertIn("NOT EXPRESSIBLE", hits[0])

    def test_negative_CP_is_sign_corrected_and_warned(self):
        self.assertEqual(self._pmin((0.0, "-1.0E6")), -1.0e6)
        res, _ = _convert(MESH(3) + _fluid(card2=(0.0, "-1.0E6")) + "*END\n")
        self.assertEqual(len(_warns(res, "is negative. LS-DYNA's cavitation")),
                         1)

    def test_a_UNIT_RESCALED_default_CP_is_still_the_default(self):
        # The 1e20 literal is a RAW number, so testing it alone makes the
        # emitted card depend on the deck's units. The corpus proves it on one
        # material: W11_SETUP_SPH_BirdStrike_Multi's "Head" fluid writes
        # K = 2.2e9 / CP = 1.00000E20 in its kg-m-s copy and K = 2200 /
        # CP = 1E+14 in the kunit-converted ton-mm-s copy -- the same 1e20 Pa.
        # Both must emit the same card.
        si = self._pmin((0.0, "1.00000E20"))
        _, starter = _convert(
            MESH(3) + _fluid(rho="2.6E-9", k=2200.0, card2=(0.0, "1E+14"))
            + "*END\n")
        mm = _col_f(_cards(_block(starter, "/MAT/HYD_VISC/3"))[1], 21, 40)
        self.assertEqual(si, 0.0)
        self.assertEqual(mm, 0.0)
        self.assertNotAlmostEqual(mm, -1.0e14, delta=1.0)

    def test_the_unreachable_CP_substitution_is_warned_with_the_ratio(self):
        res, _ = _convert(
            MESH(3) + _fluid(rho="2.6E-9", k=2200.0, card2=(0.0, "1E+14"))
            + "*END\n")
        hits = _warns(res, "x the bulk modulus")
        self.assertEqual(len(hits), 1)
        # 1e14 / 2200 = 4.5454...e10
        self.assertIn(f"{1.0e14 / 2200.0:g} x the bulk modulus K=2200", hits[0])
        self.assertIn("-INFINITY", hits[0])

    def test_a_reachable_CP_is_still_a_real_cutoff(self):
        # The guard must be far above anything physical: a cut-off of even
        # 1e5 x K stays a finite Pmin, and so does a realistic fraction of K.
        for cp, want in (("1.0E6", -1.0e6),          # K/2200
                         ("2.2E14", -2.2e14)):       # 1e5 * K, still finite
            with self.subTest(cp=cp):
                _, starter = _convert(
                    MESH(3) + _fluid(k="2.2E9", card2=(0.0, cp)) + "*END\n")
                mat = _cards(_block(starter, "/MAT/HYD_VISC/3"))
                self.assertEqual(_col_f(mat[1], 21, 40), want)

    def test_the_guard_needs_a_bulk_modulus_to_compare_against(self):
        # With K unresolvable there is nothing to scale by, so only the raw
        # 1e20 literal can still be recognised.
        _, starter = _convert(
            MESH(3) + _fluid(e=0.0, pr=0.0, k=0.0, card2=(0.0, "1E+14"))
            + "*END\n")
        mat = _cards(_block(starter, "/MAT/HYD_VISC/3"))
        self.assertEqual(_col_f(mat[1], 21, 40), -1.0e14)


class TestFluidDroppedFields(unittest.TestCase):
    def test_DA_DB_are_dropped_with_a_warning(self):
        res, _ = _convert(MESH(3) + _fluid(da=0.05, db=0.02) + "*END\n")
        hits = _warns(res, "DA=0.05")
        self.assertEqual(len(hits), 1)
        self.assertIn("BEAM elements", hits[0])

    def test_zero_DA_DB_need_no_warning(self):
        res, _ = _convert(DECK_FLUID)
        self.assertEqual(_warns(res, "damping constants"), [])


# ─────────────────────────────────────────────────────────────────────────────
# D) Dispatch, the MAT_001 base-vs-FLUID split, solid-only, _target_mat_law
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatch(unittest.TestCase):
    def test_every_spelling_is_registered(self):
        for kw in ("MAT_JOHNSON_HOLMQUIST_CERAMICS", "MAT_110",
                   "MAT_JOHNSON_HOLMQUIST_CONCRETE", "MAT_111",
                   "MAT_ELASTIC", "MAT_ELASTIC_FLUID",
                   "MAT_001", "MAT_1", "MAT_001_FLUID", "MAT_1_FLUID"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_numeric_aliases_fill_the_same_containers(self):
        st = _dispatch("*KEYWORD\n" + _mat110(kw="*MAT_110")
                       + _mat111(kw="*MAT_111") + "*END\n")
        self.assertIn(110, st.mat_jh_ceramics)
        self.assertIn(111, st.mat_jh_concrete)

    def test_TITLE_dispatch_keeps_the_title_line(self):
        st = _dispatch(
            "*KEYWORD\n"
            + _mat110(kw="*MAT_JOHNSON_HOLMQUIST_CERAMICS_TITLE",
                      title="alumina AD-995")
            + _mat111(kw="*MAT_JOHNSON_HOLMQUIST_CONCRETE_TITLE",
                      title="C35/45 concrete")
            + _fluid(kw="*MAT_ELASTIC_FLUID_TITLE", title="Head")
            + "*END\n")
        self.assertEqual(st.mat_jh_ceramics[110].title, "alumina AD-995")
        self.assertEqual(st.mat_jh_concrete[111].title, "C35/45 concrete")
        self.assertEqual(st.mat_elastic_fluid[3].title, "Head")

    def test_titles_reach_the_emitted_cards(self):
        _, starter = _convert(
            MESH(110)
            + _mat110(kw="*MAT_JOHNSON_HOLMQUIST_CERAMICS_TITLE",
                      title="alumina AD-995")
            + "*END\n")
        self.assertEqual(_block(starter, "/MAT/LAW79/110")[1], "alumina AD-995")

    def test_MAT_001_FLUID_numeric_spelling_converts(self):
        # dyna2rad's dynamatlawkeywordmap.h has *MAT_ELASTIC_FLUID but not the
        # numeric one, so there it produces NO /MAT at all and the part is
        # wired to mat_ID 0 (starter ERROR 3046).
        for kw in ("*MAT_001_FLUID", "*MAT_1_FLUID"):
            with self.subTest(kw=kw):
                st = _dispatch("*KEYWORD\n" + _fluid(kw=kw) + "*END\n")
                self.assertIn(3, st.mat_elastic_fluid)
                self.assertEqual(st.mat_elastic, {})

    def test_bare_numeric_MAT_001_is_the_plain_elastic_path(self):
        for kw in ("*MAT_001", "*MAT_1"):
            with self.subTest(kw=kw):
                st = _dispatch("*KEYWORD\n" + kw + "\n"
                               + _row(9, 7.85e-9, 210000.0, 0.3) + "\n*END\n")
                self.assertIn(9, st.mat_elastic)
                self.assertEqual(st.mat_elastic_fluid, {})

    def test_nothing_lands_in_skipped_keywords(self):
        res, _ = _convert(MESH(110) + _mat110()
                          + _part(8, 7, 111) + _mat111()
                          + _part(9, 7, 3) + _fluid() + "*END\n")
        for kw in ("MAT_JOHNSON_HOLMQUIST_CERAMICS",
                   "MAT_JOHNSON_HOLMQUIST_CONCRETE", "MAT_ELASTIC_FLUID"):
            self.assertNotIn(kw, res.skipped_keywords)

    def test_offset_specs_cover_every_spelling(self):
        # A missing spelling means an *INCLUDE_TRANSFORM-ed MID is NOT offset,
        # i.e. a silent id collision on a merged deck.
        from k2rad.assembly import _OFFSET_SPECS
        for kw in ("MAT_JOHNSON_HOLMQUIST_CERAMICS", "MAT_110",
                   "MAT_JOHNSON_HOLMQUIST_CONCRETE", "MAT_111",
                   "MAT_ELASTIC_FLUID", "MAT_001_FLUID", "MAT_1_FLUID",
                   "MAT_001", "MAT_1"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)

    def test_include_transform_offsets_every_new_MID(self):
        tmp = tempfile.TemporaryDirectory()
        inc = os.path.join(tmp.name, "inc.k")
        with open(inc, "w") as fh:
            fh.write("*KEYWORD\n" + _mat110() + _mat111() + _fluid() + "*END\n")
        main = os.path.join(tmp.name, "main.k")
        with open(main, "w") as fh:
            fh.write("*KEYWORD\n" + NODES + _solid(1, 7) + _part(7, 7, 110)
                     + _part(8, 7, 111) + _part(9, 7, 3) + SEC_SOLID
                     + "*INCLUDE_TRANSFORM\ninc.k\n"
                     + _row(0, 0, 0, 1000, 0, 0) + "\n" + _row(0, 0) + "\n"
                     + "*END\n")
        res = convert(main, write_log=False)
        with open(res.starter_path) as fh:
            starter = fh.read()
        tmp.cleanup()
        for header in ("/MAT/LAW79/1110", "/MAT/LAW126/1111",
                       "/MAT/HYD_VISC/1003", "/EOS/POLYNOMIAL/1003"):
            with self.subTest(header=header):
                self.assertIn(header, starter)


class TestEmptyCardGuards(unittest.TestCase):
    """The file's standard empty-material-card guard (21 other handlers carry
    it, e.g. handle_mat_soil_and_foam). Without it a block with no data card
    aborts the WHOLE conversion with a bare IndexError, and a card whose MID
    cell is blank silently emits a /MAT of id 0 -- the *MAT_187 failure mode
    already recorded in this repo."""

    def test_a_block_with_no_data_card_is_skipped_not_a_crash(self):
        for kw in ("*MAT_JOHNSON_HOLMQUIST_CERAMICS",
                   "*MAT_JOHNSON_HOLMQUIST_CONCRETE",
                   "*MAT_110", "*MAT_111",
                   "*MAT_ELASTIC", "*MAT_ELASTIC_FLUID",
                   "*MAT_001", "*MAT_1", "*MAT_001_FLUID"):
            with self.subTest(kw=kw):
                res, starter = _convert("*KEYWORD\n" + kw + "\n*END\n")
                hits = _warns(res, "empty material card")
                self.assertEqual(len(hits), 1)
                self.assertNotIn("/MAT/", starter)

    def test_a_blank_MID_cell_does_not_emit_a_material_of_id_zero(self):
        cases = (
            ("*MAT_JOHNSON_HOLMQUIST_CERAMICS",
             _mat110(c1=("", 3700.0, "90.16E9", 0.93, 0.31, 0.007, 0.6,
                         0.64))),
            ("*MAT_JOHNSON_HOLMQUIST_CONCRETE",
             _mat111(c1=("", 2440.0, "14.86E9", 0.79, 1.6, 0.007, 0.61,
                         "48E6"))),
            ("*MAT_ELASTIC_FLUID", _fluid(mid="")),
        )
        for kw, card in cases:
            with self.subTest(kw=kw):
                res, starter = _convert("*KEYWORD\n" + card + "*END\n")
                self.assertEqual(len(_warns(res, "empty material card")), 1)
                for header in ("/MAT/LAW79/0", "/MAT/LAW126/0",
                               "/MAT/HYD_VISC/0", "/EOS/POLYNOMIAL/0",
                               "/MAT/ELAST/0"):
                    self.assertNotIn(header, starter)

    def test_a_truncated_card_1_still_converts(self):
        # Guarded field reads, like the rest of the file: only the MID cell is
        # mandatory.
        st = _dispatch("*KEYWORD\n*MAT_ELASTIC_FLUID\n" + _row(3) + "\n*END\n")
        self.assertIn(3, st.mat_elastic_fluid)
        self.assertEqual(st.mat_elastic_fluid[3].rho, 0.0)


class TestMat001BaseVsFluidSplit(unittest.TestCase):
    """The plain *MAT_ELASTIC path must be BYTE-IDENTICAL to what it was before
    the _FLUID option existed: same container, same /MAT/ELAST emitter, same
    LAW1 entry in _target_mat_law and therefore the same place on the
    starter's solid-/XREF law whitelist."""

    PLAIN = ("*KEYWORD\n" + NODES + _solid(1, 7) + _part(7, 7, 9) + SEC_SOLID
             + "*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
             + "*END\n")

    def test_plain_mat_elastic_block_is_unchanged(self):
        _, starter = _convert(self.PLAIN)
        self.assertEqual(_block(starter, "/MAT/ELAST/9"), [
            "/MAT/ELAST/9",
            "MAT_9",
            "#              RHO_I",
            "        7.850000E-09",
            "#                  E                  nu",
            "              210000                 0.3",
        ])

    def test_plain_deck_emits_no_fluid_machinery(self):
        _, starter = _convert(self.PLAIN)
        for token in ("/MAT/HYD_VISC", "/EOS/", "/MAT/LAW79", "/MAT/LAW126"):
            self.assertNotIn(token, starter)

    def test_plain_deck_is_warning_free(self):
        res, _ = _convert(self.PLAIN)
        self.assertEqual([w for w in res.warnings if "MAT_ELASTIC" in w], [])

    def test_a_card1_K_field_does_not_leak_into_the_plain_path(self):
        # K is card-1 field 7 on BOTH spellings. Without the FLUID option it is
        # unused, and the plain path must ignore it exactly as before.
        deck = ("*KEYWORD\n" + NODES + _solid(1, 7) + _part(7, 7, 9) + SEC_SOLID
                + "*MAT_ELASTIC\n"
                + _row(9, 7.85e-9, 210000.0, 0.3, 0.0, 0.0, "2.2E9") + "\n"
                + "*END\n")
        _, starter = _convert(deck)
        self.assertIn("/MAT/ELAST/9", starter)
        self.assertNotIn("/EOS/", starter)
        self.assertEqual(_dispatch(deck).mat_elastic_fluid, {})

    def test_the_two_spellings_coexist_in_one_deck(self):
        deck = ("*KEYWORD\n" + NODES + _solid(1, 7) + _part(7, 7, 9) + SEC_SOLID
                + _part(8, 7, 3)
                + "*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
                + _fluid() + "*END\n")
        st = _dispatch(deck)
        self.assertEqual(set(st.mat_elastic), {9})
        self.assertEqual(set(st.mat_elastic_fluid), {3})
        _, starter = _convert(deck)
        self.assertIn("/MAT/ELAST/9", starter)
        self.assertIn("/MAT/HYD_VISC/3", starter)


class TestSolidOnlyEnforcement(unittest.TestCase):
    """None of LAW79 / LAW126 / LAW6 declares any SHELL_* class, so a shell
    part on any of them is starter ERROR 3046. dyna2rad checks none of them."""

    def _shell_deck(self, mid, mat_text):
        return ("*KEYWORD\n" + NODES + _shell(1, 8) + _part(8, 8, mid)
                + SEC_SHELL + mat_text + "*END\n")

    def test_mat110_shell_part_warns(self):
        res, _ = _convert(self._shell_deck(110, _mat110(fs=0.0)))
        hits = _warns(res, "are SHELL parts")
        self.assertEqual(len(hits), 1)
        self.assertIn("/MAT/LAW79 declares only SOLID_ISOTROPIC and SPH",
                      hits[0])
        self.assertIn("hm_read_mat79.F:233-234", hits[0])
        self.assertIn("ERROR 3046", hits[0])
        self.assertIn("[8]", hits[0])                   # the offending pid

    def test_mat111_shell_part_warns(self):
        res, _ = _convert(self._shell_deck(111, _mat111()))
        hits = _warns(res, "are SHELL parts")
        self.assertEqual(len(hits), 1)
        self.assertIn("hm_read_mat126.F90:247-255", hits[0])
        self.assertIn("ERROR 3046", hits[0])

    def test_fluid_shell_part_warns_and_names_the_POROUS_prop_limit(self):
        res, _ = _convert(self._shell_deck(3, _fluid()))
        hits = _warns(res, "are SHELL parts")
        self.assertEqual(len(hits), 1)
        self.assertIn("SOLID_POROUS", hits[0])
        self.assertIn("ERROR 3047", hits[0])            # the ortho-prop limit

    def test_solid_parts_draw_no_shell_warning(self):
        for mid, txt in ((110, _mat110(fs=0.0)), (111, _mat111()),
                         (3, _fluid())):
            with self.subTest(mid=mid):
                res, _ = _convert(MESH(mid) + txt + "*END\n")
                self.assertEqual(_warns(res, "are SHELL parts"), [])


class TestTargetMatLaw(unittest.TestCase):
    """_target_mat_law is the ONE mid -> emitted-law map (writer/mesh.py); a
    missing entry makes inistate._resolve_xref_parts misreport an off-whitelist
    part as having no /MAT at all."""

    def test_law_numbers(self):
        deck = ("*KEYWORD\n" + NODES + _solid(1, 7) + SEC_SOLID
                + _part(7, 7, 110) + _part(8, 7, 111) + _part(9, 7, 3)
                + _part(10, 7, 9)
                + _mat110(fs=0.0) + _mat111() + _fluid()
                + "*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
                + "*END\n")
        st = _dispatch(deck)
        for mid, law in ((110, 79), (111, 126), (3, 6), (9, 1), (77, None)):
            with self.subTest(mid=mid):
                self.assertEqual(_target_mat_law(st, mid), law)

    def test_the_three_new_laws_are_OFF_the_solid_XREF_whitelist(self):
        from k2rad.writer.inistate import _XREF_SOLID_LAWS
        for law in (79, 126, 6):
            with self.subTest(law=law):
                self.assertNotIn(law, _XREF_SOLID_LAWS)
        # ... while plain *MAT_ELASTIC's LAW1 stays ON it, which is exactly
        # why the fluid gets its own container.
        self.assertIn(1, _XREF_SOLID_LAWS)

    def test_none_of_the_three_is_beam_capable(self):
        # Grepped INIT_MAT_KEYWORD in the 2026-05-20 starter tree: LAW79
        # declares SOLID_ISOTROPIC + SPH, LAW126 adds COMPRESSIBLE/
        # INCREMENTAL/LARGE_STRAIN/HYDRO_EOS/ISOTROPIC, LAW6 declares EOS/
        # HYDRO_EOS/INCOMPRESSIBLE/SOLID_POROUS/SPH. No BEAM_* keyword on any
        # of them, so PROP_BEAM stays 0 and both beam properties refuse them.
        for law in (79, 126, 6):
            with self.subTest(law=law):
                self.assertNotIn(law, _TYPE3_BEAM_LAWS)
                self.assertNotIn(law, _TYPE18_ONLY_BEAM_LAWS)

    def test_none_of_the_three_carries_a_REF_flag(self):
        # *MAT_110 / *MAT_111 are three pure-constant cards and mat_001.cfg
        # card 1 ends at K, so none belongs on the _ref_flag_materials
        # registry that drives both REF diagnostics.
        st = _dispatch("*KEYWORD\n" + _mat110() + _mat111() + _fluid()
                       + "*END\n")
        for _kw, container in _ref_flag_materials(st):
            self.assertNotIn(110, container)
            self.assertNotIn(111, container)
            self.assertNotIn(3, container)


class TestMultiMaterialDeck(unittest.TestCase):
    """All three families in one deck, each on its own solid part."""

    def setUp(self):
        deck = ("*KEYWORD\n" + NODES + _solid(1, 7) + _solid(2, 8)
                + _solid(3, 9) + _solid(4, 10) + SEC_SOLID
                + _part(7, 7, 110) + _part(8, 7, 111) + _part(9, 7, 3)
                + _part(10, 7, 9)
                + _mat110(fs=0.0) + _mat111() + _fluid()
                + "*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
                + "*END\n")
        self.res, self.starter = _convert(deck)

    def test_each_material_is_emitted_exactly_once(self):
        for hdr in ("/MAT/LAW79/110", "/MAT/LAW126/111", "/MAT/HYD_VISC/3",
                    "/EOS/POLYNOMIAL/3", "/MAT/ELAST/9"):
            with self.subTest(hdr=hdr):
                self.assertEqual(len(_blocks(self.starter, hdr)), 1)

    def test_material_ids_are_the_LSDYNA_MIDs_verbatim(self):
        # k2rad emits every /MAT under the LS-DYNA MID (no duplication remap
        # as in dyna2rad, where a MID shared by >1 *SECTION is cloned at
        # max(MAT id)+1).
        for mid in (110, 111, 3, 9):
            with self.subTest(mid=mid):
                self.assertIn(f"/{mid}\n", self.starter)

    def test_the_JH_laws_add_no_EOS_while_the_fluid_does(self):
        self.assertEqual(len(_blocks(self.starter, "/EOS/")), 1)

    def test_no_duplicate_material_ids(self):
        heads = [ln.split("/")[-1] for ln in self.starter.splitlines()
                 if ln.startswith("/MAT/")]
        self.assertEqual(len(heads), len(set(heads)))


class TestSharedIdEosDoesNotDuplicateTheMaterial(unittest.TestCase):
    """k2rad's shared-id convention ("an *EOS_* whose id matches a material's
    is that material's EOS") is a convenience it adds on top of LS-DYNA, where
    an *EOS_* binds only through the *PART EOSID field. The standalone-fluid
    branch walks state.mat_null only, so without a guard it emits a SECOND
    /MAT under an id this batch already owns -- starter ERROR 79."""

    EOS = ("*EOS_LINEAR_POLYNOMIAL\n"
           + _row(110, 0.0, "2.0E9", 0.0, 0.0, 0.0, 0.0, 0.0) + "\n"
           + _row(0.0) + "\n")

    def _headers(self, starter):
        return [ln for ln in starter.splitlines()
                if ln.startswith("/MAT/") or ln.startswith("/EOS/")]

    def test_mat110_sharing_an_id_with_an_EOS_stays_single(self):
        res, starter = _convert(MESH(110) + _mat110(fs=0.0)
                                + self.EOS + "*END\n")
        self.assertEqual(self._headers(starter), ["/MAT/LAW79/110"])
        hits = _warns(res, "ERROR 79")
        self.assertEqual(len(hits), 1)
        self.assertIn("its own K1/K2/K3 polynomial", hits[0])
        self.assertIn("*PART EOSID field", hits[0])

    def test_mat111_sharing_an_id_with_an_EOS_stays_single(self):
        eos = self.EOS.replace(f"{110:>10}", f"{111:>10}", 1)
        res, starter = _convert(MESH(111) + _mat111() + eos + "*END\n")
        self.assertEqual(self._headers(starter), ["/MAT/LAW126/111"])
        self.assertEqual(len(_warns(res, "ERROR 79")), 1)

    def test_fluid_sharing_an_id_with_an_EOS_keeps_only_its_own(self):
        # The fluid already emits /EOS/POLYNOMIAL/3 from its own K, so the
        # shared-id carrier would duplicate BOTH the /MAT and the /EOS.
        eos = self.EOS.replace(f"{110:>10}", f"{3:>10}", 1)
        res, starter = _convert(MESH(3) + _fluid() + eos + "*END\n")
        self.assertEqual(self._headers(starter),
                         ["/MAT/HYD_VISC/3", "/EOS/POLYNOMIAL/3"])
        # ... and the surviving /EOS is the fluid's own K = 2.2e9, not the
        # dropped *EOS_LINEAR_POLYNOMIAL's C1 = 2.0e9.
        eos_cards = _cards(_block(starter, "/EOS/POLYNOMIAL/3"))
        self.assertEqual(_col_f(eos_cards[0], 21, 40), 2.2e9)
        self.assertEqual(len(_warns(res, "ERROR 79")), 1)
        self.assertIn("already emits its OWN", _warns(res, "ERROR 79")[0])

    def test_an_unrelated_EOS_id_gets_no_carrier_either(self):
        """An *EOS_* on an id NO material holds is dropped too — and this
        assertion is the REVERSE of what it pinned before the SIDE-DEFECT
        batch, because the output it used to pin is refused by the starter.

        The old expectation was ``/MAT/LAW79/110`` + ``/MAT/HYD_VISC/500`` +
        ``/EOS/POLYNOMIAL/500``. MEASURED on that exact deck (converted at
        master 0c8968e, run through the starter): the carrier's RHO_I column
        is ``0`` and the starter answers

            ERROR ID :    683   ** INPUT ERROR IN MATERIAL LAW
               -- MATERIAL ID: 500  -- MATERIAL TITLE: FLUID_500
               DENSITY IS LESS THAN OR EQUAL TO ZERO
            ERROR TERMINATION   1 ERROR(S)

        /MAT/LAW6 is not in the density exemption list at
        ``hm_read_mat.F90:1575-1583``, and NONE of the three *EOS_* spellings
        k2rad reads carries a density cell (verified: every handler stores
        ``rho0 = 0.0``, because LS-DYNA takes the density from the *PART's own
        *MAT — Vol I R17 p.37-6), so this branch could never emit a runnable
        pair for ANY deck. Dropping is also what LS-DYNA does with an *EOS_*
        no *PART EOSID names, and what dyna2rad does (convertmats.cxx:572
        reaches an EOS only from a *PART)."""
        res, starter = _convert(MESH(110) + _mat110(fs=0.0)
                                + self.EOS.replace(f"{110:>10}",
                                                   f"{500:>10}", 1)
                                + "*END\n")
        self.assertEqual(self._headers(starter), ["/MAT/LAW79/110"])
        # Not the collision message — id 500 is held by nothing.
        self.assertEqual(_warns(res, "ERROR 79"), [])
        w = _warns(res, "*EOS_POLYNOMIAL 500")
        self.assertEqual(len(w), 1)
        self.assertIn("ERROR 683", w[0])
        self.assertIn("no *MAT_NULL of that id", w[0])
        # The message must name BOTH cards it declined to write.
        self.assertIn("/MAT/HYD_VISC/500", w[0])
        self.assertIn("/EOS/POLYNOMIAL/500", w[0])

    def test_no_duplicate_MAT_ids_in_any_of_the_three_cases(self):
        for mid, txt in ((110, _mat110(fs=0.0)), (111, _mat111()),
                         (3, _fluid())):
            with self.subTest(mid=mid):
                eos = self.EOS.replace(f"{110:>10}", f"{mid:>10}", 1)
                _, starter = _convert(MESH(mid) + txt + eos + "*END\n")
                ids = [ln.rsplit("/", 1)[-1]
                       for ln in starter.splitlines()
                       if ln.startswith("/MAT/")]
                self.assertEqual(len(ids), len(set(ids)))


class TestNoMovementOnDecksWithoutTheBatch(unittest.TestCase):
    """A deck that uses none of the three keywords must be byte-identical to
    what master produced -- the batch adds emission, never rewrites."""

    BASELINE = ("*KEYWORD\n" + NODES + _solid(1, 7) + _part(7, 7, 9)
                + SEC_SOLID
                + "*MAT_ELASTIC\n" + _row(9, 7.85e-9, 210000.0, 0.3) + "\n"
                + "*END\n")

    def test_starter_deck_matches_a_recorded_snapshot(self):
        _, starter = _convert(self.BASELINE)
        # The whole /MAT section, verbatim.
        self.assertIn("\n".join([
            "/MAT/ELAST/9",
            "MAT_9",
            "#              RHO_I",
            "        7.850000E-09",
            "#                  E                  nu",
            "              210000                 0.3",
        ]), starter)

    def test_conversion_is_deterministic(self):
        a, sa = _convert(self.BASELINE)
        b, sb = _convert(self.BASELINE)
        self.assertEqual(sa, sb)
        self.assertEqual(a.warnings, b.warnings)
        self.assertEqual(a.skipped_keywords, b.skipped_keywords)

    def test_impact_prepass_is_a_no_op_without_the_containers(self):
        res, _ = _convert(self.BASELINE)
        for needle in ("LAW79", "LAW126", "HYD_VISC", "JOHNSON_HOLMQUIST",
                       "ELASTIC_FLUID"):
            with self.subTest(needle=needle):
                self.assertEqual(_warns(res, needle), [])


if __name__ == "__main__":
    unittest.main()
