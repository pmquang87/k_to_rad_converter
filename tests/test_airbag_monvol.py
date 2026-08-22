"""The AIRBAG / MONVOL batch 1:

  *MAT_FABRIC (*MAT_034)              -> /MAT/LAW19 + /PROP/TYPE9, or
                                         /MAT/LAW58 + /PROP/TYPE16
  *AIRBAG_SIMPLE_PRESSURE_VOLUME      -> /MONVOL/PRES
  *AIRBAG_SIMPLE_AIRBAG_MODEL         -> /MONVOL/AIRBAG1 + /MAT/GAS + /PROP/INJECT1
  *AIRBAG_ADIABATIC_GAS_MODEL         -> /MONVOL/GAS
  *AIRBAG_LOAD_CURVE                  -> /MONVOL/PRES (Itypfun = 1)
  *AIRBAG_LINEAR_FLUID                -> /MONVOL/LFLUID
  *AIRBAG_REFERENCE_GEOMETRY          -> /XREF per owning part
  *AIRBAG_SHELL_REFERENCE_GEOMETRY    -> /EREF/SHELL + /EREF/SH3N per part
  *CONTACT_AIRBAG_SINGLE_SURFACE      -> /INTER/TYPE25, or /INTER/TYPE19 on the
                                         dyna2rad SOFT = -19 sentinel
  *DATABASE_ABSTAT                    -> /TH/MONV over the emitted /MONVOLs

Everything below is asserted by COLUMN, because that is the only way any of it
is visible in the .rad. The conventions that carry the most risk, and why each
is pinned by a test:

* **The external surface must be ELEMENT-BACKED.** ``/SURF/SEG`` is starter
  ``ERROR 18`` ("SURFACE ID: %d IS NOT DEFINED WITH SHELLS") plus ``ERROR 54``,
  and the run aborts — ``check_surf.F:55-62`` sets ``ISH4N3N`` only for ELTYP 3
  and 7, and a segment surface never resolves back to an element at all
  (``tsurftag.F:293`` passes ``0, 0``). A ``SIDTYP=0`` deck names a
  *SET_SEGMENT, which is the COMMON case, so the segments are resolved to their
  owning shells and the surface is built from those.
* **``/PROP/INJECT1 Iflow`` must be 1.** LS-DYNA's LCID is a mass FLOW RATE
  ("Load curve ID specifying input mass flow rate", Vol I R16 p.3-13); with
  ``Iflow = 0`` the engine reads the same curve as an ACCUMULATED MASS and
  DIFFERENCES it (``airbaga1.F:349-362``: ``DGMASS = GMASS - GMASS_OLD``). No
  starter diagnostic, a factor-of-1/dt error.
* **``Itypfun`` decides what the pressure function's abscissa IS.**
  ``volpfv.F:61-88``: 0 -> ``V0/V``, 1 -> ``t``, 2 -> ``V/V0``, 3 -> ``t`` with
  the result multiplied by ``V0/V``. LS-DYNA's SPV law is ``p = BETA*CN/(V/V0)``,
  which is ``Itypfun = 0`` with ``Fscale = BETA*CN`` on a unit-slope function —
  exactly, with no assumption about V0. dyna2rad instead bakes ``BETA*CN*x``
  into a 27-point table, which is only right when V0 == 1 in deck units.
* **Gauge vs absolute.** ``*AIRBAG_ADIABATIC_GAS_MODEL``'s P0 is a GAUGE
  pressure (Vol I p.3-18, ``e_0 = (p_0 + p_e)/(rho(gamma-1))``) and Radioss
  ``Pini`` is absolute, so ``Pini = P0 + PE``. dyna2rad writes ``PSF*P0`` and
  adds no PE.
* **``/MAT/GAS`` carries a Cp POLYNOMIAL and derives Cv.**
  ``hm_read_monvol_type7.F`` forms ``CVI = CPI - R/MW``, so writing LS-DYNA's CV
  into a Cp slot inverts the gas. CV != 0 -> ``/MAT/GAS/CSTA`` (Cp | Cv
  verbatim); CV == 0 -> ``/MAT/GAS/MASS`` with ``Cpa = A/MW``, ``Cpb = B/MW``
  (LS-DYNA's A/B are MOLAR, Vol I p.3-16 Remark 3).
* **``/MAT/LAW19`` card 4 columns 21-40 are a DEAD SLOT** the reader never
  touches; ZEROSTRESS is at 41-60. And ``/PROP/TYPE9`` card 4 columns 81-90 are
  BLANK at /BEGIN 2022 but become ``Ipos`` at 2024+ with no warning either way,
  so nothing may be written there. ``Ip`` is at 91-100 at every version.
* **The law and the property are ONE decision.** /MAT/LAW19 declares
  ``SHELL_ORTHOTROPIC`` (PROP_SHELL 2) and /MAT/LAW58 ``SHELL_ANISOTROPIC``
  (PROP_SHELL 4); ``check_mat_elem_prop_compatibility.F:174-197`` accepts the
  first only on IGTYP 9 and the second only on IGTYP 16. Either crossing — or
  leaving the fabric on the isotropic /PROP/SHELL its *SECTION_SHELL gives it —
  is ``ERROR 3047`` and refuses the whole deck.
* **The mesh survives every AIRBAG spelling.** An unregistered
  ``*AIRBAG_WANG_NEFSKE`` must not take its deck's parts and elements with it,
  and must not vanish into ``skipped_keywords`` unnamed.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                              # noqa: E402
from k2rad.assembly import _OFFSET_SPECS, _offset_block  # noqa: E402
from k2rad.handlers import HANDLERS, dispatch          # noqa: E402
from k2rad.parser import parse_k_file                  # noqa: E402
from k2rad.state import ConversionState                # noqa: E402
from k2rad.writer.fabric import _fabric_law            # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

def _convert(deck: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


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
    """A block's DATA lines: after the title, comments removed."""
    return [ln for ln in block[2:] if not ln.startswith("#")]


