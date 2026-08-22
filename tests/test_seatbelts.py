"""The SEATBELT / RESTRAINT batch:

  *ELEMENT_SEATBELT (1D)          -> /SPRING on /PROP/TYPE23 + /MAT/LAW114
  *ELEMENT_SEATBELT (2D, N3/N4)   -> /SHELL  on /PROP/TYPE9  + /MAT/LAW119
  *SECTION_SEATBELT               -> /PROP/TYPE23 (SPR_MAT)
  *MAT_SEATBELT / *MAT_B01 (+_2D) -> /MAT/LAW114 or /MAT/LAW119
  *ELEMENT_SEATBELT_SLIPRING      -> /SLIPRING/SPRING
  *ELEMENT_SEATBELT_RETRACTOR     -> /RETRACTOR/SPRING
  *ELEMENT_SEATBELT_PRETENSIONER  -> the retractor's card 3
  *ELEMENT_SEATBELT_SENSOR        -> /SENSOR/ACCE | /SENSOR/TIME | /SENSOR/DIST
  *ELEMENT_SEATBELT_ACCELEROMETER -> /ACCEL + /SKEW/MOV + /ADMAS/0
  *DATABASE_SBTOUT                -> /TH/SLIPRING + /TH/RETRACTOR
  *DATABASE_HISTORY_SEATBELT      -> /TH/SPRING + /TH/SHEL + /TH/SH3N

Everything is asserted BY COLUMN, because that is the only way any of it is
visible in the .rad, and every number in the fixtures is DISTINCT per slot so
that a swap between two of them cannot pass. The conventions that carry the
most risk, and why each is pinned:

* **The force-strain curve crosses UNTOUCHED.** LS-DYNA's LLCID is "(Strain,
  Force) ... engineering strain" and /MAT/LAW114's fct_load is read at
  ``eps = (L-L0)/max(L0,LMIN)`` (``r23l114def3.F:366`` +
  ``redef_seatbelt.F90:162``), which the starter echoes as ``FORCE-ENGINEERING
  STRAIN CURVE``. So Xscale and Fscale stay at the reader default and NO
  transform is applied — the one curve in k2rad that crosses two solvers as-is.
* **``rho x Area == MPUL``, and the SPLIT decides the stiffness.** Mass is
  ``GEO(1) * max(L0,LMIN) * RHO`` (``rinit3.F:464,474``), so the product fixes
  the mass; but the area also sets ``XK_COMP = E*AREA``
  (``r23l114def3.F:224``) and the time step. The area therefore comes from
  ``*MAT_SEATBELT`` card 2's ``A``, never from ``*SECTION_SEATBELT``'s AREA,
  which LS-DYNA uses only for contact stiffness and defaults to 0.01.
* **The device node must come OFF the belt.** LS-DYNA lets a retractor's
  SBRNID be a node of its mouth element; Radioss refuses that outright
  (``hm_read_retractor.F:341`` ``ERROR 2030``). MEASURED: without the split
  the first faithful probe deck gives ``ERROR TERMINATION --- SEATBELTS``.
* **``Imass`` is inert but the LABEL is not.** ``rinit3.F:331-334`` forces
  ``IMASS = 1`` for MTN 114, so 1 and 2 are numerically identical (measured on
  a twin probe: same total mass, same inertia, same every time step) — and
  writing 2 makes the listing print ``SPRING VOLUME`` for a number that is an
  area.
* **``RE`` runs the OTHER WAY from dyna2rad.** ``RCOMP`` MULTIPLIES the
  compressive stress (``law119_membrane.F:190-191``), so eliminating
  compression means a SMALL RE — while ``convertmats.cxx:11047`` writes
  ``RE = (CSE==0) ? 1.0 : 0.01``, i.e. the LS-DYNA default (eliminate) becomes
  full compressive stiffness.
* **``PRBA`` is ``NU12``, not ``NUCOAT``.** ``convertmats.cxx:11049`` copies it
  into ``VC``, the COATING's Poisson ratio, leaving the belt's own at 0 —
  ``hm_read_mat119.F:118,165`` shows NUCOAT is meant to be left blank so the
  reader can default it to NU12.
* **``nu12*nu21 < 1`` or the deck dies late.** ``N21 = N12*100*Fscale22`` and
  ``DET = 1/(1-N12*N21)`` (``create_seatbelt.F:903,911``), refused from
  ``:920`` as ``ERROR 307`` under the misleading title SEATBELT MATERIAL.
* **``TDEL`` folds into the SENSOR, fully copied.** /RETRACTOR has no Tdel
  cell (``material_flow.F:695-702`` locks in the same cycle the sensor's
  TSTART passes), and dyna2rad's duplicate copies only Sensor_Type and Tdelay
  — so its /DIST copy has N1=N2=0 (starter ERROR 78) and its /TIME copy fires
  at TDEL instead of TIME+TDEL.
* **``/SENSOR/OR`` takes exactly TWO inputs and ignores Tdelay**
  (``sensor_or.F:75-78``), so four LS-DYNA sensors chain and the delay is
  folded into the LEAVES.
* **The count-driven card walks.** Every device's card 2 is claimed by RAW
  CONTIGUITY, never by "the next populated row": a SBSTYP=3 sensor card
  carrying TIME=0 is entirely blank, an all-blank retractor card 2 is legal,
  and on SBPRTY 7/8/9 the legacy cfg writes the pretensioner's card-2 field 0
  literally blank (#119).
* **A deck without a seatbelt keyword must be BYTE-IDENTICAL to master.**
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


def _erows(block):
    """An ELEMENT block's rows. /SHELL, /SPRING and friends carry NO title
    line, so ``_cards``'s ``block[2:]`` would drop the first element."""
    return [ln for ln in block[1:]
            if ln.strip() and not ln.startswith("#")
            and not ln.startswith("/")]


def _th_ids(starter: str, header: str):
    """The entity ids of one /TH group.

    Consecutive /TH groups are NOT separated by an HDR ruler, so ``_blocks``
    runs one into the next; the id rows are the lines after the VAR line and
    before the next ``/``-headed card."""
    blk = _block(starter, header)
    body = []
    for ln in blk[2:]:
        if ln.startswith("/"):
            break
        if ln.strip() and not ln.startswith("#"):
            body.append(ln)
    return [int(x) for ln in body[1:] for x in ln.split()]



def _col_f(line: str, a: int, b: int) -> float:
    return float(line[a - 1:b] or 0)


def _col_i(line: str, a: int, b: int) -> int:
    return int(line[a - 1:b] or 0)


def _col_s(line: str, a: int, b: int) -> str:
    return line[a - 1:b].strip()


def _warns(result, needle: str):
    return [w for w in result.warnings if needle in w]


def _c10(v) -> str:
    """One 10-column LS-DYNA cell. ``None`` is a BLANK cell, which is a
    different input from the string "0": a blank asks for the field's
    documented default, and for the count-driven walks it is what a
    preprocessor writes for an all-defaulted optional card."""
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


def _belt_card(eid, pid, n1, n2, sbrid=0, slen=0.0, n3=0, n4=0) -> str:
    """One *ELEMENT_SEATBELT card in its REAL columns:
    ``%8d%8d%8d%8d%8d%16lg%8d%8d`` — SLEN is SIXTEEN wide."""
    return (f"{eid:>8d}{pid:>8d}{n1:>8d}{n2:>8d}{sbrid:>8d}"
            f"{slen:>16g}{n3:>8d}{n4:>8d}\n")


# ── Deck fragments ───────────────────────────────────────────────────────────
#
# Six nodes on a straight line 100 apart give five belt elements of length 100
# each, so 1.6*LMIN and 3*LMIN thresholds are testable without the geometry
# warning firing on the reference deck.

_NODES = """\
*NODE
         1             0.0             0.0             0.0
         2           100.0             0.0             0.0
         3           200.0             0.0             0.0
         4           300.0             0.0             0.0
         5           400.0             0.0             0.0
         6           500.0             0.0             0.0
         7           200.0             0.0             0.0
         8           400.0             0.0             0.0
         9           500.0            50.0             0.0
        10             0.0            10.0             0.0
        11             0.0           100.0             0.0
        20             0.0             0.0           100.0
        21           100.0             0.0           100.0
        22           100.0           100.0           100.0
        23             0.0           100.0           100.0
"""

_BELT_PART = """\
*PART
belt
       900       900       900
"""

#: AREA and THICK are deliberately NON-DEFAULT and different from the
#: material's A: they are LS-DYNA contact numbers with no Radioss slot, and the
#: test asserts the emitted area comes from the MATERIAL.
_SECTION = """\
*SECTION_SEATBELT
       900      50.0       1.5
"""

_CURVES = """\
*DEFINE_CURVE
       910
                     0.0                     0.0
                    0.02                  1000.0
                     0.5                  8000.0
*DEFINE_CURVE
       911
                     0.0                     0.0
                    0.02                   900.0
                     0.5                  7500.0
*DEFINE_CURVE
       912
                     0.0                     0.0
                   0.001                  4000.0
*DEFINE_CURVE
       920
                     0.0                    0.20
                  1000.0                    0.35
*DEFINE_CURVE
       930
                     0.0                    0.22
                    0.01                    0.28
"""

_TERM = "*CONTROL_TERMINATION\n     0.020\n"


def _mat(mpul=1.5e-6, llcid=910, ulcid=911, lmin=2.5, cse=None, damp=None,
         e=None, card2=None, kw="MAT_SEATBELT", card3=None, card4=None):
    """*MAT_SEATBELT card 1 (+2/+3/+4). Card 2 is written only when E > 0,
    which is the manual's own condition and the #119 walk under test."""
    out = f"*{kw}\n" + _card(900, mpul, llcid, ulcid, lmin, cse, damp, e)
    if card2 is not None:
        out += _card(*card2)
    if card3 is not None:
        out += _card(*card3)
    if card4 is not None:
        out += _card(*card4)
    return out


def _belts(n=5, slen=0.0, sbrid=0):
    out = "*ELEMENT_SEATBELT\n"
    for k in range(n):
        out += _belt_card(11 + k, 900, 1 + k, 2 + k,
                          sbrid=sbrid if k == 0 else 0,
                          slen=slen if k == 0 else 0.0)
    return out


def _deck(*parts):
    return ("*KEYWORD\n" + _TERM + _NODES + "".join(parts) + _CURVES
            + "*END\n")


def _ref(**kw):
    """The reference 1D belt deck: part + section + material + five springs."""
    return _deck(_BELT_PART, _SECTION, _mat(**kw), _belts())


# 2D belt: one quad on a *SECTION_SHELL part carrying the belt material.
_SHELL_PART = """\
*PART
belt2d
       800       800       900
*SECTION_SHELL
       800         2
       1.2       1.2       1.2       1.2
"""




