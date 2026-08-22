"""The AIRBAG / MONVOL batch 2 — the MULTI-GAS inflators:

  *AIRBAG_HYBRID{_JETTING}{_CM}  -> /MONVOL/AIRBAG1 with N_gases > 1
                                    + one /MAT/GAS/MOLE per species
                                    + the initial-mixture /MAT/GAS/MOLE
  *AIRBAG_PARTICLE{_MPP}{_DECOMPOSITION}{_MOLEFRACTION}{_SEGMENT}{_TIME}
                                 -> /MONVOL/FVMBAG2, or /MONVOL/AIRBAG1
                                    under --airbag-particle-uniform
  *AIRBAG_INTERACTION            -> /MONVOL/COMMU1 x 2 with reciprocal
                                    Nbag communicating rows

Everything is asserted BY COLUMN, because that is the only way any of it is
visible in the .rad, and every number in the fixtures is DISTINCT per slot so
that a swap between two of them cannot pass. The conventions that carry the
most risk, and why each is pinned:

* **``/MAT/GAS/MOLE`` Cp coefficients are copied 1:1, NOT divided by MW.**
  This is the single arithmetic trap of the batch, because batch 1 divides and
  the LS-DYNA input is molar on both keywords. ``hm_read_matgas.F:295-302``
  does the division for the MOLE variant — ``CPA = CPA / MW * FAC`` — while
  batch 1's ``/MAT/GAS/MASS`` target is mass-specific and the CONVERTER
  divides (``cpa = ab.hc_a / mw``). Dividing twice understates Cp by a factor
  MW: on a 0.028 kg/mol gas, 36x.
* **``/MAT/GAS/MOLE`` has NO ``Cpf`` card.** The reader takes ``MAT_F`` only
  for ``IGAS == 2``; a sixth line after a MOLE gas is the next keyword read as
  a Cpf, and everything below it shifts.
* **The initial mixture is a MOLE-FRACTION average.** ``INITM`` is a MASS
  fraction (Vol I R17 p.3-50) while MW and A/B/C are MOLAR, so the weights are
  converted before averaging: ``M = 1 / sum(w_i/M_i)`` and
  ``Cp = sum(x_i Cp_i)``. dyna2rad takes the arithmetic mean of molar
  quantities with mass weights, which agrees only when every MW is equal.
* **``Iflow`` must be 1 and the curve is a RATE.** Same trap as batch 1:
  ``airbaga1.F`` INTEGRATES the curve at ``Iflow=1`` and DIFFERENCES it at 0.
* **A vent's ``fct_IDP`` abscissa is the GAUGE pressure ``P - Pext``.**
  ``airbagb1.F`` reads it at ``(P-PEXT)*SCALP``; the only absolute-pressure
  path in the engine is ``/MAT/FABRIC`` ``ILEAKAGE==2``. LS-DYNA documents
  LCA23 and LCAP23 against ABSOLUTE pressure, so those two are shifted and
  ``*AIRBAG_PARTICLE``'s LCPC23 — which LS-DYNA does not document either way —
  is not.
* **``Avent`` means two different things.** With ``surf_IDv == 0`` it is an
  absolute AREA; with a named surface it is a SCALE FACTOR on that surface's
  current area.
* **A pop-open pressure needs ``Tstart`` out of reach.** ``airbagb1.F:290``
  ORs the time and pressure opening criteria, so ``dPdef = PPOP`` with
  ``Tstart = 0`` opens the hole on the first cycle and PPOP is never tested.
* **``Dtmin`` follows the ``UNIT`` flag**, and 1e-4 in a ms system is the same
  floor as 1e-7 in a s system.
* **The count-driven card walks.** NGAS, NVENT and NORIF each position every
  card below them; a HYBRID gas pair is one card or two depending on whether
  the deck carries the FMASS line, and a ``STYPE2 == 2`` PARTICLE deck cannot
  be walked at all.
* **A batch-1 deck must be BYTE-IDENTICAL to what master emits.** The five
  uniform-pressure models share the vent emitter, the injector emitter and the
  /TH/MONV table with batch 2, so all three had to stay no-ops for them.
"""

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k2rad import convert                                # noqa: E402
from k2rad.assembly import _OFFSET_SPECS                 # noqa: E402
from k2rad.handlers import HANDLERS                      # noqa: E402
from k2rad.parser import parse_k_file                    # noqa: E402


# ── Harness ──────────────────────────────────────────────────────────────────

def _convert(deck: str, **kw):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "deck.k")
    with open(path, "w") as fh:
        fh.write(deck)
    result = convert(path, write_log=False, **kw)
    with open(result.starter_path) as fh:
        starter = fh.read()
    with open(result.engine_path) as fh:
        engine = fh.read()
    tmp.cleanup()
    return result, starter, engine


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
    out = []
    for ln in _cards(block):
        toks = ln.split()
        if toks and all(t.isdigit() for t in toks):
            break
        out += toks
    return out


def _c10(v) -> str:
    """One 10-column LS-DYNA cell, at the most precision that fits.

    ``None`` is a BLANK cell — not the string "0". The two are different
    inputs: a blank asks for the field's documented default, and for the
    count-driven walks a blank card is what a preprocessor writes for a
    defaulted optional card."""
    if v is None:
        return " " * 10
    if isinstance(v, int):
        return f"{v:>10d}"
    if isinstance(v, str):
        return f"{v:>10s}"
    for prec in range(10, 0, -1):
        s = f"{v:.{prec}g}"
        if len(s) <= 10:
            return f"{s:>10}"
    return f"{v:>10.3E}"[:10]


def _card(*vals) -> str:
    return "".join(_c10(v) for v in vals) + "\n"


# ── Deck fragments ───────────────────────────────────────────────────────────
#
# A closed box of six quads on eight nodes, wound OUTWARD, V = 1000 mm^3.
# Element 4 sits on its own PART so it can be named as a vent patch, an
# internal surface or an inflator nozzle without changing the bag's geometry.

def _mesh(nid0=0, eid0=0, pid_main=1, pid_patch=2, x0=5.0):
    n = [(x0, 5.0, 5.0), (x0 + 10, 5.0, 5.0), (x0 + 10, 15.0, 5.0),
         (x0, 15.0, 5.0), (x0, 5.0, 15.0), (x0 + 10, 5.0, 15.0),
         (x0 + 10, 15.0, 15.0), (x0, 15.0, 15.0)]
    faces = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    out = ["*NODE"]
    for i, (x, y, z) in enumerate(n, start=1):
        out.append(f"{nid0 + i:>8d}{x:>16.8f}{y:>16.8f}{z:>16.8f}")
    out.append("*ELEMENT_SHELL")
    for i, f in enumerate(faces, start=1):
        pid = pid_patch if i == 4 else pid_main
        out.append(f"{eid0 + i:>8d}{pid:>8d}"
                   + "".join(f"{nid0 + q:>8d}" for q in f))
    return "\n".join(out) + "\n"


_PARTS = """\
*PART
bag
         1         1         1
*PART
patch
         2         1         1
*SECTION_SHELL
         1         2       1.0         2         1         0         0         1
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*SET_PART_LIST
         7       0.0       0.0       0.0       0.0MECH
         1         2
"""

#: Curve 90 = a FLAT mass-flow RATE. Flat on purpose: a ramped curve makes the
#: Iflow=0 (differenced) vs Iflow=1 (integrated) error invisible at early
#: times, while a constant rate differences to zero immediately.
#: Curve 92's abscissae are ABSOLUTE pressures 0.101325 above the gauge values
#: they must land on after the -Pext shift.
_CURVES = """\
*DEFINE_CURVE
        90         0       1.0       1.0       0.0       0.0
                     0.0            1.60000E-4
                   0.001            1.60000E-4
*DEFINE_CURVE
        91         0       1.0       1.0       0.0       0.0
                     0.0                 900.
                   0.001                 900.
*DEFINE_CURVE
        92         0       1.0       1.0       0.0       0.0
                0.1013250                   0.
                0.2013250                  50.
*DEFINE_CURVE
        93         0       1.0       1.0       0.0       0.0
                     0.0                  1.0
                   0.001                  0.5
"""

_TERM = """\
*CONTROL_TERMINATION
     0.001
*END
"""

_ABSTAT = """\
*DATABASE_ABSTAT
    0.0001
"""


def _deck(*extra, mesh=None):
    return ("*KEYWORD\n" + (mesh if mesh is not None else _mesh())
            + _PARTS + _CURVES + "".join(extra) + _TERM)


# ── *AIRBAG_HYBRID fixture ───────────────────────────────────────────────────
#
# Two gases with DELIBERATELY UNEQUAL properties in every slot, so that a
# mixture rule that swaps MW for Cpa, or averages with the wrong weights, or
# picks up gas 2's number for gas 1, cannot produce the expected value by
# accident. MW differs by 14 %, INITM by 3.8x, and A/B/C by ~5 %, 3.7x and 2.8x.
_G1 = dict(lcidm=90, lcidt=91, mw=0.028, initm=0.79,
           a=29.1234, b=0.00123, c=-1.2e-06)
_G2 = dict(lcidm=0, lcidt=0, mw=0.032, initm=0.21,
           a=30.5678, b=0.00456, c=-3.4e-06)


def _hybrid(sid=7, ab_id=42, atmost=293.0, atmosp=0.101325, hconv=0.0015,
            c23=0.7, lcc23=0, a23=100.0, lca23=0,
            cp23=0.35, lcp23=0, ap23=12.5, lcap23=92,
            opt=0, pvent=0.0345, gases=(_G1, _G2), fmass=True,
            jetting=False, nodes=(0, 0, 0), lcefr=0, lcidm0=0,
            ngas=None, atmosd=0.0, gc=0.0, fmass_val=0.0, keyword=None):
    kw = ("*" + keyword + "_ID" if keyword else
          "*AIRBAG_HYBRID_JETTING_ID" if jetting else "*AIRBAG_HYBRID_ID")
    out = [kw + "\n", f"{ab_id:>10d}Driver hybrid bag\n"]
    out.append(_card(sid, 1, 0, 1.0, 1.0, 0.0, 0.0, 0.0))
    out.append(_card(atmost, atmosp, atmosd, gc, 1.0, hconv))
    out.append(_card(c23, lcc23, a23, lca23, cp23, lcp23, ap23, lcap23))
    out.append(_card(opt, pvent, len(gases) if ngas is None else ngas,
                     lcefr, lcidm0, 0))
    for g in gases:
        out.append(_card(g["lcidm"], g["lcidt"], 0, g["mw"], g["initm"],
                         g["a"], g["b"], g["c"]))
        if fmass:
            out.append(_card(fmass_val))
    if jetting:
        out.append(_card(10.0, 10.0, 5.0, 10.0, 10.0, 15.0, 0.5236, 1.0))
        out.append(_card(0.0, 0.0, 0.0, 0, 0.0, *nodes))
    return "".join(out)


# ── *AIRBAG_PARTICLE fixture ─────────────────────────────────────────────────

_P1 = dict(lcm=90, lct=91, xm=2.8e-05, a=26092.0, b=8.2188, c=-1.9761e-03)
_P2 = dict(lcm=90, lct=91, xm=3.2e-05, a=29659.0, b=6.1373, c=-1.1865e-03)