def _col_f(line: str, a: int, b: int) -> float:
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _warns(result, needle: str):
    return [w for w in result.warnings if needle in w]


# ── Deck fragments ───────────────────────────────────────────────────────────

#: Four nodes / one quad — the smallest thing a fabric part can be.
_MESH_ONE_QUAD = """\
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
*PART
fabric part
         1         1         3
*SECTION_SHELL
         1         9       1.0         4         1         0         0         1
     0.381     0.381     0.381     0.381
"""

#: A CLOSED box of six quads on eight nodes — the smallest surface a /MONVOL
#: can measure a volume of (1000 mm^3). Node order is deliberately mixed so
#: the closure/volume diagnostic is exercised on a real, non-trivial bag.
_MESH_CLOSED_BOX = """\
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5             0.0             0.0            10.0
       6            10.0             0.0            10.0
       7            10.0            10.0            10.0
       8             0.0            10.0            10.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       5       6       7       8
       3       1       1       2       6       5
       4       1       2       3       7       6
       5       1       3       4       8       7
       6       1       4       1       5       8
*PART
bag
         1         1         1
*SECTION_SHELL
         1         2       1.0         2         1         0         0         1
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*SET_PART_LIST
         7       0.0       0.0       0.0       0.0MECH
         1
"""

_TERM = """\
*CONTROL_TERMINATION
     0.001
*END
"""


def _c10(v) -> str:
    """One 10-column LS-DYNA cell, at the most precision that fits.

    ``f"{v:>10.6g}"`` would truncate 13789.5146 to ``13789.5`` — an artefact of
    the TEST deck, not of the converter, that silently weakens every column
    assertion made against it.
    """
    if isinstance(v, int):
        return f"{v:>10d}"
    for prec in range(10, 0, -1):
        s = f"{v:.{prec}g}"
        if len(s) <= 10:
            return f"{s:>10}"
    return f"{v:>10.3E}"[:10]


