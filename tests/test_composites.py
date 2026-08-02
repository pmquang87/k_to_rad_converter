"""Tests for the COMPOSITE conversions:

  *MAT_ORTHOTROPIC_ELASTIC (002, +_TITLE)      -> /MAT/LAW93  (ORTH_HILL)
  *MAT_ANISOTROPIC_ELASTIC (002 ANIS dialect)  -> warn-skip (no /MAT)
  *MAT_ENHANCED_COMPOSITE_DAMAGE (054/055)     -> /MAT/LAW127 [+ /FAIL/GENE1]
  *MAT_TRANSVERSELY_ANISOTROPIC_... (037)      -> /MAT/LAW43  [+ /FAIL/FLD]
  *MAT_LAMINATED_GLASS (032)                   -> a /MAT/PLAS_BRIT (LAW27) PAIR
  *PART_COMPOSITE (+_TITLE/_LONG/_CONTACT/...) -> /PROP/TYPE51 + /PROP/TYPE19
  AOPT 0/1/2/3/4/<0                            -> Ip / Vx-Vy-Vz / /SKEW/FIX

Kept in a separate module from tests/test_converter.py (same policy as
tests/test_joints.py, tests/test_connectors.py and tests/test_roadmap_keywords.py).

Assertions are COLUMN-EXACT against the emitted cards, and every physics
constant (the Poisson rescales, the plastic hardening modulus, the skew triad)
is recomputed by hand in the test rather than copied from the implementation.
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
from k2rad.handlers import dispatch              # noqa: E402
from k2rad.state import ConversionState          # noqa: E402


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
    """A block's DATA lines: everything after the title that is not a comment.

    Blank lines are KEPT — the /PROP/TYPE51 ply block is two lines per ply and
    the second one is a mandatory blank.
    """
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _fail_cards(block):
    """A /FAIL block's data lines. /FAIL cards carry NO title line."""
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


# ── Decks ────────────────────────────────────────────────────────────────────

NODES = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
        (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0)))
)
SHELL = "*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
SOLID_NODES = (
    "*NODE\n"
    + "".join(f"{nid:>8}{x:>16}{y:>16}{z:>16}\n" for nid, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
        (4, 0.0, 10.0, 0.0), (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
        (7, 10.0, 10.0, 10.0), (8, 0.0, 10.0, 10.0)))
)
BRICK = "*ELEMENT_SOLID\n" + _row(1, 7) + "\n" + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
PART = "*PART\nshell part\n" + _row(7, 7, 2) + "\n"
SECTION = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 4) + "\n"
           + _row(1.2, 1.2, 1.2, 1.2) + "\n")
SECTION_SOLID = "*SECTION_SOLID\n" + _row(7, 1) + "\n"
END = "*CONTROL_TERMINATION\n" + _row(0.001) + "\n*END\n"


def _mat002(mid=2, aopt=0.0, beta=0.0, a=(0.0, 0.0, 0.0), v=(0.0, 0.0, 0.0),
            d=(0.0, 0.0, 0.0), title=True, macf=0,
            ea=150000.0, eb=10000.0, ec=10000.0,
            prba=0.02, prca=0.02, prcb=0.4,
            gab=5000.0, gbc=3000.0, gca=4000.0):
    """*MAT_ORTHOTROPIC_ELASTIC. Card 1a.2 field 4 is AOPT; card 2 holds
    XP/YP/ZP + A1..A3 + MACF; card 3 holds V1..V3 + D1..D3 + BETA."""
    kw = "*MAT_ORTHOTROPIC_ELASTIC_TITLE\ncarbon UD\n" if title \
        else "*MAT_ORTHOTROPIC_ELASTIC\n"
    return (kw
            + _row(mid, 1.55e-9, ea, eb, ec, prba, prca, prcb) + "\n"
            + _row(gab, gbc, gca, aopt) + "\n"
            + _row(0.0, 0.0, 0.0, a[0], a[1], a[2], macf) + "\n"
            + _row(v[0], v[1], v[2], d[0], d[1], d[2], beta) + "\n")


def _mat054(mid=54, crit=54.0, aopt=0.0, mangle=0.0, tfail=0.0,
            a=(0.0, 0.0, 0.0), v=(0.0, 0.0, 0.0), cards789=True, kw=None):
    """*MAT_ENHANCED_COMPOSITE_DAMAGE with all nine cards."""
    head = kw or "*MAT_ENHANCED_COMPOSITE_DAMAGE"
    out = (head + "\n"
           + _row(mid, 1.6e-9, 135000.0, 9000.0, 9000.0, 0.02, 0.02, 0.4) + "\n"
           + _row(4700.0, 3200.0, 4100.0, "", aopt, 1, 2) + "\n"
           + _row(0.0, 0.0, 0.0, a[0], a[1], a[2], mangle) + "\n"
           + _row(v[0], v[1], v[2], 0.0, 0.0, 0.0, 0.033, 0.044) + "\n"
           + _row(tfail, 0.2, 0.8, 0.5, 2.5, 0.02, -0.015, 0.06) + "\n"
           + _row(1500.0, 2000.0, 200.0, 50.0, 70.0, crit, 0.5) + "\n")
    if cards789:
        out += (_row(20.0, 0.05, 0.10, 0.85, 0.9) + "\n"
                + _row(1.0, 0.9, 1.1, 0.8, 1.2, 3, 1.0) + "\n"
                + _row(901, 902, 903, 904, 905, 1e-4) + "\n")
    return out


def _mat037(mid=37, sigy=300.0, etan=1000.0, r=1.8, hlcid=0, opt="",
            icfld=0, strainlt=0.0, idscale=0, ea=0.0, coe=0.0):
    kw = "*MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC" + opt
    return (kw + "\n"
            + _row(mid, 7.85e-9, 210000.0, 0.3, sigy, etan, r, hlcid) + "\n"
            + _row(idscale, ea, coe, icfld, "", strainlt) + "\n")


def _mat032(mid=32, f=(0.0, 1.0, 1.0, 0.0), efg=0.01):
    return ("*MAT_LAMINATED_GLASS_TITLE\nwindshield\n"
            + _row(mid, 2.5e-9, 70000.0, 0.23, 100.0, 0.0, efg, 3000.0) + "\n"
            + _row(0.40, 20.0, 10.0) + "\n"
            + _row(*f) + "\n")


def _curve(lcid, pts=((0.0, 0.0), (0.5, 0.8))):
    return ("*DEFINE_CURVE\n" + _row(lcid) + "\n"
            + "".join(f"{x:>20}{y:>20}\n" for x, y in pts))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_ORTHOTROPIC_ELASTIC (002) -> /MAT/LAW93
# ═════════════════════════════════════════════════════════════════════════════