# ═════════════════════════════════════════════════════════════════════════════
class TestBeltElementCard(unittest.TestCase):
    """*ELEMENT_SEATBELT: eight variables in a 8/8/8/8/8/16/8/8 grid."""

    def test_the_sixteen_wide_slen_cell_is_sliced_correctly(self):
        """A uniform 8-wide slice reads the RIGHT half of SLEN as N3 and the
        LEFT half of N3 as N4 — and N3/N4 both non-zero is what turns a 1D
        belt into a 2D one, so the mis-slice silently converts the belt to a
        /SHELL on two nodes that do not exist."""
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(),
            "*ELEMENT_SEATBELT\n" + _belt_card(11, 900, 1, 2, 0, 3.25)))
        self.assertEqual(r.skipped_keywords, [])
        rows = _cards(_block(starter, "/SPRING/900"))
        self.assertEqual(rows, [f"{11:>10d}{1:>10d}{2:>10d}"])
        self.assertNotIn("/SHELL/900", starter)
        self.assertTrue(_warns(r, "SLEN=3.25"))

    def test_n3_and_n4_make_it_a_shell(self):
        """convertelements.cxx:86-95: BOTH non-zero, and the /SHELL takes
        (N1,N2,N3,N4) in that order."""
        r, starter, _e = _convert(_deck(
            _SHELL_PART, _mat(kw="MAT_SEATBELT_2D"),
            "*ELEMENT_SEATBELT\n" + _belt_card(31, 800, 20, 21, 0, 0.0,
                                               22, 23)))
        self.assertEqual(r.skipped_keywords, [])
        rows = _erows(_block(starter, "/SHELL/800"))
        self.assertEqual(rows[0][:50],
                         f"{31:>10d}{20:>10d}{21:>10d}{22:>10d}{23:>10d}")

    def test_only_one_of_n3_n4_leaves_it_one_dimensional(self):
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(),
            "*ELEMENT_SEATBELT\n" + _belt_card(11, 900, 1, 2, 0, 0.0, 3, 0)))
        self.assertEqual(r.skipped_keywords, [])
        self.assertIn("/SPRING/900", starter)
        self.assertNotIn("/SHELL/900", starter)

    def test_the_fixed_branch_keeps_the_sixteen_wide_cell(self):
        """The free split cannot handle ids wide enough to FILL all eight
        columns — they glue into one token — so this is the branch that
        actually slices, and the only one where the 16-wide SLEN cell can be
        got wrong. MEASURED with a uniform 8-wide slice: SLEN reads as 0 (its
        left half is blank) and its RIGHT half becomes N3, so the slack is
        lost silently and the element grows a node it does not have."""
        part = "*PART\nbelt\n{:>10d}       900       900\n".format(22222222)
        r, starter, _e = _convert(_deck(
            part, _SECTION, _mat(),
            "*ELEMENT_SEATBELT\n"
            + _belt_card(11111111, 22222222, 1, 2, 0, 3.25)))
        self.assertEqual(r.skipped_keywords, [])
        rows = _erows(_block(starter, "/SPRING/22222222"))
        self.assertEqual(rows, [f"{11111111:>10d}{1:>10d}{2:>10d}"])
        self.assertTrue(_warns(r, "SLEN=3.25"),
                        "the 16-wide cell was read")

    def test_a_free_format_card_still_reads(self):
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(),
            "*ELEMENT_SEATBELT\n11 900 1 2 0 3.25 0 0\n"))
        self.assertEqual(r.skipped_keywords, [])
        self.assertEqual(_cards(_block(starter, "/SPRING/900")),
                         [f"{11:>10d}{1:>10d}{2:>10d}"])
        self.assertTrue(_warns(r, "SLEN=3.25"))


# ═════════════════════════════════════════════════════════════════════════════
class TestBeltProperty(unittest.TestCase):
    """/PROP/TYPE23 (SPR_MAT) — prop_p23_SPR_MAT.cfg FORMAT(radioss2020)."""

    def test_card_columns_and_the_ten_blank_gap(self):
        """``CARD("%10d          %20lg%20lg%10d%10d%10d", ...)`` — the ten
        literal blanks at columns 11-20 are real, and writing the area there
        gives the reader an Imass of 0 and a Volume it never sees."""
        _r, starter, _e = _convert(_ref(e=200.0, card2=(33.3, 8.88e-12,
                                                        9.99e-12, 7.89e-6,
                                                        1230.0, 4.56, 2.34)))
        blk = _block(starter, "/PROP/TYPE23/900")
        self.assertEqual(blk[0], "/PROP/TYPE23/900")
        c = _cards(blk)[0]
        self.assertEqual(_col_i(c, 1, 10), 1, "Imass = 1 (AREA)")
        self.assertEqual(c[10:20], " " * 10, "cols 11-20 are blank")
        self.assertEqual(_col_f(c, 21, 40), 33.3, "Area from *MAT card 2 A")
        self.assertEqual(_col_f(c, 41, 60), 0.0, "Inertia")
        self.assertEqual(_col_i(c, 61, 70), 0, "skew_ID")
        self.assertEqual(_col_i(c, 71, 80), 0, "sens_ID")
        self.assertEqual(_col_i(c, 81, 90), 0, "Isflag")

    def test_imass_is_one_even_with_no_cross_section(self):
        """rinit3.F:331-334 forces IMASS=1 for MTN 114 anyway, so writing 2
        (as dyna2rad does at convertprops.cxx:2549) only makes the listing
        print SPRING VOLUME for a number that is an area."""
        _r, starter, _e = _convert(_ref())
        c = _cards(_block(starter, "/PROP/TYPE23/900"))[0]
        self.assertEqual(_col_i(c, 1, 10), 1)
        self.assertEqual(_col_f(c, 21, 40), 1.0)

    def test_the_section_area_and_thick_are_dropped_by_name(self):
        """*SECTION_SEATBELT AREA is a CONTACT stiffness number (default 0.01)
        and THICK a contact thickness; /PROP/TYPE23's Area is a MASS and
        STIFFNESS area. dyna2rad ignores the card entirely and never says so
        (convertprops.cxx:2538 reads LSD_MAT_SEATBELT_A instead)."""
        r, _s, _e = _convert(_ref())
        w = _warns(r, "*SECTION_SEATBELT 900")
        self.assertTrue(w)
        self.assertIn("AREA=50", w[0])
        self.assertIn("THICK=1.5", w[0])
        self.assertIn("CONTACT", w[0])

    def test_the_part_names_the_belt_material(self):
        """A /PART on a /PROP/TYPE23 MUST name a material whose law is
        108/113/114/135 — hm_read_part.F answers ERROR 179 / 1715 otherwise.
        That is why /MAT/LAW114 is written beside the property here and not
        left to the ordinary material path."""
        _r, starter, _e = _convert(_ref())
        c = _cards(_block(starter, "/PART/900"))[0]
        self.assertEqual(_col_i(c, 1, 10), 900, "prop_ID")
        self.assertEqual(_col_i(c, 11, 20), 900, "mat_ID, NOT 0")


# ═════════════════════════════════════════════════════════════════════════════
class TestBeltMaterial114(unittest.TestCase):
    """/MAT/LAW114 (SPR_SEATBELT) — five cards, mat114_spr_seatbelt.cfg."""

    def test_all_five_cards_by_column(self):
        _r, starter, _e = _convert(_ref(
            mpul=1.5e-6, lmin=2.5, e=7.77e9,
            card2=(33.3, 8.88e-12, 9.99e-12, 7.89e-6, 1230.0, 4.56, 2.34)))
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(len(c), 5)
        # card 1: RHO_I LMIN.  rho x Area = 1.5e-6/33.3 x 33.3 = MPUL.
        # _f prints %.6E below 1e-4, so the card carries seven digits and the
        # comparison has to be made at the card's precision, not the float's.
        self.assertAlmostEqual(_col_f(c[0], 1, 20), 1.5e-6 / 33.3,
                               delta=1e-13)
        self.assertAlmostEqual(_col_f(c[0], 1, 20) * 33.3, 1.5e-6,
                               delta=1e-12, msg="rho x Area == MPUL")
        self.assertEqual(_col_f(c[0], 21, 40), 2.5)
        # card 2: K C — both 0 on purpose (see the two tests below).
        self.assertEqual(_col_f(c[1], 1, 20), 0.0, "K")
        self.assertEqual(_col_f(c[1], 21, 40), 0.0, "C")
        # card 3: fct_load fct_uload Xscale Fscale
        self.assertEqual(_col_i(c[2], 1, 10), 910)
        self.assertEqual(_col_i(c[2], 11, 20), 911)
        self.assertEqual(_col_f(c[2], 21, 40), 0.0, "Xscale -> reader 1.0")
        self.assertEqual(_col_f(c[2], 41, 60), 0.0, "Fscale -> reader 1.0")
        # card 4: E I J FMAX MMAX — five DISTINCT numbers, so any swap fails.
        self.assertEqual(_col_f(c[3], 1, 20), 7.77e9, "E")
        self.assertEqual(_col_f(c[3], 21, 40), 8.88e-12, "I -> Ibend")
        self.assertEqual(_col_f(c[3], 41, 60), 9.99e-12, "J -> Itors")
        self.assertEqual(_col_f(c[3], 61, 80), 1230.0, "F -> FMAX")
        self.assertEqual(_col_f(c[3], 81, 100), 4.56, "M -> MMAX")
        # card 5: AS R
        self.assertEqual(_col_f(c[4], 1, 20), 7.89e-6, "AS -> SHEAR_AREA")
        self.assertEqual(_col_f(c[4], 21, 40), 2.34, "R -> Rfac")

    def test_the_curve_is_passed_through_untouched(self):
        """LS-DYNA LLCID is (engineering strain, force); LAW114's fct_load is
        read at eps = (L-L0)/max(L0,LMIN) and echoed by the starter as
        FORCE-ENGINEERING STRAIN CURVE. Same quantity on both axes, so Xscale
        and Fscale stay at the reader default and the /FUNCT keeps its id and
        its points."""
        _r, starter, _e = _convert(_ref())
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(_col_i(c[2], 1, 10), 910)
        self.assertEqual(_col_f(c[2], 21, 40), 0.0)
        self.assertEqual(_col_f(c[2], 41, 60), 0.0)
        pts = _cards(_block(starter, "/FUNCT/910"))
        self.assertEqual(_col_f(pts[1], 1, 20), 0.02)
        self.assertEqual(_col_f(pts[1], 21, 40), 1000.0)

    def test_no_card_two_means_tension_only(self):
        """hm_read_mat114.F:169-170 has the F_MAX = INFINITY default COMMENTED
        OUT, so a blank FMAX really is 0 — and with E=0 the compression
        tangent E*Area is 0 too. That IS LS-DYNA's 1D belt: "zero forces being
        generated whenever the strain becomes negative"."""
        _r, starter, _e = _convert(_ref())
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(_col_f(c[3], 1, 20), 0.0, "E")
        self.assertEqual(_col_f(c[3], 61, 80), 0.0, "FMAX")
        self.assertEqual(_col_f(c[3], 81, 100), 0.0, "MMAX")

    def test_card_two_is_read_only_when_e_is_positive(self):
        """The #119 walk on a card-1 VALUE. Reading card 2 unconditionally on
        an ordinary belt takes the NEXT material's MID as this one's
        cross-sectional area — and A is exactly what sizes the property."""
        deck = _deck(_BELT_PART, _SECTION,
                     _mat(e=None) + "*MAT_ELASTIC\n"
                     + _card(700, 7.8e-9, 210000.0, 0.3),
                     _belts())
        r, starter, _e = _convert(deck)
        self.assertEqual(r.skipped_keywords, [])
        c = _cards(_block(starter, "/PROP/TYPE23/900"))[0]
        self.assertEqual(_col_f(c, 21, 40), 1.0,
                         "Area 1.0, not the *MAT_ELASTIC MID")
        self.assertIn("/MAT/ELAST/700", starter)

    def test_the_lsdyna_card_two_defaults_are_applied(self):
        """J = 2I, AS = A, F = M = 1e20, R = 0.05 — every one of them real
        physics that a BLANK cell states rather than omits. dyna2rad's
        CopyValue does no defaulting at all (convertutilsbase.cxx:101-137), so
        a blank F reaches LAW114 as FMAX = 0: a belt clamped to ZERO
        compression force on a deck that explicitly asked for the bending
        model."""
        _r, starter, _e = _convert(_ref(
            e=7.77e9, card2=(33.3, 8.88e-12, None, None, None, None, None)))
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(_col_f(c[3], 41, 60), 2 * 8.88e-12, "J -> 2I")
        self.assertEqual(_col_f(c[3], 61, 80), 1.0e20, "F -> 1e20")
        self.assertEqual(_col_f(c[3], 81, 100), 1.0e20, "M -> 1e20")
        self.assertEqual(_col_f(c[4], 1, 20), 33.3, "AS -> A")
        self.assertEqual(_col_f(c[4], 21, 40), 0.05, "R -> 0.05")

    def test_damp_is_left_to_the_starter_and_said_so(self):
        """LS-DYNA's DAMP is a Rayleigh coefficient for SHELL belts; on a 1D
        belt LS-DYNA computes the damping itself. Leaving C=0 makes the
        starter do the same ('SEATBELTS DEFAULT DAMPING COMPUTATION'), so this
        is a MATCH rather than the loss dyna2rad's silence implies."""
        r, starter, _e = _convert(_ref(damp=0.1))
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(_col_f(c[1], 21, 40), 0.0)
        self.assertTrue(_warns(r, "MATCH, not a loss"))

    def test_cse_is_inert_on_a_one_dimensional_belt(self):
        """The cfg's own RADIO text says CSE eliminates compressive stresses
        'in shell fabric'; on a 1D belt compression is governed by E and FMAX.
        Reported as inert, not as a loss."""
        r, _s, _e = _convert(_ref(cse=1.0))
        self.assertTrue(_warns(r, "Nothing is lost; the field is inert"))

    def test_a_missing_curve_is_screened_out(self):
        """The #106 rule: naming a function the deck does not define is a
        starter error that refuses the whole run."""
        r, starter, _e = _convert(_ref(llcid=999))
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(_col_i(c[2], 1, 10), 0)
        self.assertTrue(_warns(r, "LLCID=999 names no *DEFINE_CURVE"))

    def test_a_define_table_takes_its_first_curve_and_names_the_loss(self):
        """LAW114 has ONE function slot and no rate dependence at all
        (hm_read_mat114.F:88 ISRATE=0), so a strain-rate FAMILY cannot be
        expressed. dyna2rad does the same but dereferences funcIdList[0] with
        no empty check (convertmats.cxx:9450)."""
        table = ("*DEFINE_TABLE_2D\n" + _card(940)
                 + _card(0.001, 910) + _card(1.0, 911))
        r, starter, _e = _convert(_deck(_BELT_PART, _SECTION,
                                        _mat(llcid=940), _belts(), table))
        c = _cards(_block(starter, "/MAT/LAW114/900"))
        self.assertEqual(_col_i(c[2], 1, 10), 910)
        self.assertTrue(_warns(r, "rate dependence is LOST"))

    def test_mat_b01_is_the_same_material(self):
        _r, starter, _e = _convert(_deck(_BELT_PART, _SECTION,
                                         _mat(kw="MAT_B01"), _belts()))
        self.assertIn("/MAT/LAW114/900", starter)


