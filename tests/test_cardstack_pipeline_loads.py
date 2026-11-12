"""Tests for the CARDSTACK PIPELINE batch (k2rad), group K2 (loads):

  K-20  a *DAMPING_PART_MASS / *DAMPING_GLOBAL LCID curve is converted in
        TIME (default ON, ``--no-damping-curve-window`` restores the old
        bytes): a piecewise-constant curve (its edges judged on alpha = SF x
        curve) becomes one alpha-only /DAMP per level with its Tstart /
        Tstop on ONE shared /GRNOD, any other shape a /DAMP/FUNCT (a
        *DEFINE_CURVE_SMOOTH on a sampled /FUNCT copy), and on
        *DAMPING_GLOBAL the curve replaces VALDMP; after its last abscissa
        a curve is 0 on both branches, except a FLAT curve, whose held level
        is named (the fix round of the review: DampingSmoothCurveCopy ..
        DampingWarningTexts)
  K-21  a *RIGIDWALL_PLANAR_FINITE face that covers none of its tracked
        nodes at t = 0 (the NSID group minus NSIDEX, the BOXID nodes, or the
        starter's NSID-0 distance search) is named (m = n x l), every planar
        wall that can touch a shell node gets one clearance line (it acts
        on the MID-SURFACE node), and the FRIC 3 weld sentence says what
        Slide 1 really does - all of it warnings only, the deck bytes stay
        those of master d7652da

Kept in its own module, the repo's one-module-per-batch convention. The
harness helpers are imported from tests/test_r14_triage_7.py as a MODULE,
so no earlier TestCase is bound in this namespace and none runs twice.

The decks use *MAT_PLASTIC_KINEMATIC shells and no tets or contacts, so the
other default flips of this batch (LAW1 shells, tet sections, SST gaps) do
not touch the pinned master bytes below.
"""

import hashlib
import unittest

import test_r14_triage_7 as _t7

_row = _t7._row
_convert = _t7._convert
_has = _t7._has


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── decks ────────────────────────────────────────────────────────────────────

#: the card plate of the D2 probe: X 40..100, Y 30..170 at Z 2.18
_PLATE_Z = 2.18
_PLATE_T = 0.35


def _plate(nx: int = 2, ny: int = 2, z: float = _PLATE_Z):
    """(node rows, shell rows, node ids) of an nx x ny quad plate."""
    ids, nodes, k = {}, [], 1
    for j in range(ny + 1):
        for i in range(nx + 1):
            ids[(i, j)] = k
            nodes.append(f"{k:>8}{40.0 + 60.0 * i / nx:>16}"
                         f"{30.0 + 140.0 * j / ny:>16}{z:>16}\n")
            k += 1
    shells, e = [], 1
    for j in range(ny):
        for i in range(nx):
            shells.append("".join(f"{v:>8}" for v in (
                e, 1, ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)],
                ids[(i, j + 1)])) + "\n")
            e += 1
    return "".join(nodes), "".join(shells), sorted(ids.values())


def _deck(extra: str = "", endtim: float = 0.01, t: float = _PLATE_T,
          z: float = _PLATE_Z) -> str:
    """One shell part (pid 1, *MAT_PLASTIC_KINEMATIC, T = *t*), node set 10
    holding every plate node, *extra* cards, ENDTIM *endtim*."""
    nodes, shells, nids = _plate(z=z)
    rows = "".join(_row(*nids[i:i + 8]) + "\n" for i in range(0, len(nids), 8))
    return ("*KEYWORD\n*TITLE\ncardstack loads\n"
            + "*CONTROL_TERMINATION\n" + _row(endtim) + "\n"
            + "*NODE\n" + nodes
            + "*ELEMENT_SHELL\n" + shells
            + "*PART\ncard\n" + _row(1, 1, 1) + "\n"
            + "*SECTION_SHELL\n" + _row(1, 2, 0.8333, 3) + "\n"
            + _row(t, t, t, t) + "\n"
            + "*MAT_PLASTIC_KINEMATIC\n"
            + _row(1, 1.35e-9, 3200.0, 0.35, 40.0, 100.0) + "\n"
            + _row(0.0, 0.0, 0.0) + "\n"
            + "*SET_NODE_LIST\n" + _row(10) + "\n" + rows
            + extra + "*END\n")


def _curve(lcid: int, pts, sfo: float = 1.0, offa: float = 0.0) -> str:
    head = (_row(lcid, 0, 1.0, sfo) if offa == 0.0
            else _row(lcid, 0, 1.0, sfo, offa))
    return ("*DEFINE_CURVE\n" + head + "\n"
            + "".join(f"{a!r:>20}{o!r:>20}\n" for a, o in pts))


def _stiffness(beta: float = 1.0e-7) -> str:
    return "*DAMPING_PART_STIFFNESS\n" + _row(1, beta) + "\n"


def _part_mass(lcid: int, sf: float = 1.0, flag: int = 0, st=None) -> str:
    card = "*DAMPING_PART_MASS\n" + _row(1, lcid, sf, flag) + "\n"
    if flag == 1:
        card += _row(*st) + "\n"
    return card


def _global(lcid: int, valdmp: float, st=None) -> str:
    return ("*DAMPING_GLOBAL\n"
            + _row(lcid, valdmp, *(st or ())) + "\n")


#: the CardStack settle window: 2500 until 3 ms, then 0 (a vertical edge)
_BOX = ((0.0, 2500.0), (0.003, 2500.0), (0.003, 0.0), (1.0, 0.0))
#: the D2-4 probe box: 250 until 1 ms, a 1 us edge, then 0
_PROBE_BOX = ((0.0, 250.0), (1.0e-3, 250.0), (1.001e-3, 0.0), (1.0, 0.0))
#: two disjoint windows of different alpha (the D2-4 'a4' measurement)
_TWO_BOXES = ((0.0, 250.0), (0.0005, 250.0), (0.0005, 0.0), (0.001, 0.0),
              (0.001, 500.0), (0.0015, 500.0), (0.0015, 0.0), (1.0, 0.0))
#: a 2 ms ramp to 100 that holds past ENDTIM (lobotto.beam's shape)
_RAMP = ((0.0, 0.0), (0.002, 100.0), (1.0, 100.0))
#: the same ramp, ending at 5 ms - before ENDTIM 0.01
_SHORT_RAMP = ((0.0, 0.0), (0.002, 100.0), (0.005, 100.0))


def _damp_cards(starter: str):
    """Every /DAMP and /DAMP/FUNCT block as (keyword, id, title, data rows)."""
    lines = starter.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if not ln.startswith("/DAMP/"):
            continue
        parts = ln.split("/")
        kw = "/DAMP/FUNCT" if parts[2] == "FUNCT" else "/DAMP"
        rows = []
        j = i + 2
        while (j < len(lines) and not lines[j].startswith("/")
               and not lines[j].startswith("#---")):
            if not lines[j].startswith("#"):
                rows.append(lines[j])
            j += 1
        out.append((kw, int(parts[-1]), lines[i + 1], rows))
    return out


def _plain(starter: str):
    """card 1 of every plain /DAMP as (alpha, beta, grnod, skew, Tstart,
    Tstop) strings, cut at the FORMAT(radioss110) columns 20/20/10/10/20/20."""
    return [(r[0][0:20].strip(), r[0][20:40].strip(), r[0][40:50].strip(),
             r[0][50:60].strip(), r[0][60:80].strip(), r[0][80:100].strip())
            for kw, _i, _t, r in _damp_cards(starter) if kw == "/DAMP"]


def _functs(starter: str):
    """every /DAMP/FUNCT as (Fct_ID, grnod_id, Alpha, [six coefficients])."""
    out = []
    for kw, _i, _t, r in _damp_cards(starter):
        if kw != "/DAMP/FUNCT":
            continue
        c = [r[1][k:k + 20].strip() for k in (0, 20, 40)]
        c += [r[2][k:k + 20].strip() for k in (0, 20, 40)]
        out.append((int(r[0][0:10]), int(r[0][10:20]), r[0][20:40].strip(),
                    c))
    return out


def _grnod_ids(starter: str, needle: str):
    lines = starter.splitlines()
    return [int(ln.rsplit("/", 1)[1]) for k, ln in enumerate(lines)
            if ln.startswith("/GRNOD/NODE/") and needle in lines[k + 1]]


def _funct_points(starter: str, fid: int):
    """the (x, y) rows of /FUNCT/<fid>."""
    lines = starter.splitlines()
    i = lines.index(f"/FUNCT/{fid}")
    pts = []
    for ln in lines[i + 2:]:
        if ln.startswith("/") or ln.startswith("#---"):
            break
        if not ln.startswith("#"):
            pts.append((float(ln[0:20]), float(ln[20:40])))
    return pts


# ═════════════════════════════════════════════════════════════════════════════
# K-20 - piecewise-constant curves -> alpha-only /DAMP windows
# ═════════════════════════════════════════════════════════════════════════════

