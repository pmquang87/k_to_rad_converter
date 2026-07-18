"""Tests for the Johnson-Cook material batch:

  * *MAT_JOHNSON_COOK (MAT_015) → /MAT/LAW2 (PLAS_JOHNS): full field map incl.
    the thermal (m/TM/TR, rhoC_p = RO·CP) and rate (c/EPS0) cards, blank-field
    defaults (EPS0→1.0, E←2G(1+ν)), and the dropped-field warnings (PC on
    LAW2, VP, SPALL, C2, EFMIN).
  * EOS routing: a *PART EOSID (or — warned — a shared-id *EOS_* no part in
    the deck binds) reroutes MAT_015 to /MAT/LAW4 (HYD_JCOOK) + the /EOS
    rebound to the material id (dyna2rad's law choice), with PC→Pmin and
    TR→T0 (NOT dyna2rad's TR→Tmax quirk). EOS ownership: a same-id *EOS_*
    bound to ANOTHER material via a part EOSID is never hijacked (the JC mat
    stays LAW2 and the EOS pairs with its *MAT_NULL under the null's mid);
    a stray same-id *EOS_JWL never reroutes.
  * Failure: D1-D5 → /FAIL/JOHNSON (D3 forced negative, EPSILON_DOT_0 = EPS0,
    EROD→Ifail_so); DTF>0 → /FAIL/GENE1 dtmin, suppressing D1-D5 (LAW2 path
    only — the EOS path ignores DTF, both per dyna2rad).
  * *MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE (MAT_099) → /MAT/LAW2 +
    flat /FAIL/FLD at PSFAIL + A/E; EPPFR→EPS_p_max, min(SIGSAT,SIGMAX)→
    SIG_max0, Fsmooth=1; LCDM warned.
  * Numeric-alias (MAT_015/MAT_15/MAT_099/MAT_99/MAT_098/MAT_98) and _TITLE
    dispatch; no-regression of the MAT_098 sampled-LAW36 path and of the
    FS→/FAIL/JOHNSON single-criterion trailer.

Helpers modeled on tests/test_tables_rates.py.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.parser import parse_k_file
from k2rad.handlers import dispatch
from k2rad.state import ConversionState


def _convert(deck: str):
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


def _block_lines(starter: str, header_prefix: str):
    lines = starter.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(header_prefix))
    out = [lines[i + 1]]                          # title line
    for ln in lines[i + 2:]:
        if ln.startswith("/"):
            break
        if ln.startswith("#") or not ln.strip():
            continue
        out.append(ln)
    return out


def _floats(line: str, n: int):
    """The first n 20-wide float fields of a card line."""
    return [float(line[i:i + 20]) for i in range(0, 20 * n, 20)]


# Single-quad shell deck; {MAT} substituted per test.
SHELL_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "*ELEMENT_SHELL\n"
    "       1       1       1       2       3       4\n"
    "*PART\n"
    "shell\n"
    "         1         1         1\n"
    "*SECTION_SHELL\n"
    "         1         2         0         3\n"
    "       0.5       0.5       0.5       0.5\n"
    "{MAT}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

# Single-brick solid deck with a *PART EOSID slot ({EOSID}, blank = none).
SOLID_DECK = (
    "*KEYWORD\n"
    "*NODE\n"
    "       1             0.0             0.0             0.0\n"
    "       2             1.0             0.0             0.0\n"
    "       3             1.0             1.0             0.0\n"
    "       4             0.0             1.0             0.0\n"
    "       5             0.0             0.0             1.0\n"
    "       6             1.0             0.0             1.0\n"
    "       7             1.0             1.0             1.0\n"
    "       8             0.0             1.0             1.0\n"
    "*ELEMENT_SOLID\n"
    "       1       1       1       2       3       4       5       6       7       8\n"
    "*PART\n"
    "solid\n"
    "         1         1         1{EOSID}\n"
    "*SECTION_SOLID\n"
    "         1         1\n"
    "{MAT}"
    "*CONTROL_TERMINATION\n"
    "       1.0\n"
    "*END\n"
)

# Full-featured MAT_015: thermal + rate + PC + D1-D5 + EFMIN (D3 positive on
# purpose — the emitted /FAIL/JOHNSON D3 must come out negative).
MAT15_FULL = (
    "*MAT_JOHNSON_COOK\n"
    "         1 7.85E-9   80000.0  210000.0       0.3       0.0       0.0       0.0\n"
    "     350.0     275.0      0.36     0.022       1.1    1800.0     293.0      5E-4\n"
    "     4.5E8   -1200.0       2.0       0.0      0.05      3.44       2.1     0.002\n"
    "      0.61       0.0       0.0      1E-6\n"
)

GRUNEISEN_7 = (
    "*EOS_GRUNEISEN\n"
    "         7    4569.0      1.49       0.0       0.0      1.93       0.5       0.0\n"
)

MAT99_FULL = (
    "*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE\n"
    "         1 7.85E-9  210000.0       0.3       0.0       0.8         9\n"
    "     350.0     275.0      0.36     0.022      0.25     500.0\n"
)

JWL_1 = (
    "*EOS_JWL\n"
    "         1     371.2      3.23      4.15      0.95       0.3       7.0"
    "       1.0\n"
)


def _solid_deck_multi(parts, mat: str) -> str:
    """A one-hex-per-part solid deck: parts = [(pid, mid, eosid), ...] with
    eosid 0 meaning a blank *PART EOSID field."""
    nodes = (
        "*NODE\n"
        "       1             0.0             0.0             0.0\n"
        "       2             1.0             0.0             0.0\n"
        "       3             1.0             1.0             0.0\n"
        "       4             0.0             1.0             0.0\n"
        "       5             0.0             0.0             1.0\n"
        "       6             1.0             0.0             1.0\n"
        "       7             1.0             1.0             1.0\n"
        "       8             0.0             1.0             1.0\n"
    )
    elems = "*ELEMENT_SOLID\n" + "".join(
        f"{eid:>8}{pid:>8}       1       2       3       4       5       6"
        "       7       8\n"
        for eid, (pid, _, _) in enumerate(parts, 1))
    cards = "".join(
        f"*PART\np{pid}\n{pid:>10}         1{mid:>10}"
        + (f"{eosid:>10}" if eosid else "") + "\n"
        for pid, mid, eosid in parts)
    return ("*KEYWORD\n" + nodes + elems + cards
            + "*SECTION_SOLID\n         1         1\n" + mat
            + "*CONTROL_TERMINATION\n       1.0\n*END\n")


# /MAT/LAW2 block line indices (index 0 is the title line).
_RHO, _EC, _ABN, _RATE, _THERM = 1, 2, 3, 4, 5


class Mat015LawTwoTests(unittest.TestCase):
    """MAT_015 without an EOS → /MAT/LAW2, full field map."""

    def setUp(self):
        self.state = _dispatch(SHELL_DECK.format(MAT=MAT15_FULL))
        self.result, self.starter = _convert(SHELL_DECK.format(MAT=MAT15_FULL))

    def test_handler_stores_johnson_cook(self):
        m = self.state.mat_johnson_cook[1]
        self.assertAlmostEqual(m.rho, 7.85e-9)
        self.assertAlmostEqual(m.e, 210000.0)     # E given → G ignored
        self.assertAlmostEqual(m.nu, 0.3)
        self.assertAlmostEqual(m.a, 350.0)
        self.assertAlmostEqual(m.b, 275.0)
        self.assertAlmostEqual(m.n, 0.36)
        self.assertAlmostEqual(m.c, 0.022)
        self.assertAlmostEqual(m.epso, 5e-4)
        self.assertAlmostEqual(m.m, 1.1)
        self.assertAlmostEqual(m.tmelt, 1800.0)
        self.assertAlmostEqual(m.tref, 293.0)
        self.assertAlmostEqual(m.rhocp, 7.85e-9 * 4.5e8)   # per-volume ρ·Cp
        self.assertAlmostEqual(m.pc, -1200.0)
        self.assertAlmostEqual(m.d1, 0.05)
        self.assertAlmostEqual(m.d2, 3.44)
        self.assertAlmostEqual(m.d3, 2.1)
        self.assertAlmostEqual(m.d4, 0.002)
        self.assertAlmostEqual(m.d5, 0.61)
        self.assertAlmostEqual(m.efmin, 1e-6)
        self.assertFalse(m.ortho)

    def test_emits_law2_not_law36_or_law4(self):
        self.assertIn("/MAT/LAW2/1", self.starter)
        self.assertNotIn("/MAT/LAW4/1", self.starter)
        self.assertNotIn("/MAT/LAW36/1", self.starter)

    def test_law2_full_field_map(self):
        d = _block_lines(self.starter, "/MAT/LAW2/1")
        self.assertAlmostEqual(_floats(d[_RHO], 1)[0], 7.85e-9)
        # E / Nu / Iflag (Iflag=0 = classic a,b,n input)
        self.assertEqual(_floats(d[_EC], 2), [210000.0, 0.3])
        self.assertEqual(int(d[_EC][40:50]), 0)
        # a / b / n / EPS_p_max / SIG_max0 (blank → starter 1e30 defaults)
        self.assertEqual(_floats(d[_ABN], 5), [350.0, 275.0, 0.36, 0.0, 0.0])
        # c / EPS_DOT_0 / ICC / Fsmooth / F_cut / Chard
        self.assertEqual(_floats(d[_RATE], 2), [0.022, 5e-4])
        self.assertEqual(int(d[_RATE][40:50]), 0)      # ICC blank → starter 1
        self.assertEqual(int(d[_RATE][50:60]), 0)      # Fsmooth off (MAT_015)
        self.assertEqual(_floats(d[_RATE][60:], 2), [0.0, 0.0])
        # m / T_melt / rhoC_p / T_r
        vals = _floats(d[_THERM], 4)
        self.assertEqual(vals[:2], [1.1, 1800.0])
        self.assertAlmostEqual(vals[2], 3.5325)        # 7.85e-9 * 4.5e8
        self.assertEqual(vals[3], 293.0)

    def test_d_params_emit_fail_johnson(self):
        self.assertIn("/FAIL/JOHNSON/1", self.starter)
        d = _block_lines(self.starter, "/FAIL/JOHNSON/1")
        # _block_lines treats the first comment as "title": data rows at 1..2
        self.assertEqual(_floats(d[1], 5), [0.05, 3.44, -2.1, 0.002, 0.61])
        self.assertAlmostEqual(_floats(d[2], 1)[0], 5e-4)   # EPSILON_DOT_0=EPS0
        self.assertEqual(int(d[2][20:30]), 2)               # Ifail_sh
        self.assertEqual(int(d[2][30:40]), 1)               # Ifail_so (EROD=0)
        self.assertNotIn("/FAIL/GENE1/1", self.starter)

    def test_pc_dropped_with_warning_on_law2(self):
        self.assertTrue(any("PC=-1200" in w and "LAW2" in w
                            for w in self.result.warnings))

    def test_efmin_dropped_with_warning(self):
        self.assertTrue(any("EFMIN=1e-06" in w for w in self.result.warnings))

    def test_damg_anim_requested(self):
        # The engine file lives in _convert's temp dir (already cleaned up),
        # so convert again with a kept directory.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.k")
            with open(path, "w") as fh:
                fh.write(SHELL_DECK.format(MAT=MAT15_FULL))
            result = convert(path, write_log=False)
            with open(result.engine_path) as fh:
                self.assertIn("/ANIM/ELEM/DAMG", fh.read())


class Mat015DefaultsTests(unittest.TestCase):
    """Blank-field handling: EPS0→1.0, E←2G(1+ν), no failure → no /FAIL."""

    MAT = (
        "*MAT_JOHNSON_COOK\n"
        "         1 7.85E-9   80000.0                 0.3\n"
        "     350.0     275.0      0.36     0.022\n"
    )

    def setUp(self):
        self.result, self.starter = _convert(SHELL_DECK.format(MAT=self.MAT))

    def test_e_falls_back_to_shear_modulus(self):
        d = _block_lines(self.starter, "/MAT/LAW2/1")
        # E = 2G(1+nu) = 2 * 80000 * 1.3
        self.assertAlmostEqual(_floats(d[_EC], 2)[0], 208000.0)

    def test_blank_epso_takes_lsdyna_default_one(self):
        d = _block_lines(self.starter, "/MAT/LAW2/1")
        self.assertEqual(_floats(d[_RATE], 2), [0.022, 1.0])

    def test_blank_thermal_left_zero_for_starter_defaults(self):
        d = _block_lines(self.starter, "/MAT/LAW2/1")
        self.assertEqual(_floats(d[_THERM], 4), [0.0, 0.0, 0.0, 0.0])

    def test_no_failure_fields_no_fail_cards(self):
        self.assertNotIn("/FAIL/", self.starter)

    def test_erod_nonzero_sets_ifail_so_2(self):
        mat = (
            "*MAT_JOHNSON_COOK\n"
            "         1 7.85E-9       0.0  210000.0       0.3\n"
            "     350.0     275.0      0.36\n"
            "       0.0       0.0       0.0       0.0      0.05\n"
            "       0.0       0.0       1.0\n"
        )
        _, starter = _convert(SHELL_DECK.format(MAT=mat))
        d = _block_lines(starter, "/FAIL/JOHNSON/1")
        self.assertEqual(int(d[2][30:40]), 2)               # EROD≠0 → keep solid


class Mat015Law4Tests(unittest.TestCase):
    """*PART EOSID → /MAT/LAW4 + /EOS rebound to the material id."""

    def setUp(self):
        deck = SOLID_DECK.format(MAT=MAT15_FULL + GRUNEISEN_7,
                                 EOSID="         7")
        self.result, self.starter = _convert(deck)

    def test_routes_law4_not_law2(self):
        self.assertIn("/MAT/LAW4/1", self.starter)
        self.assertNotIn("/MAT/LAW2/1", self.starter)

    def test_eos_rebound_to_material_id(self):
        self.assertIn("/EOS/GRUNEISEN/1", self.starter)
        self.assertNotIn("/EOS/GRUNEISEN/7", self.starter)   # not a fluid orphan
        self.assertNotIn("/MAT/HYD_VISC/7", self.starter)    # no LAW6 carrier

    def test_law4_field_map(self):
        d = _block_lines(self.starter, "/MAT/LAW4/1")
        self.assertAlmostEqual(_floats(d[1], 1)[0], 7.85e-9)         # RHO_I
        self.assertEqual(_floats(d[2], 2), [210000.0, 0.3])          # E nu
        self.assertEqual(_floats(d[3], 5), [350.0, 275.0, 0.36, 0.0, 0.0])
        self.assertEqual(_floats(d[4], 1), [-1200.0])                # Pmin = PC
        # C EPS_DOT_0 M Tmelt Tmax — Tmax stays 0 (NOT dyna2rad's TR→Tmax)
        self.assertEqual(_floats(d[5], 5), [0.022, 5e-4, 1.1, 1800.0, 0.0])
        # RHOCP ... T0: TR lands in the initial temperature
        self.assertAlmostEqual(_floats(d[6], 1)[0], 3.5325)
        self.assertEqual(float(d[6][60:80]), 293.0)

    def test_d_params_still_emit_fail_johnson(self):
        self.assertIn("/FAIL/JOHNSON/1", self.starter)
        d = _block_lines(self.starter, "/FAIL/JOHNSON/1")
        self.assertEqual(_floats(d[1], 5), [0.05, 3.44, -2.1, 0.002, 0.61])

    def test_positive_pc_forced_negative(self):
        mat = MAT15_FULL.replace("   -1200.0", "    1200.0")
        deck = SOLID_DECK.format(MAT=mat + GRUNEISEN_7, EOSID="         7")
        _, starter = _convert(deck)
        d = _block_lines(starter, "/MAT/LAW4/1")
        self.assertEqual(_floats(d[4], 1), [-1200.0])

    def test_dtf_ignored_on_eos_path(self):
        mat = MAT15_FULL.replace(
            "       0.3       0.0       0.0       0.0\n",
            "       0.3    2.5E-7       0.0       0.0\n")
        deck = SOLID_DECK.format(MAT=mat + GRUNEISEN_7, EOSID="         7")
        result, starter = _convert(deck)
        self.assertNotIn("/FAIL/GENE1/1", starter)
        self.assertIn("/FAIL/JOHNSON/1", starter)            # D1-D5 still apply
        self.assertTrue(any("DTF=2.5e-07 is ignored" in w
                            for w in result.warnings))

    def test_shared_id_eos_also_routes_law4(self):
        # No *PART EOSID anywhere; the *EOS_* shares the material id (k2rad's
        # pairing convention) — routed to LAW4 WITH a warning (in LS-DYNA an
        # unreferenced EOS is inert and dyna2rad would keep PLAS_JOHNS).
        eos1 = GRUNEISEN_7.replace("         7", "         1", 1)
        deck = SOLID_DECK.format(MAT=MAT15_FULL + eos1, EOSID="")
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW4/1", starter)
        self.assertIn("/EOS/GRUNEISEN/1", starter)
        self.assertNotIn("/MAT/HYD_VISC/1", starter)
        self.assertTrue(any("shared-id pairing convention" in w
                            for w in result.warnings))

    def test_missing_eos_card_still_routes_law4_with_warning(self):
        # dyna2rad routes on the *PART EOSID alone, even when the EOS card is
        # absent/unsupported — the material still becomes LAW4 (warned).
        deck = SOLID_DECK.format(MAT=MAT15_FULL, EOSID="         5")
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW4/1", starter)
        self.assertTrue(any("EOSID 5" in w and "WITHOUT an /EOS" in w
                            for w in result.warnings))


class Mat015EosOwnershipTests(unittest.TestCase):
    """The shared-id LAW4 fallback must not hijack an *EOS_* owned elsewhere
    (dyna2rad routes SOLELY on the *PART EOSID)."""

    def test_same_id_eos_bound_to_other_material_stays_law2(self):
        # JC mid=1 with no part EOSID; *EOS_GRUNEISEN 1 legitimately bound to
        # the *MAT_NULL mid=2 fluid via part 2's EOSID. The JC material must
        # stay /MAT/LAW2 (dyna2rad: PLAS_JOHNS) and the EOS must pair with
        # the null — re-emitted under the null's mid, not hijacked.
        eos1 = GRUNEISEN_7.replace("         7", "         1", 1)
        mat = MAT15_FULL + "*MAT_NULL\n         2   1.0E-9\n" + eos1
        deck = _solid_deck_multi([(1, 1, 0), (2, 2, 1)], mat)
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW2/1", starter)
        self.assertNotIn("/MAT/LAW4/1", starter)
        self.assertIn("/MAT/HYD_VISC/2", starter)      # the null is the carrier
        self.assertIn("/EOS/GRUNEISEN/2", starter)     # rebound to the null mid
        self.assertNotIn("/EOS/GRUNEISEN/1", starter)
        self.assertNotIn("/MAT/HYD_VISC/1", starter)   # no same-id orphan
        self.assertNotIn("/MAT/VOID/2", starter)       # not double-emitted
        self.assertTrue(any("bound to *MAT_NULL 2" in w
                            for w in result.warnings))

    def test_stray_same_id_jwl_stays_law2(self):
        # A same-id *EOS_JWL with no part binding and no explosive pair is
        # inert in LS-DYNA — the JC material must stay LAW2 (previously it
        # became a LAW4 with NO /EOS = undefined volumetric response).
        deck = SOLID_DECK.format(MAT=MAT15_FULL + JWL_1, EOSID="")
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW2/1", starter)
        self.assertNotIn("/MAT/LAW4/1", starter)
        self.assertTrue(any("no companion *MAT_HIGH_EXPLOSIVE_BURN" in w
                            for w in result.warnings))

    def test_jwl_attached_via_part_eosid_routes_law4_without_eos(self):
        # dyna2rad routes on the part EOSID alone, whatever the EOS type: a
        # part-bound JWL still means LAW4, but JWL cannot ride on it — warned,
        # and the orphan-JWL warning must NOT also fire (it was consumed).
        jwl9 = JWL_1.replace("         1", "         9", 1)
        deck = SOLID_DECK.format(MAT=MAT15_FULL + jwl9, EOSID="         9")
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW4/1", starter)
        self.assertNotIn("/EOS/", starter)
        self.assertTrue(any("cannot bind to /MAT/LAW4" in w
                            for w in result.warnings))
        self.assertFalse(any("no companion *MAT_HIGH_EXPLOSIVE_BURN" in w
                             for w in result.warnings))

    def test_parts_without_eosid_dragged_onto_law4_warn(self):
        # One mid shared by an EOS-attached part and a plain part: single
        # LAW4 for both (Radioss: one law per mat id) — warned; dyna2rad
        # would duplicate the material and keep PLAS_JOHNS for part 2.
        deck = _solid_deck_multi([(1, 1, 7), (2, 1, 0)],
                                 MAT15_FULL + GRUNEISEN_7)
        result, starter = _convert(deck)
        self.assertIn("/MAT/LAW4/1", starter)
        self.assertNotIn("/MAT/LAW2/1", starter)
        self.assertTrue(any("part(s) [2]" in w and "WITHOUT an EOSID" in w
                            for w in result.warnings))


class Mat015MultiMaterialTests(unittest.TestCase):
    """Several Johnson-Cook materials in ONE deck: distinct /MAT, /FAIL and
    auto-/FUNCT ids (guards the per-material id-allocation paths)."""

    MAT2_PLAIN = (
        "*MAT_JOHNSON_COOK\n"
        "         2 7.85E-9       0.0  210000.0       0.3\n"
        "     300.0     200.0       0.3     0.011\n"
        "       0.0       0.0       0.0       0.0      0.12\n"
    )

    def test_law4_law2_and_mat099_coexist(self):
        mat99_3 = MAT99_FULL.replace("         1", "         3", 1)
        mats = MAT15_FULL + GRUNEISEN_7 + self.MAT2_PLAIN + mat99_3
        deck = _solid_deck_multi([(1, 1, 7), (2, 2, 0), (3, 3, 0)], mats)
        _, starter = _convert(deck)
        self.assertIn("/MAT/LAW4/1", starter)
        self.assertIn("/EOS/GRUNEISEN/1", starter)
        self.assertIn("/FAIL/JOHNSON/1", starter)
        self.assertIn("/MAT/LAW2/2", starter)
        self.assertIn("/FAIL/JOHNSON/2", starter)
        self.assertIn("/MAT/LAW2/3", starter)
        self.assertIn("/FAIL/FLD/3", starter)
        self.assertNotIn("/MAT/HYD_VISC/7", starter)   # EOS consumed, no orphan

    def test_two_mat099_get_distinct_fld_curves(self):
        mat99_3 = MAT99_FULL.replace("         1", "         3", 1)
        mat99_4 = MAT99_FULL.replace("         1", "         4", 1)
        deck = _solid_deck_multi([(1, 3, 0), (2, 4, 0)], mat99_3 + mat99_4)
        _, starter = _convert(deck)
        fid3 = int(_block_lines(starter, "/FAIL/FLD/3")[1][0:10])
        fid4 = int(_block_lines(starter, "/FAIL/FLD/4")[1][0:10])
        self.assertNotEqual(fid3, fid4)
        self.assertIn(f"/FUNCT/{fid3}", starter)
        self.assertIn(f"/FUNCT/{fid4}", starter)


class Mat015DropWarningTests(unittest.TestCase):
    """Every dropped MAT_015 field warns: VP/RATEOP, SPALL, IT, C2, NUMINT."""

    MAT = (
        "*MAT_JOHNSON_COOK\n"
        "         1 7.85E-9       0.0  210000.0       0.3       0.0         1"
        "       2.0\n"
        "     350.0     275.0      0.36     0.022\n"
        "       0.0       0.0       1.0       1.0\n"
        "       0.0       5.0       0.0       0.0       2.0\n"
    )

    def setUp(self):
        self.result, self.starter = _convert(SHELL_DECK.format(MAT=self.MAT))

    def test_vp_warned_with_rateop(self):
        self.assertTrue(any("VP=1" in w and "RATEOP=2" in w
                            for w in self.result.warnings))

    def test_spall_warned(self):
        self.assertTrue(any("SPALL=1" in w for w in self.result.warnings))

    def test_it_warned(self):
        self.assertTrue(any("IT=1" in w for w in self.result.warnings))

    def test_c2_warned(self):
        self.assertTrue(any("C2/P=5" in w for w in self.result.warnings))

    def test_numint_warned(self):
        self.assertTrue(any("NUMINT=2" in w for w in self.result.warnings))


class Mat015DtfTests(unittest.TestCase):
    """DTF>0 on the plain (LAW2) path → /FAIL/GENE1 dtmin, D1-D5 suppressed."""

    MAT = (
        "*MAT_JOHNSON_COOK\n"
        "         1 7.85E-9       0.0  210000.0       0.3    2.5E-7\n"
        "     350.0     275.0      0.36     0.022\n"
        "       0.0       0.0       0.0       0.0      0.05\n"
    )

    def setUp(self):
        self.result, self.starter = _convert(SHELL_DECK.format(MAT=self.MAT))

    def test_gene1_with_dtmin_emitted(self):
        self.assertIn("/FAIL/GENE1/1", self.starter)
        body = self.starter.split("/FAIL/GENE1/1", 1)[1].splitlines()
        card1 = body[2]                       # header, comment, card 1
        self.assertAlmostEqual(float(card1[80:100]), 2.5e-7)   # dtmin
        self.assertEqual(_floats(card1, 4), [0.0, 0.0, 0.0, 0.0])

    def test_d_params_suppressed(self):
        self.assertNotIn("/FAIL/JOHNSON/1", self.starter)
        self.assertTrue(any("takes priority over D1-D5" in w
                            for w in self.result.warnings))

    def test_dtf_merges_into_existing_mat_add_erosion_gene1(self):
        deck = SHELL_DECK.format(MAT=self.MAT + (
            "*MAT_ADD_EROSION\n"
            "         1\n"
            "       0.0       0.0       0.0       1.2\n"))
        result, starter = _convert(deck)
        self.assertEqual(starter.count("/FAIL/GENE1/1"), 1)
        body = starter.split("/FAIL/GENE1/1", 1)[1].splitlines()
        self.assertAlmostEqual(float(body[2][80:100]), 2.5e-7)   # dtmin merged
        self.assertAlmostEqual(float(body[6][40:60]), 1.2)       # MXEPS kept
        self.assertTrue(any("merged" in w and "GENE1" in w
                            for w in result.warnings))


class Mat099Tests(unittest.TestCase):
    """MAT_099 → /MAT/LAW2 + flat /FAIL/FLD at PSFAIL + A/E."""

    def setUp(self):
        self.state = _dispatch(SHELL_DECK.format(MAT=MAT99_FULL))
        self.result, self.starter = _convert(SHELL_DECK.format(MAT=MAT99_FULL))

    def test_handler_stores_ortho_variant(self):
        m = self.state.mat_johnson_cook[1]
        self.assertTrue(m.ortho)
        self.assertAlmostEqual(m.eps_p_max, 0.8)        # EPPFR
        self.assertAlmostEqual(m.sig_max0, 500.0)       # SIGSAT blank → SIGMAX
        self.assertEqual(m.fsmooth, 1)
        self.assertAlmostEqual(m.psfail, 0.25)
        self.assertAlmostEqual(m.epso, 1.0)             # blank → LS-DYNA 1.0

    def test_law2_carries_eppfr_and_cap(self):
        d = _block_lines(self.starter, "/MAT/LAW2/1")
        self.assertEqual(_floats(d[_ABN], 5), [350.0, 275.0, 0.36, 0.8, 500.0])
        self.assertEqual(int(d[_RATE][50:60]), 1)       # Fsmooth=1 (dyna2rad)
        self.assertEqual(_floats(d[_THERM], 4), [0.0, 0.0, 0.0, 0.0])

    def test_psfail_emits_flat_fld(self):
        self.assertIn("/FAIL/FLD/1", self.starter)
        d = _block_lines(self.starter, "/FAIL/FLD/1")
        fid = int(d[1][0:10])
        self.assertEqual(int(d[1][10:20]), 2)           # Ifail_sh
        fn = _block_lines(self.starter, f"/FUNCT/{fid}")
        limit = 0.25 + 350.0 / 210000.0
        pts = [_floats(fn[1], 2), _floats(fn[2], 2)]
        self.assertAlmostEqual(pts[0][0], -1.0)
        self.assertAlmostEqual(pts[0][1], limit, places=6)
        self.assertAlmostEqual(pts[1][0], 1.0)
        self.assertAlmostEqual(pts[1][1], limit, places=6)

    def test_sig_max0_is_min_of_sigmax_sigsat(self):
        mat = MAT99_FULL.replace(
            "      0.25     500.0\n", "      0.25     500.0     400.0\n")
        state = _dispatch(SHELL_DECK.format(MAT=mat))
        self.assertAlmostEqual(state.mat_johnson_cook[1].sig_max0, 400.0)

    def test_no_psfail_no_fld(self):
        mat = (
            "*MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE\n"
            "         1 7.85E-9  210000.0       0.3\n"
            "     350.0     275.0      0.36\n"
        )
        _, starter = _convert(SHELL_DECK.format(MAT=mat))
        self.assertNotIn("/FAIL/", starter)

    def test_lcdm_warned(self):
        self.assertTrue(any("LCDM=9" in w for w in self.result.warnings))


class AliasDispatchTests(unittest.TestCase):
    def test_mat015_numeric_aliases_not_skipped(self):
        for kw in ("MAT_015", "MAT_15"):
            deck = SHELL_DECK.format(
                MAT=MAT15_FULL.replace("MAT_JOHNSON_COOK", kw))
            state = _dispatch(deck)
            self.assertIn(1, state.mat_johnson_cook, kw)
            self.assertNotIn(kw, state.skipped_keywords)

    def test_mat015_title_dispatch(self):
        deck = SHELL_DECK.format(MAT=MAT15_FULL.replace(
            "*MAT_JOHNSON_COOK\n", "*MAT_JOHNSON_COOK_TITLE\nsteel jc\n"))
        state = _dispatch(deck)
        self.assertEqual(state.mat_johnson_cook[1].title, "steel jc")
        self.assertAlmostEqual(state.mat_johnson_cook[1].a, 350.0)

    def test_mat099_numeric_aliases(self):
        for kw in ("MAT_099", "MAT_99"):
            deck = SHELL_DECK.format(MAT=MAT99_FULL.replace(
                "MAT_SIMPLIFIED_JOHNSON_COOK_ORTHOTROPIC_DAMAGE", kw))
            state = _dispatch(deck)
            self.assertTrue(state.mat_johnson_cook[1].ortho, kw)

    def test_mat098_numeric_aliases_reach_law36_path(self):
        mat98 = (
            "*MAT_098\n"
            "         1 7.85E-9  210000.0       0.3\n"
            "     350.0     275.0      0.36     0.022\n"
        )
        for kw in ("MAT_098", "MAT_98"):
            state = _dispatch(SHELL_DECK.format(
                MAT=mat98.replace("MAT_098", kw)))
            self.assertIn(1, state.mat_plas_tab, kw)      # sampled LAW36 path
            self.assertNotIn(1, state.mat_johnson_cook)


class NoRegressionTests(unittest.TestCase):
    def test_mat098_keyword_still_law36(self):
        mat98 = (
            "*MAT_SIMPLIFIED_JOHNSON_COOK\n"
            "         1 7.85E-9  210000.0       0.3\n"
            "     350.0     275.0      0.36     0.022\n"
        )
        _, starter = _convert(SHELL_DECK.format(MAT=mat98))
        self.assertIn("/MAT/LAW36/1", starter)
        self.assertNotIn("/MAT/LAW2/1", starter)

    def test_fs_single_criterion_fail_johnson_byte_identical(self):
        # MAT_024 FAIL → the historical single-criterion trailer: D2..D5=0,
        # EPSILON_DOT_0=0, Ifail_so=1, and the "moved criterion" warning.
        mat24 = (
            "*MAT_PIECEWISE_LINEAR_PLASTICITY\n"
            "         1 7.85E-9  210000.0       0.3     350.0    1000.0      0.15\n"
        )
        result, starter = _convert(SHELL_DECK.format(MAT=mat24))
        d = _block_lines(starter, "/FAIL/JOHNSON/1")
        self.assertEqual(
            d[1],
            "                0.15                   0                   0"
            "                   0                   0")
        self.assertEqual(
            d[2],
            "                   0         2         1                    "
            "                   0")
        self.assertTrue(any("moved from the material Eps_max" in w
                            for w in result.warnings))

    def test_null_plus_eos_fluid_pairing_untouched(self):
        # A *MAT_NULL + shared-id *EOS_* still becomes /MAT/LAW6 + /EOS (no JC
        # material in the deck consumes it).
        mat = (
            "*MAT_NULL\n"
            "         1 1.00E-9\n"
        ) + GRUNEISEN_7.replace("         7", "         1", 1)
        _, starter = _convert(SOLID_DECK.format(MAT=mat, EOSID=""))
        self.assertIn("/MAT/HYD_VISC/1", starter)
        self.assertIn("/EOS/GRUNEISEN/1", starter)


if __name__ == "__main__":
    unittest.main()