def _particle(sd1=7, stype1=1, sd2=0, stype2=0, unit=2, tatm=293.0,
              patm=0.101325, tsw=0.0055, tend=0.06, iair=1, norif=1,
              vents=((2, 0, 0.7, 0, 0, 0, 0.0138),), gases=(_P1, _P2),
              orif=((4, 25.0, -1.0, 30.0, 1, 0, 0, 0),), npdata=0,
              fric=0.0, ab_id=77, opts="", segsid=11, jnode=1,
              mpp=(1.0, 2.0, 3.0), birth=(0.0, 0.06), nids=(0, 0, 0)):
    """The OPTION cards are written in the MANUAL's order (Vol I R17 p.3-94
    Card Summary): Card MPP FIRST, then Card ID, then Card T, card 1, the
    _SEGMENT card, card 3, the _JET card, card 7."""
    out = [f"*AIRBAG_PARTICLE{opts}_ID\n"]
    if "_MPP" in opts:
        out.append(_card(*mpp))
    out.append(f"{ab_id:>10d}CPM driver bag\n")
    if "_TIME" in opts:
        out.append(_card(*birth))
    out.append(_card(sd1, stype1, sd2, stype2, 0, npdata, fric, 0))
    if "_SEGMENT" in opts:
        out.append(_card(segsid))
    out.append(_card(200000, unit, 0, tatm, patm, len(vents), tend, tsw))
    if "_JET" in opts:
        out.append(_card(jnode))
    out.append(_card(iair, len(gases), norif, *nids, 0, 0.0))
    for _ in range(npdata):
        out.append(_card(9, 0, 1.0, 0.1, 0.0, 0.0, 0, 0.0))
    for v in vents:
        out.append(_card(*v))
    if iair:
        out.append(_card(patm, tatm, 2.896e-05, 26789.065, 7.7213,
                         -1.8027e-03, 0, 0))
    for g in gases:
        out.append(_card(g["lcm"], g["lct"], g["xm"], g["a"], g["b"],
                         g["c"], 1))
    for o in orif[:norif]:
        out.append(_card(*o))
    return "".join(out)


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridGasMaterials(unittest.TestCase):
    """The per-species /MAT/GAS/MOLE and the initial mixture."""

    def test_species_material_copies_the_molar_coefficients_verbatim(self):
        """``/MAT/GAS/MOLE`` wants a MOLAR Cp and the READER divides it by MW
        (hm_read_matgas.F:295-302). LS-DYNA's A/B/C are molar too, so the copy
        is 1:1 — dividing here as well, the way batch 1's /MAT/GAS/MASS path
        must, would understate Cp by a factor MW (36x on this gas)."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        blocks = _blocks(starter, "/MAT/GAS/MOLE/")
        # blocks[0] is the mixture; blocks[1] the one injected species.
        self.assertEqual(len(blocks), 2)
        sp = _cards(blocks[1])
        self.assertEqual(_col_f(sp[0], 1, 20), 0.028)          # MW
        self.assertEqual(_col_f(sp[1], 1, 20), 29.1234)        # Cpa == A
        self.assertEqual(_col_f(sp[1], 21, 40), 0.00123)       # Cpb == B
        self.assertEqual(_col_f(sp[1], 41, 60), -1.2e-06)      # Cpc == C
        self.assertEqual(_col_f(sp[1], 61, 80), 0.0)           # Cpd
        self.assertEqual(_col_f(sp[1], 81, 100), 0.0)          # Cpe
        # and the un-divided value is NOT what a mass-specific slot would hold
        self.assertNotAlmostEqual(_col_f(sp[1], 1, 20), 29.1234 / 0.028)

    def test_mole_variant_writes_no_cpf_card(self):
        """MASS has a sixth line and MOLE does not: hm_read_matgas.F reads
        MAT_F only for IGAS == 2. A Cpf written after a MOLE gas is the next
        keyword read as one, and everything below it shifts."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        for blk in _blocks(starter, "/MAT/GAS/MOLE/"):
            with self.subTest(blk=blk[0]):
                self.assertEqual(len(_cards(blk)), 2,
                                 "MW card + Cpa..Cpe card, and nothing else")

    def test_initial_mixture_is_a_mole_fraction_average(self):
        """INITM is a MASS fraction and MW/A/B/C are MOLAR, so the weights are
        converted before averaging::

            x_i = (w_i/M_i) / sum_j (w_j/M_j)
            M   = sum_i x_i M_i = sum_i w_i / sum_i (w_i/M_i)
            Cp  = sum_i x_i Cp_i

        Hand-computed for w = (0.79, 0.21) and M = (0.028, 0.032):
            sum   = 0.79/0.028 + 0.21/0.032 = 28.2142857143 + 6.5625
                  = 34.7767857143
            M     = 1.00/34.7767857143   = 0.0287548139
            x1    = 28.2142857143/34.7767857143 = 0.8112943633
            x2    = 1 - x1                      = 0.1887056367

        The numerator is sum(w), which happens to be 1 here — see
        test_the_mixture_mw_is_normalised_by_the_stated_sum for why that
        matters."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
        inv = 0.79 / 0.028 + 0.21 / 0.032
        x1 = (0.79 / 0.028) / inv
        x2 = (0.21 / 0.032) / inv
        self.assertAlmostEqual(_col_f(mix[0], 1, 20), 1.0 / inv, places=10)
        self.assertAlmostEqual(_col_f(mix[1], 1, 20),
                               x1 * 29.1234 + x2 * 30.5678, places=6)
        self.assertAlmostEqual(_col_f(mix[1], 21, 40),
                               x1 * 0.00123 + x2 * 0.00456, places=10)
        self.assertAlmostEqual(_col_f(mix[1], 41, 60),
                               x1 * -1.2e-06 + x2 * -3.4e-06, places=12)

    def test_the_mixture_mw_is_normalised_by_the_stated_sum(self):
        """M = sum(x_i M_i) = sum(w_i) / sum(w_i/M_i). The 1/sum(w_i/M_i)
        form assumes the INITM column sums to 1, which LS-DYNA only says it
        "should" (Vol I R17 p.3-50).

        The mole fractions normalise themselves, so Cp is unaffected and ONLY
        MW moves — by exactly 1/sum(w). The SAME composition stated as
        percentages therefore has to give the SAME MW, and under the
        un-normalised form it came out 100x smaller: MW drives
        Cv = Cp - R/MW and MI = Pext*(V+Veps)/((R/MW)*T0), with no starter
        diagnostic either way."""
        base = 1.0 / (0.79 / 0.028 + 0.21 / 0.032)
        for scale in (1.0, 2.0, 100.0):
            with self.subTest(scale=scale):
                g1 = dict(_G1, initm=0.79 * scale)
                g2 = dict(_G2, initm=0.21 * scale)
                _r, starter, _e = _convert(_deck(_hybrid(gases=(g1, g2))))
                mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
                self.assertAlmostEqual(_col_f(mix[0], 1, 20), base, places=10)

    def test_a_sum_other_than_one_is_reported_without_claiming_a_rescale(self):
        g1 = dict(_G1, initm=79.0)
        g2 = dict(_G2, initm=21.0)
        r, _s, _e = _convert(_deck(_hybrid(gases=(g1, g2))))
        hits = _warns(r, "INITM column sums to 100")
        self.assertTrue(hits, r.warnings)
        self.assertIn("RENORMALISED", hits[0])

    def test_a_single_species_mixture_keeps_its_own_mw(self):
        """The degenerate case the 1/inv form got wrong on its own: one gas
        with INITM 0.79 is a pure gas, so the mixture MW is that gas's MW."""
        _r, starter, _e = _convert(_deck(_hybrid(gases=(_G1,), ngas=1)))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
        self.assertAlmostEqual(_col_f(mix[0], 1, 20), 0.028, places=10)

    def test_a_mole_card_in_the_wrong_units_is_flagged_like_a_mass_one(self):
        """hm_read_matgas.F:295 runs ``CPA = CPA / MW * FAC`` on the MOLE
        branch, so the solver reaches the SAME mass-specific Cp the MASS card
        carries directly, and hm_read_monvol_type7 then forms the same
        ``CVI = CPI - R_IGC1/MW``. MEASURED before the fix: the batch-1 MASS
        card was flagged and the batch-2 MOLE card passed in silence while
        the starter echoed GAMMA = -3.5972E-03 with 0 ERROR(S)."""
        si = dict(_G1, mw=0.028, a=29.1234, b=0.0, c=0.0, initm=1.0)
        r, _s, _e = _convert(_deck(_hybrid(gases=(si,), ngas=1)))
        hits = _warns(r, "not a usable ratio of specific heats")
        self.assertTrue(hits, r.warnings)
        self.assertIn("/MAT/GAS/MOLE", hits[0])

    def test_a_well_scaled_mole_card_raises_no_gamma_warning(self):
        """The guard must not fire on a deck stated in the mesh's own units:
        MW 2.897e-05 with Cpa 29086 on an Mg/mm/s deck gives gamma 1.4."""
        ok = dict(_G1, mw=2.8970286e-05, a=29086.167, b=0.0, c=0.0, initm=1.0)
        r, _s, _e = _convert(_deck(_hybrid(gases=(ok,), ngas=1)))
        self.assertFalse(_warns(r, "not a usable ratio"), r.warnings)

    def test_a_species_with_no_mass_flow_curve_leaves_no_orphan_function(self):
        """The default fixture's gas 2 has LCIDM = 0: it counts toward the
        INITIAL mixture but gets no injector row, so it needs neither a
        /MAT/GAS id nor a synthesized injection-temperature /FUNCT. Both were
        allocated anyway, leaving a hole in the /MAT id stream and a /FUNCT
        the deck referenced nowhere."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        fids = [ln.split("/")[-1] for ln in starter.splitlines()
                if ln.startswith("/FUNCT/")]
        for fid in fids:
            title = starter.split(f"/FUNCT/{fid}\n", 1)[1].splitlines()[0]
            if "INJECT_T" in title:
                self.assertIn(f"{int(fid):>10d}", starter,
                              f"/FUNCT/{fid} '{title}' is referenced")
        self.assertNotIn("INJECT_T_GAS_2", starter)
        # gas 2 gets no /MAT/GAS of its own either
        self.assertEqual(len(_blocks(starter, "/MAT/GAS/MOLE/")), 2,
                         "the mixture and the ONE injected species")

    def test_the_mole_fraction_average_differs_from_dyna2rads_mean(self):
        """dyna2rad accumulates ``radMW += MW_i*INITM_i/sum(INITM)`` and the
        same for A/B/C (convertcontrolvols.cxx:2494-2497) — a MASS-weighted
        arithmetic mean of MOLAR quantities. The two agree only when every MW
        is equal, which is why the fixture's two differ."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
        d2r_mw = 0.028 * 0.79 + 0.032 * 0.21
        self.assertNotAlmostEqual(_col_f(mix[0], 1, 20), d2r_mw, places=6)

    def test_a_species_with_a_fractional_initm_is_not_dropped(self):
        """d2r gates the mixture on ``INITM >= 1.0`` and the injector on
        ``INITM == 0.0``, so a species carrying its documented fraction —
        0.79 nitrogen — contributes to NEITHER and vanishes from the deck.
        Both of this fixture's gases carry one, and both are used."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
        # A mixture built from gas 1 alone would state MW = 0.028 exactly.
        self.assertNotEqual(_col_f(mix[0], 1, 20), 0.028)
        self.assertNotEqual(_col_f(mix[0], 1, 20), 0.032)

    def test_no_initm_falls_back_to_gas_one_and_says_so(self):
        """/MONVOL/AIRBAG1 REQUIRES a mat_ID (ERROR 699) and derives the
        initial gas mass from it, so there is no "no initial gas" state to
        express. d2r leaves mat_ID unset, which the starter refuses."""
        g1 = dict(_G1, initm=0.0)
        g2 = dict(_G2, initm=0.0)
        r, starter, _e = _convert(_deck(_hybrid(gases=(g1, g2))))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
        self.assertEqual(_col_f(mix[0], 1, 20), 0.028)
        self.assertTrue(_warns(r, "no gas species carries a non-zero INITM"))
        monvol = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertNotEqual(_col_i(monvol[2], 1, 10), 0, "mat_ID must be set")

    def test_zero_mw_is_named_as_starter_error_710(self):
        g1 = dict(_G1, mw=0.0)
        r, _s, _e = _convert(_deck(_hybrid(gases=(g1, _G2))))
        self.assertTrue(_warns(r, "ERROR 710"))


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridInjector(unittest.TestCase):
    """/PROP/INJECT1 with N_gases > 1."""

    def test_one_row_per_injected_species_in_card_order(self):
        g2 = dict(_G2, lcidm=93, lcidt=91)
        _r, starter, _e = _convert(_deck(_hybrid(gases=(_G1, g2))))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[0], 1, 10), 2, "N_gases")
        self.assertEqual(_col_i(inj[0], 11, 20), 1, "Iflow == 1, a mass RATE")
        self.assertEqual(_col_f(inj[0], 21, 40), 1.0, "Ascale_T explicit")
        self.assertEqual(len(inj), 3, "card 1 + one row per gas")
        self.assertEqual(_col_i(inj[1], 11, 20), 90, "gas 1 fun_ID_M")
        self.assertEqual(_col_i(inj[2], 11, 20), 93, "gas 2 fun_ID_M")
        self.assertEqual(_col_i(inj[1], 21, 30), 91, "gas 1 fun_ID_T")
        # the two Mat_ID cells are distinct and both are real /MAT/GAS ids
        mats = {int(b[0].rsplit("/", 1)[1])
                for b in _blocks(starter, "/MAT/GAS/MOLE/")}
        self.assertIn(_col_i(inj[1], 1, 10), mats)
        self.assertIn(_col_i(inj[2], 1, 10), mats)
        self.assertNotEqual(_col_i(inj[1], 1, 10), _col_i(inj[2], 1, 10))

    def test_a_species_without_a_mass_curve_gets_no_injector_row(self):
        """Gas 2 of the fixture is initial fill only (LCIDM = 0)."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[0], 1, 10), 1)
        self.assertEqual(len(inj), 2)

    def test_the_mass_curve_is_referenced_unshifted(self):
        """No /SENSOR/TIME is created and Ittf is 0, so the curve's abscissa
        stays absolute run time. d2r shifts it by -TTF and sets Ittf=3, which
        cancels on the injector and mis-times the vent curves."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[1], 11, 20), 90, "the deck's own curve id")
        self.assertNotIn("/SENSOR/TIME", starter)
        monvol = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_i(monvol[2], 91, 100), 0, "Ittf")
        self.assertEqual(_col_i(monvol[4], 11, 20), 0, "sens_ID")

    def test_a_missing_temperature_curve_gets_a_named_flat_function(self):
        """fun_ID_T = 0 makes the starter read Fscale_T as a constant, and
        this converter writes that 0 — i.e. injection at absolute zero. A flat
        /FUNCT at the ambient temperature is emitted instead."""
        g1 = dict(_G1, lcidt=0)
        r, starter, _e = _convert(_deck(_hybrid(gases=(g1, _G2))))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        fid = _col_i(inj[1], 21, 30)
        self.assertNotEqual(fid, 0)
        fct = _cards(_block(starter, f"/FUNCT/{fid}"))
        self.assertEqual([_col_f(fct[0], 21, 40), _col_f(fct[1], 21, 40)],
                         [293.0, 293.0])
        self.assertTrue(_warns(r, "no temperature curve"))

    def test_a_negative_curve_id_is_the_spline_flag_not_a_sign(self):
        """LS-DYNA reads LCIDM < 0 as "cubic-spline interpolation of |id|".
        Radioss /FUNCT is piecewise linear only, so |id| is referenced and the
        interpolation ORDER is what is lost."""
        g1 = dict(_G1, lcidm=-90)
        r, starter, _e = _convert(_deck(_hybrid(gases=(g1, _G2))))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[1], 11, 20), 90)
        self.assertTrue(_warns(r, "CUBIC-SPLINE"))

    def test_no_injected_species_emits_no_injector(self):
        """An injector with N_gases = 0 is starter ERROR 696."""
        g1 = dict(_G1, lcidm=0, lcidt=0)
        r, starter, _e = _convert(_deck(_hybrid(gases=(g1, _G2))))
        self.assertNotIn("/PROP/INJECT1/", starter)
        monvol = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_i(monvol[3], 1, 10), 0, "Njet")
        self.assertTrue(_warns(r, "receives NO GAS at all"))


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridMonvolCard(unittest.TestCase):
    """The /MONVOL/AIRBAG1 columns a HYBRID bag fills that batch 1 leaves 0."""

    def test_card_columns(self):
        _r, starter, _e = _convert(_deck(_hybrid()))
        blk = _block(starter, "/MONVOL/AIRBAG1/")
        self.assertEqual(blk[0], "/MONVOL/AIRBAG1/42")
        self.assertEqual(blk[1], "Driver hybrid bag")
        c = _cards(blk)
        self.assertEqual(_col_f(c[0], 21, 40), 0.0015, "HCONV -> Hconv")
        self.assertEqual(_col_f(c[2], 41, 60), 0.101325, "ATMOSP -> Pext")
        self.assertEqual(_col_f(c[2], 61, 80), 293.0, "ATMOST -> T0")
        self.assertEqual(_col_i(c[2], 81, 90), 0, "Iequi")
        self.assertEqual(_col_i(c[2], 91, 100), 0, "Ittf")
        self.assertEqual(_col_i(c[3], 1, 10), 1, "Njet")

    def test_a_negative_hconv_curve_is_named_and_dropped(self):
        r, starter, _e = _convert(_deck(_hybrid(hconv=-93.0)))
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_f(c[0], 21, 40), 0.0)
        self.assertTrue(_warns(r, "|HCONV| is a load curve"))

    def test_nporsurf_is_zero_and_every_leak_path_is_a_vent_hole(self):
        """The vent sub-block is the one pinned identical across AIRBAG1,
        COMMU1 and FVMBAG1 (venthole1.cfg:17), while the porous block is
        documented for type 9 only — and there the reader discards
        surf_IDps, Iblockage and both functions at Iformps = 0."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        nvent = _col_i(c[5], 1, 10)
        self.assertEqual(nvent, 2, "the orifice and the fabric porosity")
        self.assertEqual(_col_i(c[5], 11, 20), 0, "Nporsurf")


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridVents(unittest.TestCase):
    """Card 4: the orifice, the fabric porosity, and PVENT."""

    def _vents(self, starter):
        """The vent blocks of the one /MONVOL, as lists of four data cards."""
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        n = _col_i(c[5], 1, 10)
        rows = c[6:]
        return [rows[i * 4:(i + 1) * 4] for i in range(n)]

    def test_a_positive_a23_is_a_scalar_whole_bag_area(self):
        """With surf_IDv = 0 the reader takes Avent as an ABSOLUTE AREA and
        forces Bvent to 0. LS-DYNA's leak area is the product A23 x C23."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        v = self._vents(starter)[0]
        self.assertEqual(_col_i(v[0], 1, 10), 0, "surf_IDv")
        self.assertEqual(_col_i(v[0], 11, 20), 1, "Iform, isenthalpic")
        self.assertEqual(_col_f(v[0], 21, 40), 100.0 * 0.7, "Avent = A23*C23")
        self.assertEqual(_col_f(v[0], 41, 60), 0.0, "Bvent")

    def test_a_negative_a23_names_a_part_and_avent_becomes_a_scale_factor(self):
        """|A23| is a *PART when LCA23 != -1, and the vent then has a NAMED
        surface — in which case the SAME Avent column is a scale factor on
        that surface's current area, not an absolute one."""
        _r, starter, _e = _convert(_deck(_hybrid(a23=-2.0, lca23=0)))
        v = self._vents(starter)[0]
        surf = _col_i(v[0], 1, 10)
        self.assertNotEqual(surf, 0)
        self.assertEqual(_col_f(v[0], 21, 40), 0.7, "Avent = C23, a factor")
        # and it resolves to a real /SURF holding the patch element only
        grp = _block(starter, f"/SURF/GRSHEL/{surf}")
        gid = _col_i(_cards(grp)[0], 1, 10)
        self.assertEqual(_cards(_block(starter, f"/GRSHEL/SHEL/{gid}"))[0]
                         .split(), ["4"])

    def test_a_negative_a23_with_lca23_minus_one_names_a_part_set(self):
        _r, starter, _e = _convert(_deck(_hybrid(a23=-7.0, lca23=-1)))
        v = self._vents(starter)[0]
        surf = _col_i(v[0], 1, 10)
        gid = _col_i(_cards(_block(starter, f"/SURF/GRSHEL/{surf}"))[0], 1, 10)
        eids = _cards(_block(starter, f"/GRSHEL/SHEL/{gid}"))[0].split()
        self.assertEqual(eids, ["1", "2", "3", "4", "5", "6"],
                         "*SET_PART_LIST 7 is the whole bag")

    def test_a_vent_part_outside_the_bag_is_documented_not_an_error(self):
        """"With SIDTYP > 0, airbag pressure will not be applied to part/set
        |A23| representing venting holes if part/set |A23| is not included in
        SID, the part set representing the airbag. ... The area of this
        part/set becomes the vent orifice area" (Vol I R17 p.3-46).

        So it is a documented configuration, not the ERROR 902 containment
        rule (which is the COMMUNICATING-surface rule). Sealing the vent —
        surf_IDv 0 with Avent 0 — silently removed a hole LS-DYNA has open."""
        mesh = (_mesh(pid_main=1, pid_patch=2)
                + _mesh(nid0=100, eid0=100, pid_main=3, pid_patch=3, x0=25.0))
        parts = """\
*PART
bag
         1         1         1
*PART
patch
         2         1         1
*PART
outboard vent
         3         1         1
*SECTION_SHELL
         1         2       1.0         2         1         0         0         1
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*SET_PART_LIST
         7       0.0       0.0       0.0       0.0MECH
         1         2
"""
        deck = ("*KEYWORD\n" + mesh + parts + _CURVES
                + _hybrid(a23=-3.0, lca23=0) + _TERM)
        r, starter, _e = _convert(deck)
        v = self._vents(starter)[0]
        self.assertEqual(_col_i(v[0], 1, 10), 0, "surf_IDv, whole-bag mode")
        # six 10x10 faces = 600, frozen at t=0 and scaled by C23
        self.assertAlmostEqual(_col_f(v[0], 21, 40), 600.0 * 0.7, places=6)
        hits = _warns(r, "DOCUMENTED, not wrong")
        self.assertTrue(hits, r.warnings)
        self.assertIn("frozen", hits[0])

    def test_lca23_is_shifted_from_absolute_to_gauge_pressure(self):
        """LS-DYNA's LCA23 is vent area vs ABSOLUTE pressure; airbagb1.F reads
        fct_IDP at (P - PEXT)*SCALP. The copy's abscissae move by -Pext.

        A23 must be BLANK for the curve to be live at all — see
        test_a23_and_lca23_are_alternatives_not_a_product."""
        _r, starter, _e = _convert(_deck(_hybrid(a23=0.0, lca23=92)))
        v = self._vents(starter)[0]
        fid = _col_i(v[2], 11, 20)
        self.assertNotEqual(fid, 92, "a shifted COPY, not the deck's curve")
        pts = _cards(_block(starter, f"/FUNCT/{fid}"))
        self.assertAlmostEqual(_col_f(pts[0], 1, 20), 0.0, places=9)
        self.assertAlmostEqual(_col_f(pts[1], 1, 20), 0.1, places=9)
        self.assertEqual(_col_f(pts[1], 21, 40), 50.0, "ordinates untouched")
        # Avent carries the COEFFICIENT alone; the curve carries the area, and
        # the engine forms AOUT = Avent * f_P((P-Pext)*SCALP).
        self.assertEqual(_col_f(v[0], 21, 40), 0.7, "Avent = C23")

    def test_a23_and_lca23_are_alternatives_not_a_product(self):
        """Vol I R17 p.3-47: A23 "EQ.0.0: Set A23 to zero if LCA23 is != 0"
        and LCA23 "A nonzero value for A23 overrides LCA23". Exactly one is
        live — but Radioss MULTIPLIES Avent by fct_IDP (airbagb1.F), so
        emitting both vented through A23 x f_area(P) instead of A23, and the
        documented A23 = 0 form gave Avent = 0*C23 = 0, a bag that never
        vents (MEASURED: WARNING 1019, AVENT = 0, on 0 ERROR(S))."""
        r, starter, _e = _convert(_deck(_hybrid(a23=100.0, lca23=92)))
        v = self._vents(starter)[0]
        self.assertEqual(_col_f(v[0], 21, 40), 70.0, "Avent = A23*C23")
        self.assertEqual(_col_i(v[2], 11, 20), 0, "the curve is DROPPED")
        self.assertTrue(_warns(r, "non-zero A23 overrides the curve"))

    def test_ap23_and_lcap23_take_the_same_override(self):
        """"A nonzero value for AP23 overrides LCAP23" (Vol I R17 p.3-47)."""
        r, starter, _e = _convert(_deck(_hybrid(ap23=12.5, lcap23=92)))
        fabric = self._vents(starter)[1]
        self.assertAlmostEqual(_col_f(fabric[0], 21, 40), 0.35 * 12.5)
        self.assertEqual(_col_i(fabric[2], 11, 20), 0, "the curve is DROPPED")
        self.assertTrue(_warns(r, "AP23=12.5"))
        # and blanking AP23 makes the curve the AREA, with CP23 as the factor
        _r2, s2, _e2 = _convert(_deck(_hybrid(ap23=0.0, lcap23=92)))
        f2 = self._vents(s2)[1]
        self.assertEqual(_col_f(f2[0], 21, 40), 0.35, "Avent = CP23")
        self.assertNotEqual(_col_i(f2[2], 11, 20), 0, "the shifted curve")

    def test_a_blank_c23_is_a_zero_coefficient_not_an_ideal_orifice(self):
        """"Vent orifice coefficient which applies to exit hole. Set to zero
        if LCC23 is defined below" (Vol I R17 p.3-46) — the mass flow is
        C23*A23*<isentropic>, so C23 = 0 with no LCC23 means NO flow. Reading
        the blank as 1.0 gave the bag a leak path LS-DYNA does not have."""
        r, starter, _e = _convert(_deck(_hybrid(c23=0.0, lcc23=0, a23=100.0)))
        self.assertEqual([v[0][80:100].strip() for v in self._vents(starter)],
                         ["VENT_FABRIC"], "the orifice is NOT emitted")
        self.assertTrue(_warns(r, "vent orifice COEFFICIENT is 0"))

    def test_a_blank_cp23_is_a_zero_coefficient_too(self):
        r, starter, _e = _convert(_deck(_hybrid(cp23=0.0, lcp23=0)))
        self.assertEqual([v[0][80:100].strip() for v in self._vents(starter)],
                         ["VENT_A23"], "no fabric hole")
        self.assertTrue(_warns(r, "fabric-porosity orifice COEFFICIENT is 0"))

    def test_lcc23_is_a_time_function_only_when_c23_is_blank(self):
        """LS-DYNA: "Nonzero C23 overrides LCC23". dyna2rad does the opposite
        — convertcontrolvols.cxx:2801 forces C23 to 1.0 and keeps the curve."""
        r, starter, _e = _convert(_deck(_hybrid(c23=0.7, lcc23=93)))
        v = self._vents(starter)[0]
        self.assertEqual(_col_i(v[2], 1, 10), 0, "fct_IDt dropped")
        self.assertEqual(_col_f(v[0], 21, 40), 70.0, "C23 kept")
        self.assertTrue(_warns(r, "non-zero C23 overrides"))

        _r2, s2, _e2 = _convert(_deck(_hybrid(c23=0.0, lcc23=93)))
        v2 = self._vents(s2)[0]
        self.assertEqual(_col_i(v2[2], 1, 10), 93, "fct_IDt is the curve")
        self.assertEqual(_col_f(v2[0], 21, 40), 100.0, "Avent = A23 * 1")

    def test_a_negative_lcc23_is_a_pressure_RATIO_and_cannot_map(self):
        r, starter, _e = _convert(_deck(_hybrid(c23=0.0, lcc23=-93)))
        v = self._vents(starter)[0]
        self.assertEqual(_col_i(v[2], 1, 10), 0)
        self.assertTrue(_warns(r, "RELATIVE pressure ratio"))

    def test_the_fabric_porosity_is_the_second_vent_hole(self):
        """CP23 is a dimensionless coefficient and AP23 an area, so their
        product is an effective leak area — exactly what Avent means with no
        named surface."""
        _r, starter, _e = _convert(_deck(_hybrid()))
        v = self._vents(starter)[1]
        self.assertEqual(_col_i(v[0], 1, 10), 0, "surf_IDv")
        self.assertAlmostEqual(_col_f(v[0], 21, 40), 0.35 * 12.5)
        self.assertEqual(v[0][80:100].strip(), "VENT_FABRIC")

    def test_pvent_gates_the_orifice_only(self):
        """airbagb1.F:290 ORs the time and pressure criteria, so dPdef only
        bites when Tstart is out of reach. A weave leaks whenever there IS a
        pressure difference, so the threshold goes on the orifice alone —
        putting it on both would seal a leak LS-DYNA has open from t=0."""
        _r, starter, _e = _convert(_deck(_hybrid(pvent=0.0345)))
        orifice, fabric = self._vents(starter)
        self.assertEqual(_col_f(orifice[1], 41, 60), 0.0345, "dPdef")
        self.assertEqual(_col_f(orifice[1], 1, 20), 1.0e30, "Tstart")
        self.assertEqual(_col_f(fabric[1], 41, 60), 0.0)
        self.assertEqual(_col_f(fabric[1], 1, 20), 0.0)

    def test_opt_nonzero_drops_the_fabric_porosity_columns(self):
        """LS-DYNA ITSELF zeroes CP23/LCP23/AP23/LCAP23 when OPT != 0 and
        takes the porosity from *MAT_FABRIC instead. dyna2rad never reads OPT
        (grep LSD_OPTHybrid = 0 hits) and converts them anyway."""
        r, starter, _e = _convert(_deck(_hybrid(opt=2)))
        self.assertEqual(len(self._vents(starter)), 1, "the orifice only")
        self.assertTrue(_warns(r, "LS-DYNA ITSELF zeroes CP23"))

    def test_no_vent_at_all_is_named(self):
        r, starter, _e = _convert(_deck(
            _hybrid(c23=0.0, a23=0.0, cp23=0.0, ap23=0.0, lcap23=0,
                    pvent=0.0)))
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_i(c[5], 1, 10), 0, "Nvent")
        self.assertTrue(_warns(r, "this bag has NO VENT at all"))


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridJetting(unittest.TestCase):
    """_JETTING: every field gets a verdict."""

    def test_ijet_is_never_one_because_the_starter_refuses_a_zero_function(
            self):
        """Ijet=1 obliges fct_IDPt/fct_IDPTheta/fct_IDPDelta, and the reader
        has NO zero guard: hm_read_monvol_type7.F:585-620 searches each id in
        NPC inside ``IF (IJET(II) > 0)`` and calls ANCMSG(MSGID = 12/13/14,
        MSGTYPE = MSGERROR) when it is not found. Id 0 never is.

        MEASURED on the converted deck: 3 ERROR(S), 'UNDEFINED POROSITY/TIME|
        PRESSURE|AREA FUNCTION ID=0', ERROR TERMINATION, no restart file. The
        same deck without the jetting block terminates with 0 ERROR(S).

        So the jet is dropped, and the geometry with it — no jetting card is
        written at all and the injector row's node columns stay 0. The card
        AFTER the injector row must therefore be Nvent, not the jet card."""
        for nodes in ((1, 5, 0), (3, 8, 6), (0, 0, 0)):
            with self.subTest(nodes=nodes):
                r, starter, _e = _convert(_deck(
                    _hybrid(jetting=True, nodes=nodes)))
                c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
                self.assertEqual(_col_i(c[4], 21, 30), 0, "Ijet")
                self.assertEqual(_col_i(c[4], 31, 40), 0, "node_ID1")
                self.assertEqual(_col_i(c[4], 41, 50), 0, "node_ID2")
                self.assertEqual(_col_i(c[4], 51, 60), 0, "node_ID3")
                # c[5] is the Nvent/Nporsurf card, NOT a jetting card: two
                # cells only, and Nporsurf is 0.
                self.assertEqual(_col_i(c[5], 11, 20), 0, "Nporsurf")
                self.assertEqual(c[5][20:].strip(), "")
                self.assertTrue(_warns(r, "loaded by UNIFORM PRESSURE"))

    def test_a_jetting_deck_writes_no_zero_function_id_anywhere(self):
        """The ERROR 12/13/14 guard, stated as a property of the whole deck:
        no /MONVOL card may reference function id 0 in a jet slot."""
        _r, starter, _e = _convert(_deck(_hybrid(jetting=True, nodes=(1, 5, 6))))
        block = _block(starter, "/MONVOL/AIRBAG1/")
        self.assertFalse(any("fct_IDPt" in ln for ln in block), block)

    def test_the_node_form_names_the_geometry_it_had_to_drop(self):
        r, _s, _e = _convert(_deck(_hybrid(jetting=True, nodes=(1, 5, 0))))
        hits = _warns(r, "node_ID1=1")
        self.assertTrue(hits)
        self.assertIn("CONICAL", hits[0])
        self.assertIn("ERROR 12/13/14", hits[0])

    def test_node_id3_selects_a_dihedral_jet(self):
        r, _s, _e = _convert(_deck(_hybrid(jetting=True, nodes=(1, 5, 6))))
        self.assertTrue(_warns(r, "DIHEDRAL"))

    def test_coordinates_without_nodes_drop_the_jet_loudly(self):
        """Radioss's jet is node-based and this converter creates no nodes."""
        r, starter, _e = _convert(_deck(_hybrid(jetting=True, nodes=(0, 0, 0))))
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_i(c[4], 21, 30), 0, "Ijet")
        self.assertTrue(_warns(r, "loaded by UNIFORM PRESSURE"))

    def test_card_seven_is_read_by_the_manual_not_by_the_reader_cfg(self):
        """subobj_airbag_hybrid.cfg writes card 7 as SEVEN fields with IDUM
        omitted, so a cfg-following reader puts NODE1 in the IDUM slot and
        drops NODE3. Vol I R17 p.3-51 is explicit that field 5 is IDUM.

        The nodes are not emitted (the jet is dropped), so the READER is
        checked at its own level: the warning names all three by value."""
        r, _s, _e = _convert(_deck(_hybrid(jetting=True, nodes=(3, 8, 6))))
        hits = _warns(r, "node_ID1=3")
        self.assertTrue(hits, r.warnings)
        self.assertIn("node_ID2=8", hits[0])
        self.assertIn("node_ID3=6", hits[0])

    def test_cone_angle_and_efficiency_are_named_and_dropped(self):
        r, _s, _e = _convert(_deck(_hybrid(jetting=True, nodes=(1, 5, 0))))
        self.assertTrue(_warns(r, "jet cone"))
        self.assertTrue(_warns(r, "Bernoulli efficiency"))


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridDroppedFields(unittest.TestCase):
    """The card-3/4/5 fields with no Radioss expression, by name and value."""

    def test_lcidm0_says_the_inflator_is_wrong(self):
        """With LCIDM0 the per-gas LCIDM becomes a MOLAR FRACTION curve, which
        is /PROP/INJECT2's shape and not this batch's. Converting it as a mass
        flow is wrong by the ratio of the total flow to each fraction."""
        r, _s, _e = _convert(_deck(_hybrid(lcidm0=93)))
        hits = _warns(r, "LCIDM0=93")
        self.assertTrue(hits)
        self.assertIn("/PROP/INJECT2", hits[0])

    def test_lcefr_gc_atmosd_fmass_and_vntopt_are_each_named(self):
        g1 = dict(_G1)
        r, _s, _e = _convert(_deck(_hybrid(
            lcefr=93, gc=8.314, atmosd=1.29e-9, gases=(g1, _G2))))
        for needle in ("LCEFR=93", "GC=8.314", "ATMOSD=1.29e-09"):
            with self.subTest(needle=needle):
                self.assertTrue(_warns(r, needle))

    def test_fmass_is_reported_when_stated(self):
        """FMASS is the fraction of additional ASPIRATED mass drawn in with
        the inflator jet. Radioss's injector adds only the mass its own curve
        states, so the bag fills with less gas than LS-DYNA's. dyna2rad never
        reads the FMASS card at all."""
        r, _s, _e = _convert(_deck(_hybrid(fmass_val=0.25)))
        self.assertTrue(_warns(r, "ASPIRATED mass"))

    def test_a_zero_ambient_pressure_is_the_one_atmosphere_trap(self):
        r, _s, _e = _convert(_deck(_hybrid(atmosp=0.0)))
        self.assertTrue(_warns(r, "REQUEST FOR ONE ATMOSPHERE"))