def _fabric_mat(form=0, cse=0.0, curves=(), damp=0.0, aopt=0.0,
                beta=0.0, v=(0.0, 0.0, 0.0), fvopt=0.0, rgbrth=0.0,
                tsrfac=0.0, eb=13789.5146, gab=10548.9787,
                prba=0.35, prab=0.35, lratio=0.0):
    """A *MAT_FABRIC card stack with the conditional cards switched on/off the
    way LS-DYNA switches them (card 4 on FVOPT<0, card 7 on the FORM set)."""
    c = _c10
    out = ["*MAT_FABRIC",
           c(3) + c(1.0687e-9) + c(13789.5146) + c(eb)
           + f"{'':>10}" + c(prba) + c(prab),
           c(gab) + f"{'':>20}" + c(cse) + c(0.0) + c(0.0) + c(lratio)
           + c(damp),
           c(aopt) + c(0.0) + c(0.0) + c(0.0) + c(0.0) + c(form) + c(fvopt)
           + c(tsrfac)]
    if fvopt < 0.0:
        out.append(c(1.0) + c(2.0) + c(3.0) + c(4.0) + c(5.0))
    out.append(f"{'':>10}" + c(rgbrth) + c(0.0) + c(1.0) + c(0.0) + c(0.0)
               + c(0.0) + c(0.0))
    out.append(c(v[0]) + c(v[1]) + c(v[2]) + f"{'':>30}" + c(beta) + c(0))
    if form in (4, 14, -14, 24):
        cs = list(curves) + [0] * 6
        out.append("".join(c(int(x)) for x in cs[:6]) + c(0.0))
    if form == -14:
        out.append(c(0) + c(0) + c(0.0) + c(0.0) + f"{'':>10}"
                   + c(0.0) + c(0.0) + c(0.0))
    return "\n".join(out) + "\n"


_CURVES_3 = """\
*DEFINE_CURVE
       101
                 0.0                 0.0
                 0.1              1000.0
*DEFINE_CURVE
       102
                 0.0                 0.0
                 0.1              1200.0
*DEFINE_CURVE
       103
                 0.0                 0.0
                 0.5               300.0
"""


# ═════════════════════════════════════════════════════════════════════════════
# *MAT_FABRIC -> /MAT/LAW19 + /PROP/TYPE9
# ═════════════════════════════════════════════════════════════════════════════