# ═════════════════════════════════════════════════════════════════════════════
class TestBelt2D(unittest.TestCase):
    """/MAT/LAW119 (SH_SEATBELT) + the /PROP/TYPE9 the law demands."""

    def _deck(self, **kw):
        return _deck(_SHELL_PART, _mat(kw="MAT_SEATBELT_2D", **kw),
                     "*ELEMENT_SEATBELT\n"
                     + _belt_card(31, 800, 20, 21, 0, 0.0, 22, 23))

    def test_all_five_cards_by_column(self):
        _r, starter, _e = _convert(self._deck(
            mpul=0.135, lmin=1.5e-3, cse=1.0,
            card3=(None, None, 1.9e8, 1.1e-3, None, -0.25, 0.21, None),
            card4=(3.1e5,)))
        c = _cards(_block(starter, "/MAT/LAW119/900"))
        self.assertEqual(len(c), 5)
        # card 1: RHO_I is a LINEIC MASS here, so MPUL goes in unchanged.
        self.assertEqual(_col_f(c[0], 1, 20), 0.135)
        self.assertEqual(_col_f(c[0], 21, 40), 1.5e-3)
        # card 2: K C RE.  CSE=1 = "don't eliminate" -> full compression.
        self.assertEqual(_col_f(c[1], 1, 20), 0.0, "K")
        self.assertEqual(_col_f(c[1], 21, 40), 0.0, "C")
        self.assertEqual(_col_f(c[1], 41, 60), 1.0, "RE")
        # card 3: fct_load fct_uload Fscale1 Fscale2 Ireload
        self.assertEqual(_col_i(c[2], 1, 10), 910)
        self.assertEqual(_col_i(c[2], 11, 20), 911)
        # card 4: E22 V12 G12 Fscale22.  EB<0 is a RATIO, so E22 stays blank
        # and Fscale22 carries |EB|/100 (the reader multiplies it by 100).
        self.assertEqual(_col_f(c[3], 1, 20), 0.0, "E22 from the ratio")
        self.assertEqual(_col_f(c[3], 21, 40), 0.21, "PRBA -> NU12")
        self.assertEqual(_col_f(c[3], 41, 60), 3.1e5, "GAB -> G12")
        self.assertAlmostEqual(_col_f(c[3], 61, 80), 0.0025, places=12)
        # card 5: EC VC TC — NUCOAT left blank so the reader defaults it.
        self.assertEqual(_col_f(c[4], 1, 20), 1.9e8, "ECOAT -> EC")
        self.assertEqual(_col_f(c[4], 21, 40), 0.0, "NUCOAT stays blank")
        self.assertEqual(_col_f(c[4], 41, 60), 1.1e-3, "TCOAT -> TC")

    def test_prba_goes_to_nu12_not_to_the_coating(self):
        """dyna2rad's convertmats.cxx:11049 is CopyValue(..., "PRBA", "VC") —
        the belt's minor Poisson ratio into the COATING's slot, leaving NU12
        at 0. hm_read_mat119.F:165 IF (NUCOAT == ZERO) NUCOAT = N12 shows
        NUCOAT is meant to be left blank."""
        _r, starter, _e = _convert(self._deck(
            card3=(None, None, None, None, None, None, 0.27, None)))
        c = _cards(_block(starter, "/MAT/LAW119/900"))
        self.assertEqual(_col_f(c[3], 21, 40), 0.27, "NU12")
        self.assertEqual(_col_f(c[4], 21, 40), 0.0, "NUCOAT")

    def test_cse_zero_eliminates_compression(self):
        """RCOMP MULTIPLIES the compressive stress
        (law119_membrane.F:190-191), so eliminating compression is a SMALL RE.
        dyna2rad writes RE = (CSE==0) ? 1.0 : 0.01 — both directions wrong."""
        _r, starter, _e = _convert(self._deck(cse=0.0))
        c = _cards(_block(starter, "/MAT/LAW119/900"))
        self.assertEqual(_col_f(c[1], 41, 60), 0.01)

    def test_cse_two_is_warn_dropped_to_the_eliminate_side(self):
        r, starter, _e = _convert(self._deck(cse=2.0))
        c = _cards(_block(starter, "/MAT/LAW119/900"))
        self.assertEqual(_col_f(c[1], 41, 60), 0.01)
        self.assertTrue(_warns(r, "CSE=2"))

    def test_the_determinant_constraint_is_enforced(self):
        """N21 = N12*100*Fscale22 and DET = 1/(1-N12*N21)
        (create_seatbelt.F:903,911), refused LATE from :920 as ERROR 307
        'DETERMINANT OF MATERIAL MATRIX IS LESS THAN 0' under the misleading
        title SEATBELT MATERIAL. nu12*nu21 < 1 is the ordinary orthotropic
        positive-definiteness condition, so NU12 is clamped to the boundary
        and the deck is told."""
        r, starter, _e = _convert(self._deck(
            card3=(None, None, None, None, None, -20.0, 0.45, None)))
        c = _cards(_block(starter, "/MAT/LAW119/900"))
        nu12 = _col_f(c[3], 21, 40)
        ratio = _col_f(c[3], 61, 80) * 100.0
        self.assertLess(nu12 * nu12 * ratio, 1.0)
        self.assertTrue(_warns(r, "ERROR 307"))

    def test_the_property_is_a_synthesized_type9(self):
        """/MAT/LAW119 declares SHELL_ORTHOTROPIC (hm_read_mat119.F:218), so
        the part cannot stay on the isotropic /PROP/SHELL its *SECTION_SHELL
        would give it — check_mat_elem_prop_compatibility.F:175-192 answers
        ERROR 3047. Ip=24 is what the starter forces anyway (WARNING 2076)."""
        r, starter, _e = _convert(self._deck())
        blks = _blocks(starter, "/PROP/TYPE9/")
        self.assertEqual(len(blks), 1)
        c = _cards(blks[0])
        self.assertEqual(_col_i(c[0], 1, 10), 12, "Ishell (QEPH)")
        self.assertEqual(_col_i(c[0], 11, 20), 11, "Ismstr")
        self.assertEqual(_col_i(c[0], 21, 30), 3, "Ish3n")
        self.assertEqual(_col_f(c[1], 61, 80), 0.25, "Dm")
        self.assertEqual(_col_f(c[2], 21, 40), 1.2, "Thick from T1")
        self.assertEqual(_col_i(c[3], 91, 100), 24, "Ip")
        prop_id = int(blks[0][0].rsplit("/", 1)[1])
        part = _cards(_block(starter, "/PART/800"))[0]
        self.assertEqual(_col_i(part, 1, 10), prop_id, "the /PART follows it")
        self.assertTrue(_warns(r, "ERROR 3047"))

    def test_no_springs_are_emitted_for_a_2d_belt(self):
        """starter0.F:782-803 -> hm_convert_2d_elements_seatbelt.F generates
        the 1D /SPRING, /PART, /PROP/TYPE23 and /MAT/LAW114 itself. Emitting
        them here too would double the belt."""
        _r, starter, _e = _convert(self._deck())
        self.assertNotIn("/SPRING/", starter)
        self.assertNotIn("/MAT/LAW114/", starter)

    def test_the_section_decides_the_law_not_the_keyword(self):
        """convertmats.cxx:517-526 branches on the PROPERTY keyword, so a
        *MAT_SEATBELT_2D on a *SECTION_SEATBELT is LAW114 and a plain
        *MAT_SEATBELT on a *SECTION_SHELL is LAW119."""
        _r, s1, _e = _convert(_deck(_BELT_PART, _SECTION,
                                    _mat(kw="MAT_SEATBELT_2D"), _belts()))
        self.assertIn("/MAT/LAW114/900", s1)
        _r, s2, _e = _convert(_deck(
            _SHELL_PART, _mat(kw="MAT_SEATBELT"),
            "*ELEMENT_SEATBELT\n"
            + _belt_card(31, 800, 20, 21, 0, 0.0, 22, 23)))
        self.assertIn("/MAT/LAW119/900", s2)


# ═════════════════════════════════════════════════════════════════════════════
_SENSORS = """\
*ELEMENT_SEATBELT_SENSOR
        61         1         0
        10         2      12.5     0.002
        62         3         0
    0.0040
        63         4         0
         8         9      55.0       5.0
"""


def _slipring(sbsrid=51, sbid1=12, sbid2=13, fc=0.25, sbrnid=7, ltime=0.006,
              fcs=0.40, onid=11, card2=(0.55, 0, 12, 0.75, None, 920, 0)):
    out = "*ELEMENT_SEATBELT_SLIPRING\n" + _card(
        sbsrid, sbid1, sbid2, fc, sbrnid, ltime, fcs, onid)
    if card2 is not None:
        out += _card(*card2)
    return out