# ═══════════════════════════════════════════════════════════════════════════
class TestHybridCardWalk(unittest.TestCase):
    """The NGAS count-driven walk (#119)."""

    def test_the_fmass_card_is_detected_by_content(self):
        """Card 5.2 is a later addition and real decks omit it. Its presence
        decides the stride, and the stride decides where the jetting cards
        start; guessing reads gas 2's mass curve as gas 1's aspiration."""
        for fmass in (True, False):
            with self.subTest(fmass=fmass):
                _r, starter, _e = _convert(_deck(_hybrid(fmass=fmass)))
                blocks = _blocks(starter, "/MAT/GAS/MOLE/")
                sp = _cards(blocks[1])
                self.assertEqual(_col_f(sp[0], 1, 20), 0.028)
                self.assertEqual(_col_f(sp[1], 1, 20), 29.1234)
                mix = _cards(blocks[0])
                inv = 0.79 / 0.028 + 0.21 / 0.032
                self.assertAlmostEqual(_col_f(mix[0], 1, 20), 1.0 / inv,
                                       places=10)

    def test_the_walk_survives_without_the_fmass_card_before_jetting(self):
        """The stride positions the jetting cards, so a wrong one reads card 6
        as a gas card and the jet nodes as heat capacities. The jet itself is
        dropped, so the nodes are checked where the reader put them."""
        r, _s, _e = _convert(_deck(
            _hybrid(fmass=False, jetting=True, nodes=(1, 5, 0))))
        hits = _warns(r, "node_ID1=1")
        self.assertTrue(hits, r.warnings)
        self.assertIn("node_ID2=5", hits[0])

    def test_a_blank_fmass_card_does_not_end_the_gas_block(self):
        """FMASS's default is "none" (Vol I R17 p.3-49), so an all-spaces card
        5.2 is legal and is how a preprocessor writes FMASS = 0. It has ZERO
        populated cells — the same count an ABSENT card has — and deciding the
        stride on that alone read gas 2 off the blank line: MEASURED, gas 2
        came back MW = 0, no /MAT/GAS was emitted for it, the injector lost
        its row and the mixture was built from gas 1 alone."""
        g1 = dict(_G1)
        g2 = dict(_G2, lcidm=90, lcidt=91)
        deck = _deck(_hybrid(gases=(g1, g2), fmass=True, fmass_val=None))
        r, starter, _e = _convert(deck)
        self.assertEqual(r.skipped_keywords, [])
        blocks = _blocks(starter, "/MAT/GAS/MOLE/")
        self.assertEqual(len(blocks), 3, "mixture + 2 species")
        self.assertEqual(_col_f(_cards(blocks[1])[0], 1, 20), 0.028)
        self.assertEqual(_col_f(_cards(blocks[2])[0], 1, 20), 0.032)
        inv = 0.79 / 0.028 + 0.21 / 0.032
        self.assertAlmostEqual(_col_f(_cards(blocks[0])[0], 1, 20),
                               1.0 / inv, places=10)
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[0], 1, 10), 2, "N_gases")

    def test_a_blank_fmass_card_at_ngas_one_still_places_the_jet_cards(self):
        deck = _deck(_hybrid(gases=(_G1,), ngas=1, fmass=True, fmass_val=None,
                             jetting=True, nodes=(1, 5, 6)))
        r, _s, _e = _convert(deck)
        hits = _warns(r, "node_ID1=1")
        self.assertTrue(hits, r.warnings)
        self.assertIn("node_ID3=6", hits[0])

    def test_ngas_zero_emits_no_monvol_and_says_why(self):
        r, starter, _e = _convert(_deck(_hybrid(gases=(), ngas=0)))
        self.assertNotIn("/MONVOL/", starter)
        self.assertTrue(_warns(r, "declares NO gas species at all"))
        self.assertIn("/SHELL/1", starter, "the mesh survives")

    def test_a_blank_trailing_card_ends_the_walk(self):
        """A deck that stops after the last gas card — no FMASS line, nothing
        below — must not read past the end of the block."""
        deck = _deck(_hybrid(fmass=False, gases=(_G1,), ngas=1))
        r, starter, _e = _convert(deck)
        self.assertEqual(r.skipped_keywords, [])
        blocks = _blocks(starter, "/MAT/GAS/MOLE/")
        self.assertEqual(_col_f(_cards(blocks[1])[0], 1, 20), 0.028)

    def test_the_rbid_card_walk_still_shifts_card_three(self):
        """*AIRBAG_HYBRID shares card 1 and the RBID cards above card 3 with
        the batch-1 models, so the same walk applies: RBID < 0 inserts THREE
        sensor cards, and reading card 3 at a fixed offset would take an
        acceleration magnitude for the ambient temperature."""
        body = _hybrid()
        lines = body.splitlines(keepends=True)
        lines[2] = _card(7, 1, -1, 1.0, 1.0, 0.0, 0.0, 0.0)
        lines.insert(3, _card(1.0, 2.0, 3.0, 4.0, 5.0))
        lines.insert(4, _card(6.0, 7.0, 8.0, 9.0))
        lines.insert(5, _card(10.0, 11.0, 12.0, 13.0))
        _r, starter, _e = _convert(_deck("".join(lines)))
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_f(c[2], 61, 80), 293.0, "ATMOST, not 1.0")
        self.assertEqual(_col_f(c[2], 41, 60), 0.101325)