class TestFabricLaw19(unittest.TestCase):

    def _law19_deck(self, **kw):
        return ("*KEYWORD\n" + _MESH_ONE_QUAD + _fabric_mat(**kw) + _TERM)

    def test_law19_card_columns(self):
        """Every /MAT/LAW19 cell, by column, with hand-computed values."""
        _r, starter, _e = _convert(self._law19_deck())
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertEqual(len(cards), 4)
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 1.0687e-9)
        # card 2: E11 | E22 | NU12
        self.assertAlmostEqual(_col_f(cards[1], 1, 20), 13789.5146)
        self.assertAlmostEqual(_col_f(cards[1], 21, 40), 13789.5146)
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 0.35)
        # card 3: G12 | G23 | G31 — GBC/GCA blank, so both fall back to GAB
        for a, b in ((1, 20), (21, 40), (41, 60)):
            self.assertAlmostEqual(_col_f(cards[2], a, b), 10548.9787)
        # card 4: R_E | <DEAD 21-40> | ZEROSTRESS | FSCALE_POR | SENS_ID
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 1.0)      # CSE=0
        self.assertEqual(cards[3][20:40].strip(), "",
                         "columns 21-40 are the dead slot the reader ignores")
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 1.0)     # ZEROSTRESS
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 0.0)     # FSCALE_POR
        self.assertEqual(_col_i(cards[3], 81, 90), 0)             # SENS_ID

    def test_cse_one_reduces_compression(self):
        """CSE=1 ("eliminate compressive stress") -> R_E = 0.01, one decade
        above the starter's 1e-3 floor (hm_read_mat19.F:143-149 clamps below
        it and raises WARNING 1572)."""
        _r, starter, _e = _convert(self._law19_deck(cse=1.0))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 0.01)

    def test_eb_blank_falls_back_to_ea(self):
        """EB blank -> E22 = EA. dyna2rad's LAW58 twin of this line writes E1 a
        SECOND time and leaves E2 at zero (convertmats.cxx:2143), which is
        starter ERROR 306."""
        _r, starter, _e = _convert(self._law19_deck(eb=0.0))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[1], 21, 40), 13789.5146)

    def test_gab_blank_uses_isotropic_shear(self):
        """GAB blank -> G = EA / (2 (1 + nu)), the DIVISION. The commented-out
        legacy in dyna2rad multiplies (cm:2107); the live code divides."""
        _r, starter, _e = _convert(self._law19_deck(gab=0.0))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        expect = 13789.5146 / (2.0 * 1.35)
        for a, b in ((1, 20), (21, 40), (41, 60)):
            self.assertAlmostEqual(_col_f(cards[2], a, b), expect, places=4)

    def test_nu12_prefers_prab(self):
        """Radioss nu21 = NU12*E22/E11, i.e. NU12 pairs with E11 — LS-DYNA's
        PRAB (nu_ab, a<->1). PRBA is the fallback for the very many decks that
        state only the minor ratio."""
        _r, starter, _e = _convert(self._law19_deck(prba=0.20, prab=0.31))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 0.31)
        _r, starter, _e = _convert(self._law19_deck(prba=0.20, prab=0.0))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 0.20)

    def test_prop_type9_columns_and_the_2024_ipos_trap(self):
        """/PROP/TYPE9 card 4: Ip at columns 91-100 and 81-90 BLANK.

        A twin probe at /BEGIN 2022 / 2024 / 2026 showed columns 81-90 are
        ignored at 2022 and become ``Ipos`` from 2024, silently and with no
        WARNING 100211 either way. Writing anything there is a
        version-dependent change of meaning.
        """
        _r, starter, _e = _convert(self._law19_deck(damp=0.05))
        blk = _block(starter, "/PROP/TYPE9/")
        cards = _cards(blk)
        self.assertEqual(_col_i(cards[0], 1, 10), 24)     # Ishell (QEPH)
        self.assertEqual(_col_i(cards[0], 11, 20), 4)     # Ismstr = large strain
        self.assertEqual(_col_i(cards[0], 21, 30), 2)     # Ish3n
        self.assertAlmostEqual(_col_f(cards[1], 61, 80), 0.05)   # Dm <- DAMP
        self.assertEqual(_col_i(cards[2], 11, 20), 1)     # ISTRAIN gates CEPSINI
        self.assertAlmostEqual(_col_f(cards[2], 21, 40), 0.381)  # Thick
        self.assertEqual(cards[3][80:90].strip(), "",
                         "card 4 cols 81-90 must stay blank (Ipos at >=2024)")
        self.assertEqual(_col_i(cards[3], 91, 100), 2)    # Ip = element nodes

    def test_membrane_elform9_collapses_nip_to_one(self):
        """ELFORM=9 is a MEMBRANE: every through-thickness point is identical,
        so N=1. An ordinary shell ELFORM keeps the deck's NIP."""
        _r, starter, _e = _convert(self._law19_deck())
        cards = _cards(_block(starter, "/PROP/TYPE9/"))
        self.assertEqual(_col_i(cards[2], 1, 10), 1)
        deck = self._law19_deck().replace(
            "         1         9       1.0         4",
            "         1         2       1.0         4")
        _r, starter, _e = _convert(deck)
        cards = _cards(_block(starter, "/PROP/TYPE9/"))
        self.assertEqual(_col_i(cards[2], 1, 10), 4)

    def test_part_is_repointed_and_section_prop_suppressed(self):
        """The /PART must follow the fabric property, and the section's own
        isotropic /PROP/SHELL must not be emitted at all: LAW19 on IGTYP 1 is
        starter ERROR 3047."""
        _r, starter, _e = _convert(self._law19_deck())
        prop = _block(starter, "/PROP/TYPE9/")[0]
        prop_id = int(prop.rsplit("/", 1)[1])
        part = _cards(_block(starter, "/PART/1"))
        self.assertEqual(_col_i(part[0], 1, 10), prop_id)
        self.assertEqual(_col_i(part[0], 11, 20), 3)      # mat_ID
        self.assertNotIn("/PROP/SHELL/1", starter)

    def test_aopt3_vector_and_beta_shift(self):
        """AOPT=3 measures BETA from ``v x n``, a quarter turn from Radioss's
        Phi datum, so Phi = BETA + 90 and Ip goes to 0 (explicit vector)."""
        _r, starter, _e = _convert(
            self._law19_deck(aopt=3.0, v=(1.0, 0.0, 0.0), beta=17.0))
        cards = _cards(_block(starter, "/PROP/TYPE9/"))
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 1.0)
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 107.0)
        self.assertEqual(_col_i(cards[3], 91, 100), 0)

    def test_rgbrth_becomes_a_sensor(self):
        """RGBRTH -> /SENSOR/TIME Tdelay -> the law's SENS_ID (the starter's
        MATPARAM%IPARAM(1) reference-state activation sensor)."""
        _r, starter, _e = _convert(self._law19_deck(rgbrth=0.004))
        sens = _block(starter, "/SENSOR/TIME/")
        sid = int(sens[0].rsplit("/", 1)[1])
        self.assertAlmostEqual(_col_f(_cards(sens)[0], 1, 20), 0.004)
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertEqual(_col_i(cards[3], 81, 90), sid)

    def test_tsrfac_maps_to_zerostress(self):
        _r, starter, _e = _convert(self._law19_deck(tsrfac=0.4))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 0.4)

    def test_tsrfac_out_of_range_warns_and_falls_back(self):
        r, starter, _e = _convert(self._law19_deck(tsrfac=3.0))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 1.0)
        self.assertTrue(_warns(r, "TSRFAC"))

    def test_liner_and_porosity_are_named_as_dropped(self):
        r, _s, _e = _convert(self._law19_deck(lratio=0.2, fvopt=7.0))
        self.assertTrue(_warns(r, "LINER"))
        self.assertTrue(_warns(r, "POROSITY"))