class DampingWindowBox(unittest.TestCase):
    """The settle window: one /DAMP alpha = SF x level, Tstart 0, Tstop at
    the edge, on the part's ONE /GRNOD - no /DAMP/FUNCT."""

    def test_box_0_to_3_ms_is_one_window(self):
        res, s, _e = _convert(_deck(_curve(30, _BOX) + _part_mass(30)))
        cards = _plain(s)
        self.assertEqual(1, len(cards), cards)
        alpha, beta, grnod, skew, t0, t1 = cards[0]
        self.assertEqual(("2500", "0", "0", "0", "0.003"),
                         (alpha, beta, skew, t0, t1))
        self.assertEqual([int(grnod)],
                         _grnod_ids(s, "damping_part_mass_pid_1"))
        self.assertEqual([], _functs(s))
        self.assertTrue(_has(res.warnings, "*DAMPING_PART_MASS (PID=1)",
                             "written in TIME as 1 alpha-only /DAMP"),
                        res.warnings)
        self.assertFalse(_has(res.warnings, "time-VARYING"))

    def test_edge_sits_at_the_ramp_midpoint(self):
        """250 until 1 ms, a 1 us edge: Tstop = (1e-3 + 1.001e-3) / 2."""
        _r, s, _e = _convert(_deck(_curve(2, _PROBE_BOX) + _part_mass(2),
                                   endtim=0.002))
        self.assertEqual([("250", "0", _plain(s)[0][2], "0", "0",
                           "0.0010005")], _plain(s))

    def test_sf_scales_every_window(self):
        _r, s, _e = _convert(_deck(_curve(30, _BOX) + _part_mass(30, 0.5)))
        self.assertEqual("1250", _plain(s)[0][0])

    def test_two_boxes_share_one_grnod(self):
        _r, s, _e = _convert(_deck(_curve(4, _TWO_BOXES) + _part_mass(4),
                                   endtim=0.002))
        cards = _plain(s)
        self.assertEqual([("250", "0", "0.0005"), ("500", "0.001", "0.0015")],
                         [(c[0], c[4], c[5]) for c in cards])
        groups = _grnod_ids(s, "damping_part_mass_pid_1")
        self.assertEqual(1, len(groups))
        self.assertEqual({str(groups[0])}, {c[2] for c in cards})

    def test_window_starting_after_endtim_is_not_written(self):
        """'none if the window starts after ENDTIM' (the cup-draw shape)."""
        late = ((0.0, 0.0), (0.01, 0.0), (0.01, 3.0e9), (1.0, 3.0e9))
        res, s, _e = _convert(_deck(_curve(3, late) + _part_mass(3),
                                    endtim=0.0007))
        self.assertEqual([], _damp_cards(s))
        self.assertNotIn("PART MASS DAMPING", s)
        self.assertTrue(_has(res.warnings, "load curve 3 is 0 over the "
                             "whole run", "damps nothing"), res.warnings)

    def test_a_level_open_past_endtim_stops_at_1e30(self):
        step_up = ((0.0, 0.0), (0.004, 0.0), (0.004, 800.0), (0.02, 800.0))
        _r, s, _e = _convert(_deck(_curve(5, step_up) + _part_mass(5)))
        self.assertEqual([("800", "0.004", "1.000000E+30")],
                         [(c[0], c[4], c[5]) for c in _plain(s)])

    def test_a_curve_starting_before_t0_is_clipped_to_0(self):
        early = ((-0.002, 600.0), (0.001, 600.0), (0.001, 0.0), (1.0, 0.0))
        _r, s, _e = _convert(_deck(_curve(6, early) + _part_mass(6)))
        self.assertEqual([("600", "0", "0.001")],
                         [(c[0], c[4], c[5]) for c in _plain(s)])

    def test_flat_curve_keeps_the_old_whole_run_card(self):
        """A level that covers [0, ENDTIM] needs no window: the old card,
        title and all (11.3.sqt_iga_s.k is (0, 200) (0.01, 200))."""
        flat = ((0.0, 200.0), (0.01, 200.0))
        res, s, _e = _convert(_deck(_curve(201, flat) + _part_mass(201)))
        cards = _damp_cards(s)
        self.assertEqual(1, len(cards))
        self.assertEqual("Mass damping *DAMPING_PART_MASS lcid=201 "
                         "(alpha=200)", cards[0][2])
        self.assertEqual(("200", "0", "1.000000E+30"),
                         (_plain(s)[0][0], _plain(s)[0][4], _plain(s)[0][5]))
        self.assertFalse(_has(res.warnings, "written in TIME"))

    def test_flag1_scale_factors_reach_every_window(self):
        """FLAG = 1: the Format-2 rows carry alpha x ST_i on each window."""
        _r, s, _e = _convert(_deck(
            _curve(4, _TWO_BOXES)
            + _part_mass(4, 1.0, 1, (1.0, 0.5, 0.0, 0.25, 0.1, 2.0)),
            endtim=0.002))
        cards = [c for c in _damp_cards(s) if c[0] == "/DAMP"]
        self.assertEqual(2, len(cards))
        for (_kw, _id, _t, rows), level in zip(cards, (250.0, 500.0)):
            self.assertEqual(6, len(rows))
            got = [float(r[0:20]) for r in rows]
            self.assertEqual([level * f for f in
                              (1.0, 0.5, 0.0, 0.25, 0.1, 2.0)], got)
            self.assertEqual(["0"] * 5, [r[20:40].strip() for r in rows[1:]])


class DampingSteepEdgeBound(unittest.TestCase):
    """An edge counts as steep when (largest - smallest ordinate across it)
    x its duration <= 0.04: 100 x 0.0003 = 0.03 is a step, 100 x 0.0005
    = 0.05 is a ramp that only /DAMP/FUNCT can carry."""

    def _cards(self, dt):
        pts = ((0.0, 100.0), (0.003, 100.0), (0.003 + dt, 0.0), (1.0, 0.0))
        res, s, _e = _convert(_deck(_curve(7, pts) + _part_mass(7)))
        return res, s

    def test_dose_0_03_is_a_window_at_the_midpoint(self):
        _r, s = self._cards(0.0003)
        self.assertEqual([("100", "0", "0.00315")],
                         [(c[0], c[4], c[5]) for c in _plain(s)])
        self.assertEqual([], _functs(s))

    def test_dose_0_05_is_a_function(self):
        res, s = self._cards(0.0005)
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        self.assertTrue(_has(res.warnings, "not piecewise constant",
                             "(largest - smallest ordinate) x duration"),
                        res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# K-20 - any other shape -> /DAMP/FUNCT
# ═════════════════════════════════════════════════════════════════════════════

class DampingFunctRamp(unittest.TestCase):

    def test_ramp_is_one_damp_funct(self):
        res, s, _e = _convert(_deck(_curve(31, _RAMP) + _part_mass(31, 1.5)))
        self.assertEqual([], _plain(s))
        funct = _functs(s)
        self.assertEqual(1, len(funct))
        fct, grnod, alpha, coeff = funct[0]
        self.assertEqual(31, fct)               # covers ENDTIM: no copy
        self.assertEqual([grnod], _grnod_ids(s, "damping_part_mass_pid_1"))
        self.assertEqual("1.5", alpha)          # Alpha = SF
        self.assertEqual(["1"] * 6, coeff)      # written out, no default
        self.assertTrue(_has(res.warnings, "*DAMPING_PART_MASS (PID=1)",
                             "/DAMP/FUNCT", "WARNING 100211"), res.warnings)

    def test_card_layout_is_the_radioss2026_cfg(self):
        _r, s, _e = _convert(_deck(_curve(31, _RAMP) + _part_mass(31)))
        lines = s.splitlines()
        i = next(k for k, ln in enumerate(lines)
                 if ln.startswith("/DAMP/FUNCT/"))
        self.assertEqual("#   Fct_ID  grnod_id               Alpha",
                         lines[i + 2])
        self.assertEqual(40, len(lines[i + 3]))
        self.assertEqual("#            Alpha_x             Alpha_y"
                         "             Alpha_z", lines[i + 4])
        self.assertEqual(60, len(lines[i + 5]))
        self.assertEqual("#           Alpha_xx            Alpha_yy"
                         "            Alpha_zz", lines[i + 6])
        self.assertEqual(60, len(lines[i + 7]))
        self.assertTrue(lines[i + 8].startswith("#---"))

    def test_a_curve_ending_before_endtim_gets_a_zero_tail_copy(self):
        res, s, _e = _convert(_deck(_curve(32, _SHORT_RAMP)
                                    + _part_mass(32)))
        fct, _g, _a, _c = _functs(s)[0]
        self.assertNotEqual(32, fct)
        pts = _funct_points(s, fct)
        self.assertEqual(list(_SHORT_RAMP), pts[:3])
        # the drop to 0 starts 1e-4 x the last abscissa after it, and the
        # far point is 2 x ENDTIM
        self.assertEqual([(0.0050005, 0.0), (0.02, 0.0)], pts[3:])
        self.assertTrue(_has(res.warnings, f"/FUNCT/{fct}",
                             "0 after its last abscissa"), res.warnings)

    def test_global_funct_has_alpha_1_and_the_st_factors(self):
        _r, s, _e = _convert(_deck(_curve(31, _RAMP) + _global(
            31, 0.0, (1.0, 1.0, 0.0, 0.0, 0.0, 0.0))))
        fct, _g, alpha, coeff = _functs(s)[0]
        self.assertEqual((31, "1"), (fct, alpha))
        self.assertEqual(["1", "1", "0", "0", "0", "0"], coeff)

    def test_a_ramp_starting_at_0_is_not_dropped(self):
        """The old reduction read the first ordinate 0 and dropped the
        card; the ramp is now carried."""
        starts0 = ((0.0, 0.0), (0.01, 100.0))
        res, s, _e = _convert(_deck(_curve(205, starts0) + _part_mass(205)))
        self.assertEqual(1, len(_functs(s)))
        self.assertFalse(_has(res.warnings, "damps nothing"))


# ═════════════════════════════════════════════════════════════════════════════
# K-20 - *DAMPING_GLOBAL: the curve wins over VALDMP
# ═════════════════════════════════════════════════════════════════════════════

class DampingGlobalCurveWins(unittest.TestCase):

    def test_box_curve_wins_over_valdmp(self):
        _r, s, _e = _convert(_deck(_curve(30, _BOX) + _global(30, 500.0)))
        self.assertEqual([("2500", "0", "0", "0.003")],
                         [(c[0], c[1], c[4], c[5]) for c in _plain(s)])
        self.assertEqual(1, len(_grnod_ids(s, "damping_target_all_"
                                           "deformable")))

    def test_valdmp_0_with_a_curve_is_no_longer_undamped(self):
        _r, s, _e = _convert(_deck(_curve(30, _BOX) + _global(30, 0.0)))
        self.assertEqual(1, len(_plain(s)))

    def test_opt_out_keeps_valdmp_for_the_whole_run(self):
        _r, s, _e = _convert(_deck(_curve(30, _BOX) + _global(30, 500.0)),
                             damping_curve_window=False)
        self.assertEqual([("500", "0", "0", "1.000000E+30")],
                         [(c[0], c[1], c[4], c[5]) for c in _plain(s)])

    def test_beta_keeps_one_ungated_card_and_says_so(self):
        """/DAMP/FUNCT has no Beta column, and a second /DAMP on the same
        nodes would corrupt the beta term through the shared per-node
        history buffer: one ungated card, alpha = the curve at t 0."""
        res, s, _e = _convert(_deck(
            _curve(30, _BOX) + _global(30, 500.0)
            + "*DAMPING_PART_STIFFNESS\n" + _row(1, 1.0e-7) + "\n"))
        self.assertEqual([("2500", "1.000000E-07", "0", "1.000000E+30")],
                         [(c[0], c[1], c[4], c[5]) for c in _plain(s)])
        self.assertEqual([], _functs(s))
        self.assertTrue(_has(res.warnings, "*DAMPING_GLOBAL", "ONE ungated",
                             "beta", "LOST"), res.warnings)

    def test_global_curve_0_over_the_run_writes_nothing(self):
        late = ((0.0, 0.0), (0.01, 0.0), (0.01001, 3.0e9), (0.02, 3.0e9))
        res, s, _e = _convert(_deck(_curve(3, late) + _global(3, 0.0),
                                    endtim=0.0007))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "resolves to alpha=0 AND beta=0",
                             "curve 3 is 0 over the whole run"),
                        res.warnings)


class DampingSfZeroStillDrops(unittest.TestCase):

    def test_sf_0_drops_a_box_and_a_ramp(self):
        for name, pts in (("box", _BOX), ("ramp", _RAMP)):
            with self.subTest(curve=name):
                res, s, _e = _convert(_deck(_curve(30, pts)
                                            + _part_mass(30, 0.0)))
                self.assertEqual([], _damp_cards(s))
                self.assertTrue(_has(res.warnings, "damps nothing"))


# ═════════════════════════════════════════════════════════════════════════════
# K-20 - the rules of the piecewise reading, each pinned by its own deck
# ═════════════════════════════════════════════════════════════════════════════

def _windows(starter: str):
    """(alpha, Tstart, Tstop) of every plain /DAMP."""
    return [(c[0], c[4], c[5]) for c in _plain(starter)]