# ═══════════════════════════════════════════════════════════════════════════
class TestParticleFvmbag2(unittest.TestCase):
    """*AIRBAG_PARTICLE -> /MONVOL/FVMBAG2."""

    def test_card_columns(self):
        _r, starter, _e = _convert(_deck(_particle()))
        blk = _block(starter, "/MONVOL/FVMBAG2/")
        self.assertEqual(blk[0], "/MONVOL/FVMBAG2/77")
        c = _cards(blk)
        self.assertNotEqual(_col_i(c[0], 1, 10), 0, "surf_IDex")
        self.assertEqual(_col_i(c[0], 11, 20), 0, "surf_IDin, no SD2")
        self.assertEqual(_col_f(c[1], 41, 60), 0.101325, "PAIR -> Pext")
        self.assertEqual(_col_f(c[1], 61, 80), 293.0, "TAIR -> T0")
        self.assertEqual(_col_i(c[1], 91, 100), 0, "Ittf")
        self.assertEqual(_col_i(c[2], 1, 10), 1, "Njet")

    def test_ih3d_is_not_written_at_begin_2022(self):
        """IH3D appears at columns 41-50 of card 1 from FORMAT(radioss2023)
        on, and this converter writes /BEGIN 2022. MEASURED on a twin-deck
        probe: writing it at 2022 costs WARNING 100213 and the field is
        dropped — survivable, but a warning for a column carrying nothing."""
        _r, starter, _e = _convert(_deck(_particle()))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(len(c[0].rstrip()), 40,
                         "surf_IDex + surf_IDin + Hconv, and nothing after")

    def test_the_injector_row_is_one_card_with_no_jet_columns(self):
        """FVMBAG2 has no Ijet and no jet nodes: the gas enters through
        surf_IDinj at a hard-coded 300 m/s (FVEL = THREE100 * FAC_T/FAC_L)."""
        _r, starter, _e = _convert(_deck(_particle()))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(len(c[3].rstrip()), 30)
        self.assertNotEqual(_col_i(c[3], 1, 10), 0, "inject_ID")
        self.assertEqual(_col_i(c[3], 11, 20), 0, "sens_ID")
        self.assertNotEqual(_col_i(c[3], 21, 30), 0, "surf_IDinj")

    def test_the_fvm_numerics_card(self):
        """Cgmerg deliberately COARSENS the merge (the cfg default is 0.02),
        which keeps the FV count and hence the bag's own step from collapsing
        as the bag folds. Iswitch = 1 accompanies Tswitch: fv_up_switch.F
        gates the whole switch on IVOLU(74), so dyna2rad's Tswitch with
        Iswitch = 0 can never fire."""
        _r, starter, _e = _convert(_deck(_particle(tsw=0.0055)))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_f(c[-2], 1, 20), 0.05, "Cgmerg")
        self.assertEqual(_col_f(c[-2], 21, 40), 0.0055, "TSW -> Tswitch")
        self.assertEqual(_col_i(c[-2], 51, 60), 1, "Iswitch")
        self.assertEqual(_col_f(c[-1], 1, 20), 0.9, "Dtsca")

    def test_dtmin_follows_the_unit_flag(self):
        """0 = kg-mm-ms-K, 1 = SI, 2 = tonne-mm-s-K. 1e-4 in a ms system is
        the same floor as 1e-7 in a s system — one number written twice."""
        for unit, expected in ((0, 1e-4), (1, 1e-7), (2, 1e-7)):
            with self.subTest(unit=unit):
                _r, starter, _e = _convert(_deck(_particle(unit=unit)))
                c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
                self.assertEqual(_col_f(c[-1], 21, 40), expected)

    def test_an_unknown_unit_leaves_dtmin_blank_and_says_so(self):
        r, starter, _e = _convert(_deck(_particle(unit=3)))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_f(c[-1], 21, 40), 0.0)
        self.assertTrue(_warns(r, "UNIT=3 is outside the 0/1/2 table"))

    def test_the_mesher_stub_is_reported(self):
        """hm_read_monvol_type11.F:299 hard-wires KMESH=14, init_monvol.F
        dispatches that to HYPERMESH_TETRA, and fvmbags_stub.F prints
        "FVMBAGS require a mesher" and STOPs. The card is correct and a
        commercial build meshes it; on this one the run dies after the echo."""
        r, _s, _e = _convert(_deck(_particle()))
        self.assertTrue(_warns(r, "FVMBAGS require a mesher"))
        self.assertTrue(_warns(r, "--airbag-particle-uniform"))

    def test_the_uniform_flag_emits_a_runnable_airbag1(self):
        r, starter, _e = _convert(_deck(_particle()),
                                  airbag_particle_uniform=True)
        self.assertIn("/MONVOL/AIRBAG1/77", starter)
        self.assertNotIn("/MONVOL/FVMBAG2", starter)
        self.assertFalse(_warns(r, "FVMBAGS require a mesher"))


