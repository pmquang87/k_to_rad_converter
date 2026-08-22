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


def _th_monv_vars(block):
    """The VAR cells of a /TH/MONV block, across however many cards they take.

    ``FREE_CELL_LIST`` caps a line at 100 characters, so a 17-variable AIRBAG1
    group spans two cards; the id card is told apart by being all digits."""
    out = []
    for ln in _cards(block):
        toks = ln.split()
        if toks and all(t.isdigit() for t in toks):
            break
        out += toks
    return out


def _th_monv_ids(block):
    out = []
    for ln in _cards(block):
        toks = ln.split()
        if toks and all(t.isdigit() for t in toks):
            out += [int(t) for t in toks]
    return out


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

#: A CLOSED box of six quads on eight nodes, consistently wound OUTWARD — the
#: smallest surface a /MONVOL can measure a volume of (1000 mm^3).
#:
#: Two deliberate properties, both needed for the volume assertions to mean
#: anything. The box sits at [5, 15]^3 rather than at the origin, so no face
#: passes through it: a face on a coordinate plane contributes
#: ``(1/3)(N . c) = 0`` whatever its winding, which would let a MIXED-winding
#: surface still sum to the right volume by accident (it did, on the first
#: draft of this fixture). And the bottom face is written ``1 4 3 2`` so its
#: normal points OUT (-z) like every other face's — a real closed manifold,
#: not six faces that happen to cancel.
_MESH_CLOSED_BOX = """\
*NODE
       1             5.0             5.0             5.0
       2            15.0             5.0             5.0
       3            15.0            15.0             5.0
       4             5.0            15.0             5.0
       5             5.0             5.0            15.0
       6            15.0             5.0            15.0
       7            15.0            15.0            15.0
       8             5.0            15.0            15.0
*ELEMENT_SHELL
       1       1       1       4       3       2
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
        # ZEROSTRESS: TSRFAC = 0 (blank) is LS-DYNA's "no tensile stress
        # reduction", and sigeps19c.F:130 gates the WHOLE reference-state
        # cancel-and-relax block on ZEROSTRESS /= 0 — so "no reduction" is 0,
        # not 1. See test_tsrfac_maps_monotonically_onto_zerostress.
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 0.0)     # ZEROSTRESS
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
        PRAB (nu_ab, a<->1, ``mat_034.cfg:33`` "Major Poissons ratio ab")."""
        _r, starter, _e = _convert(self._law19_deck(prba=0.20, prab=0.31))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 0.31)

    def test_nu12_from_prba_is_rescaled_by_reciprocity(self):
        """PRBA is the MINOR ratio (``mat_034.cfg:32``) and Radioss NU12 the
        MAJOR one, so the fallback is ``NU12 = PRBA*EA/EB``, not PRBA.

        EA != EB on purpose: with the fixture's default EB == EA the factor is
        1 and the naive slot is indistinguishable, which is exactly how the
        defect survived. MEASURED with the real starter — EA=1000, EB=13789.5,
        PRBA=0.3 written naively gives nu21 = 4.137, DETC = -0.241 and
        ``ERROR ID : 307`` + ERROR TERMINATION; the reciprocity value 0.021755
        gives DETC = 0.9935 and NORMAL TERMINATION.
        """
        _r, starter, _e = _convert(
            self._law19_deck(prba=0.1, prab=0.0, eb=4.0 * 13789.5146))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 0.1 / 4.0)
        # EB blank -> E22 = EA -> the rescale is the identity, which is the
        # isotropic-fabric case the manual describes.
        _r, starter, _e = _convert(
            self._law19_deck(prba=0.20, prab=0.0, eb=0.0))
        cards = _cards(_block(starter, "/MAT/LAW19/3"))
        self.assertAlmostEqual(_col_f(cards[1], 41, 60), 0.20)

    def test_negative_determinant_is_named_as_error_307(self):
        """``hm_read_mat19.F:136-140``: ``DETC = 1 - N12*N21 <= 0`` is
        ERROR 307 and refuses the whole deck.

        ``NU12 = 0.6`` against ``E22 = 4*E11`` gives ``nu21 = 2.4`` and
        ``DETC = 1 - 1.44 = -0.44``.
        """
        r, _s, _e = _convert(
            self._law19_deck(prba=0.0, prab=0.6, eb=4.0 * 13789.5146))
        self.assertTrue(_warns(r, "ERROR 307"), r.warnings)
        # And the ordinary card does not trip it.
        r, _s, _e = _convert(self._law19_deck())
        self.assertFalse(_warns(r, "ERROR 307"))

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
        self.assertEqual(
            _col_i(cards[3], 91, 100), 20,
            "Ip=20 (N1->N2). IRP is a SPARSE ENUM: corthini.F:122 SELECT "
            "CASEs over 0/20/22/23/24/25 only, so a 2 matches no branch, "
            "Vx/Vy/Vz are never assigned and the projection check fires "
            "ERROR 197 ONCE PER ELEMENT. MEASURED on the real starter: "
            "99 x ERROR 197 with Ip=2, 0 ERROR(S) with Ip=20.")

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

    def test_aopt3_maps_to_ip_23_with_beta_unshifted(self):
        """AOPT=3 measures BETA from a line "defined by the cross product of
        the vector v with the element normal" — and Radioss ``Ip = 23`` is
        exactly that: ``corthini.F`` CASE(23) computes ``n x v`` PER ELEMENT.
        So the vector goes in Vx/Vy/Vz and BETA carries over with NO offset.
        dyna2rad adds +90 (convertprops.cxx:1794); that offset belongs to the
        SOLID path, where Radioss PROJECTS the vector instead of crossing it,
        and on a shell it rotates the warp direction a quarter turn."""
        _r, starter, _e = _convert(
            self._law19_deck(aopt=3.0, v=(1.0, 0.0, 0.0), beta=17.0))
        cards = _cards(_block(starter, "/PROP/TYPE9/"))
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 1.0)
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 17.0)
        self.assertEqual(_col_i(cards[3], 91, 100), 23)

    def test_aopt2_vector_uses_ip_0(self):
        """AOPT 2 reads A1/A2/A3 from card 5 (``_fabric_mat`` writes A1 = 1),
        and a stated global vector goes into Vx/Vy/Vz with Ip = 0 — Radioss
        CASE(0) reads GEO(7,8,9) directly."""
        _r, starter, _e = _convert(self._law19_deck(aopt=2.0, beta=11.0))
        cards = _cards(_block(starter, "/PROP/TYPE9/"))
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 1.0)     # Vx <- A1
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 11.0)   # Phi <- BETA
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
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 0.0)
        self.assertTrue(_warns(r, "TSRFAC"))

    def test_tsrfac_maps_monotonically_onto_zerostress(self):
        """TSRFAC -> ZEROSTRESS must be MONOTONE, and 0 must map to 0.

        ``sigeps19c.F:131`` (and ``sigeps58c.F:1690``, identical) gate the
        whole reference-state block on ``IF (ZEROSTRESS /= ZERO)``: a non-zero
        value memorises the /XREF pre-stress at cycle 1, SUBTRACTS it and then
        relaxes it away at that rate. So ZEROSTRESS CANCELS the reference
        state and only 0 applies it — which is what LS-DYNA's TSRFAC = 0
        ("no tensile stress reduction") asks for.

        The old map wrote 1.0 for a blank TSRFAC, i.e. 0 -> 1.0, 0.5 -> 0.5,
        1.0 -> 1.0: non-monotone, and the 0 end armed MAXIMUM relaxation for a
        card that asked for none. MEASURED on a 0.5 %-pre-stretched LAW19
        membrane (internal energy, mJ; analytic in brackets): peak 74.41 at
        ZS=1 vs 134.04 at ZS=0 [135.0], and the unload leg ends at -28.98 mJ
        with ZS=1 — energy returned that was never stored.
        """
        seen = []
        for tsrfac in (0.0, 0.25, 0.5, 0.75, 1.0):
            _r, starter, _e = _convert(self._law19_deck(tsrfac=tsrfac))
            cards = _cards(_block(starter, "/MAT/LAW19/3"))
            zs = _col_f(cards[3], 41, 60)
            with self.subTest(tsrfac=tsrfac):
                self.assertAlmostEqual(zs, tsrfac)
            seen.append(zs)
        self.assertEqual(seen, sorted(seen), "the map must be monotone")

    def test_a_birth_sensor_is_named_inert_when_zerostress_is_zero(self):
        """Both laws read the reference-state sensor only from INSIDE the
        ZEROSTRESS block (``sigeps19c.F:131-132``,
        ``sigeps58c.F:248-252``), so RGBRTH's /SENSOR does nothing while
        TSRFAC is 0. Radioss has no slot that holds both the delay and the
        pre-stress, so the trade is named rather than resolved."""
        r, starter, _e = _convert(self._law19_deck(rgbrth=0.003))
        self.assertIn("/SENSOR/TIME/", starter)
        self.assertTrue(_warns(r, "DELAY IS INERT"), r.warnings)
        # with a TSRFAC stated the sensor is live and nothing is said
        r, starter, _e = _convert(
            self._law19_deck(rgbrth=0.003, tsrfac=0.5))
        self.assertIn("/SENSOR/TIME/", starter)
        self.assertFalse(_warns(r, "DELAY IS INERT"))

    def test_law58_zero_stress_takes_the_same_map(self):
        """LAW58's ZERO_STRESS is the same field with the same engine block
        (``sigeps58c.F:1690-1729``), so it must not drift from LAW19's."""
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD
                + _fabric_mat(form=14, curves=(101, 102, 103), tsrfac=0.0)
                + _CURVES_3 + _TERM)
        _r, starter, _e = _convert(deck)
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertAlmostEqual(_col_f(cards[4], 81, 100), 0.0)

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
        # Df | Ds | GFROT | ZERO_STRESS (TSRFAC = 0 -> 0, see
        # test_tsrfac_maps_monotonically_onto_zerostress)
        self.assertAlmostEqual(_col_f(cards[3], 81, 100), 0.0)
        # N1 | N2 | S1 | S2 | FLEX1 | FLEX2
        self.assertEqual(_col_i(cards[4], 1, 10), 0)
        self.assertAlmostEqual(_col_f(cards[4], 21, 40), 1e-4)   # S1
        self.assertAlmostEqual(_col_f(cards[4], 41, 60), 1e-4)   # S2
        # FCT_ID1..3, one per card. The warp/weft slots take the deck's curve
        # ids unchanged; the SHEAR slot is a SYNTHESIZED copy — see
        # test_shear_curve_is_converted_to_degrees_and_mirrored.
        self.assertEqual(_col_i(cards[5], 1, 10), 101)
        self.assertEqual(_col_i(cards[6], 1, 10), 102)
        self.assertNotEqual(_col_i(cards[7], 1, 10), 103)
        self.assertGreaterEqual(_col_i(cards[7], 1, 10), 90001)
        self.assertEqual(len(cards), 8)

    def test_shear_curve_is_converted_to_degrees_and_mirrored(self):
        """Two disagreements about the LAW58 shear abscissa, one of them a hard
        starter error.

        UNIT: ``sigeps58c.F:527`` evaluates the shear function at
        ``PHI = atan(TAN_PHI)*180/PI`` — the shear ANGLE IN DEGREES — while
        LS-DYNA's LCAB abscissa is the engineering shear STRAIN. dyna2rad
        multiplies by a flat 57, which is the small-angle approximation AND a
        0.5 % error against 180/pi.

        RANGE: ``law58_upd.F:293-311`` refuses the material unless
        ``FUNC_INTERS_SHEAR`` finds two loading/unloading intersections
        STRADDLING zero (``XINT1 * XINT2 > 0`` is an error), so a one-sided
        curve is ERROR 1716 — MEASURED on the real starter, with two curves
        that genuinely crossed on the positive side.
        """
        import math
        _r, starter, _e = _convert(self._law58_deck())
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        fct3 = _col_i(cards[7], 1, 10)
        pts = [(_col_f(p, 1, 20), _col_f(p, 21, 40))
               for p in _cards(_block(starter, f"/FUNCT/{fct3}"))]
        # source curve 103 is (0, 0) / (0.5, 300)
        deg = math.degrees(math.atan(0.5))
        self.assertEqual(len(pts), 3)
        self.assertAlmostEqual(pts[0][0], -deg, places=8)
        self.assertAlmostEqual(pts[0][1], -300.0)
        self.assertEqual(pts[1], (0.0, 0.0))
        self.assertAlmostEqual(pts[2][0], deg, places=8)
        self.assertAlmostEqual(pts[2][1], 300.0)
        self.assertNotAlmostEqual(deg, 0.5 * 57.0, places=2,
                                  msg="the flat x57 dyna2rad uses is not this")

    def test_a_two_sided_shear_curve_is_converted_but_not_mirrored(self):
        """A curve the deck already states on both sides of zero is
        converted to degrees but NOT mirrored again — mirroring it would
        duplicate every point."""
        two_sided = (
            "*DEFINE_CURVE" + chr(10) + "       103" + chr(10)
            + "                -0.5              -300.0" + chr(10)
            + "                 0.0                 0.0" + chr(10)
            + "                 0.5               300.0" + chr(10))
        one_sided = (
            "*DEFINE_CURVE" + chr(10) + "       103" + chr(10)
            + "                 0.0                 0.0" + chr(10)
            + "                 0.5               300.0" + chr(10))
        curves = _CURVES_3.replace(one_sided, two_sided)
        self.assertNotEqual(curves, _CURVES_3)
        deck = ("*KEYWORD" + chr(10) + _MESH_ONE_QUAD
                + _fabric_mat(form=14, curves=(101, 102, 103, 0, 0, 0))
                + curves + _TERM)
        _r, starter, _e = _convert(deck)
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        fct3 = _col_i(cards[7], 1, 10)
        pts = _cards(_block(starter, f"/FUNCT/{fct3}"))
        self.assertEqual(len(pts), 3, "already two-sided: no extra mirror")

    def test_flex_from_cse(self):
        _r, starter, _e = _convert(self._law58_deck(cse=1.0))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertAlmostEqual(_col_f(cards[1], 81, 100), 0.01)

    def test_unloading_card_written_only_with_all_three_loading_curves(self):
        """hm_read_mat58.F:176-195: "at least one unloading curve is defined =>
        all loading curves must be defined" — a missing one is
        ERROR 1578/1579/1580 and the deck is refused. So the unloading card is
        withheld rather than emitting a deck the starter rejects."""
        _r, starter, _e = _convert(
            self._law58_deck(curves=(101, 102, 103, 104, 0, 0)))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 9)
        self.assertEqual(_col_i(cards[8], 1, 10), 104)     # FCT_ID4
        self.assertEqual(_col_i(cards[8], 11, 20), 0)      # FCT_ID5
        self.assertEqual(_col_i(cards[8], 61, 70), 0)      # FCT_ID6
        # LCB missing AND its own unloading twin LCUB stated -> the blank
        # cannot be synthesized (law58_upd.F would then have to INTERSECT the
        # synthetic loading curve with the deck's unloading one, ERROR 1716),
        # so the whole unloading card goes and the loss is NAMED.
        r, starter, _e = _convert(
            self._law58_deck(curves=(101, 0, 103, 104, 105, 0)))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 7)
        self.assertTrue(_warns(r, "UNLOADING curves"), r.warnings)
        self.assertTrue(_warns(r, "LCB"))

    def test_blank_lcab_synthesizes_the_shear_loading_curve_from_gab(self):
        """Vol II R16 card 7: "LCAB ... If zero, GAB is used". FORM=14 with
        LCA/LCB tabulated, LCAB=0 (analytic shear) and LCUA given is an
        ORDINARY LS-DYNA deck, and dropping its unloading curves for it lost
        the hysteresis silently.

        The synthesized FCT_ID3 is ``tau(PHI) = GAB*tan(PHI)`` in DEGREES —
        the engine's own analytic fallback (``sigeps58c.F:540``
        ``SIGNXY = G0*TAN_PHI``) and LS-DYNA's own ``tau = GAB*gamma``. It is
        safe precisely because LCUAB is blank too: the reader then sets
        ``IFUNC(6) = IFUNC(3)`` and ``law58_upd.F:344`` takes the
        ``FUNC == FUND`` arm, which never calls FUNC_INTERS_SHEAR.
        """
        import math
        r, starter, _e = _convert(
            self._law58_deck(curves=(101, 102, 0, 104, 0, 0)))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 9, "the unloading card survives")
        self.assertEqual(_col_i(cards[8], 1, 10), 104)          # FCT_ID4
        self.assertEqual(_col_i(cards[8], 61, 70), 0)           # FCT_ID6 blank
        fct3 = _col_i(cards[7], 1, 10)
        self.assertGreaterEqual(fct3, 90001)
        pts = [(_col_f(p, 1, 20), _col_f(p, 21, 40))
               for p in _cards(_block(starter, f"/FUNCT/{fct3}"))]
        self.assertEqual(len(pts), 25)                          # 12 + 0 + 12
        self.assertEqual(pts[12], (0.0, 0.0))
        for x, y in pts:
            self.assertAlmostEqual(
                y, 10548.9787 * math.tan(math.radians(x)), places=3)
        self.assertTrue(_warns(r, "SYNTHESIZED"), r.warnings)
        self.assertFalse(_warns(r, "UNLOADING curves"))

    def test_synthesis_is_skipped_when_the_constant_is_zero_too(self):
        """GAB = 0 with no LCAB leaves nothing to synthesize from, so the
        unloading card is dropped and named rather than guessed at."""
        r, starter, _e = _convert(
            self._law58_deck(curves=(101, 102, 0, 104, 0, 0), gab=0.0))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 7)
        self.assertTrue(_warns(r, "UNLOADING curves"))

    def test_synthesized_unloading_shear_curve_is_not_left_dangling(self):
        """When the unloading card IS dropped, the /FUNCT that
        ``_law58_shear_curve`` already built for LCUAB must not stay in the
        deck referenced by nothing."""
        r, starter, _e = _convert(
            self._law58_deck(curves=(101, 0, 103, 0, 105, 103)))
        cards = _cards(_block(starter, "/MAT/LAW58/3"))
        self.assertEqual(len(cards), 7)
        referenced = {_col_i(c, 1, 10) for c in cards[5:]}
        for blk in _blocks(starter, "/FUNCT/"):
            fid = int(blk[0].rsplit("/", 1)[1])
            if "SHEAR_UNLOAD" in blk[1]:
                self.fail(f"/FUNCT/{fid} ({blk[1]}) is emitted but unused")
        self.assertTrue(referenced)

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
        self.assertEqual(_col_i(cards[3], 91, 100), 20)    # Ip = N1->N2
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

    def test_include_transform_reads_card3_free_format_too(self):
        """``_off_mat_fabric`` must read card 3 with the module's free-format
        aware ``_fields``, not the bare 10-char slicer (#119).

        On a comma-separated *MAT_FABRIC the slicer reads FORM out of the
        wrong columns, ``form`` comes back 0 and the six card-7 curve ids are
        silently left UN-offset — while the MID on the same block IS offset
        (``_rewrite_line`` goes through ``_split_card``) and so are the
        *DEFINE_CURVE ids in the same include, leaving the material pointing
        at the parent deck's curve numbers. The HANDLER reads the same card
        through ``_card(..., fixed=True)``'s free-format fallback and gets
        FORM=14, so the two disagreed.
        """
        deck = ("*KEYWORD\n*MAT_FABRIC\n"
                "3,1.0687e-9,13789.5,13789.5,,0.35,0.35\n"
                "10548.9,,,0.0,0.0,0.0,0.0,0.0\n"
                "0.0,0.0,0.0,0.0,0.0,14,0.0,0.0\n"
                ",0.0,0.0,1.0,0.0,0.0,0.0,0.0\n"
                "0.0,0.0,0.0,,,,0.0,0\n"
                "101,102,103,0,0,0,0.0\n")
        b = [x for x in _parse_str(deck) if x.keyword == "MAT_FABRIC"][0]
        # the handler's own reading of the same block, for the comparison
        st = _dispatch(deck)
        self.assertEqual(st.mat_fabric[3].form, 14)
        self.assertEqual(st.mat_fabric[3].lca, 101)
        _offset_block(b, _OFFSET_SPECS["MAT_FABRIC"],
                      {"m": 1000, "f": 500}, lambda *_a: None)
        self.assertEqual([int(t) for t in b.raw[5].split(",")[:3]],
                         [601, 602, 603])
        self.assertEqual(int(b.raw[0].split(",")[0]), 1003)

    def test_include_transform_honours_the_fvopt_card_shift(self):
        """FVOPT < 0 inserts the L/R/C1/C2/C3 leakage card 4, so card 7 sits
        one line lower. Collapsing the shift would offset the LEAKAGE
        constants as curve ids and leave the real curve run behind."""
        deck = ("*KEYWORD\n"
                + _fabric_mat(form=14, fvopt=-1.0,
                              curves=(101, 102, 103, 0, 0, 0)))
        b = [x for x in _parse_str(deck) if x.keyword == "MAT_FABRIC"][0]
        leakage = b.raw[3]
        _offset_block(b, _OFFSET_SPECS["MAT_FABRIC"],
                      {"m": 1000, "f": 500}, lambda *_a: None)
        self.assertEqual(b.raw[3], leakage, "the leakage card is DATA")
        self.assertEqual([int(b.raw[6][i * 10:(i + 1) * 10] or 0)
                          for i in range(3)], [601, 602, 603])
        # and the un-shifted line (where card 7 would be without card 4)
        # keeps its own contents
        self.assertEqual(int(b.raw[5][0:10] or 0), 0)

    def test_the_form_set_comes_from_one_place(self):
        """``_off_mat_fabric`` reads ``state.FABRIC_CURVE_FORMS``, the set the
        parser and ``_fabric_law`` also read — two sources for one set is the
        #116 drift."""
        import inspect
        from k2rad import assembly
        src = inspect.getsource(assembly._off_mat_fabric)
        self.assertIn("FABRIC_CURVE_FORMS", src)
        self.assertNotIn("(4, 14, -14, 24)", src)

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