class DampingStepReadingRules(unittest.TestCase):
    """What makes a curve piecewise constant, and where its windows lie."""

    def _pm(self, pts, endtim=0.01, **kw):
        return _convert(_deck(_curve(30, pts) + _part_mass(30),
                              endtim=endtim), **kw)

    def test_a_bump_back_to_its_own_level_is_a_function(self):
        """A 1 us spike to 300 between two 250 plateaus is steep, but there
        is no step to stand for it: /DAMP/FUNCT, not two windows."""
        res, s, _e = self._pm(((0.0, 250.0), (0.001, 250.0),
                               (0.0010005, 300.0), (0.001001, 250.0),
                               (1.0, 250.0)))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        self.assertTrue(_has(res.warnings, "returns to its own level 250"),
                        res.warnings)

    def test_a_reversed_abscissa_is_a_function(self):
        """No piecewise reading of a reversed abscissa: the /DAMP/FUNCT
        follows the /FUNCT k2rad writes for it."""
        res, s, _e = self._pm(((0.0, 250.0), (0.002, 250.0), (0.001, 0.0),
                               (1.0, 0.0)))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        self.assertTrue(_has(res.warnings, "abscissa reverses at t 0.001"),
                        res.warnings)

    def test_an_overshooting_edge_counts_its_full_range(self):
        """100 -> 400 -> 0 within 0.2 ms: the dose takes the largest minus
        the smallest ordinate (400 x 0.0002 = 0.08), not |end - start|
        (100 x 0.0002 = 0.02). An edge through an intermediate point is
        held to 0.005 (DampingMultiPointEdgeBound)."""
        res, s, _e = self._pm(((0.0, 100.0), (0.003, 100.0),
                               (0.0031, 400.0), (0.0032, 0.0), (1.0, 0.0)))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        self.assertTrue(_has(res.warnings, "duration = 0.08 > 0.005"),
                        res.warnings)

    def test_a_level_ending_after_endtim_stops_at_1e30(self):
        """800 on 4..20 ms, ENDTIM 10 ms: the window is open at ENDTIM, so
        it runs to the end of the run (Tstop 1E30), not to 20 ms."""
        _r, s, _e = self._pm(((0.0, 0.0), (0.004, 0.0), (0.004, 800.0),
                              (0.02, 800.0), (0.02, 0.0), (1.0, 0.0)))
        self.assertEqual([("800", "0.004", "1.000000E+30")], _windows(s))

    def test_a_window_starting_at_endtim_never_opens(self):
        res, s, _e = self._pm(((0.0, 0.0), (0.01, 0.0), (0.01, 500.0),
                               (1.0, 500.0)))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 30 is 0 over the "
                             "whole run"), res.warnings)

    def test_a_level_ending_before_t0_is_dropped(self):
        """600 on -3..-1 ms, then 0: nothing of it reaches the run."""
        res, s, _e = self._pm(((-0.003, 600.0), (-0.001, 600.0),
                               (-0.001, 0.0), (1.0, 0.0)))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 30 is 0 over the "
                             "whole run"), res.warnings)

    def test_remark_4a_offa_head_delays_the_window(self):
        """OFFA 2 ms on a 250 box (0..1 ms): Vol I R17 *DEFINE_CURVE
        Remark 4a adds (0, 0) and (0.999 OFFA, 0), so the level opens at
        the midpoint 0.001999 of that added edge, not at t 0."""
        _r, s, _e = _convert(_deck(
            _curve(30, ((0.0, 250.0), (0.001, 250.0), (0.001, 0.0),
                        (1.0, 0.0)), offa=0.002) + _part_mass(30)))
        self.assertEqual([("250", "0.001999", "0.003")], _windows(s))

    def test_a_window_title_counts_the_windows(self):
        _r, s, _e = _convert(_deck(_curve(4, _TWO_BOXES) + _part_mass(4),
                                   endtim=0.002))
        self.assertEqual(
            ["Mass damping *DAMPING_PART_MASS lcid=4 window 1/2 (alpha=250)",
             "Mass damping *DAMPING_PART_MASS lcid=4 window 2/2 (alpha=500)"],
            [c[2] for c in _damp_cards(s)])


class DampingFunctCopyRules(unittest.TestCase):
    """When the /DAMP/FUNCT names a copy of the curve, and when a curve
    that is not piecewise constant is still 0 over the run."""

    def _pm(self, pts, endtim=0.01):
        return _convert(_deck(_curve(30, pts) + _part_mass(30),
                              endtim=endtim))

    def test_a_sloped_curve_starting_after_t0_holds_its_first_value(self):
        res, s, _e = self._pm(((0.001, 100.0), (0.003, 300.0),
                               (0.02, 300.0)))
        fct, _g, _a, _c = _functs(s)[0]
        self.assertNotEqual(30, fct)
        self.assertEqual([(0.0, 100.0), (0.001, 100.0), (0.003, 300.0),
                          (0.02, 300.0)], _funct_points(s, fct))
        self.assertTrue(_has(res.warnings, f"/FUNCT/{fct}",
                             "(0, 100) in front"), res.warnings)

    def test_a_curve_already_ending_at_0_needs_no_copy(self):
        """The last two points are 0, so OpenRadioss's own extension of the
        last segment is 0 too: the deck's curve is named as it is."""
        _r, s, _e = self._pm(((0.0, 0.0), (0.002, 100.0), (0.004, 0.0),
                              (0.005, 0.0)))
        self.assertEqual(30, _functs(s)[0][0])

    def test_a_curve_rising_through_endtim_is_not_zero(self):
        """Every point inside [0, ENDTIM] is 0, but the segment to (20 ms,
        1200) reaches 200 at ENDTIM 10 ms - damping that must be written."""
        _r, s, _e = self._pm(((0.0, 0.0), (0.008, 0.0), (0.02, 1200.0)))
        self.assertEqual([30], [f[0] for f in _functs(s)])

    def test_a_sloped_curve_ending_before_t0_is_zero(self):
        """(-2 ms, 0) (-1 ms, 100): the /FUNCT copy is 0 after its last
        abscissa, so nothing of it reaches the run."""
        res, s, _e = self._pm(((-0.002, 0.0), (-0.001, 100.0)))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 30 is 0 over the "
                             "whole run"), res.warnings)

    def test_a_table_curve_gets_a_funct_copy(self):
        """A curve a material reads as a /TABLE is not a /FUNCT of that
        id, so the /DAMP/FUNCT names a /FUNCT copy of its points."""
        from k2rad.writer.loads import _damping_schedule
        st = _t7._dispatch(_deck(_curve(31, _RAMP)))
        self.assertIsNone(_damping_schedule(st, 31).copy_pts)
        st.table_1d_ids.add(31)
        sch = _damping_schedule(st, 31)
        self.assertEqual(list(_RAMP), sch.copy_pts)
        self.assertTrue(any("/TABLE" in n for n in sch.copy_notes))


class DampingGlobalRules(unittest.TestCase):

    def test_beta_card_alpha_is_the_curve_at_t0(self):
        """A step up to 800 at 4 ms with beta: the ONE ungated card takes
        D(t 0) = 0, not the first window's 800."""
        res, s, _e = _convert(_deck(
            _curve(30, ((0.0, 0.0), (0.004, 0.0), (0.004, 800.0),
                        (1.0, 800.0))) + _global(30, 500.0) + _stiffness()))
        self.assertEqual([("0", "1.000000E-07", "0", "1.000000E+30")],
                         [(c[0], c[1], c[4], c[5]) for c in _plain(s)])
        self.assertTrue(_has(res.warnings, "ONE ungated", "alpha=0"),
                        res.warnings)

    def test_beta_card_alpha_holds_a_late_first_value(self):
        """A ramp whose first point is (1 ms, 100): D(t 0) is that first
        value held back to t 0, as the /DAMP/FUNCT copy would carry it."""
        _r, s, _e = _convert(_deck(
            _curve(30, ((0.001, 100.0), (0.003, 300.0), (0.02, 300.0)))
            + _global(30, 500.0) + _stiffness()))
        self.assertEqual([("100", "1.000000E-07")],
                         [(c[0], c[1]) for c in _plain(s)])

    def test_an_undefined_curve_writes_no_mass_damping(self):
        """LCID > 0 bypasses VALDMP, so an undefined curve leaves no mass
        damping at all; --no-damping-curve-window keeps VALDMP."""
        deck = _deck(_global(99, 500.0))
        res, s, _e = _convert(deck)
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 99 is not defined",
                             "VALDMP is bypassed"), res.warnings)
        self.assertTrue(_has(res.warnings, "resolves to alpha=0 AND beta=0",
                             "curve 99 is not defined"), res.warnings)
        _r, s, _e = _convert(deck, damping_curve_window=False)
        self.assertEqual(["500"], [c[0] for c in _plain(s)])

    def test_a_flat_curve_level_wins_over_a_nonzero_valdmp(self):
        _r, s, _e = _convert(_deck(_curve(201, ((0.0, 200.0), (0.01, 200.0)))
                                   + _global(201, 500.0)))
        self.assertEqual([("200", "0", "0", "1.000000E+30")],
                         [(c[0], c[1], c[4], c[5]) for c in _plain(s)])

    def test_timed_cards_name_the_zeroed_st_cells(self):
        res, _s, _e = _convert(_deck(_curve(31, _RAMP) + _global(
            31, 0.0, (1.0, 1.0, 0.0, 0.0, 0.0, 0.0))))
        self.assertTrue(_has(res.warnings, "STZ, SRX, SRY, SRZ = 0.0",
                             "alpha_i = D(t) x ST_i"), res.warnings)


class DampingPartMassRules(unittest.TestCase):

    def test_an_undefined_curve_drops_the_card(self):
        for kw in ({}, {"damping_curve_window": False}):
            with self.subTest(**kw):
                res, s, _e = _convert(_deck(_part_mass(99)), **kw)
                self.assertEqual([], _damp_cards(s))
                hits = [w for w in res.warnings
                        if w.startswith("*DAMPING_PART_MASS (PID=1)")]
                self.assertEqual(1, len(hits), hits)
                self.assertIn("load curve 99 is not defined", hits[0])

    def test_flag1_all_zero_st_reads_uniform_on_windows(self):
        res, s, _e = _convert(_deck(_curve(30, _BOX) + _part_mass(
            30, 1.0, 1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))))
        self.assertEqual([("2500", "0", "0.003")], _windows(s))
        self.assertEqual(1, len(_damp_cards(s)[0][3]))     # Format 1
        self.assertTrue(_has(res.warnings, "Read as 'uniform'",
                             "alpha = SF x curve is used on all six DOFs"),
                        res.warnings)