# ═══════════════════════════════════════════════════════════════════════════
class TestParticleSurfaces(unittest.TestCase):
    """SD1 \\ SD2, the internal surface and the inflator nozzles."""

    def _grshel_of(self, starter, surf_id):
        gid = _col_i(_cards(_block(starter, f"/SURF/GRSHEL/{surf_id}"))[0],
                     1, 10)
        return _cards(_block(starter, f"/GRSHEL/SHEL/{gid}"))[0].split()

    def test_the_external_surface_is_sd1_minus_sd2(self):
        """An internal part left in the external surface is a T-connection on
        every one of its edges (WARNING 1882) and the orientation pass gives
        up on the WHOLE bag."""
        _r, starter, _e = _convert(_deck(_particle(sd2=2, stype2=0)))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        ext, inn = _col_i(c[0], 1, 10), _col_i(c[0], 11, 20)
        self.assertEqual(self._grshel_of(starter, ext),
                         ["1", "2", "3", "5", "6"])
        self.assertEqual(self._grshel_of(starter, inn), ["4"])

    def test_no_sd2_leaves_the_internal_surface_at_zero(self):
        _r, starter, _e = _convert(_deck(_particle(sd2=0)))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_i(c[0], 11, 20), 0)
        self.assertEqual(self._grshel_of(starter, _col_i(c[0], 1, 10)),
                         ["1", "2", "3", "4", "5", "6"])

    def test_a_nozzle_is_a_shell_element_only_when_vdi_is_negative(self):
        """VDi -1/-2 make NIDi a SHELL ELEMENT id, and those elements ARE the
        inflator surface. A positive VDi is a *DEFINE_VECTOR and NIDi is then
        a node, which has no surface to be — Radioss says so itself
        (dyna2rad message 200035)."""
        _r, starter, _e = _convert(_deck(_particle()))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(self._grshel_of(starter, _col_i(c[3], 21, 30)), ["4"])

        r2, s2, _e2 = _convert(_deck(_particle(
            orif=((4, 25.0, 7.0, 30.0, 1, 0, 0, 0),))))
        c2 = _cards(_block(s2, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_i(c2[3], 21, 30), 0, "no nozzle surface")
        self.assertTrue(_warns(r2, "VDi that is not -1/-2/-3/-4"))

    def test_mixed_quad_and_tria_nozzles_both_survive(self):
        """dyna2rad loses the quads: sh4n/sh3n are declared outside its loop
        and never reset, and its SH3N write to surf_IDinj row 0 overwrites the
        SHELL one."""
        mesh = _mesh()
        # Turn element 6 into a triangle by collapsing its last corner.
        mesh = mesh.replace(f"{6:>8d}{1:>8d}{4:>8d}{1:>8d}{5:>8d}{8:>8d}",
                            f"{6:>8d}{1:>8d}{4:>8d}{1:>8d}{5:>8d}{5:>8d}")
        _r, starter, _e = _convert(_deck(_particle(norif=2, orif=(
            (4, 25.0, -1.0, 30.0, 1, 0, 0, 0),
            (6, 25.0, -1.0, 30.0, 1, 0, 0, 0))), mesh=mesh))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        surf = _col_i(c[3], 21, 30)
        subs = _cards(_block(starter, f"/SURF/SURF/{surf}"))[0].split()
        self.assertEqual(len(subs), 2, "a /SURF/SURF over shells AND trias")

    def test_imom_and_the_nozzle_area_are_named_and_dropped(self):
        r, _s, _e = _convert(_deck(_particle(
            orif=((4, 25.0, -1.0, 30.0, 1, 1, 0, 0),))))
        self.assertTrue(_warns(r, "set IMOM"))
        self.assertTrue(_warns(r, "nozzle AREA column ANi"))


# ═══════════════════════════════════════════════════════════════════════════
class TestParticleGasAndVents(unittest.TestCase):

    def test_the_air_card_becomes_the_initial_mole_gas(self):
        _r, starter, _e = _convert(_deck(_particle(iair=1)))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[0])
        self.assertEqual(_col_f(mix[0], 1, 20), 2.896e-05, "XMAIR")
        self.assertEqual(_col_f(mix[1], 1, 20), 26789.065, "AAIR")

    def test_iair_zero_falls_back_to_the_builtin_air_and_says_so(self):
        """LS-DYNA's "no initial air" has no Radioss expression: mat_ID is
        required (ERROR 699) and the starter derives the initial mass from
        it."""
        r, starter, _e = _convert(_deck(_particle(iair=0)))
        predef = _cards(_block(starter, "/MAT/GAS/PREDEF/"))
        self.assertEqual(predef[0][:8], "AIR     ")
        self.assertTrue(_warns(r, "IAIR=0 says the bag holds NO initial air"))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_f(c[1], 41, 60), 0.101325, "PATM -> Pext")

    def test_every_gas_gets_an_injector_row(self):
        """Unlike HYBRID there is no INITM gate — every species is injected."""
        _r, starter, _e = _convert(_deck(_particle()))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[0], 1, 10), 2)
        self.assertEqual(_col_i(inj[0], 11, 20), 1, "Iflow")
        self.assertEqual(len(inj), 3)

    def test_the_vent_surface_is_named_and_c23_is_a_scale_factor(self):
        _r, starter, _e = _convert(_deck(_particle()))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        v = c[5:9]
        self.assertNotEqual(_col_i(v[0], 1, 10), 0, "surf_IDv")
        self.assertEqual(_col_f(v[0], 21, 40), 0.7, "C23 -> Avent, a factor")
        self.assertEqual(v[0][80:100].strip(), "VENT1")

    def test_ppop_becomes_dpdef_with_tstart_out_of_reach(self):
        """dyna2rad never reads PPOP, so a vent that should stay shut until
        the bag reaches that pressure opens at t=0 there."""
        _r, starter, _e = _convert(_deck(_particle()))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_f(c[6], 41, 60), 0.0138, "dPdef = PPOP")
        self.assertEqual(_col_f(c[6], 1, 20), 1.0e30, "Tstart")

    def test_lcpc23_is_referenced_unshifted_and_the_ambiguity_is_named(self):
        """LS-DYNA does NOT document LCPC23's abscissa as absolute (unlike
        *AIRBAG_HYBRID's LCA23/LCAP23, which it does), so shifting it would be
        as damaging as not shifting one that needed it."""
        r, starter, _e = _convert(_deck(_particle(
            vents=((2, 0, 0.7, 93, 92, 0, 0.0),))))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_i(c[7], 1, 10), 93, "fct_IDt = LCTC23")
        self.assertEqual(_col_i(c[7], 11, 20), 92, "fct_IDP = LCPC23, raw")
        self.assertTrue(_warns(r, "does not say whether that pressure"))

    def test_a_vent_part_outside_the_bag_is_left_out(self):
        """A vent surface has to be a patch OF the bag; Radioss states the
        rule outright for the communicating case, ERROR 902."""
        mesh = _mesh() + """\
*NODE
      21             0.0             0.0            50.0
      22             1.0             0.0            50.0
      23             1.0             1.0            50.0
      24             0.0             1.0            50.0
*ELEMENT_SHELL
      21       3      21      22      23      24
"""
        deck = ("*KEYWORD\n" + mesh + _PARTS + """\
*PART
outside
         3         1         1
""" + _CURVES + _particle(vents=((3, 0, 0.7, 0, 0, 0, 0.0),)) + _TERM)
        r, starter, _e = _convert(deck)
        self.assertTrue(_warns(r, "NOT part of the monitored volume's own"))
        c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
        self.assertEqual(_col_i(c[5], 1, 10), 0, "no named vent surface")
        self.assertEqual(_col_f(c[5], 21, 40), 0.0, "sealed, not scaled")


# ═══════════════════════════════════════════════════════════════════════════
class TestParticleCardWalk(unittest.TestCase):
    """NVENT / NGAS / NORIF, and the block that cannot be walked (#119)."""

    def test_stype3_zero_is_a_PART_and_non_zero_is_a_PART_SET(self):
        """The batch's biggest inversion trap: SD1/SD2/SID3 use 0 = a PART,
        non-zero = a PART SET — the OPPOSITE of the SIDTYP on card 1 of the
        other five models.

        Pinned with a deck where id 2 is BOTH a *PART (the one-element patch)
        and a *SET_PART (the five-element remainder), so the
        "names *SET_PART N ... but *PART N exists" fallback cannot mask the
        inversion and each flag has a DIFFERENT element list to produce.
        Mutating ``stype3 != 0`` to ``== 0`` passed the whole suite before."""
        parts = _PARTS + """\
*SET_PART_LIST
         2       0.0       0.0       0.0       0.0MECH
         1
"""
        for stype3, want in ((0, ["4"]), (1, ["1", "2", "3", "5", "6"])):
            with self.subTest(stype3=stype3):
                deck = ("*KEYWORD\n" + _mesh() + parts + _CURVES
                        + _particle(vents=((2, stype3, 0.7, 0, 0, 0, 0.0),))
                        + _TERM)
                _r, starter, _e = _convert(deck)
                c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
                surf = _col_i(c[5], 1, 10)
                gid = _col_i(_cards(_block(starter,
                                           f"/SURF/GRSHEL/{surf}"))[0], 1, 10)
                eids = _cards(_block(starter,
                                     f"/GRSHEL/SHEL/{gid}"))[0].split()
                self.assertEqual(eids, want)

    def test_stype1_zero_is_a_PART_too(self):
        """SD1 takes the same convention, and the fixture only ever pinned
        STYPE1 = 1."""
        parts = _PARTS + """\
*SET_PART_LIST
         2       0.0       0.0       0.0       0.0MECH
         1
"""
        for stype1, want in ((0, ["4"]), (1, ["1", "2", "3", "5", "6"])):
            with self.subTest(stype1=stype1):
                deck = ("*KEYWORD\n" + _mesh() + parts + _CURVES
                        + _particle(sd1=2, stype1=stype1, norif=0, orif=(),
                                    vents=())
                        + _TERM)
                _r, starter, _e = _convert(deck)
                c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
                surf = _col_i(c[0], 1, 10)
                gid = _col_i(_cards(_block(starter,
                                           f"/SURF/GRSHEL/{surf}"))[0], 1, 10)
                eids = _cards(_block(starter,
                                     f"/GRSHEL/SHEL/{gid}"))[0].split()
                self.assertEqual(eids, want)

    def test_the_counts_position_every_card_below_them(self):
        for nvent in (0, 1, 3):
            with self.subTest(nvent=nvent):
                vents = tuple((2, 0, 0.7, 0, 0, 0, 0.0138)
                              for _ in range(nvent))
                _r, starter, _e = _convert(_deck(_particle(vents=vents)))
                c = _cards(_block(starter, "/MONVOL/FVMBAG2/"))
                self.assertEqual(_col_i(c[4], 1, 10), nvent, "Nvent")
                # the gas cards below still read correctly
                mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[1])
                self.assertEqual(_col_f(mix[0], 1, 20), 2.8e-05)

    def test_npdata_rows_are_counted_and_skipped(self):
        """dyna2rad's own reader has the NPDATA block commented out
        (airbag_Particle.cfg:1068-1086), so those rows are consumed as VENT
        cards there and everything below mis-parses."""
        r, starter, _e = _convert(_deck(_particle(npdata=2)))
        self.assertTrue(_warns(r, "NPDATA=2"))
        mix = _cards(_blocks(starter, "/MAT/GAS/MOLE/")[1])
        self.assertEqual(_col_f(mix[0], 1, 20), 2.8e-05, "gas 1 XMi")

    def test_stype2_two_abandons_the_walk_rather_than_guessing(self):
        """The SIDUP block repeats once per PART of the SD2 set — a count that
        only exists after the *SET_PART is resolved, i.e. after parsing.

        The abandonment must cost the cards BELOW card 1, not card 1 itself:
        card 1 is ABOVE the block that cannot be walked, so its index is
        already known and is handed back. Recomputing it as
        ``_title_offset(block)`` missed the _MPP and _TIME prelude cards and
        read SD1 off the SX/SY/SZ line — SD1 came back 9, "*SET_PART 9 ...
        defines neither as a part set nor as a part", and the whole /MONVOL
        was dropped."""
        for opts in ("", "_MPP", "_TIME", "_MPP_TIME", "_MPP_SEGMENT_TIME"):
            with self.subTest(opts=opts):
                # SD2 = PART 2 (the patch), so the bag surface is SD1 minus
                # the patch and survives — the point here is card 1, not the
                # surface.
                r, starter, _e = _convert(
                    _deck(_particle(sd2=2, stype2=2, opts=opts)))
                self.assertTrue(_warns(r, "STYPE2=2"))
                self.assertEqual(r.skipped_keywords, [])
                self.assertIn("/SHELL/1", starter, "the mesh survives")
                # SD1 = 7 was still read, so the bag keeps its surface
                self.assertIn("/MONVOL/", starter)
                self.assertFalse(_warns(r, "defines neither as a part set"),
                                 r.warnings)

    def test_the_mpp_card_comes_before_the_id_card(self):
        """Vol I R17 p.3-94 Card Summary lists "Card MPP" before "Card ID", so
        on *AIRBAG_PARTICLE_MPP_ID the SX/SY/SZ line is raw[0] and ABID +
        HEADING is raw[1]. Only the card COUNT is order-independent; reading
        the ABID off the MPP card gave the bag id 2 and the title "3"."""
        _r, starter, _e = _convert(_deck(_particle(opts="_MPP", ab_id=77)))
        blk = _block(starter, "/MONVOL/FVMBAG2/77")
        self.assertTrue(blk, starter)
        self.assertEqual(blk[1], "CPM driver bag")

    def test_the_mpp_id_is_the_one_an_interaction_can_name(self):
        """A wrong ABID also makes any *AIRBAG_INTERACTION naming it report
        "not defined by any *AIRBAG_* card"."""
        for opts in ("", "_MPP", "_MPP_TIME"):
            with self.subTest(opts=opts):
                _r, starter, _e = _convert(
                    _deck(_particle(opts=opts, ab_id=77)))
                self.assertIn("/MONVOL/FVMBAG2/77", starter)

    def test_segsid_is_named_by_value_rather_than_silently_dropped(self):
        """"SEGSID  ID for a segment set. The segments define the volume and
        should belong to the parts from SID1" (Vol I R17 p.3-99) — so it
        NARROWS the monitored volume, and dropping it makes the bag measure
        the whole of SD1 \\ SD2 instead."""
        r, starter, _e = _convert(
            _deck(_particle(opts="_SEGMENT", segsid=11)))
        self.assertEqual(r.skipped_keywords, [])
        hits = _warns(r, "SEGSID=11")
        self.assertTrue(hits, r.warnings)
        self.assertIn("NARROWS", hits[0])
        # and the card below it still parses
        self.assertEqual(_col_f(_cards(_blocks(starter, "/MAT/GAS/MOLE/")[1])
                                [0], 1, 20), 2.8e-05)

    def test_jnode_is_named_by_value(self):
        """Remark 18: F_thrust = mdot*(v_sound - v_exit) + Avent*(P_bag -
        P_ambient) and F_JNODE = -F_thrust. A Radioss vent applies no
        reaction force anywhere."""
        r, starter, _e = _convert(_deck(_particle(opts="_JET", jnode=5)))
        self.assertEqual(r.skipped_keywords, [])
        hits = _warns(r, "JNODE=5")
        self.assertTrue(hits, r.warnings)
        self.assertIn("thrust", hits[0].lower())
        self.assertEqual(_col_f(_cards(_blocks(starter, "/MAT/GAS/MOLE/")[1])
                                [0], 1, 20), 2.8e-05)

    def test_the_card_seven_nozzle_frame_nodes_are_named(self):
        """"Three nodes defining a moving coordinate system for the direction
        of flow through the gas inlet nozzles" (Vol I R17 p.3-104). They were
        read into the Airbag and then used by nothing at all."""
        r, _s, _e = _convert(_deck(_particle(nids=(11, 12, 13))))
        hits = _warns(r, "NID1=11")
        self.assertTrue(hits, r.warnings)
        self.assertIn("NID3=13", hits[0])

    def test_inflation_is_named_because_it_adds_mass_lsdyna_does_not_lose(
            self):
        """Remark 17: INFLATION holds the initial pressure by ADDING MASS over
        the NPRLX steps. It adds no card, so the walk is right either way and
        only the physics is short — the exact silent case."""
        r, _s, _e = _convert(_deck(_particle(opts="_INFLATION")))
        self.assertEqual(r.skipped_keywords, [])
        self.assertTrue(_warns(r, "_INFLATION adds no card"), r.warnings)

    def test_no_air_card_when_iair_is_zero_keeps_the_gas_cards_aligned(self):
        _r, starter, _e = _convert(_deck(_particle(iair=0)))
        blocks = _blocks(starter, "/MAT/GAS/MOLE/")
        self.assertEqual(_col_f(_cards(blocks[0])[0], 1, 20), 2.8e-05)

    def test_molefraction_consumes_its_lcmass_card(self):
        r, starter, _e = _convert(_deck(_particle(opts="_MOLEFRACTION")))
        self.assertTrue(_warns(r, "_MOLEFRACTION"))
        self.assertEqual(r.skipped_keywords, [])

    def test_the_cpm_only_fields_are_reported_once(self):
        r, _s, _e = _convert(_deck(_particle(fric=0.3)))
        hits = _warns(r, "CORPUSCULAR PARTICLE METHOD is replaced")
        self.assertEqual(len(hits), 1)
        self.assertIn("FRIC=0.3", hits[0])
        self.assertIn("TEND=0.06", hits[0])