class Law93Tests(unittest.TestCase):
    """*MAT_ORTHOTROPIC_ELASTIC -> /MAT/LAW93, with the Poisson-convention
    conversion that is the one real numeric trap in the batch."""

    def _law93(self, **kw):
        deck = ("*KEYWORD\n" + NODES + SHELL + PART + SECTION
                + _mat002(**kw) + END)
        result, starter = _convert(deck)
        return result, starter, _block(starter, "/MAT/LAW93/2")

    def test_poisson_rescale_is_minor_to_major(self):
        """LS-DYNA PRBA is the MINOR ratio nu_ba; Radioss NU12 is the MAJOR
        ratio tied to E11. Reciprocity nu12/E11 = nu21/E22 gives
        NU12 = PRBA*EA/EB — a naive 1:1 copy is wrong by the factor EA/EB."""
        _, _, blk = self._law93(ea=150000.0, eb=10000.0, ec=7500.0,
                                prba=0.02, prca=0.03, prcb=0.4)
        cards = _cards(blk)
        # card 2 = E11 E22 E33 G12 NU12 ; card 3 = G13 G23 NU13 NU23
        self.assertAlmostEqual(_f20(cards[1], 0), 150000.0)
        self.assertAlmostEqual(_f20(cards[1], 1), 10000.0)
        self.assertAlmostEqual(_f20(cards[1], 2), 7500.0)
        # hand-computed: 0.02 * 150000/10000 = 0.02 * 15 = 0.30
        self.assertAlmostEqual(_f20(cards[1], 4), 0.30, places=9)
        # 0.03 * 150000/7500 = 0.03 * 20 = 0.60
        self.assertAlmostEqual(_f20(cards[2], 2), 0.60, places=9)
        # 0.4 * 10000/7500 = 0.5333333...
        self.assertAlmostEqual(_f20(cards[2], 3), 0.4 * 10000.0 / 7500.0,
                               places=9)

    def test_shear_moduli_swap_gbc_to_g23_and_gca_to_g13(self):
        """LS-DYNA writes GAB GBC GCA; Radioss card order is G12 then G13 G23."""
        _, _, blk = self._law93(gab=5000.0, gbc=3000.0, gca=4000.0)
        cards = _cards(blk)
        self.assertAlmostEqual(_f20(cards[1], 3), 5000.0)   # G12 <- GAB
        self.assertAlmostEqual(_f20(cards[2], 0), 4000.0)   # G13 <- GCA
        self.assertAlmostEqual(_f20(cards[2], 1), 3000.0)   # G23 <- GBC

    def test_elastic_only_yield_is_out_of_reach(self):
        """LAW93 is orthotropic HILL PLASTICITY but MAT_002 is purely elastic:
        sigma_y = 1e30 and every Hill ratio 1.0 keeps the surface unreachable."""
        _, _, blk = self._law93()
        cards = _cards(blk)
        self.assertEqual(_i10(cards[3], 0), 0)                # NL  = 0
        self.assertEqual(_i10(cards[3], 1), 0)                # VP  = 0
        self.assertAlmostEqual(_f20(cards[4], 0), 1.0e30)     # sigma_y
        for i in range(1, 5):                                 # QR1 CR1 QR2 CR2
            self.assertAlmostEqual(_f20(cards[4], i), 0.0)
        for c in (cards[5], cards[6]):                        # R11..R23
            for i in range(3):
                self.assertAlmostEqual(_f20(c, i), 1.0)

    def test_title_option_dispatch(self):
        """_TITLE is stripped by _split_keyword, so both spellings hit the same
        handler and the title lands on the /MAT card."""
        _, _, blk = self._law93(title=True)
        self.assertEqual(blk[1], "carbon UD")
        _, _, blk = self._law93(title=False)
        self.assertEqual(blk[1], "MAT_2")

    def test_numeric_alias_keys(self):
        for kw in ("*MAT_002\n", "*MAT_2\n"):
            deck = ("*KEYWORD\n" + NODES + SHELL + PART + SECTION + kw
                    + _row(2, 1.55e-9, 150000.0, 10000.0, 10000.0,
                           0.02, 0.02, 0.4) + "\n"
                    + _row(5000.0, 3000.0, 4000.0, 0.0) + "\n"
                    + _row(0.0) + "\n" + _row(0.0) + "\n" + END)
            result, starter = _convert(deck)
            self.assertIn("/MAT/LAW93/2", starter, kw)
            self.assertEqual(result.skipped_keywords, [], kw)

    def test_zero_eb_is_guarded_not_infinite(self):
        """dyna2rad evaluates EA*PRBA/EB through exprtk with no zero guard and
        emits inf/NaN; here EB=0 takes the starter's own EB<-EA fallback."""
        _, starter, blk = self._law93(eb=0.0, ec=0.0)
        cards = _cards(blk)
        self.assertAlmostEqual(_f20(cards[1], 1), 150000.0)   # E22 <- E11
        self.assertAlmostEqual(_f20(cards[1], 2), 150000.0)   # E33 <- E22
        self.assertNotIn("inf", starter.lower())
        self.assertNotIn("nan", starter.lower())

    def test_unstable_poisson_pair_is_warned(self):
        """NU12*NU21 >= 1 is starter ERROR 3068 — warn before it gets there."""
        result, _, _ = self._law93(ea=150000.0, eb=10000.0, prba=0.30)
        self.assertTrue(any("NU12*NU21" in w and "3068" in w
                            for w in result.warnings), result.warnings)

    def test_macf_axis_swap_is_warned(self):
        result, _, _ = self._law93(macf=3)
        self.assertTrue(any("MACF=3" in w and "DROPPED" in w
                            for w in result.warnings), result.warnings)


class MatAnisotropicElasticTests(unittest.TestCase):
    """*MAT_ANISOTROPIC_ELASTIC (the 002 ANIS dialect) is recognized but NOT
    emitted: the 6x6 C-matrix has no /MAT/LAW93 home. dyna2rad writes a LAW93
    with all moduli zero and no warning."""

    DECK = ("*KEYWORD\n" + NODES + SHELL + PART + SECTION
            + "*MAT_ANISOTROPIC_ELASTIC\n"
            + _row(2, 1.55e-9, 150000.0, 3000.0, 10000.0, 3000.0, 3000.0,
                   10000.0) + "\n"
            + _row(0.0, 0.0, 0.0, 5000.0, 0.0, 0.0, 0.0, 0.0) + "\n"
            + _row(4000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 4500.0, 0.0) + "\n"
            + _row(0.0) + "\n" + _row(0.0) + "\n" + END)

    def test_no_zero_modulus_law93_is_written(self):
        result, starter = _convert(self.DECK)
        self.assertNotIn("/MAT/LAW93", starter)

    def test_warns_loudly_and_names_the_referencing_part(self):
        result, _ = _convert(self.DECK)
        hit = [w for w in result.warnings if "ANISOTROPIC_ELASTIC" in w]
        self.assertTrue(hit, result.warnings)
        self.assertIn("NOT emitted", hit[0])
        self.assertIn("[7]", hit[0])          # the part that references it

    def test_reported_as_recognized_not_emitted(self):
        result, _ = _convert(self.DECK)
        self.assertTrue(any(kw == "MAT_ANISOTROPIC_ELASTIC"
                            for kw, _ in result.recognized_not_emitted),
                        result.recognized_not_emitted)
        self.assertEqual(result.skipped_keywords, [])

    def test_ortho_dialect_is_unaffected(self):
        """The two dialects are separate HANDLERS keys, so *MAT_002_ANIS must
        not swallow the plain *MAT_ORTHOTROPIC_ELASTIC path."""
        state = _dispatch("*KEYWORD\n" + _mat002() + "*END\n")
        self.assertIn(2, state.mat_orthotropic)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_ENHANCED_COMPOSITE_DAMAGE (054/055) -> /MAT/LAW127
# ═════════════════════════════════════════════════════════════════════════════