class DampingHeldLastLevel(unittest.TestCase):
    """A FLAT curve (one level) whose last abscissa is before ENDTIM: the
    level is held to the end of the run (the reading k2rad has always given
    a flat curve: the old first-ordinate card damped the whole run with
    it), and the warning says the deck leaves open what LS-DYNA does there
    (*DEFINE_CURVE Remark 5 names applied loads). A curve with more than one
    level is 0 after its last abscissa instead (DampingOffScaleTail)."""

    _HELD = "is HELD to the end of the run"

    def test_a_flat_curve_ending_before_endtim_is_held_and_said(self):
        res, s, _e = _convert(_deck(_curve(30, ((0.0, 200.0), (0.005, 200.0)))
                                    + _part_mass(30)))
        self.assertEqual([("200", "0", "1.000000E+30")], _windows(s))
        hits = [w for w in res.warnings if self._HELD in w]
        self.assertEqual(1, len(hits), res.warnings)
        for needle in ("*DAMPING_PART_MASS (PID=1): load curve 30 ends at "
                       "t 0.005, before ENDTIM=0.01", "level 200",
                       "Remark 5", "not established"):
            self.assertIn(needle, hits[0])

    def test_a_last_level_of_a_stepped_curve_is_not_held(self):
        """Two levels (0, then 800 from 2 ms) ending at 5 ms: the 800
        window stops at the curve's last abscissa - no HELD sentence."""
        res, s, _e = _convert(_deck(
            _curve(30, ((0.0, 0.0), (0.002, 0.0), (0.002, 800.0),
                        (0.005, 800.0))) + _part_mass(30)))
        self.assertEqual([("800", "0.002", "0.005")], _windows(s))
        self.assertFalse(_has(res.warnings, self._HELD), res.warnings)

    def test_global_says_it_too(self):
        res, _s, _e = _convert(_deck(
            _curve(30, ((0.0, 200.0), (0.005, 200.0))) + _global(30, 0.0)))
        self.assertTrue(_has(res.warnings, "*DAMPING_GLOBAL: load curve 30 "
                             "ends at t 0.005", self._HELD), res.warnings)

    def test_a_beta_card_has_no_held_sentence(self):
        """With beta the ONE ungated card carries D(t 0) for the whole run
        (its own LOST warning), not the curve's last level."""
        res, _s, _e = _convert(_deck(
            _curve(30, ((0.0, 0.0), (0.002, 0.0), (0.002, 800.0),
                        (0.005, 800.0))) + _global(30, 0.0) + _stiffness()))
        self.assertTrue(_has(res.warnings, "ONE ungated"), res.warnings)
        self.assertFalse(_has(res.warnings, self._HELD), res.warnings)

    def test_silent_when_the_curve_ends_at_0_or_reaches_endtim(self):
        for name, pts in (("box", _BOX),
                          ("box ending at 0 before ENDTIM",
                           ((0.0, 250.0), (0.001, 250.0), (0.001, 0.0),
                            (0.005, 0.0))),
                          ("flat to ENDTIM", ((0.0, 200.0), (0.01, 200.0))),
                          ("flat past ENDTIM", ((0.0, 200.0), (0.5, 200.0)))):
            with self.subTest(curve=name):
                res, _s, _e = _convert(_deck(_curve(30, pts)
                                             + _part_mass(30)))
                self.assertFalse(_has(res.warnings, self._HELD),
                                 res.warnings)

    def test_the_opt_out_keeps_its_old_warnings(self):
        res, _s, _e = _convert(_deck(_curve(30, ((0.0, 200.0),
                                                 (0.005, 200.0)))
                                     + _part_mass(30)),
                               damping_curve_window=False)
        self.assertFalse(_has(res.warnings, self._HELD), res.warnings)


# ═════════════════════════════════════════════════════════════════════════════
# K-20 fix round - the review's blocker and majors, each pinned by its deck
# ═════════════════════════════════════════════════════════════════════════════

#: the module's *DEFINE_CURVE_SMOOTH: DIST 1, TSTART 0, TRISE 1 ms, VMAX 300,
#: so TEND = DIST / VMAX + TSTART + TRISE = 4.333 ms and the area is 1
_SMOOTH = ("*DEFINE_CURVE_SMOOTH\n"
           + _row(40, 0, 1.0, 0.0, 0.0, 0.001, 300.0) + "\n")


def _curve_cells(lcid: int, pts, sfa: float = 1.0, offa: float = 0.0,
                 dattyp: int = 0) -> str:
    """A *DEFINE_CURVE with SFA, OFFA and DATTYP written out."""
    return ("*DEFINE_CURVE\n" + _row(lcid, 0, sfa, 1.0, offa, 0.0, dattyp)
            + "\n" + "".join(f"{a!r:>20}{o!r:>20}\n" for a, o in pts))


def _no_endtim(deck: str) -> str:
    """*deck* without its *CONTROL_TERMINATION card."""
    card = "*CONTROL_TERMINATION\n" + _row(0.01) + "\n"
    assert card in deck
    return deck.replace(card, "")


class DampingSmoothCurveCopy(unittest.TestCase):
    """A *DEFINE_CURVE_SMOOTH damping curve. /DAMP/FUNCT evaluates its
    function with ufunc.F GET_U_FUNC (damping_funct_ini.F90): straight
    between the stored points, the first and the last segment extended,
    whatever the /FUNCT_SMOOTH flag (hm_read_funct.F stores both kinds in
    one PLD table). On the raw trapezoid the falling last segment runs on
    below 0 after TEND - the review measured KE/KE0 2073 at 10 ms. The
    /DAMP/FUNCT names a /FUNCT copy instead: the smooth shape sampled as the
    SINE ramp an implicit deck's smooth curve gets, 0 after TEND."""

    def test_the_funct_names_a_sampled_copy_that_ends_at_0(self):
        from k2rad.handlers import sampled_smooth_points
        res, s, _e = _convert(_deck(_SMOOTH + _part_mass(40)))
        self.assertEqual([], _plain(s))
        funct = _functs(s)
        self.assertEqual(1, len(funct))
        fct = funct[0][0]
        self.assertNotEqual(40, fct)
        self.assertIn("/FUNCT_SMOOTH/40", s)        # the deck's curve stays
        want = sampled_smooth_points(0.0, 0.001, 1.0 / 300.0 + 0.001, 300.0,
                                     0.01)
        got = _funct_points(s, fct)
        self.assertEqual(83, len(got))
        for (wa, wo), (ga, go) in zip(want, got):
            self.assertAlmostEqual(wa, ga, delta=1e-12)
            self.assertAlmostEqual(wo, go, delta=1e-7)
        self.assertTrue(all(o >= 0.0 for _a, o in got))
        # a flat last segment at 0: GET_U_FUNC's extension is 0 after TEND
        self.assertEqual([0.0, 0.0], [o for _a, o in got[-2:]])
        area = sum(0.5 * (o1 + o2) * (a2 - a1)
                   for (a1, o1), (a2, o2) in zip(got, got[1:]))
        self.assertAlmostEqual(1.0, area, delta=1e-6)          # = DIST
        self.assertTrue(_has(res.warnings, f"/FUNCT/{fct}",
                             "*DEFINE_CURVE_SMOOTH", "SINE"), res.warnings)

    def test_global_names_the_copy_too(self):
        _r, s, _e = _convert(_deck(_SMOOTH + _global(40, 0.0)))
        funct = _functs(s)
        self.assertEqual(1, len(funct))
        self.assertNotEqual(40, funct[0][0])
        self.assertEqual([0.0, 0.0],
                         [o for _a, o in _funct_points(s, funct[0][0])[-2:]])

    def test_a_steep_smooth_box_is_a_window(self):
        """TRISE 1 us at VMAX 2500 (VMAX x TRISE = 0.0025, inside the 0.005
        of an edge through intermediate points): one alpha-only window
        between the two ramp midpoints, no /DAMP/FUNCT."""
        box = ("*DEFINE_CURVE_SMOOTH\n"
               + _row(41, 0, 7.4975, 0.0, 0.0, 1e-6, 2500.0) + "\n")
        _r, s, _e = _convert(_deck(box + _part_mass(41)))
        self.assertEqual([], _functs(s))
        self.assertEqual([("2500", "5.000000E-07", "0.0029995")],
                         _windows(s))

    def test_a_degenerate_smooth_shape_keeps_its_points_and_ends_at_0(self):
        """A rise and a fall that overlap (TRISE 3 ms in a 4 ms window) are
        no well-formed ramp to sample: the copy keeps the stored points and
        gets the zero tail."""
        bad = ("*DEFINE_CURVE_SMOOTH\n"
               + _row(42, 0, 0.3, 0.0, 0.004, 0.003, 0.0) + "\n")
        _r, s, _e = _convert(_deck(bad + _part_mass(42)))
        funct = _functs(s)
        self.assertEqual(1, len(funct))
        self.assertNotEqual(42, funct[0][0])
        got = _funct_points(s, funct[0][0])
        self.assertEqual((0.004, 0.0), got[-3])     # the stored TEND point
        self.assertEqual([(0.0040004, 0.0), (0.02, 0.0)], got[-2:])


class DampingSfInTheEdgeBound(unittest.TestCase):
    """The steepness of an edge is judged on alpha = SF x curve: the bound
    keeps the damping integral of a step within 1 % of KE only for alpha."""

    def test_a_unit_curve_times_sf_100_is_judged_on_its_alpha(self):
        """(0, 1) (3 ms, 1) (7 ms, 0) x SF 100 and (0, 100) .. x SF 1 are
        one alpha(t): both are /DAMP/FUNCT (SF x 1 x 4 ms = 0.4 > 0.04)."""
        unit = ((0.0, 1.0), (0.003, 1.0), (0.007, 0.0), (1.0, 0.0))
        res, s, _e = _convert(_deck(_curve(30, unit)
                                    + _part_mass(30, 100.0)))
        self.assertEqual([], _plain(s))
        self.assertEqual([(30, "100")], [(f[0], f[2]) for f in _functs(s)])
        self.assertTrue(_has(res.warnings, "SF x (largest - smallest "
                             "ordinate) x duration = 0.4 > 0.04"),
                        res.warnings)
        same = ((0.0, 100.0), (0.003, 100.0), (0.007, 0.0), (1.0, 0.0))
        _r, s, _e = _convert(_deck(_curve(30, same) + _part_mass(30, 1.0)))
        self.assertEqual([(30, "1")], [(f[0], f[2]) for f in _functs(s)])

    def test_a_small_sf_makes_an_edge_steep(self):
        """1000 -> 0 over 0.1 ms: 0.1 at SF 1 is a function, 0.01 at SF 0.1
        a window of alpha 100."""
        pts = ((0.0, 1000.0), (0.003, 1000.0), (0.0031, 0.0), (1.0, 0.0))
        _r, s, _e = _convert(_deck(_curve(30, pts) + _part_mass(30, 1.0)))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        _r, s, _e = _convert(_deck(_curve(30, pts) + _part_mass(30, 0.1)))
        self.assertEqual([], _functs(s))
        self.assertEqual([("100", "0", "0.00305")], _windows(s))


class DampingMultiPointEdgeBound(unittest.TestCase):
    """A step at the midpoint of a STRAIGHT edge keeps the damping integral
    after it and moves it by at most 1/8 of (largest - smallest ordinate) x
    duration inside it, so 0.04 keeps KE within 1 %. An edge through
    intermediate points can move it by the WHOLE product, after the edge
    too, so it is held to 0.005."""

    def test_a_near_rectangular_edge_is_a_function(self):
        """0 -> 380 -> 370 -> 10 within 0.1 ms (product 0.038): its integral
        is 0.0371 where the step's is 0.0005."""
        pts = ((-0.001, 0.0), (0.0, 0.0), (1.0e-6, 380.0), (9.9e-5, 370.0),
               (1.0e-4, 10.0), (1.0, 10.0))
        res, s, _e = _convert(_deck(_curve(30, pts) + _part_mass(30)))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        self.assertTrue(_has(res.warnings, "duration = 0.038 > 0.005",
                             "intermediate points"), res.warnings)

    def test_the_bound_is_0_005(self):
        """0 -> 50 -> 60 within 0.1 ms is a function (0.006), the same edge
        at a third of the level a window (0.002)."""
        def pts(k):
            return ((-0.001, 0.0), (0.0, 0.0), (5.0e-5, 50.0 * k),
                    (1.0e-4, 60.0 * k), (1.0, 60.0 * k))
        _r, s, _e = _convert(_deck(_curve(30, pts(1.0)) + _part_mass(30)))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))
        _r, s, _e = _convert(_deck(_curve(30, pts(1.0 / 3.0))
                                   + _part_mass(30)))
        self.assertEqual([], _functs(s))
        self.assertEqual([("20", "5.000000E-05", "1.000000E+30")],
                         _windows(s))