class TestAirbagIncludeTransformOffsets(unittest.TestCase):
    """``*INCLUDE_TRANSFORM`` id offsets for the airbag family.

    A missing offset spec is the #119 class of bug: the include moves the
    REFERENCE and leaves the definition behind (or the other way round), and
    the airbag then points at the parent deck's part set. Every model is
    registered from the same dict ``handlers.py`` dispatches on, so a model
    cannot be readable and un-offsettable.
    """

    def _blocks(self, deck: str, keyword: str):
        return [b for b in _parse_str(deck) if b.keyword == keyword]

    def test_every_airbag_keyword_has_a_spec(self):
        from k2rad.handlers import _AIRBAG_MODELS
        for kw in _AIRBAG_MODELS:
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)
        for kw in ("AIRBAG_REFERENCE_GEOMETRY",
                   "AIRBAG_REFERENCE_GEOMETRY_ID_BIRTH",
                   "AIRBAG_REFERENCE_GEOMETRY_BIRTH_RDT",
                   "AIRBAG_SHELL_REFERENCE_GEOMETRY",
                   "AIRBAG_SHELL_REFERENCE_GEOMETRY_ID_RDT"):
            with self.subTest(kw=kw):
                self.assertIn(kw, _OFFSET_SPECS)
        # A TRAILING _ID is stripped by parser._split_keyword into
        # block.options, so it never reaches the dispatcher OR the offset
        # table — and the two tables must agree about that.
        self.assertNotIn("AIRBAG_SHELL_REFERENCE_GEOMETRY_ID", _OFFSET_SPECS)
        self.assertNotIn("AIRBAG_SHELL_REFERENCE_GEOMETRY_ID", HANDLERS)

    def test_sid_rbid_and_the_curve_slots_move(self):
        deck = "*KEYWORD\n" + _spv(sid=7, lcid=90, lciddr=91, rbid=0)
        b = self._blocks(deck, "AIRBAG_SIMPLE_PRESSURE_VOLUME")[0]
        _offset_block(b, _OFFSET_SPECS["AIRBAG_SIMPLE_PRESSURE_VOLUME"],
                      {"s": 100, "f": 500, "r": 7000, "p": 20},
                      lambda *_a: None)
        self.assertEqual(int(b.raw[0][0:10]), 7011)      # ABID  -> IDROFF
        self.assertEqual(int(b.raw[1][0:10]), 107)       # SID   -> IDSOFF
        self.assertEqual(int(b.raw[2][20:30]), 590)      # LCID  -> IDFOFF
        self.assertEqual(int(b.raw[2][30:40]), 591)      # LCIDDR

    def test_the_rbid_cards_do_not_desync_the_curve_offset(self):
        """RBID != 0 pushes card 3 down by up to six lines. A declarative spec
        would rewrite a sensor's acceleration magnitude as a curve id."""
        sensor = (_c10(9.81) + _c10(0.0) + _c10(0.0) + _c10(9.81)
                  + _c10(0.001) + "\n"
                  + _c10(1.0) + _c10(0.0) + _c10(0.0) + _c10(1.0) + "\n"
                  + _c10(2.0) + _c10(0.0) + _c10(0.0) + _c10(2.0) + "\n")
        deck = ("*KEYWORD\n"
                + _spv(sid=7, lcid=90, rbid=-3, rbid_cards=sensor))
        b = self._blocks(deck, "AIRBAG_SIMPLE_PRESSURE_VOLUME")[0]
        before = list(b.raw)
        _offset_block(b, _OFFSET_SPECS["AIRBAG_SIMPLE_PRESSURE_VOLUME"],
                      {"s": 100, "f": 500, "r": 0, "p": 20}, lambda *_a: None)
        self.assertEqual(b.raw[2:5], before[2:5], "the sensor cards are data")
        self.assertEqual(int(b.raw[1][0:10]), 107)       # SID
        self.assertEqual(int(b.raw[1][20:30]), -3)       # RBID stays negative
        self.assertEqual(int(b.raw[5][20:30]), 590)      # LCID on card 3

    def test_linear_fluid_moves_all_six_curve_slots(self):
        deck = "*KEYWORD\n" + _lfluid(lcint=1, lcoutt=2, lcoutp=3, lcfit=4,
                                      lcbulk=5, lcid=6, p_limlc=7)
        b = self._blocks(deck, "AIRBAG_LINEAR_FLUID")[0]
        _offset_block(b, _OFFSET_SPECS["AIRBAG_LINEAR_FLUID"],
                      {"s": 100, "f": 500, "r": 0}, lambda *_a: None)
        self.assertEqual([int(b.raw[2][i * 10:(i + 1) * 10] or 0)
                          for i in range(2, 8)],
                         [501, 502, 503, 504, 505, 506])
        self.assertEqual(int(b.raw[3][10:20]), 507)      # P_LIMLC on card 4

    def test_negative_curve_sentinels_keep_their_sign(self):
        """SPV's CN and the SIMPLE_AIRBAG_MODEL's MU/AREA hold a curve id only
        when NEGATIVE; a positive value there is physics and must not move."""
        deck = "*KEYWORD\n" + _spv(cn=-90.0)
        b = self._blocks(deck, "AIRBAG_SIMPLE_PRESSURE_VOLUME")[0]
        _offset_block(b, _OFFSET_SPECS["AIRBAG_SIMPLE_PRESSURE_VOLUME"],
                      {"f": 500}, lambda *_a: None)
        self.assertEqual(int(float(b.raw[2][0:10])), -590)
        deck = "*KEYWORD\n" + _spv(cn=0.5)
        b = self._blocks(deck, "AIRBAG_SIMPLE_PRESSURE_VOLUME")[0]
        _offset_block(b, _OFFSET_SPECS["AIRBAG_SIMPLE_PRESSURE_VOLUME"],
                      {"f": 500}, lambda *_a: None)
        self.assertAlmostEqual(float(b.raw[2][0:10]), 0.5)

    def test_reference_geometry_node_ids_move_and_the_coordinates_do_not(self):
        """The rows are ``NID(I10) X(E20) Y(E20) Z(E20)`` — TWENTY-column
        coordinates, not *NODE's sixteen — so only columns 1-10 may be
        rewritten. The coordinates are literal geometry a TRANID would have to
        move, which is why the keyword is in _POINT_BEARING."""
        from k2rad.assembly import _POINT_BEARING
        deck = "*KEYWORD\n" + _ref_nodes()
        b = self._blocks(deck, "AIRBAG_REFERENCE_GEOMETRY")[0]
        _offset_block(b, _OFFSET_SPECS["AIRBAG_REFERENCE_GEOMETRY"],
                      {"n": 1000}, lambda *_a: None)
        self.assertEqual([int(ln[0:10]) for ln in b.raw],
                         [1001, 1002, 1003, 1004])
        self.assertAlmostEqual(float(b.raw[2][10:30]), 5.0)
        self.assertIn("AIRBAG_REFERENCE_GEOMETRY", _POINT_BEARING)
        self.assertIn("AIRBAG_REFERENCE_GEOMETRY_ID_BIRTH", _POINT_BEARING)

    def test_reference_geometry_id_and_birth_cards_do_not_shift_the_rows(self):
        deck = "*KEYWORD\n" + _ref_nodes(sx=2.0, sy=2.0, sz=1.0, nid0=1,
                                         birth=0.002)
        b = self._blocks(deck, "AIRBAG_REFERENCE_GEOMETRY_ID_BIRTH")[0]
        _offset_block(b,
                      _OFFSET_SPECS["AIRBAG_REFERENCE_GEOMETRY_ID_BIRTH"],
                      {"n": 1000}, lambda *_a: None)
        self.assertEqual(int(b.raw[0][40:50]), 1001)     # NIDO
        self.assertAlmostEqual(float(b.raw[1][0:10]), 0.002)  # BIRTH untouched
        self.assertEqual([int(ln[0:10]) for ln in b.raw[2:]],
                         [1001, 1002, 1003, 1004])

    def test_shell_reference_geometry_splits_element_part_and_nodes(self):
        deck = ("*KEYWORD\n*AIRBAG_SHELL_REFERENCE_GEOMETRY\n"
                + _c10(1) + _c10(2) + _c10(11) + _c10(12) + _c10(13)
                + _c10(14) + "\n")
        b = self._blocks(deck, "AIRBAG_SHELL_REFERENCE_GEOMETRY")[0]
        _offset_block(b, _OFFSET_SPECS["AIRBAG_SHELL_REFERENCE_GEOMETRY"],
                      {"e": 10000, "p": 200, "n": 1000}, lambda *_a: None)
        self.assertEqual([int(b.raw[0][i * 10:(i + 1) * 10])
                          for i in range(6)],
                         [10001, 202, 1011, 1012, 1013, 1014])