# ═══════════════════════════════════════════════════════════════════════════
def _two_bag_deck(area=0.0, sf=0.85, pid=3, lcid=0, iflow=0,
                  excp=0, models=("hybrid", "hybrid")):
    """Two boxes that SHARE their partition part (3), joined by an
    *AIRBAG_INTERACTION. The partition elements belong to both bags' part
    sets, which is what Radioss requires of a communicating surface —
    ERROR 902 otherwise.

    ``area`` defaults to 0 because that is what makes PID the source of the
    orifice area: "EQ.0.0: AREA is taken as the surface area of the part ID
    defined below" (Vol I R17 p.3-91). A non-zero AREA is the orifice area
    and the partition is then not used to size it."""
    mesh = (_mesh(pid_main=1, pid_patch=3)
            + _mesh(nid0=100, eid0=100, pid_main=2, pid_patch=3, x0=15.0))
    parts = """\
*PART
bag A
         1         1         1
*PART
bag B
         2         1         1
*PART
partition
         3         1         1
*SECTION_SHELL
         1         2       1.0         2         1         0         0         1
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*SET_PART_LIST
         7       0.0       0.0       0.0       0.0MECH
         1         3
*SET_PART_LIST
         8       0.0       0.0       0.0       0.0MECH
         2         3
"""
    bags = ""
    for ab_id, sid, m in ((42, 7, models[0]), (43, 8, models[1])):
        if m == "hybrid":
            bags += _hybrid(sid=sid, ab_id=ab_id)
        elif m == "pres":
            bags += ("*AIRBAG_SIMPLE_PRESSURE_VOLUME_ID\n"
                     + f"{ab_id:>10d}pressure bag\n"
                     + _card(sid, 1, 0, 1.0, 1.0, 0.0, 0.0, 0.0)
                     + _card(0.02, 1.0, 0, 0))
    inter = ("*AIRBAG_INTERACTION\n"
             + _card(42, 43, area, sf, pid, lcid, iflow, excp))
    return ("*KEYWORD\n" + mesh + parts + _CURVES + bags + inter
            + _ABSTAT + _TERM)


def _three_bag_deck():
    """Three boxes in a CHAIN: 42<->43 through part 3, 43<->44 through part 6.

    Each partition part belongs to BOTH of the bags it separates, which is
    what ERROR 902 requires, and bag 43 is therefore named by two separate
    *AIRBAG_INTERACTION cards."""
    mesh = (_mesh(pid_main=1, pid_patch=3)
            + _mesh(nid0=100, eid0=100, pid_main=2, pid_patch=3, x0=15.0)
            + _mesh(nid0=200, eid0=200, pid_main=4, pid_patch=6, x0=25.0)
            + _mesh(nid0=300, eid0=300, pid_main=5, pid_patch=6, x0=35.0))
    parts = "".join(f"*PART\nbag {p}\n{_card(p, 1, 1)}" for p in
                    (1, 2, 3, 4, 5, 6)) + """\
*SECTION_SHELL
         1         2       1.0         2         1         0         0         1
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.85E-9  210000.0       0.3
*SET_PART_LIST
         7       0.0       0.0       0.0       0.0MECH
         1         3
*SET_PART_LIST
         8       0.0       0.0       0.0       0.0MECH
         2         3         6
*SET_PART_LIST
         9       0.0       0.0       0.0       0.0MECH
         5         6
"""
    bags = "".join(_hybrid(sid=sid, ab_id=ab)
                   for ab, sid in ((42, 7), (43, 8), (44, 9)))
    inter = ("*AIRBAG_INTERACTION\n" + _card(42, 43, 0.0, 0.85, 3, 0, 0, 0)
             + "*AIRBAG_INTERACTION\n" + _card(43, 44, 0.0, 0.85, 6, 0, 0, 0))
    return ("*KEYWORD\n" + mesh + parts + _CURVES + bags + inter
            + _ABSTAT + _TERM)


class TestAirbagInteraction(unittest.TestCase):
    """*AIRBAG_INTERACTION -> two /MONVOL/COMMU1 with reciprocal Nbag rows."""

    def test_both_bags_become_commu1_with_reciprocal_rows(self):
        """Radioss's rows are NOT reciprocal by themselves — each volume
        carries its own entry naming the other — and the engine only pushes
        gas downhill (airbagb1.F guards on P > PVOIS), so a two-way IFLOW
        needs both rows."""
        r, starter, _e = _convert(_two_bag_deck())
        blocks = _blocks(starter, "/MONVOL/COMMU1/")
        self.assertEqual([b[0] for b in blocks],
                         ["/MONVOL/COMMU1/42", "/MONVOL/COMMU1/43"])
        self.assertNotIn("/MONVOL/AIRBAG1/", starter)
        for blk, partner in zip(blocks, (43, 42)):
            c = _cards(blk)
            self.assertEqual(_col_i(c[-3], 1, 10), 1, "Nbag")
            self.assertEqual(_col_i(c[-2], 1, 10), partner, "bag_ID")
            self.assertNotEqual(_col_i(c[-2], 11, 20), 0, "surf_IDc")
            self.assertEqual(_col_f(c[-2], 41, 60), 0.85, "Acom = SF")
        self.assertTrue(_warns(r, "TWO-WAY"))

    def test_the_partition_surface_holds_the_shared_elements(self):
        """surf_IDc must be a subset of THIS bag's surf_IDex — ERROR 902,
        "COMMUNICATING SURFACE ID IS NOT INCLUDED INTO AIRBAG SURFACE ID" —
        so each bag builds its own /SURF over the same parts."""
        _r, starter, _e = _convert(_two_bag_deck())
        blocks = _blocks(starter, "/MONVOL/COMMU1/")
        ids = [_col_i(_cards(b)[-2], 11, 20) for b in blocks]
        self.assertNotEqual(ids[0], ids[1], "one /SURF per volume")
        for sid in ids:
            gid = _col_i(_cards(_block(starter, f"/SURF/GRSHEL/{sid}"))[0],
                         1, 10)
            eids = _cards(_block(starter, f"/GRSHEL/SHEL/{gid}"))[0].split()
            self.assertEqual(eids, ["4", "104"], "both partition elements")

    def test_the_partition_is_not_also_emitted_as_a_vent_hole(self):
        """A communicating surface moves gas to the PARTNER, not outside; a
        vent-hole block over the same elements would leak the bag to
        atmosphere as well."""
        _r, starter, _e = _convert(_two_bag_deck())
        for blk in _blocks(starter, "/MONVOL/COMMU1/"):
            c = _cards(blk)
            self.assertEqual(_col_i(c[5], 1, 10), 2,
                             "Nvent: the orifice and the fabric porosity only")

    def test_a_one_way_iflow_promotes_only_the_sending_bag(self):
        """The engine pushes gas downhill one row at a time, so a one-way
        IFLOW is ONE row — and the receiving bag keeps /MONVOL/AIRBAG1, the
        same gas model with no communicating block of its own. A COMMU1 with
        ``Nbag = 0`` is what ``monvol_commu1.cfg:255-259`` refuses
        ("CHECK(COMMON) { NBAG > 0; }"), the very thing this batch declines to
        copy from dyna2rad, and its AC/UC channels would read zero anyway."""
        import re
        for iflow, sender, receiver in ((-1, 42, 43), (1, 43, 42)):
            with self.subTest(iflow=iflow):
                r, starter, _e = _convert(_two_bag_deck(iflow=iflow))
                commu = _blocks(starter, "/MONVOL/COMMU1/")
                self.assertEqual([b[0] for b in commu],
                                 [f"/MONVOL/COMMU1/{sender}"])
                self.assertEqual(_col_i(_cards(commu[0])[-3], 1, 10), 1)
                self.assertEqual(_col_i(_cards(commu[0])[-2], 1, 10), receiver)
                self.assertIn(f"/MONVOL/AIRBAG1/{receiver}", starter)
                self.assertTrue(_warns(r, "ONE-WAY"))
                # and the receiving bag keeps no orphan partition /SURF
                surfs = {int(m.group(1)) for ln in starter.splitlines()
                         if (m := re.match(r"^/SURF/\w+/(\d+)$", ln))}
                named = set()
                for blk in (_blocks(starter, "/MONVOL/COMMU1/")
                            + _blocks(starter, "/MONVOL/AIRBAG1/")):
                    c = _cards(blk)
                    named.add(_col_i(c[0], 1, 10))
                    for k in range(_col_i(c[5], 1, 10)):
                        named.add(_col_i(c[6 + 4 * k], 1, 10))
                    if blk[0].startswith("/MONVOL/COMMU1/"):
                        named.add(_col_i(c[-2], 11, 20))
                # the two /SURF a /SURF/SURF wraps are named by it, not by the
                # /MONVOL, so allow anything a /SURF/SURF lists
                for blk in _blocks(starter, "/SURF/SURF/"):
                    named.update(int(t) for ln in _cards(blk)
                                 for t in ln.split())
                self.assertEqual(surfs - named - {0}, set(),
                                 "every emitted /SURF is referenced")

    def test_a_scalar_area_is_absolute_when_no_partition_resolves(self):
        r, starter, _e = _convert(_two_bag_deck(pid=0, area=33.3, sf=2.0))
        for blk in _blocks(starter, "/MONVOL/COMMU1/"):
            c = _cards(blk)
            self.assertEqual(_col_i(c[-2], 11, 20), 0, "surf_IDc")
            self.assertAlmostEqual(_col_f(c[-2], 41, 60), 33.3 * 2.0)
        self.assertFalse(_warns(r, "NO GAS FLOWS"))

    def test_a_negative_sf_becomes_the_time_function(self):
        _r, starter, _e = _convert(_two_bag_deck(sf=-93.0))
        for blk in _blocks(starter, "/MONVOL/COMMU1/"):
            c = _cards(blk)
            self.assertEqual(_col_i(c[-1], 1, 10), 93, "fct_IDCt")
            self.assertEqual(_col_f(c[-2], 41, 60), 1.0, "Acom, SF -> 1")

    def test_a_stated_area_overrides_the_partition_it_names(self):
        """"AREA  Orifice area between connected bags. ... EQ.0.0: AREA is
        taken as the surface area of the part ID defined below" (Vol I R17
        p.3-91) — so PID supplies the area ONLY when AREA is 0. Scaling the
        partition by SF alone discarded the stated number: on a 100 mm2
        partition, AREA 33.3 with SF 0.85 vented through 85 rather than
        28.3, byte-identical to a deck stating no AREA at all."""
        import re
        r, starter, _e = _convert(_two_bag_deck(area=33.3, sf=0.85, pid=3))
        for blk in _blocks(starter, "/MONVOL/COMMU1/"):
            c = _cards(blk)
            self.assertEqual(_col_i(c[-2], 11, 20), 0, "surf_IDc")
            self.assertAlmostEqual(_col_f(c[-2], 41, 60), 33.3 * 0.85)
        self.assertTrue(_warns(r, "the stated AREA governs"))
        # and the partition /SURF it no longer needs is not left behind
        surfs = {int(m.group(1)) for ln in starter.splitlines()
                 if (m := re.match(r"^/SURF/\w+/(\d+)$", ln))}
        named = set()
        for blk in _blocks(starter, "/MONVOL/COMMU1/"):
            c = _cards(blk)
            named.add(_col_i(c[0], 1, 10))
            for k in range(_col_i(c[5], 1, 10)):
                named.add(_col_i(c[6 + 4 * k], 1, 10))
            named.add(_col_i(c[-2], 11, 20))
        for blk in _blocks(starter, "/SURF/SURF/"):
            named.update(int(t) for ln in _cards(blk) for t in ln.split())
        self.assertEqual(surfs - named - {0}, set(),
                         "every emitted /SURF is referenced")

    def test_a_chain_of_interactions_gives_the_middle_bag_two_rows(self):
        """A bag can be named by MORE THAN ONE *AIRBAG_INTERACTION — which is
        the primary reason the keyword exists. With only AIRBAG1 promotable,
        the middle bag of a chain was already a COMMU1 when the second card
        was read and the second card was DROPPED, with a warning that
        contradicted itself. monvol_commu1.cfg allows NBAG <= 20."""
        def _commu(blk):
            """(Nbag, [partner bag_ID, ...]) from the block's own Nbag card."""
            i = next(k for k, ln in enumerate(blk) if ln.strip() == "#  Nbag"
                     or ln.strip().endswith("Nbag"))
            rows = [ln for ln in blk[i + 2:]
                    if ln and not ln.startswith(("#", "/"))]
            return (_col_i(blk[i + 1], 1, 10),
                    [_col_i(rows[2 * k], 1, 10)
                     for k in range(_col_i(blk[i + 1], 1, 10))])

        r, starter, _e = _convert(_three_bag_deck())
        blocks = _blocks(starter, "/MONVOL/COMMU1/")
        self.assertEqual([b[0] for b in blocks],
                         ["/MONVOL/COMMU1/42", "/MONVOL/COMMU1/43",
                          "/MONVOL/COMMU1/44"])
        got = {b[0].rsplit("/", 1)[1]: _commu(b) for b in blocks}
        self.assertEqual(got["42"], (1, [43]))
        self.assertEqual(got["44"], (1, [43]))
        # bag 43 is the middle of the chain 42<->43, 43<->44
        self.assertEqual(got["43"][0], 2, "Nbag on the middle bag")
        self.assertEqual(set(got["43"][1]), {42, 44}, "both partners")
        self.assertFalse(_warns(r, "gas exchange needs BOTH bags"),
                         r.warnings)

    def test_a_negative_area_curve_cannot_map_and_says_why(self):
        """airbagb1.F evaluates a communicating vent's pressure function at
        (P - PVOIS), the PARTNER difference — not at (P - Pext) and not at P —
        so an absolute-pressure curve has no abscissa to be shifted onto."""
        r, _s, _e = _convert(_two_bag_deck(area=-92.0, pid=3))
        self.assertTrue(_warns(r, "PARTNER pressure difference"))

    def test_lcid_is_dropped_because_commu1_has_no_mass_flow_slot(self):
        r, _s, _e = _convert(_two_bag_deck(lcid=93))
        hits = _warns(r, "LCID=93")
        self.assertTrue(hits)
        self.assertIn("Wang-Nefske", hits[0])

    def test_excp_is_named_and_dropped(self):
        """EXCP is the eighth column, which the reader cfg omits entirely —
        airbag_interaction.cfg writes only seven fields."""
        r, _s, _e = _convert(_two_bag_deck(excp=1))
        self.assertTrue(_warns(r, "EXCP=1"))

    def test_an_unknown_partner_is_dropped_naming_both_ids(self):
        deck = _two_bag_deck().replace(
            _card(42, 43, 0.0, 0.85, 3, 0, 0, 0),
            _card(42, 99, 0.0, 0.85, 3, 0, 0, 0))
        r, starter, _e = _convert(deck)
        self.assertNotIn("/MONVOL/COMMU1/", starter)
        hits = _warns(r, "not defined by any")
        self.assertTrue(hits)
        self.assertIn("[99]", hits[0])

    def test_a_non_promotable_partner_is_dropped_naming_both(self):
        """Only an AIRBAG1 bag can be promoted: it shares COMMU1's whole gas
        model (monvol0.F sends ITYP 7 and 9 to the same AIRBAGA1/AIRBAGB1),
        while a PRES volume has no gas to exchange."""
        r, starter, _e = _convert(
            _two_bag_deck(models=("hybrid", "pres")))
        self.assertNotIn("/MONVOL/COMMU1/", starter)
        hits = _warns(r, "gas exchange needs BOTH bags")
        self.assertTrue(hits)
        self.assertIn("/MONVOL/PRES", hits[0])
        self.assertIn("airbags 42 and 43", hits[0])