class TestSlipring(unittest.TestCase):
    """/SLIPRING/SPRING — three cards, slipring.cfg FORMAT(radioss2022)."""

    def _deck(self, **kw):
        return _deck(_BELT_PART, _SECTION, _mat(), _belts(),
                     _slipring(**kw))

    def test_card_columns(self):
        """Every value on the reference ring is DISTINCT, so a swap between
        any two columns fails. Note card 1's LS-DYNA field order is
        `SBSRID SBID1 SBID2 FC SBRNID LTIME FCS ONID` — FC sits BETWEEN the
        element ids and the anchorage node."""
        r, starter, _e = _convert(self._deck())
        self.assertEqual(r.skipped_keywords, [])
        blk = _block(starter, "/SLIPRING/SPRING/51")
        c = _cards(blk)
        self.assertEqual(len(c), 3)
        self.assertEqual(_col_i(c[0], 1, 10), 12, "EL_ID1")
        self.assertEqual(_col_i(c[0], 11, 20), 13, "EL_ID2")
        self.assertEqual(_col_i(c[0], 21, 30), 7, "SBRNID -> Node_ID")
        self.assertEqual(_col_i(c[0], 31, 40), 11, "ONID -> Node_ID2")
        self.assertNotEqual(_col_i(c[0], 41, 50), 0, "Sens_ID from LTIME")
        self.assertEqual(_col_i(c[0], 51, 60), 1, "DIRECT 12 -> Flow_flag 1")
        self.assertEqual(_col_f(c[0], 61, 80), 0.55, "K -> A")
        self.assertEqual(_col_f(c[0], 81, 100), 0.75, "DC -> Ed_factor")
        self.assertEqual(_col_i(c[1], 1, 10), 0, "Fct_ID1 (FC is scalar)")
        self.assertEqual(_col_i(c[1], 11, 20), 920, "LCNFFD -> Fct_ID2")
        self.assertEqual(_col_f(c[1], 21, 40), 0.25, "FC -> Fricd")
        self.assertEqual(_col_f(c[2], 21, 40), 0.40, "FCS -> Frics")

    def test_the_four_scale_cells_are_left_to_the_reader(self):
        """hm_read_slipring.F:168-190 supplies unit-consistent defaults, which
        is the only way to get a DIMENSIONED default right without knowing the
        deck's unit system."""
        _r, starter, _e = _convert(self._deck())
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        for col in ((41, 60), (61, 80), (81, 100)):
            self.assertEqual(_col_f(c[1], *col), 0.0)
            self.assertEqual(_col_f(c[2], *col), 0.0)

    def test_ltime_becomes_a_time_sensor(self):
        _r, starter, _e = _convert(self._deck(ltime=0.006))
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        sid = _col_i(c[0], 41, 50)
        self.assertEqual(_col_f(_cards(_block(starter,
                                              f"/SENSOR/TIME/{sid}"))[0],
                                1, 20), 0.006)

    def test_no_ltime_means_no_sensor(self):
        """The LS-DYNA default 1e20 means 'never locks', which is Sens_ID = 0.
        dyna2rad's SOURCE writes a Tdelay=1e20 sensor and its shipped reader
        writes none; both express the same thing, and 0 is the honest one."""
        _r, starter, _e = _convert(self._deck(ltime=None))
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        self.assertEqual(_col_i(c[0], 41, 50), 0)

    def test_a_negative_fc_is_a_curve_id(self):
        """meci_data_reader.cpp:6846 — "if the value is negative, its abs
        value is the ID of an object". Reading it as a coefficient hands the
        ring a friction of -930."""
        _r, starter, _e = _convert(self._deck(fc=-930.0, fcs=-920.0))
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        self.assertEqual(_col_i(c[1], 1, 10), 930, "FC curve -> Fct_ID1")
        self.assertEqual(_col_f(c[1], 21, 40), 0.0, "Fricd left to the reader")
        self.assertEqual(_col_i(c[2], 1, 10), 920, "FCS curve -> Fct_ID3")

    def test_the_flow_flag_table(self):
        """Established from the ENGINE: material_flow.F:266-267 grows strand
        1 and shrinks strand 2 by DELTA_LO, and :253-254 blocks FL_FLAG==1
        exactly when DELTA_LO > 0 — so Flow_flag 1 permits only 1->2, which is
        DIRECT 12."""
        for direct, flow in ((0, 0), (12, 1), (21, 2)):
            with self.subTest(direct=direct):
                _r, starter, _e = _convert(self._deck(
                    card2=(0.55, 0, direct, 0.75, None, 920, 0)))
                c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
                self.assertEqual(_col_i(c[0], 51, 60), flow)

    def test_an_unknown_direct_falls_back_to_zero_and_says_so(self):
        r, starter, _e = _convert(self._deck(
            card2=(0.55, 0, 99, 0.75, None, 920, 0)))
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        self.assertEqual(_col_i(c[0], 51, 60), 0)
        self.assertTrue(_warns(r, "DIRECT=99"))

    def test_funcid_is_warn_dropped_by_name(self):
        """Radioss's angle dependence is fixed in FORM:
        fric = mu*(1 + A*gamma^2) with gamma the SKEW angle
        (material_flow.F:204), so an arbitrary f(theta) has no slot."""
        r, _s, _e = _convert(self._deck(
            card2=(0.55, 941, 12, 0.75, None, 920, 0)))
        self.assertTrue(_warns(r, "FUNCID=941"))

    def test_a_missing_belt_element_drops_the_ring(self):
        """ERROR 2032: the element is not a /PROP/TYPE23 + /MAT/LAW114
        seatbelt spring, and the run would not start at all."""
        r, starter, _e = _convert(self._deck(sbid1=99))
        self.assertNotIn("/SLIPRING/", starter)
        self.assertTrue(_warns(r, "ERROR 2032"))

    def test_a_shell_belt_ring_is_dropped_by_name(self):
        r, starter, _e = _convert(self._deck(sbrnid=-5))
        self.assertNotIn("/SLIPRING/", starter)
        self.assertTrue(_warns(r, "SHELL-belt slipring"))

    def test_card_two_is_optional(self):
        """The cfg gates it on ONID != 0. With ONID blank and no card 2 the
        ring still converts, with A, Ed_factor and the two normal-force curves
        at their defaults."""
        _r, starter, _e = _convert(self._deck(onid=None, card2=None))
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        self.assertEqual(_col_i(c[0], 31, 40), 0, "Node_ID2")
        self.assertEqual(_col_f(c[0], 61, 80), 0.0, "A")
        self.assertEqual(_col_i(c[1], 11, 20), 0, "Fct_ID2")

    def test_two_rings_in_one_block_stay_in_phase(self):
        """The #119 walk: ring 1 carries a card 2 and ring 2 does not, so a
        stride that assumed either would read the second ring's card 1 as the
        first one's card 2 (or the reverse)."""
        body = ("*ELEMENT_SEATBELT_SLIPRING\n"
                + _card(51, 12, 13, 0.25, 7, 0.006, 0.40, 11)
                + _card(0.55, 0, 12, 0.75, None, 920, 0)
                + _card(52, 14, 15, 0.30, 8, None, 0.35, None))
        r, starter, _e = _convert(_deck(_BELT_PART, _SECTION, _mat(),
                                        _belts(), body))
        self.assertEqual(r.skipped_keywords, [])
        c1 = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        c2 = _cards(_block(starter, "/SLIPRING/SPRING/52"))
        self.assertEqual(_col_f(c1[0], 61, 80), 0.55, "ring 1 keeps its K")
        self.assertEqual(_col_i(c2[0], 1, 10), 14, "ring 2's EL_ID1")
        self.assertEqual(_col_f(c2[1], 21, 40), 0.30, "ring 2's Fricd")
        self.assertEqual(_col_f(c2[0], 61, 80), 0.0, "ring 2 has no card 2")

    def test_a_blank_card_two_does_not_swallow_the_next_ring(self):
        body = ("*ELEMENT_SEATBELT_SLIPRING\n"
                + _card(51, 12, 13, 0.25, 7, 0.006, 0.40, 11)
                + "\n"
                + _card(52, 14, 15, 0.30, 8, None, 0.35, None))
        r, starter, _e = _convert(_deck(_BELT_PART, _SECTION, _mat(),
                                        _belts(), body))
        self.assertEqual(r.skipped_keywords, [])
        self.assertEqual(len(_blocks(starter, "/SLIPRING/SPRING/")), 2)
        c2 = _cards(_block(starter, "/SLIPRING/SPRING/52"))
        self.assertEqual(_col_i(c2[0], 1, 10), 14)


# ═════════════════════════════════════════════════════════════════════════════
def _retractor(sbrid=41, sbrnid=1, sbid=11, sids=(61, 62, 0, 0), dsid=0,
               card2=(0.003, 12.0, 910, 911, 6.25, 0, 0)):
    out = "*ELEMENT_SEATBELT_RETRACTOR\n" + _card(
        sbrid, sbrnid, sbid, *sids, dsid)
    if card2 is not None:
        out += _card(*card2)
    return out


def _pretensioner(sbprid=71, sbprty=4, sbsids=(63, 0, 0, 0), sbrid=41,
                  time=0.002, ptlcid=912, lmtfrc=7777.0, lmtpin=None):
    return ("*ELEMENT_SEATBELT_PRETENSIONER\n"
            + _card(sbprid, sbprty, *sbsids)
            + _card(sbrid, time, ptlcid, lmtfrc, lmtpin))