class TestFabricFormBranch(unittest.TestCase):

    def test_form_branch_table(self):
        """The FORM x curves routing, exhaustively, through the ONE predicate
        both the material writer and the property writer read."""
        from k2rad.state import MatFabric
        cases = [
            (0, (), 19), (1, (), 19), (2, (), 19), (12, (), 19),
            (3, (), 19), (8, (), 19), (13, (), 19), (99, (), 19),
            (4, (101, 0, 0, 0, 0, 0), 58),
            (14, (101, 102, 103, 0, 0, 0), 58),
            (-14, (0, 0, 0, 104, 0, 0), 58),
            (24, (0, 0, 103, 0, 0, 0), 58),
            # the card-7 FORMs with NO curve on the card -> the analytic law
            (4, (), 19), (14, (), 19), (-14, (), 19), (24, (), 19),
        ]
        for form, curves, law in cases:
            with self.subTest(form=form, curves=curves):
                c = list(curves) + [0] * 6
                m = MatFabric(mid=1, form=form, lca=c[0], lcb=c[1], lcab=c[2],
                              lcua=c[3], lcub=c[4], lcuab=c[5])
                self.assertEqual(_fabric_law(m), law)

    def test_curveless_card7_form_warns_by_name(self):
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD
                + _fabric_mat(form=14, curves=()) + _TERM)
        r, starter, _e = _convert(deck)
        self.assertIn("/MAT/LAW19/3", starter)
        self.assertTrue(_warns(r, "FORM=14"))

    def test_unmapped_form_warns_by_name_but_keeps_the_material(self):
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD + _fabric_mat(form=13) + _TERM)
        r, starter, _e = _convert(deck)
        self.assertIn("/MAT/LAW19/3", starter)
        self.assertTrue(_warns(r, "FORM=13"))

    def test_fvopt_negative_shifts_cards_5_to_8(self):
        """Card 4 exists only when FVOPT < 0. Reading card 5 at a fixed offset
        would take the L/R/C1/C2/C3 leakage row as RGBRTH/A0REF/A1..A3 — the
        RGBRTH slot would pick up 2.0 and synthesize a birth sensor the deck
        never asked for."""
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD
                + _fabric_mat(fvopt=-1.0, rgbrth=0.0, beta=13.0) + _TERM)
        r, starter, _e = _convert(deck)
        self.assertNotIn("/SENSOR/TIME/", starter)
        cards = _cards(_block(starter, "/PROP/TYPE9/"))
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 13.0)   # Phi <- BETA
        self.assertTrue(_warns(r, "POROSITY"))