class Law127Tests(unittest.TestCase):
    """*MAT_ENHANCED_COMPOSITE_DAMAGE -> /MAT/LAW127."""

    def _law127(self, **kw):
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*PART\nshell part\n" + _row(7, 7, 54) + "\n" + SECTION
                + _mat054(**kw) + END)
        result, starter = _convert(deck)
        return result, starter, _block(starter, "/MAT/LAW127/54")

    def test_poisson_is_raw_not_rescaled(self):
        """LAW127 reads PRBA/PRCA/PRCB VERBATIM as nu21/nu31/nu32 and derives
        nu12 = nu21*E1/E2 itself (hm_read_mat127.F90:127-129, 186-198). The
        LAW93 E*nu/E rescale must NOT be applied — it would double-apply."""
        _, _, blk = self._law127()
        cards = _cards(blk)
        # card 4 (index 3) = Nu21 Nu31 Nu32
        self.assertAlmostEqual(_f20(cards[3], 0), 0.02)     # PRBA raw
        self.assertAlmostEqual(_f20(cards[3], 1), 0.02)     # PRCA raw
        self.assertAlmostEqual(_f20(cards[3], 2), 0.40)     # PRCB raw
        # ...and NOT the LAW93 value 0.02*135000/9000 = 0.30
        self.assertNotAlmostEqual(_f20(cards[3], 0), 0.30)

    def test_moduli_and_shear_order(self):
        _, _, blk = self._law127()
        cards = _cards(blk)
        self.assertAlmostEqual(_f20(cards[1], 0), 135000.0)  # E1 <- EA
        self.assertAlmostEqual(_f20(cards[1], 1), 9000.0)    # E2 <- EB
        self.assertAlmostEqual(_f20(cards[1], 2), 9000.0)    # E3 <- EC
        self.assertAlmostEqual(_f20(cards[2], 0), 4700.0)    # G12 <- GAB
        self.assertAlmostEqual(_f20(cards[2], 1), 4100.0)    # G13 <- GCA
        self.assertAlmostEqual(_f20(cards[2], 2), 3200.0)    # G23 <- GBC

    def test_strengths_slim_and_rate_curves(self):
        """Cards 5-9 pair each strength with its SLIM factor and rate curve."""
        _, _, blk = self._law127()
        cards = _cards(blk)
        #            card index, strength, SLIM, LC
        for idx, strength, slim, lc in ((4, 2000.0, 1.0, 902),    # XT SLIMT1 LCXT
                                        (5, 50.0, 1.1, 904),      # YT SLIMT2 LCYT
                                        (6, 70.0, 1.2, 905),      # SC SLIMSC LCSC
                                        (7, 1500.0, 0.9, 901),    # XC SLIMC1 LCXC
                                        (8, 200.0, 0.8, 903)):    # YC SLIMC2 LCYC
            line = cards[idx]
            self.assertAlmostEqual(_col_f(line, 1, 20), strength)
            self.assertAlmostEqual(_col_f(line, 21, 40), slim)
            self.assertEqual(_col_i(line, 51, 60), lc)
            self.assertAlmostEqual(_col_f(line, 61, 80), 1.0)     # SCALC*

    def test_failure_strains_and_ratio_from_pfl(self):
        _, _, blk = self._law127()
        cards = _cards(blk)
        c12 = cards[11]      # DFAILT DFAILC DFAILS DFAILM RATIO
        self.assertAlmostEqual(_f20(c12, 0), 0.02)      # DFAILT
        self.assertAlmostEqual(_f20(c12, 1), -0.015)    # DFAILC (negative)
        # Card 4 is V1 V2 V3 D1 D2 D3 DFAILM DFAILS — field 7 is DFAILM.
        self.assertAlmostEqual(_f20(c12, 2), 0.044)     # DFAILS (card 4 f8)
        self.assertAlmostEqual(_f20(c12, 3), 0.033)     # DFAILM (card 4 f7)
        self.assertAlmostEqual(_f20(c12, 4), 20.0)      # RATIO <- |PFL|
        c13 = cards[12]      # blank NCYRED TFAIL FBRT YCFAC
        self.assertEqual(_col_i(c13, 11, 20), 3)        # NCYRED
        self.assertAlmostEqual(_col_f(c13, 41, 60), 0.5)   # FBRT
        self.assertAlmostEqual(_col_f(c13, 61, 80), 2.5)   # YCFAC
        c14 = cards[13]      # EFS EPSF EPSR TSMD
        self.assertAlmostEqual(_f20(c14, 0), 0.06)      # EFS
        self.assertAlmostEqual(_f20(c14, 1), 0.05)      # EPSF
        self.assertAlmostEqual(_f20(c14, 2), 0.10)      # EPSR
        self.assertAlmostEqual(_f20(c14, 3), 0.85)      # TSMD

    def test_card4_dfail_columns_only_read_when_dfailt_positive(self):
        """Card 4 is always ONE line; its cols 61-80 hold DFAILM/DFAILS only
        when DFAILT (card 5) > 0 — the manual's rule stated non-circularly."""
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*PART\np\n" + _row(7, 7, 54) + "\n" + SECTION
                + "*MAT_ENHANCED_COMPOSITE_DAMAGE\n"
                + _row(54, 1.6e-9, 135000.0, 9000.0, 9000.0, 0.02, 0.02, 0.4) + "\n"
                + _row(4700.0, 3200.0, 4100.0, "", 0.0) + "\n"
                + _row(0.0) + "\n"
                + _row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.033, 0.044) + "\n"
                # DFAILT (field 6) = 0 -> cols 61-80 of card 4 are NOT DFAILM/S
                + _row(0.0, 0.2, 1.0, 0.5, 2.0, 0.0, 0.0, 0.0) + "\n"
                + _row(1500.0, 2000.0, 200.0, 50.0, 70.0, 54.0, 0.5) + "\n"
                + END)
        _, starter = _convert(deck)
        cards = _cards(_block(starter, "/MAT/LAW127/54"))
        self.assertAlmostEqual(_f20(cards[11], 2), 0.0)    # DFAILS ignored
        self.assertAlmostEqual(_f20(cards[11], 3), 0.0)    # DFAILM ignored

    def test_optional_cards_789_are_cascading(self):
        """Without cards 7/8/9 the SLIM factors keep their 1.0 defaults and no
        rate curve is referenced."""
        _, _, blk = self._law127(cards789=False)
        cards = _cards(blk)
        for idx in (4, 5, 6, 7, 8):
            self.assertAlmostEqual(_col_f(cards[idx], 21, 40), 1.0)
            self.assertEqual(_col_i(cards[idx], 51, 60), 0)
        self.assertAlmostEqual(_f20(cards[11], 4), 0.0)       # RATIO (no PFL)
        self.assertAlmostEqual(_f20(cards[13], 3), 0.9)       # TSMD default

    def test_tfail_in_unit_window_adds_fail_gene1_dtmin(self):
        """0 < TFAIL < 1 is LS-DYNA's ABSOLUTE dt criterion -> /FAIL/GENE1
        dtmin, bound by the shared id (Radioss pairs /FAIL to /MAT by id)."""
        result, starter, _ = self._law127(tfail=0.001)
        blk = _block(starter, "/FAIL/GENE1/54")
        card1 = _fail_cards(blk)[0]
        self.assertAlmostEqual(_col_f(card1, 81, 100), 0.001)   # dtmin
        self.assertTrue(any("dtmin=0.001" in w for w in result.warnings))

    def test_tfail_ratio_form_gets_no_companion(self):
        """TFAIL > 1 is a RATIO of the original dt, which Radioss's ABSOLUTE
        dtmin cannot express — no /FAIL/GENE1, and a warning saying why."""
        result, starter, blk = self._law127(tfail=1.5)
        self.assertEqual(_blocks(starter, "/FAIL/GENE1"), [])
        self.assertAlmostEqual(_f20(_cards(blk)[12], 1), 1.5)   # still on-card
        self.assertTrue(any("RATIO form" in w for w in result.warnings))

    def test_tfail_zero_gets_no_companion(self):
        _, starter, _ = self._law127(tfail=0.0)
        self.assertEqual(_blocks(starter, "/FAIL/GENE1"), [])

    def test_crit_55_tsai_wu_is_loudly_warned(self):
        """LAW127 is Chang-Chang only; dyna2rad drops CRIT silently and emits
        byte-identical output for 54 and 55."""
        result, _, _ = self._law127(crit=55.0)
        self.assertTrue(any("TSAI-WU" in w and "CHANG-CHANG" in w
                            for w in result.warnings), result.warnings)
        result, _, _ = self._law127(crit=54.0)
        self.assertFalse(any("TSAI-WU" in w for w in result.warnings))

    def test_mat_055_keyword_defaults_to_tsai_wu(self):
        """CRIT blank + a *MAT_055 spelling still means Tsai-Wu."""
        result, starter = _convert(
            "*KEYWORD\n" + NODES + SHELL + "*PART\np\n" + _row(7, 7, 54) + "\n"
            + SECTION + _mat054(crit="", kw="*MAT_055") + END)
        self.assertIn("/MAT/LAW127/54", starter)
        self.assertTrue(any("TSAI-WU" in w for w in result.warnings),
                        result.warnings)

    def test_dropped_softening_fields_are_warned(self):
        result, _, _ = self._law127()
        hit = [w for w in result.warnings if "NO /MAT/LAW127 column" in w]
        self.assertTrue(hit, result.warnings)
        self.assertIn("SOFT=0.8", hit[0])
        self.assertIn("SOFT2=0.9", hit[0])
        self.assertIn("DT=0.0001", hit[0])

    def test_all_numeric_aliases_dispatch(self):
        for kw in ("*MAT_054", "*MAT_54", "*MAT_055", "*MAT_55"):
            state = _dispatch("*KEYWORD\n" + _mat054(kw=kw) + "*END\n")
            self.assertIn(54, state.mat_enhanced_composite, kw)

    def test_unstable_raw_poisson_is_warned(self):
        """PRBA holding a MAJOR ratio is the classic authoring mistake; LAW127
        would then derive nu12 > 1 and the starter aborts (ERROR 3068/307)."""
        deck = ("*KEYWORD\n" + NODES + SHELL + "*PART\np\n" + _row(7, 7, 54)
                + "\n" + SECTION
                + "*MAT_ENHANCED_COMPOSITE_DAMAGE\n"
                + _row(54, 1.6e-9, 135000.0, 9000.0, 9000.0, 0.30, 0.02, 0.4) + "\n"
                + _row(4700.0, 3200.0, 4100.0, "", 0.0) + "\n"
                + _row(0.0) + "\n" + _row(0.0) + "\n"
                + _row(0.0, 0.2, 1.0, 0.5) + "\n"
                + _row(1500.0, 2000.0, 200.0, 50.0, 70.0, 54.0) + "\n" + END)
        result, _ = _convert(deck)
        self.assertTrue(any("PRBA=0.3" in w and "NU12*NU21" in w
                            for w in result.warnings), result.warnings)

    def test_routed_to_orthotropic_property_not_type1(self):
        """/MAT/LAW127 registers PROP_SHELL=2 and /PROP/SHELL (IGTYP 1) accepts
        only classes 1 and 5, so dyna2rad's TYPE1 route is starter ERROR 3047."""
        _, starter, _ = self._law127()
        self.assertEqual(_blocks(starter, "/PROP/SHELL"), [])
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE11")), 1)


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC (037) -> /MAT/LAW43
# ═════════════════════════════════════════════════════════════════════════════