class TestRetractorPretensioner(unittest.TestCase):
    """/RETRACTOR/SPRING — three cards, the pretensioner folded onto card 3."""

    def _deck(self, ret=None, pre=None, sensors=_SENSORS):
        return _deck(_BELT_PART, _SECTION, _mat(), _belts(), sensors,
                     _retractor() if ret is None else ret,
                     "" if pre is None else pre)

    def test_card_columns_with_unequal_sensor_ids(self):
        """SID1=61 and the pretensioner's SBSID1=63 are DIFFERENT sensors, so
        a Sens_ID1 / Sens_ID2 swap cannot pass. TDEL=0.003 and TIME=0.002 are
        different too, so the two delayed copies are distinguishable."""
        r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(61, 0, 0, 0)), pre=_pretensioner()))
        self.assertEqual(r.skipped_keywords, [])
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(len(c), 3)
        self.assertEqual(_col_i(c[0], 1, 10), 11, "SBID -> EL_ID")
        self.assertEqual(_col_i(c[0], 11, 20), 1, "SBRNID -> Node_ID")
        self.assertEqual(_col_f(c[0], 21, 40), 6.25, "LFED -> Elem_size")
        self.assertEqual(_col_f(c[1], 11, 30), 12.0, "PULL -> Pullout")
        self.assertEqual(_col_i(c[1], 31, 40), 910, "LLCID -> Fct_ID1")
        self.assertEqual(_col_i(c[1], 41, 50), 911, "ULCID -> Fct_ID2")
        self.assertEqual(_col_i(c[2], 11, 20), 2, "SBPRTY 4 -> Tens_typ 2")
        self.assertEqual(_col_f(c[2], 21, 40), 7777.0, "LMTFRC -> Force")
        self.assertEqual(_col_i(c[2], 41, 50), 912, "PTLCID -> Fct_ID3")
        # The two sensor slots must NOT be the same id.
        s1, s2 = _col_i(c[1], 1, 10), _col_i(c[2], 1, 10)
        self.assertNotEqual(s1, 0)
        self.assertNotEqual(s2, 0)
        self.assertNotEqual(s1, s2)

    def test_the_ordinate_scale_comes_before_the_abscissa_scale(self):
        """Cards 2 and 3 are `... Yscale Xscale` while the starter's echo
        prints them the other way round. Both are left 0 so
        hm_read_retractor.F:180-192 supplies the unit-consistent defaults."""
        _r, starter, _e = _convert(self._deck())
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_f(c[1], 51, 70), 0.0, "Yscale1")
        self.assertEqual(_col_f(c[1], 71, 90), 0.0, "Xscale1")
        self.assertEqual(_col_f(c[2], 51, 70), 0.0, "Yscale2")
        self.assertEqual(_col_f(c[2], 71, 90), 0.0, "Xscale2")

    def test_tdel_folds_into_a_fully_copied_sensor(self):
        """/RETRACTOR has NO Tdel cell — material_flow.F:695-702 locks in the
        same cycle the sensor's TSTART passes. dyna2rad's duplicate copies
        only Sensor_Type and Tdelay (convertelements.cxx:906-916), so its
        /TIME copy fires at TDEL instead of TIME+TDEL."""
        _r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(62, 0, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        sid = _col_i(c[1], 1, 10)
        self.assertNotEqual(sid, 62, "a COPY, not the shared sensor")
        dup = _cards(_block(starter, f"/SENSOR/TIME/{sid}"))
        self.assertAlmostEqual(_col_f(dup[0], 1, 20), 0.004 + 0.003,
                               places=10)
        # and the ORIGINAL keeps its own instant
        base = _cards(_block(starter, "/SENSOR/TIME/62"))
        self.assertEqual(_col_f(base[0], 1, 20), 0.004)

    def test_a_delayed_dist_sensor_keeps_its_nodes(self):
        """dyna2rad's /DIST duplicate has N1=N2=Dmin=Dmax=0 and the starter
        answers ERROR 78 NODE ID=0 DOES NOT EXIST, twice, refusing the run."""
        _r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(63, 0, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        sid = _col_i(c[1], 1, 10)
        dup = _cards(_block(starter, f"/SENSOR/DIST/{sid}"))
        self.assertEqual(_col_f(dup[0], 1, 20), 0.003, "Tdelay = TDEL")
        self.assertEqual(_col_i(dup[1], 1, 10), 8, "N1 survives")
        self.assertEqual(_col_i(dup[1], 11, 20), 9, "N2 survives")
        self.assertEqual(_col_f(dup[1], 21, 40), 5.0, "Dmin survives")
        self.assertEqual(_col_f(dup[1], 41, 60), 55.0, "Dmax survives")

    def test_a_delayed_acce_sensor_keeps_its_accelerometer(self):
        """dyna2rad's /ACCE duplicate has Nacc=0 and no accel_ID at all."""
        _r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(61, 0, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        sid = _col_i(c[1], 1, 10)
        dup = _cards(_block(starter, f"/SENSOR/ACCE/{sid}"))
        self.assertEqual(_col_f(dup[0], 1, 20), 0.003, "Tdelay = TDEL")
        self.assertEqual(_col_i(dup[1], 1, 10), 1, "Nacc")
        self.assertNotEqual(_col_i(dup[2], 1, 10), 0, "accel_ID")
        self.assertEqual(_col_s(dup[2], 11, 20), "Y", "dir")
        self.assertEqual(_col_f(dup[2], 21, 40), 12.5, "Tomin")
        self.assertEqual(_col_f(dup[2], 41, 60), 0.002, "Tmin")

    def test_zero_tdel_reuses_the_sensor_itself(self):
        _r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(62, 0, 0, 0),
                           card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_i(c[1], 1, 10), 62)

    def test_four_sensors_become_an_or_tree(self):
        """LS-DYNA ORs SID1..SID4; /RETRACTOR/SPRING has ONE Sens_ID1 and
        dyna2rad takes the first non-zero (convertelements.cxx:838-846), so a
        belt that should lock on either condition locks only on one."""
        sensors = _SENSORS + _card(64, 3, 0) + _card(0.0055)
        _r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(61, 62, 63, 64),
                           card2=(0.0, 12.0, 910, 911, 6.25, 0, 0)),
            sensors=sensors))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        top = _col_i(c[1], 1, 10)
        gates = {int(b[0].rsplit("/", 1)[1]): _cards(b)
                 for b in _blocks(starter, "/SENSOR/OR/")}
        self.assertEqual(len(gates), 3, "four inputs need three OR gates")
        self.assertIn(top, gates)
        # every leaf reachable from the top gate
        seen, stack = set(), [top]
        while stack:
            n = stack.pop()
            if n in gates:
                stack += [_col_i(gates[n][1], 1, 10),
                          _col_i(gates[n][1], 11, 20)]
            else:
                seen.add(n)
        self.assertEqual(seen, {61, 62, 63, 64})

    def test_the_or_gate_carries_no_delay(self):
        """sensor_or.F sets TSTART = TT at activation with no reference to
        Tdelay, so the delay has to be folded into the LEAVES."""
        _r, starter, _e = _convert(self._deck(
            ret=_retractor(sids=(61, 62, 0, 0))))
        for b in _blocks(starter, "/SENSOR/OR/"):
            self.assertEqual(_col_f(_cards(b)[0], 1, 20), 0.0)
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        gate = _cards(_block(starter, f"/SENSOR/OR/{_col_i(c[1], 1, 10)}"))
        for leaf in (_col_i(gate[1], 1, 10), _col_i(gate[1], 11, 20)):
            self.assertNotIn(leaf, (61, 62), "each leaf is a delayed COPY")

    def test_the_sbprty_table(self):
        """material_flow.F:544-596. SBPRTY 7 goes to Tens_typ 4 (ADDITIVE
        force, :580,623 YY = YY + PRETENS) because an INDEPENDENT pretensioner
        adds to the retractor rather than replacing it; dyna2rad maps 6 and 7
        both to 3 and never produces Tens_typ 4 at all."""
        for sbprty, tens in ((1, 1), (4, 2), (5, 1), (6, 3), (7, 4), (8, 5)):
            with self.subTest(sbprty=sbprty):
                _r, starter, _e = _convert(self._deck(
                    pre=_pretensioner(sbprty=sbprty)))
                c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
                self.assertEqual(_col_i(c[2], 11, 20), tens)

    def test_the_unmapped_sbprty_values_are_warn_dropped_by_name(self):
        """dyna2rad writes Tens_typ = 0 with the sensor, the curve and the
        force still attached (convertelements.cxx:1011-1027) — a retractor
        carrying a pretensioner's data and doing nothing with it."""
        for sbprty in (2, 3, 9):
            with self.subTest(sbprty=sbprty):
                r, starter, _e = _convert(self._deck(
                    pre=_pretensioner(sbprty=sbprty)))
                c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
                self.assertEqual(_col_i(c[2], 1, 10), 0, "no Sens_ID2")
                self.assertEqual(_col_i(c[2], 11, 20), 0, "no Tens_typ")
                self.assertEqual(_col_i(c[2], 41, 50), 0, "no Fct_ID3")
                self.assertTrue(_warns(r, f"*ELEMENT_SEATBELT_PRETENSIONER "
                                          f"{71}"))

    def test_two_pretensioners_do_not_poison_the_next_retractor(self):
        """dyna2rad's DEFECT B: its pretensioner SelectionRead is built once
        outside the retractor loop (convertelements.cxx:826) and never
        Restart()ed, so a retractor with no match eats the rest of the list.
        VERIFIED on its own probe v6/v7."""
        ret2 = (_retractor(sbrid=41, sbid=11, sbrnid=1,
                           sids=(61, 0, 0, 0),
                           card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))
                + _card(42, 6, 15, 62, 0, 0, 0, 0)
                + _card(0.0, 9.0, 910, 911, 5.0, 0, 0))
        pre = (_pretensioner(sbprid=72, sbrid=42, sbprty=6, ptlcid=912)
               + _pretensioner(sbprid=71, sbrid=41, sbprty=4, ptlcid=912))
        r, starter, _e = _convert(self._deck(ret=ret2, pre=pre))
        self.assertEqual(r.skipped_keywords, [])
        c41 = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        c42 = _cards(_block(starter, "/RETRACTOR/SPRING/42"))
        self.assertEqual(_col_i(c41[2], 11, 20), 2, "41 keeps SBPRTY 4")
        self.assertEqual(_col_i(c42[2], 11, 20), 3, "42 keeps SBPRTY 6")

    def test_a_second_pretensioner_on_one_retractor_is_named(self):
        pre = (_pretensioner(sbprid=71, sbprty=4)
               + _pretensioner(sbprid=72, sbprty=6))
        r, starter, _e = _convert(self._deck(pre=pre))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_i(c[2], 11, 20), 2, "the lowest SBPRID wins")
        self.assertTrue(_warns(r, "72"))

    def test_an_orphan_pretensioner_is_named(self):
        r, _s, _e = _convert(self._deck(pre=_pretensioner(sbrid=99)))
        self.assertTrue(_warns(r, "names no converted"))

    def test_dsid_lcfl_and_flopt_are_warn_dropped_by_name(self):
        r, _s, _e = _convert(self._deck(
            ret=_retractor(dsid=64,
                           card2=(0.003, 12.0, 910, 911, 6.25, 913, 2))))
        for name in ("DSID=64", "LCFL=913", "FLOPT=2"):
            with self.subTest(name=name):
                self.assertTrue(_warns(r, name))

    def test_a_shell_belt_retractor_is_dropped_by_name(self):
        """There is no /RETRACTOR/SHELL card in
        hm_cfg_files/config/CFG/radioss2022/SEATBELTS/ at all."""
        r, starter, _e = _convert(self._deck(ret=_retractor(sbrnid=-5)))
        self.assertNotIn("/RETRACTOR/", starter)
        self.assertTrue(_warns(r, "NO /RETRACTOR/SHELL"))

    def test_a_blank_card_two_does_not_swallow_the_next_retractor(self):
        """#119: every field on card 2 has a documented default, so an
        all-blank one is legal — and treating it as absent would read the next
        retractor's card 1 as this one's TDEL/PULL/LLCID."""
        ret = ("*ELEMENT_SEATBELT_RETRACTOR\n"
               + _card(41, 1, 11, 61, 0, 0, 0, 0)
               + "\n"
               + _card(42, 6, 15, 62, 0, 0, 0, 0)
               + _card(0.0, 9.0, 910, 911, 5.0, 0, 0))
        r, starter, _e = _convert(self._deck(ret=ret))
        self.assertEqual(r.skipped_keywords, [])
        self.assertEqual(len(_blocks(starter, "/RETRACTOR/SPRING/")), 2)
        c42 = _cards(_block(starter, "/RETRACTOR/SPRING/42"))
        self.assertEqual(_col_f(c42[0], 21, 40), 5.0, "42 keeps its LFED")
        c41 = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_f(c41[0], 21, 40), 0.0, "41 has no card 2")

    def test_a_pretensioner_card_two_with_a_blank_first_cell(self):
        """On SBPRTY 7/8/9 the legacy Keyword971 cfg writes card 2 as
        `CARD("          %10lg          %10lg", TIME, LMTFRC)` — field 0
        literally blank. RAW contiguity is what keeps the walk in phase."""
        pre = ("*ELEMENT_SEATBELT_PRETENSIONER\n"
               + _card(71, 4, 63, 0, 0, 0)
               + _card(None, 0.002, 912, 7777.0)
               + _card(72, 6, 63, 0, 0, 0)
               + _card(41, 0.001, 912, 5555.0))
        r, starter, _e = _convert(self._deck(pre=pre))
        self.assertEqual(r.skipped_keywords, [])
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_i(c[2], 11, 20), 3, "72 (SBPRTY 6) applied")
        self.assertEqual(_col_f(c[2], 21, 40), 5555.0)
        self.assertTrue(_warns(r, "names no converted"), "71 is orphaned")

    def test_a_missing_mouth_element_drops_the_retractor(self):
        r, starter, _e = _convert(self._deck(ret=_retractor(sbid=99)))
        self.assertNotIn("/RETRACTOR/", starter)
        self.assertTrue(_warns(r, "ERROR 2033"))

    def test_lmtpin_is_warn_dropped_by_name(self):
        r, _s, _e = _convert(self._deck(pre=_pretensioner(lmtpin=2.5)))
        self.assertTrue(_warns(r, "LMTPIN=2.5"))