class TestFabricLaw58(unittest.TestCase):

    def _law58_deck(self, curves=(101, 102, 103, 0, 0, 0), form=14, **kw):
        return ("*KEYWORD\n" + _MESH_ONE_QUAD
                + _fabric_mat(form=form, curves=curves, **kw)
                + _CURVES_3 + _TERM)

    def test_law58_card_columns(self):
        _r, starter, _e = _convert(self._law58_deck())
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 1.0687e-9)
        # E1 | B1 | E2 | B2 | Flex
        self.assertAlmostEqual(_col_f(cards[1], 1, 20), 13789.5146)
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 13789.5146)
        self.assertAlmostEqual(_col_f(cards[1], 81, 100), 1.0)   # CSE=0
        # G0 | GT | AlphaT | Gsh | sensor_ID
        self.assertAlmostEqual(_col_f(cards[2], 1, 20), 10548.9787)
        self.assertEqual(_col_i(cards[2], 91, 100), 0)
        # Df | Ds | GFROT | ZERO_STRESS
        self.assertAlmostEqual(_col_f(cards[3], 81, 100), 1.0)
        # N1 | N2 | S1 | S2 | FLEX1 | FLEX2
        self.assertEqual(_col_i(cards[4], 1, 10), 0)
        # FCT_ID1..3, one per card
        self.assertEqual(_col_i(cards[5], 1, 10), 101)
        self.assertEqual(_col_i(cards[6], 1, 10), 102)
        self.assertEqual(_col_i(cards[7], 1, 10), 103)
        self.assertEqual(len(cards), 8)

    def test_flex_from_cse(self):
        _r, starter, _e = _convert(self._law58_deck(cse=1.0))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertAlmostEqual(_col_f(cards[1], 81, 100), 0.01)

    def test_unloading_card_written_only_with_all_three_loading_curves(self):
        """hm_read_mat58.F: "at least one unloading curve is defined => all
        loading curves must be defined" — a missing one is ERROR 1578/1579/1580
        and the deck is refused. So the unloading card is withheld rather than
        emitting a deck the starter rejects."""
        _r, starter, _e = _convert(
            self._law58_deck(curves=(101, 102, 103, 104, 0, 0)))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 9)
        self.assertEqual(_col_i(cards[8], 1, 10), 104)     # FCT_ID4
        self.assertEqual(_col_i(cards[8], 11, 20), 0)      # FCT_ID5
        self.assertEqual(_col_i(cards[8], 61, 70), 0)      # FCT_ID6
        # LCB missing -> no unloading card at all
        _r, starter, _e = _convert(
            self._law58_deck(curves=(101, 0, 103, 104, 0, 0)))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 7)

    def test_prop_type16_columns(self):
        """/PROP/TYPE16 (SH_FABR). Ipos IS a real cell here at 2022 (columns
        71-80) — unlike /PROP/TYPE9, where the same idea has no cell at all."""
        _r, starter, _e = _convert(self._law58_deck(damp=0.03))
        cards = _cards(_block(starter, "/PROP/TYPE16/"))
        self.assertEqual(_col_i(cards[0], 1, 10), 24)      # Ishell
        self.assertEqual(_col_i(cards[0], 11, 20), 4)      # Ismstr
        self.assertEqual(_col_i(cards[0], 21, 30), 2)      # Ish3n
        self.assertAlmostEqual(_col_f(cards[1], 61, 80), 0.03)   # Dm <- DAMP
        self.assertEqual(_col_i(cards[2], 1, 10), 1)       # N layers
        self.assertEqual(_col_i(cards[2], 11, 20), 1)      # Istrain
        self.assertAlmostEqual(_col_f(cards[2], 21, 40), 0.381)
        self.assertEqual(_col_i(cards[3], 61, 70), 0)      # Skew_ID
        self.assertEqual(_col_i(cards[3], 71, 80), 0)      # Ipos
        self.assertEqual(_col_i(cards[3], 91, 100), 2)     # Ip
        # layer card: Phi_i | Alpha_i | T_i | Z_i | mat_IDi
        self.assertAlmostEqual(_col_f(cards[4], 21, 40), 90.0,
                               msg="90 deg = an ORTHOGONAL weave")
        self.assertAlmostEqual(_col_f(cards[4], 41, 60), 0.381)
        self.assertEqual(_col_i(cards[4], 81, 90), 3)      # mat_IDi

    def test_layer_thicknesses_sum_to_thick(self):
        """The property renormalizes them otherwise and reports WARNING 29."""
        deck = self._law58_deck().replace(
            "         1         9       1.0         4",
            "         1         2       1.0         3")
        _r, starter, _e = _convert(deck)
        cards = _cards(_block(starter, "/PROP/TYPE16/"))
        thick = _col_f(cards[2], 21, 40)
        layers = cards[4:]
        self.assertEqual(len(layers), 3)
        self.assertAlmostEqual(sum(_col_f(ln, 41, 60) for ln in layers),
                               thick, places=9)
        # z positions are the layer mid-planes, bottom to top
        self.assertAlmostEqual(_col_f(layers[0], 61, 80), -thick / 3.0)
        self.assertAlmostEqual(_col_f(layers[1], 61, 80), 0.0)
        self.assertAlmostEqual(_col_f(layers[2], 61, 80), thick / 3.0)

    def test_law58_never_lands_on_a_type9(self):
        _r, starter, _e = _convert(self._law58_deck())
        self.assertNotIn("/PROP/TYPE9/", starter)
        self.assertNotIn("/PROP/SHELL/1", starter)

    def test_form_minus_14_names_the_dropped_card8(self):
        r, _s, _e = _convert(self._law58_deck(form=-14))
        self.assertTrue(_warns(r, "FORM=-14"))