def _parse_str(deck: str):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "d.k")
    with open(path, "w") as fh:
        fh.write(deck)
    blocks = parse_k_file(path)
    tmp.cleanup()
    return blocks


# ═════════════════════════════════════════════════════════════════════════════
# The surface: element-backed, measured, and never a /SURF/SEG
# ═════════════════════════════════════════════════════════════════════════════

def _spv(sid=7, sidtyp=1, cn=0.02068427, beta=1.0, lcid=0, lciddr=0,
         rbid=0, vsca=1.0, psca=1.0, vini=0.0, mwd=0.0, spsf=0.0,
         with_id=True, rbid_cards="", abid=11):
    c = _c10
    if with_id:
        head = ("*AIRBAG_SIMPLE_PRESSURE_VOLUME_ID\n" + f"{abid:>10}"
                + "spv bag".rjust(30) + "\n")
    else:
        head = "*AIRBAG_SIMPLE_PRESSURE_VOLUME\n"
    return (head
            + c(sid) + c(sidtyp) + c(rbid) + c(vsca) + c(psca) + c(vini)
            + c(mwd) + c(spsf) + "\n"
            + rbid_cards
            + c(cn) + c(beta) + c(lcid) + c(lciddr) + "\n")


def _box_deck(*extra, mesh=None):
    return ("*KEYWORD\n" + (mesh or _MESH_CLOSED_BOX) + "".join(extra) + _TERM)


class TestMonvolSurface(unittest.TestCase):

    def test_surface_is_element_backed_never_a_seg_surface(self):
        """/SURF/SEG is starter ERROR 18 ("SURFACE ID IS NOT DEFINED WITH
        SHELLS") plus ERROR 54 and the run ABORTS: check_surf.F:55-62 sets
        ISH4N3N only for ELTYP 3 and 7, and tsurftag.F:293 resolves a segment
        surface back to no element at all."""
        _r, starter, _e = _convert(_box_deck(_spv()))
        self.assertNotIn("/SURF/SEG/", starter)
        surf = _block(starter, "/SURF/GRSHEL/")
        grp = _block(starter, "/GRSHEL/SHEL/")
        self.assertEqual(_col_i(_cards(surf)[0], 1, 10),
                         int(grp[0].rsplit("/", 1)[1]))
        self.assertEqual(sorted(int(t) for t in _cards(grp)[0].split()),
                         [1, 2, 3, 4, 5, 6])
        monvol = _cards(_block(starter, "/MONVOL/PRES/"))
        self.assertEqual(_col_i(monvol[0], 1, 10),
                         int(surf[0].rsplit("/", 1)[1]))

    def test_segment_set_resolves_to_its_owning_shells(self):
        """SIDTYP=0 is a *SET_SEGMENT — the COMMON case — and the segments are
        mapped back to the shells that own them so the surface stays
        element-backed. The corner-node SET identifies the shell: a segment's
        start corner and winding are free variables, and a monitored volume's
        surface is oriented by the starter anyway."""
        segset = """\
*SET_SEGMENT
         9
       1.0       1.0       1.0       1.0
         1         4         3         2
         5         6         7         8
         1         2         6         5
         2         3         7         6
         3         4         8         7
         4         1         5         8
"""
        _r, starter, _e = _convert(_box_deck(segset, _spv(sid=9, sidtyp=0)))
        self.assertNotIn("/SURF/SEG/", starter)
        grp = _block(starter, "/GRSHEL/SHEL/")
        self.assertEqual(sorted(int(t) for t in _cards(grp)[0].split()),
                         [1, 2, 3, 4, 5, 6])

    def test_reversed_segment_still_finds_its_shell(self):
        """The segment's winding is not the key — the corner-node SET is."""
        segset = ("*SET_SEGMENT\n         9\n"
                  "       1.0       1.0       1.0       1.0\n"
                  "         2         3         4         1\n")
        _r, starter, _e = _convert(_box_deck(segset, _spv(sid=9, sidtyp=0)))
        grp = _block(starter, "/GRSHEL/SHEL/")
        self.assertEqual([int(t) for t in _cards(grp)[0].split()], [1])

    def test_quads_and_tris_get_separate_groups_under_a_surf_surf(self):
        """A /GRSHEL/SHEL group resolves only 4-node /SHELL ids; a /SH3N id put
        in one is starter ERROR 70, not a soft loss."""
        mesh = _MESH_CLOSED_BOX.replace(
            "       6       1       4       1       5       8\n",
            "       6       1       4       1       5       8\n"
            "       7       1       1       2       3\n")
        _r, starter, _e = _convert(_box_deck(_spv(), mesh=mesh))
        quad = _block(starter, "/GRSHEL/SHEL/")
        tri = _block(starter, "/GRSH3N/SH3N/")
        self.assertEqual([int(t) for t in _cards(tri)[0].split()], [7])
        self.assertNotIn(7, [int(t) for t in _cards(quad)[0].split()])
        wrap = _cards(_block(starter, "/SURF/SURF/"))
        self.assertEqual(len(wrap[0].split()), 2)

    def test_sidtyp_falls_back_when_the_named_family_is_absent(self):
        """r14 corpus deck introduction/intro-by-a.-tabiei/misc/airbag-i/
        volume.k writes SIDTYP=0 and then defines *SET_PART_LIST 11 and
        *SET_NODE_LIST 11 and no segment set at all. LS-DYNA's set-id
        namespaces are per family, so both can exist and only SIDTYP says
        which; falling back is the difference between converting that bag and
        dropping it."""
        r, starter, _e = _convert(_box_deck(_spv(sid=7, sidtyp=0)))
        self.assertIn("/MONVOL/PRES/", starter)
        self.assertTrue(_warns(r, "SIDTYP=0 says the set is a *SET_SEGMENT"))

    def test_missing_set_drops_the_bag_loudly(self):
        r, starter, _e = _convert(_box_deck(_spv(sid=999)))
        self.assertNotIn("/MONVOL/", starter)
        self.assertTrue(_warns(r, "no shell element resolved"))

    def test_solid_part_in_the_scope_is_named_not_emitted(self):
        """A /MONVOL surface over solids is ERROR 18 and aborts the run."""
        mesh = _MESH_CLOSED_BOX.replace(
            "*SET_PART_LIST\n"
            "         7       0.0       0.0       0.0       0.0MECH\n"
            "         1\n",
            "*PART\n"
            "brick\n"
            "         2         2         1\n"
            "*SECTION_SOLID\n"
            "         2         1\n"
            "*ELEMENT_SOLID\n"
            "      99       2\n"
            "       1       2       3       4       5       6       7       8\n"
            "*SET_PART_LIST\n"
            "         7       0.0       0.0       0.0       0.0MECH\n"
            "         1         2\n")
        r, starter, _e = _convert(_box_deck(_spv(), mesh=mesh))
        self.assertIn("/MONVOL/PRES/", starter)
        self.assertTrue(_warns(r, "carry NO SHELL elements"))
        self.assertTrue(_warns(r, "ERROR 18"))


class TestSurfaceVolumeAndClosure(unittest.TestCase):
    """The conversion-time surface check. k2rad does NOT reorient anything —
    every MONVOL reader runs MONVOL_ORIENT_SURF and then MONVOL_REVERSE_NORMALS
    (``IF (VOL < ZERO)`` flip everything), so a converter-side flip would be a
    second correction of an already-correct surface. What is done instead is to
    MEASURE, with the engine's own formula, and report."""

    def _vol(self, deck):
        state = _dispatch(deck)
        from k2rad.writer.monvol import _surface_volume_and_edges
        eids = sorted(e.eid for e in state.shell_elems)
        return _surface_volume_and_edges(state, eids)

    def test_closed_box_volume_is_exact(self):
        """V = sum (1/3)(N . c) with N = half*(x13 x x24) — the engine's own
        expression, get_volume_area.F90:156-169. A 10 x 10 x 10 box is 1000."""
        vol, free, nonman, nseg = self._vol("*KEYWORD\n" + _MESH_CLOSED_BOX
                                            + _TERM)
        self.assertAlmostEqual(vol, 1000.0, places=9)
        self.assertEqual((free, nonman, nseg), (0, 0, 6))

    def test_inward_winding_gives_a_negative_volume_and_is_only_reported(self):
        """MONVOL_REVERSE_NORMALS corrects it, so the node order is passed
        through untouched and the sign is reported, not fixed."""
        flipped = []
        for ln in _MESH_CLOSED_BOX.splitlines():
            f = ln.split()
            if (len(f) == 6 and ln.startswith("       ") and f[0].isdigit()
                    and int(f[0]) <= 6 and f[1] == "1"):
                f = [f[0], f[1], f[2], f[5], f[4], f[3]]
                ln = "".join(x.rjust(8) for x in f)
            flipped.append(ln)
        deck = "*KEYWORD\n" + "\n".join(flipped) + "\n" + _TERM
        vol, free, nonman, _n = self._vol(deck)
        self.assertAlmostEqual(vol, -1000.0, places=9)
        self.assertEqual((free, nonman), (0, 0))
        r, starter, _e = _convert(deck.replace("*CONTROL_TERMINATION",
                                               _spv() + "*CONTROL_TERMINATION"))
        self.assertTrue(_warns(r, "wound INWARD"))
        # the connectivity is UNCHANGED — the starter does the flipping
        self.assertIn("         1         1         2         3         4",
                      starter)

    def test_open_surface_counts_its_free_edges_and_warns(self):
        mesh = _MESH_CLOSED_BOX.replace(
            "       1       1       1       4       3       2\n", "")
        vol, free, nonman, nseg = self._vol("*KEYWORD\n" + mesh + _TERM)
        self.assertEqual((free, nonman, nseg), (4, 0, 5))
        r, _s, _e = _convert(_box_deck(_spv(), mesh=mesh))
        self.assertTrue(_warns(r, "NOT CLOSED"))
        self.assertTrue(_warns(r, "WARNING 1875"))

    def test_t_connection_is_reported_as_unorientable(self):
        """MONVOL_ORIENT_SURF gives up on a T-connection (WARNING 1882) and
        MONVOL_REVERSE_NORMALS then returns immediately, so the normals stay
        as written and the volume can come out wrong."""
        mesh = _MESH_CLOSED_BOX.replace(
            "       6       1       4       1       5       8\n",
            "       6       1       4       1       5       8\n"
            "       7       1       1       2       3       4\n")
        _vol, free, nonman, _n = self._vol("*KEYWORD\n" + mesh + _TERM)
        self.assertEqual(nonman, 4)
        r, _s, _e = _convert(_box_deck(_spv(), mesh=mesh))
        self.assertTrue(_warns(r, "T-connections"))


# ═════════════════════════════════════════════════════════════════════════════
# /MONVOL/PRES
# ═════════════════════════════════════════════════════════════════════════════