# ═════════════════════════════════════════════════════════════════════════════
class TestSensors(unittest.TestCase):
    """*ELEMENT_SEATBELT_SENSOR -> /SENSOR/ACCE | /SENSOR/TIME | /SENSOR/DIST."""

    def _deck(self, body):
        return _deck(_BELT_PART, _SECTION, _mat(), _belts(),
                     "*ELEMENT_SEATBELT_SENSOR\n" + body)

    def test_type_one_becomes_an_acce_sensor_plus_an_accel(self):
        """sensor_acce.cfg's accel_ID is a mandatory object reference —
        Radioss has no accelerometer-free acceleration sensor."""
        r, starter, _e = _convert(self._deck(
            _card(61, 1, 0) + _card(10, 2, 12.5, 0.002)))
        self.assertEqual(r.skipped_keywords, [])
        c = _cards(_block(starter, "/SENSOR/ACCE/61"))
        self.assertEqual(_col_f(c[0], 1, 20), 0.0, "Tdelay")
        self.assertEqual(_col_i(c[1], 1, 10), 1, "Nacc")
        aid = _col_i(c[2], 1, 10)
        self.assertNotEqual(aid, 0)
        self.assertEqual(_col_s(c[2], 11, 20), "Y", "DOF 2 -> the STRING Y")
        self.assertEqual(_col_f(c[2], 21, 40), 12.5, "ACC -> Tomin")
        self.assertEqual(_col_f(c[2], 41, 60), 0.002, "ATIME -> Tmin")
        acc = _cards(_block(starter, f"/ACCEL/{aid}"))[0]
        self.assertEqual(_col_i(acc, 1, 10), 10, "the watched node")

    def test_the_dir_cell_is_a_string(self):
        """`%10s`, right-justified, X|Y|Z|XY|YZ|ZX|XYZ. The starter echoes it
        back as an integer, which is why writing 2 there looks plausible and
        is not read at all. dyna2rad writes an EMPTY string for any DOF
        outside 1..3 (convertelements.cxx:737-779)."""
        for dof, want in ((1, "X"), (2, "Y"), (3, "Z")):
            with self.subTest(dof=dof):
                _r, starter, _e = _convert(self._deck(
                    _card(61, 1, 0) + _card(10, dof, 12.5, 0.002)))
                c = _cards(_block(starter, "/SENSOR/ACCE/61"))
                self.assertEqual(_col_s(c[2], 11, 20), want)

    def test_type_three_becomes_a_time_sensor(self):
        _r, starter, _e = _convert(self._deck(_card(62, 3, 0) + _card(0.004)))
        c = _cards(_block(starter, "/SENSOR/TIME/62"))
        self.assertEqual(_col_f(c[0], 1, 20), 0.004)

    def test_type_four_reads_dmx_before_dmn(self):
        """The LS-DYNA card is `NID1 NID2 DMX DMN` — MAXIMUM first — while the
        Radioss card is `... Dmin Dmax`. A position-for-position copy swaps
        the two bounds and, with Dmin > Dmax, gives a sensor that can never
        fire."""
        _r, starter, _e = _convert(self._deck(
            _card(63, 4, 0) + _card(8, 9, 55.0, 5.0)))
        c = _cards(_block(starter, "/SENSOR/DIST/63"))
        self.assertEqual(_col_i(c[1], 1, 10), 8, "N1")
        self.assertEqual(_col_i(c[1], 11, 20), 9, "N2")
        self.assertEqual(_col_f(c[1], 21, 40), 5.0, "DMN -> Dmin")
        self.assertEqual(_col_f(c[1], 41, 60), 55.0, "DMX -> Dmax")
        self.assertEqual(_col_f(c[1], 61, 80), 0.0, "Tmin")
        self.assertEqual(_col_i(c[1], 81, 90), 0, "Dflag")

    def test_types_two_and_five_are_warn_dropped_by_name(self):
        """Radioss has no pull-out sensor of any kind. dyna2rad drops both
        silently and leaves the retractor's Sens_ID dangling."""
        for sbstyp in (2, 5):
            with self.subTest(sbstyp=sbstyp):
                r, starter, _e = _convert(self._deck(
                    _card(64, sbstyp, 0) + _card(41, 0.15, 0.001)))
                self.assertNotIn("/SENSOR/", starter)
                self.assertTrue(_warns(r, f"SBSTYP={sbstyp}"))

    def test_a_retractor_naming_a_dropped_sensor_gets_no_dangling_id(self):
        """The #106 rule reaches the device wiring too: a /RETRACTOR pointing
        at a sensor the deck does not define is refused by the starter."""
        body = ("*ELEMENT_SEATBELT_SENSOR\n"
                + _card(64, 2, 0) + _card(41, 0.15, 0.001))
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(), body,
            _retractor(sids=(64, 0, 0, 0),
                       card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_i(c[1], 1, 10), 0, "Sens_ID1 left at 0")
        self.assertTrue(_warns(r, "never locks"))

    def test_sbsfl_is_warn_dropped_by_name(self):
        r, _s, _e = _convert(self._deck(_card(62, 3, 1) + _card(0.004)))
        self.assertTrue(_warns(r, "SBSFL=1"))

    def test_a_blank_type_three_card_keeps_the_block_in_phase(self):
        """TIME = 0 (fire immediately) writes an entirely BLANK card 2, and
        skipping it would read the next sensor's card 1 as this one's TIME
        and then walk every remaining sensor one card out of phase (#119)."""
        body = (_card(62, 3, 0) + "\n"
                + _card(63, 4, 0) + _card(8, 9, 55.0, 5.0))
        r, starter, _e = _convert(self._deck(body))
        self.assertEqual(r.skipped_keywords, [])
        self.assertEqual(_col_f(_cards(_block(starter,
                                              "/SENSOR/TIME/62"))[0],
                                1, 20), 0.0)
        c = _cards(_block(starter, "/SENSOR/DIST/63"))
        self.assertEqual(_col_i(c[1], 1, 10), 8)

    def test_a_sensor_on_a_missing_node_is_dropped(self):
        r, starter, _e = _convert(self._deck(
            _card(63, 4, 0) + _card(8, 999, 55.0, 5.0)))
        self.assertNotIn("/SENSOR/DIST/", starter)
        self.assertTrue(_warns(r, "ERROR 78"))


# ═════════════════════════════════════════════════════════════════════════════
class TestAccelerometer(unittest.TestCase):
    """*ELEMENT_SEATBELT_ACCELEROMETER -> /ACCEL + /SKEW/MOV + /ADMAS/0."""

    def _deck(self, *rows):
        return _deck(_BELT_PART, _SECTION, _mat(), _belts(),
                     "*ELEMENT_SEATBELT_ACCELEROMETER\n"
                     + "".join(_card(*r) for r in rows))

    def test_the_triad_becomes_a_skew_and_the_accel_points_at_nid1(self):
        r, starter, _e = _convert(self._deck((81, 20, 21, 23, 0, 0, 0.0035)))
        self.assertEqual(r.skipped_keywords, [])
        acc = _cards(_block(starter, "/ACCEL/81"))[0]
        self.assertEqual(_col_i(acc, 1, 10), 20, "Node = NID1")
        skew_id = _col_i(acc, 11, 20)
        self.assertNotEqual(skew_id, 0)
        self.assertEqual(acc[20:30], " " * 10, "cols 21-30 are blank")
        self.assertEqual(_col_f(acc, 31, 50), 0.0, "Fcut, no filter")
        sk = _cards(_block(starter, f"/SKEW/MOV/{skew_id}"))[0]
        self.assertEqual(_col_i(sk, 1, 10), 20)
        self.assertEqual(_col_i(sk, 11, 20), 21)
        self.assertEqual(_col_i(sk, 21, 30), 23)

    def test_the_mass_is_split_over_the_triad(self):
        """LS-DYNA distributes MASS equally over NID1/NID2/NID3, and /ADMAS/0
        adds its value to EACH node of the group. dyna2rad puts the WHOLE mass
        on NID1 alone (convertelements.cxx:471-481), tripling it there."""
        _r, starter, _e = _convert(self._deck((81, 20, 21, 23, 0, 0, 0.003)))
        blk = _blocks(starter, "/ADMAS/0/")[-1]
        c = _cards(blk)[0]
        self.assertAlmostEqual(_col_f(c, 1, 20), 0.001, places=12)
        grnod = _col_i(c, 21, 30)
        rows = _cards(_block(starter, f"/GRNOD/NODE/{grnod}"))
        self.assertEqual([int(x) for x in rows[0].split()], [20, 21, 23])

    def test_no_mass_means_no_admas(self):
        """dyna2rad emits the /ADMAS even for MASS = 0 — a no-op card per
        accelerometer, which is what every corpus deck's blank cell would
        give."""
        _r, starter, _e = _convert(self._deck((81, 20, 21, 23, 0, 0, None)))
        self.assertNotIn("/ADMAS/", starter)
        self.assertIn("/ACCEL/81", starter)

    def test_a_partial_triad_gives_a_global_accel(self):
        _r, starter, _e = _convert(self._deck((81, 20, 21, 0, 0, 0, None)))
        acc = _cards(_block(starter, "/ACCEL/81"))[0]
        self.assertEqual(_col_i(acc, 1, 10), 20)
        self.assertEqual(_col_i(acc, 11, 20), 0, "no skew")

    def test_igrav_and_intopt_are_warn_dropped_by_name(self):
        """Both are dropped by dyna2rad silently."""
        r, _s, _e = _convert(self._deck((81, 20, 21, 23, 1, 1, None)))
        self.assertTrue(_warns(r, "IGRAV=1"))
        self.assertTrue(_warns(r, "INTOPT=1"))

    def test_a_missing_nid1_drops_the_card(self):
        r, starter, _e = _convert(self._deck((81, 999, 21, 23, 0, 0, None)))
        self.assertNotIn("/ACCEL/", starter)
        self.assertTrue(_warns(r, "NID1=999"))

    def test_the_accel_is_recorded_by_a_th_group(self):
        """An /ACCEL on its own writes NOTHING to the T01."""
        _r, starter, _e = _convert(self._deck((81, 20, 21, 23, 0, 0, None)))
        self.assertEqual(_th_ids(starter, "/TH/ACCEL/"), [81])

    def test_the_sensor_side_accel_is_not_recorded(self):
        """The /ACCEL a SBSTYP=1 sensor needs exists only to satisfy
        sensor_acce.cfg's mandatory accel_ID; recording it would add a channel
        the deck never asked for."""
        deck = _deck(_BELT_PART, _SECTION, _mat(), _belts(), _SENSORS,
                     "*ELEMENT_SEATBELT_ACCELEROMETER\n"
                     + _card(81, 20, 21, 23, 0, 0, None))
        _r, starter, _e = _convert(deck)
        self.assertEqual(len(_blocks(starter, "/ACCEL/")), 2)
        self.assertEqual(_th_ids(starter, "/TH/ACCEL/"), [81])


# ═════════════════════════════════════════════════════════════════════════════
class TestAnchorNodeSplit(unittest.TestCase):
    """The one STRUCTURAL difference between the two restraint models.

    LS-DYNA lets a device's node BE a belt node; Radioss requires a separate
    coincident one (``hm_read_retractor.F:341`` ERROR 2030, and ERROR 2029 /
    2004 for a slipring). MEASURED: copying SBRNID straight through — which is
    what dyna2rad does at ``convertelements.cxx:862`` — gives
    ``ERROR TERMINATION / 1 ERROR(S) / --- SEATBELTS`` on the first faithful
    probe deck.
    """

    def test_a_retractor_anchor_on_the_belt_is_split(self):
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(), _SENSORS,
            _retractor(sbrnid=1, sbid=11,
                       card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_i(c[0], 11, 20), 1, "the ORIGINAL is the anchor")
        rows = _cards(_block(starter, "/SPRING/900"))
        mouth = [x for x in rows if _col_i(x, 1, 10) == 11][0]
        twin = _col_i(mouth, 11, 20)
        self.assertNotEqual(twin, 1, "the BELT got the new node")
        self.assertEqual(_col_i(mouth, 21, 30), 2, "the far end is untouched")
        self.assertTrue(_warns(r, "ERROR 2030"))
        # the twin is a real /NODE at the same coordinates
        nodes = {_col_i(ln, 1, 10): ln
                 for ln in _cards(_block(starter, "/NODE"))}
        self.assertIn(twin, nodes)
        self.assertEqual(_col_f(nodes[twin], 11, 30),
                         _col_f(nodes[1], 11, 30))

    def test_an_anchor_already_off_the_belt_is_left_alone(self):
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(), _SENSORS,
            _retractor(sbrnid=7, sbid=13,
                       card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        c = _cards(_block(starter, "/RETRACTOR/SPRING/41"))
        self.assertEqual(_col_i(c[0], 11, 20), 7)
        rows = _cards(_block(starter, "/SPRING/900"))
        mouth = [x for x in rows if _col_i(x, 1, 10) == 13][0]
        self.assertEqual((_col_i(mouth, 11, 20), _col_i(mouth, 21, 30)),
                         (3, 4), "untouched")
        self.assertFalse(_warns(r, "were SPLIT"))

    def test_a_slipring_shared_node_is_split_in_both_elements(self):
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(),
            _slipring(sbrnid=3, onid=11, ltime=None,
                      card2=(0.55, 0, 12, 0.75, None, 920, 0))))
        c = _cards(_block(starter, "/SLIPRING/SPRING/51"))
        self.assertEqual(_col_i(c[0], 21, 30), 3, "the ORIGINAL is the anchor")
        rows = {_col_i(x, 1, 10): x
                for x in _cards(_block(starter, "/SPRING/900"))}
        twin = _col_i(rows[12], 21, 30)
        self.assertNotEqual(twin, 3)
        self.assertEqual(_col_i(rows[13], 11, 20), twin,
                         "BOTH strands moved to the twin, chain intact")
        self.assertTrue(_warns(r, "ERROR 2029"))

    def test_an_unsplittable_node_is_named_rather_than_cut(self):
        """More belt elements meet at the node than the device names, so
        splitting it would cut the webbing chain."""
        r, _s, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(),
            _slipring(sbid1=11, sbid2=12, sbrnid=2, onid=11, ltime=None,
                      card2=None)
            + "*ELEMENT_SEATBELT\n" + _belt_card(16, 900, 2, 6)))
        self.assertTrue(_warns(r, "could NOT be split"))