class DampingOffScaleTail(unittest.TestCase):
    """ONE rule after the last abscissa: a curve with more than one level is
    0 there on both branches - the last window stops at the curve's last
    abscissa, as the /DAMP/FUNCT copy's zero tail does - and only a FLAT
    curve that reaches t 0 keeps the whole-run level k2rad has always given
    it (DampingHeldLastLevel)."""

    _HELD = "is HELD to the end of the run"

    def test_a_last_level_stops_at_the_curve_end_and_is_said(self):
        res, s, _e = _convert(_deck(
            _curve(30, ((0.0, 0.0), (0.0001, 100.0), (0.005, 100.0)))
            + _part_mass(30)))
        self.assertEqual([("100", "5.000000E-05", "0.005")], _windows(s))
        self.assertTrue(_has(res.warnings, "written in TIME",
                             "ends at t 0.005, before ENDTIM=0.01",
                             "stops there"), res.warnings)
        self.assertFalse(_has(res.warnings, self._HELD), res.warnings)

    def test_a_curve_ending_on_0_needs_no_stop_sentence(self):
        """A box that ends with its own edge to 0 before ENDTIM: nothing of
        it is cut by the curve's end."""
        res, s, _e = _convert(_deck(
            _curve(30, ((0.0, 250.0), (0.001, 250.0), (0.001, 0.0),
                        (0.005, 0.0))) + _part_mass(30)))
        self.assertEqual([("250", "0", "0.001")], _windows(s))
        self.assertTrue(_has(res.warnings, "written in TIME"), res.warnings)
        self.assertFalse(_has(res.warnings, "stops there"), res.warnings)

    def test_a_slow_rise_stops_at_the_same_abscissa(self):
        """The same level reached over 0.5 ms (0.05 > 0.04): /DAMP/FUNCT on
        a copy that drops to 0 right after 5 ms."""
        slow = ((0.0, 0.0), (0.0005, 100.0), (0.005, 100.0))
        _r, s, _e = _convert(_deck(_curve(30, slow) + _part_mass(30)))
        pts = _funct_points(s, _functs(s)[0][0])
        self.assertEqual(list(slow), pts[:3])
        self.assertEqual([(0.0050005, 0.0), (0.02, 0.0)], pts[3:])

    def test_global_stops_there_too(self):
        _r, s, _e = _convert(_deck(
            _curve(30, ((0.0, 0.0), (0.002, 0.0), (0.002, 800.0),
                        (0.005, 800.0))) + _global(30, 0.0)))
        self.assertEqual([("800", "0.002", "0.005")], _windows(s))

    def test_a_steep_curve_ending_before_t0_is_zero(self):
        """(-2 ms, 0) (-1.9 ms, 100) used to damp the whole run with 100,
        while the sloped (-2 ms, 0) (-1 ms, 100) gave nothing."""
        res, s, _e = _convert(_deck(
            _curve(30, ((-0.002, 0.0), (-0.0019, 100.0))) + _part_mass(30)))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 30 is 0 over the "
                             "whole run"), res.warnings)

    def test_a_flat_curve_wholly_before_t0_is_zero(self):
        res, s, _e = _convert(_deck(
            _curve(30, ((-0.002, 100.0), (-0.001, 100.0))) + _part_mass(30)))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 30 is 0 over the "
                             "whole run"), res.warnings)

    def test_a_curve_ending_at_endtim_keeps_its_last_window_open(self):
        _r, s, _e = _convert(_deck(
            _curve(30, ((0.0, 0.0), (0.004, 0.0), (0.004, 800.0),
                        (0.01, 800.0))) + _part_mass(30)))
        self.assertEqual([("800", "0.004", "1.000000E+30")], _windows(s))

    def test_a_last_level_of_no_length_writes_no_card(self):
        """(0, 100) (5 ms, 100) (5 ms, 50): the 50 starts and ends at 5 ms,
        so only the 100 window is written."""
        _r, s, _e = _convert(_deck(
            _curve(30, ((0.0, 100.0), (0.005, 100.0), (0.005, 50.0)))
            + _part_mass(30)))
        self.assertEqual([("100", "0", "0.005")], _windows(s))

    def test_without_endtim_the_copy_still_ends_at_0(self):
        """No *CONTROL_TERMINATION (k2rad then writes /RUN 1.0): a stepped
        curve's last window stops at its last abscissa, so the /DAMP/FUNCT
        copy of a ramp drops to 0 there too."""
        _r, s, _e = _convert(_no_endtim(_deck(_curve(32, _SHORT_RAMP)
                                              + _part_mass(32))))
        fct = _functs(s)[0][0]
        self.assertNotEqual(32, fct)
        pts = _funct_points(s, fct)
        self.assertEqual(list(_SHORT_RAMP), pts[:3])
        self.assertEqual([(0.0050005, 0.0), (2.0, 0.0)], pts[3:])
        _r, s, _e = _convert(_no_endtim(_deck(
            _curve(30, ((0.0, 0.0), (0.0001, 100.0), (0.005, 100.0)))
            + _part_mass(30))))
        self.assertEqual([("100", "5.000000E-05", "0.005")], _windows(s))


class DampingRulePins(unittest.TestCase):
    """One deck per K-20 rule the review's mutants found unpinned."""

    def _pm(self, pts, **kw):
        return _convert(_deck(_curve(30, pts) + _part_mass(30)), **kw)

    def _pm4(self, pts, sfa=1.0, offa=0.002, dattyp=0):
        return _convert(_deck(_curve_cells(30, pts, sfa, offa, dattyp)
                              + _part_mass(30)))

    def test_a_step_exactly_at_t0_leaves_nothing_after_it(self):
        """100 -> 0 across t 0 (midpoint 0): the 100 window would end AT
        t 0, and hm_read_damp.F reads a Tstop of 0 as 1E30 - it is
        dropped, not written."""
        res, s, _e = self._pm(((-1.0e-4, 100.0), (1.0e-4, 0.0), (1.0, 0.0)))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "load curve 30 is 0 over the "
                             "whole run"), res.warnings)

    def test_the_zero_check_reads_the_curve_at_t0(self):
        """(-1 ms, 100) (0.5 ms, 0): no point inside the run is non-zero,
        but D(0) = 33.3."""
        _r, s, _e = self._pm(((-0.001, 100.0), (0.0005, 0.0), (1.0, 0.0)))
        self.assertEqual([30], [f[0] for f in _functs(s)])

    def test_remark_4a_needs_sfa_1(self):
        """SFA 2: no Remark 4a head, so the box level holds back to t 0."""
        _r, s, _e = self._pm4(((0.0, 250.0), (0.001, 250.0), (0.001, 0.0),
                               (1.0, 0.0)), sfa=2.0)
        self.assertEqual([("250", "0", "0.006")], _windows(s))

    def test_remark_4a_needs_dattyp_0(self):
        _r, s, _e = self._pm4(((0.0, 250.0), (0.001, 250.0), (0.001, 0.0),
                               (1.0, 0.0)), dattyp=1)
        self.assertEqual([("250", "0", "0.003")], _windows(s))

    def test_remark_4a_skips_a_curve_starting_on_two_zeros(self):
        """Shifted to (2 ms, 0) (3 ms, 0) (7 ms, 100) ..: it starts flat at 0
        already, so the /DAMP/FUNCT names the deck's own curve."""
        _r, s, _e = self._pm4(((0.0, 0.0), (0.001, 0.0), (0.005, 100.0),
                               (1.0, 100.0)))
        self.assertEqual([30], [f[0] for f in _functs(s)])

    def test_remark_4a_adds_0_999_offa_only_before_the_first_point(self):
        """Shifted to start at 0.1 ms: (0.999 OFFA, 0) would come after it,
        so only (0, 0) is added - a 0.1 ms edge to 250."""
        _r, s, _e = self._pm4(((-0.0019, 250.0), (-0.001, 250.0),
                               (-0.001, 0.0), (1.0, 0.0)))
        self.assertEqual([("250", "5.000000E-05", "0.001")], _windows(s))

    def test_two_windows_have_two_ids(self):
        _r, s, _e = _convert(_deck(_curve(4, _TWO_BOXES) + _part_mass(4),
                                   endtim=0.002))
        ids = [c[1] for c in _damp_cards(s)]
        self.assertEqual(2, len(set(ids)), ids)

    def test_no_held_sentence_without_endtim(self):
        res, s, _e = _convert(_no_endtim(_deck(
            _curve(30, ((0.0, 200.0), (0.005, 200.0))) + _part_mass(30))))
        self.assertEqual([("200", "0", "1.000000E+30")], _windows(s))
        self.assertFalse(_has(res.warnings, "is HELD"), res.warnings)

    def test_d_t0_takes_the_level_after_a_step_at_t0(self):
        """A 2 us edge centred on t 0 (0 -> 800), then 800 to 3 ms: with
        beta the ONE ungated card carries D(0) = 800."""
        _r, s, _e = _convert(_deck(
            _curve(30, ((-1.0e-6, 0.0), (1.0e-6, 800.0), (0.003, 800.0),
                        (0.003, 0.0), (1.0, 0.0)))
            + _global(30, 0.0) + _stiffness()))
        self.assertEqual([("800", "1.000000E-07")],
                         [(c[0], c[1]) for c in _plain(s)])

    def test_a_flat_first_segment_needs_no_head(self):
        """GET_U_FUNC extends a flat first segment as it stands: no copy."""
        _r, s, _e = self._pm(((0.001, 100.0), (0.002, 100.0), (0.006, 300.0),
                              (0.02, 300.0)))
        self.assertEqual([30], [f[0] for f in _functs(s)])

    def test_a_ramp_ending_at_endtim_needs_no_tail(self):
        _r, s, _e = self._pm(((0.0, 0.0), (0.01, 100.0)))
        self.assertEqual([30], [f[0] for f in _functs(s)])

    def test_a_curve_ending_at_t0_drops_within_1e_4_endtim(self):
        _r, s, _e = self._pm(((-0.002, 0.0), (0.0, 100.0)))
        fct = _functs(s)[0][0]
        self.assertNotEqual(30, fct)
        self.assertEqual([(-0.002, 0.0), (0.0, 100.0), (1.0e-6, 0.0),
                          (0.02, 0.0)], _funct_points(s, fct))