class TestFabricPartScreening(unittest.TestCase):

    def test_solid_part_on_fabric_warns_and_gets_no_property(self):
        deck = """\
*KEYWORD
*NODE
       1             0.0             0.0             0.0
       2             1.0             0.0             0.0
       3             1.0             1.0             0.0
       4             0.0             1.0             0.0
       5             0.0             0.0             1.0
       6             1.0             0.0             1.0
       7             1.0             1.0             1.0
       8             0.0             1.0             1.0
*ELEMENT_SOLID
       1       1
       1       2       3       4       5       6       7       8
*PART
solid on fabric
         1         1         3
*SECTION_SOLID
         1         1
""" + _fabric_mat() + _TERM
        r, starter, _e = _convert(deck)
        self.assertNotIn("/PROP/TYPE9/", starter)
        self.assertTrue(_warns(r, "SHELL-ONLY law"))

    def test_element_free_part_warns_as_a_mesh_check(self):
        deck = """\
*KEYWORD
*PART
empty fabric
         1         1         3
*SECTION_SHELL
         1         2       1.0         2
       1.0       1.0       1.0       1.0
""" + _fabric_mat() + _TERM
        r, _s, _e = _convert(deck)
        self.assertTrue(_warns(r, "no elements"))

    def test_shared_section_keeps_the_neighbour_isotropic(self):
        """A *SECTION_SHELL shared by a fabric part and a steel part: the
        fabric part is repointed at its own /PROP/TYPE9 and the steel part
        keeps the section's /PROP/SHELL. Retyping the shared section would be
        starter ERROR 3047 on the steel part instead."""
        deck = """\
*KEYWORD
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5            20.0             0.0             0.0
       6            20.0            10.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       2       2       5       6       3
*PART
fabric
         1         1         3
*PART
steel
         2         1         9
*SECTION_SHELL
         1         2       1.0         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         9   7.85E-9  210000.0       0.3
""" + _fabric_mat() + _TERM
        _r, starter, _e = _convert(deck)
        self.assertIn("/PROP/SHELL/1", starter)
        prop = _block(starter, "/PROP/TYPE9/")[0]
        fab_prop = int(prop.rsplit("/", 1)[1])
        self.assertEqual(_col_i(_cards(_block(starter, "/PART/1"))[0], 1, 10),
                         fab_prop)
        self.assertEqual(_col_i(_cards(_block(starter, "/PART/2"))[0], 1, 10), 1)