# ═══════════════════════════════════════════════════════════════════════════
class TestAbstatChannels(unittest.TestCase):
    """/TH/MONV per model family (the #122/#123 lesson: an ACCEPTED channel
    can still be structurally zero)."""

    def test_commu1_carries_the_communication_channels(self):
        """AC and UC are the airbagb1.F ``DO I=1,NAV`` loop's own sums, which
        only a COMMU1 has — and a COMMU1 only exists here because an
        *AIRBAG_INTERACTION filled its Nbag block, so they are never
        structurally zero on the cards this converter writes."""
        _r, starter, _e = _convert(_two_bag_deck())
        blk = _block(starter, "/TH/MONV/")
        self.assertEqual(
            _th_monv_vars(blk),
            ["MASS", "VOL", "P", "A", "T", "AO", "UO", "AC", "UC",
             "CP", "CV", "GAMA", "MASS-IN", "ENTHA-IN", "ENER-INT", "WORK"])

    def test_fvmbag2_gets_dtbag_nfv_and_upcrit_back(self):
        """The #123 handoff: DTBAG and NFV were dropped from AIRBAG1 as
        MEASURED flat zeros and named as belonging "to the batch that adds
        /MONVOL/FVMBAG1". fvbag1.F:1832 sets FSAV(13)=DTX and :1801
        FSAV(14)=NPOLH; FSAV(19)=PDISP is the switch criterion. AC/UC are
        excluded (no communication loop) and so is WORK, never assigned on the
        FV path."""
        _r, starter, _e = _convert(_deck(_particle(), _ABSTAT))
        blk = _block(starter, "/TH/MONV/")
        got = _th_monv_vars(blk)
        self.assertEqual(
            got,
            ["MASS", "VOL", "P", "A", "T", "AO", "UO", "CP", "CV", "GAMA",
             "DTBAG", "NFV", "MASS-IN", "ENTHA-IN", "ENER-INT", "UPCRIT"])
        self.assertNotIn("AC", got)
        self.assertNotIn("WORK", got)

    def test_a_hybrid_bag_uses_the_airbag1_channel_set(self):
        """dyna2rad's hybrid bags get NO /TH/MONV at all, because
        p_CreateTHMonVolForDBAbstat runs at ConvertEntities():47 and
        ConvertAirbagHybrid at :53, so its SelectionRead cannot see them."""
        _r, starter, _e = _convert(_deck(_hybrid(), _ABSTAT))
        blk = _block(starter, "/TH/MONV/")
        self.assertEqual(
            _th_monv_vars(blk),
            ["MASS", "VOL", "P", "A", "T", "AO", "UO", "AC", "UC",
             "CP", "CV", "GAMA", "MASS-IN", "ENTHA-IN", "ENER-INT", "WORK"])

    def test_the_variable_names_are_written_in_varmv_order(self):
        """The starter sorts them into its own table order
        (hm_read_thgrou.F:1181-1186) and the T01 columns come back that way,
        not in card order — so writing them pre-sorted makes the card describe
        the file it produces."""
        order = ["MASS", "VOL", "P", "A", "T", "AO", "UO", "AC", "UC", "CP",
                 "CV", "GAMA", "DTBAG", "NFV", "MASS-IN", "ENTHA-IN",
                 "ENER-INT", "WORK", "UPCRIT"]
        for extra in (_hybrid(), _particle()):
            with self.subTest(kw=extra.splitlines()[0]):
                _r, starter, _e = _convert(_deck(extra, _ABSTAT))
                got = _th_monv_vars(_block(starter, "/TH/MONV/"))
                self.assertEqual(got, sorted(got, key=order.index))

    def test_a_sealed_bag_does_not_request_the_vent_channels(self):
        _r, starter, _e = _convert(_deck(
            _hybrid(c23=0.0, a23=0.0, cp23=0.0, ap23=0.0, lcap23=0,
                    pvent=0.0), _ABSTAT))
        got = _th_monv_vars(_block(starter, "/TH/MONV/"))
        self.assertNotIn("AO", got)
        self.assertNotIn("UO", got)

    def test_the_abstat_dt_reaches_the_engine_tfile(self):
        _r, _s, engine = _convert(_deck(_particle(), _ABSTAT))
        self.assertIn("/TFILE\n0.0001", engine)


# ═══════════════════════════════════════════════════════════════════════════
class TestBatch2Dispatch(unittest.TestCase):
    """#116: the suffix stacks come from ONE source, and the parser and the
    offset table must cover the SAME set."""

    def test_every_generated_spelling_is_both_readable_and_offsettable(self):
        from itertools import product
        from k2rad.handlers import (_AIRBAG_LEGACY_SUFFIXES,
                                    _AIRBAG_OPTION_STACKS)
        n = 0
        for base, stack in _AIRBAG_OPTION_STACKS.items():
            for combo in product(*stack):
                for sfx in _AIRBAG_LEGACY_SUFFIXES:
                    kw = base + "".join(combo) + sfx
                    n += 1
                    self.assertIn(kw, HANDLERS)
                    self.assertIn(kw, _OFFSET_SPECS)
        self.assertGreater(n, 100, "the product really is generated")

    def test_the_parser_and_offset_tables_cover_the_same_airbag_set(self):
        """A spelling that dispatches but has no offset spec silently keeps
        its un-offset ids under an *INCLUDE_TRANSFORM; one with a spec but no
        handler is a bag that never inflates."""
        from k2rad.handlers import _AIRBAG_MODELS, _AIRBAG_LEGACY_SUFFIXES
        from itertools import product
        from k2rad.handlers import _AIRBAG_OPTION_STACKS
        expect = set()
        for kw in _AIRBAG_MODELS:
            expect.update(kw + s for s in _AIRBAG_LEGACY_SUFFIXES)
        for base, stack in _AIRBAG_OPTION_STACKS.items():
            for combo in product(*stack):
                expect.update(base + "".join(combo) + s
                              for s in _AIRBAG_LEGACY_SUFFIXES)
        expect.update("AIRBAG_INTERACTION" + s
                      for s in _AIRBAG_LEGACY_SUFFIXES)
        self.assertEqual(expect - set(HANDLERS), set())
        self.assertEqual(expect - set(_OFFSET_SPECS), set())

    def test_the_documented_option_spellings_dispatch(self):
        for kw in ("AIRBAG_HYBRID", "AIRBAG_HYBRID_JETTING",
                   "AIRBAG_HYBRID_JETTING_CM", "AIRBAG_PARTICLE",
                   "AIRBAG_PARTICLE_MPP", "AIRBAG_PARTICLE_DECOMPOSITION",
                   "AIRBAG_PARTICLE_MOLEFRACTION", "AIRBAG_PARTICLE_SEGMENT",
                   "AIRBAG_PARTICLE_INFLATION", "AIRBAG_PARTICLE_JET",
                   "AIRBAG_PARTICLE_TIME", "AIRBAG_INTERACTION",
                   "AIRBAG_HYBRID_1", "AIRBAG_PARTICLE_2"):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
                self.assertIn(kw, _OFFSET_SPECS)

    def test_chemkin_is_a_model_of_its_own_and_is_warn_dropped(self):
        """*AIRBAG_HYBRID_CHEMKIN is NOT a *AIRBAG_HYBRID option: Vol I R17
        p.3-54 gives it card 3 'LCIDM LCIDT NGAS DATA ATMT ATMP RG', card 4
        'HCONV', card 5 'C23 A23' and per-species thermodynamic cards.

        Reading it with the HYBRID reader takes its curve ids for
        ATMOST/ATMOSP and its DATA for GC, then walks a gas block that is not
        where it thinks. Master registered it on handle_airbag_unsupported;
        so does this batch."""
        from k2rad.handlers import (_AIRBAG_UNSUPPORTED, _airbag_base_keyword,
                                    handle_airbag_unsupported)
        self.assertIn("AIRBAG_HYBRID_CHEMKIN", _AIRBAG_UNSUPPORTED)
        for sfx in ("", "_1", "_4"):
            kw = "AIRBAG_HYBRID_CHEMKIN" + sfx
            with self.subTest(kw=kw):
                self.assertIs(HANDLERS[kw], handle_airbag_unsupported)
                # NOT offsettable: an unmodelled card stack must not have its
                # cells rewritten by position.
                self.assertNotIn(kw, _OFFSET_SPECS)
                self.assertEqual(_airbag_base_keyword(kw),
                                 "AIRBAG_HYBRID_CHEMKIN")

    def test_chemkin_and_chamber_convert_to_nothing_and_say_so(self):
        """Both are warn-DROPS, not silent skips and not mis-read HYBRIDs."""
        for kw, needle in (("AIRBAG_HYBRID_CHEMKIN", "CHEMKIN"),
                           ("AIRBAG_HYBRID_CHAMBER", "AIRBAG_HYBRID_CHAMBER")):
            with self.subTest(kw=kw):
                res, starter, _eng = _convert(_deck(_hybrid(keyword=kw)))
                self.assertEqual(res.skipped_keywords, [])
                self.assertTrue(_warns(res, needle), res.warnings)
                self.assertTrue(_warns(res, "NOT converted"), res.warnings)
                self.assertNotIn("/MONVOL/", starter)

    def test_the_id_and_title_spellings_need_no_key(self):
        """parser._split_keyword moves a trailing _ID/_TITLE into
        block.options, so they resolve to the base keyword."""
        for kw in ("AIRBAG_HYBRID_ID", "AIRBAG_PARTICLE_TITLE",
                   "AIRBAG_INTERACTION_ID"):
            with self.subTest(kw=kw):
                self.assertNotIn(kw, HANDLERS)
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(_deck(_hybrid()))
        kws = [b.keyword for b in parse_k_file(path)]
        tmp.cleanup()
        self.assertIn("AIRBAG_HYBRID", kws)

    def test_an_undocumented_suffix_keeps_the_mesh_and_is_named(self):
        """A bag that vanishes into skipped_keywords is not a missing output
        card: the run terminates NORMALLY with the fabric flapping loose."""
        for kw in ("AIRBAG_HYBRID_FUTURE_OPTION", "AIRBAG_PARTICLE_XYZ",
                   "AIRBAG_SOMETHING_NEW"):
            with self.subTest(kw=kw):
                body = (f"*{kw}\n" + _card(7, 1) + _card(1.0))
                r, starter, _e = _convert(_deck(body))
                self.assertEqual(r.skipped_keywords, [])
                self.assertIn("/SHELL/1", starter)
                self.assertIn("/PART/1", starter)
                self.assertIn("/MAT/ELAST/1", starter)
                self.assertTrue(any("NOT converted" in w
                                    for w in r.warnings))