class DampingWarningTexts(unittest.TestCase):

    def test_a_constant_curve_with_st_names_the_curve_not_valdmp(self):
        """*DAMPING_GLOBAL, flat curve 200, STX = STY = 1: the Format-2
        warning says where alpha comes from - the curve, not VALDMP."""
        deck = _deck(_curve(201, ((0.0, 200.0), (0.01, 200.0)))
                     + _global(201, 500.0, (1.0, 1.0, 0.0, 0.0, 0.0, 0.0)))
        res, _s, _e = _convert(deck)
        w = [w for w in res.warnings if "STZ, SRX, SRY, SRZ = 0.0" in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertNotIn("VALDMP x ST_i", w[0])
        self.assertIn("alpha_i = 200 x ST_i", w[0])
        self.assertIn("curve 201", w[0])
        res, _s, _e = _convert(deck, damping_curve_window=False)
        self.assertTrue(_has(res.warnings, "STZ, SRX, SRY, SRZ = 0.0",
                             "alpha_i = VALDMP x ST_i"), res.warnings)

    def test_the_windows_warning_carries_no_probe_measurement(self):
        res, _s, _e = _convert(_deck(_curve(30, _BOX) + _part_mass(30)))
        w = [w for w in res.warnings if "written in TIME" in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertNotIn("MEASURED", w[0])


# ═════════════════════════════════════════════════════════════════════════════
# K-20 - the three review minors (R14 round 10, B8; the census g2h's tests,
# ported). PIN classes are green on ed52c93 and kill a mutant that survived
# the damping modules (X09, X12); the SPEC classes were red on ed52c93.
# ═════════════════════════════════════════════════════════════════════════════

#: a FLAT curve whose last abscissa is exactly t 0, and its one-point twin
_FLAT0 = ((-0.001, 100.0), (0.0, 100.0))
_ONE0 = ((0.0, 100.0),)
#: two levels, the last one ending at 5 ms (the deck states no ENDTIM)
_ENDS5 = ((0.0, 0.0), (1.0e-4, 100.0), (0.005, 100.0))
#: a unit curve with one straight 4 ms edge
_EDGE4 = ((0.0, 0.0), (0.004, 1.0), (1.0, 1.0))
#: the review's st10 curve: 0 -> 38 -> 37 -> 1 within 0.1 ms, then 1
_ST10 = ((0.0, 0.0), (1.0e-6, 38.0), (9.9e-5, 37.0), (1.0e-4, 1.0),
         (0.02, 1.0))
#: a unit step at 0.1 ms (its 0.1 ms edge: dose 1e-4 - one window)
_STEP1 = ((0.0, 0.0), (1.0e-4, 1.0), (0.02, 1.0))


class PinFlatCurveEndingAtTimeZero(unittest.TestCase):
    """loads.py `held = len(plats) == 1 and pts[-1][0] >= 0.0`: mutant X09
    ('>' for '>=') survived the repo's damping modules; these kill it. On
    the census probe (nt 4) the cell decides between 13.6 % and 100 % of
    the kinetic energy at 10 ms (flat0: KE/KE0 0.3676 / 0.2022 / 0.1356 at
    5 / 8 / 10 ms = exp(-200 t); the mutant's bytes 1.0000)."""

    def _check(self, pts):
        res, s, _e = _convert(_deck(_curve(30, pts) + _part_mass(30)))
        cards = _plain(s)
        self.assertEqual(1, len(cards), cards)
        alpha, _beta, _g, _skew, t0, t1 = cards[0]
        self.assertEqual(("100", "0"), (alpha, t0))
        self.assertGreaterEqual(float(t1), 1.0e29)
        self.assertTrue(_has(res.warnings, "*DAMPING_PART_MASS (PID=1)",
                             "ends at t 0, before ENDTIM=0.01",
                             "HELD to the end of the run"), res.warnings)
        self.assertFalse(_has(res.warnings, "is 0 over the whole run"))

    def test_two_point_flat_curve_ending_at_t0_keeps_its_whole_run_card(self):
        self._check(_FLAT0)

    def test_one_point_curve_at_t0_keeps_its_whole_run_card(self):
        self._check(_ONE0)


class PinStopSentenceWithoutEndtim(unittest.TestCase):
    """loads.py `ends_at = ... 0.0 < xn < endtim`: mutant X12
    ('0.0 < xn < endtim < math.inf') dropped the 'stops there' sentence on
    a deck without *CONTROL_TERMINATION; this kills it. The card is right
    (census ends5: one window alpha 100, Tstop 0.005; 62 496 cycles to the
    engine's t 1, KE/KE0 0.3724 from 5.004 ms on)."""

    def test_the_last_level_stop_is_said_on_a_deck_without_endtim(self):
        res, s, _e = _convert(_no_endtim(_deck(
            _curve(30, _ENDS5) + _part_mass(30))))
        self.assertEqual([("100", "0.005")],
                         [(c[0], c[5]) for c in _plain(s)])
        self.assertTrue(_has(res.warnings, "*DAMPING_PART_MASS (PID=1)",
                             "Curve 30 ends at t 0.005",
                             "stops there"), res.warnings)


class NoInfInTheWindowText(unittest.TestCase):
    """Minor 3 (SPEC, red on ed52c93): with no ENDTIM the text names the
    end of the run k2rad writes (/RUN 1), never 'ENDTIM=inf'."""

    def test_no_endtim_text_has_no_inf(self):
        res, _s, e = _convert(_no_endtim(_deck(
            _curve(30, _ENDS5) + _part_mass(30))))
        self.assertIn("/RUN/cardstack_loads/1\n1\n", e)
        own = [w for w in res.warnings if w.startswith("*DAMPING")]
        self.assertTrue(own)
        self.assertFalse([w for w in own if "=inf" in w or "inf]" in w],
                         own)
        self.assertTrue(_has(own, "the end of the run (no ENDTIM > 0 "
                             "stated)"), own)

    def test_the_global_zero_curve_without_endtim(self):
        res, s, _e = _convert(_no_endtim(_deck(
            _curve(30, ((0.0, 0.0), (1.0, 0.0))) + _global(30, 0.0))))
        self.assertEqual([], _damp_cards(s))
        self.assertTrue(_has(res.warnings, "curve 30 is 0 over the whole run "
                             "[0, the end of the run (no ENDTIM > 0 "
                             "stated)]"), res.warnings)


class STiInTheEdgeBound(unittest.TestCase):
    """Minor 1 (SPEC, red on ed52c93): the steepness bound is judged on the
    direction alpha_i = SF x curve x ST_i, i.e. scale |SF| x max|ST_i| on a
    FLAG 1 *DAMPING_PART_MASS (an all-zero ST row reads as uniform) and
    max|ST_i| on a *DAMPING_GLOBAL with a non-zero ST row. MEASURED (census
    g2h, nt 4 = nt 2): the review's FLAG 1 ST 10 probe written as one window
    kept KE/KE0 0.8201 at 10 ms against the curve's 0.7617 (+7.67 %); the
    /DAMP/FUNCT it now gets (the measured st10fix arm's bytes) 0.7641
    (+0.32 %)."""

    def test_part_mass_st_100_on_a_4_ms_edge_is_a_damp_funct(self):
        """Hand: dose 100 x 1 x 0.004 = 0.4 > 0.04."""
        _r, s, _e = _convert(_deck(
            _curve(30, _EDGE4) + _part_mass(30, 1.0, 1,
                                            (100, 100, 100, 0, 0, 0))))
        self.assertEqual([], _plain(s))
        f = _functs(s)
        self.assertEqual(1, len(f), f)
        self.assertEqual("1", f[0][2])
        self.assertEqual(["100", "100", "100", "0", "0", "0"], f[0][3])

    def test_the_reviews_st10_curve_is_a_damp_funct(self):
        """Hand: dose 10 x 38 x 1e-4 = 0.038 > 0.005 (multi-point)."""
        res, s, _e = _convert(_deck(
            _curve(30, _ST10) + _part_mass(30, 1.0, 1,
                                           (10, 10, 10, 0, 0, 0))))
        self.assertEqual([], _plain(s))
        self.assertEqual(["10", "10", "10", "0", "0", "0"],
                         _functs(s)[0][3])
        self.assertTrue(_has(res.warnings, "|SF| x max|ST_i| x (largest - "
                             "smallest ordinate) x duration = 0.038 > 0.005"),
                        res.warnings)

    def test_global_st_100_on_a_4_ms_edge_is_a_damp_funct(self):
        _r, s, _e = _convert(_deck(
            _curve(30, _EDGE4) + _global(30, 0.0,
                                         (100, 100, 100, 0, 0, 0))))
        self.assertEqual([], _plain(s))
        self.assertEqual(1, len(_functs(s)))

    def test_unit_st_row_keeps_the_window(self):
        """the guard: ST 1 (or an all-zero FLAG-1 row) leaves the bound at
        |SF|, so the 4 ms unit edge stays one window (dose 0.004)."""
        for st in ((1, 1, 1, 0, 0, 0), (0, 0, 0, 0, 0, 0)):
            _r, s, _e = _convert(_deck(
                _curve(30, _EDGE4) + _part_mass(30, 1.0, 1, st)))
            self.assertEqual(1, len(_plain(s)), st)
            self.assertEqual([], _functs(s), st)

    def test_sf_times_st_moves_a_straight_edge_to_funct(self):
        """Hand: dose 2 x 10 x 1 x 0.004 = 0.08 > 0.04."""
        res, s, _e = _convert(_deck(
            _curve(30, _EDGE4) + _part_mass(30, 2.0, 1,
                                            (10, 10, 10, 0, 0, 0))))
        self.assertEqual([], _plain(s))
        f = _functs(s)
        self.assertEqual(1, len(f), f)
        self.assertEqual((30, "2", ["10", "10", "10", "0", "0", "0"]),
                         (f[0][0], f[0][2], f[0][3]))
        self.assertTrue(_has(res.warnings, "= 0.08 > 0.04"), res.warnings)


class AlphaIInTheWindowText(unittest.TestCase):
    """Minor 1, the sentence (round 10, B8): the windows sentence of a
    per-direction card prints alpha_i (it printed the uniform alpha, e.g.
    'alpha=2' on a card whose rows are 1 / 2 / 4)."""

    @staticmethod
    def _window_line(res):
        w = [w for w in res.warnings if "written in TIME" in w]
        assert len(w) == 1, res.warnings
        return w[0]

    def test_a_per_direction_window_names_alpha_i(self):
        """Hand: SF 1 x level 1 x ST 2."""
        res, s, _e = _convert(_deck(
            _curve(30, _STEP1) + _part_mass(30, 1.0, 1, (2, 2, 2, 0, 0, 0))))
        cards = _plain(s)
        self.assertEqual(1, len(cards), cards)
        self.assertEqual(("2", "0", "0", "5.000000E-05", "1.000000E+30"),
                         (cards[0][0], cards[0][1], cards[0][3],
                          cards[0][4], cards[0][5]))
        w = self._window_line(res)
        self.assertIn("alpha_i = SF x level x ST_i in the order x y z xx yy "
                      "zz", w)
        self.assertIn("alpha_i=2 / 2 / 2 / 0 / 0 / 0 for t 5E-05..end", w)

    def test_sf_and_st_multiply_in_the_sentence(self):
        """Hand: SF 2 x level 1 x (0.5, 1, 2) = 1 / 2 / 4."""
        res, s, _e = _convert(_deck(
            _curve(30, _STEP1) + _part_mass(30, 2.0, 1,
                                            (0.5, 1, 2, 0, 0, 0))))
        self.assertEqual("1", _plain(s)[0][0])
        w = self._window_line(res)
        self.assertIn("alpha_i=1 / 2 / 4 / 0 / 0 / 0", w)
        self.assertNotIn("alpha=2 for t", w)

    def test_global_window_names_alpha_i(self):
        res, _s, _e = _convert(_deck(
            _curve(30, _STEP1) + _global(30, 0.0, (2, 2, 2, 0, 0, 0))))
        w = self._window_line(res)
        self.assertIn("alpha_i = the level x ST_i", w)
        self.assertIn("alpha_i=2 / 2 / 2 / 0 / 0 / 0", w)

    def test_a_uniform_card_keeps_its_sentence(self):
        """FLAG 0, SF 2 on the 4 ms edge: one window at the edge's midpoint
        t 0.002, the earlier sentence."""
        res, s, _e = _convert(_deck(_curve(30, _EDGE4) + _part_mass(30, 2.0)))
        cards = _plain(s)
        self.assertEqual(1, len(cards), cards)
        self.assertEqual(("2", "0.002"), (cards[0][0], cards[0][4]))
        self.assertIn("(alpha = SF x level): alpha=2 for t 0.002..end",
                      self._window_line(res))


# ═════════════════════════════════════════════════════════════════════════════
# K-20 - the opt-out restores today's bytes; untouched decks keep them
# ═════════════════════════════════════════════════════════════════════════════

#: the other default-ON levers of the batch, held at their opt-out so the
#: pins below test THIS change only
_OTHERS_OFF = dict(tet_isolid1=False, law1_shell_global_n=False,
                   single_surface_sst_gap=False)

#: SHA-256 (starter, engine) of each deck converted at master d7652da
#: (`git archive d7652da k2rad k2rad.py`, default options, the K2 scratch
#: pin_master.py)
_PINS = {
    "box_part_mass": (
        "f1d80eecf47b39afdad9cd84baee38a85e29580ac90d231602bbac681a28aa11",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "ramp_part_mass": (
        "e5650edd095cf3c8ca71121101a4d729c5a4d3c319c0102fb9b8c75b35db6378",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "global_box_valdmp": (
        "36c5030458ad2f2a113865f4633769f92d358a0b13e33eb25bb2a1dd81a469b9",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "flat_part_mass": (
        "46a97655af0bf850532b217f1624c2b699c56f90f4904dff7735960352e1c13a",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "plain": (
        "fa72c396add8aa54e2088f56e35734078d4c561e9357a13cd269ef5ffca7086a",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "ceiling_misses": (
        "a522e5900b53dbb9f9c5f213344e965386a773d35b542e53d86ea5c5bbd815d1",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "ceiling_covers": (
        "7700512cb82b35dbe2f14f36c9945850b12981484b30a2515c88dd93f7f780af",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "ceiling_moving": (
        "ea3c72327f8e108e9c85cf6270c6f8ea8568cfaf6750023ba29aa37275ab169c",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
    "ceiling_nsidex": (
        "bc2d0797a3d2b731f867dde3a7c667e3d7c774ef11fc77b23637ea9f2b07069d",
        "76e99698a060f1c22d27638e36067b3a62e272f8b8d2fcbe5f701cd26af46f8a"),
}

#: node set 11 = the plate's top row (Y 170) - the only nodes a face at Y
#: 125..175 is over - the NSIDEX of the pinned 'ceiling_nsidex' deck and of
#: FiniteWallTrackedSet
_EXCLUDE_TOP_ROW = "*SET_NODE_LIST\n" + _row(11) + "\n" + _row(7, 8, 9) + "\n"


def _pin_decks():
    """The decks whose master bytes are pinned, by _PINS key."""
    return {
        "box_part_mass": _deck(_curve(30, _BOX) + _part_mass(30)),
        "ramp_part_mass": _deck(_curve(31, _RAMP) + _part_mass(31, 1.5)),
        "global_box_valdmp": _deck(_curve(30, _BOX) + _global(30, 500.0)),
        "flat_part_mass": _deck(_curve(201, ((0.0, 200.0), (0.01, 200.0)))
                                + _part_mass(201)),
        "plain": _deck(),
        "ceiling_misses": _deck(_ceiling(_MISS_Y)),
        "ceiling_covers": _deck(_ceiling(_COVER_Y)),
        "ceiling_moving": _deck(_ceiling(_MISS_Y, nsid=0, mass=1.0)),
        "ceiling_nsidex": _deck(_ceiling(_COVER_Y, lenm=50.0, nsidex=11)
                                + _EXCLUDE_TOP_ROW),
    }


class DampingOptOutBytes(unittest.TestCase):

    def _check(self, key, **kw):
        _r, s, e = _convert(_pin_decks()[key], **_OTHERS_OFF, **kw)
        self.assertEqual(_PINS[key], (_sha(s), _sha(e)))

    def test_opt_out_restores_the_box_bytes(self):
        self._check("box_part_mass", damping_curve_window=False)

    def test_opt_out_restores_the_ramp_bytes(self):
        self._check("ramp_part_mass", damping_curve_window=False)

    def test_opt_out_restores_the_global_bytes(self):
        self._check("global_box_valdmp", damping_curve_window=False)

    def test_flat_curve_keeps_the_master_bytes_by_default(self):
        self._check("flat_part_mass")

    def test_a_deck_without_damping_keeps_the_master_bytes(self):
        self._check("plain")
        self._check("plain", damping_curve_window=False)


# ═════════════════════════════════════════════════════════════════════════════
# K-21 - the finite-face footprint lint, the clearance line, the weld text
# ═════════════════════════════════════════════════════════════════════════════

#: the tail Y of the D2 synthetic ceiling (normal -Z): at Y 25, m = n x l
#: = -Y puts the face at Y -125..25, beside the plate (Y 30..170); at Y 175
#: the face is Y 25..175 and covers it
_MISS_Y = 25.0
_COVER_Y = 175.0


def _ceiling(y: float = _MISS_Y, z: float = 3.0, normal: float = -1.0,
             nsid: int = 10, finite: bool = True, fric: float = 0.1,
             x: float = 35.0, lenl: float = 70.0, lenm: float = 150.0,
             nsidex: int = 0, boxid: int = 0, mass: float = 0.0) -> str:
    """The D2 synthetic ceiling: tail (*x*, *y*, *z*), normal along Z
    (*normal*), l = +X from XHEV (*x* + 70, *y*, *z*), LENL 70, LENM 150 -
    so the face runs from the tail along m = n x l: -Y for a -Z normal, +Y
    for a +Z one. *mass* > 0 makes it a _MOVING wall (V0 = 0); the
    defaults write the text the master pins were taken on."""
    kw = ("*RIGIDWALL_PLANAR" + ("_MOVING" if mass > 0.0 else "")
          + ("_FINITE" if finite else "") + "_ID")
    card = (f"{kw}\n" + _row(1, "CEILING") + "\n"
            + _row(nsid, nsidex, boxid, 0.0) + "\n"
            + _row(x, y, z, x, y, z + normal, fric, 0.0) + "\n")
    if finite:
        card += _row(x + 70.0, y, z, lenl, lenm) + "\n"
    if mass > 0.0:
        card += _row(mass, 0.0) + "\n"
    return card


_LINT = "covers NONE of its"


class FiniteWallFootprintLint(unittest.TestCase):

    def test_a_ceiling_covering_no_node_is_named(self):
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y)))
        hits = [w for w in res.warnings if _LINT in w]
        self.assertEqual(1, len(hits), res.warnings)
        w = hits[0]
        # the label every *RIGIDWALL_PLANAR warning carries
        for needle in ("*RIGIDWALL_PLANAR id=1: the FINITE face",
                       "9 tracked", "m = n x l", "faithful", "(0, -1, 0)",
                       "m -145..-5", "extend or move the face"):
            self.assertIn(needle, w)
        self.assertNotIn("flip the normal", w)

    def test_a_covering_ceiling_is_silent(self):
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y)))
        self.assertFalse(_has(res.warnings, _LINT), res.warnings)

    def test_nodes_behind_the_face_name_the_normal_flip(self):
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y, normal=1.0)))
        w = [w for w in res.warnings if _LINT in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("flip the normal", w[0])
        # flipping n turns m = n x l around, so the face moves with it
        self.assertIn("re-place the face", w[0])
        self.assertNotIn("extend or move the face", w[0])

    def test_nodes_behind_and_beside_the_face_need_both(self):
        """Normal +Z with the tail at Y 175: m = +Y puts the face at Y
        175..325, beside the plate, and the plate is behind it - flip the
        normal AND place the face over the nodes."""
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, normal=1.0)))
        w = [w for w in res.warnings if _LINT in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("(0 on the normal side, 0 over the face)", w[0])
        self.assertIn("flip the normal", w[0])
        self.assertIn("place the face over them", w[0])

    def test_nsid_0_lints_the_d_search_set(self):
        """NSID = 0 tracks the nodes the starter's distance search keeps:
        every plate node is on the normal side, none over the face."""
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y, nsid=0)))
        w = [w for w in res.warnings if _LINT in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("9 tracked", w[0])

    def test_an_infinite_wall_has_no_footprint_to_lint(self):
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y, finite=False)))
        self.assertFalse(_has(res.warnings, _LINT), res.warnings)