class TestFabricDispatchAndOffsets(unittest.TestCase):

    def test_every_spelling_dispatches(self):
        for kw in ("MAT_FABRIC", "MAT_034", "MAT_34"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
                self.assertIn(kw, _OFFSET_SPECS)

    def test_title_and_id_suffixes_are_parsed(self):
        """_TITLE / _ID are stripped by parser._split_keyword, so the base key
        covers both — but only if the title line is consumed."""
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD
                + _fabric_mat().replace("*MAT_FABRIC\n",
                                        "*MAT_FABRIC_TITLE\nbag weave\n")
                + _TERM)
        _r, starter, _e = _convert(deck)
        blk = _block(starter, "/MAT/LAW19/3")
        self.assertEqual(blk[1], "bag weave")

    def test_include_transform_offsets_mid_and_the_card7_curves(self):
        """The card-7 curve run is offset with IDFOFF, and its card index moves
        with FORM and FVOPT — so a static offset spec cannot hold it."""
        deck = ("*KEYWORD\n" + _fabric_mat(form=14, curves=(101, 102, 103,
                                                            0, 0, 0)))
        blocks = [b for b in _parse_str(deck) if b.keyword == "MAT_FABRIC"]
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        _offset_block(b, _OFFSET_SPECS["MAT_FABRIC"],
                      {"m": 1000, "f": 500}, lambda *_a: None)
        self.assertEqual(int(b.raw[0][0:10]), 1003)
        self.assertEqual([int(b.raw[5][i * 10:(i + 1) * 10] or 0)
                          for i in range(3)], [601, 602, 603])

    def test_include_transform_leaves_card5_alone_on_a_form0_deck(self):
        """The mirror of the test above: with FORM=0 there IS no card 7, so
        nothing after card 3 may be touched."""
        deck = "*KEYWORD\n" + _fabric_mat(form=0)
        b = [x for x in _parse_str(deck) if x.keyword == "MAT_FABRIC"][0]
        before = list(b.raw)
        _offset_block(b, _OFFSET_SPECS["MAT_FABRIC"],
                      {"m": 1000, "f": 500}, lambda *_a: None)
        self.assertEqual(b.raw[1:], before[1:])
        self.assertEqual(int(b.raw[0][0:10]), 1003)


def _parse_str(deck: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    blocks = parse_k_file(path)
    tmp.cleanup()
    return blocks


if __name__ == "__main__":
    unittest.main()