class Law43Tests(unittest.TestCase):
    """*MAT_037 -> /MAT/LAW43 (HILL_TAB), a tabular-only law."""

    def _law43(self, extra="", **kw):
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*PART\np\n" + _row(7, 7, 37) + "\n" + SECTION
                + _mat037(**kw) + extra + END)
        result, starter = _convert(deck)
        return result, starter, _block(starter, "/MAT/LAW43/37")

    def test_single_r_bar_fills_all_three_lankford_slots(self):
        """MAT_037 is transversely isotropic: r00 = r45 = r90 = |R|."""
        _, _, blk = self._law43(r=1.8)
        c = _cards(blk)[3]
        for i in range(3):
            self.assertAlmostEqual(_f20(c, i), 1.8)
        self.assertAlmostEqual(_col_f(c, 61, 80), 0.0)      # C_hard
        self.assertEqual(_col_i(c, 81, 90), 0)              # Iyield0

    def test_negative_r_takes_magnitude(self):
        """R < 0 requests a stabilized scheme in LS-DYNA, not a negative ratio."""
        result, _, blk = self._law43(r=-2.5)
        self.assertAlmostEqual(_f20(_cards(blk)[3], 0), 2.5)
        self.assertTrue(any("stabilized" in w.lower() for w in result.warnings))

    def test_synthesized_hardening_curve_uses_plastic_modulus(self):
        """LAW43 has no SIGY/ETAN slot, so HLCID=0 needs a bilinear /FUNCT. Its
        slope must be the PLASTIC modulus H = E*ETAN/(E-ETAN) because the LAW43
        curve is stress vs PLASTIC strain (dyna2rad writes the raw ETAN)."""
        result, starter, blk = self._law43(sigy=300.0, etan=1000.0, hlcid=0)
        fid = _i10(_cards(blk)[5], 0)
        self.assertGreater(fid, 0)
        h = 210000.0 * 1000.0 / (210000.0 - 1000.0)     # = 1004.7846...
        self.assertAlmostEqual(h, 1004.784688995215, places=6)
        curve = _cards(_block(starter, f"/FUNCT/{fid}"))
        self.assertEqual(len(curve), 2)
        self.assertAlmostEqual(_f20(curve[0], 0), 0.0)
        self.assertAlmostEqual(_f20(curve[0], 1), 300.0)
        self.assertAlmostEqual(_f20(curve[1], 0), 1.0)
        self.assertAlmostEqual(_f20(curve[1], 1), 300.0 + h, places=3)
        # ...and NOT dyna2rad's SIGY + |ETAN| = 1300
        self.assertNotAlmostEqual(_f20(curve[1], 1), 1300.0, places=1)

    def test_hlcid_curve_is_bound_directly(self):
        """dyna2rad's missing braces (convertmats.cxx:3100-3102) overwrite
        func_IDi[0] with HLCID in BOTH branches; the binding must be real."""
        result, starter, blk = self._law43(hlcid=800, extra=_curve(800))
        self.assertEqual(_i10(_cards(blk)[5], 0), 800)
        self.assertAlmostEqual(_col_f(_cards(blk)[5], 21, 40), 1.0)  # Fscale
        # no synthetic curve when the deck supplies one
        self.assertFalse(any("synthesized as /FUNCT" in w
                             for w in result.warnings))

    def test_dangling_hlcid_is_warned(self):
        result, _, _ = self._law43(hlcid=808)
        self.assertTrue(any("HLCID=808" in w and "NOT in the deck" in w
                            for w in result.warnings), result.warnings)

    def test_echange_maps_to_einf_ce_and_funct_ide(self):
        result, _, blk = self._law43(opt="_ECHANGE", idscale=810, ea=180000.0,
                                     coe=25.0, extra=_curve(810))
        c = _cards(blk)[2]
        self.assertEqual(_col_i(c, 1, 10), 810)               # FUNCT_IDE
        self.assertAlmostEqual(_col_f(c, 21, 40), 180000.0)   # EINF <- EA
        self.assertAlmostEqual(_col_f(c, 41, 60), 25.0)       # CE   <- COE

    def test_icfld_creates_fail_fld_with_option_dependent_istrain(self):
        """ECHANGE_OPTION 3/5 -> Istrain=2 (engineering + filtering),
        4 -> Istrain=1 (engineering)."""
        for opt, istrain in (("_NLP_FAILURE", 2), ("_NLP2", 1),
                             ("_ECHANGE_NLP_FAILURE", 2)):
            result, starter, _ = self._law43(opt=opt, icfld=900,
                                             extra=_curve(900))
            card = _fail_cards(_block(starter, "/FAIL/FLD/37"))[0]
            self.assertEqual(_i10(card, 0), 900, opt)          # fct_ID
            self.assertEqual(_i10(card, 1), 2, opt)            # Ifail_sh
            self.assertEqual(_col_i(card, 81, 90), istrain, opt)

    def test_strainlt_alpha_drop_is_warned(self):
        """The FORMAT(radioss2019) /FAIL/FLD block a /BEGIN 2022 deck reads has
        no ALPHA column, so the NLP filtering coefficient cannot be carried."""
        result, _, _ = self._law43(opt="_NLP_FAILURE", icfld=900, strainlt=0.02,
                                   extra=_curve(900))
        self.assertTrue(any("STRAINLT=0.02" in w and "DROPPED" in w
                            for w in result.warnings), result.warnings)

    def test_no_icfld_means_no_fail_fld(self):
        _, starter, _ = self._law43()
        self.assertEqual(_blocks(starter, "/FAIL/FLD"), [])

    def test_routed_to_prop_type9(self):
        """LAW43 is shell-only and orthotropic-class -> /PROP/TYPE9 (SH_ORTH),
        which is what dyna2rad also picks."""
        _, starter, _ = self._law43()
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE9")), 1)
        self.assertEqual(_blocks(starter, "/PROP/SHELL"), [])

    def test_zero_r_falls_back_to_von_mises_with_warning(self):
        result, _, blk = self._law43(r=0.0)
        self.assertAlmostEqual(_f20(_cards(blk)[3], 0), 1.0)
        self.assertTrue(any("VON MISES" in w for w in result.warnings))


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_LAMINATED_GLASS (032) -> the LAW27 pair
# ═════════════════════════════════════════════════════════════════════════════

