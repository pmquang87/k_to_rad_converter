"""Tests for the RARE CARDS batch:

  *DEFINE_ELEMENT_DEATH_<FAMILY>[_SET]  → /ACTIV + per-family element groups
  *DEFINE_CURVE_SMOOTH[_TITLE]          → /FUNCT_SMOOTH
  *PERTURBATION_NODE                    → /RANDOM [/GRNOD]
  *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY   → /IMPDISP/FGEO
  *INTERFACE_SPRINGBACK_LSDYNA          → the ENGINE /DYNAIN block

Kept in its own module, the repo's one-module-per-batch convention.
"""

import os
import tempfile
import unittest

from k2rad import convert
from k2rad.assembly import (_OFFSET_SPECS, _RARE_CARD_OFFSETS,
                            _off_interface_springback)
from k2rad.handlers import (HANDLERS, RARE_CARD_KEYWORDS,
                            final_geometry_node_row, dispatch,
                            smooth_curve_points)
from k2rad.parser import parse_k_file
from k2rad.state import ConversionState


# ── Harness ──────────────────────────────────────────────────────────────────

def _row(*vals) -> str:
    """LS-DYNA fixed-width (10-char) card row."""
    return "".join(f"{v:>10}" for v in vals)


def _fgeo_row(nid, x, y, z, lcid="", death="", birth=None) -> str:
    """A *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY node card in the manual's own
    column layout: NID I8, X/Y/Z E16, LCID I8, DEATH E16 (card 2a) or
    DEATH E8 + BIRTH E8 (card 2b)."""
    head = (f"{nid:>8}{x:>16}{y:>16}{z:>16}{lcid:>8}")
    if birth is None:
        return head + f"{death:>16}"
    return head + f"{death:>8}{birth:>8}"


def _convert(deck: str, **kw):
    """convert() a deck string; return (result, starter_text, engine_text)."""
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


def _block(starter: str, header: str):
    """The lines of the first starter block whose header line equals *header*,
    up to the next '/' line."""
    lines = starter.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            out = []
            for data in lines[i + 1:]:
                if data.startswith("/"):
                    break
                out.append(data)
            return out
    return None


def _data_rows(starter: str, header: str):
    body = _block(starter, header)
    if body is None:
        return None
    return [ln for ln in body if not ln.startswith("#")]


def _headers(starter: str, prefix: str):
    return [ln for ln in starter.splitlines() if ln.startswith(prefix)]


def _ids_of_group(starter: str, header: str):
    """The integer ids listed in a group block (title line skipped)."""
    body = _block(starter, header)
    ids = []
    for ln in body[1:]:
        if ln.startswith("#"):
            continue
        ids.extend(int(t) for t in ln.split() if t.lstrip("-").isdigit())
    return ids


def _activ(starter: str, activ_id: int):
    """``(slots, tstart, tstop)`` of /ACTIV/<id>: slots is the eight-cell
    group row plus Iform, sliced 10-wide."""
    body = _data_rows(starter, f"/ACTIV/{activ_id}")
    row, times = body[1], body[2]
    cells = [row[i:i + 10].strip() for i in range(0, 100, 10)]
    return cells, float(times[0:20]), float(times[20:40])


def _activ_ids(starter: str):
    return [int(ln.rsplit("/", 1)[1]) for ln in _headers(starter, "/ACTIV/")]


def _smooth_points(starter: str, fid: int):
    body = _data_rows(starter, f"/FUNCT_SMOOTH/{fid}")
    # title, the Ascalex/Fscaley/Ashiftx/Fshifty card, then the pairs
    return [(float(ln[0:20]), float(ln[20:40])) for ln in body[2:]]


def _warn_containing(result, *needles):
    return [w for w in result.warnings
            if all(n in w for n in needles)]


# ── Shared deck fragments ────────────────────────────────────────────────────

#: One hex (eid 101) on part 1, one quad shell (201) and one 3-corner shell
#: (202) on part 2, and eleven nodes. `{EXTRA}` carries the card under test.
MESH = (
    "*KEYWORD\n"
    "*NODE\n"
    + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
        (4, 0.0, 10.0, 0.0), (5, 0.0, 0.0, 10.0), (6, 10.0, 0.0, 10.0),
        (7, 10.0, 10.0, 10.0), (8, 0.0, 10.0, 10.0), (9, 20.0, 0.0, 0.0),
        (10, 20.0, 10.0, 0.0), (11, 30.0, 0.0, 0.0)))
    + "*ELEMENT_SOLID\n"
    + _row(101, 1) + "\n"
    + _row(1, 2, 3, 4, 5, 6, 7, 8) + "\n"
    "*ELEMENT_SHELL\n"
    + _row(201, 2, 2, 3, 10, 9) + "\n"
    + _row(202, 2, 9, 10, 11, 11) + "\n"
    "*PART\n"
    "solid\n"
    + _row(1, 1, 1) + "\n"
    "*SECTION_SOLID\n"
    + _row(1, 1) + "\n"
    "*PART\n"
    "shell\n"
    + _row(2, 2, 1) + "\n"
    "*SECTION_SHELL\n"
    + _row(2, 2, 1.0, 5) + "\n"
    + _row(1.0, 1.0, 1.0, 1.0) + "\n"
    "*MAT_ELASTIC\n"
    + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.010\n"
    "*END\n"
)

#: One thick shell (eid 101) on part 1, for the THICK_SHELL death case.
#: *ELEMENT_TSHELL is ONE card of eight slots (Vol I R17 p.19-139), unlike
#: *ELEMENT_SOLID's two-card form.
TSHELL_MESH = (
    "*KEYWORD\n"
    "*NODE\n"
    + "".join(f"{n:>8}{x:>16}{y:>16}{z:>16}\n" for n, x, y, z in (
        (1, 0.0, 0.0, 0.0), (2, 10.0, 0.0, 0.0), (3, 10.0, 10.0, 0.0),
        (4, 0.0, 10.0, 0.0), (5, 0.0, 0.0, 2.0), (6, 10.0, 0.0, 2.0),
        (7, 10.0, 10.0, 2.0), (8, 0.0, 10.0, 2.0)))
    + "*ELEMENT_TSHELL\n"
    + "".join(f"{v:>8}" for v in (101, 1, 1, 2, 3, 4, 5, 6, 7, 8)) + "\n"
    "*PART\n"
    "tshell\n"
    + _row(1, 1, 1) + "\n"
    "*SECTION_TSHELL\n"
    + _row(1, 2, 5) + "\n"
    "*MAT_ELASTIC\n"
    + _row(1, "7.85E-9", 210000.0, 0.3) + "\n"
    "{EXTRA}"
    "*CONTROL_TERMINATION\n"
    "     0.010\n"
    "*END\n"
)