#: three free nodes at (70, -50, 5): BEHIND the -Z ceiling at Z 3 and over
#: its face (l 35, m 75)
_BEHIND_NODES = ("*NODE\n" + "".join(
    f"{k:>8}{70.0:>16}{-50.0:>16}{5.0:>16}\n" for k in (101, 102, 103)))


def _lint(res):
    return [w for w in res.warnings if _LINT in w]


class FiniteWallTrackedSet(unittest.TestCase):
    """Which nodes the lint counts as tracked: the D_search set for NSID 0
    (front side only, the wall's carrier out), the NSID group minus
    NSIDEX, the BOXID nodes - and it fires only when NONE of them acts."""

    def test_nsid_0_leaves_nodes_behind_the_plane_out(self):
        """The starter's distance search keeps 0 <= DISN <= d: the three
        nodes behind the ceiling are not tracked, so they are not 'over
        the face' either."""
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y, nsid=0)
                                     + _BEHIND_NODES))
        w = _lint(res)
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("NONE of its 9 tracked", w[0])
        self.assertIn("(9 on the normal side, 0 over the face)", w[0])

    def test_a_moving_wall_does_not_track_its_own_carrier(self):
        """*RIGIDWALL_PLANAR_MOVING_FINITE: the carrier node sits at the
        tail (DISN 0), and the starter's search skips it (I /= MSR)."""
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y, nsid=0, mass=1.0)))
        w = _lint(res)
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("NONE of its 9 tracked", w[0])

    def test_nsidex_nodes_are_not_tracked(self):
        """A face over the top row only (tail Y 175, LENM 50 -> Y 125..175)
        acts on nodes 7-9 - unless NSIDEX removes exactly those."""
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, lenm=50.0)))
        self.assertEqual([], _lint(res))
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, lenm=50.0, nsidex=11)
                                     + _EXCLUDE_TOP_ROW))
        w = _lint(res)
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("NONE of its 6 tracked", w[0])

    def test_boxid_scopes_the_tracked_nodes(self):
        box = "*DEFINE_BOX\n" + _row(5, 0.0, 200.0, 0.0, 150.0, 0.0,
                                     10.0) + "\n"
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, lenm=50.0, nsid=0,
                                              boxid=5) + box))
        w = _lint(res)
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("NONE of its 6 tracked", w[0])

    def test_a_face_over_one_node_is_silent(self):
        """A 10 x 10 face over node 9 (100, 170) alone: one acting node is
        enough, and it gets the clearance line."""
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, z=2.53, x=95.0,
                                              lenl=10.0, lenm=10.0)))
        self.assertEqual([], _lint(res))
        self.assertTrue(_has(res.warnings, _CLEAR, "at node 9"),
                        res.warnings)


_CLEAR = "acts on the tracked NODES"


class WallClearanceLine(unittest.TestCase):

    def test_face_clearance_is_node_clearance_minus_half_t(self):
        """Mid-surface Z 2.18, T 0.35, ceiling at Z 2.53: the node is 0.35
        below the plane and the shell face 0.175."""
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, z=2.53)))
        hits = [w for w in res.warnings if _CLEAR in w]
        self.assertEqual(1, len(hits), res.warnings)
        for needle in ("node clearance 0.35", "t/2 = 0.175",
                       "face clearance 0.175", "mid-surface"):
            self.assertIn(needle, hits[0])

    def test_an_infinite_ceiling_gets_the_line_too(self):
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, z=2.53,
                                              finite=False)))
        self.assertTrue(_has(res.warnings, _CLEAR, "face clearance 0.175"),
                        res.warnings)

    def test_a_face_already_through_the_plane_is_said(self):
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, z=2.28)))
        self.assertTrue(_has(res.warnings, _CLEAR, "face clearance -0.075",
                             "already through the plane"), res.warnings)

    def test_no_line_when_no_node_is_over_the_face(self):
        res, _s, _e = _convert(_deck(_ceiling(_MISS_Y)))
        self.assertFalse(_has(res.warnings, _CLEAR), res.warnings)