class LaminatedGlassTests(unittest.TestCase):
    """*MAT_032 -> two synthesized /MAT/PLAS_BRIT materials + a layered
    /PROP/TYPE11 that binds them per integration point."""

    def _glass(self, nip=4, **kw):
        section = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, nip) + "\n"
                   + _row(2.0, 2.0, 2.0, 2.0) + "\n")
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*PART\np\n" + _row(7, 7, 32) + "\n" + section
                + _mat032(**kw) + END)
        result, starter = _convert(deck)
        return result, starter

    def test_pair_id_allocation_polymer_keeps_mid(self):
        """dyna2rad's convention: the POLYMER inherits the LS-DYNA MID so
        existing references resolve, the GLASS takes a synthesized id."""
        result, starter = self._glass()
        polymer = _block(starter, "/MAT/LAW27/32")
        self.assertIn("polymer", polymer[1])
        glass = [b for b in _blocks(starter, "/MAT/LAW27/")
                 if b[0] != "/MAT/LAW27/32"]
        self.assertEqual(len(glass), 1)
        self.assertIn("Glass", glass[0][1])
        gid = int(glass[0][0].rsplit("/", 1)[1])
        self.assertGreaterEqual(gid, 90001)      # from the auto-id base

    def test_glass_card_fields(self):
        _, starter = self._glass()
        glass = [b for b in _blocks(starter, "/MAT/LAW27/")
                 if b[0] != "/MAT/LAW27/32"][0]
        c = _cards(glass)
        self.assertAlmostEqual(_f20(c[0], 0), 2.5e-9)        # RHO
        self.assertAlmostEqual(_f20(c[1], 0), 70000.0)       # E  <- EG
        self.assertAlmostEqual(_f20(c[1], 1), 0.23)          # NU <- PRG
        self.assertAlmostEqual(_f20(c[2], 0), 100.0)         # a  <- SYG
        self.assertAlmostEqual(_f20(c[2], 2), 1.0)           # n  = 1
        # EFG -> the brittle-damage ramp EFG / EFG+0.05 / EFG+0.1
        self.assertAlmostEqual(_f20(c[4], 0), 0.01)          # EPS_t1
        self.assertAlmostEqual(_f20(c[4], 1), 0.06)          # EPS_m1
        self.assertAlmostEqual(_f20(c[4], 2), 0.999)         # d_max1
        self.assertAlmostEqual(_f20(c[4], 3), 0.11)          # EPS_f1
        self.assertEqual(c[4], c[5])                         # both directions

    def test_polymer_card_never_fails(self):
        """Only the glass can fail in LS-DYNA; the polymer keeps the LAW27
        never-damage defaults."""
        _, starter = self._glass()
        c = _cards(_block(starter, "/MAT/LAW27/32"))
        self.assertAlmostEqual(_f20(c[1], 0), 3000.0)        # E  <- EP
        self.assertAlmostEqual(_f20(c[1], 1), 0.40)          # NU <- PRP
        self.assertAlmostEqual(_f20(c[2], 0), 20.0)          # a  <- SYP
        # b = plastic modulus H = EP*ETP/(EP-ETP) = 3000*10/2990
        self.assertAlmostEqual(_f20(c[2], 1), 3000.0 * 10.0 / 2990.0, places=6)
        self.assertAlmostEqual(_f20(c[4], 0), 1.0e30)        # EPS_t1
        self.assertAlmostEqual(_f20(c[4], 3), 1.2e30)        # EPS_f1

    def test_f_array_polarity_matches_ls_dyna(self):
        """LS-DYNA: F_i = 0 -> GLASS, F_i = 1 -> POLYMER. dyna2rad's
        SH_SANDW path inverts this AND self-clobbers the /PART mat_ID; its
        *INTEGRATION_SHELL path (used here) gets it right."""
        _, starter = self._glass(nip=4, f=(0.0, 1.0, 1.0, 0.0))
        gid = int([b[0] for b in _blocks(starter, "/MAT/LAW27/")
                   if b[0] != "/MAT/LAW27/32"][0].rsplit("/", 1)[1])
        layers = _cards(_block(starter, "/PROP/TYPE11/"))[4:]
        self.assertEqual([_col_i(ln, 61, 70) for ln in layers],
                         [gid, 32, 32, gid])

    def test_every_polymer_layer_gets_the_polymer(self):
        """dyna2rad rewrites the /PART mat_ID inside the layer loop, so after
        the first polymer layer EVERY later layer becomes polymer too."""
        _, starter = self._glass(nip=4, f=(1.0, 0.0, 1.0, 0.0))
        gid = int([b[0] for b in _blocks(starter, "/MAT/LAW27/")
                   if b[0] != "/MAT/LAW27/32"][0].rsplit("/", 1)[1])
        layers = _cards(_block(starter, "/PROP/TYPE11/"))[4:]
        self.assertEqual([_col_i(ln, 61, 70) for ln in layers],
                         [32, gid, 32, gid])

    def test_layer_thickness_is_the_section_split_evenly(self):
        _, starter = self._glass(nip=4)
        prop = _block(starter, "/PROP/TYPE11/")
        cards = _cards(prop)
        self.assertEqual(_i10(cards[2], 0), 4)                    # N
        self.assertAlmostEqual(_col_f(cards[2], 21, 40), 2.0)     # total Thick
        for ln in cards[4:]:
            self.assertAlmostEqual(_col_f(ln, 21, 40), 0.5)

    def test_f_count_mismatch_is_warned(self):
        result, _ = self._glass(nip=4, f=(0.0, 1.0))
        self.assertTrue(any("F array has 2 entries" in w
                            for w in result.warnings), result.warnings)

    def test_pair_synthesis_is_warned(self):
        result, _ = self._glass()
        self.assertTrue(any("PLAS_BRIT" in w and "PAIR" in w
                            for w in result.warnings), result.warnings)

    def test_glass_mid_does_not_collide_with_a_high_user_mid(self):
        """next_mat_id() must skip a user MID at or above the auto-id base."""
        section = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 2) + "\n"
                   + _row(2.0) + "\n")
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*PART\np\n" + _row(7, 7, 32) + "\n" + section
                + _mat032() + "*MAT_ELASTIC\n"
                + _row(90001, 7.85e-9, 210000.0, 0.3) + "\n" + END)
        _, starter = _convert(deck)
        law27_ids = {b[0] for b in _blocks(starter, "/MAT/LAW27/")}
        self.assertNotIn("/MAT/LAW27/90001", law27_ids)
        self.assertIn("/MAT/ELAST/90001", starter)


# ═════════════════════════════════════════════════════════════════════════════
# *PART_COMPOSITE -> /PROP/TYPE51 + /PROP/TYPE19
# ═════════════════════════════════════════════════════════════════════════════

def _part_composite(kw="*PART_COMPOSITE_TITLE", pid=7, elform=2, shrf=1.0,
                    nloc=0.0, marea=0.0, plies=((2, 0.3, 0.0), (2, 0.4, 45.0),
                                                (2, 0.5, -45.0)),
                    contact=False, long_form=False, optcard=0):
    out = kw + "\ncarbon layup\n"
    if optcard:
        out += f"{'OPTCARD':<10}{optcard:>10}\n"
    out += _row(pid, elform, shrf, nloc, marea) + "\n"
    if contact:
        out += _row(0.2, 0.2, 0.0, 0.0, 1.5) + "\n"
    if long_form:
        for (m, t, b) in plies:
            out += _row(m, t, b, 0, 0, 0.0) + "\n"
    else:
        for k in range(0, len(plies), 2):
            pair = plies[k:k + 2]
            fields = []
            for (m, t, b) in pair:
                fields += [m, t, b, 0]
            out += _row(*fields) + "\n"
    return out