#: A ramp curve 0 -> 1 over 0..0.01, for the /IMPDISP/FGEO cases.
RAMP = (
    "*DEFINE_CURVE\n"
    + _row(901, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
    "                 0.0                 0.0\n"
    "                0.01                 1.0\n"
)


# ═════════════════════════════════════════════════════════════════════════════
# *DEFINE_ELEMENT_DEATH_* → /ACTIV
# ═════════════════════════════════════════════════════════════════════════════

class ElementDeathTests(unittest.TestCase):

    def test_solid_card_is_column_exact(self):
        """/ACTIV: eight group slots, ten blanks, Iform, then Tstart/Tstop.

        Layout from radioss2019/LOADCOL/activ.cfg:142-157 —
        %10d x 8, %10s blank, %10d Iform, then %20lg%20lg. Distinct numbers
        per slot, so a column swap is visible.
        """
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID\n"
                            + _row(101, 0.003) + "\n")
        _res, starter, _eng = _convert(deck)
        (activ_id,) = _activ_ids(starter)
        cells, tstart, tstop = _activ(starter, activ_id)
        (grp,) = [int(ln.rsplit("/", 1)[1])
                  for ln in _headers(starter, "/GRBRIC/BRIC/")]
        self.assertEqual(cells[0], "0")            # sens_ID
        self.assertEqual(cells[1], str(grp))       # grbric_ID
        self.assertEqual(cells[2:8], ["0"] * 6)    # quad/shel/trus/beam/spr/sh3n
        self.assertEqual(cells[8], "")             # the blank column
        self.assertEqual(cells[9], "2")            # Iform
        self.assertEqual(tstart, 0.0)
        self.assertEqual(tstop, 0.003)
        self.assertEqual(_ids_of_group(starter, f"/GRBRIC/BRIC/{grp}"), [101])

    def test_shell_set_splits_quads_and_trias_into_two_groups(self):
        """A *SET_SHELL holding a quad and a 3-corner shell must reach TWO
        groups: /GRSHEL/SHEL resolves only 4-node /SHELL ids (#122)."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_SHELL_LIST\n" + _row(700) + "\n"
                            + _row(201, 202) + "\n"
                            "*DEFINE_ELEMENT_DEATH_SHELL_SET\n"
                            + _row(700, 0.004) + "\n")
        _res, starter, _eng = _convert(deck)
        (activ_id,) = _activ_ids(starter)
        cells, _ts, tstop = _activ(starter, activ_id)
        (quad_grp,) = [int(ln.rsplit("/", 1)[1])
                       for ln in _headers(starter, "/GRSHEL/SHEL/")]
        (tri_grp,) = [int(ln.rsplit("/", 1)[1])
                      for ln in _headers(starter, "/GRSH3N/SH3N/")]
        self.assertNotEqual(quad_grp, tri_grp)
        self.assertEqual(cells[3], str(quad_grp))   # grshel_ID
        self.assertEqual(cells[7], str(tri_grp))    # grsh3n_ID
        self.assertEqual(tstop, 0.004)
        self.assertEqual(_ids_of_group(starter, f"/GRSHEL/SHEL/{quad_grp}"),
                         [201])
        self.assertEqual(_ids_of_group(starter, f"/GRSH3N/SH3N/{tri_grp}"),
                         [202])

    def test_thick_shell_lands_in_the_brick_group(self):
        """k2rad writes a thick shell as a /BRICK, so its id is in
        solid_elem_ids and /GRBRIC/BRIC resolves it."""
        deck = TSHELL_MESH.replace("{EXTRA}",
                                   "*DEFINE_ELEMENT_DEATH_THICK_SHELL\n"
                                   + _row(101, 0.005) + "\n")
        _res, starter, _eng = _convert(deck)
        (activ_id,) = _activ_ids(starter)
        cells, _ts, tstop = _activ(starter, activ_id)
        (grp,) = [int(ln.rsplit("/", 1)[1])
                  for ln in _headers(starter, "/GRBRIC/BRIC/")]
        self.assertEqual(cells[1], str(grp))
        self.assertEqual(tstop, 0.005)
        self.assertEqual(_ids_of_group(starter, f"/GRBRIC/BRIC/{grp}"), [101])

    def test_beam_rerouted_to_a_spring_uses_the_spring_slot(self):
        """A *SECTION_BEAM ELFORM=6 discrete beam is emitted as a /SPRING, so
        its death group must be /GRSPRI/SPRI in the grspr_ID column — keyed on
        the PRODUCER-specific re-route registries, not on the /SPRING union."""
        deck = MESH.replace("{EXTRA}",
                            "*PART\n"
                            "dbeam\n"
                            + _row(3, 3, 3) + "\n"
                            "*SECTION_BEAM\n"
                            + _row(3, 6) + "\n"
                            + _row(1.0, 1.0, 1.0, 1.0, 1.0, 1.0) + "\n"
                            "*MAT_LINEAR_ELASTIC_DISCRETE_BEAM\n"
                            + _row(3, "7.85E-9", 1000.0, 1000.0, 1000.0,
                                   100.0, 100.0, 100.0) + "\n"
                            "*ELEMENT_BEAM\n"
                            + _row(301, 3, 9, 11, 0) + "\n"
                            "*DEFINE_ELEMENT_DEATH_BEAM\n"
                            + _row(301, 0.006) + "\n")
        _res, starter, _eng = _convert(deck)
        (activ_id,) = _activ_ids(starter)
        cells, _ts, tstop = _activ(starter, activ_id)
        spri = _headers(starter, "/GRSPRI/SPRI/")
        self.assertEqual(len(spri), 1, starter)
        grp = int(spri[0].rsplit("/", 1)[1])
        self.assertEqual(cells[6], str(grp))    # grspr_ID, NOT grbeam_ID
        self.assertEqual(cells[5], "0")
        self.assertEqual(tstop, 0.006)
        self.assertEqual(_ids_of_group(starter, f"/GRSPRI/SPRI/{grp}"), [301])

    def test_zero_time_is_refused_not_inverted(self):
        """LS-DYNA TIME=0 = delete at t=0; Radioss Tstop=0 = never
        (hm_read_activ.F:139). Copying it through inverts the card."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID\n"
                            + _row(101) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/ACTIV/"), [])
        self.assertTrue(_warn_containing(res, "TIME = 0",
                                         "hm_read_activ.F:139"))

    def test_boxid_beside_a_positive_time_keeps_the_time_criterion(self):
        """BOXID and TIME are two INDEPENDENT criteria.

        Vol I R17 p.17-251: the elements are considered for deletion "either
        by meeting the BOXID/INOUT criterion OR the independent
        TIME/IDGRP/PERCENT criterion", and TIME is switched off only when it
        is ZERO ("If BOXID is nonzero, a TIME value of zero is reset to
        1e16"). So a nonzero TIME still converts and only the spatial half is
        lost — the same policy the IDGRP criterion gets.
        """
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID\n"
                            + _row(101, 0.003, 55, 1, 0, 7) + "\n")
        res, starter, _eng = _convert(deck)
        (activ_id,) = _activ_ids(starter)
        _cells, tstart, tstop = _activ(starter, activ_id)
        self.assertEqual((tstart, tstop), (0.0, 0.003))
        w = _warn_containing(res, "BOXID = 55")
        self.assertTrue(w)
        self.assertIn("INOUT = 1", w[0])
        self.assertIn("CID = 7", w[0])
        self.assertIn("min(box crossing, TIME = 0.003)", w[0])

    def test_boxid_with_a_zero_time_is_refused_by_name(self):
        """With BOXID nonzero LS-DYNA resets a zero TIME to 1e16, so the card
        really is box-only and nothing is expressible."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID\n"
                            + _row(101, 0, 55, 1, 0, 7) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/ACTIV/"), [])
        w = _warn_containing(res, "BOXID = 55")
        self.assertTrue(w)
        self.assertIn("reset to 1e16", w[0])

    def test_the_contact_note_states_the_idel_k2rad_actually_writes(self):
        """k2rad hard-codes Idel=2 on TYPE7/TYPE25, so the note must not claim
        a default of 0 — and the real reason the segments stay is that
        desacti.F/eloff.F never arm IDEL7NOK."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID\n"
                            + _row(101, 0.003) + "\n")
        res, _starter, _eng = _convert(deck)
        (w,) = _warn_containing(res, "carrying contact")
        self.assertIn("Idel=2", w)
        self.assertIn("IDEL7NOK", w)
        self.assertNotIn("Idel=0", w)
        # The 4-node shell OFFG asymmetry is a user-visible /TH trap (#122):
        # eloff.F:479 keeps |OFFG| for ITY==3 while :418 (the IGBR
        # pre-loop), :522 and :565 zero the
        # solids, beams and /SH3N, and the channel then freezes.
        self.assertIn("FREEZE", w)
        self.assertIn("eloff.F", w)

    def test_thick_shell_set_does_not_adopt_a_shell_set(self):
        """*SET_TSHELL, *SET_SOLID and *SET_SHELL are three separate LS-DYNA
        SID namespaces; a *SET_SHELL cannot hold a thick-shell id."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_SHELL_LIST\n" + _row(700) + "\n"
                            + _row(201, 202) + "\n"
                            "*DEFINE_ELEMENT_DEATH_THICK_SHELL_SET\n"
                            + _row(700, 0.004) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/ACTIV/"), [])
        self.assertEqual(_headers(starter, "/GRBRIC/BRIC/"), [])
        self.assertTrue(_warn_containing(res, "*SET_TSHELL", "was not found"))

    def test_idgrp_and_percent_are_named_but_the_time_card_survives(self):
        """TIME and IDGRP/PERCENT are two INDEPENDENT criteria (Vol I R17
        p.17-251), so the time half still converts."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID\n"
                            + _row(101, 0.003, 0, 0, 9, 0, 40.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(len(_headers(starter, "/ACTIV/")), 1)
        self.assertTrue(_warn_containing(res, "IDGRP = 9", "PERCENT = 40"))

    def test_dangling_element_is_dropped_with_a_warning(self):
        """A group naming an element the deck never emits is starter ERROR
        69 and refuses the whole run."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_SHELL_LIST\n" + _row(700) + "\n"
                            + _row(201, 999) + "\n"
                            "*DEFINE_ELEMENT_DEATH_SHELL_SET\n"
                            + _row(700, 0.004) + "\n")
        res, starter, _eng = _convert(deck)
        (quad_grp,) = [int(ln.rsplit("/", 1)[1])
                       for ln in _headers(starter, "/GRSHEL/SHEL/")]
        self.assertEqual(_ids_of_group(starter, f"/GRSHEL/SHEL/{quad_grp}"),
                         [201])
        self.assertTrue(_warn_containing(res, "999", "ERROR 69"))

    def test_missing_set_drops_the_card(self):
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_ELEMENT_DEATH_SOLID_SET\n"
                            + _row(4242, 0.003) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/ACTIV/"), [])
        self.assertTrue(_warn_containing(res, "element set 4242"))

    def test_short_r6_layout_is_read_by_column(self):
        """FORMAT(Keyword971_R6.1) has four fields; the trailing cells are
        simply absent, not different."""
        state = _dispatch("*KEYWORD\n*DEFINE_ELEMENT_DEATH_BEAM_SET\n"
                          + _row(12, 0.25) + "\n*END\n")
        (rec,) = state.element_deaths
        self.assertEqual((rec.family, rec.is_set, rec.eid, rec.time),
                         ("BEAM", True, 12, 0.25))
        self.assertEqual((rec.boxid, rec.inout, rec.idgrp, rec.cid,
                          rec.percent), (0, 0, 0, 0, 0.0))

    def test_title_option_is_stripped_by_the_parser(self):
        state = _dispatch("*KEYWORD\n*DEFINE_ELEMENT_DEATH_SHELL_TITLE\n"
                          "a shell that dies\n"
                          + _row(7, 0.5) + "\n*END\n")
        (rec,) = state.element_deaths
        self.assertEqual((rec.family, rec.is_set, rec.eid), ("SHELL", False, 7))
        self.assertEqual(rec.title, "a shell that dies")


# ═════════════════════════════════════════════════════════════════════════════
# *DEFINE_CURVE_SMOOTH → /FUNCT_SMOOTH
# ═════════════════════════════════════════════════════════════════════════════

SMOOTH_CONSUMER = (
    "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
    + _row(600, 3, 0, 900, 1.0) + "\n"
    "*SET_NODE_LIST\n" + _row(600) + "\n" + _row(9, 10) + "\n"
)


class CurveSmoothTests(unittest.TestCase):

    def test_closed_form_backsolves_both_directions_exactly(self):
        """DIST = VMAX*(TEND-TSTART-TRISE) — the SAME closed form on both
        sides, so no conversion factor (#128). Both branches are its exact
        inverses."""
        pts, vmax, tend, _note = smooth_curve_points(9.0, 0.0, 0.03, 0.005, 0.0)
        self.assertAlmostEqual(vmax, 360.0, places=9)
        self.assertAlmostEqual(tend, 0.03, places=12)
        self.assertEqual([round(x, 12) for x, _y in pts],
                         [0.0, 0.005, 0.025, 0.03])
        self.assertEqual([round(y, 6) for _x, y in pts],
                         [0.0, 360.0, 360.0, 0.0])
        # trapezoid area == DIST
        area = sum(0.5 * (pts[i + 1][0] - pts[i][0]) * (pts[i][1] + pts[i + 1][1])
                   for i in range(3))
        self.assertAlmostEqual(area, 9.0, places=9)
        # the other direction
        pts2, vmax2, tend2, _n2 = smooth_curve_points(9.0, 0.0, 0.0, 0.005,
                                                      360.0)
        self.assertAlmostEqual(tend2, 0.03, places=12)
        self.assertEqual(vmax2, 360.0)
        self.assertEqual([round(x, 12) for x, _y in pts2],
                         [0.0, 0.005, 0.025, 0.03])

    def test_card_is_column_exact(self):
        """funct_smooth.cfg:52-62 — title, then Ascalex/Fscaley/Ashiftx/
        Fshifty at %20lg, then the X-Y pairs."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH_TITLE\n"
                            "tool velocity\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + SMOOTH_CONSUMER)
        _res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/FUNCT_SMOOTH/900")
        self.assertEqual(body[0], "tool velocity")
        scale = [body[1][i:i + 20].strip() for i in range(0, 80, 20)]
        self.assertEqual(scale, ["1", "1", "0", "0"])
        self.assertEqual(_smooth_points(starter, 900),
                         [(0.0, 0.0), (0.005, 360.0), (0.025, 360.0),
                          (0.03, 0.0)])
        # and NOT a plain /FUNCT on the same id
        self.assertEqual(_headers(starter, "/FUNCT/900"), [])

    def test_the_id_resolves_for_a_prescribed_motion_consumer(self):
        """The measured master defect: the LCID was skipped, the /IMPVEL was
        still emitted, and the starter answered ERROR 120 WRONG REFERENCE TO
        FUNCTION ID."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + SMOOTH_CONSUMER)
        _res, starter, _eng = _convert(deck)
        (imp,) = _headers(starter, "/IMPVEL/")
        row = _data_rows(starter, imp.strip())[1]
        self.assertEqual(int(row[0:10]), 900)
        self.assertTrue(_headers(starter, "/FUNCT_SMOOTH/900"))

    def test_id_joins_the_funct_and_table_namespace(self):
        """/FUNCT, /FUNCT_SMOOTH and /TABLE share ONE starter id table
        (measured ERROR 79). A collision must be named."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + SMOOTH_CONSUMER
                            + "*DEFINE_TABLE_2D\n"
                            + _row(900, 1.0, 0.0) + "\n"
                            + "                 0.0               901\n"
                            + "*DEFINE_CURVE\n"
                            + _row(901, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
                            "                 0.0                 0.0\n"
                            "                 1.0                 1.0\n")
        res, _starter, _eng = _convert(deck)
        self.assertTrue(_warn_containing(res, "CURVE ID 900", "ERROR 79"))

    def test_synthesized_curve_ids_dodge_a_smooth_curve(self):
        """next_curve_id() must skip a /FUNCT_SMOOTH id — it lives in
        state.curves, so the existing dodge covers it with no new registry."""
        state = ConversionState()
        state._auto_id = 90001
        deck_state = _dispatch("*KEYWORD\n*DEFINE_CURVE_SMOOTH\n"
                               + _row(90001, 0, 9.0, 0.0, 0.03, 0.005, 0.0)
                               + "\n*END\n")
        state.curves.update(deck_state.curves)
        state.funct_smooth_ids |= deck_state.funct_smooth_ids
        self.assertIn(90001, state.curves)
        self.assertNotEqual(state.next_curve_id(), 90001)

    def test_zero_trise_is_nudged_not_refused(self):
        """A collapsed trapezoid is starter ERROR 156 (non-increasing
        abscissa). The vertices are separated on the CARD value (#113)."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.0, 0.0) + "\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        pts = _smooth_points(starter, 900)
        xs = [x for x, _y in pts]
        self.assertEqual(len(xs), 4)
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(set(xs)), 4)          # strictly increasing
        self.assertEqual([y for _x, y in pts], [0.0, 300.0, 300.0, 0.0])
        self.assertTrue(_warn_containing(res, "TRISE = 0", "ERROR 156"))

    def test_zero_dist_is_named_as_an_identically_zero_curve(self):
        """Every field on this card has default 'none' (Vol I R17 p.17-153),
        and DIST is the only thing that sets the curve's height — a blank one
        emits a legal, accepted card that moves nothing (#122).

        VMAX BLANK here, which is the only arm where "identically zero" is
        true; the stated-VMAX arm is refused instead (next test)."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 0.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        self.assertEqual([y for _x, y in _smooth_points(starter, 900)],
                         [0.0, 0.0, 0.0, 0.0])
        self.assertTrue(_warn_containing(res, "DIST = 0",
                                         "identically zero"))

    def test_zero_dist_with_a_stated_vmax_is_refused_not_called_zero(self):
        """The OTHER arm. With VMAX stated the back-solve is
        TEND = DIST/VMAX + TSTART + TRISE, so DIST = 0 collapses TEND onto
        TSTART+TRISE and _strictly_increasing nudges the duplicated abscissae
        into a VMAX-HEIGHT SPIKE — the deck's own TEND is discarded. Calling
        that "identically zero ... does not move at all" would be the #122
        class in the under-alarming direction, so the card is refused by name
        the way the three sibling degeneracies on the other arm are."""
        pts, _vmax, _tend, note = smooth_curve_points(0.0, 0.0, 0.01,
                                                      0.002, 50.0)
        self.assertIsNone(pts)
        self.assertIn("DIST = 0", note)
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 0.0, 0.0, 0.01, 0.002, 50.0) + "\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/FUNCT_SMOOTH/"), [])
        self.assertEqual(_warn_containing(res, "identically zero"), [])
        self.assertTrue(_warn_containing(res, "DIST = 0",
                                         "collapses the window"))

    def test_a_dist_that_contradicts_vmax_in_sign_is_refused(self):
        """DIST/VMAX < 0 puts TEND before TSTART+TRISE — the same "the
        trapezoid runs backwards" the VMAX-blank arm refuses as a negative
        span, reached from the other side. Left unrefused it emitted a spike
        under a NEGATIVE back-solved TEND (measured: -0.025)."""
        pts, _vmax, _tend, note = smooth_curve_points(-9.0, 0.0, 0.0,
                                                      0.005, 300.0)
        self.assertIsNone(pts)
        self.assertIn("NEGATIVE", note)
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, -9.0, 0.0, 0.0, 0.005, 300.0) + "\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/FUNCT_SMOOTH/"), [])
        self.assertTrue(_warn_containing(res, "DIST/VMAX", "NEGATIVE"))
        # A DIST and a VMAX that agree in sign are a legitimate downward
        # trapezoid and still convert.
        pts2, _v2, tend2, _n2 = smooth_curve_points(-9.0, 0.0, 0.0,
                                                    0.005, -300.0)
        self.assertIsNotNone(pts2)
        self.assertAlmostEqual(tend2, 0.035, places=12)

    def test_both_blank_is_refused_by_name(self):
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.0, 0.005, 0.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/FUNCT_SMOOTH/"), [])
        self.assertTrue(_warn_containing(res, "neither TEND nor VMAX"))

    def test_the_d2r_divide_by_zero_gap_is_guarded(self):
        """VMAX=0, TEND!=0, TEND-TSTART-TRISE==0: no dyna2rad branch fires and
        it emits an all-zero flat curve silently (convertcurves.cxx:325)."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.01, 0.03, 0.02, 0.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/FUNCT_SMOOTH/"), [])
        self.assertTrue(_warn_containing(res, "divides by zero"))

    def test_sidr_is_named(self):
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 1, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + SMOOTH_CONSUMER)
        res, _starter, _eng = _convert(deck)
        self.assertTrue(_warn_containing(res, "SIDR = 1"))

    def test_unresolved_parameter_expression_is_named(self):
        """The one corpus carrier writes TRISE as '&tend/6.0'; the parser
        resolves a bare '&name' only, so the cell reads back as 0."""
        deck = MESH.replace("{EXTRA}",
                            "*PARAMETER\n"
                            "R tend     3.0e-2\n"
                            "R dist        9.0\n"
                            "*DEFINE_CURVE_SMOOTH\n"
                            "       900         0&dist            0.0"
                            "&tend     &tend/6.0        0.0\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        self.assertTrue(_warn_containing(res, "TRISE", "*PARAMETER"))
        pts = _smooth_points(starter, 900)
        self.assertEqual([y for _x, y in pts], [0.0, 300.0, 300.0, 0.0])
        # The consequence has to be a NUMBER, not just a principle: this deck
        # ships a 300 mm/s plateau where the deck meant 360.
        (w,) = _warn_containing(res, "plateau of VMAX")
        self.assertIn("VMAX = 300", w)

    def test_a_later_define_curve_on_the_same_id_clears_the_smooth_flag(self):
        """The emitted card kind must match the points that survive: a plain
        piecewise-linear curve read as /FUNCT_SMOOTH is quintic-blended and
        blended: fixfingeo.F:199 / fixvel.F:316 dispatch on ISMOOTH."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + "*DEFINE_CURVE\n"
                            + _row(900, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
                            "                 0.0                 0.0\n"
                            "                0.03                 1.0\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/FUNCT_SMOOTH/900"), [])
        self.assertEqual(_headers(starter, "/FUNCT/900"), ["/FUNCT/900"])
        self.assertTrue(_warn_containing(res, "*DEFINE_CURVE LCID 900",
                                         "already defined this id"))

    def test_a_later_define_curve_function_also_clears_the_smooth_flag(self):
        """The SIBLING producer, which the guard was dead on (#124).
        *DEFINE_CURVE_FUNCTION overwrites state.curves[lcid] with SAMPLED
        piecewise-linear points; leaving the flag set emitted a 101-point
        ramp as /FUNCT_SMOOTH, which fixfingeo.F:199 / fixvel.F:316 then read
        quintic-blended — and the deck-wide duplicate-id text scan cannot fire
        either, because it sees only one *DEFINE_CURVE_SMOOTH header."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + "*DEFINE_CURVE_FUNCTION\n"
                            + _row(900) + "\n"
                            "100.0*x\n"
                            + SMOOTH_CONSUMER)
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/FUNCT_SMOOTH/900"), [])
        self.assertEqual(_headers(starter, "/FUNCT/900"), ["/FUNCT/900"])
        self.assertTrue(_warn_containing(res,
                                         "*DEFINE_CURVE_FUNCTION LCID 900",
                                         "already defined this id"))

    def test_a_duplicate_smooth_id_is_named(self):
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE\n"
                            + _row(900, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
                            "                 0.0                 0.0\n"
                            "                0.03                 1.0\n"
                            + "*DEFINE_CURVE_SMOOTH\n"
                            + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
                            + SMOOTH_CONSUMER)
        res, _starter, _eng = _convert(deck)
        self.assertTrue(_warn_containing(res, "*DEFINE_CURVE_SMOOTH LCID 900",
                                         "already defined by a *DEFINE_CURVE"))

    def test_a_smooth_curve_is_not_a_legacy_table_row(self):
        """state.curve_order resolves the LEGACY positional *DEFINE_TABLE, and
        the manual scopes that to *DEFINE_CURVE sections by name (Vol I R17
        p.17-444). A smooth curve after the table is not one of its rows."""
        state = _dispatch("*KEYWORD\n*DEFINE_CURVE_SMOOTH\n"
                          + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0)
                          + "\n*END\n")
        self.assertIn(900, state.curves)
        self.assertIn(900, state.funct_smooth_ids)
        self.assertNotIn(900, state.curve_order)


# ═════════════════════════════════════════════════════════════════════════════
# *PERTURBATION_NODE → /RANDOM
# ═════════════════════════════════════════════════════════════════════════════

NSET = "*SET_NODE_LIST\n" + _row(600) + "\n" + _row(1, 2, 3) + "\n"


class PerturbationNodeTests(unittest.TestCase):

    def test_type8_dtype1_is_an_exact_match(self):
        """DTYPE=1 is uniform on SCL x [-AMPL, AMPL]; ALEAT() is symmetric on
        (-XALEA, +XALEA), so XALEA = SCL*AMPL."""
        deck = MESH.replace("{EXTRA}",
                            NSET
                            + "*PERTURBATION_NODE\n"
                            + _row(8, 600, 2.0, 7, 0, 0) + "\n"
                            + _row(0.5, 1.0) + "\n")
        _res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/RANDOM/GRNOD/600")
        cells = [body[0][i:i + 20].strip() for i in range(0, 40, 20)]
        self.assertEqual(cells[0], "1")            # XALEA = 2.0 * 0.5
        self.assertEqual(float(cells[1]), 0.5)     # SEED, in (0,1)

    def test_type8_dtype0_halves_the_amplitude_and_says_so(self):
        """DTYPE=0 (the DEFAULT) is one-sided on SCL x [0, AMPL]: XALEA =
        SCL*AMPL/2 reproduces the zero-mean noise and drops only the rigid
        shift. dyna2rad ignores DTYPE and doubles the spread."""
        deck = MESH.replace("{EXTRA}",
                            NSET
                            + "*PERTURBATION_NODE\n"
                            + _row(8, 600, 2.0, 7, 0, 0) + "\n"
                            + _row(0.5) + "\n")
        res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/RANDOM/GRNOD/600")
        self.assertEqual(body[0][0:20].strip(), "0.5")
        self.assertTrue(_warn_containing(res, "DTYPE = 0", "SCL*AMPL/2"))

    def test_nsid_zero_is_the_global_card(self):
        deck = MESH.replace("{EXTRA}",
                            "*PERTURBATION_NODE\n"
                            + _row(8, 0, 1.0, 7, 0, 0) + "\n"
                            + _row(0.25, 1.0) + "\n")
        _res, starter, _eng = _convert(deck)
        self.assertTrue(_headers(starter, "/RANDOM"))
        self.assertEqual(_headers(starter, "/RANDOM/GRNOD/"), [])
        body = _data_rows(starter, "/RANDOM")
        self.assertEqual(body[0][0:20].strip(), "0.25")

    def test_global_and_grouped_cannot_coexist(self):
        """hm_read_rand.F:152/156/175 leaves BOTH branches unexecuted when a
        deck holds one of each — measured, zero perturbation at zero
        diagnostics."""
        deck = MESH.replace("{EXTRA}",
                            NSET
                            + "*PERTURBATION_NODE\n"
                            + _row(8, 0, 1.0, 7, 0, 0) + "\n"
                            + _row(0.25, 1.0) + "\n"
                            + "*PERTURBATION_NODE\n"
                            + _row(8, 600, 1.0, 7, 0, 0) + "\n"
                            + _row(0.5, 1.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(len(_headers(starter, "/RANDOM")), 1)
        self.assertEqual(_headers(starter, "/RANDOM/GRNOD/"), [])
        self.assertTrue(_warn_containing(res, "cannot coexist"))

    def test_two_global_cards_collapse_to_the_largest_amplitude(self):
        """hm_read_rand.F:135-136 OVERWRITES the module-level XALEA on every
        all-nodes record and :156-163 applies it once, so a second global card
        makes the first inert. LS-DYNA instead SUMS them (Vol I R17 p.38-10
        Remark 2)."""
        deck = MESH.replace("{EXTRA}",
                            "*PERTURBATION_NODE\n"
                            + _row(8, 0, 1.0, 7, 0, 0) + "\n"
                            + _row(0.25, 1.0) + "\n"
                            + "*PERTURBATION_NODE\n"
                            + _row(8, 0, 1.0, 7, 0, 0) + "\n"
                            + _row(0.75, 1.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(len(_headers(starter, "/RANDOM")), 1)
        body = _data_rows(starter, "/RANDOM")
        self.assertEqual(body[0][0:20].strip(), "0.75")
        (w,) = _warn_containing(res, "all-nodes cards")
        self.assertIn("XALEA = 0.75", w)
        self.assertIn("XALEA = 0.25", w)

    def test_other_types_are_warn_dropped_by_name(self):
        for ptype, needle in ((1, "HARMONIC"), (2, "FADE"),
                              (3, "READ FROM A FILE"), (4, "SPECTRAL")):
            with self.subTest(ptype=ptype):
                deck = MESH.replace("{EXTRA}",
                                    NSET
                                    + "*PERTURBATION_NODE\n"
                                    + _row(ptype, 600, 1.0, 7, 0, 0) + "\n"
                                    + _row(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                                    + "\n")
                res, starter, _eng = _convert(deck)
                self.assertEqual(_headers(starter, "/RANDOM"), [])
                self.assertTrue(_warn_containing(res, f"TYPE = {ptype}",
                                                 needle))

    def test_cmp_and_icoord_are_named(self):
        deck = MESH.replace("{EXTRA}",
                            NSET
                            + "*PERTURBATION_NODE\n"
                            + _row(8, 600, 1.0, 1, 2, 55) + "\n"
                            + _row(0.5, 1.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertTrue(_headers(starter, "/RANDOM/GRNOD/600"))
        self.assertTrue(_warn_containing(res, "CMP = 1"))
        self.assertTrue(_warn_containing(res, "ICOORD = 2", "CID = 55"))

    def test_dangling_node_set_drops_the_card(self):
        deck = MESH.replace("{EXTRA}",
                            "*PERTURBATION_NODE\n"
                            + _row(8, 4242, 1.0, 7, 0, 0) + "\n"
                            + _row(0.5, 1.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/RANDOM"), [])
        self.assertTrue(_warn_containing(res, "*SET_NODE 4242", "ERROR 173"))

    def test_blank_card_two_holds_its_position(self):
        """An all-blank card 2 is legal (AMPL defaults to 1.0, DTYPE to 0.0)
        and must not make the walker step onto the next keyword (#119)."""
        state = _dispatch("*KEYWORD\n*PERTURBATION_NODE\n"
                          + _row(8, 600, 3.0, 7, 0, 0) + "\n"
                          + "\n"
                          "*SET_NODE_LIST\n" + _row(600) + "\n"
                          + _row(1, 2) + "\n*END\n")
        (rec,) = state.perturbation_nodes
        self.assertEqual((rec.ptype, rec.nsid, rec.scl), (8, 600, 3.0))
        self.assertEqual((rec.ampl, rec.dtype), (1.0, 0.0))
        self.assertEqual(sorted(state.node_sets), [600])

    def test_siblings_are_recognized_warn_drops(self):
        for kw in ("PERTURBATION_MAT", "PERTURBATION_SHELL_THICKNESS"):
            with self.subTest(kw=kw):
                deck = MESH.replace("{EXTRA}",
                                    f"*{kw}\n" + _row(1, 1, 1.0, 5, 0, 0)
                                    + "\n" + _row(1.0, 0.0) + "\n")
                res, _starter, _eng = _convert(deck)
                self.assertNotIn(kw, res.skipped_keywords)
                self.assertIn(kw, [k for k, _r in res.recognized_not_emitted])


# ═════════════════════════════════════════════════════════════════════════════
# *BOUNDARY_PRESCRIBED_FINAL_GEOMETRY → /IMPDISP/FGEO
# ═════════════════════════════════════════════════════════════════════════════

class FinalGeometryTests(unittest.TestCase):

    def test_card_is_column_exact(self):
        """impdisp_fgeo.cfg:118-145 — fct_ID/part_ID/blank/sens_ID at %10d,
        Ascale/blank/Tstart/Tstop at %20lg, then node_IDN + three %20lg."""
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.006, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n")
        _res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/IMPDISP/FGEO/800")
        self.assertEqual(body[0], "FINAL_GEOMETRY_800")
        head = [body[1][i:i + 10].strip() for i in range(0, 40, 10)]
        self.assertEqual(head, ["901", "0", "", "0"])
        times = [body[2][i:i + 20].strip() for i in range(0, 80, 20)]
        self.assertEqual(times, ["1", "", "0", "0.006"])
        self.assertEqual(body[3][0:10].strip(), "9")
        self.assertEqual([body[3][i:i + 20].strip()
                          for i in range(10, 70, 20)], ["25", "0", "0"])

    def test_per_row_lcid_and_death_split_the_card(self):
        """Radioss carries ONE fct_ID and one Tstart/Tstop per card; LS-DYNA
        lets every node state its own, and the per-row value wins when
        nonzero (Vol I R17 p.5-75). dyna2rad reads neither."""
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*DEFINE_CURVE\n"
                            + _row(902, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
                            "                 0.0                 0.0\n"
                            "               0.005                 1.0\n"
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.006, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n"
                            + _fgeo_row(10, 25.0, 10.0, 0.0, 902, 0.008)
                            + "\n")
        res, starter, _eng = _convert(deck)
        heads = _headers(starter, "/IMPDISP/FGEO/")
        self.assertEqual(len(heads), 2)
        by_curve = {}
        for h in heads:
            body = _data_rows(starter, h.strip())
            fct = int(body[1][0:10])
            tstop = float(body[2][60:80])
            nids = [int(ln[0:10]) for ln in body[3:]]
            by_curve[fct] = (tstop, nids)
        self.assertEqual(by_curve[901], (0.006, [9]))
        self.assertEqual(by_curve[902], (0.008, [10]))
        self.assertTrue(_warn_containing(res, "2 distinct"))

    def test_negative_nid_projects_the_set_it_does_not_collapse_it(self):
        """|NID| is a node set 'displaced ... to the projected points on the
        xy-plane with Z offset' — each member keeps its own x and y.
        dyna2rad writes one point for the whole set."""
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*SET_NODE_LIST\n" + _row(600) + "\n"
                            + _row(9, 10) + "\n"
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.006, 0) + "\n"
                            + _fgeo_row(-600, 0.0, 0.0, 7.5) + "\n")
        res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/IMPDISP/FGEO/800")
        rows = {int(ln[0:10]): tuple(float(ln[i:i + 20])
                                     for i in range(10, 70, 20))
                for ln in body[3:]}
        self.assertEqual(rows[9], (20.0, 0.0, 7.5))
        self.assertEqual(rows[10], (20.0, 10.0, 7.5))
        self.assertTrue(_warn_containing(res, "projects", "KEEPING its own"))

    def test_birth_sets_tstart_and_pre_shifts_the_curve(self):
        """LS-DYNA BIRTH does BOTH ('the abscissa values are shifted by an
        amount BIRTH ... same effect as OFFA = BIRTH'); the Radioss Tstart is
        a pure gate (fixfingeo.F:155/168)."""
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.0, 1) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0, 0, 0.0, 0.002)
                            + "\n")
        res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/IMPDISP/FGEO/800")
        fct = int(body[1][0:10])
        self.assertNotEqual(fct, 901)
        self.assertEqual(float(body[2][40:60]), 0.002)      # Tstart = BIRTH
        pts = [(float(ln[0:20]), float(ln[20:40]))
               for ln in _data_rows(starter, f"/FUNCT/{fct}")[1:]]
        self.assertEqual(pts, [(0.002, 0.0), (0.012, 1.0)])
        self.assertTrue(_warn_containing(res, "BIRTH = 0.002", "OFFA"))

    def test_the_birth_copy_of_a_smooth_curve_stays_smooth(self):
        """A *DEFINE_CURVE_SMOOTH re-emitted as a plain /FUNCT loses ISMOOTH,
        and fixfingeo.F:196-199 then picks FINTER2 instead of FINTER2_SMOOTH,
        so the quintic blend becomes piecewise-linear (measured f = 0.1036 vs
        the plain twin's 0.2503 at u = 0.25). NOT a clamp question on this
        path: FINTER2_SMOOTH (finter_smooth.F:116-152) has none either, so the
        smooth copy runs FURTHER past the curve, not less."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(901, 0, 1.0, 0.0, 0.01, 0.002, 0.0) + "\n"
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.0, 1) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0, 0, 0.0, 0.002)
                            + "\n")
        res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/IMPDISP/FGEO/800")
        fct = int(body[1][0:10])
        self.assertNotEqual(fct, 901)
        self.assertEqual(_headers(starter, f"/FUNCT/{fct}"), [])
        self.assertEqual(_headers(starter, f"/FUNCT_SMOOTH/{fct}"),
                         [f"/FUNCT_SMOOTH/{fct}"])
        # Every abscissa shifted by +BIRTH, ordinates untouched.
        self.assertEqual([x for x, _y in _smooth_points(starter, fct)],
                         [x + 0.002 for x, _y in _smooth_points(starter, 901)])
        self.assertTrue(_warn_containing(res, f"/FUNCT_SMOOTH/{fct}"))

    def test_a_driver_curve_outside_zero_to_one_is_named(self):
        """fixfingeo.F:243-256 computes X(t) = X0 + f(t)*(Xf - X0) with NO
        clamp, so a curve that is not the 0 -> 1 scale factor of Vol I R17
        p.5-73 sends the node somewhere else entirely — measured: a *DEFINE_
        CURVE_SMOOTH plateau of 200 drove a 1 mm offset to 98 mm."""
        deck = MESH.replace("{EXTRA}",
                            "*DEFINE_CURVE_SMOOTH\n"
                            + _row(901, 0, 1.0, 0.0, 0.006, 0.001) + "\n"
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.0, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertTrue(_headers(starter, "/IMPDISP/FGEO/800"))
        (w,) = _warn_containing(res, "is not the 0 -> 1 scale factor")
        self.assertIn("end at 0", w)
        self.assertIn("*DEFINE_CURVE_SMOOTH, which can never satisfy this", w)

    def test_two_cards_on_one_curve_are_both_range_checked(self):
        """The de-duplication is per (CARD, curve), not per DECK: the warning
        quotes the BPFGID, so a set hoisted out of the card loop silently drops
        the diagnostic for every card after the first."""
        big = ("*DEFINE_CURVE\n"
               + _row(902, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
               "                 0.0                 0.0\n"
               "               0.005               200.0\n"
               "                0.01                 0.0\n")
        deck = MESH.replace("{EXTRA}",
                            big
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 902, 0.0, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n"
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(801, 902, 0.0, 0) + "\n"
                            + _fgeo_row(10, 25.0, 10.0, 0.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertTrue(_headers(starter, "/IMPDISP/FGEO/800"))
        self.assertTrue(_headers(starter, "/IMPDISP/FGEO/801"))
        named = _warn_containing(res, "is not the 0 -> 1 scale factor")
        self.assertEqual(len(named), 2, named)
        self.assertTrue(_warn_containing(res, "BPFGID 800",
                                         "0 -> 1 scale factor"))
        self.assertTrue(_warn_containing(res, "BPFGID 801",
                                         "0 -> 1 scale factor"))

    def test_one_card_split_into_slices_is_range_checked_once(self):
        """The other half of the same rule: one deck card whose rows split
        into several /IMPDISP/FGEO must NOT repeat the diagnostic."""
        big = ("*DEFINE_CURVE\n"
               + _row(902, 0, 1.0, 1.0, 0.0, 0.0) + "\n"
               "                 0.0                 0.0\n"
               "               0.005               200.0\n"
               "                0.01                 0.0\n")
        deck = MESH.replace("{EXTRA}",
                            big
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 902, 0.0, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0, 902, 0.006) + "\n"
                            + _fgeo_row(10, 25.0, 10.0, 0.0, 902, 0.008)
                            + "\n")
        res, _starter, _eng = _convert(deck)
        self.assertEqual(
            len(_warn_containing(res, "is not the 0 -> 1 scale factor")), 1)

    def test_a_rigid_wall_impdisp_dodges_a_deck_bpfgid(self):
        """The OTHER direction of the one /IMPDISP namespace.
        *RIGIDWALL_GEOMETRIC_*_MOTION with OPT != 0 emits /IMPDISP and its
        writer section runs AFTER the FGEO one, so _make_impdisp_fgeo cannot
        screen it — it dodges the deck's BPFGIDs from its own side
        (state.next_impdisp_id). Without that the two land on one id, which
        hm_read_impvel.F:129's single UDOUBLE answers with ERROR 79."""
        rwall = ("*RIGIDWALL_GEOMETRIC_SPHERE_MOTION_ID\n"
                 "       505moving sphere\n"
                 + _row(600) + "\n"
                 + _row(1.0, 2.0, 3.0, 1.0, 2.0, 4.0) + "\n"
                 + _row(4.0) + "\n"
                 + _row(901, 1, 0.0, 1.0, 0.0) + "\n"
                 + "*SET_NODE_LIST\n" + _row(600) + "\n" + _row(1, 2) + "\n")
        _res, starter, _eng = _convert(MESH.replace("{EXTRA}", RAMP + rwall))
        (baseline,) = [int(ln.rsplit("/", 1)[1])
                       for ln in _headers(starter, "/IMPDISP/")]
        deck2 = MESH.replace(
            "{EXTRA}",
            RAMP + rwall
            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
            + _row(baseline, 901, 0.006, 0) + "\n"
            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n")
        _res2, starter2, _e2 = _convert(deck2)
        ids = [int(ln.rsplit("/", 1)[1])
               for ln in _headers(starter2, "/IMPDISP/")]
        self.assertEqual(len(ids), 2, ids)
        self.assertEqual(len(set(ids)), 2, ids)      # no ERROR 79 pair
        # The FGEO card keeps the BPFGID the deck states; the rigid wall is the
        # side that moves, because it mints its id and the deck does not.
        self.assertEqual(_headers(starter2, f"/IMPDISP/FGEO/{baseline}"),
                         [f"/IMPDISP/FGEO/{baseline}"])
        (rwall_id,) = [i for i in ids
                       if not _headers(starter2, f"/IMPDISP/FGEO/{i}")]
        self.assertNotEqual(rwall_id, baseline)

    def test_a_zero_to_one_ramp_raises_no_range_warning(self):
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.0, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n")
        res, _starter, _eng = _convert(deck)
        self.assertEqual(_warn_containing(res, "0 -> 1 scale factor"), [])

    def test_bpfgid_dodges_an_existing_impdisp_id(self):
        """/IMPDISP and /IMPDISP/FGEO are ONE starter id namespace:
        hm_read_impvel.F:129 runs a single UDOUBLE over the merged NOM_OPT
        slice, so a BPFGID landing on a synthesized /IMPDISP id is ERROR 79."""
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*SET_NODE_LIST\n" + _row(600) + "\n"
                            + _row(1, 2) + "\n"
                            + "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                            + _row(600, 3, 2, 901, 1.0) + "\n")
        _res, starter, _eng = _convert(deck)
        (existing,) = [int(ln.rsplit("/", 1)[1])
                       for ln in _headers(starter, "/IMPDISP/")]
        deck2 = MESH.replace("{EXTRA}",
                             RAMP
                             + "*SET_NODE_LIST\n" + _row(600) + "\n"
                             + _row(1, 2) + "\n"
                             + "*BOUNDARY_PRESCRIBED_MOTION_SET\n"
                             + _row(600, 3, 2, 901, 1.0) + "\n"
                             + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                             + _row(existing, 901, 0.006, 0) + "\n"
                             + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n")
        res, starter2, _e2 = _convert(deck2)
        ids = [int(ln.rsplit("/", 1)[1])
               for ln in _headers(starter2, "/IMPDISP/")]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertTrue(_warn_containing(res, f"BPFGID {existing}",
                                         "ERROR 79"))

    def test_missing_curve_drops_the_rows(self):
        deck = MESH.replace("{EXTRA}",
                            "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 4242, 0.006, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n")
        res, starter, _eng = _convert(deck)
        self.assertEqual(_headers(starter, "/IMPDISP/FGEO/"), [])
        self.assertTrue(_warn_containing(res, "load curve 4242"))

    def test_dangling_node_is_dropped(self):
        deck = MESH.replace("{EXTRA}",
                            RAMP
                            + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                            + _row(800, 901, 0.006, 0) + "\n"
                            + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n"
                            + _fgeo_row(9999, 1.0, 2.0, 3.0) + "\n")
        res, starter, _eng = _convert(deck)
        body = _data_rows(starter, "/IMPDISP/FGEO/800")
        self.assertEqual([int(ln[0:10]) for ln in body[3:]], [9])
        self.assertTrue(_warn_containing(res, "node 9999"))

    def test_node_row_is_sliced_I8_E16_not_ten_wide(self):
        """A uniform 10-wide slice would start Y inside X (the *ELEMENT_MASS
        failure). Card 2b moves DEATH/BIRTH to E8 each."""
        cells = final_geometry_node_row(
            "     9001  1234.5678901234  2345.6789012345  3456.7890123456"
            "     901  0.0123456789012", 0)
        self.assertEqual(cells[:6], ["9001", "1234.5678901234",
                                     "2345.6789012345", "3456.7890123456",
                                     "901", "0.0123456789012"])
        cells_b = final_geometry_node_row(
            "     9001  1234.5678901234  2345.6789012345  3456.7890123456"
            "     901   0.006   0.002", 1)
        self.assertEqual(cells_b, ["9001", "1234.5678901234",
                                   "2345.6789012345", "3456.7890123456",
                                   "901", "0.006", "0.002"])

    def test_blank_row_inside_the_node_list_is_skipped(self):
        state = _dispatch("*KEYWORD\n"
                          "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                          + _row(800, 901, 0.006, 0) + "\n"
                          + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n"
                          + "\n"
                          + _fgeo_row(10, 25.0, 10.0, 0.0) + "\n"
                          "*END\n")
        (rec,) = state.final_geometries
        self.assertEqual([n.nid for n in rec.nodes], [9, 10])


# ═════════════════════════════════════════════════════════════════════════════
# *INTERFACE_SPRINGBACK_LSDYNA → the engine /DYNAIN block
# ═════════════════════════════════════════════════════════════════════════════

SPRINGBACK = (
    "*SET_PART_LIST\n" + _row(950) + "\n" + _row(2) + "\n"
    "*INTERFACE_SPRINGBACK_LSDYNA\n"
    + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n"
)


class SpringbackTests(unittest.TestCase):

    def test_engine_block_is_emitted_with_the_part_list(self):
        deck = MESH.replace("{EXTRA}", SPRINGBACK)
        _res, _starter, engine = _convert(deck)
        lines = engine.splitlines()
        i = lines.index("/DYNAIN/DT")
        self.assertEqual(lines[i + 1], "0.009 0.0002")
        self.assertEqual(lines[i + 2], "         2")
        self.assertEqual(lines[i + 3], "/DYNAIN/SHELL/STRES/FULL")
        self.assertEqual(lines[i + 4], "/DYNAIN/SHELL/STRAIN/FULL")

    def test_no_comment_between_the_time_card_and_the_part_ids(self):
        """check_dynain.F:144 re-parses this file FROM THE STARTER and feeds
        whatever follows the Tstart/Tfreq line into an (I10) READ: a comment
        or blank line there is 'forrtl: severe (64)' and the starter dies with
        no .out at all."""
        deck = MESH.replace("{EXTRA}", SPRINGBACK)
        _res, _starter, engine = _convert(deck)
        lines = engine.splitlines()
        i = lines.index("/DYNAIN/DT")
        self.assertTrue(lines[i + 2].strip().isdigit(), lines[i + 2])

    def test_part_ids_are_capped_at_ten_per_line(self):
        """fredynain.F reads the part ids into a fixed IV2(10)."""
        parts = "".join(
            f"*PART\np{p}\n{_row(p, 2, 1)}\n" for p in range(3, 20))
        # Each part needs a shell of its own: /DYNAIN writes shells only, so a
        # shell-less part is screened out of the list before it is printed.
        shells = ("*ELEMENT_SHELL\n"
                  + "".join(_row(300 + p, p, 1, 2, 3, 4) + "\n"
                            for p in range(3, 20)))
        pset = ("*SET_PART_LIST\n" + _row(950) + "\n"
                + _row(*range(3, 13)) + "\n" + _row(*range(13, 20)) + "\n")
        deck = MESH.replace("{EXTRA}",
                            parts + shells + pset
                            + "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n")
        _res, _starter, engine = _convert(deck)
        lines = engine.splitlines()
        i = lines.index("/DYNAIN/DT")
        id_lines = []
        for ln in lines[i + 2:]:
            if ln.startswith("/"):
                break
            id_lines.append(ln)
        self.assertTrue(id_lines)
        for ln in id_lines:
            self.assertLessEqual(len(ln.split()), 10, ln)

    def test_missing_part_set_falls_back_to_all(self):
        """A bare /DYNAIN/DT with an empty part list is starter ERROR 1909."""
        deck = MESH.replace("{EXTRA}",
                            "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(0, 0, 0, "", 0, 0, 0, 0) + "\n")
        res, _starter, engine = _convert(deck)
        self.assertIn("/DYNAIN/DT/ALL", engine)
        self.assertNotIn("\n/DYNAIN/DT\n", engine)
        self.assertTrue(_warn_containing(res, "ERROR 1909"))

    def test_a_shell_free_deck_emits_nothing(self):
        """/DYNAIN is SHELLS ONLY (fredynain.F:132-166); measured on a
        solid-only model it produces a legal, accepted, four-line stub."""
        deck = (MESH
                .replace("*ELEMENT_SHELL\n"
                         + _row(201, 2, 2, 3, 10, 9) + "\n"
                         + _row(202, 2, 9, 10, 11, 11) + "\n", "")
                .replace("{EXTRA}", SPRINGBACK))
        res, _starter, engine = _convert(deck)
        self.assertNotIn("/DYNAIN", engine)
        self.assertTrue(_warn_containing(res, "SHELLS ONLY"))

    def test_a_shell_less_part_is_dropped_from_the_part_list(self):
        """The shells-only rule is PER PART, not only deck-wide: a solid part
        named in the *SET_PART contributes nothing to the file."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_PART_LIST\n" + _row(950) + "\n"
                            + _row(1, 2) + "\n"
                            "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n")
        res, _starter, engine = _convert(deck)
        lines = engine.splitlines()
        i = lines.index("/DYNAIN/DT")
        # Part 1 is the solid part, part 2 the shell one.
        self.assertEqual(lines[i + 2].split(), ["2"])
        self.assertTrue(_warn_containing(res, "carry no /SHELL or /SH3N"))

    def test_an_all_solid_part_set_emits_nothing_and_does_not_widen(self):
        """A part list holding no shell is ACCEPTED and writes an EMPTY dynain
        (measured: 118 bytes of *NODE + *END at 0 ERROR / 0 WARNING) — the
        #122 class. Widening to /ALL would silently dump the whole model
        instead of the parts the deck asked for."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_PART_LIST\n" + _row(950) + "\n"
                            + _row(1) + "\n"
                            "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n")
        res, _starter, engine = _convert(deck)
        self.assertNotIn("/DYNAIN", engine)
        self.assertTrue(_warn_containing(res, "no part of *SET_PART 950 "
                                              "carries a shell"))

    def test_a_refused_card_still_names_its_dropped_fields(self):
        """A refusal is a reason not to emit a block, not a reason to stop
        accounting. The three `continue`s used to skip the dropped-field pass
        further down the loop, so NHSV/FTYPE/... on a refused card vanished
        without a word — README promises each is NAMED."""
        deck = MESH.replace("{EXTRA}",
                            "*SET_PART_LIST\n" + _row(950) + "\n"
                            + _row(1) + "\n"
                            "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(950, 3, 2, "", 4, 5, 6, 9) + "\n")
        res, _starter, engine = _convert(deck)
        self.assertNotIn("/DYNAIN", engine)
        (w,) = _warn_containing(res, "dropped, with no /DYNAIN slot")
        for cell in ("NHSV=3", "FTYPE=2", "FTENSR=4", "NTHHSV=5",
                     "RFLAG=6", "INTSTRN=9"):
            self.assertIn(cell, w)

    def test_two_cards_merge_into_one_block(self):
        """/DYNAIN is a GLOBAL engine request, so two cards become one block.

        For TWO PART-SCOPED blocks the engine is additive by accident —
        fredynain.F initialises NDYNAINPRT once (:89), zeroes it only in the
        /ALL branch (:109) and APPENDS every id in the part branch (:123/:124)
        — and only the earlier block's Tstart/Tfreq is lost (:103 overwrites
        them per block). The union with ONE schedule is therefore what the
        engine would have done anyway; the ORDER-DEPENDENT case is the MIXED
        one (next test), and the warning must not claim it here."""
        parts = "*PART\np3\n" + _row(3, 2, 1) + "\n"
        shells = "*ELEMENT_SHELL\n" + _row(303, 3, 1, 2, 3, 4) + "\n"
        deck = MESH.replace("{EXTRA}",
                            parts + shells
                            + "*SET_PART_LIST\n" + _row(950) + "\n"
                            + _row(2) + "\n"
                            + "*SET_PART_LIST\n" + _row(951) + "\n"
                            + _row(3) + "\n"
                            + "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n"
                            + "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(951, 0, 0, "", 0, 0, 0, 0) + "\n")
        res, _starter, engine = _convert(deck)
        self.assertEqual(engine.count("/DYNAIN/DT"), 1)
        lines = engine.splitlines()
        i = lines.index("/DYNAIN/DT")
        self.assertEqual(lines[i + 2].split(), ["2", "3"])
        self.assertEqual(lines[i + 3], "/DYNAIN/SHELL/STRES/FULL")
        (w,) = _warn_containing(res, "were merged into ONE /DYNAIN")
        # The two part-scoped blocks would have UNIONED, not raced: naming the
        # order-dependence as this pair's consequence over-states the loss.
        self.assertIn("Two PART-SCOPED blocks are additive", w)
        self.assertIn("only the EARLIER block's Tstart/Tfreq is lost", w)
        self.assertNotIn("So one of the two cards would have been silently "
                         "ignored", w)

    def test_an_all_parts_card_widens_the_merge(self):
        deck = MESH.replace("{EXTRA}",
                            "*SET_PART_LIST\n" + _row(950) + "\n"
                            + _row(2) + "\n"
                            + "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n"
                            + "*INTERFACE_SPRINGBACK_LSDYNA\n"
                            + _row(0, 0, 0, "", 0, 0, 0, 0) + "\n")
        res, _starter, engine = _convert(deck)
        self.assertEqual(engine.count("/DYNAIN/DT"), 1)
        self.assertIn("/DYNAIN/DT/ALL", engine)
        self.assertTrue(_warn_containing(res, "widens the scope"))

    def test_the_file_count_matches_the_schedule(self):
        """0.9 ENDTIM every 0.02 ENDTIM fires at 0.90, 0.92, ..., 1.00 = SIX
        triggers; int((1-0.9)/0.02) is 4 in IEEE-754, not 5."""
        deck = MESH.replace("{EXTRA}", SPRINGBACK)
        res, _starter, _engine = _convert(deck)
        (w,) = _warn_containing(res, "at most")
        self.assertIn("at most 6 files", w)

    def test_the_capture_is_described_as_a_schedule(self):
        """GENDYNAIN fires on TT >= TDYNAIN from an output pass, so the newest
        file can precede termination by up to one interval."""
        deck = MESH.replace("{EXTRA}", SPRINGBACK)
        res, _starter, _engine = _convert(deck)
        (w,) = _warn_containing(res, "TAKE THE HIGHEST-NUMBERED ONE")
        self.assertIn("can precede termination by up to 0.0002", w)
        self.assertNotIn("it is the last computed state", w)

    def test_zero_endtim_emits_nothing(self):
        deck = (MESH
                .replace("*CONTROL_TERMINATION\n     0.010\n", "")
                .replace("{EXTRA}", SPRINGBACK))
        res, _starter, engine = _convert(deck)
        self.assertNotIn("/DYNAIN", engine)
        self.assertTrue(_warn_containing(res, "*CONTROL_TERMINATION"))

    def test_optcard_and_node_cards_are_read_and_named(self):
        """The card after card 1 is an optional card ONLY when the literal
        string OPTCARD occupies the first column (Vol I R17 p.30-80);
        otherwise it is the first Card-4 node row."""
        deck = MESH.replace(
            "{EXTRA}",
            "*SET_PART_LIST\n" + _row(950) + "\n" + _row(2) + "\n"
            "*INTERFACE_SPRINGBACK_LSDYNA\n"
            + _row(950, 4, 1, "", 1, 2, 1, 1) + "\n"
            + "OPTCARD".ljust(10) + _row(1, 7, 1, 1, 1, 1) + "\n"
            + _row(1, 7, 7) + "\n")
        res, _starter, engine = _convert(deck)
        self.assertIn("/DYNAIN/DT", engine)
        w = _warn_containing(res, "no /DYNAIN slot")
        self.assertTrue(w)
        for needle in ("NHSV=4", "FTYPE=1", "FTENSR=1", "NTHHSV=2",
                       "RFLAG=1", "INTSTRN=1", "OPTCARD card",
                       "Card-4 node constraint row"):
            self.assertIn(needle, w[0])

    def test_node_card_directly_after_card_one_is_not_an_optcard(self):
        state = _dispatch("*KEYWORD\n*INTERFACE_SPRINGBACK_LSDYNA\n"
                          + _row(1, 0, 0, "", 0, 0, 0, 0) + "\n"
                          + _row(1, 7, 7) + "\n*END\n")
        (rec,) = state.interface_springbacks
        self.assertFalse(rec.has_optcard)
        self.assertEqual(rec.constraints, [(1, 7, 7)])
        self.assertEqual(rec.sldo, 0)

    def test_every_option1_x_option2_spelling_is_dispatched(self):
        """*INTERFACE_SPRINGBACK_OPTION1_{OPTION2} (Vol I R17 p.30-80):
        4 x 2 = EIGHT legal spellings. Enumerated HERE from the manual, not
        from the converter's own table, so a missing corner is visible (the
        EXCLUDE_NOTHICKNESS one was)."""
        spellings = {
            f"INTERFACE_SPRINGBACK_{o1}{o2}"
            for o1 in ("LSDYNA", "NASTRAN", "SEAMLESS", "EXCLUDE")
            for o2 in ("", "_NOTHICKNESS")}
        self.assertEqual(len(spellings), 8)
        for kw in sorted(spellings):
            with self.subTest(kw=kw):
                self.assertIn(kw, HANDLERS)
                # `kw in _RARE_CARD_OFFSETS` is guaranteed by construction
                # (assembly.py fills the table with None for every
                # RARE_CARD_KEYWORDS entry and then KeyErrors on a spelling
                # with no verdict), so assert the VERDICT instead: the two
                # LSDYNA spellings carry the walker, the six warn-drops
                # deliberately carry none — an unmodelled card stack must not
                # have its cells rewritten by position.
                spec = _RARE_CARD_OFFSETS[kw]
                if kw.startswith("INTERFACE_SPRINGBACK_LSDYNA"):
                    self.assertIs(spec, _off_interface_springback)
                else:
                    self.assertIsNone(spec)

    def test_sibling_options_are_recognized_warn_drops(self):
        for kw in ("INTERFACE_SPRINGBACK_NASTRAN",
                   "INTERFACE_SPRINGBACK_NASTRAN_NOTHICKNESS",
                   "INTERFACE_SPRINGBACK_SEAMLESS",
                   "INTERFACE_SPRINGBACK_SEAMLESS_NOTHICKNESS",
                   "INTERFACE_SPRINGBACK_EXCLUDE",
                   "INTERFACE_SPRINGBACK_EXCLUDE_NOTHICKNESS"):
            with self.subTest(kw=kw):
                deck = MESH.replace("{EXTRA}",
                                    f"*{kw}\n"
                                    + _row(0, 0, 0, "", 0, 0, 0, 0) + "\n")
                res, _starter, engine = _convert(deck)
                self.assertNotIn(kw, res.skipped_keywords)
                self.assertIn(kw,
                              [k for k, _r in res.recognized_not_emitted])
                self.assertNotIn("/DYNAIN", engine)

    def test_nothickness_still_converts_and_names_the_difference(self):
        deck = MESH.replace("{EXTRA}", SPRINGBACK.replace(
            "*INTERFACE_SPRINGBACK_LSDYNA\n",
            "*INTERFACE_SPRINGBACK_LSDYNA_NOTHICKNESS\n"))
        res, _starter, engine = _convert(deck)
        self.assertIn("/DYNAIN/DT", engine)
        self.assertTrue(_warn_containing(res, "NOTHICKNESS"))


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch / *INCLUDE_TRANSFORM coverage
# ═════════════════════════════════════════════════════════════════════════════

def _include_transform(tmpdir: str, sub: str, offsets: dict) -> list:
    """Parse a main deck that *INCLUDE_TRANSFORMs *sub* with *offsets*, and
    return the included blocks after the offset pass."""
    main = os.path.join(tmpdir, "main.k")
    subp = os.path.join(tmpdir, "sub.k")
    with open(subp, "w") as fh:
        fh.write(sub)
    card2 = _row(*[offsets.get(k, 0) for k in
                   ("n", "e", "p", "m", "s", "f", "d")])
    with open(main, "w") as fh:
        fh.write("*KEYWORD\n*INCLUDE_TRANSFORM\nsub.k\n"
                 + card2 + "\n" + _row(offsets.get("r", 0)) + "\n*END\n")
    return parse_k_file(main)


class DispatchAndOffsetCoverageTests(unittest.TestCase):

    def test_one_source_covers_handlers_and_offsets(self):
        """#116: a spelling the handler reads and the offsetter does not know
        keeps its original ids while the rest of the include moves."""
        self.assertTrue(RARE_CARD_KEYWORDS)
        self.assertEqual(set(RARE_CARD_KEYWORDS), set(_RARE_CARD_OFFSETS))
        for kw, spec in _RARE_CARD_OFFSETS.items():
            self.assertIn(kw, HANDLERS, f"{kw} has no handler")
            if spec is None:
                self.assertNotIn(kw, _OFFSET_SPECS,
                                 f"{kw} is warn-dropped but offset anyway")
            else:
                self.assertIn(kw, _OFFSET_SPECS, f"{kw} has no offset spec")

    def test_all_eight_element_death_spellings_are_registered(self):
        for fam in ("SOLID", "BEAM", "SHELL", "THICK_SHELL"):
            for suffix in ("", "_SET"):
                kw = f"DEFINE_ELEMENT_DEATH_{fam}{suffix}"
                with self.subTest(kw=kw):
                    self.assertIn(kw, RARE_CARD_KEYWORDS)
                    self.assertIn(kw, _OFFSET_SPECS)

    def test_element_death_buckets(self):
        """EID -> IDEOFF, SID -> IDSOFF, BOXID/CID -> IDDOFF; IDGRP is a bare
        grouping tag and is deliberately left alone."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*DEFINE_ELEMENT_DEATH_SOLID\n"
                + _row(101, 0.003, 55, 1, 9, 7, 40.0) + "\n"
                "*DEFINE_ELEMENT_DEATH_SHELL_SET\n"
                + _row(700, 0.004, 55, 0, 9, 7) + "\n*END\n",
                {"e": 1000, "s": 2000, "d": 300})
            plain = [b for b in blocks
                     if b.keyword == "DEFINE_ELEMENT_DEATH_SOLID"][0]
            setb = [b for b in blocks
                    if b.keyword == "DEFINE_ELEMENT_DEATH_SHELL_SET"][0]
        f = [plain.raw[0][i:i + 10].strip() for i in range(0, 70, 10)]
        self.assertEqual(f[0], "1101")          # EID + IDEOFF
        self.assertEqual(f[2], "355")           # BOXID + IDDOFF
        self.assertEqual(f[4], "9")             # IDGRP untouched
        self.assertEqual(f[5], "307")           # CID + IDDOFF
        g = [setb.raw[0][i:i + 10].strip() for i in range(0, 70, 10)]
        self.assertEqual(g[0], "2700")          # SID + IDSOFF

    def test_curve_smooth_lcid_takes_idfoff(self):
        """IDDOFF explicitly EXCLUDES the CURVE options, so a *DEFINE_
        keyword's curve id still moves with IDFOFF."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*DEFINE_CURVE_SMOOTH\n"
                + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n*END\n",
                {"f": 40, "d": 7})
            (b,) = [x for x in blocks if x.keyword == "DEFINE_CURVE_SMOOTH"]
        self.assertEqual(b.raw[0][0:10].strip(), "940")
        self.assertEqual(b.raw[0][10:20].strip(), "0")     # SIDR is a flag

    def test_perturbation_offsets_only_card_one(self):
        """Card 2 is float-bearing on every TYPE; a positional rewrite would
        read a wavelength of 1.5 back as the id 1."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*PERTURBATION_NODE\n"
                + _row(1, 600, 1.0, 7, 0, 55) + "\n"
                + _row(1.0, 1.5, 0.0, 2.5, 0.0, 3.5, 0.0) + "\n*END\n",
                {"s": 2000, "d": 300, "n": 10, "f": 40})
            (b,) = [x for x in blocks if x.keyword == "PERTURBATION_NODE"]
        f = [b.raw[0][i:i + 10].strip() for i in range(0, 60, 10)]
        self.assertEqual(f[1], "2600")          # NSID + IDSOFF
        self.assertEqual(f[5], "355")           # CID + IDDOFF
        self.assertEqual(b.raw[1].strip().split(),
                         ["1.0", "1.5", "0.0", "2.5", "0.0", "3.5", "0.0"])

    def test_perturbation_nsid_zero_is_not_offset(self):
        """NSID = 0 means 'perturb all the nodes in the model'."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*PERTURBATION_NODE\n"
                + _row(8, 0, 1.0, 7, 0, 0) + "\n"
                + _row(0.5, 1.0) + "\n*END\n",
                {"s": 2000})
            (b,) = [x for x in blocks if x.keyword == "PERTURBATION_NODE"]
        self.assertEqual(b.raw[0][10:20].strip(), "0")

    def test_final_geometry_nid_sign_selects_the_bucket(self):
        """One cell, two id namespaces by SIGN (#125): NID > 0 is a node,
        NID < 0 is |NID| as a *SET_NODE."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                + _row(800, 901, 0.006, 0) + "\n"
                + _fgeo_row(9, 25.0, 0.0, 0.0, 902, 0.5) + "\n"
                + _fgeo_row(-600, 0.0, 0.0, 7.5) + "\n*END\n",
                {"n": 10, "s": 2000, "f": 40, "r": 5000})
            (b,) = [x for x in blocks
                    if x.keyword == "BOUNDARY_PRESCRIBED_FINAL_GEOMETRY"]
        c1 = [b.raw[0][i:i + 10].strip() for i in range(0, 40, 10)]
        self.assertEqual(c1[0], "5800")         # BPFGID + IDROFF
        self.assertEqual(c1[1], "941")          # LCIDF + IDFOFF
        r1 = final_geometry_node_row(b.raw[1], 0)
        self.assertEqual(r1[0], "19")           # NID + IDNOFF
        self.assertEqual(r1[4], "942")          # per-row LCID + IDFOFF
        self.assertEqual(r1[1:4], ["25.0", "0.0", "0.0"])
        self.assertEqual(r1[5], "0.5")
        r2 = final_geometry_node_row(b.raw[2], 0)
        self.assertEqual(r2[0], "-2600")        # |NID| + IDSOFF, sign kept
        self.assertEqual(r2[3], "7.5")

    def test_final_geometry_free_format_rows_survive(self):
        """A comma row is rewritten in its own format, and an id that outgrows
        its I8 column falls back to the comma form rather than shifting every
        later cell (#125)."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                + _row(800, 901, 0.006, 0) + "\n"
                + "9,25.0,0.0,0.0,902,0.5\n"
                + _fgeo_row(10, 25.0, 10.0, 0.0) + "\n*END\n",
                {"n": 999999999, "f": 40, "r": 5000})
            (b,) = [x for x in blocks
                    if x.keyword == "BOUNDARY_PRESCRIBED_FINAL_GEOMETRY"]
        r1 = final_geometry_node_row(b.raw[1], 0)
        self.assertEqual(r1[0], "1000000008")
        self.assertEqual(r1[4], "942")
        self.assertEqual(r1[1:4], ["25.0", "0.0", "0.0"])
        # the fixed row's id no longer fits I8 -> comma form, no cell shift
        r2 = final_geometry_node_row(b.raw[2], 0)
        self.assertEqual(r2[0], "1000000009")
        self.assertEqual([float(v) for v in r2[1:4]], [25.0, 10.0, 0.0])

    def test_a_commented_node_row_offsets_like_any_other(self):
        """parse_k_file strips a trailing '$...' from every Block.raw line, so
        the comment is gone before either walker sees the card and the offset
        pass has nothing extra to preserve. Pinned because a reviewer read the
        strip inside final_geometry_node_row as a walker-local loss."""
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
                + _row(800, 901, 0.006, 0) + "\n"
                + _fgeo_row(9, 25.0, 0.0, 0.0) + "  $ punch corner\n"
                + "10,25.0,10.0,0.0 $ die corner\n*END\n",
                {"n": 10, "f": 40, "r": 5000})
            (b,) = [x for x in blocks
                    if x.keyword == "BOUNDARY_PRESCRIBED_FINAL_GEOMETRY"]
        self.assertNotIn("$", "".join(b.raw))
        r1 = final_geometry_node_row(b.raw[1], 0)
        self.assertEqual(r1[0], "19")
        self.assertEqual(r1[1:4], ["25.0", "0.0", "0.0"])
        r2 = final_geometry_node_row(b.raw[2], 0)
        self.assertEqual(r2[0], "20")
        self.assertEqual([float(v) for v in r2[1:4]], [25.0, 10.0, 0.0])

    def test_springback_offsets_psid_and_node_rows(self):
        with tempfile.TemporaryDirectory() as td:
            blocks = _include_transform(
                td,
                "*KEYWORD\n*INTERFACE_SPRINGBACK_LSDYNA\n"
                + _row(950, 0, 0, "", 0, 0, 0, 0) + "\n"
                + "OPTCARD".ljust(10) + _row(1, 7, 1, 1, 1, 1) + "\n"
                + _row(3, 7, 7) + "\n*END\n",
                {"s": 2000, "n": 10})
            (b,) = [x for x in blocks
                    if x.keyword == "INTERFACE_SPRINGBACK_LSDYNA"]
        self.assertEqual(b.raw[0][0:10].strip(), "2950")
        self.assertTrue(b.raw[1].startswith("OPTCARD"))
        self.assertEqual(b.raw[1][10:20].strip(), "1")      # SLDO untouched
        self.assertEqual(b.raw[2][0:10].strip(), "13")      # NID + IDNOFF


# ═════════════════════════════════════════════════════════════════════════════
# Whole-deck invariants
# ═════════════════════════════════════════════════════════════════════════════

class DeckInvariantTests(unittest.TestCase):

    ALL_FIVE = (
        "*SET_SHELL_LIST\n" + _row(700) + "\n" + _row(201, 202) + "\n"
        "*SET_NODE_LIST\n" + _row(600) + "\n" + _row(1, 2, 3) + "\n"
        "*DEFINE_ELEMENT_DEATH_SOLID\n" + _row(101, 0.003) + "\n"
        "*DEFINE_ELEMENT_DEATH_SHELL_SET\n" + _row(700, 0.004) + "\n"
        "*DEFINE_CURVE_SMOOTH_TITLE\ntool\n"
        + _row(900, 0, 9.0, 0.0, 0.03, 0.005, 0.0) + "\n"
        + SMOOTH_CONSUMER
        + "*PERTURBATION_NODE\n" + _row(8, 600, 2.0, 7, 0, 0) + "\n"
        + _row(0.5, 1.0) + "\n"
        + RAMP
        + "*BOUNDARY_PRESCRIBED_FINAL_GEOMETRY\n"
        + _row(800, 901, 0.006, 0) + "\n"
        + _fgeo_row(9, 25.0, 0.0, 0.0) + "\n"
        + SPRINGBACK
    )

    def test_all_five_convert_together_and_the_mesh_survives(self):
        deck = MESH.replace("{EXTRA}", self.ALL_FIVE)
        res, starter, engine = _convert(deck)
        self.assertEqual(res.skipped_keywords, [])
        self.assertEqual(len(_headers(starter, "/ACTIV/")), 2)
        self.assertTrue(_headers(starter, "/FUNCT_SMOOTH/900"))
        self.assertTrue(_headers(starter, "/RANDOM/GRNOD/600"))
        self.assertTrue(_headers(starter, "/IMPDISP/FGEO/800"))
        self.assertIn("/DYNAIN/DT", engine)
        # mesh survival
        self.assertEqual(len(_data_rows(starter, "/BRICK/1")), 1)
        shell_ids = [int(ln[0:10]) for ln in _data_rows(starter, "/SHELL/2")]
        sh3n_ids = [int(ln[0:10]) for ln in _data_rows(starter, "/SH3N/2")]
        self.assertEqual(shell_ids, [201])
        self.assertEqual(sh3n_ids, [202])
        self.assertEqual(len(_data_rows(starter, "/NODE")), 11)

    def test_a_deck_without_these_keywords_is_unchanged(self):
        """Every new section is a no-op that draws NO id on a deck without its
        keyword, so it cannot shift an existing deck's id stream (the #119
        fixture rule)."""
        plain = MESH.replace("{EXTRA}", "")
        _r1, starter_a, engine_a = _convert(plain)
        _r2, starter_b, engine_b = _convert(plain)
        self.assertEqual(starter_a, starter_b)
        self.assertEqual(engine_a, engine_b)
        for card in ("/ACTIV", "/FUNCT_SMOOTH", "/RANDOM", "/IMPDISP/FGEO"):
            self.assertNotIn(card, starter_a)
        self.assertNotIn("/DYNAIN", engine_a)
        self.assertNotIn("/STATE", engine_a)

    def test_group_and_card_ids_do_not_collide(self):
        deck = MESH.replace("{EXTRA}", self.ALL_FIVE)
        _res, starter, _eng = _convert(deck)
        ids = []
        for prefix in ("/GRBRIC/BRIC/", "/GRSHEL/SHEL/", "/GRSH3N/SH3N/",
                       "/GRSPRI/SPRI/", "/GRBEAM/BEAM/", "/ACTIV/",
                       "/IMPDISP/FGEO/"):
            ids += [int(ln.rsplit("/", 1)[1])
                    for ln in _headers(starter, prefix)]
        self.assertEqual(len(ids), len(set(ids)), sorted(ids))


if __name__ == "__main__":
    unittest.main()