def _strip(parts: str, shells: str, tracked, z5: float = _PLATE_Z) -> str:
    """Two quads in a row - element 1 on nodes 1 2 5 4, element 2 on 2 3 6
    5 - with the *parts* / *shells* cards given, node 5 at Z *z5* (the rest
    at the plate's Z 2.18), node set 20 = *tracked*, and an INFINITE -Z
    ceiling at Z 2.53 that tracks set 20 (node clearance 0.35)."""
    xy = {1: (40.0, 30.0), 2: (70.0, 30.0), 3: (100.0, 30.0),
          4: (40.0, 100.0), 5: (70.0, 100.0), 6: (100.0, 100.0)}
    nodes = "".join(f"{k:>8}{x:>16}{y:>16}{(z5 if k == 5 else _PLATE_Z):>16}\n"
                    for k, (x, y) in xy.items())
    return ("*KEYWORD\n*TITLE\ncardstack wall strip\n"
            + "*CONTROL_TERMINATION\n" + _row(0.01) + "\n"
            + "*NODE\n" + nodes + shells + parts
            + "*MAT_PLASTIC_KINEMATIC\n"
            + _row(1, 1.35e-9, 3200.0, 0.35, 40.0, 100.0) + "\n"
            + _row(0.0, 0.0, 0.0) + "\n"
            + "*SET_NODE_LIST\n" + _row(20) + "\n" + _row(*tracked) + "\n"
            + _ceiling(_COVER_Y, z=2.53, finite=False, nsid=20) + "*END\n")


def _two_parts(t1: float, t2: float) -> str:
    out = ""
    for pid, t in ((1, t1), (2, t2)):
        out += ("*PART\nstrip\n" + _row(pid, pid, 1) + "\n"
                + "*SECTION_SHELL\n" + _row(pid, 2, 0.8333, 3) + "\n"
                + _row(t, t, t, t) + "\n")
    return out


_SHELLS = ("*ELEMENT_SHELL\n" + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 5, 4))
           + "\n" + "".join(f"{v:>8}" for v in (2, 2, 2, 3, 6, 5)) + "\n")


class WallClearanceThickness(unittest.TestCase):
    """The t of 'node clearance - t/2' is the node's THICKEST shell (the
    face closest to the wall), read the way the shell is emitted, and the
    line names the node whose face is closest."""

    def _line(self, deck):
        res, _s, _e = _convert(deck)
        hits = [w for w in res.warnings if _CLEAR in w]
        self.assertEqual(1, len(hits), res.warnings)
        return hits[0]

    def test_a_node_takes_its_thickest_shell(self):
        """Node 2 is on the 0.6 element 1 AND the 0.2 element 2: its face
        is 0.3 off it. Only nodes 2 3 5 6 are tracked, so the thin
        element's own nodes cannot stand in for it."""
        w = self._line(_strip(_two_parts(0.6, 0.2), _SHELLS, (2, 3, 5, 6)))
        self.assertIn("at node 2, node clearance 0.35 - t/2 = 0.3 -> face "
                      "clearance 0.05", w)

    def test_the_closest_face_is_reported(self):
        """Node 5 raised to Z 2.38: node clearance 0.15, face -0.025."""
        w = self._line(_strip(_two_parts(0.35, 0.35), _SHELLS,
                              (1, 2, 3, 4, 5, 6), z5=2.38))
        self.assertIn("at node 5, node clearance 0.15 - t/2 = 0.175 -> face "
                      "clearance -0.025 (the face is already through the "
                      "plane)", w)

    def test_element_shell_thickness_counts(self):
        """*ELEMENT_SHELL_THICKNESS 0.6 on element 1 over a 0.35 section."""
        shells = ("*ELEMENT_SHELL_THICKNESS\n"
                  + "".join(f"{v:>8}" for v in (1, 1, 1, 2, 5, 4)) + "\n"
                  + "".join(f"{v:>16}" for v in (0.6, 0.6, 0.6, 0.6)) + "\n"
                  + "".join(f"{v:>8}" for v in (2, 2, 2, 3, 6, 5)) + "\n"
                  + "".join(f"{v:>16}" for v in (0.0, 0.0, 0.0, 0.0)) + "\n")
        w = self._line(_strip(_two_parts(0.35, 0.35), shells,
                              (1, 2, 3, 4, 5, 6)))
        self.assertIn("at node 1, node clearance 0.35 - t/2 = 0.3 -> face "
                      "clearance 0.05", w)

    def test_a_composite_part_is_its_ply_sum(self):
        """*PART_COMPOSITE plies 0.2 + 0.3 on part 1: t 0.5."""
        parts = ("*PART_COMPOSITE\ncomposite strip\n"
                 + _row(1, 2, 0.8333, 0, 0, 0, 0, 0) + "\n"
                 + _row(1, 0.2, 0.0, 0, 1, 0.3, 0.0, 0) + "\n"
                 + "*PART\nstrip\n" + _row(2, 2, 1) + "\n"
                 + "*SECTION_SHELL\n" + _row(2, 2, 0.8333, 3) + "\n"
                 + _row(0.35, 0.35, 0.35, 0.35) + "\n")
        w = self._line(_strip(parts, _SHELLS, (1, 2, 3, 4, 5, 6)))
        self.assertIn("at node 1, node clearance 0.35 - t/2 = 0.25 -> face "
                      "clearance 0.1", w)


#: two free nodes (on no element) 0.08 under the -Z ceiling at Z 2.53 -
#: closer to it than any shell FACE of the plate (0.35 - 0.175 = 0.175)
_FREE_NODES = ("*NODE\n" + "".join(
    f"{k:>8}{70.0:>16}{100.0:>16}{2.45:>16}\n" for k in (201, 202)))


class WallNotePins(unittest.TestCase):
    """One deck per K-21 rule the review's mutants found unpinned."""

    def test_only_a_shell_node_gets_the_clearance_line(self):
        """The line is about a shell FACE, t/2 off its node: free nodes alone
        get none, and next to the plate's nodes they are not the one named,
        although they are closer to the wall."""
        ceiling = _ceiling(_COVER_Y, z=2.53, finite=False, nsid=30)
        alone = "*SET_NODE_LIST\n" + _row(30) + "\n" + _row(201, 202) + "\n"
        res, _s, _e = _convert(_deck(_FREE_NODES + alone + ceiling))
        self.assertFalse(_has(res.warnings, _CLEAR), res.warnings)
        both = ("*SET_NODE_LIST\n" + _row(30) + "\n"
                + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n" + _row(9, 201, 202)
                + "\n")
        res, _s, _e = _convert(_deck(_FREE_NODES + both + ceiling))
        hits = [w for w in res.warnings if _CLEAR in w]
        self.assertEqual(1, len(hits), res.warnings)
        self.assertIn("at node 1, node clearance 0.35 - t/2 = 0.175 -> face "
                      "clearance 0.175", hits[0])

    def test_an_infinite_wall_with_every_node_behind_it_converts(self):
        """+Z normal above the plate: no node can act, an infinite plane has
        no footprint to lint, and the conversion goes through."""
        res, s, _e = _convert(_deck(_ceiling(_COVER_Y, normal=1.0,
                                             finite=False)))
        self.assertIn("/RWALL/PLANE/", s)
        self.assertFalse(_has(res.warnings, _LINT), res.warnings)
        self.assertFalse(_has(res.warnings, _CLEAR), res.warnings)

    def test_a_composite_counts_only_its_valid_plies(self):
        """*PART_COMPOSITE plies (MID 1, 0.4) and (MID 0, 0.3): t = 0.4, the
        part beside it being 0.1 thick."""
        parts = ("*PART_COMPOSITE\ncomposite strip\n"
                 + _row(1, 2, 0.8333, 0, 0, 0, 0, 0) + "\n"
                 + _row(1, 0.4, 0.0, 0, 0, 0.3, 0.0, 0) + "\n"
                 + "*PART\nstrip\n" + _row(2, 2, 1) + "\n"
                 + "*SECTION_SHELL\n" + _row(2, 2, 0.8333, 3) + "\n"
                 + _row(0.1, 0.1, 0.1, 0.1) + "\n")
        res, _s, _e = _convert(_strip(parts, _SHELLS, (1, 2, 3, 4, 5, 6)))
        hits = [w for w in res.warnings if _CLEAR in w]
        self.assertEqual(1, len(hits), res.warnings)
        self.assertIn("at node 1, node clearance 0.35 - t/2 = 0.2 -> face "
                      "clearance 0.15", hits[0])


class GeometricWallsHaveNoPlanarNotes(unittest.TestCase):
    """K-21 reads *RIGIDWALL_PLANAR only: a *RIGIDWALL_GEOMETRIC_FLAT with
    the missing ceiling's geometry gets neither note."""

    def test_a_geometric_flat_wall_is_not_linted(self):
        flat = ("*RIGIDWALL_GEOMETRIC_FLAT_ID\n" + _row(1, "GFLAT") + "\n"
                + _row(10, 0, 0, 0.0, 0.0) + "\n"
                + _row(35.0, _MISS_Y, 3.0, 35.0, _MISS_Y, 2.0, 0.1) + "\n"
                + _row(105.0, _MISS_Y, 3.0, 70.0, 150.0) + "\n")
        res, s, _e = _convert(_deck(flat))
        self.assertIn("/RWALL/PARAL/", s)
        self.assertFalse(_has(res.warnings, _LINT), res.warnings)
        self.assertFalse(_has(res.warnings, _CLEAR), res.warnings)


class WallLintBytes(unittest.TestCase):
    """The lint and the clearance line are warnings: the deck bytes are
    those of master d7652da."""

    def test_the_ceilings_keep_the_master_bytes(self):
        """Missing and covering ceilings, the moving NSID-0 one (its carrier
        node) and the NSIDEX one - each with its lint or clearance line."""
        for key in ("ceiling_misses", "ceiling_covers", "ceiling_moving",
                    "ceiling_nsidex"):
            with self.subTest(deck=key):
                _r, s, e = _convert(_pin_decks()[key], **_OTHERS_OFF)
                self.assertEqual(_PINS[key], (_sha(s), _sha(e)))


class RwallWeldText(unittest.TestCase):
    """Vol I R17 p.40-20: FRIC 1.0 = bouncing back allowed, sliding not
    allowed - which is what Slide 1 does (rgwall.F / rgwalp.F release a
    node moving away from the wall) - while FRIC 3.0 also forbids the
    bounce once the node is welded."""

    def test_fric_3_says_slide_1_releases_a_leaving_node(self):
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, fric=3.0)))
        w = [w for w in res.warnings if "FRIC = 3" in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("a node moving away is released", w[0])
        self.assertIn("bouncing back", w[0])
        self.assertNotIn("nodes below WVEL are tied too", w[0])

    def test_fric_2_keeps_its_rebound_sentence(self):
        res, _s, _e = _convert(_deck(_ceiling(_COVER_Y, fric=2.0)))
        w = [w for w in res.warnings if "FRIC = 2" in w]
        self.assertEqual(1, len(w), res.warnings)
        self.assertIn("frictionless (Slide 0)", w[0])
        self.assertIn("will rebound", w[0])


if __name__ == "__main__":
    unittest.main()