class PartCompositeTests(unittest.TestCase):
    """*PART_COMPOSITE -> /PROP/TYPE51 (stack) + one /PROP/TYPE19 per ply."""

    def _pc(self, mat=None, **kw):
        deck = ("*KEYWORD\n" + NODES + SHELL + _part_composite(**kw)
                + (mat if mat is not None else _mat002()) + END)
        result, starter = _convert(deck)
        return result, starter

    def test_ply_order_thickness_and_angle(self):
        """Layers run bottom -> top; each ply's B_i becomes the /PROP/TYPE19
        delta_phi."""
        _, starter = self._pc()
        stack = _block(starter, "/PROP/TYPE51/")
        ply_lines = [ln for ln in _cards(stack)[4:] if ln.strip()]
        ply_ids = [_i10(ln, 0) for ln in ply_lines]
        self.assertEqual(len(ply_ids), 3)
        expected = ((2, 0.3, 0.0), (2, 0.4, 45.0), (2, 0.5, -45.0))
        for pid19, (mid, thick, beta) in zip(ply_ids, expected):
            card = _cards(_block(starter, f"/PROP/TYPE19/{pid19}"))[0]
            self.assertEqual(_col_i(card, 1, 10), mid)
            self.assertAlmostEqual(_col_f(card, 11, 30), thick)
            self.assertAlmostEqual(_col_f(card, 31, 50), beta)
            self.assertEqual(_col_i(card, 51, 60), 0)      # grsh4n_ID
            self.assertEqual(_col_i(card, 61, 70), 0)      # grsh3n_ID
            self.assertEqual(_col_i(card, 71, 80), 1)      # Npt_ply

    def test_each_ply_takes_two_lines(self):
        """The TYPE51 importer counts free cards and divides by two
        (Phi_Zi_Size = _GET_NB_FREE_CARDS() / 2), so the blank second line is
        mandatory — omitting it halves the ply count silently."""
        _, starter = self._pc()
        ply_block = _cards(_block(starter, "/PROP/TYPE51/"))[4:]
        self.assertEqual(len(ply_block), 6)
        for k in range(0, 6, 2):
            self.assertTrue(ply_block[k].strip())
            self.assertEqual(ply_block[k + 1].strip(), "")

    def test_part_is_repointed_and_section_prop_suppressed(self):
        _, starter = self._pc()
        part = _block(starter, "/PART/7")
        prop_ref = _i10(_cards(part)[0], 0)
        stack_id = int(_block(starter, "/PROP/TYPE51/")[0].rsplit("/", 1)[1])
        self.assertEqual(prop_ref, stack_id)
        self.assertEqual(_blocks(starter, "/PROP/SHELL"), [])

    def test_mesh_is_preserved(self):
        """A *PART_COMPOSITE that produced no *PART record would take its whole
        mesh with it — elements are emitted inside the state.parts loop."""
        _, starter = self._pc()
        self.assertEqual(len(_blocks(starter, "/SHELL/7")), 1)
        self.assertIn("/PART/7", starter)

    def test_ishell_from_elform(self):
        """ELFORM -16 / 9 are the fully-integrated forms -> Ishell 12 (QBAT);
        everything else -> 24 (QEPH)."""
        for elform, ishell in ((2, 24), (16, 24), (-16, 12), (9, 12)):
            _, starter = self._pc(elform=elform)
            card1 = _cards(_block(starter, "/PROP/TYPE51/"))[0]
            self.assertEqual(_i10(card1, 0), ishell, f"ELFORM={elform}")

    def test_nloc_maps_to_ipos(self):
        """NLOC 0 = mid-surface (Ipos 0), -1 = bottom (Ipos 4), +1 = top (3)."""
        for nloc, ipos in ((0.0, 0), (-1.0, 4), (1.0, 3)):
            _, starter = self._pc(nloc=nloc)
            card4 = _cards(_block(starter, "/PROP/TYPE51/"))[3]
            self.assertEqual(_col_i(card4, 81, 90), ipos, f"NLOC={nloc}")

    def test_shrf_maps_to_ashear(self):
        for shrf, ashear in ((1.0, 1.0), (0.833333, 0.833333), (0.0, 0.833333)):
            _, starter = self._pc(shrf=shrf)
            card3 = _cards(_block(starter, "/PROP/TYPE51/"))[2]
            self.assertAlmostEqual(_col_f(card3, 21, 40), ashear, places=6)

    def test_missing_ply_padding_is_skipped_without_dropping_the_last(self):
        """THICK=0 with MID=-1 is LS-DYNA's alignment padding. dyna2rad shrinks
        NIP but still walks the LEADING indices, so a hole in the MIDDLE drops
        the LAST ply instead."""
        plies = ((2, 0.3, 0.0), (-1, 0.0, 0.0), (2, 0.5, 90.0))
        result, starter = self._pc(plies=plies)
        stack = [ln for ln in _cards(_block(starter, "/PROP/TYPE51/"))[4:]
                 if ln.strip()]
        self.assertEqual(len(stack), 2)
        last = _cards(_block(starter, f"/PROP/TYPE19/{_i10(stack[1], 0)}"))[0]
        self.assertAlmostEqual(_col_f(last, 11, 30), 0.5)     # the LAST ply
        self.assertAlmostEqual(_col_f(last, 31, 50), 90.0)
        self.assertTrue(any("missing ply" in w for w in result.warnings))

    def test_long_form_one_ply_per_line(self):
        _, starter = self._pc(kw="*PART_COMPOSITE_LONG", long_form=True)
        stack = [ln for ln in _cards(_block(starter, "/PROP/TYPE51/"))[4:]
                 if ln.strip()]
        self.assertEqual(len(stack), 3)

    def test_contact_variant_reads_the_extra_card(self):
        """_CONTACT inserts card 4 before the layup — mis-reading it would make
        the first ply's MID come out as FS."""
        result, starter = self._pc(kw="*PART_COMPOSITE_CONTACT", contact=True)
        stack = [ln for ln in _cards(_block(starter, "/PROP/TYPE51/"))[4:]
                 if ln.strip()]
        self.assertEqual(len(stack), 3)
        first = _cards(_block(starter, f"/PROP/TYPE19/{_i10(stack[0], 0)}"))[0]
        self.assertEqual(_col_i(first, 1, 10), 2)
        self.assertTrue(any("OPTT=1.5" in w for w in result.warnings))

    def test_optcard_is_read_and_irpl_warned(self):
        result, starter = self._pc(optcard=103)
        stack = [ln for ln in _cards(_block(starter, "/PROP/TYPE51/"))[4:]
                 if ln.strip()]
        self.assertEqual(len(stack), 3)
        self.assertTrue(any("IRPL=103" in w for w in result.warnings))

    def test_marea_is_warn_dropped(self):
        result, _ = self._pc(marea=1.5e-6)
        self.assertTrue(any("MAREA=1.5e-06" in w for w in result.warnings),
                        result.warnings)

    def test_tshell_variant_keeps_the_mesh_and_falls_back(self):
        """An unsupported variant must never lose the part's elements, and the
        fallback property must carry the SUMMED layup thickness — a
        *PART_COMPOSITE has no *SECTION to inherit one from, so the plain
        auto-section would be zero-thickness (which the starter rejects)."""
        result, starter = self._pc(kw="*PART_COMPOSITE_TSHELL")
        self.assertIn("/PART/7", starter)
        self.assertEqual(len(_blocks(starter, "/SHELL/7")), 1)
        self.assertEqual(_blocks(starter, "/PROP/TYPE51"), [])
        # ply-0's material is MAT_002, so the fallback is still orthotropic
        prop = _block(starter, "/PROP/TYPE11/")
        self.assertAlmostEqual(_col_f(_cards(prop)[2], 21, 40), 1.2)
        self.assertTrue(any("TSHELL" in w and "still emitted" in w
                            for w in result.warnings), result.warnings)
        self.assertEqual(result.skipped_keywords, [])

    def test_unsupported_variant_with_isotropic_plies_falls_back_to_prop_shell(self):
        """With no orthotropic ply material there is nothing to repoint, so the
        part lands on a plain /PROP/SHELL carrying the summed thickness."""
        iso = "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
        result, starter = self._pc(kw="*PART_COMPOSITE_TSHELL", mat=iso)
        self.assertEqual(_blocks(starter, "/PROP/TYPE51"), [])
        self.assertEqual(len(_blocks(starter, "/SHELL/7")), 1)
        prop = _block(starter, "/PROP/SHELL/7")
        self.assertAlmostEqual(_col_f(_cards(prop)[2], 21, 40), 1.2)

    def test_no_valid_plies_keeps_the_mesh(self):
        iso = "*MAT_ELASTIC\n" + _row(2, 7.85e-9, 210000.0, 0.3) + "\n"
        result, starter = self._pc(plies=((-1, 0.0, 0.0),), mat=iso)
        self.assertIn("/PART/7", starter)
        self.assertEqual(len(_blocks(starter, "/SHELL/7")), 1)
        self.assertTrue(any("no valid plies" in w for w in result.warnings),
                        result.warnings)

    def test_title_option_and_plain_keyword_both_dispatch(self):
        for kw in ("*PART_COMPOSITE", "*PART_COMPOSITE_TITLE"):
            state = _dispatch("*KEYWORD\n" + _part_composite(kw=kw) + "*END\n")
            self.assertIn(7, state.part_composites, kw)
            self.assertIn(7, state.parts, kw)
            self.assertEqual(state.part_composites[7].title, "carbon layup", kw)

    def test_existing_part_record_is_not_overwritten(self):
        """A deck that ALSO declares the part via *PART keeps that record."""
        state = _dispatch("*KEYWORD\n*PART\nplain\n" + _row(7, 3, 9) + "\n"
                          + _part_composite() + "*END\n")
        self.assertEqual(state.parts[7].secid, 3)
        self.assertEqual(state.parts[7].mid, 9)

    def test_ply_material_not_in_deck_is_warned(self):
        result, _ = self._pc(plies=((2, 0.3, 0.0), (4242, 0.4, 0.0)))
        self.assertTrue(any("ply material 4242" in w for w in result.warnings),
                        result.warnings)

    def test_ply_prop_ids_are_unique_and_distinct_from_the_stack(self):
        _, starter = self._pc()
        stack_id = int(_block(starter, "/PROP/TYPE51/")[0].rsplit("/", 1)[1])
        ply_ids = [int(b[0].rsplit("/", 1)[1])
                   for b in _blocks(starter, "/PROP/TYPE19/")]
        self.assertEqual(len(set(ply_ids)), 3)
        self.assertNotIn(stack_id, ply_ids)

    def test_multiple_composite_parts_do_not_share_properties(self):
        nodes = ("*NODE\n"
                 + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                     (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
                     (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
                     (5, 20.0, 0.0, 0.0), (6, 20.0, 10.0, 0.0))))
        shells = ("*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
                  + _row(2, 8, 2, 5, 6, 3) + "\n")
        deck = ("*KEYWORD\n" + nodes + shells
                + _part_composite(pid=7)
                + _part_composite(pid=8, plies=((2, 1.0, 30.0),))
                + _mat002() + END)
        result, starter = _convert(deck)
        stacks = _blocks(starter, "/PROP/TYPE51/")
        self.assertEqual(len(stacks), 2)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE19/")), 4)
        refs = {b[0]: _i10(_cards(b)[0], 0)
                for b in _blocks(starter, "/PART/")}
        self.assertEqual(len(set(refs.values())), 2)