# ═══════════════════════════════════════════════════════════════════════════
class TestBatch2Offsets(unittest.TestCase):
    """*INCLUDE_TRANSFORM: the cells whose BUCKET depends on a neighbour."""

    OFF = {"n": 1000, "e": 2000, "p": 300, "m": 400, "r": 500, "f": 600,
           "s": 700}

    def _off(self, deck: str):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck)
        out = []
        for b in parse_k_file(path):
            spec = _OFFSET_SPECS.get(b.keyword)
            if spec:
                spec(b, self.OFF, lambda m: None)
                out.append((b.keyword, list(b.raw)))
        tmp.cleanup()
        return out

    def test_hybrid_cells(self):
        deck = "*KEYWORD\n" + _hybrid(
            a23=-2.0, lca23=-1, lcc23=90, lcp23=93, lcap23=92,
            lcefr=93, lcidm0=90) + "*END\n"
        _kw, raw = self._off(deck)[0]
        self.assertEqual(raw[0][:10].strip(), "542", "ABID -> IDROFF")
        self.assertEqual(_col_i(raw[1], 1, 10), 707, "SID -> IDSOFF")
        # card 4: LCC23/LCP23/LCAP23 -> IDFOFF; A23 < 0 with LCA23 == -1 is a
        # *SET_PART id, so it takes IDSOFF and keeps its sign.
        self.assertEqual(_col_i(raw[3], 11, 20), 690, "LCC23")
        self.assertEqual(_col_f(raw[3], 21, 30), -702.0, "A23 -> IDSOFF")
        self.assertEqual(_col_i(raw[3], 31, 40), -1, "LCA23 sentinel intact")
        self.assertEqual(_col_i(raw[3], 51, 60), 693, "LCP23")
        self.assertEqual(_col_i(raw[3], 71, 80), 692, "LCAP23")
        self.assertEqual(_col_i(raw[4], 31, 40), 693, "LCEFR")
        self.assertEqual(_col_i(raw[4], 41, 50), 690, "LCIDM0")
        self.assertEqual(_col_i(raw[5], 1, 10), 690, "gas 1 LCIDM")
        self.assertEqual(_col_i(raw[5], 11, 20), 691, "gas 1 LCIDT")
        self.assertEqual(_col_f(raw[5], 31, 40), 0.028, "MW untouched")

    def test_a_negative_a23_without_the_sentinel_is_a_part(self):
        deck = "*KEYWORD\n" + _hybrid(a23=-2.0, lca23=0) + "*END\n"
        _kw, raw = self._off(deck)[0]
        self.assertEqual(_col_f(raw[3], 21, 30), -302.0, "A23 -> IDPOFF")

    def test_a_negative_gas_curve_keeps_its_spline_sign(self):
        g1 = dict(_G1, lcidm=-90, lcidt=-91)
        deck = "*KEYWORD\n" + _hybrid(gases=(g1, _G2)) + "*END\n"
        _kw, raw = self._off(deck)[0]
        self.assertEqual(_col_i(raw[5], 1, 10), -690)
        self.assertEqual(_col_i(raw[5], 11, 20), -691)

    def test_jetting_nodes_and_psid_move_to_their_own_buckets(self):
        deck = "*KEYWORD\n" + _hybrid(jetting=True, nodes=(1, 5, 6)) + "*END\n"
        _kw, raw = self._off(deck)[0]
        card7 = raw[-1]
        self.assertEqual(_col_i(card7, 51, 60), 1001, "NODE1 -> IDNOFF")
        self.assertEqual(_col_i(card7, 61, 70), 1005, "NODE2")
        self.assertEqual(_col_i(card7, 71, 80), 1006, "NODE3")

    def test_particle_cells(self):
        deck = ("*KEYWORD\n" + _particle(
            sd1=7, stype1=1, sd2=5, stype2=1, iair=1, norif=2,
            vents=((11, 0, 0.7, 90, 91, 0, 0.0138),
                   (12, 1, 0.7, 0, 0, 0, 0.0)),
            orif=((4, 25.0, -1.0, 30.0, 1, 0, 0, 0),
                  (50, 25.0, 7.0, 30.0, 1, 0, 0, 0))) + "*END\n")
        _kw, raw = self._off(deck)[0]
        self.assertEqual(raw[0][:10].strip(), "577", "ABID")
        self.assertEqual(_col_i(raw[1], 1, 10), 707, "SD1, STYPE1=1 -> IDSOFF")
        self.assertEqual(_col_i(raw[1], 21, 30), 705, "SD2, STYPE2=1")
        self.assertEqual(_col_i(raw[4], 1, 10), 311, "SID3 STYPE3=0 -> IDPOFF")
        self.assertEqual(_col_i(raw[4], 31, 40), 690, "LCTC23 -> IDFOFF")
        self.assertEqual(_col_i(raw[4], 41, 50), 691, "LCPC23")
        self.assertEqual(_col_i(raw[5], 1, 10), 712, "SID3 STYPE3=1 -> IDSOFF")
        self.assertEqual(_col_i(raw[7], 1, 10), 690, "gas 1 LCMi")
        self.assertEqual(_col_i(raw[9], 1, 10), 2004,
                         "NIDi with VDi<0 is a SHELL ELEMENT -> IDEOFF")
        self.assertEqual(_col_i(raw[10], 1, 10), 1050,
                         "NIDi with VDi>0 is a NODE -> IDNOFF")

    def test_a_stype2_two_particle_is_not_offset_blind(self):
        deck = "*KEYWORD\n" + _particle(sd2=7, stype2=2) + "*END\n"
        got = self._off(deck)
        _kw, raw = got[0]
        # card 1 itself is safe to rewrite; nothing below it is touched
        self.assertEqual(_col_i(raw[4], 1, 10), 2,
                         "the vent row keeps its raw, un-offset SID3")

    def test_interaction_cells(self):
        deck = ("*KEYWORD\n*AIRBAG_INTERACTION\n"
                + _card(42, 43, -92.0, -93.0, 3, 90, 0, 0) + "*END\n")
        _kw, raw = self._off(deck)[0]
        self.assertEqual(_col_i(raw[0], 1, 10), 542, "AB1 -> IDROFF")
        self.assertEqual(_col_i(raw[0], 11, 20), 543, "AB2")
        self.assertEqual(_col_f(raw[0], 21, 30), -692.0, "AREA<0 -> IDFOFF")
        self.assertEqual(_col_f(raw[0], 31, 40), -693.0, "SF<0 -> IDFOFF")
        self.assertEqual(_col_i(raw[0], 41, 50), 303, "PID -> IDPOFF")
        self.assertEqual(_col_i(raw[0], 51, 60), 690, "LCID -> IDFOFF")


# ═══════════════════════════════════════════════════════════════════════════
class TestBatch2RegistryAudit(unittest.TestCase):
    """#120: what the new entities touch in the shared registries."""

    def test_no_duplicate_ids_across_the_whole_deck(self):
        """Every synthesized entity draws from a guarded allocator, and the
        starter checks /FUNCT against /TABLE in ONE merged scan and /PROP and
        /MAT each in their own — a collision is ERROR 79."""
        deck = _deck(_hybrid(), _particle(ab_id=78), _ABSTAT)
        _r, starter, _e = _convert(deck)
        import re
        for pat in (r"^/SURF/\w+/(\d+)$", r"^/GRSHEL/SHEL/(\d+)$",
                    r"^/PROP/\w+/(\d+)$", r"^/FUNCT/(\d+)$",
                    r"^/MONVOL/\w+/(\d+)$"):
            ids = [m.group(1) for ln in starter.splitlines()
                   if (m := re.match(pat, ln))]
            with self.subTest(pat=pat):
                self.assertEqual(len(ids), len(set(ids)), pat)
        mats = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
                if ln.startswith("/MAT/")]
        self.assertEqual(len(mats), len(set(mats)))

    def test_every_referenced_id_resolves(self):
        deck = _deck(_hybrid(a23=-2.0, lca23=0), _particle(ab_id=78, sd2=2),
                     _ABSTAT)
        _r, starter, _e = _convert(deck)
        import re
        surfs = {int(m.group(1)) for ln in starter.splitlines()
                 if (m := re.match(r"^/SURF/\w+/(\d+)$", ln))}
        mats = {int(ln.rsplit("/", 1)[1]) for ln in starter.splitlines()
                if ln.startswith("/MAT/")}
        props = {int(m.group(1)) for ln in starter.splitlines()
                 if (m := re.match(r"^/PROP/\w+/(\d+)$", ln))}
        fcts = {int(m.group(1)) for ln in starter.splitlines()
                if (m := re.match(r"^/FUNCT/(\d+)$", ln))}
        for blk in (_blocks(starter, "/MONVOL/AIRBAG1/")
                    + _blocks(starter, "/MONVOL/FVMBAG2/")):
            c = _cards(blk)
            self.assertIn(_col_i(c[0], 1, 10), surfs, "surf_IDex")
        for blk in _blocks(starter, "/PROP/INJECT1/"):
            for row in _cards(blk)[1:]:
                self.assertIn(_col_i(row, 1, 10), mats, "Mat_ID")
                fid = _col_i(row, 21, 30)
                self.assertTrue(fid in fcts or fid == 0, "fun_ID_T")
        self.assertTrue(props)

    def test_every_emitted_monvol_function_is_referenced(self):
        """The synthesized /FUNCT are the only entities this batch creates
        that nothing else names, so an unreferenced one is deck noise the
        registry would not otherwise catch."""
        import re
        deck = _deck(_hybrid(a23=0.0, lca23=92), _particle(ab_id=78), _ABSTAT)
        _r, starter, _e = _convert(deck)
        made = {}
        lines = starter.splitlines()
        for k, ln in enumerate(lines):
            if (m := re.match(r"^/FUNCT/(\d+)$", ln)) and \
                    lines[k + 1].startswith("MONVOL_"):
                made[int(m.group(1))] = lines[k + 1]
        self.assertTrue(made, "the fixture must synthesize at least one")
        named = set()
        for blk in (_blocks(starter, "/MONVOL/AIRBAG1/")
                    + _blocks(starter, "/MONVOL/FVMBAG2/")
                    + _blocks(starter, "/MONVOL/COMMU1/")
                    + _blocks(starter, "/PROP/INJECT1/")):
            for row in _cards(blk):
                named.update(int(row[c:c + 10]) for c in range(0, 90, 10)
                             if row[c:c + 10].strip().lstrip("-").isdigit())
        self.assertEqual(set(made) - named, set(),
                         f"orphan /FUNCT: {made}")

    def test_ittf_is_a_declared_field_of_the_airbag(self):
        """It is read by BOTH emitters, so a direct-construction test, a
        dataclasses.replace or an asdict round-trip must not lose it."""
        import dataclasses
        from k2rad.state import Airbag
        self.assertIn("ittf", {f.name for f in dataclasses.fields(Airbag)})
        self.assertEqual(Airbag(airbag_id=1, model="HYBRID").ittf, 0)

    def test_a_monitored_volume_still_owns_no_node(self):
        """The premise batch 1's audit rests on, re-checked for batch 2: the
        FV mesh of an FVMBAG2 is generated inside the STARTER (init_monvol.F
        appends its extra vertices to ITAB itself), so no FV node exists in
        the deck for the implicit free-node guard to find."""
        implicit = "*CONTROL_IMPLICIT_GENERAL\n         1     0.001\n"
        _r, with_bag, _e = _convert(_deck(_particle(), _hybrid(), implicit))
        _r2, without, _e2 = _convert(_deck(implicit))

        def constrained(text):
            lines = text.splitlines()
            grnods, out = {}, []
            for k, ln in enumerate(lines):
                if ln.startswith("/GRNOD/NODE/"):
                    ids, j = [], k + 2
                    while j < len(lines) and not lines[j].startswith(("/", "#")):
                        ids += [int(t) for t in lines[j].split()]
                        j += 1
                    grnods[int(ln.rsplit("/", 1)[1])] = sorted(ids)
            for k, ln in enumerate(lines):
                if ln.startswith("/BCS/"):
                    row = lines[k + 3]
                    out.append((row[:20], grnods.get(int(row[30:40] or 0), [])))
            return sorted(out)
        self.assertEqual(constrained(with_bag), constrained(without))

    def test_a_bag_and_its_vent_can_share_one_part_without_double_counting(self):
        """The vent surface is a SUBSET of the bag surface by construction —
        Radioss requires it (ERROR 902 for the communicating case) — and
        nothing is summed across the two: surf_IDex measures the VOLUME,
        surf_IDv scales an AREA."""
        _r, starter, _e = _convert(_deck(_hybrid(a23=-2.0, lca23=0)))
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        ext = _col_i(c[0], 1, 10)
        vent = _col_i(c[6], 1, 10)
        self.assertNotEqual(ext, vent, "two /SURF, one element set")
        g_ext = _col_i(_cards(_block(starter, f"/SURF/GRSHEL/{ext}"))[0], 1, 10)
        g_v = _col_i(_cards(_block(starter, f"/SURF/GRSHEL/{vent}"))[0], 1, 10)
        ext_e = set(_cards(_block(starter, f"/GRSHEL/SHEL/{g_ext}"))[0].split())
        vent_e = set(_cards(_block(starter, f"/GRSHEL/SHEL/{g_v}"))[0].split())
        self.assertTrue(vent_e <= ext_e, "the vent is a patch OF the bag")

    def test_the_monvol_id_guard_renumbers_a_collision(self):
        """/MONVOL ids share ONE Radioss namespace across every model while
        LS-DYNA's *AIRBAG_<MODEL>_ID ids are per keyword, so a HYBRID 42 and a
        PARTICLE 42 both want id 42 — ERROR 79 without the guard."""
        _r, starter, _e = _convert(_deck(_hybrid(ab_id=42),
                                         _particle(ab_id=42)))
        ids = [ln.rsplit("/", 1)[1] for ln in starter.splitlines()
               if ln.startswith("/MONVOL/")]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)


# ═══════════════════════════════════════════════════════════════════════════
class TestBatch1StaysByteIdentical(unittest.TestCase):
    """The five uniform-pressure models share the vent emitter, the injector
    emitter and the /TH/MONV table with batch 2, so all three had to stay
    strict no-ops for them."""

    def test_the_checked_in_goldens_are_unchanged(self):
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

    def test_a_batch_one_airbag_emits_the_pre_batch_two_cards(self):
        """*AIRBAG_SIMPLE_AIRBAG_MODEL: one gas, one injector row, one vent
        hole with surf_IDv = 0 — column for column what master wrote, now
        through the list-taking emitters."""
        sam = ("*AIRBAG_SIMPLE_AIRBAG_MODEL_ID\n" + f"{5:>10d}simple bag\n"
               + _card(7, 1, 0, 1.0, 1.0, 0.0, 0.0, 0.0)
               + _card(7.17e8, 1.004e9, 600.0, 90, 0.7, 100.0, 0.101325, 0.0)
               + _card(0))
        _r, starter, _e = _convert(_deck(sam, _ABSTAT))
        inj = _cards(_block(starter, "/PROP/INJECT1/"))
        self.assertEqual(_col_i(inj[0], 1, 10), 1, "N_gases")
        self.assertEqual(_col_i(inj[0], 11, 20), 1, "Iflow")
        self.assertEqual(_col_f(inj[0], 21, 40), 1.0, "Ascale_T")
        self.assertEqual(len(inj), 2)
        self.assertEqual(_col_i(inj[1], 11, 20), 90, "fun_ID_M = LCID")
        c = _cards(_block(starter, "/MONVOL/AIRBAG1/"))
        self.assertEqual(_col_f(c[0], 21, 40), 0.0, "Hconv stays 0")
        self.assertEqual(_col_i(c[5], 1, 10), 1, "Nvent")
        self.assertEqual(_col_i(c[5], 11, 20), 0, "Nporsurf")
        self.assertEqual(_col_i(c[6], 1, 10), 0, "surf_IDv, whole-bag")
        self.assertEqual(_col_f(c[6], 21, 40), 0.7 * 100.0, "Avent = mu*A")
        self.assertEqual(_col_f(c[7], 1, 20), 0.0, "Tstart stays 0")
        self.assertEqual(_col_f(c[7], 41, 60), 0.0, "dPdef stays 0")
        # /MAT/GAS/CSTA, not MOLE: CV != 0 selects the constant-Cp form
        csta = _cards(_block(starter, "/MAT/GAS/CSTA/"))
        self.assertEqual(_col_f(csta[0], 1, 20), 1.004e9)
        self.assertEqual(_col_f(csta[0], 21, 40), 7.17e8)
        # and its /TH/MONV keeps the batch-1 channel set
        self.assertEqual(
            _th_monv_vars(_block(starter, "/TH/MONV/")),
            ["MASS", "VOL", "P", "A", "T", "AO", "UO", "AC", "UC",
             "CP", "CV", "GAMA", "MASS-IN", "ENTHA-IN", "ENER-INT", "WORK"])


if __name__ == "__main__":
    unittest.main()