class TestMonvolPres(unittest.TestCase):

    def test_spv_law_is_exact_via_fscale_on_a_unit_slope_function(self):
        """LS-DYNA: ``Pressure = BETA*CN / (V/V0)`` (Vol I R16 p.3-10), i.e.
        ``p = BETA*CN*V0/V``. Radioss Itypfun=0 feeds the function exactly
        ``V0/V`` (volpfv.F: XFUN = (V0-VINC)/(VOL-VINC)), so a UNIT-SLOPE
        function with Fscale = BETA*CN is the law itself, with no assumption
        about V0 at all. dyna2rad bakes BETA*CN*x into a 27-point table and is
        right only when V0 == 1 in deck units."""
        _r, starter, _e = _convert(_box_deck(_spv(cn=0.5, beta=3.0)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertEqual(len(cards), 3)
        self.assertAlmostEqual(_col_f(cards[1], 1, 20), 0.0)     # Ascalet
        fct = _col_i(cards[2], 1, 10)
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 1.5)    # BETA*CN
        self.assertEqual(_col_i(cards[2], 41, 50), 0)            # Itypfun
        pts = _cards(_block(starter, f"/FUNCT/{fct}"))
        self.assertEqual([(_col_f(p, 1, 20), _col_f(p, 21, 40)) for p in pts],
                         [(0.0, 0.0), (1.0, 1.0)])

    def test_blank_beta_defaults_to_one(self):
        _r, starter, _e = _convert(_box_deck(_spv(cn=0.25, beta=0.0)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 0.25)

    def test_lcid_wins_and_is_relative_volume(self):
        """An "Optional load curve ID defining pressure as a function of
        RELATIVE VOLUME" is Radioss Itypfun=2, XFUN = V/V0. The curve is
        referenced as-is, and CN/BETA are ignored exactly as LS-DYNA ignores
        them."""
        curve = ("*DEFINE_CURVE\n        90\n"
                 "                 1.0                 0.0\n"
                 "                 2.0            100000.0\n")
        r, starter, _e = _convert(_box_deck(curve, _spv(lcid=90, cn=9.0,
                                                        beta=9.0)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertEqual(_col_i(cards[2], 1, 10), 90)
        self.assertEqual(_col_i(cards[2], 41, 50), 2)
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 0.0)   # Fscale default
        self.assertTrue(_warns(r, "LS-DYNA ignores CN and BETA"))

    def test_negative_cn_is_a_time_curve_over_volume(self):
        """CN < 0: |CN| is the curve giving CN(t). Radioss Itypfun=3 is
        "P = (1/V) F(T)" — the one slot that evaluates a TIME function and
        multiplies by V0/V, i.e. LS-DYNA's p = BETA*CN(t)*V0/V exactly."""
        curve = ("*DEFINE_CURVE\n        90\n"
                 "                 0.0                 0.0\n"
                 "               0.001                 1.0\n")
        r, starter, _e = _convert(_box_deck(curve, _spv(cn=-90.0, beta=2.0)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertEqual(_col_i(cards[2], 1, 10), 90)
        self.assertEqual(_col_i(cards[2], 41, 50), 3)
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 2.0)
        self.assertTrue(_warns(r, "Itypfun=3"))

    def test_psca_folds_into_fscale(self):
        _r, starter, _e = _convert(_box_deck(_spv(cn=2.0, beta=1.0, psca=0.5)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 1.0)

    def test_load_curve_is_pressure_versus_time(self):
        curve = ("*DEFINE_CURVE\n        90\n"
                 "                 0.0                 0.0\n"
                 "               0.001            250000.0\n")
        body = ("*AIRBAG_LOAD_CURVE_ID\n" + f"{13:>10}" + "lc bag".rjust(30)
                + "\n" + _c10(7) + _c10(1) + _c10(0) + _c10(1.0) + _c10(1.0)
                + _c10(0.0) + _c10(0.0) + _c10(0.0) + "\n"
                + _c10(0.0) + _c10(90) + "\n")
        _r, starter, _e = _convert(_box_deck(curve, body))
        cards = _cards(_block(starter, "/MONVOL/PRES/13"))
        self.assertEqual(_col_i(cards[2], 1, 10), 90)     # curve as-is, STIME=0
        self.assertEqual(_col_i(cards[2], 41, 50), 1)     # Itypfun = f(t)

    def test_load_curve_stime_shifts_the_curve_and_zeroes_t0(self):
        """STIME has no /MONVOL/PRES column, so it is folded into a REBUILT
        curve: every abscissa +STIME and a (0, 0) point prepended so the
        pressure is exactly zero at t=0. dyna2rad prepends (-1, 0) instead,
        which leaves a NON-ZERO pressure at t=0 for any STIME > 1."""
        curve = ("*DEFINE_CURVE\n        90\n"
                 "                 0.0            100000.0\n"
                 "               0.001            250000.0\n")
        body = ("*AIRBAG_LOAD_CURVE\n"
                + _c10(7) + _c10(1) + _c10(0) + _c10(1.0) + _c10(1.0)
                + _c10(0.0) + _c10(0.0) + _c10(0.0) + "\n"
                + _c10(0.002) + _c10(90) + "\n")
        r, starter, _e = _convert(_box_deck(curve, body))
        cards = _cards(_block(starter, "/MONVOL/PRES/"))
        fct = _col_i(cards[2], 1, 10)
        self.assertNotEqual(fct, 90)
        pts = [(_col_f(p, 1, 20), _col_f(p, 21, 40))
               for p in _cards(_block(starter, f"/FUNCT/{fct}"))]
        self.assertEqual(pts, [(0.0, 0.0), (0.002, 100000.0),
                               (0.003, 250000.0)])
        self.assertTrue(_warns(r, "leading (0, 0) point"))

    def test_load_curve_without_lcid_is_dropped_by_name(self):
        body = ("*AIRBAG_LOAD_CURVE\n"
                + _c10(7) + _c10(1) + "\n" + _c10(0.0) + _c10(0) + "\n")
        r, starter, _e = _convert(_box_deck(body))
        self.assertNotIn("/MONVOL/", starter)
        self.assertTrue(_warns(r, "P = C*rho*(T - T0)"))


# ═════════════════════════════════════════════════════════════════════════════
# /MONVOL/GAS
# ═════════════════════════════════════════════════════════════════════════════

def _agm(psf=1.0, lcid=0, gamma=1.4, p0=50000.0, pe=101325.0, ro=1.225,
         vini=0.0, vsca=1.0, sid=7):
    c = _c10
    return ("*AIRBAG_ADIABATIC_GAS_MODEL_ID\n" + f"{12:>10}" + "gas bag".rjust(30)
            + "\n" + c(sid) + c(1) + c(0) + c(vsca) + c(1.0) + c(vini)
            + c(0.0) + c(0.0) + "\n"
            + c(psf) + c(lcid) + c(gamma) + c(p0) + c(pe) + c(ro) + "\n")


class TestMonvolGas(unittest.TestCase):

    def test_gas_card_columns_and_the_gauge_to_absolute_conversion(self):
        """LS-DYNA states ``e_0 = (p_0 + p_e)/(rho(gamma-1))`` (Vol I R16
        p.3-18), i.e. **P0 is a GAUGE pressure**; Radioss feeds Pini straight
        into ``EI = PINI*(V+VEPS-VINC)/(GAMMA-1)`` and applies
        ``DP = Q + PRES - PEXT``, so Pini is ABSOLUTE. Pini = P0 + PE.
        dyna2rad writes PSF*P0 and adds no PE — one atmosphere short on any SI
        deck."""
        _r, starter, _e = _convert(_box_deck(_agm(vini=2.5)))
        cards = _cards(_block(starter, "/MONVOL/GAS/12"))
        self.assertEqual(len(cards), 5)
        self.assertEqual(_col_i(cards[0], 11, 20), 0)             # I_equi
        self.assertAlmostEqual(_col_f(cards[2], 1, 20), 1.4)      # Gamma
        self.assertAlmostEqual(_col_f(cards[2], 21, 40), 0.0)     # Mu -> 0.01
        self.assertAlmostEqual(_col_f(cards[2], 81, 100), 1.225)  # Rhoi
        self.assertAlmostEqual(_col_f(cards[3], 1, 20), 101325.0)  # Pext
        self.assertAlmostEqual(_col_f(cards[3], 21, 40), 151325.0)  # Pini
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 0.0)     # Pmax -> INF
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 2.5)     # Vinc
        self.assertEqual(_col_i(cards[4], 1, 10), 0)              # Nvent

    def test_vini_is_the_incompressible_volume_scaled_by_vsca(self):
        """Vol I p.3-4, verbatim: ``V_cvolume = (VSCA x V_femodel) - VINI``.
        VINI is subtracted AFTER the volume scale, so in model units it is
        VINI/VSCA — the Radioss Vinc."""
        _r, starter, _e = _convert(_box_deck(_agm(vini=4.0, vsca=2.0)))
        cards = _cards(_block(starter, "/MONVOL/GAS/12"))
        self.assertAlmostEqual(_col_f(cards[3], 61, 80), 2.0)

    def test_gamma_one_and_zero_are_refused_by_name(self):
        for gamma, needle in ((1.0, "ERROR 641"), (0.0, "not a usable ratio")):
            with self.subTest(gamma=gamma):
                r, starter, _e = _convert(_box_deck(_agm(gamma=gamma)))
                self.assertNotIn("/MONVOL/GAS/", starter)
                self.assertTrue(_warns(r, needle))

    def test_psf_and_lcid_are_named_as_dropped(self):
        r, _s, _e = _convert(_box_deck(_agm(psf=0.5, lcid=77)))
        self.assertTrue(_warns(r, "PSF=0.5"))
        self.assertTrue(_warns(r, "preload flag curve"))

    def test_ro_is_carried_not_dropped(self):
        """dyna2rad drops RO unconditionally, which leaves the starter unable
        to form the gas's Cv (RVOLU(19) is only computed when RHOI != 0)."""
        r, starter, _e = _convert(_box_deck(_agm(ro=0.0)))
        cards = _cards(_block(starter, "/MONVOL/GAS/12"))
        self.assertAlmostEqual(_col_f(cards[2], 81, 100), 0.0)
        self.assertTrue(_warns(r, "RO=0"))


# ═════════════════════════════════════════════════════════════════════════════
# /MONVOL/AIRBAG1 + /MAT/GAS + /PROP/INJECT1
# ═════════════════════════════════════════════════════════════════════════════

def _sam(cv=0.0, cp=0.0, t=1200.0, lcid=90, mu=0.7, area=25.0, pe=0.101325,
         ro=0.0, lou=0, t_ext=295.0, a=29.26, b=0.0022, mw=0.0289644,
         gasc=8.314, sid=7, with_id=True, vini=0.0, rbid=0, rbid_cards="",
         force_card4a=False, abid=11, keyword="AIRBAG_SIMPLE_AIRBAG_MODEL"):
    c = _c10
    if with_id:
        head = (f"*{keyword}_ID\n" + f"{abid:>10}"
                + "gas bag".rjust(30) + "\n")
    else:
        head = f"*{keyword}\n"
    card4 = (c(lou) if (cv != 0.0 and not force_card4a) else
             c(lou) + c(t_ext) + c(a) + c(b) + c(mw) + c(gasc))
    return (head
            + c(sid) + c(1) + c(rbid) + c(1.0) + c(1.0) + c(vini) + c(0.0)
            + c(0.0) + "\n"
            + rbid_cards
            + c(cv) + c(cp) + c(t) + c(lcid) + c(mu) + c(area) + c(pe)
            + c(ro) + "\n" + card4 + "\n")


_MASS_CURVE = ("*DEFINE_CURVE\n        90\n"
               "                 0.0                 0.0\n"
               "               0.001               0.005\n")


class TestGasGammaCheck(unittest.TestCase):
    """The derived-gamma check and the unit rescale it stands on.

    This is the one piece of the batch whose stated purpose is to catch a
    SILENT starter failure — ``GAMMA AT INITIAL TEMPERATURE = -3.61E-03`` with
    0 ERROR(S) and TERMINATION WITH WARNING — so it is the one piece that most
    needs a test of its own: the code path runs on every CV=0 bag, but nothing
    that only exercises the path can tell whether the arithmetic is right.
    """

    def test_radioss_gas_constant_reproduces_hm_read_matgas(self):
        """``R_IGC1 = R_IGC / FAC_M / FAC_L / FAC_L * FAC_T**2``
        (hm_read_matgas.F:293), with ``R_IGC = 8.314472``
        (common_source/modules/constant_mod.F:932 — NOT the textbook 8.314;
        the starter echoes MW = 2.8970286405876E-05 for a Cp-Cv of 287058.3,
        which is 8314.47/MW, not 8314.0/MW).

        The FAC_T**2 factor is the one a mutation can hide behind: it is 1.0
        in every second-based unit system, so only a ms deck sees it.
        """
        from k2rad.writer.monvol import _radioss_gas_constant
        from k2rad.state import ConversionState
        cases = [
            (("kg", "m", "s"), 8.314472),
            (("Mg", "mm", "s"), 8.314472e3),           # /1e3 /1e-3 /1e-3
            (("Mg", "mm", "ms"), 8.314472e3 * 1e-6),   # x (1e-3)^2
            (("g", "cm", "micro_s"), 8.314472 / 1e-3 / 1e-2 / 1e-2 * 1e-12),
        ]
        for units, expect in cases:
            with self.subTest(units=units):
                st = ConversionState()
                st.units = units
                self.assertAlmostEqual(
                    _radioss_gas_constant(st) / expect, 1.0, places=12)
        st = ConversionState()
        st.units = ("stone", "furlong", "fortnight")
        self.assertIsNone(_radioss_gas_constant(st))

    def test_si_gas_card_in_a_mm_deck_is_caught_with_the_numbers(self):
        """A/B/MW stated in SI while the mesh is in Mg/mm/s. Hand-computed:

            R_work = 8.314472 / 1e3 / 1e-3 / 1e-3        = 8314.472
            Cp     = 29.26/0.0289644 + (0.0022/0.0289644)*295
                   = 1010.2056 + 22.4068                 = 1032.6124
            R/MW   = 8314.472/0.0289644                  = 287058.32
            Cv     = 1032.6124 - 287058.32               = -286025.71
            gamma  = 1032.6124 / -286025.71              = -3.61021e-3

        The starter's own echo on that deck is -3.6102084432184E-03.
        """
        r, _s, _e = _convert(_box_deck(_MASS_CURVE, _sam()))
        hit = _warns(r, "not a usable ratio of specific heats")
        self.assertEqual(len(hit), 1, r.warnings)
        msg = hit[0]
        for token in ("1032.61", "287058", "-286026", "-0.00361021",
                      "8314.47"):
            with self.subTest(token=token):
                self.assertIn(token, msg)

    def test_a_consistent_gas_card_raises_nothing(self):
        """The same bag with A and MW restated in Mg/mm/s: Cp = 1.004e9
        mm^2/s^2/K, MW = 2.89644e-5 Mg/mol, so R/MW = 2.87058e8 and
        Cv = 7.1694e8 with gamma = 1.4005 — a real diatomic gas, no warning."""
        mw = 2.89644e-5
        a = 1.004e9 * mw                       # A is MOLAR: Cpa = A/MW
        r, _s, _e = _convert(
            _box_deck(_MASS_CURVE, _sam(a=a, b=0.0, mw=mw)))
        self.assertEqual(_warns(r, "not a usable ratio of specific heats"), [])

    def test_the_check_is_only_for_the_mass_branch(self):
        """/MAT/GAS/CSTA takes Cp and Cv directly and gamma is their unit-free
        ratio, so the same SI-vs-mm mismatch cannot produce a negative Cv
        there — the Cp > Cv screen covers it instead."""
        r, _s, _e = _convert(
            _box_deck(_MASS_CURVE, _sam(cv=717.5, cp=1004.5)))
        self.assertEqual(_warns(r, "not a usable ratio of specific heats"), [])
        self.assertIn("/MAT/GAS/CSTA/", _s)


class TestMonvolAirbag1(unittest.TestCase):

    def test_airbag1_card_columns(self):
        _r, starter, _e = _convert(_box_deck(_MASS_CURVE, _sam()))
        cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
        gas = _block(starter, "/MAT/GAS/MASS/")
        inj = _block(starter, "/PROP/INJECT1/")
        gas_id = int(gas[0].rsplit("/", 1)[1])
        inj_id = int(inj[0].rsplit("/", 1)[1])
        self.assertAlmostEqual(_col_f(cards[0], 21, 40), 0.0)      # Hconv
        self.assertEqual(_col_i(cards[2], 1, 10), gas_id)          # mat_ID
        self.assertAlmostEqual(_col_f(cards[2], 41, 60), 0.101325)  # Pext
        self.assertAlmostEqual(_col_f(cards[2], 61, 80), 295.0)    # T0
        self.assertEqual(_col_i(cards[2], 81, 90), 0)              # Iequi
        self.assertEqual(_col_i(cards[2], 91, 100), 0)             # Ittf
        self.assertEqual(_col_i(cards[3], 1, 10), 1)               # Njet
        self.assertEqual(_col_i(cards[4], 1, 10), inj_id)          # inject_ID
        self.assertEqual(_col_i(cards[5], 1, 10), 1)               # Nvent
        self.assertEqual(_col_i(cards[5], 11, 20), 0)              # Nporsurf

    def test_inject1_iflow_is_one_because_lcid_is_a_RATE(self):
        """THE catastrophic slot. airbaga1.F:349-362 reads the injector's mass
        function and branches on IFLU = IGEO(24) — with Iflow=0 the curve IS
        the accumulated mass and the engine DIFFERENCES it
        (``DGMASS = GMASS - GMASS_OLD``); with Iflow=1 it is dm/dt and the
        engine INTEGRATES it (``GMASS = GMASS*DT1 + GMASS_OLD``). LS-DYNA's
        LCID is a RATE ("Load curve ID specifying input mass flow rate",
        Vol I R16 p.3-13). Leaving Iflow at 0 is a silent factor-of-1/dt
        error with no starter diagnostic."""
        _r, starter, _e = _convert(_box_deck(_MASS_CURVE, _sam()))
        cards = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(cards[0], 1, 10), 1)         # N_gases
        self.assertEqual(_col_i(cards[0], 11, 20), 1)        # Iflow = RATE
        self.assertAlmostEqual(_col_f(cards[0], 21, 40), 1.0)  # Ascale_T
        self.assertEqual(_col_i(cards[1], 11, 20), 90)       # fun_ID_M = LCID
        tfct = _col_i(cards[1], 21, 30)
        pts = [(_col_f(p, 1, 20), _col_f(p, 21, 40))
               for p in _cards(_block(starter, f"/FUNCT/{tfct}"))]
        self.assertEqual(pts, [(0.0, 1200.0), (1.0, 1200.0)])

    def test_mat_gas_mass_divides_the_molar_coefficients_by_mw(self):
        """Vol I R16 p.3-16 Remark 3: with CV = 0, ``c_p = (a + bT)/MW`` — so
        card 4a's A and B are MOLAR (J/mol/K, J/mol/K^2) while /MAT/GAS wants a
        MASS-specific Cp polynomial. Radioss then derives Cv itself as
        ``CVI = CPI - R/MW``, which is why LS-DYNA's CV must never be written
        into a Cp slot."""
        _r, starter, _e = _convert(_box_deck(_MASS_CURVE, _sam()))
        cards = _cards(_block(starter, "/MAT/GAS/MASS/"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 0.0289644)   # MW
        self.assertAlmostEqual(_col_f(cards[1], 1, 20), 29.26 / 0.0289644,
                               places=4)                            # Cpa = A/MW
        self.assertAlmostEqual(_col_f(cards[1], 21, 40), 0.0022 / 0.0289644,
                               places=8)                            # Cpb = B/MW
        for a, b in ((41, 60), (61, 80), (81, 100)):
            self.assertAlmostEqual(_col_f(cards[1], a, b), 0.0)
        self.assertAlmostEqual(_col_f(cards[2], 1, 20), 0.0)         # Cpf

    def test_cv_nonzero_uses_mat_gas_csta_verbatim(self):
        """With CV != 0 LS-DYNA uses the card's CV and CP directly, both
        MASS-specific — which is exactly what /MAT/GAS/CSTA takes."""
        _r, starter, _e = _convert(
            _box_deck(_MASS_CURVE, _sam(cv=1119997.8, cp=1567738.8)))
        cards = _cards(_block(starter, "/MAT/GAS/CSTA/"))
        self.assertAlmostEqual(_col_f(cards[0], 1, 20), 1567738.8)   # Cp
        self.assertAlmostEqual(_col_f(cards[0], 21, 40), 1119997.8)  # Cv
        self.assertNotIn("/MAT/GAS/MASS/", starter)

    def test_csta_needs_cp_greater_than_cv(self):
        r, _s, _e = _convert(_box_deck(_MASS_CURVE, _sam(cv=2.0, cp=1.0)))
        self.assertTrue(_warns(r, "ERROR 917"))

    def test_card4_layout_branches_on_cv(self):
        """Card 4a (CV == 0) is ``LOU T_EXT A B MW GASC``; card 4b (CV != 0) is
        LOU alone. Both are ONE card, so nothing after it shifts — but reading
        4a's columns under CV != 0 would invent an ambient temperature and a
        molar Cp the deck never stated."""
        r, starter, _e = _convert(_box_deck(
            _MASS_CURVE, _sam(cv=1119997.8, cp=1567738.8, t_ext=350.0,
                              force_card4a=True)))
        cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
        self.assertAlmostEqual(_col_f(cards[2], 61, 80), 295.0,
                               msg="T_EXT does not exist on card 4b")
        self.assertTrue(_warns(r, "4b layout"))

    def test_vent_area_is_mu_times_area(self):
        _r, starter, _e = _convert(_box_deck(_MASS_CURVE,
                                             _sam(mu=0.7, area=25.0)))
        cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
        # vent card 1: surf_IDv | Iform | Avent | Bvent | ... | vent_title
        self.assertEqual(_col_i(cards[6], 1, 10), 0)     # whole-bag porosity
        self.assertEqual(_col_i(cards[6], 11, 20), 1)    # Iform = isenthalpic
        self.assertAlmostEqual(_col_f(cards[6], 21, 40), 17.5)
        self.assertAlmostEqual(_col_f(cards[6], 41, 60), 0.0)   # Bvent forced 0
        # vent card 2: Tstart = Tstop = dPdef = dtPdef = 0 -> open from t=0
        for a, b in ((1, 20), (21, 40), (41, 60), (61, 80)):
            self.assertAlmostEqual(_col_f(cards[7], a, b), 0.0)
        self.assertEqual(len(cards), 10)

    def test_no_vent_when_mu_times_area_is_zero(self):
        r, starter, _e = _convert(_box_deck(_MASS_CURVE, _sam(mu=0.0,
                                                              area=0.0)))
        cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
        self.assertEqual(_col_i(cards[5], 1, 10), 0)     # Nvent
        self.assertEqual(len(cards), 6)
        self.assertTrue(_warns(r, "NO VENT"))

    def test_negative_area_is_a_curve_shifted_to_gauge_pressure(self):
        """A negative AREA means |AREA| is a curve of exit area vs ABSOLUTE
        pressure; the Radioss vent's fct_IDP is a function of the GAUGE
        pressure P - Pext, so the abscissae shift by -PE."""
        curve = ("*DEFINE_CURVE\n        91\n"
                 "            0.101325                 0.0\n"
                 "            0.201325                50.0\n")
        r, starter, _e = _convert(_box_deck(_MASS_CURVE, curve,
                                            _sam(mu=0.7, area=-91.0)))
        cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
        self.assertAlmostEqual(_col_f(cards[6], 21, 40), 0.7)   # Avent = MU
        fct = _col_i(cards[8], 11, 20)                          # fct_IDP
        self.assertNotEqual(fct, 91)
        pts = [(_col_f(p, 1, 20), _col_f(p, 21, 40))
               for p in _cards(_block(starter, f"/FUNCT/{fct}"))]
        self.assertAlmostEqual(pts[0][0], 0.0)
        self.assertAlmostEqual(pts[1][0], 0.1)
        self.assertTrue(_warns(r, "GAUGE pressure"))

    def test_a_zero_partner_beside_a_vent_curve_is_a_CLOSED_orifice(self):
        """LS-DYNA's leak mass flow is proportional to mu*A, so a blank MU
        beside an AREA curve is an orifice that is CLOSED. Defaulting the
        missing constant to 1.0 vented a bag LS-DYNA seals, at the full curve
        area; the mirror case put a dimensionless porosity in the AREA slot."""
        curve = ("*DEFINE_CURVE\n        91\n"
                 "            0.101325                 0.0\n"
                 "            0.201325                50.0\n")
        for mu, area in ((0.0, -91.0), (-91.0, 0.0)):
            with self.subTest(mu=mu, area=area):
                r, starter, _e = _convert(
                    _box_deck(_MASS_CURVE, curve, _sam(mu=mu, area=area)))
                cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
                self.assertEqual(_col_i(cards[5], 1, 10), 0)   # Nvent
                self.assertEqual(len(cards), 6)
                self.assertTrue(_warns(r, "mu*A product is ZERO"), r.warnings)
        # ... and a NON-zero partner still opens the vent at that value
        _r, starter, _e = _convert(
            _box_deck(_MASS_CURVE, curve, _sam(mu=0.7, area=-91.0)))
        cards = _cards(_block(starter, "/MONVOL/AIRBAG1/11"))
        self.assertEqual(_col_i(cards[5], 1, 10), 1)
        self.assertAlmostEqual(_col_f(cards[6], 21, 40), 0.7)

    def test_a_zero_pe_is_named_because_the_starter_substitutes_one_atm(self):
        """``hm_read_monvol_type7.F:417-418``: a blank Pext is a REQUEST FOR
        ONE ATMOSPHERE, and :421/:536 then set PINI = PEXT and derive the
        initial gas mass from it. LS-DYNA's PE = 0 means the opposite — no
        ambient pressure at all. Measured: the starter echoes
        ``EXTERNAL PRESSURE = 0.1013250000000`` with 0 ERROR(S)."""
        r, _s, _e = _convert(_box_deck(_MASS_CURVE, _sam(pe=0.0)))
        self.assertTrue(_warns(r, "REQUEST FOR ONE ATMOSPHERE"), r.warnings)
        r, _s, _e = _convert(_box_deck(_MASS_CURVE, _sam(pe=0.101325)))
        self.assertFalse(_warns(r, "REQUEST FOR ONE ATMOSPHERE"))

    def test_lou_is_named_as_dropped(self):
        r, _s, _e = _convert(_box_deck(_MASS_CURVE,
                                       _sam(mu=0.0, area=0.0, lou=42)))
        self.assertTrue(_warns(r, "LOU=42"))


# ═════════════════════════════════════════════════════════════════════════════
# /MONVOL/LFLUID
# ═════════════════════════════════════════════════════════════════════════════

def _lfluid(bulk=2.11e9, ro=998.0, lcint=0, lcoutt=0, lcoutp=0, lcfit=0,
            lcbulk=0, lcid=0, p_limit=0.0, p_limlc=0, nonull=0, sid=7):
    c = _c10
    return ("*AIRBAG_LINEAR_FLUID_ID\n" + f"{14:>10}" + "fluid".rjust(30) + "\n"
            + c(sid) + c(1) + c(0) + c(1.0) + c(1.0) + c(0.0) + c(0.0)
            + c(0.0) + "\n"
            + c(bulk) + c(ro) + c(lcint) + c(lcoutt) + c(lcoutp) + c(lcfit)
            + c(lcbulk) + c(lcid) + "\n"
            + c(p_limit) + c(p_limlc) + c(nonull) + "\n")


class TestMonvolLfluid(unittest.TestCase):

    def test_lfluid_card_columns(self):
        _r, starter, _e = _convert(_box_deck(_lfluid()))
        cards = _cards(_block(starter, "/MONVOL/LFLUID/14"))
        self.assertEqual(len(cards), 6)
        self.assertAlmostEqual(_col_f(cards[2], 1, 20), 998.0)      # Rho
        # A scalar BULK rides its SCALE factor with fct_K = 0: volp_lfluid.F
        # reads ``BULK = SCALEF`` when the function id is 0.
        self.assertEqual(_col_i(cards[3], 1, 10), 0)                # fct_K
        self.assertAlmostEqual(_col_f(cards[3], 21, 40), 2.11e9)    # Fscale_K

    def test_curve_slots_map_one_to_one(self):
        curves = "".join(
            f"*DEFINE_CURVE\n{cid:>10}\n"
            "                 0.0                 1.0\n"
            "                 1.0                 2.0\n"
            for cid in (31, 32, 33, 34, 35))
        _r, starter, _e = _convert(_box_deck(
            curves, _lfluid(lcint=31, lcoutt=32, lcoutp=33, lcfit=34,
                            lcbulk=35)))
        cards = _cards(_block(starter, "/MONVOL/LFLUID/14"))
        self.assertEqual(_col_i(cards[3], 1, 10), 35)     # fct_K   <- LCBULK
        self.assertEqual(_col_i(cards[3], 11, 20), 31)    # fct_Mtin
        self.assertEqual(_col_i(cards[4], 1, 10), 32)     # fct_Mtout
        self.assertEqual(_col_i(cards[4], 11, 20), 33)    # fct_Mpout
        self.assertEqual(_col_i(cards[5], 1, 10), 34)     # fct_Padd

    def test_p_limit_goes_through_a_flat_function_not_the_scale_factor(self):
        """THE Pmax trap. hm_read_monvol_type10.F overwrites the scale factor
        whenever no function is given::

            IF (IFPMAX > 0) THEN
               IF (SFPMAX == ZERO) SFPMAX = ONE * FAC_GEN
            ELSE
               SFPMAX = INFINITY * FAC_GEN

        Measured: fct_Pmax = 0 with Fscale_Pmax = 5.5E+06 echoes
        ``MAXIMUM PRESSURE TIME FUNCTION SCALE FACTOR = 1.0000000200409E+20``.
        A constant P_LIMIT therefore cannot be set through the scale factor at
        all — unlike Fscale_Padd, which IS honoured with fct_Padd = 0."""
        _r, starter, _e = _convert(_box_deck(_lfluid(p_limit=5.5e6)))
        cards = _cards(_block(starter, "/MONVOL/LFLUID/14"))
        fct = _col_i(cards[5], 11, 20)
        self.assertNotEqual(fct, 0)
        pts = [(_col_f(p, 1, 20), _col_f(p, 21, 40))
               for p in _cards(_block(starter, f"/FUNCT/{fct}"))]
        self.assertEqual(pts, [(0.0, 5.5e6), (1.0, 5.5e6)])

    def test_p_limlc_wins_over_p_limit(self):
        curve = ("*DEFINE_CURVE\n        40\n"
                 "                 0.0             1.0E+06\n"
                 "                 1.0             2.0E+06\n")
        _r, starter, _e = _convert(_box_deck(curve,
                                             _lfluid(p_limit=5.5e6,
                                                     p_limlc=40)))
        cards = _cards(_block(starter, "/MONVOL/LFLUID/14"))
        self.assertEqual(_col_i(cards[5], 11, 20), 40)

    def test_dangling_curve_reference_is_named(self):
        r, _s, _e = _convert(_box_deck(_lfluid(lcint=777)))
        self.assertTrue(_warns(r, "ERROR 9"))

    def test_lcid_and_nonull_are_named_as_dropped(self):
        r, _s, _e = _convert(_box_deck(_lfluid(lcid=55, nonull=1)))
        self.assertTrue(_warns(r, "LCID=55"))
        self.assertTrue(_warns(r, "NONULL=1"))


# ═════════════════════════════════════════════════════════════════════════════
# The card walks: RBID, blank cards, and the *AIRBAG grammar
# ═════════════════════════════════════════════════════════════════════════════

class TestAirbagCardWalk(unittest.TestCase):
    """The #119 rule on a keyword whose card-3 index moves by up to six lines.

    RBID > 0 inserts card 2a (N) plus ceil(N/5) constant cards; RBID < 0
    inserts three sensor cards. A fixed ``offset + 1`` would read the sensor's
    acceleration magnitudes as the model's thermodynamic constants.
    """

    def test_rbid_zero_reads_card3_immediately(self):
        _r, starter, _e = _convert(_box_deck(_spv(cn=0.5, beta=2.0, rbid=0)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 1.0)

    def test_rbid_positive_skips_the_constant_cards(self):
        for n, ncards in ((1, 1), (5, 1), (6, 2), (11, 3), (0, 0)):
            with self.subTest(n=n):
                extra = _c10(n) + "\n" + ("".join(_c10(1.0) for _ in range(5))
                                          + "\n") * ncards
                r, starter, _e = _convert(
                    _box_deck(_spv(cn=0.5, beta=2.0, rbid=3,
                                   rbid_cards=extra)))
                cards = _cards(_block(starter, "/MONVOL/PRES/11"))
                self.assertAlmostEqual(_col_f(cards[2], 11, 30), 1.0)
                self.assertTrue(_warns(r, "RBID=3"))

    def test_rbid_negative_skips_the_three_sensor_cards(self):
        sensor = (_c10(9.81) + _c10(0.0) + _c10(0.0) + _c10(9.81)
                  + _c10(0.001) + "\n"
                  + _c10(1.0) + _c10(0.0) + _c10(0.0) + _c10(1.0) + "\n"
                  + _c10(2.0) + _c10(0.0) + _c10(0.0) + _c10(2.0) + "\n")
        r, starter, _e = _convert(_box_deck(_spv(cn=0.5, beta=2.0, rbid=-3,
                                                 rbid_cards=sensor)))
        cards = _cards(_block(starter, "/MONVOL/PRES/11"))
        self.assertAlmostEqual(_col_f(cards[2], 11, 30), 1.0,
                               msg="card 3 must not be read from the sensor "
                                   "cards")
        self.assertTrue(_warns(r, "SENSOR"))

    def test_vsca_psca_vini_mwd_spsf_are_each_named(self):
        r, _s, _e = _convert(_box_deck(_spv(vsca=2.0, psca=3.0, vini=1.0,
                                            mwd=150.0, spsf=0.5)))
        self.assertTrue(_warns(r, "VSCA=2"))
        self.assertTrue(_warns(r, "VINI=1"))
        self.assertTrue(_warns(r, "MWD=150"))
        self.assertTrue(_warns(r, "SPSF=0.5"))

    def test_id_option_carries_the_id_and_the_title(self):
        _r, starter, _e = _convert(_box_deck(_spv()))
        blk = _block(starter, "/MONVOL/PRES/11")
        self.assertEqual(blk[1], "spv bag")

    def test_without_id_the_monvol_is_renumbered_off_the_auto_stream(self):
        _r, starter, _e = _convert(_box_deck(_spv(with_id=False)))
        blk = _blocks(starter, "/MONVOL/PRES/")
        self.assertEqual(len(blk), 1)
        self.assertGreaterEqual(int(blk[0][0].rsplit("/", 1)[1]), 90001)

    def test_two_bags_sharing_an_id_are_renumbered_not_dropped(self):
        """LS-DYNA's *AIRBAG ids are per KEYWORD while Radioss's /MONVOL id
        namespace is shared across PRES/AIRBAG1/GAS/LFLUID, so two bags may
        legally both want id 11. dyna2rad's second CreateEntity then fails its
        IsValid() guard and the airbag VANISHES with no message."""
        second = _lfluid(sid=7).replace(f"{14:>10}", f"{11:>10}")
        r, starter, _e = _convert(_box_deck(_spv(), second))
        ids = {ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/MONVOL/")}
        self.assertEqual(len(ids), 2)
        self.assertTrue(_warns(r, "already used by another *AIRBAG_"))

    def test_two_bags_on_one_set_are_named(self):
        r, _s, _e = _convert(_box_deck(_spv(), _agm()))
        self.assertTrue(_warns(r, "describe ONE cavity"))


class TestAirbagDispatch(unittest.TestCase):

    def test_every_model_spelling_dispatches(self):
        from k2rad.handlers import _AIRBAG_MODELS, _AIRBAG_UNSUPPORTED
        for kw in _AIRBAG_MODELS:
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
        for kw in _AIRBAG_UNSUPPORTED:
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
        # the WANG_NEFSKE and HYBRID suffix stacks, generated from one source
        for kw in ("AIRBAG_WANG_NEFSKE", "AIRBAG_WANG_NEFSKE_JETTING",
                   "AIRBAG_WANG_NEFSKE_JETTING_POP",
                   "AIRBAG_WANG_NEFSKE_MULTIPLE_JETTING_POP",
                   "AIRBAG_HYBRID_JETTING", "AIRBAG_HYBRID_CHEMKIN"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_reference_geometry_option_permutations_dispatch(self):
        """"The order of the options in the keyword name is arbitrary", so
        every permutation is generated. A TRAILING _ID is skipped because
        parser._split_keyword already moves it into block.options."""
        for kw in ("AIRBAG_REFERENCE_GEOMETRY",
                   "AIRBAG_REFERENCE_GEOMETRY_BIRTH",
                   "AIRBAG_REFERENCE_GEOMETRY_RDT",
                   "AIRBAG_REFERENCE_GEOMETRY_ID_BIRTH",
                   "AIRBAG_REFERENCE_GEOMETRY_BIRTH_RDT",
                   "AIRBAG_REFERENCE_GEOMETRY_ID_RDT_BIRTH",
                   "AIRBAG_SHELL_REFERENCE_GEOMETRY",
                   "AIRBAG_SHELL_REFERENCE_GEOMETRY_RDT",
                   "AIRBAG_SHELL_REFERENCE_GEOMETRY_ID_RDT"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
        self.assertNotIn("AIRBAG_REFERENCE_GEOMETRY_BIRTH_ID", HANDLERS,
                         "a trailing _ID is stripped by the parser")

    def test_unsupported_model_warns_by_name_and_keeps_the_mesh(self):
        """An airbag that vanishes into skipped_keywords is not a missing
        output card: the bag never inflates and the run terminates NORMALLY
        with the fabric flapping loose."""
        for kw in ("AIRBAG_WANG_NEFSKE", "AIRBAG_ALE", "AIRBAG_ADVANCED_ALE",
                   "AIRBAG_FLUID_AND_GAS"):
            with self.subTest(kw=kw):
                body = f"*{kw}\n" + _c10(7) + _c10(1) + "\n" + _c10(1.0) + "\n"
                r, starter, _e = _convert(_box_deck(body))
                self.assertEqual(r.skipped_keywords, [])
                self.assertTrue(_warns(r, f"*{kw} is NOT converted"))
                # MESH SURVIVAL: the deck keeps everything else
                self.assertIn("/SHELL/1", starter)
                self.assertIn("/PART/1", starter)
                self.assertIn("/MAT/ELAST/1", starter)
                self.assertNotIn("/MONVOL/", starter)
                self.assertIn(kw, [k for k, _v in r.recognized_not_emitted])

    def test_offset_specs_cover_the_new_contact_keyword(self):
        self.assertIn("CONTACT_AIRBAG_SINGLE_SURFACE", HANDLERS)
        self.assertIn("CONTACT_AIRBAG_SINGLE_SURFACE_MPP", HANDLERS)
        self.assertIn("CONTACT_AIRBAG_SINGLE_SURFACE", _OFFSET_SPECS)

    def test_the_legacy_numeric_suffix_dispatches_and_converts(self):
        """``*AIRBAG_SIMPLE_PRESSURE_VOLUME_1`` / ``..._AIRBAG_MODEL_1`` are
        the spellings the r14 dynaexamples corpus actually ships: MEASURED,
        16 of its 28 *AIRBAG_* occurrences use them, and dispatch() being an
        exact dict lookup put every one of them in skipped_keywords with NO
        warning — three whole decks (airfilled.sphere.k and both
        tire-compression.k) lost their only pressure source on a run that
        terminates normally.

        The card stack is the base model's, verbatim: the corpus decks carry
        the base model's own field-name comments above each card.
        """
        base = _box_deck(_MASS_CURVE, _sam(with_id=False))
        legacy = _box_deck(
            _MASS_CURVE, _sam(with_id=False,
                              keyword="AIRBAG_SIMPLE_AIRBAG_MODEL_1"))
        r0, s0, _e = _convert(base)
        r1, s1, _e = _convert(legacy)
        self.assertEqual(r1.skipped_keywords, [])
        self.assertIn("/MONVOL/AIRBAG1/", s1)
        # Byte-identical to the base spelling apart from the keyword NAME the
        # warnings quote — the card walk is the same walk.
        self.assertEqual(s0, s1)
        self.assertEqual(len(r0.warnings), len(r1.warnings))
        # ... and the SPV twin, whose card 3 is a different shape.
        r2, s2, _e = _convert(
            _box_deck(_spv().replace("*AIRBAG_SIMPLE_PRESSURE_VOLUME_ID",
                                     "*AIRBAG_SIMPLE_PRESSURE_VOLUME_1_ID")))
        self.assertEqual(r2.skipped_keywords, [])
        self.assertIn("/MONVOL/PRES/11", s2)

    def test_the_legacy_suffix_is_registered_on_every_airbag_spelling(self):
        from k2rad.handlers import (_AIRBAG_LEGACY_SUFFIXES, _AIRBAG_MODELS,
                                    _AIRBAG_UNSUPPORTED, _airbag_base_keyword)
        for kw in list(_AIRBAG_MODELS) + list(_AIRBAG_UNSUPPORTED):
            for sfx in _AIRBAG_LEGACY_SUFFIXES:
                with self.subTest(kw=kw + sfx):
                    self.assertIn(kw + sfx, HANDLERS)
                    self.assertEqual(_airbag_base_keyword(kw + sfx), kw)
        for kw in _AIRBAG_MODELS:
            for sfx in _AIRBAG_LEGACY_SUFFIXES:
                with self.subTest(offset=kw + sfx):
                    self.assertIn(kw + sfx, _OFFSET_SPECS)
        # ... and the stripper must not eat a real option word.
        for kw in ("AIRBAG_SIMPLE_AIRBAG_MODEL", "AIRBAG_WANG_NEFSKE_JETTING",
                   "AIRBAG_REFERENCE_GEOMETRY_BIRTH"):
            self.assertEqual(_airbag_base_keyword(kw), kw)

    def test_an_undocumented_airbag_spelling_still_warns(self):
        """Every documented spelling has an exact key, but dispatch() is an
        exact lookup and a silent skip on this family costs a bag that never
        inflates on a run that terminates normally. The _PREFIX_HANDLERS net
        catches the undocumented one: warn-only, never a card."""
        for kw in ("AIRBAG_SOMETHING_NEW", "AIRBAG_REFERENCE_GEOMETRY_1",
                   "AIRBAG_WANG_NEFSKE_JETTING_7"):
            with self.subTest(kw=kw):
                body = f"*{kw}\n" + _c10(7) + _c10(1) + "\n" + _c10(1.0) + "\n"
                r, starter, _e = _convert(_box_deck(body))
                self.assertEqual(r.skipped_keywords, [])
                self.assertTrue(_warns(r, f"*{kw} is NOT converted"))
                self.assertNotIn("/MONVOL/", starter)
                self.assertIn("/SHELL/1", starter)

    def test_the_id_card_is_read_by_column_not_by_whitespace(self):
        """``ABID(I10) HEADING(A70)``: a real deck writes the heading at
        column 11 with NO separating space, and a free split then fuses them —
        "        42Driver airbag" -> ['42Driver', 'airbag'], ABID = 0, the
        /MONVOL silently auto-renumbered and the title "airbag"."""
        glued = _spv().replace(f"{11:>10}" + "spv bag".rjust(30),
                               f"{42:>10}" + "Driver airbag")
        self.assertIn("        42Driver airbag", glued)
        _r, starter, _e = _convert(_box_deck(glued))
        blk = _block(starter, "/MONVOL/PRES/42")
        self.assertEqual(blk[1], "Driver airbag")
        # a blank heading keeps the default title and still reads the id
        blank = _spv().replace(f"{11:>10}" + "spv bag".rjust(30), f"{42:>10}")
        _r, starter, _e = _convert(_box_deck(blank))
        self.assertIn("/MONVOL/PRES/42", starter)
        # and a comma-separated free-format card still works
        free = _spv().replace(f"{11:>10}" + "spv bag".rjust(30),
                              "42,Driver airbag")
        _r, starter, _e = _convert(_box_deck(free))
        blk = _block(starter, "/MONVOL/PRES/42")
        self.assertEqual(blk[1], "Driver airbag")

    def test_a_renumbered_monvol_dodges_the_ids_the_deck_states(self):
        """The /MONVOL id allocator's fallback has to re-check the ids the
        DECK states, not only the ones already handed out. A bag carrying an
        explicit ``_ID`` at or above the auto-id base (90001) is otherwise
        handed the same id a later un-ID'd bag draws — two /MONVOLs under one
        number, starter ERROR 79, and the whole deck refused. Same guard the
        other five allocators carry."""
        _r, starter, _e = _convert(
            _box_deck(_MASS_CURVE,
                      _spv(abid=90001), _spv(abid=90002, sid=7),
                      _sam(with_id=False)))
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/MONVOL/")]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3, f"duplicate /MONVOL id: {ids}")
        self.assertIn("90001", ids)
        self.assertIn("90002", ids)


# ═════════════════════════════════════════════════════════════════════════════
# *DATABASE_ABSTAT -> /TH/MONV  (+ the /TFILE chain)
# ═════════════════════════════════════════════════════════════════════════════

class TestAbstatThMonv(unittest.TestCase):

    def test_abstat_lists_every_emitted_monvol(self):
        _r, starter, engine = _convert(
            _box_deck(_spv(), "*DATABASE_ABSTAT\n     1.0E-5\n"))
        blk = _block(starter, "/TH/MONV/")
        self.assertEqual(blk[1], "TH_MONV_ABSTAT_PRES")
        self.assertEqual(_th_monv_vars(blk), ["VOL", "P", "A"])
        self.assertEqual(_th_monv_ids(blk), [11])

    def test_variables_are_per_model_not_a_union(self):
        """The whole 19-name vocabulary is legal on every monitored volume — a
        probe took all sixteen non-vent names on a PRES bag without complaint —
        but the ENGINE only fills the FSAV slots its own pressure law computes,
        and volpfv.F sets FSAV(1) = 0 for a PRES bag. Requesting MASS, T or
        GAMA there would write flat zeros that read as data.

        GAS drops MASS and T for the same reason one level deeper: volpvg.F
        DOES write FSAV(1) and FSAV(5), but AMTOT comes from
        ``RVOLU(20) = MI``, which hm_read_monvol_type3.F:300-315 only derives
        when ``I_equi > 0``, and TEMPERATURE is assigned only inside
        ``IF (IEQUI > 0)`` at :159. _emit_monvol_gas hard-writes I_equi = 0
        and Mini = 0. MEASURED over 505 samples of the adiabatic box: both
        min = max = 0. AIRBAG1 drops DTBAG — airbagb1.F:655-679 fills FSAV
        1-12 and 15-18 and never 13; index 13 belongs to the FVMBAG routines.
        """
        _r, starter, _e = _convert(
            _box_deck(_MASS_CURVE, _spv(), _sam(), _agm(), _lfluid(),
                      "*DATABASE_ABSTAT\n     1.0E-5\n"))
        got = {b[1]: _th_monv_vars(b) for b in _blocks(starter, "/TH/MONV/")}
        self.assertEqual(set(got), {"TH_MONV_ABSTAT_PRES",
                                    "TH_MONV_ABSTAT_GAS",
                                    "TH_MONV_ABSTAT_AIRBAG1",
                                    "TH_MONV_ABSTAT_LFLUID"})
        self.assertEqual(got["TH_MONV_ABSTAT_PRES"], ["VOL", "P", "A"])
        self.assertEqual(got["TH_MONV_ABSTAT_GAS"], ["VOL", "P", "A", "GAMA"])
        self.assertEqual(got["TH_MONV_ABSTAT_LFLUID"],
                         ["MASS", "VOL", "P", "A", "MASS-IN"])
        self.assertNotIn("DTBAG", got["TH_MONV_ABSTAT_AIRBAG1"])
        # the AIRBAG1 bag here HAS a vent, so the four vent channels join —
        # and they join in VARMV order (after T), not at the end.
        self.assertEqual(got["TH_MONV_ABSTAT_AIRBAG1"],
                         ["MASS", "VOL", "P", "A", "T",
                          "AO", "UO", "AC", "UC",
                          "CP", "CV", "GAMA",
                          "MASS-IN", "ENTHA-IN", "ENER-INT", "WORK"])

    def test_th_monv_names_are_written_in_the_starter_table_order(self):
        """The starter sorts the requested names into its own VARMV order
        (hm_read_thgrou.F:1181-1186) and the T01 columns come back in THAT
        order, not in card order — MEASURED, a group written
        "... GAMA MASS-IN ... DTBAG AO UO AC UC" came back with AO/UO/AC/UC in
        columns 6-9, mis-labelling 9 of 17 channels for anyone indexing
        th_to_csv positionally. Writing them pre-sorted makes the card
        describe the file it produces."""
        from k2rad.writer.output import _TH_MONV_VARS, _th_monv_groups
        varmv = ["MASS", "VOL", "P", "A", "T", "AO", "UO", "AC", "UC",
                 "CP", "CV", "GAMA", "DTBAG", "NFV", "MASS-IN", "ENTHA-IN",
                 "ENER-INT", "WORK", "UPCRIT"]
        for rad in _TH_MONV_VARS:
            for vented in ({1}, set()):
                for vars_, _ids in _th_monv_groups(rad, [1], vented):
                    with self.subTest(rad=rad, vented=bool(vented)):
                        idx = [varmv.index(v) for v in vars_]
                        self.assertEqual(idx, sorted(idx))

    def test_unvented_airbag1_drops_the_vent_channels(self):
        _r, starter, _e = _convert(
            _box_deck(_MASS_CURVE, _sam(mu=0.0, area=0.0),
                      "*DATABASE_ABSTAT\n     1.0E-5\n"))
        vars_ = _th_monv_vars(_block(starter, "/TH/MONV/"))
        for v in ("AO", "UO", "AC", "UC"):
            self.assertNotIn(v, vars_)

    def test_a_sealed_bag_does_not_take_the_vent_channels_off_a_vented_one(
            self):
        """The AIRBAG1 group splits by VENT state. All-or-nothing granularity
        meant one unvented bag removed AO/UO/AC/UC for every vented bag beside
        it — the channels are structural zeros only on the SEALED bag."""
        _r, starter, _e = _convert(
            _box_deck(_MASS_CURVE,
                      _sam(abid=71, mu=0.7, area=25.0),
                      _sam(abid=72, mu=0.0, area=0.0),
                      "*DATABASE_ABSTAT\n     1.0E-5\n"))
        blks = _blocks(starter, "/TH/MONV/")
        self.assertEqual(len(blks), 2)
        by_ids = {tuple(_th_monv_ids(b)): _th_monv_vars(b) for b in blks}
        self.assertEqual(len(by_ids), 2)
        vented = [v for k, v in by_ids.items() if "AO" in v]
        sealed = [v for k, v in by_ids.items() if "AO" not in v]
        self.assertEqual(len(vented), 1)
        self.assertEqual(len(sealed), 1)
        self.assertEqual(vented[0][5:9], ["AO", "UO", "AC", "UC"])

    def test_id_card_is_a_ten_per_line_cell_list(self):
        """th_monv.cfg's id card is FREE_CELL_LIST(idsmax,"%10d",ids,100), not
        the one-id-per-line layout every element group uses."""
        from k2rad.writer.output import _TH_CELL_LIST_TYPES, _th_id_lines
        self.assertIn("MONV", _TH_CELL_LIST_TYPES)
        self.assertEqual(_th_id_lines("MONV", list(range(1, 13))),
                         ["".join(f"{v:>10}" for v in range(1, 11)),
                          "".join(f"{v:>10}" for v in (11, 12))])

    def test_abstat_dt_joins_the_tfile_minimum_only_with_a_monvol(self):
        """*DATABASE_ABSTAT used to be excluded from the /TFILE chain by name,
        because it had no /TH consumer. It has one now — but the #122 test is
        "does this card pace a channel that is IN the T01", so it is gated on
        state.monvol_ids, not on the card's presence."""
        _r, _s, engine = _convert(
            _box_deck(_spv(), "*DATABASE_ABSTAT\n     1.0E-5\n"
                              "*DATABASE_GLSTAT\n     1.0E-3\n"))
        self.assertIn("/TFILE\n1E-05", engine)
        # no airbag at all -> the ABSTAT dt must NOT pull the T01 down
        _r, _s, engine = _convert(
            _box_deck("*DATABASE_ABSTAT\n     1.0E-5\n"
                      "*DATABASE_GLSTAT\n     1.0E-3\n"))
        self.assertIn("/TFILE\n0.001", engine)

    def test_abstat_without_any_airbag_is_a_note_not_a_warning(self):
        """An ABSTAT on a deck with no *AIRBAG_* at all is inert in LS-DYNA too
        — its abstat file would be empty as well — and it is common
        boilerplate: MEASURED, 73 of the 827 corpus decks carry one without a
        single airbag keyword. A warning there is noise; the loss belongs in
        "recognized but not emitted"."""
        r, starter, _e = _convert(
            _box_deck("*DATABASE_ABSTAT\n     1.0E-5\n"))
        self.assertNotIn("/TH/MONV/", starter)
        self.assertFalse(_warns(r, "*DATABASE_ABSTAT"))
        self.assertIn("DATABASE_ABSTAT",
                      [k for k, _v in r.recognized_not_emitted])

    def test_abstat_whose_airbags_were_all_dropped_does_warn(self):
        """That IS a real loss: the deck asked for bag statistics, the bags
        exist in the .k, and none of them reached the converted deck."""
        r, starter, _e = _convert(
            _box_deck(_spv(sid=999), "*DATABASE_ABSTAT\n     1.0E-5\n"))
        self.assertNotIn("/TH/MONV/", starter)
        self.assertTrue(_warns(r, "none of them converted to a /MONVOL"))

    def test_abstat_with_a_blank_dt_is_reported(self):
        r, starter, _e = _convert(_box_deck(_spv(), "*DATABASE_ABSTAT\n\n"))
        self.assertNotIn("/TH/MONV/", starter)
        self.assertTrue(_warns(r, "*DATABASE_ABSTAT"))


# ═════════════════════════════════════════════════════════════════════════════
# *AIRBAG_REFERENCE_GEOMETRY -> /XREF, *AIRBAG_SHELL_REFERENCE_GEOMETRY -> /EREF
# ═════════════════════════════════════════════════════════════════════════════

_REF_MESH = """\
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
       3            10.0            10.0             0.0
       4             0.0            10.0             0.0
       5            20.0             0.0             0.0
      11             0.0             0.0             0.0
      12             5.0             0.0             0.0
      13             5.0             5.0             0.0
      14             0.0             5.0             0.0
      15            10.0             0.0             0.0
*ELEMENT_SHELL
       1       1       1       2       3       4
       2       1       2       5       3       3
*PART
fabric
         1         1         3
*SECTION_SHELL
         1         2       1.0         2
       1.0       1.0       1.0       1.0
"""


def _ref_nodes(sx=None, sy=None, sz=None, nid0=0, birth=None, rdt=False):
    c = _c10
    opts = ""
    if sx is not None:
        opts += "_ID"
    if birth is not None:
        opts += "_BIRTH"
    if rdt:
        opts += "_RDT"
    out = [f"*AIRBAG_REFERENCE_GEOMETRY{opts}"]
    if sx is not None:
        out.append(c(1) + c(sx) + c(sy) + c(sz) + c(nid0) + c(0))
    if birth is not None:
        out.append(c(birth))
    for nid, xyz in ((1, (0.0, 0.0, 0.0)), (2, (5.0, 0.0, 0.0)),
                     (3, (5.0, 5.0, 0.0)), (4, (0.0, 5.0, 0.0))):
        out.append(f"{nid:>10}" + "".join(f"{v:>20.10G}" for v in xyz))
    return "\n".join(out) + "\n"


class TestAirbagReferenceGeometry(unittest.TestCase):

    def _deck(self, *extra):
        return ("*KEYWORD\n" + _REF_MESH + _fabric_mat() + "".join(extra)
                + _TERM)

    def test_xref_is_per_part_with_the_reference_coordinates(self):
        """Structurally the airbag twin of *INITIAL_FOAM_REFERENCE_GEOMETRY, so
        it feeds the same per-part /XREF. A SHELL part needs no law check at
        all: hm_read_xref.F's MTN whitelist is gated on ITYP == 2, i.e. SOLID
        parts only, and cepsini.F's CMLAWI dispatch covers ILAW 1, 19 and 58 —
        both fabric laws honour a reference state."""
        _r, starter, _e = _convert(self._deck(_ref_nodes()))
        cards = _cards(_block(starter, "/XREF/1"))
        self.assertEqual(_col_i(cards[0], 1, 10), 0)      # Nitrs -> default
        rows = [(_col_i(c, 1, 10), _col_f(c, 11, 30), _col_f(c, 31, 50),
                 _col_f(c, 51, 70)) for c in cards[1:]]
        self.assertEqual(rows, [(1, 0.0, 0.0, 0.0), (2, 5.0, 0.0, 0.0),
                                (3, 5.0, 5.0, 0.0), (4, 0.0, 5.0, 0.0)])

    def test_id_scaling_is_baked_into_the_coordinates(self):
        """Radioss /XREF has no scale and no origin column, so SX/SY/SZ about
        NIDO has to be applied at CONVERSION time. The origin is NIDO's own
        REFERENCE coordinate when the table lists it — scaling the reference
        shape about a point of the reference shape keeps the operation inside
        one geometry, where dyna2rad takes the STRUCTURAL position and mixes
        the two whenever the origin node has moved."""
        _r, starter, _e = _convert(
            self._deck(_ref_nodes(sx=2.0, sy=2.0, sz=1.0, nid0=1)))
        cards = _cards(_block(starter, "/XREF/1"))
        rows = [(_col_i(c, 1, 10), _col_f(c, 11, 30), _col_f(c, 31, 50))
                for c in cards[1:]]
        self.assertEqual(rows, [(1, 0.0, 0.0), (2, 10.0, 0.0),
                                (3, 10.0, 10.0), (4, 0.0, 10.0)])

    def test_id_scaling_about_a_non_first_origin_node(self):
        _r, starter, _e = _convert(
            self._deck(_ref_nodes(sx=3.0, sy=1.0, sz=1.0, nid0=3)))
        cards = _cards(_block(starter, "/XREF/1"))
        xs = {_col_i(c, 1, 10): _col_f(c, 11, 30) for c in cards[1:]}
        # origin x0 = 5 (node 3's reference x): x' = 5 + (x - 5)*3
        self.assertAlmostEqual(xs[1], -10.0)
        self.assertAlmostEqual(xs[2], 5.0)
        self.assertAlmostEqual(xs[3], 5.0)

    def test_birth_arms_the_fabric_law_sensor(self):
        """BIRTH is the card-level twin of *MAT_FABRIC's RGBRTH: a
        /SENSOR/TIME on the law's SENS_ID, which is the starter's
        MATPARAM%IPARAM(1) reference-state activation sensor."""
        r, starter, _e = _convert(self._deck(_ref_nodes(birth=0.0025)))
        sens = _block(starter, "/SENSOR/TIME/")
        sid = int(sens[0].rsplit("/", 1)[1])
        self.assertAlmostEqual(_col_f(_cards(sens)[0], 1, 20), 0.0025)
        self.assertEqual(_col_i(_cards(_block(starter, "/MAT/LAW19/3"))[3],
                                81, 90), sid)
        self.assertTrue(_warns(r, "BIRTH=0.0025"))

    def test_material_rgbrth_wins_over_the_card_birth(self):
        r, starter, _e = _convert(
            "*KEYWORD\n" + _REF_MESH + _fabric_mat(rgbrth=0.001)
            + _ref_nodes(birth=0.009) + _TERM)
        sens = _blocks(starter, "/SENSOR/TIME/")
        self.assertEqual(len(sens), 1)
        self.assertAlmostEqual(_col_f(_cards(sens[0])[0], 1, 20), 0.001)

    def test_rdt_is_named_as_dropped(self):
        r, _s, _e = _convert(self._deck(_ref_nodes(rdt=True)))
        self.assertTrue(_warns(r, "_RDT option"))

    def test_rdt_on_a_shell_only_deck_is_named_too(self):
        """``_warn_airbag_ref_options`` also covers the SHELL spelling, which
        never reaches the /XREF path at all — so gating the call on the /XREF
        inputs left a ``_RDT`` on a shell-only deck silently dropped."""
        eref = ("*AIRBAG_SHELL_REFERENCE_GEOMETRY_RDT\n"
                + _c10(1) + _c10(1) + _c10(11) + _c10(12) + _c10(13)
                + _c10(14) + "\n")
        r, starter, _e = _convert(self._deck(eref))
        self.assertIn("/EREF/SHELL/1", starter)
        self.assertTrue(_warns(r, "_RDT option"), r.warnings)

    def test_a_truncated_eref_row_never_reaches_the_deck(self):
        """A row carrying only EID and PID filters down to an EMPTY node list:
        the `bad` screen passes vacuously, the no-op screen compares set()
        against the element's four nodes and finds them unequal, and the quad
        padder yields [] — so the row would go out as an element id with zero
        node columns, which is not a shape."""
        eref = ("*AIRBAG_SHELL_REFERENCE_GEOMETRY\n"
                + _c10(1) + _c10(1) + "\n"
                + _c10(2) + _c10(1) + _c10(12) + _c10(15) + _c10(13) + "\n")
        r, starter, _e = _convert(self._deck(eref))
        self.assertNotIn("/EREF/SHELL/", starter)
        tri = _cards(_block(starter, "/EREF/SH3N/1"))
        self.assertEqual([int(t) for t in tri[0].split()], [2, 12, 15, 13])
        self.assertTrue(_warns(r, "fewer than three"), r.warnings)

    def test_eref_splits_quads_and_tris_per_part(self):
        eref = ("*AIRBAG_SHELL_REFERENCE_GEOMETRY\n"
                + _c10(1) + _c10(1) + _c10(11) + _c10(12) + _c10(13)
                + _c10(14) + "\n"
                + _c10(2) + _c10(1) + _c10(12) + _c10(15) + _c10(13) + "\n")
        _r, starter, _e = _convert(self._deck(eref))
        quad = _cards(_block(starter, "/EREF/SHELL/1"))
        tri = _cards(_block(starter, "/EREF/SH3N/1"))
        self.assertEqual([int(t) for t in quad[0].split()], [1, 11, 12, 13, 14])
        self.assertEqual([int(t) for t in tri[0].split()], [2, 12, 15, 13])

    def test_eref_is_dropped_where_a_xref_already_covers_the_part(self):
        """Radioss refuses a node that appears in both (ERROR 1098, "COMMON
        NODE IN EREF AND XREF OPTIONS"), and the two LS-DYNA cards are written
        TOGETHER: the node card gives the coordinates and the shell card names
        the elements. The /XREF wins — it carries the real coordinates."""
        eref = ("*AIRBAG_SHELL_REFERENCE_GEOMETRY\n"
                + _c10(1) + _c10(1) + _c10(11) + _c10(12) + _c10(13)
                + _c10(14) + "\n")
        r, starter, _e = _convert(self._deck(_ref_nodes(), eref))
        self.assertIn("/XREF/1", starter)
        self.assertNotIn("/EREF/", starter)
        self.assertTrue(_warns(r, "ERROR 1098"))

    def test_eref_screens_missing_elements_and_nodes(self):
        eref = ("*AIRBAG_SHELL_REFERENCE_GEOMETRY\n"
                + _c10(999) + _c10(1) + _c10(11) + _c10(12) + _c10(13)
                + _c10(14) + "\n"
                + _c10(1) + _c10(1) + _c10(777) + _c10(12) + _c10(13)
                + _c10(14) + "\n")
        r, starter, _e = _convert(self._deck(eref))
        self.assertNotIn("/EREF/", starter)
        self.assertTrue(_warns(r, "ERROR 1011"))
        self.assertTrue(_warns(r, "in no *NODE"))

    def test_eref_on_the_elements_own_nodes_is_named_as_a_no_op(self):
        eref = ("*AIRBAG_SHELL_REFERENCE_GEOMETRY\n"
                + _c10(1) + _c10(1) + _c10(1) + _c10(2) + _c10(3)
                + _c10(4) + "\n")
        r, starter, _e = _convert(self._deck(eref))
        self.assertIn("/EREF/SHELL/1", starter)
        self.assertTrue(_warns(r, "reference shape is identical"))


# ═════════════════════════════════════════════════════════════════════════════
# *CONTACT_AIRBAG_SINGLE_SURFACE
# ═════════════════════════════════════════════════════════════════════════════

def _airbag_contact(soft=-19, iflag=0, sst=2.0, sfst=0.5, fs=0.3, ssid=7):
    c = _c10
    return ("*CONTACT_AIRBAG_SINGLE_SURFACE\n"
            # SSID <blank> SSTYP <blank> SBOX <blank> SPR IFLAG
            + c(ssid) + " " * 10 + c(2) + " " * 10 + c(0) + " " * 10 + c(0)
            + c(iflag) + "\n"
            + c(fs) + c(0.2) + c(0.0) + c(0.0) + c(0.0) + c(0) + c(0.0)
            + c(1.0e20) + "\n"
            # SFS <blank> SST <blank> SFST <blank> FSF VSF
            + c(1.0) + " " * 10 + c(sst) + " " * 10 + c(sfst) + " " * 10
            + c(1.0) + c(0.0) + "\n"
            + c(soft) + "\n")


class TestAirbagContact(unittest.TestCase):

    def test_soft_minus_19_gives_the_airbag_type19_flavour(self):
        """dyna2rad's airbag TYPE19: Istf=4, Idel=2, Ibag=1 and a
        scale-weighted single-sided Gapmin (convertcontacts.cxx:659-664)."""
        r, starter, _e = _convert(_box_deck(_spv(), _airbag_contact()))
        cards = _cards(_block(starter, "/INTER/TYPE19/"))
        self.assertEqual(_col_i(cards[0], 21, 30), 4)      # Istf
        self.assertEqual(_col_i(cards[0], 51, 60), 2)      # Iedge
        self.assertEqual(_col_i(cards[0], 61, 70), 1)      # Ibag
        self.assertEqual(_col_i(cards[0], 71, 80), 2)      # Idel
        # SINGLE surface: the main side is the secondary side mirrored
        self.assertEqual(_col_i(cards[0], 1, 10), _col_i(cards[0], 11, 20))
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 0.5)   # SST/2 * SFST
        self.assertAlmostEqual(_col_f(cards[3], 21, 40), 0.3)   # Fric
        self.assertTrue(_warns(r, "Airbag flavour"))
        # The airbag Gapmin branch does not go through _sst_mst_to_gapmin
        # (the two-sided helper would read the missing MST as a second
        # thickness), so it has to emit that helper's two diagnostics itself.
        self.assertTrue(_warns(r, "SST contact thickness"), r.warnings)

    def test_a_negative_sst_is_named_not_silently_absolutised(self):
        """LS-DYNA gives a negative SST a side meaning the magnitude does not
        carry. Every other contact route says so; this one used to absolutise
        it in silence because it skipped the shared helper."""
        r, starter, _e = _convert(
            _box_deck(_spv(), _airbag_contact(sst=-2.0)))
        cards = _cards(_block(starter, "/INTER/TYPE19/"))
        self.assertAlmostEqual(_col_f(cards[3], 41, 60), 0.5)
        self.assertTrue(_warns(r, "negative SST"), r.warnings)

    def test_ibag_is_zero_without_a_monvol(self):
        """Ibag=1 means "close the airbag's vent holes where contact occurs",
        and hm_read_inter_type07.F:403-410 resets it to 0 with WARNING 614 when
        the deck has NVOLU == 0."""
        r, starter, _e = _convert(_box_deck(_airbag_contact()))
        cards = _cards(_block(starter, "/INTER/TYPE19/"))
        self.assertEqual(_col_i(cards[0], 61, 70), 0)
        self.assertTrue(_warns(r, "WARNING 614"))

    def test_edge_scale_gap_is_not_emitted_at_begin_2022(self):
        """It is field 3 of card 2 and exists only from radioss2024; k2rad
        declares /BEGIN 2022, where card 2 is Fscalegap | Gap_max only."""
        r, starter, _e = _convert(_box_deck(_spv(), _airbag_contact()))
        card2 = _cards(_block(starter, "/INTER/TYPE19/"))[1]
        self.assertEqual(len(card2.rstrip()), 40)
        self.assertTrue(_warns(r, "Edge_scale_gap"))

    def test_default_soft_takes_the_untouched_single_surface_path(self):
        _r, starter, _e = _convert(_box_deck(_spv(), _airbag_contact(soft=2)))
        self.assertNotIn("/INTER/TYPE19/", starter)
        self.assertTrue("/INTER/TYPE25/" in starter or "/INTER/TYPE7/" in starter)

    def test_iflag_is_read_and_named(self):
        """dyna2rad reads IFLAG and then ignores it — both of its IFLAG
        branches are commented out and the live test is on SOFT — so acting on
        it would make the two converters disagree with no way to tell which is
        right."""
        r, _s, _e = _convert(_box_deck(_spv(), _airbag_contact(iflag=1)))
        self.assertTrue(_warns(r, "IFLAG=1"))

    def test_the_column_grid_is_shared_with_the_two_sided_card(self):
        """The interleaved 10-blank columns put SSID at grid index 0, SSTYP at
        2 and SFST at 4 — the same indices the two-sided card uses, which is
        what makes this a handler ALIAS rather than a second parser."""
        state = _dispatch("*KEYWORD\n" + _airbag_contact(ssid=42, sst=3.0,
                                                          sfst=2.0))
        self.assertEqual(len(state.contacts_general), 1)
        c = state.contacts_general[0]
        self.assertEqual((c.ssid, c.sstyp, c.msid, c.mstyp), (42, 2, 42, 2))
        self.assertEqual((c.sst, c.mst, c.sfst), (3.0, 0.0, 2.0))
        self.assertTrue(c.airbag)


# ═════════════════════════════════════════════════════════════════════════════
# The registry audit and the no-regression guards
# ═════════════════════════════════════════════════════════════════════════════

class TestRegistryAudit(unittest.TestCase):

    def test_dangling_part_material_is_named(self):
        """Before the fabric batch, airbag.deploy.k emitted /PART/3 pointing at
        mid 3 with only /MAT/ELAST/1 and /MAT/ELAST/2 in the whole _0000.rad
        and NOT ONE warning. Implementing *MAT_FABRIC removed the cause; this
        scan removes the class. MEASURED on the 827-deck corpus sweep: 280
        decks carry the defect and none of them said so."""
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD
                .replace("         1         1         3",
                         "         1         1        77")
                + _TERM)
        r, starter, _e = _convert(deck)
        self.assertIn("/PART/1", starter)
        self.assertTrue(_warns(r, "reference a material id that NO /MAT"))

    def test_dangling_part_material_names_the_skipped_mat_keyword(self):
        """"Look above" is not an answer when the cause is one unconverted
        *MAT_ keyword sitting in the skip list — so it is quoted. The corpus
        example is `ale/misc/forging-a/forging_A.k`, whose `/PART/1` points at
        a `*MAT_INV_HYPERBOLIC_SIN`."""
        deck = ("*KEYWORD\n" + _MESH_ONE_QUAD
                .replace("         1         1         3",
                         "         1         1        77")
                + "*MAT_INV_HYPERBOLIC_SIN\n"
                + _c10(77) + _c10(7.85e-9) + _c10(210000.0) + "\n"
                + _TERM)
        r, _s, _e = _convert(deck)
        hits = _warns(r, "reference a material id that NO /MAT")
        self.assertTrue(hits)
        self.assertIn("*MAT_INV_HYPERBOLIC_SIN", hits[0])

    def test_connector_mat_id_zero_is_not_dangling(self):
        """mat_ID = 0 is the connector convention (a spring / damper /
        spotweld part whose whole material lives inside its /PROP/TYPE4|8|13),
        and the starter accepts it."""
        deck = """\
*KEYWORD
*NODE
       1             0.0             0.0             0.0
       2            10.0             0.0             0.0
*ELEMENT_DISCRETE
       1       1       1       2       0       0.0       0       0.0
*PART
spring
         1         1         1
*SECTION_DISCRETE
         1         0
*MAT_SPRING_ELASTIC
         1     100.0
*CONTROL_TERMINATION
     0.001
*END
"""
        r, _s, _e = _convert(deck)
        self.assertFalse(_warns(r, "reference a material id that NO /MAT"))

    def test_monvol_owns_no_mesh_so_the_free_node_guard_is_untouched(self):
        """A monitored volume owns no node and no element: its surface is
        built from shells the mesh already had. The implicit free-node guard
        walks the ELEMENT containers, so it neither gains nor loses a node —
        and the two r14 airbag decks are IMPLICIT, so this arm IS exercised by
        the batch."""
        implicit = _box_deck(
            _spv(),
            "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n")
        _r, with_bag, _e = _convert(implicit)
        _r2, without, _e2 = _convert(_box_deck(
            "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n"))
        # The /BCS group ID moves (a monitored volume draws its /SURF ids from
        # the same next_id() stream), so compare what the guard CONSTRAINS:
        # the NODE LIST of the /GRNOD each /BCS points at.
        def _constrained(text):
            lines = text.splitlines()
            grnods = {}
            for k, ln in enumerate(lines):
                if ln.startswith("/GRNOD/NODE/"):
                    ids, j = [], k + 2
                    while j < len(lines) and not lines[j].startswith(("/", "#")):
                        ids += [int(t) for t in lines[j].split()]
                        j += 1
                    grnods[int(ln.rsplit("/", 1)[1])] = sorted(ids)
            out = []
            for k, ln in enumerate(lines):
                if ln.startswith("/BCS/"):
                    row = lines[k + 3]
                    out.append((row[:20], grnods.get(int(row[30:40] or 0), [])))
            return sorted(out)
        self.assertEqual(_constrained(with_bag), _constrained(without))
        self.assertTrue(_constrained(with_bag))

    def test_goldens_are_unchanged(self):
        """A pure-addition batch adds no card to a deck that uses none of the
        new keywords, so the five checked-in goldens must be byte-identical.
        The named risks here are the /PART prop_ref chain (a new
        fabric_prop_ids lookup), _make_properties' split_pids set, the /TFILE
        minimum (a new ABSTAT term) and the two new registry sections, any of
        which would move an id or a column if it were not a strict no-op on a
        deck without an *AIRBAG_* or a *MAT_FABRIC."""
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