# ═════════════════════════════════════════════════════════════════════════════
# AOPT -> orthotropy axes
# ═════════════════════════════════════════════════════════════════════════════

class CompositeAoptTests(unittest.TestCase):
    """Every AOPT branch is either converted or loudly warned, on both the
    layered shell (/PROP/TYPE11) and the stack (/PROP/TYPE51)."""

    def _prop(self, **kw):
        deck = ("*KEYWORD\n" + NODES + SHELL + PART + SECTION
                + _mat002(**kw) + END)
        result, starter = _convert(deck)
        return result, starter, _block(starter, "/PROP/TYPE11/")

    def test_aopt0_uses_element_connectivity(self):
        """LS-DYNA AOPT=0 takes the axes from element nodes 1,2,4 — Radioss
        Ip=20 is exactly that convention, so it is an exact match."""
        result, _, blk = self._prop(aopt=0.0, beta=12.0)
        card4 = _cards(blk)[3]
        self.assertEqual(_col_i(card4, 91, 100), 20)      # Ip
        self.assertEqual(_col_i(card4, 61, 70), 0)        # no skew
        # BETA rides on every layer's Phi
        for ln in _cards(blk)[4:]:
            self.assertAlmostEqual(_col_f(ln, 1, 20), 12.0)

    def test_aopt2_builds_a_skew_whose_x_axis_is_the_a_vector(self):
        """/SKEW/FIX's two vector cards are the LOCAL Y and Z axes; the starter
        rebuilds X' = Y' x Z'. Reconstruct it here and compare against a."""
        a = (1.0, 1.0, 0.0)
        d = (0.0, 1.0, 0.0)
        result, starter, blk = self._prop(aopt=2.0, a=a, d=d, beta=15.0)
        card4 = _cards(blk)[3]
        self.assertEqual(_col_i(card4, 91, 100), 22)      # Ip = skew + phi
        skew_id = _col_i(card4, 61, 70)
        self.assertGreater(skew_id, 0)
        for i in range(3):                                # V ignored under Ip=22
            self.assertAlmostEqual(_f20(card4, i), 0.0)
        skew = _cards(_block(starter, f"/SKEW/FIX/{skew_id}"))
        yv = [_f20(skew[1], i) for i in range(3)]
        zv = [_f20(skew[2], i) for i in range(3)]
        xv = (yv[1] * zv[2] - yv[2] * zv[1],
              yv[2] * zv[0] - yv[0] * zv[2],
              yv[0] * zv[1] - yv[1] * zv[0])
        norm = math.sqrt(sum(c * c for c in a))
        for got, want in zip(xv, (a[0] / norm, a[1] / norm, a[2] / norm)):
            self.assertAlmostEqual(got, want, places=6)
        # ...and the triad is right-handed and orthonormal
        self.assertAlmostEqual(sum(y * z for y, z in zip(yv, zv)), 0.0, places=9)
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in yv)), 1.0, places=6)
        for ln in _cards(blk)[4:]:
            self.assertAlmostEqual(_col_f(ln, 1, 20), 15.0)
        self.assertTrue(any("AOPT=2" in w and "/SKEW/FIX" in w
                            for w in result.warnings), result.warnings)

    def test_aopt2_z_axis_is_a_cross_d(self):
        """With d supplied the frame is LS-DYNA's own: X'=a, Z'=a x d."""
        a, d = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        _, starter, blk = self._prop(aopt=2.0, a=a, d=d)
        skew_id = _col_i(_cards(blk)[3], 61, 70)
        skew = _cards(_block(starter, f"/SKEW/FIX/{skew_id}"))
        zv = [_f20(skew[2], i) for i in range(3)]
        for got, want in zip(zv, (0.0, 0.0, 1.0)):        # a x d = +Z
            self.assertAlmostEqual(got, want, places=9)

    def test_aopt3_puts_the_v_vector_on_the_property(self):
        v = (0.0, 1.0, 0.0)
        result, _, blk = self._prop(aopt=3.0, v=v, beta=30.0)
        card4 = _cards(blk)[3]
        self.assertEqual(_col_i(card4, 91, 100), 23)      # Ip = V + phi
        self.assertEqual(_col_i(card4, 61, 70), 0)        # skew ignored
        for i, want in enumerate(v):
            self.assertAlmostEqual(_f20(card4, i), want)
        for ln in _cards(blk)[4:]:
            self.assertAlmostEqual(_col_f(ln, 1, 20), 30.0)

    def test_negative_aopt_binds_the_define_coordinate_skew(self):
        """dyna2rad's AOPT<0 branch on TYPE51 is DEAD CODE (axisOptFlag is never
        negative after the cfg enum remap), so a *DEFINE_COORDINATE system is
        silently lost there. It must bind here."""
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _row(77, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _row(0.0, 1.0, 0.0) + "\n")
        deck = ("*KEYWORD\n" + NODES + SHELL + PART + SECTION + coord
                + _mat002(aopt=-77.0) + END)
        result, starter = _convert(deck)
        card4 = _cards(_block(starter, "/PROP/TYPE11/"))[3]
        self.assertEqual(_col_i(card4, 61, 70), 77)       # skew_ID = |AOPT|
        self.assertEqual(_col_i(card4, 91, 100), 0)       # Ip=0 -> skew axis 1
        self.assertTrue(any("DEFINE_COORDINATE" in w for w in result.warnings))

    def test_negative_aopt_with_undefined_cid_warns_and_falls_back(self):
        result, _, blk = self._prop(aopt=-88.0)
        card4 = _cards(blk)[3]
        self.assertEqual(_col_i(card4, 61, 70), 0)
        self.assertEqual(_col_i(card4, 91, 100), 20)
        self.assertTrue(any("NOT defined in the deck" in w
                            for w in result.warnings), result.warnings)

    def test_aopt1_and_4_on_a_shell_warn_and_fall_back(self):
        """AOPT=1 (point) and 4 (cylindrical) have no single global in-plane
        direction on a shell."""
        for aopt in (1.0, 4.0):
            result, _, blk = self._prop(aopt=aopt, v=(1.0, 0.0, 0.0))
            card4 = _cards(blk)[3]
            self.assertEqual(_col_i(card4, 91, 100), 20, f"AOPT={aopt}")
            self.assertTrue(any("ELEMENT frame" in w for w in result.warnings),
                            f"AOPT={aopt}: {result.warnings}")

    def test_aopt2_with_null_a_vector_warns(self):
        result, _, blk = self._prop(aopt=2.0, a=(0.0, 0.0, 0.0))
        self.assertEqual(_col_i(_cards(blk)[3], 91, 100), 20)
        self.assertTrue(any("a-vector is null" in w for w in result.warnings),
                        result.warnings)

    def test_mat054_mangle_is_the_axis_rotation(self):
        """MAT_054's card-3 field 7 is MANGLE (the material-angle offset), while
        its card-6 BETA is the shear-term weighting — different quantities.
        dyna2rad never reads MANGLE at all."""
        deck = ("*KEYWORD\n" + NODES + SHELL + "*PART\np\n" + _row(7, 7, 54)
                + "\n" + SECTION
                + _mat054(aopt=3.0, v=(1.0, 0.0, 0.0), mangle=30.0) + END)
        result, starter = _convert(deck)
        blk = _block(starter, "/PROP/TYPE11/")
        self.assertEqual(_col_i(_cards(blk)[3], 91, 100), 23)
        for ln in _cards(blk)[4:]:
            self.assertAlmostEqual(_col_f(ln, 1, 20), 30.0)
        # BETA (0.5) stays on the material as the shear weighting
        mat = _cards(_block(starter, "/MAT/LAW127/54"))
        self.assertAlmostEqual(_col_f(mat[10], 21, 40), 0.5)

    def test_negative_beta_is_applied_not_dropped(self):
        """dyna2rad applies BETA only when > 0, silently losing a negative
        rotation, which is a legal LS-DYNA angle."""
        _, _, blk = self._prop(aopt=3.0, v=(1.0, 0.0, 0.0), beta=-20.0)
        for ln in _cards(blk)[4:]:
            self.assertAlmostEqual(_col_f(ln, 1, 20), -20.0)

    def test_skew_id_avoids_the_shared_skew_frame_namespace(self):
        """/SKEW and /FRAME share ONE starter id namespace — a clash is
        ERROR 79 DUPLICATE ID."""
        coord = ("*DEFINE_COORDINATE_SYSTEM\n"
                 + _row(90003, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0) + "\n"
                 + _row(0.0, 1.0, 0.0) + "\n")
        deck = ("*KEYWORD\n" + NODES + SHELL + PART + SECTION + coord
                + _mat002(aopt=2.0, a=(1.0, 0.0, 0.0)) + END)
        _, starter = _convert(deck)
        ids = [b[0] for b in _blocks(starter, "/SKEW/")]
        self.assertEqual(len(ids), len(set(ids)))
        card4 = _cards(_block(starter, "/PROP/TYPE11/"))[3]
        self.assertNotEqual(_col_i(card4, 61, 70), 90003)

    def test_solid_orthotropic_part_gets_prop_type6(self):
        """MAT_002 on bricks -> /PROP/TYPE6 (SOL_ORTH); /PROP/SOLID is
        isotropic-class and the starter rejects it (ERROR 3047)."""
        deck = ("*KEYWORD\n" + SOLID_NODES + BRICK
                + "*PART\nbrick\n" + _row(7, 7, 2) + "\n" + SECTION_SOLID
                + _mat002(aopt=2.0, a=(1.0, 0.0, 0.0), d=(0.0, 1.0, 0.0))
                + END)
        result, starter = _convert(deck)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE6")), 1)
        self.assertEqual(_blocks(starter, "/PROP/SOLID"), [])
        card3 = _cards(_block(starter, "/PROP/TYPE6/"))[2]
        self.assertGreater(_col_i(card3, 61, 70), 0)       # skew_ID
        self.assertEqual(_col_i(card3, 71, 80), 0)         # Ip = 0 (use skew)