# ═════════════════════════════════════════════════════════════════════════════
class TestOutputs(unittest.TestCase):
    """*DATABASE_SBTOUT and *DATABASE_HISTORY_SEATBELT."""

    _FULL = None

    def _full(self, dt=1.0e-4, history="        11        12        13\n"):
        return _deck(
            _BELT_PART, _SECTION, _mat(), _belts(), _SENSORS,
            _slipring(),
            _retractor(card2=(0.0, 12.0, 910, 911, 6.25, 0, 0)),
            "*DATABASE_SBTOUT\n" + _card(dt, 1, 0, 1) if dt else "",
            "*DATABASE_HISTORY_SEATBELT\n" + history if history else "")

    def test_sbtout_emits_both_group_types(self):
        """LS-DYNA writes ONE sbtout file; Radioss splits it across two group
        types with separate channel sets. dyna2rad emits no /TH/RETRACTOR at
        all — grep over its whole tree returns zero hits."""
        r, starter, _e = _convert(self._full())
        self.assertEqual(r.skipped_keywords, [])
        sl = _block(starter, "/TH/SLIPRING/")
        rt = _block(starter, "/TH/RETRACTOR/")
        self.assertEqual(_cards(sl)[0].strip(), "DEF")
        self.assertEqual(_th_ids(starter, "/TH/SLIPRING/"), [51])
        self.assertEqual(_th_ids(starter, "/TH/RETRACTOR/"), [41])
        self.assertNotEqual(int(sl[0].rsplit("/", 1)[1]),
                            int(rt[0].rsplit("/", 1)[1]),
                            "different group ids: ERROR 79 otherwise")

    def test_the_th_group_ids_do_not_collide_with_the_history_counter(self):
        """The /TH group id namespace is GLOBAL ACROSS TYPES, so a
        /TH/SLIPRING/1 beside the /TH/SPRING/1 the history counter writes
        would be starter ERROR 79."""
        _r, starter, _e = _convert(self._full())
        ids = [int(b[0].rsplit("/", 1)[1])
               for b in _blocks(starter, "/TH/")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_sbtout_dt_joins_the_tfile_minimum(self):
        _r, _s, engine = _convert(self._full(dt=3.0e-5))
        tfile = [ln for ln in engine.splitlines()
                 if ln.strip() and not ln.startswith("#")]
        i = next(k for k, ln in enumerate(tfile) if ln.startswith("/TFILE"))
        self.assertAlmostEqual(float(tfile[i + 1]), 3.0e-5, places=12)

    def test_sbtout_without_a_device_emits_nothing_and_says_so(self):
        """#122: an output request whose channels are not in the T01 must not
        thicken it."""
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(),
            "*DATABASE_SBTOUT\n" + _card(1.0e-4, 1, 0, 1)))
        self.assertNotIn("/TH/SLIPRING", starter)
        self.assertNotIn("/TH/RETRACTOR", starter)
        self.assertIn("DATABASE_SBTOUT", dict(r.recognized_not_emitted))

    def test_history_seatbelt_routes_a_1d_belt_to_th_spring(self):
        _r, starter, _e = _convert(self._full())
        self.assertEqual(_th_ids(starter, "/TH/SPRING/"), [11, 12, 13])

    def test_history_seatbelt_splits_per_element(self):
        """dyna2rad decides from the FIRST listed element only
        (converttimehistory.cxx:312-340), so a card mixing a 1D shoulder belt
        with a 2D lap belt sends every id to one keyword."""
        deck = _deck(
            _BELT_PART, _SECTION, _mat(), _belts(),
            _SHELL_PART.replace("       800       800       900",
                                "       800       800       901"),
            _mat(kw="MAT_SEATBELT_2D").replace("*MAT_SEATBELT_2D\n       900",
                                               "*MAT_SEATBELT_2D\n       901"),
            "*ELEMENT_SEATBELT\n"
            + _belt_card(31, 800, 20, 21, 0, 0.0, 22, 23),
            "*DATABASE_HISTORY_SEATBELT\n" + "        11        31\n")
        r, starter, _e = _convert(deck)
        self.assertEqual(r.skipped_keywords, [])
        self.assertEqual(_th_ids(starter, "/TH/SPRING/"), [11])
        self.assertEqual(_th_ids(starter, "/TH/SHEL/"), [31])

    def test_the_seatbelt_history_group_takes_def_alone(self):
        """A /MAT/LAW119 shell does not stay a shell: the starter rewrites
        every /TH/SHEL that named those shells into a /TH/SPRING
        (hm_convert_2d_elements_seatbelt.F:135-141), and STRAIN is not a
        /TH/SPRING variable — ERROR 260."""
        deck = _deck(
            _SHELL_PART, _mat(kw="MAT_SEATBELT_2D"),
            "*ELEMENT_SEATBELT\n"
            + _belt_card(31, 800, 20, 21, 0, 0.0, 22, 23),
            "*DATABASE_HISTORY_SEATBELT\n" + "        31\n")
        _r, starter, _e = _convert(deck)
        self.assertEqual(_cards(_block(starter, "/TH/SHEL/"))[0].split(),
                         ["DEF"], "STRAIN would be ERROR 260 after the "
                                  "starter rewrites the group")

    def test_an_id_that_names_no_belt_element_is_screened_out(self):
        r, starter, _e = _convert(self._full(
            history="        11       999\n"))
        self.assertEqual(_th_ids(starter, "/TH/SPRING/"), [11])
        self.assertTrue(_warns(r, "ERROR 69"))