# ═════════════════════════════════════════════════════════════════════════════
# Property routing / regression
# ═════════════════════════════════════════════════════════════════════════════

class CompositeRoutingTests(unittest.TestCase):

    def test_shared_section_keeps_its_prop_when_one_part_is_plain(self):
        """A *SECTION_SHELL used by BOTH a composite and an ordinary part must
        keep its isotropic /PROP/SHELL for the ordinary one."""
        nodes = ("*NODE\n"
                 + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
                     (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0),
                     (3, 10.0, 10.0, 0.0), (4, 0.0, 10.0, 0.0),
                     (5, 20.0, 0.0, 0.0), (6, 20.0, 10.0, 0.0))))
        shells = ("*ELEMENT_SHELL\n" + _row(1, 7, 1, 2, 3, 4) + "\n"
                  + _row(2, 8, 2, 5, 6, 3) + "\n")
        deck = ("*KEYWORD\n" + nodes + shells
                + "*PART\northo\n" + _row(7, 7, 2) + "\n"
                + "*PART\nplain\n" + _row(8, 7, 3) + "\n" + SECTION
                + _mat002()
                + "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
                + END)
        _, starter = _convert(deck)
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/7")), 1)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE11")), 1)
        self.assertEqual(_i10(_cards(_block(starter, "/PART/8"))[0], 0), 7)

    def test_composite_material_wins_over_the_hourglass_split(self):
        """The three /PROP-split prepasses are mutually exclusive; a composite
        part must not also be claimed by the per-part hourglass overlay."""
        deck = ("*KEYWORD\n" + NODES + SHELL
                + "*PART\northo\n" + _row(7, 7, 2, 0, 5) + "\n" + SECTION
                + "*HOURGLASS\n" + _row(5, 4, 0.05) + "\n"
                + _mat002() + END)
        _, starter = _convert(deck)
        prop_ref = _i10(_cards(_block(starter, "/PART/7"))[0], 0)
        stack_id = int(_block(starter, "/PROP/TYPE11/")[0].rsplit("/", 1)[1])
        self.assertEqual(prop_ref, stack_id)

    def test_composite_material_on_a_meshless_part_warns(self):
        deck = ("*KEYWORD\n" + NODES
                + "*PART\northo\n" + _row(7, 7, 2) + "\n" + SECTION
                + _mat002() + END)
        result, starter = _convert(deck)
        self.assertEqual(_blocks(starter, "/PROP/TYPE11"), [])
        self.assertTrue(any("no shell or solid elements" in w
                            for w in result.warnings), result.warnings)

    def test_law43_on_solids_is_warned_as_shell_only(self):
        deck = ("*KEYWORD\n" + SOLID_NODES + BRICK
                + "*PART\nbrick\n" + _row(7, 7, 37) + "\n" + SECTION_SOLID
                + _mat037() + END)
        result, _ = _convert(deck)
        self.assertTrue(any("SHELL-ONLY law" in w for w in result.warnings),
                        result.warnings)

    def test_nip_above_ten_is_clamped(self):
        section = ("*SECTION_SHELL\n" + _row(7, 2, 1.0, 16) + "\n"
                   + _row(1.6) + "\n")
        deck = ("*KEYWORD\n" + NODES + SHELL + PART + section + _mat002() + END)
        result, starter = _convert(deck)
        cards = _cards(_block(starter, "/PROP/TYPE11/"))
        self.assertEqual(_i10(cards[2], 0), 10)
        self.assertEqual(len(cards) - 4, 10)
        self.assertTrue(any("CLAMPED to 10" in w for w in result.warnings))

    def test_layer_thicknesses_sum_to_the_section_thickness(self):
        _, starter = _convert("*KEYWORD\n" + NODES + SHELL + PART + SECTION
                              + _mat002() + END)
        cards = _cards(_block(starter, "/PROP/TYPE11/"))
        total = _col_f(cards[2], 21, 40)
        self.assertAlmostEqual(total, 1.2)
        self.assertAlmostEqual(sum(_col_f(ln, 21, 40) for ln in cards[4:]),
                               total, places=9)


class CompositeRegressionTests(unittest.TestCase):
    """The batch adds no flag and no behaviour on a deck without composites."""

    def test_plain_deck_emits_no_composite_cards(self):
        deck = ("*KEYWORD\n" + NODES + SHELL + "*PART\np\n" + _row(7, 7, 3)
                + "\n" + SECTION
                + "*MAT_ELASTIC\n" + _row(3, 7.85e-9, 210000.0, 0.3) + "\n"
                + END)
        result, starter = _convert(deck)
        for kw in ("/MAT/LAW93", "/MAT/LAW127", "/MAT/LAW43", "/MAT/LAW27",
                   "/PROP/TYPE11", "/PROP/TYPE51", "/PROP/TYPE19",
                   "COMPOSITE MATERIALS", "COMPOSITE PROPERTIES"):
            self.assertNotIn(kw, starter, kw)
        self.assertEqual(len(_blocks(starter, "/PROP/SHELL/7")), 1)

    def test_goldens_are_unchanged(self):
        """No checked-in fixture contains a composite card, so all five golden
        decks must still match byte-for-byte (asserted again here, per repo
        policy for a no-flag feature)."""
        from tests import test_golden
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(test_golden)
        result = unittest.TextTestRunner(
            stream=open(os.devnull, "w"), verbosity=0).run(suite)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])


if __name__ == "__main__":
    unittest.main()