# ═════════════════════════════════════════════════════════════════════════════
class TestRegistries(unittest.TestCase):
    """The #120 registry audit: every walk that must now see a belt element."""

    def _state(self, deck_text):
        from k2rad.handlers import dispatch
        from k2rad.parser import parse_k_file
        from k2rad.state import ConversionState
        from k2rad.writer.assembly import build_starter
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(deck_text)
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        starter = build_starter(state)
        tmp.cleanup()
        return state, starter

    def test_belt_springs_are_spring_producer_eight(self):
        """state.spring_elem_ids answers "does a /SPRING with this id exist?",
        which is the question every /TH screen has to ask. Parsed out of the
        starter TEXT — an independent check, not the registry reporting on
        itself."""
        state, starter = self._state(_ref())
        emitted = set()
        for blk in _blocks(starter, "/SPRING/"):
            for ln in _cards(blk):
                emitted.add(_col_i(ln, 1, 10))
        self.assertEqual(emitted, {11, 12, 13, 14, 15})
        self.assertEqual(emitted, set(state.spring_elem_ids))

    def test_a_belt_eid_colliding_with_a_discrete_eid_is_reported(self):
        """LS-DYNA gives *ELEMENT_SEATBELT its own id namespace, so a belt
        element and a discrete spring may legally share an id in the source
        deck and both become /SPRING in the same one — starter ERROR 79."""
        deck = _deck(
            _BELT_PART, _SECTION, _mat(), _belts(),
            "*PART\ndisc\n       700       700       700\n"
            "*SECTION_DISCRETE\n" + _card(700, 0, 0.0, 0.0, 0.0, 0.0)
            + _card(0.0, 0.0)
            + "*MAT_SPRING_ELASTIC\n" + _card(700, 100.0)
            + "*ELEMENT_DISCRETE\n"
            + f"{11:>8d}{700:>8d}{7:>8d}{8:>8d}\n")
        r, _s, _e = _convert(deck)
        self.assertTrue(_warns(r, "*ELEMENT_SEATBELT (1D belt)"))

    def test_orphan_belt_elements_reach_the_mesh_loss_census(self):
        """assembly._warn_orphan_elements is the ONE place that answers "did
        the conversion drop any of my mesh?"."""
        deck = _deck(_BELT_PART, _SECTION, _mat(),
                     "*ELEMENT_SEATBELT\n" + _belt_card(11, 555, 1, 2))
        r, _s, _e = _convert(deck)
        self.assertTrue(_warns(r, "MESH LOSS"))
        self.assertTrue(_warns(r, "PID 555 (1 seatbelt)"))

    def test_belt_nodes_are_not_pinned_by_the_implicit_free_node_guard(self):
        """A 1D belt is a /SPRING with a real force-strain curve on it, so its
        nodes carry stiffness — a /BCS 111 111 there would weld the belt to
        ground and the occupant would never move."""
        deck = ("*KEYWORD\n" + _TERM
                + "*CONTROL_IMPLICIT_GENERAL\n" + _card(1, 1.0e-3)
                + _NODES + _BELT_PART + _SECTION + _mat() + _belts()
                + _CURVES + "*END\n")
        _r, starter, _e = _convert(deck)
        for blk in _blocks(starter, "/GRNOD/NODE/"):
            listed = {int(x) for ln in _cards(blk) for x in ln.split()}
            self.assertNotIn(2, listed, "an interior belt node")

    def test_belt_nodes_join_an_initial_velocity_generation_part_scope(self):
        """Leaving them out gives the belt zero initial velocity while the
        dummy it restrains has the sled's — the belt would be yanked taut at
        t=0."""
        deck = _deck(_BELT_PART, _SECTION, _mat(), _belts(),
                     "*INITIAL_VELOCITY_GENERATION\n"
                     + _card(900, 2, 0.0, 1000.0, 0.0, 0.0)
                     + _card(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        _r, starter, _e = _convert(deck)
        blk = _blocks(starter, "/INIVEL/")
        self.assertTrue(blk)
        grnod = _col_i(_cards(blk[0])[0], 21, 30)
        listed = {int(x)
                  for ln in _cards(_block(starter, f"/GRNOD/NODE/{grnod}"))
                  for x in ln.split()}
        self.assertTrue({1, 2, 3, 4, 5, 6} <= listed, listed)

    def test_device_nodes_survive_the_tet10_pruning_pass(self):
        """--tet10-to-tet4 drops nodes nothing references; a slipring
        anchorage, a sensor's watched node and an accelerometer triad are all
        named on emitted cards without owning an element."""
        deck = _deck(_BELT_PART, _SECTION, _mat(), _belts(), _SENSORS,
                     _slipring(),
                     "*ELEMENT_SEATBELT_ACCELEROMETER\n"
                     + _card(81, 20, 21, 23, 0, 0, None))
        _r, starter, _e = _convert(deck, tet10_to_tet4=True)
        nodes = {_col_i(ln, 1, 10) for ln in _cards(_block(starter, "/NODE"))}
        for n in (7, 11, 10, 8, 9, 20, 21, 23):
            with self.subTest(node=n):
                self.assertIn(n, nodes)

    def test_a_belt_only_deck_paces_the_time_step(self):
        """A /SPRING with stiffness and mass has a time step of its own
        (r2len3.F:182), so a belt-only restraint model must not get the flat
        "every element in this deck belongs to a rigid part"."""
        deck = _deck(_BELT_PART, _SECTION, _mat(), _belts(),
                     "*CONSTRAINED_JOINT_SPHERICAL\n" + _card(1, 2, 3, 4))
        r, _s, _e = _convert(deck)
        self.assertFalse(_warns(r, "belongs to a rigid part"))

    def test_the_belt_part_is_written_once(self):
        """A part claimed by the seatbelt writer must be skipped by the mesh
        writer AND by the element-free placeholder pass, or the starter
        answers ERROR 79 DUPLICATE ID."""
        _r, starter, _e = _convert(_ref())
        self.assertEqual(len(_blocks(starter, "/PART/900")), 1)
        self.assertEqual(len(_blocks(starter, "/PROP/TYPE23/900")), 1)
        self.assertNotIn("AutoPropShell_900", starter)

    def test_an_element_free_belt_part_still_gets_a_property(self):
        """A part id is addressable independently of its mesh, so it keeps its
        id, its title and its material rather than being dropped."""
        r, starter, _e = _convert(_deck(_BELT_PART, _SECTION, _mat()))
        self.assertEqual(r.skipped_keywords, [])
        self.assertIn("/PROP/TYPE23/900", starter)
        self.assertIn("/PART/900", starter)

    def test_a_belt_material_on_a_part_with_no_section_is_inert_not_lost(self):
        r, starter, _e = _convert(_deck(
            "*PART\nbelt\n       900       900       901\n", _SECTION,
            _mat(), _belts()))
        self.assertIn("/PROP/TYPE23/900", starter)
        self.assertTrue(_warns(r, "is not a *MAT_SEATBELT"))


# ═════════════════════════════════════════════════════════════════════════════
class TestGeometryChecks(unittest.TestCase):
    """The LS-DYNA element-length rules that carry over to Radioss verbatim."""

    def test_a_short_device_element_is_named(self):
        """"An element at a slipring or the mouth of a retractor must be
        > 1.6*LMIN" — Radioss enforces the same threshold through the LMIN
        clamps in material_flow.F:229-241, and below it the device remeshes
        on nearly every cycle."""
        r, _s, _e = _convert(_deck(_BELT_PART, _SECTION, _mat(lmin=80.0),
                                   _belts(), _slipring(ltime=None)))
        self.assertTrue(_warns(r, "1.6*LMIN"))

    def test_lfed_below_three_lmin_is_named(self):
        r, _s, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(lmin=3.0), _belts(), _SENSORS,
            _retractor(card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        self.assertTrue(_warns(r, "3*LMIN"))

    def test_an_element_in_two_devices_is_named(self):
        """ERROR 2006 ELEMENT ID nn CANNOT BE INITIALLY IN SEVERAL SLIPRINGS /
        RETRACTORS — the starter refuses the deck, so it is caught here where
        the two ids can be named."""
        r, _s, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(), _SENSORS,
            _slipring(sbid1=11, sbid2=12, sbrnid=7, ltime=None, card2=None),
            _retractor(sbid=11, sbrnid=1,
                       card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        self.assertTrue(_warns(r, "ERROR 2006"))

    def test_a_belt_declaring_an_unclaimed_retractor_is_named(self):
        """Radioss states the link ONCE, on /RETRACTOR/SPRING's EL_ID, so an
        element whose SBRID is not answered by an SBID converts as ordinary
        webbing — deployed from t=0 instead of stowed on the reel. dyna2rad
        cannot report this at all: it never reads the element's SBRID."""
        r, _s, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(sbrid=41), _SENSORS,
            _retractor(sbid=13, sbrnid=7,
                       card2=(0.0, 12.0, 910, 911, 6.25, 0, 0))))
        self.assertTrue(_warns(r, "declare SBRID"))


# ═════════════════════════════════════════════════════════════════════════════
class TestDispatch(unittest.TestCase):
    """#116: the spellings come from ONE source, and the parser and the offset
    table must cover the SAME set."""

    #: The complete R14.1/R17 dictionary for this family. ``_ID`` and
    #: ``_TITLE`` are stripped by ``parser._split_keyword`` into
    #: ``block.options`` and need no key of their own.
    KEYWORDS = (
        "ELEMENT_SEATBELT",
        "ELEMENT_SEATBELT_ACCELEROMETER",
        "ELEMENT_SEATBELT_SLIPRING",
        "ELEMENT_SEATBELT_RETRACTOR",
        "ELEMENT_SEATBELT_PRETENSIONER",
        "ELEMENT_SEATBELT_SENSOR",
        "SECTION_SEATBELT",
        "MAT_SEATBELT", "MAT_SEATBELT_2D", "MAT_B01", "MAT_B01_2D",
        "DATABASE_SBTOUT",
        "DATABASE_HISTORY_SEATBELT",
    )

    def test_every_spelling_dispatches(self):
        for kw in self.KEYWORDS:
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)

    def test_every_spelling_is_offsettable(self):
        """A spelling that dispatches but has no offset spec silently keeps
        its un-offset ids under an *INCLUDE_TRANSFORM — the belt then hangs
        off nodes that are no longer there."""
        for kw in self.KEYWORDS:
            with self.subTest(kw=kw):
                from k2rad.assembly import _NO_ID_KEYWORDS
                self.assertTrue(kw in _OFFSET_SPECS or kw in _NO_ID_KEYWORDS)

    def test_the_two_tables_are_generated_from_one_source(self):
        from k2rad.assembly import _SEATBELT_OFFSET_WALKERS
        from k2rad.handlers import _SEATBELT_SUBKEYWORDS
        self.assertEqual(set(_SEATBELT_SUBKEYWORDS),
                         set(_SEATBELT_OFFSET_WALKERS))
        for sfx in _SEATBELT_SUBKEYWORDS:
            kw = "ELEMENT_SEATBELT" + sfx
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
                self.assertIn(kw, _OFFSET_SPECS)

    def test_the_mat_keywords_come_from_one_source(self):
        from k2rad.handlers import _SEATBELT_MAT_KEYWORDS
        for kw in _SEATBELT_MAT_KEYWORDS:
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
                self.assertIn(kw, _OFFSET_SPECS)

    def test_the_2d_material_is_not_a_prefix_of_the_base_one(self):
        """*MAT_SEATBELT_2D must be registered EXACTLY: a prefix walk from
        MAT_SEATBELT would swallow it, and the two carry different cards."""
        self.assertIsNot(HANDLERS["MAT_SEATBELT"], None)
        self.assertIn("MAT_SEATBELT_2D", HANDLERS)

    def test_the_id_and_title_suffixes_are_stripped_by_the_parser(self):
        for kw in ("ELEMENT_SEATBELT_SLIPRING_ID", "SECTION_SEATBELT_TITLE",
                   "MAT_SEATBELT_TITLE", "DATABASE_HISTORY_SEATBELT_ID"):
            with self.subTest(kw=kw):
                from k2rad.parser import _split_keyword
                base, opts = _split_keyword("*" + kw)
                self.assertIn(base.lstrip("*"), HANDLERS)
                self.assertTrue({"ID", "TITLE"} & set(opts))

    def test_an_unknown_suffix_keeps_the_mesh(self):
        """An *ELEMENT_SEATBELT_<UNKNOWN> must not be routed into the belt
        reader by a prefix walk (its card layout would be read wrong), and the
        rest of the deck must still convert."""
        r, starter, _e = _convert(_deck(
            _BELT_PART, _SECTION, _mat(), _belts(),
            "*ELEMENT_SEATBELT_GUIDE\n" + _card(91, 11, 12, 7)))
        self.assertIn("ELEMENT_SEATBELT_GUIDE", r.skipped_keywords)
        self.assertEqual(len(_cards(_block(starter, "/SPRING/900"))), 5)


# ═════════════════════════════════════════════════════════════════════════════
class TestNoSeatbeltIsUnchanged(unittest.TestCase):
    """A deck without a seatbelt keyword must be BYTE-IDENTICAL to what master
    emits: every registry addition, every prepass and every section added by
    this batch is a no-op that draws no id on such a deck."""

    _PLAIN = """\
*KEYWORD
*CONTROL_TERMINATION
     0.020
*NODE
         1             0.0             0.0             0.0
         2           100.0             0.0             0.0
         3           100.0           100.0             0.0
         4             0.0           100.0             0.0
*PART
plate
         1         1         1
*SECTION_SHELL
         1         2
       1.0       1.0       1.0       1.0
*MAT_ELASTIC
         1   7.8E-09  210000.0       0.3
*ELEMENT_SHELL
       1       1       1       2       3       4
*DATABASE_HISTORY_SHELL
         1
*END
"""

    def test_the_starter_is_unchanged(self):
        r, starter, engine = _convert(self._PLAIN)
        self.assertEqual(r.skipped_keywords, [])
        for needle in ("/PROP/TYPE23", "/MAT/LAW114", "/MAT/LAW119",
                       "/SLIPRING", "/RETRACTOR", "/SENSOR", "/ACCEL",
                       "SEATBELT"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, starter)
                self.assertNotIn(needle, engine)

    def test_no_auto_id_is_drawn(self):
        """The first auto id must still be 90001 for the first consumer that
        asks: a prepass that drew one would shift every synthesized id on
        every existing deck."""
        from k2rad.handlers import dispatch
        from k2rad.parser import parse_k_file
        from k2rad.state import ConversionState
        from k2rad.writer.assembly import build_starter
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "d.k")
        with open(path, "w") as fh:
            fh.write(self._PLAIN)
        state = ConversionState()
        for block in parse_k_file(path):
            dispatch(block, state)
        build_starter(state)
        tmp.cleanup()
        self.assertEqual(state.seatbelt_prop_ids, {})
        self.assertEqual(state.slipring_ids, [])
        self.assertEqual(state.retractor_ids, [])
        self.assertEqual(state.th_accel_ids, [])
        self.assertEqual(state.sensor_ids, set())


# ═════════════════════════════════════════════════════════════════════════════
class TestProductionDeckShape(unittest.TestCase):
    """The Yaris / Camry shape: the ONLY seatbelt keyword either production
    deck in the corpus carries is *ELEMENT_SEATBELT_ACCELEROMETER, with
    IGRAV / INTOPT / MASS blank in every row and the two decks disagreeing
    about whether a `mass` column header is even written.

    On master both decks converted cleanly with the accelerometers in
    ``skipped_keywords`` and NO warning naming the lost channel — 11 (Yaris)
    and 9 (Camry) acceleration channels, which is exactly what the crash-test
    post-processing needs.
    """

    _DECK = """\
*KEYWORD
*CONTROL_TERMINATION
     0.020
*NODE
         1             0.0             0.0             0.0
         2           100.0             0.0             0.0
         3           100.0           100.0             0.0
         4             0.0           100.0             0.0
         5             0.0             0.0           100.0
         6           100.0             0.0           100.0
         7           100.0           100.0           100.0
         8             0.0           100.0           100.0
*PART
cube
         1         1         1
*SECTION_SOLID
         1         1
*MAT_ELASTIC
         1   7.8E-09  210000.0       0.3
*ELEMENT_SOLID
       1       1       1       2       3       4       5       6       7       8
*ELEMENT_SEATBELT_ACCELEROMETER
$#  sbacid      nid1      nid2      nid3     igrav    intopt
         1         1         2         4
         2         5         6         8
*DATABASE_SBTOUT
1.000E-04         3
*END
"""

    def test_both_accelerometers_convert_and_are_recorded(self):
        r, starter, _e = _convert(self._DECK)
        self.assertEqual(r.skipped_keywords, [])
        for aid, n1 in ((1, 1), (2, 5)):
            with self.subTest(accel=aid):
                c = _cards(_block(starter, f"/ACCEL/{aid}"))[0]
                self.assertEqual(_col_i(c, 1, 10), n1)
                self.assertNotEqual(_col_i(c, 11, 20), 0, "the triad skew")
        self.assertNotIn("/ADMAS/", starter, "blank MASS -> no card")
        self.assertEqual(_th_ids(starter, "/TH/ACCEL/"), [1, 2])

    def test_sbtout_with_no_device_is_a_note_not_a_warning(self):
        """73 of the 827 corpus decks carry a *DATABASE_ABSTAT with no airbag;
        the same boilerplate happens here, and it is a note."""
        r, starter, _e = _convert(self._DECK)
        self.assertNotIn("/TH/SLIPRING", starter)
        self.assertIn("DATABASE_SBTOUT", dict(r.recognized_not_emitted))


if __name__ == "__main__":
    unittest.main()
